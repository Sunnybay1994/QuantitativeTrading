import datetime as dt

import polars as pl
import pytest

from quant.execution.preposted_book import PrepostedBook
from quant.portfolio.top15_limit import targets


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
