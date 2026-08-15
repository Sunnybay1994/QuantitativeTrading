"""Monthly liquidity factors derived from verified A-share daily data."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import polars as pl

from quant.domain import Bar1dSchema, DailyBasic1dSchema


@dataclass(frozen=True, slots=True)
class LiquidityFactorSpec:
    """Auditable definition and missing-value rule for one liquidity factor."""

    name: str
    source: str
    mechanism: str
    missing_rule: str


LIQUIDITY_FACTOR_SPECS: tuple[LiquidityFactorSpec, ...] = (
    LiquidityFactorSpec(
        "amihud_illiquidity_monthly",
        "monthly mean(abs(adj_close return) / (amount CNY / 1e6))",
        "price impact per million CNY traded",
        "null unless at least 15 exchange-session-contiguous positive-amount days",
    ),
    LiquidityFactorSpec(
        "free_float_turnover_level_monthly",
        "monthly mean(daily_basic.turnover_rate_free / 100)",
        "free-float investor demand and trading intensity",
        "null unless at least 15 non-null vendor observations",
    ),
    LiquidityFactorSpec(
        "free_float_turnover_abnormal_12m",
        "current monthly free-float turnover / prior-12-month mean - 1",
        "turnover relative to the security's own trailing baseline",
        "null unless current and every prior 12 complete months are valid",
    ),
)

AMIHUD_FACTOR_NAMES = ("amihud_illiquidity_monthly",)
TURNOVER_FACTOR_NAMES = (
    "free_float_turnover_level_monthly",
    "free_float_turnover_abnormal_12m",
)
LIQUIDITY_FACTOR_NAMES = AMIHUD_FACTOR_NAMES + TURNOVER_FACTOR_NAMES


def compute_monthly_amihud_illiquidity(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
    minimum_valid_days: int = 15,
) -> pl.DataFrame:
    """Compute a complete candidate-by-month Amihud signal grid.

    A return is valid only when the preceding bar belongs to the immediately
    preceding exchange session.  This prevents a suspension gap from being
    treated as one ordinary daily return.
    """
    _validate_schedule(
        sessions=sessions,
        signal_dates=signal_dates,
        candidate_symbols=candidate_symbols,
        minimum_valid_days=minimum_valid_days,
    )
    if not isinstance(bars, pl.DataFrame) or bars.is_empty():
        raise ValueError("liquidity factor bars must be non-empty")
    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("liquidity bars must have one source per symbol-date")
    if not set(clean.get_column("symbol").unique().to_list()) <= set(candidate_symbols):
        raise ValueError("liquidity bars contain a symbol outside the candidate set")

    signal_calendar = _signal_calendar(signal_dates)
    exchange_calendar = pl.DataFrame(
        {
            "trade_date": sessions,
            "_expected_previous_date": (None, *sessions[:-1]),
        },
        schema={"trade_date": pl.Date(), "_expected_previous_date": pl.Date()},
    )
    daily = (
        clean.with_columns(
            (pl.col("close") * pl.col("adj_factor")).alias("_adj_close"),
            pl.col("trade_date").shift(1).over("symbol").alias("_actual_previous_date"),
        )
        .with_columns(
            pl.col("_adj_close").shift(1).over("symbol").alias("_previous_adj_close")
        )
        .join(exchange_calendar, on="trade_date", how="left", validate="m:1")
        .with_columns(
            pl.when(
                (pl.col("_actual_previous_date") == pl.col("_expected_previous_date"))
                & (pl.col("_previous_adj_close") > 0)
                & (pl.col("amount") > 0)
            )
            .then(
                (pl.col("_adj_close") / pl.col("_previous_adj_close") - 1.0).abs()
                / (pl.col("amount") / 1_000_000.0)
            )
            .otherwise(None)
            .alias("_amihud")
        )
        .with_columns(
            pl.col("trade_date").dt.year().alias("_year"),
            pl.col("trade_date").dt.month().alias("_month"),
        )
        .join(signal_calendar, on=["_year", "_month"], how="inner", validate="m:1")
    )
    monthly = (
        daily.group_by("symbol", "_signal_date")
        .agg(
            pl.col("_amihud").count().cast(pl.Int64).alias("amihud_valid_days"),
            pl.col("_amihud").mean().alias("_amihud_mean"),
        )
        .rename({"_signal_date": "trade_date"})
    )
    result = (
        _candidate_signal_grid(candidate_symbols, signal_dates)
        .join(monthly, on=["symbol", "trade_date"], how="left", validate="1:1")
        .with_columns(
            pl.col("amihud_valid_days").fill_null(0).cast(pl.Int64),
        )
        .with_columns(
            pl.when(pl.col("amihud_valid_days") >= minimum_valid_days)
            .then(pl.col("_amihud_mean"))
            .otherwise(None)
            .alias("amihud_illiquidity_monthly")
        )
        .drop("_amihud_mean")
        .sort("trade_date", "symbol")
    )
    _reject_non_finite(result, AMIHUD_FACTOR_NAMES)
    return result


def compute_monthly_free_float_turnover_factors(
    daily_basic: pl.DataFrame,
    *,
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
    minimum_valid_days: int = 15,
    history_months: int = 12,
) -> pl.DataFrame:
    """Compute monthly free-float turnover level and trailing anomaly."""
    _validate_schedule(
        sessions=signal_dates,
        signal_dates=signal_dates,
        candidate_symbols=candidate_symbols,
        minimum_valid_days=minimum_valid_days,
    )
    if type(history_months) is not int or history_months <= 0:
        raise ValueError("turnover history months must be positive")
    if not isinstance(daily_basic, pl.DataFrame) or daily_basic.is_empty():
        raise ValueError("liquidity daily-basic input must be non-empty")
    clean = DailyBasic1dSchema.validate(daily_basic).sort(
        "symbol", "trade_date", "source"
    )
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("liquidity daily-basic rows must have one source per symbol-date")
    if not set(clean.get_column("symbol").unique().to_list()) <= set(candidate_symbols):
        raise ValueError("liquidity daily-basic contains a symbol outside the candidate set")

    signal_calendar = _signal_calendar(signal_dates)
    monthly = (
        clean.with_columns(
            pl.col("trade_date").dt.year().alias("_year"),
            pl.col("trade_date").dt.month().alias("_month"),
            (pl.col("turnover_rate_free") / 100.0).alias("_turnover"),
        )
        .join(signal_calendar, on=["_year", "_month"], how="inner", validate="m:1")
        .group_by("symbol", "_signal_date")
        .agg(
            pl.col("_turnover")
            .count()
            .cast(pl.Int64)
            .alias("free_float_turnover_valid_days"),
            pl.col("_turnover").mean().alias("_turnover_mean"),
        )
        .rename({"_signal_date": "trade_date"})
    )
    result = (
        _candidate_signal_grid(candidate_symbols, signal_dates)
        .join(monthly, on=["symbol", "trade_date"], how="left", validate="1:1")
        .with_columns(
            pl.col("free_float_turnover_valid_days").fill_null(0).cast(pl.Int64)
        )
        .with_columns(
            pl.when(pl.col("free_float_turnover_valid_days") >= minimum_valid_days)
            .then(pl.col("_turnover_mean"))
            .otherwise(None)
            .alias("free_float_turnover_level_monthly")
        )
        .drop("_turnover_mean")
        .sort("symbol", "trade_date")
        .with_columns(
            pl.col("free_float_turnover_level_monthly")
            .shift(1)
            .rolling_mean(window_size=history_months, min_samples=history_months)
            .over("symbol")
            .alias("_turnover_history_mean")
        )
        .with_columns(
            pl.when(
                pl.col("free_float_turnover_level_monthly").is_not_null()
                & (pl.col("_turnover_history_mean") > 0)
            )
            .then(
                pl.col("free_float_turnover_level_monthly")
                / pl.col("_turnover_history_mean")
                - 1.0
            )
            .otherwise(None)
            .alias("free_float_turnover_abnormal_12m")
        )
        .drop("_turnover_history_mean")
        .sort("trade_date", "symbol")
    )
    _reject_non_finite(result, TURNOVER_FACTOR_NAMES)
    return result


def _validate_schedule(
    *,
    sessions: tuple[dt.date, ...],
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
    minimum_valid_days: int,
) -> None:
    if (
        type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
        or type(signal_dates) is not tuple
        or not signal_dates
        or any(type(value) is not dt.date for value in signal_dates)
        or signal_dates != tuple(sorted(set(signal_dates)))
        or not set(signal_dates) <= set(sessions)
        or any(
            current.year * 12
            + current.month
            - (previous.year * 12 + previous.month)
            != 1
            for previous, current in zip(signal_dates, signal_dates[1:])
        )
        or type(candidate_symbols) is not tuple
        or not candidate_symbols
        or any(type(symbol) is not str or not symbol for symbol in candidate_symbols)
        or candidate_symbols != tuple(sorted(set(candidate_symbols)))
        or type(minimum_valid_days) is not int
        or minimum_valid_days <= 0
    ):
        raise ValueError("invalid monthly liquidity factor schedule")


def _signal_calendar(signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        {"_signal_date": signal_dates}, schema={"_signal_date": pl.Date()}
    ).with_columns(
        pl.col("_signal_date").dt.year().alias("_year"),
        pl.col("_signal_date").dt.month().alias("_month"),
    )


def _candidate_signal_grid(
    candidate_symbols: tuple[str, ...], signal_dates: tuple[dt.date, ...]
) -> pl.DataFrame:
    return (
        pl.DataFrame({"symbol": candidate_symbols})
        .join(
            pl.DataFrame({"trade_date": signal_dates}, schema={"trade_date": pl.Date()}),
            how="cross",
        )
        .sort("trade_date", "symbol")
    )


def _reject_non_finite(frame: pl.DataFrame, factors: tuple[str, ...]) -> None:
    if frame.select(
        pl.any_horizontal(
            *(pl.col(name).is_not_null() & pl.col(name).is_infinite() for name in factors)
        ).any()
    ).item():
        raise ValueError("monthly liquidity factors contain infinite values")


__all__ = [
    "AMIHUD_FACTOR_NAMES",
    "LIQUIDITY_FACTOR_NAMES",
    "LIQUIDITY_FACTOR_SPECS",
    "TURNOVER_FACTOR_NAMES",
    "LiquidityFactorSpec",
    "compute_monthly_amihud_illiquidity",
    "compute_monthly_free_float_turnover_factors",
]
