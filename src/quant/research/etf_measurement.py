"""Frozen ETF attribution, total-return/quote checks and bounded history extension."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import polars as pl

from quant.data.etf_paper_inputs import etf_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.etf_allocation_attribution import frozen_targets
from quant.research.etf_minute_coverage import inspect
from quant.research.joint_account_report import measure
from quant.research.monthly_etf import monthly_targets
from quant.strategies.inverse_volatility import InverseVolatilityStrategy


def quality(bars, prices, dividends, output, read):
    summaries=[];reconstructed=[];cross=[]
    for symbol in sorted(bars['symbol'].unique()):
        b=bars.filter(pl.col('symbol')==symbol).sort('trade_date').to_pandas().set_index('trade_date')
        p=prices.filter(pl.col('symbol')==symbol).sort('trade_date').to_pandas().set_index('trade_date')
        cash=dividends.filter(pl.col('symbol')==symbol).to_pandas().set_index('ex_date').div_cash
        distribution=cash.reindex(b.index,fill_value=0.)
        expected=(b.close+distribution)/b.close.shift(1)-1
        observed=p.adjusted_close.pct_change()
        errors=(expected-observed).abs()
        zero=b.close.diff().eq(0);runs=zero.groupby(zero.ne(zero.shift()).cumsum()).sum()
        invalid=((b.low<=0)|(b.high<b[['open','close']].max(axis=1))|(b.low>b[['open','close']].min(axis=1)))
        vwap=b.amount/b.volume
        summaries.append(dict(symbol=symbol,start=str(b.index.min().date()),end=str(b.index.max().date()),
            rows=len(b),duplicate_dates=int(b.index.duplicated().sum()),missing_return_prices=int(p.adjusted_close.isna().sum()),
            total_return_max_error=float(errors.max()),dividend_events=int((distribution>0).sum()),
            unchanged_close_days=int(zero.sum()),longest_unchanged_run=int(runs.max()),
            unchanged_full_ohlc_days=int(b[['open','high','low','close']].diff().eq(0).all(axis=1).sum()),
            flat_ohlc_days=int(b.high.eq(b.low).sum()),zero_volume_days=int((b.volume<=0).sum()),
            invalid_ohlc_days=int(invalid.sum()),vwap_outside_days=int(((vwap<b.low-.0011)|(vwap>b.high+.0011)).sum()),
            lag1_return_autocorrelation=float(expected.autocorr(1)),daily_return_vol=float(expected.std()),
            median_intraday_range=float(((b.high-b.low)/b.close).median()),
            lot_notional_median=float((100*b.close).median())))
        for date in b.index:
            reconstructed.append(dict(symbol=symbol,date=date.date(),close=b.loc[date,'close'],cash_dividend=distribution.loc[date],
                reconstructed_return=expected.loc[date],published_return=observed.loc[date],absolute_error=errors.loc[date]))
        path=Path(f'data/clean/bar_1d_tdx/source=tdx/market=SH/symbol={symbol}/data.parquet')
        if path.exists():
            other=read(path).to_pandas().set_index('trade_date')
            common=b.index.intersection(other.index);diff=(b.loc[common,'close']-other.loc[common,'close']).abs()
            cross.append(dict(symbol=symbol,tdx_start=str(other.index.min().date()),tdx_end=str(other.index.max().date()),
                matched_days=len(common),maximum_close_difference=float(diff.max()),
                close_differences_over_one_tick=int((diff>.0011).sum()),
                earlier_rows=int((other.index<b.index.min()).sum()),
                earlier_total_return_status='UNVERIFIED_no_published_total_return_or_corporate_action_reconciliation_before_2023'))
    pd.DataFrame(summaries).to_csv(output/'daily_quality.csv',index=False)
    pd.DataFrame(reconstructed).to_csv(output/'total_return_reconstruction.csv',index=False)
    pd.DataFrame(cross).to_csv(output/'daily_source_comparison.csv',index=False)
    if any(r['total_return_max_error']>1e-9 or r['duplicate_dates'] or r['invalid_ohlc_days'] for r in summaries):
        raise ValueError('Published daily total-return/price quality failed')
    return summaries,cross


def account_attribution(folder,bars,dividends,start,end,capital):
    nav=pl.read_parquet(folder/'nav.parquet').filter(pl.col('date').is_between(start,end)).to_pandas().set_index('date')
    fills=pl.read_parquet(folder/'trades.parquet').filter(pl.col('date').is_between(start,end)).to_pandas()
    nav['return']=nav.equity/np.r_[capital,nav.equity.to_numpy()[:-1]]-1
    all_close=bars.to_pandas().pivot(index='trade_date',columns='symbol',values='close').sort_index()
    close=all_close.reindex(nav.index);previous=all_close.shift(1).reindex(nav.index)
    daily=[];totals=[];model_pnl=np.zeros(len(nav))
    for symbol in close.columns:
        t=fills[fills.symbol==symbol].copy();t['signed']=t.quantity*np.where(t.side=='BUY',1,-1)
        signed=t.groupby('date').signed.sum().reindex(nav.index,fill_value=0.)
        quantity=signed.cumsum();oldq=quantity.shift(1).fillna(0.)
        price_pnl=oldq*(close[symbol]-previous[symbol])
        trade_pnl=(t['signed']*(t.date.map(close[symbol])-t.price)).groupby(t.date).sum().reindex(nav.index,fill_value=0.)
        fees=t.groupby('date').fee.sum().reindex(nav.index,fill_value=0.)
        distributions=pd.Series(0.,index=nav.index)
        for e in dividends.filter(pl.col('symbol')==symbol).to_dicts():
            ex=pd.Timestamp(e['ex_date']);record=pd.Timestamp(e['record_date'])
            if ex in nav.index:
                if record not in quantity.index:raise ValueError('Dividend entitlement precedes reconstructed account')
                distributions.loc[ex]+=quantity.loc[record]*e['div_cash']
        net=price_pnl+trade_pnl+distributions-fees;model_pnl+=net.to_numpy()
        totals.append(dict(symbol=symbol,mark_pnl=float(price_pnl.sum()),trade_mark_pnl=float(trade_pnl.sum()),
            dividend_income=float(distributions.sum()),fees=float(fees.sum()),net_pnl=float(net.sum()),
            contribution_pp=float(net.sum()/capital*100),average_actual_weight=float((quantity*close[symbol]/nav.equity).mean()),
            orders=len(t),median_order_notional=float(t.notional.median()),
            order_notional_below_one_lot_at_close=int((t.notional<100*t.date.map(close[symbol])).sum())))
        for date in nav.index:
            daily.append(dict(date=date.date(),symbol=symbol,quantity=float(quantity.loc[date]),
                mark_pnl=float(price_pnl.loc[date]),trade_mark_pnl=float(trade_pnl.loc[date]),
                dividend_income=float(distributions.loc[date]),fees=float(fees.loc[date]),net_pnl=float(net.loc[date])))
    actual=nav.equity-np.r_[capital,nav.equity.to_numpy()[:-1]]
    error=float(np.max(np.abs(model_pnl-actual)))
    if error>1e-6:raise ValueError(f'Attribution does not reconcile: {folder} {error}')
    return nav,totals,daily,error


def run(config,output,reuse_daily=None):
    spec=tomllib.loads(config.read_text());source=Path(spec['source'])
    if spec['auto_trade'] is not False:raise ValueError('Manual research only')
    output.mkdir(parents=True,exist_ok=False);(output/'config.toml').write_bytes(config.read_bytes());hashes={}
    def capture(p):hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return p
    def read(p):return pl.read_parquet(capture(p))
    history = Path(spec['history_inputs']) if spec.get('history_inputs') else source
    history_receipt = None
    if history != source:
        history_receipt = json.loads(capture(history/'receipt.json').read_text(encoding='utf-8'))
        if history_receipt.get('auto_trade') is not False or history_receipt.get('classification') != 'RESEARCH_ONLY':
            raise ValueError('Invalid extended history receipt')
        for filename, digest in history_receipt['source_hashes'].items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
                raise ValueError(f'Extended history source changed: {filename}')
    frames={name:read(history/f'{name}.parquet') for name in ['bars','prices','calendar','instruments','dividends']}
    bars,prices,calendar,dividends=[frames[n] for n in ['bars','prices','calendar','dividends']]
    quality_rows,cross=quality(bars,prices,dividends,output,read)
    if history_receipt:
        for row in cross:
            row['earlier_total_return_status'] = 'action_evidence_reconciled_early_bond_gold_daily_price_independence_unverified'
        pd.DataFrame(cross).to_csv(output/'daily_source_comparison.csv',index=False)
    names=tuple(sorted(bars['symbol'].unique()));strategy=InverseVolatilityStrategy(names,60,name='dynamic')
    # Verify saved dynamic targets from the immutable daily total-return input.
    regenerated=monthly_targets(prices,calendar,start=spec['common_start'],end=spec['end'],candidates=names,name='dynamic',strategy=strategy)
    saved=read(source/'dynamic_1/targets.parquet').filter(pl.col('execution_date')<=spec['end'])
    delta=regenerated.join(saved,on=['as_of','execution_date','symbol'],suffix='_saved')
    error=float((delta['weight']-delta['weight_saved']).abs().max())
    if delta.height!=saved.height or error>1e-12:raise ValueError('Frozen dynamic signal drift')
    minute,minute_hashes=inspect(output,source,names,regenerated['execution_date'].unique().sort().to_list(),spec['end'])
    hashes.update(minute_hashes)
    settings=tomllib.loads(capture(Path('configs/research/b16_cross_asset_inverse_volatility60_20260909.toml')).read_text())
    settings['portfolio']['initial_cash']=spec['capital']
    if history_receipt:
        if spec.get('historical_cost_policy') != 'unchanged_fixed_cost_sensitivity_not_verified_historical_broker_fees':
            raise ValueError('Earlier ETF history requires an explicit fixed-cost assumption')
        # Extend the *same assumed fee amounts* in all three cost scenarios.
        # This does not claim a historical broker tariff or change live costs.
        settings['costs']['etf']['effective_from'] = bars['trade_date'].min()
    if reuse_daily is not None:
        previous=tomllib.loads((reuse_daily/'config.toml').read_text())
        for field in ['capital','source','common_start','end','cost_multipliers','extension','fixed_extension','history_inputs','historical_cost_policy']:
            if previous.get(field)!=spec.get(field):raise ValueError('Cannot reuse different daily experiment')
        prior_manifest=json.loads((reuse_daily/'manifest.json').read_text())
    sessions=calendar.filter((pl.col('market')=='SH')&pl.col('is_open'))['date'].sort().to_list()
    available=sorted(set(bars['trade_date']))
    starts=[day for prior,day in zip(sessions,sessions[1:]) if prior.month!=day.month and
        day<=spec['end'] and prior in available and sum(d<=prior for d in available)>=61]
    extension_start=min(starts)
    dynamic=monthly_targets(prices,calendar,start=extension_start,end=spec['end'],candidates=names,name='dynamic',strategy=strategy)
    fixed,_=frozen_targets(dynamic)
    extended_sessions=[d for d in sessions if extension_start<=d<=spec['end']]
    capture(config)
    for p in [Path(__file__),Path('src/quant/research/etf_minute_coverage.py'),Path('src/quant/research/classic_monthly_baseline.py'),
              Path('src/quant/research/monthly_etf.py'),Path('src/quant/strategies/inverse_volatility.py'),
              Path('src/quant/backtest/daily_account.py'),Path('src/quant/backtest/daily_simulator.py')]:capture(p)
    (output/'manifest.json').write_text(json.dumps(hashes,indent=2))
    cases=[]
    for cost in spec['cost_multipliers']:
        scenario=copy.deepcopy(settings)
        for field in ['commission_rate','commission_min','slippage','slippage_per_share']:scenario['costs']['etf'][field]*=cost
        states=etf_session_states(bars,dividends,slippage=0.,slippage_per_share=.001*cost)
        for name,targets in [('dynamic',dynamic),('fixed',fixed)]:
            folder=output/f'extended_{name}_{cost:g}'
            if reuse_daily is not None:
                prior=reuse_daily/folder.name
                for label in ['nav','trades']:
                    p=prior/f'{label}.parquet'
                    if prior_manifest[str(p)]!=hashlib.sha256(p.read_bytes()).hexdigest():raise ValueError('Daily reuse checksum changed')
                    capture(p)
                shutil.copytree(prior,folder)
            else:
                folder.mkdir()
                nav,trades,rejects=replay(bars=bars,calendar=calendar,instruments=frames['instruments'],
                    targets=targets.with_columns(pl.lit(name).alias('strategy')),dividends=dividends,market_states=states,
                    config=scenario,sessions=extended_sessions,name=name,validate_once=True)
                for label,frame in [('nav',nav),('trades',trades),('rejections',rejects),('targets',targets)]:frame.write_parquet(folder/f'{label}.parquet')
            cases.extend([dict(scope='extended',rule=name,cost=cost,start=extension_start,folder=folder),
                          dict(scope='common',rule=name,cost=cost,start=spec['common_start'],folder=source/f'{name}_{cost:g}')])
            print(f'complete extended {name} {cost}x',flush=True)
    summaries=[];attribution=[];periods=[];events=[];daily=[];navs={};verifications=[]
    market_path=Path('artifacts/research/market_indicators_20260922_02/market_states.parquet')
    market=read(market_path).to_pandas().set_index('effective_date').market_state
    for case in cases:
        for label in ['nav','trades']:capture(case['folder']/f'{label}.parquet')
        nav,assets,flows,err=account_attribution(case['folder'],bars,dividends,case['start'],spec['end'],spec['capital'])
        key={k:case[k] for k in ['scope','rule','cost']};navs[tuple(key.values())]=nav
        summaries.append(dict(**key,start=str(case['start']),end=str(spec['end']),**measure(nav['return']),
            cagr=(nav.equity.iloc[-1]/spec['capital'])**(252/len(nav))-1,
            mean_cash_weight=float((nav.cash/nav.equity).mean())))
        attribution.extend(dict(**key,**r) for r in assets);daily.extend(dict(**key,**r) for r in flows)
        verifications.append(dict(**key,attribution_equity_max_error=err,nonnegative_cash=bool((nav.cash>=0).all())))
    for case in cases:
        scope,name,cost=case['scope'],case['rule'],case['cost'];key=dict(scope=scope,rule=name,cost=cost)
        nav=navs[scope,name,cost];control=navs[scope,'fixed',cost]
        for kind,labels in [('year',nav.index.strftime('%Y')),('month',nav.index.strftime('%Y-%m'))]:
            for period,part in nav.groupby(labels):
                m=measure(part['return']);baseline=measure(control.loc[part.index,'return'])
                periods.append(dict(**key,kind=kind,period=period,**m,benchmark_return=baseline['net_return'],
                    excess_pp=100*(m['net_return']-baseline['net_return'])))
        for _,segment in market.groupby(market.ne(market.shift()).cumsum()):
            if not segment.index.isin(nav.index).all():continue
            part=nav.loc[segment.index];applicable=bool((part.market_value>0).any())
            events.append(dict(**key,state=segment.iloc[0],start=str(segment.index[0].date()),end=str(segment.index[-1].date()),
                applicable=applicable,**(measure(part['return']) if applicable else dict(net_return=None)),
                benchmark_return=measure(control.loc[segment.index,'return'])['net_return']))
    for filename,rows in [('comparison',summaries),('asset_attribution',attribution),('daily_attribution',daily),
                           ('annual_monthly',periods),('continuous_events',events)]:pd.DataFrame(rows).to_csv(output/f'{filename}.csv',index=False)
    result=dict(classification='RESEARCH_ONLY',auto_trade=False,results=summaries,quality=quality_rows,
        minute_execution=minute,target_reconstruction_error=error,
        historical_cost_policy=spec.get('historical_cost_policy'),
        longer_history=history_receipt or 'Published validated inputs extend from 2023; older TDX closes exist but total-return/corporate-action reconciliation not established',
        B16_forward_unchanged=True,limitations=['Already seen development history, not independent OOS.',
            'Low close-return volatility alone does not prove liquid executable prices.',
            'No full-window price extremes used to generate signals or quantities.',
            'No parameter, pool, ratio or market-state search.'])
    (output/'summary.json').write_text(json.dumps(result,indent=2))
    (output/'verification.json').write_text(json.dumps(verifications,indent=2))
    (output/'manifest.json').write_text(json.dumps(hashes,indent=2))
    table=pd.DataFrame(summaries)[['scope','rule','cost','sessions','net_return','cagr','sharpe_rf0','sharpe_rf2','max_drawdown']]
    (output/'report.md').write_text('# 独立ETF测量与执行覆盖\n\n机器生成。10万元，原三ETF/60日逆波动规则与事前静态向量；645日统一区间及按可得历史机械扩展。\n\n'
        +table.to_markdown(index=False)+'\n\n## 收益和数据\n\n'
        'asset_attribution.csv将股票ETF、债券ETF、黄金ETF的实际价格损益、成交至收盘损益、分红和费用逐日相加，与账户净值变动核对。'
        '它是会计贡献，不是独立alpha；动态减静态也包含真实仓位、整手和费用交互。\n\n'
        'daily_quality.csv、total_return_reconstruction.csv核对现金分红总收益、重复/缺失/零成交、平价和自相关；daily_source_comparison.csv比较已有TDX日线。'
        + ('本次机械延伸已消费独立公司行动证据，来源、哈希和剩余限制见输入receipt.json；债券及黄金ETF早期日价尚无逐日独立报价复核。\n\n' if history_receipt else
        '旧TDX日线更长，但2023年前复权/公司行动未与合格总收益序列核对，未把裸价格当总收益。\n\n') +
        '年度/月度及静态基准超额见annual_monthly.csv，完整连续压力段见continuous_events.csv。rf2为年有效2%逐日扣除。\n\n'
        '## 人工延迟覆盖\n\n'+json.dumps(minute,ensure_ascii=False,indent=2)+'\n\n'
        '1/3分钟均在同一09:30–09:35窗口内，保守极值法不能分辨二者，不声称精确成交。'
        '不足覆盖时没有生成645日延迟净值，也没有以局部分钟数据替代全期；minute_gaps.csv留给现有补数流程，未新开采集。'
        'B16既定前向日程不变，当前不能升级准入。\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=Path('configs/research/etf_measurement_execution_v1.toml'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--reuse-daily',type=Path)
    a=p.parse_args();run(a.config,a.output,a.reuse_daily)
