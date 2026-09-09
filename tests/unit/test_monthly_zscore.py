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


def test_retention_buffer_keeps_marginal_members_then_replaces_missing_names():
    days = (dt.date(2025, 12, 31), dt.date(2026, 1, 5), dt.date(2026, 1, 30),
            dt.date(2026, 2, 2), dt.date(2026, 2, 27), dt.date(2026, 3, 2))
    panel = pl.DataFrame({"trade_date": [days[0]] * 4 + [days[2]] * 4 + [days[4]] * 3,
                         "symbol": ["a", "b", "c", "d", "c", "a", "b", "d", "d", "c", "a"],
                         "equal_zscore": [4., 3., 2., 1., 4., 3., 2., 1., 4., 3., 2.]})
    kwargs = dict(sessions=days, start=dt.date(2026, 1, 1), end=days[-1], top_k=2, strategy_name="test")
    default = build_monthly_zscore_targets(panel, **kwargs)
    assert_frame_equal(default, build_monthly_zscore_targets(panel, **kwargs, retention_rank=2))
    buffered = build_monthly_zscore_targets(panel, **kwargs, retention_rank=3)
    assert default.filter(pl.col("as_of") == days[2])["symbol"].to_list() == ["a", "c"]
    assert buffered.filter(pl.col("as_of") == days[2])["symbol"].to_list() == ["a", "b"]
    assert buffered.filter(pl.col("as_of") == days[4])["symbol"].to_list() == ["a", "d"]
    early = build_monthly_zscore_targets(panel.filter(pl.col("trade_date") < days[4]),
        sessions=days, start=dt.date(2026, 1, 1), end=days[3], top_k=2, strategy_name="test", retention_rank=3)
    assert_frame_equal(early, buffered.filter(pl.col("execution_date") <= days[3]))
    with pytest.raises(ValueError, match="Retention"):
        build_monthly_zscore_targets(panel, **kwargs, retention_rank=1)


def test_portfolio_candidate_requires_every_fold_and_double_cost_evidence():
    from copy import deepcopy
    from quant.research.classic_monthly_baseline import meets_portfolio_candidate

    admission = {"minimum_annual_excess_1x": .03, "maximum_annual_one_way_turnover": 6.,
                 "maximum_drawdown_ratio_to_benchmark": 1.5}
    rows = []
    for fold in (1, 2):
        rows.extend([
            {"fold": fold, "comparison": "top50", "cost_multiplier": 1,
             "cagr": .10, "annualized_one_way_turnover": 6., "max_drawdown": -.15},
            {"fold": fold, "comparison": "510300", "cost_multiplier": 1,
             "cagr": .05, "max_drawdown": -.10},
            {"fold": fold, "comparison": "top50", "cost_multiplier": 2, "total_return": .01},
        ])
    assert meets_portfolio_candidate(rows, admission)
    for key, value in (("cagr", .07), ("annualized_one_way_turnover", 6.01), ("max_drawdown", -.151)):
        failed = deepcopy(rows)
        failed[3][key] = value
        assert not meets_portfolio_candidate(failed, admission)
    assert not meets_portfolio_candidate(rows[:-1], admission)
    rows[-1]["total_return"] = 0.
    assert not meets_portfolio_candidate(rows, admission)
