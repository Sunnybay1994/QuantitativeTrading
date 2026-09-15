"""clean bar_1d 跨源收盘价比较 CLI。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

import polars as pl

from quant.data.comparison import compare_closes, write_comparison_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="比较两个 clean bar_1d 数据源")
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--symbols", required=True, nargs="+")
    parser.add_argument("--primary", default="akshare")
    parser.add_argument("--reference", default="baostock")
    parser.add_argument("--tolerance", type=float, default=0.005)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.start > args.end:
        raise ValueError("start 不得晚于 end")
    parquet_glob = args.data_root / "clean" / "bar_1d" / "date=*" / "data.parquet"
    frame = pl.read_parquet(parquet_glob).filter(
        pl.col("symbol").is_in(args.symbols)
        & pl.col("trade_date").is_between(args.start, args.end)
    )
    primary = frame.filter(pl.col("source") == args.primary)
    reference = frame.filter(pl.col("source") == args.reference)
    if primary.is_empty() or reference.is_empty():
        raise ValueError(
            f"比较区间缺少数据: {args.primary}={primary.height}, "
            f"{args.reference}={reference.height}"
        )
    report = compare_closes(primary, reference, tolerance=args.tolerance)
    output = (
        args.artifact_root
        / "data_quality"
        / "cross_source"
        / f"{args.start.isoformat()}_{args.end.isoformat()}_{args.primary}_{args.reference}.json"
    )
    write_comparison_report(report, output)
    print(json.dumps({"report_path": str(output), **report.__dict__}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
