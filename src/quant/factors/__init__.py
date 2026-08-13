"""因子工程:因子定义、注册、清洗与标签(M2/M3 里程碑实现)。

输出契约:FactorValueSchema。所有拟合参数(去极值阈值、标准化统计量)
只能在训练期获得。
"""
from quant.factors.risk import compute_realized_volatility_factors_from_prices
from quant.factors.trend import compute_trend_factors, compute_trend_factors_from_prices

__all__ = [
    "compute_realized_volatility_factors_from_prices",
    "compute_trend_factors",
    "compute_trend_factors_from_prices",
]
