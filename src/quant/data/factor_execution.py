"""Capture daily historical price bands for the factor battery and portfolios."""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.factor_panels import available_sessions
from quant.data.storage import RawStore


def capture_limits(*, data_root: Path, name: str, start: dt.date, end: dt.date) -> dict:
    if not name or Path(name).name != name or name in (".", "..") or start > end:
        raise ValueError("Invalid historical limits request")
    folder = data_root / "clean/factor_execution" / name
    client = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    raw_store = RawStore(data_root / "raw")
    dates = [d for d in available_sessions(data_root, end) if d >= start]
    if not dates:
        raise ValueError("No exchange sessions in the requested limits range")
    years = []
    for year in range(start.year, end.year + 1):
        expected = [d for d in dates if d.year == year]
        if not expected:
            continue
        output = folder / f"year={year}"
        summary_file = output / "summary.json"
        if summary_file.is_file() and (output / "limits.parquet").is_file():
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
            if summary["dates"] != [str(d) for d in expected]:
                raise ValueError("Use a new limits version for a changed date range")
            years.append(summary)
            continue
        if output.exists():
            raise FileExistsError(f"Incomplete limits output: {output}")
        frames, sources = [], []
        for date in expected:
            params = {"trade_date": date.strftime("%Y%m%d")}
            for attempt in range(3):
                try:
                    raw = client.query_raw("stk_limit", **params)
                    break
                except Exception:
                    if attempt == 2:
                        raise RuntimeError(f"Historical limits request failed on {date}") from None
                    time.sleep(2 + attempt)
            saved = raw_store.write(source="tushare", table="stk_limit", frame=raw, parameters=params)
            if raw.is_empty() or raw.height >= 5800:
                raise ValueError(f"Empty or possibly truncated limits on {date}")
            if set(raw["trade_date"]) != {params["trade_date"]}:
                raise ValueError("Historical limit response date differs")
            frame = raw.filter(pl.col("ts_code").str.contains(r"^[0-9]{6}\.(SH|SZ)$")).select(
                pl.col("ts_code").alias("symbol"), pl.lit(date).alias("trade_date"),
                pl.col("up_limit").cast(pl.Float64), pl.col("down_limit").cast(pl.Float64))
            if frame.is_empty() or frame["symbol"].is_duplicated().any():
                raise ValueError(f"Invalid historical limit keys on {date}")
            frames.append(frame)
            sources.append({"date": str(date), "rows": raw.height, "raw": str(saved.data_path)})
            time.sleep(1.05)
        limits = pl.concat(frames).sort("trade_date", "symbol")
        output.mkdir(parents=True, exist_ok=False)
        limits.write_parquet(output / "limits.parquet")
        summary = {"year": year, "dates": [str(d) for d in expected], "rows": limits.height,
                   "symbols": limits["symbol"].n_unique(), "raw": sources}
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        years.append(summary)
        print(json.dumps({"year": year, "dates": len(expected), "rows": limits.height}), flush=True)
    result = {"start": str(start), "end": str(end), "years": len(years),
        "sessions": sum(len(r["dates"]) for r in years), "rows": sum(r["rows"] for r in years)}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2010, 1, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = parser.parse_args()
    print(json.dumps(capture_limits(data_root=args.data_root, name=args.name, start=args.start, end=args.end)))


if __name__ == "__main__":
    main()
