"""M4-B7 deterministic execution and ledger-book metrics."""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
import quant.reporting.trading_metrics as trading_metrics_module

from quant.backtest.event_simulator import (
    SimulationFillSpec,
    build_event_simulation_config,
    build_scheduled_order_plan,
    build_simulation_scenario_plans,
    simulate_order_plans,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain.enums import Currency
from quant.execution.contracts import ExecutionEvent
from quant.portfolio.order_planner import OrderPlanTarget, build_order_plan
from quant.reporting import (
    TradingMetricsError,
    build_trading_metrics,
)
from tests.unit.test_event_simulator import (
    FRI,
    MON,
    SESSIONS,
    TUE,
    _account,
    _actions,
    _at,
    _fixture,
    _fully_rehash_result,
    _market,
    _planner,
    _rule,
)


def _metrics(*, partial: bool = False, suspended: bool = False):
    args = _fixture(partial=partial, suspended=suspended)
    return build_trading_metrics(simulate_order_plans(*args), 252)


def _monday_buy_result():
    planner = _planner()
    account = _account()
    snapshots = (_market(FRI), _market(MON), _market(TUE))
    plan = build_order_plan(
        targets=(OrderPlanTarget("600000.SH", snapshots[1].states[0].market, None, Decimal(1)),),
        target_identity="1" * 64,
        market=snapshots[1],
        account=account,
        config=planner,
    )
    intent = plan.intents[0]
    scheduled = build_scheduled_order_plan(
        plan=plan,
        planned_account=account,
        session_date=MON,
        signal_known_at=_at(MON, 0, 30),
        session_close_at=_at(MON, 7),
        fills=(
            SimulationFillSpec(
                intent.intent_id,
                _at(MON, 2),
                intent.quantity,
                intent.quantity,
                Decimal("10"),
            ),
        ),
    )
    actions = _actions().head(0)
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
    scenario = build_simulation_scenario_plans(
        scenario_id="drawdown", scheduled_plans=(scheduled,)
    )
    return simulate_order_plans((scenario,), snapshots, account, config)


def test_partial_fill_fees_and_identity_are_exact_and_deterministic() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    left = build_trading_metrics(result, 252)
    right = build_trading_metrics(result, 252)
    assert left == right
    assert left.metrics_id == "13fe4126c555e7f37003fbfce0c1d359d9e2536147614a7796df4aded8923826"
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        assert build_trading_metrics(result, 252) == left
    scenario = left.scenarios[0]
    assert scenario.command_count == 1
    assert scenario.fill_event_count == 1
    assert scenario.partial_fill_event_count == 1
    assert scenario.requested_quantity == 100
    assert scenario.filled_quantity == 50
    assert scenario.fill_ratio == Decimal("0.5")
    cny = scenario.currencies[0]
    assert cny.currency is Currency.CNY
    assert cny.gross_traded_notional == Decimal("500")
    assert cny.total_fees == Decimal("5.01")

    with pytest.raises(TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"):
        replace(left, metrics_id="0" * 64)


def test_zero_trade_keeps_ratios_incomputable_instead_of_filling_zero() -> None:
    metrics = _metrics(suspended=True)
    scenario = metrics.scenarios[0]
    assert scenario.command_count == 0
    assert scenario.fill_event_count == 0
    assert scenario.requested_quantity == 0
    assert scenario.filled_quantity == 0
    assert scenario.fill_ratio is None
    assert all(item.gross_traded_notional == 0 for item in scenario.currencies)
    assert all(item.total_fees == 0 for item in scenario.currencies)


def test_checkpoint_book_drawdown_and_annualized_volatility_are_reported() -> None:
    metrics = build_trading_metrics(_monday_buy_result(), 252)
    cny = metrics.scenarios[0].currencies[0]
    assert cny.maximum_book_drawdown is not None
    assert cny.maximum_book_drawdown > 0
    assert cny.annualized_book_volatility is not None
    assert cny.annualized_book_volatility > 0
    assert cny.closing_book_value < cny.opening_book_value


@pytest.mark.parametrize("annualization", [True, 0, -1, 252.0])
def test_annualization_rejects_bool_non_positive_and_non_integer(annualization: object) -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    with pytest.raises(TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"):
        build_trading_metrics(result, annualization)  # type: ignore[arg-type]


def test_nan_fill_is_rejected_instead_of_becoming_zero() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    scenario = result.scenarios[0]
    original = next(item for item in scenario.events if item.last_price is not None)
    forged = ExecutionEvent.__new__(ExecutionEvent)
    for field in fields(ExecutionEvent):
        object.__setattr__(forged, field.name, getattr(original, field.name))
    object.__setattr__(forged, "last_price", Decimal("NaN"))
    tampered_events = tuple(forged if item is original else item for item in scenario.events)
    tampered = replace(result, scenarios=(replace(scenario, events=tampered_events),))

    with pytest.raises(TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"):
        build_trading_metrics(tampered, 252)


def test_forged_b6_root_and_scenario_identity_are_rejected_before_metrics() -> None:
    args = _fixture(partial=True)
    result = simulate_order_plans(*args)
    renamed = replace(result.scenarios[0], scenario_id="renamed")
    for tampered in (
        replace(result, result_id="0" * 64),
        replace(result, scenarios=(renamed,)),
        replace(result, scenarios=(result.scenarios[0], result.scenarios[0])),
    ):
        with pytest.raises(TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"):
            build_trading_metrics(tampered, 252)


def test_fully_rehashed_b6_semantic_forgery_is_rejected_before_metrics() -> None:
    result = simulate_order_plans(*_fixture(partial=True))
    scenario = result.scenarios[0]
    forged_decision = replace(
        scenario.rule_decisions[0],
        accepted=False,
        code="FORGED_DECISION",
        normalized_quantity=0,
    )
    forged = _fully_rehash_result(
        result, replace(scenario, rule_decisions=(forged_decision,))
    )
    with pytest.raises(TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"):
        build_trading_metrics(forged, 252)


def test_hostile_b6_verifier_failure_is_detached_before_metrics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    result = simulate_order_plans(*_fixture(partial=True))

    def _hostile_verifier(_result):  # type: ignore[no-untyped-def]
        raise RuntimeError("C:/PRIVATE_TOKEN_SENTINEL")

    monkeypatch.setattr(
        trading_metrics_module, "verify_simulation_result_identity", _hostile_verifier
    )
    with pytest.raises(
        TradingMetricsError, match="^TRADING_METRICS_INPUT_INVALID$"
    ) as error:
        build_trading_metrics(result, 252)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
