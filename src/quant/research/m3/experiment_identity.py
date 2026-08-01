"""G8 formal ExperimentIdentity producer and deterministic run-plan binding."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ExperimentIdentityManifestV1,
    ExperimentIdentitySpec,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.orchestration import (
    EXPERIMENT_IDENTITY_STAGE_SPEC,
    ExternalInput,
    RunPlan,
    StageBuildReport,
    StageContext,
    StageNode,
    StaticDirectoryPublication,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_experiment_key,
    select_artifact_root,
)


def build_experiment_identity_manifest(
    *,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    config: LoadedM3Config,
    spec: ExperimentIdentitySpec,
) -> ExperimentIdentityManifestV1:
    """Build the single canonical manifest consumed by the strict G3 verifier."""
    if (
        type(snapshot) is not VerifiedSnapshotArtifact
        or type(provider) is not VerifiedProviderArtifact
        or type(config) is not LoadedM3Config
        or type(spec) is not ExperimentIdentitySpec
    ):
        raise ValueError("experiment identity inputs invalid")
    if spec.scientific_config_sha256 != config.scientific_config_sha256:
        raise ValueError("experiment scientific config drift")
    if (
        provider.manifest.snapshot_id != snapshot.manifest.snapshot_id
        or provider.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256
    ):
        raise ValueError("experiment upstream identity drift")
    experiment_key = compute_experiment_key(
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_hash=spec.scientific_config_sha256,
        code_version=spec.code_version,
        dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
    )
    return ExperimentIdentityManifestV1(
        schema_version="m3-experiment-identity-v1",
        experiment_key=experiment_key,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        scientific_config_sha256=spec.scientific_config_sha256,
        dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        code_version=spec.code_version,
    )


def experiment_identity_manifest_bytes(
    manifest: ExperimentIdentityManifestV1,
) -> bytes:
    """Serialize an ExperimentIdentity manifest as canonical JSON."""
    if type(manifest) is not ExperimentIdentityManifestV1:
        raise ValueError("experiment manifest type invalid")
    return json.dumps(
        asdict(manifest),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def verify_experiment_identity_output(
    *, root: Path, expected: ExperimentIdentityManifestV1
) -> ExperimentIdentityManifestV1:
    """Verify the pre-receipt one-file directory closure and canonical bytes."""
    if not isinstance(root, Path) or type(expected) is not ExperimentIdentityManifestV1:
        raise ValueError("experiment output verifier input invalid")
    before = os.lstat(root)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise ValueError("experiment output root invalid")
    entries = tuple(os.scandir(root))
    if len(entries) != 1 or entries[0].name != "experiment_manifest.json":
        raise ValueError("experiment output closure invalid")
    entry = entries[0]
    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
        raise ValueError("experiment manifest entry invalid")
    path = root / entry.name
    raw = _read_stable_regular(path)
    if raw != experiment_identity_manifest_bytes(expected):
        raise ValueError("experiment manifest identity drift")
    after = os.lstat(root)
    if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
    ):
        raise ValueError("experiment output drift")
    return expected


def make_experiment_identity_handler(
    *,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    spec: ExperimentIdentitySpec,
) -> Callable[[StageContext], StageBuildReport]:
    """Create the narrow handler; the runner owns its temporary directory."""
    if (
        type(snapshot) is not VerifiedSnapshotArtifact
        or type(provider) is not VerifiedProviderArtifact
        or type(spec) is not ExperimentIdentitySpec
    ):
        raise ValueError("experiment handler inputs invalid")

    def handler(context: StageContext) -> StageBuildReport:
        manifest = build_experiment_identity_manifest(
            snapshot=snapshot,
            provider=provider,
            config=context.config,
            spec=spec,
        )
        if manifest.experiment_key != context.node.scope_key:
            raise ValueError("experiment plan identity drift")
        path = context.temp_output_root / "experiment_manifest.json"
        with path.open("xb") as stream:
            stream.write(experiment_identity_manifest_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        return StageBuildReport(("experiment_manifest.json",))

    return handler


def make_experiment_identity_run_plan(
    *,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    config: LoadedM3Config,
    spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path],
) -> RunPlan:
    """Bind the exact four content inputs after a verified validation PASS gate."""
    _verify_provider_validation_gate(
        snapshot=snapshot,
        provider=provider,
        provider_validation=provider_validation,
    )
    manifest = build_experiment_identity_manifest(
        snapshot=snapshot,
        provider=provider,
        config=config,
        spec=spec,
    )
    snapshot_alias, snapshot_artifact_root = select_artifact_root(
        snapshot.root, artifact_roots=artifact_roots
    )
    provider_alias, provider_artifact_root = select_artifact_root(
        provider.root, artifact_roots=artifact_roots
    )
    inputs = (
        _digest(
            alias=snapshot_alias,
            root=snapshot_artifact_root,
            path=(
                snapshot_artifact_root
                / "receipts"
                / "snapshot"
                / f"{snapshot.request.snapshot_request_key}.json"
            ),
        ),
        _digest(
            alias=snapshot_alias,
            root=snapshot_artifact_root,
            path=snapshot.root / "manifest.json",
        ),
        _digest(
            alias=provider_alias,
            root=provider_artifact_root,
            path=(
                provider_artifact_root
                / "receipts"
                / "provider"
                / f"{provider.manifest.provider_key}.json"
            ),
        ),
        _digest(
            alias=provider_alias,
            root=provider_artifact_root,
            path=provider.root / "provider_manifest.json",
        ),
    )
    ordered = tuple(sorted(inputs, key=lambda item: (item.root_alias, item.relative_path)))
    node = StageNode(
        node_id="experiment-identity",
        spec_name=EXPERIMENT_IDENTITY_STAGE_SPEC.name,
        scope="EXPERIMENT",
        scope_key=manifest.experiment_key,
        fold=None,
        horizon=None,
        dependencies=(),
        inputs=tuple(ExternalInput(item) for item in ordered),
        publication=StaticDirectoryPublication(
            final_directory=f"runs/{manifest.experiment_key}"
        ),
        output_specs=EXPERIMENT_IDENTITY_STAGE_SPEC.outputs,
        receipt_path=(
            f"receipts/experiment-identity/{manifest.experiment_key}.json"
        ),
    )
    return RunPlan(continuation="EXPERIMENT", nodes=(node,))


def _verify_provider_validation_gate(
    *,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
) -> None:
    if (
        type(snapshot) is not VerifiedSnapshotArtifact
        or type(provider) is not VerifiedProviderArtifact
        or type(provider_validation) is not VerifiedProviderValidationArtifact
    ):
        raise ValueError("provider validation gate type invalid")
    summary = provider_validation.summary
    if (
        not summary.passed
        or summary.snapshot_id != snapshot.manifest.snapshot_id
        or summary.provider_key != provider.manifest.provider_key
        or summary.provider_manifest_sha256 != provider.manifest_sha256
        or summary.provider_receipt_sha256 != provider.provider_receipt_sha256
    ):
        raise ValueError("provider validation gate identity drift")


def _digest(*, alias: str, root: Path, path: Path) -> ArtifactDigest:
    resolved_root = root.resolve(strict=True)
    absolute_path = Path(os.path.abspath(path))
    try:
        relative = absolute_path.relative_to(resolved_root).as_posix()
    except ValueError:
        raise ValueError("experiment input outside artifact root") from None
    current = absolute_path.parent
    while True:
        state = os.lstat(current)
        if (
            stat.S_ISLNK(state.st_mode)
            or not stat.S_ISDIR(state.st_mode)
            or bool(getattr(state, "st_file_attributes", 0) & 0x400)
        ):
            raise ValueError("experiment input ancestor invalid")
        if current == resolved_root:
            break
        if current == current.parent:
            raise ValueError("experiment input outside artifact root")
        current = current.parent
    raw = _read_stable_regular(absolute_path)
    if absolute_path.resolve(strict=True) != absolute_path:
        raise ValueError("experiment input path identity drift")
    return ArtifactDigest(
        root_alias=alias,
        relative_path=relative,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _read_stable_regular(path: Path) -> bytes:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("experiment input is not a regular file")
    raw = path.read_bytes()
    after = os.lstat(path)
    if (
        not stat.S_ISREG(after.st_mode)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(raw) != before.st_size
    ):
        raise ValueError("experiment input drift")
    return raw
