"""Dated stock price bands; retrieval partitions are not exchange sessions."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.refresh_stocks import read_stock_data
from quant.data.storage import RawStore

KEYS = ["symbol", "trade_date"]


def validate_limits(frame: pl.DataFrame, as_of: dt.date) -> None:
    if (frame.is_empty() or frame["trade_date"].unique().to_list() != [as_of]
            or frame.select(KEYS).is_duplicated().any()
            or frame.select(*KEYS, "up_limit", "down_limit").null_count().sum_horizontal().item()
            or frame.filter(~pl.col("up_limit").is_finite() | ~pl.col("down_limit").is_finite()
                            | (pl.col("down_limit") < 0)
                            | (pl.col("up_limit") < pl.col("down_limit"))).height):
        raise ValueError("Invalid current-session stock price bands")


def read_saved_limits(
    data_root: Path, as_of: dt.date, required_keys: pl.DataFrame,
) -> tuple[pl.DataFrame, Path, dict] | None:
    """Read original receipts including late arrivals, without backdating them.

    Only metadata in retrieval partitions on/after the requested session is
    inspected. A matching request, payload date and checksum are all required.
    Consumers record the actual receipt path; this is recovery data, not proof
    that a late response was available on the historical session.
    """
    root = data_root / "raw/tushare/stk_limit"
    for folder in sorted(root.glob("date=*"), reverse=True):
        try:
            received_day = dt.date.fromisoformat(folder.name.removeprefix("date="))
        except ValueError:
            continue
        if received_day < as_of:
            continue
        for metadata in sorted(folder.glob("*.json"), reverse=True):
            receipt = json.loads(metadata.read_text(encoding="utf-8"))
            if receipt.get("parameters", {}).get("trade_date") != as_of.strftime("%Y%m%d"):
                continue
            path = metadata.with_suffix(".parquet")
            payload = path.read_bytes()
            if (receipt.get("source") != "tushare" or receipt.get("table") != "stk_limit"
                    or receipt.get("checksum_sha256") != hashlib.sha256(payload).hexdigest()):
                raise ValueError("Stock price-band source receipt/checksum mismatch")
            fetched = dt.datetime.fromisoformat(receipt["fetched_at"])
            if fetched.tzinfo is None or fetched.astimezone(dt.timezone.utc).date() != received_day:
                raise ValueError("Invalid stock price-band receipt time")
            raw = pl.read_parquet(path)
            if raw.is_empty() or raw["trade_date"].unique().to_list() != [as_of.strftime("%Y%m%d")]:
                raise ValueError("Current raw limits are empty or wrong-date")
            frame = raw.filter(pl.col("ts_code").str.contains(r"^\d{6}\.(SH|SZ)$")).select(
                pl.col("ts_code").alias("symbol"), pl.lit(as_of).alias("trade_date"),
                pl.col("up_limit").cast(pl.Float64), pl.col("down_limit").cast(pl.Float64))
            validate_limits(frame, as_of)
            if required_keys.join(frame.select(KEYS), on=KEYS, how="anti").is_empty():
                return frame, path, receipt
    return None


def refresh_stock_limits(*, data_root: Path, config: Path, end: dt.date) -> dict:
    """Fetch one full-session response only if saved complete raw is absent."""
    bars = read_stock_data(data_root=data_root, config=config, table="bar_1d", start=end, end=end)
    required = bars.select(KEYS)
    if required.is_empty() or required.is_duplicated().any():
        raise ValueError("Cannot refresh stock limits without unique same-session stock bars")
    saved = read_saved_limits(data_root, end, required)
    fetched = saved is None
    if fetched:
        connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
        params = {"trade_date": end.strftime("%Y%m%d")}
        try:
            raw = connector.query_raw("stk_limit", **params)
        except Exception:
            raise RuntimeError("Stock price-band request failed") from None
        RawStore(data_root / "raw").write(source="tushare", table="stk_limit", frame=raw, parameters=params)
        saved = read_saved_limits(data_root, end, required)
    if saved is None:
        raise ValueError(f"Incomplete stock price-band coverage for {end}")
    frame, source, receipt = saved
    return {"as_of": str(end), "rows": frame.height, "required_keys": required.height,
            "new_rows": frame.height if fetched else 0, "source": str(source),
            "fetched_at": receipt["fetched_at"], "checksum_sha256": receipt["checksum_sha256"]}
