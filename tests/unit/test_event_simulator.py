"""M4-B6 deterministic event-simulator contract tests."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from quant.backtest import verify_simulation_result_identity as public_identity_verifier
from quant.backtest.a_share_execution import build_a_share_rule_config
from quant.backtest.connect_execution import build_connect_rule_config
from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.backtest.event_simulator import (
    EventSimulationError,
    SimulationFillSpec,
    build_event_simulation_config,
    build_scheduled_order_plan,
    build_simulation_scenario_plans,
    simulate_order_plans,
    verify_simulation_result,
    verify_simulation_result_identity,
)
from quant.backtest.fx import FxRate, build_fx_snapshot
from quant.backtest.ledger import build_settlement_rule
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain.enums import ConnectRoute, Currency, Market
from quant.execution.config import load_trading_config
from quant.execution.contracts import (
    build_account_snapshot,
    build_cash_balance,
    build_money_amount,
    build_position_balance,
    build_symbol_market_state,
    build_verified_connect_market_context,
    build_verified_market_snapshot,
)
from quant.portfolio.order_planner import (
    OrderPlanTarget,
    build_order_plan,
    build_order_planner_config,
)

FRI = dt.date(2026, 7, 17)
MON = dt.date(2026, 7, 20)
TUE = dt.date(2026, 7, 21)
SESSIONS = (FRI, MON, TUE)
OPEN = dt.time(1, 30)
A_RULE = "a_share_execution_rules_v1"


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _at(day: dt.date, hour: int = 1, minute: int = 30) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=dt.UTC)


def _actions() -> pl.DataFrame:
    return pl.DataFrame(
        [{
            "event_id": "a" * 64,
            "symbol": "600000.SH",
            "ex_date": MON,
            "action_type": "DIVIDEND_DISTRIBUTION",
            "cash_per_share_gross": 0.1,
            "stock_ratio": 0.1,
            "rights_price": None,
            "rights_ratio": 0.0,
            "rights_actual_shares": None,
            "rights_pre_shares": None,
            "rights_post_shares": None,
            "rights_pre_circulating_shares": None,
            "rights_post_circulating_shares": None,
            "rights_mixed_change_proof_sha256": None,
            "record_date": FRI,
            "pay_date": MON,
            "stock_list_date": MON,
            "vendor_record_id": "fixture",
            "source": "fixture",
            "source_snapshot_id": _hex("action-source"),
        }]
    ).with_columns(pl.col("ex_date", "record_date", "pay_date", "stock_list_date").cast(pl.Date))


def _planner(day: dt.date = FRI):
    schedule = build_execution_cost_schedule(
        selector="a_share_research_cost_schedule_v1",
        periods=(
            ExecutionCostPeriod(
                Market.SH,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
            ExecutionCostPeriod(
                Market.SZ,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
            ExecutionCostPeriod(
                Market.HK,
                dt.date(2026, 1, 1),
                None,
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0.0005"),
                Decimal("0.00001"),
                Currency.CNY,
            ),
        ),
    )
    return build_order_planner_config(
        trading_config=load_trading_config(Path("configs/trading/example.toml")),
        a_share_rule_config=build_a_share_rule_config(
            selector=A_RULE, effective_from=dt.date(2020, 1, 1), effective_to=None
        ),
        connect_rule_configs=tuple(
            build_connect_rule_config(
                selector="hk_connect_execution_rules_v1",
                route=route,
                effective_from=dt.date(2026, 1, 1),
                effective_to=None,
            )
            for route in (ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT)
        ),
        execution_cost_schedule=schedule,
        fx_snapshot=build_fx_snapshot(
            selector="cny_hkd_fx_schedule_v1",
            session_date=day,
            observed_at=_at(day, 1),
            expires_at=_at(day, 8),
            rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.9")),),
        ),
        minimum_order_notionals=(build_money_amount(Currency.CNY, Decimal("1")),),
    )


def _state(day: dt.date, *, suspended: bool = False):
    return build_symbol_market_state(
        symbol="600000.SH",
        market=Market.SH,
        session_date=day,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=suspended,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version=A_RULE,
    )


def _market(day: dt.date, *, suspended: bool = False):
    return build_verified_market_snapshot(
        as_of=_at(day),
        session_date=day,
        states=(_state(day, suspended=suspended),),
        connect_contexts=(),
        calendar_identity=_hex(f"calendar-{day}"),
        source_identity=_hex(f"source-{day}"),
    )


def _account():
    return build_account_snapshot(
        as_of=_at(FRI, 0),
        positions=(
            build_position_balance(
                symbol="600000.SH",
                market=Market.SH,
                quantity=100,
                sellable_quantity=100,
                avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
            ),
        ),
        cash=(build_cash_balance(
            currency=Currency.CNY,
            settled=Decimal("2000"),
            available=Decimal("2000"),
            receivable=Decimal(0),
            payable=Decimal(0),
        ),),
    )


def _rule():
    return build_settlement_rule(
        selector="sh-settlement-v1",
        market=Market.SH,
        quote_currency=Currency.CNY,
        settlement_currency=Currency.CNY,
        effective_from=FRI,
        effective_to=None,
        trading_sessions=SESSIONS,
        settlement_sessions=SESSIONS,
        trading_calendar_source_identity=_hex("trade-calendar"),
        settlement_calendar_source_identity=_hex("settle-calendar"),
        settlement_lag_sessions=1,
        sellable_lag_sessions=1,
        reuse_sell_receivables=True,
    )


def _fixture(*, partial: bool = False, suspended: bool = False):
    planner = _planner()
    account = _account()
    first = _market(FRI, suspended=suspended)
    snapshots = (first, _market(MON), _market(TUE))
    plan = build_order_plan(
        targets=(OrderPlanTarget("600000.SH", Market.SH, None, Decimal("1")),),
        target_identity=_hex("target"),
        market=first,
        account=account,
        config=planner,
    )
    fills: tuple[SimulationFillSpec, ...] = ()
    if plan.intents:
        intent = plan.intents[0]
        quantity = 50 if partial else intent.quantity
        fills = (SimulationFillSpec(intent.intent_id, _at(FRI, 2), quantity, quantity, Decimal("10")),)
    scheduled = build_scheduled_order_plan(
        plan=plan,
        planned_account=account,
        session_date=FRI,
        signal_known_at=_at(FRI, 0, 30),
        session_close_at=_at(FRI, 7),
        fills=fills,
    )
    scenario = build_simulation_scenario_plans(
        scenario_id="base", scheduled_plans=(scheduled,)
    )
    actions = _actions()
    config = build_event_simulation_config(
        event_sessions=SESSIONS,
        terminal_date=TUE,
        planner_configs=(planner,),
        settlement_rules=(_rule(),),
        corporate_actions=actions,
        corporate_actions_sha256=clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=actions
        ),
        sh_sessions=SESSIONS,
    )
    return (scenario,), snapshots, account, config


def test_a_share_t1_company_action_and_no_order_sessions_advance() -> None:
    args = _fixture()
    result = simulate_order_plans(*args)
    scenario = result.scenarios[0]
    assert verify_simulation_result(result, *args) == result
    assert [item.event_type.value for item in scenario.events] == ["ACCEPTED", "FILL"]
    assert scenario.final_state.as_of_date == TUE
    position = scenario.final_state.positions[0]
    assert position.quantity == 220  # 100 original + 100 buy + 20 record-close stock
    assert position.sellable_quantity == 220
    assert len(scenario.checkpoints) == 3
    kinds = [entry.kind for transition in scenario.transitions for entry in transition.entries]
    assert kinds.index("CORPORATE_CASH_RECOGNIZE") < kinds.index("CORPORATE_CASH_SETTLE")
    assert kinds.index("TRADE_BUY") < kinds.index("CORPORATE_CAPTURE")


def test_partial_fill_is_cancelled_and_scenarios_are_isolated_and_stable() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    assert [item.event_type.value for item in result.scenarios[0].events] == [
        "ACCEPTED", "PARTIAL_FILL", "CANCELLED"
    ]
    assert simulate_order_plans(*args) == result
    second = build_simulation_scenario_plans(
        scenario_id="stress", scheduled_plans=args[0][0].scheduled_plans
    )
    combined = simulate_order_plans((args[0][0], second), args[1], args[2], args[3])
    assert combined.scenarios[0].initial_ledger_state_id == combined.scenarios[1].initial_ledger_state_id
    assert combined.scenarios[0].final_state == combined.scenarios[1].final_state


def test_suspended_plan_rejection_and_temporal_or_account_drift_fail_closed() -> None:
    args = _fixture(suspended=True)
    result = simulate_order_plans(*args)
    assert not result.scenarios[0].events
    assert result.scenarios[0].rule_decisions[0].code == "SUSPENDED"

    scheduled = args[0][0].scheduled_plans[0]
    leaked = build_scheduled_order_plan(
        plan=scheduled.plan,
        planned_account=scheduled.planned_account,
        session_date=FRI,
        signal_known_at=args[1][0].as_of,
        session_close_at=scheduled.session_close_at,
        fills=scheduled.fills,
    )
    with pytest.raises(EventSimulationError, match="^EVENT_SIM_TEMPORAL_LEAKAGE$"):
        simulate_order_plans(
            (build_simulation_scenario_plans(scenario_id="base", scheduled_plans=(leaked,)),),
            args[1], args[2], args[3]
        )

    foreign = build_account_snapshot(
        as_of=scheduled.planned_account.as_of,
        positions=scheduled.planned_account.positions,
        cash=(build_cash_balance(
            currency=Currency.CNY,
            settled=Decimal("1999"),
            available=Decimal("1999"),
            receivable=Decimal(0),
            payable=Decimal(0),
        ),),
    )
    with pytest.raises(EventSimulationError, match="^EVENT_SIM_ACCOUNT_DRIFT$"):
        build_scheduled_order_plan(
            plan=scheduled.plan,
            planned_account=foreign,
            session_date=FRI,
            signal_known_at=scheduled.signal_known_at,
            session_close_at=scheduled.session_close_at,
            fills=scheduled.fills,
        )


def test_friday_plan_rejects_monday_fill_and_close() -> None:
    args = _fixture(partial=True)
    scheduled = args[0][0].scheduled_plans[0]
    intent = scheduled.plan.intents[0]
    monday_fill = SimulationFillSpec(
        intent.intent_id, _at(MON, 2), 50, 50, Decimal("10")
    )
    with pytest.raises(EventSimulationError) as caught:
        build_scheduled_order_plan(
            plan=scheduled.plan,
            planned_account=scheduled.planned_account,
            session_date=FRI,
            signal_known_at=scheduled.signal_known_at,
            session_close_at=_at(MON, 7),
            fills=(monday_fill,),
        )
    assert "MONDAY" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_result_verifier_rejects_tampering() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    with pytest.raises(EventSimulationError, match="^EVENT_SIM_RESULT_MISMATCH$"):
        verify_simulation_result(replace(result, result_id="0" * 64), *args)


def test_result_identity_verifier_rejects_root_scenario_and_collection_forgery() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    assert verify_simulation_result_identity(result) == result
    assert public_identity_verifier is verify_simulation_result_identity
    error = "^EVENT_SIM_RESULT_IDENTITY_INVALID$"

    with pytest.raises(EventSimulationError, match=error) as caught:
        verify_simulation_result_identity(replace(result, result_id="0" * 64))
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    renamed = replace(result.scenarios[0], scenario_id="renamed")
    with pytest.raises(EventSimulationError, match=error):
        verify_simulation_result_identity(replace(result, scenarios=(renamed,)))
    with pytest.raises(EventSimulationError, match=error):
        verify_simulation_result_identity(
            replace(result, scenarios=(result.scenarios[0], result.scenarios[0]))
        )

    stress = build_simulation_scenario_plans(
        scenario_id="stress", scheduled_plans=args[0][0].scheduled_plans
    )
    combined = simulate_order_plans((args[0][0], stress), args[1], args[2], args[3])
    assert verify_simulation_result_identity(combined) == combined
    with pytest.raises(EventSimulationError, match=error):
        verify_simulation_result_identity(replace(combined, scenarios=combined.scenarios[:1]))
    with pytest.raises(EventSimulationError, match=error):
        verify_simulation_result_identity(replace(result, scenarios=combined.scenarios))


def test_nested_frozen_plan_mutation_is_reproved_without_sentinel_leak() -> None:
    args = _fixture(partial=True)
    sentinel = "TOKEN_IDENTITY_SENTINEL"
    object.__setattr__(args[0][0].scheduled_plans[0].plan, "plan_id", sentinel)
    with pytest.raises(
        EventSimulationError, match="^EVENT_SIM_IDENTITY_INVALID$"
    ) as caught:
        simulate_order_plans(*args)
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_hostile_corporate_action_failure_is_fully_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    import quant.backtest.event_simulator as simulator_module

    args = _fixture(partial=True)
    sentinel = "C:/TOKEN_CORPORATE_ACTION_SENTINEL"

    def hostile(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        simulator_module.CorporateActionLedgerSchema, "validate", hostile
    )
    with pytest.raises(
        EventSimulationError, match="^EVENT_SIM_INPUT_INVALID$"
    ) as caught:
        simulate_order_plans(*args)
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_hk_connect_t2_uses_explicit_fx_and_exact_settlement_sessions() -> None:
    planner = _planner()
    account = build_account_snapshot(
        as_of=_at(FRI, 0),
        positions=(build_position_balance(
            symbol="00700.HK",
            market=Market.HK,
            quantity=100,
            sellable_quantity=100,
            avg_cost=build_money_amount(Currency.HKD, Decimal("8")),
        ),),
        cash=(build_cash_balance(
            currency=Currency.CNY,
            settled=Decimal("1000"),
            available=Decimal("1000"),
            receivable=Decimal(0),
            payable=Decimal(0),
        ),),
    )

    def market(day: dt.date):
        context = build_verified_connect_market_context(
            route=ConnectRoute.SH_CONNECT,
            session_date=day,
            as_of=_at(day),
            mainland_open=True,
            hong_kong_open=True,
            buy_quota_available=True,
            calendar_identity=_hex(f"hk-calendar-{day}"),
            quota_identity=_hex(f"hk-quota-{day}"),
            source_identity=_hex(f"hk-context-{day}"),
        )
        state = build_symbol_market_state(
            symbol="00700.HK",
            market=Market.HK,
            session_date=day,
            quote_currency=Currency.HKD,
            reference_price=Decimal("10"),
            limit_up=Decimal("11"),
            limit_down=Decimal("9"),
            suspended=False,
            board_lot=100,
            tick_size=Decimal("0.01"),
            rule_version="hk_connect_execution_rules_v1",
        )
        return build_verified_market_snapshot(
            as_of=_at(day),
            session_date=day,
            states=(state,),
            connect_contexts=(context,),
            calendar_identity=_hex(f"root-calendar-{day}"),
            source_identity=_hex(f"root-source-{day}"),
        )

    snapshots = tuple(market(day) for day in SESSIONS)
    plan = build_order_plan(
        targets=(OrderPlanTarget(
            "00700.HK", Market.HK, ConnectRoute.SH_CONNECT, Decimal(0)
        ),),
        target_identity=_hex("hk-target"),
        market=snapshots[0],
        account=account,
        config=planner,
    )
    intent = plan.intents[0]
    scheduled = build_scheduled_order_plan(
        plan=plan,
        planned_account=account,
        session_date=FRI,
        signal_known_at=_at(FRI, 0, 30),
        session_close_at=_at(FRI, 7),
        fills=(SimulationFillSpec(
            intent.intent_id, _at(FRI, 2), 100, 100, Decimal("10")
        ),),
    )
    actions = _actions()
    hk_rule = build_settlement_rule(
        selector="hk-settlement-v1",
        market=Market.HK,
        quote_currency=Currency.HKD,
        settlement_currency=Currency.CNY,
        effective_from=FRI,
        effective_to=None,
        trading_sessions=SESSIONS,
        settlement_sessions=SESSIONS,
        trading_calendar_source_identity=_hex("hk-trade-calendar"),
        settlement_calendar_source_identity=_hex("hk-settle-calendar"),
        settlement_lag_sessions=2,
        sellable_lag_sessions=0,
        reuse_sell_receivables=True,
    )
    config = build_event_simulation_config(
        event_sessions=SESSIONS,
        terminal_date=TUE,
        planner_configs=(planner,),
        settlement_rules=(hk_rule,),
        corporate_actions=actions,
        corporate_actions_sha256=clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=actions
        ),
        sh_sessions=SESSIONS,
    )
    scenario = build_simulation_scenario_plans(
        scenario_id="hk", scheduled_plans=(scheduled,)
    )
    result = simulate_order_plans((scenario,), snapshots, account, config)
    friday_cash = next(
        item for item in result.scenarios[0].transitions[-6].state.cash
        if item.currency is Currency.CNY
    )
    final_cash = result.scenarios[0].final_state.cash[0]
    assert friday_cash.receivable > 0
    assert final_cash.receivable == 0
    assert final_cash.settled > Decimal("1000")
    assert not result.scenarios[0].final_state.pending
