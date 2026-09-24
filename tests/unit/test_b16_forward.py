import copy
import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.realtime_inputs import TZ
from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA
from quant.execution import b16_forward as b
from quant.execution import b16_forward_service as service
from quant.execution.etf_quote_paper import simulate
from quant.execution.etf_manual_bootstrap import initialize


DAY = dt.date(2026,10,8)
SIGNAL = dt.date(2026,9,30)


def quote(time='09:32:01', identity='q', size=10000):
    return dict(quote_id=identity, symbol='518880.SH', provider_time=b.clock(DAY,time).isoformat(),
                received_at=b.clock(DAY,time).isoformat(), bid=10., ask=10., bid_size=size,
                ask_size=size, up_limit=11., down_limit=9., suspended=False)


def book():
    return dict(date=str(SIGNAL), cash=100000., holdings={}, receivables=[], restricted_shares=[],
                valuation=dict(equity=100000., unit_nav=1.))


def order():
    return dict(order_id='o', symbol='518880.SH', side='BUY', quantity=200, limit=11.,
                submitted_at=b.clock(DAY,'09:32').isoformat(),deadline=b.clock(DAY,'09:40').isoformat())


def test_post_submission_stale_duplicate_and_missing_depth():
    early=quote('09:31:59','early')
    equal=quote('09:32:00','equal')
    stale=quote(identity='stale');stale['received_at']=b.clock(DAY,'09:32:12').isoformat()
    future=quote('09:32:03','future');future['received_at']=b.clock(DAY,'09:32:02').isoformat()
    missing=quote('09:32:04','missing',0)
    valid=quote('09:33:01','valid')
    repeated={**valid, 'quote_id':'poll_again','received_at':b.clock(DAY,'09:33:02').isoformat()}
    result,events,states=simulate(book(),[order()],[early,equal,stale,future,missing,valid,repeated],
        (SIGNAL,DAY),as_of=b.clock(DAY,'09:40').isoformat())
    assert len(events)==1 and events[0]['quantity']==100
    assert states[0]['remaining']==100 and result['cash']==pytest.approx(98994.9)


def test_partial_minimum_fee_and_cash_shortfall():
    initial=book();initial['cash']=2010.
    result,events,states=simulate(initial,[order()],[quote(),quote('09:33:01','q2')],
        (SIGNAL,DAY),as_of=b.clock(DAY,'09:40').isoformat())
    assert len(events)==2 and sum(e['fee'] for e in events)==pytest.approx(5.)
    assert result['cash']==pytest.approx(4.8) and states[0]['remaining']==0
    initial['cash']=2000.
    result,events,states=simulate(initial,[order()],[quote(),quote('09:33:01','q2')],
        (SIGNAL,DAY),as_of=b.clock(DAY,'09:40').isoformat())
    assert len(events)==1 and states[0]['remaining']==100 and result['cash']>=0


def test_actual_later_ready_and_cancel_without_fabrication():
    plan=dict(ready_at=b.clock(DAY,'09:33').isoformat(),execution_date=str(DAY),orders=[order()])
    limits={'518880.SH':dict(up_limit=11.,down_limit=9.)}
    assert b.submit(plan,DAY,b.clock(DAY,'09:34:59'),120,limits) is None
    actual=b.submit(plan,DAY,b.clock(DAY,'09:35:07'),120,limits)
    assert actual['submitted_at']==b.clock(DAY,'09:35:07').isoformat()
    assert b.submit(plan,DAY,b.clock(DAY,'09:40'),120,limits)['orders']==[]
    assert b.submit(plan,DAY,b.clock(DAY,'09:35'),120,{}) is None


def test_sina_depth_units_and_staleness():
    row=dict(code='SH.518880',data_date=str(DAY),data_time='09:32:01',
             bid1_price=10.,ask1_price=10.,bid1_lots=100.,ask1_lots=200.,
             depth_unit='lots_100_sdk_truncated',suspension=False,volume=999999999)
    bands={'518880.SH':dict(up_limit=11.,down_limit=9.)}
    quotes,rejected=service.normalize([row],b.clock(DAY,'09:32:02'),bands)
    assert not rejected and quotes[0]['bid_size']==10000 and quotes[0]['ask_size']==20000
    assert service.normalize([row],b.clock(DAY,'09:32:12'),bands)[0]==[]
    assert service.normalize([{**row,'ask1_lots':None}],b.clock(DAY,'09:32:02'),bands)[0]==[]


def test_six_account_lifecycle_restart_and_cash_conservation(tmp_path,monkeypatch):
    # Deliberately synthetic marks, isolated folders, no production-date override in CLI.
    dates=[dt.date(2026,6,1)+dt.timedelta(days=i) for i in range(122)]
    dates=[d for d in dates if d.weekday()<5 and d<=SIGNAL]+[DAY,DAY+dt.timedelta(days=1),dt.date(2026,10,30),dt.date(2026,11,2)]
    calendar=pl.DataFrame(dict(date=dates,market=['SH']*len(dates),is_open=[True]*len(dates)))
    root=tmp_path/'paper'
    initialize(b.CONFIG,root,calendar)
    rows=[]
    for i,day in enumerate(dates):
        for j,symbol in enumerate(b.SYMBOLS):
            rows.append(dict(symbol=symbol,trade_date=day,close=10.+j+i*.01,
                             adjusted_close=10.+j+i*.01+(.002*(i%3)*(j+1))))
    frame=pl.from_dicts(rows)
    frames=dict(bars=frame.select('symbol','trade_date','close'),prices=frame,
                calendar=calendar,dividends=pl.DataFrame(schema=DIVIDEND_SCHEMA))
    monkeypatch.setattr(b,'load_frames',lambda *_:(frames,{'fixture':'synthetic'}))
    result=b.daily(end=SIGNAL,now=b.clock(SIGNAL,'21:30'),root=root)
    assert len(result['accounts'])==6
    before={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/signal.json')}
    b.daily(end=SIGNAL,now=b.clock(SIGNAL,'21:35'),root=root)
    assert before=={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/signal.json')}
    for folder,delay,cost in b.scenarios(root):
        plan=b.read(folder/str(DAY)/'signal.json')
        assert plan['ready_at']==b.clock(SIGNAL,'21:30').isoformat()
        assert b.read(folder/'performance.json')['nav']==[]
        # Use the actual intended sizes, with large depth for deterministic capacity.
    bands={s:dict(up_limit=20.,down_limit=1.) for s in b.SYMBOLS}
    service.step(root,tmp_path, b.clock(DAY,'09:31:05'),bands)
    assert len(list(root.glob('delay_*/cost_*/*/submission.json')))==3
    service.step(root,tmp_path,b.clock(DAY,'09:32:05'),bands)
    submissions={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/submission.json')}
    service.step(root,tmp_path,b.clock(DAY,'09:33:05'),bands)
    assert submissions=={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/submission.json')}
    quotes=[]
    for i,s in enumerate(b.SYMBOLS):
        q={**quote('09:33:00',str(i),1000000), 'symbol':s,'up_limit':20.,'down_limit':1.}
        quotes.append(q)
    b.atomic_json(root/'quotes'/str(DAY)/'packet.json',dict(quotes=quotes))
    result=b.daily(end=DAY,now=b.clock(DAY,'21:30'),root=root)
    assert len(result['accounts'])==6
    files={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/execution.json')}
    b.daily(end=DAY,now=b.clock(DAY,'21:40'),root=root)
    assert files=={str(p):p.read_bytes() for p in root.glob('delay_*/cost_*/*/execution.json')}
    for folder,delay,cost in b.scenarios(root):
        execution=b.read(folder/str(DAY)/'execution.json')
        saved=b.read(folder/'state.json')
        expected=100000.-sum(e['quantity']*e['price']+e['fee'] for e in execution['events'])
        assert saved['cash']==pytest.approx(expected) and saved['cash']>=0
        assert b.read(folder/'performance.json')['inception']==str(DAY)
        assert len(b.read(folder/'performance.json')['nav'])==1
    (tmp_path/'acceptance.json').write_text(json.dumps(dict(accounts=6, restart_identical=True,
        cash_conserved=True, fixture_only=True, result=result),indent=2))


def test_sell_proceeds_fund_later_buy_and_fee_crosses_minimum():
    initial=book();initial['cash']=0.
    initial['holdings']={'518880.SH':dict(quantity=10000,mark_price=10.)}
    sell={**order(),'side':'SELL','limit':9.,'quantity':10000,'order_id':'sell'}
    buy={**order(),'quantity':10000,'order_id':'buy', 'submitted_at':b.clock(DAY,'09:34').isoformat()}
    quotes=[quote('09:32:01','a',500000),quote('09:33:01','b',500000),quote('09:34:01','c',1000000)]
    result,events,orders=simulate(initial,[sell,buy],quotes,(SIGNAL,DAY),as_of=b.clock(DAY,'09:40').isoformat())
    sells=[e for e in events if e['kind']=='SELL']
    assert len(sells)==2 and sum(e['fee'] for e in sells)==pytest.approx(99990.*.00025)
    assert events[-1]['kind']=='BUY' and events[-1]['quantity']==9900
    cash=sum((1 if e['kind']=='SELL' else -1)*e['price']*e['quantity']-e['fee'] for e in events)
    assert result['cash']==pytest.approx(cash) and result['cash']>=0


def test_simulated_dividend_is_settled_once(tmp_path):
    root=tmp_path/'paper';folder=root/'delay_120/cost_1';folder.mkdir(parents=True)
    initial=book();initial['holdings']={'518880.SH':dict(quantity=100,mark_price=10.)}
    initial['receivables']=[dict(symbol='518880.SH',amount=10.,pay_date=str(DAY))]
    b.atomic_json(folder/'state.json',initial)
    calendar=pl.DataFrame(dict(date=[SIGNAL,DAY],market=['SH','SH'],is_open=[True,True]))
    dividends=pl.DataFrame(schema=DIVIDEND_SCHEMA)
    result=b.finalize(folder,DAY,[SIGNAL,DAY],dividends,calendar)
    assert result['book']['cash']==100010. and result['book']['receivables']==[]
    assert len(result['events'])==1
    assert result==b.finalize(folder,DAY,[SIGNAL,DAY],dividends,calendar)
