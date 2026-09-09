import datetime as dt
import math

import polars as pl
import pytest

from quant.factors.market_size import compute_market_size
from quant.research.classic_factor_composite import (
    build_equal_weight_zscore_composite, build_monthly_zscore_targets,
)


def sample():
    return pl.DataFrame({"symbol": list("ABCDEFGH"), "trade_date": [dt.date(2024, 1, 31)] * 8,
        "total_market_value": [100., 10., 10., 0., -1., float("inf"), float("nan"), None]})


def test_invalid_caps_are_excluded_and_duplicate_dates_rejected():
    result = compute_market_size(sample())
    assert result["log_total_market_value"].to_list()[:3] == [math.log(100.), math.log(10.), math.log(10.)]
    assert result["log_total_market_value"].null_count() == 5
    with pytest.raises(ValueError, match="Duplicate"):
        compute_market_size(pl.concat([sample(), sample().head(1)]))


def test_negative_size_selects_smallest_next_session_without_future_leakage():
    future = sample().with_columns(pl.lit(dt.date(2024, 2, 1)).alias("trade_date"),
                                   pl.lit(1.).alias("total_market_value"))
    def targets(basic):
        scored = build_equal_weight_zscore_composite(compute_market_size(basic),
            component_directions=(("log_total_market_value", -1),))
        return build_monthly_zscore_targets(scored,
            sessions=(dt.date(2024, 1, 31), dt.date(2024, 2, 1)),
            start=dt.date(2024, 2, 1), end=dt.date(2024, 2, 1), top_k=2, strategy_name="size")
    result = targets(sample())
    assert result["symbol"].to_list() == ["B", "C"]
    assert result.equals(targets(pl.concat([sample(), future])))
    assert result["as_of"][0] < result["execution_date"][0]


def test_circulating_size_uses_its_own_column_and_can_reverse_total_size_rank():
    frame = sample().head(3).with_columns(pl.Series("circulating_market_value", [5., 8., 7.]))
    total = compute_market_size(frame)
    circulating = compute_market_size(frame, column="circulating_market_value")
    assert total.sort("log_total_market_value", "symbol")["symbol"].to_list() == ["B", "C", "A"]
    assert circulating.sort("log_circulating_market_value")["symbol"].to_list() == ["A", "C", "B"]
    invalid = frame.with_columns(pl.Series("circulating_market_value", [0., None, float("inf")]))
    assert compute_market_size(invalid, column="circulating_market_value")["log_circulating_market_value"].null_count() == 3
    with pytest.raises(ValueError, match="Unsupported"):
        compute_market_size(frame, column="pb")
