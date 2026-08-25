"""Canonical durable ORDER/CANCEL risk receipt tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

from quant.execution.risk import (
    CancelRiskDecision,
    DailyRiskCounters,
    RiskDecision,
    RiskRuleResult,
)
from quant.execution.risk_wire import (
    GENESIS_RECEIPT_ID,
    RiskReceiptError,
    build_cancel_risk_receipt,
    build_order_risk_receipt,
    decode_risk_receipt,
    encode_risk_receipt,
)


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _counter(*, orders: int = 0, cancels: int = 0) -> DailyRiskCounters:
    return DailyRiskCounters(dt.date(2026, 8, 9), orders, cancels, Decimal("10") * orders)


def _order_receipt():
    decision = RiskDecision(
        accepted=True,
        plan_id=_hex("plan"),
        rule_results=(RiskRuleResult("LIMIT", True, "OK", _hex("plan"), "passed"),),
        approved_intent_ids=(),
        commands=(),
        projected_counters=_counter(orders=1),
        requires_manual_approval=False,
    )
    return build_order_risk_receipt(
        sequence=1,
        previous_receipt_id=GENESIS_RECEIPT_ID,
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(),
        decision=decision,
    )


def test_order_receipt_round_trips_fresh_and_is_canonical() -> None:
    receipt = _order_receipt()
    payload = encode_risk_receipt(receipt)
    assert decode_risk_receipt(payload) == receipt
    assert encode_risk_receipt(decode_risk_receipt(payload)) == payload


@pytest.mark.parametrize("mutation", ["unknown", "identity", "sequence", "duplicate"])
def test_order_receipt_rejects_noncanonical_or_tampered_bytes(mutation: str) -> None:
    payload = encode_risk_receipt(_order_receipt())
    root = json.loads(payload)
    if mutation == "unknown":
        root["unknown"] = "TOKEN /host/path SELECT"
        hostile = json.dumps(root, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "identity":
        root["receipt_id"] = _hex("other")
        hostile = json.dumps(root, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "sequence":
        root["sequence"] = 2
        hostile = json.dumps(root, sort_keys=True, separators=(",", ":")).encode()
    else:
        hostile = payload.replace(b'"sequence":1', b'"sequence":1,"sequence":1')
    with pytest.raises(RiskReceiptError, match="^RISK_RECEIPT_INVALID$") as error:
        decode_risk_receipt(hostile)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "TOKEN" not in repr(error.value)


def test_cancel_receipt_binds_target_policy_and_projected_counter() -> None:
    decision = CancelRiskDecision(
        accepted=True,
        cancel_id=_hex("cancel"),
        code="CANCEL_LIMIT_OK",
        policy_identity=_hex("policy"),
        projected_counters=_counter(orders=1, cancels=1),
    )
    receipt = build_cancel_risk_receipt(
        sequence=2,
        previous_receipt_id=_hex("prior-receipt"),
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(orders=1),
        command_id=_hex("command"),
        decision=decision,
    )
    decoded = decode_risk_receipt(encode_risk_receipt(receipt))
    assert decoded == receipt
    assert decoded.transition_kind == "CANCEL"


def _zero_order_decision(*, plan_id: str | None = None) -> RiskDecision:
    subject = plan_id or _hex("zero-plan")
    return RiskDecision(
        accepted=True,
        plan_id=subject,
        rule_results=(RiskRuleResult("LIMIT", True, "OK", subject, "passed"),),
        approved_intent_ids=(),
        commands=(),
        projected_counters=_counter(),
        requires_manual_approval=False,
    )


def test_encode_execution_stage_matches_risk_and_durable_decision() -> None:
    from quant.execution.risk_wire import (
        DurableOrderRiskDecision,
        encode_execution_stage,
    )

    risk = _zero_order_decision()
    durable = DurableOrderRiskDecision(
        accepted=risk.accepted,
        plan_id=risk.plan_id,
        rule_results=risk.rule_results,
        approved_intent_ids=risk.approved_intent_ids,
        command_ids=(),
        projected_counters=risk.projected_counters,
        requires_manual_approval=risk.requires_manual_approval,
    )
    assert encode_execution_stage(risk) == encode_execution_stage(durable)


def test_verify_risk_closure_default_rejects_zero_order() -> None:
    from quant.execution.risk_wire import (
        GENESIS_RECEIPT_ID,
        RiskReceiptError,
        build_order_risk_receipt,
        verify_risk_receipt_semantic_closure,
    )

    receipt = build_order_risk_receipt(
        sequence=1,
        previous_receipt_id=GENESIS_RECEIPT_ID,
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(),
        decision=_zero_order_decision(),
    )
    with pytest.raises(RiskReceiptError, match="RISK_RECEIPT_CLOSURE_INVALID"):
        verify_risk_receipt_semantic_closure(
            receipts=(receipt,),
            commands=(),
            cancel_commands=(),
        )


def test_verify_risk_closure_allows_exact_zero_order_subject() -> None:
    from quant.execution.risk_wire import (
        GENESIS_RECEIPT_ID,
        RiskReceiptError,
        build_order_risk_receipt,
        verify_risk_receipt_semantic_closure,
    )

    decision = _zero_order_decision()
    receipt = build_order_risk_receipt(
        sequence=1,
        previous_receipt_id=GENESIS_RECEIPT_ID,
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(),
        decision=decision,
    )
    verify_risk_receipt_semantic_closure(
        receipts=(receipt,),
        commands=(),
        cancel_commands=(),
        allowed_zero_order_subject_ids=frozenset({decision.plan_id}),
    )
    with pytest.raises(RiskReceiptError):
        verify_risk_receipt_semantic_closure(
            receipts=(receipt,),
            commands=(),
            cancel_commands=(),
            allowed_zero_order_subject_ids=frozenset(
                {decision.plan_id, _hex("extra-allow")}
            ),
        )
    with pytest.raises(RiskReceiptError):
        verify_risk_receipt_semantic_closure(
            receipts=(receipt,),
            commands=(),
            cancel_commands=(),
            allowed_zero_order_subject_ids=frozenset({_hex("wrong-subject")}),
        )


@pytest.mark.parametrize(
    "mutation",
    ["approved_intents", "requires_manual", "accepted_false"],
)
def test_verify_risk_closure_rejects_illegal_zero_decision(mutation: str) -> None:
    from quant.execution.risk_wire import (
        DurableOrderRiskDecision,
        GENESIS_RECEIPT_ID,
        RiskReceiptError,
        build_order_risk_receipt,
        verify_risk_receipt_semantic_closure,
    )

    base = _zero_order_decision()
    receipt = build_order_risk_receipt(
        sequence=1,
        previous_receipt_id=GENESIS_RECEIPT_ID,
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(),
        decision=base,
    )
    decision = receipt.decision
    assert type(decision) is DurableOrderRiskDecision
    if mutation == "approved_intents":
        hostile = DurableOrderRiskDecision(
            accepted=True,
            plan_id=decision.plan_id,
            rule_results=decision.rule_results,
            approved_intent_ids=(_hex("intent"),),
            command_ids=(),
            projected_counters=decision.projected_counters,
            requires_manual_approval=False,
        )
    elif mutation == "requires_manual":
        hostile = DurableOrderRiskDecision(
            accepted=True,
            plan_id=decision.plan_id,
            rule_results=decision.rule_results,
            approved_intent_ids=(),
            command_ids=(),
            projected_counters=decision.projected_counters,
            requires_manual_approval=True,
        )
    else:
        hostile = DurableOrderRiskDecision(
            accepted=False,
            plan_id=decision.plan_id,
            rule_results=decision.rule_results,
            approved_intent_ids=(),
            command_ids=(),
            projected_counters=decision.projected_counters,
            requires_manual_approval=False,
        )
    # Rebuild receipt body with hostile decision via object surgery on a fresh build.
    mutated = build_order_risk_receipt(
        sequence=1,
        previous_receipt_id=GENESIS_RECEIPT_ID,
        risk_counter_key="paper-account:2026-08-09",
        predecessor_counters=_counter(),
        decision=RiskDecision(
            accepted=hostile.accepted,
            plan_id=hostile.plan_id,
            rule_results=hostile.rule_results,
            approved_intent_ids=hostile.approved_intent_ids,
            commands=(),
            projected_counters=hostile.projected_counters,
            requires_manual_approval=hostile.requires_manual_approval,
        ),
    )
    with pytest.raises(RiskReceiptError):
        verify_risk_receipt_semantic_closure(
            receipts=(mutated,),
            commands=(),
            cancel_commands=(),
            allowed_zero_order_subject_ids=frozenset({hostile.plan_id}),
        )
