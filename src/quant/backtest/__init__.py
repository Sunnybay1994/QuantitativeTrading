"""统一市场约束回测(M2/M4 里程碑)。

A 股:T+1、涨跌停不可成交、停牌、整手、佣金/印花税/过户费。
港股通:T+0、board lot、碎股只卖、费用、额度与可交易日。
所有候选策略(含 Qlib/vectorbt 产出)必须经此层准入复核。
"""

from quant.backtest.timing import schedule_next_trading_day
from quant.backtest.costs import AShareCostModel, EtfCostModel
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
from quant.backtest.simulator import SimulationResult, simulate_etf_targets

__all__ = [
    "AShareCostModel",
    "ConnectRuleConfig",
    "ConnectRuleInputError",
    "DailyMarketState",
    "DailySimulationResult",
    "EtfCostModel",
    "SimulationResult",
    "build_connect_rule_config",
    "evaluate_connect_intent",
    "execution_reject_reason",
    "schedule_next_trading_day",
    "simulate_etf_targets",
    "simulate_daily_targets",
]
