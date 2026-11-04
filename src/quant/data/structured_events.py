"""D1 four preregistered tables: bounded raw receipts and conservative availability."""
import argparse
import calendar
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import tomllib

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def chunks(start,end,kind):
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
    row_ids=[hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
        for row in frame.iter_rows(named=True)]
    result=frame.with_columns(pl.Series('source_row_id',row_ids),
        pl.col(rule['announcement_field']).str.to_date('%Y%m%d').alias('source_announcement_date'),
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
    if set(spec['tables'])!={'repurchase','stk_holdertrade','share_float','fund_share'}:
        raise ValueError('Require the four registered structured tables')
    if output.exists() and not resume:
        raise FileExistsError('Explicit resume required')
    output.mkdir(parents=True,exist_ok=True)
    summary=output/'summary.json'
    receipt=json.loads(summary.read_text()) if summary.exists() else {'requests':{},'tables':{}}
    digest=hashlib.sha256(config.read_bytes()).hexdigest()
    if receipt.get('config_sha256',digest)!=digest:
        raise ValueError('Frozen structured-table request changed')
    receipt.update(config_sha256=digest,status='running',auto_trade=False)
    def save():
        temporary=summary.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
        temporary.replace(summary)
    (output/'config.toml').write_bytes(config.read_bytes())
    save()
    client,store=connector or TushareConnector(),RawStore(Path('data/raw'))
    try:
        for table,rule in spec['tables'].items():
            if table in receipt['tables']:
                continue
            frames=[]
            for symbol in rule.get('symbols',[None]):
                for first,last in chunks(spec['start'],spec['end'],rule['chunk']):
                    offset=0
                    page_hashes=set()
                    while True:
                        key=f'{table}/{symbol or "all"}/{first}/{last}/{offset}'
                        record=receipt['requests'].get(key)
                        if record:
                            path=Path(record['raw_path'])
                            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
                                raise ValueError('Immutable raw checksum mismatch')
                            frame=pl.read_parquet(path)
                        else:
                            params={'start_date':first.strftime('%Y%m%d'),'end_date':last.strftime('%Y%m%d'),
                                'limit':str(spec['page_size']),'offset':str(offset)}
                            if symbol:
                                params['ts_code']=symbol
                            frame=client.query_raw(table,**params)
                            raw=store.write(source='tushare',table=table,frame=frame,
                                parameters={**params,'consumer':spec['id']})
                            record={'raw_path':str(raw.data_path),'sha256':raw.checksum_sha256,
                                'rows':frame.height,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
                            receipt['requests'][key]=record
                            receipt['current']=key
                            save()
                            print(json.dumps({'table':table,'start':str(first),'offset':offset,'rows':frame.height}),flush=True)
                            time.sleep(spec['request_pause_seconds'])
                        if frame.height>spec['page_size']:
                            raise ValueError('Supplier ignored bounded page size')
                        if frame.height:
                            dates=frame[rule['date_field']].str.to_date('%Y%m%d')
                            if dates.null_count() or dates.min()<first or dates.max()>last:
                                raise ValueError('Supplier response outside frozen date shard')
                            if symbol and set(frame['ts_code'])!={symbol}:
                                raise ValueError('Supplier symbol scope mismatch')
                            fingerprint=record['sha256']
                            if fingerprint in page_hashes:
                                raise ValueError('Repeated page; pagination completeness is unknown')
                            page_hashes.add(fingerprint)
                            frames.append(normalize(frame,table=table,rule=rule,observed_at=record['observed_at'],raw_path=record['raw_path']))
                        if frame.height<spec['page_size']:
                            break
                        offset+=frame.height
            if not frames:
                raise ValueError(f'No historical rows for {table}')
            full=pl.concat(frames,how='diagonal_relaxed').unique('source_row_id',keep='first',maintain_order=True)
            directory=Path('data/clean')/table/f'snapshot={output.name}'
            if directory.exists():
                raise FileExistsError('Refuse to overwrite a published clean snapshot')
            staging=output/f'clean_{table}'
            staging.mkdir(exist_ok=True)
            years=full.with_columns(pl.col(rule['date_field']).str.to_date('%Y%m%d').dt.year().alias('_year'))
            for (year,),part in years.partition_by('_year',as_dict=True).items():
                folder=staging/f'year={year}';folder.mkdir(exist_ok=True)
                part.drop('_year').write_parquet(folder/'data.parquet')
            dates=full[rule['date_field']].str.to_date('%Y%m%d')
            record={'rows':full.height,'first_date':str(dates.min()),'last_date':str(dates.max()),
                'symbols':full['ts_code'].n_unique(),'years':sorted(years['_year'].unique()),'date_field':rule['date_field'],
                'consumer':rule['consumer'],'clean_path':str(directory),'available_at_policy':spec['availability'],
                'null_available_at':full['available_at'].null_count()}
            (staging/'summary.json').write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding='utf-8')
            if not directory.resolve().is_relative_to(Path('data/clean').resolve()):
                raise ValueError('Clean publication escapes the intended workspace data directory')
            directory.parent.mkdir(parents=True,exist_ok=True)
            staging.rename(directory)
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
