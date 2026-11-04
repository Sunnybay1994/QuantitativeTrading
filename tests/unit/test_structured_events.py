import datetime as dt

import polars as pl
import pytest

from quant.data.structured_events import normalize,chunks


def test_original_announcement_date_does_not_backdate_current_snapshot_availability():
    frame=pl.DataFrame({'ts_code':['000001.SZ'],'ann_date':['20190104'],'value':[1.]})
    result=normalize(frame,table='repurchase',rule={'date_field':'ann_date','announcement_field':'ann_date'},
        observed_at='2026-11-04T18:30:00+00:00',raw_path='raw/immutable.parquet')
    row=result.row(0,named=True)
    assert row['source_announcement_date']==dt.date(2019,1,4)
    assert row['announcement_available_at']==dt.datetime(2019,1,4,16,tzinfo=dt.timezone.utc)
    assert row['available_at']==row['observed_at']
    again=normalize(frame,table='repurchase',rule={'date_field':'ann_date','announcement_field':'ann_date'},
        observed_at='2026-11-05T00:00:00+00:00',raw_path='raw/other.parquet')
    assert again['source_row_id'].equals(result['source_row_id'])


def test_shards_cover_every_requested_day_once_including_partial_leap_february():
    first,last=dt.date(2020,2,15),dt.date(2020,3,3)
    assert list(chunks(first,last,'month'))==[(first,dt.date(2020,2,29)),(dt.date(2020,3,1),last)]
    assert list(chunks(first,last,'year'))==[(first,last)]
