"""Strict common value objects for M3 final acceptance evidence."""

from __future__ import annotations

import re
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeAlias, cast

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.formal_cli_resolve import (
    FormalReproducibilityCliResolution,
    resolve_formal_reproducibility_cli_inputs,
)
from quant.research.m3.labels import compute_label_reconciliation_key
from quant.research.m3.model import (
    build_lightgbm_training_spec,
    training_params_sha256,
)
from quant.research.m3.orchestration import get_m3_stage_registry
from quant.research.m3.provider import build_provider_runtime_fingerprint
from quant.research.m3.provider_validation import verify_provider_validation_artifact
from quant.research.m3.quality_gate import compute_quality_key
from quant.research.m3.readiness_evidence import (
    VerifiedReadinessEvidenceArtifact,
    verify_readiness_evidence_artifact,
)
from quant.research.m3.reproducibility import (
    compute_formal_reproducibility_comparison_key,
    verify_formal_reproducibility_artifact,
)
from quant.research.m3.run_state import ArtifactDigest, Scope
from quant.research.m3.run_state import compute_provider_validation_key, compute_work_key
from quant.research.m3.contracts import ProviderValidationSpec

if TYPE_CHECKING:
    from quant.research.m3.acceptance_tracking import TrackingVerifier
    from quant.research.m3.quality_gate import VerifiedQualityArtifact

GateName: TypeAlias = Literal[
    "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"
]
_GATES: tuple[GateName, ...] = (
    "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"
)
_SCOPES = {"SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_FOLD = re.compile(r"^fold_[0-9]{3}$")
_PLAN_CODE = "M3_ACCEPTANCE_PLAN_INVALID"
_AUDIT_CODE = "M3_ACCEPTANCE_AUDIT_INVALID"
_WRITE_CODE = "M3_ACCEPTANCE_WRITE_INVALID"
_ACCEPTANCE_KEY_VERSION = "m3-acceptance-key-v1"


class M3AcceptancePlanError(ValueError):
    """Stable public failure for G9B subject and evidence planning."""

    def __init__(self) -> None:
        super().__init__(_PLAN_CODE)


class M3AcceptanceAuditError(ValueError):
    """Stable public failure for invalid G9F audit caller inputs."""

    def __init__(self) -> None:
        super().__init__(_AUDIT_CODE)


class M3AcceptanceWriteError(ValueError):
    """Stable public failure for invalid or non-PASS acceptance publication."""

    def __init__(self) -> None:
        super().__init__(_WRITE_CODE)


@dataclass(frozen=True)
class EvidenceLocatorV1:
    gate: GateName
    node_id: str
    expected_stage: str
    expected_scope: Scope
    expected_scope_key: str
    root_alias: str
    receipt_relative_path: str

    def __post_init__(self) -> None:
        _require_gate(self.gate)
        _require_token(self.node_id)
        _require_token(self.expected_stage)
        if self.expected_scope not in _SCOPES:
            raise ValueError("invalid evidence scope")
        _require_hex(self.expected_scope_key)
        _require_token(self.root_alias)
        _require_relative(self.receipt_relative_path)


@dataclass(frozen=True)
class AcceptanceIssueV1:
    gate: GateName
    code: str
    subject: str
    evidence: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        _require_gate(self.gate)
        _require_token(self.code)
        _require_subject(self.subject)
        _require_evidence(self.evidence)


@dataclass(frozen=True)
class GateResultV1:
    gate: GateName
    status: Literal["PASS", "FAIL"]
    issues: tuple[AcceptanceIssueV1, ...]
    evidence: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        _require_gate(self.gate)
        if self.status not in {"PASS", "FAIL"} or type(self.issues) is not tuple:
            raise ValueError("invalid gate result")
        if any(type(item) is not AcceptanceIssueV1 or item.gate != self.gate for item in self.issues):
            raise ValueError("invalid gate issues")
        issue_keys = tuple((item.gate, item.code, item.subject) for item in self.issues)
        if issue_keys != tuple(sorted(issue_keys)) or len(issue_keys) != len(set(issue_keys)):
            raise ValueError("gate issues are not canonical")
        if (self.status == "PASS" and self.issues) or (
            self.status == "FAIL" and not self.issues
        ):
            raise ValueError("gate status/issue mismatch")
        _require_evidence(self.evidence)


@dataclass(frozen=True)
class VerifiedRuntimeIdentity:
    code_version: str
    provider_runtime_fingerprint_sha256: str
    dependency_fingerprint_sha256: str
    full_config_sha256: str
    readiness_receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("invalid code version")
        for value in (
            self.provider_runtime_fingerprint_sha256,
            self.dependency_fingerprint_sha256,
            self.full_config_sha256,
            self.readiness_receipt_sha256,
        ):
            _require_hex(value)


@dataclass(frozen=True)
class VerifiedComparisonIdentityV1:
    fold: str
    horizon: int
    work_key: str
    comparison_key: str
    feature_receipt_sha256: str
    label_manifest_sha256: str
    label_receipt_sha256: str
    alignment_receipt_sha256: str
    label_reconciliation_key: str
    python_executable_sha256: str
    reproducibility_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.fold) is not str
            or _FOLD.fullmatch(self.fold) is None
            or type(self.horizon) is not int
            or self.horizon <= 0
        ):
            raise ValueError("invalid comparison identity")
        for value in (
            self.work_key,
            self.comparison_key,
            self.feature_receipt_sha256,
            self.label_manifest_sha256,
            self.label_receipt_sha256,
            self.alignment_receipt_sha256,
            self.label_reconciliation_key,
            self.python_executable_sha256,
            self.reproducibility_receipt_sha256,
        ):
            _require_hex(value)


@dataclass(frozen=True)
class VerifiedAcceptanceSubject:
    snapshot: VerifiedSnapshotArtifact
    provider: VerifiedProviderArtifact
    provider_validation: VerifiedProviderValidationArtifact
    experiment: VerifiedExperimentIdentity
    folds: VerifiedFoldPlanArtifact
    readiness: VerifiedReadinessEvidenceArtifact
    runtime: VerifiedRuntimeIdentity
    comparisons: tuple[VerifiedComparisonIdentityV1, ...]

    def __post_init__(self) -> None:
        exact = (
            (self.snapshot, VerifiedSnapshotArtifact),
            (self.provider, VerifiedProviderArtifact),
            (self.provider_validation, VerifiedProviderValidationArtifact),
            (self.experiment, VerifiedExperimentIdentity),
            (self.folds, VerifiedFoldPlanArtifact),
            (self.readiness, VerifiedReadinessEvidenceArtifact),
            (self.runtime, VerifiedRuntimeIdentity),
        )
        if any(type(value) is not expected for value, expected in exact):
            raise ValueError("invalid acceptance subject")
        if (
            type(self.comparisons) is not tuple
            or not self.comparisons
            or any(
                type(item) is not VerifiedComparisonIdentityV1
                for item in self.comparisons
            )
        ):
            raise ValueError("invalid acceptance comparisons")
        keys = tuple((item.fold, item.horizon) for item in self.comparisons)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("acceptance comparisons are not canonical")

    def __reduce__(self) -> Any:
        raise TypeError(_PLAN_CODE)


@dataclass(frozen=True)
class AcceptanceEvidencePlanV1:
    schema_version: Literal["m3-acceptance-evidence-plan-v1"]
    snapshot_id: str
    provider_key: str
    experiment_key: str
    expected_work_keys: tuple[str, ...]
    expected_comparison_keys: tuple[str, ...]
    evidence: tuple[EvidenceLocatorV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-acceptance-evidence-plan-v1":
            raise ValueError("invalid acceptance plan schema")
        for value in (self.snapshot_id, self.provider_key, self.experiment_key):
            _require_hex(value)
        for values in (self.expected_work_keys, self.expected_comparison_keys):
            if (
                type(values) is not tuple
                or not values
                or values != tuple(sorted(values))
                or len(values) != len(set(values))
            ):
                raise ValueError("invalid acceptance plan identities")
            for value in values:
                _require_hex(value)
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(type(item) is not EvidenceLocatorV1 for item in self.evidence)
        ):
            raise ValueError("invalid acceptance evidence")
        keys = tuple(
            (item.gate, item.node_id, item.receipt_relative_path)
            for item in self.evidence
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("acceptance evidence is not canonical")


def resolve_acceptance_subject(
    *,
    project_root: Path,
    config: LoadedM3Config,
    config_relative: PurePosixPath,
    snapshot_id: str,
    readiness: VerifiedReadinessEvidenceArtifact,
    python_executable: Path,
) -> VerifiedAcceptanceSubject:
    """Freshly resolve one complete G9B subject without scanning artifact trees."""
    result: VerifiedAcceptanceSubject | None = None
    failed = False
    try:
        if (
            type(config) is not LoadedM3Config
            or type(config_relative) is not PurePosixPath
            or type(readiness) is not VerifiedReadinessEvidenceArtifact
            or type(snapshot_id) is not str
            or _HEX64.fullmatch(snapshot_id) is None
        ):
            raise ValueError
        executable = _regular_file(python_executable)
        executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
        horizons_raw = config.section("labels")["horizons_sessions"]
        if type(horizons_raw) is not tuple or not horizons_raw:
            raise ValueError
        horizons = tuple(sorted(cast(tuple[int, ...], horizons_raw)))
        first = resolve_formal_reproducibility_cli_inputs(
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            snapshot_id=snapshot_id,
            fold="fold_001",
            horizon=horizons[0],
        )
        fold_names = tuple(item.name for item in first.folds.manifest.folds)
        if not fold_names:
            raise ValueError
        readiness_receipt = (
            first.stage_root
            / "receipts"
            / "readiness-evidence"
            / f"{readiness.report.readiness_key}.json"
        )
        fresh_readiness = verify_readiness_evidence_artifact(
            root=readiness.root,
            receipt_path=readiness_receipt,
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            release=first.release,
        )
        if fresh_readiness != readiness:
            raise ValueError
        runtime_fp = build_provider_runtime_fingerprint()
        validation_key = compute_provider_validation_key(
            provider_key=first.provider.manifest.provider_key,
            provider_receipt_sha256=first.provider.provider_receipt_sha256,
            provider_validation_config_sha256=config.provider_validation_config_sha256,
            provider_runtime_fingerprint_sha256=runtime_fp.sha256,
            code_version=first.runtime.code_version,
        )
        validation_spec = ProviderValidationSpec(
            provider_validation_key=validation_key,
            provider_validation_config_sha256=config.provider_validation_config_sha256,
            code_version=first.runtime.code_version,
            qlib_version="0.9.7",
            sampling_policy_version="provider_market_stratified_hash_first_last_v1",
            worker_protocol_version="m3-qlib-worker-v1",
        )
        provider_validation = verify_provider_validation_artifact(
            validation_root=first.stage_root / "provider-validations" / validation_key,
            validation_receipt_path=(
                first.stage_root
                / "receipts"
                / "provider-validation"
                / f"{validation_key}.json"
            ),
            snapshot=first.snapshot,
            provider=first.provider,
            config=config,
            spec=validation_spec,
            artifact_roots=first.artifact_roots,
        )
        comparisons: list[VerifiedComparisonIdentityV1] = []
        acceptance = config.section("acceptance")
        score_atol = cast(float, acceptance["reproducibility_score_atol"])
        metric_atol = cast(float, acceptance["reproducibility_metric_atol"])
        params_sha = training_params_sha256(build_lightgbm_training_spec(config))
        for fold in fold_names:
            for horizon in horizons:
                resolution = resolve_formal_reproducibility_cli_inputs(
                    project_root=project_root,
                    config=config,
                    config_relative=config_relative,
                    snapshot_id=snapshot_id,
                    fold=fold,
                    horizon=horizon,
                )
                _require_shared_resolution(first, resolution)
                work_key = compute_work_key(
                    experiment_key=first.experiment.manifest.experiment_key,
                    fold=fold,
                    horizon=horizon,
                )
                if resolution.work_key != work_key:
                    raise ValueError
                comparison_key = compute_formal_reproducibility_comparison_key(
                    work_key=work_key,
                    feature_receipt_sha256=(
                        resolution.feature.feature_receipt_sha256
                    ),
                    label_receipt_sha256=resolution.label.label_receipt_sha256,
                    alignment_receipt_sha256=(
                        resolution.alignment.alignment_receipt_sha256
                    ),
                    params_sha256=params_sha,
                    code_version=resolution.runtime.code_version,
                    dependency_fingerprint_sha256=(
                        resolution.runtime.dependency_fingerprint_sha256
                    ),
                    python_executable_sha256=executable_sha,
                    acceptance_config_sha256=config.acceptance_config_sha256,
                    score_atol=score_atol,
                    metric_atol=metric_atol,
                )
                repro_root = first.stage_root / "repro" / comparison_key
                repro_receipt = (
                    first.stage_root
                    / "receipts"
                    / "reproducibility"
                    / f"{comparison_key}.json"
                )
                verified_repro = verify_formal_reproducibility_artifact(
                    root=repro_root,
                    receipt_path=repro_receipt,
                    artifact_roots=_reproducibility_artifact_roots(project_root),
                    comparison_key=comparison_key,
                    score_atol=score_atol,
                    metric_atol=metric_atol,
                    code_version=resolution.runtime.code_version,
                    dependency_fingerprint_sha256=(
                        resolution.runtime.dependency_fingerprint_sha256
                    ),
                    python_executable_sha256=executable_sha,
                )
                if verified_repro.comparison_key != comparison_key:
                    raise ValueError
                reconciliation_key = compute_label_reconciliation_key(
                    experiment_key=first.experiment.manifest.experiment_key,
                    horizon=horizon,
                    provider_validation_receipt_sha256=(
                        provider_validation.validation_receipt_sha256
                    ),
                    label_manifest_sha256=resolution.label.manifest_sha256,
                    label_reconciliation_config_sha256=(
                        config.label_reconciliation_config_sha256
                    ),
                    dependency_fingerprint_sha256=(
                        resolution.runtime.dependency_fingerprint_sha256
                    ),
                    code_version=resolution.runtime.code_version,
                )
                comparisons.append(VerifiedComparisonIdentityV1(
                    fold=fold,
                    horizon=horizon,
                    work_key=work_key,
                    comparison_key=comparison_key,
                    feature_receipt_sha256=(
                        resolution.feature.feature_receipt_sha256
                    ),
                    label_manifest_sha256=resolution.label.manifest_sha256,
                    label_receipt_sha256=resolution.label.label_receipt_sha256,
                    alignment_receipt_sha256=(
                        resolution.alignment.alignment_receipt_sha256
                    ),
                    label_reconciliation_key=reconciliation_key,
                    python_executable_sha256=executable_sha,
                    reproducibility_receipt_sha256=hashlib.sha256(
                        _regular_file(repro_receipt).read_bytes()
                    ).hexdigest(),
                ))
        runtime = VerifiedRuntimeIdentity(
            code_version=first.runtime.code_version,
            provider_runtime_fingerprint_sha256=runtime_fp.sha256,
            dependency_fingerprint_sha256=(
                first.runtime.dependency_fingerprint_sha256
            ),
            full_config_sha256=config.full_config_sha256,
            readiness_receipt_sha256=fresh_readiness.receipt_sha256,
        )
        if (
            fresh_readiness.report.code_version != runtime.code_version
            or fresh_readiness.report.dependency_fingerprint_sha256
            != runtime.dependency_fingerprint_sha256
            or fresh_readiness.report.full_config_sha256 != runtime.full_config_sha256
            or fresh_readiness.report.provider_runtime_fingerprint_sha256
            != runtime.provider_runtime_fingerprint_sha256
        ):
            raise ValueError
        result = VerifiedAcceptanceSubject(
            snapshot=first.snapshot,
            provider=first.provider,
            provider_validation=provider_validation,
            experiment=first.experiment,
            folds=first.folds,
            readiness=fresh_readiness,
            runtime=runtime,
            comparisons=tuple(comparisons),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _plan_fail()
    return result


def _reproducibility_artifact_roots(project_root: Path) -> Mapping[str, Path]:
    """Return the project-only registry used by formal REPRO receipts."""
    return MappingProxyType({"PROJECT": project_root})


def build_acceptance_evidence_plan(
    *, subject: VerifiedAcceptanceSubject, config: LoadedM3Config
) -> AcceptanceEvidencePlanV1:
    """Build deterministic receipt locators from verified identities only."""
    result: AcceptanceEvidencePlanV1 | None = None
    failed = False
    try:
        if type(subject) is not VerifiedAcceptanceSubject or type(config) is not LoadedM3Config:
            raise ValueError
        experiment_key = subject.experiment.manifest.experiment_key
        snapshot_id = subject.snapshot.manifest.snapshot_id
        provider_key = subject.provider.manifest.provider_key
        horizons = tuple(sorted(cast(tuple[int, ...], config.section("labels")["horizons_sessions"])))
        expected_pairs = tuple(
            (fold.name, horizon)
            for fold in subject.folds.manifest.folds
            for horizon in horizons
        )
        if tuple((item.fold, item.horizon) for item in subject.comparisons) != expected_pairs:
            raise ValueError
        registry = get_m3_stage_registry()
        locators: list[EvidenceLocatorV1] = []

        def add(
            gate: GateName, node_id: str, stage: str, scope: Scope,
            scope_key: str, receipt: str, *, registry_stage: str | None = None,
        ) -> None:
            spec = registry.get(stage if registry_stage is None else registry_stage)
            if spec is None or spec.scope != scope:
                raise ValueError
            locators.append(EvidenceLocatorV1(
                gate, node_id, stage, scope, scope_key, "G8", receipt
            ))

        add(
            "G0", "readiness-evidence", "readiness-evidence", "ACCEPTANCE",
            subject.readiness.report.readiness_key,
            f"receipts/readiness-evidence/{subject.readiness.report.readiness_key}.json",
        )
        add(
            "G1", "snapshot", "snapshot", "SNAPSHOT",
            subject.snapshot.request.snapshot_request_key,
            f"receipts/snapshot/{subject.snapshot.request.snapshot_request_key}.json",
        )
        add(
            "G2", "provider", "provider", "PROVIDER", provider_key,
            f"receipts/provider/{provider_key}.json",
        )
        validation_key = subject.provider_validation.summary.provider_validation_key
        add(
            "G2", "provider-validation", "provider-validation", "PROVIDER",
            validation_key, f"receipts/provider-validation/{validation_key}.json",
        )
        add(
            "G4", "experiment", "experiment-identity", "EXPERIMENT",
            experiment_key, f"receipts/experiment-identity/{experiment_key}.json",
        )
        add(
            "G4", "folds", "folds", "EXPERIMENT", experiment_key,
            f"receipts/folds/{experiment_key}.json",
        )
        seen_horizons: set[int] = set()
        for item in subject.comparisons:
            if item.horizon not in seen_horizons:
                seen_horizons.add(item.horizon)
                add(
                    "G3", f"labels.h{item.horizon}", "labels", "EXPERIMENT",
                    experiment_key,
                    f"receipts/labels/{experiment_key}-h{item.horizon}.json",
                )
                add(
                    "G3", f"label-reconciliation.h{item.horizon}",
                    "label-reconciliation", "EXPERIMENT",
                    item.label_reconciliation_key,
                    f"receipts/label-reconciliation/{item.label_reconciliation_key}.json",
                )
                lightgbm = cast(
                    Mapping[str, object], config.section("model")["lightgbm"]
                )
                model_version = cast(str, lightgbm["model_version"])
                identity = f"h{item.horizon}.lightgbm.{model_version}"
                add(
                    "G6", f"summary.{identity}", "research-summary", "EXPERIMENT",
                    experiment_key,
                    f"receipts/research-summary/{experiment_key}.{identity}.json",
                )
            add(
                "G5", f"features.{item.fold}", "features", "EXPERIMENT",
                experiment_key,
                f"receipts/features/{experiment_key}.{item.fold}.json",
            )
            for gate, stage, registry_stage in (
                ("G5", "alignment", "alignment"),
                ("G5", "train", "train"),
                ("G5", "predictions", "predictions"),
                ("G6", "evaluation", "evaluation"),
                ("G7", "targets", "targets"),
                ("G7", "backtest-plan", "backtest_plan"),
                ("G7", "backtest", "backtest"),
                ("G8", "tracking", "tracking"),
            ):
                add(
                    cast(GateName, gate), f"{stage}.{item.fold}.h{item.horizon}",
                    stage, "WORK", item.work_key,
                    f"receipts/{stage}/{item.work_key}.json",
                    registry_stage=registry_stage,
                )
            add(
                "G5", f"reproducibility.{item.fold}.h{item.horizon}",
                "reproducibility", "REPRO", item.comparison_key,
                f"receipts/reproducibility/{item.comparison_key}.json",
            )
        quality_key = compute_quality_key(
            code_version=subject.runtime.code_version,
            dependency_fingerprint_sha256=(
                subject.runtime.dependency_fingerprint_sha256
            ),
            full_config_sha256=subject.runtime.full_config_sha256,
        )
        add(
            "G9", "quality", "quality", "ACCEPTANCE", quality_key,
            f"receipts/quality/{quality_key}.json",
        )
        evidence = tuple(sorted(
            set(locators),
            key=lambda item: (item.gate, item.node_id, item.receipt_relative_path),
        ))
        result = AcceptanceEvidencePlanV1(
            schema_version="m3-acceptance-evidence-plan-v1",
            snapshot_id=snapshot_id,
            provider_key=provider_key,
            experiment_key=experiment_key,
            expected_work_keys=tuple(sorted(item.work_key for item in subject.comparisons)),
            expected_comparison_keys=tuple(
                sorted(item.comparison_key for item in subject.comparisons)
            ),
            evidence=evidence,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _plan_fail()
    return result


def _require_shared_resolution(
    first: FormalReproducibilityCliResolution,
    current: FormalReproducibilityCliResolution,
) -> None:
    if (
        type(current) is not FormalReproducibilityCliResolution
        or current.stage_root != first.stage_root
        or current.config != first.config
        or current.runtime != first.runtime
        or current.release != first.release
        or current.snapshot != first.snapshot
        or current.provider != first.provider
        or current.experiment != first.experiment
        or current.folds != first.folds
    ):
        raise ValueError


def _regular_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError
    return resolved


def _plan_fail() -> NoReturn:
    raise M3AcceptancePlanError() from None


def _audit_fail() -> NoReturn:
    error = M3AcceptanceAuditError()
    error.__cause__ = None
    error.__context__ = None
    raise error from None


def _write_fail() -> NoReturn:
    error = M3AcceptanceWriteError()
    error.__cause__ = None
    error.__context__ = None
    raise error from None


@dataclass(frozen=True)
class RemoteTrackingObservationV1:
    work_key: str
    tracking_target_key: str
    tracking_key: str
    run_id: str
    status: Literal["FINISHED"]
    request_sha256: str
    artifact_digest_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.work_key,
            self.tracking_target_key,
            self.tracking_key,
            self.request_sha256,
            self.artifact_digest_sha256,
        ):
            _require_hex(value)
        _require_token(self.run_id)
        if self.status != "FINISHED":
            raise ValueError("invalid tracking status")


@dataclass(frozen=True)
class AcceptanceDecisionV1:
    schema_version: Literal["m3-acceptance-report-v1"]
    acceptance_key: str
    experiment_key: str
    acceptance_config_sha256: str
    code_version: str
    dependency_fingerprint_sha256: str
    tracking_target_key: str
    tracking_observations_sha256: str
    gate_results: tuple[GateResultV1, ...]
    overall_status: Literal["PASS", "FAIL"]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-acceptance-report-v1":
            raise ValueError("invalid acceptance schema")
        for value in (
            self.acceptance_key,
            self.experiment_key,
            self.acceptance_config_sha256,
            self.dependency_fingerprint_sha256,
            self.tracking_target_key,
            self.tracking_observations_sha256,
        ):
            _require_hex(value)
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("invalid acceptance code version")
        if (
            type(self.gate_results) is not tuple
            or tuple(item.gate for item in self.gate_results) != _GATES
            or any(type(item) is not GateResultV1 for item in self.gate_results)
        ):
            raise ValueError("invalid acceptance gate closure")
        expected = (
            "PASS"
            if all(item.status == "PASS" for item in self.gate_results)
            else "FAIL"
        )
        if self.overall_status != expected:
            raise ValueError("invalid acceptance overall status")


def compute_acceptance_key(
    *,
    experiment_key: str,
    acceptance_config_sha256: str,
    tracking_target_key: str,
    quality_receipt_sha256: str,
    tracking_observations_sha256: str,
    required_receipt_sha256s: tuple[str, ...],
) -> str:
    """Return the sole identity for one exact acceptance evidence closure."""

    for value in (
        experiment_key,
        acceptance_config_sha256,
        tracking_target_key,
        quality_receipt_sha256,
        tracking_observations_sha256,
    ):
        _require_hex(value)
    if (
        type(required_receipt_sha256s) is not tuple
        or not required_receipt_sha256s
    ):
        raise ValueError(_AUDIT_CODE)
    for value in required_receipt_sha256s:
        _require_hex(value)
    return hashlib.sha256(
        _canonical_bytes(
            [
                _ACCEPTANCE_KEY_VERSION,
                experiment_key,
                acceptance_config_sha256,
                tracking_target_key,
                quality_receipt_sha256,
                tracking_observations_sha256,
                list(required_receipt_sha256s),
            ]
        )
    ).hexdigest()


def audit_m3_acceptance(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    tracking_verifier: TrackingVerifier,
) -> AcceptanceDecisionV1:
    """Aggregate G0-G9 from the three strict checkers and no caller gate input."""

    result: AcceptanceDecisionV1 | None = None
    failed = False
    try:
        from quant.research.m3.acceptance_tracking import (
            audit_acceptance_tracking,
        )
        from quant.research.m3.acceptance_upstream import audit_acceptance_upstream
        from quant.research.m3.acceptance_work import audit_acceptance_work
        from quant.research.m3.quality_gate import VerifiedQualityArtifact
        from quant.research.m3.run_state import verify_stage_receipt_with_bytes

        if (
            type(subject) is not VerifiedAcceptanceSubject
            or type(plan) is not AcceptanceEvidencePlanV1
            or type(quality) is not VerifiedQualityArtifact
            or type(config) is not LoadedM3Config
            or not isinstance(artifact_roots, Mapping)
            or not artifact_roots
            or not callable(tracking_verifier)
            or plan != build_acceptance_evidence_plan(subject=subject, config=config)
        ):
            raise ValueError
        upstream = audit_acceptance_upstream(
            subject=subject,
            plan=plan,
            config=config,
            artifact_roots=artifact_roots,
        )
        work = audit_acceptance_work(
            subject=subject,
            plan=plan,
            config=config,
            artifact_roots=artifact_roots,
        )
        tracking = audit_acceptance_tracking(
            subject=subject,
            plan=plan,
            quality=quality,
            config=config,
            artifact_roots=artifact_roots,
            tracking_verifier=tracking_verifier,
        )
        gate_results = (*upstream, *work, *tracking.gate_results)
        if (
            len(gate_results) != 10
            or tuple(item.gate for item in gate_results) != _GATES
        ):
            raise ValueError
        receipt_hashes: list[str] = []
        for locator in plan.evidence:
            root = artifact_roots[locator.root_alias]
            receipt_path = root.joinpath(
                *PurePosixPath(locator.receipt_relative_path).parts
            )
            receipt = verify_stage_receipt_with_bytes(
                receipt_path=receipt_path,
                artifact_roots=artifact_roots,
            )
            if (
                receipt is None
                or
                receipt.receipt.stage != locator.expected_stage
                or receipt.receipt.scope != locator.expected_scope
                or receipt.receipt.scope_key != locator.expected_scope_key
            ):
                raise ValueError
            receipt_hashes.append(receipt.sha256)
        acceptance_key = compute_acceptance_key(
            experiment_key=subject.experiment.manifest.experiment_key,
            acceptance_config_sha256=config.acceptance_config_sha256,
            tracking_target_key=config.tracking_target_key,
            quality_receipt_sha256=quality.receipt_sha256,
            tracking_observations_sha256=(
                tracking.tracking_observations_sha256
            ),
            required_receipt_sha256s=tuple(receipt_hashes),
        )
        result = AcceptanceDecisionV1(
            schema_version="m3-acceptance-report-v1",
            acceptance_key=acceptance_key,
            experiment_key=subject.experiment.manifest.experiment_key,
            acceptance_config_sha256=config.acceptance_config_sha256,
            code_version=subject.runtime.code_version,
            dependency_fingerprint_sha256=(
                subject.runtime.dependency_fingerprint_sha256
            ),
            tracking_target_key=config.tracking_target_key,
            tracking_observations_sha256=(
                tracking.tracking_observations_sha256
            ),
            gate_results=cast(tuple[GateResultV1, ...], gate_results),
            overall_status=(
                "PASS"
                if all(item.status == "PASS" for item in gate_results)
                else "FAIL"
            ),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _audit_fail()
    return result


def write_acceptance_candidate(
    *, decision: AcceptanceDecisionV1, temp_output_root: Path
) -> ArtifactDigest:
    """Write the sole canonical PASS report into an already-empty temp root."""

    result: ArtifactDigest | None = None
    failed = False
    try:
        if (
            type(decision) is not AcceptanceDecisionV1
            or decision.overall_status != "PASS"
            or not isinstance(temp_output_root, Path)
            or not temp_output_root.is_absolute()
            or temp_output_root.is_symlink()
        ):
            raise ValueError
        root = temp_output_root.resolve(strict=True)
        root_stat = os.lstat(root)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or bool(getattr(root_stat, "st_file_attributes", 0) & 0x400)
            or any(root.iterdir())
        ):
            raise ValueError
        raw = _canonical_bytes(asdict(decision))
        path = root / "acceptance_report.json"
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != raw:
            raise ValueError
        result = ArtifactDigest(
            root_alias="ACCEPTANCE",
            relative_path="acceptance_report.json",
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _write_fail()
    return result


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _require_gate(value: object) -> None:
    if value not in _GATES:
        raise ValueError("invalid gate")


def _require_hex(value: object) -> None:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError("invalid sha256")


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError("invalid token")


def _require_subject(value: object) -> None:
    _require_token(value)
    assert type(value) is str
    if not any(value.startswith(prefix) for prefix in ("work:", "horizon:", "node:", "global:")):
        raise ValueError("invalid issue subject")


def _require_relative(value: object) -> None:
    if type(value) is not str or "\\" in value:
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid relative path")


def _require_evidence(value: object) -> None:
    if type(value) is not tuple or any(type(item) is not ArtifactDigest for item in value):
        raise ValueError("invalid evidence")
    keys = tuple((item.root_alias, item.relative_path) for item in value)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("evidence is not canonical")


__all__ = [
    "AcceptanceDecisionV1",
    "AcceptanceEvidencePlanV1",
    "AcceptanceIssueV1",
    "EvidenceLocatorV1",
    "GateName",
    "GateResultV1",
    "M3AcceptancePlanError",
    "M3AcceptanceAuditError",
    "M3AcceptanceWriteError",
    "RemoteTrackingObservationV1",
    "VerifiedAcceptanceSubject",
    "VerifiedComparisonIdentityV1",
    "VerifiedRuntimeIdentity",
    "audit_m3_acceptance",
    "build_acceptance_evidence_plan",
    "compute_acceptance_key",
    "resolve_acceptance_subject",
    "write_acceptance_candidate",
]
