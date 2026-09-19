import copy
import json
import subprocess

import pytest

from quant.reporting.mining_status import step_snapshot


@pytest.fixture
def resumed(tmp_path):
    run = tmp_path/'batch_000011'/'2026-09-19'
    errors = {'N3': 'Worker exceeded 2473 seconds', 'N4': 'N3 did not complete',
              'N5': 'Time/disk guard: -0s, 1707.9 GiB'}
    status = {'state': 'running', 'updated_at': '2026-09-19T21:25:31', 'pid': 20}
    summary = {'session_started_at': status['updated_at'], 'finished_at': '2026-09-19T21:15:32',
               'steps': {'N1': {'ok': True}, 'N2': {'ok': True},
                         **{key: {'ok': False, 'error': value} for key, value in errors.items()}}}
    attempt = {'finished_at': '2026-09-19T21:15:32', 'error': errors}
    processes = [{'pid': 20, 'command': 'python -m quant research mining'},
                 {'pid': 21, 'command': f'python -m quant.research.nightly --worker N3 --run "{run}"'}]
    return status, summary, attempt, processes, None, run


def test_old_timeout_is_history_while_its_worker_retries(resumed):
    original = copy.deepcopy(resumed)
    result = step_snapshot(*resumed)
    assert result['steps']['N3']['label'] == '正在续跑'
    assert result['steps']['N3']['error_scope'] == 'previous_attempt'
    assert result['steps']['N4']['label'] == '等待 N3 完成'
    assert result['steps']['N5']['code'] == 'unknown'
    assert result['current_errors'] == {}
    assert result['unconfirmed_errors'] == {'N5': resumed[2]['error']['N5']}
    assert result['previous_attempt']['errors'] == resumed[2]['error']
    assert resumed == original


def test_new_failure_during_a_retry_is_not_hidden_by_history(resumed):
    resumed[1]['steps']['N5']['error'] = 'N5 exit=1; see process.log'
    result = step_snapshot(*resumed)
    assert result['steps']['N5']['code'] == 'failed'
    assert result['current_errors'] == {'N5': 'N5 exit=1; see process.log'}
    assert result['previous_attempt']['errors']['N5'].startswith('Time/disk guard')


def test_identical_failure_is_current_when_new_slice_has_finished(resumed):
    resumed[0].update(state='needs_attention', updated_at='2026-09-19T23:25:32')
    resumed[1]['finished_at'] = '2026-09-19T23:25:32'
    resumed[2]['finished_at'] = '2026-09-19T23:25:32'
    resumed[3].clear()
    result = step_snapshot(*resumed)
    assert result['steps']['N3']['code'] == 'failed'
    assert result['current_errors'] == resumed[2]['error']
    assert result['previous_attempt'] is None


def test_normal_slice_expiry_is_waiting_not_fault(resumed):
    resumed[0].update(state='resumable', updated_at='2026-09-19T23:25:32')
    resumed[1]['finished_at'] = '2026-09-19T23:25:32'
    resumed[2]['finished_at'] = '2026-09-19T23:25:32'
    resumed[3].clear()
    result = step_snapshot(*resumed)
    assert result['steps']['N3']['label'] == '等待下个时间片'
    assert result['steps']['N3']['code'] == 'waiting'


@pytest.mark.parametrize('mode', ['other_run', 'missing', 'process_error'])
def test_missing_or_unrelated_process_does_not_prove_a_retry(resumed, mode):
    args = list(resumed)
    if mode == 'other_run':
        args[3][1]['command'] = f'python -m quant.research.nightly --worker N3 --run "{args[5]}-other"'
    elif mode == 'missing':
        args[3].clear()
    else:
        args[4] = 'TimeoutExpired'
    result = step_snapshot(*args)
    assert result['steps']['N3']['code'] == 'unknown'
    assert result['steps']['N3']['error_scope'] == 'unconfirmed'
    assert result['unconfirmed_errors'] == resumed[2]['error']


def test_no_attempt_evidence_does_not_silently_demote_an_error(resumed):
    resumed[2].clear()
    result = step_snapshot(*resumed)
    assert result['steps']['N3']['code'] == 'running'
    assert result['current_errors']['N3'].startswith('Worker exceeded')
    assert result['previous_attempt'] is None


def test_status_start_before_summary_rewrite_is_unconfirmed(resumed):
    resumed[1]['session_started_at'] = '2026-09-19T19:15:00'
    resumed[3].clear()
    result = step_snapshot(*resumed)
    assert result['steps']['N3']['code'] == 'unknown'
    assert result['current_errors'] == {}


def test_runner_failure_without_step_row_remains_visible(resumed):
    resumed[0].update(state='cooldown', error={'runner': 'ValueError: broken inputs'})
    result = step_snapshot(*resumed)
    assert result['current_errors']['runner'] == 'ValueError: broken inputs'


def test_snapshot_returns_views_and_preserves_original_steps(tmp_path, monkeypatch, resumed):
    from quant.reporting import mining_status, research_dashboard
    status, summary, attempt, processes, _, run = resumed
    root = tmp_path/'artifacts/research/continuous'
    run = root/run.parent.name/run.name
    run.mkdir(parents=True)
    status['run'] = str(run)
    processes[1]['command'] = f'python -m quant.research.nightly --worker N3 --run "{run}"'
    for path, value in [(root/'status.json', status), (run/'summary.json', summary),
                        (run.parent/'attempt.json', attempt)]:
        path.write_text(json.dumps(value), encoding='utf-8')

    def command(args, **kwargs):
        stdout = json.dumps(processes) if args[0] == 'powershell.exe' else 'Unavailable'
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, 'run', command)
    monkeypatch.setattr(mining_status, 'schedule_snapshot', lambda: {})
    result = research_dashboard.snapshot(tmp_path)
    assert result['status']['steps'] == summary['steps']
    assert result['mining']['steps']['N3']['label'] == '正在续跑'
    assert result['mining']['current_errors'] == {}
