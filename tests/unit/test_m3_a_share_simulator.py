"""G7E single-scenario A-share account-loop adversarial tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.backtest.a_share_simulator import (
    AShareSimulationResult,
    simulate_a_share_scenario,
)
from quant.research.m3.contracts import AShareCostPeriod

_PLAN_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_plan_test_support_for_simulator",
    Path(__file__).with_name("test_m3_backtest_plan_artifact.py"),
)
assert _PLAN_SUPPORT_SPEC is not None and _PLAN_SUPPORT_SPEC.loader is not None
_PLAN_SUPPORT = importlib.util.module_from_spec(_PLAN_SUPPORT_SPEC)
_PLAN_SUPPORT_SPEC.loader.exec_module(_PLAN_SUPPORT)

_NAV = [
    "date", "pre_trade_equity", "cash", "market_value", "cash_receivable",
    "stock_receivable_value", "equity", "unit_nav", "daily_return",
    "cumulative_commission", "cumulative_stamp_tax", "cumulative_transfer_fee",
    "cumulative_slippage_cost",
]
_TRADES = [
    "date", "symbol", "side", "quantity", "reference_open", "execution_price",
    "notional", "commission", "stamp_tax", "transfer_fee", "total_fee",
    "slippage_cost",
]
_POSITIONS = [
    "date", "symbol", "quantity", "sellable_quantity", "unsettled_quantity",
    "mark_price", "market_value", "target_weight", "target_quantity", "pending_exit",
]
_REJECTIONS = [
    "date", "symbol", "side", "reason", "requested_quantity", "filled_quantity",
    "rejected_quantity", "rejected_notional",
]
_POSTINGS = [
    "date", "event_id", "symbol", "posting_type", "cash_amount", "stock_quantity",
    "cash_rounding_delta", "cash_state_before", "cash_state_after",
    "stock_state_before", "stock_state_after",
]
_DIAGNOSTICS = [
    "date", "n_target_symbols", "n_position_symbols", "n_order_intents", "n_trades",
    "n_rejections", "pre_trade_equity", "gross_turnover", "one_way_turnover",
    "buy_allocation_lambda", "cash_after",
]
_ENTITLEMENTS = [
    "date", "event_id", "symbol", "record_quantity", "cash_entitlement_gross",
    "stock_entitlement", "cash_state", "stock_state", "cash_receivable",
    "stock_receivable", "stock_receivable_value",
]


def _periods() -> tuple[AShareCostPeriod, ...]:
    return (
        AShareCostPeriod(
            effective_from=dt_date(2016, 1, 1),
            effective_to=dt_date(2022, 4, 28),
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.001"),
            transfer_fee=Decimal("0.00002"),
            slippage=Decimal("0.001"),
        ),
        AShareCostPeriod(
            effective_from=dt_date(2022, 4, 29),
            effective_to=dt_date(2023, 8, 27),
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.001"),
            transfer_fee=Decimal("0.00001"),
            slippage=Decimal("0.001"),
        ),
        AShareCostPeriod(
            effective_from=dt_date(2023, 8, 28),
            effective_to=None,
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.0005"),
            transfer_fee=Decimal("0.00001"),
            slippage=Decimal("0.001"),
        ),
    )


def dt_date(year: int, month: int, day: int) -> Any:
    import datetime as dt

    return dt.date(year, month, day)


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    plan = _PLAN_SUPPORT._verify(plan_bundle)
    target = _PLAN_SUPPORT._TARGET_SUPPORT._verify(plan_bundle[0])
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    facts_module = __import__(
        "quant.backtest.a_share_execution", fromlist=["build_a_share_market_facts"]
    )
    facts = facts_module.build_a_share_market_facts(
        release=parts["release"], plan=plan
    )
    return plan_bundle, target, plan, facts


@pytest.fixture(scope="module")
def simulator_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, ...]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield _build_bundle(tmp_path_factory.mktemp("simulator"), monkeypatch)
    finally:
        monkeypatch.undo()


def _run(
    target: Any,
    plan: Any,
    facts: Any,
    *,
    initial_cash: Decimal = Decimal("10000"),
) -> AShareSimulationResult:
    return simulate_a_share_scenario(
        target=target,
        plan=plan,
        facts=facts,
        cost_periods=_periods(),
        multiplier=Decimal("1"),
        initial_cash=initial_cash,
    )


def _logical_digest(frame: pl.DataFrame) -> str:
    rows = [
        [
            value.isoformat() if hasattr(value, "isoformat") else value
            for value in row
        ]
        for row in frame.rows()
    ]
    import json

    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _retarget_for_rotation(target: Any, plan: Any) -> tuple[Any, Any, str, str]:
    dates = tuple(plan.manifest.window.signal_dates)
    if len(dates) < 2:
        raise AssertionError("development plan must expose two test dates")
    symbols = sorted(target.targets.get_column("symbol").unique().to_list())
    first, second = cast(str, symbols[0]), cast(str, symbols[-1])
    weights = target.targets.with_columns(
        pl.when((pl.col("as_of") == dates[0]) & (pl.col("symbol") == first))
        .then(0.8)
        .when((pl.col("as_of") == dates[1]) & (pl.col("symbol") == second))
        .then(0.8)
        .otherwise(0.0)
        .alias("weight")
    )
    daily = target.target_daily.with_columns(
        pl.lit(1, dtype=pl.Int64).alias("n_selected"),
        pl.lit(0.8, dtype=pl.Float64).alias("total_target_weight"),
    )
    new_target = replace(
        target,
        targets=weights,
        target_daily=daily,
        manifest=replace(target.manifest, n_selected=len(dates)),
    )
    scheduled = plan.scheduled_targets.drop("weight").join(
        weights,
        on=["as_of", "strategy", "strategy_version", "symbol"],
        how="left",
    ).select(plan.scheduled_targets.columns).sort("execution_date", "as_of", "symbol")
    new_plan = replace(plan, scheduled_targets=scheduled)
    return new_target, new_plan, first, second


def _move_dividend_into_window(facts: Any, plan: Any, symbol: str) -> Any:
    record_date, ex_date = plan.manifest.window.execution_dates[:2]
    actions = facts.corporate_actions.with_columns(
        pl.lit(symbol).alias("symbol"),
        pl.lit(record_date).cast(pl.Date).alias("record_date"),
        pl.lit(ex_date).cast(pl.Date).alias("ex_date"),
        pl.lit(ex_date).cast(pl.Date).alias("pay_date"),
    )
    reconciliations = facts.corporate_action_reconciliation.with_columns(
        pl.lit(symbol).alias("symbol"),
        pl.lit(record_date).cast(pl.Date).alias("previous_factor_date"),
        pl.lit(ex_date).cast(pl.Date).alias("effective_date"),
        pl.lit(record_date).cast(pl.Date).alias("previous_close_date"),
    )
    return replace(
        facts,
        corporate_actions=actions,
        corporate_action_reconciliation=reconciliations,
    )


def test_simulator_outputs_exact_seven_tables_and_decimal_invariants(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    result = _run(target, plan, facts)
    assert type(result) is AShareSimulationResult
    assert result.multiplier == Decimal("1")
    assert result.nav.columns == _NAV
    assert result.trades.columns == _TRADES
    assert result.positions.columns == _POSITIONS
    assert result.rejections.columns == _REJECTIONS
    assert result.corporate_action_postings.columns == _POSTINGS
    assert result.daily_diagnostics.columns == _DIAGNOSTICS
    assert result.entitlements.columns == _ENTITLEMENTS
    assert result.nav.height == len(plan.manifest.window.execution_dates)
    assert result.nav.get_column("date").to_list() == list(
        plan.manifest.window.execution_dates
    )
    for row in result.nav.iter_rows(named=True):
        values = {
            name: Decimal(str(row[name]))
            for name in (
                "cash", "market_value", "cash_receivable",
                "stock_receivable_value", "equity",
            )
        }
        assert values["cash"] >= 0
        assert values["equity"] == (
            values["cash"] + values["market_value"]
            + values["cash_receivable"] + values["stock_receivable_value"]
        )
    for row in result.positions.iter_rows(named=True):
        assert row["quantity"] == row["sellable_quantity"] + row["unsettled_quantity"]
        assert Decimal(str(row["market_value"])) == (
            Decimal(row["quantity"]) * Decimal(str(row["mark_price"]))
        )
    for row in result.trades.iter_rows(named=True):
        fee = sum(
            (Decimal(str(row[name])) for name in ("commission", "stamp_tax", "transfer_fee")),
            Decimal(0),
        )
        assert Decimal(str(row["total_fee"])) == fee
        assert Decimal(str(row["notional"])) == (
            Decimal(row["quantity"]) * Decimal(str(row["execution_price"]))
        )
    for frame in (
        result.nav, result.trades, result.positions, result.rejections,
        result.corporate_action_postings, result.daily_diagnostics,
        result.entitlements,
    ):
        for dtype, name in zip(frame.dtypes, frame.columns, strict=True):
            if dtype in (pl.Float32, pl.Float64):
                assert frame.get_column(name).is_finite().all()


def test_session_order_captures_record_close_then_recognizes_and_settles_ex_date(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    target, plan, held_symbol, _ = _retarget_for_rotation(target, plan)
    facts = _move_dividend_into_window(facts, plan, held_symbol)
    result = _run(target, plan, facts)
    record_date, ex_date = plan.manifest.window.execution_dates[:2]
    record_positions = result.positions.filter(
        (pl.col("date") == record_date) & (pl.col("symbol") == held_symbol)
    )
    assert record_positions.height == 1
    record_quantity = record_positions.item(0, "quantity")
    assert record_quantity > 0
    ex_postings = result.corporate_action_postings.filter(
        (pl.col("date") == ex_date) & (pl.col("symbol") == held_symbol)
    )
    assert set(ex_postings.get_column("posting_type")) >= {
        "CASH_RECOGNIZE", "CASH_SETTLE"
    }
    recognized = ex_postings.filter(pl.col("posting_type") == "CASH_RECOGNIZE")
    assert recognized.height == 1
    entitlement = Decimal(str(facts.corporate_actions.item(0, "cash_per_share_gross")))
    capture = result.corporate_action_postings.filter(
        pl.col("posting_type") == "CAPTURE"
    )
    assert capture.height == 1
    assert capture.item(0, "date") == record_date
    assert capture.item(0, "symbol") == held_symbol
    assert result.nav.filter(pl.col("date") == ex_date).item(0, "equity") > 0
    assert entitlement > 0


def test_sell_proceeds_are_available_to_same_day_buys_and_terminal_not_forced(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    target, plan, sold_symbol, bought_symbol = _retarget_for_rotation(target, plan)
    result = _run(target, plan, facts)
    last = plan.manifest.window.execution_dates[-1]
    last_trades = result.trades.filter(pl.col("date") == last)
    assert last_trades.filter(
        (pl.col("symbol") == sold_symbol) & (pl.col("side") == "SELL")
    ).height == 1
    assert last_trades.filter(
        (pl.col("symbol") == bought_symbol) & (pl.col("side") == "BUY")
    ).height == 1
    assert result.nav.filter(pl.col("date") == last).item(0, "cash") >= 0
    terminal_positions = result.positions.filter(pl.col("date") == last)
    assert terminal_positions.filter(
        (pl.col("symbol") == bought_symbol) & (pl.col("quantity") > 0)
    ).height == 1
    assert plan.manifest.window.force_liquidation is False


def test_full_day_held_position_keeps_mark_and_unexplained_missing_bar_fails_closed(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    target, plan, held_symbol, _ = _retarget_for_rotation(target, plan)
    first, last = plan.manifest.window.execution_dates[:2]
    keep = target.targets.with_columns(
        pl.when(pl.col("symbol") == held_symbol).then(0.8).otherwise(0.0).alias("weight")
    )
    target = replace(target, targets=keep)
    scheduled = plan.scheduled_targets.drop("weight").join(
        keep,
        on=["as_of", "strategy", "strategy_version", "symbol"],
        how="left",
    ).select(plan.scheduled_targets.columns).sort("execution_date", "as_of", "symbol")
    plan = replace(plan, scheduled_targets=scheduled)
    source = facts.suspensions.row(0, named=True)
    suspension = pl.DataFrame([{
        "symbol": held_symbol,
        "trade_date": last,
        "suspension_scope": "FULL_DAY",
        "suspension_detail": None,
        "source": source["source"],
        "source_snapshot_id": source["source_snapshot_id"],
    }]).with_columns(pl.col("trade_date").cast(pl.Date))
    bars = facts.bars.filter(
        ~((pl.col("symbol") == held_symbol) & (pl.col("trade_date") == last))
    )
    limits = facts.limits.filter(
        ~((pl.col("symbol") == held_symbol) & (pl.col("trade_date") == last))
    )
    suspended = replace(facts, bars=bars, limits=limits, suspensions=suspension)
    result = _run(target, plan, suspended)
    first_mark = result.positions.filter(
        (pl.col("date") == first) & (pl.col("symbol") == held_symbol)
    ).item(0, "mark_price")
    last_mark = result.positions.filter(
        (pl.col("date") == last) & (pl.col("symbol") == held_symbol)
    ).item(0, "mark_price")
    assert last_mark == first_mark
    unexplained = replace(suspended, suspensions=suspension.head(0))
    with pytest.raises(ValueError):
        _run(target, plan, unexplained)


def test_result_is_invariant_to_input_row_order(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    expected = _run(target, plan, facts)
    shuffled_target = replace(target, targets=target.targets.reverse())
    shuffled_plan = replace(plan, scheduled_targets=plan.scheduled_targets.reverse())
    shuffled_facts = replace(
        facts,
        instruments=facts.instruments.reverse(),
        calendar=facts.calendar.reverse(),
        bars=facts.bars.reverse(),
        limits=facts.limits.reverse(),
        suspensions=facts.suspensions.reverse(),
        corporate_actions=facts.corporate_actions.reverse(),
        corporate_action_reconciliation=facts.corporate_action_reconciliation.reverse(),
        benchmark_bars=facts.benchmark_bars.reverse(),
    )
    actual = _run(shuffled_target, shuffled_plan, shuffled_facts)
    for name in (
        "nav", "trades", "positions", "rejections", "corporate_action_postings",
        "daily_diagnostics", "entitlements",
    ):
        assert _logical_digest(getattr(actual, name)) == _logical_digest(
            getattr(expected, name)
        )


def test_simulator_rejects_wrong_types_non_decimal_and_identity_mix(
    simulator_bundle: tuple[Any, ...],
) -> None:
    _, target, plan, facts = simulator_bundle
    with pytest.raises((TypeError, ValueError)):
        simulate_a_share_scenario(
            target=target.targets,  # type: ignore[arg-type]
            plan=plan,
            facts=facts,
            cost_periods=_periods(),
            multiplier=Decimal("1"),
            initial_cash=Decimal("10000"),
        )
    with pytest.raises((TypeError, ValueError)):
        simulate_a_share_scenario(
            target=target,
            plan=plan,
            facts=facts,
            cost_periods=_periods(),
            multiplier=1.0,  # type: ignore[arg-type]
            initial_cash=Decimal("10000"),
        )
    with pytest.raises(ValueError):
        _run(
            target,
            replace(plan, example_id="development-example-" + "f" * 64),
            facts,
        )
    with pytest.raises(ValueError):
        _run(
            target,
            plan,
            replace(facts, example_id="development-example-" + "f" * 64),
        )
    forbidden = {"label", "prediction", "release_id", "artifact_paths"}
    assert forbidden.isdisjoint(inspect.signature(simulate_a_share_scenario).parameters)
