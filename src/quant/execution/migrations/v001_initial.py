"""Initial execution store schema (version 1)."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create durable OMS/outbox/ledger tables and unique primary keys.

    Uses discrete executes (not executescript) so the caller transaction stays open.
    """
    statements = (
        """
        CREATE TABLE IF NOT EXISTS commands (
            command_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY NOT NULL,
            command_id TEXT NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            FOREIGN KEY (command_id) REFERENCES commands (command_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS order_aggregates (
            command_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS outbox (
            outbox_key TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            entry_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reconciliation_runs (
            run_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
    )
    for statement in statements:
        conn.execute(statement)
