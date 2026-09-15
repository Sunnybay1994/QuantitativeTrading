"""Offline verifier for five scheduler-owned M1 daily receipts and logs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from quant.data.calendar import expected_open_dates
from quant.data.daily_run import build_daily_run_spec, verify_daily_receipt

_LOG_SCHEMA = "m1-scheduled-daily-v1"
_LOG_KEYS = {
    "schema_version",
    "status",
    "date",
    "started_at",
    "finished_at",
    "run_id",
    "receipt_selector",
    "replay_status",
    "exit_code",
}


class DailyStreakAuditError(ValueError):
    """Stable, sanitized offline streak audit error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def audit_daily_streak(
    *,
    dates: Sequence[dt.date],
    symbols: Sequence[str],
    data_root: Path,
    artifact_root: Path,
    log_root: Path,
) -> dict[str, object]:
    """Verify exactly five consecutive common sessions without network access."""
    if isinstance(dates, (str, bytes)) or isinstance(symbols, (str, bytes)):
        raise DailyStreakAuditError("M1_STREAK_INPUT_INVALID")
    session_dates = tuple(dates)
    canonical_symbols = tuple(symbols)
    if (
        len(session_dates) != 5
        or session_dates != tuple(sorted(set(session_dates)))
        or any(type(value) is not dt.date for value in session_dates)
        or not canonical_symbols
        or any(type(value) is not str for value in canonical_symbols)
    ):
        raise DailyStreakAuditError("M1_STREAK_INPUT_INVALID")
    if not all(isinstance(path, Path) for path in (data_root, artifact_root, log_root)):
        raise DailyStreakAuditError("M1_STREAK_INPUT_INVALID")

    calendar_error = False
    try:
        expected = tuple(
            sorted(
                expected_open_dates(
                    data_root,
                    list(canonical_symbols),
                    session_dates[0],
                    session_dates[-1],
                )
            )
        )
    except Exception:
        calendar_error = True
        expected = ()
    if calendar_error or expected != session_dates:
        raise DailyStreakAuditError("M1_STREAK_CALENDAR_INVALID")

    verified_dates: list[str] = []
    for session_date in session_dates:
        receipt_error = False
        spec = None
        receipt = None
        try:
            spec = build_daily_run_spec(
                data_root=data_root,
                session_date=session_date,
                source="tushare",
                symbols=canonical_symbols,
                use_adjustment_factors=False,
            )
            receipt = verify_daily_receipt(
                spec=spec, data_root=data_root, artifact_root=artifact_root
            )
        except Exception:
            receipt_error = True
        if receipt_error or spec is None or receipt is None:
            raise DailyStreakAuditError("M1_STREAK_RECEIPT_INVALID")
        log = _read_log(log_root / f"{session_date.isoformat()}.json")
        if (
            log["date"] != session_date.isoformat()
            or log["run_id"] != spec.run_id
            or log["run_id"] != receipt.run_id
            or log["receipt_selector"] != receipt.receipt_selector
        ):
            raise DailyStreakAuditError("M1_STREAK_LOG_INVALID")
        verified_dates.append(session_date.isoformat())
    return {
        "schema_version": "m1-daily-streak-audit-v1",
        "status": "PASS",
        "sessions": len(verified_dates),
        "dates": verified_dates,
    }


def _read_log(path: Path) -> dict[str, object]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise DailyStreakAuditError("M1_STREAK_LOG_INVALID") from None
    lines = text.splitlines()
    parsed: object | None = None
    if len(lines) == 1:
        try:
            parsed = json.loads(lines[0])
        except (TypeError, ValueError):
            pass
    if type(parsed) is not dict or set(parsed) != _LOG_KEYS:
        raise DailyStreakAuditError("M1_STREAK_LOG_INVALID")
    if (
        parsed["schema_version"] != _LOG_SCHEMA
        or parsed["status"] != "SUCCESS"
        or parsed["replay_status"] != "ALREADY_COMPLETE"
        or parsed["exit_code"] != 0
        or any(type(parsed[key]) is not str for key in _LOG_KEYS - {"exit_code"})
    ):
        raise DailyStreakAuditError("M1_STREAK_LOG_INVALID")
    started = _parse_utc(parsed["started_at"])
    finished = _parse_utc(parsed["finished_at"])
    if started is None or finished is None or finished < started:
        raise DailyStreakAuditError("M1_STREAK_LOG_INVALID")
    return parsed


def _parse_utc(value: object) -> dt.datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    parsed: dt.datetime | None = None
    try:
        parsed = dt.datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        pass
    if parsed is None or parsed.utcoffset() != dt.timedelta(0):
        return None
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return parsed if canonical == value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线验真 M1 五交易日调度证据")
    parser.add_argument("--dates", required=True, nargs=5, type=dt.date.fromisoformat)
    parser.add_argument("--symbols", required=True, nargs="+")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--log-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = audit_daily_streak(
            dates=args.dates,
            symbols=args.symbols,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            log_root=args.log_root,
        )
    except DailyStreakAuditError as exc:
        print(json.dumps({"status": "FAILED", "code": exc.code}, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DailyStreakAuditError", "audit_daily_streak"]
