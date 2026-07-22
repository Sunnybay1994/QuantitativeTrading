"""从已留档 raw 日线重新执行 mapper、质量门禁和 clean 写入。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

import polars as pl

from quant.data.calendar import expected_open_dates
from quant.data.mappers import AkshareBarMapper, BaostockBarMapper, BarMapper, TushareBarMapper
from quant.data.quality import validate_bars, write_quality_report
from quant.data.storage import CleanBarStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 raw 快照重处理不复权日线")
    parser.add_argument("--raw-path", type=Path, required=True)
    parser.add_argument("--source", choices=["tushare", "akshare", "baostock"], required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--date", type=dt.date.fromisoformat)
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start, end = _resolve_range(args.date, args.start, args.end)
    if not args.raw_path.exists() or args.raw_path.suffix != ".parquet":
        raise FileNotFoundError(f"raw Parquet 不存在: {args.raw_path}")
    mappers: dict[str, BarMapper] = {
        "tushare": TushareBarMapper(),
        "akshare": AkshareBarMapper(),
        "baostock": BaostockBarMapper(),
    }
    mapper = mappers[args.source]
    raw = pl.read_parquet(args.raw_path)
    clean = mapper.map(raw)
    clean = clean.filter(
        pl.col("symbol").is_in(args.symbols)
        & pl.col("trade_date").is_between(start, end, closed="both")
    )
    dates = expected_open_dates(args.data_root, args.symbols, start, end)
    if not dates:
        raise RuntimeError("指定区间没有开市日")
    report = validate_bars(
        clean,
        expected_dates=dates,
        expected_symbols=set(args.symbols),
        missing_rate_limit=0.0,
    )
    report_path = (
        args.artifact_root / "data_quality/bar_1d/reprocess"
        / f"{args.raw_path.stem}.json"
    )
    write_quality_report(report, report_path)
    rows = CleanBarStore(args.data_root / "clean/bar_1d").upsert(clean)
    print(json.dumps({
        "raw_path": str(args.raw_path), "clean_rows": rows,
        "quality_passed": report.passed, "adjustment_factors_applied": False,
        "start": start.isoformat(), "end": end.isoformat(),
    }, ensure_ascii=False))
    return 0


def _resolve_range(
    date: dt.date | None,
    start: dt.date | None,
    end: dt.date | None,
) -> tuple[dt.date, dt.date]:
    if date is not None:
        if start is not None or end is not None:
            raise ValueError("--date 不能与 --start/--end 同时使用")
        return date, date
    if start is None or end is None:
        raise ValueError("必须提供 --date，或同时提供 --start 和 --end")
    if start > end:
        raise ValueError("start 不得晚于 end")
    return start, end


if __name__ == "__main__":
    raise SystemExit(main())
