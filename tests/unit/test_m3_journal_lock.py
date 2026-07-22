"""Crash-safe journal writer lock unit tests (Linux flock / Windows msvcrt)."""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
import textwrap
import time
import traceback
from pathlib import Path

import pytest

import quant.data._journal_lock as journal_lock
import quant.data.m3_backfill as backfill
import quant.data.m3_reference as ref
from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.m3_backfill import M3BackfillError, execute_tushare_batch
from quant.data.storage import RawStore

from tests.unit.test_m3_backfill_requests import FakeConnector, _execute, _weight_batch

_IS_WIN32 = sys.platform == "win32"
_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

def _fds() -> set[int]:
    if _IS_WIN32:
        return set()
    fd_dir = Path("/proc/self/fd")
    result: set[int] = set()
    for entry in fd_dir.iterdir():
        try:
            result.add(int(entry.name))
        except ValueError:
            continue
    return result


def _force_kill(child: subprocess.Popen[bytes]) -> None:
    child.kill()
    child.wait(timeout=5)


def _patch_unlock_failure(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    if _IS_WIN32:
        real = journal_lock.msvcrt.locking

        def broken(fd: int, mode: int, nbytes: int) -> None:
            if mode == journal_lock.msvcrt.LK_UNLCK:
                raise OSError(errno.EBADF, message)
            real(fd, mode, nbytes)

        monkeypatch.setattr(journal_lock.msvcrt, "locking", broken)
    else:
        real = journal_lock.fcntl.flock

        def broken(fd: int, operation: int) -> None:
            if operation == journal_lock.fcntl.LOCK_UN:
                raise OSError(errno.EBADF, message)
            real(fd, operation)

        monkeypatch.setattr(journal_lock.fcntl, "flock", broken)


def _try_symlink(link: Path, target: Path, *, target_is_directory: bool = False) -> bool:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
        return True
    except OSError:
        return False


def _make_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_nested_acquire_is_active_then_reacquire_after_release(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    with hold_journal_writer_lock(journal_root=root):
        with pytest.raises(M3JournalLockError, match="JOURNAL_WRITER_ACTIVE") as nested:
            with hold_journal_writer_lock(journal_root=root):
                raise AssertionError("nested acquire must not succeed")
        assert nested.value.code == "JOURNAL_WRITER_ACTIVE"
        assert str(nested.value) == "JOURNAL_WRITER_ACTIVE"
        assert "journal" not in repr(nested.value)
    with hold_journal_writer_lock(journal_root=root):
        pass
    lock_path = root / ".writer.lock"
    assert lock_path.is_file()
    assert not lock_path.is_symlink()
    assert os.lstat(lock_path).st_nlink == 1


def test_child_process_hold_blocks_and_kill_recovers(tmp_path: Path) -> None:
    root = (tmp_path / "journal").resolve()
    root.mkdir()
    ready = tmp_path / "ready"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(_SRC_ROOT)!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        root = Path({str(root)!r})
        with hold_journal_writer_lock(journal_root=root):
            Path({str(ready)!r}).write_text("1", encoding="utf-8")
            time.sleep(60)
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(400):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(M3JournalLockError, match="JOURNAL_WRITER_ACTIVE"):
            with hold_journal_writer_lock(journal_root=root):
                pass
        _force_kill(child)
        with hold_journal_writer_lock(journal_root=root):
            pass
    finally:
        if child.poll() is None:
            _force_kill(child)


def test_child_normal_exit_releases_immediately(tmp_path: Path) -> None:
    root = (tmp_path / "journal").resolve()
    root.mkdir()
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(_SRC_ROOT)!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        with hold_journal_writer_lock(journal_root=Path({str(root)!r})):
            pass
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    with hold_journal_writer_lock(journal_root=root):
        pass


def test_stale_nonempty_lock_file_is_acquirable_without_reading(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    lock_path = root / ".writer.lock"
    secret = "token-STALE-LOCK-SECRET"
    lock_path.write_text(secret, encoding="utf-8")
    before = lock_path.read_bytes()

    def forbid_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("lock content must not be read or trusted")

    original = Path.read_bytes
    try:
        Path.read_bytes = forbid_read  # type: ignore[method-assign]
        with hold_journal_writer_lock(journal_root=root):
            pass
    finally:
        Path.read_bytes = original  # type: ignore[method-assign]
    assert lock_path.read_bytes() == before


@pytest.mark.parametrize(
    "kind",
    ["hardlink", "directory"]
    + ([] if _IS_WIN32 else ["symlink", "fifo"]),
)
def test_invalid_lock_file_kinds_are_rejected(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    lock_path = root / ".writer.lock"
    other = tmp_path / "other"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        if not _try_symlink(lock_path, target):
            pytest.skip("symlink privilege unavailable")
    elif kind == "hardlink":
        other.write_text("x", encoding="utf-8")
        os.link(other, lock_path)
    elif kind == "directory":
        lock_path.mkdir()
    else:
        os.mkfifo(lock_path)
    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=root):
            pass
    assert caught.value.code == "JOURNAL_LOCK_FILE_INVALID"
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(tmp_path) not in rendered
    assert caught.value.__cause__ is None


def test_root_and_ancestor_symlinks_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    if _IS_WIN32:
        _make_junction(linked, real)
    else:
        if not _try_symlink(linked, real, target_is_directory=True):
            pytest.skip("symlink privilege unavailable")
    with pytest.raises(M3JournalLockError) as root_err:
        with hold_journal_writer_lock(journal_root=linked):
            pass
    assert root_err.value.code == "JOURNAL_LOCK_ROOT_INVALID"

    parent_real = tmp_path / "parent-real"
    parent_real.mkdir()
    parent_link = tmp_path / "parent-link"
    if _IS_WIN32:
        _make_junction(parent_link, parent_real)
    else:
        if not _try_symlink(parent_link, parent_real, target_is_directory=True):
            pytest.skip("symlink privilege unavailable")
    nested = parent_link / "journal"
    nested.mkdir()
    with pytest.raises(M3JournalLockError) as anc_err:
        with hold_journal_writer_lock(journal_root=nested):
            pass
    assert anc_err.value.code == "JOURNAL_LOCK_ROOT_INVALID"


@pytest.mark.skipif(not _IS_WIN32, reason="Windows junction ancestor counterexample")
def test_windows_junction_ancestor_and_lock_hardlink_fail_closed(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    junc_parent = tmp_path / "junc-parent"
    _make_junction(junc_parent, real_parent)
    journal = junc_parent / "journal"
    journal.mkdir()
    with pytest.raises(M3JournalLockError) as anc:
        with hold_journal_writer_lock(journal_root=journal):
            pass
    assert anc.value.code == "JOURNAL_LOCK_ROOT_INVALID"

    root = tmp_path / "journal-hl"
    root.mkdir()
    other = tmp_path / "other-hl"
    other.write_bytes(b"x")
    os.link(other, root / ".writer.lock")
    with pytest.raises(M3JournalLockError) as hl:
        with hold_journal_writer_lock(journal_root=root):
            pass
    assert hl.value.code == "JOURNAL_LOCK_FILE_INVALID"


def test_lock_inode_replace_before_yield_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    real_apply = journal_lock._apply_exclusive_lock
    real_validate = journal_lock._validate_lock_fd

    if _IS_WIN32:
        # Windows cannot unlink an open locked file; simulate entry identity drift
        # immediately after the exclusive lock is applied.
        def replace_then_lock(fd: int) -> None:
            real_apply(fd)

            def drifted(**kwargs):
                identity = real_validate(**kwargs)
                return (identity[0], identity[1] ^ 0xFFFFFFFF)

            monkeypatch.setattr(journal_lock, "_validate_lock_fd", drifted)

        monkeypatch.setattr(journal_lock, "_apply_exclusive_lock", replace_then_lock)
    else:

        def replace_then_lock(fd: int) -> None:
            real_apply(fd)
            lock_path = root / ".writer.lock"
            os.unlink(lock_path)
            new_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
            os.close(new_fd)

        monkeypatch.setattr(journal_lock, "_apply_exclusive_lock", replace_then_lock)

    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=root):
            pass
    assert caught.value.code == "JOURNAL_LOCK_FILE_INVALID"


def test_root_inode_replace_before_yield_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    real_snapshot = journal_lock._snapshot_root_identities
    calls = {"n": 0}

    def snapshot_with_post_lock_drift(path: Path):
        ancestors, identity = real_snapshot(path)
        calls["n"] += 1
        if calls["n"] >= 2:
            drifted = (identity[0], identity[1] ^ 0xFFFFFFFF)
            ancestors = dict(ancestors)
            ancestors[path] = drifted
            return ancestors, drifted
        return ancestors, identity

    monkeypatch.setattr(journal_lock, "_snapshot_root_identities", snapshot_with_post_lock_drift)
    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=root):
            pass
    assert caught.value.code == "JOURNAL_LOCK_ROOT_INVALID"
    assert calls["n"] >= 2


def test_directory_entry_replace_while_held_reports_release_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=root):
            if _IS_WIN32:
                # Open locked files cannot be unlinked on Windows; force release-time
                # identity failure that must map to JOURNAL_LOCK_RELEASE_FAILED.
                def boom(**_kwargs):
                    raise M3JournalLockError("JOURNAL_LOCK_FILE_INVALID")

                monkeypatch.setattr(journal_lock, "_validate_lock_fd", boom)
            else:
                lock_path = root / ".writer.lock"
                os.unlink(lock_path)
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
                os.close(fd)
    assert caught.value.code == "JOURNAL_LOCK_RELEASE_FAILED"


def test_primary_body_exception_outranks_release_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    before = _fds()
    _patch_unlock_failure(monkeypatch, "token-UNLOCK-SECRET /private/lock")
    with pytest.raises(RuntimeError, match="primary-body"):
        with hold_journal_writer_lock(journal_root=root):
            raise RuntimeError("primary-body")
    if not _IS_WIN32:
        leaked = _fds() - before
        assert not leaked


def test_release_failure_visible_without_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    before = _fds()
    _patch_unlock_failure(monkeypatch, "token-UNLOCK-SECRET /private/lock")
    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=root):
            pass
    assert caught.value.code == "JOURNAL_LOCK_RELEASE_FAILED"
    rendered = "".join(traceback.format_exception(caught.value))
    assert "token-UNLOCK-SECRET" not in rendered
    assert "/private/lock" not in rendered
    assert caught.value.__cause__ is None
    if not _IS_WIN32:
        leaked = _fds() - before
        assert not leaked


def test_relative_and_missing_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(M3JournalLockError) as relative:
        with hold_journal_writer_lock(journal_root=Path("relative-journal")):
            pass
    assert relative.value.code == "JOURNAL_LOCK_INPUT_INVALID"
    missing = tmp_path / "missing"
    with pytest.raises(M3JournalLockError) as absent:
        with hold_journal_writer_lock(journal_root=missing):
            pass
    assert absent.value.code == "JOURNAL_LOCK_ROOT_INVALID"


def test_production_paths_have_no_excl_unlink_pid_mtime_or_sleep() -> None:
    lock_src = Path(journal_lock.__file__).read_text(encoding="utf-8")
    backfill_src = Path(backfill.__file__).read_text(encoding="utf-8")
    reference_src = Path(ref.__file__).read_text(encoding="utf-8")
    assert "O_EXCL" not in lock_src
    assert "unlink" not in lock_src
    assert "os.getpid" not in lock_src
    assert "mtime" not in lock_src.lower()
    assert "time.sleep" not in lock_src
    assert "win32file" not in lock_src
    assert "win32file" not in backfill_src
    assert "win32file" not in reference_src
    # msvcrt is Windows-only backend inside the lock module; executors must not import it.
    assert "msvcrt" not in backfill_src
    assert "msvcrt" not in reference_src
    assert "import msvcrt" in lock_src
    assert 'sys.platform == "win32"' in lock_src
    assert "O_EXCL" not in backfill_src
    assert "O_EXCL" not in reference_src
    assert "lock_path.unlink" not in backfill_src
    assert "lock_path.unlink" not in reference_src


def test_tushare_executor_stale_lock_and_repeat_run(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    lock_path = journal / ".writer.lock"
    lock_path.write_text("stale-but-ignored", encoding="utf-8")
    first = _execute(tmp_path, FakeConnector())
    assert lock_path.exists()
    assert stat.S_ISREG(os.lstat(lock_path).st_mode)
    second = _execute(tmp_path, FakeConnector())
    assert [item.request_id for item in first] == [item.request_id for item in second]
    for item in first:
        left = (journal / item.request_id / "receipt.json").read_bytes()
        right = (journal / item.request_id / "receipt.json").read_bytes()
        assert left == right


def test_tushare_executor_kill_recovery(tmp_path: Path) -> None:
    journal = (tmp_path / "journal").resolve()
    journal.mkdir()
    ready = tmp_path / "ready"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(_SRC_ROOT)!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        with hold_journal_writer_lock(journal_root=Path({str(journal)!r})):
            Path({str(ready)!r}).write_text("1", encoding="utf-8")
            time.sleep(60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(400):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists()
        connector = FakeConnector()
        with pytest.raises(M3BackfillError, match="JOURNAL_WRITER_ACTIVE"):
            _execute(tmp_path, connector)
        assert connector.calls == []
        _force_kill(child)
        receipts = _execute(tmp_path, FakeConnector())
        assert receipts
        assert (journal / ".writer.lock").exists()
    finally:
        if child.poll() is None:
            _force_kill(child)


def test_tushare_executor_concurrent_helper_hold(tmp_path: Path) -> None:
    from quant.data.m3_backfill import ENDPOINT_POLICIES_V1

    journal = (tmp_path / "journal").resolve()
    journal.mkdir()
    with hold_journal_writer_lock(journal_root=journal):
        connector = FakeConnector()
        with pytest.raises(M3BackfillError, match="JOURNAL_WRITER_ACTIVE"):
            execute_tushare_batch(
                batch=_weight_batch(),
                connector=connector,  # type: ignore[arg-type]
                raw_store=RawStore(tmp_path / "raw"),
                journal_root=journal,
                endpoint_policies=ENDPOINT_POLICIES_V1,
                request_rate_per_minute=60,
                max_attempts=1,
                retry_base_seconds=1.0,
                classify_error=lambda _: "UNKNOWN",
            )
        assert connector.calls == []


@pytest.mark.skipif(not _IS_WIN32, reason="Windows same-process second-handle counterexample")
def test_windows_same_process_second_handle_and_subprocess_blocked(tmp_path: Path) -> None:
    root = (tmp_path / "journal").resolve()
    root.mkdir()
    held = journal_lock._acquire_journal_writer_lock(journal_root=root)
    try:
        with pytest.raises(M3JournalLockError) as second:
            journal_lock._acquire_journal_writer_lock(journal_root=root)
        assert second.value.code == "JOURNAL_WRITER_ACTIVE"

        script = textwrap.dedent(
            f"""
            import sys
            from pathlib import Path
            sys.path.insert(0, {str(_SRC_ROOT)!r})
            from quant.data._journal_lock import hold_journal_writer_lock, M3JournalLockError
            try:
                with hold_journal_writer_lock(journal_root=Path({str(root)!r})):
                    raise SystemExit(2)
            except M3JournalLockError as exc:
                raise SystemExit(0 if exc.code == "JOURNAL_WRITER_ACTIVE" else 3)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
    finally:
        err = journal_lock._release_journal_writer_lock(held)
        assert err is None


@pytest.mark.skipif(not _IS_WIN32, reason="Windows forced-termination recovery counterexample")
def test_windows_holder_terminated_then_fresh_acquire(tmp_path: Path) -> None:
    root = (tmp_path / "journal").resolve()
    root.mkdir()
    ready = tmp_path / "ready"
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(_SRC_ROOT)!r})
        from quant.data._journal_lock import hold_journal_writer_lock
        with hold_journal_writer_lock(journal_root=Path({str(root)!r})):
            Path({str(ready)!r}).write_text("1", encoding="utf-8")
            time.sleep(60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(400):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(M3JournalLockError) as blocked:
            with hold_journal_writer_lock(journal_root=root):
                pass
        assert blocked.value.code == "JOURNAL_WRITER_ACTIVE"
        _force_kill(child)
        with hold_journal_writer_lock(journal_root=root):
            pass
        assert (root / ".writer.lock").is_file()
    finally:
        if child.poll() is None:
            _force_kill(child)


def test_missing_isjunction_plain_root_still_acquires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python <3.12 may lack os.path.isjunction; must not leak AttributeError."""
    root = (tmp_path / "journal").resolve()
    root.mkdir()
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    with hold_journal_writer_lock(journal_root=root):
        assert (root / ".writer.lock").is_file()
    with hold_journal_writer_lock(journal_root=root):
        pass


@pytest.mark.skipif(not _IS_WIN32, reason="Windows reparse fail-closed without isjunction")
def test_missing_isjunction_reparse_still_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """st_file_attributes reparse bit must still reject junctions when isjunction is absent."""
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    junc_parent = tmp_path / "junc_parent"
    _make_junction(junc_parent, real_parent)
    journal = junc_parent / "journal"
    journal.mkdir()
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    with pytest.raises(M3JournalLockError) as caught:
        with hold_journal_writer_lock(journal_root=journal):
            pass
    assert caught.value.code == "JOURNAL_LOCK_ROOT_INVALID"
