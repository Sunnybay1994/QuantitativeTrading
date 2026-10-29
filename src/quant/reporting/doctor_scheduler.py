"""Read native Task Scheduler instance evidence; never infer product acceptance from exit zero."""

import datetime as dt
import json
import subprocess
import uuid

EVENT_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$channel = 'Microsoft-Windows-TaskScheduler/Operational'
$log = Get-WinEvent -ListLog $channel
$events = @()
if ($log.IsEnabled) {
  try {
    $events = @(Get-WinEvent -FilterHashtable @{
      LogName=$channel; Id=107,110,102,111,201; StartTime=(Get-Date).AddDays(-16)
    } -MaxEvents 20001 -ErrorAction Stop)
  } catch {
    if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { throw }
  }
}
$rows = @(foreach ($event in $events) {
  $xml = [xml]$event.ToXml()
  $data = @{}
  foreach ($node in $xml.Event.EventData.Data) {
    $data[$node.GetAttribute('Name')] = $node.InnerText
  }
  $task = [string]$data.TaskName
  if ($task.Split('\')[-1] -notlike 'Quant*') { continue }
  $instance = $data.InstanceId
  if (-not $instance) { $instance = $data.TaskInstanceId }
  [pscustomobject]@{
    record_id=[long]$event.RecordId; event_id=[int]$event.Id
    occurred_at=$event.TimeCreated.ToUniversalTime().ToString('o')
    task=$task; instance_id=$instance; result=$data.ResultCode; action=$data.ActionName
  }
})
[pscustomobject]@{
  enabled=[bool]$log.IsEnabled; truncated=($events.Count -gt 20000)
  window_days=16; events=$rows
} | ConvertTo-Json -Depth 6 -Compress
'''


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
        completed = subprocess.run(['powershell', '-NoProfile', '-Command', EVENT_SCRIPT],
                                   check=False, capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=90)
        if completed.returncode:
            raise RuntimeError((completed.stderr or 'Task Scheduler event query failed')[:400])
        data = json.loads(completed.stdout)
        if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
            raise ValueError('Invalid Task Scheduler query response')
        if not isinstance(data.get('events'), list):
            raise TypeError('Task Scheduler events must be a list')
        data['instances'] = normalize_events(data['events'])
        data.update(error=None, artifact_validation='not_evaluated')
        return data
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        return {'enabled': None, 'events': [], 'instances': [], 'error': str(exc)[:400],
                'artifact_validation': 'not_evaluated'}
