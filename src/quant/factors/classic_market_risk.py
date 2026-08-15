"""Benchmark-aware daily market-risk factors for M2 research."""

from __future__ import annotations

import datetime as dt
import math

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec

DOWNSIDE_BETA_NAME = "downside_beta_60_vs_510300"
MARKET_BETA_CONTROL_NAME = "market_beta_60_vs_510300"
REALIZED_VOLATILITY_CONTROL_NAME = "annualized_realized_volatility_60"

DOWNSIDE_BETA_FACTOR_NAMES = (DOWNSIDE_BETA_NAME,)
MARKET_RISK_CONTROL_NAMES = (
    MARKET_BETA_CONTROL_NAME,
    REALIZED_VOLATILITY_CONTROL_NAME,
)
DOWNSIDE_BETA_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        DOWNSIDE_BETA_NAME,
        "OLS beta of stock log returns on 510300 returns when 510300 is negative",
        "sixty-session downside systematic-risk exposure",
    ),
)


def compute_classic_market_risk_factors(
    stock_bars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
    benchmark_symbol: str,
    window_sessions: int = 60,
    minimum_down_market_observations: int = 15,
    annualization_sessions: int = 252,
    minimum_market_variance: float = 1e-12,
) -> pl.DataFrame:
    """Compute downside beta plus total-beta and realized-volatility controls.

    Returns use only adjacent entries in ``sessions``. A missing stock or
    benchmark bar therefore invalidates the affected rolling window instead of
    creating a cross-gap return.
    """
    if (
        not isinstance(stock_bars, pl.DataFrame)
        or stock_bars.is_empty()
        or not isinstance(benchmark_bars, pl.DataFrame)
        or benchmark_bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
        or type(benchmark_symbol) is not str
        or not benchmark_symbol
        or type(window_sessions) is not int
        or window_sessions < 2
        or type(minimum_down_market_observations) is not int
        or not 2 <= minimum_down_market_observations <= window_sessions
        or type(annualization_sessions) is not int
        or annualization_sessions <= 0
        or type(minimum_market_variance) is not float
        or not math.isfinite(minimum_market_variance)
        or minimum_market_variance <= 0
    ):
        raise ValueError("invalid classic market-risk factor request")

    stocks = Bar1dSchema.validate(stock_bars).sort("symbol", "trade_date", "source")
    benchmark = Bar1dSchema.validate(benchmark_bars).sort(
        "symbol", "trade_date", "source"
    )
    if _has_duplicate_keys(stocks) or _has_duplicate_keys(benchmark):
        raise ValueError("market-risk bars must have one source per symbol-date")
    if tuple(benchmark.get_column("symbol").unique().sort()) != (benchmark_symbol,):
        raise ValueError("market-risk benchmark symbol mismatch")
    session_frame = pl.DataFrame({"trade_date": sessions}, schema={"trade_date": pl.Date})
    session_set = set(sessions)
    if any(value not in session_set for value in stocks.get_column("trade_date")) or any(
        value not in session_set for value in benchmark.get_column("trade_date")
    ):
        raise ValueError("market-risk bars contain dates outside the session calendar")

    benchmark_returns = _benchmark_returns(
        benchmark,
        session_frame=session_frame,
    )
    symbols = stocks.select("symbol").unique().sort("symbol")
    stock_prices = stocks.select(
        "symbol",
        "trade_date",
        _valid_adjusted_close().alias("_stock_price"),
    )
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            stock_prices,
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            pl.col("_stock_price")
            .shift(1)
            .over("symbol")
            .alias("_previous_stock_price")
        )
        .with_columns(
            pl.when(
                pl.col("_stock_price").is_not_null()
                & pl.col("_previous_stock_price").is_not_null()
                & (pl.col("_stock_price") > 0)
                & (pl.col("_previous_stock_price") > 0)
            )
            .then((pl.col("_stock_price") / pl.col("_previous_stock_price")).log())
            .otherwise(None)
            .alias("_stock_return")
        )
        .join(benchmark_returns, on="trade_date", how="left", validate="m:1")
    )
    paired = (
        pl.col("_stock_return").is_not_null()
        & pl.col("_stock_return").is_finite()
        & pl.col("_market_return").is_not_null()
        & pl.col("_market_return").is_finite()
    ).fill_null(False)
    down = (paired & (pl.col("_market_return") < 0)).fill_null(False)
    prepared = grid.with_columns(
        paired.cast(pl.Int64).alias("_paired"),
        down.cast(pl.Int64).alias("_down"),
        pl.when(paired).then(pl.col("_market_return")).otherwise(0.0).alias("_m"),
        pl.when(paired).then(pl.col("_stock_return")).otherwise(0.0).alias("_s"),
        pl.when(down).then(pl.col("_market_return")).otherwise(0.0).alias("_dm"),
        pl.when(down).then(pl.col("_stock_return")).otherwise(0.0).alias("_ds"),
    )
    rolling = prepared.with_columns(
        *[
            pl.col(column)
            .rolling_sum(window_sessions, min_samples=window_sessions)
            .over("symbol")
            .alias(alias)
            for column, alias in (
                ("_paired", "_pair_count"),
                ("_down", "_down_count"),
                ("_m", "_m_sum"),
                ("_s", "_s_sum"),
                ("_dm", "_dm_sum"),
                ("_ds", "_ds_sum"),
            )
        ],
        *[
            expression
            .rolling_sum(window_sessions, min_samples=window_sessions)
            .over("symbol")
            .alias(alias)
            for expression, alias in (
                (pl.col("_m") * pl.col("_m"), "_m2_sum"),
                (pl.col("_m") * pl.col("_s"), "_ms_sum"),
                (pl.col("_s") * pl.col("_s"), "_s2_sum"),
                (pl.col("_dm") * pl.col("_dm"), "_dm2_sum"),
                (pl.col("_dm") * pl.col("_ds"), "_dms_sum"),
            )
        ],
    ).with_columns(
        (
            (pl.col("_m2_sum") - pl.col("_m_sum").pow(2) / window_sessions)
            / window_sessions
        ).alias("_market_variance"),
        (
            (
                pl.col("_ms_sum")
                - pl.col("_m_sum") * pl.col("_s_sum") / window_sessions
            )
            / window_sessions
        ).alias("_market_stock_covariance"),
        (pl.col("_s2_sum") - pl.col("_s_sum").pow(2) / window_sessions).alias(
            "_stock_ss"
        ),
        pl.when(pl.col("_down_count") > 0)
        .then(
            (
                pl.col("_dm2_sum")
                - pl.col("_dm_sum").pow(2) / pl.col("_down_count")
            )
            / pl.col("_down_count")
        )
        .otherwise(None)
        .alias("_down_market_variance"),
        pl.when(pl.col("_down_count") > 0)
        .then(
            (
                pl.col("_dms_sum")
                - pl.col("_dm_sum") * pl.col("_ds_sum") / pl.col("_down_count")
            )
            / pl.col("_down_count")
        )
        .otherwise(None)
        .alias("_down_market_stock_covariance"),
    )
    factors = rolling.with_columns(
        pl.when(
            (pl.col("_pair_count") == window_sessions)
            & (pl.col("_down_count") >= minimum_down_market_observations)
            & (pl.col("_down_market_variance") > minimum_market_variance)
        )
        .then(
            pl.col("_down_market_stock_covariance")
            / pl.col("_down_market_variance")
        )
        .otherwise(None)
        .alias(DOWNSIDE_BETA_NAME),
        pl.when(
            (pl.col("_pair_count") == window_sessions)
            & (pl.col("_market_variance") > minimum_market_variance)
        )
        .then(pl.col("_market_stock_covariance") / pl.col("_market_variance"))
        .otherwise(None)
        .alias(MARKET_BETA_CONTROL_NAME),
        pl.when(
            (pl.col("_pair_count") == window_sessions) & (pl.col("_stock_ss") >= 0)
        )
        .then(
            (pl.col("_stock_ss") / (window_sessions - 1)).sqrt()
            * math.sqrt(annualization_sessions)
        )
        .otherwise(None)
        .alias(REALIZED_VOLATILITY_CONTROL_NAME),
    )
    keys = stocks.select("symbol", "trade_date").sort("symbol", "trade_date")
    result = keys.join(
        factors.select(
            "symbol",
            "trade_date",
            DOWNSIDE_BETA_NAME,
            MARKET_BETA_CONTROL_NAME,
            REALIZED_VOLATILITY_CONTROL_NAME,
        ),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    )
    if result.select(
        pl.any_horizontal(
            *[
                pl.col(name).is_infinite() | pl.col(name).is_nan()
                for name in DOWNSIDE_BETA_FACTOR_NAMES + MARKET_RISK_CONTROL_NAMES
            ]
        ).any()
    ).item():
        raise ValueError("market-risk factors contain non-finite values")
    return result


def _benchmark_returns(
    benchmark: pl.DataFrame,
    *,
    session_frame: pl.DataFrame,
) -> pl.DataFrame:
    return (
        session_frame.join(
            benchmark.select(
                "trade_date", _valid_adjusted_close().alias("_market_price")
            ),
            on="trade_date",
            how="left",
            validate="1:1",
        )
        .sort("trade_date")
        .with_columns(pl.col("_market_price").shift(1).alias("_previous_market_price"))
        .with_columns(
            pl.when(
                pl.col("_market_price").is_not_null()
                & pl.col("_previous_market_price").is_not_null()
                & (pl.col("_market_price") > 0)
                & (pl.col("_previous_market_price") > 0)
            )
            .then((pl.col("_market_price") / pl.col("_previous_market_price")).log())
            .otherwise(None)
            .alias("_market_return")
        )
        .select("trade_date", "_market_return")
    )


def _valid_adjusted_close() -> pl.Expr:
    adjusted = pl.col("close") * pl.col("adj_factor")
    return (
        pl.when(
            pl.col("close").is_not_null()
            & pl.col("adj_factor").is_not_null()
            & pl.col("close").is_finite()
            & pl.col("adj_factor").is_finite()
            & (pl.col("close") > 0)
            & (pl.col("adj_factor") > 0)
        )
        .then(adjusted)
        .otherwise(None)
    )


def _has_duplicate_keys(frame: pl.DataFrame) -> bool:
    return bool(
        frame.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item()
    )


__all__ = [
    "DOWNSIDE_BETA_FACTOR_NAMES",
    "DOWNSIDE_BETA_FACTOR_SPECS",
    "DOWNSIDE_BETA_NAME",
    "MARKET_BETA_CONTROL_NAME",
    "MARKET_RISK_CONTROL_NAMES",
    "REALIZED_VOLATILITY_CONTROL_NAME",
    "compute_classic_market_risk_factors",
]
