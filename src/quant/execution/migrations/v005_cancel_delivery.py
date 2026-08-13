"""Add the independent durable PAPER cancel outbox."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add cancel command, delivery and callback-link tables without rewriting v4."""
    conn.execute(
        """
        CREATE TABLE cancel_commands (
            cancel_id TEXT PRIMARY KEY NOT NULL,
            command_id TEXT NOT NULL UNIQUE,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            risk_counter_key TEXT NOT NULL,
            risk_policy_identity TEXT NOT NULL,
            FOREIGN KEY (command_id) REFERENCES commands(command_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE cancel_deliveries (
            cancel_id TEXT PRIMARY KEY NOT NULL,
            command_id TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK (state IN ('PENDING', 'LEASED', 'SENT', 'UNKNOWN')),
            attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
            available_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_until TEXT,
            terminal_at TEXT,
            last_error_code TEXT,
            FOREIGN KEY (cancel_id) REFERENCES cancel_commands(cancel_id),
            FOREIGN KEY (command_id) REFERENCES commands(command_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE cancel_event_links (
            cancel_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            PRIMARY KEY (cancel_id, event_id),
            FOREIGN KEY (cancel_id) REFERENCES cancel_commands(cancel_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
        """
    )


__all__ = ["upgrade"]
