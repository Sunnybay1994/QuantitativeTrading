"""Focused G9E remote tracking and bounded safety checks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest

import quant.research.m3.acceptance_tracking as tracking_audit_module
from quant.research.m3.acceptance import RemoteTrackingObservationV1
from quant.research.m3.acceptance_tracking import (
    M3AcceptanceTrackingError,
    audit_acceptance_tracking,
)
from quant.research.m3.quality_gate import (
    QualityCheckResultV1,
    QualityReportV1,
    VerifiedQualityArtifact,
)
from quant.research.m3.run_state import ArtifactDigest, publish_stage_receipt
from quant.research.m3.tracking import (
    M3TrackingRemoteError,
    RemoteTrackingRunV1,
    TrackingMarkerV1,
    TrackingRequestV1,
    compute_tracking_key,
    publish_tracking_marker,
    publish_tracking_request,
    verify_tracking_remote,
)

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "_g9e_support", Path(__file__).with_name("test_m3_acceptance_upstream.py")
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
sys.modules[_SUPPORT_SPEC.name] = _SUPPORT
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)
_bundle = cast(Any, getattr(_SUPPORT, "_bundle"))
_sha = cast(Any, getattr(_SUPPORT, "_sha"))
_write = cast(Any, getattr(_SUPPORT, "_write"))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _artifact_sha(artifacts: tuple[ArtifactDigest, ...]) -> str:
    return hashlib.sha256(_canonical([asdict(item) for item in artifacts])).hexdigest()


def _request_marker(
    root: Path,
    *,
    target_key: str,
    work_key: str,
    run_id: str = "run-1",
) -> tuple[TrackingRequestV1, TrackingMarkerV1]:
    artifact = _write(root / f"remote/{work_key}.json", b"{}")
    digest = ArtifactDigest(
        "G8",
        artifact.relative_to(root).as_posix(),
        artifact.stat().st_size,
        _sha(artifact),
    )
    request = TrackingRequestV1(
        "m3-tracking-request-v1",
        target_key,
        work_key,
        (("fold", "fold_001"),),
        (("formal_gate_eligible", "true"),),
        (("metric", 1.0),),
        (digest,),
    )
    request_sha = hashlib.sha256(
        _canonical(
            {
                **asdict(request),
                "artifacts": [asdict(item) for item in request.artifacts],
                "metrics": [[key, value] for key, value in request.metrics],
                "params": [[key, value] for key, value in request.params],
                "tags": [[key, value] for key, value in request.tags],
            }
        )
    ).hexdigest()
    tracking_key = compute_tracking_key(work_key=work_key, request_sha256=request_sha)
    marker = TrackingMarkerV1(
        "m3-tracking-marker-v1",
        target_key,
        tracking_key,
        request_sha,
        run_id,
        _artifact_sha(request.artifacts),
    )
    return request, marker


class _Remote:
    def __init__(self, runs: tuple[RemoteTrackingRunV1, ...]) -> None:
        self.runs = runs
        self.find_calls = 0
        self.mutations = 0

    def find_runs(self, *, experiment_name: str, tracking_key: str) -> tuple[RemoteTrackingRunV1, ...]:
        assert experiment_name == "m3-test"
        assert len(tracking_key) == 64
        self.find_calls += 1
        return self.runs

    def create_run(self, **kwargs: object) -> str:
        self.mutations += 1
        raise AssertionError

    def log_params(self, **kwargs: object) -> None:
        self.mutations += 1
        raise AssertionError

    def log_metrics(self, **kwargs: object) -> None:
        self.mutations += 1
        raise AssertionError

    def log_artifact(self, **kwargs: object) -> None:
        self.mutations += 1
        raise AssertionError

    def finish_run(self, **kwargs: object) -> None:
        self.mutations += 1
        raise AssertionError


def _remote_run(request: TrackingRequestV1, marker: TrackingMarkerV1, *, status: str = "FINISHED") -> RemoteTrackingRunV1:
    return RemoteTrackingRunV1(
        marker.mlflow_run_id,
        cast(Any, status),
        {
            **dict(request.tags),
            "quant_tracking_key": marker.tracking_key,
            "quant_tracking_target_key": marker.tracking_target_key,
            "quant_request_sha256": marker.request_sha256,
            "quant_artifact_digest_sha256": marker.artifact_digest_sha256,
            "quant_work_key": request.work_key,
        },
    )


@pytest.mark.parametrize("mode", ["none", "multiple", "running", "drift"])
def test_remote_verifier_is_read_only_and_fails_closed(tmp_path: Path, mode: str) -> None:
    target = "a" * 64
    request, marker = _request_marker(tmp_path, target_key=target, work_key="b" * 64)
    run = _remote_run(request, marker, status="RUNNING" if mode == "running" else "FINISHED")
    runs: tuple[RemoteTrackingRunV1, ...]
    if mode == "none":
        runs = ()
    elif mode == "multiple":
        runs = (run, run)
    elif mode == "drift":
        runs = (RemoteTrackingRunV1(run.run_id, run.status, {**run.tags, "quant_work_key": "c" * 64}),)
    else:
        runs = (run,)
    remote = _Remote(runs)

    with pytest.raises(M3TrackingRemoteError) as caught:
        verify_tracking_remote(
            marker=marker,
            request=request,
            experiment_name="m3-test",
            client=remote,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert remote.find_calls == 1
    assert remote.mutations == 0


def test_remote_verifier_returns_exact_observation(tmp_path: Path) -> None:
    request, marker = _request_marker(
        tmp_path,
        target_key="a" * 64,
        work_key="b" * 64,
    )
    remote = _Remote((_remote_run(request, marker),))
    observed = verify_tracking_remote(
        marker=marker,
        request=request,
        experiment_name="m3-test",
        client=remote,
    )
    assert type(observed) is RemoteTrackingObservationV1
    assert observed.run_id == marker.mlflow_run_id
    assert observed.request_sha256 == marker.request_sha256
    assert remote.find_calls == 1
    assert remote.mutations == 0


def _quality(bundle: Any, locator: Any) -> VerifiedQualityArtifact:
    checks = tuple(
        QualityCheckResultV1(name, ("<PYTHON>", "-m", name), 0, "1" * 64, "2" * 64)
        for name in ("pytest", "ruff", "mypy", "import_isolation")
    )
    report = QualityReportV1(
        "m3-quality-report-v1",
        locator.expected_scope_key,
        "m3-quality-commands-v1",
        bundle.subject.runtime.code_version,
        bundle.subject.runtime.dependency_fingerprint_sha256,
        cast(Any, checks),
        True,
    )
    path = _write(
        bundle.root / "fake/G9/quality/quality_report.json",
        _canonical(asdict(report)),
    )
    receipt_path = bundle.root.joinpath(*locator.receipt_relative_path.split("/"))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = publish_stage_receipt(
        receipt_path=receipt_path,
        stage=locator.expected_stage,
        scope=locator.expected_scope,
        scope_key=locator.expected_scope_key,
        artifact_roots=bundle.roots,
        inputs=(),
        outputs=(("G8", path),),
    )
    return VerifiedQualityArtifact(report, receipt.outputs[0], receipt, _sha(receipt_path))


def _complete_bundle(
    tmp_path: Path,
    *,
    unsafe: bool = False,
    bundle: Any | None = None,
) -> tuple[Any, VerifiedQualityArtifact]:
    if bundle is None:
        bundle = _bundle(tmp_path)
    quality: VerifiedQualityArtifact | None = None
    for locator in bundle.plan.evidence:
        receipt_path = bundle.root.joinpath(*locator.receipt_relative_path.split("/"))
        if receipt_path.exists():
            continue
        outputs: tuple[tuple[str, Path], ...]
        if locator.gate == "G8":
            request, marker = _request_marker(
                bundle.root,
                target_key=bundle.config.tracking_target_key,
                work_key=locator.expected_scope_key,
                run_id=f"run-{locator.expected_scope_key[:8]}",
            )
            base = bundle.root / "fake/G8" / locator.node_id
            base.mkdir(parents=True, exist_ok=True)
            request_path = base / "tracking_request.json"
            marker_path = base / "tracking_marker.json"
            publish_tracking_request(path=request_path, request=request)
            publish_tracking_marker(path=marker_path, marker=marker)
            outputs = (("G8", request_path), ("G8", marker_path))
        elif locator.gate == "G9":
            quality = _quality(bundle, locator)
            continue
        else:
            raw = b'{"password":"exposed"}' if unsafe and locator.gate == "G5" else b"{}"
            output = _write(
                bundle.root / "fake" / locator.gate / locator.node_id / "manifest.json",
                raw,
            )
            outputs = (("G8", output),)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        publish_stage_receipt(
            receipt_path=receipt_path,
            stage=locator.expected_stage,
            scope=locator.expected_scope,
            scope_key=locator.expected_scope_key,
            artifact_roots=bundle.roots,
            inputs=(),
            outputs=outputs,
        )
    assert quality is not None
    return bundle, quality


def _observation(*, marker: TrackingMarkerV1, request: TrackingRequestV1) -> RemoteTrackingObservationV1:
    return RemoteTrackingObservationV1(
        request.work_key,
        request.tracking_target_key,
        marker.tracking_key,
        marker.mlflow_run_id,
        "FINISHED",
        marker.request_sha256,
        marker.artifact_digest_sha256,
    )


def test_g9e_closes_tracking_quality_and_bounded_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    monkeypatch.setattr(tracking_audit_module, "_project_config", lambda *args, **kwargs: (tmp_path, Path("m3.toml")))
    monkeypatch.setattr(tracking_audit_module, "verify_quality_artifact", lambda **kwargs: quality)

    result = audit_acceptance_tracking(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=_observation,
    )
    assert tuple(item.status for item in result.gate_results) == ("PASS", "PASS")
    assert tuple(item.work_key for item in result.observations) == bundle.plan.expected_work_keys
    assert len(result.tracking_observations_sha256) == 64


def test_g9e_classifies_remote_and_safety_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, quality = _complete_bundle(tmp_path, unsafe=True)
    monkeypatch.setattr(tracking_audit_module, "_project_config", lambda *args, **kwargs: (tmp_path, Path("m3.toml")))
    monkeypatch.setattr(tracking_audit_module, "verify_quality_artifact", lambda **kwargs: quality)

    def unavailable(**kwargs: object) -> RemoteTrackingObservationV1:
        raise RuntimeError("TOKEN hostile")

    result = audit_acceptance_tracking(
        subject=bundle.subject,
        plan=bundle.plan,
        quality=quality,
        config=bundle.config,
        artifact_roots=bundle.roots,
        tracking_verifier=unavailable,
    )
    assert tuple(item.status for item in result.gate_results) == ("FAIL", "FAIL")
    assert {item.code for item in result.gate_results[0].issues} == {"TRACKING_REMOTE_INVALID"}
    assert {item.code for item in result.gate_results[1].issues} == {"SAFETY_SCAN_INVALID"}


def test_g9e_invalid_caller_is_sanitized(tmp_path: Path) -> None:
    bundle, quality = _complete_bundle(tmp_path)
    with pytest.raises(M3AcceptanceTrackingError) as caught:
        audit_acceptance_tracking(
            subject=bundle.subject,
            plan=bundle.plan,
            quality=quality,
            config=bundle.config,
            artifact_roots={},
            tracking_verifier=_observation,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
