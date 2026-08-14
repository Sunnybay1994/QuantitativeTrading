"""Focused G9F acceptance aggregation, identity, and PASS-only writer tests."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from quant.research.m3.acceptance import (
    GateResultV1,
    M3AcceptanceAuditError,
    M3AcceptanceWriteError,
    audit_m3_acceptance,
    compute_acceptance_key,
    write_acceptance_candidate,
)
from quant.research.m3.acceptance_tracking import AcceptanceTrackingAuditV1
from quant.research.m3.acceptance_stage import run_formal_acceptance_stage

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "_g9f_support", Path(__file__).with_name("test_m3_acceptance_tracking.py")
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
sys.modules[_SUPPORT_SPEC.name] = _SUPPORT
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)
_complete_bundle = cast(Any, getattr(_SUPPORT, "_complete_bundle"))
_observation = cast(Any, getattr(_SUPPORT, "_observation"))


def _gate(name: str, *, passed: bool = True) -> GateResultV1:
    from quant.research.m3.acceptance import AcceptanceIssueV1

    issues = () if passed else (AcceptanceIssueV1(cast(Any, name), "INVALID", "global:test", ()),)
    return GateResultV1(cast(Any, name), "PASS" if passed else "FAIL", issues, ())


def _install_checkers(monkeypatch: pytest.MonkeyPatch, *, failed_gate: str | None = None) -> None:
    import quant.research.m3.acceptance_tracking as tracking_module
    import quant.research.m3.acceptance_upstream as upstream_module
    import quant.research.m3.acceptance_work as work_module

    monkeypatch.setattr(
        upstream_module,
        "audit_acceptance_upstream",
        lambda **kwargs: tuple(_gate(name, passed=name != failed_gate) for name in ("G0", "G1", "G2", "G3", "G4")),
    )
    monkeypatch.setattr(
        work_module,
        "audit_acceptance_work",
        lambda **kwargs: tuple(_gate(name, passed=name != failed_gate) for name in ("G5", "G6", "G7")),
    )

    def tracking(**kwargs: object) -> AcceptanceTrackingAuditV1:
        observations = tuple(
            _observation(
                marker=cast(Any, object()),
                request=cast(Any, object()),
            )
            for _ in ()
        )
        return AcceptanceTrackingAuditV1(
            (_gate("G8", passed=failed_gate != "G8"), _gate("G9", passed=failed_gate != "G9")),
            observations,
            "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        )

    # Empty observation SHA is the canonical hash of [].
    monkeypatch.setattr(tracking_module, "audit_acceptance_tracking", tracking)


def test_acceptance_key_binds_ordered_receipts() -> None:
    base = dict(
        experiment_key="1" * 64,
        acceptance_config_sha256="2" * 64,
        tracking_target_key="3" * 64,
        quality_receipt_sha256="4" * 64,
        tracking_observations_sha256="5" * 64,
    )
    first = compute_acceptance_key(
        **base,
        required_receipt_sha256s=("6" * 64, "7" * 64),
    )
    assert first != compute_acceptance_key(
        **base,
        required_receipt_sha256s=("7" * 64, "6" * 64),
    )
    assert first != compute_acceptance_key(
        **{**base, "tracking_target_key": "8" * 64},
        required_receipt_sha256s=("6" * 64, "7" * 64),
    )


@pytest.mark.parametrize("failed_gate", [None, "G6", "G8", "G9"])
def test_audit_aggregates_fixed_gate_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_gate: str | None,
) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    _install_checkers(monkeypatch, failed_gate=failed_gate)
    decision = audit_m3_acceptance(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=_observation,
    )
    assert tuple(item.gate for item in decision.gate_results) == tuple(f"G{i}" for i in range(10))
    assert decision.overall_status == ("PASS" if failed_gate is None else "FAIL")
    assert decision.tracking_target_key == bundle.config.tracking_target_key


def test_pass_writer_is_canonical_and_fail_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    _install_checkers(monkeypatch)
    decision = audit_m3_acceptance(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=_observation,
    )
    target = tmp_path / "candidate"
    target.mkdir()
    digest = write_acceptance_candidate(decision=decision, temp_output_root=target)
    assert digest.relative_path == "acceptance_report.json"
    assert tuple(path.name for path in target.iterdir()) == ("acceptance_report.json",)

    rejected = tmp_path / "rejected"
    rejected.mkdir()
    failed = replace(
        decision,
        gate_results=tuple(
            _gate(f"G{i}", passed=i != 5) for i in range(10)
        ),
        overall_status="FAIL",
    )
    with pytest.raises(M3AcceptanceWriteError):
        write_acceptance_candidate(decision=failed, temp_output_root=rejected)
    assert not tuple(rejected.iterdir())


def test_audit_invalid_caller_is_sanitized(tmp_path: Path) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    with pytest.raises(M3AcceptanceAuditError) as caught:
        audit_m3_acceptance(
            subject=bundle.subject,
            plan=bundle.plan,
            quality=quality,
            config=bundle.config,
            artifact_roots={},
            tracking_verifier=_observation,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_acceptance_stage_publishes_and_resumes_exact_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    _install_checkers(monkeypatch)
    import quant.research.m3.acceptance_stage as stage_module

    monkeypatch.setattr(stage_module, "create_mlflow_tracking_client", lambda **kwargs: object())
    monkeypatch.setattr(stage_module, "verify_tracking_remote", _observation)
    first = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    second = run_formal_acceptance_stage(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
    )
    assert first.reused is False
    assert second.reused is True
    assert first.decision == second.decision
    assert first.receipt == second.receipt


def test_public_acceptance_stage_has_no_tracking_verifier_injection() -> None:
    import quant.research.m3 as package

    assert "tracking_verifier" not in inspect.signature(
        run_formal_acceptance_stage
    ).parameters
    assert "write_acceptance_candidate" not in package.__all__
    with pytest.raises(AttributeError):
        getattr(package, "write_acceptance_candidate")
