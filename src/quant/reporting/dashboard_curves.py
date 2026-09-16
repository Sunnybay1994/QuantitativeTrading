"""Read saved NAV and explicitly typed benchmarks; no backtest or trading writes."""
import hashlib
import json
from pathlib import Path

import polars as pl


def catalog(root: Path) -> list[dict]:
    entries = {}

    def add(label, paths, kind, currency='CNY', basis='成本后账户净值', code=None):
        paths = [p.resolve() for p in paths if p.is_file()]
        if not paths or any(not p.is_relative_to(root.resolve()) for p in paths):
            return
        key = hashlib.sha256(('|'.join(map(str, paths))+'|'+str(code)).encode()).hexdigest()[:20]
        entries[key] = dict(id=key, label=label, kind=kind, currency=currency,
                            basis=basis, code=code, paths=[str(p) for p in paths])

    registry = root/'artifacts/registry/experiments.parquet'
    if registry.exists():
        for r in pl.read_parquet(registry).sort('result_time', descending=True).to_dicts():
            if '/' in r['variant']:
                continue  # Factor scorecards are not strategy NAV sources.
            run = root/r['run_path']
            base = root/r['source_run'] if (run/'cost_metrics.parquet').exists() and r['source_run'] else run
            for cost in ('0.5', '1', '2'):
                folder = base/r['variant']/f'cost_{cost}'
                paths = sorted(folder.glob('????/nav.parquet')) or list(folder.glob('nav.parquet'))
                add(f"{r['experiment_id']} / {r['variant']} · {cost}× · {run.parent.name if run.name.startswith('reports') else run.name}", paths, 'strategy')
    for base in (root/'artifacts/forward/b20', root/'artifacts/forward/b32', root/'artifacts/paper'):
        if not base.exists():
            continue
        # Only known daily account snapshot layout; never traverse archives/raw.
        candidates = list(base.glob('*/????-??-??/nav.csv')) + list(base.glob('*/*/????-??-??/nav.csv'))
        latest = {}
        for p in sorted(candidates):
            latest[p.parent.parent] = p
        for account, p in latest.items():
            add('模拟盘 · '+str(account.relative_to(root/'artifacts')), [p], 'paper')
    indexes = sorted((root/'data/clean/index_benchmarks').glob('*/data.parquet'))
    if indexes:
        p = indexes[-1]
        for r in pl.read_parquet(p).select('index_code','index_name','currency','return_type').unique().sort('index_code').to_dicts():
            name = {'H00905.CSI':'中证500全收益','H00300.CSI':'沪深300全收益'}.get(r['index_code'],r['index_name'])
            add(name+' · '+r['index_code'], [p], 'benchmark', r['currency'],
                '全收益指数' if r['return_type']=='total_return' else '价格指数（不含分红）', r['index_code'])
    manifests = sorted((root/'artifacts/dashboard/benchmarks').glob('*/manifest.json'))
    if manifests:
        for r in json.loads(manifests[-1].read_text(encoding='utf-8'))['series']:
            add(r['name']+' · '+r['code'], [manifests[-1].parent/(r['code']+'.parquet')],
                'benchmark', r['currency'], '价格指数（不含分红、未换汇）', r['code'])
    return list(entries.values())


def read_curve(spec: dict) -> list[dict]:
    frames = []
    for name in spec['paths']:
        p = Path(name)
        d = pl.read_csv(p, try_parse_dates=True) if p.suffix=='.csv' else pl.read_parquet(p)
        if 'index_code' in d.columns:
            d = d.filter(pl.col('index_code')==spec['code']).select(pl.col('trade_date').alias('date'),pl.col('index_level').alias('value'))
        elif 'ts_code' in d.columns:
            d = d.filter(pl.col('ts_code')==spec['code']).select(pl.col('trade_date').str.to_date('%Y%m%d').alias('date'),pl.col('close').alias('value'))
        else:
            d = d.select('date',pl.col('unit_nav').alias('value'))
        frames.append(d.with_columns(pl.col('date').cast(pl.Date),pl.col('value').cast(pl.Float64)))
    d = pl.concat(frames).sort('date')
    if d.is_empty() or d['date'].null_count() or d['date'].is_duplicated().any():
        raise ValueError('净值为空或日期重复，无法可靠拼接')
    if d['value'].null_count() or not d['value'].is_finite().all() or (d['value']<=0).any():
        raise ValueError('净值含缺失、非有限值或非正值')
    return [{'date':str(r['date']),'value':r['value']} for r in d.to_dicts()]


def compare(specs: list[dict], start: str='', end: str='') -> dict:
    if not specs or len(specs)>8:
        raise ValueError('请选择 1–8 条曲线')
    loaded = [(s,read_curve(s)) for s in specs]
    common = set.intersection(*(set(r['date'] for r in rows if (not start or r['date']>=start) and (not end or r['date']<=end)) for _,rows in loaded))
    if len(common)<2:
        raise ValueError('所选曲线在此区间不足两个共同交易日，请调整日期或基准')
    first,last = min(common),max(common)
    series=[]
    for spec,rows in loaded:
        anchor=next(r['value'] for r in rows if r['date']==first)
        points=[dict(date=r['date'],value=r['value']/anchor-1) for r in rows if first<=r['date']<=last]
        series.append({k:spec[k] for k in ('id','label','kind','currency','basis')} | dict(points=points,
                      source=spec['paths'],coverage=[rows[0]['date'],rows[-1]['date']]))
    return dict(start=first,end=last,series=series,
                note='共同起止日归零，按各市场实际交易日期绘制，不前填或补零；跨币种未换汇、收盘时区不同。历史回测包含原记录空仓期，所选区间收益不等同于报告持股期指标。恒科 2020-07-27 发布前数据属于指数历史回溯。')
