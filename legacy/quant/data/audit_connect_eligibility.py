"""港股通资格历史逆向审计 CLI：只读、零网络、严格 JSON。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence

import polars as pl

from quant.data.eligibility import (
    EligibilityHistoryError,
    build_membership_intervals_from_reverse_audit,
    verify_reverse_eligibility_history,
)
from quant.data.storage import CleanConnectEventStore, CleanConnectSnapshotStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读逆向审计港股通资格历史")
    parser.add_argument("--route", choices=["SH_CONNECT", "SZ_CONNECT"], required=True)
    parser.add_argument("--snapshot-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--baseline-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--expected-baseline-count", type=int, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--preview-membership",
        action="store_true",
        default=False,
        help="audit PASS 后只读预览成员区间统计，不写 universe",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if type(args.expected_baseline_count) is not int or args.expected_baseline_count <= 0:
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
        if type(args.snapshot_date) is not dt.date or type(args.baseline_date) is not dt.date:
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")

        snapshot_store = CleanConnectSnapshotStore(
            args.data_root / "clean" / "connect_snapshot"
        )
        event_store = CleanConnectEventStore(args.data_root / "clean" / "connect_event")
        snapshot = snapshot_store.read_route_date(
            route=args.route, snapshot_date=args.snapshot_date
        )
        events = event_store.read_route(route=args.route)
        audit = verify_reverse_eligibility_history(
            snapshot,
            events,
            route=args.route,
            baseline_date=args.baseline_date,
            expected_baseline_count=args.expected_baseline_count,
        )
        payload = {
            "route": audit.route,
            "baseline_date": audit.baseline_date.isoformat(),
            "snapshot_date": audit.snapshot_date.isoformat(),
            "expected_baseline_count": audit.expected_baseline_count,
            "current_count": audit.current_count,
            "event_count": audit.event_count,
            "reverse_count": audit.reverse_count,
            "event_min": None
            if audit.event_min_date is None
            else audit.event_min_date.isoformat(),
            "event_max": None
            if audit.event_max_date is None
            else audit.event_max_date.isoformat(),
            "status": "PASS",
        }
        if args.preview_membership:
            intervals = build_membership_intervals_from_reverse_audit(
                audit=audit,
                snapshot=snapshot,
                events=events,
            )
            coverage_start = intervals.get_column("effective_from").min()
            if coverage_start is None or type(coverage_start) is not dt.date:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID")
            payload["membership_rows"] = intervals.height
            payload["membership_symbols"] = intervals.get_column("symbol").n_unique()
            payload["coverage_start"] = coverage_start.isoformat()
            payload["open_intervals"] = intervals.filter(
                pl.col("effective_to").is_null()
            ).height
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except EligibilityHistoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("REVERSE_AUDIT_INPUT_INVALID", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
