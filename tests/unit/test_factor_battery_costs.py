import datetime as dt

import polars as pl

from quant.research.factor_battery_costs import top_group_targets


def test_top_targets_use_next_open_and_cash_when_scores_disappear():
    january, february, march = dt.date(2020, 1, 31), dt.date(2020, 2, 28), dt.date(2020, 3, 31)
    scores = pl.DataFrame({"trade_date": [january]*4+[february]*4+[march]*4,
        "symbol": ["A", "B", "C", "D"]*3, "raw": [1., 2., 3., 4.]+[None]*4+[4., 3., 2., 1.]})
    sessions = (january, dt.date(2020, 2, 3), february, dt.date(2020, 3, 2), march, dt.date(2020, 4, 1))
    targets = top_group_targets(scores, variant="raw", sessions=sessions, end=march,
        settings={"groups": 2, "minimum_symbols": 4}, name="fixture")
    assert targets["symbol"].to_list() == ["C", "D", "A"]
    assert targets["weight"].to_list() == [.5, .5, 0.]
    assert targets["execution_date"].to_list() == [dt.date(2020, 2, 3)]*2+[dt.date(2020, 3, 2)]
    assert targets.filter(pl.col("as_of") >= pl.col("execution_date")).is_empty()


def test_constant_factor_has_no_executable_portfolio():
    day = dt.date(2020, 1, 31)
    scores = pl.DataFrame({"trade_date": [day]*4, "symbol": ["A", "B", "C", "D"], "raw": [1.]*4})
    assert top_group_targets(scores, variant="raw", sessions=(day, dt.date(2020, 2, 3)),
        end=dt.date(2020, 2, 3), settings={"groups": 2, "minimum_symbols": 4}, name="fixture").is_empty()
