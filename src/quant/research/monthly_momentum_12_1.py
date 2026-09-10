"""Fixed twelve-minus-one momentum using the existing complete-formation estimator."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.information_discreteness import compute_information_discreteness
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_momentum_12_1(config: dict[str, Any]) -> None:
    expected = {"formation_sessions": 231, "skip_sessions": 21, "total_lookback_sessions": 252,
        "formula": "adjusted_close[t-21] / adjusted_close[t-252] - 1",
        "minimum_valid_returns": 231, "zero_volume": "invalid_price_observation",
        "missing_session": "invalidate_formation_window", "winner_fraction": 1.0,
        "signal_frequency": "completed_month_end"}
    if (any(config.get("momentum_12_1", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["momentum_12_1"] or config["factors"]["directions"] != [1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Momentum requires fixed positive 252-minus-21 monthly Top50")


def build_monthly_momentum_12_1(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    """The B26 252-return/21-skip value stays a separate redundancy reference."""
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    primary = compute_information_discreteness(bars, sessions=sessions, formation_sessions=231, skip_sessions=21)
    primary = primary.filter(pl.col("trade_date").is_in(dates)).select(
        "symbol", "trade_date", pl.col("pret_12m_skip1m").alias("momentum_12_1"),
        "formation_valid_returns", "formation_price_start", "formation_end")
    reference = compute_information_discreteness(bars, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "pret_12m_skip1m")
    return primary.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
