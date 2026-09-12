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


def test_daily_value_nulls_are_reported_and_wrong_finite_values_are_errors(tmp_path, monkeypatch):
    date = dt.date(2026, 2, 24)
    bars = pl.DataFrame({'trade_date': [date]*3, 'symbol': ['a', 'b', 'c'], 'close': [10.]*3})
    basic = bars.with_columns(pl.Series('dividend_yield_ttm', [None, 0., 2.]))
    adjustment = bars.select(pl.col('trade_date').alias('effective_date'), 'symbol', pl.lit(1.).alias('adj_factor'))
    tables = {'bar_1d': bars, 'daily_basic': basic, 'adjust_factor': adjustment}
    monkeypatch.setattr(quality, 'available_sessions', lambda *args: (date,))
    monkeypatch.setattr(quality, 'read_stock_data', lambda **kwargs: tables[kwargs['table']])
    folder = tmp_path/'factors'/'daily_dividend_yield_ttm'/'year=2026'
    folder.mkdir(parents=True)
    values = pl.DataFrame({'trade_date': [date]*3, 'ts_code': ['a', 'b', 'c'], 'value': [None, 0., .02]})
    values.write_parquet(folder/'data.parquet')
    args = dict(data_root=tmp_path, config=tmp_path/'config', end=date, financials={},
                factors=[{'id': 'daily_dividend_yield_ttm', 'family': 'daily'}])
    result = quality.run_quality(**args, output=tmp_path/'valid')
    assert result['errors'] == []
    assert result['daily_value_input_checks'][0]['reasons'] == {'source_field_null': 1, 'observed': 2}
    observed = pl.read_parquet(tmp_path/'valid'/'daily_value_input_reasons.parquet')
    assert observed.filter(pl.col('symbol') == 'a')['factor_value'].item() is None
    # A source null must not silently become a finite factor, even zero.
    values.with_columns(pl.col('value').fill_null(0.)).write_parquet(folder/'data.parquet')
    result = quality.run_quality(**args, output=tmp_path/'wrong')
    assert result['daily_value_input_checks'][0]['unexpected_factor_values'] == 1
    assert any('unexpected finite values' in error for error in result['errors'])


def test_sue_context_findings_reach_daily_report_without_changing_values(tmp_path, monkeypatch):
    date = dt.date(2026, 2, 24)
    bars = pl.DataFrame({'trade_date': [date], 'symbol': ['a'], 'close': [10.]})
    adjustment = bars.select(pl.col('trade_date').alias('effective_date'), 'symbol', pl.lit(1.).alias('adj_factor'))
    tables = {'bar_1d': bars, 'daily_basic': bars, 'adjust_factor': adjustment}
    monkeypatch.setattr(quality, 'available_sessions', lambda *args: (date,))
    monkeypatch.setattr(quality, 'read_stock_data', lambda **kwargs: tables[kwargs['table']])
    folder = tmp_path/'factors'/'pit_sue8'/'year=2026'
    folder.mkdir(parents=True)
    values = pl.DataFrame({'trade_date': [date], 'ts_code': ['a'], 'value': [3.]})
    values.write_parquet(folder/'data.parquet')

    def context(**kwargs):
        assert kwargs['snapshot'] == 'frozen' and kwargs['as_of'] == date
        assert kwargs['factor_values']['value'].item() == 3.
        return kwargs['pool'].with_columns(pl.lit(3.).alias('factor_value'),
            pl.lit('non_industrial').alias('report_context'), pl.lit(True).alias('unexpected_factor_value'))

    monkeypatch.setattr(quality, 'read_sue_report_context', context)
    result = quality.run_quality(data_root=tmp_path, config=tmp_path/'config', end=date,
        financials={'financial_snapshot': 'frozen'}, factors=[{'id': 'pit_sue8', 'family': 'pit'}],
        output=tmp_path/'result')
    assert result['sue_report_context_checks'][0]['unexpected_factor_values'] == 1
    assert any('compatible latest PIT report context' in error for error in result['errors'])
    assert pl.read_parquet(tmp_path/'result'/'sue_report_context.parquet')['factor_value'].item() == 3.
    assert pl.read_parquet(folder/'data.parquet').equals(values)
