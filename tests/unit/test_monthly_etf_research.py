import datetime as dt

import polars as pl

from quant.research.monthly_etf import admission_checks, completed_month_prices, monthly_targets
from quant.strategies.monthly_etf import MonthlyEtfStrategy


def test_partial_month_is_excluded_from_initial_midmonth_decision():
    dates = [dt.date(2024, month, 28) for month in range(1, 13)]
    dates += [dt.date(2025, 1, 10), dt.date(2025, 1, 13), dt.date(2025, 1, 31)]
    calendar = pl.DataFrame({"date": dates, "market": ["SH"] * len(dates), "is_open": [True] * len(dates)})
    prices = pl.DataFrame({"symbol": ["A"] * 13, "trade_date": dates[:13],
        "adjusted_close": [10.] * 11 + [11., 1.]})
    monthly = completed_month_prices(prices, calendar)
    assert monthly["trade_date"].max() == dt.date(2024, 12, 28)
    strategy = MonthlyEtfStrategy(("A",), "sma", 10, top_k=1)
    targets = monthly_targets(prices, calendar, start=dt.date(2025, 1, 11), end=dt.date(2025, 1, 13),
        candidates=("A",), name="fixture", strategy=strategy)
    assert targets["weight"].to_list() == [1.]
    assert targets["as_of"].to_list() == [dt.date(2025, 1, 10)]
    assert targets["execution_date"].to_list() == [dt.date(2025, 1, 13)]


def test_candidate_requires_positive_each_fold_and_forward_relative_performance():
    rows = []
    for fold, start in [(1, "2025-07-01"), (2, "2026-01-01"), (3, "2026-07-11")]:
        for comparison in ["strategy", "s0"]:
            for multiplier in [1., 2.]:
                rows.append({"fold": fold, "test_start": start, "comparison": comparison,
                    "cost_multiplier": multiplier, "total_return": .1 if comparison == "strategy" else .12,
                    "cagr": .1, "max_drawdown": -.1 if comparison == "strategy" else -.2,
                    "annualized_one_way_turnover": 2.})
    settings = {"forward_start": dt.date(2026, 7, 11), "minimum_2x_positive_fold_fraction": .5,
        "maximum_annualized_one_way_turnover": 3., "forward_maximum_shortfall_to_s0": .02}
    assert all(admission_checks(rows, settings).values())
    rows[0]["total_return"] = -.01
    assert not admission_checks(rows, settings)["all_1x_folds_positive"]
    rows[-4]["total_return"] = .09
    assert not admission_checks(rows, settings)["forward_shortfall_within_limit"]
