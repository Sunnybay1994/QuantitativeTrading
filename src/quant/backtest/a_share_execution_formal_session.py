"""Formal A-share session transition execution."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from decimal import ROUND_FLOOR, Decimal, localcontext
from fractions import Fraction
from typing import cast

import polars as pl

from quant.domain import ExecutionRejectReason, OrderSide
from quant.research.m3.contracts import AShareCostPeriod

from quant.backtest.a_share_execution_contracts import (
    AShareExecutionError,
    AShareOrderQuantityRule,
    AccountPosition,
    ExecutionFill,
    ExecutionRejection,
    PositionBook,
    TargetOrderIntent,
)
from quant.backtest.a_share_execution_formal_open import AShareSessionExecutionTransition
from quant.backtest.a_share_execution_formal_facts import (
    FormalAShareMarketFactsIdentityV1,
    VerifiedAShareMarketFacts,
    _FORMAL_EXECUTION_ERROR,
    _HEX64,
)
from quant.backtest.a_share_execution_formal_open import (
    build_formal_a_share_open_execution_states,
    resolve_formal_a_share_order_quantity_rule,
)
from quant.backtest.a_share_execution_fees import _fee_total
from quant.backtest.a_share_execution_formal_decimal import (
    _CENT,
    _FORMAL_HALF_PRICE_TICK,
    _FORMAL_REJECTION_PRIORITY,
    _PRICE_TICK,
    _formal_blocked_reason,
    _formal_buy_cost,
    _formal_buy_quantity_at_fraction,
    _formal_buy_total_cost,
    _formal_decimal,
    _formal_effective_cost_period,
    _formal_fee_components,
    _formal_fill,
    _formal_math_context,
    _formal_multiply,
    _formal_next_buy_breakpoint,
    _formal_positions,
    _formal_previous_buy_breakpoint,
    _formal_quantity_rejection,
    _formal_reference_opens,
    _formal_reference_opens_sha256,
    _formal_rejection_key,
    _formal_subtract,
    _formal_target_rows,
)
from quant.backtest.a_share_execution_formal_open import (
    _state_map,
    _validate_formal_open_execution_frame,
)
from quant.backtest.a_share_execution_matching import (
    _next_valid_buy_quantity,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
)

def _formal_allocate_buys(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: dict[str, dict[str, object]],
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
) -> tuple[Decimal, PositionBook, tuple[ExecutionFill, ...], tuple[ExecutionRejection, ...], Fraction | None]:
    positions_by_symbol = {item.symbol: item for item in positions}
    rejections: list[ExecutionRejection] = []
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]] = []
    for intent in intents:
        state = states[intent.symbol]
        requested = intent.requested_quantity
        raw = intent.raw_target_quantity
        target = intent.target_position_quantity
        if requested is None or raw is None or target is None:
            raise ValueError
        existing_position = positions_by_symbol.get(intent.symbol)
        current_quantity = (
            0 if existing_position is None else existing_position.quantity
        )
        target_delta = max(target - current_quantity, 0)
        desired = largest_valid_buy_quantity(
            requested_quantity=target_delta, rule=intent.quantity_rule
        )
        lot_residual = requested - desired
        if lot_residual < 0:
            raise ValueError
        if target == 0 and intent.target_weight > 0:
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                rejected_notional=intent.target_notional,
            ))
            continue
        blocked = _formal_blocked_reason(state=state, side=OrderSide.BUY)
        if blocked is not None and requested:
            open_price = Decimal(str(state["open"]))
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=blocked,
                quantity=requested,
                rejected_notional=_formal_multiply(open_price, requested),
            ))
            continue
        if lot_residual:
            rejected_notional = _formal_multiply(
                Decimal(str(state["open"])), lot_residual
            )
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                rejected_notional=rejected_notional,
            ))
        if desired:
            executable.append((intent, state, desired))
    if not executable:
        return cash, positions, (), tuple(rejections), None

    full_quantities = {intent.symbol: desired for intent, _, desired in executable}
    full_cost = _formal_buy_total_cost(executable, full_quantities, cost_period)
    if full_cost <= cash:
        chosen = Fraction(1)
        quantities = full_quantities
    else:
        low = Fraction(0)
        high = Fraction(1)
        for _ in range(4096):
            next_breakpoint = _formal_next_buy_breakpoint(
                low=low, executable=executable
            )
            if next_breakpoint is None or next_breakpoint >= high:
                break
            next_quantities = {
                intent.symbol: _formal_buy_quantity_at_fraction(
                    desired=desired,
                    rule=intent.quantity_rule,
                    fraction=next_breakpoint,
                )
                for intent, _, desired in executable
            }
            if _formal_buy_total_cost(
                executable, next_quantities, cost_period
            ) > cash:
                break
            middle = (low + high) / 2
            candidate_quantities = {
                intent.symbol: _formal_buy_quantity_at_fraction(
                    desired=desired,
                    rule=intent.quantity_rule,
                    fraction=middle,
                )
                for intent, _, desired in executable
            }
            if _formal_buy_total_cost(
                executable, candidate_quantities, cost_period
            ) <= cash:
                low = middle
            else:
                high = middle
        else:
            raise ValueError
        chosen = _formal_previous_buy_breakpoint(
            value=low, executable=executable
        )
        quantities = {
            intent.symbol: _formal_buy_quantity_at_fraction(
                desired=desired,
                rule=intent.quantity_rule,
                fraction=chosen,
            )
            for intent, _, desired in executable
        }

    spent = _formal_buy_total_cost(executable, quantities, cost_period)
    remaining = _formal_subtract(cash, spent)
    while True:
        candidates: list[tuple[Fraction, str, int, Decimal]] = []
        for intent, state, desired in executable:
            allocated_quantity = quantities.get(intent.symbol, 0)
            next_quantity = _next_valid_buy_quantity(
                current=allocated_quantity,
                desired=desired,
                rule=intent.quantity_rule,
            )
            if next_quantity is None:
                continue
            incremental = _formal_subtract(_formal_buy_cost(
                intent=intent,
                state=state,
                quantity=next_quantity,
                cost_period=cost_period,
            ), _formal_buy_cost(
                intent=intent,
                state=state,
                quantity=allocated_quantity,
                cost_period=cost_period,
            ))
            candidates.append((
                Fraction(desired - allocated_quantity, desired),
                intent.symbol,
                next_quantity,
                incremental,
            ))
        affordable = [item for item in candidates if item[3] <= remaining]
        if not affordable:
            break
        _, symbol, quantity, incremental = min(
            affordable, key=lambda item: (-item[0], item[1])
        )
        quantities[symbol] = quantity
        remaining = _formal_subtract(remaining, incremental)

    fills: list[ExecutionFill] = []
    for intent, state, desired in executable:
        quantity = quantities.get(intent.symbol, 0)
        if quantity:
            fill = _formal_fill(
                intent=intent,
                state=state,
                quantity=quantity,
                cost_period=cost_period,
            )
            fills.append(fill)
            current = positions_by_symbol.get(intent.symbol)
            positions_by_symbol[intent.symbol] = AccountPosition(
                symbol=intent.symbol,
                quantity=quantity + (0 if current is None else current.quantity),
                sellable_quantity=(
                    0 if current is None else current.sellable_quantity
                ),
                unsettled_quantity=quantity + (
                    0 if current is None else current.unsettled_quantity
                ),
                mark_price=(
                    fill.execution_price if current is None else current.mark_price
                ),
            )
        cash_residual = desired - quantity
        if cash_residual:
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.CASH_CONSTRAINT,
                quantity=cash_residual,
                rejected_notional=_formal_multiply(
                    Decimal(str(state["open"])), cash_residual
                ),
            ))
    return (
        remaining,
        tuple(sorted(positions_by_symbol.values(), key=lambda item: item.symbol)),
        tuple(fills),
        tuple(rejections),
        chosen,
    )


def _formal_build_intents(
    *,
    rows: tuple[dict[str, object], ...],
    positions: PositionBook,
    states: dict[str, dict[str, object]],
    rules: dict[str, AShareOrderQuantityRule],
    pre_trade_equity: Decimal,
) -> tuple[tuple[TargetOrderIntent, ...], tuple[ExecutionRejection, ...]]:
    weights = {
        cast(str, row["symbol"]): Decimal(str(row["weight"])) for row in rows
    }
    positions_by_symbol = {item.symbol: item for item in positions}
    symbols = tuple(sorted(set(weights) | set(positions_by_symbol)))
    intents: list[TargetOrderIntent] = []
    target_diagnostics: list[ExecutionRejection] = []
    context, _ = _formal_math_context()
    try:
        for symbol in symbols:
            weight = weights.get(symbol, Decimal(0))
            target_notional = weight * pre_trade_equity
            position = positions_by_symbol.get(symbol)
            current_quantity = 0 if position is None else position.quantity
            current_value = (
                Decimal(0)
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            state = states[symbol]
            rule = rules[symbol]
            if not cast(bool, state["has_open"]):
                if target_notional == current_value:
                    continue
                side = (
                    OrderSide.BUY
                    if target_notional > current_value
                    else OrderSide.SELL
                )
                intents.append(TargetOrderIntent(
                    symbol=symbol,
                    side=side,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=None,
                    target_position_quantity=None,
                    requested_quantity=None,
                    quantity_rule=rule,
                ))
                reason = _formal_blocked_reason(state=state, side=side)
                if reason is None:
                    raise ValueError
                target_diagnostics.append(ExecutionRejection(
                    symbol=symbol,
                    side=side,
                    reason=reason,
                    requested_quantity=None,
                    filled_quantity=0,
                    rejected_quantity=None,
                    rejected_notional=(target_notional - current_value).copy_abs(),
                ))
                continue

            open_price = Decimal(str(state["open"]))
            raw = int(
                (target_notional / open_price).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            target_quantity = (
                0
                if weight == 0
                else largest_valid_buy_quantity(
                    requested_quantity=raw, rule=rule
                )
            )
            if target_quantity == current_quantity:
                if not (weight > 0 and target_quantity == 0):
                    continue
                intent = TargetOrderIntent(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=raw,
                    target_position_quantity=0,
                    requested_quantity=raw,
                    quantity_rule=rule,
                )
                intents.append(intent)
                continue
            if target_quantity < current_quantity:
                intent = TargetOrderIntent(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=raw,
                    target_position_quantity=target_quantity,
                    requested_quantity=current_quantity - target_quantity,
                    quantity_rule=rule,
                )
                intents.append(intent)
                if weight > 0 and target_quantity == 0:
                    target_diagnostics.append(ExecutionRejection(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        reason=ExecutionRejectReason.LOT_CONSTRAINT,
                        requested_quantity=raw,
                        filled_quantity=0,
                        rejected_quantity=raw,
                        rejected_notional=target_notional,
                    ))
                continue
            requested = raw - current_quantity
            if requested < 0:
                raise ValueError
            intents.append(TargetOrderIntent(
                symbol=symbol,
                side=OrderSide.BUY,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=requested,
                quantity_rule=rule,
            ))
    finally:
        context.__exit__(None, None, None)
    return tuple(intents), tuple(target_diagnostics)


def _formal_execute_sells(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: dict[str, dict[str, object]],
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
) -> tuple[Decimal, PositionBook, tuple[ExecutionFill, ...], tuple[ExecutionRejection, ...]]:
    positions_by_symbol = {item.symbol: item for item in positions}
    fills: list[ExecutionFill] = []
    rejections: list[ExecutionRejection] = []
    updated_cash = cash
    context, _ = _formal_math_context()
    try:
        for intent in intents:
            requested = intent.requested_quantity
            if requested is None:
                raise ValueError
            state = states[intent.symbol]
            blocked = _formal_blocked_reason(state=state, side=OrderSide.SELL)
            open_price = Decimal(str(state["open"]))
            if blocked is not None:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=blocked,
                    quantity=requested,
                    rejected_notional=open_price * requested,
                ))
                continue
            position = positions_by_symbol.get(intent.symbol)
            if position is None:
                raise ValueError
            sellable_cap = min(requested, position.sellable_quantity)
            t1_residual = requested - sellable_cap
            valid = largest_valid_sell_quantity(
                requested_quantity=sellable_cap,
                position_quantity=position.quantity,
                rule=intent.quantity_rule,
            )
            lot_residual = sellable_cap - valid
            if valid:
                fill = _formal_fill(
                    intent=intent,
                    state=state,
                    quantity=valid,
                    cost_period=cost_period,
                )
                fills.append(fill)
                updated_cash += fill.notional - _fee_total(fill.fees)
                remaining_quantity = position.quantity - valid
                if remaining_quantity:
                    positions_by_symbol[intent.symbol] = AccountPosition(
                        symbol=position.symbol,
                        quantity=remaining_quantity,
                        sellable_quantity=position.sellable_quantity - valid,
                        unsettled_quantity=position.unsettled_quantity,
                        mark_price=position.mark_price,
                    )
                else:
                    del positions_by_symbol[intent.symbol]
            if t1_residual:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=ExecutionRejectReason.T_PLUS_ONE,
                    quantity=t1_residual,
                    rejected_notional=open_price * t1_residual,
                ))
            if lot_residual:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=ExecutionRejectReason.LOT_CONSTRAINT,
                    quantity=lot_residual,
                    rejected_notional=open_price * lot_residual,
                ))
    finally:
        context.__exit__(None, None, None)
    return (
        updated_cash,
        tuple(sorted(positions_by_symbol.values(), key=lambda item: item.symbol)),
        tuple(fills),
        tuple(rejections),
    )


def _validate_formal_session_transition(
    transition: AShareSessionExecutionTransition,
) -> None:
    if (
        type(transition.input_market_facts_sha256) is not str
        or _HEX64.fullmatch(transition.input_market_facts_sha256) is None
        or type(transition.date) is not dt.date
        or type(transition.pre_trade_cash) is not Decimal
        or type(transition.pre_trade_equity) is not Decimal
        or type(transition.post_trade_cash) is not Decimal
        or type(transition.base_cost_period) is not AShareCostPeriod
        or type(transition.friction_multiplier) is not Decimal
        or type(transition.effective_cost_period) is not AShareCostPeriod
        or type(transition.reference_opens) is not tuple
        or type(transition.reference_opens_sha256) is not str
        or _HEX64.fullmatch(transition.reference_opens_sha256) is None
        or type(transition.intents) is not tuple
        or type(transition.fills) is not tuple
        or type(transition.rejections) is not tuple
        or transition.buy_allocation_lambda is not None
        and type(transition.buy_allocation_lambda) is not Fraction
    ):
        raise ValueError("formal A-share session transition invalid")
    _formal_decimal(transition.pre_trade_cash)
    _formal_decimal(transition.pre_trade_equity, positive=True)
    _formal_decimal(transition.post_trade_cash)
    pre_positions = _formal_positions(transition.pre_trade_positions)
    post_positions = _formal_positions(transition.post_trade_positions)
    reference_opens = _formal_reference_opens(transition.reference_opens)
    expected_reference_digest = _formal_reference_opens_sha256(reference_opens)
    if not hmac.compare_digest(
        transition.reference_opens_sha256, expected_reference_digest
    ):
        raise ValueError("formal A-share session transition invalid")
    if (
        any(type(item) is not TargetOrderIntent for item in transition.intents)
        or any(type(item) is not ExecutionFill for item in transition.fills)
        or any(type(item) is not ExecutionRejection for item in transition.rejections)
        or any(type(item.symbol) is not str for item in transition.fills)
        or any(
            type(item.symbol) is not str
            or item.reason not in _FORMAL_REJECTION_PRIORITY
            or item.filled_quantity != 0
            or item.requested_quantity != item.rejected_quantity
            for item in transition.rejections
        )
        or len({(item.symbol, item.side) for item in transition.fills})
        != len(transition.fills)
        or len({(item.symbol, item.side, item.reason) for item in transition.rejections})
        != len(transition.rejections)
        or any(
            left.symbol >= right.symbol
            for left, right in zip(transition.intents, transition.intents[1:])
        )
        or tuple(sorted(transition.rejections, key=_formal_rejection_key))
        != transition.rejections
        or transition.buy_allocation_lambda is not None
        and not Fraction(0) <= transition.buy_allocation_lambda <= Fraction(1)
    ):
        raise ValueError("formal A-share session transition invalid")
    effective = _formal_effective_cost_period(
        base=transition.base_cost_period,
        multiplier=transition.friction_multiplier,
        date=transition.date,
    )
    if effective != transition.effective_cost_period:
        raise ValueError("formal A-share session transition invalid")
    reference_open_by_symbol = dict(reference_opens)
    non_null_intent_symbols = {
        item.symbol for item in transition.intents
        if item.requested_quantity is not None
    }
    if set(reference_open_by_symbol) != non_null_intent_symbols:
        raise ValueError("formal A-share session transition invalid")
    side_keys = [
        (0 if fill.side is OrderSide.SELL else 1, fill.symbol)
        for fill in transition.fills
    ]
    if side_keys != sorted(side_keys):
        raise ValueError("formal A-share session transition invalid")

    context, _ = _formal_math_context()
    try:
        marked = transition.pre_trade_cash + sum(
            (
                Decimal(item.quantity) * item.mark_price
                for item in pre_positions
            ),
            Decimal(0),
        )
        if transition.pre_trade_equity < marked:
            raise ValueError
        sell_cash = Decimal(0)
        buy_cash = Decimal(0)
        for fill in transition.fills:
            if (
                fill.reference_open
                != reference_open_by_symbol.get(fill.symbol)
                or
                fill.notional != fill.execution_price * fill.quantity
                or fill.execution_price % _PRICE_TICK != 0
                or fill.fees != _formal_fee_components(
                    notional=fill.notional,
                    side=fill.side,
                    cost_period=effective,
                )
                or fill.slippage_cost != fill.quantity * (
                    fill.reference_open - fill.execution_price
                    if fill.side is OrderSide.SELL
                    else fill.execution_price - fill.reference_open
                )
            ):
                raise ValueError
            amount = fill.notional + _fee_total(fill.fees)
            if fill.side is OrderSide.SELL:
                sell_cash += fill.notional - _fee_total(fill.fees)
            else:
                buy_cash += amount
        if (
            transition.post_trade_cash
            != transition.pre_trade_cash + sell_cash - buy_cash
            or transition.post_trade_cash < 0
        ):
            raise ValueError
    finally:
        context.__exit__(None, None, None)

    expected = {item.symbol: item for item in pre_positions}
    for fill in transition.fills:
        current = expected.get(fill.symbol)
        if fill.side is OrderSide.SELL:
            if current is None or fill.quantity > current.sellable_quantity:
                raise ValueError("formal A-share session transition invalid")
            remaining = current.quantity - fill.quantity
            if remaining:
                expected[fill.symbol] = AccountPosition(
                    symbol=current.symbol,
                    quantity=remaining,
                    sellable_quantity=current.sellable_quantity - fill.quantity,
                    unsettled_quantity=current.unsettled_quantity,
                    mark_price=current.mark_price,
                )
            else:
                del expected[fill.symbol]
        else:
            expected[fill.symbol] = AccountPosition(
                symbol=fill.symbol,
                quantity=fill.quantity + (0 if current is None else current.quantity),
                sellable_quantity=0 if current is None else current.sellable_quantity,
                unsettled_quantity=fill.quantity + (
                    0 if current is None else current.unsettled_quantity
                ),
                mark_price=fill.execution_price if current is None else current.mark_price,
            )
    if tuple(sorted(expected.values(), key=lambda item: item.symbol)) != post_positions:
        raise ValueError("formal A-share session transition invalid")

    intents = {(item.symbol, item.side): item for item in transition.intents}
    fills_by_intent: dict[tuple[str, OrderSide], int] = {}
    for fill in transition.fills:
        key = (fill.symbol, fill.side)
        if key not in intents:
            raise ValueError("formal A-share session transition invalid")
        fills_by_intent[key] = fills_by_intent.get(key, 0) + fill.quantity
    residuals: dict[tuple[str, OrderSide], int] = {}
    target_lot_symbols: set[str] = set()
    null_rejection_keys: set[tuple[str, OrderSide]] = set()
    for rejection in transition.rejections:
        key = (rejection.symbol, rejection.side)
        intent = intents.get(key)
        special = False
        if (
            rejection.side is OrderSide.BUY
            and rejection.reason is ExecutionRejectReason.LOT_CONSTRAINT
        ):
            source = intents.get((rejection.symbol, OrderSide.SELL)) or intent
            special = bool(
                source is not None
                and source.target_weight > 0
                and source.target_position_quantity == 0
                and source.raw_target_quantity is not None
                and rejection.requested_quantity == source.raw_target_quantity
                and rejection.rejected_quantity == source.raw_target_quantity
                and rejection.rejected_notional == source.target_notional
            )
        if special:
            if rejection.symbol in target_lot_symbols:
                raise ValueError("formal A-share session transition invalid")
            target_lot_symbols.add(rejection.symbol)
            continue
        if intent is None:
            raise ValueError("formal A-share session transition invalid")
        if intent.requested_quantity is None:
            if (
                rejection.requested_quantity is not None
                or rejection.rejected_quantity is not None
                or rejection.filled_quantity != 0
                or key in null_rejection_keys
            ):
                raise ValueError("formal A-share session transition invalid")
            position = next(
                (
                    item for item in pre_positions
                    if item.symbol == rejection.symbol
                ),
                None,
            )
            current_value = (
                Decimal(0)
                if position is None
                else _formal_multiply(position.mark_price, position.quantity)
            )
            if rejection.rejected_notional != _formal_subtract(
                intent.target_notional, current_value
            ).copy_abs():
                raise ValueError("formal A-share session transition invalid")
            null_rejection_keys.add(key)
            continue
        if rejection.rejected_quantity is None:
            raise ValueError("formal A-share session transition invalid")
        reference_open = reference_open_by_symbol.get(rejection.symbol)
        if (
            reference_open is None
            or rejection.rejected_notional
            != _formal_multiply(reference_open, rejection.rejected_quantity)
        ):
            raise ValueError("formal A-share session transition invalid")
        residuals[key] = residuals.get(key, 0) + rejection.rejected_quantity
    for key, intent in intents.items():
        if intent.requested_quantity is None:
            if fills_by_intent.get(key, 0) or key not in null_rejection_keys:
                raise ValueError("formal A-share session transition invalid")
            continue
        if (
            intent.side is OrderSide.BUY
            and intent.target_weight > 0
            and intent.target_position_quantity == 0
            and intent.raw_target_quantity == intent.requested_quantity
        ):
            if (
                intent.symbol not in target_lot_symbols
                or fills_by_intent.get(key, 0)
                or residuals.get(key, 0)
            ):
                raise ValueError("formal A-share session transition invalid")
            continue
        if (
            fills_by_intent.get(key, 0) + residuals.get(key, 0)
            != intent.requested_quantity
        ):
            raise ValueError("formal A-share session transition invalid")
    for intent in transition.intents:
        if (
            intent.side is OrderSide.SELL
            and intent.target_weight > 0
            and intent.target_position_quantity == 0
            and intent.symbol not in target_lot_symbols
        ):
            raise ValueError("formal A-share session transition invalid")
    if any(fill.side is OrderSide.BUY for fill in transition.fills) and (
        transition.buy_allocation_lambda is None
    ):
        raise ValueError("formal A-share session transition invalid")


def execute_formal_a_share_session(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    pre_trade_equity: Decimal,
    base_cost_period: AShareCostPeriod,
    friction_multiplier: Decimal,
) -> AShareSessionExecutionTransition:
    """Execute one formal in-memory A-share target-to-account transition."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(targets) is not pl.DataFrame
            or type(positions) is not tuple
            or type(cash) is not Decimal
            or type(pre_trade_equity) is not Decimal
            or type(base_cost_period) is not AShareCostPeriod
            or type(friction_multiplier) is not Decimal
        ):
            raise ValueError
        identity = facts.identity
        if type(identity) is not FormalAShareMarketFactsIdentityV1:
            raise ValueError
        rows = _formal_target_rows(targets, date=date)
        clean_positions = _formal_positions(positions)
        clean_cash = _formal_decimal(cash)
        clean_equity = _formal_decimal(pre_trade_equity, positive=True)
        effective_cost = _formal_effective_cost_period(
            base=base_cost_period, multiplier=friction_multiplier, date=date
        )
        symbols = tuple(sorted(
            {cast(str, row["symbol"]) for row in rows}
            | {item.symbol for item in clean_positions}
        ))
        import sys

        registry = sys.modules.get("quant.backtest.a_share_execution")
        build_open = (
            getattr(registry, "build_formal_a_share_open_execution_states", None)
            if registry is not None
            else None
        )
        open_states = (build_open or build_formal_a_share_open_execution_states)(
            facts=facts, date=date, symbols=symbols
        )
        if _validate_formal_open_execution_frame(open_states) is not open_states:
            raise ValueError
        states = _state_map(open_states)
        if set(states) != set(symbols):
            raise ValueError
        rules = {
            symbol: resolve_formal_a_share_order_quantity_rule(
                facts=facts, date=date, symbol=symbol
            )
            for symbol in symbols
        }
        if any(type(rule) is not AShareOrderQuantityRule for rule in rules.values()):
            raise ValueError
        intents, diagnostics = _formal_build_intents(
            rows=rows,
            positions=clean_positions,
            states=states,
            rules=rules,
            pre_trade_equity=clean_equity,
        )
        sell_intents = tuple(
            item for item in intents if item.side is OrderSide.SELL
        )
        buy_intents = tuple(
            item for item in intents
            if item.side is OrderSide.BUY and item.requested_quantity is not None
        )
        null_rejections = tuple(
            item for item in diagnostics
            if item.requested_quantity is None
        )
        target_diagnostics = tuple(
            item for item in diagnostics
            if item.requested_quantity is not None
        )
        known_sell_intents = tuple(
            item for item in sell_intents if item.requested_quantity is not None
        )
        sell_cash, sell_positions, sell_fills, sell_rejections = (
            _formal_execute_sells(
                intents=known_sell_intents,
                states=states,
                positions=clean_positions,
                cash=clean_cash,
                cost_period=effective_cost,
            )
        )
        (
            post_cash,
            post_positions,
            buy_fills,
            buy_rejections,
            allocation_lambda,
        ) = _formal_allocate_buys(
            intents=buy_intents,
            states=states,
            positions=sell_positions,
            cash=sell_cash,
            cost_period=effective_cost,
        )
        rejections = tuple(sorted(
            sell_rejections
            + null_rejections
            + target_diagnostics
            + buy_rejections,
            key=_formal_rejection_key,
        ))
        reference_opens = tuple(
            (
                intent.symbol,
                Decimal(str(states[intent.symbol]["open"])),
            )
            for intent in intents
            if intent.requested_quantity is not None
        )
        reference_opens_sha256 = _formal_reference_opens_sha256(reference_opens)
        return AShareSessionExecutionTransition(
            input_market_facts_sha256=identity.input_market_facts_sha256,
            date=date,
            pre_trade_cash=clean_cash,
            pre_trade_positions=clean_positions,
            pre_trade_equity=clean_equity,
            base_cost_period=base_cost_period,
            friction_multiplier=friction_multiplier,
            effective_cost_period=effective_cost,
            reference_opens=reference_opens,
            reference_opens_sha256=reference_opens_sha256,
            intents=intents,
            post_trade_cash=post_cash,
            post_trade_positions=post_positions,
            fills=sell_fills + buy_fills,
            rejections=rejections,
            buy_allocation_lambda=allocation_lambda,
        )
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None

