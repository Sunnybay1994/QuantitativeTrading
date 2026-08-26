"""Package-owned successor formal / Gate downstream wiring (M3-G8F-R2W).

Owns the ten Protocol callables bound by
``make_canonical_successor_production_dependencies()``.  Combines existing
public backtest, tracking, R2S summary, reproducibility, readiness, quality,
and acceptance APIs.  Never invents receipt schema, Gate order, or caller
injection of tracking clients / wrappers.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, NoReturn

from quant.research.m3.successor_runtime import (
    FoldExecution,
    GateExecution,
    GateVerification,
    HORIZONS,
    StageReceiptRef,
    SuccessorFoldRequest,
    SuccessorPublicApiBundle,
    SuccessorRuntimeError,
    SuccessorStageContext,
    compute_successor_gate_identity,
    make_public_successor_api_bundle,
    project_stage_root,
)


def _fail(code: str) -> NoReturn:
    raise SuccessorRuntimeError(code) from None


def _require_finite_config_float(
    value: object, *, code: str = "SUCCESSOR_GATE_FAILED",
) -> float:
    """Exact float + finite; rejects bool / int / str / NaN / Inf (config semantics)."""

    if type(value) is not float or not math.isfinite(value):
        _fail(code)
    return value


def _require_canonical_public_apis(
    public_apis: SuccessorPublicApiBundle,
) -> SuccessorPublicApiBundle:
    canonical = make_public_successor_api_bundle()
    try:
        from quant.research.m3.successor_runtime import _require_canonical_public_api_bundle

        _require_canonical_public_api_bundle(public_apis, canonical)
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_INPUT_INVALID")
    return public_apis


def _require_sorted_unique_refs(
    refs: tuple[StageReceiptRef, ...],
) -> tuple[StageReceiptRef, ...]:
    if type(refs) is not tuple or any(type(item) is not StageReceiptRef for item in refs):
        _fail("SUCCESSOR_STAGE_INVALID")
    node_ids = tuple(item.node_id for item in refs)
    if node_ids != tuple(sorted(node_ids)) or len(set(node_ids)) != len(node_ids):
        _fail("SUCCESSOR_STAGE_INVALID")
    return refs


@dataclass(frozen=True)
class _NodeRef:
    node_id: str
    fold: str | None
    horizon: int | None


def _stage_receipt_ref(
    *,
    receipt_path: Path,
    receipt: object,
    project_root: Path,
    node: _NodeRef,
    artifact_roots: Mapping[str, Path] | None = None,
) -> StageReceiptRef:
    from quant.research.m3.run_state import StageReceipt, verify_stage_receipt_with_bytes

    roots = artifact_roots or MappingProxyType({"PROJECT": project_root})
    try:
        resolved = receipt_path.resolve(strict=True)
        relative = resolved.relative_to(project_root.resolve(strict=True)).as_posix()
        verified = verify_stage_receipt_with_bytes(
            receipt_path=resolved, artifact_roots=roots,
        )
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")
    if (
        verified is None
        or type(receipt) is not StageReceipt
        or verified.receipt != receipt
    ):
        _fail("SUCCESSOR_STAGE_INVALID")
    return StageReceiptRef(
        node_id=node.node_id,
        stage=receipt.stage,
        scope=receipt.scope,
        scope_key=receipt.scope_key,
        relative_path=relative,
        sha256=verified.sha256,
        fold=node.fold,
        horizon=node.horizon,
    )


def _canonical_fold_request(
    *, folds: tuple[FoldExecution, ...], context: SuccessorStageContext, fold: str,
) -> SuccessorFoldRequest:
    matches = tuple(item for item in context.request.folds if item.fold == fold)
    if len(matches) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    execution = next((item for item in folds if item.fold == fold), None)
    if execution is None:
        _fail("SUCCESSOR_GATE_FAILED")
    return matches[0]


def run_successor_formal_stage(
    *,
    stage: Literal["backtest", "tracking"],
    horizon: int,
    request: SuccessorFoldRequest,
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
    prior_refs: tuple[StageReceiptRef, ...],
    resume: bool,
) -> StageReceiptRef:
    """Run one formal backtest or tracking stage from explicit prior_refs."""

    del runner  # StageRunner identity is enforced by public formal stage APIs.
    if stage not in {"backtest", "tracking"} or type(resume) is not bool:
        _fail("SUCCESSOR_STAGE_INVALID")
    if type(request) is not SuccessorFoldRequest or type(context) is not SuccessorStageContext:
        _fail("SUCCESSOR_STAGE_INVALID")
    refs = _require_sorted_unique_refs(prior_refs)
    apis = _require_canonical_public_apis(public_apis)
    from quant.research.m3.successor_upstream_stage import (
        rehydrate_successor_formal_backtest_inputs,
        rehydrate_successor_formal_tracking_inputs,
    )

    project_root = context.project_root
    try:
        if stage == "backtest":
            inputs = rehydrate_successor_formal_backtest_inputs(
                prior_refs=refs,
                request=request,
                context=context,
                horizon=horizon,
            )
            if apis.formal_backtest_run_plan is not None:
                apis.formal_backtest_run_plan(
                    target=inputs.target,
                    plan=inputs.plan,
                    release=inputs.release,
                    experiment=inputs.experiment,
                    config=inputs.config,
                    fresh_context=inputs.fresh_context,
                    artifact_roots=inputs.artifact_roots,
                )
            backtest_result = apis.formal_backtest_stage(
                stage_root=inputs.stage_root,
                target=inputs.target,
                plan=inputs.plan,
                release=inputs.release,
                experiment=inputs.experiment,
                config=inputs.config,
                fresh_context=inputs.fresh_context,
                artifact_roots=inputs.artifact_roots,
                resume=resume,
            )
            return _stage_receipt_ref(
                receipt_path=backtest_result.receipt_path,
                receipt=backtest_result.receipt,
                project_root=project_root,
                node=_NodeRef(
                    node_id=f"backtest.{inputs.fold}.h{inputs.horizon}",
                    fold=inputs.fold,
                    horizon=inputs.horizon,
                ),
            )
        tracking = rehydrate_successor_formal_tracking_inputs(
            prior_refs=refs,
            request=request,
            context=context,
            horizon=horizon,
        )
        from quant.research.m3.tracking import create_mlflow_tracking_client

        client = create_mlflow_tracking_client(tracking_uri=tracking.tracking_uri)
        if apis.formal_tracking_run_plan is not None:
            apis.formal_tracking_run_plan(
                evaluation=tracking.evaluation,
                backtest=tracking.backtest,
                config=tracking.config,
                fresh_context=tracking.fresh_context,
                artifact_roots=tracking.artifact_roots,
            )
        tracking_result = apis.formal_tracking_stage(
            stage_root=tracking.stage_root,
            evaluation=tracking.evaluation,
            backtest=tracking.backtest,
            config=tracking.config,
            fresh_context=tracking.fresh_context,
            artifact_roots=tracking.artifact_roots,
            client=client,
            resume=resume,
        )
        return _stage_receipt_ref(
            receipt_path=tracking_result.receipt_path,
            receipt=tracking_result.receipt,
            project_root=project_root,
            node=_NodeRef(
                node_id=f"tracking.{tracking.fold}.h{tracking.horizon}",
                fold=tracking.fold,
                horizon=tracking.horizon,
            ),
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_STAGE_INVALID")


def verify_successor_fold(
    *,
    execution: FoldExecution,
    context: SuccessorStageContext,
    public_apis: SuccessorPublicApiBundle,
) -> None:
    """Fresh-rehydrate and re-verify one fold's formal closure from its receipts."""

    if type(execution) is not FoldExecution or type(context) is not SuccessorStageContext:
        _fail("SUCCESSOR_STAGE_INVALID")
    if context.fold not in (None, execution.fold):
        _fail("SUCCESSOR_STAGE_INVALID")
    _require_canonical_public_apis(public_apis)
    refs = _require_sorted_unique_refs(execution.receipts)
    fold_request = _canonical_fold_request(
        folds=(execution,), context=context, fold=execution.fold,
    )
    from quant.research.m3.successor_upstream_stage import (
        rehydrate_successor_formal_tracking_inputs,
    )

    for horizon in HORIZONS:
        try:
            rehydrate_successor_formal_tracking_inputs(
                prior_refs=refs,
                request=fold_request,
                context=context,
                horizon=horizon,
            )
        except SuccessorRuntimeError:
            raise
        except Exception:
            _fail("SUCCESSOR_STAGE_INVALID")


def verify_successor_summary_gate(
    *,
    gate: GateExecution,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
) -> GateVerification:
    """Fresh-verify each research-summary receipt via canonical R2S summary_verifier."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    _require_gate_shape(
        gate=gate,
        expected="summary",
        folds=folds,
        prior_gates=prior_gates,
        context=context,
    )
    if len(gate.receipt_refs) != 2:
        _fail("SUCCESSOR_GATE_FAILED")
    experiment_keys = {item.experiment_key for item in folds}
    if len(experiment_keys) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    experiment_key = next(iter(experiment_keys))
    if {item.horizon for item in gate.receipt_refs} != set(HORIZONS):
        _fail("SUCCESSOR_GATE_FAILED")
    from quant.research.m3.contracts import VerifiedResearchSummaryArtifact
    from quant.research.m3.successor_upstream_stage import (
        rehydrate_successor_summary_horizon_verify_inputs,
    )

    try:
        for ref in gate.receipt_refs:
            if (
                ref.stage != "research-summary"
                or ref.fold is not None
                or ref.scope != "EXPERIMENT"
                or ref.scope_key != experiment_key
                or ref.horizon not in HORIZONS
            ):
                raise ValueError
            inputs = rehydrate_successor_summary_horizon_verify_inputs(
                folds=folds,
                context=context,
                summary_ref=ref,
            )
            verified = apis.summary_verifier(
                identity=inputs.identity,
                root=inputs.root,
                receipt_path=inputs.receipt_path,
                evaluations=inputs.evaluations,
                evaluation_contexts=inputs.evaluation_contexts,
                experiment=inputs.experiment,
                config=inputs.config,
                upstream_paths=inputs.upstream_paths,
                artifact_roots=inputs.artifact_roots,
            )
            if type(verified) is not VerifiedResearchSummaryArtifact:
                raise ValueError
            if (
                verified.summary_receipt_sha256 != ref.sha256
                or verified.manifest.experiment_key != experiment_key
                or verified.manifest.horizon_sessions != ref.horizon
                or verified.root.resolve(strict=True) != inputs.root.resolve(strict=True)
            ):
                raise ValueError
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return GateVerification(
        gate="summary",
        identity=gate.identity,
        receipt_node_ids=gate.receipt_node_ids,
    )


def run_successor_reproducibility_gate(
    *,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
    resume: bool,
) -> GateExecution:
    """Run one public reproducibility stage per fold×horizon."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    if (
        type(context) is not SuccessorStageContext
        or type(resume) is not bool
        or type(folds) is not tuple
        or len(folds) != 2
        or type(prior_gates) is not tuple
        or len(prior_gates) != 1
        or prior_gates[0].gate != "summary"
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    project_root = context.project_root
    toolchain = context.request.toolchain
    refs: list[StageReceiptRef] = []
    try:
        for execution in folds:
            fold_request = _canonical_fold_request(
                folds=folds, context=context, fold=execution.fold,
            )
            config = fold_request.config.config
            config_relative = fold_request.config.relative_path
            for horizon in HORIZONS:
                result = apis.reproducibility_stage(
                    project_root=project_root,
                    config=config,
                    config_relative=config_relative,
                    snapshot_id=execution.snapshot_id,
                    fold=execution.fold,
                    horizon=horizon,
                    python_executable=toolchain.python_executable,
                    resume=resume,
                )
                if result.receipt.scope_key != result.comparison_key:
                    raise ValueError
                refs.append(
                    _stage_receipt_ref(
                        receipt_path=result.receipt_path,
                        receipt=result.receipt,
                        project_root=project_root,
                        node=_NodeRef(
                            node_id=f"reproducibility.{execution.fold}.h{horizon}",
                            fold=execution.fold,
                            horizon=horizon,
                        ),
                    )
                )
        identity = compute_successor_gate_identity(
            gate="reproducibility", folds=folds, prior_gates=prior_gates,
        )
        return GateExecution(
            gate="reproducibility",
            status="PASS",
            identity=identity,
            receipt_refs=tuple(sorted(refs, key=lambda item: item.node_id)),
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")


def verify_successor_reproducibility_gate(
    *,
    gate: GateExecution,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
) -> GateVerification:
    """Fresh-verify each reproducibility receipt against its comparison_key."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    _require_gate_shape(
        gate=gate,
        expected="reproducibility",
        folds=folds,
        prior_gates=prior_gates,
        context=context,
    )
    if len(gate.receipt_refs) != 4:
        _fail("SUCCESSOR_GATE_FAILED")
    project_root = context.project_root
    try:
        for ref in gate.receipt_refs:
            if (
                ref.stage != "reproducibility"
                or ref.scope != "REPRO"
                or ref.fold is None
                or ref.horizon is None
            ):
                raise ValueError
            fold_request = _canonical_fold_request(
                folds=folds, context=context, fold=ref.fold,
            )
            config = fold_request.config.config
            acceptance = config.section("acceptance")
            score_atol = _require_finite_config_float(
                acceptance["reproducibility_score_atol"],
            )
            metric_atol = _require_finite_config_float(
                acceptance["reproducibility_metric_atol"],
            )
            runtime = context.request.runtime_identity
            python_path = context.request.toolchain.python_executable
            python_sha = hashlib.sha256(Path(python_path).read_bytes()).hexdigest()
            stage_root = project_stage_root(project_root=project_root, config=config)
            root = stage_root / "repro" / ref.scope_key
            apis.reproducibility_verifier(
                root=root,
                receipt_path=project_root / ref.relative_path,
                artifact_roots=MappingProxyType({"PROJECT": project_root}),
                comparison_key=ref.scope_key,
                score_atol=score_atol,
                metric_atol=metric_atol,
                code_version=runtime.code_version,
                dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
                python_executable_sha256=python_sha,
            )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return GateVerification(
        gate="reproducibility",
        identity=gate.identity,
        receipt_node_ids=gate.receipt_node_ids,
    )


def run_successor_readiness_gate(
    *,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
    resume: bool,
) -> GateExecution:
    """Publish exactly one global readiness-evidence physical receipt."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    if (
        type(context) is not SuccessorStageContext
        or type(resume) is not bool
        or type(folds) is not tuple
        or len(folds) != 2
        or type(prior_gates) is not tuple
        or len(prior_gates) != 2
        or tuple(item.gate for item in prior_gates) != ("summary", "reproducibility")
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    # Canonical readiness subject: fold_001 config/release (aggregate identity
    # still binds both folds via compute_successor_gate_identity).
    fold_request = _canonical_fold_request(
        folds=folds, context=context, fold=context.request.folds[0].fold,
    )
    project_root = context.project_root
    try:
        result = apis.readiness_stage(
            project_root=project_root,
            config=fold_request.config.config,
            config_relative=fold_request.config.relative_path,
            release=fold_request.release,
            resume=resume,
        )
        readiness_key = result.report.readiness_key
        if result.receipt.scope_key != readiness_key:
            raise ValueError
        stage_root = project_stage_root(
            project_root=project_root, config=fold_request.config.config,
        )
        receipt_path = (
            stage_root / "receipts" / "readiness-evidence" / f"{readiness_key}.json"
        )
        ref = _stage_receipt_ref(
            receipt_path=receipt_path,
            receipt=result.receipt,
            project_root=project_root,
            node=_NodeRef(node_id="readiness-evidence", fold=None, horizon=None),
        )
        if ref.scope_key != readiness_key or ref.fold is not None or ref.horizon is not None:
            raise ValueError
        identity = compute_successor_gate_identity(
            gate="readiness", folds=folds, prior_gates=prior_gates,
        )
        return GateExecution(
            gate="readiness",
            status="PASS",
            identity=identity,
            receipt_refs=(ref,),
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")


def verify_successor_readiness_gate(
    *,
    gate: GateExecution,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
) -> GateVerification:
    """Fresh-verify the single global readiness physical receipt."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    _require_gate_shape(
        gate=gate,
        expected="readiness",
        folds=folds,
        prior_gates=prior_gates,
        context=context,
    )
    if len(gate.receipt_refs) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    ref = gate.receipt_refs[0]
    if (
        ref.fold is not None
        or ref.horizon is not None
        or ref.stage != "readiness-evidence"
        or ref.scope != "ACCEPTANCE"
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    fold_request = _canonical_fold_request(
        folds=folds, context=context, fold=context.request.folds[0].fold,
    )
    project_root = context.project_root
    try:
        stage_root = project_stage_root(
            project_root=project_root, config=fold_request.config.config,
        )
        root = stage_root / "acceptance" / "readiness" / ref.scope_key
        verified = apis.readiness_verifier(
            root=root,
            receipt_path=project_root / ref.relative_path,
            project_root=project_root,
            config=fold_request.config.config,
            config_relative=fold_request.config.relative_path,
            release=fold_request.release,
        )
        if verified.report.readiness_key != ref.scope_key:
            raise ValueError
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return GateVerification(
        gate="readiness",
        identity=gate.identity,
        receipt_node_ids=gate.receipt_node_ids,
    )


def run_successor_acceptance_gate(
    *,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
    resume: bool,
) -> GateExecution:
    """Run quality + formal acceptance; one physical acceptance receipt."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    if (
        type(context) is not SuccessorStageContext
        or type(resume) is not bool
        or type(folds) is not tuple
        or len(folds) != 2
        or type(prior_gates) is not tuple
        or len(prior_gates) != 3
        or tuple(item.gate for item in prior_gates)
        != ("summary", "reproducibility", "readiness")
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    readiness_gate = prior_gates[2]
    if len(readiness_gate.receipt_refs) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    readiness_ref = readiness_gate.receipt_refs[0]
    fold_request = _canonical_fold_request(
        folds=folds, context=context, fold=context.request.folds[0].fold,
    )
    project_root = context.project_root
    config = fold_request.config.config
    config_relative = fold_request.config.relative_path
    try:
        from quant.research.m3.acceptance import (
            build_acceptance_evidence_plan,
            resolve_acceptance_subject,
        )
        from quant.research.m3.quality_gate import run_quality_gate
        from quant.research.m3.readiness_evidence import verify_readiness_evidence_artifact

        stage_root = project_stage_root(project_root=project_root, config=config)
        readiness_root = (
            stage_root / "acceptance" / "readiness" / readiness_ref.scope_key
        )
        readiness = verify_readiness_evidence_artifact(
            root=readiness_root,
            receipt_path=project_root / readiness_ref.relative_path,
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            release=fold_request.release,
        )
        if readiness.report.readiness_key != readiness_ref.scope_key:
            raise ValueError
        quality = run_quality_gate(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            resume=resume,
        )
        snapshot_id = folds[0].snapshot_id
        if folds[0].snapshot_id != folds[1].snapshot_id:
            # Shared snapshot stage; both lanes must agree.
            raise ValueError
        subject = resolve_acceptance_subject(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=snapshot_id,
            readiness=readiness,
            python_executable=context.request.toolchain.python_executable,
        )
        plan = build_acceptance_evidence_plan(subject=subject, config=config)
        g8_roots = MappingProxyType({"G8": stage_root})
        result = apis.acceptance_stage(
            subject=subject,
            plan=plan,
            quality=quality,
            config=config,
            artifact_roots=g8_roots,
            resume=resume,
        )
        if result.decision.overall_status != "PASS":
            raise ValueError
        acceptance_key = result.decision.acceptance_key
        if result.receipt.scope_key != acceptance_key:
            raise ValueError
        ref = _stage_receipt_ref(
            receipt_path=result.receipt_path,
            receipt=result.receipt,
            project_root=project_root,
            node=_NodeRef(node_id="acceptance", fold=None, horizon=None),
            artifact_roots=g8_roots,
        )
        if ref.scope_key != acceptance_key or ref.fold is not None:
            raise ValueError
        identity = compute_successor_gate_identity(
            gate="acceptance", folds=folds, prior_gates=prior_gates,
        )
        return GateExecution(
            gate="acceptance",
            status="PASS",
            identity=identity,
            receipt_refs=(ref,),
        )
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")


def verify_successor_acceptance_gate(
    *,
    gate: GateExecution,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
) -> GateVerification:
    """Fresh-audit acceptance decision against the single physical receipt."""

    del runner
    apis = _require_canonical_public_apis(public_apis)
    _require_gate_shape(
        gate=gate,
        expected="acceptance",
        folds=folds,
        prior_gates=prior_gates,
        context=context,
    )
    if len(gate.receipt_refs) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    ref = gate.receipt_refs[0]
    if (
        ref.stage != "acceptance"
        or ref.fold is not None
        or ref.horizon is not None
        or ref.scope != "ACCEPTANCE"
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    fold_request = _canonical_fold_request(
        folds=folds, context=context, fold=context.request.folds[0].fold,
    )
    readiness_gate = next(item for item in prior_gates if item.gate == "readiness")
    if len(readiness_gate.receipt_refs) != 1:
        _fail("SUCCESSOR_GATE_FAILED")
    readiness_ref = readiness_gate.receipt_refs[0]
    project_root = context.project_root
    config = fold_request.config.config
    config_relative = fold_request.config.relative_path
    try:
        from quant.research.m3.acceptance import (
            build_acceptance_evidence_plan,
            resolve_acceptance_subject,
        )
        from quant.research.m3.quality_gate import compute_quality_key, verify_quality_artifact
        from quant.research.m3.readiness_evidence import verify_readiness_evidence_artifact
        from quant.research.m3.run_state import verify_stage_receipt_with_bytes

        stage_root = project_stage_root(project_root=project_root, config=config)
        readiness = verify_readiness_evidence_artifact(
            root=stage_root / "acceptance" / "readiness" / readiness_ref.scope_key,
            receipt_path=project_root / readiness_ref.relative_path,
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            release=fold_request.release,
        )
        subject = resolve_acceptance_subject(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=folds[0].snapshot_id,
            readiness=readiness,
            python_executable=context.request.toolchain.python_executable,
        )
        plan = build_acceptance_evidence_plan(subject=subject, config=config)
        runtime = context.request.runtime_identity
        quality_key = compute_quality_key(
            code_version=runtime.code_version,
            dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
            full_config_sha256=config.full_config_sha256,
        )
        quality = verify_quality_artifact(
            root=stage_root / "acceptance" / "quality" / quality_key,
            receipt_path=stage_root / "receipts" / "quality" / f"{quality_key}.json",
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            artifact_roots=MappingProxyType({"PROJECT": project_root}),
        )
        g8_roots = MappingProxyType({"G8": stage_root})
        decision = apis.acceptance_audit(
            subject=subject,
            plan=plan,
            quality=quality,
            config=config,
            artifact_roots=g8_roots,
        )
        if (
            decision.overall_status != "PASS"
            or decision.acceptance_key != ref.scope_key
        ):
            raise ValueError
        verified = verify_stage_receipt_with_bytes(
            receipt_path=project_root / ref.relative_path,
            artifact_roots=g8_roots,
        )
        if (
            verified is None
            or verified.sha256 != ref.sha256
            or verified.receipt.scope_key != ref.scope_key
        ):
            raise ValueError
    except SuccessorRuntimeError:
        raise
    except Exception:
        _fail("SUCCESSOR_GATE_FAILED")
    return GateVerification(
        gate="acceptance",
        identity=gate.identity,
        receipt_node_ids=gate.receipt_node_ids,
    )


def verify_successor_terminal_gate(
    *,
    gate: GateExecution,
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
    runner: object,
    public_apis: SuccessorPublicApiBundle,
) -> GateVerification:
    """Terminal Gate verifier: re-close identity, priors, and physical refs."""

    del runner
    _require_canonical_public_apis(public_apis)
    if type(gate) is not GateExecution or gate.gate not in {
        "summary", "reproducibility", "readiness", "acceptance",
    }:
        _fail("SUCCESSOR_GATE_FAILED")
    expected_priors = {
        "summary": (),
        "reproducibility": ("summary",),
        "readiness": ("summary", "reproducibility"),
        "acceptance": ("summary", "reproducibility", "readiness"),
    }[gate.gate]
    if tuple(item.gate for item in prior_gates) != expected_priors:
        _fail("SUCCESSOR_GATE_FAILED")
    _require_gate_shape(
        gate=gate,
        expected=gate.gate,
        folds=folds,
        prior_gates=prior_gates,
        context=context,
    )
    # Dispatch to the gate-specific fresh verifier so cache hits still re-check.
    verifiers = {
        "summary": verify_successor_summary_gate,
        "reproducibility": verify_successor_reproducibility_gate,
        "readiness": verify_successor_readiness_gate,
        "acceptance": verify_successor_acceptance_gate,
    }
    return verifiers[gate.gate](
        gate=gate,
        folds=folds,
        prior_gates=prior_gates,
        context=context,
        runner=object(),
        public_apis=public_apis,
    )


def _require_gate_shape(
    *,
    gate: GateExecution,
    expected: Literal["summary", "reproducibility", "readiness", "acceptance"],
    folds: tuple[FoldExecution, ...],
    prior_gates: tuple[GateExecution, ...],
    context: SuccessorStageContext,
) -> None:
    if (
        type(gate) is not GateExecution
        or gate.gate != expected
        or gate.status != "PASS"
        or type(context) is not SuccessorStageContext
        or type(folds) is not tuple
        or len(folds) != 2
        or type(prior_gates) is not tuple
    ):
        _fail("SUCCESSOR_GATE_FAILED")
    identity = compute_successor_gate_identity(
        gate=expected, folds=folds, prior_gates=prior_gates,
    )
    if gate.identity != identity:
        _fail("SUCCESSOR_GATE_FAILED")
    _require_sorted_unique_refs(gate.receipt_refs)


CANONICAL_RUN_FORMAL_STAGE = run_successor_formal_stage
CANONICAL_VERIFY_FOLD = verify_successor_fold
CANONICAL_VERIFY_SUMMARY = verify_successor_summary_gate
CANONICAL_RUN_REPRODUCIBILITY = run_successor_reproducibility_gate
CANONICAL_VERIFY_REPRODUCIBILITY = verify_successor_reproducibility_gate
CANONICAL_RUN_READINESS = run_successor_readiness_gate
CANONICAL_VERIFY_READINESS = verify_successor_readiness_gate
CANONICAL_RUN_ACCEPTANCE = run_successor_acceptance_gate
CANONICAL_VERIFY_ACCEPTANCE = verify_successor_acceptance_gate
CANONICAL_VERIFY_TERMINAL = verify_successor_terminal_gate

__all__ = [
    "run_successor_formal_stage",
    "verify_successor_fold",
    "verify_successor_summary_gate",
    "run_successor_reproducibility_gate",
    "verify_successor_reproducibility_gate",
    "run_successor_readiness_gate",
    "verify_successor_readiness_gate",
    "run_successor_acceptance_gate",
    "verify_successor_acceptance_gate",
    "verify_successor_terminal_gate",
]
