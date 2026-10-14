import datetime as dt
import json

from quant.research import continuous_mining as mining
from quant.research.mining_retry import failure_kind


def setup(tmp_path,monkeypatch,error):
    config=tmp_path/'config.toml'
    config.write_text('[genetic]\nseed=10\n')
    calls=[]
    def execute(*args,**kwargs):
        calls.append(kwargs['run_path'])
        return {'steps':{'N3':{'ok':False,'error':error}}}
    monkeypatch.setattr(mining.nightly,'execute',execute)
    monkeypatch.setattr(mining,'code_fingerprint',lambda:'v1')
    return config,tmp_path/'runs',calls


def test_code_change_gets_one_probe_and_preserves_failure_history(tmp_path,monkeypatch):
    config,root,calls=setup(tmp_path,monkeypatch,'ValueError: Definition changed')
    start=dt.datetime(2026,9,22)
    for hour in range(3):
        mining.dispatch(config,root,now=start+dt.timedelta(hours=hour))
    monkeypatch.setattr(mining,'code_fingerprint',lambda:'v2')
    result=mining.dispatch(config,root,now=start+dt.timedelta(hours=3))
    assert result['state']=='needs_attention'
    mining.dispatch(config,root,now=start+dt.timedelta(days=1))
    assert len(calls)==4 and len(set(calls))==1
    saved=list((root/'batch_000001/recovery').glob('*.json'))
    assert len(saved)==1 and json.loads(saved[0].read_text())['consecutive_failures']==3


def test_transient_failures_backoff_and_have_finite_budget(tmp_path,monkeypatch):
    config,root,calls=setup(tmp_path,monkeypatch,'TimeoutError: provider timed out')
    start=dt.datetime(2026,9,22)
    result=mining.dispatch(config,root,now=start)
    for hour in (1,3,7,15,31,55,79):
        result=mining.dispatch(config,root,now=start+dt.timedelta(hours=hour))
    assert len(calls)==8 and result['state']=='needs_attention'
    mining.dispatch(config,root,now=start+dt.timedelta(days=10))
    assert len(calls)==8


def test_latest_exception_controls_classification(tmp_path):
    folder=tmp_path/'N3'
    folder.mkdir()
    log=folder/'process.log'
    log.write_text('TimeoutError: old\nValueError: Definition changed\n')
    assert failure_kind({'N3':'N3 exit=1; see process.log'},tmp_path)=='deterministic_or_unknown'
    log.write_text('ValueError: old\nPermissionError: [WinError 32] locked\n')
    assert failure_kind({'N3':'N3 exit=1; see process.log','N4':'N3 did not complete'},tmp_path)=='transient'
    n2 = tmp_path / 'N2'
    n2.mkdir()
    (n2 / 'process.log').write_text(
        'PermissionError: [WinError 5] Access is denied: source_manifest.tmp\n', encoding='utf-8')
    assert failure_kind({'N2': 'N2 exit=1; see process.log'}, tmp_path) == 'transient'


def test_sticky_needs_attention_does_not_exit_one(tmp_path, monkeypatch):
    """Scheduler re-ticks must not alert every hour while the batch stays stuck."""
    config, root, calls = setup(tmp_path, monkeypatch, 'ValueError: Definition changed')
    start = dt.datetime(2026, 9, 22)
    for hour in range(3):
        mining.dispatch(config, root, now=start + dt.timedelta(hours=hour))
    assert mining.dispatch(config, root, now=start + dt.timedelta(hours=3))['state'] == 'needs_attention'
    monkeypatch.setattr('sys.argv', [
        'continuous_mining', '--config', str(config), '--output-root', str(root),
    ])
    # Sticky re-tick: no new attempt → exit 0 (suppress alert spam).
    mining.main()
    assert len(calls) == 3

def test_stale_gp_context_is_transient_and_invalidates_freeze(tmp_path):
    from quant.research.mining_retry import (
        failure_kind, invalidate_stale_gp_context, errors_indicate_stale_gp_context)

    n2 = tmp_path / 'N2'
    context = n2 / 'full_context'
    context.mkdir(parents=True)
    (context / 'source_manifest.json').write_text('{"x": "old"}', encoding='utf-8')
    (n2 / 'fitness_cache.json').write_text('{}', encoding='utf-8')
    (n2 / 'search_checkpoint.json').write_text('{}', encoding='utf-8')
    (n2 / 'process.log').write_text(
        'ValueError: Frozen GP context source checksum changed: '
        'F:\\data\\clean\\bar_intraday\\symbol=002472.SZ\\data.parquet\n',
        encoding='utf-8')
    errors = {'N2': 'N2 exit=1; see process.log'}
    assert errors_indicate_stale_gp_context(errors, tmp_path)
    assert failure_kind(errors, tmp_path) == 'transient'
    receipt = invalidate_stale_gp_context(n2)
    assert receipt['archived']
    assert not (n2 / 'full_context').exists()
    assert not (n2 / 'fitness_cache.json').exists()
    assert not (n2 / 'search_checkpoint.json').exists()
    assert (n2 / 'stale_context_recovery').is_dir()


def test_definition_errors_remain_deterministic(tmp_path):
    from quant.research.mining_retry import failure_kind
    n2 = tmp_path / 'N2'
    n2.mkdir()
    (n2 / 'process.log').write_text('ValueError: Definition changed\n', encoding='utf-8')
    assert failure_kind({'N2': 'N2 exit=1; see process.log'}, tmp_path) == 'deterministic_or_unknown'
