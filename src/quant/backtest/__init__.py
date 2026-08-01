"""统一市场约束回测(M2/M4 里程碑)。

A 股:T+1、涨跌停不可成交、停牌、整手、佣金/印花税/过户费。
港股通:T+0、board lot、碎股只卖、费用、额度与可交易日。
所有候选策略(含 Qlib/vectorbt 产出)必须经此层准入复核。
"""

from quant.backtest.timing import schedule_next_trading_day
from quant.backtest.a_share_execution import (
    AccountPosition,
    AShareFeeComponents,
    AShareOrderQuantityRule,
    BuyAllocation,
    ExecutionBatch,
    ExecutionFill,
    ExecutionRejection,
    TargetOrderIntent,
    build_target_order_intents,
    compute_a_share_fee_components,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    resolve_a_share_order_quantity_rule,
)
from quant.backtest.a_share_plan import (
    AShareCostPeriod,
    BacktestPlanManifestV1,
    BacktestPlanUpstreamPaths,
    BacktestWindow,
    build_development_example_backtest_plan_artifact,
    read_backtest_plan_manifest,
    verify_development_example_backtest_plan_artifact,
)
from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.corporate_actions import (
    EntitlementPosition,
    EntitlementPosting,
    EntitlementTransition,
    capture_record_close_entitlements,
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
from quant.backtest.simulator import SimulationResult, simulate_etf_targets

__all__ = [
    "AccountPosition",
    "AShareFeeComponents",
    "AShareOrderQuantityRule",
    "AShareCostModel",
    "AShareCostPeriod",
    "BacktestPlanManifestV1",
    "BacktestPlanUpstreamPaths",
    "BacktestWindow",
    "BuyAllocation",
    "ConnectRuleConfig",
    "ConnectRuleInputError",
    "DailyMarketState",
    "EtfCostModel",
    "EntitlementPosition",
    "EntitlementPosting",
    "EntitlementTransition",
    "ExecutionBatch",
    "ExecutionFill",
    "ExecutionRejection",
    "SimulationResult",
    "TargetOrderIntent",
    "build_connect_rule_config",
    "build_development_example_backtest_plan_artifact",
    "build_target_order_intents",
    "capture_record_close_entitlements",
    "compute_a_share_fee_components",
    "evaluate_connect_intent",
    "execution_reject_reason",
    "mark_full_day_event_from_factor",
    "largest_valid_buy_quantity",
    "largest_valid_sell_quantity",
    "read_backtest_plan_manifest",
    "recognize_ex_date_entitlements",
    "resolve_a_share_order_quantity_rule",
    "schedule_next_trading_day",
    "simulate_etf_targets",
    "settle_due_entitlements",
    "verify_development_example_backtest_plan_artifact",
]
