import datetime as dt
import json
import subprocess
import re
from types import SimpleNamespace
import xml.etree.ElementTree as ET
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


def xml_events(rows):
    root = ET.Element('Events')
    ns = scheduler.EVENT_NAMESPACE
    for row in rows:
        native = ET.SubElement(root, ns+'Event')
        system = ET.SubElement(native, ns+'System')
        ET.SubElement(system, ns+'EventID').text = str(row['event_id'])
        ET.SubElement(system, ns+'EventRecordID').text = str(row['record_id'])
        ET.SubElement(system, ns+'TimeCreated', SystemTime=row['occurred_at'])
        data = ET.SubElement(native, ns+'EventData')
        values = {'TaskName': row['task'],
                  'TaskInstanceId' if row['event_id'] == 201 else 'InstanceId': row['instance_id'],
                  'ResultCode': row['result'], 'ActionName': row['action']}
        for name, value in values.items():
            if value is not None:
                ET.SubElement(data, ns+'Data', Name=name).text = str(value)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def native_query(monkeypatch, rows):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[0] == 'wevtutil' and command[1] in ('gl', 'qe')
        assert command[2] == scheduler.CHANNEL and 0 < kwargs['timeout'] <= 90
        payload = (f'<channel name="{scheduler.CHANNEL}" enabled="true"/>'.encode()
                   if command[1] == 'gl' else xml_events(rows))
        return subprocess.CompletedProcess(command, 0, payload, b'')

    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    return calls


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
    native_query(monkeypatch, payload['events'])
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


def test_query_keeps_full_sixteen_day_scope_and_all_five_event_types(monkeypatch):
    before = dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=16)
    calls = native_query(monkeypatch, completed())
    assert scheduler.read_history()['error'] is None
    after = dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=16)
    query = next(arg[3:] for arg in calls[1] if arg.startswith('/q:'))
    assert set(re.findall(r'EventID=(\d+)', query)) == {'107', '110', '102', '111', '201'}
    stamp = dt.datetime.fromisoformat(re.search(r"@SystemTime >= '(.*?)'", query).group(1).replace('Z', '+00:00'))
    assert before <= stamp <= after
    assert '/c:20001' in calls[1] and '/rd:true' in calls[1] and '/e:Events' in calls[1]
    assert 'TaskName' not in query and 'EventRecordID' not in query


@pytest.mark.parametrize('count', [20000, 20001])
def test_truncation_counts_other_tasks_before_quant_filter(monkeypatch, count):
    other = dict(event(107, 999), task=r'\Other-Task')
    native_query(monkeypatch, [other]*(count-3)+completed())
    data = scheduler.read_history()
    assert data['error'] is None and len(data['events']) == 3
    assert data['truncated'] is (count == 20001)


@pytest.mark.parametrize('enabled', [True, False])
def test_empty_or_disabled_log_never_produces_success_instances(monkeypatch, enabled):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        payload = (f'<channel name="{scheduler.CHANNEL}" enabled="{str(enabled).lower()}"/>'.encode()
                   if command[1] == 'gl' else b'<Events/>')
        return subprocess.CompletedProcess(command, 0, payload, b'')

    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    data = scheduler.read_history()
    assert data['enabled'] is enabled and data['events'] == [] and data['instances'] == []
    assert data['error'] is None and len(calls) == (2 if enabled else 1)


@pytest.mark.parametrize('problem', ['denied', 'malformed_xml', 'wrong_namespace', 'bad_timestamp'])
def test_native_read_errors_remain_explicit_not_empty_success(monkeypatch, problem):
    def run(command, **kwargs):
        if command[1] == 'gl':
            return subprocess.CompletedProcess(command, 0,
                f'<channel name="{scheduler.CHANNEL}" enabled="true"/>'.encode(), b'')
        if problem == 'denied':
            return subprocess.CompletedProcess(command, 5, b'', b'fixture access denied')
        payload = xml_events(completed())
        if problem == 'malformed_xml': payload = b'<Events>'
        elif problem == 'wrong_namespace': payload = payload.replace(b'/08/events/event', b'/08/wrong')
        elif problem == 'bad_timestamp': payload = payload.replace(b'2026-10-29T12:00:01+08:00', b'not-a-date')
        return subprocess.CompletedProcess(command, 0, payload, b'')

    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    result = scheduler.read_history()
    assert result['enabled'] is None and result['error'] and result['instances'] == []
    if problem == 'denied': assert 'fixture access denied' in result['error']


def test_two_native_commands_share_one_ninety_second_budget(monkeypatch):
    ticks, budgets = iter([1000., 1080.]), []
    monkeypatch.setattr(scheduler, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))

    def run(command, **kwargs):
        budgets.append(kwargs['timeout'])
        payload = (f'<channel name="{scheduler.CHANNEL}" enabled="true"/>'.encode()
                   if command[1] == 'gl' else xml_events(completed()))
        return subprocess.CompletedProcess(command, 0, payload, b'')

    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    assert scheduler.read_history()['error'] is None
    assert budgets == [90, 10]


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_native_xml_adapter_preserves_encoded_fields_without_launching_tasks(monkeypatch, encoding):
    rows = completed()
    for row in rows:
        row['task'] = r'\Folder\QuantitativeTrading-Fixture'
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert command[:2] in (['wevtutil', 'gl'], ['wevtutil', 'qe'])
        xml = (ET.fromstring(f'<channel name="{scheduler.CHANNEL}" enabled="true"/>')
               if command[1] == 'gl' else ET.fromstring(xml_events(rows)))
        return subprocess.CompletedProcess(command, 0,
            ET.tostring(xml, encoding=encoding, xml_declaration=True), b'')

    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    data = scheduler.read_history()
    assert data['enabled'] and len(data['events']) == 3
    assert scheduler.normalize_events(data['events'])[0]['natural_zero_exit']
    assert data['events'] == rows and len(commands) == 2


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
