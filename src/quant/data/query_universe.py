"""查询指定时点港股通股票池的历史日线窗口。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence, cast

from quant.data.eligibility import EligibilityHistoryError
from quant.data.query import (
    AvailableHistoryCoverage,
    AuditedBarWindow,
    BarQuery,
    BarWindowCoverage,
    BarWindowQueryError,
)


def _coverage_payload(coverage: BarWindowCoverage) -> dict[str, object]:
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
        "min_required_sessions": coverage.min_required_sessions,
        "max_required_sessions": coverage.max_required_sessions,
        "is_available_history_complete": coverage.is_available_history_complete,
    }


def _success_report(
    audited: AuditedBarWindow,
    *,
    output: Path | None,
    available_history: AvailableHistoryCoverage | None = None,
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
    return report


def _incomplete_payload(coverage: BarWindowCoverage) -> dict[str, object]:
    payload = _coverage_payload(coverage)
    payload["code"] = "BAR_WINDOW_INCOMPLETE"
    return payload


def _available_history_incomplete_payload(
    coverage: BarWindowCoverage,
    available_history: AvailableHistoryCoverage,
) -> dict[str, object]:
    payload = _coverage_payload(coverage)
    payload["available_history"] = _available_history_payload(available_history)
    payload["code"] = "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE"
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询时点股票池的最近 N 个行情观测")
    parser.add_argument("--universe", choices=("SH_CONNECT", "SZ_CONNECT"), required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--source", required=True)
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
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        clean_root = args.data_root / "clean"
        membership_path = (
            clean_root / "universe_membership" / f"universe={args.universe}" / "data.parquet"
        )
        query = BarQuery(clean_root / "bar_1d")
        audited = query.recent_for_universe_audited(
            membership_path=membership_path,
            universe=args.universe,
            as_of=args.as_of,
            source=args.source,
            observations=args.observations,
        )
        if args.require_full_window and not audited.coverage.is_full_window:
            print(
                json.dumps(
                    _incomplete_payload(audited.coverage),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 1
        available_history: AvailableHistoryCoverage | None = None
        if args.require_available_history:
            available_audited = query.audit_available_history(
                audited=audited,
                calendar_path=(clean_root / "trade_calendar" / "market=HK" / "data.parquet"),
                instrument_path=(clean_root / "instrument" / "market=HK" / "data.parquet"),
                eligibility_snapshot_root=(clean_root / "connect_snapshot"),
                eligibility_event_root=(clean_root / "connect_event"),
            )
            available_history = available_audited.available_history
            if not available_history.is_available_history_complete:
                print(
                    json.dumps(
                        _available_history_incomplete_payload(audited.coverage, available_history),
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
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    except BarWindowQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except EligibilityHistoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("BAR_WINDOW_INPUT_INVALID", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
