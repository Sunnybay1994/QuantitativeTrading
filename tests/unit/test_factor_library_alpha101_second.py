"""Independent formulas for Alpha101 price/volume expansion P2f."""

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library
from tests.unit.test_factor_library_alpha101 import sample_panel

def reference_p2f(panel):
    """Use pandas kernels and explicit formulas, independently of the DSL AST."""
    frame = panel.to_pandas()
    wide = {name: frame.pivot(index="trade_date", columns="symbol", values=name).sort_index()
            for name in ("adj_close", "adj_open", "adj_high", "adj_low", "volume", "amount", "adj_factor", "open", "close", "total_market_value")}
    c, o, h, lo, v = [wide[k] for k in ("adj_close", "adj_open", "adj_high", "adj_low", "volume")]
    r, w = c / c.shift(1) - 1, wide["amount"] / v * wide["adj_factor"]

    def rank(x):
        x = x.map(lambda value: float(f"{value:.10g}"))
        return (x.rank(axis=1, method="average") - 1).div(x.count(axis=1) - 1, axis=0)

    def scale(x):
        return x.div(x.abs().sum(axis=1).replace(0, np.nan), axis=0)

    def mean(x, n):
        return x.rolling(n, min_periods=n).mean()

    def total(x, n):
        return x.rolling(n, min_periods=n).sum()

    def std(x, n):
        return x.rolling(n, min_periods=n).std(ddof=1)

    def low(x, n):
        return x.rolling(n, min_periods=n).min()

    def high(x, n):
        return x.rolling(n, min_periods=n).max()

    def corr(x, y, n):
        valid = (high(x, n) > low(x, n)) & (high(y, n) > low(y, n))
        return x.rolling(n, min_periods=n).corr(y).replace([np.inf, -np.inf], np.nan).clip(-1, 1).where(valid)

    def cov(x, y, n):
        constant = (high(x, n) == low(x, n)) | (high(y, n) == low(y, n))
        return x.rolling(n, min_periods=n).cov(y).mask(constant, 0)

    def trank(x, n):
        x = x.map(lambda value: float(f"{value:.10g}"))
        return x.rolling(n, min_periods=n).apply(
            lambda a: (np.sum(a < a[-1]) + (np.sum(a == a[-1]) - 1) / 2) / (n - 1), raw=True,
        )

    def where(left, op, right, yes, no):
        # pandas comparisons turn missing into False; preserve the DSL null mask.
        valid = left.notna() & (right.notna() if isinstance(right, pd.DataFrame) else True)
        return pd.DataFrame(np.where(op(left, right), yes, no), index=c.index, columns=c.columns).where(valid)

    gt, lt = np.greater, np.less
    def a(n):
        return mean(wide['amount'], n)
    def decay(x, n):
        return x.rolling(n).apply(lambda z: np.dot(z, np.arange(1, n + 1)) / (n * (n + 1) / 2), raw=True)
    def argmax(x, n):
        return x.rolling(n).apply(lambda z: np.argmax(z) + 1, raw=True)
    def maximum(x, y):
        return where(x, gt, y, x, y)
    def negcompare(x, y):
        return where(x, lt, y, -1., 0.)
    z = (c.shift(20) - c.shift(10)) / 10 - (c.shift(10) - c) / 10
    e = {}
    e[37] = rank(corr((o - c).shift(1), c, 200)) + rank(o - c)
    e[38] = -rank(trank(c, 10)) * rank(c / o)
    e[39] = -rank(c.diff(7) * (1 - rank(decay(v / a(20), 9)))) * (1 + rank(total(r, 250)))
    e[40] = -rank(std(h, 10)) * corr(h, v, 10)
    e[42] = rank(w - c) / rank(w + c).replace(0, np.nan)
    e[43] = trank(v / a(20), 20) * trank(-c.diff(7), 8)
    e[44] = -corr(h, rank(v), 5)
    e[45] = -rank(mean(c.shift(5), 20)) * corr(c, v, 2) * rank(corr(total(c, 5), total(c, 20), 2))
    e[46] = where(z, gt, .25, -1, where(z, lt, 0, 1, -c.diff()))
    e[47] = rank(1 / c) * v / a(20) * (h * rank(h - c) / mean(h, 5)) - rank(w.diff(5))
    e[49] = where(z, lt, -.1, 1, -c.diff())
    e[50] = -high(rank(corr(rank(v), rank(w), 5)), 5)
    e[51] = where(z, lt, -.05, 1, -c.diff())
    e[52] = (-low(lo, 5) + low(lo, 5).shift(5)) * rank((total(r, 240) - total(r, 20)) / 220) * trank(v, 5)
    e[53] = -((c - lo - (h - c)) / (c - lo).replace(0, np.nan)).diff(9)
    e[54] = -(lo - c) * o ** 5 / ((lo - h) * c ** 5).replace(0, np.nan)
    e[55] = -corr(rank((c - low(lo, 12)) / (high(h, 12) - low(lo, 12)).replace(0, np.nan)), rank(v), 6)
    e[56] = -rank(total(r, 10) / total(total(r, 2), 3).replace(0, np.nan)) * rank(r * wide['total_market_value'])
    e[57] = -(c - w) / decay(rank(argmax(c, 30)), 2).replace(0, np.nan)
    e[60] = -2 * scale(rank((c - lo - (h - c)) / (h - lo).replace(0, np.nan) * v)) + scale(rank(argmax(c, 10)))
    e[61] = where(rank(w - low(w, 16)), lt, rank(corr(w, a(180), 17)), 1, 0)
    e[62] = negcompare(rank(corr(w, total(a(20), 22), 9)), rank(where(rank(o) + rank(o), lt, rank((h + lo) / 2) + rank(h), 1, 0)))
    e[64] = negcompare(rank(corr(total(o * .178404 + lo * (1 - .178404), 12), total(a(120), 12), 16)), rank(((h + lo) / 2 * .178404 + w * (1 - .178404)).diff(3)))
    e[65] = negcompare(rank(corr(o * .00817205 + w * (1 - .00817205), total(a(60), 8), 6)), rank(o - low(o, 13)))
    e[66] = -(rank(decay(w.diff(3), 7)) + trank(decay((lo - w) / (o - (h + lo) / 2).replace(0, np.nan), 11), 6))
    e[68] = negcompare(trank(corr(rank(h), rank(a(15)), 8), 13), rank((c * .518371 + lo * (1 - .518371)).diff()))
    e[71] = maximum(trank(decay(corr(trank(c, 3), trank(a(180), 12), 18), 4), 15), trank(decay(rank(lo + o - 2 * w) ** 2, 16), 4))
    e[72] = rank(decay(corr((h + lo) / 2, a(40), 8), 10)) / rank(decay(corr(trank(w, 3), trank(v, 18), 6), 2)).replace(0, np.nan)
    mixed = o * .147155 + lo * (1 - .147155)
    e[73] = -maximum(rank(decay(w.diff(4), 2)), trank(decay(-mixed.diff(2) / mixed, 3), 16))
    e[74] = negcompare(rank(corr(c, total(a(30), 37), 15)), rank(corr(rank(h * .0261661 + w * (1 - .0261661)), rank(v), 11)))
    return {f'alpha101_{n:03d}': x for n, x in e.items()}


BATCH = {f"alpha101_{n:03d}" for n in (
    37, 38, 39, 40, 42, 43, 44, 45, 46, 47, 49, 50, 51, 52, 53,
    54, 55, 56, 57, 60, 61, 62, 64, 65, 66, 68, 71, 72, 73, 74,
)}


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


@pytest.mark.parametrize("missing", [False, True])
def test_thirty_formulas_and_future_truncation(missing):
    panel = sample_panel().with_columns((pl.col("close") * 100000000).alias("total_market_value"))
    if missing:
        gap = dt.date(2020, 10, 15)
        panel = panel.with_columns(*[
            pl.when(~((pl.col("symbol") == "000003.SZ") & (pl.col("trade_date") == gap))).then(pl.col(name)).alias(name)
            for name in panel.columns if name not in ("symbol", "trade_date")
        ])
    exprs = definitions()
    assert set(exprs) == BATCH and len(exprs) == 30
    actual = evaluate_expressions(panel, exprs)
    cutoff = dt.date(2020, 12, 1)
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff),
                       evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), exprs))
    flat = actual.to_pandas()
    for name, expected in reference_p2f(panel).items():
        values = flat.pivot(index="trade_date", columns="symbol", values=name).sort_index()
        np.testing.assert_allclose(values, expected, atol=1e-7, rtol=1e-6, equal_nan=True, err_msg=name)


def test_time_rank_uses_numerical_ties():
    panel = pl.DataFrame({"symbol": ["a"] * 4, "trade_date": list(range(4)),
                          "x": [0.7108343337334933, 0.7124849939975989, 0.7436974789915964, 0.7436974789915966]})
    result = evaluate_expressions(panel, {"rank": "ts_rank(x, 4)"})
    assert result["rank"].to_list() == [None, None, None, pytest.approx(5 / 6)]
