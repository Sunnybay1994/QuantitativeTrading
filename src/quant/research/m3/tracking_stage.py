"""Formal identity-resolved G8D tracking StageRunner wave."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    VerifiedBacktestArtifact,
    VerifiedEvaluationArtifact,
)
from quant.research.m3.orchestration import (
    TRACKING_STAGE_SPEC,
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
from quant.research.m3.tracking import (
    FormalTrackingFreshVerificationContext,
    TrackingClientProtocol,
    TrackingMarkerV1,
    TrackingRequestV1,
    _artifact_digest_sha256,
    build_formal_tracking_request,
    compute_tracking_key,
    formal_tracking_input_paths,
    publish_tracking_marker,
    publish_tracking_request,
    read_tracking_marker,
    read_tracking_request,
    register_remote_tracking_run,
)

_ERROR = "M3_FORMAL_TRACKING_STAGE_INVALID"
_TRACKING_OUTPUTS = ("tracking_marker.json", "tracking_request.json")


@dataclass(frozen=True)
class FormalTrackingStageResult:
    """Exact result of one formal tracking runner wave and final local verifier."""

    final_root: Path
    receipt_path: Path
    request: TrackingRequestV1
    marker: TrackingMarkerV1
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.final_root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.request) is not TrackingRequestV1
            or type(self.marker) is not TrackingMarkerV1
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise ValueError(_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_ERROR)


def make_formal_tracking_run_plan(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> RunPlan:
    """Resolve the exact 34-file formal tracking WORK wave without writes."""
    try:
        return _make_formal_tracking_run_plan(
            evaluation=evaluation,
            backtest=backtest,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
        )
    except Exception:
        pass
    raise M3StageRunnerError("STAGE_INPUT_INVALID") from None


def _make_formal_tracking_run_plan(
    *,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> RunPlan:
    if (
        type(evaluation) is not VerifiedEvaluationArtifact
        or type(backtest) is not VerifiedBacktestArtifact
        or type(config) is not LoadedM3Config
        or type(fresh_context) is not FormalTrackingFreshVerificationContext
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not isinstance(root, Path)
            for alias, root in artifact_roots.items()
        )
    ):
        raise ValueError
    _validate_non_nested_roots(artifact_roots)
    evaluation_manifest = evaluation.manifest
    backtest_manifest = backtest.manifest
    target_manifest = fresh_context.target.manifest
    plan_manifest = fresh_context.plan.manifest
    fold = evaluation_manifest.fold
    horizon = evaluation_manifest.horizon_sessions
    work_key = evaluation_manifest.work_key
    facts = fresh_context.backtest_context.facts_fresh_context
    if (
        work_key != backtest_manifest.work_key
        or evaluation_manifest.experiment_key != backtest_manifest.experiment_key
        or evaluation_manifest.scientific_config_sha256
        != backtest_manifest.scientific_config_sha256
        or evaluation_manifest.fold != target_manifest.fold
        or evaluation_manifest.horizon_sessions != target_manifest.horizon_sessions
        or evaluation_manifest.model != target_manifest.model
        or evaluation_manifest.model_version != target_manifest.model_version
        or plan_manifest.work_key != work_key
        or plan_manifest.fold != fold
        or plan_manifest.horizon_sessions != horizon
        or plan_manifest.experiment_key != evaluation_manifest.experiment_key
        or plan_manifest.scientific_config_sha256
        != evaluation_manifest.scientific_config_sha256
        or target_manifest.work_key != work_key
        or target_manifest.experiment_key != evaluation_manifest.experiment_key
        or target_manifest.scientific_config_sha256
        != evaluation_manifest.scientific_config_sha256
        or fresh_context.evaluation_context.release is not fresh_context.release
        or fresh_context.evaluation_context.experiment is not fresh_context.experiment
        or facts.config is not config
        or facts.experiment is not fresh_context.experiment
        or facts.target is not fresh_context.target
        or evaluation_manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or backtest_manifest.scientific_config_sha256
        != config.scientific_config_sha256
        or fresh_context.experiment.manifest.experiment_key
        != evaluation_manifest.experiment_key
        or fresh_context.release.manifest.release_id
        != backtest_manifest.g1_release_id
        or fresh_context.release.manifest_sha256
        != backtest_manifest.g1_release_manifest_sha256
        or work_key
        != compute_work_key(
            experiment_key=evaluation_manifest.experiment_key,
            fold=fold,
            horizon=horizon,
        )
    ):
        raise ValueError
    input_paths = formal_tracking_input_paths(
        evaluation=evaluation,
        backtest=backtest,
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
    if len(digests) != 34 or len(identities) != 34:
        raise ValueError
    node = StageNode(
        node_id=f"tracking.{fold}.h{horizon}",
        spec_name=TRACKING_STAGE_SPEC.name,
        scope="WORK",
        scope_key=work_key,
        fold=fold,
        horizon=horizon,
        dependencies=(),
        inputs=tuple(ExternalInput(item) for item in digests),
        publication=StaticDirectoryPublication(f"work/{work_key}/tracking"),
        output_specs=TRACKING_STAGE_SPEC.outputs,
        receipt_path=f"receipts/tracking/{work_key}.json",
    )
    return RunPlan(continuation="WORK", nodes=(node,))


def run_formal_tracking_stage(
    *,
    stage_root: Path,
    evaluation: VerifiedEvaluationArtifact,
    backtest: VerifiedBacktestArtifact,
    config: LoadedM3Config,
    fresh_context: FormalTrackingFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    client: TrackingClientProtocol,
    resume: bool = True,
) -> FormalTrackingStageResult:
    """Register, publish, receipt, and finally verify one formal tracking wave."""
    if client is None or not hasattr(client, "find_runs"):
        raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
    request = None
    run_plan = None
    input_error: str | None = None
    try:
        request = build_formal_tracking_request(
            evaluation=evaluation,
            backtest=backtest,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
        )
        run_plan = make_formal_tracking_run_plan(
            evaluation=evaluation,
            backtest=backtest,
            config=config,
            fresh_context=fresh_context,
            artifact_roots=artifact_roots,
        )
    except M3StageRunnerError as caught:
        input_error = caught.code
    except Exception:
        input_error = "STAGE_INPUT_INVALID"
    if input_error is not None or request is None or run_plan is None:
        raise M3StageRunnerError(input_error or "STAGE_INPUT_INVALID") from None
    node = run_plan.nodes[0]
    experiment_name = config.section("tracking")["experiment_name"]
    if type(experiment_name) is not str:
        raise M3StageRunnerError("STAGE_INPUT_INVALID") from None
    runner_error: str | None = None
    runner = None
    try:
        runner = StageRunner(
            stage_root=stage_root,
            artifact_roots=artifact_roots,
            config=config,
        )
    except M3StageRunnerError as caught:
        runner_error = caught.code
    except Exception:
        runner_error = "STAGE_INPUT_INVALID"
    if runner_error is not None or runner is None:
        raise M3StageRunnerError(runner_error or "STAGE_INPUT_INVALID") from None

    expected_request = request

    def handler(context: StageContext) -> StageBuildReport:
        _validate_stage_context(
            context=context,
            node=node,
            config=config,
            artifact_roots=artifact_roots,
        )
        request_path = context.temp_output_root / "tracking_request.json"
        marker_path = context.temp_output_root / "tracking_marker.json"
        request_sha = publish_tracking_request(
            path=request_path,
            request=expected_request,
        )
        if request_sha != hashlib.sha256(
            request_path.read_bytes()
        ).hexdigest():
            raise ValueError
        lock_root = (
            stage_root
            / ".tracking-locks"
            / expected_request.tracking_target_key
            / compute_tracking_key(
                work_key=expected_request.work_key,
                request_sha256=request_sha,
            )
        )
        marker = register_remote_tracking_run(
            request=expected_request,
            request_sha256=request_sha,
            tracking_uri=config.canonical_tracking_uri,
            experiment_name=experiment_name,
            artifact_roots=artifact_roots,
            lock_root=lock_root,
            client=client,
        )
        publish_tracking_marker(path=marker_path, marker=marker)
        return StageBuildReport(_TRACKING_OUTPUTS)

    def closure(root: Path) -> None:
        _verify_tracking_local_closure(
            root=root,
            expected_request=expected_request,
        )

    static_error: str | None = None
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
        static_error = caught.code
    except Exception:
        static_error = "STAGE_RECOVERY_CONFLICT"
    if static_error is not None or static is None:
        raise M3StageRunnerError(
            static_error or "STAGE_RECOVERY_CONFLICT"
        ) from None

    final_error: str | None = None
    request_on_disk: TrackingRequestV1 | None = None
    marker_on_disk: TrackingMarkerV1 | None = None
    try:
        _verify_tracking_local_closure(
            root=static.final_root,
            expected_request=expected_request,
        )
        request_on_disk = read_tracking_request(
            static.final_root / "tracking_request.json"
        )
        marker_on_disk = read_tracking_marker(
            static.final_root / "tracking_marker.json"
        )
        if (
            request_on_disk != expected_request
            or static.receipt.stage != "tracking"
            or static.receipt.scope != "WORK"
            or static.receipt.scope_key != node.scope_key
            or len(static.receipt.inputs) != 34
            or len(static.receipt.outputs) != 2
        ):
            raise ValueError
        if (stage_root / ".tracking-locks").exists():
            final_entries = {
                path.relative_to(static.final_root).as_posix()
                for path in static.final_root.rglob("*")
                if path.is_file() or path.is_dir()
            }
            if any(
                entry == ".tracking-locks" or entry.startswith(".tracking-locks/")
                for entry in final_entries
            ):
                raise ValueError
    except M3StageRunnerError as caught:
        final_error = caught.code
    except Exception:
        final_error = "STAGE_RECOVERY_CONFLICT"
    if (
        final_error is not None
        or request_on_disk is None
        or marker_on_disk is None
    ):
        raise M3StageRunnerError(
            final_error or "STAGE_RECOVERY_CONFLICT"
        ) from None
    return FormalTrackingStageResult(
        final_root=static.final_root,
        receipt_path=static.receipt_path,
        request=request_on_disk,
        marker=marker_on_disk,
        receipt=static.receipt,
        reused=static.reused,
    )


def _verify_tracking_local_closure(
    *,
    root: Path,
    expected_request: TrackingRequestV1,
) -> None:
    if not isinstance(root, Path):
        raise ValueError
    absolute = Path(os.path.abspath(root)).resolve(strict=True)
    names = {entry.name for entry in os.scandir(absolute)}
    if names != set(_TRACKING_OUTPUTS):
        raise ValueError
    request = read_tracking_request(absolute / "tracking_request.json")
    marker = read_tracking_marker(absolute / "tracking_marker.json")
    if request != expected_request:
        raise ValueError
    request_sha = hashlib.sha256(
        (absolute / "tracking_request.json").read_bytes()
    ).hexdigest()
    artifact_sha = _artifact_digest_sha256(expected_request.artifacts)
    tracking_key = compute_tracking_key(
        work_key=expected_request.work_key,
        request_sha256=request_sha,
    )
    if (
        marker.tracking_target_key != expected_request.tracking_target_key
        or marker.tracking_key != tracking_key
        or marker.request_sha256 != request_sha
        or marker.artifact_digest_sha256 != artifact_sha
    ):
        raise ValueError
    after = {entry.name for entry in os.scandir(absolute)}
    if after != names:
        raise ValueError


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
        or len(context.inputs) != 34
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
    "FormalTrackingStageResult",
    "make_formal_tracking_run_plan",
    "run_formal_tracking_stage",
]
