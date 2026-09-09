import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.overnight_decomposition import compute_overnight_decomposition


def sample():
    days = tuple(dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(6))
    bars = pl.DataFrame({"symbol": ["A"] * 6, "trade_date": days,
        "open": [10., 11., 6., 6., 6., 6.], "close": [10., 12., 6., 6., 6., 6.],
        "adj_factor": [1., 1., 2., 2., 2., 2.]})
    return days, bars


def test_split_adjustment_and_multiplicative_identity():
    days, bars = sample()
    result = compute_overnight_decomposition(bars, sessions=days, window=2)
    row = result.row(2, named=True)
    assert row["overnight_return_20"] == pytest.approx(.1)
    assert row["intraday_return_20"] == pytest.approx(12 / 11 - 1)
    assert row["total_return_20"] == pytest.approx(.2)
    assert (1 + row["overnight_return_20"]) * (1 + row["intraday_return_20"]) == pytest.approx(1.2)


def test_missing_session_invalidates_and_recovers():
    days, bars = sample()
    result = compute_overnight_decomposition(
        bars.filter(pl.col("trade_date") != days[2]), sessions=days, window=2)
    assert result["total_return_20"].to_list()[2:5] == [None, None, None]
    assert result["total_return_20"][5] == pytest.approx(0)


def test_future_append_does_not_change_history():
    days, bars = sample()
    first = compute_overnight_decomposition(bars.head(4), sessions=days[:4], window=2)
    full = compute_overnight_decomposition(bars, sessions=days, window=2)
    assert_frame_equal(first, full.head(4))


@pytest.mark.parametrize("bad", [0., -1., float("nan"), float("inf"), None])
def test_invalid_prices_never_create_a_signal(bad):
    days, bars = sample()
    bars = bars.with_columns(pl.when(pl.col("trade_date") == days[2])
                             .then(pl.lit(bad, dtype=pl.Float64)).otherwise(pl.col("open")).alias("open"))
    result = compute_overnight_decomposition(bars, sessions=days, window=2)
    assert result["total_return_20"].to_list()[2:5] == [None, None, None]


def test_duplicate_input_rejected():
    days, bars = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        compute_overnight_decomposition(pl.concat([bars, bars.head(1)]), sessions=days)
