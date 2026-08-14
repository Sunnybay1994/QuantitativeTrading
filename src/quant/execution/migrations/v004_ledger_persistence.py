"""Add immutable ledger contexts and the single-store checkpoint."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add only new v4 tables; legacy rows remain byte-for-byte untouched."""
    conn.execute(
        """
        CREATE TABLE ledger_contexts (
            command_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            FOREIGN KEY (command_id) REFERENCES commands(command_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ledger_checkpoints (
            checkpoint_key TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            last_entry_id TEXT,
            FOREIGN KEY (last_entry_id) REFERENCES ledger_entries(entry_id)
        )
        """
    )
