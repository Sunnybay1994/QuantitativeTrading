"""Native LightGBM G5A artifact boundary with delayed heavy imports."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import numpy as np
import polars as pl

from quant.data.m3_release import VerifiedG1Release
from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactPublicationError,
    ArtifactRollbackError,
)
from quant.research.m3.alignment import (
    load_supervised_segment,
    load_development_example_supervised_segment,
    verify_alignment_artifact,
    verify_development_example_alignment_artifact,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    InferenceSegment,
    LabelBuildSpec,
    LightgbmTrainingSpec,
    ModelManifestV1,
    ModelUpstreamPaths,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    VerifiedAlignmentArtifact,
    VerifiedExperimentIdentity,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedModelArtifact,
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
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.features import feature_schema_sha256

_FILES = {"model.txt", "model.metadata.json", "validation_curve.parquet"}
_CONTROL_KEYS = {
    "model_version", "num_boost_round", "early_stopping_rounds",
    "early_stopping_min_delta",
}
_REQUIRED_PARAMS = {
    "objective", "metric", "device_type", "learning_rate", "num_leaves",
    "max_depth", "feature_fraction", "bagging_fraction", "bagging_freq",
    "seed", "data_random_seed", "feature_fraction_seed", "bagging_seed",
    "deterministic", "force_col_wise", "num_threads",
}
_P = ParamSpec("_P")
_T = TypeVar("_T")


class _ModelPublicationFailure(Exception):
    """Internal marker for a publication failure after exact rollback."""


def _model_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        publication_failed = False
        rollback_failed = False
        try:
            return function(*args, **kwargs)
        except _ModelPublicationFailure:
            publication_failed = True
        except ArtifactRollbackError:
            rollback_failed = True
        except ArtifactPublicationError:
            publication_failed = True
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_MODEL_ARTIFACT_INVALID") from None
        if rollback_failed:
            raise ValueError("M3_MODEL_ROLLBACK_FAILED")
        if publication_failed:
            raise ValueError("M3_MODEL_ARTIFACT_INVALID")
        raise AssertionError("unreachable")
    return wrapped


@_model_boundary
def build_lightgbm_training_spec(config: LoadedM3Config) -> LightgbmTrainingSpec:
    if type(config) is not LoadedM3Config:
        raise ValueError("model config invalid")
    section = config.section("model").get("lightgbm")
    if not isinstance(section, Mapping) or set(section) != _REQUIRED_PARAMS | _CONTROL_KEYS:
        raise ValueError("lightgbm config closure drift")
    params = tuple(sorted(
        ((key, cast(str | int | float | bool, value))
         for key, value in section.items() if key not in _CONTROL_KEYS),
        key=lambda item: item[0],
    ))
    spec = LightgbmTrainingSpec(
        model_version=cast(str, section["model_version"]),
        booster_params=params,
        num_boost_round=cast(int, section["num_boost_round"]),
        early_stopping_rounds=cast(int, section["early_stopping_rounds"]),
        early_stopping_min_delta=cast(float, section["early_stopping_min_delta"]),
    )
    _validate_required_params(spec)
    return spec


@_model_boundary
def build_development_example_model_artifact(
    *, alignment: VerifiedDevelopmentExampleAlignmentArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: LightgbmTrainingSpec,
    output_root: Path,
) -> ModelManifestV1:
    """Fit native LightGBM using train and validation only."""
    if any(type(value) is not expected for value, expected in (
        (alignment, VerifiedDevelopmentExampleAlignmentArtifact),
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
        (label, VerifiedDevelopmentExampleLabelArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
    )):
        raise ValueError("development model requires development inputs")
    with ArtifactPublication(output_root) as publication:
        return _build_model_artifact(
            alignment=alignment, feature=feature, label=label,
            experiment=experiment, config=config, spec=spec,
            publication=publication, formal=False,
        )


@_model_boundary
def build_model_artifact(
    *, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity, experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact, fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact, feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact, label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact, alignment_spec: AlignmentBuildSpec,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    upstream_paths: ModelUpstreamPaths, artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> ModelManifestV1:
    """Fit one formal native LightGBM model from verified supervised data."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedG1Release), (snapshot, VerifiedSnapshotArtifact),
        (provider, VerifiedProviderArtifact),
        (experiment, VerifiedExperimentIdentity),
        (folds, VerifiedFoldPlanArtifact), (feature, VerifiedFeatureArtifact),
        (label, VerifiedLabelArtifact), (alignment, VerifiedAlignmentArtifact),
    )):
        raise ValueError("formal model requires formal inputs")
    with ArtifactPublication(output_root) as publication:
        fresh = _fresh_verify_formal_alignment(
            alignment=alignment, release=release, snapshot=snapshot,
            snapshot_spec=snapshot_spec, provider=provider,
            provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, label=label,
            label_spec=label_spec, config=config, alignment_spec=alignment_spec,
            upstream_paths=upstream_paths, artifact_roots=artifact_roots,
        )
        if fresh != alignment:
            raise ValueError("model alignment stale")
        return _build_model_artifact(
            alignment=alignment, feature=feature, label=label,
            experiment=experiment, config=config, spec=spec,
            publication=publication, formal=True,
        )


def _build_model_artifact(
    *,
    alignment: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    publication: ArtifactPublication,
    formal: bool,
) -> ModelManifestV1:
    _validate_model_identity(
        alignment, feature, label, experiment, config, spec, formal=formal
    )
    if formal:
        assert isinstance(alignment, VerifiedAlignmentArtifact)
        train = load_supervised_segment(alignment=alignment, segment="train")
        validation = load_supervised_segment(
            alignment=alignment, segment="validation"
        )
    else:
        assert isinstance(alignment, VerifiedDevelopmentExampleAlignmentArtifact)
        train = load_development_example_supervised_segment(
            alignment=alignment, segment="train"
        )
        validation = load_development_example_supervised_segment(
            alignment=alignment, segment="validation"
        )
    _validate_training_frames(train.features, train.labels, validation.features, validation.labels)
    lgb = _lightgbm()
    train_set = lgb.Dataset(
        train.features, label=train.labels, feature_name=list(train.features.columns),
        free_raw_data=False,
    )
    validation_set = lgb.Dataset(
        validation.features, label=validation.labels,
        feature_name=list(validation.features.columns), free_raw_data=False,
        reference=train_set,
    )
    evaluations: dict[str, dict[str, list[float]]] = {}
    callbacks = [
        lgb.early_stopping(
            stopping_rounds=spec.early_stopping_rounds,
            first_metric_only=True, verbose=False,
            min_delta=spec.early_stopping_min_delta,
        ),
        lgb.record_evaluation(evaluations),
    ]
    booster = lgb.train(
        params=dict(spec.booster_params), train_set=train_set,
        num_boost_round=spec.num_boost_round,
        valid_sets=[validation_set], valid_names=["validation"],
        callbacks=callbacks,
    )
    curve_values = _validation_curve(evaluations)
    best_iteration = int(booster.best_iteration)
    if not 1 <= best_iteration <= len(curve_values):
        raise ValueError("lightgbm best iteration invalid")
    best_l2 = float(curve_values[best_iteration - 1])
    best_score = getattr(booster, "best_score", None)
    validation_scores = (
        best_score.get("validation") if isinstance(best_score, Mapping) else None
    )
    reported_best_l2 = (
        validation_scores.get("l2")
        if isinstance(validation_scores, Mapping)
        else None
    )
    if (
        not math.isfinite(best_l2)
        or isinstance(reported_best_l2, bool)
        or not isinstance(reported_best_l2, (int, float, np.integer, np.floating))
        or float(reported_best_l2) != best_l2
    ):
        raise ValueError("lightgbm best l2 invalid")
    publication_failed = False
    try:
        model_bytes = _save_model_to_temporary_bytes(
            booster=booster, best_iteration=best_iteration
        )
        _write_exclusive(publication, "model.txt", model_bytes)
        curve = pl.DataFrame({
            "iteration": pl.Series(
                range(1, len(curve_values) + 1), dtype=pl.Int64
            ),
            "validation_l2": pl.Series(curve_values, dtype=pl.Float64),
        })
        _write_parquet(publication, "validation_curve.parquet", curve)
        train_entry = next(
            item for item in alignment.manifest.segments if item.name == "train"
        )
        validation_entry = next(
            item
            for item in alignment.manifest.segments
            if item.name == "validation"
        )
        manifest = ModelManifestV1(
            schema_version="m3-lightgbm-model-v1",
            experiment_key=experiment.manifest.experiment_key,
            work_key=alignment.manifest.work_key,
            snapshot_id=feature.manifest.snapshot_id,
            provider_receipt_sha256=feature.manifest.provider_receipt_sha256,
            fold=alignment.manifest.fold,
            horizon_sessions=alignment.manifest.horizon_sessions,
            model="lightgbm", model_version=spec.model_version,
            alignment_manifest_sha256=alignment.manifest_sha256,
            feature_manifest_sha256=feature.manifest_sha256,
            label_manifest_sha256=label.manifest_sha256,
            input_feature_schema_sha256=(
                feature.manifest.schema.input_schema_sha256
            ),
            selected_feature_names=feature.manifest.schema.selected_names,
            selected_feature_schema_sha256=(
                feature.manifest.schema.selected_schema_sha256
            ),
            params_sha256=training_params_sha256(spec),
            train_row_keys_sha256=train_entry.row_keys_sha256,
            validation_row_keys_sha256=validation_entry.row_keys_sha256,
            train_matrix_sha256=train_entry.matrix_sha256,
            validation_matrix_sha256=validation_entry.matrix_sha256,
            train_labels_sha256=train_entry.labels_sha256,
            validation_labels_sha256=validation_entry.labels_sha256,
            lightgbm_version=_lightgbm_version(lgb),
            best_iteration=best_iteration,
            best_validation_l2=best_l2,
            model_sha256=hashlib.sha256(model_bytes).hexdigest(),
            validation_curve_sha256=publication.sha256(
                "validation_curve.parquet"
            ),
        )
        _write_exclusive(
            publication,
            "model.metadata.json",
            _canonical_bytes(asdict(manifest)),
        )
        publication.commit(_FILES)
    except ArtifactRollbackError:
        raise
    except Exception:
        publication_failed = True
    if publication_failed:
        raise _ModelPublicationFailure
    return manifest


@_model_boundary
def verify_development_example_model_artifact(
    *, root: Path, receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedDevelopmentExampleLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedDevelopmentExampleAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    upstream_paths: ModelUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleModelArtifact:
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedDevelopmentExampleG1Release),
        (snapshot, VerifiedDevelopmentExampleSnapshotArtifact),
        (provider, VerifiedDevelopmentExampleProviderArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
        (folds, VerifiedDevelopmentExampleFoldPlanArtifact),
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
        (label, VerifiedDevelopmentExampleLabelArtifact),
        (alignment, VerifiedDevelopmentExampleAlignmentArtifact),
    )):
        raise ValueError("development model verify requires development inputs")
    verified = _verify_model_artifact(
        root=root, receipt_path=receipt_path, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec, folds=folds,
        fold_spec=fold_spec, feature=feature, feature_spec=feature_spec,
        label=label, label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots, formal=False,
    )
    if type(verified) is not VerifiedDevelopmentExampleModelArtifact:
        raise ValueError("development model result kind invalid")
    return verified


@_model_boundary
def verify_model_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity, experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact, fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact, feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact, label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact, alignment_spec: AlignmentBuildSpec,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    upstream_paths: ModelUpstreamPaths, artifact_roots: Mapping[str, Path],
) -> VerifiedModelArtifact:
    """Fresh-verify the formal G4C chain and the exact model bundle."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedG1Release), (snapshot, VerifiedSnapshotArtifact),
        (provider, VerifiedProviderArtifact),
        (experiment, VerifiedExperimentIdentity),
        (folds, VerifiedFoldPlanArtifact), (feature, VerifiedFeatureArtifact),
        (label, VerifiedLabelArtifact), (alignment, VerifiedAlignmentArtifact),
    )):
        raise ValueError("formal model verify requires formal inputs")
    verified = _verify_model_artifact(
        root=root, receipt_path=receipt_path, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec, folds=folds,
        fold_spec=fold_spec, feature=feature, feature_spec=feature_spec,
        label=label, label_spec=label_spec, alignment=alignment,
        alignment_spec=alignment_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots, formal=True,
    )
    if type(verified) is not VerifiedModelArtifact:
        raise ValueError("formal model result kind invalid")
    return verified


def _verify_model_artifact(
    *, root: Path, receipt_path: Path,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec, config: LoadedM3Config,
    spec: LightgbmTrainingSpec, upstream_paths: ModelUpstreamPaths,
    artifact_roots: Mapping[str, Path], formal: bool,
) -> VerifiedModelArtifact | VerifiedDevelopmentExampleModelArtifact:
    fresh: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact
    if formal:
        assert isinstance(release, VerifiedG1Release)
        assert isinstance(snapshot, VerifiedSnapshotArtifact)
        assert isinstance(provider, VerifiedProviderArtifact)
        assert isinstance(experiment, VerifiedExperimentIdentity)
        assert isinstance(folds, VerifiedFoldPlanArtifact)
        assert isinstance(feature, VerifiedFeatureArtifact)
        assert isinstance(label, VerifiedLabelArtifact)
        assert isinstance(alignment, VerifiedAlignmentArtifact)
        fresh = _fresh_verify_formal_alignment(
            alignment=alignment, release=release, snapshot=snapshot,
            snapshot_spec=snapshot_spec, provider=provider,
            provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, label=label,
            label_spec=label_spec, config=config, alignment_spec=alignment_spec,
            upstream_paths=upstream_paths, artifact_roots=artifact_roots,
        )
    else:
        assert isinstance(release, VerifiedDevelopmentExampleG1Release)
        assert isinstance(snapshot, VerifiedDevelopmentExampleSnapshotArtifact)
        assert isinstance(provider, VerifiedDevelopmentExampleProviderArtifact)
        assert isinstance(experiment, VerifiedDevelopmentExampleExperimentIdentity)
        assert isinstance(folds, VerifiedDevelopmentExampleFoldPlanArtifact)
        assert isinstance(feature, VerifiedDevelopmentExampleFeatureArtifact)
        assert isinstance(label, VerifiedDevelopmentExampleLabelArtifact)
        assert isinstance(alignment, VerifiedDevelopmentExampleAlignmentArtifact)
        fresh = verify_development_example_alignment_artifact(
            root=alignment.root,
            receipt_path=upstream_paths.alignment_receipt_path,
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, label=label,
            label_spec=label_spec, config=config, spec=alignment_spec,
            upstream_paths=upstream_paths.alignment_upstream_paths,
            artifact_roots=artifact_roots,
        )
    if fresh != alignment:
        raise ValueError("model alignment stale")
    _validate_model_identity(
        alignment, feature, label, experiment, config, spec, formal=formal
    )
    if not root.is_dir() or root.is_symlink() or {item.name for item in os.scandir(root)} != _FILES:
        raise ValueError("model tree closure drift")
    raw = (root / "model.metadata.json").read_bytes()
    manifest = read_model_manifest(root / "model.metadata.json")
    expected_identity = _expected_manifest_identity(
        alignment, feature, label, experiment, spec
    )
    if any(getattr(manifest, key) != value for key, value in expected_identity.items()):
        raise ValueError("model manifest identity drift")
    model_path = root / "model.txt"
    curve_path = root / "validation_curve.parquet"
    curve = _read_curve(curve_path)
    if (
        manifest.model_sha256 != _file_sha(model_path)
        or manifest.validation_curve_sha256 != _file_sha(curve_path)
        or not 1 <= manifest.best_iteration <= curve.height
        or manifest.best_validation_l2
        != float(curve[manifest.best_iteration - 1, "validation_l2"])
    ):
        raise ValueError("model published content drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("model receipt missing")
    receipt = verified_receipt.receipt
    inputs = (
        alignment.root / "alignment_manifest.json",
        upstream_paths.alignment_receipt_path,
        feature.root / "feature_manifest.json",
        upstream_paths.alignment_upstream_paths.feature_receipt_path,
        label.root / "label_manifest.json",
        upstream_paths.alignment_upstream_paths.label_receipt_path,
        experiment.root / "experiment_manifest.json",
    )
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != ("model" if formal else "development-model")
        or receipt.scope != "WORK"
        or receipt.scope_key != alignment.manifest.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("model receipt closure drift")
    lgb = _lightgbm()
    lgb.Booster(model_file=str(model_path))
    if manifest.lightgbm_version != _lightgbm_version(lgb):
        raise ValueError("model runtime version drift")
    if formal:
        return VerifiedModelArtifact(
            root=root.resolve(strict=True), manifest=manifest,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            model_receipt_sha256=verified_receipt.sha256,
        )
    assert isinstance(alignment, VerifiedDevelopmentExampleAlignmentArtifact)
    return VerifiedDevelopmentExampleModelArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=alignment.example_id, root=root.resolve(strict=True),
        manifest=manifest, manifest_sha256=hashlib.sha256(raw).hexdigest(),
        model_receipt_sha256=verified_receipt.sha256,
    )


@_model_boundary
def read_model_manifest(path: Path) -> ModelManifestV1:
    raw = path.read_bytes()
    payload = _strict_object(raw)
    expected = {field.name for field in fields(ModelManifestV1)}
    if set(payload) != expected or type(payload.get("selected_feature_names")) is not list:
        raise ValueError("model manifest fields drift")
    payload["selected_feature_names"] = tuple(cast(list[str], payload["selected_feature_names"]))
    manifest = ModelManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("model manifest non-canonical")
    return manifest


@_model_boundary
def predict_development_example_fitted_model(
    *, model: VerifiedDevelopmentExampleModelArtifact,
    inference: InferenceSegment,
) -> tuple[float, ...]:
    if type(model) is not VerifiedDevelopmentExampleModelArtifact or type(inference) is not InferenceSegment:
        raise ValueError("model prediction inputs invalid")
    return _predict_fitted_model(model=model, inference=inference)


@_model_boundary
def predict_fitted_model(
    *, model: VerifiedModelArtifact, inference: InferenceSegment,
) -> tuple[float, ...]:
    """Predict with the exact saved formal model projection and best iteration."""
    if type(model) is not VerifiedModelArtifact or type(inference) is not InferenceSegment:
        raise ValueError("formal model prediction inputs invalid")
    return _predict_fitted_model(model=model, inference=inference)


def _predict_fitted_model(
    *, model: VerifiedModelArtifact | VerifiedDevelopmentExampleModelArtifact,
    inference: InferenceSegment,
) -> tuple[float, ...]:
    index = inference.features.index
    metadata = inference.metadata
    if tuple(inference.features.columns) != model.manifest.selected_feature_names:
        raise ValueError("model prediction schema drift")
    if (
        getattr(index, "nlevels", None) != 2
        or tuple(index.names) != ("as_of", "symbol")
        or not index.is_unique
        or not index.is_monotonic_increasing
        or metadata.columns != ["as_of", "symbol"]
        or metadata.schema != {"as_of": pl.Date, "symbol": pl.String}
        or metadata.height != len(inference.features)
        or tuple(index.tolist()) != tuple(metadata.iter_rows())
        or any(str(dtype) != "float64" for dtype in inference.features.dtypes)
        or feature_schema_sha256(names=tuple(inference.features.columns))
        != model.manifest.selected_feature_schema_sha256
    ):
        raise ValueError("model prediction schema drift")
    values = inference.features.to_numpy(dtype="float64", copy=False)
    if np.isinf(values).any():
        raise ValueError("model prediction infinity")
    lgb = _lightgbm()
    booster = lgb.Booster(model_file=str(model.root / "model.txt"))
    raw = booster.predict(values, num_iteration=model.manifest.best_iteration)
    result = tuple(float(value) for value in raw)
    if len(result) != len(inference.features) or any(not math.isfinite(value) for value in result):
        raise ValueError("model prediction output invalid")
    return result


def _fresh_verify_formal_alignment(
    *, alignment: VerifiedAlignmentArtifact, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity, experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact, fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact, feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact, label_spec: LabelBuildSpec,
    config: LoadedM3Config, alignment_spec: AlignmentBuildSpec,
    upstream_paths: ModelUpstreamPaths, artifact_roots: Mapping[str, Path],
) -> VerifiedAlignmentArtifact:
    failed = False
    try:
        verified = verify_alignment_artifact(
            root=alignment.root,
            receipt_path=upstream_paths.alignment_receipt_path,
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            feature=feature, feature_spec=feature_spec, label=label,
            label_spec=label_spec, config=config, spec=alignment_spec,
            upstream_paths=upstream_paths.alignment_upstream_paths,
            artifact_roots=artifact_roots,
        )
    except Exception:
        failed = True
    if failed:
        raise ValueError("M3_MODEL_ALIGNMENT_VERIFY_FAILED") from None
    return verified


def training_params_sha256(spec: LightgbmTrainingSpec) -> str:
    return hashlib.sha256(_canonical_bytes({
        "booster_params": [list(item) for item in spec.booster_params],
        "num_boost_round": spec.num_boost_round,
        "early_stopping_rounds": spec.early_stopping_rounds,
        "early_stopping_min_delta": spec.early_stopping_min_delta,
    })).hexdigest()


def _validate_required_params(spec: LightgbmTrainingSpec) -> None:
    params = dict(spec.booster_params)
    if set(params) != _REQUIRED_PARAMS:
        raise ValueError("lightgbm params closure drift")
    expected = {
        "objective": "regression", "metric": "l2", "device_type": "cpu",
        "deterministic": True, "force_col_wise": True,
    }
    if any(params.get(key) != value for key, value in expected.items()):
        raise ValueError("lightgbm deterministic params drift")
    if any(type(params.get(key)) is not int for key in (
        "seed", "data_random_seed", "feature_fraction_seed", "bagging_seed",
        "num_threads",
    )):
        raise ValueError("lightgbm seed/thread params invalid")


def _validate_model_identity(
    alignment: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    *, formal: bool,
) -> None:
    expected = (
        (VerifiedAlignmentArtifact, VerifiedFeatureArtifact,
         VerifiedLabelArtifact, VerifiedExperimentIdentity)
        if formal else
        (VerifiedDevelopmentExampleAlignmentArtifact,
         VerifiedDevelopmentExampleFeatureArtifact,
         VerifiedDevelopmentExampleLabelArtifact,
         VerifiedDevelopmentExampleExperimentIdentity)
    )
    if any(type(value) is not kind for value, kind in zip(
        (alignment, feature, label, experiment), expected, strict=True
    )):
        raise ValueError("model capability identity mismatch")
    if not formal:
        assert isinstance(alignment, VerifiedDevelopmentExampleAlignmentArtifact)
        assert isinstance(feature, VerifiedDevelopmentExampleFeatureArtifact)
        assert isinstance(label, VerifiedDevelopmentExampleLabelArtifact)
        assert isinstance(experiment, VerifiedDevelopmentExampleExperimentIdentity)
        if len({alignment.example_id, feature.example_id, label.example_id,
                experiment.example_id}) != 1:
            raise ValueError("model development identity mismatch")
    if (
        build_lightgbm_training_spec(config) != spec
        or alignment.manifest.experiment_key != experiment.manifest.experiment_key
        or alignment.manifest.feature_manifest_sha256 != feature.manifest_sha256
        or alignment.manifest.label_manifest_sha256 != label.manifest_sha256
        or alignment.manifest.selected_feature_schema_sha256
        != feature.manifest.schema.selected_schema_sha256
        or alignment.manifest.horizon_sessions != label.manifest.horizon_sessions
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("model identity/config drift")


def _expected_manifest_identity(
    alignment: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    spec: LightgbmTrainingSpec,
) -> dict[str, object]:
    train = next(item for item in alignment.manifest.segments if item.name == "train")
    validation = next(item for item in alignment.manifest.segments if item.name == "validation")
    return {
        "experiment_key": experiment.manifest.experiment_key,
        "work_key": alignment.manifest.work_key,
        "snapshot_id": feature.manifest.snapshot_id,
        "provider_receipt_sha256": feature.manifest.provider_receipt_sha256,
        "fold": alignment.manifest.fold,
        "horizon_sessions": alignment.manifest.horizon_sessions,
        "model": "lightgbm", "model_version": spec.model_version,
        "alignment_manifest_sha256": alignment.manifest_sha256,
        "feature_manifest_sha256": feature.manifest_sha256,
        "label_manifest_sha256": label.manifest_sha256,
        "input_feature_schema_sha256": feature.manifest.schema.input_schema_sha256,
        "selected_feature_names": feature.manifest.schema.selected_names,
        "selected_feature_schema_sha256": feature.manifest.schema.selected_schema_sha256,
        "params_sha256": training_params_sha256(spec),
        "train_row_keys_sha256": train.row_keys_sha256,
        "validation_row_keys_sha256": validation.row_keys_sha256,
        "train_matrix_sha256": train.matrix_sha256,
        "validation_matrix_sha256": validation.matrix_sha256,
        "train_labels_sha256": train.labels_sha256,
        "validation_labels_sha256": validation.labels_sha256,
    }


def _validate_training_frames(train_x: Any, train_y: Any, validation_x: Any, validation_y: Any) -> None:
    if (
        tuple(train_x.columns) != tuple(validation_x.columns)
        or train_x.empty or validation_x.empty
        or getattr(train_x.index, "nlevels", None) != 2
        or getattr(validation_x.index, "nlevels", None) != 2
        or tuple(train_x.index.names) != ("as_of", "symbol")
        or tuple(validation_x.index.names) != ("as_of", "symbol")
        or not train_x.index.is_unique or not validation_x.index.is_unique
        or not train_x.index.is_monotonic_increasing
        or not validation_x.index.is_monotonic_increasing
        or not train_x.index.intersection(validation_x.index).empty
        or not train_x.index.equals(train_y.index)
        or not validation_x.index.equals(validation_y.index)
        or any(str(dtype) != "float64" for dtype in (*train_x.dtypes, *validation_x.dtypes))
    ):
        raise ValueError("lightgbm training frame contract drift")
    train_values = train_x.to_numpy(dtype="float64", copy=False)
    validation_values = validation_x.to_numpy(dtype="float64", copy=False)
    if np.isinf(train_values).any() or np.isinf(validation_values).any():
        raise ValueError("lightgbm X infinity")
    if not np.isfinite(train_y.to_numpy(dtype="float64" )).all() or not np.isfinite(validation_y.to_numpy(dtype="float64")).all():
        raise ValueError("lightgbm y non-finite")


def _validation_curve(evaluations: Mapping[str, Mapping[str, Sequence[object]]]) -> tuple[float, ...]:
    if set(evaluations) != {"validation"} or set(evaluations["validation"]) != {"l2"}:
        raise ValueError("lightgbm validation metric closure drift")
    values = tuple(float(cast(Any, value)) for value in evaluations["validation"]["l2"])
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("lightgbm validation curve invalid")
    return values


def _read_curve(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if (
        frame.schema != {"iteration": pl.Int64, "validation_l2": pl.Float64}
        or frame.is_empty()
        or frame["iteration"].to_list() != list(range(1, frame.height + 1))
        or not frame["validation_l2"].is_finite().all()
    ):
        raise ValueError("model validation curve drift")
    return frame


def _lightgbm() -> Any:
    return __import__("lightgbm")


def _lightgbm_version(module: Any) -> str:
    value = getattr(module, "__version__", None)
    if type(value) is not str or not value:
        raise ValueError("lightgbm version invalid")
    return value


def _strict_object(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=hook,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise ValueError("non-canonical JSON")
    return value


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...], paths: Sequence[Path], roots: Mapping[str, Path]
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(os.path.normcase(os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots))) for item in digests))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_model_to_temporary_bytes(*, booster: Any, best_iteration: int) -> bytes:
    try:
        with tempfile.TemporaryDirectory(prefix="m3-lightgbm-model-") as directory:
            path = Path(directory) / "model.txt"
            booster.save_model(str(path), num_iteration=best_iteration)
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ArtifactPublicationError
            raw = path.read_bytes()
            if not raw:
                raise ArtifactPublicationError
    except ArtifactPublicationError:
        raise
    except Exception:
        raise ArtifactPublicationError from None
    return raw


def _write_exclusive(
    publication: ArtifactPublication, name: str, raw: bytes,
) -> None:
    try:
        publication.write_bytes(name, raw)
    except ArtifactRollbackError:
        raise
    except Exception:
        raise ArtifactPublicationError from None


def _write_parquet(
    publication: ArtifactPublication, name: str, frame: pl.DataFrame,
) -> None:
    try:
        publication.write_stream(
            name,
            lambda stream: frame.write_parquet(
                stream,
                compression="zstd",
                compression_level=3,
                statistics=True,
                row_group_size=65536,
                use_pyarrow=False,
            ),
        )
    except ArtifactRollbackError:
        raise
    except Exception:
        raise ArtifactPublicationError from None
