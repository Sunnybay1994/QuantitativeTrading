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
                    "exit_date_20": date + dt.timedelta(days=3),
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


def _holding_outcomes(
    panel: pl.DataFrame, *, return_column: str = "label_20"
) -> pl.DataFrame:
    return panel.select(
        pl.col("trade_date").alias("as_of"),
        "symbol",
        pl.col(return_column).alias("holding_return"),
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


@pytest.mark.parametrize('remaining', [0, 7])
def test_incomplete_cohort_error_names_date_and_actual_count(remaining: int) -> None:
    panel = _panel().with_columns(pl.when(
        (pl.col('trade_date') == dt.date(2025, 1, 2)) & (pl.col('factor_a') >= remaining))
        .then(None).otherwise(pl.col('factor_a')).alias('factor_a'))
    with pytest.raises(ValueError, match=f'2025-01-02:{remaining}'):
        evaluate_factor_period(panel, factor='factor_a', horizon=1,
            start_date=dt.date(2025, 1, 1), end_date=dt.date(2025, 1, 8), minimum_symbols=8)


def test_factor_cohort_and_groups_are_frozen_before_pairing_future_labels() -> None:
    baseline_daily, baseline_groups, _ = evaluate_factor_period(
        _panel(),
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
    )
    changed = _panel().with_columns(
        pl.when(
            (pl.col("trade_date") == dt.date(2025, 1, 1))
            & (pl.col("symbol") == "600005.SH")
        )
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("label_1"))
        .alias("label_1")
    )
    daily, groups, _ = evaluate_factor_period(
        changed.reverse(),
        factor="factor_a",
        horizon=1,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 1, 8),
        minimum_symbols=8,
    )

    first = daily.filter(pl.col("trade_date") == dt.date(2025, 1, 1)).row(
        0, named=True
    )
    assert first["factor_count"] == first["coverage_denominator"] == 10
    assert first["n_symbols"] == first["paired_count"] == 9
    assert first["coverage_numerator"] == 9
    assert first["coverage_status"] == "PASS"
    assert groups.select("trade_date", "group", "factor_count").equals(
        baseline_groups.select("trade_date", "group", "factor_count")
    )
    assert daily.get_column("trade_date").to_list() == baseline_daily.get_column(
        "trade_date"
    ).to_list()
    assert groups.height == daily.height * 5


def test_factor_period_rejects_incomplete_or_noncomputable_planned_dates() -> None:
    too_few_pairs = _panel().with_columns(
        pl.when(
            (pl.col("trade_date") == dt.date(2025, 1, 1))
            & pl.col("symbol").is_in(["600000.SH", "600001.SH", "600002.SH"])
        )
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("label_1"))
        .alias("label_1")
    )
    with pytest.raises(ValueError, match="paired outcomes are incomplete"):
        evaluate_factor_period(
            too_few_pairs,
            factor="factor_a",
            horizon=1,
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 1, 8),
            minimum_symbols=8,
        )

    constant_label = _panel().with_columns(
        pl.when(pl.col("trade_date") == dt.date(2025, 1, 1))
        .then(pl.lit(1.0))
        .otherwise(pl.col("label_1"))
        .alias("label_1")
    )
    with pytest.raises(ValueError, match="non-computable planned date"):
        evaluate_factor_period(
            constant_label,
            factor="factor_a",
            horizon=1,
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 1, 8),
            minimum_symbols=8,
        )


@pytest.mark.parametrize("replacement", [None, dt.date(2025, 1, 3)])
def test_factor_period_rejects_mixed_exit_dates(replacement: dt.date | None) -> None:
    changed = _panel().with_columns(
        pl.when(
            (pl.col("trade_date") == dt.date(2025, 1, 1))
            & (pl.col("symbol") == "600000.SH")
        )
        .then(pl.lit(replacement, dtype=pl.Date))
        .otherwise(pl.col("exit_date_1"))
        .alias("exit_date_1")
    )
    with pytest.raises(ValueError, match="exit-date plan is inconsistent"):
        evaluate_factor_period(
            changed,
            factor="factor_a",
            horizon=1,
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 1, 8),
            minimum_symbols=8,
        )


def test_factor_period_rejects_an_internal_horizon_boundary() -> None:
    changed = _panel().with_columns(
        pl.when(pl.col("trade_date") == dt.date(2025, 1, 4))
        .then(pl.lit(None, dtype=pl.Date))
        .otherwise(pl.col("exit_date_1"))
        .alias("exit_date_1")
    )
    with pytest.raises(ValueError, match="exit-date plan is inconsistent"):
        evaluate_factor_period(
            changed,
            factor="factor_a",
            horizon=1,
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 1, 8),
            minimum_symbols=8,
        )


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
        holding_outcomes=_holding_outcomes(_panel()),
        costs=_costs(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("1000000"),
    )
    two_nav, two = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        holding_outcomes=_holding_outcomes(_panel()),
        costs=_costs(),
        multiplier=Decimal("2"),
        initial_cash=Decimal("1000000"),
    )
    assert one_nav.height == two_nav.height == periods.height
    assert two["total_return"] < one["total_return"]
    assert two_nav.get_column("cost").sum() > one_nav.get_column("cost").sum()
    assert one_nav.tail(1).get_column("terminal_cost").item() > 0


def test_portfolio_turnover_uses_return_drifted_holdings() -> None:
    first = dt.date(2025, 1, 1)
    second = dt.date(2025, 1, 3)
    targets = pl.DataFrame(
        {
            "as_of": [first, first, second, second],
            "symbol": ["600000.SH", "600001.SH"] * 2,
            "weight": [0.5, 0.5, 0.5, 0.5],
        }
    )
    periods = pl.DataFrame(
        {
            "as_of": [first, second],
            "execution_date": [dt.date(2025, 1, 2), dt.date(2025, 1, 4)],
            "exit_date": [dt.date(2025, 1, 4), dt.date(2025, 1, 6)],
            "gross_return": [0.5, 0.0],
        }
    )
    outcomes = pl.DataFrame(
        {
            "as_of": [first, first, second, second],
            "symbol": ["600000.SH", "600001.SH"] * 2,
            "holding_return": [1.0, 0.0, 0.0, 0.0],
        }
    )

    nav, _ = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        holding_outcomes=outcomes,
        costs=_costs(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("1000000"),
    )

    assert nav.item(1, "turnover") == pytest.approx(1.0 / 3.0)
    assert nav.item(1, "cost") > 0


def test_unselected_outcomes_do_not_change_nav_or_targets() -> None:
    targets, periods = _build_targets(_panel())
    baseline = _holding_outcomes(_panel())
    unselected = baseline.filter(
        (pl.col("as_of") == dt.date(2025, 1, 1))
        & (pl.col("symbol") == "600000.SH")
    ).with_columns(pl.lit(999.0).alias("holding_return"))
    first, _ = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        holding_outcomes=baseline,
        costs=_costs(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("1000000"),
    )
    second, _ = simulate_diagnostic_factor_portfolio(
        targets=targets,
        periods=periods,
        holding_outcomes=pl.concat([baseline, unselected]),
        costs=_costs(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("1000000"),
    )

    assert first.equals(second)
    assert not ({"holding_return", "label_20"} & set(targets.columns))


@pytest.mark.parametrize("bad_return", [None, float("nan"), float("inf"), -1.01])
def test_portfolio_rejects_invalid_selected_holding_outcomes(
    bad_return: float | None,
) -> None:
    targets, periods = _build_targets(_panel())
    selected = (pl.col("as_of") == dt.date(2025, 1, 1)) & (
        pl.col("symbol") == "600009.SH"
    )
    outcomes = _holding_outcomes(_panel()).with_columns(
        pl.when(selected)
        .then(pl.lit(bad_return, dtype=pl.Float64))
        .otherwise(pl.col("holding_return"))
        .alias("holding_return")
    )
    with pytest.raises(ValueError, match="holding outcomes"):
        simulate_diagnostic_factor_portfolio(
            targets=targets,
            periods=periods,
            holding_outcomes=outcomes,
            costs=_costs(),
            multiplier=Decimal("1"),
            initial_cash=Decimal("1000000"),
        )


def test_portfolio_rejects_duplicate_outcomes_and_noncontiguous_periods() -> None:
    targets, periods = _build_targets(_panel())
    outcomes = _holding_outcomes(_panel())
    duplicate = pl.concat(
        [
            outcomes,
            outcomes.filter(
                (pl.col("as_of") == dt.date(2025, 1, 1))
                & (pl.col("symbol") == "600009.SH")
            ),
        ]
    )
    with pytest.raises(ValueError, match="holding outcomes are incomplete"):
        simulate_diagnostic_factor_portfolio(
            targets=targets,
            periods=periods,
            holding_outcomes=duplicate,
            costs=_costs(),
            multiplier=Decimal("1"),
            initial_cash=Decimal("1000000"),
        )

    gapped = periods.with_columns(
        pl.when(pl.col("as_of") == periods.get_column("as_of").item(1))
        .then(pl.col("execution_date") + dt.timedelta(days=1))
        .otherwise(pl.col("execution_date"))
        .alias("execution_date")
    )
    with pytest.raises(ValueError, match="holding periods are not contiguous"):
        simulate_diagnostic_factor_portfolio(
            targets=targets,
            periods=gapped,
            holding_outcomes=outcomes,
            costs=_costs(),
            multiplier=Decimal("1"),
            initial_cash=Decimal("1000000"),
        )


def _build_targets(panel: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    return build_diagnostic_factor_targets(
        panel,
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


def _replace_selected_value(
    panel: pl.DataFrame,
    *,
    column: str,
    value: object,
) -> pl.DataFrame:
    selected = (pl.col("trade_date") == dt.date(2025, 1, 1)) & (
        pl.col("symbol") == "600009.SH"
    )
    return panel.with_columns(
        pl.when(selected).then(pl.lit(value)).otherwise(pl.col(column)).alias(column)
    )


def test_selected_missing_future_label_fails_without_substituting_next_symbol() -> None:
    panel = _replace_selected_value(_panel(), column="label_20", value=None)

    with pytest.raises(ValueError, match="diagnostic selected target outcomes are invalid"):
        _build_targets(panel)


def test_unselected_missing_future_label_does_not_change_targets() -> None:
    baseline_targets, baseline_periods = _build_targets(_panel())
    unselected = (pl.col("trade_date") == dt.date(2025, 1, 1)) & (
        pl.col("symbol") == "600000.SH"
    )
    changed = _panel().with_columns(
        pl.when(unselected)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("label_20"))
        .alias("label_20")
    )

    changed_targets, changed_periods = _build_targets(changed.reverse())

    assert changed_targets.equals(baseline_targets)
    assert changed_periods.equals(baseline_periods)


def test_future_label_values_do_not_change_symbols_or_weights() -> None:
    baseline_targets, baseline_periods = _build_targets(_panel())
    changed_targets, changed_periods = _build_targets(
        _panel().with_columns((-pl.col("label_20") + 0.25).alias("label_20"))
    )

    identity_columns = ["as_of", "strategy", "strategy_version", "symbol", "weight"]
    assert changed_targets.select(identity_columns).equals(
        baseline_targets.select(identity_columns)
    )
    assert changed_periods.get_column("gross_return").to_list() != pytest.approx(
        baseline_periods.get_column("gross_return").to_list()
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("label_20", float("nan")),
        ("label_20", float("inf")),
        ("execution_date_20", None),
        ("exit_date_20", None),
        ("execution_date_20", dt.date(2025, 1, 3)),
        ("exit_date_20", dt.date(2025, 1, 5)),
    ],
)
def test_selected_invalid_outcome_fails_closed(column: str, value: object) -> None:
    panel = _replace_selected_value(_panel(), column=column, value=value)

    with pytest.raises(ValueError, match="diagnostic selected target outcomes are invalid"):
        _build_targets(panel)


def test_selected_exit_before_execution_fails_closed() -> None:
    selected = (pl.col("trade_date") == dt.date(2025, 1, 1)) & (
        pl.col("symbol").is_in(("600008.SH", "600009.SH"))
    )
    panel = _panel().with_columns(
        pl.when(selected)
        .then(pl.lit(dt.date(2025, 1, 1)))
        .otherwise(pl.col("exit_date_20"))
        .alias("exit_date_20")
    )

    with pytest.raises(ValueError, match="diagnostic selected target outcomes are invalid"):
        _build_targets(panel)


def math_is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}
