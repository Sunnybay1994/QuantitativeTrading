"""交易日滚动切分与训练标签可知时点过滤。"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, cast

import polars as pl

from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    DateSegment,
    ExperimentIdentityManifestV1,
    ExperimentIdentitySpec,
    FoldPlanBuildSpec,
    FoldPlanManifestV1,
    FoldPlanUpstreamPaths,
    LabelBuildSpec,
    PlannedFold,
    ProviderBuildSpec,
    SnapshotBuildSpec,
    TemporalFold,
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleExperimentIdentity,
    VerifiedDevelopmentExampleFoldPlanArtifact,
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleLabelArtifact,
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_experiment_key,
    compute_development_provider_key,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_experiment_key,
    compute_provider_key,
    path_for_artifact_digest,
    select_artifact_root,
    verify_stage_receipt_with_bytes,
)


def make_temporal_folds(
    *,
    open_dates: Sequence[dt.date],
    train_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    step_sessions: int,
    embargo_sessions: int,
) -> list[TemporalFold]:
    """按交易日计数生成互不重叠且带 embargo 的 walk-forward 折。

    窗口布局::

        [train][embargo][validation][embargo][test]

    尾部不足以容纳完整 test 段时不生成该折。
    """
    if min(
        train_sessions,
        validation_sessions,
        test_sessions,
        step_sessions,
    ) <= 0:
        raise ValueError("train/validation/test/step 会话数必须为正")
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions 不得为负")

    dates = list(open_dates)
    block = (
        train_sessions
        + embargo_sessions
        + validation_sessions
        + embargo_sessions
        + test_sessions
    )
    folds: list[TemporalFold] = []
    start = 0
    fold_idx = 1
    while start + block <= len(dates):
        train_start = start
        train_end = train_start + train_sessions - 1
        valid_start = train_end + 1 + embargo_sessions
        valid_end = valid_start + validation_sessions - 1
        test_start = valid_end + 1 + embargo_sessions
        test_end = test_start + test_sessions - 1
        folds.append(
            TemporalFold(
                name=f"fold_{fold_idx:03d}",
                train=DateSegment(dates[train_start], dates[train_end]),
                validation=DateSegment(dates[valid_start], dates[valid_end]),
                test=DateSegment(dates[test_start], dates[test_end]),
            )
        )
        fold_idx += 1
        start += step_sessions
    return folds


def eligible_training_labels(
    labels: pl.DataFrame, *, fold: TemporalFold
) -> pl.DataFrame:
    """仅保留 as_of 落在训练段且 available_as_of <= train_end 的标签行。"""
    required = {"as_of", "available_as_of"}
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"labels 缺少字段: {sorted(missing)}")
    return labels.filter(
        (pl.col("as_of") >= fold.train.start)
        & (pl.col("as_of") <= fold.train.end)
        & (pl.col("available_as_of") <= fold.train.end)
    )


class M3FoldPlanError(ValueError):
    """Stable G4A boundary error without paths or payloads."""

    _CODES = frozenset({"FOLD_PLAN_INPUT_INVALID", "FOLD_PLAN_IDENTITY_MISMATCH"})

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown fold plan error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"M3FoldPlanError({self.code!r})"


def _fold_boundary(code: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapped(*args: object, **kwargs: object) -> Any:
            try:
                return function(*args, **kwargs)
            except M3FoldPlanError:
                raise
            except Exception:
                pass
            sanitized = M3FoldPlanError(code)
            sanitized.__suppress_context__ = True
            raise sanitized

        return wrapped

    return decorate


@_fold_boundary("FOLD_PLAN_INPUT_INVALID")
def build_temporal_fold_plan(
    *, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, output_root: Path,
) -> FoldPlanManifestV1:
    """Build a formal strict FoldPlan into an existing empty stage directory."""
    if (
        type(snapshot) is not VerifiedSnapshotArtifact
        or type(experiment) is not VerifiedExperimentIdentity
    ):
        raise ValueError("formal fold plan requires formal inputs")
    return _build_fold_plan(
        snapshot=snapshot, experiment=experiment, config=config, spec=spec,
        output_root=output_root, example_id=None,
    )


@_fold_boundary("FOLD_PLAN_INPUT_INVALID")
def build_development_example_temporal_fold_plan(
    *, snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: FoldPlanBuildSpec, output_root: Path,
) -> FoldPlanManifestV1:
    """Build the same contract under an explicitly development-only identity."""
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or snapshot.example_id != experiment.example_id
    ):
        raise ValueError("development fold inputs do not match")
    if "development" not in output_root.name.lower() or "example" not in output_root.name.lower():
        raise ValueError("development fold root must be labelled")
    return _build_fold_plan(
        snapshot=snapshot, experiment=experiment, config=config, spec=spec,
        output_root=output_root, example_id=snapshot.example_id,
    )


def _build_fold_plan(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: FoldPlanBuildSpec, output_root: Path,
    example_id: str | None,
) -> FoldPlanManifestV1:
    _validate_fold_inputs(
        snapshot=snapshot, experiment=experiment, config=config, spec=spec,
        example_id=example_id,
    )
    _require_empty_directory(output_root)
    _verify_upstream_files(snapshot=snapshot, experiment=experiment)
    signal_dates = _signal_dates(snapshot=snapshot, spec=spec)
    folds = _planned_folds(signal_dates=signal_dates, spec=spec)
    if not folds:
        raise ValueError("fold plan must not be empty")
    manifest = FoldPlanManifestV1(
        schema_version="m3-fold-plan-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        session_calendar_sha256=snapshot.manifest.session_calendar_sha256,
        signal_dates_sha256=_sha256_json([day.isoformat() for day in signal_dates]),
        scientific_config_sha256=config.scientific_config_sha256,
        signal_start=spec.signal_start, signal_end=spec.signal_end,
        max_horizon_sessions=spec.max_horizon_sessions, folds=folds,
    )
    _write_exclusive(
        output_root / "folds.json", _canonical_contract_bytes(asdict(manifest))
    )
    return manifest


@_fold_boundary("FOLD_PLAN_INPUT_INVALID")
def read_fold_plan_manifest(path: Path) -> FoldPlanManifestV1:
    """Read one canonical, exact-field FoldPlan manifest."""
    return _parse_fold_manifest(_read_regular(path))


@_fold_boundary("FOLD_PLAN_IDENTITY_MISMATCH")
def verify_fold_plan_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedFoldPlanArtifact:
    if (
        type(snapshot) is not VerifiedSnapshotArtifact
        or type(experiment) is not VerifiedExperimentIdentity
    ):
        raise ValueError("formal fold verification requires formal inputs")
    manifest, manifest_sha, receipt_sha = _verify_fold_plan(
        root=root, receipt_path=receipt_path, release=release,
        snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        config=config, spec=spec, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots, example_id=None,
    )
    return VerifiedFoldPlanArtifact(
        root=root.resolve(strict=True), manifest=manifest,
        manifest_sha256=manifest_sha, folds_receipt_sha256=receipt_sha,
    )


@_fold_boundary("FOLD_PLAN_IDENTITY_MISMATCH")
def verify_development_example_fold_plan_artifact(
    *, root: Path, receipt_path: Path,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleFoldPlanArtifact:
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or snapshot.example_id != experiment.example_id
    ):
        raise ValueError("development fold verification inputs do not match")
    manifest, manifest_sha, receipt_sha = _verify_fold_plan(
        root=root, receipt_path=receipt_path, release=release,
        snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        config=config, spec=spec, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots, example_id=snapshot.example_id,
    )
    return VerifiedDevelopmentExampleFoldPlanArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=snapshot.example_id, root=root.resolve(strict=True),
        manifest=manifest, manifest_sha256=manifest_sha,
        folds_receipt_sha256=receipt_sha,
    )


def _verify_fold_plan(
    *, root: Path, receipt_path: Path,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path], example_id: str | None,
) -> tuple[FoldPlanManifestV1, str, str]:
    _validate_fold_inputs(
        snapshot=snapshot, experiment=experiment, config=config, spec=spec,
        example_id=example_id,
    )
    _verify_fold_upstreams(
        release=release, snapshot=snapshot, snapshot_spec=snapshot_spec,
        provider=provider, provider_spec=provider_spec,
        experiment=experiment, experiment_spec=experiment_spec,
        config=config, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots, example_id=example_id,
    )
    _require_real_directory(root)
    if {entry.name for entry in os.scandir(root)} != {"folds.json"}:
        raise ValueError("fold root tree drift")
    _verify_upstream_files(snapshot=snapshot, experiment=experiment)
    raw = _read_regular(root / "folds.json")
    manifest = _parse_fold_manifest(raw)
    expected = _rebuild_fold_manifest(
        snapshot=snapshot, experiment=experiment, config=config, spec=spec
    )
    if manifest != expected:
        raise ValueError("fold manifest drift")
    verified = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path, artifact_roots=artifact_roots
    )
    if verified is None:
        raise ValueError("fold receipt missing")
    inputs = _fold_receipt_inputs(
        snapshot=snapshot, experiment=experiment,
        upstream_paths=upstream_paths, artifact_roots=artifact_roots,
    )
    output = _digest_bytes(
        root / "folds.json", raw=raw, artifact_roots=artifact_roots
    )
    stage = "folds" if example_id is None else "development-folds"
    if (
        verified.receipt.stage != stage
        or verified.receipt.scope != "EXPERIMENT"
        or verified.receipt.scope_key != experiment.manifest.experiment_key
        or verified.receipt.inputs != inputs
        or verified.receipt.outputs != (output,)
    ):
        raise ValueError("fold receipt closure drift")
    return manifest, hashlib.sha256(raw).hexdigest(), verified.sha256


def _rebuild_fold_manifest(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: FoldPlanBuildSpec,
) -> FoldPlanManifestV1:
    signal_dates = _signal_dates(snapshot=snapshot, spec=spec)
    folds = _planned_folds(signal_dates=signal_dates, spec=spec)
    if not folds:
        raise ValueError("fold plan must not be empty")
    return FoldPlanManifestV1(
        schema_version="m3-fold-plan-v1",
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        session_calendar_sha256=snapshot.manifest.session_calendar_sha256,
        signal_dates_sha256=_sha256_json([day.isoformat() for day in signal_dates]),
        scientific_config_sha256=config.scientific_config_sha256,
        signal_start=spec.signal_start, signal_end=spec.signal_end,
        max_horizon_sessions=spec.max_horizon_sessions, folds=folds,
    )


def _signal_dates(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    spec: FoldPlanBuildSpec,
) -> tuple[dt.date, ...]:
    dates = _read_calendar(snapshot)
    signal_dates = tuple(
        day for day in dates if spec.signal_start <= day <= spec.signal_end
    )
    if (
        not signal_dates
        or signal_dates[0] != spec.signal_start
        or signal_dates[-1] != spec.signal_end
    ):
        raise ValueError("signal calendar boundary drift")
    return signal_dates


@_fold_boundary("FOLD_PLAN_INPUT_INVALID")
def select_supervised_labels(
    *, label: VerifiedLabelArtifact, folds: VerifiedFoldPlanArtifact,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    label_spec: LabelBuildSpec, fold_spec: FoldPlanBuildSpec,
    label_receipt_path: Path, folds_receipt_path: Path,
    upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path], fold_name: str,
    segment: Literal["train", "validation"],
) -> pl.DataFrame:
    """Freshly reverify formal bundles, then select labels known by embargo cutoff."""
    if any((
        type(label) is not VerifiedLabelArtifact,
        type(folds) is not VerifiedFoldPlanArtifact,
        type(release) is not VerifiedG1Release,
        type(snapshot) is not VerifiedSnapshotArtifact,
        type(experiment) is not VerifiedExperimentIdentity,
    )):
        raise ValueError("formal label selection requires formal inputs")
    fresh_label, fresh_folds = _fresh_selection_inputs(
        label=label, folds=folds, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider,
        provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, config=config, label_spec=label_spec,
        fold_spec=fold_spec, label_receipt_path=label_receipt_path,
        folds_receipt_path=folds_receipt_path, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
        development=False,
    )
    return _select_labels(
        label=cast(VerifiedLabelArtifact, fresh_label),
        folds=cast(VerifiedFoldPlanArtifact, fresh_folds),
        fold_name=fold_name, segment=segment,
    )


@_fold_boundary("FOLD_PLAN_INPUT_INVALID")
def select_development_example_supervised_labels(
    *, label: VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedDevelopmentExampleFoldPlanArtifact,
    release: VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    label_spec: LabelBuildSpec,
    fold_spec: FoldPlanBuildSpec, label_receipt_path: Path,
    folds_receipt_path: Path, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    fold_name: str, segment: Literal["train", "validation"],
) -> pl.DataFrame:
    """Freshly reverify matching development bundles before label selection."""
    if any((
        type(label) is not VerifiedDevelopmentExampleLabelArtifact,
        type(folds) is not VerifiedDevelopmentExampleFoldPlanArtifact,
        type(release) is not VerifiedDevelopmentExampleG1Release,
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact,
        type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity,
    )) or len({
        label.example_id, folds.example_id, release.manifest.example_id,
        snapshot.example_id, experiment.example_id,
    }) != 1:
        raise ValueError("development label selection inputs do not match")
    fresh_label, fresh_folds = _fresh_selection_inputs(
        label=label, folds=folds, release=release, snapshot=snapshot,
        snapshot_spec=snapshot_spec, provider=provider,
        provider_spec=provider_spec, experiment=experiment,
        experiment_spec=experiment_spec, config=config, label_spec=label_spec,
        fold_spec=fold_spec, label_receipt_path=label_receipt_path,
        folds_receipt_path=folds_receipt_path, upstream_paths=upstream_paths,
        artifact_roots=artifact_roots,
        development=True,
    )
    return _select_labels(
        label=cast(VerifiedDevelopmentExampleLabelArtifact, fresh_label),
        folds=cast(VerifiedDevelopmentExampleFoldPlanArtifact, fresh_folds),
        fold_name=fold_name, segment=segment,
    )


def _fresh_selection_inputs(
    *, label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    label_spec: LabelBuildSpec,
    fold_spec: FoldPlanBuildSpec, label_receipt_path: Path,
    folds_receipt_path: Path, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    development: bool,
) -> tuple[
    VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
]:
    from quant.research.m3.labels import (
        verify_development_example_label_artifact,
        verify_label_artifact,
    )

    if development:
        fresh_label = verify_development_example_label_artifact(
            label_root=label.root, label_receipt_path=label_receipt_path,
            release=cast(VerifiedDevelopmentExampleG1Release, release),
            snapshot=cast(VerifiedDevelopmentExampleSnapshotArtifact, snapshot),
            experiment=cast(
                VerifiedDevelopmentExampleExperimentIdentity, experiment
            ),
            config=config, experiment_spec=experiment_spec, spec=label_spec,
            artifact_roots=artifact_roots,
        )
        fresh_folds = verify_development_example_fold_plan_artifact(
            root=folds.root, receipt_path=folds_receipt_path,
            release=cast(VerifiedDevelopmentExampleG1Release, release),
            snapshot=cast(VerifiedDevelopmentExampleSnapshotArtifact, snapshot),
            snapshot_spec=snapshot_spec,
            provider=cast(VerifiedDevelopmentExampleProviderArtifact, provider),
            provider_spec=provider_spec,
            experiment=cast(
                VerifiedDevelopmentExampleExperimentIdentity, experiment
            ),
            experiment_spec=experiment_spec, config=config, spec=fold_spec,
            upstream_paths=upstream_paths, artifact_roots=artifact_roots,
        )
    else:
        fresh_label = verify_label_artifact(
            label_root=label.root, label_receipt_path=label_receipt_path,
            release=cast(VerifiedG1Release, release),
            snapshot=cast(VerifiedSnapshotArtifact, snapshot),
            experiment=cast(VerifiedExperimentIdentity, experiment),
            config=config, experiment_spec=experiment_spec, spec=label_spec,
            artifact_roots=artifact_roots,
        )
        fresh_folds = verify_fold_plan_artifact(
            root=folds.root, receipt_path=folds_receipt_path,
            release=cast(VerifiedG1Release, release),
            snapshot=cast(VerifiedSnapshotArtifact, snapshot),
            snapshot_spec=snapshot_spec,
            provider=cast(VerifiedProviderArtifact, provider),
            provider_spec=provider_spec,
            experiment=cast(VerifiedExperimentIdentity, experiment),
            experiment_spec=experiment_spec, config=config, spec=fold_spec,
            upstream_paths=upstream_paths, artifact_roots=artifact_roots,
        )
    if not _same_verified_label(fresh_label, label) or fresh_folds != folds:
        raise ValueError("verified selection bundle drift")
    return fresh_label, fresh_folds


def _same_verified_label(
    left: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    right: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
) -> bool:
    return (
        type(left) is type(right)
        and left.root == right.root
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.label_receipt_sha256 == right.label_receipt_sha256
        and left.labels.equals(right.labels)
        and left.diagnostics.equals(right.diagnostics)
        and getattr(left, "example_id", None) == getattr(right, "example_id", None)
    )


def _select_labels(
    *, label: VerifiedLabelArtifact | VerifiedDevelopmentExampleLabelArtifact,
    folds: VerifiedFoldPlanArtifact | VerifiedDevelopmentExampleFoldPlanArtifact,
    fold_name: str, segment: Literal["train", "validation"],
) -> pl.DataFrame:
    if segment not in {"train", "validation"}:
        raise ValueError("supervised segment invalid")
    matches = tuple(fold for fold in folds.manifest.folds if fold.name == fold_name)
    if len(matches) != 1:
        raise ValueError("fold name invalid")
    fold = matches[0]
    dates = fold.train_dates if segment == "train" else fold.validation_dates
    cutoff = (
        fold.train_label_available_by
        if segment == "train" else fold.validation_label_available_by
    )
    return label.labels.filter(
        pl.col("as_of").is_in(dates) & (pl.col("available_as_of") <= cutoff)
    ).sort(["as_of", "symbol"])


def _validate_fold_inputs(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    config: LoadedM3Config, spec: FoldPlanBuildSpec, example_id: str | None,
) -> None:
    if type(config) is not LoadedM3Config or type(spec) is not FoldPlanBuildSpec:
        raise ValueError("fold config/spec invalid")
    if example_id is None:
        if (
            type(snapshot) is not VerifiedSnapshotArtifact
            or type(experiment) is not VerifiedExperimentIdentity
        ):
            raise ValueError("formal fold inputs invalid")
    elif (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
        or snapshot.example_id != example_id
        or experiment.example_id != example_id
    ):
        raise ValueError("development fold inputs invalid")
    walk = config.section("walk_forward")
    horizons = config.section("labels")["horizons_sessions"]
    if type(horizons) is not tuple or not horizons:
        raise ValueError("fold horizons invalid")
    expected = (
        experiment.manifest.experiment_key, experiment.manifest_sha256,
        snapshot.manifest.snapshot_id, snapshot.manifest_sha256,
        snapshot.request.signal_start, snapshot.request.signal_end,
        walk["train_sessions"], walk["validation_sessions"],
        walk["test_sessions"], walk["step_sessions"],
        walk["embargo_sessions"], max(cast(tuple[int, ...], horizons)),
    )
    actual = (
        spec.experiment_key, spec.experiment_manifest_sha256,
        spec.snapshot_id, spec.snapshot_manifest_sha256,
        spec.signal_start, spec.signal_end, spec.train_sessions,
        spec.validation_sessions, spec.test_sessions, spec.step_sessions,
        spec.embargo_sessions, spec.max_horizon_sessions,
    )
    if (
        actual != expected
        or snapshot.request.signal_start != snapshot.manifest.signal_start
        or snapshot.request.signal_end != snapshot.manifest.signal_end
        or experiment.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or experiment.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or experiment.manifest.scientific_config_sha256
        != config.scientific_config_sha256
    ):
        raise ValueError("fold identity/config drift")


def _planned_folds(
    *, signal_dates: tuple[dt.date, ...], spec: FoldPlanBuildSpec,
) -> tuple[PlannedFold, ...]:
    block = (
        spec.train_sessions + spec.embargo_sessions
        + spec.validation_sessions + spec.embargo_sessions + spec.test_sessions
    )
    result: list[PlannedFold] = []
    start = 0
    while start + block <= len(signal_dates):
        cursor = start
        train = signal_dates[cursor:cursor + spec.train_sessions]
        cursor += spec.train_sessions
        embargo_one = signal_dates[cursor:cursor + spec.embargo_sessions]
        cursor += spec.embargo_sessions
        validation = signal_dates[cursor:cursor + spec.validation_sessions]
        cursor += spec.validation_sessions
        embargo_two = signal_dates[cursor:cursor + spec.embargo_sessions]
        cursor += spec.embargo_sessions
        test = signal_dates[cursor:cursor + spec.test_sessions]
        name = f"fold_{len(result) + 1:03d}"
        payload = {
            "name": name,
            "train_dates": train,
            "train_validation_embargo_dates": embargo_one,
            "validation_dates": validation,
            "validation_test_embargo_dates": embargo_two,
            "test_dates": test,
            "train_label_available_by": embargo_one[-1],
            "validation_label_available_by": embargo_two[-1],
        }
        result.append(PlannedFold(
            name=name,
            train_dates=train,
            train_validation_embargo_dates=embargo_one,
            validation_dates=validation,
            validation_test_embargo_dates=embargo_two,
            test_dates=test,
            train_label_available_by=embargo_one[-1],
            validation_label_available_by=embargo_two[-1],
            planned_fold_sha256=hashlib.sha256(
                _canonical_contract_bytes(payload)
            ).hexdigest(),
        ))
        start += spec.step_sessions
    test_dates = [day for fold in result for day in fold.test_dates]
    if len(test_dates) != len(set(test_dates)):
        raise ValueError("fold test overlap")
    return tuple(result)


def _read_calendar(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
) -> tuple[dt.date, ...]:
    raw = _read_regular(snapshot.session_calendar_path)
    frame = pl.read_parquet(io.BytesIO(raw))
    if frame.columns != ["date"] or frame.schema["date"] != pl.Date:
        raise ValueError("fold calendar schema invalid")
    dates = tuple(frame.get_column("date").to_list())
    logical_sha = _sha256_json([day.isoformat() for day in dates])
    if (
        not dates
        or dates != tuple(sorted(set(dates)))
        or logical_sha != snapshot.manifest.session_calendar_sha256
        or len(dates) != snapshot.manifest.session_count
        or dates[0] != snapshot.manifest.session_start
        or dates[-1] != snapshot.manifest.session_end
        or not raw
    ):
        raise ValueError("fold calendar drift")
    return dates


def _verify_upstream_files(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
) -> None:
    snapshot_raw = _read_regular(snapshot.root / "manifest.json")
    experiment_raw = _read_regular(experiment.root / "experiment_manifest.json")
    if (
        snapshot_raw != _canonical_contract_bytes(asdict(snapshot.manifest))
        or hashlib.sha256(snapshot_raw).hexdigest() != snapshot.manifest_sha256
        or experiment_raw != _canonical_contract_bytes(asdict(experiment.manifest))
        or hashlib.sha256(experiment_raw).hexdigest() != experiment.manifest_sha256
    ):
        raise ValueError("fold upstream bytes drift")


def _verify_fold_upstreams(
    *,
    release: VerifiedG1Release | VerifiedDevelopmentExampleG1Release,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    config: LoadedM3Config,
    upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    example_id: str | None,
) -> None:
    from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
    from quant.research.m3.provider import (
        build_provider_runtime_fingerprint,
        inspect_development_example_provider_structure,
        inspect_provider_structure,
    )
    from quant.research.m3.snapshot import (
        verify_development_example_snapshot_artifact,
        verify_snapshot_artifact,
    )

    if (
        type(snapshot_spec) is not SnapshotBuildSpec
        or type(provider_spec) is not ProviderBuildSpec
        or type(experiment_spec) is not ExperimentIdentitySpec
        or type(upstream_paths) is not FoldPlanUpstreamPaths
    ):
        raise ValueError("fold upstream spec invalid")
    fresh_snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact
    if example_id is None:
        if (
            type(release) is not VerifiedG1Release
            or type(snapshot) is not VerifiedSnapshotArtifact
            or type(provider) is not VerifiedProviderArtifact
            or type(experiment) is not VerifiedExperimentIdentity
        ):
            raise ValueError("formal fold upstream nominal invalid")
        fresh_snapshot = verify_snapshot_artifact(
            snapshot_root=snapshot.root,
            snapshot_request_path=upstream_paths.snapshot_request_path,
            snapshot_receipt_path=upstream_paths.snapshot_receipt_path,
            release=release,
            config=config,
            spec=snapshot_spec,
            artifact_roots=artifact_roots,
        )
    else:
        if (
            type(release) is not VerifiedDevelopmentExampleG1Release
            or type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
            or type(provider) is not VerifiedDevelopmentExampleProviderArtifact
            or type(experiment) is not VerifiedDevelopmentExampleExperimentIdentity
            or len({
                release.manifest.example_id,
                snapshot.example_id,
                provider.example_id,
                experiment.example_id,
                example_id,
            }) != 1
        ):
            raise ValueError("development fold upstream nominal invalid")
        fresh_snapshot = verify_development_example_snapshot_artifact(
            snapshot_root=snapshot.root,
            snapshot_request_path=upstream_paths.snapshot_request_path,
            snapshot_receipt_path=upstream_paths.snapshot_receipt_path,
            release=release,
            config=config,
            spec=snapshot_spec,
            artifact_roots=artifact_roots,
        )
    if fresh_snapshot != snapshot:
        raise ValueError("fold snapshot bundle drift")

    runtime = build_provider_runtime_fingerprint()
    dump_tool = build_qlib_dump_tool_spec(config)
    dump_tool_raw = _read_regular(upstream_paths.provider_dump_tool_path)
    if (
        len(dump_tool_raw) != dump_tool.size_bytes
        or hashlib.sha256(dump_tool_raw).hexdigest() != dump_tool.sha256
    ):
        raise ValueError("fold provider dump tool drift")
    expected_provider_key = (
        compute_provider_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_config_hash=config.provider_config_sha256,
            dump_tool_sha256=dump_tool.sha256,
            qlib_version="0.9.7",
            provider_runtime_fingerprint_sha256=runtime.sha256,
            code_version=provider_spec.code_version,
        )
        if example_id is None
        else compute_development_provider_key(
            example_id=example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            provider_config_sha256=config.provider_config_sha256,
            dump_tool_sha256=dump_tool.sha256,
            qlib_version="0.9.7",
            provider_runtime_fingerprint_sha256=runtime.sha256,
            code_version=provider_spec.code_version,
        )
    )
    if (
        provider_spec.snapshot_id != snapshot.manifest.snapshot_id
        or provider_spec.snapshot_manifest_sha256 != snapshot.manifest_sha256
        or provider_spec.provider_key != expected_provider_key
        or provider_spec.provider_config_sha256 != config.provider_config_sha256
        or provider_spec.dump_tool != dump_tool
        or provider_spec.runtime_fingerprint != runtime
        or provider.manifest.provider_key != expected_provider_key
    ):
        raise ValueError("fold provider spec drift")
    rebuilt_provider = (
        inspect_provider_structure(
            qlib_dir=provider.qlib_dir,
            snapshot=cast(VerifiedSnapshotArtifact, snapshot),
            spec=provider_spec,
        )
        if example_id is None
        else inspect_development_example_provider_structure(
            qlib_dir=provider.qlib_dir,
            snapshot=cast(VerifiedDevelopmentExampleSnapshotArtifact, snapshot),
            spec=provider_spec,
        )
    )
    provider_manifest_path = provider.root / "provider_manifest.json"
    provider_manifest_raw = _read_regular(provider_manifest_path)
    if (
        rebuilt_provider != provider.manifest
        or provider_manifest_raw
        != _canonical_contract_bytes(asdict(provider.manifest))
        or hashlib.sha256(provider_manifest_raw).hexdigest()
        != provider.manifest_sha256
    ):
        raise ValueError("fold provider bundle drift")
    provider_receipt = verify_stage_receipt_with_bytes(
        receipt_path=upstream_paths.provider_receipt_path,
        artifact_roots=artifact_roots,
    )
    provider_input_paths = (
        upstream_paths.snapshot_request_path,
        upstream_paths.snapshot_receipt_path,
        snapshot.root / "manifest.json",
        snapshot.session_calendar_path,
        *snapshot.staging_paths,
        upstream_paths.provider_dump_tool_path,
    )
    provider_output_paths = (
        provider_manifest_path,
        *(provider.root / item.relative_path for item in provider.manifest.files),
    )
    provider_stage = "provider" if example_id is None else "development-provider"
    if (
        provider_receipt is None
        or provider_receipt.sha256 != provider.provider_receipt_sha256
        or provider_receipt.receipt.stage != provider_stage
        or provider_receipt.receipt.scope != "PROVIDER"
        or provider_receipt.receipt.scope_key != expected_provider_key
        or not _receipt_has_exact_paths(
            provider_receipt.receipt.inputs,
            expected_paths=provider_input_paths,
            artifact_roots=artifact_roots,
        )
        or not _receipt_has_exact_paths(
            provider_receipt.receipt.outputs,
            expected_paths=provider_output_paths,
            artifact_roots=artifact_roots,
        )
    ):
        raise ValueError("fold provider receipt drift")

    expected_experiment_key = (
        compute_experiment_key(
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_hash=experiment_spec.scientific_config_sha256,
            code_version=experiment_spec.code_version,
            dependency_fingerprint_sha256=(
                experiment_spec.dependency_fingerprint_sha256
            ),
        )
        if example_id is None
        else compute_development_experiment_key(
            example_id=example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            scientific_config_sha256=experiment_spec.scientific_config_sha256,
            code_version=experiment_spec.code_version,
            dependency_fingerprint_sha256=(
                experiment_spec.dependency_fingerprint_sha256
            ),
        )
    )
    expected_experiment = ExperimentIdentityManifestV1(
        schema_version="m3-experiment-identity-v1",
        experiment_key=expected_experiment_key,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=(
            experiment_spec.dependency_fingerprint_sha256
        ),
        code_version=experiment_spec.code_version,
    )
    experiment_manifest_path = experiment.root / "experiment_manifest.json"
    experiment_raw = _read_regular(experiment_manifest_path)
    experiment_receipt = verify_stage_receipt_with_bytes(
        receipt_path=upstream_paths.experiment_receipt_path,
        artifact_roots=artifact_roots,
    )
    experiment_stage = (
        "experiment-identity"
        if example_id is None else "development-experiment-identity"
    )
    if (
        experiment_spec.scientific_config_sha256
        != config.scientific_config_sha256
        or experiment.manifest != expected_experiment
        or experiment_raw != _canonical_contract_bytes(asdict(expected_experiment))
        or hashlib.sha256(experiment_raw).hexdigest()
        != experiment.manifest_sha256
        or experiment_receipt is None
        or experiment_receipt.sha256 != experiment.experiment_receipt_sha256
        or experiment_receipt.receipt.stage != experiment_stage
        or experiment_receipt.receipt.scope != "EXPERIMENT"
        or experiment_receipt.receipt.scope_key != expected_experiment_key
        or not _receipt_has_exact_paths(
            experiment_receipt.receipt.inputs,
            expected_paths=(
                upstream_paths.snapshot_receipt_path,
                snapshot.root / "manifest.json",
                upstream_paths.provider_receipt_path,
                provider_manifest_path,
            ),
            artifact_roots=artifact_roots,
        )
        or not _receipt_has_exact_paths(
            experiment_receipt.receipt.outputs,
            expected_paths=(experiment_manifest_path,),
            artifact_roots=artifact_roots,
        )
    ):
        raise ValueError("fold experiment bundle drift")


def _fold_receipt_inputs(
    *,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    experiment: VerifiedExperimentIdentity | VerifiedDevelopmentExampleExperimentIdentity,
    upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> tuple[ArtifactDigest, ...]:
    return _digests((
        upstream_paths.snapshot_request_path,
        snapshot.root / "manifest.json",
        upstream_paths.snapshot_receipt_path,
        snapshot.session_calendar_path,
        experiment.root / "experiment_manifest.json",
        upstream_paths.experiment_receipt_path,
    ), artifact_roots)


def _parse_fold_manifest(raw: bytes) -> FoldPlanManifestV1:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "experiment_key", "experiment_manifest_sha256",
        "snapshot_id", "snapshot_manifest_sha256", "session_calendar_sha256",
        "signal_dates_sha256", "scientific_config_sha256", "signal_start",
        "signal_end", "max_horizon_sessions", "folds",
    }
    if set(payload) != expected or type(payload["folds"]) is not list:
        raise ValueError("fold manifest fields drift")
    folds: list[PlannedFold] = []
    fold_fields = {
        "name", "train_dates", "train_validation_embargo_dates",
        "validation_dates", "validation_test_embargo_dates", "test_dates",
        "train_label_available_by", "validation_label_available_by",
        "planned_fold_sha256",
    }
    date_lists = (
        "train_dates", "train_validation_embargo_dates", "validation_dates",
        "validation_test_embargo_dates", "test_dates",
    )
    for value in cast(list[object], payload["folds"]):
        if type(value) is not dict or set(value) != fold_fields:
            raise ValueError("planned fold fields drift")
        item = cast(dict[str, object], value)
        converted = dict(item)
        for name in date_lists:
            raw_dates = item[name]
            if type(raw_dates) is not list:
                raise ValueError("planned fold date list invalid")
            converted[name] = tuple(
                dt.date.fromisoformat(cast(str, day)) for day in raw_dates
            )
        converted["train_label_available_by"] = dt.date.fromisoformat(
            cast(str, item["train_label_available_by"])
        )
        converted["validation_label_available_by"] = dt.date.fromisoformat(
            cast(str, item["validation_label_available_by"])
        )
        fold = PlannedFold(**cast(Any, converted))
        unhashed = asdict(fold)
        unhashed.pop("planned_fold_sha256")
        if fold.planned_fold_sha256 != hashlib.sha256(
            _canonical_contract_bytes(unhashed)
        ).hexdigest():
            raise ValueError("planned fold hash drift")
        folds.append(fold)
    values = dict(payload)
    values["signal_start"] = dt.date.fromisoformat(cast(str, payload["signal_start"]))
    values["signal_end"] = dt.date.fromisoformat(cast(str, payload["signal_end"]))
    values["folds"] = tuple(folds)
    manifest = FoldPlanManifestV1(**cast(Any, values))
    if raw != _canonical_contract_bytes(asdict(manifest)):
        raise ValueError("fold manifest not canonical")
    return manifest


def _strict_json(raw: bytes) -> dict[str, object]:
    def hook(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return value


def _canonical_contract_bytes(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_contract_bytes(value)).hexdigest()


def _read_regular(path: Path) -> bytes:
    _reject_parent_links(path.parent)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        _validate_regular(before)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read()
        after = os.fstat(descriptor)
        _validate_regular(after)
        if (
            (before.st_dev, before.st_ino, before.st_size, getattr(before, "st_mtime_ns", None))
            != (after.st_dev, after.st_ino, after.st_size, getattr(after, "st_mtime_ns", None))
            or len(raw) != after.st_size
        ):
            raise ValueError("artifact changed while reading")
        _reject_parent_links(path.parent)
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("artifact path identity changed")
        return raw
    finally:
        os.close(descriptor)


def _validate_regular(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_nlink", 1) != 1
        or getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("artifact regular file invalid")


def _reject_parent_links(path: Path) -> None:
    current = path.absolute()
    while True:
        info = os.lstat(current)
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("artifact parent link invalid")
        if current == current.parent:
            break
        current = current.parent


def _require_real_directory(path: Path) -> None:
    _reject_parent_links(path.parent)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("artifact directory invalid")


def _require_empty_directory(path: Path) -> None:
    _require_real_directory(path)
    if any(path.iterdir()):
        raise ValueError("artifact output must be empty")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _digests(
    paths: Sequence[Path], artifact_roots: Mapping[str, Path],
) -> tuple[ArtifactDigest, ...]:
    result: list[ArtifactDigest] = []
    for path in paths:
        raw = _read_regular(path)
        alias, root = select_artifact_root(path, artifact_roots=artifact_roots)
        absolute = Path(os.path.abspath(path))
        result.append(ArtifactDigest(
            root_alias=alias,
            relative_path=absolute.relative_to(root).as_posix(),
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        ))
    return tuple(sorted(result, key=lambda item: (item.root_alias, item.relative_path)))


def _receipt_has_exact_paths(
    digests: tuple[ArtifactDigest, ...], *, expected_paths: Sequence[Path],
    artifact_roots: Mapping[str, Path],
) -> bool:
    if len(digests) != len(expected_paths):
        return False
    actual = tuple(sorted(
        os.path.normcase(os.path.abspath(path_for_artifact_digest(
            digest, artifact_roots=artifact_roots
        )))
        for digest in digests
    ))
    expected = tuple(sorted(
        os.path.normcase(os.path.abspath(path)) for path in expected_paths
    ))
    return actual == expected and len(set(actual)) == len(actual)


def _digest_bytes(
    path: Path, *, raw: bytes, artifact_roots: Mapping[str, Path],
) -> ArtifactDigest:
    alias, root = select_artifact_root(path, artifact_roots=artifact_roots)
    absolute = Path(os.path.abspath(path))
    return ArtifactDigest(
        root_alias=alias,
        relative_path=absolute.relative_to(root).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
