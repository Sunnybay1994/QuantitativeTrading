"""Deterministic Qlib provider materialization and static verification.

This module never imports Qlib.  The pinned dump tool runs in a child process;
all persisted evidence is rebuilt from the snapshot and the resulting bytes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, ParamSpec, TypeVar, cast

import numpy as np
import polars as pl

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ProviderBuildResult,
    ProviderBuildSpec,
    ProviderManifestV1,
    ProviderRuntimeFingerprint,
    QlibDumpToolSpec,
    VerifiedProviderArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_provider_key,
)
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_provider_key,
    verify_stage_receipt,
)
from quant.research.m3.snapshot import read_snapshot_manifest

_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_PACKAGE_NAMES = ("fire", "loguru", "numpy", "pandas", "pyarrow", "pyqlib", "python", "tqdm")
_LOGICAL_ARGV = (
    "<PYTHON>", "<DUMP_TOOL>", "dump_all", "--data_path",
    "<SNAPSHOT_STAGING>", "--qlib_dir", "<PROVIDER_TEMP>/provider",
    "--freq", "day", "--file_suffix", ".parquet", "--date_field_name",
    "date", "--symbol_field_name", "symbol", "--include_fields",
    "open,high,low,close,vwap,volume,factor", "--max_workers", "1",
)
_MANIFEST_NAME = "provider_manifest.json"
_P = ParamSpec("_P")
_R = TypeVar("_R")


class M3ProviderError(ValueError):
    """Sanitized stable failure at the G2B boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _boundary(code: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                return function(*args, **kwargs)
            except M3ProviderError:
                raise
            except (
                TypeError,
                ValueError,
                OSError,
                importlib.metadata.PackageNotFoundError,
                subprocess.SubprocessError,
                pl.exceptions.PolarsError,
            ):
                raise M3ProviderError(code) from None

        return wrapped

    return decorate


def build_provider_runtime_fingerprint() -> ProviderRuntimeFingerprint:
    """Build the exact, import-free provider runtime identity."""
    python_version = ".".join(str(value) for value in sys.version_info[:3])
    versions: dict[str, str] = {"python": python_version}
    for name in _PACKAGE_NAMES:
        if name == "python":
            continue
        versions[name] = importlib.metadata.version(name)
    packages = tuple(sorted(versions.items()))
    digest = _sha256_json({
        "python_version": python_version,
        "packages": packages,
    })
    return ProviderRuntimeFingerprint(
        python_version=python_version,
        packages=packages,
        sha256=digest,
    )


@_boundary("PROVIDER_INPUT_INVALID")
def materialize_qlib_provider(
    *, snapshot: VerifiedSnapshotArtifact, qlib_dump_script: Path,
    python_executable: Path, config: LoadedM3Config, spec: ProviderBuildSpec,
    output_root: Path, timeout_seconds: float,
) -> ProviderBuildResult:
    """Run the pinned dump tool for a formal verified snapshot."""
    if type(snapshot) is not VerifiedSnapshotArtifact:
        raise ValueError("formal provider requires formal snapshot")
    return _materialize(
        snapshot=snapshot,
        qlib_dump_script=qlib_dump_script,
        python_executable=python_executable,
        config=config,
        spec=spec,
        output_root=output_root,
        timeout_seconds=timeout_seconds,
        development_example_id=None,
    )


@_boundary("DEVELOPMENT_PROVIDER_INPUT_INVALID")
def materialize_development_example_qlib_provider(
    *, snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    qlib_dump_script: Path, python_executable: Path, config: LoadedM3Config,
    spec: ProviderBuildSpec, output_root: Path, timeout_seconds: float,
) -> ProviderBuildResult:
    """Run G2B in the isolated development-example trust domain."""
    if type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact:
        raise ValueError("development provider requires development snapshot")
    _require_development_root(output_root)
    return _materialize(
        snapshot=snapshot,
        qlib_dump_script=qlib_dump_script,
        python_executable=python_executable,
        config=config,
        spec=spec,
        output_root=output_root,
        timeout_seconds=timeout_seconds,
        development_example_id=snapshot.example_id,
    )


def _materialize(
    *, snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    qlib_dump_script: Path, python_executable: Path, config: LoadedM3Config,
    spec: ProviderBuildSpec, output_root: Path, timeout_seconds: float,
    development_example_id: str | None,
) -> ProviderBuildResult:
    with _hold_python_executable(python_executable):
        _validate_preflight(
            snapshot=snapshot,
            qlib_dump_script=qlib_dump_script,
            python_executable=python_executable,
            config=config,
            spec=spec,
            output_root=output_root,
            timeout_seconds=timeout_seconds,
            development_example_id=development_example_id,
        )
        qlib_dir = output_root / "provider"
        argv = (
            str(python_executable), str(qlib_dump_script), "dump_all",
            "--data_path", str(snapshot.root / "staging"),
            "--qlib_dir", str(qlib_dir), "--freq", "day",
            "--file_suffix", ".parquet", "--date_field_name", "date",
            "--symbol_field_name", "symbol", "--include_fields",
            ",".join(_FIELDS), "--max_workers", "1",
        )
        timed_out = False
        completed: subprocess.CompletedProcess[bytes] | None = None
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        try:
            manifest = _inspect_provider_structure(
                qlib_dir=qlib_dir, snapshot=snapshot, spec=spec
            )
        except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
            if timed_out:
                raise M3ProviderError("PROVIDER_DUMP_TIMEOUT") from None
            if completed is not None and completed.returncode != 0:
                raise M3ProviderError("PROVIDER_DUMP_FAILED") from None
            raise
        if timed_out:
            raise M3ProviderError("PROVIDER_DUMP_TIMEOUT")
        if completed is None or completed.returncode != 0:
            raise M3ProviderError("PROVIDER_DUMP_FAILED")
        raw = _canonical_bytes(asdict(manifest))
        _write_exclusive(output_root / _MANIFEST_NAME, raw)
        return ProviderBuildResult(
            root=output_root.resolve(strict=True),
            qlib_dir=qlib_dir.resolve(strict=True),
            manifest=manifest,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )


def _validate_preflight(
    *, snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    qlib_dump_script: Path, python_executable: Path, config: LoadedM3Config,
    spec: ProviderBuildSpec, output_root: Path, timeout_seconds: float,
    development_example_id: str | None,
) -> None:
    if type(config) is not LoadedM3Config or type(spec) is not ProviderBuildSpec:
        raise ValueError("provider config/spec 非法")
    if spec.dump_tool != build_qlib_dump_tool_spec(config):
        raise ValueError("provider dump tool/config drift")
    _require_empty_real_directory(output_root)
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("provider timeout 非法")
    tool_raw = _read_regular(qlib_dump_script)
    if len(tool_raw) != spec.dump_tool.size_bytes:
        raise ValueError("provider dump tool size drift")
    if hashlib.sha256(tool_raw).hexdigest() != spec.dump_tool.sha256:
        raise ValueError("provider dump tool hash drift")
    if spec.dump_tool.command != "dump_all" or spec.qlib_version != spec.dump_tool.qlib_version:
        raise ValueError("provider dump tool identity drift")
    actual_runtime = build_provider_runtime_fingerprint()
    if actual_runtime != spec.runtime_fingerprint:
        raise ValueError("provider runtime drift")
    if dict(actual_runtime.packages)["pyqlib"] != spec.qlib_version:
        raise ValueError("provider runtime Qlib version drift")
    _require_current_python_executable(python_executable)
    if spec.provider_config_sha256 != config.provider_config_sha256:
        raise ValueError("provider config hash drift")
    fields = tuple(cast(Any, config.section("data"))["provider_fields"])
    if fields != spec.fields:
        raise ValueError("provider fields/config drift")
    if (
        spec.snapshot_id != snapshot.manifest.snapshot_id
        or spec.snapshot_manifest_sha256 != snapshot.manifest_sha256
    ):
        raise ValueError("provider snapshot identity drift")
    _verify_snapshot_bytes(snapshot)
    if development_example_id is None:
        expected_key = compute_provider_key(
            snapshot_id=spec.snapshot_id,
            provider_config_hash=spec.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
            code_version=spec.code_version,
        )
    else:
        expected_key = compute_development_provider_key(
            example_id=development_example_id,
            snapshot_id=spec.snapshot_id,
            snapshot_manifest_sha256=spec.snapshot_manifest_sha256,
            provider_config_sha256=spec.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
            code_version=spec.code_version,
        )
    if spec.provider_key != expected_key:
        raise ValueError("provider key drift")


def _verify_snapshot_bytes(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
) -> None:
    manifest_path = snapshot.root / "manifest.json"
    manifest_raw = _read_regular(manifest_path)
    if hashlib.sha256(manifest_raw).hexdigest() != snapshot.manifest_sha256:
        raise ValueError("snapshot manifest drift")
    if read_snapshot_manifest(manifest_path) != snapshot.manifest:
        raise ValueError("snapshot manifest object drift")
    expected = {entry.path: entry for entry in snapshot.manifest.files}
    actual_paths = (snapshot.session_calendar_path, *snapshot.staging_paths)
    actual_rel = tuple(
        path.resolve(strict=True).relative_to(snapshot.root).as_posix()
        for path in actual_paths
    )
    if set(actual_rel) != set(expected):
        raise ValueError("snapshot file closure drift")
    for relative, path in zip(actual_rel, actual_paths, strict=True):
        raw = _read_regular(path)
        if hashlib.sha256(raw).hexdigest() != expected[relative].sha256:
            raise ValueError("snapshot file digest drift")
    seen: set[tuple[str, dt.date]] = set()
    for path in snapshot.staging_paths:
        frame = pl.read_parquet(path)
        for symbol, date in frame.select("symbol", "date").iter_rows():
            key = (cast(str, symbol), cast(dt.date, date))
            if key in seen:
                raise ValueError("snapshot staging duplicate key")
            seen.add(key)


@_boundary("PROVIDER_OUTPUT_INVALID")
def inspect_provider_structure(
    *, qlib_dir: Path, snapshot: VerifiedSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1:
    if type(snapshot) is not VerifiedSnapshotArtifact:
        raise ValueError("formal inspector requires formal snapshot")
    return _inspect_provider_structure(qlib_dir=qlib_dir, snapshot=snapshot, spec=spec)


@_boundary("DEVELOPMENT_PROVIDER_OUTPUT_INVALID")
def inspect_development_example_provider_structure(
    *, qlib_dir: Path, snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1:
    if type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact:
        raise ValueError("development inspector requires development snapshot")
    return _inspect_provider_structure(qlib_dir=qlib_dir, snapshot=snapshot, spec=spec)


def _inspect_provider_structure(
    *, qlib_dir: Path,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1:
    _require_real_directory(qlib_dir)
    expected_root = {"calendars", "instruments", "features"}
    if {entry.name for entry in os.scandir(qlib_dir)} != expected_root:
        raise ValueError("provider root closure invalid")
    for name in expected_root:
        _require_real_directory(qlib_dir / name)

    calendar_path = qlib_dir / "calendars" / "day.txt"
    instrument_path = qlib_dir / "instruments" / "all.txt"
    if {entry.name for entry in os.scandir(calendar_path.parent)} != {"day.txt"}:
        raise ValueError("provider calendar closure invalid")
    if {entry.name for entry in os.scandir(instrument_path.parent)} != {"all.txt"}:
        raise ValueError("provider instrument closure invalid")
    calendar_raw = _read_regular(calendar_path)
    dates = _parse_calendar(calendar_raw)
    snapshot_dates = tuple(
        pl.read_parquet(snapshot.session_calendar_path).get_column("date").to_list()
    )
    if dates != snapshot_dates:
        raise ValueError("provider calendar mismatch")
    calendar_index = {date: index for index, date in enumerate(dates)}

    staging = _read_staging(snapshot)
    ranges = {
        symbol: (frame.get_column("date").min(), frame.get_column("date").max())
        for symbol, frame in staging.items()
    }
    instruments = _parse_instruments(_read_regular(instrument_path))
    expected_instruments = {
        _to_qlib_symbol(symbol).upper(): value for symbol, value in ranges.items()
    }
    if instruments != expected_instruments:
        raise ValueError("provider instruments mismatch")

    features_root = qlib_dir / "features"
    feature_dirs = {entry.name for entry in os.scandir(features_root)}
    expected_dirs = {_to_qlib_symbol(symbol) for symbol in staging}
    if feature_dirs != expected_dirs:
        raise ValueError("provider feature symbols mismatch")
    for symbol, frame in staging.items():
        feature_dir = features_root / _to_qlib_symbol(symbol)
        _require_real_directory(feature_dir)
        expected_files = {f"{field}.day.bin" for field in _FIELDS}
        if {entry.name for entry in os.scandir(feature_dir)} != expected_files:
            raise ValueError("provider feature fields mismatch")
        start = cast(dt.date, frame.get_column("date").min())
        end = cast(dt.date, frame.get_column("date").max())
        start_offset = calendar_index[start]
        span_dates = dates[start_offset:calendar_index[end] + 1]
        by_date = {date: row for date, *row in frame.select("date", *_FIELDS).iter_rows()}
        for field_index, field in enumerate(_FIELDS):
            raw = _read_regular(feature_dir / f"{field}.day.bin")
            if len(raw) != 4 * (1 + len(span_dates)):
                raise ValueError("provider bin span mismatch")
            values = np.frombuffer(raw, dtype="<f4")
            offset = float(values[0])
            if not math.isfinite(offset) or offset < 0 or not offset.is_integer():
                raise ValueError("provider bin offset invalid")
            if int(offset) != start_offset:
                raise ValueError("provider bin offset mismatch")
            actual = values[1:]
            for index, date in enumerate(span_dates):
                expected_row = by_date.get(date)
                if expected_row is None:
                    if not np.isnan(actual[index]):
                        raise ValueError("provider gap must be NaN")
                    continue
                expected = np.float32(expected_row[field_index])
                if actual[index].view(np.uint32) != expected.view(np.uint32):
                    raise ValueError("provider finite value drift")

    files = _tree_digests(qlib_dir)
    range_rows = tuple(
        (
            symbol,
            cast(dt.date, start).isoformat(),
            cast(dt.date, end).isoformat(),
        )
        for symbol, (start, end) in sorted(expected_instruments.items())
    )
    return ProviderManifestV1(
        schema_version="m3-provider-manifest-v1",
        provider_key=spec.provider_key,
        snapshot_id=spec.snapshot_id,
        snapshot_manifest_sha256=spec.snapshot_manifest_sha256,
        provider_config_sha256=spec.provider_config_sha256,
        qlib_version=spec.qlib_version,
        dump_tool_sha256=spec.dump_tool.sha256,
        dump_tool_bytes=spec.dump_tool.size_bytes,
        dump_contract_version=spec.dump_contract_version,
        provider_runtime_fingerprint_sha256=spec.runtime_fingerprint.sha256,
        code_version=spec.code_version,
        frequency=spec.frequency,
        fields=spec.fields,
        storage_dtype="<f4",
        calendar_sha256=hashlib.sha256(calendar_raw).hexdigest(),
        calendar_count=len(dates),
        calendar_start=dates[0],
        calendar_end=dates[-1],
        instrument_count=len(instruments),
        instrument_ranges_sha256=_sha256_json(range_rows),
        output_tree_sha256=_sha256_json(tuple(asdict(item) for item in files)),
        logical_argv=_LOGICAL_ARGV,
        files=files,
    )


def _read_staging(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
) -> dict[str, pl.DataFrame]:
    result: dict[str, pl.DataFrame] = {}
    for path in snapshot.staging_paths:
        frame = pl.read_parquet(path).sort("date")
        expected_columns = ("symbol", "date", *_FIELDS)
        if tuple(frame.columns) != expected_columns or frame.is_empty():
            raise ValueError("provider staging schema invalid")
        symbols = frame.get_column("symbol").unique().to_list()
        if len(symbols) != 1 or type(symbols[0]) is not str:
            raise ValueError("provider staging symbol invalid")
        symbol = symbols[0]
        dates = frame.get_column("date").to_list()
        if dates != sorted(set(dates)):
            raise ValueError("provider staging dates invalid")
        if symbol in result:
            raise ValueError("provider staging symbol duplicate")
        result[symbol] = frame
    return result


def _parse_calendar(raw: bytes) -> tuple[dt.date, ...]:
    text = raw.decode("utf-8")
    lines = text.splitlines()
    if not lines or any(not line for line in lines):
        raise ValueError("provider calendar invalid")
    dates = tuple(dt.date.fromisoformat(line) for line in lines)
    if dates != tuple(sorted(set(dates))):
        raise ValueError("provider calendar ordering invalid")
    return dates


def _parse_instruments(raw: bytes) -> dict[str, tuple[dt.date, dt.date]]:
    rows: dict[str, tuple[dt.date, dt.date]] = {}
    for line in raw.decode("utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError("provider instrument row invalid")
        symbol, start_raw, end_raw = fields
        if symbol != symbol.upper() or symbol in rows:
            raise ValueError("provider instrument symbol invalid")
        start = dt.date.fromisoformat(start_raw)
        end = dt.date.fromisoformat(end_raw)
        if end < start:
            raise ValueError("provider instrument range invalid")
        rows[symbol] = (start, end)
    if not rows:
        raise ValueError("provider instruments empty")
    return rows


def _to_qlib_symbol(symbol: str) -> str:
    code, market = symbol.split(".")
    if market not in {"SH", "SZ"} or len(code) != 6 or not code.isdigit():
        raise ValueError("provider symbol codec invalid")
    return f"{market.lower()}{code}"


def _tree_digests(qlib_dir: Path) -> tuple[ArtifactDigest, ...]:
    files: list[ArtifactDigest] = []
    for root, dirs, names in os.walk(qlib_dir, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            _require_real_directory(root_path / name)
        for name in names:
            path = root_path / name
            raw = _read_regular(path)
            relative = path.relative_to(qlib_dir.parent).as_posix()
            files.append(ArtifactDigest(
                root_alias="provider",
                relative_path=relative,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            ))
    return tuple(sorted(files, key=lambda item: item.relative_path))


@_boundary("PROVIDER_MANIFEST_INVALID")
def read_provider_manifest(path: Path) -> ProviderManifestV1:
    raw = _read_regular(path)
    payload = _strict_json(raw)
    expected = {
        "schema_version", "provider_key", "snapshot_id",
        "snapshot_manifest_sha256", "provider_config_sha256", "qlib_version",
        "dump_tool_sha256", "dump_tool_bytes", "dump_contract_version",
        "provider_runtime_fingerprint_sha256", "code_version", "frequency",
        "fields", "storage_dtype", "calendar_sha256", "calendar_count",
        "calendar_start", "calendar_end", "instrument_count",
        "instrument_ranges_sha256", "output_tree_sha256", "logical_argv", "files",
    }
    if set(payload) != expected or type(payload["files"]) is not list:
        raise ValueError("provider manifest keys invalid")
    files: list[ArtifactDigest] = []
    for item in cast(list[object], payload["files"]):
        if type(item) is not dict or set(item) != {
            "root_alias", "relative_path", "size_bytes", "sha256"
        }:
            raise ValueError("provider manifest file invalid")
        files.append(ArtifactDigest(**cast(dict[str, Any], item)))
    values = dict(payload)
    values["fields"] = tuple(cast(list[str], values["fields"]))
    values["logical_argv"] = tuple(cast(list[str], values["logical_argv"]))
    values["files"] = tuple(files)
    values["calendar_start"] = dt.date.fromisoformat(cast(str, values["calendar_start"]))
    values["calendar_end"] = dt.date.fromisoformat(cast(str, values["calendar_end"]))
    manifest = ProviderManifestV1(**cast(Any, values))
    if _canonical_bytes(asdict(manifest)) != raw:
        raise ValueError("provider manifest not canonical")
    return manifest


@_boundary("PROVIDER_ARTIFACT_INVALID")
def verify_provider_artifact(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderArtifact:
    if type(snapshot) is not VerifiedSnapshotArtifact:
        raise ValueError("formal verifier requires formal snapshot")
    result, receipt_sha = _verify_provider(
        provider_root=provider_root,
        provider_receipt_path=provider_receipt_path,
        snapshot=snapshot,
        config=config,
        artifact_roots=artifact_roots,
        expected_stage="provider",
        development_example_id=None,
    )
    return VerifiedProviderArtifact(
        root=result.root,
        qlib_dir=result.qlib_dir,
        manifest=result.manifest,
        manifest_sha256=result.manifest_sha256,
        provider_receipt_sha256=receipt_sha,
    )


@_boundary("DEVELOPMENT_PROVIDER_ARTIFACT_INVALID")
def verify_development_example_provider_artifact(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleProviderArtifact:
    if type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact:
        raise ValueError("development verifier requires development snapshot")
    _require_development_root(provider_root)
    result, receipt_sha = _verify_provider(
        provider_root=provider_root,
        provider_receipt_path=provider_receipt_path,
        snapshot=snapshot,
        config=config,
        artifact_roots=artifact_roots,
        expected_stage="development-provider",
        development_example_id=snapshot.example_id,
    )
    return VerifiedDevelopmentExampleProviderArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=snapshot.example_id,
        root=result.root,
        qlib_dir=result.qlib_dir,
        manifest=result.manifest,
        manifest_sha256=result.manifest_sha256,
        provider_receipt_sha256=receipt_sha,
    )


def _verify_provider(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
    expected_stage: str, development_example_id: str | None,
) -> tuple[ProviderBuildResult, str]:
    _require_real_directory(provider_root)
    _verify_snapshot_bytes(snapshot)
    if {entry.name for entry in os.scandir(provider_root)} != {"provider", _MANIFEST_NAME}:
        raise ValueError("provider artifact closure invalid")
    manifest_path = provider_root / _MANIFEST_NAME
    raw = _read_regular(manifest_path)
    manifest = read_provider_manifest(manifest_path)
    manifest_sha = hashlib.sha256(raw).hexdigest()
    runtime = build_provider_runtime_fingerprint()
    qlib = cast(Mapping[str, object], config.section("runtime")["qlib"])
    tool = QlibDumpToolSpec(
        url=cast(str, qlib["dump_script_url"]),
        sha256=cast(str, qlib["dump_script_sha256"]),
        size_bytes=cast(int, qlib["dump_script_bytes"]),
        qlib_version=cast(Any, qlib["version"]),
        command="dump_all",
    )
    spec = ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=manifest.provider_key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=tool,
        qlib_version="0.9.7",
        code_version=manifest.code_version,
        runtime_fingerprint=runtime,
        fields=_FIELDS,
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )
    if development_example_id is None:
        expected_key = compute_provider_key(
            snapshot_id=spec.snapshot_id,
            provider_config_hash=spec.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=runtime.sha256,
            code_version=spec.code_version,
        )
    else:
        expected_key = compute_development_provider_key(
            example_id=development_example_id,
            snapshot_id=spec.snapshot_id,
            snapshot_manifest_sha256=spec.snapshot_manifest_sha256,
            provider_config_sha256=spec.provider_config_sha256,
            dump_tool_sha256=spec.dump_tool.sha256,
            qlib_version=spec.qlib_version,
            provider_runtime_fingerprint_sha256=runtime.sha256,
            code_version=spec.code_version,
        )
    if manifest.provider_key != expected_key:
        raise ValueError("provider key invalid")
    rebuilt = _inspect_provider_structure(
        qlib_dir=provider_root / "provider", snapshot=snapshot, spec=spec
    )
    if rebuilt != manifest:
        raise ValueError("provider manifest/content mismatch")
    receipt = verify_stage_receipt(
        receipt_path=provider_receipt_path, artifact_roots=artifact_roots
    )
    if receipt is None or receipt.stage != expected_stage or receipt.scope != "PROVIDER":
        raise ValueError("provider receipt stage invalid")
    if receipt.scope_key != manifest.provider_key:
        raise ValueError("provider receipt key invalid")
    output_paths = (
        manifest_path,
        *(provider_root / item.relative_path for item in manifest.files),
    )
    expected_outputs = tuple(sorted(
        (_digest_for_path(path, artifact_roots) for path in output_paths),
        key=lambda item: (item.root_alias, item.relative_path),
    ))
    if receipt.outputs != expected_outputs:
        raise ValueError("provider receipt outputs invalid")
    required_input_hashes = Counter((
        snapshot.request_sha256,
        snapshot.snapshot_receipt_sha256,
        snapshot.manifest_sha256,
        *(entry.sha256 for entry in snapshot.manifest.files),
        manifest.dump_tool_sha256,
    ))
    input_hashes = Counter(item.sha256 for item in receipt.inputs)
    if input_hashes != required_input_hashes:
        raise ValueError("provider receipt inputs invalid")
    known_input_paths = (
        snapshot.root / "manifest.json",
        snapshot.session_calendar_path,
        *snapshot.staging_paths,
    )
    known_inputs = {
        _digest_for_path(path, artifact_roots) for path in known_input_paths
    }
    if not known_inputs.issubset(set(receipt.inputs)):
        raise ValueError("provider receipt input paths invalid")
    snapshot_stage = (
        "development-snapshot"
        if type(snapshot) is VerifiedDevelopmentExampleSnapshotArtifact
        else "snapshot"
    )
    key = snapshot.request.snapshot_request_key
    snapshot_manifest_digest = _digest_for_path(
        snapshot.root / "manifest.json", artifact_roots
    )
    stage_prefix = _snapshot_stage_prefix(snapshot_manifest_digest.relative_path)
    _require_receipt_input_path(
        receipt.inputs,
        sha256=snapshot.request_sha256,
        root_alias=snapshot_manifest_digest.root_alias,
        relative_path=PurePosixPath(
            *stage_prefix, "snapshot-requests", f"{key}.json"
        ).as_posix(),
    )
    _require_receipt_input_path(
        receipt.inputs,
        sha256=snapshot.snapshot_receipt_sha256,
        root_alias=snapshot_manifest_digest.root_alias,
        relative_path=PurePosixPath(
            *stage_prefix, "receipts", snapshot_stage, f"{key}.json"
        ).as_posix(),
    )
    tool_inputs = tuple(
        item for item in receipt.inputs
        if item.sha256 == manifest.dump_tool_sha256
    )
    if len(tool_inputs) != 1 or (
        tool_inputs[0].root_alias != "EXTERNAL_QLIB"
        or tool_inputs[0].relative_path != "dump_bin.py"
    ):
        raise ValueError("provider receipt dump tool path invalid")
    return (
        ProviderBuildResult(
            root=provider_root.resolve(strict=True),
            qlib_dir=(provider_root / "provider").resolve(strict=True),
            manifest=manifest,
            manifest_sha256=manifest_sha,
        ),
        hashlib.sha256(_read_regular(provider_receipt_path)).hexdigest(),
    )


def _strict_json(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("JSON BOM invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=hook)
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=lambda item: item.isoformat() if type(item) is dt.date else None,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_current_python_executable(python_executable: Path) -> None:
    if not isinstance(python_executable, Path) or not python_executable.is_absolute():
        raise ValueError("provider Python executable drift")
    current = Path(sys.executable)
    resolved = python_executable.resolve(strict=True)
    current_resolved = current.resolve(strict=True)
    if resolved != current_resolved or not resolved.samefile(current_resolved):
        raise ValueError("provider Python executable drift")


def _is_windows_current_python_executable(python_executable: Path) -> bool:
    if os.name != "nt" or not isinstance(python_executable, Path):
        return False
    if not python_executable.is_absolute():
        return False
    try:
        _require_current_python_executable(python_executable)
    except (TypeError, ValueError, OSError):
        return False
    return True


@contextmanager
def _hold_python_executable(python_executable: Path) -> Iterator[None]:
    """Anchor the dump interpreter for the full materialize critical section.

    On Windows, the current ``sys.executable`` may be a legitimate conda hardlink
    (``st_nlink >= 1``). Hold a read-only, no-share-write/delete handle across
    preflight, subprocess, inspection, and manifest write. All other files still
    go through ``_read_regular`` (``st_nlink == 1``).
    """
    if _is_windows_current_python_executable(python_executable):
        handle, fingerprint = _open_windows_current_python_anchor(python_executable)
        try:
            yield
            _verify_windows_current_python_anchor(
                handle, python_executable, fingerprint
            )
        finally:
            if not _close_windows_handle(handle):
                raise ValueError("python executable handle close failed")
        return
    _read_regular(python_executable)
    yield


def _open_windows_current_python_anchor(
    python_executable: Path,
) -> tuple[int, tuple[int, int, int, int, int, str]]:
    _require_current_python_executable(python_executable)
    current = Path(sys.executable)
    _require_no_reparse_chain(python_executable)
    _require_no_reparse_chain(current)
    status = os.lstat(python_executable)
    current_status = os.lstat(current)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_nlink < 1
        or status.st_size <= 0
        or _is_windows_reparse(status)
    ):
        raise ValueError("python executable anchor invalid")
    if (status.st_dev, status.st_ino, status.st_size, status.st_nlink) != (
        current_status.st_dev,
        current_status.st_ino,
        current_status.st_size,
        current_status.st_nlink,
    ):
        raise ValueError("python executable identity drift")
    handle = _open_windows_readonly_no_share_write_delete(python_executable)
    try:
        volume, file_index, size, nlink, attributes = _windows_handle_file_info(handle)
        if attributes & 0x400:
            raise ValueError("python executable reparse rejected")
        if file_index != status.st_ino:
            raise ValueError("python executable identity drift")
        if size != status.st_size or size <= 0:
            raise ValueError("python executable identity drift")
        if nlink != status.st_nlink or nlink < 1:
            raise ValueError("python executable identity drift")
        if (status.st_dev & 0xFFFFFFFF) != (volume & 0xFFFFFFFF):
            raise ValueError("python executable identity drift")
        digest = _windows_handle_sha256(handle, size)
        return handle, (volume, file_index, size, nlink, attributes, digest)
    except Exception:
        _close_windows_handle(handle)
        raise


def _verify_windows_current_python_anchor(
    handle: int,
    python_executable: Path,
    fingerprint: tuple[int, int, int, int, int, str],
) -> None:
    volume, file_index, size, nlink, attributes, digest = fingerprint
    _require_current_python_executable(python_executable)
    current = Path(sys.executable)
    _require_no_reparse_chain(python_executable)
    _require_no_reparse_chain(current)
    status = os.lstat(python_executable)
    current_status = os.lstat(current)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_nlink < 1
        or status.st_size <= 0
        or _is_windows_reparse(status)
    ):
        raise ValueError("python executable anchor invalid")
    if (status.st_dev, status.st_ino, status.st_size, status.st_nlink) != (
        current_status.st_dev,
        current_status.st_ino,
        current_status.st_size,
        current_status.st_nlink,
    ):
        raise ValueError("python executable identity drift")
    actual_volume, actual_index, actual_size, actual_nlink, actual_attributes = (
        _windows_handle_file_info(handle)
    )
    if actual_attributes & 0x400:
        raise ValueError("python executable reparse rejected")
    if (
        actual_volume != volume
        or actual_index != file_index
        or actual_size != size
        or actual_nlink != nlink
        or actual_attributes != attributes
    ):
        raise ValueError("python executable identity drift")
    if actual_index != status.st_ino or actual_size != status.st_size:
        raise ValueError("python executable identity drift")
    if actual_nlink != status.st_nlink or actual_nlink < 1:
        raise ValueError("python executable identity drift")
    if (status.st_dev & 0xFFFFFFFF) != (actual_volume & 0xFFFFFFFF):
        raise ValueError("python executable identity drift")
    if _windows_handle_sha256(handle, actual_size) != digest:
        raise ValueError("python executable digest drift")


def _open_windows_readonly_no_share_write_delete(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    generic_read = 0x80000000
    file_share_read = 0x00000001
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    win_dll = getattr(ctypes, "WinDLL")  # noqa: B009
    create_file = win_dll("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        generic_read,
        file_share_read,
        None,
        open_existing,
        file_flag_open_reparse_point,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if value is None or value == invalid:
        raise OSError(getattr(ctypes, "get_last_error")(), "CreateFileW failed")  # noqa: B009
    return int(value)


def _windows_handle_file_info(handle: int) -> tuple[int, int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    info = _ByHandleFileInformation()
    win_dll = getattr(ctypes, "WinDLL")  # noqa: B009
    function = win_dll(
        "kernel32", use_last_error=True
    ).GetFileInformationByHandle
    function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation))
    function.restype = wintypes.BOOL
    if not function(wintypes.HANDLE(handle), ctypes.byref(info)):
        raise OSError(
            getattr(ctypes, "get_last_error")(),  # noqa: B009
            "GetFileInformationByHandle failed",
        )
    file_index = (int(info.file_index_high) << 32) | int(info.file_index_low)
    size = (int(info.file_size_high) << 32) | int(info.file_size_low)
    return (
        int(info.volume_serial),
        file_index,
        size,
        int(info.number_of_links),
        int(info.attributes),
    )


def _windows_handle_sha256(handle: int, size: int) -> str:
    import ctypes
    from ctypes import wintypes

    if size <= 0:
        raise ValueError("python executable digest drift")
    win_dll = getattr(ctypes, "WinDLL")  # noqa: B009
    set_pointer = win_dll("kernel32", use_last_error=True).SetFilePointerEx
    set_pointer.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    set_pointer.restype = wintypes.BOOL
    read_file = win_dll("kernel32", use_last_error=True).ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    if not set_pointer(wintypes.HANDLE(handle), 0, None, 0):
        raise OSError(getattr(ctypes, "get_last_error")(), "SetFilePointerEx failed")  # noqa: B009
    digest = hashlib.sha256()
    remaining = size
    chunk_size = 1024 * 1024
    while remaining > 0:
        request = min(chunk_size, remaining)
        buffer = ctypes.create_string_buffer(request)
        read = wintypes.DWORD(0)
        if not read_file(
            wintypes.HANDLE(handle),
            buffer,
            request,
            ctypes.byref(read),
            None,
        ):
            raise OSError(getattr(ctypes, "get_last_error")(), "ReadFile failed")  # noqa: B009
        got = int(read.value)
        if got <= 0:
            raise ValueError("python executable digest drift")
        digest.update(buffer.raw[:got])
        remaining -= got
    return digest.hexdigest()


def _close_windows_handle(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")  # noqa: B009
    function = win_dll("kernel32", use_last_error=True).CloseHandle
    function.argtypes = (wintypes.HANDLE,)
    function.restype = wintypes.BOOL
    return bool(function(wintypes.HANDLE(handle)))


def _read_regular(path: Path) -> bytes:
    _require_no_reparse_chain(path)
    status = os.lstat(path)
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
        or _is_windows_reparse(status)
    ):
        raise ValueError("regular unlinked file required")
    return path.read_bytes()


def _require_real_directory(path: Path) -> None:
    _require_no_reparse_chain(path)
    status = os.lstat(path)
    if not stat.S_ISDIR(status.st_mode) or _is_windows_reparse(status):
        raise ValueError("real directory required")
    path.resolve(strict=True)


def _require_empty_real_directory(path: Path) -> None:
    _require_real_directory(path)
    if any(os.scandir(path)):
        raise ValueError("empty output directory required")


def _require_development_root(path: Path) -> None:
    tokens = path.name.lower().replace("_", "-").split("-")
    if "development" not in tokens or "example" not in tokens:
        raise ValueError("development example path marker required")


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _digest_for_path(
    path: Path, artifact_roots: Mapping[str, Path],
) -> ArtifactDigest:
    resolved = path.resolve(strict=True)
    candidates: list[tuple[str, Path]] = []
    for alias, root in artifact_roots.items():
        try:
            relative = resolved.relative_to(root.resolve(strict=True))
        except ValueError:
            continue
        candidates.append((alias, relative))
    if len(candidates) != 1:
        raise ValueError("artifact path root closure invalid")
    alias, relative = candidates[0]
    raw = _read_regular(resolved)
    return ArtifactDigest(
        root_alias=alias,
        relative_path=relative.as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _require_receipt_input_path(
    inputs: tuple[ArtifactDigest, ...], *, sha256: str, root_alias: str,
    relative_path: str,
) -> None:
    matches = tuple(item for item in inputs if item.sha256 == sha256)
    if len(matches) != 1 or (
        matches[0].root_alias != root_alias
        or matches[0].relative_path != relative_path
    ):
        raise ValueError("provider receipt identity input invalid")


def _snapshot_stage_prefix(manifest_relative_path: str) -> tuple[str, ...]:
    parts = PurePosixPath(manifest_relative_path).parts
    if len(parts) >= 3 and parts[-3] == "snapshots" and parts[-1] == "manifest.json":
        return parts[:-3]
    if len(parts) >= 2 and parts[-1] == "manifest.json":
        return ()
    raise ValueError("snapshot manifest path invalid")


def _is_windows_reparse(status: os.stat_result) -> bool:
    attributes = getattr(status, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


_REPARSE_CLEAN_PREFIXES: set[str] = set()


def clear_reparse_chain_cache() -> None:
    """Drop cached clean ancestors (call at each top-level resolve boundary)."""
    _REPARSE_CLEAN_PREFIXES.clear()


def _require_no_reparse_chain(path: Path) -> None:
    # Provider tree digests lstat every file; cache only ancestors already
    # checked clean so each directory is verified once per resolve.
    verified: list[str] = []
    for candidate in (path, *path.parents):
        key = os.fspath(candidate)
        if key in _REPARSE_CLEAN_PREFIXES:
            _REPARSE_CLEAN_PREFIXES.update(verified)
            return
        try:
            status = os.lstat(candidate)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(status.st_mode) or _is_windows_reparse(status):
            raise ValueError("path contains symlink or reparse point")
        verified.append(key)
    _REPARSE_CLEAN_PREFIXES.update(verified)
