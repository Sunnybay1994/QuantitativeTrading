"""沪深日线多日回补 CLI。"""

import argparse
import datetime as dt
from pathlib import Path
from typing import Sequence

from quant.data.calendar import expected_open_dates
from quant.data.update import _print_result, build_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按 clean 交易日历回补沪深日线")
    parser.add_argument("--start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--symbols", required=True, nargs="+")
    parser.add_argument(
        "--source", choices=["tushare", "akshare", "baostock"], default="tushare"
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--without-adjustment-factors", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    open_dates = expected_open_dates(args.data_root, args.symbols, args.start, args.end)
    if not open_dates:
        raise RuntimeError("指定区间没有开市日")
    result = build_pipeline(
        args.source,
        args.data_root,
        args.artifact_root,
        use_adjustment_factors=not args.without_adjustment_factors,
    ).update(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        expected_dates=open_dates,
    )
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
