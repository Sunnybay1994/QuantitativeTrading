"""M4-D0 OMS/ledger domain contracts: strict constructors, identities, counterexamples."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from decimal import Decimal
from pathlib import Path

import pytest

from quant.domain.enums import (
    ConnectRoute,
    Currency,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quant.execution.contracts import (
    AccountSnapshot,
    ContractError,
    ExecutionEvent,
    FeeComponent,
    MoneyAmount,
    OrderCommand,
    OrderIntent,
    OrderIntentSpec,
    OrderPlan,
    RuleDecision,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
    build_account_snapshot,
    build_account_snapshot_identity,
    build_cash_balance,
    build_execution_event,
    build_execution_event_identity,
    build_fee_component,
    build_money_amount,
    build_money_amount_identity,
    build_order_command,
    build_order_command_identity,
    build_order_intent,
    build_order_intent_identity,
    build_order_plan,
    build_order_plan_identity,
    build_position_balance,
    build_rule_decision,
    build_symbol_market_state,
    build_symbol_market_state_identity,
    build_verified_connect_market_context,
    build_verified_connect_market_context_identity,
    build_verified_market_snapshot,
    build_verified_market_snapshot_identity,
)


UTC = dt.timezone.utc


def _hex64(label: str) -> str:
    """Deterministic fake 64-hex reference identity for tests."""
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _utc(hour: int = 2) -> dt.datetime:
    return dt.datetime(2026, 7, 16, hour, 0, 0, tzinfo=UTC)


def _p0b1_ctx(
    *,
    route: ConnectRoute = ConnectRoute.SH_CONNECT,
    session_date: dt.date = dt.date(2026, 7, 16),
    as_of: dt.datetime | None = None,
    buy_quota_available: bool = True,
) -> VerifiedConnectMarketContext:
    return build_verified_connect_market_context(
        route=route,
        session_date=session_date,
        as_of=as_of or _utc(),
        mainland_open=True,
        hong_kong_open=True,
        buy_quota_available=buy_quota_available,
        calendar_identity=_hex64("cal"),
        quota_identity=_hex64("quota"),
        source_identity=_hex64("src"),
    )


def test_execution_mode_has_no_live() -> None:
    assert {m.value for m in ExecutionMode} == {"PAPER", "SHADOW"}
    assert not hasattr(ExecutionMode, "LIVE")
    assert OrderType.LIMIT.value == "LIMIT"
    assert TimeInForce.DAY.value == "DAY"
    assert ExecutionEventType.FILL.value == "FILL"


def test_money_amount_rejects_non_finite_and_cross_currency_add() -> None:
    ok = build_money_amount(Currency.CNY, Decimal("1.25"))
    assert build_money_amount_identity(ok) == build_money_amount_identity(
        MoneyAmount(currency=Currency.CNY, amount=Decimal("1.25"))
    )
    with pytest.raises(ContractError):
        build_money_amount(Currency.CNY, Decimal("NaN"))
    with pytest.raises(ContractError):
        build_money_amount(Currency.CNY, Decimal("Infinity"))
    cny = build_money_amount(Currency.CNY, Decimal("1"))
    hkd = build_money_amount(Currency.HKD, Decimal("1"))
    with pytest.raises(ContractError, match="currency"):
        _ = cny + hkd
    assert (cny + cny).amount == Decimal("2")


def test_naive_datetime_rejected_on_snapshots_and_events() -> None:
    naive = dt.datetime(2026, 7, 16, 2, 0, 0)
    pos = build_position_balance(
        symbol="600000.SH",
        market=Market.SH,
        quantity=100,
        sellable_quantity=100,
        avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
    )
    cash = build_cash_balance(
        currency=Currency.CNY,
        settled=Decimal("1000"),
        available=Decimal("800"),
        receivable=Decimal("0"),
        payable=Decimal("0"),
    )
    with pytest.raises(ContractError, match="timezone|UTC|aware"):
        build_account_snapshot(as_of=naive, positions=(pos,), cash=(cash,))

    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10.5"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    command = build_order_command(intent=intent, mode=ExecutionMode.PAPER)
    with pytest.raises(ContractError, match="timezone|UTC|aware"):
        build_execution_event(
            command=command,
            broker_order_id=None,
            event_type=ExecutionEventType.ACCEPTED,
            occurred_at=naive,
            cumulative_quantity=0,
            last_quantity=0,
            last_price=None,
            fees=(),
            reject_code=None,
        )


def test_duplicate_keys_rejected_and_collections_canonical_sorted() -> None:
    pos_a = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=100,
        sellable_quantity=50,
        avg_cost=build_money_amount(Currency.CNY, Decimal("1")),
    )
    pos_b = build_position_balance(
        symbol="600000.SH",
        market=Market.SH,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("2")),
    )
    cash_cny = build_cash_balance(
        currency=Currency.CNY,
        settled=Decimal("10"),
        available=Decimal("10"),
        receivable=Decimal("0"),
        payable=Decimal("0"),
    )
    snap = build_account_snapshot(
        as_of=_utc(),
        positions=(pos_a, pos_b),
        cash=(cash_cny,),
    )
    assert [p.symbol for p in snap.positions] == ["600000.SH", "000001.SZ"]
    assert snap.snapshot_id == build_account_snapshot_identity(snap)

    dup = build_position_balance(
        symbol="600000.SH",
        market=Market.SH,
        quantity=1,
        sellable_quantity=1,
        avg_cost=build_money_amount(Currency.CNY, Decimal("1")),
    )
    with pytest.raises(ContractError, match="duplicate"):
        build_account_snapshot(as_of=_utc(), positions=(pos_b, dup), cash=(cash_cny,))

    with pytest.raises(ContractError, match="duplicate"):
        build_account_snapshot(
            as_of=_utc(),
            positions=(),
            cash=(cash_cny, cash_cny),
        )


def test_caller_supplied_hash_rejected() -> None:
    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    fake = "0" * 64
    with pytest.raises(ContractError, match="identity|hash"):
        OrderIntent(
            intent_id=fake,
            plan_id=intent.plan_id,
            symbol=intent.symbol,
            market=intent.market,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            quote_currency=intent.quote_currency,
            session_date=intent.session_date,
            generated_at=intent.generated_at,
            target_identity=intent.target_identity,
            market_snapshot_id=intent.market_snapshot_id,
            account_snapshot_id=intent.account_snapshot_id,
            config_identity=intent.config_identity,
            connect_route=None,
        )
    assert build_order_intent_identity(intent) == intent.intent_id


def test_execution_event_field_closure_illegal_combinations() -> None:
    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    command = build_order_command(intent=intent, mode=ExecutionMode.PAPER)
    assert command.order_type is OrderType.LIMIT
    assert command.time_in_force is TimeInForce.DAY
    assert build_order_command_identity(command) == command.command_id

    with pytest.raises(ContractError):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.ACCEPTED,
            occurred_at=_utc(3),
            cumulative_quantity=0,
            last_quantity=10,
            last_price=Decimal("10"),
            fees=(),
            reject_code=None,
        )

    with pytest.raises(ContractError):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.FILL,
            occurred_at=_utc(3),
            cumulative_quantity=50,
            last_quantity=50,
            last_price=None,
            fees=(),
            reject_code=None,
        )

    with pytest.raises(ContractError):
        build_execution_event(
            command=command,
            broker_order_id=None,
            event_type=ExecutionEventType.REJECTED,
            occurred_at=_utc(3),
            cumulative_quantity=0,
            last_quantity=0,
            last_price=None,
            fees=(),
            reject_code=None,
        )

    with pytest.raises(ContractError):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.FILL,
            occurred_at=_utc(3),
            cumulative_quantity=150,
            last_quantity=150,
            last_price=Decimal("10"),
            fees=(),
            reject_code=None,
        )

    fill = build_execution_event(
        command=command,
        broker_order_id="B1",
        event_type=ExecutionEventType.PARTIAL_FILL,
        occurred_at=_utc(3),
        cumulative_quantity=40,
        last_quantity=40,
        last_price=Decimal("10.01"),
        fees=(
            build_fee_component(
                code="commission",
                amount=build_money_amount(Currency.CNY, Decimal("0.5")),
                statutory=False,
                rule_version="fee-v1",
            ),
        ),
        reject_code=None,
    )
    assert build_execution_event_identity(fill) == fill.event_id
    with pytest.raises(ContractError, match="identity|hash"):
        ExecutionEvent(
            event_id="f" * 64,
            command_id=fill.command_id,
            broker_order_id=fill.broker_order_id,
            event_type=fill.event_type,
            occurred_at=fill.occurred_at,
            cumulative_quantity=fill.cumulative_quantity,
            last_quantity=fill.last_quantity,
            last_price=fill.last_price,
            fees=fill.fees,
            reject_code=fill.reject_code,
        )


def test_market_currency_and_position_cash_invariants() -> None:
    with pytest.raises(ContractError):
        build_symbol_market_state(
            symbol="600000.SH",
            market=Market.SH,
            session_date=dt.date(2026, 7, 16),
            quote_currency=Currency.HKD,
            reference_price=Decimal("10"),
            limit_up=Decimal("11"),
            limit_down=Decimal("9"),
            suspended=False,
            board_lot=100,
            tick_size=Decimal("0.01"),
            rule_version="a-v1",
        )
    with pytest.raises(ContractError):
        build_position_balance(
            symbol="600000.SH",
            market=Market.SH,
            quantity=10,
            sellable_quantity=11,
            avg_cost=build_money_amount(Currency.CNY, Decimal("1")),
        )
    with pytest.raises(ContractError):
        build_cash_balance(
            currency=Currency.CNY,
            settled=Decimal("10"),
            available=Decimal("11"),
            receivable=Decimal("0"),
            payable=Decimal("0"),
        )
    state_sh = build_symbol_market_state(
        symbol="600000.SH",
        market=Market.SH,
        session_date=dt.date(2026, 7, 16),
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a-v1",
    )
    state_hk = build_symbol_market_state(
        symbol="00700.HK",
        market=Market.HK,
        session_date=dt.date(2026, 7, 16),
        quote_currency=Currency.HKD,
        reference_price=Decimal("300"),
        limit_up=None,
        limit_down=None,
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.2"),
        rule_version="hk-v1",
    )
    market = build_verified_market_snapshot(
        as_of=_utc(),
        session_date=dt.date(2026, 7, 16),
        states=(state_hk, state_sh),
        connect_contexts=(_p0b1_ctx(),),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    assert [s.symbol for s in market.states] == ["00700.HK", "600000.SH"]
    assert market.snapshot_id == build_verified_market_snapshot_identity(market)


def test_order_plan_unique_intent_keys_and_identity() -> None:
    spec_buy = OrderIntentSpec(
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    spec_sell = OrderIntentSpec(
        symbol="000001.SZ",
        market=Market.SZ,
        side=OrderSide.SELL,
        quantity=200,
        limit_price=Decimal("12"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(1),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    rejection = build_rule_decision(
        accepted=False,
        code="SUSPENDED",
        normalized_quantity=0,
        normalized_limit_price=Decimal("0"),
        rule_version="a-v1",
    )
    plan = build_order_plan(
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        intent_specs=(spec_buy, spec_sell),
        rejections=(rejection,),
        residual_cash=(build_money_amount(Currency.CNY, Decimal("5")),),
    )
    assert [i.symbol for i in plan.intents] == ["600000.SH", "000001.SZ"]
    assert all(i.plan_id == plan.plan_id for i in plan.intents)
    assert build_order_plan_identity(plan) == plan.plan_id

    dup_spec = OrderIntentSpec(
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=50,
        limit_price=Decimal("9"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    with pytest.raises(ContractError, match="duplicate"):
        build_order_plan(
            target_identity=_hex64("target"),
            market_snapshot_id=_hex64("mkt"),
            account_snapshot_id=_hex64("acct"),
            config_identity=_hex64("cfg"),
            intent_specs=(spec_buy, dup_spec),
            rejections=(),
            residual_cash=(),
        )


def test_fee_component_rejects_negative_and_account_snapshot_roundtrip() -> None:
    with pytest.raises(ContractError):
        build_fee_component(
            code="tax",
            amount=build_money_amount(Currency.CNY, Decimal("-1")),
            statutory=True,
            rule_version="fee-v1",
        )
    fee = build_fee_component(
        code="tax",
        amount=build_money_amount(Currency.CNY, Decimal("0")),
        statutory=True,
        rule_version="fee-v1",
    )
    assert isinstance(fee, FeeComponent)
    assert isinstance(build_rule_decision(
        accepted=True,
        code="OK",
        normalized_quantity=100,
        normalized_limit_price=Decimal("10"),
        rule_version="a-v1",
    ), RuleDecision)

    # Direct AccountSnapshot with forged snapshot_id must fail.
    cash = build_cash_balance(
        currency=Currency.CNY,
        settled=Decimal("1"),
        available=Decimal("1"),
        receivable=Decimal("0"),
        payable=Decimal("0"),
    )
    good = build_account_snapshot(as_of=_utc(), positions=(), cash=(cash,))
    with pytest.raises(ContractError, match="identity|hash"):
        AccountSnapshot(
            snapshot_id="a" * 64,
            as_of=good.as_of,
            positions=good.positions,
            cash=good.cash,
        )


def test_order_command_rejects_forged_command_id() -> None:
    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="00700.HK",
        market=Market.HK,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("300"),
        quote_currency=Currency.HKD,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=ConnectRoute.SH_CONNECT,
    )
    command = build_order_command(intent=intent, mode=ExecutionMode.SHADOW)
    with pytest.raises(ContractError, match="identity|hash"):
        OrderCommand(
            command_id="b" * 64,
            intent=command.intent,
            mode=command.mode,
            order_type=command.order_type,
            time_in_force=command.time_in_force,
        )


def test_verified_market_snapshot_duplicate_symbol_rejected() -> None:
    state = build_symbol_market_state(
        symbol="600000.SH",
        market=Market.SH,
        session_date=dt.date(2026, 7, 16),
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a-v1",
    )
    with pytest.raises(ContractError, match="duplicate"):
        build_verified_market_snapshot(
            as_of=_utc(),
            session_date=dt.date(2026, 7, 16),
            states=(state, state),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )
    with pytest.raises(ContractError, match="identity|hash"):
        VerifiedMarketSnapshot(
            snapshot_id="c" * 64,
            as_of=_utc(),
            session_date=dt.date(2026, 7, 16),
            states=(state,),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )


def test_order_plan_forged_plan_id_rejected() -> None:
    spec = OrderIntentSpec(
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    plan = build_order_plan(
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        intent_specs=(spec,),
        rejections=(),
        residual_cash=(),
    )
    with pytest.raises(ContractError, match="identity|hash|plan_id"):
        OrderPlan(
            plan_id="d" * 64,
            target_identity=plan.target_identity,
            market_snapshot_id=plan.market_snapshot_id,
            account_snapshot_id=plan.account_snapshot_id,
            config_identity=plan.config_identity,
            intents=plan.intents,
            rejections=plan.rejections,
            residual_cash=plan.residual_cash,
        )


def _aligned_intent_spec(**overrides: object) -> OrderIntentSpec:
    base: dict[str, object] = {
        "symbol": "600000.SH",
        "market": Market.SH,
        "side": OrderSide.BUY,
        "quantity": 100,
        "limit_price": Decimal("10"),
        "quote_currency": Currency.CNY,
        "session_date": dt.date(2026, 7, 16),
        "generated_at": _utc(),
        "target_identity": _hex64("target"),
        "market_snapshot_id": _hex64("mkt"),
        "account_snapshot_id": _hex64("acct"),
        "config_identity": _hex64("cfg"),
        "connect_route": None,
    }
    base.update(overrides)
    return OrderIntentSpec(**base)  # type: ignore[arg-type]


def test_order_plan_rejects_nested_identity_mismatch_and_replace() -> None:
    from dataclasses import replace

    plan_ids = {
        "target_identity": _hex64("target"),
        "market_snapshot_id": _hex64("mkt"),
        "account_snapshot_id": _hex64("acct"),
        "config_identity": _hex64("cfg"),
    }
    mismatch_fields = (
        ("target_identity", _hex64("target-other")),
        ("market_snapshot_id", _hex64("mkt-other")),
        ("account_snapshot_id", _hex64("acct-other")),
        ("config_identity", _hex64("cfg-other")),
    )
    for field, other in mismatch_fields:
        bad_spec = _aligned_intent_spec(**{field: other})
        with pytest.raises(ContractError, match="must match plan"):
            build_order_plan(
                **plan_ids,
                intent_specs=(bad_spec,),
                rejections=(),
                residual_cash=(),
            )

    good_spec = _aligned_intent_spec()
    plan = build_order_plan(
        **plan_ids,
        intent_specs=(good_spec,),
        rejections=(),
        residual_cash=(),
    )
    with pytest.raises(ContractError):
        replace(plan, target_identity=_hex64("target-replaced"))

    foreign_intent = build_order_intent(
        plan_id=plan.plan_id,
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target-foreign"),
        market_snapshot_id=plan.market_snapshot_id,
        account_snapshot_id=plan.account_snapshot_id,
        config_identity=plan.config_identity,
        connect_route=None,
    )
    with pytest.raises(ContractError, match="must match plan"):
        replace(plan, intents=(foreign_intent,))


def test_execution_event_bound_to_real_command_quantity() -> None:
    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=10,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    command = build_order_command(intent=intent, mode=ExecutionMode.PAPER)

    with pytest.raises(ContractError, match="command quantity|cumulative"):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.FILL,
            occurred_at=_utc(3),
            cumulative_quantity=11,
            last_quantity=11,
            last_price=Decimal("10"),
            fees=(),
            reject_code=None,
        )
    with pytest.raises(ContractError, match="command quantity|cumulative"):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.CANCELLED,
            occurred_at=_utc(3),
            cumulative_quantity=11,
            last_quantity=0,
            last_price=None,
            fees=(),
            reject_code=None,
        )

    zero = build_execution_event(
        command=command,
        broker_order_id="B1",
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=_utc(3),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    partial = build_execution_event(
        command=command,
        broker_order_id="B1",
        event_type=ExecutionEventType.PARTIAL_FILL,
        occurred_at=_utc(4),
        cumulative_quantity=5,
        last_quantity=5,
        last_price=Decimal("10"),
        fees=(),
        reject_code=None,
    )
    full = build_execution_event(
        command=command,
        broker_order_id="B1",
        event_type=ExecutionEventType.FILL,
        occurred_at=_utc(5),
        cumulative_quantity=10,
        last_quantity=10,
        last_price=Decimal("10"),
        fees=(),
        reject_code=None,
    )
    assert zero.cumulative_quantity == 0
    assert partial.cumulative_quantity == 5
    assert full.cumulative_quantity == 10
    assert zero.command_id == command.command_id


def test_verified_market_snapshot_rejects_session_date_mismatch() -> None:
    state_ok = build_symbol_market_state(
        symbol="600000.SH",
        market=Market.SH,
        session_date=dt.date(2026, 7, 16),
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a-v1",
    )
    state_bad = build_symbol_market_state(
        symbol="000001.SZ",
        market=Market.SZ,
        session_date=dt.date(2026, 7, 15),
        quote_currency=Currency.CNY,
        reference_price=Decimal("12"),
        limit_up=Decimal("13"),
        limit_down=Decimal("11"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a-v1",
    )
    with pytest.raises(ContractError, match="session_date"):
        build_verified_market_snapshot(
            as_of=_utc(),
            session_date=dt.date(2026, 7, 16),
            states=(state_bad,),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )
    with pytest.raises(ContractError, match="session_date"):
        build_verified_market_snapshot(
            as_of=_utc(),
            session_date=dt.date(2026, 7, 16),
            states=(state_ok, state_bad),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )


def test_order_intent_spec_strict_constructor_rejects_bad_fields() -> None:
    with pytest.raises(ContractError):
        OrderIntentSpec(
            symbol="600000.SH",
            market="SH",  # type: ignore[arg-type]
            side=OrderSide.BUY,
            quantity=100,
            limit_price=Decimal("10"),
            quote_currency=Currency.CNY,
            session_date=dt.date(2026, 7, 16),
            generated_at=_utc(),
            target_identity=_hex64("target"),
            market_snapshot_id=_hex64("mkt"),
            account_snapshot_id=_hex64("acct"),
            config_identity=_hex64("cfg"),
            connect_route=None,
        )
    with pytest.raises(ContractError):
        _aligned_intent_spec(quantity=True)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        _aligned_intent_spec(generated_at=dt.datetime(2026, 7, 16, 2, 0, 0))
    with pytest.raises(ContractError):
        _aligned_intent_spec(quote_currency=Currency.HKD)


def test_builders_reject_wrong_sequence_elements_as_contract_error() -> None:
    pos = build_position_balance(
        symbol="600000.SH",
        market=Market.SH,
        quantity=100,
        sellable_quantity=100,
        avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
    )
    cash = build_cash_balance(
        currency=Currency.CNY,
        settled=Decimal("1"),
        available=Decimal("1"),
        receivable=Decimal("0"),
        payable=Decimal("0"),
    )
    with pytest.raises(ContractError):
        build_account_snapshot(as_of=_utc(), positions=("not-a-position",), cash=(cash,))  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        build_account_snapshot(as_of=_utc(), positions=(pos,), cash=("not-cash",))  # type: ignore[arg-type]

    with pytest.raises(ContractError):
        build_verified_market_snapshot(
            as_of=_utc(),
            session_date=dt.date(2026, 7, 16),
            states=("bad-state",),  # type: ignore[arg-type]
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )

    intent = build_order_intent(
        plan_id=_hex64("plan"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=10,
        limit_price=Decimal("10"),
        quote_currency=Currency.CNY,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    command = build_order_command(intent=intent, mode=ExecutionMode.PAPER)
    with pytest.raises(ContractError):
        build_execution_event(
            command=command,
            broker_order_id="B1",
            event_type=ExecutionEventType.ACCEPTED,
            occurred_at=_utc(3),
            cumulative_quantity=0,
            last_quantity=0,
            last_price=None,
            fees=("bad-fee",),  # type: ignore[arg-type]
            reject_code=None,
        )

    good_spec = _aligned_intent_spec()
    with pytest.raises(ContractError):
        build_order_plan(
            target_identity=_hex64("target"),
            market_snapshot_id=_hex64("mkt"),
            account_snapshot_id=_hex64("acct"),
            config_identity=_hex64("cfg"),
            intent_specs=(good_spec,),
            rejections=("bad-rejection",),  # type: ignore[arg-type]
            residual_cash=(),
        )
    with pytest.raises(ContractError):
        build_order_plan(
            target_identity=_hex64("target"),
            market_snapshot_id=_hex64("mkt"),
            account_snapshot_id=_hex64("acct"),
            config_identity=_hex64("cfg"),
            intent_specs=(good_spec,),
            rejections=(),
            residual_cash=("bad-cash",),  # type: ignore[arg-type]
        )


def _connect_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "route": ConnectRoute.SH_CONNECT,
        "session_date": dt.date(2026, 7, 10),
        "as_of": dt.datetime(2026, 7, 10, 8, 0, 0, tzinfo=UTC),
        "mainland_open": True,
        "hong_kong_open": False,
        "buy_quota_available": True,
        "calendar_identity": "a" * 64,
        "quota_identity": "b" * 64,
        "source_identity": "c" * 64,
    }
    base.update(overrides)
    return base


def test_connect_market_context_frozen_vector_and_route_identity() -> None:
    payload = _connect_payload()
    ctx = build_verified_connect_market_context(**payload)  # type: ignore[arg-type]
    assert ctx.context_id == (
        "de53c71c001da5fa70feb5cc5f2745431d9c9107350e0903052a8bd527e162c1"
    )
    assert build_verified_connect_market_context_identity(ctx) == ctx.context_id

    again = build_verified_connect_market_context(
        source_identity=payload["source_identity"],  # type: ignore[arg-type]
        quota_identity=payload["quota_identity"],  # type: ignore[arg-type]
        calendar_identity=payload["calendar_identity"],  # type: ignore[arg-type]
        buy_quota_available=payload["buy_quota_available"],  # type: ignore[arg-type]
        hong_kong_open=payload["hong_kong_open"],  # type: ignore[arg-type]
        mainland_open=payload["mainland_open"],  # type: ignore[arg-type]
        as_of=payload["as_of"],  # type: ignore[arg-type]
        session_date=payload["session_date"],  # type: ignore[arg-type]
        route=payload["route"],  # type: ignore[arg-type]
    )
    assert again.context_id == ctx.context_id

    sz = build_verified_connect_market_context(
        **_connect_payload(route=ConnectRoute.SZ_CONNECT)  # type: ignore[arg-type]
    )
    assert sz.context_id != ctx.context_id


def test_connect_market_context_rejects_route_bool_and_time_types() -> None:
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(route="SH_CONNECT")  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(route="AUTO")  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(route=Market.SH)  # type: ignore[arg-type]
        )

    class FakeRoute(str, Enum):
        SH_CONNECT = "SH_CONNECT"

    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(route=FakeRoute.SH_CONNECT)  # type: ignore[arg-type]
        )

    for field in ("mainland_open", "hong_kong_open", "buy_quota_available"):
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: 1})  # type: ignore[arg-type]
            )
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: 0})  # type: ignore[arg-type]
            )

    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(
                as_of=dt.datetime(2026, 7, 10, 8, 0, 0)  # naive
            )  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(
                as_of=dt.datetime(
                    2026, 7, 10, 16, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))
                )
            )  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(
                session_date=dt.datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)
            )  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError):
        build_verified_connect_market_context(
            **_connect_payload(as_of=dt.date(2026, 7, 10))  # type: ignore[arg-type]
        )


def test_connect_market_context_rejects_upstream_id_and_forged_context_id() -> None:
    good = _connect_payload()
    for field in ("calendar_identity", "quota_identity", "source_identity"):
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: "A" * 64})  # type: ignore[arg-type]
            )
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: "a" * 63})  # type: ignore[arg-type]
            )
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: "a" * 65})  # type: ignore[arg-type]
            )
        with pytest.raises(ContractError):
            build_verified_connect_market_context(
                **_connect_payload(**{field: "g" * 64})  # type: ignore[arg-type]
            )

    ctx = build_verified_connect_market_context(**good)  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="identity|hash"):
        VerifiedConnectMarketContext(
            context_id="0" * 64,
            route=ctx.route,
            session_date=ctx.session_date,
            as_of=ctx.as_of,
            mainland_open=ctx.mainland_open,
            hong_kong_open=ctx.hong_kong_open,
            buy_quota_available=ctx.buy_quota_available,
            calendar_identity=ctx.calendar_identity,
            quota_identity=ctx.quota_identity,
            source_identity=ctx.source_identity,
        )
    # Same forged context_id cannot cover a different economic payload.
    with pytest.raises(ContractError, match="identity|hash"):
        VerifiedConnectMarketContext(
            context_id=ctx.context_id,
            route=ConnectRoute.SZ_CONNECT,
            session_date=ctx.session_date,
            as_of=ctx.as_of,
            mainland_open=ctx.mainland_open,
            hong_kong_open=ctx.hong_kong_open,
            buy_quota_available=ctx.buy_quota_available,
            calendar_identity=ctx.calendar_identity,
            quota_identity=ctx.quota_identity,
            source_identity=ctx.source_identity,
        )


def test_connect_market_context_setattr_tamper_rejects_identity() -> None:
    for field, value in (
        ("route", ConnectRoute.SZ_CONNECT),
        ("session_date", dt.date(2026, 7, 11)),
        ("as_of", dt.datetime(2026, 7, 10, 8, 0, 1, tzinfo=UTC)),
        ("mainland_open", False),
        ("hong_kong_open", True),
        ("buy_quota_available", False),
        ("calendar_identity", "d" * 64),
        ("quota_identity", "e" * 64),
        ("source_identity", "f" * 64),
    ):
        ctx = build_verified_connect_market_context(**_connect_payload())  # type: ignore[arg-type]
        object.__setattr__(ctx, field, value)
        with pytest.raises(ContractError, match="identity|hash"):
            build_verified_connect_market_context_identity(ctx)


def test_connect_market_context_bool_split_and_provenance_sensitivity() -> None:
    # mainland open + HK closed + quota available must construct (no connect_open rule).
    ctx = build_verified_connect_market_context(**_connect_payload())  # type: ignore[arg-type]
    assert ctx.mainland_open is True
    assert ctx.hong_kong_open is False
    assert ctx.buy_quota_available is True

    other_quota = build_verified_connect_market_context(
        **_connect_payload(quota_identity="e" * 64)  # type: ignore[arg-type]
    )
    assert other_quota.context_id != ctx.context_id

    other_as_of = build_verified_connect_market_context(
        **_connect_payload(
            as_of=dt.datetime(2026, 7, 10, 8, 0, 0, 1, tzinfo=UTC)
        )  # type: ignore[arg-type]
    )
    assert other_as_of.context_id != ctx.context_id

    with pytest.raises(TypeError):
        build_verified_connect_market_context(
            **_connect_payload(),  # type: ignore[arg-type]
            context_id="0" * 64,  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        build_verified_connect_market_context(
            **_connect_payload(),  # type: ignore[arg-type]
            hk_open=False,  # type: ignore[call-arg]
        )


def test_connect_market_context_import_isolation() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "quant"
    forbidden = (
        "quant.data",
        "quant.backtest",
        "import tushare",
        "import baostock",
        "import akshare",
        "import qlib",
        "import mlflow",
    )
    for rel in (
        "domain/enums.py",
        "execution/contracts.py",
        "execution/ports.py",
    ):
        source = (root / rel).read_text(encoding="utf-8")
        lowered = source.lower()
        for token in forbidden:
            assert token not in source and token not in lowered, (rel, token)


def _a_share_state(
    *,
    symbol: str = "600000.SH",
    market: Market = Market.SH,
    session_date: dt.date = dt.date(2026, 7, 16),
) -> object:
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=session_date,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="a-v1",
    )


def _hk_state(
    *,
    session_date: dt.date = dt.date(2026, 7, 16),
) -> object:
    return build_symbol_market_state(
        symbol="00700.HK",
        market=Market.HK,
        session_date=session_date,
        quote_currency=Currency.HKD,
        reference_price=Decimal("300"),
        limit_up=None,
        limit_down=None,
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.2"),
        rule_version="hk-v1",
    )


def test_p0b1_intent_route_required_for_hk_forbidden_for_a_share() -> None:
    common = dict(
        plan_id=_hex64("plan"),
        side=OrderSide.BUY,
        quantity=100,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
    )
    with pytest.raises(ContractError, match="connect_route"):
        build_order_intent(
            **common,  # type: ignore[arg-type]
            symbol="00700.HK",
            market=Market.HK,
            limit_price=Decimal("300"),
            quote_currency=Currency.HKD,
            connect_route=None,
        )
    with pytest.raises(ContractError, match="ConnectRoute|connect_route"):
        build_order_intent(
            **common,  # type: ignore[arg-type]
            symbol="00700.HK",
            market=Market.HK,
            limit_price=Decimal("300"),
            quote_currency=Currency.HKD,
            connect_route="SH_CONNECT",  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError, match="ConnectRoute|connect_route"):
        build_order_intent(
            **common,  # type: ignore[arg-type]
            symbol="00700.HK",
            market=Market.HK,
            limit_price=Decimal("300"),
            quote_currency=Currency.HKD,
            connect_route=Market.SH,  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError, match="connect_route"):
        build_order_intent(
            **common,  # type: ignore[arg-type]
            symbol="600000.SH",
            market=Market.SH,
            limit_price=Decimal("10"),
            quote_currency=Currency.CNY,
            connect_route=ConnectRoute.SH_CONNECT,
        )
    with pytest.raises(ContractError, match="connect_route"):
        OrderIntentSpec(
            symbol="000001.SZ",
            market=Market.SZ,
            side=OrderSide.SELL,
            quantity=100,
            limit_price=Decimal("12"),
            quote_currency=Currency.CNY,
            session_date=dt.date(2026, 7, 16),
            generated_at=_utc(),
            target_identity=_hex64("target"),
            market_snapshot_id=_hex64("mkt"),
            account_snapshot_id=_hex64("acct"),
            config_identity=_hex64("cfg"),
            connect_route=ConnectRoute.SZ_CONNECT,
        )


def test_p0b1_intent_route_changes_identity_and_forged_route_rejected() -> None:
    base = dict(
        plan_id=_hex64("plan"),
        symbol="00700.HK",
        market=Market.HK,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("300"),
        quote_currency=Currency.HKD,
        session_date=dt.date(2026, 7, 16),
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
    )
    sh = build_order_intent(**base, connect_route=ConnectRoute.SH_CONNECT)  # type: ignore[arg-type]
    sz = build_order_intent(**base, connect_route=ConnectRoute.SZ_CONNECT)  # type: ignore[arg-type]
    assert sh.intent_id != sz.intent_id
    assert build_order_intent_identity(sh) == sh.intent_id

    with pytest.raises(ContractError, match="identity|hash"):
        OrderIntent(
            intent_id=sh.intent_id,
            plan_id=sh.plan_id,
            symbol=sh.symbol,
            market=sh.market,
            side=sh.side,
            quantity=sh.quantity,
            limit_price=sh.limit_price,
            quote_currency=sh.quote_currency,
            session_date=sh.session_date,
            generated_at=sh.generated_at,
            target_identity=sh.target_identity,
            market_snapshot_id=sh.market_snapshot_id,
            account_snapshot_id=sh.account_snapshot_id,
            config_identity=sh.config_identity,
            connect_route=ConnectRoute.SZ_CONNECT,
        )

    object.__setattr__(sh, "connect_route", ConnectRoute.SZ_CONNECT)
    with pytest.raises(ContractError, match="identity|hash"):
        build_order_intent_identity(sh)


def test_p0b1_symbol_market_state_rejects_buy_quota_field() -> None:
    state = build_symbol_market_state(
        symbol="00700.HK",
        market=Market.HK,
        session_date=dt.date(2026, 7, 16),
        quote_currency=Currency.HKD,
        reference_price=Decimal("300"),
        limit_up=None,
        limit_down=None,
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.2"),
        rule_version="hk-v1",
    )
    assert not hasattr(state, "buy_quota_available")
    assert len(build_symbol_market_state_identity(state)) == 64
    with pytest.raises(TypeError):
        build_symbol_market_state(  # type: ignore[call-arg]
            symbol="00700.HK",
            market=Market.HK,
            session_date=dt.date(2026, 7, 16),
            quote_currency=Currency.HKD,
            reference_price=Decimal("300"),
            limit_up=None,
            limit_down=None,
            suspended=False,
            board_lot=100,
            tick_size=Decimal("0.2"),
            buy_quota_available=True,
            rule_version="hk-v1",
        )


def test_p0b1_snapshot_connect_contexts_order_independent_and_rejects() -> None:
    session = dt.date(2026, 7, 16)
    as_of = _utc(3)
    sh_ctx = _p0b1_ctx(route=ConnectRoute.SH_CONNECT, session_date=session, as_of=_utc(1))
    sz_ctx = _p0b1_ctx(route=ConnectRoute.SZ_CONNECT, session_date=session, as_of=_utc(2))
    hk = _hk_state(session_date=session)

    snap_a = build_verified_market_snapshot(
        as_of=as_of,
        session_date=session,
        states=(hk,),  # type: ignore[arg-type]
        connect_contexts=(sz_ctx, sh_ctx),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    snap_b = build_verified_market_snapshot(
        as_of=as_of,
        session_date=session,
        states=(hk,),  # type: ignore[arg-type]
        connect_contexts=(sh_ctx, sz_ctx),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    assert snap_a.snapshot_id == snap_b.snapshot_id
    assert [c.route for c in snap_a.connect_contexts] == [
        ConnectRoute.SH_CONNECT,
        ConnectRoute.SZ_CONNECT,
    ]

    with pytest.raises(ContractError, match="duplicate|route"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(hk,),  # type: ignore[arg-type]
            connect_contexts=(sh_ctx, sh_ctx),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )

    bad_session = _p0b1_ctx(
        route=ConnectRoute.SH_CONNECT,
        session_date=dt.date(2026, 7, 15),
        as_of=_utc(1),
    )
    with pytest.raises(ContractError, match="session_date"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(hk,),  # type: ignore[arg-type]
            connect_contexts=(bad_session,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )

    future_ctx = _p0b1_ctx(
        route=ConnectRoute.SH_CONNECT,
        session_date=session,
        as_of=_utc(9),
    )
    with pytest.raises(ContractError, match="as_of"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(hk,),  # type: ignore[arg-type]
            connect_contexts=(future_ctx,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )

    forged_ctx = _p0b1_ctx(
        route=ConnectRoute.SH_CONNECT, session_date=session, as_of=_utc(1)
    )
    object.__setattr__(forged_ctx, "context_id", "0" * 64)
    with pytest.raises(ContractError, match="identity|hash|context_id"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(hk,),  # type: ignore[arg-type]
            connect_contexts=(forged_ctx,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )


def test_p0b1_snapshot_hk_requires_context_a_share_forbids_context() -> None:
    session = dt.date(2026, 7, 16)
    as_of = _utc()
    hk = _hk_state(session_date=session)
    sh = _a_share_state(session_date=session)
    ctx = _p0b1_ctx(session_date=session, as_of=as_of)

    with pytest.raises(ContractError, match="connect context"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(hk,),  # type: ignore[arg-type]
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )
    with pytest.raises(ContractError, match="empty|no HK"):
        build_verified_market_snapshot(
            as_of=as_of,
            session_date=session,
            states=(sh,),  # type: ignore[arg-type]
            connect_contexts=(ctx,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )

    a_only = build_verified_market_snapshot(
        as_of=as_of,
        session_date=session,
        states=(sh,),  # type: ignore[arg-type]
        connect_contexts=(),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    a_only_again = build_verified_market_snapshot(
        as_of=as_of,
        session_date=session,
        states=(sh,),  # type: ignore[arg-type]
        connect_contexts=(),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    assert a_only.snapshot_id == a_only_again.snapshot_id
    assert a_only.connect_contexts == ()

    # A-share identity must not change when unrelated connect facts vary outside snapshot
    other_ctx_id = _p0b1_ctx(
        route=ConnectRoute.SZ_CONNECT,
        session_date=session,
        as_of=as_of,
        buy_quota_available=False,
    ).context_id
    assert other_ctx_id != ctx.context_id
    assert build_verified_market_snapshot_identity(a_only) == a_only.snapshot_id

