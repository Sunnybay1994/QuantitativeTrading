"""Deterministic G5B prediction artifacts and the sole rank normalizer."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.domain import PredictionScoreSchema
from quant.research.m3.alignment import (
    _pandas_features,
    _read_feature_segment,
    _scorable_expression,
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
    predict_development_example_fitted_model,
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


def _prediction_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_PREDICTION_ARTIFACT_INVALID") from None

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
    _require_empty_directory(output_root)
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
    scores = predict_development_example_fitted_model(model=model, inference=inference)
    if len(scores) != inference.metadata.height:
        raise ValueError("prediction output coverage drift")
    raw = inference.metadata.with_columns(
        pl.Series("score", scores, dtype=pl.Float64),
        pl.lit(spec.model).alias("model"),
        pl.lit(spec.model_version).alias("model_version"),
        pl.lit(feature.manifest.snapshot_id).alias("dataset_snapshot_id"),
        pl.lit(spec.fold).alias("fold"),
        pl.lit(spec.horizon_sessions, dtype=pl.Int64).alias("horizon_sessions"),
    )
    predictions = normalize_prediction_scores(raw)
    test = _test_segment(feature)
    if predictions.height != test.n_scorable or predictions.height <= 0:
        raise ValueError("prediction count conservation drift")
    prediction_path = output_root / "predictions.parquet"
    _write_parquet(predictions, prediction_path)
    manifest = PredictionManifestV1(
        schema_version="m3-prediction-artifact-v1",
        experiment_key=spec.experiment_key,
        work_key=spec.work_key,
        model_manifest_sha256=model.manifest_sha256,
        model_sha256=model.manifest.model_sha256,
        feature_manifest_sha256=feature.manifest_sha256,
        selected_feature_schema_sha256=feature.manifest.schema.selected_schema_sha256,
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
        predictions_sha256=_file_sha(prediction_path),
    )
    _write_exclusive(
        output_root / "prediction_manifest.json", _canonical_bytes(asdict(manifest))
    )
    return manifest


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


def _test_segment(feature: VerifiedDevelopmentExampleFeatureArtifact) -> Any:
    return next(item for item in feature.manifest.segments if item.name == "test")


def _expected_test_keys(
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
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
    model: VerifiedDevelopmentExampleModelArtifact,
    feature: VerifiedDevelopmentExampleFeatureArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
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


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("prediction output must be an empty real directory")


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
        path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
