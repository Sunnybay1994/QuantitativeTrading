import datetime as dt
from pathlib import Path

import pytest

from quant.data import refresh


def test_completed_session_cutoff_and_future_date():
    now = dt.datetime(2026, 9, 8, 8, 59, tzinfo=dt.timezone.utc)
    assert refresh.completed_date("today", now) == dt.date(2026, 9, 7)
    assert refresh.completed_date("today", now + dt.timedelta(minutes=1)) == dt.date(2026, 9, 8)
    assert refresh.completed_date("2026-09-04", now) == dt.date(2026, 9, 4)
    with pytest.raises(ValueError, match="future"):
        refresh.completed_date("2026-09-09", now)


def test_failure_stops_before_etf_refresh(monkeypatch, tmp_path: Path):
    config = tmp_path / "refresh.toml"
    config.write_text('etf_config = "configs/research/m2_s2_volatility_target.toml"')
    monkeypatch.setattr(refresh, "latest_session", lambda **kw: dt.date(2026, 9, 8))

    def failed(**kwargs):
        raise RuntimeError("unavailable stock response")

    def unexpected(**kwargs):
        pytest.fail("ETF refresh must not run after a failed stock stage")

    monkeypatch.setattr(refresh, "refresh_stocks", failed)
    monkeypatch.setattr(refresh, "refresh_etfs", unexpected)
    with pytest.raises(RuntimeError, match="unavailable stock response"):
        refresh.run_refresh(to="2026-09-08", data_root=tmp_path, artifact_root=tmp_path,
                            config=config, now=dt.datetime(2026, 9, 8, 20, tzinfo=refresh.SHANGHAI))


@pytest.mark.parametrize('lookback', [None, 7])
def test_refresh_minutes_uses_requested_day_when_mainland_closed(monkeypatch, tmp_path, lookback):
    config = tmp_path / "refresh.toml"
    config.write_text('etf_config = "configs/research/m2_s2_volatility_target.toml"')
    if lookback is not None:
        config.write_text(config.read_text() + f'\n[intraday]\nstock_lookback_days = {lookback}\n')
    monkeypatch.setattr(refresh, "latest_session", lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, "refresh_stocks", lambda **kw: {"new_dates": 0, "new_rows": 0})
    monkeypatch.setattr(refresh, "refresh_etfs", lambda **kw: {"new_rows": 0, "new_bar_rows": 0})
    monkeypatch.setattr(refresh, "refresh_limits", lambda **kw: 0)
    dates = []

    def minutes(**kwargs):
        dates.append(kwargs["end"])
        assert kwargs.get('stock_from') == (dt.date(2026, 9, 3) if lookback else None)
        return {"changed_rows": 15, "errors": []}

    monkeypatch.setattr(refresh, "refresh_intraday", minutes)
    result = refresh.run_refresh(to="2026-09-09", data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 9, 20, tzinfo=refresh.SHANGHAI))
    assert dates == [dt.date(2026, 9, 9)]
    assert result["message"] == "updated" and result["intraday_changed_rows"] == 15


def test_refresh_updates_factor_benchmark_after_prices(monkeypatch, tmp_path):
    config = tmp_path / 'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
                      'factor_benchmark_snapshot="base"\n')
    calls = []
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})

    def prices(**kwargs):
        calls.append('prices')
        return {'new_rows': 0, 'new_bar_rows': 0}

    def benchmark(**kwargs):
        assert calls == ['prices'] and kwargs['end'] == dt.date(2026, 9, 8)
        calls.append('benchmark')
        return {'new_rows': 1, 'snapshot': 'new'}

    monkeypatch.setattr(refresh, 'refresh_etfs', prices)
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(refresh, 'refresh_factor_benchmark', benchmark)
    result = refresh.run_refresh(to='2026-09-08', data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 8, 20, tzinfo=refresh.SHANGHAI), intraday=False)
    assert result['message'] == 'updated' and result['factor_benchmark_new_rows'] == 1
    assert result['factor_benchmark_snapshot'] == 'new'


@pytest.mark.parametrize('minute_errors', [[], ['missing minute input']])
def test_factor_refresh_follows_all_inputs_and_marks_minute_availability(monkeypatch, tmp_path, minute_errors):
    config = tmp_path / 'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
                      'factor_benchmark_snapshot="base"\n[factors]\nenabled=true\n')
    calls = []
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(refresh, 'refresh_intraday', lambda **kw: {'errors': minute_errors, 'stock_changed_rows': 10})

    def benchmark(**kwargs):
        calls.append('benchmark')
        return {'new_rows': 0}

    def factors(**kwargs):
        assert calls == ['benchmark'] and kwargs['end'] == dt.date(2026, 9, 8)
        assert kwargs['minute_start'] == dt.date(2020, 1, 1)
        assert kwargs['minute_available'] is (not bool(minute_errors))
        calls.append('factors')
        return {'years': [{'year': 2026}], 'message': 'updated'}

    monkeypatch.setattr(refresh, 'refresh_factor_benchmark', benchmark)
    monkeypatch.setattr(refresh, 'refresh_factors', factors)
    result = refresh.run_refresh(to='2026-09-08', data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 8, 20, tzinfo=refresh.SHANGHAI))
    assert calls == ['benchmark', 'factors']
    assert result['message'] == ('partial' if minute_errors else 'updated')
    assert result['intraday_errors'] == minute_errors


def test_factor_stage_preserves_incremental_engine_arguments(monkeypatch, tmp_path):
    from quant.factors import compute

    def run(**kwargs):
        assert kwargs['end'] == dt.date(2026, 9, 8)
        assert kwargs['start'] == dt.date(2010, 1, 1)
        assert kwargs['selected'] == 'all' and 'rebuild' not in kwargs
        return {'years': [], 'factor_count': 329, 'output': 'result'}

    monkeypatch.setattr(compute, 'run', run)
    result = refresh.refresh_factors(data_root=tmp_path, artifact_root=tmp_path,
        config=tmp_path/'refresh.toml', end=dt.date(2026, 9, 8),
        settings={'library': 'configs/factors/library', 'start': '2010-01-01'})
    assert result['message'] == 'no-op' and result['factor_count'] == 329


def test_financial_snapshot_updates_before_factors_and_uses_calendar_date(monkeypatch, tmp_path):
    config = tmp_path/'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
        'financial_snapshot="old"\n[financials]\nenabled=true\nlookback_days=3\n[factors]\nenabled=true\n')
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 11))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)

    def financials(**kwargs):
        assert kwargs['end'] == dt.date(2026, 9, 12) and kwargs['lookback_days'] == 3
        config.write_text(config.read_text().replace('"old"', '"new"'))
        return {'new_rows': 2, 'financial_snapshot': 'new'}

    def factors(**kwargs):
        assert 'financial_snapshot="new"' in kwargs['config'].read_text()
        assert kwargs['end'] == dt.date(2026, 9, 11)
        return {'years': []}

    monkeypatch.setattr(refresh, 'refresh_disclosed_financials', financials)
    monkeypatch.setattr(refresh, 'refresh_factors', factors)
    result = refresh.run_refresh(to='2026-09-12', data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 12, 20, tzinfo=refresh.SHANGHAI), intraday=False)
    assert result['message'] == 'updated' and result['financials']['new_rows'] == 2


def test_input_quality_after_factors_makes_missing_data_visible(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from quant.data import daily_input_quality
    from quant.factors import library

    config = tmp_path/'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
        '[factors]\nenabled=true\nlibrary="unused"\n[quality]\nenabled=true\nbattery_config="configs/factors/battery.toml"\n')
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 10))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(library, 'load_library', lambda *args: [SimpleNamespace(id='a', family='daily')])
    calls = []

    def factors(**kwargs):
        calls.append('factors')
        return {'years': []}

    def quality(**kwargs):
        assert calls == ['factors'] and kwargs['end'] == dt.date(2026, 9, 10)
        assert kwargs['factors'] == [{'id': 'a', 'family': 'daily'}]
        assert kwargs['minimum_symbols'] == 100
        return {'errors': ['a: missing keys']}

    monkeypatch.setattr(refresh, 'refresh_factors', factors)
    monkeypatch.setattr(daily_input_quality, 'run_quality', quality)
    result = refresh.run_refresh(to='2026-09-10', data_root=tmp_path, artifact_root=tmp_path,
        config=config, intraday=False)
    assert result['message'] == 'partial' and result['input_quality']['errors']


@pytest.mark.parametrize('daily_present', [True, False])
def test_missing_minutes_compute_only_independent_factors(monkeypatch, tmp_path, daily_present):
    from types import SimpleNamespace
    from quant.factors import compute, library
    from quant.factors.intraday_low_frequency import DAILY_NAMES

    definitions = [SimpleNamespace(id='minute', expr='minute_' + DAILY_NAMES[0])]
    if daily_present:
        definitions.append(SimpleNamespace(id='daily', expr='adj_close / adj_open'))
    monkeypatch.setattr(library, 'load_library', lambda *args: definitions)
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        return {'years': [{'year': 2026}], 'factor_count': 1, 'output': 'daily_increment'}

    monkeypatch.setattr(compute, 'run', run)
    result = refresh.refresh_factors(data_root=tmp_path, artifact_root=tmp_path,
        config=tmp_path/'refresh.toml', end=dt.date(2026, 9, 14),
        settings={'library': 'unused', 'start': '2010-01-01'},
        minute_start=dt.date(2026, 9, 14), minute_available=False)
    assert result['skipped_minute_factors'] == ['minute']
    assert len(calls) == int(daily_present)
    if daily_present:
        assert calls[0]['selected'] == 'daily'
        assert result['minute_rebuild'] is None
    else:
        assert result['factor_count'] == 0


def test_late_stock_minutes_rebuild_only_minute_consumers(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from quant.factors import compute, library
    from quant.factors.intraday_low_frequency import DAILY_NAMES
    minute_name = 'minute_' + DAILY_NAMES[0]
    monkeypatch.setattr(library, 'load_library', lambda *args: [
        SimpleNamespace(id='daily', expr='adj_close'), SimpleNamespace(id='minute', expr=minute_name)])
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return {'years': [] if len(calls)==1 else [{'year': 2026}], 'factor_count': 2 if len(calls)==1 else 1,
                'output': 'increment' if len(calls)==1 else 'minute_rebuild'}
    monkeypatch.setattr(compute, 'run', run)
    result = refresh.refresh_factors(data_root=tmp_path, artifact_root=tmp_path,
        config=tmp_path/'refresh.toml', end=dt.date(2026, 9, 11),
        settings={'library': 'unused', 'start': '2010-01-01'}, minute_start=dt.date(2026, 9, 5))
    assert len(calls)==2 and calls[1]['selected']=='minute' and calls[1]['rebuild'] is True
    assert calls[1]['start']==dt.date(2026, 9, 5) and calls[1]['end']==dt.date(2026, 9, 11)
    assert result['message']=='updated' and result['minute_rebuild']['output']=='minute_rebuild'


def test_industry_update_precedes_factors_and_passes_rebuild_date(monkeypatch, tmp_path):
    config=tmp_path/'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
                      '[industry]\nenabled=true\n[factors]\nenabled=true\n')
    monkeypatch.setattr(refresh,'latest_session',lambda **kw: dt.date(2026,9,11))
    monkeypatch.setattr(refresh,'refresh_stocks',lambda **kw: {'new_dates':0,'new_rows':0})
    monkeypatch.setattr(refresh,'refresh_etfs',lambda **kw: {'new_rows':0,'new_bar_rows':0})
    monkeypatch.setattr(refresh,'refresh_limits',lambda **kw: 0)
    calls=[]
    def industry(**kwargs):
        assert kwargs['end']==dt.date(2026,9,11)
        calls.append('industry')
        return {'new_intervals':7,'rebuild_from':'2026-09-11'}
    def factors(**kwargs):
        assert calls==['industry'] and kwargs['industry_start']==dt.date(2026,9,11)
        calls.append('factors')
        return {'years':[]}
    monkeypatch.setattr(refresh,'refresh_industry',industry)
    monkeypatch.setattr(refresh,'refresh_factors',factors)
    result=refresh.run_refresh(to='2026-09-11',data_root=tmp_path,artifact_root=tmp_path,
                               config=config,intraday=False)
    assert calls==['industry','factors'] and result['message']=='updated'


def test_expired_industry_rebuilds_only_industry_consumers(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from quant.factors import compute,library
    monkeypatch.setattr(library,'load_library',lambda *args: [
        SimpleNamespace(id='daily',expr='adj_close'),
        SimpleNamespace(id='industry',expr='ind_neutralize(adj_close, industry_l1)')])
    calls=[]
    def run(**kwargs):
        calls.append(kwargs)
        return {'years':[],'factor_count':2,'output':'result'}
    monkeypatch.setattr(compute,'run',run)
    result=refresh.refresh_factors(data_root=tmp_path,artifact_root=tmp_path,config=tmp_path/'refresh.toml',
        end=dt.date(2026,9,11),settings={'library':'unused','start':'2010-01-01'},
        industry_start=dt.date(2026,9,11))
    assert len(calls)==2 and calls[1]['selected']=='industry' and calls[1]['rebuild'] is True
    assert calls[1]['start']==dt.date(2026,9,11)
    assert result['industry_rebuild'] and result['message']=='updated'
