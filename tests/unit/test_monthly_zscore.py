import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.classic_factor_composite import (
    build_equal_weight_zscore_composite, build_monthly_zscore_targets,
)


def test_zscore_complete_cases_zero_variance_and_future_invariance():
    day = dt.date(2026, 1, 30)
    panel = pl.DataFrame({"trade_date": [day] * 4, "symbol": ["a", "b", "c", "missing"],
                          "x": [1.0, 2.0, 3.0, None], "y": [4.0, 4.0, 4.0, 10000.0]})
    result = build_equal_weight_zscore_composite(panel, component_directions=(("x", 1), ("y", -1)))
    assert result.get_column("symbol").to_list() == ["a", "b", "c"]
    assert result.get_column("equal_zscore").to_list() == pytest.approx([-0.6123724357, 0.0, 0.6123724357])
    future = panel.with_columns(pl.lit(dt.date(2026, 2, 2)).alias("trade_date"), (pl.col("x") * 1000).alias("x"))
    extended = build_equal_weight_zscore_composite(pl.concat([panel, future]), component_directions=(("x", 1), ("y", -1)))
    assert_frame_equal(result, extended.filter(pl.col("trade_date") == day))


def test_monthly_targets_use_prior_session_and_literal_symbol_tie_break():
    sessions = (dt.date(2025, 12, 31), dt.date(2026, 1, 5), dt.date(2026, 1, 30), dt.date(2026, 2, 2), dt.date(2026, 2, 3))
    panel = pl.DataFrame({"trade_date": [sessions[0]] * 2 + [sessions[2]] * 2,
                          "symbol": ["b", "a", "b", "a"], "equal_zscore": [0.0, 0.0, 2.0, 1.0]})
    targets = build_monthly_zscore_targets(panel, sessions=sessions, start=dt.date(2026, 1, 1),
        end=sessions[-1], top_k=1, strategy_name="test")
    assert targets.get_column("as_of").to_list() == [sessions[0], sessions[2]]
    assert targets.get_column("execution_date").to_list() == [sessions[1], sessions[3]]
    assert targets.get_column("symbol").to_list() == ["a", "b"]
    assert targets.get_column("weight").to_list() == [1.0, 1.0]
