"""Small hand-calculated turnover windows and point-in-time invariants."""

import datetime as dt
import math

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.turnover_variability import compute_turnover_variability


DATES = tuple(dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(6))


def frame(values: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({"symbol": ["A"] * len(values), "trade_date": DATES[:len(values)],
                         "turnover_rate": values}, schema_overrides={"turnover_rate": pl.Float64})


def test_hand_calculation_scale_and_symbol_isolation() -> None:
    first = frame([1., 2., 3., 4.])
    other = first.with_columns(pl.lit("B").alias("symbol"), (pl.col("turnover_rate") * 7))
    result = compute_turnover_variability(pl.concat([other, first]).reverse(), sessions=DATES[:4], window=3)
    for symbol in ("A", "B"):
        values = result.filter(pl.col("symbol") == symbol)["turnover_cv20"].to_list()
        assert values[:2] == [None, None]
        assert values[2:] == pytest.approx([math.sqrt(2 / 3) / 2, math.sqrt(2 / 3) / 3])


@pytest.mark.parametrize("bad", [None, -1., float("nan"), float("inf")])
def test_invalid_values_invalidate_entire_window_then_recover(bad: float | None) -> None:
    result = compute_turnover_variability(frame([1., bad, 2., 2., 2., 2.]), sessions=DATES, window=3)
    assert result["turnover_cv20"].to_list()[:4] == [None] * 4
    assert result["turnover_cv20"].to_list()[4:] == pytest.approx([0., 0.])


def test_missing_session_is_not_compressed_and_weekend_does_not_count() -> None:
    x = frame([1., 2., 3., 4., 5., 6.]).filter(pl.col("trade_date") != DATES[2])
    result = compute_turnover_variability(x, sessions=DATES, window=3)
    assert result["turnover_cv20"].to_list()[:5] == [None] * 5
    assert result["turnover_cv20"][-1] == pytest.approx(math.sqrt(2 / 3) / 5)
    # The caller supplies the exchange calendar: omitted non-session dates do not create holes.
    sparse = (DATES[0], DATES[1], DATES[4])
    three = frame([1., 2., 3.]).with_columns(pl.Series("trade_date", sparse))
    assert compute_turnover_variability(three, sessions=sparse, window=3)["turnover_cv20"][-1] is not None


def test_zero_mean_invalid_but_observed_zero_retained() -> None:
    result = compute_turnover_variability(frame([0., 0., 0., 3.]), sessions=DATES[:4], window=3)
    assert result["turnover_cv20"].to_list()[:3] == [None] * 3
    assert result["turnover_cv20"][-1] == pytest.approx(math.sqrt(2))


def test_future_values_cannot_change_past_outputs() -> None:
    initial = frame([1., 2., 3., 4.])
    before = compute_turnover_variability(initial, sessions=DATES[:4], window=3)
    after = compute_turnover_variability(frame([1., 2., 3., 4., 99999., .001]), sessions=DATES, window=3)
    assert_frame_equal(before, after.filter(pl.col("trade_date") <= DATES[3]))


def test_duplicate_keys_rejected() -> None:
    x = frame([1., 2., 3.])
    with pytest.raises(ValueError, match="Duplicate"):
        compute_turnover_variability(pl.concat([x, x.head(1)]), sessions=DATES, window=3)


def test_default_window_requires_twenty_complete_sessions() -> None:
    dates = tuple(dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(21))
    x = pl.DataFrame({"symbol": ["A"] * 21, "trade_date": dates, "turnover_rate": [1.] * 21})
    result = compute_turnover_variability(x, sessions=dates)
    assert result["turnover_cv20"].to_list()[:19] == [None] * 19
    assert result["turnover_cv20"].to_list()[19:] == [0., 0.]
