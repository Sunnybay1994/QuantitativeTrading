import datetime as dt
import json

import polars as pl
import pytest

from quant.data.index_benchmarks import normalize_index, read_index_benchmark


DATES = [dt.date(2014, 12, 31), dt.date(2015, 1, 5), dt.date(2015, 1, 6)]
SPEC = {'index_code': 'H00300.CSI', 'name': '300收益', 'return_type': 'total_return',
        'currency': 'CNY', 'level_unit': 'index_points'}


def raw():
    return pl.DataFrame({'ts_code': ['H00300.CSI'] * 3,
                         'trade_date': ['20141231', '20150105', '20150106'],
                         'close': [100.0, 110.0, 99.0], 'pre_close': [100.0, 100.0, 110.0],
                         'pct_chg': [0.0, 10.0, -10.0]})


def normalize(frame):
    return normalize_index(frame, spec=SPEC, sessions=DATES, start=dt.date(2015, 1, 1))


def test_anchor_produces_first_session_return_in_decimal_units():
    f = normalize(raw().reverse())
    assert f['trade_date'].to_list() == DATES[1:]
    assert f['daily_return'].to_list() == pytest.approx([0.1, -0.1])
    assert (1 + f['daily_return']).product() == pytest.approx(0.99)


@pytest.mark.parametrize('case', ['gap', 'duplicate', 'wrong_code', 'zero', 'nan', 'bad_percent', 'discontinuity'])
def test_corrupt_or_incomplete_index_cannot_be_published(case):
    f = raw()
    if case == 'gap':
        f = f.filter(pl.col('trade_date') != '20150105')
    elif case == 'duplicate':
        f = pl.concat([f, f.head(1)])
    elif case == 'wrong_code':
        f = f.with_columns(pl.lit('000300.SH').alias('ts_code'))
    elif case in ('zero', 'nan'):
        f = f.with_columns(pl.lit(0.0 if case == 'zero' else float('nan')).alias('close'))
    elif case == 'bad_percent':
        f = f.with_columns((pl.col('pct_chg') / 100).alias('pct_chg'))
    else:
        f = f.with_columns(pl.when(pl.col('trade_date') == '20150106').then(109.0)
                           .otherwise(pl.col('pre_close')).alias('pre_close'))
    with pytest.raises(ValueError):
        normalize(f)


def test_reader_requires_explicit_price_type_and_preserves_boundary_return(tmp_path):
    directory = tmp_path / 'clean/index_benchmarks/test'
    directory.mkdir(parents=True)
    frame = normalize(raw()).with_columns(pl.lit('price').alias('return_type'),
                                          pl.lit('000300.SH').alias('index_code'))
    frame.write_parquet(directory / 'data.parquet')
    (directory / 'summary.json').write_text(json.dumps({
        'start': '2015-01-01', 'end': '2015-01-06',
        'series': [{'index_code': '000300.SH', 'return_type': 'price'}]}))
    args = dict(data_root=tmp_path, version='test', index_code='000300.SH', start=DATES[-1], end=DATES[-1])
    with pytest.raises(ValueError, match='return type'):
        read_index_benchmark(**args)
    result = read_index_benchmark(**args, required_return_type='price')
    assert result['daily_return'].item() == pytest.approx(-0.1)
    with pytest.raises(ValueError, match='coverage'):
        read_index_benchmark(**{**args, 'end': dt.date(2015, 1, 7)}, required_return_type='price')
