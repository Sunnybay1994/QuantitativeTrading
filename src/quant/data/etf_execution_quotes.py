"""Observed ETF minute quotes for fixed daily target execution studies."""

import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.intraday_bars import validate_bars
from quant.data.intraday_research_inputs import read_etf_minutes


def read_execution_quotes(data_root: Path, symbols: tuple[str, ...], dates: list[dt.date]) -> pl.DataFrame:
    frames = []
    for symbol in symbols:
        frame = validate_bars(read_etf_minutes(data_root, symbol, "5m", "yahoo")).filter(
            pl.col("trade_date").is_in(dates))
        quotes = frame.with_columns(pl.col("bar_start").dt.strftime("%H:%M").alias("time")).filter(
            pl.col("time").is_in(["09:30", "09:35"]))
        expected = {(day, time) for day in dates for time in ("09:30", "09:35")}
        if (set(quotes.select("trade_date", "time").iter_rows()) != expected
            or quotes.height != len(expected) or not quotes["session_complete"].all()):
            raise ValueError(f"Missing or incomplete execution quotes for {symbol}")
        # Yahoo float representation is rounded to the ETF's 0.001 exchange tick.
        frames.append(quotes.select("symbol", "trade_date", "time", "bar_start",
                                    pl.col("open").round(3), "volume"))
    return pl.concat(frames).sort("trade_date", "symbol", "time")


def execution_bars(bars: pl.DataFrame, quotes: pl.DataFrame, time: str, tolerance: float) -> pl.DataFrame:
    """Replace only scheduled execution quotes; keep closing marks and daily ranges."""
    selected = quotes.filter(pl.col("time") == time).select("symbol", "trade_date",
        pl.col("open").alias("execution_open"), pl.col("volume").alias("execution_volume"))
    if selected.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate execution quote")
    joined = bars.join(selected, on=["symbol", "trade_date"], how="left")
    if joined.filter(pl.col("execution_open").is_not_null() & (
        (pl.col("execution_open") < pl.col("low") - tolerance)
        | (pl.col("execution_open") > pl.col("high") + tolerance))).height:
        raise ValueError("Minute quote outside independent daily price range")
    return joined.with_columns(
        pl.coalesce("execution_open", "open").alias("open"),
        pl.coalesce("execution_volume", "volume").alias("volume"),
    ).drop("execution_open", "execution_volume")


def quote_quality_errors(quotes: pl.DataFrame) -> list[dict]:
    """A zero-volume observation cannot establish a comparable tradable price.

    Do not turn supplier placeholders into suspended benchmark orders and thereby
    attribute a changed invested portfolio to a better execution price.
    """
    return [{"symbol": row["symbol"], "date": str(row["trade_date"]), "time": row["time"],
             "reason": "zero_volume_quote_cannot_establish_tradeability"}
            for row in quotes.filter(pl.col("volume") <= 0).iter_rows(named=True)]
