"""M4-P0 SQLite durable store: schema version, transactions, typed repositories.

Based on pending-main-acceptance M4-C0/D0/D1 contracts. Does not claim Gate pass.
No generic SQL escape hatch is exposed to callers.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from quant.execution.approval import (
    ApprovalReceiptError,
    VerifiedApprovalReceipt,
    decode_approval_receipt,
    unpack_verified_approval_receipt,
)
from quant.execution.migrations import MIGRATIONS
from quant.execution.risk import (
    DailyRiskCounters,
    build_daily_risk_counters_identity,
    deserialize_daily_risk_counters,
    serialize_daily_risk_counters,
)
from quant.execution.session_barrier import (
    SessionBarrierError,
    fresh_read_session_barrier,
    hold_open_operation_permit,
    hold_open_write_lease,
    hold_session_barrier_lock,
    initialize_open_barrier,
    invalidate_session_barrier_oms_handle,
    invalidate_write_lease,
    issue_session_barrier_oms_handle,
    read_session_barrier,
    require_matching_barrier,
    transition_closing_to_closed,
    transition_closing_to_closed_with_closure,
    transition_open_to_closing,
    unpack_session_barrier_capability,
    unpack_session_barrier_oms_handle,
    verify_lease_against_row,
    verify_terminal_child_against_row,
)

CURRENT_SCHEMA_VERSION: Final[int] = 10
LEDGER_CHECKPOINT_KEY: Final[str] = "paper-shadow-primary-v1"

_URI_PREFIX = "sqlite:///"
_HEX_OR_KEY = re.compile(r"^[A-Za-z0-9_.:\-]+$")
_HEX_LOWER = frozenset("0123456789abcdef")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SQLITE_MAX_INT: Final[int] = 2**63 - 1


class StoreError(ValueError):
    """Stable store contract error; messages must not leak absolute paths."""


class IdempotencyConflict(StoreError):
    """Same unique key with different identity/payload/related keys (non-retryable)."""


class UnknownSchemaVersionError(StoreError):
    """Database schema version is newer than this binary supports."""


class MigrationInterruptedError(StoreError):
    """A previous migration did not finish; fail closed until repaired."""


class StoreUriError(StoreError):
    """SQLite URI is malformed or unsafe."""


class OutboxDeliveryState(StrEnum):
    """Durable delivery states; SENT and UNKNOWN are terminal."""

    PENDING = "PENDING"
    LEASED = "LEASED"
    SENT = "SENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """Opaque durable row: unique key + identity + payload bytes."""

    key: str
    identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class StoredDailyRiskCounters:
    """Authenticated daily counters with their durable CAS identity."""

    counters: DailyRiskCounters
    identity: str
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class StoredEventRecord:
    """Strict event row retaining its command foreign-key closure."""

    event_id: str
    command_id: str
    identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class StoredRiskTransitionReceipt:
    """Opaque risk receipt retaining every indexed chain field."""

    sequence: int
    transition_kind: str
    subject_id: str
    receipt_id: str
    previous_receipt_id: str
    risk_counter_key: str
    predecessor_counter_identity: str
    projected_counter_identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class StoredApprovalReceipt:
    """Raw canonical approval bytes with only independently indexed values."""

    receipt_id: str
    identity: str
    schema_version: str
    classification: str
    credential_kind: str
    credential_id: str
    operator_id: str
    session_date: str
    action: str
    plan_identity: str
    challenge_identity: str
    store_recovery_identity: str
    source_identities_digest: str
    issued_at: str
    nonce: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class RecoveryRows:
    """One transaction-consistent, deterministically ordered recovery snapshot."""

    commands: tuple[StoredRecord, ...]
    events: tuple[StoredEventRecord, ...]
    order_aggregates: tuple[StoredRecord, ...]
    outbox_deliveries: tuple[OutboxDelivery, ...]
    ledger_entries: tuple[StoredRecord, ...]
    ledger_contexts: tuple[StoredRecord, ...]
    ledger_checkpoints: tuple[StoredLedgerCheckpoint, ...]
    cancel_commands: tuple[StoredCancelCommand, ...]
    cancel_deliveries: tuple[CancelOutboxDelivery, ...]
    cancel_event_links: tuple[StoredCancelEventLink, ...]
    risk_transition_receipts: tuple[StoredRiskTransitionReceipt, ...]
    risk_counter_rows: tuple[StoredRecord, ...]
    approval_receipts: tuple[StoredApprovalReceipt, ...]


@dataclass(frozen=True, slots=True)
class StoredLedgerCheckpoint:
    """Opaque checkpoint row retaining its append-only tail closure."""

    checkpoint_key: str
    identity: str
    payload: bytes
    last_entry_id: str | None


@dataclass(frozen=True, slots=True)
class StoredCancelCommand:
    """Opaque canonical cancel row retaining its target and risk closure."""

    cancel_id: str
    command_id: str
    identity: str
    payload: bytes
    risk_counter_key: str
    risk_policy_identity: str


@dataclass(frozen=True, slots=True)
class StoredCancelEventLink:
    """Durable proof that one order callback was observed for one cancel."""

    cancel_id: str
    event_id: str
    command_id: str


@dataclass(frozen=True, slots=True)
class OutboxDelivery:
    """Strict delivery metadata joined with its opaque outbox record."""

    outbox_key: str
    command_id: str
    state: OutboxDeliveryState
    attempt_count: int
    available_at: dt.datetime
    lease_owner: str | None
    lease_until: dt.datetime | None
    terminal_at: dt.datetime | None
    last_error_code: str | None
    identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class CancelOutboxDelivery:
    """Strict cancel delivery metadata joined with its immutable cancel bytes."""

    cancel_id: str
    command_id: str
    state: OutboxDeliveryState
    attempt_count: int
    available_at: dt.datetime
    lease_owner: str | None
    lease_until: dt.datetime | None
    terminal_at: dt.datetime | None
    last_error_code: str | None
    identity: str
    payload: bytes


def _require_key(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise StoreError(f"{name} must be a non-empty str")
    if not _HEX_OR_KEY.fullmatch(value):
        raise StoreError(f"{name} contains forbidden characters")
    return value


def _require_identity(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in _HEX_LOWER for char in value)
    ):
        raise StoreError("IDENTITY_INVALID")
    return value


def _require_transition_kind(value: object) -> str:
    if type(value) is not str or value not in {"ORDER", "CANCEL"}:
        raise StoreError("RISK_RECEIPT_KIND_INVALID")
    return value


def _require_checkpoint_key(value: object) -> str:
    if value != LEDGER_CHECKPOINT_KEY:
        raise StoreError("LEDGER_CHECKPOINT_KEY_INVALID")
    return LEDGER_CHECKPOINT_KEY


def _require_payload(value: object) -> bytes:
    if type(value) is not bytes:
        raise StoreError("payload must be bytes")
    return value


def _require_utc_datetime(name: str, value: object) -> dt.datetime:
    if type(value) is not dt.datetime:
        raise StoreError(f"{name} must be datetime")
    assert isinstance(value, dt.datetime)
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise StoreError(f"{name} must be timezone-aware UTC")
    return value


def _require_session_date(value: object) -> dt.date:
    if type(value) is not dt.date or isinstance(value, dt.datetime):
        raise StoreError("session_date must be date")
    return value


def _datetime_to_text(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object) -> dt.datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise StoreError("ROW_CORRUPT")
    parsed: dt.datetime | None = None
    try:
        parsed = dt.datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        pass
    if (
        parsed is None
        or parsed.tzinfo is None
        or parsed.utcoffset() != dt.timedelta(0)
        or _datetime_to_text(parsed) != value
    ):
        raise StoreError("ROW_CORRUPT")
    return parsed


def _require_positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise StoreError(f"{name} must be a positive int")
    return value


def _require_delivery_token(name: str, value: object) -> str:
    token = _require_key(name, value)
    if len(token) > 128:
        raise StoreError(f"{name} is too long")
    return token


def _row_to_stored(key: object, identity: object, payload: object) -> StoredRecord:
    if type(key) is not str or not key or not _HEX_OR_KEY.fullmatch(key):
        raise StoreError("ROW_CORRUPT")
    if (
        type(identity) is not str
        or len(identity) != 64
        or any(char not in _HEX_LOWER for char in identity)
    ):
        raise StoreError("ROW_CORRUPT")
    if type(payload) is not bytes:
        raise StoreError("ROW_CORRUPT")
    return StoredRecord(key=key, identity=identity, payload=payload)


def _row_to_daily_risk_counters(
    session_date: object,
    identity: object,
    payload: object,
    updated_at: object,
) -> StoredDailyRiskCounters:
    parsed: tuple[DailyRiskCounters, str, dt.datetime] | None = None
    try:
        if type(session_date) is not str:
            raise StoreError("ROW_CORRUPT")
        parsed_date = dt.date.fromisoformat(session_date)
        if parsed_date.isoformat() != session_date:
            raise StoreError("ROW_CORRUPT")
        parsed_identity = _require_identity(identity)
        parsed_payload = _require_payload(payload)
        counters = deserialize_daily_risk_counters(parsed_payload)
        parsed_updated_at = _datetime_from_text(updated_at)
        if counters.session_date != parsed_date:
            raise StoreError("ROW_CORRUPT")
        if build_daily_risk_counters_identity(counters) != parsed_identity:
            raise StoreError("ROW_CORRUPT")
        parsed = (counters, parsed_identity, parsed_updated_at)
    except (ArithmeticError, RecursionError, StoreError, TypeError, ValueError):
        pass
    if parsed is None:
        raise StoreError("ROW_CORRUPT")
    return StoredDailyRiskCounters(
        counters=parsed[0],
        identity=parsed[1],
        updated_at=parsed[2],
    )


def _row_to_stored_event(row: tuple[object, ...]) -> StoredEventRecord:
    if len(row) != 5:
        raise StoreError("ROW_CORRUPT")
    event = _row_to_stored(row[0], row[2], row[3])
    command_id: str | None = None
    command_ref: str | None = None
    try:
        command_id = _require_key("command_id", row[1])
        command_ref = _require_key("command_id", row[4])
    except StoreError:
        pass
    if command_id is None or command_ref is None or command_id != command_ref:
        raise StoreError("ROW_CORRUPT")
    return StoredEventRecord(
        event_id=event.key,
        command_id=command_id,
        identity=event.identity,
        payload=event.payload,
    )


def _row_to_risk_receipt(
    row: tuple[object, ...],
) -> StoredRiskTransitionReceipt:
    if len(row) != 9:
        raise StoreError("ROW_CORRUPT")
    try:
        sequence = _require_positive_int("sequence", row[0])
        kind = _require_transition_kind(row[1])
        subject = _require_identity(row[2])
        receipt = _require_identity(row[3])
        previous = _require_identity(row[4])
        counter_key = _require_key("risk_counter_key", row[5])
        predecessor = _require_identity(row[6])
        projected = _require_identity(row[7])
        payload = _require_payload(row[8])
    except StoreError:
        raise StoreError("ROW_CORRUPT") from None
    return StoredRiskTransitionReceipt(
        sequence=sequence,
        transition_kind=kind,
        subject_id=subject,
        receipt_id=receipt,
        previous_receipt_id=previous,
        risk_counter_key=counter_key,
        predecessor_counter_identity=predecessor,
        projected_counter_identity=projected,
        payload=payload,
    )


def _require_approval_index_text(name: str, value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise StoreError(f"{name.upper()}_INVALID")
    return value


def _require_approval_session_date(value: object) -> str:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is not str:
        raise StoreError("APPROVAL_SESSION_DATE_INVALID")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise StoreError("APPROVAL_SESSION_DATE_INVALID") from None
    if parsed.isoformat() != value:
        raise StoreError("APPROVAL_SESSION_DATE_INVALID")
    return value


def _row_to_stored_approval(row: tuple[object, ...]) -> StoredApprovalReceipt:
    """Validate row/index agreement without treating the decoded value as trusted."""
    if len(row) != 16:
        raise StoreError("ROW_CORRUPT")
    try:
        receipt_id = _require_identity(row[0])
        identity = _require_identity(row[1])
        schema_version = _require_approval_index_text("schema_version", row[2])
        classification = _require_approval_index_text("classification", row[3])
        credential_kind = _require_approval_index_text("credential_kind", row[4])
        credential_id = _require_approval_index_text("credential_id", row[5])
        operator_id = _require_approval_index_text("operator_id", row[6])
        session_date = _require_approval_session_date(row[7])
        action = _require_approval_index_text("action", row[8])
        plan_identity = _require_identity(row[9])
        challenge_identity = _require_identity(row[10])
        store_recovery_identity = _require_identity(row[11])
        source_identities_digest = _require_identity(row[12])
        issued_at = row[13]
        if type(issued_at) is not str:
            raise StoreError("APPROVAL_ISSUED_AT_INVALID")
        parsed_issued_at = _datetime_from_text(issued_at)
        if _datetime_to_text(parsed_issued_at) != issued_at:
            raise StoreError("APPROVAL_ISSUED_AT_INVALID")
        nonce = _require_approval_index_text("nonce", row[14])
        payload = _require_payload(row[15])
        if identity != receipt_id:
            raise StoreError("ROW_CORRUPT")
        parsed = decode_approval_receipt(payload)
        if (
            parsed.receipt_id != receipt_id
            or parsed.schema_version != schema_version
            or parsed.classification != classification
            or parsed.credential_kind != credential_kind
            or parsed.credential_id != credential_id
            or parsed.operator_id != operator_id
            or parsed.session_date != session_date
            or parsed.action != action
            or parsed.plan_identity != plan_identity
            or parsed.challenge_identity != challenge_identity
            or parsed.store_recovery_identity != store_recovery_identity
            or parsed.source_identities_digest != source_identities_digest
            or parsed.issued_at != issued_at
            or parsed.nonce != nonce
        ):
            raise StoreError("ROW_CORRUPT")
    except (ApprovalReceiptError, StoreError, TypeError, ValueError):
        raise StoreError("ROW_CORRUPT") from None
    return StoredApprovalReceipt(
        receipt_id=receipt_id,
        identity=identity,
        schema_version=schema_version,
        classification=classification,
        credential_kind=credential_kind,
        credential_id=credential_id,
        operator_id=operator_id,
        session_date=session_date,
        action=action,
        plan_identity=plan_identity,
        challenge_identity=challenge_identity,
        store_recovery_identity=store_recovery_identity,
        source_identities_digest=source_identities_digest,
        issued_at=issued_at,
        nonce=nonce,
        payload=payload,
    )


def _row_to_stored_aggregate(row: tuple[object, ...]) -> StoredRecord:
    if len(row) != 4:
        raise StoreError("ROW_CORRUPT")
    aggregate = _row_to_stored(row[0], row[1], row[2])
    command_ref: str | None = None
    try:
        command_ref = _require_key("command_id", row[3])
    except StoreError:
        pass
    if command_ref is None or aggregate.key != command_ref:
        raise StoreError("ROW_CORRUPT")
    return aggregate


def _row_to_ledger_context(row: tuple[object, ...]) -> StoredRecord:
    if len(row) != 4:
        raise StoreError("ROW_CORRUPT")
    context = _row_to_stored(row[0], row[1], row[2])
    command_ref: str | None = None
    try:
        command_ref = _require_key("command_id", row[3])
    except StoreError:
        pass
    if command_ref is None or context.key != command_ref:
        raise StoreError("ROW_CORRUPT")
    return context


def _row_to_ledger_checkpoint(row: tuple[object, ...]) -> StoredLedgerCheckpoint:
    if len(row) != 5:
        raise StoreError("ROW_CORRUPT")
    stored = _row_to_stored(row[0], row[1], row[2])
    if stored.key != LEDGER_CHECKPOINT_KEY:
        raise StoreError("ROW_CORRUPT")
    last_entry_id = row[3]
    if last_entry_id is not None:
        valid_tail: str | None = None
        try:
            valid_tail = _require_key("last_entry_id", last_entry_id)
        except StoreError:
            pass
        if valid_tail is None:
            raise StoreError("ROW_CORRUPT")
        last_entry_id = valid_tail
    tail_ref = row[4]
    if (last_entry_id is None and tail_ref is not None) or (
        last_entry_id is not None and tail_ref != last_entry_id
    ):
        raise StoreError("ROW_CORRUPT")
    return StoredLedgerCheckpoint(
        checkpoint_key=stored.key,
        identity=stored.identity,
        payload=stored.payload,
        last_entry_id=last_entry_id,
    )


def _row_to_outbox_delivery(row: tuple[object, ...]) -> OutboxDelivery:
    if len(row) != 13:
        raise StoreError("ROW_CORRUPT")
    parsed: tuple[
        str,
        str,
        OutboxDeliveryState,
        int,
        dt.datetime,
        str | None,
        dt.datetime | None,
        dt.datetime | None,
        str | None,
        str,
        bytes,
    ] | None = None
    try:
        outbox_key = _require_key("outbox_key", row[0])
        command_id = _require_key("command_id", row[1])
        if type(row[2]) is not str:
            raise StoreError("ROW_CORRUPT")
        state = OutboxDeliveryState(row[2])
        if type(row[3]) is not int or row[3] < 0:
            raise StoreError("ROW_CORRUPT")
        attempt_count = row[3]
        available_at = _datetime_from_text(row[4])
        lease_owner = (
            None if row[5] is None else _require_delivery_token("lease_owner", row[5])
        )
        lease_until = None if row[6] is None else _datetime_from_text(row[6])
        terminal_at = None if row[7] is None else _datetime_from_text(row[7])
        last_error_code = (
            None
            if row[8] is None
            else _require_delivery_token("last_error_code", row[8])
        )
        identity = _require_identity(row[9])
        payload = _require_payload(row[10])
        command_ref = _require_key("command_id", row[11])
        aggregate_ref = _require_key("command_id", row[12])
        if command_ref != command_id or aggregate_ref != command_id:
            raise StoreError("ROW_CORRUPT")
        parsed = (
            outbox_key,
            command_id,
            state,
            attempt_count,
            available_at,
            lease_owner,
            lease_until,
            terminal_at,
            last_error_code,
            identity,
            payload,
        )
    except (StoreError, ValueError):
        pass
    if parsed is None:
        raise StoreError("ROW_CORRUPT")
    (
        outbox_key,
        command_id,
        state,
        attempt_count,
        available_at,
        lease_owner,
        lease_until,
        terminal_at,
        last_error_code,
        identity,
        payload,
    ) = parsed

    valid = (
        state is OutboxDeliveryState.PENDING
        and attempt_count == 0
        and lease_owner is None
        and lease_until is None
        and terminal_at is None
        and last_error_code is None
    ) or (
        state is OutboxDeliveryState.LEASED
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and lease_until > available_at
        and terminal_at is None
        and last_error_code is None
    ) or (
        state is OutboxDeliveryState.SENT
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and terminal_at is not None
        and available_at <= terminal_at < lease_until
        and last_error_code is None
    ) or (
        state is OutboxDeliveryState.UNKNOWN
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and terminal_at is not None
        and available_at <= terminal_at < lease_until
        and last_error_code is not None
    )
    if not valid:
        raise StoreError("ROW_CORRUPT")
    return OutboxDelivery(
        outbox_key=outbox_key,
        command_id=command_id,
        state=state,
        attempt_count=attempt_count,
        available_at=available_at,
        lease_owner=lease_owner,
        lease_until=lease_until,
        terminal_at=terminal_at,
        last_error_code=last_error_code,
        identity=identity,
        payload=payload,
    )


def _row_to_cancel_command(row: tuple[object, ...]) -> StoredCancelCommand:
    if len(row) != 8:
        raise StoreError("ROW_CORRUPT")
    try:
        cancel_id = _require_identity(row[0])
        command_id = _require_identity(row[1])
        identity = _require_identity(row[2])
        payload = _require_payload(row[3])
        counter_key = _require_delivery_token("risk_counter_key", row[4])
        policy_id = _require_identity(row[5])
        cancel_ref = _require_identity(row[6])
        command_ref = _require_identity(row[7])
    except StoreError:
        raise StoreError("ROW_CORRUPT") from None
    if (
        cancel_id != identity
        or cancel_ref != cancel_id
        or command_ref != command_id
    ):
        raise StoreError("ROW_CORRUPT")
    return StoredCancelCommand(
        cancel_id=cancel_id,
        command_id=command_id,
        identity=identity,
        payload=payload,
        risk_counter_key=counter_key,
        risk_policy_identity=policy_id,
    )


def _row_to_cancel_delivery(row: tuple[object, ...]) -> CancelOutboxDelivery:
    if len(row) != 14:
        raise StoreError("ROW_CORRUPT")
    try:
        cancel_id = _require_identity(row[0])
        command_id = _require_identity(row[1])
        if type(row[2]) is not str:
            raise StoreError("ROW_CORRUPT")
        state = OutboxDeliveryState(row[2])
        if type(row[3]) is not int or row[3] < 0:
            raise StoreError("ROW_CORRUPT")
        attempt_count = row[3]
        available_at = _datetime_from_text(row[4])
        lease_owner = (
            None if row[5] is None else _require_delivery_token("lease_owner", row[5])
        )
        lease_until = None if row[6] is None else _datetime_from_text(row[6])
        terminal_at = None if row[7] is None else _datetime_from_text(row[7])
        last_error_code = (
            None
            if row[8] is None
            else _require_delivery_token("last_error_code", row[8])
        )
        identity = _require_identity(row[9])
        payload = _require_payload(row[10])
        cancel_ref = _require_identity(row[11])
        cancel_command_ref = _require_identity(row[12])
        command_ref = _require_identity(row[13])
    except (StoreError, ValueError):
        raise StoreError("ROW_CORRUPT") from None
    valid_state = (
        state is OutboxDeliveryState.PENDING
        and attempt_count >= 0
        and lease_owner is None
        and lease_until is None
        and terminal_at is None
        and last_error_code in {None, "CANCEL_GATEWAY_NOT_SENT"}
    ) or (
        state is OutboxDeliveryState.LEASED
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and lease_until > available_at
        and terminal_at is None
        and last_error_code in {None, "CANCEL_GATEWAY_STARTED"}
    ) or (
        state is OutboxDeliveryState.SENT
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and terminal_at is not None
        and available_at <= terminal_at
        and last_error_code is None
    ) or (
        state is OutboxDeliveryState.UNKNOWN
        and attempt_count >= 1
        and lease_owner is not None
        and lease_until is not None
        and terminal_at is not None
        and available_at <= terminal_at
        and last_error_code is not None
    )
    if (
        not valid_state
        or cancel_id != identity
        or cancel_ref != cancel_id
        or cancel_command_ref != command_id
        or command_ref != command_id
    ):
        raise StoreError("ROW_CORRUPT")
    return CancelOutboxDelivery(
        cancel_id=cancel_id,
        command_id=command_id,
        state=state,
        attempt_count=attempt_count,
        available_at=available_at,
        lease_owner=lease_owner,
        lease_until=lease_until,
        terminal_at=terminal_at,
        last_error_code=last_error_code,
        identity=identity,
        payload=payload,
    )


def _row_to_cancel_event_link(row: tuple[object, ...]) -> StoredCancelEventLink:
    if len(row) != 5:
        raise StoreError("ROW_CORRUPT")
    try:
        cancel_id = _require_identity(row[0])
        event_id = _require_identity(row[1])
        cancel_ref = _require_identity(row[2])
        event_ref = _require_identity(row[3])
        event_command_id = _require_identity(row[4])
    except StoreError:
        raise StoreError("ROW_CORRUPT") from None
    if cancel_ref != cancel_id or event_ref != event_id:
        raise StoreError("ROW_CORRUPT")
    return StoredCancelEventLink(
        cancel_id=cancel_id,
        event_id=event_id,
        command_id=event_command_id,
    )


def _parse_sqlite_uri(uri: str) -> Path:
    """Accept only canonical C0-aligned relative sqlite URIs.

    Returns a relative Path; callers must combine with an explicit trusted root.
    """
    if type(uri) is not str or not uri:
        raise StoreUriError("URI_INVALID")
    if any(ord(char) < 32 or ord(char) == 127 for char in uri):
        raise StoreUriError("URI_INVALID")
    if not uri.startswith(_URI_PREFIX):
        raise StoreUriError("URI_INVALID")
    remainder = uri[len(_URI_PREFIX) :]
    if (
        not remainder
        or "?" in remainder
        or "#" in remainder
        or "\\" in remainder
        or "%" in remainder
        or remainder.startswith("/")
        or remainder.startswith("//")
        or remainder.endswith("/")
        or _DRIVE_RE.match(remainder) is not None
        or any(segment in {"", ".", ".."} for segment in remainder.split("/"))
    ):
        raise StoreUriError("URI_INVALID")
    return Path(remainder)


def _is_within_root(path: Path, root: Path) -> bool:
    """Physical containment via Path.relative_to; no string startswith."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_trusted_root(trusted_root: object) -> Path:
    """Validate and resolve trusted_root; failures map to TRUSTED_ROOT_INVALID."""
    if type(trusted_root) is not type(Path()):
        raise StoreUriError("TRUSTED_ROOT_INVALID")
    assert isinstance(trusted_root, Path)
    if not trusted_root.is_absolute():
        raise StoreUriError("TRUSTED_ROOT_INVALID")

    st: os.stat_result | None
    try:
        st = trusted_root.lstat()
    except OSError:
        st = None
    if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise StoreUriError("TRUSTED_ROOT_INVALID")
    if trusted_root.parent == trusted_root:
        raise StoreUriError("TRUSTED_ROOT_INVALID")

    resolved: Path | None
    try:
        resolved = trusted_root.resolve(strict=True)
    except OSError:
        resolved = None
    if resolved is None or resolved.parent == resolved:
        raise StoreUriError("TRUSTED_ROOT_INVALID")

    rst: os.stat_result | None
    try:
        rst = resolved.lstat()
    except OSError:
        rst = None
    if rst is None or stat.S_ISLNK(rst.st_mode) or not stat.S_ISDIR(rst.st_mode):
        raise StoreUriError("TRUSTED_ROOT_INVALID")
    return resolved


def _lstat_mapped(path: Path) -> os.stat_result | None:
    """Return lstat result, None if missing; map other OSError to boundary error."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        pass
    raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID") from None


def _resolve_strict_mapped(path: Path) -> Path:
    resolved: Path | None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        resolved = None
    if resolved is None:
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID") from None
    return resolved


def _check_existing_dir_component(path: Path, resolved_root: Path) -> Path:
    """Reject symlink / non-dir / out-of-root; return resolved directory."""
    st = _lstat_mapped(path)
    if st is None:
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
    resolved = _resolve_strict_mapped(path)
    if not _is_within_root(resolved, resolved_root):
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
    return resolved


def _check_leaf(path: Path, resolved_root: Path, *, must_exist: bool) -> None:
    """Leaf must be a non-symlink regular file with a single hard link."""
    st = _lstat_mapped(path)
    if st is None:
        if must_exist:
            raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
        return
    if (
        stat.S_ISLNK(st.st_mode)
        or not stat.S_ISREG(st.st_mode)
        or st.st_nlink != 1
    ):
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
    resolved = _resolve_strict_mapped(path)
    if not _is_within_root(resolved, resolved_root):
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")


def _materialize_db_path(resolved_root: Path, relative: Path) -> Path:
    """Walk URI components under root; create missing parents; validate leaf."""
    current = resolved_root
    parts = relative.parts
    if not parts:
        raise StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
    parent_parts = parts[:-1]
    leaf_name = parts[-1]

    for part in parent_parts:
        next_path = current / part
        st = _lstat_mapped(next_path)
        if st is None:
            mkdir_err: StoreError | None = None
            try:
                next_path.mkdir(exist_ok=True)
            except OSError:
                mkdir_err = StoreError("PARENT_CREATE_FAILED")
            if mkdir_err is not None:
                raise mkdir_err from None
            current = _check_existing_dir_component(next_path, resolved_root)
        else:
            current = _check_existing_dir_component(next_path, resolved_root)

    leaf = current / leaf_name
    _check_leaf(leaf, resolved_root, must_exist=False)
    return leaf


def _ensure_schema_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            version INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('ready', 'migrating')),
            applied_at TEXT NOT NULL
        )
        """
    )


def _read_schema_row(conn: sqlite3.Connection) -> tuple[int, str] | None:
    row = conn.execute(
        "SELECT version, status FROM schema_version WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def _apply_migrations(conn: sqlite3.Connection) -> int:
    _ensure_schema_meta(conn)
    current = _read_schema_row(conn)
    if current is not None:
        version, status = current
        if status == "migrating":
            raise MigrationInterruptedError("MIGRATION_INTERRUPTED")
        if version > CURRENT_SCHEMA_VERSION:
            raise UnknownSchemaVersionError("UNKNOWN_SCHEMA_VERSION")
        if version == CURRENT_SCHEMA_VERSION:
            return version
        start_version = version
    else:
        start_version = 0

    for target_version, upgrade in MIGRATIONS:
        if target_version <= start_version:
            continue
        if target_version > CURRENT_SCHEMA_VERSION:
            raise UnknownSchemaVersionError("UNKNOWN_SCHEMA_VERSION")
        conn.execute(
            """
            INSERT INTO schema_version (singleton, version, status, applied_at)
            VALUES (1, ?, 'migrating', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(singleton) DO UPDATE SET
                status = 'migrating',
                applied_at = excluded.applied_at
            """,
            (start_version,),
        )
        upgrade(conn)
        conn.execute(
            """
            UPDATE schema_version
            SET version = ?, status = 'ready',
                applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE singleton = 1
            """,
            (target_version,),
        )
        start_version = target_version

    final = _read_schema_row(conn)
    if final is None or final[0] != CURRENT_SCHEMA_VERSION or final[1] != "ready":
        raise MigrationInterruptedError("MIGRATION_INCOMPLETE")
    return final[0]


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _safe_close(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:
        pass


class ExecutionRepository:
    """Typed repository bound to an open write transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _put_row(
        self,
        *,
        table: str,
        key_column: str,
        key: str,
        identity: str,
        payload: bytes,
        extra_columns: tuple[tuple[str, str], ...] = (),
        subject: str,
    ) -> bool:
        columns = [key_column, "identity", "payload"]
        values: list[object] = [key, identity, payload]
        for col_name, col_value in extra_columns:
            columns.insert(1, col_name)
            values.insert(1, col_value)
        placeholders = ", ".join("?" for _ in columns)
        col_sql = ", ".join(columns)
        extra_names = [name for name, _ in extra_columns]
        select_cols = "identity, payload"
        if extra_names:
            select_cols = f"{select_cols}, {', '.join(extra_names)}"
        query_error: StoreError | None = None
        existing: tuple[object, ...] | None = None
        try:
            existing = self._conn.execute(
                f"SELECT {select_cols} FROM {table} WHERE {key_column} = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            query_error = StoreError(f"{subject.upper()}_QUERY_FAILED")
        if query_error is not None:
            raise query_error from None
        if existing is not None:
            same_identity = type(existing[0]) is str and existing[0] == identity
            same_payload = type(existing[1]) is bytes and existing[1] == payload
            same_extras = all(
                type(existing[2 + i]) is str and existing[2 + i] == value
                for i, (_, value) in enumerate(extra_columns)
            )
            if same_identity and same_payload and same_extras:
                return False
            raise IdempotencyConflict(f"IDEMPOTENCY_CONFLICT:{subject}")
        mapped: StoreError | None = None
        try:
            self._conn.execute(
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                values,
            )
        except sqlite3.IntegrityError:
            mapped = StoreError("REFERENTIAL_INTEGRITY")
        except sqlite3.Error:
            mapped = StoreError(f"{subject.upper()}_WRITE_FAILED")
        if mapped is not None:
            raise mapped from None
        return True

    def _replace_row_cas(
        self,
        *,
        table: str,
        key_column: str,
        key: str,
        expected_identity: str,
        identity: str,
        payload: bytes,
        subject: str,
    ) -> bool:
        """Replace one opaque row under an identity fence and local savepoint."""
        expected = _require_identity(expected_identity)
        replacement_identity = _require_identity(identity)
        replacement_payload = _require_payload(payload)
        query_error: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                f"SELECT {key_column}, identity, payload FROM {table} "
                f"WHERE {key_column} = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            query_error = StoreError(f"{subject}_QUERY_FAILED")
        if query_error is not None:
            raise query_error from None
        if row is None:
            raise StoreError(f"{subject}_NOT_FOUND")
        current = _row_to_stored(row[0], row[1], row[2])
        if current.identity == replacement_identity:
            if current.payload == replacement_payload:
                return False
            raise IdempotencyConflict(f"IDEMPOTENCY_CONFLICT:{subject}")
        if current.identity != expected:
            raise IdempotencyConflict(f"{subject}_CAS_MISMATCH")

        savepoint_error: StoreError | None = None
        try:
            self._conn.execute("SAVEPOINT execution_state_cas")
        except sqlite3.Error:
            savepoint_error = StoreError(f"{subject}_CAS_FAILED")
        if savepoint_error is not None:
            raise savepoint_error from None

        operation_error: StoreError | None = None
        changed = 0
        verified: tuple[object, ...] | None = None
        try:
            cursor = self._conn.execute(
                f"UPDATE {table} SET identity = ?, payload = ? "
                f"WHERE {key_column} = ? AND identity = ?",
                (replacement_identity, replacement_payload, key, expected),
            )
            changed = cursor.rowcount
            verified = self._conn.execute(
                f"SELECT {key_column}, identity, payload FROM {table} "
                f"WHERE {key_column} = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            operation_error = StoreError(f"{subject}_CAS_FAILED")
        if changed != 1 or verified is None:
            operation_error = operation_error or StoreError(f"{subject}_CAS_CONFLICT")
        if operation_error is None:
            assert verified is not None
            proven: StoredRecord | None = None
            try:
                proven = _row_to_stored(verified[0], verified[1], verified[2])
            except StoreError:
                operation_error = StoreError(f"{subject}_CAS_CONFLICT")
            if operation_error is None:
                assert proven is not None
                if (
                    proven.identity != replacement_identity
                    or proven.payload != replacement_payload
                ):
                    operation_error = StoreError(f"{subject}_CAS_CONFLICT")

        if operation_error is None:
            try:
                self._conn.execute("RELEASE SAVEPOINT execution_state_cas")
            except sqlite3.Error:
                operation_error = StoreError(f"{subject}_CAS_FAILED")

        if operation_error is not None:
            rollback_failed = False
            try:
                self._conn.execute("ROLLBACK TO SAVEPOINT execution_state_cas")
                self._conn.execute("RELEASE SAVEPOINT execution_state_cas")
            except sqlite3.Error:
                rollback_failed = True
            if rollback_failed:
                raise StoreError(f"{subject}_CAS_ROLLBACK_FAILED") from None
            raise operation_error from None
        return True

    def put_command(self, *, command_id: str, identity: str, payload: bytes) -> bool:
        """Persist a client order/command; same id+payload is a no-op."""
        return self._put_row(
            table="commands",
            key_column="command_id",
            key=_require_key("command_id", command_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="command",
        )

    def get_command(self, command_id: str) -> StoredRecord | None:
        key = _require_key("command_id", command_id)
        row = self._conn.execute(
            "SELECT command_id, identity, payload FROM commands WHERE command_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def put_event(
        self,
        *,
        event_id: str,
        command_id: str,
        identity: str,
        payload: bytes,
    ) -> bool:
        """Persist an execution event; same event id+payload+command_id is a no-op."""
        return self._put_row(
            table="events",
            key_column="event_id",
            key=_require_key("event_id", event_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            extra_columns=(("command_id", _require_key("command_id", command_id)),),
            subject="event",
        )

    def get_event(self, event_id: str) -> StoredRecord | None:
        key = _require_key("event_id", event_id)
        row = self._conn.execute(
            "SELECT event_id, identity, payload FROM events WHERE event_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def put_order_aggregate(
        self, *, command_id: str, identity: str, payload: bytes
    ) -> bool:
        """Persist OMS aggregate state keyed by command/client order id."""
        return self._put_row(
            table="order_aggregates",
            key_column="command_id",
            key=_require_key("command_id", command_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="order_aggregate",
        )

    def get_order_aggregate(self, command_id: str) -> StoredRecord | None:
        key = _require_key("command_id", command_id)
        row = self._conn.execute(
            "SELECT command_id, identity, payload FROM order_aggregates"
            " WHERE command_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def replace_order_aggregate(
        self,
        *,
        command_id: str,
        expected_identity: str,
        identity: str,
        payload: bytes,
    ) -> bool:
        """CAS-replace an OMS projection; exact desired content is a no-op."""
        return self._replace_row_cas(
            table="order_aggregates",
            key_column="command_id",
            key=_require_key("command_id", command_id),
            expected_identity=expected_identity,
            identity=identity,
            payload=payload,
            subject="ORDER_AGGREGATE",
        )

    def put_execution_stage(
        self, *, plan_id: str, identity: str, payload: bytes
    ) -> bool:
        """Persist one immutable plan-stage receipt."""
        return self._put_row(
            table="execution_stages",
            key_column="plan_id",
            key=_require_key("plan_id", plan_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="execution_stage",
        )

    def get_execution_stage(self, plan_id: str) -> StoredRecord | None:
        """Return one immutable plan-stage receipt."""
        key = _require_key("plan_id", plan_id)
        mapped: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                "SELECT plan_id, identity, payload FROM execution_stages "
                "WHERE plan_id = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            mapped = StoreError("EXECUTION_STAGE_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    @staticmethod
    def _approval_columns() -> str:
        return (
            "receipt_id, identity, schema_version, classification, credential_kind, "
            "credential_id, operator_id, session_date, action, plan_identity, "
            "challenge_identity, store_recovery_identity, source_identities_digest, "
            "issued_at, nonce, payload"
        )

    def _select_approval_receipt(
        self, *, where: str, parameters: tuple[object, ...], error_code: str
    ) -> tuple[object, ...] | None:
        try:
            return self._conn.execute(
                f"SELECT {self._approval_columns()} FROM approval_receipts WHERE {where}",
                parameters,
            ).fetchone()
        except sqlite3.Error:
            raise StoreError(error_code) from None

    def put_verified_approval_receipt(
        self, verified: VerifiedApprovalReceipt
    ) -> bool:
        """Persist only the credential-free hand-off returned by verification."""
        try:
            parsed, data = unpack_verified_approval_receipt(verified)
        except ApprovalReceiptError as error:
            raise StoreError(error.code) from None
        data = _require_payload(data)
        candidate = StoredApprovalReceipt(
            receipt_id=parsed.receipt_id,
            identity=parsed.receipt_id,
            schema_version=parsed.schema_version,
            classification=parsed.classification,
            credential_kind=parsed.credential_kind,
            credential_id=parsed.credential_id,
            operator_id=parsed.operator_id,
            session_date=parsed.session_date,
            action=parsed.action,
            plan_identity=parsed.plan_identity,
            challenge_identity=parsed.challenge_identity,
            store_recovery_identity=parsed.store_recovery_identity,
            source_identities_digest=parsed.source_identities_digest,
            issued_at=parsed.issued_at,
            nonce=parsed.nonce,
            payload=data,
        )
        existing_row = self._select_approval_receipt(
            where="receipt_id = ?",
            parameters=(candidate.receipt_id,),
            error_code="APPROVAL_RECEIPT_QUERY_FAILED",
        )
        if existing_row is not None:
            existing = _row_to_stored_approval(existing_row)
            if existing == candidate:
                return False
            raise IdempotencyConflict(
                "IDEMPOTENCY_CONFLICT:approval_receipt"
            ) from None

        business_row = self._select_approval_receipt(
            where="plan_identity = ? AND session_date = ? AND action = ?",
            parameters=(candidate.plan_identity, candidate.session_date, candidate.action),
            error_code="APPROVAL_RECEIPT_QUERY_FAILED",
        )
        if business_row is not None:
            raise IdempotencyConflict("APPROVAL_BUSINESS_KEY_CONFLICT") from None

        nonce_row = self._select_approval_receipt(
            where="credential_id = ? AND nonce = ?",
            parameters=(candidate.credential_id, candidate.nonce),
            error_code="APPROVAL_RECEIPT_QUERY_FAILED",
        )
        if nonce_row is not None:
            raise IdempotencyConflict("APPROVAL_NONCE_CONFLICT") from None

        try:
            self._conn.execute(
                "INSERT INTO approval_receipts ("
                "receipt_id, identity, schema_version, classification, credential_kind, "
                "credential_id, operator_id, session_date, action, plan_identity, "
                "challenge_identity, store_recovery_identity, source_identities_digest, "
                "issued_at, nonce, payload) VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.receipt_id,
                    candidate.identity,
                    candidate.schema_version,
                    candidate.classification,
                    candidate.credential_kind,
                    candidate.credential_id,
                    candidate.operator_id,
                    candidate.session_date,
                    candidate.action,
                    candidate.plan_identity,
                    candidate.challenge_identity,
                    candidate.store_recovery_identity,
                    candidate.source_identities_digest,
                    candidate.issued_at,
                    candidate.nonce,
                    candidate.payload,
                ),
            )
        except sqlite3.IntegrityError:
            raise IdempotencyConflict("APPROVAL_RECEIPT_CONFLICT") from None
        except sqlite3.Error:
            raise StoreError("APPROVAL_RECEIPT_WRITE_FAILED") from None
        return True

    def get_approval_receipt(
        self, receipt_id: str
    ) -> StoredApprovalReceipt | None:
        """Return raw canonical bytes and indexes; never a trusted receipt object."""
        key = _require_identity(receipt_id)
        row = self._select_approval_receipt(
            where="receipt_id = ?",
            parameters=(key,),
            error_code="APPROVAL_RECEIPT_QUERY_FAILED",
        )
        return None if row is None else _row_to_stored_approval(row)

    def query_approval_receipts(
        self,
        *,
        plan_identity: str | None = None,
        session_date: str | dt.date | None = None,
        operator_id: str | None = None,
        store_recovery_identity: str | None = None,
    ) -> tuple[StoredApprovalReceipt, ...]:
        """Query raw approval rows by explicit indexed values."""
        clauses: list[str] = []
        parameters: list[object] = []
        if plan_identity is not None:
            clauses.append("plan_identity = ?")
            parameters.append(_require_identity(plan_identity))
        if session_date is not None:
            clauses.append("session_date = ?")
            parameters.append(_require_approval_session_date(session_date))
        if operator_id is not None:
            clauses.append("operator_id = ?")
            parameters.append(_require_approval_index_text("operator_id", operator_id))
        if store_recovery_identity is not None:
            clauses.append("store_recovery_identity = ?")
            parameters.append(_require_identity(store_recovery_identity))
        where = " AND ".join(clauses) if clauses else "1 = 1"
        try:
            rows = self._conn.execute(
                f"SELECT {self._approval_columns()} FROM approval_receipts "
                f"WHERE {where} ORDER BY plan_identity, session_date, receipt_id",
                tuple(parameters),
            ).fetchall()
        except sqlite3.Error:
            raise StoreError("APPROVAL_RECEIPT_QUERY_FAILED") from None
        return tuple(_row_to_stored_approval(row) for row in rows)

    def get_approval_receipt_for_plan(
        self, *, plan_identity: str, session_date: str | dt.date
    ) -> StoredApprovalReceipt | None:
        """Return the one raw approval row for a plan/session business key."""
        rows = self.query_approval_receipts(
            plan_identity=plan_identity, session_date=session_date
        )
        if len(rows) > 1:
            raise StoreError("APPROVAL_BUSINESS_KEY_CORRUPT") from None
        return rows[0] if rows else None

    def get_risk_transition_receipt(
        self, *, transition_kind: str, subject_id: str
    ) -> StoredRiskTransitionReceipt | None:
        """Return one immutable ORDER/CANCEL transition by exact subject."""
        kind = _require_transition_kind(transition_kind)
        subject = _require_identity(subject_id)
        mapped: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                "SELECT sequence, transition_kind, subject_id, receipt_id, "
                "previous_receipt_id, risk_counter_key, predecessor_counter_identity, "
                "projected_counter_identity, payload FROM risk_transition_receipts "
                "WHERE transition_kind = ? AND subject_id = ?",
                (kind, subject),
            ).fetchone()
        except sqlite3.Error:
            mapped = StoreError("RISK_RECEIPT_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None
        return None if row is None else _row_to_risk_receipt(row)

    def get_risk_transition_tail(self) -> StoredRiskTransitionReceipt | None:
        """Read the global journal tail inside this transaction."""
        mapped: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                "SELECT sequence, transition_kind, subject_id, receipt_id, "
                "previous_receipt_id, risk_counter_key, predecessor_counter_identity, "
                "projected_counter_identity, payload FROM risk_transition_receipts "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            mapped = StoreError("RISK_RECEIPT_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None
        return None if row is None else _row_to_risk_receipt(row)

    def put_risk_transition_receipt(
        self,
        *,
        sequence: int,
        transition_kind: str,
        subject_id: str,
        receipt_id: str,
        previous_receipt_id: str,
        risk_counter_key: str,
        predecessor_counter_identity: str,
        projected_counter_identity: str,
        payload: bytes,
    ) -> bool:
        """Insert one exact next transition; exact replay is a no-op."""
        if type(sequence) is not int or isinstance(sequence, bool) or sequence < 1:
            raise StoreError("RISK_RECEIPT_INVALID")
        candidate = StoredRiskTransitionReceipt(
            sequence=sequence,
            transition_kind=_require_transition_kind(transition_kind),
            subject_id=_require_identity(subject_id),
            receipt_id=_require_identity(receipt_id),
            previous_receipt_id=_require_identity(previous_receipt_id),
            risk_counter_key=_require_key("risk_counter_key", risk_counter_key),
            predecessor_counter_identity=_require_identity(predecessor_counter_identity),
            projected_counter_identity=_require_identity(projected_counter_identity),
            payload=_require_payload(payload),
        )
        existing = self.get_risk_transition_receipt(
            transition_kind=candidate.transition_kind,
            subject_id=candidate.subject_id,
        )
        if existing is not None:
            if existing == candidate:
                return False
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT:RISK_RECEIPT")
        tail = self.get_risk_transition_tail()
        expected_sequence = 1 if tail is None else tail.sequence + 1
        expected_previous = "0" * 64 if tail is None else tail.receipt_id
        if (
            candidate.sequence != expected_sequence
            or candidate.previous_receipt_id != expected_previous
        ):
            raise IdempotencyConflict("RISK_RECEIPT_CHAIN_CONFLICT")
        mapped: StoreError | None = None
        try:
            self._conn.execute(
                "INSERT INTO risk_transition_receipts "
                "(sequence, transition_kind, subject_id, receipt_id, "
                "previous_receipt_id, risk_counter_key, predecessor_counter_identity, "
                "projected_counter_identity, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.sequence, candidate.transition_kind, candidate.subject_id,
                    candidate.receipt_id, candidate.previous_receipt_id,
                    candidate.risk_counter_key, candidate.predecessor_counter_identity,
                    candidate.projected_counter_identity, candidate.payload,
                ),
            )
        except sqlite3.IntegrityError:
            mapped = IdempotencyConflict("RISK_RECEIPT_CHAIN_CONFLICT")
        except sqlite3.Error:
            mapped = StoreError("RISK_RECEIPT_WRITE_FAILED")
        if mapped is not None:
            raise mapped from None
        return True

    def put_scoped_daily_risk_counters(
        self, *, counter_key: str, identity: str, payload: bytes
    ) -> bool:
        """Insert the first durable counter snapshot for one explicit scope."""
        return self._put_row(
            table="scoped_daily_risk_counters",
            key_column="counter_key",
            key=_require_key("counter_key", counter_key),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="daily_risk_counters",
        )

    def get_scoped_daily_risk_counters(self, counter_key: str) -> StoredRecord | None:
        """Return the current opaque daily counter snapshot."""
        key = _require_key("counter_key", counter_key)
        mapped: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                "SELECT counter_key, identity, payload FROM scoped_daily_risk_counters "
                "WHERE counter_key = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            mapped = StoreError("DAILY_RISK_COUNTERS_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def compare_and_set_scoped_daily_risk_counters(
        self,
        *,
        counter_key: str,
        expected_identity: str,
        identity: str,
        payload: bytes,
    ) -> bool:
        """CAS-replace a counter snapshot; exact desired content is a no-op."""
        return self._replace_row_cas(
            table="scoped_daily_risk_counters",
            key_column="counter_key",
            key=_require_key("counter_key", counter_key),
            expected_identity=expected_identity,
            identity=identity,
            payload=payload,
            subject="DAILY_RISK_COUNTERS",
        )

    def put_outbox(self, *, outbox_key: str, identity: str, payload: bytes) -> bool:
        """Persist an outbox message; same key+payload is a no-op."""
        return self._put_row(
            table="outbox",
            key_column="outbox_key",
            key=_require_key("outbox_key", outbox_key),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="outbox",
        )

    def get_outbox(self, outbox_key: str) -> StoredRecord | None:
        key = _require_key("outbox_key", outbox_key)
        row = self._conn.execute(
            "SELECT outbox_key, identity, payload FROM outbox WHERE outbox_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def get_daily_risk_counters(
        self, session_date: dt.date
    ) -> StoredDailyRiskCounters | None:
        """Load one authenticated session row; missing means not initialized."""
        key = _require_session_date(session_date).isoformat()
        row = self._conn.execute(
            "SELECT session_date, identity, payload, updated_at "
            "FROM daily_risk_counters WHERE session_date = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_daily_risk_counters(row[0], row[1], row[2], row[3])

    def compare_and_set_daily_risk_counters(
        self,
        *,
        expected_identity: str | None,
        counters: DailyRiskCounters,
        updated_at: dt.datetime,
    ) -> bool:
        """Initialize or CAS one session; an exact committed retry is a no-op."""
        expected = (
            None if expected_identity is None else _require_identity(expected_identity)
        )
        if type(counters) is not DailyRiskCounters:
            raise StoreError("COUNTERS_INVALID")
        invalid_counters = False
        try:
            new_identity = build_daily_risk_counters_identity(counters)
            payload = serialize_daily_risk_counters(counters)
        except (ArithmeticError, AttributeError, RecursionError, TypeError, ValueError):
            invalid_counters = True
        if invalid_counters:
            raise StoreError("COUNTERS_INVALID") from None
        key = counters.session_date.isoformat()
        updated_text = _datetime_to_text(
            _require_utc_datetime("updated_at", updated_at)
        )
        current = self.get_daily_risk_counters(counters.session_date)
        if current is not None:
            if current.identity == new_identity:
                if current.counters != counters:
                    raise StoreError("ROW_CORRUPT")
                return False
            if expected is None or current.identity != expected:
                raise StoreError("RISK_COUNTERS_STALE")
            try:
                cursor = self._conn.execute(
                    "UPDATE daily_risk_counters "
                    "SET identity = ?, payload = ?, updated_at = ? "
                    "WHERE session_date = ? AND identity = ?",
                    (new_identity, payload, updated_text, key, expected),
                )
            except sqlite3.Error:
                raise StoreError("RISK_COUNTERS_WRITE_FAILED") from None
            if cursor.rowcount != 1:
                raise StoreError("RISK_COUNTERS_STALE")
            return True
        if expected is not None:
            raise StoreError("RISK_COUNTERS_STALE")
        try:
            self._conn.execute(
                "INSERT INTO daily_risk_counters "
                "(session_date, identity, payload, updated_at) VALUES (?, ?, ?, ?)",
                (key, new_identity, payload, updated_text),
            )
        except sqlite3.IntegrityError:
            raise StoreError("RISK_COUNTERS_STALE") from None
        except sqlite3.Error:
            raise StoreError("RISK_COUNTERS_WRITE_FAILED") from None
        return True

    @staticmethod
    def _delivery_columns() -> str:
        return (
            "d.outbox_key, d.command_id, d.state, d.attempt_count, "
            "d.available_at, d.lease_owner, d.lease_until, d.terminal_at, "
            "d.last_error_code, o.identity, o.payload, c.command_id, a.command_id"
        )

    def _select_outbox_delivery(self, outbox_key: str) -> OutboxDelivery | None:
        mapped: StoreError | None = None
        row: tuple[object, ...] | None = None
        try:
            row = self._conn.execute(
                f"SELECT {self._delivery_columns()} "
                "FROM outbox_deliveries AS d "
                "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                "WHERE d.outbox_key = ?",
                (outbox_key,),
            ).fetchone()
        except sqlite3.Error:
            mapped = StoreError("OUTBOX_DELIVERY_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None
        if row is None:
            return None
        return _row_to_outbox_delivery(row)

    def put_outbox_delivery(
        self,
        *,
        outbox_key: str,
        command_id: str,
        available_at: dt.datetime,
    ) -> bool:
        """Stage delivery metadata; legacy outbox rows remain non-sendable."""
        key = _require_key("outbox_key", outbox_key)
        command = _require_key("command_id", command_id)
        available_text = _datetime_to_text(
            _require_utc_datetime("available_at", available_at)
        )
        existing = self._select_outbox_delivery(key)
        if existing is not None:
            if (
                existing.command_id == command
                and _datetime_to_text(existing.available_at) == available_text
            ):
                return False
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT:outbox_delivery")

        mapped: StoreError | None = None
        try:
            self._conn.execute(
                """
                INSERT INTO outbox_deliveries (
                    outbox_key, command_id, state, attempt_count, available_at,
                    lease_owner, lease_until, terminal_at, last_error_code
                ) VALUES (?, ?, 'PENDING', 0, ?, NULL, NULL, NULL, NULL)
                """,
                (key, command, available_text),
            )
        except sqlite3.IntegrityError:
            mapped = StoreError("REFERENTIAL_INTEGRITY")
        except sqlite3.Error:
            mapped = StoreError("OUTBOX_DELIVERY_WRITE_FAILED")
        if mapped is not None:
            raise mapped from None
        return True

    def get_outbox_delivery(self, outbox_key: str) -> OutboxDelivery | None:
        """Return strict delivery metadata joined to opaque outbox bytes."""
        key = _require_key("outbox_key", outbox_key)
        return self._select_outbox_delivery(key)

    def claim_outbox_deliveries(
        self,
        *,
        worker_id: str,
        now: dt.datetime,
        lease_until: dt.datetime,
        limit: int,
    ) -> tuple[OutboxDelivery, ...]:
        """Claim ready or expired deliveries in deterministic order."""
        worker = _require_delivery_token("worker_id", worker_id)
        current = _require_utc_datetime("now", now)
        lease_end = _require_utc_datetime("lease_until", lease_until)
        if lease_end <= current:
            raise StoreError("lease_until must be after now")
        bounded_limit = _require_positive_int("limit", limit)
        now_text = _datetime_to_text(current)
        lease_text = _datetime_to_text(lease_end)

        mapped: StoreError | None = None
        rows: list[tuple[object, ...]] = []
        try:
            all_rows = self._conn.execute(
                f"SELECT {self._delivery_columns()} "
                "FROM outbox_deliveries AS d "
                "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                "ORDER BY d.outbox_key"
            ).fetchall()
            for row in all_rows:
                _row_to_outbox_delivery(row)
            rows = self._conn.execute(
                f"SELECT {self._delivery_columns()} "
                "FROM outbox_deliveries AS d "
                "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                "WHERE (d.state = 'PENDING' AND d.available_at <= ?) "
                "OR (d.state = 'LEASED' AND d.lease_until <= ?) "
                "ORDER BY d.available_at, d.outbox_key LIMIT ?",
                (now_text, now_text, bounded_limit),
            ).fetchall()
        except sqlite3.Error:
            mapped = StoreError("OUTBOX_DELIVERY_QUERY_FAILED")
        if mapped is not None:
            raise mapped from None

        candidates = tuple(_row_to_outbox_delivery(row) for row in rows)
        for candidate in candidates:
            eligible = (
                candidate.state is OutboxDeliveryState.PENDING
                and candidate.available_at <= current
            ) or (
                candidate.state is OutboxDeliveryState.LEASED
                and candidate.lease_until is not None
                and candidate.lease_until <= current
            )
            if not eligible:
                raise StoreError("ROW_CORRUPT")
            if candidate.attempt_count >= _SQLITE_MAX_INT:
                raise StoreError("OUTBOX_DELIVERY_ATTEMPT_EXHAUSTED")

        savepoint_error: StoreError | None = None
        try:
            self._conn.execute("SAVEPOINT outbox_delivery_claim")
        except sqlite3.Error:
            savepoint_error = StoreError("OUTBOX_DELIVERY_CLAIM_FAILED")
        if savepoint_error is not None:
            raise savepoint_error from None

        claim_error: Exception | None = None
        claimed: list[OutboxDelivery] = []
        try:
            for candidate in candidates:
                write_error: StoreError | None = None
                changed = 0
                try:
                    cursor = self._conn.execute(
                        """
                        UPDATE outbox_deliveries
                        SET state = 'LEASED', attempt_count = attempt_count + 1,
                            lease_owner = ?, lease_until = ?, terminal_at = NULL,
                            last_error_code = NULL
                        WHERE outbox_key = ? AND (
                            (state = 'PENDING' AND available_at <= ?)
                            OR (state = 'LEASED' AND lease_until <= ?)
                        )
                        """,
                        (
                            worker,
                            lease_text,
                            candidate.outbox_key,
                            now_text,
                            now_text,
                        ),
                    )
                    changed = cursor.rowcount
                except sqlite3.Error:
                    write_error = StoreError("OUTBOX_DELIVERY_CLAIM_FAILED")
                if write_error is not None:
                    raise write_error from None
                if changed != 1:
                    raise StoreError("OUTBOX_DELIVERY_CLAIM_CONFLICT")

            for candidate in candidates:
                row = self._select_outbox_delivery(candidate.outbox_key)
                if row is None:
                    raise StoreError("ROW_CORRUPT")
                claimed.append(row)
            release_error: StoreError | None = None
            try:
                self._conn.execute("RELEASE SAVEPOINT outbox_delivery_claim")
            except sqlite3.Error:
                release_error = StoreError("OUTBOX_DELIVERY_CLAIM_FAILED")
            if release_error is not None:
                raise release_error from None
        except Exception as exc:
            claim_error = exc

        if claim_error is not None:
            rollback_failed = False
            try:
                self._conn.execute("ROLLBACK TO SAVEPOINT outbox_delivery_claim")
                self._conn.execute("RELEASE SAVEPOINT outbox_delivery_claim")
            except sqlite3.Error:
                rollback_failed = True
            if rollback_failed:
                raise StoreError("OUTBOX_DELIVERY_ROLLBACK_FAILED") from None
            raise claim_error
        return tuple(claimed)

    def claim_selected_outbox_deliveries(
        self,
        *,
        command_ids: tuple[str, ...],
        worker_id: str,
        now: dt.datetime,
        lease_until: dt.datetime,
    ) -> tuple[OutboxDelivery, ...]:
        """Atomically claim exactly the canonical commands selected by the caller."""
        if type(command_ids) is not tuple or not command_ids:
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID")
        try:
            selected = tuple(_require_identity(item) for item in command_ids)
        except StoreError:
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID") from None
        if selected != tuple(sorted(selected)) or len(set(selected)) != len(selected):
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID")

        worker = _require_delivery_token("worker_id", worker_id)
        current = _require_utc_datetime("now", now)
        lease_end = _require_utc_datetime("lease_until", lease_until)
        if lease_end <= current:
            raise StoreError("lease_until must be after now")
        now_text = _datetime_to_text(current)
        lease_text = _datetime_to_text(lease_end)

        # Validate every member before the first write.  Besides preventing a
        # partial claim, these explicit equality checks close the command ->
        # outbox -> delivery identity/payload chain used by PAPER dispatch.
        candidates: list[OutboxDelivery] = []
        try:
            for command_id in selected:
                row = self._conn.execute(
                    f"SELECT {self._delivery_columns()} "
                    "FROM outbox_deliveries AS d "
                    "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                    "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                    "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                    "WHERE d.command_id = ?",
                    (command_id,),
                ).fetchone()
                if row is None:
                    raise StoreError("OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE")
                try:
                    candidate = _row_to_outbox_delivery(row)
                except StoreError:
                    raise StoreError(
                        "OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE"
                    ) from None
                command = self.get_command(command_id)
                outbox = self.get_outbox(candidate.outbox_key)
                if (
                    candidate.command_id != command_id
                    or candidate.outbox_key != command_id
                    or candidate.identity != command_id
                    or command is None
                    or command.key != command_id
                    or command.identity != command_id
                    or command.payload != candidate.payload
                    or outbox is None
                    or outbox.key != command_id
                    or outbox.identity != command_id
                    or outbox.payload != candidate.payload
                ):
                    raise StoreError("OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE")
                eligible = (
                    candidate.state is OutboxDeliveryState.PENDING
                    and candidate.available_at <= current
                ) or (
                    candidate.state is OutboxDeliveryState.LEASED
                    and candidate.lease_until is not None
                    and candidate.lease_until < current
                )
                if not eligible:
                    raise StoreError("OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE")
                if candidate.attempt_count >= _SQLITE_MAX_INT:
                    raise StoreError("OUTBOX_DELIVERY_ATTEMPT_EXHAUSTED")
                candidates.append(candidate)
        except sqlite3.Error:
            raise StoreError("OUTBOX_DELIVERY_QUERY_FAILED") from None

        try:
            self._conn.execute("SAVEPOINT selected_outbox_delivery_claim")
        except sqlite3.Error:
            raise StoreError("OUTBOX_DELIVERY_CLAIM_FAILED") from None

        claim_error: Exception | None = None
        claimed: list[OutboxDelivery] = []
        try:
            for candidate in candidates:
                cursor = self._conn.execute(
                    """
                    UPDATE outbox_deliveries
                    SET state = 'LEASED', attempt_count = attempt_count + 1,
                        lease_owner = ?, lease_until = ?, terminal_at = NULL,
                        last_error_code = NULL
                    WHERE outbox_key = ? AND command_id = ? AND (
                        (state = 'PENDING' AND available_at <= ?)
                        OR (state = 'LEASED' AND lease_until < ?)
                    )
                    """,
                    (
                        worker,
                        lease_text,
                        candidate.outbox_key,
                        candidate.command_id,
                        now_text,
                        now_text,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StoreError("OUTBOX_DELIVERY_CLAIM_CONFLICT")
            for candidate in candidates:
                refreshed = self._select_outbox_delivery(candidate.outbox_key)
                if refreshed is None:
                    raise StoreError("ROW_CORRUPT")
                claimed.append(refreshed)
            self._conn.execute("RELEASE SAVEPOINT selected_outbox_delivery_claim")
        except sqlite3.Error:
            claim_error = StoreError("OUTBOX_DELIVERY_CLAIM_FAILED")
        except Exception as exc:
            claim_error = exc

        if claim_error is not None:
            try:
                self._conn.execute("ROLLBACK TO SAVEPOINT selected_outbox_delivery_claim")
                self._conn.execute("RELEASE SAVEPOINT selected_outbox_delivery_claim")
            except sqlite3.Error:
                raise StoreError("OUTBOX_DELIVERY_ROLLBACK_FAILED") from None
            raise claim_error
        return tuple(claimed)

    def claim_exact_pending_outbox_deliveries(
        self,
        *,
        command_ids: tuple[str, ...],
        worker_id: str,
        now: dt.datetime,
        lease_until: dt.datetime,
    ) -> tuple[OutboxDelivery, ...]:
        """Claim only when the caller selection is the complete pending set."""
        if type(command_ids) is not tuple or not command_ids:
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID")
        try:
            selected = tuple(_require_identity(item) for item in command_ids)
            current = _require_utc_datetime("now", now)
        except StoreError:
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID") from None
        if selected != tuple(sorted(selected)) or len(set(selected)) != len(selected):
            raise StoreError("OUTBOX_DELIVERY_SELECTION_INVALID")

        query_failure_code: str | None = None
        deliveries: tuple[OutboxDelivery, ...] = ()
        try:
            rows = self._conn.execute(
                f"SELECT {self._delivery_columns()} "
                "FROM outbox_deliveries AS d "
                "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                "ORDER BY d.command_id"
            ).fetchall()
            deliveries = tuple(_row_to_outbox_delivery(row) for row in rows)
        except sqlite3.Error:
            query_failure_code = "OUTBOX_DELIVERY_EXACT_QUERY_FAILED"
        except StoreError:
            query_failure_code = "OUTBOX_DELIVERY_EXACT_SET_DRIFT"
        if query_failure_code is not None:
            raise StoreError(query_failure_code)

        if any(
            item.state in {OutboxDeliveryState.LEASED, OutboxDeliveryState.UNKNOWN}
            for item in deliveries
        ):
            raise StoreError("OUTBOX_DELIVERY_EXACT_SET_DRIFT")
        pending = tuple(
            item.command_id
            for item in deliveries
            if item.state is OutboxDeliveryState.PENDING
        )
        if (
            pending != selected
            or any(
                item.state is OutboxDeliveryState.PENDING
                and item.available_at > current
                for item in deliveries
            )
        ):
            raise StoreError("OUTBOX_DELIVERY_EXACT_SET_DRIFT")
        claim_failure_code: str | None = None
        try:
            return self.claim_selected_outbox_deliveries(
                command_ids=selected,
                worker_id=worker_id,
                now=current,
                lease_until=lease_until,
            )
        except StoreError as exc:
            if exc.args in {
                ("OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE",),
                ("OUTBOX_DELIVERY_CLAIM_CONFLICT",),
            }:
                claim_failure_code = "OUTBOX_DELIVERY_EXACT_SET_DRIFT"
            else:
                claim_failure_code = "OUTBOX_DELIVERY_EXACT_CLAIM_FAILED"
        except Exception:
            claim_failure_code = "OUTBOX_DELIVERY_EXACT_CLAIM_FAILED"
        assert claim_failure_code is not None
        raise StoreError(claim_failure_code)

    def mark_outbox_sent(
        self,
        *,
        outbox_key: str,
        lease_owner: str,
        expected_attempt: int,
        sent_at: dt.datetime,
    ) -> bool:
        """Move the caller-owned lease to terminal SENT."""
        key = _require_key("outbox_key", outbox_key)
        owner = _require_delivery_token("lease_owner", lease_owner)
        attempt = _require_positive_int("expected_attempt", expected_attempt)
        sent = _require_utc_datetime("sent_at", sent_at)
        sent_text = _datetime_to_text(sent)
        existing = self._select_outbox_delivery(key)
        if existing is None:
            raise StoreError("OUTBOX_DELIVERY_NOT_FOUND")
        if existing.state is OutboxDeliveryState.SENT:
            if (
                existing.lease_owner == owner
                and existing.attempt_count == attempt
                and existing.terminal_at == sent
            ):
                return False
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT:outbox_delivery_sent")
        if existing.state is not OutboxDeliveryState.LEASED:
            raise StoreError("OUTBOX_DELIVERY_TRANSITION_INVALID")
        if existing.lease_owner != owner:
            raise StoreError("OUTBOX_DELIVERY_LEASE_MISMATCH")
        if existing.attempt_count != attempt:
            raise StoreError("OUTBOX_DELIVERY_FENCE_MISMATCH")
        if sent < existing.available_at:
            raise StoreError("sent_at precedes available_at")
        assert existing.lease_until is not None
        if sent >= existing.lease_until:
            raise StoreError("OUTBOX_DELIVERY_LEASE_EXPIRED")

        mapped: StoreError | None = None
        changed = 0
        try:
            cursor = self._conn.execute(
                """
                UPDATE outbox_deliveries
                SET state = 'SENT', terminal_at = ?, last_error_code = NULL
                WHERE outbox_key = ? AND state = 'LEASED' AND lease_owner = ?
                    AND attempt_count = ?
                """,
                (sent_text, key, owner, attempt),
            )
            changed = cursor.rowcount
        except sqlite3.Error:
            mapped = StoreError("OUTBOX_DELIVERY_WRITE_FAILED")
        if mapped is not None:
            raise mapped from None
        if changed != 1:
            raise StoreError("OUTBOX_DELIVERY_TRANSITION_CONFLICT")
        return True

    def mark_outbox_unknown(
        self,
        *,
        outbox_key: str,
        lease_owner: str,
        expected_attempt: int,
        unknown_at: dt.datetime,
        error_code: str,
    ) -> bool:
        """Move the caller-owned lease to terminal UNKNOWN; never auto-retry it."""
        key = _require_key("outbox_key", outbox_key)
        owner = _require_delivery_token("lease_owner", lease_owner)
        attempt = _require_positive_int("expected_attempt", expected_attempt)
        terminal = _require_utc_datetime("unknown_at", unknown_at)
        terminal_text = _datetime_to_text(terminal)
        code = _require_delivery_token("error_code", error_code)
        existing = self._select_outbox_delivery(key)
        if existing is None:
            raise StoreError("OUTBOX_DELIVERY_NOT_FOUND")
        if existing.state is OutboxDeliveryState.UNKNOWN:
            if (
                existing.lease_owner == owner
                and existing.attempt_count == attempt
                and existing.terminal_at == terminal
                and existing.last_error_code == code
            ):
                return False
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT:outbox_delivery_unknown")
        if existing.state is not OutboxDeliveryState.LEASED:
            raise StoreError("OUTBOX_DELIVERY_TRANSITION_INVALID")
        if existing.lease_owner != owner:
            raise StoreError("OUTBOX_DELIVERY_LEASE_MISMATCH")
        if existing.attempt_count != attempt:
            raise StoreError("OUTBOX_DELIVERY_FENCE_MISMATCH")
        if terminal < existing.available_at:
            raise StoreError("unknown_at precedes available_at")
        assert existing.lease_until is not None
        if terminal >= existing.lease_until:
            raise StoreError("OUTBOX_DELIVERY_LEASE_EXPIRED")

        mapped: StoreError | None = None
        changed = 0
        try:
            cursor = self._conn.execute(
                """
                UPDATE outbox_deliveries
                SET state = 'UNKNOWN', terminal_at = ?, last_error_code = ?
                WHERE outbox_key = ? AND state = 'LEASED' AND lease_owner = ?
                    AND attempt_count = ?
                """,
                (terminal_text, code, key, owner, attempt),
            )
            changed = cursor.rowcount
        except sqlite3.Error:
            mapped = StoreError("OUTBOX_DELIVERY_WRITE_FAILED")
        if mapped is not None:
            raise mapped from None
        if changed != 1:
            raise StoreError("OUTBOX_DELIVERY_TRANSITION_CONFLICT")
        return True

    def put_ledger_entry(self, *, entry_id: str, identity: str, payload: bytes) -> bool:
        """Persist a ledger entry row."""
        return self._put_row(
            table="ledger_entries",
            key_column="entry_id",
            key=_require_key("entry_id", entry_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="ledger_entry",
        )

    def get_ledger_entry(self, entry_id: str) -> StoredRecord | None:
        key = _require_key("entry_id", entry_id)
        row = self._conn.execute(
            "SELECT entry_id, identity, payload FROM ledger_entries WHERE entry_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])

    def put_ledger_context(
        self, *, command_id: str, identity: str, payload: bytes
    ) -> bool:
        """Persist the immutable B5 inputs selected before dispatch."""
        return self._put_row(
            table="ledger_contexts",
            key_column="command_id",
            key=_require_key("command_id", command_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="ledger_context",
        )

    def get_ledger_context(self, command_id: str) -> StoredRecord | None:
        key = _require_key("command_id", command_id)
        try:
            row = self._conn.execute(
                "SELECT command_id, identity, payload FROM ledger_contexts "
                "WHERE command_id = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            raise StoreError("LEDGER_CONTEXT_QUERY_FAILED") from None
        return None if row is None else _row_to_stored(*row)

    def put_ledger_checkpoint(
        self,
        *,
        checkpoint_key: str,
        identity: str,
        payload: bytes,
        last_entry_id: str | None,
    ) -> bool:
        """Insert the genesis checkpoint; exact content is idempotent."""
        key = _require_checkpoint_key(checkpoint_key)
        ident = _require_identity(identity)
        data = _require_payload(payload)
        tail = None if last_entry_id is None else _require_key("last_entry_id", last_entry_id)
        existing = self.get_ledger_checkpoint(key)
        if existing is not None:
            if (existing.identity, existing.payload, existing.last_entry_id) == (
                ident, data, tail
            ):
                return False
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT:ledger_checkpoint")
        try:
            self._conn.execute(
                "INSERT INTO ledger_checkpoints "
                "(checkpoint_key, identity, payload, last_entry_id) VALUES (?, ?, ?, ?)",
                (key, ident, data, tail),
            )
        except sqlite3.Error:
            raise StoreError("LEDGER_CHECKPOINT_WRITE_FAILED") from None
        return True

    def get_ledger_checkpoint(
        self, checkpoint_key: str
    ) -> StoredLedgerCheckpoint | None:
        key = _require_checkpoint_key(checkpoint_key)
        try:
            row = self._conn.execute(
                "SELECT c.checkpoint_key, c.identity, c.payload, c.last_entry_id, "
                "e.entry_id FROM ledger_checkpoints AS c "
                "LEFT JOIN ledger_entries AS e ON e.entry_id = c.last_entry_id "
                "WHERE c.checkpoint_key = ?",
                (key,),
            ).fetchone()
        except sqlite3.Error:
            raise StoreError("LEDGER_CHECKPOINT_QUERY_FAILED") from None
        return None if row is None else _row_to_ledger_checkpoint(row)

    def replace_ledger_checkpoint(
        self,
        *,
        checkpoint_key: str,
        expected_identity: str,
        identity: str,
        payload: bytes,
        last_entry_id: str | None,
    ) -> bool:
        """CAS-replace the checkpoint and its append-only tail."""
        key = _require_checkpoint_key(checkpoint_key)
        expected = _require_identity(expected_identity)
        ident = _require_identity(identity)
        data = _require_payload(payload)
        tail = None if last_entry_id is None else _require_key("last_entry_id", last_entry_id)
        existing = self.get_ledger_checkpoint(key)
        if existing is None:
            raise StoreError("LEDGER_CHECKPOINT_NOT_FOUND")
        if (existing.identity, existing.payload, existing.last_entry_id) == (
            ident, data, tail
        ):
            return False
        if existing.identity != expected:
            raise StoreError("LEDGER_CHECKPOINT_CAS_CONFLICT")
        try:
            cursor = self._conn.execute(
                "UPDATE ledger_checkpoints SET identity = ?, payload = ?, last_entry_id = ? "
                "WHERE checkpoint_key = ? AND identity = ?",
                (ident, data, tail, key, expected),
            )
        except sqlite3.Error:
            raise StoreError("LEDGER_CHECKPOINT_WRITE_FAILED") from None
        if cursor.rowcount != 1:
            raise StoreError("LEDGER_CHECKPOINT_CAS_CONFLICT")
        return True

    def put_cancel_command(
        self,
        *,
        cancel_id: str,
        command_id: str,
        identity: str,
        payload: bytes,
        risk_counter_key: str,
        risk_policy_identity: str,
    ) -> bool:
        """Insert one immutable cancel request and its risk-source closure."""
        cancel = _require_identity(cancel_id)
        command = _require_identity(command_id)
        ident = _require_identity(identity)
        data = _require_payload(payload)
        counter_key = _require_delivery_token("risk_counter_key", risk_counter_key)
        policy_id = _require_identity(risk_policy_identity)
        if cancel != ident:
            raise StoreError("CANCEL_IDENTITY_INVALID")
        existing = self.get_cancel_command(cancel)
        by_command = self.get_cancel_command_for_order(command)
        expected = StoredCancelCommand(
            cancel_id=cancel,
            command_id=command,
            identity=ident,
            payload=data,
            risk_counter_key=counter_key,
            risk_policy_identity=policy_id,
        )
        if existing is not None or by_command is not None:
            if existing == expected and by_command == expected:
                return False
            raise IdempotencyConflict("CANCEL_IDENTITY_CONFLICT")
        try:
            self._conn.execute(
                "INSERT INTO cancel_commands "
                "(cancel_id, command_id, identity, payload, risk_counter_key, "
                "risk_policy_identity) VALUES (?, ?, ?, ?, ?, ?)",
                (cancel, command, ident, data, counter_key, policy_id),
            )
        except sqlite3.IntegrityError:
            raise IdempotencyConflict("CANCEL_IDENTITY_CONFLICT") from None
        except sqlite3.Error:
            raise StoreError("CANCEL_COMMAND_WRITE_FAILED") from None
        return True

    def get_cancel_command(self, cancel_id: str) -> StoredCancelCommand | None:
        cancel = _require_identity(cancel_id)
        row = self._conn.execute(
            "SELECT cc.cancel_id, cc.command_id, cc.identity, cc.payload, "
            "cc.risk_counter_key, cc.risk_policy_identity, cc.cancel_id, "
            "c.command_id FROM cancel_commands AS cc "
            "LEFT JOIN commands AS c ON c.command_id = cc.command_id "
            "WHERE cc.cancel_id = ?",
            (cancel,),
        ).fetchone()
        return None if row is None else _row_to_cancel_command(row)

    def get_cancel_command_for_order(
        self, command_id: str
    ) -> StoredCancelCommand | None:
        command = _require_identity(command_id)
        row = self._conn.execute(
            "SELECT cc.cancel_id, cc.command_id, cc.identity, cc.payload, "
            "cc.risk_counter_key, cc.risk_policy_identity, cc.cancel_id, "
            "c.command_id FROM cancel_commands AS cc "
            "LEFT JOIN commands AS c ON c.command_id = cc.command_id "
            "WHERE cc.command_id = ?",
            (command,),
        ).fetchone()
        return None if row is None else _row_to_cancel_command(row)

    @staticmethod
    def _cancel_delivery_columns() -> str:
        return (
            "d.cancel_id, d.command_id, d.state, d.attempt_count, d.available_at, "
            "d.lease_owner, d.lease_until, d.terminal_at, d.last_error_code, "
            "cc.identity, cc.payload, cc.cancel_id, cc.command_id, c.command_id"
        )

    def _select_cancel_delivery(
        self, cancel_id: str
    ) -> CancelOutboxDelivery | None:
        row = self._conn.execute(
            f"SELECT {self._cancel_delivery_columns()} "
            "FROM cancel_deliveries AS d "
            "LEFT JOIN cancel_commands AS cc ON cc.cancel_id = d.cancel_id "
            "LEFT JOIN commands AS c ON c.command_id = d.command_id "
            "WHERE d.cancel_id = ?",
            (cancel_id,),
        ).fetchone()
        return None if row is None else _row_to_cancel_delivery(row)

    def put_cancel_delivery(
        self, *, cancel_id: str, command_id: str, available_at: dt.datetime
    ) -> bool:
        """Insert the unique initial PENDING delivery for one cancel."""
        cancel = _require_identity(cancel_id)
        command = _require_identity(command_id)
        available = _require_utc_datetime("available_at", available_at)
        existing = self._select_cancel_delivery(cancel)
        if existing is not None:
            if (
                existing.command_id == command
                and existing.state is OutboxDeliveryState.PENDING
                and existing.attempt_count == 0
                and existing.available_at == available
            ):
                return False
            raise IdempotencyConflict("CANCEL_DELIVERY_CONFLICT")
        try:
            self._conn.execute(
                "INSERT INTO cancel_deliveries "
                "(cancel_id, command_id, state, attempt_count, available_at) "
                "VALUES (?, ?, 'PENDING', 0, ?)",
                (cancel, command, _datetime_to_text(available)),
            )
        except sqlite3.IntegrityError:
            raise IdempotencyConflict("CANCEL_DELIVERY_CONFLICT") from None
        except sqlite3.Error:
            raise StoreError("CANCEL_DELIVERY_WRITE_FAILED") from None
        return True

    def get_cancel_delivery(self, cancel_id: str) -> CancelOutboxDelivery | None:
        return self._select_cancel_delivery(_require_identity(cancel_id))

    def claim_cancel_delivery(
        self,
        *,
        cancel_id: str,
        worker_id: str,
        now: dt.datetime,
        lease_until: dt.datetime,
    ) -> CancelOutboxDelivery:
        """Lease exactly one canonical cancel delivery, never a global queue row."""
        cancel = _require_identity(cancel_id)
        worker = _require_delivery_token("worker_id", worker_id)
        current = _require_utc_datetime("now", now)
        lease_end = _require_utc_datetime("lease_until", lease_until)
        if lease_end <= current:
            raise StoreError("CANCEL_DELIVERY_LEASE_INVALID")
        candidate = self._select_cancel_delivery(cancel)
        if candidate is None:
            raise StoreError("CANCEL_DELIVERY_NOT_CLAIMABLE")
        eligible = (
            candidate.state is OutboxDeliveryState.PENDING
            and candidate.available_at <= current
        ) or (
            candidate.state is OutboxDeliveryState.LEASED
            and candidate.lease_until is not None
            and candidate.lease_until < current
            and candidate.last_error_code is None
        )
        if not eligible or candidate.attempt_count >= _SQLITE_MAX_INT:
            raise StoreError("CANCEL_DELIVERY_NOT_CLAIMABLE")
        try:
            cursor = self._conn.execute(
                "UPDATE cancel_deliveries SET state='LEASED', "
                "attempt_count=attempt_count+1, lease_owner=?, lease_until=?, "
                "terminal_at=NULL, last_error_code=NULL WHERE cancel_id=? AND "
                "((state='PENDING' AND available_at<=?) OR "
                "(state='LEASED' AND lease_until<? AND last_error_code IS NULL))",
                (
                    worker,
                    _datetime_to_text(lease_end),
                    cancel,
                    _datetime_to_text(current),
                    _datetime_to_text(current),
                ),
            )
        except sqlite3.Error:
            raise StoreError("CANCEL_DELIVERY_CLAIM_FAILED") from None
        if cursor.rowcount != 1:
            raise StoreError("CANCEL_DELIVERY_NOT_CLAIMABLE")
        claimed = self._select_cancel_delivery(cancel)
        if claimed is None:
            raise StoreError("ROW_CORRUPT")
        return claimed

    def mark_cancel_gateway_started(
        self,
        *,
        cancel_id: str,
        lease_owner: str,
        expected_attempt: int,
    ) -> bool:
        """Durably fence a cancel attempt before it may cross the adapter."""
        cancel = _require_identity(cancel_id)
        owner = _require_delivery_token("lease_owner", lease_owner)
        attempt = _require_positive_int("expected_attempt", expected_attempt)
        current = self._select_cancel_delivery(cancel)
        if (
            current is None
            or current.state is not OutboxDeliveryState.LEASED
            or current.lease_owner != owner
            or current.attempt_count != attempt
            or current.lease_until is None
            or current.last_error_code is not None
        ):
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        try:
            cursor = self._conn.execute(
                "UPDATE cancel_deliveries SET last_error_code="
                "'CANCEL_GATEWAY_STARTED' WHERE cancel_id=? AND state='LEASED' "
                "AND lease_owner=? AND attempt_count=? AND last_error_code IS NULL",
                (cancel, owner, attempt),
            )
        except sqlite3.Error:
            raise StoreError("CANCEL_DELIVERY_FINALIZE_FAILED") from None
        if cursor.rowcount != 1:
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        return True

    def mark_cancel_sent(
        self,
        *,
        cancel_id: str,
        lease_owner: str,
        expected_attempt: int,
        sent_at: dt.datetime,
    ) -> bool:
        return self._mark_cancel_terminal(
            cancel_id=cancel_id,
            lease_owner=lease_owner,
            expected_attempt=expected_attempt,
            terminal_at=sent_at,
            state=OutboxDeliveryState.SENT,
            error_code=None,
        )

    def mark_cancel_unknown(
        self,
        *,
        cancel_id: str,
        lease_owner: str,
        expected_attempt: int,
        unknown_at: dt.datetime,
        error_code: str,
    ) -> bool:
        return self._mark_cancel_terminal(
            cancel_id=cancel_id,
            lease_owner=lease_owner,
            expected_attempt=expected_attempt,
            terminal_at=unknown_at,
            state=OutboxDeliveryState.UNKNOWN,
            error_code=_require_delivery_token("error_code", error_code),
        )

    def _mark_cancel_terminal(
        self,
        *,
        cancel_id: str,
        lease_owner: str,
        expected_attempt: int,
        terminal_at: dt.datetime,
        state: OutboxDeliveryState,
        error_code: str | None,
    ) -> bool:
        cancel = _require_identity(cancel_id)
        owner = _require_delivery_token("lease_owner", lease_owner)
        attempt = _require_positive_int("expected_attempt", expected_attempt)
        terminal = _require_utc_datetime("terminal_at", terminal_at)
        if state not in {OutboxDeliveryState.SENT, OutboxDeliveryState.UNKNOWN}:
            raise StoreError("CANCEL_DELIVERY_STATE_INVALID")
        current = self._select_cancel_delivery(cancel)
        if current is None:
            raise StoreError("CANCEL_DELIVERY_NOT_FOUND")
        if current.state is state:
            if (
                current.lease_owner == owner
                and current.attempt_count == attempt
                and current.terminal_at == terminal
                and current.last_error_code == error_code
            ):
                return False
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        if (
            current.state is not OutboxDeliveryState.LEASED
            or current.lease_owner != owner
            or current.attempt_count != attempt
            or current.lease_until is None
            or terminal < current.available_at
        ):
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        try:
            cursor = self._conn.execute(
                "UPDATE cancel_deliveries SET state=?, terminal_at=?, "
                "last_error_code=? WHERE cancel_id=? AND state='LEASED' AND "
                "lease_owner=? AND attempt_count=?",
                (
                    state.value,
                    _datetime_to_text(terminal),
                    error_code,
                    cancel,
                    owner,
                    attempt,
                ),
            )
        except sqlite3.Error:
            raise StoreError("CANCEL_DELIVERY_FINALIZE_FAILED") from None
        if cursor.rowcount != 1:
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        return True

    def mark_cancel_not_sent(
        self,
        *,
        cancel_id: str,
        lease_owner: str,
        expected_attempt: int,
        retry_at: dt.datetime,
    ) -> bool:
        """Return a proven NOT_SENT cancel to explicit-retry PENDING state."""
        cancel = _require_identity(cancel_id)
        owner = _require_delivery_token("lease_owner", lease_owner)
        attempt = _require_positive_int("expected_attempt", expected_attempt)
        retry = _require_utc_datetime("retry_at", retry_at)
        current = self._select_cancel_delivery(cancel)
        if (
            current is None
            or current.state is not OutboxDeliveryState.LEASED
            or current.lease_owner != owner
            or current.attempt_count != attempt
            or current.lease_until is None
            or retry < current.available_at
        ):
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        try:
            cursor = self._conn.execute(
                "UPDATE cancel_deliveries SET state='PENDING', available_at=?, "
                "lease_owner=NULL, lease_until=NULL, terminal_at=NULL, "
                "last_error_code='CANCEL_GATEWAY_NOT_SENT' "
                "WHERE cancel_id=? AND state='LEASED' AND "
                "lease_owner=? AND attempt_count=?",
                (_datetime_to_text(retry), cancel, owner, attempt),
            )
        except sqlite3.Error:
            raise StoreError("CANCEL_DELIVERY_FINALIZE_FAILED") from None
        if cursor.rowcount != 1:
            raise StoreError("CANCEL_DELIVERY_FENCE_MISMATCH")
        return True

    def put_cancel_event_link(self, *, cancel_id: str, event_id: str) -> bool:
        cancel = _require_identity(cancel_id)
        event = _require_identity(event_id)
        row = self._conn.execute(
            "SELECT cancel_id, event_id FROM cancel_event_links "
            "WHERE cancel_id=? AND event_id=?",
            (cancel, event),
        ).fetchone()
        if row is not None:
            if row == (cancel, event):
                return False
            raise IdempotencyConflict("CANCEL_CALLBACK_CONFLICT")
        try:
            self._conn.execute(
                "INSERT INTO cancel_event_links (cancel_id, event_id) VALUES (?, ?)",
                (cancel, event),
            )
        except sqlite3.IntegrityError:
            raise IdempotencyConflict("CANCEL_CALLBACK_CONFLICT") from None
        except sqlite3.Error:
            raise StoreError("CANCEL_CALLBACK_LINK_FAILED") from None
        return True

    def read_recovery_rows(self) -> RecoveryRows:
        """Read all recovery inputs atomically inside the caller's transaction."""
        query_error: StoreError | None = None
        command_rows: list[tuple[object, ...]] = []
        event_rows: list[tuple[object, ...]] = []
        aggregate_rows: list[tuple[object, ...]] = []
        delivery_rows: list[tuple[object, ...]] = []
        ledger_rows: list[tuple[object, ...]] = []
        context_rows: list[tuple[object, ...]] = []
        checkpoint_rows: list[tuple[object, ...]] = []
        cancel_rows: list[tuple[object, ...]] = []
        cancel_delivery_rows: list[tuple[object, ...]] = []
        cancel_link_rows: list[tuple[object, ...]] = []
        risk_receipt_rows: list[tuple[object, ...]] = []
        risk_counter_rows: list[tuple[object, ...]] = []
        approval_receipt_rows: list[tuple[object, ...]] = []
        try:
            command_rows = self._conn.execute(
                "SELECT command_id, identity, payload FROM commands ORDER BY command_id"
            ).fetchall()
            event_rows = self._conn.execute(
                "SELECT e.event_id, e.command_id, e.identity, e.payload, c.command_id "
                "FROM events AS e "
                "LEFT JOIN commands AS c ON c.command_id = e.command_id "
                "ORDER BY e.event_id"
            ).fetchall()
            aggregate_rows = self._conn.execute(
                "SELECT a.command_id, a.identity, a.payload, c.command_id "
                "FROM order_aggregates AS a "
                "LEFT JOIN commands AS c ON c.command_id = a.command_id "
                "ORDER BY a.command_id"
            ).fetchall()
            delivery_rows = self._conn.execute(
                f"SELECT {self._delivery_columns()} "
                "FROM outbox_deliveries AS d "
                "LEFT JOIN outbox AS o ON o.outbox_key = d.outbox_key "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "LEFT JOIN order_aggregates AS a ON a.command_id = d.command_id "
                "ORDER BY d.outbox_key"
            ).fetchall()
            ledger_rows = self._conn.execute(
                "SELECT entry_id, identity, payload FROM ledger_entries ORDER BY entry_id"
            ).fetchall()
            context_rows = self._conn.execute(
                "SELECT lc.command_id, lc.identity, lc.payload, c.command_id "
                "FROM ledger_contexts AS lc "
                "LEFT JOIN commands AS c ON c.command_id = lc.command_id "
                "ORDER BY lc.command_id"
            ).fetchall()
            checkpoint_rows = self._conn.execute(
                "SELECT c.checkpoint_key, c.identity, c.payload, c.last_entry_id, "
                "e.entry_id FROM ledger_checkpoints AS c "
                "LEFT JOIN ledger_entries AS e ON e.entry_id = c.last_entry_id "
                "ORDER BY c.checkpoint_key"
            ).fetchall()
            cancel_rows = self._conn.execute(
                "SELECT cc.cancel_id, cc.command_id, cc.identity, cc.payload, "
                "cc.risk_counter_key, cc.risk_policy_identity, cc.cancel_id, "
                "c.command_id FROM cancel_commands AS cc "
                "LEFT JOIN commands AS c ON c.command_id = cc.command_id "
                "ORDER BY cc.cancel_id"
            ).fetchall()
            cancel_delivery_rows = self._conn.execute(
                "SELECT d.cancel_id, d.command_id, d.state, d.attempt_count, "
                "d.available_at, d.lease_owner, d.lease_until, d.terminal_at, "
                "d.last_error_code, cc.identity, cc.payload, cc.cancel_id, "
                "cc.command_id, c.command_id FROM cancel_deliveries AS d "
                "LEFT JOIN cancel_commands AS cc ON cc.cancel_id = d.cancel_id "
                "LEFT JOIN commands AS c ON c.command_id = d.command_id "
                "ORDER BY d.cancel_id"
            ).fetchall()
            cancel_link_rows = self._conn.execute(
                "SELECT l.cancel_id, l.event_id, cc.cancel_id, e.event_id, "
                "e.command_id FROM cancel_event_links AS l "
                "LEFT JOIN cancel_commands AS cc ON cc.cancel_id = l.cancel_id "
                "LEFT JOIN events AS e ON e.event_id = l.event_id "
                "ORDER BY l.cancel_id, l.event_id"
            ).fetchall()
            risk_receipt_rows = self._conn.execute(
                "SELECT sequence, transition_kind, subject_id, receipt_id, "
                "previous_receipt_id, risk_counter_key, predecessor_counter_identity, "
                "projected_counter_identity, payload FROM risk_transition_receipts "
                "ORDER BY sequence"
            ).fetchall()
            risk_counter_rows = self._conn.execute(
                "SELECT counter_key, identity, payload FROM scoped_daily_risk_counters "
                "ORDER BY counter_key"
            ).fetchall()
            approval_receipt_rows = self._conn.execute(
                f"SELECT {self._approval_columns()} FROM approval_receipts "
                "ORDER BY plan_identity, session_date, receipt_id"
            ).fetchall()
        except sqlite3.Error:
            query_error = StoreError("RECOVERY_SNAPSHOT_READ_FAILED")
        if query_error is not None:
            raise query_error from None

        return RecoveryRows(
            commands=tuple(_row_to_stored(*row) for row in command_rows),
            events=tuple(_row_to_stored_event(row) for row in event_rows),
            order_aggregates=tuple(_row_to_stored_aggregate(row) for row in aggregate_rows),
            outbox_deliveries=tuple(
                _row_to_outbox_delivery(row) for row in delivery_rows
            ),
            ledger_entries=tuple(_row_to_stored(*row) for row in ledger_rows),
            ledger_contexts=tuple(_row_to_ledger_context(row) for row in context_rows),
            ledger_checkpoints=tuple(
                _row_to_ledger_checkpoint(row) for row in checkpoint_rows
            ),
            cancel_commands=tuple(
                _row_to_cancel_command(row) for row in cancel_rows
            ),
            cancel_deliveries=tuple(
                _row_to_cancel_delivery(row) for row in cancel_delivery_rows
            ),
            cancel_event_links=tuple(
                _row_to_cancel_event_link(row) for row in cancel_link_rows
            ),
            risk_transition_receipts=tuple(
                _row_to_risk_receipt(row) for row in risk_receipt_rows
            ),
            risk_counter_rows=tuple(
                _row_to_stored(*row) for row in risk_counter_rows
            ),
            approval_receipts=tuple(
                _row_to_stored_approval(row) for row in approval_receipt_rows
            ),
        )

    def put_reconciliation_run(
        self, *, run_id: str, identity: str, payload: bytes
    ) -> bool:
        """Persist a reconciliation run record."""
        return self._put_row(
            table="reconciliation_runs",
            key_column="run_id",
            key=_require_key("run_id", run_id),
            identity=_require_identity(identity),
            payload=_require_payload(payload),
            subject="reconciliation_run",
        )

    def get_reconciliation_run(self, run_id: str) -> StoredRecord | None:
        key = _require_key("run_id", run_id)
        row = self._conn.execute(
            "SELECT run_id, identity, payload FROM reconciliation_runs WHERE run_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_stored(row[0], row[1], row[2])


class ExecutionStore:
    """SQLite-backed durable store with explicit schema version and migrations."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        version: int,
        session_barrier: object | None = None,
        barrier_oms_handle: object | None = None,
    ) -> None:
        self._conn: sqlite3.Connection | None = conn
        self._version = version
        self._write_lock = threading.Lock()
        self._write_lock_owner: int | None = None
        self._session_barrier: object | None = None
        self._barrier_oms_handle: object | None = None
        if session_barrier is not None:
            try:
                self._session_barrier = unpack_session_barrier_capability(session_barrier)
                if barrier_oms_handle is None:
                    raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
                self._barrier_oms_handle = unpack_session_barrier_oms_handle(
                    barrier_oms_handle, capability=self._session_barrier
                )
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None

    @classmethod
    def open(
        cls,
        uri: str,
        *,
        trusted_root: Path,
        session_barrier: object | None = None,
        initialize_barrier: bool = False,
        barrier_created_at: dt.datetime | None = None,
    ) -> ExecutionStore:
        """Open (or create) the store under trusted_root, apply migrations.

        When ``session_barrier`` is omitted, behavior matches the pre-barrier
        non-formal store aside from schema v9 table presence.

        When ``session_barrier`` is provided, writers require an OPEN write lease.
        ``initialize_barrier=True`` may create the OPEN row only on an empty new
        root; old economic roots are refused (no adopt/backfill).
        """
        relative = _parse_sqlite_uri(uri)
        resolved_root = _validate_trusted_root(trusted_root)

        path_err: StoreError | None = None
        path: Path | None = None
        try:
            path = _materialize_db_path(resolved_root, relative)
        except StoreError:
            raise
        except OSError:
            path_err = StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
        if path_err is not None:
            raise path_err from None
        assert path is not None

        conn: sqlite3.Connection | None = None
        try:
            open_err: StoreError | None = None
            connected: sqlite3.Connection | None = None
            try:
                connected = sqlite3.connect(
                    str(path),
                    isolation_level=None,
                    check_same_thread=False,
                    timeout=0.0,
                )
            except sqlite3.Error:
                open_err = StoreError("OPEN_FAILED")
            if open_err is not None:
                raise open_err from None
            assert connected is not None
            conn = connected

            # Re-verify parent and leaf after connect; close on failure.
            post_err: StoreUriError | None = None
            try:
                parent = path.parent
                _check_existing_dir_component(parent, resolved_root)
                _check_leaf(path, resolved_root, must_exist=True)
            except StoreUriError as exc:
                post_err = StoreUriError(str(exc))
            except OSError:
                post_err = StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
            if post_err is not None:
                _safe_close(connected)
                conn = None
                raise post_err from None

            pragma_err: StoreError | None = None
            try:
                connected.execute("PRAGMA journal_mode = WAL")
                connected.execute("PRAGMA foreign_keys = ON")
            except sqlite3.Error:
                pragma_err = StoreError("PRAGMA_FAILED")
            if pragma_err is not None:
                raise pragma_err from None

            migration_err: StoreError | None = None
            try:
                connected.execute("BEGIN IMMEDIATE")
                version = _apply_migrations(connected)
                connected.execute("COMMIT")
            except StoreError:
                raise
            except sqlite3.Error:
                migration_err = StoreError("MIGRATION_FAILED")
            if migration_err is not None:
                _safe_rollback(connected)
                raise migration_err from None

            if session_barrier is not None:
                # Barrier init owns OS-lock → BEGIN → COMMIT → unlock (no nested lock).
                try:
                    _bind_session_barrier_on_open(
                        connected,
                        session_barrier,
                        initialize_barrier=initialize_barrier,
                        barrier_created_at=barrier_created_at,
                    )
                except SessionBarrierError as exc:
                    raise StoreError(str(exc)) from None
        except Exception:
            if conn is not None:
                _safe_rollback(conn)
                _safe_close(conn)
            raise

        assert conn is not None
        handle: object | None = None
        if session_barrier is not None:
            try:
                handle = issue_session_barrier_oms_handle(
                    capability=session_barrier, conn=conn
                )
            except SessionBarrierError as exc:
                _safe_close(conn)
                raise StoreError(str(exc)) from None
        return cls(
            conn,
            version=version,
            session_barrier=session_barrier,
            barrier_oms_handle=handle,
        )

    def schema_version(self) -> int:
        """Return the applied schema version."""
        return self._version

    def session_barrier_enabled(self) -> bool:
        """Return whether this store requires OPEN write leases."""
        return self._session_barrier is not None

    def session_barrier_oms_handle(self) -> object:
        """Return the process-local OMS barrier handle (no sqlite connection)."""
        if self._session_barrier is None or self._barrier_oms_handle is None:
            raise StoreError("BARRIER_MISSING")
        try:
            return unpack_session_barrier_oms_handle(
                self._barrier_oms_handle, capability=self._session_barrier
            )
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None

    def read_session_barrier_row(self) -> object:
        """Fresh-read the OMS barrier row (SSOT); available with or without binding."""
        if self._session_barrier is not None and self._barrier_oms_handle is not None:
            try:
                return fresh_read_session_barrier(
                    oms_handle=self._barrier_oms_handle,
                    capability=self._session_barrier,
                )
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None
        conn = self._conn
        if conn is None:
            raise StoreError("STORE_CLOSED")
        try:
            return read_session_barrier(conn)
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None

    def transition_session_barrier_to_closing(
        self,
        *,
        nonce: str,
        now: dt.datetime,
    ) -> tuple[object, str, object]:
        """OPEN → CLOSING; returns (row, token_identity, closure_capability).

        Closure is process-local and issue-only in B1B1 (no terminal writes).
        """
        conn = self._conn
        barrier = self._session_barrier
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            # transition_* owns OS lock → BEGIN → COMMIT → unlock.
            return transition_open_to_closing(conn, barrier, nonce=nonce, now=now)
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None
        finally:
            self._release_write_lock()

    def transition_session_barrier_to_closed(
        self,
        *,
        close_token_identity: str,
        now: dt.datetime,
    ) -> object:
        """CLOSING → CLOSED under the store's internal connection.

        Substrate ``SUBSTRATE_RAW_TOKEN`` barriers may close with the raw token.
        Formal ``FORMAL_CLOSURE_ONLY`` barriers reject this entry with
        ``BARRIER_CLOSURE_REQUIRED`` (surfaced as ``StoreError``).
        """
        conn = self._conn
        barrier = self._session_barrier
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            return transition_closing_to_closed(
                conn,
                barrier,
                close_token_identity=close_token_identity,
                now=now,
            )
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None
        finally:
            self._release_write_lock()

    def transition_session_barrier_to_closed_with_closure(
        self,
        *,
        closure: object,
        terminal_successor_identity: str,
        now: dt.datetime,
    ) -> object:
        """Formal CLOSING → CLOSED under an active ``closing_to_closed`` child.

        Reuses the terminal context's already-held anchored OS lock (no
        second lock acquisition); only ``FORMAL_CLOSURE_ONLY`` capabilities
        may use this entry. ``SUBSTRATE_RAW_TOKEN`` barriers reject with
        ``BARRIER_CLOSURE_REQUIRED`` inside the session-barrier module.
        """
        conn = self._conn
        barrier = self._session_barrier
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            return transition_closing_to_closed_with_closure(
                conn,
                barrier,
                closure=closure,
                terminal_successor_identity=terminal_successor_identity,
                now=now,
            )
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None
        finally:
            self._release_write_lock()

    @contextmanager
    def transaction_under_terminal_child(
        self,
        *,
        terminal_child: object,
        step_kind: str,
    ) -> Iterator[ExecutionRepository]:
        """OMS committing transaction under an exact ``oms_recovery`` terminal child.

        Reuses the already-held terminal anchored lock (physical lock depth stays
        exact one). Other terminal step kinds are refused: they must not receive
        a general writable OMS repository.
        """
        if step_kind != "oms_recovery":
            raise StoreError("BARRIER_TERMINAL_STEP_INVALID")
        conn = self._conn
        barrier = self._session_barrier
        handle = self._barrier_oms_handle
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None or handle is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            try:
                row = fresh_read_session_barrier(oms_handle=handle, capability=barrier)
                verify_terminal_child_against_row(
                    terminal_child, capability=barrier, row=row, step_kind="oms_recovery"
                )
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None
            begin_err: StoreError | None = None
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                    begin_err = StoreError("TX_BUSY")
                else:
                    begin_err = StoreError("TX_BEGIN_FAILED")
            if begin_err is not None:
                raise begin_err from None
            try:
                row = fresh_read_session_barrier(oms_handle=handle, capability=barrier)
                verify_terminal_child_against_row(
                    terminal_child, capability=barrier, row=row, step_kind="oms_recovery"
                )
            except SessionBarrierError as exc:
                _safe_rollback(conn)
                raise StoreError(str(exc)) from None
            repo = ExecutionRepository(conn)
            try:
                yield repo
            except Exception:
                _safe_rollback(conn)
                raise
            else:
                commit_err: StoreError | None = None
                try:
                    row = fresh_read_session_barrier(
                        oms_handle=handle, capability=barrier
                    )
                    verify_terminal_child_against_row(
                        terminal_child,
                        capability=barrier,
                        row=row,
                        step_kind="oms_recovery",
                    )
                    conn.execute("COMMIT")
                except SessionBarrierError as exc:
                    _safe_rollback(conn)
                    commit_err = StoreError(str(exc))
                except sqlite3.Error:
                    _safe_rollback(conn)
                    commit_err = StoreError("TX_COMMIT_FAILED")
                if commit_err is not None:
                    raise commit_err from None
        finally:
            self._release_write_lock()

    @contextmanager
    def inspect_repository_under_terminal_child(
        self,
        *,
        terminal_child: object,
        step_kind: str,
    ) -> Iterator[ExecutionRepository]:
        """Read-only OMS inspect under a live terminal child; always ROLLBACK.

        Never commits. Used by ``broker_finality`` (and similar) to obtain fresh
        recovery facts without exposing a writable repository.
        """
        conn = self._conn
        barrier = self._session_barrier
        handle = self._barrier_oms_handle
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None or handle is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            try:
                row = fresh_read_session_barrier(oms_handle=handle, capability=barrier)
                verify_terminal_child_against_row(
                    terminal_child, capability=barrier, row=row, step_kind=step_kind  # type: ignore[arg-type]
                )
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None
            begin_err: StoreError | None = None
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                    begin_err = StoreError("TX_BUSY")
                else:
                    begin_err = StoreError("TX_BEGIN_FAILED")
            if begin_err is not None:
                raise begin_err from None
            try:
                row = fresh_read_session_barrier(oms_handle=handle, capability=barrier)
                verify_terminal_child_against_row(
                    terminal_child, capability=barrier, row=row, step_kind=step_kind  # type: ignore[arg-type]
                )
                yield ExecutionRepository(conn)
            finally:
                _safe_rollback(conn)
        finally:
            self._release_write_lock()

    @contextmanager
    def inspect_repository_when_barrier_closed(self) -> Iterator[ExecutionRepository]:
        """Read-only OMS inspect after barrier is CLOSED; always ROLLBACK.

        Holds the anchored barrier lock, proves ``state=CLOSED``, then yields a
        repository that cannot commit. Used by formal CLOSED replay to fresh
        recompute the durable successor chain without writers.
        """
        conn = self._conn
        barrier = self._session_barrier
        handle = self._barrier_oms_handle
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if barrier is None or handle is None:
            raise StoreError("BARRIER_MISSING")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        try:
            try:
                with hold_session_barrier_lock(barrier) as held:
                    row = fresh_read_session_barrier(
                        oms_handle=handle, capability=barrier
                    )
                    if row.state != "CLOSED":
                        raise SessionBarrierError("BARRIER_TRANSITION_INVALID")
                    if row.lock_identity != held.lock_identity:
                        raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT")
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                    except sqlite3.Error as exc:
                        if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                            raise StoreError("TX_BUSY") from None
                        raise StoreError("TX_BEGIN_FAILED") from None
                    try:
                        row = fresh_read_session_barrier(
                            oms_handle=handle, capability=barrier
                        )
                        if row.state != "CLOSED":
                            raise SessionBarrierError("BARRIER_TRANSITION_INVALID")
                        yield ExecutionRepository(conn)
                    finally:
                        _safe_rollback(conn)
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None
        finally:
            self._release_write_lock()

    @contextmanager
    def open_operation_fence(self) -> Iterator[object | None]:
        """Hold one OPEN operation permit across claim → gateway → callback.

        Stores without a bound session barrier yield ``None`` (legacy no-op).
        Does not hold ``_write_lock`` for the fence lifetime; each inner
        ``transaction()`` still acquires it per TX and mints a child write lease
        that reuses the permit's anchored OS lock.

        Substrate raw-token barriers may still use
        ``transition_session_barrier_to_closed``; formal ``FORMAL_CLOSURE_ONLY``
        barriers reject that path with ``BARRIER_CLOSURE_REQUIRED``.
        """
        barrier = self._session_barrier
        handle = self._barrier_oms_handle
        if barrier is None:
            yield None
            return
        if handle is None:
            raise StoreError("BARRIER_OMS_HANDLE_INVALID")
        try:
            with hold_open_operation_permit(barrier, oms_handle=handle) as permit:
                yield permit
        except SessionBarrierError as exc:
            raise StoreError(str(exc)) from None

    @contextmanager
    def transaction(self) -> Iterator[ExecutionRepository]:
        """Begin an immediate write transaction; rollback on exception.

        Barrier-enabled stores acquire the anchored lock, mint an OPEN write
        lease, and re-verify lock/lease/state before commit.
        """
        conn = self._conn
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if not self._try_acquire_write_lock():
            raise StoreError("TX_BUSY")
        barrier = self._session_barrier
        handle = self._barrier_oms_handle
        try:
            if barrier is None:
                yield from self._transaction_unbounded(conn)
                return
            if handle is None:
                raise StoreError("BARRIER_OMS_HANDLE_INVALID")
            try:
                with hold_open_write_lease(
                    barrier, oms_handle=handle, store_kind="oms"
                ) as lease:
                    begin_err: StoreError | None = None
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                    except sqlite3.Error as exc:
                        if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                            begin_err = StoreError("TX_BUSY")
                        else:
                            begin_err = StoreError("TX_BEGIN_FAILED")
                    if begin_err is not None:
                        raise begin_err from None
                    try:
                        row = fresh_read_session_barrier(
                            oms_handle=handle, capability=barrier
                        )
                        verify_lease_against_row(
                            lease, capability=barrier, row=row, store_kind="oms"
                        )
                    except SessionBarrierError as exc:
                        _safe_rollback(conn)
                        raise StoreError(str(exc)) from None
                    repo = ExecutionRepository(conn)
                    try:
                        yield repo
                    except Exception:
                        _safe_rollback(conn)
                        invalidate_write_lease(lease)
                        raise
                    else:
                        commit_err: StoreError | None = None
                        try:
                            row = fresh_read_session_barrier(
                                oms_handle=handle, capability=barrier
                            )
                            verify_lease_against_row(
                                lease, capability=barrier, row=row, store_kind="oms"
                            )
                            conn.execute("COMMIT")
                        except SessionBarrierError as exc:
                            _safe_rollback(conn)
                            commit_err = StoreError(str(exc))
                        except sqlite3.Error:
                            _safe_rollback(conn)
                            commit_err = StoreError("TX_COMMIT_FAILED")
                        invalidate_write_lease(lease)
                        if commit_err is not None:
                            raise commit_err from None
            except SessionBarrierError as exc:
                raise StoreError(str(exc)) from None
        finally:
            self._release_write_lock()

    def _transaction_unbounded(
        self, conn: sqlite3.Connection
    ) -> Iterator[ExecutionRepository]:
        begin_err: StoreError | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                begin_err = StoreError("TX_BUSY")
            else:
                begin_err = StoreError("TX_BEGIN_FAILED")
        if begin_err is not None:
            raise begin_err from None
        repo = ExecutionRepository(conn)
        try:
            yield repo
        except Exception:
            _safe_rollback(conn)
            raise
        else:
            commit_err: StoreError | None = None
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                _safe_rollback(conn)
                commit_err = StoreError("TX_COMMIT_FAILED")
            if commit_err is not None:
                raise commit_err from None

    def _try_acquire_write_lock(self) -> bool:
        if not self._write_lock.acquire(blocking=False):
            return False
        self._write_lock_owner = threading.get_ident()
        return True

    def _release_write_lock(self) -> None:
        self._write_lock_owner = None
        self._write_lock.release()

    def close(self) -> None:
        """Close the underlying connection; serialize with active writers.

        Same-thread close while this thread owns an active write lock fails
        immediately (non-reentrant Lock cannot be re-acquired). Cross-thread
        close waits for the owner to finish commit/rollback and release the
        OS lease, then invalidates the handle and closes the connection.
        """
        owner = self._write_lock_owner
        if owner is not None and owner == threading.get_ident():
            raise StoreError("CLOSE_DURING_TX") from None
        self._write_lock.acquire(blocking=True)
        try:
            # Re-check after acquire: owner should be clear once we hold the lock.
            self._write_lock_owner = threading.get_ident()
            if self._barrier_oms_handle is not None:
                invalidate_session_barrier_oms_handle(self._barrier_oms_handle)
                self._barrier_oms_handle = None
            conn = self._conn
            if conn is not None:
                close_err: StoreError | None = None
                try:
                    conn.close()
                except sqlite3.Error:
                    close_err = StoreError("CLOSE_FAILED")
                finally:
                    self._conn = None
                if close_err is not None:
                    raise close_err from None
        finally:
            self._write_lock_owner = None
            self._write_lock.release()


def _bind_session_barrier_on_open(
    conn: sqlite3.Connection,
    session_barrier: object,
    *,
    initialize_barrier: bool,
    barrier_created_at: dt.datetime | None,
) -> None:
    capability = unpack_session_barrier_capability(session_barrier)
    try:
        require_matching_barrier(conn, capability)
        return
    except SessionBarrierError as exc:
        if exc.code != "BARRIER_MISSING":
            raise
    if not initialize_barrier:
        raise SessionBarrierError("BARRIER_MISSING")
    if barrier_created_at is None:
        raise SessionBarrierError("BARRIER_TIME_INVALID")
    initialize_open_barrier(conn, capability, created_at=barrier_created_at)


__all__ = [
    "CancelOutboxDelivery",
    "CURRENT_SCHEMA_VERSION",
    "LEDGER_CHECKPOINT_KEY",
    "ExecutionRepository",
    "ExecutionStore",
    "IdempotencyConflict",
    "MigrationInterruptedError",
    "OutboxDelivery",
    "OutboxDeliveryState",
    "RecoveryRows",
    "StoreError",
    "StoreUriError",
    "StoredDailyRiskCounters",
    "StoredEventRecord",
    "StoredCancelCommand",
    "StoredCancelEventLink",
    "StoredApprovalReceipt",
    "StoredLedgerCheckpoint",
    "StoredRecord",
    "StoredRiskTransitionReceipt",
    "UnknownSchemaVersionError",
]
