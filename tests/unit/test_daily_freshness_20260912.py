import datetime as dt
import polars as pl
from quant.data.daily_freshness_20260912 import profile


def test_profile_counts_only_requested_session_and_flags_duplicate_keys():
    day=dt.date(2026,9,11)
    frame=pl.DataFrame({'symbol':['A','A','B','C'],'trade_date':[day,day,day,dt.date(2026,9,10)]})
    result=profile(frame,'trade_date',day)
    assert result['rows']==3
    assert result['symbols']==2
    assert result['duplicate_keys']==1
    assert result['latest_date']=='2026-09-11'
