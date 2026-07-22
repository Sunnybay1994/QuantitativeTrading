"""旧模块名兼容入口；实现的唯一事实来源是 ``connectors.akshare``。"""

from quant.data.connectors.akshare import AkshareConnector

# 保留骨架阶段已出现的类名，避免旧导入立即失效；新代码使用 AkshareConnector。
AKShareConnector = AkshareConnector

__all__ = ["AKShareConnector"]
