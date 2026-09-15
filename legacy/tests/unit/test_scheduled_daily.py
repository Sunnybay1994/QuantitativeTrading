"""M1-U0C scheduler wrapper: SUCCESS plus zero-network replay."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from quant.data.scheduled_daily import ScheduledDailyError, run_scheduled_daily

UTC = dt.timezone.utc


def _clock(*values: dt.datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _runner(statuses: list[str], calls: list[list[str]], *, mismatch: bool = False):
    def run(argv: Any) -> int:
        calls.append(list(argv))
        status = statuses.pop(0)
        print(
            json.dumps(
                {
                    "status": status,
                    "run_id": "b" * 64 if mismatch and status == "ALREADY_COMPLETE" else "a" * 64,
                    "receipt_selector": f"run_state/m1_daily/{'a' * 64}/receipt.json",
                },
                separators=(",", ":"),
            )
        )
        return 0

    return run


def test_success_requires_new_run_then_same_identity_replay(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    start = dt.datetime(2026, 7, 20, 13, 30, tzinfo=UTC)
    result = run_scheduled_daily(
        session_date=dt.date(2026, 7, 20),
        symbols=("000001.SZ", "600000.SH", "00005.HK", "00700.HK"),
        data_root=tmp_path / "data",
        artifact_root=tmp_path / "artifacts",
        runner=_runner(["SUCCESS", "ALREADY_COMPLETE"], calls),
        clock=_clock(start, start + dt.timedelta(seconds=2)),
    )
    assert len(calls) == 2 and calls[0] == calls[1]
    assert "--without-adjustment-factors" in calls[0]
    assert result.run_id == "a" * 64
    payload = result.as_dict()
    assert payload["status"] == "SUCCESS"
    assert payload["replay_status"] == "ALREADY_COMPLETE"
    assert payload["exit_code"] == 0


def test_first_already_complete_does_not_count_as_scheduled_success(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    with pytest.raises(ScheduledDailyError, match="FIRST_NOT_SUCCESS") as exc_info:
        run_scheduled_daily(
            session_date=dt.date(2026, 7, 20),
            symbols=("000001.SZ",),
            data_root=tmp_path,
            artifact_root=tmp_path,
            runner=_runner(["ALREADY_COMPLETE"], calls),
            clock=_clock(dt.datetime(2026, 7, 20, tzinfo=UTC)),
        )
    assert len(calls) == 1
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_replay_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    with pytest.raises(ScheduledDailyError, match="IDENTITY_MISMATCH"):
        run_scheduled_daily(
            session_date=dt.date(2026, 7, 20),
            symbols=("000001.SZ",),
            data_root=tmp_path,
            artifact_root=tmp_path,
            runner=_runner(["SUCCESS", "ALREADY_COMPLETE"], calls, mismatch=True),
            clock=_clock(dt.datetime(2026, 7, 20, tzinfo=UTC)),
        )


def test_runner_exception_is_sanitized_without_context(tmp_path: Path) -> None:
    def boom(_argv: Any) -> int:
        raise RuntimeError("secret-token-and-path")

    with pytest.raises(ScheduledDailyError) as exc_info:
        run_scheduled_daily(
            session_date=dt.date(2026, 7, 20),
            symbols=("000001.SZ",),
            data_root=tmp_path,
            artifact_root=tmp_path,
            runner=boom,
            clock=_clock(dt.datetime(2026, 7, 20, tzinfo=UTC)),
        )
    assert str(exc_info.value) == "M1_SCHEDULE_RUNNER_FAILED"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_non_utc_clock_rejected_before_runner(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    with pytest.raises(ScheduledDailyError, match="CLOCK_INVALID"):
        run_scheduled_daily(
            session_date=dt.date(2026, 7, 20),
            symbols=("000001.SZ",),
            data_root=tmp_path,
            artifact_root=tmp_path,
            runner=_runner(["SUCCESS"], calls),
            clock=_clock(dt.datetime(2026, 7, 20)),
        )
    assert calls == []


@pytest.mark.parametrize(
    ("run_id", "selector"),
    [
        ("leaked-secret", "run_state/m1_daily/leaked-secret/receipt.json"),
        ("A" * 64, f"run_state/m1_daily/{'A' * 64}/receipt.json"),
        ("a" * 64, r"C:\Users\owner\token.txt"),
        ("a" * 64, f"run_state/m1_daily/{'b' * 64}/receipt.json"),
        ("a" * 64, f"../run_state/m1_daily/{'a' * 64}/receipt.json"),
    ],
)
def test_unsafe_log_identity_fails_closed(
    tmp_path: Path, run_id: str, selector: str
) -> None:
    statuses = iter(("SUCCESS", "ALREADY_COMPLETE"))

    def runner(_argv: Any) -> int:
        print(
            json.dumps(
                {
                    "status": next(statuses),
                    "run_id": run_id,
                    "receipt_selector": selector,
                }
            )
        )
        return 0

    with pytest.raises(ScheduledDailyError) as exc_info:
        run_scheduled_daily(
            session_date=dt.date(2026, 7, 20),
            symbols=("000001.SZ",),
            data_root=tmp_path / "data",
            artifact_root=tmp_path / "artifacts",
            runner=runner,
            clock=_clock(
                dt.datetime(2026, 7, 20, tzinfo=UTC),
                dt.datetime(2026, 7, 20, 0, 0, 1, tzinfo=UTC),
            ),
        )

    assert str(exc_info.value) == "M1_SCHEDULE_RESULT_INVALID"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
