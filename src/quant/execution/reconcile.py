"""Deterministic local recovery and zero-I/O PAPER reconciliation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast

from quant.backtest.ledger import LedgerEntry, LedgerState
from quant.backtest.ledger_adapter import (
    ExecutionLedgerContext,
    decode_ledger_context,
    encode_ledger_context,
    verify_execution_ledger_context,
)
from quant.backtest.ledger_wire import (
    decode_ledger_entry,
    decode_ledger_state,
    encode_ledger_entry,
    encode_ledger_state,
)
from quant.domain.enums import OrderStatus
from quant.execution.contracts import (
    AccountSnapshot,
    CancelCommand,
    ExecutionEvent,
    OrderCommand,
    build_account_snapshot_identity,
    build_cancel_command_identity,
    build_execution_event_identity,
    build_order_command_identity,
)
from quant.execution.oms import OrderAggregate, new_order_aggregate, reduce_order
from quant.execution.risk import DailyRiskCounters
from quant.execution.risk_wire import (
    DurableCancelRiskDecision,
    DurableOrderRiskDecision,
    DurableRiskTransitionReceipt,
    GENESIS_RECEIPT_ID,
    counter_identity,
    counter_payload,
    decode_risk_receipt,
    encode_risk_receipt,
    verify_risk_receipt_semantic_closure,
)
from quant.execution.store import (
    CancelOutboxDelivery,
    LEDGER_CHECKPOINT_KEY,
    ExecutionStore,
    OutboxDelivery,
    OutboxDeliveryState,
    StoredCancelEventLink,
    StoredCancelCommand,
    StoredRecord,
    StoredRiskTransitionReceipt,
)
from quant.execution.wire import (
    decode_cancel_command,
    decode_execution_event,
    decode_order_aggregate,
    decode_order_command,
    encode_cancel_command,
    encode_execution_event,
    encode_order_aggregate,
    encode_order_command,
)

RecoveryDisposition = Literal["READY", "QUERY_REQUIRED", "MANUAL_REQUIRED"]
DifferenceAction = Literal["AUTOMATIC_RETRY", "QUERY_REQUIRED", "MANUAL_REQUIRED"]
BrokerSnapshotFinality = Literal["INTRADAY", "END_OF_DAY"]

_ACTIONS = frozenset({"AUTOMATIC_RETRY", "QUERY_REQUIRED", "MANUAL_REQUIRED"})
_DISPOSITIONS = frozenset({"READY", "QUERY_REQUIRED", "MANUAL_REQUIRED"})
_FINALITIES = frozenset({"INTRADAY", "END_OF_DAY"})
_ACTION_RANK = {"AUTOMATIC_RETRY": 0, "QUERY_REQUIRED": 1, "MANUAL_REQUIRED": 2}
_HEX = frozenset("0123456789abcdef")


class RecoveryError(ValueError):
    """Stable local recovery failure without retained hostile context."""


class ReconciliationError(ValueError):
    """Stable reconciliation failure without retained hostile context."""


@dataclass(frozen=True, slots=True)
class RecoveryIssue:
    code: str
    subject: str
    action: DifferenceAction

    def __post_init__(self) -> None:
        if not _text(self.code) or not _text(self.subject) or self.action not in _ACTIONS:
            raise RecoveryError("RECOVERY_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    recovery_id: str
    disposition: RecoveryDisposition
    commands: tuple[OrderCommand, ...]
    events: tuple[ExecutionEvent, ...]
    order_aggregates: tuple[OrderAggregate, ...]
    deliveries: tuple[OutboxDelivery, ...]
    cancel_commands: tuple[CancelCommand, ...]
    cancel_deliveries: tuple[CancelOutboxDelivery, ...]
    cancel_event_links: tuple[StoredCancelEventLink, ...]
    ledger_entries: tuple[LedgerEntry, ...]
    ledger_contexts: tuple[ExecutionLedgerContext, ...]
    checkpoint: LedgerState | None
    issues: tuple[RecoveryIssue, ...]
    risk_receipts: tuple[DurableRiskTransitionReceipt, ...] = ()

    def __post_init__(self) -> None:
        valid = False
        try:
            valid = (
                self.disposition in _DISPOSITIONS
                and _hex64(self.recovery_id)
                and self.issues
                == tuple(sorted(
                    self.issues,
                    key=lambda item: (_ACTION_RANK[item.action], item.code, item.subject),
                ))
                and self.disposition
                == _disposition_from_actions(tuple(item.action for item in self.issues))
                and self.cancel_commands
                == tuple(sorted(self.cancel_commands, key=lambda item: item.cancel_id))
                and len({item.cancel_id for item in self.cancel_commands})
                == len(self.cancel_commands)
                and self.cancel_deliveries
                == tuple(sorted(self.cancel_deliveries, key=lambda item: item.cancel_id))
                and len({item.cancel_id for item in self.cancel_deliveries})
                == len(self.cancel_deliveries)
                and self.cancel_event_links
                == tuple(sorted(
                    self.cancel_event_links,
                    key=lambda item: (item.cancel_id, item.event_id),
                ))
                and len({(item.cancel_id, item.event_id) for item in self.cancel_event_links})
                == len(self.cancel_event_links)
                and (
                    not self.commands and not self.cancel_commands
                    or bool(self.risk_receipts)
                )
                and _valid_recovery_receipts(
                    self.risk_receipts, self.commands, self.cancel_commands
                )
                and self.recovery_id == _recovery_identity(self)
            )
        except Exception:
            pass
        if not valid:
            raise RecoveryError("RECOVERY_RESULT_INVALID") from None


@dataclass(frozen=True, slots=True)
class BrokerOrderObservation:
    broker_order_id: str
    command_id: str | None
    status: OrderStatus
    cumulative_quantity: int
    observed_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not _text(self.broker_order_id)
            or (self.command_id is not None and not _hex64(self.command_id))
            or type(self.status) is not OrderStatus
            or type(self.cumulative_quantity) is not int
            or self.cumulative_quantity < 0
            or type(self.observed_event_ids) is not tuple
            or any(not _hex64(value) for value in self.observed_event_ids)
            or self.observed_event_ids != tuple(sorted(set(self.observed_event_ids)))
        ):
            raise ReconciliationError("BROKER_SNAPSHOT_INVALID")


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    snapshot_id: str
    source_identity: str
    as_of: dt.datetime
    finality: BrokerSnapshotFinality
    account: AccountSnapshot
    orders: tuple[BrokerOrderObservation, ...]
    events: tuple[ExecutionEvent, ...]

    def __post_init__(self) -> None:
        valid = False
        try:
            valid = (
                _hex64(self.snapshot_id)
                and _hex64(self.source_identity)
                and _utc(self.as_of)
                and self.finality in _FINALITIES
                and type(self.account) is AccountSnapshot
                and type(self.orders) is tuple
                and not any(type(item) is not BrokerOrderObservation for item in self.orders)
                and self.orders
                == tuple(sorted(self.orders, key=lambda item: item.broker_order_id))
                and len({item.broker_order_id for item in self.orders}) == len(self.orders)
                and type(self.events) is tuple
                and not any(type(item) is not ExecutionEvent for item in self.events)
                and self.events == tuple(sorted(self.events, key=lambda item: item.event_id))
                and len({item.event_id for item in self.events}) == len(self.events)
                and self.snapshot_id == _broker_identity(self)
            )
        except Exception:
            pass
        if not valid:
            raise ReconciliationError("BROKER_SNAPSHOT_INVALID")


@dataclass(frozen=True, slots=True)
class ReconciliationDifference:
    code: str
    action: DifferenceAction
    subject: str
    local_identity: str | None
    broker_identity: str | None

    def __post_init__(self) -> None:
        if (
            not _text(self.code)
            or self.action not in _ACTIONS
            or not _text(self.subject)
            or (self.local_identity is not None and not _hex64(self.local_identity))
            or (self.broker_identity is not None and not _hex64(self.broker_identity))
        ):
            raise ReconciliationError("RECONCILIATION_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reconciliation_id: str
    local_recovery_id: str
    broker_snapshot_id: str
    as_of: dt.datetime
    gate_passed: bool
    disposition: RecoveryDisposition
    differences: tuple[ReconciliationDifference, ...]

    def __post_init__(self) -> None:
        valid = False
        try:
            valid = (
                _hex64(self.reconciliation_id)
                and _hex64(self.local_recovery_id)
                and _hex64(self.broker_snapshot_id)
                and _utc(self.as_of)
                and type(self.gate_passed) is bool
                and self.disposition in _DISPOSITIONS
                and type(self.differences) is tuple
                and self.differences == tuple(sorted(self.differences, key=_difference_key))
                and len({item.subject for item in self.differences}) == len(self.differences)
                and self.disposition
                == _disposition_from_actions(tuple(item.action for item in self.differences))
                and self.gate_passed == (not self.differences)
                and self.reconciliation_id == _reconciliation_identity(self)
            )
        except Exception:
            pass
        if not valid:
            raise ReconciliationError("RECONCILIATION_RESULT_INVALID")


def build_broker_snapshot(
    *, source_identity: str, as_of: dt.datetime,
    finality: BrokerSnapshotFinality, account: AccountSnapshot,
    orders: tuple[BrokerOrderObservation, ...], events: tuple[ExecutionEvent, ...],
) -> BrokerSnapshot:
    """Build a canonical broker observation bundle from already retained evidence."""
    result: BrokerSnapshot | None = None
    try:
        provisional = BrokerSnapshot.__new__(BrokerSnapshot)
        values = {
            "source_identity": source_identity, "as_of": as_of, "finality": finality,
            "account": account,
            "orders": tuple(sorted(orders, key=lambda item: item.broker_order_id)),
            "events": tuple(sorted(events, key=lambda item: item.event_id)),
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "snapshot_id", "0" * 64)
        result = BrokerSnapshot(
            snapshot_id=_broker_identity(provisional), **values  # type: ignore[arg-type]
        )
    except Exception:
        pass
    if result is None:
        raise ReconciliationError("BROKER_SNAPSHOT_INVALID") from None
    return result


def recover_local_state(store: ExecutionStore) -> RecoveryResult:
    """Recover one transaction-consistent local state without changing the store."""
    result: RecoveryResult | None = None
    cancel_closure_invalid = False
    risk_closure_invalid = False
    try:
        if type(store) is not ExecutionStore:
            raise ValueError
        with store.transaction() as repo:
            rows = repo.read_recovery_rows()
            cancel_counter_rows = {
                row.risk_counter_key: repo.get_scoped_daily_risk_counters(
                    row.risk_counter_key
                )
                for row in rows.cancel_commands
            }
        commands: list[OrderCommand] = []
        command_map: dict[str, OrderCommand] = {}
        for row in rows.commands:
            command = decode_order_command(row.payload)
            if (
                row.key != command.command_id or row.identity != command.command_id
                or encode_order_command(command) != row.payload
                or build_order_command_identity(command) != row.identity
            ):
                raise ValueError
            commands.append(command)
            command_map[command.command_id] = command

        events: list[ExecutionEvent] = []
        event_map: dict[str, ExecutionEvent] = {}
        for event_row in rows.events:
            command = command_map[event_row.command_id]
            event = decode_execution_event(event_row.payload, command=command)
            if (
                event_row.event_id != event.event_id
                or event_row.identity != event.event_id
                or encode_execution_event(event) != event_row.payload
            ):
                raise ValueError
            events.append(event)
            event_map[event.event_id] = event

        aggregates: list[OrderAggregate] = []
        aggregate_map: dict[str, OrderAggregate] = {}
        for row in rows.order_aggregates:
            command = command_map[row.key]
            aggregate = decode_order_aggregate(row.payload, command=command)
            if hashlib.sha256(row.payload).hexdigest() != row.identity:
                raise ValueError
            rebuilt = new_order_aggregate(command)
            for event_id in aggregate.applied_event_ids:
                rebuilt = reduce_order(rebuilt, command, event_map[event_id])
            if rebuilt != aggregate or encode_order_aggregate(aggregate) != row.payload:
                raise ValueError
            aggregates.append(aggregate)
            aggregate_map[aggregate.command_id] = aggregate

        cancel_commands: list[CancelCommand] = []
        cancel_map: dict[str, CancelCommand] = {}
        cancel_rows_by_id = {row.cancel_id: row for row in rows.cancel_commands}
        manual_cancel_subjects: set[str] = set()
        cancels_by_counter: dict[str, list[CancelCommand]] = {}
        for cancel_row in rows.cancel_commands:
            try:
                cancel_command = decode_cancel_command(cancel_row.payload)
                build_cancel_command_identity(cancel_command)
                if encode_cancel_command(cancel_command) != cancel_row.payload:
                    raise ValueError
            except Exception:
                raise _CancelRecoveryClosureError from None
            cancel_commands.append(cancel_command)
            cancel_map[cancel_command.cancel_id] = cancel_command
            cancels_by_counter.setdefault(cancel_row.risk_counter_key, []).append(
                cancel_command
            )
            target_command = command_map.get(cancel_command.command_id)
            current_aggregate = aggregate_map.get(cancel_command.command_id)
            if (
                cancel_row.cancel_id != cancel_command.cancel_id
                or cancel_row.identity != cancel_command.cancel_id
                or cancel_row.command_id != cancel_command.command_id
                or target_command is None
                or current_aggregate is None
            ):
                manual_cancel_subjects.add(cancel_command.cancel_id)
                continue
            prefix_length = len(cancel_command.observed_event_ids)
            if (
                current_aggregate.applied_event_ids[:prefix_length]
                != cancel_command.observed_event_ids
            ):
                manual_cancel_subjects.add(cancel_command.cancel_id)
                continue
            try:
                snapshot = new_order_aggregate(target_command)
                for event_id in cancel_command.observed_event_ids:
                    snapshot_event = event_map[event_id]
                    if snapshot_event.command_id != cancel_command.command_id:
                        raise ValueError
                    snapshot = reduce_order(snapshot, target_command, snapshot_event)
            except Exception:
                manual_cancel_subjects.add(cancel_command.cancel_id)
                continue
            if (
                snapshot.status is not cancel_command.aggregate_status
                or snapshot.filled_quantity != cancel_command.observed_filled_quantity
                or snapshot.broker_order_id != cancel_command.broker_order_id
                or snapshot.last_event_at != cancel_command.observed_last_event_at
            ):
                manual_cancel_subjects.add(cancel_command.cancel_id)

        target_cancel_ids: dict[str, str] = {}
        for cancel in cancel_commands:
            prior = target_cancel_ids.setdefault(cancel.command_id, cancel.cancel_id)
            if prior != cancel.cancel_id:
                manual_cancel_subjects.update((prior, cancel.cancel_id))

        for counter_key, grouped in cancels_by_counter.items():
            dates = {
                command_map[item.command_id].intent.session_date
                for item in grouped
                if item.command_id in command_map
            }
            counter_row = cancel_counter_rows.get(counter_key)
            counter_valid = len(dates) == 1 and counter_row is not None
            cancel_count = -1
            if counter_valid:
                try:
                    assert counter_row is not None
                    cancel_count = _decode_cancel_counter(counter_row, next(iter(dates)))
                except Exception:
                    counter_valid = False
            if not counter_valid or cancel_count < len(grouped):
                manual_cancel_subjects.update(item.cancel_id for item in grouped)

        cancel_deliveries = tuple(rows.cancel_deliveries)
        delivery_map = {item.cancel_id: item for item in cancel_deliveries}
        for cancel_delivery in cancel_deliveries:
            linked_cancel = cancel_map.get(cancel_delivery.cancel_id)
            stored_cancel = cancel_rows_by_id.get(cancel_delivery.cancel_id)
            if (
                linked_cancel is None
                or stored_cancel is None
                or cancel_delivery.command_id != linked_cancel.command_id
                or cancel_delivery.identity != linked_cancel.cancel_id
                or cancel_delivery.payload != stored_cancel.payload
            ):
                manual_cancel_subjects.add(cancel_delivery.cancel_id)
        for cancel in cancel_commands:
            if cancel.cancel_id not in delivery_map:
                manual_cancel_subjects.add(cancel.cancel_id)

        cancel_event_links = tuple(rows.cancel_event_links)
        links_by_cancel: dict[str, list[StoredCancelEventLink]] = {}
        for link in cancel_event_links:
            links_by_cancel.setdefault(link.cancel_id, []).append(link)
            linked_cancel = cancel_map.get(link.cancel_id)
            linked_event = event_map.get(link.event_id)
            linked_aggregate = (
                None
                if linked_cancel is None
                else aggregate_map.get(linked_cancel.command_id)
            )
            if (
                linked_cancel is None
                or linked_event is None
                or linked_aggregate is None
                or link.command_id != linked_cancel.command_id
                or linked_event.command_id != linked_cancel.command_id
                or link.event_id in linked_cancel.observed_event_ids
                or link.event_id not in linked_aggregate.applied_event_ids
            ):
                manual_cancel_subjects.add(link.cancel_id)
        for cancel in cancel_commands:
            final_delivery = delivery_map.get(cancel.cancel_id)
            if final_delivery is not None and final_delivery.state is OutboxDeliveryState.SENT:
                linked_aggregate_state = aggregate_map.get(cancel.command_id)
                linked_ids = {
                    item.event_id for item in links_by_cancel.get(cancel.cancel_id, ())
                }
                expected_ids = (
                    set()
                    if linked_aggregate_state is None
                    else set(
                        linked_aggregate_state.applied_event_ids[
                            len(cancel.observed_event_ids) :
                        ]
                    )
                )
                if not expected_ids or linked_ids != expected_ids:
                    manual_cancel_subjects.add(cancel.cancel_id)

        risk_receipts = _verify_risk_closure(
            stored_receipts=rows.risk_transition_receipts,
            counter_rows=rows.risk_counter_rows,
            command_map=command_map,
            stored_cancel_rows=cancel_rows_by_id,
            cancel_map=cancel_map,
        )

        contexts: list[ExecutionLedgerContext] = []
        for row in rows.ledger_contexts:
            command = command_map[row.key]
            context = decode_ledger_context(row.payload)
            context = verify_execution_ledger_context(context, command=command)
            if row.identity != context.context_id or encode_ledger_context(context) != row.payload:
                raise ValueError
            contexts.append(context)

        entries: list[LedgerEntry] = []
        for row in rows.ledger_entries:
            entry = decode_ledger_entry(row.payload)
            if row.key != entry.entry_id or row.identity != entry.entry_id or encode_ledger_entry(entry) != row.payload:
                raise ValueError
            entries.append(entry)

        checkpoint: LedgerState | None = None
        if len(rows.ledger_checkpoints) > 1:
            raise ValueError
        if rows.ledger_checkpoints:
            checkpoint_row = rows.ledger_checkpoints[0]
            checkpoint = decode_ledger_state(checkpoint_row.payload)
            entry_ids = {item.entry_id for item in entries}
            if (
                checkpoint_row.checkpoint_key != LEDGER_CHECKPOINT_KEY
                or checkpoint_row.identity != checkpoint.state_id
                or encode_ledger_state(checkpoint) != checkpoint_row.payload
                or (
                    checkpoint_row.last_entry_id is not None
                    and checkpoint_row.last_entry_id not in entry_ids
                )
                or not set(checkpoint.applied_event_ids).issubset(event_map)
            ):
                raise ValueError
            if any(
                command.intent.account_snapshot_id
                != checkpoint.origin_account_snapshot_id
                for command in commands
            ):
                raise ValueError

        deliveries = tuple(rows.outbox_deliveries)
        for order_delivery in deliveries:
            decoded_command = decode_order_command(order_delivery.payload)
            if (
                order_delivery.command_id not in command_map
                or decoded_command != command_map[order_delivery.command_id]
                or order_delivery.outbox_key != order_delivery.command_id
                or order_delivery.identity != order_delivery.command_id
                or encode_order_command(decoded_command) != order_delivery.payload
            ):
                raise ValueError

        context_ids = {item.command_id for item in contexts}
        aggregate_ids = {item.command_id for item in aggregates}
        delivery_ids = {item.command_id for item in deliveries}
        issues: list[RecoveryIssue] = []
        for order_delivery in deliveries:
            if order_delivery.state is OutboxDeliveryState.UNKNOWN:
                issues.append(RecoveryIssue(
                    "DELIVERY_UNKNOWN", order_delivery.command_id, "QUERY_REQUIRED"
                ))
        for cancel_delivery in cancel_deliveries:
            if cancel_delivery.state is OutboxDeliveryState.LEASED:
                issues.append(RecoveryIssue(
                    "CANCEL_DELIVERY_LEASED",
                    cancel_delivery.cancel_id,
                    "QUERY_REQUIRED",
                ))
            elif cancel_delivery.state is OutboxDeliveryState.UNKNOWN:
                issues.append(RecoveryIssue(
                    "CANCEL_DELIVERY_UNKNOWN",
                    cancel_delivery.cancel_id,
                    "QUERY_REQUIRED",
                ))
        for cancel_id in manual_cancel_subjects:
            issues.append(RecoveryIssue(
                "CANCEL_RECOVERY_CLOSURE_INVALID",
                cancel_id,
                "MANUAL_REQUIRED",
            ))
        for command in commands:
            if command.command_id not in context_ids:
                issues.append(RecoveryIssue("LEGACY_LEDGER_CONTEXT_MISSING", command.command_id, "MANUAL_REQUIRED"))
            if command.command_id not in aggregate_ids:
                issues.append(RecoveryIssue(
                    "LEGACY_ORDER_AGGREGATE_MISSING", command.command_id,
                    "MANUAL_REQUIRED",
                ))
            if command.command_id not in delivery_ids:
                issues.append(RecoveryIssue(
                    "LEGACY_DELIVERY_MISSING", command.command_id,
                    "MANUAL_REQUIRED",
                ))
        if commands and checkpoint is None:
            issues.append(RecoveryIssue("LEGACY_LEDGER_CHECKPOINT_MISSING", LEDGER_CHECKPOINT_KEY, "MANUAL_REQUIRED"))
        issues.sort(key=lambda item: (_ACTION_RANK[item.action], item.code, item.subject))
        disposition = _disposition_from_actions(tuple(item.action for item in issues))
        provisional = RecoveryResult.__new__(RecoveryResult)
        values = {
            "disposition": disposition,
            "commands": tuple(commands), "events": tuple(events),
            "order_aggregates": tuple(aggregates), "deliveries": deliveries,
            "cancel_commands": tuple(cancel_commands),
            "cancel_deliveries": cancel_deliveries,
            "cancel_event_links": cancel_event_links,
            "ledger_entries": tuple(entries), "ledger_contexts": tuple(contexts),
            "checkpoint": checkpoint, "issues": tuple(issues),
            "risk_receipts": risk_receipts,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "recovery_id", "0" * 64)
        result = RecoveryResult(recovery_id=_recovery_identity(provisional), **values)  # type: ignore[arg-type]
    except _CancelRecoveryClosureError:
        cancel_closure_invalid = True
    except _RiskRecoveryClosureError:
        risk_closure_invalid = True
    except Exception:
        pass
    if cancel_closure_invalid:
        raise RecoveryError("CANCEL_RECOVERY_CLOSURE_INVALID") from None
    if risk_closure_invalid:
        raise RecoveryError("RECOVERY_RISK_CLOSURE_INVALID") from None
    if result is None:
        raise RecoveryError("RECOVERY_LOCAL_INVALID") from None
    return result


def reconcile(
    local: RecoveryResult, broker_snapshot: BrokerSnapshot, as_of: dt.datetime,
) -> ReconciliationResult:
    """Compare proven local and broker snapshots without performing IO or repair."""
    result: ReconciliationResult | None = None
    try:
        if (
            type(local) is not RecoveryResult or local.recovery_id != _recovery_identity(local)
            or type(broker_snapshot) is not BrokerSnapshot
            or broker_snapshot.snapshot_id != _broker_identity(broker_snapshot)
            or not _utc(as_of) or broker_snapshot.as_of != as_of
        ):
            raise ValueError
        build_account_snapshot_identity(broker_snapshot.account)
        for event in broker_snapshot.events:
            build_execution_event_identity(event)

        differences: list[ReconciliationDifference] = [
            ReconciliationDifference(issue.code, issue.action, issue.subject, local.recovery_id, None)
            for issue in local.issues
        ]
        aggregates = {item.command_id: item for item in local.order_aggregates}
        deliveries = {item.command_id: item for item in local.deliveries}
        observed_commands: set[str] = set()
        broker_event_ids = {item.event_id for item in broker_snapshot.events}
        for order in broker_snapshot.orders:
            if order.command_id is None:
                differences.append(ReconciliationDifference(
                    "BROKER_ORDER_UNKNOWN", "MANUAL_REQUIRED", f"broker:{order.broker_order_id}",
                    None, broker_snapshot.snapshot_id,
                ))
                continue
            observed_commands.add(order.command_id)
            aggregate = aggregates.get(order.command_id)
            if aggregate is None:
                differences.append(ReconciliationDifference(
                    "BROKER_ORDER_LOCAL_MISSING", "MANUAL_REQUIRED", order.command_id,
                    None, broker_snapshot.snapshot_id,
                ))
                continue
            if (
                aggregate.status is not order.status
                or aggregate.filled_quantity != order.cumulative_quantity
                or aggregate.broker_order_id != order.broker_order_id
                or set(order.observed_event_ids) != set(aggregate.applied_event_ids)
                or not set(order.observed_event_ids).issubset(broker_event_ids)
            ):
                differences.append(ReconciliationDifference(
                    "BROKER_ORDER_STATE_MISMATCH", "MANUAL_REQUIRED", order.command_id,
                    _aggregate_identity(aggregate), broker_snapshot.snapshot_id,
                ))

        local_event_ids = {item.event_id for item in local.events}
        seen_economic_events: dict[tuple[object, ...], str] = {}
        for event in broker_snapshot.events:
            economic_key = (
                event.command_id, event.event_type.value,
                event.cumulative_quantity, event.last_quantity,
                None if event.last_price is None else str(event.last_price),
            )
            prior = seen_economic_events.get(economic_key)
            if prior is not None and prior != event.event_id:
                differences.append(ReconciliationDifference(
                    "BROKER_ECONOMIC_EVENT_DUPLICATE", "MANUAL_REQUIRED",
                    event.event_id, None, event.event_id,
                ))
            else:
                seen_economic_events[economic_key] = event.event_id
            if (
                event.command_id not in observed_commands
                or event.event_id not in local_event_ids
            ):
                differences.append(ReconciliationDifference(
                    "BROKER_EVENT_LOCAL_MISSING", "MANUAL_REQUIRED",
                    event.event_id, None, event.event_id,
                ))

        for command in local.commands:
            if command.command_id in observed_commands:
                continue
            delivery = deliveries.get(command.command_id)
            if delivery is not None and delivery.state is OutboxDeliveryState.PENDING:
                action: DifferenceAction = "AUTOMATIC_RETRY"
                code = "LOCAL_NOT_SENT"
            elif delivery is not None and delivery.state in {
                OutboxDeliveryState.LEASED, OutboxDeliveryState.UNKNOWN,
            }:
                action, code = "QUERY_REQUIRED", "LOCAL_DELIVERY_UNCERTAIN"
            else:
                action, code = "QUERY_REQUIRED", "BROKER_ORDER_MISSING"
            differences.append(ReconciliationDifference(
                code, action, command.command_id, command.command_id, None,
            ))

        checkpoint = local.checkpoint
        if checkpoint is None:
            if broker_snapshot.account.positions or broker_snapshot.account.cash:
                differences.append(ReconciliationDifference(
                    "BROKER_ACCOUNT_LOCAL_MISSING", "MANUAL_REQUIRED", "account",
                    None, broker_snapshot.account.snapshot_id,
                ))
        elif (
            checkpoint.positions != broker_snapshot.account.positions
            or checkpoint.cash != broker_snapshot.account.cash
        ):
            differences.append(ReconciliationDifference(
                "BROKER_ACCOUNT_MISMATCH", "MANUAL_REQUIRED", "account",
                checkpoint.state_id, broker_snapshot.account.snapshot_id,
            ))
        if broker_snapshot.finality == "INTRADAY":
            differences.append(ReconciliationDifference(
                "BROKER_SNAPSHOT_INTRADAY", "QUERY_REQUIRED", "snapshot-finality",
                None, broker_snapshot.snapshot_id,
            ))
        differences = _unique_sorted_differences(differences)
        disposition = _disposition_from_actions(tuple(item.action for item in differences))
        gate_passed = not differences and local.disposition == "READY" and broker_snapshot.finality == "END_OF_DAY"
        provisional = ReconciliationResult.__new__(ReconciliationResult)
        values = {
            "local_recovery_id": local.recovery_id,
            "broker_snapshot_id": broker_snapshot.snapshot_id,
            "as_of": as_of, "gate_passed": gate_passed,
            "disposition": disposition, "differences": tuple(differences),
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "reconciliation_id", "0" * 64)
        result = ReconciliationResult(
            reconciliation_id=_reconciliation_identity(provisional), **values  # type: ignore[arg-type]
        )
    except Exception:
        pass
    if result is None:
        raise ReconciliationError("RECONCILIATION_INPUT_INVALID") from None
    return result


def _recovery_identity(value: RecoveryResult) -> str:
    return _hash({
        "commands": [hashlib.sha256(encode_order_command(item)).hexdigest()
                     for item in value.commands],
        "events": [hashlib.sha256(encode_execution_event(item)).hexdigest()
                   for item in value.events],
        "aggregates": [_aggregate_identity(item) for item in value.order_aggregates],
        "deliveries": [
            [item.outbox_key, item.command_id, item.state.value, item.attempt_count,
             _time(item.available_at), item.lease_owner, _optional_time(item.lease_until),
             _optional_time(item.terminal_at), item.last_error_code, item.identity,
             hashlib.sha256(item.payload).hexdigest()]
            for item in value.deliveries
        ],
        "cancel_commands": [
            hashlib.sha256(encode_cancel_command(item)).hexdigest()
            for item in value.cancel_commands
        ],
        "cancel_deliveries": [
            [item.cancel_id, item.command_id, item.state.value, item.attempt_count,
             _time(item.available_at), item.lease_owner, _optional_time(item.lease_until),
             _optional_time(item.terminal_at), item.last_error_code, item.identity,
             hashlib.sha256(item.payload).hexdigest()]
            for item in value.cancel_deliveries
        ],
        "cancel_event_links": [
            [item.cancel_id, item.event_id, item.command_id]
            for item in value.cancel_event_links
        ],
        "entries": [hashlib.sha256(encode_ledger_entry(item)).hexdigest()
                    for item in value.ledger_entries],
        "contexts": [hashlib.sha256(encode_ledger_context(item)).hexdigest()
                     for item in value.ledger_contexts],
        "checkpoint": None if value.checkpoint is None else hashlib.sha256(
            encode_ledger_state(value.checkpoint)
        ).hexdigest(),
        "issues": [[item.code, item.subject, item.action] for item in value.issues],
        "risk_receipts": [
            [item.receipt_id, hashlib.sha256(encode_risk_receipt(item)).hexdigest()]
            for item in value.risk_receipts
        ],
        "disposition": value.disposition,
    })


def _broker_identity(value: BrokerSnapshot) -> str:
    build_account_snapshot_identity(value.account)
    if value.account.as_of != value.as_of:
        raise ValueError
    event_map = {item.event_id: item for item in value.events}
    for event in value.events:
        build_execution_event_identity(event)
        if event.occurred_at > value.as_of:
            raise ValueError
    for order in value.orders:
        observed = tuple(event_map[event_id] for event_id in order.observed_event_ids)
        if order.command_id is None:
            if observed:
                raise ValueError
        elif any(
            event.command_id != order.command_id
            or event.broker_order_id != order.broker_order_id
            for event in observed
        ):
            raise ValueError
    return _hash({
        "source_identity": value.source_identity, "as_of": _time(value.as_of),
        "finality": value.finality, "account": value.account.snapshot_id,
        "orders": [[item.broker_order_id, item.command_id, item.status.value,
                    item.cumulative_quantity, list(item.observed_event_ids)] for item in value.orders],
        "events": [item.event_id for item in value.events],
    })


def _reconciliation_identity(value: ReconciliationResult) -> str:
    return _hash({
        "local_recovery_id": value.local_recovery_id,
        "broker_snapshot_id": value.broker_snapshot_id,
        "as_of": _time(value.as_of), "gate_passed": value.gate_passed,
        "disposition": value.disposition,
        "differences": [[item.code, item.action, item.subject,
                         item.local_identity, item.broker_identity]
                        for item in value.differences],
    })


def _aggregate_identity(value: OrderAggregate) -> str:
    return hashlib.sha256(encode_order_aggregate(value)).hexdigest()


def _unique_sorted_differences(
    values: list[ReconciliationDifference],
) -> list[ReconciliationDifference]:
    result: dict[str, ReconciliationDifference] = {}
    for value in values:
        previous = result.get(value.subject)
        if (
            previous is None
            or _ACTION_RANK[value.action] > _ACTION_RANK[previous.action]
            or (
                _ACTION_RANK[value.action] == _ACTION_RANK[previous.action]
                and _difference_key(value) < _difference_key(previous)
            )
        ):
            result[value.subject] = value
    return sorted(result.values(), key=_difference_key)


def _difference_key(value: ReconciliationDifference) -> tuple[object, ...]:
    return (value.action, value.code, value.subject,
            value.local_identity or "", value.broker_identity or "")


def _disposition_from_actions(actions: tuple[DifferenceAction, ...]) -> RecoveryDisposition:
    if "MANUAL_REQUIRED" in actions:
        return "MANUAL_REQUIRED"
    if "QUERY_REQUIRED" in actions:
        return "QUERY_REQUIRED"
    return "READY"


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _valid_recovery_receipts(
    value: object,
    commands: object,
    cancel_commands: object,
) -> bool:
    if type(value) is not tuple or type(commands) is not tuple or type(cancel_commands) is not tuple:
        return False
    receipts = cast(tuple[object, ...], value)
    if any(type(item) is not DurableRiskTransitionReceipt for item in receipts):
        return False
    typed = cast(tuple[DurableRiskTransitionReceipt, ...], receipts)
    if tuple(item.sequence for item in typed) != tuple(range(1, len(typed) + 1)):
        return False
    expected = GENESIS_RECEIPT_ID
    try:
        for item in typed:
            if item.previous_receipt_id != expected:
                return False
            payload = encode_risk_receipt(item)
            if decode_risk_receipt(payload) != item:
                return False
            expected = item.receipt_id
        verify_risk_receipt_semantic_closure(
            receipts=typed,
            commands=cast(tuple[OrderCommand, ...], commands),
            cancel_commands=cast(tuple[CancelCommand, ...], cancel_commands),
        )
    except Exception:
        return False
    return True


def _stored_receipt_matches(
    stored: StoredRiskTransitionReceipt,
    receipt: DurableRiskTransitionReceipt,
) -> bool:
    return (
        stored.sequence == receipt.sequence
        and stored.transition_kind == receipt.transition_kind
        and stored.subject_id == receipt.subject_id
        and stored.receipt_id == receipt.receipt_id
        and stored.previous_receipt_id == receipt.previous_receipt_id
        and stored.risk_counter_key == receipt.risk_counter_key
        and stored.predecessor_counter_identity
        == receipt.predecessor_counter_identity
        and stored.projected_counter_identity == receipt.projected_counter_identity
        and stored.payload == encode_risk_receipt(receipt)
    )


def _verify_risk_closure(
    *,
    stored_receipts: tuple[StoredRiskTransitionReceipt, ...],
    counter_rows: tuple[StoredRecord, ...],
    command_map: dict[str, OrderCommand],
    stored_cancel_rows: dict[str, StoredCancelCommand],
    cancel_map: dict[str, CancelCommand],
) -> tuple[DurableRiskTransitionReceipt, ...]:
    failed = False
    result: tuple[DurableRiskTransitionReceipt, ...] = ()
    try:
        receipts: list[DurableRiskTransitionReceipt] = []
        expected_previous = GENESIS_RECEIPT_ID
        last_counter_identity: dict[str, str] = {}
        last_counter_payload: dict[str, bytes] = {}
        command_owners: dict[str, int] = {key: 0 for key in command_map}
        cancel_owners: dict[str, int] = {key: 0 for key in cancel_map}
        for expected_sequence, stored in enumerate(stored_receipts, start=1):
            receipt = decode_risk_receipt(stored.payload)
            if (
                receipt.sequence != expected_sequence
                or receipt.previous_receipt_id != expected_previous
                or not _stored_receipt_matches(stored, receipt)
            ):
                raise ValueError
            decision = receipt.decision
            prior = last_counter_identity.get(receipt.risk_counter_key)
            if prior is None:
                zero = DailyRiskCounters(
                    session_date=decision.projected_counters.session_date,
                    order_count=0,
                    cancel_count=0,
                    buy_notional=Decimal(0),
                )
                prior = counter_identity(zero)
            if receipt.predecessor_counter_identity != prior:
                raise ValueError
            last_counter_identity[receipt.risk_counter_key] = (
                receipt.projected_counter_identity
            )
            last_counter_payload[receipt.risk_counter_key] = counter_payload(
                decision.projected_counters
            )
            if receipt.transition_kind == "ORDER":
                if type(decision) is not DurableOrderRiskDecision:
                    raise ValueError
                commands: list[OrderCommand] = []
                for command_id in decision.command_ids:
                    command = command_map.get(command_id)
                    if command is None or command.intent.plan_id != decision.plan_id:
                        raise ValueError
                    commands.append(command)
                    command_owners[command_id] += 1
                if commands and tuple(
                    item.intent.intent_id for item in commands
                ) != decision.approved_intent_ids:
                    raise ValueError
            elif receipt.transition_kind == "CANCEL":
                if type(decision) is not DurableCancelRiskDecision:
                    raise ValueError
                cancel = cancel_map.get(decision.cancel_id)
                stored_cancel = stored_cancel_rows.get(decision.cancel_id)
                if (
                    cancel is None
                    or stored_cancel is None
                    or cancel.command_id != decision.command_id
                    or decision.command_id not in command_map
                    or stored_cancel.command_id != decision.command_id
                    or stored_cancel.risk_counter_key != receipt.risk_counter_key
                    or stored_cancel.risk_policy_identity != decision.policy_identity
                ):
                    raise ValueError
                cancel_owners[decision.cancel_id] += 1
            else:
                raise ValueError
            receipts.append(receipt)
            expected_previous = receipt.receipt_id

        if any(value != 1 for value in command_owners.values()):
            raise ValueError
        if any(value != 1 for value in cancel_owners.values()):
            raise ValueError
        counters = {row.key: row for row in counter_rows}
        if set(counters) != set(last_counter_identity):
            raise ValueError
        for key, identity in last_counter_identity.items():
            row = counters[key]
            if row.identity != identity or row.payload != last_counter_payload[key]:
                raise ValueError
        result = tuple(receipts)
        verify_risk_receipt_semantic_closure(
            receipts=result,
            commands=tuple(command_map.values()),
            cancel_commands=tuple(cancel_map.values()),
        )
        if not _valid_recovery_receipts(
            result, tuple(command_map.values()), tuple(cancel_map.values())
        ):
            raise ValueError
    except Exception:
        failed = True
    if failed:
        raise _RiskRecoveryClosureError from None
    return result


class _RiskRecoveryClosureError(Exception):
    pass


class _CancelRecoveryClosureError(Exception):
    pass


def _decode_cancel_counter(record: StoredRecord, session_date: dt.date) -> int:
    if record.identity != hashlib.sha256(record.payload).hexdigest():
        raise ValueError
    root = json.loads(record.payload)
    if type(root) is not dict or set(root) != {"schema_version", "counter"}:
        raise ValueError
    if root["schema_version"] != "m4-daily-risk-counters-v1":
        raise ValueError
    counter = root["counter"]
    if type(counter) is not dict or set(counter) != {
        "session_date", "order_count", "cancel_count", "buy_notional",
    }:
        raise ValueError
    if counter["session_date"] != session_date.isoformat():
        raise ValueError
    order_count = counter["order_count"]
    cancel_count = counter["cancel_count"]
    buy_notional = counter["buy_notional"]
    if (
        type(order_count) is not int
        or order_count < 0
        or type(cancel_count) is not int
        or cancel_count < 0
        or type(buy_notional) is not str
    ):
        raise ValueError
    amount = Decimal(buy_notional)
    if not amount.is_finite() or amount < 0:
        raise ValueError
    canonical = json.dumps(
        root,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if canonical != record.payload:
        raise ValueError
    return cancel_count


def _hex64(value: object) -> bool:
    return type(value) is str and len(cast(str, value)) == 64 and all(
        char in _HEX for char in cast(str, value)
    )


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and "TOKEN" not in cast(str, value)


def _utc(value: object) -> bool:
    return type(value) is dt.datetime and cast(dt.datetime, value).tzinfo is not None and cast(
        dt.datetime, value
    ).utcoffset() == dt.timedelta(0)


def _time(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _optional_time(value: dt.datetime | None) -> str | None:
    return None if value is None else _time(value)


__all__ = [
    "BrokerOrderObservation", "BrokerSnapshot", "BrokerSnapshotFinality",
    "DifferenceAction", "ReconciliationDifference", "ReconciliationError",
    "ReconciliationResult", "RecoveryDisposition", "RecoveryError", "RecoveryIssue",
    "RecoveryResult", "build_broker_snapshot", "recover_local_state", "reconcile",
]
