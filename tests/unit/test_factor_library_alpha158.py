"""Scalar checks for the first Qlib Alpha158 library expansion."""

import datetime as dt
import statistics
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library
from tests.unit.test_factor_expressions import prepared, sample_bars


SHAPES = ("kmid", "klen", "kmid2", "kup", "kup2", "klow", "klow2", "ksft", "ksft2",
          "open0", "high0", "low0", "vwap0", "vstd20")
BATCH = {f"alpha158_{name}" for name in SHAPES} | {
    f"alpha158_{name}{window}" for name in ("roc", "ma", "std", "rsv") for window in (5, 10, 30, 60)
}


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


def test_all_thirty_values_match_scalar_official_formulas():
    bars = sample_bars()
    expressions = definitions()
    assert set(expressions) == BATCH and len(BATCH) == 30
    actual = evaluate_expressions(prepared(bars), expressions)
    for symbol in bars["symbol"].unique():
        one = bars.filter(pl.col("symbol") == symbol).sort("trade_date")
        last = one.tail(1).to_dicts()[0]
        result = actual.filter(pl.col("symbol") == symbol).tail(1).to_dicts()[0]
        opening, high, low, close = (last[key] for key in ("open", "high", "low", "close"))
        full_range = high - low + 1e-12
        expected = {
            "kmid": (close - opening) / opening, "klen": (high - low) / opening,
            "kmid2": (close - opening) / full_range,
            "kup": (high - max(opening, close)) / opening,
            "kup2": (high - max(opening, close)) / full_range,
            "klow": (min(opening, close) - low) / opening,
            "klow2": (min(opening, close) - low) / full_range,
            "ksft": (2 * close - high - low) / opening,
            "ksft2": (2 * close - high - low) / full_range,
            "open0": opening / close, "high0": high / close, "low0": low / close,
            "vwap0": last["amount"] / last["volume"] / close,
            "vstd20": statistics.stdev(one["volume"].tail(20).to_list()) / (last["volume"] + 1e-12),
        }
        adjusted = {name: [row[name] * row["adj_factor"] for row in one.iter_rows(named=True)]
                    for name in ("close", "high", "low")}
        current = adjusted["close"][-1]
        for window in (5, 10, 30, 60):
            closes = adjusted["close"][-window:]
            bottom, top = min(adjusted["low"][-window:]), max(adjusted["high"][-window:])
            expected.update({
                f"roc{window}": adjusted["close"][-window - 1] / current,
                f"ma{window}": statistics.mean(closes) / current,
                f"std{window}": statistics.stdev(closes) / current,
                f"rsv{window}": (current - bottom) / (top - bottom + 1e-12),
            })
        for name, value in expected.items():
            assert result[f"alpha158_{name}"] == pytest.approx(value, rel=1e-9, abs=1e-12)


def test_batch_prefix_and_missing_sixty_session_window():
    panel = prepared(sample_bars())
    expressions = definitions()
    cutoff = dt.date(2020, 2, 20)
    full = evaluate_expressions(panel, expressions)
    prefix = evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), expressions)
    assert_frame_equal(full.filter(pl.col("trade_date") <= cutoff), prefix)
    gap = dt.date(2020, 1, 20)
    panel = panel.with_columns(*[
        pl.when(pl.col("trade_date") != gap).then(pl.col(column)).alias(column)
        for column in ("adj_close", "adj_low", "adj_high")
    ])
    missing = evaluate_expressions(panel, expressions).filter(pl.col("trade_date") == dt.date(2020, 3, 10))
    for name in ("alpha158_ma60", "alpha158_std60", "alpha158_rsv60"):
        assert missing[name].null_count() == missing.height
