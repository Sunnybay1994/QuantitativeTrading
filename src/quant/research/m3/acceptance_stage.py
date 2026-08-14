"""PASS-only G9F acceptance StageRunner publication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from quant.research.m3.acceptance import (
    AcceptanceDecisionV1,
    AcceptanceEvidencePlanV1,
    VerifiedAcceptanceSubject,
    audit_m3_acceptance,
    write_acceptance_candidate,
)
from quant.research.m3.acceptance_tracking import TrackingVerifier
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.orchestration import (
    ACCEPTANCE_STAGE_SPEC,
    ExternalInput,
    StageBuildReport,
    StageContext,
    StageNode,
    StageRunner,
    StaticDirectoryPublication,
)
from quant.research.m3.quality_gate import VerifiedQualityArtifact
from quant.research.m3.run_state import (
    ArtifactDigest,
    StageReceipt,
    select_artifact_root,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.tracking import (
    create_mlflow_tracking_client,
    verify_tracking_remote,
)

_ERROR = "M3_ACCEPTANCE_STAGE_INVALID"


@dataclass(frozen=True)
class FormalAcceptanceStageResult:
    final_root: Path
    receipt_path: Path
    decision: AcceptanceDecisionV1
    receipt: StageReceipt
    reused: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.final_root, Path)
            or not isinstance(self.receipt_path, Path)
            or type(self.decision) is not AcceptanceDecisionV1
            or self.decision.overall_status != "PASS"
            or type(self.receipt) is not StageReceipt
            or type(self.reused) is not bool
        ):
            raise ValueError(_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_ERROR)


def run_formal_acceptance_stage(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    resume: bool = True,
) -> FormalAcceptanceStageResult:
    """Use the production read-only tracking boundary and publish one PASS report."""

    return _run_formal_acceptance_stage(
        subject=subject,
        plan=plan,
        quality=quality,
        config=config,
        artifact_roots=artifact_roots,
        tracking_verifier=_production_tracking_verifier(config),
        resume=resume,
    )


def audit_formal_m3_acceptance(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> AcceptanceDecisionV1:
    """Run G9F with the production read-only tracking verifier."""

    return audit_m3_acceptance(
        subject=subject,
        plan=plan,
        quality=quality,
        config=config,
        artifact_roots=artifact_roots,
        tracking_verifier=_production_tracking_verifier(config),
    )


def _production_tracking_verifier(config: LoadedM3Config) -> TrackingVerifier:
    try:
        if type(config) is not LoadedM3Config:
            raise ValueError
        experiment_name = config.section("tracking")["experiment_name"]
        if type(experiment_name) is not str or not experiment_name:
            raise ValueError
        client = create_mlflow_tracking_client(
            tracking_uri=config.canonical_tracking_uri
        )

        def remote(*, marker: Any, request: Any) -> Any:
            return verify_tracking_remote(
                marker=marker,
                request=request,
                experiment_name=experiment_name,
                client=client,
            )

        return remote
    except Exception:
        pass
    raise ValueError(_ERROR) from None


def _run_formal_acceptance_stage(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    tracking_verifier: TrackingVerifier,
    resume: bool,
) -> FormalAcceptanceStageResult:
    """Private testable core after the production tracking boundary is fixed."""

    try:
        decision = audit_m3_acceptance(
            subject=subject,
            plan=plan,
            quality=quality,
            config=config,
            artifact_roots=artifact_roots,
            tracking_verifier=tracking_verifier,
        )
        if decision.overall_status != "PASS" or type(resume) is not bool:
            raise ValueError
        stage_root = artifact_roots["G8"].resolve(strict=True)
        node = _plan_node(
            decision=decision,
            plan=plan,
            artifact_roots=artifact_roots,
        )
        expected_raw = _canonical_bytes(asdict(decision))

        def handler(context: StageContext) -> StageBuildReport:
            digest = write_acceptance_candidate(
                decision=decision,
                temp_output_root=context.temp_output_root,
            )
            if digest.relative_path != "acceptance_report.json":
                raise ValueError
            return StageBuildReport(("acceptance_report.json",))

        def closure(root: Path) -> None:
            path = root / "acceptance_report.json"
            if path.read_bytes() != expected_raw or tuple(
                item.name for item in root.iterdir()
            ) != ("acceptance_report.json",):
                raise ValueError

        static = StageRunner(
            stage_root=stage_root,
            artifact_roots=artifact_roots,
            config=config,
        ).run_static(
            node=node,
            handler=handler,
            closure_verifier=closure,
            resume=resume,
        )
        verified = verify_stage_receipt_with_bytes(
            receipt_path=static.receipt_path,
            artifact_roots=artifact_roots,
        )
        if (
            verified is None
            or verified.receipt != static.receipt
            or verified.receipt.stage != "acceptance"
            or verified.receipt.scope != "ACCEPTANCE"
            or verified.receipt.scope_key != decision.acceptance_key
            or len(verified.receipt.outputs) != 1
            or verified.receipt.outputs[0].sha256
            != hashlib.sha256(expected_raw).hexdigest()
        ):
            raise ValueError
        closure(static.final_root)
        return FormalAcceptanceStageResult(
            static.final_root,
            static.receipt_path,
            decision,
            static.receipt,
            static.reused,
        )
    except Exception:
        pass
    raise ValueError(_ERROR) from None


def _plan_node(
    *,
    decision: AcceptanceDecisionV1,
    plan: AcceptanceEvidencePlanV1,
    artifact_roots: Mapping[str, Path],
) -> StageNode:
    inputs: list[ExternalInput] = []
    for locator in plan.evidence:
        path = artifact_roots[locator.root_alias].joinpath(
            *PurePosixPath(locator.receipt_relative_path).parts
        )
        raw = path.read_bytes()
        alias, root = select_artifact_root(path, artifact_roots=artifact_roots)
        inputs.append(ExternalInput(ArtifactDigest(
            alias,
            path.resolve(strict=True).relative_to(root).as_posix(),
            len(raw),
            hashlib.sha256(raw).hexdigest(),
        )))
    ordered = tuple(
        sorted(inputs, key=lambda item: (
            item.artifact.root_alias, item.artifact.relative_path
        ))
    )
    if len(ordered) != len(plan.evidence):
        raise ValueError
    return StageNode(
        node_id=f"acceptance-{decision.acceptance_key[:16]}",
        spec_name=ACCEPTANCE_STAGE_SPEC.name,
        scope="ACCEPTANCE",
        scope_key=decision.acceptance_key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=ordered,
        publication=StaticDirectoryPublication(
            f"acceptance/final/{decision.acceptance_key}"
        ),
        output_specs=ACCEPTANCE_STAGE_SPEC.outputs,
        receipt_path=f"receipts/acceptance/{decision.acceptance_key}.json",
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "FormalAcceptanceStageResult",
    "audit_formal_m3_acceptance",
    "run_formal_acceptance_stage",
]
