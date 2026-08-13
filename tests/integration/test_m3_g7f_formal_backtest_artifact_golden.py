"""Golden formal G7F three-scenario artifact integration test."""

from __future__ import annotations

import importlib.util
import json
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_reporting as reporting_module
from quant.backtest.a_share_reporting import build_backtest_artifact

_UNIT_SPEC = importlib.util.spec_from_file_location(
    "m3_g7f_unit_support_for_golden",
    Path(__file__).parents[1]
    / "unit"
    / "test_m3_g7f_formal_backtest_artifact.py",
)
assert _UNIT_SPEC is not None and _UNIT_SPEC.loader is not None
_UNIT = importlib.util.module_from_spec(_UNIT_SPEC)
_UNIT_SPEC.loader.exec_module(_UNIT)


def _amounts(frame: pl.DataFrame, column: str) -> Decimal:
    return sum(
        (Decimal(str(value)) for value in frame[column].to_list()),
        Decimal(0),
    )


def test_five_session_three_scenario_golden_matches_actual_g7e_and_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _UNIT._formal_case(tmp_path, monkeypatch)
    results: list[Any] = []
    actual_g7e = reporting_module.simulate_formal_a_share_scenarios

    def captured(**kwargs: Any) -> Any:
        replayed = actual_g7e(**kwargs)
        results.extend(replayed)
        return replayed

    monkeypatch.setattr(
        reporting_module, "simulate_formal_a_share_scenarios", captured
    )
    manifest = build_backtest_artifact(
        **case["kwargs"], output_root=case["root"]
    )
    assert [result.multiplier for result in results] == [
        Decimal("0.5"), Decimal("1"), Decimal("2")
    ]
    assert [name for name, _ in case["calls"]] == [
        "g7f-plan", "g7f-facts", "g7e-plan"
    ]
    assert len(reporting_module._FORMAL_EXPECTED_NAMES) == 29

    facts_sha256s: set[str] = set()
    cost_sha256s: set[str] = set()
    root_metrics = json.loads(
        (case["root"] / "backtest_metrics.json").read_text(encoding="utf-8")
    )
    assert [item["scenario"] for item in root_metrics["scenarios"]] == [
        "0p5x", "1p0x", "2p0x"
    ]
    context = Context(prec=80, rounding=ROUND_HALF_UP)
    for scenario, result, metrics in zip(
        ("0p5x", "1p0x", "2p0x"),
        results,
        root_metrics["scenarios"],
        strict=True,
    ):
        scenario_root = case["root"] / scenario
        for filename, attribute, _ in reporting_module._TABLES:
            stored = pl.read_parquet(scenario_root / filename)
            assert stored.equals(cast(pl.DataFrame, getattr(result, attribute)))
        scenario_manifest = json.loads(
            (scenario_root / "manifest.json").read_text(encoding="utf-8")
        )
        assert len(scenario_manifest["output_files"]) == 8
        assert {item["path"] for item in scenario_manifest["output_files"]} == {
            "nav.parquet", "trades.parquet", "positions.parquet",
            "rejections.parquet", "corporate_action_postings.parquet",
            "daily_diagnostics.parquet", "entitlements.parquet", "metrics.json",
        }
        assert "manifest.json" not in {
            item["path"] for item in scenario_manifest["output_files"]
        }
        facts_sha256s.add(scenario_manifest["input_market_facts_sha256"])
        cost_sha256s.add(scenario_manifest["cost_periods_sha256"])

        nav = result.nav
        with localcontext(context):
            terminal_equity = Decimal(str(nav.item(-1, "equity")))
            portfolio_return = terminal_equity / Decimal("1000000") - Decimal(1)
            annualized = (
                (Decimal(1) + portfolio_return)
                ** (Decimal(252) / Decimal(5))
                - Decimal(1)
            )
            commission = _amounts(result.trades, "commission")
            stamp = _amounts(result.trades, "stamp_tax")
            transfer = _amounts(result.trades, "transfer_fee")
            slippage = _amounts(result.trades, "slippage_cost")
            gross = _amounts(result.daily_diagnostics, "gross_turnover")
            one_way = _amounts(result.daily_diagnostics, "one_way_turnover")
        assert metrics["n_sessions"] == 5
        assert metrics["initial_cash"] == 1000000.0
        assert metrics["terminal_equity"] == float(terminal_equity)
        assert metrics["portfolio_return"] == float(portfolio_return)
        assert metrics["annualized_return"] == float(annualized)
        assert metrics["benchmark_return"] == 0.0
        assert metrics["target_gross_turnover"] == 0.6
        assert metrics["target_one_way_turnover"] == 0.3
        assert metrics["realized_gross_turnover"] == float(gross)
        assert metrics["test_turnover"] == float(one_way)
        assert one_way == gross / Decimal(2)
        assert metrics["commission_total"] == float(commission)
        assert metrics["stamp_tax_total"] == float(stamp)
        assert metrics["transfer_fee_total"] == float(transfer)
        assert metrics["total_fees"] == float(commission + stamp + transfer)
        assert metrics["slippage_cost_total"] == float(slippage)
        assert metrics["total_trading_cost"] == float(
            commission + stamp + transfer + slippage
        )
        assert metrics["rejection_count"] <= metrics["requested_order_count"]

    assert len(facts_sha256s) == 1
    assert len(cost_sha256s) == 3
    assert tuple(name for name, _ in manifest.scenario_manifest_sha256s) == (
        "0p5x", "1p0x", "2p0x"
    )
    root_manifest = json.loads(
        (case["root"] / "backtest_manifest.json").read_text(encoding="utf-8")
    )
    assert root_manifest["common_market_facts_sha256"] == facts_sha256s.pop()
    assert root_manifest["common_target_manifest_sha256"] == (
        case["kwargs"]["target"].manifest_sha256
    )
