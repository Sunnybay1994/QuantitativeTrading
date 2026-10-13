"""Scalar checks for Alpha158 extrema, correlation and volume changes."""

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


BATCH = ({f"alpha158_{family}{n}" for family in ("imax", "imin", "imxd", "cord", "vsump", "vsumn", "vsumd")
          for n in (5, 10, 20, 30, 60)}
         | {f"alpha158_corr{n}" for n in (5, 10, 30, 60)} | {"alpha158_wvma60"})


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


def scalar_values(prices, highs, lows, volumes, n):
    high, low = highs[-n:], lows[-n:]
    imax, imin = (high.index(max(high)) + 1) / n, (low.index(min(low)) + 1) / n
    price_ratios = [b / a for a, b in zip(prices[-n-1:-1], prices[-n:])]
    volume_ratios = [math.log(b / a + 1) for a, b in zip(volumes[-n-1:-1], volumes[-n:])]
    changes = [b - a for a, b in zip(volumes[-n-1:-1], volumes[-n:])]
    gain, loss = sum(max(x, 0) for x in changes), sum(max(-x, 0) for x in changes)
    total = sum(abs(x) for x in changes) + 1e-12
    weighted = [abs(r - 1) * v for r, v in zip(price_ratios, volumes[-n:])]
    return {"imax": imax, "imin": imin, "imxd": imax - imin,
            "corr": statistics.correlation(prices[-n:], [math.log(v + 1) for v in volumes[-n:]]),
            "cord": statistics.correlation(price_ratios, volume_ratios),
            "vsump": gain / total, "vsumn": loss / total, "vsumd": (gain - loss) / total,
            "wvma": statistics.stdev(weighted) / (statistics.mean(weighted) + 1e-12)}


def _snap_corr(value: float) -> float:
    """Match expressions.ts_corr near-±1 / near-zero ULP snap."""
    if abs(value) <= 1e-12:
        return 0.0
    if (1.0 - abs(value)) <= 1e-3:
        return 1.0 if value >= 0 else -1.0
    return value


def test_all_forty_formulas():
    panel = prepared(sample_bars())
    expressions = definitions()
    assert len(expressions) == 40
    actual = evaluate_expressions(panel, expressions)
    for symbol in panel["symbol"].unique():
        one = panel.filter(pl.col("symbol") == symbol).sort("trade_date")
        row = actual.filter(pl.col("symbol") == symbol).tail(1).to_dicts()[0]
        for n in (5, 10, 20, 30, 60):
            expected = scalar_values(*[one[name].to_list() for name in ("adj_close", "adj_high", "adj_low", "volume")], n)
            for family, value in expected.items():
                name = f"alpha158_{family}{n}"
                if name in BATCH:
                    if family in {"corr", "cord"}:
                        value = _snap_corr(value)
                    assert row[name] == pytest.approx(value, rel=1e-7, abs=1e-8)


def test_prefix_and_gaps():
    panel = prepared(sample_bars())
    cutoff = dt.date(2020, 3, 5)
    actual = evaluate_expressions(panel, definitions())
    prefix = evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), definitions())
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff), prefix)
    panel = panel.with_columns(*[
        pl.when(pl.col("trade_date") != dt.date(2020, 3, 8)).then(pl.col(name)).alias(name)
        for name in ("adj_close", "adj_high", "adj_low", "volume")
    ])
    last = evaluate_expressions(panel, definitions()).group_by("symbol").last()
    for name in BATCH:
        assert last[name].null_count() == 4


def test_first_tie_and_short_groups():
    panel = pl.DataFrame({"symbol": ["a"] * 6 + ["b"] * 2, "trade_date": list(range(6)) + [0, 1],
                          "x": [3.0, 1.0, 3.0, 1.0, 2.0, 4.0, 1.0, 5.0]})
    actual = evaluate_expressions(panel, {"max": "ts_argmax(x, 5)", "min": "ts_argmin(x, 5)"})
    assert actual["max"].to_list() == [None, None, None, None, 1.0, 5.0, None, None]
    assert actual["min"].to_list() == [None, None, None, None, 2.0, 1.0, None, None]


def test_constant_price_and_volume():
    panel = prepared(sample_bars()).with_columns(
        pl.lit(10.0).alias("adj_close"), pl.lit(1000.0).alias("volume"),
    )
    last = evaluate_expressions(panel, definitions()).group_by("symbol").last()
    for name in BATCH:
        if name.startswith(("alpha158_corr", "alpha158_cord")):
            assert last[name].null_count() == 4
        if name.startswith(("alpha158_vsum", "alpha158_wvma")):
            assert last[name].to_list() == [0.0] * 4
