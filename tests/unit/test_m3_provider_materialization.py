from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from quant.research.m3.config import load_m3_config
from quant.research.m3.contracts import (
    ProviderBuildSpec,
    ProviderRuntimeFingerprint,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleSnapshotArtifact,
    build_development_example_g1_release,
    compute_development_provider_key,
    compute_development_snapshot_request_key,
    derive_development_example_m3_config,
)
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.provider import (
    M3ProviderError,
    build_provider_runtime_fingerprint,
    inspect_development_example_provider_structure,
    materialize_development_example_qlib_provider,
    materialize_qlib_provider,
    read_provider_manifest,
    verify_development_example_provider_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt
from quant.research.m3.snapshot import (
    build_development_example_snapshot_artifact,
    build_development_example_snapshot_request_record,
    snapshot_request_record_bytes,
    verify_development_example_snapshot_artifact,
)
from quant.research.m3.contracts import SnapshotBuildSpec


def _runtime() -> ProviderRuntimeFingerprint:
    packages = tuple(sorted((
        ("python", "3.12.0"), ("numpy", "1"), ("pandas", "2"),
        ("pyarrow", "3"), ("pyqlib", "0.9.7"), ("fire", "1"),
        ("tqdm", "1"), ("loguru", "1"),
    )))
    raw = json.dumps(
        {"packages": packages, "python_version": "3.12.0"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    return ProviderRuntimeFingerprint(
        python_version="3.12.0",
        packages=packages,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _snapshot(
    common: Path,
) -> tuple[VerifiedDevelopmentExampleSnapshotArtifact, Any, SnapshotBuildSpec]:
    release_root = common / "development-example-g1"
    release_root.mkdir()
    release = build_development_example_g1_release(output_root=release_root)
    base = load_m3_config(Path("configs/research/m3_qlib_example.toml"))
    config = derive_development_example_m3_config(base=base)
    code_version = "development-example/g2b-v1"
    snapshot_key = compute_development_snapshot_request_key(
        release=release,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
    )
    spec = SnapshotBuildSpec(
        snapshot_request_key=snapshot_key,
        config_version=config.config_version,
        snapshot_config_sha256=config.snapshot_config_sha256,
        code_version=code_version,
        history_start=release.manifest.history_start,
        history_end=release.manifest.history_end,
        staging_schema_version="m3-qlib-staging-v1",
        adjustment_formula_version="qlib_yahoo_like_v1",
    )
    root = common / "development-example-snapshot"
    root.mkdir()
    result = build_development_example_snapshot_artifact(
        release=release, config=config, spec=spec, output_root=root
    )
    request = build_development_example_snapshot_request_record(
        release=release, config=config, spec=spec, result=result
    )
    request_path = common / "snapshot-requests" / f"{snapshot_key}.json"
    request_path.parent.mkdir()
    request_path.write_bytes(snapshot_request_record_bytes(request))
    receipt_path = common / "receipts" / "development-snapshot" / f"{snapshot_key}.json"
    receipt_path.parent.mkdir(parents=True)
    release_paths = dict(release.artifact_paths)
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-snapshot",
        scope="SNAPSHOT",
        scope_key=spec.snapshot_request_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            ("root", release_paths["bar_1d.parquet"]),
            ("root", release_paths["universe_membership.parquet"]),
            ("root", release_paths["trade_calendar.parquet"]),
        ],
        outputs=[
            ("root", request_path), ("root", root / "manifest.json"),
            ("root", root / "session_calendar.parquet"),
            *(("root", path) for path in sorted((root / "staging").glob("*.parquet"))),
        ],
    )
    verified = verify_development_example_snapshot_artifact(
        snapshot_root=root,
        snapshot_request_path=request_path,
        snapshot_receipt_path=receipt_path,
        release=release,
        config=config,
        spec=spec,
        artifact_roots={"root": common},
    )
    return verified, config, spec


def _provider_spec(snapshot: VerifiedDevelopmentExampleSnapshotArtifact, config: Any) -> ProviderBuildSpec:
    runtime = _runtime()
    tool = build_qlib_dump_tool_spec(config)
    code_version = "development-example/g2b-v1"
    key = compute_development_provider_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool_sha256=tool.sha256,
        qlib_version=tool.qlib_version,
        provider_runtime_fingerprint_sha256=runtime.sha256,
        code_version=code_version,
    )
    return ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=tool,
        qlib_version="0.9.7",
        code_version=code_version,
        runtime_fingerprint=runtime,
        fields=("open", "high", "low", "close", "vwap", "volume", "factor"),
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )


def _fake_dump(argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    assert kwargs == {
        "shell": False, "check": False, "capture_output": True, "timeout": 30.0,
    }
    assert argv[2:] == (
        "dump_all", "--data_path", argv[4], "--qlib_dir", argv[6],
        "--freq", "day", "--file_suffix", ".parquet", "--date_field_name",
        "date", "--symbol_field_name", "symbol", "--include_fields",
        "open,high,low,close,vwap,volume,factor", "--max_workers", "1",
    )
    staging_root = Path(argv[4])
    qlib_dir = Path(argv[6])
    frames = [pl.read_parquet(path) for path in sorted(staging_root.glob("*.parquet"))]
    dates = sorted({date for frame in frames for date in frame.get_column("date").to_list()})
    (qlib_dir / "calendars").mkdir(parents=True)
    (qlib_dir / "instruments").mkdir()
    (qlib_dir / "features").mkdir()
    (qlib_dir / "calendars" / "day.txt").write_bytes(
        ("\n".join(date.isoformat() for date in dates) + "\n").encode()
    )
    instruments: list[str] = []
    for frame in frames:
        symbol = frame.item(0, "symbol")
        code, market = symbol.split(".")
        qlib_symbol = f"{market.lower()}{code}"
        frame = frame.sort("date")
        symbol_dates = frame.get_column("date").to_list()
        instruments.append(
            f"{qlib_symbol.upper()}\t{symbol_dates[0].isoformat()}\t{symbol_dates[-1].isoformat()}"
        )
        feature_dir = qlib_dir / "features" / qlib_symbol
        feature_dir.mkdir()
        span = dates[dates.index(symbol_dates[0]):dates.index(symbol_dates[-1]) + 1]
        rows = {row[0]: row[1:] for row in frame.select(
            "date", "open", "high", "low", "close", "vwap", "volume", "factor"
        ).iter_rows()}
        for index, field in enumerate(("open", "high", "low", "close", "vwap", "volume", "factor")):
            values = [float(dates.index(symbol_dates[0]))]
            values.extend(np.nan if date not in rows else rows[date][index] for date in span)
            (feature_dir / f"{field}.day.bin").write_bytes(
                np.asarray(values, dtype="<f4").tobytes()
            )
    (qlib_dir / "instruments" / "all.txt").write_bytes(
        ("\n".join(instruments) + "\n").encode()
    )
    return subprocess.CompletedProcess(argv, 0, b"ignored", b"")


def _materialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    spec = _provider_spec(snapshot, config)
    tool = common.parent / "external_qlib" / "dump_bin.py"
    tool.parent.mkdir()
    shutil.copyfile(Path("data/external/qlib/v0.9.7/dump_bin.py"), tool)
    python = Path(sys.executable).resolve()
    output = common / "development-example-provider"
    output.mkdir()
    monkeypatch.setattr("quant.research.m3.provider.build_provider_runtime_fingerprint", _runtime)
    monkeypatch.setattr("quant.research.m3.provider.subprocess.run", _fake_dump)
    result = materialize_development_example_qlib_provider(
        snapshot=snapshot, qlib_dump_script=tool, python_executable=python,
        config=config, spec=spec, output_root=output, timeout_seconds=30.0,
    )
    return common, snapshot, config, spec, tool, result


def test_development_provider_build_manifest_and_receipt_closed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, config, spec, tool, result = _materialized(tmp_path, monkeypatch)
    assert result.manifest.provider_key == spec.provider_key
    assert result.manifest.logical_argv[0] == "<PYTHON>"
    assert all(item.relative_path.startswith("provider/") for item in result.manifest.files)
    assert read_provider_manifest(result.root / "provider_manifest.json") == result.manifest
    receipt_path = common / "development-provider-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=spec.provider_key,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            (
                "root",
                common / "snapshot-requests" / f"{snapshot.request.snapshot_request_key}.json",
            ),
            (
                "root",
                common / "receipts" / "development-snapshot"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[
            ("root", result.root / "provider_manifest.json"),
            *(("root", result.root / item.relative_path) for item in result.manifest.files),
        ],
    )
    verified = verify_development_example_provider_artifact(
        provider_root=result.root,
        provider_receipt_path=receipt_path,
        snapshot=snapshot,
        config=config,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
    )
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.example_id == snapshot.example_id


def test_formal_entry_rejects_development_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    output = common / "formal-provider"
    output.mkdir()
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("quant.research.m3.provider.subprocess.run", forbidden)
    with pytest.raises(M3ProviderError):
        materialize_qlib_provider(
            snapshot=snapshot,  # type: ignore[arg-type]
            qlib_dump_script=Path("missing"),
            python_executable=Path("missing"),
            config=config,
            spec=_provider_spec(snapshot, config),
            output_root=output,
            timeout_seconds=30.0,
        )
    assert called is False
    assert not any(output.iterdir())


def test_receipt_rejects_same_bytes_from_wrong_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, config, spec, tool, result = _materialized(tmp_path, monkeypatch)
    target = result.root / result.manifest.files[0].relative_path
    decoy = common / "same-bytes-wrong-provider-output.bin"
    shutil.copyfile(target, decoy)
    outputs = [
        result.root / "provider_manifest.json",
        *(result.root / item.relative_path for item in result.manifest.files),
    ]
    outputs[1] = decoy
    receipt_path = common / "development-provider-wrong-path-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=spec.provider_key,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            (
                "root",
                common / "snapshot-requests" / f"{snapshot.request.snapshot_request_key}.json",
            ),
            (
                "root",
                common / "receipts" / "development-snapshot"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[("root", path) for path in outputs],
    )
    with pytest.raises(M3ProviderError) as exc:
        verify_development_example_provider_artifact(
            provider_root=result.root,
            provider_receipt_path=receipt_path,
            snapshot=snapshot,
            config=config,
            artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        )
    assert exc.value.code == "DEVELOPMENT_PROVIDER_ARTIFACT_INVALID"


def test_receipt_rejects_request_and_snapshot_receipt_wrong_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, config, spec, tool, result = _materialized(tmp_path, monkeypatch)
    request = common / "snapshot-requests" / f"{snapshot.request.snapshot_request_key}.json"
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    wrong_request = common / "wrong-request.json"
    wrong_snapshot_receipt = common / "wrong-snapshot-receipt.json"
    shutil.copyfile(request, wrong_request)
    shutil.copyfile(snapshot_receipt, wrong_snapshot_receipt)
    receipt_path = common / "development-provider-wrong-input-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=spec.provider_key,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            ("root", wrong_request),
            ("root", wrong_snapshot_receipt),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[
            ("root", result.root / "provider_manifest.json"),
            *(("root", result.root / item.relative_path) for item in result.manifest.files),
        ],
    )
    with pytest.raises(M3ProviderError):
        verify_development_example_provider_artifact(
            provider_root=result.root,
            provider_receipt_path=receipt_path,
            snapshot=snapshot,
            config=config,
            artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        )


def test_receipt_rejects_correct_suffix_in_decoy_root_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, config, spec, tool, result = _materialized(tmp_path, monkeypatch)
    key = snapshot.request.snapshot_request_key
    request = common / "snapshot-requests" / f"{key}.json"
    snapshot_receipt = common / "receipts" / "development-snapshot" / f"{key}.json"
    decoy = tmp_path / "decoy"
    decoy_request = decoy / "snapshot-requests" / f"{key}.json"
    decoy_receipt = decoy / "receipts" / "development-snapshot" / f"{key}.json"
    decoy_request.parent.mkdir(parents=True)
    decoy_receipt.parent.mkdir(parents=True)
    shutil.copyfile(request, decoy_request)
    shutil.copyfile(snapshot_receipt, decoy_receipt)
    roots = {
        "root": common,
        "EXTERNAL_QLIB": tool.parent,
        "DECOY": decoy,
    }
    provider_receipt = common / "development-provider-decoy-input-receipt.json"
    publish_stage_receipt(
        receipt_path=provider_receipt,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=spec.provider_key,
        artifact_roots=roots,
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            ("DECOY", decoy_request),
            ("DECOY", decoy_receipt),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[
            ("root", result.root / "provider_manifest.json"),
            *(("root", result.root / item.relative_path) for item in result.manifest.files),
        ],
    )
    with pytest.raises(M3ProviderError):
        verify_development_example_provider_artifact(
            provider_root=result.root,
            provider_receipt_path=provider_receipt,
            snapshot=snapshot,
            config=config,
            artifact_roots=roots,
        )


def test_dump_tool_spec_must_be_bound_to_loaded_config_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    spec = _provider_spec(snapshot, config)
    forged_tool = replace(
        spec.dump_tool,
        sha256=hashlib.sha256(b"forged").hexdigest(),
        size_bytes=len(b"forged"),
    )
    forged_key = compute_development_provider_key(
        example_id=snapshot.example_id,
        snapshot_id=spec.snapshot_id,
        snapshot_manifest_sha256=spec.snapshot_manifest_sha256,
        provider_config_sha256=spec.provider_config_sha256,
        dump_tool_sha256=forged_tool.sha256,
        qlib_version=spec.qlib_version,
        provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
        code_version=spec.code_version,
    )
    forged_spec = replace(spec, dump_tool=forged_tool, provider_key=forged_key)
    output = common / "development-example-provider-forged-tool"
    output.mkdir()
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("quant.research.m3.provider.subprocess.run", forbidden)
    with pytest.raises(M3ProviderError) as exc:
        materialize_development_example_qlib_provider(
            snapshot=snapshot,
            qlib_dump_script=common / "missing-forged-tool.py",
            python_executable=Path(sys.executable),
            config=config,
            spec=forged_spec,
            output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "DEVELOPMENT_PROVIDER_INPUT_INVALID"
    assert called is False
    assert not any(output.iterdir())


def test_missing_runtime_package_is_sanitized_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    spec = _provider_spec(snapshot, config)
    output = common / "development-example-provider-missing-package"
    output.mkdir()
    monkeypatch.setattr(
        "quant.research.m3.provider.build_provider_runtime_fingerprint",
        lambda: (_ for _ in ()).throw(PackageNotFoundError("pyqlib")),
    )
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("quant.research.m3.provider.subprocess.run", forbidden)
    with pytest.raises(M3ProviderError) as exc:
        materialize_development_example_qlib_provider(
            snapshot=snapshot,
            qlib_dump_script=Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
            python_executable=Path(sys.executable).resolve(),
            config=config,
            spec=spec,
            output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "DEVELOPMENT_PROVIDER_INPUT_INVALID"
    assert called is False
    assert not any(output.iterdir())


def test_nonzero_dump_still_invokes_static_inspector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    spec = _provider_spec(snapshot, config)
    output = common / "development-example-provider-nonzero"
    output.mkdir()
    monkeypatch.setattr(
        "quant.research.m3.provider.build_provider_runtime_fingerprint", _runtime
    )
    monkeypatch.setattr(
        "quant.research.m3.provider.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 9, b"", b""),
    )
    inspected = False

    def inspector(**kwargs: Any) -> None:
        nonlocal inspected
        inspected = True
        raise ValueError("malformed partial tree")

    monkeypatch.setattr(
        "quant.research.m3.provider._inspect_provider_structure", inspector
    )
    with pytest.raises(M3ProviderError) as exc:
        materialize_development_example_qlib_provider(
            snapshot=snapshot,
            qlib_dump_script=Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
            python_executable=Path(sys.executable).resolve(),
            config=config,
            spec=spec,
            output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_DUMP_FAILED"
    assert inspected is True


def test_development_output_rejects_symlinked_parent_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    spec = _provider_spec(snapshot, config)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    real_output = real_parent / "development-example-provider"
    real_output.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlink creation")
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("quant.research.m3.provider.subprocess.run", forbidden)
    with pytest.raises(M3ProviderError) as exc:
        materialize_development_example_qlib_provider(
            snapshot=snapshot,
            qlib_dump_script=Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
            python_executable=Path(sys.executable).resolve(),
            config=config,
            spec=spec,
            output_root=alias / "development-example-provider",
            timeout_seconds=30.0,
        )
    assert exc.value.code == "DEVELOPMENT_PROVIDER_INPUT_INVALID"
    assert called is False
    assert not any(real_output.iterdir())


@pytest.mark.parametrize("mutation", ["missing-factor", "bad-offset", "gap-finite"])
def test_inspector_rejects_bin_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    _, snapshot, _, spec, _, result = _materialized(tmp_path, monkeypatch)
    feature = result.qlib_dir / "features" / "sz000001"
    if mutation == "missing-factor":
        (feature / "factor.day.bin").unlink()
    elif mutation == "bad-offset":
        path = feature / "open.day.bin"
        values = np.frombuffer(path.read_bytes(), dtype="<f4").copy()
        values[0] = np.float32(0.5)
        path.write_bytes(values.tobytes())
    else:
        # 000001.SZ is suspended on the middle session, so this is an interval gap.
        path = feature / "open.day.bin"
        values = np.frombuffer(path.read_bytes(), dtype="<f4").copy()
        values[2] = np.float32(123.0)
        path.write_bytes(values.tobytes())
    with pytest.raises(M3ProviderError):
        inspect_development_example_provider_structure(
            qlib_dir=result.qlib_dir, snapshot=snapshot, spec=spec
        )


def test_runtime_fingerprint_rejects_forged_hash() -> None:
    runtime = _runtime()
    with pytest.raises(ValueError, match="sha256"):
        ProviderRuntimeFingerprint(
            python_version=runtime.python_version,
            packages=runtime.packages,
            sha256="0" * 64,
        )


def test_runtime_fingerprint_reads_metadata_without_importing_qlib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.modules.pop("qlib", None)
    versions = {
        "fire": "1", "loguru": "1", "numpy": "1", "pandas": "1",
        "pyarrow": "1", "pyqlib": "0.9.7", "tqdm": "1",
    }
    monkeypatch.setattr(
        "quant.research.m3.provider.importlib.metadata.version",
        lambda name: versions[name],
    )
    fingerprint = build_provider_runtime_fingerprint()
    assert dict(fingerprint.packages)["pyqlib"] == "0.9.7"
    assert "qlib" not in sys.modules


@pytest.mark.skipif(
    os.environ.get("M3_RUN_REAL_QLIB") != "1",
    reason="explicit py312 real-Qlib smoke only",
)
def test_real_pinned_qlib_dump_static_readback(tmp_path: Path) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    runtime = build_provider_runtime_fingerprint()
    tool = build_qlib_dump_tool_spec(config)
    code_version = "development-example/g2b-real-qlib-v1"
    key = compute_development_provider_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool_sha256=tool.sha256,
        qlib_version=tool.qlib_version,
        provider_runtime_fingerprint_sha256=runtime.sha256,
        code_version=code_version,
    )
    spec = ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=tool,
        qlib_version="0.9.7",
        code_version=code_version,
        runtime_fingerprint=runtime,
        fields=("open", "high", "low", "close", "vwap", "volume", "factor"),
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )
    output = common / "development-example-provider-real-qlib"
    output.mkdir()
    result = materialize_development_example_qlib_provider(
        snapshot=snapshot,
        qlib_dump_script=Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
        python_executable=Path(sys.executable).resolve(),
        config=config,
        spec=spec,
        output_root=output,
        timeout_seconds=60.0,
    )
    assert result.manifest.instrument_count == 3
    assert result.manifest.calendar_count == 3
    assert len(result.manifest.files) == 23
