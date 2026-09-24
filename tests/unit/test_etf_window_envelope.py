import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.research.etf_window_envelope import build, valid_opening


def test_opening_row_requires_own_valid_turnover():
    stamp=dt.datetime(2024,1,2,9,30,tzinfo=ZoneInfo('Asia/Shanghai'))
    row=dict(is_opening_row=True,adjustment='none',bar_time=stamp,trade_date=stamp.date(),
             open=10.,high=10.,low=10.,close=10.,volume=100.,amount=1000.)
    assert valid_opening(row)
    assert not valid_opening({**row,'amount':1200.})
    assert not valid_opening({**row,'adjustment':'forward'})
    assert not valid_opening({**row,'bar_time':stamp+dt.timedelta(minutes=1)})


def test_envelope_separates_opening_and_rejects_outside_daily_source(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);source=Path('source');source.mkdir();out=Path('out');out.mkdir()
    day=dt.date(2024,1,2);symbol='510300.SH';stamp=dt.datetime(2024,1,2,9,30,tzinfo=ZoneInfo('Asia/Shanghai'))
    pl.DataFrame([dict(symbol=symbol,trade_date=day,low=9.,high=12.)]).write_parquet(source/'bars.parquet')
    pl.DataFrame([dict(symbol=symbol,currency='CNY')]).write_parquet(source/'instruments.parquet')
    raw=[]
    for i in range(6):
        raw.append(dict(symbol=symbol,trade_date=day,bar_time=stamp+dt.timedelta(minutes=i),is_opening_row=i==0,
            adjustment='none',open=12. if i==0 else 10.,close=12. if i==0 else 10.,
            high=12. if i==0 else 11.,low=12. if i==0 else 9.,volume=100.,amount=1200. if i==0 else 1000.))
    folder=Path(f'data/clean/futu_minute/test/symbol={symbol}/year=2024');folder.mkdir(parents=True)
    pl.DataFrame(raw).write_parquet(folder/'data.parquet')
    common=dict(symbol=symbol,date=day,status='valid',freq='1m',open=10.,high=11.,low=9.,close=10.,volume=500.,amount=5000.)
    pl.DataFrame([{**common,'source':'futu:test'}, {**common,'source':'tdx','freq':'5m','high':12.},
                  {**common,'source':'baostock','freq':'5m','high':13.}]).write_csv(out/'minute_source_checks.csv')
    pl.DataFrame([dict(date=day,symbol=symbol,source_conflict=True,covered=False,reason='source_conflict')]).write_csv(out/'required_windows.csv')
    before=(out/'required_windows.csv').read_bytes()
    result,_=build(out,source,[symbol],[day])
    assert result['opening_explained_conflicts']==1 and result['strict_covered']==0
    assert (out/'required_windows.csv').read_bytes()==before
    envelope=pl.read_csv(out/'envelope_windows.csv').row(0,named=True)
    assert envelope['envelope_eligible'] and envelope['high']==12 and envelope['low']==9
    components=pl.read_csv(out/'source_window_components.csv')
    assert not components.filter(pl.col('source')=='baostock')['envelope_eligible'][0]
    assert set(components.filter(pl.col('source')=='futu:test')['component'])=={
        'opening_row','regular_first5m','opening_plus_regular_first5m'}
