import datetime as dt

import polars as pl
import pytest

from quant.execution.etf_quote_paper import simulate
from quant.execution.manual_nav import close_manual_day
from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA


D0,D1,D2=dt.date(2026,9,21),dt.date(2026,9,22),dt.date(2026,9,23)


def at(time):
    return f'{D1}T{time}+08:00'


def order(identifier,side='BUY',symbol='518880.SH',time='09:32:00'):
    return dict(order_id=identifier,side=side,symbol=symbol,quantity=200,
                limit=11 if side=='BUY' else 9,submitted_at=at(time),deadline=at('09:40:00'))


def quote(identifier,time,symbol='518880.SH'):
    return dict(quote_id=identifier,symbol=symbol,provider_time=at(time),received_at=at(time),
                bid=10.,ask=10.,bid_size=10000.,ask_size=10000.,
                up_limit=11.,down_limit=9.,suspended=False)


def opening():
    return dict(date=str(D0),cash=100000.,holdings={},receivables=[],restricted_shares=[])


def test_partial_commission_t0_and_closing_nav_reconcile():
    orders=[order('buy'),order('sell','SELL',time='09:34:00')]
    quotes=[quote('a','09:32:01'),quote('b','09:33:01'),quote('c','09:34:01'),quote('d','09:35:01')]
    book,events,states=simulate(opening(),orders,quotes,(D0,D1,D2),as_of=at('09:40:00'))
    assert states[0]['fees']==pytest.approx(5)
    assert states[1]['fees']==pytest.approx(5)
    assert len(events)==4 and book['holdings']=={}
    assert book['cash']==pytest.approx(99989.6)
    state,result=close_manual_day(opening={**opening(),'t_plus_zero_symbols':['518880.SH']},events=events,date=D1,
        bars=pl.DataFrame({'symbol':['518880.SH'],'trade_date':[D1],'close':[10.]}),
        calendar=pl.DataFrame({'date':[D0,D1,D2],'market':['SH']*3,'is_open':[True]*3}),
        dividends=pl.DataFrame(schema=DIVIDEND_SCHEMA),
        suspensions=pl.DataFrame(schema={'symbol':pl.String,'trade_date':pl.Date}))
    assert result['valuation']['equity']==pytest.approx(book['cash'])
    assert state['cumulative_fees']==pytest.approx(10)


def test_t1_cannot_sell_new_shares_and_duplicate_quote_has_no_extra_capacity():
    symbol='510300.SH'
    quotes=[quote('a','09:32:01',symbol),quote('b','09:33:01',symbol),quote('c','09:34:01',symbol)]
    book,events,states=simulate(opening(),[order('buy',symbol=symbol),order('sell','SELL',symbol,'09:34:00')],
        quotes+[quotes[0]],(D0,D1,D2),as_of=at('09:40:00'))
    assert len(events)==2 and states[1]['remaining']==200
    assert book['holdings'][symbol]['quantity']==200


def test_stale_future_and_pre_submission_quotes_never_fill():
    stale=quote('stale','09:32:00')
    stale['received_at']=at('09:32:11')
    quotes=[stale,quote('early','09:31:59'),quote('late','09:41:00')]
    _,events,states=simulate(opening(),[order('buy')],quotes,(D0,D1,D2),as_of=at('09:40:00'))
    assert events==[] and states[0]['remaining']==200
    with pytest.raises(ValueError,match='Finalize'):
        simulate(opening(),[order('buy')],quotes,(D0,D1,D2),as_of=at('09:35:00'))
