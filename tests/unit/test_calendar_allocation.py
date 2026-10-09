import datetime as dt

import numpy as np
import pandas as pd
import polars as pl
import pytest

from quant.research.calendar_allocation import paired_bootstrap, statistics
from quant.strategies.calendar_allocation import calendar_targets


def calendar():
    days = [d.date() for d in pd.bdate_range("2023-10-01", "2024-02-05")
            if d.date() != dt.date(2024, 1, 1)]
    return pl.DataFrame(dict(market=["SH"] * len(days), date=days, is_open=[True] * len(days)))


def build(name="calendar_bond", **overrides):
    kwargs = dict(start=dt.date(2023, 11, 1), end=dt.date(2024, 1, 31), name=name,
                  equity_symbol="510300.SH", bond_symbol="511010.SH")
    kwargs.update(overrides)
    return calendar_targets(calendar(), **kwargs)


def test_exchange_sessions_holidays_and_month_boundary():
    targets, schedule = build()
    eq = targets.filter(pl.col("symbol") == "510300.SH")
    weights = dict(eq.select("execution_date", "weight").iter_rows())
    assert weights[dt.date(2023, 11, 30)] == .25
    assert dt.date(2023, 12, 1) not in weights  # Same active window, no artificial rebalance.
    assert weights[dt.date(2023, 12, 6)] == 0
    assert weights[dt.date(2023, 12, 29)] == .25
    assert weights[dt.date(2024, 1, 5)] == 0  # Jan 1 exchange holiday excluded.
    assert (targets["as_of"] < targets["execution_date"]).all()
    assert schedule.filter(pl.col("date") == dt.date(2024, 1, 2))["as_of"].item() == dt.date(2023, 12, 29)


def test_end_date_does_not_invent_month_end_or_change_prior_signals():
    full, _ = build()
    truncated, _ = build(end=dt.date(2023, 12, 15))
    assert truncated.equals(full.filter(pl.col("execution_date") <= dt.date(2023, 12, 15)))
    bad = calendar().filter(pl.col("date") <= dt.date(2024, 1, 31))
    with pytest.raises(ValueError, match="next-month"):
        calendar_targets(bad, start=dt.date(2023, 11, 1), end=dt.date(2024, 1, 31),
                         name="calendar_bond", equity_symbol="EQ", bond_symbol="BD")


def test_static_control_matches_calendar_target_exposure_without_price_fit():
    _, primary = build()
    targets, static = build("static_calendar_exposure")
    for month in [11, 12, 1]:
        p = primary.filter(pl.col("date").dt.month() == month)
        s = static.filter(pl.col("date").dt.month() == month)
        assert s["equity_target"].mean() == pytest.approx(p["equity_target"].mean())
    assert targets.filter(pl.col("symbol") == "510300.SH").height == 3
    sums = targets.group_by("execution_date").agg(pl.col("weight").sum())
    assert np.allclose(sums["weight"], 1.)


def test_cash_control_preserves_bond_sleeve_and_no_negative_weights():
    targets, schedule = build("calendar_cash")
    assert schedule["bond_target"].unique().to_list() == [.75]
    assert targets["weight"].min() >= 0
    assert targets.group_by("execution_date").agg(pl.col("weight").sum())["weight"].max() == 1


def test_bootstrap_pairing_identical_series_has_exact_zero_gain():
    r = pd.Series(np.random.default_rng(7).normal(0, .01, 800), index=pd.bdate_range("2019-01-01", periods=800))
    result = paired_bootstrap(r, r.copy(), samples=30, block_months=12, seed=7)
    assert result["lower_95"] == result["upper_95"] == result["annualized_log_excess"] == 0
    with pytest.raises(ValueError, match="aligned"):
        paired_bootstrap(r, r.iloc[1:], samples=30, block_months=12, seed=7)


def test_drawdown_includes_loss_on_first_held_day():
    r = pd.Series([-.1, .01], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    assert statistics(r)["max_drawdown"] == pytest.approx(-.1)


def test_duplicate_calendar_fails_closed():
    c = calendar()
    with pytest.raises(ValueError, match="Duplicate"):
        calendar_targets(pl.concat([c, c.tail(1)]), start=dt.date(2023, 11, 1), end=dt.date(2024, 1, 31),
                         name="calendar_bond", equity_symbol="EQ", bond_symbol="BD")


def test_emergency_closure_is_not_known_before_announcement():
    dates = [d.date() for d in pd.bdate_range("2019-12-01", "2020-03-03")
        if d.date() != dt.date(2020, 1, 1) and not dt.date(2020, 1, 24) <= d.date() <= dt.date(2020, 2, 2)]
    c = pl.DataFrame(dict(market=["SH"]*len(dates), date=dates, is_open=[True]*len(dates)))
    revisions = [dict(session=dt.date(2020, 1, 31), previous_open=True, final_open=False, announced_date=dt.date(2020, 1, 27))]
    kwargs = dict(start=dt.date(2020, 1, 2), end=dt.date(2020, 2, 28),
                  equity_symbol="EQ", bond_symbol="BD", calendar_revisions=revisions)
    targets, schedule = calendar_targets(c, name="calendar_bond", **kwargs)
    eq = targets.filter(pl.col("symbol") == "EQ")
    assert dt.date(2020, 1, 23) not in eq["execution_date"].to_list()
    assert eq.filter(pl.col("execution_date") == dt.date(2020, 2, 3))["weight"].item() == .25
    _, static = calendar_targets(c, name="static_calendar_exposure", **kwargs)
    january = static.filter(pl.col("date") == dt.date(2020, 1, 2))
    assert january["calendar_sessions"].item() == 17  # Jan31 still scheduled open then.
    assert january["equity_target"].item() == pytest.approx(.25*4/17)
    february = schedule.filter(pl.col("date") == dt.date(2020, 2, 3))
    assert february["decision_date"].item() == dt.date(2020, 2, 2)


def test_continuous_account_lots_three_costs_and_no_same_day_roundtrip():
    import copy
    import tomllib
    from pathlib import Path
    from quant.data.etf_paper_inputs import etf_session_states
    from quant.research.classic_monthly_baseline import replay

    spec = tomllib.loads(Path("configs/research/calendar_allocation_v1.toml").read_text())
    c = calendar().with_columns(pl.lit(False).alias("is_connect_open"), pl.lit(False).alias("is_half_day"))
    target, _ = build(end=dt.date(2023, 12, 7))
    names = ["510300.SH", "511010.SH"]
    bars = pl.DataFrame([dict(symbol=s, trade_date=d, open=p, high=p, low=p, close=p,
        volume=1000000., amount=1000000.*p, adj_factor=1., source="fixture")
        for d in c["date"] for s, p in zip(names, [4., 100.])])
    instruments = pl.DataFrame(dict(symbol=names, market=["SH"]*2, name=names,
        instrument_type=["ETF"]*2, currency=["CNY"]*2, list_date=[dt.date(2012, 1, 1)]*2,
        delist_date=[None]*2, board_lot=[100]*2, status=["LISTED"]*2))
    dividends = pl.DataFrame(schema={"symbol": pl.String, "ann_date": pl.Date, "record_date": pl.Date,
                                    "ex_date": pl.Date, "pay_date": pl.Date, "div_cash": pl.Float64})
    sessions = c.filter(pl.col("date").is_between(dt.date(2023, 11, 1), dt.date(2023, 12, 7)))["date"].to_list()
    ending = []
    for cost in [.5, 1., 2.]:
        settings = dict(portfolio=dict(initial_cash=100000.), costs=copy.deepcopy(spec["costs"]))
        for field in ["commission_rate", "commission_min", "slippage", "slippage_per_share"]:
            settings["costs"]["etf"][field] *= cost
        states = etf_session_states(bars, dividends, slippage_per_share=.001*cost)
        nav, fills, _ = replay(bars=bars, calendar=c, instruments=instruments, targets=target,
            dividends=dividends, market_states=states, config=settings, sessions=sessions,
            name="calendar_bond", validate_once=True)
        assert nav.height == len(sessions)
        assert nav["cash"].min() >= 0
        assert (fills["quantity"] % 100 == 0).all()
        assert fills.group_by("date", "symbol").agg(pl.col("side").n_unique())["side"].max() == 1
        expected = 100000. - fills["fee"].sum() - fills["slippage_cost"].sum()
        assert nav["equity"][-1] == pytest.approx(expected, abs=1e-7)
        ending.append(nav["equity"][-1])
    assert ending[0] > ending[1] > ending[2]
