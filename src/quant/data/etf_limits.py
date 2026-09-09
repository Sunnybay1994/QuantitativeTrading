"""Incremental official price bands for the fixed ETF paper pool."""

import datetime as dt
import time
from pathlib import Path

import polars as pl

from quant.data.calendar import expected_open_dates
from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def read_limits(data_root: Path) -> pl.DataFrame:
    path = data_root / "clean/etf_limit/data.parquet"
    return (pl.read_parquet(path) if path.exists() else pl.DataFrame(schema={
        "symbol": pl.String, "trade_date": pl.Date,
        "up_limit": pl.Float64, "down_limit": pl.Float64}))


def validate_limits(frame: pl.DataFrame) -> None:
    if (frame.null_count().sum_horizontal().item()
            or frame.select("symbol", "trade_date").is_duplicated().any()
            or frame.filter(~pl.col("up_limit").is_finite()
                            | ~pl.col("down_limit").is_finite()
                            | (pl.col("down_limit") <= 0)
                            | (pl.col("up_limit") <= pl.col("down_limit"))).height):
        raise ValueError("Invalid ETF price bands")


def refresh_limits(*, data_root: Path, symbols: list[str], end: dt.date,
                   start: dt.date = dt.date(2026, 7, 10)) -> int:
    old = read_limits(data_root)
    frames = [old]
    connector = None
    for symbol in symbols:
        dates = expected_open_dates(data_root, [symbol], start, end)
        known = set(old.filter(pl.col("symbol") == symbol)["trade_date"].to_list())
        missing = sorted(set(dates) - known)
        if not missing:
            continue
        connector = connector or TushareConnector(config_path=Path("configs/tushare.local.toml"))
        params = {"ts_code": symbol, "start_date": min(missing).strftime("%Y%m%d"),
                  "end_date": end.strftime("%Y%m%d")}
        try:
            raw = connector.query_raw("etf_limit", **params)
        except Exception:
            raise RuntimeError("ETF price-band request failed") from None
        RawStore(data_root / "raw").write(source="tushare", table="etf_limit", frame=raw,
                                           parameters=params)
        if raw.is_empty() or raw.height >= 3000:
            raise ValueError("Missing or truncated ETF price bands")
        incoming = raw.select(pl.col("ts_code").alias("symbol"),
                              pl.col("trade_date").str.to_date("%Y%m%d"),
                              pl.col("up_limit").cast(pl.Float64),
                              pl.col("down_limit").cast(pl.Float64))
        validate_limits(incoming)
        if set(incoming["symbol"]) != {symbol} or not set(missing) <= set(incoming["trade_date"]):
            raise ValueError("Incomplete ETF price-band coverage")
        frames.append(incoming.filter(pl.col("trade_date").is_in(missing)))
        time.sleep(0.4)
    result = pl.concat(frames).sort("symbol", "trade_date")
    validate_limits(result)
    if result.height > old.height:
        path = data_root / "clean/etf_limit/data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        result.write_parquet(path)
    return result.height - old.height
