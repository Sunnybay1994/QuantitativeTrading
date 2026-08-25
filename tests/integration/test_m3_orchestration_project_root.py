"""PROJECT-only digest remapping for identity-resolved orchestration builders."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant.research.m3.orchestration as orchestration
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import ProviderBuildSpec
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleSnapshotArtifact,
)
from quant.research.m3.orchestration import (
    ExternalInput,
    RunPlan,
    StageNode,
    StaticDirectoryPublication,
    make_provider_materialization_run_plan,
    select_run_plan_nodes,
)
from quant.research.m3.run_state import ArtifactDigest

_KEY = "3" * 64
_SHA = "5" * 64
_EXAMPLE = "development-example-project-root-v1"


def _unchecked(cls: type[object], **values: object) -> object:
    value = object.__new__(cls)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    return value


def _config() -> LoadedM3Config:
    digest = "2" * 64
    return LoadedM3Config(
        document={"labels": {"horizons_sessions": (5, 10)}},
        config_version="test",
        full_config_sha256=digest,
        g1_config_sha256=digest,
        snapshot_config_sha256=digest,
        provider_config_sha256=digest,
        scientific_config_sha256=digest,
        provider_validation_config_sha256=digest,
        label_reconciliation_config_sha256=digest,
        acceptance_config_sha256=digest,
        canonical_tracking_uri="test",
        tracking_target_key=digest,
    )


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _snapshot_bundle(stage: Path) -> VerifiedDevelopmentExampleSnapshotArtifact:
    snapshot_id = _KEY
    request_key = "4" * 64
    snapshot_root = stage / "snapshots" / snapshot_id
    for relative, payload in (
        (f"snapshots/{snapshot_id}/manifest.json", b"snapshot-manifest"),
        (f"snapshots/{snapshot_id}/session_calendar.parquet", b"calendar"),
        (f"snapshot-requests/{request_key}.json", b"snapshot-request"),
        (f"receipts/development-snapshot/{request_key}.json", b"snapshot-receipt"),
    ):
        _write(stage / relative, payload)
    return _unchecked(  # type: ignore[return-value]
        VerifiedDevelopmentExampleSnapshotArtifact,
        example_id=_EXAMPLE,
        root=snapshot_root,
        manifest=SimpleNamespace(
            snapshot_id=snapshot_id,
            g1_release_id=_KEY,
            g1_release_manifest_sha256=_SHA,
            signal_start="2020-01-01",
            signal_end="2020-01-31",
        ),
        manifest_sha256=hashlib.sha256(b"snapshot-manifest").hexdigest(),
        request=SimpleNamespace(snapshot_request_key=request_key),
        request_sha256=hashlib.sha256(b"snapshot-request").hexdigest(),
        snapshot_receipt_sha256=hashlib.sha256(b"snapshot-receipt").hexdigest(),
        staging_paths=(),
    )


def test_verified_digest_project_remap_changes_alias_and_relative(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    stage = project / "output" / "stage"
    leaf = stage / "snapshots" / "a" / "manifest.json"
    _write(leaf, b"payload")

    legacy = orchestration._verified_digest(leaf, root=stage, alias="stage")
    remapped = orchestration._verified_digest(
        leaf, root=stage, alias="stage", artifact_roots={"PROJECT": project},
    )
    assert legacy.root_alias == "stage"
    assert legacy.relative_path == "snapshots/a/manifest.json"
    assert remapped.root_alias == "PROJECT"
    assert remapped.relative_path == "output/stage/snapshots/a/manifest.json"
    assert remapped.sha256 == legacy.sha256
    assert remapped.size_bytes == legacy.size_bytes


def test_legacy_none_and_omitted_roots_are_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    stage = project / "output" / "stage"
    dump_tool = project / "tools" / "dump_bin.py"
    _write(dump_tool, b"dump")
    snapshot = _snapshot_bundle(stage)
    spec = _unchecked(
        ProviderBuildSpec,
        snapshot_id=_KEY,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=_KEY,
        provider_config_sha256="2" * 64,
        dump_tool=SimpleNamespace(
            sha256=hashlib.sha256(b"dump").hexdigest(),
            size_bytes=4,
        ),
        qlib_version="0.9.7",
        runtime_fingerprint=SimpleNamespace(sha256=_SHA),
        code_version="development-example/provider-v1",
    )
    monkeypatch.setattr(
        orchestration, "compute_development_provider_key", lambda **_kw: _KEY,
    )
    omitted = make_provider_materialization_run_plan(
        config=_config(),
        snapshot=snapshot,
        spec=spec,  # type: ignore[arg-type]
        dump_tool_path=dump_tool,
    )
    explicit = make_provider_materialization_run_plan(
        config=_config(),
        snapshot=snapshot,
        spec=spec,  # type: ignore[arg-type]
        dump_tool_path=dump_tool,
        artifact_roots=None,
    )
    assert asdict(omitted) == asdict(explicit)
    assert {
        item.artifact.root_alias
        for item in omitted.nodes[0].inputs
        if type(item) is ExternalInput
    } == {"stage", "qlib-dump-tool"}


def test_provider_builder_project_roots_require_recomputed_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    stage = project / "output" / "stage"
    dump_tool = project / "tools" / "dump_bin.py"
    _write(dump_tool, b"dump")
    snapshot = _snapshot_bundle(stage)
    spec = _unchecked(
        ProviderBuildSpec,
        snapshot_id=_KEY,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=_KEY,
        provider_config_sha256="2" * 64,
        dump_tool=SimpleNamespace(
            sha256=hashlib.sha256(b"dump").hexdigest(),
            size_bytes=4,
        ),
        qlib_version="0.9.7",
        runtime_fingerprint=SimpleNamespace(sha256=_SHA),
        code_version="development-example/provider-v1",
    )
    monkeypatch.setattr(
        orchestration, "compute_development_provider_key", lambda **_kw: _KEY,
    )
    legacy = make_provider_materialization_run_plan(
        config=_config(),
        snapshot=snapshot,
        spec=spec,  # type: ignore[arg-type]
        dump_tool_path=dump_tool,
    )
    remapped = make_provider_materialization_run_plan(
        config=_config(),
        snapshot=snapshot,
        spec=spec,  # type: ignore[arg-type]
        dump_tool_path=dump_tool,
        artifact_roots={"PROJECT": project},
    )
    legacy_paths = {
        item.artifact.relative_path
        for item in legacy.nodes[0].inputs
        if type(item) is ExternalInput
    }
    remapped_inputs = tuple(
        item.artifact
        for item in remapped.nodes[0].inputs
        if type(item) is ExternalInput
    )
    assert {item.root_alias for item in remapped_inputs} == {"PROJECT"}
    remapped_paths = {item.relative_path for item in remapped_inputs}
    assert legacy_paths != remapped_paths
    assert all((project / item.relative_path).is_file() for item in remapped_inputs)


def test_nested_duplicate_and_escaped_roots_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    stage = project / "output" / "stage"
    dump_tool = project / "tools" / "dump_bin.py"
    outside = tmp_path / "outside" / "dump_bin.py"
    _write(dump_tool, b"dump")
    _write(outside, b"dump")
    snapshot = _snapshot_bundle(stage)
    spec = _unchecked(
        ProviderBuildSpec,
        snapshot_id=_KEY,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=_KEY,
        provider_config_sha256="2" * 64,
        dump_tool=SimpleNamespace(
            sha256=hashlib.sha256(b"dump").hexdigest(),
            size_bytes=4,
        ),
        qlib_version="0.9.7",
        runtime_fingerprint=SimpleNamespace(sha256=_SHA),
        code_version="development-example/provider-v1",
    )
    monkeypatch.setattr(
        orchestration, "compute_development_provider_key", lambda **_kw: _KEY,
    )
    with pytest.raises(ValueError, match="嵌套"):
        make_provider_materialization_run_plan(
            config=_config(),
            snapshot=snapshot,
            spec=spec,  # type: ignore[arg-type]
            dump_tool_path=dump_tool,
            artifact_roots={"PROJECT": project, "STAGE": stage},
        )
    with pytest.raises(ValueError, match="物理重复"):
        make_provider_materialization_run_plan(
            config=_config(),
            snapshot=snapshot,
            spec=spec,  # type: ignore[arg-type]
            dump_tool_path=dump_tool,
            artifact_roots={"A": project, "B": project},
        )
    with pytest.raises(ValueError):
        make_provider_materialization_run_plan(
            config=_config(),
            snapshot=snapshot,
            spec=spec,  # type: ignore[arg-type]
            dump_tool_path=outside,
            artifact_roots={"PROJECT": project},
        )


def test_select_run_plan_nodes_is_pure_and_closure_exact(tmp_path: Path) -> None:
    plan = RunPlan(
        "PROVIDER",
        (
            StageNode(
                node_id="provider",
                spec_name="development-provider",
                scope="PROVIDER",
                scope_key=_KEY,
                fold=None,
                horizon=None,
                dependencies=(),
                inputs=(
                    ExternalInput(ArtifactDigest("fixture", "input.json", 1, _SHA)),
                ),
                publication=StaticDirectoryPublication("providers/one"),
                output_specs=orchestration.DEVELOPMENT_PROVIDER_STAGE_SPEC.outputs,
                receipt_path="receipts/development-provider/one.json",
            ),
        ),
    )
    before = list(tmp_path.iterdir()) if tmp_path.exists() else []
    selected = select_run_plan_nodes(
        plan,
        expected_continuation="PROVIDER",
        expected_node_ids=("provider",),
    )
    assert tuple(item.node_id for item in selected) == ("provider",)
    assert (list(tmp_path.iterdir()) if tmp_path.exists() else []) == before
    assert not (tmp_path / "receipts").exists()
    with pytest.raises(ValueError, match="closure"):
        select_run_plan_nodes(
            plan,
            expected_continuation="PROVIDER",
            expected_node_ids=("provider", "extra"),
        )
