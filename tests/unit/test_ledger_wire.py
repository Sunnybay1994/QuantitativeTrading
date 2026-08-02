"""P0B ledger wire round-trip and identity-closure tests."""

from __future__ import annotations

import datetime as dt
import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest

from quant.backtest.ledger import (
    apply_execution_event,
    build_ledger_state,
    build_settlement_rule,
)
from quant.backtest.ledger_wire import (
    decode_ledger_entry,
    decode_ledger_state,
    encode_ledger_entry,
    encode_ledger_state,
)
from quant.domain.enums import Currency, ExecutionEventType, ExecutionMode, Market, OrderSide
from quant.execution.contracts import (
    build_account_snapshot,
    build_cash_balance,
    build_execution_event,
    build_order_command,
    build_order_intent,
)
from quant.execution.wire import WireError

DAY = dt.date(2026, 7, 17)
NOW = dt.datetime(2026, 7, 17, 2, tzinfo=dt.UTC)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _assert_sanitized(error: WireError) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True


def _transition():
    account = build_account_snapshot(
        as_of=NOW,
        positions=(),
        cash=(
            build_cash_balance(
                currency=Currency.CNY,
                settled=Decimal("10000"),
                available=Decimal("10000"),
                receivable=Decimal(0),
                payable=Decimal(0),
            ),
        ),
    )
    state = build_ledger_state(account, as_of_date=DAY)
    command = build_order_command(
        intent=build_order_intent(
            plan_id="a" * 64,
            symbol="600000.SH",
            market=Market.SH,
            side=OrderSide.BUY,
            quantity=100,
            limit_price=Decimal("10"),
            quote_currency=Currency.CNY,
            session_date=DAY,
            generated_at=NOW,
            target_identity="b" * 64,
            market_snapshot_id="c" * 64,
            account_snapshot_id="d" * 64,
            config_identity="e" * 64,
            connect_route=None,
        ),
        mode=ExecutionMode.PAPER,
    )
    event = build_execution_event(
        command=command,
        broker_order_id="paper-1",
        event_type=ExecutionEventType.FILL,
        occurred_at=NOW + dt.timedelta(hours=1),
        cumulative_quantity=100,
        last_quantity=100,
        last_price=Decimal("10"),
        fees=(),
        reject_code=None,
    )
    rule = build_settlement_rule(
        selector="sh-settlement-v1",
        market=Market.SH,
        quote_currency=Currency.CNY,
        settlement_currency=Currency.CNY,
        effective_from=DAY,
        effective_to=None,
        trading_sessions=(DAY, DAY + dt.timedelta(days=3)),
        settlement_sessions=(DAY, DAY + dt.timedelta(days=3)),
        trading_calendar_source_identity="f" * 64,
        settlement_calendar_source_identity="1" * 64,
        settlement_lag_sessions=1,
        sellable_lag_sessions=1,
        reuse_sell_receivables=True,
    )
    return state, apply_execution_event(state, command, event, rule, None)


def test_entry_and_state_round_trip_reprove_nested_identities() -> None:
    genesis, transition = _transition()
    assert decode_ledger_state(encode_ledger_state(genesis)) == genesis
    assert decode_ledger_state(encode_ledger_state(transition.state)) == transition.state
    assert transition.entries
    for entry in transition.entries:
        assert decode_ledger_entry(encode_ledger_entry(entry)) == entry


@pytest.mark.parametrize("target", ["entry", "state"])
def test_ledger_identity_tamper_fails_closed(target: str) -> None:
    _, transition = _transition()
    if target == "entry":
        raw = json.loads(encode_ledger_entry(transition.entries[0]))
        raw["entry_id"] = "0" * 64
        decoder = decode_ledger_entry
    else:
        raw = json.loads(encode_ledger_state(transition.state))
        raw["state_id"] = "0" * 64
        decoder = decode_ledger_state
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decoder(_canonical(raw))


def test_ledger_wire_rejects_future_version_duplicate_key_and_nonfinite_decimal() -> None:
    _, transition = _transition()
    raw = json.loads(encode_ledger_entry(transition.entries[0]))
    raw["schema_version"] = "m4-ledger-entry-v2"
    with pytest.raises(WireError, match="^WIRE_VERSION_UNSUPPORTED$"):
        decode_ledger_entry(_canonical(raw))
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_ledger_entry(b'{"entry_id":"x","entry_id":"x"}')
    raw = json.loads(encode_ledger_entry(transition.entries[0]))
    raw["settled_delta"] = "Infinity"
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_ledger_entry(_canonical(raw))


@pytest.mark.parametrize(
    "version",
    [None, "", "v2", "garbage", "m4-order-command-v2", "m4-ledger-entry-v0", "m4-ledger-entry-v02", 2],
)
def test_ledger_malformed_or_wrong_family_schema_versions_are_invalid(version: object) -> None:
    _, transition = _transition()
    raw = json.loads(encode_ledger_entry(transition.entries[0]))
    raw["schema_version"] = version
    with pytest.raises(WireError, match="^WIRE_INVALID$"):
        decode_ledger_entry(_canonical(raw))


def test_ledger_constructor_failure_does_not_leak_exception_chain(monkeypatch) -> None:
    _, transition = _transition()
    payload = encode_ledger_entry(transition.entries[0])

    def hostile_constructor(**_kwargs):
        raise RuntimeError("TOKEN")

    monkeypatch.setattr("quant.backtest.ledger_wire.LedgerEntry", hostile_constructor)
    with pytest.raises(WireError) as caught:
        decode_ledger_entry(payload)
    _assert_sanitized(caught.value)
    assert "TOKEN" not in repr(caught.value)


def test_canonical_wire_dependency_direction_has_no_execution_back_edge() -> None:
    ledger_source = Path("src/quant/backtest/ledger_wire.py").read_text(encoding="utf-8")
    ledger_tree = ast.parse(ledger_source)
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "quant.execution.wire"
        for node in ast.walk(ledger_tree)
    )

    primitive_source = Path("src/quant/domain/canonical_wire.py").read_text(encoding="utf-8")
    primitive_tree = ast.parse(primitive_source)
    forbidden = ("quant.execution", "quant.backtest")
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith(forbidden)
        for node in ast.walk(primitive_tree)
    )
