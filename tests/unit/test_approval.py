"""Focused static contract tests for the durable formal-approval codec."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from quant.domain.canonical_wire import canonical_json_bytes
from quant.execution.approval import (
    APPROVAL_RECEIPT_CLASSIFICATION,
    APPROVAL_RECEIPT_SCHEMA_VERSION,
    ApprovalReceiptError,
    FORMAL_APPROVAL_ACTION,
    HMAC_SHA256_CREDENTIAL_V1,
    MIN_SECRET_BYTES,
    VerifiedApprovalReceipt,
    build_approval_receipt,
    canonical_source_identities_digest,
    decode_approval_receipt,
    encode_approval_receipt,
    verify_approval_receipt,
    verify_approval_receipt_for_store,
)

UTC = dt.timezone.utc
SECRET = b"approval-secret-for-tests-0123456789"
OTHER_SECRET = b"another-secret-for-tests-012345678"
SESSION_DATE = dt.date(2026, 8, 24)
ISSUED_AT = dt.datetime(2026, 8, 24, 3, 4, 5, 678901, tzinfo=UTC)
PLAN_ID = "1" * 64
CHALLENGE_ID = "2" * 64
STORE_RECOVERY_ID = "3" * 64
SOURCES = {
    "account_snapshot": "4" * 64,
    "market_snapshot": "5" * 64,
    "planner_config": "6" * 64,
}


def _receipt(*, nonce: str = "nonce-1"):
    return build_approval_receipt(
        SECRET,
        credential_id="credential/operator-key-1",
        operator_id="operator-1",
        session_date=SESSION_DATE,
        plan_identity=PLAN_ID,
        challenge_identity=CHALLENGE_ID,
        store_recovery_identity=STORE_RECOVERY_ID,
        source_identities=SOURCES,
        issued_at=ISSUED_AT,
        nonce=nonce,
    )


def _rewrite(payload: bytes, **changes: object) -> bytes:
    root = json.loads(payload.decode("utf-8"))
    root.update(changes)
    return canonical_json_bytes(root)


def test_canonical_hmac_round_trip_and_caller_only_secret() -> None:
    receipt = _receipt()
    encoded = encode_approval_receipt(receipt)

    assert decode_approval_receipt(encoded) == receipt
    assert verify_approval_receipt(
        encoded, SECRET, source_identities=SOURCES
    ) == receipt
    assert SECRET not in encoded
    assert SECRET.hex().encode("ascii") not in encoded
    assert SECRET.decode("ascii") not in repr(receipt)
    assert receipt.action == FORMAL_APPROVAL_ACTION
    assert receipt.classification == APPROVAL_RECEIPT_CLASSIFICATION
    assert receipt.credential_kind == HMAC_SHA256_CREDENTIAL_V1
    assert receipt.schema_version == APPROVAL_RECEIPT_SCHEMA_VERSION


@pytest.mark.parametrize(
    "payload_factory",
    [
        lambda raw: _rewrite(raw, operator_id="operator-tampered"),
        lambda raw: _rewrite(raw, tag="0" * 64),
        lambda raw: _rewrite(raw, receipt_id="0" * 64),
    ],
)
def test_single_field_body_tag_or_identity_tamper_fails_closed(
    payload_factory,
) -> None:  # type: ignore[no-untyped-def]
    raw = encode_approval_receipt(_receipt())
    tampered = payload_factory(raw)

    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(tampered)
    with pytest.raises(ApprovalReceiptError):
        verify_approval_receipt(tampered, SECRET)


def test_wrong_key_is_constant_time_fail_closed_without_secret_error_text() -> None:
    raw = encode_approval_receipt(_receipt())

    with pytest.raises(ApprovalReceiptError) as error:
        verify_approval_receipt(raw, OTHER_SECRET)
    assert OTHER_SECRET.decode("ascii") not in str(error.value)
    assert OTHER_SECRET.decode("ascii") not in repr(error.value)


def test_noncanonical_duplicate_extra_and_future_wire_forms_fail_closed() -> None:
    raw = encode_approval_receipt(_receipt())

    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(raw + b" ")
    duplicate_tag = raw[:-1] + b',"tag":"' + b"0" * 64 + b'"}'
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(duplicate_tag)
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(_rewrite(raw, extra="forbidden"))
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(
            _rewrite(raw, schema_version="m4-approval-receipt-v2")
        )
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(
            _rewrite(raw, credential_kind="UNKNOWN_CREDENTIAL_V2")
        )
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(
            _rewrite(raw, issued_at="2026-08-24T11:04:05.678901+08:00")
        )


def test_receipt_id_is_required_and_duplicate_receipt_id_fails_closed() -> None:
    raw = encode_approval_receipt(_receipt())
    missing_receipt_id = json.loads(raw.decode("utf-8"))
    missing_receipt_id.pop("receipt_id")

    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(canonical_json_bytes(missing_receipt_id))

    duplicate_receipt_id = raw[:-1] + b',"receipt_id":"' + b"0" * 64 + b'"}'
    with pytest.raises(ApprovalReceiptError):
        decode_approval_receipt(duplicate_receipt_id)


def test_source_identities_are_canonical_and_digest_is_rebound_on_verify() -> None:
    assert canonical_source_identities_digest(SOURCES) == _receipt().source_identities_digest

    with pytest.raises(ApprovalReceiptError):
        canonical_source_identities_digest(
            {"market_snapshot": "5" * 64, "account_snapshot": "4" * 64}
        )
    with pytest.raises(ApprovalReceiptError):
        canonical_source_identities_digest(("source-a", "source-a"))
    with pytest.raises(ApprovalReceiptError):
        canonical_source_identities_digest(("source-b", "source-a"))

    raw = encode_approval_receipt(_receipt())
    with pytest.raises(ApprovalReceiptError):
        verify_approval_receipt(
            raw,
            SECRET,
            source_identities={
                "account_snapshot": "4" * 64,
                "market_snapshot": "5" * 64,
                "planner_config": "7" * 64,
            },
        )


@pytest.mark.parametrize(
    "secret",
    ["not-bytes", b"short", memoryview(b"short")],
)
def test_secret_requires_bytes_like_minimum_length(secret: object) -> None:
    assert MIN_SECRET_BYTES >= 32
    with pytest.raises(ApprovalReceiptError):
        _ = build_approval_receipt(
            secret,
            credential_id="credential-1",
            operator_id="operator-1",
            session_date=SESSION_DATE,
            plan_identity=PLAN_ID,
            challenge_identity=CHALLENGE_ID,
            store_recovery_identity=STORE_RECOVERY_ID,
            source_identities=SOURCES,
            issued_at=ISSUED_AT,
            nonce="nonce-invalid-secret",
        )


def test_zero_order_noop_theme_is_representable_without_dispatch_api() -> None:
    receipt = _receipt(nonce="noop-receipt")
    verified = verify_approval_receipt_for_store(
        encode_approval_receipt(receipt), SECRET, source_identities=SOURCES
    )

    assert isinstance(verified, VerifiedApprovalReceipt)
    assert verified.receipt == receipt
    assert verified.payload == encode_approval_receipt(receipt)
    assert "_proof" not in repr(verified)
    assert not any(name.endswith("dispatch") for name in dir(verified))


def test_verified_handoff_direct_construction_fails_closed() -> None:
    receipt = _receipt(nonce="constructor-guard")
    raw = encode_approval_receipt(receipt)

    with pytest.raises(ApprovalReceiptError, match="^APPROVAL_RECEIPT_NOT_VERIFIED$"):
        VerifiedApprovalReceipt(receipt=receipt, payload=raw)
