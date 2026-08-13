"""Strict common value objects for M3 final acceptance evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, TypeAlias

from quant.research.m3.run_state import ArtifactDigest, Scope

GateName: TypeAlias = Literal[
    "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"
]
_GATES: tuple[GateName, ...] = (
    "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"
)
_SCOPES = {"GLOBAL", "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "ACCEPTANCE"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


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
    "AcceptanceIssueV1",
    "EvidenceLocatorV1",
    "GateName",
    "GateResultV1",
    "RemoteTrackingObservationV1",
    "VerifiedRuntimeIdentity",
]
