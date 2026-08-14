"""Label-safe G4C alignment and inference boundaries.

The development entry points use the production manifest shape while keeping
the explicit ``development_example`` trust domain.  This module has no Qlib or
LightGBM dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, ParamSpec, TypeVar, cast

import pandas as pd  # type: ignore[import-untyped]
import polars as pl

from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    AlignmentManifestV1,
    AlignmentSegmentManifestV1,
    AlignmentUpstreamPaths,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FoldPlanBuildSpec,
    InferenceSegment,
    InferenceUpstreamPaths,
    LabelBuildSpec,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    SupervisedSegment,
    VerifiedAlignmentArtifact,
    VerifiedExperimentIdentity,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
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
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.features import (
    canonical_row_keys_sha256,
    f64_matrix_sha256,
    verify_feature_artifact,
    verify_development_example_feature_artifact,
)
from quant.research.m3.labels import (
    verify_development_example_label_artifact,
    verify_label_artifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_work_key,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_SEGMENTS: tuple[Literal["train", "validation"], ...] = ("train", "validation")
_FILES = {"train.parquet", "validation.parquet", "diagnostics.parquet", "alignment_manifest.json"}
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _alignment_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_ALIGNMENT_ARTIFACT_INVALID") from None
    return wrapped


@_alignment_boundary
def build_development_example_alignment_artifact(
    *, feature: VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: AlignmentBuildSpec,
    output_root: Path,
) -> AlignmentManifestV1:
    """Build deterministic train/validation supervised matrices; never test labels."""
    if any(type(value) is not expected for value, expected in (
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
        (label, VerifiedDevelopmentExampleLabelArtifact),
        (folds, VerifiedDevelopmentExampleFoldPlanArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
    )):
        raise ValueError("development alignment requires development inputs")
    return _build_alignment_artifact(
        feature=feature, label=label, folds=folds, experiment=experiment,
        config=config, spec=spec, output_root=output_root, formal=False,
    )


@_alignment_boundary
def build_alignment_artifact(
    *, feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: AlignmentBuildSpec, output_root: Path,
) -> AlignmentManifestV1:
    """Build one formal train/validation alignment without any test labels."""
    if any(type(value) is not expected for value, expected in (
        (feature, VerifiedFeatureArtifact), (label, VerifiedLabelArtifact),
        (folds, VerifiedFoldPlanArtifact),
        (experiment, VerifiedExperimentIdentity),
    )):
        raise ValueError("formal alignment requires formal inputs")
    return _build_alignment_artifact(
        feature=feature, label=label, folds=folds, experiment=experiment,
        config=config, spec=spec, output_root=output_root, formal=True,
    )


def _build_alignment_artifact(
    *,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: AlignmentBuildSpec, output_root: Path,
    formal: bool,
) -> AlignmentManifestV1:
    planned = _validate_identity(
        feature, label, folds, experiment, config, spec, formal=formal
    )
    _require_empty_directory(output_root)
    feature_names = feature.manifest.schema.selected_names
    manifests: list[AlignmentSegmentManifestV1] = []
    diagnostics: list[dict[str, object]] = []
    for segment in _SEGMENTS:
        feature_frame = _read_feature_segment(feature, segment)
        dates = planned.train_dates if segment == "train" else planned.validation_dates
        cutoff = (
            planned.train_label_available_by
            if segment == "train"
            else planned.validation_label_available_by
        )
        feature_frame = feature_frame.filter(pl.col("as_of").is_in(dates))
        scorable = feature_frame.filter(_scorable_expression(feature_names))
        identity_labels = label.labels.filter(
            (pl.col("as_of").is_in(dates))
            & (pl.col("horizon_sessions") == spec.horizon_sessions)
        ).select("as_of", "symbol", "available_as_of", "relative_return")
        _require_unique_keys(scorable, "feature")
        _require_unique_keys(identity_labels, "label")
        joined = scorable.join(
            identity_labels, on=["as_of", "symbol"], how="left", validate="1:1"
        )
        missing = joined.filter(pl.col("relative_return").is_null())
        late = joined.filter(
            pl.col("relative_return").is_not_null()
            & (pl.col("available_as_of") > pl.lit(cutoff))
        )
        for reason, frame in (("MISSING_LABEL", missing), ("LABEL_AFTER_CUTOFF", late)):
            diagnostics.extend(
                {"segment": segment, "as_of": day, "symbol": symbol, "reason": reason}
                for day, symbol in frame.select("as_of", "symbol").iter_rows()
            )
        final = joined.filter(
            pl.col("relative_return").is_not_null()
            & (pl.col("available_as_of") <= pl.lit(cutoff))
        ).select("as_of", "symbol", *feature_names, "relative_return").sort("as_of", "symbol")
        if final.is_empty():
            raise ValueError(f"alignment {segment} empty")
        _require_finite_labels(final)
        path = output_root / f"{segment}.parquet"
        _write_parquet(final, path)
        keys = _keys(final)
        manifests.append(AlignmentSegmentManifestV1(
            name=segment,
            path=path.name,
            bytes_sha256=_file_sha(path),
            row_keys_sha256=canonical_row_keys_sha256(keys),
            matrix_sha256=f64_matrix_sha256(
                columns=feature_names,
                rows=tuple(tuple(row) for row in final.select(*feature_names).iter_rows()),
            ),
            labels_sha256=f64_matrix_sha256(
                columns=("relative_return",),
                rows=tuple((value,) for value in final.get_column("relative_return")),
            ),
            n_feature_scorable=scorable.height,
            n_label_identity=identity_labels.height,
            n_label_joined=joined.filter(pl.col("relative_return").is_not_null()).height,
            n_cutoff_dropped=late.height,
            n_final=final.height,
        ))
    diagnostics_frame = pl.DataFrame(
        diagnostics,
        schema={"segment": pl.Utf8, "as_of": pl.Date, "symbol": pl.Utf8, "reason": pl.Utf8},
    ).sort("segment", "as_of", "symbol", "reason")
    diagnostics_path = output_root / "diagnostics.parquet"
    _write_parquet(diagnostics_frame, diagnostics_path)
    manifest = AlignmentManifestV1(
        schema_version="m3-alignment-artifact-v1",
        experiment_key=experiment.manifest.experiment_key,
        work_key=spec.work_key,
        fold=spec.fold,
        planned_fold_sha256=spec.planned_fold_sha256,
        horizon_sessions=spec.horizon_sessions,
        feature_manifest_sha256=feature.manifest_sha256,
        label_manifest_sha256=label.manifest_sha256,
        selected_feature_schema_sha256=feature.manifest.schema.selected_schema_sha256,
        segments=tuple(manifests),
        diagnostics_path="diagnostics.parquet",
        diagnostics_sha256=_file_sha(diagnostics_path),
        diagnostics_row_count=diagnostics_frame.height,
    )
    _write_exclusive(output_root / "alignment_manifest.json", _canonical_bytes(asdict(manifest)))
    return manifest


@_alignment_boundary
def verify_development_example_alignment_artifact(
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
    config: LoadedM3Config,
    spec: AlignmentBuildSpec,
    upstream_paths: AlignmentUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleAlignmentArtifact:
    """Freshly verify both parents, artifact bytes, logical hashes and receipt."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedDevelopmentExampleG1Release),
        (snapshot, VerifiedDevelopmentExampleSnapshotArtifact),
        (provider, VerifiedDevelopmentExampleProviderArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
        (folds, VerifiedDevelopmentExampleFoldPlanArtifact),
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
        (label, VerifiedDevelopmentExampleLabelArtifact),
    )):
        raise ValueError("development alignment verify requires development inputs")
    verified = _verify_alignment_artifact(
        root=root, receipt_path=receipt_path, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec, folds=folds,
        fold_spec=fold_spec, feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots, formal=False,
    )
    if type(verified) is not VerifiedDevelopmentExampleAlignmentArtifact:
        raise ValueError("development alignment result kind invalid")
    return verified


@_alignment_boundary
def verify_alignment_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity, experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact, fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact, feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact, label_spec: LabelBuildSpec,
    config: LoadedM3Config, spec: AlignmentBuildSpec,
    upstream_paths: AlignmentUpstreamPaths, artifact_roots: Mapping[str, Path],
) -> VerifiedAlignmentArtifact:
    """Fresh-verify formal feature/label parents, alignment bytes and receipt."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedG1Release), (snapshot, VerifiedSnapshotArtifact),
        (provider, VerifiedProviderArtifact),
        (experiment, VerifiedExperimentIdentity),
        (folds, VerifiedFoldPlanArtifact), (feature, VerifiedFeatureArtifact),
        (label, VerifiedLabelArtifact),
    )):
        raise ValueError("formal alignment verify requires formal inputs")
    verified = _verify_alignment_artifact(
        root=root, receipt_path=receipt_path, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec, folds=folds,
        fold_spec=fold_spec, feature=feature, feature_spec=feature_spec, label=label,
        label_spec=label_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots, formal=True,
    )
    if type(verified) is not VerifiedAlignmentArtifact:
        raise ValueError("formal alignment result kind invalid")
    return verified


def _verify_alignment_artifact(
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
    label_spec: LabelBuildSpec, config: LoadedM3Config, spec: AlignmentBuildSpec,
    upstream_paths: AlignmentUpstreamPaths, artifact_roots: Mapping[str, Path],
    formal: bool,
) -> VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact:
    fresh_feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact
    fresh_label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact
    if formal:
        assert isinstance(release, VerifiedG1Release)
        assert isinstance(snapshot, VerifiedSnapshotArtifact)
        assert isinstance(provider, VerifiedProviderArtifact)
        assert isinstance(experiment, VerifiedExperimentIdentity)
        assert isinstance(folds, VerifiedFoldPlanArtifact)
        fresh_feature = verify_feature_artifact(
            root=feature.root, receipt_path=upstream_paths.feature_receipt_path,
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            config=config, spec=feature_spec,
            upstream_paths=upstream_paths.feature_upstream_paths,
            artifact_roots=artifact_roots,
        )
        fresh_label = verify_label_artifact(
            label_root=label.root,
            label_receipt_path=upstream_paths.label_receipt_path,
            release=release, snapshot=snapshot, experiment=experiment,
            config=config, experiment_spec=experiment_spec, spec=label_spec,
            artifact_roots=artifact_roots,
        )
    else:
        assert isinstance(release, VerifiedDevelopmentExampleG1Release)
        assert isinstance(snapshot, VerifiedDevelopmentExampleSnapshotArtifact)
        assert isinstance(provider, VerifiedDevelopmentExampleProviderArtifact)
        assert isinstance(experiment, VerifiedDevelopmentExampleExperimentIdentity)
        assert isinstance(folds, VerifiedDevelopmentExampleFoldPlanArtifact)
        fresh_feature = verify_development_example_feature_artifact(
            root=feature.root, receipt_path=upstream_paths.feature_receipt_path,
            release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
            provider=provider, provider_spec=provider_spec, experiment=experiment,
            experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
            config=config, spec=feature_spec,
            upstream_paths=upstream_paths.feature_upstream_paths,
            artifact_roots=artifact_roots,
        )
        fresh_label = verify_development_example_label_artifact(
            label_root=label.root,
            label_receipt_path=upstream_paths.label_receipt_path,
            release=release, snapshot=snapshot, experiment=experiment,
            config=config, experiment_spec=experiment_spec, spec=label_spec,
            artifact_roots=artifact_roots,
        )
    if (
        fresh_feature != feature
        or fresh_label.manifest != label.manifest
        or fresh_label.manifest_sha256 != label.manifest_sha256
        or fresh_label.label_receipt_sha256 != label.label_receipt_sha256
        or not fresh_label.labels.equals(label.labels)
        or not fresh_label.diagnostics.equals(label.diagnostics)
    ):
        raise ValueError("alignment upstream stale")
    _validate_identity(feature, label, folds, experiment, config, spec, formal=formal)
    if not root.is_dir() or root.is_symlink() or {item.name for item in os.scandir(root)} != _FILES:
        raise ValueError("alignment tree closure drift")
    raw = (root / "alignment_manifest.json").read_bytes()
    manifest = read_alignment_manifest(root / "alignment_manifest.json")
    if (
        manifest.experiment_key != spec.experiment_key
        or manifest.work_key != spec.work_key
        or manifest.fold != spec.fold
        or manifest.planned_fold_sha256 != spec.planned_fold_sha256
        or manifest.horizon_sessions != spec.horizon_sessions
        or manifest.feature_manifest_sha256 != feature.manifest_sha256
        or manifest.label_manifest_sha256 != label.manifest_sha256
        or manifest.selected_feature_schema_sha256
        != feature.manifest.schema.selected_schema_sha256
    ):
        raise ValueError("alignment manifest identity drift")
    rebuilt = _rebuild_manifest(root, manifest)
    if rebuilt != manifest:
        raise ValueError("alignment content drift")
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    expected_diagnostics: list[dict[str, object]] = []
    for entry in manifest.segments:
        expected_frame, expected_counts, segment_diagnostics = _expected_segment(
            feature=feature, label=label, planned=planned, spec=spec,
            segment=entry.name,
        )
        expected_diagnostics.extend(segment_diagnostics)
        names = feature.manifest.schema.selected_names
        expected_tuple = (
            canonical_row_keys_sha256(_keys(expected_frame)),
            f64_matrix_sha256(
                columns=names,
                rows=tuple(tuple(row) for row in expected_frame.select(*names).iter_rows()),
            ),
            f64_matrix_sha256(
                columns=("relative_return",),
                rows=tuple((value,) for value in expected_frame["relative_return"]),
            ),
            *expected_counts,
        )
        actual_tuple = (
            entry.row_keys_sha256, entry.matrix_sha256, entry.labels_sha256,
            entry.n_feature_scorable, entry.n_label_identity,
            entry.n_label_joined, entry.n_cutoff_dropped, entry.n_final,
        )
        if actual_tuple != expected_tuple:
            raise ValueError("alignment supervised rebuild drift")
    expected_diagnostics_frame = pl.DataFrame(
        expected_diagnostics,
        schema={"segment": pl.Utf8, "as_of": pl.Date, "symbol": pl.Utf8, "reason": pl.Utf8},
    ).sort("segment", "as_of", "symbol", "reason")
    if not pl.read_parquet(root / manifest.diagnostics_path).equals(expected_diagnostics_frame):
        raise ValueError("alignment diagnostics content drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("alignment receipt missing")
    receipt = verified_receipt.receipt
    inputs = (
        feature.root / "feature_manifest.json", upstream_paths.feature_receipt_path,
        label.root / "label_manifest.json", upstream_paths.label_receipt_path,
        folds.root / "folds.json", upstream_paths.feature_upstream_paths.fold_receipt_path,
        experiment.root / "experiment_manifest.json",
    )
    outputs = tuple(root / name for name in sorted(_FILES))
    if (
        receipt.stage != ("alignment" if formal else "development-alignment")
        or receipt.scope != "WORK"
        or receipt.scope_key != spec.work_key
        or not _digest_paths_equal(receipt.inputs, inputs, artifact_roots)
        or not _digest_paths_equal(receipt.outputs, outputs, artifact_roots)
    ):
        raise ValueError("alignment receipt closure drift")
    if formal:
        return VerifiedAlignmentArtifact(
            root=root.resolve(strict=True), manifest=manifest,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            alignment_receipt_sha256=verified_receipt.sha256,
        )
    assert isinstance(feature, VerifiedDevelopmentExampleFeatureArtifact)
    return VerifiedDevelopmentExampleAlignmentArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=feature.example_id, root=root.resolve(strict=True),
        manifest=manifest, manifest_sha256=hashlib.sha256(raw).hexdigest(),
        alignment_receipt_sha256=verified_receipt.sha256,
    )


@_alignment_boundary
def read_alignment_manifest(path: Path) -> AlignmentManifestV1:
    try:
        raw = path.read_bytes()
        payload = _strict_object(raw)
    except ValueError:
        raise
    except Exception:
        raise ValueError("M3_ALIGNMENT_ARTIFACT_INVALID") from None
    expected = {
        "schema_version", "experiment_key", "work_key", "fold",
        "planned_fold_sha256", "horizon_sessions", "feature_manifest_sha256",
        "label_manifest_sha256", "selected_feature_schema_sha256", "segments",
        "diagnostics_path", "diagnostics_sha256", "diagnostics_row_count",
    }
    if set(payload) != expected or type(payload.get("segments")) is not list:
        raise ValueError("alignment manifest fields drift")
    segments = tuple(
        AlignmentSegmentManifestV1(**cast(Any, item))
        for item in cast(list[object], payload["segments"])
        if type(item) is dict
    )
    if len(segments) != len(cast(list[object], payload["segments"])):
        raise ValueError("alignment segments invalid")
    payload["segments"] = segments
    manifest = AlignmentManifestV1(**cast(Any, payload))
    if raw != _canonical_bytes(asdict(manifest)):
        raise ValueError("alignment manifest non-canonical")
    return manifest


@_alignment_boundary
def load_development_example_supervised_segment(
    *, alignment: VerifiedDevelopmentExampleAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment:
    if type(alignment) is not VerifiedDevelopmentExampleAlignmentArtifact or segment not in _SEGMENTS:
        raise ValueError("development supervised input invalid")
    return _load_supervised_segment(alignment=alignment, segment=segment)


@_alignment_boundary
def load_supervised_segment(
    *, alignment: VerifiedAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment:
    """Load one verified formal supervised segment with physical digest checks."""
    if type(alignment) is not VerifiedAlignmentArtifact or segment not in _SEGMENTS:
        raise ValueError("formal supervised input invalid")
    return _load_supervised_segment(alignment=alignment, segment=segment)


def _load_supervised_segment(
    *,
    alignment: VerifiedAlignmentArtifact | VerifiedDevelopmentExampleAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment:
    on_disk = read_alignment_manifest(alignment.root / "alignment_manifest.json")
    if on_disk != alignment.manifest:
        raise ValueError("supervised manifest drift")
    entry = next(item for item in on_disk.segments if item.name == segment)
    frame = _read_alignment_frame(alignment.root / entry.path, entry, on_disk)
    metadata = frame.select("as_of", "symbol")
    features = _pandas_features(frame, _feature_columns(frame))
    labels = pd.Series(
        frame.get_column("relative_return").to_numpy(),
        index=features.index, name="relative_return", dtype="float64",
    )
    return SupervisedSegment(name=segment, features=features, labels=labels, metadata=metadata)


@_alignment_boundary
def build_development_example_inference_segment(
    *, release: VerifiedDevelopmentExampleG1Release,
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
    config: LoadedM3Config,
    fold_name: str,
    upstream_paths: InferenceUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> InferenceSegment:
    """Load only scorable test features after fresh feature/fold verification."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedDevelopmentExampleG1Release),
        (snapshot, VerifiedDevelopmentExampleSnapshotArtifact),
        (provider, VerifiedDevelopmentExampleProviderArtifact),
        (experiment, VerifiedDevelopmentExampleExperimentIdentity),
        (folds, VerifiedDevelopmentExampleFoldPlanArtifact),
        (feature, VerifiedDevelopmentExampleFeatureArtifact),
    )):
        raise ValueError("development inference requires development inputs")
    fresh = verify_development_example_feature_artifact(
        root=feature.root, receipt_path=upstream_paths.feature_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        config=config, spec=feature_spec,
        upstream_paths=upstream_paths.feature_upstream_paths,
        artifact_roots=artifact_roots,
    )
    return _build_inference_segment(
        fresh=fresh, feature=feature, fold_name=fold_name,
        error_prefix="development",
    )


@_alignment_boundary
def build_inference_segment(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, config: LoadedM3Config, fold_name: str,
    upstream_paths: InferenceUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> InferenceSegment:
    """Fresh-verify and load formal test features without any label dependency."""
    if any(type(value) is not expected for value, expected in (
        (release, VerifiedG1Release), (snapshot, VerifiedSnapshotArtifact),
        (provider, VerifiedProviderArtifact),
        (experiment, VerifiedExperimentIdentity),
        (folds, VerifiedFoldPlanArtifact), (feature, VerifiedFeatureArtifact),
    )):
        raise ValueError("formal inference requires formal inputs")
    fresh = verify_feature_artifact(
        root=feature.root, receipt_path=upstream_paths.feature_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, folds=folds, fold_spec=fold_spec,
        config=config, spec=feature_spec,
        upstream_paths=upstream_paths.feature_upstream_paths,
        artifact_roots=artifact_roots,
    )
    return _build_inference_segment(
        fresh=fresh, feature=feature, fold_name=fold_name, error_prefix="formal"
    )


def _build_inference_segment(
    *, fresh: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    fold_name: str, error_prefix: str,
) -> InferenceSegment:
    if fresh != feature or fold_name != feature.manifest.fold:
        raise ValueError(f"{error_prefix} inference identity mismatch")
    names = feature.manifest.schema.selected_names
    frame = _read_feature_segment(feature, "test").filter(_scorable_expression(names))
    if frame.is_empty():
        raise ValueError(f"{error_prefix} inference empty")
    metadata = frame.select("as_of", "symbol")
    return InferenceSegment(name="test", features=_pandas_features(frame, names), metadata=metadata)


def _validate_identity(
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config,
    spec: AlignmentBuildSpec,
    *, formal: bool,
) -> Any:
    expected = (
        (VerifiedFeatureArtifact, VerifiedLabelArtifact,
         VerifiedFoldPlanArtifact, VerifiedExperimentIdentity)
        if formal else
        (VerifiedDevelopmentExampleFeatureArtifact,
         VerifiedDevelopmentExampleLabelArtifact,
         VerifiedDevelopmentExampleFoldPlanArtifact,
         VerifiedDevelopmentExampleExperimentIdentity)
    )
    if any(type(value) is not kind for value, kind in zip(
        (feature, label, folds, experiment), expected, strict=True
    )):
        raise ValueError("alignment capability identity mismatch")
    if not formal:
        assert isinstance(feature, VerifiedDevelopmentExampleFeatureArtifact)
        assert isinstance(label, VerifiedDevelopmentExampleLabelArtifact)
        assert isinstance(folds, VerifiedDevelopmentExampleFoldPlanArtifact)
        assert isinstance(experiment, VerifiedDevelopmentExampleExperimentIdentity)
        if len({feature.example_id, label.example_id, folds.example_id,
                experiment.example_id}) != 1:
            raise ValueError("alignment development identity mismatch")
    planned = next((item for item in folds.manifest.folds if item.name == spec.fold), None)
    expected_work = compute_work_key(
        experiment_key=experiment.manifest.experiment_key,
        fold=spec.fold,
        horizon=spec.horizon_sessions,
    )
    if (
        planned is None
        or spec.experiment_key != experiment.manifest.experiment_key
        or spec.work_key != expected_work
        or spec.planned_fold_sha256 != planned.planned_fold_sha256
        or spec.feature_manifest_sha256 != feature.manifest_sha256
        or spec.label_manifest_sha256 != label.manifest_sha256
        or feature.manifest.fold != spec.fold
        or feature.manifest.planned_fold_sha256 != spec.planned_fold_sha256
        or label.manifest.horizon_sessions != spec.horizon_sessions
        or feature.manifest.experiment_key != spec.experiment_key
        or label.manifest.experiment_key != spec.experiment_key
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("alignment identity/config drift")
    return planned


def _expected_segment(
    *, feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    planned: Any, spec: AlignmentBuildSpec,
    segment: Literal["train", "validation"],
) -> tuple[pl.DataFrame, tuple[int, int, int, int, int], list[dict[str, object]]]:
    names = feature.manifest.schema.selected_names
    dates = planned.train_dates if segment == "train" else planned.validation_dates
    cutoff = (
        planned.train_label_available_by
        if segment == "train" else planned.validation_label_available_by
    )
    feature_frame = _read_feature_segment(feature, segment).filter(
        pl.col("as_of").is_in(dates)
    )
    scorable = feature_frame.filter(_scorable_expression(names))
    identity_labels = label.labels.filter(
        (pl.col("as_of").is_in(dates))
        & (pl.col("horizon_sessions") == spec.horizon_sessions)
    ).select("as_of", "symbol", "available_as_of", "relative_return")
    _require_unique_keys(scorable, "feature")
    _require_unique_keys(identity_labels, "label")
    joined = scorable.join(
        identity_labels, on=["as_of", "symbol"], how="left", validate="1:1"
    )
    missing = joined.filter(pl.col("relative_return").is_null())
    late = joined.filter(
        pl.col("relative_return").is_not_null()
        & (pl.col("available_as_of") > pl.lit(cutoff))
    )
    diagnostics = [
        {"segment": segment, "as_of": day, "symbol": symbol, "reason": reason}
        for reason, frame in (("MISSING_LABEL", missing), ("LABEL_AFTER_CUTOFF", late))
        for day, symbol in frame.select("as_of", "symbol").iter_rows()
    ]
    final = joined.filter(
        pl.col("relative_return").is_not_null()
        & (pl.col("available_as_of") <= pl.lit(cutoff))
    ).select("as_of", "symbol", *names, "relative_return").sort("as_of", "symbol")
    counts = (
        scorable.height,
        identity_labels.height,
        joined.filter(pl.col("relative_return").is_not_null()).height,
        late.height,
        final.height,
    )
    return final, counts, diagnostics


def _rebuild_manifest(root: Path, manifest: AlignmentManifestV1) -> AlignmentManifestV1:
    segments: list[AlignmentSegmentManifestV1] = []
    for entry in manifest.segments:
        frame = _read_alignment_frame(root / entry.path, entry, manifest, check_entry=False)
        names = _feature_columns(frame)
        segments.append(AlignmentSegmentManifestV1(
            name=entry.name, path=entry.path, bytes_sha256=_file_sha(root / entry.path),
            row_keys_sha256=canonical_row_keys_sha256(_keys(frame)),
            matrix_sha256=f64_matrix_sha256(
                columns=names, rows=tuple(tuple(row) for row in frame.select(*names).iter_rows())
            ),
            labels_sha256=f64_matrix_sha256(
                columns=("relative_return",), rows=tuple((value,) for value in frame["relative_return"])
            ),
            n_feature_scorable=entry.n_feature_scorable,
            n_label_identity=entry.n_label_identity,
            n_label_joined=entry.n_label_joined,
            n_cutoff_dropped=entry.n_cutoff_dropped,
            n_final=frame.height,
        ))
    diagnostics = pl.read_parquet(root / manifest.diagnostics_path)
    if diagnostics.schema != {"segment": pl.Utf8, "as_of": pl.Date, "symbol": pl.Utf8, "reason": pl.Utf8}:
        raise ValueError("alignment diagnostics schema drift")
    return AlignmentManifestV1(
        **{**asdict(manifest), "segments": tuple(segments),
           "diagnostics_sha256": _file_sha(root / manifest.diagnostics_path),
           "diagnostics_row_count": diagnostics.height}
    )


def _read_feature_segment(
    feature: VerifiedFeatureArtifact | VerifiedDevelopmentExampleFeatureArtifact,
    segment: str,
) -> pl.DataFrame:
    entry = next(item for item in feature.manifest.segments if item.name == segment)
    path = feature.root / entry.path
    frame = pl.read_parquet(path)
    if _file_sha(path) != entry.bytes_sha256 or frame.columns != ["as_of", "symbol", *feature.manifest.schema.selected_names]:
        raise ValueError("feature segment drift")
    return frame.sort("as_of", "symbol")


def _read_alignment_frame(
    path: Path, entry: AlignmentSegmentManifestV1, manifest: AlignmentManifestV1,
    *, check_entry: bool = True,
) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if frame.columns[:2] != ["as_of", "symbol"] or frame.columns[-1:] != ["relative_return"]:
        raise ValueError("alignment frame schema drift")
    names = _feature_columns(frame)
    if any(frame.schema[name] != pl.Float64 for name in (*names, "relative_return")):
        raise ValueError("alignment frame dtype drift")
    keys = _keys(frame)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("alignment frame key/order drift")
    _require_finite_labels(frame)
    if check_entry and (
        _file_sha(path) != entry.bytes_sha256
        or canonical_row_keys_sha256(_keys(frame)) != entry.row_keys_sha256
        or f64_matrix_sha256(columns=names, rows=tuple(tuple(row) for row in frame.select(*names).iter_rows())) != entry.matrix_sha256
        or f64_matrix_sha256(columns=("relative_return",), rows=tuple((value,) for value in frame["relative_return"])) != entry.labels_sha256
        or frame.height != entry.n_final
    ):
        raise ValueError("alignment segment digest drift")
    return frame


def _feature_columns(frame: pl.DataFrame) -> tuple[str, ...]:
    names = tuple(frame.columns[2:-1])
    if not names:
        raise ValueError("alignment feature projection empty")
    return names


def _scorable_expression(names: Sequence[str]) -> pl.Expr:
    return pl.any_horizontal(
        pl.col(name).is_not_null() & pl.col(name).is_not_nan() for name in names
    )


def _require_unique_keys(frame: pl.DataFrame, name: str) -> None:
    if frame.select("as_of", "symbol").n_unique() != frame.height:
        raise ValueError(f"alignment duplicate {name} key")


def _require_finite_labels(frame: pl.DataFrame) -> None:
    if any(not math.isfinite(float(value)) for value in frame["relative_return"]):
        raise ValueError("alignment label non-finite")


def _keys(frame: pl.DataFrame) -> tuple[tuple[str, str], ...]:
    return tuple((day.isoformat(), symbol) for day, symbol in frame.select("as_of", "symbol").iter_rows())


def _pandas_features(frame: pl.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [frame["as_of"].to_list(), frame["symbol"].to_list()],
        names=["as_of", "symbol"],
    )
    return pd.DataFrame(
        {name: frame[name].to_numpy() for name in names}, index=index, dtype="float64"
    )


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...], paths: Sequence[Path], roots: Mapping[str, Path]
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(os.path.normcase(os.path.abspath(path_for_artifact_digest(item, artifact_roots=roots))) for item in digests))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


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


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("alignment output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path, compression="zstd", compression_level=3, statistics=True, row_group_size=65536, use_pyarrow=False)
