import datetime as dt

import polars as pl
import pytest

from quant.execution.preposted_book import PrepostedBook
from quant.execution.preposted_book import quote_tick
from quant.portfolio.top15_limit import targets


def test_legal_quote_rounding_never_widens_registered_bound():
    book=PrepostedBook()
    args=dict(signal=dt.date(2026,1,5),targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
        equity=30000.,closes={'600000.SH':10.03},offset=.01)
    book.replace(**args,holdings={})
    assert book.orders[0]['limit']==10.13
    book.replace(**{**args,'targets':pl.DataFrame({'symbol':['600000.SH'],'weight':[0.]})},
        holdings={'600000.SH':{'quantity':200}})
    assert book.orders[0]['limit']==9.93
    assert quote_tick(10.10,'BUY')==quote_tick(10.10,'SELL')==10.10
    ex=dt.date(2026,1,6)
    book.apply_actions(ex,pl.DataFrame({'symbol':['600000.SH'],'ann_date':[args['signal']],
        'ex_date':[ex],'div_cash':[.003],'share_ratio':[0.]}))
    assert book.orders[0]['limit']==9.93


def test_partial_fills_retry_only_original_remainder_and_expire_on_third_session():
    book=PrepostedBook()
    signal=dt.date(2026,1,5)
    book.replace(signal=signal,targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
        holdings={},equity=30000.,closes={'600000.SH':10.},offset=.01)
    empty=pl.DataFrame(schema={'symbol':pl.String,'side':pl.String,'quantity':pl.Int64})
    day=signal+dt.timedelta(days=1)
    orders,limits=book.attempt(day)
    assert orders['quantity'].item()==200 and limits['600000.SH','BUY']==10.1
    book.settle(pl.DataFrame({'symbol':['600000.SH'],'side':['BUY'],'quantity':[100]}))
    with pytest.raises(ValueError,match='new session'):
        book.attempt(day)
    orders,_=book.attempt(day+dt.timedelta(days=1))
    assert orders['quantity'].item()==100
    book.settle(empty)
    orders,_=book.attempt(day+dt.timedelta(days=2))
    assert orders['quantity'].item()==100
    book.settle(empty)
    assert book.orders[0]['status']=='expired'
    orders,_=book.attempt(day+dt.timedelta(days=3))
    assert orders.is_empty()
    book.settle(empty)
    assert book.orders[0]['original_quantity']==200 and book.orders[0]['remaining']==100


def test_new_signal_cancels_outstanding_without_relabelling_filled_orders():
    book=PrepostedBook()
    args=dict(signal=dt.date(2026,1,5),targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
        holdings={},equity=30000.,closes={'600000.SH':10.},offset=.03)
    book.replace(**args)
    book.replace(**{**args,'signal':dt.date(2026,2,2)})
    assert book.history[0]['status']=='cancelled_new_signal'
    assert book.orders[0]['id']!=book.history[0]['id']


def test_cash_and_split_adjust_pending_remainder_without_double_counting_fills():
    book=PrepostedBook()
    day=dt.date(2026,1,5)
    book.replace(signal=day,targets=pl.DataFrame({'symbol':['600000.SH'],'weight':[.08]}),
        holdings={},equity=30000.,closes={'600000.SH':10.},offset=.01)
    book.attempt(day+dt.timedelta(days=1))
    book.settle(pl.DataFrame({'symbol':['600000.SH'],'side':['BUY'],'quantity':[100]}))
    ex=day+dt.timedelta(days=2)
    event=pl.DataFrame({'symbol':['600000.SH'],'ann_date':[day], 'ex_date':[ex],
                       'share_ratio':[1.],'div_cash':[.1]})
    book.apply_actions(ex,event)
    orders,limits=book.attempt(ex)
    assert orders['quantity'].item()==200
    assert limits['600000.SH','BUY']==5.
    book.settle(pl.DataFrame({'symbol':['600000.SH'],'side':['BUY'],'quantity':[200]}))
    assert book.orders[0]['status']=='filled'
    assert book.orders[0]['filled_original_units']==book.orders[0]['original_quantity']==200


def test_unheld_zero_target_needs_no_obsolete_quote():
    book=PrepostedBook()
    book.replace(signal=dt.date(2026,1,5),targets=pl.DataFrame({'symbol':['003003.SZ'],'weight':[0.]}),
        holdings={},equity=300000.,closes={},offset=.01)
    assert book.orders==[]


def test_selector_preserves_buffer_caps_and_signal_close_lot_rule():
    day=dt.date(2026,1,5)
    names=[f'{600000+i}.SH' for i in range(40)]
    scores=pl.DataFrame({'symbol':names,'trade_date':[day]*40,'prediction':[float(40-i) for i in range(40)]})
    closes={s:10. for s in names}
    closes[names[0]]=1000. # A lot costs more than half any permitted name budget.
    batch,selected=targets(scores=scores,previous=[names[20],names[35]],closes=closes,
        equity=300000.,execution_date=day+dt.timedelta(days=1))
    assert names[20] in selected and names[35] not in selected and names[0] not in selected
    assert len(selected)<=15 and batch['weight'].max()<=.08 and batch['weight'].sum()<=1+1e-9
    weights=dict(batch.select('symbol','weight').iter_rows())
    assert all(100*closes[s]<=.5*weights[s]*300000 for s in selected)
    assert weights[names[35]]==0.
