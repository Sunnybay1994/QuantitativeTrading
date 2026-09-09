import datetime as dt
import math

import polars as pl
import pytest

from quant.factors.return_skewness import compute_return_skewness


def sample():
    returns = [.01, .02, -.01, .03, .09]
    prices = [100.]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    sessions = tuple(dt.date(2024, 1, i) for i in range(1, 7))
    frame = pl.DataFrame({"symbol": ["A"] * 6, "trade_date": sessions,
                          "close": prices, "adj_factor": [1.] * 6})
    return frame, sessions, returns


def test_bias_corrected_skew_matches_centered_hand_calculation():
    frame, sessions, returns = sample()
    mean = sum(returns) / 5
    m2 = sum((r - mean) ** 2 for r in returns) / 5
    m3 = sum((r - mean) ** 3 for r in returns) / 5
    expected = math.sqrt(5 * 4) / 3 * m3 / m2 ** 1.5
    values = compute_return_skewness(frame, sessions=sessions, window=5)["return_skew20"]
    assert values[:-1].null_count() == 5
    assert values[-1] == pytest.approx(expected)


def test_adjustment_and_future_prices_cannot_change_past_skew():
    frame, sessions, _ = sample()
    adjusted = frame.with_columns(pl.when(pl.col("trade_date") >= sessions[3])
        .then(pl.col("close") / 2).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("trade_date") >= sessions[3]).then(2.).otherwise(1.).alias("adj_factor"))
    before = compute_return_skewness(frame, sessions=sessions, window=5)
    assert before.equals(compute_return_skewness(adjusted, sessions=sessions, window=5))
    later = frame.tail(1).with_columns(pl.lit(dt.date(2024, 1, 7)).alias("trade_date"),
                                      pl.lit(1.).alias("close"))
    after = compute_return_skewness(pl.concat([frame, later]),
        sessions=(*sessions, dt.date(2024, 1, 7)), window=5).head(6)
    assert before.equals(after)


def test_missing_and_invalid_prices_do_not_compress_the_window():
    frame, sessions, _ = sample()
    for broken in (frame.filter(pl.col("trade_date") != sessions[2]),
                   frame.with_columns(pl.when(pl.col("trade_date") == sessions[2])
                       .then(0.).otherwise(pl.col("close")).alias("close"))):
        assert compute_return_skewness(broken, sessions=sessions, window=5)["return_skew20"][-1] is None
    flat = frame.with_columns(pl.lit(100.).alias("close"))
    assert compute_return_skewness(flat, sessions=sessions, window=5)["return_skew20"].null_count() == 6
    with pytest.raises(ValueError, match="Duplicate"):
        compute_return_skewness(pl.concat([frame, frame.tail(1)]), sessions=sessions)
