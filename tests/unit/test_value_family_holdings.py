import datetime as dt

import polars as pl
import pytest

from quant.research.value_family_evidence import annual_security_bridge, returns
from quant.research.value_family_holdings import holdings_evidence, snapshot_overlap


def test_saved_return_keeps_boundary_loss():
    dates = [dt.date(2020, 1, 2), dt.date(2020, 1, 3), dt.date(2020, 1, 6)]
    nav = pl.DataFrame({"date": dates, "unit_nav": [2., 1.8, 1.98], "equity": [200., 180., 198.]})
    part = returns(nav, dates[1], dates[-1])
    assert part["return"].to_list() == pytest.approx([-.1, .1])
    assert part["prior_equity"].to_list() == [200., 180.]


def snapshot(date, quantity, value, equity):
    return {"date": date, "equity": equity, "frame": pl.DataFrame({"symbol": ["A"], "quantity": [float(quantity)],
             "mark_price": [value / quantity], "value": [float(value)]})}


def test_mark_trade_bridge_does_not_invent_dividend_attribution():
    before = snapshot(dt.date(2019, 12, 31), 100, 1000., 2000.)
    after = snapshot(dt.date(2020, 12, 31), 80, 880., 2168.)
    trades = pl.DataFrame({"date": [dt.date(2020, 6, 1)], "symbol": ["A"], "side": ["SELL"],
        "quantity": [20.], "notional": [240.], "fee": [2.], "slippage_cost": [4.]})
    a = {"identity": {"account": "x"}, "snapshots": {2019: before, 2020: after}, "trades": trades}
    rows, totals = annual_security_bridge(a, [2020])
    assert rows[0]["quantity_consistent"]
    # 880 - 1000 + 240 - 2 = 118. Already executed notional includes slippage.
    assert rows[0]["mark_trade_bridge_cny"] == 118.
    assert totals[0]["unallocated_distributions_and_other_cash_cny"] == 50.
    assert totals[0]["equity_gain"] == 168.


def test_unexplained_share_change_stays_unidentified():
    before = snapshot(dt.date(2019, 12, 31), 100, 1000., 2000.)
    after = snapshot(dt.date(2020, 12, 31), 200, 1100., 2100.)
    tr = pl.DataFrame(schema={"date": pl.Date, "symbol": pl.String, "side": pl.String, "quantity": pl.Float64,
                              "notional": pl.Float64, "fee": pl.Float64})
    rows, totals = annual_security_bridge({"identity": {}, "snapshots": {2019: before, 2020: after}, "trades": tr}, [2020])
    assert not rows[0]["quantity_consistent"]
    assert rows[0]["unexplained_quantity"] == 100.
    assert totals[0]["top5_positive_bridge_share"] is None


def test_other_vintage_exposure_not_filled_by_current_controls():
    date = dt.date(2020, 12, 31)
    a = {"identity": {"account": "q10", "snapshot_identity": "old"}, "snapshots": {2020: snapshot(date, 100, 1000, 2000)}}
    controls = pl.DataFrame({"trade_date": [date], "symbol": ["A"], "eligible": [True],
                             "total_market_value": [1000.], "industry_l1": ["industry"]})
    summary, positions = holdings_evidence([a], controls)
    assert summary["industry_unknown_equity_weight"][0] == .5
    assert summary["smallest_quartile_equity_weight"][0] is None
    assert positions["industry_l1"][0] is None


def test_snapshot_overlap_uses_equity_weight_and_exact_date():
    date = dt.date(2020, 12, 31)
    a = {"identity": {"account": "a", "cost": 1}, "snapshots": {2020: snapshot(date, 100, 1000., 2000.)}}
    b = {"identity": {"account": "b", "cost": 1}, "snapshots": {2020: snapshot(date, 100, 1000., 4000.)}}
    assert snapshot_overlap(a, b, 2020)["shared_equity_weight"] == .25
    b["snapshots"][2020]["date"] = dt.date(2020, 12, 30)
    assert snapshot_overlap(a, b, 2020) is None
