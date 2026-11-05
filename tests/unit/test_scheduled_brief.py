import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import polars as pl
import pytest

from quant.reporting import research_brief, scheduled_brief

SH = dt.timezone(dt.timedelta(hours=8))
DUE = dt.datetime(2026,12,1,21,30,tzinfo=SH)


@pytest.mark.parametrize('clock',[
    dt.datetime(2026,11,5,21,30,tzinfo=SH),
    DUE.replace(hour=20), DUE.replace(hour=8), DUE.replace(day=2),
    dt.datetime(2026,11,30,23,30,tzinfo=dt.timezone.utc),
])
def test_no_paid_attempt_or_artifact_before_the_first_evening(tmp_path,monkeypatch,clock):
    monkeypatch.setattr(research_brief,'write_brief',lambda *a,**kw:pytest.fail('brief is not due'))
    assert scheduled_brief.run(root=tmp_path,now=clock)['status']=='not_due'
    assert not list(tmp_path.iterdir())


def _mock_llm(monkeypatch, text):
    calls=[]
    monkeypatch.setattr('quant.llm.complete_messages',lambda *args:calls.append(args) or {'content':text,'usd':.01})
    monkeypatch.setattr('quant.notify.send',lambda **kw:pytest.fail('scheduled brief must not send messages'))
    return calls


def test_closed_month_has_one_paid_attempt_and_reuses_unchanged_products(tmp_path,monkeypatch):
    calls=_mock_llm(monkeypatch,'市场资料仍不足，按现有事实核对风险。')
    first=scheduled_brief.run(root=tmp_path,now=DUE)
    monkeypatch.chdir(tmp_path)
    second=scheduled_brief.run(root=Path('.'),now=DUE.replace(hour=22))
    assert first['status']=='complete' and first['month']=='2026-11'
    assert second['reused'] and second['products_sha256']==first['products_sha256']
    assert len(calls)==1
    cache=json.loads((tmp_path/'artifacts/research/brief/2026-11.narrative.json').read_text(encoding='utf-8'))
    assert cache['facts']['month']=='2026-11' and cache['maximum_calls']==1
    ledger=list((tmp_path/'artifacts/research/llm_ledger').glob('*.jsonl'))
    assert len(ledger)==1 and len(ledger[0].read_text(encoding='utf-8').splitlines())==1


def test_rejected_paid_text_stays_incomplete_without_another_call(tmp_path,monkeypatch):
    calls=_mock_llm(monkeypatch,'市场风险为2级。')
    first=scheduled_brief.run(root=tmp_path,now=DUE)
    second=scheduled_brief.run(root=tmp_path,now=DUE.replace(hour=22))
    assert first['status']==second['status']=='incomplete'
    assert first['narrative_status']=='rejected_numeric_narrative' and len(calls)==1


def test_completed_product_tampering_is_not_another_paid_attempt(tmp_path,monkeypatch):
    calls=_mock_llm(monkeypatch,'仅依据已核对资料描述当前市场。')
    result=scheduled_brief.run(root=tmp_path,now=DUE)
    Path(result['report']).write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='product changed'):
        scheduled_brief.run(root=tmp_path,now=DUE.replace(hour=22))
    assert len(calls)==1


def _context(root,date):
    parent=root/'artifacts/daily/market_context'/date/'version'
    folder=parent/'attempt_001';folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'latest':{'trade_date':date,
        'observed_stocks':5000,'market_state':'trend_down'}}),encoding='utf-8')
    (folder/'report.md').write_text('machine report',encoding='utf-8')
    pl.DataFrame({'trade_date':[date],'observed_stocks':[5000]}).write_parquet(folder/'market_states.parquet')
    (folder/'source_manifest.json').write_text('{}',encoding='utf-8')
    receipt={'output':str(folder),'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
    (parent/'completed.json').write_text(json.dumps(receipt),encoding='utf-8')
    return folder


def test_brief_uses_dated_completed_market_facts_after_latest_pointer_moves(tmp_path):
    folder=_context(tmp_path,'2026-10-30')
    _context(tmp_path,'2026-11-02')
    (tmp_path/'artifacts/daily/market_context/latest.json').write_text(json.dumps({'date':'2026-11-02'}))
    facts=research_brief.collect_facts('2026-10',root=tmp_path)
    assert facts['market_state']['as_of']=='2026-10-30'
    assert facts['market_state']['source']==str(folder/'summary.json')
    assert facts['market_state']['status']=='observed_in_month'


def test_unpublished_attempt_is_not_market_fact_and_tampering_is_visible(tmp_path):
    folder=_context(tmp_path,'2026-10-30')
    marker=folder.parent/'completed.json';payload=marker.read_bytes();marker.unlink()
    assert research_brief.collect_facts('2026-10',root=tmp_path)['market_state']['status']=='unavailable_for_month'
    marker.write_bytes(payload)
    (folder/'source_manifest.json').write_text('changed')
    with pytest.raises(ValueError,match='checksum mismatch'):
        research_brief.collect_facts('2026-10',root=tmp_path)


def test_january_uses_previous_calendar_year(tmp_path,monkeypatch):
    _mock_llm(monkeypatch,'资料不足，保留原有事实与费用记录。')
    assert scheduled_brief.run(root=tmp_path,now=DUE.replace(year=2027,month=1))['month']=='2026-12'


@pytest.mark.skipif(sys.platform!='win32',reason='Production wrapper is Windows PowerShell')
def test_actual_wrapper_branch_honors_check_only_and_keeps_primary_exit(tmp_path):
    script=tmp_path/'verify_wrapper.ps1'
    script.write_text(r'''
param([string]$BriefWrapperPath)
$ErrorActionPreference='Stop'
$briefTokens=$null; $briefErrors=$null
$briefAst=[System.Management.Automation.Language.Parser]::ParseFile($BriefWrapperPath,[ref]$briefTokens,[ref]$briefErrors)
if ($briefErrors.Count) { throw 'Wrapper parse failed' }
$briefBranch=@($briefAst.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.Contains("Write-Stage 'monthly_research_brief'")
},$true))
if ($briefBranch.Count -ne 1) { throw 'Expected one monthly wrapper branch' }
$briefBlock=[ScriptBlock]::Create($briefBranch[0].Extent.Text)
function Write-Stage([string]$stage) { }
function Invoke-Python([string[]]$ArgumentList,[switch]$Append) {
    if (($ArgumentList -join ' ') -ne '-m quant report brief --scheduled --no-notify') {
        throw 'Unexpected paid command'
    }
    $script:briefCalls+=1
    return $script:briefExit
}
$cases=@(
    @{check=$true; primary=0; brief=0; calls=0; expected=0},
    @{check=$false; primary=0; brief=0; calls=1; expected=0},
    @{check=$false; primary=1; brief=0; calls=1; expected=1},
    @{check=$false; primary=0; brief=1; calls=1; expected=1},
    @{check=$false; primary=2; brief=0; calls=1; expected=2}
)
foreach ($case in $cases) {
    $CheckOnly=$case.check; $code=$case.primary
    $script:briefCalls=0; $script:briefExit=$case.brief
    . $briefBlock
    if ($code -ne $case.expected -or $script:briefCalls -ne $case.calls) {
        throw 'Wrapper changed primary failure or invoked paid work in check-only mode'
    }
}
Write-Output 'five wrapper cases passed; no real child job'
''',encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),
        '-BriefWrapperPath',str(Path('scripts/run_daily_observation.ps1').resolve())],
        capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stdout+result.stderr
    assert 'five wrapper cases passed' in result.stdout
