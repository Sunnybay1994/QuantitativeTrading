"""统一策略接口(调研文档 3.5 节)。

策略输入 as_of 时点的可知数据,输出 TargetWeightSchema 契约的目标权重。
策略不得下载数据、不得触碰订单或券商 API。
"""

import datetime as dt
from abc import ABC, abstractmethod

import polars as pl


class Strategy(ABC):
    """目标权重策略抽象基类。"""

    #: 策略标识与版本,写入 target_weight 的 strategy / strategy_version 字段
    name: str
    version: str

    @abstractmethod
    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """计算 as_of 时点的目标权重。

        Args:
            as_of: 信号可知日。只能使用该时点及之前可知的数据。
            data: 上游按契约准备好的输入(行情/因子等),策略自身不做 IO。

        Returns:
            符合 TargetWeightSchema 的 DataFrame;权重和 <= 1,余量为现金。
        """
