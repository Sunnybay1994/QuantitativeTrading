"""多源原始数据连接器统一接口。

换源(AKShare → Tushare Pro → 券商行情)只新增 BaseConnector 子类,
不改标准化后的下游代码。第三方数据 SDK 只允许在
quant.data.connectors.* 内部 import。

每个 fetch_* 方法返回数据源原始字段。调用方必须先把响应原样写入
不可变 raw 层，再由独立的 source mapper 映射到 quant.domain.schemas，
通过质量门禁后写入 clean 层。连接器不得跳过 raw 层直接产出 clean 数据。
"""

import datetime as dt
from abc import ABC, abstractmethod

import polars as pl


class BaseConnector(ABC):
    """数据源原始采集抽象基类，不负责标准字段映射。"""

    #: 数据源标识,写入各表的 source 字段(如 "akshare"、"baostock"、"tushare")
    source: str

    @abstractmethod
    def fetch_instruments(self, market: str) -> pl.DataFrame:
        """获取数据源原始证券列表。market: SH/SZ/HK。"""

    @abstractmethod
    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取数据源原始交易日历。"""

    @abstractmethod
    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取数据源原始日线行情。"""

    @abstractmethod
    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取数据源原始公司行动。"""

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取累计后复权因子；不支持的数据源应显式报错。"""
        raise NotImplementedError(f"{self.source} 不支持复权因子")
