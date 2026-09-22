"""Reconcile fixed-fill minute P&L; not a counterfactual zero-cost account."""
import json
import math
import tomllib

import polars as pl


def decompose(trade, buy_open, sell_open):
    qty = trade['quantity']
    interval_move = qty*(sell_open-buy_open)
    executed_move = qty*(trade['sell_price']-trade['buy_price'])
    adverse_pricing = interval_move-executed_move
    fees = executed_move-trade['pnl']
    if fees < -1e-7:
        raise ValueError('Negative inferred fees: replay does not reconcile')
    assert math.isclose(interval_move-adverse_pricing-fees, trade['pnl'], abs_tol=1e-7)
    return dict(interval_open_move=interval_move, adverse_pricing_and_slippage=adverse_pricing,
                commissions=fees, net_pnl=trade['pnl'])


def diagnose(attempt, snapshot):
    cfg = tomllib.loads((snapshot/'config.toml').read_text(encoding='utf-8'))
    freq = '5m' if cfg.get('execution_model') == 'next_5m_worst' else '1m'
    bars = pl.read_parquet(snapshot/f"data/clean/bar_intraday/freq={freq}/source={cfg['source']}/symbol={cfg['symbol']}/data.parquet")
    opens = {str(r['bar_start']): r['open'] for r in bars.iter_rows(named=True)}
    trades_path = attempt/'daily_replay.csv'
    details = []
    if trades_path.exists():
        trades = pl.read_csv(trades_path).filter(pl.col('quantity')>0)
        for row in trades.iter_rows(named=True):
            details.append(dict(date=row['date'],delay=row['manual_delay_seconds'],cost=row['cost'],
                                **decompose(row, opens[row['entry']], opens[row['exit']])))
    summaries=[]
    for delay in cfg['manual_delays_seconds']:
        for cost in cfg['cost_multipliers']:
            group=[r for r in details if r['delay']==delay and r['cost']==cost]
            summaries.append(dict(delay=delay,cost=cost,trades=len(group),
                **{k:sum(r[k] for r in group) if group else None for k in
                   ('interval_open_move','adverse_pricing_and_slippage','commissions','net_pnl')}))
    positive = bars.filter(pl.col('volume')>0)
    ratio = positive.select((pl.col('amount')/pl.col('volume')/pl.col('close')).alias('ratio'))['ratio']
    result=dict(summaries=summaries, source=cfg['source'],symbol=cfg['symbol'],
                amount_volume_close_ratio={str(q):ratio.quantile(q) for q in (.1,.5,.9)},
                limitation='Additive reconciliation for saved quantities only; not zero-cost NAV or causal attribution. Full-window extrema/volume do not establish executable fills.')
    (attempt/'pnl_diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (attempt/'pnl_diagnosis.md').write_text('# 分钟盈亏分解\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    return result
