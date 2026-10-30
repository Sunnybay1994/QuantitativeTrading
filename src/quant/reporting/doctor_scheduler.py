"""Read native Task Scheduler instance evidence; never infer product acceptance from exit zero."""

import datetime as dt
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

CHANNEL = 'Microsoft-Windows-TaskScheduler/Operational'
EVENT_NAMESPACE = '{http://schemas.microsoft.com/win/2004/08/events/event}'


def _native_xml(arguments: list[str], timeout: float) -> ET.Element:
    completed = subprocess.run(['wevtutil', *arguments], check=False, capture_output=True,
                               timeout=timeout)
    if completed.returncode:
        error = completed.stderr or b'Native Task Scheduler query failed'
        if isinstance(error, bytes):
            error = error.decode('utf-8', errors='replace')
        raise RuntimeError(error[:400])
    # Parse bytes directly: native XML declarations/BOMs identify UTF-8/UTF-16.
    return ET.fromstring(completed.stdout)


def _native_events(document: ET.Element) -> tuple[list[dict], int]:
    if document.tag != 'Events':
        raise ValueError('Invalid native event query root')
    rows = []
    for event in document:
        if event.tag != EVENT_NAMESPACE+'Event':
            raise ValueError('Invalid native event namespace')
        data = {node.get('Name'): node.text
                for node in event.findall(EVENT_NAMESPACE+'EventData/'+EVENT_NAMESPACE+'Data')}
        task = data.get('TaskName') or ''
        if not task.rsplit('\\', 1)[-1].lower().startswith('quant'):
            continue
        system = event.find(EVENT_NAMESPACE+'System')
        if system is None:
            raise ValueError('Missing native event System fields')
        created = system.find(EVENT_NAMESPACE+'TimeCreated')
        if created is None or not created.get('SystemTime'):
            raise ValueError('Missing native event timestamp')
        rows.append({
            'record_id': int(system.findtext(EVENT_NAMESPACE+'EventRecordID')),
            'event_id': int(system.findtext(EVENT_NAMESPACE+'EventID')),
            'occurred_at': created.get('SystemTime'), 'task': task,
            'instance_id': data.get('InstanceId') or data.get('TaskInstanceId'),
            'result': data.get('ResultCode'), 'action': data.get('ActionName'),
        })
    return rows, len(document)


def normalize_events(events: list[dict]) -> list[dict]:
    """Join trigger, completion and action results by native GUID, not time proximity."""
    groups, seen = {}, {}
    for event in events:
        task = str(event['task']).lstrip('\\')
        if not task.rsplit('\\', 1)[-1].lower().startswith('quant'):
            continue
        instance = str(uuid.UUID(event['instance_id']))
        kind, record = int(event['event_id']), int(event['record_id'])
        if kind not in (107, 110, 102, 111, 201):
            continue
        stamp = dt.datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Scheduler event timestamp must include a timezone')
        result = event.get('result')
        if result is not None:
            if isinstance(result, bool):
                raise ValueError('Boolean scheduler return code is invalid')
            result = int(str(result), 16 if str(result).lower().startswith('0x') else 10)
        row = {'record_id': record, 'event_id': kind, 'occurred_at': stamp.isoformat(),
               'result': result, 'action': event.get('action')}
        key = (task, instance, record)
        if key in seen:
            if seen[key] != row:
                raise ValueError('Conflicting duplicate Task Scheduler record')
            continue
        seen[key] = row
        groups.setdefault((task, instance), []).append(row)
    instances = []
    for (task, instance), rows in groups.items():
        rows.sort(key=lambda r: (dt.datetime.fromisoformat(r['occurred_at']), r['record_id']))
        triggers = [r for r in rows if r['event_id'] in (107, 110)]
        sources = {r['event_id'] for r in triggers}
        trigger = {frozenset({107}): 'time', frozenset({110}): 'manual'}.get(
            frozenset(sources), 'conflicting' if sources else 'unknown')
        finished = [r for r in rows if r['event_id'] == 102]
        terminated = [r for r in rows if r['event_id'] == 111]
        actions = [r for r in rows if r['event_id'] == 201]
        codes = [r['result'] for r in actions]
        result = None
        if finished and actions and None not in codes and not terminated:
            result = next((code for code in codes if code != 0), 0)
        instances.append({
            'task': task, 'instance_id': instance, 'trigger': trigger,
            'start_time': triggers[0]['occurred_at'] if triggers else None,
            'last_event_time': rows[-1]['occurred_at'],
            'status': 'terminated' if terminated else 'finished' if finished else 'no_completion_event',
            'action_results': codes, 'result': result,
            'natural_zero_exit': trigger == 'time' and result == 0,
            'record_ids': [r['record_id'] for r in rows],
        })
    return sorted(instances, key=lambda r: (
        dt.datetime.fromisoformat(r['start_time'] or r['last_event_time']), r['instance_id']))


def read_history() -> dict:
    try:
        clock = time.monotonic()
        config = _native_xml(['gl', CHANNEL, '/f:xml'], timeout=90)
        enabled = config.get('enabled')
        if (config.tag.rsplit('}', 1)[-1] != 'channel' or config.get('name') != CHANNEL
                or enabled not in ('true', 'false')):
            raise ValueError('Invalid native event channel configuration')
        data = {'enabled': enabled == 'true', 'truncated': False, 'window_days': 16,
                'events': [], 'reader': 'wevtutil'}
        if data['enabled']:
            start = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=16)).isoformat().replace('+00:00', 'Z')
            query = ("*[System[(EventID=107 or EventID=110 or EventID=102 or EventID=111 "
                     f"or EventID=201) and TimeCreated[@SystemTime >= '{start}']]]")
            remaining = 90-(time.monotonic()-clock)
            if remaining <= 0:
                raise subprocess.TimeoutExpired('native event history', 90)
            document = _native_xml(['qe', CHANNEL, '/q:'+query, '/rd:true', '/c:20001',
                                    '/f:xml', '/e:Events'], timeout=remaining)
            data['events'], count = _native_events(document)
            data['truncated'] = count > 20000
        data['instances'] = normalize_events(data['events'])
        data.update(error=None, artifact_validation='not_evaluated')
        return data
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, ET.ParseError, subprocess.TimeoutExpired) as exc:
        return {'enabled': None, 'events': [], 'instances': [], 'error': str(exc)[:400],
                'artifact_validation': 'not_evaluated'}
