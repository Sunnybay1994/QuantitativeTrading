"""M4-P4 execution orchestration over the durable store and gateway protocol.

The service is deliberately synchronous.  Durable outbox leases provide the
restart and multi-worker boundary; scheduling/background execution belongs to
the caller.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from quant.backtest.ledger_adapter import (
    ExecutionLedgerContext,
    LedgerContextProvider,
    apply_ledger_callbacks,
    build_genesis_checkpoint,
    decode_ledger_context,
    encode_ledger_context,
    verify_execution_ledger_context,
)
from quant.backtest.ledger import LedgerState
from quant.backtest.ledger_wire import (
    decode_ledger_state,
    encode_ledger_entry,
    encode_ledger_state,
)
from quant.domain.enums import ExecutionMode
from quant.execution.approval import (
    ApprovalReceiptError,
    FORMAL_APPROVAL_ACTION,
    canonical_source_identities_digest,
    decode_approval_receipt,
    unpack_verified_approval_receipt,
)
from quant.execution.approval_flow import (
    ApprovalFlowError,
    prove_approval_source_binding,
    require_verified_approval_receipt,
)
from quant.execution.config import TradingConfig
from quant.execution.contracts import (
    AccountSnapshot,
    CancelCommand,
    OrderCommand,
    OrderPlan,
    VerifiedMarketSnapshot,
    build_cancel_command,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelTransport,
    GatewayTransport,
    validate_gateway_cancel,
    validate_gateway_submit,
    verify_gateway_cancel_result,
    verify_gateway_dispatch_result,
)
from quant.execution.oms import OrderAggregate, new_order_aggregate, reduce_order
from quant.execution.reconcile import RecoveryError, recover_repository_state
from quant.execution.risk import (
    CancelRiskDecision,
    DailyRiskCounters,
    RiskDecision,
    RiskRuleResult,
    evaluate_cancel_risk,
    evaluate_pretrade,
)
from quant.execution.risk_wire import (
    DurableCancelRiskDecision,
    DurableOrderRiskDecision,
    DurableRiskTransitionReceipt,
    EXECUTION_STAGE_SCHEMA,
    GENESIS_RECEIPT_ID,
    build_cancel_risk_receipt,
    build_order_risk_receipt,
    decode_risk_receipt,
    encode_execution_stage,
    encode_risk_receipt,
    verify_risk_receipt_semantic_closure,
)
from quant.execution.store import (
    CancelOutboxDelivery,
    ExecutionRepository,
    ExecutionStore,
    IdempotencyConflict,
    LEDGER_CHECKPOINT_KEY,
    OutboxDelivery,
    OutboxDeliveryState,
    StoreError,
    StoredApprovalReceipt,
    StoredRecord,
    StoredRiskTransitionReceipt,
    StoredLedgerCheckpoint,
)
from quant.execution.wire import (
    WireError,
    decode_cancel_command,
    decode_order_aggregate,
    decode_order_command,
    encode_cancel_command,
    encode_execution_event,
    encode_order_aggregate,
    encode_order_command,
)
from quant.portfolio.order_planner import (
    OrderPlannerConfig,
    OrderPlanTarget,
    build_order_plan,
)

_SCOPE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_HEX64 = frozenset("0123456789abcdef")
_STAGE_SCHEMA = EXECUTION_STAGE_SCHEMA
_COUNTER_SCHEMA = "m4-daily-risk-counters-v1"

__all__ = [
    "CancelDispatchResult",
    "DispatchItemResult",
    "DispatchResult",
    "ExecutionService",
    "ExecutionServiceError",
    "ServiceClock",
    "StagedCancel",
    "StagedExecution",
]


class ExecutionServiceError(ValueError):
    """Stable, path-free service error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ServiceClock(Protocol):
    """Injected UTC clock."""

    def now(self) -> dt.datetime:
        """Return the current timezone-aware UTC instant."""
        ...


@dataclass(frozen=True, slots=True)
class StagedExecution:
    """One durable plan/risk/outbox staging result."""

    plan: OrderPlan
    risk: RiskDecision
    staged_command_ids: tuple[str, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class StagedCancel:
    """One durable PAPER cancel staging result."""

    cancel: CancelCommand
    risk: CancelRiskDecision
    replayed: bool


@dataclass(frozen=True, slots=True)
class CancelDispatchResult:
    """Sanitized observation for one exact cancel dispatch."""

    cancel_id: str
    dispatch_attempt: int
    certainty: DispatchCertainty | None
    callback_event_ids: tuple[str, ...]
    code: str


@dataclass(frozen=True, slots=True)
class DispatchItemResult:
    """Sanitized observation for one claimed delivery."""

    outbox_key: str
    command_id: str
    dispatch_attempt: int
    certainty: DispatchCertainty | None
    callback_event_ids: tuple[str, ...]
    code: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """One bounded dispatch pass."""

    claimed_count: int
    items: tuple[DispatchItemResult, ...]


class ExecutionService:
    """Compose planner, risk, durable outbox and a narrow gateway transport."""

    def __init__(
        self,
        *,
        store: ExecutionStore,
        gateway: GatewayTransport,
        clock: ServiceClock,
        worker_id: str,
        lease_duration: dt.timedelta,
        risk_counter_scope: str,
        ledger_context_provider: LedgerContextProvider,
        cancel_gateway: GatewayCancelTransport | None = None,
    ) -> None:
        if not isinstance(store, ExecutionStore):
            raise ExecutionServiceError("SERVICE_STORE_INVALID")
        if not isinstance(gateway, GatewayTransport):
            raise ExecutionServiceError("SERVICE_GATEWAY_INVALID")
        if not callable(getattr(clock, "now", None)):
            raise ExecutionServiceError("SERVICE_CLOCK_INVALID")
        if type(worker_id) is not str or _SCOPE.fullmatch(worker_id) is None:
            raise ExecutionServiceError("SERVICE_WORKER_ID_INVALID")
        if (
            type(lease_duration) is not dt.timedelta
            or lease_duration <= dt.timedelta(0)
        ):
            raise ExecutionServiceError("SERVICE_LEASE_INVALID")
        if type(risk_counter_scope) is not str or _SCOPE.fullmatch(risk_counter_scope) is None:
            raise ExecutionServiceError("SERVICE_COUNTER_SCOPE_INVALID")
        if not isinstance(ledger_context_provider, LedgerContextProvider):
            raise ExecutionServiceError("SERVICE_LEDGER_PROVIDER_INVALID")
        if cancel_gateway is not None and not isinstance(
            cancel_gateway, GatewayCancelTransport
        ):
            raise ExecutionServiceError("SERVICE_CANCEL_GATEWAY_INVALID")
        self._store = store
        self._gateway = gateway
        self._clock = clock
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._risk_counter_scope = risk_counter_scope
        self._ledger_context_provider = ledger_context_provider
        self._cancel_gateway = cancel_gateway

    def plan_and_stage(
        self,
        *,
        targets: Sequence[OrderPlanTarget],
        target_identity: str,
        market: VerifiedMarketSnapshot,
        account: AccountSnapshot,
        planner_config: OrderPlannerConfig,
        approval: object | None = None,
        approval_source_identities: Mapping[str, str] | None = None,
    ) -> StagedExecution:
        """Plan, risk-check and atomically stage commands exactly once per plan."""
        now = self._now()
        if approval is not None:
            return self._plan_and_stage_with_approval(
                targets=targets,
                target_identity=target_identity,
                market=market,
                account=account,
                planner_config=planner_config,
                approval=approval,
                approval_source_identities=approval_source_identities,
                now=now,
            )
        if approval_source_identities is not None:
            raise ExecutionServiceError("APPROVAL_SOURCE_DRIFT") from None
        plan: OrderPlan | None = None
        try:
            plan = build_order_plan(
                targets=targets,
                target_identity=target_identity,
                market=market,
                account=account,
                config=planner_config,
            )
        except Exception:
            pass
        if plan is None:
            raise ExecutionServiceError("SERVICE_PLANNING_FAILED") from None

        with self._store.transaction() as repo:
            counter_key = f"{self._risk_counter_scope}:{market.session_date.isoformat()}"
            existing = repo.get_execution_stage(plan.plan_id)
            if existing is not None:
                replayed_risk = _decode_stage(
                    existing, plan, market.session_date, repo
                )
                receipt_row = repo.get_risk_transition_receipt(
                    transition_kind="ORDER", subject_id=plan.plan_id
                )
                _verify_replay_risk_chain(repo, expected_counter_key=counter_key)
                _require_order_receipt(
                    receipt_row, replayed_risk, expected_counter_key=counter_key
                )
                _require_staged_ledger_rows(repo, replayed_risk.commands)
                return _staged(plan, replayed_risk, replayed=True)

            counter_row = repo.get_scoped_daily_risk_counters(counter_key)
            if counter_row is None:
                counters = DailyRiskCounters(
                    session_date=market.session_date,
                    order_count=0,
                    cancel_count=0,
                    buy_notional=Decimal(0),
                )
            else:
                counters = _decode_counter(counter_row, market.session_date)
            receipt_tail = repo.get_risk_transition_tail()

            risk: RiskDecision | None = None
            try:
                risk = evaluate_pretrade(
                    plan,
                    account,
                    market,
                    planner_config.trading_config,
                    counters,
                    now=now,
                )
            except Exception:
                pass
            if risk is None:
                raise ExecutionServiceError("SERVICE_RISK_FAILED") from None

            return self._write_order_stage(
                repo,
                plan=plan,
                account=account,
                market=market,
                risk=risk,
                counters=counters,
                counter_row=counter_row,
                counter_key=counter_key,
                receipt_tail=receipt_tail,
                now=now,
            )

    def _plan_and_stage_with_approval(
        self,
        *,
        targets: Sequence[OrderPlanTarget],
        target_identity: str,
        market: VerifiedMarketSnapshot,
        account: AccountSnapshot,
        planner_config: OrderPlannerConfig,
        approval: object,
        approval_source_identities: Mapping[str, str] | None,
        now: dt.datetime,
    ) -> StagedExecution:
        try:
            with self._store.transaction() as repo:
                plan: OrderPlan | None = None
                try:
                    plan = build_order_plan(
                        targets=targets,
                        target_identity=target_identity,
                        market=market,
                        account=account,
                        config=planner_config,
                    )
                except Exception:
                    pass
                if plan is None:
                    raise ExecutionServiceError("SERVICE_PLANNING_FAILED") from None

                mode_raw = planner_config.trading_config.section("execution")["mode"]
                if mode_raw != ExecutionMode.PAPER.value:
                    raise ExecutionServiceError("APPROVAL_PAPER_ONLY") from None

                verified = require_verified_approval_receipt(approval)
                receipt, payload = unpack_verified_approval_receipt(verified)
                if receipt.plan_identity != plan.plan_id:
                    raise ExecutionServiceError("APPROVAL_PLAN_DRIFT") from None
                if receipt.session_date != market.session_date.isoformat():
                    raise ExecutionServiceError("APPROVAL_SESSION_DRIFT") from None
                if approval_source_identities is None:
                    raise ExecutionServiceError("APPROVAL_SOURCE_DRIFT") from None
                try:
                    expected_sources = prove_approval_source_binding(
                        approval_source_identities,
                        account_snapshot_id=plan.account_snapshot_id,
                        market_snapshot_id=plan.market_snapshot_id,
                        planner_config_identity=plan.config_identity,
                        trading_config_identity=plan.trading_config_identity,
                    )
                except ApprovalFlowError as error:
                    raise ExecutionServiceError(error.code) from None
                expected_digest = canonical_source_identities_digest(expected_sources)
                if not hmac.compare_digest(
                    receipt.source_identities_digest, expected_digest
                ):
                    raise ExecutionServiceError("APPROVAL_SOURCE_DRIFT") from None

                existing_approval = repo.get_approval_receipt_for_plan(
                    plan_identity=plan.plan_id,
                    session_date=market.session_date,
                )
                counter_key = (
                    f"{self._risk_counter_scope}:{market.session_date.isoformat()}"
                )
                if existing_approval is not None:
                    if (
                        existing_approval.payload != payload
                        or existing_approval.receipt_id != receipt.receipt_id
                        or existing_approval.identity != receipt.receipt_id
                        or existing_approval.schema_version != receipt.schema_version
                        or existing_approval.classification != receipt.classification
                        or existing_approval.credential_kind != receipt.credential_kind
                        or existing_approval.credential_id != receipt.credential_id
                        or existing_approval.operator_id != receipt.operator_id
                        or existing_approval.session_date != receipt.session_date
                        or existing_approval.action != receipt.action
                        or existing_approval.plan_identity != receipt.plan_identity
                        or existing_approval.challenge_identity
                        != receipt.challenge_identity
                        or existing_approval.store_recovery_identity
                        != receipt.store_recovery_identity
                        or existing_approval.source_identities_digest
                        != receipt.source_identities_digest
                        or existing_approval.issued_at != receipt.issued_at
                        or existing_approval.nonce != receipt.nonce
                    ):
                        raise ExecutionServiceError(
                            "APPROVAL_BUSINESS_KEY_CONFLICT"
                        ) from None
                    existing_stage = repo.get_execution_stage(plan.plan_id)
                    if existing_stage is None:
                        raise ExecutionServiceError(
                            "APPROVAL_ORPHAN_STAGE_MISSING"
                        ) from None
                    replayed_risk = _decode_stage(
                        existing_stage, plan, market.session_date, repo
                    )
                    receipt_row = repo.get_risk_transition_receipt(
                        transition_kind="ORDER", subject_id=plan.plan_id
                    )
                    _verify_replay_risk_chain(repo, expected_counter_key=counter_key)
                    _require_order_receipt(
                        receipt_row, replayed_risk, expected_counter_key=counter_key
                    )
                    _require_approval_replay_closure(repo, replayed_risk)
                    return _staged(plan, replayed_risk, replayed=True)

                try:
                    current = recover_repository_state(repo)
                except RecoveryError as error:
                    raise ExecutionServiceError(error.code) from None
                if current.recovery_id != receipt.store_recovery_identity:
                    raise ExecutionServiceError("APPROVAL_RECOVERY_DRIFT") from None

                try:
                    inserted = repo.put_verified_approval_receipt(verified)
                except IdempotencyConflict as error:
                    raise ExecutionServiceError(_store_error_code(error)) from None
                except StoreError as error:
                    raise ExecutionServiceError(_store_error_code(error)) from None
                if not inserted:
                    raise ExecutionServiceError("APPROVAL_IDEMPOTENCY_INVALID") from None

                counter_row = repo.get_scoped_daily_risk_counters(counter_key)
                if counter_row is None:
                    counters = DailyRiskCounters(
                        session_date=market.session_date,
                        order_count=0,
                        cancel_count=0,
                        buy_notional=Decimal(0),
                    )
                else:
                    counters = _decode_counter(counter_row, market.session_date)
                receipt_tail = repo.get_risk_transition_tail()

                risk: RiskDecision | None = None
                try:
                    risk = evaluate_pretrade(
                        plan,
                        account,
                        market,
                        planner_config.trading_config,
                        counters,
                        now=now,
                        approval=verified,
                    )
                except Exception:
                    pass
                if risk is None:
                    raise ExecutionServiceError("SERVICE_RISK_FAILED") from None

                return self._write_order_stage(
                    repo,
                    plan=plan,
                    account=account,
                    market=market,
                    risk=risk,
                    counters=counters,
                    counter_row=counter_row,
                    counter_key=counter_key,
                    receipt_tail=receipt_tail,
                    now=now,
                )
        except ExecutionServiceError:
            raise
        except ApprovalFlowError as error:
            raise ExecutionServiceError(error.code) from None
        except ApprovalReceiptError as error:
            raise ExecutionServiceError(error.code) from None
        except StoreError as error:
            raise ExecutionServiceError(_store_error_code(error)) from None
        except Exception:
            raise ExecutionServiceError("SERVICE_STAGE_WRITE_FAILED") from None

    def _write_order_stage(
        self,
        repo: ExecutionRepository,
        *,
        plan: OrderPlan,
        account: AccountSnapshot,
        market: VerifiedMarketSnapshot,
        risk: RiskDecision,
        counters: DailyRiskCounters,
        counter_row: object | None,
        counter_key: str,
        receipt_tail: object | None,
        now: dt.datetime,
    ) -> StagedExecution:
        counter_payload = _encode_counter(risk.projected_counters)
        counter_identity = _digest(counter_payload)
        receipt: DurableRiskTransitionReceipt | None = None
        try:
            next_sequence, previous_receipt_id = _next_risk_receipt_position(
                receipt_tail  # type: ignore[arg-type]
            )
            receipt = build_order_risk_receipt(
                sequence=next_sequence,
                previous_receipt_id=previous_receipt_id,
                risk_counter_key=counter_key,
                predecessor_counters=counters,
                decision=risk,
            )
        except Exception:
            pass
        if receipt is None:
            raise ExecutionServiceError("SERVICE_RISK_RECEIPT_INVALID") from None
        stage_error: ExecutionServiceError | None = None
        try:
            checkpoint = repo.get_ledger_checkpoint(LEDGER_CHECKPOINT_KEY)
            if checkpoint is None:
                genesis = build_genesis_checkpoint(
                    account, as_of_date=market.session_date
                )
                genesis_payload = encode_ledger_state(genesis)
                repo.put_ledger_checkpoint(
                    checkpoint_key=LEDGER_CHECKPOINT_KEY,
                    identity=genesis.state_id,
                    payload=genesis_payload,
                    last_entry_id=None,
                )
            else:
                persisted = decode_ledger_state(checkpoint.payload)
                if (
                    persisted.state_id != checkpoint.identity
                    or persisted.origin_account_snapshot_id != account.snapshot_id
                ):
                    raise ExecutionServiceError(
                        "SERVICE_LEDGER_ACCOUNT_MISMATCH"
                    )
            if counter_row is None:
                repo.put_scoped_daily_risk_counters(
                    counter_key=counter_key,
                    identity=counter_identity,
                    payload=counter_payload,
                )
            else:
                repo.compare_and_set_scoped_daily_risk_counters(
                    counter_key=counter_key,
                    expected_identity=counter_row.identity,  # type: ignore[attr-defined]
                    identity=counter_identity,
                    payload=counter_payload,
                )

            for command in risk.commands:
                context = self._ledger_context_provider.context_for(command)
                context = verify_execution_ledger_context(
                    context, command=command
                )
                context_payload = encode_ledger_context(context)
                command_payload = encode_order_command(command)
                aggregate = new_order_aggregate(command)
                aggregate_payload = encode_order_aggregate(aggregate)
                repo.put_command(
                    command_id=command.command_id,
                    identity=command.command_id,
                    payload=command_payload,
                )
                repo.put_ledger_context(
                    command_id=command.command_id,
                    identity=context.context_id,
                    payload=context_payload,
                )
                repo.put_order_aggregate(
                    command_id=command.command_id,
                    identity=_digest(aggregate_payload),
                    payload=aggregate_payload,
                )
                repo.put_outbox(
                    outbox_key=command.command_id,
                    identity=command.command_id,
                    payload=command_payload,
                )
                repo.put_outbox_delivery(
                    outbox_key=command.command_id,
                    command_id=command.command_id,
                    available_at=now,
                )

            _put_risk_receipt(repo, receipt)

            stage_payload = _encode_stage(risk)
            repo.put_execution_stage(
                plan_id=plan.plan_id,
                identity=_digest(stage_payload),
                payload=stage_payload,
            )
        except ExecutionServiceError as error:
            stage_error = error
        except Exception:
            stage_error = ExecutionServiceError("SERVICE_STAGE_WRITE_FAILED")
        if stage_error is not None:
            raise stage_error from None
        return _staged(plan, risk, replayed=False)

    def stage_cancel(
        self, *, command_id: str, trading_config: TradingConfig
    ) -> StagedCancel:
        """Risk-check and atomically stage one content-addressed PAPER cancel."""
        now = self._now()
        try:
            with self._store.transaction() as repo:
                command, aggregate, _ = _load_order_state(repo, command_id)
                if command.mode is not ExecutionMode.PAPER:
                    raise ExecutionServiceError("CANCEL_PAPER_ONLY")
                existing = repo.get_cancel_command_for_order(command_id)
                if existing is not None:
                    cancel = _decode_stored_cancel(existing.payload, existing.cancel_id)
                    _verify_cancel_against_order(cancel, command, aggregate, now=now)
                    delivery = repo.get_cancel_delivery(cancel.cancel_id)
                    if (
                        delivery is None
                        or delivery.command_id != command.command_id
                        or delivery.identity != cancel.cancel_id
                        or delivery.payload != existing.payload
                    ):
                        raise ExecutionServiceError("CANCEL_RECOVERY_CLOSURE_INVALID")
                    receipt_row = repo.get_risk_transition_receipt(
                        transition_kind="CANCEL", subject_id=cancel.cancel_id
                    )
                    expected_counter_key = (
                        f"{self._risk_counter_scope}:"
                        f"{command.intent.session_date.isoformat()}"
                    )
                    _verify_replay_risk_chain(
                        repo, expected_counter_key=expected_counter_key
                    )
                    durable = _require_cancel_receipt(
                        receipt_row,
                        cancel_id=cancel.cancel_id,
                        command_id=command.command_id,
                        counter_key=expected_counter_key,
                        policy_identity=existing.risk_policy_identity,
                    )
                    if existing.risk_counter_key != expected_counter_key:
                        raise ExecutionServiceError(
                            "CANCEL_RECOVERY_CLOSURE_INVALID"
                        ) from None
                    return StagedCancel(
                        cancel=cancel,
                        risk=CancelRiskDecision(
                            accepted=durable.accepted,
                            cancel_id=durable.cancel_id,
                            code=durable.code,
                            policy_identity=durable.policy_identity,
                            projected_counters=durable.projected_counters,
                        ),
                        replayed=True,
                    )

                cancel = build_cancel_command(
                    command=command, aggregate=aggregate, as_of=now
                )
                counter_key = (
                    f"{self._risk_counter_scope}:{command.intent.session_date.isoformat()}"
                )
                counter_row = repo.get_scoped_daily_risk_counters(counter_key)
                counters = (
                    DailyRiskCounters(
                        session_date=command.intent.session_date,
                        order_count=0,
                        cancel_count=0,
                        buy_notional=Decimal(0),
                    )
                    if counter_row is None
                    else _decode_counter(counter_row, command.intent.session_date)
                )
                risk = evaluate_cancel_risk(cancel, trading_config, counters)
                if not risk.accepted:
                    raise ExecutionServiceError("CANCEL_LIMIT_EXCEEDED")
                counter_payload = _encode_counter(risk.projected_counters)
                counter_identity = _digest(counter_payload)
                receipt_tail = repo.get_risk_transition_tail()
                next_sequence, previous_receipt_id = _next_risk_receipt_position(
                    receipt_tail
                )
                receipt = build_cancel_risk_receipt(
                    sequence=next_sequence,
                    previous_receipt_id=previous_receipt_id,
                    risk_counter_key=counter_key,
                    predecessor_counters=counters,
                    command_id=command.command_id,
                    decision=risk,
                )
                if counter_row is None:
                    repo.put_scoped_daily_risk_counters(
                        counter_key=counter_key,
                        identity=counter_identity,
                        payload=counter_payload,
                    )
                else:
                    repo.compare_and_set_scoped_daily_risk_counters(
                        counter_key=counter_key,
                        expected_identity=counter_row.identity,
                        identity=counter_identity,
                        payload=counter_payload,
                    )
                payload = encode_cancel_command(cancel)
                repo.put_cancel_command(
                    cancel_id=cancel.cancel_id,
                    command_id=command.command_id,
                    identity=cancel.cancel_id,
                    payload=payload,
                    risk_counter_key=counter_key,
                    risk_policy_identity=risk.policy_identity,
                )
                repo.put_cancel_delivery(
                    cancel_id=cancel.cancel_id,
                    command_id=command.command_id,
                    available_at=now,
                )
                _put_risk_receipt(repo, receipt)
                return StagedCancel(cancel=cancel, risk=risk, replayed=False)
        except ExecutionServiceError:
            raise
        except StoreError:
            raise
        except Exception:
            pass
        raise ExecutionServiceError("CANCEL_STAGE_FAILED") from None

    def dispatch_cancel(self, *, cancel_id: str) -> CancelDispatchResult:
        """Claim and dispatch exactly one durable cancel request."""
        if self._cancel_gateway is None:
            raise ExecutionServiceError("SERVICE_CANCEL_GATEWAY_MISSING")
        # Outer OPEN operation fence covers claim → gateway → callback/unknown.
        # Non-barrier stores: open_operation_fence is a no-op; permit always
        # released via the contextmanager finally path.
        with self._store.open_operation_fence():
            return self._dispatch_cancel_under_operation_fence(cancel_id=cancel_id)

    def _dispatch_cancel_under_operation_fence(
        self, *, cancel_id: str
    ) -> CancelDispatchResult:
        cancel_gateway = self._cancel_gateway
        if cancel_gateway is None:
            raise ExecutionServiceError("SERVICE_CANCEL_GATEWAY_MISSING")
        claimed_at = self._now()
        lease_until = claimed_at + self._lease_duration
        try:
            with self._store.transaction() as repo:
                delivery = repo.claim_cancel_delivery(
                    cancel_id=cancel_id,
                    worker_id=self._worker_id,
                    now=claimed_at,
                    lease_until=lease_until,
                )
        except Exception:
            raise ExecutionServiceError("CANCEL_DELIVERY_NOT_CLAIMABLE") from None

        # Commit a fail-closed "adapter may start" fence before the adapter call.
        # An abandoned/expired started attempt is never eligible for auto-reclaim.
        try:
            with self._store.transaction() as repo:
                current = repo.get_cancel_delivery(delivery.cancel_id)
                if not _same_cancel_lease(current, delivery, self._worker_id):
                    raise ExecutionServiceError("CANCEL_DELIVERY_FENCE_MISMATCH")
                command, aggregate, _ = _load_order_state(repo, delivery.command_id)
                cancel = _decode_stored_cancel(delivery.payload, delivery.cancel_id)
                _verify_cancel_frozen_snapshot(cancel, command, aggregate)
                repo.mark_cancel_gateway_started(
                    cancel_id=cancel.cancel_id,
                    lease_owner=self._worker_id,
                    expected_attempt=delivery.attempt_count,
                )
        except Exception:
            return self._mark_cancel_unknown(delivery, "CANCEL_SNAPSHOT_DRIFT")

        callback_ids: tuple[str, ...] = ()
        # Barrier-enabled formal writers share one non-reentrant OS lock across OMS
        # and broker. Lease depth must stay exact 1: never hold an OMS write lease
        # across the gateway/broker boundary (same pattern as submit dispatch).
        try:
            with self._store.transaction() as repo:
                current = repo.get_cancel_delivery(cancel.cancel_id)
                if (
                    not _same_cancel_lease(current, delivery, self._worker_id)
                    or current is None
                    or current.last_error_code != "CANCEL_GATEWAY_STARTED"
                ):
                    raise ExecutionServiceError("CANCEL_DELIVERY_FENCE_MISMATCH")
                current_command, current_aggregate, aggregate_row = _load_order_state(
                    repo, command.command_id
                )
                try:
                    _verify_cancel_frozen_snapshot(
                        cancel, current_command, current_aggregate
                    )
                except Exception:
                    drift_at = self._now()
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=drift_at,
                        error_code="CANCEL_SNAPSHOT_DRIFT",
                    )
                    return _cancel_item(
                        delivery,
                        DispatchCertainty.UNKNOWN,
                        (),
                        "CANCEL_SNAPSHOT_DRIFT",
                    )
                dispatch_at = self._now()
                if delivery.lease_until is None or dispatch_at >= delivery.lease_until:
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=dispatch_at,
                        error_code="CANCEL_LEASE_EXPIRED_BEFORE_DISPATCH",
                    )
                    return _cancel_item(
                        delivery, DispatchCertainty.UNKNOWN, (),
                        "CANCEL_LEASE_EXPIRED_BEFORE_DISPATCH",
                    )
                try:
                    validate_gateway_cancel(cancel, delivery.attempt_count, dispatch_at)
                except Exception:
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=dispatch_at,
                        error_code="CANCEL_GATEWAY_INPUT_INVALID",
                    )
                    return _cancel_item(
                        delivery,
                        DispatchCertainty.UNKNOWN,
                        (),
                        "CANCEL_GATEWAY_INPUT_INVALID",
                    )
                # Capture durable snapshots before releasing the OMS lease.
                preflight_command = current_command
                preflight_aggregate = current_aggregate
                preflight_aggregate_row = aggregate_row
                preflight_dispatch_at = dispatch_at
        except ExecutionServiceError:
            raise
        except Exception:
            return self._mark_cancel_unknown(delivery, "CANCEL_SNAPSHOT_DRIFT")

        try:
            raw_result = cancel_gateway.cancel(
                command=cancel,
                dispatch_attempt=delivery.attempt_count,
                now=preflight_dispatch_at,
            )
        except Exception:
            return self._mark_cancel_unknown(delivery, "CANCEL_GATEWAY_EXCEPTION")

        observed_at = self._now()
        try:
            result = verify_gateway_cancel_result(
                preflight_command,
                cancel,
                preflight_aggregate,
                delivery.attempt_count,
                observed_at,
                raw_result,
            )
        except Exception:
            return self._mark_cancel_unknown(delivery, "CANCEL_RESULT_INVALID")

        callback_ids = tuple(item.event_id for item in result.callbacks)
        try:
            with self._store.transaction() as repo:
                current = repo.get_cancel_delivery(cancel.cancel_id)
                if (
                    not _same_cancel_lease(current, delivery, self._worker_id)
                    or current is None
                    or current.last_error_code != "CANCEL_GATEWAY_STARTED"
                ):
                    raise ExecutionServiceError("CANCEL_DELIVERY_FENCE_MISMATCH")
                current_command, current_aggregate, aggregate_row = _load_order_state(
                    repo, command.command_id
                )
                if (
                    current_command.command_id != preflight_command.command_id
                    or aggregate_row.identity != preflight_aggregate_row.identity
                ):
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=observed_at,
                        error_code="CANCEL_SNAPSHOT_DRIFT",
                    )
                    return _cancel_item(
                        delivery,
                        DispatchCertainty.UNKNOWN,
                        callback_ids,
                        "CANCEL_SNAPSHOT_DRIFT",
                    )
                try:
                    _verify_cancel_frozen_snapshot(
                        cancel, current_command, current_aggregate
                    )
                except Exception:
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=observed_at,
                        error_code="CANCEL_SNAPSHOT_DRIFT",
                    )
                    return _cancel_item(
                        delivery,
                        DispatchCertainty.UNKNOWN,
                        callback_ids,
                        "CANCEL_SNAPSHOT_DRIFT",
                    )
                if result.certainty is DispatchCertainty.NOT_SENT:
                    repo.mark_cancel_not_sent(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        retry_at=observed_at,
                    )
                    return _cancel_item(delivery, result.certainty, (), "NOT_SENT")
                if result.certainty is DispatchCertainty.UNKNOWN:
                    repo.mark_cancel_unknown(
                        cancel_id=cancel.cancel_id,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        unknown_at=observed_at,
                        error_code="CANCEL_GATEWAY_UNKNOWN",
                    )
                    return _cancel_item(
                        delivery, result.certainty, (), "CANCEL_DELIVERY_UNKNOWN"
                    )

                context = _load_ledger_context(repo, current_command)
                checkpoint_row, checkpoint = _load_ledger_checkpoint(repo)
                mutation = apply_ledger_callbacks(
                    state=checkpoint,
                    command=current_command,
                    callbacks=result.callbacks,
                    context=context,
                )
                updated = current_aggregate
                for event in result.callbacks:
                    repo.put_event(
                        event_id=event.event_id,
                        command_id=event.command_id,
                        identity=event.event_id,
                        payload=encode_execution_event(event),
                    )
                    repo.put_cancel_event_link(
                        cancel_id=cancel.cancel_id, event_id=event.event_id
                    )
                    updated = reduce_order(updated, current_command, event)
                if updated != current_aggregate:
                    aggregate_payload = encode_order_aggregate(updated)
                    repo.replace_order_aggregate(
                        command_id=current_command.command_id,
                        expected_identity=aggregate_row.identity,
                        identity=_digest(aggregate_payload),
                        payload=aggregate_payload,
                    )
                for entry in mutation.entries:
                    repo.put_ledger_entry(
                        entry_id=entry.entry_id,
                        identity=entry.entry_id,
                        payload=encode_ledger_entry(entry),
                    )
                if mutation.state != checkpoint:
                    state_payload = encode_ledger_state(mutation.state)
                    tail = (
                        mutation.entries[-1].entry_id
                        if mutation.entries
                        else checkpoint_row.last_entry_id
                    )
                    repo.replace_ledger_checkpoint(
                        checkpoint_key=LEDGER_CHECKPOINT_KEY,
                        expected_identity=checkpoint_row.identity,
                        identity=mutation.state.state_id,
                        payload=state_payload,
                        last_entry_id=tail,
                    )
                repo.mark_cancel_sent(
                    cancel_id=cancel.cancel_id,
                    lease_owner=self._worker_id,
                    expected_attempt=delivery.attempt_count,
                    sent_at=observed_at,
                )
        except Exception:
            return self._mark_cancel_unknown(
                delivery,
                "CANCEL_CALLBACK_TRANSACTION_FAILED",
                callback_ids,
                result_code="CANCEL_CALLBACK_TRANSACTION_FAILED",
            )
        return _cancel_item(delivery, DispatchCertainty.SENT, callback_ids, "SENT")

    def dispatch_pending(self, *, limit: int) -> DispatchResult:
        """Claim and synchronously dispatch at most ``limit`` ready commands."""
        if type(limit) is not int or limit <= 0:
            raise ExecutionServiceError("SERVICE_DISPATCH_LIMIT_INVALID")
        claimed_at = self._now()
        lease_until = claimed_at + self._lease_duration
        with self._store.open_operation_fence():
            try:
                with self._store.transaction() as repo:
                    claimed = repo.claim_outbox_deliveries(
                        worker_id=self._worker_id,
                        now=claimed_at,
                        lease_until=lease_until,
                        limit=limit,
                    )
            except Exception:
                raise ExecutionServiceError("SERVICE_CLAIM_FAILED") from None
            return self._dispatch_claimed(claimed, lease_until=lease_until)

    def dispatch_commands(self, *, command_ids: tuple[str, ...]) -> DispatchResult:
        """Claim and dispatch exactly one canonical, ordered command allowlist."""
        valid = type(command_ids) is tuple and bool(command_ids)
        if valid:
            assert isinstance(command_ids, tuple)
            valid = all(
                type(item) is str
                and len(item) == 64
                and all(char in _HEX64 for char in item)
                for item in command_ids
            )
        if valid:
            valid = command_ids == tuple(sorted(command_ids)) and len(
                set(command_ids)
            ) == len(command_ids)
        if not valid:
            error = ExecutionServiceError("SERVICE_COMMAND_SELECTION_INVALID")
            error.__suppress_context__ = True
            raise error
        claimed_at = self._now()
        lease_until = claimed_at + self._lease_duration
        with self._store.open_operation_fence():
            claim_failed = False
            try:
                with self._store.transaction() as repo:
                    claimed = repo.claim_selected_outbox_deliveries(
                        command_ids=command_ids,
                        worker_id=self._worker_id,
                        now=claimed_at,
                        lease_until=lease_until,
                    )
            except Exception:
                claim_failed = True
            if claim_failed:
                error = ExecutionServiceError("SERVICE_SELECTED_CLAIM_FAILED")
                error.__suppress_context__ = True
                raise error
            return self._dispatch_claimed(claimed, lease_until=lease_until)

    def dispatch_exact_pending_commands(
        self, *, command_ids: tuple[str, ...]
    ) -> DispatchResult:
        """Dispatch only if ``command_ids`` is still the complete pending set."""
        valid = type(command_ids) is tuple and bool(command_ids)
        if valid:
            assert isinstance(command_ids, tuple)
            valid = all(
                type(item) is str
                and len(item) == 64
                and all(char in _HEX64 for char in item)
                for item in command_ids
            )
        if valid:
            valid = command_ids == tuple(sorted(command_ids)) and len(
                set(command_ids)
            ) == len(command_ids)
        if not valid:
            raise ExecutionServiceError("SERVICE_COMMAND_SELECTION_INVALID")
        claimed_at = self._now()
        lease_until = claimed_at + self._lease_duration
        with self._store.open_operation_fence():
            failure_code: str | None = None
            try:
                with self._store.transaction() as repo:
                    claimed = repo.claim_exact_pending_outbox_deliveries(
                        command_ids=command_ids,
                        worker_id=self._worker_id,
                        now=claimed_at,
                        lease_until=lease_until,
                    )
            except StoreError as store_error:
                failure_code = (
                    "SERVICE_EXACT_PENDING_SET_DRIFT"
                    if store_error.args == ("OUTBOX_DELIVERY_EXACT_SET_DRIFT",)
                    else "SERVICE_EXACT_PENDING_WRITE_FAILED"
                )
            except Exception:
                failure_code = "SERVICE_EXACT_PENDING_WRITE_FAILED"
            if failure_code is not None:
                service_error = ExecutionServiceError(failure_code)
                service_error.__suppress_context__ = True
                raise service_error
            return self._dispatch_claimed(claimed, lease_until=lease_until)

    def _dispatch_claimed(
        self,
        claimed: tuple[OutboxDelivery, ...],
        *,
        lease_until: dt.datetime,
    ) -> DispatchResult:
        """Run the single fenced gateway/OMS/ledger path for claimed rows."""

        items: list[DispatchItemResult] = []
        for delivery in claimed:
            if self._now() >= lease_until:
                items.append(_dispatch_item(delivery, None, (), "LEASE_EXPIRED"))
                continue
            try:
                with self._store.transaction() as repo:
                    current = repo.get_outbox_delivery(delivery.outbox_key)
                    if not _same_lease(current, delivery, self._worker_id):
                        items.append(
                            _dispatch_item(delivery, None, (), "LEASE_LOST_BEFORE_DISPATCH")
                        )
                        continue
                    assert current is not None
                    command, _ = _load_command_and_aggregate(repo, current)
            except Exception:
                raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID") from None

            # Re-read the clock after durable closure validation.  This is the
            # final enforceable fence before crossing the adapter boundary.
            dispatch_at = self._now()
            if current.lease_until is None or dispatch_at >= current.lease_until:
                items.append(
                    _dispatch_item(delivery, None, (), "LEASE_EXPIRED_BEFORE_DISPATCH")
                )
                continue
            try:
                validate_gateway_submit(command, delivery.attempt_count, dispatch_at)
            except Exception:
                raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID") from None

            try:
                raw_result = self._gateway.submit(
                    command=command,
                    dispatch_attempt=delivery.attempt_count,
                    now=dispatch_at,
                )
            except Exception:
                items.append(self._mark_unknown(delivery, "GATEWAY_EXCEPTION"))
                continue

            observed_at = self._now()
            try:
                result = verify_gateway_dispatch_result(
                    command,
                    delivery.attempt_count,
                    observed_at,
                    raw_result,
                )
            except Exception:
                items.append(self._mark_unknown(delivery, "GATEWAY_RESULT_INVALID"))
                continue

            if observed_at >= lease_until:
                items.append(
                    _dispatch_item(
                        delivery,
                        result.certainty,
                        tuple(item.event_id for item in result.callbacks),
                        "LEASE_EXPIRED_AFTER_DISPATCH",
                    )
                )
                continue
            if result.certainty is DispatchCertainty.NOT_SENT:
                items.append(_dispatch_item(delivery, result.certainty, (), "NOT_SENT"))
                continue
            if result.certainty is DispatchCertainty.UNKNOWN:
                items.append(self._mark_unknown(delivery, "GATEWAY_UNKNOWN"))
                continue

            callback_ids = tuple(item.event_id for item in result.callbacks)
            try:
                with self._store.transaction() as repo:
                    current = repo.get_outbox_delivery(delivery.outbox_key)
                    if current is None:
                        raise ExecutionServiceError("SERVICE_DELIVERY_MISSING")
                    current_command, aggregate_row = _load_command_and_aggregate(repo, current)
                    aggregate = _decode_aggregate(aggregate_row, current_command)
                    context = _load_ledger_context(repo, current_command)
                    checkpoint_row, checkpoint = _load_ledger_checkpoint(repo)
                    mutation = apply_ledger_callbacks(
                        state=checkpoint,
                        command=current_command,
                        callbacks=result.callbacks,
                        context=context,
                    )
                    updated = aggregate
                    for event in result.callbacks:
                        event_payload = encode_execution_event(event)
                        repo.put_event(
                            event_id=event.event_id,
                            command_id=event.command_id,
                            identity=event.event_id,
                            payload=event_payload,
                        )
                        updated = reduce_order(updated, current_command, event)
                    if updated != aggregate:
                        payload = encode_order_aggregate(updated)
                        repo.replace_order_aggregate(
                            command_id=current_command.command_id,
                            expected_identity=aggregate_row.identity,
                            identity=_digest(payload),
                            payload=payload,
                        )
                    for entry in mutation.entries:
                        entry_payload = encode_ledger_entry(entry)
                        repo.put_ledger_entry(
                            entry_id=entry.entry_id,
                            identity=entry.entry_id,
                            payload=entry_payload,
                        )
                    if mutation.state != checkpoint:
                        state_payload = encode_ledger_state(mutation.state)
                        tail = (
                            mutation.entries[-1].entry_id
                            if mutation.entries
                            else checkpoint_row.last_entry_id
                        )
                        repo.replace_ledger_checkpoint(
                            checkpoint_key=LEDGER_CHECKPOINT_KEY,
                            expected_identity=checkpoint_row.identity,
                            identity=mutation.state.state_id,
                            payload=state_payload,
                            last_entry_id=tail,
                        )
                    repo.mark_outbox_sent(
                        outbox_key=delivery.outbox_key,
                        lease_owner=self._worker_id,
                        expected_attempt=delivery.attempt_count,
                        sent_at=observed_at,
                    )
            except Exception:
                items.append(
                    _dispatch_item(
                        delivery,
                        DispatchCertainty.SENT,
                        callback_ids,
                        "CALLBACK_TRANSACTION_FAILED",
                    )
                )
                continue
            items.append(
                _dispatch_item(delivery, DispatchCertainty.SENT, callback_ids, "SENT")
            )
        return DispatchResult(claimed_count=len(claimed), items=tuple(items))

    def _mark_unknown(self, delivery: object, error_code: str) -> DispatchItemResult:
        from quant.execution.store import OutboxDelivery

        if not isinstance(delivery, OutboxDelivery):
            raise ExecutionServiceError("SERVICE_DELIVERY_INVALID")
        at = self._now()
        if delivery.lease_until is None or at >= delivery.lease_until:
            return _dispatch_item(
                delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN_NOT_DURABLE"
            )
        try:
            with self._store.transaction() as repo:
                repo.mark_outbox_unknown(
                    outbox_key=delivery.outbox_key,
                    lease_owner=self._worker_id,
                    expected_attempt=delivery.attempt_count,
                    unknown_at=at,
                    error_code=error_code,
                )
        except Exception:
            return _dispatch_item(
                delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN_NOT_DURABLE"
            )
        return _dispatch_item(delivery, DispatchCertainty.UNKNOWN, (), "UNKNOWN")

    def _mark_cancel_unknown(
        self,
        delivery: CancelOutboxDelivery,
        error_code: str,
        callbacks: tuple[str, ...] = (),
        *,
        result_code: str = "CANCEL_DELIVERY_UNKNOWN",
    ) -> CancelDispatchResult:
        at = self._now()
        if delivery.lease_until is None:
            return _cancel_item(
                delivery,
                DispatchCertainty.UNKNOWN,
                callbacks,
                "UNKNOWN_NOT_DURABLE",
            )
        try:
            with self._store.transaction() as repo:
                repo.mark_cancel_unknown(
                    cancel_id=delivery.cancel_id,
                    lease_owner=self._worker_id,
                    expected_attempt=delivery.attempt_count,
                    unknown_at=at,
                    error_code=error_code,
                )
        except Exception:
            return _cancel_item(
                delivery,
                DispatchCertainty.UNKNOWN,
                callbacks,
                "UNKNOWN_NOT_DURABLE",
            )
        return _cancel_item(
            delivery, DispatchCertainty.UNKNOWN, callbacks, result_code
        )

    def _now(self) -> dt.datetime:
        value: object = None
        try:
            value = self._clock.now()
            if type(value) is not dt.datetime:
                raise TypeError
            assert isinstance(value, dt.datetime)
            if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
                raise ValueError
        except Exception:
            raise ExecutionServiceError("SERVICE_CLOCK_INVALID") from None
        return value


def _same_lease(
    current: OutboxDelivery | None,
    claimed: OutboxDelivery,
    worker_id: str,
) -> bool:
    """Return whether the claimed attempt is still owned by this worker."""
    return (
        current is not None
        and current.state is OutboxDeliveryState.LEASED
        and current.lease_owner == worker_id
        and current.attempt_count == claimed.attempt_count
        and current.lease_until == claimed.lease_until
    )


def _same_cancel_lease(
    current: CancelOutboxDelivery | None,
    claimed: CancelOutboxDelivery,
    worker_id: str,
) -> bool:
    return (
        current is not None
        and current.state is OutboxDeliveryState.LEASED
        and current.lease_owner == worker_id
        and current.attempt_count == claimed.attempt_count
        and current.lease_until == claimed.lease_until
        and current.cancel_id == claimed.cancel_id
        and current.command_id == claimed.command_id
    )


def _staged(plan: OrderPlan, risk: RiskDecision, *, replayed: bool) -> StagedExecution:
    return StagedExecution(
        plan=plan,
        risk=risk,
        staged_command_ids=tuple(item.command_id for item in risk.commands),
        replayed=replayed,
    )


def _store_error_code(error: StoreError) -> str:
    message = str(error)
    if not message:
        return "SERVICE_STORE_WRITE_FAILED"
    if message.startswith("IDEMPOTENCY_CONFLICT"):
        return "APPROVAL_IDEMPOTENCY_CONFLICT"
    return message.split(":", 1)[0]


def _dispatch_item(
    delivery: object,
    certainty: DispatchCertainty | None,
    callbacks: tuple[str, ...],
    code: str,
) -> DispatchItemResult:
    from quant.execution.store import OutboxDelivery

    assert isinstance(delivery, OutboxDelivery)
    return DispatchItemResult(
        outbox_key=delivery.outbox_key,
        command_id=delivery.command_id,
        dispatch_attempt=delivery.attempt_count,
        certainty=certainty,
        callback_event_ids=callbacks,
        code=code,
    )


def _cancel_item(
    delivery: CancelOutboxDelivery,
    certainty: DispatchCertainty | None,
    callbacks: tuple[str, ...],
    code: str,
) -> CancelDispatchResult:
    return CancelDispatchResult(
        cancel_id=delivery.cancel_id,
        dispatch_attempt=delivery.attempt_count,
        certainty=certainty,
        callback_event_ids=callbacks,
        code=code,
    )


def _load_order_state(
    repo: ExecutionRepository, command_id: str
) -> tuple[OrderCommand, OrderAggregate, StoredRecord]:
    row = repo.get_command(command_id)
    aggregate_row = repo.get_order_aggregate(command_id)
    if (
        row is None
        or aggregate_row is None
        or row.key != command_id
        or row.identity != command_id
    ):
        raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID")
    command = _decode_command(row.payload)
    if command.command_id != command_id:
        raise ExecutionServiceError("SERVICE_DURABLE_COMMAND_INVALID")
    aggregate = _decode_aggregate(aggregate_row, command)
    return command, aggregate, aggregate_row


def _decode_stored_cancel(payload: bytes, cancel_id: str) -> CancelCommand:
    cancel: CancelCommand | None = None
    try:
        cancel = decode_cancel_command(payload)
    except Exception:
        pass
    if (
        cancel is None
        or cancel.cancel_id != cancel_id
        or encode_cancel_command(cancel) != payload
    ):
        raise ExecutionServiceError("CANCEL_RECOVERY_CLOSURE_INVALID") from None
    return cancel


def _verify_cancel_frozen_snapshot(
    cancel: CancelCommand, command: OrderCommand, aggregate: OrderAggregate
) -> None:
    rebuilt: CancelCommand | None = None
    try:
        rebuilt = build_cancel_command(
            command=command, aggregate=aggregate, as_of=cancel.as_of
        )
    except Exception:
        pass
    if rebuilt != cancel:
        raise ExecutionServiceError("CANCEL_SNAPSHOT_DRIFT") from None


def _verify_cancel_against_order(
    cancel: CancelCommand,
    command: OrderCommand,
    aggregate: OrderAggregate,
    *,
    now: dt.datetime,
) -> None:
    verified: CancelCommand | None = None
    try:
        if aggregate.status.value in {"SUBMITTED", "PARTIAL_FILLED"}:
            verified = build_cancel_command(
                command=command, aggregate=aggregate, as_of=cancel.as_of
            )
        else:
            verified = build_cancel_command(
                command=command, aggregate=aggregate, as_of=now, replay=cancel
            )
    except Exception:
        pass
    if verified != cancel:
        raise ExecutionServiceError("CANCEL_RECOVERY_CLOSURE_INVALID") from None


def _load_command_and_aggregate(
    repo: ExecutionRepository, delivery: object
) -> tuple[OrderCommand, StoredRecord]:
    from quant.execution.store import OutboxDelivery

    if not isinstance(delivery, OutboxDelivery):
        raise ExecutionServiceError("SERVICE_DELIVERY_INVALID")
    if (
        delivery.outbox_key != delivery.command_id
        or delivery.identity != delivery.command_id
    ):
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    command = _decode_command(delivery.payload)
    if command.command_id != delivery.command_id:
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    row = repo.get_command(delivery.command_id)
    aggregate = repo.get_order_aggregate(delivery.command_id)
    if (
        row is None
        or aggregate is None
        or row.key != delivery.command_id
        or row.identity != delivery.command_id
        or row.payload != delivery.payload
    ):
        raise ExecutionServiceError("SERVICE_DELIVERY_CLOSURE_INVALID")
    _decode_aggregate(aggregate, command)
    return command, aggregate


def _load_ledger_context(
    repo: ExecutionRepository, command: OrderCommand
) -> ExecutionLedgerContext:
    row = repo.get_ledger_context(command.command_id)
    if row is None or row.key != command.command_id:
        raise ExecutionServiceError("LEGACY_LEDGER_CONTEXT_MISSING")
    context: ExecutionLedgerContext | None = None
    try:
        context = decode_ledger_context(row.payload)
        context = verify_execution_ledger_context(context, command=command)
    except Exception:
        pass
    if context is None:
        raise ExecutionServiceError("SERVICE_LEDGER_CONTEXT_INVALID") from None
    if context.command_id != command.command_id or context.context_id != row.identity:
        raise ExecutionServiceError("SERVICE_LEDGER_CONTEXT_INVALID")
    return context


def _load_ledger_checkpoint(
    repo: ExecutionRepository,
) -> tuple[StoredLedgerCheckpoint, LedgerState]:
    row = repo.get_ledger_checkpoint(LEDGER_CHECKPOINT_KEY)
    if row is None:
        raise ExecutionServiceError("LEGACY_LEDGER_CHECKPOINT_MISSING")
    state: LedgerState | None = None
    try:
        state = decode_ledger_state(row.payload)
    except Exception:
        pass
    if state is None:
        raise ExecutionServiceError("LEGACY_LEDGER_WIRE_UNVERIFIED") from None
    if state.state_id != row.identity:
        raise ExecutionServiceError("SERVICE_LEDGER_CHECKPOINT_INVALID")
    return row, state


def _require_staged_ledger_rows(
    repo: ExecutionRepository, commands: tuple[OrderCommand, ...]
) -> None:
    _load_ledger_checkpoint(repo)
    for command in commands:
        _load_ledger_context(repo, command)


def _require_approval_replay_closure(
    repo: ExecutionRepository, risk: RiskDecision
) -> None:
    """Prove full stage/command/aggregate/outbox/delivery/ledger join for replay."""
    _require_staged_ledger_rows(repo, risk.commands)
    for command in risk.commands:
        _require_staged_command_storage_closure(repo, command)


def _require_staged_command_storage_closure(
    repo: ExecutionRepository, command: OrderCommand
) -> None:
    command_payload = encode_order_command(command)
    row = repo.get_command(command.command_id)
    if (
        row is None
        or row.key != command.command_id
        or row.identity != command.command_id
        or row.payload != command_payload
    ):
        raise ExecutionServiceError("APPROVAL_ORPHAN_COMMAND_MISSING") from None
    aggregate = repo.get_order_aggregate(command.command_id)
    if aggregate is None:
        raise ExecutionServiceError("APPROVAL_ORPHAN_AGGREGATE_MISSING") from None
    try:
        _decode_aggregate(aggregate, command)
    except ExecutionServiceError:
        raise ExecutionServiceError("APPROVAL_ORPHAN_AGGREGATE_MISSING") from None
    outbox = repo.get_outbox(command.command_id)
    if (
        outbox is None
        or outbox.key != command.command_id
        or outbox.identity != command.command_id
        or outbox.payload != command_payload
    ):
        raise ExecutionServiceError("APPROVAL_ORPHAN_OUTBOX_MISSING") from None
    delivery = repo.get_outbox_delivery(command.command_id)
    if (
        delivery is None
        or delivery.outbox_key != command.command_id
        or delivery.command_id != command.command_id
        or delivery.identity != command.command_id
        or delivery.payload != command_payload
        or delivery.state
        not in {
            OutboxDeliveryState.PENDING,
            OutboxDeliveryState.LEASED,
            OutboxDeliveryState.SENT,
            OutboxDeliveryState.UNKNOWN,
        }
    ):
        raise ExecutionServiceError("APPROVAL_ORPHAN_DELIVERY_MISSING") from None


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parse(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    value: object = None
    try:
        value = json.loads(payload.decode("utf-8"))
    except Exception:
        pass
    if type(value) is not dict or _canonical(value) != payload:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _exact_keys(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _str(value: object) -> str:
    if type(value) is not str or not value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return value


def _decimal(value: object, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    parsed: Decimal | None = None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        pass
    if parsed is None or not parsed.is_finite() or format(parsed, "f") != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _date(value: object) -> dt.date:
    parsed: dt.date | None = None
    try:
        if type(value) is str:
            parsed = dt.date.fromisoformat(value)
    except ValueError:
        pass
    if parsed is None or parsed.isoformat() != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _datetime(value: object) -> dt.datetime:
    parsed: dt.datetime | None = None
    try:
        if type(value) is str and value.endswith("Z"):
            parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        pass
    if parsed is None or _datetime_text(parsed) != value:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    return parsed


def _datetime_text(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _enum(cls: type[object], value: object) -> object:
    if type(value) is not str:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID")
    try:
        return cls(value)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID") from None


def _decode_command(payload: bytes) -> OrderCommand:
    try:
        return decode_order_command(payload)
    except WireError:
        raise ExecutionServiceError("SERVICE_PAYLOAD_INVALID") from None


def _encode_counter(counter: DailyRiskCounters) -> bytes:
    return _canonical(
        {"counter": counter.to_persistable_dict(), "schema_version": _COUNTER_SCHEMA}
    )


def _decode_counter(record: StoredRecord, session_date: dt.date) -> DailyRiskCounters:
    root = _exact_keys(_parse(record.payload), {"schema_version", "counter"})
    raw = _exact_keys(
        root["counter"], {"session_date", "order_count", "cancel_count", "buy_notional"}
    )
    if root["schema_version"] != _COUNTER_SCHEMA or record.identity != _digest(record.payload):
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID")
    try:
        counter = DailyRiskCounters(
            session_date=_date(raw["session_date"]),
            order_count=_int(raw["order_count"]),
            cancel_count=_int(raw["cancel_count"]),
            buy_notional=_decimal(raw["buy_notional"]),  # type: ignore[arg-type]
        )
    except Exception:
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID") from None
    if counter.session_date != session_date or _encode_counter(counter) != record.payload:
        raise ExecutionServiceError("SERVICE_COUNTER_INVALID")
    return counter


def _encode_stage(risk: RiskDecision) -> bytes:
    try:
        return encode_execution_stage(risk)
    except Exception:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID") from None


def _put_risk_receipt(
    repo: ExecutionRepository, receipt: DurableRiskTransitionReceipt
) -> None:
    payload = encode_risk_receipt(receipt)
    repo.put_risk_transition_receipt(
        sequence=receipt.sequence,
        transition_kind=receipt.transition_kind,
        subject_id=receipt.subject_id,
        receipt_id=receipt.receipt_id,
        previous_receipt_id=receipt.previous_receipt_id,
        risk_counter_key=receipt.risk_counter_key,
        predecessor_counter_identity=receipt.predecessor_counter_identity,
        projected_counter_identity=receipt.projected_counter_identity,
        payload=payload,
    )


def _decode_stored_risk_receipt(
    row: StoredRiskTransitionReceipt | None,
) -> DurableRiskTransitionReceipt:
    if row is None:
        raise ExecutionServiceError("SERVICE_RISK_RECEIPT_INVALID") from None
    failed = False
    receipt: DurableRiskTransitionReceipt | None = None
    try:
        receipt = decode_risk_receipt(row.payload)
        if (
            row.sequence != receipt.sequence
            or row.transition_kind != receipt.transition_kind
            or row.subject_id != receipt.subject_id
            or row.receipt_id != receipt.receipt_id
            or row.previous_receipt_id != receipt.previous_receipt_id
            or row.risk_counter_key != receipt.risk_counter_key
            or row.predecessor_counter_identity
            != receipt.predecessor_counter_identity
            or row.projected_counter_identity != receipt.projected_counter_identity
        ):
            raise ValueError
    except Exception:
        failed = True
    if failed or receipt is None:
        raise ExecutionServiceError("SERVICE_RISK_RECEIPT_INVALID") from None
    return receipt


def _next_risk_receipt_position(
    tail: StoredRiskTransitionReceipt | None,
) -> tuple[int, str]:
    if tail is None:
        return 1, GENESIS_RECEIPT_ID
    receipt = _decode_stored_risk_receipt(tail)
    return receipt.sequence + 1, receipt.receipt_id


def _require_order_receipt(
    row: StoredRiskTransitionReceipt | None,
    risk: RiskDecision,
    *,
    expected_counter_key: str,
) -> None:
    receipt = _decode_stored_risk_receipt(row)
    decision = receipt.decision
    if (
        receipt.transition_kind != "ORDER"
        or receipt.risk_counter_key != expected_counter_key
        or type(decision) is not DurableOrderRiskDecision
        or decision.accepted != risk.accepted
        or decision.plan_id != risk.plan_id
        or decision.rule_results != risk.rule_results
        or decision.approved_intent_ids != risk.approved_intent_ids
        or decision.command_ids != tuple(item.command_id for item in risk.commands)
        or decision.projected_counters != risk.projected_counters
        or decision.requires_manual_approval != risk.requires_manual_approval
    ):
        raise ExecutionServiceError("SERVICE_RISK_RECEIPT_INVALID") from None


def _verify_replay_risk_chain(
    repo: ExecutionRepository, *, expected_counter_key: str
) -> tuple[DurableRiskTransitionReceipt, ...]:
    failed = False
    result: tuple[DurableRiskTransitionReceipt, ...] = ()
    try:
        rows = repo.read_recovery_rows()
        commands: list[OrderCommand] = []
        for row in rows.commands:
            command = _decode_command(row.payload)
            if (
                row.key != command.command_id
                or row.identity != command.command_id
                or encode_order_command(command) != row.payload
            ):
                raise ValueError
            commands.append(command)
        cancels: list[CancelCommand] = []
        for cancel_row in rows.cancel_commands:
            cancel = _decode_stored_cancel(cancel_row.payload, cancel_row.cancel_id)
            if (
                cancel_row.command_id != cancel.command_id
                or cancel_row.identity != cancel.cancel_id
                or encode_cancel_command(cancel) != cancel_row.payload
            ):
                raise ValueError
            cancels.append(cancel)
        receipts = tuple(
            _decode_stored_risk_receipt(row)
            for row in rows.risk_transition_receipts
        )
        allowed_zeros = _prove_zero_order_allow_set(
            repo,
            receipts=receipts,
            approval_receipts=rows.approval_receipts,
        )
        verify_risk_receipt_semantic_closure(
            receipts=receipts,
            commands=tuple(commands),
            cancel_commands=tuple(cancels),
            allowed_zero_order_subject_ids=allowed_zeros,
        )
        key_receipts = tuple(
            item for item in receipts if item.risk_counter_key == expected_counter_key
        )
        if not key_receipts:
            raise ValueError
        tail = key_receipts[-1]
        counter_row = repo.get_scoped_daily_risk_counters(expected_counter_key)
        projected = tail.decision.projected_counters
        projected_payload = _encode_counter(projected)
        if (
            counter_row is None
            or counter_row.identity != tail.projected_counter_identity
            or counter_row.identity != _digest(projected_payload)
            or counter_row.payload != projected_payload
        ):
            raise ValueError
        result = receipts
    except StoreError:
        raise
    except Exception:
        failed = True
    if failed:
        raise ExecutionServiceError("SERVICE_RISK_RECEIPT_INVALID") from None
    return result


def _prove_zero_order_allow_set(
    repo: ExecutionRepository,
    *,
    receipts: tuple[DurableRiskTransitionReceipt, ...],
    approval_receipts: tuple[StoredApprovalReceipt, ...],
) -> frozenset[str]:
    """Prove approval+stage ownership for every empty-command ORDER receipt."""
    by_plan = {
        item.plan_identity: item
        for item in approval_receipts
    }
    if len(by_plan) != len(approval_receipts):
        raise ValueError
    allowed: set[str] = set()
    for receipt in receipts:
        if receipt.transition_kind != "ORDER":
            continue
        decision = receipt.decision
        if type(decision) is not DurableOrderRiskDecision:
            raise ValueError
        if decision.command_ids:
            continue
        if receipt.subject_id != decision.plan_id:
            raise ValueError
        stored = by_plan.get(receipt.subject_id)
        if stored is None:
            raise ValueError
        decoded = decode_approval_receipt(stored.payload)
        if (
            stored.receipt_id != decoded.receipt_id
            or stored.identity != decoded.receipt_id
            or stored.schema_version != decoded.schema_version
            or stored.classification != decoded.classification
            or stored.credential_kind != decoded.credential_kind
            or stored.credential_id != decoded.credential_id
            or stored.operator_id != decoded.operator_id
            or stored.session_date != decoded.session_date
            or stored.action != decoded.action
            or stored.action != FORMAL_APPROVAL_ACTION
            or stored.plan_identity != decoded.plan_identity
            or stored.plan_identity != receipt.subject_id
            or stored.challenge_identity != decoded.challenge_identity
            or stored.store_recovery_identity != decoded.store_recovery_identity
            or stored.source_identities_digest != decoded.source_identities_digest
            or stored.issued_at != decoded.issued_at
            or stored.nonce != decoded.nonce
        ):
            raise ValueError
        stage = repo.get_execution_stage(receipt.subject_id)
        expected_payload = encode_execution_stage(decision)
        if (
            stage is None
            or stage.key != receipt.subject_id
            or stage.identity != _digest(expected_payload)
            or stage.payload != expected_payload
        ):
            raise ValueError
        allowed.add(receipt.subject_id)
    return frozenset(allowed)


def _require_cancel_receipt(
    row: StoredRiskTransitionReceipt | None,
    *, cancel_id: str, command_id: str, counter_key: str, policy_identity: str,
) -> DurableCancelRiskDecision:
    receipt = _decode_stored_risk_receipt(row)
    decision = receipt.decision
    if (
        receipt.transition_kind != "CANCEL"
        or type(decision) is not DurableCancelRiskDecision
        or receipt.risk_counter_key != counter_key
        or decision.cancel_id != cancel_id
        or decision.command_id != command_id
        or decision.policy_identity != policy_identity
    ):
        raise ExecutionServiceError("CANCEL_RECOVERY_CLOSURE_INVALID") from None
    return decision


def _decode_stage(
    record: StoredRecord,
    plan: OrderPlan,
    session_date: dt.date,
    repo: ExecutionRepository,
) -> RiskDecision:
    root = _exact_keys(
        _parse(record.payload),
        {
            "schema_version", "accepted", "approved_intent_ids", "command_ids",
            "plan_id", "projected_counters", "requires_manual_approval", "rule_results",
        },
    )
    if (
        root["schema_version"] != _STAGE_SCHEMA
        or root["plan_id"] != plan.plan_id
        or record.key != plan.plan_id
        or record.identity != _digest(record.payload)
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    if type(root["approved_intent_ids"]) is not list or type(root["command_ids"]) is not list:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    approved = tuple(_str(item) for item in root["approved_intent_ids"])
    command_ids = tuple(_str(item) for item in root["command_ids"])
    intents = {item.intent_id: item for item in plan.intents}
    intent_ids = set(intents)
    if len(set(approved)) != len(approved) or not set(approved) <= intent_ids:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    commands: list[OrderCommand] = []
    for command_id in command_ids:
        row = repo.get_command(command_id)
        if row is None or row.key != command_id or row.identity != command_id:
            raise ExecutionServiceError("SERVICE_STAGE_INVALID")
        command = _decode_command(row.payload)
        if (
            command.intent.intent_id not in approved
            or command.intent.plan_id != plan.plan_id
            or command.intent != intents[command.intent.intent_id]
            or command.mode is not ExecutionMode.PAPER
        ):
            raise ExecutionServiceError("SERVICE_STAGE_INVALID")
        commands.append(command)
    if (
        len({item.command_id for item in commands}) != len(commands)
        or commands
        and tuple(item.intent.intent_id for item in commands) != approved
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    raw_counters = _exact_keys(
        root["projected_counters"],
        {"session_date", "order_count", "cancel_count", "buy_notional"},
    )
    counters = DailyRiskCounters(
        session_date=_date(raw_counters["session_date"]),
        order_count=_int(raw_counters["order_count"]),
        cancel_count=_int(raw_counters["cancel_count"]),
        buy_notional=_decimal(raw_counters["buy_notional"]),  # type: ignore[arg-type]
    )
    raw_rules = root["rule_results"]
    if type(raw_rules) is not list:
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    rules: list[RiskRuleResult] = []
    for item in raw_rules:
        raw = _exact_keys(item, {"rule", "accepted", "code", "subject", "detail"})
        rules.append(
            RiskRuleResult(
                rule=_str(raw["rule"]),
                accepted=_bool(raw["accepted"]),
                code=_str(raw["code"]),
                subject=_str(raw["subject"]),
                detail=_str(raw["detail"]),
            )
        )
    risk = RiskDecision(
        accepted=_bool(root["accepted"]),
        plan_id=plan.plan_id,
        rule_results=tuple(rules),
        approved_intent_ids=approved,
        commands=tuple(commands),
        projected_counters=counters,
        requires_manual_approval=_bool(root["requires_manual_approval"]),
    )
    if (
        counters.session_date != session_date
        or bool(commands) and risk.requires_manual_approval
        or plan.intents and risk.accepted != bool(approved)
        or _encode_stage(risk) != record.payload
    ):
        raise ExecutionServiceError("SERVICE_STAGE_INVALID")
    return risk


def _decode_aggregate(record: StoredRecord, command: OrderCommand) -> OrderAggregate:
    if record.identity != _digest(record.payload):
        raise ExecutionServiceError("SERVICE_AGGREGATE_INVALID")
    try:
        return decode_order_aggregate(record.payload, command=command)
    except WireError:
        raise ExecutionServiceError("SERVICE_AGGREGATE_INVALID") from None
