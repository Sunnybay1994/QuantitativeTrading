"""Deterministic, in-memory PAPER gateway adapter.

The adapter implements the durable gateway transport contracts without owning
IO or persistence.  Every source of time, fills and transport faults is
injected, so a recovered process can reproduce the same callback identities.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from quant.backtest.costs import ExecutionCostSchedule, calculate_execution_cost
from quant.backtest.fx import FxSnapshot
from quant.domain.enums import ExecutionEventType, OrderSide
from quant.execution.contracts import (
    CancelCommand,
    ExecutionEvent,
    FeeComponent,
    OrderCommand,
    build_execution_event,
    build_order_command_identity,
    build_order_intent_identity,
)
from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelResult,
    GatewayDispatchResult,
    validate_gateway_cancel,
    validate_gateway_submit,
    verify_gateway_cancel_result,
    verify_gateway_dispatch_result,
)
from quant.execution.oms import OrderAggregate, new_order_aggregate, reduce_order

_PAPER_REJECT_CODES = frozenset({"PAPER_RULE_REJECT"})


class PaperGatewayError(ValueError):
    """Stable, sanitized PAPER adapter failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PaperFill:
    """One incremental deterministic fill requested by a fill policy."""

    quantity: int
    price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.quantity) is not int
            or self.quantity <= 0
            or type(self.price) is not Decimal
            or not self.price.is_finite()
            or self.price <= 0
        ):
            raise PaperGatewayError("PAPER_FILL_INVALID")


@dataclass(frozen=True, slots=True)
class PaperSubmitPlan:
    """Submit disposition: broker rejection or an accepted fill sequence."""

    fills: tuple[PaperFill, ...] = ()
    reject_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.fills) is not tuple or any(
            type(item) is not PaperFill for item in self.fills
        ):
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        if self.reject_code is not None and (
            type(self.reject_code) is not str
            or self.reject_code not in _PAPER_REJECT_CODES
            or self.fills
        ):
            raise PaperGatewayError("PAPER_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class PaperCancelPlan:
    """Late fills observed after cancel acceptance and optional final cancel."""

    late_fills: tuple[PaperFill, ...] = ()
    confirm_cancel: bool = True

    def __post_init__(self) -> None:
        if type(self.late_fills) is not tuple or any(
            type(item) is not PaperFill for item in self.late_fills
        ):
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        if type(self.confirm_cancel) is not bool:
            raise PaperGatewayError("PAPER_POLICY_INVALID")


class PaperClock(Protocol):
    """Content-addressed event clock supplied by tests or an operator service."""

    def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
        """Return the stable timestamp for one operation event ordinal."""
        ...


@runtime_checkable
class _DispatchAnchoredPaperClock(Protocol):
    """Clock whose event time is anchored to one explicit dispatch observation."""

    def event_time_for_dispatch(
        self,
        *,
        operation_id: str,
        event_ordinal: int,
        observed_at: dt.datetime,
    ) -> dt.datetime:
        """Return an event time derived from the caller-provided dispatch time."""
        ...


class PaperFillPolicy(Protocol):
    """Pure policy that describes submit fills and cancel/fill races."""

    def plan_submit(self, *, command: OrderCommand) -> PaperSubmitPlan:
        """Return a deterministic plan for one command identity."""
        ...

    def plan_cancel(
        self, *, command: OrderCommand, cancel: CancelCommand
    ) -> PaperCancelPlan:
        """Return a deterministic plan for one durable cancel identity."""
        ...


class PaperFaultPlan(Protocol):
    """Injected transport certainty and exact-duplicate callback plan."""

    def submit_certainty(
        self, *, command_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        """Return whether one submit crossed the adapter boundary."""
        ...

    def cancel_certainty(
        self, *, cancel_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        """Return whether one cancel crossed the adapter boundary."""
        ...

    def duplicate_callback_ordinals(
        self, *, operation_id: str
    ) -> tuple[int, ...]:
        """Select callbacks that should be repeated byte-for-byte."""
        ...


class PaperGateway:
    """Deterministic implementation of submit and cancel transport protocols."""

    def __init__(
        self,
        *,
        clock: PaperClock,
        fill_policy: PaperFillPolicy,
        fault_plan: PaperFaultPlan,
        cost_schedule: ExecutionCostSchedule,
        fx_snapshot: FxSnapshot | None,
        recovered_commands: tuple[OrderCommand, ...] = (),
    ) -> None:
        if type(recovered_commands) is not tuple:
            raise PaperGatewayError("PAPER_INPUT_INVALID")
        self._clock = clock
        self._fill_policy = fill_policy
        self._fault_plan = fault_plan
        self._cost_schedule = cost_schedule
        self._fx_snapshot = fx_snapshot
        self._commands: dict[str, OrderCommand] = {}
        self._submit_callbacks: dict[str, tuple[ExecutionEvent, ...]] = {}
        self._cancel_callbacks: dict[str, tuple[ExecutionEvent, ...]] = {}
        self._sent_operations: set[str] = set()
        self._unknown_operations: set[str] = set()
        for command in recovered_commands:
            self._register_command(command)

    def submit(
        self,
        *,
        command: OrderCommand,
        dispatch_attempt: int,
        now: dt.datetime,
    ) -> GatewayDispatchResult:
        """Submit a PAPER command under the existing attempt fence."""
        validate_gateway_submit(command, dispatch_attempt, now)
        self._register_command(command)
        certainty = (
            DispatchCertainty.UNKNOWN
            if command.command_id in self._unknown_operations
            else self._fence_certainty(
                command.command_id,
                self._submit_certainty(command.command_id, dispatch_attempt),
            )
        )
        if certainty is not DispatchCertainty.SENT:
            result = GatewayDispatchResult(
                command_id=command.command_id,
                dispatch_attempt=dispatch_attempt,
                certainty=certainty,
                callbacks=(),
            )
            return verify_gateway_dispatch_result(command, dispatch_attempt, now, result)

        callbacks = self._submit_callbacks.get(command.command_id)
        if callbacks is None:
            callbacks = self._build_submit_callbacks(command, observed_at=now)
            self._submit_callbacks[command.command_id] = callbacks
        visible = tuple(event for event in callbacks if event.occurred_at <= now)
        result = GatewayDispatchResult(
            command_id=command.command_id,
            dispatch_attempt=dispatch_attempt,
            certainty=certainty,
            callbacks=visible,
        )
        return verify_gateway_dispatch_result(command, dispatch_attempt, now, result)

    def cancel(
        self,
        *,
        command: CancelCommand,
        dispatch_attempt: int,
        now: dt.datetime,
    ) -> GatewayCancelResult:
        """Dispatch a durable cancel against a known or recovered source command."""
        validate_gateway_cancel(command, dispatch_attempt, now)
        source = self._commands.get(command.command_id)
        if source is None:
            raise PaperGatewayError("PAPER_SOURCE_COMMAND_MISSING")
        snapshot = self._cancel_snapshot(source, command)
        certainty = (
            DispatchCertainty.UNKNOWN
            if command.cancel_id in self._unknown_operations
            else self._fence_certainty(
                command.cancel_id,
                self._cancel_certainty(command.cancel_id, dispatch_attempt),
            )
        )
        if certainty is not DispatchCertainty.SENT:
            result = GatewayCancelResult(
                cancel_id=command.cancel_id,
                dispatch_attempt=dispatch_attempt,
                certainty=certainty,
                callbacks=(),
            )
            return verify_gateway_cancel_result(
                source, command, snapshot, dispatch_attempt, now, result
            )

        callbacks = self._cancel_callbacks.get(command.cancel_id)
        if callbacks is None:
            callbacks = self._build_cancel_callbacks(
                source, command, snapshot, observed_at=now
            )
            self._cancel_callbacks[command.cancel_id] = callbacks
        visible = tuple(event for event in callbacks if event.occurred_at <= now)
        result = GatewayCancelResult(
            cancel_id=command.cancel_id,
            dispatch_attempt=dispatch_attempt,
            certainty=certainty,
            callbacks=visible,
        )
        return verify_gateway_cancel_result(
            source, command, snapshot, dispatch_attempt, now, result
        )

    def _register_command(self, command: OrderCommand) -> None:
        invalid = False
        try:
            build_order_intent_identity(command.intent)
            build_order_command_identity(command)
        except Exception:
            invalid = True
        if invalid:
            raise PaperGatewayError("PAPER_INPUT_INVALID")
        previous = self._commands.get(command.command_id)
        if previous is not None and previous != command:
            raise PaperGatewayError("PAPER_INPUT_INVALID")
        self._commands[command.command_id] = command

    def _submit_certainty(
        self, command_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        invalid = False
        certainty: object = None
        try:
            certainty = self._fault_plan.submit_certainty(
                command_id=command_id, dispatch_attempt=dispatch_attempt
            )
        except Exception:
            invalid = True
        if invalid or type(certainty) is not DispatchCertainty:
            raise PaperGatewayError("PAPER_FAULT_PLAN_INVALID")
        return certainty

    def _cancel_certainty(
        self, cancel_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        invalid = False
        certainty: object = None
        try:
            certainty = self._fault_plan.cancel_certainty(
                cancel_id=cancel_id, dispatch_attempt=dispatch_attempt
            )
        except Exception:
            invalid = True
        if invalid or type(certainty) is not DispatchCertainty:
            raise PaperGatewayError("PAPER_FAULT_PLAN_INVALID")
        return certainty

    def _fence_certainty(
        self, operation_id: str, certainty: DispatchCertainty
    ) -> DispatchCertainty:
        if operation_id in self._unknown_operations:
            return DispatchCertainty.UNKNOWN
        if operation_id in self._sent_operations and certainty is not DispatchCertainty.SENT:
            raise PaperGatewayError("PAPER_FAULT_PLAN_INVALID")
        if certainty is DispatchCertainty.UNKNOWN:
            self._unknown_operations.add(operation_id)
        elif certainty is DispatchCertainty.SENT:
            self._sent_operations.add(operation_id)
        return certainty

    def _build_submit_callbacks(
        self, command: OrderCommand, *, observed_at: dt.datetime
    ) -> tuple[ExecutionEvent, ...]:
        plan = self._submit_plan(command)
        callbacks: list[ExecutionEvent] = []
        aggregate = new_order_aggregate(command)
        if plan.reject_code is not None:
            callbacks.append(
                self._event(
                    command=command,
                    operation_id=command.command_id,
                    ordinal=0,
                    broker_order_id=self._broker_order_id(command.command_id),
                    event_type=ExecutionEventType.REJECTED,
                    cumulative_quantity=0,
                    last_quantity=0,
                    last_price=None,
                    fees=(),
                    reject_code=plan.reject_code,
                    not_before=command.intent.generated_at,
                    observed_at=observed_at,
                )
            )
        else:
            broker_order_id = self._broker_order_id(command.command_id)
            callbacks.append(
                self._event(
                    command=command,
                    operation_id=command.command_id,
                    ordinal=0,
                    broker_order_id=broker_order_id,
                    event_type=ExecutionEventType.ACCEPTED,
                    cumulative_quantity=0,
                    last_quantity=0,
                    last_price=None,
                    fees=(),
                    reject_code=None,
                    not_before=command.intent.generated_at,
                    observed_at=observed_at,
                )
            )
            cumulative = 0
            for ordinal, fill in enumerate(plan.fills, start=1):
                self._validate_fill(command, fill, remaining=command.intent.quantity - cumulative)
                cumulative += fill.quantity
                event_type = (
                    ExecutionEventType.FILL
                    if cumulative == command.intent.quantity
                    else ExecutionEventType.PARTIAL_FILL
                )
                callbacks.append(
                    self._event(
                        command=command,
                        operation_id=command.command_id,
                        ordinal=ordinal,
                        broker_order_id=broker_order_id,
                        event_type=event_type,
                        cumulative_quantity=cumulative,
                        last_quantity=fill.quantity,
                        last_price=fill.price,
                        fees=self._fees(command, fill),
                        reject_code=None,
                        not_before=command.intent.generated_at,
                        observed_at=observed_at,
                    )
                )
        aggregate = self._prove_sequence(aggregate, command, tuple(callbacks))
        del aggregate
        return self._with_duplicates(command.command_id, tuple(callbacks))

    def _build_cancel_callbacks(
        self,
        source: OrderCommand,
        cancel: CancelCommand,
        snapshot: OrderAggregate,
        *,
        observed_at: dt.datetime,
    ) -> tuple[ExecutionEvent, ...]:
        plan = self._cancel_plan(source, cancel)
        callbacks: list[ExecutionEvent] = [
            self._event(
                command=source,
                operation_id=cancel.cancel_id,
                ordinal=0,
                broker_order_id=cancel.broker_order_id,
                event_type=ExecutionEventType.CANCEL_ACCEPTED,
                cumulative_quantity=cancel.observed_filled_quantity,
                last_quantity=0,
                last_price=None,
                fees=(),
                reject_code=None,
                not_before=cancel.as_of,
                observed_at=observed_at,
            )
        ]
        cumulative = cancel.observed_filled_quantity
        for ordinal, fill in enumerate(plan.late_fills, start=1):
            self._validate_fill(source, fill, remaining=source.intent.quantity - cumulative)
            cumulative += fill.quantity
            event_type = (
                ExecutionEventType.FILL
                if cumulative == source.intent.quantity
                else ExecutionEventType.PARTIAL_FILL
            )
            callbacks.append(
                self._event(
                    command=source,
                    operation_id=cancel.cancel_id,
                    ordinal=ordinal,
                    broker_order_id=cancel.broker_order_id,
                    event_type=event_type,
                    cumulative_quantity=cumulative,
                    last_quantity=fill.quantity,
                    last_price=fill.price,
                    fees=self._fees(source, fill),
                    reject_code=None,
                    not_before=cancel.as_of,
                    observed_at=observed_at,
                )
            )
        if plan.confirm_cancel and cumulative < source.intent.quantity:
            callbacks.append(
                self._event(
                    command=source,
                    operation_id=cancel.cancel_id,
                    ordinal=len(callbacks),
                    broker_order_id=cancel.broker_order_id,
                    event_type=ExecutionEventType.CANCELLED,
                    cumulative_quantity=cumulative,
                    last_quantity=0,
                    last_price=None,
                    fees=(),
                    reject_code=None,
                    not_before=cancel.as_of,
                    observed_at=observed_at,
                )
            )
        self._prove_sequence(snapshot, source, tuple(callbacks))
        return self._with_duplicates(cancel.cancel_id, tuple(callbacks))

    def _submit_plan(self, command: OrderCommand) -> PaperSubmitPlan:
        invalid = False
        plan: object = None
        try:
            plan = self._fill_policy.plan_submit(command=command)
        except Exception:
            invalid = True
        if invalid or type(plan) is not PaperSubmitPlan:
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        try:
            plan.__post_init__()
        except Exception:
            invalid = True
        if invalid:
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        return plan

    def _cancel_plan(
        self, source: OrderCommand, cancel: CancelCommand
    ) -> PaperCancelPlan:
        invalid = False
        plan: object = None
        try:
            plan = self._fill_policy.plan_cancel(command=source, cancel=cancel)
        except Exception:
            invalid = True
        if invalid or type(plan) is not PaperCancelPlan:
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        try:
            plan.__post_init__()
        except Exception:
            invalid = True
        if invalid:
            raise PaperGatewayError("PAPER_POLICY_INVALID")
        return plan

    def _event(
        self,
        *,
        command: OrderCommand,
        operation_id: str,
        ordinal: int,
        broker_order_id: str,
        event_type: ExecutionEventType,
        cumulative_quantity: int,
        last_quantity: int,
        last_price: Decimal | None,
        fees: tuple[FeeComponent, ...],
        reject_code: str | None,
        not_before: dt.datetime,
        observed_at: dt.datetime,
    ) -> ExecutionEvent:
        occurred_at = self._event_time(
            operation_id, ordinal, not_before, observed_at
        )
        invalid = False
        event: ExecutionEvent | None = None
        try:
            event = build_execution_event(
                command=command,
                broker_order_id=broker_order_id,
                event_type=event_type,
                occurred_at=occurred_at,
                cumulative_quantity=cumulative_quantity,
                last_quantity=last_quantity,
                last_price=last_price,
                fees=fees,
                reject_code=reject_code,
            )
        except Exception:
            invalid = True
        if invalid or event is None:
            raise PaperGatewayError("PAPER_SEQUENCE_INVALID")
        return event

    def _event_time(
        self,
        operation_id: str,
        ordinal: int,
        not_before: dt.datetime,
        observed_at: dt.datetime,
    ) -> dt.datetime:
        invalid = False
        value: object = None
        try:
            if isinstance(self._clock, _DispatchAnchoredPaperClock):
                value = self._clock.event_time_for_dispatch(
                    operation_id=operation_id,
                    event_ordinal=ordinal,
                    observed_at=observed_at,
                )
            else:
                value = self._clock.event_time(
                    operation_id=operation_id, event_ordinal=ordinal
                )
            if (
                type(value) is not dt.datetime
                or value.tzinfo is None
                or value.utcoffset() != dt.timedelta(0)
                or value < not_before
            ):
                invalid = True
        except Exception:
            invalid = True
        if invalid or type(value) is not dt.datetime:
            raise PaperGatewayError("PAPER_CLOCK_INVALID")
        return value

    def _validate_fill(
        self, command: OrderCommand, fill: PaperFill, *, remaining: int
    ) -> None:
        invalid = False
        try:
            fill.__post_init__()
        except Exception:
            invalid = True
        if invalid or fill.quantity > remaining:
            raise PaperGatewayError("PAPER_FILL_INVALID")
        if (
            command.intent.side is OrderSide.BUY
            and fill.price > command.intent.limit_price
            or command.intent.side is OrderSide.SELL
            and fill.price < command.intent.limit_price
        ):
            raise PaperGatewayError("PAPER_PRICE_LIMIT_VIOLATION")

    def _fees(
        self, command: OrderCommand, fill: PaperFill
    ) -> tuple[FeeComponent, ...]:
        invalid = False
        fees: object = None
        try:
            fees = calculate_execution_cost(
                command.intent,
                fill.price,
                fill.quantity,
                self._cost_schedule,
                self._fx_snapshot,
            )
        except Exception:
            invalid = True
        if invalid or type(fees) is not tuple:
            raise PaperGatewayError("PAPER_COST_INVALID")
        return fees

    def _with_duplicates(
        self, operation_id: str, callbacks: tuple[ExecutionEvent, ...]
    ) -> tuple[ExecutionEvent, ...]:
        invalid = False
        ordinals: object = None
        try:
            ordinals = self._fault_plan.duplicate_callback_ordinals(
                operation_id=operation_id
            )
        except Exception:
            invalid = True
        if (
            invalid
            or type(ordinals) is not tuple
            or any(type(item) is not int or item < 0 or item >= len(callbacks) for item in ordinals)
            or tuple(sorted(ordinals)) != ordinals
            or len(set(ordinals)) != len(ordinals)
        ):
            raise PaperGatewayError("PAPER_FAULT_PLAN_INVALID")
        repeated = set(ordinals)
        output: list[ExecutionEvent] = []
        for ordinal, event in enumerate(callbacks):
            output.append(event)
            if ordinal in repeated:
                output.append(event)
        return tuple(output)

    @staticmethod
    def _broker_order_id(command_id: str) -> str:
        return f"PAPER-{command_id}"

    @staticmethod
    def _cancel_snapshot(
        source: OrderCommand, cancel: CancelCommand
    ) -> OrderAggregate:
        invalid = False
        snapshot: OrderAggregate | None = None
        try:
            snapshot = OrderAggregate(
                command_id=cancel.command_id,
                status=cancel.aggregate_status,
                filled_quantity=cancel.observed_filled_quantity,
                broker_order_id=cancel.broker_order_id,
                reject_code=None,
                applied_event_ids=cancel.observed_event_ids,
                command_quantity=source.intent.quantity,
                last_event_at=cancel.observed_last_event_at,
            )
        except Exception:
            invalid = True
        if invalid or snapshot is None:
            raise PaperGatewayError("PAPER_INPUT_INVALID")
        return snapshot

    @staticmethod
    def _prove_sequence(
        aggregate: OrderAggregate,
        command: OrderCommand,
        callbacks: tuple[ExecutionEvent, ...],
    ) -> OrderAggregate:
        invalid = False
        projected = aggregate
        try:
            for event in callbacks:
                projected = reduce_order(projected, command, event)
        except Exception:
            invalid = True
        if invalid:
            raise PaperGatewayError("PAPER_SEQUENCE_INVALID")
        return projected


__all__ = [
    "PaperCancelPlan",
    "PaperClock",
    "PaperFaultPlan",
    "PaperFill",
    "PaperFillPolicy",
    "PaperGateway",
    "PaperGatewayError",
    "PaperSubmitPlan",
]
