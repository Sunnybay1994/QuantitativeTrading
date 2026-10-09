"""Bounded production-input/resume and saved-order checks for opening activation."""
import argparse
import dataclasses
import datetime as dt
import json
from pathlib import Path
import tomllib
from unittest.mock import patch

import polars as pl

from quant.data.monthly_open_inputs import digest, validate_binding
from quant.data.nightly_genetic_inputs import require_execution_coverage
from quant.data.nightly_month_inputs import ensure_nightly_month_inputs, _daily_extensions
from quant.data.stock_execution_inputs import stock_session_states
from quant.research.monthly_open_activation import save


def verify(publication: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    settings = json.loads((publication/'settings.json').read_text(encoding='utf-8'))
    for key in ('history_start','as_of','training_end'):
        if key in settings:
            settings[key] = dt.date.fromisoformat(settings[key])
    as_of = dt.date.fromisoformat(json.loads((publication/'summary.json').read_text())['as_of'])
    root = Path(settings['data_root'])
    new = root/'clean/stock_execution'/settings['execution_snapshot']
    before = json.loads((publication/'source_manifest_after.json').read_text(encoding='utf-8'))
    before.update({str(p):digest(p) for p in new.glob('*') if p.is_file()})
    save(output/'source_manifest_before.json',before)
    def forbidden(*args,**kwargs):
        raise AssertionError('Covered production input path attempted refresh or network')
    with patch('quant.data.nightly_month_inputs.refresh_stocks', forbidden), \
         patch('quant.data.nightly_month_inputs._capture_day', forbidden), \
         patch('quant.data.nightly_month_inputs._extend_returns', forbidden), \
         patch('quant.data.nightly_month_inputs._extend_official', forbidden):
        first = ensure_nightly_month_inputs(settings=settings,as_of=as_of,output=output/'production_inputs')
        second = ensure_nightly_month_inputs(settings=settings,as_of=as_of,output=output/'production_inputs')
        if first != second or first['execution_snapshot'] != new.name:
            raise ValueError('Production resume changed execution source')
    require_execution_coverage(root,new.name,as_of)
    validate_binding(first,root)
    try:
        _daily_extensions(settings,as_of,output/'would_overwrite',new.name)
    except ValueError as exc:
        if 'cannot be overwritten' not in str(exc):
            raise
    else:
        raise AssertionError('Existing monthly target accepted overwrite')
    # Only the three actual saved stock-days are needed. Filter bands before
    # mapping states, so no unrelated account or full-history replay is run.
    previous = Path('artifacts/research/suspension_execution_repair_20261005_01/paired_validation/matched_decision_pairs.json')
    cases = Path('artifacts/research/capital_gains_input_feasibility_20261005_01/suspension_followup/execution_and_eligible_check/afternoon_halt_records.parquet')
    pairs = json.loads(previous.read_text(encoding='utf-8'))
    bars = pl.read_parquet(cases).select('symbol','trade_date','open','volume')
    limits = pl.read_parquet(new/'limits.parquet').join(bars.select('symbol','trade_date'),on=['symbol','trade_date'],how='semi')
    suspensions = pl.read_parquet(new/'suspensions.parquet').join(bars.select('symbol','trade_date'),on=['symbol','trade_date'],how='semi')
    checked=[]
    for row in pairs:
        day,symbol=dt.date.fromisoformat(row['date']),row['symbol']
        selected=bars.filter((pl.col('symbol')==symbol)&(pl.col('trade_date')==day))
        if selected['open'].item()!=row['reference_price']:
            raise ValueError('Saved opening price changed')
        state=stock_session_states(bars=selected,limits=limits,suspensions=suspensions,
            sessions=[day],symbols=[symbol],execution_dates=[day],slippage=row['slippage'])[day,symbol]
        if dataclasses.asdict(state)!=row['new_state']:
            raise ValueError('Monthly extension changed a verified saved-order market check')
        checked.append({'date':str(day),'symbol':symbol,'cost_multiplier':row['cost_multiplier'],
            'state':dataclasses.asdict(state),'saved_source':row['source_path']})
    if len(checked)!=9:
        raise ValueError('Expected exactly nine actual saved rejection pairs')
    save(output/'saved_rejection_pairs.json',checked)
    after={name:digest(Path(name)) for name in before}
    if before!=after:
        raise ValueError('Frozen sources or publication changed during production resume')
    save(output/'source_manifest_after.json',after)
    result={'snapshot':new.name,'production_prepare_and_resume_equal':True,'network_attempts':0,
        'existing_target_overwrite_rejected':True,'frozen_batch_and_old_month_unchanged':True,
        'source_files_checked':len(before),'saved_rejection_pairs_unchanged':len(checked),
        'cost_multipliers':sorted({r['cost_multiplier'] for r in checked}),
        'execution_coverage_check_passed':True,'benchmark_binding_check_passed':True,
        'account_runs':0,'battery_runs':0,'auto_trade':False}
    save(output/'summary.json',result)
    (output/'report.md').write_text('# 月度开盘版生产入口验证\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(verify(**vars(parser.parse_args())),ensure_ascii=False))
