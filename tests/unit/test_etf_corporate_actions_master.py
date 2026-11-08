import datetime as dt
import json

import polars as pl
import pytest

from quant.data.etf_corporate_actions import publish,load,sha


def test_announced_future_cash_is_opt_in_and_rejects_unannounced_terms():
    from quant.data.etf_corporate_actions import cash_actions
    raw=pl.DataFrame({'ts_code':['511010.SH','511010.SH'], 'div_proc':['实施','实施'],
        'ann_date':['20260101','20260106'], 'imp_anndate':['20260101','20260106'],
        'record_date':['20260102','20260107'], 'ex_date':['20260105','20260108'],
        'pay_date':['20260106','20260109'], 'div_cash':[.1,.2]})
    day=dt.date(2026,1,2)
    assert cash_actions(raw,day)==[]
    selected=cash_actions(raw,day,include_announced_future=True)
    assert len(selected)==1 and selected[0]['record_date']==day
    assert selected[0]['ex_date']==dt.date(2026,1,5)


def test_record_to_ex_cash_entitlement_is_not_given_to_ex_day_buyer():
    from quant.backtest.daily_account import advance
    from quant.data.etf_corporate_actions import cash_actions,SCHEMA
    from quant.backtest.rules import DailyMarketState
    from tests.unit.test_daily_simulator import (
        ETF,_calendar,_stock_and_etf_bars,_stock_and_etf_instruments,_stock_costs,_etf_costs)
    record,ex,pay=dt.date(2026,1,2),dt.date(2026,1,5),dt.date(2026,1,6)
    raw=pl.DataFrame({'ts_code':[ETF], 'div_proc':['实施'], 'ann_date':['20260101'],
        'record_date':['20260102'], 'ex_date':['20260105'], 'pay_date':['20260106'],
        'div_cash':[.1]})
    event=pl.from_dicts([{**r,'action_type':'CASH_DIVIDEND','adjust_share_price':True}
        for r in cash_actions(raw,record,include_announced_future=True)],schema=SCHEMA)
    calendar=pl.concat([_calendar(d) for d in (record,ex,pay)]).unique(['market','date'])
    config={'paper':{'name':'cash-test','auto_trade':False,'initial_cash':1400.},
        'costs':{'etf':_etf_costs().__dict__,'a_share':_stock_costs().__dict__}}
    state={'date':'2026-01-01','cash':1000.,'holdings':{ETF:{'quantity':100,'mark_price':4.}},
        'receivables':[],'pending':[],'nav':[]}
    state,_=advance(date=record,state=state,bars=_stock_and_etf_bars(record),calendar=calendar,
        instruments=_stock_and_etf_instruments(),market_states={(record,ETF):DailyMarketState()},
        dividends=event,config=config)
    bars=_stock_and_etf_bars(ex).filter(pl.col('symbol')==ETF).with_columns(
        *[pl.lit(3.9).alias(c) for c in ('open','high','low','close')])
    orders=pl.DataFrame({'as_of':[record],'execution_date':[ex], 'symbol':[ETF],
                         'side':['BUY'],'quantity':[100]})
    state,_=advance(date=ex,state=state,bars=bars,calendar=calendar,
        instruments=_stock_and_etf_instruments(),market_states={(ex,ETF):DailyMarketState()},
        dividends=event,config=config,scheduled_orders=orders)
    assert state['holdings'][ETF]['quantity']==200
    assert sum(r['amount'] for r in state['receivables'])==pytest.approx(10.)
    before=state['cash']
    bars=bars.with_columns(pl.lit(pay).alias('trade_date'))
    state,_=advance(date=pay,state=state,bars=bars,calendar=calendar,
        instruments=_stock_and_etf_instruments(),market_states={(pay,ETF):DailyMarketState()},
        dividends=event,config=config)
    assert state['cash']==pytest.approx(before+10.)
    assert state['receivables']==[]


def test_publisher_retains_announced_future_only_when_requested(tmp_path):
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    capture=tmp_path/'capture'
    capture.mkdir()
    (capture/'corporate_actions.toml').write_text('splits=[]\n',encoding='utf-8')
    (capture/'config.toml').write_text('auto_trade=false\n',encoding='utf-8')
    raw=capture/'cash.parquet'
    pl.DataFrame({'ts_code':['511010.SH'], 'div_proc':['实施'],
        'ann_date':[today.strftime('%Y%m%d')], 'record_date':[today.strftime('%Y%m%d')],
        'ex_date':[(today+dt.timedelta(days=1)).strftime('%Y%m%d')],
        'pay_date':[(today+dt.timedelta(days=2)).strftime('%Y%m%d')], 'div_cash':[.1]}).write_parquet(raw)
    (capture/'summary.json').write_text(json.dumps({
        'events_sha256':sha(capture/'corporate_actions.toml'),
        'requests':{'511010.SH/fund_div/0':{'raw_path':str(raw),'sha256':sha(raw)}}}),encoding='utf-8')
    sources=capture/'sources.json'
    sources.write_text('{}',encoding='utf-8')
    publish(capture=capture,sources=sources,output=tmp_path/'historical')
    publish(capture=capture,sources=sources,output=tmp_path/'announced',include_announced_future=True)
    assert load(tmp_path/'historical').is_empty()
    assert load(tmp_path/'announced')['record_date'].item()==today


def test_master_keeps_zero_cash_inventory_and_explicit_source_backed_split(tmp_path):
    capture=tmp_path/'capture'
    capture.mkdir()
    terms='''[[splits]]
symbol="512890.SH"
announcement_date=2021-10-18
record_date=2021-10-21
effective_date=2021-10-22
tradable_date=2021-10-25
ratio=2.0
notice="https://issuer/notice.pdf"
result="https://issuer/result.pdf"
'''
    (capture/'corporate_actions.toml').write_text(terms,encoding='utf-8')
    (capture/'config.toml').write_text('auto_trade=false\n',encoding='utf-8')
    empty=capture/'fund_div.parquet'
    pl.DataFrame(schema={'ts_code':pl.String}).write_parquet(empty)
    (capture/'summary.json').write_text(json.dumps({'events_sha256':sha(capture/'corporate_actions.toml'),
        'requests':{'512890.SH/fund_div/0':{'raw_path':str(empty),'sha256':sha(empty),'rows':0}}}),encoding='utf-8')
    notices={}
    for name in ['notice','result']:
        p=capture/f'{name}.pdf'
        p.write_bytes(b'%PDF-fixture')
        notices[name]={'url':f'https://issuer/{name}.pdf','path':str(p),'sha256':sha(p)}
    sources=capture/'sources.json'
    sources.write_text(json.dumps(notices),encoding='utf-8')
    master=tmp_path/'master'
    summary=publish(capture=capture,sources=sources,output=master)
    assert summary['symbols']==['512890.SH']
    inventory=json.loads((master/'sources.json').read_text(encoding='utf-8'))
    assert inventory[0]['rows']==0
    row=load(master,symbols=['512890.SH']).row(0,named=True)
    assert row['action_type']=='SHARE_SPLIT' and row['adjust_share_price'] is True
    assert row['share_ratio']==1. and row['source_sha256']==notices['notice']['sha256']
    assert load(master,end=dt.date(2021,10,21)).is_empty()
    with pytest.raises(ValueError,match='lacks a captured'):
        load(master,symbols=['511010.SH'])
    (master/'actions.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Invalid ETF action master'):
        load(master)
