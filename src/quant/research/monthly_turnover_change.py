"""Fixed 20/120-session abnormal turnover and existing turnover comparators."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.liquidity import compute_monthly_free_float_turnover_factors
from quant.factors.turnover_change import FACTOR_NAME, compute_turnover_change
from quant.factors.turnover_variability import compute_turnover_variability
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_turnover_change(config: dict[str, Any]) -> None:
    expected = {
        "short_window_sessions": 20, "long_window_sessions": 120,
        "input_column": "turnover_rate", "estimator": "mean_short_divided_by_mean_long",
        "long_window_includes_short": True, "minimum_valid_sessions": 120,
        "missing_session": "invalidate_window", "zero_turnover": "retain_reported_zero",
        "signal_frequency": "completed_month_end",
    }
    if (any(config.get("turnover_change", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != [FACTOR_NAME]
        or config["factors"]["directions"] != [-1]
        or config["portfolio"]["top_k"] != 50
        or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Turnover change requires fixed negative 20/120-session monthly Top50")


def build_monthly_turnover_change(
    daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...], candidates: tuple[str, ...],
    start: dt.date, end: dt.date,
) -> pl.DataFrame:
    """Keep old 12-month free-float abnormal turnover separate from the new ratio."""
    signal_dates = monthly_signal_sessions(sessions, start=sessions[0], end=end)
    ratio = compute_turnover_change(daily_basic, sessions=sessions).filter(
        pl.col("trade_date").is_in(signal_dates))
    cv = compute_turnover_variability(daily_basic, sessions=sessions).filter(
        pl.col("trade_date").is_in(signal_dates))
    old = compute_monthly_free_float_turnover_factors(
        daily_basic, signal_dates=signal_dates, candidate_symbols=candidates,
        minimum_valid_days=15, history_months=12,
    )
    return ratio.join(cv, on=["symbol", "trade_date"], how="left", validate="1:1").join(
        old, on=["symbol", "trade_date"], how="left", validate="1:1",
    ).filter(pl.col("trade_date").is_between(start, end))
