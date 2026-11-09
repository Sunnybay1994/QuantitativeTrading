"""Native launcher control-flow tests; no provider calls or production tasks."""
import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest


@pytest.mark.skipif(shutil.which('powershell.exe') is None, reason='Native PowerShell required')
@pytest.mark.parametrize('failure', ['exit', 'invalid_json', 'missing_id'])
def test_pause_failure_retains_bounded_fallback_without_release(tmp_path, failure):
    script = tmp_path/'scripts/run_daily_observation.ps1'
    script.parent.mkdir()
    payload = (Path(__file__).resolve().parents[2]/'scripts/run_daily_observation.ps1').read_text(encoding='utf-8-sig')
    script.write_text(payload.replace("$python = 'D:\\Miniforge3\\python.exe'",
                                     "$python = 'Invoke-FixturePython'"), encoding='utf-8-sig')
    wrapper = tmp_path/'run.ps1'
    response = {'exit': "$global:LASTEXITCODE=1; 'request failed'",
                'invalid_json': "$global:LASTEXITCODE=0; 'invalid JSON'",
                'missing_id': "$global:LASTEXITCODE=0; '{}'"}[failure]
    wrapper.write_text('''function Get-CimInstance { [pscustomobject]@{ProcessId=123; CommandLine='python -m quant.data.baostock_history'} }
function Invoke-FixturePython {
    $captured=@($args)
    ConvertTo-Json -InputObject $captured -Compress | Add-Content -Encoding utf8 -LiteralPath (Join-Path $PSScriptRoot 'calls.jsonl')
    if ($captured -contains 'request') { RESPONSE; return }
    if ($captured -contains 'quant.execution.paper_order_fallback') { $global:LASTEXITCODE=2; return }
    $global:LASTEXITCODE=0
}
& (Join-Path $PSScriptRoot 'scripts/run_daily_observation.ps1') -To 2026-11-06 -WaitForWriter -WriterWaitSeconds 1
exit $LASTEXITCODE
'''.replace('RESPONSE', response), encoding='utf-8-sig')
    began = time.monotonic()
    result = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],
                            cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode == 2, (result.stdout,result.stderr)
    assert time.monotonic()-began < 30
    calls = [json.loads(line) for line in (tmp_path/'calls.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert sum('request' in call for call in calls) == 1
    assert not any('release' in call or 'daily' in call for call in calls)
    fallback = next(call for call in calls if 'quant.execution.paper_order_fallback' in call)
    assert 0 < float(fallback[fallback.index('--budget-seconds')+1]) <= 110
    logs = list((tmp_path/'artifacts/daily/scheduler').glob('*.log'))
    log = logs[0].read_text(encoding='utf-8-sig')
    assert 'capital_pause_request_failed' in log
    assert 'writer_wait_budget_exhausted' in log
    assert 'frozen_order_fallback_exit=2; full_daily_not_run' in log
