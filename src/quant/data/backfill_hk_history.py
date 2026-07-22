"""CLI for one-step execution or finalization of a frozen HK history plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from quant.data.connectors.tushare import TushareConnector
from quant.data.hk_history_backfill import (
    HKHistoryBackfillError,
    execute_next_hk_history_request,
    finalize_hk_history,
    load_hk_history_plan,
)
from quant.data.storage import RawStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行冻结的 HK60 严格历史回填计划")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--journal-root", type=Path, default=Path("artifacts/hk_history_backfill")
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--confirm-uncertain-retry", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = load_hk_history_plan(args.plan)
        data_root = args.data_root.resolve()
        journal_root = args.journal_root.resolve()
        raw_store = RawStore(data_root / "raw")
        if args.finalize:
            rows = finalize_hk_history(
                plan=plan,
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=data_root / "raw",
                clean_root=data_root / "clean" / "bar_1d",
            )
            payload: dict[str, object] = {"status": "PASS", "published_rows": rows}
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
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
