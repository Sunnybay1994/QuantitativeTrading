"""Formal decimal helpers for verified A-share matching."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from fractions import Fraction
from typing import Any, cast

import polars as pl

from quant.domain import ExecutionRejectReason, OrderSide, TargetWeightSchema
from quant.research.m3.contracts import AShareCostPeriod

from quant.backtest.a_share_execution_contracts import (
    AShareFeeComponents,
    AShareOrderQuantityRule,
    AccountPosition,
    ExecutionFill,
    ExecutionRejection,
    PositionBook,
    TargetOrderIntent,
)
from quant.backtest.a_share_execution_fees import _fee_total
from quant.backtest.a_share_execution_matching import (
    _next_valid_buy_quantity,
    largest_valid_buy_quantity,
)

_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.01")
_FORMAL_HALF_PRICE_TICK = Decimal("0.005")

_FORMAL_TARGET_COLUMNS = [
    "as_of", "strategy", "strategy_version", "symbol", "weight",
]
_FORMAL_TARGET_DTYPES = [
    pl.Date, pl.Utf8, pl.Utf8, pl.Utf8, pl.Float64,
]
_FORMAL_REJECTION_PRIORITY = {
    ExecutionRejectReason.SUSPENDED: 0,
    ExecutionRejectReason.OPEN_UNKNOWN: 0,
    ExecutionRejectReason.MISSING_OPEN: 0,
    ExecutionRejectReason.BUY_AT_UPPER_LIMIT: 1,
    ExecutionRejectReason.SELL_AT_LOWER_LIMIT: 1,
    ExecutionRejectReason.T_PLUS_ONE: 2,
    ExecutionRejectReason.LOT_CONSTRAINT: 3,
    ExecutionRejectReason.CASH_CONSTRAINT: 4,
}


def _formal_math_context() -> Any:
    context = localcontext()
    active = context.__enter__()
    active.prec = 80
    active.rounding = ROUND_HALF_UP
    active.Emax = 999999
    active.Emin = -999999
    active.capitals = 1
    active.clamp = 0
    active.clear_flags()
    for signal in active.traps:
        active.traps[signal] = False
    return context, active


def _formal_decimal(value: object, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError
    if value < 0 or positive and value <= 0:
        raise ValueError
    return value


def _formal_add(left: Decimal, right: Decimal) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left + right
    finally:
        context.__exit__(None, None, None)


def _formal_subtract(left: Decimal, right: Decimal) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left - right
    finally:
        context.__exit__(None, None, None)


def _formal_multiply(left: Decimal, right: Decimal | int) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left * right
    finally:
        context.__exit__(None, None, None)


def _formal_positions(positions: PositionBook) -> PositionBook:
    if (
        type(positions) is not tuple
        or any(type(item) is not AccountPosition for item in positions)
        or any(item.quantity <= 0 for item in positions)
        or any(
            left.symbol >= right.symbol
            for left, right in zip(positions, positions[1:])
        )
    ):
        raise ValueError
    return positions


def _formal_reference_opens(
    reference_opens: tuple[tuple[str, Decimal], ...],
) -> tuple[tuple[str, Decimal], ...]:
    if type(reference_opens) is not tuple:
        raise ValueError
    for item in reference_opens:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not Decimal
            or not item[1].is_finite()
            or item[1] <= 0
        ):
            raise ValueError
    if any(
        left[0] >= right[0]
        for left, right in zip(reference_opens, reference_opens[1:])
    ):
        raise ValueError
    return reference_opens


def _formal_decimal_plain_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise ValueError
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    if not result or "e" in result.lower():
        raise ValueError
    return result


def _formal_reference_opens_sha256(
    reference_opens: tuple[tuple[str, Decimal], ...],
) -> str:
    validated = _formal_reference_opens(reference_opens)
    payload = [
        "m3-formal-reference-opens-v1",
        [
            [symbol, _formal_decimal_plain_text(open_price)]
            for symbol, open_price in validated
        ],
    ]
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _formal_target_rows(
    targets: pl.DataFrame, *, date: dt.date
) -> tuple[dict[str, object], ...]:
    if (
        targets.columns != _FORMAL_TARGET_COLUMNS
        or targets.dtypes != _FORMAL_TARGET_DTYPES
        or targets.is_empty()
        or any(targets.get_column(name).null_count() for name in targets.columns)
    ):
        raise ValueError
    validated = TargetWeightSchema.validate(targets)
    if (
        validated.columns != targets.columns
        or validated.dtypes != targets.dtypes
        or not validated.equals(targets)
    ):
        raise ValueError
    rows = tuple(targets.iter_rows(named=True))
    symbols = tuple(row["symbol"] for row in rows)
    if (
        any(type(symbol) is not str for symbol in symbols)
        or any(left >= right for left, right in zip(symbols, symbols[1:]))
    ):
        raise ValueError
    as_of_values = {row["as_of"] for row in rows}
    strategies = {row["strategy"] for row in rows}
    versions = {row["strategy_version"] for row in rows}
    if (
        len(as_of_values) != 1
        or len(strategies) != 1
        or len(versions) != 1
        or any(type(value) is not str or not value for value in strategies | versions)
    ):
        raise ValueError
    as_of = next(iter(as_of_values))
    if type(as_of) is not dt.date or as_of >= date:
        raise ValueError
    weights: list[Decimal] = []
    for row in rows:
        raw = row["weight"]
        if type(raw) is not float:
            raise ValueError
        weight = Decimal(str(raw))
        if not weight.is_finite() or weight < 0:
            raise ValueError
        weights.append(weight)
    context, _ = _formal_math_context()
    try:
        total = sum(weights, Decimal(0))
    finally:
        context.__exit__(None, None, None)
    if not total.is_finite() or total > Decimal(1):
        raise ValueError
    return rows


def _formal_effective_cost_period(
    *, base: AShareCostPeriod, multiplier: Decimal, date: dt.date
) -> AShareCostPeriod:
    if (
        type(base) is not AShareCostPeriod
        or type(multiplier) is not Decimal
        or not multiplier.is_finite()
        or multiplier not in {Decimal("0.5"), Decimal(1), Decimal(2)}
        or base.effective_from > date
        or base.effective_to is not None and date > base.effective_to
    ):
        raise ValueError
    context, _ = _formal_math_context()
    try:
        return AShareCostPeriod(
            effective_from=base.effective_from,
            effective_to=base.effective_to,
            commission_rate=base.commission_rate * multiplier,
            commission_min=base.commission_min * multiplier,
            stamp_tax_sell=base.stamp_tax_sell,
            transfer_fee=base.transfer_fee,
            slippage=base.slippage * multiplier,
        )
    finally:
        context.__exit__(None, None, None)


def _formal_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    context, _ = _formal_math_context()
    try:
        commission = max(
            notional * cost_period.commission_rate,
            cost_period.commission_min,
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        stamp = (
            notional * cost_period.stamp_tax_sell
            if side is OrderSide.SELL
            else Decimal(0)
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        transfer = (notional * cost_period.transfer_fee).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        return AShareFeeComponents(commission, stamp, transfer)
    finally:
        context.__exit__(None, None, None)


def _formal_execution_price(
    *, state: dict[str, object], side: OrderSide, slippage: Decimal
) -> tuple[Decimal, Decimal]:
    open_value = state["open"]
    lower_value = state["down_limit"]
    upper_value = state["up_limit"]
    if any(type(value) is not float for value in (open_value, lower_value, upper_value)):
        raise ValueError
    open_price = Decimal(str(open_value))
    lower = Decimal(str(lower_value))
    upper = Decimal(str(upper_value))
    context, _ = _formal_math_context()
    try:
        raw = open_price * (
            Decimal(1) + slippage
            if side is OrderSide.BUY
            else Decimal(1) - slippage
        )
        rounding = ROUND_CEILING if side is OrderSide.BUY else ROUND_FLOOR
        ticked = (
            (raw / _PRICE_TICK).to_integral_value(rounding=rounding)
            * _PRICE_TICK
        )
        return open_price, min(max(ticked, lower), upper)
    finally:
        context.__exit__(None, None, None)


def _formal_fill(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
) -> ExecutionFill:
    open_price, execution_price = _formal_execution_price(
        state=state, side=intent.side, slippage=cost_period.slippage
    )
    context, _ = _formal_math_context()
    try:
        notional = execution_price * quantity
        fees = _formal_fee_components(
            notional=notional, side=intent.side, cost_period=cost_period
        )
        slippage_cost = quantity * (
            execution_price - open_price
            if intent.side is OrderSide.BUY
            else open_price - execution_price
        )
        return ExecutionFill(
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            reference_open=open_price,
            execution_price=execution_price,
            notional=notional,
            fees=fees,
            slippage_cost=slippage_cost,
        )
    finally:
        context.__exit__(None, None, None)


def _formal_quantity_rejection(
    *,
    intent: TargetOrderIntent,
    reason: ExecutionRejectReason,
    quantity: int,
    rejected_notional: Decimal,
) -> ExecutionRejection:
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=quantity,
        filled_quantity=0,
        rejected_quantity=quantity,
        rejected_notional=rejected_notional,
    )


def _formal_rejection_key(item: ExecutionRejection) -> tuple[int, str, int]:
    return (
        0 if item.side is OrderSide.SELL else 1,
        item.symbol,
        _FORMAL_REJECTION_PRIORITY[item.reason],
    )


def _formal_blocked_reason(
    *, state: dict[str, object], side: OrderSide
) -> ExecutionRejectReason | None:
    raw_reason = state["reason"]
    if raw_reason in {"SUSPENDED", "OPEN_UNKNOWN", "MISSING_OPEN"}:
        return ExecutionRejectReason(cast(str, raw_reason))
    allowed = state["sell_allowed" if side is OrderSide.SELL else "buy_allowed"]
    if type(allowed) is not bool:
        raise ValueError
    if allowed:
        return None
    return (
        ExecutionRejectReason.SELL_AT_LOWER_LIMIT
        if side is OrderSide.SELL
        else ExecutionRejectReason.BUY_AT_UPPER_LIMIT
    )


def _formal_buy_quantity_at_fraction(
    *, desired: int, rule: AShareOrderQuantityRule, fraction: Fraction
) -> int:
    cap = desired * fraction.numerator // fraction.denominator
    return largest_valid_buy_quantity(requested_quantity=cap, rule=rule)


def _formal_next_buy_breakpoint(
    *,
    low: Fraction,
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
) -> Fraction | None:
    result: Fraction | None = None
    for intent, _, desired in executable:
        current = _formal_buy_quantity_at_fraction(
            desired=desired, rule=intent.quantity_rule, fraction=low
        )
        next_quantity = _next_valid_buy_quantity(
            current=current, desired=desired, rule=intent.quantity_rule
        )
        if next_quantity is None:
            continue
        candidate = Fraction(next_quantity, desired)
        result = candidate if result is None else min(result, candidate)
    return result


def _formal_previous_buy_breakpoint(
    *,
    value: Fraction,
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
) -> Fraction:
    result = Fraction(0)
    for intent, _, desired in executable:
        quantity = _formal_buy_quantity_at_fraction(
            desired=desired, rule=intent.quantity_rule, fraction=value
        )
        if quantity:
            result = max(result, Fraction(quantity, desired))
    return result


def _formal_buy_cost(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
) -> Decimal:
    if quantity == 0:
        return Decimal(0)
    fill = _formal_fill(
        intent=intent, state=state, quantity=quantity, cost_period=cost_period
    )
    context, _ = _formal_math_context()
    try:
        return fill.notional + _fee_total(fill.fees)
    finally:
        context.__exit__(None, None, None)


def _formal_buy_total_cost(
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
    quantities: dict[str, int],
    cost_period: AShareCostPeriod,
) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return sum(
            (
                _formal_buy_cost(
                    intent=intent,
                    state=state,
                    quantity=quantities.get(intent.symbol, 0),
                    cost_period=cost_period,
                )
                for intent, state, _ in executable
            ),
            Decimal(0),
        )
    finally:
        context.__exit__(None, None, None)


