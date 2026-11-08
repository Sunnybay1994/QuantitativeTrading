import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import structured_incremental as module
from quant.reporting.structured_freshness import build_status, render_lines
from tests.unit.test_structured_incremental import setup, Client, NOW, forecast


def test_zero_event_is_fresh_checked_while_absent_daily_is_visible(tmp_path):
    args, _ = setup(tmp_path, ['forecast', 'margin_detail'])
    module.run(**args, connector=Client(lambda *a: pl.DataFrame()))
    status = build_status(data_root=tmp_path, config=args['config'], as_of=args['as_of'], now=NOW)
    rows = {r['table']: r for r in status['tables']}
    assert rows['forecast']['status'] == 'checked_empty'
    assert rows['forecast']['checked_through'] == '2026-11-07'
    assert rows['margin_detail']['status'] == 'missing_daily_rows'
    assert len(render_lines(status)) == 2
    assert status['five_real_trading_days_verified'] is False


def test_shanghai_doctor_clock_matches_utc_for_real_nonempty_snapshot(tmp_path):
    args, _ = setup(tmp_path)
    module.run(**args,connector=Client(lambda *a:forecast()))
    utc=build_status(data_root=tmp_path,config=args['config'],as_of=args['as_of'],now=NOW)
    local=build_status(data_root=tmp_path,config=args['config'],as_of=args['as_of'],
        now=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))))
    assert local==utc
    from quant.data.structured_availability import read_versions
    first=read_versions(data_root=tmp_path,table='forecast',known_at=NOW)
    second=read_versions(data_root=tmp_path,table='forecast',
        known_at=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))))
    assert first.equals(second)


def test_failed_latest_attempt_cannot_be_hidden_by_old_published_check(tmp_path):
    args, _ = setup(tmp_path)
    module.run(**args, connector=Client(lambda *a: forecast()))
    receipts = tmp_path/'receipts/x'
    receipts.mkdir(parents=True)
    (receipts/'summary.json').write_text(json.dumps({'observed_at': NOW.isoformat(),
        'tables': {'forecast': {'status': 'error', 'error_type': 'RuntimeError'}}}))
    rows = build_status(data_root=tmp_path, config=args['config'], as_of=args['as_of'],
                        now=NOW, receipt_root=receipts.parent)['tables']
    assert rows[0]['status'] == 'error'
    assert rows[0]['last_attempt_status'] == 'error'
    assert rows[0]['checked_through'] == '2026-11-07'


def test_repeated_native_rows_do_not_inflate_day_count(tmp_path):
    args, _ = setup(tmp_path)
    args['as_of'] = dt.date(2026, 11, 6)
    for name in ('one', 'two'):
        args['output'] = tmp_path/name
        module.run(**args, connector=Client(lambda *a: forecast('20261106')))
    report = build_status(data_root=tmp_path, config=args['config'],
        as_of=dt.date(2026, 11, 6), now=max(NOW, dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1)))['tables'][0]
    assert report['rows_on_as_of'] == 1


def test_native_date_whitespace_is_not_a_freshness_failure(tmp_path):
    args, _ = setup(tmp_path)
    module.run(**args, connector=Client(lambda *a: forecast()))
    p = tmp_path/'clean/forecast/snapshot=d2_run1/data.parquet'
    pl.read_parquet(p).with_columns((pl.col('ann_date')+' ').alias('ann_date')).write_parquet(p)
    report = build_status(data_root=tmp_path, config=args['config'], as_of=args['as_of'],
                          now=max(NOW, dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1)))
    assert report['tables'][0]['latest_date'] == '2026-11-07'


def test_cached_pages_cannot_fake_five_real_collection_days(tmp_path):
    args, _ = setup(tmp_path)
    folder = tmp_path/'receipts'
    for i, day in enumerate(range(2, 7)):
        path = folder/str(i)
        path.mkdir(parents=True)
        stamp = f'2026-11-{day:02}T10:00:00+00:00'
        record = {'finished_at': stamp, 'tables': {'forecast': {'status': 'captured',
            'requests': {'page': {'observed_at': '2026-11-02T09:00:00+00:00'}}}}}
        (path/'summary.json').write_text(json.dumps(record))
    def report():
        return build_status(data_root=tmp_path, config=args['config'],
            as_of=dt.date(2026, 11, 6), now=NOW, receipt_root=folder)
    assert report()['five_real_trading_days_verified'] is False
    for p in folder.glob('*/summary.json'):
        record = json.loads(p.read_text())
        record['tables']['forecast']['requests']['page']['observed_at'] = record['finished_at']
        p.write_text(json.dumps(record))
    assert report()['five_real_trading_days_verified'] is True


def test_trial_query_days_are_audited_without_passing_coverage_gate(tmp_path):
    args, _ = setup(tmp_path, ['report_rc'])
    folder = tmp_path/'receipts'
    for day in range(2, 7):
        path = folder/str(day)
        path.mkdir(parents=True)
        stamp = f'2026-11-{day:02}T10:00:00+00:00'
        (path/'summary.json').write_text(json.dumps({'finished_at': stamp,
            'tables': {'report_rc': {'status': 'permission_limited', 'published': 'immutable_snapshot',
                'requests': {'page': {'observed_at': stamp}}}}}))
    report = build_status(data_root=tmp_path, config=args['config'],
        as_of=dt.date(2026, 11, 6), now=NOW, receipt_root=folder)
    row = report['tables'][0]
    assert row['status'] == 'permission_limited'
    assert row['consecutive_real_query_trading_days'] == 5
    assert row['consecutive_real_checked_trading_days'] == 0
    assert row['last_successful_query_at'] == '2026-11-06T10:00:00+00:00'
    assert not row['query_audit_proves_full_coverage']
    assert not report['five_real_trading_days_verified']


@pytest.mark.parametrize('status,published', [('partial_budget', True), ('permission_limited', False), ('error', False)])
def test_unfinished_trial_queries_do_not_count_as_completed_days(tmp_path, status, published):
    args, _ = setup(tmp_path, ['report_rc'])
    path = tmp_path/'receipts/one'
    path.mkdir(parents=True)
    stamp = '2026-11-06T10:00:00+00:00'
    (path/'summary.json').write_text(json.dumps({'finished_at': stamp,
        'tables': {'report_rc': {'status': status, 'published': published,
            'requests': {'page': {'observed_at': stamp}}}}}))
    row = build_status(data_root=tmp_path, config=args['config'], as_of=dt.date(2026, 11, 6),
        now=NOW, receipt_root=path.parent)['tables'][0]
    assert row['consecutive_real_query_trading_days'] == 0
    assert row['last_successful_query_at'] is None


def test_trial_seed_pages_do_not_count_as_current_query_day(tmp_path):
    args, _ = setup(tmp_path, ['report_rc'])
    path = tmp_path/'receipts/seeded'
    path.mkdir(parents=True)
    (path/'summary.json').write_text(json.dumps({'finished_at': '2026-11-06T10:00:00+00:00',
        'tables': {'report_rc': {'status': 'permission_limited', 'published': 'immutable_snapshot',
            'requests': {'page': {'observed_at': '2026-11-02T10:00:00+00:00'}}}}}))
    row = build_status(data_root=tmp_path, config=args['config'], as_of=dt.date(2026, 11, 6),
        now=NOW, receipt_root=path.parent)['tables'][0]
    assert row['consecutive_real_query_trading_days'] == 0
    assert row['successful_query_calendar_days'] == []
    assert row['consecutive_real_checked_trading_days'] == 0
