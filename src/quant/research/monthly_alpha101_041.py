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
    if (any(config.get("alpha101_041", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["alpha101_041"] or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]
        or "alpha101_041" in config["admission"].get("redundancy_references", [])):
        raise ValueError("Alpha101 #41 requires fixed raw-price geometric mean minus VWAP and monthly Top50")


def build_monthly_alpha101_041(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_041", "alpha101_006", "alpha101_012")
