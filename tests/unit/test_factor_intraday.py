import datetime as dt
import math

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.factor_intraday_inputs import read_factor_minute_inputs
from quant.factors.expressions import evaluate_expressions, required_history
from quant.factors.intraday_low_frequency import DAILY_NAMES, compute_intraday_low_frequency_factors
from quant.research.factor_intraday import attach_minute_factors, minute_input_names
from tests.unit.test_intraday_low_frequency import _day


def _varied(day):
    bars = _day(day)
    returns = [0.003 * math.sin(i * 1.7) + 0.001 for i in range(48)]
    close = 10 * np.exp(np.cumsum(returns))
    opening = np.r_[10.0, close[:-1]]
    volume = np.arange(1, 49, dtype=float) * 100
    return bars.with_columns(pl.Series('open', opening), pl.Series('close', close),
        pl.Series('high', np.maximum(close, opening)), pl.Series('low', np.minimum(close, opening)),
        pl.Series('volume', volume), pl.Series('amount', volume * close)), np.array(returns)


@pytest.mark.parametrize('mode', ['valid', 'partial', 'mismatch', 'off_grid', 'primary_complete', 'tdx_only'])
def test_tdx_fallback_requires_complete_reconciled_days_and_preserves_source(tmp_path, mode):
    day = dt.date(2026, 1, 5)
    full = _varied(day)[0].with_columns(pl.lit('baostock').alias('source'))
    daily = full.group_by('symbol', 'trade_date').agg(
        pl.col('close').last(), pl.col('volume').sum(), pl.col('amount').sum())
    primary = full if mode == 'primary_complete' else full.slice(1)
    alternative = full.with_columns(pl.lit('tdx').alias('source'))
    if mode == 'partial':
        alternative = alternative.slice(1)
    elif mode == 'mismatch':
        alternative = alternative.with_columns((pl.col('amount') * 2).alias('amount'))
    elif mode == 'off_grid':
        alternative = alternative.with_columns(
            (pl.col('bar_start') + pl.duration(seconds=1)).alias('bar_start'))
    paths = []
    for source, frame in [('baostock', primary), ('tdx', alternative)]:
        if mode == 'tdx_only' and source == 'baostock':
            continue
        path = tmp_path / f'clean/bar_intraday/freq=5m/source={source}/symbol=600000.SH/data.parquet'
        path.parent.mkdir(parents=True)
        frame.write_parquet(path)
        paths.append((path, path.read_bytes()))
    result = list(read_factor_minute_inputs(tmp_path, daily))[0]
    expected_source = 'tdx' if mode in ('valid', 'tdx_only') else 'baostock'
    assert result['source'].unique().to_list() == [expected_source]
    assert result.height == (48 if mode in ('valid', 'tdx_only', 'primary_complete') else 47)
    if expected_source == 'tdx':
        assert result['daily_reconciled'].all()
    for path, original in paths:
        assert path.read_bytes() == original


def test_expanded_daily_moments_and_correlations_match_numpy():
    day = dt.date(2026, 1, 5)
    minute, returns = _varied(day)
    row = compute_intraday_low_frequency_factors(minute, sessions=(day,), window=1, expanded=True).row(0, named=True)
    expected = {
        'realized_vol': np.sqrt(sum(returns**2)),
        'kurtosis': 48 * sum(returns**4) / sum(returns**2)**2,
        'open_return': np.exp(sum(returns[:6])) - 1,
        'volume_return_corr': np.corrcoef(returns, minute['volume'].to_numpy())[0, 1],
        'return_autocorr': np.corrcoef(returns[1:], returns[:-1])[0, 1],
    }
    for name, value in expected.items():
        assert row[f'daily_{name}'] == pytest.approx(value, abs=1e-12)
    flat = compute_intraday_low_frequency_factors(_day(day, flat=True), sessions=(day,), window=1, expanded=True)
    assert flat['daily_realized_vol'].item() == 0
    assert flat['daily_open_return'].item() == 0
    for name in ('kurtosis', 'volume_return_corr', 'return_autocorr'):
        assert flat[f'daily_{name}'].item() is None


def test_minutes_left_join_missing_days_and_reconciliation(tmp_path):
    sessions = tuple(dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(23))
    minute = pl.concat([_varied(day)[0] for day in sessions])
    daily = minute.group_by('symbol', 'trade_date').agg(
        pl.col('close').last(), pl.col('volume').sum(), pl.col('amount').sum()).sort('symbol', 'trade_date')
    missing_symbol = daily.with_columns(pl.lit('000001.SZ').alias('symbol'))
    panel = pl.concat([daily, missing_symbol]).sort('symbol', 'trade_date')
    directory = tmp_path / 'clean/bar_intraday/freq=5m/source=baostock/symbol=600000.SH'
    directory.mkdir(parents=True)
    file = directory / 'data.parquet'
    minute.write_parquet(file)
    expressions = {f'intraday_{name}20': f'ts_mean(minute_{name},20)' for name in DAILY_NAMES}
    names = minute_input_names(tuple(expressions.values()))
    assert len(names) == 9 and required_history(expressions['intraday_skew20']) == 19

    def calculate(input_panel):
        attached = attach_minute_factors(input_panel, read_factor_minute_inputs(tmp_path, input_panel), sessions, names)
        return evaluate_expressions(attached, expressions).sort('symbol', 'trade_date')

    full = calculate(panel)
    assert full.height == panel.height
    assert full.filter(pl.col('symbol') == '000001.SZ')['intraday_tail_amount20'].null_count() == 23
    assert full.filter(pl.col('symbol') == '600000.SH')['intraday_tail_amount20'].count() == 4
    original = compute_intraday_low_frequency_factors(minute, sessions=sessions)
    for name in ('tail_amount', 'smart_vwap', 'skew', 'open_amount'):
        assert_frame_equal(full.filter(pl.col('symbol') == '600000.SH').select(f'intraday_{name}20'),
                           original.select(f'intraday_{name}20'))
    truncated = calculate(panel.filter(pl.col('trade_date') <= sessions[20]))
    assert_frame_equal(truncated, full.filter(pl.col('trade_date') <= sessions[20]))
    # A missing file is missing coverage; a missing middle day breaks the full 20-session window.
    minute.filter(pl.col('trade_date') != sessions[2]).write_parquet(file)
    gap = calculate(panel).filter(pl.col('symbol') == '600000.SH')
    assert gap['intraday_tail_amount20'].count() == 1
    minute.write_parquet(file)
    bad_reference = panel.with_columns(pl.when((pl.col('symbol') == '600000.SH') &
        (pl.col('trade_date') == sessions[2])).then(pl.col('amount') * 2).otherwise(pl.col('amount')).alias('amount'))
    assert calculate(bad_reference).filter(pl.col('symbol') == '600000.SH')['intraday_tail_amount20'].count() == 1


def test_minute_compute_cross_year_increment_matches_full(tmp_path, monkeypatch):
    from pathlib import Path
    from quant.factors import compute

    sessions = tuple(dt.date(2025, 12, 1) + dt.timedelta(days=i) for i in range(60))
    minute = pl.concat([_varied(day)[0] for day in sessions])
    bars = minute.group_by('symbol', 'trade_date').agg(pl.col('open').first(), pl.col('high').max(),
        pl.col('low').min(), pl.col('close').last(), pl.col('volume').sum(), pl.col('amount').sum()
    ).with_columns(pl.lit(1.0).alias('adj_factor'), pl.lit('tushare').alias('source')).sort('symbol', 'trade_date')
    monkeypatch.setattr(compute, 'available_sessions', lambda root, end: tuple(d for d in sessions if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col('trade_date').is_between(start, end))
        return subset, subset

    monkeypatch.setattr(compute, 'read_factor_inputs', read)
    selected = ','.join(f'intraday_{name}20' for name in DAILY_NAMES)
    args = dict(refresh_config=Path('unused'), library=Path('configs/factors/library'), selected=selected,
                start=sessions[0], artifact_root=tmp_path / 'artifacts')
    for mode in ('full', 'increment'):
        directory = tmp_path / mode / 'clean/bar_intraday/freq=5m/source=baostock/symbol=600000.SH'
        directory.mkdir(parents=True)
        minute.write_parquet(directory / 'data.parquet')
    compute.run(**args, data_root=tmp_path / 'increment', end=sessions[38])
    compute.run(**args, data_root=tmp_path / 'increment', end=sessions[-1])
    compute.run(**args, data_root=tmp_path / 'full', end=sessions[-1])
    for file in (tmp_path / 'full/factors').glob('*/year=*/data.parquet'):
        assert_frame_equal(pl.read_parquet(file), pl.read_parquet(tmp_path / 'increment' / file.relative_to(tmp_path / 'full')))
    current = pl.read_parquet(tmp_path / 'full/factors/intraday_realized_vol20/year=2026/data.parquet')
    assert current['value'].count() == 29
    assert compute.run(**args, data_root=tmp_path / 'increment', end=sessions[-1])['years'] == []
