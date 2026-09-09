"""Read the ETF research panel across its historical source cutovers."""

import datetime as dt
from pathlib import Path

import polars as pl


def read_etf_research_inputs(
    data_root: Path, candidates: list[str], start: dt.date, end: dt.date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Return one bar and total-return price per symbol and open session."""
    scope = pl.col("symbol").is_in(candidates) & pl.col("trade_date").is_between(start, end)
    bars = pl.read_parquet(data_root / "clean/bar_1d/date=*/data.parquet").filter(
        scope & (
            ((pl.col("trade_date") < dt.date(2026, 1, 1)) & (pl.col("source") == "akshare"))
            | (pl.col("trade_date").is_between(dt.date(2026, 1, 1), dt.date(2026, 7, 10))
               & (pl.col("source") == "baostock"))
            | ((pl.col("trade_date") > dt.date(2026, 7, 10)) & (pl.col("source") == "tushare"))
        )
    ).sort("trade_date", "symbol")
    prices = pl.read_parquet(data_root / "clean/research_price_1d/date=*/data.parquet").filter(
        scope & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
    ).sort("trade_date", "symbol")
    calendars = pl.concat([
        pl.read_parquet(data_root / f"clean/trade_calendar/market={market}/data.parquet")
        for market in ("SH", "SZ")
    ])
    instruments = pl.concat([
        pl.read_parquet(data_root / f"clean/instrument/market={market}/data.parquet")
        for market in ("SH", "SZ")
    ]).filter(pl.col("symbol").is_in(candidates))
    for symbol in candidates:
        dates = set(calendars.filter(
            (pl.col("market") == symbol[-2:]) & pl.col("is_open")
            & pl.col("date").is_between(start, end)
        ).get_column("date").to_list())
        if not dates:
            raise ValueError(f"Missing ETF calendar: {symbol}")
        for label, frame in (("bars", bars), ("prices", prices)):
            observed = frame.filter(pl.col("symbol") == symbol).get_column("trade_date")
            if set(observed.to_list()) != dates or observed.n_unique() != observed.len():
                raise ValueError(f"Incomplete or duplicate ETF {label}: {symbol}")
    return bars, prices, calendars, instruments
