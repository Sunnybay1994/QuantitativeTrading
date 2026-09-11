import copy
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.factor_battery_screen import screen_statistics


def fixture():
    settings = tomllib.loads(Path('configs/factors/battery.toml').read_text(encoding='utf-8'))
    rows = []
    for factor in ('a', 'b'):
        for variant in settings['variants']:
            rows.append({'factor': factor, 'variant': variant, 'months': 96,
                         'newey_west_t': 3., 'icir': .3, 'yearly_positive_fraction': .7,
                         'p_value': .02 if factor == 'a' and variant == 'raw' else None,
                         'group_statistics': {'long_short_sharpe': .5}})
    return rows, settings


def test_bh_keeps_missing_tests_and_does_not_change_registered_admission():
    rows, settings = fixture()
    result = screen_statistics(pl.from_dicts(rows), factors=['a', 'b'], settings=settings)
    row = result.filter((pl.col('factor') == 'a') & (pl.col('variant') == 'raw')).row(0, named=True)
    assert row['bh_adjusted_p'] == pytest.approx(.08)
    assert row['bh_discovery'] is False
    assert row['statistical_pass'] is True
    strict = copy.deepcopy(settings)
    strict['multiple_testing']['admission_requires_fdr'] = True
    assert not screen_statistics(pl.from_dicts(rows), factors=['a', 'b'], settings=strict)['statistical_pass'].any()


def test_negative_direction_and_short_history_fail_without_flipping_sign():
    rows, settings = fixture()
    rows[0].update(newey_west_t=-6., icir=-.8)
    rows[1].update(months=95)
    rows[2]['group_statistics']['long_short_sharpe'] = None
    result = screen_statistics(pl.from_dicts(rows), factors=['a', 'b'], settings=settings)
    assert result['statistical_pass'].sum() == 1
    assert result.filter(pl.col('factor') == 'a')['statistical_failures'].to_list() == [
        ['directional_icir'], ['history']]


def test_missing_or_duplicate_family_rows_cannot_shrink_multiple_testing_family():
    rows, settings = fixture()
    for bad in (rows[:-1], rows+[rows[0]]):
        with pytest.raises(ValueError, match='complete unique'):
            screen_statistics(pl.from_dicts(bad), factors=['a', 'b'], settings=settings)
