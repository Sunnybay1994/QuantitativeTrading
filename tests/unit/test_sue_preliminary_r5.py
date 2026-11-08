import datetime as dt
import json

import polars as pl
import pytest

from quant.factors.earnings_surprise import compute_sue8
from quant.research.sue_preliminary_s4 import (
    SH, build_monthly_s4, normalize, read_inputs, score_point,
    select_points, visible_inputs,
)


def native(table='forecast', **changes):
    row = dict(ts_code='600000.SH', ann_date='20261028', end_date='20260930',
               source_row_id='a', source_raw_path='raw/a.json', update_flag='1',
               observed_at=dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC),
               available_at=dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC),
               net_profit_min=10., net_profit_max=20., last_parent_net=100., n_income=150000.)
    row.update(changes)
    return pl.from_dicts([row])


def test_native_units_and_basis_are_not_inferred():
    f = normalize(native(), 'forecast')
    assert f['point_cny'].item() == 150000
    assert f['last_parent_net'].item() == 100
    assert f['parent_point_cny'].item() is None
    assert f['input_reason'].item() == 'parent_profit_basis_unverified'
    e = normalize(native(), 'express')
    assert e['point_cny'].item() == 150000
    assert e['parent_point_cny'].item() is None


def test_first_seen_bound_not_announcement_backdated():
    f = normalize(native(), 'forecast')
    assert visible_inputs(f, dt.date(2026, 10, 30)).is_empty()
    assert visible_inputs(f, dt.date(2026, 11, 5)).is_empty()
    assert visible_inputs(f, dt.date(2026, 11, 6)).height == 1
    midnight = dt.datetime(2026, 11, 6, tzinfo=SH)
    assert visible_inputs(normalize(native(available_at=midnight), 'forecast'), dt.date(2026, 11, 6)).is_empty()


@pytest.mark.parametrize('changes,reason', [
    ({'available_at': dt.datetime(2026, 11, 4, tzinfo=dt.UTC)}, 'invalid_arrival'),
    ({'net_profit_min': 21.}, 'reversed_profit_range'),
    ({'net_profit_min': float('nan')}, 'missing_native_profit'),
    ({'source_row_id': None}, 'invalid_native_key'),
])
def test_invalid_native_values_remain_missing(changes, reason):
    assert normalize(native(**changes), 'forecast')['input_reason'].item() == reason


def test_revision_conflict_and_no_older_period_rescue():
    old = normalize(native(parent_net_profit_min_10000cny=10., parent_net_profit_max_10000cny=20.), 'forecast')
    revised = normalize(native(source_row_id='b', net_profit_max=30., parent_net_profit_min_10000cny=10.,
                               parent_net_profit_max_10000cny=30.), 'forecast')
    conflicted = select_points(pl.concat([old, revised]), dt.date(2026, 11, 6))
    assert conflicted['input_reason'].item() == 'ambiguous_latest_revision'
    express = normalize(native(n_income_attr_p=150000., source_row_id='e'), 'express')
    express_revision = normalize(native(n_income_attr_p=160000., source_row_id='f'), 'express')
    cross_source = select_points(pl.concat([old, express, express_revision]), dt.date(2026, 11, 6))
    assert cross_source['input_reason'].item() == 'ambiguous_latest_revision'
    missing_latest = normalize(native(source_row_id='c', end_date='20261231'), 'forecast')
    selected = select_points(pl.concat([old, missing_latest]), dt.date(2026, 11, 6))
    assert selected['input_reason'].item() == 'period_not_ended'
    assert selected['source_row_id'].item() == 'c'


def test_earliest_observation_dedup_and_flat_d2_reader(tmp_path):
    base = tmp_path / 'clean/forecast/snapshot=d1/year=2026'
    base.mkdir(parents=True)
    (base.parent / 'summary.json').write_text('{}')
    native().write_parquet(base / 'data.parquet')
    d2 = tmp_path / 'clean/forecast/snapshot=d2_x'
    d2.mkdir()
    (d2 / 'summary.json').write_text('{}')
    later = native(observed_at=dt.datetime(2026, 11, 7, tzinfo=dt.UTC),
                   available_at=dt.datetime(2026, 11, 7, tzinfo=dt.UTC))
    revision = native(source_row_id='b', net_profit_max=30.)
    pl.concat([later, revision]).write_parquet(d2 / 'data.parquet')
    unpublished = tmp_path / 'clean/forecast/snapshot=unfinished'
    unpublished.mkdir()
    native(source_row_id='unpublished').write_parquet(unpublished / 'data.parquet')
    frame, manifest = read_inputs(tmp_path, known_at=dt.datetime(2026, 11, 8, tzinfo=dt.UTC))
    assert frame.height == 2
    assert frame.filter(pl.col('source_row_id') == 'a')['observed_at'].item().day == 5
    assert len(manifest) == 4


def income_chain():
    rows = []
    for year in range(2022, 2026):
        cumulative = 0.
        for quarter, (month, day) in enumerate([(3, 31), (6, 30), (9, 30), (12, 31)], 1):
            i = (year - 2022) * 4 + quarter
            cumulative += i * i + (i % 3) * 2.
            rows.append(dict(symbol='600000.SH', report_type='1', comp_type='1',
                             end_date=dt.date(year, month, day), n_income_attr_p=cumulative))
    return pl.from_dicts(rows)


def test_preliminary_score_exact_original_kernel_and_not_final_fallback():
    income = income_chain()
    last = income.tail(1).row(0, named=True)
    point = dict(symbol=last['symbol'], report_period_end=last['end_date'],
                 parent_point_cny=last['n_income_attr_p'], input_reason='usable')
    expected = compute_sue8(income).tail(1)['pit_sue8'].item()
    value, reason = score_point(income.head(-1), point)
    assert reason == 'VALID'
    assert value == pytest.approx(expected)
    assert score_point(income, point) == (None, 'final_report_already_visible')
    assert score_point(income.head(3), point)[0] is None


def test_original_kernel_missing_quarter_is_not_zero_filled():
    income = income_chain()
    last = income.tail(1).row(0, named=True)
    point = dict(symbol=last['symbol'], report_period_end=last['end_date'],
                 parent_point_cny=last['n_income_attr_p'], input_reason='usable')
    broken = income.head(-1).filter(pl.col('end_date') != dt.date(2025, 6, 30))
    assert score_point(broken, point)[0] is None


def test_monthly_adapter_does_not_touch_income_for_ineligible_input():
    result = build_monthly_s4(income_history=pl.DataFrame(),
        preliminary_history=normalize(native(), 'forecast'),
        signal_dates=(dt.date(2026, 10, 30), dt.date(2026, 11, 6)), candidate_symbols=('600000.SH',))
    assert result.factors['sue_prelim'].null_count() == 2
    assert result.eligibility['input_reason'].to_list() == ['no_visible_preliminary_input', 'parent_profit_basis_unverified']


def test_audit_real_receipt_keeps_metrics_unmeasured_and_does_not_register(tmp_path):
    from quant.research.sue_preliminary_audit import run
    data = tmp_path / 'data'
    folder = data / 'clean/forecast/snapshot=d2_x'
    folder.mkdir(parents=True)
    (folder / 'summary.json').write_text('{}')
    native().write_parquet(folder / 'data.parquet')
    calendar = data / 'clean/trade_calendar/market=SH'
    calendar.mkdir(parents=True)
    days = pl.date_range(dt.date(2026, 9, 1), dt.date(2026, 11, 30), eager=True)
    pl.DataFrame({'date': days, 'is_open': days.dt.weekday() <= 5}).write_parquet(calendar / 'data.parquet')
    from pathlib import Path
    result = run(config=Path('configs/research/sue_preliminary_s4_v1.toml'),
                 output=tmp_path / 'result', data_root=data, known_at=dt.datetime(2026, 11, 9, tzinfo=dt.UTC))
    assert result['status'] == 'SAMPLE_INSUFFICIENT'
    assert result['months_with_visible_inputs'] == 0
    assert not result['completed_battery'] and not result['registered']
    assert all(result[name] is None for name in ('incremental_nw_t', 'sue_rank_correlation', 'january_ic', 'admission'))
    assert json.loads((tmp_path / 'result/summary.json').read_text(encoding='utf-8'))['formal_months'] is None
