import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess

import polars as pl
import pytest

from quant.core import capital_window as window


def calendars(root, day, opened=True):
    for market in ('SH','SZ'):
        path=root/f'clean/trade_calendar/market={market}/data.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        pl.DataFrame(dict(date=[day],is_open=[opened])).write_parquet(path)


@pytest.mark.parametrize('clock,expected', [('20:29',None),('20:30','capital_path_2030_2330'),
    ('23:29','capital_path_2030_2330'),('23:30',None)])
def test_exact_trading_window_not_weekday_guess(tmp_path,clock,expected):
    day=dt.date(2026,11,9);calendars(tmp_path,day)
    now=dt.datetime.fromisoformat(f'{day}T{clock}:00+08:00')
    assert window.reason(now=now,data_root=tmp_path,pause_path=tmp_path/'absent')==expected
    calendars(tmp_path,day,False)
    assert window.reason(now=now,data_root=tmp_path,pause_path=tmp_path/'absent') is None


def test_request_expiry_and_owner_release(tmp_path):
    path=tmp_path/'pause.json';now=dt.datetime(2026,11,9,21,tzinfo=window.TZ)
    calendars(tmp_path,now.date())
    marker=window.request(target='2026-11-06',pause_path=path,now=now)
    assert window.reason(now=now,data_root=tmp_path,pause_path=path)=='capital_path_pause_requested'
    window.release('different-owner',pause_path=path)
    assert path.exists()
    assert window.reason(now=now+dt.timedelta(seconds=601),data_root=tmp_path,pause_path=path)=='capital_path_2030_2330'
    window.release(marker['request_id'],pause_path=path)
    assert not path.exists()


def test_pause_hint_cannot_reserve_weekend_or_daytime(tmp_path):
    path=tmp_path/'pause.json'
    for clock,opened in [(dt.datetime(2026,11,8,21,tzinfo=window.TZ),False),
                         (dt.datetime(2026,11,9,12,tzinfo=window.TZ),True)]:
        calendars(tmp_path,clock.date(),opened)
        window.request(target=str(clock.date()),pause_path=path,now=clock)
        assert window.reason(now=clock,data_root=tmp_path,pause_path=path) is None


def test_disagreeing_or_missing_calendar_does_not_guess_weekdays(tmp_path):
    clock=dt.datetime(2026,11,9,21,tzinfo=window.TZ)
    calendars(tmp_path,clock.date())
    p=tmp_path/'clean/trade_calendar/market=SH/data.parquet'
    pl.DataFrame(dict(date=[clock.date()],is_open=[False])).write_parquet(p)
    assert window.reason(now=clock,data_root=tmp_path)=='capital_window_calendar_unavailable'


def test_background_checkpoint_yields_but_order_path_does_not(tmp_path,monkeypatch):
    monkeypatch.setattr(window,'reason',lambda **kw:'capital_path_pause_requested')
    monkeypatch.delenv('QUANT_BACKGROUND_WRITER',raising=False)
    window.checkpoint()
    monkeypatch.setenv('QUANT_BACKGROUND_WRITER','1')
    with pytest.raises(window.CapitalPathPause):window.checkpoint()
    from quant.research.slice_budget import checkpoint,SliceYield
    with pytest.raises(SliceYield,match='Time slice yielded'):checkpoint()


def test_baostock_yields_before_next_request_without_source_failure(tmp_path,monkeypatch):
    from quant.data import baostock_history as history,refresh
    monkeypatch.setenv('QUANT_BACKGROUND_WRITER','1')
    monkeypatch.setattr(window,'reason',lambda **kw:'capital_path_pause_requested')
    monkeypatch.setattr(refresh,'latest_session',lambda **kw:dt.date(2026,11,6))
    monkeypatch.setattr(history,'bao_members',lambda root:[dict(symbol='600000.SH',list_date='20200101')])
    monkeypatch.setattr(history,'capture',lambda *a:pytest.fail('Cannot fetch in paused batch'))
    receipt=history.run(root=tmp_path/'data',output=tmp_path/'record')
    assert receipt['status']=='paused' and receipt['requests']==receipt['errors']==0
    assert not list((tmp_path/'record').glob('checkpoints/*/*.json'))


def test_futu_page_saved_before_cooperative_yield(tmp_path,monkeypatch):
    import pandas as pd
    from quant.data import futu_minute_backfill as download
    monkeypatch.setenv('QUANT_BACKGROUND_WRITER','1')
    calls=[]
    monkeypatch.setattr(window,'reason',lambda **kw:'capital_path_pause_requested' if calls else None)
    monkeypatch.setattr(download.time,'sleep',lambda seconds:None)
    def fetch(*args):
        calls.append(args)
        return pd.DataFrame(dict(code=['HK.00001'],time_key=['2026-11-06 10:00:00'])), 'next-page'
    monkeypatch.setattr(download,'history_page',fetch)
    raw=tmp_path/'raw'
    with pytest.raises(window.CapitalPathPause):
        download.fetch_history_pages(None,'00001.HK','2026-01-01','2026-11-06',raw)
    assert len(calls)==1 and (raw/'page_0000.parquet').exists()


@pytest.mark.skipif(shutil.which('powershell.exe') is None,reason='Native PowerShell required')
def test_installer_triggers_without_deploying_tasks(tmp_path):
    repo=Path(__file__).resolve().parents[2]
    wrapper=tmp_path/'install_probe.ps1'
    wrapper.write_text('''$global:k2TestRecords=New-Object System.Collections.Generic.List[object]
function Get-ScheduledTask { return $null }
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory) return @{arguments=$Argument;workspace=$WorkingDirectory} }
function New-ScheduledTaskTrigger { param([switch]$Daily,[switch]$Weekly,$DaysOfWeek,$At) return @{at=$At;days=$DaysOfWeek} }
function New-ScheduledTaskSettingsSet { return @{} }
function New-ScheduledTaskPrincipal { return @{} }
function Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Settings,$Principal,$Description,[switch]$Force)
 $global:k2TestRecords.Add(@{name=$TaskName;action=$Action;triggers=@($Trigger)})
}
'''+f"& '{(repo/'scripts/install_minute_refresh.ps1').as_posix()}'\n"+
        f"& '{(repo/'scripts/install_fast_tests.ps1').as_posix()}'\n"+
        '$global:k2TestRecords | ConvertTo-Json -Depth 8\n',encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(wrapper)],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    records={r['name']:r for r in json.loads(result.stdout)}
    assert [t['at'] for t in records['QuantitativeTrading-MinutesHistory']['triggers']]==['23:35']
    assert [t['at'] for t in records['QuantitativeTrading-MinutesRecent']['triggers']]==['16:10','21:10']
    assert [t['at'] for t in records['QuantitativeTrading-FastTests']['triggers']]==['00:30']
    assert all(Path(r['action']['workspace'])==repo for r in records.values())
