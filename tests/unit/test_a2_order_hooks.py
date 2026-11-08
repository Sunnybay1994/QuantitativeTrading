import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quant.execution import account_30w_top15_paper as paper
from quant.execution import paper_order_chain as chain


def test_order_chain_records_not_started_without_future_account_or_collection(
    tmp_path, monkeypatch
):
    config = tmp_path / "daily.toml"
    config.write_text(
        'auto_trade=false\n[q10]\nconfig="primary"\noutput="primary"\n'
        "[account_30w_top15]\nconfig="
        + json.dumps(paper.CONFIG.resolve().as_posix())
        + "\noutput="
        + json.dumps((tmp_path / "a2").as_posix())
        + "\n"
    )
    day = dt.date(2026, 11, 6)
    monkeypatch.setattr(chain, "run_q10", lambda **kwargs: dict(as_of=str(day), reference_orders=0))
    result = chain.run(config=config, end=day, output=tmp_path / "receipt")
    assert result["status"] == "complete"
    assert result["observation_accounts"]["account_30w_top15"]["status"] == "not_started"
    assert not (tmp_path / "a2").exists()


@pytest.mark.parametrize("status", ["not_due", "submitted", "failed"])
def test_notification_cli_exit_exposes_unaccepted_transport(monkeypatch, status):
    import sys

    monkeypatch.setattr(sys, "argv", ["a2", "--notify-due"])
    monkeypatch.setattr(
        paper,
        "notify_due",
        lambda **kwargs: dict(status=status, transport_accepted=status == "submitted"),
    )
    if status == "failed":
        with pytest.raises(SystemExit) as exc:
            paper.main()
        assert exc.value.code == 1
    else:
        paper.main()


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Native PowerShell required")
@pytest.mark.parametrize("notify_code", [0, 1])
def test_actual_morning_launcher_notifies_before_context_and_preserves_failure(
    tmp_path, notify_code
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    calls = tmp_path / "calls.txt"
    fake = tmp_path / "fake_python.cmd"
    fake.write_text(
        '@echo off\necho %* >> "' + str(calls) + '"\n'
        'if "%~5"=="--notify-due" exit /b ' + str(notify_code) + "\nexit /b 0\n"
    )
    original = Path("scripts/run_daily_observation.ps1").read_text(encoding="utf-8-sig")
    original = original.replace(
        "$python = 'D:\\Miniforge3\\python.exe'", "$python = '" + str(fake) + "'"
    )
    target = scripts / "run_daily_observation.ps1"
    target.write_text(original, encoding="utf-8-sig")
    wrapper = tmp_path / "probe.ps1"
    wrapper.write_text(
        "function Get-Date { param($Format)\n"
        '$clock=[datetime]"2026-11-09T08:30:00"\n'
        "if ($Format) { return $clock.ToString($Format) }; return $clock\n}\n"
        "& '" + str(target) + "'\nexit $LASTEXITCODE\n",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(wrapper)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == notify_code, result.stderr
    assert not result.stderr
    lines = calls.read_text(encoding='utf-8',errors='replace').splitlines()
    assert "account-30w-top15 --notify-due" in lines[0]
    assert "quant.research.daily_market_context" in lines[1]
    assert not any("quant research daily" in line for line in lines)
