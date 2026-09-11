import datetime as dt
import json

import polars as pl

from quant.data import daily_input_quality as quality


def stock_frames():
    dates = [dt.date(2026, 2, 13), dt.date(2026, 2, 24)]
    bars = pl.DataFrame({'trade_date': dates, 'symbol': ['a', 'a'], 'close': [10., 11.]})
    basic = bars.clone()
    adjustment = bars.select(pl.col('trade_date').alias('effective_date'), 'symbol', pl.lit(1.).alias('adj_factor'))
    return dates, bars, basic, adjustment


def test_calendar_closures_are_not_missing_sessions_but_real_holes_are():
    dates, bars, basic, adjustment = stock_frames()
    result = quality.check_stock_inputs(bars, basic, adjustment, sessions=tuple(dates))
    assert result['missing_sessions'] == [] and result['expected_sessions'] == 2
    assert result['latest_traded_symbols'] == 1
    result = quality.check_stock_inputs(bars.head(1), basic, adjustment, sessions=tuple(dates))
    assert result['missing_sessions'] == ['2026-02-24']
    result = quality.check_stock_inputs(bars, basic.head(1), pl.concat([adjustment, adjustment.tail(1)]),
                                        sessions=tuple(dates))
    assert result['daily_basic_missing_keys'] == 1 and result['adjustment_duplicate_keys'] == 1


def test_nonfinite_and_duplicate_factor_values_are_not_counted_as_coverage():
    frame = pl.DataFrame({'ts_code': ['a', 'a', 'b', 'c', 'd', 'extra'],
                         'value': [1., 1., None, float('nan'), float('inf'), 3.]})
    result = quality.inspect_factor(frame, symbols={'a', 'b', 'c', 'd', 'missing'})
    assert result['valid_symbols'] == 1 and result['valid_share'] == .2
    assert result['nonfinite_values'] == 2 and result['duplicate_keys'] == 1
    assert result['missing_bar_symbols'] == 1 and result['extra_symbols'] == 1


def test_actual_values_and_missing_files_are_distinguished(tmp_path, monkeypatch):
    dates, bars, basic, adjustment = stock_frames()
    monkeypatch.setattr(quality, 'available_sessions', lambda *args: tuple(dates))
    tables = {'bar_1d': bars, 'daily_basic': basic, 'adjust_factor': adjustment}
    monkeypatch.setattr(quality, 'read_stock_data', lambda **kwargs: tables[kwargs['table']])
    folder = tmp_path/'factors'/'sparse'/'year=2026'
    folder.mkdir(parents=True)
    pl.DataFrame({'trade_date': dates, 'ts_code': ['a', 'a'], 'value': [2., None]}).write_parquet(folder/'data.parquet')
    args = dict(data_root=tmp_path, config=tmp_path/'config', end=dates[-1],
                financials={'financial_snapshot': 'new', 'unresolved_announcements': [{'symbol': 'a'}]},
                factors=[{'id': 'sparse', 'family': 'monthly'}])
    result = quality.run_quality(**args, output=tmp_path/'first')
    assert result['errors'] == [] and result['factors_without_valid_values'] == ['sparse']
    assert result['factors_meeting_symbol_count'] == 0
    table = pl.read_parquet(tmp_path/'first'/'factor_coverage.parquet')
    assert table['last_valid_date_this_year'].item() == '2026-02-13'
    assert result['unresolved_financial_symbols'] == ['a']
    assert json.loads((tmp_path/'first'/'summary.json').read_text()) == result
    args['factors'].append({'id': 'absent', 'family': 'daily'})
    result = quality.run_quality(**args, output=tmp_path/'second')
    assert len(result['errors']) == 1 and 'absent' in result['errors'][0]
