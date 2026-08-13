"""M4-P3 pre-trade risk: per-rule decisions, audit trail, counterexamples."""

from __future__ import annotations

import datetime as dt
import hashlib
import traceback
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
)
from quant.execution.config import load_trading_config, trading_config_identity
from quant.execution.contracts import (
    OrderIntentSpec,
    build_account_snapshot,
    build_cancel_command,
    build_cash_balance,
    build_execution_event,
    build_money_amount,
    build_order_plan,
    build_position_balance,
    build_symbol_market_state,
    build_verified_connect_market_context,
    build_verified_market_snapshot,
)
from quant.execution.oms import new_order_aggregate, reduce_order
from quant.execution.risk import (
    CancelRiskDecision,
    DailyRiskCounters,
    RiskInputError,
    evaluate_cancel_risk,
    evaluate_pretrade,
)

UTC = dt.timezone.utc
SESSION = dt.date(2026, 7, 17)
CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "trading" / "example.toml"


def _hex64(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _utc(hour: int = 2, minute: int = 0, second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 17, hour, minute, second, tzinfo=UTC)


def _write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "trading.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _base_toml(
    *,
    mode: str = "PAPER",
    manual_approval: str = "false",
    sell_only: str = "false",
    frozen: str = "[]",
    max_order_notional: str = "1000000.0",
    max_symbol_weight: str = "0.50",
    max_gross_exposure: str = "2.0",
    max_daily_notional: str = "5000000.0",
    max_orders_per_day: str = "50",
    max_cancels_per_day: str = "20",
    snapshot_max_age_seconds: str = "86400",
) -> str:
    return f"""
[meta]
schema_version = "trading-config-v1"

[execution]
mode = "{mode}"
auto_trade = false
manual_approval = {manual_approval}
sell_only = {sell_only}
frozen_symbols = {frozen}

[rules]
a_share_rule_selector = "a_share_execution_rules_v1"
hk_connect_rule_selector = "hk_connect_execution_rules_v1"
fee_schedule_selector = "a_share_research_cost_schedule_v1"
fx_schedule_selector = "cny_hkd_fx_schedule_v1"

[data]
snapshot_max_age_seconds = {snapshot_max_age_seconds}

[store]
sqlite_uri = "sqlite:///artifacts/trading/execution.db"

[[risk.limits]]
effective_from = 2016-01-01
max_order_notional = {max_order_notional}
max_symbol_weight = {max_symbol_weight}
max_gross_exposure = {max_gross_exposure}
max_daily_notional = {max_daily_notional}
max_orders_per_day = {max_orders_per_day}
max_cancels_per_day = {max_cancels_per_day}
"""


def _config(tmp_path: Path, **kwargs: str):
    return load_trading_config(_write_toml(tmp_path, _base_toml(**kwargs)))


def _market_of(symbol: str) -> Market:
    if symbol.endswith(".HK"):
        return Market.HK
    if symbol.endswith(".SZ"):
        return Market.SZ
    return Market.SH


def _connect_ctx(
    *,
    route: ConnectRoute = ConnectRoute.SH_CONNECT,
    as_of: dt.datetime | None = None,
    session_date: dt.date = SESSION,
    buy_quota_available: bool = True,
    mainland_open: bool = True,
    hong_kong_open: bool = True,
):
    return build_verified_connect_market_context(
        route=route,
        session_date=session_date,
        as_of=as_of or _utc(3),
        mainland_open=mainland_open,
        hong_kong_open=hong_kong_open,
        buy_quota_available=buy_quota_available,
        calendar_identity=_hex64("cal"),
        quota_identity=_hex64("quota"),
        source_identity=_hex64("src"),
    )


def _market(
    *,
    as_of: dt.datetime | None = None,
    symbols: tuple[str, ...] = ("600000.SH",),
    price: Decimal = Decimal("10"),
    suspended: bool = False,
    connect_contexts: tuple = (),
):
    as_of = as_of or _utc(3)
    states = []
    for symbol in symbols:
        market = _market_of(symbol)
        is_hk = market is Market.HK
        states.append(
            build_symbol_market_state(
                symbol=symbol,
                market=market,
                session_date=SESSION,
                quote_currency=Currency.HKD if is_hk else Currency.CNY,
                reference_price=price,
                limit_up=None if is_hk else price * Decimal("1.1"),
                limit_down=None if is_hk else price * Decimal("0.9"),
                suspended=suspended,
                board_lot=100,
                tick_size=Decimal("0.20") if is_hk else Decimal("0.01"),
                rule_version=(
                    "hk_connect_execution_rules_v1"
                    if is_hk
                    else "a_share_execution_rules_v1"
                ),
            )
        )
    return build_verified_market_snapshot(
        as_of=as_of,
        session_date=SESSION,
        states=tuple(states),
        connect_contexts=connect_contexts,
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )


def _account(
    *,
    cash_available: Decimal = Decimal("1000000"),
    positions: tuple = (),
    as_of: dt.datetime | None = None,
):
    cash = build_cash_balance(
        currency=Currency.CNY,
        settled=cash_available,
        available=cash_available,
        receivable=Decimal("0"),
        payable=Decimal("0"),
    )
    return build_account_snapshot(
        as_of=as_of or _utc(3),
        positions=positions,
        cash=(cash,),
    )


def _plan(
    config,
    market,
    account,
    *,
    intents: list,
):
    cfg_id = trading_config_identity(config)
    specs = []
    for item in intents:
        if len(item) == 5:
            symbol, side, qty, price, connect_route = item
        else:
            symbol, side, qty, price = item
            connect_route = None
        market_e = _market_of(symbol)
        specs.append(
            OrderIntentSpec(
                symbol=symbol,
                market=market_e,
                side=side,
                quantity=qty,
                limit_price=price,
                quote_currency=Currency.HKD if market_e is Market.HK else Currency.CNY,
                session_date=SESSION,
                generated_at=_utc(2),
                target_identity=_hex64("target"),
                market_snapshot_id=market.snapshot_id,
                account_snapshot_id=account.snapshot_id,
                config_identity=cfg_id,
                connect_route=connect_route,
            )
        )
    return build_order_plan(
        target_identity=_hex64("target"),
        market_snapshot_id=market.snapshot_id,
        account_snapshot_id=account.snapshot_id,
        config_identity=cfg_id,
        trading_config_identity=cfg_id,
        intent_specs=tuple(specs),
        rejections=(),
        residual_cash=(),
    )


def _counters(**kwargs: object) -> DailyRiskCounters:
    defaults: dict[str, object] = {
        "session_date": SESSION,
        "order_count": 0,
        "cancel_count": 0,
        "buy_notional": Decimal("0"),
    }
    defaults.update(kwargs)
    return DailyRiskCounters(**defaults)  # type: ignore[arg-type]


def _codes(decision) -> list[str]:
    return [item.code for item in decision.rule_results]


def _cancel(config):
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    risk = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    command = risk.commands[0]
    accepted = build_execution_event(
        command=command,
        broker_order_id="PAPER-1",
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=_utc(3),
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    aggregate = reduce_order(new_order_aggregate(command), command, accepted)
    return build_cancel_command(command=command, aggregate=aggregate, as_of=_utc(3))


def test_cancel_risk_uses_versioned_daily_limit_and_changes_only_cancel_count(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, max_cancels_per_day="20")
    cancel = _cancel(config)
    accepted = evaluate_cancel_risk(
        cancel,
        config,
        _counters(order_count=7, cancel_count=19, buy_notional=Decimal("123.45")),
    )
    rejected = evaluate_cancel_risk(
        cancel,
        config,
        _counters(order_count=7, cancel_count=20, buy_notional=Decimal("123.45")),
    )

    assert isinstance(accepted, CancelRiskDecision)
    assert accepted.accepted and accepted.code == "CANCEL_LIMIT_OK"
    assert accepted.projected_counters == _counters(
        order_count=7, cancel_count=20, buy_notional=Decimal("123.45")
    )
    assert not rejected.accepted and rejected.code == "CANCEL_LIMIT_EXCEEDED"
    assert rejected.projected_counters == _counters(
        order_count=7, cancel_count=20, buy_notional=Decimal("123.45")
    )
    assert accepted.policy_identity == trading_config_identity(config)


def test_cancel_risk_rejects_session_or_identity_drift_without_context(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    cancel = _cancel(config)
    object.__setattr__(cancel, "broker_order_id", "TOKEN C:\\hostile")
    with pytest.raises(RiskInputError, match="^CANCEL_RISK_INPUT_INVALID$") as info:
        evaluate_cancel_risk(cancel, config, _counters())
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert "TOKEN" not in repr(info.value)
    clean = _cancel(config)
    hostile_counters = _counters()
    object.__setattr__(hostile_counters, "cancel_count", -1)
    with pytest.raises(RiskInputError, match="^CANCEL_RISK_INPUT_INVALID$"):
        evaluate_cancel_risk(clean, config, hostile_counters)


def test_happy_path_paper_emits_commands_and_full_audit(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert decision.requires_manual_approval is False
    assert len(decision.approved_intent_ids) == 1
    assert len(decision.commands) == 1
    assert decision.commands[0].mode is ExecutionMode.PAPER
    assert decision.commands[0].intent.intent_id == decision.approved_intent_ids[0]
    assert decision.rule_results  # complete audit trail
    assert all(hasattr(item, "rule") and hasattr(item, "accepted") for item in decision.rule_results)
    assert "MASTER_SWITCH" in {item.rule for item in decision.rule_results}


def test_shadow_accepts_risk_but_never_emits_commands(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="SHADOW", manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert decision.approved_intent_ids
    assert decision.commands == ()
    assert "SHADOW_READ_ONLY" in _codes(decision)


def test_manual_approval_blocks_commands(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="true")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert decision.requires_manual_approval is True
    assert decision.approved_intent_ids
    assert decision.commands == ()
    assert "MANUAL_APPROVAL_REQUIRED" in _codes(decision)


def test_stale_snapshot_rejects_buy_allows_sell(tmp_path: Path) -> None:
    config = _config(tmp_path, snapshot_max_age_seconds="60", manual_approval="false")
    stale_as_of = _utc(3) - dt.timedelta(seconds=120)
    market = _market(
        as_of=stale_as_of,
        symbols=("600000.SH", "000001.SZ"),
    )
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,), as_of=_utc(3))
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.SELL, 100, Decimal("9")),
        ],
    )
    decision = evaluate_pretrade(
        plan,
        account,
        market,
        config,
        _counters(),
        now=_utc(3),
    )
    assert "DATA_GATE_STALE" in _codes(decision) or any(
        item.code.startswith("DATA_GATE") and not item.accepted for item in decision.rule_results
    )
    buy_ids = {i.intent_id for i in plan.intents if i.side is OrderSide.BUY}
    sell_ids = {i.intent_id for i in plan.intents if i.side is OrderSide.SELL}
    assert buy_ids.isdisjoint(set(decision.approved_intent_ids))
    assert sell_ids <= set(decision.approved_intent_ids)
    assert all(cmd.intent.side is OrderSide.SELL for cmd in decision.commands)


def test_future_market_rejects_all_intents(tmp_path: Path) -> None:
    config = _config(tmp_path, snapshot_max_age_seconds="60", manual_approval="false")
    market = _market(as_of=_utc(4), symbols=("600000.SH", "000001.SZ"))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,), as_of=_utc(3))
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.SELL, 100, Decimal("9")),
        ],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is False
    assert decision.approved_intent_ids == ()
    assert decision.commands == ()
    assert "DATA_GATE_FUTURE" in _codes(decision)
    assert "MANUAL_APPROVAL_REQUIRED" not in _codes(decision)
    assert "COMMANDS_EMITTED" not in _codes(decision)


def test_stale_account_rejects_all_intents(tmp_path: Path) -> None:
    config = _config(tmp_path, snapshot_max_age_seconds="60", manual_approval="false")
    market = _market(as_of=_utc(3))
    account = _account(as_of=_utc(1))
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is False
    assert decision.approved_intent_ids == ()
    assert decision.commands == ()
    assert "ACCOUNT_GATE_STALE" in _codes(decision)


def test_future_account_rejects_all_intents(tmp_path: Path) -> None:
    config = _config(tmp_path, snapshot_max_age_seconds="60", manual_approval="false")
    market = _market(as_of=_utc(3))
    account = _account(as_of=_utc(4))
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is False
    assert decision.approved_intent_ids == ()
    assert "ACCOUNT_GATE_FUTURE" in _codes(decision)


def test_snapshot_age_equal_max_is_accepted(tmp_path: Path) -> None:
    config = _config(tmp_path, snapshot_max_age_seconds="60", manual_approval="false")
    as_of = _utc(3) - dt.timedelta(seconds=60)
    market = _market(as_of=as_of)
    account = _account(as_of=as_of)
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert len(decision.approved_intent_ids) == 1
    assert "DATA_GATE_OK" in _codes(decision)


def test_sell_only_rejects_buy_not_sell(tmp_path: Path) -> None:
    config = _config(tmp_path, sell_only="true", manual_approval="false")
    market = _market(symbols=("600000.SH", "000001.SZ"))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.SELL, 100, Decimal("9")),
        ],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert any(item.code == "SELL_ONLY" and not item.accepted for item in decision.rule_results)
    buy_ids = {i.intent_id for i in plan.intents if i.side is OrderSide.BUY}
    sell_ids = {i.intent_id for i in plan.intents if i.side is OrderSide.SELL}
    assert buy_ids.isdisjoint(set(decision.approved_intent_ids))
    assert sell_ids <= set(decision.approved_intent_ids)
    # sell must not be rejected by buy notional/order limits
    assert not any(
        item.subject in sell_ids and item.code.startswith("MAX_") and not item.accepted
        for item in decision.rule_results
    )


def test_frozen_symbol_blocks_before_sell_only(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        sell_only="true",
        frozen='["000001.SZ"]',
        manual_approval="false",
    )
    market = _market(symbols=("000001.SZ",))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 100, Decimal("9"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    frozen_idx = next(
        i for i, item in enumerate(decision.rule_results) if item.code == "FROZEN_SYMBOL"
    )
    # frozen runs before sell-only; sell-only should not be the reject reason for this sell
    assert decision.rule_results[frozen_idx].accepted is False
    assert not any(
        item.code == "SELL_ONLY" and item.subject == plan.intents[0].intent_id
        for item in decision.rule_results
    )


def test_batch_aggregate_rejects_when_singles_would_pass(tmp_path: Path) -> None:
    # each order notional = 100*10 = 1000 < 1500; sum = 2000 > 1500 daily
    config = _config(
        tmp_path,
        max_order_notional="1500.0",
        max_daily_notional="1500.0",
        manual_approval="false",
    )
    market = _market(symbols=("600000.SH", "000001.SZ"), price=Decimal("10"))
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.BUY, 100, Decimal("10")),
        ],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert any(
        item.code == "MAX_DAILY_NOTIONAL" and not item.accepted for item in decision.rule_results
    )


def test_daily_counters_survive_restart_roundtrip(tmp_path: Path) -> None:
    config = _config(tmp_path, max_orders_per_day="5", manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    before = _counters(order_count=4, cancel_count=17, buy_notional=Decimal("500"))
    payload = before.to_persistable_dict()
    restored = DailyRiskCounters.from_persistable_dict(payload)
    assert restored.cancel_count == 17
    assert restored.order_count == 4
    assert restored.buy_notional == Decimal("500")

    decision = evaluate_pretrade(plan, account, market, config, restored, now=_utc(3))
    assert decision.accepted is True
    assert decision.projected_counters.order_count == 5
    assert decision.projected_counters.cancel_count == 17  # cancels preserved across restart

    # without persistence, a fresh zeroed counter would lose cancel history
    lost = _counters()
    assert lost.cancel_count == 0
    assert lost.cancel_count != restored.cancel_count


def test_max_orders_uses_persisted_counter(tmp_path: Path) -> None:
    config = _config(tmp_path, max_orders_per_day="5", manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(
        plan, account, market, config, _counters(order_count=5), now=_utc(3)
    )
    assert decision.approved_intent_ids == ()
    assert any(
        item.code == "MAX_ORDERS_PER_DAY" and not item.accepted for item in decision.rule_results
    )


def test_priority_master_switch_before_limits(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    # forge config identity mismatch on plan via different config
    other = _config(tmp_path, max_order_notional="999999.0", manual_approval="false")
    plan = _plan(
        other,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is False
    assert decision.commands == ()
    assert decision.approved_intent_ids == ()
    assert any(item.code == "CONFIG_IDENTITY_MISMATCH" for item in decision.rule_results)
    # limits should not run as the primary accept path after hard master failure
    assert not any(
        item.code == "MAX_ORDER_NOTIONAL" and item.accepted for item in decision.rule_results
    )


def test_buy_quota_and_suspended_block_buy_not_unrelated_sell(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    # rebuild market with per-symbol flags (A-share: no connect context / no state quota)
    states = (
        build_symbol_market_state(
            symbol="600000.SH",
            market=Market.SH,
            session_date=SESSION,
            quote_currency=Currency.CNY,
            reference_price=Decimal("10"),
            limit_up=Decimal("11"),
            limit_down=Decimal("9"),
            suspended=True,
            board_lot=100,
            tick_size=Decimal("0.01"),
            rule_version="a_share_execution_rules_v1",
        ),
        build_symbol_market_state(
            symbol="000001.SZ",
            market=Market.SZ,
            session_date=SESSION,
            quote_currency=Currency.CNY,
            reference_price=Decimal("9"),
            limit_up=Decimal("10"),
            limit_down=Decimal("8"),
            suspended=False,
            board_lot=100,
            tick_size=Decimal("0.01"),
            rule_version="a_share_execution_rules_v1",
        ),
    )
    market = build_verified_market_snapshot(
        as_of=_utc(3),
        session_date=SESSION,
        states=states,
        connect_contexts=(),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.SELL, 100, Decimal("9")),
        ],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    buy_id = next(i.intent_id for i in plan.intents if i.side is OrderSide.BUY)
    sell_id = next(i.intent_id for i in plan.intents if i.side is OrderSide.SELL)
    assert buy_id not in decision.approved_intent_ids
    assert sell_id in decision.approved_intent_ids
    assert any(item.code == "SYMBOL_SUSPENDED" and not item.accepted for item in decision.rule_results)


def test_example_config_loads_for_smoke() -> None:
    assert CONFIG_PATH.is_file()
    loaded = load_trading_config(CONFIG_PATH)
    assert loaded.document["execution"]["mode"] == "PAPER"


def test_example_config_all_cash_small_buy_passes_gross() -> None:
    """P0-A: example max_gross_exposure=1.0 must accept all-cash small first buy."""
    config = load_trading_config(CONFIG_PATH)
    market = _market(as_of=_utc(3))
    account = _account(cash_available=Decimal("1000000"), as_of=_utc(3))
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert len(decision.approved_intent_ids) == 1
    assert not any(
        item.code == "MAX_GROSS_EXPOSURE" and not item.accepted for item in decision.rule_results
    )
    # example.toml has manual_approval=true → no PAPER commands, but intents approved
    assert decision.commands == ()
    assert decision.requires_manual_approval is True


def test_cash_excluded_from_gross_numerator(tmp_path: Path) -> None:
    # max_gross=1.0; large cash must not count as exposure; small buy still ok
    config = _config(
        tmp_path,
        max_gross_exposure="1.0",
        max_symbol_weight="1.0",
        manual_approval="false",
    )
    market = _market()
    account = _account(cash_available=Decimal("5000000"))
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert decision.approved_intent_ids


def test_projected_gross_with_holdings_buy_and_sell(tmp_path: Path) -> None:
    # holdings 600000=500*10=5000, 000001=400*10=4000; gross=9000; equity=cash1000+9000=10000
    # sell 200 of 000001 → -2000; buy 100 of 600000 → +1000; projected gross=8000; ratio=0.8
    # max_gross=0.75 → reject buy, keep sell
    config = _config(
        tmp_path,
        max_gross_exposure="0.75",
        max_symbol_weight="1.0",
        manual_approval="false",
    )
    market = _market(symbols=("600000.SH", "000001.SZ"), price=Decimal("10"))
    positions = (
        build_position_balance(
            symbol="600000.SH",
            market=Market.SH,
            quantity=500,
            sellable_quantity=500,
            avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
        ),
        build_position_balance(
            symbol="000001.SZ",
            market=Market.SZ,
            quantity=400,
            sellable_quantity=400,
            avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
        ),
    )
    account = _account(cash_available=Decimal("1000"), positions=positions)
    plan = _plan(
        config,
        market,
        account,
        intents=[
            ("600000.SH", OrderSide.BUY, 100, Decimal("10")),
            ("000001.SZ", OrderSide.SELL, 200, Decimal("10")),
        ],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    buy_id = next(i.intent_id for i in plan.intents if i.side is OrderSide.BUY)
    sell_id = next(i.intent_id for i in plan.intents if i.side is OrderSide.SELL)
    assert buy_id not in decision.approved_intent_ids
    assert sell_id in decision.approved_intent_ids
    assert any(
        item.code == "MAX_GROSS_EXPOSURE" and not item.accepted for item in decision.rule_results
    )


def test_existing_holdings_buy_exceeds_gross_rejected(tmp_path: Path) -> None:
    # equity ≈ 10000 cash + 9000 pos = 19000; buy another 1000 → gross 10000; ratio>0.5
    config = _config(
        tmp_path,
        max_gross_exposure="0.50",
        max_symbol_weight="1.0",
        manual_approval="false",
    )
    market = _market(symbols=("600000.SH", "000001.SZ"), price=Decimal("10"))
    positions = (
        build_position_balance(
            symbol="600000.SH",
            market=Market.SH,
            quantity=500,
            sellable_quantity=500,
            avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
        ),
        build_position_balance(
            symbol="000001.SZ",
            market=Market.SZ,
            quantity=400,
            sellable_quantity=400,
            avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
        ),
    )
    account = _account(cash_available=Decimal("10000"), positions=positions)
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert any(
        item.code == "MAX_GROSS_EXPOSURE" and not item.accepted for item in decision.rule_results
    )


def test_non_positive_equity_rejects_buy_allows_sell(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    market = _market(symbols=("600000.SH", "000001.SZ"), price=Decimal("10"))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=100,
        sellable_quantity=100,
        avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
    )
    empty = _account(cash_available=Decimal("0"), positions=())
    buy_plan = _plan(
        config,
        market,
        empty,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    buy_decision = evaluate_pretrade(buy_plan, empty, market, config, _counters(), now=_utc(3))
    assert buy_decision.approved_intent_ids == ()
    assert any(
        item.code == "NON_POSITIVE_EQUITY" and not item.accepted
        for item in buy_decision.rule_results
    )

    sell_account = _account(cash_available=Decimal("0"), positions=(pos,))
    sell_plan = _plan(
        config,
        market,
        sell_account,
        intents=[("000001.SZ", OrderSide.SELL, 50, Decimal("10"))],
    )
    sell_decision = evaluate_pretrade(sell_plan, sell_account, market, config, _counters(), now=_utc(3))
    assert len(sell_decision.approved_intent_ids) == 1
    assert not any(
        item.code == "NON_POSITIVE_EQUITY" and not item.accepted
        for item in sell_decision.rule_results
    )


def test_sell_without_position_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("000001.SZ",))
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 100, Decimal("9"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert decision.commands == ()
    assert "SELLABLE_POSITION_MISSING" in _codes(decision)


def test_sell_exceeds_sellable_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("000001.SZ",))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=50,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 100, Decimal("9"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert decision.commands == ()
    assert "SELLABLE_EXCEEDED" in _codes(decision)


def test_sell_exactly_sellable_accepted(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("000001.SZ",))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=50,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 50, Decimal("9"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert len(decision.approved_intent_ids) == 1
    assert len(decision.commands) == 1
    assert "SELLABLE_OK" in _codes(decision)


def test_no_approved_intent_skips_command_policy_success_audit(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="true", sell_only="true")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert decision.commands == ()
    assert decision.requires_manual_approval is False
    assert "MANUAL_APPROVAL_REQUIRED" not in _codes(decision)
    assert "COMMANDS_EMITTED" not in _codes(decision)
    assert "SHADOW_READ_ONLY" not in _codes(decision)
    assert any(item.code == "SELL_ONLY" and not item.accepted for item in decision.rule_results)


def _assert_stable_risk_input_error(exc: BaseException, code: str, *forbidden: object) -> None:
    assert isinstance(exc, RiskInputError)
    assert type(exc) is RiskInputError
    assert str(exc) == code
    assert repr(exc) == f"RiskInputError({code!r})"
    assert exc.__cause__ is None
    assert exc.__context__ is None
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert code in rendered
    for item in forbidden:
        token = str(item)
        assert token not in str(exc)
        assert token not in repr(exc)
        assert token not in rendered


def test_forged_market_quota_and_price_rejected_before_rules(tmp_path: Path) -> None:
    """P0-A style: mutate market economics while keeping old snapshot_id."""
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    state = market.states[0]
    forged_price = Decimal("987654.32")
    object.__setattr__(state, "reference_price", forged_price)
    assert market.snapshot_id == plan.market_snapshot_id
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(
            exc,
            "MARKET_CONTRACT_INVALID",
            forged_price,
            "987654.32",
        )
    else:
        raise AssertionError("forged market must raise RiskInputError")


def test_forged_market_suspended_rejected_before_rules(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(suspended=True)
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    state = market.states[0]
    object.__setattr__(state, "suspended", False)
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "MARKET_CONTRACT_INVALID")
    else:
        raise AssertionError("forged suspended flag must raise RiskInputError")


def test_forged_account_cash_and_sellable_rejected(tmp_path: Path) -> None:
    """P0-B style: mutate account economics while keeping old snapshot_id."""
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("000001.SZ",))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=50,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(cash_available=Decimal("1000"), positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 100, Decimal("9"))],
    )
    forged_sellable = 555
    forged_cash = Decimal("999999.01")
    object.__setattr__(account.positions[0], "sellable_quantity", forged_sellable)
    object.__setattr__(account.cash[0], "available", forged_cash)
    assert account.snapshot_id == plan.account_snapshot_id
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(
            exc,
            "ACCOUNT_CONTRACT_INVALID",
            forged_sellable,
            forged_cash,
            "999999.01",
        )
    else:
        raise AssertionError("forged account must raise RiskInputError")


def test_forged_account_quantity_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("000001.SZ",))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=50,
        sellable_quantity=50,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 50, Decimal("9"))],
    )
    forged_qty = 7777
    object.__setattr__(account.positions[0], "quantity", forged_qty)
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "ACCOUNT_CONTRACT_INVALID", forged_qty)
    else:
        raise AssertionError("forged position quantity must raise RiskInputError")


def test_forged_plan_intent_quantity_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    intent = plan.intents[0]
    old_plan_id = plan.plan_id
    old_intent_id = intent.intent_id
    forged_qty = 888888
    object.__setattr__(intent, "quantity", forged_qty)
    assert plan.plan_id == old_plan_id
    assert intent.intent_id == old_intent_id
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "PLAN_CONTRACT_INVALID", forged_qty)
    else:
        raise AssertionError("forged intent quantity must raise RiskInputError")


def test_forged_plan_intent_side_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market(symbols=("600000.SH", "000001.SZ"))
    pos = build_position_balance(
        symbol="000001.SZ",
        market=Market.SZ,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    account = _account(positions=(pos,))
    plan = _plan(
        config,
        market,
        account,
        intents=[("000001.SZ", OrderSide.SELL, 100, Decimal("9"))],
    )
    intent = plan.intents[0]
    old_plan_id = plan.plan_id
    old_intent_id = intent.intent_id
    object.__setattr__(intent, "side", OrderSide.BUY)
    assert plan.plan_id == old_plan_id
    assert intent.intent_id == old_intent_id
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "PLAN_CONTRACT_INVALID", "BUY")
    else:
        raise AssertionError("forged intent side must raise RiskInputError")


def test_forged_daily_counters_negative_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    counters = _counters()
    object.__setattr__(counters, "order_count", -3)
    try:
        evaluate_pretrade(plan, account, market, config, counters, now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "COUNTERS_INVALID", -3)
    else:
        raise AssertionError("negative counter must raise RiskInputError")


def test_forged_daily_counters_bool_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    counters = _counters()
    object.__setattr__(counters, "cancel_count", True)
    try:
        evaluate_pretrade(plan, account, market, config, counters, now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "COUNTERS_INVALID", True)
    else:
        raise AssertionError("bool counter must raise RiskInputError")


# --- P0B3: route-aware connect context / quota ---


def test_p0b3_hk_buy_quota_false_rejects_sell_not_blocked(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=False)
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(ctx,),
    )
    pos = build_position_balance(
        symbol="00700.HK",
        market=Market.HK,
        quantity=200,
        sellable_quantity=200,
        avg_cost=build_money_amount(Currency.HKD, Decimal("80")),
    )
    account = _account(positions=(pos,))
    buy_plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    buy_decision = evaluate_pretrade(buy_plan, account, market, config, _counters(), now=_utc(3))
    assert buy_decision.approved_intent_ids == ()
    assert "BUY_QUOTA_UNAVAILABLE" in _codes(buy_decision)

    sell_plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.SELL, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    sell_decision = evaluate_pretrade(sell_plan, account, market, config, _counters(), now=_utc(3))
    assert len(sell_decision.approved_intent_ids) == 1
    assert "BUY_QUOTA_UNAVAILABLE" not in _codes(sell_decision)


def test_p0b3_hk_missing_context_and_route_mismatch_fail_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    sh_ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=True)
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(sh_ctx,),
    )
    account = _account()
    # intent route absent from snapshot contexts
    plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SZ_CONNECT)],
    )
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.approved_intent_ids == ()
    assert "CONNECT_CONTEXT_MISSING" in _codes(decision)


def test_p0b3_hk_session_and_future_context_fail_closed(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    good = _connect_ctx(route=ConnectRoute.SH_CONNECT, as_of=_utc(3))
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        as_of=_utc(3),
        connect_contexts=(good,),
    )
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )

    # wrong session kept under old snapshot_id → prove rejects
    object.__setattr__(market.connect_contexts[0], "session_date", dt.date(2026, 7, 15))
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "MARKET_CONTRACT_INVALID")
    else:
        raise AssertionError("session-mismatched context must raise")

    # rebuild then forge future as_of
    good2 = _connect_ctx(route=ConnectRoute.SH_CONNECT, as_of=_utc(3))
    market2 = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        as_of=_utc(3),
        connect_contexts=(good2,),
    )
    plan2 = _plan(
        config,
        market2,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    object.__setattr__(market2.connect_contexts[0], "as_of", _utc(4))
    try:
        evaluate_pretrade(plan2, account, market2, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "MARKET_CONTRACT_INVALID")
    else:
        raise AssertionError("future context as_of must raise")


def test_p0b3_exact_route_selection_no_or_aggregate(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    sh_closed = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=False)
    sz_open = _connect_ctx(route=ConnectRoute.SZ_CONNECT, buy_quota_available=True)
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(sh_closed, sz_open),
    )
    account = _account()
    # SH intent must use SH context (quota false), not OR/first SZ
    sh_plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    sh_decision = evaluate_pretrade(sh_plan, account, market, config, _counters(), now=_utc(3))
    assert sh_decision.approved_intent_ids == ()
    assert "BUY_QUOTA_UNAVAILABLE" in _codes(sh_decision)

    sz_plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SZ_CONNECT)],
    )
    sz_decision = evaluate_pretrade(sz_plan, account, market, config, _counters(), now=_utc(3))
    assert len(sz_decision.approved_intent_ids) == 1
    assert "BUY_QUOTA_UNAVAILABLE" not in _codes(sz_decision)


def test_p0b3_a_share_ignores_connect_context_and_state_has_no_quota(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, manual_approval="false")
    market = _market()
    assert market.connect_contexts == ()
    assert not hasattr(market.states[0], "buy_quota_available")
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("600000.SH", OrderSide.BUY, 100, Decimal("10"))],
    )
    assert plan.intents[0].connect_route is None
    decision = evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    assert decision.accepted is True
    assert len(decision.approved_intent_ids) == 1
    assert not any(
        item.code.startswith("CONNECT_CONTEXT") for item in decision.rule_results
    )
    assert "BUY_QUOTA_UNAVAILABLE" not in _codes(decision)


def test_p0b3_forged_context_or_intent_route_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=True)
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(ctx,),
    )
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )

    object.__setattr__(market.connect_contexts[0], "buy_quota_available", False)
    assert market.snapshot_id == plan.market_snapshot_id
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "MARKET_CONTRACT_INVALID")
    else:
        raise AssertionError("forged context quota must raise")

    ctx2 = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=True)
    market2 = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(ctx2,),
    )
    plan2 = _plan(
        config,
        market2,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    object.__setattr__(plan2.intents[0], "connect_route", ConnectRoute.SZ_CONNECT)
    try:
        evaluate_pretrade(plan2, account, market2, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "PLAN_CONTRACT_INVALID")
    else:
        raise AssertionError("forged intent route must raise")


def test_p0b3_duplicate_route_contexts_fail_closed_at_prove(tmp_path: Path) -> None:
    config = _config(tmp_path, manual_approval="false", max_symbol_weight="1.0")
    ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT, buy_quota_available=True)
    market = _market(
        symbols=("00700.HK",),
        price=Decimal("100"),
        connect_contexts=(ctx,),
    )
    account = _account()
    plan = _plan(
        config,
        market,
        account,
        intents=[("00700.HK", OrderSide.BUY, 100, Decimal("100"), ConnectRoute.SH_CONNECT)],
    )
    # inject duplicate route under old snapshot_id
    object.__setattr__(market, "connect_contexts", (ctx, ctx))
    try:
        evaluate_pretrade(plan, account, market, config, _counters(), now=_utc(3))
    except RiskInputError as exc:
        _assert_stable_risk_input_error(exc, "MARKET_CONTRACT_INVALID")
    else:
        raise AssertionError("duplicate connect contexts must raise")
    build_execution_event,
    evaluate_cancel_risk,
