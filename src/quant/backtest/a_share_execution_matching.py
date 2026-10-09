"""Informal A-share target-to-order matching."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction
from typing import Literal, cast

import polars as pl

from quant.domain import (
    AShareBoard,
    ExecutionRejectReason,
    OrderSide,
    TargetWeightSchema,
)
from quant.research.m3.contracts import AShareCostPeriod

from quant.backtest.a_share_execution_contracts import (
    AccountPosition,
    AShareOrderQuantityRule,
    BuyAllocation,
    ExecutionBatch,
    ExecutionFill,
    ExecutionRejection,
    PositionBook,
    TargetOrderIntent,
)
from quant.backtest.a_share_execution_fees import (
    _fee_total,
    compute_a_share_fee_components,
)

_RULE_VERSION: Literal["sse_szse_limit_order_quantity_v1"] = (
    "sse_szse_limit_order_quantity_v1"
)
_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.01")
def resolve_a_share_order_quantity_rule(
    *, symbol: str, date: dt.date
) -> AShareOrderQuantityRule:
    if type(symbol) is not str or type(date) is not dt.date:
        raise ValueError("A-share rule lookup invalid")
    prefix, suffix = symbol[:3], symbol[-3:]
    if len(symbol) != 9 or symbol[6] != ".":
        raise ValueError("A-share symbol invalid")
    if suffix == ".SH" and prefix in {"600", "601", "603", "605"}:
        board = AShareBoard.SSE_MAIN
    elif suffix == ".SH" and prefix in {"688", "689"}:
        if date < dt.date(2019, 7, 22):
            raise ValueError("STAR rule not effective")
        board = AShareBoard.SSE_STAR
    elif suffix == ".SZ" and prefix in {"000", "001", "002", "003"}:
        board = AShareBoard.SZSE_MAIN
    elif suffix == ".SZ" and prefix in {"300", "301"}:
        board = AShareBoard.SZSE_CHINEXT
    else:
        raise ValueError("unsupported A-share board")
    if board is AShareBoard.SSE_STAR:
        return AShareOrderQuantityRule(
            _RULE_VERSION, board, 200, 1, 200, 1, "FULL_BALANCE_BELOW_MIN"
        )
    return AShareOrderQuantityRule(
        _RULE_VERSION, board, 100, 100, 100, 100, "MATCH_POSITION_REMAINDER"
    )
def largest_valid_buy_quantity(
    *, requested_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("quantity rule invalid")
    if requested_quantity < rule.buy_min_quantity:
        return 0
    if rule.board is AShareBoard.SSE_STAR:
        return requested_quantity
    return requested_quantity - requested_quantity % rule.buy_increment


def largest_valid_sell_quantity(
    *, requested_quantity: int, position_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    _validate_quantity(position_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("sell quantity invalid")
    capped_quantity = min(requested_quantity, position_quantity)
    if capped_quantity == position_quantity:
        return capped_quantity
    if rule.board is AShareBoard.SSE_STAR:
        return capped_quantity if capped_quantity >= rule.sell_min_quantity else 0
    round_lot = capped_quantity - capped_quantity % rule.sell_increment
    remainder = position_quantity % rule.sell_increment
    odd_lot = 0
    if remainder and capped_quantity >= remainder:
        odd_lot = capped_quantity - (capped_quantity - remainder) % rule.sell_increment
    return max(round_lot, odd_lot)


def build_target_order_intents(
    *,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    open_states: pl.DataFrame,
    pre_trade_equity: Decimal,
) -> tuple[TargetOrderIntent, ...]:
    if (
        type(date) is not dt.date
        or type(pre_trade_equity) is not Decimal
        or not pre_trade_equity.is_finite()
        or pre_trade_equity <= 0
    ):
        raise ValueError("target intent inputs invalid")
    clean = TargetWeightSchema.validate(targets)
    if clean["as_of"].n_unique() != 1 or clean["symbol"].n_unique() != clean.height:
        raise ValueError("target intent target domain invalid")
    _validate_open_states(open_states, date)
    if len({item.symbol for item in positions}) != len(positions):
        raise ValueError("position book duplicate symbols")
    by_position = {item.symbol: item for item in positions}
    by_open = {cast(str, row["symbol"]): row for row in open_states.iter_rows(named=True)}
    intents: list[TargetOrderIntent] = []
    for row in clean.sort("symbol").iter_rows(named=True):
        symbol = cast(str, row["symbol"])
        if symbol not in by_open:
            raise ValueError("target open state missing")
        rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=date)
        position = by_position.get(symbol)
        current_quantity = 0 if position is None else position.quantity
        weight = Decimal(str(row["weight"]))
        target_notional = weight * pre_trade_equity
        state = by_open[symbol]
        open_value = state["open"]
        if open_value is None or not cast(bool, state["has_open"]):
            current_value = (
                Decimal("0")
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            if target_notional == current_value:
                continue
            side = OrderSide.BUY if target_notional > current_value else OrderSide.SELL
            intents.append(
                TargetOrderIntent(
                    symbol, side, weight, target_notional, None, None, None, rule
                )
            )
            continue
        open_price = Decimal(str(open_value))
        if open_price <= 0:
            raise ValueError("target open price invalid")
        raw = int((target_notional / open_price).to_integral_value(rounding=ROUND_FLOOR))
        target_quantity = (
            0 if weight == 0 else largest_valid_buy_quantity(requested_quantity=raw, rule=rule)
        )
        lot_constrained_buy = (
            weight > 0 and raw > 0 and target_quantity == 0 and current_quantity == 0
        )
        if target_quantity == current_quantity and not lot_constrained_buy:
            continue
        side = (
            OrderSide.BUY
            if target_quantity > current_quantity or lot_constrained_buy
            else OrderSide.SELL
        )
        intents.append(
            TargetOrderIntent(
                symbol=symbol,
                side=side,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=abs(target_quantity - current_quantity),
                quantity_rule=rule,
            )
        )
    return tuple(intents)


def execute_sell_intents(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionBatch:
    """Execute valid sell quantities while preserving T+1 and lot residuals."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.SELL,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    state_by_symbol = _state_map(open_states)
    position_by_symbol = {item.symbol: item for item in positions}
    fills: list[ExecutionFill] = []
    rejections: list[ExecutionRejection] = []
    updated_cash = cash
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = state_by_symbol[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.SELL)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        position = position_by_symbol.get(intent.symbol)
        if position is None:
            raise ValueError("sell position missing")
        requested = intent.requested_quantity
        if requested is None:
            raise ValueError("sell requested quantity unknown with trusted open")
        sellable_cap = min(requested, position.sellable_quantity)
        t1_residual = requested - sellable_cap
        valid = largest_valid_sell_quantity(
            requested_quantity=sellable_cap,
            position_quantity=position.quantity,
            rule=intent.quantity_rule,
        )
        lot_residual = sellable_cap - valid
        open_price = Decimal(str(state["open"]))
        if valid:
            execution_price = _execution_price(
                open_price=open_price,
                side=OrderSide.SELL,
                slippage=cost_period.slippage,
                price_tick=price_tick,
                lower=Decimal(str(state["down_limit"])),
                upper=Decimal(str(state["up_limit"])),
            )
            notional = execution_price * valid
            fees = compute_a_share_fee_components(
                notional=notional,
                side=OrderSide.SELL,
                cost_period=cost_period,
            )
            fill = ExecutionFill(
                symbol=intent.symbol,
                side=OrderSide.SELL,
                quantity=valid,
                reference_open=open_price,
                execution_price=execution_price,
                notional=notional,
                fees=fees,
                slippage_cost=(open_price - execution_price) * valid,
            )
            fills.append(fill)
            updated_cash += notional - _fee_total(fees)
            position_by_symbol[intent.symbol] = AccountPosition(
                symbol=position.symbol,
                quantity=position.quantity - valid,
                sellable_quantity=position.sellable_quantity - valid,
                unsettled_quantity=position.unsettled_quantity,
                mark_price=position.mark_price,
            )
        if t1_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.T_PLUS_ONE,
                quantity=t1_residual,
                open_price=open_price,
            ))
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=open_price,
            ))
    return ExecutionBatch(
        cash=updated_cash,
        positions=tuple(sorted(position_by_symbol.values(), key=lambda item: item.symbol)),
        fills=tuple(fills),
        rejections=tuple(rejections),
    )


def allocate_buy_lots(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> BuyAllocation:
    """Allocate discrete buy quantities by exact Fraction breakpoints."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.BUY,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    states = _state_map(open_states)
    positions_by_symbol = {item.symbol: item for item in positions}
    rejections: list[ExecutionRejection] = []
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]] = []
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = states[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.BUY)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        if intent.requested_quantity is None:
            raise ValueError("buy requested quantity unknown with trusted open")
        desired = largest_valid_buy_quantity(
            requested_quantity=intent.requested_quantity,
            rule=intent.quantity_rule,
        )
        raw_gap_base = max(
            intent.requested_quantity,
            0 if intent.raw_target_quantity is None else intent.raw_target_quantity,
        )
        lot_residual = raw_gap_base - desired
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=Decimal(str(state["open"])),
            ))
        if desired:
            executable.append((intent, state, desired))
    if not executable:
        return BuyAllocation(
            lambda_fraction=None,
            batch=ExecutionBatch(
                cash=cash,
                positions=tuple(sorted(positions, key=lambda item: item.symbol)),
                fills=(),
                rejections=tuple(rejections),
            ),
        )
    breakpoints = {Fraction(0), Fraction(1)}
    for intent, _, desired in executable:
        breakpoints.update(
            Fraction(quantity, desired)
            for quantity in _valid_buy_quantities(desired, intent.quantity_rule)
        )
    chosen = Fraction(0)
    quantities: dict[str, int] = {}
    for candidate in sorted(breakpoints):
        candidate_quantities = {
            intent.symbol: _quantity_at_fraction(
                desired=desired,
                rule=intent.quantity_rule,
                fraction=candidate,
            )
            for intent, _, desired in executable
        }
        if _buy_total_cost(executable, candidate_quantities, cost_period, price_tick) <= cash:
            chosen = candidate
            quantities = candidate_quantities
        else:
            break
    remaining = cash - _buy_total_cost(executable, quantities, cost_period, price_tick)
    while True:
        candidates: list[tuple[Fraction, str, int, Decimal]] = []
        for intent, state, desired in executable:
            current = quantities.get(intent.symbol, 0)
            next_quantity = _next_valid_buy_quantity(
                current=current, desired=desired, rule=intent.quantity_rule
            )
            if next_quantity is None:
                continue
            incremental = _buy_cost(
                intent=intent,
                state=state,
                quantity=next_quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            ) - _buy_cost(
                intent=intent,
                state=state,
                quantity=current,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            candidates.append(
                (Fraction(desired - current, desired), intent.symbol, next_quantity, incremental)
            )
        affordable = [item for item in candidates if item[3] <= remaining]
        if not affordable:
            break
        _, symbol, next_quantity, incremental = sorted(
            affordable, key=lambda item: (-item[0], item[1])
        )[0]
        quantities[symbol] = next_quantity
        remaining -= incremental
    fills: list[ExecutionFill] = []
    for intent, state, desired in executable:
        quantity = quantities.get(intent.symbol, 0)
        if quantity:
            fill = _buy_fill(
                intent=intent,
                state=state,
                quantity=quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            fills.append(fill)
            current_position = positions_by_symbol.get(intent.symbol)
            positions_by_symbol[intent.symbol] = AccountPosition(
                symbol=intent.symbol,
                quantity=quantity
                + (0 if current_position is None else current_position.quantity),
                sellable_quantity=(
                    0
                    if current_position is None
                    else current_position.sellable_quantity
                ),
                unsettled_quantity=quantity
                + (
                    0
                    if current_position is None
                    else current_position.unsettled_quantity
                ),
                mark_price=(
                    fill.execution_price
                    if current_position is None
                    else current_position.mark_price
                ),
            )
        cash_residual = desired - quantity
        if cash_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.CASH_CONSTRAINT,
                quantity=cash_residual,
                open_price=Decimal(str(state["open"])),
            ))
    spent = sum((fill.notional + _fee_total(fill.fees) for fill in fills), Decimal(0))
    return BuyAllocation(
        lambda_fraction=chosen,
        batch=ExecutionBatch(
            cash=cash - spent,
            positions=tuple(
                sorted(positions_by_symbol.values(), key=lambda item: item.symbol)
            ),
            fills=tuple(fills),
            rejections=tuple(rejections),
        ),
    )


def _validate_execution_inputs(
    *,
    intents: tuple[TargetOrderIntent, ...],
    side: OrderSide,
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> None:
    if (
        type(intents) is not tuple
        or any(type(intent) is not TargetOrderIntent or intent.side is not side for intent in intents)
        or len({intent.symbol for intent in intents}) != len(intents)
        or any(type(position) is not AccountPosition for position in positions)
        or len({position.symbol for position in positions}) != len(positions)
        or type(cash) is not Decimal
        or not cash.is_finite()
        or cash < 0
        or type(cost_period) is not AShareCostPeriod
        or type(price_tick) is not Decimal
        or not price_tick.is_finite()
        or price_tick <= 0
    ):
        raise ValueError("execution inputs invalid")
    if not intents:
        return
    dates = open_states.get_column("date").unique()
    if len(dates) != 1:
        raise ValueError("execution open-state date invalid")
    _validate_open_states(open_states, dates.item())
    if {intent.symbol for intent in intents} - set(open_states.get_column("symbol")):
        raise ValueError("execution open state missing")


def _state_map(frame: pl.DataFrame) -> dict[str, dict[str, object]]:
    return {
        cast(str, row["symbol"]): row for row in frame.iter_rows(named=True)
    }


def _blocked_reason(
    *, state: dict[str, object], side: OrderSide
) -> ExecutionRejectReason | None:
    reason = state["reason"]
    if reason in {"MISSING_OPEN", "OPEN_UNKNOWN", "SUSPENDED"}:
        return ExecutionRejectReason(cast(str, reason))
    allowed_field = "buy_allowed" if side is OrderSide.BUY else "sell_allowed"
    if not cast(bool, state[allowed_field]):
        return (
            ExecutionRejectReason.BUY_AT_UPPER_LIMIT
            if side is OrderSide.BUY
            else ExecutionRejectReason.SELL_AT_LOWER_LIMIT
        )
    return None


def _whole_rejection(
    intent: TargetOrderIntent,
    state: dict[str, object],
    reason: ExecutionRejectReason,
) -> ExecutionRejection:
    requested = intent.requested_quantity
    open_value = state["open"]
    rejected_notional = (
        intent.target_notional
        if requested is None or open_value is None
        else Decimal(requested) * Decimal(str(open_value))
    )
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=requested,
        filled_quantity=0,
        rejected_quantity=requested,
        rejected_notional=rejected_notional,
    )


def _quantity_rejection(
    *,
    intent: TargetOrderIntent,
    reason: ExecutionRejectReason,
    quantity: int,
    open_price: Decimal,
) -> ExecutionRejection:
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=quantity,
        filled_quantity=0,
        rejected_quantity=quantity,
        rejected_notional=open_price * quantity,
    )


def _execution_price(
    *,
    open_price: Decimal,
    side: OrderSide,
    slippage: Decimal,
    price_tick: Decimal,
    lower: Decimal,
    upper: Decimal,
) -> Decimal:
    raw = open_price * (
        Decimal(1) + slippage if side is OrderSide.BUY else Decimal(1) - slippage
    )
    rounding = ROUND_CEILING if side is OrderSide.BUY else ROUND_FLOOR
    ticked = (raw / price_tick).to_integral_value(rounding=rounding) * price_tick
    return min(max(ticked, lower), upper)


def _fee_total(fees: AShareFeeComponents) -> Decimal:
    return fees.commission + fees.stamp_tax + fees.transfer_fee


def _valid_buy_quantities(
    desired: int, rule: AShareOrderQuantityRule
) -> tuple[int, ...]:
    if rule.board is AShareBoard.SSE_STAR:
        return tuple(range(rule.buy_min_quantity, desired + 1))
    return tuple(range(rule.buy_min_quantity, desired + 1, rule.buy_increment))


def _quantity_at_fraction(
    *, desired: int, rule: AShareOrderQuantityRule, fraction: Fraction
) -> int:
    cap = (desired * fraction.numerator) // fraction.denominator
    return largest_valid_buy_quantity(requested_quantity=cap, rule=rule)


def _next_valid_buy_quantity(
    *, current: int, desired: int, rule: AShareOrderQuantityRule
) -> int | None:
    if current >= desired:
        return None
    if current == 0:
        candidate = rule.buy_min_quantity
    else:
        candidate = current + rule.buy_increment
    return candidate if candidate <= desired else None


def _buy_fill(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionFill:
    open_price = Decimal(str(state["open"]))
    execution_price = _execution_price(
        open_price=open_price,
        side=OrderSide.BUY,
        slippage=cost_period.slippage,
        price_tick=price_tick,
        lower=Decimal(str(state["down_limit"])),
        upper=Decimal(str(state["up_limit"])),
    )
    notional = execution_price * quantity
    fees = compute_a_share_fee_components(
        notional=notional, side=OrderSide.BUY, cost_period=cost_period
    )
    return ExecutionFill(
        symbol=intent.symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        reference_open=open_price,
        execution_price=execution_price,
        notional=notional,
        fees=fees,
        slippage_cost=(execution_price - open_price) * quantity,
    )


def _buy_cost(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    if quantity == 0:
        return Decimal(0)
    fill = _buy_fill(
        intent=intent,
        state=state,
        quantity=quantity,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    return fill.notional + _fee_total(fill.fees)


def _buy_total_cost(
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
    quantities: dict[str, int],
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    return sum(
        (
            _buy_cost(
                intent=intent,
                state=state,
                quantity=quantities.get(intent.symbol, 0),
                cost_period=cost_period,
                price_tick=price_tick,
            )
            for intent, state, _ in executable
        ),
        Decimal(0),
    )


def _validate_quantity(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("quantity invalid")


def _validate_open_states(frame: pl.DataFrame, date: dt.date) -> None:
    required = [
        "date", "symbol", "open", "has_open", "full_day_suspended",
        "partial_open_status", "has_price_limit", "up_limit", "down_limit",
        "buy_allowed", "sell_allowed", "reason",
    ]
    if (
        set(frame.columns) != set(required)
        or frame["symbol"].n_unique() != frame.height
        or any(day != date for day in frame["date"])
    ):
        raise ValueError("open execution states invalid")

