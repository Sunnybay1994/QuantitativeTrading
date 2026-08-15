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
    build_paper_account_descriptor,
    build_paper_broker_policy_descriptor,
    initialize_paper_broker_store,
    open_verified_paper_broker_store,
)
import quant.execution.paper_broker_store as broker_store_module

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 9, 1, tzinfo=UTC)


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
