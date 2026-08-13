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
    verify_backtest_artifact,
    verify_backtest_build_output,
)
from quant.data.m3_release import G1ManifestV5, VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
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
)

_ERROR = "M3_FORMAL_BACKTEST_STAGE_INVALID"


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
        build_backtest_artifact(
            target=target,
            plan=plan,
            release=release,
            experiment=experiment,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
            output_root=context.temp_output_root,
        )
        return StageBuildReport(backtest_artifact_output_relative_paths())

    def closure(root: Path) -> None:
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
