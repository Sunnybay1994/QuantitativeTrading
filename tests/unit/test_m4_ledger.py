"""Adversarial M4-B5 settlement-ledger tests."""

from __future__ import annotations

import datetime as dt
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from quant.backtest.corporate_actions import (
    EntitlementPosition,
    recognize_ex_date_entitlements,
    settle_due_entitlements,
)
from quant.backtest.fx import FxRate, build_fx_snapshot
from quant.backtest.ledger import (
    CommandProjection,
    LedgerError,
    advance_ledger_state,
    apply_corporate_action,
    apply_execution_event,
    build_capture_entitlement_transition,
    build_ledger_state,
    build_settlement_rule,
)
from quant.domain.enums import (
    ConnectRoute,
    Currency,
    EntitlementLegState,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
)
from quant.execution.contracts import (
    FeeComponent,
    build_account_snapshot,
    build_cash_balance,
    build_execution_event,
    build_fee_component,
    build_money_amount,
    build_order_command,
    build_order_intent,
    build_position_balance,
)

FRI = dt.date(2026, 7, 17)
MON = dt.date(2026, 7, 20)
TUE = dt.date(2026, 7, 21)
WED = dt.date(2026, 7, 22)
THU = dt.date(2026, 7, 23)
NOW = dt.datetime(2026, 7, 17, 2, tzinfo=dt.UTC)
HEX = "a" * 64


class _NamedUtc(dt.tzinfo):
    def utcoffset(self, value: dt.datetime | None) -> dt.timedelta:
        return dt.timedelta(0)

    def dst(self, value: dt.datetime | None) -> dt.timedelta:
        return dt.timedelta(0)

    def tzname(self, value: dt.datetime | None) -> str:
        return "NAMED_UTC"


class _HostileTz(dt.tzinfo):
    def utcoffset(self, value: dt.datetime | None) -> dt.timedelta:
        raise RuntimeError("hostile timezone payload")

    def dst(self, value: dt.datetime | None) -> dt.timedelta:
        raise RuntimeError("hostile timezone payload")

    def tzname(self, value: dt.datetime | None) -> str:
        raise RuntimeError("hostile timezone payload")


def _rule(
    market: Market = Market.SH,
    *,
    settlement_sessions: tuple[dt.date, ...] = (FRI, MON, TUE, WED, THU),
    reuse: bool = True,
    selector: str | None = None,
):
    hk = market is Market.HK
    return build_settlement_rule(
        selector=selector or f"{market.value.lower()}_settlement_v1",
        market=market,
        quote_currency=Currency.HKD if hk else Currency.CNY,
        settlement_currency=Currency.CNY,
        effective_from=FRI,
        effective_to=None,
        trading_sessions=(FRI, MON, TUE, WED, THU),
        settlement_sessions=settlement_sessions,
        trading_calendar_source_identity="b" * 64,
        settlement_calendar_source_identity="c" * 64,
        settlement_lag_sessions=2 if hk else 1,
        sellable_lag_sessions=0 if hk else 1,
        reuse_sell_receivables=reuse,
    )


def _account(
    *,
    cash: str = "10000",
    positions: tuple[tuple[str, Market, int, int, str], ...] = (),
):
    return build_account_snapshot(
        as_of=NOW,
        positions=tuple(
            build_position_balance(
                symbol=symbol,
                market=market,
                quantity=quantity,
                sellable_quantity=sellable,
                avg_cost=build_money_amount(
                    Currency.HKD if market is Market.HK else Currency.CNY,
                    Decimal(cost),
                ),
            )
            for symbol, market, quantity, sellable, cost in positions
        ),
        cash=(
            build_cash_balance(
                currency=Currency.CNY,
                settled=Decimal(cash),
                available=Decimal(cash),
                receivable=Decimal(0),
                payable=Decimal(0),
            ),
        ),
    )


def _command(
    symbol: str,
    market: Market,
    side: OrderSide,
    quantity: int,
    *,
    price: str = "10",
    mode: ExecutionMode = ExecutionMode.PAPER,
):
    return build_order_command(
        intent=build_order_intent(
            plan_id=HEX,
            symbol=symbol,
            market=market,
            side=side,
            quantity=quantity,
            limit_price=Decimal(price),
            quote_currency=Currency.HKD if market is Market.HK else Currency.CNY,
            session_date=FRI,
            generated_at=NOW,
            target_identity="d" * 64,
            market_snapshot_id="e" * 64,
            account_snapshot_id="f" * 64,
            config_identity="1" * 64,
            connect_route=ConnectRoute.SH_CONNECT if market is Market.HK else None,
        ),
        mode=mode,
    )


def _fill(
    command,
    *,
    cumulative: int,
    last: int,
    price: str = "10",
    fee: str = "0",
    at: dt.datetime = NOW + dt.timedelta(hours=1),
    broker: str | None = "paper-1",
):
    fees: tuple[FeeComponent, ...] = ()
    if Decimal(fee):
        fees = (
            build_fee_component(
                code="COMMISSION",
                amount=build_money_amount(Currency.CNY, Decimal(fee)),
                statutory=False,
                rule_version="fees-v1",
            ),
        )
    return build_execution_event(
        command=command,
        broker_order_id=broker,
        event_type=(
            ExecutionEventType.FILL
            if cumulative == command.intent.quantity
            else ExecutionEventType.PARTIAL_FILL
        ),
        occurred_at=at,
        cumulative_quantity=cumulative,
        last_quantity=last,
        last_price=Decimal(price),
        fees=fees,
        reject_code=None,
    )


def _cash(state):
    return next(item for item in state.cash if item.currency is Currency.CNY)


def test_a_share_buy_changes_available_at_trade_and_settled_only_at_real_session() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    traded = apply_execution_event(state, command, _fill(command, cumulative=100, last=100, fee="5"), _rule(), None)

    cash = _cash(traded.state)
    assert (cash.settled, cash.available, cash.payable) == (
        Decimal("10000"), Decimal("8995"), Decimal("1005")
    )
    position = traded.state.positions[0]
    assert (position.quantity, position.sellable_quantity) == (100, 0)
    weekend = advance_ledger_state(traded.state, through_date=dt.date(2026, 7, 19))
    assert _cash(weekend.state) == cash
    assert weekend.state.positions[0].sellable_quantity == 0

    settled = advance_ledger_state(weekend.state, through_date=MON)
    assert (_cash(settled.state).settled, _cash(settled.state).available, _cash(settled.state).payable) == (
        Decimal("8995"), Decimal("8995"), Decimal(0)
    )
    assert settled.state.positions[0].sellable_quantity == 100


def test_hk_t_plus_two_uses_second_eligible_session_not_natural_days() -> None:
    state = build_ledger_state(
        _account(cash="0", positions=(("00700.HK", Market.HK, 100, 100, "8"),)),
        as_of_date=FRI,
    )
    command = _command("00700.HK", Market.HK, OrderSide.SELL, 100)
    rule = _rule(Market.HK, settlement_sessions=(FRI, TUE, THU))
    fx = build_fx_snapshot(
        selector="hkd_cny_v1",
        session_date=FRI,
        observed_at=NOW,
        expires_at=NOW + dt.timedelta(hours=8),
        rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.92345")),),
    )
    traded = apply_execution_event(state, command, _fill(command, cumulative=100, last=100), rule, fx)
    receivable = _cash(traded.state).receivable
    assert receivable == Decimal("923.45")
    assert {item.due_session for item in traded.state.pending} == {THU}
    before_due = advance_ledger_state(traded.state, through_date=WED)
    assert _cash(before_due.state).settled == 0
    settled = advance_ledger_state(before_due.state, through_date=THU)
    assert (_cash(settled.state).settled, _cash(settled.state).available) == (
        receivable, receivable
    )


def test_sell_credit_finances_buy_once_and_settlement_does_not_double_debit() -> None:
    state = build_ledger_state(
        _account(cash="0", positions=(("600000.SH", Market.SH, 100, 100, "8"),)),
        as_of_date=FRI,
    )
    sell = _command("600000.SH", Market.SH, OrderSide.SELL, 100)
    sold = apply_execution_event(state, sell, _fill(sell, cumulative=100, last=100), _rule(), None)
    assert (_cash(sold.state).settled, _cash(sold.state).available, _cash(sold.state).receivable) == (
        Decimal(0), Decimal(0), Decimal("1000")
    )
    assert sold.state.trading_credits[0].remaining_amount == Decimal("1000")

    buy = _command("600001.SH", Market.SH, OrderSide.BUY, 80)
    bought = apply_execution_event(sold.state, buy, _fill(buy, cumulative=80, last=80), _rule(), None)
    assert _cash(bought.state).available == 0
    assert _cash(bought.state).payable == Decimal("800")
    assert bought.state.trading_credits[0].remaining_amount == Decimal("200")

    with pytest.raises(LedgerError, match="^LEDGER_CASH_INSUFFICIENT$"):
        extra = _command("600002.SH", Market.SH, OrderSide.BUY, 30)
        apply_execution_event(bought.state, extra, _fill(extra, cumulative=30, last=30), _rule(), None)

    settled = advance_ledger_state(bought.state, through_date=MON)
    cash = _cash(settled.state)
    assert (cash.settled, cash.available, cash.receivable, cash.payable) == (
        Decimal("200"), Decimal("200"), Decimal(0), Decimal(0)
    )
    assert settled.state.trading_credits == ()
    kinds = [item.kind for item in settled.entries]
    assert kinds.index("SETTLE_SELL_CASH") < kinds.index("SETTLE_BUY_CASH")


def test_non_reusable_sell_receivable_becomes_available_only_when_settled() -> None:
    state = build_ledger_state(
        _account(cash="0", positions=(("600000.SH", Market.SH, 100, 100, "8"),)),
        as_of_date=FRI,
    )
    sell = _command("600000.SH", Market.SH, OrderSide.SELL, 100)
    traded = apply_execution_event(
        state, sell, _fill(sell, cumulative=100, last=100), _rule(reuse=False), None
    )
    assert traded.state.trading_credits == ()
    assert (_cash(traded.state).settled, _cash(traded.state).available) == (0, 0)
    settled = advance_ledger_state(traded.state, through_date=MON)
    assert (_cash(settled.state).settled, _cash(settled.state).available) == (
        Decimal("1000"),
        Decimal("1000"),
    )


def test_duplicate_fill_is_noop_and_partial_gap_or_forgery_fails_closed() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    first = _fill(command, cumulative=40, last=40)
    applied = apply_execution_event(state, command, first, _rule(), None)
    replay = apply_execution_event(applied.state, command, first, _rule(), None)
    assert replay.no_op and replay.state == applied.state
    with pytest.raises(LedgerError, match="^LEDGER_EVENT_PROJECTION_CONFLICT$"):
        apply_execution_event(
            applied.state,
            command,
            first,
            _rule(selector="sh_settlement_drifted"),
            None,
        )

    object.__setattr__(first, "last_price", Decimal("11"))
    with pytest.raises(LedgerError, match="^LEDGER_IDENTITY_INVALID$") as duplicate_error:
        apply_execution_event(applied.state, command, first, _rule(), None)
    assert (
        duplicate_error.value.__cause__ is None
        and duplicate_error.value.__context__ is None
    )

    gap = _fill(command, cumulative=100, last=50)
    with pytest.raises(LedgerError, match="^LEDGER_EVENT_SEQUENCE_INVALID$"):
        apply_execution_event(applied.state, command, gap, _rule(), None)

    forged = _fill(command, cumulative=100, last=60)
    object.__setattr__(forged, "last_price", Decimal("11"))
    with pytest.raises(LedgerError, match="^LEDGER_IDENTITY_INVALID$") as error:
        apply_execution_event(applied.state, command, forged, _rule(), None)
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_command_projection_rejects_broker_time_and_rule_drift() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    rule = _rule()
    first = _fill(
        command,
        cumulative=40,
        last=40,
        at=NOW + dt.timedelta(hours=2),
    )
    applied = apply_execution_event(state, command, first, rule, None)
    projection = applied.state.command_projections[0]
    assert (
        projection.command_id,
        projection.cumulative_quantity,
        projection.broker_order_id,
        projection.last_event_at,
        projection.settlement_rule_id,
    ) == (command.command_id, 40, "paper-1", first.occurred_at, rule.rule_id)

    candidates = (
        (
            _fill(
                command,
                cumulative=60,
                last=20,
                at=NOW + dt.timedelta(hours=3),
                broker="foreign-order",
            ),
            rule,
        ),
        (
            _fill(
                command,
                cumulative=60,
                last=20,
                at=NOW + dt.timedelta(hours=1),
            ),
            rule,
        ),
        (
            _fill(
                command,
                cumulative=60,
                last=20,
                at=NOW + dt.timedelta(hours=3),
            ),
            _rule(selector="sh_settlement_drifted"),
        ),
    )
    for event, candidate_rule in candidates:
        with pytest.raises(
            LedgerError, match="^LEDGER_EVENT_PROJECTION_CONFLICT$"
        ):
            apply_execution_event(
                applied.state, command, event, candidate_rule, None
            )


def test_command_projection_binds_first_known_broker_order_id() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    rule = _rule()
    accepted_without_broker = build_execution_event(
        command=command,
        broker_order_id=None,
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=NOW + dt.timedelta(minutes=1),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    accepted = apply_execution_event(
        state, command, accepted_without_broker, rule, None
    )
    assert accepted.state.command_projections[0].broker_order_id is None

    fill_with_broker = _fill(
        command,
        cumulative=100,
        last=100,
        at=NOW + dt.timedelta(hours=1),
        broker="bound-order",
    )
    bound = apply_execution_event(
        accepted.state, command, fill_with_broker, rule, None
    )
    assert bound.state.command_projections[0].broker_order_id == "bound-order"


def test_command_projection_retains_bound_broker_when_event_omits_it() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    rule = _rule()
    first = _fill(
        command,
        cumulative=40,
        last=40,
        at=NOW + dt.timedelta(hours=1),
        broker="bound-order",
    )
    partial = apply_execution_event(state, command, first, rule, None)
    final_without_broker = _fill(
        command,
        cumulative=100,
        last=60,
        at=NOW + dt.timedelta(hours=2),
        broker=None,
    )
    filled = apply_execution_event(
        partial.state, command, final_without_broker, rule, None
    )
    projection = filled.state.command_projections[0]
    assert projection.cumulative_quantity == 100
    assert projection.broker_order_id == "bound-order"


@pytest.mark.parametrize(
    "zero_offset_tz",
    (
        dt.timezone(dt.timedelta(0), name="FIXED_UTC"),
        _NamedUtc(),
    ),
)
def test_command_projection_accepts_and_normalizes_zero_offset_utc(
    zero_offset_tz: dt.tzinfo,
) -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    event = _fill(
        command,
        cumulative=100,
        last=100,
        at=NOW.replace(tzinfo=zero_offset_tz),
    )
    applied = apply_execution_event(state, command, event, _rule(), None)
    projected = applied.state.command_projections[0].last_event_at
    assert projected == event.occurred_at
    assert projected.tzinfo is dt.UTC


def test_command_projection_rejects_hostile_tzinfo_without_leaking_context() -> None:
    hostile = dt.datetime(2026, 7, 17, 2, tzinfo=_HostileTz())
    with pytest.raises(LedgerError, match="^LEDGER_INPUT_INVALID$") as error:
        CommandProjection(
            command_id="a" * 64,
            cumulative_quantity=0,
            broker_order_id=None,
            last_event_at=hostile,
            settlement_rule_id="b" * 64,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_ledger_state_uses_utc_snapshot_date_as_backdating_floor() -> None:
    account = _account()
    assert account.as_of.tzinfo is dt.UTC
    with pytest.raises(LedgerError, match="^LEDGER_BACKDATED$"):
        build_ledger_state(account, as_of_date=FRI - dt.timedelta(days=1))
    assert build_ledger_state(account, as_of_date=FRI).as_of_date == NOW.date()


def test_missing_calendar_tail_and_shadow_fill_fail_before_mutation() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    hk_rule = _rule(Market.HK, settlement_sessions=(FRI, TUE))
    command = _command("00700.HK", Market.HK, OrderSide.BUY, 100)
    fx = build_fx_snapshot(
        selector="hkd_cny_v1", session_date=FRI, observed_at=NOW,
        expires_at=NOW + dt.timedelta(hours=8),
        rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.92345")),),
    )
    with pytest.raises(LedgerError, match="^LEDGER_CALENDAR_INCOMPLETE$"):
        apply_execution_event(state, command, _fill(command, cumulative=100, last=100), hk_rule, fx)
    shadow = _command("600000.SH", Market.SH, OrderSide.BUY, 100, mode=ExecutionMode.SHADOW)
    with pytest.raises(LedgerError, match="^LEDGER_SHADOW_MUTATION_FORBIDDEN$"):
        apply_execution_event(state, shadow, _fill(shadow, cumulative=100, last=100), _rule(), None)

    valid_hk_rule = _rule(Market.HK)
    expired = build_fx_snapshot(
        selector="hkd_cny_expired_v1",
        session_date=FRI,
        observed_at=NOW,
        expires_at=NOW + dt.timedelta(minutes=30),
        rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.92345")),),
    )
    with pytest.raises(LedgerError, match="^FX_SNAPSHOT_EXPIRED$") as error:
        apply_execution_event(
            state,
            command,
            _fill(command, cumulative=100, last=100),
            valid_hk_rule,
            expired,
        )
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_non_fill_is_identity_tracked_without_economic_change() -> None:
    state = build_ledger_state(_account(), as_of_date=FRI)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    accepted = build_execution_event(
        command=command,
        broker_order_id="paper-accepted",
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=NOW + dt.timedelta(minutes=1),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    result = apply_execution_event(state, command, accepted, _rule(), None)
    assert result.state.cash == state.cash and result.state.positions == state.positions
    assert accepted.event_id in result.state.applied_event_ids
    assert result.entries[-1].kind == "NON_ECONOMIC_EVENT"


def test_late_fill_keeps_current_as_of_and_matures_original_trade_session_due() -> None:
    opened = build_ledger_state(_account(), as_of_date=FRI)
    current = advance_ledger_state(opened, through_date=WED).state
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    late = apply_execution_event(
        current,
        command,
        _fill(command, cumulative=100, last=100, fee="5"),
        _rule(),
        None,
    )
    assert late.state.as_of_date == WED
    assert late.state.pending == ()
    assert (late.state.positions[0].quantity, late.state.positions[0].sellable_quantity) == (
        100,
        100,
    )
    assert (_cash(late.state).settled, _cash(late.state).available, _cash(late.state).payable) == (
        Decimal("8995"),
        Decimal("8995"),
        Decimal(0),
    )
    assert any(
        entry.kind == "TRADE_BUY" and entry.effective_date == FRI
        for entry in late.entries
    )
    assert any(
        entry.kind == "SETTLE_BUY_CASH" and entry.effective_date == MON
        for entry in late.entries
    )


def _entitlement() -> EntitlementPosition:
    return EntitlementPosition(
        event_id="9" * 64,
        symbol="600000.SH",
        record_date=FRI,
        ex_date=MON,
        pay_date=TUE,
        stock_list_date=MON,
        cash_settlement_session=TUE,
        stock_settlement_session=MON,
        record_quantity=100,
        cash_per_share_gross=Decimal("0.01005"),
        stock_ratio=Decimal("0.1"),
        cash_entitlement_gross=Decimal("1.00500"),
        stock_entitlement=10,
        cash_state=EntitlementLegState.CAPTURED,
        stock_state=EntitlementLegState.CAPTURED,
    )


def test_company_action_reuses_g7c_states_and_explains_rounding() -> None:
    state = build_ledger_state(_account(cash="0"), as_of_date=FRI)
    captured_position = _entitlement()
    capture = build_capture_entitlement_transition(date=FRI, before=(), after=(captured_position,))
    captured = apply_corporate_action(state, capture)
    assert captured.state.entitlements == (captured_position,)
    assert apply_corporate_action(captured.state, capture).no_op

    recognized_action = recognize_ex_date_entitlements(date=MON, positions=(captured_position,))
    wrong_date = replace(
        recognized_action,
        postings=(replace(recognized_action.postings[0], date=TUE), *recognized_action.postings[1:]),
    )
    with pytest.raises(LedgerError, match="^LEDGER_ACTION_CONFLICT$"):
        apply_corporate_action(captured.state, wrong_date)
    recognized = apply_corporate_action(captured.state, recognized_action)
    assert _cash(recognized.state).receivable == Decimal("1.00500")
    stock_action = settle_due_entitlements(date=MON, positions=recognized_action.positions)
    stock = apply_corporate_action(recognized.state, stock_action)
    assert (stock.state.positions[0].quantity, stock.state.positions[0].sellable_quantity) == (10, 10)

    cash_action = settle_due_entitlements(date=TUE, positions=stock_action.positions)
    settled = apply_corporate_action(stock.state, cash_action)
    cash = _cash(settled.state)
    assert (cash.settled, cash.available, cash.receivable) == (
        Decimal("1.01"), Decimal("1.01"), Decimal(0)
    )
    rounding = next(item for item in settled.entries if item.kind == "CORPORATE_CASH_SETTLE")
    assert rounding.rounding_delta == Decimal("0.00500")


def test_identities_are_frozen_and_rule_binds_exact_session_order() -> None:
    rule = _rule()
    with pytest.raises(FrozenInstanceError):
        rule.selector = "other"  # type: ignore[misc]
    changed = _rule(settlement_sessions=(FRI, MON, TUE, WED))
    assert changed.rule_id != rule.rule_id
    forged = _rule()
    object.__setattr__(forged, "rule_id", "f" * 64)
    command = _command("600000.SH", Market.SH, OrderSide.BUY, 100)
    with pytest.raises(LedgerError, match="^LEDGER_IDENTITY_INVALID$"):
        apply_execution_event(
            build_ledger_state(_account(), as_of_date=FRI),
            command,
            _fill(command, cumulative=100, last=100),
            forged,
            None,
        )
