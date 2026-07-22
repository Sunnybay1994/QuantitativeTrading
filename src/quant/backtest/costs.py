"""版本化研究成本模型；数值由 configs/ 提供。"""

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class EtfCostModel:
    commission_rate: float
    commission_min: float
    slippage: float
    effective_from: dt.date

    def __post_init__(self) -> None:
        if self.commission_rate < 0 or self.commission_min < 0 or self.slippage < 0:
            raise ValueError("费率、最低佣金和滑点不得为负")
        if self.slippage >= 1:
            raise ValueError("滑点必须小于 1")

    def execution_price(self, open_price: float, side: str) -> float:
        if side == "BUY":
            return open_price * (1 + self.slippage)
        if side == "SELL":
            return open_price * (1 - self.slippage)
        raise ValueError(f"未知方向: {side}")

    def fee(self, notional: float, date: dt.date) -> float:
        if date < self.effective_from:
            raise ValueError("交易日期早于成本配置有效期")
        return max(notional * self.commission_rate, self.commission_min)


@dataclass(frozen=True)
class AShareCostModel:
    """A 股股票双边佣金/过户费与卖出印花税模型。"""

    commission_rate: float
    commission_min: float
    stamp_tax_sell: float
    transfer_fee: float
    slippage: float
    effective_from: dt.date

    def __post_init__(self) -> None:
        rates = (
            self.commission_rate,
            self.commission_min,
            self.stamp_tax_sell,
            self.transfer_fee,
            self.slippage,
        )
        if any(value < 0 for value in rates):
            raise ValueError("费率、最低佣金和滑点不得为负")
        if self.slippage >= 1:
            raise ValueError("滑点必须小于 1")

    def execution_price(self, open_price: float, side: str) -> float:
        if side == "BUY":
            return open_price * (1 + self.slippage)
        if side == "SELL":
            return open_price * (1 - self.slippage)
        raise ValueError(f"未知方向: {side}")

    def fee(self, notional: float, date: dt.date, side: str) -> float:
        if date < self.effective_from:
            raise ValueError("交易日期早于成本配置有效期")
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"未知方向: {side}")
        commission = max(notional * self.commission_rate, self.commission_min)
        transfer = notional * self.transfer_fee
        stamp = notional * self.stamp_tax_sell if side == "SELL" else 0.0
        return commission + transfer + stamp
