import datetime as dt
import json

import polars as pl
import pytest

from quant.research.mining_recovery_audit import check_nav_keys, scheduler_records


def test_scheduler_evidence_retains_sources_and_ignores_non_status_logs(tmp_path):
    record = {'batch': 'batch_1', 'run': 'saved', 'state': 'resumable', 'seed': 1,
              'updated_at': '2026-09-18T10:00:00'}
    (tmp_path/'1.log').write_text('worker output\n'+json.dumps(record)+'\n', encoding='utf-8-sig')
    (tmp_path/'2.log').write_text(json.dumps({**record, 'state': 'completed',
        'updated_at': '2026-09-18T11:00:00'}), encoding='utf-16')
    (tmp_path/'3.log').write_text('{"generation": 1}\n')
    rows = scheduler_records(tmp_path)
    assert [row['state'] for row in rows] == ['resumable', 'completed']
    assert rows[0]['source_log'].endswith('1.log')


@pytest.mark.parametrize('duplicate,expected', [(False, True), (True, False)])
def test_cross_year_duplicate_dates_are_detected(tmp_path, duplicate, expected):
    end = dt.date(2021, 1, 4)
    for year, dates in [(2020, [dt.date(2020, 12, 31)]),
                        (2021, [dt.date(2020, 12, 31), end] if duplicate else [end])]:
        folder = tmp_path/'raw/cost_1'/str(year)
        folder.mkdir(parents=True)
        pl.DataFrame({'date': dates}).write_parquet(folder/'nav.parquet')
    (tmp_path/'summary.json').write_text(json.dumps({'factor': 'a', 'rows': [
        {'variant': 'raw', 'cost_multiplier': 1, 'last_date': str(end)}]}))
    result = check_nav_keys(tmp_path)
    assert result['passed'] is expected
    assert result['scenarios'][0]['duplicate_dates'] == int(duplicate)
