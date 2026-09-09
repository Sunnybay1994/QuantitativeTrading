"""Dividend events and session states for the fixed eleven-ETF paper pool."""

import datetime as dt
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import polars as pl

from quant.backtest.rules import DailyMarketState
from quant.data.etf_limits import validate_limits


def read_etf_dividends(
    data_root: Path, symbols: list[str], start: dt.date,
) -> pl.DataFrame:
    """Use latest captured implementation records; preserve ex-date and pay-date."""
    latest: dict[str, pl.DataFrame] = {}
    for path in sorted((data_root / "raw/tushare/fund_div").glob("date=*/*.parquet")):
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        symbol = metadata["parameters"].get("ts_code")
        if symbol in symbols:
            latest[symbol] = pl.read_parquet(path)
    if set(latest) != set(symbols):
        raise ValueError("ETF dividend snapshots missing; refresh ETF data first")
    events = pl.concat([f for f in latest.values() if not f.is_empty()], how="diagonal_relaxed").filter(
        (pl.col("div_proc") == "实施") & pl.col("ex_date").is_not_null()
    ).select(
        pl.col("ts_code").alias("symbol"),
        pl.col("imp_anndate").str.to_date("%Y%m%d").alias("ann_date"),
        pl.col("record_date").str.to_date("%Y%m%d"),
        pl.col("ex_date").str.to_date("%Y%m%d"),
        pl.col("pay_date").str.to_date("%Y%m%d"),
        pl.col("div_cash").cast(pl.Float64),
    ).unique().filter(pl.col("ex_date") >= start)
    if events.select("symbol", "ex_date").is_duplicated().any():
        raise ValueError("Conflicting ETF dividend implementations")
    if events.null_count().sum_horizontal().item() or events.filter(
        (pl.col("ann_date") > pl.col("record_date"))
        | (pl.col("record_date") >= pl.col("ex_date"))
        | (pl.col("pay_date") < pl.col("ex_date"))
        | ~pl.col("div_cash").is_finite() | (pl.col("div_cash") < 0)
    ).height:
        raise ValueError("Incomplete ETF dividend implementation")
    return events.sort("ex_date", "symbol")


def etf_session_states(
    bars: pl.DataFrame, dividends: pl.DataFrame, *, limit_fraction: float = 0.10, slippage: float = 0.0,
    official_limits: pl.DataFrame | None = None,
    slippage_per_share: float = 0.0,
) -> dict[tuple[dt.date, str], DailyMarketState]:
    """Fixed pool: 10% daily bands, 0.001 tick, ex-dividend reference adjustment.

    Missing bars are rejected by the panel reader. Zero-volume bars cannot fill.
    The open denotes the first tradable daily quote, including a delayed opening.
    """
    if official_limits is not None:
        validate_limits(official_limits)
        joined = bars.join(official_limits, on=["symbol", "trade_date"], how="left")
        if joined["up_limit"].null_count():
            raise ValueError("ETF price bands missing; refresh ETF data first")
        return {(r["trade_date"], r["symbol"]): DailyMarketState(
            suspended=r["volume"] <= 0,
            at_upper_limit=r["open"] * (1 + slippage) + slippage_per_share >= r["up_limit"] - 1e-9,
            at_lower_limit=r["open"] * (1 - slippage) - slippage_per_share <= r["down_limit"] + 1e-9,
        ) for r in joined.iter_rows(named=True)}
    cash_div = {(r["ex_date"], r["symbol"]): r["div_cash"]
                for r in dividends.iter_rows(named=True)}
    previous: dict[str, float] = {}
    states = {}
    for row in bars.sort("trade_date", "symbol").iter_rows(named=True):
        symbol, date = row["symbol"], row["trade_date"]
        if symbol in previous:
            reference = previous[symbol] - cash_div.get((date, symbol), 0.0)
            if reference <= 0:
                raise ValueError("Invalid ETF ex-dividend reference")
            upper = float((Decimal(str(reference)) * (1 + Decimal(str(limit_fraction))))
                          .quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
            lower = float((Decimal(str(reference)) * (1 - Decimal(str(limit_fraction))))
                          .quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
            states[(date, symbol)] = DailyMarketState(
                suspended=row["volume"] <= 0,
                at_upper_limit=row["open"] * (1 + slippage) + slippage_per_share >= upper - 1e-9,
                at_lower_limit=row["open"] * (1 - slippage) - slippage_per_share <= lower + 1e-9,
            )
        previous[symbol] = row["close"]
    return states
