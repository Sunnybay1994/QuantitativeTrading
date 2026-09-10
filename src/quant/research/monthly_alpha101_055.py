"""Fixed monthly replication of Alpha101 #55."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.alpha101_055 import compute_alpha101_055
from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_055(config: dict[str, Any]) -> None:
    expected = {"range_sessions": 12, "correlation_sessions": 6, "minimum_valid_bars": 17,
        "price": "ohlc_times_adj_factor", "volume": "raw_shares",
        "cross_sectional_rank": "average_rank_minus_one_over_n_minus_one",
        "rank_cohort": "each_expression_finite_in_frozen_universe", "singleton_rank": .5,
        "flat_range": "null", "constant_correlation": "null", "missing_session": "invalidate_17_bar_window",
        "zero_volume": "invalid_bar", "signal_frequency": "completed_month_end"}
    if (any(config.get("alpha101_055", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["alpha101_055"]
        or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50
        or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Alpha101 #55 requires fixed 12/6 windows, positive direction and monthly Top50")


def build_monthly_alpha101_055(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    primary = compute_alpha101_055(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
    reference = compute_sixth_batch_daily_factors(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "alpha101_006")
    return primary.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
