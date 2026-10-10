"""Formal verified A-share open projection and matching core."""

from __future__ import annotations

import datetime as dt
import re
import sys
from collections.abc import Mapping
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, cast

import polars as pl

from quant.domain import (
    AShareBoard,
    ExecutionRejectReason,
    InstrumentType,
    OpenExecutionStateSchema,
    OrderSide,
)
from quant.domain.enums import Currency, Market
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
from quant.backtest.a_share_execution_fees import _fee_total
from quant.backtest.a_share_execution_formal_facts import (
    VerifiedAShareMarketFacts,
    _FORMAL_EXECUTION_ERROR,
    _FORMAL_HALF_PRICE_TICK,
    _HEX64,
    _RULE_VERSION,
    _partial_open_status,
)
from quant.backtest.a_share_execution_matching import (
    _next_valid_buy_quantity,
    _state_map,
    _validate_quantity,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    resolve_a_share_order_quantity_rule,
)

from quant.backtest.a_share_execution_formal_decimal import (
    _FORMAL_REJECTION_PRIORITY,
    _formal_add,
    _formal_blocked_reason,
    _formal_buy_cost,
    _formal_buy_quantity_at_fraction,
    _formal_buy_total_cost,
    _formal_decimal,
    _formal_effective_cost_period,
    _formal_execution_price,
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

_PRICE_TICK = Decimal("0.01")

@dataclass(frozen=True)
class AShareSessionExecutionTransition:
    """Immutable result of one formal A-share execution session."""

    input_market_facts_sha256: str
    date: dt.date
    pre_trade_cash: Decimal
    pre_trade_positions: PositionBook
    pre_trade_equity: Decimal
    base_cost_period: AShareCostPeriod
    friction_multiplier: Decimal
    effective_cost_period: AShareCostPeriod
    reference_opens: tuple[tuple[str, Decimal], ...]
    reference_opens_sha256: str
    intents: tuple[TargetOrderIntent, ...]
    post_trade_cash: Decimal
    post_trade_positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]
    buy_allocation_lambda: Fraction | None

    def __post_init__(self) -> None:
        # Lazy import: validator lives in formal_session to avoid import cycles.
        from quant.backtest.a_share_execution_formal_session import (
            _validate_formal_session_transition,
        )

        _validate_formal_session_transition(self)


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


_OPEN_EXECUTION_FRAME_SCHEMA: Mapping[
    str, pl.DataType | type[pl.DataType]
] = {
    "date": pl.Date,
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "has_open": pl.Boolean,
    "full_day_suspended": pl.Boolean,
    "partial_open_status": pl.Utf8,
    "has_price_limit": pl.Boolean,
    "up_limit": pl.Float64,
    "down_limit": pl.Float64,
    "buy_allowed": pl.Boolean,
    "sell_allowed": pl.Boolean,
    "reason": pl.Utf8,
}


def _formal_execution_frames(
    facts: VerifiedAShareMarketFacts, *, include_limits: bool
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame | None]:
    instruments = facts.instruments
    bars = facts.bars
    suspensions = facts.suspensions
    limits = facts.limits if include_limits else None
    if (
        type(instruments) is not pl.DataFrame
        or type(bars) is not pl.DataFrame
        or type(suspensions) is not pl.DataFrame
        or include_limits
        and type(limits) is not pl.DataFrame
    ):
        raise ValueError
    return instruments, bars, suspensions, limits


def _formal_execution_benchmark(
    facts: VerifiedAShareMarketFacts,
) -> pl.DataFrame:
    _ = facts.identity
    benchmark = facts.benchmark_bars
    if type(benchmark) is not pl.DataFrame:
        raise ValueError
    return benchmark


def _validate_formal_execution_date(
    benchmark: pl.DataFrame, date: dt.date
) -> None:
    benchmark_keys = benchmark.select("benchmark", "trade_date")
    if benchmark_keys.filter(
        pl.col("trade_date") == date
    ).height != 1:
        raise ValueError


def _formal_request_domain(
    *,
    instruments: pl.DataFrame,
    bars: pl.DataFrame,
    suspensions: pl.DataFrame,
    date: dt.date,
    symbol: str,
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    dict[str, object] | None,
    AShareOrderQuantityRule,
]:
    instrument_rows = instruments.select(
        "symbol", "market", "instrument_type", "currency",
        "list_date", "delist_date",
    ).filter(pl.col("symbol") == symbol)
    if instrument_rows.height != 1:
        raise ValueError
    instrument = instrument_rows.row(0, named=True)
    market = instrument["market"]
    expected_suffix = (
        ".SH" if market == Market.SH.value
        else ".SZ" if market == Market.SZ.value
        else None
    )
    list_date = instrument["list_date"]
    delist_date = instrument["delist_date"]
    if (
        instrument["instrument_type"] != InstrumentType.STOCK.value
        or instrument["currency"] != Currency.CNY.value
        or expected_suffix is None
        or not symbol.endswith(expected_suffix)
        or re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) is None
        or type(list_date) is not dt.date
        or delist_date is not None and type(delist_date) is not dt.date
        or date < list_date
        or delist_date is not None and date > delist_date
    ):
        raise ValueError
    quantity_rule = resolve_a_share_order_quantity_rule(
        symbol=symbol, date=date
    )

    bar_rows = bars.select(
        "symbol", "trade_date", "source", "open"
    ).filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == date))
    suspension_rows = suspensions.select(
        "symbol", "trade_date", "source",
        "suspension_scope", "suspension_detail",
    ).filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == date))
    if bar_rows.height > 1 or suspension_rows.height > 1:
        raise ValueError
    bar = None if bar_rows.is_empty() else bar_rows.row(0, named=True)
    suspension = (
        None if suspension_rows.is_empty()
        else suspension_rows.row(0, named=True)
    )
    if (
        bar is not None
        and (type(bar["source"]) is not str or not bar["source"])
        or suspension is not None
        and (
            type(suspension["source"]) is not str
            or not suspension["source"]
            or suspension["suspension_scope"] not in {"FULL_DAY", "PARTIAL"}
        )
    ):
        raise ValueError
    full_day = bool(
        suspension is not None
        and suspension["suspension_scope"] == "FULL_DAY"
    )
    if (bar is None) == (not full_day):
        raise ValueError
    if suspension is not None and not full_day and bar is None:
        raise ValueError
    return instrument, bar, suspension, quantity_rule


def _formal_price(value: object) -> Decimal:
    if type(value) is not float:
        raise ValueError
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError
    return result


def _formal_limit_fields(
    row: dict[str, object] | None,
) -> tuple[bool, float | None, float | None, Decimal | None, Decimal | None]:
    if row is None:
        return False, None, None, None, None
    if type(row["source"]) is not str or not row["source"]:
        raise ValueError
    has_limit = row["has_price_limit"]
    if type(has_limit) is not bool:
        raise ValueError
    if not has_limit:
        if row["up_limit"] is not None or row["down_limit"] is not None:
            raise ValueError
        return False, None, None, None, None
    upper = _formal_price(row["up_limit"])
    lower = _formal_price(row["down_limit"])
    if lower >= upper:
        raise ValueError
    return (
        True,
        cast(float, row["up_limit"]),
        cast(float, row["down_limit"]),
        upper,
        lower,
    )


def _validate_formal_open_execution_frame(frame: pl.DataFrame) -> pl.DataFrame:
    validated = OpenExecutionStateSchema.validate(frame)
    if (
        frame.columns != list(_OPEN_EXECUTION_FRAME_SCHEMA)
        or frame.dtypes != list(_OPEN_EXECUTION_FRAME_SCHEMA.values())
        or validated.columns != frame.columns
        or validated.dtypes != frame.dtypes
        or not validated.equals(frame)
        or frame.height != frame.unique(subset=["date", "symbol"]).height
        or not frame.equals(frame.sort("date", "symbol"))
    ):
        raise ValueError
    return frame


def _build_formal_open_execution_states(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    benchmark = _formal_execution_benchmark(facts)
    _validate_formal_execution_date(benchmark, date)
    if not symbols:
        return _validate_formal_open_execution_frame(
            pl.DataFrame(schema=_OPEN_EXECUTION_FRAME_SCHEMA)
        )
    instruments, bars, suspensions, limits = _formal_execution_frames(
        facts, include_limits=True
    )
    if type(limits) is not pl.DataFrame:
        raise ValueError
    limit_view = limits.select(
        "symbol", "trade_date", "source",
        "has_price_limit", "up_limit", "down_limit",
    )
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        _, bar, suspension, _ = _formal_request_domain(
            instruments=instruments,
            bars=bars,
            suspensions=suspensions,
            date=date,
            symbol=symbol,
        )
        matching_limits = limit_view.filter(
            (pl.col("symbol") == symbol) & (pl.col("trade_date") == date)
        )
        if matching_limits.height > 1:
            raise ValueError
        limit_row = (
            None if matching_limits.is_empty()
            else matching_limits.row(0, named=True)
        )
        has_limit, upper_value, lower_value, upper, lower = (
            _formal_limit_fields(limit_row)
        )
        full_day = bool(
            suspension is not None
            and suspension["suspension_scope"] == "FULL_DAY"
        )
        if full_day:
            rows.append({
                "date": date,
                "symbol": symbol,
                "open": None,
                "has_open": False,
                "full_day_suspended": True,
                "partial_open_status": "NOT_APPLICABLE",
                "has_price_limit": has_limit,
                "up_limit": upper_value,
                "down_limit": lower_value,
                "buy_allowed": False,
                "sell_allowed": False,
                "reason": ExecutionRejectReason.SUSPENDED.value,
            })
            continue
        if bar is None or not has_limit or upper is None or lower is None:
            raise ValueError
        open_value = cast(float, bar["open"])
        open_price = _formal_price(open_value)
        partial_status = "NOT_APPLICABLE"
        reason: str | None = None
        allowed = True
        if suspension is not None:
            registry = sys.modules.get("quant.backtest.a_share_execution")
            partial_fn = (
                getattr(registry, "_partial_open_status", None)
                if registry is not None
                else None
            )
            partial_status = (partial_fn or _partial_open_status)(
                cast(str, suspension["suspension_detail"])
            )
            if partial_status == "SUSPENDED_AT_OPEN":
                allowed = False
                reason = ExecutionRejectReason.SUSPENDED.value
            elif partial_status == "OPEN_UNKNOWN":
                allowed = False
                reason = ExecutionRejectReason.OPEN_UNKNOWN.value
        buy_allowed = allowed and open_price < _formal_subtract(
            upper, _FORMAL_HALF_PRICE_TICK
        )
        sell_allowed = allowed and open_price > _formal_add(
            lower, _FORMAL_HALF_PRICE_TICK
        )
        rows.append({
            "date": date,
            "symbol": symbol,
            "open": open_value,
            "has_open": True,
            "full_day_suspended": False,
            "partial_open_status": partial_status,
            "has_price_limit": True,
            "up_limit": upper_value,
            "down_limit": lower_value,
            "buy_allowed": buy_allowed,
            "sell_allowed": sell_allowed,
            "reason": reason,
        })
    return _validate_formal_open_execution_frame(
        pl.DataFrame(rows, schema=_OPEN_EXECUTION_FRAME_SCHEMA)
    )


def build_formal_a_share_open_execution_states(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    """Project formal opening facts from one exact verified capability."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(symbols) is not tuple
            or any(type(symbol) is not str for symbol in symbols)
            or any(left >= right for left, right in zip(symbols, symbols[1:]))
        ):
            raise ValueError
        return _build_formal_open_execution_states(
            facts=facts, date=date, symbols=symbols
        )
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None


def resolve_formal_a_share_order_quantity_rule(
    *, facts: VerifiedAShareMarketFacts, date: dt.date, symbol: str
) -> AShareOrderQuantityRule:
    """Resolve one formal rule only after verifying its requested facts domain."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(symbol) is not str
        ):
            raise ValueError
        benchmark = _formal_execution_benchmark(facts)
        _validate_formal_execution_date(benchmark, date)
        instruments, bars, suspensions, _ = _formal_execution_frames(
            facts, include_limits=False
        )
        _, _, _, rule = _formal_request_domain(
            instruments=instruments,
            bars=bars,
            suspensions=suspensions,
            date=date,
            symbol=symbol,
        )
        return rule
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None


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


def compute_a_share_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    if (
        type(notional) is not Decimal
        or not notional.is_finite()
        or notional < 0
        or type(side) is not OrderSide
        or type(cost_period) is not AShareCostPeriod
    ):
        raise ValueError("fee inputs invalid")
    commission = max(
        notional * cost_period.commission_rate, cost_period.commission_min
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    stamp = (
        notional * cost_period.stamp_tax_sell
        if side is OrderSide.SELL
        else Decimal("0")
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    transfer = (notional * cost_period.transfer_fee).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return AShareFeeComponents(commission, stamp, transfer)


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


