"""Add the append-only ORDER/CANCEL risk transition journal."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create v006 without rewriting or endorsing any legacy row."""
    conn.execute(
        """
        CREATE TABLE risk_transition_receipts (
            sequence INTEGER PRIMARY KEY CHECK (sequence >= 1),
            transition_kind TEXT NOT NULL CHECK (transition_kind IN ('ORDER', 'CANCEL')),
            subject_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL UNIQUE,
            previous_receipt_id TEXT NOT NULL,
            risk_counter_key TEXT NOT NULL,
            predecessor_counter_identity TEXT NOT NULL,
            projected_counter_identity TEXT NOT NULL,
            payload BLOB NOT NULL,
            UNIQUE (transition_kind, subject_id)
        )
        """
    )


__all__ = ["upgrade"]
