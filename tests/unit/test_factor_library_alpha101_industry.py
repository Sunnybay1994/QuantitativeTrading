"""Independent formulas for Alpha101 dated industry neutralization."""

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

def reference_p2h(panel):
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
        stable_x = x.map(lambda value: float(f"{value:.10g}"))
        stable_y = y.map(lambda value: float(f"{value:.10g}"))
        valid = (high(stable_x, n) > low(stable_x, n)) & (high(stable_y, n) > low(stable_y, n))
        return x.rolling(n, min_periods=n).corr(y).replace([np.inf, -np.inf], np.nan).clip(-1, 1).where(valid)

    def cov(x, y, n):
        stable_x = x.map(lambda value: float(f"{value:.10g}"))
        stable_y = y.map(lambda value: float(f"{value:.10g}"))
        constant = (high(stable_x, n) == low(stable_x, n)) | (high(stable_y, n) == low(stable_y, n))
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
    def minimum(x,y):
        return where(x, lt, y, x, y)
    def power(x,y):
        return (x ** y).where(x.notna() & y.notna())
    def argmin(x,n):
        return x.rolling(n).apply(lambda z:np.argmin(z)+1,raw=True)
    labels={n:frame.pivot(index='trade_date',columns='symbol',values=f'industry_l{n}').sort_index() for n in (1,2,3)}
    def ind(x,n):
        result=x.copy()
        for date in x.index:
            row=x.loc[date]
            result.loc[date]=row-row.groupby(labels[n].loc[date]).transform('mean')
        return result
    e={}
    e[48]=ind(corr(c.diff(),c.shift(1).diff(),250)*c.diff()/c,3)/total((c.diff()/c.shift())**2,250).replace(0,np.nan)
    e[58]=-trank(decay(corr(ind(w,1),v,3),7),5)
    e[59]=-trank(decay(corr(ind(w,2),v,4),16),8)
    e[63]=-(rank(decay(ind(c,2).diff(2),8))-rank(decay(corr(w*.318108+o*(1-.318108),total(a(180),37),13),12)))
    e[67]=-power(rank(h-low(h,2)),rank(corr(ind(w,1),ind(a(20),3),6)))
    e[69]=-power(rank(high(ind(w,2).diff(2),4)),trank(corr(c*.490655+w*(1-.490655),a(20),4),9))
    e[70]=-power(rank(w.diff()),trank(corr(ind(c,2),a(50),17),17))
    e[76]=-maximum(rank(decay(w.diff(),11)),trank(decay(trank(corr(ind(lo,1),a(81),8),19),17),19))
    e[79]=where(rank(ind(c*.60733+o*(1-.60733),1).diff()),lt,rank(corr(trank(w,3),trank(a(150),9),14)),1.,0.)
    e[80]=-power(rank(np.sign(ind(o*.868128+h*(1-.868128),2).diff(4))),trank(corr(h,a(10),5),5))
    e[82]=-minimum(rank(decay(o.diff(),14)),trank(decay(corr(ind(v,1),o,17),6),13))
    e[87]=-maximum(rank(decay((c*.369701+w*(1-.369701)).diff(),2)),trank(decay(corr(ind(a(81),2),c,13).abs(),4),14))
    e[89]=trank(decay(corr(lo,a(10),6),5),3)-trank(decay(ind(w,2).diff(3),10),15)
    e[90]=-power(rank(c-high(c,4)),trank(corr(ind(a(40),3),lo,5),3))
    e[91]=-(trank(decay(decay(corr(ind(c,2),v,9),16),3),4)-rank(decay(corr(w,a(30),4),2)))
    e[93]=trank(decay(corr(ind(w,2),a(81),17),19),7)/rank(decay((c*.524434+w*(1-.524434)).diff(2),16)).replace(0,np.nan)
    e[97]=-(rank(decay(ind(lo*.721001+w*(1-.721001),2).diff(3),20))-trank(decay(trank(corr(trank(lo,7),trank(a(60),17),4),18),15),6))
    body=rank(((c-lo)-(h-c))/(h-lo).replace(0,np.nan)*v)
    e[100]=-(1.5*scale(ind(ind(body,3),3))-scale(ind(corr(c,rank(a(20)),5)-rank(argmin(c,30)),3)))*v/a(20)
    return {f'alpha101_{n:03d}':x.replace([np.inf,-np.inf],np.nan) for n,x in e.items()}

def industry_panel(missing=False):
    panel=sample_panel().with_columns((pl.col('close')*100000000).alias('total_market_value'))
    code=pl.col('symbol').str.slice(0,6).cast(pl.Int32)
    panel=panel.with_columns(*[(code//divisor).cast(pl.String).alias(f'industry_l{n}') for n,divisor in [(1,8),(2,4),(3,2)]])
    if missing:
        panel=panel.with_columns(*[pl.when(~((pl.col('symbol')=='000003.SZ') & pl.col('trade_date').is_between(dt.date(2020,10,1),dt.date(2020,10,15)))).then(pl.col(n)).alias(n) for n in panel.columns if n not in ('symbol','trade_date')])
    return panel


BATCH = {f"alpha101_{n:03d}" for n in (48,58,59,63,67,69,70,76,79,80,82,87,89,90,91,93,97,100)}

@pytest.mark.parametrize("case", ["normal", "price_gap", "industry_change"])
def test_eighteen_industry_formulas_and_future_truncation(case):
    panel=industry_panel(case=="price_gap")
    if case=="industry_change":
        panel=panel.with_columns(*[
            pl.when((pl.col("symbol")=="000003.SZ") & pl.col("trade_date").is_between(dt.date(2020,10,1),dt.date(2020,10,15))).then(None).otherwise(pl.col(f"industry_l{n}")).alias(f"industry_l{n}")
            for n in (1,2,3)
        ])
        panel=panel.with_columns(*[
            pl.when((pl.col("symbol")=="000001.SZ") & (pl.col("trade_date")>=dt.date(2020,9,30))).then(pl.lit(label)).otherwise(pl.col(f"industry_l{n}")).alias(f"industry_l{n}")
            for n,label in ((2,"1"),(3,"2"))
        ])
    exprs={row.id:row.expr for row in load_library(Path("configs/factors/library")) if row.id in BATCH}
    assert set(exprs)==BATCH and len(exprs)==18
    actual=evaluate_expressions(panel,exprs)
    cutoff=dt.date(2020,12,1)
    assert_frame_equal(actual.filter(pl.col("trade_date")<=cutoff),evaluate_expressions(panel.filter(pl.col("trade_date")<=cutoff),exprs))
    flat=actual.to_pandas()
    for name,expected in reference_p2h(panel).items():
        values=flat.pivot(index="trade_date",columns="symbol",values=name).sort_index()
        np.testing.assert_allclose(values,expected,atol=1e-7,rtol=1e-6,equal_nan=True,err_msg=name)
