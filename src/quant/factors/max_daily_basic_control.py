"""Cross-sectional size and turnover control for the M2 MAX signal."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import polars as pl

from quant.domain import DailyBasic1dSchema
from quant.factors.classic_fifth_batch import compute_fifth_batch_daily_factors


@dataclass(frozen=True, slots=True)
class MaxDailyBasicControlSpec:
    """Auditable definition of one controlled MAX research signal."""

    name: str
    source: str
    mechanism: str
    missing_rule: str


MAX_DAILY_BASIC_CONTROL_SPECS: tuple[MaxDailyBasicControlSpec, ...] = (
    MaxDailyBasicControlSpec(
        "max_daily_return_20_size_turnover_residual",
        "daily cross-sectional average-rank OLS residual of MAX on size and turnover",
        "lottery-preference signal after same-close size and free-float-turnover "
        "control",
        "null when MAX or either control is missing, the design is ill-conditioned, "
        "or the frozen normal-equation check fails",
    ),
)

MAX_DAILY_BASIC_CONTROL_NAMES = tuple(
    spec.name for spec in MAX_DAILY_BASIC_CONTROL_SPECS
)

_RAW_MAX = "max_daily_return_20"
_SIZE_CONTROL = "log_total_market_value"
_TURNOVER_CONTROL = "turnover_rate_free"


def compute_max_daily_basic_control(
    bars: pl.DataFrame,
    daily_basic: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
    minimum_regression_rows: int,
    maximum_condition_number: float,
    orthogonality_tolerance: float,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return controlled MAX values and deterministic per-date OLS diagnostics."""
    if (
        not isinstance(daily_basic, pl.DataFrame)
        or daily_basic.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or sessions != tuple(sorted(set(sessions)))
        or any(type(value) is not dt.date for value in sessions)
        or type(minimum_regression_rows) is not int
        or minimum_regression_rows < 3
        or type(maximum_condition_number) is not float
        or not math.isfinite(maximum_condition_number)
        or maximum_condition_number <= 1.0
        or type(orthogonality_tolerance) is not float
        or not math.isfinite(orthogonality_tolerance)
        or not 0.0 < orthogonality_tolerance < 1.0
    ):
        raise ValueError("invalid MAX daily-basic control request")

    max_values = compute_fifth_batch_daily_factors(bars, sessions=sessions)
    clean_daily = DailyBasic1dSchema.validate(daily_basic).sort(
        "symbol", "trade_date", "source"
    )
    if clean_daily.select(
        pl.struct("symbol", "trade_date").is_duplicated().any()
    ).item():
        raise ValueError("MAX daily-basic controls must have one row per symbol-date")
    session_set = set(sessions)
    if any(
        value not in session_set
        for value in clean_daily.get_column("trade_date").to_list()
    ):
        raise ValueError("MAX daily-basic controls contain an out-of-calendar date")

    daily_controls = clean_daily.select(
        "symbol",
        "trade_date",
        pl.when(pl.col("total_market_value") > 0.0)
        .then(pl.col("total_market_value").log())
        .otherwise(None)
        .alias(_SIZE_CONTROL),
        pl.col(_TURNOVER_CONTROL),
    )
    base = (
        max_values.join(
            daily_controls,
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            "symbol",
            "trade_date",
            _RAW_MAX,
            _SIZE_CONTROL,
            _TURNOVER_CONTROL,
        )
        .sort("symbol", "trade_date")
    )
    complete = base.filter(
        pl.all_horizontal(
            pl.col(_RAW_MAX).is_not_null(),
            pl.col(_RAW_MAX).is_finite(),
            pl.col(_SIZE_CONTROL).is_not_null(),
            pl.col(_SIZE_CONTROL).is_finite(),
            pl.col(_TURNOVER_CONTROL).is_not_null(),
            pl.col(_TURNOVER_CONTROL).is_finite(),
        )
    )
    ranked = (
        complete.with_columns(
            pl.len().over("trade_date").alias("_n"),
            pl.col(_RAW_MAX).rank("average").over("trade_date").alias("_y"),
            pl.col(_SIZE_CONTROL)
            .rank("average")
            .over("trade_date")
            .alias("_size"),
            pl.col(_TURNOVER_CONTROL)
            .rank("average")
            .over("trade_date")
            .alias("_turnover"),
        )
        .with_columns(
            (pl.col("_y") - pl.col("_y").mean().over("trade_date")).alias(
                "_yc"
            ),
            (
                pl.col("_size")
                - pl.col("_size").mean().over("trade_date")
            ).alias("_sc"),
            (
                pl.col("_turnover")
                - pl.col("_turnover").mean().over("trade_date")
            ).alias("_tc"),
        )
        .with_columns(
            (pl.col("_sc") * pl.col("_sc")).sum().over("trade_date").alias(
                "_ss"
            ),
            (pl.col("_tc") * pl.col("_tc")).sum().over("trade_date").alias(
                "_tt"
            ),
            (pl.col("_sc") * pl.col("_tc")).sum().over("trade_date").alias(
                "_st"
            ),
            (pl.col("_yc") * pl.col("_sc")).sum().over("trade_date").alias(
                "_ys"
            ),
            (pl.col("_yc") * pl.col("_tc")).sum().over("trade_date").alias(
                "_yt"
            ),
        )
        .with_columns(
            (pl.col("_ss") * pl.col("_tt") - pl.col("_st") ** 2).alias(
                "_determinant"
            ),
            (pl.col("_ss") + pl.col("_tt")).alias("_trace"),
            (
                (pl.col("_ss") - pl.col("_tt")) ** 2
                + 4.0 * pl.col("_st") ** 2
            )
            .sqrt()
            .alias("_discriminant"),
        )
        .with_columns(
            ((pl.col("_trace") + pl.col("_discriminant")) / 2.0).alias(
                "_lambda_max"
            ),
            ((pl.col("_trace") - pl.col("_discriminant")) / 2.0).alias(
                "_lambda_min"
            ),
        )
        .with_columns(
            (pl.col("_lambda_max") / pl.col("_lambda_min")).alias(
                "_condition_number"
            )
        )
        .with_columns(
            (
                (pl.col("_n") >= minimum_regression_rows)
                & (pl.col("_determinant") > 0.0)
                & (pl.col("_lambda_min") > 0.0)
                & pl.col("_condition_number").is_finite()
                & (pl.col("_condition_number") <= maximum_condition_number)
            ).alias("_design_valid")
        )
        .with_columns(
            pl.when(pl.col("_design_valid"))
            .then(
                (
                    pl.col("_ys") * pl.col("_tt")
                    - pl.col("_yt") * pl.col("_st")
                )
                / pl.col("_determinant")
            )
            .otherwise(None)
            .alias("_beta_size"),
            pl.when(pl.col("_design_valid"))
            .then(
                (
                    pl.col("_yt") * pl.col("_ss")
                    - pl.col("_ys") * pl.col("_st")
                )
                / pl.col("_determinant")
            )
            .otherwise(None)
            .alias("_beta_turnover"),
        )
        .with_columns(
            (
                pl.col("_yc")
                - pl.col("_beta_size") * pl.col("_sc")
                - pl.col("_beta_turnover") * pl.col("_tc")
            ).alias("_residual")
        )
        .with_columns(
            (pl.col("_residual") * pl.col("_residual"))
            .sum()
            .over("trade_date")
            .alias("_rr"),
            (pl.col("_residual") * pl.col("_sc"))
            .sum()
            .over("trade_date")
            .alias("_rs"),
            (pl.col("_residual") * pl.col("_tc"))
            .sum()
            .over("trade_date")
            .alias("_rt"),
            pl.col("_residual").mean().over("trade_date").alias("_rmean"),
        )
        .with_columns(
            pl.when(pl.col("_design_valid") & (pl.col("_rr") > 0.0))
            .then(
                pl.max_horizontal(
                    pl.col("_rmean").abs(),
                    (
                        pl.col("_rs").abs()
                        / (pl.col("_rr") * pl.col("_ss")).sqrt()
                    ),
                    (
                        pl.col("_rt").abs()
                        / (pl.col("_rr") * pl.col("_tt")).sqrt()
                    ),
                )
            )
            .otherwise(None)
            .alias("_orthogonality_error")
        )
        .with_columns(
            (
                pl.col("_design_valid")
                & (pl.col("_rr") > 0.0)
                & pl.col("_orthogonality_error").is_not_null()
                & pl.col("_orthogonality_error").is_finite()
                & (pl.col("_orthogonality_error") <= orthogonality_tolerance)
            ).alias("_regression_valid")
        )
        .with_columns(
            pl.when(pl.col("_regression_valid"))
            .then(pl.col("_residual"))
            .otherwise(None)
            .alias(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        )
    )

    diagnostics = (
        ranked.group_by("trade_date")
        .agg(
            pl.col("_n").first().alias("complete_rows"),
            pl.col("_condition_number").first().alias("condition_number"),
            pl.col("_design_valid").first().alias("design_valid"),
            pl.col("_orthogonality_error")
            .first()
            .alias("orthogonality_error"),
            pl.col("_regression_valid").first().alias("regression_valid"),
        )
        .sort("trade_date")
    )
    all_dates = base.select("trade_date").unique().sort("trade_date")
    diagnostics = (
        all_dates.join(diagnostics, on="trade_date", how="left", validate="1:1")
        .with_columns(
            pl.col("complete_rows").fill_null(0).cast(pl.Int64),
            pl.col("design_valid").fill_null(False),
            pl.col("regression_valid").fill_null(False),
        )
        .sort("trade_date")
    )
    if diagnostics.filter(
        pl.col("design_valid")
        & (
            pl.col("orthogonality_error").is_null()
            | ~pl.col("orthogonality_error").is_finite()
            | (pl.col("orthogonality_error") > orthogonality_tolerance)
        )
    ).height:
        raise ValueError("MAX daily-basic normal equations failed")

    result = base.join(
        ranked.select(
            "symbol", "trade_date", MAX_DAILY_BASIC_CONTROL_NAMES[0]
        ),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    ).sort("symbol", "trade_date")
    if result.filter(
        pl.col(MAX_DAILY_BASIC_CONTROL_NAMES[0]).is_not_null()
        & (
            ~pl.col(MAX_DAILY_BASIC_CONTROL_NAMES[0]).is_finite()
            | pl.col(MAX_DAILY_BASIC_CONTROL_NAMES[0]).is_nan()
        )
    ).height:
        raise ValueError("controlled MAX factor contains non-finite values")
    return result, diagnostics


__all__ = [
    "MAX_DAILY_BASIC_CONTROL_NAMES",
    "MAX_DAILY_BASIC_CONTROL_SPECS",
    "MaxDailyBasicControlSpec",
    "compute_max_daily_basic_control",
]
