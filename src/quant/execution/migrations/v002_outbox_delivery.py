"""Add restart-safe delivery state for transactional outbox rows."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create delivery metadata without making legacy outbox rows sendable."""
    statements = (
        """
        CREATE TABLE outbox_deliveries (
            outbox_key TEXT PRIMARY KEY NOT NULL,
            command_id TEXT NOT NULL,
            state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            available_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_until TEXT,
            terminal_at TEXT,
            last_error_code TEXT,
            FOREIGN KEY (outbox_key) REFERENCES outbox (outbox_key),
            FOREIGN KEY (command_id) REFERENCES commands (command_id),
            FOREIGN KEY (command_id) REFERENCES order_aggregates (command_id),
            CHECK (state IN ('PENDING', 'LEASED', 'SENT', 'UNKNOWN')),
            CHECK (typeof(attempt_count) = 'integer' AND attempt_count >= 0),
            CHECK (
                (state = 'PENDING' AND attempt_count = 0
                    AND lease_owner IS NULL AND lease_until IS NULL
                    AND terminal_at IS NULL AND last_error_code IS NULL)
                OR
                (state = 'LEASED' AND attempt_count >= 1
                    AND lease_owner IS NOT NULL AND lease_until IS NOT NULL
                    AND terminal_at IS NULL AND last_error_code IS NULL)
                OR
                (state = 'SENT' AND attempt_count >= 1
                    AND lease_owner IS NOT NULL AND lease_until IS NOT NULL
                    AND terminal_at IS NOT NULL AND last_error_code IS NULL)
                OR
                (state = 'UNKNOWN' AND attempt_count >= 1
                    AND lease_owner IS NOT NULL AND lease_until IS NOT NULL
                    AND terminal_at IS NOT NULL AND last_error_code IS NOT NULL)
            )
        )
        """,
        """
        CREATE INDEX idx_outbox_deliveries_pending
        ON outbox_deliveries (available_at, outbox_key)
        WHERE state = 'PENDING'
        """,
        """
        CREATE INDEX idx_outbox_deliveries_expired_lease
        ON outbox_deliveries (lease_until, available_at, outbox_key)
        WHERE state = 'LEASED'
        """,
    )
    for statement in statements:
        conn.execute(statement)
