import datetime as dt

import polars as pl
import pytest

from quant.research.monthly_small_value_quality import select_small_value_quality


def sample():
    return pl.DataFrame({"trade_date": [dt.date(2024, 1, 31)] * 6,
        "symbol": list("ABCDEF"), "circulating_market_value": [1., 2., 3., 4., 5., 6.],
        "pb": [1., 2., 6., 3., 4., 5.], "pit_roe_ttm": [.1, -.1, .1, .1, .1, .1]})


def test_intersection_precedes_the_only_quality_treatment():
    primary, paired = select_small_value_quality(sample(), small_fraction=.5, minimum_candidates=1)
    assert paired["symbol"].to_list() == ["A", "B"]
    assert primary["symbol"].to_list() == ["A"]
    assert paired["cohort_size"].to_list() == [6, 6]


def test_ties_use_symbol_order_and_zero_roe_is_excluded():
    frame = sample().with_columns(pl.lit(1.).alias("pb"), pl.lit(1.).alias("circulating_market_value"),
        pl.when(pl.col("symbol") == "A").then(0.).otherwise(.1).alias("pit_roe_ttm"))
    primary, paired = select_small_value_quality(frame.reverse(), small_fraction=.5, minimum_candidates=1)
    assert paired["symbol"].to_list() == ["A", "B", "C"]
    assert primary["symbol"].to_list() == ["B", "C"]


def test_a_date_with_no_positive_roe_fails_instead_of_disappearing():
    missing = sample().with_columns(pl.lit(dt.date(2024, 2, 29)).alias("trade_date"),
                                    pl.lit(-.1).alias("pit_roe_ttm"))
    with pytest.raises(ValueError, match="target count"):
        select_small_value_quality(pl.concat([sample(), missing]), minimum_candidates=1)


def test_missing_roe_cannot_improve_one_side_by_changing_its_universe():
    frame = sample().with_columns(pl.when(pl.col("symbol") == "B")
        .then(None).otherwise(pl.col("pit_roe_ttm")).alias("pit_roe_ttm"))
    with pytest.raises(ValueError, match="same complete"):
        select_small_value_quality(frame, minimum_candidates=1)
