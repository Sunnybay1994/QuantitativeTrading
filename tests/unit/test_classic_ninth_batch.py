from __future__ import annotations

import datetime as dt
import math
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.factors import classic_ninth_batch as ninth_batch
from quant.factors.classic_ninth_batch import (
    NINTH_BATCH_FACTOR_NAMES,
    NINTH_BATCH_FACTOR_SPECS,
    compute_ninth_batch_daily_factors,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    PROJECT_ROOT / "configs/research/m2_classic_daily_factors_ninth_batch.toml"
)


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 2)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    raw_gaps: dict[str, list[float | None]],
    volumes: dict[str, list[float]] | None = None,
    adj_factors: dict[str, list[float]] | None = None,
    missing: set[tuple[str, dt.date]] | None = None,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    omitted = missing or set()
    for symbol, gaps in raw_gaps.items():
        assert len(gaps) == len(sessions)
        symbol_volumes = (
            [1_000.0 + 10.0 * index for index in range(len(sessions))]
            if volumes is None
            else volumes[symbol]
        )
        symbol_factors = (
            [1.0] * len(sessions)
            if adj_factors is None
            else adj_factors[symbol]
        )
        assert len(symbol_volumes) == len(sessions)
        assert len(symbol_factors) == len(sessions)
        for trade_date, gap, volume, factor in zip(
            sessions,
            gaps,
            symbol_volumes,
            symbol_factors,
            strict=True,
        ):
            if (symbol, trade_date) in omitted:
                continue
            close = 10.0
            amount = 0.0 if gap is None else (close + gap) * volume
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "adj_factor": factor,
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _factor_for(
    result: pl.DataFrame,
    *,
    symbol: str,
    trade_date: dt.date,
) -> float | None:
    return (
        result.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("trade_date") == trade_date)
        )
        .get_column("alpha101_011")
        .item()
    )


def _three_symbol_bars(
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    return _bars(
        sessions=sessions,
        raw_gaps={
            "600001.SH": [1.0] * len(sessions),
            "600002.SH": [2.0] * len(sessions),
            "600003.SH": [3.0] * len(sessions),
        },
        volumes={
            "600001.SH": [100.0] * len(sessions),
            "600002.SH": [100.0] * (len(sessions) - 1) + [110.0],
            "600003.SH": [100.0] * (len(sessions) - 1) + [120.0],
        },
    )


def _is_exact_int(value: object) -> bool:
    return type(value) is int


def test_public_identity_exact_output_and_formula_boundaries() -> None:
    assert NINTH_BATCH_FACTOR_NAMES == ("alpha101_011",)
    assert tuple(spec.name for spec in NINTH_BATCH_FACTOR_SPECS) == (
        "alpha101_011",
    )
    assert "adjusted VWAP-close gap" in NINTH_BATCH_FACTOR_SPECS[0].source

    sessions = _sessions(4)
    result = compute_ninth_batch_daily_factors(
        _three_symbol_bars(sessions),
        sessions=sessions,
    )

    assert result.columns == ["symbol", "trade_date", "alpha101_011"]
    assert result.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "alpha101_011": pl.Float64,
    }
    final = result.filter(pl.col("trade_date") == sessions[-1])
    assert final.get_column("alpha101_011").to_list() == pytest.approx(
        [0.0, 0.5, 2.0]
    )
    zero = final.head(1).get_column("alpha101_011").item()
    assert math.copysign(1.0, zero) == 1.0
    assert result.filter(pl.col("trade_date") != sessions[-1]).get_column(
        "alpha101_011"
    ).null_count() == 9


def test_amount_div_volume_and_common_adjustment_scale_the_gap() -> None:
    sessions = _sessions(4)
    raw = _three_symbol_bars(sessions)
    adjusted = raw.with_columns(
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
        .then(4.0)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    raw_result = compute_ninth_batch_daily_factors(raw, sessions=sessions)
    adjusted_result = compute_ninth_batch_daily_factors(
        adjusted,
        sessions=sessions,
    )

    assert _factor_for(
        raw_result,
        symbol="600002.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(0.5)
    assert _factor_for(
        adjusted_result,
        symbol="600002.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(0.25)
    assert _factor_for(
        adjusted_result,
        symbol="600003.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(1.5)


def test_component_rank_uses_ascending_average_ties_and_own_valid_set() -> None:
    day = _sessions(1)[0]
    frame = pl.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "trade_date": [day] * 4,
            "_first": [1.0, 2.0, 2.0, None],
            "_second": [None, 10.0, 20.0, 30.0],
        },
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "_first": pl.Float64,
            "_second": pl.Float64,
        },
    )
    ranked = ninth_batch._with_component_rank(
        frame,
        value_column="_first",
        rank_column="_first_rank",
    )
    ranked = ninth_batch._with_component_rank(
        ranked,
        value_column="_second",
        rank_column="_second_rank",
    ).sort("symbol")

    assert ranked.get_column("_first_rank").to_list() == [0.0, 0.75, 0.75, None]
    assert ranked.get_column("_second_rank").to_list() == [None, 0.0, 0.5, 1.0]

    one = ninth_batch._with_component_rank(
        frame.with_columns(
            pl.when(pl.col("symbol") == "A")
            .then(pl.col("_first"))
            .otherwise(None)
            .alias("_first")
        ),
        value_column="_first",
        rank_column="_only_rank",
    )
    assert one.get_column("_only_rank").null_count() == one.height


def test_gap_extrema_need_three_and_volume_lag_needs_four_sessions() -> None:
    short_sessions = _sessions(3)
    short = compute_ninth_batch_daily_factors(
        _three_symbol_bars(short_sessions),
        sessions=short_sessions,
    )
    assert short.get_column("alpha101_011").null_count() == short.height

    sessions = _sessions(5)
    complete = compute_ninth_batch_daily_factors(
        _three_symbol_bars(sessions),
        sessions=sessions,
    )
    for symbol in ("600001.SH", "600002.SH", "600003.SH"):
        values = complete.filter(pl.col("symbol") == symbol).get_column(
            "alpha101_011"
        )
        assert values.head(3).null_count() == 3
        assert values.tail(2).null_count() == 0


def test_internal_and_edge_gaps_never_bridge_sessions() -> None:
    sessions = _sessions(5)
    bars = _three_symbol_bars(sessions)

    internal = compute_ninth_batch_daily_factors(
        bars.filter(
            ~(
                (pl.col("symbol") == "600001.SH")
                & (pl.col("trade_date") == sessions[2])
            )
        ),
        sessions=sessions,
    )
    assert _factor_for(
        internal,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) is None
    assert _factor_for(
        internal,
        symbol="600002.SH",
        trade_date=sessions[-1],
    ) is not None

    missing_first = compute_ninth_batch_daily_factors(
        bars.filter(
            ~(
                (pl.col("symbol") == "600001.SH")
                & (pl.col("trade_date") == sessions[0])
            )
        ),
        sessions=sessions,
    )
    assert _factor_for(
        missing_first,
        symbol="600001.SH",
        trade_date=sessions[3],
    ) is None
    assert _factor_for(
        missing_first,
        symbol="600001.SH",
        trade_date=sessions[4],
    ) is not None

    missing_last_bars = bars.filter(
        ~(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
    )
    missing_last = compute_ninth_batch_daily_factors(
        missing_last_bars,
        sessions=sessions,
    )
    assert missing_last.height == missing_last_bars.height
    assert not missing_last.filter(
        (pl.col("symbol") == "600001.SH")
        & (pl.col("trade_date") == sessions[-1])
    ).height


def test_zero_amount_and_volume_are_local_and_zero_lag_endpoint_is_valid() -> None:
    sessions = _sessions(4)
    bars = _three_symbol_bars(sessions)
    zero_current_amount = bars.with_columns(
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
        .then(0.0)
        .otherwise(pl.col("amount"))
        .alias("amount")
    )
    amount_result = compute_ninth_batch_daily_factors(
        zero_current_amount,
        sessions=sessions,
    )
    assert _factor_for(
        amount_result,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) is None

    zero_current_volume = bars.with_columns(
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
        .then(0.0)
        .otherwise(pl.col("volume"))
        .alias("volume"),
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
        .then(0.0)
        .otherwise(pl.col("amount"))
        .alias("amount"),
    )
    volume_result = compute_ninth_batch_daily_factors(
        zero_current_volume,
        sessions=sessions,
    )
    assert _factor_for(
        volume_result,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) is None

    zero_lag_endpoint = bars.with_columns(
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[0])
        )
        .then(0.0)
        .otherwise(pl.col("volume"))
        .alias("volume"),
        pl.when(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[0])
        )
        .then(0.0)
        .otherwise(pl.col("amount"))
        .alias("amount"),
    )
    endpoint_result = compute_ninth_batch_daily_factors(
        zero_lag_endpoint,
        sessions=sessions,
    )
    assert _factor_for(
        endpoint_result,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) is not None


def test_volume_component_is_raw_lag_three_not_one_day_ratio_or_log() -> None:
    sessions = _sessions(4)
    bars = _bars(
        sessions=sessions,
        raw_gaps={
            "600001.SH": [1.0] * 4,
            "600002.SH": [2.0] * 4,
            "600003.SH": [3.0] * 4,
        },
        volumes={
            "600001.SH": [100.0, 1000.0, 1000.0, 200.0],
            "600002.SH": [10.0, 1.0, 1.0, 20.0],
            "600003.SH": [1000.0, 10.0, 10.0, 1050.0],
        },
    )
    result = compute_ninth_batch_daily_factors(bars, sessions=sessions)
    final = result.filter(pl.col("trade_date") == sessions[-1])

    assert final.get_column("alpha101_011").to_list() == pytest.approx(
        [0.0, 0.0, 1.0]
    )


def test_volume_delta_does_not_apply_adjustment_factor() -> None:
    sessions = _sessions(4)
    volumes = {
        "600001.SH": [100.0, 100.0, 100.0, 110.0],
        "600002.SH": [100.0, 100.0, 100.0, 120.0],
        "600003.SH": [100.0, 100.0, 100.0, 130.0],
    }
    adjusted = _bars(
        sessions=sessions,
        raw_gaps={
            "600001.SH": [0.02] * 4,
            "600002.SH": [1.0] * 4,
            "600003.SH": [3.0] * 4,
        },
        volumes=volumes,
        adj_factors={
            "600001.SH": [100.0] * 4,
            "600002.SH": [1.0] * 4,
            "600003.SH": [1.0] * 4,
        },
    )
    baseline = _bars(
        sessions=sessions,
        raw_gaps={
            "600001.SH": [2.0] * 4,
            "600002.SH": [1.0] * 4,
            "600003.SH": [3.0] * 4,
        },
        volumes=volumes,
    )
    adjusted_result = compute_ninth_batch_daily_factors(
        adjusted,
        sessions=sessions,
    )
    baseline_result = compute_ninth_batch_daily_factors(
        baseline,
        sessions=sessions,
    )

    assert _factor_for(
        adjusted_result,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(0.0)
    assert adjusted_result.equals(baseline_result, null_equal=True)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("close", True),
        ("volume", True),
        ("amount", True),
        ("adj_factor", True),
        ("amount", float("nan")),
        ("volume", float("inf")),
        ("close", float("-inf")),
    ),
    ids=(
        "bool-close",
        "bool-volume",
        "bool-amount",
        "bool-adjustment",
        "nan-amount",
        "inf-volume",
        "negative-inf-close",
    ),
)
def test_boolean_nan_and_infinity_sources_fail_closed(
    column: str,
    value: object,
) -> None:
    sessions = _sessions(4)
    bars = _three_symbol_bars(sessions).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError):
        compute_ninth_batch_daily_factors(bars, sessions=sessions)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("close", 0.0),
        ("adj_factor", 0.0),
        ("volume", -1.0),
        ("amount", -1.0),
    ),
)
def test_invalid_schema_values_fail_closed(column: str, value: float) -> None:
    sessions = _sessions(4)
    bars = _three_symbol_bars(sessions).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError, match="fail Bar1dSchema validation"):
        compute_ninth_batch_daily_factors(bars, sessions=sessions)


def test_vwap_and_adjusted_gap_overflow_fail_closed() -> None:
    sessions = _sessions(4)
    bars = _three_symbol_bars(sessions)
    vwap_overflow = bars.with_columns(
        pl.when(pl.col("symbol") == "600001.SH")
        .then(1.0e-308)
        .otherwise(pl.col("volume"))
        .alias("volume"),
        pl.when(pl.col("symbol") == "600001.SH")
        .then(1.0e308)
        .otherwise(pl.col("amount"))
        .alias("amount"),
    )
    with pytest.raises(ValueError, match="VWAP-gap arithmetic is non-finite"):
        compute_ninth_batch_daily_factors(vwap_overflow, sessions=sessions)

    adjusted_overflow = bars.with_columns(
        pl.when(pl.col("symbol") == "600001.SH")
        .then(1.0e308)
        .otherwise(pl.col("adj_factor"))
        .alias("adj_factor")
    )
    with pytest.raises(ValueError, match="VWAP-gap arithmetic is non-finite"):
        compute_ninth_batch_daily_factors(adjusted_overflow, sessions=sessions)


def test_duplicate_calendar_escape_and_invalid_sessions_fail_closed() -> None:
    sessions = _sessions(4)
    bars = _three_symbol_bars(sessions)
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_ninth_batch_daily_factors(duplicate, sessions=sessions)
    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_ninth_batch_daily_factors(bars, sessions=sessions[:-1])
    with pytest.raises(ValueError, match="invalid ninth-batch factor request"):
        compute_ninth_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError, match="invalid ninth-batch factor request"):
        compute_ninth_batch_daily_factors(
            bars,
            sessions=(sessions[0], sessions[0]),
        )


def test_row_order_is_canonical_input_only_and_values_finite() -> None:
    sessions = _sessions(5)
    bars = _three_symbol_bars(sessions).filter(
        ~(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[1])
        )
    )
    result = compute_ninth_batch_daily_factors(bars, sessions=sessions)
    reversed_result = compute_ninth_batch_daily_factors(
        bars.reverse(),
        sessions=sessions,
    )

    assert result.equals(reversed_result, null_equal=True)
    assert result.height == bars.height
    assert result.select("symbol", "trade_date").rows() == (
        bars.select("symbol", "trade_date")
        .sort("symbol", "trade_date")
        .rows()
    )
    assert result.select("symbol", "trade_date").is_sorted(
        "symbol", "trade_date"
    )
    values = result.get_column("alpha101_011").drop_nulls()
    assert values.is_finite().all()
    assert values.min() >= 0.0
    assert values.max() <= 2.0


def test_ninth_batch_config_identity_values_types_and_order_are_exact() -> None:
    with CONFIG_PATH.open("rb") as stream:
        config = tomllib.load(stream)

    assert list(config) == [
        "research",
        "data",
        "universe",
        "factors",
        "alpha101_ninth_batch",
        "coverage",
        "portfolio",
        "admission",
        "walk_forward",
    ]
    assert list(config["research"]) == [
        "hypothesis_id",
        "hypothesis",
        "strategy_name",
        "strategy_version",
        "random_seed",
    ]
    assert config["research"]["hypothesis_id"] == (
        "m2-alpha101-011-vwap-volume-extremes-v1"
    )
    assert config["research"]["strategy_name"] == (
        "classic_alpha101_011_vwap_volume_extremes_top50"
    )
    assert list(config["data"]) == [
        "snapshot_id",
        "warmup_start",
        "research_start",
        "research_end",
    ]
    assert list(config["universe"]) == [
        "freeze_start",
        "freeze_end",
        "top_n",
        "minimum_observations",
        "minimum_average_amount",
    ]
    assert list(config["factors"]) == [
        "catalog",
        "names",
        "redundancy_reference_names",
        "horizons",
        "minimum_history_rows",
        "minimum_daily_symbols",
        "groups",
        "maximum_median_absolute_rank_correlation",
    ]
    assert config["factors"]["catalog"] == (
        "alpha101_vwap_volume_extremes_ninth_batch_v1"
    )
    assert config["factors"]["names"] == ["alpha101_011"]
    assert config["factors"]["horizons"] == [1, 5, 20]

    section = config["alpha101_ninth_batch"]
    assert list(section) == [
        "schema_version",
        "hypothesis_id",
        "factors",
        "vwap_basis",
        "gap_basis",
        "gap_extreme_window_sessions",
        "volume_basis",
        "volume_delta_lag_sessions",
        "required_bar_sessions",
        "cross_section_rank",
        "cross_section_minimum_symbols",
        "expected_direction",
        "direction_policy",
        "signal_timing",
        "execution_timing",
        "attempt_ordinal",
        "trial_budget",
        "trial_delta",
        "economic_execution",
    ]
    assert section == {
        "schema_version": "m2-alpha101-ninth-batch-v1",
        "hypothesis_id": "m2-alpha101-011-vwap-volume-extremes-v1",
        "factors": ["alpha101_011"],
        "vwap_basis": "amount_cny_divided_by_volume_shares",
        "gap_basis": "adjusted_vwap_minus_adjusted_close",
        "gap_extreme_window_sessions": 3,
        "volume_basis": "raw_volume_shares",
        "volume_delta_lag_sessions": 3,
        "required_bar_sessions": 4,
        "cross_section_rank": (
            "componentwise_average_normalized_zero_one_ascending"
        ),
        "cross_section_minimum_symbols": 2,
        "expected_direction": 1,
        "direction_policy": "pre_registered_fixed_positive",
        "signal_timing": "close",
        "execution_timing": "next_session_open",
        "attempt_ordinal": 1,
        "trial_budget": 1,
        "trial_delta": 0,
        "economic_execution": (
            "BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK"
        ),
    }
    exact_int_fields = (
        "gap_extreme_window_sessions",
        "volume_delta_lag_sessions",
        "required_bar_sessions",
        "cross_section_minimum_symbols",
        "expected_direction",
        "attempt_ordinal",
        "trial_budget",
        "trial_delta",
    )
    assert all(_is_exact_int(section[field]) for field in exact_int_fields)
    assert not _is_exact_int(True)
    assert section["trial_delta"] == 0
    assert section["economic_execution"].startswith("BLOCKED_")
    assert list(config["coverage"]) == [
        "minimum_rebalance_symbols",
        "minimum_median_coverage",
    ]
    assert list(config["portfolio"]) == [
        "selection_horizon_sessions",
        "rebalance_every_sessions",
        "top_k",
        "initial_cash",
        "cost_multipliers",
        "cost_config_relative_path",
        "cost_schedule_semantic_sha256",
    ]
    assert list(config["admission"]) == [
        "minimum_mean_test_rank_ic",
        "minimum_positive_test_folds",
        "require_direction_consistency",
        "require_positive_2x_cost_return",
    ]
    assert len(config["walk_forward"]["folds"]) == 3
    assert all(
        list(fold) == [
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        ]
        for fold in config["walk_forward"]["folds"]
    )
