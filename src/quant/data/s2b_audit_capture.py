"""Bounded annual supplier receipts for the fixed twelve-ETF S2b data audit."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import tomllib

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore


def run(*,output,resume=False):
    config=Path('configs/research/few_holdings_v1.toml')
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if output.exists() and not resume:
        raise FileExistsError('Explicit resume required')
    output.mkdir(parents=True,exist_ok=True)
    summary=output/'summary.json'
    receipt=json.loads(summary.read_text()) if summary.exists() else {'requests':{}}
    digest=hashlib.sha256(config.read_bytes()).hexdigest()
    if receipt.get('config_sha256',digest)!=digest:
        raise ValueError('Frozen S2b request changed')
    receipt.update(config_sha256=digest,status='running',auto_trade=False,
        purpose='R3 independent raw daily / adjustment / dividend reconciliation, no parameter tuning')
    def save():
        temporary=summary.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        temporary.replace(summary)
    save()
    (output/'config.toml').write_bytes(config.read_bytes())
    connector,store=TushareConnector(),RawStore(Path('data/raw'))
    try:
        for symbol in spec['s2b']['pool']:
            original=Path('data/clean/bar_1d_tdx/source=tdx')/f'market={symbol[-2:]}'/f'symbol={symbol}/data.parquet'
            first=pl.read_parquet(original,columns=['trade_date'])['trade_date'].min()
            for table,fields in [('fund_daily','ts_code,trade_date,open,high,low,close,pre_close,vol,amount'),
                    ('fund_adj','ts_code,trade_date,adj_factor'),
                    ('fund_div','ts_code,ann_date,imp_anndate,record_date,ex_date,pay_date,div_proc,div_cash')]:
                frames=[]
                years=range(first.year,spec['s2b']['end'].year+1) if table!='fund_div' else [0]
                for year in years:
                    key=f'{symbol}/{table}/{year}'
                    prior=receipt['requests'].get(key)
                    if prior:
                        path=Path(prior['raw_path'])
                        if hashlib.sha256(path.read_bytes()).hexdigest()!=prior['sha256']:
                            raise ValueError('Immutable raw checksum mismatch')
                        frame=pl.read_parquet(path)
                    else:
                        params={'symbol':symbol,'fields':fields}
                        if year:
                            params.update(start=max(first,dt.date(year,1,1)),end=min(spec['s2b']['end'],dt.date(year,12,31)))
                        frame=getattr(connector,'fetch_'+table+'_raw')(**params)
                        raw=store.write(source='tushare',table=table,frame=frame,parameters={
                            'ts_code':symbol,'consumer':'r3_s2b_20261104',
                            **{k:str(v) for k,v in params.items() if k!='symbol'}})
                        receipt['requests'][key]={'raw_path':str(raw.data_path),'sha256':raw.checksum_sha256,'rows':frame.height}
                        receipt['current']=key
                        save()
                        print(json.dumps({'request':key,'rows':frame.height}),flush=True)
                        time.sleep(1.1)
                    frames.append(frame)
                pl.concat(frames,how='diagonal_relaxed').write_parquet(output/f'{symbol}_{table}.parquet')
        receipt['status']='captured'
    except Exception as exc:
        receipt.update(status='failed',error_type=type(exc).__name__)
        save()
        raise
    save()
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    run(output=args.output,resume=args.resume)
