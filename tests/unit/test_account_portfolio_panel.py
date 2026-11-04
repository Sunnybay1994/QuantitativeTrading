import datetime as dt

import polars as pl
import pytest

from quant.data.account_portfolio_panel import economic_prices, cash_actions
from quant.backtest.daily_account import prepare_account_actions


def test_official_split_preserves_suspended_value_and_keeps_real_reopening_loss():
    days = [dt.date(2021,10,21), dt.date(2021,10,22), dt.date(2021,10,25)]
    terms = dict(symbol='512890.SH', announcement_date=dt.date(2021,10,18), record_date=days[0],
                 effective_date=days[1], tradable_date=days[2], ratio=2., suspended_dates=[days[1]])
    bars = pl.DataFrame({'symbol': ['512890.SH']*2, 'trade_date': [days[0],days[2]], 'close': [1.639,.801]})
    prices = economic_prices(bars=bars, sessions=days, actions=[], splits=[terms])
    assert prices['observed_quote'].to_list() == [True,False,True]
    assert prices['total_return_price'][1] == 100.
    assert prices['total_return_price'][2] == pytest.approx(100*2*.801/1.639)
    calendar = pl.DataFrame({'market': ['SH']*3, 'date': days, 'is_open': [True]*3})
    state = {'holdings': {'512890.SH': {'quantity': 1000, 'mark_price': 1.639}}, 'cash': 0., 'receivables': []}
    events = pl.DataFrame({'symbol': ['512890.SH'], 'ann_date': [terms['announcement_date']],
        'record_date': [days[0]], 'ex_date': [days[1]], 'pay_date': [days[1]],
        'div_cash': [0.], 'share_ratio': [1.], 'share_list_date': [days[2]]})
    prepared = prepare_account_actions(date=days[1], state=state, calendar=calendar, dividends=events)
    holding = prepared['holdings']['512890.SH']
    assert holding['quantity'] == 2000
    assert holding['quantity']*holding['mark_price'] == pytest.approx(1639.)
    assert prepared['restricted_shares'][0]['list_date'] == str(days[2])
    with pytest.raises(ValueError, match='Unexplained absent'):
        economic_prices(bars=bars, sessions=days, actions=[], splits=[])


def test_duplicate_dividend_not_paid_twice_and_conflicting_terms_fail():
    row = dict(ts_code='511010.SH', div_proc='实施', ex_date='20260625',
        ann_date='20260622', imp_anndate='20260622', record_date='20260624',
        pay_date='20260630', div_cash=.8144)
    assert len(cash_actions(pl.from_dicts([row,row]), dt.date(2026,8,31))) == 1
    with pytest.raises(ValueError, match='Conflicting'):
        cash_actions(pl.from_dicts([row,{**row,'div_cash':.9}]),dt.date(2026,8,31))


def test_post_split_trade_uses_published_daily_reference_not_old_quote():
    from quant.research.account_portfolio_etf_baselines import market_states
    date = dt.date(2021,10,25)
    bars = pl.DataFrame({'symbol':['512890.SH'],'trade_date':[date], 'open':[.87],'volume':[1000.]})
    refs = pl.DataFrame({'symbol':['512890.SH'],'trade_date':[date], 'pre_close':[.801]})
    state = market_states(bars,refs,[],1.)[date,'512890.SH']
    assert not state.at_lower_limit and not state.at_upper_limit
