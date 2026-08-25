"""M4-P0 SQLite ExecutionStore: schema version, transactions, uniqueness, migrations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import pytest

from quant.execution.approval import (
    ApprovalReceiptError,
    build_approval_receipt,
    decode_approval_receipt,
    encode_approval_receipt,
    verify_approval_receipt_for_store,
)
from quant.execution.store import (
    CURRENT_SCHEMA_VERSION,
    ExecutionRepository,
    ExecutionStore,
    IdempotencyConflict,
    LEDGER_CHECKPOINT_KEY,
    MigrationInterruptedError,
    OutboxDeliveryState,
    StoredApprovalReceipt,
    StoreError,
    StoreUriError,
    UnknownSchemaVersionError,
)
from quant.execution.migrations.v001_initial import upgrade as upgrade_v001
from quant.execution.migrations.v002_outbox_delivery import upgrade as upgrade_v002
from quant.execution.migrations.v003_daily_risk_counters import (
    upgrade as upgrade_typed_v003,
)
from quant.execution.migrations.v003_execution_state import (
    upgrade as upgrade_scoped_v003,
)
from quant.execution.risk import (
    DailyRiskCounters,
    build_daily_risk_counters_identity,
    serialize_daily_risk_counters,
)


def _hex(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


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


APPROVAL_SECRET = b"execution-store-approval-secret-012345"
APPROVAL_SOURCES = {
    "account_snapshot": _hex("approval-account"),
    "market_snapshot": _hex("approval-market"),
    "planner_config": _hex("approval-planner"),
}


def _approval(nonce: str = "store-approval-1", *, plan: str = "plan"):
    return build_approval_receipt(
        APPROVAL_SECRET,
        credential_id="credential-store-1",
        operator_id="operator-store-1",
        session_date=dt.date(2026, 8, 24),
        plan_identity=_hex(plan),
        challenge_identity=_hex(f"challenge-{nonce}"),
        store_recovery_identity=_hex("store-recovery"),
        source_identities=APPROVAL_SOURCES,
        issued_at=dt.datetime(2026, 8, 24, 3, 4, 5, tzinfo=UTC),
        nonce=nonce,
    )


def _self_consistent_hmac_forgery(payload: bytes) -> bytes:
    root = json.loads(payload.decode("utf-8"))
    root["tag"] = "0" * 64 if root["tag"] != "0" * 64 else "1" * 64
    unsigned = dict(root)
    unsigned.pop("receipt_id")
    root["receipt_id"] = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    return _canonical_bytes(root)


def _corrupt_handoff(
    verified: Any,
    payload: bytes,
    *,
    receipt: Any | None = None,
    proof: bytes | None = None,
) -> Any:
    """Deliberately bypass construction to exercise the proof guard."""
    forged = object.__new__(type(verified))
    object.__setattr__(
        forged,
        "receipt",
        verified.receipt if receipt is None else receipt,
    )
    object.__setattr__(forged, "payload", payload)
    if proof is not None:
        object.__setattr__(forged, "_proof", proof)
    return forged


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


def test_v3_execution_stage_is_immutable_and_preserves_canonical_bytes(
    cwd_tmp: Path,
) -> None:
    payload = _canonical_bytes(
        {"schema_version": "m4-execution-stage-v1", "symbols": ["600000.SH", "腾讯"]}
    )
    store = _open("stage-v3.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            assert repo.put_execution_stage(
                plan_id="plan-1", identity=ID_A, payload=payload
            )
            assert not repo.put_execution_stage(
                plan_id="plan-1", identity=ID_A, payload=payload
            )
            with pytest.raises(IdempotencyConflict, match="execution_stage"):
                repo.put_execution_stage(
                    plan_id="plan-1", identity=ID_A, payload=b"different"
                )
            got = repo.get_execution_stage("plan-1")
            assert got is not None
            assert got.identity == ID_A
            assert got.payload == payload
            with pytest.raises(IdempotencyConflict, match="execution_stage"):
                repo.put_execution_stage(
                    plan_id="plan-1", identity=ID_B, payload=b"different"
                )
    finally:
        store.close()


def test_v3_order_aggregate_strict_cas_and_exact_replay(cwd_tmp: Path) -> None:
    store = _open("aggregate-cas-v3.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_order_aggregate(
                command_id="cmd-cas", identity=ID_A, payload=b"created"
            )
            assert repo.replace_order_aggregate(
                command_id="cmd-cas",
                expected_identity=ID_A,
                identity=ID_B,
                payload=b"submitted",
            )
            assert not repo.replace_order_aggregate(
                command_id="cmd-cas",
                expected_identity=ID_A,
                identity=ID_B,
                payload=b"submitted",
            )
            with pytest.raises(IdempotencyConflict, match="IDEMPOTENCY_CONFLICT"):
                repo.replace_order_aggregate(
                    command_id="cmd-cas",
                    expected_identity=ID_B,
                    identity=ID_B,
                    payload=b"same-identity-different-payload",
                )
            with pytest.raises(IdempotencyConflict, match="CAS_MISMATCH"):
                repo.replace_order_aggregate(
                    command_id="cmd-cas",
                    expected_identity=ID_A,
                    identity=ID_X,
                    payload=b"filled",
                )
            got = repo.get_order_aggregate("cmd-cas")
            assert got is not None
            assert (got.identity, got.payload) == (ID_B, b"submitted")
    finally:
        store.close()


def test_v4_scoped_daily_risk_counters_insert_read_and_cas(cwd_tmp: Path) -> None:
    initial = _canonical_bytes(
        {"buy_notional": "0", "cancel_count": 0, "order_count": 0}
    )
    projected = _canonical_bytes(
        {"buy_notional": "1000.00", "cancel_count": 0, "order_count": 1}
    )
    store = _open("counters-cas-v3.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            assert repo.put_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03", identity=ID_A, payload=initial
            )
            assert not repo.put_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03", identity=ID_A, payload=initial
            )
            with pytest.raises(IdempotencyConflict, match="daily_risk_counters"):
                repo.put_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03",
                    identity=ID_B,
                    payload=projected,
                )
            assert repo.compare_and_set_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03",
                expected_identity=ID_A,
                identity=ID_B,
                payload=projected,
            )
            assert not repo.compare_and_set_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03",
                expected_identity=ID_A,
                identity=ID_B,
                payload=projected,
            )
            with pytest.raises(IdempotencyConflict, match="IDEMPOTENCY_CONFLICT"):
                repo.compare_and_set_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03",
                    expected_identity=ID_B,
                    identity=ID_B,
                    payload=b"same-identity-different-payload",
                )
            with pytest.raises(IdempotencyConflict, match="CAS_MISMATCH"):
                repo.compare_and_set_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03",
                    expected_identity=ID_A,
                    identity=ID_X,
                    payload=b"forbidden",
                )
            got = repo.get_scoped_daily_risk_counters("paper:2026-08-03")
            assert got is not None
            assert (got.identity, got.payload) == (ID_B, projected)
    finally:
        store.close()


def test_v4_execution_state_outer_transaction_rolls_back_together(
    cwd_tmp: Path,
) -> None:
    store = _open("state-atomic-v3.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_order_aggregate(
                command_id="cmd-atomic", identity=ID_A, payload=b"created"
            )
            repo.put_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03", identity=ID_A, payload=b"zero"
            )
        with pytest.raises(RuntimeError, match="crash"):
            with store.transaction() as repo:
                repo.replace_order_aggregate(
                    command_id="cmd-atomic",
                    expected_identity=ID_A,
                    identity=ID_B,
                    payload=b"submitted",
                )
                repo.compare_and_set_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03",
                    expected_identity=ID_A,
                    identity=ID_B,
                    payload=b"one",
                )
                repo.put_execution_stage(
                    plan_id="plan-atomic", identity=ID_X, payload=b"receipt"
                )
                raise RuntimeError("crash")
        with store.transaction() as repo:
            aggregate = repo.get_order_aggregate("cmd-atomic")
            counters = repo.get_scoped_daily_risk_counters("paper:2026-08-03")
            assert aggregate is not None and aggregate.identity == ID_A
            assert counters is not None and counters.identity == ID_A
            assert repo.get_execution_stage("plan-atomic") is None
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
        (
            "execution_stage",
            lambda repo, ident: repo.put_execution_stage(
                plan_id="plan-k", identity=ident, payload=b"p"
            ),
        ),
        (
            "scoped_daily_risk_counters",
            lambda repo, ident: repo.put_scoped_daily_risk_counters(
                counter_key="paper:2026-08-03", identity=ident, payload=b"p"
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


def test_v2_to_current_adds_empty_daily_risk_counters_without_data_loss(
    cwd_tmp: Path,
) -> None:
    db = cwd_tmp / "legacy-v2.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY "
            "CHECK (singleton = 1), version INTEGER NOT NULL, status TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        upgrade_v001(conn)
        upgrade_v002(conn)
        conn.execute(
            "INSERT INTO schema_version VALUES (1, 2, 'ready', '2026-07-18T00:00:00Z')"
        )
        conn.execute("INSERT INTO commands VALUES ('cmd-v2', ?, ?)", (ID_A, b"c"))
        conn.commit()
    finally:
        conn.close()

    store = _open("legacy-v2.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        with store.transaction() as repo:
            assert repo.get_command("cmd-v2") is not None
            assert repo.get_daily_risk_counters(dt.date(2026, 7, 18)) is None
    finally:
        store.close()


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


def test_v2_to_current_preserves_delivery_rows_and_adds_execution_state(
    cwd_tmp: Path,
) -> None:
    db = cwd_tmp / "legacy-v2.db"
    now_text = "2026-08-03T00:00:00.000000Z"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY "
            "CHECK (singleton = 1), version INTEGER NOT NULL, status TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        upgrade_v001(conn)
        upgrade_v002(conn)
        conn.execute(
            "INSERT INTO schema_version VALUES (1, 2, 'ready', ?)", (now_text,)
        )
        conn.execute("INSERT INTO commands VALUES ('cmd-old', ?, ?)", (ID_A, b"c"))
        conn.execute(
            "INSERT INTO order_aggregates VALUES ('cmd-old', ?, ?)",
            (ID_AGG, b"created"),
        )
        conn.execute("INSERT INTO outbox VALUES ('obx-old', ?, ?)", (ID_O_A, b"o"))
        conn.execute(
            "INSERT INTO outbox_deliveries VALUES "
            "('obx-old', 'cmd-old', 'PENDING', 0, ?, NULL, NULL, NULL, NULL)",
            (now_text,),
        )
        conn.commit()
    finally:
        conn.close()

    store = _open("legacy-v2.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        with store.transaction() as repo:
            delivery = repo.get_outbox_delivery("obx-old")
            assert delivery is not None
            assert delivery.state is OutboxDeliveryState.PENDING
            assert repo.get_execution_stage("plan-new") is None
            assert repo.get_scoped_daily_risk_counters("paper:2026-08-03") is None
    finally:
        store.close()


def test_scoped_v3_to_v7_preserves_rows_and_adds_typed_counters(
    cwd_tmp: Path,
) -> None:
    db = cwd_tmp / "legacy-scoped-v3.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY "
            "CHECK (singleton = 1), version INTEGER NOT NULL, status TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        upgrade_v001(conn)
        upgrade_v002(conn)
        upgrade_scoped_v003(conn)
        conn.execute(
            "INSERT INTO schema_version VALUES (1, 3, 'ready', "
            "'2026-08-03T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO daily_risk_counters VALUES (?, ?, ?)",
            ("paper:2026-08-03", ID_A, b"legacy-scoped"),
        )
        conn.commit()
    finally:
        conn.close()

    store = _open("legacy-scoped-v3.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        with store.transaction() as repo:
            scoped = repo.get_scoped_daily_risk_counters("paper:2026-08-03")
            assert scoped is not None
            assert (scoped.identity, scoped.payload) == (ID_A, b"legacy-scoped")
            assert repo.get_daily_risk_counters(dt.date(2026, 8, 3)) is None
    finally:
        store.close()


def test_typed_v3_to_v7_preserves_rows_and_adds_scoped_counters(
    cwd_tmp: Path,
) -> None:
    db = cwd_tmp / "legacy-typed-v3.db"
    counters = DailyRiskCounters(
        session_date=dt.date(2026, 8, 3),
        order_count=2,
        cancel_count=1,
        buy_notional=Decimal("123.45"),
    )
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE schema_version (singleton INTEGER PRIMARY KEY "
            "CHECK (singleton = 1), version INTEGER NOT NULL, status TEXT NOT NULL, "
            "applied_at TEXT NOT NULL)"
        )
        upgrade_v001(conn)
        upgrade_v002(conn)
        upgrade_typed_v003(conn)
        conn.execute(
            "INSERT INTO schema_version VALUES (1, 3, 'ready', "
            "'2026-08-03T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO daily_risk_counters VALUES (?, ?, ?, ?)",
            (
                counters.session_date.isoformat(),
                build_daily_risk_counters_identity(counters),
                serialize_daily_risk_counters(counters),
                "2026-08-03T00:00:00.000000Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    store = _open("legacy-typed-v3.db", cwd_tmp)
    try:
        assert store.schema_version() == CURRENT_SCHEMA_VERSION
        with store.transaction() as repo:
            typed = repo.get_daily_risk_counters(dt.date(2026, 8, 3))
            assert typed is not None and typed.counters == counters
            assert repo.get_scoped_daily_risk_counters("paper:2026-08-03") is None
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


def test_selected_claim_preserves_input_order_and_excludes_other_ready_rows(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 8, 2, tzinfo=UTC)
    command_ids = tuple(sorted((_hex("selected-a"), _hex("selected-b"))))
    other = _hex("other-ready")
    store = _open("selected-exact.db", cwd_tmp)
    try:
        for command_id in (*command_ids, other):
            with store.transaction() as repo:
                repo.put_command(
                    command_id=command_id, identity=command_id, payload=b"wire"
                )
                repo.put_order_aggregate(
                    command_id=command_id, identity=ID_AGG, payload=b"aggregate"
                )
                repo.put_outbox(
                    outbox_key=command_id, identity=command_id, payload=b"wire"
                )
                repo.put_outbox_delivery(
                    outbox_key=command_id,
                    command_id=command_id,
                    available_at=now,
                )
        with store.transaction() as repo:
            before = repo.get_outbox_delivery(other)
            claimed = repo.claim_selected_outbox_deliveries(
                command_ids=command_ids,
                worker_id="selected-worker",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )
            after = repo.get_outbox_delivery(other)
        assert tuple(item.command_id for item in claimed) == command_ids
        assert before == after
        assert after is not None and after.state is OutboxDeliveryState.PENDING
    finally:
        store.close()


def test_selected_claim_rolls_back_all_members_when_one_is_terminal(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 8, 2, 1, tzinfo=UTC)
    command_ids = tuple(sorted((_hex("atomic-a"), _hex("atomic-b"))))
    store = _open("selected-atomic.db", cwd_tmp)
    try:
        for command_id in command_ids:
            with store.transaction() as repo:
                repo.put_command(
                    command_id=command_id, identity=command_id, payload=b"wire"
                )
                repo.put_order_aggregate(
                    command_id=command_id, identity=ID_AGG, payload=b"aggregate"
                )
                repo.put_outbox(
                    outbox_key=command_id, identity=command_id, payload=b"wire"
                )
                repo.put_outbox_delivery(
                    outbox_key=command_id,
                    command_id=command_id,
                    available_at=now,
                )
        terminal_id = command_ids[1]
        with store.transaction() as repo:
            delivery = repo.claim_selected_outbox_deliveries(
                command_ids=(terminal_id,),
                worker_id="terminal-worker",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )[0]
            repo.mark_outbox_sent(
                outbox_key=terminal_id,
                lease_owner="terminal-worker",
                expected_attempt=delivery.attempt_count,
                sent_at=now + dt.timedelta(seconds=1),
            )
        with pytest.raises(StoreError, match="OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE"):
            with store.transaction() as repo:
                repo.claim_selected_outbox_deliveries(
                    command_ids=command_ids,
                    worker_id="selected-worker",
                    now=now,
                    lease_until=now + dt.timedelta(minutes=1),
                )
        with store.transaction() as repo:
            ready = repo.get_outbox_delivery(command_ids[0])
        assert ready is not None and ready.state is OutboxDeliveryState.PENDING
        assert ready.attempt_count == 0
    finally:
        store.close()


def _stage_exact_pending_delivery(
    store: ExecutionStore,
    *,
    command_id: str,
    available_at: dt.datetime,
) -> None:
    with store.transaction() as repo:
        repo.put_command(
            command_id=command_id, identity=command_id, payload=b"wire"
        )
        repo.put_order_aggregate(
            command_id=command_id, identity=ID_AGG, payload=b"aggregate"
        )
        repo.put_outbox(
            outbox_key=command_id, identity=command_id, payload=b"wire"
        )
        repo.put_outbox_delivery(
            outbox_key=command_id,
            command_id=command_id,
            available_at=available_at,
        )


def test_exact_pending_claim_succeeds_only_for_complete_global_set(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 8, 2, 2, tzinfo=UTC)
    command_ids = tuple(sorted((_hex("exact-a"), _hex("exact-b"))))
    store = _open("exact-pending-success.db", cwd_tmp)
    try:
        for command_id in command_ids:
            _stage_exact_pending_delivery(
                store, command_id=command_id, available_at=now
            )
        with store.transaction() as repo:
            claimed = repo.claim_exact_pending_outbox_deliveries(
                command_ids=command_ids,
                worker_id="exact-worker",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )
        assert tuple(item.command_id for item in claimed) == command_ids
        assert all(item.state is OutboxDeliveryState.LEASED for item in claimed)
        assert all(item.lease_owner == "exact-worker" for item in claimed)
    finally:
        store.close()


def test_exact_pending_claim_preserves_sqlite_write_failure_as_retryable(
    cwd_tmp: Path,
) -> None:
    now = dt.datetime(2026, 8, 2, 2, 30, tzinfo=UTC)
    command_id = _hex("exact-write-failure")
    store = _open("exact-pending-write-failure.db", cwd_tmp)
    try:
        _stage_exact_pending_delivery(store, command_id=command_id, available_at=now)
        store._conn.execute(  # noqa: SLF001 - fault injection at SQLite boundary
            """
            CREATE TRIGGER fail_exact_pending_claim
            BEFORE UPDATE OF state ON outbox_deliveries
            WHEN NEW.state = 'LEASED'
            BEGIN
                SELECT RAISE(ABORT, 'PRIVATE_TRIGGER_SENTINEL');
            END
            """
        )
        with pytest.raises(
            StoreError, match="^OUTBOX_DELIVERY_EXACT_CLAIM_FAILED$"
        ) as error:
            with store.transaction() as repo:
                repo.claim_exact_pending_outbox_deliveries(
                    command_ids=(command_id,),
                    worker_id="exact-worker",
                    now=now,
                    lease_until=now + dt.timedelta(minutes=1),
                )
        assert error.value.__cause__ is None
        assert error.value.__context__ is None
        with store.transaction() as repo:
            delivery = repo.get_outbox_delivery(command_id)
        assert delivery is not None
        assert delivery.state is OutboxDeliveryState.PENDING
        assert delivery.attempt_count == 0
    finally:
        store.close()


@pytest.mark.parametrize("drift_kind", ["EXTRA", "MISSING", "FUTURE"])
def test_exact_pending_claim_rejects_any_pending_set_drift(
    cwd_tmp: Path, drift_kind: str
) -> None:
    now = dt.datetime(2026, 8, 2, 3, tzinfo=UTC)
    command_ids = tuple(sorted((_hex("drift-a"), _hex("drift-b"))))
    store = _open(f"exact-pending-{drift_kind.lower()}.db", cwd_tmp)
    try:
        for index, command_id in enumerate(command_ids):
            available_at = (
                now + dt.timedelta(minutes=1)
                if drift_kind == "FUTURE" and index == 1
                else now
            )
            _stage_exact_pending_delivery(
                store, command_id=command_id, available_at=available_at
            )
        if drift_kind == "EXTRA":
            selected = (command_ids[0],)
        elif drift_kind == "MISSING":
            selected = tuple(sorted((command_ids[0], _hex("absent"))))
        else:
            selected = command_ids
        with pytest.raises(StoreError, match="^OUTBOX_DELIVERY_EXACT_SET_DRIFT$"):
            with store.transaction() as repo:
                repo.claim_exact_pending_outbox_deliveries(
                    command_ids=selected,
                    worker_id="exact-worker",
                    now=now,
                    lease_until=now + dt.timedelta(minutes=1),
                )
        with store.transaction() as repo:
            deliveries = tuple(
                repo.get_outbox_delivery(command_id) for command_id in command_ids
            )
        assert all(item is not None for item in deliveries)
        assert all(
            item is not None
            and item.state is OutboxDeliveryState.PENDING
            and item.attempt_count == 0
            for item in deliveries
        )
    finally:
        store.close()


@pytest.mark.parametrize("blocked_state", ["LEASED", "UNKNOWN"])
def test_exact_pending_claim_rejects_global_ambiguous_delivery(
    cwd_tmp: Path, blocked_state: str
) -> None:
    now = dt.datetime(2026, 8, 2, 4, tzinfo=UTC)
    command_ids = tuple(sorted((_hex("ambiguous-a"), _hex("ambiguous-b"))))
    store = _open(f"exact-pending-{blocked_state.lower()}.db", cwd_tmp)
    try:
        for command_id in command_ids:
            _stage_exact_pending_delivery(
                store, command_id=command_id, available_at=now
            )
        with store.transaction() as repo:
            claimed = repo.claim_selected_outbox_deliveries(
                command_ids=(command_ids[1],),
                worker_id="other-worker",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )[0]
            if blocked_state == "UNKNOWN":
                repo.mark_outbox_unknown(
                    outbox_key=claimed.outbox_key,
                    lease_owner="other-worker",
                    expected_attempt=claimed.attempt_count,
                    unknown_at=now + dt.timedelta(seconds=1),
                    error_code="FIXTURE_UNKNOWN",
                )
        with pytest.raises(StoreError, match="^OUTBOX_DELIVERY_EXACT_SET_DRIFT$"):
            with store.transaction() as repo:
                repo.claim_exact_pending_outbox_deliveries(
                    command_ids=(command_ids[0],),
                    worker_id="exact-worker",
                    now=now,
                    lease_until=now + dt.timedelta(minutes=1),
                )
        with store.transaction() as repo:
            untouched = repo.get_outbox_delivery(command_ids[0])
        assert untouched is not None
        assert untouched.state is OutboxDeliveryState.PENDING
        assert untouched.attempt_count == 0
    finally:
        store.close()


def test_v3_cas_post_update_failure_rolls_back_savepoint_when_caller_catches(
    cwd_tmp: Path,
) -> None:
    store = _open("state-cas-savepoint.db", cwd_tmp)
    with store.transaction() as repo:
        repo.put_order_aggregate(
            command_id="cmd-savepoint", identity=ID_A, payload=b"created"
        )
    inner = store._conn  # noqa: SLF001 - fault injection at SQLite boundary
    assert inner is not None
    leak = str(cwd_tmp / "private-state")

    class _FailPostUpdateRead:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._inner = conn
            self._aggregate_selects = 0

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql.lstrip().startswith(
                "SELECT command_id, identity, payload FROM order_aggregates"
            ):
                self._aggregate_selects += 1
                if self._aggregate_selects == 2:
                    raise sqlite3.OperationalError(f"injected failure near {leak}")
            return self._inner.execute(sql, parameters)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FailPostUpdateRead(inner)  # type: ignore[assignment]  # noqa: SLF001
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ORDER_AGGREGATE_CAS_FAILED") as exc_info:
                repo.replace_order_aggregate(
                    command_id="cmd-savepoint",
                    expected_identity=ID_A,
                    identity=ID_B,
                    payload=b"submitted",
                )
            assert leak not in str(exc_info.value)
            assert exc_info.value.__cause__ is None
            assert exc_info.value.__context__ is None
            got = repo.get_order_aggregate("cmd-savepoint")
            assert got is not None
            assert (got.identity, got.payload) == (ID_A, b"created")
    finally:
        store.close()


def test_v3_cas_missing_rows_fail_without_creating_state(cwd_tmp: Path) -> None:
    store = _open("state-cas-missing.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="ORDER_AGGREGATE_NOT_FOUND"):
                repo.replace_order_aggregate(
                    command_id="missing-command",
                    expected_identity=ID_A,
                    identity=ID_B,
                    payload=b"x",
                )
            with pytest.raises(StoreError, match="DAILY_RISK_COUNTERS_NOT_FOUND"):
                repo.compare_and_set_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03",
                    expected_identity=ID_A,
                    identity=ID_B,
                    payload=b"x",
                )
            assert repo.get_order_aggregate("missing-command") is None
            assert repo.get_scoped_daily_risk_counters("paper:2026-08-03") is None
    finally:
        store.close()


def test_v3_stage_select_operational_error_is_sanitized_and_atomic(
    cwd_tmp: Path,
) -> None:
    store = _open("stage-select-failure.db", cwd_tmp)
    inner = store._conn  # noqa: SLF001 - fault injection at SQLite boundary
    assert inner is not None
    sentinel = str(cwd_tmp / "stage-select-sentinel")

    class _FailStageSelect:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._inner = conn

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql.lstrip().startswith(
                "SELECT identity, payload FROM execution_stages"
            ):
                raise sqlite3.OperationalError(f"select failed near {sentinel}")
            return self._inner.execute(sql, parameters)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FailStageSelect(inner)  # type: ignore[assignment]  # noqa: SLF001
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="EXECUTION_STAGE_QUERY_FAILED") as info:
                repo.put_execution_stage(
                    plan_id="plan-select-failure", identity=ID_A, payload=b"receipt"
                )
            assert sentinel not in str(info.value)
            assert info.value.__cause__ is None
            assert info.value.__context__ is None
            assert repo.get_execution_stage("plan-select-failure") is None
    finally:
        store.close()


def test_v4_scoped_counter_insert_operational_error_is_sanitized_and_atomic(
    cwd_tmp: Path,
) -> None:
    store = _open("counter-insert-failure.db", cwd_tmp)
    inner = store._conn  # noqa: SLF001 - fault injection at SQLite boundary
    assert inner is not None
    sentinel = str(cwd_tmp / "counter-insert-sentinel")

    class _FailCounterInsert:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._inner = conn

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql.lstrip().startswith("INSERT INTO scoped_daily_risk_counters"):
                raise sqlite3.OperationalError(f"insert failed near {sentinel}")
            return self._inner.execute(sql, parameters)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FailCounterInsert(inner)  # type: ignore[assignment]  # noqa: SLF001
    try:
        with store.transaction() as repo:
            with pytest.raises(
                StoreError, match="DAILY_RISK_COUNTERS_WRITE_FAILED"
            ) as info:
                repo.put_scoped_daily_risk_counters(
                    counter_key="paper:2026-08-03", identity=ID_A, payload=b"zero"
                )
            assert sentinel not in str(info.value)
            assert info.value.__cause__ is None
            assert info.value.__context__ is None
            assert repo.get_scoped_daily_risk_counters("paper:2026-08-03") is None
    finally:
        store.close()


def test_put_event_foreign_key_failure_keeps_referential_integrity_code(
    cwd_tmp: Path,
) -> None:
    store = _open("event-fk-regression.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="REFERENTIAL_INTEGRITY") as info:
                repo.put_event(
                    event_id="event-without-command",
                    command_id="missing-command",
                    identity=ID_E,
                    payload=b"event",
                )
            assert info.value.__cause__ is None
            assert info.value.__context__ is None
            assert repo.get_event("event-without-command") is None
    finally:
        store.close()


def test_recovery_rows_empty_store_is_valid(cwd_tmp: Path) -> None:
    store = _open("recovery-empty.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            rows = repo.read_recovery_rows()
        assert rows.commands == ()
        assert rows.events == ()
        assert rows.order_aggregates == ()
        assert rows.outbox_deliveries == ()
        assert rows.ledger_entries == ()
        assert rows.ledger_contexts == ()
        assert rows.ledger_checkpoints == ()
    finally:
        store.close()


def test_recovery_rows_are_strict_and_sorted_by_primary_key(cwd_tmp: Path) -> None:
    store = _open("recovery-sorted.db", cwd_tmp)
    now = dt.datetime(2026, 8, 3, 1, tzinfo=UTC)
    try:
        with store.transaction() as repo:
            for suffix in ("b", "a"):
                command_id = f"cmd-{suffix}"
                repo.put_command(
                    command_id=command_id,
                    identity=_hex(f"command-{suffix}"),
                    payload=f"command-{suffix}".encode(),
                )
                repo.put_order_aggregate(
                    command_id=command_id,
                    identity=_hex(f"aggregate-{suffix}"),
                    payload=f"aggregate-{suffix}".encode(),
                )
                repo.put_event(
                    event_id=f"evt-{suffix}",
                    command_id=command_id,
                    identity=_hex(f"event-{suffix}"),
                    payload=f"event-{suffix}".encode(),
                )
                repo.put_outbox(
                    outbox_key=f"obx-{suffix}",
                    identity=_hex(f"outbox-{suffix}"),
                    payload=f"outbox-{suffix}".encode(),
                )
                repo.put_outbox_delivery(
                    outbox_key=f"obx-{suffix}",
                    command_id=command_id,
                    available_at=now,
                )
                repo.put_ledger_entry(
                    entry_id=f"led-{suffix}",
                    identity=_hex(f"ledger-{suffix}"),
                    payload=f"ledger-{suffix}".encode(),
                )
                repo.put_ledger_context(
                    command_id=command_id,
                    identity=_hex(f"context-{suffix}"),
                    payload=f"context-{suffix}".encode(),
                )
            repo.put_ledger_checkpoint(
                checkpoint_key="paper-shadow-primary-v1",
                identity=_hex("checkpoint"),
                payload=b"checkpoint",
                last_entry_id="led-b",
            )
            rows = repo.read_recovery_rows()

        assert tuple(item.key for item in rows.commands) == ("cmd-a", "cmd-b")
        assert tuple(item.event_id for item in rows.events) == ("evt-a", "evt-b")
        assert tuple(item.command_id for item in rows.events) == ("cmd-a", "cmd-b")
        assert tuple(item.key for item in rows.order_aggregates) == ("cmd-a", "cmd-b")
        assert tuple(item.outbox_key for item in rows.outbox_deliveries) == (
            "obx-a",
            "obx-b",
        )
        assert tuple(item.key for item in rows.ledger_entries) == ("led-a", "led-b")
        assert tuple(item.key for item in rows.ledger_contexts) == ("cmd-a", "cmd-b")
        assert tuple(item.checkpoint_key for item in rows.ledger_checkpoints) == (
            "paper-shadow-primary-v1",
        )
        assert rows.ledger_checkpoints[0].last_entry_id == "led-b"
    finally:
        store.close()


def test_recovery_rows_hold_one_transaction_snapshot(cwd_tmp: Path) -> None:
    first = _open("recovery-atomic.db", cwd_tmp)
    second = _open("recovery-atomic.db", cwd_tmp)
    try:
        with first.transaction() as repo:
            repo.put_command(command_id="cmd-a", identity=ID_A, payload=b"a")
            before = repo.read_recovery_rows()
            with pytest.raises(StoreError, match="^TX_BUSY$"):
                with second.transaction() as other:
                    other.put_command(command_id="cmd-b", identity=ID_B, payload=b"b")
            after = repo.read_recovery_rows()
            assert before == after

        with second.transaction() as repo:
            repo.put_command(command_id="cmd-b", identity=ID_B, payload=b"b")
        with first.transaction() as repo:
            latest = repo.read_recovery_rows()
        assert tuple(item.key for item in latest.commands) == ("cmd-a", "cmd-b")
    finally:
        first.close()
        second.close()


def test_ledger_checkpoint_cas_and_context_idempotency(cwd_tmp: Path) -> None:
    store = _open("ledger-v4-cas.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id="cmd-a", identity=ID_A, payload=b"command")
            assert repo.put_ledger_context(
                command_id="cmd-a", identity=ID_B, payload=b"context"
            )
            assert not repo.put_ledger_context(
                command_id="cmd-a", identity=ID_B, payload=b"context"
            )
            repo.put_ledger_entry(entry_id="entry-a", identity=ID_E, payload=b"entry")
            assert repo.put_ledger_checkpoint(
                checkpoint_key="paper-shadow-primary-v1",
                identity=ID_A,
                payload=b"state-a",
                last_entry_id=None,
            )
            assert repo.replace_ledger_checkpoint(
                checkpoint_key="paper-shadow-primary-v1",
                expected_identity=ID_A,
                identity=ID_B,
                payload=b"state-b",
                last_entry_id="entry-a",
            )
            with pytest.raises(StoreError, match="LEDGER_CHECKPOINT_CAS_CONFLICT"):
                repo.replace_ledger_checkpoint(
                    checkpoint_key="paper-shadow-primary-v1",
                    expected_identity=ID_A,
                    identity=ID_E,
                    payload=b"state-c",
                    last_entry_id="entry-a",
                )
    finally:
        store.close()


def test_ledger_checkpoint_api_rejects_every_noncanonical_key(cwd_tmp: Path) -> None:
    store = _open("ledger-v4-fixed-key.db", cwd_tmp)
    try:
        with store.transaction() as repo:
            for operation in (
                lambda: repo.put_ledger_checkpoint(
                    checkpoint_key="arbitrary-account-path", identity=ID_A,
                    payload=b"state", last_entry_id=None,
                ),
                lambda: repo.get_ledger_checkpoint("arbitrary-account-path"),
                lambda: repo.replace_ledger_checkpoint(
                    checkpoint_key="arbitrary-account-path",
                    expected_identity=ID_A, identity=ID_B,
                    payload=b"state-b", last_entry_id=None,
                ),
            ):
                with pytest.raises(StoreError, match="^LEDGER_CHECKPOINT_KEY_INVALID$"):
                    operation()
            assert repo.get_ledger_checkpoint(LEDGER_CHECKPOINT_KEY) is None
    finally:
        store.close()


def test_recovery_rejects_offline_second_checkpoint_key(cwd_tmp: Path) -> None:
    name = "ledger-v4-offline-second-key.db"
    database = cwd_tmp / name
    store = _open(name, cwd_tmp)
    store.close()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO ledger_checkpoints "
            "(checkpoint_key, identity, payload, last_entry_id) VALUES (?, ?, ?, NULL)",
            ("arbitrary-account-path", ID_A, b"hostile"),
        )
    reopened = _open(name, cwd_tmp)
    try:
        with reopened.transaction() as repo:
            with pytest.raises(StoreError, match="^ROW_CORRUPT$") as error:
                repo.read_recovery_rows()
        assert error.value.__cause__ is None
        assert error.value.__context__ is None
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("first_kind", "second_kind"),
    [("ORDER", "ORDER"), ("CANCEL", "CANCEL"), ("ORDER", "CANCEL")],
)
def test_risk_receipt_same_predecessor_is_serialized_and_fresh_retry_does_not_fork(
    cwd_tmp: Path, first_kind: str, second_kind: str
) -> None:
    name = f"risk-race-{first_kind}-{second_kind}.db"
    first = _open(name, cwd_tmp)
    second = _open(name, cwd_tmp)
    first_subject = _hex(f"{first_kind}-subject-1")
    second_subject = _hex(f"{second_kind}-subject-2")
    first_receipt = _hex(f"{first_kind}-receipt-1")
    second_receipt = _hex(f"{second_kind}-receipt-2")

    def put(
        repo: ExecutionRepository,
        *,
        sequence: int,
        kind: str,
        subject: str,
        receipt: str,
        previous: str,
    ) -> bool:
        return repo.put_risk_transition_receipt(
            sequence=sequence,
            transition_kind=kind,
            subject_id=subject,
            receipt_id=receipt,
            previous_receipt_id=previous,
            risk_counter_key="paper-account:2026-08-09",
            predecessor_counter_identity=_hex(f"counter-{sequence - 1}"),
            projected_counter_identity=_hex(f"counter-{sequence}"),
            payload=f"{kind}-{sequence}".encode(),
        )

    try:
        with first.transaction() as repo:
            assert put(
                repo,
                sequence=1,
                kind=first_kind,
                subject=first_subject,
                receipt=first_receipt,
                previous="0" * 64,
            )
            with pytest.raises(StoreError, match="^TX_BUSY$"):
                with second.transaction():
                    pass
        with second.transaction() as repo:
            assert put(
                repo,
                sequence=2,
                kind=second_kind,
                subject=second_subject,
                receipt=second_receipt,
                previous=first_receipt,
            )
            tail = repo.get_risk_transition_tail()
            assert tail is not None and tail.sequence == 2
        with first.transaction() as repo:
            rows = repo.read_recovery_rows().risk_transition_receipts
        assert tuple(item.previous_receipt_id for item in rows) == (
            "0" * 64,
            first_receipt,
        )
    finally:
        second.close()
        first.close()


def test_v3_upgrade_adds_empty_ledger_tables_without_forging_context(
    cwd_tmp: Path,
) -> None:
    name = "legacy-v3-ledger.db"
    store = _open(name, cwd_tmp)
    with store.transaction() as repo:
        repo.put_command(command_id="cmd-a", identity=ID_A, payload=b"legacy")
        repo.put_order_aggregate(
            command_id="cmd-a", identity=ID_AGG, payload=b"aggregate"
        )
    store.close()
    database = cwd_tmp / name
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE risk_transition_receipts")
        conn.execute("DROP TABLE cancel_event_links")
        conn.execute("DROP TABLE cancel_deliveries")
        conn.execute("DROP TABLE cancel_commands")
        conn.execute("DROP TABLE ledger_checkpoints")
        conn.execute("DROP TABLE ledger_contexts")
        conn.execute("UPDATE schema_version SET version = 3")
    reopened = _open(name, cwd_tmp)
    try:
        assert reopened.schema_version() == CURRENT_SCHEMA_VERSION
        with reopened.transaction() as repo:
            rows = repo.read_recovery_rows()
        assert tuple(item.key for item in rows.commands) == ("cmd-a",)
        assert rows.ledger_contexts == ()
        assert rows.ledger_checkpoints == ()
    finally:
        reopened.close()


@pytest.mark.parametrize("subject", ["event", "aggregate", "delivery", "context"])
def test_recovery_rows_fail_closed_on_broken_join(
    cwd_tmp: Path, subject: str
) -> None:
    name = f"recovery-broken-{subject}.db"
    db = cwd_tmp / name
    store = _open(name, cwd_tmp)
    now = dt.datetime(2026, 8, 3, 1, tzinfo=UTC)
    with store.transaction() as repo:
        repo.put_command(command_id="cmd-a", identity=ID_A, payload=b"command")
        if subject != "context":
            repo.put_order_aggregate(
                command_id="cmd-a", identity=ID_AGG, payload=b"aggregate"
            )
        if subject == "event":
            repo.put_event(
                event_id="evt-a",
                command_id="cmd-a",
                identity=ID_E,
                payload=b"event",
            )
        elif subject in {"aggregate", "delivery"}:
            repo.put_outbox(outbox_key="obx-a", identity=ID_O_A, payload=b"outbox")
            repo.put_outbox_delivery(
                outbox_key="obx-a", command_id="cmd-a", available_at=now
            )
        else:
            repo.put_ledger_context(
                command_id="cmd-a", identity=ID_B, payload=b"context"
            )
    store.close()

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        if subject in {"event", "aggregate", "context"}:
            conn.execute("DELETE FROM commands WHERE command_id = 'cmd-a'")
        else:
            conn.execute("DELETE FROM outbox WHERE outbox_key = 'obx-a'")
        conn.commit()

    store = _open(name, cwd_tmp)
    try:
        with store.transaction() as repo:
            with pytest.raises(StoreError, match="^ROW_CORRUPT$") as exc_info:
                repo.read_recovery_rows()
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__context__ is None
    finally:
        store.close()


@pytest.mark.parametrize("subject", ["context", "checkpoint"])
def test_recovery_rows_fail_closed_on_hostile_ledger_row(
    cwd_tmp: Path, subject: str
) -> None:
    name = f"recovery-hostile-ledger-{subject}.db"
    database = cwd_tmp / name
    store = _open(name, cwd_tmp)
    with store.transaction() as repo:
        repo.put_command(command_id="cmd-a", identity=ID_A, payload=b"command")
        repo.put_ledger_context(
            command_id="cmd-a", identity=ID_B, payload=b"context"
        )
        repo.put_ledger_checkpoint(
            checkpoint_key="paper-shadow-primary-v1",
            identity=ID_A,
            payload=b"checkpoint",
            last_entry_id=None,
        )
    store.close()
    with sqlite3.connect(database) as conn:
        table = "ledger_contexts" if subject == "context" else "ledger_checkpoints"
        conn.execute(f"UPDATE {table} SET identity = 'HOSTILE'")
    reopened = _open(name, cwd_tmp)
    try:
        with reopened.transaction() as repo:
            with pytest.raises(StoreError, match="^ROW_CORRUPT$"):
                repo.read_recovery_rows()
    finally:
        reopened.close()


def test_recovery_rows_fail_closed_when_checkpoint_tail_is_missing(
    cwd_tmp: Path,
) -> None:
    name = "recovery-missing-ledger-tail.db"
    database = cwd_tmp / name
    store = _open(name, cwd_tmp)
    with store.transaction() as repo:
        repo.put_ledger_entry(entry_id="entry-a", identity=ID_E, payload=b"entry")
        repo.put_ledger_checkpoint(
            checkpoint_key="paper-shadow-primary-v1",
            identity=ID_A,
            payload=b"checkpoint",
            last_entry_id="entry-a",
        )
    store.close()
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM ledger_entries WHERE entry_id = 'entry-a'")
        conn.commit()
    reopened = _open(name, cwd_tmp)
    try:
        with reopened.transaction() as repo:
            with pytest.raises(StoreError, match="^ROW_CORRUPT$"):
                repo.read_recovery_rows()
    finally:
        reopened.close()


def test_recovery_rows_sqlite_error_is_stable_scrubbed_and_detached(
    cwd_tmp: Path,
) -> None:
    store = _open("recovery-hostile.db", cwd_tmp)
    inner = store._conn  # noqa: SLF001 - fault injection at SQLite boundary
    assert inner is not None
    sentinel = str(cwd_tmp / "TOKEN-recovery-hostile")

    class _FailRecoveryRead:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._inner = conn

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql.startswith("SELECT command_id, identity, payload FROM commands ORDER"):
                raise sqlite3.OperationalError(f"failed near {sentinel}")
            return self._inner.execute(sql, parameters)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    store._conn = _FailRecoveryRead(inner)  # type: ignore[assignment]  # noqa: SLF001
    try:
        with store.transaction() as repo:
            with pytest.raises(
                StoreError, match="^RECOVERY_SNAPSHOT_READ_FAILED$"
            ) as exc_info:
                repo.read_recovery_rows()
        _assert_scrubbed_store_error(
            exc_info.value,
            code="RECOVERY_SNAPSHOT_READ_FAILED",
            injected=sentinel,
        )
    finally:
        store.close()


def test_v5_cancel_command_delivery_round_trip_and_strict_lease_boundary(
    cwd_tmp: Path,
) -> None:
    store = _open("cancel-v5-round-trip.db", cwd_tmp)
    command_id = _hex("cancel-target")
    cancel_id = _hex("cancel-request")
    policy_id = _hex("cancel-policy")
    now = dt.datetime(2026, 8, 2, 2, tzinfo=UTC)
    try:
        with store.transaction() as repo:
            repo.put_command(
                command_id=command_id, identity=command_id, payload=b"order-wire"
            )
            assert repo.put_cancel_command(
                cancel_id=cancel_id,
                command_id=command_id,
                identity=cancel_id,
                payload=b"cancel-wire",
                risk_counter_key="paper:2026-08-02",
                risk_policy_identity=policy_id,
            )
            assert not repo.put_cancel_command(
                cancel_id=cancel_id,
                command_id=command_id,
                identity=cancel_id,
                payload=b"cancel-wire",
                risk_counter_key="paper:2026-08-02",
                risk_policy_identity=policy_id,
            )
            assert repo.put_cancel_delivery(
                cancel_id=cancel_id, command_id=command_id, available_at=now
            )
            claimed = repo.claim_cancel_delivery(
                cancel_id=cancel_id,
                worker_id="cancel-worker-1",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )
        with pytest.raises(StoreError, match="^CANCEL_DELIVERY_NOT_CLAIMABLE$"):
            with store.transaction() as repo:
                repo.claim_cancel_delivery(
                    cancel_id=cancel_id,
                    worker_id="cancel-worker-2",
                    now=now + dt.timedelta(minutes=1),
                    lease_until=now + dt.timedelta(minutes=2),
                )
        with store.transaction() as repo:
            reclaimed = repo.claim_cancel_delivery(
                cancel_id=cancel_id,
                worker_id="cancel-worker-2",
                now=now + dt.timedelta(minutes=1, microseconds=1),
                lease_until=now + dt.timedelta(minutes=2),
            )
            assert reclaimed.attempt_count == claimed.attempt_count + 1
            assert repo.mark_cancel_unknown(
                cancel_id=cancel_id,
                lease_owner="cancel-worker-2",
                expected_attempt=reclaimed.attempt_count,
                unknown_at=now + dt.timedelta(minutes=1, seconds=1),
                error_code="GATEWAY_UNKNOWN",
            )
            terminal = repo.get_cancel_delivery(cancel_id)
        assert terminal is not None
        assert terminal.state is OutboxDeliveryState.UNKNOWN
        assert terminal.last_error_code == "GATEWAY_UNKNOWN"
    finally:
        store.close()


def test_v5_cancel_not_sent_returns_to_explicit_retry_without_resetting_attempt(
    cwd_tmp: Path,
) -> None:
    store = _open("cancel-v5-not-sent.db", cwd_tmp)
    command_id = _hex("cancel-not-sent-target")
    cancel_id = _hex("cancel-not-sent")
    now = dt.datetime(2026, 8, 2, 3, tzinfo=UTC)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id=command_id, identity=command_id, payload=b"o")
            repo.put_cancel_command(
                cancel_id=cancel_id,
                command_id=command_id,
                identity=cancel_id,
                payload=b"c",
                risk_counter_key="paper:2026-08-02",
                risk_policy_identity=_hex("policy"),
            )
            repo.put_cancel_delivery(
                cancel_id=cancel_id, command_id=command_id, available_at=now
            )
            first = repo.claim_cancel_delivery(
                cancel_id=cancel_id,
                worker_id="worker",
                now=now,
                lease_until=now + dt.timedelta(minutes=1),
            )
            repo.mark_cancel_not_sent(
                cancel_id=cancel_id,
                lease_owner="worker",
                expected_attempt=first.attempt_count,
                retry_at=now + dt.timedelta(seconds=1),
            )
            pending = repo.get_cancel_delivery(cancel_id)
            assert pending is not None
            assert pending.state is OutboxDeliveryState.PENDING
            assert pending.attempt_count == 1
            assert pending.last_error_code == "CANCEL_GATEWAY_NOT_SENT"
            second = repo.claim_cancel_delivery(
                cancel_id=cancel_id,
                worker_id="worker",
                now=now + dt.timedelta(seconds=1),
                lease_until=now + dt.timedelta(minutes=1),
            )
        assert second.attempt_count == 2
    finally:
        store.close()


def test_v5_recovery_rows_close_cancel_event_link_and_reject_orphan(
    cwd_tmp: Path,
) -> None:
    name = "cancel-v5-recovery.db"
    database = cwd_tmp / name
    store = _open(name, cwd_tmp)
    command_id = _hex("cancel-link-target")
    cancel_id = _hex("cancel-link")
    event_id = _hex("cancel-event")
    now = dt.datetime(2026, 8, 2, 4, tzinfo=UTC)
    try:
        with store.transaction() as repo:
            repo.put_command(command_id=command_id, identity=command_id, payload=b"o")
            repo.put_event(
                event_id=event_id,
                command_id=command_id,
                identity=event_id,
                payload=b"e",
            )
            repo.put_cancel_command(
                cancel_id=cancel_id,
                command_id=command_id,
                identity=cancel_id,
                payload=b"c",
                risk_counter_key="paper:2026-08-02",
                risk_policy_identity=_hex("policy"),
            )
            repo.put_cancel_delivery(
                cancel_id=cancel_id, command_id=command_id, available_at=now
            )
            assert repo.put_cancel_event_link(cancel_id=cancel_id, event_id=event_id)
            assert not repo.put_cancel_event_link(cancel_id=cancel_id, event_id=event_id)
            rows = repo.read_recovery_rows()
        assert rows.cancel_commands[0].cancel_id == cancel_id
        assert rows.cancel_deliveries[0].cancel_id == cancel_id
        assert rows.cancel_event_links[0].command_id == command_id
    finally:
        store.close()
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM events WHERE event_id=?", (event_id,))
    reopened = _open(name, cwd_tmp)
    try:
        with pytest.raises(StoreError, match="^ROW_CORRUPT$"):
            with reopened.transaction() as repo:
                repo.read_recovery_rows()
    finally:
        reopened.close()


def test_v8_approval_receipt_round_trip_is_raw_and_exactly_idempotent(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8.db", cwd_tmp)
    receipt = _approval()
    raw = encode_approval_receipt(receipt)
    verified = verify_approval_receipt_for_store(
        raw, APPROVAL_SECRET, source_identities=APPROVAL_SOURCES
    )
    try:
        with store.transaction() as repo:
            assert repo.put_verified_approval_receipt(verified)
            assert not repo.put_verified_approval_receipt(verified)
            stored = repo.get_approval_receipt(receipt.receipt_id)
            assert stored is not None
            assert stored.payload == raw
            assert stored.receipt_id == receipt.receipt_id
            assert stored.plan_identity == receipt.plan_identity
            assert not hasattr(stored, "receipt")
            assert not hasattr(stored, "_proof")
            recovery = repo.read_recovery_rows()
            assert recovery.approval_receipts == (stored,)
    finally:
        store.close()


def test_v8_nonempty_approval_close_reopen_requires_caller_reverification(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8-reopen.db", cwd_tmp)
    receipt = _approval("reopen-approval", plan="reopen-plan")
    raw = encode_approval_receipt(receipt)
    try:
        with store.transaction() as repo:
            assert repo.put_verified_approval_receipt(
                verify_approval_receipt_for_store(
                    raw, APPROVAL_SECRET, source_identities=APPROVAL_SOURCES
                )
            )
    finally:
        store.close()

    recovered: StoredApprovalReceipt | None = None
    reopened = _open("approval-v8-reopen.db", cwd_tmp)
    try:
        with reopened.transaction() as repo:
            recovered = repo.get_approval_receipt(receipt.receipt_id)
            assert recovered is not None
            assert recovered.payload == raw
            assert not hasattr(recovered, "receipt")
            assert not hasattr(recovered, "_proof")
            assert repo.read_recovery_rows().approval_receipts == (recovered,)
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(recovered)
    finally:
        reopened.close()

    assert recovered is not None
    reverified = verify_approval_receipt_for_store(
        recovered.payload,
        APPROVAL_SECRET,
        source_identities=APPROVAL_SOURCES,
    )
    reopened = _open("approval-v8-reopen.db", cwd_tmp)
    try:
        with reopened.transaction() as repo:
            assert not repo.put_verified_approval_receipt(reverified)
    finally:
        reopened.close()


def test_v8_approval_store_requires_credential_free_handoff_and_rejects_index_drift(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8-index-drift.db", cwd_tmp)
    receipt = _approval()
    raw = encode_approval_receipt(receipt)
    verified = verify_approval_receipt_for_store(
        raw, APPROVAL_SECRET, source_identities=APPROVAL_SOURCES
    )
    try:
        with store.transaction() as repo:
            assert not hasattr(repo, "put_approval_receipt")
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(raw)

            tampered = _canonical_bytes(
                {**json.loads(raw.decode("utf-8")), "operator_id": "operator-drift"}
            )
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_INDEX_MISMATCH$"):
                repo.put_verified_approval_receipt(
                    _corrupt_handoff(  # noqa: SLF001 - proof replay adversary
                        verified, tampered, proof=verified._proof
                    )
                )

            other = _approval("proof-replay", plan="proof-replay-plan")
            other_verified = verify_approval_receipt_for_store(
                encode_approval_receipt(other),
                APPROVAL_SECRET,
                source_identities=APPROVAL_SOURCES,
            )
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(
                    _corrupt_handoff(
                        other_verified,
                        other_verified.payload,
                        proof=verified._proof,  # noqa: SLF001 - proof replay adversary
                    )
                )
            assert repo.get_approval_receipt(receipt.receipt_id) is None
    finally:
        store.close()


def test_v8_hmac_invalid_self_consistent_payload_has_no_public_store_bypass(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8-forgery.db", cwd_tmp)
    receipt = _approval()
    raw = encode_approval_receipt(receipt)
    verified = verify_approval_receipt_for_store(
        raw, APPROVAL_SECRET, source_identities=APPROVAL_SOURCES
    )
    forged = _self_consistent_hmac_forgery(raw)
    forged_receipt = decode_approval_receipt(forged)
    try:
        with pytest.raises(ApprovalReceiptError, match="^APPROVAL_RECEIPT_SIGNATURE_INVALID$"):
            verify_approval_receipt_for_store(
                forged, APPROVAL_SECRET, source_identities=APPROVAL_SOURCES
            )
        with store.transaction() as repo:
            assert not hasattr(repo, "put_approval_receipt")
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(forged)
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(
                    _corrupt_handoff(
                        verified, forged, receipt=forged_receipt
                    )
                )
            assert repo.get_approval_receipt(receipt.receipt_id) is None
    finally:
        store.close()


def test_v8_raw_index_candidate_has_no_repository_persistence_bypass(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8-candidate-bypass.db", cwd_tmp)
    receipt = _approval()
    forged_raw = _self_consistent_hmac_forgery(encode_approval_receipt(receipt))
    forged = decode_approval_receipt(forged_raw)
    candidate = StoredApprovalReceipt(
        receipt_id=forged.receipt_id,
        identity=forged.receipt_id,
        schema_version=forged.schema_version,
        classification=forged.classification,
        credential_kind=forged.credential_kind,
        credential_id=forged.credential_id,
        operator_id=forged.operator_id,
        session_date=forged.session_date,
        action=forged.action,
        plan_identity=forged.plan_identity,
        challenge_identity=forged.challenge_identity,
        store_recovery_identity=forged.store_recovery_identity,
        source_identities_digest=forged.source_identities_digest,
        issued_at=forged.issued_at,
        nonce=forged.nonce,
        payload=forged_raw,
    )
    try:
        with store.transaction() as repo:
            assert not hasattr(repo, "_put_approval_receipt_candidate")
            assert not callable(
                getattr(ExecutionRepository, "_put_approval_receipt_candidate", None)
            )
            with pytest.raises(StoreError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
                repo.put_verified_approval_receipt(candidate)
            assert repo.query_approval_receipts() == ()
    finally:
        store.close()


def test_v8_approval_business_key_conflict_fails_without_partial_write(
    cwd_tmp: Path,
) -> None:
    store = _open("approval-v8-conflicts.db", cwd_tmp)
    first = _approval()
    second_same_plan = _approval("store-approval-2")
    try:
        with store.transaction() as repo:
            assert repo.put_verified_approval_receipt(
                verify_approval_receipt_for_store(
                    encode_approval_receipt(first),
                    APPROVAL_SECRET,
                    source_identities=APPROVAL_SOURCES,
                )
            )
            with pytest.raises(
                IdempotencyConflict, match="^APPROVAL_BUSINESS_KEY_CONFLICT$"
            ):
                repo.put_verified_approval_receipt(
                    verify_approval_receipt_for_store(
                        encode_approval_receipt(second_same_plan),
                        APPROVAL_SECRET,
                        source_identities=APPROVAL_SOURCES,
                    )
                )
            assert len(repo.query_approval_receipts()) == 1
    finally:
        store.close()


def test_v8_recovery_fails_closed_on_index_payload_drift(cwd_tmp: Path) -> None:
    database = cwd_tmp / "approval-v8-corrupt.db"
    store = _open("approval-v8-corrupt.db", cwd_tmp)
    receipt = _approval()
    try:
        with store.transaction() as repo:
            repo.put_verified_approval_receipt(
                verify_approval_receipt_for_store(
                    encode_approval_receipt(receipt),
                    APPROVAL_SECRET,
                    source_identities=APPROVAL_SOURCES,
                )
            )
    finally:
        store.close()

    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE approval_receipts SET operator_id = ? WHERE receipt_id = ?",
            ("operator-drift", receipt.receipt_id),
        )
        conn.commit()

    reopened = _open("approval-v8-corrupt.db", cwd_tmp)
    try:
        with reopened.transaction() as repo:
            with pytest.raises(StoreError, match="^ROW_CORRUPT$"):
                repo.read_recovery_rows()
    finally:
        reopened.close()


def test_v7_database_upgrade_adds_only_approval_substrate_and_preserves_rows(
    cwd_tmp: Path,
) -> None:
    database = cwd_tmp / "approval-v7-upgrade.db"
    store = _open("approval-v7-upgrade.db", cwd_tmp)
    with store.transaction() as repo:
        repo.put_command(command_id="legacy-command", identity=ID_A, payload=b"legacy")
    store.close()

    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE approval_receipts")
        conn.execute(
            "UPDATE schema_version SET version = 7, status = 'ready' "
            "WHERE singleton = 1"
        )
        conn.commit()

    reopened = _open("approval-v7-upgrade.db", cwd_tmp)
    try:
        assert reopened.schema_version() == CURRENT_SCHEMA_VERSION
        with reopened.transaction() as repo:
            assert repo.get_command("legacy-command") is not None
            assert repo.read_recovery_rows().approval_receipts == ()
    finally:
        reopened.close()
