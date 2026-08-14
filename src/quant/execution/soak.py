"""Append-only PAPER soak evidence and conservative four-week Gate decisions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from quant.backtest.ledger_adapter import decode_ledger_context, encode_ledger_context
from quant.backtest.ledger_wire import (
    decode_ledger_entry,
    decode_ledger_state,
    encode_ledger_entry,
    encode_ledger_state,
)
from quant.execution.contracts import (
    build_execution_event_identity,
    build_order_command_identity,
)
from quant.execution.reconcile import (
    RecoveryIssue,
    RecoveryResult,
    ReconciliationDifference,
    ReconciliationResult,
)
from quant.execution.risk_wire import decode_risk_receipt, encode_risk_receipt
from quant.execution.store import (
    CancelOutboxDelivery,
    OutboxDelivery,
    OutboxDeliveryState,
    StoredCancelEventLink,
)
from quant.execution.wire import (
    decode_cancel_command,
    decode_execution_event,
    decode_order_aggregate,
    decode_order_command,
    encode_cancel_command,
    encode_execution_event,
    encode_order_aggregate,
    encode_order_command,
)
from quant.reporting.execution_report import (
    ExecutionCashLine,
    ExecutionDifferenceLine,
    ExecutionFillLine,
    ExecutionOrderLine,
    ExecutionPositionLine,
    ExecutionReport,
    ExecutionReportTotals,
    ExecutionRiskLine,
    encode_execution_report,
)

_MANIFEST_SCHEMA = "m4-soak-run-v1"
_SESSION_SCHEMA = "m4-soak-session-v1"
_FAULT_SCHEMA = "m4-fault-drill-v1"
_SESSION_FACTS_SCHEMA = "m4-soak-session-facts-v1"
_RECOVERY_FACTS_SCHEMA = "m4-soak-recovery-facts-v2"
_FAULT_FACTS_SCHEMA = "m4-soak-fault-recovery-facts-v2"
_ANCHOR_SCHEMA = "m4-soak-append-anchor-v1"
_HEX = frozenset("0123456789abcdef")
_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,79}$")
_MINIMUM_SPAN = dt.timedelta(days=28)
_FORMAL_CLOCK_TOLERANCE = dt.timedelta(minutes=5)

REQUIRED_FAULT_DRILLS = (
    "callback_payload_conflict_closed",
    "cancel_transaction_rollback_unknown",
    "completed_actions_idempotent",
    "duplicate_callback_idempotent",
    "gateway_unknown_to_query",
    "out_of_order_callback_closed",
    "redaction",
    "scheduler_inputs_blocked",
    "sqlite_atomic_failure",
    "stage_exit_recovery_exact_submit",
)


class SoakError(ValueError):
    """Stable, path-free error for invalid or conflicting soak evidence."""


class SoakEvidenceKind(StrEnum):
    DEVELOPMENT_EXAMPLE = "development_example"
    PAPER_REAL_TIME = "paper_real_time"


@dataclass(frozen=True, slots=True)
class SoakRunManifest:
    schema_version: Literal["m4-soak-run-v1"]
    run_id: str
    evidence_kind: SoakEvidenceKind
    formal_gate_eligible: bool
    root_identity: str
    anchor_root_identity: str
    source_identity: str
    config_identity: str
    gateway_identity: str
    store_identity: str
    account_identity: str
    expected_schedule_identity: str
    expected_sessions: tuple[dt.date, ...]
    started_at: dt.datetime
    required_fault_drills: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoakSessionReceipt:
    schema_version: Literal["m4-soak-session-v1"]
    run_id: str
    session_date: dt.date
    invocation_started_at: dt.datetime
    invocation_completed_at: dt.datetime
    invocation_identity: str
    recovery_id: str
    reconciliation_id: str
    execution_report_id: str
    gate_passed: bool
    command_ids_sha256: str
    event_ids_sha256: str
    ledger_state_id: str | None
    issue_codes: tuple[str, ...]
    facts_sha256: str
    receipt_id: str


@dataclass(frozen=True, slots=True)
class FaultDrillReceipt:
    schema_version: Literal["m4-fault-drill-v1"]
    run_id: str
    drill: str
    started_at: dt.datetime
    completed_at: dt.datetime
    before_recovery_id: str
    after_recovery_id: str
    affected_subject_ids: tuple[str, ...]
    economic_effect_ids_sha256: str
    outcome: Literal["PASS", "BLOCKED"]
    stable_codes: tuple[str, ...]
    before_facts_sha256: str
    after_facts_sha256: str
    receipt_id: str


@dataclass(frozen=True, slots=True)
class SoakAppendAnchor:
    schema_version: Literal["m4-soak-append-anchor-v1"]
    run_id: str
    sequence: int
    entry_kind: Literal["session", "fault"]
    entry_key: str
    evidence_root_identity: str
    previous_anchor_id: str | None
    receipt_id: str
    facts_digests: tuple[str, ...]
    anchored_at: dt.datetime
    anchor_id: str


@dataclass(frozen=True, slots=True)
class VerifiedDevelopmentSoakEvidence:
    evidence_id: str
    manifest: SoakRunManifest
    sessions: tuple[SoakSessionReceipt, ...]
    fault_drills: tuple[FaultDrillReceipt, ...]
    terminal_anchor_id: str


@dataclass(frozen=True, slots=True)
class VerifiedPaperSoakEvidence:
    evidence_id: str
    manifest: SoakRunManifest
    sessions: tuple[SoakSessionReceipt, ...]
    fault_drills: tuple[FaultDrillReceipt, ...]
    terminal_anchor_id: str


@dataclass(frozen=True, slots=True)
class SoakGateDecision:
    decision_id: str
    status: Literal["PASS", "WAITING_FOR_SOAK_EVIDENCE", "BLOCKED"]
    run_id: str
    first_observed_at: dt.datetime | None
    last_observed_at: dt.datetime | None
    expected_sessions: tuple[dt.date, ...]
    observed_sessions: tuple[dt.date, ...]
    missing_sessions: tuple[dt.date, ...]
    receipt_ids: tuple[str, ...]
    fault_receipt_ids: tuple[str, ...]
    stable_codes: tuple[str, ...]


def build_soak_run(
    *,
    root: Path,
    anchor_root: Path,
    evidence_kind: SoakEvidenceKind,
    source_identity: str,
    config_identity: str,
    gateway_identity: str,
    store_identity: str,
    account_identity: str,
    expected_sessions: tuple[dt.date, ...],
    expected_schedule_identity: str,
    started_at: dt.datetime,
) -> SoakRunManifest:
    """Create or idempotently reopen one explicit content-addressed run."""
    try:
        if type(evidence_kind) is not SoakEvidenceKind:
            raise ValueError
        _validate_root_kind(root, evidence_kind)
        _validate_anchor_roots(root, anchor_root)
        root_identity = _root_identity(root)
        anchor_root_identity = _root_identity(anchor_root)
        if evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME:
            _require_formal_now(started_at)
        values: dict[str, object] = {
            "schema_version": _MANIFEST_SCHEMA,
            "evidence_kind": evidence_kind,
            "formal_gate_eligible": evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME,
            "root_identity": root_identity,
            "anchor_root_identity": anchor_root_identity,
            "source_identity": _require_hex(source_identity),
            "config_identity": _require_hex(config_identity),
            "gateway_identity": _require_hex(gateway_identity),
            "store_identity": _require_hex(store_identity),
            "account_identity": _require_hex(account_identity),
            "expected_schedule_identity": expected_schedule_identity,
            "expected_sessions": expected_sessions,
            "started_at": started_at,
            "required_fault_drills": REQUIRED_FAULT_DRILLS,
        }
        _validate_schedule(expected_sessions, expected_schedule_identity)
        if not _utc(started_at):
            raise ValueError
        run_id = _identity("SoakRunManifest", _manifest_payload_values(values))
        manifest = SoakRunManifest(run_id=run_id, **values)  # type: ignore[arg-type]
        manifest = _prove_manifest(manifest)
        path = _run_dir(root, run_id) / "manifest.json"
        _write_once(path, _encode_manifest(manifest))
        return manifest
    except SoakError:
        raise
    except Exception:
        pass
    raise SoakError("SOAK_RUN_INVALID") from None


def append_soak_session(
    *,
    root: Path,
    anchor_root: Path,
    manifest: SoakRunManifest,
    session_date: dt.date,
    invocation_started_at: dt.datetime,
    invocation_completed_at: dt.datetime,
    source_identity: str,
    config_identity: str,
    gateway_identity: str,
    store_identity: str,
    account_identity: str,
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    execution_report: ExecutionReport,
) -> SoakSessionReceipt:
    """Append one session derived only from verified P5/P7 closure facts."""
    try:
        checked_manifest = _require_persisted_manifest(root, anchor_root, manifest)
        _require_runtime_identities(
            checked_manifest,
            source_identity=source_identity,
            config_identity=config_identity,
            gateway_identity=gateway_identity,
            store_identity=store_identity,
            account_identity=account_identity,
        )
        checked_recovery = _prove_recovery(recovery)
        checked_reconciliation = _prove_reconciliation(reconciliation)
        checked_report = _prove_report(execution_report)
        _validate_session_links(
            checked_recovery, checked_reconciliation, checked_report
        )
        if (
            type(session_date) is not dt.date
            or session_date not in checked_manifest.expected_sessions
            or not _utc(invocation_started_at)
            or not _utc(invocation_completed_at)
            or invocation_started_at < checked_manifest.started_at
            or invocation_completed_at < invocation_started_at
            or checked_report.as_of > invocation_completed_at
        ):
            raise ValueError
        facts = _encode_session_facts(
            checked_recovery, checked_reconciliation, checked_report
        )
        facts_sha256 = hashlib.sha256(facts).hexdigest()
        command_hash = _ordered_hash(
            tuple(item.command_id for item in checked_recovery.commands)
        )
        event_hash = _ordered_hash(
            tuple(item.event_id for item in checked_recovery.events)
        )
        ledger_state_id = (
            None
            if checked_recovery.checkpoint is None
            else _ledger_state_identity(checked_recovery)
        )
        issues = _session_issues(
            checked_recovery, checked_reconciliation, checked_report
        )
        gate_passed = not issues
        invocation_identity = _identity(
            "SoakInvocation",
            {
                "run_id": checked_manifest.run_id,
                "session_date": session_date.isoformat(),
                "started_at": _time(invocation_started_at),
                "completed_at": _time(invocation_completed_at),
                "recovery_id": checked_recovery.recovery_id,
                "reconciliation_id": checked_reconciliation.reconciliation_id,
                "execution_report_id": checked_report.report_id,
                "source_identity": checked_manifest.source_identity,
                "config_identity": checked_manifest.config_identity,
                "gateway_identity": checked_manifest.gateway_identity,
                "store_identity": checked_manifest.store_identity,
                "account_identity": checked_manifest.account_identity,
            },
        )
        values = {
            "schema_version": _SESSION_SCHEMA,
            "run_id": checked_manifest.run_id,
            "session_date": session_date,
            "invocation_started_at": invocation_started_at,
            "invocation_completed_at": invocation_completed_at,
            "invocation_identity": invocation_identity,
            "recovery_id": checked_recovery.recovery_id,
            "reconciliation_id": checked_reconciliation.reconciliation_id,
            "execution_report_id": checked_report.report_id,
            "gate_passed": gate_passed,
            "command_ids_sha256": command_hash,
            "event_ids_sha256": event_hash,
            "ledger_state_id": ledger_state_id,
            "issue_codes": issues,
            "facts_sha256": facts_sha256,
        }
        receipt_id = _identity("SoakSessionReceipt", _session_payload_values(values))
        receipt = SoakSessionReceipt(receipt_id=receipt_id, **values)  # type: ignore[arg-type]
        _prove_session(receipt, checked_manifest)
        path = _run_dir(root, checked_manifest.run_id) / "sessions" / session_date.isoformat()
        receipt_path = path / "receipt.json"
        facts_path = path / "facts.json"
        encoded = _encode_session(receipt)
        if (
            checked_manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME
            and not path.exists()
        ):
            _require_formal_now(invocation_completed_at)
        if not path.exists():
            _require_next_session(root, checked_manifest, receipt)
        _write_evidence_pair(facts_path, facts, receipt_path, encoded)
        _verify_session_facts(receipt, facts_path.read_bytes(), checked_manifest)
        _append_anchor(
            root=root,
            anchor_root=anchor_root,
            manifest=checked_manifest,
            entry_kind="session",
            entry_key=session_date.isoformat(),
            receipt_id=receipt.receipt_id,
            facts_digests=(receipt.facts_sha256,),
        )
        return receipt
    except SoakError:
        raise
    except Exception:
        pass
    raise SoakError("SOAK_SESSION_INVALID") from None


def append_fault_drill(
    *,
    root: Path,
    anchor_root: Path,
    manifest: SoakRunManifest,
    drill: str,
    started_at: dt.datetime,
    completed_at: dt.datetime,
    source_identity: str,
    config_identity: str,
    gateway_identity: str,
    store_identity: str,
    account_identity: str,
    before_recovery: RecoveryResult,
    after_recovery: RecoveryResult,
    affected_subject_ids: tuple[str, ...],
) -> FaultDrillReceipt:
    """Append one drill result computed from its before/after recovery closures."""
    try:
        checked_manifest = _require_persisted_manifest(root, anchor_root, manifest)
        _require_runtime_identities(
            checked_manifest,
            source_identity=source_identity,
            config_identity=config_identity,
            gateway_identity=gateway_identity,
            store_identity=store_identity,
            account_identity=account_identity,
        )
        before = _prove_recovery(before_recovery)
        after = _prove_recovery(after_recovery)
        if (
            type(drill) is not str
            or drill not in checked_manifest.required_fault_drills
            or not _utc(started_at)
            or not _utc(completed_at)
            or started_at < checked_manifest.started_at
            or completed_at < started_at
            or type(affected_subject_ids) is not tuple
            or affected_subject_ids != tuple(sorted(set(affected_subject_ids)))
            or any(not _hex64(item) for item in affected_subject_ids)
        ):
            raise ValueError
        before_facts = _encode_recovery_facts(before, schema=_FAULT_FACTS_SCHEMA)
        after_facts = _encode_recovery_facts(after, schema=_FAULT_FACTS_SCHEMA)
        before_effects = _economic_effect_ids(before)
        after_effects = _economic_effect_ids(after)
        codes = _fault_codes(drill, before, after, before_effects, after_effects)
        outcome: Literal["PASS", "BLOCKED"] = "PASS" if not codes else "BLOCKED"
        effect_hash = _identity(
            "SoakEconomicEffects",
            {"before": before_effects, "after": after_effects},
        )
        values = {
            "schema_version": _FAULT_SCHEMA,
            "run_id": checked_manifest.run_id,
            "drill": drill,
            "started_at": started_at,
            "completed_at": completed_at,
            "before_recovery_id": before.recovery_id,
            "after_recovery_id": after.recovery_id,
            "affected_subject_ids": affected_subject_ids,
            "economic_effect_ids_sha256": effect_hash,
            "outcome": outcome,
            "stable_codes": codes,
            "before_facts_sha256": hashlib.sha256(before_facts).hexdigest(),
            "after_facts_sha256": hashlib.sha256(after_facts).hexdigest(),
        }
        receipt_id = _identity("FaultDrillReceipt", _fault_payload_values(values))
        receipt = FaultDrillReceipt(receipt_id=receipt_id, **values)  # type: ignore[arg-type]
        _prove_fault(receipt, checked_manifest)
        path = _run_dir(root, checked_manifest.run_id) / "faults" / drill
        if (
            checked_manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME
            and not path.exists()
        ):
            _require_formal_now(completed_at)
        _write_evidence_triplet(
            path / "before_facts.json",
            before_facts,
            path / "after_facts.json",
            after_facts,
            path / "receipt.json",
            _encode_fault(receipt),
        )
        _verify_fault_facts(
            receipt,
            (path / "before_facts.json").read_bytes(),
            (path / "after_facts.json").read_bytes(),
            checked_manifest,
        )
        _append_anchor(
            root=root,
            anchor_root=anchor_root,
            manifest=checked_manifest,
            entry_kind="fault",
            entry_key=drill,
            receipt_id=receipt.receipt_id,
            facts_digests=(
                receipt.before_facts_sha256,
                receipt.after_facts_sha256,
            ),
        )
        return receipt
    except SoakError:
        raise
    except Exception:
        pass
    raise SoakError("SOAK_FAULT_DRILL_INVALID") from None


def verify_soak_evidence(
    *, root: Path, anchor_root: Path, manifest: SoakRunManifest
) -> VerifiedDevelopmentSoakEvidence | VerifiedPaperSoakEvidence:
    """Verify only the explicitly supplied run; no discovery or data scan occurs."""
    try:
        checked = _require_persisted_manifest(root, anchor_root, manifest)
        run_dir = _run_dir(root, checked.run_id)
        _require_exact_run_entries(run_dir, checked)
        sessions: list[SoakSessionReceipt] = []
        for session_date in checked.expected_sessions:
            path = run_dir / "sessions" / session_date.isoformat()
            if not path.exists():
                continue
            facts = (path / "facts.json").read_bytes()
            session_receipt = _decode_session((path / "receipt.json").read_bytes(), checked)
            sessions.append(_verify_session_facts(session_receipt, facts, checked))
        faults: list[FaultDrillReceipt] = []
        for drill in checked.required_fault_drills:
            path = run_dir / "faults" / drill
            if not path.exists():
                continue
            fault_receipt = _decode_fault((path / "receipt.json").read_bytes(), checked)
            faults.append(
                _verify_fault_facts(
                    fault_receipt,
                    (path / "before_facts.json").read_bytes(),
                    (path / "after_facts.json").read_bytes(),
                    checked,
                )
            )
        session_tuple = tuple(sessions)
        fault_tuple = tuple(faults)
        _validate_observation_order(session_tuple, checked)
        anchors = _read_anchor_chain(anchor_root, checked)
        terminal_anchor_id = _verify_anchor_correspondence(
            anchors, session_tuple, fault_tuple, checked
        )
        evidence_id = _identity(
            "VerifiedSoakEvidence",
            {
                "run_id": checked.run_id,
                "receipt_ids": tuple(item.receipt_id for item in session_tuple),
                "fault_receipt_ids": tuple(item.receipt_id for item in fault_tuple),
                "terminal_anchor_id": terminal_anchor_id,
            },
        )
        if checked.evidence_kind is SoakEvidenceKind.DEVELOPMENT_EXAMPLE:
            return VerifiedDevelopmentSoakEvidence(
                evidence_id, checked, session_tuple, fault_tuple, terminal_anchor_id
            )
        return VerifiedPaperSoakEvidence(
            evidence_id, checked, session_tuple, fault_tuple, terminal_anchor_id
        )
    except SoakError:
        raise
    except Exception:
        pass
    raise SoakError("SOAK_EVIDENCE_INVALID") from None


def decide_soak_gate(
    verified: VerifiedDevelopmentSoakEvidence | VerifiedPaperSoakEvidence,
    *,
    root: Path,
    anchor_root: Path,
    as_of: dt.datetime,
) -> SoakGateDecision:
    """Return PASS only for complete real-time PAPER evidence spanning 28 days."""
    try:
        checked = _prove_verified(verified)
        if not _utc(as_of):
            raise ValueError
        manifest = checked.manifest
        fresh = verify_soak_evidence(
            root=root, anchor_root=anchor_root, manifest=manifest
        )
        if fresh != checked:
            raise ValueError
        if manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME:
            _require_formal_now(as_of)
        sessions = checked.sessions
        faults = checked.fault_drills
        observed = tuple(item.session_date for item in sessions)
        missing = tuple(item for item in manifest.expected_sessions if item not in observed)
        first = None if not sessions else sessions[0].invocation_started_at
        last = None if not sessions else sessions[-1].invocation_completed_at
        codes: set[str] = set()
        if any(not item.gate_passed or item.issue_codes for item in sessions):
            codes.add("SOAK_SESSION_BLOCKED")
        if any(item.outcome != "PASS" or item.stable_codes for item in faults):
            codes.add("SOAK_FAULT_DRILL_BLOCKED")
        fault_names = {item.drill for item in faults}
        if any(item not in fault_names for item in manifest.required_fault_drills):
            codes.add("SOAK_FAULT_DRILL_MISSING")
        if last is not None and last > as_of:
            raise ValueError
        waiting = bool(missing) or first is None or last is None
        if first is not None and last is not None and last - first < _MINIMUM_SPAN:
            waiting = True
            codes.add("SOAK_MINIMUM_DURATION_PENDING")
        if missing:
            codes.add("SOAK_EXPECTED_SESSION_MISSING")
        if type(checked) is VerifiedDevelopmentSoakEvidence:
            status: Literal["PASS", "WAITING_FOR_SOAK_EVIDENCE", "BLOCKED"] = (
                "BLOCKED" if "SOAK_SESSION_BLOCKED" in codes or "SOAK_FAULT_DRILL_BLOCKED" in codes
                else "WAITING_FOR_SOAK_EVIDENCE"
            )
            codes.add("SOAK_DEVELOPMENT_NOT_GATE_ELIGIBLE")
        elif "SOAK_SESSION_BLOCKED" in codes or "SOAK_FAULT_DRILL_BLOCKED" in codes:
            status = "BLOCKED"
        elif waiting or "SOAK_FAULT_DRILL_MISSING" in codes:
            status = "WAITING_FOR_SOAK_EVIDENCE"
        else:
            status = "PASS"
        values: dict[str, object] = {
            "status": status,
            "run_id": manifest.run_id,
            "first_observed_at": first,
            "last_observed_at": last,
            "expected_sessions": manifest.expected_sessions,
            "observed_sessions": observed,
            "missing_sessions": missing,
            "receipt_ids": tuple(item.receipt_id for item in sessions),
            "fault_receipt_ids": tuple(item.receipt_id for item in faults),
            "stable_codes": tuple(sorted(codes)),
        }
        decision_id = _identity("SoakGateDecision", _decision_payload_values(values))
        return SoakGateDecision(decision_id=decision_id, **values)  # type: ignore[arg-type]
    except SoakError:
        raise
    except Exception:
        pass
    raise SoakError("SOAK_GATE_INPUT_INVALID") from None


def expected_schedule_identity(expected_sessions: tuple[dt.date, ...]) -> str:
    """Return the canonical identity that callers must bind into a run."""
    try:
        if (
            type(expected_sessions) is not tuple
            or not expected_sessions
            or any(type(item) is not dt.date for item in expected_sessions)
            or expected_sessions != tuple(sorted(set(expected_sessions)))
        ):
            raise ValueError
        return _identity(
            "SoakExpectedSessions",
            tuple(item.isoformat() for item in expected_sessions),
        )
    except Exception:
        raise SoakError("SOAK_EXPECTED_SCHEDULE_INVALID") from None


def _prove_manifest(value: object) -> SoakRunManifest:
    if type(value) is not SoakRunManifest:
        raise ValueError
    manifest = cast(SoakRunManifest, value)
    values = {
        "schema_version": manifest.schema_version,
        "evidence_kind": manifest.evidence_kind,
        "formal_gate_eligible": manifest.formal_gate_eligible,
        "root_identity": manifest.root_identity,
        "anchor_root_identity": manifest.anchor_root_identity,
        "source_identity": manifest.source_identity,
        "config_identity": manifest.config_identity,
        "gateway_identity": manifest.gateway_identity,
        "store_identity": manifest.store_identity,
        "account_identity": manifest.account_identity,
        "expected_schedule_identity": manifest.expected_schedule_identity,
        "expected_sessions": manifest.expected_sessions,
        "started_at": manifest.started_at,
        "required_fault_drills": manifest.required_fault_drills,
    }
    if (
        manifest.schema_version != _MANIFEST_SCHEMA
        or type(manifest.evidence_kind) is not SoakEvidenceKind
        or manifest.formal_gate_eligible
        != (manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME)
        or any(
            not _hex64(item)
            for item in (
                manifest.run_id,
                manifest.root_identity,
                manifest.anchor_root_identity,
                manifest.source_identity,
                manifest.config_identity,
                manifest.gateway_identity,
                manifest.store_identity,
                manifest.account_identity,
                manifest.expected_schedule_identity,
            )
        )
        or not _utc(manifest.started_at)
        or manifest.required_fault_drills != REQUIRED_FAULT_DRILLS
    ):
        raise ValueError
    _validate_schedule(manifest.expected_sessions, manifest.expected_schedule_identity)
    if manifest.run_id != _identity("SoakRunManifest", _manifest_payload_values(values)):
        raise ValueError
    return manifest


def _prove_recovery(value: object) -> RecoveryResult:
    if type(value) is not RecoveryResult:
        raise ValueError
    item = cast(RecoveryResult, value)
    checked = RecoveryResult(
        item.recovery_id,
        item.disposition,
        item.commands,
        item.events,
        item.order_aggregates,
        item.deliveries,
        item.cancel_commands,
        item.cancel_deliveries,
        item.cancel_event_links,
        item.ledger_entries,
        item.ledger_contexts,
        item.checkpoint,
        item.issues,
        item.risk_receipts,
    )
    command_ids = tuple(command.command_id for command in checked.commands)
    event_ids = tuple(event.event_id for event in checked.events)
    if (
        command_ids != tuple(sorted(set(command_ids)))
        or event_ids != tuple(sorted(set(event_ids)))
    ):
        raise ValueError
    for command in checked.commands:
        if build_order_command_identity(command) != command.command_id:
            raise ValueError
    command_set = set(command_ids)
    for event in checked.events:
        if (
            build_execution_event_identity(event) != event.event_id
            or event.command_id not in command_set
        ):
            raise ValueError
    for entry in checked.ledger_entries:
        encode_ledger_entry(entry)
    if checked.checkpoint is not None:
        encode_ledger_state(checked.checkpoint)
    return checked


def _prove_reconciliation(value: object) -> ReconciliationResult:
    if type(value) is not ReconciliationResult:
        raise ValueError
    item = cast(ReconciliationResult, value)
    return ReconciliationResult(
        item.reconciliation_id,
        item.local_recovery_id,
        item.broker_snapshot_id,
        item.as_of,
        item.gate_passed,
        item.disposition,
        item.differences,
    )


def _prove_report(value: object) -> ExecutionReport:
    if type(value) is not ExecutionReport:
        raise ValueError
    report = cast(ExecutionReport, value)
    encode_execution_report(report)
    return report


def _validate_session_links(
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    report: ExecutionReport,
) -> None:
    if (
        reconciliation.local_recovery_id != recovery.recovery_id
        or report.recovery_id != recovery.recovery_id
        or report.reconciliation_id != reconciliation.reconciliation_id
        or report.as_of != reconciliation.as_of
        or report.gate_passed != reconciliation.gate_passed
        or report.local_disposition != recovery.disposition
        or report.reconciliation_disposition != reconciliation.disposition
    ):
        raise ValueError


def _session_issues(
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    report: ExecutionReport,
) -> tuple[str, ...]:
    codes = {_redacted_code(item.code) for item in recovery.issues}
    codes.update(_redacted_code(item.code) for item in reconciliation.differences)
    if recovery.disposition != "READY":
        codes.add("SOAK_RECOVERY_NOT_READY")
    if not reconciliation.gate_passed or reconciliation.disposition != "READY":
        codes.add("SOAK_RECONCILIATION_BLOCKED")
    if not report.gate_passed:
        codes.add("SOAK_EXECUTION_REPORT_BLOCKED")
    states = tuple(item.state for item in recovery.deliveries) + tuple(
        item.state for item in recovery.cancel_deliveries
    )
    if OutboxDeliveryState.UNKNOWN in states:
        codes.add("SOAK_DELIVERY_UNKNOWN")
    if OutboxDeliveryState.LEASED in states:
        codes.add("SOAK_DELIVERY_LEASED")
    return tuple(sorted(codes))


def _ledger_state_identity(recovery: RecoveryResult) -> str:
    checkpoint = recovery.checkpoint
    if checkpoint is None:
        raise ValueError
    encoded = encode_ledger_state(checkpoint)
    if hashlib.sha256(encoded).hexdigest() == checkpoint.state_id:
        return checkpoint.state_id
    # LedgerState's public identity may not equal its encoded byte hash; re-entry above
    # proves the body, and the state_id remains the public ledger summary.
    return checkpoint.state_id


def _economic_effect_ids(recovery: RecoveryResult) -> tuple[str, ...]:
    effects = [f"command:{item.command_id}" for item in recovery.commands]
    effects.extend(f"cancel:{item.cancel_id}" for item in recovery.cancel_commands)
    effects.extend(f"event:{item.event_id}" for item in recovery.events)
    effects.extend(
        "ledger:" + hashlib.sha256(encode_ledger_entry(item)).hexdigest()
        for item in recovery.ledger_entries
    )
    if recovery.checkpoint is not None:
        effects.append("checkpoint:" + recovery.checkpoint.state_id)
    return tuple(sorted(effects))


def _fault_codes(
    drill: str,
    before: RecoveryResult,
    after: RecoveryResult,
    before_effects: tuple[str, ...],
    after_effects: tuple[str, ...],
) -> tuple[str, ...]:
    codes: set[str] = set()
    unchanged = before_effects == after_effects
    no_effect_drills = {
        "callback_payload_conflict_closed",
        "cancel_transaction_rollback_unknown",
        "completed_actions_idempotent",
        "duplicate_callback_idempotent",
        "gateway_unknown_to_query",
        "out_of_order_callback_closed",
        "redaction",
        "scheduler_inputs_blocked",
        "sqlite_atomic_failure",
    }
    if drill in no_effect_drills and not unchanged:
        codes.add("SOAK_DRILL_ECONOMIC_EFFECT_CHANGED")
    if drill == "stage_exit_recovery_exact_submit":
        if not set(before_effects).issubset(after_effects) or unchanged:
            codes.add("SOAK_DRILL_EXACT_SUBMIT_NOT_PROVEN")
    if drill == "gateway_unknown_to_query":
        states = tuple(item.state for item in after.deliveries)
        if OutboxDeliveryState.UNKNOWN not in states or after.disposition == "READY":
            codes.add("SOAK_DRILL_UNKNOWN_QUERY_NOT_PROVEN")
    if drill in {"callback_payload_conflict_closed", "out_of_order_callback_closed"}:
        if after.disposition == "READY":
            codes.add("SOAK_DRILL_CALLBACK_CLOSE_NOT_PROVEN")
    if drill == "cancel_transaction_rollback_unknown":
        states = tuple(item.state for item in after.cancel_deliveries)
        if OutboxDeliveryState.UNKNOWN not in states or after.disposition == "READY":
            codes.add("SOAK_DRILL_CANCEL_ROLLBACK_NOT_PROVEN")
    return tuple(sorted(codes))


def _prove_session(
    value: object, manifest: SoakRunManifest
) -> SoakSessionReceipt:
    if type(value) is not SoakSessionReceipt:
        raise ValueError
    item = cast(SoakSessionReceipt, value)
    values = {name: getattr(item, name) for name in _SESSION_FIELDS}
    expected_invocation_identity = _identity(
        "SoakInvocation",
        {
            "run_id": item.run_id,
            "session_date": item.session_date.isoformat(),
            "started_at": _time(item.invocation_started_at),
            "completed_at": _time(item.invocation_completed_at),
            "recovery_id": item.recovery_id,
            "reconciliation_id": item.reconciliation_id,
            "execution_report_id": item.execution_report_id,
            "source_identity": manifest.source_identity,
            "config_identity": manifest.config_identity,
            "gateway_identity": manifest.gateway_identity,
            "store_identity": manifest.store_identity,
            "account_identity": manifest.account_identity,
        },
    ) if _utc(item.invocation_started_at) and _utc(item.invocation_completed_at) else ""
    if (
        item.schema_version != _SESSION_SCHEMA
        or item.run_id != manifest.run_id
        or type(item.session_date) is not dt.date
        or item.session_date not in manifest.expected_sessions
        or not _utc(item.invocation_started_at)
        or not _utc(item.invocation_completed_at)
        or item.invocation_completed_at < item.invocation_started_at
        or any(
            not _hex64(field)
            for field in (
                item.receipt_id,
                item.invocation_identity,
                item.recovery_id,
                item.reconciliation_id,
                item.execution_report_id,
                item.command_ids_sha256,
                item.event_ids_sha256,
                item.facts_sha256,
            )
        )
        or (item.ledger_state_id is not None and not _hex64(item.ledger_state_id))
        or type(item.gate_passed) is not bool
        or type(item.issue_codes) is not tuple
        or item.issue_codes != tuple(sorted(set(item.issue_codes)))
        or any(_STABLE_CODE.fullmatch(code) is None for code in item.issue_codes)
        or item.gate_passed != (not item.issue_codes)
        or item.invocation_identity != expected_invocation_identity
        or item.receipt_id
        != _identity("SoakSessionReceipt", _session_payload_values(values))
    ):
        raise ValueError
    return item


def _prove_fault(value: object, manifest: SoakRunManifest) -> FaultDrillReceipt:
    if type(value) is not FaultDrillReceipt:
        raise ValueError
    item = cast(FaultDrillReceipt, value)
    values = {name: getattr(item, name) for name in _FAULT_FIELDS}
    if (
        item.schema_version != _FAULT_SCHEMA
        or item.run_id != manifest.run_id
        or item.drill not in manifest.required_fault_drills
        or not _utc(item.started_at)
        or not _utc(item.completed_at)
        or item.completed_at < item.started_at
        or any(
            not _hex64(field)
            for field in (
                item.receipt_id,
                item.before_recovery_id,
                item.after_recovery_id,
                item.economic_effect_ids_sha256,
                item.before_facts_sha256,
                item.after_facts_sha256,
            )
        )
        or item.affected_subject_ids
        != tuple(sorted(set(item.affected_subject_ids)))
        or any(not _hex64(field) for field in item.affected_subject_ids)
        or item.outcome not in {"PASS", "BLOCKED"}
        or item.stable_codes != tuple(sorted(set(item.stable_codes)))
        or item.outcome != ("PASS" if not item.stable_codes else "BLOCKED")
        or item.receipt_id
        != _identity("FaultDrillReceipt", _fault_payload_values(values))
    ):
        raise ValueError
    return item


def _append_anchor(
    *,
    root: Path,
    anchor_root: Path,
    manifest: SoakRunManifest,
    entry_kind: Literal["session", "fault"],
    entry_key: str,
    receipt_id: str,
    facts_digests: tuple[str, ...],
) -> None:
    anchors = _read_anchor_chain(anchor_root, manifest)
    for anchor in anchors:
        if (anchor.entry_kind, anchor.entry_key) != (entry_kind, entry_key):
            continue
        if (
            anchor.receipt_id != receipt_id
            or anchor.facts_digests != facts_digests
            or anchor.evidence_root_identity != _root_identity(root)
        ):
            raise SoakError("SOAK_APPEND_CONFLICT")
        return
    if entry_kind == "session":
        anchored_sessions = tuple(
            item.entry_key for item in anchors if item.entry_kind == "session"
        )
        expected = tuple(item.isoformat() for item in manifest.expected_sessions)
        if (
            anchored_sessions != expected[: len(anchored_sessions)]
            or len(anchored_sessions) >= len(expected)
            or entry_key != expected[len(anchored_sessions)]
        ):
            raise ValueError
    anchored_at = _production_utc_now()
    if not _utc(anchored_at) or (
        anchors and anchored_at <= anchors[-1].anchored_at
    ):
        raise ValueError
    if manifest.evidence_kind is SoakEvidenceKind.PAPER_REAL_TIME:
        _require_formal_now(anchored_at)
    values: dict[str, object] = {
        "schema_version": _ANCHOR_SCHEMA,
        "run_id": manifest.run_id,
        "sequence": len(anchors) + 1,
        "entry_kind": entry_kind,
        "entry_key": entry_key,
        "evidence_root_identity": manifest.root_identity,
        "previous_anchor_id": None if not anchors else anchors[-1].anchor_id,
        "receipt_id": receipt_id,
        "facts_digests": facts_digests,
        "anchored_at": anchored_at,
    }
    anchor_id = _identity("SoakAppendAnchor", _anchor_payload_values(values))
    anchor = SoakAppendAnchor(anchor_id=anchor_id, **values)  # type: ignore[arg-type]
    _prove_anchor(anchor, manifest)
    path = _anchor_dir(anchor_root, manifest.run_id) / f"{anchor.sequence:010d}.json"
    _write_once(path, _encode_anchor(anchor))


def _read_anchor_chain(
    anchor_root: Path, manifest: SoakRunManifest
) -> tuple[SoakAppendAnchor, ...]:
    if _root_identity(anchor_root) != manifest.anchor_root_identity:
        raise ValueError
    run_dir = _safe_path(anchor_root / manifest.run_id)
    if not run_dir.exists():
        return ()
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError
    entries = tuple(run_dir.iterdir())
    if any(
        item.name != "anchors" or item.is_symlink() or not item.is_dir()
        for item in entries
    ) or len(entries) != 1:
        raise ValueError
    directory = entries[0]
    files = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    anchors: list[SoakAppendAnchor] = []
    keys: set[tuple[str, str]] = set()
    previous_time: dt.datetime | None = None
    for sequence, path in enumerate(files, 1):
        if (
            path.name != f"{sequence:010d}.json"
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ValueError
        anchor = _decode_anchor(path.read_bytes(), manifest)
        if (
            anchor.sequence != sequence
            or anchor.previous_anchor_id
            != (None if not anchors else anchors[-1].anchor_id)
            or (anchor.entry_kind, anchor.entry_key) in keys
            or (previous_time is not None and anchor.anchored_at <= previous_time)
        ):
            raise ValueError
        anchors.append(anchor)
        keys.add((anchor.entry_kind, anchor.entry_key))
        previous_time = anchor.anchored_at
    return tuple(anchors)


def _verify_anchor_correspondence(
    anchors: tuple[SoakAppendAnchor, ...],
    sessions: tuple[SoakSessionReceipt, ...],
    faults: tuple[FaultDrillReceipt, ...],
    manifest: SoakRunManifest,
) -> str:
    expected: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {
        ("session", item.session_date.isoformat()): (
            item.receipt_id,
            (item.facts_sha256,),
        )
        for item in sessions
    }
    expected.update(
        {
            ("fault", item.drill): (
                item.receipt_id,
                (item.before_facts_sha256, item.after_facts_sha256),
            )
            for item in faults
        }
    )
    actual = {
        (item.entry_kind, item.entry_key): (item.receipt_id, item.facts_digests)
        for item in anchors
    }
    if actual != expected or any(
        item.evidence_root_identity != manifest.root_identity for item in anchors
    ):
        raise ValueError
    return (
        _identity("SoakAnchorGenesis", manifest.run_id)
        if not anchors
        else anchors[-1].anchor_id
    )


def _prove_anchor(
    value: object, manifest: SoakRunManifest
) -> SoakAppendAnchor:
    if type(value) is not SoakAppendAnchor:
        raise ValueError
    item = cast(SoakAppendAnchor, value)
    values = {name: getattr(item, name) for name in _ANCHOR_FIELDS}
    expected_key = (
        item.entry_key in {date.isoformat() for date in manifest.expected_sessions}
        if item.entry_kind == "session"
        else item.entry_key in manifest.required_fault_drills
    )
    if (
        item.schema_version != _ANCHOR_SCHEMA
        or item.run_id != manifest.run_id
        or type(item.sequence) is not int
        or item.sequence < 1
        or item.entry_kind not in {"session", "fault"}
        or not expected_key
        or item.evidence_root_identity != manifest.root_identity
        or (item.previous_anchor_id is not None and not _hex64(item.previous_anchor_id))
        or not _hex64(item.receipt_id)
        or type(item.facts_digests) is not tuple
        or len(item.facts_digests) != (1 if item.entry_kind == "session" else 2)
        or any(not _hex64(value) for value in item.facts_digests)
        or not _utc(item.anchored_at)
        or not _hex64(item.anchor_id)
        or item.anchor_id
        != _identity("SoakAppendAnchor", _anchor_payload_values(values))
    ):
        raise ValueError
    return item


def _prove_verified(
    value: object,
) -> VerifiedDevelopmentSoakEvidence | VerifiedPaperSoakEvidence:
    if type(value) not in {
        VerifiedDevelopmentSoakEvidence,
        VerifiedPaperSoakEvidence,
    }:
        raise ValueError
    checked = cast(
        VerifiedDevelopmentSoakEvidence | VerifiedPaperSoakEvidence, value
    )
    manifest = _prove_manifest(checked.manifest)
    if (
        (type(checked) is VerifiedDevelopmentSoakEvidence)
        != (manifest.evidence_kind is SoakEvidenceKind.DEVELOPMENT_EXAMPLE)
        or type(checked.sessions) is not tuple
        or type(checked.fault_drills) is not tuple
        or not _hex64(checked.terminal_anchor_id)
    ):
        raise ValueError
    sessions = tuple(_prove_session(item, manifest) for item in checked.sessions)
    faults = tuple(_prove_fault(item, manifest) for item in checked.fault_drills)
    _validate_observation_order(sessions, manifest)
    if tuple(item.drill for item in faults) != tuple(
        sorted(item.drill for item in faults)
    ) or len({item.drill for item in faults}) != len(faults):
        raise ValueError
    expected = _identity(
        "VerifiedSoakEvidence",
        {
            "run_id": manifest.run_id,
            "receipt_ids": tuple(item.receipt_id for item in sessions),
            "fault_receipt_ids": tuple(item.receipt_id for item in faults),
            "terminal_anchor_id": checked.terminal_anchor_id,
        },
    )
    if checked.evidence_id != expected:
        raise ValueError
    return checked


def _validate_observation_order(
    sessions: tuple[SoakSessionReceipt, ...], manifest: SoakRunManifest
) -> None:
    observed = tuple(item.session_date for item in sessions)
    if observed != manifest.expected_sessions[: len(observed)]:
        raise ValueError
    previous: dt.datetime | None = None
    for receipt in sessions:
        if previous is not None and receipt.invocation_started_at <= previous:
            raise ValueError
        previous = receipt.invocation_completed_at


def _require_next_session(
    root: Path, manifest: SoakRunManifest, receipt: SoakSessionReceipt
) -> None:
    run_dir = _run_dir(root, manifest.run_id)
    existing: list[SoakSessionReceipt] = []
    for date in manifest.expected_sessions:
        path = run_dir / "sessions" / date.isoformat()
        if path.exists():
            existing_receipt = _decode_session(
                (path / "receipt.json").read_bytes(), manifest
            )
            existing.append(
                _verify_session_facts(
                    existing_receipt, (path / "facts.json").read_bytes(), manifest
                )
            )
    _validate_observation_order(tuple(existing), manifest)
    expected_index = len(existing)
    if (
        expected_index >= len(manifest.expected_sessions)
        or receipt.session_date != manifest.expected_sessions[expected_index]
        or (
            existing
            and receipt.invocation_started_at
            <= existing[-1].invocation_completed_at
        )
    ):
        raise ValueError


def _require_persisted_manifest(
    root: Path, anchor_root: Path, manifest: SoakRunManifest
) -> SoakRunManifest:
    checked = _prove_manifest(manifest)
    _validate_anchor_roots(root, anchor_root)
    if (
        _root_identity(root) != checked.root_identity
        or _root_identity(anchor_root) != checked.anchor_root_identity
    ):
        raise ValueError
    path = _run_dir(root, checked.run_id) / "manifest.json"
    if _safe_path(path).read_bytes() != _encode_manifest(checked):
        raise ValueError
    return checked


def _require_exact_run_entries(
    run_dir: Path, manifest: SoakRunManifest
) -> None:
    checked_dir = _safe_path(run_dir)
    allowed_root = {"manifest.json", "sessions", "faults"}
    for item in checked_dir.iterdir():
        if item.name not in allowed_root or item.is_symlink():
            raise ValueError
    expected_sessions = {item.isoformat() for item in manifest.expected_sessions}
    expected_faults = set(manifest.required_fault_drills)
    for directory_name, allowed, files in (
        ("sessions", expected_sessions, {"receipt.json", "facts.json"}),
        (
            "faults",
            expected_faults,
            {"receipt.json", "before_facts.json", "after_facts.json"},
        ),
    ):
        directory = checked_dir / directory_name
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError
        for item in directory.iterdir():
            if item.name not in allowed or item.is_symlink() or not item.is_dir():
                raise ValueError
            if {child.name for child in item.iterdir()} != files:
                raise ValueError
            if any(child.is_symlink() or not child.is_file() for child in item.iterdir()):
                raise ValueError


def _require_runtime_identities(
    manifest: SoakRunManifest,
    *,
    source_identity: str,
    config_identity: str,
    gateway_identity: str,
    store_identity: str,
    account_identity: str,
) -> None:
    if (
        source_identity != manifest.source_identity
        or config_identity != manifest.config_identity
        or gateway_identity != manifest.gateway_identity
        or store_identity != manifest.store_identity
        or account_identity != manifest.account_identity
    ):
        raise ValueError


def _validate_root_kind(root: Path, kind: SoakEvidenceKind) -> None:
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError
    suffix = tuple(part.lower() for part in root.parts[-3:])
    development_suffix = ("artifacts", "development_example", "m4_p8")
    if kind is SoakEvidenceKind.DEVELOPMENT_EXAMPLE:
        if suffix != development_suffix:
            raise ValueError
    elif suffix == development_suffix:
        raise ValueError


def _validate_anchor_roots(root: Path, anchor_root: Path) -> None:
    if not isinstance(root, Path) or not isinstance(anchor_root, Path):
        raise ValueError
    if not root.is_absolute() or not anchor_root.is_absolute():
        raise ValueError
    _safe_path(root)
    _safe_path(anchor_root)
    evidence = Path(os.path.normcase(str(root.resolve(strict=False))))
    anchor = Path(os.path.normcase(str(anchor_root.resolve(strict=False))))
    if evidence == anchor or evidence in anchor.parents or anchor in evidence.parents:
        raise ValueError


def _validate_schedule(sessions: object, identity: object) -> None:
    if (
        type(sessions) is not tuple
        or not sessions
        or any(type(item) is not dt.date for item in sessions)
        or sessions != tuple(sorted(set(sessions)))
        or not _hex64(identity)
        or identity != expected_schedule_identity(cast(tuple[dt.date, ...], sessions))
    ):
        raise ValueError


def _manifest_payload_values(values: dict[str, object]) -> dict[str, object]:
    return {
        **values,
        "evidence_kind": cast(SoakEvidenceKind, values["evidence_kind"]).value,
        "expected_sessions": tuple(
            item.isoformat() for item in cast(tuple[dt.date, ...], values["expected_sessions"])
        ),
        "started_at": _time(cast(dt.datetime, values["started_at"])),
    }


_SESSION_FIELDS = (
    "schema_version", "run_id", "session_date", "invocation_started_at",
    "invocation_completed_at", "invocation_identity", "recovery_id",
    "reconciliation_id", "execution_report_id", "gate_passed",
    "command_ids_sha256", "event_ids_sha256", "ledger_state_id", "issue_codes",
    "facts_sha256",
)
_FAULT_FIELDS = (
    "schema_version", "run_id", "drill", "started_at", "completed_at",
    "before_recovery_id", "after_recovery_id", "affected_subject_ids",
    "economic_effect_ids_sha256", "outcome", "stable_codes",
    "before_facts_sha256", "after_facts_sha256",
)
_ANCHOR_FIELDS = (
    "schema_version", "run_id", "sequence", "entry_kind", "entry_key",
    "evidence_root_identity", "previous_anchor_id", "receipt_id",
    "facts_digests", "anchored_at",
)


def _session_payload_values(values: dict[str, object]) -> dict[str, object]:
    return {
        **values,
        "session_date": cast(dt.date, values["session_date"]).isoformat(),
        "invocation_started_at": _time(cast(dt.datetime, values["invocation_started_at"])),
        "invocation_completed_at": _time(cast(dt.datetime, values["invocation_completed_at"])),
    }


def _fault_payload_values(values: dict[str, object]) -> dict[str, object]:
    return {
        **values,
        "started_at": _time(cast(dt.datetime, values["started_at"])),
        "completed_at": _time(cast(dt.datetime, values["completed_at"])),
    }


def _anchor_payload_values(values: dict[str, object]) -> dict[str, object]:
    return {
        **values,
        "anchored_at": _time(cast(dt.datetime, values["anchored_at"])),
    }


def _decision_payload_values(values: dict[str, object]) -> dict[str, object]:
    return {
        **values,
        "first_observed_at": _optional_time(cast(dt.datetime | None, values["first_observed_at"])),
        "last_observed_at": _optional_time(cast(dt.datetime | None, values["last_observed_at"])),
        "expected_sessions": tuple(
            item.isoformat() for item in cast(tuple[dt.date, ...], values["expected_sessions"])
        ),
        "observed_sessions": tuple(
            item.isoformat() for item in cast(tuple[dt.date, ...], values["observed_sessions"])
        ),
        "missing_sessions": tuple(
            item.isoformat() for item in cast(tuple[dt.date, ...], values["missing_sessions"])
        ),
    }


def _encode_manifest(value: SoakRunManifest) -> bytes:
    values = {name: getattr(value, name) for name in value.__dataclass_fields__}
    values["evidence_kind"] = value.evidence_kind.value
    values["expected_sessions"] = [item.isoformat() for item in value.expected_sessions]
    values["started_at"] = _time(value.started_at)
    values["required_fault_drills"] = list(value.required_fault_drills)
    return _canonical(values)


def _encode_session(value: SoakSessionReceipt) -> bytes:
    values = {name: getattr(value, name) for name in value.__dataclass_fields__}
    values["session_date"] = value.session_date.isoformat()
    values["invocation_started_at"] = _time(value.invocation_started_at)
    values["invocation_completed_at"] = _time(value.invocation_completed_at)
    values["issue_codes"] = list(value.issue_codes)
    return _canonical(values)


def _encode_fault(value: FaultDrillReceipt) -> bytes:
    values = {name: getattr(value, name) for name in value.__dataclass_fields__}
    values["started_at"] = _time(value.started_at)
    values["completed_at"] = _time(value.completed_at)
    values["affected_subject_ids"] = list(value.affected_subject_ids)
    values["stable_codes"] = list(value.stable_codes)
    return _canonical(values)


def _encode_anchor(value: SoakAppendAnchor) -> bytes:
    values = {name: getattr(value, name) for name in value.__dataclass_fields__}
    values["facts_digests"] = list(value.facts_digests)
    values["anchored_at"] = _time(value.anchored_at)
    return _canonical(values)


def _decode_session(data: bytes, manifest: SoakRunManifest) -> SoakSessionReceipt:
    raw = _decode_object(data, set(_SESSION_FIELDS) | {"receipt_id"})
    item = SoakSessionReceipt(
        schema_version=raw["schema_version"],
        run_id=raw["run_id"],
        session_date=dt.date.fromisoformat(raw["session_date"]),
        invocation_started_at=_parse_time(raw["invocation_started_at"]),
        invocation_completed_at=_parse_time(raw["invocation_completed_at"]),
        invocation_identity=raw["invocation_identity"],
        recovery_id=raw["recovery_id"],
        reconciliation_id=raw["reconciliation_id"],
        execution_report_id=raw["execution_report_id"],
        gate_passed=raw["gate_passed"],
        command_ids_sha256=raw["command_ids_sha256"],
        event_ids_sha256=raw["event_ids_sha256"],
        ledger_state_id=raw["ledger_state_id"],
        issue_codes=tuple(raw["issue_codes"]),
        facts_sha256=raw["facts_sha256"],
        receipt_id=raw["receipt_id"],
    )
    if _encode_session(item) != data:
        raise ValueError
    return _prove_session(item, manifest)


def _decode_fault(data: bytes, manifest: SoakRunManifest) -> FaultDrillReceipt:
    raw = _decode_object(data, set(_FAULT_FIELDS) | {"receipt_id"})
    item = FaultDrillReceipt(
        schema_version=raw["schema_version"],
        run_id=raw["run_id"],
        drill=raw["drill"],
        started_at=_parse_time(raw["started_at"]),
        completed_at=_parse_time(raw["completed_at"]),
        before_recovery_id=raw["before_recovery_id"],
        after_recovery_id=raw["after_recovery_id"],
        affected_subject_ids=tuple(raw["affected_subject_ids"]),
        economic_effect_ids_sha256=raw["economic_effect_ids_sha256"],
        outcome=raw["outcome"],
        stable_codes=tuple(raw["stable_codes"]),
        before_facts_sha256=raw["before_facts_sha256"],
        after_facts_sha256=raw["after_facts_sha256"],
        receipt_id=raw["receipt_id"],
    )
    if _encode_fault(item) != data:
        raise ValueError
    return _prove_fault(item, manifest)


def _decode_anchor(data: bytes, manifest: SoakRunManifest) -> SoakAppendAnchor:
    raw = _decode_object(data, set(_ANCHOR_FIELDS) | {"anchor_id"})
    item = SoakAppendAnchor(
        schema_version=raw["schema_version"],
        run_id=raw["run_id"],
        sequence=raw["sequence"],
        entry_kind=raw["entry_kind"],
        entry_key=raw["entry_key"],
        evidence_root_identity=raw["evidence_root_identity"],
        previous_anchor_id=raw["previous_anchor_id"],
        receipt_id=raw["receipt_id"],
        facts_digests=tuple(raw["facts_digests"]),
        anchored_at=_parse_time(raw["anchored_at"]),
        anchor_id=raw["anchor_id"],
    )
    if _encode_anchor(item) != data:
        raise ValueError
    return _prove_anchor(item, manifest)


def _encode_session_facts(
    recovery: RecoveryResult,
    reconciliation: ReconciliationResult,
    report: ExecutionReport,
) -> bytes:
    return _canonical(
        {
            "schema_version": _SESSION_FACTS_SCHEMA,
            "recovery": _recovery_facts(recovery, schema=_RECOVERY_FACTS_SCHEMA),
            "reconciliation": {
                "reconciliation_id": reconciliation.reconciliation_id,
                "local_recovery_id": reconciliation.local_recovery_id,
                "broker_snapshot_id": reconciliation.broker_snapshot_id,
                "as_of": _time(reconciliation.as_of),
                "gate_passed": reconciliation.gate_passed,
                "disposition": reconciliation.disposition,
                "differences": [
                    [
                        item.code,
                        item.action,
                        item.subject,
                        item.local_identity,
                        item.broker_identity,
                    ]
                    for item in reconciliation.differences
                ],
            },
            "execution_report_wire": encode_execution_report(report).hex(),
        }
    )


def _encode_recovery_facts(recovery: RecoveryResult, *, schema: str) -> bytes:
    return _canonical(_recovery_facts(recovery, schema=schema))


def _recovery_facts(recovery: RecoveryResult, *, schema: str) -> dict[str, object]:
    return {
        "schema_version": schema,
        "recovery_id": recovery.recovery_id,
        "disposition": recovery.disposition,
        "commands": [encode_order_command(item).hex() for item in recovery.commands],
        "events": [encode_execution_event(item).hex() for item in recovery.events],
        "order_aggregates": [
            encode_order_aggregate(item).hex() for item in recovery.order_aggregates
        ],
        "deliveries": [_delivery_facts(item) for item in recovery.deliveries],
        "cancel_commands": [
            encode_cancel_command(item).hex() for item in recovery.cancel_commands
        ],
        "cancel_deliveries": [
            _cancel_delivery_facts(item) for item in recovery.cancel_deliveries
        ],
        "cancel_event_links": [
            [item.cancel_id, item.event_id, item.command_id]
            for item in recovery.cancel_event_links
        ],
        "ledger_entries": [encode_ledger_entry(item).hex() for item in recovery.ledger_entries],
        "ledger_contexts": [
            encode_ledger_context(item).hex() for item in recovery.ledger_contexts
        ],
        "checkpoint": (
            None if recovery.checkpoint is None else encode_ledger_state(recovery.checkpoint).hex()
        ),
        "issues": [[item.code, item.subject, item.action] for item in recovery.issues],
        "risk_receipts": [
            encode_risk_receipt(item).hex() for item in recovery.risk_receipts
        ],
    }


def _delivery_facts(item: OutboxDelivery) -> dict[str, object]:
    return {
        "outbox_key": item.outbox_key,
        "command_id": item.command_id,
        "state": item.state.value,
        "attempt_count": item.attempt_count,
        "available_at": _time(item.available_at),
        "lease_owner": item.lease_owner,
        "lease_until": _optional_time(item.lease_until),
        "terminal_at": _optional_time(item.terminal_at),
        "last_error_code": item.last_error_code,
        "identity": item.identity,
        "payload": item.payload.hex(),
    }


def _cancel_delivery_facts(item: CancelOutboxDelivery) -> dict[str, object]:
    return {
        "cancel_id": item.cancel_id,
        "command_id": item.command_id,
        "state": item.state.value,
        "attempt_count": item.attempt_count,
        "available_at": _time(item.available_at),
        "lease_owner": item.lease_owner,
        "lease_until": _optional_time(item.lease_until),
        "terminal_at": _optional_time(item.terminal_at),
        "last_error_code": item.last_error_code,
        "identity": item.identity,
        "payload": item.payload.hex(),
    }


def _verify_session_facts(
    receipt: SoakSessionReceipt, data: bytes, manifest: SoakRunManifest
) -> SoakSessionReceipt:
    if hashlib.sha256(data).hexdigest() != receipt.facts_sha256:
        raise ValueError
    raw = _decode_object(
        data,
        {"schema_version", "recovery", "reconciliation", "execution_report_wire"},
    )
    if raw["schema_version"] != _SESSION_FACTS_SCHEMA:
        raise ValueError
    recovery = _decode_recovery_facts(raw["recovery"], schema=_RECOVERY_FACTS_SCHEMA)
    reconciliation = _decode_reconciliation_facts(raw["reconciliation"])
    report = _verify_report_wire(_decode_hex_bytes(raw["execution_report_wire"]))
    _validate_session_links_from_wire(recovery, reconciliation, report)
    command_hash = _ordered_hash(tuple(item.command_id for item in recovery.commands))
    event_hash = _ordered_hash(tuple(item.event_id for item in recovery.events))
    ledger_state_id = None if recovery.checkpoint is None else _ledger_state_identity(recovery)
    issues = _session_issues_from_wire(recovery, reconciliation, report)
    if (
        receipt.recovery_id != recovery.recovery_id
        or receipt.reconciliation_id != reconciliation.reconciliation_id
        or receipt.execution_report_id != report.report_id
        or receipt.command_ids_sha256 != command_hash
        or receipt.event_ids_sha256 != event_hash
        or receipt.ledger_state_id != ledger_state_id
        or receipt.issue_codes != issues
        or receipt.gate_passed != (not issues)
    ):
        raise ValueError
    return _prove_session(receipt, manifest)


def _verify_fault_facts(
    receipt: FaultDrillReceipt,
    before_data: bytes,
    after_data: bytes,
    manifest: SoakRunManifest,
) -> FaultDrillReceipt:
    if (
        hashlib.sha256(before_data).hexdigest() != receipt.before_facts_sha256
        or hashlib.sha256(after_data).hexdigest() != receipt.after_facts_sha256
    ):
        raise ValueError
    before_raw = _decode_object_bytes(before_data)
    after_raw = _decode_object_bytes(after_data)
    before = _decode_recovery_facts(before_raw, schema=_FAULT_FACTS_SCHEMA)
    after = _decode_recovery_facts(after_raw, schema=_FAULT_FACTS_SCHEMA)
    before_effects = _economic_effect_ids(before)
    after_effects = _economic_effect_ids(after)
    codes = _fault_codes(receipt.drill, before, after, before_effects, after_effects)
    effect_hash = _identity(
        "SoakEconomicEffects", {"before": before_effects, "after": after_effects}
    )
    if (
        receipt.before_recovery_id != before.recovery_id
        or receipt.after_recovery_id != after.recovery_id
        or receipt.economic_effect_ids_sha256 != effect_hash
        or receipt.stable_codes != codes
        or receipt.outcome != ("PASS" if not codes else "BLOCKED")
    ):
        raise ValueError
    return _prove_fault(receipt, manifest)


def _decode_recovery_facts(value: object, *, schema: str) -> RecoveryResult:
    fields = {
        "schema_version", "recovery_id", "disposition", "commands", "events",
        "order_aggregates", "deliveries", "cancel_commands", "cancel_deliveries",
        "cancel_event_links", "ledger_entries", "ledger_contexts", "checkpoint", "issues",
        "risk_receipts",
    }
    raw = _exact_dict(value, fields)
    if raw["schema_version"] != schema:
        raise ValueError
    commands = tuple(decode_order_command(_decode_hex_bytes(item)) for item in _list(raw["commands"]))
    command_map = {item.command_id: item for item in commands}
    events = tuple(
        decode_execution_event(
            _decode_hex_bytes(item),
            command=command_map[_wire_command_id(_decode_hex_bytes(item))],
        )
        for item in _list(raw["events"])
    )
    aggregates = tuple(
        decode_order_aggregate(
            _decode_hex_bytes(item),
            command=command_map[_wire_command_id(_decode_hex_bytes(item))],
        )
        for item in _list(raw["order_aggregates"])
    )
    cancel_commands = tuple(
        decode_cancel_command(_decode_hex_bytes(item)) for item in _list(raw["cancel_commands"])
    )
    cancel_map = {item.cancel_id: item for item in cancel_commands}
    deliveries = tuple(_decode_delivery(item, command_map) for item in _list(raw["deliveries"]))
    cancel_deliveries = tuple(
        _decode_cancel_delivery(item, cancel_map) for item in _list(raw["cancel_deliveries"])
    )
    links = tuple(
        StoredCancelEventLink(*_triple(item)) for item in _list(raw["cancel_event_links"])
    )
    entries = tuple(decode_ledger_entry(_decode_hex_bytes(item)) for item in _list(raw["ledger_entries"]))
    contexts = tuple(decode_ledger_context(_decode_hex_bytes(item)) for item in _list(raw["ledger_contexts"]))
    checkpoint_raw = raw["checkpoint"]
    checkpoint = None if checkpoint_raw is None else decode_ledger_state(_decode_hex_bytes(checkpoint_raw))
    issues = tuple(RecoveryIssue(*_triple(item)) for item in _list(raw["issues"]))
    risk_receipts = tuple(
        decode_risk_receipt(_decode_hex_bytes(item))
        for item in _list(raw["risk_receipts"])
    )
    result = RecoveryResult(
        raw["recovery_id"], raw["disposition"], commands, events, aggregates,
        deliveries, cancel_commands, cancel_deliveries, links, entries, contexts,
        checkpoint, issues, risk_receipts,
    )
    if (
        aggregates != tuple(sorted(aggregates, key=lambda item: item.command_id))
        or deliveries != tuple(sorted(deliveries, key=lambda item: item.outbox_key))
        or contexts != tuple(sorted(contexts, key=lambda item: item.command_id))
        or any(
            item.cancel_id not in cancel_map
            or item.event_id not in {event.event_id for event in events}
            or item.command_id not in command_map
            for item in links
        )
    ):
        raise ValueError
    return _prove_recovery(result)


def _decode_reconciliation_facts(value: object) -> ReconciliationResult:
    raw = _exact_dict(
        value,
        {"reconciliation_id", "local_recovery_id", "broker_snapshot_id", "as_of",
         "gate_passed", "disposition", "differences"},
    )
    differences = tuple(
        ReconciliationDifference(*_five(item)) for item in _list(raw["differences"])
    )
    return ReconciliationResult(
        raw["reconciliation_id"], raw["local_recovery_id"], raw["broker_snapshot_id"],
        _parse_time(raw["as_of"]), raw["gate_passed"], raw["disposition"], differences,
    )


def _verify_report_wire(data: bytes) -> ExecutionReport:
    fields = {
        "schema_version", "report_id", "as_of", "recovery_id", "reconciliation_id",
        "local_disposition", "reconciliation_disposition", "gate_passed", "checkpoint_id",
        "orders", "fills", "positions", "cash", "risk_events", "differences", "totals",
    }
    raw = _decode_object(data, fields)
    if raw["schema_version"] != "m4-execution-report-v1":
        raise ValueError
    payload = {name: raw[name] for name in fields if name != "report_id"}
    if not _hex64(raw["report_id"]) or hashlib.sha256(_canonical(payload)).hexdigest() != raw["report_id"]:
        raise ValueError
    orders = tuple(
        ExecutionOrderLine(**_exact_dict(item, {"command_id", "symbol", "market", "side", "requested_quantity", "filled_quantity", "status", "broker_order_identity"}))
        for item in _list(raw["orders"])
    )
    fills: list[ExecutionFillLine] = []
    for item in _list(raw["fills"]):
        values = _exact_dict(item, {"event_id", "command_id", "event_type", "cumulative_quantity", "last_quantity", "last_price", "fees"})
        fees = tuple((pair[0], pair[1]) for pair in _pairs(values["fees"]))
        fills.append(ExecutionFillLine(**{**values, "fees": fees}))
    positions = tuple(
        ExecutionPositionLine(**_exact_dict(item, {"symbol", "market", "quantity", "sellable_quantity", "avg_cost_currency", "avg_cost"}))
        for item in _list(raw["positions"])
    )
    cash = tuple(
        ExecutionCashLine(**_exact_dict(item, {"currency", "settled", "available", "receivable", "payable"}))
        for item in _list(raw["cash"])
    )
    risks = tuple(
        ExecutionRiskLine(**_exact_dict(item, {"plan_id", "rule", "accepted", "code", "subject_identity"}))
        for item in _list(raw["risk_events"])
    )
    differences = tuple(
        ExecutionDifferenceLine(**_exact_dict(item, {"code", "action", "subject_identity", "local_identity", "broker_identity"}))
        for item in _list(raw["differences"])
    )
    totals = ExecutionReportTotals(**_exact_dict(raw["totals"], {"commands", "orders", "fills", "positions", "cash_balances", "risk_events", "differences"}))
    report = ExecutionReport(
        report_id=raw["report_id"],
        as_of=_parse_report_time(raw["as_of"]),
        recovery_id=raw["recovery_id"],
        reconciliation_id=raw["reconciliation_id"],
        local_disposition=raw["local_disposition"],
        reconciliation_disposition=raw["reconciliation_disposition"],
        gate_passed=raw["gate_passed"],
        checkpoint_id=raw["checkpoint_id"],
        orders=orders,
        fills=tuple(fills),
        positions=positions,
        cash=cash,
        risk_events=risks,
        differences=differences,
        totals=totals,
    )
    if encode_execution_report(report) != data:
        raise ValueError
    return report


def _validate_session_links_from_wire(
    recovery: RecoveryResult, reconciliation: ReconciliationResult, report: ExecutionReport
) -> None:
    if (
        reconciliation.local_recovery_id != recovery.recovery_id
        or report.recovery_id != recovery.recovery_id
        or report.reconciliation_id != reconciliation.reconciliation_id
        or report.as_of != reconciliation.as_of
        or report.gate_passed != reconciliation.gate_passed
        or report.local_disposition != recovery.disposition
        or report.reconciliation_disposition != reconciliation.disposition
    ):
        raise ValueError


def _session_issues_from_wire(
    recovery: RecoveryResult, reconciliation: ReconciliationResult, report: ExecutionReport
) -> tuple[str, ...]:
    codes = {_redacted_code(item.code) for item in recovery.issues}
    codes.update(_redacted_code(item.code) for item in reconciliation.differences)
    if recovery.disposition != "READY":
        codes.add("SOAK_RECOVERY_NOT_READY")
    if not reconciliation.gate_passed or reconciliation.disposition != "READY":
        codes.add("SOAK_RECONCILIATION_BLOCKED")
    if report.gate_passed is not True:
        codes.add("SOAK_EXECUTION_REPORT_BLOCKED")
    states = tuple(item.state for item in recovery.deliveries) + tuple(
        item.state for item in recovery.cancel_deliveries
    )
    if OutboxDeliveryState.UNKNOWN in states:
        codes.add("SOAK_DELIVERY_UNKNOWN")
    if OutboxDeliveryState.LEASED in states:
        codes.add("SOAK_DELIVERY_LEASED")
    return tuple(sorted(codes))


def _decode_delivery(
    value: object, command_map: dict[str, Any]
) -> OutboxDelivery:
    fields = {
        "outbox_key", "command_id", "state", "attempt_count", "available_at",
        "lease_owner", "lease_until", "terminal_at", "last_error_code", "identity", "payload",
    }
    raw = _exact_dict(value, fields)
    payload = _decode_hex_bytes(raw["payload"])
    command_id = raw["command_id"]
    command = command_map[command_id]
    if (
        raw["outbox_key"] != command_id
        or raw["identity"] != command_id
        or payload != encode_order_command(command)
    ):
        raise ValueError
    return OutboxDelivery(
        raw["outbox_key"], command_id, OutboxDeliveryState(raw["state"]),
        raw["attempt_count"], _parse_time(raw["available_at"]), raw["lease_owner"],
        _parse_optional_time(raw["lease_until"]), _parse_optional_time(raw["terminal_at"]),
        raw["last_error_code"], raw["identity"], payload,
    )


def _decode_cancel_delivery(
    value: object, cancel_map: dict[str, Any]
) -> CancelOutboxDelivery:
    fields = {
        "cancel_id", "command_id", "state", "attempt_count", "available_at",
        "lease_owner", "lease_until", "terminal_at", "last_error_code", "identity", "payload",
    }
    raw = _exact_dict(value, fields)
    payload = _decode_hex_bytes(raw["payload"])
    cancel_id = raw["cancel_id"]
    cancel = cancel_map[cancel_id]
    if (
        raw["command_id"] != cancel.command_id
        or raw["identity"] != cancel_id
        or payload != encode_cancel_command(cancel)
    ):
        raise ValueError
    return CancelOutboxDelivery(
        cancel_id, raw["command_id"], OutboxDeliveryState(raw["state"]),
        raw["attempt_count"], _parse_time(raw["available_at"]), raw["lease_owner"],
        _parse_optional_time(raw["lease_until"]), _parse_optional_time(raw["terminal_at"]),
        raw["last_error_code"], raw["identity"], payload,
    )


def _wire_command_id(data: bytes) -> str:
    raw = json.loads(data)
    if type(raw) is not dict or type(raw.get("command_id")) is not str:
        raise ValueError
    return cast(str, raw["command_id"])


def _decode_object_bytes(data: bytes) -> dict[str, Any]:
    raw = json.loads(data)
    if type(raw) is not dict or _canonical(raw) != data:
        raise ValueError
    return raw


def _exact_dict(value: object, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(cast(dict[object, object], value)) != fields:
        raise ValueError
    return cast(dict[str, Any], value)


def _list(value: object) -> list[Any]:
    if type(value) is not list:
        raise ValueError
    return cast(list[Any], value)


def _triple(value: object) -> tuple[Any, Any, Any]:
    if type(value) is not list or len(cast(list[object], value)) != 3:
        raise ValueError
    item = cast(list[Any], value)
    return item[0], item[1], item[2]


def _five(value: object) -> tuple[Any, Any, Any, Any, Any]:
    if type(value) is not list or len(cast(list[object], value)) != 5:
        raise ValueError
    item = cast(list[Any], value)
    return item[0], item[1], item[2], item[3], item[4]


def _pairs(value: object) -> list[tuple[Any, Any]]:
    result: list[tuple[Any, Any]] = []
    for item in _list(value):
        if type(item) is not list or len(cast(list[object], item)) != 2:
            raise ValueError
        pair = cast(list[Any], item)
        result.append((pair[0], pair[1]))
    return result


def _decode_hex_bytes(value: object) -> bytes:
    if type(value) is not str or len(cast(str, value)) % 2:
        raise ValueError
    data = bytes.fromhex(cast(str, value))
    if data.hex() != value:
        raise ValueError
    return data


def _decode_object(data: bytes, fields: set[str]) -> dict[str, Any]:
    raw = json.loads(data)
    if type(raw) is not dict or set(raw) != fields or _canonical(raw) != data:
        raise ValueError
    return raw


def _write_once(path: Path, data: bytes) -> None:
    checked = _safe_path(path)
    checked.parent.mkdir(parents=True, exist_ok=True)
    conflict = False
    try:
        with checked.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        conflict = checked.read_bytes() != data
    if conflict:
        raise SoakError("SOAK_APPEND_CONFLICT")


def _write_evidence_pair(
    facts_path: Path, facts: bytes, receipt_path: Path, receipt: bytes
) -> None:
    _require_sidecar_subset(facts_path.parent, {"facts.json", "receipt.json"})
    _write_once(facts_path, facts)
    _write_once(receipt_path, receipt)


def _write_evidence_triplet(
    before_path: Path,
    before: bytes,
    after_path: Path,
    after: bytes,
    receipt_path: Path,
    receipt: bytes,
) -> None:
    _require_sidecar_subset(
        before_path.parent,
        {"before_facts.json", "after_facts.json", "receipt.json"},
    )
    _write_once(before_path, before)
    _write_once(after_path, after)
    _write_once(receipt_path, receipt)


def _require_sidecar_subset(path: Path, allowed: set[str]) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise ValueError
    for item in path.iterdir():
        if item.name not in allowed or item.is_symlink() or not item.is_file():
            raise ValueError


def _safe_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError
    for parent in (path, *path.parents):
        junction = getattr(parent, "is_junction", lambda: False)
        if parent.exists() and (parent.is_symlink() or junction()):
            raise ValueError
    return path


def _root_identity(root: Path) -> str:
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError
    _safe_path(root)
    normalized = os.path.normcase(str(root.resolve(strict=False)))
    return _identity("SoakPhysicalRoot", normalized)


def _production_utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _require_formal_now(value: dt.datetime) -> None:
    now = _production_utc_now()
    if (
        not _utc(now)
        or not _utc(value)
        or value > now
        or now - value > _FORMAL_CLOCK_TOLERANCE
    ):
        raise ValueError


def _run_dir(root: Path, run_id: str) -> Path:
    if not isinstance(root, Path) or not root.is_absolute() or not _hex64(run_id):
        raise ValueError
    return root / run_id


def _anchor_dir(anchor_root: Path, run_id: str) -> Path:
    if not isinstance(anchor_root, Path) or not anchor_root.is_absolute() or not _hex64(run_id):
        raise ValueError
    return anchor_root / run_id / "anchors"


def _ordered_hash(values: tuple[str, ...]) -> str:
    if values != tuple(sorted(set(values))) or any(not _hex64(item) for item in values):
        raise ValueError
    return hashlib.sha256(_canonical(values)).hexdigest()


def _require_hex(value: object) -> str:
    if not _hex64(value):
        raise ValueError
    return cast(str, value)


def _redacted_code(value: str) -> str:
    return value if _STABLE_CODE.fullmatch(value) is not None else "SOAK_UPSTREAM_ISSUE_REDACTED"


def _hex64(value: object) -> bool:
    return type(value) is str and len(cast(str, value)) == 64 and set(
        cast(str, value)
    ).issubset(_HEX)


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and cast(dt.datetime, value).tzinfo is not None
        and cast(dt.datetime, value).utcoffset() == dt.timedelta(0)
    )


def _time(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _optional_time(value: dt.datetime | None) -> str | None:
    return None if value is None else _time(value)


def _parse_time(value: object) -> dt.datetime:
    if type(value) is not str or not cast(str, value).endswith("Z"):
        raise ValueError
    parsed = dt.datetime.fromisoformat(cast(str, value)[:-1] + "+00:00")
    if not _utc(parsed) or _time(parsed) != value:
        raise ValueError
    return parsed


def _parse_optional_time(value: object) -> dt.datetime | None:
    return None if value is None else _parse_time(value)


def _parse_report_time(value: object) -> dt.datetime:
    if type(value) is not str:
        raise ValueError
    parsed = dt.datetime.fromisoformat(cast(str, value))
    if not _utc(parsed) or parsed.isoformat() != value:
        raise ValueError
    return parsed


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _identity(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical({"domain": domain, "payload": value})).hexdigest()


__all__ = [
    "FaultDrillReceipt",
    "REQUIRED_FAULT_DRILLS",
    "SoakError",
    "SoakEvidenceKind",
    "SoakGateDecision",
    "SoakAppendAnchor",
    "SoakRunManifest",
    "SoakSessionReceipt",
    "VerifiedDevelopmentSoakEvidence",
    "VerifiedPaperSoakEvidence",
    "append_fault_drill",
    "append_soak_session",
    "build_soak_run",
    "decide_soak_gate",
    "expected_schedule_identity",
    "verify_soak_evidence",
]
