import datetime as dt

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.factor_battery_groups import (
    assign_groups, group_returns, persistence, summarize_groups,
)
from quant.research.factor_battery_statistics import session_ic_summary


def test_group_membership_precedes_labels_and_preserves_ties_and_missing_months():
    dates = tuple(dt.date(2020, month, 28) for month in range(1, 5))
    frame = pl.DataFrame([{"trade_date": date, "symbol": f"s{i:02}",
        "score": float(i if index != 1 else 19-i)}
        for index, date in enumerate(dates) if index != 2 for i in range(20)])
    cohort = assign_groups(frame, score="score", groups=2, minimum_symbols=20)
    labels = frame.select("symbol", "trade_date", (pl.col("score")/1000).alias("return"))
    labels = labels.with_columns(pl.when((pl.col("symbol") == "s19")
        & (pl.col("trade_date") == dates[0])).then(None).otherwise(pl.col("return")).alias("return"))
    output = group_returns(cohort, labels, label="return", signal_dates=dates, groups=2)
    top = output.filter((pl.col("trade_date") == dates[0]) & (pl.col("group") == 2)).row(0, named=True)
    assert (top["members"], top["paired"], top["paired_coverage"]) == (10, 9, .9)
    assert top["mean_return"] is None
    relaxed = group_returns(cohort, labels, label="return", signal_dates=dates, groups=2,
        minimum_paired_coverage=.9)
    assert relaxed.filter((pl.col("trade_date") == dates[0]) & (pl.col("group") == 2))[
        "mean_return"].item() == pytest.approx(np.mean(np.arange(10,19)/1000))
    assert output.filter(pl.col("trade_date") == dates[2])["members"].to_list() == [0,0]
    # Future outcomes and input ordering cannot change the selected groups.
    shuffled = frame.reverse().join(labels, on=["symbol", "trade_date"])
    assert_frame_equal(cohort, assign_groups(shuffled, score="score", groups=2, minimum_symbols=20))
    stats = persistence(cohort, signal_dates=dates, groups=2, minimum_symbols=20)
    assert stats["rank_autocorrelation"].to_list() == [pytest.approx(-1), None, None]
    assert stats["top_target_turnover"].to_list() == [pytest.approx(1), None, None]
    tied = frame.filter(pl.col("trade_date") == dates[0]).with_columns((pl.col("score") >= 10).cast(pl.Float64))
    ties = assign_groups(tied, score="score", groups=10, minimum_symbols=20)
    assert set(ties["group"]) == {3,8}
    empty_top = persistence(pl.concat([ties, ties.with_columns(pl.lit(dates[1]).alias("trade_date"))]),
        signal_dates=dates[:2], minimum_symbols=20)
    assert empty_top["top_target_turnover"].item() is None


def test_group_summary_uses_nonoverlapping_months_and_keeps_coverage():
    dates = [dt.date(2020,month,28) for month in range(1,4)]
    values = {1:[-.01,.01,0.], 2:[.02,.04,None]}
    frame = pl.DataFrame([{"trade_date": date, "group": group, "mean_return": value}
        for group, sequence in values.items() for date, value in zip(dates, sequence)])
    summary = summarize_groups(frame, groups=2)
    assert summary["groups"][1]["months"] == 2
    assert summary["groups"][1]["annualized_return"] == pytest.approx((1.02*1.04)**6-1)
    assert summary["long_short_months"] == 2
    # Constant spread has no estimated risk, so its Sharpe is unavailable.
    assert summary["long_short_sharpe"] is None
    assert summary["group_mean_rank_monotonicity"] == pytest.approx(1)


def test_daily_hac_lag_counts_exchange_sessions_instead_of_observed_rows():
    sessions = tuple(dt.date(2020,1,1)+dt.timedelta(days=i) for i in range(8))
    dates, values = [sessions[i] for i in (0,2,4,7)], [.01,.04,-.02,.06]
    actual = session_ic_summary(dates, values, sessions=sessions, lag=1)
    centered = np.array(values)-np.mean(values)
    expected = np.mean(values)/np.sqrt(np.sum(centered**2)/len(values)**2)
    assert actual["sessions"] == 4 and actual["newey_west_t"] == pytest.approx(expected)
    with pytest.raises(ValueError):
        session_ic_summary(dates, values, sessions=sessions[:5])
