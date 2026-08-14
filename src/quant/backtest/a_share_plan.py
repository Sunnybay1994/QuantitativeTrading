"""Deterministic A-share backtest plans for the M3 development chain."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.domain import TargetWeightSchema, TradeCalendarSchema
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactRollbackError,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    AShareCostPeriod,
    BacktestPlanManifestV1,
    BacktestWindow,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    LabelBuildSpec,
    LightgbmTrainingSpec,
    PredictionBuildSpec,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    TargetBuildSpec,
    TargetUpstreamPaths,
    VerifiedAlignmentArtifact,
    VerifiedBacktestPlanArtifact,
    VerifiedExperimentIdentity,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedModelArtifact,
    VerifiedPredictionArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
    VerifiedTargetArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleBacktestPlanArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleTargetArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.targets import read_target_manifest, verify_target_artifact

G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION = "sse_szse_limit_order_quantity_v1"
_FILES = {
    "cost_schedule.json",
    "manifest.json",
    "schedule_diagnostics.parquet",
    "scheduled_targets.parquet",
}
_SCHEDULED_COLUMNS = [
    "as_of",
    "strategy",
    "strategy_version",
    "symbol",
    "weight",
    "execution_date",
]
_DIAGNOSTICS_SCHEMA = {
    "as_of": pl.Date,
    "execution_date": pl.Date,
    "n_targets": pl.Int64,
    "total_target_weight": pl.Float64,
    "session_lag": pl.Int64,
}
_P = ParamSpec("_P")
_T = TypeVar("_T")


@dataclass(frozen=True)
class BacktestPlanFreshVerificationContext:
    """Non-serializable arguments required to freshly verify G7A."""

    snapshot: VerifiedSnapshotArtifact
    snapshot_spec: SnapshotBuildSpec
    provider: VerifiedProviderArtifact
    provider_spec: ProviderBuildSpec
    experiment_spec: ExperimentIdentitySpec
    fold_spec: FoldPlanBuildSpec
    feature: VerifiedFeatureArtifact
    feature_spec: FeatureBuildSpec
    label: VerifiedLabelArtifact
    label_spec: LabelBuildSpec
    alignment: VerifiedAlignmentArtifact
    alignment_spec: AlignmentBuildSpec
    model: VerifiedModelArtifact
    model_spec: LightgbmTrainingSpec
    prediction: VerifiedPredictionArtifact
    prediction_spec: PredictionBuildSpec
    target_spec: TargetBuildSpec
    target_upstream_paths: TargetUpstreamPaths
    target_receipt_path: Path

    def __post_init__(self) -> None:
        typed = (
            (self.snapshot, VerifiedSnapshotArtifact),
            (self.snapshot_spec, SnapshotBuildSpec),
            (self.provider, VerifiedProviderArtifact),
            (self.provider_spec, ProviderBuildSpec),
            (self.experiment_spec, ExperimentIdentitySpec),
            (self.fold_spec, FoldPlanBuildSpec),
            (self.feature, VerifiedFeatureArtifact),
            (self.feature_spec, FeatureBuildSpec),
            (self.label, VerifiedLabelArtifact),
            (self.label_spec, LabelBuildSpec),
            (self.alignment, VerifiedAlignmentArtifact),
            (self.alignment_spec, AlignmentBuildSpec),
            (self.model, VerifiedModelArtifact),
            (self.model_spec, LightgbmTrainingSpec),
            (self.prediction, VerifiedPredictionArtifact),
            (self.prediction_spec, PredictionBuildSpec),
            (self.target_spec, TargetBuildSpec),
            (self.target_upstream_paths, TargetUpstreamPaths),
        )
        if (
            any(type(value) is not expected for value, expected in typed)
            or not isinstance(self.target_receipt_path, Path)
        ):
            raise ValueError("backtest plan fresh context invalid")


def _plan_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_BACKTEST_PLAN_INVALID") from None

    return wrapped


def _formal_plan_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    """Expose only stable, redacted formal publication failures."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        rollback_failed = False
        try:
            return function(*args, **kwargs)
        except ArtifactRollbackError:
            rollback_failed = True
        except Exception:
            pass
        if rollback_failed:
            raise ValueError("M3_BACKTEST_PLAN_ROLLBACK_FAILED") from None
        raise ValueError("M3_BACKTEST_PLAN_ARTIFACT_INVALID") from None

    return wrapped


class BacktestPlanUpstreamPaths:
    """Receipt paths not derivable from the verified artifact roots."""

    def __init__(
        self,
        *,
        target_receipt_path: Path,
        fold_receipt_path: Path,
        experiment_receipt_path: Path,
    ) -> None:
        paths = (target_receipt_path, fold_receipt_path, experiment_receipt_path)
        if any(not isinstance(path, Path) for path in paths) or len(set(paths)) != 3:
            raise ValueError("backtest plan upstream paths invalid")
        self.target_receipt_path = target_receipt_path
        self.fold_receipt_path = fold_receipt_path
        self.experiment_receipt_path = experiment_receipt_path


@_formal_plan_boundary
def build_backtest_plan_artifact(
    *,
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> BacktestPlanManifestV1:
    """Publish a formal next-SH-session plan from one freshly verified target."""
    _validate_formal_outer(
        target, release, folds, experiment, config, fresh_context, artifact_roots
    )
    _require_empty_directory(output_root)
    with ArtifactPublication(output_root) as publication:
        fresh = _fresh_target_once(
            target, release, folds, experiment, config, fresh_context, artifact_roots
        )
        sessions = _formal_sh_open_sessions(release)
        scheduled, diagnostics, window = _formal_schedule_targets(
            fresh, folds, sessions
        )
        _require_cost_coverage(config, window.execution_dates)
        cost_raw = _canonical_bytes(_formal_cost_schedule_payload(config))
        scheduled_raw = _parquet_bytes(scheduled)
        diagnostics_raw = _parquet_bytes(diagnostics)
        manifest = _make_formal_manifest(
            target=fresh,
            release=release,
            folds=folds,
            experiment=experiment,
            config=config,
            window=window,
            sessions=sessions,
            cost_raw=cost_raw,
            scheduled_raw=scheduled_raw,
            diagnostics_raw=diagnostics_raw,
        )
        publication.write_bytes("scheduled_targets.parquet", scheduled_raw)
        publication.write_bytes("schedule_diagnostics.parquet", diagnostics_raw)
        publication.write_bytes("cost_schedule.json", cost_raw)
        publication.write_bytes("manifest.json", _canonical_bytes(asdict(manifest)))
        if (
            not _read_formal_scheduled_bytes(
                publication.read_bytes("scheduled_targets.parquet")
            ).equals(scheduled)
            or not _read_formal_diagnostics_bytes(
                publication.read_bytes("schedule_diagnostics.parquet")
            ).equals(diagnostics)
            or publication.read_bytes("cost_schedule.json") != cost_raw
            or _read_backtest_plan_manifest_bytes(
                publication.read_bytes("manifest.json")
            ) != manifest
        ):
            raise ValueError("formal backtest plan readback drift")
        publication.commit(_FILES)
        return manifest


@_formal_plan_boundary
def verify_backtest_plan_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestPlanArtifact:
    """Freshly recompute a formal plan and verify its exact receipt closure."""
    _validate_formal_outer(
        target, release, folds, experiment, config, fresh_context, artifact_roots
    )
    root_identity = _formal_tree_identity(root)
    fresh = _fresh_target_once(
        target, release, folds, experiment, config, fresh_context, artifact_roots
    )
    sessions = _formal_sh_open_sessions(release)
    expected_scheduled, expected_diagnostics, window = _formal_schedule_targets(
        fresh, folds, sessions
    )
    _require_cost_coverage(config, window.execution_dates)
    raw = _stable_formal_tree_read(root, root_identity)
    scheduled = _read_formal_scheduled_bytes(raw["scheduled_targets.parquet"])
    diagnostics = _read_formal_diagnostics_bytes(raw["schedule_diagnostics.parquet"])
    if (
        not scheduled.equals(expected_scheduled)
        or not diagnostics.equals(expected_diagnostics)
    ):
        raise ValueError("formal backtest plan content drift")
    expected_cost = _canonical_bytes(_formal_cost_schedule_payload(config))
    if raw["cost_schedule.json"] != expected_cost:
        raise ValueError("formal backtest plan cost drift")
    manifest = _read_backtest_plan_manifest_bytes(raw["manifest.json"])
    expected_manifest = _make_formal_manifest(
        target=fresh,
        release=release,
        folds=folds,
        experiment=experiment,
        config=config,
        window=window,
        sessions=sessions,
        cost_raw=expected_cost,
        scheduled_raw=raw["scheduled_targets.parquet"],
        diagnostics_raw=raw["schedule_diagnostics.parquet"],
    )
    if manifest != expected_manifest:
        raise ValueError("formal backtest plan manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("formal backtest plan receipt missing")
    inputs = _formal_receipt_inputs(
        release, folds, experiment, fresh_context, fresh
    )
    outputs = tuple(root / name for name in sorted(_FILES))
    receipt = verified_receipt.receipt
    if (
        receipt.stage != "backtest-plan"
        or receipt.scope != "WORK"
        or receipt.scope_key != fresh.manifest.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("formal backtest plan receipt closure drift")
    if _stable_formal_tree_read(root, root_identity) != raw:
        raise ValueError("formal backtest plan post-verification drift")
    return VerifiedBacktestPlanArtifact(
        root=Path(os.path.abspath(root)),
        scheduled_targets=scheduled,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw["manifest.json"]).hexdigest(),
        plan_receipt_sha256=verified_receipt.sha256,
    )


@_plan_boundary
def build_development_example_backtest_plan_artifact(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    output_root: Path,
) -> BacktestPlanManifestV1:
    """Build a closed development-only schedule without touching formal roots."""
    _require_empty_directory(output_root)
    _validate_inputs(target, release, folds, experiment, config)
    sessions = _sh_open_sessions(release)
    scheduled, diagnostics, window = _schedule_targets(target, folds, sessions)
    cost_payload = _cost_schedule_payload(config)
    cost_bytes = _canonical_bytes(cost_payload)

    scheduled_path = output_root / "scheduled_targets.parquet"
    diagnostics_path = output_root / "schedule_diagnostics.parquet"
    cost_path = output_root / "cost_schedule.json"
    _write_parquet(scheduled, scheduled_path)
    _write_parquet(diagnostics, diagnostics_path)
    _write_exclusive(cost_path, cost_bytes)
    manifest = _make_manifest(
        target=target,
        release=release,
        folds=folds,
        experiment=experiment,
        config=config,
        window=window,
        sessions=sessions,
        cost_bytes=cost_bytes,
        scheduled_path=scheduled_path,
        diagnostics_path=diagnostics_path,
    )
    _write_exclusive(output_root / "manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_plan_boundary
def verify_development_example_backtest_plan_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    upstream_paths: BacktestPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleBacktestPlanArtifact:
    """Freshly recompute the complete plan and receipt closure."""
    _validate_inputs(target, release, folds, experiment, config)
    _validate_upstream_bytes(target, release, folds, experiment, upstream_paths)
    if (
        not root.is_dir()
        or root.is_symlink()
        or {entry.name for entry in os.scandir(root)} != _FILES
    ):
        raise ValueError("backtest plan tree closure drift")
    manifest_raw = (root / "manifest.json").read_bytes()
    manifest = read_backtest_plan_manifest(root / "manifest.json")
    scheduled = _read_scheduled(root / "scheduled_targets.parquet")
    diagnostics = _read_diagnostics(root / "schedule_diagnostics.parquet")
    sessions = _sh_open_sessions(release)
    expected_scheduled, expected_diagnostics, window = _schedule_targets(
        target, folds, sessions
    )
    if not scheduled.equals(expected_scheduled) or not diagnostics.equals(
        expected_diagnostics
    ):
        raise ValueError("backtest plan content drift")
    cost_bytes = (root / "cost_schedule.json").read_bytes()
    if cost_bytes != _canonical_bytes(_cost_schedule_payload(config)):
        raise ValueError("backtest plan cost schedule drift")
    expected_manifest = _make_manifest(
        target=target,
        release=release,
        folds=folds,
        experiment=experiment,
        config=config,
        window=window,
        sessions=sessions,
        cost_bytes=cost_bytes,
        scheduled_path=root / "scheduled_targets.parquet",
        diagnostics_path=root / "schedule_diagnostics.parquet",
    )
    if manifest != expected_manifest:
        raise ValueError("backtest plan manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("backtest plan receipt missing")
    receipt = verified_receipt.receipt
    inputs = _receipt_inputs(target, release, folds, experiment, upstream_paths)
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != "development-backtest-plan"
        or receipt.scope != "WORK"
        or receipt.scope_key != target.manifest.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("backtest plan receipt closure drift")
    return VerifiedDevelopmentExampleBacktestPlanArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=target.example_id,
        root=root.resolve(strict=True),
        scheduled_targets=scheduled,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        plan_receipt_sha256=verified_receipt.sha256,
    )


@_plan_boundary
def read_backtest_plan_manifest(path: Path) -> BacktestPlanManifestV1:
    return _read_backtest_plan_manifest_bytes(path.read_bytes())


def _read_backtest_plan_manifest_bytes(raw: bytes) -> BacktestPlanManifestV1:
    payload = _strict_object(raw)
    if set(payload) != {field.name for field in fields(BacktestPlanManifestV1)}:
        raise ValueError("backtest plan manifest fields drift")
    window_raw = payload.get("window")
    if type(window_raw) is not dict:
        raise ValueError("backtest plan window invalid")
    window_fields = {field.name for field in fields(BacktestWindow)}
    if set(window_raw) != window_fields:
        raise ValueError("backtest plan window fields drift")
    window = BacktestWindow(
        signal_dates=tuple(
            dt.date.fromisoformat(cast(str, value))
            for value in cast(list[object], window_raw["signal_dates"])
        ),
        execution_dates=tuple(
            dt.date.fromisoformat(cast(str, value))
            for value in cast(list[object], window_raw["execution_dates"])
        ),
        first_execution_date=dt.date.fromisoformat(
            cast(str, window_raw["first_execution_date"])
        ),
        terminal_valuation_date=dt.date.fromisoformat(
            cast(str, window_raw["terminal_valuation_date"])
        ),
        force_liquidation=cast(Any, window_raw["force_liquidation"]),
    )
    values = dict(payload)
    values["window"] = window
    manifest = BacktestPlanManifestV1(**cast(Any, values))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("backtest plan manifest non-canonical")
    return manifest


def _validate_formal_outer(
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> None:
    if (
        type(target) is not VerifiedTargetArtifact
        or type(release) is not VerifiedG1Release
        or type(folds) is not VerifiedFoldPlanArtifact
        or type(experiment) is not VerifiedExperimentIdentity
        or type(config) is not LoadedM3Config
        or type(context) is not BacktestPlanFreshVerificationContext
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(type(name) is not str or not isinstance(path, Path)
               for name, path in artifact_roots.items())
    ):
        raise ValueError("formal backtest plan inputs invalid")
    planned = next(
        (item for item in folds.manifest.folds if item.name == target.manifest.fold),
        None,
    )
    if (
        planned is None
        or target.manifest.experiment_key != experiment.manifest.experiment_key
        or target.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or target.manifest.g1_release_id != release.manifest.release_id
        or target.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or target.manifest.fold_plan_manifest_sha256 != folds.manifest_sha256
        or target.manifest.scientific_config_sha256 != config.scientific_config_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or context.target_spec.work_key != target.manifest.work_key
        or context.target_spec.fold != target.manifest.fold
        or context.target_spec.horizon_sessions != target.manifest.horizon_sessions
    ):
        raise ValueError("formal backtest plan identity drift")
    _validate_formal_scientific_config(config)
    _formal_fresh_upstream_bytes(target, release, folds, experiment, context)


def _validate_formal_scientific_config(config: LoadedM3Config) -> None:
    backtest = config.section("backtest")
    a_share = backtest.get("a_share")
    if not isinstance(a_share, Mapping):
        raise ValueError("formal backtest plan config invalid")
    multipliers = a_share.get("friction_multipliers")
    if not isinstance(multipliers, Sequence) or isinstance(multipliers, (str, bytes)):
        raise ValueError("formal backtest plan multipliers invalid")
    rebuilt = tuple(Decimal(str(value)) for value in multipliers)
    if (
        rebuilt != (Decimal("0.5"), Decimal("1"), Decimal("2"))
        or a_share.get("execution_price_rounding")
        != "BUY_CEIL_SELL_FLOOR_TICK_V1"
        or a_share.get("fee_rounding") != "EACH_COMPONENT_HALF_UP_CENT_V1"
        or a_share.get("cash_settlement_rounding") != "HALF_UP_CENT_V1"
        or a_share.get("annualization_sessions") != 252
        or config.section("costs").get("scaled_components")
        != ("commission_rate", "commission_min", "slippage")
    ):
        raise ValueError("formal backtest plan scientific config drift")


def _fresh_target_once(
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    context: BacktestPlanFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedTargetArtifact:
    fresh = verify_target_artifact(
        root=target.root,
        receipt_path=context.target_receipt_path,
        release=release,
        snapshot=context.snapshot,
        snapshot_spec=context.snapshot_spec,
        provider=context.provider,
        provider_spec=context.provider_spec,
        experiment=experiment,
        experiment_spec=context.experiment_spec,
        folds=folds,
        fold_spec=context.fold_spec,
        feature=context.feature,
        feature_spec=context.feature_spec,
        label=context.label,
        label_spec=context.label_spec,
        alignment=context.alignment,
        alignment_spec=context.alignment_spec,
        model=context.model,
        model_spec=context.model_spec,
        prediction=context.prediction,
        prediction_spec=context.prediction_spec,
        config=config,
        spec=context.target_spec,
        upstream_paths=context.target_upstream_paths,
        artifact_roots=artifact_roots,
    )
    if (
        type(fresh) is not VerifiedTargetArtifact
        or Path(os.path.abspath(fresh.root)) != Path(os.path.abspath(target.root))
        or not fresh.targets.equals(target.targets)
        or not fresh.target_daily.equals(target.target_daily)
        or fresh.manifest != target.manifest
        or fresh.manifest_sha256 != target.manifest_sha256
        or fresh.target_receipt_sha256 != target.target_receipt_sha256
        or fresh.target_receipt_sha256 != _file_sha(context.target_receipt_path)
    ):
        raise ValueError("formal backtest plan fresh target mismatch")
    return fresh


def _formal_sh_open_sessions(release: VerifiedG1Release) -> tuple[dt.date, ...]:
    calendar_path = dict(release.artifact_paths)["trade_calendar.parquet"]
    raw = pl.read_parquet(calendar_path)
    calendar = TradeCalendarSchema.validate(raw)
    if not calendar.equals(raw):
        raise ValueError("formal SH calendar schema normalization forbidden")
    sessions = tuple(cast(
        list[dt.date],
        calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date").to_list(),
    ))
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("formal SH calendar physical order invalid")
    return sessions


def _formal_target_frame(target: VerifiedTargetArtifact) -> pl.DataFrame:
    frame = target.targets
    validated = TargetWeightSchema.validate(frame)
    if (
        not validated.equals(frame)
        or frame.columns != [
            "as_of", "strategy", "strategy_version", "symbol", "weight"
        ]
        or frame.n_unique(["as_of", "symbol"]) != frame.height
        or not frame.equals(frame.sort("as_of", "symbol"))
    ):
        raise ValueError("formal target physical order invalid")
    return frame


def _formal_schedule_targets(
    target: VerifiedTargetArtifact,
    folds: VerifiedFoldPlanArtifact,
    sessions: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame, BacktestWindow]:
    frame = _formal_target_frame(target)
    planned = next(
        item for item in folds.manifest.folds if item.name == target.manifest.fold
    )
    physical_dates = tuple(dict.fromkeys(cast(list[dt.date], frame["as_of"].to_list())))
    if physical_dates != planned.test_dates:
        raise ValueError("formal target signal domain drift")
    session_index = {day: index for index, day in enumerate(sessions)}
    executions: list[dt.date] = []
    for signal in planned.test_dates:
        index = session_index.get(signal)
        if index is None or index + 1 >= len(sessions):
            raise ValueError("formal backtest plan next SH session missing")
        executions.append(sessions[index + 1])
    by_signal = dict(zip(planned.test_dates, executions, strict=True))
    execution_column = [by_signal[day] for day in frame["as_of"].to_list()]
    scheduled = frame.with_columns(
        pl.Series("execution_date", execution_column, dtype=pl.Date)
    ).select(_SCHEDULED_COLUMNS)
    if not scheduled.equals(scheduled.sort("execution_date", "as_of", "symbol")):
        raise ValueError("formal scheduled target order invalid")
    diagnostics_rows: list[dict[str, object]] = []
    for signal, execution in zip(planned.test_dates, executions, strict=True):
        batch = frame.filter(pl.col("as_of") == signal)
        if batch.is_empty():
            raise ValueError("formal backtest plan empty signal batch")
        total = sum(
            (Decimal(str(value)) for value in batch["weight"].to_list()),
            Decimal(0),
        )
        diagnostics_rows.append({
            "as_of": signal,
            "execution_date": execution,
            "n_targets": batch.height,
            "total_target_weight": float(total),
            "session_lag": 1,
        })
    diagnostics = pl.DataFrame(diagnostics_rows, schema=_DIAGNOSTICS_SCHEMA)
    if not diagnostics.equals(diagnostics.sort("as_of")):
        raise ValueError("formal diagnostics order invalid")
    window = BacktestWindow(
        signal_dates=planned.test_dates,
        execution_dates=tuple(executions),
        first_execution_date=executions[0],
        terminal_valuation_date=executions[-1],
        force_liquidation=False,
    )
    return scheduled, diagnostics, window


def _formal_cost_schedule_payload(config: LoadedM3Config) -> dict[str, object]:
    _validate_formal_scientific_config(config)
    costs = config.section("costs")
    raw_periods = cast(Sequence[Mapping[str, object]], costs["a_share_periods"])
    periods = tuple(_cost_period(item) for item in raw_periods)
    _validate_cost_periods(periods)
    a_share = cast(Mapping[str, object], config.section("backtest")["a_share"])
    multipliers = tuple(
        Decimal(str(value))
        for value in cast(Sequence[object], a_share["friction_multipliers"])
    )
    return {
        "multipliers": [_decimal_text(value) for value in multipliers],
        "scaled_components": list(cast(tuple[str, ...], costs["scaled_components"])),
        "schedules": [
            {
                "multiplier": _decimal_text(multiplier),
                "periods": [_period_payload(period, multiplier) for period in periods],
            }
            for multiplier in multipliers
        ],
    }


def _require_cost_coverage(
    config: LoadedM3Config, execution_dates: tuple[dt.date, ...]
) -> None:
    periods = tuple(
        _cost_period(item)
        for item in cast(
            Sequence[Mapping[str, object]],
            config.section("costs")["a_share_periods"],
        )
    )
    _validate_cost_periods(periods)
    for day in execution_dates:
        matches = [
            period for period in periods
            if period.effective_from <= day
            and (period.effective_to is None or day <= period.effective_to)
        ]
        if len(matches) != 1:
            raise ValueError("formal backtest plan cost coverage invalid")


def _make_formal_manifest(
    *,
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    window: BacktestWindow,
    sessions: tuple[dt.date, ...],
    cost_raw: bytes,
    scheduled_raw: bytes,
    diagnostics_raw: bytes,
) -> BacktestPlanManifestV1:
    return BacktestPlanManifestV1(
        schema_version="m3-a-share-backtest-plan-v1",
        experiment_key=target.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        target_manifest_sha256=target.manifest_sha256,
        target_receipt_sha256=target.target_receipt_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        fold=target.manifest.fold,
        horizon_sessions=target.manifest.horizon_sessions,
        window=window,
        session_calendar_sha256=_sha256_json(
            [day.isoformat() for day in sessions]
        ),
        cost_schedule_sha256=hashlib.sha256(cost_raw).hexdigest(),
        cost_schedule_version=cast(str, config.section("costs")["schedule_version"]),
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scheduled_targets_sha256=hashlib.sha256(scheduled_raw).hexdigest(),
        schedule_diagnostics_sha256=hashlib.sha256(diagnostics_raw).hexdigest(),
    )


def _formal_g1_quality_path(release: VerifiedG1Release) -> Path:
    quality = release.release.quality_path
    expected = release.release.root / "quality.json"
    if (
        not isinstance(quality, Path)
        or quality.name != "quality.json"
        or quality != expected
    ):
        raise ValueError("formal backtest plan g1 quality path invalid")
    return quality


def _formal_fresh_upstream_bytes(
    target: VerifiedTargetArtifact,
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    context: BacktestPlanFreshVerificationContext,
) -> None:
    quality = _formal_g1_quality_path(release)
    paths = context.target_upstream_paths
    checks = (
        (target.root / "target_manifest.json", target.manifest_sha256),
        (context.target_receipt_path, target.target_receipt_sha256),
        (release.release.manifest_path, release.manifest_sha256),
        (quality, release.quality_sha256),
        (folds.root / "folds.json", folds.manifest_sha256),
        (paths.fold_receipt_path, folds.folds_receipt_sha256),
        (experiment.root / "experiment_manifest.json", experiment.manifest_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
    )
    if any(not path.is_file() or _file_sha(path) != digest for path, digest in checks):
        raise ValueError("formal backtest plan upstream bytes stale")


def _formal_receipt_inputs(
    release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    context: BacktestPlanFreshVerificationContext,
    target: VerifiedTargetArtifact,
) -> tuple[Path, ...]:
    paths = context.target_upstream_paths
    quality = _formal_g1_quality_path(release)
    inputs = (
        release.release.manifest_path,
        quality,
        dict(release.artifact_paths)["eligible_keys.parquet"],
        context.feature.root / "feature_manifest.json",
        paths.feature_receipt_path,
        context.feature.root / "coverage.parquet",
        context.feature.root / "test.parquet",
        context.prediction.root / "prediction_manifest.json",
        paths.prediction_receipt_path,
        context.prediction.root / "predictions.parquet",
        folds.root / "folds.json",
        paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
        paths.experiment_receipt_path,
        target.root / "target_manifest.json",
        context.target_receipt_path,
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
        dict(release.artifact_paths)["trade_calendar.parquet"],
    )
    if any(path.name == "receipt.json" for path in inputs[:3]):
        raise ValueError("formal backtest plan g1 receipt input forbidden")
    normalized = tuple(os.path.normcase(os.path.abspath(path)) for path in inputs)
    if len(inputs) != 19 or len(set(normalized)) != 19:
        raise ValueError("formal backtest plan receipt input duplicate")
    for index, left in enumerate(inputs):
        for right in inputs[index + 1:]:
            if os.path.samefile(left, right):
                raise ValueError("formal backtest plan receipt input alias")
    return inputs


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
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


def _read_formal_scheduled_bytes(raw: bytes) -> pl.DataFrame:
    frame = pl.read_parquet(io.BytesIO(raw))
    if (
        frame.columns != _SCHEDULED_COLUMNS
        or frame.schema != {
            "as_of": pl.Date,
            "strategy": pl.String,
            "strategy_version": pl.String,
            "symbol": pl.String,
            "weight": pl.Float64,
            "execution_date": pl.Date,
        }
        or not frame.equals(frame.sort("execution_date", "as_of", "symbol"))
        or not TargetWeightSchema.validate(frame.drop("execution_date")).equals(
            frame.drop("execution_date")
        )
    ):
        raise ValueError("formal scheduled target invalid")
    return frame


def _read_formal_diagnostics_bytes(raw: bytes) -> pl.DataFrame:
    frame = pl.read_parquet(io.BytesIO(raw))
    if (
        frame.columns != list(_DIAGNOSTICS_SCHEMA)
        or frame.schema != _DIAGNOSTICS_SCHEMA
        or not frame.equals(frame.sort("as_of"))
    ):
        raise ValueError("formal schedule diagnostics invalid")
    return frame


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _formal_tree_identity(root: Path) -> tuple[os.stat_result, dict[str, os.stat_result]]:
    root_info = os.lstat(root)
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or _is_link_or_reparse(root_info)
        or {item.name for item in os.scandir(root)} != _FILES
    ):
        raise ValueError("formal backtest plan tree invalid")
    files: dict[str, os.stat_result] = {}
    for name in _FILES:
        info = os.lstat(root / name)
        if not stat.S_ISREG(info.st_mode) or _is_link_or_reparse(info):
            raise ValueError("formal backtest plan entry invalid")
        files[name] = info
    return root_info, files


def _require_same_tree_identity(
    root: Path, identity: tuple[os.stat_result, dict[str, os.stat_result]]
) -> None:
    root_info, files = identity
    current_root = os.lstat(root)
    if (
        _is_link_or_reparse(current_root)
        or not os.path.samestat(root_info, current_root)
        or {item.name for item in os.scandir(root)} != _FILES
    ):
        raise ValueError("formal backtest plan root replaced")
    for name, expected in files.items():
        current = os.lstat(root / name)
        if _is_link_or_reparse(current) or not os.path.samestat(expected, current):
            raise ValueError("formal backtest plan file replaced")


def _stable_formal_tree_read(
    root: Path, identity: tuple[os.stat_result, dict[str, os.stat_result]]
) -> dict[str, bytes]:
    first = {name: (root / name).read_bytes() for name in sorted(_FILES)}
    _require_same_tree_identity(root, identity)
    second = {name: (root / name).read_bytes() for name in sorted(_FILES)}
    _require_same_tree_identity(root, identity)
    if first != second:
        raise ValueError("formal backtest plan unstable read")
    return first


def _validate_inputs(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
) -> None:
    if (
        type(target) is not VerifiedDevelopmentExampleTargetArtifact
        or type(release) is not VerifiedDevelopmentExampleG1Release
        or type(folds) is not VerifiedDevelopmentExampleFoldPlanArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or type(config) is not LoadedM3Config
    ):
        raise ValueError("backtest plan inputs invalid")
    planned = next(
        (item for item in folds.manifest.folds if item.name == target.manifest.fold), None
    )
    if (
        len({target.example_id, folds.example_id, experiment.example_id}) != 1
        or target.example_id != release.manifest.example_id
        or planned is None
        or target.manifest.experiment_key != experiment.manifest.experiment_key
        or target.manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or target.manifest.g1_release_id != release.manifest.release_id
        or target.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or target.manifest.fold_plan_manifest_sha256 != folds.manifest_sha256
        or target.manifest.horizon_sessions
        not in cast(tuple[int, ...], config.section("labels")["horizons_sessions"])
        or target.manifest.scientific_config_sha256 != config.scientific_config_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
    ):
        raise ValueError("backtest plan identity drift")
    manifest_path = target.root / "target_manifest.json"
    targets_path = target.root / "target_weights.parquet"
    daily_path = target.root / "target_daily.parquet"
    if (
        _file_sha(manifest_path) != target.manifest_sha256
        or read_target_manifest(manifest_path) != target.manifest
        or not _read_target_weights(targets_path).equals(target.targets)
        or not pl.read_parquet(daily_path).equals(target.target_daily)
    ):
        raise ValueError("backtest plan target capability stale")
    targets = _read_target_weights(targets_path)
    signal_dates = tuple(sorted(set(cast(list[dt.date], targets["as_of"].to_list()))))
    if (
        signal_dates != planned.test_dates
        or any(not symbol.endswith((".SH", ".SZ")) for symbol in targets["symbol"])
        or targets["strategy"].n_unique() != 1
        or targets["strategy_version"].n_unique() != 1
        or targets.item(0, "strategy") != target.manifest.strategy
        or targets.item(0, "strategy_version") != target.manifest.strategy_version
    ):
        raise ValueError("backtest plan target domain invalid")


def _sh_open_sessions(
    release: VerifiedDevelopmentExampleG1Release,
) -> tuple[dt.date, ...]:
    path = dict(release.artifact_paths)["trade_calendar.parquet"]
    calendar = TradeCalendarSchema.validate(pl.read_parquet(path))
    sessions = tuple(
        cast(
            list[dt.date],
            calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))
            .sort("date")
            .get_column("date")
            .to_list(),
        )
    )
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("backtest plan SH calendar invalid")
    return sessions


def _schedule_targets(
    target: VerifiedDevelopmentExampleTargetArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    sessions: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame, BacktestWindow]:
    planned = next(item for item in folds.manifest.folds if item.name == target.manifest.fold)
    signals = planned.test_dates
    execution: list[dt.date] = []
    for signal in signals:
        following = next((day for day in sessions if day > signal), None)
        if following is None:
            raise ValueError("backtest plan missing next execution session")
        execution.append(following)
    mapping = pl.DataFrame(
        {"as_of": signals, "execution_date": execution},
        schema={"as_of": pl.Date, "execution_date": pl.Date},
    )
    scheduled = (
        target.targets.join(mapping, on="as_of", how="left")
        .select(_SCHEDULED_COLUMNS)
        .sort("execution_date", "as_of", "symbol")
    )
    if scheduled["execution_date"].null_count() or scheduled.height != target.targets.height:
        raise ValueError("backtest plan incomplete signal batch")
    diagnostics_rows: list[dict[str, object]] = []
    for signal, execution_date in zip(signals, execution, strict=True):
        batch = target.targets.filter(pl.col("as_of") == signal)
        if batch.is_empty():
            raise ValueError("backtest plan empty signal batch")
        diagnostics_rows.append(
            {
                "as_of": signal,
                "execution_date": execution_date,
                "n_targets": batch.height,
                "total_target_weight": float(batch["weight"].sum()),
                "session_lag": 1,
            }
        )
    diagnostics = pl.DataFrame(diagnostics_rows, schema=_DIAGNOSTICS_SCHEMA).sort(
        "as_of"
    )
    window = BacktestWindow(
        signal_dates=signals,
        execution_dates=tuple(execution),
        first_execution_date=execution[0],
        terminal_valuation_date=execution[-1],
        force_liquidation=False,
    )
    return scheduled, diagnostics, window


def _cost_schedule_payload(config: LoadedM3Config) -> dict[str, object]:
    costs = config.section("costs")
    raw_periods = cast(Sequence[Mapping[str, object]], costs["a_share_periods"])
    base = tuple(_cost_period(item) for item in raw_periods)
    _validate_cost_periods(base)
    multipliers = (Decimal("0.5"), Decimal("1"), Decimal("2"))
    schedules: list[dict[str, object]] = []
    for multiplier in multipliers:
        schedules.append(
            {
                "multiplier": _decimal_text(multiplier),
                "periods": [
                    _period_payload(period, multiplier) for period in base
                ],
            }
        )
    return {
        "multipliers": [_decimal_text(value) for value in multipliers],
        "scaled_components": list(cast(tuple[str, ...], costs["scaled_components"])),
        "schedules": schedules,
    }


def _cost_period(raw: Mapping[str, object]) -> AShareCostPeriod:
    return AShareCostPeriod(
        effective_from=cast(dt.date, raw["effective_from"]),
        effective_to=cast(dt.date | None, raw.get("effective_to")),
        commission_rate=Decimal(str(raw["commission_rate"])),
        commission_min=Decimal(str(raw["commission_min"])),
        stamp_tax_sell=Decimal(str(raw["stamp_tax_sell"])),
        transfer_fee=Decimal(str(raw["transfer_fee"])),
        slippage=Decimal(str(raw["slippage"])),
    )


def _validate_cost_periods(periods: tuple[AShareCostPeriod, ...]) -> None:
    if not periods:
        raise ValueError("backtest plan cost schedule empty")
    for index, period in enumerate(periods):
        if (period.effective_to is None) != (index == len(periods) - 1):
            raise ValueError("backtest plan open cost interval invalid")
        if index:
            previous = periods[index - 1]
            assert previous.effective_to is not None
            if period.effective_from != previous.effective_to + dt.timedelta(days=1):
                raise ValueError("backtest plan cost intervals not contiguous")


def _period_payload(period: AShareCostPeriod, multiplier: Decimal) -> dict[str, object]:
    return {
        "effective_from": period.effective_from.isoformat(),
        "effective_to": (
            None if period.effective_to is None else period.effective_to.isoformat()
        ),
        "commission_rate": _decimal_text(period.commission_rate * multiplier),
        "commission_min": _decimal_text(period.commission_min * multiplier),
        "stamp_tax_sell": _decimal_text(period.stamp_tax_sell),
        "transfer_fee": _decimal_text(period.transfer_fee),
        "slippage": _decimal_text(period.slippage * multiplier),
    }


def _make_manifest(
    *,
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    window: BacktestWindow,
    sessions: tuple[dt.date, ...],
    cost_bytes: bytes,
    scheduled_path: Path,
    diagnostics_path: Path,
) -> BacktestPlanManifestV1:
    return BacktestPlanManifestV1(
        schema_version="m3-a-share-backtest-plan-v1",
        experiment_key=target.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=target.manifest.work_key,
        target_manifest_sha256=target.manifest_sha256,
        target_receipt_sha256=target.target_receipt_sha256,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        fold=target.manifest.fold,
        horizon_sessions=target.manifest.horizon_sessions,
        window=window,
        session_calendar_sha256=_sha256_json(
            [day.isoformat() for day in sessions]
        ),
        cost_schedule_sha256=hashlib.sha256(cost_bytes).hexdigest(),
        cost_schedule_version=cast(str, config.section("costs")["schedule_version"]),
        order_quantity_rule_version=G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION,
        scheduled_targets_sha256=_file_sha(scheduled_path),
        schedule_diagnostics_sha256=_file_sha(diagnostics_path),
    )


def _validate_upstream_bytes(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestPlanUpstreamPaths,
) -> None:
    checks = (
        (target.root / "target_manifest.json", target.manifest_sha256),
        (paths.target_receipt_path, target.target_receipt_sha256),
        (release.release.manifest_path, release.manifest_sha256),
        (release.release.root / "receipt.json", release.receipt_sha256),
        (folds.root / "folds.json", folds.manifest_sha256),
        (paths.fold_receipt_path, folds.folds_receipt_sha256),
        (experiment.root / "experiment_manifest.json", experiment.manifest_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
    )
    if any(not path.is_file() or _file_sha(path) != digest for path, digest in checks):
        raise ValueError("backtest plan upstream bytes stale")


def _receipt_inputs(
    target: VerifiedDevelopmentExampleTargetArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: BacktestPlanUpstreamPaths,
) -> tuple[Path, ...]:
    return (
        target.root / "target_manifest.json",
        paths.target_receipt_path,
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
        release.release.manifest_path,
        release.release.root / "receipt.json",
        dict(release.artifact_paths)["trade_calendar.parquet"],
        folds.root / "folds.json",
        paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
        paths.experiment_receipt_path,
    )


def _read_target_weights(path: Path) -> pl.DataFrame:
    frame = TargetWeightSchema.validate(pl.read_parquet(path)).sort("as_of", "symbol")
    if frame.columns != [
        "as_of", "strategy", "strategy_version", "symbol", "weight"
    ] or frame.n_unique(["as_of", "symbol"]) != frame.height:
        raise ValueError("backtest plan target schema drift")
    return frame


def _read_scheduled(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.columns != _SCHEDULED_COLUMNS or frame.schema != {
        "as_of": pl.Date,
        "strategy": pl.String,
        "strategy_version": pl.String,
        "symbol": pl.String,
        "weight": pl.Float64,
        "execution_date": pl.Date,
    }:
        raise ValueError("backtest scheduled targets schema drift")
    TargetWeightSchema.validate(frame.drop("execution_date"))
    if not frame.equals(frame.sort("execution_date", "as_of", "symbol")):
        raise ValueError("backtest scheduled targets order drift")
    return frame


def _read_diagnostics(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if (
        frame.columns != list(_DIAGNOSTICS_SCHEMA)
        or frame.schema != _DIAGNOSTICS_SCHEMA
        or not frame.equals(frame.sort("as_of"))
    ):
        raise ValueError("backtest schedule diagnostics drift")
    return frame


def _strict_object(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value


def _canonical_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...],
    paths: Sequence[Path],
    roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(
        sorted(
            os.path.normcase(
                os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots))
            )
            for item in digests
        )
    )
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("backtest plan output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o644,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )


__all__ = [
    "AShareCostPeriod",
    "BacktestPlanFreshVerificationContext",
    "BacktestPlanManifestV1",
    "BacktestPlanUpstreamPaths",
    "BacktestWindow",
    "G7_A_SHARE_ORDER_QUANTITY_RULE_VERSION",
    "build_backtest_plan_artifact",
    "build_development_example_backtest_plan_artifact",
    "read_backtest_plan_manifest",
    "verify_backtest_plan_artifact",
    "verify_development_example_backtest_plan_artifact",
]
