"""Add nullable terminal_successor_identity on session_barrier (schema v10).

Does not backfill or invent successor values. Existing v9 rows keep NULL.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add nullable terminal_successor_identity; leave all existing rows NULL."""
    conn.execute(
        """
        ALTER TABLE session_barrier
        ADD COLUMN terminal_successor_identity TEXT
        """
    )


__all__ = ["upgrade"]
