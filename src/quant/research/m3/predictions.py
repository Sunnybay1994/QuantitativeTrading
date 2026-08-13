"""Deterministic G5B prediction artifacts and the sole rank normalizer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.data.m3_release import VerifiedG1Release
from quant.domain import PredictionScoreSchema
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactPublicationError,
    ArtifactRollbackError,
)
from quant.research.m3.alignment import (
    _pandas_features,
    _read_feature_segment,
    _scorable_expression,
    build_inference_segment,
    build_development_example_inference_segment as _fresh_inference_segment,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    InferenceUpstreamPaths,
    InferenceSegment,
    LabelBuildSpec,
    LightgbmTrainingSpec,
    PredictionBuildSpec,
    PredictionManifestV1,
    PredictionUpstreamPaths,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    VerifiedAlignmentArtifact,
    VerifiedExperimentIdentity,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedModelArtifact,
    VerifiedPredictionArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleAlignmentArtifact,
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFeatureArtifact,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleModelArtifact,
    VerifiedDevelopmentExamplePredictionArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.model import (
    predict_fitted_model,
    predict_development_example_fitted_model,
    verify_model_artifact,
    verify_development_example_model_artifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_FILES = {"prediction_manifest.json", "predictions.parquet"}
_COLUMNS = (
    "as_of", "symbol", "score", "rank", "model", "model_version",
    "dataset_snapshot_id", "fold", "horizon_sessions",
)
_GROUPS = (
    "as_of", "model", "model_version", "dataset_snapshot_id", "fold",
    "horizon_sessions",
)
_P = ParamSpec("_P")
_T = TypeVar("_T")


class _PredictionWriteFailure(Exception):
    """Internal marker for a write failure whose rollback completed."""


def _prediction_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        write_failed = False
        rollback_failed = False
        try:
            return function(*args, **kwargs)
        except ArtifactRollbackError:
            rollback_failed = True
        except ArtifactPublicationError:
            write_failed = True
        except _PredictionWriteFailure:
            write_failed = True
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_PREDICTION_ARTIFACT_INVALID") from None
        if rollback_failed:
            raise ValueError("M3_PREDICTION_ROLLBACK_FAILED")
        if write_failed:
            raise ValueError("M3_PREDICTION_ARTIFACT_INVALID")
        raise AssertionError("unreachable")

    return wrapped


def _formal_prediction_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    """Translate every formal-boundary failure without retaining private context."""
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        failed = False
        rollback_failed = False
        try:
            return function(*args, **kwargs)
        except ArtifactRollbackError:
            rollback_failed = True
        except Exception:
            failed = True
        if rollback_failed:
            raise ValueError("M3_PREDICTION_ROLLBACK_FAILED")
        if failed:
            raise ValueError("M3_PREDICTION_ARTIFACT_INVALID")
        raise AssertionError("unreachable")

    return wrapped


@_prediction_boundary
def normalize_prediction_scores(frame: pl.DataFrame) -> pl.DataFrame:
    """Validate and rank each complete model cross-section deterministically."""
    base_columns = tuple(name for name in _COLUMNS if name != "rank")
    if (
        not isinstance(frame, pl.DataFrame)
        or frozenset(frame.columns)
        not in {frozenset(base_columns), frozenset(_COLUMNS)}
    ):
        raise ValueError("prediction columns drift")
    frame = frame.select(base_columns)
    if frame.is_empty() or not frame.get_column("score").is_finite().all():
        raise ValueError("prediction scores invalid")
    ranked = frame.sort(
        [*_GROUPS, "score", "symbol"],
        descending=[False] * len(_GROUPS) + [True, False],
    ).with_columns(
        pl.col("symbol").cum_count().over(list(_GROUPS)).alias("rank")
    ).select(_COLUMNS)
    return PredictionScoreSchema.validate(ranked)


@_prediction_boundary
def build_prediction_spec(
    *,
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
) -> PredictionBuildSpec:
    _validate_common_identity(model, feature, folds, experiment)
    return PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=model.manifest.work_key,
        fold=model.manifest.fold,
        horizon_sessions=cast(Any, model.manifest.horizon_sessions),
        model="lightgbm",
        model_version=model.manifest.model_version,
    )


def build_development_example_inference_segment(
    *,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_name: str,
) -> InferenceSegment:
    """Load test features from already verified development capabilities."""
    if (
        type(feature) is not VerifiedDevelopmentExampleFeatureArtifact
        or type(folds) is not VerifiedDevelopmentExampleFoldPlanArtifact
        or feature.example_id != folds.example_id
        or feature.manifest.fold != fold_name
    ):
        raise ValueError("prediction inference identity mismatch")
    planned = next((item for item in folds.manifest.folds if item.name == fold_name), None)
    if planned is None or planned.planned_fold_sha256 != feature.manifest.planned_fold_sha256:
        raise ValueError("prediction inference fold drift")
    names = feature.manifest.schema.selected_names
    frame = _read_feature_segment(feature, "test").filter(_scorable_expression(names))
    test = _test_segment(feature)
    if frame.height != test.n_scorable or frame.is_empty():
        raise ValueError("prediction inference coverage drift")
    return InferenceSegment(
        name="test",
        features=_pandas_features(frame, names),
        metadata=frame.select("as_of", "symbol"),
    )


@_prediction_boundary
def build_development_example_prediction_artifact(
    *,
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
    output_root: Path,
) -> PredictionManifestV1:
    """Score every scorable test row exactly once without consulting labels."""
    _validate_prediction_identity(model, feature, folds, experiment, config, spec)
    with ArtifactPublication(output_root) as publication:
        inference = build_development_example_inference_segment(
            feature=feature, folds=folds, fold_name=spec.fold
        )
        expected_keys = _expected_test_keys(feature, folds, spec.fold)
        actual_keys = tuple(
            (row["as_of"], row["symbol"])
            for row in inference.metadata.iter_rows(named=True)
        )
        if actual_keys != expected_keys:
            raise ValueError("prediction inference keys drift")
        scores = predict_development_example_fitted_model(
            model=model, inference=inference
        )
        if len(scores) != inference.metadata.height:
            raise ValueError("prediction output coverage drift")
        raw = inference.metadata.with_columns(
            pl.Series("score", scores, dtype=pl.Float64),
            pl.lit(spec.model).alias("model"),
            pl.lit(spec.model_version).alias("model_version"),
            pl.lit(feature.manifest.snapshot_id).alias("dataset_snapshot_id"),
            pl.lit(spec.fold).alias("fold"),
            pl.lit(spec.horizon_sessions, dtype=pl.Int64).alias(
                "horizon_sessions"
            ),
        )
        predictions = normalize_prediction_scores(raw)
        test = _test_segment(feature)
        if predictions.height != test.n_scorable or predictions.height <= 0:
            raise ValueError("prediction count conservation drift")
        return _write_prediction_bundle(
            publication=publication,
            predictions=predictions,
            manifest_factory=lambda predictions_sha256: PredictionManifestV1(
                schema_version="m3-prediction-artifact-v1",
                experiment_key=spec.experiment_key,
                work_key=spec.work_key,
                model_manifest_sha256=model.manifest_sha256,
                model_sha256=model.manifest.model_sha256,
                feature_manifest_sha256=feature.manifest_sha256,
                selected_feature_schema_sha256=(
                    feature.manifest.schema.selected_schema_sha256
                ),
                eligibility_sha256=test.eligible_keys_sha256,
                signal_dates_sha256=folds.manifest.signal_dates_sha256,
                snapshot_id=feature.manifest.snapshot_id,
                fold=spec.fold,
                horizon_sessions=spec.horizon_sessions,
                model=spec.model,
                model_version=spec.model_version,
                n_eligible=test.n_eligible,
                n_scorable=test.n_scorable,
                n_predicted=predictions.height,
                prediction_keys_sha256=prediction_keys_sha256(predictions),
                predictions_sha256=predictions_sha256,
            ),
        )


@_formal_prediction_boundary
def build_prediction_artifact(
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
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
    upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> PredictionManifestV1:
    """Build a formal prediction bundle from fresh model and test features."""
    _validate_formal_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        config=config, spec=spec, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
    )
    with ArtifactPublication(output_root) as publication:
        inference = _fresh_formal_inputs(
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, label=label,
            label_spec=label_spec, alignment=alignment,
            alignment_spec=alignment_spec, model=model, model_spec=model_spec,
            config=config, spec=spec, upstream_paths=upstream_paths,
            artifact_roots=artifact_roots,
        )
        keys = _formal_inference_keys(inference, feature, folds, spec.fold)
        scores = predict_fitted_model(model=model, inference=inference)
        predictions = _predictions_from_scores(
            metadata=inference.metadata, scores=scores, feature=feature, spec=spec
        )
        test = _test_segment(feature)
        if (
            tuple(sorted(predictions.select("as_of", "symbol").iter_rows()))
            != keys
            or predictions.height != test.n_scorable
            or predictions.height <= 0
        ):
            raise ValueError("formal prediction coverage drift")
        return _write_prediction_bundle(
            publication=publication,
            predictions=predictions,
            manifest_factory=lambda predictions_sha256: _formal_manifest(
                predictions=predictions,
                predictions_sha256=predictions_sha256,
                model=model,
                feature=feature,
                folds=folds,
                spec=spec,
            ),
        )


@_formal_prediction_boundary
def verify_prediction_artifact(
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
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
    upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedPredictionArtifact:
    """Fresh-verify formal upstreams and reconstruct every prediction row."""
    _validate_formal_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        config=config, spec=spec, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
    )
    inference = _fresh_formal_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, model=model, model_spec=model_spec,
        config=config, spec=spec, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
    )
    _formal_inference_keys(inference, feature, folds, spec.fold)
    scores = predict_fitted_model(model=model, inference=inference)
    expected_predictions = _predictions_from_scores(
        metadata=inference.metadata, scores=scores, feature=feature, spec=spec
    )
    _require_exact_tree(root)
    raw_manifest = (root / "prediction_manifest.json").read_bytes()
    manifest = read_prediction_manifest(root / "prediction_manifest.json")
    predictions = _read_predictions(root / "predictions.parquet")
    if not predictions.equals(expected_predictions):
        raise ValueError("formal prediction content drift")
    expected_manifest = _formal_manifest(
        predictions=predictions, prediction_path=root / "predictions.parquet",
        model=model, feature=feature, folds=folds, spec=spec,
    )
    if manifest != expected_manifest:
        raise ValueError("formal prediction manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("formal prediction receipt missing")
    receipt = verified_receipt.receipt
    inputs = _receipt_inputs(model, feature, folds, experiment, upstream_paths)
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != "predictions"
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("formal prediction receipt closure drift")
    return VerifiedPredictionArtifact(
        root=root.resolve(strict=True), predictions=predictions, manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        prediction_receipt_sha256=verified_receipt.sha256,
    )


@_prediction_boundary
def verify_development_example_prediction_artifact(
    *,
    root: Path,
    receipt_path: Path,
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    alignment: VerifiedDevelopmentExampleAlignmentArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment_spec: ExperimentIdentitySpec,
    fold_spec: FoldPlanBuildSpec,
    feature_spec: FeatureBuildSpec,
    label_spec: LabelBuildSpec,
    alignment_spec: AlignmentBuildSpec,
    model_spec: LightgbmTrainingSpec,
    spec: PredictionBuildSpec,
    upstream_paths: PredictionUpstreamPaths,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExamplePredictionArtifact:
    fresh_model = verify_development_example_model_artifact(
        root=model.root, receipt_path=upstream_paths.model_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, config=config, spec=model_spec,
        upstream_paths=upstream_paths.model_upstream_paths,
        artifact_roots=artifact_roots,
    )
    if fresh_model != model:
        raise ValueError("prediction model stale")
    _validate_prediction_identity(
        model, feature, folds, experiment, config, spec
    )
    if not root.is_dir() or root.is_symlink() or {item.name for item in os.scandir(root)} != _FILES:
        raise ValueError("prediction tree closure drift")
    raw_manifest = (root / "prediction_manifest.json").read_bytes()
    manifest = read_prediction_manifest(root / "prediction_manifest.json")
    predictions = _read_predictions(root / "predictions.parquet")
    test = _test_segment(feature)
    expected = {
        "experiment_key": spec.experiment_key,
        "work_key": spec.work_key,
        "model_manifest_sha256": model.manifest_sha256,
        "model_sha256": _file_sha(model.root / "model.txt"),
        "feature_manifest_sha256": feature.manifest_sha256,
        "selected_feature_schema_sha256": feature.manifest.schema.selected_schema_sha256,
        "eligibility_sha256": test.eligible_keys_sha256,
        "signal_dates_sha256": folds.manifest.signal_dates_sha256,
        "snapshot_id": feature.manifest.snapshot_id,
        "fold": spec.fold,
        "horizon_sessions": spec.horizon_sessions,
        "model": spec.model,
        "model_version": spec.model_version,
        "n_eligible": test.n_eligible,
        "n_scorable": test.n_scorable,
        "n_predicted": predictions.height,
        "prediction_keys_sha256": prediction_keys_sha256(predictions),
        "predictions_sha256": _file_sha(root / "predictions.parquet"),
    }
    if any(getattr(manifest, name) != value for name, value in expected.items()):
        raise ValueError("prediction manifest/content drift")
    expected_keys = tuple(
        (row["as_of"], row["symbol"]) for row in
        _fresh_inference_segment(
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, config=config,
            fold_name=spec.fold,
            upstream_paths=InferenceUpstreamPaths(
                feature_receipt_path=upstream_paths.feature_receipt_path,
                feature_upstream_paths=upstream_paths.feature_upstream_paths,
            ),
            artifact_roots=artifact_roots,
        ).metadata.iter_rows(named=True)
    )
    actual_keys = tuple(
        (row["as_of"], row["symbol"]) for row in predictions.iter_rows(named=True)
    )
    if tuple(sorted(actual_keys)) != tuple(sorted(expected_keys)):
        raise ValueError("prediction keys differ from scorable test")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("prediction receipt missing")
    receipt = verified_receipt.receipt
    inputs = _receipt_inputs(
        model, feature, folds, experiment, upstream_paths
    )
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != "development-predictions"
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("prediction receipt closure drift")
    return VerifiedDevelopmentExamplePredictionArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=model.example_id, root=root.resolve(strict=True),
        predictions=predictions, manifest=manifest,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        prediction_receipt_sha256=verified_receipt.sha256,
    )


@_prediction_boundary
def read_prediction_manifest(path: Path) -> PredictionManifestV1:
    raw = path.read_bytes()
    payload = _strict_object(raw)
    if set(payload) != {field.name for field in fields(PredictionManifestV1)}:
        raise ValueError("prediction manifest fields drift")
    manifest = PredictionManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("prediction manifest non-canonical")
    return manifest


def prediction_keys_sha256(predictions: pl.DataFrame) -> str:
    rows = [
        [
            row["as_of"].isoformat(), row["symbol"], row["model"],
            row["model_version"], row["dataset_snapshot_id"], row["fold"],
            row["horizon_sessions"],
        ]
        for row in predictions.iter_rows(named=True)
    ]
    return hashlib.sha256(_canonical_bytes(rows)).hexdigest()


def _validate_formal_inputs(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec, alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec, model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec, config: LoadedM3Config,
    spec: PredictionBuildSpec, upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
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
        (model_spec, LightgbmTrainingSpec), (config, LoadedM3Config),
        (spec, PredictionBuildSpec), (upstream_paths, PredictionUpstreamPaths),
    )
    if (
        any(type(value) is not expected for value, expected in exact)
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not alias or not isinstance(path, Path)
            for alias, path in artifact_roots.items()
        )
    ):
        raise ValueError("formal prediction inputs invalid")
    planned = next(
        (item for item in folds.manifest.folds if item.name == model.manifest.fold),
        None,
    )
    expected_spec = PredictionBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        work_key=model.manifest.work_key,
        fold=model.manifest.fold,
        horizon_sessions=cast(Any, model.manifest.horizon_sessions),
        model="lightgbm",
        model_version=model.manifest.model_version,
    )
    test = _test_segment(feature)
    nested_feature_paths = (
        upstream_paths.model_upstream_paths
        .alignment_upstream_paths.feature_upstream_paths
    )
    nested_feature_receipt = (
        upstream_paths.model_upstream_paths
        .alignment_upstream_paths.feature_receipt_path
    )
    if (
        planned is None
        or spec != expected_spec
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or feature.manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or model.manifest.experiment_key != experiment.manifest.experiment_key
        or feature.manifest.experiment_key != experiment.manifest.experiment_key
        or folds.manifest.experiment_key != experiment.manifest.experiment_key
        or model.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or model.manifest.selected_feature_schema_sha256
        != feature.manifest.schema.selected_schema_sha256
        or model.manifest.snapshot_id != feature.manifest.snapshot_id
        or feature.manifest.snapshot_id != experiment.manifest.snapshot_id
        or folds.manifest.snapshot_id != experiment.manifest.snapshot_id
        or feature.manifest.fold != spec.fold
        or feature.manifest.planned_fold_sha256 != planned.planned_fold_sha256
        or test.n_scorable <= 0
        or test.n_scorable > test.n_eligible
        or not _same_path(
            upstream_paths.feature_receipt_path, nested_feature_receipt
        )
        or upstream_paths.feature_upstream_paths != nested_feature_paths
        or not _same_path(
            upstream_paths.fold_receipt_path,
            upstream_paths.feature_upstream_paths.fold_receipt_path,
        )
    ):
        raise ValueError("formal prediction identity/path drift")


def _fresh_formal_inputs(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec, alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec, model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec, config: LoadedM3Config,
    spec: PredictionBuildSpec, upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> InferenceSegment:
    fresh_model = verify_model_artifact(
        root=model.root, receipt_path=upstream_paths.model_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, config=config, spec=model_spec,
        upstream_paths=upstream_paths.model_upstream_paths,
        artifact_roots=artifact_roots,
    )
    if type(fresh_model) is not VerifiedModelArtifact or fresh_model != model:
        raise ValueError("formal prediction model stale")
    inference = build_inference_segment(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        feature=feature, feature_spec=feature_spec, config=config,
        fold_name=spec.fold,
        upstream_paths=InferenceUpstreamPaths(
            feature_receipt_path=upstream_paths.feature_receipt_path,
            feature_upstream_paths=upstream_paths.feature_upstream_paths,
        ),
        artifact_roots=artifact_roots,
    )
    if type(inference) is not InferenceSegment:
        raise ValueError("formal prediction inference invalid")
    return inference


def _formal_inference_keys(
    inference: InferenceSegment,
    feature: VerifiedFeatureArtifact,
    folds: VerifiedFoldPlanArtifact,
    fold_name: str,
) -> tuple[tuple[object, str], ...]:
    expected = _expected_test_keys(feature, folds, fold_name)
    metadata = inference.metadata
    index = inference.features.index
    actual = tuple(metadata.iter_rows())
    if (
        metadata.columns != ["as_of", "symbol"]
        or metadata.schema != {"as_of": pl.Date, "symbol": pl.String}
        or actual != expected
        or len(actual) != len(set(actual))
        or getattr(index, "nlevels", None) != 2
        or tuple(index.names) != ("as_of", "symbol")
        or not index.is_unique
        or not index.is_monotonic_increasing
        or tuple(index.tolist()) != actual
    ):
        raise ValueError("formal prediction inference keys drift")
    return expected


def _predictions_from_scores(
    *, metadata: pl.DataFrame, scores: Sequence[float],
    feature: VerifiedFeatureArtifact, spec: PredictionBuildSpec,
) -> pl.DataFrame:
    if (
        not isinstance(scores, Sequence)
        or len(scores) != metadata.height
        or any(type(value) is not float for value in scores)
    ):
        raise ValueError("formal prediction score coverage drift")
    raw = metadata.with_columns(
        pl.Series("score", scores, dtype=pl.Float64),
        pl.lit(spec.model).alias("model"),
        pl.lit(spec.model_version).alias("model_version"),
        pl.lit(feature.manifest.snapshot_id).alias("dataset_snapshot_id"),
        pl.lit(spec.fold).alias("fold"),
        pl.lit(spec.horizon_sessions, dtype=pl.Int64).alias("horizon_sessions"),
    )
    return normalize_prediction_scores(raw)


def _formal_manifest(
    *, predictions: pl.DataFrame, prediction_path: Path | None = None,
    predictions_sha256: str | None = None,
    model: VerifiedModelArtifact, feature: VerifiedFeatureArtifact,
    folds: VerifiedFoldPlanArtifact, spec: PredictionBuildSpec,
) -> PredictionManifestV1:
    if (prediction_path is None) == (predictions_sha256 is None):
        raise ValueError("prediction content digest source invalid")
    content_sha256 = (
        _file_sha(prediction_path)
        if prediction_path is not None
        else cast(str, predictions_sha256)
    )
    test = _test_segment(feature)
    return PredictionManifestV1(
        schema_version="m3-prediction-artifact-v1",
        experiment_key=spec.experiment_key, work_key=spec.work_key,
        model_manifest_sha256=model.manifest_sha256,
        model_sha256=_file_sha(model.root / "model.txt"),
        feature_manifest_sha256=feature.manifest_sha256,
        selected_feature_schema_sha256=(
            feature.manifest.schema.selected_schema_sha256
        ),
        eligibility_sha256=test.eligible_keys_sha256,
        signal_dates_sha256=folds.manifest.signal_dates_sha256,
        snapshot_id=feature.manifest.snapshot_id, fold=spec.fold,
        horizon_sessions=spec.horizon_sessions, model=spec.model,
        model_version=spec.model_version, n_eligible=test.n_eligible,
        n_scorable=test.n_scorable, n_predicted=predictions.height,
        prediction_keys_sha256=prediction_keys_sha256(predictions),
        predictions_sha256=content_sha256,
    )


def _validate_common_identity(
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
) -> None:
    if any(type(value) is not expected for value, expected in (
        (model, VerifiedDevelopmentExampleModelArtifact),
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
        (folds, VerifiedDevelopmentExampleFoldPlanArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
    )) or len({model.example_id, feature.example_id, folds.example_id, experiment.example_id}) != 1:
        raise ValueError("prediction development identity mismatch")
    if (
        model.manifest.experiment_key != experiment.manifest.experiment_key
        or model.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or model.manifest.snapshot_id != feature.manifest.snapshot_id
        or model.manifest.fold != feature.manifest.fold
        or feature.manifest.planned_fold_sha256
        != next(
            (
                item.planned_fold_sha256
                for item in folds.manifest.folds
                if item.name == feature.manifest.fold
            ),
            None,
        )
    ):
        raise ValueError("prediction lineage mismatch")


def _validate_prediction_identity(
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
) -> None:
    _validate_common_identity(model, feature, folds, experiment)
    if (
        type(config) is not LoadedM3Config
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
        or build_prediction_spec(
            model=model, feature=feature, folds=folds, experiment=experiment
        ) != spec
    ):
        raise ValueError("prediction identity/config drift")


def _test_segment(
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
) -> Any:
    return next(item for item in feature.manifest.segments if item.name == "test")


def _expected_test_keys(
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_name: str,
) -> tuple[tuple[object, str], ...]:
    planned = next((item for item in folds.manifest.folds if item.name == fold_name), None)
    if planned is None:
        raise ValueError("prediction fold missing")
    names = feature.manifest.schema.selected_names
    frame = _read_feature_segment(feature, "test").filter(_scorable_expression(names))
    keys = tuple(frame.select("as_of", "symbol").iter_rows())
    if (
        len(keys) != len(set(keys))
        or keys != tuple(sorted(keys))
        or any(day not in set(planned.test_dates) for day, _ in keys)
        or len(keys) != _test_segment(feature).n_scorable
    ):
        raise ValueError("prediction expected test keys drift")
    return keys


def _read_predictions(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if tuple(frame.columns) != _COLUMNS:
        raise ValueError("prediction parquet columns drift")
    validated = PredictionScoreSchema.validate(frame)
    raw = validated.drop("rank")
    if not validated.equals(normalize_prediction_scores(raw)):
        raise ValueError("prediction rank/order drift")
    return validated


def _receipt_inputs(
    model: VerifiedModelArtifact | VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: (
        VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity
    ),
    upstream_paths: PredictionUpstreamPaths,
) -> tuple[Path, ...]:
    return (
        model.root / "model.metadata.json",
        upstream_paths.model_receipt_path,
        feature.root / "feature_manifest.json",
        upstream_paths.feature_receipt_path,
        folds.root / "folds.json", upstream_paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
        upstream_paths.model_upstream_paths.alignment_receipt_path,
    )


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
    digests: tuple[ArtifactDigest, ...],
    paths: Sequence[Path],
    roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(
        os.path.normcase(os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots)))
        for item in digests
    ))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _is_link_or_reparse(path: Path) -> bool:
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_exact_tree(root: Path) -> None:
    if (
        not root.is_dir()
        or _is_link_or_reparse(root)
        or {item.name for item in os.scandir(root)} != _FILES
        or any(_is_link_or_reparse(root / name) for name in _FILES)
    ):
        raise ValueError("formal prediction tree closure drift")


def _write_prediction_bundle(
    *, publication: ArtifactPublication, predictions: pl.DataFrame,
    manifest_factory: Callable[[str], PredictionManifestV1],
) -> PredictionManifestV1:
    try:
        _write_parquet(publication, "predictions.parquet", predictions)
        manifest = manifest_factory(publication.sha256("predictions.parquet"))
        _write_exclusive(
            publication,
            "prediction_manifest.json",
            _canonical_bytes(asdict(manifest)),
        )
        publication.commit(_FILES)
        return manifest
    except ArtifactRollbackError:
        raise
    except Exception:
        raise _PredictionWriteFailure from None


def _write_exclusive(
    publication: ArtifactPublication, name: str, raw: bytes,
) -> None:
    publication.write_bytes(name, raw)


def _write_parquet(
    publication: ArtifactPublication, name: str, frame: pl.DataFrame,
) -> None:
    publication.write_stream(
        name,
        lambda stream: (
            frame.write_parquet(
                stream, compression="zstd", compression_level=3, statistics=True,
                row_group_size=65536, use_pyarrow=False,
            )
        ),
    )
