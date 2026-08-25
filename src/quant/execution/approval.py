"""Canonical, caller-keyed durable formal-approval receipts.

The credential is deliberately accepted only at the build/verify boundary.  It
is never a field on a receipt, store row, recovery value, exception, or log
message.  The store can therefore retain verified raw bytes without owning the
credential needed to verify them again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Final, Literal, cast

from quant.domain.canonical_wire import (
    WireError,
    canonical_json_bytes,
    require_date,
    require_exact_object,
    require_string,
    require_utc_datetime,
    require_wire_root,
    utc_datetime_text,
)

APPROVAL_RECEIPT_SCHEMA_VERSION: Final[str] = "m4-approval-receipt-v1"
APPROVAL_RECEIPT_CLASSIFICATION: Final[str] = "FORMAL_APPROVAL"
HMAC_SHA256_CREDENTIAL_V1: Final[str] = "HMAC_SHA256_CREDENTIAL_V1"
FORMAL_APPROVAL_ACTION: Final[str] = "FORMAL_APPROVAL"
MIN_SECRET_BYTES: Final[int] = 32
MIN_CREDENTIAL_SECRET_BYTES: Final[int] = MIN_SECRET_BYTES

_HEX = frozenset("0123456789abcdef")
_SCHEMA = APPROVAL_RECEIPT_SCHEMA_VERSION
_CLASSIFICATION = APPROVAL_RECEIPT_CLASSIFICATION
_CREDENTIAL_KIND = HMAC_SHA256_CREDENTIAL_V1
_ACTION = FORMAL_APPROVAL_ACTION
_HANDOFF_PROOF_KEY: Final[bytes] = secrets.token_bytes(32)
_HANDOFF_PROOF_DOMAIN: Final[bytes] = b"m4-approval-receipt-handoff-v1\x00"
_WIRE_KEYS = frozenset(
    {
        "classification",
        "credential_id",
        "credential_kind",
        "operator_id",
        "session_date",
        "action",
        "plan_identity",
        "challenge_identity",
        "store_recovery_identity",
        "source_identities_digest",
        "issued_at",
        "nonce",
        "tag",
        "receipt_id",
    }
)


class ApprovalReceiptError(ValueError):
    """Stable, detached rejection of an invalid approval receipt."""

    def __init__(self, code: str = "APPROVAL_RECEIPT_INVALID") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    """One canonical formal-approval receipt without its signing credential."""

    schema_version: str
    classification: Literal["FORMAL_APPROVAL"]
    credential_kind: Literal["HMAC_SHA256_CREDENTIAL_V1"]
    credential_id: str
    operator_id: str
    session_date: str
    action: Literal["FORMAL_APPROVAL"]
    plan_identity: str
    challenge_identity: str
    store_recovery_identity: str
    source_identities_digest: str
    issued_at: str
    nonce: str
    tag: str
    receipt_id: str

    def __post_init__(self) -> None:
        _validate_receipt(self)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedApprovalReceipt:
    """Credential-free raw bytes proven by the caller's credential.

    Ordinary callers cannot construct this hand-off.  Its in-process proof is
    intentionally omitted from repr/equality and never enters the wire/store.
    """

    receipt: ApprovalReceipt
    payload: bytes
    _proof: bytes = field(repr=False, compare=False)

    def __init__(self, receipt: ApprovalReceipt, payload: bytes) -> None:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None


def canonical_source_identities_digest(source_identities: object) -> str:
    """Digest one explicitly ordered source-identity collection.

    A mapping must already be key-sorted.  A tuple of identities must already
    be strictly sorted, and a tuple of key/value pairs follows the same rule.
    Lists, duplicate keys/values, and reordered inputs are rejected instead of
    being silently normalized.
    """
    try:
        normalized = _canonical_source_identities(source_identities)
        return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()
    except ApprovalReceiptError:
        raise
    except Exception:
        raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID") from None


def build_approval_receipt(
    secret: object,
    *,
    credential_id: str,
    operator_id: str,
    session_date: dt.date | str,
    plan_identity: str,
    challenge_identity: str,
    store_recovery_identity: str,
    source_identities: object | None = None,
    source_identities_digest: str | None = None,
    issued_at: dt.datetime | str | None = None,
    nonce: str | bytes | bytearray | memoryview | None = None,
    action: str = FORMAL_APPROVAL_ACTION,
    classification: str = APPROVAL_RECEIPT_CLASSIFICATION,
    credential_kind: str = HMAC_SHA256_CREDENTIAL_V1,
) -> ApprovalReceipt:
    """Build and sign one canonical receipt using a caller-only credential."""
    try:
        key = _secret_bytes(secret)
        if action != _ACTION or classification != _CLASSIFICATION:
            raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID")
        if credential_kind != _CREDENTIAL_KIND:
            raise ApprovalReceiptError("APPROVAL_CREDENTIAL_UNSUPPORTED")

        source_digest = _resolve_source_digest(
            source_identities, source_identities_digest
        )
        body: dict[str, object] = {
            "action": _ACTION,
            "challenge_identity": _require_hex64(
                "challenge_identity", challenge_identity
            ),
            "classification": _CLASSIFICATION,
            "credential_id": _require_opaque("credential_id", credential_id),
            "credential_kind": _CREDENTIAL_KIND,
            "issued_at": _issued_at_text(issued_at),
            "nonce": _nonce_text(nonce),
            "operator_id": _require_opaque("operator_id", operator_id),
            "plan_identity": _require_hex64("plan_identity", plan_identity),
            "schema_version": _SCHEMA,
            "session_date": _session_date_text(session_date),
            "source_identities_digest": source_digest,
            "store_recovery_identity": _require_hex64(
                "store_recovery_identity", store_recovery_identity
            ),
        }
        body_bytes = canonical_json_bytes(body)
        if key in body_bytes or key.hex().encode("ascii") in body_bytes:
            raise ApprovalReceiptError("APPROVAL_SECRET_INVALID")
        tag = hmac.new(key, body_bytes, hashlib.sha256).hexdigest()
        envelope = {**body, "tag": tag}
        receipt_id = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
        return ApprovalReceipt(
            schema_version=_SCHEMA,
            classification=cast(Literal["FORMAL_APPROVAL"], _CLASSIFICATION),
            credential_kind=cast(
                Literal["HMAC_SHA256_CREDENTIAL_V1"], _CREDENTIAL_KIND
            ),
            credential_id=cast(str, body["credential_id"]),
            operator_id=cast(str, body["operator_id"]),
            session_date=cast(str, body["session_date"]),
            action=cast(Literal["FORMAL_APPROVAL"], _ACTION),
            plan_identity=cast(str, body["plan_identity"]),
            challenge_identity=cast(str, body["challenge_identity"]),
            store_recovery_identity=cast(str, body["store_recovery_identity"]),
            source_identities_digest=cast(str, body["source_identities_digest"]),
            issued_at=cast(str, body["issued_at"]),
            nonce=cast(str, body["nonce"]),
            tag=tag,
            receipt_id=receipt_id,
        )
    except ApprovalReceiptError:
        raise
    except Exception:
        raise ApprovalReceiptError() from None


def encode_approval_receipt(value: ApprovalReceipt) -> bytes:
    """Encode one exact canonical receipt, excluding any signing secret."""
    try:
        if type(value) is not ApprovalReceipt:
            raise ApprovalReceiptError()
        _validate_receipt(value)
        return canonical_json_bytes({**_receipt_envelope(value), "receipt_id": value.receipt_id})
    except ApprovalReceiptError:
        raise
    except Exception:
        raise ApprovalReceiptError() from None


def decode_approval_receipt(payload: bytes) -> ApprovalReceipt:
    """Decode and structurally re-prove canonical receipt bytes."""
    try:
        if type(payload) is not bytes:
            raise ApprovalReceiptError()
        root = require_wire_root(
            payload,
            schema=_SCHEMA,
            keys=set(_WIRE_KEYS),
        )
        exact = require_exact_object(root, set(_WIRE_KEYS) | {"schema_version"}, schema=_SCHEMA)
        value = ApprovalReceipt(
            schema_version=cast(str, require_string(exact["schema_version"])),
            classification=cast(
                Literal["FORMAL_APPROVAL"], require_string(exact["classification"])
            ),
            credential_kind=cast(
                Literal["HMAC_SHA256_CREDENTIAL_V1"],
                require_string(exact["credential_kind"]),
            ),
            credential_id=cast(str, require_string(exact["credential_id"])),
            operator_id=cast(str, require_string(exact["operator_id"])),
            session_date=cast(str, require_string(exact["session_date"])),
            action=cast(Literal["FORMAL_APPROVAL"], require_string(exact["action"])),
            plan_identity=cast(str, require_string(exact["plan_identity"])),
            challenge_identity=cast(
                str, require_string(exact["challenge_identity"])
            ),
            store_recovery_identity=cast(
                str, require_string(exact["store_recovery_identity"])
            ),
            source_identities_digest=cast(
                str, require_string(exact["source_identities_digest"])
            ),
            issued_at=cast(str, require_string(exact["issued_at"])),
            nonce=cast(str, require_string(exact["nonce"])),
            tag=cast(str, require_string(exact["tag"])),
            receipt_id=cast(str, require_string(exact["receipt_id"])),
        )
        if encode_approval_receipt(value) != payload:
            raise ApprovalReceiptError()
        return value
    except ApprovalReceiptError:
        raise
    except WireError as error:
        if error.code == "WIRE_VERSION_UNSUPPORTED":
            raise ApprovalReceiptError("APPROVAL_RECEIPT_UNSUPPORTED_VERSION") from None
        raise ApprovalReceiptError() from None
    except Exception:
        raise ApprovalReceiptError() from None


def verify_approval_receipt(
    payload: bytes,
    secret: object,
    *,
    source_identities: object | None = None,
) -> ApprovalReceipt:
    """Verify the HMAC and identity with a caller-provided credential."""
    try:
        value = decode_approval_receipt(payload)
        key = _secret_bytes(secret)
        expected_tag = hmac.new(
            key, canonical_json_bytes(_receipt_body(value)), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(value.tag, expected_tag):
            raise ApprovalReceiptError("APPROVAL_RECEIPT_SIGNATURE_INVALID")
        expected_receipt_id = hashlib.sha256(
            canonical_json_bytes(_receipt_envelope(value))
        ).hexdigest()
        if not hmac.compare_digest(value.receipt_id, expected_receipt_id):
            raise ApprovalReceiptError("APPROVAL_RECEIPT_IDENTITY_INVALID")
        if source_identities is not None:
            expected_source_digest = canonical_source_identities_digest(
                source_identities
            )
            if not hmac.compare_digest(
                value.source_identities_digest, expected_source_digest
            ):
                raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        return value
    except ApprovalReceiptError:
        raise
    except Exception:
        raise ApprovalReceiptError() from None


def verify_approval_receipt_for_store(
    payload: bytes,
    secret: object,
    *,
    source_identities: object | None = None,
) -> VerifiedApprovalReceipt:
    """Verify once and return the credential-free store hand-off value."""
    value = verify_approval_receipt(
        payload, secret, source_identities=source_identities
    )
    return _new_verified_handoff(value, payload)


def _new_verified_handoff(
    receipt: ApprovalReceipt, payload: bytes
) -> VerifiedApprovalReceipt:
    handoff = object.__new__(VerifiedApprovalReceipt)
    object.__setattr__(handoff, "receipt", receipt)
    object.__setattr__(handoff, "payload", payload)
    object.__setattr__(
        handoff, "_proof", _handoff_proof(receipt.receipt_id, payload)
    )
    return handoff


def unpack_verified_approval_receipt(
    value: object,
) -> tuple[ApprovalReceipt, bytes]:
    """Validate and unwrap one in-process verified hand-off.

    The proof key remains private to this module.  Callers receive only the
    already-validated receipt and canonical bytes; the proof is discarded at
    this boundary.
    """
    if type(value) is not VerifiedApprovalReceipt:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    try:
        receipt = value.receipt
        payload = value.payload
        proof = value._proof
    except (AttributeError, TypeError):
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    if type(receipt) is not ApprovalReceipt or type(payload) is not bytes:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    if type(proof) is not bytes:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    try:
        if encode_approval_receipt(receipt) != payload:
            raise ApprovalReceiptError("APPROVAL_RECEIPT_INDEX_MISMATCH")
        expected = _handoff_proof(receipt.receipt_id, payload)
        if not hmac.compare_digest(proof, expected):
            raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED")
    except ApprovalReceiptError:
        raise
    except Exception:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    return receipt, payload


def _handoff_proof(receipt_id: str, payload: bytes) -> bytes:
    material = (
        _HANDOFF_PROOF_DOMAIN
        + receipt_id.encode("ascii")
        + b"\x00"
        + payload
    )
    return hmac.new(_HANDOFF_PROOF_KEY, material, hashlib.sha256).digest()


def _secret_bytes(value: object) -> bytes:
    if type(value) is bytes:
        result = value
    elif type(value) is bytearray:
        result = bytes(value)
    elif type(value) is memoryview:
        result = value.tobytes()
    else:
        raise ApprovalReceiptError("APPROVAL_SECRET_INVALID") from None
    if len(result) < MIN_SECRET_BYTES:
        raise ApprovalReceiptError("APPROVAL_SECRET_INVALID") from None
    return result


def _require_opaque(name: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID")
    return value


def _require_hex64(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in _HEX for char in value)
    ):
        raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID")
    return value


def _session_date_text(value: object) -> str:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is str:
        try:
            return require_date(value).isoformat()
        except Exception:
            pass
    raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID") from None


def _issued_at_text(value: dt.datetime | str | None) -> str:
    if value is None:
        value = dt.datetime.now(dt.timezone.utc)
    if type(value) is dt.datetime:
        try:
            return utc_datetime_text(value)
        except Exception:
            pass
    if type(value) is str:
        try:
            return utc_datetime_text(require_utc_datetime(value))
        except Exception:
            pass
    raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID") from None


def _nonce_text(value: object) -> str:
    if value is None:
        return secrets.token_hex(16)
    if type(value) is bytes:
        return value.hex()
    if type(value) is bytearray:
        return bytes(value).hex()
    if type(value) is memoryview:
        return value.tobytes().hex()
    return _require_opaque("nonce", value)


def _canonical_source_identities(source_identities: object) -> dict[str, object]:
    if type(source_identities) is dict:
        items = list(source_identities.items())
        keys = [_require_opaque("source_identity_key", item[0]) for item in items]
        if len(set(keys)) != len(keys) or tuple(keys) != tuple(sorted(keys)):
            raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        values = [_require_opaque("source_identity", item[1]) for item in items]
        if len(set(values)) != len(values):
            raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        return {"source_identities": dict(zip(keys, values, strict=True))}

    if type(source_identities) is not tuple:
        raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
    if all(type(item) is str for item in source_identities):
        values = [_require_opaque("source_identity", item) for item in source_identities]
        if len(set(values)) != len(values) or tuple(values) != tuple(sorted(values)):
            raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        return {"source_identities": values}

    pairs: list[tuple[str, str]] = []
    for item in source_identities:
        if type(item) is not tuple or len(item) != 2:
            raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        pairs.append(
            (
                _require_opaque("source_identity_key", item[0]),
                _require_opaque("source_identity", item[1]),
            )
        )
    keys = [item[0] for item in pairs]
    values = [item[1] for item in pairs]
    if (
        len(set(keys)) != len(keys)
        or len(set(values)) != len(values)
        or tuple(keys) != tuple(sorted(keys))
    ):
        raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
    return {"source_identities": dict(pairs)}


def _resolve_source_digest(
    source_identities: object | None,
    source_identities_digest: str | None,
) -> str:
    if source_identities is None and source_identities_digest is None:
        raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
    computed = (
        None
        if source_identities is None
        else canonical_source_identities_digest(source_identities)
    )
    supplied = (
        None
        if source_identities_digest is None
        else _require_hex64("source_identities_digest", source_identities_digest)
    )
    if computed is not None and supplied is not None:
        if not hmac.compare_digest(computed, supplied):
            raise ApprovalReceiptError("APPROVAL_SOURCE_IDENTITIES_INVALID")
        return computed
    return cast(str, computed if computed is not None else supplied)


def _receipt_body(value: ApprovalReceipt) -> dict[str, object]:
    return {
        "action": value.action,
        "challenge_identity": value.challenge_identity,
        "classification": value.classification,
        "credential_id": value.credential_id,
        "credential_kind": value.credential_kind,
        "issued_at": value.issued_at,
        "nonce": value.nonce,
        "operator_id": value.operator_id,
        "plan_identity": value.plan_identity,
        "schema_version": value.schema_version,
        "session_date": value.session_date,
        "source_identities_digest": value.source_identities_digest,
        "store_recovery_identity": value.store_recovery_identity,
    }


def _receipt_envelope(value: ApprovalReceipt) -> dict[str, object]:
    return {**_receipt_body(value), "tag": value.tag}


def _validate_receipt(value: ApprovalReceipt) -> None:
    if (
        type(value.schema_version) is not str
        or value.schema_version != _SCHEMA
        or type(value.classification) is not str
        or value.classification != _CLASSIFICATION
        or type(value.credential_kind) is not str
        or value.credential_kind != _CREDENTIAL_KIND
        or type(value.action) is not str
        or value.action != _ACTION
    ):
        raise ApprovalReceiptError("APPROVAL_RECEIPT_INVALID") from None
    _require_opaque("credential_id", value.credential_id)
    _require_opaque("operator_id", value.operator_id)
    _session_date_text(value.session_date)
    _require_hex64("plan_identity", value.plan_identity)
    _require_hex64("challenge_identity", value.challenge_identity)
    _require_hex64("store_recovery_identity", value.store_recovery_identity)
    _require_hex64("source_identities_digest", value.source_identities_digest)
    _issued_at_text(value.issued_at)
    _require_opaque("nonce", value.nonce)
    _require_hex64("tag", value.tag)
    _require_hex64("receipt_id", value.receipt_id)
    expected = hashlib.sha256(canonical_json_bytes(_receipt_envelope(value))).hexdigest()
    if not hmac.compare_digest(value.receipt_id, expected):
        raise ApprovalReceiptError("APPROVAL_RECEIPT_IDENTITY_INVALID") from None


__all__ = [
    "APPROVAL_RECEIPT_CLASSIFICATION",
    "APPROVAL_RECEIPT_SCHEMA_VERSION",
    "ApprovalReceipt",
    "ApprovalReceiptError",
    "FORMAL_APPROVAL_ACTION",
    "HMAC_SHA256_CREDENTIAL_V1",
    "MIN_CREDENTIAL_SECRET_BYTES",
    "MIN_SECRET_BYTES",
    "VerifiedApprovalReceipt",
    "build_approval_receipt",
    "canonical_source_identities_digest",
    "decode_approval_receipt",
    "encode_approval_receipt",
    "unpack_verified_approval_receipt",
    "verify_approval_receipt",
    "verify_approval_receipt_for_store",
]
