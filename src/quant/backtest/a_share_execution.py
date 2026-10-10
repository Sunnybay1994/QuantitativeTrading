"""Pure A-share target-to-order and fee contracts for M3 G7D.

Facade over split modules. Capability tokens bind to this module name so
``importlib.reload`` rotates signing keys the same way the former monolith did.
"""

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
from quant.backtest.a_share_execution_formal_decimal import (
    _formal_multiply,
    _formal_reference_opens_sha256,
)
from quant.backtest.a_share_execution_formal_fact_specs import (
    _FORMAL_CAPABILITY_FRAME_SLOTS,
    _FORMAL_FACT_SPECS,
)
from quant.backtest.a_share_execution_formal_facts import (
    AShareMarketFactsFreshVerificationContext,
    AShareMarketFactsIdentityV1,
    FormalAShareMarketFactArtifactDigestV1,
    FormalAShareMarketFactsIdentityV1,
    _PathEntity,
    _event_set_sha256,
    _formal_capability_content,
    _formal_fact_digests,
    _partial_open_status,
    _read_formal_fact_files,
    _select_and_validate_formal_facts,
    _snapshot_directory,
    _snapshot_regular_file,
    _validate_formal_facts_outer,
    build_a_share_market_facts,
    build_open_execution_states,
    rebind_capability_for_a_share_execution,
)
from quant.backtest.a_share_execution_formal_matching import (
    AShareSessionExecutionTransition,
    build_formal_a_share_open_execution_states,
    execute_formal_a_share_session,
    resolve_formal_a_share_order_quantity_rule,
)
from quant.backtest.a_share_execution_formal_open import _valid_buy_quantities
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
from quant.backtest.a_share_plan import verify_backtest_plan_artifact
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_release import verify_g1_release

# Rotate / bind capability on every import (including importlib.reload).
VerifiedAShareMarketFacts, load_verified_a_share_market_facts = (
    rebind_capability_for_a_share_execution()
)
# Keep prepare lookup on this module for public_loader monkeypatch resolution.
from quant.backtest.a_share_execution_formal_facts import (  # noqa: E402
    _prepare_verified_a_share_market_facts,
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
    "clean_table_content_sha256",
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
    "verify_backtest_plan_artifact",
    "verify_g1_release",
]
