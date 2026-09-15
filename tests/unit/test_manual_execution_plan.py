import datetime as dt

import polars as pl
import pytest

from quant.execution.manual_execution_plan import build_plan, opening_band


def plan(quantity=2500, side='BUY', amount=200000., sessions=None):
    dates = [dt.date(2026, 9, d) for d in (11, 14, 15)]
    return build_plan(orders=pl.DataFrame({'symbol': ['A'], 'side': [side],
        'quantity': [quantity], 'estimated_fill_price': [10.], 'execution_date': [str(dates[0])]}),
        market=pl.DataFrame({'symbol': ['A'], 'board_lot': [100], 'average_amount': [amount]}),
        sessions=dates if sessions is None else sessions, participation_rate=.05)


def test_three_day_split_preserves_shares_and_skips_weekend():
    rows = plan()
    assert rows['quantity'].to_list() == [1000, 1000, 500]
    assert rows['execution_date'].to_list() == ['2026-09-11', '2026-09-14', '2026-09-15']
    assert rows['estimated_participation'].max() <= .05
    assert rows['status'].unique().to_list() == ['requires_daily_recheck']
    assert not rows['auto_trade'].any()


def test_odd_lot_sale_preserves_final_remainder():
    assert plan(2051, 'SELL')['quantity'].to_list() == [1000, 1000, 51]


@pytest.mark.parametrize('kwargs,reason', [
    ({'quantity': 3100}, 'exceeds_three_day_capacity'),
    ({'quantity': 2051}, 'invalid_buy_lot'),
    ({'amount': None}, 'missing_liquidity'),
    ({'amount': 100.}, 'less_than_one_lot_per_day'),
    ({'sessions': [dt.date(2026, 9, 11)]}, 'missing_execution_calendar'),
])
def test_unplannable_order_has_no_partial_release(kwargs, reason):
    rows = plan(**kwargs)
    assert rows.height == 1 and rows['status'][0] == 'rejected'
    assert rows['reason'][0] == reason and rows['execution_date'][0] is None


def test_opening_band_intersects_official_limits_and_rounds_inward():
    assert opening_band(opening=10.03, down_limit=9., up_limit=11.) == (9.93, 10.13)
    assert opening_band(opening=10., down_limit=9.98, up_limit=10.05) == (9.98, 10.05)
    with pytest.raises(ValueError):
        opening_band(opening=11., down_limit=9., up_limit=10.)
