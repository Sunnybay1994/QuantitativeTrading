"""CV20 and its existing liquidity/price-volume comparators, at month ends."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors.classic_second_batch import compute_second_batch_daily_factors
from quant.factors.liquidity import compute_monthly_free_float_turnover_factors
from quant.factors.turnover_variability import compute_turnover_variability
from quant.research.pit_quality_research import monthly_signal_sessions


def build_monthly_turnover_variability(
    *, bars: pl.DataFrame, daily_basic: pl.DataFrame, sessions: tuple[dt.date, ...],
    candidates: tuple[str, ...], start: dt.date, end: dt.date, settings: dict[str, Any],
) -> pl.DataFrame:
    """Compute on full history; truncate only after all trailing comparators exist."""
    expected = {
        "window_sessions": 20, "parameter_grid": [20], "minimum_valid_sessions": 20,
        "input_table": "daily_basic", "input_column": "turnover_rate",
        "missing_session": "null_window_not_previous_20_observations",
        "valid_values": "finite_nonnegative_with_positive_mean",
        "zero_turnover": "retain_only_if_reported_do_not_impute",
        "signal_frequency": "completed_month_end", "availability": "signal_date_close",
        "label": "next_session_open_to_open_20_sessions_later",
        "drop_labels_crossing_fold_end": True,
        "direction_selection": "fixed_negative_no_validation_flip",
        "formula": "std(turnover_rate / 100, last_20_exchange_sessions, ddof=0) / mean(turnover_rate / 100, last_20_exchange_sessions)",
    }
    if any(settings.get(k) != value for k, value in expected.items()):
        raise ValueError("Unsupported pre-registered CV20 configuration")
    signal_dates = monthly_signal_sessions(sessions, start=sessions[0], end=end)
    cv = compute_turnover_variability(daily_basic, sessions=sessions).filter(
        pl.col("trade_date").is_in(signal_dates))
    volume = compute_second_batch_daily_factors(bars).select("symbol", "trade_date", "alpha158_wvma20")
    turnover = compute_monthly_free_float_turnover_factors(
        daily_basic, signal_dates=signal_dates, candidate_symbols=candidates,
        minimum_valid_days=15, history_months=12,
    )
    return cv.join(volume, on=["symbol", "trade_date"], how="left", validate="1:1").join(
        turnover, on=["symbol", "trade_date"], how="left", validate="1:1",
    ).filter(pl.col("trade_date").is_between(start, end))
