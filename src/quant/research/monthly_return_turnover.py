"""Monthly synchronous return/turnover correlation and Alpha158 comparators."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.classic_second_batch import compute_second_batch_daily_factors
from quant.factors.classic_third_batch import compute_third_batch_daily_factors
from quant.factors.return_turnover_correlation import FACTOR_NAME, compute_return_turnover_correlation
from quant.research.pit_quality_research import monthly_signal_sessions


def validate_return_turnover(config: dict[str, Any]) -> None:
    expected = {
        "window_sessions": 20, "return_type": "adjusted_close_simple_return",
        "input_column": "turnover_rate", "lag_sessions": 0, "estimator": "pearson",
        "minimum_pair_count": 20, "minimum_population_variance": 1e-12,
        "missing_session": "invalidate_window", "signal_frequency": "completed_month_end",
    }
    if (any(config.get("return_turnover", {}).get(k) != v for k, v in expected.items())
        or config["factors"]["names"] != [FACTOR_NAME] or config["factors"]["directions"] != [-1]
        or config["portfolio"]["top_k"] != 50 or config["portfolio"].get("retention_rank", 50) != 50
        or "execution_months" in config["portfolio"]):
        raise ValueError("Return-turnover requires fixed synchronous 20-session negative Top50")


def build_monthly_return_turnover(
    bars: pl.DataFrame, daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...],
    start: dt.date, end: dt.date,
) -> pl.DataFrame:
    """Keep the new return/turnover factor distinct from existing CORR20/CORD20."""
    dates = monthly_signal_sessions(sessions, start=start, end=end)
    values = compute_return_turnover_correlation(bars, daily_basic, sessions=sessions).filter(
        pl.col("trade_date").is_in(dates))
    for compute, name in ((compute_second_batch_daily_factors, "alpha158_corr20"),
                          (compute_third_batch_daily_factors, "alpha158_cord20")):
        reference = compute(bars).select("symbol", "trade_date", name)
        values = values.join(reference, on=["symbol", "trade_date"], how="left", validate="1:1")
    return values
