"""Pure A-share target-to-order and fee contracts for M3 G7D."""

from __future__ import annotations

from quant.domain import AShareBoard, ExecutionRejectReason

from quant.backtest.a_share_execution_contracts import (
    AShareExecutionError,
    AShareFeeComponents,
    AShareOrderQuantityRule,
    AccountPosition,
    BuyAllocation,
    ExecutionBatch,
    ExecutionFill,
    ExecutionRejection,
    PositionBook,
    TargetOrderIntent,
)
from quant.backtest.a_share_execution_fees import compute_a_share_fee_components
from quant.backtest.a_share_execution_formal_facts import (
    AShareMarketFactsFreshVerificationContext,
    AShareMarketFactsIdentityV1,
    FormalAShareMarketFactArtifactDigestV1,
    FormalAShareMarketFactsIdentityV1,
    VerifiedAShareMarketFacts,
    build_a_share_market_facts,
    build_open_execution_states,
    load_verified_a_share_market_facts,
)
from quant.backtest.a_share_execution_formal_matching import (
    AShareSessionExecutionTransition,
    build_formal_a_share_open_execution_states,
    execute_formal_a_share_session,
    resolve_formal_a_share_order_quantity_rule,
)
from quant.backtest.a_share_execution_matching import (
    allocate_buy_lots,
    build_target_order_intents,
    execute_sell_intents,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    resolve_a_share_order_quantity_rule,
)
from quant.backtest.a_share_execution_reporting import (
    AShareRuleConfig,
    AShareRuleInputError,
    build_a_share_rule_config,
    evaluate_a_share_intent,
)

__all__ = [
    "AShareBoard",
    "AShareExecutionError",
    "ExecutionRejectReason",
    "AShareSessionExecutionTransition",
    "AShareMarketFactsFreshVerificationContext",
    "AShareRuleConfig",
    "AShareRuleInputError",
    "AShareFeeComponents",
    "AShareMarketFactsIdentityV1",
    "AShareOrderQuantityRule",
    "AccountPosition",
    "BuyAllocation",
    "ExecutionBatch",
    "ExecutionFill",
    "ExecutionRejection",
    "FormalAShareMarketFactArtifactDigestV1",
    "FormalAShareMarketFactsIdentityV1",
    "PositionBook",
    "TargetOrderIntent",
    "allocate_buy_lots",
    "build_a_share_market_facts",
    "build_a_share_rule_config",
    "build_formal_a_share_open_execution_states",
    "build_open_execution_states",
    "build_target_order_intents",
    "compute_a_share_fee_components",
    "evaluate_a_share_intent",
    "execute_formal_a_share_session",
    "execute_sell_intents",
    "largest_valid_buy_quantity",
    "largest_valid_sell_quantity",
    "load_verified_a_share_market_facts",
    "resolve_formal_a_share_order_quantity_rule",
    "resolve_a_share_order_quantity_rule",
    "VerifiedAShareMarketFacts",
]
