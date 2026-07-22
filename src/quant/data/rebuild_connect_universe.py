"""从港股通基线快照和官方事件重建历史成员区间。"""

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
    build_membership_intervals,
    build_membership_intervals_from_reverse_audit,
    verify_reverse_eligibility_history,
)
from quant.data.storage import (
    CleanConnectEventStore,
    CleanConnectSnapshotStore,
    CleanUniverseMembershipStore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重建港股通历史成员区间")
    parser.add_argument("--route", choices=["SH_CONNECT", "SZ_CONNECT"], required=True)
    parser.add_argument("--baseline-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument(
        "--mode",
        choices=["snapshot", "reverse-audit"],
        default="snapshot",
    )
    parser.add_argument("--snapshot-date", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--expected-baseline-count", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    return parser


def _validate_mode_args(args: argparse.Namespace) -> None:
    """严格参数关系；任何 FS 写入前拒绝。"""
    if args.mode not in ("snapshot", "reverse-audit"):
        raise ValueError("非法 mode")
    if type(args.baseline_date) is not dt.date:
        raise ValueError("baseline_date 必须是 exact date")
    if type(args.dry_run) is not bool:
        raise ValueError("dry_run 必须是 bool")
    if args.mode == "snapshot":
        if args.snapshot_date is not None or args.expected_baseline_count is not None:
            raise ValueError("snapshot mode 禁止 --snapshot-date/--expected-baseline-count")
        return
    if args.snapshot_date is None or args.expected_baseline_count is None:
        raise ValueError("reverse-audit mode 要求 --snapshot-date/--expected-baseline-count")
    if type(args.snapshot_date) is not dt.date:
        raise ValueError("snapshot_date 必须是 exact date")
    if type(args.expected_baseline_count) is not int or args.expected_baseline_count <= 0:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")


def _success_payload(
    *,
    route: str,
    mode: str,
    baseline_date: dt.date,
    snapshot_date: dt.date,
    intervals: pl.DataFrame,
    published: bool,
) -> dict[str, object]:
    coverage_start = intervals.get_column("effective_from").min()
    if coverage_start is None or type(coverage_start) is not dt.date:
        raise ValueError("coverage_start 非法")
    return {
        "route": route,
        "mode": mode,
        "baseline_date": baseline_date.isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
        "rows": intervals.height,
        "symbols": intervals.get_column("symbol").n_unique(),
        "coverage_start": coverage_start.isoformat(),
        "open_intervals": intervals.filter(pl.col("effective_to").is_null()).height,
        "published": published,
        "status": "PASS",
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        _validate_mode_args(args)

        snapshot_store = CleanConnectSnapshotStore(
            args.data_root / "clean" / "connect_snapshot"
        )
        event_store = CleanConnectEventStore(args.data_root / "clean" / "connect_event")
        universe_store = CleanUniverseMembershipStore(
            args.data_root / "clean" / "universe_membership"
        )

        if args.mode == "snapshot":
            snapshot = snapshot_store.read_route_date(
                route=args.route, snapshot_date=args.baseline_date
            )
            events = event_store.read_route(route=args.route)
            intervals = build_membership_intervals(
                snapshot, events, route=args.route
            )
            snapshot_date = args.baseline_date
        else:
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
            intervals = build_membership_intervals_from_reverse_audit(
                audit=audit,
                snapshot=snapshot,
                events=events,
            )
            snapshot_date = audit.snapshot_date

        published = False
        if not args.dry_run:
            universe_store.replace_universe(intervals)
            published = True

        payload = _success_payload(
            route=args.route,
            mode=args.mode,
            baseline_date=args.baseline_date,
            snapshot_date=snapshot_date,
            intervals=intervals,
            published=published,
        )
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except EligibilityHistoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("REBUILD_UNIVERSE_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
