"""Crash-safe journal writer lock for M3 (Linux flock / Windows msvcrt).

Lock files are persistent; only kernel advisory ownership indicates an active
writer. The kernel releases the lock on process exit, including forced kill.
Linux and Windows backends share the public context manager and stable codes;
filesystem primitives are not claimed to be equivalent across platforms.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

if sys.platform == "win32":
    import msvcrt  # noqa: F401 — used on Windows backend
else:
    import fcntl  # noqa: F401 — test monkeypatch surface

_LockCode = Literal[
    "JOURNAL_LOCK_INPUT_INVALID",
    "JOURNAL_LOCK_ROOT_INVALID",
    "JOURNAL_LOCK_FILE_INVALID",
    "JOURNAL_WRITER_ACTIVE",
    "JOURNAL_LOCK_IO_FAILED",
    "JOURNAL_LOCK_RELEASE_FAILED",
]

_LOCK_NAME = ".writer.lock"
_Identity = tuple[int, int]
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_IS_WIN32 = sys.platform == "win32"


class M3JournalLockError(ValueError):
    """Stable, sanitized journal writer-lock failure; ``str(error)`` equals ``code``."""

    def __init__(self, code: _LockCode) -> None:
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3JournalLockError({self.code!r})"


@contextmanager
def hold_journal_writer_lock(*, journal_root: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``journal_root / .writer.lock``."""
    held = _acquire_journal_writer_lock(journal_root=journal_root)
    try:
        yield
    finally:
        has_primary = sys.exc_info()[0] is not None
        release_error = _release_journal_writer_lock(held)
        if release_error is not None and not has_primary:
            raise release_error from None


class _HeldJournalLock:
    __slots__ = (
        "dir_fd",
        "lock_fd",
        "root",
        "lock_path",
        "root_identity",
        "ancestor_identities",
        "lock_identity",
    )

    def __init__(
        self,
        *,
        dir_fd: int,
        lock_fd: int,
        root: Path,
        lock_path: Path,
        root_identity: _Identity,
        ancestor_identities: dict[Path, _Identity],
        lock_identity: _Identity,
    ) -> None:
        self.dir_fd = dir_fd
        self.lock_fd = lock_fd
        self.root = root
        self.lock_path = lock_path
        self.root_identity = root_identity
        self.ancestor_identities = ancestor_identities
        self.lock_identity = lock_identity


def _acquire_journal_writer_lock(*, journal_root: Path) -> _HeldJournalLock:
    if not isinstance(journal_root, Path):
        raise M3JournalLockError("JOURNAL_LOCK_INPUT_INVALID")
    if not journal_root.is_absolute():
        raise M3JournalLockError("JOURNAL_LOCK_INPUT_INVALID")

    if _IS_WIN32:
        return _acquire_journal_writer_lock_win32(journal_root=journal_root)
    return _acquire_journal_writer_lock_posix(journal_root=journal_root)


def _acquire_journal_writer_lock_posix(*, journal_root: Path) -> _HeldJournalLock:
    ancestor_identities, root_identity = _snapshot_root_identities(journal_root)
    dir_fd = -1
    lock_fd = -1
    try:
        try:
            dir_fd = os.open(
                journal_root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY")
                | getattr(os, "O_CLOEXEC")
                | getattr(os, "O_NOFOLLOW"),
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}:
                raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID") from None
            raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
        _assert_fd_identity(dir_fd, root_identity, "JOURNAL_LOCK_ROOT_INVALID")

        try:
            lock_fd = os.open(
                _LOCK_NAME,
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_CLOEXEC")
                | getattr(os, "O_NOFOLLOW"),
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID") from None
            raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None

        lock_path = journal_root / _LOCK_NAME
        lock_identity = _validate_lock_fd(dir_fd=dir_fd, lock_fd=lock_fd, lock_path=lock_path)
        _apply_exclusive_lock(lock_fd)
        _revalidate_after_acquire(
            root=journal_root,
            dir_fd=dir_fd,
            lock_fd=lock_fd,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity,
        )
        held = _HeldJournalLock(
            dir_fd=dir_fd,
            lock_fd=lock_fd,
            root=journal_root,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity,
        )
        dir_fd = -1
        lock_fd = -1
        return held
    except M3JournalLockError:
        _best_effort_close(lock_fd)
        _best_effort_close(dir_fd)
        raise
    except Exception:
        _best_effort_close(lock_fd)
        _best_effort_close(dir_fd)
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None


def _acquire_journal_writer_lock_win32(*, journal_root: Path) -> _HeldJournalLock:
    ancestor_identities, root_identity = _snapshot_root_identities(journal_root)
    lock_path = journal_root / _LOCK_NAME
    lock_fd = -1
    try:
        _reject_reparse_path(lock_path, missing_ok=True, code="JOURNAL_LOCK_FILE_INVALID")
        try:
            lock_fd = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except OSError as exc:
            if _path_is_plain_dir(lock_path):
                raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID") from None
            if exc.errno in {errno.EISDIR}:
                raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID") from None
            raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None

        _ensure_lock_byte(lock_fd)
        lock_identity = _validate_lock_fd(dir_fd=-1, lock_fd=lock_fd, lock_path=lock_path)
        _apply_exclusive_lock(lock_fd)
        _revalidate_after_acquire(
            root=journal_root,
            dir_fd=-1,
            lock_fd=lock_fd,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity,
        )
        held = _HeldJournalLock(
            dir_fd=-1,
            lock_fd=lock_fd,
            root=journal_root,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity,
        )
        lock_fd = -1
        return held
    except M3JournalLockError:
        _best_effort_close(lock_fd)
        raise
    except Exception:
        _best_effort_close(lock_fd)
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None


def _release_journal_writer_lock(held: _HeldJournalLock) -> M3JournalLockError | None:
    release_error: M3JournalLockError | None = None
    try:
        _revalidate_for_release(held)
        try:
            _release_exclusive_lock(held.lock_fd)
        except OSError:
            release_error = M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")
    except M3JournalLockError as exc:
        release_error = exc
    except Exception:
        release_error = M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")

    if not _best_effort_close(held.lock_fd) and release_error is None:
        release_error = M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")
    held.lock_fd = -1
    if held.dir_fd >= 0:
        if not _best_effort_close(held.dir_fd) and release_error is None:
            release_error = M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")
    held.dir_fd = -1
    return release_error


def _apply_exclusive_lock(lock_fd: int) -> None:
    if _IS_WIN32:
        try:
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)  # type: ignore[name-defined]
        except OSError as exc:
            if exc.errno in {
                errno.EACCES,
                errno.EAGAIN,
                getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
            }:
                raise M3JournalLockError("JOURNAL_WRITER_ACTIVE") from None
            raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
        return
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[name-defined, attr-defined]
    except OSError as exc:
        if exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
        }:
            raise M3JournalLockError("JOURNAL_WRITER_ACTIVE") from None
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None


def _release_exclusive_lock(lock_fd: int) -> None:
    if _IS_WIN32:
        os.lseek(lock_fd, 0, os.SEEK_SET)
        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)  # type: ignore[name-defined]
        return
    fcntl.flock(lock_fd, fcntl.LOCK_UN)  # type: ignore[name-defined, attr-defined]


def _ensure_lock_byte(lock_fd: int) -> None:
    try:
        size = os.fstat(lock_fd).st_size
    except OSError:
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if size >= 1:
        return
    try:
        os.lseek(lock_fd, 0, os.SEEK_SET)
        os.write(lock_fd, b"\0")
    except OSError:
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None


def _snapshot_root_identities(root: Path) -> tuple[dict[Path, _Identity], _Identity]:
    identities: dict[Path, _Identity] = {}
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID") from None
    except OSError:
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if _is_reparse_stat(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID")
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    identities[root] = root_identity

    for path in root.parents:
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID") from None
        except OSError:
            raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
        if _is_reparse_stat(path, path_stat):
            raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID")
        if not stat.S_ISDIR(path_stat.st_mode):
            raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID")
        identities[path] = (path_stat.st_dev, path_stat.st_ino)
    return identities, root_identity


def _is_reparse_stat(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    # Python 3.12+; feature-detect so requires-python >=3.10 does not leak AttributeError.
    isjunction = getattr(os.path, "isjunction", None)
    if callable(isjunction) and isjunction(path):
        return True
    attrs = getattr(path_stat, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_reparse_path(path: Path, *, missing_ok: bool, code: _LockCode) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return
        raise M3JournalLockError(code) from None
    except OSError:
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if _is_reparse_stat(path, path_stat):
        raise M3JournalLockError(code)


def _path_is_plain_dir(path: Path) -> bool:
    try:
        path_stat = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(path_stat.st_mode) and not _is_reparse_stat(path, path_stat)


def _validate_lock_fd(*, dir_fd: int, lock_fd: int, lock_path: Path) -> _Identity:
    try:
        fd_stat = os.fstat(lock_fd)
    except OSError:
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if not stat.S_ISREG(fd_stat.st_mode) or fd_stat.st_nlink != 1:
        raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")
    try:
        if dir_fd >= 0:
            entry_stat = os.stat(_LOCK_NAME, dir_fd=dir_fd, follow_symlinks=False)
        else:
            entry_stat = os.lstat(lock_path)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ELOOP, errno.ENOTDIR}:
            raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID") from None
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if dir_fd < 0 and _is_reparse_stat(lock_path, entry_stat):
        raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")
    if not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1:
        raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")
    if (entry_stat.st_dev, entry_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
        raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")
    return (fd_stat.st_dev, fd_stat.st_ino)


def _revalidate_after_acquire(
    *,
    root: Path,
    dir_fd: int,
    lock_fd: int,
    lock_path: Path,
    root_identity: _Identity,
    ancestor_identities: dict[Path, _Identity],
    lock_identity: _Identity,
) -> None:
    current_ancestors, current_root = _snapshot_root_identities(root)
    if current_root != root_identity:
        raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID")
    if current_ancestors != ancestor_identities:
        raise M3JournalLockError("JOURNAL_LOCK_ROOT_INVALID")
    if dir_fd >= 0:
        _assert_fd_identity(dir_fd, root_identity, "JOURNAL_LOCK_ROOT_INVALID")
    current_lock = _validate_lock_fd(dir_fd=dir_fd, lock_fd=lock_fd, lock_path=lock_path)
    if current_lock != lock_identity:
        raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")


def _revalidate_for_release(held: _HeldJournalLock) -> None:
    try:
        current_ancestors, current_root = _snapshot_root_identities(held.root)
        if current_root != held.root_identity or current_ancestors != held.ancestor_identities:
            raise M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")
        if held.dir_fd >= 0:
            _assert_fd_identity(held.dir_fd, held.root_identity, "JOURNAL_LOCK_RELEASE_FAILED")
        current_lock = _validate_lock_fd(
            dir_fd=held.dir_fd, lock_fd=held.lock_fd, lock_path=held.lock_path
        )
        if current_lock != held.lock_identity:
            raise M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED")
    except M3JournalLockError as exc:
        if exc.code == "JOURNAL_LOCK_RELEASE_FAILED":
            raise
        raise M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED") from None


def _assert_fd_identity(fd: int, expected: _Identity, code: _LockCode) -> None:
    try:
        current = os.fstat(fd)
    except OSError:
        if code == "JOURNAL_LOCK_RELEASE_FAILED":
            raise M3JournalLockError("JOURNAL_LOCK_RELEASE_FAILED") from None
        raise M3JournalLockError("JOURNAL_LOCK_IO_FAILED") from None
    if (current.st_dev, current.st_ino) != expected:
        raise M3JournalLockError(code)


def _best_effort_close(fd: int) -> bool:
    if fd < 0:
        return True
    try:
        os.close(fd)
        return True
    except OSError:
        return False
