"""Strict shared G9 acceptance value contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from quant.research.m3.acceptance import (
    AcceptanceDecisionV1,
    AcceptanceIssueV1,
    EvidenceLocatorV1,
    GateResultV1,
    RemoteTrackingObservationV1,
    VerifiedRuntimeIdentity,
)
from quant.research.m3.run_state import ArtifactDigest
from quant.research.m3.orchestration import STAGE_SPEC_REGISTRY, get_m3_stage_registry

_HEX = "a" * 64


def test_public_stage_registry_is_single_and_immutable() -> None:
    registry = get_m3_stage_registry()
    assert registry is STAGE_SPEC_REGISTRY
    assert get_m3_stage_registry() is registry
    assert registry["quality"].scope == "ACCEPTANCE"
    with pytest.raises(TypeError):
        registry["hostile"] = registry["quality"]  # type: ignore[index]


def _digest(path: str) -> ArtifactDigest:
    return ArtifactDigest("stage", path, 1, _HEX)


def _pass(gate: str) -> GateResultV1:
    return GateResultV1(gate, "PASS", (), (_digest(f"{gate}/receipt.json"),))  # type: ignore[arg-type]


def test_common_acceptance_values_form_one_canonical_pass_decision() -> None:
    locator = EvidenceLocatorV1(
        "G5", "evaluation.fold_001.h5", "evaluation", "WORK", _HEX,
        "stage", "receipts/evaluation/key.json",
    )
    runtime = VerifiedRuntimeIdentity("code-v1", _HEX, _HEX, _HEX, _HEX)
    observation = RemoteTrackingObservationV1(
        _HEX, _HEX, _HEX, "run-1", "FINISHED", _HEX, _HEX
    )
    gates = tuple(_pass(f"G{index}") for index in range(10))
    decision = AcceptanceDecisionV1(
        "m3-acceptance-report-v1", _HEX, _HEX, _HEX, runtime.code_version,
        runtime.dependency_fingerprint_sha256, observation.tracking_target_key,
        _HEX, gates, "PASS",  # type: ignore[arg-type]
    )

    assert locator.expected_scope_key == _HEX
    assert observation.status == "FINISHED"
    assert decision.overall_status == "PASS"


def test_issue_and_evidence_order_are_exact_and_fail_status_is_derived() -> None:
    first = AcceptanceIssueV1("G5", "A_CODE", "work:aaa", (_digest("a"),))
    second = AcceptanceIssueV1("G5", "B_CODE", "work:bbb", (_digest("b"),))
    failure = GateResultV1("G5", "FAIL", (first, second), (_digest("a"), _digest("b")))
    gates = list(_pass(f"G{index}") for index in range(10))
    gates[5] = failure
    decision = AcceptanceDecisionV1(
        "m3-acceptance-report-v1", _HEX, _HEX, _HEX, "code-v1", _HEX,
        _HEX, _HEX, tuple(gates), "FAIL",  # type: ignore[arg-type]
    )
    assert decision.gate_results[5] is failure

    with pytest.raises(ValueError):
        replace(failure, issues=(second, first))
    with pytest.raises(ValueError):
        replace(failure, evidence=(_digest("b"), _digest("a")))
    with pytest.raises(ValueError):
        replace(failure, status="PASS")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EvidenceLocatorV1("G1", "node", "stage", "WORK", _HEX, "root", "../x"),
        lambda: AcceptanceIssueV1("G1", "CODE", "C:/secret", ()),
        lambda: GateResultV1("G1", "FAIL", (), ()),
        lambda: VerifiedRuntimeIdentity("code", "x" * 64, _HEX, _HEX, _HEX),
        lambda: RemoteTrackingObservationV1(_HEX, _HEX, _HEX, "run", "RUNNING", _HEX, _HEX),
    ],
)
def test_common_contracts_reject_noncanonical_or_unverified_values(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]
