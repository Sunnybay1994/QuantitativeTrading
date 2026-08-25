"""STATIC_ONLY unit contracts for session barrier substrate (M4-B1A).

UA-M4-006 remains OPEN. No formal composition / PAPER / soak claims.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import os
import pickle
import sqlite3
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import pytest

from quant.execution.migrations.v009_session_barrier import upgrade as upgrade_v009
from quant.execution.session_barrier import (
    SessionBarrierCapability,
    SessionBarrierError,
    SessionBarrierOmsHandle,
    SessionBarrierWriteLease,
    build_session_barrier_capability,
    compute_close_token_identity,
    fresh_read_session_barrier,
    hold_open_write_lease,
    hold_session_barrier_lock,
    initialize_open_barrier,
    invalidate_session_barrier_oms_handle,
    invalidate_write_lease,
    issue_session_barrier_oms_handle,
    read_session_barrier,
    transition_closing_to_closed,
    transition_open_to_closing,
    unpack_open_write_lease,
    unpack_session_barrier_capability,
    unpack_session_barrier_oms_handle,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 25, 1, 2, 3, 456789, tzinfo=UTC)


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _capability(tmp_path: Path, **overrides: object) -> SessionBarrierCapability:
    root = tmp_path / "barrier-lock-root"
    root.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "barrier_epoch": _hex("epoch"),
        "session_date": dt.date(2026, 8, 25),
        "account_identity": _hex("account"),
        "oms_store_identity": _hex("oms"),
        "broker_store_identity": _hex("broker"),
        "gateway_identity": _hex("gateway"),
        "config_identity": _hex("config"),
        "lock_root": root,
    }
    kwargs.update(overrides)
    return build_session_barrier_capability(**kwargs)  # type: ignore[arg-type]


def _oms_conn(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "oms.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        CREATE TABLE schema_version (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            version INTEGER NOT NULL,
            status TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    upgrade_v009(conn)
    conn.execute(
        "INSERT INTO schema_version VALUES (1, 9, 'ready', '2026-08-25T00:00:00.000000Z')"
    )
    conn.execute("COMMIT")
    return conn


def test_capability_factory_rejects_fakes_and_hides_paths(tmp_path: Path) -> None:
    cap = _capability(tmp_path)
    assert "barrier-lock-root" not in repr(cap)
    assert unpack_session_barrier_capability(cap) is cap
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(True)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability({"capability_identity": cap.capability_identity})


def test_protocol_subclass_object_new_and_replace_capability_rejected(
    tmp_path: Path,
) -> None:
    class CapProto(Protocol):
        capability_identity: str

    @dataclass(frozen=True, slots=True)
    class Fake:
        capability_identity: str

    with pytest.raises(SessionBarrierError):
        unpack_session_barrier_capability(Fake(capability_identity=_hex("x")))

    forged = object.__new__(SessionBarrierCapability)
    for name, value in (
        ("barrier_epoch", _hex("epoch")),
        ("session_date", "2026-08-25"),
        ("account_identity", _hex("account")),
        ("oms_store_identity", _hex("oms")),
        ("broker_store_identity", _hex("broker")),
        ("gateway_identity", _hex("gateway")),
        ("config_identity", _hex("config")),
        ("lock_root", tmp_path),
        ("capability_identity", _hex("cap")),
    ):
        object.__setattr__(forged, name, value)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(forged)

    cap = _capability(tmp_path)
    with pytest.raises(TypeError):
        copy.copy(cap)
    with pytest.raises(TypeError):
        copy.deepcopy(cap)
    with pytest.raises(TypeError):
        pickle.dumps(cap)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        replace(cap, session_date="2026-01-01")
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        SessionBarrierCapability()  # type: ignore[call-arg]


def test_open_closing_closed_transitions_and_token_conflicts(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    # initialize/transition own OS-lock → BEGIN → COMMIT/ROLLBACK → unlock.
    row = initialize_open_barrier(conn, cap, created_at=NOW)
    assert row.state == "OPEN"
    assert row.close_token_identity is None

    token_a = compute_close_token_identity(
        capability=cap, predecessor_state="OPEN", nonce="nonce-a"
    )
    closing, token = transition_open_to_closing(
        conn, cap, nonce="nonce-a", now=NOW + dt.timedelta(seconds=1)
    )
    assert token == token_a
    assert closing.state == "CLOSING"
    assert closing.close_token_identity == token_a

    # exact replay
    again, token2 = transition_open_to_closing(
        conn, cap, nonce="nonce-a", now=NOW + dt.timedelta(seconds=2)
    )
    assert again == closing and token2 == token_a

    # different token conflict
    with pytest.raises(SessionBarrierError, match="BARRIER_TOKEN_CONFLICT"):
        transition_open_to_closing(
            conn, cap, nonce="nonce-b", now=NOW + dt.timedelta(seconds=3)
        )

    # skip CLOSING：OPEN 上直接 closed → invalid
    skip_root = tmp_path / "skip"
    skip_root.mkdir()
    skip_cap = _capability(skip_root)
    fresh = _oms_conn(skip_root)
    initialize_open_barrier(fresh, skip_cap, created_at=NOW)
    with pytest.raises(SessionBarrierError, match="BARRIER_TRANSITION_INVALID"):
        transition_closing_to_closed(
            fresh,
            skip_cap,
            close_token_identity=_hex("nope"),
            now=NOW + dt.timedelta(seconds=3),
        )
    fresh.close()

    closed = transition_closing_to_closed(
        conn, cap, close_token_identity=token_a, now=NOW + dt.timedelta(seconds=4)
    )
    assert closed.state == "CLOSED"

    # reopen forbidden
    with pytest.raises(SessionBarrierError, match="BARRIER_TRANSITION_INVALID"):
        transition_open_to_closing(
            conn, cap, nonce="nonce-a", now=NOW + dt.timedelta(seconds=5)
        )

    # exact closed replay
    replay = transition_closing_to_closed(
        conn, cap, close_token_identity=token_a, now=NOW + dt.timedelta(seconds=6)
    )
    assert replay == closed


def test_old_root_with_economic_rows_refuses_open_init(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    conn.execute("CREATE TABLE commands (command_id TEXT PRIMARY KEY, payload BLOB)")
    conn.execute("INSERT INTO commands VALUES ('c1', X'00')")
    cap = _capability(tmp_path)
    with pytest.raises(SessionBarrierError, match="BARRIER_OLD_ROOT_REFUSED"):
        initialize_open_barrier(conn, cap, created_at=NOW)


def test_missing_extra_corrupt_barrier_rows_fail_closed(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    with pytest.raises(SessionBarrierError, match="BARRIER_MISSING"):
        read_session_barrier(conn)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    conn.execute(
        "UPDATE session_barrier SET row_identity = ? WHERE singleton = 1",
        (_hex("tampered-row-identity"),),
    )
    with pytest.raises(SessionBarrierError, match="BARRIER_ROW_CORRUPT"):
        read_session_barrier(conn)


def test_capability_rejects_copied_valid_proof_with_mutated_identity_fields(
    tmp_path: Path,
) -> None:
    base_kwargs = {
        "barrier_epoch": _hex("epoch"),
        "session_date": "2026-08-25",
        "account_identity": _hex("account"),
        "oms_store_identity": _hex("oms"),
        "broker_store_identity": _hex("broker"),
        "gateway_identity": _hex("gateway"),
        "config_identity": _hex("config"),
        "lock_root": (tmp_path / "barrier-lock-root"),
    }
    (tmp_path / "barrier-lock-root").mkdir(parents=True, exist_ok=True)
    mutants = (
        ("account_identity", _hex("mutated-account")),
        ("oms_store_identity", _hex("mutated-oms")),
        ("broker_store_identity", _hex("mutated-broker")),
        ("gateway_identity", _hex("mutated-gateway")),
        ("config_identity", _hex("mutated-config")),
        ("session_date", "2026-01-01"),
        ("barrier_epoch", _hex("mutated-epoch")),
    )
    for field_name, mutant in mutants:
        # Mutate fields on the exact minted object after registration.
        victim = build_session_barrier_capability(**base_kwargs)  # type: ignore[arg-type]
        object.__setattr__(victim, field_name, mutant)
        with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
            unpack_session_barrier_capability(victim)

        # Exact public-field clone of a still-valid capability is also rejected.
        genuine = build_session_barrier_capability(**base_kwargs)  # type: ignore[arg-type]
        clone = object.__new__(SessionBarrierCapability)
        for name in (
            "barrier_epoch",
            "session_date",
            "account_identity",
            "oms_store_identity",
            "broker_store_identity",
            "gateway_identity",
            "config_identity",
            "lock_root",
            "capability_identity",
        ):
            object.__setattr__(clone, name, getattr(genuine, name))
        assert clone != genuine
        with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
            unpack_session_barrier_capability(clone)
        assert unpack_session_barrier_capability(genuine) is genuine


def test_write_lease_lifecycle_and_forgery(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    handle = issue_session_barrier_oms_handle(capability=cap, conn=conn)
    initialize_open_barrier(conn, cap, created_at=NOW)

    with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms") as lease:
        assert unpack_open_write_lease(lease, capability=cap, store_kind="oms") is lease
        with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_STORE_MISMATCH"):
            unpack_open_write_lease(lease, capability=cap, store_kind="broker")

    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease(lease, capability=cap, store_kind="oms")

    with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms") as lease2:
        invalidate_write_lease(lease2)
        with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
            unpack_open_write_lease(lease2, capability=cap, store_kind="oms")

    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease(True, capability=cap, store_kind="oms")
    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease("raw-token", capability=cap, store_kind="oms")

    forged = object.__new__(SessionBarrierWriteLease)
    for name, value in (
        ("capability_identity", cap.capability_identity),
        ("barrier_epoch", cap.barrier_epoch),
        ("session_date", cap.session_date),
        ("state", "OPEN"),
        ("lock_identity", _hex("lock")),
        ("store_kind", "oms"),
        ("transaction_nonce", _hex("nonce")),
        ("owner_pid", os.getpid()),
        ("owner_thread_id", threading.get_ident()),
    ):
        object.__setattr__(forged, name, value)
    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease(forged, capability=cap, store_kind="oms")

    with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms") as live:
        with pytest.raises(TypeError):
            copy.copy(live)
        with pytest.raises(TypeError):
            copy.deepcopy(live)
        with pytest.raises(TypeError):
            pickle.dumps(live)
        with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
            replace(live, store_kind="broker")


def test_oms_handle_has_no_connection_escape_and_rejects_exact_clones(
    tmp_path: Path,
) -> None:
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    handle = issue_session_barrier_oms_handle(capability=cap, conn=conn)
    assert unpack_session_barrier_oms_handle(handle, capability=cap) is handle

    # Handed object: no connection / seal / proof / alive field or property escape.
    assert not hasattr(handle, "_conn")
    assert not hasattr(handle, "conn")
    assert not hasattr(handle, "_seal")
    assert not hasattr(handle, "_proof")
    assert not hasattr(handle, "_alive")
    assert not hasattr(type(handle), "_conn")
    assert not hasattr(type(handle), "conn")
    slots = getattr(type(handle), "__slots__", ())
    assert "_conn" not in slots
    assert "conn" not in slots
    with pytest.raises(AttributeError):
        getattr(handle, "_conn")
    with pytest.raises(TypeError):
        vars(handle)

    initialize_open_barrier(conn, cap, created_at=NOW)
    row = fresh_read_session_barrier(oms_handle=handle, capability=cap)
    assert row.state == "OPEN"

    clone = object.__new__(SessionBarrierOmsHandle)
    object.__setattr__(clone, "capability_identity", handle.capability_identity)
    object.__setattr__(clone, "handle_identity", handle.handle_identity)
    assert clone != handle
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        unpack_session_barrier_oms_handle(clone, capability=cap)
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        fresh_read_session_barrier(oms_handle=clone, capability=cap)
    invalidate_session_barrier_oms_handle(clone)
    assert unpack_session_barrier_oms_handle(handle, capability=cap) is handle
    assert fresh_read_session_barrier(oms_handle=handle, capability=cap).state == "OPEN"

    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        unpack_session_barrier_oms_handle(True, capability=cap)
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        unpack_session_barrier_oms_handle(lambda: conn, capability=cap)
    with pytest.raises(TypeError):
        copy.copy(handle)
    with pytest.raises(TypeError):
        pickle.dumps(handle)

    # Exact close lifecycle: invalidate removes registry binding; read fails.
    invalidate_session_barrier_oms_handle(handle)
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        unpack_session_barrier_oms_handle(handle, capability=cap)
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        fresh_read_session_barrier(oms_handle=handle, capability=cap)


def test_exact_object_new_clones_rejected_for_capability_handle_and_lease(
    tmp_path: Path,
) -> None:
    """Structurally equal clones must not retrieve or invalidate genuine bindings."""
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    handle = issue_session_barrier_oms_handle(capability=cap, conn=conn)
    initialize_open_barrier(conn, cap, created_at=NOW)

    cap_clone = object.__new__(SessionBarrierCapability)
    for name in (
        "barrier_epoch",
        "session_date",
        "account_identity",
        "oms_store_identity",
        "broker_store_identity",
        "gateway_identity",
        "config_identity",
        "lock_root",
        "capability_identity",
    ):
        object.__setattr__(cap_clone, name, getattr(cap, name))
    assert cap_clone is not cap
    assert cap_clone != cap  # identity keys: structural twins are not equal
    assert hash(cap_clone) != hash(cap)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(cap_clone)
    assert unpack_session_barrier_capability(cap) is cap

    handle_clone = object.__new__(SessionBarrierOmsHandle)
    object.__setattr__(handle_clone, "capability_identity", handle.capability_identity)
    object.__setattr__(handle_clone, "handle_identity", handle.handle_identity)
    assert handle_clone is not handle
    assert handle_clone != handle
    assert hash(handle_clone) != hash(handle)
    with pytest.raises(SessionBarrierError, match="BARRIER_OMS_HANDLE_INVALID"):
        unpack_session_barrier_oms_handle(handle_clone, capability=cap)
    # Clone invalidate must not pop the genuine handle binding / private conn.
    invalidate_session_barrier_oms_handle(handle_clone)
    assert unpack_session_barrier_oms_handle(handle, capability=cap) is handle
    assert fresh_read_session_barrier(oms_handle=handle, capability=cap).state == "OPEN"

    with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms") as lease:
        lease_clone = object.__new__(SessionBarrierWriteLease)
        for name in (
            "capability_identity",
            "barrier_epoch",
            "session_date",
            "state",
            "lock_identity",
            "store_kind",
            "transaction_nonce",
            "owner_pid",
            "owner_thread_id",
        ):
            object.__setattr__(lease_clone, name, getattr(lease, name))
        assert lease_clone is not lease
        assert lease_clone != lease
        assert hash(lease_clone) != hash(lease)
        with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
            unpack_open_write_lease(lease_clone, capability=cap, store_kind="oms")
        invalidate_write_lease(lease_clone)
        assert unpack_open_write_lease(lease, capability=cap, store_kind="oms") is lease

    # After context exit, genuine lease binding is gone; clone still fails.
    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease(lease, capability=cap, store_kind="oms")
    with pytest.raises(SessionBarrierError, match="BARRIER_LEASE_INVALID"):
        unpack_open_write_lease(lease_clone, capability=cap, store_kind="oms")


def test_closing_and_closed_reject_open_write_lease(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    handle = issue_session_barrier_oms_handle(capability=cap, conn=conn)
    initialize_open_barrier(conn, cap, created_at=NOW)
    token = transition_open_to_closing(conn, cap, nonce="n1", now=NOW)[1]
    with pytest.raises(SessionBarrierError, match="BARRIER_STATE_CLOSING"):
        with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms"):
            pass
    transition_closing_to_closed(conn, cap, close_token_identity=token, now=NOW)
    with pytest.raises(SessionBarrierError, match="BARRIER_STATE_CLOSED"):
        with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms"):
            pass


def test_concurrent_lock_serializes_writers(tmp_path: Path) -> None:
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    started = threading.Event()
    release = threading.Event()
    errors: list[str] = []

    def holder() -> None:
        try:
            with hold_session_barrier_lock(cap):
                started.set()
                release.wait(timeout=5)
        except SessionBarrierError as exc:
            errors.append(exc.code)

    thread = threading.Thread(target=holder)
    thread.start()
    assert started.wait(timeout=5)
    with pytest.raises(SessionBarrierError, match="BARRIER_WRITER_BUSY"):
        with hold_session_barrier_lock(cap):
            pass
    release.set()
    thread.join(timeout=5)
    assert errors == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink probe")
def test_lock_symlink_leaf_rejected(tmp_path: Path) -> None:
    cap = _capability(tmp_path)
    lock_root = cap.lock_root
    real = tmp_path / "real-lock-file"
    real.write_bytes(b"\0")
    link = lock_root / ".session-barrier.lock"
    link.symlink_to(real)
    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_FILE_INVALID",
        "BARRIER_LOCK_IO_FAILED",
        "BARRIER_LOCK_ROOT_INVALID",
    }


def test_close_token_binds_predecessor_session_epoch_nonce(tmp_path: Path) -> None:
    cap = _capability(tmp_path)
    a = compute_close_token_identity(
        capability=cap, predecessor_state="OPEN", nonce="same"
    )
    b = compute_close_token_identity(
        capability=cap, predecessor_state="CLOSING", nonce="same"
    )
    other = _capability(tmp_path, barrier_epoch=_hex("other-epoch"))
    c = compute_close_token_identity(
        capability=other, predecessor_state="OPEN", nonce="same"
    )
    assert a != b and a != c


def test_hold_session_barrier_lock_release_completes_without_frozen_error(
    tmp_path: Path,
) -> None:
    """F1: mutable held lock must release without FrozenInstanceError."""
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    handle = issue_session_barrier_oms_handle(capability=cap, conn=conn)
    with hold_session_barrier_lock(cap) as held:
        assert held.lock_fd >= 0
    assert held.lock_fd == -1
    with hold_open_write_lease(cap, oms_handle=handle, store_kind="oms"):
        pass


def test_transition_acquires_barrier_lock_before_begin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: OS lock must precede BEGIN IMMEDIATE on initialize/transition."""
    import quant.execution.session_barrier as sb

    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    order: list[str] = []
    real_hold = sb.hold_session_barrier_lock

    @contextmanager
    def tracked_hold(capability: object):
        order.append("lock")
        with real_hold(capability) as held:
            yield held
        order.append("unlock")

    def trace_sql(sql: str) -> None:
        text = str(sql).strip().upper()
        if text.startswith("BEGIN"):
            order.append("begin")
        elif text.startswith("COMMIT"):
            order.append("commit")
        elif text.startswith("ROLLBACK"):
            order.append("rollback")

    monkeypatch.setattr(sb, "hold_session_barrier_lock", tracked_hold)
    # Observe SQL order without replacing Connection.execute (may be read-only).
    conn.set_trace_callback(trace_sql)
    try:
        initialize_open_barrier(conn, cap, created_at=NOW)
        assert order[:3] == ["lock", "begin", "commit"]
        assert order[3] == "unlock"
        order.clear()

        transition_open_to_closing(conn, cap, nonce="order-1", now=NOW)
        assert order.index("lock") < order.index("begin")
        assert order.index("begin") < order.index("commit")
        assert order.index("commit") < order.index("unlock")
    finally:
        conn.set_trace_callback(None)


def _await_writer_ready_or_expose_failure(
    *,
    writer_ready: threading.Event,
    release_writer: threading.Event,
    thread: threading.Thread,
    errors: list[str],
    timeout: float = 0.5,
) -> None:
    """Fail-fast if writer dies before ready; never mask with a long wait AssertionError."""
    if writer_ready.wait(timeout=timeout):
        return
    release_writer.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive(), f"writer still alive after pre-ready failure; errors={errors!r}"
    assert errors, "writer failed before ready without a stable observable code"
    pytest.fail(f"writer failed before ready with stable code(s): {errors!r}")


def _writer_cleanup_handle_and_conn(
    *,
    handle2: object | None,
    conn2: sqlite3.Connection | None,
    cleanup_errors: list[str],
    closed: list[bool] | None = None,
) -> None:
    """Invalidate then unbound close; cleanup faults stay off the primary channel.

    Never assign/replace ``Connection.close``/``execute``. ``closed`` is marked only
    after ``sqlite3.Connection.close(conn2)`` returns successfully.
    """
    import quant.execution.session_barrier as sb

    try:
        if handle2 is not None:
            try:
                sb.invalidate_session_barrier_oms_handle(handle2)
            except Exception as exc:  # noqa: BLE001 - never raise into primary path
                cleanup_errors.append(f"cleanup_invalidate:{type(exc).__name__}")
    finally:
        if conn2 is not None:
            try:
                sqlite3.Connection.close(conn2)
            except Exception as exc:  # noqa: BLE001 - close must run; do not raise
                cleanup_errors.append(f"cleanup_close:{type(exc).__name__}")
            else:
                if closed is not None:
                    closed.append(True)


def _run_writer_until_pre_ready_failure(
    *,
    writer: object,
    writer_ready: threading.Event,
    release_writer: threading.Event,
    errors: list[str],
    timeout: float = 0.5,
) -> threading.Thread:
    """Start writer; require pre-ready failure with stable primary errors in <1s."""
    thread = threading.Thread(target=writer)  # type: ignore[arg-type]
    thread.start()
    assert not writer_ready.wait(timeout=timeout), (
        f"writer reached ready; expected pre-ready failure; errors={errors!r}"
    )
    release_writer.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive(), f"writer still alive; errors={errors!r}"
    assert errors, "writer failed before ready without a stable primary code"
    return thread


def test_writer_and_transition_lock_order_no_deadlock(tmp_path: Path) -> None:
    """F2/F5: writer (lock→BEGIN) vs transition (lock→BEGIN) must not deadlock."""
    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    errors: list[str] = []
    cleanup_errors: list[str] = []
    writer_ready = threading.Event()
    release_writer = threading.Event()
    db_path = str(tmp_path / "oms.sqlite3")

    def writer() -> None:
        # Same thread owns conn2 + handle + lease + BEGIN (no cross-thread Connection).
        conn2: sqlite3.Connection | None = None
        handle2: object | None = None
        try:
            conn2 = sqlite3.connect(db_path, isolation_level=None, timeout=0.0)
            handle2 = issue_session_barrier_oms_handle(capability=cap, conn=conn2)
            with hold_open_write_lease(cap, oms_handle=handle2, store_kind="oms"):
                conn2.execute("BEGIN IMMEDIATE")
                writer_ready.set()
                release_writer.wait(timeout=5)
                conn2.execute("COMMIT")
        except SessionBarrierError as exc:
            errors.append(exc.code)
        except sqlite3.Error as exc:
            errors.append(type(exc).__name__)
        finally:
            _writer_cleanup_handle_and_conn(
                handle2=handle2,
                conn2=conn2,
                cleanup_errors=cleanup_errors,
            )

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        _await_writer_ready_or_expose_failure(
            writer_ready=writer_ready,
            release_writer=release_writer,
            thread=thread,
            errors=errors,
        )
        # Main thread only competes on transition (OS lock); no shared Connection.
        with pytest.raises(SessionBarrierError, match="BARRIER_WRITER_BUSY"):
            transition_open_to_closing(conn, cap, nonce="race", now=NOW)
    finally:
        release_writer.set()
        thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert errors == []
    assert cleanup_errors == []
    # After writer releases, transition proceeds.
    closing, _token = transition_open_to_closing(conn, cap, nonce="race", now=NOW)
    assert closing.state == "CLOSING"


def test_writer_pre_ready_issue_failure_fail_fast_exposes_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V2-F6: issue failure before ready — primary code <1s; no native close patch."""
    import quant.execution.session_barrier as sb

    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    errors: list[str] = []
    cleanup_errors: list[str] = []
    writer_ready = threading.Event()
    release_writer = threading.Event()
    db_path = str(tmp_path / "oms.sqlite3")
    closed: list[bool] = []
    issued: list[object] = []

    def boom_issue(**_kwargs: object) -> object:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")

    monkeypatch.setattr(sb, "issue_session_barrier_oms_handle", boom_issue)

    def writer() -> None:
        conn2: sqlite3.Connection | None = None
        handle2: object | None = None
        try:
            conn2 = sqlite3.connect(db_path, isolation_level=None, timeout=0.0)
            handle2 = sb.issue_session_barrier_oms_handle(capability=cap, conn=conn2)
            issued.append(handle2)
            with hold_open_write_lease(cap, oms_handle=handle2, store_kind="oms"):
                conn2.execute("BEGIN IMMEDIATE")
                writer_ready.set()
                release_writer.wait(timeout=5)
                conn2.execute("COMMIT")
        except SessionBarrierError as exc:
            errors.append(exc.code)
        except sqlite3.Error as exc:
            errors.append(type(exc).__name__)
        finally:
            _writer_cleanup_handle_and_conn(
                handle2=handle2,
                conn2=conn2,
                cleanup_errors=cleanup_errors,
                closed=closed,
            )

    _run_writer_until_pre_ready_failure(
        writer=writer,
        writer_ready=writer_ready,
        release_writer=release_writer,
        errors=errors,
        timeout=0.5,
    )
    assert errors == ["BARRIER_OMS_HANDLE_INVALID"]
    assert cleanup_errors == []
    assert issued == []
    assert closed == [True]
    assert not writer_ready.is_set()


def test_writer_pre_ready_lease_failure_fail_fast_exposes_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V2-F6: lease failure before ready — primary code <1s; handle cleared; close marked."""
    import quant.execution.session_barrier as sb

    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    errors: list[str] = []
    cleanup_errors: list[str] = []
    writer_ready = threading.Event()
    release_writer = threading.Event()
    db_path = str(tmp_path / "oms.sqlite3")
    closed: list[bool] = []
    issued: list[object] = []

    @contextmanager
    def boom_lease(*_a: object, **_k: object):
        raise SessionBarrierError("BARRIER_LEASE_INVALID")
        yield  # pragma: no cover

    monkeypatch.setattr(sb, "hold_open_write_lease", boom_lease)

    def writer() -> None:
        conn2: sqlite3.Connection | None = None
        handle2: object | None = None
        try:
            conn2 = sqlite3.connect(db_path, isolation_level=None, timeout=0.0)
            handle2 = issue_session_barrier_oms_handle(capability=cap, conn=conn2)
            issued.append(handle2)
            with sb.hold_open_write_lease(cap, oms_handle=handle2, store_kind="oms"):
                conn2.execute("BEGIN IMMEDIATE")
                writer_ready.set()
                release_writer.wait(timeout=5)
                conn2.execute("COMMIT")
        except SessionBarrierError as exc:
            errors.append(exc.code)
        except sqlite3.Error as exc:
            errors.append(type(exc).__name__)
        finally:
            _writer_cleanup_handle_and_conn(
                handle2=handle2,
                conn2=conn2,
                cleanup_errors=cleanup_errors,
                closed=closed,
            )

    _run_writer_until_pre_ready_failure(
        writer=writer,
        writer_ready=writer_ready,
        release_writer=release_writer,
        errors=errors,
        timeout=0.5,
    )
    assert errors == ["BARRIER_LEASE_INVALID"]
    assert cleanup_errors == []
    assert len(issued) == 1
    assert issued[0] not in sb._OMS_HANDLE_BINDINGS
    assert closed == [True]
    assert not writer_ready.is_set()


def test_writer_pre_ready_begin_failure_fail_fast_exposes_code(
    tmp_path: Path,
) -> None:
    """V2-F6: BEGIN failure before ready — primary sqlite name <1s; no execute patch."""
    import quant.execution.session_barrier as sb

    conn = _oms_conn(tmp_path)
    cap = _capability(tmp_path)
    initialize_open_barrier(conn, cap, created_at=NOW)
    errors: list[str] = []
    cleanup_errors: list[str] = []
    writer_ready = threading.Event()
    release_writer = threading.Event()
    db_path = str(tmp_path / "oms.sqlite3")
    closed: list[bool] = []
    issued: list[object] = []

    def writer() -> None:
        conn2: sqlite3.Connection | None = None
        handle2: object | None = None
        try:
            conn2 = sqlite3.connect(db_path, isolation_level=None, timeout=0.0)
            handle2 = issue_session_barrier_oms_handle(capability=cap, conn=conn2)
            issued.append(handle2)
            with hold_open_write_lease(cap, oms_handle=handle2, store_kind="oms"):
                # Force BEGIN failure without patching Connection.execute/close.
                sqlite3.Connection.close(conn2)
                conn2.execute("BEGIN IMMEDIATE")
                writer_ready.set()
                release_writer.wait(timeout=5)
                conn2.execute("COMMIT")
        except SessionBarrierError as exc:
            errors.append(exc.code)
        except sqlite3.Error as exc:
            errors.append(type(exc).__name__)
        finally:
            _writer_cleanup_handle_and_conn(
                handle2=handle2,
                conn2=conn2,
                cleanup_errors=cleanup_errors,
                closed=closed,
            )

    _run_writer_until_pre_ready_failure(
        writer=writer,
        writer_ready=writer_ready,
        release_writer=release_writer,
        errors=errors,
        timeout=0.5,
    )
    assert len(errors) == 1
    assert errors[0] in ("ProgrammingError", "OperationalError", "DatabaseError")
    assert cleanup_errors == []
    assert len(issued) == 1
    assert issued[0] not in sb._OMS_HANDLE_BINDINGS
    assert closed == [True]
    assert not writer_ready.is_set()


def test_lock_hardlink_rejected(tmp_path: Path) -> None:
    cap = _capability(tmp_path)
    other = tmp_path / "other-lock-bytes"
    other.write_bytes(b"\0")
    lock_path = cap.lock_root / ".session-barrier.lock"
    try:
        os.link(other, lock_path)
    except OSError:
        pytest.skip("hardlink not supported")
    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_FILE_INVALID",
        "BARRIER_LOCK_IO_FAILED",
        "BARRIER_LOCK_ROOT_INVALID",
    }


def test_lock_leaf_replaced_after_open_fails_revalidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.execution.session_barrier as sb

    cap = _capability(tmp_path)
    real_apply = sb._apply_exclusive_lock
    real_validate = sb._validate_lock_fd

    if sys.platform == "win32":

        def replace_then_lock(fd: int) -> None:
            real_apply(fd)

            def drifted(**kwargs: object):
                identity = real_validate(**kwargs)
                return (identity[0], identity[1] ^ 0xFFFFFFFF)

            monkeypatch.setattr(sb, "_validate_lock_fd", drifted)

        monkeypatch.setattr(sb, "_apply_exclusive_lock", replace_then_lock)
    else:

        def replace_then_lock(fd: int) -> None:
            real_apply(fd)
            lock_path = cap.lock_root / ".session-barrier.lock"
            os.unlink(lock_path)
            new_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
            os.close(new_fd)

        monkeypatch.setattr(sb, "_apply_exclusive_lock", replace_then_lock)

    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_FILE_INVALID",
        "BARRIER_LOCK_IO_FAILED",
        "BARRIER_LOCK_RELEASE_FAILED",
    }


def test_lock_parent_replaced_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.execution.session_barrier as sb

    cap = _capability(tmp_path)
    real_snapshot = sb._snapshot_root_identities
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

    monkeypatch.setattr(sb, "_snapshot_root_identities", snapshot_with_post_lock_drift)
    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_ROOT_INVALID",
        "BARRIER_LOCK_RELEASE_FAILED",
        "BARRIER_LOCK_IO_FAILED",
    }
    assert calls["n"] >= 2


def test_lock_object_identity_drift_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acquire-time lock object identity must match revalidate snapshot."""
    import quant.execution.session_barrier as sb

    cap = _capability(tmp_path)
    real_validate = sb._validate_lock_fd
    calls = {"n": 0}

    def validate_with_drift(**kwargs: object):
        identity = real_validate(**kwargs)
        calls["n"] += 1
        if calls["n"] >= 2:
            return (identity[0], identity[1] ^ 0xABCDEF)
        return identity

    monkeypatch.setattr(sb, "_validate_lock_fd", validate_with_drift)
    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_FILE_INVALID",
        "BARRIER_LOCK_IO_FAILED",
        "BARRIER_LOCK_RELEASE_FAILED",
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reparse/junction probe")
def test_lock_windows_junction_ancestor_rejected(tmp_path: Path) -> None:
    import subprocess

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    junc_parent = tmp_path / "junc-parent"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junc_parent), str(real_parent)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip("cannot create Windows junction")
    nested = junc_parent / "barrier-lock-root"
    nested.mkdir()
    cap = build_session_barrier_capability(
        barrier_epoch=_hex("epoch"),
        session_date=dt.date(2026, 8, 25),
        account_identity=_hex("account"),
        oms_store_identity=_hex("oms"),
        broker_store_identity=_hex("broker"),
        gateway_identity=_hex("gateway"),
        config_identity=_hex("config"),
        lock_root=nested,
    )
    with pytest.raises(SessionBarrierError) as excinfo:
        with hold_session_barrier_lock(cap):
            pass
    assert excinfo.value.code in {
        "BARRIER_LOCK_ROOT_INVALID",
        "BARRIER_LOCK_IO_FAILED",
        "BARRIER_LOCK_FILE_INVALID",
    }

def test_lock_root_concrete_path_guards_native_and_rejects_nonconcrete(
    tmp_path: Path,
) -> None:
    """VALIDATION1: both path guards accept only type(Path()), reject impostors."""
    from pathlib import PurePath, PurePosixPath, PureWindowsPath

    import quant.execution.session_barrier as sb

    concrete = type(Path())
    assert sb._CONCRETE_PATH_TYPE is concrete

    root = tmp_path / "native-lock-root"
    root.mkdir()
    # Native platform Path (WindowsPath / PosixPath) — factory + unpack accept.
    cap = build_session_barrier_capability(
        barrier_epoch=_hex("path-epoch"),
        session_date=dt.date(2026, 8, 25),
        account_identity=_hex("path-account"),
        oms_store_identity=_hex("path-oms"),
        broker_store_identity=_hex("path-broker"),
        gateway_identity=_hex("path-gateway"),
        config_identity=_hex("path-config"),
        lock_root=root,
    )
    assert type(cap.lock_root) is concrete
    assert unpack_session_barrier_capability(cap) is cap

    base_kwargs = {
        "barrier_epoch": _hex("path-epoch"),
        "session_date": dt.date(2026, 8, 25),
        "account_identity": _hex("path-account"),
        "oms_store_identity": _hex("path-oms"),
        "broker_store_identity": _hex("path-broker"),
        "gateway_identity": _hex("path-gateway"),
        "config_identity": _hex("path-config"),
    }

    # Relative concrete Path — both guards reject (absolute required).
    relative = Path("relative-lock-root")
    assert type(relative) is concrete
    with pytest.raises(SessionBarrierError, match="BARRIER_LOCK_ROOT_INVALID"):
        build_session_barrier_capability(**base_kwargs, lock_root=relative)
    object.__setattr__(cap, "lock_root", relative)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(cap)
    object.__setattr__(cap, "lock_root", root)
    assert unpack_session_barrier_capability(cap) is cap

    # Custom concrete Path subclass — rejected (exact type, not isinstance).
    class HostileConcretePath(concrete):  # type: ignore[misc, valid-type]
        pass

    hostile_root = tmp_path / "hostile-subclass-root"
    hostile_root.mkdir()
    hostile = HostileConcretePath(hostile_root)
    assert isinstance(hostile, Path)
    assert type(hostile) is not concrete
    with pytest.raises(SessionBarrierError, match="BARRIER_LOCK_ROOT_INVALID"):
        build_session_barrier_capability(**base_kwargs, lock_root=hostile)
    object.__setattr__(cap, "lock_root", hostile)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(cap)
    object.__setattr__(cap, "lock_root", root)

    # PurePath / PureWindowsPath / PurePosixPath — constructible but not concrete.
    for pure in (
        PurePath(str(root)),
        PureWindowsPath(str(root)),
        PurePosixPath(str(root)),
    ):
        assert type(pure) is not concrete
        with pytest.raises(SessionBarrierError, match="BARRIER_LOCK_ROOT_INVALID"):
            build_session_barrier_capability(
                **base_kwargs, lock_root=pure  # type: ignore[arg-type]
            )
        object.__setattr__(cap, "lock_root", pure)
        with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
            unpack_session_barrier_capability(cap)
    object.__setattr__(cap, "lock_root", root)

    # Duck-typed pseudo-Path — rejected by both guards.
    class DuckPath:
        def is_absolute(self) -> bool:
            return True

        def __fspath__(self) -> str:
            return str(root)

    duck = DuckPath()
    with pytest.raises(SessionBarrierError, match="BARRIER_LOCK_ROOT_INVALID"):
        build_session_barrier_capability(
            **base_kwargs, lock_root=duck  # type: ignore[arg-type]
        )
    object.__setattr__(cap, "lock_root", duck)
    with pytest.raises(SessionBarrierError, match="BARRIER_CAPABILITY_INVALID"):
        unpack_session_barrier_capability(cap)
    object.__setattr__(cap, "lock_root", root)

    # Both guards share the identical concrete type predicate.
    sample_ok = root
    sample_bad = PurePath(str(root))
    assert type(sample_ok) is sb._CONCRETE_PATH_TYPE
    assert type(sample_bad) is not sb._CONCRETE_PATH_TYPE
    assert sb._require_absolute_path(sample_ok) is sample_ok
    with pytest.raises(SessionBarrierError, match="BARRIER_LOCK_ROOT_INVALID"):
        sb._require_absolute_path(sample_bad)  # type: ignore[arg-type]
    assert "_CONCRETE_PATH_TYPE" in sb.unpack_session_barrier_capability.__code__.co_names
    assert "_CONCRETE_PATH_TYPE" in sb._require_absolute_path.__code__.co_names
