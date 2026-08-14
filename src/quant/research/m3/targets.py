"""Deterministic complete-domain target artifacts for the M3 development chain."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from decimal import Context, Decimal, ROUND_DOWN
from functools import wraps
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.data.m3_release import VerifiedG1Release
from quant.domain import TargetWeightSchema
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactPublicationError,
    ArtifactRollbackError,
)
from quant.research.m3.alignment import (
    _read_feature_segment,
    _scorable_expression,
    build_inference_segment,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    InferenceUpstreamPaths,
    LabelBuildSpec,
    LightgbmTrainingSpec,
    PredictionBuildSpec,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    TargetBuildSpec,
    TargetManifestV1,
    TargetUpstreamPaths,
    VerifiedAlignmentArtifact,
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
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFeatureArtifact,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExamplePredictionArtifact,
    VerifiedDevelopmentExampleTargetArtifact,
)
from quant.research.m3.features import canonical_row_keys_sha256
from quant.research.m3.predictions import verify_prediction_artifact
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_FILES = {"target_daily.parquet", "target_manifest.json", "target_weights.parquet"}
_DAILY_SCHEMA = {
    "as_of": pl.Date,
    "n_eligible": pl.Int64,
    "n_scorable": pl.Int64,
    "n_predicted": pl.Int64,
    "n_selected": pl.Int64,
    "scorable_coverage": pl.Float64,
    "total_target_weight": pl.Float64,
}
_P = ParamSpec("_P")
_T = TypeVar("_T")
_TARGET_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_DOWN)


def _target_allocation(
    *, cash_buffer: float, max_weight: float, n_selected: int,
) -> tuple[Decimal, Decimal]:
    """Return one weight and total without using the caller's Decimal context."""
    if n_selected < 1:
        raise ValueError("target empty selection")
    context = _TARGET_DECIMAL_CONTEXT.copy()
    cash = Decimal(str(cash_buffer))
    cap = Decimal(str(max_weight))
    investable = context.subtract(Decimal(1), cash)
    count = Decimal(n_selected)
    capped = Fraction(cap) * n_selected <= Fraction(investable)
    weight = cap if capped else context.divide(investable, count)
    total = context.multiply(weight, count)
    if total > investable:
        raise ValueError("target decimal allocation exceeds investable")
    return weight, total


def _formal_target_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    """Expose only stable, redacted formal target failures."""

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
            raise ValueError("M3_TARGET_ROLLBACK_FAILED") from None
        raise ValueError("M3_TARGET_ARTIFACT_INVALID") from None

    return wrapped


def _target_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_TARGET_ARTIFACT_INVALID") from None

    return wrapped


def build_target_spec(
    *,
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
) -> TargetBuildSpec:
    if len({feature.example_id, prediction.example_id, folds.example_id, experiment.example_id}) != 1:
        raise ValueError("target spec development identity mismatch")
    if feature.manifest.g1_release_id != release.manifest.release_id:
        raise ValueError("target spec release mismatch")
    portfolio = config.section("portfolio")
    features = config.section("features")
    return TargetBuildSpec(
        experiment_key=prediction.manifest.experiment_key,
        work_key=prediction.manifest.work_key,
        fold=prediction.manifest.fold,
        horizon_sessions=cast(Any, prediction.manifest.horizon_sessions),
        strategy=cast(Any, portfolio["strategy"]),
        strategy_version=cast(str, portfolio["strategy_version"]),
        top_k=cast(int, portfolio["top_k"]),
        cash_buffer=cast(float, portfolio["cash_buffer"]),
        max_weight=cast(float, portfolio["max_weight"]),
        minimum_scorable_coverage=cast(float, features["minimum_scorable_coverage"]),
    )


@_formal_target_boundary
def build_target_artifact(
    *,
    release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec,
    prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
    upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> TargetManifestV1:
    """Build a formal complete-domain target from a fresh G1--G5B chain."""
    _validate_formal_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        prediction=prediction, prediction_spec=prediction_spec, config=config,
        spec=spec, upstream_paths=upstream_paths, output_root=output_root,
    )
    with ArtifactPublication(output_root) as publication:
        targets, daily = _fresh_formal_target_frames(
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec,
            experiment=experiment, experiment_spec=experiment_spec,
            folds=folds, fold_spec=fold_spec, feature=feature,
            feature_spec=feature_spec, label=label, label_spec=label_spec,
            alignment=alignment, alignment_spec=alignment_spec, model=model,
            model_spec=model_spec, prediction=prediction,
            prediction_spec=prediction_spec, config=config, spec=spec,
            upstream_paths=upstream_paths, artifact_roots=artifact_roots,
        )
        targets_raw = _parquet_bytes(targets)
        daily_raw = _parquet_bytes(daily)
        manifest = _formal_target_manifest(
            release=release, feature=feature, prediction=prediction,
            folds=folds, experiment=experiment, config=config, spec=spec,
            targets=targets, daily=daily,
            targets_sha=hashlib.sha256(targets_raw).hexdigest(),
            daily_sha=hashlib.sha256(daily_raw).hexdigest(),
        )
        publication.write_bytes("target_weights.parquet", targets_raw)
        publication.write_bytes("target_daily.parquet", daily_raw)
        publication.write_bytes(
            "target_manifest.json", _canonical_bytes(asdict(manifest))
        )
        if (
            not _read_targets(output_root / "target_weights.parquet").equals(targets)
            or not _read_target_daily(output_root / "target_daily.parquet").equals(daily)
            or read_target_manifest(output_root / "target_manifest.json") != manifest
        ):
            raise ArtifactPublicationError
        publication.commit(_FILES)
        return manifest


@_formal_target_boundary
def verify_target_artifact(
    *,
    root: Path,
    receipt_path: Path,
    release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec,
    prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
    upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedTargetArtifact:
    """Freshly reconstruct and verify one formal target and exact receipt."""
    _validate_formal_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        prediction=prediction, prediction_spec=prediction_spec, config=config,
        spec=spec, upstream_paths=upstream_paths, output_root=root,
        require_empty_output=False,
    )
    expected_targets, expected_daily = _fresh_formal_target_frames(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        folds=folds, fold_spec=fold_spec, feature=feature,
        feature_spec=feature_spec, label=label, label_spec=label_spec,
        alignment=alignment, alignment_spec=alignment_spec, model=model,
        model_spec=model_spec, prediction=prediction,
        prediction_spec=prediction_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots,
    )
    if (
        not root.is_dir()
        or root.is_symlink()
        or {item.name for item in os.scandir(root)} != _FILES
    ):
        raise ValueError("formal target tree drift")
    raw_manifest = (root / "target_manifest.json").read_bytes()
    targets = _read_targets(root / "target_weights.parquet")
    daily = _read_target_daily(root / "target_daily.parquet")
    manifest = read_target_manifest(root / "target_manifest.json")
    if not targets.equals(expected_targets) or not daily.equals(expected_daily):
        raise ValueError("formal target content drift")
    expected_manifest = _formal_target_manifest(
        release=release, feature=feature, prediction=prediction,
        folds=folds, experiment=experiment, config=config, spec=spec,
        targets=targets, daily=daily,
        targets_sha=_file_sha(root / "target_weights.parquet"),
        daily_sha=_file_sha(root / "target_daily.parquet"),
    )
    if manifest != expected_manifest:
        raise ValueError("formal target manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("formal target receipt missing")
    inputs = _formal_receipt_inputs(
        release, feature, prediction, folds, experiment, upstream_paths
    )
    outputs = tuple(root / name for name in sorted(_FILES))
    receipt = verified_receipt.receipt
    if (
        receipt.stage != "targets"
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("formal target receipt closure drift")
    return VerifiedTargetArtifact(
        root=root.resolve(strict=True), targets=targets, target_daily=daily,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        target_receipt_sha256=verified_receipt.sha256,
    )


@_target_boundary
def build_development_example_target_artifact(
    *,
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
    output_root: Path,
) -> TargetManifestV1:
    _validate_identity(release, feature, prediction, folds, experiment, config, spec)
    _require_empty_directory(output_root)
    targets, daily = _build_target_frames(release, feature, prediction, folds, spec)
    targets_path = output_root / "target_weights.parquet"
    daily_path = output_root / "target_daily.parquet"
    _write_parquet(targets, targets_path)
    _write_parquet(daily, daily_path)
    manifest = _target_manifest(
        release, feature, prediction, folds, experiment, config, spec,
        targets, daily, targets_path, daily_path,
    )
    _write_exclusive(output_root / "target_manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_target_boundary
def verify_development_example_target_artifact(
    *,
    root: Path,
    receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
    upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleTargetArtifact:
    _validate_identity(release, feature, prediction, folds, experiment, config, spec)
    _fresh_upstream_bytes(release, feature, prediction, folds, experiment, upstream_paths)
    if not root.is_dir() or root.is_symlink() or {item.name for item in os.scandir(root)} != _FILES:
        raise ValueError("target tree closure drift")
    raw_manifest = (root / "target_manifest.json").read_bytes()
    manifest = read_target_manifest(root / "target_manifest.json")
    targets = _read_targets(root / "target_weights.parquet")
    daily = _read_target_daily(root / "target_daily.parquet")
    expected_targets, expected_daily = _build_target_frames(
        release, feature, prediction, folds, spec
    )
    if not targets.equals(expected_targets) or not daily.equals(expected_daily):
        raise ValueError("target content drift")
    expected_manifest = _target_manifest(
        release, feature, prediction, folds, experiment, config, spec,
        targets, daily, root / "target_weights.parquet", root / "target_daily.parquet",
    )
    if manifest != expected_manifest:
        raise ValueError("target manifest/content drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("target receipt missing")
    receipt = verified_receipt.receipt
    inputs = _receipt_inputs(release, feature, prediction, folds, experiment, upstream_paths)
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != "development-targets"
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("target receipt closure drift")
    return VerifiedDevelopmentExampleTargetArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=prediction.example_id,
        root=root.resolve(strict=True),
        targets=targets,
        target_daily=daily,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        target_receipt_sha256=verified_receipt.sha256,
    )


def read_target_manifest(path: Path) -> TargetManifestV1:
    raw = path.read_bytes()
    payload = _strict_object(raw)
    if set(payload) != {field.name for field in fields(TargetManifestV1)}:
        raise ValueError("target manifest fields drift")
    manifest = TargetManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("target manifest non-canonical")
    return manifest


def target_keys_sha256(targets: pl.DataFrame) -> str:
    return canonical_row_keys_sha256(tuple(
        (row[0].isoformat(), row[1])
        for row in targets.select("as_of", "symbol").iter_rows()
    ))


def _validate_formal_inputs(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec, alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec, model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec, prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec, config: LoadedM3Config,
    spec: TargetBuildSpec, upstream_paths: TargetUpstreamPaths,
    output_root: Path, require_empty_output: bool = True,
) -> None:
    exact = (
        (release, VerifiedG1Release), (snapshot, VerifiedSnapshotArtifact),
        (snapshot_spec, SnapshotBuildSpec), (provider, VerifiedProviderArtifact),
        (provider_spec, ProviderBuildSpec),
        (experiment, VerifiedExperimentIdentity),
        (experiment_spec, ExperimentIdentitySpec),
        (folds, VerifiedFoldPlanArtifact), (fold_spec, FoldPlanBuildSpec),
        (feature, VerifiedFeatureArtifact), (feature_spec, FeatureBuildSpec),
        (label, VerifiedLabelArtifact), (label_spec, LabelBuildSpec),
        (alignment, VerifiedAlignmentArtifact),
        (alignment_spec, AlignmentBuildSpec), (model, VerifiedModelArtifact),
        (model_spec, LightgbmTrainingSpec),
        (prediction, VerifiedPredictionArtifact),
        (prediction_spec, PredictionBuildSpec), (config, LoadedM3Config),
        (spec, TargetBuildSpec), (upstream_paths, TargetUpstreamPaths),
    )
    if any(type(value) is not expected for value, expected in exact):
        raise ValueError("formal target requires exact formal inputs")
    if not isinstance(output_root, Path):
        raise ValueError("formal target output root invalid")
    if require_empty_output and (
        not output_root.is_dir()
        or output_root.is_symlink()
        or any(output_root.iterdir())
    ):
        raise ValueError("formal target output must be empty")
    portfolio = config.section("portfolio")
    features = config.section("features")
    expected = TargetBuildSpec(
        experiment_key=prediction.manifest.experiment_key,
        work_key=prediction.manifest.work_key,
        fold=prediction.manifest.fold,
        horizon_sessions=cast(Any, prediction.manifest.horizon_sessions),
        strategy=cast(Any, portfolio["strategy"]),
        strategy_version=cast(str, portfolio["strategy_version"]),
        top_k=cast(int, portfolio["top_k"]),
        cash_buffer=cast(float, portfolio["cash_buffer"]),
        max_weight=cast(float, portfolio["max_weight"]),
        minimum_scorable_coverage=cast(
            float, features["minimum_scorable_coverage"]
        ),
    )
    planned = next(
        (item for item in folds.manifest.folds if item.name == spec.fold), None
    )
    test = next(
        (item for item in feature.manifest.segments if item.name == "test"), None
    )
    if (
        expected != spec
        or planned is None
        or test is None
        or prediction_spec.experiment_key != spec.experiment_key
        or prediction_spec.work_key != spec.work_key
        or prediction_spec.fold != spec.fold
        or prediction_spec.horizon_sessions != spec.horizon_sessions
        or prediction.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or prediction.manifest.eligibility_sha256 != test.eligible_keys_sha256
        or prediction.manifest.signal_dates_sha256
        != folds.manifest.signal_dates_sha256
        or prediction.manifest.n_eligible != test.n_eligible
        or prediction.manifest.n_scorable != test.n_scorable
        or prediction.manifest.n_predicted != test.n_scorable
        or feature.manifest.planned_fold_sha256 != planned.planned_fold_sha256
        or feature.manifest.experiment_key != experiment.manifest.experiment_key
        or feature.manifest.g1_release_id != release.manifest.release_id
        or feature.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or label.manifest.experiment_key != spec.experiment_key
        or label.manifest.horizon_sessions != spec.horizon_sessions
        or alignment.manifest.work_key != spec.work_key
        or alignment.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or alignment.manifest.label_manifest_sha256 != label.manifest_sha256
        or model.manifest.work_key != spec.work_key
        or model.manifest.alignment_manifest_sha256 != alignment.manifest_sha256
        or model.manifest.model_version != prediction.manifest.model_version
        or config.scientific_config_sha256
        != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("formal target identity/config drift")
    _validate_formal_upstream_paths(upstream_paths)
    _formal_fresh_upstream_bytes(
        release, feature, prediction, folds, experiment, upstream_paths
    )


def _validate_formal_upstream_paths(paths: TargetUpstreamPaths) -> None:
    prediction = paths.prediction_upstream_paths
    alignment = prediction.model_upstream_paths.alignment_upstream_paths
    feature_paths = (
        paths.feature_receipt_path,
        prediction.feature_receipt_path,
        alignment.feature_receipt_path,
    )
    fold_paths = (
        paths.fold_receipt_path,
        prediction.fold_receipt_path,
        prediction.feature_upstream_paths.fold_receipt_path,
        alignment.feature_upstream_paths.fold_receipt_path,
    )
    experiment_paths = (
        paths.experiment_receipt_path,
        prediction.feature_upstream_paths.fold_upstream_paths.experiment_receipt_path,
        alignment.feature_upstream_paths.fold_upstream_paths.experiment_receipt_path,
    )
    if not all(_all_exact_paths(group) for group in (
        feature_paths, fold_paths, experiment_paths,
    )):
        raise ValueError("formal target upstream path drift")


def _all_exact_paths(paths: Sequence[Path]) -> bool:
    normalized = tuple(os.path.normcase(os.path.abspath(path)) for path in paths)
    if len(set(normalized)) != 1:
        return False
    try:
        return all(os.path.samefile(paths[0], path) for path in paths[1:])
    except OSError:
        return False


def _fresh_formal_target_frames(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec, alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec, model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec, prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec, config: LoadedM3Config,
    spec: TargetBuildSpec, upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    fresh_prediction = verify_prediction_artifact(
        root=prediction.root,
        receipt_path=upstream_paths.prediction_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        config=config, spec=prediction_spec,
        upstream_paths=upstream_paths.prediction_upstream_paths,
        artifact_roots=artifact_roots,
    )
    if not _same_formal_prediction(fresh_prediction, prediction):
        raise ValueError("formal target prediction stale")
    inference = build_inference_segment(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, config=config,
        fold_name=spec.fold,
        upstream_paths=InferenceUpstreamPaths(
            feature_receipt_path=upstream_paths.feature_receipt_path,
            feature_upstream_paths=(
                upstream_paths.prediction_upstream_paths.feature_upstream_paths
            ),
        ),
        artifact_roots=artifact_roots,
    )
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    eligible = _formal_eligible_keys(release, planned.test_dates)
    scorable = inference.metadata
    if tuple(scorable.columns) != ("as_of", "symbol"):
        raise ValueError("formal target scorable schema drift")
    return _build_frames_from_layers(
        eligible=eligible, scorable=scorable,
        predictions=fresh_prediction.predictions, dates=planned.test_dates,
        spec=spec,
    )


def _same_formal_prediction(
    left: VerifiedPredictionArtifact, right: VerifiedPredictionArtifact,
) -> bool:
    return (
        type(left) is VerifiedPredictionArtifact
        and left.root == right.root
        and left.predictions.equals(right.predictions)
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.prediction_receipt_sha256 == right.prediction_receipt_sha256
    )


def _formal_eligible_keys(
    release: VerifiedG1Release, dates: tuple[dt.date, ...],
) -> pl.DataFrame:
    frame = (
        pl.read_parquet(dict(release.artifact_paths)["eligible_keys.parquet"])
        .select("as_of", "symbol")
        .filter(pl.col("as_of").is_in(list(dates)))
    )
    rows = tuple(cast(tuple[dt.date, str], row) for row in frame.iter_rows())
    if rows != tuple(sorted(rows)) or len(rows) != len(set(rows)):
        raise ValueError("formal target eligible order/keys drift")
    if set(frame.get_column("as_of").to_list()) != set(dates):
        raise ValueError("formal target eligible dates drift")
    return frame


def _build_frames_from_layers(
    *, eligible: pl.DataFrame, scorable: pl.DataFrame,
    predictions: pl.DataFrame, dates: tuple[dt.date, ...], spec: TargetBuildSpec,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    eligible_rows = tuple(eligible.select("as_of", "symbol").iter_rows())
    scorable_rows = tuple(scorable.select("as_of", "symbol").iter_rows())
    prediction_rows = tuple(predictions.select("as_of", "symbol").iter_rows())
    ordered_predictions = predictions.sort("as_of", "rank")
    if (
        tuple(dates) != tuple(sorted(set(dates)))
        or scorable_rows != tuple(sorted(scorable_rows))
        or len(scorable_rows) != len(set(scorable_rows))
        or not predictions.equals(ordered_predictions)
        or len(prediction_rows) != len(set(prediction_rows))
        or not set(scorable_rows) <= set(eligible_rows)
        or set(prediction_rows) != set(scorable_rows)
    ):
        raise ValueError("formal target key/order layer drift")
    target_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    threshold = Decimal(str(spec.minimum_scorable_coverage))
    for day in dates:
        day_eligible = eligible.filter(pl.col("as_of") == day)
        day_scorable = scorable.filter(pl.col("as_of") == day)
        day_predictions = predictions.filter(pl.col("as_of") == day)
        n_eligible = day_eligible.height
        n_scorable = day_scorable.height
        n_predicted = day_predictions.height
        if n_eligible == 0 or n_predicted == 0 or n_scorable != n_predicted:
            raise ValueError("formal target daily domain incomplete")
        coverage = Decimal(n_scorable) / Decimal(n_eligible)
        if coverage < threshold:
            raise ValueError("formal target scorable coverage below minimum")
        selected = day_predictions.head(spec.top_k)
        n_selected = selected.height
        if n_selected == 0:
            raise ValueError("formal target empty selection")
        selected_symbols = set(cast(list[str], selected.get_column("symbol").to_list()))
        weight, total = _target_allocation(
            cash_buffer=spec.cash_buffer,
            max_weight=spec.max_weight,
            n_selected=n_selected,
        )
        for symbol in cast(list[str], day_eligible.get_column("symbol").to_list()):
            target_rows.append({
                "as_of": day, "strategy": spec.strategy,
                "strategy_version": spec.strategy_version, "symbol": symbol,
                "weight": float(weight if symbol in selected_symbols else Decimal(0)),
            })
        daily_rows.append({
            "as_of": day, "n_eligible": n_eligible,
            "n_scorable": n_scorable, "n_predicted": n_predicted,
            "n_selected": n_selected, "scorable_coverage": float(coverage),
            "total_target_weight": float(total),
        })
    targets = TargetWeightSchema.validate(pl.DataFrame(target_rows))
    daily = pl.DataFrame(daily_rows, schema=_DAILY_SCHEMA)
    if (
        tuple(targets.select("as_of", "symbol").iter_rows()) != eligible_rows
        or tuple(daily.get_column("as_of").to_list()) != dates
    ):
        raise ValueError("formal target output order drift")
    return targets, daily


def _formal_target_manifest(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: TargetBuildSpec, targets: pl.DataFrame, daily: pl.DataFrame,
    targets_sha: str, daily_sha: str,
) -> TargetManifestV1:
    test = next(item for item in feature.manifest.segments if item.name == "test")
    if target_keys_sha256(targets) != test.eligible_keys_sha256:
        raise ValueError("formal target eligibility identity drift")
    return TargetManifestV1(
        schema_version="m3-target-artifact-v1",
        experiment_key=spec.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=spec.work_key, g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        prediction_manifest_sha256=prediction.manifest_sha256,
        feature_manifest_sha256=feature.manifest_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        snapshot_id=prediction.manifest.snapshot_id, fold=spec.fold,
        horizon_sessions=spec.horizon_sessions,
        model=prediction.manifest.model,
        model_version=prediction.manifest.model_version,
        strategy=spec.strategy, strategy_version=spec.strategy_version,
        eligible_keys_sha256=test.eligible_keys_sha256,
        signal_dates_sha256=folds.manifest.signal_dates_sha256,
        n_dates=daily.height,
        n_eligible=int(daily.get_column("n_eligible").sum()),
        n_scorable=int(daily.get_column("n_scorable").sum()),
        n_predicted=int(daily.get_column("n_predicted").sum()),
        n_selected=int(daily.get_column("n_selected").sum()),
        target_keys_sha256=target_keys_sha256(targets),
        targets_sha256=targets_sha, target_daily_sha256=daily_sha,
    )


def _formal_g1_quality_path(release: VerifiedG1Release) -> Path:
    quality = release.release.quality_path
    expected = release.release.root / "quality.json"
    if (
        not isinstance(quality, Path)
        or quality.name != "quality.json"
        or quality != expected
    ):
        raise ValueError("formal target g1 quality path invalid")
    return quality


def _formal_fresh_upstream_bytes(
    release: VerifiedG1Release,
    feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact,
    folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity,
    paths: TargetUpstreamPaths,
) -> None:
    quality = _formal_g1_quality_path(release)
    checks = (
        (release.release.manifest_path, release.manifest_sha256),
        (quality, release.quality_sha256),
        (feature.root / "feature_manifest.json", feature.manifest_sha256),
        (paths.feature_receipt_path, feature.feature_receipt_sha256),
        (prediction.root / "prediction_manifest.json", prediction.manifest_sha256),
        (paths.prediction_receipt_path, prediction.prediction_receipt_sha256),
        (folds.root / "folds.json", folds.manifest_sha256),
        (paths.fold_receipt_path, folds.folds_receipt_sha256),
        (experiment.root / "experiment_manifest.json", experiment.manifest_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
    )
    if any(not path.is_file() or _file_sha(path) != digest for path, digest in checks):
        raise ValueError("formal target upstream bytes stale")


def _formal_receipt_inputs(
    release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity, paths: TargetUpstreamPaths,
) -> tuple[Path, ...]:
    quality = _formal_g1_quality_path(release)
    inputs = (
        release.release.manifest_path,
        quality,
        dict(release.artifact_paths)["eligible_keys.parquet"],
        feature.root / "feature_manifest.json", paths.feature_receipt_path,
        feature.root / "coverage.parquet", feature.root / "test.parquet",
        prediction.root / "prediction_manifest.json", paths.prediction_receipt_path,
        prediction.root / "predictions.parquet",
        folds.root / "folds.json", paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json", paths.experiment_receipt_path,
    )
    if any(path.name == "receipt.json" for path in inputs[:3]):
        raise ValueError("formal target g1 receipt input forbidden")
    normalized = tuple(os.path.normcase(os.path.abspath(path)) for path in inputs)
    if len(set(normalized)) != 14:
        raise ValueError("formal target receipt input duplicate")
    for index, left in enumerate(inputs):
        for right in inputs[index + 1:]:
            if os.path.samefile(left, right):
                raise ValueError("formal target receipt input alias")
    return inputs


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    stream = io.BytesIO()
    frame.write_parquet(
        stream, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    return stream.getvalue()


def _build_target_frames(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    spec: TargetBuildSpec,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    dates = planned.test_dates
    eligible = pl.read_parquet(dict(release.artifact_paths)["eligible_keys.parquet"]).select(
        "as_of", "symbol"
    ).filter(pl.col("as_of").is_in(list(dates))).sort("as_of", "symbol")
    if eligible.select("as_of", "symbol").n_unique() != eligible.height:
        raise ValueError("target eligible duplicate keys")
    feature_frame = _read_feature_segment(feature, "test")
    scorable = feature_frame.filter(
        _scorable_expression(feature.manifest.schema.selected_names)
    ).select("as_of", "symbol").sort("as_of", "symbol")
    predictions = prediction.predictions.sort("as_of", "symbol")
    if scorable.n_unique(["as_of", "symbol"]) != scorable.height:
        raise ValueError("target scorable duplicate keys")
    if predictions.n_unique(["as_of", "symbol"]) != predictions.height:
        raise ValueError("target prediction duplicate keys")
    eligible_keys = set(cast(list[tuple[dt.date, str]], eligible.rows()))
    scorable_keys = set(cast(list[tuple[dt.date, str]], scorable.rows()))
    prediction_keys = set(cast(list[tuple[dt.date, str]], predictions.select("as_of", "symbol").rows()))
    if not scorable_keys <= eligible_keys or prediction_keys != scorable_keys:
        raise ValueError("target key layer drift")
    target_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    threshold = Decimal(str(spec.minimum_scorable_coverage))
    for day in dates:
        day_eligible = eligible.filter(pl.col("as_of") == day)
        day_predictions = predictions.filter(pl.col("as_of") == day).sort("rank")
        n_eligible = day_eligible.height
        n_scorable = scorable.filter(pl.col("as_of") == day).height
        n_predicted = day_predictions.height
        if n_eligible == 0 or n_predicted == 0 or n_scorable != n_predicted:
            raise ValueError("target daily domain incomplete")
        coverage = Decimal(n_scorable) / Decimal(n_eligible)
        if coverage < threshold:
            raise ValueError("target scorable coverage below minimum")
        selected = day_predictions.head(spec.top_k)
        n_selected = selected.height
        if n_selected == 0:
            raise ValueError("target empty selection")
        selected_symbols = set(cast(list[str], selected.get_column("symbol").to_list()))
        weight, total = _target_allocation(
            cash_buffer=spec.cash_buffer,
            max_weight=spec.max_weight,
            n_selected=n_selected,
        )
        for symbol in cast(list[str], day_eligible.get_column("symbol").to_list()):
            target_rows.append({
                "as_of": day,
                "strategy": spec.strategy,
                "strategy_version": spec.strategy_version,
                "symbol": symbol,
                "weight": float(weight if symbol in selected_symbols else Decimal(0)),
            })
        daily_rows.append({
            "as_of": day,
            "n_eligible": n_eligible,
            "n_scorable": n_scorable,
            "n_predicted": n_predicted,
            "n_selected": n_selected,
            "scorable_coverage": float(coverage),
            "total_target_weight": float(total),
        })
    targets = TargetWeightSchema.validate(pl.DataFrame(target_rows)).sort("as_of", "symbol")
    daily = pl.DataFrame(daily_rows, schema=_DAILY_SCHEMA).sort("as_of")
    return targets, daily


def _target_manifest(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
    targets: pl.DataFrame,
    daily: pl.DataFrame,
    targets_path: Path,
    daily_path: Path,
) -> TargetManifestV1:
    test = next(item for item in feature.manifest.segments if item.name == "test")
    return TargetManifestV1(
        schema_version="m3-target-artifact-v1",
        experiment_key=spec.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        work_key=spec.work_key,
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        prediction_manifest_sha256=prediction.manifest_sha256,
        feature_manifest_sha256=feature.manifest_sha256,
        fold_plan_manifest_sha256=folds.manifest_sha256,
        snapshot_id=prediction.manifest.snapshot_id,
        fold=spec.fold,
        horizon_sessions=spec.horizon_sessions,
        model=prediction.manifest.model,
        model_version=prediction.manifest.model_version,
        strategy=spec.strategy,
        strategy_version=spec.strategy_version,
        eligible_keys_sha256=test.eligible_keys_sha256,
        signal_dates_sha256=folds.manifest.signal_dates_sha256,
        n_dates=daily.height,
        n_eligible=int(daily.get_column("n_eligible").sum()),
        n_scorable=int(daily.get_column("n_scorable").sum()),
        n_predicted=int(daily.get_column("n_predicted").sum()),
        n_selected=int(daily.get_column("n_selected").sum()),
        target_keys_sha256=target_keys_sha256(targets),
        targets_sha256=_file_sha(targets_path),
        target_daily_sha256=_file_sha(daily_path),
    )


def _validate_identity(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: TargetBuildSpec,
) -> None:
    planned = next((item for item in folds.manifest.folds if item.name == spec.fold), None)
    test = next((item for item in feature.manifest.segments if item.name == "test"), None)
    if (
        len({feature.example_id, prediction.example_id, folds.example_id, experiment.example_id}) != 1
        or planned is None
        or test is None
        or build_target_spec(
            release=release, feature=feature, prediction=prediction,
            folds=folds, experiment=experiment, config=config,
        ) != spec
        or feature.manifest.experiment_key != experiment.manifest.experiment_key
        or feature.manifest.g1_release_id != release.manifest.release_id
        or feature.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or prediction.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or prediction.manifest.eligibility_sha256 != test.eligible_keys_sha256
        or feature.manifest.planned_fold_sha256 != planned.planned_fold_sha256
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("target identity/config drift")


def _fresh_upstream_bytes(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: TargetUpstreamPaths,
) -> None:
    checks = (
        (release.release.manifest_path, release.manifest_sha256),
        (release.release.root / "receipt.json", release.receipt_sha256),
        (feature.root / "feature_manifest.json", feature.manifest_sha256),
        (paths.feature_receipt_path, feature.feature_receipt_sha256),
        (prediction.root / "prediction_manifest.json", prediction.manifest_sha256),
        (paths.prediction_receipt_path, prediction.prediction_receipt_sha256),
        (folds.root / "folds.json", folds.manifest_sha256),
        (paths.fold_receipt_path, folds.folds_receipt_sha256),
        (experiment.root / "experiment_manifest.json", experiment.manifest_sha256),
        (paths.experiment_receipt_path, experiment.experiment_receipt_sha256),
    )
    if any(not path.is_file() or _file_sha(path) != digest for path, digest in checks):
        raise ValueError("target upstream bytes stale")


def _receipt_inputs(
    release: VerifiedDevelopmentExampleG1Release,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    prediction: VerifiedDevelopmentExamplePredictionArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    paths: TargetUpstreamPaths,
) -> tuple[Path, ...]:
    test = next(item for item in feature.manifest.segments if item.name == "test")
    return (
        release.release.manifest_path,
        release.release.root / "receipt.json",
        dict(release.artifact_paths)["eligible_keys.parquet"],
        feature.root / "feature_manifest.json",
        paths.feature_receipt_path,
        feature.root / test.path,
        prediction.root / "prediction_manifest.json",
        paths.prediction_receipt_path,
        prediction.root / "predictions.parquet",
        folds.root / "folds.json",
        paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
        paths.experiment_receipt_path,
    )


def _read_targets(path: Path) -> pl.DataFrame:
    frame = TargetWeightSchema.validate(pl.read_parquet(path))
    if frame.columns != ["as_of", "strategy", "strategy_version", "symbol", "weight"]:
        raise ValueError("target parquet columns drift")
    keys = tuple(frame.select("as_of", "symbol").iter_rows())
    if not keys or keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("target parquet order/keys drift")
    return frame


def _read_target_daily(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.columns != list(_DAILY_SCHEMA) or frame.schema != _DAILY_SCHEMA:
        raise ValueError("target daily schema drift")
    dates = frame.get_column("as_of").to_list()
    if not dates or dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("target daily dates drift")
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
        raw.decode("utf-8"), object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...], paths: Sequence[Path], roots: Mapping[str, Path]
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(os.path.normcase(os.path.abspath(
        path_for_artifact_digest(item, artifact_roots=roots)
    )) for item in digests))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("target output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
