import datetime as dt

import polars as pl
import pytest

from quant.data.event_family_inputs import read_event_source,event_family_source_facts

NOW=dt.datetime(2026,11,5,3,tzinfo=dt.timezone.utc)


def publish(root,table,rows,*,snapshot='one'):
    folder=root/f'clean/{table}/snapshot={snapshot}/year=2026'
    folder.mkdir(parents=True)
    (folder.parent/'summary.json').write_text('{}')
    frame=pl.from_dicts([{'ts_code':'600000.SH','source_announcement_date':dt.date(2026,10,1),
        'available_at':NOW,'observed_at':NOW,'source_raw_path':'raw/'+snapshot,**row} for row in rows])
    frame.write_parquet(folder/'data.parquet')
    return folder


def test_unlock_keeps_future_scheduled_date_and_individual_native_holder_records(tmp_path):
    publish(tmp_path,'share_float',[{'source_row_id':'a','float_date':'20261201','float_share':100.,'holder_name':'A'},
        {'source_row_id':'b','float_date':'20261201','float_share':200.,'holder_name':'B'}])
    frame,paths=read_event_source(tmp_path,'share_float',known_at=NOW)
    result=frame.collect()
    assert len(paths)==1 and result.height==2 and result['float_share'].to_list()==[100.,200.]
    assert set(result['float_date'])=={'20261201'}
    hidden,_=read_event_source(tmp_path,'share_float',known_at=NOW-dt.timedelta(seconds=1))
    assert hidden.collect().is_empty()
    facts=event_family_source_facts(tmp_path,known_at=NOW)
    assert facts['sources']['share_float']['visible_native_records']==2
    assert not facts['quantity_aggregation_performed'] and not facts['evaluate_this_round']


def test_first_observation_dedup_does_not_merge_distinct_holder_count_periods(tmp_path):
    rows=[{'source_row_id':'a','end_date':'20260930','holder_num':1000},
        {'source_row_id':'b','end_date':'20260630','holder_num':2000}]
    publish(tmp_path,'stk_holdernumber',rows)
    later=[{**row,'available_at':NOW+dt.timedelta(days=1),'observed_at':NOW+dt.timedelta(days=1)} for row in rows]
    publish(tmp_path,'stk_holdernumber',later,snapshot='repeated')
    frame,_=read_event_source(tmp_path,'stk_holdernumber',known_at=NOW+dt.timedelta(days=2))
    result=frame.collect()
    assert result.height==2 and set(result['source_raw_path'])=={'raw/one'}
    assert result['holder_num'].to_list()==[1000,2000]


def test_unpublished_snapshots_and_late_observations_cannot_supply_past_inputs(tmp_path):
    folder=publish(tmp_path,'share_float',[{'source_row_id':'a','float_share':100.,'observed_at':NOW+dt.timedelta(days=1)}])
    frame,_=read_event_source(tmp_path,'share_float',known_at=NOW)
    assert frame.collect().is_empty()
    (folder.parent/'summary.json').unlink()
    assert read_event_source(tmp_path,'share_float',known_at=NOW)==(None,[])
    assert event_family_source_facts(tmp_path,known_at=NOW)['sources']['share_float']['status']=='table_not_captured'


def test_source_whitelist_timezone_and_provenance_are_required(tmp_path):
    with pytest.raises(ValueError,match='Unregistered'):
        read_event_source(tmp_path,'unregistered',known_at=NOW)
    with pytest.raises(ValueError,match='timezone-aware'):
        read_event_source(tmp_path,'share_float',known_at=NOW.replace(tzinfo=None))
    folder=publish(tmp_path,'share_float',[{'source_row_id':'a','float_share':100.}])
    path=folder/'data.parquet'
    pl.read_parquet(path).drop('source_raw_path').write_parquet(path)
    with pytest.raises(ValueError,match='provenance'):
        read_event_source(tmp_path,'share_float',known_at=NOW)
