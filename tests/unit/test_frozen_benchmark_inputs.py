from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.equal_weight_index import read_equal_weight_targets
from quant.data.factor_battery_inputs import read_frozen_battery_universe


_DATES = [dt.date(2022, 12, 30), dt.date(2026, 7, 31)]
_VERSION = 'test_frozen_20260912'
_INDEX = 'all_market_equal_weight'


def _targets() -> pl.DataFrame:
    return pl.DataFrame({
        'as_of': [_DATES[0], _DATES[0], _DATES[1], _DATES[1]],
        'effective_date': [dt.date(2023, 1, 3)] * 2 + [dt.date(2026, 8, 3)] * 2,
        'symbol': ['a', 'b', 'a', 'b'], 'weight': [.5, .5, .5, .5],
        'signal_close': [2., 3., 4., 5.], 'membership_date': [None] * 4,
        'saved_extra': ['keep'] * 4,
    }, schema_overrides={'membership_date': pl.Date})


def _write_targets(data_root: Path, frame: pl.DataFrame) -> None:
    folder = data_root / 'clean/equal_weight_indexes' / _VERSION
    folder.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(folder / f'{_INDEX}_selections.parquet')


def _read_targets(data_root: Path, dates: list[dt.date] | None = None) -> pl.DataFrame:
    return read_equal_weight_targets(data_root=data_root, version=_VERSION,
                                     index_name=_INDEX, as_of_dates=_DATES if dates is None else dates)


def _universe() -> pl.DataFrame:
    return pl.DataFrame({
        'symbol': ['a', 'b', 'a', 'b'],
        'trade_date': [_DATES[0], _DATES[0], _DATES[1], _DATES[1]],
        'eligible': [True, False, True, False], 'industry_l1': ['bank', None, 'bank', None],
        'total_market_value': [1e8, None, 2e8, None], 'amount20': [1e6, None, 2e6, None],
        'unused_column': [99] * 4,
    })


def _write_universe(statistics: Path, frame: pl.DataFrame) -> None:
    for year in sorted({date.year for date in frame['trade_date']}):
        folder = statistics / f'inputs/{year}'
        folder.mkdir(parents=True, exist_ok=True)
        frame.filter(pl.col('trade_date').dt.year() == year).write_parquet(folder / 'universe.parquet')


def test_targets_keep_all_original_columns_and_only_requested_dates(tmp_path: Path) -> None:
    original = _targets()
    _write_targets(tmp_path, original)
    assert_frame_equal(_read_targets(tmp_path, list(reversed(_DATES))), original)
    assert_frame_equal(_read_targets(tmp_path, [_DATES[1]]), original.tail(2))


@pytest.mark.parametrize('version', ['', '.', '..', '../outside', 'a/b', 'a\\b', 'C:other', '版本'])
def test_target_version_whitelist_rejects_paths(tmp_path: Path, version: str) -> None:
    with pytest.raises(ValueError, match='version'):
        read_equal_weight_targets(data_root=tmp_path, version=version, index_name=_INDEX,
                                  as_of_dates=_DATES)


def test_target_index_whitelist_rejects_other_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='index name'):
        read_equal_weight_targets(data_root=tmp_path, version=_VERSION, index_name='510300',
                                  as_of_dates=_DATES)


@pytest.mark.parametrize('dates', [[], [_DATES[0], _DATES[0]]])
def test_both_readers_reject_empty_or_duplicate_requests(tmp_path: Path, dates: list[dt.date]) -> None:
    with pytest.raises(ValueError, match='nonempty unique dates'):
        _read_targets(tmp_path, dates)
    with pytest.raises(ValueError, match='nonempty unique dates'):
        read_frozen_battery_universe(statistics=tmp_path, as_of_dates=dates)


def test_target_missing_date_is_not_replaced_by_latest_snapshot(tmp_path: Path) -> None:
    _write_targets(tmp_path, _targets())
    with pytest.raises(ValueError, match='Missing equal-weight target as_of dates'):
        _read_targets(tmp_path, [*_DATES, dt.date(2026, 8, 31)])


def test_duplicate_target_keys_raise(tmp_path: Path) -> None:
    _write_targets(tmp_path, pl.concat([_targets(), _targets().head(1)]))
    with pytest.raises(ValueError, match='Duplicate equal-weight target'):
        _read_targets(tmp_path)


@pytest.mark.parametrize('weight', [None, float('nan'), float('inf'), -0.5, 0.0])
def test_invalid_target_weights_raise(tmp_path: Path, weight: float | None) -> None:
    changed = _targets().with_columns(
        pl.when(pl.col('symbol') == 'a').then(pl.lit(weight, dtype=pl.Float64))
        .otherwise(pl.col('weight')).alias('weight'))
    _write_targets(tmp_path, changed)
    with pytest.raises(ValueError, match='finite and positive'):
        _read_targets(tmp_path)


def test_weight_sum_is_checked_separately_for_every_date(tmp_path: Path) -> None:
    changed = _targets().with_columns(pl.when(pl.col('as_of') == _DATES[0]).then(.4)
                                      .otherwise(.6).alias('weight'))
    _write_targets(tmp_path, changed)
    with pytest.raises(ValueError, match='sum to one per as_of date'):
        _read_targets(tmp_path)


@pytest.mark.parametrize('offset', [0, -1])
def test_effective_date_must_be_strictly_after_signal(tmp_path: Path, offset: int) -> None:
    changed = _targets().with_columns((pl.col('as_of') + pl.duration(days=offset)).alias('effective_date'))
    _write_targets(tmp_path, changed)
    with pytest.raises(ValueError, match='effective_date must follow as_of'):
        _read_targets(tmp_path)


def test_frozen_universe_reads_cross_years_and_keeps_ineligible_null_controls(tmp_path: Path) -> None:
    original = _universe()
    _write_universe(tmp_path, original)
    columns = ['symbol', 'trade_date', 'eligible', 'industry_l1', 'total_market_value', 'amount20']
    result = read_frozen_battery_universe(statistics=tmp_path, as_of_dates=list(reversed(_DATES)))
    assert_frame_equal(result, original.select(columns))
    assert result['eligible'].to_list() == [True, False, True, False]
    assert result['industry_l1'].null_count() == 2
    subset = read_frozen_battery_universe(statistics=tmp_path, as_of_dates=[_DATES[1]])
    assert_frame_equal(subset, original.select(columns).tail(2))


@pytest.mark.parametrize('missing_date', [dt.date(2026, 8, 31), dt.date(2025, 12, 31)])
def test_frozen_universe_missing_date_or_year_raises(tmp_path: Path, missing_date: dt.date) -> None:
    _write_universe(tmp_path, _universe())
    with pytest.raises(ValueError, match='Missing frozen universe'):
        read_frozen_battery_universe(statistics=tmp_path, as_of_dates=[*_DATES, missing_date])


def test_duplicate_frozen_universe_keys_raise(tmp_path: Path) -> None:
    _write_universe(tmp_path, pl.concat([_universe(), _universe().head(1)]))
    with pytest.raises(ValueError, match='Duplicate frozen universe'):
        read_frozen_battery_universe(statistics=tmp_path, as_of_dates=_DATES)


def test_optional_tradeability_is_saved_signal_day_evidence_not_eligibility(tmp_path: Path) -> None:
    original = _universe().with_columns(pl.lit(True).alias('traded'),
        pl.lit(True).alias('limits_known'), pl.Series('away_from_limits', [True, True, False, None]))
    _write_universe(tmp_path, original)
    result = read_frozen_battery_universe(statistics=tmp_path, as_of_dates=_DATES,
                                         include_tradeability=True)
    assert result['eligible'].to_list() == [True, False, True, False]
    assert result['traded'].to_list() == [True]*4
    assert result['away_from_limits'].to_list() == [True, True, False, None]
    default = read_frozen_battery_universe(statistics=tmp_path, as_of_dates=_DATES)
    assert 'traded' not in default.columns
