import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from quant.research import scheduled_observation as scheduled


def setup_config(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("selection").mkdir()
    Path("refresh.toml").touch()
    config = Path("daily.toml")
    config.write_text(
        'auto_trade=false\ndata_root="data"\nrefresh_config="refresh.toml"\n'
        '[model]\nselection="selection"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(scheduled, "latest_session", lambda **kw: kw["through"])
    return config


def record(root, *, status="complete", rehearsal=False, saved_data=False):
    folder = root / "previous"
    folder.mkdir(parents=True)
    value = {
        "as_of": "2026-09-14",
        "status": status,
        "rehearsal": rehearsal,
        "saved_data": saved_data,
        "requires_review": False,
        "stages": {"refresh": {"status": "complete"}},
    }
    (folder / "summary.json").write_text(json.dumps(value))
    return value


NOW = dt.datetime(2026, 9, 14, 21, 30, tzinfo=scheduled.SHANGHAI)


def test_probe_does_not_run_calendar_or_subprocess(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)

    def forbidden(**kwargs):
        raise AssertionError("Probe must not refresh")

    monkeypatch.setattr(scheduled, "latest_session", forbidden)
    assert scheduled.run(config=config, check_only=True)["status"] == "checked"


def test_closed_session_does_not_backdate_forecast(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)
    monkeypatch.setattr(scheduled, "latest_session", lambda **kw: dt.date(2026, 9, 11))
    assert scheduled.run(config=config, now=NOW)["status"] == "skipped"


def test_complete_day_only_runs_missing_s0(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)
    root = Path("records")
    record(root)
    commands = []

    def execute(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", execute)
    assert scheduled.run(config=config, root=root, now=NOW)["status"] == "complete"
    assert len(commands) == 1 and commands[0][2] == "quant.execution.paper_ledger"
    assert scheduled.run(config=config, root=root, now=NOW)["status"] == "complete"
    assert len(commands) == 1


def test_rehearsal_and_saved_data_are_not_forward_completion(tmp_path):
    root = tmp_path / "records"
    record(root, rehearsal=True)
    assert scheduled.completed_record(root, "2026-09-14") is None
    p = root / "previous/summary.json"
    value = json.loads(p.read_text())
    value.update(rehearsal=False, saved_data=True)
    p.write_text(json.dumps(value))
    assert scheduled.completed_record(root, "2026-09-14") is None


def test_failed_subprocess_cannot_be_success_even_with_complete_summary(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)

    def execute(command, **kwargs):
        if command[2] == "quant.research.run_daily_observation":
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True)
            value = {
                "as_of": "2026-09-14",
                "status": "complete",
                "rehearsal": False,
                "stages": {"refresh": {"status": "complete"}},
            }
            (output / "summary.json").write_text(json.dumps(value))
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", execute)
    result = scheduled.run(config=config, root=Path("records"), now=NOW)
    assert result["status"] == "incomplete" and result["observation_exit_code"] == 1
    assert scheduled.completed_record(Path("records"), "2026-09-14") is None


def test_s0_failure_retries_without_repeating_observation(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)
    root = Path("records")
    record(root)
    codes = iter([1, 0])

    def execute(command, **kwargs):
        assert command[2] == "quant.execution.paper_ledger"
        return SimpleNamespace(returncode=next(codes))

    monkeypatch.setattr(scheduled.subprocess, "run", execute)
    assert scheduled.run(config=config, root=root, now=NOW)["status"] == "incomplete"
    assert scheduled.run(config=config, root=root, now=NOW)["status"] == "complete"
