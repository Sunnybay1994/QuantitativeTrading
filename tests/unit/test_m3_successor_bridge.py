"""Unit contracts for the production successor bridge request boundary."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import quant.research.m3.successor_bridge as bridge
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.fetch_qlib_tool import DEFAULT_TARGET_PATH, build_qlib_dump_tool_spec
from quant.research.m3.successor_bridge import (
    BRIDGE_INPUT_ERROR,
    REQUEST_SCHEMA_ID,
    SuccessorBridgeError,
    run_production_successor_bridge,
)


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


def _write_request(path: Path, payload: object) -> Path:
    path.write_bytes(_canonical(payload))
    return path


def _minimal_payload(*, project: Path, **overrides: object) -> dict[str, object]:
    fold_a = _hex("release-a")
    fold_b = _hex("release-b")
    base: dict[str, object] = {
        "schema_id": REQUEST_SCHEMA_ID,
        "project_root": str(project.resolve()),
        "controlled_output_root": "output/stage",
        "folds": [
            {
                "fold": "fold_001",
                "config_path": "configs/fold_001.toml",
                "config_raw_sha256": _hex("raw-a"),
                "config_full_sha256": _hex("full-a"),
                "g1_release_path": f"data/clean/m3_g1/releases/{fold_a}",
                "g1_release_id": fold_a,
                "g1_release_manifest_sha256": _hex("manifest-a"),
            },
            {
                "fold": "fold_002",
                "config_path": "configs/fold_002.toml",
                "config_raw_sha256": _hex("raw-b"),
                "config_full_sha256": _hex("full-b"),
                "g1_release_path": f"data/clean/m3_g1/releases/{fold_b}",
                "g1_release_id": fold_b,
                "g1_release_manifest_sha256": _hex("manifest-b"),
            },
        ],
        "runtime_identity": {
            "code_version": "bridge-fixture-v1",
            "dependency_fingerprint_sha256": _hex("deps"),
            "provider_runtime_fingerprint_sha256": _hex("provider"),
        },
        "now": "2026-08-26T10:00:00.000000Z",
        "toolchain": {
            "python_executable": str((project / "toolchain" / "python.exe").resolve()),
            "qlib_dump_tool_path": "data/external/qlib/v0.9.7/dump_bin.py",
            "qlib_dump_tool_size_bytes": 4,
            "qlib_dump_tool_sha256": hashlib.sha256(b"dump").hexdigest(),
            "timeout_seconds": 30.0,
        },
        "resume": False,
    }
    base.update(overrides)
    return base


def _fake_config(*, dump_sha: str, dump_size: int, artifact_root: str = "output/stage") -> LoadedM3Config:
    config = object.__new__(LoadedM3Config)
    object.__setattr__(
        config,
        "document",
        {
            "tracking": {"artifact_root": artifact_root},
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
    object.__setattr__(config, "full_config_sha256", _hex(f"full:{dump_sha}"))
    object.__setattr__(config, "g1_config_sha256", _hex(f"g1:{dump_sha}"))
    object.__setattr__(config, "snapshot_config_sha256", _hex(f"snap:{dump_sha}"))
    object.__setattr__(config, "provider_config_sha256", _hex(f"prov:{dump_sha}"))
    object.__setattr__(config, "scientific_config_sha256", _hex("scientific"))
    object.__setattr__(
        config, "provider_validation_config_sha256", _hex(f"pv:{dump_sha}")
    )
    object.__setattr__(
        config, "label_reconciliation_config_sha256", _hex(f"lr:{dump_sha}")
    )
    object.__setattr__(config, "acceptance_config_sha256", _hex(f"acc:{dump_sha}"))
    object.__setattr__(config, "canonical_tracking_uri", "file:///test")
    object.__setattr__(config, "tracking_target_key", _hex(f"track:{dump_sha}"))
    object.__setattr__(config, "raw_config_sha256", _hex(f"raw:{dump_sha}"))
    return config


def test_rejects_unknown_missing_duplicate_and_noncanonical_request_fields(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    request = tmp_path / "request.json"

    missing = _minimal_payload(project=project)
    del missing["resume"]
    _write_request(request, missing)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    unknown = _minimal_payload(project=project, extra_field=True)
    _write_request(request, unknown)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    payload = _minimal_payload(project=project)
    request.write_text(
        json.dumps(payload, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    request.write_bytes(
        b'{"schema_id":"m3-successor-bridge-request-v1","schema_id":"x"}'
    )
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_rejects_path_subclass_purepath_and_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    request = tmp_path / "request.json"
    _write_request(request, _minimal_payload(project=project))

    class SubPath(type(Path())):  # type: ignore[misc,valid-type]
        pass

    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=SubPath(request))
    assert error.value.code == BRIDGE_INPUT_ERROR

    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=PurePosixPath(request.as_posix()))  # type: ignore[arg-type]
    assert error.value.code == BRIDGE_INPUT_ERROR

    relative = Path("request.json")
    monkeypatch.chdir(tmp_path)
    _write_request(tmp_path / "request.json", _minimal_payload(project=project))
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=relative)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_rejects_request_leaf_symlink_or_reparse_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    real = tmp_path / "real-request.json"
    _write_request(real, _minimal_payload(project=project))
    link = tmp_path / "link-request.json"
    try:
        link.symlink_to(real)
        symlink_ok = True
    except OSError:
        symlink_ok = False

    if symlink_ok:
        link_abs = type(Path())(os.path.abspath(link))
        with pytest.raises(SuccessorBridgeError) as error:
            run_production_successor_bridge(request_path=link_abs)
        assert error.value.code == BRIDGE_INPUT_ERROR

    # Narrow non-following lstat injection for Windows reparse / unavailable symlink.
    request = tmp_path / "reparse-request.json"
    _write_request(request, _minimal_payload(project=project))
    real_lstat = os.lstat

    def reparse_lstat(path: str | bytes | os.PathLike[str]) -> os.stat_result:
        info = real_lstat(path)
        if Path(path) == request:
            return SimpleNamespace(  # type: ignore[return-value]
                st_mode=info.st_mode,
                st_ino=info.st_ino,
                st_dev=info.st_dev,
                st_nlink=info.st_nlink,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
        return info

    monkeypatch.setattr(bridge.os, "lstat", reparse_lstat)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_rejects_member_file_symlink_without_following_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    real_config = project / "configs" / "real.toml"
    real_config.write_bytes(b"config-a")
    link_config = project / "configs" / "fold_001.toml"
    try:
        link_config.symlink_to(real_config)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")

    dump = project / DEFAULT_TARGET_PATH
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"dump")
    python = project / "toolchain" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"py")
    fold_a = _hex("release-a")
    fold_b = _hex("release-b")
    (project / "data" / "clean" / "m3_g1" / "releases" / fold_a).mkdir(parents=True)
    (project / "data" / "clean" / "m3_g1" / "releases" / fold_b).mkdir(parents=True)
    (project / "configs" / "fold_002.toml").write_bytes(b"config-b")

    payload = _minimal_payload(project=project)
    payload["folds"][0]["config_raw_sha256"] = hashlib.sha256(b"config-a").hexdigest()
    payload["folds"][1]["config_raw_sha256"] = hashlib.sha256(b"config-b").hexdigest()
    request = tmp_path / "request.json"
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_rejects_request_bytes_drift_between_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    request = tmp_path / "request.json"
    first = _canonical(_minimal_payload(project=project))
    second = _canonical(_minimal_payload(project=project, resume=True))
    request.write_bytes(first)

    state = {"n": 0}
    real_read = bridge._read_regular_file_bytes

    def flaky(path: Path, *, expected: os.stat_result) -> bytes:
        state["n"] += 1
        if state["n"] == 1:
            return first
        request.write_bytes(second)
        return real_read(path, expected=expected)

    monkeypatch.setattr(bridge, "_read_regular_file_bytes", flaky)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_controlled_root_absent_after_nested_or_identity_failure(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    missing_controlled = project / "output" / "stage"
    assert not missing_controlled.exists()

    payload = _minimal_payload(
        project=project,
        controlled_output_root="output/stage",
        folds=[],
    )
    request = tmp_path / "request.json"
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert not missing_controlled.exists()

    payload = _minimal_payload(
        project=project,
        controlled_output_root="..",
    )
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert not missing_controlled.exists()


def test_rejects_fold_arity_order_and_unreferenced_files(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "configs").mkdir(parents=True)
    request = tmp_path / "request.json"
    payload = _minimal_payload(project=project)
    folds = list(payload["folds"])  # type: ignore[arg-type]
    payload["folds"] = [folds[1], folds[0]]
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    payload = _minimal_payload(project=project)
    only = list(payload["folds"])[0]  # type: ignore[index]
    payload["folds"] = [only]
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    (project / "configs" / "extra.toml").write_bytes(b"extra")
    payload = _minimal_payload(project=project)
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert (project / "configs" / "extra.toml").exists()


def test_rejects_duplicate_fold_ids_before_factory_and_without_controlled_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    controlled = project / "output" / "stage"
    assert not controlled.exists()
    request = tmp_path / "request.json"
    payload = _minimal_payload(project=project)
    first = dict(payload["folds"][0])  # type: ignore[index]
    second = dict(first)
    payload["folds"] = [first, second]
    _write_request(request, payload)

    gate_hits: list[str] = []

    def counting_require() -> None:
        gate_hits.append("entrypoints")
        raise AssertionError("duplicate folds must fail before factory/entry gate")

    monkeypatch.setattr(bridge, "_require_canonical_entrypoints", counting_require)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert gate_hits == []
    assert not controlled.exists()


def test_rejects_wrong_dump_target_and_timeout_types(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    controlled = project / "output" / "stage"
    request = tmp_path / "request.json"
    true_factory = bridge.runtime.make_canonical_successor_production_dependencies
    true_entry = bridge.runtime.run_production_two_fold_successor

    payload = _minimal_payload(project=project)
    toolchain = dict(payload["toolchain"])  # type: ignore[arg-type]
    toolchain["qlib_dump_tool_path"] = "data/external/qlib/other/dump_bin.py"
    payload["toolchain"] = toolchain
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert not controlled.exists()
    assert bridge.runtime.make_canonical_successor_production_dependencies is true_factory
    assert bridge.runtime.run_production_two_fold_successor is true_entry

    # Finite-type / non-positive cases must still go through the canonical writer.
    for bad_timeout in (True, 30, 0.0, -1.0):
        payload = _minimal_payload(project=project)
        toolchain = dict(payload["toolchain"])  # type: ignore[arg-type]
        toolchain["timeout_seconds"] = bad_timeout
        payload["toolchain"] = toolchain
        _write_request(request, payload)
        with pytest.raises(SuccessorBridgeError) as error:
            run_production_successor_bridge(request_path=request)
        assert error.value.code == BRIDGE_INPUT_ERROR
        assert not controlled.exists()
        assert (
            bridge.runtime.make_canonical_successor_production_dependencies
            is true_factory
        )
        assert bridge.runtime.run_production_two_fold_successor is true_entry

    # Non-finite tokens are illegal for allow_nan=False helpers; inject test-owned
    # raw JSON so the loader re-encode boundary returns INPUT (not bare ValueError).
    for token in ("NaN", "Infinity", "-Infinity"):
        payload = _minimal_payload(project=project)
        body = _canonical(payload).decode("ascii")
        needle = '"timeout_seconds":30.0'
        assert needle in body
        request.write_bytes(body.replace(needle, f'"timeout_seconds":{token}').encode("ascii"))
        with pytest.raises(SuccessorBridgeError) as error:
            run_production_successor_bridge(request_path=request)
        assert error.value.code == BRIDGE_INPUT_ERROR
        assert not controlled.exists()
        assert (
            bridge.runtime.make_canonical_successor_production_dependencies
            is true_factory
        )
        assert bridge.runtime.run_production_two_fold_successor is true_entry


def test_rejects_two_fold_tool_spec_drift_via_public_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    (project / "configs").mkdir(parents=True)
    (project / "output" / "stage").mkdir(parents=True)
    dump = project / DEFAULT_TARGET_PATH
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"dump")
    python = project / "toolchain" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"py")
    fold_a = _hex("release-a")
    fold_b = _hex("release-b")
    (project / "data" / "clean" / "m3_g1" / "releases" / fold_a).mkdir(parents=True)
    (project / "data" / "clean" / "m3_g1" / "releases" / fold_b).mkdir(parents=True)
    (project / "configs" / "fold_001.toml").write_bytes(b"config-a")
    (project / "configs" / "fold_002.toml").write_bytes(b"config-b")

    sha_a = hashlib.sha256(b"dump").hexdigest()
    sha_b = hashlib.sha256(b"DUMP").hexdigest()
    assert sha_a != sha_b
    config_a = _fake_config(dump_sha=sha_a, dump_size=4)
    object.__setattr__(
        config_a, "raw_config_sha256", hashlib.sha256(b"config-a").hexdigest()
    )
    object.__setattr__(config_a, "full_config_sha256", _hex("full-a"))
    config_b = _fake_config(dump_sha=sha_b, dump_size=4)
    object.__setattr__(
        config_b, "raw_config_sha256", hashlib.sha256(b"config-b").hexdigest()
    )
    object.__setattr__(config_b, "full_config_sha256", _hex("full-b"))
    assert build_qlib_dump_tool_spec(config_a) != build_qlib_dump_tool_spec(config_b)

    configs = {
        (project / "configs" / "fold_001.toml").resolve(): config_a,
        (project / "configs" / "fold_002.toml").resolve(): config_b,
    }

    from quant.data.m3_release import VerifiedG1Release
    from types import SimpleNamespace as NS

    def load_config(path: Path) -> LoadedM3Config:
        return configs[path.resolve()]

    def fake_verify(*, release: object) -> VerifiedG1Release:
        release_id = getattr(release, "release_id")
        verified = object.__new__(VerifiedG1Release)
        object.__setattr__(verified, "release", release)
        object.__setattr__(verified, "manifest", NS(release_id=release_id))
        object.__setattr__(verified, "manifest_sha256", _hex(f"manifest:{release_id}"))
        object.__setattr__(verified, "quality", NS())
        object.__setattr__(verified, "quality_sha256", _hex(f"quality:{release_id}"))
        object.__setattr__(verified, "artifact_paths", ())
        return verified

    monkeypatch.setattr(bridge, "load_m3_config", load_config)
    monkeypatch.setattr(bridge, "verify_g1_release", fake_verify)

    gate_hits: list[str] = []

    def counting_require() -> None:
        gate_hits.append("entrypoints")
        raise AssertionError("spec drift must fail before factory/entry")

    monkeypatch.setattr(bridge, "_require_canonical_entrypoints", counting_require)

    payload = _minimal_payload(project=project)
    payload["folds"][0]["config_raw_sha256"] = config_a.raw_config_sha256
    payload["folds"][0]["config_full_sha256"] = config_a.full_config_sha256
    payload["folds"][0]["g1_release_id"] = fold_a
    payload["folds"][0]["g1_release_path"] = f"data/clean/m3_g1/releases/{fold_a}"
    payload["folds"][0]["g1_release_manifest_sha256"] = _hex(f"manifest:{fold_a}")
    payload["folds"][1]["config_raw_sha256"] = config_b.raw_config_sha256
    payload["folds"][1]["config_full_sha256"] = config_b.full_config_sha256
    payload["folds"][1]["g1_release_id"] = fold_b
    payload["folds"][1]["g1_release_path"] = f"data/clean/m3_g1/releases/{fold_b}"
    payload["folds"][1]["g1_release_manifest_sha256"] = _hex(f"manifest:{fold_b}")
    payload["toolchain"]["qlib_dump_tool_sha256"] = sha_a
    payload["toolchain"]["python_executable"] = str(python.resolve())

    request = tmp_path / "request.json"
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert gate_hits == []


def test_rejects_wrapper_factory_or_entrypoint_unilateral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    request = tmp_path / "request.json"
    _write_request(request, _minimal_payload(project=project))

    real_factory = bridge.runtime.make_canonical_successor_production_dependencies

    def wrapper_factory() -> object:
        return real_factory()

    monkeypatch.setattr(
        bridge.runtime,
        "make_canonical_successor_production_dependencies",
        wrapper_factory,
    )
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR

    monkeypatch.setattr(
        bridge.runtime,
        "make_canonical_successor_production_dependencies",
        real_factory,
    )
    real_entry = bridge.runtime.run_production_two_fold_successor

    def wrapper_entry(**_kwargs: object) -> object:
        return real_entry(**_kwargs)

    monkeypatch.setattr(
        bridge.runtime,
        "run_production_two_fold_successor",
        wrapper_entry,
    )
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_rejects_bilateral_same_impostor_on_factory_and_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    request = tmp_path / "request.json"
    _write_request(request, _minimal_payload(project=project))

    true_factory = bridge.runtime.make_canonical_successor_production_dependencies
    true_entry = bridge.runtime.run_production_two_fold_successor

    def impostor_factory() -> object:
        return true_factory()

    def impostor_entry(**kwargs: object) -> object:
        return true_entry(**kwargs)

    # Bilateral same impostor: module attrs both replaced; closure true-body still rejects.
    monkeypatch.setattr(
        bridge.runtime,
        "make_canonical_successor_production_dependencies",
        impostor_factory,
    )
    monkeypatch.setattr(
        bridge.runtime,
        "run_production_two_fold_successor",
        impostor_entry,
    )
    # Also overwrite any leftover module-level aliases if present.
    if hasattr(bridge, "_CANONICAL_FACTORY"):
        monkeypatch.setattr(bridge, "_CANONICAL_FACTORY", impostor_factory)
    if hasattr(bridge, "_CANONICAL_ENTRY"):
        monkeypatch.setattr(bridge, "_CANONICAL_ENTRY", impostor_entry)

    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR


def test_dump_toctou_same_size_content_swap_rejects_before_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    (project / "configs").mkdir(parents=True)
    controlled = project / "output" / "stage"
    controlled.mkdir(parents=True)
    marker = controlled / "preexisting.txt"
    marker.write_bytes(b"keep")
    before_names = sorted(path.name for path in controlled.iterdir())
    before_marker = marker.read_bytes()
    dump = project / DEFAULT_TARGET_PATH
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"dump")
    python = project / "toolchain" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"py")
    for fold, label in (("fold_001", "config-a"), ("fold_002", "config-b")):
        (project / "configs" / f"{fold}.toml").write_bytes(label.encode("ascii"))
        rid = _hex(f"release:{fold}")
        (project / "data" / "clean" / "m3_g1" / "releases" / rid).mkdir(parents=True)

    sha = hashlib.sha256(b"dump").hexdigest()
    configs: dict[Path, LoadedM3Config] = {}
    for fold, label in (("fold_001", "config-a"), ("fold_002", "config-b")):
        path = (project / "configs" / f"{fold}.toml").resolve()
        item = _fake_config(dump_sha=sha, dump_size=4)
        object.__setattr__(item, "raw_config_sha256", hashlib.sha256(label.encode()).hexdigest())
        object.__setattr__(item, "full_config_sha256", _hex(f"full:{label}"))
        configs[path] = item

    from quant.data.m3_release import VerifiedG1Release
    from types import SimpleNamespace as NS

    def load_config(path: Path) -> LoadedM3Config:
        return configs[path.resolve()]

    def fake_verify(*, release: object) -> VerifiedG1Release:
        release_id = getattr(release, "release_id")
        verified = object.__new__(VerifiedG1Release)
        object.__setattr__(verified, "release", release)
        object.__setattr__(verified, "manifest", NS(release_id=release_id))
        object.__setattr__(verified, "manifest_sha256", _hex(f"manifest:{release_id}"))
        object.__setattr__(verified, "quality", NS())
        object.__setattr__(verified, "quality_sha256", _hex(f"quality:{release_id}"))
        object.__setattr__(verified, "artifact_paths", ())
        return verified

    # Approved seams only: config/G1 fakes. Canonical factory/entry/package callables
    # and `_require_canonical_entrypoints` stay untouched.
    monkeypatch.setattr(bridge, "load_m3_config", load_config)
    monkeypatch.setattr(bridge, "verify_g1_release", fake_verify)
    monkeypatch.setattr(
        bridge.runtime,
        "load_m3_config",
        load_config,
    )

    payload = _minimal_payload(project=project)
    for idx, (fold, label) in enumerate(
        (("fold_001", "config-a"), ("fold_002", "config-b"))
    ):
        rid = _hex(f"release:{fold}")
        payload["folds"][idx]["config_raw_sha256"] = hashlib.sha256(
            label.encode()
        ).hexdigest()
        payload["folds"][idx]["config_full_sha256"] = _hex(f"full:{label}")
        payload["folds"][idx]["g1_release_id"] = rid
        payload["folds"][idx]["g1_release_path"] = f"data/clean/m3_g1/releases/{rid}"
        payload["folds"][idx]["g1_release_manifest_sha256"] = _hex(f"manifest:{rid}")
    payload["toolchain"]["python_executable"] = str(python.resolve())
    payload["toolchain"]["qlib_dump_tool_sha256"] = sha

    dump_resolved = dump.resolve()
    state = {"dump_reads": 0, "swapped": False}
    real_read = bridge._read_regular_file_bytes

    def swap_dump(path: Path, *, expected: os.stat_result) -> bytes:
        if path.resolve() == dump_resolved:
            state["dump_reads"] += 1
            if state["dump_reads"] == 1:
                data = real_read(path, expected=expected)
                # Same size, different content — classic TOCTOU swap / mtime drift.
                dump.write_bytes(b"DUMP")
                state["swapped"] = True
                return data
        return real_read(path, expected=expected)

    monkeypatch.setattr(bridge, "_read_regular_file_bytes", swap_dump)

    true_factory = bridge.runtime.make_canonical_successor_production_dependencies
    true_entry = bridge.runtime.run_production_two_fold_successor
    true_require = bridge._require_canonical_entrypoints

    request = tmp_path / "request.json"
    _write_request(request, payload)
    with pytest.raises(SuccessorBridgeError) as error:
        run_production_successor_bridge(request_path=request)
    assert error.value.code == BRIDGE_INPUT_ERROR
    assert state["swapped"] is True
    assert state["dump_reads"] >= 1
    # Entry/factory never reached: authority objects and identity gate unchanged;
    # controlled root retains only the preexisting marker (zero bridge write).
    assert bridge.runtime.make_canonical_successor_production_dependencies is true_factory
    assert bridge.runtime.run_production_two_fold_successor is true_entry
    assert bridge._require_canonical_entrypoints is true_require
    assert sorted(path.name for path in controlled.iterdir()) == before_names
    assert marker.read_bytes() == before_marker
    assert not (controlled / "completion.json").exists()
    assert not any(controlled.glob("**/receipts/**"))


def test_bridge_source_calls_factory_and_entry_exactly_once() -> None:
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_production_successor_bridge"
    )
    factory_calls = 0
    entry_calls = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "make_canonical_successor_production_dependencies":
                factory_calls += 1
            if func.attr == "run_production_two_fold_successor":
                entry_calls += 1
    assert factory_calls == 1
    assert entry_calls == 1
