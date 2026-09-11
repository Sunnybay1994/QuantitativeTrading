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


def test_refresh_minutes_uses_requested_day_when_mainland_closed(monkeypatch, tmp_path):
    config = tmp_path / "refresh.toml"
    config.write_text('etf_config = "configs/research/m2_s2_volatility_target.toml"')
    monkeypatch.setattr(refresh, "latest_session", lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, "refresh_stocks", lambda **kw: {"new_dates": 0, "new_rows": 0})
    monkeypatch.setattr(refresh, "refresh_etfs", lambda **kw: {"new_rows": 0, "new_bar_rows": 0})
    monkeypatch.setattr(refresh, "refresh_limits", lambda **kw: 0)
    dates = []

    def minutes(**kwargs):
        dates.append(kwargs["end"])
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
def test_factor_refresh_follows_all_inputs_and_stops_on_minute_error(monkeypatch, tmp_path, minute_errors):
    config = tmp_path / 'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
                      'factor_benchmark_snapshot="base"\n[factors]\nenabled=true\n')
    calls = []
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(refresh, 'refresh_intraday', lambda **kw: {'errors': minute_errors})

    def benchmark(**kwargs):
        calls.append('benchmark')
        return {'new_rows': 0}

    def factors(**kwargs):
        assert calls == ['benchmark'] and kwargs['end'] == dt.date(2026, 9, 8)
        calls.append('factors')
        return {'years': [{'year': 2026}], 'message': 'updated'}

    monkeypatch.setattr(refresh, 'refresh_factor_benchmark', benchmark)
    monkeypatch.setattr(refresh, 'refresh_factors', factors)
    result = refresh.run_refresh(to='2026-09-08', data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 8, 20, tzinfo=refresh.SHANGHAI))
    assert calls == (['benchmark'] if minute_errors else ['benchmark', 'factors'])
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
