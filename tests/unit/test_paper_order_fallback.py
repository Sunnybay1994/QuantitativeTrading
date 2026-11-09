import datetime as dt
import hashlib
import json
import tomllib
import shutil

import polars as pl
import pytest

from quant.execution import paper_order_fallback as fallback


def setup_account(tmp_path):
    account=tmp_path/'account';state=account/'2026-11-05/state.json'
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps(dict(date='2026-11-05',holdings={},pending=[],receivables=[])))
    forecast_root=tmp_path/'forecasts';forecast_root.mkdir()
    config=tmp_path/'paper.toml'
    config.write_text(f'[paper]\nauto_trade=false\n[model]\nselection="selection"\n'
        f'forecast_root={json.dumps(forecast_root.as_posix())}\n[data]\nrefresh_config="unused"\n'
        'warmup_start=2026-10-01\n')
    daily=tmp_path/'daily.toml'
    daily.write_text(f'auto_trade=false\n[q10]\nconfig={json.dumps(config.as_posix())}\n'
                     f'output={json.dumps(account.as_posix())}\n')
    return account,state,forecast_root,config,daily


def test_old_forecast_not_promoted_to_current_readiness(tmp_path,monkeypatch):
    account,state,root,config,daily=setup_account(tmp_path)
    old=root/'old/model/forecast';old.mkdir(parents=True)
    (old/'summary.json').write_text('{"as_of":"2026-11-05"}')
    monkeypatch.setattr(fallback,'read_stock_paper_calendar',lambda root:pl.DataFrame(dict(
        date=[dt.date(2026,11,5),dt.date(2026,11,6),dt.date(2026,11,9)],is_open=[True]*3)))
    monkeypatch.setattr(fallback.q10_paper,'run',lambda **kw:pytest.fail('Old forecast cannot advance account'))
    before=state.read_bytes()
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result')
    assert result['status']=='unavailable'
    assert 'same-date' in result['accounts']['q10']['reason']
    assert state.read_bytes()==before and not (account/'latest_orders.md').exists()


def test_active_account_writer_is_never_raced(tmp_path,monkeypatch):
    account,state,root,config,daily=setup_account(tmp_path)
    monkeypatch.setattr(fallback,'freeze_account',lambda **kw:pytest.fail('Concurrent account writer'))
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result',account_writer=True)
    assert result['status']=='unavailable'
    assert 'Account writer' in result['accounts']['q10']['reason']
    assert not (account/'latest_orders.md').exists()


def test_future_available_at_is_rejected_before_freeze(tmp_path,monkeypatch):
    account,state,root,config,daily=setup_account(tmp_path)
    path=root/'run/model/forecast';path.mkdir(parents=True)
    (path/'summary.json').write_text(json.dumps(dict(as_of='2026-11-06',recorded_at='2099-01-01T21:00:00+08:00')))
    monkeypatch.setattr(fallback,'read_stock_paper_calendar',lambda root:pl.DataFrame(dict(
        date=[dt.date(2026,11,5),dt.date(2026,11,6),dt.date(2026,11,9)],is_open=[True]*3)))
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result')
    assert result['status']=='unavailable' and 'actual fallback clock' in result['accounts']['q10']['reason']
    assert not (account/'latest_orders.md').exists()


def test_expired_preparation_cannot_publish_any_account(tmp_path,monkeypatch):
    account,state,root,config,daily=setup_account(tmp_path)
    def freeze(**kwargs):
        raise TimeoutError('Frozen order preparation exceeded its remaining capital-path budget')
    monkeypatch.setattr(fallback,'freeze_account',freeze)
    monkeypatch.setattr(fallback.q10_paper,'run',lambda **kw:pytest.fail('Expired preparation cannot write'))
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result',budget_seconds=1)
    assert result['status']=='unavailable' and 'budget' in result['accounts']['q10']['reason']
    assert not (account/'latest_orders.md').exists()


@pytest.mark.parametrize('budget',[0,-1,121])
def test_budget_cannot_consume_the_writer_wait_reserve(tmp_path,budget):
    with pytest.raises(ValueError,match='120'):
        fallback.run(end=dt.date(2026,11,6),output=tmp_path/'result',budget_seconds=budget)


def fake_freeze(**kw):
    account, output = kw['account'], kw['output']
    output.mkdir(parents=True)
    config = output/'config.toml'
    shutil.copy2(kw['config_path'], config)
    state = sorted(account.glob('????-??-??/state.json'))[-1]
    return dict(_config_path=config, _frozen_sha256={'config.toml':fallback.digest(config)},
                _controls_sha256=None, _account_snapshot=dict(path=str(state),sha256=fallback.digest(state)))


def test_primary_publishes_before_slow_shadow_and_a2_share_budget(tmp_path,monkeypatch):
    account,state,_,config,daily=setup_account(tmp_path)
    shadow=tmp_path/'shadow'
    shutil.copytree(account,shadow)
    with daily.open('a') as f:
        for name,path in [('q10_shadow',shadow),('account_30w_top15',tmp_path/'a2')]:
            f.write(f'[{name}]\nconfig={json.dumps(config.as_posix())}\noutput={json.dumps(path.as_posix())}\n')
    clock=[100.]
    monkeypatch.setattr(fallback.time,'monotonic',lambda:clock[0])
    def freeze(**kw):
        if kw['account']==shadow:
            assert (account/'published').exists()
            clock[0]+=20
            fallback.guard(kw['deadline'])
        return fake_freeze(**kw)
    monkeypatch.setattr(fallback,'freeze_account',freeze)
    def publish(**kw):
        kw['preflight']()
        kw['before_publish']()
        (kw['output']/'published').write_text('primary ready')
        return dict(as_of='2026-11-06')
    monkeypatch.setattr(fallback.q10_paper,'run',publish)
    from quant.execution import account_30w_top15_frozen
    monkeypatch.setattr(account_30w_top15_frozen,'run',lambda *a,**kw:pytest.fail('Expired A2 must not start'))
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result',budget_seconds=10)
    assert result['accounts']['q10']['status']=='complete'
    assert 'budget' in result['accounts']['q10_shadow']['reason']
    assert 'budget' in result['observation_accounts']['account_30w_top15']['reason']


def test_snapshot_advanced_after_freeze_is_checked_inside_mutex(tmp_path,monkeypatch):
    account,state,_,config,daily=setup_account(tmp_path)
    monkeypatch.setattr(fallback,'freeze_account',fake_freeze)
    actual_run=fallback.q10_paper.run
    monkeypatch.setattr(fallback.q10_paper,'_admitted_config',lambda *a: ('',{}))
    monkeypatch.setattr(fallback.q10_paper,'_run',lambda **kw:pytest.fail('Stale freeze must not enter writer'))
    def race(**kw):
        # Another writer has finished before mutex acquisition; prior outside-lock
        # checks cannot make this frozen snapshot safe.
        state.write_text('{"date":"2026-11-05","new_fills":true}')
        return actual_run(**kw)
    monkeypatch.setattr(fallback.q10_paper,'run',race)
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result')
    assert 'Account advanced' in result['accounts']['q10']['reason']
    assert 'new_fills' in state.read_text()


def test_a2_retains_writer_flag_and_shared_deadline(tmp_path,monkeypatch):
    _,_,_,config,daily=setup_account(tmp_path)
    with daily.open('a') as f:
        f.write(f'[account_30w_top15]\nconfig={json.dumps(config.as_posix())}\noutput="a2"\n')
    from quant.execution import account_30w_top15_frozen
    calls=[]
    def observe(spec,**kw):
        calls.append(kw)
        return dict(status='not_started')
    monkeypatch.setattr(account_30w_top15_frozen,'run',observe)
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result',account_writer=True,budget_seconds=2)
    assert len(calls)==1 and calls[0]['account_writer'] is True
    assert calls[0]['deadline']-fallback.time.monotonic() <= 2
    assert result['observation_accounts']['account_30w_top15']['status']=='not_started'


def test_frozen_input_mutation_rejected_before_publication(tmp_path,monkeypatch):
    _,state,_,_,daily=setup_account(tmp_path)
    before=state.read_bytes()
    monkeypatch.setattr(fallback,'freeze_account',fake_freeze)
    def mutate(**kw):
        kw['config_path'].write_text('tampered')
        kw['before_publish']()
        pytest.fail('Tampered inputs published')
    monkeypatch.setattr(fallback.q10_paper,'run',mutate)
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result')
    assert 'Frozen order inputs changed' in result['accounts']['q10']['reason']
    assert state.read_bytes()==before


@pytest.mark.parametrize('changed',['state','config'])
def test_initial_parsed_bytes_cannot_bind_to_replaced_source_hash(tmp_path,monkeypatch,changed):
    _,state,root,config,daily=setup_account(tmp_path)
    forecast=root/'run/model/forecast';forecast.mkdir(parents=True)
    (forecast/'summary.json').write_text(json.dumps(dict(as_of='2026-11-06',recorded_at='2026-11-06T22:00:00+08:00')))
    monkeypatch.setattr(fallback,'read_stock_paper_calendar',lambda root:pl.DataFrame(dict(
        date=[dt.date(2026,11,5),dt.date(2026,11,6),dt.date(2026,11,9)],is_open=[True]*3)))
    data=tmp_path/'data'
    folder=data/'clean/stock_paper_inputs/date=2026-11-06';folder.mkdir(parents=True)
    for name in ('instruments','names','limits','suspensions','dividends'):
        (folder/(name+'.parquet')).write_bytes(b'presence check only')
    payload=daily.read_text().replace('auto_trade=false\n','auto_trade=false\ndata_root='+json.dumps(data.as_posix())+'\n')
    daily.write_text(payload)
    def replace_after_read(*args):
        target=state if changed=='state' else config
        replacement=target.with_suffix('.replacement')
        replacement.write_bytes(target.read_bytes()+b'\n ')
        replacement.replace(target)
        return {str(p):fallback.digest(p) for p in (state,config)}
    monkeypatch.setattr(fallback,'sources',replace_after_read)
    monkeypatch.setattr(fallback,'read_stock_paper_inputs',lambda *a:pytest.fail('Inconsistent seed reached input reader'))
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result')
    assert 'after initial read' in result['accounts']['q10']['reason']
    assert not (tmp_path/'result/frozen/q10').exists()


def test_budget_expiring_after_preflight_cannot_publish(tmp_path,monkeypatch):
    _,state,_,_,daily=setup_account(tmp_path)
    before=state.read_bytes()
    clock=[100.]
    monkeypatch.setattr(fallback.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(fallback,'freeze_account',fake_freeze)
    def calculate(**kw):
        kw['preflight']()
        clock[0]+=11
        kw['before_publish']()
        pytest.fail('Expired computation reached publication')
    monkeypatch.setattr(fallback.q10_paper,'run',calculate)
    result=fallback.run(config=daily,end=dt.date(2026,11,6),output=tmp_path/'result',budget_seconds=10)
    assert 'budget' in result['accounts']['q10']['reason']
    assert state.read_bytes()==before
