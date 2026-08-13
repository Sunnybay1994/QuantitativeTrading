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

from quant.execution.migrations import MIGRATIONS
from quant.execution.risk import (
    DailyRiskCounters,
    build_daily_risk_counters_identity,
    deserialize_daily_risk_counters,
    serialize_daily_risk_counters,
)

CURRENT_SCHEMA_VERSION: Final[int] = 4

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

    def __init__(self, conn: sqlite3.Connection, *, version: int) -> None:
        self._conn: sqlite3.Connection | None = conn
        self._version = version
        self._write_lock = threading.Lock()

    @classmethod
    def open(cls, uri: str, *, trusted_root: Path) -> ExecutionStore:
        """Open (or create) the store under trusted_root, apply migrations."""
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
                raise migration_err from None
        except Exception:
            if conn is not None:
                _safe_rollback(conn)
                _safe_close(conn)
            raise

        assert conn is not None
        return cls(conn, version=version)

    def schema_version(self) -> int:
        """Return the applied schema version."""
        return self._version

    @contextmanager
    def transaction(self) -> Iterator[ExecutionRepository]:
        """Begin an immediate write transaction; rollback on exception."""
        conn = self._conn
        if conn is None:
            raise StoreError("STORE_CLOSED")
        if not self._write_lock.acquire(blocking=False):
            raise StoreError("TX_BUSY")
        begin_err: StoreError | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                begin_err = StoreError("TX_BUSY")
            else:
                begin_err = StoreError("TX_BEGIN_FAILED")
        if begin_err is not None:
            self._write_lock.release()
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
        finally:
            self._write_lock.release()

    def close(self) -> None:
        """Close the underlying connection."""
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


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ExecutionRepository",
    "ExecutionStore",
    "IdempotencyConflict",
    "MigrationInterruptedError",
    "OutboxDelivery",
    "OutboxDeliveryState",
    "StoreError",
    "StoreUriError",
    "StoredDailyRiskCounters",
    "StoredRecord",
    "UnknownSchemaVersionError",
]
