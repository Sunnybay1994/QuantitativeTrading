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


def test_q10_early_trigger_defers_without_recomputing_or_false_failure(tmp_path,monkeypatch):
    config=setup_config(tmp_path,monkeypatch)
    config.write_text(config.read_text()+'\n[q10]\nconfig="q10.toml"\n')
    def forbidden(*args,**kwargs):
        raise AssertionError('Cannot start full observation before Q10 inputs are available')
    monkeypatch.setattr(scheduled.subprocess,'run',forbidden)
    result=scheduled.run(config=config,root=Path('records'),now=NOW.replace(hour=17))
    assert result['status']=='deferred'
    assert result['not_before'].endswith('21:00:00+08:00')
    assert scheduled.completed_record(Path('records'),'2026-09-14') is None


def test_q10_evening_trigger_can_complete(tmp_path,monkeypatch):
    config=setup_config(tmp_path,monkeypatch)
    config.write_text(config.read_text()+'\n[q10]\nconfig="q10.toml"\n')
    root=Path('records')
    record(root)
    monkeypatch.setattr(scheduled.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0))
    assert scheduled.run(config=config,root=root,now=NOW)['status']=='complete'


def test_probe_does_not_run_calendar_or_subprocess(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)

    def forbidden(**kwargs):
        raise AssertionError("Probe must not refresh")

    monkeypatch.setattr(scheduled, "latest_session", forbidden)
    assert scheduled.run(config=config, check_only=True)["status"] == "checked"


def test_explicit_previous_session_can_catch_up_in_morning_without_fake_clock(tmp_path,monkeypatch):
    config=setup_config(tmp_path,monkeypatch)
    config.write_text(config.read_text()+'\n[q10]\nconfig="q10.toml"\n')
    root=Path('records')
    record(root)
    monkeypatch.setattr(scheduled.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0))
    result=scheduled.run(config=config,root=root,now=NOW.replace(day=15,hour=8),to='2026-09-14')
    assert result['status']=='complete'
    assert result['as_of']=='2026-09-14'
    assert result['delayed_recording'] is True
    assert 'recorded_at' in result
    assert scheduled.run(config=config,root=root,now=NOW.replace(day=15,hour=8))['status']=='skipped'


def test_explicit_future_session_rejected(tmp_path,monkeypatch):
    import pytest
    config=setup_config(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='future'):
        scheduled.run(config=config,now=NOW,to='2026-09-15')


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


def test_interrupted_s0_hint_recovers_through_ledger(tmp_path, monkeypatch):
    config = setup_config(tmp_path, monkeypatch)
    root = Path("records")
    record(root)
    (root / "2026-09-14_s0.json").write_text('{"exit_code":')

    def execute(command, **kwargs):
        assert command[2] == "quant.execution.paper_ledger"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", execute)
    assert scheduled.run(config=config, root=root, now=NOW)["status"] == "complete"
    assert json.loads((root / "2026-09-14_s0.json").read_text())["exit_code"] == 0


def test_evening_context_binds_completed_record_and_uses_finish_clock(tmp_path, monkeypatch):
    from quant.research import daily_market_context
    config = setup_config(tmp_path, monkeypatch)
    root = Path('records')
    record(root)
    (root/'2026-09-14_s0.json').write_text('{"exit_code":0}')
    seen = {}

    def publish(**kwargs):
        seen.update(kwargs)
        return {'status': 'complete'}

    monkeypatch.setattr(daily_market_context, 'run', publish)
    before = dt.datetime.now(scheduled.SHANGHAI)
    assert scheduled.run(config=config, root=root, now=NOW)['market_context']['status'] == 'complete'
    assert seen['now'] >= before and seen['now'] != NOW
    assert seen['completed_session'] == NOW.date()
    assert seen['daily_record'] == root/'previous/summary.json'
    assert seen['daily_root'] == root and seen['require_daily_receipt'] is True


def test_monitor_incomplete_still_attempts_independent_market_publication(tmp_path, monkeypatch):
    from quant.research import daily_market_context
    config = setup_config(tmp_path, monkeypatch)
    calls = []

    def execute(command, **kwargs):
        if command[2] == 'quant.research.run_daily_observation':
            output = Path(command[command.index('--output')+1]); output.mkdir(parents=True)
            value = dict(as_of=str(NOW.date()), status='incomplete', rehearsal=False, saved_data=False,
                stages=dict(refresh=dict(status='complete'), signal_monitor=dict(status='incomplete')))
            (output/'summary.json').write_text(json.dumps(value))
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    def publish(**kwargs):
        calls.append(kwargs)
        return dict(status='complete', daily_completion=None)

    monkeypatch.setattr(scheduled.subprocess, 'run', execute)
    monkeypatch.setattr(daily_market_context, 'run', publish)
    result = scheduled.run(config=config, root=Path('records'), now=NOW)
    assert result['status'] == 'incomplete' and result['observation_exit_code'] == 1
    assert result['market_context']['status'] == 'complete' and len(calls) == 1
    assert scheduled.completed_record(Path('records'), str(NOW.date())) is None
