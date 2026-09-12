import datetime as dt

import polars as pl
import pytest

from quant.reporting.turnover_decomposition import decompose


def inputs():
    first, second = dt.date(2025, 12, 30), dt.date(2026, 1, 2)
    raw = pl.DataFrame({'as_of': [dt.date(2025, 12, 29), dt.date(2025, 12, 31)],
        'execution_date': [first, second], 'symbol': ['A', 'B'], 'weight': [1., 1.]})
    buffer = raw.with_columns(pl.lit('A').alias('symbol'))
    nav = pl.DataFrame({'date': [second, first, dt.date(2025, 12, 31)], 'equity': [125., 120., 120.]})
    trades = pl.DataFrame({'date': [first, second], 'symbol': ['A', 'A'],
        'side': ['BUY', 'SELL'], 'quantity': [100, 50], 'price': [1., 2.4],
        'notional': [100., 120.], 'fee': [0., 0.]})
    rejects = pl.DataFrame({'date': [second], 'reason': ['insufficient_cash']})
    return dict(unbuffered=raw, buffered=buffer, nav=nav, trades=trades,
                rejections=rejects, initial_cash=100.)


def test_same_dates_and_cross_year_carry():
    data = inputs()
    monthly, daily = decompose(**data)
    assert monthly['unbuffered_target_turnover'].to_list() == [.5, 1.]
    assert monthly['buffered_target_turnover'].to_list() == [.5, 0.]
    assert monthly['actual_one_way_turnover'].to_list() == [.5, .5]
    assert daily['prior_equity'].to_list() == [100., 120., 120.]
    assert daily['gross_notional'].sum() == data['trades']['notional'].sum()
    assert monthly['constrained_target_turnover'].null_count() == 2
    assert monthly['needed_buy_weight_at_signal_close'].null_count() == 2
    assert monthly['rejection_reasons'][-1] == '{"insufficient_cash": 1}'


def test_actual_holdings_and_partial_constraints_are_not_fabricated():
    data = inputs()
    result, _ = decompose(**data, constrained=data['buffered'].tail(1),
        holdings={dt.date(2025, 12, 31): {'A': .8}})
    assert result['constrained_target_turnover'].null_count() == 2
    assert result['constraint_provided'].to_list() == [False, True]
    assert result['needed_buy_weight_at_signal_close'][-1] == pytest.approx(.2)
    assert result['needed_sell_weight_at_signal_close'][-1] == 0


@pytest.mark.parametrize('problem', ['date', 'duplicate', 'notional', 'outside', 'missing_signal_nav'])
def test_fail_on_unaligned_or_unreconciled_inputs(problem):
    data = inputs()
    if problem == 'date':
        data['buffered'] = data['buffered'].with_columns(pl.col('execution_date')+dt.timedelta(days=1))
    elif problem == 'duplicate':
        data['nav'] = pl.concat([data['nav'], data['nav'].head(1)])
    elif problem == 'missing_signal_nav':
        data['nav'] = data['nav'].filter(pl.col('date') != dt.date(2025, 12, 31))
    elif problem == 'outside':
        data['trades'] = data['trades'].with_columns(pl.col('date')+dt.timedelta(days=10))
    else:
        data['trades'] = data['trades'].with_columns(pl.col('notional')+1)
    with pytest.raises(ValueError):
        decompose(**data)
