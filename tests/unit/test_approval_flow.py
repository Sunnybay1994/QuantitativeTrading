"""Focused static contract tests for formal approval-flow capability issuance."""

from __future__ import annotations

import copy
import datetime as dt
import pickle
from dataclasses import dataclass

import pytest

from quant.execution.approval import (
    VerifiedApprovalReceipt,
    build_approval_receipt,
    encode_approval_receipt,
    verify_approval_receipt,
    verify_approval_receipt_for_store,
)
from quant.execution.approval_flow import (
    ApprovalFlowError,
    FormalApprovalCredentialCapability,
    approval_source_identities_from_plan,
    build_formal_approval_credential_capability,
    issue_verified_approval_from_approve_challenge,
    reverify_stored_approval_receipt,
    unpack_formal_approval_credential_capability,
)

UTC = dt.timezone.utc
SECRET = b"approval-flow-secret-bytes-01234567"
OTHER_SECRET = b"approval-flow-other-secret-0123456"
OPERATOR = "operator-flow-1"
CREDENTIAL = "credential/flow-key-1"
SESSION = dt.date(2026, 7, 20)
PLAN_ID = "a" * 64
RECOVERY_ID = "b" * 64
NOW = dt.datetime(2026, 7, 20, 8, 3, tzinfo=UTC)


def _sources() -> dict[str, str]:
    return approval_source_identities_from_plan(
        account_snapshot_id="3" * 64,
        market_snapshot_id="2" * 64,
        planner_config_identity="4" * 64,
        target_receipt_identity="6" * 64,
        target_verification_identity="7" * 64,
        trading_config_identity="5" * 64,
    )


def _challenge(**overrides: object) -> dict[str, object]:
    issued = NOW.replace(second=0, microsecond=0, minute=(NOW.minute // 5) * 5)
    expires = issued + dt.timedelta(minutes=10)
    value: dict[str, object] = {
        "action": "approve",
        "expires_at": expires.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "gateway_identity": None,
        "issued_at": issued.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "mode": "PAPER",
        "schema_version": "m4-paper-cli-challenge-v1",
        "source_identities": _sources(),
        "store_recovery_id": RECOVERY_ID,
        "subject_ids": [PLAN_ID],
    }
    value.update(overrides)
    return value


def _capability(*, secret: bytes = SECRET):
    return build_formal_approval_credential_capability(
        secret,
        credential_id=CREDENTIAL,
        operator_id=OPERATOR,
        session_date=SESSION,
    )


def test_capability_factory_rejects_fakes_and_hides_secret() -> None:
    capability = _capability()
    assert "approval-flow-secret" not in repr(capability)
    assert SECRET not in repr(capability).encode("utf-8")
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        FormalApprovalCredentialCapability(  # type: ignore[call-arg]
            credential_id=CREDENTIAL,
            operator_id=OPERATOR,
            session_date=SESSION.isoformat(),
        )
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        unpack_formal_approval_credential_capability(True)
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        unpack_formal_approval_credential_capability(
            build_approval_receipt(
                SECRET,
                credential_id=CREDENTIAL,
                operator_id=OPERATOR,
                session_date=SESSION,
                plan_identity=PLAN_ID,
                challenge_identity="c" * 64,
                store_recovery_identity=RECOVERY_ID,
                source_identities=_sources(),
                issued_at=NOW,
                nonce="n1",
            )
        )


def test_protocol_subclass_and_object_new_capability_rejected() -> None:
    class Fake:
        credential_id = CREDENTIAL
        operator_id = OPERATOR
        session_date = SESSION.isoformat()
        _secret = SECRET
        _proof = b"\x00" * 32

    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        unpack_formal_approval_credential_capability(Fake())

    forged = object.__new__(FormalApprovalCredentialCapability)
    object.__setattr__(forged, "credential_id", CREDENTIAL)
    object.__setattr__(forged, "operator_id", OPERATOR)
    object.__setattr__(forged, "session_date", SESSION.isoformat())
    object.__setattr__(forged, "_secret", SECRET)
    object.__setattr__(forged, "_proof", b"\x00" * 32)
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        unpack_formal_approval_credential_capability(forged)


def test_copy_deepcopy_pickle_capability_fail_closed() -> None:
    capability = _capability()
    with pytest.raises(Exception):
        copy.copy(capability)
    with pytest.raises(Exception):
        copy.deepcopy(capability)
    with pytest.raises(Exception):
        pickle.dumps(capability)


def test_exact_challenge_is_deterministic_and_exact_retry_stable() -> None:
    capability = _capability()
    challenge = _challenge()
    first = issue_verified_approval_from_approve_challenge(
        capability,
        challenge=challenge,
        now=NOW,
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
    )
    second = issue_verified_approval_from_approve_challenge(
        capability,
        challenge=challenge,
        now=NOW,
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
    )
    assert first.payload == second.payload
    assert first.receipt.receipt_id == second.receipt.receipt_id
    assert first.receipt.store_recovery_identity == RECOVERY_ID
    assert SECRET not in first.payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"action": "plan"},
        {"mode": "SHADOW"},
        {"subject_ids": [PLAN_ID, "d" * 64]},
        {"schema_version": "m4-paper-cli-challenge-v0"},
    ],
)
def test_challenge_field_drift_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ApprovalFlowError):
        issue_verified_approval_from_approve_challenge(
            _capability(),
            challenge=_challenge(**overrides),
            now=NOW,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
        )


def test_operator_session_and_expiry_drift_fail_closed() -> None:
    capability = _capability()
    challenge = _challenge()
    with pytest.raises(ApprovalFlowError, match="APPROVAL_OPERATOR_DRIFT"):
        issue_verified_approval_from_approve_challenge(
            capability,
            challenge=challenge,
            now=NOW,
            expected_operator_id="other-operator",
            expected_session_date=SESSION,
        )
    with pytest.raises(ApprovalFlowError, match="APPROVAL_SESSION_DRIFT"):
        issue_verified_approval_from_approve_challenge(
            capability,
            challenge=challenge,
            now=NOW,
            expected_operator_id=OPERATOR,
            expected_session_date=dt.date(2026, 7, 21),
        )
    expired = NOW + dt.timedelta(minutes=30)
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CHALLENGE_EXPIRED"):
        issue_verified_approval_from_approve_challenge(
            capability,
            challenge=challenge,
            now=expired,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
        )


def test_exact_type_guard_rejects_fake_capability_without_getattr() -> None:
    class Guard:
        touched = False

        def __getattr__(self, name: str):
            type(self).touched = True
            raise ApprovalFlowError("APPROVAL_CAPABILITY_INVALID")

    guard = Guard()
    assert Guard.touched is False
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        issue_verified_approval_from_approve_challenge(
            guard,
            challenge=_challenge(),
            now=NOW,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
        )
    assert Guard.touched is False


def test_reverify_source_map_mismatch_normalizes_to_source_drift() -> None:
    capability = _capability()
    verified = issue_verified_approval_from_approve_challenge(
        capability,
        challenge=_challenge(),
        now=NOW,
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
    )
    other_sources = approval_source_identities_from_plan(
        account_snapshot_id="3" * 64,
        market_snapshot_id="2" * 64,
        planner_config_identity="4" * 64,
        target_receipt_identity="8" * 64,
        target_verification_identity="7" * 64,
        trading_config_identity="5" * 64,
    )
    with pytest.raises(ApprovalFlowError, match="APPROVAL_SOURCE_DRIFT") as error:
        reverify_stored_approval_receipt(
            capability,
            payload=verified.payload,
            source_identities=other_sources,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
            expected_plan_identity=PLAN_ID,
        )
    assert error.value.args == ("APPROVAL_SOURCE_DRIFT",)
    assert "IDENTITIES_INVALID" not in repr(error.value)


def test_first_capability_authority_honesty_and_wrong_secret_reverify() -> None:
    capability = _capability()
    verified = issue_verified_approval_from_approve_challenge(
        capability,
        challenge=_challenge(),
        now=NOW,
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
    )
    # Wrong secret cannot re-verify an already sealed receipt.
    with pytest.raises(Exception):
        verify_approval_receipt(verified.payload, OTHER_SECRET)
    with pytest.raises(ApprovalFlowError):
        reverify_stored_approval_receipt(
            _capability(secret=OTHER_SECRET),
            payload=verified.payload,
            source_identities=_sources(),
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
            expected_plan_identity=PLAN_ID,
        )
    # Another first-injected capability is its own authority and may mint a
    # different receipt for the same challenge; that is not a key authenticity Gate.
    other = build_formal_approval_credential_capability(
        OTHER_SECRET,
        credential_id="credential/other-key",
        operator_id=OPERATOR,
        session_date=SESSION,
    )
    other_verified = issue_verified_approval_from_approve_challenge(
        other,
        challenge=_challenge(),
        now=NOW,
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
    )
    assert other_verified.payload != verified.payload
    assert verify_approval_receipt_for_store(
        verified.payload, SECRET, source_identities=_sources()
    ).receipt == verified.receipt
    same = reverify_stored_approval_receipt(
        capability,
        payload=verified.payload,
        source_identities=_sources(),
        expected_operator_id=OPERATOR,
        expected_session_date=SESSION,
        expected_plan_identity=PLAN_ID,
    )
    assert same.payload == verified.payload
    assert same.receipt.receipt_id == verified.receipt.receipt_id


def test_approval_source_map_requires_target_receipt_and_verification_keys() -> None:
    sources = _sources()
    assert set(sources) == {
        "account_snapshot_id",
        "market_snapshot_id",
        "planner_config_identity",
        "target_receipt_identity",
        "target_verification_identity",
        "trading_config_identity",
    }
    weak = {
        "account_snapshot_id": "3" * 64,
        "market_snapshot_id": "2" * 64,
        "planner_config_identity": "4" * 64,
        "target_identity": "1" * 64,
        "trading_config_identity": "5" * 64,
    }
    with pytest.raises(ApprovalFlowError, match="APPROVAL_SOURCE_DRIFT"):
        issue_verified_approval_from_approve_challenge(
            _capability(),
            challenge=_challenge(source_identities=weak),
            now=NOW,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
        )
    drifted_receipt = dict(sources)
    drifted_receipt["target_receipt_identity"] = "8" * 64
    with pytest.raises(ApprovalFlowError, match="APPROVAL_SOURCE_DRIFT"):
        reverify_stored_approval_receipt(
            _capability(),
            payload=issue_verified_approval_from_approve_challenge(
                _capability(),
                challenge=_challenge(),
                now=NOW,
                expected_operator_id=OPERATOR,
                expected_session_date=SESSION,
            ).payload,
            source_identities=drifted_receipt,
            expected_operator_id=OPERATOR,
            expected_session_date=SESSION,
            expected_plan_identity=PLAN_ID,
        )


def test_raw_receipt_bool_and_verified_init_rejected_as_capability() -> None:
    raw = build_approval_receipt(
        SECRET,
        credential_id=CREDENTIAL,
        operator_id=OPERATOR,
        session_date=SESSION,
        plan_identity=PLAN_ID,
        challenge_identity="c" * 64,
        store_recovery_identity=RECOVERY_ID,
        source_identities=_sources(),
        issued_at=NOW,
        nonce="nonce-raw",
    )
    with pytest.raises(ApprovalFlowError):
        unpack_formal_approval_credential_capability(raw)
    with pytest.raises(ApprovalFlowError):
        unpack_formal_approval_credential_capability(encode_approval_receipt(raw))
    with pytest.raises(Exception):
        VerifiedApprovalReceipt(raw, encode_approval_receipt(raw))


@dataclass(frozen=True, slots=True)
class _ProtoLike:
    credential_id: str
    operator_id: str
    session_date: str


def test_dataclass_protocol_like_capability_rejected() -> None:
    with pytest.raises(ApprovalFlowError, match="APPROVAL_CAPABILITY_INVALID"):
        unpack_formal_approval_credential_capability(
            _ProtoLike(CREDENTIAL, OPERATOR, SESSION.isoformat())
        )
