"""Terminal-closure-driven single-session closure for the Windows PAPER soak track.

Consumes the same formal ``FORMAL_CLOSURE_ONLY`` closure capability B1B1
issued on OPEN→CLOSING to drive the durable terminal step sequence: broker
finality → OMS fresh recovery/reconciliation → report/soak evidence →
terminal successor → CLOSING→CLOSED. The B1 barrier anchored lock (held via
``VerifiedFormalPaperClosureView.hold_terminal_closure``) is the only
serialization authority; this module does not acquire a second lock layer.

The two SQLite stores (OMS, broker) are not one atomic transaction. Each
durable step carries a canonical, content-addressed identity referencing its
predecessor; same-token resume fresh-verifies existing steps from durable
facts (broker marker, OMS recovery/reconciliation recomputation, persisted
soak receipt) and only appends the next missing step. Highest claim remains
Windows engineering validation; no PAPER/soak/Gate claim is made here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from quant.domain.canonical_wire import canonical_json_bytes
from quant.execution.paper_formal_broker_snapshot import (
    finalize_and_query_formal_paper_broker_eod,
)
from quant.execution.paper_formal_execution_store import FormalPaperExecutionStoreError
from quant.execution.paper_formal_schedule import (
    VerifiedFormalPaperSoakSchedule,
    verify_existing_formal_paper_soak_schedule,
)
from quant.execution.paper_formal_service import (
    VerifiedFormalPaperClosureView,
    VerifiedFormalPaperServiceComposition,
    open_formal_paper_closure_view,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
)
from quant.execution.reconcile import (
    RecoveryResult,
    ReconciliationResult,
    build_broker_snapshot,
    reconcile,
)
from quant.execution.session_barrier import (
    SessionBarrierRow,
    compute_terminal_step_identity,
    compute_terminal_successor_identity,
)
from quant.execution.soak import (
    SoakGateDecision,
    SoakRunManifest,
    SoakSessionReceipt,
    SoakEvidenceKind,
    VerifiedPaperSoakEvidence,
    append_soak_session,
    build_soak_run,
    decide_soak_gate,
    session_order_semantic_closure_identity,
    verify_soak_evidence,
)


class SessionReportPort(Protocol):
    """Narrow boundary implemented by the reporting layer."""

    def build(
        self,
        *,
        recovery: RecoveryResult,
        reconciliation: ReconciliationResult,
        as_of: dt.datetime,
    ) -> object: ...


class FormalPaperSoakSessionError(ValueError):
    """Stable, sanitized single-session closure failure."""

    def __init__(self) -> None:
        self.code = "PAPER_SOAK_SESSION_INVALID"
        super().__init__(self.code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class FormalPaperSoakSessionResult:
    """Exact fresh result for one appended, resumed, or replayed session."""

    manifest: SoakRunManifest
    session_receipt: SoakSessionReceipt
    evidence: VerifiedPaperSoakEvidence
    decision: SoakGateDecision
    replayed: bool
    closed_row: object | None = None
    terminal_successor_identity: str | None = None


def close_formal_paper_soak_session(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    schedule: VerifiedFormalPaperSoakSchedule,
    session_date: dt.date,
    now: dt.datetime,
    report_port: SessionReportPort,
    closure: object,
) -> FormalPaperSoakSessionResult:
    """Close (or resume/replay) one exact Windows PAPER session.

    ``closure`` must be a live formal ``SessionBarrierClosureCapability``
    matching the composition's own barrier. Serialization is exclusively the
    B1 anchored lock held for the durable terminal step sequence; there is no
    second lock layer here. Soak evidence ``before``/existing receipt bytes are
    only read under that lock.
    """
    try:
        if (
            type(environment) is not VerifiedPaperRuntimeEnvironment
            or type(policy) is not VerifiedPaperExecutionPolicy
            or type(composition) is not VerifiedFormalPaperServiceComposition
            or type(schedule) is not VerifiedFormalPaperSoakSchedule
            or type(session_date) is not dt.date
            or not _utc(now)
            or not callable(getattr(report_port, "build", None))
            or closure is None
        ):
            raise ValueError

        verify_existing_paper_runtime_preflight(
            environment,
            config_path=environment.config.source_path,
            now=now,
        )
        view = _verified_view(
            environment=environment,
            policy=policy,
            composition=composition,
            schedule=schedule,
            session_date=session_date,
            now=now,
        )
        config = environment.config
        manifest = build_soak_run(
            root=config.evidence_root,
            anchor_root=config.anchor_root,
            evidence_kind=SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS,
            source_identity=schedule.schedule_identity,
            config_identity=config.config_identity,
            gateway_identity=view.gateway_identity,
            store_identity=view.execution_store_identity,
            account_identity=view.account_id,
            expected_sessions=schedule.expected_sessions,
            expected_schedule_identity=schedule.expected_schedule_identity,
            started_at=schedule.readiness_completed_at,
        )

        try:
            with view.hold_terminal_closure(closure) as context:
                before = _verified_windows_evidence(
                    root=config.evidence_root,
                    anchor_root=config.anchor_root,
                    manifest=manifest,
                )
                existing = _session_receipt(before, session_date)
                missing = tuple(
                    item
                    for item in schedule.expected_sessions
                    if item not in {receipt.session_date for receipt in before.sessions}
                )
                if existing is None and (not missing or missing[0] != session_date):
                    raise ValueError
                return _run_terminal_sequence(
                    view=view,
                    context=context,
                    closure=closure,
                    manifest=manifest,
                    before=before,
                    existing=existing,
                    session_date=session_date,
                    now=now,
                    report_port=report_port,
                    config_evidence_root=config.evidence_root,
                    config_anchor_root=config.anchor_root,
                )
        except FormalPaperExecutionStoreError as exc:
            if str(exc) != "BARRIER_STATE_CLOSED":
                raise
            return _replay_closed(
                view=view,
                closure=closure,
                manifest=manifest,
                session_date=session_date,
                now=now,
                config_evidence_root=config.evidence_root,
                config_anchor_root=config.anchor_root,
            )
    except FormalPaperSoakSessionError:
        raise
    except Exception:
        pass
    raise FormalPaperSoakSessionError() from None


def _run_terminal_sequence(
    *,
    view: VerifiedFormalPaperClosureView,
    context: object,
    closure: object,
    manifest: SoakRunManifest,
    before: VerifiedPaperSoakEvidence,
    existing: SoakSessionReceipt | None,
    session_date: dt.date,
    now: dt.datetime,
    report_port: SessionReportPort,
    config_evidence_root: Path,
    config_anchor_root: Path,
) -> FormalPaperSoakSessionResult:
    close_token_identity = _closure_field(closure, "close_token_identity")
    closing_row_identity = _closure_field(closure, "closing_row_identity")
    closure_identity = _closure_field(closure, "closure_identity")

    # Step 1: broker EOD finality. Preliminary OMS recovery is computed inside
    # the formal view (rollback-only inspect); caller only receives RecoveryResult.
    with view.hold_terminal_step(context, step_kind="broker_finality") as child:
        pre_recovery = view.recover_oms_under_terminal_child(
            terminal_child=child, step_kind="broker_finality"
        )
        pre_closure_identity = session_order_semantic_closure_identity(
            pre_recovery, session_date=session_date
        )
        broker_marker = view.broker_store.store.read_session_finality(
            session_date=session_date
        )
        if existing is not None and broker_marker is None:
            raise ValueError
        broker_evidence = finalize_and_query_formal_paper_broker_eod(
            store_capability=view.broker_store,
            environment=view.environment,
            policy=view.policy,
            binding=view.binding,
            account=view.account,
            session_date=session_date,
            now=now,
            gateway_identity=view.gateway_identity,
            order_semantic_closure_identity=pre_closure_identity,
        )
        step1_identity = compute_terminal_step_identity(
            step_kind="broker_finality",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=None,
            fact_identity=broker_evidence.source_identity,
        )

    # Step 2: fresh OMS recovery + ORDER semantic closure (committing OMS
    # transaction stays inside the formal view; only RecoveryResult returns).
    with view.hold_terminal_step(context, step_kind="oms_recovery") as child:
        fresh_recovery = view.recover_oms_under_terminal_child(
            terminal_child=child, step_kind="oms_recovery"
        )
        fresh_closure_identity = session_order_semantic_closure_identity(
            fresh_recovery, session_date=session_date
        )
        if (
            fresh_recovery.recovery_id != pre_recovery.recovery_id
            or fresh_closure_identity != pre_closure_identity
        ):
            raise ValueError
        if existing is not None and existing.recovery_id != fresh_recovery.recovery_id:
            raise ValueError
        step2_identity = compute_terminal_step_identity(
            step_kind="oms_recovery",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step1_identity,
            fact_identity=_hex(
                {
                    "recovery_id": fresh_recovery.recovery_id,
                    "order_semantic_closure_identity": fresh_closure_identity,
                }
            ),
        )

    # Step 3: broker snapshot + reconciliation (pure computation).
    with view.hold_terminal_step(context, step_kind="reconciliation"):
        broker_snapshot = build_broker_snapshot(
            source_identity=broker_evidence.source_identity,
            as_of=broker_evidence.as_of,
            finality=broker_evidence.finality,
            account=broker_evidence.account,
            orders=broker_evidence.orders,
            events=broker_evidence.events,
        )
        reconciliation = reconcile(fresh_recovery, broker_snapshot, broker_evidence.as_of)
        if (
            existing is not None
            and existing.reconciliation_id != reconciliation.reconciliation_id
        ):
            raise ValueError
        step3_identity = compute_terminal_step_identity(
            step_kind="reconciliation",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step2_identity,
            fact_identity=reconciliation.reconciliation_id,
        )

    # Step 4: report + soak evidence append. Fresh re-verify under the same
    # barrier lock before and after any append; lock-out snapshots are refused.
    with view.hold_terminal_step(context, step_kind="report_soak"):
        locked_before = _verified_windows_evidence(
            root=config_evidence_root,
            anchor_root=config_anchor_root,
            manifest=manifest,
        )
        if locked_before != before:
            raise ValueError
        locked_existing = _session_receipt(locked_before, session_date)
        if locked_existing != existing:
            raise ValueError
        if locked_existing is not None:
            receipt = locked_existing
            evidence = locked_before
        else:
            report = report_port.build(
                recovery=fresh_recovery,
                reconciliation=reconciliation,
                as_of=broker_evidence.as_of,
            )
            receipt = append_soak_session(
                root=config_evidence_root,
                anchor_root=config_anchor_root,
                manifest=manifest,
                session_date=session_date,
                invocation_started_at=now,
                invocation_completed_at=now,
                source_identity=manifest.source_identity,
                config_identity=manifest.config_identity,
                gateway_identity=manifest.gateway_identity,
                store_identity=manifest.store_identity,
                account_identity=manifest.account_identity,
                recovery=fresh_recovery,
                reconciliation=reconciliation,
                execution_report=cast(Any, report),
            )
            evidence = _verified_windows_evidence(
                root=config_evidence_root,
                anchor_root=config_anchor_root,
                manifest=manifest,
            )
            if _session_receipt(evidence, session_date) != receipt:
                raise ValueError
        step4_identity = compute_terminal_step_identity(
            step_kind="report_soak",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step3_identity,
            fact_identity=receipt.receipt_id,
        )

    # Step 5: terminal successor identity binding the full durable chain.
    with view.hold_terminal_step(context, step_kind="terminal_successor"):
        terminal_successor_identity = compute_terminal_successor_identity(
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            closure_identity=closure_identity,
            broker_finality_step_identity=step1_identity,
            oms_recovery_step_identity=step2_identity,
            reconciliation_step_identity=step3_identity,
            report_soak_step_identity=step4_identity,
        )
        view.bind_terminal_successor(
            context, terminal_successor_identity=terminal_successor_identity
        )

    # Step 6: exact CLOSING → CLOSED under the terminal successor identity.
    with view.hold_terminal_step(context, step_kind="closing_to_closed"):
        closed_row = view.transition_to_closed(
            closure=closure,
            terminal_successor_identity=terminal_successor_identity,
            now=now,
        )

    decision = _fresh_decision(
        evidence=evidence,
        root=config_evidence_root,
        anchor_root=config_anchor_root,
        now=now,
    )
    return FormalPaperSoakSessionResult(
        manifest,
        receipt,
        evidence,
        decision,
        existing is not None,
        closed_row=closed_row,
        terminal_successor_identity=terminal_successor_identity,
    )


def _replay_closed(
    *,
    view: VerifiedFormalPaperClosureView,
    closure: object,
    manifest: SoakRunManifest,
    session_date: dt.date,
    now: dt.datetime,
    config_evidence_root: Path,
    config_anchor_root: Path,
) -> FormalPaperSoakSessionResult:
    """Zero-write verify-only replay after the barrier is already CLOSED.

    Fresh-reads the persisted terminal successor and recomputes the full durable
    chain while the anchored barrier lock is held. Legal replay never returns
    ``None`` for the successor; missing/tamper/drift fail closed.
    """
    close_token_identity = _closure_field(closure, "close_token_identity")
    closing_row_identity = _closure_field(closure, "closing_row_identity")
    closure_identity = _closure_field(closure, "closure_identity")

    with view.recover_oms_when_barrier_closed() as (fresh_recovery, closed_row):
        if type(closed_row) is not SessionBarrierRow:
            raise ValueError
        if (
            closed_row.state != "CLOSED"
            or closed_row.close_token_identity != close_token_identity
        ):
            raise ValueError
        persisted_successor = closed_row.terminal_successor_identity
        if type(persisted_successor) is not str or len(persisted_successor) != 64:
            raise ValueError

        before = _verified_windows_evidence(
            root=config_evidence_root,
            anchor_root=config_anchor_root,
            manifest=manifest,
        )
        existing = _session_receipt(before, session_date)
        if existing is None:
            raise ValueError

        if existing.recovery_id != fresh_recovery.recovery_id:
            raise ValueError
        fresh_closure_identity = session_order_semantic_closure_identity(
            fresh_recovery, session_date=session_date
        )
        broker_evidence = finalize_and_query_formal_paper_broker_eod(
            store_capability=view.broker_store,
            environment=view.environment,
            policy=view.policy,
            binding=view.binding,
            account=view.account,
            session_date=session_date,
            now=now,
            gateway_identity=view.gateway_identity,
            order_semantic_closure_identity=fresh_closure_identity,
        )
        step1_identity = compute_terminal_step_identity(
            step_kind="broker_finality",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=None,
            fact_identity=broker_evidence.source_identity,
        )
        step2_identity = compute_terminal_step_identity(
            step_kind="oms_recovery",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step1_identity,
            fact_identity=_hex(
                {
                    "recovery_id": fresh_recovery.recovery_id,
                    "order_semantic_closure_identity": fresh_closure_identity,
                }
            ),
        )
        broker_snapshot = build_broker_snapshot(
            source_identity=broker_evidence.source_identity,
            as_of=broker_evidence.as_of,
            finality=broker_evidence.finality,
            account=broker_evidence.account,
            orders=broker_evidence.orders,
            events=broker_evidence.events,
        )
        reconciliation = reconcile(
            fresh_recovery, broker_snapshot, broker_evidence.as_of
        )
        if existing.reconciliation_id != reconciliation.reconciliation_id:
            raise ValueError
        step3_identity = compute_terminal_step_identity(
            step_kind="reconciliation",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step2_identity,
            fact_identity=reconciliation.reconciliation_id,
        )
        locked_evidence = _verified_windows_evidence(
            root=config_evidence_root,
            anchor_root=config_anchor_root,
            manifest=manifest,
        )
        if locked_evidence != before:
            raise ValueError
        locked_receipt = _session_receipt(locked_evidence, session_date)
        if locked_receipt != existing:
            raise ValueError
        step4_identity = compute_terminal_step_identity(
            step_kind="report_soak",
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            predecessor_step_identity=step3_identity,
            fact_identity=existing.receipt_id,
        )
        recomputed = compute_terminal_successor_identity(
            close_token_identity=close_token_identity,
            closing_row_identity=closing_row_identity,
            closure_identity=closure_identity,
            broker_finality_step_identity=step1_identity,
            oms_recovery_step_identity=step2_identity,
            reconciliation_step_identity=step3_identity,
            report_soak_step_identity=step4_identity,
        )
        if recomputed != persisted_successor:
            raise ValueError

        decision = _fresh_decision(
            evidence=before,
            root=config_evidence_root,
            anchor_root=config_anchor_root,
            now=now,
        )
        return FormalPaperSoakSessionResult(
            manifest,
            existing,
            before,
            decision,
            True,
            closed_row=closed_row,
            terminal_successor_identity=persisted_successor,
        )


def _verified_view(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    composition: VerifiedFormalPaperServiceComposition,
    schedule: VerifiedFormalPaperSoakSchedule,
    session_date: dt.date,
    now: dt.datetime,
) -> VerifiedFormalPaperClosureView:
    fresh_policy = verify_existing_paper_execution_policy(
        policy=policy, environment=environment, now=now
    )
    view = open_formal_paper_closure_view(composition=composition, now=now)
    fresh_schedule = verify_existing_formal_paper_soak_schedule(
        schedule=schedule, now=now
    )
    if (
        fresh_policy != policy
        or fresh_schedule is not schedule
        or environment.config.mode != "PAPER_REAL_TIME_WINDOWS"
        or policy.session_date != session_date
        or view.policy is not policy
        or view.account.session_date != session_date
        or view.broker_store.session_date != session_date
        or view.execution_store_identity != composition.execution_store_identity
        or view.gateway_identity != composition.gateway_identity
        or view.account_id != composition.account_id
        or view.ledger_provider_identity != composition.ledger_provider_identity
        or schedule.ledger_provider_identity != composition.ledger_provider_identity
        or session_date not in schedule.expected_sessions
    ):
        raise ValueError
    return view


def _verified_windows_evidence(
    *, root: Path, anchor_root: Path, manifest: SoakRunManifest
) -> VerifiedPaperSoakEvidence:
    evidence = verify_soak_evidence(
        root=root, anchor_root=anchor_root, manifest=manifest
    )
    if (
        type(evidence) is not VerifiedPaperSoakEvidence
        or evidence.manifest != manifest
        or manifest.evidence_kind is not SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS
        or manifest.formal_gate_eligible
    ):
        raise ValueError
    return evidence


def _session_receipt(
    evidence: VerifiedPaperSoakEvidence, session_date: dt.date
) -> SoakSessionReceipt | None:
    matches = tuple(
        receipt
        for receipt in evidence.sessions
        if receipt.session_date == session_date
    )
    if len(matches) > 1:
        raise ValueError
    return None if not matches else matches[0]


def _fresh_decision(
    *,
    evidence: VerifiedPaperSoakEvidence,
    root: Path,
    anchor_root: Path,
    now: dt.datetime,
) -> SoakGateDecision:
    decision = decide_soak_gate(
        evidence, root=root, anchor_root=anchor_root, as_of=now
    )
    if decision.run_id != evidence.manifest.run_id or decision.status == "PASS":
        raise ValueError
    return decision


def _closure_field(closure: object, name: str) -> str:
    value = getattr(closure, name, None)
    if type(value) is not str or len(value) != 64:
        raise ValueError
    return value


def _hex(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and cast(dt.datetime, value).tzinfo is not None
        and cast(dt.datetime, value).utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "FormalPaperSoakSessionError",
    "FormalPaperSoakSessionResult",
    "SessionReportPort",
    "close_formal_paper_soak_session",
]
