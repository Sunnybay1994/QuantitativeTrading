"""Deterministic complete-domain target artifacts for the M3 development chain."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from decimal import Decimal
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

import polars as pl

from quant.domain import TargetWeightSchema
from quant.research.m3.alignment import _read_feature_segment, _scorable_expression
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import TargetBuildSpec, TargetManifestV1, TargetUpstreamPaths
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFeatureArtifact,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExamplePredictionArtifact,
    VerifiedDevelopmentExampleTargetArtifact,
)
from quant.research.m3.features import canonical_row_keys_sha256
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
    cash_buffer = Decimal(str(spec.cash_buffer))
    max_weight = Decimal(str(spec.max_weight))
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
        weight = min((Decimal(1) - cash_buffer) / Decimal(n_selected), max_weight)
        total = weight * Decimal(n_selected)
        if total > Decimal(1) - cash_buffer:
            raise ValueError("target decimal allocation exceeds investable")
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
    frame = TargetWeightSchema.validate(pl.read_parquet(path)).sort("as_of", "symbol")
    if frame.columns != ["as_of", "strategy", "strategy_version", "symbol", "weight"]:
        raise ValueError("target parquet columns drift")
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
