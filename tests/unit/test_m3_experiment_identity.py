from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from quant.research.m3.contracts import (
    ExperimentIdentitySpec,
    VerifiedExperimentIdentity,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.experiment_identity import (
    build_experiment_identity_manifest,
    make_experiment_identity_handler,
    make_experiment_identity_run_plan,
    verify_experiment_identity_output,
)
from quant.research.m3.orchestration import M3StageRunnerError, StageRunner

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_experiment_identity_test_support",
    Path(__file__).with_name("test_m3_provider_validation.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _test_commit_directory_noreplace(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    os.rename(source, destination)


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, ...]:
    monkeypatch.setattr(
        "quant.research.m3.orchestration.commit_directory_noreplace",
        _test_commit_directory_noreplace,
    )
    (
        common,
        development_snapshot,
        development_provider,
        config,
        _,
        development_provider_receipt,
        validation_root,
        validation_result,
    ) = _SUPPORT._built_validation(tmp_path, monkeypatch)
    snapshot = VerifiedSnapshotArtifact(
        root=development_snapshot.root,
        request=development_snapshot.request,
        request_sha256=development_snapshot.request_sha256,
        manifest=development_snapshot.manifest,
        manifest_sha256=development_snapshot.manifest_sha256,
        snapshot_receipt_sha256=development_snapshot.snapshot_receipt_sha256,
        session_calendar_path=development_snapshot.session_calendar_path,
        staging_paths=development_snapshot.staging_paths,
    )
    provider = VerifiedProviderArtifact(
        root=development_provider.root,
        qlib_dir=development_provider.qlib_dir,
        manifest=development_provider.manifest,
        manifest_sha256=development_provider.manifest_sha256,
        provider_receipt_sha256=development_provider.provider_receipt_sha256,
    )
    formal_snapshot_receipt = (
        common / "receipts" / "snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    formal_snapshot_receipt.parent.mkdir()
    development_snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    shutil.copyfile(development_snapshot_receipt, formal_snapshot_receipt)
    formal_provider_receipt = (
        common / "receipts" / "provider" / f"{provider.manifest.provider_key}.json"
    )
    formal_provider_receipt.parent.mkdir()
    shutil.copyfile(development_provider_receipt, formal_provider_receipt)
    validation = VerifiedProviderValidationArtifact(
        root=validation_root,
        details=validation_result.details,
        summary=validation_result.summary,
        summary_sha256=hashlib.sha256(b"summary").hexdigest(),
        validation_receipt_sha256=hashlib.sha256(b"receipt").hexdigest(),
    )
    stage_root = tmp_path / "formal-g8"
    stage_root.mkdir()
    external = tmp_path / "external_qlib"
    external.mkdir(exist_ok=True)
    roots = {"root": common, "EXTERNAL_QLIB": external, "stage": stage_root}
    spec = ExperimentIdentitySpec(
        scientific_config_sha256=config.scientific_config_sha256,
        dependency_fingerprint_sha256=hashlib.sha256(b"full-dependencies").hexdigest(),
        code_version="m3-git-v1-" + "a" * 40 + "-clean",
    )
    return common, stage_root, roots, snapshot, provider, validation, config, spec


def test_formal_experiment_identity_publish_resume_and_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        _, stage_root, roots, snapshot, provider, validation, config, spec,
    ) = _fixture(tmp_path, monkeypatch)
    plan = make_experiment_identity_run_plan(
        snapshot=snapshot,
        provider=provider,
        provider_validation=validation,
        config=config,
        spec=spec,
        artifact_roots=roots,
    )
    node = plan.nodes[0]
    expected = build_experiment_identity_manifest(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    runner = StageRunner(stage_root=stage_root, artifact_roots=roots, config=config)

    def output_verifier(root: Path):
        return verify_experiment_identity_output(root=root, expected=expected)

    def final_verifier(root: Path, receipt: Path) -> VerifiedExperimentIdentity:
        manifest = output_verifier(root)
        manifest_raw = (root / "experiment_manifest.json").read_bytes()
        return VerifiedExperimentIdentity(
            root=root,
            manifest=manifest,
            manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            experiment_receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        )

    first = runner.run_experiment_identity(
        node=node,
        handler=make_experiment_identity_handler(
            snapshot=snapshot, provider=provider, spec=spec
        ),
        output_verifier=output_verifier,
        final_verifier=final_verifier,
    )
    assert first.reused is False
    assert first.experiment_root == stage_root / "runs" / expected.experiment_key
    assert tuple(path.name for path in first.experiment_root.iterdir()) == (
        "experiment_manifest.json",
    )
    assert len(first.receipt.inputs) == 4
    assert len(first.receipt.outputs) == 1
    assert all("provider-validation" not in item.relative_path for item in first.receipt.inputs)
    assert first.receipt.scope == "EXPERIMENT"
    assert first.receipt.stage == "experiment-identity"

    def forbidden(_context: Any):
        raise AssertionError("resume must not invoke handler")

    second = runner.run_experiment_identity(
        node=node,
        handler=forbidden,
        output_verifier=output_verifier,
        final_verifier=final_verifier,
    )
    assert second.reused is True
    assert not any((stage_root / ".stage-tmp").iterdir())


def test_validation_is_gate_only_and_must_have_matching_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, roots, snapshot, provider, validation, config, spec = _fixture(
        tmp_path, monkeypatch
    )
    failed = VerifiedProviderValidationArtifact(
        root=validation.root,
        details=validation.details,
        summary=replace(validation.summary, passed=False),
        summary_sha256=validation.summary_sha256,
        validation_receipt_sha256=validation.validation_receipt_sha256,
    )
    with pytest.raises(ValueError, match="provider validation gate identity drift"):
        make_experiment_identity_run_plan(
            snapshot=snapshot,
            provider=provider,
            provider_validation=failed,
            config=config,
            spec=spec,
            artifact_roots=roots,
        )


def test_existing_output_tamper_fails_closed_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, stage_root, roots, snapshot, provider, validation, config, spec = _fixture(
        tmp_path, monkeypatch
    )
    plan = make_experiment_identity_run_plan(
        snapshot=snapshot, provider=provider, provider_validation=validation,
        config=config, spec=spec, artifact_roots=roots,
    )
    node = plan.nodes[0]
    expected = build_experiment_identity_manifest(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    runner = StageRunner(stage_root=stage_root, artifact_roots=roots, config=config)

    def output(root: Path):
        return verify_experiment_identity_output(root=root, expected=expected)

    def final(root: Path, receipt: Path) -> VerifiedExperimentIdentity:
        manifest = output(root)
        return VerifiedExperimentIdentity(
            root=root,
            manifest=manifest,
            manifest_sha256=hashlib.sha256(
                (root / "experiment_manifest.json").read_bytes()
            ).hexdigest(),
            experiment_receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        )

    first = runner.run_experiment_identity(
        node=node,
        handler=make_experiment_identity_handler(
            snapshot=snapshot, provider=provider, spec=spec
        ),
        output_verifier=output,
        final_verifier=final,
    )
    (first.experiment_root / "unexpected.txt").write_text("tamper", encoding="utf-8")
    with pytest.raises(M3StageRunnerError) as exc:
        runner.run_experiment_identity(
            node=node,
            handler=make_experiment_identity_handler(
                snapshot=snapshot, provider=provider, spec=spec
            ),
            output_verifier=output,
            final_verifier=final,
        )
    assert exc.value.code == "STAGE_RECOVERY_CONFLICT"
