"""CLI for one scheduler-owned SUCCESS + ALREADY_COMPLETE daily run."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from quant.data.scheduled_daily import ScheduledDailyError, run_scheduled_daily


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 M1 调度日更并立即验真重放")
    parser.add_argument("--date", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--symbols", required=True, nargs="+")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_scheduled_daily(
            session_date=args.date,
            symbols=args.symbols,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
        )
    except ScheduledDailyError as exc:
        print(json.dumps({"status": "FAILED", "code": exc.code}, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result.as_dict(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
