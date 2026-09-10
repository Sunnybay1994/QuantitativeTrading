"""Monthly adapter for the existing Alpha101 #41 implementation."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_041(config: dict[str, Any]) -> None:
    expected = {"price": "raw_high_low", "vwap": "amount_cny_div_volume_shares", "adjustment": "none",
        "nonpositive_input": "null", "missing_session": "null_current_day",
        "signal_frequency": "completed_month_end"}
    composition = "alpha101_041_composition" in config
    names, directions = (["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", "alpha101_041"],
                         [-1, 1, -1, 1]) if composition else (["alpha101_041"], [1])
    if (any(config.get("alpha101_041", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != names or config["factors"]["directions"] != directions
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]
        or "alpha101_041" in config["admission"].get("redundancy_references", [])):
        raise ValueError("Alpha101 #41 requires fixed raw-price geometric mean minus VWAP and monthly Top50")

    if composition and (
        config["alpha101_041_composition"] != {"comparison": "three_factor", "eligibility": "complete_four_factor", "weights": "equal_zscore"}
        or config["admission"].get("comparison") != "three_factor"
        or "minimum_mean_test_rank_ic" in config["admission"]
        or any(config["admission"].get(k) is not True for k in (
            "require_positive_1x_compounded_return", "require_positive_2x_compounded_return",
            "require_positive_paired_1x_compounded_increment"))):
        raise ValueError("Alpha101 #41 composition requires a complete matched cohort and positive paired increment")


def build_monthly_alpha101_041(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_041", "alpha101_006", "alpha101_012")
