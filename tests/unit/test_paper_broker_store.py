"""RUN-0B1 independent durable PAPER broker store contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.domain.enums import Currency, Market
from quant.execution.contracts import CashBalance, build_account_snapshot
from quant.execution.paper_broker_store import (
    PaperBrokerStoreError,
    build_formal_paper_broker_policy_descriptor,
    build_paper_account_descriptor,
    build_paper_broker_policy_descriptor,
    initialize_paper_broker_store,
    open_verified_paper_broker_store,
)
import quant.execution.paper_broker_store as broker_store_module
from quant.execution.paper_broker_binding import (
    VerifiedFormalPaperBrokerPolicyBinding,
)
from quant.execution import paper_broker_binding as binding_module
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    paper_execution_cost_schedule_identity,
)
from quant.execution import paper_policy as policy_module

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 9, 1, tzinfo=UTC)
_FROZEN_FORMAL_COST_SCHEDULE_IDENTITY = (
    "9864f09ccbc7be9f30299f74cb4659665765194776844ed36914815a87749f7a"
)
_FROZEN_DEVELOPMENT_COST_SCHEDULE_IDENTITY = (
    "464bc03f41dfe131dad396995b047c1365b2c6b403e991cbffa1ac1da7b7a1a7"
)
_FROZEN_DEVELOPMENT_DESCRIPTOR_IDENTITY = (
    "9dd4dcb507578098ff946a2e57607ff03840af0f0b482b9283b3126233c12db1"
)


def _schedule():
    return build_execution_cost_schedule(
        selector="paper-cost-v1",
        periods=(ExecutionCostPeriod(Market.SH, dt.date(2026, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0.0005"), Decimal("0.00001"), Currency.CNY),),
    )


def _inputs():
    snapshot = build_account_snapshot(
        as_of=NOW,
        positions=(),
        cash=(CashBalance(Currency.CNY, Decimal("100000"), Decimal("100000"), Decimal(0), Decimal(0)),),
    )
    account = build_paper_account_descriptor(account_label="paper-main", created_at=NOW, base_currency=Currency.CNY, initial_snapshot=snapshot)
    policy = build_paper_broker_policy_descriptor(
        adapter_policy_version="adapter-v1", fill_policy_version="fill-v1",
        fault_policy_version="fault-v1", finality_policy_version="eod-v1",
        cost_schedule=_schedule(), fx_snapshot=None,
    )
    return account, policy


def _store(tmp_path: Path):
    root = tmp_path / "broker"
    oms = tmp_path / "oms"
    root.mkdir()
    oms.mkdir()
    account, policy = _inputs()
    return initialize_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms, account=account, policy=policy, created_at=NOW), oms


def test_descriptor_is_stable_and_reopen_fresh(tmp_path: Path) -> None:
    store, oms = _store(tmp_path)
    first = store.gateway_identity
    reopened = open_verified_paper_broker_store(root=tmp_path / "broker", database_filename="paper.sqlite3", oms_store_path=oms)
    assert reopened.gateway_identity == first
    assert reopened.account_descriptor.account_id != reopened.account_descriptor.initial_snapshot.snapshot_id


def test_rejects_oms_ancestor_and_relative_root(tmp_path: Path) -> None:
    account, policy = _inputs()
    root = tmp_path / "broker"
    root.mkdir()
    with pytest.raises(PaperBrokerStoreError):
        initialize_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=tmp_path, account=account, policy=policy, created_at=NOW)
    with pytest.raises(PaperBrokerStoreError):
        initialize_paper_broker_store(root=Path("relative"), database_filename="paper.sqlite3", oms_store_path=tmp_path / "oms", account=account, policy=policy, created_at=NOW)


def test_copy_root_and_descriptor_tamper_fail_closed(tmp_path: Path) -> None:
    store, oms = _store(tmp_path)
    copied = tmp_path / "copied"
    shutil.copytree(tmp_path / "broker", copied)
    with pytest.raises(PaperBrokerStoreError):
        open_verified_paper_broker_store(root=copied, database_filename="paper.sqlite3", oms_store_path=oms)

    descriptor = tmp_path / "broker" / "store-instance.json"
    payload = bytearray(descriptor.read_bytes())
    payload[-2] = ord("0") if payload[-2] != ord("0") else ord("1")
    descriptor.write_bytes(payload)
    with pytest.raises(PaperBrokerStoreError):
        store.verify_fresh()


def test_policy_and_account_identities_reject_forgery() -> None:
    account, policy = _inputs()
    assert len(account.account_id) == 64
    assert len(policy.descriptor_identity) == 64
    assert policy.cost_schedule_identity != hashlib.sha256(b"not-the-policy").hexdigest()
    with pytest.raises(TypeError):
        build_paper_broker_policy_descriptor(
            adapter_policy_version="example-adapter",
            fill_policy_version="example-fill",
            fault_policy_version="example-fault",
            finality_policy_version="example-finality",
            cost_schedule=_schedule(),
            fx_snapshot=None,
            classification="formal",  # type: ignore[call-arg]
        )


def test_direct_formal_policy_value_cannot_initialize_store(tmp_path: Path) -> None:
    account, policy = _inputs()
    forged = replace(policy, classification="formal")  # type: ignore[arg-type]
    root, oms = tmp_path / "broker", tmp_path / "oms"
    root.mkdir()
    oms.mkdir()
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_POLICY_INVALID"):
        initialize_paper_broker_store(
            root=root, database_filename="paper.sqlite3", oms_store_path=oms,
            account=account, policy=forged, created_at=NOW,
        )


def test_account_state_and_checkpoint_tamper_fail_closed(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    database = tmp_path / "broker" / "paper.sqlite3"
    conn = sqlite3.connect(database)
    try:
        conn.execute("UPDATE checkpoint SET state_digest=?", ("0" * 64,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_JOURNAL_INVALID"):
        store.verify_fresh()


def test_database_file_replacement_is_identity_drift(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    database = tmp_path / "broker" / "paper.sqlite3"
    replacement = tmp_path / "replacement.sqlite3"
    shutil.copy2(database, replacement)
    try:
        database.unlink()
    except PermissionError:
        # Windows guard deliberately denies delete sharing while the store is open.
        store.close()
        database.unlink()
    replacement.rename(database)
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_IDENTITY_DRIFT") as caught:
        open_verified_paper_broker_store(
            root=tmp_path / "broker",
            database_filename="paper.sqlite3",
            oms_store_path=tmp_path / "oms",
        )
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_initial_store_is_not_eod_final(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    assert store.evidence_finality() == "INTRADAY"


def test_exact_zero_order_finality_is_bound_and_idempotent(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    session_date = NOW.date()
    finalized_at = NOW + dt.timedelta(minutes=5)
    closure_identity = hashlib.sha256(b"exact-order-semantic-closure").hexdigest()

    store.record_zero_broker_command_session_finality(
        session_date=session_date,
        finalized_at=finalized_at,
        order_semantic_closure_identity=closure_identity,
    )
    store.record_zero_broker_command_session_finality(
        session_date=session_date,
        finalized_at=finalized_at,
        order_semantic_closure_identity=closure_identity,
    )

    marker = store.read_session_finality(session_date=session_date)
    assert marker is not None
    assert marker.session_date == session_date
    assert marker.finalized_at == finalized_at
    assert marker.order_semantic_closure_identity == closure_identity
    snapshot = store.read_evidence_snapshot(session_date=session_date)
    assert snapshot[3] == NOW
    assert snapshot[-1] == "END_OF_DAY"
    assert store.evidence_finality() == "INTRADAY"

    with pytest.raises(
        PaperBrokerStoreError, match="^PAPER_BROKER_FINALITY_CONFLICT$"
    ):
        store.record_zero_broker_command_session_finality(
            session_date=session_date,
            finalized_at=NOW,
            order_semantic_closure_identity="f" * 64,
        )


def test_zero_order_finality_decoder_rejects_numeric_identity() -> None:
    payload = json.dumps(
        {
            "finalized_at": NOW.isoformat().replace("+00:00", "Z"),
            "order_semantic_closure_identity": int("1" * 64),
            "schema_version": "paper-zero-broker-command-session-finality-v1",
            "session_date": NOW.date().isoformat(),
        }
    ).encode()

    with pytest.raises(
        PaperBrokerStoreError, match="^PAPER_BROKER_JOURNAL_INVALID$"
    ):
        broker_store_module._decode_finality_payload(payload)


def test_explicit_close_maps_failure_but_attempts_every_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _store(tmp_path)
    handles = store._guard_handles
    original = broker_store_module._guard_close
    calls: list[tuple[str, int]] = []

    def fail(handle: tuple[str, int]) -> None:
        calls.append(handle)
        raise OSError("HOSTILE_CLOSE_PATH_MARKER")

    monkeypatch.setattr(broker_store_module, "_guard_close", fail)
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_CLOSE_FAILED") as caught:
        store.close()
    assert len(calls) == len(handles)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    monkeypatch.setattr(broker_store_module, "_guard_close", original)
    for handle in handles:
        original(handle)


def test_destructor_ignores_public_close_failure_without_unraisable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _store(tmp_path)
    unraisable: list[object] = []

    def hostile_close() -> None:
        raise RuntimeError("HOSTILE_DESTRUCTOR_PATH_MARKER")

    monkeypatch.setattr(store, "close", hostile_close)
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    store.__del__()
    assert unraisable == []
    assert store._guard_handles == ()


def test_fresh_subprocess_without_explicit_close_has_clean_exit(
    tmp_path: Path,
) -> None:
    child_root = tmp_path / "child"
    child_oms = tmp_path / "child-oms"
    script = r'''
import datetime as dt
import os
from decimal import Decimal
from pathlib import Path
from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.domain.enums import Currency, Market
from quant.execution.contracts import CashBalance, build_account_snapshot
from quant.execution.paper_broker_store import build_paper_account_descriptor, build_paper_broker_policy_descriptor, initialize_paper_broker_store
root = Path(os.environ["PAPER_BROKER_CHILD_ROOT"])
oms = Path(os.environ["PAPER_BROKER_CHILD_OMS"])
root.mkdir()
oms.mkdir()
now = dt.datetime(2026, 8, 9, 1, tzinfo=dt.timezone.utc)
snapshot = build_account_snapshot(as_of=now, positions=(), cash=(CashBalance(Currency.CNY, Decimal("100000"), Decimal("100000"), Decimal(0), Decimal(0)),))
account = build_paper_account_descriptor(account_label="paper-child", created_at=now, base_currency=Currency.CNY, initial_snapshot=snapshot)
schedule = build_execution_cost_schedule(selector="paper-cost-v1", periods=(ExecutionCostPeriod(Market.SH, dt.date(2026, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0.0005"), Decimal("0.00001"), Currency.CNY),))
policy = build_paper_broker_policy_descriptor(adapter_policy_version="adapter-v1", fill_policy_version="fill-v1", fault_policy_version="fault-v1", finality_policy_version="eod-v1", cost_schedule=schedule, fx_snapshot=None)
STORE_LEFT_OPEN = initialize_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms, account=account, policy=policy, created_at=now)
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    environment["PAPER_BROKER_CHILD_ROOT"] = str(child_root)
    environment["PAPER_BROKER_CHILD_OMS"] = str(child_oms)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_unconfigured_broker_store_unchanged_without_barrier(tmp_path: Path) -> None:
    account, policy = _inputs()
    root = tmp_path / "broker"
    oms = tmp_path / "oms"
    root.mkdir()
    oms.mkdir()
    store = initialize_paper_broker_store(
        root=root,
        database_filename="paper.sqlite3",
        oms_store_path=oms,
        account=account,
        policy=policy,
        created_at=NOW,
    )
    try:
        assert store.session_barrier_enabled() is False
        assert store.evidence_finality() == "INTRADAY"
    finally:
        store.close()


def test_broker_barrier_identity_mismatch_rejected(tmp_path: Path) -> None:
    from quant.execution.session_barrier import build_session_barrier_capability
    from quant.execution.store import ExecutionStore

    account, policy = _inputs()
    broker_root = tmp_path / "broker"
    oms_root = tmp_path / "oms-root"
    lock_root = tmp_path / "lock"
    broker_root.mkdir()
    oms_root.mkdir()
    lock_root.mkdir()
    broker = initialize_paper_broker_store(
        root=broker_root,
        database_filename="paper.sqlite3",
        oms_store_path=oms_root / "x",
        account=account,
        policy=policy,
        created_at=NOW,
    )
    cap = build_session_barrier_capability(
        barrier_epoch=hashlib.sha256(b"e").hexdigest(),
        session_date=dt.date(2026, 8, 25),
        account_identity=hashlib.sha256(b"wrong-account").hexdigest(),
        oms_store_identity=hashlib.sha256(b"oms").hexdigest(),
        broker_store_identity=broker.descriptor.descriptor_identity,
        gateway_identity=broker.gateway_identity,
        config_identity=hashlib.sha256(b"cfg").hexdigest(),
        lock_root=lock_root,
    )
    oms = ExecutionStore.open(
        "sqlite:///oms.db",
        trusted_root=oms_root,
        session_barrier=cap,
        initialize_barrier=True,
        barrier_created_at=NOW,
    )
    try:
        assert not hasattr(oms, "barrier_oms_connection")
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_IDENTITY_DRIFT"):
            broker.bind_session_barrier(
                cap, oms_handle=oms.session_barrier_oms_handle()
            )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_OMS_HANDLE_INVALID"):
            broker.bind_session_barrier(cap, oms_handle=lambda: None)
        with pytest.raises(TypeError):
            broker.bind_session_barrier(  # type: ignore[call-arg]
                cap, oms_conn_provider=lambda: None
            )
    finally:
        oms.close()
        broker.close()


def test_broker_all_writers_require_open_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writers take real OPEN lease at depth exact 1; no public gateway_identity under hold."""
    from contextlib import contextmanager

    from quant.execution.gateways.contracts import DispatchCertainty
    from quant.execution.session_barrier import build_session_barrier_capability
    from quant.execution.store import ExecutionStore

    account, policy = _inputs()
    broker_root = tmp_path / "broker2"
    oms_root = tmp_path / "oms-root2"
    lock_root = tmp_path / "lock2"
    broker_root.mkdir()
    oms_root.mkdir()
    lock_root.mkdir()
    broker = initialize_paper_broker_store(
        root=broker_root,
        database_filename="paper.sqlite3",
        oms_store_path=oms_root / "x",
        account=account,
        policy=policy,
        created_at=NOW,
    )
    # Public gateway_identity (fresh) only before lease observation is armed.
    gateway_identity = broker.gateway_identity
    cap = build_session_barrier_capability(
        barrier_epoch=hashlib.sha256(b"e2").hexdigest(),
        session_date=dt.date(2026, 8, 25),
        account_identity=broker.account_descriptor.descriptor_identity,
        oms_store_identity=hashlib.sha256(b"oms2").hexdigest(),
        broker_store_identity=broker.descriptor.descriptor_identity,
        gateway_identity=gateway_identity,
        config_identity=hashlib.sha256(b"cfg2").hexdigest(),
        lock_root=lock_root,
    )
    oms = ExecutionStore.open(
        "sqlite:///oms2.db",
        trusted_root=oms_root,
        session_barrier=cap,
        initialize_barrier=True,
        barrier_created_at=NOW,
    )
    try:
        broker.bind_session_barrier(cap, oms_handle=oms.session_barrier_oms_handle())
        assert broker.session_barrier_enabled() is True
        assert type(broker._bound_gateway_identity) is str
        assert broker._bound_gateway_identity == gateway_identity
        session = dt.date(2026, 8, 25)
        closure = hashlib.sha256(b"closure").hexdigest()

        lease_events: list[tuple[str, int]] = []
        depth = {"n": 0}
        public_gw_during_lease: list[str] = []
        real_hold = broker_store_module.hold_open_write_lease
        orig_gateway = broker_store_module.PaperBrokerStore.gateway_identity

        @contextmanager
        def observe_hold(*args: object, **kwargs: object):
            depth["n"] += 1
            lease_events.append(("enter", depth["n"]))
            assert depth["n"] == 1, (
                "hold_open_write_lease re-entered; writer depth must be exact 1"
            )
            try:
                with real_hold(*args, **kwargs) as lease:
                    yield lease
            finally:
                lease_events.append(("exit", depth["n"]))
                depth["n"] -= 1

        def tracking_gateway_identity(self: object) -> str:
            if depth["n"] > 0:
                public_gw_during_lease.append("public_gateway_identity")
            return orig_gateway.__get__(self, type(self))

        monkeypatch.setattr(broker_store_module, "hold_open_write_lease", observe_hold)
        monkeypatch.setattr(
            broker_store_module.PaperBrokerStore,
            "gateway_identity",
            property(tracking_gateway_identity),
        )

        def _clear_lease_events() -> None:
            lease_events.clear()
            public_gw_during_lease.clear()

        def _enter_depths() -> list[int]:
            return [d for kind, d in lease_events if kind == "enter"]

        def _assert_writer_depth_exact_1() -> None:
            enters = _enter_depths()
            assert enters, "writer path must acquire real OPEN lease"
            assert all(d == 1 for d in enters)
            assert max(enters) == 1
            assert depth["n"] == 0
            assert public_gw_during_lease == [], (
                "must not call public gateway_identity while holding lease"
            )

        # Observer alone must not change hold / must not enter.
        assert _enter_depths() == []
        assert depth["n"] == 0
        assert public_gw_during_lease == []

        # OPEN record writer: depth exact 1; no public gateway under hold.
        _clear_lease_events()
        broker.record_zero_broker_command_session_finality(
            session_date=session,
            finalized_at=NOW,
            order_semantic_closure_identity=closure,
        )
        marker = broker.read_session_finality(session_date=session)
        assert marker is not None
        _assert_writer_depth_exact_1()

        # Anchor checkpoint UPDATE under OPEN (depth-0 verify_fresh → _sync_anchors).
        _clear_lease_events()
        db_path = broker_root / "paper.sqlite3"
        with sqlite3.connect(db_path) as raw:
            seq = raw.execute(
                "SELECT sequence,anchored_sequence FROM checkpoint WHERE singleton=1"
            ).fetchone()
            assert seq is not None
            if int(seq[0]) > 0:
                raw.execute(
                    "UPDATE checkpoint SET anchored_sequence=0 WHERE singleton=1"
                )
                raw.commit()
                broker.verify_fresh()
                assert _enter_depths() == [1]
                assert depth["n"] == 0
                assert public_gw_during_lease == []

        # persist_operation / update-path probe under OPEN.
        _clear_lease_events()
        with pytest.raises(PaperBrokerStoreError):
            broker.persist_operation(
                operation_id="op-open-probe",
                kind="SUBMIT",
                dispatch_attempt=1,
                request_payload=b"{}",
                certainty=DispatchCertainty.SENT,
                result_payload=b"{}",
                command_payload=b"{}",
                callbacks=(),
                account=account.initial_snapshot,
                predecessor_state_digest="0" * 64,
            )
        _assert_writer_depth_exact_1()

        # finalize_session under OPEN.
        _clear_lease_events()
        try:
            broker.finalize_session(session_date=session, finalized_at=NOW)
        except PaperBrokerStoreError:
            pass
        _assert_writer_depth_exact_1()

        # Bound raw identity drift vs lease capability must fail-closed.
        _clear_lease_events()
        saved_bound = broker._bound_gateway_identity
        broker._bound_gateway_identity = "f" * 64
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_IDENTITY_DRIFT"):
            broker.record_zero_broker_command_session_finality(
                session_date=dt.date(2026, 8, 26),
                finalized_at=NOW + dt.timedelta(hours=1),
                order_semantic_closure_identity=hashlib.sha256(b"drift").hexdigest(),
            )
        assert max(_enter_depths() or [1]) == 1
        assert public_gw_during_lease == []
        broker._bound_gateway_identity = saved_bound

        oms.transition_session_barrier_to_closing(
            nonce="broker-close", now=NOW + dt.timedelta(seconds=1)
        )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSING"):
            broker.record_zero_broker_command_session_finality(
                session_date=dt.date(2026, 8, 26),
                finalized_at=NOW + dt.timedelta(days=1),
                order_semantic_closure_identity=hashlib.sha256(b"c2").hexdigest(),
            )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSING"):
            broker.finalize_session(
                session_date=dt.date(2026, 8, 26),
                finalized_at=NOW + dt.timedelta(days=1),
            )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSING"):
            broker.persist_operation(
                operation_id="op-closing",
                kind="SUBMIT",
                dispatch_attempt=1,
                request_payload=b"{}",
                certainty=DispatchCertainty.SENT,
                result_payload=b"{}",
                command_payload=b"{}",
                callbacks=(),
                account=account.initial_snapshot,
                predecessor_state_digest="0" * 64,
            )
        with sqlite3.connect(db_path) as raw:
            seq = raw.execute(
                "SELECT sequence FROM checkpoint WHERE singleton=1"
            ).fetchone()
            assert seq is not None and int(seq[0]) >= 0
            raw.execute("UPDATE checkpoint SET anchored_sequence=0 WHERE singleton=1")
            raw.commit()
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSING"):
            broker.verify_fresh()

        token = oms.read_session_barrier_row()
        close_token = getattr(token, "close_token_identity")
        oms.transition_session_barrier_to_closed(
            close_token_identity=close_token,
            now=NOW + dt.timedelta(seconds=2),
        )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSED"):
            broker.persist_operation(
                operation_id="op-closed",
                kind="SUBMIT",
                dispatch_attempt=1,
                request_payload=b"{}",
                certainty=DispatchCertainty.SENT,
                result_payload=b"{}",
                command_payload=b"{}",
                callbacks=(),
                account=account.initial_snapshot,
                predecessor_state_digest="0" * 64,
            )
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSED"):
            broker.finalize_session(
                session_date=dt.date(2026, 8, 27),
                finalized_at=NOW + dt.timedelta(days=2),
            )
        with sqlite3.connect(db_path) as raw:
            raw.execute("UPDATE checkpoint SET anchored_sequence=0 WHERE singleton=1")
            raw.commit()
        with pytest.raises(PaperBrokerStoreError, match="BARRIER_STATE_CLOSED"):
            broker.verify_fresh()
    finally:
        oms.close()
        broker.close()

def test_broker_rejects_raw_connection_provider_bypass(tmp_path: Path) -> None:
    account, policy = _inputs()
    broker_root = tmp_path / "broker3"
    oms_root = tmp_path / "oms-root3"
    broker_root.mkdir()
    oms_root.mkdir()
    broker = initialize_paper_broker_store(
        root=broker_root,
        database_filename="paper.sqlite3",
        oms_store_path=oms_root / "x",
        account=account,
        policy=policy,
        created_at=NOW,
    )
    try:
        with pytest.raises(TypeError):
            broker.bind_session_barrier(  # type: ignore[call-arg]
                object(), oms_conn_provider=lambda: None
            )
        assert "oms_conn_provider" not in broker.bind_session_barrier.__code__.co_varnames
    finally:
        broker.close()


def _formal_schedule():
    return build_execution_cost_schedule(
        selector="paper_a_share_cost_schedule_v1",
        periods=(
            ExecutionCostPeriod(
                Market.SH,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.00025"),
                Decimal("5.00"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
            ExecutionCostPeriod(
                Market.SZ,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.00025"),
                Decimal("5.00"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
        ),
    )


def _formal_policy_and_binding(
    *,
    schedule=None,
    cost_schedule_identity: str | None = None,
    session_date: dt.date = NOW.date(),
    adapter_policy_version: str = "paper_durable_a_share_adapter_v1",
    fill_policy_version: str = "paper_deterministic_fill_v1",
    fault_policy_version: str = "paper_controlled_fault_drills_v1",
    finality_policy_version: str = "paper_session_eod_finality_v1",
    clock_policy_version: str = "utc_system_clock_v1",
    binding_cost_schedule_identity: str | None = None,
    binding_session_date: dt.date | None = None,
    binding_fill_policy_version: str | None = None,
):
    resolved_schedule = _formal_schedule() if schedule is None else schedule
    identity = (
        paper_execution_cost_schedule_identity(resolved_schedule)
        if cost_schedule_identity is None
        else cost_schedule_identity
    )
    policy = VerifiedPaperExecutionPolicy(
        schema_version="paper-execution-policy-v1",
        selector="paper_a_share_v1",
        session_date=session_date,
        source_path=Path("formal-project").absolute() / "policy.toml",
        source_file_identity="a" * 64,
        source_parent_identity="b" * 64,
        raw_sha256="c" * 64,
        trading_config=object(),  # type: ignore[arg-type]
        trading_config_identity="d" * 64,
        supported_markets=(Market.SH, Market.SZ),
        execution_cost_schedule=resolved_schedule,
        cost_schedule_identity=identity,
        minimum_order_notionals=(),
        a_share_rule_selector="a_share_execution_rules_v1",
        adapter_policy_version=adapter_policy_version,
        fill_policy_version=fill_policy_version,
        fault_policy_version=fault_policy_version,
        finality_policy_version=finality_policy_version,
        clock_policy_version=clock_policy_version,
        fx_snapshot_identity=None,
        policy_identity="e" * 64,
        verified_at=NOW,
        _attestation=policy_module._PolicyAttestation(b"test"),
    )
    binding = VerifiedFormalPaperBrokerPolicyBinding(
        schema_version="formal-paper-broker-policy-binding-v1",
        classification="formal-paper-simulation",
        session_date=session_date if binding_session_date is None else binding_session_date,
        runtime_environment_identity="1" * 64,
        runtime_config_identity="2" * 64,
        execution_policy_identity=policy.policy_identity,
        adapter_policy_version=policy.adapter_policy_version,
        fill_policy_version=(
            policy.fill_policy_version
            if binding_fill_policy_version is None
            else binding_fill_policy_version
        ),
        fault_policy_version=policy.fault_policy_version,
        finality_policy_version=policy.finality_policy_version,
        clock_policy_version=policy.clock_policy_version,
        cost_schedule_identity=(
            identity if binding_cost_schedule_identity is None else binding_cost_schedule_identity
        ),
        fx_snapshot_identity=None,
        binding_identity="f" * 64,
        verified_at=NOW,
        _attestation=binding_module._BindingAttestation(b"test"),
    )
    return policy, binding


def test_formal_descriptor_accepts_public_cost_identity_and_keeps_schema() -> None:
    policy, binding = _formal_policy_and_binding()
    assert policy.cost_schedule_identity == _FROZEN_FORMAL_COST_SCHEDULE_IDENTITY
    descriptor = build_formal_paper_broker_policy_descriptor(
        policy=policy, binding=binding
    )
    assert descriptor.schema_version == "paper-broker-policy-v1"
    assert descriptor.classification == "formal-paper-simulation"
    assert descriptor.cost_schedule_identity == _FROZEN_FORMAL_COST_SCHEDULE_IDENTITY
    assert descriptor.adapter_policy_version == policy.adapter_policy_version
    assert descriptor.fill_policy_version == policy.fill_policy_version
    assert descriptor.fault_policy_version == policy.fault_policy_version
    assert descriptor.finality_policy_version == policy.finality_policy_version
    assert descriptor.fx_snapshot_identity is None
    body = {
        "adapter_policy_version": descriptor.adapter_policy_version,
        "classification": "formal-paper-simulation",
        "cost_schedule_identity": descriptor.cost_schedule_identity,
        "fault_policy_version": descriptor.fault_policy_version,
        "fill_policy_version": descriptor.fill_policy_version,
        "finality_policy_version": descriptor.finality_policy_version,
        "fx_snapshot_identity": None,
        "schema_version": "paper-broker-policy-v1",
    }
    assert descriptor.descriptor_identity == broker_store_module._digest(body)
    assert broker_store_module._is_issued_formal_policy_descriptor(descriptor)


def test_formal_descriptor_rejects_stale_cost_identity_and_rule_drift() -> None:
    drifted = build_execution_cost_schedule(
        selector="paper_a_share_cost_schedule_v1",
        periods=(
            ExecutionCostPeriod(
                Market.SH,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.00026"),
                Decimal("5.00"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
            ExecutionCostPeriod(
                Market.SZ,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.00025"),
                Decimal("5.00"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
        ),
    )
    stale_policy, stale_binding = _formal_policy_and_binding(
        schedule=drifted,
        cost_schedule_identity=_FROZEN_FORMAL_COST_SCHEDULE_IDENTITY,
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(
            policy=stale_policy, binding=stale_binding
        )

    claimed_wrong, claimed_binding = _formal_policy_and_binding(
        cost_schedule_identity="f" * 64,
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(
            policy=claimed_wrong, binding=claimed_binding
        )

    policy, binding = _formal_policy_and_binding(
        binding_cost_schedule_identity="0" * 64,
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)

    policy, binding = _formal_policy_and_binding(
        binding_session_date=dt.date(2026, 8, 8),
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)

    policy, binding = _formal_policy_and_binding(
        binding_fill_policy_version="paper_deterministic_fill_v0",
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)


def test_formal_descriptor_rejects_forged_objects_and_nonexact_schedule() -> None:
    policy, binding = _formal_policy_and_binding()
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(
            policy=object.__new__(VerifiedPaperExecutionPolicy),
            binding=binding,
        )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(
            policy=policy,
            binding=object.__new__(VerifiedFormalPaperBrokerPolicyBinding),
        )
    forged_policy = replace(
        policy,
        execution_cost_schedule=object(),  # type: ignore[arg-type]
        cost_schedule_identity=_FROZEN_FORMAL_COST_SCHEDULE_IDENTITY,
    )
    forged_binding = replace(
        binding, cost_schedule_identity=_FROZEN_FORMAL_COST_SCHEDULE_IDENTITY
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(
            policy=forged_policy, binding=forged_binding
        )


def test_monkeypatched_public_identity_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy, binding = _formal_policy_and_binding()

    def boom(schedule: object) -> str:
        del schedule
        raise RuntimeError("HOSTILE_IDENTITY_PATH")

    monkeypatch.setattr(broker_store_module, "paper_execution_cost_schedule_identity", boom)
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$") as caught:
        build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "HOSTILE" not in repr(caught.value)

    monkeypatch.setattr(
        broker_store_module,
        "paper_execution_cost_schedule_identity",
        lambda schedule: "0" * 64,
    )
    with pytest.raises(PaperBrokerStoreError, match="^PAPER_BROKER_POLICY_INVALID$"):
        build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)


def test_issued_formal_descriptor_required_for_store(tmp_path: Path) -> None:
    policy, binding = _formal_policy_and_binding()
    issued = build_formal_paper_broker_policy_descriptor(policy=policy, binding=binding)
    clone = replace(issued)
    assert clone == issued and clone is not issued
    account, _ = _inputs()
    root = tmp_path / "formal-issued"
    oms = tmp_path / "formal-oms"
    root.mkdir()
    oms.mkdir()
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_POLICY_INVALID"):
        initialize_paper_broker_store(
            root=root,
            database_filename="paper.sqlite3",
            oms_store_path=oms,
            account=account,
            policy=clone,
            created_at=NOW,
        )
    assert tuple(root.iterdir()) == ()
    store = initialize_paper_broker_store(
        root=root,
        database_filename="paper.sqlite3",
        oms_store_path=oms,
        account=account,
        policy=issued,
        created_at=NOW,
    )
    try:
        assert store.policy_identity == issued.descriptor_identity
    finally:
        store.close()


def test_non_formal_descriptor_bytes_and_identity_regression() -> None:
    account, policy = _inputs()
    del account
    assert policy.cost_schedule_identity == _FROZEN_DEVELOPMENT_COST_SCHEDULE_IDENTITY
    assert policy.descriptor_identity == _FROZEN_DEVELOPMENT_DESCRIPTOR_IDENTITY
    assert policy.classification == "development"
    assert policy.schema_version == "paper-broker-policy-v1"
    rebuilt = build_paper_broker_policy_descriptor(
        adapter_policy_version="adapter-v1",
        fill_policy_version="fill-v1",
        fault_policy_version="fault-v1",
        finality_policy_version="eod-v1",
        cost_schedule=_schedule(),
        fx_snapshot=None,
    )
    assert rebuilt.cost_schedule_identity == _FROZEN_DEVELOPMENT_COST_SCHEDULE_IDENTITY
    assert rebuilt.descriptor_identity == _FROZEN_DEVELOPMENT_DESCRIPTOR_IDENTITY
    # Incompatible paper-policy algorithm must not be forced into non-formal path.
    assert rebuilt.cost_schedule_identity != paper_execution_cost_schedule_identity(
        _schedule()
    )
