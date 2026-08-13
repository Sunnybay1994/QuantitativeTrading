"""Focused G9B-F0 readiness evidence contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

import quant.research.m3.readiness_evidence as subject
from quant.research.m3.orchestration import get_m3_stage_registry
from quant.research.m3.readiness import ReadinessIssue
from quant.research.m3.readiness_evidence import (
    M3ReadinessEvidenceError,
    ReadinessEvidenceReportV1,
    run_readiness_evidence_stage,
)

_HEX = "a" * 64


def _report(*issues: ReadinessIssue) -> ReadinessEvidenceReportV1:
    return ReadinessEvidenceReportV1(
        schema_version="m3-readiness-evidence-v1",
        readiness_key=_HEX,
        g1_release_id=_HEX,
        g1_release_manifest_sha256=_HEX,
        full_config_sha256=_HEX,
        provider_runtime_fingerprint_sha256=_HEX,
        code_version="code-v1",
        dependency_fingerprint_sha256=_HEX,
        issues=tuple(issues),
    )


def test_readiness_stage_is_in_the_single_immutable_registry() -> None:
    registry = get_m3_stage_registry()
    spec = registry["readiness-evidence"]
    assert spec.scope == "ACCEPTANCE"
    assert tuple(item.relative_path for item in spec.outputs) == (
        "readiness_report.json",
    )
    with pytest.raises(TypeError):
        registry["hostile"] = spec  # type: ignore[index]


def test_readiness_report_requires_canonical_complete_issues() -> None:
    error = ReadinessIssue("A_ERROR", "ERROR", "error")
    warning = ReadinessIssue("B_WARNING", "WARNING", "warning")
    report = _report(error, warning)
    assert report.issues == (error, warning)

    with pytest.raises(M3ReadinessEvidenceError):
        _report(warning, error)
    with pytest.raises(M3ReadinessEvidenceError):
        replace(report, readiness_key="A" * 64)
    with pytest.raises(M3ReadinessEvidenceError):
        _report(ReadinessIssue("", "ERROR", "error"))


def test_public_failure_is_stable_and_has_no_hostile_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = RuntimeError("TOKEN=C:/secret")
    hostile.__cause__ = ValueError("nested")

    def boom(**_kwargs: object) -> object:
        raise hostile

    monkeypatch.setattr(subject, "_run_stage", boom)
    with pytest.raises(M3ReadinessEvidenceError) as caught:
        run_readiness_evidence_stage(
            project_root=Path("."),
            config=object(),  # type: ignore[arg-type]
            config_relative=PurePosixPath("configs/research/example.toml"),
            release=object(),  # type: ignore[arg-type]
        )
    assert str(caught.value) == "M3_READINESS_EVIDENCE_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "TOKEN" not in repr(caught.value)


def test_readiness_report_is_auditable_data_not_verified_authority() -> None:
    report = _report()
    assert report.schema_version == "m3-readiness-evidence-v1"
    assert not hasattr(report, "receipt")
    assert not hasattr(report, "verify_existing")
