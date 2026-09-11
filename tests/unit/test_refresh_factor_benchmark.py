import datetime as dt
import tomllib

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.factor_benchmark import read_factor_benchmark, refresh_factor_benchmark
from quant.data.mappers import TushareBarMapper


def fixture(tmp_path, monkeypatch):
    from quant.data import factor_panels, factor_benchmark

    dates = [dt.date(2026, 9, day) for day in (7, 8, 9)]
    daily = pl.DataFrame({'ts_code': ['510300.SH'] * 3,
        'trade_date': [day.strftime('%Y%m%d') for day in dates],
        'open': [4.] * 3, 'high': [4.2] * 3, 'low': [3.8] * 3, 'close': [4., 4.1, 4.2],
        'vol': [100.] * 3, 'amount': [40.] * 3})
    adj = daily.select('ts_code', 'trade_date').with_columns(pl.lit(1.5).alias('adj_factor'))
    bars = TushareBarMapper().map(daily.with_columns(
        pl.col('ts_code').alias('_request_symbol'), pl.lit('SH').alias('_market'))).with_columns(
            pl.lit(1.5).alias('adj_factor'))
    folder = tmp_path / 'clean/factor_benchmark/base'
    folder.mkdir(parents=True)
    bars.head(2).write_parquet(folder / 'bars.parquet')
    config = tmp_path / 'refresh.toml'
    config.write_text('# keep this comment\nfactor_benchmark_snapshot = "base" # source\nother = 42\n')
    monkeypatch.setattr(factor_panels, 'available_sessions', lambda root, end: tuple(d for d in dates if d <= end))
    monkeypatch.setattr(factor_benchmark.time, 'sleep', lambda delay: None)
    return config, bars, daily.tail(2), adj.tail(2), dates


def test_increment_preserves_base_updates_config_and_second_run_is_noop(tmp_path, monkeypatch):
    config, expected, daily, adj, dates = fixture(tmp_path, monkeypatch)
    calls = []

    class Client:
        def query_raw(self, endpoint, **params):
            calls.append((endpoint, params))
            return daily if endpoint == 'fund_daily' else adj

    original = (tmp_path / 'clean/factor_benchmark/base/bars.parquet').read_bytes()
    result = refresh_factor_benchmark(data_root=tmp_path, config=config, end=dates[-1], client=Client())
    assert result['new_rows'] == 1 and len(calls) == 2
    assert tomllib.loads(config.read_text())['factor_benchmark_snapshot'] == result['snapshot']
    assert '# keep this comment' in config.read_text() and 'other = 42' in config.read_text()
    assert_frame_equal(read_factor_benchmark(tmp_path, config, dates[0], dates[-1]), expected)
    assert (tmp_path / 'clean/factor_benchmark/base/bars.parquet').read_bytes() == original
    assert len(list((tmp_path / 'raw/tushare').glob('*/date=*/*.parquet'))) == 2
    again = refresh_factor_benchmark(data_root=tmp_path, config=config, end=dates[-1], client=Client())
    assert again['new_rows'] == 0 and len(calls) == 2


@pytest.mark.parametrize('problem', ['missing_day', 'changed_seam', 'duplicate_adjustment'])
def test_bad_increment_preserves_config_and_old_snapshot(tmp_path, monkeypatch, problem):
    config, _, daily, adj, dates = fixture(tmp_path, monkeypatch)
    if problem == 'missing_day':
        daily, adj = daily.head(1), adj.head(1)
    elif problem == 'changed_seam':
        adj = adj.with_columns(pl.lit(1.6).alias('adj_factor'))
    else:
        adj = pl.concat([adj, adj.head(1)])

    class Client:
        def query_raw(self, endpoint, **params):
            return daily if endpoint == 'fund_daily' else adj

    original = config.read_bytes()
    with pytest.raises((ValueError, pl.exceptions.ComputeError)):
        refresh_factor_benchmark(data_root=tmp_path, config=config, end=dates[-1], client=Client())
    assert config.read_bytes() == original
    assert len(list((tmp_path / 'clean/factor_benchmark').iterdir())) == 1
