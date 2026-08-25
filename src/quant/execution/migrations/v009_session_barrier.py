"""Add the singleton OMS session-barrier table (schema v9).

Creates the table only. Does not insert OPEN, adopt old roots, or backfill.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the unique session_barrier table without inserting a row."""
    conn.execute(
        """
        CREATE TABLE session_barrier (
            singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
            barrier_schema TEXT NOT NULL
                CHECK (barrier_schema = 'm4-session-barrier-v1'),
            barrier_epoch TEXT NOT NULL,
            session_date TEXT NOT NULL,
            account_identity TEXT NOT NULL,
            oms_store_identity TEXT NOT NULL,
            broker_store_identity TEXT NOT NULL,
            gateway_identity TEXT NOT NULL,
            config_identity TEXT NOT NULL,
            lock_identity TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSING', 'CLOSED')),
            close_token_identity TEXT,
            created_at TEXT NOT NULL,
            transitioned_at TEXT NOT NULL,
            row_identity TEXT NOT NULL UNIQUE,
            CHECK (typeof(barrier_epoch) = 'text' AND length(barrier_epoch) = 64),
            CHECK (typeof(session_date) = 'text' AND length(session_date) = 10),
            CHECK (typeof(account_identity) = 'text' AND length(account_identity) = 64),
            CHECK (typeof(oms_store_identity) = 'text' AND length(oms_store_identity) = 64),
            CHECK (
                typeof(broker_store_identity) = 'text'
                AND length(broker_store_identity) = 64
            ),
            CHECK (typeof(gateway_identity) = 'text' AND length(gateway_identity) = 64),
            CHECK (typeof(config_identity) = 'text' AND length(config_identity) = 64),
            CHECK (typeof(lock_identity) = 'text' AND length(lock_identity) = 64),
            CHECK (typeof(created_at) = 'text' AND length(created_at) = 27),
            CHECK (typeof(transitioned_at) = 'text' AND length(transitioned_at) = 27),
            CHECK (typeof(row_identity) = 'text' AND length(row_identity) = 64),
            CHECK (
                (state = 'OPEN' AND close_token_identity IS NULL)
                OR (
                    state IN ('CLOSING', 'CLOSED')
                    AND typeof(close_token_identity) = 'text'
                    AND length(close_token_identity) = 64
                )
            )
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX idx_session_barrier_row_identity
        ON session_barrier (row_identity)
        """
    )


__all__ = ["upgrade"]
