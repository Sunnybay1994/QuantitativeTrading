from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from quant.backtest import (
    AShareRuleInputError,
    build_a_share_rule_config,
    evaluate_a_share_intent,
)
from quant.domain.enums import Currency, Market, OrderSide
from quant.execution.contracts import (
    MoneyAmount,
    OrderIntent,
    build_order_intent,
    build_position_balance,
    build_symbol_market_state,
)

_HEX = "1" * 64
_SELECTOR = "a_share_execution_rules_v1"
_DAY = dt.date(2026, 7, 20)
_NOW = dt.datetime(2026, 7, 19, 8, tzinfo=dt.UTC)


def _config(
    *, start: dt.date = dt.date(2020, 8, 24), end: dt.date | None = None
):
    return build_a_share_rule_config(
        selector=_SELECTOR, effective_from=start, effective_to=end
    )


def _intent(
    *,
    symbol: str = "600000.SH",
    market: Market = Market.SH,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 100,
    price: str = "10.00",
):
    return build_order_intent(
        plan_id=_HEX,
        symbol=symbol,
        market=market,
        side=side,
        quantity=quantity,
        limit_price=Decimal(price),
        quote_currency=Currency.CNY,
        session_date=_DAY,
        generated_at=_NOW,
        target_identity="2" * 64,
        market_snapshot_id="3" * 64,
        account_snapshot_id="4" * 64,
        config_identity="5" * 64,
        connect_route=None,
    )


def _state(
    *,
    symbol: str = "600000.SH",
    market: Market = Market.SH,
    board_lot: int = 100,
    suspended: bool = False,
    up: str | None = "11.00",
    down: str | None = "9.00",
    tick: str = "0.01",
    selector: str = _SELECTOR,
):
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=_DAY,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=None if up is None else Decimal(up),
        limit_down=None if down is None else Decimal(down),
        suspended=suspended,
        board_lot=board_lot,
        tick_size=Decimal(tick),
        rule_version=selector,
    )


def _position(
    *, symbol: str = "600000.SH", market: Market = Market.SH, quantity: int = 150,
    sellable: int = 150,
):
    return build_position_balance(
        symbol=symbol,
        market=market,
        quantity=quantity,
        sellable_quantity=sellable,
        avg_cost=MoneyAmount(Currency.CNY, Decimal("9.50")),
    )


@pytest.mark.parametrize(
    ("symbol", "market", "board_lot", "quantity"),
    [
        ("600000.SH", Market.SH, 100, 100),
        ("300001.SZ", Market.SZ, 100, 100),
        ("688001.SH", Market.SH, 200, 201),
    ],
)
def test_accepts_main_chinext_and_star_quantity_rules(
    symbol: str, market: Market, board_lot: int, quantity: int
) -> None:
    decision = evaluate_a_share_intent(
        _intent(symbol=symbol, market=market, quantity=quantity),
        _state(symbol=symbol, market=market, board_lot=board_lot),
        None,
        _config(),
    )
    assert decision.accepted
    assert decision.normalized_quantity == quantity


@pytest.mark.parametrize(
    ("symbol", "board_lot", "quantity"),
    [("600000.SH", 100, 150), ("688001.SH", 200, 150)],
)
def test_accepts_only_valid_full_odd_lot_exit(
    symbol: str, board_lot: int, quantity: int
) -> None:
    decision = evaluate_a_share_intent(
        _intent(symbol=symbol, side=OrderSide.SELL, quantity=quantity),
        _state(symbol=symbol, board_lot=board_lot),
        _position(symbol=symbol, quantity=quantity, sellable=quantity),
        _config(),
    )
    assert decision.accepted


def test_rejects_t_plus_one_and_invalid_lot() -> None:
    t1 = evaluate_a_share_intent(
        _intent(side=OrderSide.SELL), _state(), _position(sellable=0), _config()
    )
    invalid_lot = evaluate_a_share_intent(
        _intent(quantity=150), _state(), None, _config()
    )
    assert (t1.accepted, t1.code) == (False, "T_PLUS_ONE")
    assert (invalid_lot.accepted, invalid_lot.code) == (False, "LOT_CONSTRAINT")


def test_suspension_and_price_boundaries_are_fail_closed() -> None:
    suspended = evaluate_a_share_intent(
        _intent(), _state(suspended=True), None, _config()
    )
    upper = evaluate_a_share_intent(
        _intent(price="11.00"), _state(), None, _config()
    )
    lower = evaluate_a_share_intent(
        _intent(side=OrderSide.SELL, price="9.00"),
        _state(),
        _position(quantity=100, sellable=100),
        _config(),
    )
    assert suspended.code == "SUSPENDED"
    assert upper.code == "BUY_AT_UPPER_LIMIT"
    assert lower.code == "SELL_AT_LOWER_LIMIT"


def test_effective_window_is_inclusive_and_versioned() -> None:
    on_day = evaluate_a_share_intent(
        _intent(), _state(), None, _config(start=_DAY, end=_DAY)
    )
    expired = evaluate_a_share_intent(
        _intent(), _state(), None, _config(end=_DAY - dt.timedelta(days=1))
    )
    mismatch = evaluate_a_share_intent(
        _intent(), _state(selector="other_v1"), None, _config()
    )
    assert on_day.accepted
    assert expired.code == "RULE_NOT_EFFECTIVE"
    assert mismatch.code == "RULE_VERSION_MISMATCH"


def test_missing_band_bad_tick_and_outside_band_have_stable_codes() -> None:
    missing = evaluate_a_share_intent(_intent(), _state(up=None), None, _config())
    bad_tick = evaluate_a_share_intent(
        _intent(price="10.005"), _state(tick="0.01"), None, _config()
    )
    outside = evaluate_a_share_intent(
        _intent(side=OrderSide.SELL, price="11.01"),
        _state(),
        _position(quantity=100, sellable=100),
        _config(),
    )
    assert missing.code == "PRICE_BAND_MISSING"
    assert bad_tick.code == "PRICE_TICK_INVALID"
    assert outside.code == "PRICE_OUT_OF_RANGE"


def test_cross_market_and_forged_identity_raise_sanitized_input_error() -> None:
    with pytest.raises(AShareRuleInputError, match="^A_SHARE_RULE_INPUT_INVALID$"):
        evaluate_a_share_intent(
            _intent(), _state(symbol="300001.SZ", market=Market.SZ), None, _config()
        )

    forged = object.__new__(OrderIntent)
    for name in OrderIntent.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(_intent(), name))
    object.__setattr__(forged, "intent_id", "f" * 64)
    with pytest.raises(AShareRuleInputError, match="^A_SHARE_RULE_INPUT_INVALID$"):
        evaluate_a_share_intent(forged, _state(), None, _config())


def test_rule_config_rejects_hostile_selector_and_forged_identity() -> None:
    with pytest.raises(AShareRuleInputError, match="^A_SHARE_RULE_INPUT_INVALID$"):
        build_a_share_rule_config(
            selector="C:\\secret", effective_from=_DAY, effective_to=None
        )
    config = _config()
    with pytest.raises(AShareRuleInputError, match="^A_SHARE_RULE_INPUT_INVALID$"):
        type(config)("f" * 64, config.selector, config.effective_from, None)
