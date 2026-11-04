import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from quant.data.events_v0 import _task_spend, _record_spend
from quant.data.events_v0_budget import complete_with_budget, EventBudgetExhausted, pending, task_budget_usd
from quant.llm import RequestFailure
from quant.llm.ledger import append, month_path


def _call(root, complete, *, record=None):
    if record is None:
        def record(response, request_id, started):
            append(dict(task='event_extract', usd=response['usd'], event_request_id=request_id), root, now=started)
    return complete_with_budget(complete, [], {'max_tokens': 250}, ledger_root=root,
        announcement_id='fixture', spend=_task_spend, record=record, limit=5.)


def test_parallel_workers_cannot_all_pass_the_same_remaining_balance(tmp_path):
    append(dict(task='event_extract', usd=task_budget_usd()-.03), tmp_path)
    reached = threading.Event()
    calls, active, maximum = [], [0], [0]
    def complete(messages, settings):
        assert settings['reserve_usd'] == settings['max_usd'] == .02
        active[0] += 1; maximum[0] = max(maximum[0], active[0])
        time.sleep(.02)
        calls.append(1); active[0] -= 1
        return {'usd': .01}
    def worker():
        reached.wait()
        try:
            _call(tmp_path, complete)
            return 'charged'
        except EventBudgetExhausted:
            return 'budget'
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker) for _ in range(4)]
        reached.set()
        outcomes = [f.result(timeout=15) for f in futures]
    assert outcomes.count('charged') == len(calls) == 2
    assert maximum[0] == 1 and _task_spend(tmp_path) < task_budget_usd()
    assert pending(tmp_path) == dict(requests=0, usd=0.)


def test_unknown_transport_keeps_a_durable_reservation(tmp_path):
    append(dict(task='event_extract', usd=task_budget_usd()-.03), tmp_path)
    def unknown(*args): raise RequestFailure('transport_outcome_unknown')
    with pytest.raises(RequestFailure): _call(tmp_path, unknown)
    assert pending(tmp_path) == dict(requests=1, usd=.02)
    with pytest.raises(EventBudgetExhausted):
        _call(tmp_path, lambda *a: pytest.fail('must not send again'))
    assert _task_spend(tmp_path) == pytest.approx(task_budget_usd()-.03)


def test_proven_connection_failure_releases_reservation_for_retry(tmp_path):
    def offline(*args): raise RequestFailure('connect_failed', retryable=True)
    with pytest.raises(RequestFailure): _call(tmp_path, offline)
    assert pending(tmp_path) == dict(requests=0, usd=0.)
    _call(tmp_path, lambda *a: {'usd': .001})
    assert _task_spend(tmp_path) == .001


def test_a_failed_charge_write_cannot_make_the_request_free(tmp_path):
    def broken(*args): raise OSError('fixture ledger write failed')
    with pytest.raises(OSError):
        _call(tmp_path, lambda *a: {'usd': .001}, record=broken)
    assert pending(tmp_path) == dict(requests=1, usd=.02)


def test_response_with_unknown_price_records_a_labeled_conservative_estimate(tmp_path):
    tariff = tmp_path/'pricing.toml'
    tariff.write_text('input_usd_per_million = 0.3\noutput_usd_per_million = 1.2\n')
    _call(tmp_path, lambda *a: {}, record=lambda reply, identity, started:
        _record_spend(reply, tmp_path, tariff, 'fixture', identity, started))
    row = json.loads(month_path(tmp_path).read_text())
    assert row['usd'] == .02 and row['estimated'] and row['unknown_charge']
    assert pending(tmp_path) == dict(requests=0, usd=0.)


def test_malformed_reservation_blocks_new_requests(tmp_path):
    directory = tmp_path/'.event_extract_budget'
    directory.mkdir()
    month_path(directory).write_text('{broken\n')
    with pytest.raises(ValueError):
        _call(tmp_path, lambda *a: pytest.fail('must not send'))


def test_killed_request_process_keeps_reservation_and_releases_kernel_lock(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    append(dict(task='event_extract', usd=task_budget_usd()-.03), tmp_path)
    code = '''
import os, sys
from pathlib import Path
from quant.data.events_v0 import _task_spend
from quant.data.events_v0_budget import complete_with_budget
complete_with_budget(lambda *a: os._exit(29), [], {'max_tokens':250},
    ledger_root=Path(sys.argv[1]), announcement_id='crash_fixture',
    spend=_task_spend, record=lambda *a: None, limit=5.)
'''
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2]/'src')
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env=env,
                            capture_output=True, timeout=60)
    assert result.returncode == 29, result.stderr
    assert pending(tmp_path) == dict(requests=1, usd=.02)
    # This reaches the budget rejection, proving the dead process's lock released.
    with pytest.raises(EventBudgetExhausted):
        _call(tmp_path, lambda *a: pytest.fail('must not pay after unpriced crash'))


def test_charge_is_booked_in_the_reserved_request_month(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from quant.data import events_v0_budget as budget
    from quant.llm.ledger import SHANGHAI

    start = dt.datetime(2026, 10, 31, 23, 59, 59, tzinfo=SHANGHAI)
    end = dt.datetime(2026, 11, 1, 0, 0, 1, tzinfo=SHANGHAI)
    clock = [start]
    monkeypatch.setattr(budget, 'dt', SimpleNamespace(datetime=SimpleNamespace(now=lambda tz: clock[0])))
    append(dict(task='event_extract', usd=4.97), tmp_path, now=start)
    def complete(*args):
        clock[0] = end
        return dict(usd=.001)
    _call(tmp_path, complete)
    assert not month_path(tmp_path, now=end).exists()
    assert _task_spend(tmp_path, start) == 4.971
    assert pending(tmp_path, start) == dict(requests=0, usd=0.)
