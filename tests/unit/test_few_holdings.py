import datetime as dt

import polars as pl

from quant.research.few_holdings import load_config, lot_constraint_share, momentum_book


def test_config_is_frozen():
    spec = load_config()
    assert spec["top_k"] == 15
    assert len(spec["s2b"]["pool"]) == 12
    assert spec["s2b"]["cash_symbol"] == "511010.SH"


def test_negative_momentum_holds_only_the_bond():
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(400)]
    # Force month changes by using real calendar-ish month ends via sequential dates
    # that cross months: use 20 dates per month.
    rows = []
    day = dt.date(2018, 1, 2)
    for _ in range(36):
        for _session in range(20):
            while day.weekday() >= 5:
                day += dt.timedelta(days=1)
            for symbol, price in (("510300.SH", 1.0), ("511010.SH", 1.0)):
                rows.append({"symbol": symbol, "trade_date": day, "close": price})
            day += dt.timedelta(days=1)
    book = momentum_book(
        pl.DataFrame(rows), pool=["510300.SH", "511010.SH"], cash_symbol="511010.SH", top_k=3,
    )
    assert book["symbol"].unique().to_list() == ["511010.SH"]


def test_lot_constraint_share_uses_the_planner():
    day = dt.date(2024, 6, 28)
    targets = pl.DataFrame({
        "as_of": [day],
        "symbol": ["600000.SH"],
        "weight": [0.01],
    })
    prices = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [day], "close": [100.0]})
    # 1% of 100000 is 1000 yuan, one board lot costs 10000, so the buy is rejected.
    result = lot_constraint_share(targets, prices, cash=100_000)
    assert result["requested"] == 1
    assert result["lot_constraint"] == 1.0
