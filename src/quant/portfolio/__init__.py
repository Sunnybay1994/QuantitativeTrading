"""组合构建:约束(个股/行业上限、换手惩罚、现金缓冲)与目标订单生成(M4 里程碑)。

输入:各策略 target_weight + 当前持仓;输出:合并后的目标仓位快照与差量订单建议。
"""

from quant.portfolio.order_planner import (
    OrderPlannerConfig,
    OrderPlannerError,
    OrderPlanTarget,
    build_order_plan,
    build_order_planner_config,
)
from quant.portfolio.selection import (
    retain_ranked_target_selection,
    scale_target_weights_to_volatility,
)

__all__ = [
    "OrderPlannerConfig",
    "OrderPlannerError",
    "OrderPlanTarget",
    "build_order_plan",
    "build_order_planner_config",
    "retain_ranked_target_selection",
    "scale_target_weights_to_volatility",
]
