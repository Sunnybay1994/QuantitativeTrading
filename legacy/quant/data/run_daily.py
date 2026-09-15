"""Receipt-backed M1 daily update CLI.

Example::

    python -m quant.data.run_daily --date 2026-07-10 --symbols 000001.SZ
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence

from quant.data.daily_run import (
    M1DailyRunError,
    build_daily_run_spec,
    execute_daily_run,
)
from quant.data.update import build_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit-date operational daily runner parser."""
    parser = argparse.ArgumentParser(description="运行带不可变完成收据的 M1 单日更新")
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--symbols", required=True, nargs="+", help="标准证券代码列表")
    parser.add_argument(
        "--source",
        choices=["tushare", "akshare", "baostock"],
        default="tushare",
        help="原始数据源",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--without-adjustment-factors",
        action="store_true",
        help="显式仅保存不复权行情；不得用于需要复权收益的研究",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one strict daily spec and print a sanitized single-line result."""
    args = build_parser().parse_args(argv)
    try:
        spec = build_daily_run_spec(
            data_root=args.data_root,
            session_date=args.date,
            source=args.source,
            symbols=args.symbols,
            use_adjustment_factors=not args.without_adjustment_factors,
        )

        def update():  # type: ignore[no-untyped-def]
            pipeline = build_pipeline(
                spec.source,
                args.data_root,
                args.artifact_root,
                use_adjustment_factors=spec.use_adjustment_factors,
            )
            return pipeline.update(
                symbols=list(spec.symbols),
                start=spec.session_date,
                end=spec.session_date,
                expected_dates={spec.session_date},
            )

        result = execute_daily_run(
            spec=spec,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            update=update,
        )
    except M1DailyRunError as exc:
        print(
            json.dumps({"status": "FAILED", "code": exc.code}, separators=(",", ":")),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": result.status,
                "run_id": result.run_id,
                "receipt_selector": result.receipt_selector,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
