import datetime as dt
import json

import pytest

from quant.research import run_daily_model_forecast as daily


def arguments(tmp_path, monkeypatch):
    selection = tmp_path/'selection'
    selection.mkdir()
    (selection/'selection.json').write_text(json.dumps({'forward_start':'2026-09-14',
        'conclusion':'RESEARCH_ONLY','auto_trade':False}))
    monkeypatch.setattr(daily,'latest_session',lambda **kwargs: dt.date(2026,9,14))
    return dict(to='today',selection=selection,output=tmp_path/'record',data_root=tmp_path,
        refresh_config=tmp_path/'refresh.toml',artifact_root=tmp_path,
        now=dt.datetime(2026,9,14,18,tzinfo=daily.SHANGHAI))


@pytest.mark.parametrize('errors,count', [([],2393),(['missing bars'],0),([],0)])
def test_refresh_then_forecast_and_failures_remain_visible(tmp_path,monkeypatch,errors,count):
    args=arguments(tmp_path,monkeypatch)
    calls=[]
    def refresh(**kwargs):
        calls.append('refresh')
        return {'latest_session':'2026-09-14','intraday_errors':[], 'input_quality':{'errors':errors}}
    def forecast(**kwargs):
        assert calls==['refresh'] and kwargs['as_of']==dt.date(2026,9,14)
        calls.append('forecast')
        return {'prediction_stocks':count}
    monkeypatch.setattr(daily,'run_refresh',refresh)
    monkeypatch.setattr(daily,'run_forecast',forecast)
    result=daily.run_daily(**args)
    assert calls==(['refresh'] if errors else ['refresh','forecast'])
    assert result['status']==('input_errors' if errors else 'recorded' if count else 'missing_model_inputs')
    assert result['auto_trade'] is False
    with pytest.raises(FileExistsError):
        daily.run_daily(**args)


def test_saved_input_rehearsal_does_not_refresh(tmp_path,monkeypatch):
    args=arguments(tmp_path,monkeypatch)
    monkeypatch.setattr(daily,'latest_session',lambda **kwargs:dt.date(2026,9,11))
    monkeypatch.setattr(daily,'run_refresh',lambda **kwargs:pytest.fail('no provider refresh'))
    with pytest.raises(ValueError,match='rehearsal'):
        daily.run_daily(**args,saved_data=True)
    assert not args['output'].exists()
    def forecast(**kwargs):
        assert kwargs['rehearsal'] is True and kwargs['as_of']==dt.date(2026,9,11)
        return {'prediction_stocks':2393}
    monkeypatch.setattr(daily,'run_forecast',forecast)
    result=daily.run_daily(**args,saved_data=True,rehearsal=True)
    assert result['status']=='recorded' and result['saved_data'] is True


def test_saved_input_mode_does_not_fetch_a_missing_calendar(tmp_path,monkeypatch):
    from quant.data import refresh
    monkeypatch.setattr(refresh,'TushareConnector',lambda **kwargs:pytest.fail('no network in saved mode'))
    with pytest.raises(ValueError,match='Saved calendar'):
        refresh.latest_session(data_root=tmp_path,through=dt.date(2026,9,11),refresh_calendar=False)
