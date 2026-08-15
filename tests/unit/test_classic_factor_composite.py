from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import TargetWeightSchema
from quant.research.classic_factor_composite import (
    COMPOSITE_COMPONENTS,
    COMPOSITE_NAME,
    build_equal_weight_rank_composite,
    build_volatility_controlled_composite_targets,
    infer_validation_component_directions,
)


def test_equal_rank_composite_is_directional_and_row_order_invariant() -> None:
    day = dt.date(2024, 1, 2)
    panel = pl.DataFrame(
        {
            "trade_date": [day] * 3,
            "symbol": ["000001.SZ", "000002.SZ", "600000.SH"],
            "alpha158_std20": [3.0, 2.0, 1.0],
            "alpha158_roc20": [1.0, 2.0, 3.0],
            "alpha158_rsv20": [3.0, 2.0, 1.0],
        }
    )
    directions = (
        ("alpha158_std20", -1),
        ("alpha158_roc20", 1),
        ("alpha158_rsv20", -1),
    )

    expected = build_equal_weight_rank_composite(
        panel, component_directions=directions
    ).sort("symbol")
    shuffled = build_equal_weight_rank_composite(
        panel.reverse(), component_directions=directions
    ).sort("symbol")

    assert expected.equals(shuffled)
    assert expected.get_column(COMPOSITE_NAME).to_list() == [1 / 3, 2 / 3, 1.0]


def test_validation_directions_do_not_read_test_labels() -> None:
    validation_dates = [dt.date(2024, 1, day) for day in (2, 3, 4)]
    test_date = dt.date(2024, 2, 1)
    rows: list[dict[str, object]] = []
    for date in [*validation_dates, test_date]:
        for index, symbol in enumerate(
            ("000001.SZ", "000002.SZ", "600000.SH", "600001.SH"), 1
        ):
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "alpha158_std20": float(index),
                    "alpha158_roc20": float(5 - index),
                    "alpha158_rsv20": float(index),
                    "label_20": float(-index),
                    "exit_date_20": date,
                }
            )
    panel = pl.DataFrame(rows)
    request = {
        "components": COMPOSITE_COMPONENTS,
        "validation_start": validation_dates[0],
        "validation_end": validation_dates[-1],
        "minimum_symbols": 4,
        "groups": 2,
    }

    before = infer_validation_component_directions(panel, **request)
    changed = panel.with_columns(
        pl.when(pl.col("trade_date") == test_date)
        .then(-pl.col("label_20"))
        .otherwise(pl.col("label_20"))
        .alias("label_20")
    )
    after = infer_validation_component_directions(changed, **request)

    assert before == after
    assert before == (
        ("alpha158_std20", -1),
        ("alpha158_roc20", 1),
        ("alpha158_rsv20", -1),
    )


def test_volatility_control_preserves_selection_and_scales_gross_return() -> None:
    dates = [dt.date(2024, 1, day) for day in range(2, 13)]
    symbols = ("000001.SZ", "000002.SZ", "600000.SH", "600001.SH")
    rows: list[dict[str, object]] = []
    for date_index, date in enumerate(dates):
        for symbol_index, symbol in enumerate(symbols):
            close = 100.0 * (1.15 if date_index % 2 else 0.85) + symbol_index
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "close": close,
                    "adj_factor": 1.0,
                    "source": "fixture",
                    COMPOSITE_NAME: float(symbol_index),
                    "label_20": 0.04 - symbol_index * 0.01,
                    "execution_date_20": date,
                    "exit_date_20": date,
                }
            )
    panel = pl.DataFrame(rows)

    targets, periods = build_volatility_controlled_composite_targets(
        panel,
        factor=COMPOSITE_NAME,
        fold=1,
        test_start=dates[5],
        test_end=dates[-1],
        top_k=2,
        rebalance_every_sessions=2,
        minimum_symbols=4,
        strategy_name="composite",
        strategy_version="v1",
        lookback_observations=3,
        annualized_target_volatility=0.12,
        annualization_sessions=252,
    )

    TargetWeightSchema.validate(
        targets.select("as_of", "strategy", "strategy_version", "symbol", "weight")
    )
    assert targets.group_by("as_of").len().get_column("len").to_list() == [2, 2, 2]
    assert targets.get_column("symbol").unique().sort().to_list() == [
        "600000.SH",
        "600001.SH",
    ]
    assert targets.select((pl.col("weight") <= pl.col("base_weight")).all()).item()
    assert periods.select((pl.col("invested_weight") < 1.0).all()).item()
    for row in periods.iter_rows(named=True):
        current = targets.filter(pl.col("as_of") == row["as_of"])
        expected = sum(
            weight * (0.04 - symbols.index(symbol) * 0.01)
            for symbol, weight in current.select("symbol", "weight").iter_rows()
        )
        assert abs(row["gross_return"] - expected) < 1e-15
        assert row["gross_return"] < row["gross_return_unscaled"]


def test_volatility_control_fails_closed_to_cash_without_history() -> None:
    dates = [dt.date(2024, 1, day) for day in range(2, 8)]
    symbols = ("000001.SZ", "000002.SZ")
    panel = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": date,
                "close": 10.0 + index,
                "adj_factor": 1.0,
                "source": "fixture",
                COMPOSITE_NAME: float(index),
                "label_20": 0.01,
                "execution_date_20": date,
                "exit_date_20": date,
            }
            for date in dates
            for index, symbol in enumerate(symbols)
        ]
    )

    targets, periods = build_volatility_controlled_composite_targets(
        panel,
        factor=COMPOSITE_NAME,
        fold=1,
        test_start=dates[0],
        test_end=dates[-1],
        top_k=1,
        rebalance_every_sessions=1,
        minimum_symbols=2,
        strategy_name="composite",
        strategy_version="v1",
        lookback_observations=5,
        annualized_target_volatility=0.12,
        annualization_sessions=252,
    )

    first = targets.filter(pl.col("as_of") == dates[0])
    assert first.item(0, "weight") == 0.0
    assert periods.item(0, "gross_return") == 0.0


def test_benchmark_risk_control_does_not_require_common_stock_dates() -> None:
    dates = [dt.date(2024, 1, day) for day in range(2, 13)]
    symbols = ("000001.SZ", "000002.SZ", "600000.SH")
    panel = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": date,
                "close": 10.0 + index,
                "adj_factor": 1.0,
                "source": "fixture",
                COMPOSITE_NAME: float(index),
                "label_20": 0.01,
                "execution_date_20": date,
                "exit_date_20": date,
            }
            for date in dates
            for index, symbol in enumerate(symbols)
        ]
    )
    benchmark_prices = pl.DataFrame(
        {
            "symbol": ["510300.SH"] * len(dates),
            "trade_date": dates,
            "adjusted_close": [4.0 + 0.02 * index for index in range(len(dates))],
            "adjustment_method": ["CUMULATIVE_FACTOR"] * len(dates),
            "source": ["fixture"] * len(dates),
        }
    )

    targets, periods = build_volatility_controlled_composite_targets(
        panel,
        factor=COMPOSITE_NAME,
        fold=1,
        test_start=dates[5],
        test_end=dates[-1],
        top_k=2,
        rebalance_every_sessions=2,
        minimum_symbols=3,
        strategy_name="composite",
        strategy_version="v1",
        lookback_observations=3,
        annualized_target_volatility=0.12,
        annualization_sessions=252,
        risk_prices=benchmark_prices,
        risk_symbol="510300.SH",
    )

    assert periods.select((pl.col("invested_weight") > 0).all()).item()
    assert periods.select((pl.col("invested_weight") <= 1).all()).item()
    assert targets.group_by("as_of").agg(pl.col("risk_scale").n_unique()).select(
        (pl.col("risk_scale") == 1).all()
    ).item()
