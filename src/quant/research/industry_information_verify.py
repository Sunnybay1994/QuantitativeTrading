"""Verify real production carry against the frozen industry coverage, without a battery."""
import argparse
import datetime as dt
import json
from pathlib import Path
from unittest.mock import patch

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.data.monthly_open_inputs import digest
from quant.factors.compute import attach_expression_inputs
from quant.factors.industry_information import SIGNALS,CONTROL
from quant.research.turnover_reference_family import save


def verify(*,coverage:Path,output:Path,data_root:Path)->dict:
    output.mkdir(parents=True,exist_ok=False)
    refresh=Path('configs/data/refresh_q2_sue_v2_model_20260912.toml')
    low,high,cutoff=dt.date(2025,11,1),dt.date(2026,9,30),dt.date(2026,4,30)
    original=json.loads((coverage/'source_manifest_after.json').read_text(encoding='utf-8'))
    frozen={name:value for name,value in original.items() if Path(name).suffix!='.py'}
    if any(digest(Path(name))!=value for name,value in frozen.items()):
        raise ValueError('Coverage input changed before production verification')
    code=[Path(p) for p in ('src/quant/data/factor_industry_information_inputs.py','src/quant/factors/industry_information.py',
        'src/quant/factors/compute.py','src/quant/research/factor_monthly.py','src/quant/data/refresh_stocks.py')]
    before={**frozen,**{str(p):digest(p) for p in [*code,Path(__file__),coverage/'signals.parquet']}}
    save(output/'source_manifest_before.json',before)
    bars=read_stock_data(data_root=data_root,config=refresh,table='bar_1d',start=low,end=high,
        columns=('symbol','trade_date','close','adj_factor','volume'))
    calendar=available_sessions(data_root,high+dt.timedelta(days=40))
    def attach(frame,end):
        return attach_expression_inputs(frame,frame,expressions=SIGNALS,data_root=data_root,refresh_config=refresh,
            read_start=low,read_end=end,sessions=calendar)
    full=attach(bars,high)
    columns=['symbol','trade_date',*SIGNALS,CONTROL]
    independent=pl.read_parquet(coverage/'signals.parquet').filter(pl.col('trade_date')>=dt.date(2026,1,1)).select(columns)
    independent=independent.join(bars.select('symbol','trade_date'),on=['symbol','trade_date'],how='semi').sort('symbol','trade_date')
    actual=full.select(columns).join(independent.select('symbol','trade_date'),on=['symbol','trade_date'],how='semi').sort('symbol','trade_date')
    if not actual.equals(independent):
        raise ValueError('Production industry month-end values differ from coverage')
    prefix=attach(bars.filter(pl.col('trade_date')<=cutoff),cutoff)
    if not prefix.equals(full.filter(pl.col('trade_date')<=cutoff)):
        raise ValueError('Production industry prefix differs')
    from quant.data import factor_industry_information_inputs as source
    reader=source.read_stock_data
    def disturbed(**kwargs):
        values=reader(**kwargs)
        fields=[c for c in ('close','adj_factor','volume','total_market_value') if c in values.columns]
        return values.with_columns(*[pl.when(pl.col('trade_date')>cutoff).then(pl.col(c)*3.)
            .otherwise(pl.col(c)).alias(c) for c in fields])
    with patch.object(source,'read_stock_data',disturbed):
        changed=attach(bars,high)
    if not changed.filter(pl.col('trade_date')<=cutoff).equals(prefix):
        raise ValueError('Future industry inputs changed earlier production values')
    after={name:digest(Path(name)) for name in before}
    if before!=after:
        raise ValueError('Industry verification source changed')
    actual.write_parquet(output/'production_monthly_values.parquet')
    save(output/'source_manifest_after.json',after)
    result={'production_vs_coverage_rows':actual.height,'prefix_daily_rows':prefix.height,
        'signal_columns':list(SIGNALS),'matched_control':CONTROL,'month_end_values_equal':True,
        'prefix_equal':True,'future_observation_perturbation_equal':True,'source_files_unchanged':len(before),
        'label_data_read':False,'battery_runs':0,'account_runs':0,'auto_trade':False}
    save(output/'summary.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coverage',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    print(json.dumps(verify(**vars(parser.parse_args())),ensure_ascii=False))


if __name__=='__main__':
    main()
