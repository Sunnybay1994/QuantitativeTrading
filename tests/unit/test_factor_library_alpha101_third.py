"""Independent formulas for Alpha101 remaining price/volume expansion P2g."""

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

def reference_p2g(panel):
    """Use pandas kernels and explicit formulas, independently of the DSL AST."""
    frame = panel.to_pandas()
    wide = {name: frame.pivot(index="trade_date", columns="symbol", values=name).sort_index()
            for name in ("adj_close", "adj_open", "adj_high", "adj_low", "volume", "amount", "adj_factor", "open", "close", "total_market_value")}
    c, o, h, lo, v = [wide[k] for k in ("adj_close", "adj_open", "adj_high", "adj_low", "volume")]
    w = wide["amount"] / v * wide["adj_factor"]

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
    def minimum(x, y):
        return where(x, lt, y, x, y)
    def argmin(x, n):
        return x.rolling(n).apply(lambda z: np.argmin(z) + 1, raw=True)
    def power(x, y):
        return (x ** y).where(x.notna() & y.notna())
    e = {}
    e[75] = where(rank(corr(w, v, 4)), lt, rank(corr(rank(lo), rank(a(50)), 12)), 1., 0.)
    e[77] = minimum(rank(decay((h + lo) / 2 - w, 20)), rank(decay(corr((h + lo) / 2, a(40), 3), 5)))
    e[78] = power(rank(corr(total(lo * .352233 + w * (1 - .352233), 19), total(a(40), 19), 6)), rank(corr(rank(w), rank(v), 5)))
    product = rank(rank(corr(w, total(a(10), 49), 8)) ** 4).rolling(14).apply(np.prod, raw=True)
    e[81] = negcompare(rank(np.log(product.where(product > 0))), rank(corr(rank(w), rank(v), 5)))
    spread = (h - lo) / mean(c, 5)
    e[83] = rank(spread.shift(2)) * rank(rank(v)) / (spread / (w - c).replace(0, np.nan)).replace(0, np.nan)
    base = trank(w - high(w, 15), 20)
    e[84] = np.sign(base) * base.abs() ** c.diff(4)
    e[85] = power(rank(corr(h * .876703 + c * (1 - .876703), a(30), 9)), rank(corr(trank((h + lo) / 2, 3), trank(v, 10), 7)))
    e[86] = negcompare(trank(corr(c, total(a(20), 14), 6), 20), rank(c - w))
    e[88] = minimum(rank(decay(rank(o) + rank(lo) - rank(h) - rank(c), 8)), trank(decay(corr(trank(c, 8), trank(a(60), 20), 8), 6), 2))
    e[92] = minimum(trank(decay(where((h + lo) / 2 + c, lt, lo + o, 1., 0.), 14), 18), trank(decay(corr(rank(lo), rank(a(30)), 7), 6), 6))
    e[94] = -power(rank(w - low(w, 11)), trank(corr(trank(w, 19), trank(a(60), 4), 18), 2))
    e[95] = where(rank(o - low(o, 12)), lt, trank(rank(corr(total((h + lo) / 2, 19), total(a(40), 19), 12)) ** 5, 11), 1., 0.)
    e[96] = -maximum(trank(decay(corr(rank(w), rank(v), 3), 4), 8), trank(decay(argmax(corr(trank(c, 7), trank(a(60), 4), 3), 12), 14), 13))
    e[98] = rank(decay(corr(w, total(a(5), 26), 4), 7)) - rank(decay(trank(argmin(corr(rank(o), rank(a(15)), 20), 8), 6), 8))
    e[99] = negcompare(rank(corr(total((h + lo) / 2, 19), total(a(60), 19), 8)), rank(corr(lo, v, 6)))
    return {f'alpha101_{n:03d}': x.replace([np.inf, -np.inf], np.nan) for n, x in e.items()}


BATCH = {f"alpha101_{n:03d}" for n in (75, 77, 78, 81, 83, 84, 85, 86, 88, 92, 94, 95, 96, 98, 99)}

@pytest.mark.parametrize("missing", [False, True])
def test_fifteen_formulas_and_future_truncation(missing):
    panel = sample_panel().with_columns((pl.col("close") * 100000000).alias("total_market_value"))
    if missing:
        panel = panel.with_columns(*[
            pl.when(~((pl.col("symbol") == "000003.SZ") & (pl.col("trade_date") == dt.date(2020, 10, 15)))).then(pl.col(n)).alias(n)
            for n in panel.columns if n not in ("symbol", "trade_date")
        ])
    exprs = {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}
    assert set(exprs) == BATCH and len(exprs) == 15
    actual = evaluate_expressions(panel, exprs)
    cutoff = dt.date(2020, 12, 1)
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff),
                       evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), exprs))
    flat = actual.to_pandas()
    for name, expected in reference_p2g(panel).items():
        values = flat.pivot(index="trade_date", columns="symbol", values=name).sort_index()
        np.testing.assert_allclose(values, expected, atol=1e-7, rtol=1e-6, equal_nan=True, err_msg=name)
