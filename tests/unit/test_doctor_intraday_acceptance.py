import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quant.reporting import doctor_intraday_acceptance as acceptance

NOW = dt.datetime(2026, 11, 6, 18, tzinfo=ZoneInfo('Asia/Shanghai'))
ASIA = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06']
US = ['2026-10-30', '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05']


@pytest.fixture
def tree(tmp_path):
    dates = pl.date_range(dt.date(2026, 9, 1), dt.date(2026, 11, 30), eager=True)
    frame = pl.DataFrame({'date': dates}).with_columns(
        (pl.col('date').dt.weekday() <= 5).alias('is_open'),
        pl.lit(False).alias('is_half_day'))
    for market in ('SH', 'SZ', 'HK'):
        path = tmp_path/f'data/clean/trade_calendar/market={market}/data.parquet'
        path.parent.mkdir(parents=True)
        frame.write_parquet(path)
    config = tmp_path/'configs/data/us_sessions.toml'
    config.parent.mkdir(parents=True)
    config.write_bytes(Path('configs/data/us_sessions.toml').read_bytes())
    return tmp_path


def row(market, day):
    complete = 95 if market == 'cn' else 90
    return dict(date=day, market=market, expected=100, complete=complete, partial=0,
                missing=100-complete, complete_rate=complete/100,
                denominator_verified=True, denominator_basis='pre_collection_pool')


def rows():
    return [row(market, day) for market in ('cn', 'hk', 'us')
            for day in (US if market == 'us' else ASIA)]


def test_exact_five_completed_sessions_with_counts_at_threshold_pass(tree):
    value = acceptance.evaluate(tree, rows(), NOW)
    assert value['scheduled_review_date'] == '2026-11-06'
    assert value['review_date_reached'] and value['coverage_passed'] and value['criteria_met']
    for market in ('cn', 'hk', 'us'):
        actual = value['markets'][market]
        assert actual['passed_sessions'] == 5
        assert [item['date'] for item in actual['sessions']] == (US if market == 'us' else ASIA)
    assert 'Natural scheduler receipts and commit are separately required.' in acceptance.markdown(value)


@pytest.mark.parametrize('fault,reason', [
    ('missing', 'missing_coverage'), ('duplicate', 'duplicate_coverage'),
    ('legacy', 'full_universe_unverified'), ('wrong_basis', 'full_universe_unverified'),
    ('rate', 'rate_does_not_match_counts'), ('nan', 'rate_does_not_match_counts'),
    ('sum', 'unreconciled_counts'), ('bool', 'invalid_counts'),
    ('below', 'below_threshold'),
])
def test_every_session_must_reconcile_and_pass_not_average_or_count_rows(tree, fault, reason):
    data = rows()
    target = data[2]
    if fault == 'missing':
        data.remove(target)
        data.append(row('cn', '2026-10-30'))  # Five rows still do not fill Nov 4.
    elif fault == 'duplicate':
        data.append(dict(target))
    elif fault == 'legacy':
        target['denominator_verified'] = False
    elif fault == 'wrong_basis':
        target['denominator_basis'] = 'receipts_only'
    elif fault == 'rate':
        target['complete_rate'] = 1.0
    elif fault == 'nan':
        target['complete_rate'] = float('nan')
    elif fault == 'sum':
        target['missing'] = 0
    elif fault == 'bool':
        target['expected'] = True
    elif fault == 'below':
        target.update(complete=94, missing=6, complete_rate=.94)
    value = acceptance.evaluate(tree, data, NOW)
    assert not value['criteria_met'] and not value['coverage_passed']
    assert value['markets']['cn']['sessions'][2]['reason'] == reason
    assert value['markets']['cn']['passed_sessions'] == 4


def test_five_real_completed_sessions_can_be_verified_before_original_review_date(tree):
    now = NOW-dt.timedelta(days=1)
    asia = ['2026-10-30', *ASIA[:4]]
    us = ['2026-10-29', *US[:4]]
    data = [row(market, day) for market in ('cn', 'hk', 'us')
            for day in (us if market == 'us' else asia)]
    value = acceptance.evaluate(tree, data, now)
    assert value['coverage_passed']
    assert not value['review_date_reached'] and value['criteria_met']
    assert value['observed_at']==now.isoformat()


@pytest.mark.parametrize('fault', ['absent', 'hole_duplicate', 'disagreement'])
def test_calendar_failures_are_explicit_no_weekday_or_old_date_fallback(tree, fault):
    path = tree/'data/clean/trade_calendar/market=SZ/data.parquet'
    frame = pl.read_parquet(path)
    if fault == 'absent':
        path.unlink()
    elif fault == 'hole_duplicate':
        # Preserve height; a row-count-only calendar check would miss the hole.
        frame.with_columns(pl.when(pl.col('date') == dt.date(2026,11,4))
                           .then(pl.lit(dt.date(2026,11,3))).otherwise(pl.col('date'))
                           .alias('date')).write_parquet(path)
    else:
        frame.with_columns(pl.when(pl.col('date') == dt.date(2026,11,4))
                           .then(False).otherwise(pl.col('is_open')).alias('is_open')).write_parquet(path)
    value = acceptance.evaluate(tree, rows(), NOW)
    assert not value['criteria_met']
    assert value['markets']['cn']['calendar_error']
    assert not value['markets']['cn']['sessions']


def test_session_close_cutoffs_half_day_and_weekends(tree):
    morning = NOW.replace(hour=12, minute=6)
    assert acceptance._sessions(tree, 'cn', morning)[-1] == dt.date(2026,11,5)
    assert acceptance._sessions(tree, 'hk', morning)[-1] == dt.date(2026,11,5)
    path = tree/'data/clean/trade_calendar/market=HK/data.parquet'
    frame = pl.read_parquet(path).with_columns(
        (pl.col('date') == dt.date(2026,11,6)).alias('is_half_day'))
    frame.write_parquet(path)
    assert acceptance._sessions(tree, 'hk', morning)[-1] == dt.date(2026,11,6)
    assert acceptance._sessions(tree, 'cn', NOW+dt.timedelta(days=2)) == [dt.date.fromisoformat(d) for d in ASIA]


def test_us_holiday_early_close_and_settlement_cutoff(tree):
    before = dt.datetime(2026,11,28,2,4,tzinfo=ZoneInfo('Asia/Shanghai'))
    after = before+dt.timedelta(minutes=2)
    assert acceptance._sessions(tree, 'us', before)[-1] == dt.date(2026,11,25)
    assert acceptance._sessions(tree, 'us', after) == [dt.date(2026,11,d) for d in (20,23,24,25,27)]
    (tree/'configs/data/us_sessions.toml').unlink()
    value = acceptance.evaluate(tree, rows(), NOW)
    assert value['markets']['us']['calendar_error'] and not value['criteria_met']


def test_probe_dates_are_rejected_and_future_rows_cannot_replace_required_sessions(tree):
    data = [row('cn','2026-10-16_probe_settling_wrong'), row('cn','2026-11-09')]
    value = acceptance.evaluate(tree, data, NOW)
    assert len(value['rejected_rows']) == 1 and not value['criteria_met']
    assert value['markets']['cn']['passed_sessions'] == 0
    with pytest.raises(ValueError, match='aware'):
        acceptance.evaluate(tree, rows(), NOW.replace(tzinfo=None))


def test_doctor_publishes_criteria_and_red_after_gate_without_claiming_all_d1_done(tree, monkeypatch):
    from quant.reporting import doctor

    path = tree/'artifacts/post_close_k1m/coverage.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'rows': rows()}), encoding='utf-8')
    monkeypatch.setattr(doctor, '_git_facts', lambda _: {
        'git_ok': True, 'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0})
    arguments = dict(root=tree, now=NOW, tasks=[], history={'enabled':True, 'instances':[]})
    report = doctor.collect(**arguments)
    assert report['coverage']['five_sessions']['criteria_met']
    assert 'D1 five-session' in doctor.render_markdown(report)
    path.write_text(json.dumps({'rows': []}), encoding='utf-8')
    report = doctor.collect(**arguments)
    assert not report['coverage']['five_sessions']['criteria_met']
    assert 'coverage: D1 requires five verified consecutive sessions per market' in report['red']


def test_current_worklist_cannot_hide_missing_coverage_before_original_review(tree,monkeypatch):
    from quant.reporting import doctor
    docs=tree/'docs';docs.mkdir()
    (docs/'工作清单_20261102.md').write_text('Current worklist',encoding='utf-8')
    monkeypatch.setattr(doctor,'_git_facts',lambda _:{
        'git_ok':True,'dirty':0,'days_since_commit':0,'root_scratch_py':0})
    report=doctor.collect(root=tree,now=NOW-dt.timedelta(days=1),tasks=[],
        history={'enabled':True,'instances':[]})
    assert not report['coverage']['five_sessions']['criteria_met']
    assert 'coverage: D1 requires five verified consecutive sessions per market' in report['red']
