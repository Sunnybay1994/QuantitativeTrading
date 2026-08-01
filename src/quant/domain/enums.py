"""领域枚举:市场、币种、证券与订单生命周期。"""

from enum import Enum


class Market(str, Enum):
    SH = "SH"
    SZ = "SZ"
    HK = "HK"


class ConnectRoute(str, Enum):
    """南向港股通显式 route；SH_CONNECT→SH、SZ_CONNECT→SZ（映射留待 P0B）。"""

    SH_CONNECT = "SH_CONNECT"
    SZ_CONNECT = "SZ_CONNECT"


class Currency(str, Enum):
    CNY = "CNY"
    HKD = "HKD"


class InstrumentType(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    INDEX = "INDEX"


class InstrumentStatus(str, Enum):
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class CorporateActionType(str, Enum):
    DIVIDEND = "DIVIDEND"        # 现金分红
    BONUS = "BONUS"              # 送股/转增
    SPLIT = "SPLIT"              # 拆股/并股
    RIGHTS = "RIGHTS"            # 配股/供股


class EntitlementLegState(str, Enum):
    ABSENT = "ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CAPTURED = "CAPTURED"
    RECOGNIZED = "RECOGNIZED"
    SETTLED = "SETTLED"


class EntitlementPostingType(str, Enum):
    CAPTURE = "CAPTURE"
    CASH_RECOGNIZE = "CASH_RECOGNIZE"
    STOCK_RECOGNIZE = "STOCK_RECOGNIZE"
    CASH_SETTLE = "CASH_SETTLE"
    STOCK_SETTLE = "STOCK_SETTLE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """OMS 订单状态机(调研文档 3.7 节)。"""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExecutionRejectReason(str, Enum):
    """回测与 OMS 共用的事前成交拒绝原因。"""

    SUSPENDED = "SUSPENDED"
    BUY_AT_UPPER_LIMIT = "BUY_AT_UPPER_LIMIT"
    SELL_AT_LOWER_LIMIT = "SELL_AT_LOWER_LIMIT"
    T_PLUS_ONE = "T_PLUS_ONE"
    RULE_NOT_EFFECTIVE = "RULE_NOT_EFFECTIVE"
    RULE_VERSION_MISMATCH = "RULE_VERSION_MISMATCH"
    CONNECT_CALENDAR_CLOSED = "CONNECT_CALENDAR_CLOSED"
    INSUFFICIENT_SELLABLE = "INSUFFICIENT_SELLABLE"
    CONNECT_BUY_QUOTA_UNAVAILABLE = "CONNECT_BUY_QUOTA_UNAVAILABLE"
    CONNECT_BUY_BOARD_LOT_REQUIRED = "CONNECT_BUY_BOARD_LOT_REQUIRED"
    CONNECT_SELL_MIXED_LOT = "CONNECT_SELL_MIXED_LOT"
    PRICE_BAND_MISSING = "PRICE_BAND_MISSING"
    PRICE_TICK_INVALID = "PRICE_TICK_INVALID"
    PRICE_OUT_OF_RANGE = "PRICE_OUT_OF_RANGE"


class ExecutionMode(str, Enum):
    """M4 执行模式；禁止 LIVE。"""

    PAPER = "PAPER"
    SHADOW = "SHADOW"


class OrderType(str, Enum):
    """M4 仅支持限价单。"""

    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    """M4 仅支持当日有效。"""

    DAY = "DAY"


class ExecutionEventType(str, Enum):
    """Gateway/OMS 事件类型；与 OrderStatus 聚合状态分离。"""

    ACCEPTED = "ACCEPTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCEL_ACCEPTED = "CANCEL_ACCEPTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
