"""Fixed monthly replication of Alpha101 #54."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.alpha101_054 import compute_alpha101_054
from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_054(config: dict[str, Any]) -> None:
    expected = {"power": 5, "direction": 1, "price": "same_session_ohlc_ratios",
        "flat_range": "null", "missing_session": "null_no_fill", "zero_volume": "invalid_bar",
        "signal_frequency": "completed_month_end"}
    if (any(config.get("alpha101_054", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["alpha101_054"]
        or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50
        or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Alpha101 #54 requires fixed power five, positive direction and monthly Top50")


def build_monthly_alpha101_054(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    primary = compute_alpha101_054(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
    reference = compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_006")
    return primary.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
