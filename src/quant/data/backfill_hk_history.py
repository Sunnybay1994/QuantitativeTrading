"""CLI for one-step execution or finalization of a frozen HK history plan.

Explicit v3 finalize trusts write-once/no-clobber retained inputs and caller
quiescence through consumption of the verified bundle.  The anchored loader
does not independently make two externally writable paths jointly immutable.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Sequence

from quant.data.connectors.tushare import TushareConnector
from quant.data.hk_history_backfill import (
    HKHistoryBackfillError,
    execute_next_hk_history_request,
    finalize_hk_history,
    load_verified_hkex_retained_bundle_for_finalize,
    load_hk_history_plan,
    recover_existing_hk_history_requests,
)
from quant.data.storage import RawStore

_PUBLIC_FAILURE_CODES = frozenset(
    {
        "HK_HISTORY_API_FAILED",
        "HK_HISTORY_ATTEMPT_UNCERTAIN",
        "HK_HISTORY_AVAILABILITY_INVALID",
        "HK_HISTORY_AVAILABILITY_UNSUPPORTED",
        "HK_HISTORY_COOLDOWN_ACTIVE",
        "HK_HISTORY_FINALIZE_V3_INVALID",
        "HK_HISTORY_INCOMPLETE",
        "HK_HISTORY_INPUT_INVALID",
        "HK_HISTORY_PLAN_CONFLICT",
        "HK_HISTORY_PUBLISH_CONFLICT",
        "HK_HISTORY_PUBLISH_FAILED",
        "HK_HISTORY_RAW_INVALID",
        "HK_HISTORY_REFERENCE_INVALID",
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行冻结的 HK60 严格历史回填计划")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--journal-root", type=Path, default=Path("artifacts/hk_history_backfill")
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--finalize-v3", action="store_true")
    parser.add_argument("--confirm-uncertain-retry", action="store_true")
    parser.add_argument("--recover-existing-only", action="store_true")
    parser.add_argument("--hkex-retained-raw", type=Path)
    parser.add_argument("--hkex-retained-metadata", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failure: str | None = None
    try:
        _validate_modes(args)
        if args.finalize_v3:
            _validate_finalize_paths(
                plan_path=args.plan,
                journal_root=args.journal_root,
                raw_root=args.data_root / "raw",
                clean_root=args.data_root / "clean" / "bar_1d",
            )
        plan = load_hk_history_plan(args.plan)
        data_root = args.data_root.resolve()
        journal_root = args.journal_root.resolve()
        raw_root = data_root / "raw"
        clean_root = data_root / "clean" / "bar_1d"
        raw_store = RawStore(raw_root)
        if args.recover_existing_only:
            if args.finalize or args.confirm_uncertain_retry:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
            result = recover_existing_hk_history_requests(
                plan=plan,
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=data_root / "raw",
            )
            payload: dict[str, object] = {
                "status": "PASS",
                "request_id": result.request_id,
                "network_requests": result.network_requests,
                "completed_requests": result.completed_requests,
                "total_requests": result.total_requests,
                "is_complete": result.is_complete,
                "recover_existing_only": True,
            }
        elif args.finalize_v3:
            bundle = load_verified_hkex_retained_bundle_for_finalize(
                args.hkex_retained_raw,
                args.hkex_retained_metadata,
            )
            rows = finalize_hk_history(
                plan=plan,
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=raw_root,
                clean_root=clean_root,
                hkex_retained_bundle=bundle,
            )
            payload = {
                "status": "PASS",
                "finalize_schema_version": "hk-history-finalize-v3",
                "published_rows": rows,
                "retained_bundle_id": bundle.bundle_id,
                "retained_metadata_identity": bundle.metadata.metadata_identity,
            }
        elif args.finalize:
            try:
                hkex_retained_raw = (
                    None
                    if args.hkex_retained_raw is None
                    else args.hkex_retained_raw.read_bytes()
                )
            except OSError:
                raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
            rows = finalize_hk_history(
                plan=plan,
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=raw_root,
                clean_root=clean_root,
                hkex_retained_raw=hkex_retained_raw,
            )
            payload = {"status": "PASS", "published_rows": rows}
        else:
            result = execute_next_hk_history_request(
                plan=plan,
                connector=TushareConnector(config_path=args.config),
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=data_root / "raw",
                confirm_uncertain_retry=args.confirm_uncertain_retry,
            )
            payload = {
                "status": "PASS",
                "request_id": result.request_id,
                "network_requests": result.network_requests,
                "completed_requests": result.completed_requests,
                "total_requests": result.total_requests,
                "is_complete": result.is_complete,
            }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except HKHistoryBackfillError as exc:
        code = str(exc)
        failure = (
            code if code in _PUBLIC_FAILURE_CODES else "HK_HISTORY_REFERENCE_INVALID"
        )
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    print(failure, file=sys.stderr)
    return 1


def _validate_modes(args: argparse.Namespace) -> None:
    if args.finalize_v3:
        if (
            args.finalize
            or args.recover_existing_only
            or args.confirm_uncertain_retry
            or args.hkex_retained_raw is None
            or args.hkex_retained_metadata is None
        ):
            raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None
        return
    if args.hkex_retained_metadata is not None or (
        args.hkex_retained_raw is not None and not args.finalize
    ):
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


def _validate_finalize_paths(
    *, plan_path: Path, journal_root: Path, raw_root: Path, clean_root: Path
) -> None:
    failed = False
    try:
        roots = tuple(_safe_role_path(path) for path in (journal_root, raw_root, clean_root))
        for index, left in enumerate(roots):
            for right in roots[index + 1 :]:
                if _contains(left, right) or _contains(right, left):
                    raise ValueError
                if left.exists() and right.exists() and os.path.samefile(left, right):
                    raise ValueError
        plan = _safe_role_path(plan_path)
        if any(_contains(root, plan) for root in roots):
            raise ValueError
    except Exception:
        failed = True
    if failed:
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


def _safe_role_path(path: Path) -> Path:
    absolute = path.absolute()
    resolved = path.resolve(strict=False)
    if absolute != resolved:
        raise ValueError
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        try:
            info = os.lstat(cursor)
        except FileNotFoundError:
            continue
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError
    return absolute


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
