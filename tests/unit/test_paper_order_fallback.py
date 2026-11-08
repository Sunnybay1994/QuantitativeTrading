import datetime as dt
import hashlib
import json
import tomllib

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
