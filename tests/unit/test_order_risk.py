import copy
import datetime as dt

import polars as pl
import pytest

from quant.execution.order_risk import assess_reference_orders, render_report

D0, D1 = dt.date(2026, 9, 10), dt.date(2026, 9, 11)
LIMITS = dict(cash_buffer=0.02, single_stock_weight=0.6, industry_weight=0.7,
              participation_rate=0.05, maximum_liquidation_days=5.0)


def inputs():
    state = {'date': str(D0), 'cash': 10000.0,
             'holdings': {'A': {'quantity': 1000, 'mark_price': 10.0}},
             'receivables': [{'amount': 100.0}], 'restricted_shares': []}
    market = pl.DataFrame([{'symbol': symbol, 'trade_date': D0, 'close': 10.0,
        'board_lot': 100, 'suspended': False, 'up_limit': 11.0, 'down_limit': 9.0,
        'industry': 'bank', 'average_amount': 10000.0} for symbol in ('A', 'B')])
    orders = pl.DataFrame([{'symbol': 'A', 'side': 'SELL', 'quantity': 200,
        'as_of': str(D0), 'execution_date': str(D1), 'estimated_fill_price': 10.0,
        'estimated_fee': 5.0}, {'symbol': 'B', 'side': 'BUY', 'quantity': 500,
        'as_of': str(D0), 'execution_date': str(D1), 'estimated_fill_price': 10.0,
        'estimated_fee': 5.0}])
    return state, market, orders


def assess(state, market, orders):
    return assess_reference_orders(state=state, orders=orders, market=market,
                                   next_session=D1, limits=LIMITS)


def test_combined_positions_fees_receivables_and_liquidity():
    state, market, orders = inputs()
    original = copy.deepcopy(state)
    result = assess(state, market, orders)
    assert result['initial_equity'] == 20100
    assert result['projected_cash'] == 6990
    assert result['projected_equity'] == 20090
    assert result['industry_weights']['bank'] == pytest.approx(13000/20090)
    assert result['positions'][0]['quantity'] == 800
    assert result['positions'][0]['liquidation_days'] == 16
    assert result['positions'][0]['half_volume_liquidation_days'] == 32
    assert result['one_way_turnover'] == pytest.approx(7000/40200)
    assert state == original


def test_same_day_buys_cannot_supply_later_sell_orders():
    state, market, orders = inputs()
    orders = pl.concat([orders, orders.tail(1).with_columns(pl.lit('SELL').alias('side'))])
    result = assess(state, market, orders)
    assert not result['projection_valid']
    assert any(row['rule'] == 'sellable_quantity' for row in result['issues'])
    assert result['projected_cash'] is None and result['positions'] == []
    assert '订单不可行，暂停预测' in render_report(result)


def test_full_liquidation_still_checks_order_participation():
    state, market, orders = inputs()
    orders = orders.head(1).with_columns(pl.lit(1000).alias('quantity'))
    result = assess(state, market, orders)
    assert result['positions'] == []
    assert result['order_liquidity'][0]['participation_rate'] == 1
    assert result['order_liquidity'][0]['minimum_execution_days'] == 20
    assert 'order_participation' in {r['rule'] for r in result['issues']}


def test_splitting_same_symbol_does_not_bypass_daily_participation():
    state, market, orders = inputs()
    market = market.with_columns(pl.lit(60000.).alias('average_amount'))
    orders = pl.concat([orders.head(1), orders.head(1)])
    result = assess(state, market, orders)
    assert len(result['order_liquidity']) == 1
    assert result['order_liquidity'][0]['gross_order_amount'] == 4000
    assert 'order_participation' in {r['rule'] for r in result['issues']}


def test_restricted_shares_and_cash_are_checked_without_trusting_cash_after():
    state, market, orders = inputs()
    state['restricted_shares'] = [{'symbol': 'A', 'quantity': 900, 'list_date': '2026-09-14'}]
    orders = orders.with_columns(pl.when(pl.col('side') == 'BUY').then(2000)
                                .otherwise(pl.col('quantity')).alias('quantity'),
                                pl.lit(1000000.0).alias('cash_after'))
    result = assess(state, market, orders)
    assert not result['projection_valid']
    assert result['projected_equity'] is None and result['industry_weights'] is None
    assert {'sellable_quantity', 'insufficient_cash', 'cash_buffer'} <= {
        row['rule'] for row in result['issues']}


def test_held_positions_are_checked_even_without_orders():
    state, market, orders = inputs()
    state['cash'] = 0.0
    result = assess(state, market, orders.clear())
    assert {'single_stock_weight', 'industry_weight', 'cash_buffer'} <= {
        row['rule'] for row in result['issues']}


def test_missing_industry_and_liquidity_are_not_zero_risk():
    state, market, orders = inputs()
    market = market.with_columns(pl.lit(None, dtype=pl.String).alias('industry'),
                                 pl.lit(None, dtype=pl.Float64).alias('average_amount'))
    result = assess(state, market, orders)
    assert result['unknown_industry_weight'] > 0
    assert {'missing_industry', 'missing_liquidity'} <= {row['rule'] for row in result['issues']}


def test_signal_day_limits_are_reported_as_known_not_tomorrow_status():
    state, market, orders = inputs()
    market = market.with_columns(pl.lit(True).alias('suspended'), pl.lit(10.0).alias('up_limit'))
    result = assess(state, market, orders)
    assert {'signal_day_suspension', 'signal_day_price_limit'} <= {
        row['rule'] for row in result['issues']}
    assert result['execution_day_market_status'] == 'unknown_at_signal_close'


@pytest.mark.parametrize('change', ['date', 'duplicate', 'price', 'future_price', 'fractional_shares'])
def test_invalid_inputs_fail(change):
    state, market, orders = inputs()
    if change == 'date':
        orders = orders.with_columns(pl.lit(str(D0)).alias('execution_date'))
    elif change == 'duplicate':
        market = pl.concat([market, market.head(1)])
    elif change == 'price':
        market = market.with_columns(pl.lit(float('nan')).alias('close'))
    elif change == 'future_price':
        market = market.with_columns(pl.lit(D1).alias('price_date'), pl.lit(True).alias('suspended'))
    else:
        state['holdings']['A']['quantity'] = 1000.5
    with pytest.raises(ValueError):
        assess(state, market, orders)


def test_local_reader_uses_completed_calendar_and_reports_missing_liquidity(tmp_path, monkeypatch):
    from quant.data import order_risk_inputs as reader

    sessions = (D0-dt.timedelta(days=1), D0, D1)
    monkeypatch.setattr(reader, 'available_sessions', lambda *_: sessions)
    folder = tmp_path/'clean/stock_paper_inputs'/f'date={D0}'
    folder.mkdir(parents=True)
    pl.DataFrame({'symbol': ['A'], 'board_lot': [100]}).write_parquet(folder/'instruments.parquet')
    pl.DataFrame({'symbol': ['A'], 'trade_date': [D0], 'up_limit': [11.0],
                  'down_limit': [9.0]}).write_parquet(folder/'limits.parquet')
    pl.DataFrame({'symbol': ['A'], 'trade_date': [D0]}).write_parquet(folder/'suspensions.parquet')

    def bars(**kwargs):
        assert kwargs['start'] == sessions[0] and kwargs['end'] == D0
        return pl.DataFrame({'symbol': ['A'], 'trade_date': [sessions[0]],
                             'close': [10.0], 'amount': [1000.0]})

    monkeypatch.setattr(reader, 'read_stock_data', bars)
    monkeypatch.setattr(reader, 'read_factor_industry', lambda root, panel:
                        panel.with_columns(pl.lit('bank').alias('industry_l1')))
    market, following = reader.read_order_risk_inputs(data_root=tmp_path,
        refresh_config=tmp_path/'unused.toml', symbols=['A'], as_of=D0, lookback=2)
    assert following == D1
    assert market['average_amount'].item() is None
    assert market['price_date'].item() == sessions[0]
    assert market['suspended'].item()
    state, _, orders = inputs()
    result = assess(state, market, orders.clear())
    assert any(row['rule'] == 'missing_liquidity' for row in result['issues'])
