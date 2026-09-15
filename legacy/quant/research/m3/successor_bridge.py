"""Production successor bridge: one request file → one runtime entry.

This module is the sole production bridge into
``run_production_two_fold_successor``.  It never enumerates, selects, wraps, or
copies stage/fold/Gate sequences.  It only validates an explicit request,
fresh-rebuilds config/release/toolchain, calls the zero-arg canonical
dependency factory, and invokes the package-owned production entrypoint.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal, NoReturn, cast

from quant.data.m3_release import G1Release, VerifiedG1Release, verify_g1_release
from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.fetch_qlib_tool import DEFAULT_TARGET_PATH, build_qlib_dump_tool_spec
from quant.research.m3 import successor_runtime as runtime

REQUEST_SCHEMA_ID: Literal["m3-successor-bridge-request-v1"] = (
    "m3-successor-bridge-request-v1"
)
RESULT_SCHEMA_ID: Literal["m3-successor-bridge-result-v1"] = (
    "m3-successor-bridge-result-v1"
)

BRIDGE_INPUT_ERROR = "SUCCESSOR_BRIDGE_INPUT_INVALID"
BRIDGE_RUNTIME_ERROR = "SUCCESSOR_BRIDGE_RUNTIME_FAILED"

_PATH_TYPE = type(Path())
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_FOLD_RE = re.compile(r"^fold_[0-9]{3}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_REQUEST_KEYS = frozenset(
    {
        "schema_id",
        "project_root",
        "controlled_output_root",
        "folds",
        "runtime_identity",
        "now",
        "toolchain",
        "resume",
    }
)
_FOLD_KEYS = frozenset(
    {
        "fold",
        "config_path",
        "config_raw_sha256",
        "config_full_sha256",
        "g1_release_path",
        "g1_release_id",
        "g1_release_manifest_sha256",
    }
)
_RUNTIME_IDENTITY_KEYS = frozenset(
    {
        "code_version",
        "dependency_fingerprint_sha256",
        "provider_runtime_fingerprint_sha256",
    }
)
_TOOLCHAIN_KEYS = frozenset(
    {
        "python_executable",
        "qlib_dump_tool_path",
        "qlib_dump_tool_size_bytes",
        "qlib_dump_tool_sha256",
        "timeout_seconds",
    }
)

_RUNTIME_INPUT_CODES = frozenset(
    {
        "SUCCESSOR_INPUT_INVALID",
        "SUCCESSOR_CONFIG_INVALID",
        "SUCCESSOR_RELEASE_INVALID",
    }
)


def _build_entrypoint_authority(
    true_factory: object,
    true_entry: object,
) -> Callable[[], None]:
    """Bind import-time package-owned callables in a closure (not rewritable aliases)."""

    true_factory_code = getattr(true_factory, "__code__", None)
    true_entry_code = getattr(true_entry, "__code__", None)

    def _require_canonical_entrypoints() -> None:
        factory = runtime.make_canonical_successor_production_dependencies
        entry = runtime.run_production_two_fold_successor
        if factory is not true_factory or entry is not true_entry:
            _fail_input()
        if (
            getattr(factory, "__code__", None) is not true_factory_code
            or getattr(entry, "__code__", None) is not true_entry_code
        ):
            _fail_input()
        if (
            getattr(factory, "__wrapped__", None) is not None
            or getattr(entry, "__wrapped__", None) is not None
        ):
            _fail_input()

    return _require_canonical_entrypoints


# Closure-captured package-owned true bodies; bilateral alias swaps cannot satisfy this.
_require_canonical_entrypoints = _build_entrypoint_authority(
    runtime.make_canonical_successor_production_dependencies,
    runtime.run_production_two_fold_successor,
)


class SuccessorBridgeError(ValueError):
    """Stable, redacted bridge boundary failure."""

    _CODES = frozenset({BRIDGE_INPUT_ERROR, BRIDGE_RUNTIME_ERROR})

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown successor bridge error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"SuccessorBridgeError({self.code!r})"


@dataclass(frozen=True)
class SuccessorBridgeResultProjection:
    """Narrow, path-free success projection for CLI stdout."""

    schema_version: Literal["m3-successor-bridge-result-v1"]
    terminal_status: Literal["PASS"]
    two_fold_identity: str
    attested_at: str
    reused: bool
    controlled_output_root: str
    fold_ids: tuple[str, ...]
    gate_names: tuple[str, ...]
    receipt_node_ids: tuple[str, ...]
    receipt_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.schema_version != RESULT_SCHEMA_ID
            or self.terminal_status != "PASS"
            or not _is_hex64(self.two_fold_identity)
            or type(self.attested_at) is not str
            or not self.attested_at.endswith("Z")
            or type(self.reused) is not bool
            or type(self.controlled_output_root) is not str
            or type(self.fold_ids) is not tuple
            or type(self.gate_names) is not tuple
            or type(self.receipt_node_ids) is not tuple
            or type(self.receipt_sha256s) is not tuple
            or len(self.receipt_node_ids) != len(self.receipt_sha256s)
        ):
            raise ValueError("invalid successor bridge result projection")


def run_production_successor_bridge(*, request_path: Path) -> runtime.SuccessorRunResult:
    """Validate one request file and enter the package-owned production runtime."""

    _require_exact_absolute_path(request_path)
    payload = _load_canonical_request_object(request_path)
    request, resume = _build_runtime_request(payload)
    _require_canonical_entrypoints()
    dependencies = runtime.make_canonical_successor_production_dependencies()
    _require_canonical_dependencies(dependencies)
    try:
        return runtime.run_production_two_fold_successor(
            request=request,
            dependencies=dependencies,
            public_apis=None,
            resume=resume,
        )
    except SuccessorBridgeError:
        raise
    except runtime.SuccessorRuntimeError as error:
        _map_runtime_error(error)
    except Exception:
        _fail_runtime()
    raise AssertionError("unreachable successor bridge return")


def project_successor_bridge_result(
    result: runtime.SuccessorRunResult,
) -> SuccessorBridgeResultProjection:
    """Project a native result into a narrow, redacted CLI success payload."""

    if type(result) is not runtime.SuccessorRunResult:
        _fail_input()
    attestation = result.attestation
    if type(attestation) is not runtime.TerminalAttestation:
        _fail_input()
    receipt_node_ids = tuple(item.node_id for item in attestation.receipts)
    receipt_sha256s = tuple(item.sha256 for item in attestation.receipts)
    return SuccessorBridgeResultProjection(
        schema_version=RESULT_SCHEMA_ID,
        terminal_status="PASS",
        two_fold_identity=attestation.two_fold_identity,
        attested_at=attestation.attested_at,
        reused=result.reused,
        controlled_output_root=attestation.controlled_output_root,
        fold_ids=tuple(item.fold for item in attestation.folds),
        gate_names=tuple(item.gate for item in attestation.gates),
        receipt_node_ids=receipt_node_ids,
        receipt_sha256s=receipt_sha256s,
    )


def successor_bridge_result_json_bytes(
    projection: SuccessorBridgeResultProjection,
) -> bytes:
    """Encode one success projection as canonical JSON bytes (no trailing newline)."""

    if type(projection) is not SuccessorBridgeResultProjection:
        _fail_input()
    payload = {
        "schema_version": projection.schema_version,
        "terminal_status": projection.terminal_status,
        "two_fold_identity": projection.two_fold_identity,
        "attested_at": projection.attested_at,
        "reused": projection.reused,
        "controlled_output_root": projection.controlled_output_root,
        "fold_ids": list(projection.fold_ids),
        "gate_names": list(projection.gate_names),
        "receipt_node_ids": list(projection.receipt_node_ids),
        "receipt_sha256s": list(projection.receipt_sha256s),
    }
    return _canonical_json_bytes(payload)


def _require_canonical_dependencies(
    dependencies: runtime.SuccessorProductionDependencies,
) -> None:
    from quant.research.m3 import successor_downstream_stage as downstream
    from quant.research.m3 import successor_upstream_stage as upstream

    if type(dependencies) is not runtime.SuccessorProductionDependencies:
        _fail_input()
    if (
        dependencies.stage_runner_factory is not runtime.make_project_stage_runner
        or dependencies.run_upstream_wave is not upstream.run_successor_upstream_wave
        or dependencies.run_summary is not upstream.run_successor_formal_summary_gate
        or dependencies.run_formal_stage is not downstream.run_successor_formal_stage
        or dependencies.verify_fold is not downstream.verify_successor_fold
        or dependencies.verify_summary is not downstream.verify_successor_summary_gate
        or dependencies.run_reproducibility
        is not downstream.run_successor_reproducibility_gate
        or dependencies.verify_reproducibility
        is not downstream.verify_successor_reproducibility_gate
        or dependencies.run_readiness is not downstream.run_successor_readiness_gate
        or dependencies.verify_readiness
        is not downstream.verify_successor_readiness_gate
        or dependencies.run_acceptance is not downstream.run_successor_acceptance_gate
        or dependencies.verify_acceptance
        is not downstream.verify_successor_acceptance_gate
        or dependencies.verify_gate is not downstream.verify_successor_terminal_gate
    ):
        _fail_input()


def _load_canonical_request_object(request_path: Path) -> dict[str, object]:
    raw = _read_stable_regular_file_bytes(request_path)
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail_input()
    if type(parsed) is not dict:
        _fail_input()
    # Non-finite JSON tokens (NaN/Infinity/-Infinity) parse in json.loads but
    # cannot be re-encoded under allow_nan=False; map that to INPUT, never bare.
    try:
        canonical = _canonical_json_bytes(parsed)
    except (TypeError, ValueError):
        _fail_input()
    if canonical != raw:
        _fail_input()
    return cast(dict[str, object], parsed)


def _build_runtime_request(
    payload: Mapping[str, object],
) -> tuple[runtime.SuccessorRuntimeRequest, bool]:
    root = _exact_object(payload, _REQUEST_KEYS)
    if root.get("schema_id") != REQUEST_SCHEMA_ID:
        _fail_input()

    project_root = _parse_absolute_path_text(root["project_root"])
    project = _require_real_directory(project_root)

    controlled_relative = _require_project_relative(
        root["controlled_output_root"], require_nonempty=True
    )
    # Existence / topology checks happen after fold rebuild so input failures
    # never create the controlled root.  Resolve the intended path only.
    controlled_candidate = project.joinpath(*controlled_relative.parts)

    resume = root["resume"]
    if type(resume) is not bool:
        _fail_input()

    now = _parse_canonical_utc(root["now"])
    runtime_identity = _parse_runtime_identity(root["runtime_identity"])
    fold_items = _exact_list(root["folds"])
    if len(fold_items) != 2:
        _fail_input()
    # Reject duplicate / unsorted fold ids before any config/release file IO.
    preflight_folds: list[str] = []
    for item in fold_items:
        if type(item) is not dict:
            _fail_input()
        fold_name = item.get("fold")
        if type(fold_name) is not str or _FOLD_RE.fullmatch(fold_name) is None:
            _fail_input()
        preflight_folds.append(fold_name)
    if (
        tuple(preflight_folds) != tuple(sorted(preflight_folds))
        or len(set(preflight_folds)) != 2
    ):
        _fail_input()

    folds: list[runtime.SuccessorFoldRequest] = []
    loaded_configs: list[LoadedM3Config] = []
    for item in fold_items:
        fold_request, loaded = _parse_fold(project=project, value=item)
        folds.append(fold_request)
        loaded_configs.append(loaded)

    fold_names = tuple(item.fold for item in folds)
    if fold_names != tuple(preflight_folds):
        _fail_input()

    toolchain = _parse_toolchain(
        project=project,
        value=root["toolchain"],
        fold_configs=tuple(loaded_configs),
    )

    # Controlled root must already exist and match both configs' artifact_root.
    # Fail closed without creating or writing anything under controlled root.
    controlled = _require_real_directory(controlled_candidate)
    if not controlled.is_relative_to(project) or controlled == project:
        _fail_input()
    if controlled.as_posix() != controlled_candidate.resolve(strict=True).as_posix():
        # Keep character-equal resolved form vs joined relative parts.
        if os.path.normcase(str(controlled)) != os.path.normcase(
            str(controlled_candidate.resolve(strict=True))
        ):
            _fail_input()
    expected_rel = controlled_relative.as_posix()
    actual_rel = controlled.relative_to(project).as_posix()
    if actual_rel != expected_rel:
        _fail_input()

    stage_roots: list[Path] = []
    for loaded in loaded_configs:
        try:
            stage = runtime.project_stage_root(project_root=project, config=loaded)
        except runtime.SuccessorRuntimeError as error:
            _map_runtime_error(error)
        except Exception:
            _fail_input()
        stage_roots.append(stage)
    if len(set(stage_roots)) != 1 or stage_roots[0] != controlled:
        _fail_input()

    request = runtime.SuccessorRuntimeRequest(
        project_root=project,
        controlled_output_root=controlled,
        folds=tuple(folds),
        runtime_identity=runtime_identity,
        now=now,
        toolchain=toolchain,
    )
    return request, resume


def _parse_fold(
    *, project: Path, value: object
) -> tuple[runtime.SuccessorFoldRequest, LoadedM3Config]:
    item = _exact_object(value, _FOLD_KEYS)
    fold = item["fold"]
    if type(fold) is not str or _FOLD_RE.fullmatch(fold) is None:
        _fail_input()

    config_relative = _require_project_relative(
        item["config_path"], require_prefix="configs/"
    )
    config_raw_sha = _require_hex64(item["config_raw_sha256"])
    config_full_sha = _require_hex64(item["config_full_sha256"])
    config_path = _require_project_member_file(project, config_relative)
    loaded = _fresh_load_config(config_path, expected_raw_sha256=config_raw_sha)
    if (
        loaded.raw_config_sha256 != config_raw_sha
        or loaded.full_config_sha256 != config_full_sha
    ):
        _fail_input()

    release_relative = _require_project_relative(item["g1_release_path"])
    release_id = _require_hex64(item["g1_release_id"])
    manifest_sha = _require_hex64(item["g1_release_manifest_sha256"])
    release_root = _require_project_member_directory(project, release_relative)
    if release_root.name != release_id:
        _fail_input()
    verified = _fresh_verify_release(release_root=release_root, release_id=release_id)
    if (
        verified.manifest.release_id != release_id
        or verified.manifest_sha256 != manifest_sha
    ):
        _fail_input()

    fold_request = runtime.SuccessorFoldRequest(
        fold=fold,
        config=runtime.SuccessorConfigInput(
            relative_path=config_relative,
            config=loaded,
        ),
        release=verified,
    )
    return fold_request, loaded


def _parse_runtime_identity(value: object) -> runtime.SuccessorRuntimeIdentity:
    item = _exact_object(value, _RUNTIME_IDENTITY_KEYS)
    code_version = item["code_version"]
    if (
        type(code_version) is not str
        or not code_version
        or _CONTROL_RE.search(code_version) is not None
    ):
        _fail_input()
    try:
        return runtime.SuccessorRuntimeIdentity(
            code_version=code_version,
            dependency_fingerprint_sha256=_require_hex64(
                item["dependency_fingerprint_sha256"]
            ),
            provider_runtime_fingerprint_sha256=_require_hex64(
                item["provider_runtime_fingerprint_sha256"]
            ),
        )
    except ValueError:
        _fail_input()


def _parse_toolchain(
    *,
    project: Path,
    value: object,
    fold_configs: tuple[LoadedM3Config, ...],
) -> runtime.SuccessorToolchainBinding:
    item = _exact_object(value, _TOOLCHAIN_KEYS)
    python = _parse_absolute_path_text(item["python_executable"])
    python = _require_concrete_absolute_regular_file(python)

    dump_relative = _require_project_relative(item["qlib_dump_tool_path"])
    if dump_relative != PurePosixPath(DEFAULT_TARGET_PATH.as_posix()):
        _fail_input()
    dump_path = _require_project_member_file(project, dump_relative)

    size = item["qlib_dump_tool_size_bytes"]
    if type(size) is bool or type(size) is not int or size <= 0:
        _fail_input()
    sha = _require_hex64(item["qlib_dump_tool_sha256"])

    timeout = item["timeout_seconds"]
    if (
        type(timeout) is not float
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0.0
    ):
        _fail_input()

    try:
        specs = tuple(build_qlib_dump_tool_spec(config) for config in fold_configs)
    except Exception:
        _fail_input()
    if len(specs) != 2 or specs[0] != specs[1]:
        _fail_input()
    spec = specs[0]
    if spec.size_bytes != size or spec.sha256 != sha:
        _fail_input()

    before = _lstat_regular_file(dump_path)
    raw = _read_regular_file_bytes(dump_path, expected=before)
    after = _lstat_regular_file(dump_path)
    if (
        (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        _fail_input()
    raw_after = _read_regular_file_bytes(dump_path, expected=after)
    if (
        raw_after != raw
        or len(raw) != size
        or hashlib.sha256(raw).hexdigest() != sha
    ):
        _fail_input()

    try:
        binding = runtime.SuccessorToolchainBinding(
            python_executable=python,
            qlib_dump_tool_path=dump_path,
            timeout_seconds=timeout,
        )
    except ValueError:
        _fail_input()

    try:
        from quant.research.m3.successor_upstream_stage import (
            validate_successor_toolchain_binding,
        )

        validate_successor_toolchain_binding(
            project_root=project,
            toolchain=binding,
            fold_configs=fold_configs,
        )
    except runtime.SuccessorRuntimeError as error:
        _map_runtime_error(error)
    except Exception:
        _fail_input()
    return binding


def _fresh_load_config(path: Path, *, expected_raw_sha256: str) -> LoadedM3Config:
    raw = _read_stable_regular_file_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected_raw_sha256:
        _fail_input()
    try:
        loaded = load_m3_config(path)
    except Exception:
        _fail_input()
    if type(loaded) is not LoadedM3Config:
        _fail_input()
    raw_after = _read_stable_regular_file_bytes(path)
    if raw_after != raw or loaded.raw_config_sha256 != expected_raw_sha256:
        _fail_input()
    return loaded


def _fresh_verify_release(*, release_root: Path, release_id: str) -> VerifiedG1Release:
    try:
        release = G1Release(
            release_id=release_id,
            root=release_root,
            manifest_path=release_root / "manifest.json",
            quality_path=release_root / "quality.json",
        )
        verified = verify_g1_release(release=release)
    except Exception:
        _fail_input()
    if type(verified) is not VerifiedG1Release:
        _fail_input()
    return verified


def _parse_absolute_path_text(value: object) -> Path:
    if type(value) is not str or not value or _CONTROL_RE.search(value) is not None:
        _fail_input()
    try:
        path = Path(value)
    except (TypeError, ValueError):
        _fail_input()
    return _require_exact_absolute_path(path)


def _require_exact_absolute_path(path: object) -> Path:
    if isinstance(path, PurePath) and type(path) is not _PATH_TYPE:
        _fail_input()
    if type(path) is not _PATH_TYPE:
        _fail_input()
    concrete = cast(Path, path)
    if not concrete.is_absolute():
        _fail_input()
    try:
        absolute = Path(os.path.abspath(concrete))
    except (OSError, ValueError, TypeError):
        _fail_input()
    if os.path.normcase(os.path.normpath(str(concrete))) != os.path.normcase(
        os.path.normpath(str(absolute))
    ):
        _fail_input()
    return concrete


def _require_project_relative(
    value: object, *, require_prefix: str | None = None, require_nonempty: bool = True
) -> PurePosixPath:
    if type(value) is not str:
        _fail_input()
    if require_nonempty and not value:
        _fail_input()
    if "\\" in value or ":" in value or value.startswith("/"):
        _fail_input()
    try:
        relative = PurePosixPath(value)
    except (TypeError, ValueError):
        _fail_input()
    if (
        relative.is_absolute()
        or value != relative.as_posix()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        _fail_input()
    if require_prefix is not None and not value.startswith(require_prefix):
        _fail_input()
    return relative


def _require_project_member_file(project: Path, relative: PurePosixPath) -> Path:
    current = project
    leaf_stat: os.stat_result | None = None
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            _fail_input()
        if _is_link_or_reparse(info):
            _fail_input()
        is_leaf = index == len(relative.parts) - 1
        if is_leaf:
            if not stat.S_ISREG(info.st_mode) or not _regular_file_link_count_allowed(
                info.st_nlink
            ):
                _fail_input()
            leaf_stat = info
        elif not stat.S_ISDIR(info.st_mode):
            _fail_input()
    if leaf_stat is None:
        _fail_input()
    try:
        resolved = current.resolve(strict=True)
        project_resolved = project.resolve(strict=True)
    except OSError:
        _fail_input()
    if not resolved.is_relative_to(project_resolved):
        _fail_input()
    if os.path.normcase(str(Path(os.path.abspath(current)))) != os.path.normcase(
        str(resolved)
    ):
        _fail_input()
    return resolved


def _require_project_member_directory(project: Path, relative: PurePosixPath) -> Path:
    current = project
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            _fail_input()
        if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
            _fail_input()
        del index
    try:
        resolved = current.resolve(strict=True)
        project_resolved = project.resolve(strict=True)
    except OSError:
        _fail_input()
    if not resolved.is_relative_to(project_resolved):
        _fail_input()
    return resolved


def _require_real_directory(path: Path) -> Path:
    _require_exact_absolute_path(path)
    try:
        info = os.lstat(path)
        resolved = path.resolve(strict=True)
    except OSError:
        _fail_input()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_link_or_reparse(info)
        or os.path.normcase(str(path)) != os.path.normcase(str(resolved))
    ):
        _fail_input()
    return resolved


def _require_concrete_absolute_regular_file(path: Path) -> Path:
    _require_exact_absolute_path(path)
    try:
        info = os.lstat(path)
        resolved = path.resolve(strict=True)
    except OSError:
        _fail_input()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_link_or_reparse(info)
        or not _regular_file_link_count_allowed(info.st_nlink)
        or os.path.normcase(str(path)) != os.path.normcase(str(resolved))
    ):
        _fail_input()
    return resolved


def _lstat_regular_file(path: Path) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError:
        _fail_input()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_link_or_reparse(info)
        or not _regular_file_link_count_allowed(info.st_nlink)
    ):
        _fail_input()
    return info


def _read_regular_file_bytes(path: Path, *, expected: os.stat_result) -> bytes:
    try:
        info = os.lstat(path)
    except OSError:
        _fail_input()
    if (
        (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino)
        or not stat.S_ISREG(info.st_mode)
        or _is_link_or_reparse(info)
        or not _regular_file_link_count_allowed(info.st_nlink)
    ):
        _fail_input()
    try:
        return Path(path).read_bytes()
    except OSError:
        _fail_input()


def _read_stable_regular_file_bytes(path: Path) -> bytes:
    """Non-following TOCTOU closure: lstat → read → lstat(+mtime) → re-read."""

    before = _lstat_regular_file(path)
    raw = _read_regular_file_bytes(path, expected=before)
    after = _lstat_regular_file(path)
    if (
        (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        _fail_input()
    raw_after = _read_regular_file_bytes(path, expected=after)
    if raw_after != raw:
        _fail_input()
    return raw


def _regular_file_link_count_allowed(nlink: int) -> bool:
    if sys.platform == "win32":
        return nlink in {0, 1}
    return nlink == 1


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return bool(stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & _REPARSE))


def _parse_canonical_utc(value: object) -> dt.datetime:
    if type(value) is not str or not value.endswith("Z"):
        _fail_input()
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail_input()
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        _fail_input()
    text = parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    if text != value:
        _fail_input()
    return parsed


def _exact_object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail_input()
    return cast(dict[str, object], value)


def _exact_list(value: object) -> list[object]:
    if type(value) is not list:
        _fail_input()
    return cast(list[object], value)


def _reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ValueError("duplicate or invalid JSON key")
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _require_hex64(value: object) -> str:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        _fail_input()
    return value


def _is_hex64(value: object) -> bool:
    return type(value) is str and _HEX64_RE.fullmatch(value) is not None


def _map_runtime_error(error: runtime.SuccessorRuntimeError) -> NoReturn:
    if error.code in _RUNTIME_INPUT_CODES:
        _fail_input()
    _fail_runtime()


def _fail_input() -> NoReturn:
    raise SuccessorBridgeError(BRIDGE_INPUT_ERROR) from None


def _fail_runtime() -> NoReturn:
    raise SuccessorBridgeError(BRIDGE_RUNTIME_ERROR) from None


__all__ = [
    "BRIDGE_INPUT_ERROR",
    "BRIDGE_RUNTIME_ERROR",
    "REQUEST_SCHEMA_ID",
    "RESULT_SCHEMA_ID",
    "SuccessorBridgeError",
    "SuccessorBridgeResultProjection",
    "project_successor_bridge_result",
    "run_production_successor_bridge",
    "successor_bridge_result_json_bytes",
]
