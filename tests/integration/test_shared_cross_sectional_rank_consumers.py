from __future__ import annotations

import datetime as dt

import polars as pl

from quant.factors.cross_sectional_rank import rank_cross_sectional_components


def _frame(rows: list[tuple[dt.date, str, str, float | None]]) -> pl.DataFrame:
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


def test_r14_single_component_fixture_uses_the_public_identity() -> None:
    day = dt.date(2026, 8, 31)
    result = rank_cross_sectional_components(
        _frame([(day, "alpha004_input", "B", 7.0), (day, "alpha004_input", "A", 2.0)])
    )
    assert result.get_column("normalized_rank").to_list() == [0.0, 1.0]


def test_r15_three_components_keep_heterogeneous_valid_sets() -> None:
    day = dt.date(2026, 8, 31)
    result = rank_cross_sectional_components(
        _frame(
            [
                (day, "open", "A", 1.0),
                (day, "open", "B", 2.0),
                (day, "open", "C", 3.0),
                (day, "close", "A", None),
                (day, "close", "B", 10.0),
                (day, "close", "C", 20.0),
                (day, "volume", "A", 9.0),
                (day, "volume", "B", None),
                (day, "volume", "C", 1.0),
            ]
        )
    )
    assert result.filter(pl.col("component") == "open").get_column(
        "normalized_rank"
    ).to_list() == [0.0, 0.5, 1.0]
    assert result.filter(pl.col("component") == "close").get_column(
        "normalized_rank"
    ).to_list() == [None, 0.0, 1.0]
    assert result.filter(pl.col("component") == "volume").get_column(
        "normalized_rank"
    ).to_list() == [1.0, None, 0.0]


def test_r21_two_component_names_do_not_change_mathematics() -> None:
    day = dt.date(2026, 8, 31)
    rows = [("A", 3.0), ("B", 3.0), ("C", 9.0)]
    result = rank_cross_sectional_components(
        _frame(
            [
                (day, component, symbol, value)
                for component in ("high", "volume")
                for symbol, value in rows
            ]
        )
    )
    high = result.filter(pl.col("component") == "high").get_column(
        "normalized_rank"
    ).to_list()
    volume = result.filter(pl.col("component") == "volume").get_column(
        "normalized_rank"
    ).to_list()
    assert high == [0.25, 0.25, 1.0]
    assert volume == high
