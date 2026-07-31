"""ETF 目标权重的兼容模拟器。

该入口保留 S0/S1 的历史分红反推与数值语义。股票/ETF 共用的权威
calendar-driven 事件循环由 :mod:`quant.backtest.daily_simulator` 提供。
"""

import datetime as dt
from dataclasses import dataclass

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
    return SimulationResult(nav=nav, trades=trades)


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
