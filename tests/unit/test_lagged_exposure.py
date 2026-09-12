import datetime as dt

import polars as pl
import pytest

from quant.reporting.lagged_exposure import attribute, reconstruct


def test_control_is_strictly_lagged_and_linked_contributions_reconcile():
    days = [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    detail = pl.DataFrame({'date': days, 'symbol': ['A', 'A'], 'prior_weight': [.8, .9],
                           'pnl': [10., -5.], 'contribution': [.1, -5/110]})
    daily = pl.DataFrame({'date': days, 'prior_equity': [100., 110.]})
    controls = pl.DataFrame({'trade_date': [dt.date(2023, 12, 29), days[0]], 'symbol': ['A', 'A'],
        'size': ['low', 'high'], 'industry': ['old', 'new'], 'liquidity': ['low', 'high']})
    joined, groups = attribute(detail, daily, controls)
    assert joined['industry'].to_list() == ['old', 'new']
    assert joined['control_age_days'].to_list() == [4, 1]
    assert groups.filter(pl.col('dimension') == 'industry')['linked_contribution'].sum() == pytest.approx(.05)


def test_saved_fills_include_fee_once_and_fail_wrong_mark():
    day = dt.date(2024, 1, 2)
    nav = pl.DataFrame({'date': [day], 'equity': [109.], 'market_value': [60.], 'cash': [49.], 'delisted_symbols': ['']})
    trades = pl.DataFrame({'date': [day], 'symbol': ['A'], 'side': ['BUY'], 'quantity': [5],
                           'price': [10.], 'notional': [50.], 'fee': [1.]})
    bars = pl.DataFrame({'trade_date': [day], 'symbol': ['A'], 'close': [12.]})
    dividends = pl.DataFrame(schema={'ex_date': pl.Date, 'record_date': pl.Date, 'symbol': pl.String, 'share_ratio': pl.Float64})
    initial = {'cash': 100., 'holdings': {}, 'receivables': []}
    details, daily = reconstruct(nav=nav, trades=trades, bars=bars, dividends=dividends, calendar=pl.DataFrame(), initial=initial)
    assert details['pnl'][0] == 9.
    assert daily['residual_pnl'][0] == 0.
    assert initial['holdings'] == {}
    with pytest.raises(ValueError, match='does not reconcile'):
        reconstruct(nav=nav, trades=trades, bars=bars.with_columns(pl.lit(13.).alias('close')),
                    dividends=dividends, calendar=pl.DataFrame(), initial=initial)


def test_ex_date_same_day_payment_is_income_not_unexplained_residual():
    day, previous = dt.date(2024, 1, 3), dt.date(2024, 1, 2)
    nav = pl.DataFrame({'date': [day], 'equity': [100.], 'market_value': [90.], 'cash': [10.], 'delisted_symbols': ['']})
    trades = pl.DataFrame(schema={'date': pl.Date, 'symbol': pl.String, 'side': pl.String,
        'quantity': pl.Int64, 'price': pl.Float64, 'notional': pl.Float64, 'fee': pl.Float64})
    bars = pl.DataFrame({'trade_date': [day], 'symbol': ['600000.SH'], 'close': [9.]})
    dividends = pl.DataFrame({'symbol': ['600000.SH'], 'ex_date': [day], 'record_date': [previous],
        'pay_date': [day], 'ann_date': [previous], 'div_cash': [1.], 'share_ratio': [0.]})
    calendar = pl.DataFrame({'date': [previous, day], 'is_open': [True, True], 'market': ['SH', 'SH']})
    initial = {'cash': 0., 'holdings': {'600000.SH': {'quantity': 10, 'mark_price': 10.}}, 'receivables': []}
    details, daily = reconstruct(nav=nav, trades=trades, bars=bars, dividends=dividends, calendar=calendar, initial=initial)
    assert details['pnl'][0] == 0.
    assert daily['residual_pnl'][0] == 0.
