import datetime as dt

import polars as pl
import pytest

from quant.research.monthly_sue import build_monthly_sue
from quant.research.monthly_sue_context_v2 import NAME, build_monthly_sue_context_v2
from tests.unit.test_earnings_surprise import income

SYMBOL = '000001.SZ'


def history():
    return income([float(i * i + 5 * (i % 4)) for i in range(16)])


def added_report(frame, *, period=None, available=None, comp_type='4', update='0'):
    available = available or frame['available_date'][-1] + dt.timedelta(days=10)
    return frame.tail(1).with_columns(
        pl.lit(period or frame['end_date'][-1] + dt.timedelta(days=91)).alias('end_date'),
        pl.lit(available).alias('ann_date'), pl.lit(available).alias('f_ann_date'),
        pl.lit(available).alias('available_date'), pl.lit(comp_type, dtype=pl.String).alias('comp_type'),
        pl.lit(update).alias('update_flag'))


def evaluate(frame, date=None, candidates=(SYMBOL,)):
    return build_monthly_sue_context_v2(income_history=frame,
        signal_dates=(date or frame['available_date'].max() + dt.timedelta(days=1),),
        candidate_symbols=candidates)


def test_unmodified_industrial_history_matches_original_values_and_quarantine_exactly():
    frame = history()
    dates = (frame['available_date'][-2] + dt.timedelta(days=1),
             frame['available_date'][-1] + dt.timedelta(days=1))
    old = build_monthly_sue(income_history=frame, signal_dates=dates, candidate_symbols=(SYMBOL, '000002.SZ'))
    new = build_monthly_sue_context_v2(income_history=frame, signal_dates=dates, candidate_symbols=(SYMBOL, '000002.SZ'))
    assert new.factors.rename({NAME: 'pit_sue8'}).select(old.factors.columns).equals(old.factors)
    assert new.quarantined.equals(old.quarantined)
    valid = new.eligibility.filter(pl.col('symbol') == SYMBOL)
    assert valid['status'].to_list() == ['VALID', 'VALID']
    assert valid['period_matches_context'].all()
    assert not valid['suppressed_legacy_value'].any()


def test_industrial_to_security_blocks_old_anchor_and_keeps_latest_report_diagnostics():
    frame = history()
    later = added_report(frame, period=dt.date(2024, 3, 31), available=dt.date(2024, 4, 20))
    combined = pl.concat([frame, later])
    date = dt.date(2024, 4, 21)
    old = build_monthly_sue(income_history=combined, signal_dates=(date,), candidate_symbols=(SYMBOL,))
    new = evaluate(combined, date)
    assert old.factors['pit_sue8'][0] is not None
    assert new.factors[NAME][0] is None
    row = new.eligibility.row(0, named=True)
    assert row['status'] == 'CONTEXT_NON_INDUSTRIAL'
    assert row['latest_report_end'] == dt.date(2024, 3, 31)
    assert row['latest_comp_type'] == '4' and row['suppressed_legacy_value']
    assert row['financial_period_end'] == dt.date(2023, 12, 31)
    assert new.quarantined.equals(old.quarantined)


def test_same_period_type_correction_is_invisible_on_announcement_day():
    frame = history()
    correction_date = frame['available_date'][-1] + dt.timedelta(days=10)
    revised = added_report(frame, period=frame['end_date'][-1], available=correction_date, update='1')
    combined = pl.concat([frame, revised])
    new = build_monthly_sue_context_v2(income_history=combined,
        signal_dates=(correction_date, correction_date + dt.timedelta(days=1)), candidate_symbols=(SYMBOL,))
    assert new.factors[NAME][0] is not None and new.factors[NAME][1] is None
    assert new.eligibility['report_context'].to_list() == ['industrial', 'non_industrial']
    assert new.eligibility['latest_available_date'][1] == correction_date


def test_late_old_quarter_does_not_override_newer_period_context():
    frame = history()
    latest = added_report(frame, period=dt.date(2024, 3, 31), available=dt.date(2024, 4, 20))
    old_revision = added_report(frame, period=dt.date(2023, 9, 30),
        available=dt.date(2024, 5, 20), comp_type='1', update='1')
    new = evaluate(pl.concat([frame, latest, old_revision]))
    assert new.factors[NAME][0] is None
    assert new.eligibility['latest_report_end'][0] == dt.date(2024, 3, 31)
    assert new.eligibility['latest_available_date'][0] == dt.date(2024, 4, 20)


def test_update_priority_after_latest_publication_and_tied_types_stay_ambiguous():
    frame = history()
    corrected = frame.tail(1).with_columns(pl.lit('4').alias('comp_type'), pl.lit('1').alias('update_flag'))
    highest = evaluate(pl.concat([frame, corrected]))
    assert highest.eligibility['latest_comp_type'][0] == '4'
    tied = frame.tail(1).with_columns(pl.lit('1').alias('update_flag'))
    ambiguous = evaluate(pl.concat([frame, corrected, tied]))
    assert ambiguous.eligibility['status'][0] == 'CONTEXT_AMBIGUOUS'
    assert ambiguous.eligibility['latest_comp_types'][0] == '1,4'
    assert ambiguous.factors[NAME][0] is None
    later = added_report(frame, period=frame['end_date'][-1], comp_type='1')
    restored = evaluate(pl.concat([frame, corrected, later]))
    assert restored.eligibility['report_context'][0] == 'industrial'
    assert restored.eligibility['latest_available_date'][0] == later['available_date'][0]


@pytest.mark.parametrize('comp_type', [None, '9', ''])
def test_unknown_latest_type_cannot_reuse_old_industrial_value(comp_type):
    frame = history()
    latest = added_report(frame, period=frame['end_date'][-1], comp_type=comp_type)
    new = evaluate(pl.concat([frame, latest]))
    assert new.factors[NAME][0] is None
    assert new.eligibility['status'][0] == 'CONTEXT_UNKNOWN'


@pytest.mark.parametrize('field', ['n_income_attr_p', 'n_income'])
def test_economic_correction_conflict_keeps_original_quarantine_and_null(field):
    frame = history()
    conflict = frame.tail(1).with_columns(pl.lit(99999.0).alias(field))
    combined = pl.concat([frame, conflict])
    date = frame['available_date'][-1] + dt.timedelta(days=1)
    old = build_monthly_sue(income_history=combined, signal_dates=(date,), candidate_symbols=(SYMBOL,))
    new = evaluate(combined, date)
    assert new.factors[NAME][0] is None and new.eligibility['status'][0] == 'QUARANTINED'
    assert new.eligibility['legacy_status'][0] == 'QUARANTINED'
    assert new.quarantined.equals(old.quarantined)
    assert new.quarantined['quarantine_reason'].is_in(['LATEST_REVISION_CONFLICT', 'REVISION_CHAIN_CONFLICT']).any()


def test_latest_industrial_period_must_match_the_original_computed_anchor(monkeypatch):
    import quant.research.monthly_sue_context_v2 as module
    from quant.research.pit_quality_research import PITQualitySignalResult

    frame = history()
    date = frame['available_date'][-1] + dt.timedelta(days=1)
    old = build_monthly_sue(income_history=frame, signal_dates=(date,), candidate_symbols=(SYMBOL,))
    fake_old = PITQualitySignalResult(factors=old.factors.with_columns(
        pl.lit(dt.date(2023, 9, 30)).alias('financial_period_end')),
        eligibility=old.eligibility, quarantined=old.quarantined)
    monkeypatch.setattr(module, 'build_monthly_sue', lambda **_: fake_old)
    new = evaluate(frame, date)
    assert new.factors[NAME][0] is None
    assert new.eligibility['status'][0] == 'CONTEXT_PERIOD_MISMATCH'
    assert new.eligibility['latest_report_end'][0] == dt.date(2023, 12, 31)
    assert new.eligibility['reason'][0] == 'LATEST_REPORT_DIFFERS_FROM_COMPUTED_FINANCIAL_PERIOD'


def test_unannounced_and_empty_income_context_are_null_without_old_fallback():
    frame = history()
    for source in (frame, frame.clear()):
        new = evaluate(source, dt.date(2019, 12, 31))
        assert new.factors[NAME][0] is None
        assert new.eligibility['status'][0] == 'CONTEXT_NO_REPORT'
        assert new.eligibility['latest_report_end'][0] is None


@pytest.mark.parametrize('empty', ['candidates', 'signals'])
def test_empty_work_returns_typed_frames(empty):
    frame = history()
    new = build_monthly_sue_context_v2(income_history=frame,
        signal_dates=() if empty == 'signals' else (dt.date(2024, 1, 22),),
        candidate_symbols=() if empty == 'candidates' else (SYMBOL,))
    assert new.factors.is_empty() and new.eligibility.is_empty() and new.quarantined.is_empty()
    assert new.factors.schema[NAME] == pl.Float64 and new.factors.schema['trade_date'] == pl.Date


def test_latest_industrial_zero_variance_stays_null():
    new = evaluate(income([float(i) for i in range(16)]))
    assert new.factors[NAME][0] is None
    assert new.eligibility['status'][0] == 'MISSING_OR_ZERO_VARIANCE'
    assert new.eligibility['period_matches_context'][0]
