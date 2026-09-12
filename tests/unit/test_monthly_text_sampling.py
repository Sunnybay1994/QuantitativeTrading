import datetime as dt
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from quant.research.plan_monthly_text_scoring import monthly_selection


def test_sampling_is_order_invariant_and_nested_without_return_selection():
    panel = pl.DataFrame({'symbol':['000001.SZ','000002.SZ','000003.SZ']*2,
        'trade_date':[dt.date(2020,1,31)]*3+[dt.date(2020,2,28)]*3,
        'future_return':[1.,None,-1.,3.,2.,1.]})
    a = monthly_selection(panel,count=2,seed='fixed')
    b = monthly_selection(panel.reverse(),count=2,seed='fixed')
    assert_frame_equal(a,b)
    c = monthly_selection(panel.with_columns(pl.lit(999.).alias('future_return')),count=2,seed='fixed')
    assert a.select('symbol','trade_date').equals(c.select('symbol','trade_date'))
    small = monthly_selection(panel,count=1,seed='fixed')
    assert small.join(a,on=['symbol','trade_date'],how='anti').is_empty()


def test_duplicate_monthly_members_are_rejected():
    panel = pl.DataFrame({'symbol':['000001.SZ']*2,'trade_date':[dt.date(2020,1,31)]*2})
    with pytest.raises(ValueError,match='unique'):
        monthly_selection(panel,count=1,seed='fixed')
