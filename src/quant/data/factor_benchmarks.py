"""Capture historical monthly CSI 800 constituents for the factor battery."""
import argparse
import calendar
import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def capture_csi800(*, data_root: Path, name: str, start: dt.date, end: dt.date) -> dict:
    if not name or Path(name).name != name or name in (".", "..") or start > end:
        raise ValueError("Invalid benchmark capture request")
    output = data_root / "clean/factor_benchmarks" / name
    if output.exists():
        raise FileExistsError(output)
    client = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    store = RawStore(data_root / "raw")
    frames, requests = [], []
    month = start.replace(day=1)
    while month <= end:
        high = min(end, month.replace(day=calendar.monthrange(month.year, month.month)[1]))
        params = {"index_code": "000906.SH", "start_date": max(start, month).strftime("%Y%m%d"),
                  "end_date": high.strftime("%Y%m%d")}
        for attempt in range(3):
            try:
                frame = client.query_raw("index_weight", **params)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError(f"CSI 800 request failed in {month:%Y-%m}") from None
                time.sleep(2 + attempt)
        raw = store.write(source="tushare", table="index_weight", frame=frame, parameters=params)
        if frame.height >= 5000:
            raise ValueError(f"Possibly truncated CSI 800 response in {month:%Y-%m}")
        requests.append({"month": f"{month:%Y-%m}", "rows": frame.height, "raw": str(raw.data_path)})
        if not frame.is_empty():
            if set(frame["index_code"]) != {"000906.SH"}:
                raise ValueError("CSI 800 response contains another index")
            dates = frame["trade_date"].str.to_date("%Y%m%d")
            if not dates.is_between(max(start, month), high).all():
                raise ValueError("CSI 800 response dates differ from the requested month")
            frames.append(frame)
        if month.month == 12 or high == end:
            print(json.dumps({"through": str(high), "requests": len(requests)}), flush=True)
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        time.sleep(1.05)
    if not frames:
        raise ValueError("No CSI 800 membership observations")
    members = pl.concat(frames, how="diagonal_relaxed").select(
        pl.col("trade_date").str.to_date("%Y%m%d").alias("snapshot_date"),
        pl.col("con_code").alias("symbol"), pl.col("weight").cast(pl.Float64).alias("vendor_weight"),
    ).sort("snapshot_date", "symbol")
    if members.select("snapshot_date", "symbol").is_duplicated().any():
        raise ValueError("Duplicate CSI 800 constituent keys")
    if members.filter(~pl.col("symbol").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
        | pl.col("vendor_weight").is_null() | ~pl.col("vendor_weight").is_finite()
        | (pl.col("vendor_weight") <= 0) | ~pl.col("snapshot_date").is_between(start, end)).height:
        raise ValueError("Invalid CSI 800 membership observations")
    counts = members.group_by("snapshot_date").agg(pl.len().alias("members"),
        pl.col("vendor_weight").sum().alias("weight_sum")).sort("snapshot_date")
    empty_months = [row["month"] for row in requests if row["rows"] == 0]
    summary = {"index": "000906.SH", "start": str(start), "end": str(end), "rows": members.height,
        "snapshots": counts.height, "minimum_members": counts["members"].min(),
        "maximum_members": counts["members"].max(), "empty_months": empty_months, "raw": requests,
        "use": "latest snapshot dated at or before the signal close; equal weights, monthly rebalance"}
    output.mkdir(parents=True, exist_ok=False)
    members.write_parquet(output / "members.parquet")
    counts.write_parquet(output / "coverage.parquet")
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2009, 12, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = parser.parse_args()
    summary = capture_csi800(data_root=args.data_root, name=args.name, start=args.start, end=args.end)
    print(json.dumps({key: value for key, value in summary.items() if key != "raw"}), flush=True)


if __name__ == "__main__":
    main()
