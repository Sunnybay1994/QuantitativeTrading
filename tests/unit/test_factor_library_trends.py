"""Scalar regression, percentile and boundary checks for Alpha158 batch P2b."""

import datetime as dt
import math
import statistics
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library
from tests.unit.test_factor_expressions import prepared, sample_bars


FAMILIES = ("beta", "rsqr", "resi", "qtlu", "qtld", "rank", "max", "min")
BATCH = {f"alpha158_{name}{n}" for name in FAMILIES for n in (5, 10, 20, 30, 60)}


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


def quantile(values, q):
    ordered = sorted(values)
    index = (len(values) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def test_all_forty_trend_and_distribution_formulas():
    bars = sample_bars()
    expressions = definitions()
    assert set(expressions) == BATCH and len(BATCH) == 40
    result = evaluate_expressions(prepared(bars), expressions)
    for symbol in bars["symbol"].unique():
        one = bars.filter(pl.col("symbol") == symbol).sort("trade_date").to_dicts()
        values = [row["close"] * row["adj_factor"] for row in one]
        actual = result.filter(pl.col("symbol") == symbol).tail(1).to_dicts()[0]
        for n in (5, 10, 20, 30, 60):
            window = values[-n:]
            slope, intercept = statistics.linear_regression(range(n), window)
            current = window[-1]
            less = sum(value < current for value in window)
            ties = sum(value == current for value in window)
            expected = {
                "beta": slope / current,
                "rsqr": statistics.correlation(range(n), window) ** 2,
                "resi": (current - intercept - slope * (n - 1)) / current,
                "qtlu": quantile(window, 0.8) / current,
                "qtld": quantile(window, 0.2) / current,
                "rank": (less + (ties + 1) / 2) / n,
                "max": max(row["high"] * row["adj_factor"] for row in one[-n:]) / current,
                "min": min(row["low"] * row["adj_factor"] for row in one[-n:]) / current,
            }
            for name, value in expected.items():
                assert actual[f"alpha158_{name}{n}"] == pytest.approx(value, rel=1e-8, abs=1e-10)


def test_trend_batch_has_no_future_access_and_does_not_skip_gaps():
    panel = prepared(sample_bars())
    expressions = definitions()
    cutoff = dt.date(2020, 3, 5)
    full = evaluate_expressions(panel, expressions)
    prefix = evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), expressions)
    assert_frame_equal(full.filter(pl.col("trade_date") <= cutoff), prefix)
    gap = dt.date(2020, 3, 8)
    panel = panel.with_columns(*[
        pl.when(pl.col("trade_date") != gap).then(pl.col(name)).alias(name)
        for name in ("adj_close", "adj_high", "adj_low")
    ])
    last = evaluate_expressions(panel, expressions).filter(pl.col("trade_date") == dt.date(2020, 3, 10))
    for name in BATCH:
        assert last[name].null_count() == 4


def test_constant_near_constant_regression_and_rank_ties():
    panel = pl.DataFrame({"symbol": ["a"] * 5,
                          "trade_date": [dt.date(2020, 1, d) for d in range(1, 6)],
                          "x": [10.0] * 5, "tiny": [10 + 1e-6 * d for d in range(5)]})
    row = evaluate_expressions(panel, {"slope": "ts_slope(x, 5)", "residual": "ts_resi(x, 5)",
                                       "fit": "ts_rsquare(x, 5)", "tiny_fit": "ts_rsquare(tiny, 5)",
                                       "rank": "(ts_rank(x, 5)*4+1)/5"}).tail(1).to_dicts()[0]
    assert row["slope"] == row["residual"] == 0
    assert row["fit"] is None and row["tiny_fit"] is None
    assert row["rank"] == pytest.approx(0.6)


@pytest.mark.parametrize("expression", ["ts_quantile(x, 1.1, 5)", "ts_quantile(x, x, 5)", "ts_slope(x, 1)"])
def test_reject_invalid_distribution_parameters(expression):
    panel = pl.DataFrame({"symbol": ["a"], "trade_date": [dt.date(2020, 1, 1)], "x": [1.0]})
    with pytest.raises(ValueError):
        evaluate_expressions(panel, {"bad": expression})
