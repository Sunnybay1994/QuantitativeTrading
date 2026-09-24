import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.backtest.costs import AShareCostModel
from quant.portfolio.integer_construction import construct


def case():
    day = dt.date(2024, 1, 31)
    names = ['600001.SH','600002.SH','600003.SH']
    raw = pl.DataFrame(dict(as_of=[day]*3, symbol=names, weight=[.02,.02,.02]))
    market = pl.DataFrame([dict(as_of=day,known_at=day,symbol=s,industry_l1='industry'+str(i),
        size=0.,adv20=1e8,can_buy=True,can_sell=True) for i,s in enumerate(names)])
    spec = tomllib.loads(Path('configs/research/joint_integer_v1.toml').read_text())
    costs=AShareCostModel(.00025,5.,.0005,.00001,.001,dt.date(2010,1,1))
    return dict(raw=raw,budgeted=raw,state=dict(date=str(day),nav=[dict(equity=100000.)],holdings={}),
        market=market,prices={s:10. for s in names},instruments={s:dict(board_lot=100) for s in names},
        scores={s:3-i for i,s in enumerate(names)},costs=costs,spec=spec)


def test_fee_hurdle_and_risk_budget_and_no_future_input():
    args=case(); weights,deltas,rows,info=construct(**args)
    assert info['constraints_satisfied']
    assert all(d%100==0 for d in deltas.values())
    assert max(weights.values())<=.03+1e-8
    for row in rows:
        if row['net_order_quantity']:
            assert (row['expected_fee']+row['expected_slippage'])/(abs(row['net_order_quantity'])*10)<=.005+1e-12
    assert max(r['violation'] for r in info['residuals'])<.011
    args['market']=args['market'].with_columns((pl.col('known_at')+dt.timedelta(days=1)).alias('known_at'))
    with pytest.raises(ValueError,match='Future'):construct(**args)


def test_small_exit_exempt_and_missing_price_preserved_not_zero():
    args=case();s='600001.SH'
    args['state']['holdings']={s:dict(quantity=100,mark_price=10.)}
    args['raw']=args['raw'].with_columns(pl.when(pl.col('symbol')==s).then(0.).otherwise(pl.col('weight')).alias('weight'))
    weights,deltas,rows,info=construct(**args)
    assert info['constraints_satisfied'] and deltas[s]==-100 and weights[s]==0
    args['prices'].pop(s)
    weights,deltas,rows,info=construct(**args)
    row=next(r for r in rows if r['symbol']==s)
    assert row['signal_price'] is None and row['valuation_mark']==10
    assert deltas[s]==0 and row['naive_integer_quantity'] is None


def test_unavoidable_risk_violation_freezes_without_relaxing():
    args=case();s='600001.SH';args['state']['holdings']={s:dict(quantity=500,mark_price=10.)}
    args['prices'].pop(s)
    weights,deltas,rows,info=construct(**args)
    assert not info['constraints_satisfied'] and weights[s]==.05
    assert set(deltas.values())=={0}
