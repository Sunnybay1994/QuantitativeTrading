import datetime as dt

import polars as pl
import pytest

from quant.research.weekly_etf_targets import weekly_targets
from quant.strategies.weekly_etf_reversal import WeeklyEtfReversalStrategy


def inputs():
    dates = [dt.date(2025, 12, 22) + dt.timedelta(days=i) for i in range(26)]
    dates = [d for d in dates if d.weekday() < 5 and d != dt.date(2026, 1, 1)]
    calendar = pl.DataFrame(
        {"market": ["SH"] * len(dates), "date": dates, "is_open": [True] * len(dates)}
    )
    rows = [
        {"symbol": s, "trade_date": d, "adjusted_close": 100.0 + i * slope}
        for s, slope in [("A", -1), ("B", 0), ("C", 1), ("D", -2)]
        for i, d in enumerate(dates)
    ]
    return dates, calendar, pl.DataFrame(rows)


def test_selects_losers_with_exact_five_session_return_and_no_future():
    dates, _, prices = inputs()
    strategy = WeeklyEtfReversalStrategy(("A", "B", "C", "D"), top_k=2)
    as_of = dates[8]
    actual = strategy.target_weights(as_of, prices)
    assert actual["weight"].to_list() == [0.5, 0.0, 0.0, 0.5]
    future = prices.with_columns(
        pl.when(pl.col("trade_date") > as_of)
        .then(1e9)
        .otherwise(pl.col("adjusted_close"))
        .alias("adjusted_close")
    )
    assert actual.equals(strategy.target_weights(as_of, future))
    # Alter a price earlier than the six required observations: it must not affect selection.
    older = prices.with_columns(
        pl.when(pl.col("trade_date") < dates[3])
        .then(1e9)
        .otherwise(pl.col("adjusted_close"))
        .alias("adjusted_close")
    )
    assert actual.equals(strategy.target_weights(as_of, older))


def test_ties_use_symbol_order_and_allocation_sums_to_one():
    dates, _, prices = inputs()
    prices = prices.with_columns(pl.lit(100.0).alias("adjusted_close"))
    result = WeeklyEtfReversalStrategy(("D", "C", "B", "A")).target_weights(dates[8], prices)
    assert result["weight"].to_list() == [0.0, 1 / 3, 1 / 3, 1 / 3]
    assert result["weight"].sum() == pytest.approx(1.0)


@pytest.mark.parametrize("problem", ["gap", "duplicate", "nan", "zero"])
def test_bad_price_history_fails(problem):
    dates, _, prices = inputs()
    mask = (pl.col("symbol") == "A") & (pl.col("trade_date") == dates[6])
    if problem == "gap":
        prices = prices.filter(~mask)
    elif problem == "duplicate":
        prices = pl.concat([prices, prices.filter(mask)])
    else:
        prices = prices.with_columns(
            pl.when(mask)
            .then(float("nan") if problem == "nan" else 0.0)
            .otherwise(pl.col("adjusted_close"))
            .alias("adjusted_close")
        )
    with pytest.raises(ValueError):
        WeeklyEtfReversalStrategy(("A", "B", "C", "D")).target_weights(dates[8], prices)


def test_midweek_start_holiday_and_year_boundary_use_completed_week():
    _, calendar, prices = inputs()
    strategy = WeeklyEtfReversalStrategy(("A", "B", "C", "D"))
    targets = weekly_targets(
        prices,
        calendar,
        start=dt.date(2026, 1, 7),
        end=dt.date(2026, 1, 15),
        candidates=strategy.candidates,
        name=strategy.name,
        strategy=strategy,
    )
    assert targets.select("as_of", "execution_date").unique().sort("execution_date").rows() == [
        (dt.date(2026, 1, 2), dt.date(2026, 1, 7)),
        (dt.date(2026, 1, 9), dt.date(2026, 1, 12)),
    ]
    assert (targets["as_of"] < targets["execution_date"]).all()
    # Every symbol missing the same exchange day is still a gap, not a shorter lookback.
    with pytest.raises(ValueError, match="Missing exchange session"):
        weekly_targets(
            prices.filter(pl.col("trade_date") != dt.date(2025, 12, 30)),
            calendar,
            start=dt.date(2026, 1, 7),
            end=dt.date(2026, 1, 8),
            candidates=strategy.candidates,
            name=strategy.name,
            strategy=strategy,
        )


def test_weekly_equal_weight_uses_identical_execution_dates():
    _, calendar, prices = inputs()
    strategy = WeeklyEtfReversalStrategy(("A", "B", "C", "D"))
    args = dict(
        start=dt.date(2026, 1, 7),
        end=dt.date(2026, 1, 15),
        candidates=strategy.candidates,
        name="test",
    )
    selected = weekly_targets(prices, calendar, **args, strategy=strategy)
    equal = weekly_targets(prices, calendar, **args, strategy=None)
    assert selected.select("as_of", "execution_date").equals(
        equal.select("as_of", "execution_date")
    )
    assert equal["weight"].to_list() == [0.25] * equal.height
