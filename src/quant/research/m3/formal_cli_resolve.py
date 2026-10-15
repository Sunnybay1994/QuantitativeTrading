"""Zero-write formal backtest CLI input resolver (G8C-C0)."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, NoReturn, cast

from quant.backtest.a_share_execution import AShareMarketFactsFreshVerificationContext
from quant.backtest.a_share_plan import (
    BacktestPlanFreshVerificationContext,
    verify_backtest_plan_artifact,
)
from quant.backtest.a_share_reporting import (
    BacktestArtifactFreshVerificationContext,
    FormalBacktestArtifactUpstreamPaths,
    verify_backtest_artifact,
)
from quant.data.m3_release import G1Release, VerifiedG1Release, verify_g1_release
from quant.research.m3.alignment import verify_alignment_artifact
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AlignmentBuildSpec,
    AlignmentUpstreamPaths,
    EvaluationSpec,
    EvaluationUpstreamPaths,
    ExperimentIdentitySpec,
    FeatureBuildSpec,
    FeatureUpstreamPaths,
    FoldPlanBuildSpec,
    FoldPlanUpstreamPaths,
    LabelBuildSpec,
    ModelUpstreamPaths,
    PredictionBuildSpec,
    PredictionUpstreamPaths,
    ProviderBuildSpec,
    ProviderValidationSpec,
    SnapshotBuildSpec,
    TargetBuildSpec,
    TargetUpstreamPaths,
    VerifiedAlignmentArtifact,
    VerifiedBacktestArtifact,
    VerifiedBacktestPlanArtifact,
    VerifiedExperimentIdentity,
    VerifiedEvaluationArtifact,
    VerifiedFeatureArtifact,
    VerifiedFoldPlanArtifact,
    VerifiedLabelArtifact,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
    VerifiedTargetArtifact,
)
from quant.research.m3.features import verify_feature_artifact
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.folds import verify_fold_plan_artifact
from quant.research.m3.labels import verify_experiment_identity, verify_label_artifact
from quant.research.m3.evaluate import (
    EvaluationFreshVerificationContext,
    verify_evaluation_artifact,
)
from quant.research.m3.model import build_lightgbm_training_spec, verify_model_artifact
from quant.research.m3.predictions import verify_prediction_artifact
from quant.research.m3.provider import (
    build_provider_runtime_fingerprint,
    clear_reparse_chain_cache,
    verify_provider_artifact,
)
from quant.research.m3.provider_validation import verify_provider_validation_artifact
from quant.research.m3.run_state import (
    compute_experiment_key,
    compute_provider_key,
    compute_provider_validation_key,
    compute_snapshot_request_key,
    compute_work_key,
)
from quant.research.m3.runtime_identity import (
    M3RuntimeIdentityError,
    M3RuntimeIdentityV1,
    M3SourceDigestV1,
    compute_m3_runtime_identity,
)
from quant.research.m3.snapshot import (
    read_snapshot_manifest,
    read_snapshot_request_record,
    verify_snapshot_artifact,
)
from quant.research.m3.targets import verify_target_artifact
from quant.research.m3.tracking import FormalTrackingFreshVerificationContext

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FOLD = re.compile(r"^fold_[0-9]{3}$")
_PROVIDER_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_CODE_INPUT = "FORMAL_CLI_INPUT_INVALID"
_CODE_CONFIG = "FORMAL_CLI_CONFIG_INVALID"
_CODE_RUNTIME = "FORMAL_CLI_RUNTIME_IDENTITY_INVALID"
_CODE_G1 = "FORMAL_CLI_G1_INVALID"
_CODE_UPSTREAM = "FORMAL_CLI_UPSTREAM_INVALID"
_CODE_DEPENDENCY = "FORMAL_CLI_DEPENDENCY_UNAVAILABLE"
_CODE_MISSING = "FORMAL_CLI_ARTIFACT_MISSING"
_CODE_CLOSURE = "FORMAL_CLI_CLOSURE_DRIFT"


class FormalCliResolveError(ValueError):
    """Stable, redacted formal CLI resolve failure."""

    code: str
    exit_code: int

    def __init__(self, code: str, exit_code: int, message: str | None = None) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(message if message is not None else code)


@dataclass(frozen=True)
class FormalBacktestCliResolution:
    """Process-local verified values for a future C1 formal backtest call."""

    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: LoadedM3Config
    release: VerifiedG1Release
    experiment: VerifiedExperimentIdentity
    target: VerifiedTargetArtifact
    plan: VerifiedBacktestPlanArtifact
    fresh_context: BacktestArtifactFreshVerificationContext
    work_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage_root, Path)
            or not isinstance(self.artifact_roots, Mapping)
            or type(self.config) is not LoadedM3Config
            or type(self.release) is not VerifiedG1Release
            or type(self.experiment) is not VerifiedExperimentIdentity
            or type(self.target) is not VerifiedTargetArtifact
            or type(self.plan) is not VerifiedBacktestPlanArtifact
            or type(self.fresh_context) is not BacktestArtifactFreshVerificationContext
            or type(self.work_key) is not str
            or not _HEX64.fullmatch(self.work_key)
        ):
            raise FormalCliResolveError(_CODE_INPUT, 2)

    def __reduce__(self) -> Any:
        raise TypeError(_CODE_INPUT)


@dataclass(frozen=True)
class FormalTrackingCliResolution:
    """Fresh evaluation/backtest inputs for one formal tracking CLI call."""

    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: LoadedM3Config
    evaluation: VerifiedEvaluationArtifact
    backtest: VerifiedBacktestArtifact
    fresh_context: FormalTrackingFreshVerificationContext
    work_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage_root, Path)
            or not isinstance(self.artifact_roots, Mapping)
            or type(self.config) is not LoadedM3Config
            or type(self.evaluation) is not VerifiedEvaluationArtifact
            or type(self.backtest) is not VerifiedBacktestArtifact
            or type(self.fresh_context) is not FormalTrackingFreshVerificationContext
            or type(self.work_key) is not str
            or not _HEX64.fullmatch(self.work_key)
        ):
            raise FormalCliResolveError(_CODE_INPUT, 2)

    def __reduce__(self) -> Any:
        raise TypeError(_CODE_INPUT)


@dataclass(frozen=True)
class FormalReproducibilityCliResolution:
    """Fresh formal inputs through alignment, without reading normal work outputs."""

    stage_root: Path
    artifact_roots: Mapping[str, Path]
    config: LoadedM3Config
    runtime: M3RuntimeIdentityV1
    release: VerifiedG1Release
    snapshot: VerifiedSnapshotArtifact
    snapshot_spec: SnapshotBuildSpec
    provider: VerifiedProviderArtifact
    provider_spec: ProviderBuildSpec
    experiment: VerifiedExperimentIdentity
    experiment_spec: ExperimentIdentitySpec
    folds: VerifiedFoldPlanArtifact
    fold_spec: FoldPlanBuildSpec
    fold_upstream_paths: FoldPlanUpstreamPaths
    fold_receipt_path: Path
    feature: VerifiedFeatureArtifact
    feature_spec: FeatureBuildSpec
    feature_upstream_paths: FeatureUpstreamPaths
    feature_receipt_path: Path
    label: VerifiedLabelArtifact
    label_spec: LabelBuildSpec
    label_receipt_path: Path
    alignment: VerifiedAlignmentArtifact
    alignment_spec: AlignmentBuildSpec
    alignment_upstream_paths: AlignmentUpstreamPaths
    alignment_receipt_path: Path
    work_key: str

    def __post_init__(self) -> None:
        exact = (
            (self.config, LoadedM3Config),
            (self.runtime, M3RuntimeIdentityV1),
            (self.release, VerifiedG1Release),
            (self.snapshot, VerifiedSnapshotArtifact),
            (self.snapshot_spec, SnapshotBuildSpec),
            (self.provider, VerifiedProviderArtifact),
            (self.provider_spec, ProviderBuildSpec),
            (self.experiment, VerifiedExperimentIdentity),
            (self.experiment_spec, ExperimentIdentitySpec),
            (self.folds, VerifiedFoldPlanArtifact),
            (self.fold_spec, FoldPlanBuildSpec),
            (self.fold_upstream_paths, FoldPlanUpstreamPaths),
            (self.feature, VerifiedFeatureArtifact),
            (self.feature_spec, FeatureBuildSpec),
            (self.feature_upstream_paths, FeatureUpstreamPaths),
            (self.label, VerifiedLabelArtifact),
            (self.label_spec, LabelBuildSpec),
            (self.alignment, VerifiedAlignmentArtifact),
            (self.alignment_spec, AlignmentBuildSpec),
            (self.alignment_upstream_paths, AlignmentUpstreamPaths),
        )
        paths = (
            self.stage_root,
            self.fold_receipt_path,
            self.feature_receipt_path,
            self.label_receipt_path,
            self.alignment_receipt_path,
        )
        if (
            not isinstance(self.artifact_roots, Mapping)
            or any(type(value) is not expected for value, expected in exact)
            or any(not isinstance(path, Path) for path in paths)
            or type(self.work_key) is not str
            or not _HEX64.fullmatch(self.work_key)
        ):
            raise FormalCliResolveError(_CODE_INPUT, 2)

    def __reduce__(self) -> Any:
        raise TypeError(_CODE_INPUT)


def resolve_formal_backtest_cli_inputs(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
) -> FormalBacktestCliResolution:
    """Resolve and freshly verify the formal backtest CLI input closure."""
    try:
        return cast(
            FormalBacktestCliResolution,
            _resolve(
                project_root=project_root,
                config=config,
                config_relative=config_relative,
                snapshot_id=snapshot_id,
                fold=fold,
                horizon=horizon,
                reproducibility_only=False,
            ),
        )
    except FormalCliResolveError:
        raise
    except M3RuntimeIdentityError:
        _fail(_CODE_RUNTIME, 2)
    except (ImportError, ModuleNotFoundError):
        _fail(_CODE_DEPENDENCY, 4)
    except (OSError, TypeError, ValueError, AttributeError, KeyError):
        _fail(_CODE_CLOSURE, 5)
    except Exception:
        _fail(_CODE_CLOSURE, 5)


def resolve_formal_reproducibility_cli_inputs(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
) -> FormalReproducibilityCliResolution:
    """Resolve only verified reusable inputs required by a fresh G8E worker."""
    try:
        return cast(
            FormalReproducibilityCliResolution,
            _resolve(
                project_root=project_root,
                config=config,
                config_relative=config_relative,
                snapshot_id=snapshot_id,
                fold=fold,
                horizon=horizon,
                reproducibility_only=True,
            ),
        )
    except FormalCliResolveError:
        raise
    except M3RuntimeIdentityError:
        _fail(_CODE_RUNTIME, 2)
    except (ImportError, ModuleNotFoundError):
        _fail(_CODE_DEPENDENCY, 4)
    except (OSError, TypeError, ValueError, AttributeError, KeyError):
        _fail(_CODE_CLOSURE, 5)
    except Exception:
        _fail(_CODE_CLOSURE, 5)


def resolve_formal_tracking_cli_inputs(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
) -> FormalTrackingCliResolution:
    """Resolve existing evaluation/backtest artifacts for one tracking wave."""
    try:
        backtest_resolution = resolve_formal_backtest_cli_inputs(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=snapshot_id,
            fold=fold,
            horizon=horizon,
        )
        return _resolve_tracking_from_backtest(backtest_resolution)
    except FormalCliResolveError:
        raise
    except M3RuntimeIdentityError:
        _fail(_CODE_RUNTIME, 2)
    except (ImportError, ModuleNotFoundError):
        _fail(_CODE_DEPENDENCY, 4)
    except (OSError, TypeError, ValueError, AttributeError, KeyError):
        _fail(_CODE_CLOSURE, 5)
    except Exception:
        _fail(_CODE_CLOSURE, 5)


def _resolve_tracking_from_backtest(
    resolved: FormalBacktestCliResolution,
) -> FormalTrackingCliResolution:
    if type(resolved) is not FormalBacktestCliResolution:
        raise ValueError
    facts_context = resolved.fresh_context.facts_fresh_context
    plan_context = facts_context.plan_fresh_context
    target_paths = plan_context.target_upstream_paths
    prediction_paths = target_paths.prediction_upstream_paths
    model_paths = prediction_paths.model_upstream_paths
    alignment_paths = model_paths.alignment_upstream_paths
    minimum = resolved.config.section("evaluation")["minimum_ic_symbols"]
    if type(minimum) is not int:
        raise ValueError

    evaluation_spec = EvaluationSpec(
        experiment_key=resolved.experiment.manifest.experiment_key,
        work_key=resolved.work_key,
        fold=resolved.target.manifest.fold,
        horizon_sessions=cast(Any, resolved.target.manifest.horizon_sessions),
        minimum_ic_symbols=minimum,
    )
    evaluation_paths = EvaluationUpstreamPaths(
        prediction_receipt_path=target_paths.prediction_receipt_path,
        prediction_upstream_paths=prediction_paths,
        label_receipt_path=alignment_paths.label_receipt_path,
        feature_receipt_path=target_paths.feature_receipt_path,
        fold_receipt_path=target_paths.fold_receipt_path,
    )
    evaluation_context = EvaluationFreshVerificationContext(
        release=resolved.release,
        snapshot=plan_context.snapshot,
        snapshot_spec=plan_context.snapshot_spec,
        provider=plan_context.provider,
        provider_spec=plan_context.provider_spec,
        experiment=resolved.experiment,
        experiment_spec=plan_context.experiment_spec,
        folds=facts_context.folds,
        fold_spec=plan_context.fold_spec,
        feature=plan_context.feature,
        feature_spec=plan_context.feature_spec,
        label=plan_context.label,
        label_spec=plan_context.label_spec,
        alignment=plan_context.alignment,
        alignment_spec=plan_context.alignment_spec,
        model=plan_context.model,
        model_spec=plan_context.model_spec,
        prediction=plan_context.prediction,
        prediction_spec=plan_context.prediction_spec,
        evaluation_spec=evaluation_spec,
        evaluation_upstream_paths=evaluation_paths,
    )
    evaluation_root = resolved.stage_root / "work" / resolved.work_key / "evaluation"
    evaluation_receipt = (
        resolved.stage_root / "receipts" / "evaluation" / f"{resolved.work_key}.json"
    )
    evaluation = verify_evaluation_artifact(
        root=evaluation_root,
        receipt_path=evaluation_receipt,
        release=evaluation_context.release,
        snapshot=evaluation_context.snapshot,
        snapshot_spec=evaluation_context.snapshot_spec,
        provider=evaluation_context.provider,
        provider_spec=evaluation_context.provider_spec,
        experiment=evaluation_context.experiment,
        experiment_spec=evaluation_context.experiment_spec,
        folds=evaluation_context.folds,
        fold_spec=evaluation_context.fold_spec,
        feature=evaluation_context.feature,
        feature_spec=evaluation_context.feature_spec,
        label=evaluation_context.label,
        label_spec=evaluation_context.label_spec,
        alignment=evaluation_context.alignment,
        alignment_spec=evaluation_context.alignment_spec,
        model=evaluation_context.model,
        model_spec=evaluation_context.model_spec,
        prediction=evaluation_context.prediction,
        prediction_spec=evaluation_context.prediction_spec,
        config=resolved.config,
        spec=evaluation_spec,
        upstream_paths=evaluation_paths,
        artifact_roots=resolved.artifact_roots,
    )
    backtest_receipt = (
        resolved.stage_root / "receipts" / "backtest" / f"{resolved.work_key}.json"
    )
    backtest = verify_backtest_artifact(
        root=resolved.stage_root / "work" / resolved.work_key / "backtest",
        receipt_path=backtest_receipt,
        target=resolved.target,
        plan=resolved.plan,
        release=resolved.release,
        experiment=resolved.experiment,
        config=resolved.config,
        fresh_context=resolved.fresh_context,
        artifact_roots=resolved.artifact_roots,
    )
    fresh_context = FormalTrackingFreshVerificationContext(
        evaluation_context=evaluation_context,
        evaluation_receipt_path=evaluation_receipt,
        target=resolved.target,
        plan=resolved.plan,
        release=resolved.release,
        experiment=resolved.experiment,
        backtest_context=resolved.fresh_context,
        backtest_receipt_path=backtest_receipt,
    )
    return FormalTrackingCliResolution(
        stage_root=resolved.stage_root,
        artifact_roots=resolved.artifact_roots,
        config=resolved.config,
        evaluation=evaluation,
        backtest=backtest,
        fresh_context=fresh_context,
        work_key=resolved.work_key,
    )


def _resolve(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    fold: str,
    horizon: int,
    reproducibility_only: bool,
) -> FormalBacktestCliResolution | FormalReproducibilityCliResolution:
    clear_reparse_chain_cache()
    root = _validate_project_root(project_root)
    loaded = _validate_config(config)
    relative = _validate_config_relative(config_relative)
    snap_id = _require_hex64(snapshot_id, _CODE_INPUT, 2)
    fold_name = _validate_fold(fold)
    horizon_sessions = _validate_horizon(horizon, loaded)

    _anchor_config_file(root, relative, loaded.raw_config_sha256)
    runtime = compute_m3_runtime_identity(
        project_root=root,
        config_paths=(relative,),
        frozen_config_digests=(
            M3SourceDigestV1(relative.as_posix(), cast(str, loaded.raw_config_sha256)),
        ),
    )

    stage_root = _resolve_stage_root(root, loaded)
    external_qlib = _require_real_dir(
        root / "data" / "external" / "qlib" / "v0.9.7",
        code=_CODE_MISSING,
        exit_code=5,
    )
    dump_tool_path = _require_real_file(
        external_qlib / "dump_bin.py",
        code=_CODE_MISSING,
        exit_code=5,
    )

    snapshot_root = stage_root / "snapshots" / snap_id
    bootstrap_manifest = _read_bootstrap_manifest(snapshot_root)
    if bootstrap_manifest.snapshot_id != snap_id:
        _fail(_CODE_CLOSURE, 5)
    if bootstrap_manifest.snapshot_config_sha256 != loaded.snapshot_config_sha256:
        _fail(_CODE_CLOSURE, 5)

    snapshot_request_key = compute_snapshot_request_key(
        g1_release_id=bootstrap_manifest.g1_release_id,
        g1_release_manifest_sha256=bootstrap_manifest.g1_release_manifest_sha256,
        snapshot_config_sha256=loaded.snapshot_config_sha256,
        code_version=runtime.code_version,
    )
    request_path = stage_root / "snapshot-requests" / f"{snapshot_request_key}.json"
    receipt_snapshot = stage_root / "receipts" / "snapshot" / f"{snapshot_request_key}.json"
    bootstrap_request = _read_bootstrap_request(request_path)
    if (
        bootstrap_request.snapshot_request_key != snapshot_request_key
        or bootstrap_request.snapshot_id != snap_id
        or bootstrap_request.g1_release_id != bootstrap_manifest.g1_release_id
        or bootstrap_request.g1_release_manifest_sha256
        != bootstrap_manifest.g1_release_manifest_sha256
        or bootstrap_request.snapshot_config_sha256 != loaded.snapshot_config_sha256
        or bootstrap_request.code_version != runtime.code_version
    ):
        _fail(_CODE_CLOSURE, 5)

    release_id = bootstrap_request.g1_release_id
    release_root = root / "data" / "clean" / "m3_g1" / "releases" / release_id
    release = verify_g1_release(
        release=G1Release(
            release_id=release_id,
            root=release_root,
            manifest_path=release_root / "manifest.json",
            quality_path=release_root / "quality.json",
        )
    )
    if (
        release.manifest.release_id != release_id
        or release.manifest_sha256 != bootstrap_request.g1_release_manifest_sha256
    ):
        _fail(_CODE_G1, 3)

    artifact_roots: Mapping[str, Path] = MappingProxyType(
        {
            "G1_RELEASE": release.release.root,
            "G8": stage_root,
            "EXTERNAL_QLIB": external_qlib,
        }
    )

    snapshot_spec = SnapshotBuildSpec(
        snapshot_request_key=snapshot_request_key,
        config_version=loaded.config_version,
        snapshot_config_sha256=loaded.snapshot_config_sha256,
        code_version=runtime.code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    snapshot = verify_snapshot_artifact(
        snapshot_root=snapshot_root,
        snapshot_request_path=request_path,
        snapshot_receipt_path=receipt_snapshot,
        release=release,
        config=loaded,
        spec=snapshot_spec,
        artifact_roots=artifact_roots,
    )
    if (
        snapshot.manifest.snapshot_id != snap_id
        or snapshot.request.snapshot_request_key != snapshot_request_key
        or snapshot.request.code_version != runtime.code_version
    ):
        _fail(_CODE_CLOSURE, 5)

    runtime_fp = build_provider_runtime_fingerprint()
    dump_tool = build_qlib_dump_tool_spec(loaded)
    provider_key = compute_provider_key(
        snapshot_id=snap_id,
        provider_config_hash=loaded.provider_config_sha256,
        dump_tool_sha256=dump_tool.sha256,
        qlib_version=dump_tool.qlib_version,
        provider_runtime_fingerprint_sha256=runtime_fp.sha256,
        code_version=runtime.code_version,
    )
    provider_root = stage_root / "providers" / provider_key
    provider_receipt = stage_root / "receipts" / "provider" / f"{provider_key}.json"
    provider = verify_provider_artifact(
        provider_root=provider_root,
        provider_receipt_path=provider_receipt,
        snapshot=snapshot,
        config=loaded,
        artifact_roots=artifact_roots,
    )
    provider_spec = ProviderBuildSpec(
        snapshot_id=provider.manifest.snapshot_id,
        snapshot_manifest_sha256=provider.manifest.snapshot_manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_config_sha256=loaded.provider_config_sha256,
        dump_tool=dump_tool,
        qlib_version="0.9.7",
        code_version=provider.manifest.code_version,
        runtime_fingerprint=runtime_fp,
        fields=_PROVIDER_FIELDS,
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )

    validation_key = compute_provider_validation_key(
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=loaded.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=runtime_fp.sha256,
        code_version=runtime.code_version,
    )
    validation_root = stage_root / "provider-validations" / validation_key
    validation_receipt = stage_root / "receipts" / "provider-validation" / f"{validation_key}.json"
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=loaded.provider_validation_config_sha256,
        code_version=runtime.code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    verify_provider_validation_artifact(
        validation_root=validation_root,
        validation_receipt_path=validation_receipt,
        snapshot=snapshot,
        provider=provider,
        config=loaded,
        spec=validation_spec,
        artifact_roots=artifact_roots,
    )

    experiment_spec = ExperimentIdentitySpec(
        scientific_config_sha256=loaded.scientific_config_sha256,
        dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
        code_version=runtime.code_version,
    )
    experiment_key = compute_experiment_key(
        snapshot_id=snap_id,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_hash=loaded.scientific_config_sha256,
        code_version=runtime.code_version,
        dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
    )
    experiment_root = stage_root / "runs" / experiment_key
    experiment_receipt = stage_root / "receipts" / "experiment-identity" / f"{experiment_key}.json"
    experiment = verify_experiment_identity(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt,
        snapshot=snapshot,
        provider=provider,
        config=loaded,
        spec=experiment_spec,
        artifact_roots=artifact_roots,
    )
    if experiment.manifest.experiment_key != experiment_key:
        _fail(_CODE_CLOSURE, 5)

    label_spec = LabelBuildSpec(
        experiment_key=experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        horizon_sessions=cast(Any, horizon_sessions),
        benchmark=cast(Any, loaded.section("data")["benchmark"]),
        label_version=cast(str, loaded.section("labels")["label_version"]),
        label_build_code_version=runtime.code_version,
    )
    label_root = stage_root / "labels" / experiment_key / f"h{horizon_sessions}"
    label_receipt = (
        stage_root / "receipts" / "labels" / f"{experiment_key}-h{horizon_sessions}.json"
    )
    label = verify_label_artifact(
        label_root=label_root,
        label_receipt_path=label_receipt,
        release=release,
        snapshot=snapshot,
        experiment=experiment,
        config=loaded,
        experiment_spec=experiment_spec,
        spec=label_spec,
        artifact_roots=artifact_roots,
    )

    walk = loaded.section("walk_forward")
    fold_spec = FoldPlanBuildSpec(
        experiment_key=experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        snapshot_id=snap_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        signal_start=snapshot.request.signal_start,
        signal_end=snapshot.request.signal_end,
        train_sessions=cast(int, walk["train_sessions"]),
        validation_sessions=cast(int, walk["validation_sessions"]),
        test_sessions=cast(int, walk["test_sessions"]),
        step_sessions=cast(int, walk["step_sessions"]),
        embargo_sessions=cast(int, walk["embargo_sessions"]),
        max_horizon_sessions=max(
            cast(tuple[int, ...], loaded.section("labels")["horizons_sessions"])
        ),
    )
    fold_upstream = FoldPlanUpstreamPaths(
        snapshot_request_path=request_path,
        snapshot_receipt_path=receipt_snapshot,
        provider_dump_tool_path=dump_tool_path,
        provider_receipt_path=provider_receipt,
        experiment_receipt_path=experiment_receipt,
    )
    folds_root = stage_root / "folds" / experiment_key
    folds_receipt = stage_root / "receipts" / "folds" / f"{experiment_key}.json"
    folds = verify_fold_plan_artifact(
        root=folds_root,
        receipt_path=folds_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        config=loaded,
        spec=fold_spec,
        upstream_paths=fold_upstream,
        artifact_roots=artifact_roots,
    )
    planned = next((item for item in folds.manifest.folds if item.name == fold_name), None)
    if planned is None:
        _fail(_CODE_INPUT, 2)

    feature_spec = FeatureBuildSpec(
        experiment_key=experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        fold=fold_name,
        planned_fold_sha256=planned.planned_fold_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        feature_version=cast(str, loaded.section("features")["feature_version"]),
        expected_qlib_version="0.9.7",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    feature_upstream = FeatureUpstreamPaths(
        fold_receipt_path=folds_receipt,
        fold_upstream_paths=fold_upstream,
    )
    feature_root = stage_root / "features" / experiment_key / fold_name
    feature_receipt = stage_root / "receipts" / "features" / f"{experiment_key}.{fold_name}.json"
    feature = verify_feature_artifact(
        root=feature_root,
        receipt_path=feature_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        config=loaded,
        spec=feature_spec,
        upstream_paths=feature_upstream,
        artifact_roots=artifact_roots,
    )

    work_key = compute_work_key(
        experiment_key=experiment_key,
        fold=fold_name,
        horizon=horizon_sessions,
    )
    alignment_spec = AlignmentBuildSpec(
        experiment_key=experiment_key,
        work_key=work_key,
        fold=fold_name,
        planned_fold_sha256=planned.planned_fold_sha256,
        horizon_sessions=cast(Any, horizon_sessions),
        feature_manifest_sha256=feature.manifest_sha256,
        label_manifest_sha256=label.manifest_sha256,
    )
    alignment_upstream = AlignmentUpstreamPaths(
        feature_receipt_path=feature_receipt,
        feature_upstream_paths=feature_upstream,
        label_receipt_path=label_receipt,
    )
    alignment_root = stage_root / "work" / work_key / "alignment"
    alignment_receipt = stage_root / "receipts" / "alignment" / f"{work_key}.json"
    alignment = verify_alignment_artifact(
        root=alignment_root,
        receipt_path=alignment_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        config=loaded,
        spec=alignment_spec,
        upstream_paths=alignment_upstream,
        artifact_roots=artifact_roots,
    )

    if reproducibility_only:
        return FormalReproducibilityCliResolution(
            stage_root=stage_root,
            artifact_roots=artifact_roots,
            config=loaded,
            runtime=runtime,
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=experiment_spec,
            folds=folds,
            fold_spec=fold_spec,
            fold_upstream_paths=fold_upstream,
            fold_receipt_path=folds_receipt,
            feature=feature,
            feature_spec=feature_spec,
            feature_upstream_paths=feature_upstream,
            feature_receipt_path=feature_receipt,
            label=label,
            label_spec=label_spec,
            label_receipt_path=label_receipt,
            alignment=alignment,
            alignment_spec=alignment_spec,
            alignment_upstream_paths=alignment_upstream,
            alignment_receipt_path=alignment_receipt,
            work_key=work_key,
        )

    model_spec = build_lightgbm_training_spec(loaded)
    model_upstream = ModelUpstreamPaths(
        alignment_receipt_path=alignment_receipt,
        alignment_upstream_paths=alignment_upstream,
    )
    model_root = stage_root / "work" / work_key / "train"
    model_receipt = stage_root / "receipts" / "train" / f"{work_key}.json"
    model = verify_model_artifact(
        root=model_root,
        receipt_path=model_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        alignment=alignment,
        alignment_spec=alignment_spec,
        config=loaded,
        spec=model_spec,
        upstream_paths=model_upstream,
        artifact_roots=artifact_roots,
    )

    prediction_spec = PredictionBuildSpec(
        experiment_key=experiment_key,
        work_key=work_key,
        fold=fold_name,
        horizon_sessions=cast(Any, horizon_sessions),
        model="lightgbm",
        model_version=model.manifest.model_version,
    )
    prediction_upstream = PredictionUpstreamPaths(
        model_receipt_path=model_receipt,
        model_upstream_paths=model_upstream,
        feature_receipt_path=feature_receipt,
        feature_upstream_paths=feature_upstream,
        fold_receipt_path=folds_receipt,
    )
    prediction_root = stage_root / "work" / work_key / "predictions"
    prediction_receipt = stage_root / "receipts" / "predictions" / f"{work_key}.json"
    prediction = verify_prediction_artifact(
        root=prediction_root,
        receipt_path=prediction_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        alignment=alignment,
        alignment_spec=alignment_spec,
        model=model,
        model_spec=model_spec,
        config=loaded,
        spec=prediction_spec,
        upstream_paths=prediction_upstream,
        artifact_roots=artifact_roots,
    )

    portfolio = loaded.section("portfolio")
    features_cfg = loaded.section("features")
    target_spec = TargetBuildSpec(
        experiment_key=experiment_key,
        work_key=work_key,
        fold=fold_name,
        horizon_sessions=cast(Any, horizon_sessions),
        strategy=cast(Any, portfolio["strategy"]),
        strategy_version=cast(str, portfolio["strategy_version"]),
        top_k=cast(int, portfolio["top_k"]),
        cash_buffer=cast(float, portfolio["cash_buffer"]),
        max_weight=cast(float, portfolio["max_weight"]),
        minimum_scorable_coverage=cast(float, features_cfg["minimum_scorable_coverage"]),
    )
    target_upstream = TargetUpstreamPaths(
        feature_receipt_path=feature_receipt,
        prediction_receipt_path=prediction_receipt,
        prediction_upstream_paths=prediction_upstream,
        fold_receipt_path=folds_receipt,
        experiment_receipt_path=experiment_receipt,
    )
    target_root = stage_root / "work" / work_key / "targets"
    target_receipt = stage_root / "receipts" / "targets" / f"{work_key}.json"
    target = verify_target_artifact(
        root=target_root,
        receipt_path=target_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        alignment=alignment,
        alignment_spec=alignment_spec,
        model=model,
        model_spec=model_spec,
        prediction=prediction,
        prediction_spec=prediction_spec,
        config=loaded,
        spec=target_spec,
        upstream_paths=target_upstream,
        artifact_roots=artifact_roots,
    )
    if target.manifest.work_key != work_key:
        _fail(_CODE_CLOSURE, 5)

    plan_fresh = BacktestPlanFreshVerificationContext(
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment_spec=experiment_spec,
        fold_spec=fold_spec,
        feature=feature,
        feature_spec=feature_spec,
        label=label,
        label_spec=label_spec,
        alignment=alignment,
        alignment_spec=alignment_spec,
        model=model,
        model_spec=model_spec,
        prediction=prediction,
        prediction_spec=prediction_spec,
        target_spec=target_spec,
        target_upstream_paths=target_upstream,
        target_receipt_path=target_receipt,
    )
    plan_root = stage_root / "work" / work_key / "backtest_plan"
    plan_receipt = stage_root / "receipts" / "backtest_plan" / f"{work_key}.json"
    plan = verify_backtest_plan_artifact(
        root=plan_root,
        receipt_path=plan_receipt,
        target=target,
        release=release,
        folds=folds,
        experiment=experiment,
        config=loaded,
        fresh_context=plan_fresh,
        artifact_roots=artifact_roots,
    )
    if plan.manifest.work_key != work_key:
        _fail(_CODE_CLOSURE, 5)

    facts_fresh = AShareMarketFactsFreshVerificationContext(
        target=target,
        folds=folds,
        experiment=experiment,
        config=loaded,
        plan_fresh_context=plan_fresh,
        plan_receipt_path=plan_receipt,
    )
    upstream_paths = FormalBacktestArtifactUpstreamPaths(
        target_receipt_path=target_receipt,
        plan_receipt_path=plan_receipt,
        experiment_receipt_path=experiment_receipt,
    )
    fresh_context = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=facts_fresh,
        upstream_paths=upstream_paths,
        release=release,
    )
    return FormalBacktestCliResolution(
        stage_root=stage_root,
        artifact_roots=artifact_roots,
        config=loaded,
        release=release,
        experiment=experiment,
        target=target,
        plan=plan,
        fresh_context=fresh_context,
        work_key=work_key,
    )


def _fail(code: str, exit_code: int, message: str | None = None) -> NoReturn:
    try:
        raise FormalCliResolveError(code, exit_code, message)
    except FormalCliResolveError as error:
        error.__cause__ = None
        error.__context__ = None
        raise


def _validate_project_root(project_root: Path) -> Path:
    if not isinstance(project_root, Path):
        _fail(_CODE_INPUT, 2)
    try:
        root = project_root.resolve(strict=True)
    except OSError:
        _fail(_CODE_INPUT, 2)
    _require_real_dir(root, code=_CODE_INPUT, exit_code=2)
    for required in (root / "src" / "quant", root / "configs", root / "pyproject.toml"):
        try:
            st = os.lstat(required)
        except OSError:
            _fail(_CODE_INPUT, 2)
        if _is_link_or_reparse(st):
            _fail(_CODE_INPUT, 2)
    return root


def _validate_config(config: LoadedM3Config) -> LoadedM3Config:
    if type(config) is not LoadedM3Config:
        _fail(_CODE_CONFIG, 2)
    raw = config.raw_config_sha256
    if type(raw) is not str or not _HEX64.fullmatch(raw):
        _fail(_CODE_CONFIG, 2)
    return config


def _validate_config_relative(value: PurePosixPath) -> PurePosixPath:
    if type(value) is not PurePosixPath:
        _fail(_CODE_INPUT, 2)
    text = value.as_posix()
    if not text or text.startswith("/") or "\\" in text or value.is_absolute() or value.drive:
        _fail(_CODE_INPUT, 2)
    parts = value.parts
    if (
        not parts
        or parts[0] != "configs"
        or any(part in {"", ".", ".."} for part in parts)
        or len(set(parts)) != len(parts)
    ):
        _fail(_CODE_INPUT, 2)
    return value


def _validate_fold(fold: str) -> str:
    if type(fold) is not str or _FOLD.fullmatch(fold) is None:
        _fail(_CODE_INPUT, 2)
    return fold


def _validate_horizon(horizon: int, config: LoadedM3Config) -> int:
    if type(horizon) is bool or type(horizon) is not int or horizon not in {5, 10}:
        _fail(_CODE_INPUT, 2)
    horizons = config.section("labels")["horizons_sessions"]
    if type(horizons) is not tuple or horizon not in horizons:
        _fail(_CODE_INPUT, 2)
    return horizon


def _require_hex64(value: str, code: str, exit_code: int) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        _fail(code, exit_code)
    return value


def _anchor_config_file(
    project_root: Path, config_relative: PurePosixPath, expected_sha256: str | None
) -> None:
    """Bind config to the raw project-relative path before any resolve/read.

    Walks each ``config_relative`` component with ``lstat`` under the already
    anchored project root. Intermediate components must be real directories;
    the leaf must be a real regular file with ``st_nlink == 1``. Symlink,
    junction, and reparse points are rejected on the original path before
    ``Path.resolve``. A later resolve only re-confirms containment; it does
    not replace the raw-path checks. Bytes are bound to open-before/after
    entity identity and ``raw_config_sha256``.
    """
    if type(expected_sha256) is not str or not _HEX64.fullmatch(expected_sha256):
        _fail(_CODE_CONFIG, 2)
    parts = config_relative.parts
    if not parts:
        _fail(_CODE_CONFIG, 2)
    current = project_root
    leaf_stat: os.stat_result | None = None
    for index, part in enumerate(parts):
        current = current / part
        try:
            st = os.lstat(current)
        except OSError:
            _fail(_CODE_CONFIG, 2)
        if _is_link_or_reparse(st):
            _fail(_CODE_CONFIG, 2)
        is_leaf = index == len(parts) - 1
        if is_leaf:
            if not stat.S_ISREG(st.st_mode) or getattr(st, "st_nlink", 1) != 1:
                _fail(_CODE_CONFIG, 2)
            leaf_stat = st
        elif not stat.S_ISDIR(st.st_mode):
            _fail(_CODE_CONFIG, 2)
    if leaf_stat is None:
        _fail(_CODE_CONFIG, 2)
    leaf = current
    try:
        resolved = leaf.resolve(strict=True)
    except OSError:
        _fail(_CODE_CONFIG, 2)
    abs_leaf = Path(os.path.abspath(leaf))
    if os.path.normcase(str(abs_leaf)) != os.path.normcase(str(resolved)):
        _fail(_CODE_CONFIG, 2)
    if not resolved.is_relative_to(project_root):
        _fail(_CODE_CONFIG, 2)
    try:
        post = os.lstat(leaf)
    except OSError:
        _fail(_CODE_CONFIG, 2)
    if (
        _is_link_or_reparse(post)
        or not stat.S_ISREG(post.st_mode)
        or getattr(post, "st_nlink", 1) != 1
        or (post.st_dev, post.st_ino) != (leaf_stat.st_dev, leaf_stat.st_ino)
    ):
        _fail(_CODE_CONFIG, 2)
    digest = _hash_stable_regular_file(leaf, expected=leaf_stat)
    if digest != expected_sha256:
        _fail(_CODE_CONFIG, 2)


def _resolve_stage_root(project_root: Path, config: LoadedM3Config) -> Path:
    logical = config.section("tracking")["artifact_root"]
    if type(logical) is not str or not logical:
        _fail(_CODE_CONFIG, 2)
    try:
        relative = PurePosixPath(logical)
    except Exception:
        _fail(_CODE_CONFIG, 2)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in logical
    ):
        _fail(_CODE_CONFIG, 2)
    candidate = project_root.joinpath(*relative.parts)
    return _require_real_dir(candidate, code=_CODE_MISSING, exit_code=5)


def _read_bootstrap_manifest(snapshot_root: Path) -> Any:
    manifest_path = snapshot_root / "manifest.json"
    _require_real_file(manifest_path, code=_CODE_MISSING, exit_code=5)
    try:
        return read_snapshot_manifest(manifest_path)
    except Exception:
        _fail(_CODE_UPSTREAM, 3)


def _read_bootstrap_request(request_path: Path) -> Any:
    _require_real_file(request_path, code=_CODE_MISSING, exit_code=5)
    try:
        return read_snapshot_request_record(request_path)
    except Exception:
        _fail(_CODE_UPSTREAM, 3)


def _missing_detail(kind: str, path: Path) -> str | None:
    """Optional path detail for local diagnosis; redacted unless explicitly enabled."""
    if os.environ.get("QUANT_FORMAL_CLI_RESOLVE_DETAIL") != "1":
        return None
    return f"{kind}:{path}"


def _require_real_dir(path: Path, *, code: str, exit_code: int) -> Path:
    try:
        resolved = path.resolve(strict=True)
        st = os.lstat(resolved)
    except OSError:
        _fail(code, exit_code, _missing_detail("missing_dir", path))
    if not stat.S_ISDIR(st.st_mode) or _is_link_or_reparse(st):
        _fail(code, exit_code, _missing_detail("bad_dir", path))
    _reject_symlink_ancestors(resolved, code=code, exit_code=exit_code)
    return resolved


def _require_real_file(path: Path, *, code: str, exit_code: int) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _fail(code, exit_code, _missing_detail("missing_file", path))
    _require_regular_file_stat(resolved, code=code, exit_code=exit_code)
    return resolved


def _require_regular_file_stat(path: Path, *, code: str, exit_code: int) -> os.stat_result:
    try:
        st = os.lstat(path)
    except OSError:
        _fail(code, exit_code, _missing_detail("missing_stat", path))
    if not stat.S_ISREG(st.st_mode) or _is_link_or_reparse(st):
        _fail(code, exit_code, _missing_detail("bad_file", path))
    _reject_symlink_ancestors(path, code=code, exit_code=exit_code)
    return st


def _reject_symlink_ancestors(path: Path, *, code: str, exit_code: int) -> None:
    current = path
    while True:
        parent = current.parent
        if parent == current:
            return
        try:
            st = os.lstat(parent)
        except OSError:
            _fail(code, exit_code, _missing_detail("missing_ancestor", parent))
        if _is_link_or_reparse(st):
            _fail(code, exit_code, _missing_detail("reparse_ancestor", parent))
        current = parent


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return bool(stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & _REPARSE))


def _hash_stable_regular_file(path: Path, *, expected: os.stat_result) -> str:
    """Read leaf bytes bound to open-before/after entity identity."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _fail(_CODE_CONFIG, 2)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or getattr(before, "st_nlink", 1) != 1
            or (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino)
        ):
            _fail(_CODE_CONFIG, 2)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or _is_link_or_reparse(after)
            or getattr(after, "st_nlink", 1) != 1
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or size != before.st_size
        ):
            _fail(_CODE_CONFIG, 2)
        try:
            rebound = os.lstat(path)
        except OSError:
            _fail(_CODE_CONFIG, 2)
        if (
            _is_link_or_reparse(rebound)
            or not stat.S_ISREG(rebound.st_mode)
            or getattr(rebound, "st_nlink", 1) != 1
            or (rebound.st_dev, rebound.st_ino) != (before.st_dev, before.st_ino)
        ):
            _fail(_CODE_CONFIG, 2)
        return digest.hexdigest()
    finally:
        os.close(descriptor)
