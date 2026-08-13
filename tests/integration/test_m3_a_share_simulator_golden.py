"""Deterministic development-example golden for the G7E account loop."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from quant.backtest.a_share_execution import build_a_share_market_facts
from quant.backtest.a_share_simulator import simulate_a_share_scenario
from quant.research.m3.contracts import AShareCostPeriod

_PLAN_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_plan_test_support_for_simulator_golden",
    Path(__file__).parents[1] / "unit" / "test_m3_backtest_plan_artifact.py",
)
assert _PLAN_SUPPORT_SPEC is not None and _PLAN_SUPPORT_SPEC.loader is not None
_PLAN_SUPPORT = importlib.util.module_from_spec(_PLAN_SUPPORT_SPEC)
_PLAN_SUPPORT_SPEC.loader.exec_module(_PLAN_SUPPORT)

_TABLES = (
    "nav",
    "trades",
    "positions",
    "rejections",
    "corporate_action_postings",
    "daily_diagnostics",
    "entitlements",
)


def _cost_periods() -> tuple[AShareCostPeriod, ...]:
    return (
        AShareCostPeriod(
            effective_from=dt.date(2016, 1, 1),
            effective_to=dt.date(2022, 4, 28),
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.001"),
            transfer_fee=Decimal("0.00002"),
            slippage=Decimal("0.001"),
        ),
        AShareCostPeriod(
            effective_from=dt.date(2022, 4, 29),
            effective_to=dt.date(2023, 8, 27),
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.001"),
            transfer_fee=Decimal("0.00001"),
            slippage=Decimal("0.001"),
        ),
        AShareCostPeriod(
            effective_from=dt.date(2023, 8, 28),
            effective_to=None,
            commission_rate=Decimal("0.00025"),
            commission_min=Decimal("5"),
            stamp_tax_sell=Decimal("0.0005"),
            transfer_fee=Decimal("0.00001"),
            slippage=Decimal("0.001"),
        ),
    )


def _verified_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any, Any]:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    plan = _PLAN_SUPPORT._verify(plan_bundle)
    target_bundle = plan_bundle[0]
    target = _PLAN_SUPPORT._TARGET_SUPPORT._verify(target_bundle)
    release = _PLAN_SUPPORT._TARGET_SUPPORT._parts(target_bundle[0])["release"]
    facts = build_a_share_market_facts(release=release, plan=plan)
    assert target.release_kind == plan.release_kind == facts.release_kind == (
        "development_example"
    )
    assert target.formal_gate_eligible is False
    assert plan.formal_gate_eligible is False
    assert facts.formal_gate_eligible is False
    return target, plan, facts


@pytest.fixture(scope="module")
def verified_inputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Any, Any]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield _verified_inputs(tmp_path_factory.mktemp("simulator-golden"), monkeypatch)
    finally:
        monkeypatch.undo()


def _run(target: Any, plan: Any, facts: Any) -> Any:
    return simulate_a_share_scenario(
        target=target,
        plan=plan,
        facts=facts,
        cost_periods=_cost_periods(),
        multiplier=Decimal("1"),
        initial_cash=Decimal("100000"),
    )


def _canonical_digest(frame: pl.DataFrame) -> str:
    def normalize(value: object) -> object:
        if isinstance(value, (dt.date, dt.datetime, Decimal)):
            return str(value)
        return value

    payload = {
        "columns": frame.columns,
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "rows": [[normalize(value) for value in row] for row in frame.rows()],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_verified_development_example_simulation_is_canonical_and_balanced(
    verified_inputs: tuple[Any, Any, Any],
) -> None:
    target, plan, facts = verified_inputs

    first = _run(target, plan, facts)
    rerun = _run(target, plan, facts)

    assert tuple(vars(first)) == ("multiplier", *_TABLES)
    assert first.multiplier == Decimal("1")
    assert first.nav.get_column("date").to_list() == list(
        plan.manifest.window.execution_dates
    )
    assert first.trades.height > 0
    for table in _TABLES:
        actual = getattr(first, table)
        assert _canonical_digest(actual) == _canonical_digest(getattr(rerun, table))

    for row in first.nav.iter_rows(named=True):
        cash = Decimal(str(row["cash"]))
        market_value = Decimal(str(row["market_value"]))
        cash_receivable = Decimal(str(row["cash_receivable"]))
        stock_receivable_value = Decimal(str(row["stock_receivable_value"]))
        assert Decimal(str(row["equity"])) == (
            cash + market_value + cash_receivable + stock_receivable_value
        )
        assert cash >= 0

    for row in first.trades.iter_rows(named=True):
        assert Decimal(str(row["notional"])) == (
            Decimal(row["quantity"]) * Decimal(str(row["execution_price"]))
        )
        assert Decimal(str(row["total_fee"])) == sum(
            (
                Decimal(str(row["commission"])),
                Decimal(str(row["stamp_tax"])),
                Decimal(str(row["transfer_fee"])),
            ),
            Decimal(0),
        )

    for row in first.positions.iter_rows(named=True):
        assert row["quantity"] == (
            row["sellable_quantity"] + row["unsettled_quantity"]
        )
    assert first.rejections.columns
    assert first.entitlements.columns


def test_verified_inputs_reject_target_drift_and_identity_mix(
    verified_inputs: tuple[Any, Any, Any],
) -> None:
    target, plan, facts = verified_inputs

    with pytest.raises(ValueError):
        _run(replace(target, manifest_sha256="e" * 64), plan, facts)
    with pytest.raises(ValueError):
        _run(
            target,
            replace(plan, example_id="development-example-" + "f" * 64),
            facts,
        )
