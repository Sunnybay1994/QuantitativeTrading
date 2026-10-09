"""M4 A-share rule adapter (intent evaluation)."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal

from quant.domain import ExecutionRejectReason, OrderSide
from quant.domain.enums import Currency, Market
from quant.execution.contracts import (
    OrderIntent,
    PositionBalance,
    RuleDecision,
    SymbolMarketState,
    build_order_intent,
    build_position_balance,
    build_rule_decision,
    build_symbol_market_state,
)

from quant.backtest.a_share_execution_formal_facts import _canonical_json_bytes
from quant.backtest.a_share_execution_matching import (
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    resolve_a_share_order_quantity_rule,
)

_A_SHARE_RULE_HASH_VERSION = "a-share-rule-hash-v1"
_A_SHARE_RULE_ACCEPTED = "ACCEPTED"
_A_SHARE_RULE_INPUT_INVALID = "A_SHARE_RULE_INPUT_INVALID"


class AShareRuleInputError(ValueError):
    """Typed M4 A-share rule contract failure with a stable message code."""


@dataclass(frozen=True, slots=True)
class AShareRuleConfig:
    """Versioned selector window for the pure A-share rule adapter."""

    rule_identity: str
    selector: str
    effective_from: dt.date
    effective_to: dt.date | None

    def __post_init__(self) -> None:
        if (
            type(self.selector) is not str
            or not self.selector
            or any(ord(char) < 32 or ord(char) == 127 for char in self.selector)
            or "/" in self.selector
            or "\\" in self.selector
            or "://" in self.selector
            or self.selector.startswith("~")
            or (len(self.selector) >= 2 and self.selector[1] == ":")
            or type(self.effective_from) is not dt.date
            or self.effective_to is not None
            and type(self.effective_to) is not dt.date
            or self.effective_to is not None
            and self.effective_to < self.effective_from
            or type(self.rule_identity) is not str
            or len(self.rule_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.rule_identity)
            or self.rule_identity
            != _a_share_rule_config_identity(
                selector=self.selector,
                effective_from=self.effective_from,
                effective_to=self.effective_to,
            )
        ):
            raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)


def _a_share_rule_config_identity(
    *, selector: str, effective_from: dt.date, effective_to: dt.date | None
) -> str:
    envelope = {
        "hash_version": _A_SHARE_RULE_HASH_VERSION,
        "type": "AShareRuleConfig",
        "payload": {
            "effective_from": effective_from,
            "effective_to": effective_to,
            "selector": selector,
        },
    }
    return hashlib.sha256(_canonical_json_bytes(envelope)).hexdigest()


def build_a_share_rule_config(
    *, selector: str, effective_from: dt.date, effective_to: dt.date | None
) -> AShareRuleConfig:
    """Build a strict rule config whose identity is package-computed."""
    try:
        identity = _a_share_rule_config_identity(
            selector=selector,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        return AShareRuleConfig(identity, selector, effective_from, effective_to)
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None


def _prove_a_share_rule_inputs(
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    rule_config: AShareRuleConfig,
) -> tuple[OrderIntent, SymbolMarketState, PositionBalance | None, AShareRuleConfig]:
    try:
        if type(intent) is not OrderIntent or type(state) is not SymbolMarketState:
            raise ValueError
        if position is not None and type(position) is not PositionBalance:
            raise ValueError
        if type(rule_config) is not AShareRuleConfig:
            raise ValueError
        proven_intent = build_order_intent(
            plan_id=intent.plan_id,
            symbol=intent.symbol,
            market=intent.market,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            quote_currency=intent.quote_currency,
            session_date=intent.session_date,
            generated_at=intent.generated_at,
            target_identity=intent.target_identity,
            market_snapshot_id=intent.market_snapshot_id,
            account_snapshot_id=intent.account_snapshot_id,
            config_identity=intent.config_identity,
            connect_route=intent.connect_route,
        )
        proven_state = build_symbol_market_state(
            symbol=state.symbol,
            market=state.market,
            session_date=state.session_date,
            quote_currency=state.quote_currency,
            reference_price=state.reference_price,
            limit_up=state.limit_up,
            limit_down=state.limit_down,
            suspended=state.suspended,
            board_lot=state.board_lot,
            tick_size=state.tick_size,
            rule_version=state.rule_version,
        )
        proven_position = (
            None
            if position is None
            else build_position_balance(
                symbol=position.symbol,
                market=position.market,
                quantity=position.quantity,
                sellable_quantity=position.sellable_quantity,
                avg_cost=position.avg_cost,
            )
        )
        proven_config = build_a_share_rule_config(
            selector=rule_config.selector,
            effective_from=rule_config.effective_from,
            effective_to=rule_config.effective_to,
        )
        if (
            proven_intent != intent
            or proven_state != state
            or proven_position != position
            or proven_config != rule_config
        ):
            raise ValueError
        return proven_intent, proven_state, proven_position, proven_config
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None


def _a_share_rule_reject(
    reason: ExecutionRejectReason, selector: str
) -> RuleDecision:
    return build_rule_decision(
        accepted=False,
        code=reason.value,
        normalized_quantity=0,
        normalized_limit_price=Decimal("0"),
        rule_version=selector,
    )


def _a_share_tick_multiple(price: Decimal, tick: Decimal) -> bool:
    """Check an exact decimal multiple without depending on Decimal context."""
    price_parts, tick_parts = price.as_tuple(), tick.as_tuple()
    if type(price_parts.exponent) is not int or type(tick_parts.exponent) is not int:
        return False
    price_coeff = int("".join(str(item) for item in price_parts.digits))
    tick_coeff = int("".join(str(item) for item in tick_parts.digits))
    if price_coeff <= 0 or tick_coeff <= 0:
        return False
    exponent_delta = price_parts.exponent - tick_parts.exponent
    if exponent_delta >= 0:
        return price_coeff * 10**exponent_delta % tick_coeff == 0
    return price_coeff % (tick_coeff * 10 ** (-exponent_delta)) == 0


def evaluate_a_share_intent(
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    rule_config: AShareRuleConfig,
) -> RuleDecision:
    """Evaluate a send-ready A-share limit intent using the shared G7 rules."""
    intent, state, position, rule_config = _prove_a_share_rule_inputs(
        intent, state, position, rule_config
    )
    if (
        intent.market not in {Market.SH, Market.SZ}
        or intent.quote_currency is not Currency.CNY
        or intent.connect_route is not None
        or state.market is not intent.market
        or state.quote_currency is not Currency.CNY
        or state.symbol != intent.symbol
        or state.session_date != intent.session_date
        or position is not None
        and (position.market is not intent.market or position.symbol != intent.symbol)
    ):
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)

    selector = rule_config.selector
    session = intent.session_date
    if session < rule_config.effective_from or (
        rule_config.effective_to is not None and session > rule_config.effective_to
    ):
        return _a_share_rule_reject(ExecutionRejectReason.RULE_NOT_EFFECTIVE, selector)
    if state.rule_version != selector:
        return _a_share_rule_reject(
            ExecutionRejectReason.RULE_VERSION_MISMATCH, selector
        )

    try:
        quantity_rule = resolve_a_share_order_quantity_rule(
            symbol=intent.symbol, date=session
        )
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None
    if state.board_lot != quantity_rule.buy_min_quantity:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)
    if state.suspended:
        return _a_share_rule_reject(ExecutionRejectReason.SUSPENDED, selector)

    if intent.side is OrderSide.BUY:
        valid_quantity = largest_valid_buy_quantity(
            requested_quantity=intent.quantity, rule=quantity_rule
        )
    elif intent.side is OrderSide.SELL:
        if position is None or intent.quantity > position.sellable_quantity:
            return _a_share_rule_reject(ExecutionRejectReason.T_PLUS_ONE, selector)
        valid_quantity = largest_valid_sell_quantity(
            requested_quantity=intent.quantity,
            position_quantity=position.quantity,
            rule=quantity_rule,
        )
    else:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)
    if valid_quantity != intent.quantity:
        return _a_share_rule_reject(ExecutionRejectReason.LOT_CONSTRAINT, selector)

    if state.limit_up is None or state.limit_down is None:
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_BAND_MISSING, selector)
    if not _a_share_tick_multiple(intent.limit_price, state.tick_size):
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_TICK_INVALID, selector)
    if intent.side is OrderSide.BUY and intent.limit_price >= state.limit_up:
        return _a_share_rule_reject(ExecutionRejectReason.BUY_AT_UPPER_LIMIT, selector)
    if intent.side is OrderSide.SELL and intent.limit_price <= state.limit_down:
        return _a_share_rule_reject(ExecutionRejectReason.SELL_AT_LOWER_LIMIT, selector)
    if not state.limit_down <= intent.limit_price <= state.limit_up:
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_OUT_OF_RANGE, selector)
    return build_rule_decision(
        accepted=True,
        code=_A_SHARE_RULE_ACCEPTED,
        normalized_quantity=intent.quantity,
        normalized_limit_price=intent.limit_price,
        rule_version=selector,
    )

