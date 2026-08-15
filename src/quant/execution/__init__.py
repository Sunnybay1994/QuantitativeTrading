"""执行面:纸面账户、OMS 状态机、事前风控、券商通道 Gateway(M4/M5 里程碑)。

券商 API(QMT/PTrade/MiniQMT 存量)只允许出现在本包的 Gateway 适配器内部;
外部只见标准订单/查询命令与标准化回报事件。
程序化交易合规(先报告后交易、当日下单/撤单次数上限)在事前风控中实现。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from quant.execution.config import (
    ConfigIssue,
    TradingConfig,
    TradingConfigError,
    load_trading_config,
    trading_config_identity,
)
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    CancelCommand,
    ContractError,
    ExecutionEvent,
    FeeComponent,
    MoneyAmount,
    OrderCommand,
    OrderIntent,
    OrderIntentSpec,
    OrderPlan,
    OrderPlanDecision,
    OrderPlanReasonClass,
    PositionBalance,
    RuleDecision,
    SymbolMarketState,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
    build_account_snapshot,
    build_account_snapshot_identity,
    build_cash_balance,
    build_cash_balance_identity,
    build_cancel_command,
    build_cancel_command_identity,
    build_execution_event,
    build_execution_event_identity,
    build_fee_component,
    build_fee_component_identity,
    build_money_amount,
    build_money_amount_identity,
    build_order_command,
    build_order_command_identity,
    build_order_intent,
    build_order_intent_identity,
    build_order_plan,
    build_order_plan_decision,
    build_order_plan_identity,
    build_position_balance,
    build_position_balance_identity,
    build_rule_decision,
    build_rule_decision_identity,
    build_symbol_market_state,
    build_symbol_market_state_identity,
    build_verified_connect_market_context,
    build_verified_connect_market_context_identity,
    build_verified_market_snapshot,
    build_verified_market_snapshot_identity,
)
from quant.execution.ports import (
    AccountSnapshotRepository,
    ConnectMarketContextRepository,
    MarketDataRepository,
)

if TYPE_CHECKING:
    from quant.execution.paper_formal_daily import (
        FormalPaperCandidateTargetLoader,
        FormalPaperDailyInputError,
        FormalPaperDailyRunnerError,
        FormalPaperDailySourcePlan,
        FormalPaperPlanningLoader,
        build_formal_paper_daily_dependencies,
        load_formal_paper_daily_source_plan,
        publish_formal_paper_opening_market_input,
        run_formal_paper_daily_operator,
        run_formal_paper_daily_read_only,
    )
    from quant.execution.paper_formal_ledger import (
        FormalPaperLedgerContextError,
        VerifiedFormalPaperLedgerContextProvider,
        load_verified_formal_paper_ledger_context_provider,
        verify_existing_formal_paper_ledger_context_provider,
    )
    from quant.execution.paper_formal_service import (
        FormalPaperServiceError,
        VerifiedFormalPaperServiceComposition,
        open_verified_formal_paper_service_composition,
        verify_existing_formal_paper_service_composition,
    )
    from quant.execution.paper_formal_schedule import (
        FormalPaperScheduleError,
        VerifiedFormalPaperSoakSchedule,
        build_verified_formal_paper_soak_schedule,
        verify_existing_formal_paper_soak_schedule,
    )
    from quant.execution.paper_formal_execution_store import (
        FormalPaperExecutionStoreError,
        VerifiedFormalPaperExecutionStoreCapability,
        initialize_verified_formal_paper_execution_store,
        open_verified_formal_paper_execution_store,
        verify_existing_formal_paper_execution_store_capability,
    )
    from quant.execution.paper_formal_gateway import (
        FormalPaperGatewayError,
        open_verified_formal_paper_gateway_factory,
    )
    from quant.execution.paper_formal_broker_snapshot import (
        FormalPaperBrokerSnapshotError,
        open_verified_formal_paper_broker_snapshot_port,
    )
    from quant.execution.paper_formal_broker_store import (
        FormalPaperBrokerStoreError,
        VerifiedFormalPaperBrokerStoreCapability,
        initialize_verified_formal_paper_broker_store,
        open_verified_formal_paper_broker_store,
        verify_existing_formal_paper_broker_store_capability,
    )
    from quant.execution.soak import (
        FaultDrillReceipt,
        REQUIRED_FAULT_DRILLS,
        SoakAppendAnchor,
        SoakError,
        SoakEvidenceKind,
        SoakGateDecision,
        SoakRunManifest,
        SoakSessionReceipt,
        VerifiedDevelopmentSoakEvidence,
        VerifiedPaperSoakEvidence,
        append_fault_drill,
        append_soak_session,
        build_soak_run,
        decide_soak_gate,
        expected_schedule_identity,
        verify_soak_evidence,
    )

_SOAK_EXPORTS = frozenset(
    {
        "FaultDrillReceipt",
        "REQUIRED_FAULT_DRILLS",
        "SoakAppendAnchor",
        "SoakError",
        "SoakEvidenceKind",
        "SoakGateDecision",
        "SoakRunManifest",
        "SoakSessionReceipt",
        "VerifiedDevelopmentSoakEvidence",
        "VerifiedPaperSoakEvidence",
        "append_fault_drill",
        "append_soak_session",
        "build_soak_run",
        "decide_soak_gate",
        "expected_schedule_identity",
        "verify_soak_evidence",
    }
)

_FORMAL_STORE_EXPORTS = frozenset(
    {
        "FormalPaperBrokerStoreError",
        "VerifiedFormalPaperBrokerStoreCapability",
        "initialize_verified_formal_paper_broker_store",
        "open_verified_formal_paper_broker_store",
        "verify_existing_formal_paper_broker_store_capability",
    }
)

_FORMAL_SNAPSHOT_EXPORTS = frozenset(
    {
        "FormalPaperBrokerSnapshotError",
        "open_verified_formal_paper_broker_snapshot_port",
    }
)

_FORMAL_GATEWAY_EXPORTS = frozenset(
    {
        "FormalPaperGatewayError",
        "open_verified_formal_paper_gateway_factory",
    }
)

_FORMAL_EXECUTION_STORE_EXPORTS = frozenset(
    {
        "FormalPaperExecutionStoreError",
        "VerifiedFormalPaperExecutionStoreCapability",
        "initialize_verified_formal_paper_execution_store",
        "open_verified_formal_paper_execution_store",
        "verify_existing_formal_paper_execution_store_capability",
    }
)

_FORMAL_LEDGER_EXPORTS = frozenset(
    {
        "FormalPaperLedgerContextError",
        "VerifiedFormalPaperLedgerContextProvider",
        "load_verified_formal_paper_ledger_context_provider",
        "verify_existing_formal_paper_ledger_context_provider",
    }
)

_FORMAL_SERVICE_EXPORTS = frozenset(
    {
        "FormalPaperServiceError",
        "VerifiedFormalPaperServiceComposition",
        "open_verified_formal_paper_service_composition",
        "verify_existing_formal_paper_service_composition",
    }
)

_FORMAL_SCHEDULE_EXPORTS = frozenset(
    {
        "FormalPaperScheduleError",
        "VerifiedFormalPaperSoakSchedule",
        "build_verified_formal_paper_soak_schedule",
        "verify_existing_formal_paper_soak_schedule",
    }
)

_FORMAL_DAILY_EXPORTS = frozenset(
    {
        "FormalPaperCandidateTargetLoader",
        "FormalPaperDailyInputError",
        "FormalPaperDailyRunnerError",
        "FormalPaperDailySourcePlan",
        "FormalPaperPlanningLoader",
        "build_formal_paper_daily_dependencies",
        "load_formal_paper_daily_source_plan",
        "publish_formal_paper_opening_market_input",
        "run_formal_paper_daily_operator",
        "run_formal_paper_daily_read_only",
    }
)


def __getattr__(name: str) -> Any:
    """Resolve P8 exports without pulling reporting/backtest at package import."""
    if name in _FORMAL_DAILY_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_daily"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_SCHEDULE_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_schedule"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_SERVICE_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_service"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_LEDGER_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_ledger"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_EXECUTION_STORE_EXPORTS:
        value = getattr(
            import_module("quant.execution.paper_formal_execution_store"), name
        )
        globals()[name] = value
        return value
    if name in _FORMAL_GATEWAY_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_gateway"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_SNAPSHOT_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_broker_snapshot"), name)
        globals()[name] = value
        return value
    if name in _FORMAL_STORE_EXPORTS:
        value = getattr(import_module("quant.execution.paper_formal_broker_store"), name)
        globals()[name] = value
        return value
    if name not in _SOAK_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("quant.execution.soak"), name)
    globals()[name] = value
    return value

__all__ = [
    "AccountSnapshot",
    "AccountSnapshotRepository",
    "CashBalance",
    "CancelCommand",
    "ConfigIssue",
    "ConnectMarketContextRepository",
    "ContractError",
    "ExecutionEvent",
    "FeeComponent",
    "FaultDrillReceipt",
    "FormalPaperBrokerSnapshotError",
    "FormalPaperBrokerStoreError",
    "FormalPaperCandidateTargetLoader",
    "FormalPaperDailyInputError",
    "FormalPaperDailyRunnerError",
    "FormalPaperDailySourcePlan",
    "FormalPaperExecutionStoreError",
    "FormalPaperGatewayError",
    "FormalPaperLedgerContextError",
    "FormalPaperServiceError",
    "FormalPaperScheduleError",
    "FormalPaperPlanningLoader",
    "MarketDataRepository",
    "MoneyAmount",
    "OrderCommand",
    "OrderIntent",
    "OrderIntentSpec",
    "OrderPlan",
    "OrderPlanDecision",
    "OrderPlanReasonClass",
    "PositionBalance",
    "REQUIRED_FAULT_DRILLS",
    "RuleDecision",
    "SoakError",
    "SoakAppendAnchor",
    "SoakEvidenceKind",
    "SoakGateDecision",
    "SoakRunManifest",
    "SoakSessionReceipt",
    "SymbolMarketState",
    "TradingConfig",
    "TradingConfigError",
    "VerifiedConnectMarketContext",
    "VerifiedFormalPaperExecutionStoreCapability",
    "VerifiedFormalPaperLedgerContextProvider",
    "VerifiedFormalPaperServiceComposition",
    "VerifiedFormalPaperSoakSchedule",
    "VerifiedDevelopmentSoakEvidence",
    "VerifiedFormalPaperBrokerStoreCapability",
    "VerifiedMarketSnapshot",
    "VerifiedPaperSoakEvidence",
    "append_fault_drill",
    "append_soak_session",
    "build_account_snapshot",
    "build_account_snapshot_identity",
    "build_cash_balance",
    "build_cash_balance_identity",
    "build_cancel_command",
    "build_cancel_command_identity",
    "build_formal_paper_daily_dependencies",
    "build_execution_event",
    "build_execution_event_identity",
    "build_fee_component",
    "build_fee_component_identity",
    "build_money_amount",
    "build_money_amount_identity",
    "build_order_command",
    "build_order_command_identity",
    "build_order_intent",
    "build_order_intent_identity",
    "build_order_plan",
    "build_order_plan_decision",
    "build_order_plan_identity",
    "build_position_balance",
    "build_position_balance_identity",
    "build_rule_decision",
    "build_rule_decision_identity",
    "build_soak_run",
    "build_symbol_market_state",
    "build_symbol_market_state_identity",
    "build_verified_connect_market_context",
    "build_verified_connect_market_context_identity",
    "build_verified_market_snapshot",
    "build_verified_market_snapshot_identity",
    "build_verified_formal_paper_soak_schedule",
    "load_trading_config",
    "load_formal_paper_daily_source_plan",
    "load_verified_formal_paper_ledger_context_provider",
    "initialize_verified_formal_paper_broker_store",
    "initialize_verified_formal_paper_execution_store",
    "open_verified_formal_paper_broker_store",
    "open_verified_formal_paper_broker_snapshot_port",
    "open_verified_formal_paper_gateway_factory",
    "open_verified_formal_paper_execution_store",
    "open_verified_formal_paper_service_composition",
    "publish_formal_paper_opening_market_input",
    "run_formal_paper_daily_operator",
    "run_formal_paper_daily_read_only",
    "decide_soak_gate",
    "expected_schedule_identity",
    "trading_config_identity",
    "verify_soak_evidence",
    "verify_existing_formal_paper_broker_store_capability",
    "verify_existing_formal_paper_execution_store_capability",
    "verify_existing_formal_paper_ledger_context_provider",
    "verify_existing_formal_paper_service_composition",
    "verify_existing_formal_paper_soak_schedule",
]
