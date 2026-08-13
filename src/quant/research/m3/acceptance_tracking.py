"""G9E checks for remote tracking and bounded local safety evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, Protocol, cast

from quant.research.m3.acceptance import (
    AcceptanceEvidencePlanV1,
    AcceptanceIssueV1,
    GateResultV1,
    RemoteTrackingObservationV1,
    VerifiedAcceptanceSubject,
    build_acceptance_evidence_plan,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.quality_gate import (
    VerifiedQualityArtifact,
    verify_quality_artifact,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    VerifiedStageReceipt,
    path_for_artifact_digest,
    verify_stage_receipt_with_bytes,
)
from quant.research.m3.tracking import (
    TrackingMarkerV1,
    TrackingRequestV1,
    read_tracking_marker,
    read_tracking_request,
)

_CODE = "M3_ACCEPTANCE_TRACKING_INVALID"
_GATES: tuple[Literal["G8", "G9"], ...] = ("G8", "G9")
_MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_TEXT_BYTES = 32 * 1024 * 1024
_ABSOLUTE = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:home|mnt|users|tmp|var|opt)/)")
_SECRET = re.compile(
    r"(?i)(?:(?:password|passwd|secret|api[_-]?key|access[_-]?token)"
    r"(?:[\"']|\s)*[:=]|bearer\s+)"
)


class M3AcceptanceTrackingError(ValueError):
    """Stable, redacted public failure for invalid G9E caller inputs."""

    def __init__(self) -> None:
        super().__init__(_CODE)


class TrackingVerifier(Protocol):
    """Injected read-only remote verification boundary used by G9E/G9F."""

    def __call__(
        self, *, marker: TrackingMarkerV1, request: TrackingRequestV1
    ) -> RemoteTrackingObservationV1: ...


@dataclass(frozen=True)
class AcceptanceTrackingAuditV1:
    gate_results: tuple[GateResultV1, GateResultV1]
    observations: tuple[RemoteTrackingObservationV1, ...]
    tracking_observations_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.gate_results) is not tuple
            or len(self.gate_results) != 2
            or tuple(item.gate for item in self.gate_results) != _GATES
            or any(type(item) is not GateResultV1 for item in self.gate_results)
            or type(self.observations) is not tuple
            or any(
                type(item) is not RemoteTrackingObservationV1
                for item in self.observations
            )
            or tuple(item.work_key for item in self.observations)
            != tuple(sorted(item.work_key for item in self.observations))
            or len({item.work_key for item in self.observations})
            != len(self.observations)
            or not _is_hex64(self.tracking_observations_sha256)
            or self.tracking_observations_sha256
            != _observations_sha256(self.observations)
        ):
            raise ValueError(_CODE)


def audit_acceptance_tracking(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    tracking_verifier: TrackingVerifier,
) -> AcceptanceTrackingAuditV1:
    """Audit G8/G9 without importing MLflow or scanning unplanned directories."""

    result: AcceptanceTrackingAuditV1 | None = None
    failed = False
    try:
        _validate_inputs(
            subject,
            plan,
            quality,
            config,
            artifact_roots,
            tracking_verifier,
        )
        issues: dict[str, list[AcceptanceIssueV1]] = {gate: [] for gate in _GATES}
        evidence: dict[str, list[ArtifactDigest]] = {gate: [] for gate in _GATES}
        observations = _audit_tracking(
            subject=subject,
            plan=plan,
            config=config,
            artifact_roots=artifact_roots,
            tracking_verifier=tracking_verifier,
            issues=issues["G8"],
            evidence=evidence["G8"],
        )
        _audit_quality_and_safety(
            subject=subject,
            plan=plan,
            quality=quality,
            config=config,
            artifact_roots=artifact_roots,
            issues=issues["G9"],
            evidence=evidence["G9"],
        )
        canonical_observations = tuple(
            sorted(observations, key=lambda item: item.work_key)
        )
        result = AcceptanceTrackingAuditV1(
            gate_results=(
                _gate_result("G8", issues["G8"], evidence["G8"]),
                _gate_result("G9", issues["G9"], evidence["G9"]),
            ),
            observations=canonical_observations,
            tracking_observations_sha256=_observations_sha256(
                canonical_observations
            ),
        )
    except Exception:
        failed = True
    if failed or result is None:
        _fail()
    return result


def _validate_inputs(
    subject: object,
    plan: object,
    quality: object,
    config: object,
    artifact_roots: object,
    tracking_verifier: object,
) -> None:
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
    for alias, root in artifact_roots.items():
        if type(alias) is not str or not alias or not isinstance(root, Path):
            raise ValueError


def _audit_tracking(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    tracking_verifier: TrackingVerifier,
    issues: list[AcceptanceIssueV1],
    evidence: list[ArtifactDigest],
) -> list[RemoteTrackingObservationV1]:
    observations: list[RemoteTrackingObservationV1] = []
    expected_work_keys = {item.work_key for item in subject.comparisons}
    locators = tuple(item for item in plan.evidence if item.gate == "G8")
    if len(locators) != len(expected_work_keys):
        issues.append(_issue("G8", "TRACKING_COVERAGE_INVALID", "global:tracking"))
    seen: set[str] = set()
    for locator in locators:
        work_key = locator.expected_scope_key
        logical_subject = f"work:{work_key}"
        try:
            if (
                locator.expected_stage != "tracking"
                or locator.expected_scope != "WORK"
                or work_key not in expected_work_keys
                or work_key in seen
            ):
                raise ValueError
            seen.add(work_key)
            receipt = _verify_locator(locator, artifact_roots)
            request_digest = _single_output(receipt, "tracking_request.json")
            marker_digest = _single_output(receipt, "tracking_marker.json")
            request = read_tracking_request(_path(request_digest, artifact_roots))
            marker = read_tracking_marker(_path(marker_digest, artifact_roots))
            if (
                request.work_key != work_key
                or request.tracking_target_key != config.tracking_target_key
                or marker.tracking_target_key != config.tracking_target_key
            ):
                raise ValueError
            observation = tracking_verifier(marker=marker, request=request)
            if (
                type(observation) is not RemoteTrackingObservationV1
                or observation.work_key != work_key
                or observation.tracking_target_key != config.tracking_target_key
                or observation.tracking_key != marker.tracking_key
                or observation.run_id != marker.mlflow_run_id
                or observation.status != "FINISHED"
                or observation.request_sha256 != marker.request_sha256
                or observation.artifact_digest_sha256
                != marker.artifact_digest_sha256
            ):
                raise ValueError
            observations.append(observation)
            evidence.extend((
                ArtifactDigest(
                    locator.root_alias,
                    locator.receipt_relative_path,
                    len(receipt.raw),
                    receipt.sha256,
                ),
                request_digest,
                marker_digest,
            ))
        except Exception:
            issues.append(_issue("G8", "TRACKING_REMOTE_INVALID", logical_subject))
    if seen != expected_work_keys:
        issues.append(_issue("G8", "TRACKING_COVERAGE_INVALID", "global:tracking"))
    return observations


def _audit_quality_and_safety(
    *,
    subject: VerifiedAcceptanceSubject,
    plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
    issues: list[AcceptanceIssueV1],
    evidence: list[ArtifactDigest],
) -> None:
    try:
        locator = next(
            item
            for item in plan.evidence
            if item.gate == "G9" and item.node_id == "quality"
        )
        if sum(1 for item in plan.evidence if item.gate == "G9") != 1:
            raise ValueError
        receipt = _verify_locator(locator, artifact_roots)
        project_root, config_relative = _project_config(
            subject, config, artifact_roots
        )
        fresh = verify_quality_artifact(
            root=_path(quality.report_digest, artifact_roots).parent,
            receipt_path=artifact_roots[locator.root_alias].joinpath(
                *PurePosixPath(locator.receipt_relative_path).parts
            ),
            project_root=project_root,
            config=config,
            config_relative=config_relative,
            artifact_roots=artifact_roots,
        )
        if (
            fresh != quality
            or receipt.receipt != quality.receipt
            or receipt.sha256 != quality.receipt_sha256
            or quality.report.code_version != subject.runtime.code_version
            or quality.report.dependency_fingerprint_sha256
            != subject.runtime.dependency_fingerprint_sha256
            or quality.report.passed is not True
            or quality.report_digest not in receipt.receipt.outputs
        ):
            raise ValueError
        evidence.extend((
            ArtifactDigest(
                locator.root_alias,
                locator.receipt_relative_path,
                len(receipt.raw),
                receipt.sha256,
            ),
            quality.report_digest,
        ))
    except Exception:
        issues.append(_issue("G9", "QUALITY_INVALID", "global:quality"))

    try:
        _bounded_safety_scan(plan=plan, artifact_roots=artifact_roots)
    except Exception:
        issues.append(_issue("G9", "SAFETY_SCAN_INVALID", "global:safety"))


def _bounded_safety_scan(
    *,
    plan: AcceptanceEvidencePlanV1,
    artifact_roots: Mapping[str, Path],
) -> None:
    total = 0
    seen: set[tuple[str, str]] = set()
    for locator in plan.evidence:
        receipt = _verify_locator(locator, artifact_roots)
        total = _scan_text(receipt.raw, total)
        for digest in receipt.receipt.outputs:
            name = PurePosixPath(digest.relative_path).name.casefold()
            if not (
                name.endswith(".log")
                or "manifest" in name
                or "report" in name
                or name in {"tracking_request.json", "tracking_marker.json"}
            ):
                continue
            key = (digest.root_alias, digest.relative_path)
            if key in seen:
                continue
            seen.add(key)
            raw = _path(digest, artifact_roots).read_bytes()
            if len(raw) != digest.size_bytes or hashlib.sha256(raw).hexdigest() != digest.sha256:
                raise ValueError
            total = _scan_text(raw, total)


def _scan_text(raw: bytes, total: int) -> int:
    if len(raw) > _MAX_TEXT_FILE_BYTES or total + len(raw) > _MAX_TOTAL_TEXT_BYTES:
        raise ValueError
    text = raw.decode("utf-8", "strict")
    if "\x00" in text or _ABSOLUTE.search(text) or _SECRET.search(text):
        raise ValueError
    return total + len(raw)


def _project_config(
    subject: VerifiedAcceptanceSubject,
    config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> tuple[Path, PurePosixPath]:
    matches = tuple(
        item
        for item in subject.readiness.receipt.inputs
        if item.sha256 == config.raw_config_sha256
        and PurePosixPath(item.relative_path).parts
        and PurePosixPath(item.relative_path).parts[0] == "configs"
    )
    if len(matches) != 1:
        raise ValueError
    digest = matches[0]
    return artifact_roots[digest.root_alias], PurePosixPath(digest.relative_path)


def _verify_locator(
    locator: object,
    artifact_roots: Mapping[str, Path],
) -> VerifiedStageReceipt:
    root_alias = cast(str, getattr(locator, "root_alias"))
    relative = cast(str, getattr(locator, "receipt_relative_path"))
    verified = verify_stage_receipt_with_bytes(
        receipt_path=artifact_roots[root_alias].joinpath(
            *PurePosixPath(relative).parts
        ),
        artifact_roots=artifact_roots,
    )
    if verified is None:
        raise ValueError
    receipt = verified.receipt
    if (
        receipt.stage != getattr(locator, "expected_stage")
        or receipt.scope != getattr(locator, "expected_scope")
        or receipt.scope_key != getattr(locator, "expected_scope_key")
    ):
        raise ValueError
    return verified


def _single_output(
    receipt: VerifiedStageReceipt, filename: str
) -> ArtifactDigest:
    matches = tuple(
        item
        for item in receipt.receipt.outputs
        if PurePosixPath(item.relative_path).name == filename
    )
    if len(matches) != 1 or len(receipt.receipt.outputs) != 2:
        raise ValueError
    return matches[0]


def _path(digest: ArtifactDigest, roots: Mapping[str, Path]) -> Path:
    return path_for_artifact_digest(digest, artifact_roots=roots)


def _issue(gate: Literal["G8", "G9"], code: str, subject: str) -> AcceptanceIssueV1:
    return AcceptanceIssueV1(gate, code, subject, ())


def _gate_result(
    gate: Literal["G8", "G9"],
    issues: list[AcceptanceIssueV1],
    evidence: list[ArtifactDigest],
) -> GateResultV1:
    canonical_issues = tuple(
        sorted(set(issues), key=lambda item: (item.gate, item.code, item.subject))
    )
    canonical_evidence = tuple(
        sorted(set(evidence), key=lambda item: (item.root_alias, item.relative_path))
    )
    return GateResultV1(
        gate,
        "FAIL" if canonical_issues else "PASS",
        canonical_issues,
        canonical_evidence,
    )


def _observations_sha256(
    observations: tuple[RemoteTrackingObservationV1, ...],
) -> str:
    raw = json.dumps(
        [asdict(item) for item in observations],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail() -> NoReturn:
    error = M3AcceptanceTrackingError()
    error.__cause__ = None
    error.__context__ = None
    raise error from None


__all__ = [
    "AcceptanceTrackingAuditV1",
    "M3AcceptanceTrackingError",
    "TrackingVerifier",
    "audit_acceptance_tracking",
]
