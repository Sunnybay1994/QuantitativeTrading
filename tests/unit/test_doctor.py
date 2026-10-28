import datetime as dt
import json
from zoneinfo import ZoneInfo

import polars as pl

from quant.cli import main
from quant.reporting.doctor import collect, notify_red, render_markdown

SH = ZoneInfo("Asia/Shanghai")
NOW = dt.datetime(2026, 10, 26, 22, 0, tzinfo=SH)


def _tree(tmp_path):
    day = "2026-10-26"
    cal = tmp_path / "data" / "clean" / "trade_calendar" / "market=SH"
    cal.mkdir(parents=True)
    pl.DataFrame({"date": [dt.date(2026, 10, 26)], "is_open": [True]}).write_parquet(cal / "data.parquet")
    daily = tmp_path / "artifacts" / "daily" / "sue_v2" / f"{day}_213000"
    daily.mkdir(parents=True)
    (daily / "summary.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    q10 = tmp_path / "artifacts" / "paper" / "q10_sue_v2" / day
    q10.mkdir(parents=True)
    (q10 / "state.json").write_text("{}", encoding="utf-8")
    mining = tmp_path / "artifacts" / "research" / "continuous" / "batch_000076" / day
    mining.mkdir(parents=True)
    (mining / "summary.json").write_text(json.dumps({
        "steps": {step: {"ok": True} for step in ("N1", "N2", "N3", "N4", "N5")}
    }), encoding="utf-8")
    (mining.parent.parent / "status.json").write_text(json.dumps({
        "failure_kind": None, "consecutive_failures": 0, "state": "completed"
    }), encoding="utf-8")
    registry = tmp_path / "artifacts" / "registry"
    registry.mkdir(parents=True)
    pl.DataFrame({
        "run_path": [str(tmp_path / "artifacts" / "models" / "q10")],
        "experiment_id": ["q10"],
        "variant": ["budgeted"],
    }).write_parquet(registry / "experiments.parquet")
    ledger = tmp_path / "artifacts" / "research" / "llm_ledger"
    ledger.mkdir(parents=True)
    (ledger / "2026-10.jsonl").write_text(
        json.dumps({"task": "brief", "usd": 0.2, "tokens": 10}) + "\n", encoding="utf-8")
    tests = tmp_path / "artifacts" / "tests"
    tests.mkdir()
    (tests / "latest.json").write_text(json.dumps({
        "ran_at": NOW.isoformat(), "exit_code": 0, "passed": 3, "failed": 0, "duration_seconds": 1
    }), encoding="utf-8")
    return tmp_path


def test_clean_tree_has_no_red_when_git_is_fresh(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    monkeypatch.setattr("quant.reporting.doctor._git_facts", lambda _root: {
        "dirty": 0, "days_since_commit": 0, "root_scratch_py": 0, "git_ok": True,
    })
    report = collect(root=root, now=NOW, tasks=[{
        "name": "QuantitativeTrading-IntelWeekly", "last_run_time": NOW.isoformat(), "result": 0,
    }])
    assert report["red"] == []
    assert report["scheduled_tasks"][0]["name"].endswith("IntelWeekly")
    assert report["scheduled_tasks"][0]["result"] == 0
    assert "IntelWeekly" in render_markdown(report)


def test_known_failures_are_red(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    outside = tmp_path / "artifacts" / "registry" / "experiments.parquet"
    pl.DataFrame({
        "run_path": [r"C:\Temp\pytest\run", str(tmp_path / "artifacts" / "models" / "q10")],
        "experiment_id": ["q10", "q10"],
        "variant": ["budgeted", "budgeted"],
    }).write_parquet(outside)
    ledger = root / "artifacts" / "research" / "llm_ledger" / "2026-10.jsonl"
    ledger.write_text(json.dumps({"task": "gp_hints", "usd": 0, "tokens": 12}) + "\n", encoding="utf-8")
    monkeypatch.setattr("quant.reporting.doctor._git_facts", lambda _root: {
        "dirty": 21, "days_since_commit": 3, "root_scratch_py": 2, "git_ok": True,
    })
    report = collect(root=root, now=NOW, tasks=[
        {"name": "QuantitativeTrading-IntelWeekly", "last_run_time": NOW.isoformat(), "result": 1},
        {"name": "QuantitativeTrading-DailyObservation", "last_run_time": NOW.isoformat(), "result": 0},
    ])
    text = "\n".join(report["red"])
    assert "IntelWeekly" in text and "result=1" in text
    assert "outside=1" in text
    assert "duplicate" in text
    assert "usd=0" in text
    assert "dirty=21" in text
    assert "days_since_commit=3" in text
    assert "root _*.py=2" in text
    assert len(report["red"]) >= 5


def test_daily_receipt_ignores_logs_and_waiting_sidecars(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    folder = root / 'artifacts/daily/sue_v2'
    (folder / '2026-10-26_213000.log').write_text('child stdout', encoding='utf-8')
    (folder / '2026-10-26_waiting_inputs.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('quant.reporting.doctor._git_facts', lambda _: {
        'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0, 'git_ok': True,
    })
    report = collect(root=root, now=NOW, tasks=[{'name': 'daily', 'result': 0}])
    assert report['daily']['status'] == 'complete'
    assert report['daily']['run'].endswith('2026-10-26_213000')
    # A newer real run without a summary must remain incomplete, not inherit success.
    (folder / '2026-10-26_220000').mkdir()
    report = collect(root=root, now=NOW, tasks=[{'name': 'daily', 'result': 0}])
    assert report['daily']['status'] is None
    assert 'daily: 2026-10-26 status=None' in report['red']


def test_notify_sends_red_lines(monkeypatch):
    sent = {}

    def fake_send(title, body, **_kwargs):
        sent["title"] = title
        sent["body"] = body
        return []

    monkeypatch.setattr("quant.notify.send", fake_send)
    notify_red({"date": "2026-10-26", "red": ["scheduled_tasks: IntelWeekly result=1"]})
    assert "IntelWeekly" in sent["body"]
    notify_red({"date": "2026-10-26", "red": []})
    assert sent["body"].count("IntelWeekly") == 1


def test_cli_doctor_flag(monkeypatch):
    monkeypatch.setattr("quant.reporting.doctor.main", lambda argv=None: 0 if argv == ["--json", "--no-notify"] else 1)
    assert main(["doctor", "--json", "--no-notify"]) == 0
