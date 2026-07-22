"""M1-U0C offline audit of five logs and verified daily receipts."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.data.audit_daily_streak as audit_mod
from quant.data.audit_daily_streak import DailyStreakAuditError, audit_daily_streak


DATES = tuple(dt.date(2026, 7, day) for day in range(20, 25))
SYMBOLS = ("000001.SZ", "600000.SH", "00005.HK", "00700.HK")


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_mod, "expected_open_dates", lambda *_a, **_k: set(DATES))

    def build(*, session_date: dt.date, **_kwargs: object) -> object:
        return SimpleNamespace(run_id=f"{session_date.day:064x}")

    def verify(*, spec: object, **_kwargs: object) -> object:
        run_id = spec.run_id  # type: ignore[attr-defined]
        return SimpleNamespace(
            run_id=run_id,
            receipt_selector=f"run_state/m1_daily/{run_id}/receipt.json",
        )

    monkeypatch.setattr(audit_mod, "build_daily_run_spec", build)
    monkeypatch.setattr(audit_mod, "verify_daily_receipt", verify)


def _write_logs(root: Path) -> None:
    root.mkdir()
    for session_date in DATES:
        run_id = f"{session_date.day:064x}"
        payload = {
            "schema_version": "m1-scheduled-daily-v1",
            "status": "SUCCESS",
            "date": session_date.isoformat(),
            "started_at": "2026-07-20T13:30:00.000000Z",
            "finished_at": "2026-07-20T13:30:02.000000Z",
            "run_id": run_id,
            "receipt_selector": f"run_state/m1_daily/{run_id}/receipt.json",
            "replay_status": "ALREADY_COMPLETE",
            "exit_code": 0,
        }
        (root / f"{session_date.isoformat()}.json").write_text(
            json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
        )


def test_five_exact_common_sessions_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fakes(monkeypatch)
    logs = tmp_path / "logs"
    _write_logs(logs)
    result = audit_daily_streak(
        dates=DATES,
        symbols=SYMBOLS,
        data_root=tmp_path / "data",
        artifact_root=tmp_path / "artifacts",
        log_root=logs,
    )
    assert result["status"] == "PASS"
    assert result["sessions"] == 5


def test_missing_common_session_fails_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_mod, "expected_open_dates", lambda *_a, **_k: set(DATES[:-1]))
    called = {"n": 0}

    def build(**_kwargs: object) -> object:
        called["n"] += 1
        raise AssertionError

    monkeypatch.setattr(audit_mod, "build_daily_run_spec", build)
    with pytest.raises(DailyStreakAuditError, match="CALENDAR_INVALID"):
        audit_daily_streak(
            dates=DATES, symbols=SYMBOLS, data_root=tmp_path,
            artifact_root=tmp_path, log_root=tmp_path,
        )
    assert called["n"] == 0


def test_tampered_log_identity_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fakes(monkeypatch)
    logs = tmp_path / "logs"
    _write_logs(logs)
    path = logs / "2026-07-22.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_id"] = "f" * 64
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(DailyStreakAuditError, match="LOG_INVALID"):
        audit_daily_streak(
            dates=DATES, symbols=SYMBOLS, data_root=tmp_path,
            artifact_root=tmp_path, log_root=logs,
        )


def test_receipt_failure_is_sanitized_without_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fakes(monkeypatch)
    logs = tmp_path / "logs"
    _write_logs(logs)

    def boom(**_kwargs: object) -> object:
        raise RuntimeError("secret path and token")

    monkeypatch.setattr(audit_mod, "verify_daily_receipt", boom)
    with pytest.raises(DailyStreakAuditError) as exc_info:
        audit_daily_streak(
            dates=DATES, symbols=SYMBOLS, data_root=tmp_path,
            artifact_root=tmp_path, log_root=logs,
        )
    assert str(exc_info.value) == "M1_STREAK_RECEIPT_INVALID"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
