"""Fail-closed code and dependency identity for M3 experiment/work stages."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

_HEX = re.compile(r"^[0-9a-f]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NOT_INSTALLED = "NOT_INSTALLED"
_DEPENDENCY_DISTRIBUTIONS = (
    "duckdb",
    "lightgbm",
    "loguru",
    "mlflow",
    "numpy",
    "pandas",
    "pandera",
    "polars",
    "pyarrow",
    "pydantic",
    "pydantic-settings",
    "pyqlib",
    "quantstats",
    "scikit-learn",
    "scipy",
)
_DEFAULT_CONFIG_PATHS = (PurePosixPath("configs/research/m3_qlib_example.toml"),)


class M3RuntimeIdentityError(ValueError):
    """Stable boundary error without host paths or dependency exception details."""

    _CODES = frozenset(
        {
            "M3_RUNTIME_IDENTITY_INPUT_INVALID",
            "M3_RUNTIME_IDENTITY_SOURCE_INVALID",
            "M3_RUNTIME_IDENTITY_GIT_INVALID",
            "M3_RUNTIME_IDENTITY_DEPENDENCY_INVALID",
            "M3_RUNTIME_IDENTITY_DRIFT",
        }
    )

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown runtime identity error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, order=True)
class M3SourceDigestV1:
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        _require_relative(self.relative_path)
        _require_hex64(self.sha256)


@dataclass(frozen=True, order=True)
class M3DependencyVersionV1:
    distribution: str
    version: str

    def __post_init__(self) -> None:
        if (
            type(self.distribution) is not str
            or not self.distribution
            or _CONTROL.search(self.distribution)
            or type(self.version) is not str
            or not self.version
            or _CONTROL.search(self.version)
        ):
            raise ValueError("invalid dependency version")


@dataclass(frozen=True)
class M3RuntimeIdentityV1:
    schema_version: Literal["m3-runtime-identity-v1"]
    code_version: str
    code_source: Literal["git", "source-tree-fallback"]
    git_commit: str | None
    git_status_sha256: str | None
    git_dirty_content_sha256: str | None
    source_tree_sha256: str
    source_files: tuple[M3SourceDigestV1, ...]
    pyproject_sha256: str
    python_implementation: str
    python_version: str
    os_name: str
    sys_platform: str
    platform_system: str
    platform_release: str
    machine: str
    dependencies: tuple[M3DependencyVersionV1, ...]
    dependency_fingerprint_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-runtime-identity-v1":
            raise ValueError("invalid runtime identity schema")
        if self.code_source not in {"git", "source-tree-fallback"}:
            raise ValueError("invalid code source")
        for value in (
            self.code_version,
            self.python_implementation,
            self.python_version,
            self.os_name,
            self.sys_platform,
            self.platform_system,
            self.platform_release,
            self.machine,
        ):
            if type(value) is not str or not value or _CONTROL.search(value):
                raise ValueError("invalid runtime identity string")
        for value in (
            self.source_tree_sha256,
            self.pyproject_sha256,
            self.dependency_fingerprint_sha256,
        ):
            _require_hex64(value)
        if self.source_files != tuple(sorted(self.source_files)) or not self.source_files:
            raise ValueError("invalid source closure")
        if self.dependencies != tuple(sorted(self.dependencies)):
            raise ValueError("invalid dependency closure")
        if tuple(item.distribution for item in self.dependencies) != _DEPENDENCY_DISTRIBUTIONS:
            raise ValueError("invalid dependency set")
        if self.code_source == "git":
            if (
                type(self.git_commit) is not str
                or len(self.git_commit) not in {40, 64}
                or not _HEX.fullmatch(self.git_commit)
            ):
                raise ValueError("invalid git commit")
            if self.git_status_sha256 is None:
                raise ValueError("missing git status identity")
            _require_hex64(self.git_status_sha256)
            if self.git_dirty_content_sha256 is not None:
                _require_hex64(self.git_dirty_content_sha256)
            expected_dirty = _hash_json(
                {
                    "schema_version": "m3-git-dirty-content-v1",
                    "status_sha256": self.git_status_sha256,
                    "source_tree_sha256": self.source_tree_sha256,
                    "pyproject_sha256": self.pyproject_sha256,
                }
            )
            expected_clean = _hash_json(
                {
                    "schema_version": "m3-git-clean-content-v1",
                    "source_tree_sha256": self.source_tree_sha256,
                    "pyproject_sha256": self.pyproject_sha256,
                }
            )
            expected_code = (
                f"m3-git-v1-{self.git_commit}-clean-{expected_clean}"
                if self.git_dirty_content_sha256 is None
                else f"m3-git-v1-{self.git_commit}-dirty-{expected_dirty}"
            )
            if (
                self.code_version != expected_code
                or (
                    self.git_dirty_content_sha256 is None
                    and self.git_status_sha256 != hashlib.sha256(b"").hexdigest()
                )
                or (
                    self.git_dirty_content_sha256 is not None
                    and self.git_dirty_content_sha256 != expected_dirty
                )
            ):
                raise ValueError("invalid git content identity")
        elif (
            self.git_commit is not None
            or self.git_status_sha256 is not None
            or self.git_dirty_content_sha256 is not None
        ):
            raise ValueError("fallback identity contains git metadata")
        if self.source_tree_sha256 != _hash_json(
            {
                "schema_version": "m3-source-tree-v1",
                "files": [asdict(item) for item in self.source_files],
            }
        ):
            raise ValueError("invalid source tree identity")
        if self.code_source == "source-tree-fallback" and self.code_version != (
            f"m3-source-v1-{self.source_tree_sha256}"
        ):
            raise ValueError("invalid fallback code identity")
        if self.dependency_fingerprint_sha256 != _dependency_fingerprint(
            pyproject_sha256=self.pyproject_sha256,
            platform_values=(
                self.python_implementation,
                self.python_version,
                self.os_name,
                self.sys_platform,
                self.platform_system,
                self.platform_release,
                self.machine,
            ),
            dependencies=self.dependencies,
        ):
            raise ValueError("invalid dependency identity")


@dataclass(frozen=True)
class _GitProbe:
    available: bool
    commit: str | None
    status_sha256: str | None
    dirty: bool


@dataclass(frozen=True)
class _IdentityProbe:
    files: tuple[M3SourceDigestV1, ...]
    source_tree_sha256: str
    pyproject_sha256: str
    git: _GitProbe
    platform_values: tuple[str, ...]
    dependencies: tuple[M3DependencyVersionV1, ...]


def compute_m3_runtime_identity(
    *,
    project_root: Path,
    config_paths: Sequence[PurePosixPath] = _DEFAULT_CONFIG_PATHS,
) -> M3RuntimeIdentityV1:
    """Measure M3 code/dependencies twice and reject any mid-probe drift."""
    try:
        root = _validate_project_root(project_root)
        configs = _validate_config_paths(config_paths)
        first = _probe(root, configs)
        second = _probe(root, configs)
        if first != second:
            raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_DRIFT")
        code_source: Literal["git", "source-tree-fallback"]
        dirty_sha: str | None = None
        if first.git.available:
            if first.git.commit is None or first.git.status_sha256 is None:
                raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID")
            code_source = "git"
            if first.git.dirty:
                dirty_sha = _hash_json(
                    {
                        "schema_version": "m3-git-dirty-content-v1",
                        "status_sha256": first.git.status_sha256,
                        "source_tree_sha256": first.source_tree_sha256,
                        "pyproject_sha256": first.pyproject_sha256,
                    }
                )
                code_version = f"m3-git-v1-{first.git.commit}-dirty-{dirty_sha}"
            else:
                clean_sha = _hash_json(
                    {
                        "schema_version": "m3-git-clean-content-v1",
                        "source_tree_sha256": first.source_tree_sha256,
                        "pyproject_sha256": first.pyproject_sha256,
                    }
                )
                code_version = f"m3-git-v1-{first.git.commit}-clean-{clean_sha}"
            git_commit = first.git.commit
        else:
            code_source = "source-tree-fallback"
            git_commit = None
            code_version = f"m3-source-v1-{first.source_tree_sha256}"
        dependency_sha = _dependency_fingerprint(
            pyproject_sha256=first.pyproject_sha256,
            platform_values=first.platform_values,
            dependencies=first.dependencies,
        )
        return M3RuntimeIdentityV1(
            schema_version="m3-runtime-identity-v1",
            code_version=code_version,
            code_source=code_source,
            git_commit=git_commit,
            git_status_sha256=first.git.status_sha256,
            git_dirty_content_sha256=dirty_sha,
            source_tree_sha256=first.source_tree_sha256,
            source_files=first.files,
            pyproject_sha256=first.pyproject_sha256,
            python_implementation=first.platform_values[0],
            python_version=first.platform_values[1],
            os_name=first.platform_values[2],
            sys_platform=first.platform_values[3],
            platform_system=first.platform_values[4],
            platform_release=first.platform_values[5],
            machine=first.platform_values[6],
            dependencies=first.dependencies,
            dependency_fingerprint_sha256=dependency_sha,
        )
    except M3RuntimeIdentityError:
        raise
    except (OSError, TypeError, ValueError):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID") from None


def runtime_identity_bytes(identity: M3RuntimeIdentityV1) -> bytes:
    """Return canonical, path-safe diagnostic bytes for a measured identity."""
    if type(identity) is not M3RuntimeIdentityV1:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
    return _canonical_json(asdict(identity))


def _probe(root: Path, configs: tuple[PurePosixPath, ...]) -> _IdentityProbe:
    files = _collect_source_files(root, configs)
    pyproject_sha = _read_hash(root / "pyproject.toml")
    git = _probe_git(root, configs)
    platform_values = _platform_values()
    dependencies = _dependency_versions()
    return _IdentityProbe(
        files=files,
        source_tree_sha256=_hash_json(
            {
                "schema_version": "m3-source-tree-v1",
                "files": [asdict(item) for item in files],
            }
        ),
        pyproject_sha256=pyproject_sha,
        git=git,
        platform_values=platform_values,
        dependencies=dependencies,
    )


def _validate_project_root(path: Path) -> Path:
    if not isinstance(path, Path):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
    root = path.resolve(strict=True)
    for required in (root / "src" / "quant", root / "configs", root / "pyproject.toml"):
        st = os.lstat(required)
        if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
            raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID")
    return root


def _validate_config_paths(
    paths: Sequence[PurePosixPath],
) -> tuple[PurePosixPath, ...]:
    if isinstance(paths, (str, bytes)):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
    result: list[PurePosixPath] = []
    for value in paths:
        if type(value) is not PurePosixPath:
            raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
        _require_relative(value.as_posix())
        if not value.parts or value.parts[0] != "configs":
            raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
        result.append(value)
    ordered = tuple(sorted(set(result), key=lambda item: item.as_posix().encode("utf-8")))
    if not ordered:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_INPUT_INVALID")
    return ordered


def _collect_source_files(
    root: Path, configs: tuple[PurePosixPath, ...]
) -> tuple[M3SourceDigestV1, ...]:
    src_root = root / "src" / "quant"
    entries: list[M3SourceDigestV1] = []
    try:
        for path in src_root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
                raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID")
            if stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode):
                raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID")
            if path.suffix == ".py" or path.name == "py.typed":
                entries.append(M3SourceDigestV1(relative, _read_hash(path)))
        for config_relative in configs:
            path = root.joinpath(*config_relative.parts)
            entries.append(
                M3SourceDigestV1(config_relative.as_posix(), _read_hash(path))
            )
    except M3RuntimeIdentityError:
        raise
    except OSError:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID") from None
    ordered = tuple(sorted(entries))
    if not ordered or len({item.relative_path for item in ordered}) != len(ordered):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID")
    return ordered


def _read_hash(path: Path) -> str:
    try:
        before = os.lstat(path)
        if (
            stat.S_ISLNK(before.st_mode)
            or _is_reparse(before)
            or not stat.S_ISREG(before.st_mode)
        ):
            raise OSError
        payload = path.read_bytes()
        after = os.lstat(path)
        if (
            not stat.S_ISREG(after.st_mode)
            or _is_reparse(after)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(payload) != before.st_size
        ):
            raise OSError
        return hashlib.sha256(payload).hexdigest()
    except OSError:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_SOURCE_INVALID") from None


def _probe_git(root: Path, configs: tuple[PurePosixPath, ...]) -> _GitProbe:
    marker = root / ".git"
    try:
        marker_state = os.lstat(marker)
    except FileNotFoundError:
        return _GitProbe(False, None, None, False)
    if stat.S_ISLNK(marker_state.st_mode) or _is_reparse(marker_state):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID")
    try:
        commit_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                "src/quant",
                "pyproject.toml",
                *(item.as_posix() for item in configs),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except FileNotFoundError:
        return _GitProbe(False, None, None, False)
    except (OSError, subprocess.SubprocessError):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID") from None
    if commit_result.returncode != 0 or status_result.returncode != 0:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID")
    try:
        commit = commit_result.stdout.decode("ascii").strip().lower()
    except UnicodeError:
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID") from None
    if len(commit) not in {40, 64} or not _HEX.fullmatch(commit):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_GIT_INVALID")
    status = status_result.stdout
    return _GitProbe(
        True,
        commit,
        hashlib.sha256(status).hexdigest(),
        bool(status),
    )


def _platform_values() -> tuple[str, ...]:
    values = (
        sys.implementation.name,
        platform.python_version(),
        os.name,
        sys.platform,
        platform.system(),
        platform.release(),
        platform.machine(),
    )
    if any(type(value) is not str or not value or _CONTROL.search(value) for value in values):
        raise M3RuntimeIdentityError("M3_RUNTIME_IDENTITY_DEPENDENCY_INVALID")
    return values


def _is_reparse(status: os.stat_result) -> bool:
    return bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _dependency_versions() -> tuple[M3DependencyVersionV1, ...]:
    result: list[M3DependencyVersionV1] = []
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = _NOT_INSTALLED
        except Exception:
            raise M3RuntimeIdentityError(
                "M3_RUNTIME_IDENTITY_DEPENDENCY_INVALID"
            ) from None
        try:
            result.append(M3DependencyVersionV1(distribution, version))
        except ValueError:
            raise M3RuntimeIdentityError(
                "M3_RUNTIME_IDENTITY_DEPENDENCY_INVALID"
            ) from None
    return tuple(result)


def _dependency_fingerprint(
    *,
    pyproject_sha256: str,
    platform_values: tuple[str, ...],
    dependencies: tuple[M3DependencyVersionV1, ...],
) -> str:
    return _hash_json(
        {
            "schema_version": "m3-full-dependency-fingerprint-v1",
            "pyproject_sha256": pyproject_sha256,
            "python": {
                "implementation": platform_values[0],
                "version": platform_values[1],
            },
            "platform": {
                "os_name": platform_values[2],
                "sys_platform": platform_values[3],
                "system": platform_values[4],
                "release": platform_values[5],
                "machine": platform_values[6],
            },
            "dependencies": [asdict(item) for item in dependencies],
        }
    )


def _require_relative(value: str) -> None:
    if type(value) is not str or not value or "\\" in value or _CONTROL.search(value):
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("invalid relative path")


def _require_hex64(value: str) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError("invalid sha256")


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
