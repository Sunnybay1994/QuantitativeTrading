"""Formal research-summary StageRunner publication compatibility."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ResearchSummaryUpstreamPaths,
    VerifiedEvaluationArtifact,
    VerifiedExperimentIdentity,
    VerifiedResearchSummaryArtifact,
)
from quant.research.m3.evaluate import (
    EvaluationFreshVerificationContext,
    FormalSummaryStagePublicationIdentity,
    build_research_summary_stage_artifact,
    verify_research_summary_stage_artifact,
    verify_research_summary_stage_precommit,
    verify_research_summary_stage_publication,
)
from quant.research.m3.orchestration import (
    SUMMARY_STAGE_SPEC,
    M3StageRunnerError,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
    make_summary_run_plan,
    select_run_plan_nodes,
)
from quant.research.m3.run_state import StageReceipt

_ERROR = "M3_FORMAL_SUMMARY_STAGE_INVALID"
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_SUMMARY_OUTPUTS = tuple(
    sorted(item.relative_path for item in SUMMARY_STAGE_SPEC.outputs)
)


@dataclass(frozen=True)
class FormalSummaryStageResult:
    """Exact result of one formal summary StageRunner wave and final verifier."""

    final_root: Path
    receipt_path: Path
    verified: VerifiedResearchSummaryArtifact
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        path_type = type(Path())
        if (
            type(self.final_root) is not path_type
            or type(self.receipt_path) is not path_type
            or type(self.verified) is not VerifiedResearchSummaryArtifact
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
            or self.verified.root != self.final_root
            or self.receipt.stage != "research-summary"
            or self.receipt.scope != "EXPERIMENT"
        ):
            raise ValueError(_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_ERROR)


def run_formal_summary_stage(
    *,
    stage_root: Path,
    artifact_roots: Mapping[str, Path],
    config: LoadedM3Config,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    evaluation_contexts: Sequence[EvaluationFreshVerificationContext],
    experiment: VerifiedExperimentIdentity,
    horizon_sessions: Literal[5, 10],
    upstream_paths: ResearchSummaryUpstreamPaths,
    resume: bool = True,
) -> FormalSummaryStageResult:
    """Publish one formal summary node through the unique StageRunner wiring."""
    identity: FormalSummaryStagePublicationIdentity | None = None
    node: StageNode | None = None
    plan = None
    horizon_bundle = None
    input_error: str | None = None
    try:
        _require_project_only_roots(artifact_roots)
        _require_stage_root(stage_root, artifact_roots=artifact_roots)
        if (
            type(config) is not LoadedM3Config
            or type(experiment) is not VerifiedExperimentIdentity
            or type(horizon_sessions) is not int
            or horizon_sessions not in {5, 10}
            or type(upstream_paths) is not ResearchSummaryUpstreamPaths
            or type(resume) is not bool
            or not evaluations
            or not evaluation_contexts
            or len(evaluations) != len(evaluation_contexts)
            or len(evaluations) != len(upstream_paths.evaluation_receipt_paths)
            or any(type(item) is not VerifiedEvaluationArtifact for item in evaluations)
            or any(
                type(item) is not EvaluationFreshVerificationContext
                for item in evaluation_contexts
            )
        ):
            raise ValueError
        plan = make_summary_run_plan(
            config=config,
            experiment=experiment,
            evaluations=evaluations,
            artifact_roots=artifact_roots,
        )
        identity, node = _select_canonical_summary_node(
            plan=plan,
            evaluations=evaluations,
            experiment=experiment,
            horizon_sessions=horizon_sessions,
            stage_root=stage_root,
        )
        horizon_bundle = _horizon_inputs(
            evaluations=evaluations,
            evaluation_contexts=evaluation_contexts,
            upstream_paths=upstream_paths,
            horizon_sessions=horizon_sessions,
        )
    except M3StageRunnerError as caught:
        input_error = caught.code
    except Exception:
        input_error = "STAGE_INPUT_INVALID"
    if (
        input_error is not None
        or identity is None
        or node is None
        or plan is None
        or horizon_bundle is None
    ):
        raise M3StageRunnerError(input_error or "STAGE_INPUT_INVALID") from None

    runner_error: str | None = None
    runner: StageRunner | None = None
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

    expected_identity = identity
    expected_node = node
    expected_bundle = horizon_bundle
    closure = _make_summary_stage_closure_dispatcher(
        identity=expected_identity,
        evaluations=expected_bundle[0],
        evaluation_contexts=expected_bundle[1],
        experiment=experiment,
        config=config,
        upstream_paths=expected_bundle[2],
        artifact_roots=artifact_roots,
    )

    def handler(context: StageContext) -> StageBuildReport:
        if (
            type(context) is not StageContext
            or context.node is not expected_node
            or context.config is not config
        ):
            raise ValueError
        build_research_summary_stage_artifact(
            identity=expected_identity,
            evaluations=expected_bundle[0],
            evaluation_contexts=expected_bundle[1],
            experiment=experiment,
            config=config,
            upstream_paths=expected_bundle[2],
            artifact_roots=artifact_roots,
            output_root=context.temp_output_root,
        )
        report = StageBuildReport(_SUMMARY_OUTPUTS)
        if report.output_relative_paths != _SUMMARY_OUTPUTS:
            raise ValueError
        return report

    static_error: str | None = None
    static = None
    try:
        static = runner.run_static(
            node=expected_node,
            handler=handler,
            closure_verifier=closure,
            resume=resume,
            plan=plan,
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
    verified: VerifiedResearchSummaryArtifact | None = None
    try:
        expected_final = stage_root.joinpath(
            *expected_identity.final_relative_path.parts
        ).resolve(strict=True)
        expected_receipt = (stage_root / expected_node.receipt_path).resolve(strict=True)
        if (
            static.final_root.resolve(strict=True) != expected_final
            or static.receipt_path.resolve(strict=True) != expected_receipt
            or type(static.receipt) is not StageReceipt
        ):
            raise ValueError
        candidate = verify_research_summary_stage_artifact(
            identity=expected_identity,
            root=static.final_root,
            receipt_path=static.receipt_path,
            evaluations=expected_bundle[0],
            evaluation_contexts=expected_bundle[1],
            experiment=experiment,
            config=config,
            upstream_paths=expected_bundle[2],
            artifact_roots=artifact_roots,
        )
        if (
            type(candidate) is not VerifiedResearchSummaryArtifact
            or candidate.root != static.final_root.resolve(strict=True)
            or candidate.manifest.experiment_key != expected_identity.experiment_key
            or candidate.manifest.horizon_sessions != expected_identity.horizon_sessions
            or candidate.manifest.model != expected_identity.model
            or candidate.manifest.model_version != expected_identity.model_version
            or static.receipt.stage != "research-summary"
            or static.receipt.scope != "EXPERIMENT"
            or static.receipt.scope_key != expected_identity.experiment_key
            or len(static.receipt.outputs) != len(_SUMMARY_OUTPUTS)
        ):
            raise ValueError
        verified = candidate
    except M3StageRunnerError as caught:
        final_error = caught.code
    except Exception:
        final_error = "STAGE_RECOVERY_CONFLICT"
    if final_error is not None or verified is None:
        raise M3StageRunnerError(
            final_error or "STAGE_RECOVERY_CONFLICT"
        ) from None
    return FormalSummaryStageResult(
        final_root=static.final_root.resolve(strict=True),
        receipt_path=static.receipt_path.resolve(strict=True),
        verified=verified,
        receipt=static.receipt,
        reused=static.reused,
    )


def _make_summary_stage_closure_dispatcher(
    *,
    identity: FormalSummaryStagePublicationIdentity,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    evaluation_contexts: Sequence[EvaluationFreshVerificationContext],
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    upstream_paths: ResearchSummaryUpstreamPaths,
    artifact_roots: Mapping[str, Path],
):
    """Package-owned closure: final→publication, else prove temp→precommit."""

    def dispatcher(root: Path) -> None:
        path_type = type(Path())
        if type(root) is not path_type or not root.is_absolute():
            raise ValueError
        # Lexical absolute only — never resolve before phase or before verifier.
        raw_absolute = Path(os.path.abspath(root))
        try:
            info = os.lstat(raw_absolute)
        except OSError:
            raise ValueError from None
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE
            or not stat.S_ISDIR(info.st_mode)
        ):
            raise ValueError
        if (
            type(identity.stage_root) is not path_type
            or not identity.stage_root.is_absolute()
        ):
            raise ValueError
        candidate_final = Path(os.path.abspath(identity.stage_root)).joinpath(
            *identity.final_relative_path.parts
        )
        is_final = os.path.normcase(str(raw_absolute)) == os.path.normcase(
            str(candidate_final)
        )
        if is_final:
            verified = verify_research_summary_stage_publication(
                identity=identity,
                root=raw_absolute,
                evaluations=evaluations,
                evaluation_contexts=evaluation_contexts,
                experiment=experiment,
                config=config,
                upstream_paths=upstream_paths,
                artifact_roots=artifact_roots,
            )
            if type(verified) is not VerifiedResearchSummaryArtifact:
                raise ValueError
            return
        verified = verify_research_summary_stage_precommit(
            identity=identity,
            root=raw_absolute,
            evaluations=evaluations,
            evaluation_contexts=evaluation_contexts,
            experiment=experiment,
            config=config,
            upstream_paths=upstream_paths,
            artifact_roots=artifact_roots,
        )
        if type(verified) is not VerifiedResearchSummaryArtifact:
            raise ValueError

    return dispatcher


def _select_canonical_summary_node(
    *,
    plan: Any,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    experiment: VerifiedExperimentIdentity,
    horizon_sessions: Literal[5, 10],
    stage_root: Path,
) -> tuple[FormalSummaryStagePublicationIdentity, StageNode]:
    model, model_version = _unique_model_version(
        evaluations=evaluations, horizon_sessions=horizon_sessions
    )
    experiment_key = experiment.manifest.experiment_key
    node_id = f"summary.h{horizon_sessions}.{model}.{model_version}"
    expected_ids = tuple(item.node_id for item in plan.nodes)
    selected = select_run_plan_nodes(
        plan,
        expected_continuation="SUMMARY",
        expected_node_ids=expected_ids,
    )
    matches = [item for item in selected if item.node_id == node_id]
    if len(matches) != 1:
        raise ValueError
    node = matches[0]
    if (
        type(node) is not StageNode
        or node.spec_name != SUMMARY_STAGE_SPEC.name
        or node.scope != SUMMARY_STAGE_SPEC.scope
        or node.scope_key != experiment_key
        or node.horizon != horizon_sessions
        or node.output_specs != SUMMARY_STAGE_SPEC.outputs
        or type(node.publication) is not StaticDirectoryPublication
    ):
        raise ValueError
    final_relative = PurePosixPath(node.publication.final_directory)
    identity = FormalSummaryStagePublicationIdentity(
        stage_root=stage_root,
        node_id=node.node_id,
        final_relative_path=final_relative,
        experiment_key=experiment_key,
        horizon_sessions=horizon_sessions,
        model=model,
        model_version=model_version,
    )
    if final_relative != identity.final_relative_path:
        raise ValueError
    expected_receipt = (
        f"receipts/{SUMMARY_STAGE_SPEC.name}/"
        f"{experiment_key}.h{horizon_sessions}.{model}.{model_version}.json"
    )
    if node.receipt_path != expected_receipt:
        raise ValueError
    return identity, node


def _unique_model_version(
    *,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    horizon_sessions: Literal[5, 10],
) -> tuple[str, str]:
    group = tuple(
        item
        for item in evaluations
        if item.manifest.horizon_sessions == horizon_sessions
    )
    if len(group) < 2:
        raise ValueError
    models = {item.manifest.model for item in group}
    versions = {item.manifest.model_version for item in group}
    if len(models) != 1 or len(versions) != 1:
        raise ValueError
    return next(iter(models)), next(iter(versions))


def _horizon_inputs(
    *,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    evaluation_contexts: Sequence[EvaluationFreshVerificationContext],
    upstream_paths: ResearchSummaryUpstreamPaths,
    horizon_sessions: Literal[5, 10],
) -> tuple[
    tuple[VerifiedEvaluationArtifact, ...],
    tuple[EvaluationFreshVerificationContext, ...],
    ResearchSummaryUpstreamPaths,
]:
    selected: list[int] = []
    for index, item in enumerate(evaluations):
        if item.manifest.horizon_sessions == horizon_sessions:
            selected.append(index)
    if len(selected) < 2:
        raise ValueError
    horizon_evaluations = tuple(evaluations[index] for index in selected)
    horizon_contexts = tuple(evaluation_contexts[index] for index in selected)
    horizon_receipts = tuple(
        upstream_paths.evaluation_receipt_paths[index] for index in selected
    )
    folds = tuple(item.manifest.fold for item in horizon_evaluations)
    if folds != tuple(sorted(folds)) or len(set(folds)) != len(folds):
        raise ValueError
    return (
        horizon_evaluations,
        horizon_contexts,
        ResearchSummaryUpstreamPaths(
            experiment_receipt_path=upstream_paths.experiment_receipt_path,
            evaluation_receipt_paths=horizon_receipts,
        ),
    )


def _require_project_only_roots(artifact_roots: Mapping[str, Path]) -> None:
    path_type = type(Path())
    if (
        not isinstance(artifact_roots, Mapping)
        or set(artifact_roots) != {"PROJECT"}
        or type(next(iter(artifact_roots))) is not str
    ):
        raise ValueError
    root = artifact_roots["PROJECT"]
    if type(root) is not path_type:
        raise ValueError
    absolute = Path(os.path.abspath(root))
    resolved = absolute.resolve(strict=True)
    info = os.lstat(absolute)
    if (
        os.path.normcase(str(absolute)) != os.path.normcase(str(resolved))
        or not absolute.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & _REPARSE
    ):
        raise ValueError


def _require_stage_root(
    stage_root: Path, *, artifact_roots: Mapping[str, Path]
) -> None:
    path_type = type(Path())
    if type(stage_root) is not path_type:
        raise ValueError
    absolute = Path(os.path.abspath(stage_root))
    resolved = absolute.resolve(strict=True)
    info = os.lstat(absolute)
    project = artifact_roots["PROJECT"].resolve(strict=True)
    if (
        os.path.normcase(str(absolute)) != os.path.normcase(str(resolved))
        or not absolute.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & _REPARSE
        or not resolved.is_relative_to(project)
    ):
        raise ValueError


__all__ = [
    "FormalSummaryStageResult",
    "run_formal_summary_stage",
]
