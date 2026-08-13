"""统一市场约束回测(M2/M4 里程碑)。

A 股:T+1、涨跌停不可成交、停牌、整手、佣金/印花税/过户费。
港股通:T+0、board lot、碎股只卖、费用、额度与可交易日。
所有候选策略(含 Qlib/vectorbt 产出)必须经此层准入复核。
"""

import importlib
from typing import TYPE_CHECKING, Any

from quant.backtest.timing import schedule_next_trading_day
from quant.backtest.a_share_execution import (
    AccountPosition,
    AShareExecutionError,
    AShareMarketFactsFreshVerificationContext,
    AShareFeeComponents,
    AShareMarketFactsIdentityV1,
    AShareOrderQuantityRule,
    AShareRuleConfig,
    AShareRuleInputError,
    AShareSessionExecutionTransition,
    BuyAllocation,
    ExecutionBatch,
    ExecutionFill,
    ExecutionRejection,
    FormalAShareMarketFactArtifactDigestV1,
    FormalAShareMarketFactsIdentityV1,
    TargetOrderIntent,
    allocate_buy_lots,
    build_a_share_market_facts,
    build_a_share_rule_config,
    build_formal_a_share_open_execution_states,
    build_open_execution_states,
    build_target_order_intents,
    compute_a_share_fee_components,
    evaluate_a_share_intent,
    execute_sell_intents,
    execute_formal_a_share_session,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    load_verified_a_share_market_facts,
    resolve_formal_a_share_order_quantity_rule,
    resolve_a_share_order_quantity_rule,
    VerifiedAShareMarketFacts,
)
from quant.backtest.a_share_plan import (
    AShareCostPeriod,
    BacktestPlanFreshVerificationContext,
    BacktestPlanManifestV1,
    BacktestPlanUpstreamPaths,
    BacktestWindow,
    build_backtest_plan_artifact,
    build_development_example_backtest_plan_artifact,
    read_backtest_plan_manifest,
    verify_backtest_plan_artifact,
    verify_development_example_backtest_plan_artifact,
)
from quant.backtest.costs import (
    AShareCostModel,
    EtfCostModel,
    ExecutionCostError,
    ExecutionCostPeriod,
    ExecutionCostSchedule,
    build_execution_cost_schedule,
    calculate_execution_cost,
)
from quant.backtest.fx import (
    FxContractError,
    FxRate,
    FxSnapshot,
    build_fx_snapshot,
    convert_money,
    require_fx_snapshot_current,
)
from quant.backtest.corporate_actions import (
    AShareEntitlementError,
    AShareEntitlementReplayState,
    AShareEntitlementReplayTransition,
    EntitlementPosition,
    EntitlementPosting,
    EntitlementReplayPhase,
    EntitlementTransition,
    advance_formal_a_share_entitlements_pre_open,
    capture_formal_a_share_entitlements_record_close,
    capture_record_close_entitlements,
    initialize_formal_a_share_entitlement_replay,
    mark_full_day_event_from_factor,
    recognize_ex_date_entitlements,
    settle_due_entitlements,
)
from quant.backtest.connect_execution import (
    ConnectRuleConfig,
    ConnectRuleInputError,
    build_connect_rule_config,
    evaluate_connect_intent,
)
from quant.backtest.rules import DailyMarketState, execution_reject_reason
from quant.backtest.daily_simulator import (
    DailySimulationResult,
    simulate_daily_targets,
)
from quant.backtest.simulator import (
    EtfDiagnosticSimulationResult,
    SimulationResult,
    simulate_etf_targets,
    simulate_etf_targets_with_diagnostics,
)
from quant.backtest.a_share_simulator import (
    AShareSimulationError,
    AShareSimulationFreshVerificationContext,
    AShareSimulationResult,
    simulate_a_share_scenario,
    simulate_formal_a_share_scenario,
)
from quant.backtest.a_share_reporting import (
    AShareBacktestArtifactError,
    BacktestArtifactFreshVerificationContext,
    BacktestArtifactUpstreamPaths,
    FormalBacktestArtifactUpstreamPaths,
    backtest_artifact_input_paths,
    backtest_artifact_output_relative_paths,
    build_backtest_artifact,
    build_development_example_backtest_artifact,
    read_backtest_bundle_manifest,
    read_backtest_scenario_manifest,
    verify_backtest_artifact,
    verify_backtest_build_output,
    verify_development_example_backtest_artifact,
)
if TYPE_CHECKING:
    from quant.backtest.event_simulator import (
        SimulationReplayInputs,
        VerifiedSimulationResult,
    )

_EVENT_SIMULATOR_EXPORTS = frozenset({
    "SimulationReplayInputs",
    "VerifiedSimulationResult",
    "verify_simulation_result_identity",
})


def __getattr__(name: str) -> Any:
    """Load the event replay API without creating a portfolio import cycle."""
    if name not in _EVENT_SIMULATOR_EXPORTS:
        raise AttributeError(name)
    module = importlib.import_module("quant.backtest.event_simulator")
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "AccountPosition",
    "AShareExecutionError",
    "AShareMarketFactsFreshVerificationContext",
    "AShareFeeComponents",
    "AShareMarketFactsIdentityV1",
    "AShareOrderQuantityRule",
    "AShareRuleConfig",
    "AShareRuleInputError",
    "AShareSessionExecutionTransition",
    "AShareSimulationError",
    "AShareSimulationFreshVerificationContext",
    "AShareSimulationResult",
    "AShareBacktestArtifactError",
    "AShareCostModel",
    "AShareCostPeriod",
    "AShareEntitlementError",
    "AShareEntitlementReplayState",
    "AShareEntitlementReplayTransition",
    "BacktestPlanFreshVerificationContext",
    "BacktestPlanManifestV1",
    "BacktestPlanUpstreamPaths",
    "BacktestWindow",
    "BacktestArtifactUpstreamPaths",
    "FormalBacktestArtifactUpstreamPaths",
    "BacktestArtifactFreshVerificationContext",
    "backtest_artifact_input_paths",
    "backtest_artifact_output_relative_paths",
    "BuyAllocation",
    "ConnectRuleConfig",
    "ConnectRuleInputError",
    "DailyMarketState",
    "DailySimulationResult",
    "EtfDiagnosticSimulationResult",
    "EtfCostModel",
    "ExecutionCostError",
    "ExecutionCostPeriod",
    "ExecutionCostSchedule",
    "FxContractError",
    "FxRate",
    "FxSnapshot",
    "EntitlementPosition",
    "EntitlementPosting",
    "EntitlementReplayPhase",
    "EntitlementTransition",
    "advance_formal_a_share_entitlements_pre_open",
    "capture_formal_a_share_entitlements_record_close",
    "ExecutionBatch",
    "ExecutionFill",
    "ExecutionRejection",
    "FormalAShareMarketFactArtifactDigestV1",
    "FormalAShareMarketFactsIdentityV1",
    "SimulationResult",
    "SimulationReplayInputs",
    "VerifiedSimulationResult",
    "TargetOrderIntent",
    "allocate_buy_lots",
    "build_a_share_market_facts",
    "build_a_share_rule_config",
    "build_formal_a_share_open_execution_states",
    "build_backtest_plan_artifact",
    "build_connect_rule_config",
    "build_development_example_backtest_plan_artifact",
    "build_development_example_backtest_artifact",
    "build_backtest_artifact",
    "build_execution_cost_schedule",
    "build_fx_snapshot",
    "build_open_execution_states",
    "build_target_order_intents",
    "capture_record_close_entitlements",
    "initialize_formal_a_share_entitlement_replay",
    "compute_a_share_fee_components",
    "calculate_execution_cost",
    "convert_money",
    "evaluate_a_share_intent",
    "evaluate_connect_intent",
    "execution_reject_reason",
    "execute_sell_intents",
    "execute_formal_a_share_session",
    "mark_full_day_event_from_factor",
    "largest_valid_buy_quantity",
    "largest_valid_sell_quantity",
    "load_verified_a_share_market_facts",
    "read_backtest_plan_manifest",
    "read_backtest_bundle_manifest",
    "read_backtest_scenario_manifest",
    "recognize_ex_date_entitlements",
    "resolve_a_share_order_quantity_rule",
    "resolve_formal_a_share_order_quantity_rule",
    "require_fx_snapshot_current",
    "schedule_next_trading_day",
    "simulate_etf_targets",
    "simulate_a_share_scenario",
    "simulate_formal_a_share_scenario",
    "simulate_etf_targets_with_diagnostics",
    "simulate_daily_targets",
    "settle_due_entitlements",
    "verify_development_example_backtest_plan_artifact",
    "verify_backtest_plan_artifact",
    "verify_development_example_backtest_artifact",
    "verify_simulation_result_identity",
    "verify_backtest_artifact",
    "verify_backtest_build_output",
    "VerifiedAShareMarketFacts",
]
