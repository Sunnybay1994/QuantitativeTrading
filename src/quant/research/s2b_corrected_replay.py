"""Revalue fixed S2b rules with issuer actions, dividends and zeroed exits."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.research.few_holdings import momentum_book
from quant.research.s2b_price_audit import reconstruct
from quant.reporting.cycle_stress import path_statistics


def total_return(daily,*,sessions,splits,dividends,nontrading):
    quotes={r['trade_date']:r['close'] for r in daily.iter_rows(named=True)}
    if len(quotes)!=daily.height or not quotes:
        raise ValueError('Require unique nonempty daily quotes')
    rows=[]
    previous=None
    value=1.
    for day in sessions:
        if day<min(quotes):
            continue
        quoted=day in quotes
        if not quoted and day not in nontrading:
            raise ValueError(f'Unverified quote gap: {day}')
        if not quoted and (day in splits or day in dividends):
            raise ValueError('Missing ex-action quote requires explicit valuation')
        close=quotes[day] if quoted else previous
        if close is None or close<=0:
            raise ValueError('Invalid valuation quote')
        if day in splits and day in dividends:
            raise ValueError('Combined cash/split unit basis requires explicit handling')
        gross=1. if previous is None else splits.get(day,1.)*(close+dividends.get(day,0.))/previous
        value*=gross
        rows.append({'trade_date':day,'close':value,'raw_close':close,'gross':gross,
            'quoted':quoted,'tradable':quoted and day not in nontrading})
        previous=close
    return pl.from_dicts(rows)


def dense_targets(weights,pool):
    return weights.select('as_of','execution_date').unique().join(pl.DataFrame({'symbol':pool}),how='cross').join(
        weights,on=['as_of','execution_date','symbol'],how='left').with_columns(pl.col('weight').fill_null(0.)).sort('execution_date','symbol')


def run(*,capture,output,register=False):
    if output.exists():
        raise FileExistsError(output)
    receipt=json.loads((capture/'summary.json').read_text())
    if receipt['status']!='captured':
        raise ValueError('Need complete immutable supplier capture')
    for request in receipt['requests'].values():
        if hashlib.sha256(Path(request['raw_path']).read_bytes()).hexdigest()!=request['sha256']:
            raise ValueError('Captured raw changed')
    spec=tomllib.loads((capture/'config.toml').read_text(encoding='utf-8'))
    rule=spec['s2b']
    events_path=Path('configs/data/s2b_audit_events_v1.toml')
    events=tomllib.loads(events_path.read_text(encoding='utf-8'))
    end=rule['end']
    frames=[]
    audit=[]
    calendar=read_stock_paper_calendar(Path('data'))
    sessions=sorted(calendar.filter(pl.col('is_open')&(pl.col('date')<=end))['date'].unique())
    for symbol in rule['pool']:
        daily=pl.read_parquet(capture/f'{symbol}_fund_daily.parquet').with_columns(
            pl.col('trade_date').str.to_date('%Y%m%d')).filter(pl.col('trade_date')<=end).sort('trade_date')
        dividend=pl.read_parquet(capture/f'{symbol}_fund_div.parquet')
        amounts={}
        if dividend.height:
            dividend=dividend.filter((pl.col('div_proc')=='实施')&pl.col('ex_date').is_not_null())
            for row in dividend.iter_rows(named=True):
                ex=dt.datetime.strptime(row['ex_date'],'%Y%m%d').date()
                if ex>end:
                    continue
                announcement=row['imp_anndate'] or row['ann_date']
                if not announcement or dt.datetime.strptime(announcement,'%Y%m%d').date()>ex:
                    raise ValueError('Unknown dividend before its effective date')
                cash=float(row['div_cash'])
                if cash<0 or (ex in amounts and amounts[ex]!=cash):
                    raise ValueError('Conflicting dividend or unit basis')
                amounts[ex]=cash
        ratios={e['date']:e['ratio'] for e in events['splits'] if e['symbol']==symbol}
        nontrading={d for e in events['nontrading'] if e['symbol']==symbol for d in e['dates']}
        frame=total_return(daily,sessions=sessions,splits=ratios,dividends=amounts,nontrading=nontrading)
        frames.append(frame.with_columns(pl.lit(symbol).alias('symbol')))
        audit.append({'symbol':symbol,'sessions':frame.height,'first':frame['trade_date'].min(),
            'end':frame['trade_date'].max(),'nontrading_valuations':frame.filter(~pl.col('quoted')).height,
            'dividends':len(amounts),'issuer_splits':len(ratios)})
    panel=pl.concat(frames)
    prices=panel.select('symbol','trade_date','close')
    weights=momentum_book(prices,pool=rule['pool'],cash_symbol=rule['cash_symbol'],top_k=rule['top_k'])
    weights=weights.filter(pl.col('execution_date')<=end)
    complete=dense_targets(weights,rule['pool'])
    if complete.group_by('execution_date').agg(pl.col('weight').sum())['weight'].max()>1+1e-9:
        raise ValueError('Unfunded target weight')
    output.mkdir(parents=True,exist_ok=False)
    panel.write_parquet(output/'total_return_prices.parquet')
    weights.write_parquet(output/'weights.parquet')
    complete.write_parquet(output/'dense_targets.parquet')
    sources=[capture/'summary.json',capture/'config.toml',events_path,Path(__file__),
        Path('src/quant/research/few_holdings.py'),Path('src/quant/research/s2b_price_audit.py'),
        *capture.glob('*.parquet')]
    (output/'manifest.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2))
    rows=[]
    comparisons=[]
    previous_nav=None
    for cost in rule['cost_multipliers']:
        positions,daily=reconstruct(prices,complete,cost=rule['one_way_cost']*cost,chronological=True)
        active=positions.group_by('trade_date').agg((pl.col('weight')>0).sum().alias('active_names'))
        daily=daily.join(active,on='trade_date').sort('trade_date')
        if daily['trade_date'][0]!=weights['execution_date'].min() or daily['trade_date'][-1]!=end:
            raise ValueError('Report must cover the complete registered holding interval')
        if previous_nav is not None and (not previous_nav['trade_date'].equals(daily['trade_date'])
                or (previous_nav['unit_nav']+1e-12<daily['unit_nav']).any()):
            raise ValueError('Paired cost date grid or daily NAV monotonicity failed')
        previous_nav=daily
        if daily['exposure'].max()>1+1e-9 or daily['active_names'].max()>rule['top_k']:
            raise ValueError('Corrected proxy violates original Top3 funding')
        folder=output/f'cost_{cost:g}'
        folder.mkdir()
        daily.write_parquet(folder/'nav.parquet')
        positions.write_parquet(folder/'daily_positions.parquet')
        nav=daily.select(pl.col('trade_date').alias('date'),'unit_nav')
        start=nav['date'][0]
        risk=path_statistics(nav,start=start,end=end)
        years=(end-start).days/365.25
        rows.append({'variant':'budgeted','cost_multiplier':cost,**risk,
            'active_start':start,'report_end':end,
            'annualized_one_way_turnover':daily['turnover'].sum()/years,
            'maximum_target_exposure':daily['exposure'].max(),'maximum_selected_names':daily['active_names'].max()})
        for symbol in ('510300.SH','511010.SH'):
            reference=prices.filter(pl.col('symbol')==symbol).select(pl.col('trade_date').alias('date'),pl.col('close').alias('unit_nav'))
            comparisons.append({'variant':'budgeted','cost_multiplier':cost,'benchmark':symbol,
                'benchmark_cagr':path_statistics(reference,start=start,end=end)['cagr']})
    conclusion='REJECTED' if next(r for r in rows if r['cost_multiplier']==2.)['cagr']<=0 else 'RESEARCH_ONLY'
    result={'rows':rows,'assessments':{'budgeted':{'conclusion':conclusion,'net_cagr_excess':None}},
        'benchmark_comparisons':comparisons,'source':'artifacts/research/few_holdings_v1_20261027/s2b_etf_momentum',
        'auto_trade':False,'data_audit':audit,'correction':'issuer splits, cash dividends, zeroed exits, original registered end; pool/formula/Top3/cash rule/cost unchanged',
        'measurement':'Corrected historical target-weight proxy; daily target weights and dividend reinvestment indexes, not an actual-share execution account',
        'limitations':['Original weight-proxy semantics remain; monthly-only turnover costs do not validate implicit daily constant-weight trading',
            'No queue, lot, liquidity, manual-delay or full ETF admission validation; cannot promote to PAPER_CANDIDATE',
            'Issuer per-account fractional-share rounding is not modeled by the total-return index']}
    (output/'assessment.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    (output/'config.toml').write_text('id = "few_holdings_s2b_data_corrected_r3_v1"\nregistered_on = 2026-11-05\nauto_trade = false\n'
        'source_config = "configs/research/few_holdings_v1.toml"\nhistorical_evidence = "data_and_accounting_repair_not_unseen_oos"\n',encoding='utf-8')
    lines=['# S2b 数据与权重账本修复重算','',result['measurement'],'',
        '原−77.125%可精确重建，但混入400%权重及漏算拆并；旧结果保留，不作为可执行Top3证据。',
        '保持原12只ETF、12-1、Top3、债券现金腿、月度信号及三档成本，只修价格公司行动、退出清零和截止日。',
        '', '| 成本 | 年化 | Sharpe | 回撤 | 换手代理 | 最大权重 | 最大名称数 |','|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['cost_multiplier']:g} | {row['cagr']:.2%} | {row['sharpe']:.3f} | {row['max_drawdown']:.2%} | "
            f"{row['annualized_one_way_turnover']:.3f} | {row['maximum_target_exposure']:.0%} | {row['maximum_selected_names']} |")
    lines+=['',f'结论：{conclusion}。']+['- '+text for text in result['limitations']]
    lines+=['','## 原始数据与公告','',f'独立原始响应及校验和：{capture}/summary.json；数据不覆盖raw。']
    lines += [f"- {e['symbol']} {e['date']} 比例{e['ratio']}：[发行人公告]({e['source']})。" for e in events['splits']]
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (output/'summary.json').write_text(json.dumps({'status':'revalued','auto_trade':False,'conclusion':conclusion,'rows':3}),encoding='utf-8')
    if register:
        from quant.reporting.experiment_registry import register_run
        total=register_run(output)
        (output/'registration.json').write_text(json.dumps({'registered_count':1,'registry_total_rows':total}),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--register',action='store_true')
    args=parser.parse_args()
    result=run(capture=args.capture,output=args.output,register=args.register)
    print(json.dumps(result['rows'],default=str))
