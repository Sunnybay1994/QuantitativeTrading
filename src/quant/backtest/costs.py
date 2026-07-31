"""版本化研究成本模型；数值由 configs/ 提供。"""

import datetime as dt
import math
from dataclasses import dataclass


def _require_finite_nonnegative(name: str, value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} 必须是非负有限数")


@dataclass(frozen=True)
class EtfCostModel:
    commission_rate: float
    commission_min: float
    slippage: float
    effective_from: dt.date

    def __post_init__(self) -> None:
        _require_finite_nonnegative("commission_rate", self.commission_rate)
        _require_finite_nonnegative("commission_min", self.commission_min)
        _require_finite_nonnegative("slippage", self.slippage)
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

    def with_execution_cost_multiplier(
        self, multiplier: float
    ) -> "EtfCostModel":
        """返回只缩放执行摩擦的新成本模型。"""
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValueError("成本压力倍数必须是正有限数")
        return EtfCostModel(
            commission_rate=self.commission_rate * multiplier,
            commission_min=self.commission_min * multiplier,
            slippage=self.slippage * multiplier,
            effective_from=self.effective_from,
        )


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
        _require_finite_nonnegative("commission_rate", self.commission_rate)
        _require_finite_nonnegative("commission_min", self.commission_min)
        _require_finite_nonnegative("stamp_tax_sell", self.stamp_tax_sell)
        _require_finite_nonnegative("transfer_fee", self.transfer_fee)
        _require_finite_nonnegative("slippage", self.slippage)
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

    def with_execution_cost_multiplier(
        self, multiplier: float
    ) -> "AShareCostModel":
        """返回只缩放佣金和滑点、不缩放法定税费的新模型。"""
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValueError("成本压力倍数必须是正有限数")
        return AShareCostModel(
            commission_rate=self.commission_rate * multiplier,
            commission_min=self.commission_min * multiplier,
            stamp_tax_sell=self.stamp_tax_sell,
            transfer_fee=self.transfer_fee,
            slippage=self.slippage * multiplier,
            effective_from=self.effective_from,
        )
