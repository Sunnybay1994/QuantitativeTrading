"""Monthly adapter for the existing Alpha101 #12 implementation."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_012(config: dict[str, Any]) -> None:
    expected = {"delta_sessions": 1, "price": "close_times_adj_factor", "price_change": "absolute_difference",
        "volume": "raw_shares", "unchanged_volume": "zero", "missing_session": "invalidate_pair",
        "zero_volume": "invalid_bar", "signal_frequency": "completed_month_end"}
    buffered = "alpha101_012_buffer" in config
    composition = "alpha101_012_composition" in config or buffered
    names, directions = (["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", "alpha101_012"],
                         [-1, 1, -1, 1]) if composition else (["alpha101_012"], [1])
    if (any(config.get("alpha101_012", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != names or config["factors"]["directions"] != directions
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != (75 if buffered else 50)
        or "execution_months" in config["portfolio"]
        or "alpha101_012" in config["admission"].get("redundancy_references", [])):
        raise ValueError("Alpha101 #12 requires fixed one-session signed-volume/price delta and monthly Top50")

    comparison = "alpha101_012_unbuffered" if buffered else "three_factor"
    section = "alpha101_012_buffer" if buffered else "alpha101_012_composition"
    experiment = {"comparison": comparison, "eligibility": "complete_four_factor", "weights": "equal_zscore"}
    if buffered:
        experiment["retention_rule"] = "prior_targets_top75_then_fill"
    if composition and (
        config[section] != experiment
        or (buffered and "alpha101_012_composition" in config)
        or (buffered and config["admission"].get("require_lower_turnover_every_fold") is not True)
        or config["admission"].get("comparison") != comparison
        or "minimum_mean_test_rank_ic" in config["admission"]
        or any(config["admission"].get(k) is not True for k in (
            "require_positive_1x_compounded_return", "require_positive_2x_compounded_return",
            "require_positive_paired_1x_compounded_increment"))):
        raise ValueError("Alpha101 #12 composition requires a complete matched cohort and positive paired increment")


def build_monthly_alpha101_012(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_012", "alpha101_006")
