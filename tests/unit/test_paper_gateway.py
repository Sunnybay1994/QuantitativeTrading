"""M4-P2B deterministic PAPER gateway contract tests."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
from decimal import Decimal

import pytest

from quant.backtest.costs import (
    ExecutionCostPeriod,
    build_execution_cost_schedule,
)
from quant.domain.enums import (
    Currency,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
    OrderStatus,
)
from quant.execution.contracts import (
    CancelCommand,
    OrderCommand,
    build_cancel_command,
    build_execution_event,
    build_order_command,
    build_order_intent,
)
from quant.execution.gateways import (
    DispatchCertainty,
    GatewayContractError,
    GatewayCancelTransport,
    GatewayTransport,
    PaperCancelPlan,
    PaperFill,
    PaperGateway,
    PaperGatewayError,
    PaperSubmitPlan,
)
from quant.execution.oms import OmsError, OrderAggregate, new_order_aggregate, reduce_order

UTC = dt.timezone.utc


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _time(minute: int) -> dt.datetime:
    return dt.datetime(2026, 8, 3, 14, minute, tzinfo=UTC)


def _command(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 100,
    limit: str = "10.50",
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> OrderCommand:
    intent = build_order_intent(
        plan_id=_hex(f"plan-{side.value}-{quantity}-{limit}"),
        symbol="600000.SH",
        market=Market.SH,
        side=side,
        quantity=quantity,
        limit_price=Decimal(limit),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 8, 3),
        generated_at=_time(0),
        target_identity=_hex("target"),
        market_snapshot_id=_hex("market"),
        account_snapshot_id=_hex("account"),
        config_identity=_hex("config"),
        connect_route=None,
    )
    return build_order_command(intent=intent, mode=mode)


class _Clock:
    def __init__(self) -> None:
        self.anchors: dict[str, dt.datetime] = {}
        self.calls = 0

    def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
        self.calls += 1
        return self.anchors.get(operation_id, _time(1)) + dt.timedelta(
            minutes=event_ordinal
        )


class _Policy:
    def __init__(self, submit: PaperSubmitPlan = PaperSubmitPlan()) -> None:
        self.submit_plan = submit
        self.cancel_plan = PaperCancelPlan()
        self.submit_calls = 0
        self.cancel_calls = 0

    def plan_submit(self, *, command: OrderCommand) -> PaperSubmitPlan:
        del command
        self.submit_calls += 1
        return self.submit_plan

    def plan_cancel(
        self, *, command: OrderCommand, cancel: CancelCommand
    ) -> PaperCancelPlan:
        del command, cancel
        self.cancel_calls += 1
        return self.cancel_plan


class _Faults:
    def __init__(
        self,
        certainty: DispatchCertainty = DispatchCertainty.SENT,
        duplicates: tuple[int, ...] = (),
    ) -> None:
        self.certainty = certainty
        self.duplicates = duplicates

    def submit_certainty(
        self, *, command_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        del command_id, dispatch_attempt
        return self.certainty

    def cancel_certainty(
        self, *, cancel_id: str, dispatch_attempt: int
    ) -> DispatchCertainty:
        del cancel_id, dispatch_attempt
        return self.certainty

    def duplicate_callback_ordinals(self, *, operation_id: str) -> tuple[int, ...]:
        del operation_id
        return self.duplicates


def _schedule():
    return build_execution_cost_schedule(
        selector="paper-cost-v1",
        periods=(
            ExecutionCostPeriod(
                market=Market.SH,
                effective_from=dt.date(2026, 1, 1),
                effective_to=None,
                commission_rate=Decimal("0.0003"),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.0005"),
                transfer_fee=Decimal("0.00001"),
                settlement_currency=Currency.CNY,
            ),
        ),
    )


def _gateway(
    *,
    clock: _Clock | None = None,
    policy: _Policy | None = None,
    faults: _Faults | None = None,
    recovered: tuple[OrderCommand, ...] = (),
) -> tuple[PaperGateway, _Clock, _Policy, _Faults]:
    actual_clock = clock or _Clock()
    actual_policy = policy or _Policy()
    actual_faults = faults or _Faults()
    gateway = PaperGateway(
        clock=actual_clock,
        fill_policy=actual_policy,
        fault_plan=actual_faults,
        cost_schedule=_schedule(),
        fx_snapshot=None,
        recovered_commands=recovered,
    )
    return gateway, actual_clock, actual_policy, actual_faults


def _accepted_aggregate(
    gateway: PaperGateway, command: OrderCommand
) -> OrderAggregate:
    result = gateway.submit(command=command, dispatch_attempt=1, now=_time(9))
    aggregate = new_order_aggregate(command)
    for event in result.callbacks:
        aggregate = reduce_order(aggregate, command, event)
    assert aggregate.status is OrderStatus.SUBMITTED
    return aggregate


def _cancel(
    gateway: PaperGateway, clock: _Clock, command: OrderCommand
) -> tuple[CancelCommand, OrderAggregate]:
    aggregate = _accepted_aggregate(gateway, command)
    cancel = build_cancel_command(command=command, aggregate=aggregate, as_of=_time(10))
    clock.anchors[cancel.cancel_id] = _time(11)
    return cancel, aggregate


def test_full_fill_reuses_transport_oms_and_cost_contracts() -> None:
    command = _command()
    policy = _Policy(PaperSubmitPlan(fills=(PaperFill(100, Decimal("10.40")),)))
    gateway, _, _, _ = _gateway(policy=policy)

    assert isinstance(gateway, GatewayTransport)
    assert isinstance(gateway, GatewayCancelTransport)
    result = gateway.submit(command=command, dispatch_attempt=2, now=_time(5))

    assert result.certainty is DispatchCertainty.SENT
    assert [item.event_type for item in result.callbacks] == [
        ExecutionEventType.ACCEPTED,
        ExecutionEventType.FILL,
    ]
    assert [item.code for item in result.callbacks[-1].fees] == [
        "COMMISSION",
        "STAMP_TAX",
        "TRANSFER_FEE",
    ]
    aggregate = new_order_aggregate(command)
    for event in result.callbacks:
        aggregate = reduce_order(aggregate, command, event)
    assert aggregate.status is OrderStatus.FILLED


def test_submit_replay_and_delayed_ack_are_deterministic() -> None:
    command = _command()
    clock = _Clock()
    clock.anchors[command.command_id] = _time(5)
    gateway, _, policy, _ = _gateway(clock=clock)

    delayed = gateway.submit(command=command, dispatch_attempt=1, now=_time(4))
    first = gateway.submit(command=command, dispatch_attempt=2, now=_time(8))
    replay = gateway.submit(command=command, dispatch_attempt=3, now=_time(8))

    assert delayed.certainty is DispatchCertainty.SENT and delayed.callbacks == ()
    assert first.callbacks == replay.callbacks
    assert policy.submit_calls == 1


def test_submit_restart_reproduces_exact_callback_identities() -> None:
    command = _command()
    plan = PaperSubmitPlan(fills=(PaperFill(100, Decimal("10.40")),))
    first, _, _, _ = _gateway(policy=_Policy(plan))
    second, _, _, _ = _gateway(policy=_Policy(plan), recovered=(command,))
    one = first.submit(command=command, dispatch_attempt=1, now=_time(8))
    two = second.submit(command=command, dispatch_attempt=9, now=_time(8))
    assert one.callbacks == two.callbacks


def test_rejection_and_partial_fill_sequences() -> None:
    rejected = _command(quantity=10)
    reject_gateway, _, _, _ = _gateway(
        policy=_Policy(PaperSubmitPlan(reject_code="PAPER_RULE_REJECT"))
    )
    result = reject_gateway.submit(command=rejected, dispatch_attempt=1, now=_time(5))
    assert len(result.callbacks) == 1
    assert result.callbacks[0].event_type is ExecutionEventType.REJECTED

    partial = _command(quantity=100)
    partial_gateway, _, _, _ = _gateway(
        policy=_Policy(PaperSubmitPlan(fills=(PaperFill(40, Decimal("10.40")),)))
    )
    result = partial_gateway.submit(command=partial, dispatch_attempt=1, now=_time(5))
    assert result.callbacks[-1].event_type is ExecutionEventType.PARTIAL_FILL
    assert result.callbacks[-1].cumulative_quantity == 40


@pytest.mark.parametrize(
    "hostile_code",
    [
        r"C:\TOKEN_SECRET",
        "TOKEN_SECRET",
        "UNKNOWN_BROKER_REJECT",
        "PAPER_OTHER_REJECT",
        "PAPER_RULE_REJECT\nTOKEN_SECRET",
    ],
)
def test_reject_code_is_a_closed_set_at_construction_and_policy_return(
    hostile_code: str,
) -> None:
    with pytest.raises(PaperGatewayError, match="^PAPER_POLICY_INVALID$") as direct:
        PaperSubmitPlan(reject_code=hostile_code)
    assert hostile_code not in str(direct.value)
    assert direct.value.__cause__ is None and direct.value.__context__ is None

    forged = PaperSubmitPlan(reject_code="PAPER_RULE_REJECT")
    object.__setattr__(forged, "reject_code", hostile_code)
    gateway, _, _, _ = _gateway(policy=_Policy(forged))
    with pytest.raises(PaperGatewayError, match="^PAPER_POLICY_INVALID$") as returned:
        gateway.submit(command=_command(), dispatch_attempt=1, now=_time(5))
    assert hostile_code not in str(returned.value)
    assert returned.value.__cause__ is None and returned.value.__context__ is None


def test_allowed_rejection_code_is_restart_identity_stable() -> None:
    command = _command()
    plan = PaperSubmitPlan(reject_code="PAPER_RULE_REJECT")
    first, _, _, _ = _gateway(policy=_Policy(plan))
    recovered, _, _, _ = _gateway(policy=_Policy(plan), recovered=(command,))
    one = first.submit(command=command, dispatch_attempt=1, now=_time(5))
    two = recovered.submit(command=command, dispatch_attempt=8, now=_time(5))
    assert one.callbacks == two.callbacks
    assert one.callbacks[0].reject_code == "PAPER_RULE_REJECT"


@pytest.mark.parametrize(
    "certainty", [DispatchCertainty.NOT_SENT, DispatchCertainty.UNKNOWN]
)
def test_non_sent_certainties_are_callback_free_and_skip_economic_policy(
    certainty: DispatchCertainty,
) -> None:
    command = _command()
    clock, policy, faults = _Clock(), _Policy(), _Faults(certainty)
    gateway, _, _, _ = _gateway(clock=clock, policy=policy, faults=faults)
    result = gateway.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert result.certainty is certainty and result.callbacks == ()
    assert clock.calls == policy.submit_calls == 0


def test_unknown_is_sticky_but_not_sent_may_reconnect() -> None:
    class StickyFault(_Faults):
        explode = False

        def submit_certainty(
            self, *, command_id: str, dispatch_attempt: int
        ) -> DispatchCertainty:
            if self.explode:
                raise RuntimeError("TOKEN_UNKNOWN_MUST_NOT_REENTER_FAULT_PLAN")
            return super().submit_certainty(
                command_id=command_id, dispatch_attempt=dispatch_attempt
            )

    command = _command()
    faults = StickyFault(DispatchCertainty.UNKNOWN)
    gateway, _, _, _ = _gateway(faults=faults)
    assert gateway.submit(command=command, dispatch_attempt=1, now=_time(5)).certainty is DispatchCertainty.UNKNOWN
    faults.explode = True
    assert gateway.submit(command=command, dispatch_attempt=2, now=_time(5)).certainty is DispatchCertainty.UNKNOWN

    second = _command(quantity=200)
    faults = _Faults(DispatchCertainty.NOT_SENT)
    gateway, _, _, _ = _gateway(faults=faults)
    assert gateway.submit(command=second, dispatch_attempt=1, now=_time(5)).certainty is DispatchCertainty.NOT_SENT
    faults.certainty = DispatchCertainty.SENT
    assert gateway.submit(command=second, dispatch_attempt=2, now=_time(5)).certainty is DispatchCertainty.SENT


def test_exact_duplicate_callbacks_keep_order_and_identity() -> None:
    command = _command()
    gateway, _, _, _ = _gateway(faults=_Faults(duplicates=(0,)))
    result = gateway.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert result.callbacks[0] is result.callbacks[1]
    aggregate = new_order_aggregate(command)
    for event in result.callbacks:
        aggregate = reduce_order(aggregate, command, event)
    assert aggregate.applied_event_ids == (result.callbacks[0].event_id,)


def test_non_monotonic_clock_and_bad_duplicate_plan_fail_closed() -> None:
    command = _command()

    class BackwardClock(_Clock):
        def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
            del operation_id
            return _time(3 - event_ordinal)

    backward, _, _, _ = _gateway(
        clock=BackwardClock(),
        policy=_Policy(PaperSubmitPlan(fills=(PaperFill(100, Decimal("10.40")),))),
    )
    with pytest.raises(PaperGatewayError, match="^PAPER_SEQUENCE_INVALID$"):
        backward.submit(command=command, dispatch_attempt=1, now=_time(8))

    bad_duplicate, _, _, _ = _gateway(faults=_Faults(duplicates=(5,)))
    with pytest.raises(PaperGatewayError, match="^PAPER_FAULT_PLAN_INVALID$"):
        bad_duplicate.submit(command=command, dispatch_attempt=1, now=_time(8))


def test_cost_failure_is_sanitized() -> None:
    command = _command()
    hk_only = build_execution_cost_schedule(
        selector="hk-only",
        periods=(
            ExecutionCostPeriod(
                market=Market.HK,
                effective_from=dt.date(2026, 1, 1),
                effective_to=None,
                commission_rate=Decimal("0.0003"),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.001"),
                transfer_fee=Decimal("0"),
                settlement_currency=Currency.CNY,
            ),
        ),
    )
    gateway = PaperGateway(
        clock=_Clock(),
        fill_policy=_Policy(
            PaperSubmitPlan(fills=(PaperFill(100, Decimal("10.40")),))
        ),
        fault_plan=_Faults(),
        cost_schedule=hk_only,
        fx_snapshot=None,
    )
    with pytest.raises(PaperGatewayError, match="^PAPER_COST_INVALID$") as caught:
        gateway.submit(command=command, dispatch_attempt=1, now=_time(8))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("side", "price"),
    [(OrderSide.BUY, "10.51"), (OrderSide.SELL, "10.49")],
)
def test_fill_cannot_cross_limit(side: OrderSide, price: str) -> None:
    command = _command(side=side)
    gateway, _, _, _ = _gateway(
        policy=_Policy(PaperSubmitPlan(fills=(PaperFill(100, Decimal(price)),)))
    )
    with pytest.raises(PaperGatewayError, match="^PAPER_PRICE_LIMIT_VIOLATION$"):
        gateway.submit(command=command, dispatch_attempt=1, now=_time(5))


def test_cancel_without_recovered_source_fails_closed() -> None:
    source = _command()
    seed, _, _, _ = _gateway()
    aggregate = _accepted_aggregate(seed, source)
    cancel = build_cancel_command(command=source, aggregate=aggregate, as_of=_time(10))
    gateway, _, _, _ = _gateway()
    with pytest.raises(PaperGatewayError, match="^PAPER_SOURCE_COMMAND_MISSING$"):
        gateway.cancel(command=cancel, dispatch_attempt=1, now=_time(15))


@pytest.mark.parametrize(
    ("late_fills", "expected_status"),
    [
        ((), OrderStatus.CANCELLED),
        ((PaperFill(20, Decimal("10.40")),), OrderStatus.CANCELLED),
        ((PaperFill(100, Decimal("10.40")),), OrderStatus.FILLED),
    ],
)
def test_cancel_fill_races_are_oms_reachable(
    late_fills: tuple[PaperFill, ...], expected_status: OrderStatus
) -> None:
    source = _command()
    policy = _Policy()
    gateway, clock, _, _ = _gateway(policy=policy)
    cancel, aggregate = _cancel(gateway, clock, source)
    policy.cancel_plan = PaperCancelPlan(late_fills=late_fills)

    result = gateway.cancel(command=cancel, dispatch_attempt=1, now=_time(20))
    for event in result.callbacks:
        aggregate = reduce_order(aggregate, source, event)
    assert aggregate.status is expected_status
    if expected_status is OrderStatus.FILLED:
        assert all(event.event_type is not ExecutionEventType.CANCELLED for event in result.callbacks)


def test_cancel_restart_replay_and_duplicate_are_identity_stable() -> None:
    source = _command()
    first_policy = _Policy()
    first, clock, _, _ = _gateway(
        policy=first_policy, faults=_Faults(duplicates=(0,))
    )
    cancel, aggregate = _cancel(first, clock, source)
    first_policy.cancel_plan = PaperCancelPlan(
        late_fills=(PaperFill(20, Decimal("10.40")),)
    )
    one = first.cancel(command=cancel, dispatch_attempt=1, now=_time(20))

    recovered_policy = _Policy()
    recovered_policy.cancel_plan = first_policy.cancel_plan
    recovered_clock = _Clock()
    recovered_clock.anchors[cancel.cancel_id] = _time(11)
    second, _, _, _ = _gateway(
        clock=recovered_clock,
        policy=recovered_policy,
        faults=_Faults(duplicates=(0,)),
        recovered=(source,),
    )
    two = second.cancel(command=cancel, dispatch_attempt=2, now=_time(20))

    assert one.callbacks == two.callbacks
    assert one.callbacks[0] is one.callbacks[1]
    for event in two.callbacks:
        aggregate = reduce_order(aggregate, source, event)
    assert aggregate.status is OrderStatus.CANCELLED


def test_cancel_unknown_has_no_callback_or_policy_side_effect() -> None:
    source = _command()
    policy, faults = _Policy(), _Faults(DispatchCertainty.SENT)
    gateway, clock, _, _ = _gateway(policy=policy, faults=faults)
    cancel, _ = _cancel(gateway, clock, source)
    faults.certainty = DispatchCertainty.UNKNOWN
    before_clock = clock.calls
    result = gateway.cancel(command=cancel, dispatch_attempt=1, now=_time(20))
    assert result.certainty is DispatchCertainty.UNKNOWN and result.callbacks == ()
    assert policy.cancel_calls == 0 and clock.calls == before_clock


def test_forged_input_is_rejected_before_injected_dependencies() -> None:
    command = _command()
    object.__setattr__(command.intent, "quantity", 200)
    gateway, clock, policy, _ = _gateway()
    with pytest.raises(GatewayContractError, match="COMMAND_INVALID"):
        gateway.submit(command=command, dispatch_attempt=1, now=_time(5))
    assert clock.calls == policy.submit_calls == 0


def test_hostile_policy_clock_and_fault_errors_are_sanitized() -> None:
    sentinel = "TOKEN_SECRET_PAYLOAD"

    class HostilePolicy(_Policy):
        def plan_submit(self, *, command: OrderCommand) -> PaperSubmitPlan:
            del command
            raise RuntimeError(sentinel)

    class HostileClock(_Clock):
        def event_time(self, *, operation_id: str, event_ordinal: int) -> dt.datetime:
            del operation_id, event_ordinal
            raise RuntimeError(sentinel)

    class HostileFault(_Faults):
        def submit_certainty(
            self, *, command_id: str, dispatch_attempt: int
        ) -> DispatchCertainty:
            del command_id, dispatch_attempt
            raise RuntimeError(sentinel)

    cases = (
        _gateway(policy=HostilePolicy())[0],
        _gateway(clock=HostileClock())[0],
        _gateway(faults=HostileFault())[0],
    )
    for gateway in cases:
        with pytest.raises(PaperGatewayError) as caught:
            gateway.submit(command=_command(), dispatch_attempt=1, now=_time(5))
        assert sentinel not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None


def test_same_event_id_different_payload_still_fails_in_oms() -> None:
    command = _command()
    gateway, _, _, _ = _gateway()
    result = gateway.submit(command=command, dispatch_attempt=1, now=_time(5))
    accepted = result.callbacks[0]
    forged = copy.copy(accepted)
    object.__setattr__(forged, "broker_order_id", "TOKEN_DIFFERENT")
    aggregate = reduce_order(new_order_aggregate(command), command, accepted)
    with pytest.raises(OmsError, match="identity"):
        reduce_order(aggregate, command, forged)


def test_late_fill_after_cancelled_is_rejected_by_shared_oms() -> None:
    source = _command()
    gateway, clock, _, _ = _gateway()
    cancel, aggregate = _cancel(gateway, clock, source)
    result = gateway.cancel(command=cancel, dispatch_attempt=1, now=_time(20))
    for event in result.callbacks:
        aggregate = reduce_order(aggregate, source, event)
    assert aggregate.status is OrderStatus.CANCELLED
    late = build_execution_event(
        command=source,
        broker_order_id=cancel.broker_order_id,
        event_type=ExecutionEventType.FILL,
        occurred_at=_time(21),
        cumulative_quantity=100,
        last_quantity=100,
        last_price=Decimal("10.40"),
        fees=(),
        reject_code=None,
    )
    with pytest.raises(OmsError, match="terminal|CANCELLED|illegal"):
        reduce_order(aggregate, source, late)
