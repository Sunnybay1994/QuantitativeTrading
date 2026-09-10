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
    if (any(config.get("alpha101_012", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["alpha101_012"] or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]
        or "alpha101_012" in config["admission"].get("redundancy_references", [])):
        raise ValueError("Alpha101 #12 requires fixed one-session signed-volume/price delta and monthly Top50")


def build_monthly_alpha101_012(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_012", "alpha101_006")
