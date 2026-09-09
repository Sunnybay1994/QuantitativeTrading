import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.high52 import compute_high52


def sample():
    days = tuple(dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(7))
    return days, pl.DataFrame({"symbol": ["A"] * 7, "trade_date": days,
        "high": [12., 11., 6., 7., 8., 9., 10.],
        "close": [10., 10., 5., 6., 7., 8., 9.], "adj_factor": [1., 1., 2., 2., 2., 2., 2.]})


def test_adjusted_intraday_high_and_trailing_momentum():
    days, bars = sample()
    result = compute_high52(bars, sessions=days, high_window=3, momentum_window=2)
    assert result["high52_proximity"][2] == pytest.approx(10 / 12)
    assert result["momentum_126"][2] == pytest.approx(0)
    assert result["high52_proximity"][3] == pytest.approx(12 / 14)
    assert result["momentum_126"][3] == pytest.approx(.2)


def test_missing_session_recovers_only_after_full_window():
    days, bars = sample()
    result = compute_high52(bars.filter(pl.col("trade_date") != days[2]),
                            sessions=days, high_window=3, momentum_window=2)
    assert result["high52_proximity"].to_list()[2:5] == [None, None, None]
    assert result["momentum_126"].to_list()[2:5] == [None, None, None]
    assert result["high52_proximity"][5] == pytest.approx(16 / 18)


def test_future_append_preserves_signal():
    days, bars = sample()
    early = compute_high52(bars.head(4), sessions=days[:4], high_window=3, momentum_window=2)
    later = compute_high52(bars, sessions=days, high_window=3, momentum_window=2)
    assert_frame_equal(early, later.head(4))


def test_high_below_close_is_invalid():
    days, bars = sample()
    bars = bars.with_columns(pl.when(pl.col("trade_date") == days[2])
                             .then(4.).otherwise(pl.col("high")).alias("high"))
    result = compute_high52(bars, sessions=days, high_window=3, momentum_window=2)
    assert result["high52_proximity"][2] is None


def test_duplicate_rejected():
    days, bars = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        compute_high52(pl.concat([bars, bars.head(1)]), sessions=days)
