"""Independent pandas arithmetic for the first Alpha101 library expansion."""

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library


NUMBERS = set(range(1, 37)) - {2, 4, 6, 9, 12, 33}
BATCH = {f"alpha101_{n:03d}" for n in NUMBERS} | {"alpha101_033_paper"}


def definitions():
    return {row.id: row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}


def sample_panel():
    rng = np.random.default_rng(314)
    records = []
    for stock in range(8):
        close = (8 + stock * 4) * np.exp(np.cumsum(rng.normal(0.0004, 0.012, 380)))
        for day in range(380):
            adjustment = 2.0 if day >= 120 else 1.0
            current = close[day] / adjustment
            opening = current * (1 + rng.normal(0, 0.004))
            high = max(current, opening) * (1 + rng.uniform(0.001, 0.02))
            low = min(current, opening) * (1 - rng.uniform(0.001, 0.02))
            volume = float(rng.integers(10000, 1000000))
            records.append({"symbol": f"{stock:06d}.SZ", "trade_date": dt.date(2020, 1, 1) + dt.timedelta(days=day),
                            "open": opening, "high": high, "low": low, "close": current,
                            "volume": volume, "amount": volume * (current + opening) / 2,
                            "adj_factor": adjustment})
    panel = pl.DataFrame(records)
    return panel.with_columns(*[(pl.col(k) * pl.col("adj_factor")).alias(f"adj_{k}") for k in ("open", "high", "low", "close")])


def reference(panel):
    """Use pandas kernels and explicit formulas, independently of the DSL AST."""
    frame = panel.to_pandas()
    wide = {name: frame.pivot(index="trade_date", columns="symbol", values=name).sort_index()
            for name in ("adj_close", "adj_open", "adj_high", "adj_low", "volume", "amount", "adj_factor", "open", "close")}
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
        return x.rolling(n, min_periods=n).apply(
            lambda a: (np.sum(a < a[-1]) + (np.sum(a == a[-1]) - 1) / 2) / (n - 1), raw=True,
        )

    def where(left, op, right, yes, no):
        # pandas comparisons turn missing into False; preserve the DSL null mask.
        valid = left.notna() & (right.notna() if isinstance(right, pd.DataFrame) else True)
        return pd.DataFrame(np.where(op(left, right), yes, no), index=c.index, columns=c.columns).where(valid)

    gt, lt = np.greater, np.less
    a, d = mean(wide["amount"], 20), c.diff()
    result = {}
    base = where(r, lt, 0, std(r, 20), c)
    result[1] = rank((base ** 2).rolling(5).apply(lambda x: float(np.argmax(x) + 1), raw=True)) - 0.5
    result[3] = -corr(rank(o), rank(v), 10)
    result[5] = rank(o - mean(w, 10)) * -abs(rank(c - w))
    result[7] = where(a, lt, v, -trank(abs(c.diff(7)), 60) * np.sign(c.diff(7)), -1)
    result[8] = -rank((total(o, 5) * total(r, 5)).diff(10))
    result[10] = rank(where(low(d, 4), gt, 0, d, where(high(d, 4), lt, 0, d, -d)))
    result[11] = (rank(high(w - c, 3)) + rank(low(w - c, 3))) * rank(v.diff(3))
    result[13] = -rank(cov(rank(c), rank(v), 5))
    result[14] = -rank(r.diff(3)) * corr(o, v, 10)
    result[15] = -total(rank(corr(rank(h), rank(v), 3)), 3)
    result[16] = -rank(cov(rank(h), rank(v), 5))
    result[17] = -rank(trank(c, 10)) * rank(c.diff().diff()) * rank(trank(v / a, 5))
    result[18] = -rank(std(abs(c - o), 5) + c - o + corr(c, o, 10))
    result[19] = -np.sign(c - c.shift(7) + c.diff(7)) * (1 + rank(1 + total(r, 250)))
    result[20] = -rank(o - h.shift(1)) * rank(o - c.shift(1)) * rank(o - lo.shift(1))
    result[21] = where(mean(c, 8) + std(c, 8), lt, mean(c, 2), -1,
                       where(mean(c, 2), lt, mean(c, 8) - std(c, 8), 1,
                             where(v / a, np.greater_equal, 1, 1, -1)))
    result[22] = -corr(h, v, 5).diff(5) * rank(std(c, 20))
    result[23] = where(mean(h, 20), lt, h, -h.diff(2), 0)
    result[24] = where(mean(c, 100).diff(100) / c.shift(100), np.less_equal, 0.05, -(c - low(c, 100)), -c.diff(3))
    result[25] = rank(-r * a * w * (h - c))
    result[26] = -high(corr(trank(v, 5), trank(h, 5), 5), 3)
    result[27] = where(rank(mean(corr(rank(v), rank(w), 6), 2)), gt, 0.5, -1, 1)
    positive = low(rank(rank(-rank((c - 1).diff(5)))), 2)
    result[28] = scale(corr(a, lo, 5) + (h + lo) / 2 - c)
    result[29] = low(rank(rank(scale(np.log(positive.where(positive > 0))))), 5) + trank((-r).shift(6), 5)
    result[30] = (1 - rank(np.sign(d) + np.sign(d.shift(1)) + np.sign(d.shift(2)))) * total(v, 5) / total(v, 20)
    decay = (-rank(rank(c.diff(10)))).rolling(10).apply(lambda x: np.dot(x, np.arange(1, 11)) / 55, raw=True)
    result[31] = rank(rank(rank(decay))) + rank(-c.diff(3)) + np.sign(scale(corr(a, lo, 12)))
    result[32] = scale(mean(c, 7) - c) + 20 * scale(corr(w, c.shift(5), 230))
    result[34] = rank(1 - rank(std(r, 2) / std(r, 5)) + 1 - rank(d))
    result[35] = trank(v, 32) * (1 - trank(c + h - lo, 16)) * (1 - trank(r, 32))
    result[36] = (2.21 * rank(corr(c - o, v.shift(1), 15)) + 0.7 * rank(o - c)
                  + 0.73 * rank(trank((-r).shift(6), 5)) + rank(abs(corr(w, a, 6)))
                  + 0.6 * rank((mean(c, 200) - o) * (c - o)))
    named = {f"alpha101_{n:03d}": x for n, x in result.items()}
    named["alpha101_033_paper"] = rank(-(1 - wide["open"] / wide["close"]))
    return named


def test_all_31_against_pandas_reference():
    panel = sample_panel()
    expressions = definitions()
    assert len(expressions) == 31 and set(expressions) == BATCH
    actual = evaluate_expressions(panel, expressions).to_pandas()
    for name, expected in reference(panel).items():
        wide = actual.pivot(index="trade_date", columns="symbol", values=name).sort_index()
        np.testing.assert_allclose(wide, expected, atol=1e-7, rtol=1e-6, equal_nan=True, err_msg=name)


def test_prefix_and_missing_values_match_reference():
    panel = sample_panel()
    gap = dt.date(2020, 10, 15)
    panel = panel.with_columns(*[
        pl.when(~((pl.col("trade_date") == gap) & (pl.col("symbol") == "000003.SZ"))).then(pl.col(name)).alias(name)
        for name in ("adj_close", "adj_open", "adj_high", "adj_low", "volume", "amount", "adj_factor", "open", "close")
    ])
    cutoff = dt.date(2020, 12, 1)
    actual = evaluate_expressions(panel, definitions())
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff),
                       evaluate_expressions(panel.filter(pl.col("trade_date") <= cutoff), definitions()))
    frame = actual.to_pandas()
    for name, expected in reference(panel).items():
        wide = frame.pivot(index="trade_date", columns="symbol", values=name).sort_index()
        np.testing.assert_allclose(wide, expected, atol=1e-7, rtol=1e-6, equal_nan=True, err_msg=name)


def test_decay_weights_and_missing_window():
    panel = pl.DataFrame({"symbol": ["a"] * 7, "trade_date": list(range(7)), "x": [1., 2., 3., None, 5., 6., 7.]})
    result = evaluate_expressions(panel, {"decay": "decay_linear(x, 3)"})
    assert result["decay"].to_list() == [None, None, pytest.approx(14 / 6), None, None, None, pytest.approx(38 / 6)]


def test_constant_covariance_and_numerical_rank_ties():
    panel = pl.DataFrame({"symbol": ["a"] * 6, "trade_date": list(range(6)),
                          "x": [0.7142857142857] * 6, "y": [1., 7., 2., 9., None, 4.]})
    result = evaluate_expressions(panel, {"corr": "ts_corr(x, y, 3)", "cov": "ts_cov(x, y, 3)", "one": "ts_cov(x, y, 1)"})
    assert result["corr"].null_count() == result["one"].null_count() == 6
    assert result["cov"].to_list() == [None, None, 0.0, 0.0, None, None]
    panel = pl.DataFrame({"symbol": ["a", "b", "c"], "trade_date": [1, 1, 1],
                          "x": [-0.7559289460184436, -0.7559289460185018, -0.4],
                          "tiny": [1e-20, 2e-20, 3e-20]})
    result = evaluate_expressions(panel, {"rank": "rank(x)", "tiny_rank": "rank(tiny)"})
    assert result["rank"].to_list() == [0.25, 0.25, 1.0]
    assert result["tiny_rank"].to_list() == [0.0, 0.5, 1.0]
