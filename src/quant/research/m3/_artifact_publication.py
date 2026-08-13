"""Private anchored publication transaction for M3 artifact builders."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, NoReturn

_LEASE_NAME = ".m3-artifact-publication.lease"
_OPEN_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0)
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_ACTIVE_ROOTS: set[str] = set()
_ACTIVE_ROOTS_LOCK = threading.Lock()


class ArtifactPublicationError(Exception):
    """An internal publication failure whose rollback may still succeed."""


class ArtifactRollbackError(Exception):
    """An internal failure to prove exact rollback of owned outputs."""


def _raise_publication_error() -> NoReturn:
    try:
        raise ArtifactPublicationError
    except ArtifactPublicationError as error:
        error.__context__ = None
        error.__cause__ = None
        raise


def _raise_rollback_error() -> NoReturn:
    try:
        raise ArtifactRollbackError
    except ArtifactRollbackError as error:
        error.__context__ = None
        error.__cause__ = None
        raise


@dataclass
class _OwnedDirectory:
    identity: os.stat_result
    directory_fd: int | None = None
    windows_handle: int | None = None
    windows_identity: tuple[int, int, int, int] | None = None


def _parse_publication_name(name: object) -> tuple[str, ...]:
    if type(name) is not str or not name or len(name) > 257:
        raise ArtifactPublicationError
    if "\\" in name or ":" in name or "\x00" in name:
        raise ArtifactPublicationError
    parts = tuple(name.split("/"))
    if len(parts) not in {1, 2} or "/".join(parts) != name:
        raise ArtifactPublicationError
    for component in parts:
        stem = component.split(".", 1)[0].casefold()
        if (
            _COMPONENT.fullmatch(component) is None
            or component in {".", "..", _LEASE_NAME}
            or component.endswith(".")
            or stem in _WINDOWS_RESERVED
        ):
            raise ArtifactPublicationError
    return parts


def _parse_expected_names(
    names: Collection[str],
) -> tuple[set[str], dict[str, set[str]]]:
    if isinstance(names, (str, bytes)):
        raise ArtifactPublicationError
    try:
        raw_names = tuple(names)
    except Exception:
        raise ArtifactPublicationError from None
    parsed = tuple((_parse_publication_name(name), name) for name in raw_names)
    if len({name for _, name in parsed}) != len(parsed):
        raise ArtifactPublicationError

    canonical_by_key: dict[str, str] = {}
    root_files: dict[str, str] = {}
    child_names: dict[str, str] = {}
    child_files: dict[str, set[str]] = {}
    for parts, name in parsed:
        key = name.casefold()
        if key in canonical_by_key:
            raise ArtifactPublicationError
        canonical_by_key[key] = name
        if len(parts) == 1:
            root_key = parts[0].casefold()
            if root_key in root_files or root_key in child_names:
                raise ArtifactPublicationError
            root_files[root_key] = parts[0]
            continue
        parent, leaf = parts
        parent_key = parent.casefold()
        if parent_key in root_files:
            raise ArtifactPublicationError
        existing_parent = child_names.get(parent_key)
        if existing_parent is not None and existing_parent != parent:
            raise ArtifactPublicationError
        child_names[parent_key] = parent
        child_files.setdefault(parent, set()).add(leaf)
    return {name for _, name in parsed}, child_files


class ArtifactPublication:
    """Anchor one caller-created output directory for one publication call."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self._root_identity: os.stat_result | None = None
        self._directory_fd: int | None = None
        self._windows_handle: int | None = None
        self._windows_identity: tuple[int, int, int, int] | None = None
        self._lease_identity: os.stat_result | None = None
        self._lease_created = False
        self._owned: dict[str, os.stat_result] = {}
        self._children: dict[str, _OwnedDirectory] = {}
        self._registry_key: str | None = None
        self._committed = False
        self._closed = False

    def __enter__(self) -> ArtifactPublication:
        failed = False
        rollback_failed = False
        try:
            self._acquire()
        except Exception as error:
            failed = True
            rollback_failed = (
                isinstance(error, ArtifactRollbackError)
                or self._cleanup_failed_acquire()
            )
        if rollback_failed:
            _raise_rollback_error()
        if failed:
            _raise_publication_error()
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object,
    ) -> Literal[False]:
        del exc_type, exc, traceback
        if self._committed:
            return False
        if self._rollback():
            _raise_rollback_error()
        return False

    def write_bytes(self, name: str, raw: bytes) -> None:
        """Exclusive-create, flush and fsync one owned final file."""
        self.write_stream(name, lambda stream: stream.write(raw))

    def write_stream(self, name: str, writer: Callable[[BinaryIO], object]) -> None:
        """Write one owned final file through its already-exclusive stream."""
        descriptor = -1
        failed = False
        try:
            parts = _parse_publication_name(name)
            self._require_path_available(parts)
            self._require_current_root()
            child = self._ensure_child(parts[0]) if len(parts) == 2 else None
            if child is not None:
                self._require_current_child(parts[0])
            descriptor = self._open_parsed_output(parts)
            identity = os.fstat(descriptor)
            if (
                not stat.S_ISREG(identity.st_mode)
                or _is_link_or_reparse(identity)
                or identity.st_nlink != 1
            ):
                raise ArtifactPublicationError
            self._owned[name] = identity
            self._require_current_root()
            if child is not None:
                self._require_current_child(parts[0])
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                writer(stream)
                stream.flush()
                os.fsync(stream.fileno())
            self._require_current_root()
            if child is None:
                self._sync_directory()
            else:
                self._require_current_child(parts[0])
                self._sync_child(parts[0])
        except Exception:
            failed = True
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if failed:
            _raise_publication_error()

    def read_bytes(self, name: str) -> bytes:
        """Read an owned file through its anchored parent directory."""
        descriptor = -1
        failed = False
        raw = b""
        try:
            parts = _parse_publication_name(name)
            self._require_current_root()
            if len(parts) == 2:
                self._require_current_child(parts[0])
            expected = self._require_owned_identity(name)
            descriptor = self._open_parsed_read(parts)
            opened = os.fstat(descriptor)
            if (
                _is_link_or_reparse(opened)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not os.path.samestat(expected, opened)
            ):
                raise ArtifactPublicationError
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read()
            self._require_current_root()
            if len(parts) == 2:
                self._require_current_child(parts[0])
            self._require_owned_identity(name)
            return raw
        except Exception:
            failed = True
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if failed:
            _raise_publication_error()
        return raw

    def sha256(self, name: str) -> str:
        return hashlib.sha256(self.read_bytes(name)).hexdigest()

    def commit(self, expected_names: Collection[str]) -> None:
        """Verify the whole tree, remove the lease, and close all anchors."""
        failed = False
        try:
            expected, expected_children = _parse_expected_names(expected_names)
            if expected != set(self._owned) or _LEASE_NAME in expected:
                raise ArtifactPublicationError
            if set(expected_children) != set(self._children):
                raise ArtifactPublicationError
            self._require_current_root()
            self._require_exact_tree(expected, expected_children, include_lease=True)
            for name in expected:
                self._require_owned_identity(name)
            for parent in expected_children:
                self._sync_child(parent)
            self._unlink_lease(require_identity=True)
            self._sync_directory()
            self._require_current_root()
            self._require_exact_tree(expected, expected_children, include_lease=False)
            for name in expected:
                self._require_owned_identity(name)
            self._close_child_anchors()
            self._close_anchor()
        except Exception:
            failed = True
        if failed:
            _raise_publication_error()
        self._committed = True

    def _acquire(self) -> None:
        _require_real_ancestors(self.root)
        initial = os.lstat(self.root)
        if not stat.S_ISDIR(initial.st_mode) or _is_link_or_reparse(initial):
            raise ArtifactPublicationError
        self._root_identity = initial
        if os.name == "nt":
            handle = _open_windows_directory_handle(self.root)
            self._windows_handle = handle
            self._windows_identity = _windows_handle_identity(handle)
            if (
                self._windows_identity[3] & _windows_reparse_attribute()
                or _windows_file_index(self._windows_identity) != initial.st_ino
            ):
                raise ArtifactPublicationError
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise ArtifactPublicationError
            self._directory_fd = os.open(self.root, flags | nofollow)
            anchored = os.fstat(self._directory_fd)
            if not stat.S_ISDIR(anchored.st_mode) or not os.path.samestat(initial, anchored):
                raise ArtifactPublicationError
        self._require_current_root()
        registry_key = os.path.normcase(str(self.root))
        with _ACTIVE_ROOTS_LOCK:
            if registry_key in _ACTIVE_ROOTS:
                raise ArtifactPublicationError
            _ACTIVE_ROOTS.add(registry_key)
            self._registry_key = registry_key
        self._require_exact_entries(set())
        descriptor = self._open_output(_LEASE_NAME)
        self._lease_created = True
        try:
            self._lease_identity = os.fstat(descriptor)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(b"m3-artifact-publication-v1\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise ArtifactPublicationError from None
        self._sync_directory()
        self._require_exact_entries({_LEASE_NAME})

    def _require_path_available(self, parts: tuple[str, ...]) -> None:
        name = "/".join(parts)
        name_key = name.casefold()
        if any(existing.casefold() == name_key for existing in self._owned):
            raise ArtifactPublicationError
        flat_keys = {
            existing.casefold() for existing in self._owned if "/" not in existing
        }
        child_by_key = {child.casefold(): child for child in self._children}
        if len(parts) == 1:
            if parts[0].casefold() in child_by_key:
                raise ArtifactPublicationError
            return
        parent = parts[0]
        parent_key = parent.casefold()
        if parent_key in flat_keys:
            raise ArtifactPublicationError
        existing_parent = child_by_key.get(parent_key)
        if existing_parent is not None and existing_parent != parent:
            raise ArtifactPublicationError

    def _ensure_child(self, name: str) -> _OwnedDirectory:
        existing = self._children.get(name)
        if existing is not None:
            return existing
        self._require_current_root()
        if self._directory_fd is not None:
            os.mkdir(name, 0o755, dir_fd=self._directory_fd)
        else:
            os.mkdir(self.root / name, 0o755)
        identity = self._stat_entry(name)
        child = _OwnedDirectory(identity=identity)
        self._children[name] = child
        if not stat.S_ISDIR(identity.st_mode) or _is_link_or_reparse(identity):
            raise ArtifactPublicationError
        if os.name == "nt":
            handle = _open_windows_directory_handle(self.root / name)
            child.windows_handle = handle
            child.windows_identity = _windows_handle_identity(handle)
            if (
                child.windows_identity[3] & _windows_reparse_attribute()
                or _windows_file_index(child.windows_identity) != identity.st_ino
            ):
                raise ArtifactPublicationError
        else:
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow or self._directory_fd is None:
                raise ArtifactPublicationError
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
            child.directory_fd = os.open(name, flags, dir_fd=self._directory_fd)
            anchored = os.fstat(child.directory_fd)
            if not stat.S_ISDIR(anchored.st_mode) or not os.path.samestat(identity, anchored):
                raise ArtifactPublicationError
        self._require_current_root()
        self._require_current_child(name)
        self._sync_directory()
        return child

    def _open_output(self, name: str) -> int:
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ArtifactPublicationError
        if self._directory_fd is not None:
            return os.open(name, _OPEN_FLAGS, 0o644, dir_fd=self._directory_fd)
        return os.open(self.root / name, _OPEN_FLAGS, 0o644)

    def _open_parsed_output(self, parts: tuple[str, ...]) -> int:
        if len(parts) == 1:
            return self._open_output(parts[0])
        child = self._children.get(parts[0])
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            return os.open(parts[1], _OPEN_FLAGS, 0o644, dir_fd=child.directory_fd)
        return os.open(self.root / parts[0] / parts[1], _OPEN_FLAGS, 0o644)

    def _open_parsed_read(self, parts: tuple[str, ...]) -> int:
        flags = _READ_FLAGS
        if os.name != "nt":
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise ArtifactPublicationError
            flags |= nofollow
        if len(parts) == 1:
            if self._directory_fd is not None:
                return os.open(parts[0], flags, dir_fd=self._directory_fd)
            return os.open(self.root / parts[0], flags)
        child = self._children.get(parts[0])
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            return os.open(parts[1], flags, dir_fd=child.directory_fd)
        return os.open(self.root / parts[0] / parts[1], flags)

    def _require_current_root(self) -> None:
        if self._root_identity is None:
            raise ArtifactPublicationError
        _require_real_ancestors(self.root)
        current = os.lstat(self.root)
        if (
            not stat.S_ISDIR(current.st_mode)
            or _is_link_or_reparse(current)
            or not os.path.samestat(self._root_identity, current)
        ):
            raise ArtifactPublicationError
        if self._directory_fd is not None:
            anchored = os.fstat(self._directory_fd)
            if not os.path.samestat(self._root_identity, anchored):
                raise ArtifactPublicationError
        if self._windows_handle is not None:
            handle_identity = _windows_handle_identity(self._windows_handle)
            if (
                handle_identity != self._windows_identity
                or _windows_file_index(handle_identity) != current.st_ino
            ):
                raise ArtifactPublicationError

    def _require_current_child(self, name: str) -> None:
        child = self._children.get(name)
        if child is None:
            raise ArtifactPublicationError
        current = self._stat_entry(name)
        if (
            not stat.S_ISDIR(current.st_mode)
            or _is_link_or_reparse(current)
            or not os.path.samestat(child.identity, current)
        ):
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            anchored = os.fstat(child.directory_fd)
            if not os.path.samestat(child.identity, anchored):
                raise ArtifactPublicationError
        if child.windows_handle is not None:
            handle_identity = _windows_handle_identity(child.windows_handle)
            if (
                handle_identity != child.windows_identity
                or _windows_file_index(handle_identity) != current.st_ino
            ):
                raise ArtifactPublicationError

    def _entries(self) -> set[str]:
        if self._directory_fd is not None:
            return set(os.listdir(self._directory_fd))
        return {item.name for item in os.scandir(self.root)}

    def _child_entries(self, name: str) -> set[str]:
        child = self._children.get(name)
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            return set(os.listdir(child.directory_fd))
        return {item.name for item in os.scandir(self.root / name)}

    def _require_exact_entries(self, expected: set[str]) -> None:
        if self._entries() != expected:
            raise ArtifactPublicationError

    def _require_exact_tree(
        self,
        expected: set[str],
        expected_children: dict[str, set[str]],
        *,
        include_lease: bool,
    ) -> None:
        root_files = {name for name in expected if "/" not in name}
        root_entries = root_files | set(expected_children)
        if include_lease:
            root_entries.add(_LEASE_NAME)
        self._require_exact_entries(root_entries)
        for parent, leaves in expected_children.items():
            self._require_current_child(parent)
            if self._child_entries(parent) != leaves:
                raise ArtifactPublicationError

    def _stat_entry(self, name: str) -> os.stat_result:
        if self._directory_fd is not None:
            return os.stat(name, dir_fd=self._directory_fd, follow_symlinks=False)
        return os.lstat(self.root / name)

    def _stat_owned_path(self, name: str) -> os.stat_result:
        parts = _parse_publication_name(name)
        if len(parts) == 1:
            return self._stat_entry(parts[0])
        child = self._children.get(parts[0])
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            return os.stat(parts[1], dir_fd=child.directory_fd, follow_symlinks=False)
        return os.lstat(self.root / parts[0] / parts[1])

    def _require_owned_identity(self, name: str) -> os.stat_result:
        expected = self._owned.get(name)
        if expected is None:
            raise ArtifactPublicationError
        parts = _parse_publication_name(name)
        self._require_current_root()
        if len(parts) == 2:
            self._require_current_child(parts[0])
        current = self._stat_owned_path(name)
        if (
            _is_link_or_reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or not os.path.samestat(expected, current)
        ):
            raise ArtifactPublicationError
        return expected

    def _unlink_entry(self, name: str) -> None:
        if self._directory_fd is not None:
            os.unlink(name, dir_fd=self._directory_fd)
        else:
            (self.root / name).unlink()

    def _unlink_owned_path(self, name: str) -> None:
        parts = _parse_publication_name(name)
        if len(parts) == 1:
            self._unlink_entry(parts[0])
            return
        child = self._children.get(parts[0])
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            os.unlink(parts[1], dir_fd=child.directory_fd)
        else:
            (self.root / parts[0] / parts[1]).unlink()

    def _unlink_lease(self, *, require_identity: bool) -> None:
        if self._lease_identity is None:
            if require_identity or self._lease_created:
                raise ArtifactPublicationError
            return
        current = self._stat_entry(_LEASE_NAME)
        if not os.path.samestat(self._lease_identity, current):
            raise ArtifactPublicationError
        self._unlink_entry(_LEASE_NAME)
        self._lease_identity = None
        self._lease_created = False

    def _rollback(self) -> bool:
        failed = False
        for name, identity in reversed(tuple(self._owned.items())):
            try:
                parts = _parse_publication_name(name)
                self._require_current_root()
                if len(parts) == 2:
                    self._require_current_child(parts[0])
                current = self._stat_owned_path(name)
                if (
                    _is_link_or_reparse(current)
                    or current.st_nlink != 1
                    or not os.path.samestat(identity, current)
                ):
                    failed = True
                    continue
                self._unlink_owned_path(name)
                if len(parts) == 1:
                    self._sync_directory()
                else:
                    self._sync_child(parts[0])
            except Exception:
                failed = True
        self._owned.clear()

        for name, child in reversed(tuple(self._children.items())):
            removable = True
            try:
                self._require_current_root()
                self._require_current_child(name)
                if self._child_entries(name):
                    removable = False
                    failed = True
            except Exception:
                removable = False
                failed = True
            try:
                self._close_child_anchor(child)
            except Exception:
                removable = False
                failed = True
            if removable:
                try:
                    current = self._stat_entry(name)
                    if (
                        not stat.S_ISDIR(current.st_mode)
                        or _is_link_or_reparse(current)
                        or not os.path.samestat(child.identity, current)
                    ):
                        raise ArtifactPublicationError
                    if any(os.scandir(self.root / name)):
                        raise ArtifactPublicationError
                    if self._directory_fd is not None:
                        os.rmdir(name, dir_fd=self._directory_fd)
                    else:
                        os.rmdir(self.root / name)
                    self._sync_directory()
                except Exception:
                    failed = True
        self._children.clear()

        try:
            self._unlink_lease(require_identity=self._lease_identity is not None)
        except Exception:
            failed = True
        try:
            self._sync_directory()
            if self._entries():
                failed = True
        except Exception:
            failed = True
        try:
            self._close_anchor()
        except Exception:
            failed = True
        return failed

    def _cleanup_failed_acquire(self) -> bool:
        if self._lease_created or self._owned or self._children:
            return self._rollback()
        try:
            self._close_anchor()
        except Exception:
            return True
        return False

    def _sync_directory(self) -> None:
        if self._directory_fd is not None:
            os.fsync(self._directory_fd)
        if self._windows_handle is not None:
            _flush_windows_handle(self._windows_handle)

    def _sync_child(self, name: str) -> None:
        child = self._children.get(name)
        if child is None:
            raise ArtifactPublicationError
        if child.directory_fd is not None:
            os.fsync(child.directory_fd)
        if child.windows_handle is not None:
            _flush_windows_handle(child.windows_handle)

    def _close_child_anchor(self, child: _OwnedDirectory) -> None:
        failed = False
        if child.directory_fd is not None:
            try:
                os.close(child.directory_fd)
            except OSError:
                failed = True
            child.directory_fd = None
        if child.windows_handle is not None:
            if not _close_windows_handle(child.windows_handle):
                failed = True
            child.windows_handle = None
        if failed:
            raise ArtifactRollbackError

    def _close_child_anchors(self) -> None:
        failed = False
        for child in reversed(tuple(self._children.values())):
            try:
                self._close_child_anchor(child)
            except Exception:
                failed = True
        if failed:
            raise ArtifactRollbackError

    def _close_anchor(self) -> None:
        if self._closed:
            return
        failed = False
        if self._directory_fd is not None:
            try:
                os.close(self._directory_fd)
            except OSError:
                failed = True
            self._directory_fd = None
        if self._windows_handle is not None:
            if not _close_windows_handle(self._windows_handle):
                failed = True
            self._windows_handle = None
        if self._registry_key is not None:
            with _ACTIVE_ROOTS_LOCK:
                _ACTIVE_ROOTS.discard(self._registry_key)
            self._registry_key = None
        self._closed = True
        if failed:
            raise ArtifactRollbackError


def _require_real_ancestors(path: Path) -> None:
    for ancestor in path.parents:
        info = os.lstat(ancestor)
        if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
            raise ArtifactPublicationError


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _windows_reparse_attribute() -> int:
    return 0x400


def _windows_file_index(identity: tuple[int, int, int, int]) -> int:
    return (identity[1] << 32) | identity[2]


def _open_windows_directory_handle(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
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
        0x40000000 | 0x0001,
        0x1 | 0x2,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if value is None or value == invalid:
        raise ArtifactPublicationError
    return int(value)


def _flush_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
    function = win_dll("kernel32", use_last_error=True).FlushFileBuffers
    function.argtypes = (wintypes.HANDLE,)
    function.restype = wintypes.BOOL
    if not function(wintypes.HANDLE(handle)):
        raise ArtifactPublicationError


def _windows_handle_identity(handle: int) -> tuple[int, int, int, int]:
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
    win_dll = getattr(ctypes, "WinDLL")
    function = win_dll(
        "kernel32", use_last_error=True
    ).GetFileInformationByHandle
    function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation))
    function.restype = wintypes.BOOL
    if not function(wintypes.HANDLE(handle), ctypes.byref(info)):
        raise ArtifactPublicationError
    return (
        int(info.volume_serial),
        int(info.file_index_high),
        int(info.file_index_low),
        int(info.attributes),
    )


def _close_windows_handle(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
    function = win_dll("kernel32", use_last_error=True).CloseHandle
    function.argtypes = (wintypes.HANDLE,)
    function.restype = wintypes.BOOL
    return bool(function(wintypes.HANDLE(handle)))
