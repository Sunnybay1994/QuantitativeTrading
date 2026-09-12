import datetime as dt

import polars as pl
import pytest

from quant.data.held_control_supplements import read_held_risk_estimates


DAY = dt.date(2024, 4, 30)


def fixture(tmp_path):
    row = {'symbol': 'A', 'as_of': DAY, 'known_at': DAY,
        'source_date': dt.date(2024, 4, 29), 'industry_l1': 'SW2021:730000',
        'last_observed_total_market_value': 2042289329., 'market_value_unit': 'CNY',
        'suspended': True, 'same_day_size_missing': True,
        'normalization_pass': True, 'mv_reconciliation_pass': True, 'close_match': True,
        'industry_valid_from': dt.date(2021, 8, 2),
        'industry_valid_to': dt.date(2025, 1, 1), 'industry_raw_path': 'membership.parquet',
        'suspension_source_date': DAY, 'suspension_raw_path': 'suspension.parquet',
        'size_raw_path': 'basic.parquet', 'daily_raw_path': 'daily.parquet',
        'adjustment_raw_path': 'adjustment.parquet', 'capital_events_verified': True,
        'capital_coverage_start': dt.date(2024, 4, 29), 'capital_coverage_end': DAY,
        'capital_information_cutoff': DAY, 'capital_evidence_path': 'capital_check.json',
        'capital_events_reason': 'Complete coverage; no unhandled capital changes'}
    frame = pl.from_dicts([row, {**row, 'symbol': 'B'}])
    path = tmp_path/'supplement.parquet'
    frame.write_parquet(path)
    return frame, path


def test_verified_prior_cap_is_a_dated_estimate_for_requested_keys_only(tmp_path):
    _, path = fixture(tmp_path)
    before = path.read_bytes()
    row = read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY).row(0, named=True)
    assert row['symbol'] == 'A'
    assert row['total_market_value'] == row['last_observed_total_market_value'] == 2042289329.
    assert row['source_date'] == dt.date(2024, 4, 29) and row['staleness_days'] == 1
    assert row['risk_estimate'] is True and row['status'] == 'available'
    assert path.read_bytes() == before
    assert read_held_risk_estimates(path=path, symbols=[], as_of=DAY).is_empty()
    assert read_held_risk_estimates(path=path, symbols=['A'], as_of=dt.date(2024, 5, 1)).is_empty()


@pytest.mark.parametrize('verified, text', [(None, 'unknown'), (False, 'unhandled capital change')])
def test_unknown_and_known_capital_failure_remain_distinct_and_cannot_supply_size(
        tmp_path, verified, text):
    frame, path = fixture(tmp_path)
    frame.with_columns(pl.lit(verified, dtype=pl.Boolean).alias('capital_events_verified'),
        pl.lit(999.).alias('total_market_value'), pl.lit(True).alias('risk_estimate'),
        pl.lit('available').alias('status')).write_parquet(path)
    row = read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY).row(0, named=True)
    assert row['capital_events_verified'] is verified
    assert row['total_market_value'] is None and row['risk_estimate'] is False
    assert row['last_observed_total_market_value'] == 2042289329.
    assert row['status'] == 'unavailable' and text in row['reason']


@pytest.mark.parametrize('name, value, text', [
    ('source_date', dt.date(2024, 5, 1), 'later than'),
    ('known_at', dt.date(2024, 5, 1), 'later than'),
    ('source_date', dt.date(2024, 4, 22), '7 calendar'),
    ('source_date', DAY, '7 calendar'),
    ('industry_valid_from', dt.date(2024, 5, 1), 'industry interval'),
    ('industry_valid_to', DAY, 'industry interval'),
    ('suspension_source_date', dt.date(2024, 4, 29), 'confirmed suspension'),
    ('suspended', False, 'confirmed suspension'),
    ('same_day_size_missing', False, 'use current controls'),
    ('capital_coverage_start', DAY, 'complete dated coverage'),
    ('capital_coverage_end', dt.date(2024, 4, 29), 'complete dated coverage'),
    ('capital_information_cutoff', dt.date(2024, 5, 6), 'complete dated coverage'),
    ('capital_evidence_path', '', 'complete dated coverage'),
    ('size_raw_path', '', 'Missing source evidence'),
    ('last_observed_total_market_value', float('nan'), 'normalized CNY'),
    ('last_observed_total_market_value', -1., 'normalized CNY'),
    ('market_value_unit', '10k CNY', 'normalized CNY'),
    ('normalization_pass', False, 'normalized CNY'),
    ('mv_reconciliation_pass', False, 'normalized CNY'),
    ('close_match', False, 'normalized CNY'),
])
def test_incomplete_or_future_evidence_returns_explicit_unavailable(tmp_path, name, value, text):
    frame, path = fixture(tmp_path)
    frame.with_columns(pl.lit(value).alias(name)).write_parquet(path)
    row = read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY).row(0, named=True)
    assert row['total_market_value'] is None and row['risk_estimate'] is False
    assert text in row['reason']


def test_seven_calendar_days_is_inclusive(tmp_path):
    frame, path = fixture(tmp_path)
    frame.with_columns(pl.lit(dt.date(2024, 4, 23)).alias('source_date'),
        pl.lit(dt.date(2024, 4, 23)).alias('capital_coverage_start')).write_parquet(path)
    row = read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY).row(0, named=True)
    assert row['risk_estimate'] is True and row['staleness_days'] == 7


def test_duplicate_keys_are_rejected(tmp_path):
    frame, path = fixture(tmp_path)
    pl.concat([frame, frame.head(1)]).write_parquet(path)
    with pytest.raises(ValueError, match='duplicate/null'):
        read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY)


def test_unknown_capital_requires_nullable_boolean_not_string(tmp_path):
    frame, path = fixture(tmp_path)
    frame.with_columns(pl.lit('unknown').alias('capital_events_verified')).write_parquet(path)
    with pytest.raises(ValueError, match='types'):
        read_held_risk_estimates(path=path, symbols=['A'], as_of=DAY)
