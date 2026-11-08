"""Quota-aware, year-resumable minute backfill for a fixed download priority pool.

Clean keeps the provider's timestamp and opening row explicitly, without imposing
the existing 240-bar research convention. No strategy is switched to this source.
"""

import argparse
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.connectors.futu_history import history_page, history_quota, open_quotes


def normalize(frame: pl.DataFrame, symbol: str, start: str, end: str) -> pl.DataFrame:
    code, market = symbol.split(".")
    if set(frame["code"].unique()) != {f"{market}.{code}"}:
        raise ValueError("Unexpected provider symbol")
    result = frame.select(
        pl.lit(symbol).alias("symbol"),
        pl.col("time_key").str.to_datetime("%Y-%m-%d %H:%M:%S")
        .dt.replace_time_zone("Asia/Shanghai").alias("bar_time"),
        *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")],
        pl.col("turnover").cast(pl.Float64).alias("amount"),
    ).with_columns(
        pl.col("bar_time").dt.date().alias("trade_date"),
        (pl.col("bar_time").dt.strftime("%H:%M:%S") == "09:30:00")
        .alias("is_opening_row"),
        pl.lit("futu").alias("source"),
        pl.lit("none").alias("adjustment"),
    ).filter(pl.col("trade_date").is_between(dt.date.fromisoformat(start),
                                             dt.date.fromisoformat(end)))
    if result.is_empty():
        raise ValueError("No bars in requested date range")
    if result["bar_time"].n_unique() != result.height:
        raise ValueError("Duplicate provider timestamps")
    numeric = ["open", "high", "low", "close", "volume", "amount"]
    if result.null_count().sum_horizontal().item() or result.filter(
        pl.any_horizontal([~pl.col(c).is_finite() for c in numeric])
        | pl.any_horizontal([pl.col(c) <= 0 for c in numeric[:4]])
        | (pl.col("volume") < 0) | (pl.col("amount") < 0)
        | (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
    ).height:
        raise ValueError("Invalid provider OHLCV")
    return result.sort("bar_time")


def fetch_history_pages(context: Any, symbol: str, start: str, end: str,
                         raw_directory: Path) -> tuple[pl.DataFrame, int]:
    """Append-only raw pages; caller decides whether to replace or merge clean."""
    raw_directory.mkdir(parents=True, exist_ok=False)
    page_key = None
    frames = []
    for page in range(1000):
        from quant.core.capital_window import checkpoint as capital_checkpoint
        capital_checkpoint()
        # Only initial pages are subject to the 60/30s history rate limit.
        if page == 0:
            time.sleep(2.1)
        frame, page_key = history_page(context, symbol, start, end, page_key)
        raw = pl.from_pandas(frame)
        raw.write_parquet(raw_directory / f"page_{page:04d}.parquet", compression="zstd")
        frames.append(raw)
        capital_checkpoint()
        if not page_key:
            break
    else:
        raise RuntimeError("Excessive pagination")
    return pl.concat(frames, how="vertical_relaxed"), len(frames)


def write_clean(clean_path: Path, clean: pl.DataFrame) -> None:
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = clean_path.with_suffix(".tmp.parquet")
    clean.write_parquet(temporary, compression="zstd")
    temporary.replace(clean_path)


def merge_clean(clean_path: Path, incoming: pl.DataFrame) -> pl.DataFrame:
    """Keep prior year bars; same-day top-up must not wipe earlier months."""
    old = pl.read_parquet(clean_path) if clean_path.exists() else incoming.head(0)
    merged = pl.concat([old, incoming], how="diagonal_relaxed").unique(
        subset=["symbol", "bar_time"], keep="last", maintain_order=True,
    ).sort("bar_time")
    write_clean(clean_path, merged)
    return merged


def download_year(context: Any, symbol: str, start: str, end: str,
                  raw_directory: Path, clean_path: Path) -> dict[str, Any]:
    joined, pages = fetch_history_pages(context, symbol, start, end, raw_directory)
    if joined.is_empty():
        return {"symbol": symbol, "start": start, "end": end, "rows": 0,
                "raw": str(raw_directory), "empty": True}
    clean = normalize(joined, symbol, start, end)
    write_clean(clean_path, clean)
    counts = clean.group_by("trade_date").len()["len"]
    return dict(symbol=symbol, start=start, end=end, rows=clean.height,
                days=counts.len(), first=str(clean["bar_time"].min()),
                last=str(clean["bar_time"].max()), days_241=int((counts == 241).sum()),
                days_other=int((counts != 241).sum()), raw=str(raw_directory),
                clean=str(clean_path), pages=pages)


def download_range_merge(context: Any, symbol: str, start: str, end: str,
                         raw_directory: Path, clean_path: Path) -> dict[str, Any]:
    """Fetch [start, end] and merge into an existing year partition (same-day top-up)."""
    joined, pages = fetch_history_pages(context, symbol, start, end, raw_directory)
    if joined.is_empty():
        return {"symbol": symbol, "start": start, "end": end, "rows": 0,
                "raw": str(raw_directory), "empty": True, "merged": False,
                "clean": str(clean_path)}
    incoming = normalize(joined, symbol, start, end)
    merged = merge_clean(clean_path, incoming)
    counts = merged.group_by("trade_date").len()["len"]
    return dict(symbol=symbol, start=start, end=end, rows=incoming.height,
                merged_rows=merged.height, days=counts.len(),
                first=str(merged["bar_time"].min()), last=str(merged["bar_time"].max()),
                days_241=int((counts == 241).sum()), days_other=int((counts != 241).sum()),
                raw=str(raw_directory), clean=str(clean_path), pages=pages, merged=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards <= 4:
        raise ValueError("Use 1 to 4 disjoint download shards")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "summary.json"
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "plan": str(args.plan), "results": [], "errors": [],
    }
    clean_root = Path("data/clean/futu_minute") / args.plan.stem
    context = open_quotes()
    try:
        used, remaining, charged = history_quota(context)
        report["quota_before"] = {"used": used, "remaining": remaining}
        print(f"quota used={used} remaining={remaining}", flush=True)
        for member in plan["members"][args.shard::args.shards]:
            symbol = member["symbol"]
            if symbol not in charged:
                used, remaining, charged = history_quota(context)
                if remaining <= plan["quota_reserve"]:
                    report["quota_pause"] = symbol
                    break
            for year in range(int(plan["end"][:4]), int(plan["start"][:4]) - 1, -1):
                start = max(plan["start"], f"{year}-01-01")
                end = min(plan["end"], f"{year}-12-31")
                clean_path = clean_root / f"symbol={symbol}" / f"year={year}" / "data.parquet"
                if clean_path.exists():
                    continue
                raw_path = (Path("data/raw/futu/minute_backfill") / f"symbol={symbol}"
                            / f"year={year}" / dt.datetime.now().strftime("%Y%m%dT%H%M%S%f"))
                try:
                    result = download_year(context, symbol, start, end, raw_path, clean_path)
                    report["results"].append(result)
                    charged.add(symbol)
                    print(json.dumps(result), flush=True)
                except Exception as exc:
                    report["errors"].append({"symbol": symbol, "year": year,
                                             "error": str(exc), "raw": str(raw_path)})
                    print(f"download error {symbol} {year}: {exc}", flush=True)
                    # Keep raw and continue other symbols rather than repeated failing requests.
                    break
                finally:
                    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        used, remaining, _ = history_quota(context)
        report["quota_after"] = {"used": used, "remaining": remaining}
    finally:
        context.close()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
