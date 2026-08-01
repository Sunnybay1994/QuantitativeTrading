"""Immutable three-scenario A-share backtest artifact for M3 G7F."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.backtest.a_share_execution import (
    build_a_share_market_facts,
    compute_a_share_fee_components,
)
from quant.backtest.a_share_plan import G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
from quant.backtest.a_share_simulator import AShareSimulationResult, simulate_a_share_scenario
from quant.domain import OrderSide
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AShareCostPeriod,
    AShareScenarioMetricsV1,
    BacktestArtifactEntryV1,
    BacktestBundleManifestV1,
    BacktestMetricsV1,
    BacktestScenarioManifestV1,
    ScenarioName,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestArtifact,
    VerifiedDevelopmentExampleBacktestPlanArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleTargetArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_SCENARIOS: tuple[tuple[ScenarioName, Decimal], ...] = (
    ("0p5x", Decimal("0.5")),
    ("1p0x", Decimal("1")),
    ("2p0x", Decimal("2")),
)
_TABLES = (
    ("corporate_action_postings.parquet", "corporate_action_postings", "AShareCorporateActionPostingSchema"),
    ("daily_diagnostics.parquet", "daily_diagnostics", "AShareDailyDiagnosticsSchema"),
    ("entitlements.parquet", "entitlements", "AShareEntitlementSnapshotSchema"),
    ("nav.parquet", "nav", "AShareSimulationNavSchema"),
    ("positions.parquet", "positions", "AShareSimulationPositionSchema"),
    ("rejections.parquet", "rejections", "AShareSimulationRejectionSchema"),
    ("trades.parquet", "trades", "AShareSimulationTradeSchema"),
)
_SCENARIO_FILES = {name for name, _, _ in _TABLES} | {"metrics.json", "manifest.json"}
_ROOT_FILES = {"backtest_metrics.json", "backtest_manifest.json"}
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _reporting_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_A_SHARE_BACKTEST_ARTIFACT_INVALID") from None
    return wrapped


@dataclass(frozen=True)
class BacktestArtifactUpstreamPaths:
    target_receipt_path: Path
    plan_receipt_path: Path
    experiment_receipt_path: Path
    g1_receipt_path: Path

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(not isinstance(path, Path) for path in values) or len(set(values)) != 4:
            raise ValueError("backtest upstream receipt paths invalid")


@_reporting_boundary
def build_development_example_backtest_artifact(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    output_root: Path,
) -> BacktestBundleManifestV1:
    """Build three independent development-only scenario replays."""
    _validate_inputs(target, plan, release, experiment, config)
    _require_empty_development_directory(output_root)
    facts = build_a_share_market_facts(release=release, plan=plan)
    initial_cash = Decimal(str(config.section("backtest")["a_share"]["initial_cash"]))  # type: ignore[index]
    annualization = cast(int, config.section("backtest")["a_share"]["annualization_sessions"])  # type: ignore[index]
    manifests: list[tuple[str, str]] = []
    metrics: list[AShareScenarioMetricsV1] = []
    base_periods = _cost_periods(config, Decimal("1"))
    for scenario, multiplier in _SCENARIOS:
        scenario_root = output_root / scenario
        scenario_root.mkdir()
        periods = _cost_periods(config, multiplier)
        result = simulate_a_share_scenario(
            target=target,
            plan=plan,
            facts=facts,
            cost_periods=base_periods,
            multiplier=multiplier,
            initial_cash=initial_cash,
        )
        for filename, attribute, _ in _TABLES:
            _write_parquet(cast(pl.DataFrame, getattr(result, attribute)), scenario_root / filename)
        scenario_metrics = _scenario_metrics(
            target=target,
            plan=plan,
            facts=facts,
            result=result,
            base_periods=base_periods,
            scenario=scenario,
            initial_cash=initial_cash,
            annualization_sessions=annualization,
        )
        metrics_raw = _canonical_bytes(asdict(scenario_metrics))
        _write_exclusive(scenario_root / "metrics.json", metrics_raw)
        scenario_manifest = _scenario_manifest(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            facts_sha256=facts.identity.input_market_facts_sha256,
            scenario=scenario,
            multiplier=multiplier,
            periods=periods,
            scenario_root=scenario_root,
            metrics_raw=metrics_raw,
        )
        manifest_raw = _canonical_bytes(asdict(scenario_manifest))
        _write_exclusive(scenario_root / "manifest.json", manifest_raw)
        manifests.append((scenario, hashlib.sha256(manifest_raw).hexdigest()))
        metrics.append(scenario_metrics)
    bundle_metrics = BacktestMetricsV1(
        schema_version="m3-a-share-backtest-metrics-v1",
        experiment_key=experiment.manifest.experiment_key,
        work_key=target.manifest.work_key,
        scenarios=tuple(metrics),
    )
    metrics_raw = _canonical_bytes(asdict(bundle_metrics))
    _write_exclusive(output_root / "backtest_metrics.json", metrics_raw)
    manifest = BacktestBundleManifestV1(
        schema_version="m3-a-share-backtest-bundle-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        scientific_config_sha256=config.scientific_config_sha256,
        target_manifest_sha256=target.manifest_sha256,
        backtest_plan_manifest_sha256=plan.manifest_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scenario_manifest_sha256s=tuple(manifests),
        common_target_manifest_sha256=target.manifest_sha256,
        common_market_facts_sha256=facts.identity.input_market_facts_sha256,
        backtest_metrics_sha256=hashlib.sha256(metrics_raw).hexdigest(),
    )
    _write_exclusive(output_root / "backtest_manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_reporting_boundary
def verify_development_example_backtest_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    upstream_paths: BacktestArtifactUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleBacktestArtifact:
    """Re-run all ledgers and verify bytes, tree closure, identity and receipt."""
    _validate_inputs(target, plan, release, experiment, config)
    _validate_upstream_receipts(target, plan, release, experiment, upstream_paths)
    _validate_tree(root)
    facts = build_a_share_market_facts(release=release, plan=plan)
    initial_cash = Decimal(str(config.section("backtest")["a_share"]["initial_cash"]))  # type: ignore[index]
    annualization = cast(int, config.section("backtest")["a_share"]["annualization_sessions"])  # type: ignore[index]
    expected_scenario_hashes: list[tuple[str, str]] = []
    expected_metrics: list[AShareScenarioMetricsV1] = []
    base_periods = _cost_periods(config, Decimal("1"))
    for scenario, multiplier in _SCENARIOS:
        scenario_root = root / scenario
        periods = _cost_periods(config, multiplier)
        result = simulate_a_share_scenario(
            target=target,
            plan=plan,
            facts=facts,
            cost_periods=base_periods,
            multiplier=multiplier,
            initial_cash=initial_cash,
        )
        for filename, attribute, _ in _TABLES:
            actual = pl.read_parquet(scenario_root / filename)
            if not actual.equals(cast(pl.DataFrame, getattr(result, attribute))):
                raise ValueError("backtest scenario table drift")
        metrics = _scenario_metrics(
            target=target,
            plan=plan,
            facts=facts,
            result=result,
            base_periods=base_periods,
            scenario=scenario,
            initial_cash=initial_cash,
            annualization_sessions=annualization,
        )
        metrics_raw = (scenario_root / "metrics.json").read_bytes()
        if metrics_raw != _canonical_bytes(asdict(metrics)):
            raise ValueError("backtest scenario metrics drift")
        scenario_manifest = read_backtest_scenario_manifest(scenario_root / "manifest.json")
        expected_scenario_manifest = _scenario_manifest(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            facts_sha256=facts.identity.input_market_facts_sha256,
            scenario=scenario,
            multiplier=multiplier,
            periods=periods,
            scenario_root=scenario_root,
            metrics_raw=metrics_raw,
        )
        if scenario_manifest != expected_scenario_manifest:
            raise ValueError("backtest scenario manifest drift")
        expected_scenario_hashes.append((scenario, _file_sha(scenario_root / "manifest.json")))
        expected_metrics.append(metrics)
    bundle_metrics = BacktestMetricsV1(
        schema_version="m3-a-share-backtest-metrics-v1",
        experiment_key=experiment.manifest.experiment_key,
        work_key=target.manifest.work_key,
        scenarios=tuple(expected_metrics),
    )
    metrics_raw = (root / "backtest_metrics.json").read_bytes()
    if metrics_raw != _canonical_bytes(asdict(bundle_metrics)):
        raise ValueError("backtest bundle metrics drift")
    manifest_raw = (root / "backtest_manifest.json").read_bytes()
    manifest = read_backtest_bundle_manifest(root / "backtest_manifest.json")
    expected_manifest = BacktestBundleManifestV1(
        schema_version="m3-a-share-backtest-bundle-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        scientific_config_sha256=config.scientific_config_sha256,
        target_manifest_sha256=target.manifest_sha256,
        backtest_plan_manifest_sha256=plan.manifest_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scenario_manifest_sha256s=tuple(expected_scenario_hashes),
        common_target_manifest_sha256=target.manifest_sha256,
        common_market_facts_sha256=facts.identity.input_market_facts_sha256,
        backtest_metrics_sha256=hashlib.sha256(metrics_raw).hexdigest(),
    )
    if manifest != expected_manifest or manifest_raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("backtest bundle manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("backtest receipt missing")
    receipt = verified_receipt.receipt
    if (
        receipt.stage != "development-backtest"
        or receipt.scope != "WORK"
        or receipt.scope_key != target.manifest.work_key
        or not _digest_paths_equal(
            receipt.inputs,
            _receipt_inputs(target, plan, release, experiment, upstream_paths),
            artifact_roots,
        )
        or not _digest_paths_equal(receipt.outputs, _output_paths(root), artifact_roots)
    ):
        raise ValueError("backtest receipt closure drift")
    return VerifiedDevelopmentExampleBacktestArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=target.example_id,
        root=root,
        metrics=bundle_metrics,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        backtest_receipt_sha256=verified_receipt.sha256,
    )


def read_backtest_scenario_manifest(path: Path) -> BacktestScenarioManifestV1:
    payload, raw = _strict_object(path)
    if set(payload) != {field.name for field in fields(BacktestScenarioManifestV1)}:
        raise ValueError("backtest scenario manifest fields drift")
    entries = payload.get("output_files")
    if type(entries) is not list:
        raise ValueError("backtest scenario output files invalid")
    payload["output_files"] = tuple(
        BacktestArtifactEntryV1(**cast(Any, item)) for item in entries
    )
    manifest = BacktestScenarioManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("backtest scenario manifest non-canonical")
    return manifest


def read_backtest_bundle_manifest(path: Path) -> BacktestBundleManifestV1:
    payload, raw = _strict_object(path)
    if set(payload) != {field.name for field in fields(BacktestBundleManifestV1)}:
        raise ValueError("backtest bundle manifest fields drift")
    pairs = payload.get("scenario_manifest_sha256s")
    if type(pairs) is not list or any(type(item) is not list or len(item) != 2 for item in pairs):
        raise ValueError("backtest bundle scenario hashes invalid")
    payload["scenario_manifest_sha256s"] = tuple(
        (cast(str, item[0]), cast(str, item[1])) for item in pairs
    )
    manifest = BacktestBundleManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("backtest bundle manifest non-canonical")
    return manifest


def _validate_inputs(
    target: object, plan: object, release: object, experiment: object, config: object
) -> None:
    if (
        type(target) is not VerifiedDevelopmentExampleTargetArtifact
        or type(plan) is not VerifiedDevelopmentExampleBacktestPlanArtifact
        or type(release) is not VerifiedDevelopmentExampleG1Release
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or type(config) is not LoadedM3Config
    ):
        raise ValueError("backtest inputs invalid")
    assert isinstance(target, VerifiedDevelopmentExampleTargetArtifact)
    assert isinstance(plan, VerifiedDevelopmentExampleBacktestPlanArtifact)
    assert isinstance(release, VerifiedDevelopmentExampleG1Release)
    assert isinstance(experiment, VerifiedDevelopmentExampleExperimentIdentity)
    assert isinstance(config, LoadedM3Config)
    if (
        len({target.example_id, plan.example_id, experiment.example_id}) != 1
        or target.example_id != release.manifest.example_id
        or target.manifest.experiment_key != experiment.manifest.experiment_key
        or plan.manifest.experiment_key != experiment.manifest.experiment_key
        or experiment.manifest.scientific_config_sha256 != config.scientific_config_sha256
        or target.manifest_sha256 != plan.manifest.target_manifest_sha256
        or release.manifest.release_id != plan.manifest.g1_release_id
        or release.manifest_sha256 != plan.manifest.g1_release_manifest_sha256
        or plan.manifest.order_quantity_rule_version != G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
    ):
        raise ValueError("backtest input identity mismatch")
    section = cast(Mapping[str, object], config.section("backtest")["a_share"])
    if tuple(cast(Sequence[object], section["friction_multipliers"])) != (0.5, 1.0, 2.0):
        raise ValueError("backtest scenario multipliers drift")


def _cost_periods(config: LoadedM3Config, multiplier: Decimal) -> tuple[AShareCostPeriod, ...]:
    costs = config.section("costs")
    if tuple(cast(Sequence[str], costs["scaled_components"])) != (
        "commission_rate", "commission_min", "slippage"
    ):
        raise ValueError("backtest scaled cost components drift")
    raw = cast(Sequence[Mapping[str, object]], costs["a_share_periods"])
    return tuple(
        AShareCostPeriod(
            effective_from=cast(dt.date, item["effective_from"]),
            effective_to=cast(dt.date | None, item.get("effective_to")),
            commission_rate=Decimal(str(item["commission_rate"])) * multiplier,
            commission_min=Decimal(str(item["commission_min"])) * multiplier,
            stamp_tax_sell=Decimal(str(item["stamp_tax_sell"])),
            transfer_fee=Decimal(str(item["transfer_fee"])),
            slippage=Decimal(str(item["slippage"])) * multiplier,
        )
        for item in raw
    )


def _scenario_metrics(
    *, target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    facts: Any,
    result: AShareSimulationResult,
    base_periods: tuple[AShareCostPeriod, ...],
    scenario: ScenarioName,
    initial_cash: Decimal,
    annualization_sessions: int,
) -> AShareScenarioMetricsV1:
    nav = result.nav
    terminal_equity_value = float(nav.item(-1, "equity"))
    initial_cash_value = float(initial_cash)
    portfolio_return_value = terminal_equity_value / initial_cash_value - 1.0
    annualized_value = -1.0 if terminal_equity_value == 0.0 else (
        math.pow(1.0 + portfolio_return_value, annualization_sessions / nav.height) - 1.0
    )
    values = [Decimal("1"), *(Decimal(str(value)) for value in nav["unit_nav"].to_list())]
    peak = values[0]
    max_drawdown = Decimal(0)
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    benchmark = facts.benchmark_bars.filter(
        (pl.col("benchmark") == "510300.SH")
        & pl.col("trade_date").is_in(list(plan.manifest.window.execution_dates))
    ).sort("trade_date")
    if benchmark.height != nav.height:
        raise ValueError("backtest benchmark window incomplete")
    benchmark_return_value = (
        float(benchmark.item(-1, "close")) / float(benchmark.item(0, "open")) - 1.0
    )
    relative_wealth_value = (
        (1.0 + portfolio_return_value) / (1.0 + benchmark_return_value) - 1.0
    )
    target_gross = _target_turnover(plan.scheduled_targets)
    realized_gross = sum(
        (Decimal(str(value)) for value in result.daily_diagnostics["gross_turnover"].to_list()),
        Decimal(0),
    )
    one_way = sum(
        (Decimal(str(value)) for value in result.daily_diagnostics["one_way_turnover"].to_list()),
        Decimal(0),
    )
    commission_value = float(result.trades["commission"].sum() or 0.0)
    stamp_value = float(result.trades["stamp_tax"].sum() or 0.0)
    transfer_value = float(result.trades["transfer_fee"].sum() or 0.0)
    slippage_value = float(result.trades["slippage_cost"].sum() or 0.0)
    fees_value = commission_value + stamp_value + transfer_value
    requested = int(result.daily_diagnostics["n_order_intents"].sum())
    rejected = result.rejections.height
    terminal_date = plan.manifest.window.terminal_valuation_date
    terminal_positions = result.positions.filter(pl.col("date") == terminal_date)
    terminal_value = sum(
        (Decimal(str(value)) for value in terminal_positions["market_value"].to_list()), Decimal(0)
    )
    pending_value = sum(
        (
            Decimal(str(value))
            for value in terminal_positions.filter(pl.col("pending_exit"))["market_value"].to_list()
        ),
        Decimal(0),
    )
    base = _period_for_date(terminal_date, base_periods)
    exit_cost = Decimal(0)
    for row in terminal_positions.iter_rows(named=True):
        notional = Decimal(str(row["market_value"]))
        fee = compute_a_share_fee_components(
            notional=notional, side=OrderSide.SELL, cost_period=base
        )
        exit_cost += fee.commission + fee.stamp_tax + fee.transfer_fee + notional * base.slippage
    rounding_delta = sum(
        (Decimal(str(value)) for value in result.corporate_action_postings["cash_rounding_delta"].to_list()),
        Decimal(0),
    )
    average_cash_ratio = sum(
        (
            Decimal(str(row["cash"])) / Decimal(str(row["equity"]))
            for row in nav.iter_rows(named=True)
        ),
        Decimal(0),
    ) / nav.height
    return AShareScenarioMetricsV1(
        schema_version="m3-a-share-scenario-metrics-v1",
        experiment_key=target.manifest.experiment_key,
        work_key=target.manifest.work_key,
        scenario=scenario,
        multiplier=float(result.multiplier),
        n_sessions=nav.height,
        initial_cash=float(initial_cash),
        terminal_equity=terminal_equity_value,
        portfolio_return=portfolio_return_value,
        annualized_return=annualized_value,
        test_max_drawdown=float(max_drawdown),
        benchmark_return=benchmark_return_value,
        test_net_excess_return=portfolio_return_value - benchmark_return_value,
        relative_wealth=relative_wealth_value,
        target_gross_turnover=float(target_gross),
        target_one_way_turnover=float(target_gross / 2),
        realized_gross_turnover=float(realized_gross),
        test_turnover=float(one_way),
        commission_total=commission_value,
        stamp_tax_total=stamp_value,
        transfer_fee_total=transfer_value,
        total_fees=fees_value,
        slippage_cost_total=slippage_value,
        total_trading_cost=fees_value + slippage_value,
        cash_rounding_delta_total=float(rounding_delta),
        requested_order_count=requested,
        rejection_count=rejected,
        rejection_rate=None if requested == 0 else float(Decimal(rejected) / Decimal(requested)),
        unfilled_notional=float(sum(
            (Decimal(str(value)) for value in result.rejections["rejected_notional"].to_list()),
            Decimal(0),
        )),
        average_cash_ratio=float(average_cash_ratio),
        corporate_action_posting_count=result.corporate_action_postings.height,
        unexecutable_date_count=result.rejections["date"].n_unique(),
        terminal_positions_market_value=float(terminal_value),
        terminal_pending_exit_value=float(pending_value),
        terminal_estimated_exit_cost_1x=float(exit_cost),
    )


def _target_turnover(scheduled: pl.DataFrame) -> Decimal:
    previous: dict[str, Decimal] = {}
    gross = Decimal(0)
    for date in sorted(cast(list[dt.date], scheduled["execution_date"].unique().to_list())):
        current = {
            cast(str, row["symbol"]): Decimal(str(row["weight"]))
            for row in scheduled.filter(pl.col("execution_date") == date).iter_rows(named=True)
        }
        gross += sum(
            (abs(current.get(symbol, Decimal(0)) - previous.get(symbol, Decimal(0)))
             for symbol in current.keys() | previous.keys()),
            Decimal(0),
        )
        previous = current
    return gross


def _scenario_manifest(
    *, target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    facts_sha256: str,
    scenario: ScenarioName,
    multiplier: Decimal,
    periods: tuple[AShareCostPeriod, ...],
    scenario_root: Path,
    metrics_raw: bytes,
) -> BacktestScenarioManifestV1:
    entries = [
        BacktestArtifactEntryV1(
            path=filename,
            sha256=_file_sha(scenario_root / filename),
            size_bytes=(scenario_root / filename).stat().st_size,
            row_count=pl.read_parquet(scenario_root / filename).height,
            schema_name=schema,
        )
        for filename, _, schema in _TABLES
    ]
    entries.append(BacktestArtifactEntryV1(
        path="metrics.json", sha256=hashlib.sha256(metrics_raw).hexdigest(),
        size_bytes=len(metrics_raw), row_count=None, schema_name="AShareScenarioMetricsV1",
    ))
    return BacktestScenarioManifestV1(
        schema_version="m3-a-share-scenario-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        scientific_config_sha256=config.scientific_config_sha256,
        target_manifest_sha256=target.manifest_sha256,
        backtest_plan_manifest_sha256=plan.manifest_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        fold=target.manifest.fold,
        horizon_sessions=target.manifest.horizon_sessions,
        scenario=scenario,
        multiplier=float(multiplier),
        cost_periods_sha256=hashlib.sha256(_canonical_bytes([asdict(x) for x in periods])).hexdigest(),
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        input_market_facts_sha256=facts_sha256,
        output_files=tuple(sorted(entries, key=lambda item: item.path)),
        metrics_sha256=hashlib.sha256(metrics_raw).hexdigest(),
    )


def _receipt_inputs(
    target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestArtifactUpstreamPaths,
) -> tuple[Path, ...]:
    source = dict(release.artifact_paths)
    return (
        target.root / "target_manifest.json",
        paths.target_receipt_path,
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
        plan.root / "manifest.json",
        paths.plan_receipt_path,
        plan.root / "scheduled_targets.parquet",
        plan.root / "schedule_diagnostics.parquet",
        plan.root / "cost_schedule.json",
        experiment.root / "experiment_manifest.json",
        paths.experiment_receipt_path,
        release.release.manifest_path,
        paths.g1_receipt_path,
        *(source[name] for name in sorted(source) if name in {
            "bar_1d.parquet", "benchmark_bar_1d.parquet",
            "corporate_action_ledger.parquet", "corporate_action_reconciliation.parquet",
            "instrument.parquet", "price_limit_1d.parquet", "suspension_1d.parquet",
            "trade_calendar.parquet",
        }),
    )


def _validate_upstream_receipts(
    target: VerifiedDevelopmentExampleTargetArtifact,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestArtifactUpstreamPaths,
) -> None:
    expected = (
        (paths.target_receipt_path, target.target_receipt_sha256),
        (paths.plan_receipt_path, plan.plan_receipt_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
        (paths.g1_receipt_path, release.receipt_sha256),
    )
    if paths.g1_receipt_path.resolve(strict=True) != (
        release.release.root / "receipt.json"
    ).resolve(strict=True):
        raise ValueError("backtest G1 receipt path mismatch")
    for path, sha256 in expected:
        if _file_sha(path) != sha256:
            raise ValueError("backtest upstream receipt digest drift")


def _output_paths(root: Path) -> tuple[Path, ...]:
    paths = [root / name for name in sorted(_ROOT_FILES)]
    for scenario, _ in _SCENARIOS:
        paths.extend(root / scenario / name for name in sorted(_SCENARIO_FILES))
    return tuple(paths)


def _validate_tree(root: Path) -> None:
    if not root.is_dir() or root.is_symlink() or {entry.name for entry in os.scandir(root)} != (
        _ROOT_FILES | {name for name, _ in _SCENARIOS}
    ):
        raise ValueError("backtest tree closure drift")
    for scenario, _ in _SCENARIOS:
        child = root / scenario
        if child.is_symlink() or not child.is_dir() or {entry.name for entry in os.scandir(child)} != _SCENARIO_FILES:
            raise ValueError("backtest scenario tree closure drift")


def _period_for_date(date: dt.date, periods: tuple[AShareCostPeriod, ...]) -> AShareCostPeriod:
    matches = tuple(
        item for item in periods
        if item.effective_from <= date and (item.effective_to is None or date <= item.effective_to)
    )
    if len(matches) != 1:
        raise ValueError("backtest terminal cost period missing")
    return matches[0]


def _strict_object(path: Path) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value, raw


def _canonical_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if type(item) is Decimal:
            return format(item, "f")
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item
    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _require_empty_development_directory(path: Path) -> None:
    tokens = path.name.lower().replace("_", "-").split("-")
    if (
        not path.is_dir() or path.is_symlink() or any(path.iterdir())
        or "development" not in tokens or "example" not in tokens
    ):
        raise ValueError("backtest output must be an empty development example directory")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...], paths: Sequence[Path], roots: Mapping[str, Path]
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(
        os.path.normcase(os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots)))
        for item in digests
    ))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


__all__ = [
    "BacktestArtifactUpstreamPaths",
    "build_development_example_backtest_artifact",
    "read_backtest_bundle_manifest",
    "read_backtest_scenario_manifest",
    "verify_development_example_backtest_artifact",
]
