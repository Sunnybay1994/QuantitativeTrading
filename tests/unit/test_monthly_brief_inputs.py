import datetime as dt
import json

import polars as pl
import pytest

from quant.data.monthly_brief_inputs import realized, series_facts, source_id


def test_facts_use_signal_close_and_keep_short_history_missing():
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(70)]
    frame = pl.DataFrame({'date': dates, 'unit_nav': [1.01 ** i for i in range(70)]})
    facts = series_facts(frame, as_of=dates[60], name='index', source='fixed')
    assert facts['return_20'] == pytest.approx(1.01 ** 20 - 1)
    assert facts['return_60'] == pytest.approx(1.01 ** 60 - 1)
    assert facts['annualized_volatility_60'] == pytest.approx(0., abs=1e-12)
    assert facts == series_facts(frame.head(61), as_of=dates[60], name='index', source='fixed')
    short = series_facts(frame.head(20), as_of=dates[19], name='index', source='fixed')
    assert short['return_20'] is None and short['annualized_volatility_60'] is None
    with pytest.raises(ValueError, match='complete dated'):
        series_facts(frame.head(20), as_of=dates[20], name='index', source='fixed')


def test_future_target_rejected_before_reading_data(tmp_path):
    (tmp_path/'facts.json').write_text(json.dumps({'target_date': '2099-01-01'}))
    with pytest.raises(ValueError, match='not observable'):
        realized(inputs=tmp_path, output=tmp_path/'out', known_through=dt.date(2099, 1, 1))
    assert not (tmp_path/'out').exists()


def test_realized_return_uses_saved_anchor_and_rejects_revisions(tmp_path, monkeypatch):
    config = '[benchmarks]\netf_total_return_snapshot="old"\nequal_weight_snapshot="old"\n'
    (tmp_path/'benchmarks.toml').write_text(config)
    settings = {'etf_total_return_snapshot': 'old', 'equal_weight_snapshot': 'old'}
    source = source_id('510300', settings)
    facts = {'as_of': '2020-01-02', 'target_date': '2020-01-03',
             'series': [{'id': '510300', 'level': 2., 'source': source}]}
    (tmp_path/'facts.json').write_text(json.dumps(facts))
    frame = pl.DataFrame({'date': [dt.date(2020, 1, 2), dt.date(2020, 1, 3)], 'unit_nav': [2., 2.2]})
    monkeypatch.setattr('quant.data.monthly_brief_inputs.load_return_benchmarks', lambda **kw: {'510300': frame})
    result = realized(inputs=tmp_path, output=tmp_path/'out', known_through=dt.date(2020, 1, 3))
    assert result['series'][0]['total_return'] == pytest.approx(.1)
    assert result['series'][0]['reference_level'] == 2.
    frame = frame.with_columns((pl.col('unit_nav') * 2).alias('unit_nav'))
    with pytest.raises(ValueError, match='Origin level'):
        realized(inputs=tmp_path, output=tmp_path/'changed', known_through=dt.date(2020, 1, 3))
    assert not (tmp_path/'changed').exists()
