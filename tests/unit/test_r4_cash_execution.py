import polars as pl
import pytest
from quant.backtest import DailyMarketState, simulate_daily_targets
from tests.unit.test_daily_simulator import (
    SESSION, STOCK, _calendar, _bar, _target, _instruments, _initial_position,
    _etf_costs, _stock_costs, _simulate,
)


def test_missing_adv_cap_blocks_trade_instead_of_allowing_unbounded_order():
    result = simulate_daily_targets(
        calendar=_calendar(SESSION), bars=_bar(), scheduled_targets=_target(1.),
        instruments=_instruments(), market_states={(SESSION, STOCK): DailyMarketState()},
        initial_cash=20000., etf_costs=_etf_costs(), stock_costs=_stock_costs(),
        strategy='m2-u1', execution_notional_caps={})
    assert result.trades.is_empty()
    assert result.rejections['reason'].to_list() == ['PARTICIPATION_CAP']


@pytest.mark.parametrize('case', ['adv_cap', 'signal_block', 'suspended', 'unsettled', 'lower_limit'])
def test_constrained_cash_exit_uses_shared_execution_guards(case):
    from quant.portfolio.constrained_selection import constrained_targets
    target = _target(0.)
    day = target['as_of'][0]
    market = pl.DataFrame({'as_of': [day], 'known_at': [day], 'symbol': [STOCK],
        'can_sell': [case != 'signal_block'], 'adv20': [50000.]})
    state = {'date': str(day), 'nav': [{'equity': 10000.}],
        'holdings': {STOCK: {'quantity': 1000, 'mark_price': 10.}}}
    targets, info = constrained_targets(targets=target, state=state, market=market,
        scores=pl.DataFrame(), policy={'adv_participation': .05, 'tolerance': 1e-8})
    result = simulate_daily_targets(calendar=_calendar(SESSION), bars=_bar(),
        scheduled_targets=targets, instruments=_instruments(),
        market_states={(SESSION, STOCK): DailyMarketState(suspended=case == 'suspended', at_lower_limit=case == 'lower_limit')},
        initial_cash=0., etf_costs=_etf_costs(), stock_costs=_stock_costs(), strategy='m2-u1',
        initial_positions=_initial_position(quantity=1000, settled_quantity=0 if case == 'unsettled' else 1000),
        execution_notional_caps=info['execution_notional_caps'],
        target_permissions=info['execution_direction_permissions'])
    if case == 'adv_cap':
        assert result.trades['quantity'].to_list() == [200]
        assert result.trades['notional'].sum() <= 2500.
    else:
        assert result.trades.is_empty()


def test_full_day_suspension_without_bar_carries_mark_and_rejects_sale() -> None:
    result = _simulate(
        bars=_bar().head(0),
        target_weight=0.0,
        state=DailyMarketState(suspended=True),
        initial_position=_initial_position(quantity=100, settled_quantity=100),
    )

    assert result.nav.item(0, "market_value") == pytest.approx(1_000.0)
    assert result.positions.item(0, "quantity") == 100
    assert result.positions.item(0, "mark_price") == pytest.approx(10.0)
    assert result.trades.height == 0
    assert result.rejections.select(
        "symbol",
        "side",
        "reason",
        "requested_quantity",
        "rejected_quantity",
        "reference_price",
    ).row(0) == (STOCK, "SELL", "SUSPENDED", 100, 100, 10.0)


