import datetime as dt
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from quant.factors import compute
from quant.research.factor_financials import attach_financial_factors, financial_input_names
from tests.unit.test_earnings_surprise import income
from tests.unit.test_factor_expressions import prepared, sample_bars


NAME = 'pit_sue8_context_v2'


def switched_income():
    original = income([float(i * i) for i in range(16)])
    first = original['available_date'][-1] + dt.timedelta(days=1)
    publication = first + dt.timedelta(days=1)
    revised = original.tail(1).with_columns(pl.lit('4').alias('comp_type'),
        pl.lit('1').alias('update_flag'),
        *[pl.lit(publication).alias(c) for c in ('ann_date', 'f_ann_date', 'available_date')])
    dates = tuple(first + dt.timedelta(days=i) for i in range(4))
    return pl.concat([original, revised]), dates


def test_daily_carry_erases_old_anchor_only_after_type_change_is_known():
    history, dates = switched_income()
    panel = pl.DataFrame({'symbol': ['000001.SZ'] * len(dates), 'trade_date': dates, 'close': [10.] * len(dates)})
    values = attach_financial_factors(panel, {'income': history}, ('pit_sue8', NAME))
    assert financial_input_names((f'rank({NAME}) + pit_sue8',)) == ('pit_sue8', NAME)
    assert values['pit_sue8'].null_count() == 0
    assert values[NAME].to_list()[:2] == values['pit_sue8'].to_list()[:2]
    assert values[NAME].to_list()[2:] == [None, None]


def test_new_version_incremental_compute_keeps_legacy_partition_unchanged(tmp_path, monkeypatch):
    history, dates = switched_income()
    bars = sample_bars().filter(pl.col('symbol') == '600000.SH').head(len(dates)).with_columns(
        pl.Series('trade_date', dates, dtype=pl.Date), pl.lit('000001.SZ').alias('symbol'))
    monkeypatch.setattr(compute, 'available_sessions', lambda root, end: tuple(day for day in dates if day <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col('trade_date').is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, 'read_factor_inputs', read)
    monkeypatch.setattr(compute, 'read_factor_financial_history', lambda *args, **kwargs: {'income': history})
    common = dict(refresh_config=Path('configs/data/refresh_sue_context_v2_20260912.toml'),
        library=Path('configs/factors/library'), start=dates[0], artifact_root=tmp_path/'artifacts')
    for mode in ('full', 'increment'):
        data_root = tmp_path/mode
        compute.run(**common, data_root=data_root, selected='pit_sue8', end=dates[-1])
        legacy = data_root/f'factors/pit_sue8/year={dates[0].year}/data.parquet'
        preserved = legacy.read_bytes()
        if mode == 'increment':
            compute.run(**common, data_root=data_root, selected=NAME, end=dates[1])
        compute.run(**common, data_root=data_root, selected=NAME, end=dates[-1])
        assert legacy.read_bytes() == preserved
        assert compute.run(**common, data_root=data_root, selected=NAME, end=dates[-1])['years'] == []
    path = f'factors/{NAME}/year={dates[0].year}/data.parquet'
    full = pl.read_parquet(tmp_path/'full'/path)
    assert full['value'].null_count() == 2
    assert_frame_equal(full, pl.read_parquet(tmp_path/'increment'/path))
