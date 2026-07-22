"""第三方数据源连接器；SDK 依赖只允许出现在本包内部。"""

from quant.data.connectors.akshare import AkshareConnector
from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.connect_official import SseConnectConnector, SzseConnectConnector
from quant.data.connectors.hkex_etp import HkexEtpConnector
from quant.data.connectors.tushare import TushareConnector

__all__ = [
    "AkshareConnector",
    "BaostockConnector",
    "HkexEtpConnector",
    "SseConnectConnector",
    "SzseConnectConnector",
    "TushareConnector",
]
