"""M4-P1 OMS pure reducer: legal transitions, idempotency, counterexamples."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import pytest

from quant.domain.enums import (
    Currency,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
    OrderStatus,
)
from quant.execution.contracts import (
    OrderCommand,
    build_execution_event,
    build_fee_component,
    build_money_amount,
    build_order_command,
    build_order_intent,
)
from quant.execution.oms import (
    OmsError,
    OrderAggregate,
    new_order_aggregate,
    reduce_order,
)

UTC = dt.timezone.utc


def _hex64(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _utc(hour: int = 2, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 16, hour, minute, 0, tzinfo=UTC)


def _command(*, quantity: int = 100) -> OrderCommand:
    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=quantity,
        limit_price=Decimal("10.50"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    assert intent.connect_route is None
    return build_order_command(intent=intent, mode=ExecutionMode.PAPER)


def _event(
    command: OrderCommand,
    *,
    event_type: ExecutionEventType,
    occurred_at: dt.datetime,
    cumulative_quantity: int = 0,
    last_quantity: int = 0,
    last_price: Decimal | None = None,
    broker_order_id: str | None = "B-1",
    reject_code: str | None = None,
):
    return build_execution_event(
        command=command,
        broker_order_id=broker_order_id,
        event_type=event_type,
        occurred_at=occurred_at,
        cumulative_quantity=cumulative_quantity,
        last_quantity=last_quantity,
        last_price=last_price,
        fees=(),
        reject_code=reject_code,
    )


def _accepted(
    command: OrderCommand,
    *,
    at: dt.datetime | None = None,
    broker_order_id: str | None = "B-1",
):
    return _event(
        command,
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=at or _utc(2, 1),
        broker_order_id=broker_order_id,
    )


def _partial(
    command: OrderCommand,
    *,
    cum: int,
    last: int,
    at: dt.datetime | None = None,
    price: Decimal = Decimal("10.50"),
    broker_order_id: str | None = "B-1",
):
    return _event(
        command,
        event_type=ExecutionEventType.PARTIAL_FILL,
        occurred_at=at or _utc(2, 2),
        cumulative_quantity=cum,
        last_quantity=last,
        last_price=price,
        broker_order_id=broker_order_id,
    )


def _fill(
    command: OrderCommand,
    *,
    cum: int,
    last: int,
    at: dt.datetime | None = None,
    price: Decimal = Decimal("10.50"),
    broker_order_id: str | None = "B-1",
):
    return _event(
        command,
        event_type=ExecutionEventType.FILL,
        occurred_at=at or _utc(2, 3),
        cumulative_quantity=cum,
        last_quantity=last,
        last_price=price,
        broker_order_id=broker_order_id,
    )


def _cancel_accepted(
    command: OrderCommand,
    *,
    cum: int = 0,
    at: dt.datetime | None = None,
    broker_order_id: str | None = "B-1",
):
    return _event(
        command,
        event_type=ExecutionEventType.CANCEL_ACCEPTED,
        occurred_at=at or _utc(2, 4),
        cumulative_quantity=cum,
        broker_order_id=broker_order_id,
    )


def _cancelled(
    command: OrderCommand,
    *,
    cum: int = 0,
    at: dt.datetime | None = None,
    broker_order_id: str | None = "B-1",
):
    return _event(
        command,
        event_type=ExecutionEventType.CANCELLED,
        occurred_at=at or _utc(2, 5),
        cumulative_quantity=cum,
        broker_order_id=broker_order_id,
    )


def _rejected(command: OrderCommand, *, at: dt.datetime | None = None):
    return _event(
        command,
        event_type=ExecutionEventType.REJECTED,
        occurred_at=at or _utc(2, 1),
        broker_order_id=None,
        reject_code="RISK_REJECT",
    )


def _seed_event_id(label: str) -> str:
    return _hex64(f"seed-event-{label}")


def _legal_aggregate(
    *,
    status: OrderStatus,
    command_quantity: int = 100,
    filled_quantity: int = 0,
    broker_order_id: str | None = "B-1",
    reject_code: str | None = None,
    event_labels: tuple[str, ...] = ("e1",),
    last_event_at: dt.datetime | None = None,
) -> OrderAggregate:
    """Build a structurally valid aggregate for direct-construction tests."""
    if status is OrderStatus.CREATED:
        return OrderAggregate(
            command_id=_hex64("agg-cmd"),
            status=status,
            filled_quantity=0,
            broker_order_id=None,
            reject_code=None,
            applied_event_ids=(),
            command_quantity=command_quantity,
            last_event_at=None,
        )
    at = last_event_at if last_event_at is not None else _utc(2, 1)
    return OrderAggregate(
        command_id=_hex64("agg-cmd"),
        status=status,
        filled_quantity=filled_quantity,
        broker_order_id=broker_order_id,
        reject_code=reject_code,
        applied_event_ids=tuple(_seed_event_id(label) for label in event_labels),
        command_quantity=command_quantity,
        last_event_at=at,
    )


# --- existing P1 suite (adapted) ---


def test_new_aggregate_is_created() -> None:
    command = _command()
    agg = new_order_aggregate(command)
    assert isinstance(agg, OrderAggregate)
    assert agg.command_id == command.command_id
    assert agg.status is OrderStatus.CREATED
    assert agg.filled_quantity == 0
    assert agg.broker_order_id is None
    assert agg.reject_code is None
    assert agg.applied_event_ids == ()
    assert agg.command_quantity == command.intent.quantity
    assert agg.last_event_at is None


def test_happy_path_partial_then_fill() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    assert agg.status is OrderStatus.SUBMITTED
    assert agg.broker_order_id == "B-1"
    assert agg.last_event_at == _utc(2, 1)

    agg = reduce_order(agg, command, _partial(command, cum=40, last=40))
    assert agg.status is OrderStatus.PARTIAL_FILLED
    assert agg.filled_quantity == 40
    assert agg.last_event_at == _utc(2, 2)

    agg = reduce_order(agg, command, _fill(command, cum=100, last=60, at=_utc(2, 3)))
    assert agg.status is OrderStatus.FILLED
    assert agg.filled_quantity == 100
    assert agg.last_event_at == _utc(2, 3)


def test_reject_from_created() -> None:
    command = _command()
    agg = reduce_order(new_order_aggregate(command), command, _rejected(command))
    assert agg.status is OrderStatus.REJECTED
    assert agg.reject_code == "RISK_REJECT"


def test_idempotent_replay_same_event() -> None:
    command = _command()
    accepted = _accepted(command)
    agg1 = reduce_order(new_order_aggregate(command), command, accepted)
    agg2 = reduce_order(agg1, command, accepted)
    assert agg2 is agg1 or agg2 == agg1
    assert agg2.applied_event_ids == (accepted.event_id,)
    assert agg2.status is OrderStatus.SUBMITTED
    assert agg2.last_event_at == agg1.last_event_at


def test_stale_new_after_ack_rejected() -> None:
    """ACK 后又收到另一条旧 NEW/ACCEPTED → fail closed（非幂等重放）。"""
    command = _command()
    agg = reduce_order(new_order_aggregate(command), command, _accepted(command, at=_utc(2, 1)))
    stale = _accepted(command, at=_utc(2, 0))  # different occurred_at → different event_id
    assert stale.event_id != agg.applied_event_ids[0]
    with pytest.raises(OmsError, match="occurred_at|last_event|ACCEPTED|NEW|terminal|illegal"):
        reduce_order(agg, command, stale)


def test_duplicate_fill_same_payload_is_noop() -> None:
    command = _command(quantity=50)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    fill = _fill(command, cum=50, last=50)
    agg = reduce_order(agg, command, fill)
    again = reduce_order(agg, command, fill)
    assert again == agg
    assert again.filled_quantity == 50


def test_duplicate_fill_with_new_event_id_rejected() -> None:
    """重复经济影响的第二笔 fill（不同 event_id）拒绝。"""
    command = _command(quantity=50)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _fill(command, cum=50, last=50, at=_utc(2, 3)))
    replay_like = _fill(command, cum=50, last=50, at=_utc(2, 4))
    with pytest.raises(OmsError):
        reduce_order(agg, command, replay_like)


def test_out_of_order_partial_after_higher_cum_rejected() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _partial(command, cum=60, last=60, at=_utc(2, 2)))
    late_lower = _partial(command, cum=30, last=30, at=_utc(2, 1))
    with pytest.raises(OmsError, match="occurred_at|last_event|monotonic|cumulative|order"):
        reduce_order(agg, command, late_lower)


def test_out_of_order_final_before_partial_state_still_accepts_monotonic_fill() -> None:
    """直接 FILL（无 partial）合法；但 cum 回退非法。"""
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _fill(command, cum=100, last=100))
    assert agg.status is OrderStatus.FILLED
    with pytest.raises(OmsError):
        reduce_order(agg, command, _partial(command, cum=40, last=40, at=_utc(2, 9)))


def test_fill_exceeding_command_quantity_rejected_by_builder_or_oms() -> None:
    command = _command(quantity=100)
    reduce_order(new_order_aggregate(command), command, _accepted(command))
    # D0 builder already blocks cum > qty; OMS still guards last_qty mismatch / over-apply.
    from quant.execution.contracts import ContractError

    with pytest.raises(ContractError):
        _fill(command, cum=120, last=120)


def test_oms_rejects_fill_delta_mismatch() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _partial(command, cum=40, last=40))
    # cum=70 but last claims 40 (should be 30)
    bad = _partial(command, cum=70, last=40, at=_utc(2, 8))
    with pytest.raises(OmsError, match="last_quantity|delta"):
        reduce_order(agg, command, bad)


def test_cancel_fill_race_fill_wins_full() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _cancel_accepted(command))
    assert agg.status is OrderStatus.CANCELLING
    agg = reduce_order(agg, command, _fill(command, cum=100, last=100, at=_utc(2, 6)))
    assert agg.status is OrderStatus.FILLED
    assert agg.filled_quantity == 100


def test_cancel_fill_race_partial_then_cancelled() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _partial(command, cum=40, last=40))
    agg = reduce_order(agg, command, _cancel_accepted(command, cum=40, at=_utc(2, 4)))
    assert agg.status is OrderStatus.CANCELLING
    agg = reduce_order(
        agg,
        command,
        _partial(command, cum=60, last=20, at=_utc(2, 5)),
    )
    assert agg.status is OrderStatus.CANCELLING
    assert agg.filled_quantity == 60
    agg = reduce_order(agg, command, _cancelled(command, cum=60, at=_utc(2, 6)))
    assert agg.status is OrderStatus.CANCELLED
    assert agg.filled_quantity == 60


def test_late_fill_after_cancelled_rejected() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _cancelled(command, cum=0))
    assert agg.status is OrderStatus.CANCELLED
    with pytest.raises(OmsError, match="terminal|CANCELLED|illegal"):
        reduce_order(agg, command, _fill(command, cum=100, last=100, at=_utc(2, 9)))


def test_terminal_filled_rejects_cancel() -> None:
    command = _command(quantity=50)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command))
    agg = reduce_order(agg, command, _fill(command, cum=50, last=50))
    with pytest.raises(OmsError, match="terminal|FILLED|illegal"):
        reduce_order(agg, command, _cancelled(command, cum=50, at=_utc(2, 9)))


def test_command_id_mismatch_rejected() -> None:
    command_a = _command(quantity=100)
    command_b = _command(quantity=200)
    assert command_a.command_id != command_b.command_id
    agg = new_order_aggregate(command_a)
    with pytest.raises(OmsError, match="command_id"):
        reduce_order(agg, command_b, _accepted(command_b))


def test_event_command_id_must_match_aggregate() -> None:
    command_a = _command(quantity=100)
    command_b = _command(quantity=200)
    agg = new_order_aggregate(command_a)
    foreign = _accepted(command_b)
    with pytest.raises(OmsError, match="command_id"):
        reduce_order(agg, command_a, foreign)


def test_partial_fill_must_not_reach_full_quantity() -> None:
    command = _command(quantity=100)
    agg = reduce_order(new_order_aggregate(command), command, _accepted(command))
    # PARTIAL_FILL with cum == qty is illegal at OMS layer (should be FILL)
    bad = _event(
        command,
        event_type=ExecutionEventType.PARTIAL_FILL,
        occurred_at=_utc(2, 2),
        cumulative_quantity=100,
        last_quantity=100,
        last_price=Decimal("10.50"),
    )
    with pytest.raises(OmsError, match="PARTIAL_FILL|FILL|full"):
        reduce_order(agg, command, bad)


def test_fill_must_reach_full_quantity() -> None:
    command = _command(quantity=100)
    agg = reduce_order(new_order_aggregate(command), command, _accepted(command))
    bad = _event(
        command,
        event_type=ExecutionEventType.FILL,
        occurred_at=_utc(2, 2),
        cumulative_quantity=80,
        last_quantity=80,
        last_price=Decimal("10.50"),
    )
    with pytest.raises(OmsError, match="FILL|full|quantity"):
        reduce_order(agg, command, bad)


def test_no_network_or_db_imports_in_oms_module() -> None:
    from pathlib import Path

    import quant.execution.oms as oms_mod

    source = Path(oms_mod.__file__).read_text(encoding="utf-8")
    for needle in (
        "import sqlite3",
        "from sqlite3",
        "import httpx",
        "import requests",
        "urllib.request",
        "import socket",
    ):
        assert needle not in source


# --- F1: OrderAggregate self-validation ---


@pytest.mark.parametrize(
    "kwargs,exc,match",
    [
        ({"status": "FILLED"}, TypeError, "status"),
        ({"filled_quantity": True}, TypeError, "filled_quantity"),
        ({"command_quantity": True}, TypeError, "command_quantity"),
        ({"command_id": "not-hex"}, OmsError, "hex"),
        ({"command_id": "A" * 64}, OmsError, "hex"),
        (
            {
                "status": OrderStatus.FILLED,
                "filled_quantity": 100,
                "applied_event_ids": ("not-hex-event-id",),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "hex",
        ),
        (
            {
                "status": OrderStatus.PARTIAL_FILLED,
                "filled_quantity": 40,
                "applied_event_ids": (_seed_event_id("dup"), _seed_event_id("dup")),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "duplicate",
        ),
        (
            {
                "status": OrderStatus.SUBMITTED,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": dt.datetime(2026, 7, 16, 2, 1, 0),
            },
            OmsError,
            "UTC|timezone",
        ),
        (
            {
                "status": OrderStatus.FILLED,
                "filled_quantity": 999,
                "reject_code": "bad",
                "applied_event_ids": ("deadbeef" * 8,),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "FILLED|filled|reject|hex",
        ),
        (
            {"status": OrderStatus.CREATED, "filled_quantity": 1},
            OmsError,
            "CREATED",
        ),
        (
            {
                "status": OrderStatus.CREATED,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "CREATED",
        ),
        (
            {
                "status": OrderStatus.PARTIAL_FILLED,
                "filled_quantity": 0,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "PARTIAL_FILLED",
        ),
        (
            {
                "status": OrderStatus.PARTIAL_FILLED,
                "filled_quantity": 100,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "PARTIAL_FILLED",
        ),
        (
            {
                "status": OrderStatus.FILLED,
                "filled_quantity": 80,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "FILLED",
        ),
        (
            {
                "status": OrderStatus.REJECTED,
                "reject_code": None,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "REJECTED|reject_code",
        ),
        (
            {
                "status": OrderStatus.REJECTED,
                "filled_quantity": 10,
                "reject_code": "X",
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "REJECTED|fill",
        ),
        (
            {
                "status": OrderStatus.SUBMITTED,
                "reject_code": "X",
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "reject_code|SUBMITTED",
        ),
        (
            {
                "status": OrderStatus.SUBMITTED,
                "applied_event_ids": (),
                "last_event_at": _utc(2, 1),
            },
            OmsError,
            "empty|last_event|SUBMITTED",
        ),
        (
            {
                "status": OrderStatus.SUBMITTED,
                "applied_event_ids": (_seed_event_id("e1"),),
                "last_event_at": None,
            },
            OmsError,
            "last_event",
        ),
        (
            {
                "status": OrderStatus.FILLED,
                "filled_quantity": 100,
                "applied_event_ids": [_seed_event_id("e1")],  # type: ignore[list-item]
                "last_event_at": _utc(2, 1),
            },
            TypeError,
            "tuple",
        ),
    ],
)
def test_order_aggregate_direct_construction_rejects_illegal(
    kwargs: dict,
    exc: type[BaseException],
    match: str,
) -> None:
    base: dict = {
        "command_id": _hex64("agg-cmd"),
        "status": OrderStatus.CREATED,
        "filled_quantity": 0,
        "broker_order_id": None,
        "reject_code": None,
        "applied_event_ids": (),
        "command_quantity": 100,
        "last_event_at": None,
    }
    base.update(kwargs)
    with pytest.raises(exc, match=match):
        OrderAggregate(**base)


@pytest.mark.parametrize(
    "status,filled,reject,broker",
    [
        (OrderStatus.CREATED, 0, None, None),
        (OrderStatus.SUBMITTED, 0, None, "B-1"),
        (OrderStatus.PARTIAL_FILLED, 40, None, "B-1"),
        (OrderStatus.FILLED, 100, None, "B-1"),
        (OrderStatus.CANCELLING, 40, None, "B-1"),
        (OrderStatus.CANCELLED, 40, None, "B-1"),
        (OrderStatus.REJECTED, 0, "RISK_REJECT", None),
    ],
)
def test_order_aggregate_legal_states_constructible(
    status: OrderStatus,
    filled: int,
    reject: str | None,
    broker: str | None,
) -> None:
    agg = _legal_aggregate(
        status=status,
        filled_quantity=filled,
        reject_code=reject,
        broker_order_id=broker,
        event_labels=() if status is OrderStatus.CREATED else ("e1",),
    )
    assert agg.status is status
    assert agg.filled_quantity == filled


def test_command_quantity_mismatch_rejected() -> None:
    command = _command(quantity=100)
    forged = OrderAggregate(
        command_id=command.command_id,
        status=OrderStatus.CREATED,
        filled_quantity=0,
        broker_order_id=None,
        reject_code=None,
        applied_event_ids=(),
        command_quantity=200,
        last_event_at=None,
    )
    with pytest.raises(OmsError, match="command_quantity"):
        reduce_order(forged, command, _accepted(command))


# --- F2: event time ordering ---


def test_event_before_command_generated_at_rejected() -> None:
    command = _command()
    assert command.intent.generated_at == _utc(2, 0)
    agg = new_order_aggregate(command)
    early = _accepted(command, at=_utc(1, 59))
    with pytest.raises(OmsError, match="occurred_at|generated_at"):
        reduce_order(agg, command, early)


def test_event_before_last_event_at_rejected() -> None:
    """P0-B: reverse-time partial after later accepted must fail closed."""
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command, at=_utc(2, 5)))
    reverse = _partial(command, cum=40, last=40, at=_utc(2, 4))
    with pytest.raises(OmsError, match="occurred_at|last_event"):
        reduce_order(agg, command, reverse)


def test_same_timestamp_different_legal_events_allowed() -> None:
    """Non-decreasing (not strictly increasing): equal timestamps are legal."""
    command = _command(quantity=100)
    same = _utc(2, 5)
    agg = new_order_aggregate(command)
    agg = reduce_order(agg, command, _accepted(command, at=same))
    agg = reduce_order(agg, command, _partial(command, cum=40, last=40, at=same))
    assert agg.status is OrderStatus.PARTIAL_FILLED
    assert agg.filled_quantity == 40
    assert agg.last_event_at == same
    agg = reduce_order(agg, command, _fill(command, cum=100, last=60, at=same))
    assert agg.status is OrderStatus.FILLED
    assert agg.last_event_at == same


def test_duplicate_event_id_noop_preserves_last_event_at() -> None:
    command = _command()
    accepted = _accepted(command, at=_utc(2, 1))
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    assert agg.last_event_at == _utc(2, 1)
    again = reduce_order(agg, command, accepted)
    assert again is agg or again == agg
    assert again.last_event_at == _utc(2, 1)


# --- F3: broker_order_id single bind ---


def test_broker_id_none_then_bind() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    assert agg.broker_order_id is None
    agg = reduce_order(agg, command, _accepted(command, broker_order_id="B-1"))
    assert agg.broker_order_id == "B-1"


def test_broker_id_bound_then_none_keeps() -> None:
    command = _command(quantity=100)
    agg = reduce_order(
        new_order_aggregate(command),
        command,
        _accepted(command, broker_order_id="B-1"),
    )
    agg = reduce_order(
        agg,
        command,
        _partial(command, cum=40, last=40, broker_order_id=None),
    )
    assert agg.broker_order_id == "B-1"


def test_broker_id_same_value_allowed() -> None:
    command = _command(quantity=100)
    agg = reduce_order(
        new_order_aggregate(command),
        command,
        _accepted(command, broker_order_id="B-1"),
    )
    agg = reduce_order(
        agg,
        command,
        _partial(command, cum=40, last=40, broker_order_id="B-1"),
    )
    assert agg.broker_order_id == "B-1"


@pytest.mark.parametrize(
    "event_factory",
    [
        lambda c: _partial(c, cum=40, last=40, at=_utc(2, 2), broker_order_id="B-2"),
        lambda c: _fill(c, cum=100, last=100, at=_utc(2, 3), broker_order_id="B-2"),
        lambda c: _cancel_accepted(c, cum=0, at=_utc(2, 4), broker_order_id="B-2"),
        lambda c: _cancelled(c, cum=0, at=_utc(2, 5), broker_order_id="B-2"),
    ],
)
def test_broker_id_change_fail_closed(event_factory) -> None:
    """P0-C: bound B-1 must not silently drift to B-2 on any applicable event."""
    command = _command(quantity=100)
    agg = reduce_order(
        new_order_aggregate(command),
        command,
        _accepted(command, broker_order_id="B-1"),
    )
    with pytest.raises(OmsError, match="broker_order_id"):
        reduce_order(agg, command, event_factory(command))


def test_broker_id_change_on_accepted_path_via_reject_not_applicable() -> None:
    """REJECTED from CREATED can set broker; change after bind covered by fill/cancel."""
    command = _command(quantity=100)
    agg = reduce_order(
        new_order_aggregate(command),
        command,
        _accepted(command, broker_order_id="B-1"),
    )
    # Second ACCEPTED is illegal transition; still must not rewrite broker first.
    with pytest.raises(OmsError):
        reduce_order(agg, command, _accepted(command, at=_utc(2, 2), broker_order_id="B-2"))
    assert agg.broker_order_id == "B-1"


# --- F1 secondary rework: content identity before membership ---


def test_same_event_id_tampered_broker_id_rejected() -> None:
    command = _command()
    accepted = _accepted(command, broker_order_id="B-1")
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    object.__setattr__(accepted, "broker_order_id", "B-FORGED")
    with pytest.raises(OmsError, match="identity"):
        reduce_order(agg, command, accepted)


def test_same_event_id_tampered_occurred_at_rejected() -> None:
    command = _command()
    accepted = _accepted(command, at=_utc(2, 1))
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    object.__setattr__(accepted, "occurred_at", _utc(2, 9))
    with pytest.raises(OmsError, match="identity"):
        reduce_order(agg, command, accepted)


def test_same_event_id_tampered_cumulative_quantity_rejected() -> None:
    command = _command(quantity=100)
    agg = reduce_order(new_order_aggregate(command), command, _accepted(command))
    fill = _partial(command, cum=40, last=40)
    agg = reduce_order(agg, command, fill)
    object.__setattr__(fill, "cumulative_quantity", 99)
    with pytest.raises(OmsError, match="identity"):
        reduce_order(agg, command, fill)


def test_same_event_id_tampered_fees_rejected() -> None:
    command = _command()
    accepted = _accepted(command)
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    forged_fee = build_fee_component(
        code="INJECTED-FEE-PAYLOAD",
        amount=build_money_amount(Currency.CNY, Decimal("0.01")),
        statutory=True,
        rule_version="forge-v1",
    )
    object.__setattr__(accepted, "fees", (forged_fee,))
    with pytest.raises(OmsError, match="identity"):
        reduce_order(agg, command, accepted)


def test_tampered_intent_content_rejected_before_state() -> None:
    command = _command(quantity=100)
    agg = new_order_aggregate(command)
    object.__setattr__(command.intent, "quantity", 200)
    with pytest.raises(OmsError, match="identity"):
        reduce_order(agg, command, _accepted(command))
    assert agg.status is OrderStatus.CREATED
    assert agg.applied_event_ids == ()


def test_tampered_illegal_aggregate_rejected_even_if_event_id_known() -> None:
    command = _command()
    accepted = _accepted(command)
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    assert accepted.event_id in agg.applied_event_ids
    object.__setattr__(agg, "filled_quantity", 1)
    with pytest.raises(OmsError, match="CREATED|filled"):
        reduce_order(agg, command, accepted)


def test_legal_duplicate_returns_same_aggregate_object() -> None:
    command = _command()
    accepted = _accepted(command)
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    again = reduce_order(agg, command, accepted)
    assert again is agg
    assert again.last_event_at == agg.last_event_at


def test_legal_distinct_event_still_advances_state() -> None:
    command = _command(quantity=100)
    agg = reduce_order(new_order_aggregate(command), command, _accepted(command))
    agg = reduce_order(agg, command, _partial(command, cum=40, last=40))
    assert agg.status is OrderStatus.PARTIAL_FILLED
    assert agg.filled_quantity == 40


def test_identity_rejection_cause_none_and_no_injected_payload() -> None:
    injected = "B-FORGED-SECRET-PAYLOAD-XYZ"
    command = _command()
    accepted = _accepted(command, broker_order_id="B-1")
    agg = reduce_order(new_order_aggregate(command), command, accepted)
    object.__setattr__(accepted, "broker_order_id", injected)
    with pytest.raises(OmsError) as exc_info:
        reduce_order(agg, command, accepted)
    err = exc_info.value
    assert err.__cause__ is None
    assert err.__context__ is None
    text = f"{err!s}{err!r}"
    assert injected not in text
    assert "FORGED" not in text
    assert "SECRET" not in text
