"""ETF 目标权重的兼容模拟器。

该入口保留 S0/S1 的历史分红反推与数值语义。股票/ETF 共用的权威
calendar-driven 事件循环由 :mod:`quant.backtest.daily_simulator` 提供。
"""

import datetime as dt
from dataclasses import dataclass
from typing import cast

import polars as pl

from quant.backtest.costs import EtfCostModel
from quant.domain import (
    BacktestNavSchema,
    BacktestTradeSchema,
    Bar1dSchema,
    InstrumentSchema,
    ResearchPrice1dSchema,
    TargetWeightSchema,
)


@dataclass(frozen=True)
class SimulationResult:
    nav: pl.DataFrame
    trades: pl.DataFrame


@dataclass(frozen=True)
class EtfDiagnosticSimulationResult:
    """兼容 ETF 回放结果及可由本入口直接证明的目标缺口。"""

    nav: pl.DataFrame
    trades: pl.DataFrame
    target_gaps: pl.DataFrame


def simulate_etf_targets(
    *,
    bars: pl.DataFrame,
    research_prices: pl.DataFrame,
    scheduled_targets: pl.DataFrame,
    instruments: pl.DataFrame,
    initial_cash: float,
    costs: EtfCostModel,
    strategy: str,
) -> SimulationResult:
    """以真实不复权开/收盘成交估值，并计入分红、整手、佣金和滑点。"""
    result = _simulate_etf_targets(
        bars=bars,
        research_prices=research_prices,
        scheduled_targets=scheduled_targets,
        instruments=instruments,
        initial_cash=initial_cash,
        costs=costs,
        strategy=strategy,
        collect_target_gaps=False,
    )
    return SimulationResult(nav=result.nav, trades=result.trades)


def simulate_etf_targets_with_diagnostics(
    *,
    bars: pl.DataFrame,
    research_prices: pl.DataFrame,
    scheduled_targets: pl.DataFrame,
    instruments: pl.DataFrame,
    initial_cash: float,
    costs: EtfCostModel,
    strategy: str,
) -> EtfDiagnosticSimulationResult:
    """在保持兼容回放经济语义的同时输出整手、现金和缺价目标缺口。"""
    return _simulate_etf_targets(
        bars=bars,
        research_prices=research_prices,
        scheduled_targets=scheduled_targets,
        instruments=instruments,
        initial_cash=initial_cash,
        costs=costs,
        strategy=strategy,
        collect_target_gaps=True,
    )


def _simulate_etf_targets(
    *,
    bars: pl.DataFrame,
    research_prices: pl.DataFrame,
    scheduled_targets: pl.DataFrame,
    instruments: pl.DataFrame,
    initial_cash: float,
    costs: EtfCostModel,
    strategy: str,
    collect_target_gaps: bool,
) -> EtfDiagnosticSimulationResult:
    if initial_cash <= 0:
        raise ValueError("initial_cash 必须大于 0")
    clean_bars = Bar1dSchema.validate(bars).sort(["trade_date", "symbol"])
    clean_prices = ResearchPrice1dSchema.validate(research_prices).sort(
        ["trade_date", "symbol"]
    )
    clean_instruments = InstrumentSchema.validate(instruments)
    TargetWeightSchema.validate(
        scheduled_targets.select(
            "as_of", "strategy", "strategy_version", "symbol", "weight"
        )
    )
    if clean_bars.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("模拟器每只证券每日只能有一个行情来源")
    if clean_prices.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("模拟器每只证券每日只能有一个研究价格")

    lots = dict(
        clean_instruments.select("symbol", "board_lot").iter_rows()
    )
    bar_rows = {
        (row["trade_date"], row["symbol"]): row
        for row in clean_bars.iter_rows(named=True)
    }
    research_rows = {
        (row["trade_date"], row["symbol"]): row["adjusted_close"]
        for row in clean_prices.iter_rows(named=True)
    }
    targets_by_date = {
        date: frame
        for (date,), frame in scheduled_targets.partition_by(
            "execution_date", as_dict=True, maintain_order=True
        ).items()
    }
    symbols = sorted(set(clean_bars.get_column("symbol").to_list()))
    dates = sorted(set(clean_bars.get_column("trade_date").to_list()))
    positions = {symbol: 0 for symbol in symbols}
    cash = initial_cash
    cumulative_fees = 0.0
    previous_close: dict[str, float] = {}
    previous_research: dict[str, float] = {}
    nav_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    target_gap_rows: list[dict[str, object]] = []

    for date in dates:
        daily_bars = {
            symbol: bar_rows[(date, symbol)]
            for symbol in symbols
            if (date, symbol) in bar_rows
        }
        for symbol, bar in daily_bars.items():
            adjusted = research_rows.get((date, symbol))
            if adjusted is None:
                raise ValueError(f"研究价格缺少 {symbol} {date}")
            if symbol in previous_close and symbol in previous_research:
                dividend = (
                    adjusted / previous_research[symbol] * previous_close[symbol]
                    - bar["close"]
                )
                if dividend < -1e-8:
                    raise ValueError(f"反推现金分红为负: {symbol} {date} {dividend}")
                if dividend > 1e-8:
                    cash += positions[symbol] * dividend

        target_frame = targets_by_date.get(date)
        if target_frame is not None:
            target_weights = dict(
                target_frame.select("symbol", "weight").iter_rows()
            )
            open_equity = cash + sum(
                positions[symbol] * bar["open"]
                for symbol, bar in daily_bars.items()
            )
            desired = {
                symbol: _round_lot(
                    target_weights.get(symbol, 0.0) * open_equity / bar["open"],
                    lots[symbol],
                )
                for symbol, bar in daily_bars.items()
            }
            for symbol in symbols:
                quantity = positions[symbol] - desired.get(symbol, 0)
                if quantity > 0 and symbol in daily_bars:
                    cash, fee = _execute(
                        date=date,
                        symbol=symbol,
                        side="SELL",
                        quantity=quantity,
                        open_price=daily_bars[symbol]["open"],
                        cash=cash,
                        costs=costs,
                        strategy=strategy,
                        rows=trade_rows,
                    )
                    positions[symbol] -= quantity
                    cumulative_fees += fee
            for symbol in symbols:
                wanted = desired.get(symbol, 0) - positions[symbol]
                if wanted <= 0 or symbol not in daily_bars:
                    continue
                lot = lots[symbol]
                quantity = wanted
                while quantity > 0:
                    price = costs.execution_price(daily_bars[symbol]["open"], "BUY")
                    notional = price * quantity
                    fee = costs.fee(notional, date)
                    if notional + fee <= cash + 1e-9:
                        break
                    quantity -= lot
                if quantity > 0:
                    cash, fee = _execute(
                        date=date,
                        symbol=symbol,
                        side="BUY",
                        quantity=quantity,
                        open_price=daily_bars[symbol]["open"],
                        cash=cash,
                        costs=costs,
                        strategy=strategy,
                        rows=trade_rows,
                    )
                    positions[symbol] += quantity
                    cumulative_fees += fee
            if collect_target_gaps:
                _append_target_gaps(
                    rows=target_gap_rows,
                    strategy=strategy,
                    date=date,
                    target_weights=target_weights,
                    positions=positions,
                    daily_bars=daily_bars,
                    lots=lots,
                    open_equity=open_equity,
                )

        market_value = sum(
            positions[symbol] * bar["close"] for symbol, bar in daily_bars.items()
        )
        equity = cash + market_value
        nav_rows.append({
            "strategy": strategy,
            "date": date,
            "equity": equity,
            "unit_nav": equity / initial_cash,
            "cash": cash,
            "market_value": market_value,
            "cumulative_fees": cumulative_fees,
        })
        for symbol, bar in daily_bars.items():
            previous_close[symbol] = bar["close"]
            previous_research[symbol] = research_rows[(date, symbol)]

    nav = BacktestNavSchema.validate(pl.DataFrame(nav_rows))
    trades = (
        BacktestTradeSchema.validate(pl.DataFrame(trade_rows))
        if trade_rows
        else _empty_trades()
    )
    return EtfDiagnosticSimulationResult(
        nav=nav,
        trades=trades,
        target_gaps=_target_gap_frame(target_gap_rows),
    )


def _append_target_gaps(
    *,
    rows: list[dict[str, object]],
    strategy: str,
    date: dt.date,
    target_weights: dict[str, float],
    positions: dict[str, int],
    daily_bars: dict[str, dict[str, object]],
    lots: dict[str, int],
    open_equity: float,
) -> None:
    for symbol in sorted(set(target_weights) | {s for s, q in positions.items() if q > 0}):
        weight = float(target_weights.get(symbol, 0.0))
        bar = daily_bars.get(symbol)
        achieved_quantity = positions.get(symbol, 0)
        if bar is None:
            rows.append({
                "strategy": strategy,
                "date": date,
                "symbol": symbol,
                "target_weight": weight,
                "achieved_weight": None,
                "raw_target_quantity": None,
                "rounded_target_quantity": None,
                "achieved_quantity": achieved_quantity,
                "absolute_weight_gap": None,
                "absolute_notional_gap": None,
                "gap_reason": "OPEN_PRICE_UNAVAILABLE",
            })
            continue
        open_price = cast(float, bar["open"])
        raw_quantity = weight * open_equity / open_price
        rounded_quantity = _round_lot(raw_quantity, lots[symbol])
        achieved_weight = achieved_quantity * open_price / open_equity
        absolute_weight_gap = abs(weight - achieved_weight)
        absolute_notional_gap = absolute_weight_gap * open_equity
        if achieved_quantity != rounded_quantity:
            reason = "CASH_CONSTRAINT"
        elif abs(raw_quantity - rounded_quantity) > 1e-9:
            reason = "LOT_ROUNDING"
        else:
            reason = "NONE"
        rows.append({
            "strategy": strategy,
            "date": date,
            "symbol": symbol,
            "target_weight": weight,
            "achieved_weight": achieved_weight,
            "raw_target_quantity": raw_quantity,
            "rounded_target_quantity": rounded_quantity,
            "achieved_quantity": achieved_quantity,
            "absolute_weight_gap": absolute_weight_gap,
            "absolute_notional_gap": absolute_notional_gap,
            "gap_reason": reason,
        })


def _round_lot(quantity: float, lot: int) -> int:
    return max(0, int(quantity // lot) * lot)


def _execute(
    *,
    date: dt.date,
    symbol: str,
    side: str,
    quantity: int,
    open_price: float,
    cash: float,
    costs: EtfCostModel,
    strategy: str,
    rows: list[dict[str, object]],
) -> tuple[float, float]:
    price = costs.execution_price(open_price, side)
    notional = price * quantity
    fee = costs.fee(notional, date)
    cash = cash - notional - fee if side == "BUY" else cash + notional - fee
    rows.append({
        "strategy": strategy,
        "date": date,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "notional": notional,
        "fee": fee,
        "slippage_cost": abs(price - open_price) * quantity,
    })
    return cash, fee


def _empty_trades() -> pl.DataFrame:
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


def _target_gap_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    schema = {
        "strategy": pl.String,
        "date": pl.Date,
        "symbol": pl.String,
        "target_weight": pl.Float64,
        "achieved_weight": pl.Float64,
        "raw_target_quantity": pl.Float64,
        "rounded_target_quantity": pl.Int64,
        "achieved_quantity": pl.Int64,
        "absolute_weight_gap": pl.Float64,
        "absolute_notional_gap": pl.Float64,
        "gap_reason": pl.String,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    result = pl.DataFrame(rows, schema=schema).sort("date", "symbol")
    if result.select("strategy", "date", "symbol").is_duplicated().any():
        raise ValueError("ETF_TARGET_GAP_DUPLICATED")
    allowed = {"NONE", "LOT_ROUNDING", "CASH_CONSTRAINT", "OPEN_PRICE_UNAVAILABLE"}
    if not set(result.get_column("gap_reason").to_list()).issubset(allowed):
        raise ValueError("ETF_TARGET_GAP_REASON_INVALID")
    return result
