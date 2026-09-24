import datetime as dt
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quant.research.etf_minute_coverage import window_quality


DAY=dt.date(2024,1,2)


def frame():
    start=dt.datetime(2024,1,2,9,30,tzinfo=ZoneInfo('Asia/Shanghai'))
    return pl.DataFrame([dict(trade_date=DAY,bar_start=start+dt.timedelta(minutes=i),
        bar_end=start+dt.timedelta(minutes=i+1),open=10.,high=11.,low=9.,close=10.,volume=100.,amount=1000.) for i in range(5)])


def test_exact_contiguous_window_and_noncontiguous_rejected():
    bars=frame();window,reason=window_quality(bars,DAY,'1m')
    assert reason=='valid' and window['volume']==500 and window['high']==11
    assert window_quality(bars.head(4),DAY,'1m')[0] is None
    assert window_quality(bars,DAY+dt.timedelta(days=1),'1m')[0] is None


@pytest.mark.parametrize('amount',[None,0.,float('nan'),1200.])
def test_missing_turnover_or_vwap_failure_not_valid(amount):
    bars=frame().with_columns(pl.lit(amount,dtype=pl.Float64).alias('amount'))
    assert window_quality(bars,DAY,'1m')[0] is None


def test_orders_use_signal_close_actual_holdings_and_whole_lots():
    from quant.research.etf_delayed_replay import planned_orders
    signal=DAY-dt.timedelta(days=1)
    batch=pl.DataFrame(dict(as_of=[signal,signal],execution_date=[DAY,DAY],symbol=['bond','gold'],weight=[.8,.2]))
    state=dict(date=str(signal),nav=[dict(equity=100000.)],holdings={'bond':dict(quantity=600),'gold':dict(quantity=1000)})
    orders=planned_orders(batch,state,{'bond':140.,'gold':5.},{'bond':100,'gold':100})
    rows={r['symbol']:r for r in orders.to_dicts()}
    assert rows['bond']['quantity']==100 and rows['bond']['side']=='SELL'
    assert rows['gold']['quantity']==3000 and rows['gold']['side']=='BUY'
    state['date']=str(DAY)
    with pytest.raises(ValueError,match='signal-close'):planned_orders(batch,state,{}, {})
