"""Fixed monthly Alpha101 #26 with the existing #6 as a redundancy control."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.alpha101_026 import compute_alpha101_026
from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_026(config: dict[str, Any]) -> None:
    expected = {"rank_sessions": 5, "correlation_sessions": 5, "maximum_sessions": 3,
        "minimum_valid_bars": 11, "high_price": "high_times_adj_factor", "volume": "raw_shares",
        "time_series_rank": "average_rank_minus_one_over_four", "constant_correlation": "null",
        "missing_session": "invalidate_11_bar_window", "zero_volume": "invalid_bar",
        "signal_frequency": "completed_month_end"}
    buffered = "alpha101_026_buffer" in config
    composition = "alpha101_026_composition" in config or buffered
    names, directions = (["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", "alpha101_026"],
                         [-1, 1, -1, 1]) if composition else (["alpha101_026"], [1])
    if (any(config.get("alpha101_026", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != names or config["factors"]["directions"] != directions
        or config["portfolio"]["top_k"] != 50
        or config["portfolio"].get("retention_rank", 50) != (75 if buffered else 50)
        or "execution_months" in config["portfolio"]
        or (not composition and "alpha101_006" not in config["admission"]["redundancy_references"])):
        raise ValueError("Alpha101 #26 requires fixed positive monthly Top50, 5/5/3 windows and #6 control")
    comparison = "alpha101_026_unbuffered" if buffered else "three_factor"
    section = "alpha101_026_buffer" if buffered else "alpha101_026_composition"
    experiment = {"comparison": comparison, "eligibility": "complete_four_factor", "weights": "equal_zscore"}
    if buffered:
        experiment["retention_rule"] = "prior_targets_top75_then_fill"
    if composition and (
        config[section] != experiment
        or (buffered and "alpha101_026_composition" in config)
        or (buffered and config["admission"].get("require_lower_turnover_every_fold") is not True)
        or config["admission"].get("comparison") != comparison
        or "minimum_mean_test_rank_ic" in config["admission"]
        or any(config["admission"].get(k) is not True for k in (
            "require_positive_1x_compounded_return", "require_positive_2x_compounded_return",
            "require_positive_paired_1x_compounded_increment"))):
        raise ValueError("Alpha101 #26 composition requires positive paired increment on the same complete pool")


def build_monthly_alpha101_026(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    primary = compute_alpha101_026(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
    reference = compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_006")
    return primary.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
