import datetime as dt

import polars as pl
import pytest

from quant.portfolio.signal_netting import net_signals


def inputs():
    day, next_day = dt.date(2024, 1, 2), dt.date(2024, 1, 3)
    return {'targets': pl.DataFrame({'strategy': ['a', 'b'], 'symbol': ['x', 'x'], 'weight': [.8, .2],
        'as_of': [day, day], 'execution_date': [next_day, next_day]}),
        'budgets': {'a': .5, 'b': .5}, 'holdings': pl.DataFrame({'symbol': ['x'], 'quantity': [500], 'settled_quantity': [500]}),
        'prices': pl.DataFrame({'symbol': ['x'], 'price': [10.]}), 'equity': 10000., 'as_of': day, 'execution_date': next_day}


def test_same_account_cancellation_and_weight_conservation():
    merged, sleeves, orders = net_signals(**inputs())
    assert sleeves['signed_notional'].to_list() == [1500., -1500.]
    assert merged['weight'][0] == .5
    assert merged['cancelled_notional'][0] == 1500.
    assert merged['gross_notional'][0] == merged['net_notional'][0] + 2*merged['cancelled_notional'][0]
    assert orders.is_empty()


@pytest.mark.parametrize('case', ['missing_strategy', 'negative_weight', 'wrong_date', 'wrong_budget'])
def test_invalid_inputs_fail(case):
    args = inputs()
    if case == 'missing_strategy':
        args['targets'] = args['targets'].head(1)
    elif case == 'negative_weight':
        args['targets'] = args['targets'].with_columns(pl.lit(-.1).alias('weight'))
    elif case == 'wrong_date':
        args['execution_date'] = dt.date(2024, 1, 4)
    else:
        args['budgets'] = {'a': .4, 'b': .4}
    with pytest.raises(ValueError):
        net_signals(**args)


def test_sell_only_is_applied_after_netting_and_settled_cap_is_lot_safe():
    args = inputs()
    args['targets'] = args['targets'].with_columns(pl.lit(.8).alias('weight'))
    merged, _, orders = net_signals(**args, sell_only=True)
    assert orders.is_empty()
    assert merged['withheld_delta'][0] == 300
    args['targets'] = args['targets'].with_columns(pl.lit(0.).alias('weight'))
    args['holdings'] = args['holdings'].with_columns(pl.lit(150).alias('settled_quantity'))
    merged, _, orders = net_signals(**args, sell_only=True)
    assert orders['quantity'][0] == 100
    assert merged['withheld_delta'][0] == -400


def test_odd_share_liquidation_can_clear_position():
    args = inputs()
    args['targets'] = args['targets'].with_columns(pl.lit(0.).alias('weight'))
    args['holdings'] = args['holdings'].with_columns(pl.lit(135).alias('quantity'), pl.lit(135).alias('settled_quantity'))
    _, _, orders = net_signals(**args)
    assert orders['quantity'][0] == 135
