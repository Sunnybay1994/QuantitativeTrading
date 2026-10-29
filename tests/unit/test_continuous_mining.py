import datetime as dt
import json
import tomllib
from pathlib import Path

import pytest

from quant.research import continuous_mining as mining


def config(tmp_path):
    path = tmp_path/'nightly.toml'
    path.write_text('[genetic]\nseed = 10\n', encoding='utf-8')
    return path


def success():
    return {'steps': {step: {'ok': True} for step in ('N1', 'N2', 'N3', 'N4', 'N5')}}


def test_stale_controls_wait_then_resume_when_ready_or_month_due(tmp_path, monkeypatch):
    from quant.research import nightly_monthly
    path, root = config(tmp_path), tmp_path/'continuous'
    run = root/'batch_000001'/'2026-10-01'
    run.mkdir(parents=True)
    (run/'config.toml').write_text(path.read_text())
    summary = success()
    summary['steps']['N4'] = {'ok': False, 'error': 'N4 exit=1'}
    (run/'summary.json').write_text(json.dumps(summary))
    mining.save(run.parent/'attempt.json', {'consecutive_failures': 3,
        'code_fingerprint': mining.code_fingerprint()})
    dependency = {'ready': False, 'required_as_of': '2026-09-30'}
    monkeypatch.setattr(mining, 'admission_dependency', lambda *a: dependency)
    monkeypatch.setattr(nightly_monthly, 'pending_month', lambda *a, **k: None)
    calls = []
    def execute(*a, **k):
        calls.append(k['run_path'])
        return success()
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    for _ in range(2):
        assert mining.dispatch(path, root)['state'] == 'waiting_dependency'
    assert calls == []
    dependency['ready'] = True
    assert mining.dispatch(path, root)['state'] == 'completed'
    dependency['ready'] = False
    mining.save(run.parent/'attempt.json', {'consecutive_failures': 3,
        'code_fingerprint': mining.code_fingerprint()})
    monkeypatch.setattr(nightly_monthly, 'pending_month', lambda *a, **k: '2026-10')
    assert mining.dispatch(path, root)['state'] == 'completed'
    assert calls == [run, run]


def test_admission_dependency_requires_exact_error_and_live_reference(tmp_path):
    from quant.research.mining_retry import admission_dependency
    run, batch, reference = tmp_path/'run', tmp_path/'batch', tmp_path/'reference'
    for folder in (run/'N3', run/'N4', batch, reference):
        folder.mkdir(parents=True)
    (run/'N3/result.json').write_text(json.dumps({'batch': str(batch)}))
    (batch/'settings.json').write_text(json.dumps({'as_of': '2026-09-30',
        'reference_statistics': str(reference)}))
    (reference/'battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    log = run/'N4/process.log'
    log.write_text('ValueError: ADMITTED controls end 2026-08-31, required 2026-09-30; complete monthly full-library battery before retry\n')
    steps = success()['steps']
    steps['N4'] = {'ok': False}
    assert admission_dependency(run, steps)['ready'] is False
    (reference/'battery.toml').write_text('[run]\nas_of=2026-09-30\n')
    assert admission_dependency(run, steps)['ready'] is True
    (reference/'battery.toml').write_text('[run]\nas_of=2026-10-31\n')
    assert admission_dependency(run, steps) is None
    log.write_text(log.read_text()+'ValueError: unrelated corruption\n')
    assert admission_dependency(run, steps) is None
    steps['N5'] = {'ok': False}
    assert admission_dependency(run, steps) is None


def test_registered_search_is_frozen_for_exactly_one_new_batch(tmp_path, monkeypatch):
    path, root = config(tmp_path), tmp_path/'continuous'
    recipe = tmp_path/'experiment.toml'
    recipe.write_text('version="cross_stock_v1"\nmaximum_batches=1\n')
    path.write_text(f'one_shot_search_config={json.dumps(str(recipe))}\n'+path.read_text())
    observed = []
    def execute(frozen, **kwargs):
        saved = tomllib.loads(frozen.read_text())
        observed.append(saved.get('cross_stock_config'))
        if saved.get('cross_stock_config'):
            assert Path(saved['cross_stock_config']).read_text() == recipe.read_text()
        result = success()
        (kwargs['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    mining.dispatch(path, root)
    mining.dispatch(path, root)
    assert observed[0] and observed[1] is None


def test_weekly_candidates_run_before_local_research_without_blocking_on_failure(tmp_path, monkeypatch):
    from quant.research import weekly_factor_candidates as weekly
    path = config(tmp_path)
    path.write_text('weekly_candidates_config = "weekly.toml"\n' + path.read_text())
    calls = []
    def generate(config, **kwargs):
        assert kwargs['execute'] is True
        calls.append('weekly')
        raise ValueError('Pricing snapshot requires refresh')
    def execute(*args, **kwargs):
        assert calls == ['weekly']
        return success()
    monkeypatch.setattr(weekly, 'run', generate)
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    result = mining.dispatch(path, tmp_path/'continuous')
    assert result['state'] == 'completed'
    assert result['weekly_candidates']['state'] == 'needs_attention'


def test_cross_day_interruption_resumes_same_frozen_batch(tmp_path, monkeypatch):
    path, root = config(tmp_path), tmp_path/'continuous'
    calls = []

    def execute(frozen, **kwargs):
        calls.append((frozen, kwargs))
        run = kwargs['run_path']
        checkpoint = run/'checkpoint.json'
        if len(calls) == 1:
            checkpoint.write_text('retained')
            raise KeyboardInterrupt()
        assert checkpoint.read_text() == 'retained'
        assert 'seed = 11' in frozen.read_text()
        return success()

    monkeypatch.setattr(mining.nightly, 'execute', execute)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        mining.dispatch(path, root, now=dt.datetime(2026, 9, 14, 12))
    path.write_text('[genetic]\nseed = 99\n')
    result = mining.dispatch(path, root, now=dt.datetime(2026, 9, 16, 12))
    assert result['state'] == 'completed'
    assert calls[0][0] == calls[1][0]
    assert calls[1][1]['session_hours'] == 2


def test_completed_batch_advances_with_new_seed(tmp_path, monkeypatch):
    def execute(frozen, **kwargs):
        result = success()
        (kwargs['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    path, root = config(tmp_path), tmp_path/'continuous'
    first = mining.dispatch(path, root)
    second = mining.dispatch(path, root)
    assert first['seed'] == 11
    assert second['seed'] == 12
    assert first['run'] != second['run']


def test_interrupted_batch_creation_is_not_published(tmp_path, monkeypatch):
    root = tmp_path/'continuous'
    partial = root/'batch_000001.2026-09-14.pending'
    (partial/'2026-09-14').mkdir(parents=True)
    monkeypatch.setattr(mining.nightly, 'execute', lambda *a, **k: success())
    result = mining.dispatch(config(tmp_path), root, now=dt.datetime(2026, 9, 16))
    assert result['state'] == 'completed'
    assert result['batch'] == 'batch_000001'
    assert result['run'].endswith('2026-09-16')
    assert partial.exists()


def test_failure_cools_down_then_stops_retries(tmp_path, monkeypatch):
    calls = []
    def execute(*args, **kwargs):
        calls.append(1)
        return {'steps': {'N2': {'ok': False, 'error': 'N2 exit=1; see process.log'}}}
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    path, root = config(tmp_path), tmp_path/'continuous'
    start = dt.datetime(2026, 9, 14, 12)
    assert mining.dispatch(path, root, now=start)['state'] == 'cooldown'
    mining.dispatch(path, root, now=start+dt.timedelta(minutes=10))
    assert len(calls) == 1
    mining.dispatch(path, root, now=start+dt.timedelta(hours=1))
    assert mining.dispatch(path, root, now=start+dt.timedelta(hours=2))['state'] == 'needs_attention'
    mining.dispatch(path, root, now=start+dt.timedelta(days=1))
    assert len(calls) == 3


def test_time_slice_is_resumable_not_repeated_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mining.nightly, 'execute', lambda *a, **k: {'steps': {
        'N2': {'ok': False, 'error': 'Worker exceeded 7200 seconds'},
        'N3': {'ok': False, 'error': 'Time/disk guard: -2s, 100.0 GiB'},
        'N4': {'ok': False, 'error': 'N3 did not complete'}}})
    path, root = config(tmp_path), tmp_path/'continuous'
    for _ in range(4):
        assert mining.dispatch(path, root)['state'] == 'resumable'


def test_explicit_session_resumes_expired_run_without_changing_default(tmp_path, monkeypatch):
    from quant.factors import library
    from quant.research import nightly, nightly_steps
    monkeypatch.setattr(library, 'load_library', lambda _: [])
    monkeypatch.setattr(nightly_steps, 'resolve_settings', lambda s, _: s)
    monkeypatch.setattr(nightly, 'work_order', lambda *_: ())
    monkeypatch.setattr(nightly, 'digest', lambda *_: None)
    path = tmp_path/'config.toml'
    path.write_text('output_root="unused"\nlibrary="unused"\nweekday_hours=6\nweekend_hours=20\n')
    run = tmp_path/'2026-09-14'
    run.mkdir()
    (run/'summary.json').write_text(json.dumps({'started_at': '2026-09-14T00:00:00',
        'deadline_at': '2026-09-14T06:00:00', 'steps': {}, 'library_before': 0}))
    result = nightly.execute(path, now=dt.datetime(2026, 9, 16, 10), run_path=run, session_hours=2)
    assert result['started_at'] == '2026-09-14T00:00:00'
    assert result['deadline_at'] == '2026-09-16T12:00:00'

def test_stale_gp_freeze_cannot_repin_or_probe_after_code_change(tmp_path, monkeypatch):
    path, root = config(tmp_path), tmp_path / 'continuous'
    run = root / 'batch_000001' / '2026-10-13'
    n2 = run / 'N2'
    n2.mkdir(parents=True)
    (run / 'config.toml').write_text(path.read_text())
    (run / 'summary.json').write_text(json.dumps({
        'steps': {'N1': {'ok': True}, 'N2': {'ok': False, 'error': 'N2 exit=1'},
                  'N3': {'ok': True}, 'N4': {'ok': True}, 'N5': {'ok': True}}
    }))
    context = n2 / 'full_context'
    context.mkdir()
    (context / 'source_manifest.json').write_text('{"old": true}', encoding='utf-8')
    (n2 / 'process.log').write_text(
        'ValueError: Frozen GP context source checksum changed: data.parquet\n', encoding='utf-8')
    mining.save(run.parent / 'attempt.json', {
        'consecutive_failures': 1,
        'error': {'N2': 'N2 exit=1; see process.log'},
        'failure_kind': 'transient',
        'code_fingerprint': mining.code_fingerprint(),
        'retry_after': '2026-10-13T00:00:00',
    })
    calls = []
    def execute(*a, **k):
        calls.append(k['run_path'])
        raise AssertionError('Cannot retry invalid frozen inputs')
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    result = mining.dispatch(path, root, now=__import__('datetime').datetime(2026, 10, 13, 12))
    assert result['state'] == 'needs_attention'
    assert result['failure_kind'] == 'frozen_inputs_invalidated'
    assert not calls
    assert (context/'source_manifest.json').read_text() == '{"old": true}'
    assert not (n2 / 'stale_context_recovery').exists()
    monkeypatch.setattr(mining, 'code_fingerprint', lambda: 'changed-code')
    result = mining.dispatch(path, root, now=dt.datetime(2026, 10, 14, 12))
    assert result['failure_kind'] == 'frozen_inputs_invalidated' and not calls


def test_new_frozen_source_failure_stops_retries_without_erasing_checkpoints(tmp_path, monkeypatch):
    path, root = config(tmp_path), tmp_path/'continuous'
    n2_paths = []

    def execute(*args, **kwargs):
        n2 = kwargs['run_path']/'N2'; n2.mkdir(parents=True,exist_ok=True)
        n2_paths.append(n2)
        (n2/'search_checkpoint.json').write_text('{"generation":12}')
        (n2/'process.log').write_text('ValueError: Frozen GP context source checksum changed: x.parquet\n')
        result = success(); result['steps']['N2'] = dict(ok=False,error='N2 exit=1; see process.log')
        mining.save(kwargs['run_path']/'summary.json',result)
        return result

    monkeypatch.setattr(mining.nightly,'execute',execute)
    result = mining.dispatch(path,root,now=dt.datetime(2026,10,27,12))
    assert result['state'] == 'needs_attention' and result['retry_after'] is None
    assert result['failure_kind'] == 'frozen_inputs_invalidated'
    assert (n2_paths[0]/'search_checkpoint.json').read_text() == '{"generation":12}'
    mining.dispatch(path,root,now=dt.datetime(2026,10,28,12))
    assert len(n2_paths) == 1


@pytest.mark.parametrize('failures', [1, 3, 8])
@pytest.mark.parametrize('retry_after', [None, '2026-10-30T12:00:00'])
def test_exact_source_restoration_resumes_original_batch_and_checkpoint(tmp_path, monkeypatch, failures, retry_after):
    import hashlib
    path, root = config(tmp_path), tmp_path/'continuous'
    run = root/'batch_000001/2026-10-27'
    context = run/'N2/full_context'; context.mkdir(parents=True)
    (run/'config.toml').write_text(path.read_text())
    source = tmp_path/'input.parquet'; source.write_bytes(b'original')
    (context/'source_manifest.json').write_text(json.dumps(
        {str(source):hashlib.sha256(source.read_bytes()).hexdigest()}))
    checkpoint = run/'N2/search_checkpoint.json'; checkpoint.write_text('{"generation":12}')
    (run/'N2/process.log').write_text('ValueError: Frozen GP context source checksum changed: input.parquet\n')
    value = success(); value['steps']['N2'] = dict(ok=False,error='N2 exit=1')
    mining.save(run/'summary.json',value)
    monkeypatch.setattr(mining, 'code_fingerprint', lambda: 'unchanged-code')
    previous = dict(error={'N2':'N2 exit=1'},consecutive_failures=failures,
                    code_fingerprint='unchanged-code',retry_after=retry_after)
    mining.save(run.parent/'attempt.json',previous)
    calls = []

    def execute(*args, **kwargs):
        assert kwargs['run_path'] == run
        assert checkpoint.read_text() == '{"generation":12}'
        calls.append(run)
        return success()

    monkeypatch.setattr(mining.nightly,'execute',execute)
    source.write_bytes(b'changed')
    assert mining.dispatch(path,root,now=dt.datetime(2026,10,27,12))['state'] == 'needs_attention'
    assert not calls
    source.write_bytes(b'original')
    assert mining.dispatch(path,root,now=dt.datetime(2026,10,27,13))['state'] == 'completed'
    assert calls == [run]
    recovery = list((run.parent/'recovery').glob('inputs_*.json'))
    assert len(recovery) == 1
    assert json.loads(recovery[0].read_text()) == previous


def test_evidence_bound_input_invalidation_advances_without_completing_or_rewriting_old_batch(tmp_path,monkeypatch):
    import hashlib
    path, root = config(tmp_path),tmp_path/'continuous'
    batch = root/'batch_000001'; run = batch/'2026-10-27'; run.mkdir(parents=True)
    (run/'config.toml').write_text(path.read_text())
    summary = dict(steps={'N2':dict(ok=False,error='invalid input lineage')})
    mining.save(run/'summary.json',summary)
    evidence = run/'proof.json'; evidence.write_text('{"lineage":"changed"}')
    mining.save(batch/'input_invalidation.json',dict(batch=batch.name,classification='FROZEN_INPUTS_INVALIDATED',
        strategy_result=None,evidence=[dict(path=str(evidence),sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())]))
    before = (run/'summary.json').read_bytes()
    calls = []
    def execute(*args,**kwargs):
        calls.append(kwargs['run_path'])
        return success()
    monkeypatch.setattr(mining.nightly,'execute',execute)
    result = mining.dispatch(path,root,now=dt.datetime(2026,10,27,12))
    assert result['batch'] == 'batch_000002' and calls == [root/'batch_000002/2026-10-27']
    assert (run/'summary.json').read_bytes() == before and not mining.completed(summary)
    evidence.write_text('{"lineage":"tampered"}')
    with __import__('pytest').raises(ValueError,match='evidence changed'):
        mining.dispatch(path,root,now=dt.datetime(2026,10,27,13))
