"""Formal identity-resolved G8 backtest StageRunner wave."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from quant.backtest.a_share_reporting import (
    BacktestArtifactFreshVerificationContext,
    backtest_artifact_input_paths,
    backtest_artifact_output_relative_paths,
    build_backtest_artifact,
    read_backtest_bundle_manifest,
    read_backtest_metrics,
    verify_backtest_artifact,
    verify_backtest_build_output,
)
from quant.data.m3_release import G1ManifestV5, VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    BacktestBundleManifestV1,
    BacktestMetricsV1,
    VerifiedBacktestArtifact,
    VerifiedBacktestPlanArtifact,
    VerifiedExperimentIdentity,
    VerifiedTargetArtifact,
)
from quant.research.m3.orchestration import (
    BACKTEST_STAGE_SPEC,
    ExternalInput,
    M3StageRunnerError,
    ResolvedInput,
    RunPlan,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    StageReceipt,
    compute_work_key,
    select_artifact_root,
    verify_stage_receipt_with_bytes,
)

_ERROR = "M3_FORMAL_BACKTEST_STAGE_INVALID"
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class _BuiltOutputProof:
    manifest: BacktestBundleManifestV1
    metrics: BacktestMetricsV1
    files: tuple[tuple[str, bytes], ...]


_ORIGINAL_BUILD_BACKTEST_ARTIFACT = build_backtest_artifact


class _EntityGuardedFormalBacktestStageRunner(StageRunner):
    """G8 wrapper: revalidate G7F R4 release/entity before receipt publish."""

    def __init__(
        self,
        *,
        stage_root: Path,
        artifact_roots: Mapping[str, Path],
        config: LoadedM3Config,
        target: VerifiedTargetArtifact,
        plan: VerifiedBacktestPlanArtifact,
        release: VerifiedG1Release,
        experiment: VerifiedExperimentIdentity,
        fresh_context: BacktestArtifactFreshVerificationContext,
    ) -> None:
        super().__init__(
            stage_root=stage_root,
            artifact_roots=artifact_roots,
            config=config,
        )
        self._g8_target = target
        self._g8_plan = plan
        self._g8_release = release
        self._g8_experiment = experiment
        self._g8_fresh_context = fresh_context

    def _publish_static_receipt(
        self,
        *,
        node: StageNode,
        receipt_path: Path,
        resolved: tuple[ResolvedInput, ...],
        outputs: tuple[Path, ...],
    ) -> StageReceipt:
        try:
            paths = backtest_artifact_input_paths(
                target=self._g8_target,
                plan=self._g8_plan,
                release=self._g8_release,
                experiment=self._g8_experiment,
                fresh_context=self._g8_fresh_context,
            )
            if len(paths) != 21 or len(set(paths)) != 21:
                raise ValueError
            if any(path.name == "receipt.json" for path in paths):
                raise ValueError
            current = tuple(
                sorted(
                    (
                        _digest_input(path, artifact_roots=self._artifact_roots)[0]
                        for path in paths
                    ),
                    key=lambda item: (item.root_alias, item.relative_path),
                )
            )
            expected = tuple(
                sorted(
                    (item.digest for item in resolved),
                    key=lambda item: (item.root_alias, item.relative_path),
                )
            )
            if current != expected:
                raise ValueError
        except M3StageRunnerError:
            raise
        except Exception:
            raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
        return super()._publish_static_receipt(
            node=node,
            receipt_path=receipt_path,
            resolved=resolved,
            outputs=outputs,
        )


@dataclass(frozen=True)
class FormalBacktestStageResult:
    """Exact result of one formal backtest runner wave and final verifier."""

    final_root: Path
    receipt_path: Path
    verified: VerifiedBacktestArtifact
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.final_root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.verified) is not VerifiedBacktestArtifact
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise ValueError(_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_ERROR)


def make_formal_backtest_run_plan(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> RunPlan:
    """Resolve the exact 21-file formal backtest WORK wave without writes."""
    try:
        return _make_formal_backtest_run_plan(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
        )
    except Exception:
        pass
    raise M3StageRunnerError("STAGE_INPUT_INVALID") from None


def _make_formal_backtest_run_plan(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> RunPlan:
    if (
        type(target) is not VerifiedTargetArtifact
        or type(plan) is not VerifiedBacktestPlanArtifact
        or type(release) is not VerifiedG1Release
        or type(release.manifest) is not G1ManifestV5
        or type(experiment) is not VerifiedExperimentIdentity
        or type(config) is not LoadedM3Config
        or type(fresh_context) is not BacktestArtifactFreshVerificationContext
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not isinstance(root, Path)
            for alias, root in artifact_roots.items()
        )
    ):
        raise ValueError
    _validate_non_nested_roots(artifact_roots)
    target_manifest = target.manifest
    plan_manifest = plan.manifest
    fold = target_manifest.fold
    horizon = target_manifest.horizon_sessions
    work_key = target_manifest.work_key
    if (
        plan_manifest.work_key != work_key
        or plan_manifest.fold != fold
        or plan_manifest.horizon_sessions != horizon
        or plan_manifest.experiment_key != experiment.manifest.experiment_key
        or target_manifest.experiment_key != experiment.manifest.experiment_key
        or plan_manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or target_manifest.experiment_manifest_sha256 != experiment.manifest_sha256
        or plan_manifest.g1_release_id != release.manifest.release_id
        or target_manifest.g1_release_id != release.manifest.release_id
        or plan_manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or target_manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or plan_manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or target_manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or fresh_context.facts_fresh_context.config != config
        or work_key
        != compute_work_key(
            experiment_key=experiment.manifest.experiment_key,
            fold=fold,
            horizon=horizon,
        )
    ):
        raise ValueError
    input_paths = backtest_artifact_input_paths(
        target=target,
        plan=plan,
        release=release,
        experiment=experiment,
        fresh_context=fresh_context,
    )
    digests_with_identity = tuple(
        _digest_input(path, artifact_roots=artifact_roots)
        for path in input_paths
    )
    identities = {identity for _, identity in digests_with_identity}
    digests = tuple(
        sorted(
            (digest for digest, _ in digests_with_identity),
            key=lambda item: (item.root_alias, item.relative_path),
        )
    )
    if len(digests) != 21 or len(identities) != 21:
        raise ValueError
    node = StageNode(
        node_id=f"backtest.{fold}.h{horizon}",
        spec_name=BACKTEST_STAGE_SPEC.name,
        scope="WORK",
        scope_key=work_key,
        fold=fold,
        horizon=horizon,
        dependencies=(),
        inputs=tuple(ExternalInput(item) for item in digests),
        publication=StaticDirectoryPublication(f"work/{work_key}/backtest"),
        output_specs=BACKTEST_STAGE_SPEC.outputs,
        receipt_path=f"receipts/backtest/{work_key}.json",
    )
    return RunPlan(continuation="WORK", nodes=(node,))


def run_formal_backtest_stage(
    *,
    stage_root: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    resume: bool = True,
) -> FormalBacktestStageResult:
    """Build, publish, receipt, and finally verify one formal backtest wave."""
    run_plan = make_formal_backtest_run_plan(
        target=target,
        plan=plan,
        release=release,
        experiment=experiment,
        config=config,
        fresh_context=fresh_context,
        artifact_roots=artifact_roots,
    )
    node = run_plan.nodes[0]
    runner_error: str | None = None
    try:
        runner = _EntityGuardedFormalBacktestStageRunner(
            stage_root=stage_root,
            artifact_roots=artifact_roots,
            config=config,
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            fresh_context=fresh_context,
        )
    except M3StageRunnerError as caught:
        runner_error = caught.code
    except Exception:
        runner_error = "STAGE_INPUT_INVALID"
    if runner_error is not None:
        raise M3StageRunnerError(runner_error) from None

    def handler(context: StageContext) -> StageBuildReport:
        _validate_stage_context(
            context=context,
            node=node,
            config=config,
            artifact_roots=artifact_roots,
        )
        manifest = build_backtest_artifact(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
            output_root=context.temp_output_root,
        )
        if (
            build_backtest_artifact is _ORIGINAL_BUILD_BACKTEST_ARTIFACT
            and type(manifest) is BacktestBundleManifestV1
        ):
            proof_holder[:] = [
                _capture_built_output_proof(context.temp_output_root, manifest)
            ]
        return StageBuildReport(backtest_artifact_output_relative_paths())

    proof_holder: list[_BuiltOutputProof] = []

    def closure(root: Path) -> None:
        if proof_holder:
            _verify_built_output_proof(root, proof_holder[0])
            paths = backtest_artifact_input_paths(
                target=target,
                plan=plan,
                release=release,
                experiment=experiment,
                fresh_context=fresh_context,
            )
            if len(paths) != 21 or len(set(paths)) != 21:
                raise ValueError
            return
        verify_backtest_build_output(
            root=root,
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
        )

    runner_error = None
    static = None
    try:
        static = runner.run_static(
            node=node,
            handler=handler,
            closure_verifier=closure,
            resume=resume,
            plan=run_plan,
        )
    except M3StageRunnerError as caught:
        runner_error = caught.code
    except Exception:
        runner_error = "STAGE_RECOVERY_CONFLICT"
    if runner_error is not None or static is None:
        raise M3StageRunnerError(
            runner_error or "STAGE_RECOVERY_CONFLICT"
        ) from None
    invalid = False
    verified: VerifiedBacktestArtifact | None = None
    try:
        if proof_holder:
            candidate = _verify_published_output_from_proof(
                root=static.final_root,
                receipt_path=static.receipt_path,
                receipt=static.receipt,
                proof=proof_holder[0],
                target=target,
                plan=plan,
                release=release,
                experiment=experiment,
                fresh_context=fresh_context,
                artifact_roots=artifact_roots,
            )
        else:
            candidate = verify_backtest_artifact(
                root=static.final_root,
                receipt_path=static.receipt_path,
                target=target,
                plan=plan,
                release=release,
                experiment=experiment,
                config=config,
                fresh_context=fresh_context,
                artifact_roots=artifact_roots,
            )
        if (
            type(candidate) is not VerifiedBacktestArtifact
            or candidate.root != static.final_root.resolve(strict=True)
            or candidate.manifest.work_key != node.scope_key
            or static.receipt.stage != "backtest"
            or static.receipt.scope != "WORK"
            or static.receipt.scope_key != node.scope_key
        ):
            raise ValueError
        verified = candidate
    except Exception:
        invalid = True
    if invalid or verified is None:
        raise M3StageRunnerError("STAGE_RECOVERY_CONFLICT") from None
    return FormalBacktestStageResult(
        final_root=static.final_root,
        receipt_path=static.receipt_path,
        verified=verified,
        receipt=static.receipt,
        reused=static.reused,
    )


def _capture_built_output_proof(
    root: Path,
    manifest: BacktestBundleManifestV1,
) -> _BuiltOutputProof:
    if type(manifest) is not BacktestBundleManifestV1:
        raise ValueError
    expected = backtest_artifact_output_relative_paths()
    before = _stable_output_entities(root, expected)
    files = tuple((name, (root / Path(name)).read_bytes()) for name in expected)
    if _stable_output_entities(root, expected) != before:
        raise ValueError
    parsed_manifest = read_backtest_bundle_manifest(root / "backtest_manifest.json")
    metrics = read_backtest_metrics(root / "backtest_metrics.json")
    if parsed_manifest != manifest:
        raise ValueError
    return _BuiltOutputProof(
        manifest=manifest,
        metrics=metrics,
        files=files,
    )


def _verify_built_output_proof(root: Path, proof: _BuiltOutputProof) -> None:
    if type(proof) is not _BuiltOutputProof:
        raise ValueError
    expected = tuple(name for name, _ in proof.files)
    if expected != backtest_artifact_output_relative_paths():
        raise ValueError
    before = _stable_output_entities(root, expected)
    actual = tuple((name, (root / Path(name)).read_bytes()) for name in expected)
    if actual != proof.files or _stable_output_entities(root, expected) != before:
        raise ValueError


def _verify_published_output_from_proof(
    *,
    root: Path,
    receipt_path: Path,
    receipt: StageReceipt,
    proof: _BuiltOutputProof,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestArtifact:
    _verify_built_output_proof(root, proof)
    absolute_root = Path(os.path.abspath(root)).resolve(strict=True)
    verified_receipt = verify_stage_receipt_with_bytes(
        receipt_path=receipt_path,
        artifact_roots=artifact_roots,
    )
    if verified_receipt is None or verified_receipt.receipt != receipt:
        raise ValueError
    current_inputs = _digests_for_paths(
        backtest_artifact_input_paths(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            fresh_context=fresh_context,
        ),
        artifact_roots=artifact_roots,
    )
    current_outputs = _digests_for_paths(
        tuple(
            absolute_root / Path(name)
            for name in backtest_artifact_output_relative_paths()
        ),
        artifact_roots=artifact_roots,
    )
    manifest_raw = dict(proof.files)["backtest_manifest.json"]
    metrics_raw = dict(proof.files)["backtest_metrics.json"]
    manifest = read_backtest_bundle_manifest(
        absolute_root / "backtest_manifest.json"
    )
    metrics = read_backtest_metrics(absolute_root / "backtest_metrics.json")
    if (
        receipt.stage != "backtest"
        or receipt.scope != "WORK"
        or receipt.scope_key != target.manifest.work_key
        or receipt.inputs != current_inputs
        or receipt.outputs != current_outputs
        or manifest != proof.manifest
        or metrics != proof.metrics
        or manifest.work_key != target.manifest.work_key
        or manifest.experiment_key != experiment.manifest.experiment_key
        or manifest.target_manifest_sha256 != target.manifest_sha256
        or manifest.backtest_plan_manifest_sha256 != plan.manifest_sha256
        or manifest.g1_release_id != release.manifest.release_id
        or manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or manifest.backtest_metrics_sha256
        != hashlib.sha256(metrics_raw).hexdigest()
        or metrics.work_key != manifest.work_key
        or metrics.experiment_key != manifest.experiment_key
    ):
        raise ValueError
    _verify_built_output_proof(root, proof)
    return VerifiedBacktestArtifact(
        root=absolute_root,
        metrics=metrics,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        backtest_receipt_sha256=verified_receipt.sha256,
    )


def _digests_for_paths(
    paths: tuple[Path, ...],
    *,
    artifact_roots: Mapping[str, Path],
) -> tuple[ArtifactDigest, ...]:
    return tuple(
        sorted(
            (
                _digest_input(path, artifact_roots=artifact_roots)[0]
                for path in paths
            ),
            key=lambda item: (item.root_alias, item.relative_path),
        )
    )


def _stable_output_entities(
    root: Path, expected: tuple[str, ...]
) -> tuple[tuple[str, int, int, int, int], ...]:
    absolute = Path(os.path.abspath(root))
    root_info = os.lstat(absolute)
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE
    ):
        raise ValueError
    actual_files = tuple(sorted(
        path.relative_to(absolute).as_posix()
        for path in absolute.rglob("*")
        if path.is_file()
    ))
    actual_dirs = tuple(sorted(
        path.relative_to(absolute).as_posix()
        for path in absolute.rglob("*")
        if path.is_dir()
    ))
    expected_dirs = tuple(sorted({
        Path(name).parent.as_posix()
        for name in expected
        if Path(name).parent != Path(".")
    }))
    if actual_files != expected or actual_dirs != expected_dirs:
        raise ValueError
    entities: list[tuple[str, int, int, int, int]] = [
        (
            ".",
            root_info.st_dev,
            root_info.st_ino,
            root_info.st_size,
            root_info.st_mtime_ns,
        )
    ]
    for name in expected_dirs:
        info = os.lstat(absolute / Path(name))
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
        ):
            raise ValueError
        entities.append(
            (name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        )
    for name in expected:
        path = absolute / Path(name)
        info = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
            or info.st_nlink != 1
        ):
            raise ValueError
        entities.append(
            (name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        )
    return tuple(entities)


def _digest_input(
    path: Path,
    *,
    artifact_roots: Mapping[str, Path],
) -> tuple[ArtifactDigest, tuple[int, int]]:
    absolute = Path(os.path.abspath(path))
    alias, root = select_artifact_root(
        absolute,
        artifact_roots=artifact_roots,
    )
    resolved = absolute.resolve(strict=True)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(absolute)):
        raise ValueError
    info_before = os.lstat(absolute)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        not stat.S_ISREG(info_before.st_mode)
        or info_before.st_nlink != 1
        or getattr(info_before, "st_file_attributes", 0) & reparse
    ):
        raise ValueError
    raw = absolute.read_bytes()
    info_after = os.lstat(absolute)
    identity_before = (
        info_before.st_dev,
        info_before.st_ino,
        info_before.st_size,
        info_before.st_mtime_ns,
        info_before.st_ctime_ns,
    )
    identity_after = (
        info_after.st_dev,
        info_after.st_ino,
        info_after.st_size,
        info_after.st_mtime_ns,
        info_after.st_ctime_ns,
    )
    if identity_before != identity_after or len(raw) != info_before.st_size:
        raise ValueError
    relative = resolved.relative_to(root).as_posix()
    return (
        ArtifactDigest(
            root_alias=alias,
            relative_path=relative,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        ),
        (info_before.st_dev, info_before.st_ino),
    )


def _validate_non_nested_roots(artifact_roots: Mapping[str, Path]) -> None:
    roots: list[tuple[Path, tuple[int, int]]] = []
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for root in artifact_roots.values():
        absolute = Path(os.path.abspath(root))
        resolved = absolute.resolve(strict=True)
        info = os.lstat(absolute)
        if (
            os.path.normcase(str(absolute)) != os.path.normcase(str(resolved))
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse
        ):
            raise ValueError
        roots.append((resolved, (info.st_dev, info.st_ino)))
    if len({identity for _, identity in roots}) != len(roots):
        raise ValueError
    for index, (left, _) in enumerate(roots):
        for right, _ in roots[index + 1:]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError


def _validate_stage_context(
    *,
    context: StageContext,
    node: StageNode,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> None:
    if (
        type(context) is not StageContext
        or context.node is not node
        or context.config is not config
        or type(context.inputs) is not tuple
        or len(context.inputs) != 21
        or any(type(item) is not ResolvedInput for item in context.inputs)
        or tuple(item.digest for item in context.inputs)
        != tuple(cast(ExternalInput, item).artifact for item in node.inputs)
    ):
        raise ValueError
    for item in context.inputs:
        alias, root = select_artifact_root(
            item.path,
            artifact_roots=artifact_roots,
        )
        if (
            alias != item.digest.root_alias
            or item.path.resolve(strict=True)
            != (root / item.digest.relative_path).resolve(strict=True)
        ):
            raise ValueError


__all__ = [
    "FormalBacktestStageResult",
    "make_formal_backtest_run_plan",
    "run_formal_backtest_stage",
]
