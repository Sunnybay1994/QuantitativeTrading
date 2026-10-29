"""A denied scheduler query must survive as evidence, not an empty inventory."""

import json
import sys

import pytest

from quant.reporting import doctor


@pytest.mark.skipif(sys.platform != 'win32', reason='Native PowerShell query')
def test_native_nonterminating_query_error_is_not_an_empty_inventory(monkeypatch):
    # Shadow only the read command; no real tasks are started or modified.
    source = "function Get-ScheduledTask { Write-Error 'fixture access denied' }\n"
    monkeypatch.setattr(doctor, '_TASK_SCRIPT', source + doctor._TASK_SCRIPT)
    with pytest.raises(RuntimeError, match='fixture access denied'):
        doctor.windows_scheduled_tasks()


@pytest.mark.skipif(sys.platform != 'win32', reason='Native PowerShell query')
@pytest.mark.parametrize('code', [0, 2147946720, 4294967295])
def test_native_query_preserves_active_results_and_filters_retired_tasks(monkeypatch, code):
    source = r'''
function Get-ScheduledTask {
  [pscustomobject]@{TaskName='QuantitativeTrading-Fixture';State='Ready'}
  [pscustomobject]@{TaskName='QuantitativeTrading-Retired';State='Disabled'}
  [pscustomobject]@{TaskName='Other';State='Ready'}
}
function Get-ScheduledTaskInfo {
  param($InputObject)
  [pscustomobject]@{LastRunTime=[datetime]'2026-10-29T08:30:00';LastTaskResult=0}
}
'''
    source = source.replace('LastTaskResult=0', f'LastTaskResult=[long]{code}')
    monkeypatch.setattr(doctor, '_TASK_SCRIPT', source + doctor._TASK_SCRIPT)
    rows = doctor.windows_scheduled_tasks()
    assert len(rows) == 1
    assert rows[0]['name'] == 'QuantitativeTrading-Fixture'
    assert rows[0]['result'] == code
    assert rows[0]['last_run_time'].startswith('2026-10-29T08:30:00')


def test_failed_query_reason_survives_in_doctor_json_and_page(tmp_path, monkeypatch):
    def denied():
        raise RuntimeError('fixture access denied')

    monkeypatch.setattr(doctor, 'windows_scheduled_tasks', denied)
    monkeypatch.setattr(doctor, '_git_facts', lambda _: {
        'git_ok': True, 'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0})
    report = doctor.collect(root=tmp_path, history={
        'enabled': True, 'events': [], 'instances': [], 'error': None})
    row = report['scheduled_tasks'][0]
    assert row['name'] == 'query' and row['result'] is None and not row['ok']
    assert row['error'] == 'fixture access denied'
    assert 'scheduled_tasks: none' not in report['red']
    assert any('fixture access denied' in red for red in report['red'])
    path, page = doctor.write_report(report, tmp_path/'artifacts')
    assert json.loads(path.read_text(encoding='utf-8'))['scheduled_tasks'][0] == row
    assert 'fixture access denied' in page.read_text(encoding='utf-8')
