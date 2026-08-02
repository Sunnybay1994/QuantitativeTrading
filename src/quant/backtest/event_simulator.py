"""Pure, deterministic M4-B6 event replay over verified M4 contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import NoReturn, TypeVar, cast

import polars as pl

from quant.backtest.a_share_execution import evaluate_a_share_intent
from quant.backtest.connect_execution import evaluate_connect_intent
from quant.backtest.corporate_actions import (
    capture_record_close_entitlements,
    recognize_ex_date_entitlements,
    settle_due_entitlements,
)
from quant.backtest.costs import calculate_execution_cost
from quant.backtest.ledger import (
    LedgerState,
    LedgerTransition,
    SettlementRule,
    advance_ledger_state,
    apply_corporate_action,
    apply_execution_event,
    build_capture_entitlement_transition,
    build_ledger_state,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import CorporateActionLedgerSchema
from quant.domain.enums import ExecutionEventType, ExecutionMode, Market, OrderSide
from quant.execution.contracts import (
    AccountSnapshot,
    ExecutionEvent,
    OrderCommand,
    OrderIntent,
    OrderPlan,
    RuleDecision,
    VerifiedMarketSnapshot,
    build_account_snapshot_identity,
    build_execution_event_identity,
    build_execution_event,
    build_order_command_identity,
    build_order_command,
    build_order_intent_identity,
    build_order_plan_identity,
    build_rule_decision_identity,
    build_verified_market_snapshot_identity,
)
from quant.portfolio.order_planner import OrderPlannerConfig

_HASH_VERSION = "m4-event-simulator-v1"
_HEX = frozenset("0123456789abcdef")
_T = TypeVar("_T")


class EventSimulationError(ValueError):
    """Stable, path-free simulator contract failure."""


def _fail(code: str) -> NoReturn:
    raise EventSimulationError(code) from None


def _sanitized(code: str, operation: Callable[[], _T]) -> _T:
    """Map an untrusted exception only after leaving its active except scope."""
    failed = False
    result: _T | None = None
    try:
        result = operation()
    except EventSimulationError:
        raise
    except Exception:
        failed = True
    if failed:
        _fail(code)
    return cast(_T, result)


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in _HEX for c in value)


def _utc(value: object) -> bool:
    if type(value) is not dt.datetime:
        return False
    try:
        return value.utcoffset() == dt.timedelta(0)
    except Exception:
        return False


def _canon(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canon(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        if not value.is_finite():
            _fail("EVENT_SIM_INPUT_INVALID")
        return format(value, "f")
    if type(value) is dt.datetime:
        if not _utc(value):
            _fail("EVENT_SIM_INPUT_INVALID")
        return value.astimezone(dt.UTC).isoformat()
    if type(value) is dt.date:
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canon(item) for item in value]
    if isinstance(value, list):
        return [_canon(item) for item in value]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            _fail("EVENT_SIM_INPUT_INVALID")
        return {key: _canon(child) for key, child in value.items()}
    if type(value) in {str, int, bool} or value is None:
        return value
    _fail("EVENT_SIM_INPUT_INVALID")


def _identity(type_name: str, payload: object) -> str:
    raw = json.dumps(
        {"hash_version": _HASH_VERSION, "type": type_name, "payload": _canon(payload)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulationFillSpec:
    intent_id: str
    occurred_at: dt.datetime
    cumulative_quantity: int
    last_quantity: int
    last_price: Decimal

    def __post_init__(self) -> None:
        if (
            not _hex64(self.intent_id)
            or not _utc(self.occurred_at)
            or type(self.cumulative_quantity) is not int
            or type(self.last_quantity) is not int
            or self.cumulative_quantity <= 0
            or self.last_quantity <= 0
            or self.last_quantity > self.cumulative_quantity
            or type(self.last_price) is not Decimal
            or not self.last_price.is_finite()
            or self.last_price <= 0
        ):
            _fail("EVENT_SIM_FILL_INVALID")


@dataclass(frozen=True, slots=True)
class ScheduledOrderPlan:
    schedule_id: str
    plan: OrderPlan
    planned_account: AccountSnapshot
    session_date: dt.date
    signal_known_at: dt.datetime
    session_close_at: dt.datetime
    fills: tuple[SimulationFillSpec, ...]

    def __post_init__(self) -> None:
        if (
            not _hex64(self.schedule_id)
            or type(self.plan) is not OrderPlan
            or type(self.planned_account) is not AccountSnapshot
            or self.plan.account_snapshot_id != self.planned_account.snapshot_id
            or type(self.session_date) is not dt.date
            or any(item.session_date != self.session_date for item in self.plan.intents)
            or not _utc(self.signal_known_at)
            or not _utc(self.session_close_at)
            or self.session_close_at.date() != self.session_date
            or type(self.fills) is not tuple
            or any(type(item) is not SimulationFillSpec for item in self.fills)
            or any(item.occurred_at.date() != self.session_date for item in self.fills)
            or self.schedule_id != _schedule_identity(
                self.plan,
                self.planned_account,
                self.session_date,
                self.signal_known_at,
                self.session_close_at,
                self.fills,
            )
        ):
            _fail("EVENT_SIM_IDENTITY_INVALID")


def _schedule_identity(
    plan: OrderPlan,
    account: AccountSnapshot,
    session_date: dt.date,
    signal: dt.datetime,
    close: dt.datetime,
    fills: tuple[SimulationFillSpec, ...],
) -> str:
    return _identity(
        "ScheduledOrderPlan",
        {
            "plan_id": plan.plan_id,
            "account_snapshot_id": account.snapshot_id,
            "session_date": session_date,
            "signal_known_at": signal,
            "session_close_at": close,
            "fills": fills,
        },
    )


def build_scheduled_order_plan(
    *,
    plan: OrderPlan,
    planned_account: AccountSnapshot,
    session_date: dt.date,
    signal_known_at: dt.datetime,
    session_close_at: dt.datetime,
    fills: tuple[SimulationFillSpec, ...],
) -> ScheduledOrderPlan:
    """Build one identity-bound plan scheduled for its verified snapshot."""
    def build() -> ScheduledOrderPlan:
        build_order_plan_identity(plan)
        build_account_snapshot_identity(planned_account)
        if plan.account_snapshot_id != planned_account.snapshot_id:
            _fail("EVENT_SIM_ACCOUNT_DRIFT")
        schedule_id = _schedule_identity(
            plan,
            planned_account,
            session_date,
            signal_known_at,
            session_close_at,
            fills,
        )
        return ScheduledOrderPlan(
            schedule_id,
            plan,
            planned_account,
            session_date,
            signal_known_at,
            session_close_at,
            fills,
        )

    return _sanitized("EVENT_SIM_INPUT_INVALID", build)


@dataclass(frozen=True, slots=True)
class SimulationScenarioPlans:
    scenario_input_id: str
    scenario_id: str
    scheduled_plans: tuple[ScheduledOrderPlan, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.scheduled_plans, key=lambda item: item.schedule_id))
        if (
            not _hex64(self.scenario_input_id)
            or type(self.scenario_id) is not str
            or not self.scenario_id
            or self.scenario_id != self.scenario_id.strip()
            or any(char in "/\\:%" or ord(char) < 32 for char in self.scenario_id)
            or type(self.scheduled_plans) is not tuple
            or ordered != self.scheduled_plans
            or len({item.plan.market_snapshot_id for item in ordered}) != len(ordered)
            or self.scenario_input_id
            != _identity(
                "SimulationScenarioPlans",
                {
                    "scenario_id": self.scenario_id,
                    "schedule_ids": tuple(item.schedule_id for item in ordered),
                },
            )
        ):
            _fail("EVENT_SIM_IDENTITY_INVALID")


def build_simulation_scenario_plans(
    *, scenario_id: str, scheduled_plans: tuple[ScheduledOrderPlan, ...]
) -> SimulationScenarioPlans:
    """Canonicalize one scenario-specific account/plan stream."""
    def build() -> SimulationScenarioPlans:
        ordered = tuple(sorted(scheduled_plans, key=lambda item: item.schedule_id))
        identity = _identity(
            "SimulationScenarioPlans",
            {"scenario_id": scenario_id, "schedule_ids": tuple(item.schedule_id for item in ordered)},
        )
        return SimulationScenarioPlans(identity, scenario_id, ordered)

    return _sanitized("EVENT_SIM_INPUT_INVALID", build)


def _prove_scenario(scenario: SimulationScenarioPlans) -> None:
    def prove() -> None:
        if type(scenario) is not SimulationScenarioPlans:
            raise ValueError
        rebuilt: list[ScheduledOrderPlan] = []
        for scheduled in scenario.scheduled_plans:
            build_order_plan_identity(scheduled.plan)
            build_account_snapshot_identity(scheduled.planned_account)
            rebuilt.append(
                ScheduledOrderPlan(
                    schedule_id=scheduled.schedule_id,
                    plan=scheduled.plan,
                    planned_account=scheduled.planned_account,
                    session_date=scheduled.session_date,
                    signal_known_at=scheduled.signal_known_at,
                    session_close_at=scheduled.session_close_at,
                    fills=scheduled.fills,
                )
            )
        SimulationScenarioPlans(
            scenario_input_id=scenario.scenario_input_id,
            scenario_id=scenario.scenario_id,
            scheduled_plans=tuple(rebuilt),
        )

    _sanitized("EVENT_SIM_IDENTITY_INVALID", prove)


@dataclass(frozen=True, slots=True)
class EventSimulationConfig:
    config_id: str
    event_sessions: tuple[dt.date, ...]
    terminal_date: dt.date
    planner_configs: tuple[OrderPlannerConfig, ...]
    settlement_rules: tuple[SettlementRule, ...]
    corporate_actions: pl.DataFrame
    corporate_actions_sha256: str
    sh_sessions: tuple[dt.date, ...]

    def __post_init__(self) -> None:
        _prove_config(self)


def _config_payload(config: EventSimulationConfig) -> dict[str, object]:
    return {
        "event_sessions": config.event_sessions,
        "terminal_date": config.terminal_date,
        "planner_config_ids": tuple(item.config_identity for item in config.planner_configs),
        "settlement_rule_ids": tuple(item.rule_id for item in config.settlement_rules),
        "corporate_actions_sha256": config.corporate_actions_sha256,
        "sh_sessions": config.sh_sessions,
    }


def _prove_config(config: EventSimulationConfig) -> None:
    def prove() -> None:
        if (
            type(config.event_sessions) is not tuple
            or not config.event_sessions
            or any(type(item) is not dt.date for item in config.event_sessions)
            or tuple(sorted(set(config.event_sessions))) != config.event_sessions
            or type(config.terminal_date) is not dt.date
            or config.terminal_date < config.event_sessions[-1]
            or type(config.planner_configs) is not tuple
            or not config.planner_configs
            or any(type(item) is not OrderPlannerConfig for item in config.planner_configs)
            or tuple(sorted(config.planner_configs, key=lambda item: item.config_identity))
            != config.planner_configs
            or len({item.config_identity for item in config.planner_configs})
            != len(config.planner_configs)
            or type(config.settlement_rules) is not tuple
            or not config.settlement_rules
            or any(type(item) is not SettlementRule for item in config.settlement_rules)
            or tuple(sorted(config.settlement_rules, key=lambda item: item.rule_id))
            != config.settlement_rules
            or len({item.rule_id for item in config.settlement_rules}) != len(config.settlement_rules)
            or not isinstance(config.corporate_actions, pl.DataFrame)
            or not _hex64(config.corporate_actions_sha256)
            or type(config.sh_sessions) is not tuple
            or any(type(item) is not dt.date for item in config.sh_sessions)
            or tuple(sorted(set(config.sh_sessions))) != config.sh_sessions
        ):
            raise ValueError
        for planner in config.planner_configs:
            OrderPlannerConfig(
                config_identity=planner.config_identity,
                trading_config=planner.trading_config,
                a_share_rule_config=planner.a_share_rule_config,
                connect_rule_configs=planner.connect_rule_configs,
                execution_cost_schedule=planner.execution_cost_schedule,
                fx_snapshot=planner.fx_snapshot,
                minimum_order_notionals=planner.minimum_order_notionals,
            )
        for rule in config.settlement_rules:
            SettlementRule(
                **{field.name: getattr(rule, field.name) for field in fields(rule)}
            )
        CorporateActionLedgerSchema.validate(config.corporate_actions)
        if clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=config.corporate_actions
        ) != config.corporate_actions_sha256:
            raise ValueError
        if config.config_id != _identity("EventSimulationConfig", _config_payload(config)):
            _fail("EVENT_SIM_IDENTITY_INVALID")

    _sanitized("EVENT_SIM_INPUT_INVALID", prove)


def build_event_simulation_config(
    *,
    event_sessions: tuple[dt.date, ...],
    terminal_date: dt.date,
    planner_configs: tuple[OrderPlannerConfig, ...],
    settlement_rules: tuple[SettlementRule, ...],
    corporate_actions: pl.DataFrame,
    corporate_actions_sha256: str,
    sh_sessions: tuple[dt.date, ...],
) -> EventSimulationConfig:
    """Build a self-proving, pure in-memory simulation config."""
    def build() -> EventSimulationConfig:
        ordered_configs = tuple(sorted(planner_configs, key=lambda item: item.config_identity))
        ordered_rules = tuple(sorted(settlement_rules, key=lambda item: item.rule_id))
        provisional = EventSimulationConfig.__new__(EventSimulationConfig)
        values: dict[str, object] = {
            "event_sessions": event_sessions,
            "terminal_date": terminal_date,
            "planner_configs": ordered_configs,
            "settlement_rules": ordered_rules,
            "corporate_actions": corporate_actions.clone(),
            "corporate_actions_sha256": corporate_actions_sha256,
            "sh_sessions": sh_sessions,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "config_id", "0" * 64)
        identity = _identity("EventSimulationConfig", _config_payload(provisional))
        return EventSimulationConfig(config_id=identity, **values)  # type: ignore[arg-type]

    return _sanitized("EVENT_SIM_INPUT_INVALID", build)


@dataclass(frozen=True, slots=True)
class SimulationCheckpoint:
    session_date: dt.date
    market_snapshot_id: str
    ledger_state_id: str


@dataclass(frozen=True, slots=True)
class VerifiedScenarioResult:
    scenario_result_id: str
    scenario_id: str
    input_identity: str
    initial_ledger_state_id: str
    final_state: LedgerState
    commands: tuple[OrderCommand, ...]
    events: tuple[ExecutionEvent, ...]
    rule_decisions: tuple[RuleDecision, ...]
    transitions: tuple[LedgerTransition, ...]
    checkpoints: tuple[SimulationCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class VerifiedSimulationResult:
    result_id: str
    config_id: str
    initial_account_snapshot_id: str
    market_snapshot_ids: tuple[str, ...]
    scenarios: tuple[VerifiedScenarioResult, ...]


def _result_payload(result: VerifiedScenarioResult) -> dict[str, object]:
    return {
        "scenario_id": result.scenario_id,
        "input_identity": result.input_identity,
        "initial_ledger_state_id": result.initial_ledger_state_id,
        "final_state_id": result.final_state.state_id,
        "command_ids": tuple(item.command_id for item in result.commands),
        "event_ids": tuple(item.event_id for item in result.events),
        "rule_decisions": result.rule_decisions,
        "transition_ids": tuple(item.transition_id for item in result.transitions),
        "checkpoints": result.checkpoints,
    }


def _prove_ledger_state(state: LedgerState) -> LedgerState:
    """Re-enter every nested public ledger constructor before trusting state_id."""
    return replace(
        state,
        positions=tuple(replace(item, avg_cost=replace(item.avg_cost)) for item in state.positions),
        cash=tuple(replace(item) for item in state.cash),
        pending=tuple(replace(item) for item in state.pending),
        trading_credits=tuple(replace(item) for item in state.trading_credits),
        entitlements=tuple(replace(item) for item in state.entitlements),
        applied_actions=tuple(replace(item) for item in state.applied_actions),
        command_projections=tuple(replace(item) for item in state.command_projections),
    )


def _prove_scenario_result(
    scenario: VerifiedScenarioResult,
    *,
    market_snapshot_ids: tuple[str, ...],
    initial_account_snapshot_id: str,
) -> VerifiedScenarioResult:
    if (
        type(scenario) is not VerifiedScenarioResult
        or not _hex64(scenario.scenario_result_id)
        or type(scenario.scenario_id) is not str
        or not scenario.scenario_id
        or scenario.scenario_id != scenario.scenario_id.strip()
        or any(char in "/\\:%" or ord(char) < 32 for char in scenario.scenario_id)
        or not _hex64(scenario.input_identity)
        or not _hex64(scenario.initial_ledger_state_id)
        or type(scenario.commands) is not tuple
        or type(scenario.events) is not tuple
        or type(scenario.rule_decisions) is not tuple
        or type(scenario.transitions) is not tuple
        or not scenario.transitions
        or type(scenario.checkpoints) is not tuple
        or not scenario.checkpoints
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")

    commands: list[OrderCommand] = []
    for command in scenario.commands:
        if type(command) is not OrderCommand:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        build_order_intent_identity(command.intent)
        build_order_command_identity(command)
        commands.append(replace(command, intent=replace(command.intent)))
    command_ids = tuple(item.command_id for item in commands)
    if len(set(command_ids)) != len(command_ids):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")

    events: list[ExecutionEvent] = []
    for event in scenario.events:
        if type(event) is not ExecutionEvent:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        fees = tuple(
            replace(fee, amount=replace(fee.amount)) for fee in event.fees
        )
        proven_event = replace(event, fees=fees)
        build_execution_event_identity(proven_event)
        if proven_event.command_id not in command_ids:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        events.append(proven_event)
    event_ids = tuple(item.event_id for item in events)
    if (
        len(set(event_ids)) != len(event_ids)
        or {item.command_id for item in events} != set(command_ids)
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")

    decisions: list[RuleDecision] = []
    for decision in scenario.rule_decisions:
        if type(decision) is not RuleDecision:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        proven_decision = replace(decision)
        build_rule_decision_identity(proven_decision)
        decisions.append(proven_decision)

    transitions: list[LedgerTransition] = []
    previous_state_id = scenario.initial_ledger_state_id
    state_by_id: dict[str, LedgerState] = {}
    for transition in scenario.transitions:
        if type(transition) is not LedgerTransition:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        entries = tuple(replace(entry) for entry in transition.entries)
        state = _prove_ledger_state(transition.state)
        proven_transition = replace(transition, state=state, entries=entries)
        if proven_transition.previous_state_id != previous_state_id:
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        previous_state_id = proven_transition.state.state_id
        state_by_id[proven_transition.state.state_id] = proven_transition.state
        transitions.append(proven_transition)
    final_state = _prove_ledger_state(scenario.final_state)
    if (
        previous_state_id != final_state.state_id
        or final_state.origin_account_snapshot_id != initial_account_snapshot_id
        or set(final_state.applied_event_ids) != set(event_ids)
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")

    checkpoints: list[SimulationCheckpoint] = []
    for checkpoint in scenario.checkpoints:
        if (
            type(checkpoint) is not SimulationCheckpoint
            or type(checkpoint.session_date) is not dt.date
            or not _hex64(checkpoint.market_snapshot_id)
            or checkpoint.market_snapshot_id not in market_snapshot_ids
            or not _hex64(checkpoint.ledger_state_id)
            or checkpoint.ledger_state_id not in state_by_id
            or state_by_id[checkpoint.ledger_state_id].as_of_date != checkpoint.session_date
        ):
            _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
        checkpoints.append(replace(checkpoint))
    if (
        tuple(item.session_date for item in checkpoints)
        != tuple(sorted({item.session_date for item in checkpoints}))
        or tuple(item.market_snapshot_id for item in checkpoints) != market_snapshot_ids
        or len({item.market_snapshot_id for item in checkpoints}) != len(checkpoints)
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")

    proven_scenario = replace(
        scenario,
        final_state=final_state,
        commands=tuple(commands),
        events=tuple(events),
        rule_decisions=tuple(decisions),
        transitions=tuple(transitions),
        checkpoints=tuple(checkpoints),
    )
    if proven_scenario.scenario_result_id != _identity(
        "VerifiedScenarioResult", _result_payload(proven_scenario)
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
    return proven_scenario


def _prove_simulation_result_identity(
    result: VerifiedSimulationResult,
) -> VerifiedSimulationResult:
    if (
        type(result) is not VerifiedSimulationResult
        or not _hex64(result.result_id)
        or not _hex64(result.config_id)
        or not _hex64(result.initial_account_snapshot_id)
        or type(result.market_snapshot_ids) is not tuple
        or not result.market_snapshot_ids
        or any(not _hex64(item) for item in result.market_snapshot_ids)
        or len(set(result.market_snapshot_ids)) != len(result.market_snapshot_ids)
        or type(result.scenarios) is not tuple
        or not result.scenarios
        or any(type(item) is not VerifiedScenarioResult for item in result.scenarios)
        or tuple(item.scenario_id for item in result.scenarios)
        != tuple(sorted(item.scenario_id for item in result.scenarios))
        or len({item.scenario_id for item in result.scenarios}) != len(result.scenarios)
    ):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
    scenarios = tuple(
        _prove_scenario_result(
            item,
            market_snapshot_ids=result.market_snapshot_ids,
            initial_account_snapshot_id=result.initial_account_snapshot_id,
        )
        for item in result.scenarios
    )
    if len({item.initial_ledger_state_id for item in scenarios}) != 1:
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
    root_payload = {
        "config_id": result.config_id,
        "initial_account_snapshot_id": result.initial_account_snapshot_id,
        "market_snapshot_ids": result.market_snapshot_ids,
        "scenario_result_ids": tuple(item.scenario_result_id for item in scenarios),
    }
    if result.result_id != _identity("VerifiedSimulationResult", root_payload):
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
    return replace(result, scenarios=scenarios)


def verify_simulation_result_identity(
    result: VerifiedSimulationResult,
) -> VerifiedSimulationResult:
    """Verify B6 result self-consistency without replay inputs or private consumers."""
    failed = False
    proven: VerifiedSimulationResult | None = None
    try:
        proven = _prove_simulation_result_identity(result)
    except Exception:
        failed = True
    if failed or proven is None:
        _fail("EVENT_SIM_RESULT_IDENTITY_INVALID")
    return proven


def _rule_for(config: EventSimulationConfig, intent: OrderIntent) -> SettlementRule:
    matches = tuple(
        item
        for item in config.settlement_rules
        if item.market is intent.market
        and item.quote_currency is intent.quote_currency
        and item.effective_from <= intent.session_date
        and (item.effective_to is None or intent.session_date <= item.effective_to)
    )
    if len(matches) != 1:
        _fail("EVENT_SIM_SETTLEMENT_RULE_MISSING")
    return matches[0]


def _planner_config(config: EventSimulationConfig, identity: str) -> OrderPlannerConfig:
    matches = tuple(item for item in config.planner_configs if item.config_identity == identity)
    if len(matches) != 1:
        _fail("EVENT_SIM_CONFIG_MISMATCH")
    return matches[0]


def _eligible(snapshot: VerifiedMarketSnapshot, plan: OrderPlan) -> bool:
    states = {(item.market, item.symbol) for item in snapshot.states}
    if any((intent.market, intent.symbol) not in states for intent in plan.intents):
        return False
    contexts = {item.route: item for item in snapshot.connect_contexts}
    for intent in plan.intents:
        if intent.market is Market.HK:
            if intent.connect_route is None:
                return False
            context = contexts.get(intent.connect_route)
            if context is None or not (context.mainland_open and context.hong_kong_open):
                return False
    return True


def _decision(
    intent: OrderIntent,
    snapshot: VerifiedMarketSnapshot,
    state: LedgerState,
    planner: OrderPlannerConfig,
) -> RuleDecision:
    market_state = next(
        (item for item in snapshot.states if item.market is intent.market and item.symbol == intent.symbol),
        None,
    )
    if market_state is None:
        _fail("EVENT_SIM_SNAPSHOT_MISSING")
    position = next(
        (item for item in state.positions if item.market is intent.market and item.symbol == intent.symbol),
        None,
    )
    def evaluate() -> RuleDecision:
        if intent.market is Market.HK:
            context = next(item for item in snapshot.connect_contexts if item.route is intent.connect_route)
            rule = next(item for item in planner.connect_rule_configs if item.route is intent.connect_route)
            return evaluate_connect_intent(intent, market_state, position, context, rule)
        return evaluate_a_share_intent(intent, market_state, position, planner.a_share_rule_config)

    return _sanitized("EVENT_SIM_RULE_DRIFT", evaluate)


def _apply(state: LedgerState, transition: LedgerTransition, output: list[LedgerTransition]) -> LedgerState:
    output.append(transition)
    return transition.state


def _prove_account(state: LedgerState, account: AccountSnapshot, at: dt.datetime) -> None:
    _sanitized(
        "EVENT_SIM_ACCOUNT_DRIFT", lambda: build_account_snapshot_identity(account)
    )
    if account.as_of > at or account.positions != state.positions or account.cash != state.cash:
        _fail("EVENT_SIM_ACCOUNT_DRIFT")


def _fill_events(
    *,
    scheduled: ScheduledOrderPlan,
    intent: OrderIntent,
    command: OrderCommand,
    snapshot: VerifiedMarketSnapshot,
    planner: OrderPlannerConfig,
    rule: SettlementRule,
    state: LedgerState,
    transitions: list[LedgerTransition],
) -> tuple[LedgerState, tuple[ExecutionEvent, ...]]:
    broker = f"SIM-{command.command_id[:24]}"
    ledger_fx = (
        None
        if rule.quote_currency is rule.settlement_currency
        else planner.fx_snapshot
    )
    events: list[ExecutionEvent] = []
    accepted = build_execution_event(
        command=command,
        broker_order_id=broker,
        event_type=ExecutionEventType.ACCEPTED,
        occurred_at=snapshot.as_of,
        cumulative_quantity=0,
        last_quantity=0,
        last_price=None,
        fees=(),
        reject_code=None,
    )
    events.append(accepted)
    state = _apply(
        state,
        apply_execution_event(state, command, accepted, rule, ledger_fx),
        transitions,
    )
    specs = tuple(item for item in scheduled.fills if item.intent_id == intent.intent_id)
    prior = 0
    market_state = next(item for item in snapshot.states if item.market is intent.market and item.symbol == intent.symbol)
    for spec in specs:
        valid_limit = (
            spec.last_price <= intent.limit_price
            if intent.side is OrderSide.BUY
            else spec.last_price >= intent.limit_price
        )
        if (
            spec.occurred_at.date() != snapshot.session_date
            or
            spec.occurred_at < snapshot.as_of
            or spec.occurred_at > scheduled.session_close_at
            or spec.cumulative_quantity != prior + spec.last_quantity
            or spec.cumulative_quantity > intent.quantity
            or not valid_limit
            or spec.last_price % market_state.tick_size != 0
            or market_state.limit_down is not None and spec.last_price < market_state.limit_down
            or market_state.limit_up is not None and spec.last_price > market_state.limit_up
        ):
            _fail("EVENT_SIM_FILL_INVALID")
        fees = calculate_execution_cost(
            intent,
            spec.last_price,
            spec.last_quantity,
            planner.execution_cost_schedule,
            planner.fx_snapshot,
        )
        event = build_execution_event(
            command=command,
            broker_order_id=broker,
            event_type=(
                ExecutionEventType.FILL
                if spec.cumulative_quantity == intent.quantity
                else ExecutionEventType.PARTIAL_FILL
            ),
            occurred_at=spec.occurred_at,
            cumulative_quantity=spec.cumulative_quantity,
            last_quantity=spec.last_quantity,
            last_price=spec.last_price,
            fees=fees,
            reject_code=None,
        )
        events.append(event)
        state = _apply(
            state,
            apply_execution_event(state, command, event, rule, ledger_fx),
            transitions,
        )
        prior = spec.cumulative_quantity
    if prior < intent.quantity:
        cancelled = build_execution_event(
            command=command,
            broker_order_id=broker,
            event_type=ExecutionEventType.CANCELLED,
            occurred_at=scheduled.session_close_at,
            cumulative_quantity=prior,
            last_quantity=0,
            last_price=None,
            fees=(),
            reject_code=None,
        )
        events.append(cancelled)
        state = _apply(
            state,
            apply_execution_event(state, command, cancelled, rule, ledger_fx),
            transitions,
        )
    return state, tuple(events)


def _simulate_scenario(
    scenario: SimulationScenarioPlans,
    snapshots: tuple[VerifiedMarketSnapshot, ...],
    initial_account: AccountSnapshot,
    config: EventSimulationConfig,
) -> VerifiedScenarioResult:
    state = build_ledger_state(initial_account, as_of_date=initial_account.as_of.date())
    initial_state_id = state.state_id
    scheduled_by_snapshot = {item.plan.market_snapshot_id: item for item in scenario.scheduled_plans}
    commands: list[OrderCommand] = []
    events: list[ExecutionEvent] = []
    decisions: list[RuleDecision] = []
    transitions: list[LedgerTransition] = []
    checkpoints: list[SimulationCheckpoint] = []
    for snapshot in snapshots:
        state = _apply(state, advance_ledger_state(state, through_date=snapshot.session_date), transitions)
        recognized = recognize_ex_date_entitlements(date=snapshot.session_date, positions=state.entitlements)
        state = _apply(state, apply_corporate_action(state, recognized), transitions)
        settled = settle_due_entitlements(date=snapshot.session_date, positions=state.entitlements)
        state = _apply(state, apply_corporate_action(state, settled), transitions)
        scheduled = scheduled_by_snapshot.get(snapshot.snapshot_id)
        if scheduled is not None:
            if (
                scheduled.session_date != snapshot.session_date
                or scheduled.session_close_at.date() != snapshot.session_date
                or any(
                    item.session_date != snapshot.session_date
                    for item in scheduled.plan.intents
                )
                or not scheduled.signal_known_at
                < snapshot.as_of
                <= scheduled.session_close_at
            ):
                _fail("EVENT_SIM_TEMPORAL_LEAKAGE")
            eligible = next(
                (
                    item
                    for item in snapshots
                    if item.as_of > scheduled.signal_known_at and _eligible(item, scheduled.plan)
                ),
                None,
            )
            if eligible is None or eligible.snapshot_id != snapshot.snapshot_id:
                _fail("EVENT_SIM_TEMPORAL_LEAKAGE")
            _prove_account(state, scheduled.planned_account, snapshot.as_of)
            planner = _planner_config(config, scheduled.plan.config_identity)
            decisions.extend(scheduled.plan.rejections)
            known_intents = {item.intent_id for item in scheduled.plan.intents}
            if any(item.intent_id not in known_intents for item in scheduled.fills):
                _fail("EVENT_SIM_FILL_INVALID")
            for intent in scheduled.plan.intents:
                decision = _decision(intent, snapshot, state, planner)
                decisions.append(decision)
                if not decision.accepted:
                    if any(item.intent_id == intent.intent_id for item in scheduled.fills):
                        _fail("EVENT_SIM_RULE_DRIFT")
                    continue
                command = build_order_command(intent=intent, mode=ExecutionMode.PAPER)
                commands.append(command)
                rule = _rule_for(config, intent)
                state, generated = _fill_events(
                    scheduled=scheduled,
                    intent=intent,
                    command=command,
                    snapshot=snapshot,
                    planner=planner,
                    rule=rule,
                    state=state,
                    transitions=transitions,
                )
                events.extend(generated)
        quantities = {item.symbol: item.quantity for item in state.positions}
        def apply_actions() -> LedgerState:
            captured = capture_record_close_entitlements(
                date=snapshot.session_date,
                positions=state.entitlements,
                total_quantities=quantities,
                corporate_actions=config.corporate_actions,
                sh_sessions=config.sh_sessions,
                terminal_valuation_date=config.terminal_date,
            )
            capture = build_capture_entitlement_transition(
                date=snapshot.session_date, before=state.entitlements, after=captured
            )
            return _apply(state, apply_corporate_action(state, capture), transitions)

        state = _sanitized("EVENT_SIM_CORPORATE_ACTION_INVALID", apply_actions)
        checkpoints.append(SimulationCheckpoint(snapshot.session_date, snapshot.snapshot_id, state.state_id))
    state = _apply(state, advance_ledger_state(state, through_date=config.terminal_date), transitions)
    provisional = VerifiedScenarioResult(
        "0" * 64,
        scenario.scenario_id,
        scenario.scenario_input_id,
        initial_state_id,
        state,
        tuple(commands),
        tuple(events),
        tuple(decisions),
        tuple(transitions),
        tuple(checkpoints),
    )
    return VerifiedScenarioResult(
        _identity("VerifiedScenarioResult", _result_payload(provisional)),
        scenario.scenario_id,
        scenario.scenario_input_id,
        initial_state_id,
        state,
        tuple(commands),
        tuple(events),
        tuple(decisions),
        tuple(transitions),
        tuple(checkpoints),
    )


def simulate_order_plans(
    plans: tuple[SimulationScenarioPlans, ...],
    snapshots: tuple[VerifiedMarketSnapshot, ...],
    initial_account: AccountSnapshot,
    config: EventSimulationConfig,
) -> VerifiedSimulationResult:
    """Run isolated scenario streams through shared rule, cost and ledger APIs."""
    failed = False
    try:
        _prove_config(config)
        build_account_snapshot_identity(initial_account)
        if (
            type(plans) is not tuple
            or not plans
            or any(type(item) is not SimulationScenarioPlans for item in plans)
            or tuple(sorted(plans, key=lambda item: item.scenario_id)) != plans
            or len({item.scenario_id for item in plans}) != len(plans)
            or type(snapshots) is not tuple
            or not snapshots
            or any(type(item) is not VerifiedMarketSnapshot for item in snapshots)
            or tuple(item.session_date for item in snapshots) != config.event_sessions
            or tuple(sorted(snapshots, key=lambda item: item.as_of)) != snapshots
            or len({item.snapshot_id for item in snapshots}) != len(snapshots)
        ):
            _fail("EVENT_SIM_INPUT_INVALID")
        for snapshot in snapshots:
            build_verified_market_snapshot_identity(snapshot)
        for scenario in plans:
            _prove_scenario(scenario)
        snapshot_ids = {item.snapshot_id for item in snapshots}
        if any(
            scheduled.plan.market_snapshot_id not in snapshot_ids
            for scenario in plans
            for scheduled in scenario.scheduled_plans
        ):
            _fail("EVENT_SIM_SNAPSHOT_MISSING")
        scenario_results = tuple(
            _simulate_scenario(item, snapshots, initial_account, config) for item in plans
        )
        root_payload = {
            "config_id": config.config_id,
            "initial_account_snapshot_id": initial_account.snapshot_id,
            "market_snapshot_ids": tuple(item.snapshot_id for item in snapshots),
            "scenario_result_ids": tuple(item.scenario_result_id for item in scenario_results),
        }
        return VerifiedSimulationResult(
            _identity("VerifiedSimulationResult", root_payload),
            config.config_id,
            initial_account.snapshot_id,
            tuple(item.snapshot_id for item in snapshots),
            scenario_results,
        )
    except EventSimulationError:
        raise
    except Exception:
        failed = True
    if failed:
        _fail("EVENT_SIM_INPUT_INVALID")
    _fail("EVENT_SIM_INPUT_INVALID")


def verify_simulation_result(
    result: VerifiedSimulationResult,
    plans: tuple[SimulationScenarioPlans, ...],
    snapshots: tuple[VerifiedMarketSnapshot, ...],
    initial_account: AccountSnapshot,
    config: EventSimulationConfig,
) -> VerifiedSimulationResult:
    """Re-run the complete pure replay and reject any result drift."""
    expected = simulate_order_plans(plans, snapshots, initial_account, config)
    if type(result) is not VerifiedSimulationResult or result != expected:
        _fail("EVENT_SIM_RESULT_MISMATCH")
    return expected


__all__ = [
    "EventSimulationConfig",
    "EventSimulationError",
    "ScheduledOrderPlan",
    "SimulationCheckpoint",
    "SimulationFillSpec",
    "SimulationScenarioPlans",
    "VerifiedScenarioResult",
    "VerifiedSimulationResult",
    "build_event_simulation_config",
    "build_scheduled_order_plan",
    "build_simulation_scenario_plans",
    "simulate_order_plans",
    "verify_simulation_result",
    "verify_simulation_result_identity",
]
