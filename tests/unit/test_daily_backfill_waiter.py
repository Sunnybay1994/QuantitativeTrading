"""Exercise the PowerShell waiter with isolated receipts and no provider or live writer."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2]/'scripts/run_daily_observation_backfill.ps1'
SHELL = shutil.which('powershell.exe') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(SHELL is None, reason='PowerShell not installed')


def copy_script(tmp_path):
    path=tmp_path/'scripts'/SCRIPT.name
    path.parent.mkdir()
    shutil.copyfile(SCRIPT,path)
    return path


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


@pytest.mark.parametrize('kind', ['stale', 'complete', 'failed_scheduler', 'rehearsal'])
def test_completion_requires_target_receipts_not_existing_directory(tmp_path, kind):
    script=copy_script(tmp_path)
    daily=tmp_path/'artifacts/daily/sue_v2/run'
    save(daily/'summary.json',dict(as_of='2026-11-06',status='complete',saved_data=False,
                                 rehearsal=kind=='rehearsal'))
    save(daily/'scheduler.json',dict(exit_code=1 if kind=='failed_scheduler' else 0))
    save(tmp_path/'artifacts/daily/market_context/latest.json',
         dict(status='complete',date='2026-11-05' if kind=='stale' else '2026-11-06'))
    command=f". '{script}' -To '2026-11-06'; Get-BackfillCompletion '{tmp_path}' '2026-11-06' | ConvertTo-Json -Compress"
    result=subprocess.run([SHELL,'-NoProfile','-Command',command],capture_output=True,text=True,check=True)
    receipt=json.loads(result.stdout)
    assert receipt['market_context_complete'] is (kind!='stale')
    assert receipt['daily_complete'] is (kind not in ['failed_scheduler','rehearsal'])


def test_timeout_writes_terminal_state_and_never_launches_runner(tmp_path):
    script=copy_script(tmp_path)
    command=("function Get-CimInstance { [pscustomobject]@{ProcessId=1234; CommandLine='python -m quant data baostock-history'} }; "
             f"& '{script}' -To '2026-11-06' -MaxWaitMinutes 0; exit $LASTEXITCODE")
    result=subprocess.run([SHELL,'-NoProfile','-Command',command],capture_output=True,text=True)
    assert result.returncode==3, result.stdout+result.stderr
    receipt=json.loads((tmp_path/'artifacts/daily/scheduler/do_backfill_status.json').read_text(encoding='utf-8-sig'))
    assert receipt['status']=='do_backfill_timed_out'
    assert receipt['writer_pids']==[1234] and receipt['exit_code']==3
    assert not (tmp_path/'artifacts/daily/sue_v2').exists()


@pytest.mark.parametrize('context_date,expected_code', [('2026-11-06',0), ('2026-11-05',1)])
def test_runner_zero_is_not_success_without_matching_context(tmp_path,context_date,expected_code):
    script=copy_script(tmp_path)
    (script.parent/'run_daily_observation.ps1').write_text(
        'param([string]$To,[switch]$WaitForWriter)\nexit 0\n',encoding='utf-8')
    save(tmp_path/'artifacts/daily/sue_v2/run/summary.json',dict(
        as_of='2026-11-06',status='complete',rehearsal=False,saved_data=False))
    save(tmp_path/'artifacts/daily/market_context/latest.json',dict(status='complete',date=context_date))
    command=(f"function Get-CimInstance {{ }}; & '{script}' -To '2026-11-06' "
             '-MaxWaitMinutes 0; exit $LASTEXITCODE')
    result=subprocess.run([SHELL,'-NoProfile','-Command',command],capture_output=True,text=True)
    assert result.returncode==expected_code, result.stdout+result.stderr
    receipt=json.loads((tmp_path/'artifacts/daily/scheduler/do_backfill_status.json').read_text(encoding='utf-8-sig'))
    assert receipt['status']==('do_backfill_finished' if expected_code==0 else 'do_backfill_incomplete')
