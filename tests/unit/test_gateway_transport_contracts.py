"""M4-P2A gateway dispatch certainty and fencing contracts."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
from decimal import Decimal
from typing import Any

import pytest

from quant.domain.enums import (
    Currency,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
)
from quant.execution.contracts import (
    OrderCommand,
    build_execution_event,
    build_order_command,
    build_order_intent,
)
from quant.execution.gateways import (
    DispatchCertainty,
    GatewayContractError,
    GatewayDispatchResult,
    GatewayTransport,
    validate_gateway_submit,
    verify_gateway_dispatch_result,
)

UTC = dt.timezone.utc


def _hex64(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _time(minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 18, 14, minute, tzinfo=UTC)


def _command(*, mode: ExecutionMode = ExecutionMode.PAPER, symbol: str = "600000.SH") -> OrderCommand:
    intent = build_order_intent(
        plan_id=_hex64(f"plan-{symbol}"),
        symbol=symbol,
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10.50"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 18),
        generated_at=_time(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("market"),
        account_snapshot_id=_hex64("account"),
        config_identity=_hex64("config"),
        connect_route=None,
    )
    return build_order_command(intent=intent, mode=mode)


def _accepted(command: OrderCommand, *, minute: int = 1):
    return build_execution_event(
        command=command,
        broker_order_id="PAPER-1",
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=_time(minute),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )


class _Transport:
    def __init__(self) -> None:
        self.calls = 0

    def submit(
        self, *, command: OrderCommand, dispatch_attempt: int, now: dt.datetime
    ) -> GatewayDispatchResult:
        del now
        self.calls += 1
        return GatewayDispatchResult(
            command_id=command.command_id,
            dispatch_attempt=dispatch_attempt,
            certainty=DispatchCertainty.SENT,
            callbacks=(),
        )


def _result(
    command: OrderCommand,
    *,
    attempt: int = 2,
    certainty: DispatchCertainty = DispatchCertainty.SENT,
    callbacks: tuple[Any, ...] = (),
) -> GatewayDispatchResult:
    return GatewayDispatchResult(
        command_id=command.command_id,
        dispatch_attempt=attempt,
        certainty=certainty,
        callbacks=callbacks,
    )


def test_protocol_and_sent_without_callback_are_valid() -> None:
    command = _command()
    transport = _Transport()
    assert isinstance(transport, GatewayTransport)
    validate_gateway_submit(command, 2, _time(5))
    result = transport.submit(command=command, dispatch_attempt=2, now=_time(5))
    assert verify_gateway_dispatch_result(command, 2, _time(5), result) is result
    assert transport.calls == 1


@pytest.mark.parametrize("certainty", [DispatchCertainty.NOT_SENT, DispatchCertainty.UNKNOWN])
def test_non_sent_certainties_require_empty_callbacks(certainty: DispatchCertainty) -> None:
    command = _command()
    assert verify_gateway_dispatch_result(
        command, 1, _time(5), _result(command, attempt=1, certainty=certainty)
    ).certainty is certainty
    with pytest.raises(GatewayContractError, match="CALLBACKS_FORBIDDEN"):
        _result(command, attempt=1, certainty=certainty, callbacks=(_accepted(command),))


@pytest.mark.parametrize("attempt", [True, 0, -1, 1.0])
def test_attempt_rejected_before_adapter(attempt: Any) -> None:
    transport = _Transport()
    with pytest.raises(GatewayContractError, match="ATTEMPT_INVALID"):
        validate_gateway_submit(_command(), attempt, _time(5))
    assert transport.calls == 0


def test_shadow_and_forged_intent_rejected_before_adapter() -> None:
    transport = _Transport()
    with pytest.raises(GatewayContractError, match="MODE_UNSUPPORTED"):
        validate_gateway_submit(_command(mode=ExecutionMode.SHADOW), 1, _time(5))
    forged = _command()
    object.__setattr__(forged.intent, "target_identity", _hex64("forged"))
    with pytest.raises(GatewayContractError, match="COMMAND_INVALID") as exc_info:
        validate_gateway_submit(forged, 1, _time(5))
    assert transport.calls == 0
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_result_command_and_attempt_are_fenced() -> None:
    command = _command()
    other = _command(symbol="600001.SH")
    with pytest.raises(GatewayContractError, match="COMMAND_MISMATCH"):
        verify_gateway_dispatch_result(command, 2, _time(5), _result(other, attempt=2))
    with pytest.raises(GatewayContractError, match="ATTEMPT_MISMATCH"):
        verify_gateway_dispatch_result(command, 2, _time(5), _result(command, attempt=1))


def test_callback_order_and_identical_duplicates_are_preserved() -> None:
    command = _command()
    first = _accepted(command, minute=1)
    second = build_execution_event(
        command=command,
        broker_order_id="PAPER-1",
        event_type=ExecutionEventType.PARTIAL_FILL,
        occurred_at=_time(2),
        cumulative_quantity=20,
        last_quantity=20,
        last_price=Decimal("10.50"),
        fees=(),
        reject_code=None,
    )
    result = _result(command, callbacks=(second, first, first))
    verified = verify_gateway_dispatch_result(command, 2, _time(5), result)
    assert verified.callbacks == (second, first, first)


def test_cross_command_forged_future_and_conflicting_callbacks_fail_closed() -> None:
    command = _command()
    other = _command(symbol="600001.SH")
    with pytest.raises(GatewayContractError, match="CALLBACK_COMMAND_MISMATCH"):
        verify_gateway_dispatch_result(
            command, 2, _time(5), _result(command, callbacks=(_accepted(other),))
        )
    with pytest.raises(GatewayContractError, match="CALLBACK_TIME_INVALID"):
        verify_gateway_dispatch_result(
            command, 2, _time(5), _result(command, callbacks=(_accepted(command, minute=6),))
        )

    valid = _accepted(command)
    forged = copy.copy(valid)
    object.__setattr__(forged, "broker_order_id", "PAPER-2")
    with pytest.raises(GatewayContractError, match="CALLBACK_INVALID") as exc_info:
        verify_gateway_dispatch_result(
            command, 2, _time(5), _result(command, callbacks=(valid, forged))
        )
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    "value",
    [dt.datetime(2026, 7, 18), dt.datetime(2026, 7, 18, tzinfo=dt.timezone(dt.timedelta(hours=8)))],
)
def test_submit_time_must_be_aware_utc(value: dt.datetime) -> None:
    with pytest.raises(GatewayContractError, match="TIME_INVALID"):
        validate_gateway_submit(_command(), 1, value)


def test_identity_and_hostile_timezone_errors_are_sanitized() -> None:
    forged = _command()
    object.__setattr__(forged, "command_id", _hex64("forged-command"))
    with pytest.raises(GatewayContractError, match="COMMAND_INVALID") as identity_exc:
        validate_gateway_submit(forged, 1, _time(5))

    class HostileTimezone(dt.tzinfo):
        def utcoffset(self, value: dt.datetime | None) -> dt.timedelta:
            del value
            raise RuntimeError("secret-from-tzinfo")

        def dst(self, value: dt.datetime | None) -> dt.timedelta:
            del value
            return dt.timedelta(0)

    hostile_now = dt.datetime(2026, 7, 18, tzinfo=HostileTimezone())
    with pytest.raises(GatewayContractError, match="TIME_INVALID") as time_exc:
        validate_gateway_submit(_command(), 1, hostile_now)

    for caught in (identity_exc.value, time_exc.value):
        assert caught.__cause__ is None
        assert caught.__context__ is None
        assert "secret" not in str(caught)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("dispatch_attempt", True, "ATTEMPT_INVALID"),
        ("certainty", "SENT", "RESULT_INVALID"),
        ("callbacks", [], "RESULT_INVALID"),
    ],
)
def test_post_verifier_rejects_mutated_frozen_result(
    field: str, value: object, code: str
) -> None:
    command = _command()
    result = _result(command)
    object.__setattr__(result, field, value)
    with pytest.raises(GatewayContractError, match=code):
        verify_gateway_dispatch_result(command, 2, _time(5), result)
