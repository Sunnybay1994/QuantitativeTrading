"""因子工程:因子定义、注册、清洗与标签(M2/M3 里程碑实现)。

输出契约:FactorValueSchema。所有拟合参数(去极值阈值、标准化统计量)
只能在训练期获得。
"""
from quant.factors.classic import (
    CLASSIC_FACTOR_NAMES,
    CLASSIC_FACTOR_SPECS,
    ClassicFactorSpec,
    compute_classic_daily_factors,
)
from quant.factors.classic_second_batch import (
    SECOND_BATCH_FACTOR_NAMES,
    SECOND_BATCH_FACTOR_SPECS,
    compute_second_batch_daily_factors,
)
from quant.factors.classic_third_batch import (
    THIRD_BATCH_FACTOR_NAMES,
    THIRD_BATCH_FACTOR_SPECS,
    compute_third_batch_daily_factors,
)
from quant.factors.daily_value import (
    DAILY_VALUE_FACTOR_NAMES,
    DAILY_VALUE_FACTOR_SPECS,
    DailyValueFactorSpec,
    compute_daily_value_factors,
)
from quant.factors.risk import compute_realized_volatility_factors_from_prices
from quant.factors.trend import compute_trend_factors, compute_trend_factors_from_prices

__all__ = [
    "CLASSIC_FACTOR_NAMES",
    "CLASSIC_FACTOR_SPECS",
    "SECOND_BATCH_FACTOR_NAMES",
    "SECOND_BATCH_FACTOR_SPECS",
    "THIRD_BATCH_FACTOR_NAMES",
    "THIRD_BATCH_FACTOR_SPECS",
    "DAILY_VALUE_FACTOR_NAMES",
    "DAILY_VALUE_FACTOR_SPECS",
    "ClassicFactorSpec",
    "DailyValueFactorSpec",
    "compute_classic_daily_factors",
    "compute_second_batch_daily_factors",
    "compute_third_batch_daily_factors",
    "compute_daily_value_factors",
    "compute_realized_volatility_factors_from_prices",
    "compute_trend_factors",
    "compute_trend_factors_from_prices",
]
