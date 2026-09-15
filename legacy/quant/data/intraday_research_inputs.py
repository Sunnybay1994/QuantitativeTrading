"""Daily ETF prices and turnover for the minute-strategy cost map."""

import datetime as dt
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def prepare_etf_daily(*, data_root: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    members = tomllib.loads(Path("configs/universe/t0_etf_pool_v1.toml").read_text(encoding="utf-8"))["members"]
    client = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    frames = []
    for member in members:
        parameters = {"ts_code": member["symbol"], "start_date": start.strftime("%Y%m%d"),
                      "end_date": end.strftime("%Y%m%d")}
        raw = client.query_raw("fund_daily", **parameters)
        RawStore(data_root / "raw").write(source="tushare", table="fund_daily", frame=raw, parameters=parameters)
        if raw.is_empty() or raw.height >= 2000 or set(raw["ts_code"]) != {member["symbol"]}:
            raise ValueError("Missing, truncated or unexpected ETF daily response")
        frames.append(raw.select(
            pl.col("ts_code").alias("symbol"), pl.col("trade_date").str.to_date("%Y%m%d"),
            pl.col("open", "high", "low", "close", "pre_close").cast(pl.Float64),
            (pl.col("pct_chg").cast(pl.Float64) / 100).alias("return"),
            (pl.col("vol").cast(pl.Float64) * 100).alias("volume"),
            (pl.col("amount").cast(pl.Float64) * 1000).alias("amount"),
        ))
        time.sleep(1)
    frame = pl.concat(frames).sort("symbol", "trade_date")
    path = data_root / "clean/intraday_research/etf_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return frame


def read_etf_daily(data_root: Path) -> pl.DataFrame:
    return pl.read_parquet(data_root / "clean/intraday_research/etf_daily.parquet")


def read_etf_minutes(data_root: Path, symbol: str, frequency: str, source: str) -> pl.DataFrame:
    return pl.read_parquet(data_root / "clean/bar_intraday" / f"freq={frequency}"
                           / f"source={source}" / f"symbol={symbol}" / "data.parquet")
