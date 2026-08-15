from __future__ import annotations

import datetime as dt
from decimal import Decimal

import polars as pl
import pytest

import quant.research.classic_factor_evaluation as evaluation_module
from quant.research.classic_factor_evaluation import (
    build_diagnostic_factor_targets,
    evaluate_factor_period,
    evaluate_factor_redundancy,
    newey_west_t_statistic,
    simulate_diagnostic_factor_portfolio,
)
from quant.research.m3.contracts import AShareCostPeriod


def _panel() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for day in range(8):
        date = start + dt.timedelta(days=day)
        for rank in range(10):
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"{600000 + rank:06d}.SH",
                    "factor_a": float(rank),
                    "label_1": rank / 100.0 + day / 10_000.0,
                    "exit_date_1": date + dt.timedelta(days=1),
                    "label_20": rank / 50.0 - 0.05,
                    "execution_date_20": date + dt.timedelta(days=1),
                    "exit_date_20": date + dt.timedelta(days=2),
                }
            )
    return pl.DataFrame(rows)


def _costs() -> tuple[AShareCostPeriod, ...]:
    return (
        AShareCostPeriod(
            effective_from=dt.date(2020, 1, 1),
            effective_to=None,
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.0005"),
            transfer_fee=Decimal("0.00001"),
            slippage=Decimal("0.001"),
        ),
    )


def test_ic_groups_and_newey_west_are_row_order_invariant() -> None:
    panel = _panel()
    first = evaluate_factor_period(
        panel,
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
    )
    shuffled = evaluate_factor_period(
        panel.reverse(),
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
    )
    assert first[0].equals(shuffled[0])
    assert first[1].equals(shuffled[1])
    assert first[2] == shuffled[2]
    assert first[2]["rank_ic_mean"] == pytest.approx(1.0)
    assert (
        first[1].filter(pl.col("group") == 5).get_column("mean_return").mean()
        > first[1].filter(pl.col("group") == 1).get_column("mean_return").mean()
    )
    assert math_is_finite(newey_west_t_statistic([0.01, 0.02, -0.01, 0.03], lag=1))


def test_direction_is_frozen_input_not_inferred_from_test_returns() -> None:
    positive = evaluate_factor_period(
        _panel(),
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
        direction=1,
    )[2]
    negative = evaluate_factor_period(
        _panel(),
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
        direction=-1,
    )[2]
    assert positive["rank_ic_mean"] == pytest.approx(-negative["rank_ic_mean"])


def test_explicit_monthly_newey_west_lag_is_not_replaced_by_session_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[int] = []

    def capture(values: list[float], *, lag: int) -> float:
        observed.append(lag)
        return 0.0

    monkeypatch.setattr(evaluation_module, "newey_west_t_statistic", capture)
    evaluate_factor_period(
        _panel(),
        factor="factor_a",
        horizon=20,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
        newey_west_lag=1,
    )
    assert observed == [1]


def test_redundancy_uses_daily_rank_correlation_and_is_row_order_invariant() -> None:
    panel = _panel().with_columns(
        (pl.col("factor_a") * 2.0).alias("factor_b"),
        (-pl.col("factor_a")).alias("reference_a"),
    )
    request = {
        "factors": ("factor_a", "factor_b"),
        "reference_factors": ("reference_a",),
        "start_date": dt.date(2025, 1, 1),
        "end_date": dt.date(2025, 1, 8),
        "minimum_symbols": 8,
    }

    daily, summary = evaluate_factor_redundancy(panel, **request)
    shuffled = evaluate_factor_redundancy(panel.reverse(), **request)

    assert daily.equals(shuffled[0])
    assert summary.equals(shuffled[1])
    assert summary.get_column("median_abs_rank_corr").to_list() == [1.0, 1.0, 1.0]


def test_targets_validate_and_two_x_cost_cannot_improve_return() -> None:
    targets, periods = build_diagnostic_factor_targets(
        _panel(),
        factor="factor_a",
        direction=1,
        fold=1,
        test_start=dt.date(2025, 1, 1),
        test_end=dt.date(2025, 1, 10),
        top_k=2,
        rebalance_every_sessions=2,
        minimum_symbols=8,
        strategy_name="classic",
        strategy_version="v1",
    )
    assert targets.group_by("as_of").agg(pl.col("weight").sum()).get_column(
        "weight"
    ).to_list() == pytest.approx([1.0] * periods.height)
    one_nav, one = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        costs=_costs(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("1000000"),
    )
    two_nav, two = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        costs=_costs(),
        multiplier=Decimal("2"),
        initial_cash=Decimal("1000000"),
    )
    assert one_nav.height == two_nav.height == periods.height
    assert two["total_return"] < one["total_return"]
    assert two_nav.get_column("cost").sum() > one_nav.get_column("cost").sum()
    assert one_nav.tail(1).get_column("terminal_cost").item() > 0


def math_is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}
