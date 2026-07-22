"""使用显式市场状态的成交准入规则。"""

from dataclasses import dataclass

from quant.domain.enums import ExecutionRejectReason, OrderSide


@dataclass(frozen=True)
class DailyMarketState:
    """执行时点已知的停牌与涨跌停状态，不从缺失行情隐式推断。"""

    suspended: bool = False
    at_upper_limit: bool = False
    at_lower_limit: bool = False

    def __post_init__(self) -> None:
        if self.at_upper_limit and self.at_lower_limit:
            raise ValueError("证券不能同时处于涨停和跌停")


def execution_reject_reason(
    *,
    side: OrderSide,
    quantity: int,
    settled_quantity: int,
    state: DailyMarketState,
    enforce_t_plus_one: bool,
) -> ExecutionRejectReason | None:
    """返回订单不可成交的首个确定原因；可成交时返回 ``None``。"""
    if quantity <= 0:
        raise ValueError("委托数量必须大于 0")
    if settled_quantity < 0:
        raise ValueError("可卖数量不得为负")
    if state.suspended:
        return ExecutionRejectReason.SUSPENDED
    if side is OrderSide.BUY and state.at_upper_limit:
        return ExecutionRejectReason.BUY_AT_UPPER_LIMIT
    if side is OrderSide.SELL and state.at_lower_limit:
        return ExecutionRejectReason.SELL_AT_LOWER_LIMIT
    if (
        side is OrderSide.SELL
        and enforce_t_plus_one
        and quantity > settled_quantity
    ):
        return ExecutionRejectReason.T_PLUS_ONE
    return None
