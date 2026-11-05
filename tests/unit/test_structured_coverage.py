import datetime as dt

import polars as pl

from quant.reporting.structured_coverage import describe_table

START,END=dt.date(2019,1,1),dt.date(2019,1,3)
NOW=dt.datetime(2026,11,5,tzinfo=dt.timezone.utc)


def table(root,table,rows):
    folder=root/f'clean/{table}/snapshot=test/year=2019'
    folder.mkdir(parents=True)
    (folder.parent/'summary.json').write_text('{}')
    pl.from_dicts([{**row,'available_at':NOW,'observed_at':NOW} for row in rows]).write_parquet(folder/'data.parquet')
    return {'clean_path':str(folder.parent),'rows':len(rows),'symbols':len({r['ts_code'] for r in rows}),
        'first_date':'2019-01-02','last_date':'2019-01-03','years':[2019],'null_available_at':0,
        'date_field':'trade_date' if table=='fund_share' else 'ann_date'}


def calendars(root,*,end=END):
    path=root/'clean/trade_calendar/market=SH/data.parquet';path.parent.mkdir(parents=True)
    dates=pl.date_range(START,end,eager=True)
    pl.DataFrame({'date':dates,'is_open':dates!=START}).write_parquet(path)


def test_actual_dates_and_counts_override_declared_metadata(tmp_path):
    record=table(tmp_path,'repurchase',[{'ts_code':'600000.SH','ann_date':'20190102'},
        {'ts_code':'600000.SH','ann_date':'20190103'}])
    record.update(rows=99,first_date='2018-01-01',date_field='incorrect_date_role')
    result=describe_table('repurchase',record,{'date_field':'ann_date'},start=START,end=END,data_root=tmp_path)
    assert result['rows']==2 and result['first_date']=='2019-01-02'
    assert result['yearly_rows']=={'2019':2} and not result['declared_metadata_matches']
    assert not result['historical_vintage_verified']


def test_event_table_does_not_invent_a_daily_event_grid(tmp_path):
    record=table(tmp_path,'repurchase',[{'ts_code':'600000.SH','ann_date':'20190102'}])
    record['last_date']='2019-01-02'
    result=describe_table('repurchase',record,{'date_field':'ann_date'},start=START,end=dt.date(2020,12,31),data_root=tmp_path)
    assert result['declared_metadata_matches'] and result['missing_requested_years']==[2020]
    assert 'daily_grid' not in result


def test_fund_grid_uses_exchange_sessions_and_all_registered_symbols(tmp_path):
    symbols=['510300.SH','510050.SH']
    rows=[{'ts_code':s,'trade_date':d,'fd_share':100.} for s in symbols for d in ('20190102','20190103')]
    record=table(tmp_path,'fund_share',rows);calendars(tmp_path)
    result=describe_table('fund_share',record,{'date_field':'trade_date','symbols':symbols},start=START,end=END,data_root=tmp_path)
    assert result['daily_grid']['daily_grid_complete'] and result['daily_grid']['expected_symbol_days']==4
    path=next((tmp_path/'clean/fund_share').glob('snapshot=*/year=*/data.parquet'))
    pl.read_parquet(path).filter(~((pl.col('ts_code')=='510050.SH')&(pl.col('trade_date')=='20190102'))).write_parquet(path)
    missing=describe_table('fund_share',record,{'date_field':'trade_date','symbols':symbols},start=START,end=END,data_root=tmp_path)
    assert not missing['daily_grid']['daily_grid_complete'] and missing['daily_grid']['missing_symbol_days']==1


def test_incomplete_calendar_and_duplicate_fund_days_cannot_prove_coverage(tmp_path):
    row={'ts_code':'510300.SH','trade_date':'20190102','fd_share':100.}
    record=table(tmp_path,'fund_share',[row,row]);record['last_date']='2019-01-02'
    calendars(tmp_path,end=dt.date(2019,1,2))
    rule={'date_field':'trade_date','symbols':['510300.SH']}
    result=describe_table('fund_share',record,rule,start=START,end=END,data_root=tmp_path)
    assert not result['daily_grid']['calendar_complete']
    path=tmp_path/'clean/trade_calendar/market=SH/data.parquet';path.unlink()
    path.parent.rmdir()
    calendars(tmp_path)
    result=describe_table('fund_share',record,rule,start=START,end=END,data_root=tmp_path)
    assert result['daily_grid']['duplicate_symbol_days']==1 and not result['daily_grid']['daily_grid_complete']


def test_internal_calendar_hole_is_unknown_even_with_correct_endpoints(tmp_path):
    rows=[{'ts_code':'510300.SH','trade_date':'20190103','fd_share':100.}]
    record=table(tmp_path,'fund_share',rows);record['first_date']='2019-01-03'
    calendars(tmp_path)
    path=tmp_path/'clean/trade_calendar/market=SH/data.parquet'
    pl.read_parquet(path).filter(pl.col('date')!=dt.date(2019,1,2)).write_parquet(path)
    result=describe_table('fund_share',record,{'date_field':'trade_date','symbols':['510300.SH']},
        start=START,end=END,data_root=tmp_path)
    assert not result['daily_grid']['calendar_complete'] and not result['daily_grid']['daily_grid_complete']


def test_closed_day_native_record_is_disclosed_but_cannot_fill_missing_session(tmp_path):
    rows=[{'ts_code':'510300.SH','trade_date':d,'fd_share':100.} for d in ('20190101','20190102','20190103')]
    record=table(tmp_path,'fund_share',rows);record['first_date']='2019-01-01'
    calendars(tmp_path)
    rule={'date_field':'trade_date','symbols':['510300.SH']}
    result=describe_table('fund_share',record,rule,start=START,end=END,data_root=tmp_path)['daily_grid']
    assert result['daily_grid_complete'] and result['nontrading_native_symbol_days']==1
    assert result['unexpected_symbol_days']==1 and result['outside_registered_grid']==0
    assert not result['nontrading_values_verified']
    path=next((tmp_path/'clean/fund_share').glob('snapshot=*/year=*/data.parquet'))
    pl.read_parquet(path).filter(pl.col('trade_date')!='20190102').write_parquet(path)
    missing=describe_table('fund_share',record,rule,start=START,end=END,data_root=tmp_path)['daily_grid']
    assert not missing['daily_grid_complete'] and missing['missing_symbol_days']==1
