import polars as pl
import pytest

from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from tests.unit.test_daily_simulator import (
    SESSION, STOCK, ETF, _calendar, _stock_and_etf_instruments, _stock_and_etf_bars,
    _target, _stock_costs, _etf_costs, _initial_position,
)


def source(price=10.):
    bars=_stock_and_etf_bars(SESSION).with_columns(*[
        pl.when(pl.col('symbol')==STOCK).then(price).otherwise(pl.col(c)).alias(c)
        for c in ['open','high','low','close']])
    targets=pl.concat([_target(.3),_target(.3).with_columns(pl.lit(ETF).alias('symbol'))])
    return dict(calendar=_calendar(SESSION),bars=bars,scheduled_targets=targets,
        instruments=_stock_and_etf_instruments(),market_states={(SESSION,s):DailyMarketState() for s in [STOCK,ETF]},
        initial_cash=10000.,etf_costs=_etf_costs(),stock_costs=_stock_costs(),strategy='m2-u1')


def test_fixed_stock_quantity_survives_gap_etf_preserves_weight_sizing():
    for price in [8.,12.]:
        args=source(price)
        result=simulate_daily_targets(**args,target_share_deltas={STOCK:200})
        assert result.trades.filter(pl.col('symbol')==STOCK)['quantity'].to_list()==[200]
        control=simulate_daily_targets(**args)
        assert result.trades.filter(pl.col('symbol')==ETF).equals(control.trades.filter(pl.col('symbol')==ETF))


def test_fixed_quantity_records_cash_shortfall_and_t1_rejection():
    args=source();args['initial_cash']=1500.
    result=simulate_daily_targets(**args,target_share_deltas={STOCK:200})
    assert 'CASH_CONSTRAINT' in result.rejections['reason']
    args=source();args['initial_positions']=_initial_position(quantity=200,settled_quantity=0)
    result=simulate_daily_targets(**args,target_share_deltas={STOCK:-200})
    assert result.trades.filter(pl.col('symbol')==STOCK).is_empty()
    assert 'T_PLUS_ONE' in result.rejections['reason']


@pytest.mark.parametrize('delta',[1,-100,True])
def test_invalid_deltas_fail(delta):
    with pytest.raises(ValueError):simulate_daily_targets(**source(),target_share_deltas={STOCK:delta})
