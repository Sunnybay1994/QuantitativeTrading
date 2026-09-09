import datetime as dt

import polars as pl
import pytest

from quant.research.monthly_etf import monthly_targets
from quant.strategies.inverse_volatility import InverseVolatilityStrategy


def prices():
    dates = [dt.date(2025, 1, d) for d in (27, 28, 29, 31)]
    return pl.DataFrame({"symbol": ["A"] * 4 + ["B"] * 4, "trade_date": dates * 2,
        "adjusted_close": [100., 110., 99., 108.9, 100., 120., 96., 115.2]})


def test_inverse_volatility_weights_hand_calculation_and_invalid_history():
    strategy = InverseVolatilityStrategy(("A", "B"), 3)
    frame = prices()
    result = strategy.target_weights(dt.date(2025, 1, 31), frame)
    assert result["weight"].to_list() == pytest.approx([2/3, 1/3])
    with pytest.raises(ValueError, match="Zero or unavailable"):
        strategy.target_weights(dt.date(2025, 1, 31), frame.with_columns(pl.lit(100.).alias("adjusted_close")))
    with pytest.raises(ValueError, match="Incomplete"):
        strategy.target_weights(dt.date(2025, 1, 31), frame.filter(~((pl.col("symbol") == "B")
            & (pl.col("trade_date") == dt.date(2025, 1, 29)))))


def test_midmonth_initialization_keeps_last_completed_month_cutoff():
    frame = pl.concat([prices(), pl.DataFrame({"symbol": ["A", "B"],
        "trade_date": [dt.date(2025, 2, 10)] * 2, "adjusted_close": [1000., 1.]})])
    dates = sorted(set(frame["trade_date"]) | {dt.date(2025, 2, 13), dt.date(2025, 2, 28)})
    calendar = pl.DataFrame({"date": dates, "market": ["SH"] * len(dates), "is_open": [True] * len(dates)})
    target = monthly_targets(frame, calendar, start=dt.date(2025, 2, 11), end=dt.date(2025, 2, 13),
        candidates=("A", "B"), name="sample", strategy=InverseVolatilityStrategy(("A", "B"), 3))
    assert target["weight"].to_list() == pytest.approx([2/3, 1/3])
    assert target["as_of"].to_list() == [dt.date(2025, 2, 10)] * 2
    assert target["execution_date"].to_list() == [dt.date(2025, 2, 13)] * 2
