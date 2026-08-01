"""M4-P0 SQLite ExecutionStore: schema version, transactions, uniqueness, migrations."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sqlite3
import traceback
from pathlib import Path
from typing import Any, Callable

import pytest

from quant.execution.store import (
    CURRENT_SCHEMA_VERSION,
    ExecutionRepository,
    ExecutionStore,
    IdempotencyConflict,
    MigrationInterruptedError,
    OutboxDeliveryState,
    StoreError,
    StoreUriError,
    UnknownSchemaVersionError,
)
from quant.execution.migrations.v001_initial import upgrade as upgrade_v001


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


ID_A = _hex("id-a")
ID_B = _hex("id-b")
ID_X = _hex("id-x")
ID_Y = _hex("id-y")
ID_E = _hex("eid")
ID_E_A = _hex("eid-a")
ID_E_B = _hex("eid-b")
ID_O_A = _hex("oid-a")
ID_O_B = _hex("oid-b")
ID_AGG = _hex("agg-y")
ID_L1 = _hex("lid-1")
ID_R1 = _hex("rid-1")
ID_A1 = _hex("a1")
ID_A2 = _hex("a2")
ID_L = _hex("l1")
ID_L2 = _hex("l2")
ID_RR1 = _hex("rr1")
ID_RR2 = _hex("rr2")


def _uri(name: str) -> str:
    """Canonical relative sqlite URI (C0-aligned)."""
    return f"sqlite:///{name}"


def _open(name: str, trusted_root: Path) -> ExecutionStore:
    return ExecutionStore.open(_uri(name), trusted_root=trusted_root)


UTC = dt.timezone.utc


def _symlink_or_skip(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise


def _stage_delivery(
    store: ExecutionStore,
    *,
    suffix: str,
    available_at: dt.datetime,
) -> None:
    command_id = f"cmd-{suffix}"
    outbox_key = f"obx-{suffix}"
    with store.transaction() as repo:
        repo.put_command(command_id=command_id, identity=ID_A, payload=b"command")
        repo.put_order_aggregate(
            command_id=command_id,
            identity=ID_AGG,
            payload=b"aggregate",
        )
        repo.put_outbox(outbox_key=outbox_key, identity=ID_O_A, payload=b"outbox")
        assert repo.put_outbox_delivery(
            outbox_key=outbox_key,
            command_id=command_id,
            available_at=available_at,
        )


@pytest.fixture
def cwd_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_open_applies_migration_and_reports_schema_version(cwd_tmp: Path) -> None:
    db = cwd_tmp / "execution.db"
    store = _open("execution.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        assert db.is_file()
    finally:
        store.close()


def test_command_idempotent_same_payload_no_op(cwd_tmp: Path) -> None:
    store = _open("c.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            assert repo.put_command(
                command_id="cmd-1",
                identity=ID_A,
                payload=b"payload-a",
            )
            assert not repo.put_command(
                command_id="cmd-1",
                identity=ID_A,
                payload=b"payload-a",
            )
            got = repo.get_command("cmd-1")
            assert got is not None
            assert got.key == "cmd-1"
            assert got.identity == ID_A
            assert got.payload == b"payload-a"
    finally:
        store.close()


def test_command_same_key_different_payload_conflict(cwd_tmp: Path) -> None:
    store = _open("c2.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"a")
            with pytest.raises(IdempotencyConflict) as exc_info:
                repo.put_command(command_id="cmd-1", identity=ID_B, payload=b"b")
            assert "command" in str(exc_info.value).lower() or "COMMAND" in str(
                exc_info.value
            )
            assert str(cwd_tmp) not in str(exc_info.value)
            assert "/" not in str(exc_info.value) or "cmd-1" in str(exc_info.value)
    finally:
        store.close()


def test_event_and_outbox_unique_key_conflicts(cwd_tmp: Path) -> None:
    store = _open("eo.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"c1")
            repo.put_event(
                event_id="evt-1",
                command_id="cmd-1",
                identity=ID_E_A,
                payload=b"e1",
            )
            assert not repo.put_event(
                event_id="evt-1",
                command_id="cmd-1",
                identity=ID_E_A,
                payload=b"e1",
            )
            with pytest.raises(IdempotencyConflict):
                repo.put_event(
                    event_id="evt-1",
                    command_id="cmd-1",
                    identity=ID_E_B,
                    payload=b"e2",
                )

            repo.put_outbox(outbox_key="obx-1", identity=ID_O_A, payload=b"o1")
            assert not repo.put_outbox(
                outbox_key="obx-1", identity=ID_O_A, payload=b"o1"
            )
            with pytest.raises(IdempotencyConflict):
                repo.put_outbox(outbox_key="obx-1", identity=ID_O_B, payload=b"o2")
    finally:
        store.close()


def test_event_same_id_different_command_id_conflict(cwd_tmp: Path) -> None:
    """Same event_id + same identity/payload but different command_id must conflict.

    Fail-closed: must not silently no-op while leaving the old command_id durable.
    """
    db = cwd_tmp / "evt_cmd.db"
    store = _open("evt_cmd.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-old", identity=ID_A, payload=b"old")
            repo.put_command(command_id="cmd-new", identity=ID_B, payload=b"new")
            assert repo.put_event(
                event_id="evt-a3",
                command_id="cmd-old",
                identity=ID_E,
                payload=b"body",
            )
            with pytest.raises(IdempotencyConflict) as exc_info:
                repo.put_event(
                    event_id="evt-a3",
                    command_id="cmd-new",
                    identity=ID_E,
                    payload=b"body",
                )
            msg = str(exc_info.value)
            assert "IDEMPOTENCY_CONFLICT" in msg
            assert "event" in msg.lower()
            assert str(cwd_tmp) not in msg
            got = repo.get_event("evt-a3")
            assert got is not None
            assert got.identity == ID_E
            assert got.payload == b"body"
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT command_id FROM events WHERE event_id = ?",
                ("evt-a3",),
            ).fetchone()
            assert row is not None
            assert row[0] == "cmd-old"
        finally:
            conn.close()
    finally:
        store.close()


def test_transaction_rollback_on_crash_before_commit(cwd_tmp: Path) -> None:
    store = _open("crash_before.db", cwd_tmp)
    try:
        with pytest.raises(RuntimeError, match="simulated crash before commit"):
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-x", identity=ID_X, payload=b"x")
                raise RuntimeError("simulated crash before commit")
        with store.transaction() as repo:
            assert repo.get_command("cmd-x") is None
    finally:
        store.close()


def test_transaction_persists_after_commit(cwd_tmp: Path) -> None:
    store = _open("crash_after.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-y", identity=ID_Y, payload=b"y")
            repo.put_order_aggregate(
                command_id="cmd-y",
                identity=ID_AGG,
                payload=b"agg",
            )
            repo.put_ledger_entry(entry_id="led-1", identity=ID_L1, payload=b"l1")
            repo.put_reconciliation_run(run_id="rec-1", identity=ID_R1, payload=b"r1")
        store.close()
        store = _open("crash_after.db", cwd_tmp)
        with store.transaction() as repo:
            assert repo.get_command("cmd-y") is not None
            assert repo.get_order_aggregate("cmd-y") is not None
            assert repo.get_ledger_entry("led-1") is not None
            assert repo.get_reconciliation_run("rec-1") is not None
    finally:
        store.close()


def test_unknown_higher_schema_version_fail_closed(cwd_tmp: Path) -> None:
    db = cwd_tmp / "future.db"
    store = _open("future.db", cwd_tmp)
    store.close()

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE schema_version SET version = ?, status = 'ready' WHERE singleton = 1",
            (CURRENT_SCHEMA_VERSION + 99,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(UnknownSchemaVersionError) as exc_info:
        _open("future.db", cwd_tmp)
    assert str(cwd_tmp) not in str(exc_info.value)


def test_migration_interrupted_fail_closed(cwd_tmp: Path) -> None:
    db = cwd_tmp / "interrupted.db"
    store = _open("interrupted.db", cwd_tmp)
    store.close()

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE schema_version SET status = 'migrating' WHERE singleton = 1",
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(MigrationInterruptedError) as exc_info:
        _open("interrupted.db", cwd_tmp)
    assert str(cwd_tmp) not in str(exc_info.value)


def test_aggregates_ledger_reconciliation_idempotent(cwd_tmp: Path) -> None:
    store = _open("rest.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            assert repo.put_order_aggregate(
                command_id="c1", identity=ID_A1, payload=b"p1"
            )
            assert not repo.put_order_aggregate(
                command_id="c1", identity=ID_A1, payload=b"p1"
            )
            with pytest.raises(IdempotencyConflict):
                repo.put_order_aggregate(command_id="c1", identity=ID_A2, payload=b"p2")

            assert repo.put_ledger_entry(entry_id="e1", identity=ID_L, payload=b"x")
            assert not repo.put_ledger_entry(entry_id="e1", identity=ID_L, payload=b"x")
            with pytest.raises(IdempotencyConflict):
                repo.put_ledger_entry(entry_id="e1", identity=ID_L2, payload=b"y")

            assert repo.put_reconciliation_run(run_id="r1", identity=ID_RR1, payload=b"z")
            assert not repo.put_reconciliation_run(
                run_id="r1", identity=ID_RR1, payload=b"z"
            )
            with pytest.raises(IdempotencyConflict):
                repo.put_reconciliation_run(run_id="r1", identity=ID_RR2, payload=b"w")
    finally:
        store.close()


# --- F1: SQLite URI defensive alignment with C0 ---


@pytest.mark.parametrize(
    "bad_uri",
    [
        "sqlite:////tmp/absolute.db",
        "sqlite:////home/someone/secrets/trading.db",
        "sqlite:///C:/Users/me/trading.db",
        "sqlite:///c:/Users/me/trading.db",
        "SQLITE:///artifacts/trading/execution.db",
        "SQLite:///artifacts/trading/execution.db",
        "sqlite:///artifacts/../secrets/trading.db",
        "sqlite:///./trading.db",
        "sqlite:///foo//bar.db",
        "sqlite:///%2e%2e/private.db",
        "sqlite:///artifacts\\trading.db",
        "sqlite:///artifacts/trading/execution.db?mode=ro",
        "sqlite:///artifacts/trading/execution.db#x",
        "sqlite:///artifacts/trading/execution.db\n",
        "sqlite:///",
        "file:///artifacts/trading/execution.db",
    ],
)
def test_f1_rejects_absolute_and_unsafe_uris(bad_uri: str, cwd_tmp: Path) -> None:
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(bad_uri, trusted_root=cwd_tmp)
    assert str(exc_info.value) == "URI_INVALID"
    assert exc_info.value.__cause__ is None
    assert str(cwd_tmp) not in str(exc_info.value)
    assert str(cwd_tmp) not in repr(exc_info.value)


def test_f1_canonical_relative_uri_opens(cwd_tmp: Path) -> None:
    store = _open("artifacts/trading/execution.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        assert (cwd_tmp / "artifacts" / "trading" / "execution.db").is_file()
    finally:
        store.close()


# --- F2: durable identity wire format ---


class _StrIdentity(str):
    """str subclass must be rejected (exact str only)."""


_INVALID_IDENTITIES: list[Any] = [
    "not-a-hash",
    "A" * 64,
    "ab" * 31,  # 62 chars
    "ab" * 32 + "0",  # 65 chars
    "g" + "a" * 63,  # non-hex
    True,
    False,
    1,
    None,
    b"a" * 64,
    _StrIdentity("a" * 64),
]


def _putters() -> list[tuple[str, Callable[[ExecutionRepository, Any], bool]]]:
    return [
        (
            "command",
            lambda repo, ident: repo.put_command(
                command_id="cmd-k", identity=ident, payload=b"p"
            ),
        ),
        (
            "event",
            lambda repo, ident: repo.put_event(
                event_id="evt-k",
                command_id="cmd-k",
                identity=ident,
                payload=b"p",
            ),
        ),
        (
            "order_aggregate",
            lambda repo, ident: repo.put_order_aggregate(
                command_id="cmd-k", identity=ident, payload=b"p"
            ),
        ),
        (
            "outbox",
            lambda repo, ident: repo.put_outbox(
                outbox_key="obx-k", identity=ident, payload=b"p"
            ),
        ),
        (
            "ledger_entry",
            lambda repo, ident: repo.put_ledger_entry(
                entry_id="led-k", identity=ident, payload=b"p"
            ),
        ),
        (
            "reconciliation_run",
            lambda repo, ident: repo.put_reconciliation_run(
                run_id="rec-k", identity=ident, payload=b"p"
            ),
        ),
    ]


@pytest.mark.parametrize(
    "subject,putter",
    _putters(),
    ids=[name for name, _ in _putters()],
)
@pytest.mark.parametrize(
    "bad_identity",
    _INVALID_IDENTITIES,
    ids=[f"{type(v).__name__}:{repr(v)[:20]}" for v in _INVALID_IDENTITIES],
)
def test_f2_put_rejects_illegal_identity(
    cwd_tmp: Path,
    subject: str,
    putter: Callable[[ExecutionRepository, Any], bool],
    bad_identity: Any,
) -> None:
    store = _open(f"id_{subject}.db", cwd_tmp)
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                if subject == "event":
                    repo.put_command(
                        command_id="cmd-k", identity=ID_A, payload=b"c"
                    )
                putter(repo, bad_identity)
        assert str(exc_info.value) == "IDENTITY_INVALID"
        assert exc_info.value.__cause__ is None
    finally:
        store.close()


def test_f2_get_rejects_corrupt_identity_row(cwd_tmp: Path) -> None:
    db = cwd_tmp / "corrupt_id.db"
    store = _open("corrupt_id.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"ok")
    finally:
        store.close()

    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE commands SET identity = ? WHERE command_id = ?",
            ("not-a-hash", "cmd-1"),
        )
        conn.commit()
    finally:
        conn.close()

    store = _open("corrupt_id.db", cwd_tmp)
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.get_command("cmd-1")
        assert str(exc_info.value) == "ROW_CORRUPT"
        assert exc_info.value.__cause__ is None
        assert str(cwd_tmp) not in str(exc_info.value)
    finally:
        store.close()


# --- F3: command/event referential integrity ---


def test_f3_orphan_event_rejected(cwd_tmp: Path) -> None:
    store = _open("orphan.db", cwd_tmp)
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.put_event(
                    event_id="evt-1",
                    command_id="missing-command",
                    identity=ID_E_A,
                    payload=b"e1",
                )
        assert str(exc_info.value) == "REFERENTIAL_INTEGRITY"
        assert exc_info.value.__cause__ is None
        with store.transaction() as repo:
            assert repo.get_event("evt-1") is None
    finally:
        store.close()


def test_f3_command_then_event_ok(cwd_tmp: Path) -> None:
    store = _open("cmd_evt.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            assert repo.put_command(
                command_id="cmd-1", identity=ID_A, payload=b"c"
            )
            assert repo.put_event(
                event_id="evt-1",
                command_id="cmd-1",
                identity=ID_E_A,
                payload=b"e",
            )
            got = repo.get_event("evt-1")
            assert got is not None
            assert got.identity == ID_E_A
    finally:
        store.close()


def test_f3_orphan_in_same_txn_rolls_back_command(cwd_tmp: Path) -> None:
    store = _open("orphan_rb.db", cwd_tmp)
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-keep", identity=ID_A, payload=b"c")
                repo.put_event(
                    event_id="evt-1",
                    command_id="missing-command",
                    identity=ID_E_A,
                    payload=b"e",
                )
        assert str(exc_info.value) == "REFERENTIAL_INTEGRITY"
        with store.transaction() as repo:
            assert repo.get_command("cmd-keep") is None
            assert repo.get_event("evt-1") is None
    finally:
        store.close()


# --- F4: scrubbed OS/SQLite errors ---


def _assert_scrubbed_store_error(
    exc: BaseException, *, code: str, injected: str
) -> None:
    assert isinstance(exc, StoreError)
    assert str(exc) == code
    assert exc.__cause__ is None
    assert exc.__context__ is None
    rendered = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    text = f"{exc!s}\n{exc!r}\n{rendered}"
    assert injected not in text
    for fragment in (injected, Path(injected).name):
        if fragment:
            assert fragment not in str(exc)
            assert fragment not in repr(exc)


def test_f4_mkdir_parent_conflict_scrubbed(cwd_tmp: Path) -> None:
    blocker = cwd_tmp / "blocked"
    blocker.write_text("not-a-directory", encoding="utf-8")
    with pytest.raises(StoreUriError) as exc_info:
        _open("blocked/child.db", cwd_tmp)
    _assert_scrubbed_store_error(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=str(cwd_tmp),
    )


def test_f4_directory_as_db_boundary_scrubbed(cwd_tmp: Path) -> None:
    (cwd_tmp / "isdir").mkdir()
    with pytest.raises(StoreUriError) as exc_info:
        _open("isdir", cwd_tmp)
    _assert_scrubbed_store_error(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=str(cwd_tmp),
    )


def test_f4_mkdir_oserror_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak = str(cwd_tmp / "mkdir_secret")

    def _boom(self: Path, *a: object, **k: object) -> None:
        raise OSError(f"mkdir failed near {leak}")

    monkeypatch.setattr(Path, "mkdir", _boom)
    with pytest.raises(StoreError) as exc_info:
        _open("nested/child.db", cwd_tmp)
    _assert_scrubbed_store_error(
        exc_info.value, code="PARENT_CREATE_FAILED", injected=leak
    )


def test_f4_connect_failure_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak = str(cwd_tmp / "secret.db")

    def _boom(*_a: object, **_k: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError(f"unable to open database file: {leak}")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    with pytest.raises(StoreError) as exc_info:
        _open("x.db", cwd_tmp)
    _assert_scrubbed_store_error(exc_info.value, code="OPEN_FAILED", injected=leak)


def test_f4_pragma_failure_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    leak = str(cwd_tmp / "pragma_secret")

    class _PragmaFailConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", inner)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and sql.upper().startswith("PRAGMA"):
                raise sqlite3.OperationalError(f"pragma failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def _connect(*a: object, **k: object) -> Any:
        return _PragmaFailConn(real_connect(*a, **k))

    monkeypatch.setattr(sqlite3, "connect", _connect)
    with pytest.raises(StoreError) as exc_info:
        _open("pragma.db", cwd_tmp)
    _assert_scrubbed_store_error(exc_info.value, code="PRAGMA_FAILED", injected=leak)


def test_f4_migration_failure_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    leak = str(cwd_tmp / "mig_secret")

    class _MigrationFailConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", inner)
            object.__setattr__(self, "_seen_begin", False)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and sql.upper().startswith("BEGIN"):
                object.__setattr__(self, "_seen_begin", True)
                return self._inner.execute(sql, *args, **kwargs)
            if (
                self._seen_begin
                and isinstance(sql, str)
                and "schema_version" in sql.lower()
            ):
                raise sqlite3.OperationalError(f"migration boom {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def _connect(*a: object, **k: object) -> Any:
        return _MigrationFailConn(real_connect(*a, **k))

    monkeypatch.setattr(sqlite3, "connect", _connect)
    with pytest.raises(StoreError) as exc_info:
        _open("mig.db", cwd_tmp)
    _assert_scrubbed_store_error(
        exc_info.value, code="MIGRATION_FAILED", injected=leak
    )


def test_f4_user_exception_in_transaction_not_swallowed(cwd_tmp: Path) -> None:
    store = _open("user_exc.db", cwd_tmp)
    try:
        with pytest.raises(RuntimeError, match="business boom"):
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"x")
                raise RuntimeError("business boom")
        with store.transaction() as repo:
            assert repo.get_command("cmd-1") is None
    finally:
        store.close()


def test_f4_tx_begin_failed_scrubbed(cwd_tmp: Path) -> None:
    store = _open("tx_begin.db", cwd_tmp)
    leak = str(cwd_tmp / "tx_begin_secret.db")
    inner = store._conn
    assert inner is not None

    class _BeginFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and sql.upper().startswith("BEGIN"):
                raise sqlite3.OperationalError(f"begin failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _BeginFailConn(inner)  # type: ignore[assignment]
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction():
                pass
        _assert_scrubbed_store_error(
            exc_info.value, code="TX_BEGIN_FAILED", injected=leak
        )
    finally:
        store._conn = inner
        store.close()


def test_f4_tx_commit_failed_scrubbed(cwd_tmp: Path) -> None:
    store = _open("tx_commit.db", cwd_tmp)
    leak = str(cwd_tmp / "tx_commit_secret.db")
    inner = store._conn
    assert inner is not None

    class _CommitFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and sql.upper().startswith("COMMIT"):
                raise sqlite3.OperationalError(f"commit failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _CommitFailConn(inner)  # type: ignore[assignment]
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"x")
        _assert_scrubbed_store_error(
            exc_info.value, code="TX_COMMIT_FAILED", injected=leak
        )
    finally:
        store._conn = inner
        store.close()


def test_f4_tx_commit_then_rollback_fail_keeps_commit_primary(cwd_tmp: Path) -> None:
    store = _open("tx_commit_rb.db", cwd_tmp)
    leak = str(cwd_tmp / "rb_cover_secret.db")
    inner = store._conn
    assert inner is not None

    class _CommitRollbackFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if not isinstance(sql, str):
                return self._inner.execute(sql, *args, **kwargs)
            upper = sql.upper()
            if upper.startswith("COMMIT"):
                raise sqlite3.OperationalError(f"commit failed near {leak}")
            if upper.startswith("ROLLBACK"):
                raise sqlite3.OperationalError(f"rollback failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _CommitRollbackFailConn(inner)  # type: ignore[assignment]
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"x")
        _assert_scrubbed_store_error(
            exc_info.value, code="TX_COMMIT_FAILED", injected=leak
        )
    finally:
        store._conn = inner
        store.close()


def test_f4_business_exception_survives_rollback_failure(cwd_tmp: Path) -> None:
    store = _open("biz_rb.db", cwd_tmp)
    leak = str(cwd_tmp / "biz_rb_secret.db")
    inner = store._conn
    assert inner is not None

    class _RollbackFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and sql.upper().startswith("ROLLBACK"):
                raise sqlite3.OperationalError(f"rollback failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _RollbackFailConn(inner)  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="primary business boom") as exc_info:
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-1", identity=ID_A, payload=b"x")
                raise RuntimeError("primary business boom")
        assert not isinstance(exc_info.value, StoreError)
        assert str(exc_info.value) == "primary business boom"
    finally:
        store._conn = inner
        store.close()


def test_f4_close_failed_scrubbed(cwd_tmp: Path) -> None:
    store = _open("close_fail.db", cwd_tmp)
    leak = str(cwd_tmp / "close_secret.db")
    inner = store._conn
    assert inner is not None

    class _CloseFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            raise sqlite3.OperationalError(f"close failed near {leak}")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _CloseFailConn(inner)  # type: ignore[assignment]
    with pytest.raises(StoreError) as exc_info:
        store.close()
    _assert_scrubbed_store_error(exc_info.value, code="CLOSE_FAILED", injected=leak)
    assert store._conn is None
    inner.close()


def test_f4_referential_integrity_scrubbed(cwd_tmp: Path) -> None:
    store = _open("fk_scrub.db", cwd_tmp)
    leak = str(cwd_tmp / "fk_secret.db")
    inner = store._conn
    assert inner is not None

    class _FkFailConn:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", conn)

        def execute(self, sql: object, *args: object, **kwargs: object) -> Any:
            if isinstance(sql, str) and "INSERT INTO events" in sql:
                raise sqlite3.IntegrityError(f"FOREIGN KEY failed near {leak}")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FkFailConn(inner)  # type: ignore[assignment]
    try:
        with pytest.raises(StoreError) as exc_info:
            with store.transaction() as repo:
                repo.put_event(
                    event_id="evt-1",
                    command_id="missing",
                    identity=ID_E_A,
                    payload=b"e",
                )
        _assert_scrubbed_store_error(
            exc_info.value, code="REFERENTIAL_INTEGRITY", injected=leak
        )
    finally:
        store._conn = inner
        store.close()


# --- P0-H1: trusted_root + physical URI boundary ---


def _assert_uri_code(exc: BaseException, *, code: str, injected: str) -> None:
    assert isinstance(exc, StoreUriError)
    assert str(exc) == code
    assert exc.__cause__ is None
    assert exc.__context__ is None
    rendered = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    text = f"{exc!s}\n{exc!r}\n{rendered}"
    assert injected not in text

def test_h1_missing_trusted_root_typeerror(cwd_tmp: Path) -> None:
    with pytest.raises(TypeError):
        ExecutionStore.open(_uri("x.db"))  # type: ignore[call-arg]


def test_h1_relative_trusted_root_rejected(cwd_tmp: Path) -> None:
    rel = Path("relative_root")
    rel.mkdir()
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=rel)
    _assert_uri_code(
        exc_info.value, code="TRUSTED_ROOT_INVALID", injected=str(cwd_tmp)
    )


def test_h1_string_trusted_root_rejected(cwd_tmp: Path) -> None:
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(
            _uri("x.db"), trusted_root=str(cwd_tmp)  # type: ignore[arg-type]
        )
    _assert_uri_code(
        exc_info.value, code="TRUSTED_ROOT_INVALID", injected=str(cwd_tmp)
    )


def test_h1_bytes_bool_fspath_root_rejected(cwd_tmp: Path) -> None:
    class _FsPath:
        def __fspath__(self) -> str:
            return str(cwd_tmp)

    for bad in (str(cwd_tmp).encode(), True, False, _FsPath()):
        with pytest.raises(StoreUriError) as exc_info:
            ExecutionStore.open(
                _uri("x.db"), trusted_root=bad  # type: ignore[arg-type]
            )
        assert str(exc_info.value) == "TRUSTED_ROOT_INVALID"
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None


def test_h1_path_subclass_root_rejected(cwd_tmp: Path) -> None:
    concrete = type(Path())

    class _SubPath(concrete):  # type: ignore[valid-type,misc]
        pass

    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=_SubPath(cwd_tmp))
    assert str(exc_info.value) == "TRUSTED_ROOT_INVALID"


def test_h1_symlink_trusted_root_rejected(
    cwd_tmp: Path, tmp_path: Path
) -> None:
    real = tmp_path / "real_root"
    real.mkdir()
    link = cwd_tmp / "link_root"
    _symlink_or_skip(link, real, target_is_directory=True)
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=link)
    _assert_uri_code(
        exc_info.value, code="TRUSTED_ROOT_INVALID", injected=str(real)
    )


def test_h1_file_trusted_root_rejected(cwd_tmp: Path) -> None:
    root_file = cwd_tmp / "root_file"
    root_file.write_text("x", encoding="utf-8")
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=root_file)
    _assert_uri_code(
        exc_info.value, code="TRUSTED_ROOT_INVALID", injected=str(root_file)
    )


def test_h1_filesystem_root_rejected(cwd_tmp: Path) -> None:
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=Path("/"))
    assert str(exc_info.value) == "TRUSTED_ROOT_INVALID"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_h1_mid_symlink_outside_rejected(
    cwd_tmp: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside_target"
    outside.mkdir()
    link = cwd_tmp / "mid"
    _symlink_or_skip(link, outside, target_is_directory=True)
    with pytest.raises(StoreUriError) as exc_info:
        _open("mid/db.sqlite", cwd_tmp)
    _assert_uri_code(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=str(outside),
    )
    assert not (outside / "db.sqlite").exists()


def test_h1_mid_symlink_inside_still_rejected(cwd_tmp: Path) -> None:
    inside = cwd_tmp / "inside_dir"
    inside.mkdir()
    link = cwd_tmp / "mid_link"
    _symlink_or_skip(link, inside, target_is_directory=True)
    with pytest.raises(StoreUriError) as exc_info:
        _open("mid_link/db.sqlite", cwd_tmp)
    _assert_uri_code(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=str(inside),
    )


def test_h1_leaf_symlink_outside_rejected(
    cwd_tmp: Path, tmp_path: Path
) -> None:
    outside_file = tmp_path / "ext.db"
    outside_file.write_bytes(b"x")
    link = cwd_tmp / "leaf.db"
    _symlink_or_skip(link, outside_file)
    with pytest.raises(StoreUriError) as exc_info:
        _open("leaf.db", cwd_tmp)
    _assert_uri_code(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=str(outside_file),
    )


def test_h1_leaf_directory_rejected(cwd_tmp: Path) -> None:
    (cwd_tmp / "as_dir").mkdir()
    with pytest.raises(StoreUriError) as exc_info:
        _open("as_dir", cwd_tmp)
    assert str(exc_info.value) == "URI_PHYSICAL_BOUNDARY_INVALID"


def test_h1_leaf_fifo_rejected(cwd_tmp: Path) -> None:
    fifo = cwd_tmp / "fifo.db"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError, NotImplementedError):
        pytest.skip("fifo not supported on this platform")
    with pytest.raises(StoreUriError) as exc_info:
        _open("fifo.db", cwd_tmp)
    assert str(exc_info.value) == "URI_PHYSICAL_BOUNDARY_INVALID"


def test_h1_leaf_hardlink_rejected(cwd_tmp: Path) -> None:
    primary = cwd_tmp / "primary.db"
    primary.write_bytes(b"sqlite-placeholder")
    hard = cwd_tmp / "hard.db"
    try:
        os.link(primary, hard)
    except OSError:
        pytest.skip("hardlink not supported")
    with pytest.raises(StoreUriError) as exc_info:
        _open("hard.db", cwd_tmp)
    assert str(exc_info.value) == "URI_PHYSICAL_BOUNDARY_INVALID"


def test_h1_existing_regular_single_link_opens(cwd_tmp: Path) -> None:
    store = _open("regular.db", cwd_tmp)
    store.close()
    assert (cwd_tmp / "regular.db").is_file()
    store2 = _open("regular.db", cwd_tmp)
    try:
        assert store2.schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        store2.close()


def test_h1_missing_nested_parents_created_inside_root(cwd_tmp: Path) -> None:
    store = _open("a/b/c/store.db", cwd_tmp)
    try:
        target = cwd_tmp / "a" / "b" / "c" / "store.db"
        assert target.is_file()
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        store.close()


def test_h1_cwd_change_still_uses_explicit_root(
    cwd_tmp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other_cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    store = ExecutionStore.open(_uri("only_in_root.db"), trusted_root=cwd_tmp)
    try:
        assert (cwd_tmp / "only_in_root.db").is_file()
        assert not (other / "only_in_root.db").exists()
    finally:
        store.close()


def test_h1_trusted_root_resolve_oserror_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leak = str(cwd_tmp / "resolve_secret")

    def _boom(self: Path, *a: object, **k: object) -> Path:
        raise OSError(f"resolve failed near {leak}")

    monkeypatch.setattr(Path, "resolve", _boom)
    with pytest.raises(StoreUriError) as exc_info:
        ExecutionStore.open(_uri("x.db"), trusted_root=cwd_tmp)
    _assert_uri_code(
        exc_info.value, code="TRUSTED_ROOT_INVALID", injected=leak
    )


def test_h1_lstat_oserror_scrubbed(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.execution.store as store_mod

    leak = str(cwd_tmp / "lstat_secret")

    def _boom(_path: Path) -> os.stat_result | None:
        raise OSError(f"lstat failed near {leak}")

    monkeypatch.setattr(store_mod, "_lstat_mapped", _boom)
    with pytest.raises(StoreUriError) as exc_info:
        _open("x.db", cwd_tmp)
    _assert_uri_code(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=leak,
    )


def test_h1_post_connect_recheck_closes_connection(
    cwd_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.execution.store as store_mod

    leak = str(cwd_tmp / "post_secret")
    closed = {"n": 0}
    real_connect = sqlite3.connect
    real_check_leaf = store_mod._check_leaf

    class _CloseFailConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            object.__setattr__(self, "_inner", inner)

        def close(self) -> None:
            closed["n"] += 1
            raise sqlite3.OperationalError(f"close failed near {leak}")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def _connect(*a: object, **k: object) -> Any:
        return _CloseFailConn(real_connect(*a, **k))

    def _check(
        path: Path, resolved_root: Path, *, must_exist: bool
    ) -> None:
        if must_exist:
            raise OSError(f"post recheck failed near {leak}")
        return real_check_leaf(path, resolved_root, must_exist=must_exist)

    monkeypatch.setattr(sqlite3, "connect", _connect)
    monkeypatch.setattr(store_mod, "_check_leaf", _check)
    with pytest.raises(StoreUriError) as exc_info:
        _open("post.db", cwd_tmp)
    _assert_uri_code(
        exc_info.value,
        code="URI_PHYSICAL_BOUNDARY_INVALID",
        injected=leak,
    )
    assert closed["n"] == 1


def test_v1_to_current_preserves_legacy_outbox_but_does_not_make_it_sendable(
    cwd_tmp: Path,
) -> None:
    db = cwd_tmp / "legacy-v1.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY "
            "CHECK (singleton = 1), version INTEGER NOT NULL, status TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        upgrade_v001(conn)
        conn.execute(
            "INSERT INTO schema_version VALUES (1, 1, 'ready', '2026-07-18T00:00:00Z')"
        )
        conn.execute("INSERT INTO commands VALUES ('cmd-old', ?, ?)", (ID_A, b"c"))
        conn.execute("INSERT INTO outbox VALUES ('obx-old', ?, ?)", (ID_O_A, b"o"))
        conn.commit()
    finally:
        conn.close()

    store = _open("legacy-v1.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        with store.transaction() as repo:
            assert repo.get_outbox("obx-old") is not None
            assert repo.get_outbox_delivery("obx-old") is None
            assert repo.claim_outbox_deliveries(
                worker_id="worker-1",
                now=dt.datetime(2026, 7, 18, tzinfo=UTC),
                lease_until=dt.datetime(2026, 7, 18, 0, 1, tzinfo=UTC),
                limit=1,
            ) == ()
    finally:
        store.close()


def test_delivery_requires_command_aggregate_and_outbox_in_atomic_transaction(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, tzinfo=UTC)
    store = _open("delivery-fk.db", cwd_tmp)
    try:
        with pytest.raises(StoreError, match="REFERENTIAL_INTEGRITY"):
            with store.transaction() as repo:
                repo.put_command(command_id="cmd-no-agg", identity=ID_A, payload=b"c")
                repo.put_outbox(outbox_key="obx-no-agg", identity=ID_O_A, payload=b"o")
                repo.put_outbox_delivery(
                    outbox_key="obx-no-agg",
                    command_id="cmd-no-agg",
                    available_at=now,
                )
        with store.transaction() as repo:
            assert repo.get_command("cmd-no-agg") is None
            assert repo.get_outbox("obx-no-agg") is None
    finally:
        store.close()


def test_claim_is_ordered_restart_safe_and_terminal_sent_is_idempotent(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 1, tzinfo=UTC)
    store = _open("delivery-order.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="b", available_at=now)
        _stage_delivery(store, suffix="a", available_at=now)
        _stage_delivery(store, suffix="future", available_at=now + dt.timedelta(seconds=1))
        store.close()
        store = _open("delivery-order.db", cwd_tmp)
        with store.transaction() as repo:
            claimed = repo.claim_outbox_deliveries(
                worker_id="worker-1",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
                limit=1,
            )
            assert [row.outbox_key for row in claimed] == ["obx-a"]
            assert claimed[0].command_id == "cmd-a"
            assert claimed[0].payload == b"outbox"
            assert claimed[0].attempt_count == 1
        store.close()
        store = _open("delivery-order.db", cwd_tmp)
        sent_at = now + dt.timedelta(seconds=10)
        with store.transaction() as repo:
            assert repo.mark_outbox_sent(
                outbox_key="obx-a", lease_owner="worker-1",
                expected_attempt=1, sent_at=sent_at,
            )
            assert not repo.mark_outbox_sent(
                outbox_key="obx-a", lease_owner="worker-1",
                expected_attempt=1, sent_at=sent_at,
            )
            assert not repo.put_outbox_delivery(
                outbox_key="obx-a", command_id="cmd-a", available_at=now
            )
            got = repo.get_outbox_delivery("obx-a")
            assert got is not None and got.state is OutboxDeliveryState.SENT
            remaining = repo.claim_outbox_deliveries(
                worker_id="worker-2", now=now + dt.timedelta(seconds=30),
                lease_until=now + dt.timedelta(minutes=2), limit=5,
            )
            assert [row.outbox_key for row in remaining] == ["obx-b", "obx-future"]
    finally:
        store.close()


def test_same_worker_old_attempt_is_fenced_after_expired_lease_reclaim(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 2, tzinfo=UTC)
    store = _open("delivery-fence.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="fence", available_at=now)
        first_lease = now + dt.timedelta(seconds=10)
        with store.transaction() as repo:
            first = repo.claim_outbox_deliveries(
                worker_id="same-worker", now=now,
                lease_until=first_lease, limit=1,
            )[0]
        with store.transaction() as repo:
            second = repo.claim_outbox_deliveries(
                worker_id="same-worker", now=first_lease,
                lease_until=now + dt.timedelta(seconds=30), limit=1,
            )[0]
            assert (first.attempt_count, second.attempt_count) == (1, 2)
            with pytest.raises(StoreError, match="FENCE_MISMATCH"):
                repo.mark_outbox_sent(
                    outbox_key="obx-fence", lease_owner="same-worker",
                    expected_attempt=1, sent_at=now + dt.timedelta(seconds=15),
                )
            assert repo.mark_outbox_sent(
                outbox_key="obx-fence", lease_owner="same-worker",
                expected_attempt=2, sent_at=now + dt.timedelta(seconds=15),
            )
    finally:
        store.close()


def test_unknown_is_audited_terminal_and_never_reclaimed(cwd_tmp: Path) -> None:
    now = dt.datetime(2026, 7, 18, 4, tzinfo=UTC)
    store = _open("delivery-unknown.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="unknown", available_at=now)
        terminal = now + dt.timedelta(seconds=5)
        with store.transaction() as repo:
            claimed = repo.claim_outbox_deliveries(
                worker_id="worker-u", now=now,
                lease_until=now + dt.timedelta(seconds=30), limit=1,
            )[0]
            assert repo.mark_outbox_unknown(
                outbox_key=claimed.outbox_key, lease_owner="worker-u",
                expected_attempt=1, unknown_at=terminal,
                error_code="GATEWAY_TIMEOUT",
            )
            assert not repo.mark_outbox_unknown(
                outbox_key=claimed.outbox_key, lease_owner="worker-u",
                expected_attempt=1, unknown_at=terminal,
                error_code="GATEWAY_TIMEOUT",
            )
            with pytest.raises(StoreError):
                repo.mark_outbox_sent(
                    outbox_key=claimed.outbox_key, lease_owner="worker-u",
                    expected_attempt=1, sent_at=terminal,
                )
            assert repo.claim_outbox_deliveries(
                worker_id="worker-v", now=now + dt.timedelta(days=1),
                lease_until=now + dt.timedelta(days=1, minutes=1), limit=1,
            ) == ()
    finally:
        store.close()


def test_expired_lease_cannot_be_completed_before_reclaim(cwd_tmp: Path) -> None:
    now = dt.datetime(2026, 7, 18, 3, tzinfo=UTC)
    store = _open("delivery-expired.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="expired", available_at=now)
        lease_until = now + dt.timedelta(seconds=10)
        with store.transaction() as repo:
            repo.claim_outbox_deliveries(
                worker_id="worker-old", now=now,
                lease_until=lease_until, limit=1,
            )
            with pytest.raises(StoreError, match="LEASE_EXPIRED"):
                repo.mark_outbox_sent(
                    outbox_key="obx-expired", lease_owner="worker-old",
                    expected_attempt=1, sent_at=lease_until,
                )
    finally:
        store.close()


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, "1"])
def test_claim_rejects_invalid_limit_before_state_change(
    cwd_tmp: Path, limit: object
) -> None:
    now = dt.datetime(2026, 7, 18, 5, tzinfo=UTC)
    store = _open(f"delivery-limit-{str(limit).replace('.', '-')}.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="limit", available_at=now)
        with store.transaction() as repo:
            with pytest.raises(StoreError):
                repo.claim_outbox_deliveries(
                    worker_id="worker-l", now=now,
                    lease_until=now + dt.timedelta(minutes=1),
                    limit=limit,  # type: ignore[arg-type]
                )
            got = repo.get_outbox_delivery("obx-limit")
            assert got is not None and got.attempt_count == 0
    finally:
        store.close()


def test_claim_rejects_non_utc_times_before_state_change(cwd_tmp: Path) -> None:
    now = dt.datetime(2026, 7, 18, 6, tzinfo=UTC)
    store = _open("delivery-time.db", cwd_tmp)
    try:
        _stage_delivery(store, suffix="time", available_at=now)
        invalid = (
            now.replace(tzinfo=None),
            now.astimezone(dt.timezone(dt.timedelta(hours=8))),
        )
        with store.transaction() as repo:
            for bad_now in invalid:
                with pytest.raises(StoreError):
                    repo.claim_outbox_deliveries(
                        worker_id="worker-t", now=bad_now,
                        lease_until=now + dt.timedelta(minutes=1), limit=1,
                    )
            got = repo.get_outbox_delivery("obx-time")
            assert got is not None and got.attempt_count == 0
    finally:
        store.close()


def test_corrupt_orphan_delivery_is_not_silently_hidden_from_claim(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 7, tzinfo=UTC)
    db = cwd_tmp / "delivery-orphan.db"
    store = _open("delivery-orphan.db", cwd_tmp)
    _stage_delivery(store, suffix="orphan", available_at=now)
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM order_aggregates WHERE command_id = 'cmd-orphan'")
        conn.commit()
    finally:
        conn.close()
    store = _open("delivery-orphan.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ROW_CORRUPT"):
                repo.claim_outbox_deliveries(
                    worker_id="worker-o", now=now,
                    lease_until=now + dt.timedelta(minutes=1), limit=1,
                )
    finally:
        store.close()


def test_delivery_corrupt_timestamp_and_real_attempt_fail_closed(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 8, tzinfo=UTC)
    db = cwd_tmp / "delivery-corrupt.db"
    store = _open("delivery-corrupt.db", cwd_tmp)
    _stage_delivery(store, suffix="corrupt", available_at=now)
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "UPDATE outbox_deliveries SET attempt_count = 1.5, available_at = ?",
            ("2026-07-18T08:00:00Z",),
        )
        conn.commit()
    finally:
        conn.close()
    store = _open("delivery-corrupt.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ROW_CORRUPT"):
                repo.get_outbox_delivery("obx-corrupt")
            with pytest.raises(StoreError, match="ROW_CORRUPT"):
                repo.claim_outbox_deliveries(
                    worker_id="worker-c", now=now,
                    lease_until=now + dt.timedelta(minutes=1), limit=1,
                )
    finally:
        store.close()


def test_two_connections_and_nested_writer_fail_fast_with_tx_busy(
    cwd_tmp: Path,
) -> None:
    store_a = _open("delivery-busy.db", cwd_tmp)
    store_b = _open("delivery-busy.db", cwd_tmp)
    try:
        with store_a.transaction():
            with pytest.raises(StoreError, match="TX_BUSY"):
                with store_a.transaction():
                    pass
            with pytest.raises(StoreError, match="TX_BUSY"):
                with store_b.transaction():
                    pass
        with store_b.transaction() as repo:
            assert repo.get_outbox_delivery("does-not-exist") is None
    finally:
        store_a.close()
        store_b.close()


def test_batch_claim_preflight_prevents_partial_update_when_attempt_exhausted(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 9, tzinfo=UTC)
    db = cwd_tmp / "delivery-exhausted.db"
    store = _open("delivery-exhausted.db", cwd_tmp)
    _stage_delivery(store, suffix="a-exhaust", available_at=now)
    _stage_delivery(store, suffix="b-exhaust", available_at=now)
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            UPDATE outbox_deliveries
            SET state = 'LEASED', attempt_count = ?, lease_owner = 'old-worker',
                lease_until = ?, terminal_at = NULL, last_error_code = NULL
            WHERE outbox_key = 'obx-b-exhaust'
            """,
            (2**63 - 1, "2026-07-18T09:00:01.000000Z"),
        )
        conn.commit()
    finally:
        conn.close()
    store = _open("delivery-exhausted.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ATTEMPT_EXHAUSTED"):
                repo.claim_outbox_deliveries(
                    worker_id="new-worker", now=now + dt.timedelta(seconds=1),
                    lease_until=now + dt.timedelta(minutes=1), limit=2,
                )
            first = repo.get_outbox_delivery("obx-a-exhaust")
            second = repo.get_outbox_delivery("obx-b-exhaust")
            assert first is not None
            assert first.state is OutboxDeliveryState.PENDING
            assert first.attempt_count == 0
            assert second is not None
            assert second.state is OutboxDeliveryState.LEASED
            assert second.attempt_count == 2**63 - 1
    finally:
        store.close()


def test_delivery_row_corruption_error_has_no_cause_or_context(cwd_tmp: Path) -> None:
    now = dt.datetime(2026, 7, 18, 10, tzinfo=UTC)
    db = cwd_tmp / "delivery-context.db"
    store = _open("delivery-context.db", cwd_tmp)
    _stage_delivery(store, suffix="context", available_at=now)
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "UPDATE outbox_deliveries SET state = 'BOGUS' "
            "WHERE outbox_key = 'obx-context'"
        )
        conn.commit()
    finally:
        conn.close()
    store = _open("delivery-context.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ROW_CORRUPT") as exc_info:
                repo.get_outbox_delivery("obx-context")
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None
    finally:
        store.close()


def test_batch_claim_sql_failure_rolls_back_savepoint_when_caller_catches(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 7, 18, 11, tzinfo=UTC)
    store = _open("delivery-savepoint.db", cwd_tmp)
    _stage_delivery(store, suffix="a-savepoint", available_at=now)
    _stage_delivery(store, suffix="b-savepoint", available_at=now)
    inner = store._conn  # noqa: SLF001 - fault injection at SQLite boundary
    assert inner is not None

    class _FailSecondClaimUpdate:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._inner = conn
            self._updates = 0

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql.lstrip().startswith("UPDATE outbox_deliveries"):
                self._updates += 1
                if self._updates == 2:
                    raise sqlite3.OperationalError("injected second update failure")
            return self._inner.execute(sql, parameters)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FailSecondClaimUpdate(inner)  # type: ignore[assignment]  # noqa: SLF001
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="CLAIM_FAILED") as exc_info:
                repo.claim_outbox_deliveries(
                    worker_id="worker-savepoint", now=now,
                    lease_until=now + dt.timedelta(minutes=1), limit=2,
                )
            assert exc_info.value.__cause__ is None
            assert exc_info.value.__context__ is None
            for key in ("obx-a-savepoint", "obx-b-savepoint"):
                got = repo.get_outbox_delivery(key)
                assert got is not None
                assert got.state is OutboxDeliveryState.PENDING
                assert got.attempt_count == 0
    finally:
        store.close()
