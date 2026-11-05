"""Actual published D1 table observations; year presence is not vintage proof."""
from pathlib import Path

import polars as pl


def fund_daily_grid(frame,*,symbols,start,end,data_root):
    expected=[]
    for symbol in symbols:
        calendar_path=data_root/f'clean/trade_calendar/market={symbol[-2:]}/data.parquet'
        if not calendar_path.is_file():return {'calendar_complete':False,'daily_grid_complete':False}
        calendar=pl.read_parquet(calendar_path)
        if calendar.is_empty() or calendar['date'].min()>start or calendar['date'].max()<end:
            return {'calendar_complete':False,'daily_grid_complete':False}
        window=calendar.filter(pl.col('date').is_between(start,end))
        if (window.height!=(end-start).days+1 or window['date'].n_unique()!=window.height
                or window['is_open'].null_count()):
            return {'calendar_complete':False,'daily_grid_complete':False}
        dates=calendar.filter(pl.col('is_open')&pl.col('date').is_between(start,end))['date']
        expected.extend((symbol,date) for date in dates)
    keys=['ts_code','_date']
    grid=pl.DataFrame(expected,schema={'ts_code':pl.String,'_date':pl.Date},orient='row')
    observations=frame.select(*keys,pl.col('fd_share').cast(pl.Float64,strict=False)).collect()
    invalid=observations.filter(pl.col('fd_share').is_null()|~pl.col('fd_share').is_finite()|(pl.col('fd_share')<=0)).height
    actual=observations.select(keys).unique()
    missing=grid.join(actual,on=keys,how='anti')
    unexpected=actual.join(grid,on=keys,how='anti')
    duplicate=observations.height-actual.height
    return {'calendar_complete':True,'expected_symbol_days':grid.height,'observed_symbol_days':actual.height,
        'missing_symbol_days':missing.height,'missing_examples':[{**r,'_date':str(r['_date'])} for r in missing.head(10).to_dicts()],
        'unexpected_symbol_days':unexpected.height,'duplicate_symbol_days':duplicate,'invalid_share_rows':invalid,
        'daily_grid_complete':not (missing.height or unexpected.height or duplicate or invalid)}


def describe_table(table,record,rule,*,start,end,data_root=Path('data')):
    folder=Path(record['clean_path']).resolve()
    if not folder.is_relative_to((data_root/'clean'/table).resolve()):
        raise ValueError('Published structured table escapes its registered data directory')
    files=sorted(folder.glob('year=*/data.parquet'))
    if not (folder/'summary.json').is_file() or not files:
        return {'published':False,'declared_metadata_matches':False,'reason':'Published files missing'}
    frame=pl.scan_parquet(files)
    date=pl.col(rule['date_field'])
    if frame.collect_schema()[rule['date_field']]==pl.String:date=date.str.to_date('%Y%m%d',strict=False)
    frame=frame.with_columns(date.cast(pl.Date).alias('_date'))
    values=frame.select(pl.len().alias('rows'),pl.col('_date').min().alias('first_date'),
        pl.col('_date').max().alias('last_date'),pl.col('ts_code').n_unique().alias('symbols'),
        pl.col('available_at').null_count().alias('null_available_at'),pl.col('_date').null_count().alias('invalid_dates'),
        (~pl.col('_date').is_between(start,end)).sum().alias('dates_outside_request'),
        (pl.col('available_at')<pl.col('observed_at')).sum().alias('availability_before_observation')).collect().row(0,named=True)
    years=frame.group_by(pl.col('_date').dt.year().alias('year')).len().collect().sort('year')
    year_counts={str(r['year']):r['len'] for r in years.to_dicts() if r['year'] is not None}
    actual={**values,'first_date':str(values['first_date']) if values['first_date'] else None,
        'last_date':str(values['last_date']) if values['last_date'] else None,'years':sorted(map(int,year_counts))}
    fields=('rows','first_date','last_date','symbols','null_available_at','years')
    matches=all(record.get(key)==actual[key] for key in fields) and record.get('date_field')==rule['date_field']
    result={'published':True,**actual,'yearly_rows':year_counts,
        'missing_requested_years':sorted(set(range(start.year,end.year+1))-set(actual['years'])),
        'declared_metadata_matches':matches,'date_field':rule['date_field'],
        'historical_vintage_verified':False,'scope':'Actual stored observations; complete request execution remains a separate collector receipt'}
    if table=='fund_share':
        result['daily_grid']=fund_daily_grid(frame,symbols=rule['symbols'],start=start,end=end,data_root=data_root)
    return result
