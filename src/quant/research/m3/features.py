"""Safe parent-side contracts and logical digests for M3 feature artifacts.

This module never imports Qlib.  Qlib execution belongs exclusively to the
fresh-worker entrypoint in :mod:`quant.research.m3.qlib_adapter`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FeatureManifestV1,
    FeatureSchemaManifestV1,
    FeatureSegmentManifestV1,
    FeatureUpstreamPaths,
    FoldPlanBuildSpec,
    ProviderBuildSpec,
    SnapshotBuildSpec,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFeatureArtifact,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.folds import verify_development_example_fold_plan_artifact
from quant.research.m3.run_state import (
    ArtifactDigest,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)

_DIGEST_VERSION = "m3-f64-matrix-digest-v1"
_CANONICAL_NAN_LE = bytes.fromhex("000000000000f87f")
_SEGMENTS = ("train", "validation", "test")
_P = ParamSpec("_P")
_T = TypeVar("_T")


def _feature_boundary(function: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise
        except Exception:
            raise ValueError("M3_FEATURE_ARTIFACT_INVALID") from None
    return wrapped


def canonical_row_keys_sha256(rows: Sequence[tuple[str, str]]) -> str:
    """Hash row keys in their frozen order; never sort away alignment errors."""
    normalized: list[list[str]] = []
    for row in rows:
        if (
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
        ):
            raise ValueError("feature row key 非法")
        normalized.append([row[0], row[1]])
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def f64_matrix_sha256(
    *, columns: Sequence[str], rows: Sequence[Sequence[float | int | None]]
) -> str:
    """Return the cross-platform logical digest frozen by the G4-G6 SSOT."""
    names = _column_names(columns)
    header = {
        "digest_version": _DIGEST_VERSION,
        "n_rows": len(rows),
        "columns": list(names),
        "dtype": "float64-le",
    }
    digest = hashlib.sha256()
    digest.update(_canonical_bytes(header))
    digest.update(b"\n")
    for row in rows:
        if len(row) != len(names):
            raise ValueError("feature matrix width 非法")
        for value in row:
            if value is None:
                digest.update(_CANONICAL_NAN_LE)
                continue
            if type(value) not in {int, float}:
                raise ValueError("feature matrix value 非法")
            number = float(value)
            if math.isinf(number):
                raise ValueError("feature matrix 不允许 infinity")
            digest.update(
                _CANONICAL_NAN_LE if math.isnan(number) else struct.pack("<d", number)
            )
    return digest.hexdigest()


def feature_schema_sha256(*, names: Sequence[str]) -> str:
    """Hash an ordered Float64 feature projection."""
    columns = _column_names(names)
    return hashlib.sha256(_canonical_bytes({
        "columns": [
            {"name": name, "dtype": "Float64"}
            for name in columns
        ]
    })).hexdigest()


def feature_segment_content_sha256(
    *, name: str, feature_row_keys_sha256: str,
    feature_matrix_sha256: str, selected_schema_sha256: str,
) -> str:
    """Hash the exact logical FeatureSegment content envelope."""
    if name not in {"train", "validation", "test"}:
        raise ValueError("feature segment name 非法")
    for value in (
        feature_row_keys_sha256, feature_matrix_sha256, selected_schema_sha256,
    ):
        if not _is_hex64(value):
            raise ValueError("feature segment digest 非法")
    return hashlib.sha256(_canonical_bytes({
        "name": name,
        "feature_row_keys_sha256": feature_row_keys_sha256,
        "feature_matrix_sha256": feature_matrix_sha256,
        "selected_schema_sha256": selected_schema_sha256,
    })).hexdigest()


@_feature_boundary
def build_development_example_feature_artifact(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    config: LoadedM3Config, spec: FeatureBuildSpec,
    upstream_paths: FeatureUpstreamPaths,
    artifact_roots: Mapping[str, Path], python_executable: Path,
    output_root: Path, timeout_seconds: float,
) -> FeatureManifestV1:
    """Build one development-only fold-shared feature bundle in a fresh worker."""
    fresh = _fresh_development_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        folds=folds, fold_spec=fold_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots,
    )
    _require_empty_directory(output_root)
    planned = next(item for item in fresh.manifest.folds if item.name == spec.fold)
    eligible_path = dict(release.artifact_paths)["eligible_keys.parquet"]
    eligible = pl.read_parquet(eligible_path).select("as_of", "symbol").sort(
        "as_of", "symbol"
    )
    segment_dates = {
        "train": planned.train_dates,
        "validation": planned.validation_dates,
        "test": planned.test_dates,
    }
    eligible_rows = tuple(
        (name, day.isoformat(), cast(str, symbol))
        for name in _SEGMENTS
        for dates in (segment_dates[name],)
        for day, symbol in eligible.filter(pl.col("as_of").is_in(dates)).iter_rows()
    )
    request = {
        "schema_version": "m3-feature-worker-request-v1",
        "worker_protocol_version": spec.worker_protocol_version,
        "release_kind": "development_example", "formal_gate_eligible": False,
        "example_id": release.manifest.example_id,
        "experiment_key": experiment.manifest.experiment_key,
        "experiment_manifest_sha256": experiment.manifest_sha256,
        "g1_release_id": release.manifest.contract_release_id,
        "g1_release_manifest_sha256": release.manifest_sha256,
        "snapshot_id": snapshot.manifest.snapshot_id,
        "snapshot_manifest_sha256": snapshot.manifest_sha256,
        "provider_key": provider.manifest.provider_key,
        "provider_manifest_sha256": provider.manifest_sha256,
        "provider_receipt_sha256": provider.provider_receipt_sha256,
        "fold": spec.fold, "planned_fold_sha256": planned.planned_fold_sha256,
        "scientific_config_sha256": config.scientific_config_sha256,
        "feature_version": spec.feature_version,
        "qlib_version": spec.expected_qlib_version,
        "segments": {
            name: [day.isoformat() for day in dates]
            for name, dates in segment_dates.items()
        },
        "eligible_rows": [list(row) for row in eligible_rows],
    }
    request_path = output_root / "request.json"
    _write_exclusive(request_path, _canonical_bytes(request))
    worker_root = output_root / ".worker"
    worker_root.mkdir()
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, env.get("PYTHONPATH", "")) if item
    )
    try:
        result = subprocess.run(
            [str(python_executable), "-m", "quant.research.m3.qlib_adapter",
             "build-alpha158-example", "--request", str(request_path),
             "--output-root", str(worker_root)],
            cwd=output_root, env=env, capture_output=True, check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0 or result.stdout or result.stderr:
            raise ValueError("development feature worker failed")
        response_raw = (worker_root / "worker-response.json").read_bytes()
        response = _strict_object(response_raw)
        _validate_worker_response(response, request)
        names = tuple(cast(list[str], response["input_names"]))
        expressions = tuple(cast(list[str], response["expressions"]))
        raw_frames = {
            name: pl.read_parquet(worker_root / f"raw_{name}.parquet")
            for name in _SEGMENTS
        }
        selected, dropped = _select_train_schema(raw_frames["train"], names)
        schema = FeatureSchemaManifestV1(
            feature_version=spec.feature_version, qlib_version="0.9.7",
            input_names=names, expressions=expressions,
            input_schema_sha256=hashlib.sha256(_canonical_bytes({
                "names": list(names), "expressions": list(expressions),
                "dtypes": ["Float64"] * len(names),
            })).hexdigest(),
            selected_names=selected,
            selected_dtypes=("Float64",) * len(selected),
            dropped_all_nan_train=dropped,
            selected_schema_sha256=feature_schema_sha256(names=selected),
        )
        segment_manifests, coverage = _publish_segments(
            raw_frames=raw_frames, names=names, selected=selected,
            segment_dates=segment_dates, eligible_rows=eligible_rows,
            output_root=output_root, selected_schema_sha256=schema.selected_schema_sha256,
        )
        coverage_path = output_root / "coverage.parquet"
        _write_parquet(coverage, coverage_path)
        _write_exclusive(output_root / "worker-response.json", response_raw)
        manifest = FeatureManifestV1(
            schema_version="m3-feature-artifact-v1",
            experiment_key=experiment.manifest.experiment_key,
            experiment_manifest_sha256=experiment.manifest_sha256,
            g1_release_id=release.manifest.contract_release_id,
            g1_release_manifest_sha256=release.manifest_sha256,
            snapshot_id=snapshot.manifest.snapshot_id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            provider_key=provider.manifest.provider_key,
            provider_manifest_sha256=provider.manifest_sha256,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            fold=spec.fold, planned_fold_sha256=planned.planned_fold_sha256,
            scientific_config_sha256=config.scientific_config_sha256,
            eligible_keys_sha256=canonical_row_keys_sha256(tuple(
                (day, symbol) for _, day, symbol in eligible_rows
            )),
            worker_protocol_version=spec.worker_protocol_version, schema=schema,
            segments=segment_manifests, coverage_path="coverage.parquet",
            coverage_sha256=hashlib.sha256(coverage_path.read_bytes()).hexdigest(),
            coverage_row_count=coverage.height,
        )
        _write_exclusive(
            output_root / "feature_manifest.json", _canonical_bytes(asdict(manifest))
        )
        return manifest
    finally:
        shutil.rmtree(worker_root, ignore_errors=True)


@_feature_boundary
def read_feature_manifest(path: Path) -> FeatureManifestV1:
    """Read an exact-field canonical feature manifest."""
    payload = _strict_object(path.read_bytes())
    schema_payload = payload.get("schema")
    segments_payload = payload.get("segments")
    if type(schema_payload) is not dict or type(segments_payload) is not list:
        raise ValueError("feature manifest shape invalid")
    schema = FeatureSchemaManifestV1(**cast(Any, {
        **schema_payload,
        "input_names": tuple(schema_payload["input_names"]),
        "expressions": tuple(schema_payload["expressions"]),
        "selected_names": tuple(schema_payload["selected_names"]),
        "selected_dtypes": tuple(schema_payload["selected_dtypes"]),
        "dropped_all_nan_train": tuple(schema_payload["dropped_all_nan_train"]),
    }))
    segments = tuple(
        FeatureSegmentManifestV1(**cast(Any, item))
        for item in segments_payload
    )
    return FeatureManifestV1(**cast(Any, {
        **payload, "schema": schema, "segments": segments,
    }))


@_feature_boundary
def verify_development_example_feature_artifact(
    *, root: Path, receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, config: LoadedM3Config,
    spec: FeatureBuildSpec, upstream_paths: FeatureUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleFeatureArtifact:
    """Fresh-verify one development feature bundle and its exact receipt closure."""
    fresh = _fresh_development_inputs(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        folds=folds, fold_spec=fold_spec, config=config, spec=spec,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots,
    )
    expected_names = {
        "request.json", "worker-response.json", "train.parquet",
        "validation.parquet", "test.parquet", "coverage.parquet",
        "feature_manifest.json",
    }
    if not root.is_dir() or root.is_symlink() or {entry.name for entry in os.scandir(root)} != expected_names:
        raise ValueError("development feature artifact closure invalid")
    manifest_raw = (root / "feature_manifest.json").read_bytes()
    manifest = read_feature_manifest(root / "feature_manifest.json")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    request_raw = (root / "request.json").read_bytes()
    request = _strict_object(request_raw)
    response = _strict_object((root / "worker-response.json").read_bytes())
    _validate_worker_response(response, request)
    planned = next(item for item in fresh.manifest.folds if item.name == spec.fold)
    identity = {
        "release_kind": "development_example", "formal_gate_eligible": False,
        "example_id": release.manifest.example_id,
        "experiment_key": experiment.manifest.experiment_key,
        "experiment_manifest_sha256": experiment.manifest_sha256,
        "g1_release_id": release.manifest.contract_release_id,
        "g1_release_manifest_sha256": release.manifest_sha256,
        "snapshot_id": snapshot.manifest.snapshot_id,
        "snapshot_manifest_sha256": snapshot.manifest_sha256,
        "provider_key": provider.manifest.provider_key,
        "provider_manifest_sha256": provider.manifest_sha256,
        "provider_receipt_sha256": provider.provider_receipt_sha256,
        "fold": spec.fold, "planned_fold_sha256": planned.planned_fold_sha256,
        "scientific_config_sha256": config.scientific_config_sha256,
        "feature_version": spec.feature_version,
        "qlib_version": spec.expected_qlib_version,
        "worker_protocol_version": spec.worker_protocol_version,
    }
    if any(request.get(key) != value for key, value in identity.items()):
        raise ValueError("development feature request identity drift")
    names = tuple(cast(list[str], response["input_names"]))
    expressions = tuple(cast(list[str], response["expressions"]))
    if names != manifest.schema.input_names or expressions != manifest.schema.expressions:
        raise ValueError("development feature worker schema drift")
    expected_input_schema = hashlib.sha256(_canonical_bytes({
        "names": list(names), "expressions": list(expressions),
        "dtypes": ["Float64"] * len(names),
    })).hexdigest()
    if (
        manifest.schema.input_schema_sha256 != expected_input_schema
        or manifest.schema.selected_schema_sha256
        != feature_schema_sha256(names=manifest.schema.selected_names)
    ):
        raise ValueError("development feature schema digest drift")
    eligible_rows_raw = request.get("eligible_rows")
    if type(eligible_rows_raw) is not list:
        raise ValueError("development feature eligible rows invalid")
    eligible_rows = tuple(tuple(cast(list[str], row)) for row in eligible_rows_raw)
    if any(len(row) != 3 for row in eligible_rows):
        raise ValueError("development feature eligible row invalid")
    rebuilt_segments: list[FeatureSegmentManifestV1] = []
    coverage_rows: list[dict[str, object]] = []
    segments_payload = request.get("segments")
    if type(segments_payload) is not dict:
        raise ValueError("development feature segments invalid")
    for segment in _SEGMENTS:
        frame = pl.read_parquet(root / f"{segment}.parquet")
        selected = manifest.schema.selected_names
        if frame.columns != ["as_of", "symbol", *selected] or any(
            frame.schema[name] != pl.Float64 for name in selected
        ):
            raise ValueError("development feature published schema invalid")
        frame = frame.sort("as_of", "symbol")
        keys = tuple((day.isoformat(), symbol) for day, symbol in frame.select("as_of", "symbol").iter_rows())
        expected = tuple((row[1], row[2]) for row in eligible_rows if row[0] == segment)
        if keys != expected:
            raise ValueError("development feature published keys drift")
        matrix = tuple(tuple(row) for row in frame.select(*selected).iter_rows())
        if any(math.isinf(float(value)) for row in matrix for value in row if value is not None):
            raise ValueError("development feature published infinity")
        scorable = tuple(key for key, row in zip(keys, matrix, strict=True) if any(not _missing(value) for value in row))
        row_hash = canonical_row_keys_sha256(keys)
        matrix_hash = f64_matrix_sha256(columns=selected, rows=matrix)
        path = root / f"{segment}.parquet"
        rebuilt_segments.append(FeatureSegmentManifestV1(
            name=cast(Any, segment), path=f"{segment}.parquet",
            bytes_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            content_sha256=feature_segment_content_sha256(
                name=segment, feature_row_keys_sha256=row_hash,
                feature_matrix_sha256=matrix_hash,
                selected_schema_sha256=manifest.schema.selected_schema_sha256,
            ), eligible_keys_sha256=canonical_row_keys_sha256(expected),
            feature_row_keys_sha256=row_hash, feature_matrix_sha256=matrix_hash,
            scorable_keys_sha256=canonical_row_keys_sha256(scorable),
            n_eligible=len(expected), n_feature_rows=len(keys), n_scorable=len(scorable),
        ))
        date_values = segments_payload.get(segment)
        if type(date_values) is not list:
            raise ValueError("development feature segment dates invalid")
        for day in cast(list[str], date_values):
            day_rows = tuple(
                flag for key, flag in zip(keys, (
                    any(not _missing(value) for value in row) for row in matrix
                ), strict=True) if key[0] == day
            )
            n_eligible = sum(1 for item in expected if item[0] == day)
            n_rows, n_scorable = len(day_rows), sum(day_rows)
            reason = (
                "NO_ELIGIBLE" if n_eligible == 0 else "NO_FEATURE_ROWS" if n_rows == 0
                else "NO_SCORABLE" if n_scorable == 0 else
                "FULL" if n_scorable == n_eligible else "PARTIAL"
            )
            coverage_rows.append({"segment": segment, "as_of": day,
                                  "n_eligible": n_eligible, "n_feature_rows": n_rows,
                                  "n_scorable": n_scorable, "reason": reason})
    coverage = pl.read_parquet(root / "coverage.parquet")
    expected_coverage = pl.DataFrame(coverage_rows, schema={
        "segment": pl.Utf8, "as_of": pl.Utf8, "n_eligible": pl.Int64,
        "n_feature_rows": pl.Int64, "n_scorable": pl.Int64, "reason": pl.Utf8,
    }).with_columns(pl.col("as_of").str.to_date())
    if not coverage.equals(expected_coverage):
        raise ValueError("development feature coverage drift")
    if (
        manifest.segments != tuple(rebuilt_segments)
        or manifest.coverage_sha256
        != hashlib.sha256((root / "coverage.parquet").read_bytes()).hexdigest()
        or manifest.coverage_row_count != coverage.height
        or manifest.eligible_keys_sha256 != canonical_row_keys_sha256(tuple(
            (row[1], row[2]) for row in eligible_rows
        ))
        or manifest.experiment_key != experiment.manifest.experiment_key
        or manifest.fold != spec.fold
    ):
        raise ValueError("development feature manifest drift")
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified_receipt is None:
        raise ValueError("development feature receipt missing")
    receipt = verified_receipt.receipt
    if (
        receipt.stage != "development-features" or receipt.scope != "EXPERIMENT"
        or receipt.scope_key != experiment.manifest.experiment_key
        or not _digest_paths_equal(
            receipt.inputs, _feature_input_paths(
                release=release, snapshot=snapshot, provider=provider,
                experiment=experiment, folds=folds, upstream_paths=upstream_paths,
            ), artifact_roots,
        )
        or not _digest_paths_equal(receipt.outputs, tuple(root / name for name in sorted(expected_names)), artifact_roots)
    ):
        raise ValueError("development feature receipt closure invalid")
    return VerifiedDevelopmentExampleFeatureArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=release.manifest.example_id, root=root.resolve(strict=True),
        manifest=manifest, manifest_sha256=manifest_sha,
        feature_receipt_sha256=verified_receipt.sha256,
    )


def _feature_input_paths(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    upstream_paths: FeatureUpstreamPaths,
) -> tuple[Path, ...]:
    return (
        release.release.manifest_path,
        dict(release.artifact_paths)["eligible_keys.parquet"],
        upstream_paths.fold_upstream_paths.snapshot_request_path,
        snapshot.root / "manifest.json",
        upstream_paths.fold_upstream_paths.snapshot_receipt_path,
        snapshot.session_calendar_path,
        provider.root / "provider_manifest.json",
        upstream_paths.fold_upstream_paths.provider_receipt_path,
        experiment.root / "experiment_manifest.json",
        upstream_paths.fold_upstream_paths.experiment_receipt_path,
        folds.root / "folds.json", upstream_paths.fold_receipt_path,
    )


def _digest_paths_equal(
    digests: tuple[ArtifactDigest, ...], paths: Sequence[Path],
    roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(paths):
        return False
    actual = tuple(sorted(os.path.normcase(os.path.abspath(
        path_for_artifact_digest(item, artifact_roots=roots)
    )) for item in digests))
    expected = tuple(sorted(os.path.normcase(os.path.abspath(path)) for path in paths))
    return actual == expected and len(set(actual)) == len(actual)


def _fresh_development_inputs(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, config: LoadedM3Config, spec: FeatureBuildSpec,
    upstream_paths: FeatureUpstreamPaths, artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleFoldPlanArtifact:
    values = (snapshot, provider, experiment, folds)
    if any(getattr(value, "example_id", None) != release.manifest.example_id for value in values):
        raise ValueError("development feature example identity mismatch")
    fresh = verify_development_example_fold_plan_artifact(
        root=folds.root, receipt_path=upstream_paths.fold_receipt_path,
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, config=config, spec=fold_spec,
        upstream_paths=upstream_paths.fold_upstream_paths,
        artifact_roots=artifact_roots,
    )
    planned = next((item for item in fresh.manifest.folds if item.name == spec.fold), None)
    features = config.section("features")
    if (
        fresh != folds or planned is None
        or spec.experiment_key != experiment.manifest.experiment_key
        or spec.experiment_manifest_sha256 != experiment.manifest_sha256
        or spec.planned_fold_sha256 != planned.planned_fold_sha256
        or spec.provider_key != provider.manifest.provider_key
        or spec.provider_manifest_sha256 != provider.manifest_sha256
        or spec.provider_receipt_sha256 != provider.provider_receipt_sha256
        or spec.feature_version != features["feature_version"]
        or spec.expected_qlib_version != provider.manifest.qlib_version
        or config.scientific_config_sha256 != experiment.manifest.scientific_config_sha256
    ):
        raise ValueError("development feature identity mismatch")
    return fresh


def _select_train_schema(frame: pl.DataFrame, names: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    _require_raw_frame(frame, names)
    dropped = tuple(name for name in names if all(_missing(value) for value in frame[name]))
    selected = tuple(name for name in names if name not in dropped)
    if not selected:
        raise ValueError("feature projection empty")
    return selected, dropped


def _publish_segments(
    *, raw_frames: Mapping[str, pl.DataFrame], names: tuple[str, ...],
    selected: tuple[str, ...], segment_dates: Mapping[str, Sequence[object]],
    eligible_rows: Sequence[tuple[str, str, str]], output_root: Path,
    selected_schema_sha256: str,
) -> tuple[tuple[FeatureSegmentManifestV1, ...], pl.DataFrame]:
    manifests: list[FeatureSegmentManifestV1] = []
    coverage_rows: list[dict[str, object]] = []
    for segment in _SEGMENTS:
        frame = raw_frames[segment]
        _require_raw_frame(frame, names)
        clean = frame.select("as_of", "symbol", *selected).sort("as_of", "symbol")
        keys = tuple((day.isoformat(), symbol) for day, symbol in clean.select("as_of", "symbol").iter_rows())
        expected = tuple((day, symbol) for name, day, symbol in eligible_rows if name == segment)
        if keys != expected or len(keys) != len(set(keys)):
            raise ValueError("feature worker row closure invalid")
        matrix = tuple(tuple(row) for row in clean.select(*selected).iter_rows())
        if any(math.isinf(float(value)) for row in matrix for value in row if value is not None):
            raise ValueError("feature worker infinity invalid")
        scorable = tuple(key for key, row in zip(keys, matrix, strict=True) if any(not _missing(value) for value in row))
        path = output_root / f"{segment}.parquet"
        _write_parquet(clean, path)
        row_hash = canonical_row_keys_sha256(keys)
        matrix_hash = f64_matrix_sha256(columns=selected, rows=matrix)
        manifests.append(FeatureSegmentManifestV1(
            name=cast(Any, segment), path=f"{segment}.parquet",
            bytes_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            content_sha256=feature_segment_content_sha256(
                name=segment, feature_row_keys_sha256=row_hash,
                feature_matrix_sha256=matrix_hash,
                selected_schema_sha256=selected_schema_sha256,
            ),
            eligible_keys_sha256=canonical_row_keys_sha256(expected),
            feature_row_keys_sha256=row_hash, feature_matrix_sha256=matrix_hash,
            scorable_keys_sha256=canonical_row_keys_sha256(scorable),
            n_eligible=len(expected), n_feature_rows=len(keys), n_scorable=len(scorable),
        ))
        by_date: dict[str, list[bool]] = {
            cast(Any, day).isoformat(): [] for day in segment_dates[segment]
        }
        for key, row in zip(keys, matrix, strict=True):
            by_date[key[0]].append(any(not _missing(value) for value in row))
        for day, flags in by_date.items():
            n_eligible = sum(1 for item in expected if item[0] == day)
            n_rows = len(flags)
            n_scorable = sum(flags)
            reason = (
                "NO_ELIGIBLE" if n_eligible == 0 else
                "NO_FEATURE_ROWS" if n_rows == 0 else
                "NO_SCORABLE" if n_scorable == 0 else
                "FULL" if n_scorable == n_eligible else "PARTIAL"
            )
            coverage_rows.append({
                "segment": segment, "as_of": day, "n_eligible": n_eligible,
                "n_feature_rows": n_rows, "n_scorable": n_scorable, "reason": reason,
            })
    coverage = pl.DataFrame(coverage_rows, schema={
        "segment": pl.Utf8, "as_of": pl.Utf8, "n_eligible": pl.Int64,
        "n_feature_rows": pl.Int64, "n_scorable": pl.Int64, "reason": pl.Utf8,
    }).with_columns(pl.col("as_of").str.to_date())
    return tuple(manifests), coverage


def _require_raw_frame(frame: pl.DataFrame, names: tuple[str, ...]) -> None:
    if frame.columns != ["as_of", "symbol", *names] or frame.schema["as_of"] != pl.Date:
        raise ValueError("feature worker frame schema invalid")
    if any(frame.schema[name] != pl.Float64 for name in names):
        raise ValueError("feature worker dtype invalid")


def _validate_worker_response(response: Mapping[str, object], request: Mapping[str, object]) -> None:
    expected_keys = (set(request) - {"eligible_rows"}) | {
        "response_schema_version", "input_names", "expressions"
    }
    names = response.get("input_names")
    expressions = response.get("expressions")
    if (
        set(response) != expected_keys
        or response.get("response_schema_version") != "m3-feature-worker-response-v1"
        or any(response.get(key) != value for key, value in request.items() if key != "eligible_rows")
        or type(names) is not list or len(cast(list[object], names)) != 158
        or type(expressions) is not list or len(cast(list[object], expressions)) != 158
        or len(set(cast(list[object], names))) != 158
        or len(set(cast(list[object], expressions))) != 158
    ):
        raise ValueError("feature worker response invalid")


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


def _missing(value: object) -> bool:
    return value is None or (type(value) is float and math.isnan(value))


def _require_empty_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or any(path.iterdir()):
        raise ValueError("feature output must be an empty real directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )


def _column_names(columns: Sequence[str]) -> tuple[str, ...]:
    result = tuple(columns)
    if (
        not result
        or any(type(name) is not str or not name for name in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError("feature columns 非法")
    return result


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
