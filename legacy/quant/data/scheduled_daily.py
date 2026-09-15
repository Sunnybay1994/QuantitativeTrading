"""Strict two-pass wrapper for one scheduler-owned M1 daily run."""

from __future__ import annotations

import datetime as dt
import io
import json
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant.data.run_daily import main as daily_main

_SCHEMA_VERSION = "m1-scheduled-daily-v1"


class ScheduledDailyError(ValueError):
    """Stable scheduler wrapper failure without nested exception details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ScheduledDailyResult:
    """Sanitized evidence from SUCCESS followed by ALREADY_COMPLETE."""

    session_date: dt.date
    started_at: dt.datetime
    finished_at: dt.datetime
    run_id: str
    receipt_selector: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": "SUCCESS",
            "date": self.session_date.isoformat(),
            "started_at": _utc_text(self.started_at),
            "finished_at": _utc_text(self.finished_at),
            "run_id": self.run_id,
            "receipt_selector": self.receipt_selector,
            "replay_status": "ALREADY_COMPLETE",
            "exit_code": 0,
        }


Runner = Callable[[Sequence[str] | None], int]
Clock = Callable[[], dt.datetime]


def run_scheduled_daily(
    *,
    session_date: dt.date,
    symbols: Sequence[str],
    data_root: Path,
    artifact_root: Path,
    runner: Runner = daily_main,
    clock: Clock = lambda: dt.datetime.now(dt.timezone.utc),
) -> ScheduledDailyResult:
    """Require a new SUCCESS and an immediate zero-network verified replay."""
    if type(session_date) is not dt.date or isinstance(symbols, (str, bytes)):
        raise ScheduledDailyError("M1_SCHEDULE_INPUT_INVALID")
    canonical_symbols = tuple(symbols)
    if not canonical_symbols or any(type(value) is not str for value in canonical_symbols):
        raise ScheduledDailyError("M1_SCHEDULE_INPUT_INVALID")
    if not isinstance(data_root, Path) or not isinstance(artifact_root, Path):
        raise ScheduledDailyError("M1_SCHEDULE_INPUT_INVALID")
    if not callable(runner) or not callable(clock):
        raise ScheduledDailyError("M1_SCHEDULE_INPUT_INVALID")

    started_at = _require_clock(clock())
    argv = [
        "--source",
        "tushare",
        "--date",
        session_date.isoformat(),
        "--symbols",
        *canonical_symbols,
        "--without-adjustment-factors",
        "--data-root",
        str(data_root),
        "--artifact-root",
        str(artifact_root),
    ]
    first = _invoke(runner, argv)
    if first.get("status") != "SUCCESS":
        raise ScheduledDailyError("M1_SCHEDULE_FIRST_NOT_SUCCESS")
    replay = _invoke(runner, argv)
    if replay.get("status") != "ALREADY_COMPLETE":
        raise ScheduledDailyError("M1_SCHEDULE_REPLAY_NOT_COMPLETE")
    if (
        replay.get("run_id") != first.get("run_id")
        or replay.get("receipt_selector") != first.get("receipt_selector")
    ):
        raise ScheduledDailyError("M1_SCHEDULE_REPLAY_IDENTITY_MISMATCH")
    run_id = first.get("run_id")
    selector = first.get("receipt_selector")
    if not _is_safe_identity(run_id, selector):
        raise ScheduledDailyError("M1_SCHEDULE_RESULT_INVALID")
    assert isinstance(run_id, str)
    assert isinstance(selector, str)
    finished_at = _require_clock(clock())
    if finished_at < started_at:
        raise ScheduledDailyError("M1_SCHEDULE_CLOCK_INVALID")
    return ScheduledDailyResult(
        session_date=session_date,
        started_at=started_at,
        finished_at=finished_at,
        run_id=run_id,
        receipt_selector=selector,
    )


def _invoke(runner: Runner, argv: Sequence[str]) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    runner_failed = False
    exit_code = -1
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = runner(argv)
    except Exception:
        runner_failed = True
    if runner_failed or exit_code != 0 or stderr.getvalue():
        raise ScheduledDailyError("M1_SCHEDULE_RUNNER_FAILED")
    lines = stdout.getvalue().splitlines()
    parsed: object | None = None
    if len(lines) == 1:
        try:
            parsed = json.loads(lines[0])
        except (TypeError, ValueError):
            pass
    if type(parsed) is not dict:
        raise ScheduledDailyError("M1_SCHEDULE_RESULT_INVALID")
    if set(parsed) != {"status", "run_id", "receipt_selector"}:
        raise ScheduledDailyError("M1_SCHEDULE_RESULT_INVALID")
    return parsed


def _require_clock(value: object) -> dt.datetime:
    if type(value) is not dt.datetime:
        raise ScheduledDailyError("M1_SCHEDULE_CLOCK_INVALID")
    assert isinstance(value, dt.datetime)
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise ScheduledDailyError("M1_SCHEDULE_CLOCK_INVALID")
    return value


def _is_safe_identity(run_id: object, selector: object) -> bool:
    if type(run_id) is not str or type(selector) is not str:
        return False
    assert isinstance(run_id, str)
    assert isinstance(selector, str)
    return (
        len(run_id) == 64
        and all(character in "0123456789abcdef" for character in run_id)
        and selector == f"run_state/m1_daily/{run_id}/receipt.json"
    )


def _utc_text(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = ["ScheduledDailyError", "ScheduledDailyResult", "run_scheduled_daily"]
