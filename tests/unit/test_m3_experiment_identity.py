from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from dataclasses import asdict, replace
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
    experiment_identity_manifest_bytes,
    make_experiment_identity_handler,
    make_experiment_identity_run_plan,
    verify_experiment_identity_output,
)
from quant.research.m3.labels import M3LabelArtifactError, verify_experiment_identity
from quant.research.m3.orchestration import M3StageRunnerError, StageRunner
from quant.research.m3.provider import verify_provider_artifact
from quant.research.m3.run_state import (
    compute_provider_key,
    path_for_artifact_digest,
    publish_stage_receipt,
    verify_stage_receipt,
)

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
    external = tmp_path / "external_qlib"
    external.mkdir(exist_ok=True)
    receipt_roots = {"root": common, "EXTERNAL_QLIB": external}
    formal_snapshot_receipt = (
        common / "receipts" / "snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    formal_snapshot_receipt.parent.mkdir()
    development_snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    development_snapshot_stage = verify_stage_receipt(
        receipt_path=development_snapshot_receipt,
        artifact_roots=receipt_roots,
    )
    assert development_snapshot_stage is not None
    release_manifest_candidates = tuple(
        item
        for item in development_snapshot_stage.inputs
        if item.sha256 == snapshot.manifest.g1_release_manifest_sha256
        and Path(item.relative_path).name == "manifest.json"
    )
    assert len(release_manifest_candidates) == 1
    release_manifest = path_for_artifact_digest(
        release_manifest_candidates[0], artifact_roots=receipt_roots
    )
    for name in (
        "bar_1d.parquet",
        "universe_membership.parquet",
        "trade_calendar.parquet",
    ):
        shutil.copyfile(release_manifest.parent / "contract" / name, release_manifest.parent / name)
    publish_stage_receipt(
        receipt_path=formal_snapshot_receipt,
        stage="snapshot",
        scope="SNAPSHOT",
        scope_key=snapshot.request.snapshot_request_key,
        artifact_roots=receipt_roots,
        inputs=[
            ("root", release_manifest),
            ("root", release_manifest.parent / "bar_1d.parquet"),
            ("root", release_manifest.parent / "universe_membership.parquet"),
            ("root", release_manifest.parent / "trade_calendar.parquet"),
        ],
        outputs=[
            (
                item.root_alias,
                path_for_artifact_digest(item, artifact_roots=receipt_roots),
            )
            for item in development_snapshot_stage.outputs
        ],
    )
    snapshot = replace(
        snapshot,
        snapshot_receipt_sha256=hashlib.sha256(
            formal_snapshot_receipt.read_bytes()
        ).hexdigest(),
    )
    development_provider_stage = verify_stage_receipt(
        receipt_path=development_provider_receipt,
        artifact_roots=receipt_roots,
    )
    assert development_provider_stage is not None
    formal_provider_key = compute_provider_key(
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_config_hash=config.provider_config_sha256,
        dump_tool_sha256=provider.manifest.dump_tool_sha256,
        qlib_version=provider.manifest.qlib_version,
        provider_runtime_fingerprint_sha256=(
            provider.manifest.provider_runtime_fingerprint_sha256
        ),
        code_version=provider.manifest.code_version,
    )
    formal_provider_manifest = replace(
        provider.manifest,
        provider_key=formal_provider_key,
    )
    formal_provider_manifest_raw = json.dumps(
        asdict(formal_provider_manifest),
        default=lambda item: item.isoformat(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    (provider.root / "provider_manifest.json").write_bytes(
        formal_provider_manifest_raw
    )
    provider = replace(
        provider,
        manifest=formal_provider_manifest,
        manifest_sha256=hashlib.sha256(formal_provider_manifest_raw).hexdigest(),
    )
    formal_provider_receipt = (
        common / "receipts" / "provider" / f"{provider.manifest.provider_key}.json"
    )
    formal_provider_receipt.parent.mkdir()
    publish_stage_receipt(
        receipt_path=formal_provider_receipt,
        stage="provider",
        scope="PROVIDER",
        scope_key=provider.manifest.provider_key,
        artifact_roots=receipt_roots,
        inputs=[
            (
                "root" if item.sha256 == development_snapshot.snapshot_receipt_sha256 else item.root_alias,
                formal_snapshot_receipt
                if item.sha256 == development_snapshot.snapshot_receipt_sha256
                else path_for_artifact_digest(item, artifact_roots=receipt_roots),
            )
            for item in development_provider_stage.inputs
        ],
        outputs=[
            (
                item.root_alias,
                path_for_artifact_digest(item, artifact_roots=receipt_roots),
            )
            for item in development_provider_stage.outputs
        ],
    )
    provider = replace(
        provider,
        provider_receipt_sha256=hashlib.sha256(
            formal_provider_receipt.read_bytes()
        ).hexdigest(),
    )
    validation = VerifiedProviderValidationArtifact(
        root=validation_root,
        details=validation_result.details,
        summary=replace(
            validation_result.summary,
            provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_manifest_sha256=provider.manifest_sha256,
        ),
        summary_sha256=hashlib.sha256(b"summary").hexdigest(),
        validation_receipt_sha256=hashlib.sha256(b"receipt").hexdigest(),
    )
    stage_root = tmp_path / "formal-g8"
    stage_root.mkdir()
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


def test_formal_verifier_resolves_snapshot_and_provider_receipts_from_own_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        common, stage_root, roots, snapshot, provider, _, config, spec,
    ) = _fixture(tmp_path, monkeypatch)
    old_provider_receipt = (
        common / "receipts" / "provider"
        / f"{provider.manifest.provider_key}.json"
    )
    old_receipt = verify_stage_receipt(
        receipt_path=old_provider_receipt, artifact_roots=roots
    )
    assert old_receipt is not None
    provider_artifact_root = tmp_path / "formal-g2b"
    split_provider_root = provider_artifact_root / provider.root.name
    shutil.copytree(provider.root, split_provider_root)
    split_roots = {**roots, "G2B": provider_artifact_root}
    split_provider_receipt = (
        provider_artifact_root / "receipts" / "provider"
        / f"{provider.manifest.provider_key}.json"
    )
    split_provider_receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=split_provider_receipt,
        stage="provider",
        scope="PROVIDER",
        scope_key=provider.manifest.provider_key,
        artifact_roots=split_roots,
        inputs=[
            (
                item.root_alias,
                path_for_artifact_digest(item, artifact_roots=roots),
            )
            for item in old_receipt.inputs
        ],
        outputs=[
            (
                "G2B",
                split_provider_root
                / path_for_artifact_digest(item, artifact_roots=roots).relative_to(
                    provider.root
                ),
            )
            for item in old_receipt.outputs
        ],
    )
    old_provider_receipt.unlink()
    provider = replace(
        provider,
        root=split_provider_root,
        qlib_dir=split_provider_root / "provider",
        provider_receipt_sha256=hashlib.sha256(
            split_provider_receipt.read_bytes()
        ).hexdigest(),
    )
    manifest = build_experiment_identity_manifest(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    experiment_root = stage_root / "split-root-experiment"
    experiment_root.mkdir()
    (experiment_root / "experiment_manifest.json").write_bytes(
        experiment_identity_manifest_bytes(manifest)
    )
    snapshot_receipt = (
        common / "receipts" / "snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    experiment_receipt = (
        stage_root / "receipts" / "experiment-identity"
        / f"{manifest.experiment_key}.json"
    )
    experiment_receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=experiment_receipt,
        stage="experiment-identity",
        scope="EXPERIMENT",
        scope_key=manifest.experiment_key,
        artifact_roots=split_roots,
        inputs=[
            ("root", snapshot_receipt),
            ("root", snapshot.root / "manifest.json"),
            ("G2B", split_provider_receipt),
            ("G2B", provider.root / "provider_manifest.json"),
        ],
        outputs=[("stage", experiment_root / "experiment_manifest.json")],
    )
    assert verify_provider_artifact(
        provider_root=provider.root,
        provider_receipt_path=split_provider_receipt,
        snapshot=snapshot,
        config=config,
        artifact_roots=split_roots,
    ) == provider
    verified = verify_experiment_identity(
        experiment_root=experiment_root,
        experiment_receipt_path=experiment_receipt,
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
        artifact_roots=split_roots,
    )
    assert verified.manifest == manifest
    assert not old_provider_receipt.exists()

    original = split_provider_receipt.read_bytes()
    for mutation in ("stage", "hash", "escape"):
        payload = json.loads(original)
        if mutation == "stage":
            payload["stage"] = "snapshot"
        elif mutation == "hash":
            payload["inputs"][0]["sha256"] = "0" * 64
        else:
            payload["inputs"][0]["relative_path"] = "../escape"
        split_provider_receipt.write_bytes(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        )
        with pytest.raises(M3LabelArtifactError):
            verify_experiment_identity(
            experiment_root=experiment_root,
            experiment_receipt_path=experiment_receipt,
            snapshot=snapshot,
            provider=provider,
            config=config,
            spec=spec,
            artifact_roots=split_roots,
        )
        split_provider_receipt.write_bytes(original)


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
