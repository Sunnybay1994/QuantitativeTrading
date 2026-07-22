"""港股通日频订单纯内存规则判定（M4-B2 / P0B2）。

不实现 IO、repository、费用、FX、账本或 Gateway；仅消费上游已验证状态。
直接消费 VerifiedConnectMarketContext；connect_open 仅在规则层派生。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from quant.domain.enums import ConnectRoute, Currency, ExecutionRejectReason, Market, OrderSide
from quant.execution.contracts import (
    OrderIntent,
    PositionBalance,
    RuleDecision,
    SymbolMarketState,
    VerifiedConnectMarketContext,
    build_order_intent,
    build_position_balance,
    build_rule_decision,
    build_symbol_market_state,
    build_verified_connect_market_context,
)

_HASH_VERSION = "connect-rule-hash-v1"
_HEX64 = frozenset("0123456789abcdef")
_ACCEPTED = "ACCEPTED"
_INPUT_INVALID = "CONNECT_RULE_INPUT_INVALID"


class ConnectRuleInputError(ValueError):
    """Typed connect-rule input/contract failure; message is a stable code only."""


def _require_non_empty_str(value: object) -> str:
    if type(value) is not str or not value:
        raise ConnectRuleInputError(_INPUT_INVALID)
    return value


def _require_hex64(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ConnectRuleInputError(_INPUT_INVALID)
    return value


def _require_date(value: object) -> dt.date:
    if type(value) is not dt.date:
        raise ConnectRuleInputError(_INPUT_INVALID)
    return value


def _require_route(value: object) -> ConnectRoute:
    if type(value) is not ConnectRoute:
        raise ConnectRuleInputError(_INPUT_INVALID)
    return value


def _require_stable_id(value: object) -> str:
    text = _require_non_empty_str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ConnectRuleInputError(_INPUT_INVALID)
    if "://" in text:
        raise ConnectRuleInputError(_INPUT_INVALID)
    if "/" in text or "\\" in text:
        raise ConnectRuleInputError(_INPUT_INVALID)
    if text.startswith("~") or (len(text) >= 2 and text[1] == ":"):
        raise ConnectRuleInputError(_INPUT_INVALID)
    return text


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        return format(value, "f")
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is bool or value is None or type(value) is int or type(value) is str:
        return value
    raise ConnectRuleInputError(_INPUT_INVALID)


def _sha256_envelope(*, type_name: str, payload: dict[str, object]) -> str:
    envelope = {
        "hash_version": _HASH_VERSION,
        "type": type_name,
        "payload": payload,
    }
    encoded = json.dumps(
        _json_value(envelope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rule_config_payload(
    *,
    selector: str,
    route: ConnectRoute,
    effective_from: dt.date,
    effective_to: dt.date | None,
) -> dict[str, object]:
    return {
        "selector": selector,
        "route": route,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def _rule_config_digest(**payload: Any) -> str:
    return _sha256_envelope(
        type_name="ConnectRuleConfig",
        payload=_rule_config_payload(**payload),
    )


@dataclass(frozen=True, slots=True)
class ConnectRuleConfig:
    """Versioned connect rule selector window; identity is package-computed."""

    rule_identity: str
    selector: str
    route: ConnectRoute
    effective_from: dt.date
    effective_to: dt.date | None

    def __post_init__(self) -> None:
        _require_hex64(self.rule_identity)
        selector = _require_stable_id(self.selector)
        route = _require_route(self.route)
        effective_from = _require_date(self.effective_from)
        if self.effective_to is not None:
            effective_to = _require_date(self.effective_to)
            if effective_to < effective_from:
                raise ConnectRuleInputError(_INPUT_INVALID)
        else:
            effective_to = None
        expected = _rule_config_digest(
            selector=selector,
            route=route,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        if self.rule_identity != expected:
            raise ConnectRuleInputError(_INPUT_INVALID)


def build_connect_rule_config(
    *,
    selector: str,
    route: ConnectRoute,
    effective_from: dt.date,
    effective_to: dt.date | None,
) -> ConnectRuleConfig:
    """Strict ConnectRuleConfig constructor with package-computed identity."""
    digest = _rule_config_digest(
        selector=_require_stable_id(selector),
        route=_require_route(route),
        effective_from=_require_date(effective_from),
        effective_to=None if effective_to is None else _require_date(effective_to),
    )
    return ConnectRuleConfig(
        rule_identity=digest,
        selector=selector,
        route=route,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _raise_input_invalid() -> None:
    raise ConnectRuleInputError(_INPUT_INVALID)


def _prove_order_intent(intent: OrderIntent) -> OrderIntent:
    failure: ConnectRuleInputError | None = None
    rebuilt: OrderIntent | None = None
    try:
        if type(intent) is not OrderIntent:
            raise ValueError("bad type")
        rebuilt = build_order_intent(
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
        if rebuilt != intent:
            raise ValueError("mismatch")
    except Exception:
        failure = ConnectRuleInputError(_INPUT_INVALID)
    if failure is not None:
        raise failure from None
    assert rebuilt is not None
    return rebuilt


def _prove_symbol_market_state(state: SymbolMarketState) -> SymbolMarketState:
    failure: ConnectRuleInputError | None = None
    rebuilt: SymbolMarketState | None = None
    try:
        if type(state) is not SymbolMarketState:
            raise ValueError("bad type")
        rebuilt = build_symbol_market_state(
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
        if rebuilt != state:
            raise ValueError("mismatch")
    except Exception:
        failure = ConnectRuleInputError(_INPUT_INVALID)
    if failure is not None:
        raise failure from None
    assert rebuilt is not None
    return rebuilt


def _prove_position(position: PositionBalance | None) -> PositionBalance | None:
    if position is None:
        return None
    failure: ConnectRuleInputError | None = None
    rebuilt: PositionBalance | None = None
    try:
        if type(position) is not PositionBalance:
            raise ValueError("bad type")
        rebuilt = build_position_balance(
            symbol=position.symbol,
            market=position.market,
            quantity=position.quantity,
            sellable_quantity=position.sellable_quantity,
            avg_cost=position.avg_cost,
        )
        if rebuilt != position:
            raise ValueError("mismatch")
    except Exception:
        failure = ConnectRuleInputError(_INPUT_INVALID)
    if failure is not None:
        raise failure from None
    return rebuilt


def _prove_connect_context(
    context: VerifiedConnectMarketContext,
) -> VerifiedConnectMarketContext:
    failure: ConnectRuleInputError | None = None
    rebuilt: VerifiedConnectMarketContext | None = None
    try:
        if type(context) is not VerifiedConnectMarketContext:
            raise ValueError("bad type")
        rebuilt = build_verified_connect_market_context(
            route=context.route,
            session_date=context.session_date,
            as_of=context.as_of,
            mainland_open=context.mainland_open,
            hong_kong_open=context.hong_kong_open,
            buy_quota_available=context.buy_quota_available,
            calendar_identity=context.calendar_identity,
            quota_identity=context.quota_identity,
            source_identity=context.source_identity,
        )
        if rebuilt != context:
            raise ValueError("mismatch")
    except Exception:
        failure = ConnectRuleInputError(_INPUT_INVALID)
    if failure is not None:
        raise failure from None
    assert rebuilt is not None
    return rebuilt


def _prove_rule_config(rule_config: ConnectRuleConfig) -> ConnectRuleConfig:
    failure: ConnectRuleInputError | None = None
    rebuilt: ConnectRuleConfig | None = None
    try:
        if type(rule_config) is not ConnectRuleConfig:
            raise ValueError("bad type")
        rebuilt = build_connect_rule_config(
            selector=rule_config.selector,
            route=rule_config.route,
            effective_from=rule_config.effective_from,
            effective_to=rule_config.effective_to,
        )
        if rebuilt != rule_config:
            raise ValueError("mismatch")
    except Exception:
        failure = ConnectRuleInputError(_INPUT_INVALID)
    if failure is not None:
        raise failure from None
    assert rebuilt is not None
    return rebuilt


def _reject(code: ExecutionRejectReason, rule_version: str) -> RuleDecision:
    return build_rule_decision(
        accepted=False,
        code=code.value,
        normalized_quantity=0,
        normalized_limit_price=Decimal("0"),
        rule_version=rule_version,
    )


def _accept(intent: OrderIntent, rule_version: str) -> RuleDecision:
    return build_rule_decision(
        accepted=True,
        code=_ACCEPTED,
        normalized_quantity=intent.quantity,
        normalized_limit_price=intent.limit_price,
        rule_version=rule_version,
    )


def _coefficient_int(digits: tuple[int, ...]) -> int:
    value = 0
    for digit in digits:
        value = value * 10 + digit
    return value


def _decimal_ten_valuation(n: int) -> int:
    """Return the exponent of 10 dividing n (min of 2- and 5-adic valuations)."""
    twos = 0
    fives = 0
    while n % 2 == 0:
        n //= 2
        twos += 1
    while n % 5 == 0:
        n //= 5
        fives += 1
    return twos if twos < fives else fives


def _is_tick_multiple(price: Decimal, tick_size: Decimal) -> bool:
    """Exact tick multiple via coefficient/exponent; never uses Decimal arithmetic."""
    price_parts = price.as_tuple()
    tick_parts = tick_size.as_tuple()
    exp_price = price_parts.exponent
    exp_tick = tick_parts.exponent
    if type(exp_price) is not int or type(exp_tick) is not int:
        return False
    coeff_price = _coefficient_int(price_parts.digits)
    coeff_tick = _coefficient_int(tick_parts.digits)
    if coeff_price <= 0 or coeff_tick <= 0:
        return False
    exponent_delta = exp_price - exp_tick
    if exponent_delta >= 0:
        if coeff_tick == 1:
            return True
        return (
            (coeff_price % coeff_tick) * pow(10, exponent_delta, coeff_tick) % coeff_tick
            == 0
        )
    if coeff_price % coeff_tick != 0:
        return False
    return _decimal_ten_valuation(coeff_price // coeff_tick) >= -exponent_delta


def evaluate_connect_intent(
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    connect_context: VerifiedConnectMarketContext,
    rule_config: ConnectRuleConfig,
) -> RuleDecision:
    """Evaluate one HK Connect day-frequency intent against pure in-memory rules."""
    proven_intent = _prove_order_intent(intent)
    proven_state = _prove_symbol_market_state(state)
    proven_position = _prove_position(position)
    proven_context = _prove_connect_context(connect_context)
    proven_config = _prove_rule_config(rule_config)

    if proven_intent.market is not Market.HK or proven_intent.quote_currency is not Currency.HKD:
        _raise_input_invalid()
    if proven_state.market is not Market.HK or proven_state.quote_currency is not Currency.HKD:
        _raise_input_invalid()
    if proven_intent.symbol != proven_state.symbol:
        _raise_input_invalid()
    if proven_intent.session_date != proven_state.session_date:
        _raise_input_invalid()
    if proven_position is not None:
        if (
            proven_position.market is not proven_intent.market
            or proven_position.symbol != proven_intent.symbol
        ):
            _raise_input_invalid()
    if proven_context.route is not proven_config.route:
        _raise_input_invalid()
    if proven_intent.connect_route is not proven_context.route:
        _raise_input_invalid()
    if proven_intent.connect_route is not proven_config.route:
        _raise_input_invalid()
    if proven_context.session_date != proven_intent.session_date:
        _raise_input_invalid()
    if proven_context.as_of > proven_intent.generated_at:
        _raise_input_invalid()

    selector = proven_config.selector
    session = proven_intent.session_date

    if session < proven_config.effective_from or (
        proven_config.effective_to is not None and session > proven_config.effective_to
    ):
        return _reject(ExecutionRejectReason.RULE_NOT_EFFECTIVE, selector)
    if proven_state.rule_version != selector:
        return _reject(ExecutionRejectReason.RULE_VERSION_MISMATCH, selector)

    connect_open = proven_context.mainland_open and proven_context.hong_kong_open
    if not connect_open:
        return _reject(ExecutionRejectReason.CONNECT_CALENDAR_CLOSED, selector)
    if proven_state.suspended:
        return _reject(ExecutionRejectReason.SUSPENDED, selector)

    if proven_intent.side is OrderSide.SELL:
        if proven_position is None or proven_intent.quantity > proven_position.sellable_quantity:
            return _reject(ExecutionRejectReason.INSUFFICIENT_SELLABLE, selector)
    elif proven_intent.side is OrderSide.BUY:
        if not proven_context.buy_quota_available:
            return _reject(ExecutionRejectReason.CONNECT_BUY_QUOTA_UNAVAILABLE, selector)
    else:
        _raise_input_invalid()

    board_lot = proven_state.board_lot
    quantity = proven_intent.quantity
    if proven_intent.side is OrderSide.BUY:
        if quantity % board_lot != 0:
            return _reject(ExecutionRejectReason.CONNECT_BUY_BOARD_LOT_REQUIRED, selector)
    else:
        if quantity > board_lot and quantity % board_lot != 0:
            return _reject(ExecutionRejectReason.CONNECT_SELL_MIXED_LOT, selector)

    if proven_state.limit_up is None or proven_state.limit_down is None:
        return _reject(ExecutionRejectReason.PRICE_BAND_MISSING, selector)
    if not _is_tick_multiple(proven_intent.limit_price, proven_state.tick_size):
        return _reject(ExecutionRejectReason.PRICE_TICK_INVALID, selector)
    if not (
        proven_state.limit_down <= proven_intent.limit_price <= proven_state.limit_up
    ):
        return _reject(ExecutionRejectReason.PRICE_OUT_OF_RANGE, selector)

    return _accept(proven_intent, selector)
