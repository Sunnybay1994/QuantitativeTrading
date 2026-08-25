"""Process-local formal-approval credential capability and challenge issuance.

Secrets stay caller-injected and never enter wire, store, CLI output, or errors.
A2 has no credential store: the first injected capability is the authority for
this process; wrong-secret checks apply only to re-verify / conflict paths.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, NoReturn, SupportsIndex, cast

from quant.domain.canonical_wire import (
    canonical_json_bytes,
    require_date,
    require_utc_datetime,
    utc_datetime_text,
)
from quant.execution.approval import (
    MIN_SECRET_BYTES,
    ApprovalReceiptError,
    VerifiedApprovalReceipt,
    build_approval_receipt,
    canonical_source_identities_digest,
    encode_approval_receipt,
    unpack_verified_approval_receipt,
    verify_approval_receipt_for_store,
)

_CHALLENGE_SCHEMA: Final[str] = "m4-paper-cli-challenge-v1"
_APPROVE_ACTION: Final[str] = "approve"
_PAPER_MODE: Final[str] = "PAPER"
_NONCE_DOMAIN: Final[bytes] = b"m4-approval-flow-nonce-v1\x00"
_CAPABILITY_PROOF_DOMAIN: Final[bytes] = b"m4-approval-flow-capability-v1\x00"
_CAPABILITY_PROOF_KEY: Final[bytes] = secrets.token_bytes(32)
_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")


class ApprovalFlowError(ValueError):
    """Stable, detached rejection for approval-flow failures."""

    def __init__(self, code: str = "APPROVAL_FLOW_INVALID") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, init=False)
class FormalApprovalCredentialCapability:
    """Exact internal credential capability; cannot be Protocol/dataclass faked."""

    credential_id: str
    operator_id: str
    session_date: str
    _secret: bytes = field(repr=False, compare=False)
    _proof: bytes = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal approval capability is process-local")


def build_formal_approval_credential_capability(
    secret: object,
    *,
    credential_id: str,
    operator_id: str,
    session_date: dt.date | str,
) -> FormalApprovalCredentialCapability:
    """Mint one exact capability from caller-provided secret and trusted anchors."""
    try:
        key = _secret_bytes(secret)
        cred = _require_opaque(credential_id)
        operator = _require_opaque(operator_id)
        session = _session_date_text(session_date)
        proof = _capability_proof(cred, operator, session, key)
        capability = object.__new__(FormalApprovalCredentialCapability)
        object.__setattr__(capability, "credential_id", cred)
        object.__setattr__(capability, "operator_id", operator)
        object.__setattr__(capability, "session_date", session)
        object.__setattr__(capability, "_secret", key)
        object.__setattr__(capability, "_proof", proof)
        return capability
    except ApprovalFlowError:
        raise
    except Exception:
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None


def unpack_formal_approval_credential_capability(
    value: object,
) -> FormalApprovalCredentialCapability:
    """Validate one in-process capability hand-off without exposing the secret."""
    if type(value) is not FormalApprovalCredentialCapability:
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None
    try:
        credential_id = value.credential_id
        operator_id = value.operator_id
        session_date = value.session_date
        secret = value._secret
        proof = value._proof
    except (AttributeError, TypeError):
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None
    if (
        type(credential_id) is not str
        or type(operator_id) is not str
        or type(session_date) is not str
        or type(secret) is not bytes
        or type(proof) is not bytes
    ):
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None
    expected = _capability_proof(credential_id, operator_id, session_date, secret)
    if not hmac.compare_digest(proof, expected):
        raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID") from None
    return value


def issue_verified_approval_from_approve_challenge(
    capability: object,
    *,
    challenge: Mapping[str, object],
    now: dt.datetime,
    expected_operator_id: str,
    expected_session_date: dt.date | str,
) -> VerifiedApprovalReceipt:
    """Prove one canonical approve challenge and return a store hand-off receipt."""
    try:
        cap = unpack_formal_approval_credential_capability(capability)
        expected_operator = _require_opaque(expected_operator_id)
        expected_session = _session_date_text(expected_session_date)
        if not hmac.compare_digest(cap.operator_id, expected_operator):
            raise ApprovalFlowError("APPROVAL_OPERATOR_DRIFT")
        if not hmac.compare_digest(cap.session_date, expected_session):
            raise ApprovalFlowError("APPROVAL_SESSION_DRIFT")
        proven = _prove_approve_challenge(challenge, now=now)
        nonce = _deterministic_nonce(cap._secret, cast(str, proven["challenge_identity"]))
        receipt = build_approval_receipt(
            cap._secret,
            credential_id=cap.credential_id,
            operator_id=cap.operator_id,
            session_date=cap.session_date,
            plan_identity=cast(str, proven["plan_identity"]),
            challenge_identity=cast(str, proven["challenge_identity"]),
            store_recovery_identity=cast(str, proven["store_recovery_id"]),
            source_identities=proven["source_identities"],
            issued_at=cast(str, proven["issued_at"]),
            nonce=nonce,
        )
        payload = encode_approval_receipt(receipt)
        return verify_approval_receipt_for_store(
            payload,
            cap._secret,
            source_identities=proven["source_identities"],
        )
    except ApprovalFlowError:
        raise
    except ApprovalReceiptError as error:
        raise ApprovalFlowError(_normalize_approval_receipt_code(error.code)) from None
    except Exception:
        raise ApprovalFlowError("APPROVAL_FLOW_INVALID") from None


_APPROVAL_SOURCE_KEYS: Final[tuple[str, ...]] = (
    "account_snapshot_id",
    "market_snapshot_id",
    "planner_config_identity",
    "target_receipt_identity",
    "target_verification_identity",
    "trading_config_identity",
)
_DERIVABLE_APPROVAL_SOURCE_KEYS: Final[tuple[str, ...]] = (
    "account_snapshot_id",
    "market_snapshot_id",
    "planner_config_identity",
    "trading_config_identity",
)


def build_approval_source_identities(
    *,
    account_snapshot_id: str,
    market_snapshot_id: str,
    planner_config_identity: str,
    target_receipt_identity: str,
    target_verification_identity: str,
    trading_config_identity: str,
) -> dict[str, str]:
    """Build the exact sorted planning-source map sealed into approve challenges."""
    items = {
        "account_snapshot_id": _require_hex64(account_snapshot_id),
        "market_snapshot_id": _require_hex64(market_snapshot_id),
        "planner_config_identity": _require_hex64(planner_config_identity),
        "target_receipt_identity": _require_hex64(target_receipt_identity),
        "target_verification_identity": _require_hex64(target_verification_identity),
        "trading_config_identity": _require_hex64(trading_config_identity),
    }
    return dict(sorted(items.items()))


def approval_source_identities_from_plan(
    *,
    account_snapshot_id: str,
    market_snapshot_id: str,
    planner_config_identity: str,
    target_receipt_identity: str,
    target_verification_identity: str,
    trading_config_identity: str,
) -> dict[str, str]:
    """Alias for the full planning-source map (not the weaker plan-only subset)."""
    return build_approval_source_identities(
        account_snapshot_id=account_snapshot_id,
        market_snapshot_id=market_snapshot_id,
        planner_config_identity=planner_config_identity,
        target_receipt_identity=target_receipt_identity,
        target_verification_identity=target_verification_identity,
        trading_config_identity=trading_config_identity,
    )


def derivable_approval_source_identities_from_plan(
    *,
    account_snapshot_id: str,
    market_snapshot_id: str,
    planner_config_identity: str,
    trading_config_identity: str,
) -> dict[str, str]:
    """Plan-recomputable subset; never invents target receipt/verification keys."""
    items = {
        "account_snapshot_id": _require_hex64(account_snapshot_id),
        "market_snapshot_id": _require_hex64(market_snapshot_id),
        "planner_config_identity": _require_hex64(planner_config_identity),
        "trading_config_identity": _require_hex64(trading_config_identity),
    }
    return dict(sorted(items.items()))


def normalize_approval_source_identities(
    source_identities: Mapping[str, str],
) -> dict[str, str]:
    """Require the exact canonical planning-source key set, sorted."""
    if type(source_identities) is not dict:
        raise ApprovalFlowError("APPROVAL_SOURCE_DRIFT")
    if set(source_identities) != set(_APPROVAL_SOURCE_KEYS):
        raise ApprovalFlowError("APPROVAL_SOURCE_DRIFT")
    normalized = {
        key: _require_hex64(source_identities[key]) for key in _APPROVAL_SOURCE_KEYS
    }
    return dict(sorted(normalized.items()))


def prove_approval_source_binding(
    source_identities: Mapping[str, str],
    *,
    account_snapshot_id: str,
    market_snapshot_id: str,
    planner_config_identity: str,
    trading_config_identity: str,
) -> dict[str, str]:
    """Prove full source digest inputs and recompute the derivable subset."""
    sources = normalize_approval_source_identities(source_identities)
    canonical_source_identities_digest(sources)
    derivable = derivable_approval_source_identities_from_plan(
        account_snapshot_id=account_snapshot_id,
        market_snapshot_id=market_snapshot_id,
        planner_config_identity=planner_config_identity,
        trading_config_identity=trading_config_identity,
    )
    for key in _DERIVABLE_APPROVAL_SOURCE_KEYS:
        if not hmac.compare_digest(sources[key], derivable[key]):
            raise ApprovalFlowError("APPROVAL_SOURCE_DRIFT")
    return sources


def reverify_stored_approval_receipt(
    capability: object,
    *,
    payload: bytes,
    source_identities: Mapping[str, str],
    expected_operator_id: str,
    expected_session_date: dt.date | str,
    expected_plan_identity: str,
) -> VerifiedApprovalReceipt:
    """Re-HMAC a stored raw approval with the live capability; never mint a second receipt."""
    try:
        cap = unpack_formal_approval_credential_capability(capability)
        expected_operator = _require_opaque(expected_operator_id)
        expected_session = _session_date_text(expected_session_date)
        expected_plan = _require_hex64(expected_plan_identity)
        if not hmac.compare_digest(cap.operator_id, expected_operator):
            raise ApprovalFlowError("APPROVAL_OPERATOR_DRIFT")
        if not hmac.compare_digest(cap.session_date, expected_session):
            raise ApprovalFlowError("APPROVAL_SESSION_DRIFT")
        if type(payload) is not bytes:
            raise ApprovalFlowError("APPROVAL_STORED_RECEIPT_INVALID")
        sources = normalize_approval_source_identities(source_identities)
        verified = verify_approval_receipt_for_store(
            payload,
            cap._secret,
            source_identities=sources,
        )
        receipt = verified.receipt
        if not hmac.compare_digest(receipt.operator_id, expected_operator):
            raise ApprovalFlowError("APPROVAL_OPERATOR_DRIFT")
        if not hmac.compare_digest(receipt.session_date, expected_session):
            raise ApprovalFlowError("APPROVAL_SESSION_DRIFT")
        if not hmac.compare_digest(receipt.plan_identity, expected_plan):
            raise ApprovalFlowError("APPROVAL_PLAN_DRIFT")
        if not hmac.compare_digest(receipt.credential_id, cap.credential_id):
            raise ApprovalFlowError("APPROVAL_CREDENTIAL_CONFLICT")
        if verified.payload != payload:
            raise ApprovalFlowError("APPROVAL_STORED_RECEIPT_INVALID")
        return verified
    except ApprovalFlowError:
        raise
    except ApprovalReceiptError as error:
        raise ApprovalFlowError(_normalize_approval_receipt_code(error.code)) from None
    except Exception:
        raise ApprovalFlowError("APPROVAL_FLOW_INVALID") from None


def _normalize_approval_receipt_code(code: str) -> str:
    """Map A1 source-codec codes to A2 business source drift at the reverify boundary."""
    if code == "APPROVAL_SOURCE_IDENTITIES_INVALID":
        return "APPROVAL_SOURCE_DRIFT"
    return code


def _prove_approve_challenge(
    challenge: Mapping[str, object], *, now: dt.datetime
) -> dict[str, object]:
    if type(challenge) is not dict:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    required = {
        "action",
        "expires_at",
        "gateway_identity",
        "issued_at",
        "mode",
        "schema_version",
        "source_identities",
        "store_recovery_id",
        "subject_ids",
    }
    if set(challenge) != required:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    if (
        challenge["schema_version"] != _CHALLENGE_SCHEMA
        or challenge["action"] != _APPROVE_ACTION
        or challenge["mode"] != _PAPER_MODE
        or challenge["gateway_identity"] is not None
    ):
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    subject_ids = challenge["subject_ids"]
    if type(subject_ids) is not list or len(subject_ids) != 1:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    plan_identity = _require_hex64(subject_ids[0])
    store_recovery_id = _require_hex64(challenge["store_recovery_id"])
    source_raw = challenge["source_identities"]
    if type(source_raw) is not dict:
        raise ApprovalFlowError("APPROVAL_SOURCE_DRIFT")
    source_identities = normalize_approval_source_identities(
        cast(Mapping[str, str], source_raw)
    )
    # Re-prove digest shape; reject silently-normalized inputs.
    canonical_source_identities_digest(source_identities)
    issued_at = _utc_text(challenge["issued_at"])
    expires_at = _utc_text(challenge["expires_at"])
    issued = require_utc_datetime(issued_at)
    expires = require_utc_datetime(expires_at)
    clock = _require_utc(now)
    if expires <= issued:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    if clock < issued or clock > expires:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_EXPIRED")
    # Re-bucket: issued must be exact 5-minute floor of some UTC instant within window.
    if issued.second != 0 or issued.microsecond != 0 or issued.minute % 5 != 0:
        raise ApprovalFlowError("APPROVAL_CHALLENGE_BUCKET_INVALID")
    if expires != issued + dt.timedelta(minutes=10):
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    canonical = {
        "action": _APPROVE_ACTION,
        "expires_at": expires_at,
        "gateway_identity": None,
        "issued_at": issued_at,
        "mode": _PAPER_MODE,
        "schema_version": _CHALLENGE_SCHEMA,
        "source_identities": source_identities,
        "store_recovery_id": store_recovery_id,
        "subject_ids": [plan_identity],
    }
    if canonical_json_bytes(canonical) != canonical_json_bytes(dict(challenge)):
        raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID")
    challenge_identity = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    return {
        "challenge_identity": challenge_identity,
        "plan_identity": plan_identity,
        "source_identities": source_identities,
        "store_recovery_id": store_recovery_id,
        "issued_at": issued_at,
    }


def _deterministic_nonce(secret: bytes, challenge_identity: str) -> bytes:
    material = _NONCE_DOMAIN + challenge_identity.encode("ascii")
    return hmac.new(secret, material, hashlib.sha256).digest()


def _capability_proof(
    credential_id: str, operator_id: str, session_date: str, secret: bytes
) -> bytes:
    material = (
        _CAPABILITY_PROOF_DOMAIN
        + credential_id.encode("utf-8")
        + b"\x00"
        + operator_id.encode("utf-8")
        + b"\x00"
        + session_date.encode("ascii")
        + b"\x00"
        + secret
    )
    return hmac.new(_CAPABILITY_PROOF_KEY, material, hashlib.sha256).digest()


def _secret_bytes(value: object) -> bytes:
    if type(value) is bytes:
        result = value
    elif type(value) is bytearray:
        result = bytes(value)
    elif type(value) is memoryview:
        result = value.tobytes()
    else:
        raise ApprovalFlowError("APPROVAL_SECRET_INVALID") from None
    if len(result) < MIN_SECRET_BYTES:
        raise ApprovalFlowError("APPROVAL_SECRET_INVALID") from None
    return result


def _require_opaque(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise ApprovalFlowError("APPROVAL_FLOW_INVALID")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ApprovalFlowError("APPROVAL_FLOW_INVALID")
    return value


def _require_hex64(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in _HEX for char in value)
    ):
        raise ApprovalFlowError("APPROVAL_FLOW_INVALID")
    return value


def _session_date_text(value: object) -> str:
    if type(value) is dt.date and type(value) is not dt.datetime:
        return value.isoformat()
    if type(value) is str:
        try:
            return require_date(value).isoformat()
        except Exception:
            pass
    raise ApprovalFlowError("APPROVAL_SESSION_DRIFT") from None


def _utc_text(value: object) -> str:
    if type(value) is str:
        try:
            return utc_datetime_text(require_utc_datetime(value))
        except Exception:
            pass
    raise ApprovalFlowError("APPROVAL_CHALLENGE_INVALID") from None


def _require_utc(value: object) -> dt.datetime:
    if (
        type(value) is not dt.datetime
        or value.tzinfo is None
        or value.utcoffset() != dt.timedelta(0)
    ):
        raise ApprovalFlowError("APPROVAL_CLOCK_INVALID") from None
    return cast(dt.datetime, value)


# Re-export unpack for service-side module proof without leaking secret.
def require_verified_approval_receipt(value: object) -> VerifiedApprovalReceipt:
    """Reject bool/raw/Protocol/subclass forges; return exact verified hand-off."""
    try:
        unpack_verified_approval_receipt(value)
    except ApprovalReceiptError as error:
        raise ApprovalFlowError(error.code) from None
    if type(value) is not VerifiedApprovalReceipt:
        raise ApprovalFlowError("APPROVAL_RECEIPT_NOT_VERIFIED") from None
    return value


__all__ = [
    "ApprovalFlowError",
    "FormalApprovalCredentialCapability",
    "approval_source_identities_from_plan",
    "build_approval_source_identities",
    "build_formal_approval_credential_capability",
    "derivable_approval_source_identities_from_plan",
    "issue_verified_approval_from_approve_challenge",
    "normalize_approval_source_identities",
    "prove_approval_source_binding",
    "require_verified_approval_receipt",
    "reverify_stored_approval_receipt",
    "unpack_formal_approval_credential_capability",
]
