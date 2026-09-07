from __future__ import annotations

import datetime as dt
import itertools
import math
from collections.abc import Callable
from typing import cast

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import quant.factors.cross_sectional_rank as rank_module
from quant.factors.cross_sectional_rank import rank_cross_sectional_components


def _frame(rows: list[tuple[dt.date, str | None, str | None, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "signal_date": pl.Date,
            "component": pl.String,
            "symbol": pl.String,
            "value": pl.Float64,
        },
        orient="row",
    )


def _assert_error(frame: object, code: str, error: type[Exception]) -> None:
    with pytest.raises(error) as captured:
        rank_cross_sectional_components(cast(pl.DataFrame, frame))
    assert captured.value.args == (code,)
    assert str(captured.value) == code
    assert "\\" not in str(captured.value) and "/" not in str(captured.value)


def test_two_values_and_partial_ties_use_average_normalized_rank() -> None:
    day = dt.date(2026, 8, 31)
    result = rank_cross_sectional_components(
        _frame(
            [
                (day, "x", "D", 30.0),
                (day, "x", "A", 10.0),
                (day, "x", "C", 20.0),
                (day, "x", "B", 20.0),
            ]
        )
    )
    assert result.get_column("normalized_rank").to_list() == pytest.approx(
        [0.0, 0.5, 0.5, 1.0]
    )

    two = rank_cross_sectional_components(
        _frame([(day, "two", "B", 2.0), (day, "two", "A", 1.0)])
    )
    assert two.get_column("normalized_rank").to_list() == [0.0, 1.0]


def test_equal_null_and_small_groups_have_frozen_null_semantics() -> None:
    day = dt.date(2026, 8, 31)
    result = rank_cross_sectional_components(
        _frame(
            [
                (day, "equal", "A", 4.0),
                (day, "equal", "B", 4.0),
                (day, "equal", "C", 4.0),
                (day, "none", "A", None),
                (day, "one", "A", 7.0),
                (day, "one", "B", None),
            ]
        )
    )
    assert result.filter(pl.col("component") == "equal").get_column(
        "normalized_rank"
    ).to_list() == [0.5, 0.5, 0.5]
    assert result.filter(pl.col("component") == "none").get_column(
        "normalized_rank"
    ).to_list() == [None]
    assert result.filter(pl.col("component") == "one").get_column(
        "normalized_rank"
    ).to_list() == [None, None]


def test_components_use_independent_valid_sets_without_intersection() -> None:
    day = dt.date(2026, 8, 31)
    result = rank_cross_sectional_components(
        _frame(
            [
                (day, "left", "A", 1.0),
                (day, "left", "B", 2.0),
                (day, "left", "C", 3.0),
                (day, "right", "A", None),
                (day, "right", "B", 10.0),
                (day, "right", "C", 20.0),
            ]
        )
    )
    assert result.filter(pl.col("component") == "left").get_column(
        "normalized_rank"
    ).to_list() == [0.0, 0.5, 1.0]
    assert result.filter(pl.col("component") == "right").get_column(
        "normalized_rank"
    ).to_list() == [None, 0.0, 1.0]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_value_rejects_the_whole_call(bad: float) -> None:
    day = dt.date(2026, 8, 31)
    _assert_error(
        _frame([(day, "good", "A", 1.0), (day, "bad", "B", bad)]),
        "CROSS_SECTIONAL_RANK_NON_FINITE_VALUE",
        ValueError,
    )


def test_type_schema_key_and_duplicate_failures_are_exact() -> None:
    day = dt.date(2026, 8, 31)
    valid = _frame([(day, "x", "A", 1.0)])
    _assert_error([], "CROSS_SECTIONAL_RANK_TYPE_ERROR", TypeError)
    _assert_error(pl.DataFrame(), "CROSS_SECTIONAL_RANK_SCHEMA_ERROR", ValueError)
    _assert_error(
        valid.select("component", "signal_date", "symbol", "value"),
        "CROSS_SECTIONAL_RANK_SCHEMA_ERROR",
        ValueError,
    )
    _assert_error(valid.drop("value"), "CROSS_SECTIONAL_RANK_SCHEMA_ERROR", ValueError)
    _assert_error(
        valid.with_columns(pl.lit(1).alias("extra")),
        "CROSS_SECTIONAL_RANK_SCHEMA_ERROR",
        ValueError,
    )
    _assert_error(
        valid.with_columns(pl.col("value").cast(pl.Float32)),
        "CROSS_SECTIONAL_RANK_SCHEMA_ERROR",
        ValueError,
    )
    _assert_error(
        valid.with_columns(pl.lit(True).alias("value")),
        "CROSS_SECTIONAL_RANK_SCHEMA_ERROR",
        ValueError,
    )
    _assert_error(
        _frame([(day, "x", None, 1.0)]),
        "CROSS_SECTIONAL_RANK_KEY_NULL",
        ValueError,
    )
    _assert_error(
        pl.concat([valid, valid]),
        "CROSS_SECTIONAL_RANK_DUPLICATE_KEY",
        ValueError,
    )


@pytest.mark.parametrize(
    ("builder", "code"),
    [
        (
            lambda day: pl.DataFrame(
                {
                    "component": ["x", "x"],
                    "signal_date": [day, day],
                    "symbol": [None, None],
                    "value": [math.inf, math.inf],
                },
                schema_overrides={"signal_date": pl.Date, "value": pl.Float64},
            ),
            "CROSS_SECTIONAL_RANK_SCHEMA_ERROR",
        ),
        (
            lambda day: _frame(
                [(day, "x", None, math.inf), (day, "x", None, math.inf)]
            ),
            "CROSS_SECTIONAL_RANK_KEY_NULL",
        ),
        (
            lambda day: _frame(
                [(day, "x", "A", math.inf), (day, "x", "A", math.inf)]
            ),
            "CROSS_SECTIONAL_RANK_DUPLICATE_KEY",
        ),
    ],
)
def test_compound_invalid_precedence_is_permutation_stable(
    builder: Callable[[dt.date], pl.DataFrame], code: str
) -> None:
    day = dt.date(2026, 8, 31)
    frame = builder(day)
    for permutation in itertools.permutations(range(frame.height)):
        _assert_error(frame[list(permutation), :], code, ValueError)


def test_compute_and_output_failures_use_the_internal_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = dt.date(2026, 8, 31)
    frame = _frame([(day, "x", "A", 1.0), (day, "x", "B", 2.0)])

    def fail_compute(_: pl.DataFrame) -> pl.DataFrame:
        raise ValueError("uncontrolled library detail")

    monkeypatch.setattr(rank_module, "_compute_rank", fail_compute)
    _assert_error(
        frame,
        "CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT",
        RuntimeError,
    )


def test_multiple_dates_components_and_input_permutations_are_canonical() -> None:
    first = dt.date(2026, 8, 30)
    second = dt.date(2026, 8, 31)
    frame = _frame(
        [
            (second, "b", "Z", 3.0),
            (first, "a", "B", 2.0),
            (second, "a", "A", 5.0),
            (first, "a", "A", 1.0),
            (second, "a", "B", 5.0),
            (second, "b", "A", 1.0),
        ]
    )
    expected = rank_cross_sectional_components(frame)
    actual = rank_cross_sectional_components(frame.reverse())
    assert_frame_equal(actual, expected, check_row_order=True, check_column_order=True)
    assert actual.columns == [
        "signal_date",
        "component",
        "symbol",
        "normalized_rank",
    ]
    assert actual.dtypes == [pl.Date, pl.String, pl.String, pl.Float64]
    assert actual.select("signal_date", "component", "symbol").equals(
        frame.select("signal_date", "component", "symbol").sort(
            "signal_date", "component", "symbol"
        )
    )
    non_null = actual.get_column("normalized_rank").drop_nulls().to_list()
    assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in non_null)
    assert all(math.copysign(1.0, value) == 1.0 for value in non_null if value == 0.0)
