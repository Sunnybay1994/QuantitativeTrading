import datetime as dt

import polars as pl

from quant.data.structured_s4 import StructuredS4


def test_primary_known_date_cannot_precede_the_later_native_observation(tmp_path):
    published=dt.date(2026,10,9)
    first=dt.datetime(2026,11,5,3,tzinfo=dt.timezone.utc)
    observed=first+dt.timedelta(days=1)
    folder=tmp_path/'clean/stk_holdertrade/snapshot=fixture/year=2026'
    folder.mkdir(parents=True)
    (folder.parent/'summary.json').write_text('{}')
    pl.DataFrame({'ts_code':['000001.SZ'],'source_announcement_date':[published],
        'source_row_id':['a'],'source_raw_path':['raw/a'],'observed_at':[observed],
        'available_at':[first],'in_de':['DE'],'change_vol':[100000.],
        'avg_price':[10.],'change_ratio':[None]}).write_parquet(folder/'data.parquet')
    args=dict(family='insider_trading',symbol='000001.SZ',published=published,
        excerpt='股东已减持，成交金额100万元。')
    assert StructuredS4(data_root=tmp_path,start=published,end=published,now=first).lookup(**args) is None
    result=StructuredS4(data_root=tmp_path,start=published,end=published,now=observed).lookup(**args)
    assert result['known_at']==dt.date(2026,11,7)
