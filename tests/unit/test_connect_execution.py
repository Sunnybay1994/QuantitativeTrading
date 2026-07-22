"""M4-B2 / P0B2 HK Connect pure in-memory rule evaluation tests."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, Inexact, Overflow, Rounded, localcontext
from enum import Enum

import pytest

from quant.backtest.connect_execution import (
    ConnectRuleConfig,
    ConnectRuleInputError,
    build_connect_rule_config,
    evaluate_connect_intent,
)
from quant.domain.enums import ConnectRoute, Currency, ExecutionRejectReason, Market, OrderSide
from quant.execution.contracts import (
    VerifiedConnectMarketContext,
    build_money_amount,
    build_order_intent,
    build_position_balance,
    build_rule_decision_identity,
    build_symbol_market_state,
    build_verified_connect_market_context,
)

UTC = dt.timezone.utc
SESSION = dt.date(2026, 7, 16)
SYMBOL = "00700.HK"
SELECTOR = "hk_connect_rules_v1"
ROUTE = ConnectRoute.SH_CONNECT


def _hex64(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _utc(hour: int = 2) -> dt.datetime:
    return dt.datetime(2026, 7, 16, hour, 0, 0, tzinfo=UTC)


def _intent(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 100,
    limit_price: Decimal = Decimal("100.00"),
    session_date: dt.date = SESSION,
    market: Market = Market.HK,
    quote_currency: Currency = Currency.HKD,
    symbol: str = SYMBOL,
    connect_route: ConnectRoute | None = ROUTE,
    generated_at: dt.datetime | None = None,
):
    return build_order_intent(
        plan_id=_hex64("plan"),
        symbol=symbol,
        market=market,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        quote_currency=quote_currency,
        session_date=session_date,
        generated_at=generated_at or _utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=connect_route,
    )


def _state(
    *,
    board_lot: int = 100,
    tick_size: Decimal = Decimal("0.20"),
    limit_up: Decimal | None = Decimal("110.00"),
    limit_down: Decimal | None = Decimal("90.00"),
    suspended: bool = False,
    rule_version: str = SELECTOR,
    session_date: dt.date = SESSION,
    symbol: str = SYMBOL,
    market: Market = Market.HK,
    quote_currency: Currency = Currency.HKD,
    reference_price: Decimal = Decimal("100.00"),
):
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=session_date,
        quote_currency=quote_currency,
        reference_price=reference_price,
        limit_up=limit_up,
        limit_down=limit_down,
        suspended=suspended,
        board_lot=board_lot,
        tick_size=tick_size,
        rule_version=rule_version,
    )


def _position(
    *,
    quantity: int = 150,
    sellable_quantity: int = 150,
    symbol: str = SYMBOL,
    market: Market = Market.HK,
):
    return build_position_balance(
        symbol=symbol,
        market=market,
        quantity=quantity,
        sellable_quantity=sellable_quantity,
        avg_cost=build_money_amount(Currency.HKD, Decimal("80")),
    )


def _context(
    *,
    mainland_open: bool = True,
    hong_kong_open: bool = True,
    buy_quota_available: bool = True,
    session_date: dt.date = SESSION,
    route: ConnectRoute = ROUTE,
    as_of: dt.datetime | None = None,
    calendar_identity: str | None = None,
    quota_identity: str | None = None,
    source_identity: str | None = None,
) -> VerifiedConnectMarketContext:
    return build_verified_connect_market_context(
        route=route,
        session_date=session_date,
        as_of=as_of or _utc(),
        mainland_open=mainland_open,
        hong_kong_open=hong_kong_open,
        buy_quota_available=buy_quota_available,
        calendar_identity=calendar_identity or _hex64("cal"),
        quota_identity=quota_identity or _hex64("quota"),
        source_identity=source_identity or _hex64("src"),
    )


def _config(
    *,
    selector: str = SELECTOR,
    route: ConnectRoute = ROUTE,
    effective_from: dt.date = dt.date(2026, 1, 1),
    effective_to: dt.date | None = dt.date(2026, 12, 31),
):
    return build_connect_rule_config(
        selector=selector,
        route=route,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _assert_reject(decision, code: ExecutionRejectReason) -> None:
    assert decision.accepted is False
    assert decision.code == code.value
    assert decision.normalized_quantity == 0
    assert decision.normalized_limit_price == Decimal("0")
    assert decision.rule_version == SELECTOR


def _assert_stable_input_error(exc: BaseException) -> None:
    assert type(exc) is ConnectRuleInputError
    assert str(exc) == "CONNECT_RULE_INPUT_INVALID"
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert "00700" not in repr(exc)
    assert "/" not in str(exc)


def test_accept_buy_board_lot_and_sell_board_lot() -> None:
    buy = evaluate_connect_intent(
        _intent(side=OrderSide.BUY, quantity=200),
        _state(board_lot=100),
        None,
        _context(),
        _config(),
    )
    assert buy.accepted is True
    assert buy.code == "ACCEPTED"
    assert buy.normalized_quantity == 200
    assert buy.normalized_limit_price == Decimal("100.00")

    sell = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=200),
        _state(board_lot=100),
        _position(quantity=200, sellable_quantity=200),
        _context(),
        _config(),
    )
    assert sell.accepted is True
    assert sell.normalized_quantity == 200


def test_accept_sell_pure_odd_lot_and_t0_same_day_sellable() -> None:
    odd = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=37),
        _state(board_lot=100),
        _position(quantity=37, sellable_quantity=37),
        _context(),
        _config(),
    )
    assert odd.accepted is True
    assert odd.normalized_quantity == 37

    # Newly acquired sellable on the same session (HK T+0); no settle-date check.
    t0 = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=100),
        _state(),
        _position(quantity=100, sellable_quantity=100),
        _context(),
        _config(),
    )
    assert t0.accepted is True


def test_calendar_closed_variants() -> None:
    cases = (
        _context(mainland_open=True, hong_kong_open=False),
        _context(mainland_open=False, hong_kong_open=True),
        _context(mainland_open=False, hong_kong_open=False),
    )
    for context in cases:
        decision = evaluate_connect_intent(
            _intent(),
            _state(),
            None,
            context,
            _config(),
        )
        _assert_reject(decision, ExecutionRejectReason.CONNECT_CALENDAR_CLOSED)

    # Caller-reported connect_open must not exist on context SSOT.
    assert not hasattr(_context(), "connect_open")


def test_quota_blocks_buy_only() -> None:
    buy = evaluate_connect_intent(
        _intent(side=OrderSide.BUY),
        _state(),
        None,
        _context(buy_quota_available=False),
        _config(),
    )
    _assert_reject(buy, ExecutionRejectReason.CONNECT_BUY_QUOTA_UNAVAILABLE)

    sell = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=100),
        _state(),
        _position(quantity=100, sellable_quantity=100),
        _context(buy_quota_available=False),
        _config(),
    )
    assert sell.accepted is True


def test_board_lot_variants() -> None:
    lot200 = evaluate_connect_intent(
        _intent(side=OrderSide.BUY, quantity=200),
        _state(board_lot=200),
        None,
        _context(),
        _config(),
    )
    assert lot200.accepted is True

    buy_odd = evaluate_connect_intent(
        _intent(side=OrderSide.BUY, quantity=50),
        _state(board_lot=100),
        None,
        _context(),
        _config(),
    )
    _assert_reject(buy_odd, ExecutionRejectReason.CONNECT_BUY_BOARD_LOT_REQUIRED)

    mixed = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=150),
        _state(board_lot=100),
        _position(quantity=150, sellable_quantity=150),
        _context(),
        _config(),
    )
    _assert_reject(mixed, ExecutionRejectReason.CONNECT_SELL_MIXED_LOT)


def test_price_tick_and_band() -> None:
    ok_tick = evaluate_connect_intent(
        _intent(limit_price=Decimal("100.00")),
        _state(tick_size=Decimal("0.20")),
        None,
        _context(),
        _config(),
    )
    assert ok_tick.accepted is True

    bad_tick = evaluate_connect_intent(
        _intent(limit_price=Decimal("100.10")),
        _state(tick_size=Decimal("0.20")),
        None,
        _context(),
        _config(),
    )
    _assert_reject(bad_tick, ExecutionRejectReason.PRICE_TICK_INVALID)

    at_up = evaluate_connect_intent(
        _intent(limit_price=Decimal("110.00")),
        _state(limit_up=Decimal("110.00"), limit_down=Decimal("90.00")),
        None,
        _context(),
        _config(),
    )
    assert at_up.accepted is True

    at_down = evaluate_connect_intent(
        _intent(limit_price=Decimal("90.00")),
        _state(limit_up=Decimal("110.00"), limit_down=Decimal("90.00")),
        None,
        _context(),
        _config(),
    )
    assert at_down.accepted is True

    over = evaluate_connect_intent(
        _intent(limit_price=Decimal("110.20")),
        _state(limit_up=Decimal("110.00"), limit_down=Decimal("90.00")),
        None,
        _context(),
        _config(),
    )
    _assert_reject(over, ExecutionRejectReason.PRICE_OUT_OF_RANGE)

    missing_up = evaluate_connect_intent(
        _intent(),
        _state(limit_up=None, limit_down=Decimal("90.00")),
        None,
        _context(),
        _config(),
    )
    _assert_reject(missing_up, ExecutionRejectReason.PRICE_BAND_MISSING)

    missing_down = evaluate_connect_intent(
        _intent(),
        _state(limit_up=Decimal("110.00"), limit_down=None),
        None,
        _context(),
        _config(),
    )
    _assert_reject(missing_down, ExecutionRejectReason.PRICE_BAND_MISSING)


def test_suspended_and_rule_window_and_version() -> None:
    suspended = evaluate_connect_intent(
        _intent(),
        _state(suspended=True),
        None,
        _context(),
        _config(),
    )
    _assert_reject(suspended, ExecutionRejectReason.SUSPENDED)

    on_from = evaluate_connect_intent(
        _intent(session_date=dt.date(2026, 1, 1)),
        _state(session_date=dt.date(2026, 1, 1)),
        None,
        _context(session_date=dt.date(2026, 1, 1)),
        _config(effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 12, 31)),
    )
    assert on_from.accepted is True

    on_to = evaluate_connect_intent(
        _intent(session_date=dt.date(2026, 12, 31)),
        _state(session_date=dt.date(2026, 12, 31)),
        None,
        _context(session_date=dt.date(2026, 12, 31)),
        _config(effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 12, 31)),
    )
    assert on_to.accepted is True

    expired = evaluate_connect_intent(
        _intent(session_date=dt.date(2027, 1, 1)),
        _state(session_date=dt.date(2027, 1, 1)),
        None,
        _context(session_date=dt.date(2027, 1, 1)),
        _config(effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 12, 31)),
    )
    _assert_reject(expired, ExecutionRejectReason.RULE_NOT_EFFECTIVE)

    mismatch = evaluate_connect_intent(
        _intent(),
        _state(rule_version="other_selector"),
        None,
        _context(),
        _config(),
    )
    _assert_reject(mismatch, ExecutionRejectReason.RULE_VERSION_MISMATCH)


def test_association_mismatches_are_typed_input_errors() -> None:
    with pytest.raises(ConnectRuleInputError) as exc_route:
        evaluate_connect_intent(
            _intent(connect_route=ConnectRoute.SH_CONNECT),
            _state(),
            None,
            _context(route=ConnectRoute.SH_CONNECT),
            _config(route=ConnectRoute.SZ_CONNECT),
        )
    _assert_stable_input_error(exc_route.value)

    with pytest.raises(ConnectRuleInputError) as exc_date:
        evaluate_connect_intent(
            _intent(session_date=SESSION),
            _state(session_date=SESSION),
            None,
            _context(session_date=dt.date(2026, 7, 17)),
            _config(),
        )
    _assert_stable_input_error(exc_date.value)

    with pytest.raises(ConnectRuleInputError) as exc_symbol:
        evaluate_connect_intent(
            _intent(symbol=SYMBOL),
            _state(symbol="00981.HK"),
            None,
            _context(),
            _config(),
        )
    _assert_stable_input_error(exc_symbol.value)

    with pytest.raises(ConnectRuleInputError) as exc_pos:
        evaluate_connect_intent(
            _intent(side=OrderSide.SELL, quantity=100),
            _state(),
            _position(symbol="00981.HK"),
            _context(),
            _config(),
        )
    _assert_stable_input_error(exc_pos.value)

    sh_intent = build_order_intent(
        plan_id=_hex64("plan-sh"),
        symbol="600000.SH",
        market=Market.SH,
        side=OrderSide.BUY,
        quantity=100,
        limit_price=Decimal("10.00"),
        quote_currency=Currency.CNY,
        session_date=SESSION,
        generated_at=_utc(),
        target_identity=_hex64("target"),
        market_snapshot_id=_hex64("mkt"),
        account_snapshot_id=_hex64("acct"),
        config_identity=_hex64("cfg"),
        connect_route=None,
    )
    sh_state = build_symbol_market_state(
        symbol="600000.SH",
        market=Market.SH,
        session_date=SESSION,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10.00"),
        limit_up=Decimal("11.00"),
        limit_down=Decimal("9.00"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version=SELECTOR,
    )
    with pytest.raises(ConnectRuleInputError) as exc_mkt:
        evaluate_connect_intent(sh_intent, sh_state, None, _context(), _config())
    _assert_stable_input_error(exc_mkt.value)


def test_p0b2_route_triple_must_agree() -> None:
    """context/config/intent routes must agree exactly; no OR / AUTO."""
    with pytest.raises(ConnectRuleInputError) as exc_ctx_cfg:
        evaluate_connect_intent(
            _intent(connect_route=ConnectRoute.SH_CONNECT),
            _state(),
            None,
            _context(route=ConnectRoute.SZ_CONNECT),
            _config(route=ConnectRoute.SZ_CONNECT),
        )
    _assert_stable_input_error(exc_ctx_cfg.value)

    with pytest.raises(ConnectRuleInputError) as exc_intent_cfg:
        evaluate_connect_intent(
            _intent(connect_route=ConnectRoute.SZ_CONNECT),
            _state(),
            None,
            _context(route=ConnectRoute.SH_CONNECT),
            _config(route=ConnectRoute.SH_CONNECT),
        )
    _assert_stable_input_error(exc_intent_cfg.value)


def test_p0b2_exact_route_no_aggregate() -> None:
    """Same symbol two routes: only the intent-selected route is consumed."""
    sh_open = _context(route=ConnectRoute.SH_CONNECT, mainland_open=True, hong_kong_open=True)
    sz_closed = _context(
        route=ConnectRoute.SZ_CONNECT,
        mainland_open=True,
        hong_kong_open=False,
    )

    accepted = evaluate_connect_intent(
        _intent(connect_route=ConnectRoute.SH_CONNECT),
        _state(),
        None,
        sh_open,
        _config(route=ConnectRoute.SH_CONNECT),
    )
    assert accepted.accepted is True

    # Passing the closed SZ context with SH intent fails closed (no pick-first / OR).
    with pytest.raises(ConnectRuleInputError) as exc_mismatch:
        evaluate_connect_intent(
            _intent(connect_route=ConnectRoute.SH_CONNECT),
            _state(),
            None,
            sz_closed,
            _config(route=ConnectRoute.SH_CONNECT),
        )
    _assert_stable_input_error(exc_mismatch.value)

    closed = evaluate_connect_intent(
        _intent(connect_route=ConnectRoute.SZ_CONNECT),
        _state(),
        None,
        sz_closed,
        _config(route=ConnectRoute.SZ_CONNECT),
    )
    _assert_reject(closed, ExecutionRejectReason.CONNECT_CALENDAR_CLOSED)


def test_p0b2_future_as_of_rejected() -> None:
    future = _utc(hour=5)
    with pytest.raises(ConnectRuleInputError) as exc:
        evaluate_connect_intent(
            _intent(generated_at=_utc(hour=2)),
            _state(),
            None,
            _context(as_of=future),
            _config(),
        )
    _assert_stable_input_error(exc.value)

    # Equal as_of / generated_at is allowed.
    ok = evaluate_connect_intent(
        _intent(generated_at=_utc(hour=2)),
        _state(),
        None,
        _context(as_of=_utc(hour=2)),
        _config(),
    )
    assert ok.accepted is True


def test_forged_context_and_rule_identity_rejected() -> None:
    with pytest.raises(Exception):
        VerifiedConnectMarketContext(
            context_id="0" * 64,
            route=ROUTE,
            session_date=SESSION,
            as_of=_utc(),
            mainland_open=True,
            hong_kong_open=True,
            buy_quota_available=True,
            calendar_identity=_hex64("cal"),
            quota_identity=_hex64("quota"),
            source_identity=_hex64("src"),
        )

    with pytest.raises(ConnectRuleInputError):
        ConnectRuleConfig(
            rule_identity="a" * 64,
            selector=SELECTOR,
            route=ROUTE,
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )

    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector="../evil",
            route=ROUTE,
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )

    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector="http://example.com/x",
            route=ROUTE,
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )

    # Bare string / wrong enum rejected at config builder.
    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector=SELECTOR,
            route="SH_CONNECT",  # type: ignore[arg-type]
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )
    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector=SELECTOR,
            route="HK_CONNECT",  # type: ignore[arg-type]
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )

    class FakeRoute(str, Enum):
        SH_CONNECT = "SH_CONNECT"

    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector=SELECTOR,
            route=FakeRoute.SH_CONNECT,  # type: ignore[arg-type]
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )


def test_setattr_tamper_intent_state_position_context_config() -> None:
    intent = _intent(side=OrderSide.BUY, quantity=100)
    state = _state()
    context = _context()
    config = _config()

    object.__setattr__(intent, "quantity", 999)
    with pytest.raises(ConnectRuleInputError) as exc_intent:
        evaluate_connect_intent(intent, state, None, context, config)
    _assert_stable_input_error(exc_intent.value)

    intent2 = _intent()
    state2 = _state()
    object.__setattr__(state2, "board_lot", 0)
    with pytest.raises(ConnectRuleInputError) as exc_state:
        evaluate_connect_intent(intent2, state2, None, _context(), _config())
    _assert_stable_input_error(exc_state.value)

    intent3 = _intent(side=OrderSide.SELL, quantity=50)
    pos = _position(quantity=100, sellable_quantity=100)
    object.__setattr__(pos, "sellable_quantity", -1)
    with pytest.raises(ConnectRuleInputError) as exc_pos:
        evaluate_connect_intent(intent3, _state(), pos, _context(), _config())
    _assert_stable_input_error(exc_pos.value)

    ctx = _context()
    object.__setattr__(ctx, "session_date", dt.date(2026, 8, 1))
    with pytest.raises(ConnectRuleInputError) as exc_ctx:
        evaluate_connect_intent(_intent(), _state(), None, ctx, _config())
    _assert_stable_input_error(exc_ctx.value)

    ctx2 = _context()
    object.__setattr__(ctx2, "buy_quota_available", False)
    with pytest.raises(ConnectRuleInputError) as exc_quota:
        evaluate_connect_intent(_intent(), _state(), None, ctx2, _config())
    _assert_stable_input_error(exc_quota.value)

    cfg = _config()
    object.__setattr__(cfg, "selector", "tampered_selector")
    with pytest.raises(ConnectRuleInputError) as exc_cfg:
        evaluate_connect_intent(_intent(), _state(), None, _context(), cfg)
    _assert_stable_input_error(exc_cfg.value)


def test_builder_failure_maps_to_stable_desensitized_error() -> None:
    intent = _intent()
    object.__setattr__(intent, "limit_price", Decimal("NaN"))
    with pytest.raises(ConnectRuleInputError) as exc:
        evaluate_connect_intent(intent, _state(), None, _context(), _config())
    _assert_stable_input_error(exc.value)


def test_decision_and_identity_stable_across_reruns() -> None:
    intent = _intent(side=OrderSide.BUY, quantity=100, limit_price=Decimal("100.00"))
    state = _state()
    context = _context()
    config = _config()
    first = evaluate_connect_intent(intent, state, None, context, config)
    second = evaluate_connect_intent(intent, state, None, context, config)
    assert first == second
    assert build_rule_decision_identity(first) == build_rule_decision_identity(second)

    ctx_a = _context()
    ctx_b = _context()
    assert ctx_a.context_id == ctx_b.context_id
    assert ctx_a == ctx_b

    cfg_a = build_connect_rule_config(
        selector=SELECTOR,
        route=ROUTE,
        effective_from=dt.date(2026, 1, 1),
        effective_to=None,
    )
    cfg_b = build_connect_rule_config(
        selector=SELECTOR,
        route=ROUTE,
        effective_from=dt.date(2026, 1, 1),
        effective_to=None,
    )
    assert cfg_a.rule_identity == cfg_b.rule_identity
    assert cfg_a == cfg_b


def test_insufficient_sellable_without_position_or_over_qty() -> None:
    missing = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=100),
        _state(),
        None,
        _context(),
        _config(),
    )
    _assert_reject(missing, ExecutionRejectReason.INSUFFICIENT_SELLABLE)

    over = evaluate_connect_intent(
        _intent(side=OrderSide.SELL, quantity=120),
        _state(),
        _position(quantity=100, sellable_quantity=100),
        _context(),
        _config(),
    )
    _assert_reject(over, ExecutionRejectReason.INSUFFICIENT_SELLABLE)


def test_bool_int_and_datetime_rejected_on_builders() -> None:
    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector=SELECTOR,
            route=1,  # type: ignore[arg-type]
            effective_from=dt.date(2026, 1, 1),
            effective_to=None,
        )
    with pytest.raises(ConnectRuleInputError):
        build_connect_rule_config(
            selector=SELECTOR,
            route=ROUTE,
            effective_from=dt.datetime(2026, 7, 16, tzinfo=UTC),  # type: ignore[arg-type]
            effective_to=None,
        )


def test_tick_exact_divisibility_and_hostile_decimal_context() -> None:
    """P1-TICK: exact coefficient/exponent multiple; context-free; no Overflow."""
    extreme_hi = Decimal("1E+999999")
    extreme_lo = Decimal("1E-999999")

    multiple_extreme = evaluate_connect_intent(
        _intent(limit_price=extreme_hi),
        _state(
            tick_size=extreme_lo,
            limit_up=extreme_hi,
            limit_down=extreme_hi,
            reference_price=extreme_hi,
        ),
        None,
        _context(),
        _config(),
    )
    assert multiple_extreme.accepted is True
    assert multiple_extreme.code == "ACCEPTED"

    not_multiple_extreme = evaluate_connect_intent(
        _intent(limit_price=extreme_lo),
        _state(
            tick_size=extreme_hi,
            limit_up=extreme_lo,
            limit_down=extreme_lo,
            reference_price=extreme_lo,
        ),
        None,
        _context(),
        _config(),
    )
    _assert_reject(not_multiple_extreme, ExecutionRejectReason.PRICE_TICK_INVALID)

    multiple_030 = evaluate_connect_intent(
        _intent(limit_price=Decimal("0.30")),
        _state(
            tick_size=Decimal("0.05"),
            limit_up=Decimal("0.40"),
            limit_down=Decimal("0.20"),
            reference_price=Decimal("0.30"),
        ),
        None,
        _context(),
        _config(),
    )
    assert multiple_030.accepted is True

    not_multiple_03 = evaluate_connect_intent(
        _intent(limit_price=Decimal("0.3")),
        _state(
            tick_size=Decimal("0.2"),
            limit_up=Decimal("1.0"),
            limit_down=Decimal("0.2"),
            reference_price=Decimal("0.4"),
        ),
        None,
        _context(),
        _config(),
    )
    _assert_reject(not_multiple_03, ExecutionRejectReason.PRICE_TICK_INVALID)

    not_multiple_100 = evaluate_connect_intent(
        _intent(limit_price=Decimal("1.00")),
        _state(
            tick_size=Decimal("0.03"),
            limit_up=Decimal("1.20"),
            limit_down=Decimal("0.90"),
            reference_price=Decimal("1.00"),
        ),
        None,
        _context(),
        _config(),
    )
    _assert_reject(not_multiple_100, ExecutionRejectReason.PRICE_TICK_INVALID)

    with localcontext() as ctx:
        ctx.prec = 2
        ctx.Emax = 10
        ctx.Emin = -10
        ctx.traps[Overflow] = True
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        before = (
            ctx.prec,
            ctx.Emax,
            ctx.Emin,
            dict(ctx.traps),
        )
        hostile_ok = evaluate_connect_intent(
            _intent(limit_price=Decimal("0.30")),
            _state(
                tick_size=Decimal("0.05"),
                limit_up=Decimal("0.40"),
                limit_down=Decimal("0.20"),
                reference_price=Decimal("0.30"),
            ),
            None,
            _context(),
            _config(),
        )
        hostile_bad = evaluate_connect_intent(
            _intent(limit_price=Decimal("0.3")),
            _state(
                tick_size=Decimal("0.2"),
                limit_up=Decimal("1.0"),
                limit_down=Decimal("0.2"),
                reference_price=Decimal("0.4"),
            ),
            None,
            _context(),
            _config(),
        )
        after = (
            ctx.prec,
            ctx.Emax,
            ctx.Emin,
            dict(ctx.traps),
        )
    assert hostile_ok.accepted is True
    _assert_reject(hostile_bad, ExecutionRejectReason.PRICE_TICK_INVALID)
    assert before == after
    assert before[0] == 2
    assert before[1] == 10
    assert before[2] == -10
    assert before[3][Overflow] is True
    assert before[3][Inexact] is True
    assert before[3][Rounded] is True


def test_state_has_no_buy_quota_field() -> None:
    state = _state()
    assert not hasattr(state, "buy_quota_available")
    with pytest.raises(TypeError):
        build_symbol_market_state(
            symbol=SYMBOL,
            market=Market.HK,
            session_date=SESSION,
            quote_currency=Currency.HKD,
            reference_price=Decimal("100.00"),
            limit_up=Decimal("110.00"),
            limit_down=Decimal("90.00"),
            suspended=False,
            board_lot=100,
            tick_size=Decimal("0.20"),
            buy_quota_available=True,  # type: ignore[call-arg]
            rule_version=SELECTOR,
        )
