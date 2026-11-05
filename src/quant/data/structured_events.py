"""D1 registered table profiles: bounded raw receipts and conservative availability."""
import argparse
import calendar
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore,publish_directory
from quant.data.realtime_store import atomic_json
from quant.data.structured_event_pages import pages
from quant.data.structured_native_rows import native_row_id,split_native_rows


def chunks(start,end,kind):
    if kind=='all':
        yield start,end
        return
    if kind not in ('month','year'):
        raise ValueError('Unknown registered date chunk')
    first=start
    while first<=end:
        last=min(end,dt.date(first.year,12,31) if kind=='year' else
            dt.date(first.year,first.month,calendar.monthrange(first.year,first.month)[1]))
        yield first,last
        first=last+dt.timedelta(days=1)


def normalize(frame,*,table,rule,observed_at,raw_path):
    if frame.is_empty():
        return frame
    if not {'ts_code',rule['date_field'],rule['announcement_field']}.issubset(frame.columns):
        raise ValueError('Missing structured-table identity/availability fields')
    row_ids=[native_row_id(row) for row in frame.iter_rows(named=True)]
    result=frame.with_columns(pl.Series('source_row_id',row_ids),
        pl.col(rule['announcement_field']).str.strip_chars().str.to_date('%Y%m%d').alias('source_announcement_date'),
        pl.lit(observed_at).str.to_datetime(time_zone='UTC').alias('observed_at'),
        pl.lit(raw_path).alias('source_raw_path'),pl.lit(table).alias('source_table'))
    result=result.with_columns((pl.col('source_announcement_date').cast(pl.Datetime('us'))
        .dt.replace_time_zone('Asia/Shanghai').dt.offset_by('1d').dt.convert_time_zone('UTC'))
        .alias('announcement_available_at'))
    return result.with_columns(pl.max_horizontal('announcement_available_at','observed_at').alias('available_at'),
        pl.when(pl.col('source_announcement_date').is_null()).then(pl.lit('announcement_unknown_first_observed_only'))
        .otherwise(pl.lit('current_supplier_history_original_vintage_unverified')).alias('vintage_status'))


def run(*,config,output,resume=False,connector=None):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['evaluate_factors'] is not False:
        raise ValueError('This capture must not trade or evaluate new factors')
    profiles={'structured_events_v1':{'repurchase','stk_holdertrade','share_float','fund_share'},
        'structured_events_remaining_v1':{'forecast','express','stk_holdernumber','margin_detail'}}
    if set(spec['tables'])!=profiles.get(spec['id']):
        raise ValueError('Require one exact preregistered structured-table profile')
    if output.exists() and not resume:
        raise FileExistsError('Explicit resume required')
    output.mkdir(parents=True,exist_ok=True)
    summary=output/'summary.json'
    receipt=json.loads(summary.read_text()) if summary.exists() else {'requests':{},'tables':{}}
    digest=hashlib.sha256(config.read_bytes()).hexdigest()
    if receipt.get('config_sha256',digest)!=digest:
        raise ValueError('Frozen structured-table request changed')
    receipt.update(config_sha256=digest,status='running',auto_trade=False)
    receipt.pop('error_type',None)
    def save():
        atomic_json(summary,receipt)
    (output/'config.toml').write_bytes(config.read_bytes())
    save()
    client,store=connector or TushareConnector(),RawStore(Path('data/raw'))
    try:
        from quant.data.structured_symbol_recovery import load_symbol_recovery
        from quant.data.structured_parameter_recovery import load_parameter_recovery,parameter_pages
        symbol_recovery=load_symbol_recovery(output,receipt)
        parameter_recovery=load_parameter_recovery(output,receipt,spec,symbol_recovery)
        save()
        for table,rule in spec['tables'].items():
            if table in receipt['tables']:
                continue
            frames=[]
            symbols=rule.get('symbols',[None])
            if rule.get('symbols_file'):
                catalog=Path(rule['symbols_file'])
                if hashlib.sha256(catalog.read_bytes()).hexdigest()!=rule['symbols_sha256']:
                    raise ValueError('Frozen structured capture stock catalog changed')
                symbols=json.loads(catalog.read_text(encoding='utf-8'))['symbols']
                if not symbols or len(symbols)!=len(set(symbols)):
                    raise ValueError('Require a nonempty unique acquisition catalog')
            for symbol in symbols:
                for first,last in chunks(spec['start'],spec['end'],rule['chunk']):
                    recovering=(parameter_recovery and table==parameter_recovery['table']
                        and first==parameter_recovery['first'])
                    if recovering:
                        iterator=parameter_pages(table=table,rule=rule,spec=spec,receipt=receipt,
                            client=client,store=store,save=save,recovery=parameter_recovery)
                    else:
                        iterator=pages(table=table,rule=rule,spec=spec,symbol=symbol,
                            first=first,last=last,receipt=receipt,client=client,store=store,save=save,
                            symbol_recovery=symbol_recovery)
                    for frame,record in iterator:
                        # Pagination has already used the original raw page height.
                        frame,rejected=split_native_rows(table,frame)
                        if not rejected.is_empty():
                            receipt.setdefault('quarantined_native_rows',{})[record['raw_path']]={
                                'table':table,'raw_sha256':record['sha256'],'rows':rejected.height,
                                'reason':'supplier_non_record_marker',
                                'source_row_ids':[native_row_id(r) for r in rejected.iter_rows(named=True)],
                                'native_symbols':rejected['ts_code'].to_list()}
                            save()
                        if not frame.is_empty():
                            frames.append(normalize(frame,table=table,rule=rule,
                                observed_at=record['observed_at'],raw_path=record['raw_path']))
                    if recovering:
                        break
            if not frames:
                raise ValueError(f'No historical rows for {table}')
            full=pl.concat(frames,how='diagonal_relaxed').unique('source_row_id',keep='first',maintain_order=True)
            directory=Path('data/clean')/table/f'snapshot={output.name}'
            if directory.exists():
                raise FileExistsError('Refuse to overwrite a published clean snapshot')
            staging=output/f'clean_{table}'
            staging.mkdir(exist_ok=True)
            years=full.with_columns(pl.col(rule['date_field']).str.strip_chars().str.to_date('%Y%m%d').dt.year().alias('_year'))
            for (year,),part in years.partition_by('_year',as_dict=True).items():
                folder=staging/f'year={year}';folder.mkdir(exist_ok=True)
                part.drop('_year').write_parquet(folder/'data.parquet')
            dates=full[rule['date_field']].str.strip_chars().str.to_date('%Y%m%d')
            record={'rows':full.height,'first_date':str(dates.min()),'last_date':str(dates.max()),
                'symbols':full['ts_code'].n_unique(),'years':sorted(years['_year'].unique()),'date_field':rule['date_field'],
                'consumer':rule['consumer'],'clean_path':str(directory),'available_at_policy':spec['availability'],
                'null_available_at':full['available_at'].null_count()}
            (staging/'summary.json').write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding='utf-8')
            if not directory.resolve().is_relative_to(Path('data/clean').resolve()):
                raise ValueError('Clean publication escapes the intended workspace data directory')
            directory.parent.mkdir(parents=True,exist_ok=True)
            publish_directory(staging,directory,staging_root=output,destination_root=directory.parent)
            receipt['tables'][table]=record
            save()
        receipt['status']='captured'
    except Exception as exc:
        receipt.update(status='stopped',error_type=type(exc).__name__)
        save()
        raise
    save()
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/data/structured_events_v1.toml'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    run(config=args.config,output=args.output,resume=args.resume)
