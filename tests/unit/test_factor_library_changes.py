"""Independent arithmetic checks for Alpha158 frequency and change features."""

import datetime as dt
import statistics
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library
from tests.unit.test_factor_expressions import prepared, sample_bars


BATCH = ({f"alpha158_{family}{n}" for family in ("cntp", "cntn", "cntd", "sump", "sumn", "sumd")
          for n in (5, 10, 20, 30, 60)}
         | {f"alpha158_{family}{n}" for family in ("vma", "vstd") for n in (5, 10, 30, 60)}
         | {f"alpha158_wvma{n}" for n in (5, 10, 30)})


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


def scalar_values(prices, volumes, n):
    changes = [b - a for a, b in zip(prices[-n-1:-1], prices[-n:])]
    weighted = [abs(b / a - 1) * v for a, b, v in zip(prices[-n-1:-1], prices[-n:], volumes[-n:])]
    gain = sum(max(x, 0) for x in changes)
    loss = sum(max(-x, 0) for x in changes)
    total = sum(abs(x) for x in changes) + 1e-12
    up, down = sum(x > 0 for x in changes) / n, sum(x < 0 for x in changes) / n
    return {"cntp": up, "cntn": down, "cntd": up - down,
            "sump": gain / total, "sumn": loss / total, "sumd": (gain - loss) / total,
            "vma": statistics.mean(volumes[-n:]) / (volumes[-1] + 1e-12),
            "vstd": statistics.stdev(volumes[-n:]) / (volumes[-1] + 1e-12),
            "wvma": statistics.stdev(weighted) / (statistics.mean(weighted) + 1e-12)}


def test_all_41_formulas_match_scalar_arithmetic():
    panel = prepared(sample_bars())
    expressions = definitions()
    assert len(expressions) == 41 and set(expressions) == BATCH
    result = evaluate_expressions(panel, expressions)
    for symbol in panel["symbol"].unique():
        one = panel.filter(pl.col("symbol") == symbol).sort("trade_date")
        actual = result.filter(pl.col("symbol") == symbol).tail(1).to_dicts()[0]
        for n in (5, 10, 20, 30, 60):
            for family, expected in scalar_values(one["adj_close"].to_list(), one["volume"].to_list(), n).items():
                name = f"alpha158_{family}{n}"
                if name in BATCH:
                    assert actual[name] == pytest.approx(expected, rel=1e-9, abs=1e-10)


def test_no_future_access_and_null_windows():
    panel = prepared(sample_bars())
    expressions = definitions()
    cutoff = dt.date(2020, 3, 5)
    full = evaluate_expressions(panel, expressions)
    prefix = evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), expressions)
    assert_frame_equal(full.filter(pl.col("trade_date") <= cutoff), prefix)
    panel = panel.with_columns(*[
        pl.when(pl.col("trade_date") != dt.date(2020, 3, 8)).then(pl.col(name)).alias(name)
        for name in ("adj_close", "volume")
    ])
    last = evaluate_expressions(panel, expressions).group_by("symbol").last()
    for name in BATCH:
        assert last[name].null_count() == 4


@pytest.mark.parametrize("trend", [-1, 0, 1])
def test_monotone_and_flat_prices(trend):
    panel = prepared(sample_bars()).with_columns(
        (100 + pl.col("trade_date").dt.ordinal_day() * trend * 0.1).alias("adj_close"),
        pl.lit(1000.0).alias("volume"),
    )
    last = evaluate_expressions(panel, definitions()).group_by("symbol").last()
    for n in (5, 10, 20, 30, 60):
        assert last[f"alpha158_cntp{n}"].to_list() == [float(trend > 0)] * 4
        assert last[f"alpha158_cntn{n}"].to_list() == [float(trend < 0)] * 4
        assert last[f"alpha158_sumd{n}"].to_list() == pytest.approx([float(trend)] * 4)
    if trend == 0:
        for family in ("sump", "sumn", "sumd", "wvma", "vstd"):
            for name in (name for name in BATCH if name.startswith(f"alpha158_{family}")):
                assert last[name].to_list() == [0.0] * 4
