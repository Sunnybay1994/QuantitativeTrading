"""M4-P7 deterministic and redacted EOD execution reports."""

from __future__ import annotations

import builtins
import dataclasses
import datetime as dt
import hashlib
import json
import socket
import sqlite3
from pathlib import Path
from decimal import Decimal

import pytest

import quant.execution.reconcile as reconcile_module
import quant.reporting.execution_report as report_module
from quant.domain.enums import OrderStatus

from quant.execution.contracts import build_account_snapshot
from quant.execution.reconcile import (
    BrokerOrderObservation,
    build_broker_snapshot,
    recover_local_state,
    reconcile,
)
from quant.execution.risk import DailyRiskCounters
from quant.execution.risk_wire import build_order_risk_receipt
from quant.execution.store import ExecutionStore
from quant.reporting.execution_report import (
    ExecutionReportError,
    build_execution_report,
    encode_execution_report,
)
from tests.unit.test_execution_service import (
    FakeGateway,
    MutableClock,
    _service,
    _stage,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 7, 19, 8, tzinfo=UTC)


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _empty_inputs(tmp_path: Path):
    store = ExecutionStore.open("sqlite:///report/empty.db", trusted_root=tmp_path)
    try:
        recovery = recover_local_state(store)
    finally:
        store.close()
    account = build_account_snapshot(as_of=NOW, positions=(), cash=())
    broker = build_broker_snapshot(
        source_identity=_hex("paper-evidence"),
        as_of=NOW,
        finality="END_OF_DAY",
        account=account,
        orders=(),
        events=(),
    )
    return recovery, reconcile(recovery, broker, NOW)


def _filled_inputs(tmp_path: Path):
    store = ExecutionStore.open("sqlite:///report/filled.db", trusted_root=tmp_path)
    gateway = FakeGateway()
    gateway.partial_then_fill = True
    try:
        service = _service(store, gateway, MutableClock())
        staged = _stage(service, tmp_path)
        dispatched = service.dispatch_pending(limit=1)
        assert dispatched.items[0].code == "SENT"
        recovery = recover_local_state(store)
    finally:
        store.close()
    assert recovery.checkpoint is not None
    aggregate = recovery.order_aggregates[0]
    account = build_account_snapshot(
        as_of=NOW,
        positions=recovery.checkpoint.positions,
        cash=recovery.checkpoint.cash,
    )
    broker = build_broker_snapshot(
        source_identity=_hex("retained-paper-query"),
        as_of=NOW,
        finality="END_OF_DAY",
        account=account,
        orders=(
            BrokerOrderObservation(
                broker_order_id="PAPER-1",
                command_id=aggregate.command_id,
                status=aggregate.status,
                cumulative_quantity=aggregate.filled_quantity,
                observed_event_ids=tuple(sorted(aggregate.applied_event_ids)),
            ),
        ),
        events=recovery.events,
    )
    return recovery, reconcile(recovery, broker, NOW), staged.risk


def test_empty_report_is_deterministic_content_addressed_and_gate_passed(
    tmp_path: Path,
) -> None:
    recovery, reconciliation = _empty_inputs(tmp_path)
    first = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )
    second = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )

    assert first == second
    assert first.gate_passed
    assert first.totals.commands == first.totals.fills == 0
    assert encode_execution_report(first) == encode_execution_report(second)
    assert not encode_execution_report(first).endswith(b"\n")


def test_filled_report_covers_orders_fills_ledger_risk_and_redacts_raw_text(
    tmp_path: Path,
) -> None:
    recovery, reconciliation, risk = _filled_inputs(tmp_path)
    hostile_rule = dataclasses.replace(
        risk.rule_results[0],
        subject="broker:PAPER-1",
        detail="TOKEN C:\\private\\execution.db SELECT * FROM secret",
    )
    hostile_risk = dataclasses.replace(
        risk, rule_results=(hostile_rule, *risk.rule_results[1:])
    )
    retained = recovery.risk_receipts[0]
    hostile_receipt = build_order_risk_receipt(
        sequence=retained.sequence,
        previous_receipt_id=retained.previous_receipt_id,
        risk_counter_key=retained.risk_counter_key,
        predecessor_counters=DailyRiskCounters(
            session_date=hostile_risk.projected_counters.session_date,
            order_count=0,
            cancel_count=0,
            buy_notional=Decimal(0),
        ),
        decision=hostile_risk,
    )
    object.__setattr__(recovery, "risk_receipts", (hostile_receipt,))
    object.__setattr__(
        recovery, "recovery_id", reconcile_module._recovery_identity(recovery)
    )
    object.__setattr__(reconciliation, "local_recovery_id", recovery.recovery_id)
    object.__setattr__(
        reconciliation,
        "reconciliation_id",
        reconcile_module._reconciliation_identity(reconciliation),
    )

    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )
    encoded = encode_execution_report(report)
    decoded = json.loads(encoded)

    assert report.gate_passed
    assert report.totals.orders == 1
    assert report.totals.fills == 2
    assert report.totals.positions == 1
    assert report.totals.cash_balances == 1
    assert report.totals.risk_events == len(
        recovery.risk_receipts[0].decision.rule_results  # type: ignore[union-attr]
    )
    assert report.orders[0].broker_order_identity == _hex("PAPER-1")
    assert decoded["report_id"] == report.report_id
    for secret in (b"PAPER-1", b"TOKEN", b"private", b"SELECT", b"secret"):
        assert secret not in encoded
        assert secret.decode() not in repr(report)


def test_durable_risk_projection_is_deterministic(tmp_path: Path) -> None:
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    forward = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )
    reversed_report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )

    assert encode_execution_report(forward) == encode_execution_report(reversed_report)
    assert forward.report_id == reversed_report.report_id


def test_forged_or_cross_recovery_inputs_fail_without_retained_context(
    tmp_path: Path,
) -> None:
    recovery, reconciliation = _empty_inputs(tmp_path)
    object.__setattr__(recovery, "disposition", "MANUAL_REQUIRED")
    with pytest.raises(
        ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"
    ) as info:
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
        )
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_caller_risk_injection_is_rejected_and_missing_receipt_fails(
    tmp_path: Path,
) -> None:
    recovery, reconciliation, risk = _filled_inputs(tmp_path)
    with pytest.raises(TypeError):
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
            risk_decisions=(risk,),  # type: ignore[call-arg]
        )

    object.__setattr__(recovery, "risk_receipts", ())
    object.__setattr__(
        recovery, "recovery_id", reconcile_module._recovery_identity(recovery)
    )
    object.__setattr__(reconciliation, "local_recovery_id", recovery.recovery_id)
    object.__setattr__(
        reconciliation,
        "reconciliation_id",
        reconcile_module._reconciliation_identity(reconciliation),
    )
    with pytest.raises(ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"):
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
        )


def test_builder_and_encoder_perform_zero_io_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery, reconciliation = _empty_inputs(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("IO forbidden")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )
    assert encode_execution_report(report)


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_hostile_public_receipt_verifier_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    recovery, reconciliation, _ = _filled_inputs(tmp_path)

    def hostile(**_: object) -> None:
        raise error_type("TOKEN C:\\private\\oms.db SELECT secret")

    monkeypatch.setattr(
        report_module, "verify_risk_receipt_semantic_closure", hostile
    )
    with pytest.raises(
        ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"
    ) as error:
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert "TOKEN" not in repr(error.value)


def test_mutated_report_is_rejected_by_encoder(tmp_path: Path) -> None:
    recovery, reconciliation = _empty_inputs(tmp_path)
    report = build_execution_report(
        recovery=recovery,
        reconciliation=reconciliation,
        as_of=NOW,
    )
    object.__setattr__(report, "gate_passed", False)
    with pytest.raises(ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"):
        encode_execution_report(report)


def test_self_consistent_hash_cannot_bless_hostile_mutated_report_line(
    tmp_path: Path,
) -> None:
    recovery2, reconciliation2, _ = _filled_inputs(tmp_path)
    report = build_execution_report(
        recovery=recovery2,
        reconciliation=reconciliation2,
        as_of=NOW,
    )
    object.__setattr__(report.orders[0], "symbol", "TOKEN C:\\private\\account.db")
    object.__setattr__(report, "report_id", report_module._report_identity(report))
    with pytest.raises(ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"):
        encode_execution_report(report)


def test_self_consistent_duplicate_recovery_command_is_not_silently_folded(
    tmp_path: Path,
) -> None:
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    command = recovery.commands[0]
    object.__setattr__(recovery, "commands", (command, command))
    object.__setattr__(
        recovery, "recovery_id", reconcile_module._recovery_identity(recovery)
    )
    object.__setattr__(
        reconciliation, "local_recovery_id", recovery.recovery_id
    )
    object.__setattr__(
        reconciliation,
        "reconciliation_id",
        reconcile_module._reconciliation_identity(reconciliation),
    )
    with pytest.raises(ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"):
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
        )


def test_self_consistent_aggregate_must_replay_all_retained_events(
    tmp_path: Path,
) -> None:
    recovery, reconciliation, _ = _filled_inputs(tmp_path)
    forged = dataclasses.replace(
        recovery.order_aggregates[0],
        status=OrderStatus.SUBMITTED,
        filled_quantity=0,
    )
    object.__setattr__(recovery, "order_aggregates", (forged,))
    object.__setattr__(
        recovery, "recovery_id", reconcile_module._recovery_identity(recovery)
    )
    object.__setattr__(
        reconciliation, "local_recovery_id", recovery.recovery_id
    )
    object.__setattr__(
        reconciliation,
        "reconciliation_id",
        reconcile_module._reconciliation_identity(reconciliation),
    )
    with pytest.raises(ExecutionReportError, match="^EXECUTION_REPORT_INVALID$"):
        build_execution_report(
            recovery=recovery,
            reconciliation=reconciliation,
            as_of=NOW,
        )
