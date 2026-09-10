"""Fixed monthly replication of Alpha101 #46."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.alpha101_046 import compute_alpha101_046
from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_046(config: dict[str, Any]) -> None:
    expected = {"long_lag": 20, "short_lag": 10, "change_lag": 1, "slope_divisor": 10,
        "upper_threshold": .25, "lower_threshold": 0., "minimum_valid_bars": 21,
        "price": "close_times_lag_adj_over_signal_adj", "threshold_unit": "CNY",
        "missing_session": "invalidate_21_bar_window", "zero_volume": "invalid_bar",
        "signal_frequency": "completed_month_end", "boundary_rule": "strict_gt_upper_strict_lt_lower"}
    composition = "alpha101_046_composition" in config
    names, directions = (["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", "alpha101_046"],
                         [-1, 1, -1, 1]) if composition else (["alpha101_046"], [1])
    if (any(config.get("alpha101_046", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != names or config["factors"]["directions"] != directions
        or config["portfolio"]["top_k"] != 50
        or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]
        or (not composition and "alpha101_006" not in config["admission"]["redundancy_references"])):
        raise ValueError("Alpha101 #46 requires fixed monthly Top50, as-of CNY prices and strict thresholds")
    if composition and (
        config["alpha101_046_composition"] != {"comparison": "three_factor", "eligibility": "complete_four_factor",
                                               "weights": "equal_zscore"}
        or config["admission"].get("comparison") != "three_factor"
        or "minimum_mean_test_rank_ic" in config["admission"]
        or any(config["admission"].get(k) is not True for k in (
            "require_positive_1x_compounded_return", "require_positive_2x_compounded_return",
            "require_positive_paired_1x_compounded_increment"))):
        raise ValueError("Alpha101 #46 composition requires a complete matched cohort and positive paired increment")


def build_monthly_alpha101_046(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    primary = compute_alpha101_046(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
    reference = compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_006")
    return primary.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
