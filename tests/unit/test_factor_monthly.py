import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.calendar_liquidity import CALENDAR_LIQUIDITY_NAMES
from quant.factors.expressions import required_history
from quant.factors.liquidity import LIQUIDITY_FACTOR_NAMES
from quant.research.factor_monthly import attach_monthly_factors
from tests.unit.test_daily_value_factors import _daily_basic
from tests.unit.test_factor_expressions import prepared


def sample():
    first, last = dt.date(2018, 12, 1), dt.date(2022, 3, 15)
    calendar = tuple(first + dt.timedelta(days=i) for i in range((last-first).days+1)
                     if (first + dt.timedelta(days=i)).weekday() < 5)
    sessions = tuple(d for d in calendar if dt.date(2019, 1, 1) <= d <= dt.date(2022, 2, 15))
    rows = []
    for stock in range(2):
        for index, date in enumerate(sessions):
            adjustment = 2.0 if index >= 390 else 1.0
            close = (10.0 + stock + index*.01 + np.sin(index)*.2)/adjustment
            rows.append(dict(symbol=f"60000{stock}.SH", trade_date=date, open=close,
                high=close*1.02, low=close*.98, close=close, volume=10000.0,
                amount=close*10000.0, adj_factor=adjustment, source="tushare"))
    bars = pl.DataFrame(rows)
    fixture = _daily_basic()
    basic = bars.select(*[pl.col(name) if name in bars.columns else
        pl.lit(fixture[name].item(), dtype=dtype).alias(name)
        for name, dtype in fixture.schema.items()]).with_columns(
            (1.0 + ((pl.col("trade_date").dt.year()-2019)*12 + pl.col("trade_date").dt.month())*.1)
            .alias("turnover_rate_free"))
    basic = basic.with_columns(pl.when((pl.col("symbol") == "600001.SH") &
        (pl.col("trade_date").dt.year() == 2020) & (pl.col("trade_date").dt.month() == 7))
        .then(None).otherwise(pl.col("turnover_rate_free")).alias("turnover_rate_free"))
    return bars, basic, calendar


def test_completed_month_values_and_invalid_month_replace_old_values():
    bars, basic, calendar = sample()
    result = attach_monthly_factors(prepared(bars), bars, basic, calendar, LIQUIDITY_FACTOR_NAMES)

    def value(symbol, date, name):
        return result.filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == date))[name].item()

    level, abnormal = LIQUIDITY_FACTOR_NAMES[1:]
    assert value("600000.SH", dt.date(2020, 7, 30), level) == pytest.approx(.028)
    assert value("600000.SH", dt.date(2020, 7, 31), level) == pytest.approx(.029)
    assert value("600001.SH", dt.date(2020, 7, 30), level) == pytest.approx(.028)
    assert value("600001.SH", dt.date(2020, 7, 31), level) is None
    assert value("600001.SH", dt.date(2020, 8, 3), level) is None
    assert value("600001.SH", dt.date(2020, 8, 31), level) == pytest.approx(.030)
    assert value("600001.SH", dt.date(2021, 7, 30), abnormal) is None
    assert value("600001.SH", dt.date(2021, 8, 31), abnormal) is not None
    assert value("600000.SH", dt.date(2020, 1, 31), abnormal) == pytest.approx(.023 / np.mean(np.arange(11, 23)/1000) - 1)
    # The unfinished February cannot replace January's observation.
    assert value("600000.SH", dt.date(2022, 2, 15), level) == pytest.approx(.047)
    stock = bars.filter(pl.col("symbol") == "600000.SH").sort("trade_date")
    price = (stock["close"]*stock["adj_factor"]).to_numpy()
    raw = np.r_[np.nan, np.abs(price[1:]/price[:-1]-1)]/(stock["amount"].to_numpy()/1e6)
    july = np.array([d.year == 2020 and d.month == 7 for d in stock["trade_date"]])
    assert value("600000.SH", dt.date(2020, 7, 31), LIQUIDITY_FACTOR_NAMES[0]) == pytest.approx(np.mean(raw[july]))
    high = dt.date(2020, 7, 30)
    shortened = attach_monthly_factors(prepared(bars.filter(pl.col("trade_date") <= high)),
        bars.filter(pl.col("trade_date") <= high), basic.filter(pl.col("trade_date") <= high),
        calendar, LIQUIDITY_FACTOR_NAMES)
    assert_frame_equal(shortened, result.filter(pl.col("trade_date") <= high))
    for name in LIQUIDITY_FACTOR_NAMES:
        assert required_history(f"ts_mean({name},20)") == required_history(name) + 19


@pytest.mark.parametrize("names", [LIQUIDITY_FACTOR_NAMES, CALENDAR_LIQUIDITY_NAMES])
def test_monthly_cross_year_increment_preserves_twelve_month_history(tmp_path, monkeypatch, names):
    from quant.factors import compute

    bars, basic, calendar = sample()
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in calendar if dt.date(2019,1,1) <= d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    monkeypatch.setattr(compute, "read_stock_data", lambda **kwargs: basic.filter(
        pl.col("trade_date").is_between(kwargs["start"], kwargs["end"])))
    args = dict(refresh_config=Path("unused"), library=Path("configs/factors/library"),
        selected=",".join(names), start=dt.date(2019,1,1), artifact_root=tmp_path / "artifacts")
    compute.run(**args, data_root=tmp_path / "increment", end=dt.date(2022,1,14))
    compute.run(**args, data_root=tmp_path / "increment", end=dt.date(2022,2,15))
    compute.run(**args, data_root=tmp_path / "full", end=dt.date(2022,2,15))
    for file in (tmp_path / "full/factors").glob("*/year=*/data.parquet"):
        assert_frame_equal(pl.read_parquet(file), pl.read_parquet(
            tmp_path / "increment" / file.relative_to(tmp_path / "full")))
    for name in names:
        values = pl.read_parquet(tmp_path / "full/factors" / name / "year=2022/data.parquet")["value"]
        assert values.count() == 64
    assert compute.run(**args, data_root=tmp_path / "increment", end=dt.date(2022,2,15))["years"] == []
