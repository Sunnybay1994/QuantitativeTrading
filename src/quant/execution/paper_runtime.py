"""Read-only platform and absent-root environment proof for PAPER runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import stat
import sys
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, Protocol, SupportsIndex, TypeAlias, cast

_CONFIG_SCHEMA_VERSION = "paper-runtime-config-v2"
_HASH_VERSION = "paper-runtime-hash-v2"
_ENVIRONMENT_VERSION = "paper-runtime-environment-v2"
_ATTESTATION_VERSION = "paper-runtime-environment-attestation-v1"
_FORMAL_MODE: Literal["PAPER_REAL_TIME"] = "PAPER_REAL_TIME"
_WINDOWS_FORMAL_MODE: Literal["PAPER_REAL_TIME_WINDOWS"] = "PAPER_REAL_TIME_WINDOWS"
_FORMAL_MODES = frozenset({_FORMAL_MODE, _WINDOWS_FORMAL_MODE})
_DEVELOPMENT_MODE: Literal["development-example"] = "development-example"
_EXPECTED_WSL_BASE_PREFIX = PurePosixPath("/home/mabw/miniforge3")
_EXPECTED_WINDOWS_BASE_PREFIX = Path(r"D:\Miniforge3")
_SELECTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FORBIDDEN_FORMAL_SELECTOR_PARTS = ("development", "example", "fixture", "unknown")
_REPARSE_POINT = 0x400
_WINDOWS_DRIVE_FIXED = 3
_WINDOWS_FILE_PERSISTENT_ACLS = 0x00000008


class PaperRuntimeError(ValueError):
    """Stable, sanitized PAPER runtime environment failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"PaperRuntimeError({self.code!r})"


@dataclass(frozen=True, slots=True)
class FormalPaperRuntimeConfig:
    """Strict formal config bound to one file and its physical parent."""

    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    schema_version: str
    runtime_version: str
    mode: Literal["PAPER_REAL_TIME", "PAPER_REAL_TIME_WINDOWS"]
    runtime_root: Path
    broker_root: Path
    evidence_root: Path
    anchor_root: Path
    log_root: Path
    project_root: Path
    oms_sqlite_filename: str
    broker_sqlite_filename: str
    account_selector: str
    source_selector: str
    policy_selector: str
    expected_schedule_selector: str
    config_identity: str


@dataclass(frozen=True, slots=True)
class DevelopmentPaperRuntimeConfig:
    """Strict development config that cannot enter the formal verifier."""

    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    schema_version: str
    runtime_version: str
    mode: Literal["development-example"]
    runtime_root: Path
    broker_root: Path
    evidence_root: Path
    anchor_root: Path
    log_root: Path
    project_root: Path
    oms_sqlite_filename: str
    broker_sqlite_filename: str
    account_selector: str
    source_selector: str
    policy_selector: str
    expected_schedule_selector: str
    config_identity: str


PaperRuntimeConfig: TypeAlias = FormalPaperRuntimeConfig | DevelopmentPaperRuntimeConfig


@dataclass(frozen=True, slots=True)
class PaperRuntimeLayout:
    """Fresh identity of five sibling roots below one physical parent."""

    parent: Path
    runtime_root: Path
    broker_root: Path
    evidence_root: Path
    anchor_root: Path
    log_root: Path
    parent_identity: str
    root_identities: tuple[tuple[str, str], ...]
    layout_identity: str


@dataclass(frozen=True, slots=True)
class RuntimePlatformProof:
    """Actual interpreter, target parent, and mount projection."""

    os_name: str
    kernel_release: str
    wsl_generation: str
    python_executable: str
    python_executable_identity: str
    python_prefix: str
    python_prefix_identity: str
    conda_environment: str
    conda_prefix: str
    parent_identity: str
    mount_point: str
    mount_root: str
    filesystem_type: str
    device_identity: str
    mount_options: tuple[str, ...]
    probed_at: dt.datetime
    environment_identity: str
    proof_digest: str


@dataclass(frozen=True, slots=True)
class _EnvironmentAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("runtime environment proof is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedPaperRuntimeEnvironment:
    """Ephemeral formal proof of config, platform, and cold or broker-materialized layout."""

    schema_version: str
    config: FormalPaperRuntimeConfig
    layout: PaperRuntimeLayout
    platform: RuntimePlatformProof
    verified_at: dt.datetime
    verification_identity: str
    _attestation: _EnvironmentAttestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("runtime environment proof is process-local")


@dataclass(frozen=True, slots=True)
class DevelopmentPaperRuntimeEnvironment:
    """Development-only environment result with no formal capability."""

    schema_version: str
    config: DevelopmentPaperRuntimeConfig
    layout: PaperRuntimeLayout
    platform: RuntimePlatformProof
    verified_at: dt.datetime
    verification_identity: str


@dataclass(frozen=True, slots=True)
class _ParsedConfig:
    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    schema_version: str
    runtime_version: str
    mode: str
    runtime_root: Path
    broker_root: Path
    evidence_root: Path
    anchor_root: Path
    log_root: Path
    project_root: Path
    oms_sqlite_filename: str
    broker_sqlite_filename: str
    account_selector: str
    source_selector: str
    policy_selector: str
    expected_schedule_selector: str
    config_identity: str


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class _ModeFailure(Exception):
    pass


class _FormalEnvironmentVerifier(Protocol):
    def __call__(
        self, *, config: PaperRuntimeConfig, now: dt.datetime
    ) -> VerifiedPaperRuntimeEnvironment: ...


def _create_formal_environment_api() -> tuple[
    _FormalEnvironmentVerifier,
    Callable[[dict[str, object], _EnvironmentAttestation], bool],
]:
    key = secrets.token_bytes(32)

    def verify_paper_runtime_environment(
        *, config: PaperRuntimeConfig, now: dt.datetime
    ) -> VerifiedPaperRuntimeEnvironment:
        """Only mint path for a fresh actual formal runtime environment."""
        failure: str | None = None
        result: VerifiedPaperRuntimeEnvironment | None = None
        try:
            if type(config) is not FormalPaperRuntimeConfig:
                raise _Failure("PAPER_RUNTIME_MODE_INVALID")
            timestamp = _require_utc(now)
            fresh = load_paper_runtime_config(config.source_path)
            if type(fresh) is not FormalPaperRuntimeConfig or fresh != config:
                raise _Failure("PAPER_RUNTIME_CONFIG_INVALID")
            parent = _syntactic_common_parent(config)
            platform_proof = _run_configured_platform_probe(
                parent, timestamp, formal_mode=config.mode
            )
            _run_configured_formal_platform_verifier(
                platform_proof, parent, mode=config.mode
            )
            _after_platform_probe_hook(parent)
            layout = _run_layout_builder(config, allow_system_temp=False)
            _run_platform_layout_verifier(platform_proof, layout)
            _before_environment_return_hook(parent)
            return_fresh = load_paper_runtime_config(config.source_path)
            if type(return_fresh) is not FormalPaperRuntimeConfig or return_fresh != config:
                raise _Failure("PAPER_RUNTIME_CONFIG_INVALID")
            _fresh_verify_layout(config, layout, allow_system_temp=False)
            _run_platform_layout_verifier(platform_proof, layout)
            payload = _environment_payload(config, layout, platform_proof, timestamp)
            token = hmac.new(key, _attestation_message(payload), hashlib.sha256).digest()
            result = VerifiedPaperRuntimeEnvironment(
                schema_version=_ENVIRONMENT_VERSION,
                config=config,
                layout=layout,
                platform=platform_proof,
                verified_at=timestamp,
                verification_identity=_sha256(payload),
                _attestation=_EnvironmentAttestation(token),
            )
            _verify_environment_attestation(result)
        except PaperRuntimeError as exc:
            failure = exc.code
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_RUNTIME_VERIFY_FAILED"
        if failure is not None or result is None:
            raise PaperRuntimeError(failure or "PAPER_RUNTIME_VERIFY_FAILED") from None
        return result

    def verify(payload: dict[str, object], attestation: _EnvironmentAttestation) -> bool:
        if type(attestation) is not _EnvironmentAttestation:
            return False
        expected = hmac.new(key, _attestation_message(payload), hashlib.sha256).digest()
        return hmac.compare_digest(attestation.token, expected)

    return verify_paper_runtime_environment, verify


verify_paper_runtime_environment, _verify_environment_token = (
    _create_formal_environment_api()
)
del _create_formal_environment_api


def load_paper_runtime_config(path: Path) -> PaperRuntimeConfig:
    """Load a v2 config and bind the exact file and parent directory identities."""
    failure: str | None = None
    parsed: _ParsedConfig | None = None
    try:
        parsed = _load_config(path)
    except _ModeFailure:
        failure = "PAPER_RUNTIME_MODE_INVALID"
    except Exception:
        failure = "PAPER_RUNTIME_CONFIG_INVALID"
    if failure is not None or parsed is None:
        raise PaperRuntimeError(failure or "PAPER_RUNTIME_CONFIG_INVALID") from None
    if parsed.mode in _FORMAL_MODES:
        return _formal_config(parsed)
    return _development_config(parsed)


def verify_development_paper_runtime_preflight(
    *, config: PaperRuntimeConfig, now: dt.datetime
) -> DevelopmentPaperRuntimeEnvironment:
    """Build an exact development-only read-only environment result."""
    failure: str | None = None
    result: DevelopmentPaperRuntimeEnvironment | None = None
    try:
        if type(config) is not DevelopmentPaperRuntimeConfig:
            raise _Failure("PAPER_RUNTIME_MODE_INVALID")
        timestamp = _require_utc(now)
        fresh = load_paper_runtime_config(config.source_path)
        if type(fresh) is not DevelopmentPaperRuntimeConfig or fresh != config:
            raise _Failure("PAPER_RUNTIME_CONFIG_INVALID")
        parent = _syntactic_common_parent(config)
        platform_proof = _run_platform_probe(parent, timestamp)
        _after_platform_probe_hook(parent)
        layout = _run_layout_builder(config, allow_system_temp=True)
        _run_platform_layout_verifier(platform_proof, layout)
        payload: dict[str, object] = {
            "schema_version": _ENVIRONMENT_VERSION,
            "kind": _DEVELOPMENT_MODE,
            "config": _config_projection(config),
            "layout": _layout_projection(layout),
            "platform": _platform_projection(platform_proof),
            "verified_at": _canonical_datetime(timestamp),
        }
        result = DevelopmentPaperRuntimeEnvironment(
            schema_version=_ENVIRONMENT_VERSION,
            config=config,
            layout=layout,
            platform=platform_proof,
            verified_at=timestamp,
            verification_identity=_sha256(payload),
        )
        _before_environment_return_hook(parent)
        _fresh_verify_layout(config, result.layout, allow_system_temp=True)
        _run_platform_layout_verifier(result.platform, result.layout)
    except PaperRuntimeError as exc:
        failure = exc.code
    except _Failure as exc:
        failure = exc.code
    except Exception:
        failure = "PAPER_RUNTIME_VERIFY_FAILED"
    if failure is not None or result is None:
        raise PaperRuntimeError(failure or "PAPER_RUNTIME_VERIFY_FAILED") from None
    return result


def verify_existing_paper_runtime_preflight(
    environment: VerifiedPaperRuntimeEnvironment,
    *,
    config_path: Path,
    now: dt.datetime,
) -> None:
    """Recompute retained nested identities, then fresh-check the actual environment."""
    failure: str | None = None
    try:
        if type(environment) is not VerifiedPaperRuntimeEnvironment:
            raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
        if type(environment.config) is not FormalPaperRuntimeConfig:
            raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
        _verify_platform_proof_digest(environment.platform)
        _verify_retained_platform_files(environment.platform)
        _verify_retained_layout(environment.config, environment.layout)
        _verify_environment_attestation(environment)
        config = load_paper_runtime_config(config_path)
        if type(config) is not FormalPaperRuntimeConfig or config != environment.config:
            raise _Failure("PAPER_RUNTIME_CONFIG_INVALID")
        current = verify_paper_runtime_environment(config=config, now=now)
        if (
            _config_projection(current.config) != _config_projection(environment.config)
            or _layout_projection(current.layout) != _layout_projection(environment.layout)
            or _stable_platform_projection(current.platform)
            != _stable_platform_projection(environment.platform)
        ):
            raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    except PaperRuntimeError as exc:
        failure = exc.code
    except _Failure as exc:
        failure = exc.code
    except Exception:
        failure = "PAPER_RUNTIME_PREFLIGHT_INVALID"
    if failure is not None:
        raise PaperRuntimeError(failure) from None


def _formal_config(parsed: _ParsedConfig) -> FormalPaperRuntimeConfig:
    return FormalPaperRuntimeConfig(
        source_path=parsed.source_path,
        source_file_identity=parsed.source_file_identity,
        source_parent_identity=parsed.source_parent_identity,
        raw_sha256=parsed.raw_sha256,
        schema_version=parsed.schema_version,
        runtime_version=parsed.runtime_version,
        mode=cast(
            Literal["PAPER_REAL_TIME", "PAPER_REAL_TIME_WINDOWS"], parsed.mode
        ),
        runtime_root=parsed.runtime_root,
        broker_root=parsed.broker_root,
        evidence_root=parsed.evidence_root,
        anchor_root=parsed.anchor_root,
        log_root=parsed.log_root,
        project_root=parsed.project_root,
        oms_sqlite_filename=parsed.oms_sqlite_filename,
        broker_sqlite_filename=parsed.broker_sqlite_filename,
        account_selector=parsed.account_selector,
        source_selector=parsed.source_selector,
        policy_selector=parsed.policy_selector,
        expected_schedule_selector=parsed.expected_schedule_selector,
        config_identity=parsed.config_identity,
    )


def _development_config(parsed: _ParsedConfig) -> DevelopmentPaperRuntimeConfig:
    return DevelopmentPaperRuntimeConfig(
        source_path=parsed.source_path,
        source_file_identity=parsed.source_file_identity,
        source_parent_identity=parsed.source_parent_identity,
        raw_sha256=parsed.raw_sha256,
        schema_version=parsed.schema_version,
        runtime_version=parsed.runtime_version,
        mode=_DEVELOPMENT_MODE,
        runtime_root=parsed.runtime_root,
        broker_root=parsed.broker_root,
        evidence_root=parsed.evidence_root,
        anchor_root=parsed.anchor_root,
        log_root=parsed.log_root,
        project_root=parsed.project_root,
        oms_sqlite_filename=parsed.oms_sqlite_filename,
        broker_sqlite_filename=parsed.broker_sqlite_filename,
        account_selector=parsed.account_selector,
        source_selector=parsed.source_selector,
        policy_selector=parsed.policy_selector,
        expected_schedule_selector=parsed.expected_schedule_selector,
        config_identity=parsed.config_identity,
    )


def _load_config(path: Path) -> _ParsedConfig:
    source_path, raw, file_identity, parent_identity = _read_regular_bytes(path)
    document = cast(dict[str, object], tomllib.loads(raw.decode("utf-8")))
    _require_exact_keys(document, {"meta", "paths", "store", "selectors"})
    meta = _require_table(document["meta"])
    paths = _require_table(document["paths"])
    store = _require_table(document["store"])
    selectors = _require_table(document["selectors"])
    _require_exact_keys(meta, {"schema_version", "runtime_version", "mode"})
    _require_exact_keys(
        paths,
        {
            "runtime_root",
            "broker_root",
            "evidence_root",
            "anchor_root",
            "log_root",
            "project_root",
        },
    )
    _require_exact_keys(store, {"oms_sqlite_filename", "broker_sqlite_filename"})
    _require_exact_keys(
        selectors,
        {
            "account_selector",
            "source_selector",
            "policy_selector",
            "expected_schedule_selector",
        },
    )
    schema_version = _require_string(meta["schema_version"])
    if schema_version != _CONFIG_SCHEMA_VERSION:
        raise ValueError
    mode = _require_string(meta["mode"])
    if mode not in {*_FORMAL_MODES, _DEVELOPMENT_MODE}:
        raise _ModeFailure
    formal = mode in _FORMAL_MODES
    runtime_version = _require_selector(meta["runtime_version"], formal=False)
    root_values = {
        name: _require_absolute_path(paths[name])
        for name in (
            "runtime_root",
            "broker_root",
            "evidence_root",
            "anchor_root",
            "log_root",
            "project_root",
        )
    }
    if _path_key(root_values["project_root"]) != _path_key(_actual_project_root()):
        raise ValueError
    selector_values = {
        name: _require_selector(selectors[name], formal=formal)
        for name in (
            "account_selector",
            "source_selector",
            "policy_selector",
            "expected_schedule_selector",
        )
    }
    oms_name = _require_relative_sqlite_filename(store["oms_sqlite_filename"])
    broker_name = _require_relative_sqlite_filename(store["broker_sqlite_filename"])
    raw_sha = hashlib.sha256(raw).hexdigest()
    canonical = {
        "schema_version": schema_version,
        "runtime_version": runtime_version,
        "mode": mode,
        "source_path": _path_key(source_path),
        "source_file_identity": file_identity,
        "source_parent_identity": parent_identity,
        "paths": {name: _path_key(value) for name, value in root_values.items()},
        "oms_sqlite_filename": oms_name,
        "broker_sqlite_filename": broker_name,
        "selectors": selector_values,
        "raw_sha256": raw_sha,
    }
    return _ParsedConfig(
        source_path=source_path,
        source_file_identity=file_identity,
        source_parent_identity=parent_identity,
        raw_sha256=raw_sha,
        schema_version=schema_version,
        runtime_version=runtime_version,
        mode=mode,
        runtime_root=root_values["runtime_root"],
        broker_root=root_values["broker_root"],
        evidence_root=root_values["evidence_root"],
        anchor_root=root_values["anchor_root"],
        log_root=root_values["log_root"],
        project_root=root_values["project_root"],
        oms_sqlite_filename=oms_name,
        broker_sqlite_filename=broker_name,
        account_selector=selector_values["account_selector"],
        source_selector=selector_values["source_selector"],
        policy_selector=selector_values["policy_selector"],
        expected_schedule_selector=selector_values["expected_schedule_selector"],
        config_identity=_sha256(canonical),
    )


def _read_regular_bytes(path: Path) -> tuple[Path, bytes, str, str]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError
    absolute = path.absolute()
    parent = absolute.parent
    _reject_link_chain(parent)
    parent_before = os.lstat(parent)
    parent_identity = _directory_identity(parent, parent_before)
    path_before = os.lstat(absolute)
    _require_regular_file_status(path_before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    try:
        opened_before = os.fstat(descriptor)
        _require_regular_file_status(opened_before)
        if _stat_object_identity(path_before) != _stat_object_identity(opened_before):
            raise ValueError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        opened_after = os.fstat(descriptor)
        if _file_state_identity(opened_before) != _file_state_identity(opened_after):
            raise ValueError
        if len(raw) != opened_after.st_size:
            raise ValueError
        file_identity = _regular_file_identity(absolute, opened_after)
        _after_config_read_hook(absolute)
        path_after = os.lstat(absolute)
        parent_after = os.lstat(parent)
        if _stat_object_identity(path_after) != _stat_object_identity(opened_after):
            raise ValueError
        if _directory_identity(parent, parent_after) != parent_identity:
            raise ValueError
        if _regular_file_identity(absolute, path_after) != file_identity:
            raise ValueError
        return absolute.resolve(strict=True), raw, file_identity, parent_identity
    finally:
        os.close(descriptor)


def _after_config_read_hook(path: Path) -> None:
    del path


def _after_platform_probe_hook(parent: Path) -> None:
    del parent


def _before_environment_return_hook(parent: Path) -> None:
    del parent


def _require_regular_file_status(status: os.stat_result) -> None:
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or _is_reparse(status)
        or status.st_nlink != 1
    ):
        raise ValueError


def _require_exact_keys(value: dict[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError


def _require_table(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError
    return cast(dict[str, object], value)


def _require_string(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError
    return value


def _require_selector(value: object, *, formal: bool) -> str:
    selector = _require_string(value)
    if _SELECTOR.fullmatch(selector) is None:
        raise ValueError
    if formal and any(part in selector.lower() for part in _FORBIDDEN_FORMAL_SELECTOR_PARTS):
        raise ValueError
    return selector


def _require_absolute_path(value: object) -> Path:
    text = _require_string(value)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts or text.startswith("\\\\"):
        raise ValueError
    return Path(os.path.abspath(os.fspath(path)))


def _require_relative_sqlite_filename(value: object) -> str:
    text = _require_string(value)
    candidate = PurePosixPath(text)
    if (
        candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name in {"", ".", ".."}
        or candidate.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}
        or any(character in text for character in ("\\", ":", "%"))
    ):
        raise ValueError
    return candidate.name


def _actual_project_root() -> Path:
    return Path(__file__).resolve(strict=True).parents[3]


def _syntactic_common_parent(config: PaperRuntimeConfig) -> Path:
    parents = {_path_key(item.parent): item.parent for item in _layout_roots(config).values()}
    if len(parents) != 1:
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    return next(iter(parents.values()))


def _build_layout(config: PaperRuntimeConfig, *, allow_system_temp: bool) -> PaperRuntimeLayout:
    roots = _layout_roots(config)
    parent = _syntactic_common_parent(config)
    _require_real_directory(parent)
    parent_status = os.lstat(parent)
    parent_identity = _directory_identity(parent, parent_status)
    if len({_path_key(item) for item in roots.values()}) != len(roots):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    is_formal = type(config) is FormalPaperRuntimeConfig
    root_identities = _compute_root_identities(roots, parent_identity, formal=is_formal)
    actual_project = _actual_project_root()
    for candidate in (parent, *roots.values()):
        if _is_within(candidate, actual_project):
            raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    if not allow_system_temp and _is_within(parent, _system_temp_root()):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    layout = PaperRuntimeLayout(
        parent=parent,
        runtime_root=roots["runtime"],
        broker_root=roots["broker"],
        evidence_root=roots["evidence"],
        anchor_root=roots["anchor"],
        log_root=roots["log"],
        parent_identity=parent_identity,
        root_identities=root_identities,
        layout_identity=_layout_identity(parent, parent_identity, root_identities),
    )
    _verify_retained_layout(config, layout)
    return layout


def _run_layout_builder(config: PaperRuntimeConfig, *, allow_system_temp: bool) -> PaperRuntimeLayout:
    try:
        return _build_layout(config, allow_system_temp=allow_system_temp)
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID") from None


def _fresh_verify_layout(
    config: PaperRuntimeConfig,
    layout: PaperRuntimeLayout,
    *,
    allow_system_temp: bool,
) -> None:
    fresh = _run_layout_builder(config, allow_system_temp=allow_system_temp)
    if _layout_projection(fresh) != _layout_projection(layout):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")


def _verify_retained_layout(config: PaperRuntimeConfig, layout: PaperRuntimeLayout) -> None:
    if type(layout) is not PaperRuntimeLayout:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    expected_roots = _layout_roots(config)
    if (
        layout.parent != _syntactic_common_parent(config)
        or layout.runtime_root != expected_roots["runtime"]
        or layout.broker_root != expected_roots["broker"]
        or layout.evidence_root != expected_roots["evidence"]
        or layout.anchor_root != expected_roots["anchor"]
        or layout.log_root != expected_roots["log"]
    ):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    roots = _layout_roots(config)
    is_formal = type(config) is FormalPaperRuntimeConfig
    expected_root_ids = _compute_root_identities(
        roots, layout.parent_identity, formal=is_formal
    )
    expected_layout_id = _layout_identity(layout.parent, layout.parent_identity, expected_root_ids)
    if layout.root_identities != expected_root_ids or layout.layout_identity != expected_layout_id:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    current_parent_identity = _directory_identity(layout.parent, os.lstat(layout.parent))
    if current_parent_identity != layout.parent_identity:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")


def _layout_roots(config: PaperRuntimeConfig) -> dict[str, Path]:
    return {
        "runtime": config.runtime_root,
        "broker": config.broker_root,
        "evidence": config.evidence_root,
        "anchor": config.anchor_root,
        "log": config.log_root,
    }


def _absent_root_identity(role: str, parent_identity: str, root: Path) -> str:
    return _sha256(
        {
            "type": "absent-paper-runtime-root-v2",
            "role": role,
            "parent_identity": parent_identity,
            "leaf_name": root.name,
            "resolved_path": _path_key(root),
        }
    )


def _materialized_root_identity(
    role: str, parent_identity: str, root: Path, status: os.stat_result
) -> str:
    return _sha256(
        {
            "type": "materialized-paper-runtime-root-v1",
            "role": role,
            "parent_identity": parent_identity,
            "leaf_name": root.name,
            "resolved_path": _path_key(root),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _probe_root_identity(
    role: str, root: Path, parent_identity: str, *, formal: bool
) -> str:
    try:
        status = os.lstat(root)
    except FileNotFoundError:
        return _absent_root_identity(role, parent_identity, root)
    if not formal:
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    if role not in {"broker", "runtime"}:
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    if not stat.S_ISDIR(status.st_mode):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    _reject_link_chain(root)
    return _materialized_root_identity(role, parent_identity, root, status)


def _compute_root_identities(
    roots: dict[str, Path], parent_identity: str, *, formal: bool
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, _probe_root_identity(name, root, parent_identity, formal=formal))
        for name, root in roots.items()
    )


def _layout_identity(
    parent: Path,
    parent_identity: str,
    root_identities: tuple[tuple[str, str], ...],
) -> str:
    return _sha256(
        {
            "type": "paper-runtime-layout-v2",
            "parent": _path_key(parent),
            "parent_identity": parent_identity,
            "roots": root_identities,
        }
    )


def _require_real_directory(path: Path) -> None:
    _reject_link_chain(path)
    status = os.lstat(path)
    if not stat.S_ISDIR(status.st_mode) or _is_reparse(status):
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")


def _system_temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _reject_link_chain(path: Path) -> None:
    current = path.absolute()
    for candidate in (current, *current.parents):
        status = os.lstat(candidate)
        if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
            raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")


def _probe_actual_runtime_platform(parent: Path, now: dt.datetime) -> RuntimePlatformProof:
    parent_status = os.lstat(parent)
    if not stat.S_ISDIR(parent_status.st_mode) or _is_reparse(parent_status):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    parent_identity = _directory_identity(parent, parent_status)
    os_name = platform.system()
    kernel_release = platform.release()
    release_lower = f"{kernel_release} {platform.version()}".lower()
    if os_name == "Linux" and "microsoft" in release_lower:
        wsl_generation = "2" if "wsl2" in release_lower else "1"
    else:
        wsl_generation = "none"
    executable_path = Path(sys.executable).resolve(strict=True)
    prefix_path = Path(sys.prefix).resolve(strict=True)
    executable = str(executable_path)
    prefix = str(prefix_path)
    conda_environment = os.environ.get("CONDA_DEFAULT_ENV", "")
    conda_prefix = (
        str(Path(os.environ["CONDA_PREFIX"]).resolve(strict=True))
        if os.environ.get("CONDA_PREFIX")
        else ""
    )
    mount_point = Path(parent.anchor) if os_name != "Linux" else Path("/")
    mount_root = "/"
    filesystem_type = "windows" if os_name == "Windows" else "unknown"
    mount_options: tuple[str, ...] = ()
    if os_name == "Linux":
        mount_point_text, mount_root, filesystem_type, mount_options = _linux_mount_for(parent)
        mount_point = Path(mount_point_text)
    stable: dict[str, object] = {
        "type": "paper-runtime-platform-environment-v2",
        "os_name": os_name,
        "kernel_release": kernel_release,
        "wsl_generation": wsl_generation,
        "python_executable": executable,
        "python_executable_identity": _regular_file_identity(
            executable_path, os.stat(executable_path)
        ),
        "python_prefix": prefix,
        "python_prefix_identity": _directory_identity(prefix_path, os.stat(prefix_path)),
        "conda_environment": conda_environment,
        "conda_prefix": conda_prefix,
        "parent_identity": parent_identity,
        "mount_point": _path_key(mount_point),
        "mount_root": mount_root,
        "filesystem_type": filesystem_type,
        "device_identity": str(parent_status.st_dev),
        "mount_options": mount_options,
    }
    environment_identity = _sha256(stable)
    proof_payload = {**stable, "probed_at": _canonical_datetime(now)}
    return RuntimePlatformProof(
        os_name=os_name,
        kernel_release=kernel_release,
        wsl_generation=wsl_generation,
        python_executable=executable,
        python_executable_identity=cast(str, stable["python_executable_identity"]),
        python_prefix=prefix,
        python_prefix_identity=cast(str, stable["python_prefix_identity"]),
        conda_environment=conda_environment,
        conda_prefix=conda_prefix,
        parent_identity=parent_identity,
        mount_point=_path_key(mount_point),
        mount_root=mount_root,
        filesystem_type=filesystem_type,
        device_identity=str(parent_status.st_dev),
        mount_options=mount_options,
        probed_at=now,
        environment_identity=environment_identity,
        proof_digest=_sha256(proof_payload),
    )


def _run_platform_probe(parent: Path, now: dt.datetime) -> RuntimePlatformProof:
    try:
        return _probe_actual_runtime_platform(parent, now)
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED") from None


def _run_configured_platform_probe(
    parent: Path,
    now: dt.datetime,
    *,
    formal_mode: Literal["PAPER_REAL_TIME", "PAPER_REAL_TIME_WINDOWS"],
) -> RuntimePlatformProof:
    proof = _run_platform_probe(parent, now)
    if formal_mode == _WINDOWS_FORMAL_MODE:
        try:
            return _bind_windows_volume_proof(proof, parent)
        except _Failure:
            raise
        except Exception:
            raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED") from None
    if formal_mode != _FORMAL_MODE:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    return proof


def _bind_windows_volume_proof(
    proof: RuntimePlatformProof, parent: Path
) -> RuntimePlatformProof:
    if proof.os_name != "Windows" or proof.wsl_generation != "none":
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    mount_point, filesystem_type, device_identity, mount_options = (
        _windows_volume_for(parent)
    )
    candidate = replace(
        proof,
        mount_point=mount_point,
        mount_root="/",
        filesystem_type=filesystem_type,
        device_identity=device_identity,
        mount_options=mount_options,
        environment_identity="",
        proof_digest="",
    )
    stable = _stable_platform_projection(candidate)
    return replace(
        candidate,
        environment_identity=_sha256(stable),
        proof_digest=_sha256(
            {
                **stable,
                "probed_at": _canonical_datetime(candidate.probed_at),
            }
        ),
    )


def _windows_volume_for(parent: Path) -> tuple[str, str, str, tuple[str, ...]]:
    """Return an actual fixed-NTFS volume projection without exposing its serial."""
    if platform.system() != "Windows":
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    get_volume_path = kernel32.GetVolumePathNameW
    get_volume_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_volume_path.restype = wintypes.BOOL
    get_volume_information = kernel32.GetVolumeInformationW
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT

    volume_path = ctypes.create_unicode_buffer(32768)
    if not get_volume_path(
        str(parent.resolve(strict=True)), volume_path, len(volume_path)
    ):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    volume_root = volume_path.value
    volume_name = ctypes.create_unicode_buffer(261)
    filesystem_name = ctypes.create_unicode_buffer(261)
    volume_serial = wintypes.DWORD()
    maximum_component = wintypes.DWORD()
    filesystem_flags = wintypes.DWORD()
    if not get_volume_information(
        volume_root,
        volume_name,
        len(volume_name),
        ctypes.byref(volume_serial),
        ctypes.byref(maximum_component),
        ctypes.byref(filesystem_flags),
        filesystem_name,
        len(filesystem_name),
    ):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    del maximum_component, volume_name
    filesystem_type = filesystem_name.value.lower()
    if (
        filesystem_type != "ntfs"
        or get_drive_type(volume_root) != _WINDOWS_DRIVE_FIXED
        or not (filesystem_flags.value & _WINDOWS_FILE_PERSISTENT_ACLS)
    ):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    parent_status = os.lstat(parent)
    normalized_root = _path_key(Path(volume_root))
    device_identity = _sha256(
        {
            "type": "paper-runtime-windows-volume-v1",
            "volume_root": normalized_root,
            "volume_serial": volume_serial.value,
            "parent_device": parent_status.st_dev,
        }
    )
    return (
        normalized_root,
        filesystem_type,
        device_identity,
        ("fixed-drive", "persistent-acls"),
    )


def _verify_formal_platform(proof: RuntimePlatformProof, parent: Path) -> None:
    _verify_platform_proof_digest(proof)
    expected_prefix = str(_EXPECTED_WSL_BASE_PREFIX)
    expected_executable = str(Path(expected_prefix, "bin", "python").resolve(strict=True))
    if (
        proof.os_name != "Linux"
        or proof.wsl_generation != "2"
        or proof.filesystem_type != "ext4"
        or proof.mount_root != "/"
        or proof.python_prefix != expected_prefix
        or proof.conda_prefix != expected_prefix
        or proof.python_executable != expected_executable
        or proof.conda_environment != "base"
        or proof.python_prefix_identity
        != _directory_identity(Path(expected_prefix), os.stat(expected_prefix))
        or proof.python_executable_identity
        != _regular_file_identity(Path(expected_executable), os.stat(expected_executable))
        or proof.parent_identity != _directory_identity(parent, os.lstat(parent))
        or proof.device_identity != str(os.lstat(parent).st_dev)
    ):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")


def _verify_windows_formal_platform(
    proof: RuntimePlatformProof, parent: Path
) -> None:
    _verify_platform_proof_digest(proof)
    expected_prefix_path = _EXPECTED_WINDOWS_BASE_PREFIX.resolve(strict=True)
    expected_executable_path = (expected_prefix_path / "python.exe").resolve(strict=True)
    mount_point, filesystem_type, device_identity, mount_options = (
        _windows_volume_for(parent)
    )
    if (
        proof.os_name != "Windows"
        or proof.wsl_generation != "none"
        or proof.filesystem_type != filesystem_type
        or proof.filesystem_type != "ntfs"
        or proof.mount_point != mount_point
        or proof.mount_root != "/"
        or proof.mount_options != mount_options
        or proof.python_prefix != str(expected_prefix_path)
        or proof.conda_prefix != str(expected_prefix_path)
        or proof.python_executable != str(expected_executable_path)
        or proof.conda_environment != "base"
        or proof.python_prefix_identity
        != _directory_identity(expected_prefix_path, os.stat(expected_prefix_path))
        or proof.python_executable_identity
        != _regular_file_identity(
            expected_executable_path, os.stat(expected_executable_path)
        )
        or proof.parent_identity != _directory_identity(parent, os.lstat(parent))
        or proof.device_identity != device_identity
    ):
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")


def _run_formal_platform_verifier(proof: RuntimePlatformProof, parent: Path) -> None:
    try:
        _verify_formal_platform(proof, parent)
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED") from None


def _run_windows_formal_platform_verifier(
    proof: RuntimePlatformProof, parent: Path
) -> None:
    try:
        _verify_windows_formal_platform(proof, parent)
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED") from None


def _run_configured_formal_platform_verifier(
    proof: RuntimePlatformProof,
    parent: Path,
    *,
    mode: Literal["PAPER_REAL_TIME", "PAPER_REAL_TIME_WINDOWS"],
) -> None:
    if mode == _FORMAL_MODE:
        _run_formal_platform_verifier(proof, parent)
    elif mode == _WINDOWS_FORMAL_MODE:
        _run_windows_formal_platform_verifier(proof, parent)
    else:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")


def _verify_platform_proof_digest(proof: RuntimePlatformProof) -> None:
    if type(proof) is not RuntimePlatformProof:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    stable = _stable_platform_projection(proof)
    if proof.environment_identity != _sha256(stable):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    timestamp = _require_utc(proof.probed_at)
    if proof.proof_digest != _sha256({**stable, "probed_at": _canonical_datetime(timestamp)}):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")


def _verify_retained_platform_files(proof: RuntimePlatformProof) -> None:
    try:
        prefix = Path(proof.python_prefix)
        executable = Path(proof.python_executable)
        if (
            proof.python_prefix_identity
            != _directory_identity(prefix, os.stat(prefix))
            or proof.python_executable_identity
            != _regular_file_identity(executable, os.stat(executable))
        ):
            raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID") from None


def _run_platform_layout_verifier(
    proof: RuntimePlatformProof, layout: PaperRuntimeLayout
) -> None:
    try:
        _verify_platform_proof_digest(proof)
        current_parent = _directory_identity(layout.parent, os.lstat(layout.parent))
        if proof.os_name == "Windows" and proof.filesystem_type == "ntfs":
            mount_point, filesystem_type, device_identity, mount_options = (
                _windows_volume_for(layout.parent)
            )
            storage_matches = (
                proof.mount_point == mount_point
                and proof.filesystem_type == filesystem_type
                and proof.device_identity == device_identity
                and proof.mount_options == mount_options
            )
        else:
            storage_matches = proof.device_identity == str(os.lstat(layout.parent).st_dev)
        if (
            proof.parent_identity != layout.parent_identity
            or proof.parent_identity != current_parent
            or not storage_matches
            or not _is_within(layout.parent, Path(proof.mount_point))
        ):
            raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID")
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_RUNTIME_LAYOUT_INVALID") from None


def _linux_mount_for(parent: Path) -> tuple[str, str, str, tuple[str, ...]]:
    raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    target = str(parent.resolve(strict=True))
    matches: list[tuple[str, str, str, tuple[str, ...]]] = []
    for line in raw.splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        after = right.split()
        if len(fields) < 6 or len(after) < 3:
            continue
        mount_root = _decode_mount_path(fields[3])
        mount_point = _decode_mount_path(fields[4])
        if not _posix_is_within(target, mount_point):
            continue
        options = tuple(sorted(set(fields[5].split(",") + after[2].split(","))))
        matches.append((mount_point, mount_root, after[0], options))
    if not matches:
        raise _Failure("PAPER_RUNTIME_PLATFORM_UNSUPPORTED")
    return max(matches, key=lambda item: len(item[0]))


def _decode_mount_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _posix_is_within(candidate: str, boundary: str) -> bool:
    return boundary == "/" or candidate == boundary or candidate.startswith(boundary.rstrip("/") + "/")


def _verify_environment_attestation(environment: VerifiedPaperRuntimeEnvironment) -> None:
    if type(environment) is not VerifiedPaperRuntimeEnvironment:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    if type(environment.config) is not FormalPaperRuntimeConfig:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    payload = _environment_payload(
        environment.config,
        environment.layout,
        environment.platform,
        _require_utc(environment.verified_at),
    )
    if environment.schema_version != _ENVIRONMENT_VERSION:
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    if environment.verification_identity != _sha256(payload):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    if not _verify_environment_token(payload, environment._attestation):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")


def _environment_payload(
    config: FormalPaperRuntimeConfig,
    layout: PaperRuntimeLayout,
    platform_proof: RuntimePlatformProof,
    now: dt.datetime,
) -> dict[str, object]:
    return {
        "schema_version": _ENVIRONMENT_VERSION,
        "config": _config_projection(config),
        "layout": _layout_projection(layout),
        "platform": _platform_projection(platform_proof),
        "verified_at": _canonical_datetime(now),
    }


def _config_projection(config: PaperRuntimeConfig) -> dict[str, object]:
    return {
        "type": type(config).__name__,
        "source_path": _path_key(config.source_path),
        "source_file_identity": config.source_file_identity,
        "source_parent_identity": config.source_parent_identity,
        "raw_sha256": config.raw_sha256,
        "schema_version": config.schema_version,
        "runtime_version": config.runtime_version,
        "mode": config.mode,
        "runtime_root": _path_key(config.runtime_root),
        "broker_root": _path_key(config.broker_root),
        "evidence_root": _path_key(config.evidence_root),
        "anchor_root": _path_key(config.anchor_root),
        "log_root": _path_key(config.log_root),
        "project_root": _path_key(config.project_root),
        "oms_sqlite_filename": config.oms_sqlite_filename,
        "broker_sqlite_filename": config.broker_sqlite_filename,
        "account_selector": config.account_selector,
        "source_selector": config.source_selector,
        "policy_selector": config.policy_selector,
        "expected_schedule_selector": config.expected_schedule_selector,
        "config_identity": config.config_identity,
    }


def _layout_projection(layout: PaperRuntimeLayout) -> dict[str, object]:
    return {
        "parent": _path_key(layout.parent),
        "runtime_root": _path_key(layout.runtime_root),
        "broker_root": _path_key(layout.broker_root),
        "evidence_root": _path_key(layout.evidence_root),
        "anchor_root": _path_key(layout.anchor_root),
        "log_root": _path_key(layout.log_root),
        "parent_identity": layout.parent_identity,
        "root_identities": layout.root_identities,
        "layout_identity": layout.layout_identity,
    }


def _stable_platform_projection(proof: RuntimePlatformProof) -> dict[str, object]:
    return {
        "type": "paper-runtime-platform-environment-v2",
        "os_name": proof.os_name,
        "kernel_release": proof.kernel_release,
        "wsl_generation": proof.wsl_generation,
        "python_executable": proof.python_executable,
        "python_executable_identity": proof.python_executable_identity,
        "python_prefix": proof.python_prefix,
        "python_prefix_identity": proof.python_prefix_identity,
        "conda_environment": proof.conda_environment,
        "conda_prefix": proof.conda_prefix,
        "parent_identity": proof.parent_identity,
        "mount_point": proof.mount_point,
        "mount_root": proof.mount_root,
        "filesystem_type": proof.filesystem_type,
        "device_identity": proof.device_identity,
        "mount_options": proof.mount_options,
    }


def _platform_projection(proof: RuntimePlatformProof) -> dict[str, object]:
    return {
        **_stable_platform_projection(proof),
        "probed_at": _canonical_datetime(proof.probed_at),
        "environment_identity": proof.environment_identity,
        "proof_digest": proof.proof_digest,
    }


def _attestation_message(payload: dict[str, object]) -> bytes:
    return _canonical_json({"version": _ATTESTATION_VERSION, "payload": payload})


def _stat_object_identity(status: os.stat_result) -> tuple[int, int, int]:
    return (status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode))


def _file_state_identity(status: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        stat.S_IFMT(status.st_mode),
    )


def _regular_file_identity(path: Path, status: os.stat_result) -> str:
    return _sha256(
        {
            "type": "paper-runtime-file-v2",
            "path": _path_key(path),
            "device": status.st_dev,
            "inode": status.st_ino,
            "size": status.st_size,
            "mtime_ns": status.st_mtime_ns,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _directory_identity(path: Path, status: os.stat_result) -> str:
    return _sha256(
        {
            "type": "paper-runtime-directory-v2",
            "path": _path_key(path),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _is_reparse(status: os.stat_result) -> bool:
    return bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)


def _is_within(candidate: Path, boundary: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(candidate), _path_key(boundary))) == _path_key(
            boundary
        )
    except ValueError:
        return False


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _require_utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise _Failure("PAPER_RUNTIME_PREFLIGHT_INVALID")
    return value.astimezone(dt.timezone.utc)


def _canonical_datetime(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json({"version": _HASH_VERSION, "value": value})).hexdigest()
