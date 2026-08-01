"""Add restart-safe daily pre-trade risk counters."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create one authenticated counter row per trading session."""
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
