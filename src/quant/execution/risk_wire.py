"""Canonical durable ORDER/CANCEL risk-transition receipts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, cast

from quant.domain.canonical_wire import (
    canonical_json_bytes,
    parse_canonical_json_object,
    require_boolean,
    require_decimal,
    require_exact_object,
    require_integer,
    require_string,
)
from quant.execution.risk import (
    CancelRiskDecision,
    DailyRiskCounters,
    RiskDecision,
    RiskRuleResult,
)
from quant.execution.contracts import (
    CancelCommand,
    OrderCommand,
    build_cancel_command_identity,
    build_order_command_identity,
)

RiskTransitionKind = Literal["ORDER", "CANCEL"]
GENESIS_RECEIPT_ID: Final[str] = "0" * 64
_SCHEMA: Final[str] = "m4-risk-transition-receipt-v1"
_COUNTER_SCHEMA: Final[str] = "m4-daily-risk-counters-v1"
_HEX = frozenset("0123456789abcdef")


class RiskReceiptError(ValueError):
    """Stable, detached rejection of an invalid risk receipt."""

    def __init__(self, code: str = "RISK_RECEIPT_INVALID") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DurableOrderRiskDecision:
    """Fresh-decoded ORDER decision without private-plan dependencies."""

    accepted: bool
    plan_id: str
    rule_results: tuple[RiskRuleResult, ...]
    approved_intent_ids: tuple[str, ...]
    command_ids: tuple[str, ...]
    projected_counters: DailyRiskCounters
    requires_manual_approval: bool


@dataclass(frozen=True, slots=True)
class DurableCancelRiskDecision:
    """Fresh-decoded accepted CANCEL decision and target closure."""

    accepted: bool
    cancel_id: str
    command_id: str
    code: str
    policy_identity: str
    projected_counters: DailyRiskCounters


@dataclass(frozen=True, slots=True)
class DurableRiskTransitionReceipt:
    """One verified transition in the global durable risk chain."""

    schema_version: str
    transition_kind: RiskTransitionKind
    sequence: int
    previous_receipt_id: str
    receipt_id: str
    subject_id: str
    risk_counter_key: str
    predecessor_counter_identity: str
    projected_counter_identity: str
    decision_payload_digest: str
    decision: DurableOrderRiskDecision | DurableCancelRiskDecision

    def __post_init__(self) -> None:
        if not _valid_receipt(self):
            raise RiskReceiptError() from None


def counter_payload(value: DailyRiskCounters) -> bytes:
    """Return the exact canonical bytes used by the durable counter row."""
    failed = False
    result = b""
    try:
        if type(value) is not DailyRiskCounters:
            raise ValueError
        result = canonical_json_bytes(
            {"counter": value.to_persistable_dict(), "schema_version": _COUNTER_SCHEMA}
        )
    except Exception:
        failed = True
    if failed:
        raise RiskReceiptError() from None
    return result


def counter_identity(value: DailyRiskCounters) -> str:
    """Return the SHA-256 identity of one canonical counter snapshot."""
    return hashlib.sha256(counter_payload(value)).hexdigest()


def build_order_risk_receipt(
    *,
    sequence: int,
    previous_receipt_id: str,
    risk_counter_key: str,
    predecessor_counters: DailyRiskCounters,
    decision: RiskDecision,
) -> DurableRiskTransitionReceipt:
    """Build an ORDER transition only at the service's fresh staging boundary."""
    failed = False
    result: DurableRiskTransitionReceipt | None = None
    try:
        if type(decision) is not RiskDecision:
            raise ValueError
        durable = DurableOrderRiskDecision(
            accepted=decision.accepted,
            plan_id=decision.plan_id,
            rule_results=decision.rule_results,
            approved_intent_ids=decision.approved_intent_ids,
            command_ids=tuple(item.command_id for item in decision.commands),
            projected_counters=decision.projected_counters,
            requires_manual_approval=decision.requires_manual_approval,
        )
        result = _build(
            kind="ORDER",
            sequence=sequence,
            previous_receipt_id=previous_receipt_id,
            subject_id=decision.plan_id,
            risk_counter_key=risk_counter_key,
            predecessor_counters=predecessor_counters,
            decision=durable,
        )
    except Exception:
        failed = True
    if failed or result is None:
        raise RiskReceiptError() from None
    return result


def build_cancel_risk_receipt(
    *,
    sequence: int,
    previous_receipt_id: str,
    risk_counter_key: str,
    predecessor_counters: DailyRiskCounters,
    command_id: str,
    decision: CancelRiskDecision,
) -> DurableRiskTransitionReceipt:
    """Build an accepted CANCEL transition at the service staging boundary."""
    failed = False
    result: DurableRiskTransitionReceipt | None = None
    try:
        if type(decision) is not CancelRiskDecision or not decision.accepted:
            raise ValueError
        durable = DurableCancelRiskDecision(
            accepted=decision.accepted,
            cancel_id=decision.cancel_id,
            command_id=command_id,
            code=decision.code,
            policy_identity=decision.policy_identity,
            projected_counters=decision.projected_counters,
        )
        result = _build(
            kind="CANCEL",
            sequence=sequence,
            previous_receipt_id=previous_receipt_id,
            subject_id=decision.cancel_id,
            risk_counter_key=risk_counter_key,
            predecessor_counters=predecessor_counters,
            decision=durable,
        )
    except Exception:
        failed = True
    if failed or result is None:
        raise RiskReceiptError() from None
    return result


def encode_risk_receipt(value: DurableRiskTransitionReceipt) -> bytes:
    """Encode one exact, self-identifying canonical receipt."""
    failed = False
    result = b""
    try:
        if type(value) is not DurableRiskTransitionReceipt or not _valid_receipt(value):
            raise ValueError
        body = _receipt_body(value)
        result = canonical_json_bytes({**body, "receipt_id": value.receipt_id})
    except Exception:
        failed = True
    if failed:
        raise RiskReceiptError() from None
    return result


def decode_risk_receipt(payload: bytes) -> DurableRiskTransitionReceipt:
    """Fresh-decode and re-prove one canonical receipt byte-for-byte."""
    failed = False
    result: DurableRiskTransitionReceipt | None = None
    try:
        root = parse_canonical_json_object(payload)
        common = {
            "schema_version", "transition_kind", "sequence", "previous_receipt_id",
            "receipt_id", "subject_id", "risk_counter_key",
            "predecessor_counter_identity", "projected_counter_identity",
            "decision_payload_digest",
        }
        kind = require_string(root.get("transition_kind"))
        decision: DurableOrderRiskDecision | DurableCancelRiskDecision
        if kind == "ORDER":
            exact = require_exact_object(root, common | {"order_decision"})
            decision = _decode_order(exact["order_decision"])
        elif kind == "CANCEL":
            exact = require_exact_object(root, common | {"cancel_decision"})
            decision = _decode_cancel(exact["cancel_decision"])
        else:
            raise ValueError
        result = DurableRiskTransitionReceipt(
            schema_version=cast(str, require_string(exact["schema_version"])),
            transition_kind=cast(RiskTransitionKind, kind),
            sequence=require_integer(exact["sequence"], minimum=1),
            previous_receipt_id=cast(str, require_string(exact["previous_receipt_id"])),
            receipt_id=cast(str, require_string(exact["receipt_id"])),
            subject_id=cast(str, require_string(exact["subject_id"])),
            risk_counter_key=cast(str, require_string(exact["risk_counter_key"])),
            predecessor_counter_identity=cast(
                str, require_string(exact["predecessor_counter_identity"])
            ),
            projected_counter_identity=cast(
                str, require_string(exact["projected_counter_identity"])
            ),
            decision_payload_digest=cast(
                str, require_string(exact["decision_payload_digest"])
            ),
            decision=decision,
        )
        if encode_risk_receipt(result) != payload:
            raise ValueError
    except Exception:
        failed = True
    if failed or result is None:
        raise RiskReceiptError() from None
    return result


def verify_risk_receipt_semantic_closure(
    *,
    receipts: tuple[DurableRiskTransitionReceipt, ...],
    commands: tuple[OrderCommand, ...],
    cancel_commands: tuple[CancelCommand, ...],
) -> None:
    """Prove every retained command/cancel has exactly one semantic receipt owner."""
    failed = False
    try:
        if (
            type(receipts) is not tuple
            or type(commands) is not tuple
            or type(cancel_commands) is not tuple
            or any(type(item) is not DurableRiskTransitionReceipt for item in receipts)
            or any(type(item) is not OrderCommand for item in commands)
            or any(type(item) is not CancelCommand for item in cancel_commands)
        ):
            raise ValueError
        if not commands and not cancel_commands and receipts:
            raise ValueError
        command_map = {item.command_id: item for item in commands}
        cancel_map = {item.cancel_id: item for item in cancel_commands}
        if len(command_map) != len(commands) or len(cancel_map) != len(cancel_commands):
            raise ValueError
        for command in commands:
            if build_order_command_identity(command) != command.command_id:
                raise ValueError
        for cancel in cancel_commands:
            if build_cancel_command_identity(cancel) != cancel.cancel_id:
                raise ValueError
        command_owners = {key: 0 for key in command_map}
        cancel_owners = {key: 0 for key in cancel_map}
        expected_previous = GENESIS_RECEIPT_ID
        per_key_tail: dict[str, str] = {}
        for expected_sequence, receipt in enumerate(receipts, start=1):
            if (
                receipt.sequence != expected_sequence
                or receipt.previous_receipt_id != expected_previous
                or decode_risk_receipt(encode_risk_receipt(receipt)) != receipt
            ):
                raise ValueError
            decision = receipt.decision
            expected_counter = per_key_tail.get(receipt.risk_counter_key)
            if expected_counter is None:
                expected_counter = counter_identity(DailyRiskCounters(
                    session_date=decision.projected_counters.session_date,
                    order_count=0,
                    cancel_count=0,
                    buy_notional=Decimal(0),
                ))
            if receipt.predecessor_counter_identity != expected_counter:
                raise ValueError
            per_key_tail[receipt.risk_counter_key] = receipt.projected_counter_identity
            if receipt.transition_kind == "ORDER":
                if (
                    type(decision) is not DurableOrderRiskDecision
                    or not decision.command_ids
                    or len(decision.command_ids) != len(decision.approved_intent_ids)
                ):
                    raise ValueError
                owned: list[OrderCommand] = []
                for command_id in decision.command_ids:
                    owned_command = command_map.get(command_id)
                    if (
                        owned_command is None
                        or owned_command.intent.plan_id != decision.plan_id
                    ):
                        raise ValueError
                    command_owners[command_id] += 1
                    owned.append(owned_command)
                if tuple(item.intent.intent_id for item in owned) != decision.approved_intent_ids:
                    raise ValueError
            elif receipt.transition_kind == "CANCEL":
                if type(decision) is not DurableCancelRiskDecision:
                    raise ValueError
                owned_cancel = cancel_map.get(decision.cancel_id)
                if (
                    owned_cancel is None
                    or owned_cancel.command_id != decision.command_id
                    or decision.command_id not in command_map
                ):
                    raise ValueError
                cancel_owners[decision.cancel_id] += 1
            else:
                raise ValueError
            expected_previous = receipt.receipt_id
        if any(value != 1 for value in command_owners.values()):
            raise ValueError
        if any(value != 1 for value in cancel_owners.values()):
            raise ValueError
    except Exception:
        failed = True
    if failed:
        raise RiskReceiptError("RISK_RECEIPT_CLOSURE_INVALID") from None


def _build(
    *, kind: RiskTransitionKind, sequence: int, previous_receipt_id: str,
    subject_id: str, risk_counter_key: str,
    predecessor_counters: DailyRiskCounters,
    decision: DurableOrderRiskDecision | DurableCancelRiskDecision,
) -> DurableRiskTransitionReceipt:
    projected = decision.projected_counters
    provisional = DurableRiskTransitionReceipt.__new__(DurableRiskTransitionReceipt)
    values = {
        "schema_version": _SCHEMA, "transition_kind": kind, "sequence": sequence,
        "previous_receipt_id": previous_receipt_id, "subject_id": subject_id,
        "risk_counter_key": risk_counter_key,
        "predecessor_counter_identity": counter_identity(predecessor_counters),
        "projected_counter_identity": counter_identity(projected),
        "decision_payload_digest": hashlib.sha256(
            canonical_json_bytes(_decision_payload(decision))
        ).hexdigest(),
        "decision": decision,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "receipt_id", "f" * 64)
    receipt_id = hashlib.sha256(canonical_json_bytes(_receipt_body(provisional))).hexdigest()
    return DurableRiskTransitionReceipt(receipt_id=receipt_id, **values)  # type: ignore[arg-type]


def _counter_dict(value: DailyRiskCounters) -> dict[str, object]:
    return value.to_persistable_dict()


def _rule_dict(value: RiskRuleResult) -> dict[str, object]:
    return {
        "accepted": value.accepted, "code": value.code, "detail": value.detail,
        "rule": value.rule, "subject": value.subject,
    }


def _decision_payload(
    value: DurableOrderRiskDecision | DurableCancelRiskDecision,
) -> dict[str, object]:
    if type(value) is DurableOrderRiskDecision:
        return {
            "accepted": value.accepted,
            "approved_intent_ids": list(value.approved_intent_ids),
            "command_ids": list(value.command_ids),
            "plan_id": value.plan_id,
            "projected_counters": _counter_dict(value.projected_counters),
            "requires_manual_approval": value.requires_manual_approval,
            "rule_results": [_rule_dict(item) for item in value.rule_results],
        }
    if type(value) is DurableCancelRiskDecision:
        return {
            "accepted": value.accepted, "cancel_id": value.cancel_id,
            "code": value.code, "command_id": value.command_id,
            "policy_identity": value.policy_identity,
            "projected_counters": _counter_dict(value.projected_counters),
        }
    raise ValueError


def _receipt_body(value: DurableRiskTransitionReceipt) -> dict[str, object]:
    result: dict[str, object] = {
        "decision_payload_digest": value.decision_payload_digest,
        "predecessor_counter_identity": value.predecessor_counter_identity,
        "previous_receipt_id": value.previous_receipt_id,
        "projected_counter_identity": value.projected_counter_identity,
        "receipt_id": value.receipt_id,
        "risk_counter_key": value.risk_counter_key,
        "schema_version": value.schema_version,
        "sequence": value.sequence,
        "subject_id": value.subject_id,
        "transition_kind": value.transition_kind,
    }
    result.pop("receipt_id")
    if value.transition_kind == "ORDER":
        result["order_decision"] = _decision_payload(value.decision)
    else:
        result["cancel_decision"] = _decision_payload(value.decision)
    return result


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX


def _valid_counter(value: object) -> bool:
    try:
        return type(value) is DailyRiskCounters and bool(counter_identity(value))
    except Exception:
        return False


def _valid_rule(value: object) -> bool:
    return (
        type(value) is RiskRuleResult and type(value.accepted) is bool
        and all(_text(item) for item in (value.rule, value.code, value.subject, value.detail))
    )


def _valid_receipt(value: DurableRiskTransitionReceipt) -> bool:
    try:
        common = (
            value.schema_version == _SCHEMA
            and value.transition_kind in ("ORDER", "CANCEL")
            and type(value.sequence) is int and value.sequence >= 1
            and _hex64(value.previous_receipt_id) and _hex64(value.receipt_id)
            and _hex64(value.subject_id) and _text(value.risk_counter_key)
            and _hex64(value.predecessor_counter_identity)
            and _hex64(value.projected_counter_identity)
            and _hex64(value.decision_payload_digest)
        )
        if not common:
            return False
        decision = value.decision
        if value.transition_kind == "ORDER":
            if type(decision) is not DurableOrderRiskDecision:
                return False
            rules = decision.rule_results
            ids = decision.approved_intent_ids + decision.command_ids
            valid_decision = (
                type(decision.accepted) is bool and decision.plan_id == value.subject_id
                and type(rules) is tuple and all(_valid_rule(item) for item in rules)
                and len(set(rules)) == len(rules)
                and type(decision.approved_intent_ids) is tuple
                and type(decision.command_ids) is tuple
                and all(_hex64(item) for item in ids)
                and len(set(decision.approved_intent_ids)) == len(decision.approved_intent_ids)
                and len(set(decision.command_ids)) == len(decision.command_ids)
                and len(decision.command_ids) in (0, len(decision.approved_intent_ids))
                and type(decision.requires_manual_approval) is bool
                and _valid_counter(decision.projected_counters)
                and not (decision.command_ids and decision.requires_manual_approval)
                and (not decision.command_ids or decision.accepted)
            )
        else:
            if type(decision) is not DurableCancelRiskDecision:
                return False
            valid_decision = (
                decision.accepted is True and decision.cancel_id == value.subject_id
                and _hex64(decision.command_id) and decision.code == "CANCEL_LIMIT_OK"
                and _hex64(decision.policy_identity)
                and _valid_counter(decision.projected_counters)
            )
        if not valid_decision:
            return False
        payload = _decision_payload(decision)
        return (
            value.projected_counter_identity == counter_identity(decision.projected_counters)
            and value.decision_payload_digest
            == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
            and value.receipt_id
            == hashlib.sha256(canonical_json_bytes(_receipt_body(value))).hexdigest()
        )
    except Exception:
        return False


def _decode_counter(value: object) -> DailyRiskCounters:
    raw = require_exact_object(
        value, {"session_date", "order_count", "cancel_count", "buy_notional"}
    )
    return DailyRiskCounters.from_persistable_dict({
        "session_date": cast(str, require_string(raw["session_date"])),
        "order_count": require_integer(raw["order_count"]),
        "cancel_count": require_integer(raw["cancel_count"]),
        "buy_notional": format(cast(object, require_decimal(raw["buy_notional"])), "f"),
    })


def _decode_order(value: object) -> DurableOrderRiskDecision:
    raw = require_exact_object(value, {
        "accepted", "plan_id", "rule_results", "approved_intent_ids", "command_ids",
        "projected_counters", "requires_manual_approval",
    })
    rule_values = raw["rule_results"]
    approved_values = raw["approved_intent_ids"]
    command_values = raw["command_ids"]
    if type(rule_values) is not list or type(approved_values) is not list or type(command_values) is not list:
        raise ValueError
    rules = []
    for item in rule_values:
        rule = require_exact_object(item, {"accepted", "code", "detail", "rule", "subject"})
        rules.append(RiskRuleResult(
            rule=cast(str, require_string(rule["rule"])),
            accepted=require_boolean(rule["accepted"]),
            code=cast(str, require_string(rule["code"])),
            subject=cast(str, require_string(rule["subject"])),
            detail=cast(str, require_string(rule["detail"])),
        ))
    return DurableOrderRiskDecision(
        accepted=require_boolean(raw["accepted"]),
        plan_id=cast(str, require_string(raw["plan_id"])),
        rule_results=tuple(rules),
        approved_intent_ids=tuple(cast(str, require_string(item)) for item in approved_values),
        command_ids=tuple(cast(str, require_string(item)) for item in command_values),
        projected_counters=_decode_counter(raw["projected_counters"]),
        requires_manual_approval=require_boolean(raw["requires_manual_approval"]),
    )


def _decode_cancel(value: object) -> DurableCancelRiskDecision:
    raw = require_exact_object(value, {
        "accepted", "cancel_id", "code", "command_id", "policy_identity",
        "projected_counters",
    })
    return DurableCancelRiskDecision(
        accepted=require_boolean(raw["accepted"]),
        cancel_id=cast(str, require_string(raw["cancel_id"])),
        command_id=cast(str, require_string(raw["command_id"])),
        code=cast(str, require_string(raw["code"])),
        policy_identity=cast(str, require_string(raw["policy_identity"])),
        projected_counters=_decode_counter(raw["projected_counters"]),
    )


__all__ = [
    "DurableCancelRiskDecision", "DurableOrderRiskDecision",
    "DurableRiskTransitionReceipt", "GENESIS_RECEIPT_ID", "RiskReceiptError",
    "RiskTransitionKind", "build_cancel_risk_receipt", "build_order_risk_receipt",
    "counter_identity", "counter_payload", "decode_risk_receipt", "encode_risk_receipt",
    "verify_risk_receipt_semantic_closure",
]
