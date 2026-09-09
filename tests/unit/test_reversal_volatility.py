import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.factors.reversal_volatility import (
    compute_reversal_volatility_factors, exclude_historical_risk_names,
    rolling_residual_volatility, size_value_proxy_returns,
)


def test_regression_residual_matches_orthogonal_hand_calculation():
    a = np.array([1., -1.] * 4)
    b = np.array([1., 1., -1., -1.] * 2)
    c = np.array([1.] * 4 + [-1.] * 4)
    x = np.column_stack([a, b, c]) * .01
    y = .02 + x @ np.array([2., -1., .5]) + a * b * .001
    result = rolling_residual_volatility(y, x, window=8, annualization=1)
    assert np.isnan(result[:-1]).all()
    assert result[-1] == pytest.approx(.001 * 2 ** .5)
    x[-1, 0] = np.nan
    assert np.isnan(rolling_residual_volatility(y, x, window=8, annualization=1)).all()


def test_reversal_and_total_volatility_do_not_bridge_missing_sessions():
    dates = [dt.date(2026, 1, day) for day in (5, 6, 7, 8)]
    bars = pl.DataFrame({"symbol": ["A"] * 4, "trade_date": dates,
                         "close": [100., 110., 99., 108.9], "adj_factor": [1.] * 4})
    basic = bars.select("symbol", "trade_date").with_columns(
        pl.lit(1000.).alias("total_market_value"), pl.lit(1.).alias("pb"))
    settings = {"reversal_window_sessions": 2, "volatility_window_sessions": 2,
                "ivol_window_sessions": 8, "annualization_sessions": 1, "proxy_minimum_bucket_symbols": 1}
    values, _ = compute_reversal_volatility_factors(bars, basic, sessions=tuple(dates), settings=settings)
    assert values["reversal_20"][2:].to_list() == pytest.approx([.01, .01])
    assert values["realized_volatility_60"][-1] == pytest.approx(.02 ** .5)
    missing, _ = compute_reversal_volatility_factors(bars.filter(pl.col("trade_date") != dates[2]),
        basic, sessions=tuple(dates), settings=settings)
    assert missing["reversal_20"][-1] is None
    assert missing["realized_volatility_60"][-1] is None


def test_size_value_sorts_are_frozen_before_return_month():
    rows = []
    for day, month in [(dt.date(2026, 1, 30), dt.date(2026, 1, 1)),
                       (dt.date(2026, 2, 2), dt.date(2026, 2, 1))]:
        for index in range(6):
            rows.append({"symbol": str(index), "trade_date": day, "_month": month,
                "total_market_value": float(index + 1), "pb": 1 / (index % 3 + 1),
                "_lag_mv": float(index + 1), "_return": .01 * (index + 1)})
    grid = pl.DataFrame(rows)
    first = size_value_proxy_returns(grid, minimum_bucket_symbols=1).row(-1, named=True)
    assert first["smb_return"] == pytest.approx(-.03)
    assert first["hml_return"] == pytest.approx(.02)
    assert first["market_return"] == pytest.approx(.91 / 21)
    changed = grid.with_columns(pl.when(pl.col("trade_date").dt.month() == 2)
        .then(100.0).otherwise(pl.col("pb")).alias("pb"))
    assert size_value_proxy_returns(changed, minimum_bucket_symbols=1).row(-1, named=True) == first


def test_historical_st_name_and_unknown_names_are_excluded():
    dates = [dt.date(2026, 1, day) for day in (5, 6, 7)]
    panel = pl.DataFrame({"symbol": ["A"] * 3 + ["B"], "trade_date": dates + dates[:1]})
    names = pl.DataFrame({"symbol": ["A", "A"], "name": ["Normal", "*STExample"],
        "start_date": dates[:2], "end_date": [dates[0], None]},
        schema_overrides={"end_date": pl.Date})
    assert exclude_historical_risk_names(panel, names).to_dicts() == [{"symbol": "A", "trade_date": dates[0]}]
