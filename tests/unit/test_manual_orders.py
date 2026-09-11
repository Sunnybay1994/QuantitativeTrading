import copy
import datetime as dt

import polars as pl
import pytest
from tests.unit.test_stock_paper import fixture_inputs

from quant.execution.manual_orders import prepare_manual_orders
from quant.execution.stock_paper import reference_orders


def case():
    inputs, base, _, _ = fixture_inputs()
    day, next_day = dt.date(2026, 9, 10), dt.date(2026, 9, 11)
    market = inputs.bars.filter(pl.col('trade_date') == day).select('symbol', 'trade_date', 'close').with_columns(
        pl.lit(100).alias('board_lot'), pl.lit(False).alias('suspended'),
        pl.lit(100.0).alias('up_limit'), pl.lit(1.0).alias('down_limit'),
        pl.lit('bank').alias('industry'), pl.lit(1e9).alias('average_amount'))
    symbol = market['symbol'][0]
    price = market['close'][0]
    state = {'date': str(day), 'cash': 90000.0,
             'holdings': {symbol: {'quantity': 100, 'mark_price': price}},
             'valuation': {'date': str(day), 'equity': 90000 + 100 * price}}
    targets = pl.DataFrame([{'as_of': str(day), 'execution_date': str(next_day),
        'symbol': symbol, 'weight': 0.09, 'strategy': 'fixture', 'strategy_version': 'v1'}])
    config = {'paper': {'name': 'fixture', 'auto_trade': False}, 'costs': base['costs']}
    limits = dict(cash_buffer=0.02, single_stock_weight=0.1, industry_weight=0.3,
                  participation_rate=0.05, maximum_liquidation_days=5.0)
    return dict(state=state, targets=targets, inputs=inputs, market=market,
                next_session=next_day, config=config, limits=limits)


def test_closed_book_reuses_sizing_and_does_not_mutate_account():
    args = case()
    original = copy.deepcopy(args['state'])
    proposed, orders, result = prepare_manual_orders(**args)
    scenario = {**original, 'pending': args['targets'].to_dicts()}
    expected = reference_orders(scenario, args['inputs'], args['config'])
    assert orders.equals(expected) and proposed.equals(expected) and orders.height > 0
    assert not result['withheld'] and result['rehearsal']
    assert args['state'] == original


def test_concentration_withholds_whole_proposal():
    args = case()
    args['targets'] = args['targets'].with_columns(pl.lit(0.8).alias('weight'))
    proposed, orders, result = prepare_manual_orders(**args)
    assert proposed.height > 0 and orders.is_empty() and result['withheld']
    assert 'single_stock_weight' in {r['rule'] for r in result['risk']['issues']}


@pytest.mark.parametrize('change', ['valuation', 'date', 'duplicate', 'weight', 'next_session'])
def test_invalid_book_or_target_is_rejected(change):
    args = case()
    if change == 'valuation':
        args['state']['cash'] += 1
    elif change == 'date':
        args['targets'] = args['targets'].with_columns(pl.lit('2026-09-09').alias('as_of'))
    elif change == 'duplicate':
        args['targets'] = pl.concat([args['targets']] * 2)
    elif change == 'weight':
        args['targets'] = args['targets'].with_columns(pl.lit(float('nan')).alias('weight'))
    else:
        args['next_session'] = dt.date(2026, 9, 14)
    with pytest.raises(ValueError):
        prepare_manual_orders(**args)


def test_halt_sell_only_and_empty_targets():
    args = case()
    args['config']['paper']['enabled'] = False
    assert prepare_manual_orders(**args)[1].is_empty()
    args['config']['paper']['enabled'] = True
    args['config']['paper']['sell_only'] = True
    assert prepare_manual_orders(**args)[1].is_empty()
    args['targets'] = args['targets'].with_columns(pl.lit(0.0).alias('weight'))
    orders = prepare_manual_orders(**args)[1]
    assert orders['side'].to_list() == ['SELL'] and orders['quantity'].to_list() == [100]
    args['targets'] = args['targets'].clear()
    assert prepare_manual_orders(**args)[1].is_empty()
