"""Scheduler exit codes must reflect completed research, including failures."""

import sys
import datetime as dt
import json
import subprocess
from types import SimpleNamespace

import pytest

from quant.research import nightly


def test_scheduler_sees_failed_required_step(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nightly"])
    monkeypatch.setattr(nightly, "execute", lambda _: {
        "steps": {"N1": {"ok": True}, "N2": {"ok": False, "error": "disk guard"}}
    })
    with pytest.raises(SystemExit) as result:
        nightly.main()
    assert result.value.code != 0


def test_monthly_not_due_is_success(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nightly"])
    monkeypatch.setattr(nightly, "execute", lambda _: {
        "steps": {"N1": {"ok": True}, "N5": {"ok": True, "result": {"scheduled": False}}}
    })
    try:
        nightly.main()
    except SystemExit as result:
        assert result.code in (None, 0)


def test_space_drop_during_worker_stops_process_tree(monkeypatch, tmp_path):
    free_values = iter([100 * 1024**3, 49 * 1024**3])
    monkeypatch.setattr(nightly.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(free_values)))
    killed = []
    monkeypatch.setattr(nightly.subprocess, "run", lambda command, **_: killed.append(command))

    class Worker:
        pid = 123456789
        stopped = False

        def poll(self):
            return -1 if self.stopped else None

        def kill(self):
            self.stopped = True

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return -1

    worker = Worker()
    with pytest.raises(RuntimeError, match="Disk guard"):
        nightly.wait_bounded(worker, run=tmp_path, timeout=600, minimum_free_gb=50)
    assert worker.stopped
    if sys.platform == "win32":
        assert killed == [["taskkill", "/PID", "123456789", "/T", "/F"]]


def test_restart_does_not_extend_expired_night(monkeypatch, tmp_path):
    from quant.factors import library
    from quant.research import nightly_steps

    monkeypatch.setattr(library, "load_library", lambda _: [])
    monkeypatch.setattr(nightly_steps, "resolve_settings", lambda settings, _: settings, raising=False)
    monkeypatch.setattr(nightly, "digest", lambda *_: None)
    monkeypatch.setattr(nightly, "work_order", lambda *_: ('N1', 'N2', 'N3', 'N4', 'N5'))
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Expired run spawned worker"))
    config = tmp_path / "nightly.toml"
    config.write_text(f'output_root = "{tmp_path.as_posix()}/runs"\n'
                      'library = "unused"\nweekday_hours = 6\nweekend_hours = 20\n'
                      'minimum_free_gb = 0\n', encoding="utf-8")
    run = tmp_path / "runs" / "2026-09-14"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps({
        "date": "2026-09-14", "started_at": "2026-09-14T00:00:00",
        "library_before": 383, "steps": {}
    }), encoding="utf-8")
    result = nightly.execute(config, now=dt.datetime(2026, 9, 14, 7))
    assert result["deadline_at"] == "2026-09-14T06:00:00"
    assert result["library_before"] == 383
    assert all(not state["ok"] for state in result["steps"].values())


def test_deferred_attempt_preserves_successful_run(monkeypatch, tmp_path):
    config = tmp_path / "nightly.toml"
    config.write_text(f'output_root = "{tmp_path.as_posix()}/runs"\n', encoding="utf-8")
    run = tmp_path / "runs" / dt.date.today().isoformat()
    run.mkdir(parents=True)
    original = '{"steps":{"N1":{"ok":true}}}'
    (run / "summary.json").write_text(original, encoding="utf-8")
    (run / "digest.md").write_text("completed", encoding="utf-8")
    monkeypatch.setattr(nightly, "digest", lambda *_a, **_k: pytest.fail("Replaced prior digest"))
    nightly.record_deferred(config, "Existing writer")
    assert (run / "summary.json").read_text(encoding="utf-8") == original
    assert (run / "digest.md").read_text(encoding="utf-8") == "completed"
    assert len(list(run.glob("deferred_attempt_*.json"))) == 1


def test_gp_resume_reopens_only_empty_evaluation(tmp_path):
    for step, value in (("N3", {"evaluated": 0}), ("N4", {"admitted": 0})):
        folder = tmp_path / step
        folder.mkdir()
        (folder / "result.json").write_text(json.dumps(value), encoding="utf-8")
    summary = {"steps": {"N3": {"ok": True}, "N4": {"ok": True}}}
    nightly.reopen_empty_evaluation(tmp_path, summary, {"candidates": 20})
    assert not (tmp_path / "N3" / "result.json").exists()
    assert not (tmp_path / "N4" / "result.json").exists()
    assert not summary["steps"]
    assert len(list((tmp_path / "N3").glob("result_before_gp_resume_*.json"))) == 1
    completed = '{"evaluated":20}'
    (tmp_path / "N3" / "result.json").write_text(completed, encoding="utf-8")
    nightly.reopen_empty_evaluation(tmp_path, summary, {"candidates": 20})
    assert (tmp_path / "N3" / "result.json").read_text(encoding="utf-8") == completed


def test_gp_candidates_survive_completed_nonempty_evaluation(tmp_path):
    from quant.research.nightly_steps import preserve_gp_candidates
    folder = tmp_path/'run/N2/library'
    folder.mkdir(parents=True)
    content = 'id="gp_new"\nexpr="close"\ndirection=1\n'
    (folder/'gp_new.toml').write_text(content)
    prior = tmp_path/'run/N3/result.json'
    prior.parent.mkdir()
    prior.write_text('{"evaluated":4}')
    settings = {'queue': str(tmp_path/'queue'), 'library': str(tmp_path/'library')}
    assert preserve_gp_candidates(settings, tmp_path/'run', {'candidates': 1}) == 1
    queued = tmp_path/'queue/processing/gp_new.toml'
    assert queued.read_text() == content
    assert prior.read_text() == '{"evaluated":4}'
    assert preserve_gp_candidates(settings, tmp_path/'run', {'candidates': 1}) == 0
    queued.write_text(content.replace('direction=1', 'direction=-1'))
    with pytest.raises(ValueError, match='collision'):
        preserve_gp_candidates(settings, tmp_path/'run', {'candidates': 1})


def test_unfinished_monthly_work_precedes_new_search(tmp_path):
    settings = {"output_root": str(tmp_path), "monthly_first_period": "2026-10"}
    month = tmp_path / "monthly" / "2026-10"
    month.mkdir(parents=True)
    order = nightly.work_order(settings, dt.date(2026, 10, 5))
    assert order.index("N5") < order.index("N2")
    (month / "summary.json").write_text('{"completed":true}', encoding="utf-8")
    order = nightly.work_order(settings, dt.date(2026, 10, 5))
    assert order.index("N2") < order.index("N5")


def test_queued_order_keeps_monthly_prerequisite_and_empty_queue_order(tmp_path):
    original=('N1','N5','N2','N3','N4')
    settings={'queue':str(tmp_path/'queue')}
    assert nightly.prioritize_queued_battery(original,settings,tmp_path/'run') == original
    queue=tmp_path/'queue'; queue.mkdir(); (queue/'whole_family.toml').write_text('fixture')
    actual=nightly.prioritize_queued_battery(original,settings,tmp_path/'run')
    assert actual == ('N1','N5','N3','N4','N2')


@pytest.mark.parametrize('gp_finishes',[False,True,None])
def test_queued_battery_completes_before_gp_and_late_gp_candidates_are_retained(tmp_path,monkeypatch,gp_finishes):
    from quant.factors import library
    from quant.research import nightly_steps
    monkeypatch.setattr(library,'load_library',lambda _:[])
    monkeypatch.setattr(nightly_steps,'resolve_settings',lambda settings,run:settings)
    monkeypatch.setattr(nightly,'digest',lambda *args:None)
    monkeypatch.setattr(nightly,'work_order',lambda *args:('N1','N2','N3','N4','N5'))
    run=tmp_path/'2026-10-27'; run.mkdir()
    queue=tmp_path/'queue'; queue.mkdir(); (queue/'registered_family.toml').write_text('fixture')
    config=tmp_path/'nightly.toml'
    config.write_text(f'output_root="{tmp_path.as_posix()}"\nlibrary="unused"\nqueue="{queue.as_posix()}"\n'
        'weekday_hours=6\nweekend_hours=20\nminimum_free_gb=0\n[step_timeout_seconds]\n'
        'N1=300\nN2=5000\nN3=5000\nN4=5000\nN5=5000\n')
    checkpoint=run/'N2/search_checkpoint.json'; checkpoint.parent.mkdir()
    checkpoint.write_text('{"generation":12,"population":["saved"]}')
    original_checkpoint=checkpoint.read_bytes()
    if gp_finishes is None:
        import hashlib
        proof=run/'N2/proof.json'; proof.write_text('{}')
        (run/'N2/computation_invalidation.json').write_text(json.dumps(dict(
            classification='INVALID_COMPUTATION',reason='Known computation defect',
            evidence=[dict(path=str(proof),sha256=hashlib.sha256(proof.read_bytes()).hexdigest())])))
    calls=[]

    def spawn(command,**kwargs):
        step=command[command.index('--worker')+1]; calls.append(step)
        if step=='N2' and gp_finishes is None:
            pytest.fail('Retired GP must not spawn another worker')
        if step=='N2' and not gp_finishes:
            return SimpleNamespace(code=75)
        value={'N1':{'queued_candidates':3},'N2':{'candidates':1},'N3':{'evaluated':3},
               'N4':{'admitted':0,'rejected':3},'N5':{'skipped':True}}[step]
        if step=='N2':
            folder=run/'N2/library'; folder.mkdir()
            (folder/'gp_late.toml').write_text('id="gp_late"\nexpr="close"\ndirection=1\n')
        (run/step/'result.json').write_text(json.dumps(value))
        return SimpleNamespace(code=0)

    monkeypatch.setattr(nightly.subprocess,'Popen',spawn)
    monkeypatch.setattr(nightly,'wait_bounded',lambda worker,**kwargs:worker.code)
    result=nightly.execute(config,run_path=run,now=dt.datetime(2026,10,27,12),session_hours=2)
    assert calls == (['N1','N3','N4','N5'] if gp_finishes is None else ['N1','N3','N4','N2','N5'])
    assert result['steps']['N3']['ok'] and result['steps']['N4']['ok']
    assert result['steps']['N2']['ok'] is (gp_finishes is not False)
    if gp_finishes is None:
        assert result['steps']['N2']['result']['classification']=='INVALID_COMPUTATION'
        assert result['steps']['N2']['result']['strategy_result'] is None
    assert checkpoint.read_bytes()==original_checkpoint
    assert json.loads((run/'N3/result.json').read_text())=={'evaluated':3}
    if gp_finishes:
        assert (queue/'processing/gp_late.toml').is_file()


def test_retired_gp_is_not_resumed_or_delivered_and_its_queue_files_are_preserved(tmp_path,monkeypatch):
    import hashlib
    from quant.research import nightly_steps
    from quant.research.mining_retry import retired_gp_result
    run=tmp_path/'2026-10-27'; n2=run/'N2'; n2.mkdir(parents=True)
    proof=n2/'frozen_proof.json'; proof.write_text('{}')
    checkpoint=n2/'search_checkpoint.json'; checkpoint.write_text('{"generation":0}')
    (n2/'computation_invalidation.json').write_text(json.dumps(dict(classification='INVALID_COMPUTATION',
        reason='Known unsupported intrinsic input path',evidence=[dict(path=str(proof),sha256=hashlib.sha256(proof.read_bytes()).hexdigest())])))
    settings={'queue':str(tmp_path/'queue'),'library':str(tmp_path/'library')}
    queue=tmp_path/'queue'; queue.mkdir()
    content=f'id="gp_bad"\nexpr="close"\ndirection=1\nfamily="gp"\nsource_ref={json.dumps(str(n2/"search.json"))}\n'
    (queue/'gp_bad.toml').write_text(content)
    result=nightly_steps.ingest(settings,run)
    assert result['queued_candidates']==0
    assert next((queue/'processing/invalid_computation').glob('*.toml')).read_text()==content
    assert nightly_steps.preserve_gp_candidates(settings,run,{'candidates':20})==0
    # A definition copied before retirement must not survive in the run library.
    copied = run/'candidates/gp_bad.toml'
    copied.write_text(content)
    evaluated = nightly_steps.evaluate(settings,run)
    assert evaluated['candidates'] == evaluated['evaluated'] == 0
    assert not copied.exists()
    assert (copied.parent/'invalid_computation/gp_bad.toml').read_text() == content
    assert retired_gp_result(n2)['classification']=='INVALID_COMPUTATION'
    assert checkpoint.read_text()=='{"generation":0}'
    proof.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='evidence changed'):
        retired_gp_result(n2)


@pytest.mark.parametrize("monthly, expected", [
    ({"ok": True, "result": {"completed": True, "skipped": False}}, "月度模型已完成"),
    ({"ok": False, "error": "Time guard"}, "月度步骤未完成"),
    ({"ok": True, "result": {"skipped": True}}, "本夜无需月度重训"),
])
def test_digest_uses_actual_monthly_outcome(monkeypatch, tmp_path, monthly, expected):
    from quant.factors import library
    monkeypatch.setattr(library, "load_library", lambda _: [])
    run = tmp_path / "2026-10-03"
    run.mkdir()
    nightly.digest({"library": "unused"}, run,
                   {"library_before": 0, "steps": {"N5": monthly}}, rewrite_leaderboard=False)
    assert expected in (run / "digest.md").read_text(encoding="utf-8")
