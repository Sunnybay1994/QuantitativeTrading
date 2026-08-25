"""M4-P5 deterministic local recovery and reconciliation contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest
import quant.execution.reconcile as reconcile_module

from quant.domain.enums import Currency, ExecutionEventType, OrderStatus
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    build_account_snapshot,
    build_cash_balance,
    build_execution_event,
)
from quant.execution.reconcile import (
    BrokerOrderObservation,
    ReconciliationError,
    RecoveryError,
    RecoveryResult,
    build_broker_snapshot,
    recover_local_state,
    recover_repository_state,
    reconcile,
)
from quant.execution.risk import CancelRiskDecision, RiskDecision, RiskRuleResult
from quant.execution.risk_wire import (
    DurableOrderRiskDecision,
    build_cancel_risk_receipt,
    build_order_risk_receipt,
)
from quant.execution.store import (
    ExecutionRepository,
    ExecutionStore,
    StoreError,
)
from tests.unit.test_execution_service import (
    FakeGateway,
    MutableClock,
    _approval_bundle,
    _inputs as service_inputs,
    _logical_execution_snapshot,
    _open as service_open,
    _planner_config,
    _service as build_service,
    _stage as stage_service,
    _trading_config,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 2, 8, tzinfo=UTC)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _assert_detached(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True


def _open(tmp_path: Path) -> ExecutionStore:
    return ExecutionStore.open(
        "sqlite:///reconcile/execution.db", trusted_root=tmp_path
    )


@contextmanager
def _opened(tmp_path: Path) -> Iterator[ExecutionStore]:
    store = _open(tmp_path)
    try:
        yield store
    finally:
        store.close()


def _account(*, cash: str | None = None) -> AccountSnapshot:
    balances: tuple[CashBalance, ...] = ()
    if cash is not None:
        balances = (
            build_cash_balance(
                currency=Currency.CNY,
                settled=Decimal(cash),
                available=Decimal(cash),
                receivable=Decimal(0),
                payable=Decimal(0),
            ),
        )
    return build_account_snapshot(as_of=NOW, positions=(), cash=balances)


def test_empty_recovery_is_ready_deterministic_and_read_only(tmp_path: Path) -> None:
    with _opened(tmp_path) as store:
        with store.transaction() as repo:
            before = repo.read_recovery_rows()
        first = recover_local_state(store)
        second = recover_local_state(store)
        with store.transaction() as repo:
            after = repo.read_recovery_rows()

    assert first == second
    assert first.disposition == "READY"
    assert first.checkpoint is None
    assert first.commands == first.events == first.issues == ()
    assert before == after


def _rebuild_recovery_with_receipts(
    value: RecoveryResult, receipts: tuple[object, ...]
) -> RecoveryResult:
    values = {
        field.name: getattr(value, field.name)
        for field in fields(RecoveryResult)
        if field.name != "recovery_id"
    }
    values["risk_receipts"] = receipts
    provisional = RecoveryResult.__new__(RecoveryResult)
    for name, child in values.items():
        object.__setattr__(provisional, name, child)
    object.__setattr__(provisional, "recovery_id", "0" * 64)
    identity = reconcile_module._recovery_identity(  # noqa: SLF001 - hostile outer rehash
        provisional
    )
    return RecoveryResult(recovery_id=identity, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra_order", "duplicate_owner", "cross_plan", "extra_cancel"],
)
def test_recovery_result_rejects_semantic_receipt_drift_after_outer_rehash(
    tmp_path: Path, mutation: str
) -> None:
    with _opened(tmp_path) as store:
        service = build_service(store, FakeGateway(), MutableClock())
        stage_service(service, tmp_path)
        local = recover_local_state(store)
    tail = local.risk_receipts[-1]
    projected = tail.decision.projected_counters
    receipts = local.risk_receipts
    if mutation == "missing":
        mutated: tuple[object, ...] = ()
    elif mutation == "extra_cancel":
        cancel_decision = CancelRiskDecision(
            accepted=True,
            cancel_id=_hex("extra-cancel"),
            code="CANCEL_LIMIT_OK",
            policy_identity=_hex("extra-policy"),
            projected_counters=type(projected)(
                projected.session_date,
                projected.order_count,
                projected.cancel_count + 1,
                projected.buy_notional,
            ),
        )
        extra = build_cancel_risk_receipt(
            sequence=tail.sequence + 1,
            previous_receipt_id=tail.receipt_id,
            risk_counter_key=tail.risk_counter_key,
            predecessor_counters=projected,
            command_id=local.commands[0].command_id,
            decision=cancel_decision,
        )
        mutated = (*receipts, extra)
    else:
        command_tuple = () if mutation == "extra_order" else local.commands
        approved = (
            ()
            if not command_tuple
            else tuple(item.intent.intent_id for item in command_tuple)
        )
        plan_id = (
            _hex("cross-plan")
            if mutation in {"extra_order", "cross_plan"}
            else command_tuple[0].intent.plan_id
        )
        order_decision = RiskDecision(
            accepted=bool(command_tuple),
            plan_id=plan_id,
            rule_results=(RiskRuleResult(
                "R2_TEST", bool(command_tuple), "R2_TEST", plan_id, "fresh closure"
            ),),
            approved_intent_ids=approved,
            commands=command_tuple,
            projected_counters=projected,
            requires_manual_approval=False,
        )
        extra = build_order_risk_receipt(
            sequence=tail.sequence + 1,
            previous_receipt_id=tail.receipt_id,
            risk_counter_key=tail.risk_counter_key,
            predecessor_counters=projected,
            decision=order_decision,
        )
        mutated = (*receipts, extra)
    with pytest.raises(
        RecoveryError, match="^RECOVERY_RESULT_INVALID$"
    ) as error:
        _rebuild_recovery_with_receipts(local, mutated)
    _assert_detached(error.value)


def test_empty_end_of_day_broker_snapshot_passes_gate(tmp_path: Path) -> None:
    with _opened(tmp_path) as store:
        local = recover_local_state(store)
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=NOW,
        finality="END_OF_DAY",
        account=_account(),
        orders=(),
        events=(),
    )

    first = reconcile(local, broker, NOW)
    second = reconcile(local, broker, NOW)

    assert first == second
    assert first.gate_passed
    assert first.disposition == "READY"
    assert first.differences == ()


def test_intraday_snapshot_never_passes_even_when_equal(tmp_path: Path) -> None:
    with _opened(tmp_path) as store:
        local = recover_local_state(store)
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=NOW,
        finality="INTRADAY",
        account=_account(),
        orders=(),
        events=(),
    )

    result = reconcile(local, broker, NOW)

    assert not result.gate_passed
    assert result.disposition == "QUERY_REQUIRED"
    assert tuple(item.code for item in result.differences) == (
        "BROKER_SNAPSHOT_INTRADAY",
    )


def test_unknown_broker_order_and_account_difference_are_manual(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        local = recover_local_state(store)
    order = BrokerOrderObservation(
        broker_order_id="PAPER-UNKNOWN",
        command_id=None,
        status=OrderStatus.SUBMITTED,
        cumulative_quantity=0,
        observed_event_ids=(),
    )
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=NOW,
        finality="END_OF_DAY",
        account=_account(cash="1000"),
        orders=(order,),
        events=(),
    )

    result = reconcile(local, broker, NOW)

    assert not result.gate_passed
    assert result.disposition == "MANUAL_REQUIRED"
    assert {item.code for item in result.differences} == {
        "BROKER_ACCOUNT_LOCAL_MISSING",
        "BROKER_ORDER_UNKNOWN",
    }


def test_recovery_rejects_hostile_command_without_retained_context(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        with store.transaction() as repo:
            repo.put_command(
                command_id=_hex("hostile-command"),
                identity=_hex("hostile-command"),
                payload=b"TOKEN",
            )
        with pytest.raises(RecoveryError, match="^RECOVERY_LOCAL_INVALID$") as info:
            recover_local_state(store)

    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert "TOKEN" not in repr(info.value.args)


def test_recovery_error_exposes_stable_code_without_context(tmp_path: Path) -> None:
    """F19: RecoveryError exposes stable .code; instances do not share state."""
    with _opened(tmp_path) as store:
        with store.transaction() as repo:
            repo.put_command(
                command_id=_hex("hostile-command-code"),
                identity=_hex("hostile-command-code"),
                payload=b"TOKEN",
            )
        with pytest.raises(RecoveryError, match="^RECOVERY_LOCAL_INVALID$") as first_info:
            recover_local_state(store)
        with pytest.raises(RecoveryError, match="^RECOVERY_LOCAL_INVALID$") as second_info:
            recover_local_state(store)

    first = first_info.value
    second = second_info.value
    assert first is not second
    assert first.code == first.args[0] == str(first) == "RECOVERY_LOCAL_INVALID"
    assert second.code == second.args[0] == str(second) == "RECOVERY_LOCAL_INVALID"
    assert type(first.code) is str and type(first.args[0]) is str
    _assert_detached(first)
    _assert_detached(second)
    assert "TOKEN" not in repr(first.args) and "TOKEN" not in repr(second.args)
    first.code = "MUTATED"
    assert second.code == second.args[0] == str(second) == "RECOVERY_LOCAL_INVALID"


def test_staged_command_recovers_full_context_and_is_retry_classified(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        service = build_service(store, FakeGateway(), MutableClock())
        staged = stage_service(service, tmp_path)
        local = recover_local_state(store)
        _, _, account = service_inputs(cash="2000")

    assert tuple(item.command_id for item in local.commands) == staged.staged_command_ids
    assert tuple(item.command_id for item in local.ledger_contexts) == staged.staged_command_ids
    assert local.checkpoint is not None
    assert local.disposition == "READY"
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=account.as_of,
        finality="END_OF_DAY",
        account=account,
        orders=(),
        events=(),
    )
    result = reconcile(local, broker, account.as_of)
    assert not result.gate_passed
    assert result.disposition == "READY"
    assert tuple((item.code, item.action) for item in result.differences) == (
        ("LOCAL_NOT_SENT", "AUTOMATIC_RETRY"),
    )


def test_forged_broker_and_local_identity_fail_closed(tmp_path: Path) -> None:
    with _opened(tmp_path) as store:
        local = recover_local_state(store)
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=NOW,
        finality="END_OF_DAY",
        account=_account(),
        orders=(),
        events=(),
    )
    object.__setattr__(broker, "source_identity", _hex("forged"))
    with pytest.raises(
        ReconciliationError, match="^RECONCILIATION_INPUT_INVALID$"
    ) as broker_error:
        reconcile(local, broker, NOW)
    assert broker_error.value.__cause__ is None
    assert broker_error.value.__context__ is None

    object.__setattr__(local, "disposition", "MANUAL_REQUIRED")
    with pytest.raises(
        ReconciliationError, match="^RECONCILIATION_INPUT_INVALID$"
    ) as local_error:
        reconcile(local, broker, NOW)
    assert local_error.value.__cause__ is None
    assert local_error.value.__context__ is None


def test_sent_callback_recovers_and_matching_end_of_day_broker_passes(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        gateway = FakeGateway()
        gateway.partial_then_fill = True
        service = build_service(store, gateway, MutableClock())
        stage_service(service, tmp_path)
        assert service.dispatch_pending(limit=1).items[0].code == "SENT"
        with store.transaction() as repo:
            before = repo.read_recovery_rows()
        local = recover_local_state(store)
        with store.transaction() as repo:
            after = repo.read_recovery_rows()

    assert before == after
    assert local.checkpoint is not None
    aggregate = local.order_aggregates[0]
    observed_at = max(item.occurred_at for item in local.events)
    account = build_account_snapshot(
        as_of=observed_at,
        positions=local.checkpoint.positions,
        cash=local.checkpoint.cash,
    )
    order = BrokerOrderObservation(
        broker_order_id=aggregate.broker_order_id or "",
        command_id=aggregate.command_id,
        status=aggregate.status,
        cumulative_quantity=aggregate.filled_quantity,
        observed_event_ids=tuple(sorted(aggregate.applied_event_ids)),
    )
    broker = build_broker_snapshot(
        source_identity=_hex("paper-eod"), as_of=observed_at,
        finality="END_OF_DAY", account=account, orders=(order,),
        events=local.events,
    )

    result = reconcile(local, broker, observed_at)
    assert result.gate_passed
    assert result.disposition == "READY"
    assert result.differences == ()


def test_duplicate_economic_broker_event_keeps_specific_manual_classification(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        gateway = FakeGateway()
        service = build_service(store, gateway, MutableClock())
        stage_service(service, tmp_path)
        assert service.dispatch_pending(limit=1).items[0].code == "SENT"
        local = recover_local_state(store)

    assert local.checkpoint is not None
    aggregate = local.order_aggregates[0]
    command = local.commands[0]
    original = local.events[0]
    duplicate = build_execution_event(
        command=command,
        broker_order_id=original.broker_order_id,
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=original.occurred_at + dt.timedelta(seconds=1),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    observed_at = duplicate.occurred_at
    account = build_account_snapshot(
        as_of=observed_at,
        positions=local.checkpoint.positions,
        cash=local.checkpoint.cash,
    )
    order = BrokerOrderObservation(
        broker_order_id=aggregate.broker_order_id or "",
        command_id=aggregate.command_id,
        status=aggregate.status,
        cumulative_quantity=aggregate.filled_quantity,
        observed_event_ids=tuple(sorted((*aggregate.applied_event_ids, duplicate.event_id))),
    )
    broker = build_broker_snapshot(
        source_identity=_hex("paper-eod-duplicate"), as_of=observed_at,
        finality="END_OF_DAY", account=account, orders=(order,),
        events=tuple(sorted((*local.events, duplicate), key=lambda item: item.event_id)),
    )

    result = reconcile(local, broker, observed_at)
    by_subject = {item.subject: item for item in result.differences}
    assert by_subject[duplicate.event_id].code == "BROKER_ECONOMIC_EVENT_DUPLICATE"
    assert by_subject[duplicate.event_id].action == "MANUAL_REQUIRED"


def test_inner_typed_mutation_is_reproved_before_reconciliation(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        service = build_service(store, FakeGateway(), MutableClock())
        stage_service(service, tmp_path)
        local = recover_local_state(store)
        _, _, account = service_inputs(cash="2000")
    broker = build_broker_snapshot(
        source_identity=_hex("paper-eod-mutation"), as_of=account.as_of,
        finality="END_OF_DAY", account=account, orders=(), events=(),
    )
    intent = local.commands[0].intent
    object.__setattr__(intent, "quantity", intent.quantity + 100)

    with pytest.raises(
        ReconciliationError, match="^RECONCILIATION_INPUT_INVALID$"
    ) as info:
        reconcile(local, broker, account.as_of)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_orphaned_context_parent_fails_recovery_without_hidden_sql_context(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        service = build_service(store, FakeGateway(), MutableClock())
        stage_service(service, tmp_path)
        database = tmp_path / "reconcile" / "execution.db"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DELETE FROM commands")
            connection.commit()
        with pytest.raises(RecoveryError, match="^RECOVERY_LOCAL_INVALID$") as info:
            recover_local_state(store)
        assert info.value.__cause__ is None
        assert info.value.__context__ is None
    finally:
        store.close()


def test_recovery_holds_one_consistent_snapshot_against_concurrent_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _open(tmp_path)
    second = ExecutionStore.open(
        "sqlite:///reconcile/execution.db", trusted_root=tmp_path
    )
    captured = threading.Event()
    release = threading.Event()
    results: list[object] = []
    original = ExecutionRepository.read_recovery_rows

    def paused(repo: ExecutionRepository):
        rows = original(repo)
        captured.set()
        assert release.wait(5)
        return rows

    monkeypatch.setattr(ExecutionRepository, "read_recovery_rows", paused)
    thread = threading.Thread(
        target=lambda: results.append(recover_local_state(store)), daemon=True
    )
    try:
        thread.start()
        assert captured.wait(5)
        with pytest.raises(StoreError, match="^TX_BUSY$"):
            with second.transaction():
                pass
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert len(results) == 1
        assert getattr(results[0], "disposition") == "READY"
        with second.transaction():
            pass
    finally:
        release.set()
        thread.join(5)
        second.close()
        store.close()


def _stage_pending_cancel(store: ExecutionStore, tmp_path: Path):
    service = build_service(store, FakeGateway(), MutableClock())
    staged = stage_service(service, tmp_path)
    assert service.dispatch_pending(limit=1).items[0].code == "SENT"
    return service.stage_cancel(
        command_id=staged.staged_command_ids[0],
        trading_config=_trading_config(tmp_path),
    ).cancel


def test_pending_cancel_recovers_typed_closure_and_binds_recovery_id(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        cancel = _stage_pending_cancel(store, tmp_path)
        first = recover_local_state(store)
        second = recover_local_state(store)

    assert first == second
    assert first.disposition == "READY"
    assert first.cancel_commands == (cancel,)
    assert tuple(item.cancel_id for item in first.cancel_deliveries) == (
        cancel.cancel_id,
    )
    assert first.cancel_event_links == ()


def test_order_cancel_order_same_counter_key_has_one_continuous_risk_chain(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        service = build_service(store, FakeGateway(), MutableClock())
        first = stage_service(service, tmp_path)
        assert service.dispatch_pending(limit=1).items[0].code == "SENT"
        cancel = service.stage_cancel(
            command_id=first.staged_command_ids[0],
            trading_config=_trading_config(tmp_path),
        )
        targets, market, account = service_inputs(cash="2000")
        second = service.plan_and_stage(
            targets=targets,
            target_identity=_hex("second-targets"),
            market=market,
            account=account,
            planner_config=_planner_config(tmp_path),
        )
        first_replay = stage_service(service, tmp_path)
        cancel_replay = service.stage_cancel(
            command_id=first.staged_command_ids[0],
            trading_config=_trading_config(tmp_path),
        )
        recovered = recover_local_state(store)

    assert not second.replayed and cancel.risk.accepted
    assert first_replay.replayed and cancel_replay.replayed
    assert tuple(item.transition_kind for item in recovered.risk_receipts) == (
        "ORDER", "CANCEL", "ORDER",
    )
    assert tuple(item.sequence for item in recovered.risk_receipts) == (1, 2, 3)
    assert recovered.risk_receipts[1].predecessor_counter_identity == (
        recovered.risk_receipts[0].projected_counter_identity
    )
    assert recovered.risk_receipts[2].predecessor_counter_identity == (
        recovered.risk_receipts[1].projected_counter_identity
    )


def test_legacy_cancel_without_transition_receipt_fails_closed(tmp_path: Path) -> None:
    with _opened(tmp_path) as store:
        cancel = _stage_pending_cancel(store, tmp_path)
        database = tmp_path / "reconcile" / "execution.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "DELETE FROM risk_transition_receipts WHERE transition_kind='CANCEL' "
                "AND subject_id=?",
                (cancel.cancel_id,),
            )
            connection.commit()
        with pytest.raises(
            RecoveryError, match="^RECOVERY_RISK_CLOSURE_INVALID$"
        ) as error:
            recover_local_state(store)
    _assert_detached(error.value)


def test_leased_and_unknown_cancel_are_query_required_and_change_identity(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        cancel = _stage_pending_cancel(store, tmp_path)
        before = recover_local_state(store)
        with store.transaction() as repo:
            claimed = repo.claim_cancel_delivery(
                cancel_id=cancel.cancel_id,
                worker_id="recovery-worker",
                now=cancel.as_of,
                lease_until=cancel.as_of + dt.timedelta(minutes=1),
            )
        leased = recover_local_state(store)
        with store.transaction() as repo:
            repo.mark_cancel_unknown(
                cancel_id=cancel.cancel_id,
                lease_owner="recovery-worker",
                expected_attempt=claimed.attempt_count,
                unknown_at=cancel.as_of + dt.timedelta(seconds=1),
                error_code="BROKER_UNCERTAIN",
            )
        unknown = recover_local_state(store)

    assert leased.disposition == unknown.disposition == "QUERY_REQUIRED"
    assert tuple(item.code for item in leased.issues) == (
        "CANCEL_DELIVERY_LEASED",
    )
    assert tuple(item.code for item in unknown.issues) == (
        "CANCEL_DELIVERY_UNKNOWN",
    )
    assert len({before.recovery_id, leased.recovery_id, unknown.recovery_id}) == 3


def test_cancel_counter_shortfall_and_sent_without_link_are_manual(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        cancel = _stage_pending_cancel(store, tmp_path)
        counter_payload = (
            b'{"counter":{"buy_notional":"0","cancel_count":0,'
            b'"order_count":1,"session_date":"2026-07-20"},'
            b'"schema_version":"m4-daily-risk-counters-v1"}'
        )
        with store.transaction() as repo:
            cancel_row = repo.read_recovery_rows().cancel_commands[0]
            original_counter = repo.get_scoped_daily_risk_counters(
                cancel_row.risk_counter_key
            )
        assert original_counter is not None
        database = tmp_path / "reconcile" / "execution.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE scoped_daily_risk_counters SET identity=?, payload=? "
                "WHERE counter_key=?",
                (
                    hashlib.sha256(counter_payload).hexdigest(),
                    counter_payload,
                    cancel_row.risk_counter_key,
                ),
            )
            connection.commit()
        with pytest.raises(
            RecoveryError, match="^RECOVERY_RISK_CLOSURE_INVALID$"
        ) as shortfall:
            recover_local_state(store)
        _assert_detached(shortfall.value)

        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE scoped_daily_risk_counters SET identity=?, payload=? "
                "WHERE counter_key=?",
                (
                    original_counter.identity,
                    original_counter.payload,
                    cancel_row.risk_counter_key,
                ),
            )
            connection.commit()
        with store.transaction() as repo:
            claimed = repo.claim_cancel_delivery(
                cancel_id=cancel.cancel_id,
                worker_id="recovery-worker",
                now=cancel.as_of,
                lease_until=cancel.as_of + dt.timedelta(minutes=1),
            )
            repo.mark_cancel_sent(
                cancel_id=cancel.cancel_id,
                lease_owner="recovery-worker",
                expected_attempt=claimed.attempt_count,
                sent_at=cancel.as_of + dt.timedelta(seconds=1),
            )
        missing_link = recover_local_state(store)

    assert missing_link.disposition == "MANUAL_REQUIRED"
    assert tuple(item.code for item in missing_link.issues) == (
        "CANCEL_RECOVERY_CLOSURE_INVALID",
    )


def test_sent_cancel_with_one_of_two_callback_links_deleted_is_manual(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path)
    try:
        gateway = FakeGateway()
        service = build_service(store, gateway, MutableClock())
        staged_order = stage_service(service, tmp_path)
        assert service.dispatch_pending(limit=1).items[0].code == "SENT"
        staged_cancel = service.stage_cancel(
            command_id=staged_order.staged_command_ids[0],
            trading_config=_trading_config(tmp_path),
        )
        dispatched = service.dispatch_cancel(cancel_id=staged_cancel.cancel.cancel_id)
        assert dispatched.code == "SENT"
        assert len(dispatched.callback_event_ids) == 2
        database = tmp_path / "reconcile" / "execution.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "DELETE FROM cancel_event_links WHERE cancel_id=? AND event_id=?",
                (staged_cancel.cancel.cancel_id, dispatched.callback_event_ids[0]),
            )
            connection.commit()

        recovered = recover_local_state(store)
    finally:
        store.close()

    assert recovered.disposition == "MANUAL_REQUIRED"
    assert tuple(item.code for item in recovered.issues) == (
        "CANCEL_RECOVERY_CLOSURE_INVALID",
    )


def test_malformed_cancel_payload_fails_with_detached_stable_code(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        _stage_pending_cancel(store, tmp_path)
        database = tmp_path / "reconcile" / "execution.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE cancel_commands SET payload=?", (b"TOKEN",))
            connection.commit()
        with pytest.raises(
            RecoveryError, match="^CANCEL_RECOVERY_CLOSURE_INVALID$"
        ) as info:
            recover_local_state(store)

    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert "TOKEN" not in repr(info.value.args)

def test_recover_repository_state_matches_recover_local_state_identity(
    tmp_path: Path,
) -> None:
    with _opened(tmp_path) as store:
        wrapped = recover_local_state(store)
        with store.transaction() as repo:
            direct = recover_repository_state(repo)
        assert direct == wrapped
        assert direct.recovery_id == wrapped.recovery_id


def test_recover_zero_approval_structural_closure_without_hmac_claim(
    tmp_path: Path,
) -> None:
    """Reconcile proves stored approval indexes+stage bytes; no credential reverify."""
    store = service_open(tmp_path)
    service = build_service(store, FakeGateway(), MutableClock())
    targets, market, account, planner, sources, verified, plan = _approval_bundle(
        tmp_path, store, zero_intent=True
    )
    service.plan_and_stage(
        targets=targets,
        target_identity=_hex("targets"),
        market=market,
        account=account,
        planner_config=planner,
        approval=verified,
        approval_source_identities=sources,
    )
    recovered = recover_local_state(store)
    with store.transaction() as repo:
        direct = recover_repository_state(repo)
    assert direct == recovered
    assert recovered.allowed_zero_order_subject_ids == frozenset({plan.plan_id})
    assert recovered.commands == ()
    again = recover_local_state(store)
    assert again.recovery_id == recovered.recovery_id
    assert again.allowed_zero_order_subject_ids == recovered.allowed_zero_order_subject_ids
    store.close()


@pytest.mark.parametrize(
    "tamper",
    [
        "approval_raw_payload",
        "approval_index_identity",
        "stage_payload",
        "stage_identity",
    ],
)
def test_recover_zero_approval_rejects_approval_or_stage_structure_drift(
    tmp_path: Path, tamper: str
) -> None:
    """Reconcile ownership drifts fail closed; persisted logical snapshot stays exact."""
    store = service_open(tmp_path)
    service = build_service(store, FakeGateway(), MutableClock())
    targets, market, account, planner, sources, verified, plan = _approval_bundle(
        tmp_path, store, zero_intent=True
    )
    service.plan_and_stage(
        targets=targets,
        target_identity=_hex("targets"),
        market=market,
        account=account,
        planner_config=planner,
        approval=verified,
        approval_source_identities=sources,
    )
    database = tmp_path / "db" / "execution.db"
    before = _logical_execution_snapshot(database)
    with sqlite3.connect(database) as connection:
        if tamper == "approval_raw_payload":
            connection.execute(
                "UPDATE approval_receipts SET payload = "
                "CAST(payload || X'00' AS BLOB) WHERE plan_identity = ?",
                (plan.plan_id,),
            )
        elif tamper == "approval_index_identity":
            connection.execute(
                "UPDATE approval_receipts SET identity = ? WHERE plan_identity = ?",
                ("0" * 64, plan.plan_id),
            )
        elif tamper == "stage_payload":
            connection.execute(
                "UPDATE execution_stages SET payload = payload || X'00' WHERE plan_id = ?",
                (plan.plan_id,),
            )
        else:
            connection.execute(
                "UPDATE execution_stages SET identity = ? WHERE plan_id = ?",
                ("0" * 64, plan.plan_id),
            )
        connection.commit()
        if tamper == "approval_raw_payload":
            assert (
                connection.execute(
                    "SELECT typeof(payload) FROM approval_receipts "
                    "WHERE plan_identity = ?",
                    (plan.plan_id,),
                ).fetchone()[0]
                == "blob"
            )
    after_tamper = _logical_execution_snapshot(database)
    assert after_tamper != before
    with pytest.raises(
        RecoveryError, match="^RECOVERY_RISK_CLOSURE_INVALID$"
    ) as error:
        recover_local_state(store)
    _assert_detached(error.value)
    assert _logical_execution_snapshot(database) == after_tamper
    with store.transaction() as repo:
        with pytest.raises(
            RecoveryError, match="^RECOVERY_RISK_CLOSURE_INVALID$"
        ):
            recover_repository_state(repo)
    assert _logical_execution_snapshot(database) == after_tamper
    store.close()


def _rebuild_recovery_with_allow_set(
    value: RecoveryResult, allowed: frozenset[str]
) -> RecoveryResult:
    values = {
        field.name: getattr(value, field.name)
        for field in fields(RecoveryResult)
        if field.name != "recovery_id"
    }
    values["allowed_zero_order_subject_ids"] = allowed
    # Keep the original recovery_id so a forged allow-set cannot invent a new identity.
    return RecoveryResult(recovery_id=value.recovery_id, **values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    ["extra", "missing", "wrong"],
)
def test_recovery_result_allow_set_exact_with_observed_zero_subjects(
    tmp_path: Path, mutation: str
) -> None:
    """Allow-set is uniquely fixed by observed legal zero receipts; not a free dimension."""
    store = service_open(tmp_path)
    service = build_service(store, FakeGateway(), MutableClock())
    targets, market, account, planner, sources, verified, plan = _approval_bundle(
        tmp_path, store, zero_intent=True
    )
    service.plan_and_stage(
        targets=targets,
        target_identity=_hex("targets"),
        market=market,
        account=account,
        planner_config=planner,
        approval=verified,
        approval_source_identities=sources,
    )
    recovered = recover_local_state(store)
    legal = frozenset({plan.plan_id})
    assert recovered.allowed_zero_order_subject_ids == legal
    zero_subjects = frozenset(
        item.subject_id
        for item in recovered.risk_receipts
        if (
            item.transition_kind == "ORDER"
            and type(item.decision) is DurableOrderRiskDecision
            and item.decision.command_ids == ()
        )
    )
    assert zero_subjects == legal
    # Same receipts → same recovery_id; legal allow-set rebuilds exactly once.
    rebuilt = _rebuild_recovery_with_allow_set(recovered, legal)
    assert rebuilt.recovery_id == recovered.recovery_id
    assert rebuilt.allowed_zero_order_subject_ids == legal
    if mutation == "extra":
        forged = frozenset({plan.plan_id, _hex("extra-zero-subject")})
    elif mutation == "missing":
        forged = frozenset()
    else:
        forged = frozenset({_hex("wrong-zero-subject")})
    assert forged != legal
    # Identity digest ignores allow-set, so a forged set would keep the same id if accepted.
    provisional = RecoveryResult.__new__(RecoveryResult)
    for field in fields(RecoveryResult):
        if field.name == "recovery_id":
            continue
        object.__setattr__(
            provisional,
            field.name,
            forged
            if field.name == "allowed_zero_order_subject_ids"
            else getattr(recovered, field.name),
        )
    object.__setattr__(provisional, "recovery_id", "0" * 64)
    forged_identity = reconcile_module._recovery_identity(provisional)  # noqa: SLF001
    assert forged_identity == recovered.recovery_id
    with pytest.raises(RecoveryError, match="^RECOVERY_RESULT_INVALID$") as error:
        _rebuild_recovery_with_allow_set(recovered, forged)
    _assert_detached(error.value)
    store.close()
