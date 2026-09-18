import datetime as dt

import pytest

from quant.reporting.mining_status import ZONE, describe


def test_progress_reads_latest_complete_compute_record(tmp_path):
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(
        '{"year": 2019, "factors_written": 20, "stock_days": 800000}\n'
        '{"year": 2020, "factors_written": 20, "stock_days": 900000}\n'
        '{"year":2021', encoding='utf-8')
    result = progress_snapshot(tmp_path)
    assert result['compute_year'] == 2020 and result['factors_written'] == 20
    assert result['source'] == 'N3/process.log'


def test_log_noise_does_not_claim_computation_progress(tmp_path):
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(
        '{"year": 2020, "factors_written": 0, "stock_days": 100}\n[]\nwarning\n', encoding='utf-8')
    assert progress_snapshot(tmp_path) == {}

NOW = dt.datetime(2026, 9, 18, 12, tzinfo=ZONE)


def test_statistics_progress_supersedes_computation_and_ignores_partial_line(tmp_path):
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(
        '{"year":2026,"factors_written":20,"stock_days":800000}\n'
        '{"factor":"candidate_a","completed":2,"seconds":60}\n'
        '{"factor":"unfinished"', encoding='utf-8')
    result = progress_snapshot(tmp_path)
    assert result['statistics_completed'] == 2
    assert result['statistics_factor'] == 'candidate_a'
    assert result['compute_year'] is None


def test_cost_progress_supersedes_statistics(tmp_path):
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(
        '{"factor":"a","completed":20}\n'
        '{"factor":"stock_benchmarks","year":2015,"variant":"all_market_equal_weight",'
        '"multiplier":2.0,"sessions":244}\n', encoding='utf-8')
    result = progress_snapshot(tmp_path)
    assert result['replay_year'] == 2015
    assert result['replay_cost'] == 2.0
    assert result['replay_variant'] == 'all_market_equal_weight'
    assert result['statistics_completed'] is None


@pytest.mark.parametrize('cost,sessions', [(True, 244), (3, 244), (1, 0)])
def test_invalid_cost_progress_is_ignored(tmp_path, cost, sessions):
    import json
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(json.dumps({
        'factor': 'a', 'year': 2025, 'variant': 'raw', 'multiplier': cost,
        'sessions': sessions})+'\n', encoding='utf-8')
    assert progress_snapshot(tmp_path) == {}


@pytest.mark.parametrize('record', [
    '{"factor":"a","completed":true}',
    '{"factor":"","completed":2}',
    '{"factor":"a","completed":0}',
])
def test_invalid_statistics_record_is_not_progress(tmp_path, record):
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(record+'\n', encoding='utf-8')
    assert progress_snapshot(tmp_path) == {}


@pytest.mark.parametrize('total', [19, 0, True])
def test_correlation_progress_is_not_factor_statistics(tmp_path, total):
    import json
    from quant.reporting.mining_status import progress_snapshot
    (tmp_path/'N3').mkdir()
    (tmp_path/'N3/process.log').write_text(json.dumps({
        'factor': 'a', 'completed': 12, 'total': total})+'\n', encoding='utf-8')
    result = progress_snapshot(tmp_path)
    if total == 19:
        assert result['correlations_completed'] == 12
        assert result['correlations_total'] == 19
        assert result['statistics_completed'] is None
    else:
        assert result == {}


def view(state='running', processes=None, scheduler=None, error=None, **status):
    return describe({'state': state, 'updated_at': '2026-09-18T11:00:00', **status},
                    scheduler or {}, processes or [], error,
                    {'state': 'Ready', 'next_trigger': '2026-09-18T12:05:00+08:00'}, now=NOW)


def test_failed_process_collection_is_unknown_not_stopped():
    assert view(error='TimeoutExpired')['code'] == 'unknown'


def test_daily_process_does_not_masquerade_as_live_mining():
    assert view(processes=[{'command': 'python -m quant research daily'}])['code'] == 'interrupted'
    assert view(processes=[{'command': 'python -m quant research mining'}])['code'] == 'running'


@pytest.mark.parametrize('state,code', [('resumable', 'slice_wait'), ('completed', 'batch_wait'),
                                       ('needs_attention', 'failed'), ('running', 'interrupted')])
def test_saved_states_do_not_claim_a_live_process(state, code):
    assert view(state)['code'] == code


def test_future_retry_and_timezone_are_kept_separate_from_scheduler_trigger():
    result = view('cooldown', retry_after='2026-09-18T13:00:00')
    assert result['code'] == 'cooldown'
    assert result['retry_after'] == '2026-09-18T13:00:00+08:00'
    assert result['next_trigger'] == '2026-09-18T12:05:00+08:00'


@pytest.mark.parametrize('reason,code', [('Reserved for daily observation', 'daily_wait'),
    ('Another data/factor/account writer is running', 'writer_wait')])
def test_only_newer_defer_records_override_saved_idle_state(reason, code):
    scheduler = {'status': 'deferred', 'reason': reason, 'updated_at': '2026-09-18T11:30:00+08:00'}
    assert view('resumable', scheduler=scheduler)['code'] == code
    scheduler['updated_at'] = '2026-09-18T10:30:00+08:00'
    assert view('resumable', scheduler=scheduler)['code'] == 'slice_wait'


def test_disabled_or_stale_schedule_does_not_promise_restart():
    for schedule in [{'state': 'Disabled', 'next_trigger': '2026-09-18T12:05:00'},
                     {'state': 'Ready', 'next_trigger': '2026-09-17T12:05:00'},
                     {'error': 'TimeoutExpired'}]:
        assert describe({}, {}, [], None, schedule, now=NOW)['next_trigger'] is None
