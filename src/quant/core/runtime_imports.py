"""Append imported ``quant.*`` module names at quant CLI process exit.

The output is intentionally limited to module names. ``QUANT_RUNTIME_IMPORTS_ROOT``
can redirect it to an isolated directory for tests and local verification.
"""

from __future__ import annotations

import atexit
import errno
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

_RUNTIME_ROOT_ENV = "QUANT_RUNTIME_IMPORTS_ROOT"
_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
_LOCK_NAME = ".runtime_imports.lock"
_LOCK_WAIT_SECONDS = 0.25
_LOGGER_REGISTERED = False


def _project_root() -> Path:
    configured_root = os.environ.get("QUANT_PROJECT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd().resolve()


def _runtime_imports_root() -> Path:
    override = os.environ.get(_RUNTIME_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()

    project_root = _project_root()
    artifacts_root = Path(os.environ.get("QUANT_ARTIFACTS_ROOT", "artifacts"))
    if not artifacts_root.is_absolute():
        artifacts_root = project_root / artifacts_root
    return artifacts_root / "runtime_imports"


@contextmanager
def _cross_process_lock(path: Path) -> Iterator[None]:
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)

        if os.name == "nt":
            import msvcrt

            def lock() -> None:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock() -> None:
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

            retryable_errors = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while True:
                try:
                    lock()
                    break
                except OSError as exc:
                    if exc.errno not in retryable_errors:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out acquiring runtime imports lock") from exc
                    time.sleep(min(0.01, remaining))
            try:
                yield
            finally:
                stream.seek(0)
                unlock()
        else:
            import fcntl

            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out acquiring runtime imports lock") from exc
                    time.sleep(min(0.01, remaining))
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append_imported_modules() -> Path | None:
    """Append this process's imported dotted ``quant.*`` names to its date file."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(_RUNTIME_ROOT_ENV):
        return None

    names = sorted({name for name in tuple(sys.modules) if name.startswith("quant.")})
    if not names:
        return None

    output_root = _runtime_imports_root()
    output_root.mkdir(parents=True, exist_ok=True)
    date = datetime.now(_SHANGHAI).date().isoformat()
    output_path = output_root / f"{date}.txt"
    lock_path = output_root / _LOCK_NAME

    with _cross_process_lock(lock_path):
        with output_path.open("a", encoding="utf-8", newline="\n") as output:
            output.write("".join(f"{name}\n" for name in names))
            output.flush()
    return output_path


def _append_at_exit() -> None:
    try:
        append_imported_modules()
    except BaseException:
        # Failure to write evidence must never change the command's exit result.
        pass


def register_runtime_import_logger() -> None:
    """Register the fail-safe process-exit recorder once."""
    global _LOGGER_REGISTERED
    if _LOGGER_REGISTERED:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(_RUNTIME_ROOT_ENV):
        return

    _LOGGER_REGISTERED = True
    try:
        atexit.register(_append_at_exit)
    except BaseException:
        pass
