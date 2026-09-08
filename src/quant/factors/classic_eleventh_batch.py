"""Eleventh-batch Alpha101 #002 price-volume divergence factor."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec
from quant.factors.cross_sectional_rank import rank_cross_sectional_components


ELEVENTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_002",
        "Alpha101 #002: -correlation(rank(delta(log(volume), 2)), "
        "rank((close-open)/open), 6)",
        "six-session price-volume divergence",
    ),
)
ELEVENTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in ELEVENTH_BATCH_FACTOR_SPECS)

_NUMERIC_SOURCE_COLUMNS = ("open", "close", "volume", "adj_factor")
_REQUIRED_SESSIONS = 8
_CORRELATION_WINDOW = 6
_TRACE_COMPONENTS = ("volume_change", "intraday_return")

_TRACE_FACTOR_COLUMNS = ["symbol", "trade_date", "alpha101_002"]
_TRACE_COMPONENT_COUNT_COLUMNS = [
    "trade_date",
    "component",
    "grid_symbols",
    "finite_values",
    "ranked_values",
]
_TRACE_OBSERVATION_COLUMNS = [
    "symbol",
    "trade_date",
    "bar_present",
    "volume_change",
    "intraday_return",
    "volume_rank",
    "return_rank",
    "window_ready",
    "pair_count",
    "volume_ss",
    "return_ss",
    "alpha101_002",
    "primary_reason",
    "session_index",
    "current_bar_missing",
    "lag1_bar_missing",
    "lag2_bar_missing",
    "current_volume_zero",
    "lag2_volume_zero",
    "volume_rank_members_lt2",
    "return_rank_members_lt2",
]


@dataclass(frozen=True, slots=True)
class _EleventhBatchComputation:
    factors: pl.DataFrame
    grid: pl.DataFrame


def compute_eleventh_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the frozen local Alpha101 #002 adaptation.

    The public rank helper is called exactly once with both component columns in
    one long-form frame.  Missing bars remain explicit grid rows so lag and
    rolling windows cannot bridge a session gap.
    """
    return _compute_eleventh_batch_core(bars, sessions=sessions).factors


def compute_eleventh_batch_daily_factors_with_trace(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> dict[str, pl.DataFrame]:
    """Compute Alpha101 #002 and its single-pass component/window trace.

    The returned mapping is materialized only after all trace invariants pass;
    an unexplained trace intermediate raises without returning partial tables.
    """
    computation = _compute_eleventh_batch_core(bars, sessions=sessions)
    component_counts = _project_component_counts(computation.grid)
    observations = _project_observations(computation.grid)
    _validate_trace(
        factors=computation.factors,
        grid=computation.grid,
        component_counts=component_counts,
        observations=observations,
    )
    return {
        "factors": computation.factors,
        "component_counts": component_counts,
        "observations": observations,
    }


def _compute_eleventh_batch_core(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> _EleventhBatchComputation:
    if (
        type(bars) is not pl.DataFrame
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid eleventh-batch factor request")
    if any(bars.schema.get(column) == pl.Boolean for column in _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("eleventh-batch bars contain boolean numeric sources")
    try:
        clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    except Exception as exc:
        raise ValueError("eleventh-batch bars fail Bar1dSchema validation") from exc
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("eleventh-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("eleventh-batch bars contain dates outside the session calendar")
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("eleventh-batch bars contain non-finite numeric sources")

    session_frame = pl.DataFrame(
        {"trade_date": sessions, "_session_index": list(range(len(sessions)))},
        schema={"trade_date": pl.Date, "_session_index": pl.UInt32},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    present = clean.select("symbol", "trade_date", "open", "close", "volume").with_columns(
        pl.lit(1, dtype=pl.Int64).alias("_bar_present")
    )
    grid = (
        symbols.join(session_frame, how="cross")
        .join(present, on=["symbol", "trade_date"], how="left", validate="1:1")
        .sort("symbol", "trade_date")
        .with_columns(
            ((pl.col("close") - pl.col("open")) / pl.col("open"))
            .cast(pl.Float64)
            .alias("_intraday_return"),
            pl.col("volume").shift(2).over("symbol").alias("_volume_lag2"),
            pl.col("_bar_present").shift(1).over("symbol").alias("_bar_present_lag1"),
            pl.col("_bar_present").shift(2).over("symbol").alias("_bar_present_lag2"),
        )
        .with_columns(
            pl.when(
                (pl.col("_bar_present") == 1)
                & (pl.col("_bar_present_lag1") == 1)
                & (pl.col("_volume_lag2") > 0)
                & (pl.col("volume") > 0)
            )
            .then(pl.col("volume").log() - pl.col("_volume_lag2").log())
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_volume_change"),
            pl.when(pl.col("_bar_present") == 1)
            .then(pl.col("_intraday_return"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_intraday_return_valid"),
        )
    )
    if _has_non_finite(
        grid,
        ("_volume_change", "_intraday_return_valid"),
        non_null_only=True,
    ):
        raise ValueError("eleventh-batch feature arithmetic is non-finite")

    grid = grid.with_columns(
        pl.col("symbol").count().over("trade_date").cast(pl.UInt32).alias("_grid_symbols"),
        pl.col("_volume_change")
        .is_not_null()
        .cast(pl.UInt32)
        .sum()
        .over("trade_date")
        .cast(pl.UInt32)
        .alias("_volume_finite_values"),
        pl.col("_intraday_return_valid")
        .is_not_null()
        .cast(pl.UInt32)
        .sum()
        .over("trade_date")
        .cast(pl.UInt32)
        .alias("_return_finite_values"),
    )

    long_form = pl.concat(
        [
            grid.select(
                pl.col("trade_date").alias("signal_date"),
                pl.lit("volume_change", dtype=pl.String).alias("component"),
                "symbol",
                pl.col("_volume_change").alias("value"),
            ),
            grid.select(
                pl.col("trade_date").alias("signal_date"),
                pl.lit("intraday_return", dtype=pl.String).alias("component"),
                "symbol",
                pl.col("_intraday_return_valid").alias("value"),
            ),
        ],
        how="vertical",
    ).select(
        pl.col("signal_date").cast(pl.Date),
        pl.col("component").cast(pl.String),
        pl.col("symbol").cast(pl.String),
        pl.col("value").cast(pl.Float64),
    )
    ranked = rank_cross_sectional_components(long_form).with_columns(
        pl.col("normalized_rank")
        .is_not_null()
        .cast(pl.UInt32)
        .sum()
        .over("signal_date", "component")
        .cast(pl.UInt32)
        .alias("_ranked_values")
    )
    volume_rank = ranked.filter(pl.col("component") == "volume_change").select(
        pl.col("signal_date").alias("trade_date"),
        "symbol",
        pl.col("normalized_rank").alias("_u"),
        pl.col("_ranked_values").alias("_volume_ranked_values"),
    )
    return_rank = ranked.filter(pl.col("component") == "intraday_return").select(
        pl.col("signal_date").alias("trade_date"),
        "symbol",
        pl.col("normalized_rank").alias("_r"),
        pl.col("_ranked_values").alias("_return_ranked_values"),
    )
    grid = grid.join(volume_rank, on=["symbol", "trade_date"], how="left", validate="1:1").join(
        return_rank, on=["symbol", "trade_date"], how="left", validate="1:1"
    )
    pair = pl.col("_u").is_not_null() & pl.col("_r").is_not_null()
    grid = grid.with_columns(
        pair.cast(pl.Int64).rolling_sum(_CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW)
        .over("symbol")
        .alias("_pair_count"),
        (pl.col("_u") * pl.col("_r")).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_ur_sum"),
        pl.col("_u").rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_u_sum"),
        pl.col("_r").rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_r_sum"),
        (pl.col("_u") ** 2).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_u2_sum"),
        (pl.col("_r") ** 2).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_r2_sum"),
    ).with_columns(
        (
            pl.col("_u2_sum") - pl.col("_u_sum") ** 2 / _CORRELATION_WINDOW
        ).alias("_u_ss"),
        (
            pl.col("_r2_sum") - pl.col("_r_sum") ** 2 / _CORRELATION_WINDOW
        ).alias("_r_ss"),
        (
            pl.col("_ur_sum") - pl.col("_u_sum") * pl.col("_r_sum") / _CORRELATION_WINDOW
        ).alias("_cross_ss"),
    ).with_columns(
        pl.when(
            (pl.col("_pair_count") == _CORRELATION_WINDOW)
            & (pl.col("_u_ss") > 0.0)
            & (pl.col("_r_ss") > 0.0)
        )
        .then(-pl.col("_cross_ss") / (pl.col("_u_ss") * pl.col("_r_ss")).sqrt())
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_002")
    )
    result = keys.join(
        grid.select("symbol", "trade_date", "alpha101_002"),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    ).select(
        pl.col("symbol").cast(pl.String),
        pl.col("trade_date").cast(pl.Date),
        pl.col("alpha101_002").cast(pl.Float64),
    ).sort("symbol", "trade_date")
    if _has_non_finite(result, ("alpha101_002",), non_null_only=True):
        raise ValueError("eleventh-batch factors contain non-finite values")
    factors = result.with_columns(
        pl.when(pl.col("alpha101_002") == 0.0)
        .then(0.0)
        .otherwise(pl.col("alpha101_002"))
        .alias("alpha101_002")
    )
    return _EleventhBatchComputation(factors=factors, grid=grid)


def _positive_zero_expression(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column) == 0.0)
        .then(0.0)
        .otherwise(pl.col(column))
        .cast(pl.Float64)
    )


def _project_component_counts(grid: pl.DataFrame) -> pl.DataFrame:
    daily = grid.group_by("trade_date").agg(
        pl.col("_grid_symbols").first().cast(pl.UInt32),
        pl.col("_volume_finite_values").first().cast(pl.UInt32),
        pl.col("_return_finite_values").first().cast(pl.UInt32),
        pl.col("_volume_ranked_values").first().cast(pl.UInt32),
        pl.col("_return_ranked_values").first().cast(pl.UInt32),
    )
    result = pl.concat(
        [
            daily.select(
                "trade_date",
                pl.lit("volume_change", dtype=pl.String).alias("component"),
                pl.col("_grid_symbols").alias("grid_symbols"),
                pl.col("_volume_finite_values").alias("finite_values"),
                pl.col("_volume_ranked_values").alias("ranked_values"),
            ),
            daily.select(
                "trade_date",
                pl.lit("intraday_return", dtype=pl.String).alias("component"),
                pl.col("_grid_symbols").alias("grid_symbols"),
                pl.col("_return_finite_values").alias("finite_values"),
                pl.col("_return_ranked_values").alias("ranked_values"),
            ),
        ],
        how="vertical",
    ).select(
        pl.col("trade_date").cast(pl.Date),
        pl.col("component").cast(pl.String),
        pl.col("grid_symbols").cast(pl.UInt32),
        pl.col("finite_values").cast(pl.UInt32),
        pl.col("ranked_values").cast(pl.UInt32),
    )
    return result.sort("trade_date", "component")


def _primary_reason_expression() -> pl.Expr:
    return (
        pl.when(pl.col("_bar_present").is_null())
        .then(pl.lit("MISSING_CURRENT_BAR", dtype=pl.String))
        .when(pl.col("_session_index") < (_REQUIRED_SESSIONS - 1))
        .then(pl.lit("WARMUP_LT8_SESSIONS", dtype=pl.String))
        .when(pl.col("_pair_count") != _CORRELATION_WINDOW)
        .then(pl.lit("PAIR_INCOMPLETE", dtype=pl.String))
        .when((pl.col("_u_ss") <= 0.0) & (pl.col("_r_ss") <= 0.0))
        .then(pl.lit("BOTH_VARIANCES_NONPOSITIVE", dtype=pl.String))
        .when(pl.col("_u_ss") <= 0.0)
        .then(pl.lit("VOLUME_VARIANCE_NONPOSITIVE", dtype=pl.String))
        .when(pl.col("_r_ss") <= 0.0)
        .then(pl.lit("RETURN_VARIANCE_NONPOSITIVE", dtype=pl.String))
        .otherwise(pl.lit("VALID", dtype=pl.String))
        .alias("primary_reason")
    )


def _project_observations(grid: pl.DataFrame) -> pl.DataFrame:
    return (
        grid.with_columns(_primary_reason_expression())
        .select(
            pl.col("symbol").cast(pl.String),
            pl.col("trade_date").cast(pl.Date),
            pl.col("_bar_present").is_not_null().cast(pl.Boolean).alias("bar_present"),
            pl.col("_volume_change").cast(pl.Float64).alias("volume_change"),
            pl.col("_intraday_return_valid")
            .cast(pl.Float64)
            .alias("intraday_return"),
            pl.col("_u").cast(pl.Float64).alias("volume_rank"),
            pl.col("_r").cast(pl.Float64).alias("return_rank"),
            (pl.col("_session_index") >= 5).cast(pl.Boolean).alias("window_ready"),
            pl.col("_pair_count").cast(pl.Int64).alias("pair_count"),
            pl.col("_u_ss").cast(pl.Float64).alias("volume_ss"),
            pl.col("_r_ss").cast(pl.Float64).alias("return_ss"),
            _positive_zero_expression("alpha101_002").alias("alpha101_002"),
            pl.col("primary_reason").cast(pl.String),
            pl.col("_session_index").cast(pl.UInt32).alias("session_index"),
            pl.col("_bar_present").is_null().cast(pl.Boolean).alias("current_bar_missing"),
            pl.when(pl.col("_session_index") < 1)
            .then(pl.lit(None, dtype=pl.Boolean))
            .otherwise(pl.col("_bar_present_lag1").is_null())
            .cast(pl.Boolean)
            .alias("lag1_bar_missing"),
            pl.when(pl.col("_session_index") < 2)
            .then(pl.lit(None, dtype=pl.Boolean))
            .otherwise(pl.col("_bar_present_lag2").is_null())
            .cast(pl.Boolean)
            .alias("lag2_bar_missing"),
            pl.when(pl.col("_bar_present").is_not_null())
            .then(pl.col("volume") == 0)
            .otherwise(pl.lit(None, dtype=pl.Boolean))
            .cast(pl.Boolean)
            .alias("current_volume_zero"),
            pl.when(
                (pl.col("_session_index") >= 2)
                & pl.col("_bar_present_lag2").is_not_null()
            )
            .then(pl.col("_volume_lag2") == 0)
            .otherwise(pl.lit(None, dtype=pl.Boolean))
            .cast(pl.Boolean)
            .alias("lag2_volume_zero"),
            (pl.col("_volume_finite_values") < 2)
            .cast(pl.Boolean)
            .alias("volume_rank_members_lt2"),
            (pl.col("_return_finite_values") < 2)
            .cast(pl.Boolean)
            .alias("return_rank_members_lt2"),
        )
        .sort("symbol", "trade_date")
    )


def _validate_trace(
    *,
    factors: pl.DataFrame,
    grid: pl.DataFrame,
    component_counts: pl.DataFrame,
    observations: pl.DataFrame,
) -> None:
    if (
        factors.columns != _TRACE_FACTOR_COLUMNS
        or factors.schema
        != {"symbol": pl.String, "trade_date": pl.Date, "alpha101_002": pl.Float64}
        or component_counts.columns != _TRACE_COMPONENT_COUNT_COLUMNS
        or component_counts.schema
        != {
            "trade_date": pl.Date,
            "component": pl.String,
            "grid_symbols": pl.UInt32,
            "finite_values": pl.UInt32,
            "ranked_values": pl.UInt32,
        }
        or observations.columns != _TRACE_OBSERVATION_COLUMNS
        or observations.schema
        != {
            "symbol": pl.String,
            "trade_date": pl.Date,
            "bar_present": pl.Boolean,
            "volume_change": pl.Float64,
            "intraday_return": pl.Float64,
            "volume_rank": pl.Float64,
            "return_rank": pl.Float64,
            "window_ready": pl.Boolean,
            "pair_count": pl.Int64,
            "volume_ss": pl.Float64,
            "return_ss": pl.Float64,
            "alpha101_002": pl.Float64,
            "primary_reason": pl.String,
            "session_index": pl.UInt32,
            "current_bar_missing": pl.Boolean,
            "lag1_bar_missing": pl.Boolean,
            "lag2_bar_missing": pl.Boolean,
            "current_volume_zero": pl.Boolean,
            "lag2_volume_zero": pl.Boolean,
            "volume_rank_members_lt2": pl.Boolean,
            "return_rank_members_lt2": pl.Boolean,
        }
    ):
        _raise_trace_error()
    if (
        factors.select(pl.struct(["symbol", "trade_date"]).is_duplicated().any()).item()
        or component_counts.select(
            pl.struct(["trade_date", "component"]).is_duplicated().any()
        ).item()
        or observations.select(pl.struct(["symbol", "trade_date"]).is_duplicated().any()).item()
        or not factors.equals(factors.sort("symbol", "trade_date"))
        or not component_counts.equals(component_counts.sort("trade_date", "component"))
        or not observations.equals(observations.sort("symbol", "trade_date"))
    ):
        _raise_trace_error()

    expected_observation_keys = grid.select("symbol", "trade_date").sort(
        "symbol", "trade_date"
    )
    if (
        observations.height != grid.height
        or not observations.select("symbol", "trade_date").equals(expected_observation_keys)
    ):
        _raise_trace_error()

    expected_dates = grid.select("trade_date").unique().sort("trade_date")
    component_frame = pl.DataFrame(
        {"component": list(_TRACE_COMPONENTS)},
        schema={"component": pl.String},
    )
    expected_component_keys = expected_dates.join(component_frame, how="cross").sort(
        "trade_date", "component"
    )
    if (
        component_counts.height != expected_component_keys.height
        or not component_counts.select("trade_date", "component").equals(expected_component_keys)
    ):
        _raise_trace_error()

    if _has_non_finite(
        grid,
        (
            "_volume_change",
            "_intraday_return_valid",
            "_u",
            "_r",
            "_u_ss",
            "_r_ss",
            "_cross_ss",
            "alpha101_002",
        ),
        non_null_only=True,
    ):
        _raise_trace_error()
    if _has_any(
        grid,
        pl.col("_bar_present").is_null()
        & (
            pl.col("_u_ss").is_not_null()
            | pl.col("_r_ss").is_not_null()
            | pl.col("_cross_ss").is_not_null()
        ),
    ):
        _raise_trace_error()
    if _has_any(
        grid,
        (pl.col("_pair_count") == _CORRELATION_WINDOW)
        & (
            pl.col("_u_ss").is_null()
            | pl.col("_r_ss").is_null()
            | pl.col("_cross_ss").is_null()
        ),
    ):
        _raise_trace_error()
    if _has_any(
        grid,
        (pl.col("_session_index") < 5) != pl.col("_pair_count").is_null(),
    ) or _has_any(
        grid,
        (pl.col("_session_index") >= 5)
        & (
            pl.col("_pair_count").is_null()
            | (pl.col("_pair_count") < 0)
            | (pl.col("_pair_count") > _CORRELATION_WINDOW)
        ),
    ):
        _raise_trace_error()

    expected_grid_symbols = grid.group_by("trade_date").agg(
        pl.col("_grid_symbols").first().alias("grid_symbols"),
    ).sort("trade_date")
    for component in _TRACE_COMPONENTS:
        actual = component_counts.filter(pl.col("component") == component).select(
            "trade_date", "grid_symbols"
        )
        if not actual.equals(expected_grid_symbols):
            _raise_trace_error()

    expected_raw = grid.select(
        pl.col("symbol").cast(pl.String),
        pl.col("trade_date").cast(pl.Date),
        pl.col("_bar_present").is_not_null().cast(pl.Boolean).alias("bar_present"),
        pl.col("_volume_change").cast(pl.Float64).alias("volume_change"),
        pl.col("_intraday_return_valid")
        .cast(pl.Float64)
        .alias("intraday_return"),
        pl.col("_u").cast(pl.Float64).alias("volume_rank"),
        pl.col("_r").cast(pl.Float64).alias("return_rank"),
        pl.col("_pair_count").cast(pl.Int64).alias("pair_count"),
        pl.col("_u_ss").cast(pl.Float64).alias("volume_ss"),
        pl.col("_r_ss").cast(pl.Float64).alias("return_ss"),
    ).sort("symbol", "trade_date")
    actual_raw = observations.select(
        "symbol",
        "trade_date",
        "bar_present",
        "volume_change",
        "intraday_return",
        "volume_rank",
        "return_rank",
        "pair_count",
        "volume_ss",
        "return_ss",
    )
    if not actual_raw.equals(expected_raw):
        _raise_trace_error()

    if not observations.filter(pl.col("bar_present")).select(
        "symbol", "trade_date", "alpha101_002"
    ).equals(factors):
        _raise_trace_error()
    if observations.filter(
        ~pl.col("bar_present") & pl.col("alpha101_002").is_not_null()
    ).height:
        _raise_trace_error()

    expected_flags = grid.select(
        pl.col("_session_index").cast(pl.UInt32).alias("session_index"),
        pl.col("_bar_present").is_null().cast(pl.Boolean).alias("current_bar_missing"),
        pl.when(pl.col("_session_index") < 1)
        .then(pl.lit(None, dtype=pl.Boolean))
        .otherwise(pl.col("_bar_present_lag1").is_null())
        .cast(pl.Boolean)
        .alias("lag1_bar_missing"),
        pl.when(pl.col("_session_index") < 2)
        .then(pl.lit(None, dtype=pl.Boolean))
        .otherwise(pl.col("_bar_present_lag2").is_null())
        .cast(pl.Boolean)
        .alias("lag2_bar_missing"),
        pl.when(pl.col("_bar_present").is_not_null())
        .then(pl.col("volume") == 0)
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .cast(pl.Boolean)
        .alias("current_volume_zero"),
        pl.when(
            (pl.col("_session_index") >= 2) & pl.col("_bar_present_lag2").is_not_null()
        )
        .then(pl.col("_volume_lag2") == 0)
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .cast(pl.Boolean)
        .alias("lag2_volume_zero"),
        (pl.col("_volume_finite_values") < 2)
        .cast(pl.Boolean)
        .alias("volume_rank_members_lt2"),
        (pl.col("_return_finite_values") < 2)
        .cast(pl.Boolean)
        .alias("return_rank_members_lt2"),
    )
    actual_flags = observations.select(
        "session_index",
        "current_bar_missing",
        "lag1_bar_missing",
        "lag2_bar_missing",
        "current_volume_zero",
        "lag2_volume_zero",
        "volume_rank_members_lt2",
        "return_rank_members_lt2",
    )
    if not actual_flags.equals(expected_flags):
        _raise_trace_error()

    if _has_any(
        observations,
        pl.col("volume_rank").is_null()
        != (pl.col("volume_change").is_null() | pl.col("volume_rank_members_lt2")),
    ) or _has_any(
        observations,
        pl.col("return_rank").is_null()
        != (pl.col("intraday_return").is_null() | pl.col("return_rank_members_lt2")),
    ):
        _raise_trace_error()

    expected_reason = grid.select(_primary_reason_expression()).get_column("primary_reason")
    if not observations.get_column("primary_reason").equals(expected_reason):
        _raise_trace_error()
    valid = pl.col("primary_reason") == "VALID"
    final_factor_valid = (
        pl.col("bar_present")
        & pl.col("alpha101_002").is_not_null()
        & pl.col("alpha101_002").is_finite()
    )
    if _has_any(observations, valid != final_factor_valid):
        _raise_trace_error()


def _has_any(frame: pl.DataFrame, expression: pl.Expr) -> bool:
    return bool(frame.select(expression.fill_null(False).any()).item())


def _raise_trace_error() -> None:
    raise ValueError("eleventh-batch trace contains unexplained intermediate state")


def _has_non_finite(frame: pl.DataFrame, columns: tuple[str, ...], *, non_null_only: bool = False) -> bool:
    expressions: list[pl.Expr] = []
    for column in columns:
        expression = pl.col(column).is_finite()
        expressions.append(pl.col(column).is_not_null() & ~expression if non_null_only else ~expression)
    return bool(frame.select(pl.any_horizontal(*expressions).fill_null(False).any()).item())


__all__ = [
    "ELEVENTH_BATCH_FACTOR_NAMES",
    "ELEVENTH_BATCH_FACTOR_SPECS",
    "compute_eleventh_batch_daily_factors",
    "compute_eleventh_batch_daily_factors_with_trace",
]
