import datetime as dt
import tomllib
from pathlib import Path

import polars as pl

from quant.portfolio.account_portfolio_v1 import Allocation


def setup(day):
    spec=tomllib.loads(Path('configs/research/account_portfolio_v1.toml').read_text(encoding='utf-8'))
    empty=pl.DataFrame(schema={'date':pl.Date,'stock':pl.Float64,'dividend':pl.Float64,'treasury':pl.Float64})
    allocator=Allocation(variant='fixed_40_30_30',spec=spec,returns=empty,etf_prices=None)
    batch=pl.DataFrame({'as_of':[day],'execution_date':[day+dt.timedelta(days=1)],
        'symbol':['600000.SH'],'weight':[1.],'strategy':['fixture'],'strategy_version':['1']})
    state={'date':str(day),'cash':300000.,'holdings':{},'nav':[{'equity':300000.}]}
    return allocator,batch,state


def test_initial_allocation_reserves_unlisted_leg_without_renormalizing():
    allocator,batch,state=setup(dt.date(2018,12,28))
    result,info=allocator(batch,state)
    assert dict(result.select('symbol','weight').iter_rows())=={
        '600000.SH':.4,'511010.SH':.3}
    assert info['reserved_unlisted_cash']==90000.
    assert state['holdings']=={} and state['nav'][0]['equity']==300000.


def test_nonquarter_etf_quantities_are_fixed_despite_price_drift():
    allocator,batch,state=setup(dt.date(2020,2,28))
    allocator.initialized=True
    state['holdings']={'600000.SH':{'quantity':10000,'mark_price':10.},
        '512890.SH':{'quantity':80000,'mark_price':1.},'511010.SH':{'quantity':1000,'mark_price':100.}}
    result,info=allocator(batch,state)
    assert info['target_share_deltas']=={'512890.SH':0,'511010.SH':0}
    assert not info['quarterly_allocation']
    assert result['weight'].sum()<=1+1e-10


def test_inverse_volatility_uses_no_returns_after_signal():
    allocator,_,_=setup(dt.date(2020,6,30))
    allocator.variant='inverse_volatility60'
    start=dt.date(2020,1,1)
    history=pl.DataFrame({'date':[start+dt.timedelta(days=i) for i in range(61)],
        'stock':[.01*(-1)**i for i in range(61)],
        'dividend':[.005*(-1)**i for i in range(61)],'treasury':[.001*(-1)**i for i in range(61)]})
    allocator.returns=history
    before=allocator.weights(dt.date(2020,6,30))
    allocator.returns=pl.concat([history,pl.DataFrame({'date':[dt.date(2021,1,1)],
        'stock':[1e6],'dividend':[1e6],'treasury':[1e6]})])
    assert allocator.weights(dt.date(2020,6,30))==before
    assert allocator.weights(dt.date(2020,1,2))==[.4,.3,.3]


def test_proxy_cash_reserve_is_net_of_real_shared_account_fees():
    allocator,batch,state=setup(dt.date(2015,2,27))
    allocator.proxy=True
    allocator.initialized=True
    allocator.reserved=90000.
    batch=batch.with_columns(pl.lit('510300.SH').alias('symbol'))
    state.update(cash=89900.,holdings={'510300.SH':{'quantity':10000,'mark_price':12.},
        '511010.SH':{'quantity':900,'mark_price':100.}},nav=[{'equity':299900.}])
    result,info=allocator(batch,state)
    assert allocator.reserved==89900.
    assert result['weight'].sum()<=1.
