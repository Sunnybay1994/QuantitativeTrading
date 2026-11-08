"""Exercise the native launcher in a temporary workspace without starting jobs."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('powershell.exe') is None, reason='Native PowerShell required')
@pytest.mark.parametrize('case', ['active', 'future', 'expired', 'too_long', 'reversed', 'writer', 'ready'])
def test_bounded_reservation_and_read_only_probe(tmp_path, case):
    script = tmp_path/'scripts/run_continuous_mining.ps1'
    script.parent.mkdir()
    script.write_bytes((Path(__file__).resolve().parents[2]/'scripts/run_continuous_mining.ps1').read_bytes())
    shutil.copyfile(Path(__file__).resolve().parents[2]/'scripts/capital_path_window.ps1',
                    script.parent/'capital_path_window.ps1')
    root = tmp_path/'artifacts/research/continuous'
    slots = {
        'active': ('2026-10-31T11:00:00', '2026-10-31T13:00:00'),
        'future': ('2026-10-31T12:30:00', '2026-10-31T13:00:00'),
        'expired': ('2026-10-31T10:00:00', '2026-10-31T11:00:00'),
        'too_long': ('2026-10-31T11:00:00', '2026-10-31T16:00:00'),
        'reversed': ('2026-10-31T13:00:00', '2026-10-31T11:00:00'),
    }
    if case in slots:
        root.mkdir(parents=True)
        start,end=slots[case]
        (root/'data_window.json').write_text(json.dumps(dict(starts_at=start,expires_at=end)))
    if case == 'writer':
        root.mkdir(parents=True)
        (root/'scheduler.json').write_text('{"status":"original"}')
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    processes="[pscustomobject]@{CommandLine='python -m quant.data.baostock_history'}" if case=='writer' else '@()'
    wrapper=tmp_path/'probe.ps1'
    wrapper.write_text(
        "function Get-Date { [datetime]::Parse('2026-10-31T12:00:00') }\n"
        f"function Get-CimInstance {{ {processes} }}\n"
        "& (Join-Path $PSScriptRoot 'scripts/run_continuous_mining.ps1') -CheckOnly\n",
        encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],
        cwd=tmp_path,capture_output=True,text=True,timeout=30)
    if case in ('too_long','reversed'):
        assert result.returncode != 0 and 'at most four hours' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        if case in ('active','writer'):
            assert json.loads(result.stdout)['status']=='deferred'
        else:
            expected='0.5' if case=='future' else '2'
            assert result.stdout.strip()==f'Ready; maximum slice hours: {expected}'
    after={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and p!=wrapper}
    assert after == before
    if case=='ready':
        assert not root.exists()
