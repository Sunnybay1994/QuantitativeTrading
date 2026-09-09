import datetime as dt

import polars as pl
import pytest

from quant.research.monthly_lowvol_reversal import select_low_volatility_pool


def test_ceiling_symbol_ties_and_date_local_selection():
    day = dt.date(2026, 1, 5)
    frame = pl.DataFrame({"trade_date": [day] * 11,
                          "symbol": [f"{n:06}.SH" for n in range(11)],
                          "realized_volatility_60": [0.1] * 11,
                          "reversal_20": [float(n) for n in range(11)]})
    selected = select_low_volatility_pool(frame.reverse(), keep_fraction=.3, minimum_candidates=4)
    assert selected["symbol"].to_list() == ["000000.SH", "000001.SH", "000002.SH", "000003.SH"]
    assert selected["low_vol_rank"].to_list() == [1, 2, 3, 4]
    future = frame.with_columns(pl.lit(day + dt.timedelta(days=1)).alias("trade_date"),
                                (-pl.col("reversal_20") + 20).alias("realized_volatility_60"))
    combined = select_low_volatility_pool(pl.concat([frame, future]), keep_fraction=.3, minimum_candidates=4)
    assert combined.filter(pl.col("trade_date") == day).equals(selected)
    # Reversal ranking happens after the filter; the high-reversal/high-vol tail is absent.
    assert selected.sort("reversal_20", descending=True).head(2)["symbol"].to_list() == ["000003.SH", "000002.SH"]


def test_insufficient_intersection_and_unknown_volatility_fail():
    frame = pl.DataFrame({"trade_date": [dt.date(2026, 1, 5)] * 3,
                          "symbol": ["a", "b", "c"], "realized_volatility_60": [0.1, 0.2, 0.3]})
    with pytest.raises(ValueError, match="target count"):
        select_low_volatility_pool(frame, keep_fraction=.3, minimum_candidates=2)
    for value in [None, float("nan"), -1.0]:
        invalid = frame.with_columns(pl.lit(value, dtype=pl.Float64).alias("realized_volatility_60"))
        with pytest.raises(ValueError, match="complete"):
            select_low_volatility_pool(invalid, keep_fraction=.3, minimum_candidates=1)
