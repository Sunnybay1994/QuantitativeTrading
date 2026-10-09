import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.research.pead_event_market_inputs import freeze
from quant.research.residual_momentum_inputs import digest, write_json


def inputs(tmp_path):
    data = tmp_path/'data'
    output = tmp_path/'output'
    frozen = output/'inputs'
    frozen.mkdir(parents=True)
    (frozen/'refresh.toml').write_text('stock_snapshot="history"\n')
    write_json(frozen/'manifest.json', {'files': {'refresh.toml': digest(frozen/'refresh.toml')}})
    source = data/'clean/tushare_bulk/snapshots/history/bar_1d/asset=stock/year=2010'
    source.mkdir(parents=True)
    bars = pl.DataFrame({'symbol': ['600001.SH', '000001.SZ', '900001.SH'],
        'trade_date': [dt.date(2010, 1, 4)]*3, 'close': [10., 20., 30.], 'amount': [1e8]*3})
    bars.write_parquet(source/'data.parquet')
    names = data/'clean/stock_name_history'
    names.mkdir(parents=True)
    pl.DataFrame({'symbol': bars['symbol'], 'name': ['former', 'normal', 'B'],
        'start_date': [dt.date(1999, 1, 1)]*3, 'end_date': [None]*3},
        schema_overrides={'end_date': pl.Date}).write_parquet(names/'data.parquet')
    return output, data, source/'data.parquet', bars


def test_freeze_complete_increment_override_and_historical_population(tmp_path):
    output, data, source, bars = inputs(tmp_path)
    increment = data/'clean/tushare_incremental/date=2010-01-04'
    increment.mkdir(parents=True)
    bars.head(1).with_columns(pl.lit(11.).alias('close')).write_parquet(increment/'bar_1d.parquet')
    for table in ('adjust_factor', 'daily_basic'):
        bars.head(0).write_parquet(increment/f'{table}.parquet')
    partial = data/'clean/tushare_incremental/date=2010-01-05'
    partial.mkdir()
    bars.with_columns(pl.lit(dt.date(2010, 1, 5)).alias('trade_date')).write_parquet(partial/'bar_1d.parquet')
    before = digest(source)
    result = freeze(output=output, data_root=data,
        config=Path('configs/research/pead_event_market_inputs_20260930.toml'))
    got = pl.read_parquet(output/'market_inputs/bars.parquet')
    assert got.height == 2 and set(got['symbol']) == {'600001.SH', '000001.SZ'}
    assert got.filter(pl.col('symbol') == '600001.SH')['close'].item() == 11.
    assert result['overlap_rows'] == 1 and digest(source) == before


def test_freeze_duplicate_inside_partition_is_not_silently_removed(tmp_path):
    output, data, source, bars = inputs(tmp_path)
    pl.concat([bars, bars.head(1)]).write_parquet(source)
    with pytest.raises(ValueError, match='Duplicate daily keys'):
        freeze(output=output, data_root=data,
            config=Path('configs/research/pead_event_market_inputs_20260930.toml'))
    assert not (output/'market_inputs').exists()


def test_freeze_rejects_modified_parent_input(tmp_path):
    output, data, _, _ = inputs(tmp_path)
    (output/'inputs/refresh.toml').write_text('stock_snapshot="changed"')
    with pytest.raises(ValueError, match='Financial-stage input changed'):
        freeze(output=output, data_root=data,
            config=Path('configs/research/pead_event_market_inputs_20260930.toml'))
