"""Fixed 120-session low volatility with the original 60-session comparator."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.reversal_volatility import compute_total_volatility_windows
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_lowvol120(config: dict[str, Any]) -> None:
    expected = {"window_sessions": 120, "comparison_window_sessions": 60,
        "return_type": "adjusted_close_simple_return", "standard_deviation_ddof": 1,
        "annualization_sessions": 252, "minimum_valid_returns": 120,
        "missing_session": "invalidate_window", "signal_frequency": "completed_month_end"}
    if (any(config.get("lowvol120", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != ["realized_volatility_120"]
        or config["factors"]["directions"] != [-1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Low volatility requires fixed negative 120-session monthly Top50")


def build_monthly_lowvol120(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> pl.DataFrame:
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    return compute_total_volatility_windows(bars, sessions=sessions).filter(pl.col("trade_date").is_in(dates))
