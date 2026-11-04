import datetime as dt

import polars as pl

from quant.data.structured_s4 import StructuredS4


def test_structured_fields_require_executed_excerpt_and_current_snapshot_availability(tmp_path):
    published=dt.date(2020,10,15)
    observed=dt.datetime(2026,11,4,12,tzinfo=dt.timezone.utc)
    folder=tmp_path/'clean/repurchase/snapshot=fixture/year=2020'
    folder.mkdir(parents=True)
    frame=pl.DataFrame({'ts_code':['000001.SZ'],'source_announcement_date':[published],
        'source_row_id':['immutable-id'],'source_raw_path':['raw/snapshot.parquet'],
        'observed_at':[observed],'available_at':[observed],
        'proc':['完成'],'end_date':['20201014'],'amount':[1000000.]})
    frame.write_parquet(folder/'data.parquet')
    excerpt='本次回购实施完成，支付的资金总额100万元。'
    args=dict(family='repurchase',symbol='000001.SZ',published=published,excerpt=excerpt)
    before=StructuredS4(data_root=tmp_path,start=published,end=published,now=observed-dt.timedelta(seconds=1))
    assert before.lookup(**args) is None
    current=StructuredS4(data_root=tmp_path,start=published,end=published,now=observed+dt.timedelta(seconds=1))
    result=current.lookup(**args)
    assert result['parsed']['amount_cny']==1000000.
    assert result['known_at']==dt.date(2026,11,5)
    assert current.lookup(**{**args,'excerpt':'拟回购金额不超过100万元。'}) is None
    assert current.lookup(**{**args,'excerpt':'本次回购完成，支付的资金总额200万元。'}) is None


def test_insider_quantity_is_native_shares_and_unexecuted_sells_cannot_reappear(tmp_path):
    published=dt.date(2020,10,15)
    observed=dt.datetime(2026,11,4,12,tzinfo=dt.timezone.utc)
    folder=tmp_path/'clean/stk_holdertrade/snapshot=fixture/year=2020'
    folder.mkdir(parents=True)
    pl.DataFrame({'ts_code':['000001.SZ'],'source_announcement_date':[published],
        'source_row_id':['native-shares'],'source_raw_path':['raw/snapshot.parquet'],
        'observed_at':[observed],'available_at':[observed],'in_de':['DE'],
        'change_vol':[100000.],'avg_price':[10.],'change_ratio':[None]}).write_parquet(folder/'data.parquet')
    lookup=StructuredS4(data_root=tmp_path,start=published,end=published,now=observed)
    args=dict(family='insider_trading',symbol='000001.SZ',published=published,excerpt='股东已减持，成交金额100万元。')
    assert lookup.lookup(**args)['parsed']['amount_cny']==1000000.
    assert lookup.lookup(**{**args,'excerpt':'股东未实施减持，计划金额100万元。'}) is None
