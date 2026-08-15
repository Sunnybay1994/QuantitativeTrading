"""Independent, durable state store for the local PAPER broker adapter."""

from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import sys
import weakref
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Literal, cast

from quant.backtest.costs import ExecutionCostSchedule
from quant.backtest.fx import FxSnapshot, build_fx_snapshot
from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.domain.enums import Currency, ExecutionEventType, Market, OrderSide, OrderStatus
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    ExecutionEvent,
    OrderCommand,
    PositionBalance,
    build_account_snapshot,
    build_account_snapshot_identity,
    build_money_amount,
)
from quant.execution.gateways.contracts import DispatchCertainty
from quant.execution.reconcile import BrokerOrderObservation
from quant.execution.paper_broker_binding import VerifiedFormalPaperBrokerPolicyBinding
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.wire import (
    decode_cancel_command,
    decode_execution_event,
    decode_order_command,
    encode_execution_event,
    encode_order_command,
)

_ACCOUNT_SCHEMA = "paper-account-v1"
_POLICY_SCHEMA = "paper-broker-policy-v1"
_STORE_SCHEMA = "paper-broker-store-v1"
_LABEL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
_HEX = frozenset("0123456789abcdef")
_FORBIDDEN_PARTS = frozenset({"data", "legacy", "candidates", "releases", "journal", "evidence", "anchor"})


class PaperBrokerStoreError(ValueError):
    """Stable, sanitized durable broker failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    @property
    def __context__(self) -> None:
        """Never expose an implementation exception through the public error."""
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class PaperAccountDescriptor:
    schema_version: str
    account_id: str
    account_label: str
    created_at: dt.datetime
    base_currency: Currency
    initial_snapshot: AccountSnapshot
    initial_snapshot_identity: str
    descriptor_identity: str


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PaperBrokerPolicyDescriptor:
    schema_version: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    cost_schedule_identity: str
    fx_snapshot_identity: str | None
    classification: Literal["development", "formal-paper-simulation"]
    descriptor_identity: str


@dataclass(frozen=True, slots=True)
class PaperBrokerStoreDescriptor:
    schema_version: str
    resolved_root: str
    root_device: int
    root_inode: int
    database_filename: str
    database_device: int
    database_inode: int
    account_id: str
    policy_identity: str
    created_at: dt.datetime
    instance_nonce: str
    descriptor_identity: str


@dataclass(frozen=True, slots=True)
class RetainedOperation:
    operation_id: str
    kind: Literal["SUBMIT", "CANCEL"]
    dispatch_attempt: int
    request_digest: str
    certainty: DispatchCertainty
    result_payload: bytes


@dataclass(frozen=True, slots=True)
class PaperSessionFinality:
    """Exact durable EOD marker for one explicitly named broker session."""

    schema_version: Literal[
        "paper-session-finality-v1",
        "paper-zero-broker-command-session-finality-v1",
    ]
    session_date: dt.date
    finalized_at: dt.datetime
    order_semantic_closure_identity: str | None


def build_paper_account_descriptor(
    *, account_label: str, created_at: dt.datetime, base_currency: Currency,
    initial_snapshot: AccountSnapshot,
) -> PaperAccountDescriptor:
    """Build a stable account identity distinct from daily snapshot identity."""
    try:
        if not _token(account_label) or type(base_currency) is not Currency or not _utc(created_at):
            raise ValueError
        snapshot_id = build_account_snapshot_identity(initial_snapshot)
        wire = _account_wire(initial_snapshot)
        body = {
            "account_label": account_label,
            "base_currency": base_currency.value,
            "created_at": utc_datetime_text(created_at),
            "initial_snapshot": json.loads(wire),
            "initial_snapshot_identity": snapshot_id,
            "schema_version": _ACCOUNT_SCHEMA,
        }
        account_id = _digest({"type": "PaperAccount", **body})
        identity = _digest({"account_id": account_id, **body})
        return PaperAccountDescriptor(
            _ACCOUNT_SCHEMA, account_id, account_label, created_at, base_currency,
            initial_snapshot, snapshot_id, identity,
        )
    except PaperBrokerStoreError:
        raise
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_ACCOUNT_INVALID") from None


def build_paper_broker_policy_descriptor(
    *, adapter_policy_version: str, fill_policy_version: str,
    fault_policy_version: str, finality_policy_version: str,
    cost_schedule: ExecutionCostSchedule, fx_snapshot: FxSnapshot | None,
) -> PaperBrokerPolicyDescriptor:
    """Bind deterministic adapter inputs without freezing business values here."""
    try:
        versions = (adapter_policy_version, fill_policy_version, fault_policy_version, finality_policy_version)
        if any(not _token(item) for item in versions):
            raise ValueError
        if type(cost_schedule) is not ExecutionCostSchedule:
            raise ValueError
        cost_identity = _digest(_cost_payload(cost_schedule))
        fx_identity: str | None = None
        if fx_snapshot is not None:
            if type(fx_snapshot) is not FxSnapshot:
                raise ValueError
            rebuilt = build_fx_snapshot(
                selector=fx_snapshot.selector, session_date=fx_snapshot.session_date,
                observed_at=fx_snapshot.observed_at, expires_at=fx_snapshot.expires_at,
                rates=fx_snapshot.rates,
            )
            if rebuilt != fx_snapshot:
                raise ValueError
            fx_identity = rebuilt.snapshot_id
        body = {
            "adapter_policy_version": adapter_policy_version,
            "classification": "development",
            "cost_schedule_identity": cost_identity,
            "fault_policy_version": fault_policy_version,
            "fill_policy_version": fill_policy_version,
            "finality_policy_version": finality_policy_version,
            "fx_snapshot_identity": fx_identity,
            "schema_version": _POLICY_SCHEMA,
        }
        return PaperBrokerPolicyDescriptor(
            _POLICY_SCHEMA, adapter_policy_version, fill_policy_version,
            fault_policy_version, finality_policy_version, cost_identity,
            fx_identity, "development", _digest(body),
        )
    except PaperBrokerStoreError:
        raise
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_POLICY_INVALID") from None


def _initialize_formal_policy_descriptor_api() -> tuple[Any, Any]:
    issued: dict[int, weakref.ReferenceType[PaperBrokerPolicyDescriptor]] = {}

    def remember(value: PaperBrokerPolicyDescriptor) -> None:
        key = id(value)

        def discard(reference: weakref.ReferenceType[PaperBrokerPolicyDescriptor]) -> None:
            if issued.get(key) is reference:
                issued.pop(key, None)

        issued[key] = weakref.ref(value, discard)

    def build(
        *,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
    ) -> PaperBrokerPolicyDescriptor:
        """Build the B1 descriptor from one exact formal policy/binding pair."""
        try:
            if (
                type(policy) is not VerifiedPaperExecutionPolicy
                or type(binding) is not VerifiedFormalPaperBrokerPolicyBinding
                or binding.classification != "formal-paper-simulation"
                or binding.session_date != policy.session_date
                or binding.execution_policy_identity != policy.policy_identity
                or binding.adapter_policy_version != policy.adapter_policy_version
                or binding.fill_policy_version != policy.fill_policy_version
                or binding.fault_policy_version != policy.fault_policy_version
                or binding.finality_policy_version != policy.finality_policy_version
                or binding.clock_policy_version != policy.clock_policy_version
                or binding.cost_schedule_identity != policy.cost_schedule_identity
                or binding.fx_snapshot_identity != policy.fx_snapshot_identity
                or _digest(_cost_payload(policy.execution_cost_schedule))
                != policy.cost_schedule_identity
            ):
                raise ValueError
            body = {
                "adapter_policy_version": policy.adapter_policy_version,
                "classification": "formal-paper-simulation",
                "cost_schedule_identity": policy.cost_schedule_identity,
                "fault_policy_version": policy.fault_policy_version,
                "fill_policy_version": policy.fill_policy_version,
                "finality_policy_version": policy.finality_policy_version,
                "fx_snapshot_identity": policy.fx_snapshot_identity,
                "schema_version": _POLICY_SCHEMA,
            }
            result = PaperBrokerPolicyDescriptor(
                _POLICY_SCHEMA,
                policy.adapter_policy_version,
                policy.fill_policy_version,
                policy.fault_policy_version,
                policy.finality_policy_version,
                policy.cost_schedule_identity,
                policy.fx_snapshot_identity,
                "formal-paper-simulation",
                _digest(body),
            )
            remember(result)
            return result
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_POLICY_INVALID") from None

    def is_issued(value: PaperBrokerPolicyDescriptor) -> bool:
        reference = issued.get(id(value))
        return reference is not None and reference() is value

    return build, is_issued


(
    build_formal_paper_broker_policy_descriptor,
    _is_issued_formal_policy_descriptor,
) = _initialize_formal_policy_descriptor_api()
del _initialize_formal_policy_descriptor_api


class PaperBrokerStore:
    """Verified SQLite broker instance; never reads an OMS store."""

    def __init__(self, root: Path, database_filename: str, *, timeout: float = 0.0) -> None:
        self._root = root
        self._database_filename = database_filename
        self._db_path = root / database_filename
        self._descriptor_path = root / "store-instance.json"
        self._account_path = root / "initial-account.json"
        self._anchor_root = root / "sequence-anchors"
        self._timeout = timeout
        self._closed = False
        self.descriptor = self._load_descriptor()
        self.account_descriptor = self._load_account_descriptor()
        self._verify_files()
        self._guard_handles = tuple(
            _guard_open(path, directory=directory)
            for path, directory in (
                (self._root, True),
                (self._db_path, False),
                (self._descriptor_path, False),
                (self._account_path, False),
                (self._anchor_root, True),
            )
        )
        self._guarded_anchor_names: set[str] = set()

    @property
    def gateway_identity(self) -> str:
        self.verify_fresh()
        return _digest({
            "account_id": self.descriptor.account_id,
            "policy_identity": self.descriptor.policy_identity,
            "store_identity": self.descriptor.descriptor_identity,
            "type": "DurablePaperGateway",
        })

    def close(self) -> None:
        """Release physical instance anchors; transaction connections are scoped."""
        handles = getattr(self, "_guard_handles", ())
        self._guard_handles = ()
        self._closed = True
        failed = False
        for handle in handles:
            try:
                _guard_close(handle)
            except BaseException:
                failed = True
        if failed:
            raise PaperBrokerStoreError("PAPER_BROKER_CLOSE_FAILED")

    def __del__(self) -> None:
        """Best-effort teardown that never reaches ``sys.unraisablehook``."""
        try:
            handles = getattr(self, "_guard_handles", ())
            self._guard_handles = ()
            self._closed = True
            for handle in handles:
                try:
                    _guard_close(handle)
                except BaseException:
                    pass
        except BaseException:
            pass

    def verify_fresh(self) -> None:
        if self._closed:
            raise PaperBrokerStoreError("PAPER_BROKER_STORE_CLOSED")
        try:
            current = self._load_descriptor()
            if current != self.descriptor:
                raise ValueError
            self._verify_files()
            account = self._load_account_descriptor()
            if account != self.account_descriptor:
                raise ValueError
            with self._connect() as conn:
                self._verify_database(conn)
            self._sync_anchors()
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_IDENTITY_DRIFT") from None

    def retained_operation(self, operation_id: str) -> RetainedOperation | None:
        self.verify_fresh()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT kind, attempt, request_digest, certainty, result_payload "
                    "FROM operations WHERE operation_id=?", (operation_id,),
                ).fetchone()
            if row is None:
                return None
            return RetainedOperation(operation_id, cast(Any, row[0]), int(row[1]), str(row[2]), DispatchCertainty(row[3]), bytes(row[4]))
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_READ_FAILED") from None

    def all_commands(self) -> tuple[Any, ...]:
        """Return fresh-decoded broker-owned commands for deterministic recovery."""
        self.verify_fresh()
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT payload FROM commands ORDER BY command_id").fetchall()
            return tuple(decode_order_command(bytes(row[0])) for row in rows)
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_READ_FAILED") from None

    @property
    def policy_identity(self) -> str:
        return self.descriptor.policy_identity

    @property
    def source_identity(self) -> str:
        self.verify_fresh()
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT sequence,head_hash FROM checkpoint WHERE singleton=1").fetchone()
            if row is None:
                raise ValueError
            return _digest({
                "head_hash": str(row[1]), "sequence": int(row[0]),
                "store_identity": self.descriptor.descriptor_identity,
            })
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def persist_operation(
        self, *, operation_id: str, kind: Literal["SUBMIT", "CANCEL"],
        dispatch_attempt: int, request_payload: bytes, certainty: DispatchCertainty,
        result_payload: bytes, command_payload: bytes,
        callbacks: tuple[ExecutionEvent, ...], account: AccountSnapshot,
        predecessor_state_digest: str,
    ) -> None:
        """Atomically retain operation, callback/state and journal checkpoint."""
        self._verify_files()
        request_digest = hashlib.sha256(request_payload).hexdigest()
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._verify_database(conn)
                checkpoint = conn.execute(
                    "SELECT state_digest FROM checkpoint WHERE singleton=1"
                ).fetchone()
                if (
                    checkpoint is None
                    or str(checkpoint[0]) != predecessor_state_digest
                ):
                    raise PaperBrokerStoreError("PAPER_BROKER_PREDECESSOR_STALE")
                prior = conn.execute(
                    "SELECT attempt, request_digest FROM operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if prior is not None:
                    if int(prior[0]) == dispatch_attempt and str(prior[1]) == request_digest:
                        conn.rollback()
                        return
                    raise PaperBrokerStoreError("PAPER_BROKER_OPERATION_CONFLICT")
                command = decode_order_command(command_payload)
                finalized = conn.execute(
                    "SELECT 1 FROM session_finality WHERE session_date=?",
                    (command.intent.session_date.isoformat(),),
                ).fetchone()
                if finalized is not None:
                    raise PaperBrokerStoreError("PAPER_BROKER_SESSION_FINAL")
                conn.execute(
                    "INSERT OR IGNORE INTO commands(command_id,payload) VALUES(?,?)",
                    (command.command_id, command_payload),
                )
                retained_command = conn.execute(
                    "SELECT payload FROM commands WHERE command_id=?", (command.command_id,),
                ).fetchone()
                if retained_command is None or bytes(retained_command[0]) != command_payload:
                    raise PaperBrokerStoreError("PAPER_BROKER_OPERATION_CONFLICT")
                conn.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,?,?)",
                    (operation_id, kind, dispatch_attempt, request_digest, request_payload, certainty.value, result_payload),
                )
                for ordinal, event in enumerate(callbacks):
                    event_payload = encode_execution_event(event)
                    conn.execute(
                        "INSERT OR IGNORE INTO events(event_id,command_id,payload) VALUES(?,?,?)",
                        (event.event_id, command.command_id, event_payload),
                    )
                    existing = conn.execute("SELECT payload FROM events WHERE event_id=?", (event.event_id,)).fetchone()
                    if existing is None or bytes(existing[0]) != event_payload:
                        raise PaperBrokerStoreError("PAPER_BROKER_EVENT_CONFLICT")
                    conn.execute(
                        "INSERT INTO operation_events(operation_id,ordinal,event_id) VALUES(?,?,?)",
                        (operation_id, ordinal, event.event_id),
                    )
                observations = _rebuild_observations(conn)
                conn.execute("DELETE FROM order_state")
                conn.executemany(
                    "INSERT INTO order_state(broker_order_id,payload) VALUES(?,?)",
                    tuple(
                        (item.broker_order_id, _observation_wire(item))
                        for item in observations
                    ),
                )
                conn.execute("UPDATE account_state SET payload=? WHERE singleton=1", (_account_wire(account),))
                self._append_journal(conn, kind=kind, subject=operation_id, payload=result_payload)
                conn.commit()
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise PaperBrokerStoreError("PAPER_BROKER_BUSY") from None
                raise PaperBrokerStoreError("PAPER_BROKER_WRITE_FAILED") from None
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self.verify_fresh()
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_WRITE_FAILED") from None

    def read_state(self) -> tuple[AccountSnapshot, tuple[BrokerOrderObservation, ...], tuple[ExecutionEvent, ...], dt.datetime]:
        """Fresh rebuild all evidence in one consistent read transaction."""
        self.verify_fresh()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN")
                self._verify_database(conn)
                account_row = conn.execute("SELECT payload FROM account_state WHERE singleton=1").fetchone()
                command_rows = conn.execute("SELECT command_id,payload FROM commands ORDER BY command_id").fetchall()
                event_rows = conn.execute("SELECT event_id,command_id,payload FROM events ORDER BY event_id").fetchall()
                order_rows = conn.execute(
                    "SELECT payload FROM order_state ORDER BY broker_order_id"
                ).fetchall()
                operation_rows = conn.execute("SELECT result_payload FROM operations").fetchall()
                conn.commit()
            if account_row is None:
                raise ValueError
            account = _decode_account(bytes(account_row[0]))
            commands = {str(row[0]): decode_order_command(bytes(row[1])) for row in command_rows}
            events = tuple(decode_execution_event(bytes(row[2]), command=commands[str(row[1])]) for row in event_rows)
            orders = tuple(_decode_observation(bytes(row[0])) for row in order_rows)
            as_of = max((account.as_of, *(event.occurred_at for event in events)))
            del operation_rows
            return account, orders, events, as_of
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def read_predecessor(
        self,
    ) -> tuple[AccountSnapshot, str]:
        """Read the account and its strict CAS predecessor in one snapshot."""
        self.verify_fresh()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN")
                account_row = conn.execute(
                    "SELECT payload FROM account_state WHERE singleton=1"
                ).fetchone()
                checkpoint = conn.execute(
                    "SELECT state_digest FROM checkpoint WHERE singleton=1"
                ).fetchone()
                conn.commit()
            if account_row is None or checkpoint is None:
                raise ValueError
            return _decode_account(bytes(account_row[0])), str(checkpoint[0])
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def read_evidence_snapshot(
        self,
        *,
        session_date: dt.date | None = None,
    ) -> tuple[
        AccountSnapshot,
        tuple[BrokerOrderObservation, ...],
        tuple[ExecutionEvent, ...],
        dt.datetime,
        str,
        Literal["INTRADAY", "END_OF_DAY"],
    ]:
        """Rebuild broker evidence, optionally bound to one exact session."""
        self.verify_fresh()
        try:
            if session_date is not None and type(session_date) is not dt.date:
                raise ValueError
            finality_marker: PaperSessionFinality | None = None
            with self._connect() as conn:
                conn.execute("BEGIN")
                self._verify_database(conn)
                account_row = conn.execute(
                    "SELECT payload FROM account_state WHERE singleton=1"
                ).fetchone()
                command_rows = conn.execute(
                    "SELECT command_id,payload FROM commands ORDER BY command_id"
                ).fetchall()
                event_rows = conn.execute(
                    "SELECT event_id,command_id,payload FROM events ORDER BY event_id"
                ).fetchall()
                order_rows = conn.execute(
                    "SELECT payload FROM order_state ORDER BY broker_order_id"
                ).fetchall()
                checkpoint = conn.execute(
                    "SELECT sequence,head_hash FROM checkpoint WHERE singleton=1"
                ).fetchone()
                commands = {
                    str(row[0]): decode_order_command(bytes(row[1]))
                    for row in command_rows
                }
                selected_session = session_date
                if selected_session is None and commands:
                    selected_session = max(
                        item.intent.session_date for item in commands.values()
                    )
                finality_row = (
                    None
                    if selected_session is None
                    else conn.execute(
                        "SELECT payload FROM session_finality WHERE session_date=?",
                        (selected_session.isoformat(),),
                    ).fetchone()
                )
                if finality_row is not None:
                    finality_marker = _decode_finality_payload(
                        bytes(finality_row[0])
                    )
                    if finality_marker.session_date != selected_session:
                        raise ValueError
                conn.commit()
            if account_row is None or checkpoint is None:
                raise ValueError
            account = _decode_account(bytes(account_row[0]))
            events = tuple(
                decode_execution_event(
                    bytes(row[2]), command=commands[str(row[1])]
                )
                for row in event_rows
            )
            orders = tuple(_decode_observation(bytes(row[0])) for row in order_rows)
            as_of = max((account.as_of, *(event.occurred_at for event in events)))
            source_identity = _digest(
                {
                    "head_hash": str(checkpoint[1]),
                    "sequence": int(checkpoint[0]),
                    "store_identity": self.descriptor.descriptor_identity,
                }
            )
            finality: Literal["INTRADAY", "END_OF_DAY"] = (
                "END_OF_DAY" if finality_row is not None else "INTRADAY"
            )
            return account, orders, events, as_of, source_identity, finality
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def read_session_finality(
        self, *, session_date: dt.date
    ) -> PaperSessionFinality | None:
        """Read one exact durable finality marker without inferring a latest day."""
        self.verify_fresh()
        try:
            if type(session_date) is not dt.date:
                raise ValueError
            with self._connect() as conn:
                self._verify_database(conn)
                row = conn.execute(
                    "SELECT payload FROM session_finality WHERE session_date=?",
                    (session_date.isoformat(),),
                ).fetchone()
            if row is None:
                return None
            result = _decode_finality_payload(bytes(row[0]))
            if result.session_date != session_date:
                raise ValueError
            return result
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def record_zero_broker_command_session_finality(
        self,
        *,
        session_date: dt.date,
        finalized_at: dt.datetime,
        order_semantic_closure_identity: str,
    ) -> None:
        """Append a low-level marker; this primitive proves no human authorization."""
        if (
            type(session_date) is not dt.date
            or not _utc(finalized_at)
            or type(order_semantic_closure_identity) is not str
            or len(order_semantic_closure_identity) != 64
            or not set(order_semantic_closure_identity) <= _HEX
        ):
            raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_INVALID")
        payload = canonical_json_bytes(
            {
                "finalized_at": utc_datetime_text(finalized_at),
                "order_semantic_closure_identity": order_semantic_closure_identity,
                "schema_version": "paper-zero-broker-command-session-finality-v1",
                "session_date": session_date.isoformat(),
            }
        )
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._verify_database(conn)
                existing = conn.execute(
                    "SELECT payload FROM session_finality WHERE session_date=?",
                    (session_date.isoformat(),),
                ).fetchone()
                if existing is not None:
                    if bytes(existing[0]) == payload:
                        conn.rollback()
                        return
                    raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_CONFLICT")
                command_rows = conn.execute(
                    "SELECT payload FROM commands ORDER BY command_id"
                ).fetchall()
                if any(
                    decode_order_command(bytes(row[0])).intent.session_date
                    == session_date
                    for row in command_rows
                ):
                    raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_INVALID")
                conn.execute(
                    "INSERT INTO session_finality(session_date,payload) VALUES(?,?)",
                    (session_date.isoformat(), payload),
                )
                self._append_journal(
                    conn,
                    kind="SESSION_FINALITY",
                    subject=session_date.isoformat(),
                    payload=payload,
                )
                conn.commit()
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise PaperBrokerStoreError("PAPER_BROKER_BUSY") from None
                raise PaperBrokerStoreError("PAPER_BROKER_WRITE_FAILED") from None
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self.verify_fresh()
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_INVALID") from None

    def finalize_session(self, *, session_date: dt.date, finalized_at: dt.datetime) -> None:
        """Append one EOD checkpoint only after the session is demonstrably terminal."""
        if type(session_date) is not dt.date or not _utc(finalized_at):
            raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_INVALID")
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._verify_database(conn)
                existing = conn.execute(
                    "SELECT payload FROM session_finality WHERE session_date=?",
                    (session_date.isoformat(),),
                ).fetchone()
                payload = canonical_json_bytes({
                    "finalized_at": utc_datetime_text(finalized_at),
                    "schema_version": "paper-session-finality-v1",
                    "session_date": session_date.isoformat(),
                })
                if existing is not None:
                    if bytes(existing[0]) == payload:
                        conn.rollback()
                        return
                    raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_CONFLICT")
                if not _session_is_terminal(conn, session_date=session_date, finalized_at=finalized_at):
                    raise PaperBrokerStoreError("PAPER_BROKER_SESSION_NOT_FINAL")
                conn.execute(
                    "INSERT INTO session_finality(session_date,payload) VALUES(?,?)",
                    (session_date.isoformat(), payload),
                )
                self._append_journal(
                    conn, kind="SESSION_FINALITY", subject=session_date.isoformat(), payload=payload
                )
                conn.commit()
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise PaperBrokerStoreError("PAPER_BROKER_BUSY") from None
                raise PaperBrokerStoreError("PAPER_BROKER_WRITE_FAILED") from None
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self.verify_fresh()
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_FINALITY_INVALID") from None

    def evidence_finality(self) -> Literal["INTRADAY", "END_OF_DAY"]:
        """Return EOD only for the latest known command session checkpoint."""
        self.verify_fresh()
        try:
            commands = self.all_commands()
            if not commands:
                return "INTRADAY"
            latest = max(command.intent.session_date for command in commands)
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM session_finality WHERE session_date=?",
                    (latest.isoformat(),),
                ).fetchone()
            return "END_OF_DAY" if row is not None else "INTRADAY"
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID") from None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=self._timeout, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _sync_anchors(self) -> None:
        """Verify acknowledged anchors and recover only committed trailing anchors."""
        try:
            if _is_link_or_reparse(self._anchor_root):
                raise ValueError
            with self._connect() as conn:
                checkpoint = conn.execute(
                    "SELECT sequence,anchored_sequence FROM checkpoint WHERE singleton=1"
                ).fetchone()
                rows = conn.execute(
                    "SELECT seq,kind,subject,state_digest,entry_hash "
                    "FROM journal ORDER BY seq"
                ).fetchall()
            if checkpoint is None or int(checkpoint[0]) != len(rows):
                raise ValueError
            anchored = int(checkpoint[1])
            names = sorted(path.name for path in self._anchor_root.iterdir())
            expected_names = [f"{sequence:020d}.json" for sequence in range(1, len(rows) + 1)]
            if any(
                not name.endswith(".json")
                or len(name) != 25
                or not name[:20].isdigit()
                for name in names
            ) or names != expected_names[: len(names)]:
                raise ValueError
            if len(names) < anchored:
                raise ValueError
            predecessor_digest = "0" * 64
            for sequence, row in enumerate(rows, 1):
                seq, kind, subject, state_digest, entry_hash = row
                if int(seq) != sequence:
                    raise ValueError
                payload = canonical_json_bytes(
                    {
                        "entry_hash": str(entry_hash),
                        "kind": str(kind),
                        "predecessor_anchor_digest": predecessor_digest,
                        "schema_version": "paper-broker-sequence-anchor-v1",
                        "sequence": sequence,
                        "state_digest": str(state_digest),
                        "store_identity": self.descriptor.descriptor_identity,
                        "subject": str(subject),
                    }
                )
                path = self._anchor_root / f"{sequence:020d}.json"
                if path.exists():
                    if _is_link_or_reparse(path) or path.read_bytes() != payload:
                        raise ValueError
                else:
                    if sequence <= anchored or sequence != len(names) + 1:
                        raise ValueError
                    _exclusive_write(path, payload)
                    names.append(path.name)
                    _fsync_directory(self._anchor_root)
                if path.name not in self._guarded_anchor_names:
                    self._guard_handles += (_guard_open(path, directory=False),)
                    self._guarded_anchor_names.add(path.name)
                predecessor_digest = hashlib.sha256(payload).hexdigest()
            if anchored != len(rows):
                conn = self._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    current = conn.execute(
                        "SELECT sequence,anchored_sequence FROM checkpoint WHERE singleton=1"
                    ).fetchone()
                    if current is None or (int(current[0]), int(current[1])) != (
                        len(rows),
                        anchored,
                    ):
                        raise PaperBrokerStoreError("PAPER_BROKER_ANCHOR_RETRY")
                    conn.execute(
                        "UPDATE checkpoint SET anchored_sequence=? "
                        "WHERE singleton=1 AND anchored_sequence=?",
                        (len(rows), anchored),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        except PaperBrokerStoreError:
            raise
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_ANCHOR_INVALID") from None

    def _verify_files(self) -> None:
        root_stat = self._root.stat()
        db_stat = self._db_path.stat()
        if (
            str(self._root.resolve(strict=True)) != self.descriptor.resolved_root
            or (root_stat.st_dev, root_stat.st_ino) != (self.descriptor.root_device, self.descriptor.root_inode)
            or (db_stat.st_dev, db_stat.st_ino) != (self.descriptor.database_device, self.descriptor.database_inode)
            or _is_link_or_reparse(self._root) or _is_link_or_reparse(self._db_path)
            or _is_link_or_reparse(self._anchor_root)
        ):
            raise PaperBrokerStoreError("PAPER_BROKER_IDENTITY_DRIFT")

    def _load_descriptor(self) -> PaperBrokerStoreDescriptor:
        try:
            raw = self._descriptor_path.read_bytes()
            value = _exact_json(raw, {
                "account_id", "created_at", "database_device", "database_filename",
                "database_inode", "descriptor_identity", "instance_nonce", "policy_identity",
                "resolved_root", "root_device", "root_inode", "schema_version",
            })
            body = {key: value[key] for key in value if key != "descriptor_identity"}
            if canonical_json_bytes(value) != raw or value["schema_version"] != _STORE_SCHEMA or _digest(body) != value["descriptor_identity"]:
                raise ValueError
            return PaperBrokerStoreDescriptor(
                _STORE_SCHEMA, str(value["resolved_root"]), int(value["root_device"]), int(value["root_inode"]),
                str(value["database_filename"]), int(value["database_device"]), int(value["database_inode"]),
                str(value["account_id"]), str(value["policy_identity"]), _parse_utc(value["created_at"]),
                str(value["instance_nonce"]), str(value["descriptor_identity"]),
            )
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_DESCRIPTOR_INVALID") from None

    def _load_account_descriptor(self) -> PaperAccountDescriptor:
        try:
            raw = self._account_path.read_bytes()
            value = _exact_json(raw, {
                "account_id", "account_label", "base_currency", "created_at", "descriptor_identity",
                "initial_snapshot", "initial_snapshot_identity", "schema_version",
            })
            snapshot = _decode_account(canonical_json_bytes(value["initial_snapshot"]))
            result = build_paper_account_descriptor(
                account_label=str(value["account_label"]), created_at=_parse_utc(value["created_at"]),
                base_currency=Currency(value["base_currency"]), initial_snapshot=snapshot,
            )
            if canonical_json_bytes(value) != raw or result.account_id != value["account_id"] or result.descriptor_identity != value["descriptor_identity"]:
                raise ValueError
            return result
        except Exception:
            raise PaperBrokerStoreError("PAPER_BROKER_ACCOUNT_INVALID") from None

    def _verify_database(self, conn: sqlite3.Connection) -> None:
        meta = conn.execute("SELECT value FROM metadata WHERE key='store_descriptor_identity'").fetchone()
        if meta is None or str(meta[0]) != self.descriptor.descriptor_identity:
            raise PaperBrokerStoreError("PAPER_BROKER_DATABASE_INVALID")
        retained_files = dict(
            conn.execute(
                "SELECT key,value FROM metadata WHERE key IN "
                "('descriptor_device','descriptor_inode','account_device','account_inode',"
                "'anchor_device','anchor_inode')"
            ).fetchall()
        )
        descriptor_stat = self._descriptor_path.stat()
        account_stat = self._account_path.stat()
        anchor_stat = self._anchor_root.stat()
        if retained_files != {
            "descriptor_device": str(descriptor_stat.st_dev),
            "descriptor_inode": str(descriptor_stat.st_ino),
            "account_device": str(account_stat.st_dev),
            "account_inode": str(account_stat.st_ino),
            "anchor_device": str(anchor_stat.st_dev),
            "anchor_inode": str(anchor_stat.st_ino),
        }:
            raise PaperBrokerStoreError("PAPER_BROKER_IDENTITY_DRIFT")
        rows = conn.execute("SELECT seq,kind,subject,payload_digest,state_digest,prev_hash,entry_hash FROM journal ORDER BY seq").fetchall()
        operations = conn.execute(
            "SELECT operation_id,kind,attempt,request_digest,request_payload,certainty,result_payload FROM operations ORDER BY rowid"
        ).fetchall()
        operation_map = {str(row[0]): row for row in operations}
        finality_rows = dict(conn.execute("SELECT session_date,payload FROM session_finality").fetchall())
        seen_operations: set[str] = set()
        seen_finality: set[str] = set()
        if len(rows) != len(operations) + len(finality_rows):
            raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
        previous = "0" * 64
        for expected, row in enumerate(rows, 1):
            seq, kind, subject, payload_digest, state_digest, prev_hash, entry_hash = row
            calculated = _digest({"kind": kind, "payload_digest": payload_digest, "state_digest": state_digest, "prev_hash": previous, "seq": expected, "subject": subject})
            if int(seq) != expected or prev_hash != previous or entry_hash != calculated:
                raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
            if kind in {"SUBMIT", "CANCEL"}:
                operation = operation_map.get(str(subject))
                if operation is None or str(subject) in seen_operations:
                    raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
                operation_id, operation_kind, attempt, request_digest, request_payload, certainty, result_payload = operation
                if (
                    kind != operation_kind
                    or payload_digest != hashlib.sha256(bytes(result_payload)).hexdigest()
                    or request_digest != hashlib.sha256(bytes(request_payload)).hexdigest()
                    or type(attempt) is not int or attempt <= 0
                    or certainty not in {item.value for item in DispatchCertainty}
                ):
                    raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
                _verify_operation_closure(
                    conn, operation_id=str(operation_id), kind=str(operation_kind),
                    request_payload=bytes(request_payload), result_payload=bytes(result_payload),
                    certainty=str(certainty),
                )
                seen_operations.add(str(subject))
            elif kind == "SESSION_FINALITY":
                payload = finality_rows.get(str(subject))
                if payload is None or str(subject) in seen_finality or payload_digest != hashlib.sha256(bytes(payload)).hexdigest():
                    raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
                _verify_finality_payload(bytes(payload), str(subject))
                seen_finality.add(str(subject))
            else:
                raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
            previous = str(entry_hash)
        if seen_operations != set(operation_map) or seen_finality != set(finality_rows):
            raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
        checkpoint = conn.execute("SELECT sequence,head_hash,state_digest,anchored_sequence FROM checkpoint WHERE singleton=1").fetchone()
        if (
            checkpoint is None
            or (int(checkpoint[0]), str(checkpoint[1]), str(checkpoint[2]))
            != (len(rows), previous, _state_digest(conn))
            or not 0 <= int(checkpoint[3]) <= len(rows)
        ):
            raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
        _verify_replayed_state(conn, self.account_descriptor.initial_snapshot)

    @staticmethod
    def _append_journal(conn: sqlite3.Connection, *, kind: str, subject: str, payload: bytes) -> None:
        row = conn.execute("SELECT sequence,head_hash FROM checkpoint WHERE singleton=1").fetchone()
        if row is None:
            raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")
        sequence = int(row[0]) + 1
        previous = str(row[1])
        payload_digest = hashlib.sha256(payload).hexdigest()
        state_digest = _state_digest(conn)
        entry_hash = _digest({"kind": kind, "payload_digest": payload_digest, "state_digest": state_digest, "prev_hash": previous, "seq": sequence, "subject": subject})
        conn.execute("INSERT INTO journal VALUES(?,?,?,?,?,?,?)", (sequence, kind, subject, payload_digest, state_digest, previous, entry_hash))
        conn.execute(
            "UPDATE checkpoint SET sequence=?,head_hash=?,state_digest=? WHERE singleton=1",
            (sequence, entry_hash, state_digest),
        )


def initialize_paper_broker_store(
    *, root: Path, database_filename: str, oms_store_path: Path,
    account: PaperAccountDescriptor, policy: PaperBrokerPolicyDescriptor,
    created_at: dt.datetime,
) -> PaperBrokerStore:
    """Exclusively initialize a caller-owned, independent broker root."""
    created: dict[Path, tuple[int, int, int]] = {}
    store: PaperBrokerStore | None = None
    try:
        resolved = _trusted_root(root)
        oms = oms_store_path.resolve(strict=False)
        if not oms.is_absolute() or _related(resolved, oms):
            raise ValueError
        if not _relative_filename(database_filename) or not _utc(created_at):
            raise ValueError
        _prove_account(account)
        _prove_policy(policy)
        db_path = resolved / database_filename
        sidecars = (resolved / f"{database_filename}-wal", resolved / f"{database_filename}-shm")
        descriptor_path = resolved / "store-instance.json"
        account_path = resolved / "initial-account.json"
        anchor_root = resolved / "sequence-anchors"
        if any(path.exists() for path in (db_path, *sidecars, descriptor_path, account_path, anchor_root)):
            raise PaperBrokerStoreError("PAPER_BROKER_ALREADY_EXISTS")
        anchor_root.mkdir(mode=0o700)
        created[anchor_root] = _object_identity(anchor_root)
        account_bytes = _account_descriptor_wire(account)
        _exclusive_write(account_path, account_bytes)
        created[account_path] = _object_identity(account_path)
        database_fd = os.open(
            db_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        os.close(database_fd)
        created[db_path] = _object_identity(db_path)
        conn = sqlite3.connect(db_path, isolation_level=None)
        try:
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()
        root_stat, db_stat = resolved.stat(), db_path.stat()
        body: dict[str, object] = {
            "account_id": account.account_id,
            "created_at": utc_datetime_text(created_at),
            "database_device": db_stat.st_dev,
            "database_filename": database_filename,
            "database_inode": db_stat.st_ino,
            "instance_nonce": secrets.token_hex(32),
            "policy_identity": policy.descriptor_identity,
            "resolved_root": str(resolved),
            "root_device": root_stat.st_dev,
            "root_inode": root_stat.st_ino,
            "schema_version": _STORE_SCHEMA,
        }
        descriptor_bytes = canonical_json_bytes({**body, "descriptor_identity": _digest(body)})
        _exclusive_write(descriptor_path, descriptor_bytes)
        created[descriptor_path] = _object_identity(descriptor_path)
        descriptor_identity = cast(str, json.loads(descriptor_bytes)["descriptor_identity"])
        conn = sqlite3.connect(db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO metadata VALUES('store_descriptor_identity',?)", (descriptor_identity,))
            conn.execute("INSERT INTO metadata VALUES('policy_identity',?)", (policy.descriptor_identity,))
            descriptor_stat = descriptor_path.stat()
            account_stat = account_path.stat()
            anchor_stat = anchor_root.stat()
            conn.executemany(
                "INSERT INTO metadata VALUES(?,?)",
                (
                    ("descriptor_device", str(descriptor_stat.st_dev)),
                    ("descriptor_inode", str(descriptor_stat.st_ino)),
                    ("account_device", str(account_stat.st_dev)),
                    ("account_inode", str(account_stat.st_ino)),
                    ("anchor_device", str(anchor_stat.st_dev)),
                    ("anchor_inode", str(anchor_stat.st_ino)),
                ),
            )
            conn.execute("INSERT INTO account_state VALUES(1,?)", (_account_wire(account.initial_snapshot),))
            conn.execute("INSERT INTO checkpoint VALUES(1,0,?,?,0)", ("0" * 64, _state_digest(conn)))
            conn.commit()
        finally:
            conn.close()
        store = PaperBrokerStore(resolved, database_filename)
        return store
    except PaperBrokerStoreError as exc:
        if created and not _rollback_initialization(root, created, store):
            raise PaperBrokerStoreError("PAPER_BROKER_ROLLBACK_REQUIRED") from None
        raise exc from None
    except Exception:
        if created and not _rollback_initialization(root, created, store):
            raise PaperBrokerStoreError("PAPER_BROKER_ROLLBACK_REQUIRED") from None
        raise PaperBrokerStoreError("PAPER_BROKER_INITIALIZE_FAILED") from None


def open_verified_paper_broker_store(
    *, root: Path, database_filename: str, oms_store_path: Path,
) -> PaperBrokerStore:
    """Fresh-open an existing broker instance under its original physical root."""
    try:
        resolved = _trusted_root(root)
        if _related(resolved, oms_store_path.resolve(strict=False)):
            raise ValueError
        if not _relative_filename(database_filename):
            raise ValueError
        store = PaperBrokerStore(resolved, database_filename)
        store.verify_fresh()
        return store
    except PaperBrokerStoreError:
        raise
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_OPEN_FAILED") from None


def _account_wire(value: AccountSnapshot) -> bytes:
    build_account_snapshot_identity(value)
    return canonical_json_bytes({
        "as_of": utc_datetime_text(value.as_of),
        "cash": [{"available": str(item.available), "currency": item.currency.value, "payable": str(item.payable), "receivable": str(item.receivable), "settled": str(item.settled)} for item in value.cash],
        "positions": [{"avg_cost": str(item.avg_cost.amount), "currency": item.avg_cost.currency.value, "market": item.market.value, "quantity": item.quantity, "sellable_quantity": item.sellable_quantity, "symbol": item.symbol} for item in value.positions],
        "schema_version": "paper-account-snapshot-v1", "snapshot_id": value.snapshot_id,
    })


def _decode_account(payload: bytes) -> AccountSnapshot:
    value = _exact_json(payload, {"as_of", "cash", "positions", "schema_version", "snapshot_id"})
    if value["schema_version"] != "paper-account-snapshot-v1" or type(value["cash"]) is not list or type(value["positions"]) is not list:
        raise ValueError
    cash = tuple(CashBalance(Currency(item["currency"]), Decimal(item["settled"]), Decimal(item["available"]), Decimal(item["receivable"]), Decimal(item["payable"])) for item in value["cash"])
    positions = tuple(PositionBalance(str(item["symbol"]), Market(item["market"]), int(item["quantity"]), int(item["sellable_quantity"]), build_money_amount(Currency(item["currency"]), Decimal(item["avg_cost"]))) for item in value["positions"])
    snapshot = build_account_snapshot(as_of=_parse_utc(value["as_of"]), positions=positions, cash=cash)
    if snapshot.snapshot_id != value["snapshot_id"] or _account_wire(snapshot) != payload:
        raise ValueError
    return snapshot


def _account_descriptor_wire(value: PaperAccountDescriptor) -> bytes:
    return canonical_json_bytes({
        "account_id": value.account_id, "account_label": value.account_label,
        "base_currency": value.base_currency.value, "created_at": utc_datetime_text(value.created_at),
        "descriptor_identity": value.descriptor_identity,
        "initial_snapshot": json.loads(_account_wire(value.initial_snapshot)),
        "initial_snapshot_identity": value.initial_snapshot_identity, "schema_version": value.schema_version,
    })


def _prove_account(value: PaperAccountDescriptor) -> None:
    if type(value) is not PaperAccountDescriptor or build_paper_account_descriptor(
        account_label=value.account_label, created_at=value.created_at,
        base_currency=value.base_currency, initial_snapshot=value.initial_snapshot,
    ) != value:
        raise PaperBrokerStoreError("PAPER_BROKER_ACCOUNT_INVALID")


def _prove_policy(value: PaperBrokerPolicyDescriptor) -> None:
    if type(value) is not PaperBrokerPolicyDescriptor:
        raise PaperBrokerStoreError("PAPER_BROKER_POLICY_INVALID")
    body = {
        "adapter_policy_version": value.adapter_policy_version, "classification": value.classification,
        "cost_schedule_identity": value.cost_schedule_identity, "fault_policy_version": value.fault_policy_version,
        "fill_policy_version": value.fill_policy_version, "finality_policy_version": value.finality_policy_version,
        "fx_snapshot_identity": value.fx_snapshot_identity, "schema_version": value.schema_version,
    }
    if (
        value.schema_version != _POLICY_SCHEMA
        or value.classification not in {"development", "formal-paper-simulation"}
        or _digest(body) != value.descriptor_identity
        or (
            value.classification == "formal-paper-simulation"
            and not _is_issued_formal_policy_descriptor(value)
        )
    ):
        raise PaperBrokerStoreError("PAPER_BROKER_POLICY_INVALID")


def _object_identity(path: Path) -> tuple[int, int, int]:
    status = path.lstat()
    return status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode)


def _rollback_initialization(
    root: Path,
    created: Mapping[Path, tuple[int, int, int]],
    store: PaperBrokerStore | None,
) -> bool:
    """Remove only exact objects created by this initializer."""
    try:
        if store is not None:
            store.close()
        resolved = root.resolve(strict=True)
        allowed = {path.name for path in created}
        allowed.update(
            f"{path.name}{suffix}"
            for path in created
            if path.suffix in {".sqlite", ".sqlite3", ".db"}
            for suffix in ("-wal", "-shm")
        )
        if any(path.name not in allowed for path in resolved.iterdir()):
            return False
        for path, identity in created.items():
            if not path.exists() or _object_identity(path) != identity:
                return False
        for path in tuple(resolved.iterdir()):
            if path.name.endswith(("-wal", "-shm")):
                if not path.is_file() or _is_link_or_reparse(path):
                    return False
                path.unlink()
        for path in sorted(created, key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        return True
    except BaseException:
        return False


def _rollback_fresh_store(store: PaperBrokerStore) -> bool:
    """Compensate a just-created, still-empty store by exact retained identity."""
    try:
        if type(store) is not PaperBrokerStore:
            return False
        store.verify_fresh()
        root = store._root
        expected = {
            store._db_path,
            store._descriptor_path,
            store._account_path,
            store._anchor_root,
        }
        identities = {path: _object_identity(path) for path in expected}
        if any(path not in expected for path in root.iterdir()):
            return False
        store.close()
        if any(_object_identity(path) != identity for path, identity in identities.items()):
            return False
        for path in sorted(expected, key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        return True
    except BaseException:
        return False


def _observation(broker_id: str, events: list[ExecutionEvent]) -> BrokerOrderObservation:
    ordered = sorted({event.event_id: event for event in events}.values(), key=lambda item: item.occurred_at)
    last = ordered[-1]
    mapping = {
        "ACCEPTED": OrderStatus.SUBMITTED, "PARTIAL_FILL": OrderStatus.PARTIAL_FILLED,
        "FILL": OrderStatus.FILLED, "REJECTED": OrderStatus.REJECTED,
        "CANCEL_ACCEPTED": OrderStatus.CANCELLING, "CANCELLED": OrderStatus.CANCELLED,
    }
    return BrokerOrderObservation(broker_id, last.command_id, mapping[last.event_type.value], last.cumulative_quantity, tuple(sorted(event.event_id for event in ordered)))


def apply_broker_callbacks(
    account: AccountSnapshot,
    command: OrderCommand,
    events: tuple[ExecutionEvent, ...],
) -> AccountSnapshot:
    """Replay unique economic callbacks from one journal transition."""
    positions = {(item.market, item.symbol): item for item in account.positions}
    cash = {item.currency: item for item in account.cash}
    as_of = account.as_of
    for event in events:
        as_of = max(as_of, event.occurred_at)
        if event.event_type not in {
            ExecutionEventType.FILL,
            ExecutionEventType.PARTIAL_FILL,
        }:
            continue
        if event.last_price is None or event.last_quantity <= 0:
            raise PaperBrokerStoreError("PAPER_BROKER_STATE_INVALID")
        intent = command.intent
        quote = intent.quote_currency
        current_cash = cash.get(
            quote,
            CashBalance(quote, Decimal(0), Decimal(0), Decimal(0), Decimal(0)),
        )
        fees = sum(
            (
                fee.amount.amount
                for fee in event.fees
                if fee.amount.currency is quote
            ),
            Decimal(0),
        )
        notional = event.last_price * event.last_quantity
        key = (intent.market, intent.symbol)
        current_position = positions.get(key)
        if intent.side is OrderSide.BUY:
            debit = notional + fees
            if current_cash.settled < debit or current_cash.available < debit:
                raise PaperBrokerStoreError("PAPER_BROKER_CASH_INSUFFICIENT")
            old_quantity = 0 if current_position is None else current_position.quantity
            old_value = (
                Decimal(0)
                if current_position is None
                else current_position.avg_cost.amount * old_quantity
            )
            quantity = old_quantity + event.last_quantity
            positions[key] = PositionBalance(
                intent.symbol,
                intent.market,
                quantity,
                0 if current_position is None else current_position.sellable_quantity,
                build_money_amount(
                    quote, (old_value + notional + fees) / quantity
                ),
            )
            cash[quote] = CashBalance(
                quote,
                current_cash.settled - debit,
                current_cash.available - debit,
                current_cash.receivable,
                current_cash.payable,
            )
        else:
            if (
                current_position is None
                or current_position.quantity < event.last_quantity
                or current_position.sellable_quantity < event.last_quantity
            ):
                raise PaperBrokerStoreError("PAPER_BROKER_POSITION_INSUFFICIENT")
            quantity = current_position.quantity - event.last_quantity
            if quantity:
                positions[key] = PositionBalance(
                    intent.symbol,
                    intent.market,
                    quantity,
                    current_position.sellable_quantity - event.last_quantity,
                    current_position.avg_cost,
                )
            else:
                positions.pop(key)
            credit = notional - fees
            cash[quote] = CashBalance(
                quote,
                current_cash.settled + credit,
                current_cash.available + credit,
                current_cash.receivable,
                current_cash.payable,
            )
    return build_account_snapshot(
        as_of=as_of,
        positions=tuple(positions.values()),
        cash=tuple(cash.values()),
    )


def _cost_payload(value: ExecutionCostSchedule) -> dict[str, object]:
    return {"periods": [{"commission_min": str(item.commission_min), "commission_rate": str(item.commission_rate), "effective_from": item.effective_from.isoformat(), "effective_to": None if item.effective_to is None else item.effective_to.isoformat(), "market": item.market.value, "settlement_currency": item.settlement_currency.value, "stamp_tax_sell": str(item.stamp_tax_sell), "transfer_fee": str(item.transfer_fee)} for item in value.periods], "selector": value.selector, "type": "ExecutionCostSchedule"}


def _trusted_root(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir() or _is_link_or_reparse(root):
        raise ValueError
    resolved = root.resolve(strict=True)
    if any(part.lower() in _FORBIDDEN_PARTS for part in resolved.parts):
        raise ValueError
    return resolved


def _is_link_or_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
        return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)
    except OSError:
        return True


def _related(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _relative_filename(value: object) -> bool:
    return type(value) is str and value not in {"", ".", ".."} and Path(value).name == value and not Path(value).is_absolute()


def _token(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= 128 and all(char in _LABEL for char in value)


def _utc(value: object) -> bool:
    return type(value) is dt.datetime and value.tzinfo is not None and value.utcoffset() == dt.timedelta(0)


def _parse_utc(value: object) -> dt.datetime:
    if type(value) is not str:
        raise ValueError
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not _utc(result):
        raise ValueError
    return result


def _exact_json(payload: bytes, keys: set[str]) -> dict[str, Any]:
    value = json.loads(payload)
    if type(value) is not dict or set(value) != keys or canonical_json_bytes(value) != payload:
        raise ValueError
    return cast(dict[str, Any], value)


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _exclusive_write(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    if sys.platform == "win32":
        return
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _guard_open(path: Path, *, directory: bool) -> tuple[str, int]:
    """Keep a no-follow identity anchor; Windows denies delete sharing."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        create_file = getattr(ctypes, "WinDLL")(
            "kernel32", use_last_error=True
        ).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3,
            0x02000000 if directory else 0, None,
        )
        numeric = int(handle)
        if numeric == cast(int, ctypes.c_void_p(-1).value):
            raise PaperBrokerStoreError("PAPER_BROKER_IDENTITY_DRIFT")
        return "windows", numeric
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return "posix", os.open(path, flags)


def _guard_close(handle: tuple[str, int]) -> None:
    kind, value = handle
    if kind == "windows":
        import ctypes
        from ctypes import wintypes

        close_handle = getattr(ctypes, "WinDLL")(
            "kernel32", use_last_error=True
        ).CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        if not close_handle(wintypes.HANDLE(value)):
            raise OSError("PAPER_BROKER_CLOSE_FAILED")
    else:
        os.close(value)


def _state_digest(conn: sqlite3.Connection) -> str:
    """Bind every mutable state row into the retained checkpoint."""
    tables = {
        "account_state": conn.execute("SELECT singleton,payload FROM account_state ORDER BY singleton").fetchall(),
        "commands": conn.execute("SELECT command_id,payload FROM commands ORDER BY command_id").fetchall(),
        "events": conn.execute("SELECT event_id,command_id,payload FROM events ORDER BY event_id").fetchall(),
        "operation_events": conn.execute("SELECT operation_id,ordinal,event_id FROM operation_events ORDER BY operation_id,ordinal").fetchall(),
        "operations": conn.execute("SELECT operation_id,kind,attempt,request_digest,request_payload,certainty,result_payload FROM operations ORDER BY rowid").fetchall(),
        "order_state": conn.execute("SELECT broker_order_id,payload FROM order_state ORDER BY broker_order_id").fetchall(),
        "session_finality": conn.execute("SELECT session_date,payload FROM session_finality ORDER BY session_date").fetchall(),
    }
    payload: dict[str, object] = {}
    for table, rows in tables.items():
        payload[table] = [
            [hashlib.sha256(bytes(value)).hexdigest() if isinstance(value, bytes) else value for value in row]
            for row in rows
        ]
    return _digest(payload)


def _verify_operation_closure(
    conn: sqlite3.Connection, *, operation_id: str, kind: str,
    request_payload: bytes, result_payload: bytes, certainty: str,
) -> None:
    try:
        if kind == "SUBMIT":
            command = decode_order_command(request_payload)
            expected_schema = "paper-submit-result-v1"
            expected_id_key = "command_id"
            if command.command_id != operation_id:
                raise ValueError
        elif kind == "CANCEL":
            cancel = decode_cancel_command(request_payload)
            expected_schema = "paper-cancel-result-v1"
            expected_id_key = "cancel_id"
            if cancel.cancel_id != operation_id:
                raise ValueError
            command_row = conn.execute("SELECT payload FROM commands WHERE command_id=?", (cancel.command_id,)).fetchone()
            if command_row is None:
                raise ValueError
            command = decode_order_command(bytes(command_row[0]))
        else:
            raise ValueError
        retained_command = conn.execute("SELECT payload FROM commands WHERE command_id=?", (command.command_id,)).fetchone()
        if retained_command is None or bytes(retained_command[0]) != encode_order_command(command):
            raise ValueError
        result = json.loads(result_payload)
        expected_keys = {"callbacks", "certainty", expected_id_key, "dispatch_attempt", "schema_version"}
        if (
            type(result) is not dict or set(result) != expected_keys
            or canonical_json_bytes(result) != result_payload
            or result["schema_version"] != expected_schema
            or result[expected_id_key] != operation_id
            or result["certainty"] != certainty
            or type(result["callbacks"]) is not list
        ):
            raise ValueError
        links = conn.execute(
            "SELECT ordinal,event_id FROM operation_events WHERE operation_id=? ORDER BY ordinal",
            (operation_id,),
        ).fetchall()
        if len(links) != len(result["callbacks"]):
            raise ValueError
        for ordinal, (link, token) in enumerate(zip(links, result["callbacks"], strict=True)):
            event_payload = base64.b64decode(token, validate=True)
            event = decode_execution_event(event_payload, command=command)
            if int(link[0]) != ordinal or str(link[1]) != event.event_id:
                raise ValueError
            event_row = conn.execute("SELECT payload FROM events WHERE event_id=?", (event.event_id,)).fetchone()
            if event_row is None or bytes(event_row[0]) != event_payload:
                raise ValueError
        if certainty != DispatchCertainty.SENT.value and links:
            raise ValueError
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID") from None


def _decode_finality_payload(payload: bytes) -> PaperSessionFinality:
    try:
        raw = json.loads(payload)
        if type(raw) is not dict:
            raise ValueError
        schema = raw.get("schema_version")
        closure_identity: str | None = None
        if schema == "paper-session-finality-v1":
            value = _exact_json(
                payload, {"finalized_at", "schema_version", "session_date"}
            )
        elif schema == "paper-zero-broker-command-session-finality-v1":
            value = _exact_json(
                payload,
                {
                    "finalized_at",
                    "order_semantic_closure_identity",
                    "schema_version",
                    "session_date",
                },
            )
            raw_closure_identity = value["order_semantic_closure_identity"]
            if type(raw_closure_identity) is not str:
                raise ValueError
            closure_identity = raw_closure_identity
            if len(closure_identity) != 64 or not set(closure_identity) <= _HEX:
                raise ValueError
        else:
            raise ValueError
        session_date = dt.date.fromisoformat(str(value["session_date"]))
        finalized_at = _parse_utc(value["finalized_at"])
        return PaperSessionFinality(
            schema_version=cast(
                Literal[
                    "paper-session-finality-v1",
                    "paper-zero-broker-command-session-finality-v1",
                ],
                schema,
            ),
            session_date=session_date,
            finalized_at=finalized_at,
            order_semantic_closure_identity=closure_identity,
        )
    except PaperBrokerStoreError:
        raise
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID") from None


def _verify_finality_payload(payload: bytes, session_text: str) -> None:
    value = _decode_finality_payload(payload)
    if value.session_date.isoformat() != session_text:
        raise PaperBrokerStoreError("PAPER_BROKER_JOURNAL_INVALID")


def _observation_wire(value: BrokerOrderObservation) -> bytes:
    return canonical_json_bytes(
        {
            "broker_order_id": value.broker_order_id,
            "command_id": value.command_id,
            "cumulative_quantity": value.cumulative_quantity,
            "observed_event_ids": list(value.observed_event_ids),
            "schema_version": "paper-broker-order-v1",
            "status": value.status.value,
        }
    )


def _decode_observation(payload: bytes) -> BrokerOrderObservation:
    value = _exact_json(
        payload,
        {
            "broker_order_id",
            "command_id",
            "cumulative_quantity",
            "observed_event_ids",
            "schema_version",
            "status",
        },
    )
    if (
        value["schema_version"] != "paper-broker-order-v1"
        or type(value["observed_event_ids"]) is not list
    ):
        raise ValueError
    result = BrokerOrderObservation(
        broker_order_id=str(value["broker_order_id"]),
        command_id=(
            None if value["command_id"] is None else str(value["command_id"])
        ),
        status=OrderStatus(value["status"]),
        cumulative_quantity=int(value["cumulative_quantity"]),
        observed_event_ids=tuple(str(item) for item in value["observed_event_ids"]),
    )
    if _observation_wire(result) != payload:
        raise ValueError
    return result


def _rebuild_observations(
    conn: sqlite3.Connection,
) -> tuple[BrokerOrderObservation, ...]:
    commands = {
        str(row[0]): decode_order_command(bytes(row[1]))
        for row in conn.execute("SELECT command_id,payload FROM commands").fetchall()
    }
    grouped: dict[str, list[ExecutionEvent]] = {}
    for command_id, payload in conn.execute(
        "SELECT command_id,payload FROM events"
    ).fetchall():
        event = decode_execution_event(
            bytes(payload), command=commands[str(command_id)]
        )
        if event.broker_order_id is not None:
            grouped.setdefault(event.broker_order_id, []).append(event)
    return tuple(
        _observation(broker_id, values)
        for broker_id, values in sorted(grouped.items())
    )


def _verify_replayed_state(
    conn: sqlite3.Connection, initial: AccountSnapshot
) -> None:
    try:
        account = initial
        globally_seen: set[str] = set()
        rows = conn.execute(
            "SELECT kind,subject FROM journal ORDER BY seq"
        ).fetchall()
        for kind, subject in rows:
            if kind == "SESSION_FINALITY":
                continue
            operation = conn.execute(
                "SELECT request_payload FROM operations WHERE operation_id=?",
                (subject,),
            ).fetchone()
            if operation is None:
                raise ValueError
            if kind == "SUBMIT":
                command = decode_order_command(bytes(operation[0]))
            elif kind == "CANCEL":
                cancel = decode_cancel_command(bytes(operation[0]))
                command_row = conn.execute(
                    "SELECT payload FROM commands WHERE command_id=?",
                    (cancel.command_id,),
                ).fetchone()
                if command_row is None:
                    raise ValueError
                command = decode_order_command(bytes(command_row[0]))
            else:
                raise ValueError
            callbacks: list[ExecutionEvent] = []
            local_seen: set[str] = set()
            for event_id, payload in conn.execute(
                "SELECT oe.event_id,e.payload FROM operation_events AS oe "
                "JOIN events AS e ON e.event_id=oe.event_id "
                "WHERE oe.operation_id=? ORDER BY oe.ordinal",
                (subject,),
            ).fetchall():
                event = decode_execution_event(bytes(payload), command=command)
                if event.event_id != event_id:
                    raise ValueError
                if event.event_id in globally_seen and event.event_id not in local_seen:
                    raise ValueError
                if event.event_id not in local_seen:
                    callbacks.append(event)
                    local_seen.add(event.event_id)
                    globally_seen.add(event.event_id)
            account = apply_broker_callbacks(account, command, tuple(callbacks))
        account_row = conn.execute(
            "SELECT payload FROM account_state WHERE singleton=1"
        ).fetchone()
        if account_row is None or _account_wire(account) != bytes(account_row[0]):
            raise ValueError
        retained_orders = tuple(
            _decode_observation(bytes(row[0]))
            for row in conn.execute(
                "SELECT payload FROM order_state ORDER BY broker_order_id"
            ).fetchall()
        )
        if retained_orders != _rebuild_observations(conn):
            raise ValueError
    except PaperBrokerStoreError:
        raise
    except Exception:
        raise PaperBrokerStoreError("PAPER_BROKER_REPLAY_INVALID") from None


def _session_is_terminal(
    conn: sqlite3.Connection, *, session_date: dt.date, finalized_at: dt.datetime
) -> bool:
    try:
        command_rows = conn.execute("SELECT command_id,payload FROM commands").fetchall()
        commands = {
            str(row[0]): decode_order_command(bytes(row[1]))
            for row in command_rows
            if decode_order_command(bytes(row[1])).intent.session_date == session_date
        }
        if not commands:
            return False
        related_operations = 0
        for kind, request_payload, certainty in conn.execute(
            "SELECT kind,request_payload,certainty FROM operations"
        ).fetchall():
            command_id: str
            if kind == "SUBMIT":
                command_id = decode_order_command(bytes(request_payload)).command_id
            elif kind == "CANCEL":
                command_id = decode_cancel_command(bytes(request_payload)).command_id
            else:
                return False
            if command_id in commands:
                related_operations += 1
                if certainty == DispatchCertainty.UNKNOWN.value:
                    return False
        if related_operations < len(commands):
            return False
        grouped: dict[str, list[ExecutionEvent]] = {}
        for command_id, payload in conn.execute(
            "SELECT command_id,payload FROM events"
        ).fetchall():
            if str(command_id) not in commands:
                continue
            event = decode_execution_event(
                bytes(payload), command=commands[str(command_id)]
            )
            if event.occurred_at > finalized_at or event.broker_order_id is None:
                return False
            grouped.setdefault(event.broker_order_id, []).append(event)
        observations = tuple(
            _observation(broker_id, values) for broker_id, values in grouped.items()
        )
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        return (
            len(observations) == len(commands)
            and {item.command_id for item in observations} == set(commands)
            and all(item.status in terminal for item in observations)
        )
    except Exception:
        return False


_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE commands(command_id TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE operations(operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, attempt INTEGER NOT NULL, request_digest TEXT NOT NULL, request_payload BLOB NOT NULL, certainty TEXT NOT NULL, result_payload BLOB NOT NULL);
CREATE TABLE events(event_id TEXT PRIMARY KEY, command_id TEXT NOT NULL REFERENCES commands(command_id), payload BLOB NOT NULL);
CREATE TABLE operation_events(operation_id TEXT NOT NULL REFERENCES operations(operation_id), ordinal INTEGER NOT NULL, event_id TEXT NOT NULL REFERENCES events(event_id), PRIMARY KEY(operation_id,ordinal));
CREATE TABLE order_state(broker_order_id TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE account_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload BLOB NOT NULL);
CREATE TABLE session_finality(session_date TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE journal(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, payload_digest TEXT NOT NULL, state_digest TEXT NOT NULL, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
CREATE TABLE checkpoint(singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL, head_hash TEXT NOT NULL, state_digest TEXT NOT NULL, anchored_sequence INTEGER NOT NULL);
"""


__all__ = [
    "PaperAccountDescriptor", "PaperBrokerPolicyDescriptor", "PaperBrokerStore",
    "PaperBrokerStoreDescriptor", "PaperBrokerStoreError", "RetainedOperation",
    "build_formal_paper_broker_policy_descriptor", "build_paper_account_descriptor",
    "build_paper_broker_policy_descriptor",
    "initialize_paper_broker_store", "open_verified_paper_broker_store",
]
