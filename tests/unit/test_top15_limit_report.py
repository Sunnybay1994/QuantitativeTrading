import polars as pl
import pytest

from quant.reporting.top15_limit_v1 import fill_evidence


def test_split_fills_reconcile_in_original_units_and_side_signed_open_reference():
    orders=[{'id':1,'symbol':'600000.SH','side':'BUY','original_quantity':200,
        'filled_original_units':200.,'status':'filled'},
        {'id':2,'symbol':'600001.SH','side':'SELL','original_quantity':100,
         'filled_original_units':0.,'status':'expired'}]
    audit=pl.DataFrame({'order_id':[1,1],'symbol':['600000.SH']*2,'side':['BUY']*2,
        'quantity':[100,200],'share_factor':[1.,2.],'opening':[10.,5.],
        'signed_gap_to_open':[10.,-5.]})
    result=fill_evidence(orders,audit)
    assert result['all']['share_fill_rate']==pytest.approx(2/3)
    assert result['BUY']['share_fill_rate']==1.
    assert result['SELL']['expired_orders']==1
    assert result['all']['matched_quote_gap_to_open']==.0025
    assert result['all']['full_order_fill_rate']==.5
    with pytest.raises(ValueError,match='reconcile'):
        fill_evidence(orders,audit.with_columns(pl.lit(1.).alias('share_factor')))
    with pytest.raises(ValueError,match='Duplicate'):
        fill_evidence([*orders,orders[0]],audit)
