import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.expressions import required_history
from quant.research.factor_legacy_special import LEGACY_SPECIAL_NAMES, attach_legacy_special_factors
from tests.unit.test_daily_value_factors import _daily_basic
from tests.unit.test_factor_expressions import prepared


def sample():
    begin = dt.date(2025, 9, 1)
    sessions = tuple(begin + dt.timedelta(days=i) for i in range(250)
        if (begin + dt.timedelta(days=i)).weekday() < 5)[:160]
    rng = np.random.default_rng(921)
    rows = []
    for stock in range(180):
        returns = (.002*np.sin(np.arange(160)*.7) + (stock/180-.5)*.006*np.cos(np.arange(160)*.11)
            + (stock%6-2.5)*.001*np.sin(np.arange(160)*.3) + rng.normal(0,.003,160))
        prices = (10+stock*.1)*np.cumprod(1+returns)
        for index, date in enumerate(sessions):
            if stock == 0 and index == 145:
                continue
            adjustment = 2.0 if index >= 80 else 1.0
            close = prices[index]/adjustment
            volume = 10000.0+(stock*79+index*97)%3000
            rows.append(dict(symbol=f"{600000+stock}.SH", trade_date=date, open=close,
                high=close*1.02, low=close*.98, close=close, adj_factor=adjustment,
                amount=close*volume, volume=volume, source="tushare"))
    bars = pl.DataFrame(rows)
    fixture = _daily_basic()
    basic = bars.select(*[pl.col(name) if name in bars.columns else
        pl.lit(fixture[name].item(), dtype=dtype).alias(name)
        for name,dtype in fixture.schema.items()]).with_columns(
            pl.col("symbol").str.slice(0,6).cast(pl.Int64).sub(600000).alias("stock"))
    basic = basic.with_columns(
        ((20+pl.col("stock"))*1e6).alias("total_market_value"),
        ((20+pl.col("stock"))*8e5).alias("circulating_market_value"),
        (pl.col("stock")%6*.4+.5).alias("pb"),
        ((pl.col("stock")*73%181)*.01+.5).alias("turnover_rate_free"),
    ).drop("stock")
    panel = bars.select("symbol").unique().join(pl.DataFrame({"trade_date":sessions}), how="cross").join(
        bars,on=["symbol","trade_date"],how="left").sort("symbol","trade_date")
    return bars,basic,prepared(panel),sessions


def test_special_factors_positive_values_gaps_and_numpy_checks():
    bars,basic,panel,sessions = sample()
    result = attach_legacy_special_factors(panel,bars,basic,sessions,LEGACY_SPECIAL_NAMES)
    final = result.filter(pl.col("trade_date")==sessions[-1]).sort("symbol")
    for name in LEGACY_SPECIAL_NAMES:
        assert final[name].count() == 179
    assert result.filter((pl.col("symbol")=="600000.SH") &
        (pl.col("trade_date")==sessions[145]))[LEGACY_SPECIAL_NAMES[0]].item() is None
    for symbol in ("600001.SH","600033.SH","600101.SH"):
        stock = panel.filter(pl.col("symbol")==symbol).sort("trade_date")
        p = stock["adj_close"].to_numpy()
        differences = p[7:]-p[:-7]
        values = np.abs(differences[-60:])
        rank = (np.sum(values<values[-1])+(np.sum(values==values[-1])-1)/2)/59
        a = stock["amount"].to_numpy()
        expected = -rank*np.sign(differences[-1]) if a[-1]>a[-20:].mean() else -1.0
        assert final.filter(pl.col("symbol")==symbol)[LEGACY_SPECIAL_NAMES[0]].item() == pytest.approx(expected)
    # Independently form the latest complete MAX cross-section and fit its controls.
    records = []
    for symbol in final["symbol"]:
        p = panel.filter(pl.col("symbol")==symbol).sort("trade_date").tail(21)["adj_close"].to_numpy()
        if np.isfinite(p).all():
            row = basic.filter((pl.col("symbol")==symbol) & (pl.col("trade_date")==sessions[-1]))
            records.append(dict(symbol=symbol, y=float(np.max(p[1:]/p[:-1]-1)),
                size=np.log(row["total_market_value"].item()), turnover=row["turnover_rate_free"].item()))
    ranked = pl.DataFrame(records).sort("symbol").with_columns(pl.col(name).rank("average") for name in ("y","size","turnover"))
    x = np.column_stack((np.ones(ranked.height),ranked.select("size","turnover").to_numpy()))
    y = ranked["y"].to_numpy()
    expected = y-x@np.linalg.lstsq(x,y,rcond=None)[0]
    actual = final.join(ranked.select("symbol"),on="symbol",how="semi")[LEGACY_SPECIAL_NAMES[1]].to_numpy()
    np.testing.assert_allclose(actual,expected,atol=1e-8)
    for name,lookback in zip(LEGACY_SPECIAL_NAMES,(66,20,100),strict=True):
        assert required_history(name)==lookback
        assert required_history(f"ts_mean({name},20)")==lookback+19


def test_special_cross_year_increment_matches_full(tmp_path,monkeypatch):
    from quant.factors import compute

    bars,basic,panel,sessions = sample()
    monkeypatch.setattr(compute,"available_sessions",lambda root,end:tuple(d for d in sessions if d<=end))
    monkeypatch.setattr(compute,"read_factor_inputs",lambda root,config,start,end,sessions:(
        panel.filter(pl.col("trade_date").is_between(start,end)),
        bars.filter(pl.col("trade_date").is_between(start,end))))
    monkeypatch.setattr(compute,"read_stock_data",lambda **kwargs:basic.filter(
        pl.col("trade_date").is_between(kwargs["start"],kwargs["end"])))
    args = dict(refresh_config=Path("unused"),library=Path("configs/factors/library"),
        selected=",".join(LEGACY_SPECIAL_NAMES),start=sessions[0],artifact_root=tmp_path/"artifacts")
    compute.run(**args,data_root=tmp_path/"increment",end=sessions[150])
    compute.run(**args,data_root=tmp_path/"increment",end=sessions[-1])
    compute.run(**args,data_root=tmp_path/"full",end=sessions[-1])
    for file in (tmp_path/"full/factors").glob("*/year=*/data.parquet"):
        assert_frame_equal(pl.read_parquet(file),pl.read_parquet(tmp_path/"increment"/file.relative_to(tmp_path/"full")),abs_tol=1e-8)
    for name in LEGACY_SPECIAL_NAMES:
        assert pl.read_parquet(tmp_path/"full/factors"/name/"year=2026/data.parquet")["value"].count()>1000
    assert compute.run(**args,data_root=tmp_path/"increment",end=sessions[-1])["years"]==[]
