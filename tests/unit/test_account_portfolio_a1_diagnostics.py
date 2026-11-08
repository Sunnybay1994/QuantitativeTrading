import datetime as dt

import polars as pl
import pytest

from quant.reporting.account_portfolio_v1 import assess_gates, measure
from quant.research.account_portfolio_zero_alpha import ETFProxyAllocation, index_reference


def spec():
    return {'fixed_weights': [.4, .3, .3], 'etfs': {
        'dividend': {'symbol': '512890.SH', 'listing_date': dt.date(2019, 1, 18)},
        'treasury': {'symbol': '511010.SH', 'listing_date': dt.date(2013, 3, 25)}}}


def test_delete_improvement_diagnostic_preserves_sharpe_floor_and_other_gates():
    limits = dict(maximum_drawdown=.2, minimum_sharpe=1.,
        minimum_sharpe_improvement_over_stock=.2, minimum_double_cost_cagr_over_treasury=.04,
        minimum_worst_calendar_year=-.1)
    rows = [dict(cost_multiplier=c, max_drawdown=-.15, sharpe=1.1,
                 sharpe_improvement=-.3, worst_year={'return': -.05}, treasury_cagr_excess=.05)
            for c in (.5, 1., 2.)]
    assert assess_gates(rows, limits)['conclusion'] == 'REJECTED'
    diagnostic = assess_gates(rows, limits, remove_improvement=True)
    assert diagnostic['conclusion'] == 'PAPER_CANDIDATE'
    assert diagnostic['effective'] is False
    rows[-1]['sharpe'] = .99
    assert assess_gates(rows, limits, remove_improvement=True)['conclusion'] == 'REJECTED'
    rows[-1]['sharpe'] = 1.1
    rows[-1]['treasury_cagr_excess'] = .039
    assert assess_gates(rows, limits, remove_improvement=True)['conclusion'] == 'REJECTED'


def test_index_reference_keeps_first_day_loss_and_prelisting_cash():
    day = dt.date(2019, 1, 2)
    returns = pl.DataFrame({'date': [day], 'stock': [-.1], 'dividend': [None], 'treasury': [0.]})
    result = index_reference(returns=returns, days=[day], previous=dt.date(2018, 12, 28),
                             spec=spec(), variant='fixed_40_30_30')
    assert result['equity'].item() == pytest.approx(288000.)
    assert result['cash'].item() == 90000.
    assert result['cumulative_fees'].item() == 0.
    with pytest.raises(ValueError, match='Missing return-index date'):
        index_reference(returns=returns, days=[day+dt.timedelta(days=1)], previous=day,
                        spec=spec(), variant='fixed_40_30_30')


def test_proxy_offquarter_preserves_etf_units_and_never_adds_q10_budget():
    day = dt.date(2020, 2, 28)
    batch = pl.DataFrame({'as_of': [day], 'symbol': ['510300.SH'], 'weight': [1.]})
    allocator = ETFProxyAllocation(variant='fixed_40_30_30', spec=spec(),
                                   returns=pl.DataFrame(), etf_prices=None)
    allocator.initialized = True
    state = {'nav': [{'equity': 300000.}], 'holdings': {
        '512890.SH': {'quantity': 90000, 'mark_price': 1.},
        '511010.SH': {'quantity': 900, 'mark_price': 100.}}}
    targets, info = allocator(batch, state)
    assert targets.filter(pl.col('symbol') == '510300.SH')['weight'].item() == .4
    assert info['target_share_deltas'] == {'512890.SH': 0, '511010.SH': 0}


def test_gross_reference_metrics_use_no_fabricated_execution(tmp_path):
    days = [dt.date(2019, 1, 2), dt.date(2019, 1, 3)]
    returns = pl.DataFrame({'date': days, 'stock': [-.1, .02],
                            'dividend': [None, None], 'treasury': [0., 0.]})
    nav = index_reference(returns=returns, days=days, previous=dt.date(2018, 12, 28),
                          spec=spec(), variant='fixed_40_30_30')
    nav.write_parquet(tmp_path/'nav.parquet')
    pl.DataFrame(schema={'date': pl.Date, 'symbol': pl.String,
                         'notional': pl.Float64}).write_parquet(tmp_path/'trades.parquet')
    result = measure(tmp_path)
    assert result['trade_count'] == 0
    assert result['cumulative_fees'] == 0
    assert result['max_drawdown'] <= -.04
