import datetime as dt
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from quant.reporting import doctor
from quant.reporting import doctor_scheduler as scheduler


def event(kind, record, *, instance=1, result=None):
    return {'task': r'\QuantitativeTrading-DailyObservation',
            'instance_id': f'00000000-0000-0000-0000-{instance:012d}',
            'event_id': kind, 'record_id': record,
            'occurred_at': f'2026-10-29T12:00:{record:02d}+08:00',
            'result': result, 'action': 'powershell.exe' if kind == 201 else None}


def completed(*, trigger=107, instance=1, offset=0, code='0'):
    return [event(trigger, offset+1, instance=instance),
            event(201, offset+2, instance=instance, result=code),
            event(102, offset+3, instance=instance)]


def test_native_instance_guid_keeps_manual_and_natural_runs_separate():
    rows = completed() + completed(trigger=110, instance=2, offset=3)
    natural, manual = scheduler.normalize_events(list(reversed(rows)) + [rows[0]])
    assert natural['natural_zero_exit'] and natural['trigger'] == 'time'
    assert natural['record_ids'] == [1, 2, 3]
    assert manual['result'] == 0 and manual['trigger'] == 'manual'
    assert not manual['natural_zero_exit']


@pytest.mark.parametrize('case', ['unfinished', 'no_action', 'old_event', 'terminated', 'conflicting'])
def test_incomplete_and_ambiguous_events_never_prove_natural_success(case):
    rows = completed()
    if case == 'unfinished':
        rows.pop()
    elif case == 'no_action':
        rows.pop(1)
    elif case == 'old_event':
        rows[1]['result'] = None
    elif case == 'terminated':
        rows.append(event(111, 4))
    else:
        rows.append(event(110, 4))
    result = scheduler.normalize_events(rows)[0]
    assert not result['natural_zero_exit']
    if case != 'conflicting':
        assert result['result'] is None


def test_any_nonzero_action_code_remains_failure_even_if_last_action_succeeds():
    rows = completed(code='0xFFFFFFFF')
    rows.append(event(201, 4, result=0))
    result = scheduler.normalize_events(rows)[0]
    assert result['result'] == 4294967295
    assert not result['natural_zero_exit']


def test_conflicting_duplicate_record_rejects_history():
    rows = completed()
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        scheduler.normalize_events(rows + [{**rows[1], 'result': '1'}])


@pytest.mark.parametrize('value', [True, 'not-a-code'])
def test_invalid_exit_code_cannot_be_interpreted_as_zero(value):
    with pytest.raises(ValueError):
        scheduler.normalize_events(completed(code=value))


def test_reader_keeps_native_rows_and_marks_products_unverified(monkeypatch):
    payload = {'enabled': True, 'truncated': False, 'events': completed()}
    monkeypatch.setattr(scheduler.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, json.dumps(payload), ''))
    result = scheduler.read_history()
    assert result['events'] == payload['events']
    assert result['instances'][0]['natural_zero_exit']
    assert result['artifact_validation'] == 'not_evaluated'


def test_query_timeout_is_explicit_missing_evidence(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('powershell', 90)
    monkeypatch.setattr(scheduler.subprocess, 'run', timeout)
    result = scheduler.read_history()
    assert result['enabled'] is None and result['error']
    assert result['instances'] == []


@pytest.mark.skipif(sys.platform != 'win32', reason='Native PowerShell XML adapter')
def test_native_powershell_adapter_reads_event_xml_without_launching_tasks():
    # Shadow the read-only event source inside this process; use the real query/adapter.
    source = r'''
function Get-WinEvent {
  param($ListLog, $FilterHashtable, $MaxEvents)
  if ($ListLog) { return [pscustomobject]@{IsEnabled=$true} }
  $record = 0
  foreach ($id in 107,201,102) {
    $record++
    $field = if ($id -eq 201) { 'TaskInstanceId' } else { 'InstanceId' }
    $code = if ($id -eq 201) { '<Data Name="ResultCode">0</Data>' } else { '' }
    $xml = '<Event><EventData><Data Name="TaskName">\Folder\QuantitativeTrading-Fixture</Data>' +
           '<Data Name="'+$field+'">{00000000-0000-0000-0000-000000000001}</Data>' + $code + '</EventData></Event>'
    $row = [pscustomobject]@{RecordId=$record;Id=$id;TimeCreated=(Get-Date);Payload=$xml}
    $row | Add-Member -MemberType ScriptMethod -Name ToXml -Value {$this.Payload}
    $row
  }
}
'''
    result = subprocess.run(['powershell', '-NoProfile', '-Command', source + scheduler.EVENT_SCRIPT],
                            check=True, capture_output=True, text=True, encoding='utf-8', timeout=30)
    data = json.loads(result.stdout)
    assert data['enabled'] and len(data['events']) == 3
    assert scheduler.normalize_events(data['events'])[0]['natural_zero_exit']


def test_doctor_archives_each_check_and_reports_disabled_event_log(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, '_git_facts', lambda _: {
        'git_ok': True, 'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0})
    report = doctor.collect(root=tmp_path, tasks=[], history={
        'enabled': False, 'events': [], 'instances': [], 'error': None},
        now=dt.datetime(2026, 10, 29, 12, tzinfo=ZoneInfo('Asia/Shanghai')))
    assert any(r.startswith('scheduled_history:') for r in report['red'])
    destination = tmp_path / 'artifacts'
    doctor.write_report(report, destination)
    folder = destination / 'doctor/runs/2026-10-29'
    original = next(folder.glob('*.json'))
    original_bytes = original.read_bytes()
    report['scheduled_history']['enabled'] = True
    latest, _ = doctor.write_report(report, destination)
    assert len(list(folder.glob('*.json'))) == 2
    assert original.read_bytes() == original_bytes
    assert json.loads(latest.read_text())['scheduled_history']['enabled']
