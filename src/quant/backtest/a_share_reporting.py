"""Immutable three-scenario A-share backtest artifact for M3 G7F."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from decimal import Context, Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.backtest.a_share_execution import (
    AShareMarketFactsFreshVerificationContext,
    FormalAShareMarketFactsIdentityV1,
    VerifiedAShareMarketFacts,
    build_a_share_market_facts,
    compute_a_share_fee_components,
    load_verified_a_share_market_facts,
)
from quant.backtest.a_share_plan import (
    G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
    verify_backtest_plan_artifact,
)
from quant.backtest.a_share_simulator import (
    AShareSimulationFreshVerificationContext,
    AShareSimulationResult,
    simulate_a_share_scenario,
    simulate_formal_a_share_scenarios,
)
from quant.data.m3_release import (
    G1ManifestV5,
    G1QualityReportV1,
    G1Release,
    VerifiedG1Release,
)
from quant.domain import OrderSide
from quant.domain import (
    AShareCorporateActionPostingSchema,
    AShareDailyDiagnosticsSchema,
    AShareEntitlementSnapshotSchema,
    AShareSimulationNavSchema,
    AShareSimulationPositionSchema,
    AShareSimulationRejectionSchema,
    AShareSimulationTradeSchema,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AShareCostPeriod,
    AShareScenarioMetricsV1,
    BacktestArtifactEntryV1,
    BacktestBundleManifestV1,
    BacktestMetricsV1,
    BacktestScenarioManifestV1,
    ScenarioName,
    VerifiedBacktestArtifact,
    VerifiedBacktestPlanArtifact,
    VerifiedExperimentIdentity,
    VerifiedTargetArtifact,
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
    select_artifact_root,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactRollbackError,
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
    """Development-only four-path upstream receipts, including G1 receipt."""

    target_receipt_path: Path
    plan_receipt_path: Path
    experiment_receipt_path: Path
    g1_receipt_path: Path

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(not isinstance(path, Path) for path in values) or len(set(values)) != 4:
            raise ValueError("backtest upstream receipt paths invalid")


@dataclass(frozen=True)
class FormalBacktestArtifactUpstreamPaths:
    """Formal three-path upstream receipts; G1 quality is derived from release."""

    target_receipt_path: Path
    plan_receipt_path: Path
    experiment_receipt_path: Path

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(not isinstance(path, Path) for path in values) or len(set(values)) != 3:
            raise ValueError("formal backtest upstream receipt paths invalid")


_FORMAL_ERROR = "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID"
_FORMAL_ROLLBACK_ERROR = "M3_A_SHARE_BACKTEST_ARTIFACT_ROLLBACK_FAILED"
_FORMAL_EXPECTED_NAMES = frozenset(
    {
        *(f"{scenario}/{name}" for scenario, _ in _SCENARIOS for name in _SCENARIO_FILES),
        *_ROOT_FILES,
    }
)
_FORMAL_TABLE_SCHEMAS: Mapping[str, type[Any]] = {
    "corporate_action_postings": AShareCorporateActionPostingSchema,
    "daily_diagnostics": AShareDailyDiagnosticsSchema,
    "entitlements": AShareEntitlementSnapshotSchema,
    "nav": AShareSimulationNavSchema,
    "positions": AShareSimulationPositionSchema,
    "rejections": AShareSimulationRejectionSchema,
    "trades": AShareSimulationTradeSchema,
}


def _formal_decimal_context() -> Context:
    context = Context(
        prec=80,
        rounding=ROUND_HALF_UP,
        Emax=999999,
        Emin=-999999,
        capitals=1,
        clamp=0,
    )
    context.clear_flags()
    for signal in context.traps:
        context.traps[signal] = False
    return context


_FORMAL_DECIMAL_CONTEXT = _formal_decimal_context()


class AShareBacktestArtifactError(ValueError):
    """Stable formal A-share backtest artifact contract error."""


@dataclass(frozen=True)
class _FormalG1SourceEntitySnapshot:
    """Process-local G1 root/manifest/quality/eight-table file entities."""

    root: _FormalFileEntity
    manifest: _FormalFileEntity
    quality: _FormalFileEntity
    market_tables: tuple[tuple[str, _FormalFileEntity], ...]


@dataclass(frozen=True)
class BacktestArtifactFreshVerificationContext:
    facts_fresh_context: AShareMarketFactsFreshVerificationContext
    upstream_paths: FormalBacktestArtifactUpstreamPaths
    release: VerifiedG1Release
    _source_snapshot: _FormalG1SourceEntitySnapshot = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            type(self.facts_fresh_context)
            is not AShareMarketFactsFreshVerificationContext
            or type(self.upstream_paths) is not FormalBacktestArtifactUpstreamPaths
            or type(self.release) is not VerifiedG1Release
        ):
            raise AShareBacktestArtifactError(_FORMAL_ERROR)
        try:
            snapshot = _capture_formal_g1_source_snapshot(self.release)
        except Exception:
            raise AShareBacktestArtifactError(_FORMAL_ERROR) from None
        object.__setattr__(self, "_source_snapshot", snapshot)

    def __reduce__(self) -> Any:
        raise TypeError(_FORMAL_ERROR)


def _raise_formal(message: str) -> Any:
    raise AShareBacktestArtifactError(message) from None


def build_backtest_artifact(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> BacktestBundleManifestV1:
    """Build one formal three-scenario A-share artifact transaction."""
    if not isinstance(output_root, Path):
        return cast(BacktestBundleManifestV1, _raise_formal(_FORMAL_ERROR))
    try:
        with localcontext(_FORMAL_DECIMAL_CONTEXT):
            with ArtifactPublication(output_root) as publication:
                select_artifact_root(output_root, artifact_roots=artifact_roots)
                expected_names = backtest_artifact_output_relative_paths()
                bundle = _formal_bundle(
                    target=target,
                    plan=plan,
                    release=release,
                    experiment=experiment,
                    config=config,
                    fresh_context=fresh_context,
                    artifact_roots=artifact_roots,
                )
                for name in expected_names:
                    raw = bundle.raw_files[name]
                    publication.write_bytes(name, raw)
                    readback = publication.read_bytes(name)
                    if readback != raw:
                        raise ValueError
                    _validate_formal_readback(name, readback, bundle)
                publication.commit(expected_names)
                return bundle.manifest
    except ArtifactRollbackError:
        failure = _FORMAL_ROLLBACK_ERROR
    except Exception:
        failure = _FORMAL_ERROR
    return cast(BacktestBundleManifestV1, _raise_formal(failure))


def backtest_artifact_input_paths(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    fresh_context: BacktestArtifactFreshVerificationContext,
) -> tuple[Path, ...]:
    """Return the exact ordered 21-file formal backtest input closure."""
    try:
        _validate_formal_input_identity(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            fresh_context=fresh_context,
        )
        result = tuple(
            Path(os.path.abspath(path))
            for path in _formal_receipt_inputs(
                target,
                plan,
                release,
                experiment,
                fresh_context.upstream_paths,
            )
        )
        if len(result) != 21 or len(set(result)) != 21:
            raise ValueError
        return result
    except Exception:
        pass
    return cast(tuple[Path, ...], _raise_formal(_FORMAL_ERROR))


def backtest_artifact_output_relative_paths() -> tuple[str, ...]:
    """Return the canonical ordered 29-leaf formal backtest output closure."""
    result = tuple(sorted(_FORMAL_EXPECTED_NAMES))
    if len(result) != 29:
        return cast(tuple[str, ...], _raise_formal(_FORMAL_ERROR))
    return result


def verify_backtest_build_output(
    *,
    root: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> None:
    """Freshly verify one built formal tree before its receipt exists."""
    try:
        with localcontext(_FORMAL_DECIMAL_CONTEXT):
            _verify_formal_build_tree(
                root=root,
                target=target,
                plan=plan,
                release=release,
                experiment=experiment,
                config=config,
                fresh_context=fresh_context,
                artifact_roots=artifact_roots,
            )
            return
    except Exception:
        pass
    _raise_formal(_FORMAL_ERROR)


def verify_backtest_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestArtifact:
    """Freshly replay and whole-rehash one formal backtest artifact."""
    try:
        with localcontext(_FORMAL_DECIMAL_CONTEXT):
            absolute_root, before, bundle, actual = _verify_formal_build_tree(
                root=root,
                target=target,
                plan=plan,
                release=release,
                experiment=experiment,
                config=config,
                fresh_context=fresh_context,
                artifact_roots=artifact_roots,
            )
            select_artifact_root(receipt_path, artifact_roots=artifact_roots)
            verified_receipt = verify_stage_receipt_with_bytes(
                receipt_path=receipt_path,
                artifact_roots=artifact_roots,
            )
            if verified_receipt is None:
                raise ValueError
            receipt = verified_receipt.receipt
            if (
                receipt.stage != "backtest"
                or receipt.scope != "WORK"
                or receipt.scope_key != target.manifest.work_key
                or not _digest_paths_equal(
                    receipt.inputs,
                    backtest_artifact_input_paths(
                        target=target,
                        plan=bundle.fresh_plan,
                        release=release,
                        experiment=experiment,
                        fresh_context=fresh_context,
                    ),
                    artifact_roots,
                )
                or not _digest_paths_equal(
                    receipt.outputs,
                    tuple(
                        absolute_root / name
                        for name in backtest_artifact_output_relative_paths()
                    ),
                    artifact_roots,
                )
            ):
                raise ValueError
            if _formal_tree_snapshot(absolute_root) != before:
                raise ValueError
            manifest_raw = actual["backtest_manifest.json"]
            return VerifiedBacktestArtifact(
                root=absolute_root,
                metrics=bundle.metrics,
                manifest=bundle.manifest,
                manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                backtest_receipt_sha256=verified_receipt.sha256,
            )
    except Exception:
        pass
    return cast(VerifiedBacktestArtifact, _raise_formal(_FORMAL_ERROR))


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


def read_backtest_metrics(path: Path) -> BacktestMetricsV1:
    """Read one canonical formal backtest metrics value."""
    payload, raw = _strict_object(path)
    if set(payload) != {field.name for field in fields(BacktestMetricsV1)}:
        raise ValueError("backtest metrics fields drift")
    scenarios = payload.get("scenarios")
    if type(scenarios) is not list or any(type(item) is not dict for item in scenarios):
        raise ValueError("backtest metrics scenarios invalid")
    payload["scenarios"] = tuple(
        AShareScenarioMetricsV1(**cast(Any, item)) for item in scenarios
    )
    metrics = BacktestMetricsV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(metrics)):
        raise ValueError("backtest metrics non-canonical")
    return metrics


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
    if type(paths) is not BacktestArtifactUpstreamPaths:
        raise ValueError("backtest upstream receipt paths invalid")
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


@dataclass(frozen=True)
class _FormalBundle:
    fresh_plan: VerifiedBacktestPlanArtifact
    metrics: BacktestMetricsV1
    manifest: BacktestBundleManifestV1
    scenario_metrics: tuple[AShareScenarioMetricsV1, ...]
    scenario_manifests: tuple[BacktestScenarioManifestV1, ...]
    results: tuple[tuple[ScenarioName, AShareSimulationResult], ...]
    raw_files: dict[str, bytes]


def _formal_bundle(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> _FormalBundle:
    _validate_formal_inputs(
        target, plan, release, experiment, config, fresh_context, artifact_roots
    )
    facts_context = fresh_context.facts_fresh_context
    fresh_plan = verify_backtest_plan_artifact(
        root=plan.root,
        receipt_path=facts_context.plan_receipt_path,
        target=target,
        release=release,
        folds=facts_context.folds,
        experiment=experiment,
        config=config,
        fresh_context=facts_context.plan_fresh_context,
        artifact_roots=artifact_roots,
    )
    if not _same_formal_plan(fresh_plan, plan):
        raise ValueError
    facts = load_verified_a_share_market_facts(
        release=release,
        plan=fresh_plan,
        fresh_context=facts_context,
        artifact_roots=artifact_roots,
    )
    identity = facts.identity
    if (
        type(identity) is not FormalAShareMarketFactsIdentityV1
        or identity.g1_release_id != release.manifest.release_id
        or identity.g1_release_manifest_sha256 != release.manifest_sha256
        or identity.backtest_plan_manifest_sha256 != fresh_plan.manifest_sha256
        or identity.backtest_plan_receipt_sha256
        != fresh_plan.plan_receipt_sha256
        or config.section("data")["benchmark"] != "510300.SH"
    ):
        raise ValueError
    base_periods, initial_cash, annualization = _formal_config_values(
        config, fresh_plan
    )
    simulation_context = AShareSimulationFreshVerificationContext(
        release=release,
        facts_fresh_context=facts_context,
    )
    results: list[tuple[ScenarioName, AShareSimulationResult]] = []
    scenario_metrics: list[AShareScenarioMetricsV1] = []
    replayed = simulate_formal_a_share_scenarios(
        target=target,
        plan=fresh_plan,
        facts=facts,
        cost_periods=base_periods,
        multipliers=tuple(multiplier for _, multiplier in _SCENARIOS),
        initial_cash=initial_cash,
        fresh_context=simulation_context,
        artifact_roots=artifact_roots,
    )
    for (scenario, multiplier), result in zip(_SCENARIOS, replayed, strict=True):
        if result.multiplier != multiplier:
            raise ValueError
        results.append((scenario, result))
        scenario_metrics.append(_formal_scenario_metrics(
            target=target,
            plan=fresh_plan,
            facts=facts,
            result=result,
            base_periods=base_periods,
            scenario=scenario,
            initial_cash=initial_cash,
            annualization_sessions=annualization,
        ))
    raw_files: dict[str, bytes] = {}
    scenario_manifests: list[BacktestScenarioManifestV1] = []
    scenario_hashes: list[tuple[str, str]] = []
    result_by_scenario = dict(results)
    for (scenario, multiplier), scenario_metric in zip(
        _SCENARIOS, scenario_metrics, strict=True
    ):
        result = result_by_scenario[scenario]
        for filename, attribute, _ in _TABLES:
            raw_files[f"{scenario}/{filename}"] = _formal_parquet_bytes(
                cast(pl.DataFrame, getattr(result, attribute))
            )
        metrics_raw = _canonical_bytes(asdict(scenario_metric))
        raw_files[f"{scenario}/metrics.json"] = metrics_raw
        scenario_manifest = _formal_scenario_manifest(
            target=target,
            plan=fresh_plan,
            release=release,
            experiment=experiment,
            config=config,
            identity=identity,
            scenario=scenario,
            multiplier=multiplier,
            periods=_scaled_periods(base_periods, multiplier),
            raw_files=raw_files,
            result=result,
            metrics_raw=metrics_raw,
        )
        manifest_raw = _canonical_bytes(asdict(scenario_manifest))
        raw_files[f"{scenario}/manifest.json"] = manifest_raw
        scenario_manifests.append(scenario_manifest)
        scenario_hashes.append((scenario, hashlib.sha256(manifest_raw).hexdigest()))
    bundle_metrics = BacktestMetricsV1(
        schema_version="m3-a-share-backtest-metrics-v1",
        experiment_key=experiment.manifest.experiment_key,
        work_key=target.manifest.work_key,
        scenarios=tuple(scenario_metrics),
    )
    metrics_raw = _canonical_bytes(asdict(bundle_metrics))
    raw_files["backtest_metrics.json"] = metrics_raw
    bundle_manifest = BacktestBundleManifestV1(
        schema_version="m3-a-share-backtest-bundle-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        scientific_config_sha256=config.scientific_config_sha256,
        target_manifest_sha256=target.manifest_sha256,
        backtest_plan_manifest_sha256=fresh_plan.manifest_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scenario_manifest_sha256s=tuple(scenario_hashes),
        common_target_manifest_sha256=target.manifest_sha256,
        common_market_facts_sha256=identity.input_market_facts_sha256,
        backtest_metrics_sha256=hashlib.sha256(metrics_raw).hexdigest(),
    )
    raw_files["backtest_manifest.json"] = _canonical_bytes(
        asdict(bundle_manifest)
    )
    if set(raw_files) != _FORMAL_EXPECTED_NAMES or len(raw_files) != 29:
        raise ValueError
    return _FormalBundle(
        fresh_plan=fresh_plan,
        metrics=bundle_metrics,
        manifest=bundle_manifest,
        scenario_metrics=tuple(scenario_metrics),
        scenario_manifests=tuple(scenario_manifests),
        results=tuple(results),
        raw_files=raw_files,
    )


def _validate_formal_inputs(
    target: object,
    plan: object,
    release: object,
    experiment: object,
    config: object,
    fresh_context: object,
    artifact_roots: object,
) -> None:
    if (
        type(config) is not LoadedM3Config
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not isinstance(root, Path)
            for alias, root in artifact_roots.items()
        )
    ):
        raise ValueError
    assert isinstance(config, LoadedM3Config)
    _validate_formal_input_identity(
        target=target,
        plan=plan,
        release=release,
        experiment=experiment,
        fresh_context=fresh_context,
    )
    assert isinstance(target, VerifiedTargetArtifact)
    assert isinstance(plan, VerifiedBacktestPlanArtifact)
    assert isinstance(release, VerifiedG1Release)
    assert isinstance(experiment, VerifiedExperimentIdentity)
    assert isinstance(fresh_context, BacktestArtifactFreshVerificationContext)
    facts_context = fresh_context.facts_fresh_context
    paths = fresh_context.upstream_paths
    plan_context = facts_context.plan_fresh_context
    if (
        facts_context.config != config
        or plan.manifest.scientific_config_sha256 != config.scientific_config_sha256
        or target.manifest.scientific_config_sha256 != config.scientific_config_sha256
    ):
        raise ValueError
    quality = _formal_g1_quality_path(release)
    expected_paths = (
        (paths.target_receipt_path, plan_context.target_receipt_path),
        (paths.plan_receipt_path, facts_context.plan_receipt_path),
        (
            paths.experiment_receipt_path,
            plan_context.target_upstream_paths.experiment_receipt_path,
        ),
    )
    if any(not _same_physical_path(left, right) for left, right in expected_paths):
        raise ValueError
    _formal_fresh_upstream_bytes(target, plan, release, experiment, paths)
    for path in (
        target.root,
        plan.root,
        release.release.root,
        experiment.root,
        quality,
        *tuple(path for pair in expected_paths for path in pair),
    ):
        select_artifact_root(
            path, artifact_roots=cast(Mapping[str, Path], artifact_roots)
        )


def _validate_formal_input_identity(
    *,
    target: object,
    plan: object,
    release: object,
    experiment: object,
    fresh_context: object,
) -> None:
    if (
        type(target) is not VerifiedTargetArtifact
        or type(plan) is not VerifiedBacktestPlanArtifact
        or type(experiment) is not VerifiedExperimentIdentity
        or type(fresh_context) is not BacktestArtifactFreshVerificationContext
    ):
        raise ValueError
    _validate_formal_release_context_binding(release, fresh_context)
    assert isinstance(release, VerifiedG1Release)
    assert isinstance(fresh_context, BacktestArtifactFreshVerificationContext)
    facts_context = fresh_context.facts_fresh_context
    paths = fresh_context.upstream_paths
    plan_context = facts_context.plan_fresh_context
    if (
        not _same_formal_target(facts_context.target, target)
        or facts_context.experiment != experiment
        or plan.manifest.target_manifest_sha256 != target.manifest_sha256
        or plan.manifest.target_receipt_sha256 != target.target_receipt_sha256
        or plan.manifest.experiment_key != experiment.manifest.experiment_key
        or plan.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or plan.manifest.g1_release_id != release.manifest.release_id
        or plan.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or target.manifest.experiment_key != experiment.manifest.experiment_key
        or target.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or target.manifest.g1_release_id != release.manifest.release_id
        or target.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or plan.manifest.order_quantity_rule_version
        != G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION
    ):
        raise ValueError
    expected_paths = (
        (paths.target_receipt_path, plan_context.target_receipt_path),
        (paths.plan_receipt_path, facts_context.plan_receipt_path),
        (
            paths.experiment_receipt_path,
            plan_context.target_upstream_paths.experiment_receipt_path,
        ),
    )
    if any(not _same_physical_path(left, right) for left, right in expected_paths):
        raise ValueError
    _formal_g1_quality_path(release)


def _same_formal_target(left: object, right: VerifiedTargetArtifact) -> bool:
    return bool(
        type(left) is VerifiedTargetArtifact
        and left.root == right.root
        and left.targets.equals(right.targets)
        and left.target_daily.equals(right.target_daily)
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.target_receipt_sha256 == right.target_receipt_sha256
    )


def _same_formal_plan(
    left: object, right: VerifiedBacktestPlanArtifact
) -> bool:
    return bool(
        type(left) is VerifiedBacktestPlanArtifact
        and left.root == right.root
        and left.scheduled_targets.equals(right.scheduled_targets)
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.plan_receipt_sha256 == right.plan_receipt_sha256
    )


def _formal_config_values(
    config: LoadedM3Config,
    plan: VerifiedBacktestPlanArtifact,
) -> tuple[tuple[AShareCostPeriod, ...], Decimal, int]:
    backtest = config.section("backtest")["a_share"]
    costs = config.section("costs")
    if not isinstance(backtest, Mapping):
        raise ValueError
    if (
        tuple(cast(Sequence[object], backtest["friction_multipliers"]))
        != (0.5, 1.0, 2.0)
        or backtest["execution_price_rounding"]
        != "BUY_CEIL_SELL_FLOOR_TICK_V1"
        or backtest["fee_rounding"] != "EACH_COMPONENT_HALF_UP_CENT_V1"
        or backtest["cash_settlement_rounding"] != "HALF_UP_CENT_V1"
        or Decimal(str(backtest["price_tick"])) != Decimal("0.01")
        or type(backtest["annualization_sessions"]) is not int
        or backtest["annualization_sessions"] != 252
        or tuple(cast(Sequence[object], costs["scaled_components"]))
        != ("commission_rate", "commission_min", "slippage")
    ):
        raise ValueError
    initial_cash = Decimal(str(backtest["initial_cash"]))
    if not initial_cash.is_finite() or initial_cash <= 0:
        raise ValueError
    raw_periods = cast(Sequence[Mapping[str, object]], costs["a_share_periods"])
    periods = tuple(
        AShareCostPeriod(
            effective_from=cast(dt.date, item["effective_from"]),
            effective_to=cast(dt.date | None, item.get("effective_to")),
            commission_rate=Decimal(str(item["commission_rate"])),
            commission_min=Decimal(str(item["commission_min"])),
            stamp_tax_sell=Decimal(str(item["stamp_tax_sell"])),
            transfer_fee=Decimal(str(item["transfer_fee"])),
            slippage=Decimal(str(item["slippage"])),
        )
        for item in raw_periods
    )
    if not periods:
        raise ValueError
    for left, right in zip(periods, periods[1:]):
        if (
            left.effective_to is None
            or left.effective_to + dt.timedelta(days=1) != right.effective_from
        ):
            raise ValueError
    for date in plan.manifest.window.execution_dates:
        _period_for_date(date, periods)
    return periods, initial_cash, cast(int, backtest["annualization_sessions"])


def _scaled_periods(
    periods: tuple[AShareCostPeriod, ...], multiplier: Decimal
) -> tuple[AShareCostPeriod, ...]:
    return tuple(
        AShareCostPeriod(
            effective_from=item.effective_from,
            effective_to=item.effective_to,
            commission_rate=item.commission_rate * multiplier,
            commission_min=item.commission_min * multiplier,
            stamp_tax_sell=item.stamp_tax_sell,
            transfer_fee=item.transfer_fee,
            slippage=item.slippage * multiplier,
        )
        for item in periods
    )


def _formal_scenario_metrics(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    facts: VerifiedAShareMarketFacts,
    result: AShareSimulationResult,
    base_periods: tuple[AShareCostPeriod, ...],
    scenario: ScenarioName,
    initial_cash: Decimal,
    annualization_sessions: int,
) -> AShareScenarioMetricsV1:
    nav = result.nav
    sessions = plan.manifest.window.execution_dates
    if (
        nav.height != len(sessions)
        or tuple(nav["date"].to_list()) != sessions
        or result.daily_diagnostics.height != len(sessions)
        or tuple(result.daily_diagnostics["date"].to_list()) != sessions
    ):
        raise ValueError
    terminal_equity = _decimal_value(nav.item(-1, "equity"))
    if terminal_equity < 0:
        raise ValueError
    portfolio_return = terminal_equity / initial_cash - Decimal(1)
    if terminal_equity == 0:
        annualized_return = Decimal(-1)
    else:
        exponent = Decimal(annualization_sessions) / Decimal(nav.height)
        annualized_return = (
            (Decimal(1) + portfolio_return) ** exponent - Decimal(1)
        )
    unit_navs = (Decimal(1), *tuple(
        _decimal_value(value) for value in nav["unit_nav"].to_list()
    ))
    peak = unit_navs[0]
    max_drawdown = Decimal(0)
    for value in unit_navs:
        if value < 0:
            raise ValueError
        peak = max(peak, value)
        if peak <= 0:
            raise ValueError
        max_drawdown = min(max_drawdown, value / peak - Decimal(1))
    benchmark = facts.benchmark_bars
    if (
        type(benchmark) is not pl.DataFrame
        or benchmark.height != len(sessions)
        or set(benchmark["benchmark"].to_list()) != {"510300.SH"}
        or tuple(benchmark["trade_date"].to_list()) != sessions
        or benchmark.select("benchmark", "trade_date").unique().height
        != len(sessions)
    ):
        raise ValueError
    benchmark_open = _decimal_value(benchmark.item(0, "open"))
    benchmark_close = _decimal_value(benchmark.item(-1, "close"))
    if benchmark_open <= 0 or benchmark_close <= 0:
        raise ValueError
    benchmark_return = benchmark_close / benchmark_open - Decimal(1)
    benchmark_wealth = Decimal(1) + benchmark_return
    if benchmark_wealth <= 0:
        raise ValueError
    net_excess = portfolio_return - benchmark_return
    relative_wealth = (
        (Decimal(1) + portfolio_return) / benchmark_wealth - Decimal(1)
    )
    target_gross = _target_turnover(plan.scheduled_targets)
    realized_gross = _decimal_sum(
        result.daily_diagnostics["gross_turnover"].to_list()
    )
    test_turnover = _decimal_sum(
        result.daily_diagnostics["one_way_turnover"].to_list()
    )
    if test_turnover != realized_gross / Decimal(2):
        raise ValueError
    commissions = _decimal_sum(result.trades["commission"].to_list())
    stamps = _decimal_sum(result.trades["stamp_tax"].to_list())
    transfers = _decimal_sum(result.trades["transfer_fee"].to_list())
    slippage = _decimal_sum(result.trades["slippage_cost"].to_list())
    total_fees = commissions + stamps + transfers
    for row in result.trades.iter_rows(named=True):
        if _decimal_value(row["total_fee"]) != (
            _decimal_value(row["commission"])
            + _decimal_value(row["stamp_tax"])
            + _decimal_value(row["transfer_fee"])
        ):
            raise ValueError
    terminal_nav = nav.row(-1, named=True)
    if (
        _decimal_value(terminal_nav["cumulative_commission"]) != commissions
        or _decimal_value(terminal_nav["cumulative_stamp_tax"]) != stamps
        or _decimal_value(terminal_nav["cumulative_transfer_fee"]) != transfers
        or _decimal_value(terminal_nav["cumulative_slippage_cost"]) != slippage
    ):
        raise ValueError
    requested = sum(cast(list[int], result.daily_diagnostics[
        "n_order_intents"
    ].to_list()))
    rejection_keys = {
        (row["date"], row["symbol"], row["side"])
        for row in result.rejections.iter_rows(named=True)
        if (
            (row["rejected_quantity"] is not None
             and cast(int, row["rejected_quantity"]) > 0)
            or _decimal_value(row["rejected_notional"]) > 0
        )
    }
    rejected = len(rejection_keys)
    if rejected > requested:
        raise ValueError
    rejection_rate = (
        None if requested == 0 else Decimal(rejected) / Decimal(requested)
    )
    unfilled_notional = _decimal_sum(
        result.rejections["rejected_notional"].to_list()
    )
    rounding_delta = _decimal_sum(
        result.corporate_action_postings["cash_rounding_delta"].to_list()
    )
    cash_ratios: list[Decimal] = []
    for row in nav.iter_rows(named=True):
        equity = _decimal_value(row["equity"])
        if equity <= 0:
            raise ValueError
        cash_ratios.append(_decimal_value(row["cash"]) / equity)
    average_cash_ratio = sum(cash_ratios, Decimal(0)) / Decimal(nav.height)
    terminal_date = plan.manifest.window.terminal_valuation_date
    terminal_positions = result.positions.filter(pl.col("date") == terminal_date)
    terminal_value = _decimal_sum(terminal_positions["market_value"].to_list())
    pending_value = _decimal_sum(
        terminal_positions.filter(pl.col("pending_exit"))[
            "market_value"
        ].to_list()
    )
    exit_cost = _formal_terminal_exit_cost(
        terminal_positions,
        _period_for_date(terminal_date, base_periods),
    )
    return AShareScenarioMetricsV1(
        schema_version="m3-a-share-scenario-metrics-v1",
        experiment_key=target.manifest.experiment_key,
        work_key=target.manifest.work_key,
        scenario=scenario,
        multiplier=_finite_float(result.multiplier),
        n_sessions=nav.height,
        initial_cash=_finite_float(initial_cash),
        terminal_equity=_finite_float(terminal_equity),
        portfolio_return=_finite_float(portfolio_return),
        annualized_return=_finite_float(annualized_return),
        test_max_drawdown=_finite_float(max_drawdown),
        benchmark_return=_finite_float(benchmark_return),
        test_net_excess_return=_finite_float(net_excess),
        relative_wealth=_finite_float(relative_wealth),
        target_gross_turnover=_finite_float(target_gross),
        target_one_way_turnover=_finite_float(target_gross / Decimal(2)),
        realized_gross_turnover=_finite_float(realized_gross),
        test_turnover=_finite_float(test_turnover),
        commission_total=_finite_float(commissions),
        stamp_tax_total=_finite_float(stamps),
        transfer_fee_total=_finite_float(transfers),
        total_fees=_finite_float(total_fees),
        slippage_cost_total=_finite_float(slippage),
        total_trading_cost=_finite_float(total_fees + slippage),
        cash_rounding_delta_total=_finite_float(rounding_delta),
        requested_order_count=requested,
        rejection_count=rejected,
        rejection_rate=(
            None if rejection_rate is None else _finite_float(rejection_rate)
        ),
        unfilled_notional=_finite_float(unfilled_notional),
        average_cash_ratio=_finite_float(average_cash_ratio),
        corporate_action_posting_count=result.corporate_action_postings.height,
        unexecutable_date_count=result.rejections["date"].n_unique(),
        terminal_positions_market_value=_finite_float(terminal_value),
        terminal_pending_exit_value=_finite_float(pending_value),
        terminal_estimated_exit_cost_1x=_finite_float(exit_cost),
    )


def _decimal_value(value: object) -> Decimal:
    if type(value) not in {float, int, Decimal} or type(value) is bool:
        raise ValueError
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError
    return result


def _decimal_sum(values: Sequence[object]) -> Decimal:
    return sum((_decimal_value(value) for value in values), Decimal(0))


def _finite_float(value: Decimal) -> float:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError
    projected = float(value)
    if not math.isfinite(projected):
        raise ValueError
    return projected


def _formal_terminal_exit_cost(
    terminal_positions: pl.DataFrame,
    period: AShareCostPeriod,
) -> Decimal:
    total = Decimal(0)
    tick = Decimal("0.01")
    for row in terminal_positions.iter_rows(named=True):
        quantity = row["quantity"]
        if type(quantity) is not int or quantity <= 0:
            raise ValueError
        mark = _decimal_value(row["mark_price"])
        raw = mark * (Decimal(1) - period.slippage)
        execution_price = (
            (raw / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        )
        if execution_price <= 0:
            raise ValueError
        notional = execution_price * quantity
        fees = compute_a_share_fee_components(
            notional=notional,
            side=OrderSide.SELL,
            cost_period=period,
        )
        slippage = Decimal(quantity) * (mark - execution_price)
        if slippage < 0:
            raise ValueError
        total += (
            fees.commission + fees.stamp_tax + fees.transfer_fee + slippage
        )
    return total


def _formal_scenario_manifest(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    identity: FormalAShareMarketFactsIdentityV1,
    scenario: ScenarioName,
    multiplier: Decimal,
    periods: tuple[AShareCostPeriod, ...],
    raw_files: Mapping[str, bytes],
    result: AShareSimulationResult,
    metrics_raw: bytes,
) -> BacktestScenarioManifestV1:
    entries: list[BacktestArtifactEntryV1] = []
    for filename, attribute, schema_name in _TABLES:
        path = f"{scenario}/{filename}"
        raw = raw_files[path]
        frame = cast(pl.DataFrame, getattr(result, attribute))
        entries.append(BacktestArtifactEntryV1(
            path=filename,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            row_count=frame.height,
            schema_name=schema_name,
        ))
    entries.append(BacktestArtifactEntryV1(
        path="metrics.json",
        sha256=hashlib.sha256(metrics_raw).hexdigest(),
        size_bytes=len(metrics_raw),
        row_count=None,
        schema_name="AShareScenarioMetricsV1",
    ))
    periods_raw = _canonical_bytes([asdict(item) for item in periods])
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
        multiplier=_finite_float(multiplier),
        cost_periods_sha256=hashlib.sha256(periods_raw).hexdigest(),
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        input_market_facts_sha256=identity.input_market_facts_sha256,
        output_files=tuple(sorted(entries, key=lambda item: item.path)),
        metrics_sha256=hashlib.sha256(metrics_raw).hexdigest(),
    )


def _formal_parquet_bytes(frame: pl.DataFrame) -> bytes:
    stream = io.BytesIO()
    frame.write_parquet(
        stream,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )
    return stream.getvalue()


def _validate_formal_readback(
    name: str,
    raw: bytes,
    bundle: _FormalBundle,
) -> None:
    if name.endswith(".json"):
        _strict_json_bytes(raw)
        if raw != bundle.raw_files[name]:
            raise ValueError
        return
    parts = name.split("/")
    if len(parts) != 2 or not name.endswith(".parquet"):
        raise ValueError
    scenario = cast(ScenarioName, parts[0])
    filename = parts[1]
    match = tuple(item for item in _TABLES if item[0] == filename)
    if len(match) != 1:
        raise ValueError
    _, attribute, schema_name = match[0]
    result = dict(bundle.results)[scenario]
    expected = cast(pl.DataFrame, getattr(result, attribute))
    actual = pl.read_parquet(io.BytesIO(raw))
    schema = _FORMAL_TABLE_SCHEMAS[attribute]
    validated = schema.validate(actual)
    if (
        actual.columns != expected.columns
        or actual.dtypes != expected.dtypes
        or validated.columns != actual.columns
        or validated.dtypes != actual.dtypes
        or not actual.equals(validated)
        or not actual.equals(expected)
        or schema.__name__ != schema_name
        or raw != bundle.raw_files[name]
    ):
        raise ValueError


def _strict_json_bytes(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError
            payload[key] = value
        return payload

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError
    return value


_FORMAL_G1_ARTIFACT_PATH_COUNT = 17
_FORMAL_MARKET_TABLE_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "instrument.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)


def _formal_g1_quality_path(release: VerifiedG1Release) -> Path:
    quality = release.release.quality_path
    expected = release.release.root / "quality.json"
    if (
        not isinstance(quality, Path)
        or quality.name != "quality.json"
        or quality != expected
    ):
        raise ValueError
    return quality


def _require_formal_g1_release_exact(release: object) -> VerifiedG1Release:
    if type(release) is not VerifiedG1Release:
        raise ValueError
    inner = release.release
    if (
        type(inner) is not G1Release
        or type(release.manifest) is not G1ManifestV5
        or type(release.quality) is not G1QualityReportV1
        or type(release.manifest_sha256) is not str
        or type(release.quality_sha256) is not str
        or type(release.artifact_paths) is not tuple
        or len(release.artifact_paths) != _FORMAL_G1_ARTIFACT_PATH_COUNT
    ):
        raise ValueError
    root = inner.root
    if (
        not isinstance(root, Path)
        or not isinstance(inner.manifest_path, Path)
        or not isinstance(inner.quality_path, Path)
        or inner.manifest_path != root / "manifest.json"
        or inner.quality_path != root / "quality.json"
    ):
        raise ValueError
    rebuilt: list[tuple[str, Path]] = []
    for item in release.artifact_paths:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError
        name, path = item
        if type(name) is not str or not isinstance(path, Path):
            raise ValueError
        absolute = Path(os.path.abspath(path))
        if absolute.parent != root or absolute.name != name:
            raise ValueError
        rebuilt.append((name, absolute))
    ordered = tuple(sorted(rebuilt, key=lambda value: value[0]))
    if tuple(rebuilt) != ordered or len({name for name, _ in ordered}) != len(
        ordered
    ):
        raise ValueError
    _formal_g1_quality_path(release)
    return release


def _same_formal_g1_release(left: object, right: VerifiedG1Release) -> bool:
    return bool(
        type(left) is VerifiedG1Release
        and type(left.release) is G1Release
        and left.release == right.release
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.quality == right.quality
        and left.quality_sha256 == right.quality_sha256
        and left.artifact_paths == right.artifact_paths
    )


def _capture_formal_g1_source_snapshot(
    release: object,
) -> _FormalG1SourceEntitySnapshot:
    verified = _require_formal_g1_release_exact(release)
    inner = verified.release
    root_entity = _formal_entity(inner.root, directory=True)
    manifest_entity = _formal_entity(inner.manifest_path, directory=False)
    quality_entity = _formal_entity(inner.quality_path, directory=False)
    source = dict(verified.artifact_paths)
    market_tables: list[tuple[str, _FormalFileEntity]] = []
    identities = {
        (manifest_entity.device, manifest_entity.inode),
        (quality_entity.device, quality_entity.inode),
    }
    if len(identities) != 2:
        raise ValueError
    for name in _FORMAL_MARKET_TABLE_FILES:
        path = source.get(name)
        if path is None or path != inner.root / name:
            raise ValueError
        entity = _formal_entity(path, directory=False)
        identity = (entity.device, entity.inode)
        if identity in identities:
            raise ValueError
        identities.add(identity)
        market_tables.append((name, entity))
    if len(market_tables) != len(_FORMAL_MARKET_TABLE_FILES):
        raise ValueError
    return _FormalG1SourceEntitySnapshot(
        root=root_entity,
        manifest=manifest_entity,
        quality=quality_entity,
        market_tables=tuple(market_tables),
    )


def _validate_formal_release_context_binding(
    release: object,
    fresh_context: BacktestArtifactFreshVerificationContext,
) -> None:
    if type(fresh_context) is not BacktestArtifactFreshVerificationContext:
        raise ValueError
    caller = _require_formal_g1_release_exact(release)
    bound = _require_formal_g1_release_exact(fresh_context.release)
    if not _same_formal_g1_release(caller, bound):
        raise ValueError
    snapshot = object.__getattribute__(fresh_context, "_source_snapshot")
    if type(snapshot) is not _FormalG1SourceEntitySnapshot:
        raise ValueError
    current = _capture_formal_g1_source_snapshot(bound)
    if current != snapshot:
        raise ValueError


def _formal_fresh_upstream_bytes(
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    paths: FormalBacktestArtifactUpstreamPaths,
) -> None:
    if type(paths) is not FormalBacktestArtifactUpstreamPaths:
        raise ValueError
    _ = (target, plan, experiment)
    quality = _formal_g1_quality_path(release)
    if (
        not paths.target_receipt_path.is_file()
        or not paths.plan_receipt_path.is_file()
        or not paths.experiment_receipt_path.is_file()
        or not quality.is_file()
        or _file_sha(quality) != release.quality_sha256
    ):
        raise ValueError


def _formal_receipt_inputs(
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    paths: FormalBacktestArtifactUpstreamPaths,
) -> tuple[Path, ...]:
    if type(paths) is not FormalBacktestArtifactUpstreamPaths:
        raise ValueError
    source = dict(release.artifact_paths)
    quality = _formal_g1_quality_path(release)
    result = (
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
        quality,
        *(source[name] for name in _FORMAL_MARKET_TABLE_FILES),
    )
    if any(path.name == "receipt.json" for path in result[11:13]):
        raise ValueError
    absolute = tuple(Path(os.path.abspath(path)) for path in result)
    if len(result) != 21 or len(set(absolute)) != 21:
        raise ValueError
    for index, left in enumerate(result):
        for right in result[index + 1 :]:
            if os.path.samefile(left, right):
                raise ValueError
    return result


def _formal_output_paths(root: Path) -> tuple[Path, ...]:
    result = tuple(root / name for name in sorted(_FORMAL_EXPECTED_NAMES))
    if len(result) != 29:
        raise ValueError
    return result


@dataclass(frozen=True)
class _FormalFileEntity:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    links: int


@dataclass(frozen=True)
class _FormalTreeSnapshot:
    root: _FormalFileEntity
    children: tuple[tuple[str, _FormalFileEntity], ...]
    files: tuple[tuple[str, _FormalFileEntity], ...]


def _path_has_reparse(path: Path) -> bool:
    info = os.lstat(path)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & marker)


def _require_real_path(path: Path) -> None:
    current = Path(os.path.abspath(path))
    while True:
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or _path_has_reparse(current):
            raise ValueError
        if current.parent == current:
            return
        current = current.parent


def _formal_entity(
    path: Path,
    *,
    directory: bool,
) -> _FormalFileEntity:
    _require_real_path(path)
    info = os.lstat(path)
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError
    return _FormalFileEntity(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        links=info.st_nlink,
    )


def _formal_tree_snapshot(root: Path) -> _FormalTreeSnapshot:
    absolute = Path(os.path.abspath(root))
    root_entity = _formal_entity(absolute, directory=True)
    expected_children = {scenario for scenario, _ in _SCENARIOS}
    expected_root_files = _ROOT_FILES
    root_entries = {item.name for item in os.scandir(absolute)}
    if root_entries != expected_children | expected_root_files:
        raise ValueError
    children: list[tuple[str, _FormalFileEntity]] = []
    files: list[tuple[str, _FormalFileEntity]] = []
    for name in sorted(expected_root_files):
        files.append((name, _formal_entity(absolute / name, directory=False)))
    for child_name in sorted(expected_children):
        child = absolute / child_name
        child_entity = _formal_entity(child, directory=True)
        children.append((child_name, child_entity))
        child_entries = {item.name for item in os.scandir(child)}
        if child_entries != _SCENARIO_FILES:
            raise ValueError
        for leaf in sorted(_SCENARIO_FILES):
            relative = f"{child_name}/{leaf}"
            files.append((relative, _formal_entity(child / leaf, directory=False)))
    identities = {(item.device, item.inode) for _, item in files}
    if len(files) != 29 or len(identities) != len(files):
        raise ValueError
    return _FormalTreeSnapshot(
        root=root_entity,
        children=tuple(children),
        files=tuple(files),
    )


def _stable_formal_tree_read(
    root: Path,
    snapshot: _FormalTreeSnapshot,
) -> dict[str, bytes]:
    if _formal_tree_snapshot(root) != snapshot:
        raise ValueError
    raw: dict[str, bytes] = {}
    for name, _ in snapshot.files:
        raw[name] = (root / Path(name)).read_bytes()
    if _formal_tree_snapshot(root) != snapshot:
        raise ValueError
    return raw


def _verify_formal_build_tree(
    *,
    root: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> tuple[Path, _FormalTreeSnapshot, _FormalBundle, dict[str, bytes]]:
    absolute_root = Path(os.path.abspath(root))
    select_artifact_root(absolute_root, artifact_roots=artifact_roots)
    before = _formal_tree_snapshot(absolute_root)
    bundle = _formal_bundle(
        target=target,
        plan=plan,
        release=release,
        experiment=experiment,
        config=config,
        fresh_context=fresh_context,
        artifact_roots=artifact_roots,
    )
    actual = _stable_formal_tree_read(absolute_root, before)
    if actual != bundle.raw_files:
        raise ValueError
    for name, raw in actual.items():
        _validate_formal_readback(name, raw, bundle)
    if _formal_tree_snapshot(absolute_root) != before:
        raise ValueError
    return absolute_root, before, bundle, actual


def _same_physical_path(left: Path, right: Path) -> bool:
    left_absolute = Path(os.path.abspath(left))
    right_absolute = Path(os.path.abspath(right))
    if os.path.normcase(str(left_absolute)) != os.path.normcase(str(right_absolute)):
        return False
    left_entity = _formal_entity(left_absolute, directory=False)
    right_entity = _formal_entity(right_absolute, directory=False)
    return (
        left_entity.device,
        left_entity.inode,
    ) == (
        right_entity.device,
        right_entity.inode,
    )


__all__ = [
    "AShareBacktestArtifactError",
    "BacktestArtifactFreshVerificationContext",
    "BacktestArtifactUpstreamPaths",
    "FormalBacktestArtifactUpstreamPaths",
    "backtest_artifact_input_paths",
    "backtest_artifact_output_relative_paths",
    "build_backtest_artifact",
    "build_development_example_backtest_artifact",
    "read_backtest_bundle_manifest",
    "read_backtest_metrics",
    "read_backtest_scenario_manifest",
    "verify_backtest_artifact",
    "verify_backtest_build_output",
    "verify_development_example_backtest_artifact",
]
