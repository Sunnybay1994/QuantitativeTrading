"""Integration fixtures for the production successor bridge (no actual worker)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import quant.research.m3.successor_bridge as bridge
import quant.research.m3.successor_runtime as runtime
from quant.data.m3_release import VerifiedG1Release
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.fetch_qlib_tool import DEFAULT_TARGET_PATH
from quant.research.m3.successor_bridge import (
    BRIDGE_INPUT_ERROR,
    BRIDGE_RUNTIME_ERROR,
    REQUEST_SCHEMA_ID,
    SuccessorBridgeError,
    run_production_successor_bridge,
)


def _load_runtime_integration() -> ModuleType:
    path = Path(__file__).with_name("test_m3_successor_runtime.py")
    spec = importlib.util.spec_from_file_location(
        "m3_successor_runtime_integration_fixture", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RUNTIME_IT = _load_runtime_integration()
_DeterministicProductionBoundary = _RUNTIME_IT._DeterministicProductionBoundary
_install_fixture_verifiers = _RUNTIME_IT._install_fixture_verifiers


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _config(
    *, raw: str, full: str, scientific: str, dump_sha: str, dump_size: int
) -> LoadedM3Config:
    config = object.__new__(LoadedM3Config)
    object.__setattr__(
        config,
        "document",
        {
            "tracking": {"artifact_root": "output/stage"},
            "runtime": {
                "qlib": {
                    "dump_script_url": "https://example.invalid/dump_bin.py",
                    "dump_script_sha256": dump_sha,
                    "dump_script_bytes": dump_size,
                    "version": "0.9.7",
                }
            },
        },
    )
    object.__setattr__(config, "config_version", "test-config-v1")
    object.__setattr__(config, "full_config_sha256", full)
    object.__setattr__(config, "g1_config_sha256", _hex(f"g1:{raw}"))
    object.__setattr__(config, "snapshot_config_sha256", _hex(f"snapshot:{raw}"))
    object.__setattr__(config, "provider_config_sha256", _hex(f"provider:{raw}"))
    object.__setattr__(config, "scientific_config_sha256", scientific)
    object.__setattr__(
        config,
        "provider_validation_config_sha256",
        _hex(f"provider-validation:{raw}"),
    )
    object.__setattr__(
        config,
        "label_reconciliation_config_sha256",
        _hex(f"label-reconciliation:{raw}"),
    )
    object.__setattr__(config, "acceptance_config_sha256", _hex(f"acceptance:{raw}"))
    object.__setattr__(config, "canonical_tracking_uri", "file:///test")
    object.__setattr__(config, "tracking_target_key", _hex(f"tracking:{raw}"))
    object.__setattr__(config, "raw_config_sha256", raw)
    return config


def _release(*, project_root: Path, fold: str) -> VerifiedG1Release:
    release_id = _hex(f"release:{fold}")
    release_root = project_root / "data" / "clean" / "m3_g1" / "releases" / release_id
    release_root.mkdir(parents=True)
    release = SimpleNamespace(root=release_root, release_id=release_id)
    manifest = SimpleNamespace(release_id=release_id)
    verified = object.__new__(VerifiedG1Release)
    object.__setattr__(verified, "release", release)
    object.__setattr__(verified, "manifest", manifest)
    object.__setattr__(verified, "manifest_sha256", _hex(f"manifest:{fold}"))
    object.__setattr__(verified, "quality", SimpleNamespace())
    object.__setattr__(verified, "quality_sha256", _hex(f"quality:{fold}"))
    object.__setattr__(verified, "artifact_paths", ())
    return verified


def _prepare_bridge_fixture(tmp_path: Path) -> tuple[
    Path,
    Path,
    _DeterministicProductionBoundary,
    dict[Path, LoadedM3Config],
    dict[str, VerifiedG1Release],
    bytes,
]:
    project = tmp_path / "successor-project"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    python_path = type(Path())(project / "toolchain" / "python.exe")
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"fixture-python")
    dump_bytes = b"dump"
    dump_path = type(Path())(project / DEFAULT_TARGET_PATH)
    dump_path.parent.mkdir(parents=True)
    dump_path.write_bytes(dump_bytes)
    dump_sha = hashlib.sha256(dump_bytes).hexdigest()

    scientific = _hex("scientific")
    configs: dict[Path, LoadedM3Config] = {}
    releases: dict[str, VerifiedG1Release] = {}
    fold_payloads: list[dict[str, object]] = []
    for fold, raw_label in (("fold_001", "config-a"), ("fold_002", "config-b")):
        raw_bytes = raw_label.encode("ascii")
        raw = hashlib.sha256(raw_bytes).hexdigest()
        full = _hex(f"full:{raw_label}")
        config = _config(
            raw=raw,
            full=full,
            scientific=scientific,
            dump_sha=dump_sha,
            dump_size=len(dump_bytes),
        )
        path = project / "configs" / f"{fold}.toml"
        path.write_bytes(raw_bytes)
        configs[path.resolve()] = config
        release = _release(project_root=project, fold=fold)
        releases[release.release.release_id] = release
        fold_payloads.append(
            {
                "fold": fold,
                "config_path": f"configs/{fold}.toml",
                "config_raw_sha256": raw,
                "config_full_sha256": full,
                "g1_release_path": (
                    f"data/clean/m3_g1/releases/{release.release.release_id}"
                ),
                "g1_release_id": release.release.release_id,
                "g1_release_manifest_sha256": release.manifest_sha256,
            }
        )

    payload = {
        "schema_id": REQUEST_SCHEMA_ID,
        "project_root": str(project.resolve()),
        "controlled_output_root": "output/stage",
        "folds": fold_payloads,
        "runtime_identity": {
            "code_version": "successor-bridge-fixture-v1",
            "dependency_fingerprint_sha256": _hex("dependencies"),
            "provider_runtime_fingerprint_sha256": _hex("provider-runtime"),
        },
        "now": "2026-08-26T12:00:00.000000Z",
        "toolchain": {
            "python_executable": str(python_path.resolve()),
            "qlib_dump_tool_path": DEFAULT_TARGET_PATH.as_posix(),
            "qlib_dump_tool_size_bytes": len(dump_bytes),
            "qlib_dump_tool_sha256": dump_sha,
            "timeout_seconds": 30.0,
        },
        "resume": True,
    }
    request_path = tmp_path / "bridge-request.json"
    raw_request = _canonical(payload)
    request_path.write_bytes(raw_request)
    boundary = _DeterministicProductionBoundary(project)
    return request_path, project, boundary, configs, releases, raw_request


def _install_bridge_verifiers(
    monkeypatch: pytest.MonkeyPatch,
    configs: dict[Path, LoadedM3Config],
    releases: dict[str, VerifiedG1Release],
    boundary: object,
) -> None:
    def load_config(path: Path) -> LoadedM3Config:
        return configs[path.resolve()]

    def verify_release(*, release: object) -> VerifiedG1Release:
        release_id = getattr(release, "release_id")
        assert type(release_id) is str
        return releases[release_id]

    monkeypatch.setattr(bridge, "load_m3_config", load_config)
    monkeypatch.setattr(bridge, "verify_g1_release", verify_release)
    monkeypatch.setattr(bridge.runtime, "load_m3_config", load_config)
    monkeypatch.setattr(bridge.runtime, "verify_g1_release", verify_release)
    _install_fixture_verifiers(
        monkeypatch,
        configs,
        releases,
        boundary.public_apis,
        boundary,
    )


def test_bridge_reaches_two_folds_without_replacing_canonical_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _project, boundary, configs, releases, _raw = _prepare_bridge_fixture(
        tmp_path
    )
    _install_bridge_verifiers(monkeypatch, configs, releases, boundary)

    true_factory = bridge.runtime.make_canonical_successor_production_dependencies
    true_entry = bridge.runtime.run_production_two_fold_successor

    result = run_production_successor_bridge(request_path=request_path)

    # True-body identity must remain intact after a successful fixture run.
    assert (
        bridge.runtime.make_canonical_successor_production_dependencies is true_factory
    )
    assert bridge.runtime.run_production_two_fold_successor is true_entry
    assert result.reused is False
    assert tuple(item.fold for item in result.folds) == ("fold_001", "fold_002")
    assert tuple(item.gate for item in result.gates) == (
        "summary",
        "reproducibility",
        "readiness",
        "acceptance",
    )
    assert result.attestation.terminal_status == "PASS"


def test_resume_false_rejects_existing_terminal_resume_true_reuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, project, boundary, configs, releases, raw = _prepare_bridge_fixture(
        tmp_path
    )
    _install_bridge_verifiers(monkeypatch, configs, releases, boundary)

    first = run_production_successor_bridge(request_path=request_path)
    assert first.reused is False
    assert (project / "output" / "stage" / runtime.TERMINAL_FILENAME).exists()

    # resume=false must reject an already-complete terminal.
    payload = json.loads(raw.decode("ascii"))
    payload["resume"] = False
    request_path.write_bytes(_canonical(payload))
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request_path)
    assert error.value.code == BRIDGE_RUNTIME_ERROR

    # resume=true reuses the exact retained terminal.
    payload["resume"] = True
    request_path.write_bytes(_canonical(payload))
    second = run_production_successor_bridge(request_path=request_path)
    assert second.reused is True
    assert second.attestation.two_fold_identity == first.attestation.two_fold_identity

    # Toolchain size drift must reject retained terminal reuse.
    payload["toolchain"]["qlib_dump_tool_size_bytes"] = 5
    request_path.write_bytes(_canonical(payload))
    with pytest.raises(SuccessorBridgeError) as drift_error:
        run_production_successor_bridge(request_path=request_path)
    assert drift_error.value.code == BRIDGE_INPUT_ERROR

    # Restore size; toolchain SHA drift also rejects.
    payload["toolchain"]["qlib_dump_tool_size_bytes"] = 4
    payload["toolchain"]["qlib_dump_tool_sha256"] = _hex("wrong-dump-sha")
    request_path.write_bytes(_canonical(payload))
    with pytest.raises(SuccessorBridgeError) as sha_error:
        run_production_successor_bridge(request_path=request_path)
    assert sha_error.value.code == BRIDGE_INPUT_ERROR

    # Restore toolchain; request runtime identity drift must reject old terminal.
    payload["toolchain"]["qlib_dump_tool_sha256"] = hashlib.sha256(b"dump").hexdigest()
    payload["runtime_identity"]["code_version"] = "drifted-code-version"
    request_path.write_bytes(_canonical(payload))
    with pytest.raises(SuccessorBridgeError) as identity_error:
        run_production_successor_bridge(request_path=request_path)
    assert identity_error.value.code == BRIDGE_RUNTIME_ERROR
    assert second.attestation.two_fold_identity == first.attestation.two_fold_identity


def test_wrong_config_sha_fails_without_discovering_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, project, boundary, configs, releases, raw = _prepare_bridge_fixture(
        tmp_path
    )
    _install_bridge_verifiers(monkeypatch, configs, releases, boundary)
    sibling = project / "configs" / "unreferenced.toml"
    sibling.write_bytes(b"should-not-be-opened")

    payload = json.loads(raw.decode("ascii"))
    payload["folds"][0]["config_raw_sha256"] = _hex("wrong-raw")
    request_path.write_bytes(_canonical(payload))

    opened: list[Path] = []
    real_read = bridge._read_regular_file_bytes

    def tracked(path: Path, *, expected: object) -> bytes:
        opened.append(path)
        return real_read(path, expected=expected)  # type: ignore[arg-type]

    monkeypatch.setattr(bridge, "_read_regular_file_bytes", tracked)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request_path)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert sibling not in opened
    assert sibling.read_bytes() == b"should-not-be-opened"


def test_controlled_exists_but_artifact_mismatch_leaves_tree_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, project, boundary, configs, releases, raw = _prepare_bridge_fixture(
        tmp_path
    )
    _install_bridge_verifiers(monkeypatch, configs, releases, boundary)
    controlled = project / "output" / "stage"
    sentinel = controlled / "preexisting-sentinel.bin"
    sentinel.write_bytes(b"keep")
    before = {
        path.relative_to(controlled).as_posix(): path.read_bytes()
        if path.is_file()
        else None
        for path in controlled.rglob("*")
    }

    # Point fold_002 artifact_root away from controlled while keeping fold_001.
    drifted = configs[(project / "configs" / "fold_002.toml").resolve()]
    object.__setattr__(
        drifted,
        "document",
        {
            "tracking": {"artifact_root": "output/other-stage"},
            "runtime": drifted.document["runtime"],
        },
    )

    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request_path)
    assert error.value.code == BRIDGE_INPUT_ERROR

    after = {
        path.relative_to(controlled).as_posix(): path.read_bytes()
        if path.is_file()
        else None
        for path in controlled.rglob("*")
    }
    assert after == before
    assert not (controlled / runtime.TERMINAL_FILENAME).exists()
    assert not (controlled / "receipts").exists()
    assert list(controlled.glob(".completion.json.*.tmp")) == []
