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
