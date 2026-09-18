import datetime as dt
import json

import polars as pl
import pytest

from quant.research.mining_recovery_audit import check_nav_keys, scheduler_records


def test_file_comparison_does_not_certify_resume_and_detects_change(tmp_path):
    import hashlib
    from quant.research.mining_recovery_audit import compare_files
    p = tmp_path/'data.bin'
    p.write_bytes(b'original')
    baseline = tmp_path/'baseline.json'
    baseline.write_text(json.dumps({'files': [{'path': 'data.bin',
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mtime_ns': p.stat().st_mtime_ns}]}))
    result = compare_files(tmp_path, baseline)
    assert result['content_matches'] and result['mtime_matches']
    assert result['automatic_resume_verified'] is False
    p.write_bytes(b'changed')
    assert not compare_files(tmp_path, baseline)['content_matches']
    p.unlink()
    assert compare_files(tmp_path, baseline)['files'][0]['status'] == 'unavailable'


def test_empty_file_evidence_is_not_a_pass(tmp_path):
    from quant.research.mining_recovery_audit import compare_files
    baseline = tmp_path/'baseline.json'
    baseline.write_text('{"files": []}')
    assert not compare_files(tmp_path, baseline)['content_matches']


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
