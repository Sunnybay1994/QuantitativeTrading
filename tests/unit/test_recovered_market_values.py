from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.neutralization_inputs import (
    apply_recovered_market_values,
    neutralization_control_status,
)


_DATE = dt.date(2026, 7, 31)
_SYMBOLS = [f'{number:06d}.SZ' for number in range(21)]


def _inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    universe = pl.DataFrame({
        'symbol': [*_SYMBOLS, 'valid_outside', 'missing_outside'],
        'trade_date': [_DATE] * 23,
        'total_market_value': [None, float('nan'), float('inf'), 0., -5.] * 4 + [None, 999., None],
        'industry_l1': [None] + ['SW2021:480000'] * 22,
        'eligible': [True] * 23,
    })
    recovery = pl.DataFrame({
        'symbol': _SYMBOLS, 'as_of': [_DATE] * 21,
        'total_market_value': [1000. + number * 10 for number in range(21)],
        'recovery_status': ['recovered_same_day_raw'] * 21,
        'source_date': [_DATE] * 21,
        'raw_path': ['data/raw/frozen_daily_basic.parquet'] * 21,
        'evidence_reason': ['Same-day source close and CNY market value reconcile'] * 21,
        'market_value_unit': ['CNY'] * 21, 'normalization_pass': [True] * 21,
        'mv_reconciliation_pass': [True] * 21, 'close_match': [True] * 21,
        'fallback_used': [False] * 21,
    })
    return neutralization_control_status(universe), recovery


def test_verified_values_only_replace_21_invalid_keys_and_refresh_diagnostics(tmp_path: Path) -> None:
    universe, recovery = _inputs()
    original = universe.clone()
    path = tmp_path / 'recovered.parquet'
    recovery.write_parquet(path)
    original_bytes = path.read_bytes()
    result = apply_recovered_market_values(universe=universe, recovery_path=path)

    assert result.height == 23 and result['symbol'].to_list() == universe['symbol'].to_list()
    assert result['total_market_value'].head(21).to_list() == recovery['total_market_value'].to_list()
    assert result['total_market_value'].tail(2).to_list() == [999., None]
    assert result['market_value_recovered'].to_list() == [True] * 21 + [False, False]
    assert result['market_value_recovery_status'].head(21).to_list() == recovery['recovery_status'].to_list()
    assert result['market_value_source_date'].head(21).to_list() == [_DATE] * 21
    assert result['market_value_raw_path'].head(21).to_list() == recovery['raw_path'].to_list()
    assert result['market_value_evidence_reason'].head(21).to_list() == recovery['evidence_reason'].to_list()
    assert result['market_value_recovery_status'].tail(2).null_count() == 2
    assert result['size_missing'].sum() == 1
    assert result['industry_missing'].sum() == 1
    assert result['controls_valid'].sum() == 21
    assert not result['controls_valid'][0]  # Recovered size does not fill the unknown industry.
    assert_frame_equal(result.select('symbol', 'trade_date', 'industry_l1', 'eligible'),
                       original.select('symbol', 'trade_date', 'industry_l1', 'eligible'))
    assert_frame_equal(universe, original)
    assert path.read_bytes() == original_bytes
    assert_frame_equal(pl.read_parquet(path), recovery)


@pytest.mark.parametrize('source', ['unknown_key', 'existing_value', 'universe_duplicate', 'recovery_duplicate'])
def test_key_and_existing_value_conflicts_fail_without_mutating_inputs(tmp_path: Path, source: str) -> None:
    universe, recovery = _inputs()
    if source == 'unknown_key':
        universe = universe.filter(pl.col('symbol') != _SYMBOLS[0])
        message = 'unknown frozen-universe keys'
    elif source == 'existing_value':
        universe = universe.with_columns(pl.when(pl.col('symbol') == _SYMBOLS[0]).then(1000.)
                                         .otherwise(pl.col('total_market_value')).alias('total_market_value'))
        message = 'overwrite an existing valid market value'
    elif source == 'universe_duplicate':
        universe = pl.concat([universe, universe.head(1)])
        message = 'Frozen universe needs unique'
    else:
        recovery = pl.concat([recovery.head(20), recovery.head(1)])
        message = 'Recovery needs unique'
    original = universe.clone()
    path = tmp_path / 'conflict.parquet'
    recovery.write_parquet(path)
    original_bytes = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        apply_recovered_market_values(universe=universe, recovery_path=path)
    assert_frame_equal(universe, original)
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize(('field', 'replacement'), [
    ('source_date', _DATE + dt.timedelta(days=1)),
    ('source_date', _DATE - dt.timedelta(days=1)),
    ('market_value_unit', 'CNY_10K'),
    ('recovery_status', 'unverified'),
    ('normalization_pass', False),
    ('mv_reconciliation_pass', False),
    ('close_match', False),
    ('fallback_used', True),
    ('normalization_pass', None),
    ('raw_path', ''),
    ('evidence_reason', ''),
    ('total_market_value', 0.),
    ('total_market_value', -1.),
    ('total_market_value', float('inf')),
    ('total_market_value', float('nan')),
])
def test_invalid_or_incomplete_source_evidence_is_rejected(
    tmp_path: Path, field: str, replacement: object,
) -> None:
    universe, recovery = _inputs()
    recovery = recovery.with_columns(
        pl.when(pl.col('symbol') == _SYMBOLS[0])
        .then(pl.lit(replacement, dtype=recovery.schema[field]))
        .otherwise(pl.col(field)).alias(field))
    path = tmp_path / 'invalid.parquet'
    recovery.write_parquet(path)
    with pytest.raises(ValueError, match='verified same-day evidence'):
        apply_recovered_market_values(universe=universe, recovery_path=path)


def test_partial_recovery_table_and_reapplying_overlay_are_rejected(tmp_path: Path) -> None:
    universe, recovery = _inputs()
    path = tmp_path / 'partial.parquet'
    recovery.head(20).write_parquet(path)
    with pytest.raises(ValueError, match='complete 21-row'):
        apply_recovered_market_values(universe=universe, recovery_path=path)
    complete = tmp_path / 'complete.parquet'
    recovery.write_parquet(complete)
    result = apply_recovered_market_values(universe=universe, recovery_path=complete)
    with pytest.raises(ValueError, match='overwrite an existing valid market value'):
        apply_recovered_market_values(universe=result, recovery_path=complete)
