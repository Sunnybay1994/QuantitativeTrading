import datetime as dt

import polars as pl
import pytest

from quant.data import equal_weight_index as module


def test_extension_requires_august_signal_even_when_september_is_not_finished():
    dates = (dt.date(2026, 7, 31), dt.date(2026, 8, 3), dt.date(2026, 8, 31),
             dt.date(2026, 9, 1), dt.date(2026, 9, 11))
    universe = pl.DataFrame({'trade_date': [dates[0]]})
    with pytest.raises(ValueError, match='2026, 8, 31'):
        module.require_monthly_inputs(universe, dates, dates[0], dates[-1])
    module.require_monthly_inputs(pl.DataFrame({'trade_date': [dates[0], dates[2]]}), dates, dates[0], dates[-1])


def test_etf_extension_preserves_old_levels_and_validates_seam(tmp_path, monkeypatch):
    dates = [dt.date(2026, 1, 1)+dt.timedelta(days=i) for i in range(26)]
    old = pl.DataFrame({'symbol': ['510300.SH']*25, 'trade_date': dates[:25],
        'adjusted_close': [100.+i for i in range(25)], 'adjustment_method': ['total_return']*25, 'source': ['old']*25})
    fresh = pl.DataFrame({'symbol': ['510300.SH']*26, 'trade_date': dates,
        'adjusted_close': [(100.+i)/2 for i in range(26)], 'adjustment_method': ['total_return']*26, 'source': ['fresh']*26})
    prior = tmp_path/'clean/factor_benchmarks/old'
    prior.mkdir(parents=True)
    old.write_parquet(prior/'prices.parquet')
    incoming = tmp_path/'clean/research_price_1d/date=2026-01-26'
    incoming.mkdir(parents=True)
    fresh.write_parquet(incoming/'data.parquet')
    monkeypatch.setattr(module, 'available_sessions', lambda *_: tuple(dates))
    result = module.publish_etf_extension(data_root=tmp_path, previous='old', version='new', end=dates[-1])
    combined = pl.read_parquet(tmp_path/'clean/factor_benchmarks/new/prices.parquet')
    assert result['old_prefix_exact'] and result['new_rows'] == 1
    assert combined.head(25).equals(old)
    assert combined['adjusted_close'][-1] == 125.
    fresh.with_columns(pl.when(pl.col('trade_date') == dates[23]).then(999.)
        .otherwise(pl.col('adjusted_close')).alias('adjusted_close')).write_parquet(incoming/'data.parquet')
    with pytest.raises(ValueError, match='seam mismatch'):
        module.publish_etf_extension(data_root=tmp_path, previous='old', version='bad', end=dates[-1])
