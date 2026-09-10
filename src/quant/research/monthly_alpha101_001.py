"""Fixed monthly long-only adaptation of Alpha101 #1."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.alpha101_001 import compute_alpha101_001
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_alpha101_001(config: dict[str, Any]) -> None:
    expected = {"volatility_sessions": 20, "argmax_sessions": 5, "minimum_valid_prices": 25,
        "standard_deviation_ddof": 1, "price": "close_times_adj_factor",
        "argmax_index": "oldest_1_newest_5", "argmax_ties": "oldest",
        "cross_section_rank": "average_rank_minus_one_over_n_minus_one", "singleton_score": 0.0,
        "zero_volume": "invalid_price_observation", "missing_session": "invalidate_25_price_window",
        "signal_frequency": "completed_month_end"}
    if (any(config.get("alpha101_001", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["alpha101_001"] or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Alpha101 #1 requires fixed positive monthly Top50 and 20/5 windows")


def build_monthly_alpha101_001(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_alpha101_001(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
