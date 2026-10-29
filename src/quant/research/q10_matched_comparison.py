"""Compare existing continuous accounts on one investable window, without replay."""
import datetime as dt
import json
import hashlib
import re
import shutil
import tomllib
from pathlib import Path

import polars as pl

from quant.reporting.cycle_stress import path_statistics
from quant.research.factor_battery_cost_report import compare_holding_index, load_cost_history

COSTS = (0.5,1.0,2.0)


def common_window(histories: dict) -> tuple[dt.date,dt.date,pl.Series]:
    if set(histories) != set(COSTS):
        raise ValueError('Matched Q10 comparison requires all three cost levels')
    frames = [frame for pair in histories.values() for frame in pair]
    starts, ends = [], []
    for frame in frames:
        if (frame.is_empty() or not frame['date'].is_sorted()
                or frame['date'].n_unique()!=frame.height or frame['date'].null_count()):
            raise ValueError('Matched comparison requires ordered unique NAV dates')
        first = frame.filter(pl.col('market_value')>0)['date'].min()
        if first is None:
            raise ValueError('Matched comparison not applicable without holding evidence')
        starts.append(first); ends.append(frame['date'][-1])
    start,end = max(starts),min(ends)
    if start>end:
        raise ValueError('No common investable holding window')
    grid = frames[0].filter(pl.col('date').is_between(start,end))['date']
    for frame in frames:
        if not frame.filter(pl.col('date').is_between(start,end))['date'].equals(grid):
            raise ValueError('Matched comparison dates differ; never drop missing sessions')
    if not len(grid) or grid[0]!=start or grid[-1]!=end:
        raise ValueError('Matched comparison endpoints are incomplete')
    return start,end,grid


def compare_histories(histories: dict, benchmarks: dict[str,pl.DataFrame]) -> dict:
    """Keep the preceding wealth anchor and all subsequent cash days."""
    from quant.research.factor_battery_cost_report import REQUIRED_BENCHMARKS
    if set(benchmarks)!=REQUIRED_BENCHMARKS:
        raise ValueError('Require the same three return-index benchmarks')
    start,end,grid = common_window(histories)
    rows = []
    for cost in COSTS:
        treatment,control = histories[cost]
        stats = [path_statistics(nav,start=start,end=end) for nav in (treatment,control)]
        comparisons = []
        for name,index in sorted(benchmarks.items()):
            left=compare_holding_index(treatment,index,start=start,end=end)
            right=compare_holding_index(control,index,start=start,end=end)
            if left['sessions']!=right['sessions'] or left['benchmark_cagr']!=right['benchmark_cagr']:
                raise ValueError('Q10 benchmark comparison windows differ')
            comparisons.append(dict(benchmark=name,benchmark_cagr=left['benchmark_cagr'],
                treatment_excess=left['net_cagr_excess'],q10_excess=right['net_cagr_excess']))
        left_excess=min(row['treatment_excess'] for row in comparisons)
        right_excess=min(row['q10_excess'] for row in comparisons)
        fields=('cagr','sharpe','max_drawdown','total_return','starting_unit_nav','ending_unit_nav')
        rows.append(dict(cost_multiplier=cost,treatment={key:stats[0][key] for key in fields},
            q10={key:stats[1][key] for key in fields},benchmarks=comparisons,
            treatment_excess=left_excess,q10_excess=right_excess,
            vs_q10_excess_pp=(left_excess-right_excess)*100,
            mdd_no_worse=stats[0]['max_drawdown']>=stats[1]['max_drawdown']))
    return dict(measurement='common_investable_window_continuous_nav_v1',start=str(start),end=str(end),
        sessions=len(grid),rows=rows,includes_subsequent_cash=True,
        anchor='Each saved account/index wealth immediately before common start; initial capital only if no prior observation',
        evidence='Retrospective saved NAV comparison; no new OOS, strategy replay, weights or account')


def compare_saved(treatment: Path,control: Path,*,end: dt.date,benchmark_config: Path,data_root: Path) -> dict:
    from quant.data.equal_weight_index import load_return_benchmarks
    histories={cost:(load_cost_history(treatment,'budgeted',cost,end)[0],
                     load_cost_history(control,'budgeted',cost,end)[0]) for cost in COSTS}
    start,_,_=common_window(histories)
    anchors=[frame.filter(pl.col('date')<start)['date'].max()
             for pair in histories.values() for frame in pair]
    known=[day for day in anchors if day is not None]
    if known and len(set(known))!=1:
        raise ValueError('Pre-window account anchor dates differ')
    first=known[0] if known else start
    raw=load_return_benchmarks(config=benchmark_config,data_root=data_root,start=first,end=end)
    benchmarks={('510300_total_return_reference' if name=='510300' else name):frame for name,frame in raw.items()}
    return compare_histories(histories,benchmarks)


def repair_saved(root: Path, *, receipt: Path, data_root: Path) -> dict:
    """Correct comparison fields only, preserving original evidence before writing."""
    if receipt.exists():
        raise ValueError('Use a new correction receipt directory')
    spec=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    control=Path(spec['q10_control'])
    folders=sorted(path.parent for path in root.glob('*/cell_result.json'))
    if not folders:
        raise ValueError('No completed saved cells')
    files=[*(folder/name for folder in folders for name in ('assessment.json','cell_result.json','report.md')),
           root/'summary.json']
    for path in files:
        if not path.is_file():
            raise ValueError(f'Saved correction requires complete artifacts: {path}')
        text=path.read_text(encoding='utf-8')
        if path.suffix == '.json':
            payload=json.loads(text)
            if not isinstance(payload,dict):
                raise ValueError(f'Saved correction requires object artifacts: {path}')
            if path.name == 'assessment.json' and not isinstance(payload.get('assessments',{}).get('budgeted'),dict):
                raise ValueError(f'Saved correction requires budgeted assessment: {path}')
            if path == root/'summary.json':
                rows=payload.get('members',payload.get('rows',[]))
                if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                    raise ValueError('Saved correction requires summary member objects')
    files.extend(path for folder in folders if (path:=folder/'matched_q10_comparison.json').is_file())
    evidence={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
              for base in (root,control) for path in base.glob('**/nav.parquet')}
    results={}
    for folder in folders:
        assessment=json.loads((folder/'assessment.json').read_text(encoding='utf-8'))
        ends={str(row['last_date']) for row in assessment['rows'] if row.get('variant')=='budgeted'}
        if len(ends)!=1:
            raise ValueError('Saved cost assessment end dates differ')
        results[folder.name]=compare_saved(folder,control,end=dt.date.fromisoformat(ends.pop()),
            benchmark_config=folder/'return_benchmarks.toml',data_root=data_root)
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha for path,sha in evidence.items()):
        raise ValueError('Saved NAV changed during comparison')
    receipt.mkdir(parents=True)
    originals={}
    for path in files:
        if path.is_file():
            relative=path.relative_to(root)
            target=receipt/'before'/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            originals[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
    changes=[]
    for folder in folders:
        matched=results[folder.name]
        two=next(row for row in matched['rows'] if row['cost_multiplier']==2.)
        window={key:matched[key] for key in ('start','end','sessions','measurement')}
        for name in ('assessment.json','cell_result.json'):
            path=folder/name
            payload=json.loads(path.read_text(encoding='utf-8'))
            row=payload['assessments']['budgeted'] if name=='assessment.json' else payload
            old=row.get('vs_q10_2x_excess_pp')
            row.update(vs_q10_2x_excess_pp=two['vs_q10_excess_pp'],comparison_window=window)
            path.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
        path=folder/'report.md'
        text=path.read_text(encoding='utf-8')
        text=re.sub(r'(vs Q10 Δpp=)[^ ]+',lambda m:m[1]+str(two['vs_q10_excess_pp']),text)
        text=re.sub(r'(vs Q10 同窗 2× 超额差 = )[^ ]+ pp',
                    lambda m:m[1]+str(two['vs_q10_excess_pp'])+' pp',text)
        text+=f"\n共同可投资窗口：{matched['start']} 至 {matched['end']}，{matched['sessions']}个交易日；三档成本详见 matched_q10_comparison.json。原策略自身窗口指标及结论保留。\n"
        path.write_text(text,encoding='utf-8')
        (folder/'matched_q10_comparison.json').write_text(json.dumps(matched,indent=2),encoding='utf-8')
        changes.append(dict(cell=folder.name,previous_delta_pp=old,delta_pp=two['vs_q10_excess_pp'],**window))
    path=root/'summary.json'
    summary=json.loads(path.read_text(encoding='utf-8'))
    for row in summary.get('members',summary.get('rows',[])):
        key=row.get('id',row.get('cell_id'))
        change=next((item for item in changes if item['cell']==key),None)
        if change:
            row['vs_q10_2x_excess_pp']=change['delta_pp']
            row['comparison_window']={key:change[key] for key in ('start','end','sessions','measurement')}
    path.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha for path,sha in evidence.items()):
        raise ValueError('Saved NAV changed during correction')
    result=dict(root=str(root),changes=changes,original_sha256=originals,nav_sha256=evidence,
                strategy_replayed=False,conclusions_changed=False)
    (receipt/'completed.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
