"""股票与 ETF 共用的权威交易日驱动日频账户模拟器。"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any

import polars as pl

from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.rules import DailyMarketState, execution_reject_reason
from quant.domain import (
    BacktestNavSchema,
    BacktestPositionSchema,
    BacktestRejectionSchema,
    BacktestTradeSchema,
    Bar1dSchema,
    InstrumentSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
)
from quant.domain.enums import ExecutionRejectReason, OrderSide

_TARGET_COLUMNS = (
    "as_of",
    "strategy",
    "strategy_version",
    "symbol",
    "weight",
)
_INITIAL_POSITION_COLUMNS = (
    "symbol",
    "quantity",
    "settled_quantity",
    "mark_price",
)
_SUPPORTED_TYPES = {"STOCK", "ETF"}
_SUPPORTED_MARKETS = {"SH", "SZ"}
_EPSILON = 1e-8


@dataclass(frozen=True)
class DailySimulationResult:
    """统一日频模拟的账户和执行证据。"""

    nav: pl.DataFrame
    trades: pl.DataFrame
    positions: pl.DataFrame
    rejections: pl.DataFrame


@dataclass
class _Position:
    quantity: int
    settled: int
    mark: float
    target_weight: float | None = None


def simulate_daily_targets(
    *,
    calendar: pl.DataFrame,
    bars: pl.DataFrame,
    scheduled_targets: pl.DataFrame,
    instruments: pl.DataFrame,
    market_states: Mapping[tuple[dt.date, str], DailyMarketState],
    initial_cash: float,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
    strategy: str,
    initial_positions: pl.DataFrame | None = None,
) -> DailySimulationResult:
    """按权威 session 模拟股票/ETF 目标权重，显式保留拒单证据。"""
    if (
        not isinstance(initial_cash, (int, float))
        or isinstance(initial_cash, bool)
        or not math.isfinite(float(initial_cash))
        or initial_cash < 0
    ):
        raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
    if not isinstance(strategy, str) or not strategy:
        raise ValueError("BACKTEST_TARGET_BATCH_INVALID")

    clean_calendar = TradeCalendarSchema.validate(calendar).sort(
        ["date", "market"]
    )
    clean_bars = Bar1dSchema.validate(bars).sort(
        ["trade_date", "symbol"]
    )
    clean_instruments = InstrumentSchema.validate(instruments).sort("symbol")
    clean_targets = _validate_targets(scheduled_targets, strategy=strategy)

    if clean_bars.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("BACKTEST_TRADABLE_BAR_MISSING")

    instrument_rows = {
        row["symbol"]: row
        for row in clean_instruments.iter_rows(named=True)
    }
    bar_rows = {
        (row["trade_date"], row["symbol"]): row
        for row in clean_bars.iter_rows(named=True)
    }
    targets_by_date = {
        date: frame.sort("symbol")
        for (date,), frame in clean_targets.partition_by(
            "execution_date", as_dict=True, maintain_order=True
        ).items()
    }
    positions = _load_initial_positions(
        initial_positions,
        instrument_rows=instrument_rows,
    )
    target_symbols = set(clean_targets.get_column("symbol").to_list())
    _require_instrument_policy(target_symbols, instrument_rows)
    open_pairs = {
        (row["market"], row["date"])
        for row in clean_calendar.filter(pl.col("is_open")).iter_rows(
            named=True
        )
    }
    calendar_pairs = {
        (row["market"], row["date"])
        for row in clean_calendar.iter_rows(named=True)
    }
    for row in clean_targets.iter_rows(named=True):
        instrument = instrument_rows[row["symbol"]]
        if not _instrument_active(instrument, row["execution_date"]):
            raise ValueError("BACKTEST_INSTRUMENT_POLICY_MISSING")
        market = instrument["market"]
        if (market, row["execution_date"]) not in open_pairs:
            raise ValueError("BACKTEST_CALENDAR_COVERAGE_MISSING")

    active_symbols = target_symbols | set(positions)
    if not active_symbols:
        active_symbols = {
            symbol
            for symbol in clean_bars.get_column("symbol").to_list()
            if symbol in instrument_rows
            and _instrument_policy_supported(instrument_rows[symbol])
        }
    active_markets = {
        instrument_rows[symbol]["market"] for symbol in active_symbols
    }
    if not active_markets:
        active_markets = {
            row["market"]
            for row in instrument_rows.values()
            if _instrument_policy_supported(row)
        }
    sessions = sorted(
        {
            date
            for market, date in open_pairs
            if market in active_markets
        }
    )
    if active_symbols and not sessions:
        raise ValueError("BACKTEST_CALENDAR_COVERAGE_MISSING")
    if any(
        (market, date) not in calendar_pairs
        for date in sessions
        for market in active_markets
    ):
        raise ValueError("BACKTEST_CALENDAR_COVERAGE_MISSING")
    initial_equity_decimal = Decimal(str(initial_cash)) + sum(
        (
            Decimal(positions[symbol].quantity)
            * Decimal(str(positions[symbol].mark))
            for symbol in sorted(positions)
        ),
        Decimal(0),
    )
    initial_equity = float(initial_equity_decimal)
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")

    cash = float(initial_cash)
    cumulative_fees = 0.0
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    rejection_rows: list[dict[str, Any]] = []
    for session_index, date in enumerate(sessions):
        open_markets = {
            market
            for market in active_markets
            if (market, date) in open_pairs
        }
        if session_index > 0:
            _settle_previous_session(positions)

        target_frame = targets_by_date.get(date)
        batch_weights = (
            dict(target_frame.select("symbol", "weight").iter_rows())
            if target_frame is not None
            else None
        )
        relevant_symbols = {
            symbol
            for symbol, position in positions.items()
            if position.quantity > 0
        }
        if batch_weights is not None:
            relevant_symbols.update(batch_weights)

        _require_instrument_policy(relevant_symbols, instrument_rows)
        _require_active_instruments(
            relevant_symbols,
            instrument_rows,
            date=date,
        )
        if target_frame is not None and any(
            instrument_rows[symbol]["market"] not in open_markets
            for symbol in relevant_symbols
        ):
            raise ValueError("BACKTEST_CALENDAR_COVERAGE_MISSING")
        references = _build_references(
            date=date,
            symbols=relevant_symbols,
            positions=positions,
            bar_rows=bar_rows,
            market_states=market_states,
            instrument_rows=instrument_rows,
            open_markets=open_markets,
        )

        if batch_weights is not None:
            for symbol in relevant_symbols:
                position = positions.setdefault(
                    symbol,
                    _Position(
                        quantity=0,
                        settled=0,
                        mark=references[symbol]["open"],
                    ),
                )
                position.target_weight = float(batch_weights.get(symbol, 0.0))

            open_equity_decimal = Decimal(str(cash)) + sum(
                (
                    Decimal(positions[symbol].quantity)
                    * Decimal(str(references[symbol]["open"]))
                    for symbol in sorted(relevant_symbols)
                ),
                Decimal(0),
            )
            open_equity = float(open_equity_decimal)
            if not math.isfinite(open_equity) or open_equity < -_EPSILON:
                raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
            desired = {
                symbol: _round_lot(
                    float(batch_weights.get(symbol, 0.0)),
                    open_equity_decimal,
                    references[symbol]["open"],
                    int(instrument_rows[symbol]["board_lot"]),
                )
                for symbol in relevant_symbols
            }

            for symbol in sorted(relevant_symbols):
                requested = positions[symbol].quantity - desired[symbol]
                if requested <= 0:
                    continue
                reason = _reject_reason(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=requested,
                    position=positions[symbol],
                    state=market_states[(date, symbol)],
                    instrument_rows=instrument_rows,
                )
                if reason is not None:
                    _append_rejection(
                        rows=rejection_rows,
                        strategy=strategy,
                        date=date,
                        symbol=symbol,
                        side=OrderSide.SELL,
                        reason=reason,
                        quantity=requested,
                        reference_price=references[symbol]["open"],
                    )
                    continue
                cash, fee = _execute(
                    rows=trade_rows,
                    strategy=strategy,
                    date=date,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=requested,
                    open_price=references[symbol]["open"],
                    cash=cash,
                    instrument_type=instrument_rows[symbol]["instrument_type"],
                    etf_costs=etf_costs,
                    stock_costs=stock_costs,
                )
                position = positions[symbol]
                position.quantity -= requested
                position.settled = max(0, position.settled - requested)
                cumulative_fees += fee

            for symbol in sorted(relevant_symbols):
                wanted = desired[symbol] - positions[symbol].quantity
                if wanted <= 0:
                    continue
                reason = _reject_reason(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=wanted,
                    position=positions[symbol],
                    state=market_states[(date, symbol)],
                    instrument_rows=instrument_rows,
                )
                if reason is not None:
                    _append_rejection(
                        rows=rejection_rows,
                        strategy=strategy,
                        date=date,
                        symbol=symbol,
                        side=OrderSide.BUY,
                        reason=reason,
                        quantity=wanted,
                        reference_price=references[symbol]["open"],
                    )
                    continue
                quantity = _affordable_quantity(
                    date=date,
                    requested=wanted,
                    lot=int(instrument_rows[symbol]["board_lot"]),
                    open_price=references[symbol]["open"],
                    cash=cash,
                    instrument_type=instrument_rows[symbol]["instrument_type"],
                    etf_costs=etf_costs,
                    stock_costs=stock_costs,
                )
                if quantity <= 0:
                    continue
                cash, fee = _execute(
                    rows=trade_rows,
                    strategy=strategy,
                    date=date,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=quantity,
                    open_price=references[symbol]["open"],
                    cash=cash,
                    instrument_type=instrument_rows[symbol]["instrument_type"],
                    etf_costs=etf_costs,
                    stock_costs=stock_costs,
                )
                position = positions[symbol]
                position.quantity += quantity
                cumulative_fees += fee

        for symbol in relevant_symbols:
            positions[symbol].mark = references[symbol]["close"]

        output_symbols = {
            symbol
            for symbol, position in positions.items()
            if position.quantity > 0
        }
        if batch_weights is not None:
            output_symbols.update(batch_weights)
            output_symbols.update(relevant_symbols)
        market_value_decimal = sum(
            (
                Decimal(positions[symbol].quantity)
                * Decimal(str(positions[symbol].mark))
                for symbol in sorted(output_symbols)
            ),
            Decimal(0),
        )
        market_value = float(market_value_decimal)
        equity = float(Decimal(str(cash)) + market_value_decimal)
        unit_nav = equity / initial_equity
        if (
            cash < 0.0
            or market_value < -_EPSILON
            or equity < -_EPSILON
            or not all(
                math.isfinite(value)
                for value in (cash, market_value, equity, unit_nav)
            )
        ):
            raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
        nav_rows.append({
            "strategy": strategy,
            "date": date,
            "equity": equity,
            "unit_nav": unit_nav,
            "cash": cash,
            "market_value": market_value,
            "cumulative_fees": cumulative_fees,
        })
        for symbol in sorted(output_symbols):
            position = positions[symbol]
            unsettled = position.quantity - position.settled
            if unsettled < 0:
                raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
            position_rows.append({
                "strategy": strategy,
                "date": date,
                "symbol": symbol,
                "quantity": position.quantity,
                "settled_quantity": position.settled,
                "unsettled_quantity": unsettled,
                "mark_price": position.mark,
                "market_value": position.quantity * position.mark,
                "target_weight": position.target_weight,
            })

    return DailySimulationResult(
        nav=BacktestNavSchema.validate(pl.DataFrame(nav_rows)).sort("date"),
        trades=_validate_or_empty_trades(trade_rows),
        positions=_validate_or_empty_positions(position_rows),
        rejections=_validate_or_empty_rejections(rejection_rows),
    )


def _validate_targets(
    scheduled_targets: pl.DataFrame, *, strategy: str
) -> pl.DataFrame:
    required = set(_TARGET_COLUMNS) | {"execution_date"}
    if not required.issubset(scheduled_targets.columns):
        raise ValueError("BACKTEST_TARGET_BATCH_INVALID")
    try:
        validated_targets = TargetWeightSchema.validate(
            scheduled_targets.select(_TARGET_COLUMNS)
        )
    except Exception as exc:
        raise ValueError("BACKTEST_TARGET_BATCH_INVALID") from exc
    execution_dates = scheduled_targets.get_column("execution_date")
    if execution_dates.dtype != pl.Date or execution_dates.null_count():
        raise ValueError("BACKTEST_TARGET_BATCH_INVALID")
    clean = validated_targets.with_columns(execution_dates).sort(
        ["execution_date", "symbol"]
    )
    if clean.filter(pl.col("as_of") >= pl.col("execution_date")).height:
        raise ValueError("BACKTEST_TARGET_BATCH_INVALID")
    for (_date,), frame in clean.partition_by(
        "execution_date", as_dict=True, maintain_order=True
    ).items():
        if (
            frame.get_column("strategy").unique().to_list() != [strategy]
            or frame.get_column("as_of").n_unique() != 1
            or frame.get_column("strategy_version").n_unique() != 1
            or frame.get_column("symbol").n_unique() != frame.height
            or frame.get_column("weight").sum() > 1.0 + _EPSILON
        ):
            raise ValueError("BACKTEST_TARGET_BATCH_INVALID")
    return clean


def _load_initial_positions(
    initial_positions: pl.DataFrame | None,
    *,
    instrument_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, _Position]:
    if initial_positions is None:
        return {}
    if not set(_INITIAL_POSITION_COLUMNS).issubset(initial_positions.columns):
        raise ValueError("BACKTEST_INITIAL_MARK_MISSING")
    selected = initial_positions.select(_INITIAL_POSITION_COLUMNS)
    if selected.get_column("symbol").n_unique() != selected.height:
        raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
    result: dict[str, _Position] = {}
    for row in selected.iter_rows(named=True):
        symbol = row["symbol"]
        _require_instrument_policy({symbol}, instrument_rows)
        mark = row["mark_price"]
        quantity = row["quantity"]
        settled = row["settled_quantity"]
        if (
            mark is None
            or not isinstance(mark, (int, float))
            or not math.isfinite(float(mark))
            or mark <= 0
        ):
            raise ValueError("BACKTEST_INITIAL_MARK_MISSING")
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or not isinstance(settled, int)
            or isinstance(settled, bool)
            or quantity < 0
            or settled < 0
            or settled > quantity
        ):
            raise ValueError("BACKTEST_ACCOUNT_INVARIANT_BROKEN")
        result[symbol] = _Position(
            quantity=quantity,
            settled=settled,
            mark=float(mark),
        )
    return result


def _settle_previous_session(
    positions: Mapping[str, _Position],
) -> None:
    for position in positions.values():
        position.settled = position.quantity


def _require_instrument_policy(
    symbols: set[str],
    instrument_rows: Mapping[str, Mapping[str, Any]],
) -> None:
    for symbol in symbols:
        row = instrument_rows.get(symbol)
        if row is None or not _instrument_policy_supported(row):
            raise ValueError("BACKTEST_INSTRUMENT_POLICY_MISSING")


def _instrument_policy_supported(row: Mapping[str, Any]) -> bool:
    return (
        row["instrument_type"] in _SUPPORTED_TYPES
        and row["market"] in _SUPPORTED_MARKETS
        and row["currency"] == "CNY"
    )


def _instrument_active(
    row: Mapping[str, Any],
    date: dt.date,
) -> bool:
    delist_date = row["delist_date"]
    return row["list_date"] <= date and (
        delist_date is None or date <= delist_date
    )


def _require_active_instruments(
    symbols: set[str],
    instrument_rows: Mapping[str, Mapping[str, Any]],
    *,
    date: dt.date,
) -> None:
    if any(
        not _instrument_active(instrument_rows[symbol], date)
        for symbol in symbols
    ):
        raise ValueError("BACKTEST_INSTRUMENT_POLICY_MISSING")


def _build_references(
    *,
    date: dt.date,
    symbols: set[str],
    positions: Mapping[str, _Position],
    bar_rows: Mapping[tuple[dt.date, str], Mapping[str, Any]],
    market_states: Mapping[tuple[dt.date, str], DailyMarketState],
    instrument_rows: Mapping[str, Mapping[str, Any]],
    open_markets: set[str],
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for symbol in sorted(symbols):
        if instrument_rows[symbol]["market"] not in open_markets:
            if (date, symbol) in bar_rows:
                raise ValueError("BACKTEST_CALENDAR_COVERAGE_MISSING")
            position = positions.get(symbol)
            if position is None or position.mark <= 0:
                raise ValueError("BACKTEST_INITIAL_MARK_MISSING")
            result[symbol] = {
                "open": position.mark,
                "close": position.mark,
            }
            continue
        state = market_states.get((date, symbol))
        if not isinstance(state, DailyMarketState):
            raise ValueError("BACKTEST_MARKET_STATE_MISSING")
        bar = bar_rows.get((date, symbol))
        if bar is not None:
            result[symbol] = {
                "open": float(bar["open"]),
                "close": float(bar["close"]),
            }
            continue
        if not state.suspended:
            raise ValueError("BACKTEST_TRADABLE_BAR_MISSING")
        position = positions.get(symbol)
        carried_mark = (
            position.mark
            if position is not None
            else _latest_prior_close(
                date=date, symbol=symbol, bar_rows=bar_rows
            )
        )
        if carried_mark is None or carried_mark <= 0:
            raise ValueError("BACKTEST_INITIAL_MARK_MISSING")
        result[symbol] = {"open": carried_mark, "close": carried_mark}
    return result


def _latest_prior_close(
    *, date: dt.date, symbol: str,
    bar_rows: Mapping[tuple[dt.date, str], Mapping[str, Any]],
) -> float | None:
    prior_dates = [
        trade_date
        for trade_date, current_symbol in bar_rows
        if current_symbol == symbol and trade_date < date
    ]
    if not prior_dates:
        return None
    return float(bar_rows[(max(prior_dates), symbol)]["close"])


def _round_lot(
    weight: float,
    equity: Decimal,
    price: float,
    lot: int,
) -> int:
    raw = Decimal(str(weight)) * equity / Decimal(str(price))
    lots = (raw / Decimal(lot)).to_integral_value(rounding=ROUND_FLOOR)
    return max(0, int(lots) * lot)


def _reject_reason(
    *,
    symbol: str,
    side: OrderSide,
    quantity: int,
    position: _Position,
    state: DailyMarketState,
    instrument_rows: Mapping[str, Mapping[str, Any]],
) -> ExecutionRejectReason | None:
    is_stock = instrument_rows[symbol]["instrument_type"] == "STOCK"
    settled = position.settled if is_stock else position.quantity
    return execution_reject_reason(
        side=side,
        quantity=quantity,
        settled_quantity=settled,
        state=state,
        enforce_t_plus_one=is_stock,
    )


def _append_rejection(
    *,
    rows: list[dict[str, Any]],
    strategy: str,
    date: dt.date,
    symbol: str,
    side: OrderSide,
    reason: ExecutionRejectReason,
    quantity: int,
    reference_price: float,
) -> None:
    rows.append({
        "strategy": strategy,
        "date": date,
        "symbol": symbol,
        "side": side.value,
        "reason": reason.value,
        "requested_quantity": quantity,
        "rejected_quantity": quantity,
        "reference_price": reference_price,
    })


def _model_for(
    instrument_type: str,
    *,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
) -> EtfCostModel | AShareCostModel:
    return etf_costs if instrument_type == "ETF" else stock_costs


def _execution_values(
    *,
    date: dt.date,
    side: OrderSide,
    quantity: int,
    open_price: float,
    instrument_type: str,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
) -> tuple[float, float, float]:
    model = _model_for(
        instrument_type,
        etf_costs=etf_costs,
        stock_costs=stock_costs,
    )
    if date < model.effective_from:
        raise ValueError("BACKTEST_COST_NOT_EFFECTIVE")
    price = model.execution_price(open_price, side.value)
    notional = price * quantity
    if isinstance(model, AShareCostModel):
        fee = model.fee(notional, date, side.value)
    else:
        fee = model.fee(notional, date)
    return price, notional, fee


def _affordable_quantity(
    *,
    date: dt.date,
    requested: int,
    lot: int,
    open_price: float,
    cash: float,
    instrument_type: str,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
) -> int:
    maximum_lots = requested // lot
    low = 0
    high = maximum_lots
    while low < high:
        candidate_lots = (low + high + 1) // 2
        quantity = candidate_lots * lot
        _price, notional, fee = _execution_values(
            date=date,
            side=OrderSide.BUY,
            quantity=quantity,
            open_price=open_price,
            instrument_type=instrument_type,
            etf_costs=etf_costs,
            stock_costs=stock_costs,
        )
        required = Decimal(str(notional)) + Decimal(str(fee))
        if required <= Decimal(str(cash)):
            low = candidate_lots
        else:
            high = candidate_lots - 1
    return low * lot


def _execute(
    *,
    rows: list[dict[str, Any]],
    strategy: str,
    date: dt.date,
    symbol: str,
    side: OrderSide,
    quantity: int,
    open_price: float,
    cash: float,
    instrument_type: str,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
) -> tuple[float, float]:
    price, notional, fee = _execution_values(
        date=date,
        side=side,
        quantity=quantity,
        open_price=open_price,
        instrument_type=instrument_type,
        etf_costs=etf_costs,
        stock_costs=stock_costs,
    )
    if side is OrderSide.BUY:
        cash -= notional + fee
    else:
        cash += notional - fee
    rows.append({
        "strategy": strategy,
        "date": date,
        "symbol": symbol,
        "side": side.value,
        "quantity": quantity,
        "price": price,
        "notional": notional,
        "fee": fee,
        "slippage_cost": abs(price - open_price) * quantity,
    })
    return cash, fee


def _validate_or_empty_trades(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if rows:
        return BacktestTradeSchema.validate(pl.DataFrame(rows)).sort(
            ["date", "side", "symbol"],
            descending=[False, True, False],
        )
    return pl.DataFrame(
        schema={
            "strategy": pl.String,
            "date": pl.Date,
            "symbol": pl.String,
            "side": pl.String,
            "quantity": pl.Int64,
            "price": pl.Float64,
            "notional": pl.Float64,
            "fee": pl.Float64,
            "slippage_cost": pl.Float64,
        }
    )


def _validate_or_empty_positions(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if rows:
        return BacktestPositionSchema.validate(pl.DataFrame(rows)).sort(
            ["date", "symbol"]
        )
    return pl.DataFrame(
        schema={
            "strategy": pl.String,
            "date": pl.Date,
            "symbol": pl.String,
            "quantity": pl.Int64,
            "settled_quantity": pl.Int64,
            "unsettled_quantity": pl.Int64,
            "mark_price": pl.Float64,
            "market_value": pl.Float64,
            "target_weight": pl.Float64,
        }
    )


def _validate_or_empty_rejections(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if rows:
        return BacktestRejectionSchema.validate(pl.DataFrame(rows)).sort(
            ["date", "symbol", "side"]
        )
    return pl.DataFrame(
        schema={
            "strategy": pl.String,
            "date": pl.Date,
            "symbol": pl.String,
            "side": pl.String,
            "reason": pl.String,
            "requested_quantity": pl.Int64,
            "rejected_quantity": pl.Int64,
            "reference_price": pl.Float64,
        }
    )
