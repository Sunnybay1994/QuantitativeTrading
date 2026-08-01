"""G7F development three-scenario backtest publication adversarial tests."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import math
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_reporting as reporting_module
from quant.backtest.a_share_reporting import (
    BacktestArtifactUpstreamPaths,
    build_development_example_backtest_artifact,
    verify_development_example_backtest_artifact,
)
from quant.research.m3.contracts import (
    AShareScenarioMetricsV1,
    BacktestArtifactEntryV1,
    BacktestBundleManifestV1,
    BacktestMetricsV1,
    BacktestScenarioManifestV1,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestArtifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_PLAN_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_plan_test_support_for_reporting",
    Path(__file__).with_name("test_m3_backtest_plan_artifact.py"),
)
assert _PLAN_SUPPORT_SPEC is not None and _PLAN_SUPPORT_SPEC.loader is not None
_PLAN_SUPPORT = importlib.util.module_from_spec(_PLAN_SUPPORT_SPEC)
_PLAN_SUPPORT_SPEC.loader.exec_module(_PLAN_SUPPORT)

_SCENARIOS = ("0p5x", "1p0x", "2p0x")
_MULTIPLIERS = (0.5, 1.0, 2.0)
_TABLES = (
    "nav.parquet",
    "trades.parquet",
    "positions.parquet",
    "rejections.parquet",
    "corporate_action_postings.parquet",
    "daily_diagnostics.parquet",
    "entitlements.parquet",
)


def _parts(plan_bundle: tuple[Any, ...]) -> dict[str, Any]:
    target_bundle = plan_bundle[0]
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(target_bundle[0])
    return {
        **parts,
        "target": _PLAN_SUPPORT._TARGET_SUPPORT._verify(target_bundle),
        "target_receipt": target_bundle[5],
        "plan": _PLAN_SUPPORT._verify(plan_bundle),
        "plan_receipt": plan_bundle[4],
    }


def _inputs(plan_bundle: tuple[Any, ...]) -> list[tuple[str, Path]]:
    p = _parts(plan_bundle)
    target, plan, release, experiment = (
        p["target"], p["plan"], p["release"], p["experiment"]
    )
    target_files = [
        target.root / "target_manifest.json",
        cast(Path, p["target_receipt"]),
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
    ]
    plan_files = [
        plan.root / "manifest.json",
        cast(Path, p["plan_receipt"]),
        plan.root / "scheduled_targets.parquet",
        plan.root / "schedule_diagnostics.parquet",
        plan.root / "cost_schedule.json",
    ]
    experiment_files = [
        experiment.root / "experiment_manifest.json",
        _PLAN_SUPPORT._TARGET_SUPPORT._experiment_receipt(p),
    ]
    release_files = [
        release.release.manifest_path,
        release.release.root / "receipt.json",
        *(path for name, path in release.artifact_paths if name in {
            "instrument.parquet", "trade_calendar.parquet", "bar_1d.parquet",
            "price_limit_1d.parquet", "suspension_1d.parquet",
            "corporate_action_ledger.parquet",
            "corporate_action_reconciliation.parquet", "benchmark_bar_1d.parquet",
        }),
    ]
    return [("root", path) for path in (*target_files, *plan_files, *experiment_files, *release_files)]


def _outputs(root: Path) -> list[tuple[str, Path]]:
    paths = [
        *(root / scenario / name for scenario in _SCENARIOS for name in (*_TABLES, "metrics.json", "manifest.json")),
        root / "backtest_metrics.json",
        root / "backtest_manifest.json",
    ]
    return [("root", path) for path in paths]


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    p = _parts(plan_bundle)
    root = cast(Path, p["common"]) / f"development-example-backtest-{p['target'].manifest.work_key}"
    root.mkdir()
    manifest = build_development_example_backtest_artifact(
        target=p["target"], plan=p["plan"], release=p["release"],
        experiment=p["experiment"], config=p["config"], output_root=root,
    )
    receipt = (
        cast(Path, p["common"]) / "receipts" / "development-backtest"
        / f"{p['target'].manifest.work_key}.json"
    )
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-backtest",
        scope="WORK",
        scope_key=p["target"].manifest.work_key,
        artifact_roots=p["roots"],
        inputs=_inputs(plan_bundle),
        outputs=_outputs(root),
    )
    upstream = BacktestArtifactUpstreamPaths(
        target_receipt_path=cast(Path, p["target_receipt"]),
        plan_receipt_path=cast(Path, p["plan_receipt"]),
        experiment_receipt_path=_PLAN_SUPPORT._TARGET_SUPPORT._experiment_receipt(p),
        g1_receipt_path=p["release"].release.root / "receipt.json",
    )
    return plan_bundle, p, upstream, root, receipt, manifest


@pytest.fixture(scope="module")
def reporting_bundle(tmp_path_factory: pytest.TempPathFactory) -> Any:
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield _build_bundle(tmp_path_factory.mktemp("reporting"), monkeypatch)
    finally:
        monkeypatch.undo()


def _verify(bundle: tuple[Any, ...], *, receipt: Path | None = None, plan: Any = None) -> Any:
    plan_bundle, p, upstream, root, default_receipt, _ = bundle
    kwargs = {
        "root": root,
        "receipt_path": receipt or default_receipt,
        "target": p["target"],
        "plan": plan or p["plan"],
        "release": p["release"],
        "experiment": p["experiment"],
        "config": p["config"],
        "upstream_paths": upstream,
        "artifact_roots": p["roots"],
    }
    parameters = inspect.signature(verify_development_example_backtest_artifact).parameters
    assert plan_bundle
    return verify_development_example_backtest_artifact(
        **{name: value for name, value in kwargs.items() if name in parameters}
    )


def _read_metric(root: Path, scenario: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((root / scenario / "metrics.json").read_bytes()))


def test_public_contracts_and_three_scenario_tree_are_exact(reporting_bundle: Any) -> None:
    bundle = reporting_bundle
    verified = _verify(bundle)
    _, p, _, root, receipt, manifest = bundle
    assert isinstance(verified, VerifiedDevelopmentExampleBacktestArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.example_id == p["target"].example_id
    assert type(verified.metrics) is BacktestMetricsV1
    assert type(verified.manifest) is BacktestBundleManifestV1
    assert tuple(item.scenario for item in verified.metrics.scenarios) == _SCENARIOS
    assert tuple(item.multiplier for item in verified.metrics.scenarios) == _MULTIPLIERS
    assert tuple(name for name, _ in manifest.scenario_manifest_sha256s) == _SCENARIOS
    assert {path.name for path in root.iterdir() if path.is_dir()} == set(_SCENARIOS)
    assert {path.name for path in root.iterdir() if path.is_file()} == {
        "backtest_metrics.json", "backtest_manifest.json"
    }
    for scenario in _SCENARIOS:
        assert {path.name for path in (root / scenario).iterdir()} == {
            *_TABLES, "metrics.json", "manifest.json"
        }
    assert len(json.loads(receipt.read_bytes())["inputs"]) == 21
    assert len(json.loads(receipt.read_bytes())["outputs"]) == 29


def test_scenario_metrics_match_frozen_formulas_and_510300_benchmark(
    reporting_bundle: Any,
) -> None:
    _, p, _, root, _, _ = reporting_bundle
    initial_cash = float(p["config"].section("backtest")["a_share"]["initial_cash"])
    annualization = int(p["config"].section("backtest")["a_share"]["annualization_sessions"])
    benchmark = p["release"].artifact_paths
    benchmark_frame = pl.read_parquet(dict(benchmark)["benchmark_bar_1d.parquet"]).filter(
        pl.col("benchmark") == "510300.SH"
    )
    first = p["plan"].manifest.window.first_execution_date
    terminal = p["plan"].manifest.window.terminal_valuation_date
    benchmark_return = (
        benchmark_frame.filter(pl.col("trade_date") == terminal).item(0, "close")
        / benchmark_frame.filter(pl.col("trade_date") == first).item(0, "open")
        - 1.0
    )
    for scenario in _SCENARIOS:
        metrics = _read_metric(root, scenario)
        nav = pl.read_parquet(root / scenario / "nav.parquet")
        trades = pl.read_parquet(root / scenario / "trades.parquet")
        rejections = pl.read_parquet(root / scenario / "rejections.parquet")
        postings = pl.read_parquet(root / scenario / "corporate_action_postings.parquet")
        terminal_equity = nav.tail(1).item(0, "equity")
        portfolio_return = terminal_equity / initial_cash - 1.0
        expected_annualized = -1.0 if terminal_equity == 0 else (
            (1.0 + portfolio_return) ** (annualization / nav.height) - 1.0
        )
        assert metrics["terminal_equity"] == terminal_equity
        assert metrics["portfolio_return"] == portfolio_return
        assert metrics["annualized_return"] == expected_annualized
        assert metrics["benchmark_return"] == benchmark_return
        assert metrics["test_net_excess_return"] == portfolio_return - benchmark_return
        assert metrics["relative_wealth"] == (
            (1.0 + portfolio_return) / (1.0 + benchmark_return) - 1.0
        )
        assert metrics["commission_total"] == trades.get_column("commission").sum()
        assert metrics["stamp_tax_total"] == trades.get_column("stamp_tax").sum()
        assert metrics["transfer_fee_total"] == trades.get_column("transfer_fee").sum()
        assert metrics["total_fees"] == sum(
            metrics[name] for name in ("commission_total", "stamp_tax_total", "transfer_fee_total")
        )
        assert metrics["total_trading_cost"] == metrics["total_fees"] + metrics["slippage_cost_total"]
        assert metrics["unfilled_notional"] == rejections.get_column("rejected_notional").sum()
        assert metrics["unexecutable_date_count"] == rejections.get_column("date").n_unique()
        assert metrics["corporate_action_posting_count"] == postings.height
        assert math.isfinite(metrics["average_cash_ratio"])


def test_scenarios_are_independent_fixed_order_and_share_market_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    p = _parts(plan_bundle)
    calls: list[tuple[Decimal, int, int, tuple[Any, ...]]] = []
    real = reporting_module.simulate_a_share_scenario

    def traced(**kwargs: Any) -> Any:
        result = real(**kwargs)
        calls.append((
            kwargs["multiplier"], id(kwargs["facts"]), id(result),
            tuple(kwargs["cost_periods"]),
        ))
        return result

    monkeypatch.setattr(reporting_module, "simulate_a_share_scenario", traced)
    root = cast(Path, p["common"]) / "development-example-backtest-call-trace"
    root.mkdir()
    manifest = build_development_example_backtest_artifact(
        target=p["target"], plan=p["plan"], release=p["release"],
        experiment=p["experiment"], config=p["config"], output_root=root,
    )
    assert tuple(item[0] for item in calls) == (
        Decimal("0.5"), Decimal("1"), Decimal("2")
    )
    assert len({item[1] for item in calls}) == 1
    assert len({item[2] for item in calls}) == 3
    assert calls[0][3] == calls[1][3] == calls[2][3]
    assert all(
        period.stamp_tax_sell in {Decimal("0.001"), Decimal("0.0005")}
        and period.transfer_fee in {Decimal("0.00002"), Decimal("0.00001")}
        for period in calls[0][3]
    )
    scenario_manifests = [
        json.loads((root / name / "manifest.json").read_bytes()) for name in _SCENARIOS
    ]
    assert len({item["input_market_facts_sha256"] for item in scenario_manifests}) == 1
    assert all(
        item["order_quantity_rule_version"] == "sse_szse_limit_order_quantity_v1"
        for item in scenario_manifests
    )
    assert manifest.order_quantity_rule_version == "sse_szse_limit_order_quantity_v1"


def test_build_is_deterministic_and_no_clobber(reporting_bundle: Any) -> None:
    _, p, _, root, _, _ = reporting_bundle
    second = root.parent / "development-example-backtest-deterministic-copy"
    second.mkdir()
    build_development_example_backtest_artifact(
        target=p["target"], plan=p["plan"], release=p["release"],
        experiment=p["experiment"], config=p["config"], output_root=second,
    )
    left = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    right = {path.relative_to(second).as_posix(): path.read_bytes() for path in second.rglob("*") if path.is_file()}
    assert left == right
    with pytest.raises(ValueError):
        build_development_example_backtest_artifact(
            target=p["target"], plan=p["plan"], release=p["release"],
            experiment=p["experiment"], config=p["config"], output_root=root,
        )
    assert {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()} == left


def test_verifier_rejects_missing_or_tampered_any_declared_file(reporting_bundle: Any) -> None:
    bundle = reporting_bundle
    root = cast(Path, bundle[3])
    for path in (root / "0p5x" / "nav.parquet", root / "1p0x" / "metrics.json", root / "2p0x" / "manifest.json", root / "backtest_metrics.json", root / "backtest_manifest.json"):
        raw = path.read_bytes()
        path.write_bytes(raw + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        path.write_bytes(raw)
        _verify(bundle)
    missing = root / "2p0x" / "entitlements.parquet"
    raw = missing.read_bytes()
    missing.unlink()
    with pytest.raises(ValueError):
        _verify(bundle)
    missing.write_bytes(raw)
    _verify(bundle)


def test_verifier_rejects_identity_or_order_rule_mix(reporting_bundle: Any) -> None:
    bundle = reporting_bundle
    plan = bundle[1]["plan"]
    with pytest.raises(ValueError):
        _verify(bundle, plan=replace(plan, example_id="development-example-" + "f" * 64))
    with pytest.raises(ValueError):
        replace(
            plan.manifest,
            order_quantity_rule_version="future-rule",  # type: ignore[arg-type]
        )


def test_reporting_contract_types_and_signature_are_closed() -> None:
    assert all(item is not None for item in (
        AShareScenarioMetricsV1, BacktestMetricsV1, BacktestArtifactEntryV1,
        BacktestScenarioManifestV1, BacktestBundleManifestV1,
    ))
    build_parameters = inspect.signature(build_development_example_backtest_artifact).parameters
    assert tuple(build_parameters) == (
        "target", "plan", "release", "experiment", "config", "output_root"
    )
    assert all(item.kind is inspect.Parameter.KEYWORD_ONLY for item in build_parameters.values())
    forbidden = {"multiplier", "cost_periods", "metrics", "market_facts_sha256"}
    assert forbidden.isdisjoint(build_parameters)
    assert importlib.import_module("quant.backtest.a_share_reporting") is reporting_module
