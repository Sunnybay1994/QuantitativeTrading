import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.classic import CLASSIC_FACTOR_NAMES, compute_classic_daily_factors
from quant.factors.classic_second_batch import (
    SECOND_BATCH_FACTOR_NAMES, compute_second_batch_daily_factors,
)
from quant.factors.classic_sixth_batch import (
    SIXTH_BATCH_FACTOR_NAMES, compute_sixth_batch_daily_factors,
)
from quant.factors.classic_eighth_batch import compute_eighth_batch_daily_factors
from quant.factors.classic_fifth_batch import compute_fifth_batch_daily_factors
from quant.factors.classic_seventh_batch import compute_seventh_batch_daily_factors
from quant.factors.market_size import compute_market_size
from quant.factors.turnover_variability import compute_turnover_variability
from quant.factors.expressions import evaluate_expressions, required_history
from quant.factors.library import load_library
from quant.research.factor_labels import build_next_open_factor_labels


def sample_bars() -> pl.DataFrame:
    rows = []
    for stock in range(4):
        for day in range(70):
            factor = 2.0 if day >= 30 else 1.0
            close = (10 + stock * 5 + day * 0.13 + ((day * (stock + 1)) % 7) * 0.2) / factor
            volume = 1000.0 + ((day * 71 + stock * 29) % 500)
            rows.append({
                "symbol": f"60000{stock}.SH", "trade_date": dt.date(2020, 1, 1) + dt.timedelta(days=day),
                "open": close * 0.99, "high": close * 1.03, "low": close * 0.97,
                "close": close, "volume": volume, "amount": close * volume,
                "adj_factor": factor, "source": "fixture",
            })
    return pl.DataFrame(rows)


def prepared(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.with_columns(
        *[(pl.col(name) * pl.col("adj_factor")).alias(f"adj_{name}")
          for name in ("open", "high", "low", "close")],
        pl.lit(2.0).alias("turnover_rate"), pl.lit(10.0).alias("pb"),
        pl.lit(100.0).alias("total_market_value"), pl.lit(50.0).alias("circulating_market_value"),
    )


def test_batch_matches_existing_twelve_factors_and_split_adjustments():
    bars = sample_bars()
    definitions = load_library(Path("configs/factors/library"))
    panel = prepared(bars).with_columns(
        *[pl.lit("sector").alias(f"industry_l{n}") for n in (1, 2, 3)])
    result = evaluate_expressions(panel, {row.id: row.expr for row in definitions})
    sessions = tuple(sorted(bars["trade_date"].unique()))
    for baseline, names in (
        (compute_classic_daily_factors(bars), CLASSIC_FACTOR_NAMES),
        (compute_second_batch_daily_factors(bars), SECOND_BATCH_FACTOR_NAMES),
        (compute_sixth_batch_daily_factors(bars, sessions=sessions), SIXTH_BATCH_FACTOR_NAMES),
    ):
        columns = ["symbol", "trade_date", *names]
        assert_frame_equal(result.select(columns).sort("symbol", "trade_date"),
                           baseline.select(columns).sort("symbol", "trade_date"),
                           rel_tol=1e-8, abs_tol=1e-10)
    assert set(CLASSIC_FACTOR_NAMES) <= {row.id for row in definitions}


def test_remaining_migrated_formulas_match_existing_functions():
    bars = sample_bars()
    panel = prepared(bars).with_columns(
        *[pl.lit("sector").alias(f"industry_l{n}") for n in (1, 2, 3)])
    definitions = load_library(Path("configs/factors/library"))
    result = evaluate_expressions(panel, {row.id: row.expr for row in definitions})
    sessions = tuple(sorted(bars["trade_date"].unique()))
    for function, name in (
        (compute_eighth_batch_daily_factors, "alpha101_004"),
        (compute_fifth_batch_daily_factors, "max_daily_return_20"),
        (compute_seventh_batch_daily_factors, "alpha101_009"),
    ):
        baseline = function(bars, sessions=sessions).select("symbol", "trade_date", name)
        assert_frame_equal(result.select(baseline.columns).sort("symbol", "trade_date"),
                           baseline.sort("symbol", "trade_date"), rel_tol=1e-8, abs_tol=1e-10)
    # This fixture has open = close * .99 for every stock/day. Its intraday
    # return rank is constant, so #2 correlation is mathematically undefined;
    # the legacy implementation spuriously ranked binary floating-point noise.
    assert result["alpha101_002"].null_count() == result.height
    for baseline in (
        compute_turnover_variability(panel, sessions=sessions),
        compute_market_size(panel),
        compute_market_size(panel, column="circulating_market_value"),
    ):
        assert_frame_equal(result.select(baseline.columns).sort("symbol", "trade_date"),
                           baseline.sort("symbol", "trade_date"), rel_tol=1e-8, abs_tol=1e-10)
    assert result["book_to_price"].to_list() == pytest.approx([0.1] * result.height)


def test_undefined_correlation_is_not_ranked_as_an_extreme():
    panel = pl.DataFrame({"symbol": ["a", "a", "b", "b"],
                          "trade_date": [dt.date(2020, 1, 1), dt.date(2020, 1, 2)] * 2,
                          "x": [1.0, 1.0, 1.0, 2.0]})
    result = evaluate_expressions(panel, {"ranked": "rank(ts_corr(x, x, 2))"})
    assert result["ranked"].null_count() == 4  # only one valid member on day two


def test_window_operators_match_hand_calculation():
    panel = pl.DataFrame({"symbol": ["a"] * 6,
                          "trade_date": [dt.date(2020, 1, d) for d in range(1, 7)],
                          "x": [1.0, 2.0, 3.0, 2.0, 5.0, 4.0]})
    expressions = {"mean": "ts_mean(x, 3)", "sum": "ts_sum(x, 3)",
                   "std": "ts_std(x, 3)", "std0": "ts_std0(x, 3)",
                   "min": "ts_min(x, 3)", "max": "ts_max(x, 3)",
                   "rank": "ts_rank(x, 3)", "argmax": "ts_argmax(x, 3)",
                   "argmin": "ts_argmin(x, 3)", "decay": "decay_linear(x, 3)",
                   "cov": "ts_cov(x, 2*x, 3)", "corr": "ts_corr(x, 2*x, 3)",
                   "delay": "delay(x, 2)", "delta": "delta(x, 2)"}
    result = evaluate_expressions(panel, expressions).tail(1).to_dicts()[0]
    expected = {"mean": 11/3, "sum": 11, "std": (7/3)**0.5, "std0": (14/9)**0.5,
                "min": 2, "max": 5, "rank": 0.5, "argmax": 2, "argmin": 1,
                "decay": 4, "cov": 14/3, "corr": 1, "delay": 2, "delta": 2}
    for key, value in expected.items():
        assert result[key] == pytest.approx(value)


def test_rolling_rank_requires_complete_window_after_listing_or_gap():
    panel = pl.DataFrame({"symbol": ["a"] * 8,
                          "trade_date": [dt.date(2020, 1, d) for d in range(1, 9)],
                          "x": [None, 1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0]})
    result = evaluate_expressions(panel, {"ranked": "ts_rank(x, 3)"})
    assert result["ranked"].to_list() == [None] * 6 + [1.0, 1.0]


def test_prefix_invariance_missing_sessions_and_nested_rank():
    panel = prepared(sample_bars())
    gap = dt.date(2020, 1, 20)
    panel = panel.with_columns(pl.when(pl.col("trade_date") != gap).then(pl.col("adj_close")).alias("adj_close"))
    definitions = {"x": "ts_mean(delta(adj_close, 1), 3)", "r": "ts_rank(rank(adj_close), 5)"}
    result = evaluate_expressions(panel, definitions)
    cutoff = dt.date(2020, 2, 10)
    prefix = evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), definitions)
    assert_frame_equal(result.filter(pl.col("trade_date") <= cutoff), prefix)
    assert result.filter(pl.col("trade_date").is_between(gap, gap + dt.timedelta(days=3)))["x"].null_count() == 16
    assert required_history("ts_corr(rank(delta(log(volume), 2)), rank(close / open), 6)") == 7


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo bad')", "close.__class__", "delay(close, -1)",
    "ts_mean(close, 2.5)", "[close][0]", "unknown(close)", "future_close",
])
def test_reject_non_dsl_and_forward_access(expression):
    with pytest.raises(ValueError):
        evaluate_expressions(prepared(sample_bars()), {"bad": expression})


def test_rank_ties_industry_nulls_and_zero_division():
    panel = pl.DataFrame({"symbol": ["a", "b", "c", "d"],
                          "trade_date": [dt.date(2020, 1, 1)] * 4,
                          "x": [1.0, 1.0, 3.0, 5.0], "industry": ["A", "A", "B", None]})
    result = evaluate_expressions(panel, {"ranked": "rank(x)", "neutral": "ind_neutralize(x, industry)",
                                          "invalid": "0 / 0"})
    assert result["ranked"].to_list() == pytest.approx([1 / 6, 1 / 6, 2 / 3, 1])
    assert result["neutral"].to_list() == [0, 0, 0, None]
    assert result["invalid"].null_count() == 4


def test_next_open_labels_do_not_bridge_missing_session_and_include_split():
    bars = sample_bars()
    dates = tuple(sorted(bars["trade_date"].unique()))
    bars = bars.filter(~((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == dates[31])))
    labels = build_next_open_factor_labels(factor_values=bars.select("symbol", "trade_date"),
                                          bars=bars, sessions=dates, horizons=(1, 5))
    missing = labels.filter((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == dates[29]))
    assert missing["exit_date_1"].item() == dates[31]
    assert missing["label_1"].item() is None
    row = labels.filter((pl.col("symbol") == "600001.SH") & (pl.col("trade_date") == dates[28]))
    expected = bars.filter(pl.col("symbol") == "600001.SH").with_columns(
        (pl.col("open") * pl.col("adj_factor")).alias("adjusted"))
    assert row["label_1"].item() == pytest.approx(expected["adjusted"][30] / expected["adjusted"][29] - 1)
