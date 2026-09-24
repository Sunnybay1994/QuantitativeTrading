import datetime as dt
from types import SimpleNamespace

import polars as pl
import pytest

from quant.backtest import daily_account, daily_simulator
from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.rules import DailyMarketState
from quant.domain.enums import OrderSide, ExecutionRejectReason
from quant.research.personal_top5_construction import (
    _bind, affordable, fixed_orders, rank_targets, reject,
)

DAY=dt.date(2020,1,31)
NEXT=dt.date(2020,2,3)


def test_rank_ties_eligibility_next_session_and_no_last_day_execution():
    symbols=[f'{i:06}.SZ' for i in range(8)]
    p=pl.DataFrame(dict(symbol=symbols,trade_date=[DAY]*8,lightgbm=[1.]*8))
    u=p.select('symbol','trade_date').with_columns(pl.Series('eligible',[False]+[True]*7))
    t,r=rank_targets(p,u,[DAY,NEXT],NEXT,5,.02)
    assert t['symbol'].to_list()==symbols[1:6]
    assert t['execution_date'].unique().to_list()==[NEXT]
    assert t['weight'].sum()==pytest.approx(.98)
    with pytest.raises(ValueError,match='No executable'):
        rank_targets(p,u,[DAY],DAY,5,.02)


def batch(symbol,weight=.196):
    return pl.DataFrame([dict(as_of=DAY,execution_date=NEXT,symbol=symbol,weight=weight,
        strategy='personal_top5',strategy_version='v1')])


def control(price=10.):
    return dict(close=price,traded=True,limits_known=True,eligible=True,away_from_limits=True,
                down_limit=price*.9,up_limit=price*1.1)


def test_fixed_at_signal_close_old_holding_exit_and_odd_lot():
    state=dict(date=str(DAY),nav=[dict(equity=100000.)],holdings={'000002.SZ':dict(quantity=123,mark_price=10.)})
    trace=[]
    t,info=fixed_orders(batch('000001.SZ'),state,{(DAY,s):control() for s in ('000001.SZ','000002.SZ')},
        {s:dict(board_lot=100) for s in ('000001.SZ','000002.SZ')},trace)
    assert info['target_share_deltas']=={'000001.SZ':1900,'000002.SZ':-123}
    assert t.filter(pl.col('symbol')=='000002.SZ')['weight'][0]==0
    assert trace[0]['lot_shortfall_value']==pytest.approx(600.)
    state['date']=str(NEXT)
    with pytest.raises(ValueError,match='signal-close'):
        fixed_orders(batch('000001.SZ'),state,{}, {},[])


@pytest.mark.parametrize('price,expected',[(100.,0),(90.,217),(10.,1960)])
def test_star_actual_minimum_and_unit_increment(price,expected):
    state=dict(date=str(DAY),nav=[dict(equity=100000.)],holdings={})
    _,info=fixed_orders(batch('688001.SH'),state,{(DAY,'688001.SH'):control(price)},
                       {'688001.SH':dict(board_lot=100)},[])
    assert info['target_share_deltas']['688001.SH']==expected


def test_missing_control_preserves_unsellable_actual_holding():
    state=dict(date=str(DAY),nav=[dict(equity=100000.)],holdings={'000002.SZ':dict(quantity=100,mark_price=10.)})
    _,info=fixed_orders(batch('000001.SZ'),state,{(DAY,'000001.SZ'):control()},
        {s:dict(board_lot=100) for s in ('000001.SZ','000002.SZ')},[])
    assert info['execution_direction_permissions']['000002.SZ']==(False,False)


def costs(floor=1.):
    return AShareCostModel(.00025,floor,.0005,.00001,0.,dt.date(2010,1,1)), EtfCostModel(.00025,floor,0.,dt.date(2010,1,1))


@pytest.mark.parametrize('cash,expected',[(1999.,0),(2001.,0),(2001.02,200),(2171.,216)])
def test_star_cash_cannot_fill_under_minimum(cash,expected):
    stock,etf=costs()
    assert affordable(date=NEXT,symbol='688001.SH',requested=300,lot=1,open_price=10.,cash=cash,
                      instrument_type='STOCK',etf_costs=etf,stock_costs=stock)==expected


def test_star_odd_exit_and_tplusone_still_enforced():
    args=dict(symbol='688001.SH',side=OrderSide.SELL,quantity=150,
        position=SimpleNamespace(quantity=150,settled=150),state=DailyMarketState(),
        instrument_rows={'688001.SH':dict(instrument_type='STOCK')})
    assert reject(**args) is None
    args['position'].settled=0
    assert reject(**args)==ExecutionRejectReason.T_PLUS_ONE
    args['position'].settled=150;args['quantity']=100
    assert reject(**args)==ExecutionRejectReason.LOT_CONSTRAINT


def test_injected_simulation_preserves_existing_engine_and_cash_rules():
    from tests.unit.test_daily_simulator import _calendar,_instruments,_bar,_target,SESSION
    stock,etf=costs()
    kwargs=dict(calendar=_calendar(SESSION),bars=_bar(),scheduled_targets=_target(.98),
        instruments=_instruments(),market_states={(SESSION,'600000.SH'):DailyMarketState()},
        initial_cash=100000.,etf_costs=etf,stock_costs=stock,strategy='m2-u1')
    original=daily_account.simulate_daily_targets
    simulated=_bind(daily_simulator.simulate_daily_targets,_affordable_quantity=affordable,_reject_reason=reject)
    a=original(**kwargs);b=simulated(**kwargs)
    assert a.trades.equals(b.trades) and a.nav.equals(b.nav)
    assert daily_account.simulate_daily_targets is original
    # With STAR lot=1, the dedicated binding rejects a cash-limited subminimum fill.
    kwargs['bars']=kwargs['bars'].with_columns(pl.lit('688001.SH').alias('symbol'))
    kwargs['instruments']=kwargs['instruments'].with_columns(pl.lit('688001.SH').alias('symbol'),pl.lit(1).alias('board_lot'))
    kwargs['scheduled_targets']=kwargs['scheduled_targets'].with_columns(pl.lit('688001.SH').alias('symbol'))
    kwargs['market_states']={(SESSION,'688001.SH'):DailyMarketState()}
    kwargs['initial_cash']=1999.
    kwargs['target_share_deltas']={'688001.SH':300}
    result=simulated(**kwargs)
    assert result.trades.is_empty()
    assert result.rejections['reason'].to_list()==['CASH_CONSTRAINT']


def test_floor_scaling_leaves_statutory_fees_unchanged():
    stock,_=costs(1.)
    doubled=stock.with_execution_cost_multiplier(2.)
    assert stock.fee(1000.,NEXT,'SELL',market='SH',quantity=100)==pytest.approx(1.51)
    assert doubled.fee(1000.,NEXT,'SELL',market='SH',quantity=100)==pytest.approx(2.51)


def test_unselected_future_symbol_needs_no_execution_band():
    from quant.data.stock_execution_inputs import stock_session_states
    from tests.unit.test_daily_simulator import _bar,SESSION
    bars=_bar()
    bands=pl.DataFrame(schema={'trade_date':pl.Date,'symbol':pl.String,'up_limit':pl.Float64,'down_limit':pl.Float64})
    stopped=pl.DataFrame(schema={'trade_date':pl.Date,'symbol':pl.String})
    states=stock_session_states(bars=bars,limits=bands,suspensions=stopped,sessions=[SESSION],
        symbols=['600000.SH'],execution_dates=[],slippage=.001)
    assert not states[SESSION,'600000.SH'].suspended
    with pytest.raises(ValueError,match='Missing stock price band'):
        stock_session_states(bars=bars,limits=bands,suspensions=stopped,sessions=[SESSION],
            symbols=['600000.SH'],execution_dates=[SESSION],slippage=.001)


def test_personal_binding_checkpoint_restores_dividends_and_account(tmp_path):
    from quant.research.personal_top5_construction import personal_replay
    from quant.research.factor_cost_checkpoint import save_year,read_year
    from tests.unit.test_factor_cost_checkpoint import scenario,DAYS
    source=scenario()
    continuous=personal_replay(**source,sessions=DAYS,name='probe',validate_once=True)
    state={}
    split={**source,'targets':source['targets'].filter(pl.col('execution_date')<=DAYS[2])}
    first=personal_replay(**split,sessions=DAYS[:3],name='probe',validate_once=True,account_state=state)
    save_year(tmp_path/'2020',account=state,chunks=first,target_records=[])
    restored,stored=read_year(tmp_path/'2020',dates=DAYS[:3],previous={})
    split['targets']=source['targets'].filter(pl.col('execution_date')>DAYS[2])
    second=personal_replay(**split,sessions=DAYS[3:],name='probe',validate_once=True,account_state=restored)
    for expected,a,b in zip(continuous,stored,second):
        assert expected.equals(pl.concat([a,b],how='vertical_relaxed'))
