"""Completed Yahoo GC daily reference prices for the B33 design screen."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from quant.data.connectors.yahoo_intraday import fetch_chart
from quant.data.storage import RawStore

RELATIVE_PATH = Path("clean/gold_reference_1d/source=yahoo/symbol=GC_F/data.parquet")
SCHEMA = pl.Schema({
    "reference_date": pl.Date(),
    "available_at": pl.Datetime("us", "UTC"),
    "close": pl.Float64(),
    "reference_return": pl.Float64(),
})
NEW_YORK = ZoneInfo("America/New_York")


def normalize_gold_reference(payload: dict[str, Any], *, as_of: dt.datetime) -> pl.DataFrame:
    """Use 18:00 New York, one hour after normal GC close, as availability.

    Yahoo labels daily records at midnight, or 09:30 on some holiday dates,
    in its exchange timezone. Both labels belong to the same reference date.
    The extra hour is a conservative historical availability assumption, not
    evidence of the original publication time. Never forward-fill null closes.
    """
    if as_of.tzinfo is None:
        raise ValueError("Gold reference as_of must be timezone-aware")
    chart = payload.get("chart", {})
    results = chart.get("result")
    if chart.get("error") or not results or len(results) != 1:
        raise ValueError("Missing Yahoo gold chart")
    result = results[0]
    meta = result["meta"]
    if meta.get("symbol") != "GC=F" or meta.get("exchangeTimezoneName") != "America/New_York":
        raise ValueError("Unexpected gold reference symbol or timezone")
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    if not timestamps or len(timestamps) != len(closes):
        raise ValueError("Gold timestamps and closes differ")
    rows = []
    for stamp, close in zip(timestamps, closes, strict=True):
        local = dt.datetime.fromtimestamp(stamp, NEW_YORK)
        if local.time() not in (dt.time(), dt.time(9, 30)):
            raise ValueError("Unexpected Yahoo daily timestamp convention")
        date = local.date()
        available = dt.datetime.combine(date, dt.time(18), NEW_YORK).astimezone(dt.timezone.utc)
        rows.append({"reference_date": date, "available_at": available, "close": close})
    frame = pl.DataFrame(rows, schema={k: v for k, v in SCHEMA.items() if k != "reference_return"})
    if frame["reference_date"].n_unique() != frame.height:
        raise ValueError("Duplicate gold reference dates")
    if frame.filter(pl.col("close").is_not_null() & (~pl.col("close").is_finite() | (pl.col("close") <= 0))).height:
        raise ValueError("Invalid gold reference price")
    return frame.sort("reference_date").filter(pl.col("available_at") <= as_of).with_columns(
        (pl.col("close") / pl.col("close").shift(1) - 1).alias("reference_return")
    )


def read_gold_reference(data_root: Path) -> pl.DataFrame:
    return pl.read_parquet(data_root / RELATIVE_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--raw", type=Path, help="Rebuild clean from a saved raw response")
    args = parser.parse_args()
    raw_path = args.raw
    if raw_path is None:
        payload = fetch_chart("GC=F", "1d")
        raw_path = RawStore(args.data_root / "raw").write(
            source="yahoo_gold", table="GC_F_daily",
            frame=pl.DataFrame({"payload_json": [json.dumps(payload)]}),
            parameters={"symbol": "GC=F", "frequency": "1d", "range": "2y"},
        ).data_path
    else:
        payload = json.loads(pl.read_parquet(raw_path)["payload_json"][0])
    frame = normalize_gold_reference(payload, as_of=dt.datetime.now(dt.timezone.utc))
    if frame.is_empty():
        raise ValueError("No completed gold reference days")
    path = args.data_root / RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    print(json.dumps({"raw": str(raw_path), "output": str(path), "rows": frame.height,
                      "start": str(frame["reference_date"].min()),
                      "end": str(frame["reference_date"].max())}))


if __name__ == "__main__":
    main()
