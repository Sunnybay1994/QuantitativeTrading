"""Fourth-batch Alpha158 shape and volume factors for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec

FOURTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha158_resi20",
        "Alpha158 RESI20: Resi(adj_close,20)/adj_close",
        "latest normalized residual from a twenty-session close-price trend",
    ),
    ClassicFactorSpec(
        "alpha158_imxd20",
        "Alpha158 IMXD20: (IdxMax(adj_high,20)-IdxMin(adj_low,20))/20",
        "relative timing of the first rolling high and first rolling low",
    ),
    ClassicFactorSpec(
        "alpha158_vsumd20",
        "Alpha158 VSUMD20: signed volume-change sum / absolute volume-change sum",
        "twenty-session directional volume-change amplitude imbalance",
    ),
)

FOURTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in FOURTH_BATCH_FACTOR_SPECS)

_WINDOW = 20
_X_SUM = 190.0
_X_SQUARED_SUM = 2470.0
_X_DENOMINATOR = _WINDOW * _X_SQUARED_SUM - _X_SUM * _X_SUM
_X_LAST_DEVIATION = (_WINDOW - 1) - (_X_SUM / _WINDOW)
_X_WEIGHTS = [float(value) for value in range(_WINDOW)]


def compute_fourth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute strict-session RESI20, IMXD20 and VSUMD20 values.

    RESI20 and IMXD20 require twenty consecutive exchange sessions. VSUMD20
    requires twenty consecutive volume changes, hence twenty-one observations.
    Missing bars invalidate the affected window instead of joining across a gap.
    """
    if (
        not isinstance(bars, pl.DataFrame)
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid fourth-batch factor request")

    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("fourth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("fourth-batch bars contain dates outside the session calendar")

    session_frame = pl.DataFrame(
        {"trade_date": sessions},
        schema={"trade_date": pl.Date},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            clean.select(
                "symbol",
                "trade_date",
                "high",
                "low",
                "close",
                "volume",
                "adj_factor",
            ),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            _valid_adjusted_price("high").alias("_adj_high"),
            _valid_adjusted_price("low").alias("_adj_low"),
            _valid_adjusted_price("close").alias("_adj_close"),
            pl.when(
                pl.col("volume").is_not_null()
                & pl.col("volume").is_finite()
                & (pl.col("volume") >= 0)
            )
            .then(pl.col("volume"))
            .otherwise(None)
            .alias("_volume"),
        )
        .with_columns(
            pl.col("_volume").diff().over("symbol").alias("_volume_change"),
            pl.col("_adj_close")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_close_count"),
            pl.col("_adj_high")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_high_count"),
            pl.col("_adj_low")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_low_count"),
            pl.col("_adj_close")
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_close_sum"),
            pl.col("_adj_close")
            .fill_null(0.0)
            .rolling_sum(
                _WINDOW,
                weights=_X_WEIGHTS,
                min_samples=_WINDOW,
            )
            .over("symbol")
            .alias("_close_weighted_sum"),
            pl.col("_adj_high")
            .rolling_max(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_rolling_high"),
            pl.col("_adj_low")
            .rolling_min(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_rolling_low"),
        )
        .with_columns(
            (
                (
                    _WINDOW * pl.col("_close_weighted_sum")
                    - _X_SUM * pl.col("_close_sum")
                )
                / _X_DENOMINATOR
            ).alias("_close_slope"),
            _oldest_extreme_lag("_adj_high", "_rolling_high").alias(
                "_high_lag"
            ),
            _oldest_extreme_lag("_adj_low", "_rolling_low").alias("_low_lag"),
            pl.col("_volume_change")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_volume_change_count"),
            pl.col("_volume_change")
            .clip(lower_bound=0)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_volume_gain_sum"),
            (-pl.col("_volume_change"))
            .clip(lower_bound=0)
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_volume_loss_sum"),
            pl.col("_volume_change")
            .abs()
            .rolling_sum(_WINDOW, min_samples=_WINDOW)
            .over("symbol")
            .alias("_volume_absolute_sum"),
        )
        .with_columns(
            pl.when((pl.col("_close_count") == _WINDOW) & (pl.col("_adj_close") > 0))
            .then(
                (
                    pl.col("_adj_close")
                    - (
                        pl.col("_close_sum") / _WINDOW
                        + pl.col("_close_slope") * _X_LAST_DEVIATION
                    )
                )
                / pl.col("_adj_close")
            )
            .otherwise(None)
            .alias("alpha158_resi20"),
            pl.when(
                (pl.col("_high_count") == _WINDOW)
                & (pl.col("_low_count") == _WINDOW)
                & (pl.col("_high_lag") >= 0)
                & (pl.col("_low_lag") >= 0)
            )
            .then((pl.col("_low_lag") - pl.col("_high_lag")) / _WINDOW)
            .otherwise(None)
            .alias("alpha158_imxd20"),
            pl.when(pl.col("_volume_change_count") == _WINDOW)
            .then(
                (pl.col("_volume_gain_sum") - pl.col("_volume_loss_sum"))
                / (pl.col("_volume_absolute_sum") + 1e-12)
            )
            .otherwise(None)
            .alias("alpha158_vsumd20"),
        )
    )
    result = keys.join(
        grid.select("symbol", "trade_date", *FOURTH_BATCH_FACTOR_NAMES),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    )
    if result.select(
        pl.any_horizontal(
            *[
                pl.col(name).is_infinite() | pl.col(name).is_nan()
                for name in FOURTH_BATCH_FACTOR_NAMES
            ]
        ).any()
    ).item():
        raise ValueError("fourth-batch factors contain non-finite values")
    return result.sort("symbol", "trade_date")


def _valid_adjusted_price(column: str) -> pl.Expr:
    raw = pl.col(column)
    factor = pl.col("adj_factor")
    return (
        pl.when(
            raw.is_not_null()
            & factor.is_not_null()
            & raw.is_finite()
            & factor.is_finite()
            & (raw > 0)
            & (factor > 0)
        )
        .then(raw * factor)
        .otherwise(None)
    )


def _oldest_extreme_lag(value: str, extreme: str) -> pl.Expr:
    return pl.max_horizontal(
        *[
            pl.when(
                pl.col(value).shift(lag).over("symbol") == pl.col(extreme)
            )
            .then(pl.lit(lag))
            .otherwise(pl.lit(-1))
            for lag in range(_WINDOW)
        ]
    )


__all__ = [
    "FOURTH_BATCH_FACTOR_NAMES",
    "FOURTH_BATCH_FACTOR_SPECS",
    "compute_fourth_batch_daily_factors",
]
