import datetime as dt

import pytest

from quant.reporting.mining_status import ZONE, describe

NOW = dt.datetime(2026, 9, 18, 12, tzinfo=ZONE)


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
