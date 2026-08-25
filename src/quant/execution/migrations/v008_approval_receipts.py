"""Add the immutable, indexed durable formal-approval receipt table."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create v008 without rewriting any existing OMS or risk rows."""
    conn.execute(
        """
        CREATE TABLE approval_receipts (
            receipt_id TEXT PRIMARY KEY NOT NULL,
            identity TEXT NOT NULL UNIQUE,
            schema_version TEXT NOT NULL
                CHECK (schema_version = 'm4-approval-receipt-v1'),
            classification TEXT NOT NULL
                CHECK (classification = 'FORMAL_APPROVAL'),
            credential_kind TEXT NOT NULL
                CHECK (credential_kind = 'HMAC_SHA256_CREDENTIAL_V1'),
            credential_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action = 'FORMAL_APPROVAL'),
            plan_identity TEXT NOT NULL,
            challenge_identity TEXT NOT NULL,
            store_recovery_identity TEXT NOT NULL,
            source_identities_digest TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            nonce TEXT NOT NULL,
            payload BLOB NOT NULL,
            UNIQUE (plan_identity, session_date, action),
            UNIQUE (credential_id, nonce),
            CHECK (typeof(receipt_id) = 'text' AND length(receipt_id) = 64),
            CHECK (typeof(identity) = 'text' AND length(identity) = 64),
            CHECK (typeof(credential_id) = 'text' AND length(credential_id) > 0),
            CHECK (typeof(operator_id) = 'text' AND length(operator_id) > 0),
            CHECK (typeof(session_date) = 'text' AND length(session_date) = 10),
            CHECK (typeof(plan_identity) = 'text' AND length(plan_identity) = 64),
            CHECK (typeof(challenge_identity) = 'text' AND length(challenge_identity) = 64),
            CHECK (
                typeof(store_recovery_identity) = 'text'
                AND length(store_recovery_identity) = 64
            ),
            CHECK (
                typeof(source_identities_digest) = 'text'
                AND length(source_identities_digest) = 64
            ),
            CHECK (typeof(issued_at) = 'text' AND length(issued_at) = 27),
            CHECK (typeof(nonce) = 'text' AND length(nonce) > 0),
            CHECK (typeof(payload) = 'blob')
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_approval_receipts_plan_session
        ON approval_receipts (plan_identity, session_date, receipt_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_approval_receipts_recovery
        ON approval_receipts (store_recovery_identity, receipt_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_approval_receipts_operator_session
        ON approval_receipts (operator_id, session_date, receipt_id)
        """
    )


__all__ = ["upgrade"]
