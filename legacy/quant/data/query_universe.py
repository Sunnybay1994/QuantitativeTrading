"""查询指定时点港股通股票池的历史日线窗口。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence, cast

from quant.data.eligibility import EligibilityHistoryError
from quant.data.hk_history_backfill import (
    HKHistoryBackfillError,
    load_hk_history_plan,
    load_verified_hk_bar_bundle,
    verify_hk_bar_bundle,
)
from quant.data.query import (
    AvailableHistoryCoverage,
    AuditedBarWindow,
    AuditedMixedSourceBarWindow,
    BarQuery,
    BarWindowCoverage,
    BarWindowQueryError,
    MixedSourceBarWindowCoverage,
)
from quant.data.storage import RawStore

_HK_PUBLIC_FAILURE_CODES = frozenset(
    {
        "HK_BAR_PUBLICATION_INVALID",
        "HK_BAR_VERIFY_FAILED",
        "HK_HISTORY_AVAILABILITY_UNSUPPORTED",
        "HK_HISTORY_FINALIZE_V3_INVALID",
        "HK_HISTORY_PLAN_CONFLICT",
        "HK_HISTORY_REFERENCE_INVALID",
    }
)


def _coverage_payload(
    coverage: BarWindowCoverage | MixedSourceBarWindowCoverage,
) -> dict[str, object]:
    return {
        "universe": coverage.universe,
        "as_of": coverage.as_of.isoformat(),
        "source": coverage.source,
        "requested_observations": coverage.requested_observations,
        "eligible_symbol_count": coverage.eligible_symbol_count,
        "returned_symbol_count": coverage.returned_symbol_count,
        "missing_symbols": list(coverage.missing_symbols),
        "short_symbol_counts": [[symbol, count] for symbol, count in coverage.short_symbol_counts],
        "min_observations": coverage.min_observations,
        "max_observations": coverage.max_observations,
        "is_full_window": coverage.is_full_window,
    }


def _available_history_payload(
    coverage: AvailableHistoryCoverage,
) -> dict[str, object]:
    structurally_short = [
        [symbol, len(dates)]
        for symbol, dates in coverage.required_sessions
        if len(dates) < coverage.requested_observations
    ]
    missing_counts = [[symbol, len(dates)] for symbol, dates in coverage.missing_sessions]
    unexpected_counts = [[symbol, len(dates)] for symbol, dates in coverage.unexpected_sessions]
    return {
        "eligible_symbol_count": coverage.eligible_symbol_count,
        "required_stock_symbol_count": coverage.required_stock_symbol_count,
        "excluded_etf_symbols": list(coverage.excluded_etf_symbols),
        "structurally_short_symbol_counts": structurally_short,
        "missing_session_counts": missing_counts,
        "unexpected_session_counts": unexpected_counts,
        "missing_session_total": sum(len(dates) for _, dates in coverage.missing_sessions),
        "unexpected_session_total": sum(len(dates) for _, dates in coverage.unexpected_sessions),
        "exempted_session_count": coverage.exempted_session_count,
        "exemption_reason_counts": [
            [reason, count] for reason, count in coverage.exemption_reason_counts
        ],
        "no_trade_evidence_sha256": coverage.no_trade_evidence_sha256,
        "min_required_sessions": coverage.min_required_sessions,
        "max_required_sessions": coverage.max_required_sessions,
        "is_available_history_complete": coverage.is_available_history_complete,
    }


def _success_report(
    audited: AuditedBarWindow | AuditedMixedSourceBarWindow,
    *,
    output: Path | None,
    available_history: AvailableHistoryCoverage | None = None,
    verification_as_of: dt.datetime | None = None,
) -> dict[str, object]:
    frame = audited.frame
    first_trade_date = cast(dt.date, frame.get_column("trade_date").min()) if frame.height else None
    last_trade_date = cast(dt.date, frame.get_column("trade_date").max()) if frame.height else None
    report = _coverage_payload(audited.coverage)
    report.update(
        {
            "rows": frame.height,
            "symbols": (frame.get_column("symbol").n_unique() if frame.height else 0),
            "first_trade_date": (first_trade_date.isoformat() if first_trade_date else None),
            "last_trade_date": (last_trade_date.isoformat() if last_trade_date else None),
            "output": output.as_posix() if output is not None else None,
        }
    )
    if available_history is not None:
        report["available_history"] = _available_history_payload(available_history)
    if isinstance(audited.coverage, MixedSourceBarWindowCoverage):
        report["plan_sha256"] = audited.coverage.plan_sha256
        report["publication_sha256"] = audited.coverage.publication_sha256
        report["availability_content_sha256"] = audited.coverage.availability_content_sha256
        report["source_row_counts"] = [
            [source, count] for source, count in audited.coverage.source_row_counts
        ]
        if verification_as_of is not None:
            report["verification_as_of"] = _canonical_verification_as_of(verification_as_of)
    return report


def _incomplete_payload(
    coverage: BarWindowCoverage | MixedSourceBarWindowCoverage,
) -> dict[str, object]:
    payload = _coverage_payload(coverage)
    payload["code"] = "BAR_WINDOW_INCOMPLETE"
    return payload


def _available_history_incomplete_payload(
    coverage: BarWindowCoverage | MixedSourceBarWindowCoverage,
    available_history: AvailableHistoryCoverage,
    *,
    verification_as_of: dt.datetime | None = None,
) -> dict[str, object]:
    payload = _coverage_payload(coverage)
    if isinstance(coverage, MixedSourceBarWindowCoverage):
        payload["plan_sha256"] = coverage.plan_sha256
        payload["publication_sha256"] = coverage.publication_sha256
        payload["availability_content_sha256"] = coverage.availability_content_sha256
        payload["source_row_counts"] = [
            [source, count] for source, count in coverage.source_row_counts
        ]
        if verification_as_of is not None:
            payload["verification_as_of"] = _canonical_verification_as_of(verification_as_of)
    payload["available_history"] = _available_history_payload(available_history)
    payload["code"] = "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    return payload


def _canonical_verification_as_of(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def _parse_verification_as_of(value: object) -> dt.datetime:
    if type(value) is not str or not value:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if parsed.tzinfo is None:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    offset = parsed.utcoffset()
    if offset is None or offset != dt.timedelta(0):
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    return parsed.astimezone(dt.timezone.utc)


def _public_hk_cli_code(error: HKHistoryBackfillError) -> str:
    code = str(error)
    if code in _HK_PUBLIC_FAILURE_CODES:
        return code
    return "HK_HISTORY_REFERENCE_INVALID"


def _run_mixed(
    args: argparse.Namespace,
) -> tuple[AuditedMixedSourceBarWindow, AvailableHistoryCoverage, dt.datetime]:
    if args.require_full_window:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if not args.require_available_history:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if args.plan is None or args.journal_root is None or args.verification_as_of is None:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if not isinstance(args.plan, Path) or not isinstance(args.journal_root, Path):
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    verification_as_of = _parse_verification_as_of(args.verification_as_of)
    try:
        plan = load_hk_history_plan(args.plan)
    except HKHistoryBackfillError:
        raise
    except Exception:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if dt.date.fromisoformat(plan.as_of) != args.as_of:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    data_root = args.data_root
    raw_root = data_root / "raw"
    clean_root = data_root / "clean"
    bar_root = clean_root / "bar_1d"
    membership_path = (
        clean_root / "universe_membership" / f"universe={args.universe}" / "data.parquet"
    )
    bundle = load_verified_hk_bar_bundle(
        plan=plan,
        journal_root=args.journal_root,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=bar_root,
        as_of=verification_as_of,
    )
    query = BarQuery(bar_root)
    audited = query.recent_for_universe_mixed_audited(
        membership_path=membership_path,
        universe=args.universe,
        as_of=args.as_of,
        observations=args.observations,
        bundle=bundle,
        plan=plan,
    )
    available_audited = query.audit_available_history_mixed(
        audited=audited,
        calendar_path=(clean_root / "trade_calendar" / "market=HK" / "data.parquet"),
        instrument_path=(clean_root / "instrument" / "market=HK" / "data.parquet"),
        eligibility_snapshot_root=(clean_root / "connect_snapshot"),
        eligibility_event_root=(clean_root / "connect_event"),
        no_trade_evidences=plan.no_trade_evidence,
        no_trade_evidence_sha256=plan.no_trade_evidence_sha256,
    )
    verify_hk_bar_bundle(
        bundle,
        plan=plan,
        journal_root=args.journal_root,
        seed_raw_root=raw_root,
        raw_store=RawStore(raw_root),
        clean_root=bar_root,
        as_of=verification_as_of,
    )
    return audited, available_audited.available_history, verification_as_of


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询时点股票池的最近 N 个行情观测")
    parser.add_argument("--universe", choices=("SH_CONNECT", "SZ_CONNECT"), required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--source")
    parser.add_argument(
        "--from-verified-hk-availability",
        action="store_true",
        default=False,
    )
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--journal-root", type=Path)
    parser.add_argument("--verification-as-of")
    parser.add_argument("--observations", type=int, default=60)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-full-window",
        action="store_true",
        default=False,
        help="缺少证券或任一证券观测数 < N 时失败且不写 output",
    )
    parser.add_argument(
        "--require-available-history",
        action="store_true",
        default=False,
        help="按 HK 日历和上市区间审计每只股票的精确应有交易日",
    )
    args = parser.parse_args(argv)

    try:
        if type(args.observations) is not int or args.observations <= 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        mixed = bool(args.from_verified_hk_availability)
        has_source = args.source is not None
        if mixed == has_source:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if mixed:
            if args.source is not None:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
            audited, available_history, verification_as_of = _run_mixed(args)
            if not available_history.is_available_history_complete:
                print(
                    json.dumps(
                        _available_history_incomplete_payload(
                            audited.coverage,
                            available_history,
                            verification_as_of=verification_as_of,
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                return 1
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                audited.frame.write_parquet(args.output)
            print(
                json.dumps(
                    _success_report(
                        audited,
                        output=args.output,
                        available_history=available_history,
                        verification_as_of=verification_as_of,
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 0
        if (
            args.plan is not None
            or args.journal_root is not None
            or (args.verification_as_of is not None)
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        clean_root = args.data_root / "clean"
        membership_path = (
            clean_root / "universe_membership" / f"universe={args.universe}" / "data.parquet"
        )
        query = BarQuery(clean_root / "bar_1d")
        audited_single = query.recent_for_universe_audited(
            membership_path=membership_path,
            universe=args.universe,
            as_of=args.as_of,
            source=args.source,
            observations=args.observations,
        )
        if args.require_full_window and not audited_single.coverage.is_full_window:
            print(
                json.dumps(
                    _incomplete_payload(audited_single.coverage),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 1
        available_history_single: AvailableHistoryCoverage | None = None
        if args.require_available_history:
            available_audited = query.audit_available_history(
                audited=audited_single,
                calendar_path=(clean_root / "trade_calendar" / "market=HK" / "data.parquet"),
                instrument_path=(clean_root / "instrument" / "market=HK" / "data.parquet"),
                eligibility_snapshot_root=(clean_root / "connect_snapshot"),
                eligibility_event_root=(clean_root / "connect_event"),
                no_trade_evidence_path=(clean_root / "hk_no_trade_evidence" / "evidence.json"),
                no_trade_raw_root=(args.data_root / "raw"),
            )
            available_history_single = available_audited.available_history
            if not available_history_single.is_available_history_complete:
                print(
                    json.dumps(
                        _available_history_incomplete_payload(
                            audited_single.coverage, available_history_single
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                return 1
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            audited_single.frame.write_parquet(args.output)
        print(
            json.dumps(
                _success_report(
                    audited_single,
                    output=args.output,
                    available_history=available_history_single,
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    except BarWindowQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except HKHistoryBackfillError as exc:
        print(_public_hk_cli_code(exc), file=sys.stderr)
        return 1
    except EligibilityHistoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("BAR_WINDOW_INPUT_INVALID", file=sys.stderr)
        return 1
    except OSError:
        print("BAR_WINDOW_REFERENCE_INVALID", file=sys.stderr)
        return 1
    except ValueError:
        print("BAR_WINDOW_INPUT_INVALID", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
