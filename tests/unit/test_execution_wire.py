"""P0B canonical execution wire compatibility and hostile-input tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

from quant.domain.enums import Currency, ExecutionEventType, ExecutionMode, Market, OrderSide
from quant.execution.contracts import (
    build_execution_event,
    build_fee_component,
    build_money_amount,
    build_order_command,
    build_order_intent,
)
from quant.execution.oms import new_order_aggregate
from quant.execution.wire import (
    WireError,
    decode_execution_event,
    decode_order_aggregate,
    decode_order_command,
    encode_execution_event,
    encode_order_aggregate,
    encode_order_command,
)

NOW = dt.datetime(2026, 7, 19, 8, tzinfo=dt.UTC)


def _command():
    return build_order_command(
        intent=build_order_intent(
            plan_id="9567e1771a45bb28b9ad3ecb065b71d3fb23a7af36f07cb248b0cb134b936394",
            symbol="600000.SH",
            market=Market.SH,
            side=OrderSide.BUY,
            quantity=100,
            limit_price=Decimal("10"),
            quote_currency=Currency.CNY,
            session_date=dt.date(2026, 7, 20),
            generated_at=NOW,
            target_identity="26cafb94003a654827f52047a9368c0821f01f4512828a68f7bd4b44e6a0afcf",
            market_snapshot_id="c1b83ecfdb66a3d00fada53e78f44c49ddbb77ebde1b7804d34f4ba683148b58",
            account_snapshot_id="ad965271a2820461f14e377af15c461ceef249a1e9c0b2de1823b9c9db9563c4",
            config_identity="77afd585354c6a480657a4bc4072d7db52564c3eca813a9de4c46776f01eb20f",
            connect_route=None,
        ),
        mode=ExecutionMode.PAPER,
    )


def _event(command):
    return build_execution_event(
        command=command,
        broker_order_id="PAPER-1",
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=NOW,
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _assert_sanitized(error: WireError) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True


def test_p4_fixture_golden_bytes_and_hashes_are_unchanged() -> None:
    command = _command()
    aggregate = new_order_aggregate(command)
    event = _event(command)

    payloads = (
        encode_order_command(command),
        encode_order_aggregate(aggregate),
        encode_execution_event(event),
    )
    assert tuple(hashlib.sha256(item).hexdigest() for item in payloads) == (
        "7a8a797d89c8736c35846bda6f2636a6fa2795892646389cf8ae12c956d103e5",
        "c6e6c8b39119092d3fd7fafd3e11ec3d303f24e70e1f472701c4884804ad08a7",
        "98c52676f5e9165f9d59cfcb11f578df88bb59ab621f4955254926586c7fddac",
    )
    assert decode_order_command(payloads[0]) == command
    assert decode_order_aggregate(payloads[1], command=command) == aggregate
    assert decode_execution_event(payloads[2], command=command) == event


@pytest.mark.parametrize("mutation", ["extra", "missing", "identity", "enum"])
def test_command_structural_and_identity_tamper_fails_closed(mutation: str) -> None:
    raw = json.loads(encode_order_command(_command()))
    if mutation == "extra":
        raw["extra"] = 1
    elif mutation == "missing":
        del raw["mode"]
    elif mutation == "identity":
        raw["command_id"] = "0" * 64
    else:
        raw["mode"] = "LIVE"
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_command(_canonical(raw))


@pytest.mark.parametrize(
    "payload",
    [
        b'{"command_id":"x","command_id":"x"}',
        b"{}\n",
        b"\xef\xbb\xbf{}",
        b'{"quantity":NaN}',
        b'\xff',
    ],
)
def test_hostile_json_forms_fail_closed(payload: bytes) -> None:
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_command(payload)


def test_decimal_and_datetime_are_strict() -> None:
    raw = json.loads(encode_order_command(_command()))
    raw["intent"]["limit_price"] = "1E+1"
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_command(_canonical(raw))
    raw = json.loads(encode_order_command(_command()))
    raw["intent"]["generated_at"] = "2026-07-19T16:00:00.000000+08:00"
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_command(_canonical(raw))


@pytest.mark.parametrize(
    "version",
    [None, "", "v2", "garbage", "m4-other-v2", "m4-order-command-v0", "m4-order-command-v02", 2],
)
def test_malformed_or_wrong_family_schema_versions_are_invalid(version: object) -> None:
    raw = json.loads(encode_order_command(_command()))
    raw["schema_version"] = version
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_command(_canonical(raw))


@pytest.mark.parametrize("version", ["m4-order-command-v2", "m4-order-command-v17"])
def test_canonical_future_schema_versions_are_unsupported(version: str) -> None:
    raw = json.loads(encode_order_command(_command()))
    raw["schema_version"] = version
    with pytest.raises(WireError, match="^WIRE_VERSION_UNSUPPORTED$"):
        decode_order_command(_canonical(raw))


def test_parser_and_constructor_failures_do_not_leak_exception_chain(monkeypatch) -> None:
    with pytest.raises(WireError) as parse_error:
        decode_order_command(b"\xffTOKEN")
    _assert_sanitized(parse_error.value)
    assert "TOKEN" not in repr(parse_error.value)

    def hostile_constructor(**_kwargs):
        raise RuntimeError("TOKEN")

    monkeypatch.setattr("quant.execution.wire.build_order_intent", hostile_constructor)
    with pytest.raises(WireError) as constructor_error:
        decode_order_command(encode_order_command(_command()))
    _assert_sanitized(constructor_error.value)
    assert "TOKEN" not in repr(constructor_error.value)


def test_event_and_aggregate_must_close_over_the_supplied_command() -> None:
    command = _command()
    other = build_order_command(
        intent=build_order_intent(
            plan_id=command.intent.plan_id,
            symbol=command.intent.symbol,
            market=command.intent.market,
            side=command.intent.side,
            quantity=200,
            limit_price=command.intent.limit_price,
            quote_currency=command.intent.quote_currency,
            session_date=command.intent.session_date,
            generated_at=command.intent.generated_at,
            target_identity=command.intent.target_identity,
            market_snapshot_id=command.intent.market_snapshot_id,
            account_snapshot_id=command.intent.account_snapshot_id,
            config_identity=command.intent.config_identity,
            connect_route=None,
        ),
        mode=ExecutionMode.PAPER,
    )
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_execution_event(encode_execution_event(_event(command)), command=other)

    raw = json.loads(encode_order_aggregate(new_order_aggregate(command)))
    raw["command_quantity"] = 200
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_order_aggregate(_canonical(raw), command=command)


def test_fill_event_fee_round_trip_and_noncanonical_fee_decimal_rejected() -> None:
    command = _command()
    event = build_execution_event(
        command=command,
        broker_order_id="PAPER-1",
        event_type=ExecutionEventType.FILL,
        occurred_at=NOW,
        cumulative_quantity=100,
        last_quantity=100,
        last_price=Decimal("10"),
        fees=(
            build_fee_component(
                code="COMMISSION",
                amount=build_money_amount(Currency.CNY, Decimal("5.00")),
                statutory=False,
                rule_version="fees-v1",
            ),
        ),
        reject_code=None,
    )
    payload = encode_execution_event(event)
    assert decode_execution_event(payload, command=command) == event
    raw = json.loads(payload)
    raw["fees"][0]["amount"]["amount"] = "5E+0"
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_execution_event(_canonical(raw), command=command)
