"""Durable, independent PAPER gateway and broker evidence adapter."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from decimal import Decimal

from quant.backtest.costs import ExecutionCostSchedule
from quant.backtest.fx import FxSnapshot
from quant.domain.canonical_wire import canonical_json_bytes
from quant.domain.enums import ExecutionEventType, OrderSide
from quant.execution.cli_ports import (
    VerifiedBrokerEvidence,
    VerifiedPaperGateway,
    build_verified_broker_evidence,
    build_verified_paper_gateway,
)
from quant.execution.contracts import (
    AccountSnapshot,
    CancelCommand,
    CashBalance,
    ExecutionEvent,
    OrderCommand,
    PositionBalance,
    build_account_snapshot,
    build_money_amount,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayContractError,
    GatewayCancelResult,
    GatewayDispatchResult,
    validate_gateway_cancel,
    validate_gateway_submit,
    verify_gateway_cancel_result,
    verify_gateway_dispatch_result,
)
from quant.execution.gateways.paper import (
    PaperClock,
    PaperFaultPlan,
    PaperFillPolicy,
    PaperGateway,
)
from quant.execution.paper_broker_store import (
    PaperBrokerPolicyDescriptor,
    PaperBrokerStore,
    PaperBrokerStoreError,
    build_formal_paper_broker_policy_descriptor,
    build_paper_broker_policy_descriptor,
)
from quant.execution.paper_broker_binding import (
    VerifiedFormalPaperBrokerPolicyBinding,
)
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.wire import (
    decode_execution_event,
    encode_cancel_command,
    encode_execution_event,
    encode_order_command,
)


class DurablePaperGatewayError(ValueError):
    """Stable, sanitized durable adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    @property
    def __context__(self) -> None:
        """Never expose a policy, codec, SQL or path implementation error."""
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


class DurablePaperGateway:
    """Persist-before-return transport backed only by PaperBrokerStore."""

    def __init__(
        self, *, store: PaperBrokerStore, clock: PaperClock,
        fill_policy: PaperFillPolicy, fault_plan: PaperFaultPlan,
        cost_schedule: ExecutionCostSchedule, fx_snapshot: FxSnapshot | None,
    ) -> None:
        if type(store) is not PaperBrokerStore:
            raise DurablePaperGatewayError("PAPER_BROKER_STORE_INVALID")
        store.verify_fresh()
        self._store = store
        self._clock = clock
        self._fill_policy = fill_policy
        self._fault_plan = fault_plan
        self._cost_schedule = cost_schedule
        self._fx_snapshot = fx_snapshot

    def submit(
        self, *, command: OrderCommand, dispatch_attempt: int, now: dt.datetime,
    ) -> GatewayDispatchResult:
        error: DurablePaperGatewayError | None = None
        try:
            return self._submit(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
        except (DurablePaperGatewayError, PaperBrokerStoreError, GatewayContractError):
            raise
        except Exception:
            error = DurablePaperGatewayError("PAPER_BROKER_DISPATCH_FAILED")
        assert error is not None
        raise error

    def _submit(
        self, *, command: OrderCommand, dispatch_attempt: int, now: dt.datetime,
    ) -> GatewayDispatchResult:
        validate_gateway_submit(command, dispatch_attempt, now)
        request = encode_order_command(command)
        retained = self._store.retained_operation(command.command_id)
        if retained is not None:
            if retained.kind != "SUBMIT" or retained.request_digest != hashlib.sha256(request).hexdigest():
                raise DurablePaperGatewayError("PAPER_BROKER_OPERATION_CONFLICT")
            if retained.dispatch_attempt != dispatch_attempt:
                if retained.certainty is DispatchCertainty.UNKNOWN:
                    return GatewayDispatchResult(command.command_id, dispatch_attempt, DispatchCertainty.UNKNOWN, ())
                raise DurablePaperGatewayError("PAPER_BROKER_ATTEMPT_STALE")
            return verify_gateway_dispatch_result(command, dispatch_attempt, now, _decode_submit_result(retained.result_payload, command))
        gateway = self._ephemeral()
        result = gateway.submit(command=command, dispatch_attempt=dispatch_attempt, now=now)
        callbacks = _unique_callbacks(result.callbacks)
        predecessor, predecessor_digest = self._store.read_predecessor()
        account = _apply_callbacks(predecessor, command, callbacks)
        result_payload = _submit_result_wire(result)
        self._store.persist_operation(
            operation_id=command.command_id, kind="SUBMIT", dispatch_attempt=dispatch_attempt,
            request_payload=request, certainty=result.certainty, result_payload=result_payload,
            command_payload=request, callbacks=result.callbacks, account=account,
            predecessor_state_digest=predecessor_digest,
        )
        return verify_gateway_dispatch_result(command, dispatch_attempt, now, _decode_submit_result(result_payload, command))

    def cancel(
        self, *, command: CancelCommand, dispatch_attempt: int, now: dt.datetime,
    ) -> GatewayCancelResult:
        error: DurablePaperGatewayError | None = None
        try:
            return self._cancel(
                command=command, dispatch_attempt=dispatch_attempt, now=now
            )
        except (DurablePaperGatewayError, PaperBrokerStoreError, GatewayContractError):
            raise
        except Exception:
            error = DurablePaperGatewayError("PAPER_BROKER_CANCEL_FAILED")
        assert error is not None
        raise error

    def _cancel(
        self, *, command: CancelCommand, dispatch_attempt: int, now: dt.datetime,
    ) -> GatewayCancelResult:
        validate_gateway_cancel(command, dispatch_attempt, now)
        request = encode_cancel_command(command)
        retained = self._store.retained_operation(command.cancel_id)
        source = _source_command(self._store, command.command_id)
        snapshot = PaperGateway._cancel_snapshot(source, command)
        if retained is not None:
            if retained.kind != "CANCEL" or retained.request_digest != hashlib.sha256(request).hexdigest():
                raise DurablePaperGatewayError("PAPER_BROKER_OPERATION_CONFLICT")
            if retained.dispatch_attempt != dispatch_attempt:
                if retained.certainty is DispatchCertainty.UNKNOWN:
                    return GatewayCancelResult(command.cancel_id, dispatch_attempt, DispatchCertainty.UNKNOWN, ())
                raise DurablePaperGatewayError("PAPER_BROKER_ATTEMPT_STALE")
            return verify_gateway_cancel_result(source, command, snapshot, dispatch_attempt, now, _decode_cancel_result(retained.result_payload, source))
        result = self._ephemeral().cancel(command=command, dispatch_attempt=dispatch_attempt, now=now)
        callbacks = _unique_callbacks(result.callbacks)
        predecessor, predecessor_digest = self._store.read_predecessor()
        account = _apply_callbacks(predecessor, source, callbacks)
        result_payload = _cancel_result_wire(result)
        self._store.persist_operation(
            operation_id=command.cancel_id, kind="CANCEL", dispatch_attempt=dispatch_attempt,
            request_payload=request, certainty=result.certainty, result_payload=result_payload,
            command_payload=encode_order_command(source), callbacks=result.callbacks, account=account,
            predecessor_state_digest=predecessor_digest,
        )
        return verify_gateway_cancel_result(source, command, snapshot, dispatch_attempt, now, _decode_cancel_result(result_payload, source))

    def _ephemeral(self) -> PaperGateway:
        return PaperGateway(
            clock=self._clock, fill_policy=self._fill_policy, fault_plan=self._fault_plan,
            cost_schedule=self._cost_schedule, fx_snapshot=self._fx_snapshot,
            recovered_commands=self._store.all_commands(),
        )


class DurablePaperGatewayFactory:
    """Production-candidate implementation of the existing PAPER factory port."""

    def __init__(
        self, *, store: PaperBrokerStore, policy: PaperBrokerPolicyDescriptor,
        clock: PaperClock, fill_policy: PaperFillPolicy, fault_plan: PaperFaultPlan,
        cost_schedule: ExecutionCostSchedule, fx_snapshot: FxSnapshot | None,
    ) -> None:
        expected = build_paper_broker_policy_descriptor(
            adapter_policy_version=policy.adapter_policy_version,
            fill_policy_version=policy.fill_policy_version,
            fault_policy_version=policy.fault_policy_version,
            finality_policy_version=policy.finality_policy_version,
            cost_schedule=cost_schedule, fx_snapshot=fx_snapshot,
        )
        if type(policy) is not PaperBrokerPolicyDescriptor or expected != policy:
            raise DurablePaperGatewayError("PAPER_BROKER_POLICY_INVALID")
        self._bind(
            store=store,
            policy=policy,
            clock=clock,
            fill_policy=fill_policy,
            fault_plan=fault_plan,
            cost_schedule=cost_schedule,
            fx_snapshot=fx_snapshot,
        )

    @classmethod
    def _from_formal(
        cls,
        *,
        store: PaperBrokerStore,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        clock: PaperClock,
        fill_policy: PaperFillPolicy,
        fault_plan: PaperFaultPlan,
    ) -> DurablePaperGatewayFactory:
        """Construct from the sole B1-issued formal policy descriptor path."""
        descriptor = build_formal_paper_broker_policy_descriptor(
            policy=policy, binding=binding
        )
        result = cls.__new__(cls)
        result._bind(
            store=store,
            policy=descriptor,
            clock=clock,
            fill_policy=fill_policy,
            fault_plan=fault_plan,
            cost_schedule=policy.execution_cost_schedule,
            fx_snapshot=None,
        )
        return result

    def _bind(
        self,
        *,
        store: PaperBrokerStore,
        policy: PaperBrokerPolicyDescriptor,
        clock: PaperClock,
        fill_policy: PaperFillPolicy,
        fault_plan: PaperFaultPlan,
        cost_schedule: ExecutionCostSchedule,
        fx_snapshot: FxSnapshot | None,
    ) -> None:
        if type(store) is not PaperBrokerStore:
            raise DurablePaperGatewayError("PAPER_BROKER_STORE_INVALID")
        store.verify_fresh()
        if store.policy_identity != policy.descriptor_identity:
            raise DurablePaperGatewayError("PAPER_BROKER_POLICY_INVALID")
        self._store = store
        self._policy = policy
        self._clock = clock
        self._fill_policy = fill_policy
        self._fault_plan = fault_plan
        self._cost_schedule = cost_schedule
        self._fx_snapshot = fx_snapshot

    def identity(self) -> str:
        self._store.verify_fresh()
        return self._store.gateway_identity

    def open(self) -> VerifiedPaperGateway:
        identity = self.identity()
        gateway = DurablePaperGateway(
            store=self._store, clock=self._clock, fill_policy=self._fill_policy,
            fault_plan=self._fault_plan, cost_schedule=self._cost_schedule,
            fx_snapshot=self._fx_snapshot,
        )
        return build_verified_paper_gateway(gateway_identity=identity, submit=gateway, cancel=gateway)


class DurablePaperBrokerSnapshotPort:
    """Fresh broker evidence reconstructed exclusively from broker storage."""

    def __init__(self, *, store: PaperBrokerStore) -> None:
        if type(store) is not PaperBrokerStore:
            raise DurablePaperGatewayError("PAPER_BROKER_STORE_INVALID")
        store.verify_fresh()
        self._store = store

    def query_and_verify(self, *, gateway_identity: str) -> VerifiedBrokerEvidence:
        if gateway_identity != self._store.gateway_identity:
            raise DurablePaperGatewayError("PAPER_BROKER_GATEWAY_IDENTITY_MISMATCH")
        account, orders, events, as_of, source_identity, finality = (
            self._store.read_evidence_snapshot()
        )
        return build_verified_broker_evidence(
            source_identity=source_identity, gateway_identity=gateway_identity,
            as_of=as_of, finality=finality, account=account, orders=orders, events=events,
        )


def _source_command(store: PaperBrokerStore, command_id: str) -> OrderCommand:
    for command in store.all_commands():
        if command.command_id == command_id:
            return command
    raise DurablePaperGatewayError("PAPER_SOURCE_COMMAND_MISSING")


def _unique_callbacks(values: tuple[ExecutionEvent, ...]) -> tuple[ExecutionEvent, ...]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value.event_id not in seen:
            result.append(value)
            seen.add(value.event_id)
    return tuple(result)


def _apply_callbacks(account: AccountSnapshot, command: OrderCommand, events: tuple[ExecutionEvent, ...]) -> AccountSnapshot:
    positions = {(item.market, item.symbol): item for item in account.positions}
    cash = {item.currency: item for item in account.cash}
    as_of = account.as_of
    for event in events:
        as_of = max(as_of, event.occurred_at)
        if event.event_type not in {ExecutionEventType.FILL, ExecutionEventType.PARTIAL_FILL}:
            continue
        if event.last_price is None or event.last_quantity <= 0:
            raise DurablePaperGatewayError("PAPER_BROKER_STATE_INVALID")
        intent = command.intent
        quote = intent.quote_currency
        current_cash = cash.get(quote, CashBalance(quote, Decimal(0), Decimal(0), Decimal(0), Decimal(0)))
        fees = sum((fee.amount.amount for fee in event.fees if fee.amount.currency is quote), Decimal(0))
        notional = event.last_price * event.last_quantity
        key = (intent.market, intent.symbol)
        current_position = positions.get(key)
        if intent.side is OrderSide.BUY:
            debit = notional + fees
            if current_cash.settled < debit or current_cash.available < debit:
                raise DurablePaperGatewayError("PAPER_BROKER_CASH_INSUFFICIENT")
            old_quantity = 0 if current_position is None else current_position.quantity
            old_value = Decimal(0) if current_position is None else current_position.avg_cost.amount * old_quantity
            quantity = old_quantity + event.last_quantity
            positions[key] = PositionBalance(
                intent.symbol, intent.market, quantity,
                (0 if current_position is None else current_position.sellable_quantity),
                build_money_amount(quote, (old_value + notional + fees) / quantity),
            )
            cash[quote] = CashBalance(quote, current_cash.settled - debit, current_cash.available - debit, current_cash.receivable, current_cash.payable)
        else:
            if current_position is None or current_position.quantity < event.last_quantity or current_position.sellable_quantity < event.last_quantity:
                raise DurablePaperGatewayError("PAPER_BROKER_POSITION_INSUFFICIENT")
            quantity = current_position.quantity - event.last_quantity
            if quantity:
                positions[key] = PositionBalance(intent.symbol, intent.market, quantity, current_position.sellable_quantity - event.last_quantity, current_position.avg_cost)
            else:
                positions.pop(key)
            credit = notional - fees
            cash[quote] = CashBalance(quote, current_cash.settled + credit, current_cash.available + credit, current_cash.receivable, current_cash.payable)
    return build_account_snapshot(as_of=as_of, positions=tuple(positions.values()), cash=tuple(cash.values()))


def _event_token(event: ExecutionEvent) -> str:
    return base64.b64encode(encode_execution_event(event)).decode("ascii")


def _submit_result_wire(value: GatewayDispatchResult) -> bytes:
    return canonical_json_bytes({"callbacks": [_event_token(item) for item in value.callbacks], "certainty": value.certainty.value, "command_id": value.command_id, "dispatch_attempt": value.dispatch_attempt, "schema_version": "paper-submit-result-v1"})


def _cancel_result_wire(value: GatewayCancelResult) -> bytes:
    return canonical_json_bytes({"callbacks": [_event_token(item) for item in value.callbacks], "cancel_id": value.cancel_id, "certainty": value.certainty.value, "dispatch_attempt": value.dispatch_attempt, "schema_version": "paper-cancel-result-v1"})


def _decode_submit_result(payload: bytes, command: OrderCommand) -> GatewayDispatchResult:
    try:
        value = json.loads(payload)
        if canonical_json_bytes(value) != payload or set(value) != {"callbacks", "certainty", "command_id", "dispatch_attempt", "schema_version"} or value["schema_version"] != "paper-submit-result-v1":
            raise ValueError
        callbacks = tuple(decode_execution_event(base64.b64decode(item, validate=True), command=command) for item in value["callbacks"])
        result = GatewayDispatchResult(str(value["command_id"]), int(value["dispatch_attempt"]), DispatchCertainty(value["certainty"]), callbacks)
        if _submit_result_wire(result) != payload:
            raise ValueError
        return result
    except Exception:
        raise DurablePaperGatewayError("PAPER_BROKER_RESULT_INVALID") from None


def _decode_cancel_result(payload: bytes, command: OrderCommand) -> GatewayCancelResult:
    try:
        value = json.loads(payload)
        if canonical_json_bytes(value) != payload or set(value) != {"callbacks", "cancel_id", "certainty", "dispatch_attempt", "schema_version"} or value["schema_version"] != "paper-cancel-result-v1":
            raise ValueError
        callbacks = tuple(decode_execution_event(base64.b64decode(item, validate=True), command=command) for item in value["callbacks"])
        result = GatewayCancelResult(str(value["cancel_id"]), int(value["dispatch_attempt"]), DispatchCertainty(value["certainty"]), callbacks)
        if _cancel_result_wire(result) != payload:
            raise ValueError
        return result
    except Exception:
        raise DurablePaperGatewayError("PAPER_BROKER_RESULT_INVALID") from None


__all__ = [
    "DurablePaperBrokerSnapshotPort", "DurablePaperGateway",
    "DurablePaperGatewayError", "DurablePaperGatewayFactory",
]
