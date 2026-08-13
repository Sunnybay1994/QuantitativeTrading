"""策略层:输入 as_of 可知数据,输出 target_weight。不做 IO,不碰券商。"""

from quant.strategies.base import Strategy
from quant.strategies.baselines import (
    BreadthFilteredEtfTrendStrategy,
    EqualWeightStrategy,
    EtfTrendStrategy,
    RegimeFilteredEtfLowVolatilityStrategy,
    RegimeFilteredEtfRiskAdjustedMomentumStrategy,
    RegimeFilteredEtfTrendStrategy,
)
from quant.strategies.ml_topk import MlTopkStrategy, normalize_prediction_scores

__all__ = [
    "Strategy",
    "BreadthFilteredEtfTrendStrategy",
    "EqualWeightStrategy",
    "EtfTrendStrategy",
    "RegimeFilteredEtfLowVolatilityStrategy",
    "RegimeFilteredEtfRiskAdjustedMomentumStrategy",
    "RegimeFilteredEtfTrendStrategy",
    "MlTopkStrategy",
    "normalize_prediction_scores",
]
