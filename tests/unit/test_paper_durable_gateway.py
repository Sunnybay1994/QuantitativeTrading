"""RUN-0B1 durable gateway, restart, idempotency and evidence contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.domain.enums import Currency, ExecutionMode, Market, OrderSide
from quant.execution.contracts import CashBalance, OrderCommand, build_account_snapshot, build_cancel_command, build_order_command, build_order_intent
from quant.execution.gateways.contracts import DispatchCertainty
from quant.execution.gateways.paper import PaperCancelPlan, PaperFill, PaperSubmitPlan
import pytest
import quant.execution.paper_broker_store as broker_store_module

from quant.execution.gateways.paper_durable import DurablePaperBrokerSnapshotPort, DurablePaperGateway, DurablePaperGatewayError, DurablePaperGatewayFactory
from quant.execution.oms import new_order_aggregate, reduce_order
from quant.execution.paper_broker_store import PaperBrokerStore, PaperBrokerStoreError
from quant.execution.paper_broker_store import build_paper_account_descriptor, build_paper_broker_policy_descriptor, initialize_paper_broker_store, open_verified_paper_broker_store

UTC = dt.timezone.utc


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _time(minute: int) -> dt.datetime:
    return dt.datetime(2026, 8, 9, 1, minute, tzinfo=UTC)


def _command(*, symbol: str = "600000.SH") -> OrderCommand:
    intent = build_order_intent(
        plan_id=_hex(f"plan-{symbol}"), symbol=symbol, market=Market.SH, side=OrderSide.BUY,
        quantity=100, limit_price=Decimal("10.50"), quote_currency=Currency.CNY,
        session_date=dt.date(2026, 8, 9), generated_at=_time(0), target_identity=_hex("target"),
        market_snapshot_id=_hex("market"), account_snapshot_id=_hex("account"),
        config_identity=_hex("config"), connect_route=None,
    )
    return build_order_command(intent=intent, mode=ExecutionMode.PAPER)


class _Clock:
    def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
        del operation_id
        return _time(1 + event_ordinal)


class _Policy:
    def __init__(
        self,
        submit: PaperSubmitPlan | None = None,
        cancel: PaperCancelPlan | None = None,
    ) -> None:
        self.calls = 0
        self.submit_plan = submit or PaperSubmitPlan(
            fills=(PaperFill(100, Decimal("10.40")),)
        )
        self.cancel_plan = cancel or PaperCancelPlan()

    def plan_submit(self, *, command: OrderCommand) -> PaperSubmitPlan:
        del command
        self.calls += 1
        return self.submit_plan

    def plan_cancel(self, *, command, cancel) -> PaperCancelPlan:
        del command, cancel
        return self.cancel_plan


class _Faults:
    def __init__(self, certainty: DispatchCertainty = DispatchCertainty.SENT, duplicates: tuple[int, ...] = ()) -> None:
        self.certainty = certainty
        self.duplicates = duplicates

    def submit_certainty(self, *, command_id: str, dispatch_attempt: int) -> DispatchCertainty:
        del command_id, dispatch_attempt
        return self.certainty

    def cancel_certainty(self, *, cancel_id: str, dispatch_attempt: int) -> DispatchCertainty:
        del cancel_id, dispatch_attempt
        return self.certainty

    def duplicate_callback_ordinals(self, *, operation_id: str) -> tuple[int, ...]:
        del operation_id
        return self.duplicates


def _schedule():
    return build_execution_cost_schedule(selector="paper-cost-v1", periods=(ExecutionCostPeriod(Market.SH, dt.date(2026, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0.0005"), Decimal("0.00001"), Currency.CNY),))


def _setup(tmp_path: Path, *, certainty: DispatchCertainty = DispatchCertainty.SENT):
    root, oms = tmp_path / "broker", tmp_path / "oms"
    root.mkdir()
    oms.mkdir()
    initial = build_account_snapshot(as_of=_time(0), positions=(), cash=(CashBalance(Currency.CNY, Decimal("100000"), Decimal("100000"), Decimal(0), Decimal(0)),))
    account = build_paper_account_descriptor(account_label="paper-main", created_at=_time(0), base_currency=Currency.CNY, initial_snapshot=initial)
    policy_descriptor = build_paper_broker_policy_descriptor(adapter_policy_version="adapter-v1", fill_policy_version="fill-v1", fault_policy_version="fault-v1", finality_policy_version="eod-v1", cost_schedule=_schedule(), fx_snapshot=None)
    store = initialize_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms, account=account, policy=policy_descriptor, created_at=_time(0))
    policy = _Policy()
    factory = DurablePaperGatewayFactory(store=store, policy=policy_descriptor, clock=_Clock(), fill_policy=policy, fault_plan=_Faults(certainty), cost_schedule=_schedule(), fx_snapshot=None)
    return root, oms, store, policy_descriptor, policy, factory


def test_submit_is_durable_exact_retry_and_broker_evidence_is_independent(tmp_path: Path) -> None:
    root, oms, store, descriptor, policy, factory = _setup(tmp_path)
    command = _command()
    opened = factory.open()
    first = opened.submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    retry = opened.submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert retry == first and policy.calls == 1
    store.finalize_session(session_date=command.intent.session_date, finalized_at=_time(5))

    reopened = open_verified_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms)
    restarted = DurablePaperGatewayFactory(store=reopened, policy=descriptor, clock=_Clock(), fill_policy=_Policy(), fault_plan=_Faults(), cost_schedule=_schedule(), fx_snapshot=None)
    after_restart = restarted.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert after_restart == first
    evidence = DurablePaperBrokerSnapshotPort(store=reopened).query_and_verify(gateway_identity=restarted.identity())
    assert evidence.finality == "END_OF_DAY"
    assert len(evidence.events) == 2 and evidence.account.cash[0].available < Decimal("100000")
    assert len(evidence.orders) == 1 and evidence.orders[0].command_id == command.command_id


def test_unknown_is_retained_across_restart_and_future_attempt_does_not_resend(tmp_path: Path) -> None:
    root, oms, _, descriptor, _, factory = _setup(tmp_path, certainty=DispatchCertainty.UNKNOWN)
    command = _command()
    first = factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert first.certainty is DispatchCertainty.UNKNOWN
    reopened = open_verified_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms)
    sent_policy = _Policy()
    restarted = DurablePaperGatewayFactory(store=reopened, policy=descriptor, clock=_Clock(), fill_policy=sent_policy, fault_plan=_Faults(DispatchCertainty.SENT), cost_schedule=_schedule(), fx_snapshot=None)
    later = restarted.open().submit.submit(command=command, dispatch_attempt=2, now=_time(5))
    assert later.certainty is DispatchCertainty.UNKNOWN and sent_policy.calls == 0
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_SESSION_NOT_FINAL"):
        reopened.finalize_session(session_date=command.intent.session_date, finalized_at=_time(5))
    assert DurablePaperBrokerSnapshotPort(store=reopened).query_and_verify(gateway_identity=restarted.identity()).finality == "INTRADAY"


def test_stale_attempt_and_wrong_gateway_identity_fail_closed(tmp_path: Path) -> None:
    _, _, store, _, _, factory = _setup(tmp_path)
    command = _command()
    factory.open().submit.submit(command=command, dispatch_attempt=3, now=_time(5))
    with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_ATTEMPT_STALE") as caught:
        factory.open().submit.submit(command=command, dispatch_attempt=2, now=_time(5))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_GATEWAY_IDENTITY_MISMATCH"):
        DurablePaperBrokerSnapshotPort(store=store).query_and_verify(gateway_identity="0" * 64)


def test_duplicate_callback_is_retained_but_applied_to_account_once(tmp_path: Path) -> None:
    _, _, store, descriptor, _, _ = _setup(tmp_path)
    factory = DurablePaperGatewayFactory(
        store=store, policy=descriptor, clock=_Clock(), fill_policy=_Policy(),
        fault_plan=_Faults(duplicates=(1,)), cost_schedule=_schedule(), fx_snapshot=None,
    )
    result = factory.open().submit.submit(command=_command(), dispatch_attempt=1, now=_time(5))
    assert len(result.callbacks) == 3 and result.callbacks[1] == result.callbacks[2]
    evidence = DurablePaperBrokerSnapshotPort(store=store).query_and_verify(gateway_identity=factory.identity())
    assert len(evidence.events) == 2
    assert evidence.account.cash[0].available == Decimal("98954.99")


def test_independent_writer_lock_is_busy_not_identity_drift(tmp_path: Path) -> None:
    root, _, _, _, _, factory = _setup(tmp_path)
    command = _command()
    conn = sqlite3.connect(root / "paper.sqlite3", isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_BUSY"):
            factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    finally:
        conn.rollback()
        conn.close()


def test_journal_result_tamper_rejected_before_evidence(tmp_path: Path) -> None:
    root, _, store, _, _, factory = _setup(tmp_path)
    factory.open().submit.submit(command=_command(), dispatch_attempt=1, now=_time(5))
    conn = sqlite3.connect(root / "paper.sqlite3")
    try:
        conn.execute("UPDATE operations SET result_payload=?", (b"{}",))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PaperBrokerStoreError):
        DurablePaperBrokerSnapshotPort(store=store).query_and_verify(gateway_identity=factory.identity())


def test_precommit_failure_rolls_back_and_retry_applies_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, store, _, _, factory = _setup(tmp_path)
    command = _command()
    original = store._append_journal

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("HOSTILE_PRECOMMIT_MARKER")

    monkeypatch.setattr(store, "_append_journal", fail)
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_WRITE_FAILED") as caught:
        factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert store.retained_operation(command.command_id) is None
    monkeypatch.setattr(store, "_append_journal", original)
    factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert len(store.read_state()[2]) == 2


def test_postcommit_lost_return_retries_retained_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, store, _, _, factory = _setup(tmp_path)
    command = _command()
    original = store.persist_operation

    def commit_then_fail(**kwargs):
        original(**kwargs)
        raise RuntimeError("HOSTILE_AFTER_COMMIT_MARKER")

    monkeypatch.setattr(store, "persist_operation", commit_then_fail)
    with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_DISPATCH_FAILED") as caught:
        factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    monkeypatch.setattr(store, "persist_operation", original)
    retained = factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert retained.certainty is DispatchCertainty.SENT
    assert len(store.read_state()[2]) == 2


def test_partial_fill_cancel_late_fill_and_final_cancel_survive_restart(tmp_path: Path) -> None:
    root, oms, store, descriptor, _, _ = _setup(tmp_path)
    command = _command()
    policy = _Policy(
        submit=PaperSubmitPlan(fills=(PaperFill(40, Decimal("10.40")),)),
        cancel=PaperCancelPlan(late_fills=(PaperFill(20, Decimal("10.30")),), confirm_cancel=True),
    )

    class Clock:
        anchors: dict[str, dt.datetime] = {}

        def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
            return self.anchors.get(operation_id, _time(1)) + dt.timedelta(minutes=event_ordinal)

    clock = Clock()
    factory = DurablePaperGatewayFactory(store=store, policy=descriptor, clock=clock, fill_policy=policy, fault_plan=_Faults(), cost_schedule=_schedule(), fx_snapshot=None)
    submitted = factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    aggregate = new_order_aggregate(command)
    for event in submitted.callbacks:
        aggregate = reduce_order(aggregate, command, event)
    cancel = build_cancel_command(command=command, aggregate=aggregate, as_of=_time(6))
    clock.anchors[cancel.cancel_id] = _time(7)
    cancelled = factory.open().cancel.cancel(command=cancel, dispatch_attempt=1, now=_time(12))
    assert [item.event_type.value for item in cancelled.callbacks] == ["CANCEL_ACCEPTED", "PARTIAL_FILL", "CANCELLED"]
    store.finalize_session(session_date=command.intent.session_date, finalized_at=_time(12))

    reopened = open_verified_paper_broker_store(root=root, database_filename="paper.sqlite3", oms_store_path=oms)
    evidence = DurablePaperBrokerSnapshotPort(store=reopened).query_and_verify(gateway_identity=reopened.gateway_identity)
    assert evidence.finality == "END_OF_DAY"
    assert evidence.orders[0].status.value == "CANCELLED"
    assert evidence.orders[0].cumulative_quantity == 60


def test_public_adapters_require_exact_store_and_fresh_policy(tmp_path: Path) -> None:
    _, _, store, descriptor, _, _ = _setup(tmp_path)

    class StoreSubclass(PaperBrokerStore):
        pass

    subclass = object.__new__(StoreSubclass)

    class Duck:
        policy_identity = descriptor.descriptor_identity
        gateway_identity = "a" * 64

        def verify_fresh(self) -> None:
            return None

    for fake in (subclass, Duck()):
        with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_STORE_INVALID"):
            DurablePaperGatewayFactory(
                store=fake,  # type: ignore[arg-type]
                policy=descriptor, clock=_Clock(), fill_policy=_Policy(),
                fault_plan=_Faults(), cost_schedule=_schedule(), fx_snapshot=None,
            )
        with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_STORE_INVALID"):
            DurablePaperBrokerSnapshotPort(store=fake)  # type: ignore[arg-type]
        with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_STORE_INVALID"):
            DurablePaperGateway(
                store=fake,  # type: ignore[arg-type]
                clock=_Clock(), fill_policy=_Policy(), fault_plan=_Faults(),
                cost_schedule=_schedule(), fx_snapshot=None,
            )

    forged = replace(descriptor, descriptor_identity="f" * 64)
    with pytest.raises(DurablePaperGatewayError, match="PAPER_BROKER_POLICY_INVALID"):
        DurablePaperGatewayFactory(
            store=store, policy=forged, clock=_Clock(), fill_policy=_Policy(),
            fault_plan=_Faults(), cost_schedule=_schedule(), fx_snapshot=None,
        )


def test_two_writers_same_predecessor_cas_then_retry_once(tmp_path: Path) -> None:
    root, oms, first_store, descriptor, _, _ = _setup(tmp_path)
    second_store = open_verified_paper_broker_store(
        root=root, database_filename="paper.sqlite3", oms_store_path=oms
    )
    stores = (first_store, second_store)
    factories = tuple(
        DurablePaperGatewayFactory(
            store=item, policy=descriptor, clock=_Clock(), fill_policy=_Policy(),
            fault_plan=_Faults(), cost_schedule=_schedule(), fx_snapshot=None,
        )
        for item in stores
    )
    commands = (_command(symbol="600000.SH"), _command(symbol="600001.SH"))
    barrier = threading.Barrier(2)
    originals = (first_store.read_predecessor, second_store.read_predecessor)

    def fenced(original):
        def read():
            value = original()
            barrier.wait(timeout=30)
            return value

        return read

    first_store.read_predecessor = fenced(originals[0])  # type: ignore[method-assign]
    second_store.read_predecessor = fenced(originals[1])  # type: ignore[method-assign]

    def submit(index: int):
        return factories[index].open().submit.submit(
            command=commands[index], dispatch_attempt=1, now=_time(5)
        )

    results: list[object] = []
    errors: list[tuple[int, BaseException]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(submit, index) for index in (0, 1))
        for index, future in enumerate(futures):
            try:
                results.append(future.result(timeout=60))
            except BaseException as error:
                errors.append((index, error))
    assert len(results) == 1, [(index, type(error).__name__, str(error)) for index, error in errors]
    assert len(errors) == 1
    assert isinstance(errors[0][1], PaperBrokerStoreError)
    assert str(errors[0][1]) in {
        "PAPER_BROKER_BUSY",
        "PAPER_BROKER_PREDECESSOR_STALE",
    }

    first_store.read_predecessor = originals[0]  # type: ignore[method-assign]
    second_store.read_predecessor = originals[1]  # type: ignore[method-assign]
    loser = errors[0][0]
    submit(loser)
    evidence = DurablePaperBrokerSnapshotPort(store=first_store).query_and_verify(
        gateway_identity=first_store.gateway_identity
    )
    assert len(evidence.events) == 4
    assert len(evidence.orders) == 2
    assert len(evidence.account.positions) == 2
    assert evidence.account.cash[0].available == Decimal("97909.98")


def test_replay_rejects_valid_account_and_checkpoint_whole_rehash(tmp_path: Path) -> None:
    root, _, store, _, _, factory = _setup(tmp_path)
    factory.open().submit.submit(command=_command(), dispatch_attempt=1, now=_time(5))
    store.close()
    database = root / "paper.sqlite3"
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "UPDATE account_state SET payload=? WHERE singleton=1",
            (broker_store_module._account_wire(store.account_descriptor.initial_snapshot),),
        )
        state_digest = broker_store_module._state_digest(conn)
        row = conn.execute(
            "SELECT seq,kind,subject,payload_digest,prev_hash FROM journal WHERE seq=1"
        ).fetchone()
        assert row is not None
        entry_hash = broker_store_module._digest(
            {
                "kind": row[1], "payload_digest": row[3],
                "state_digest": state_digest, "prev_hash": row[4],
                "seq": row[0], "subject": row[2],
            }
        )
        conn.execute(
            "UPDATE journal SET state_digest=?,entry_hash=? WHERE seq=1",
            (state_digest, entry_hash),
        )
        conn.execute(
            "UPDATE checkpoint SET state_digest=?,head_hash=? WHERE singleton=1",
            (state_digest, entry_hash),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_REPLAY_INVALID"):
        open_verified_paper_broker_store(
            root=root, database_filename="paper.sqlite3", oms_store_path=tmp_path / "oms"
        )


def test_anchor_exact_retry_delete_and_commit_gap_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, oms, store, _, _, factory = _setup(tmp_path)
    command = _command()
    original_write = broker_store_module._exclusive_write

    def fail_anchor(path: Path, payload: bytes) -> None:
        if path.parent.name == "sequence-anchors":
            raise OSError("HOSTILE_ANCHOR_GAP")
        original_write(path, payload)

    monkeypatch.setattr(broker_store_module, "_exclusive_write", fail_anchor)
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_ANCHOR_INVALID"):
        factory.open().submit.submit(command=command, dispatch_attempt=1, now=_time(5))
    monkeypatch.setattr(broker_store_module, "_exclusive_write", original_write)
    retained = factory.open().submit.submit(
        command=command, dispatch_attempt=1, now=_time(5)
    )
    assert retained.certainty is DispatchCertainty.SENT
    anchors = tuple((root / "sequence-anchors").iterdir())
    assert [path.name for path in anchors] == ["00000000000000000001.json"]

    store.close()
    anchors[0].unlink()
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_ANCHOR_INVALID"):
        open_verified_paper_broker_store(
            root=root, database_filename="paper.sqlite3", oms_store_path=oms
        )


def test_anchor_modified_or_sequence_jump_fail_closed(tmp_path: Path) -> None:
    root, oms, store, _, _, factory = _setup(tmp_path)
    factory.open().submit.submit(command=_command(), dispatch_attempt=1, now=_time(5))
    store.close()
    anchor = root / "sequence-anchors" / "00000000000000000001.json"
    payload = bytearray(anchor.read_bytes())
    payload[-2] = ord("0") if payload[-2] != ord("0") else ord("1")
    anchor.write_bytes(payload)
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_ANCHOR_INVALID"):
        open_verified_paper_broker_store(
            root=root, database_filename="paper.sqlite3", oms_store_path=oms
        )

    # Restore the exact committed anchor, then prove an uncommitted jump is rejected.
    anchor.unlink()
    conn = sqlite3.connect(root / "paper.sqlite3")
    try:
        conn.execute("UPDATE checkpoint SET anchored_sequence=0")
        conn.commit()
    finally:
        conn.close()
    recovered = open_verified_paper_broker_store(
        root=root, database_filename="paper.sqlite3", oms_store_path=oms
    )
    recovered.close()
    (root / "sequence-anchors" / "00000000000000000003.json").write_bytes(b"{}")
    with pytest.raises(PaperBrokerStoreError, match="PAPER_BROKER_ANCHOR_INVALID"):
        open_verified_paper_broker_store(
            root=root, database_filename="paper.sqlite3", oms_store_path=oms
        )
