"""Historical exchange names for point-in-time ST exclusions."""

import datetime as dt
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def capture_name_history(data_root: Path) -> pl.DataFrame:
    client = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    frames, offset = [], 0
    seen: set[tuple[object, ...]] = set()
    while True:
        parameters = {"limit": "5000", "offset": str(offset)}
        try:
            raw = client.query_raw("namechange", **parameters)
        except Exception:
            raise RuntimeError("Tushare namechange request failed") from None
        RawStore(data_root / "raw").write(source="tushare", table="namechange", frame=raw, parameters=parameters)
        if raw.is_empty():
            break
        keys = set(raw.select("ts_code", "name", "start_date", "end_date").iter_rows())
        if keys <= seen:
            raise ValueError("Name history pagination made no progress")
        seen.update(keys)
        frames.append(raw)
        offset += raw.height
        print(f"Captured name history {offset} rows", flush=True)
        time.sleep(1)
    if not frames:
        raise ValueError("No historical names")
    clean = pl.concat(frames, how="diagonal_relaxed").unique().select(
        pl.col("ts_code").alias("symbol"), "name",
        pl.col("start_date").str.to_date("%Y%m%d"), pl.col("end_date").str.to_date("%Y%m%d"),
        pl.col("ann_date").str.to_date("%Y%m%d", strict=False),
    ).filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
    if clean["start_date"].null_count():
        raise ValueError("Historical names missing effective dates")
    path = data_root / "clean/stock_name_history/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    clean.sort("symbol", "start_date").write_parquet(path)
    return clean


def read_name_history(data_root: Path, symbols: list[str], end: dt.date) -> pl.DataFrame:
    return pl.read_parquet(data_root / "clean/stock_name_history/data.parquet").filter(
        pl.col("symbol").is_in(symbols) & (pl.col("start_date") <= end))
