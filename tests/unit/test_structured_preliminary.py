import datetime as dt

import polars as pl
import pytest

from quant.data.structured_preliminary import read_preliminary_history
from quant.research.monthly_sue_family import build_monthly_sue_prelim

NOW=dt.datetime(2026,11,5,3,tzinfo=dt.timezone.utc)


def publish(root,table,*,snapshot='one',identifier=None,seen=NOW,**values):
    path=root/f'clean/{table}/snapshot={snapshot}/year=2026'
    path.mkdir(parents=True)
    (path.parent/'summary.json').write_text('{}')
    row={'ts_code':'000001.SZ','ann_date':'20261010','end_date':'20260930',
        'available_at':seen,'observed_at':seen,'source_row_id':identifier or table,
        'source_raw_path':f'raw/{table}/{snapshot}.parquet',**values}
    pl.from_dicts([row]).write_parquet(path/'data.parquet')
    return path


def test_published_native_units_and_sources_reach_sue_without_point_imputation(tmp_path):
    publish(tmp_path,'forecast',net_profit_min='100',net_profit_max='200',p_change_min='-10',p_change_max='20')
    publish(tmp_path,'express',n_income=150.,revenue=1000.)
    history=read_preliminary_history(tmp_path,known_at=NOW)
    forecast=history.filter(pl.col('source_table')=='forecast').row(0,named=True)
    express=history.filter(pl.col('source_table')=='express').row(0,named=True)
    assert forecast['forecast_profit_min_10000cny']==100 and forecast['forecast_profit_max_10000cny']==200
    assert forecast['forecast_change_min_pct']==-10 and express['express_net_income_cny']==150
    assert express['forecast_profit_min_10000cny'] is None
    result=build_monthly_sue_prelim(income_history=pl.DataFrame(),
        signal_dates=(dt.date(2026,11,5),dt.date(2026,11,6)),
        candidate_symbols=('000001.SZ','000002.SZ'),preliminary_history=history)
    assert result.factors['sue_prelim'].null_count()==4
    selected=result.eligibility.filter(pl.col('symbol')=='000001.SZ').sort('as_of')
    assert selected['preliminary_observation_count'].to_list()==[0,2]
    assert selected['input_reason'].to_list()==['no_visible_preliminary_input','point_surprise_not_defined']
    assert selected['status'].to_list()==['SAMPLE_INSUFFICIENT']*2
    assert selected['preliminary_sources'][1].to_list()==['express','forecast']
    native=selected['preliminary_observations'][1].to_list()
    assert next(r for r in native if r['source_table']=='forecast')['forecast_profit_max_10000cny']==200


def test_current_download_does_not_retroactively_fill_announced_history(tmp_path):
    publish(tmp_path,'forecast',net_profit_min=100.,net_profit_max=200.)
    assert read_preliminary_history(tmp_path,known_at=NOW-dt.timedelta(seconds=1)).is_empty()
    history=read_preliminary_history(tmp_path,known_at=NOW)
    result=build_monthly_sue_prelim(income_history=pl.DataFrame(),signal_dates=(dt.date(2026,10,31),),
        candidate_symbols=('000001.SZ',),preliminary_history=history)
    assert result.eligibility['preliminary_observation_count'][0]==0
    assert result.factors['sue_prelim'][0] is None


def test_repeated_source_keeps_first_seen_but_distinct_revisions_stay_distinct(tmp_path):
    publish(tmp_path,'forecast',net_profit_min=100.,net_profit_max=200.)
    publish(tmp_path,'forecast',snapshot='repeat',seen=NOW+dt.timedelta(days=1),net_profit_min=100.,net_profit_max=200.)
    publish(tmp_path,'forecast',snapshot='revision',identifier='revised',seen=NOW+dt.timedelta(days=1),net_profit_min=120.,net_profit_max=220.)
    history=read_preliminary_history(tmp_path,known_at=NOW+dt.timedelta(days=2))
    assert history.height==2 and history['available_at'].min()==NOW
    original=history.filter(pl.col('source_row_id')=='forecast').row(0,named=True)
    assert original['source_raw_path']=='raw/forecast/one.parquet'


def test_unpublished_invalid_numeric_and_invalid_availability(tmp_path):
    folder=publish(tmp_path,'forecast',net_profit_min='not disclosed',net_profit_max='inf')
    history=read_preliminary_history(tmp_path,known_at=NOW)
    assert history['forecast_profit_min_10000cny'][0] is None and history['forecast_profit_max_10000cny'][0] is None
    (folder.parent/'summary.json').unlink()
    assert read_preliminary_history(tmp_path,known_at=NOW).is_empty()
    with pytest.raises(ValueError,match='timezone-aware'):
        read_preliminary_history(tmp_path,known_at=NOW.replace(tzinfo=None))
    (folder.parent/'summary.json').write_text('{}')
    p=folder/'data.parquet'
    pl.read_parquet(p).with_columns(pl.lit(NOW-dt.timedelta(days=1)).alias('available_at')).write_parquet(p)
    with pytest.raises(ValueError,match='precedes observation'):
        read_preliminary_history(tmp_path,known_at=NOW)


def test_compute_entry_loads_only_the_requested_sue_preliminary_consumer(tmp_path,monkeypatch):
    from quant.factors import compute
    publish(tmp_path,'forecast',net_profit_min=100.,net_profit_max=200.)
    calls=[]
    monkeypatch.setattr(compute,'read_factor_financial_history',lambda *a,**kw:{})
    def attach(panel,histories,names,**kw):
        calls.append(kw['preliminary_history'])
        return panel.with_columns(pl.lit(None,dtype=pl.Float64).alias('sue_prelim'))
    monkeypatch.setattr(compute,'attach_financial_factors',attach)
    date=dt.date(2026,11,6)
    panel=pl.DataFrame({'symbol':['000001.SZ'],'trade_date':[date],'close':[10.]})
    value=compute.attach_expression_inputs(panel,panel,expressions=('sue_prelim',),data_root=tmp_path,
        refresh_config=tmp_path/'unused.toml',sessions=(date,),read_start=date,read_end=date)
    assert len(calls)==1 and calls[0].height==1 and value['sue_prelim'][0] is None
