"""Sanitized M1 daily CLI behavior."""

from __future__ import annotations

import datetime as dt

from quant.data.daily_run import (
    CalendarSessionV1,
    DailyRunResult,
    DailyRunSpecV1,
    M1DailyRunError,
)
from quant.data.run_daily import main


def _spec() -> DailyRunSpecV1:
    day = dt.date(2026, 7, 10)
    return DailyRunSpecV1(
        session_date=day,
        source="tushare",
        symbols=("000001.SZ",),
        use_adjustment_factors=False,
        calendar_sessions=(
            CalendarSessionV1(
                market="SZ",
                date=day,
                is_open=True,
                is_connect_open=False,
                is_half_day=False,
            ),
        ),
    )


def test_cli_replay_is_lazy_and_prints_only_relative_selector(
    monkeypatch, capsys
) -> None:
    spec = _spec()
    monkeypatch.setattr("quant.data.run_daily.build_daily_run_spec", lambda **_kwargs: spec)
    monkeypatch.setattr(
        "quant.data.run_daily.build_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must stay lazy")),
    )

    def replay(**kwargs):
        del kwargs
        return DailyRunResult(
            status="ALREADY_COMPLETE",
            run_id=spec.run_id,
            receipt_selector=f"run_state/m1_daily/{spec.run_id}/receipt.json",
        )

    monkeypatch.setattr("quant.data.run_daily.execute_daily_run", replay)
    assert main(
        [
            "--date", "2026-07-10", "--symbols", "000001.SZ",
            "--without-adjustment-factors",
        ]
    ) == 0
    captured = capsys.readouterr()
    assert '"status":"ALREADY_COMPLETE"' in captured.out
    assert "run_state/m1_daily/" in captured.out
    assert "F:\\" not in captured.out
    assert "/home/" not in captured.out
    assert captured.err == ""


def test_cli_failure_prints_only_stable_code(monkeypatch, capsys) -> None:
    def fail(**_kwargs):
        raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID")

    monkeypatch.setattr("quant.data.run_daily.build_daily_run_spec", fail)
    assert main(["--date", "2026-07-10", "--symbols", "000001.SZ"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        '{"status":"FAILED","code":"M1_DAILY_CALENDAR_INVALID"}'
    )
    assert "/home/private" not in captured.err
    assert "C:\\private" not in captured.err
