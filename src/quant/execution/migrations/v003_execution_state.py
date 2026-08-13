"""Add immutable stage receipts and durable daily risk counters."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create opaque execution-state rows without changing delivery semantics."""
    statements = (
        """
        CREATE TABLE execution_stages (
            plan_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE daily_risk_counters (
            counter_key TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL
        )
        """,
    )
    for statement in statements:
        conn.execute(statement)
