"""Converge the two historical risk-counter schemas after M4 version 6."""

from __future__ import annotations

import sqlite3


_TYPED_COUNTER_COLUMNS = (
    "session_date",
    "identity",
    "payload",
    "updated_at",
)
_SCOPED_COUNTER_COLUMNS = ("counter_key", "identity", "payload")


def _columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...] | None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None:
        return None
    return tuple(
        str(column[1]) for column in conn.execute(f'PRAGMA table_info("{table}")')
    )


def _create_typed_counters(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE daily_risk_counters (
            session_date TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (typeof(session_date) = 'text' AND length(session_date) = 10),
            CHECK (typeof(identity) = 'text' AND length(identity) = 64),
            CHECK (typeof(payload) = 'blob'),
            CHECK (typeof(updated_at) = 'text' AND length(updated_at) = 27)
        )
        """
    )


def _create_scoped_counters(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE scoped_daily_risk_counters (
            counter_key TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """
    )


def upgrade(conn: sqlite3.Connection) -> None:
    """Preserve either legacy shape and expose both non-overlapping stores."""
    counter_columns = _columns(conn, "daily_risk_counters")
    scoped_columns = _columns(conn, "scoped_daily_risk_counters")

    if counter_columns == _SCOPED_COUNTER_COLUMNS:
        if scoped_columns is not None:
            raise sqlite3.DatabaseError("ambiguous legacy risk counter schema")
        conn.execute(
            "ALTER TABLE daily_risk_counters RENAME TO scoped_daily_risk_counters"
        )
        _create_typed_counters(conn)
    elif counter_columns == _TYPED_COUNTER_COLUMNS:
        if scoped_columns is None:
            _create_scoped_counters(conn)
        elif scoped_columns != _SCOPED_COUNTER_COLUMNS:
            raise sqlite3.DatabaseError("invalid scoped risk counter schema")
    elif counter_columns is None:
        _create_typed_counters(conn)
        if scoped_columns is None:
            _create_scoped_counters(conn)
        elif scoped_columns != _SCOPED_COUNTER_COLUMNS:
            raise sqlite3.DatabaseError("invalid scoped risk counter schema")
    else:
        raise sqlite3.DatabaseError("unknown risk counter schema")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_stages (
            plan_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """
    )
