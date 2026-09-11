import datetime as dt

import polars as pl
import pytest

from quant.backtest import DailyMarketState
from quant.data.etf_paper_inputs import etf_session_states
from quant.execution.paper_ledger import advance, next_targets, order_estimates

SYMBOL = "510300.SH"
D1 = dt.date(2026, 7, 14)
D2 = dt.date(2026, 7, 15)
D3 = dt.date(2026, 7, 16)


def inputs():
    dates = [D1, D2, D3]
    bars = pl.DataFrame({"symbol": [SYMBOL] * 3, "trade_date": dates,
        "open": [10.0, 9.0, 9.0], "high": [10.0, 9.0, 9.0],
        "low": [10.0, 9.0, 9.0], "close": [10.0, 9.0, 9.0],
        "volume": [10000.0] * 3, "amount": [100000.0] * 3,
        "adj_factor": [1.0] * 3, "source": ["fixture"] * 3})
    calendar = pl.DataFrame({"market": ["SH"] * 3, "date": dates,
        "is_open": [True] * 3, "is_connect_open": [False] * 3, "is_half_day": [False] * 3})
    instruments = pl.DataFrame({"symbol": [SYMBOL], "market": ["SH"], "name": ["ETF"],
        "instrument_type": ["ETF"], "currency": ["CNY"], "list_date": [dt.date(2012, 5, 28)],
        "delist_date": [None], "board_lot": [100], "status": ["LISTED"]})
    dividends = pl.DataFrame({"symbol": [SYMBOL], "ann_date": [D1], "record_date": [D1],
        "ex_date": [D2], "pay_date": [D3], "div_cash": [1.0]})
    costs = {"commission_rate": 0.0, "commission_min": 0.0, "slippage": 0.0,
             "effective_from": dt.date(2020, 1, 1)}
    config = {"paper": {"name": "s0_equal", "auto_trade": False, "initial_cash": 1100.0},
              "costs": {"etf": costs, "a_share": {**costs, "stamp_tax_sell": 0.0, "transfer_fee": 0.0}}}
    state = {"holdings": {SYMBOL: {"quantity": 100, "mark_price": 10.0}},
             "cash": 100.0, "receivables": [], "pending": [], "nav": []}
    return dict(bars=bars, calendar=calendar, instruments=instruments,
                dividends=dividends, market_states={(d, SYMBOL): DailyMarketState() for d in dates},
                config=config), state


def test_dividend_is_equity_on_ex_date_but_not_spendable_until_pay_date():
    kwargs, state = inputs()
    state, _ = advance(date=D2, state=state, **kwargs)
    assert state["cash"] == 100.0
    assert state["nav"][-1]["receivable"] == 100.0
    assert state["nav"][-1]["equity"] == 1100.0
    state, _ = advance(date=D3, state=state, **kwargs)
    assert state["cash"] == 200.0
    assert not state["receivables"]
    assert state["nav"][-1]["unit_nav"] == 1.0


def test_delayed_share_surrender_reduces_nav_without_compensating_mark():
    kwargs, initial = inputs()
    kwargs["bars"] = kwargs["bars"].with_columns([
        pl.lit(10.).alias(c) for c in ("open", "high", "low", "close")])
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(D3).alias("ex_date"), pl.lit(D3).alias("ann_date"),
        pl.lit(0.).alias("div_cash"), pl.lit(-.2).alias("share_ratio"))
    initial["holdings"][SYMBOL]["quantity"] = 103
    state, _ = advance(date=D1, state=initial, **kwargs)
    assert state["holdings"][SYMBOL]["quantity"] == 103
    assert state["nav"][-1]["equity"] == 1130.
    state, _ = advance(date=D2, state=state, **kwargs)
    assert state["holdings"][SYMBOL]["quantity"] == 103
    state, _ = advance(date=D3, state=state, **kwargs)
    assert state["holdings"][SYMBOL]["quantity"] == 82
    assert state["holdings"][SYMBOL]["mark_price"] == 10.
    assert state["cash"] == 100.
    assert state["nav"][-1]["equity"] == 920.
    assert not state.get("share_reduction_entitlements")
    with pytest.raises(ValueError, match="record-date holdings snapshot"):
        advance(date=D3, state=initial, **kwargs)


def test_reduction_rejects_changed_holdings_and_preserves_zero_entitlement():
    kwargs, state = inputs()
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(D3).alias("ex_date"), pl.lit(0.).alias("div_cash"),
        pl.lit(-.2).alias("share_ratio"))
    state, _ = advance(date=D1, state=state, **kwargs)
    state["holdings"][SYMBOL]["quantity"] = 50
    with pytest.raises(ValueError, match="holdings changed"):
        advance(date=D3, state=state, **kwargs)
    kwargs, empty = inputs()
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(D3).alias("ex_date"), pl.lit(0.).alias("div_cash"),
        pl.lit(-.2).alias("share_ratio"))
    empty["holdings"] = {}
    empty, _ = advance(date=D1, state=empty, **kwargs)
    empty, _ = advance(date=D3, state=empty, **kwargs)
    assert not empty["holdings"] and empty["cash"] == 100.


def test_weekend_final_dividend_terms_apply_once_on_monday_ex_date():
    kwargs, state = inputs()
    friday, monday, tuesday = dt.date(2025, 7, 4), dt.date(2025, 7, 7), dt.date(2025, 7, 8)
    dates = {D1: friday, D2: monday, D3: tuesday}
    kwargs["bars"] = kwargs["bars"].with_columns(pl.col("trade_date").replace_strict(dates))
    kwargs["calendar"] = kwargs["calendar"].with_columns(pl.col("date").replace_strict(dates))
    kwargs["market_states"] = {(dates[day], symbol): value
                                for (day, symbol), value in kwargs["market_states"].items()}
    kwargs["instruments"] = kwargs["instruments"].with_columns(pl.lit("STOCK").alias("instrument_type"))
    kwargs["dividends"] = pl.DataFrame({"symbol": [SYMBOL],
        "ann_date": [dt.date(2025, 7, 5)], "record_date": [friday], "ex_date": [monday],
        "pay_date": [monday], "div_cash": [.2814904], "share_ratio": [.3992772],
        "share_list_date": [monday]})
    state, _ = advance(date=friday, state=state, **kwargs)
    assert state["cash"] == 100.0
    assert state["holdings"][SYMBOL]["quantity"] == 100
    state, _ = advance(date=monday, state=state, **kwargs)
    assert state["cash"] == pytest.approx(128.14904)
    assert state["holdings"][SYMBOL]["quantity"] == 139
    state, _ = advance(date=tuesday, state=state, **kwargs)
    assert state["cash"] == pytest.approx(128.14904)
    assert state["holdings"][SYMBOL]["quantity"] == 139


def test_sell_only_keeps_current_quantity_when_target_requests_more():
    kwargs, state = inputs()
    kwargs["config"]["paper"]["sell_only"] = True
    state["cash"] = 2000.0
    state["pending"] = [{"as_of": str(D1), "execution_date": str(D2), "symbol": SYMBOL,
                         "strategy": "s0_equal", "strategy_version": "1.0.0", "weight": 1.0}]
    state, result = advance(date=D2, state=state, **kwargs)
    assert result.trades.is_empty()
    assert state["holdings"][SYMBOL]["quantity"] == 100


def test_zero_cash_fully_invested_account_can_advance():
    kwargs, state = inputs()
    state["cash"] = 0.0
    state, _ = advance(date=D2, state=state, **kwargs)
    assert state["cash"] == 0.0
    assert state["nav"][-1]["equity"] == 1000.0


def test_signals_only_month_end_or_initial_session():
    config = {"paper": {"name": "s0_equal"}}
    assert not next_targets(D1, D2, D1, [SYMBOL], config)
    targets = next_targets(dt.date(2026, 9, 30), dt.date(2026, 10, 9), dt.date(2026, 10, 9), [SYMBOL], config)
    assert targets[0]["as_of"] == "2026-09-30"
    assert targets[0]["execution_date"] == "2026-10-09"


def test_ex_dividend_reference_does_not_create_false_lower_limit():
    kwargs, _ = inputs()
    states = etf_session_states(kwargs["bars"], kwargs["dividends"])
    assert not states[(D2, SYMBOL)].at_lower_limit
    bars = kwargs["bars"].with_columns(pl.when(pl.col("trade_date") == D2)
        .then(9.9).otherwise(pl.col("open")).alias("open"))
    assert etf_session_states(bars, kwargs["dividends"])[(D2, SYMBOL)].at_upper_limit


def test_order_reference_list_obeys_cash_and_sell_only():
    kwargs, state = inputs()
    state["pending"] = [{"as_of": str(D1), "execution_date": str(D2), "symbol": SYMBOL,
                         "strategy": "s0_equal", "strategy_version": "1.0.0", "weight": 1.0}]
    bars = kwargs["bars"].filter(pl.col("trade_date") == D1)
    orders = order_estimates(state, bars, kwargs["config"])
    assert orders.is_empty()  # only 100 yuan cash cannot buy a 100-share lot
    kwargs["config"]["paper"]["auto_trade"] = True
    with pytest.raises(ValueError, match="auto_trade"):
        advance(date=D2, state=state, **kwargs)


def test_manual_halt_suppresses_execution_but_keeps_valuation():
    kwargs, state = inputs()
    kwargs["config"]["paper"]["enabled"] = False
    state["cash"] = 2000.0
    state["pending"] = [{"as_of": str(D1), "execution_date": str(D2), "symbol": SYMBOL,
                         "strategy": "s0_equal", "strategy_version": "1.0.0", "weight": 1.0}]
    state, result = advance(date=D2, state=state, **kwargs)
    assert result.trades.is_empty()
    assert state["nav"][-1]["equity"] == 3000.0


def test_slippage_cannot_push_a_fill_outside_the_daily_band():
    kwargs, _ = inputs()
    bars = kwargs["bars"].with_columns(pl.when(pl.col("trade_date") == D2)
        .then(9.899).otherwise(pl.col("open")).alias("open"))
    assert not etf_session_states(bars, kwargs["dividends"])[(D2, SYMBOL)].at_upper_limit
    assert etf_session_states(bars, kwargs["dividends"], slippage=0.001)[(D2, SYMBOL)].at_upper_limit


def test_restructuring_bonus_does_not_adjust_prior_mark():
    kwargs, state = inputs()
    kwargs["instruments"] = kwargs["instruments"].with_columns(pl.lit("STOCK").alias("instrument_type"))
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(0.0).alias("div_cash"), pl.lit(.05).alias("share_ratio"),
        pl.lit(D3).alias("share_list_date"), pl.lit(False).alias("adjust_share_price"))
    kwargs["bars"] = kwargs["bars"].filter(pl.col("trade_date") < D2)
    kwargs["market_states"] = {(d, SYMBOL): DailyMarketState(suspended=True) for d in (D2, D3)}
    state, _ = advance(date=D2, state=state, **kwargs)
    assert state["holdings"][SYMBOL]["quantity"] == 105
    assert state["holdings"][SYMBOL]["mark_price"] == 10.
    assert state["nav"][-1]["equity"] == 1150.
    assert state["restricted_shares"][0]["quantity"] == 5
    state, _ = advance(date=D3, state=state, **kwargs)
    assert state["restricted_shares"] == []


def test_bonus_shares_cannot_be_sold_before_listing():
    kwargs, state = inputs()
    kwargs["instruments"] = kwargs["instruments"].with_columns(pl.lit("STOCK").alias("instrument_type"))
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(0.0).alias("div_cash"), pl.lit(0.5).alias("share_ratio"),
        pl.lit(D3).alias("share_list_date"))
    kwargs["bars"] = kwargs["bars"].with_columns([
        pl.when(pl.col("trade_date") >= D2).then(20 / 3).otherwise(pl.col(c)).alias(c)
        for c in ("open", "high", "low", "close")])
    state["pending"] = [{"as_of": str(D1), "execution_date": str(D2), "symbol": SYMBOL,
                         "strategy": "s0_equal", "strategy_version": "v1", "weight": 0.0}]
    state, result = advance(date=D2, state=state, **kwargs)
    assert state["holdings"][SYMBOL]["quantity"] == 150
    assert result.trades.is_empty()
    assert result.rejections.get_column("reason").to_list() == ["T_PLUS_ONE"]
    state["pending"] = [{"as_of": str(D2), "execution_date": str(D3), "symbol": SYMBOL,
                         "strategy": "s0_equal", "strategy_version": "v1", "weight": 0.0}]
    state, result = advance(date=D3, state=state, **kwargs)
    assert result.trades.get_column("quantity").to_list() == [150]
    assert state["cash"] == pytest.approx(1100.0)
    assert state["nav"][-1]["unit_nav"] == pytest.approx(1.0)


def test_research_replay_rejects_missing_open_using_only_prior_mark():
    from quant.research.classic_monthly_baseline import replay

    kwargs, _ = inputs()
    kwargs["bars"] = kwargs["bars"].filter(pl.col("trade_date") != D2)
    states = dict(kwargs["market_states"])
    states[(D2, SYMBOL)] = DailyMarketState(suspended=True)
    targets = pl.DataFrame({"as_of": [D1], "execution_date": [D2], "symbol": [SYMBOL],
        "strategy": ["test"], "strategy_version": ["v1"], "weight": [1.0]})
    config = {"portfolio": {"initial_cash": 1100.0}, "costs": kwargs["config"]["costs"]}
    nav, trades, rejections = replay(bars=kwargs["bars"], calendar=kwargs["calendar"],
        instruments=kwargs["instruments"], targets=targets, dividends=kwargs["dividends"],
        market_states=states, config=config, sessions=[D2, D3], name="test")
    assert trades.is_empty()
    assert rejections.get_column("reason").to_list() == ["SUSPENDED"]
    assert nav.get_column("equity").to_list() == [1100.0, 1100.0]
    assert nav.get_column("position_count").to_list() == [0, 0]
