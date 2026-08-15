"""核心数据契约(调研文档 3.2 节标准表)。

以 Pandera Polars schema 定义 clean 层各标准表的结构与领域约束。
所有下游(因子、策略、回测、执行)只依赖这些契约,不依赖任何数据源的原始字段。

约定:
- symbol 统一为 "000001.SZ" / "600000.SH" / "00700.HK" 风格。
- 时间字段:trade_date 为交易日(Date);as_of 为信号可知时间。
- 金额单位:人民币/港币元;成交量单位:股(不是手)。
"""

import datetime as dt
from typing import Annotated

import pandera.polars as pa
import polars as pl

from quant.domain.enums import (
    EntitlementLegState,
    EntitlementPostingType,
    ExecutionRejectReason,
    OrderSide,
)

SYMBOL_PATTERN = r"^\d{5,6}\.(SH|SZ|HK)$"
# Price-index-compatible tradeable codes plus CSI300 total-return index.
BENCHMARK_PATTERN = rf"^({SYMBOL_PATTERN[1:-1]}|H00300\.CSI)$"


class InstrumentSchema(pa.DataFrameModel):
    """证券主表 instrument。"""

    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN, unique=True)
    market: str = pa.Field(isin=["SH", "SZ", "HK"])
    name: str
    instrument_type: str = pa.Field(isin=["STOCK", "ETF", "INDEX"])
    currency: str = pa.Field(isin=["CNY", "HKD"])
    list_date: pl.Date
    delist_date: pl.Date = pa.Field(nullable=True)
    board_lot: int = pa.Field(gt=0)  # A 股 100;港股每只不同
    status: str = pa.Field(isin=["LISTED", "SUSPENDED", "DELISTED"])

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def instrument_fields_consistent(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """上市区间、代码市场和币种必须相互一致。"""
        suffix = pl.col("symbol").str.split(".").list.last()
        expected_currency = pl.when(pl.col("market") == "HK").then(
            pl.lit("HKD")
        ).otherwise(pl.lit("CNY"))
        return data.lazyframe.select(
            (pl.col("delist_date").is_null() | (pl.col("delist_date") >= pl.col("list_date")))
            & (suffix == pl.col("market"))
            & (pl.col("currency") == expected_currency)
        )


class TradeCalendarSchema(pa.DataFrameModel):
    """双市场交易日历 trade_calendar。"""

    market: str = pa.Field(isin=["SH", "SZ", "HK"])
    date: pl.Date
    is_open: bool
    is_connect_open: bool  # 港股通可交易日(A 股市场恒为 False 无意义,填 False)
    is_half_day: bool

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def market_date_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同一市场交易日只能有一条记录。"""
        return _rows_are_unique(data, ["market", "date"])


class SnapshotSessionCalendarSchema(pa.DataFrameModel):
    """G2A 使用的唯一、严格递增 SH session 日期序列。"""

    date: pl.Date = pa.Field(unique=True)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def non_empty_and_strictly_increasing(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        frame = data.lazyframe
        return frame.select(
            (pl.len() > 0)
            & pl.col("date").is_not_null().all()
            & (pl.col("date") == pl.col("date").sort()).all()
        )


class Bar1dSchema(pa.DataFrameModel):
    """日线行情 bar_1d（不复权价 + 累计后复权因子）。

    研究用后复权价 = 不复权 OHLC × adj_factor；账户核算始终使用不复权价。
    """

    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    trade_date: pl.Date
    open: float = pa.Field(gt=0)
    high: float = pa.Field(gt=0)
    low: float = pa.Field(gt=0)
    close: float = pa.Field(gt=0)
    volume: float = pa.Field(ge=0)   # 股
    amount: float = pa.Field(ge=0)   # 元
    adj_factor: float = pa.Field(gt=0)
    source: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def ohlc_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """OHLC 合法性: low <= open/close <= high。"""
        return data.lazyframe.select(
            (pl.col("high") >= pl.col("low"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
            & (pl.col("low") <= pl.col("open"))
            & (pl.col("low") <= pl.col("close"))
        )

    @pa.dataframe_check
    def symbol_date_source_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同一来源的证券日线只能有一条。"""
        return _rows_are_unique(data, ["symbol", "trade_date", "source"])


class HKNoTradeEvidenceSchema(pa.DataFrameModel):
    """Verified one-key HK no-daily-trading evidence projection.

    The projection is deliberately narrower than an HKEX source parser.  It
    binds an authoritative source record to retained raw bytes; source-format
    interpretation remains a separately frozen/licensed ingestion concern.
    """

    schema_version: str = pa.Field(isin=["hk-no-trade-evidence-v1"])
    evidence_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    trade_date: pl.Date
    market: str = pa.Field(isin=["HK"])
    reason: str = pa.Field(isin=["NO_DAILY_TRADING_V1"])
    source: str = pa.Field(
        isin=[
            "HKEX_DAILY_QUOTATIONS",
            "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
        ]
    )
    source_record_id: str
    source_as_of: pl.Datetime
    raw_selector: str
    raw_file_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def evidence_key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["symbol", "trade_date"])

    @pa.dataframe_check
    def user_approved_consensus_is_exactly_scoped(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """The user-approved consensus source is three exact audited exceptions."""
        return data.lazyframe.select(
            (pl.col("source") != "USER_APPROVED_MULTI_SOURCE_CONSENSUS")
            | (
                (pl.col("symbol") == "01065.HK")
                & (pl.col("trade_date") == pl.date(2026, 5, 5))
                & (pl.col("source_record_id") == "UA-M1-001")
                & (
                    pl.col("raw_selector")
                    == "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"
                )
            )
            | (
                (pl.col("symbol") == "02402.HK")
                & pl.col("trade_date").is_in(
                    [
                        dt.date(2026, 4, 14),
                        dt.date(2026, 4, 15),
                        dt.date(2026, 4, 16),
                        dt.date(2026, 4, 17),
                        dt.date(2026, 4, 20),
                        dt.date(2026, 4, 21),
                        dt.date(2026, 4, 22),
                        dt.date(2026, 4, 23),
                        dt.date(2026, 4, 24),
                        dt.date(2026, 4, 27),
                        dt.date(2026, 4, 28),
                        dt.date(2026, 4, 29),
                        dt.date(2026, 4, 30),
                    ]
                )
                & (pl.col("source_record_id") == "UA-M1-004")
                & (
                    pl.col("raw_selector")
                    == "user-approved-consensus/"
                    "ua-m1-004-02402-2026-04-01-to-2026-05-04.record"
                )
            )
            | (
                (pl.col("symbol") == "06110.HK")
                & (pl.col("trade_date") == pl.date(2026, 6, 25))
                & (pl.col("source_record_id") == "UA-M1-005")
                & (
                    pl.col("raw_selector")
                    == "user-approved-consensus/"
                    "ua-m1-005-06110-2026-06-25.record"
                )
            )
        )

    @pa.dataframe_check
    def ua_m1_005_identity_binds_user_approved_source(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """UA-M1-005 record or selector identity cannot ride a non-approved source."""
        return data.lazyframe.select(
            (
                (pl.col("source_record_id") != "UA-M1-005")
                & (
                    pl.col("raw_selector")
                    != "user-approved-consensus/"
                    "ua-m1-005-06110-2026-06-25.record"
                )
            )
            | (
                (pl.col("source") == "USER_APPROVED_MULTI_SOURCE_CONSENSUS")
                & (pl.col("symbol") == "06110.HK")
                & (pl.col("trade_date") == pl.date(2026, 6, 25))
                & (pl.col("source_record_id") == "UA-M1-005")
                & (
                    pl.col("raw_selector")
                    == "user-approved-consensus/"
                    "ua-m1-005-06110-2026-06-25.record"
                )
            )
        )


class HkBarAvailabilityEvidenceSchema(pa.DataFrameModel):
    """Exact retained-source availability evidence for one HK daily bar."""

    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    trade_date: pl.Date
    source: str
    availability_source_kind: str = pa.Field(
        isin=["SEED_RAW", "REQUEST_RAW", "HKEX_SUPPLEMENT"]
    )
    bar_available_at: Annotated[pl.Datetime, "us", "UTC"]
    source_record_id: str
    request_id: str = pa.Field(
        nullable=True, str_matches=r"^[0-9a-f]{64}$"
    )
    raw_file_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    request_receipt_sha256: str = pa.Field(
        nullable=True, str_matches=r"^[0-9a-f]{64}$"
    )
    plan_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    availability_evidence_sha256: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$", unique=True
    )

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def availability_fields_consistent(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        request = pl.col("availability_source_kind") == "REQUEST_RAW"
        return data.lazyframe.select(
            _unique_expr(["symbol", "trade_date"])
            & pl.col("source").str.len_chars().gt(0).all()
            & pl.col("source_record_id").str.len_chars().gt(0).all()
            & (
                (
                    request
                    & pl.col("request_id").is_not_null()
                    & pl.col("request_receipt_sha256").is_not_null()
                )
                | (
                    ~request
                    & pl.col("request_id").is_null()
                    & pl.col("request_receipt_sha256").is_null()
                )
            ).all()
        )


class AdjustmentFactorSchema(pa.DataFrameModel):
    """累计后复权因子；从 effective_date 起生效。"""

    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    effective_date: pl.Date
    adj_factor: float = pa.Field(gt=0)
    source: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def factor_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return _rows_are_unique(data, ["symbol", "effective_date", "source"])


class AdjustmentFactorMatchSchema(pa.DataFrameModel):
    """G1 bar↔factor 精确匹配证据；每个 emitted bar 一行。"""

    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    trade_date: pl.Date
    source: str = pa.Field(isin=["tushare"])
    adj_factor: float = pa.Field(gt=0)
    bar_request_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    bar_stable_response_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    factor_request_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    factor_stable_response_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def match_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return _rows_are_unique(data, ["symbol", "trade_date", "source"])


class ResearchPrice1dSchema(pa.DataFrameModel):
    """仅用于研究的后复权日收盘价，不得进入账户核算或成交模拟。"""

    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    trade_date: pl.Date
    adjusted_close: float = pa.Field(gt=0)
    adjustment_method: str = pa.Field(
        isin=[
            "HFQ",
            "TOTAL_RETURN_DIVIDEND",
            "CUMULATIVE_FACTOR",
            "HK_GROSS_TOTAL_RETURN_V1",
        ]
    )
    source: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["symbol", "trade_date"])


class CorporateActionSchema(pa.DataFrameModel):
    """港股 PIT 公司行动 canonical 表（研究事实，不是账户账本）。"""

    event_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    action_type: str = pa.Field(isin=["DIVIDEND", "BONUS", "SPLIT", "RIGHTS"])
    record_date: pl.Date
    ex_date: pl.Date
    pay_date: pl.Date = pa.Field(nullable=True)
    stock_list_date: pl.Date = pa.Field(nullable=True)
    declared_currency: str = pa.Field(isin=["CNY", "HKD"], nullable=True)
    cash_per_share_gross: float = pa.Field(gt=0, nullable=True)
    stock_ratio: float = pa.Field(gt=0, nullable=True)
    share_multiplier: float = pa.Field(gt=0, nullable=True)
    rights_ratio: float = pa.Field(gt=0, nullable=True)
    rights_subscription_price: float = pa.Field(gt=0, nullable=True)
    rights_subscription_start: pl.Date = pa.Field(nullable=True)
    rights_subscription_end: pl.Date = pa.Field(nullable=True)
    announce_time: pl.Datetime
    source: str
    source_event_id: str
    source_revision_id: str
    source_snapshot_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def action_fields_consistent(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        """日期、有限数值和四类行动的互斥经济字段必须闭包。"""
        action = pl.col("action_type")
        cash = pl.col("cash_per_share_gross")
        stock = pl.col("stock_ratio")
        multiplier = pl.col("share_multiplier")
        rights_ratio = pl.col("rights_ratio")
        rights_price = pl.col("rights_subscription_price")
        rights_start = pl.col("rights_subscription_start")
        rights_end = pl.col("rights_subscription_end")
        currency = pl.col("declared_currency")
        pay = pl.col("pay_date")
        list_date = pl.col("stock_list_date")
        common = (
            (pl.col("record_date") <= pl.col("ex_date"))
            & (cash.is_null() | cash.is_finite())
            & (stock.is_null() | stock.is_finite())
            & (multiplier.is_null() | multiplier.is_finite())
            & (rights_ratio.is_null() | rights_ratio.is_finite())
            & (rights_price.is_null() | rights_price.is_finite())
        )
        dividend = (
            (action == "DIVIDEND")
            & currency.is_not_null()
            & cash.is_not_null()
            & pay.is_not_null()
            & (pay >= pl.col("ex_date"))
            & stock.is_null()
            & multiplier.is_null()
            & rights_ratio.is_null()
            & rights_price.is_null()
            & rights_start.is_null()
            & rights_end.is_null()
            & list_date.is_null()
        )
        bonus = (
            (action == "BONUS")
            & currency.is_null()
            & cash.is_null()
            & stock.is_not_null()
            & multiplier.is_null()
            & rights_ratio.is_null()
            & rights_price.is_null()
            & rights_start.is_null()
            & rights_end.is_null()
            & pay.is_null()
            & list_date.is_not_null()
            & (list_date >= pl.col("ex_date"))
        )
        split = (
            (action == "SPLIT")
            & currency.is_null()
            & cash.is_null()
            & stock.is_null()
            & multiplier.is_not_null()
            & (multiplier != 1.0)
            & rights_ratio.is_null()
            & rights_price.is_null()
            & rights_start.is_null()
            & rights_end.is_null()
            & pay.is_null()
            & list_date.is_not_null()
            & (list_date >= pl.col("ex_date"))
        )
        rights = (
            (action == "RIGHTS")
            & currency.is_not_null()
            & cash.is_null()
            & stock.is_null()
            & multiplier.is_null()
            & rights_ratio.is_not_null()
            & rights_price.is_not_null()
            & rights_start.is_not_null()
            & rights_end.is_not_null()
            & pay.is_null()
            & list_date.is_not_null()
            & (pl.col("ex_date") <= rights_start)
            & (rights_start <= rights_end)
            & (rights_end <= list_date)
        )
        return data.lazyframe.select((common & (dividend | bonus | split | rights)).all())


class HkCorporateActionRevisionEvidenceSchema(pa.DataFrameModel):
    """港股同一经济事件的完整修订、撤回与 PIT 选择证据。"""

    economic_event_key_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    candidate_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    action_type: str = pa.Field(isin=["DIVIDEND", "BONUS", "SPLIT", "RIGHTS"])
    source: str
    source_event_id: str
    source_revision_id: str
    revision_sequence: int = pa.Field(gt=0)
    predecessor_candidate_id: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$", nullable=True
    )
    revision_status: str = pa.Field(isin=["ACTIVE", "WITHDRAWN"])
    published_at: pl.Datetime
    source_observed_at: pl.Datetime
    record_date: pl.Date
    ex_date: pl.Date
    pay_date: pl.Date = pa.Field(nullable=True)
    stock_list_date: pl.Date = pa.Field(nullable=True)
    declared_currency: str = pa.Field(isin=["CNY", "HKD"], nullable=True)
    cash_per_share_gross: float = pa.Field(gt=0, nullable=True)
    stock_ratio: float = pa.Field(gt=0, nullable=True)
    share_multiplier: float = pa.Field(gt=0, nullable=True)
    rights_ratio: float = pa.Field(gt=0, nullable=True)
    rights_subscription_price: float = pa.Field(gt=0, nullable=True)
    rights_subscription_start: pl.Date = pa.Field(nullable=True)
    rights_subscription_end: pl.Date = pa.Field(nullable=True)
    raw_bundle_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_file_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_selector: str
    selected: bool
    selection_reason: str = pa.Field(
        isin=[
            "SELECTED_AS_OF",
            "SUPERSEDED_AS_OF",
            "FUTURE_AS_OF",
            "WITHDRAWN_AS_OF",
        ]
    )
    query_as_of: pl.Datetime

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def evidence_keys_and_reasons_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        frame = data.lazyframe
        reason = pl.col("selection_reason")
        selected = pl.col("selected")
        status = pl.col("revision_status")
        return frame.select(
            _unique_expr(["source", "source_revision_id"])
            & (pl.col("source_observed_at") >= pl.col("published_at")).all()
            & (
                ((reason == "FUTURE_AS_OF") == (pl.col("published_at") > pl.col("query_as_of")))
                & ((reason != "FUTURE_AS_OF") | ~selected)
                & ((reason == "SELECTED_AS_OF") == (selected & (status == "ACTIVE")))
                & ((reason == "WITHDRAWN_AS_OF") == (selected & (status == "WITHDRAWN")))
                & ((reason != "SUPERSEDED_AS_OF") | (~selected & (pl.col("published_at") <= pl.col("query_as_of"))))
            ).all()
        )

    @pa.dataframe_check
    def evidence_action_fields_consistent(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """Evidence rows use exactly the canonical action economic branches."""
        return data.lazyframe.select(_hk_action_fields_consistent_expr().all())

    @pa.dataframe_check
    def at_most_one_selected_revision_per_event(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        selected = data.lazyframe.filter(pl.col("selected"))
        return selected.select(
            _unique_expr(["source", "source_event_id"]).alias("selected_event_unique")
        )


class HkCorporateActionImplementationEvidenceSchema(pa.DataFrameModel):
    """来源明确确认的港股公司行动实施事实。"""

    event_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    action_type: str = pa.Field(isin=["DIVIDEND", "BONUS", "SPLIT", "RIGHTS"])
    source: str
    source_event_id: str
    source_revision_id: str
    implementation_status: str = pa.Field(isin=["IMPLEMENTED"])
    implementation_effective_date: pl.Date
    implementation_confirmed_at: pl.Datetime
    source_observed_at: pl.Datetime
    source_record_id: str
    raw_selector: str
    raw_file_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_metadata_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    raw_bundle_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    p0_actions_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    p0_evidence_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    p0_query_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    implementation_evidence_sha256: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$", unique=True
    )

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def implementation_times_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return data.lazyframe.select(
            (pl.col("source_observed_at") >= pl.col("implementation_confirmed_at")).all()
            & _unique_expr(["source", "source_event_id"])
            & _unique_expr(["source", "source_revision_id"])
        )


class HkTotalReturnApplicationScheduleSchema(pa.DataFrameModel):
    """Source-neutral HK gross-total-return action application schedule."""

    event_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^[0-9]{5}\.HK$")
    action_type: str = pa.Field(isin=["DIVIDEND", "BONUS", "SPLIT", "RIGHTS"])
    source: str
    source_event_id: str
    source_revision_id: str
    ex_date: pl.Date
    pay_date: pl.Date = pa.Field(nullable=True)
    stock_list_date: pl.Date = pa.Field(nullable=True)
    declared_currency: str = pa.Field(isin=["CNY", "HKD"], nullable=True)
    implementation_effective_date: pl.Date
    implementation_confirmed_at: Annotated[pl.Datetime, "us", "UTC"]
    source_observed_at: Annotated[pl.Datetime, "us", "UTC"]
    window_disposition: str = pa.Field(
        isin=[
            "BASELINE_PREWINDOW",
            "APPLY_IN_WINDOW",
            "OUTSIDE_FUTURE_WINDOW",
        ]
    )
    application_trade_date: pl.Date = pa.Field(nullable=True)
    application_bar_available_at: Annotated[pl.Datetime, "us", "UTC"] = pa.Field(
        nullable=True
    )
    application_availability_evidence_sha256: str = pa.Field(
        nullable=True, str_matches=r"^[0-9a-f]{64}$"
    )
    cash_per_share_gross_hkd: float = pa.Field(gt=0, nullable=True)
    stock_ratio: float = pa.Field(gt=0, nullable=True)
    share_multiplier: float = pa.Field(gt=0, nullable=True)
    policy_version: str = pa.Field(isin=["HK_GROSS_TOTAL_RETURN_SCHEDULE_V1"])
    p0_query_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    p0_actions_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    p0_evidence_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    implementation_evidence_content_sha256: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$"
    )
    implementation_projection_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    bar_plan_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    bar_publication_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    bars_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    bar_availability_content_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    row_identity_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def schedule_fields_consistent(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        action = pl.col("action_type")
        applied = pl.col("window_disposition") == "APPLY_IN_WINDOW"
        application_complete = (
            pl.col("application_trade_date").is_not_null()
            & pl.col("application_bar_available_at").is_not_null()
            & pl.col("application_availability_evidence_sha256").is_not_null()
        )
        dividend = (
            (action == "DIVIDEND")
            & (pl.col("declared_currency") == "HKD")
            & pl.col("pay_date").is_not_null()
            & pl.col("stock_list_date").is_null()
            & pl.col("cash_per_share_gross_hkd").is_not_null()
            & pl.col("stock_ratio").is_null()
            & pl.col("share_multiplier").is_null()
        )
        bonus = (
            (action == "BONUS")
            & pl.col("declared_currency").is_null()
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
            & pl.col("cash_per_share_gross_hkd").is_null()
            & pl.col("stock_ratio").is_not_null()
            & pl.col("share_multiplier").is_not_null()
            & (pl.col("share_multiplier") == 1.0 + pl.col("stock_ratio"))
        )
        split = (
            (action == "SPLIT")
            & pl.col("declared_currency").is_null()
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
            & pl.col("cash_per_share_gross_hkd").is_null()
            & pl.col("stock_ratio").is_null()
            & pl.col("share_multiplier").is_not_null()
            & (pl.col("share_multiplier") != 1.0)
        )
        unsupported_outside = (
            ~applied
            & (
                (action == "RIGHTS")
                | ((action == "DIVIDEND") & (pl.col("declared_currency") == "CNY"))
            )
            & pl.col("cash_per_share_gross_hkd").is_null()
            & pl.col("stock_ratio").is_null()
            & pl.col("share_multiplier").is_null()
            & (
                (
                    (action == "RIGHTS")
                    & pl.col("pay_date").is_null()
                    & pl.col("stock_list_date").is_not_null()
                )
                | (
                    (action == "DIVIDEND")
                    & pl.col("pay_date").is_not_null()
                    & pl.col("stock_list_date").is_null()
                )
            )
        )
        return data.lazyframe.select(
            _unique_expr(["symbol", "source", "source_event_id", "source_revision_id"])
            & (pl.col("source_observed_at") >= pl.col("implementation_confirmed_at")).all()
            & ((applied & application_complete) | (~applied & ~application_complete)).all()
            & (pl.col("application_trade_date").is_null() | (pl.col("application_trade_date") >= pl.col("ex_date"))).all()
            & (dividend | bonus | split | unsupported_outside).all()
        )


class CorporateActionLedgerSchema(pa.DataFrameModel):
    """账户回放使用的已实施 A 股分红送转事件。

    与面向 PIT 研究的 ``CorporateActionSchema`` 分离：本表只表达已经实施且可按
    除权日进入账户账本的事实，不伪造供应商没有提供的盘中公告时间。
    """

    event_id: str = pa.Field(unique=True)
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    ex_date: pl.Date
    action_type: str = pa.Field(
        isin=["DIVIDEND_DISTRIBUTION", "RIGHTS", "SHARE_CONSIDERATION"]
    )
    cash_per_share_gross: float = pa.Field(ge=0)
    stock_ratio: float = pa.Field(ge=0)
    rights_price: float = pa.Field(gt=0, nullable=True)
    rights_ratio: float = pa.Field(ge=0)
    rights_actual_shares: float = pa.Field(gt=0, nullable=True)
    rights_pre_shares: float = pa.Field(gt=0, nullable=True)
    rights_post_shares: float = pa.Field(gt=0, nullable=True)
    rights_pre_circulating_shares: float = pa.Field(gt=0, nullable=True)
    rights_post_circulating_shares: float = pa.Field(gt=0, nullable=True)
    rights_mixed_change_proof_sha256: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$", nullable=True
    )
    record_date: pl.Date
    pay_date: pl.Date = pa.Field(nullable=True)
    stock_list_date: pl.Date = pa.Field(nullable=True)
    vendor_record_id: str = pa.Field(nullable=True)
    source: str
    source_snapshot_id: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def ledger_event_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """经济效果、登记日非空，并按 action_type 分支校验事件语义。"""
        cash = pl.col("cash_per_share_gross")
        stock = pl.col("stock_ratio")
        rights_price = pl.col("rights_price")
        rights_ratio = pl.col("rights_ratio")
        actual = pl.col("rights_actual_shares")
        pre = pl.col("rights_pre_shares")
        post = pl.col("rights_post_shares")
        pre_circulating = pl.col("rights_pre_circulating_shares")
        post_circulating = pl.col("rights_post_circulating_shares")
        mixed_proof_sha256 = pl.col("rights_mixed_change_proof_sha256")
        action_type = pl.col("action_type")
        share_delta = (post - pre).abs()
        representation_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, actual.abs()) * 1e-6,
            pl.lit(1e-6),
        )
        share_close = (post - pre - actual).abs() <= representation_tolerance
        circulating_delta = post_circulating - pre_circulating
        mixed_representation_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, actual.abs()) * 1e-12,
            pl.lit(1e-12),
        )
        delta_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, circulating_delta.abs()) * 1e-12,
            pl.lit(1e-12),
        )
        deltas_close = (post - pre - circulating_delta).abs() <= delta_tolerance
        strict_rights = (
            share_close
            & pre_circulating.is_null()
            & post_circulating.is_null()
            & mixed_proof_sha256.is_null()
        )
        mixed_rights = (
            pre_circulating.is_not_null()
            & (pre_circulating > 0)
            & post_circulating.is_not_null()
            & (post_circulating > pre_circulating)
            & deltas_close
            & ((post - pre - actual) > mixed_representation_tolerance)
            & mixed_proof_sha256.is_not_null()
        )
        no_mixed_rights_fields = (
            pre_circulating.is_null()
            & post_circulating.is_null()
            & mixed_proof_sha256.is_null()
        )
        common = (
            cash.is_finite()
            & stock.is_finite()
            & rights_ratio.is_finite()
            & (rights_price.is_null() | rights_price.is_finite())
            & (actual.is_null() | actual.is_finite())
            & (pre.is_null() | pre.is_finite())
            & (post.is_null() | post.is_finite())
            & pl.col("record_date").is_not_null()
            & (pl.col("record_date") <= pl.col("ex_date"))
            & (
                pl.col("pay_date").is_null()
                | (pl.col("pay_date") >= pl.col("ex_date"))
            )
            & (
                pl.col("stock_list_date").is_null()
                | (pl.col("stock_list_date") >= pl.col("ex_date"))
            )
        )
        dividend_branch = (
            (action_type == "DIVIDEND_DISTRIBUTION")
            & ((cash > 0) | (stock > 0))
            & rights_price.is_null()
            & (rights_ratio == 0)
            & actual.is_null()
            & pre.is_null()
            & post.is_null()
            & no_mixed_rights_fields
            & ((cash > 0) == pl.col("pay_date").is_not_null())
            & ((stock > 0) == pl.col("stock_list_date").is_not_null())
        )
        rights_branch = (
            (action_type == "RIGHTS")
            & (cash == 0)
            & (stock == 0)
            & rights_price.is_not_null()
            & (rights_price > 0)
            & (rights_ratio > 0)
            & actual.is_not_null()
            & (actual > 0)
            & pre.is_not_null()
            & (pre > 0)
            & post.is_not_null()
            & (post > 0)
            & (post > pre)
            & (strict_rights | mixed_rights)
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
        )
        consideration_branch = (
            (action_type == "SHARE_CONSIDERATION")
            & (cash == 0)
            & (stock > 0)
            & rights_price.is_null()
            & (rights_ratio == 0)
            & actual.is_null()
            & pre.is_null()
            & post.is_null()
            & no_mixed_rights_fields
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
            & (pl.col("stock_list_date") == pl.col("ex_date"))
        )
        return data.lazyframe.select(
            (common & (dividend_branch | rights_branch | consideration_branch)).all()
        )


class CorporateActionSelectionEvidenceSchema(pa.DataFrameModel):
    """公司行动多公告选版证据；每个 candidate 一行。"""

    economic_event_key_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    candidate_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$", unique=True)
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    action_type: str = pa.Field(
        isin=["DIVIDEND_DISTRIBUTION", "RIGHTS", "SHARE_CONSIDERATION"]
    )
    end_date: pl.Date = pa.Field(nullable=True)
    record_date: pl.Date
    ex_date: pl.Date
    imp_ann_date: pl.Date = pa.Field(nullable=True)
    ann_date: pl.Date = pa.Field(nullable=True)
    cash_per_share_gross: float = pa.Field(ge=0)
    stock_ratio: float = pa.Field(ge=0)
    rights_price: float = pa.Field(gt=0, nullable=True)
    rights_ratio: float = pa.Field(ge=0)
    rights_actual_shares: float = pa.Field(gt=0, nullable=True)
    rights_pre_shares: float = pa.Field(gt=0, nullable=True)
    rights_post_shares: float = pa.Field(gt=0, nullable=True)
    rights_pre_circulating_shares: float = pa.Field(gt=0, nullable=True)
    rights_post_circulating_shares: float = pa.Field(gt=0, nullable=True)
    rights_mixed_change_proof_sha256: str = pa.Field(
        str_matches=r"^[0-9a-f]{64}$", nullable=True
    )
    rights_mixed_change_proof_json: str = pa.Field(
        str_matches=r"^\{.*\}$", nullable=True
    )
    pay_date: pl.Date = pa.Field(nullable=True)
    stock_list_date: pl.Date = pa.Field(nullable=True)
    vendor_record_id: str = pa.Field(nullable=True)
    candidate_rank: int = pa.Field(gt=0)
    candidate_count: int = pa.Field(gt=0)
    raw_row_count: int = pa.Field(gt=0)
    selected: bool
    selection_reason: str = pa.Field(isin=["SELECTED_LATEST", "SUPERSEDED_OLDER"])
    source: str
    source_request_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    source_snapshot_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def selection_evidence_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """数值、日期顺序、rank/selected/reason 与 action_type 分支约束。"""
        cash = pl.col("cash_per_share_gross")
        stock = pl.col("stock_ratio")
        rights_price = pl.col("rights_price")
        rights_ratio = pl.col("rights_ratio")
        actual = pl.col("rights_actual_shares")
        pre = pl.col("rights_pre_shares")
        post = pl.col("rights_post_shares")
        pre_circulating = pl.col("rights_pre_circulating_shares")
        post_circulating = pl.col("rights_post_circulating_shares")
        mixed_proof_sha256 = pl.col("rights_mixed_change_proof_sha256")
        mixed_proof_json = pl.col("rights_mixed_change_proof_json")
        action_type = pl.col("action_type")
        share_delta = (post - pre).abs()
        representation_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, actual.abs()) * 1e-6,
            pl.lit(1e-6),
        )
        share_close = (post - pre - actual).abs() <= representation_tolerance
        circulating_delta = post_circulating - pre_circulating
        mixed_representation_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, actual.abs()) * 1e-12,
            pl.lit(1e-12),
        )
        delta_tolerance = pl.max_horizontal(
            pl.max_horizontal(share_delta, circulating_delta.abs()) * 1e-12,
            pl.lit(1e-12),
        )
        deltas_close = (post - pre - circulating_delta).abs() <= delta_tolerance
        strict_rights = (
            share_close
            & pre_circulating.is_null()
            & post_circulating.is_null()
            & mixed_proof_sha256.is_null()
            & mixed_proof_json.is_null()
        )
        mixed_rights = (
            pre_circulating.is_not_null()
            & (pre_circulating > 0)
            & post_circulating.is_not_null()
            & (post_circulating > pre_circulating)
            & deltas_close
            & ((post - pre - actual) > mixed_representation_tolerance)
            & mixed_proof_sha256.is_not_null()
            & mixed_proof_json.is_not_null()
        )
        no_mixed_rights_fields = (
            pre_circulating.is_null()
            & post_circulating.is_null()
            & mixed_proof_sha256.is_null()
            & mixed_proof_json.is_null()
        )
        common = (
            cash.is_finite()
            & stock.is_finite()
            & rights_ratio.is_finite()
            & (rights_price.is_null() | rights_price.is_finite())
            & (actual.is_null() | actual.is_finite())
            & (pre.is_null() | pre.is_finite())
            & (post.is_null() | post.is_finite())
            & (pl.col("record_date") <= pl.col("ex_date"))
            & (
                pl.col("pay_date").is_null()
                | (pl.col("pay_date") >= pl.col("ex_date"))
            )
            & (
                pl.col("stock_list_date").is_null()
                | (pl.col("stock_list_date") >= pl.col("ex_date"))
            )
            & (pl.col("candidate_rank") <= pl.col("candidate_count"))
            & (
                (pl.col("selected") & (pl.col("candidate_rank") == 1)
                 & (pl.col("selection_reason") == "SELECTED_LATEST"))
                | (
                    (~pl.col("selected"))
                    & (pl.col("candidate_rank") > 1)
                    & (pl.col("selection_reason") == "SUPERSEDED_OLDER")
                )
            )
        )
        dividend_branch = (
            (action_type == "DIVIDEND_DISTRIBUTION")
            & pl.col("end_date").is_not_null()
            & ((cash > 0) | (stock > 0))
            & rights_price.is_null()
            & (rights_ratio == 0)
            & actual.is_null()
            & pre.is_null()
            & post.is_null()
            & no_mixed_rights_fields
            & ((cash > 0) == pl.col("pay_date").is_not_null())
            & ((stock > 0) == pl.col("stock_list_date").is_not_null())
        )
        rights_branch = (
            (action_type == "RIGHTS")
            & pl.col("end_date").is_not_null()
            & (cash == 0)
            & (stock == 0)
            & rights_price.is_not_null()
            & (rights_price > 0)
            & (rights_ratio > 0)
            & actual.is_not_null()
            & (actual > 0)
            & pre.is_not_null()
            & (pre > 0)
            & post.is_not_null()
            & (post > 0)
            & (post > pre)
            & (strict_rights | mixed_rights)
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
        )
        consideration_branch = (
            (action_type == "SHARE_CONSIDERATION")
            & pl.col("end_date").is_null()
            & (cash == 0)
            & (stock > 0)
            & rights_price.is_null()
            & (rights_ratio == 0)
            & actual.is_null()
            & pre.is_null()
            & post.is_null()
            & no_mixed_rights_fields
            & pl.col("pay_date").is_null()
            & pl.col("stock_list_date").is_not_null()
            & (pl.col("stock_list_date") == pl.col("ex_date"))
        )
        return data.lazyframe.select(
            (common & (dividend_branch | rights_branch | consideration_branch)).all()
        )


class CorporateActionReconciliationSchema(pa.DataFrameModel):
    """复权因子相邻观测与已实施公司行动的对账证据。"""

    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    previous_factor_date: pl.Date
    effective_date: pl.Date
    previous_close_date: pl.Date = pa.Field(nullable=True)
    previous_close: float = pa.Field(nullable=True)
    ex_reference_price: float = pa.Field(nullable=True)
    daily_request_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    daily_stable_response_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    event_count: int = pa.Field(ge=0)
    event_ids_json: str
    event_ids_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    stock_ratio_terms_json: str = pa.Field(str_matches=r"^\[.*\]$")
    stock_ratio_terms_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    cash_per_share_gross: float = pa.Field(ge=0)
    stock_ratio: float = pa.Field(ge=0)
    rights_ratio: float = pa.Field(ge=0)
    rights_subscription_cash_per_share: float = pa.Field(ge=0)
    declared_dividend_factor_ratio: float = pa.Field(gt=0)
    market_reference_factor_ratio: float = pa.Field(gt=0, nullable=True)
    actual_factor_ratio: float = pa.Field(gt=0)
    market_reference_relative_error: float = pa.Field(ge=0, nullable=True)
    declared_dividend_relative_error: float = pa.Field(ge=0)
    factor_ratio_rtol: float = pa.Field(ge=0)
    status: str = pa.Field(
        isin=[
            "NO_EVENT_STABLE_FACTOR",
            "MATCHED_EVENT_DECLARED_FORMULA",
            "MATCHED_EVENT_MARKET_REFERENCE",
            "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE",
            "MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA",
        ]
    )
    source: str = pa.Field(isin=["tushare"])

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def reconciliation_semantics_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """状态条件字段、日期递增、rtol 上界与唯一键。"""
        lf = data.lazyframe
        dates_ok = pl.col("previous_factor_date") < pl.col("effective_date")
        rtol_ok = (
            pl.col("factor_ratio_rtol").is_finite()
            & (pl.col("factor_ratio_rtol") <= 0.01)
            & pl.col("declared_dividend_relative_error").is_finite()
            & (
                pl.col("market_reference_relative_error").is_null()
                | pl.col("market_reference_relative_error").is_finite()
            )
        )
        rights_consistent = (
            pl.col("rights_ratio").is_finite()
            & pl.col("rights_subscription_cash_per_share").is_finite()
            & (
                (pl.col("rights_ratio") > 0)
                == (pl.col("rights_subscription_cash_per_share") > 0)
            )
        )
        no_event = (
            (pl.col("status") == "NO_EVENT_STABLE_FACTOR")
            & (pl.col("event_count") == 0)
            & (pl.col("stock_ratio_terms_json") == "[]")
            & (pl.col("cash_per_share_gross") == 0)
            & (pl.col("stock_ratio") == 0)
            & (pl.col("rights_ratio") == 0)
            & (pl.col("rights_subscription_cash_per_share") == 0)
            & pl.col("previous_close_date").is_null()
            & pl.col("previous_close").is_null()
            & pl.col("ex_reference_price").is_null()
            & pl.col("market_reference_factor_ratio").is_null()
            & pl.col("market_reference_relative_error").is_null()
            & (pl.col("declared_dividend_factor_ratio") == 1.0)
        )
        # P0E: matched actual/market may be >1 or within the row's 1±rtol band.
        supported_actual = (pl.col("actual_factor_ratio") > 1.0) | (
            (pl.col("actual_factor_ratio") - 1.0).abs() <= pl.col("factor_ratio_rtol")
        )
        supported_market = (pl.col("market_reference_factor_ratio") > 1.0) | (
            (pl.col("market_reference_factor_ratio") - 1.0).abs()
            <= pl.col("factor_ratio_rtol")
        )
        matched_market = (
            (pl.col("status").is_in([
                "MATCHED_EVENT_DECLARED_FORMULA",
                "MATCHED_EVENT_MARKET_REFERENCE",
                "MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA",
            ]))
            & (pl.col("event_count") > 0)
            & (pl.col("stock_ratio_terms_json") != "[]")
            & (
                (pl.col("cash_per_share_gross") > 0)
                | (pl.col("stock_ratio") > 0)
                | (pl.col("rights_ratio") > 0)
            )
            & pl.col("previous_close_date").is_not_null()
            & (pl.col("previous_close_date") < pl.col("effective_date"))
            & pl.col("previous_close").is_not_null()
            & (pl.col("previous_close") > 0)
            & pl.col("ex_reference_price").is_not_null()
            & (pl.col("ex_reference_price") > 0)
            & pl.col("market_reference_factor_ratio").is_not_null()
            & supported_market
            & (pl.col("declared_dividend_factor_ratio") > 1)
            & supported_actual
            & pl.col("market_reference_relative_error").is_not_null()
        )
        matched_declared = (
            (pl.col("status") == "MATCHED_EVENT_DECLARED_FORMULA")
            & (
                pl.col("declared_dividend_relative_error")
                <= pl.col("factor_ratio_rtol")
            )
            & (
                pl.col("market_reference_relative_error")
                <= pl.col("factor_ratio_rtol")
            )
        )
        matched_market_ref = (
            (pl.col("status") == "MATCHED_EVENT_MARKET_REFERENCE")
            & (
                pl.col("declared_dividend_relative_error")
                > pl.col("factor_ratio_rtol")
            )
            & (
                pl.col("market_reference_relative_error")
                <= pl.col("factor_ratio_rtol")
            )
        )
        matched_basis_normalized = (
            (
                pl.col("status")
                == "MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA"
            )
            & (
                pl.col("declared_dividend_relative_error")
                <= pl.col("factor_ratio_rtol")
            )
            & (
                pl.col("market_reference_relative_error")
                > pl.col("factor_ratio_rtol")
            )
        )
        matched_no_ref = (
            (pl.col("status") == "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE")
            & (pl.col("event_count") > 0)
            & (pl.col("stock_ratio_terms_json") != "[]")
            & (
                (pl.col("cash_per_share_gross") > 0)
                | (pl.col("stock_ratio") > 0)
                | (pl.col("rights_ratio") > 0)
            )
            & pl.col("previous_close_date").is_not_null()
            & (pl.col("previous_close_date") < pl.col("effective_date"))
            & pl.col("previous_close").is_not_null()
            & (pl.col("previous_close") > 0)
            & pl.col("ex_reference_price").is_null()
            & pl.col("market_reference_factor_ratio").is_null()
            & pl.col("market_reference_relative_error").is_null()
            & (pl.col("declared_dividend_factor_ratio") > 1)
            & supported_actual
            & (
                pl.col("declared_dividend_relative_error")
                <= pl.col("factor_ratio_rtol")
            )
        )
        status_ok = (
            no_event
            | (matched_market & matched_declared)
            | (matched_market & matched_market_ref)
            | (matched_market & matched_basis_normalized)
            | matched_no_ref
        )
        return lf.select(
            (
                dates_ok.all()
                & rtol_ok.all()
                & rights_consistent.all()
                & status_ok.all()
                & _unique_expr(["symbol", "effective_date", "source"])
            ).alias("reconciliation_semantics_valid")
        )


class PriceLimit1dSchema(pa.DataFrameModel):
    """执行模拟使用的 A 股每日未复权涨跌停价。"""

    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    trade_date: pl.Date
    pre_close: float = pa.Field(gt=0)
    has_price_limit: bool
    up_limit: float = pa.Field(gt=0, nullable=True)
    down_limit: float = pa.Field(gt=0, nullable=True)
    source: str
    source_snapshot_id: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def limit_fields_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同源证券日唯一，且昨收严格位于上下限之间。"""
        limited_row = pl.all_horizontal(
            pl.col("up_limit").is_not_null(),
            pl.col("down_limit").is_not_null(),
            pl.col("up_limit").is_finite(),
            pl.col("down_limit").is_finite(),
            pl.col("down_limit") < pl.col("pre_close"),
            pl.col("pre_close") < pl.col("up_limit"),
        )
        unlimited_row = (
            pl.col("up_limit").is_null() & pl.col("down_limit").is_null()
        )
        return data.lazyframe.select(
            (
                (
                    pl.col("pre_close").is_finite()
                    & pl.when(pl.col("has_price_limit"))
                    .then(limited_row)
                    .otherwise(unlimited_row)
                ).all()
                & _unique_expr(["symbol", "trade_date", "source"])
            ).alias("limit_fields_valid")
        )


class IndexConstituentObservationSchema(pa.DataFrameModel):
    """指数成分月度观察快照（B3）；集合规则由消费边界显式执行。"""

    universe: str = pa.Field(isin=["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"])
    observation_date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    weight: float = pa.Field(gt=0)
    source: str = pa.Field(isin=["tushare"])
    source_snapshot_id: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def observation_fields_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """权重必须有限，且观察键唯一。"""
        return data.lazyframe.select(
            (
                pl.col("weight").is_finite().all()
                & _unique_expr(
                    ["universe", "observation_date", "symbol", "source"]
                )
            ).alias("observation_fields_valid")
        )


class UniverseMembershipSchema(pa.DataFrameModel):
    """历史股票池成员 universe_membership(时点有效区间)。"""

    universe: str  # 例如 CSI300 / HKConnect / ETF_POOL_CORE
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    effective_from: pl.Date
    effective_to: pl.Date = pa.Field(nullable=True)  # null 表示至今有效

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def membership_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """成员起始记录唯一，且有效期不倒置。"""
        return data.lazyframe.select(
            (
                (
                    pl.col("effective_to").is_null()
                    | (pl.col("effective_to") >= pl.col("effective_from"))
                ).all()
                & _unique_expr(["universe", "symbol", "effective_from"])
            ).alias("membership_valid")
        )


class ConnectEligibilitySnapshotSchema(pa.DataFrameModel):
    """港股通当前标的快照；快照不是历史区间，必须保留 snapshot_date。"""

    route: str = pa.Field(isin=["SH_CONNECT", "SZ_CONNECT"])
    snapshot_date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{5}\.HK$")
    name_cn: str
    name_en: str
    security_type: str = pa.Field(isin=["STOCK", "ETF", "OTHER"])
    buy_eligible: bool
    source: str = pa.Field(isin=["sse", "szse"])

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["route", "snapshot_date", "symbol"])


class ConnectEligibilityEventSchema(pa.DataFrameModel):
    """港股通标的调入/调出事件，以官方生效日为准。"""

    route: str = pa.Field(isin=["SH_CONNECT", "SZ_CONNECT"])
    effective_date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{5}\.HK$")
    action: str = pa.Field(isin=["ADD", "REMOVE"])
    name_cn: str
    name_en: str
    security_type: str = pa.Field(isin=["STOCK", "ETF", "OTHER"])
    published_date: pl.Date = pa.Field(nullable=True)
    source: str = pa.Field(isin=["sse", "szse"])

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["route", "effective_date", "symbol", "action"])


class ConnectCalendarSchema(pa.DataFrameModel):
    """按沪/深港股通路由区分的可交易日历。"""

    route: str = pa.Field(isin=["SH_CONNECT", "SZ_CONNECT"])
    date: pl.Date
    is_open: bool
    is_half_day: bool
    holiday_name: str = pa.Field(nullable=True)
    source: str = pa.Field(isin=["sse", "szse"])

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["route", "date"])


class FactorValueSchema(pa.DataFrameModel):
    """因子值 factor_value。"""

    as_of: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    factor: str
    value: float = pa.Field(nullable=True)
    factor_version: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def factor_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """因子版本在同一时点、证券和因子名下只能有一个值。"""
        return _rows_are_unique(
            data, ["as_of", "symbol", "factor", "factor_version"]
        )


class BenchmarkBar1dSchema(pa.DataFrameModel):
    """不可交易基准日线（价格指数兼容码或全收益指数），非 Bar1d 证券行情。"""

    benchmark: str = pa.Field(str_matches=BENCHMARK_PATTERN)
    trade_date: pl.Date
    open: float = pa.Field(gt=0)
    high: float = pa.Field(gt=0)
    low: float = pa.Field(gt=0)
    close: float = pa.Field(gt=0)
    source: str
    source_snapshot_id: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def ohlc_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """OHLC 合法性: low <= open/close <= high。"""
        return data.lazyframe.select(
            (pl.col("high") >= pl.col("low"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
            & (pl.col("low") <= pl.col("open"))
            & (pl.col("low") <= pl.col("close"))
        )

    @pa.dataframe_check
    def benchmark_date_source_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同一来源的基准日线只能有一条。"""
        return _rows_are_unique(data, ["benchmark", "trade_date", "source"])


class Suspension1dSchema(pa.DataFrameModel):
    """停牌日表；FULL_DAY 与 PARTIAL 互斥且与 detail 一一对应。"""

    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    trade_date: pl.Date
    suspension_scope: str = pa.Field(isin=["FULL_DAY", "PARTIAL"])
    suspension_detail: str = pa.Field(nullable=True)
    source: str
    source_snapshot_id: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def suspension_semantics_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """FULL_DAY 当且仅当 detail=null；PARTIAL 当且仅当 detail 非空；键唯一。"""
        scope_ok = (
            (
                (pl.col("suspension_scope") == "FULL_DAY")
                & pl.col("suspension_detail").is_null()
            )
            | (
                (pl.col("suspension_scope") == "PARTIAL")
                & pl.col("suspension_detail").is_not_null()
                & (pl.col("suspension_detail").str.len_chars() > 0)
            )
        )
        source_ok = (
            (pl.col("source").str.len_chars() > 0)
            & (pl.col("source_snapshot_id").str.len_chars() > 0)
            & (~pl.col("source").str.contains(r"[\x00-\x1f]"))
            & (~pl.col("source_snapshot_id").str.contains(r"[\x00-\x1f]"))
        )
        return data.lazyframe.select(
            (scope_ok.all() & source_ok.all() & _unique_expr(["symbol", "trade_date", "source"]))
            .alias("suspension_semantics_valid")
        )


class ForwardReturnLabelSchema(pa.DataFrameModel):
    """M3 监督学习标签：下一交易日开盘至未来收盘的基准相对收益。"""

    as_of: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    benchmark: str = pa.Field(str_matches=BENCHMARK_PATTERN)
    horizon_sessions: int = pa.Field(gt=0)
    return_start_date: pl.Date
    return_end_date: pl.Date
    available_as_of: pl.Date
    raw_return: float
    benchmark_return: float
    relative_return: float
    label_version: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def label_semantics_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """标签只能在收益区间结束后可知，且相对收益必须可复算。"""
        return data.lazyframe.select(
            (
                (pl.col("return_start_date") > pl.col("as_of"))
                & (pl.col("return_end_date") >= pl.col("return_start_date"))
                & (pl.col("available_as_of") >= pl.col("return_end_date"))
                & pl.col("raw_return").is_finite()
                & pl.col("benchmark_return").is_finite()
                & pl.col("relative_return").is_finite()
                & (
                    (
                        pl.col("relative_return")
                        - (pl.col("raw_return") - pl.col("benchmark_return"))
                    ).abs()
                    <= 1e-10
                )
            ).all()
        )

    @pa.dataframe_check
    def label_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return _rows_are_unique(
            data,
            ["as_of", "symbol", "benchmark", "horizon_sessions", "label_version"],
        )


class PredictionScoreSchema(pa.DataFrameModel):
    """M3 模型输出；Qlib/LightGBM 与组合策略之间的唯一预测契约。"""

    as_of: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    score: float
    rank: int = pa.Field(gt=0)
    model: str
    model_version: str
    dataset_snapshot_id: str
    fold: str
    horizon_sessions: int = pa.Field(gt=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def scores_finite(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return data.lazyframe.select(pl.col("score").is_finite().all())

    @pa.dataframe_check
    def prediction_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return _rows_are_unique(
            data,
            [
                "as_of",
                "symbol",
                "model",
                "model_version",
                "dataset_snapshot_id",
                "fold",
                "horizon_sessions",
            ],
        )

    @pa.dataframe_check
    def rank_unique_per_cross_section(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return (
            data.lazyframe.group_by(
                "as_of",
                "model",
                "model_version",
                "dataset_snapshot_id",
                "fold",
                "horizon_sessions",
            )
            .agg((pl.col("rank").n_unique() == pl.len()).alias("rank_unique"))
            .select(pl.col("rank_unique").all())
        )


class TargetWeightSchema(pa.DataFrameModel):
    """统一目标权重 target_weight:研究面与交易面的唯一交汇接口。"""

    as_of: pl.Date
    strategy: str  # type: ignore[assignment]  # Pandera 基类存在同名方法
    strategy_version: str
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    weight: float = pa.Field(ge=0.0, le=1.0)  # MVP 只做多头

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def weights_sum_leq_one(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同一策略版本的权重和不超过 1(允许留现金)。"""
        return (
            data.lazyframe.group_by("as_of", "strategy", "strategy_version")
            .agg(pl.col("weight").sum().alias("w"))
            .select(pl.col("w") <= 1.0 + 1e-9)
        )

    @pa.dataframe_check
    def target_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """同一策略版本不能为同一证券输出重复权重。"""
        return _rows_are_unique(
            data, ["as_of", "strategy", "strategy_version", "symbol"]
        )


class OpenExecutionStateSchema(pa.DataFrameModel):
    """A-share opening facts projected without future intraday information."""

    date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    open: float = pa.Field(gt=0, nullable=True)
    has_open: bool
    full_day_suspended: bool
    partial_open_status: str = pa.Field(
        isin=[
            "NOT_APPLICABLE",
            "SUSPENDED_AT_OPEN",
            "PROVEN_OPEN_TRADABLE",
            "OPEN_UNKNOWN",
        ]
    )
    has_price_limit: bool
    up_limit: float = pa.Field(gt=0, nullable=True)
    down_limit: float = pa.Field(gt=0, nullable=True)
    buy_allowed: bool
    sell_allowed: bool
    reason: str = pa.Field(
        nullable=True,
        isin=["SUSPENDED", "OPEN_UNKNOWN", "MISSING_OPEN"],
    )

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def state_fields_consistent(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        frame = data.lazyframe
        open_consistent = pl.col("has_open") == pl.col("open").is_not_null()
        limits_consistent = pl.when(pl.col("has_price_limit")).then(
            pl.col("up_limit").is_not_null()
            & pl.col("down_limit").is_not_null()
            & (pl.col("down_limit") < pl.col("up_limit"))
        ).otherwise(
            pl.col("up_limit").is_null() & pl.col("down_limit").is_null()
        )
        blocked_consistent = pl.when(pl.col("reason").is_not_null()).then(
            ~pl.col("buy_allowed") & ~pl.col("sell_allowed")
        ).otherwise(pl.lit(True))
        full_day_consistent = pl.when(pl.col("full_day_suspended")).then(
            (pl.col("partial_open_status") == "NOT_APPLICABLE")
            & (pl.col("reason") == "SUSPENDED")
        ).otherwise(pl.lit(True))
        return frame.select(
            (
                open_consistent
                & limits_consistent
                & blocked_consistent
                & full_day_consistent
                & _unique_expr(["date", "symbol"])
            ).all()
        )


class AShareSimulationNavSchema(pa.DataFrameModel):
    date: pl.Date = pa.Field(unique=True)
    pre_trade_equity: float = pa.Field(ge=0)
    cash: float = pa.Field(ge=0)
    market_value: float = pa.Field(ge=0)
    cash_receivable: float = pa.Field(ge=0)
    stock_receivable_value: float = pa.Field(ge=0)
    equity: float = pa.Field(ge=0)
    unit_nav: float = pa.Field(ge=0)
    daily_return: float
    cumulative_commission: float = pa.Field(ge=0)
    cumulative_stamp_tax: float = pa.Field(ge=0)
    cumulative_transfer_fee: float = pa.Field(ge=0)
    cumulative_slippage_cost: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def finite_and_balanced(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        numeric = [name for name in cls.to_schema().columns if name != "date"]
        return data.lazyframe.select(
            pl.all_horizontal(*(pl.col(name).is_finite() for name in numeric)).all()
            & (
                pl.col("equity")
                == pl.col("cash")
                + pl.col("market_value")
                + pl.col("cash_receivable")
                + pl.col("stock_receivable_value")
            ).all()
        )


class AShareSimulationTradeSchema(pa.DataFrameModel):
    date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    side: str = pa.Field(isin=[item.value for item in OrderSide])
    quantity: int = pa.Field(gt=0)
    reference_open: float = pa.Field(gt=0)
    execution_price: float = pa.Field(gt=0)
    notional: float = pa.Field(gt=0)
    commission: float = pa.Field(ge=0)
    stamp_tax: float = pa.Field(ge=0)
    transfer_fee: float = pa.Field(ge=0)
    total_fee: float = pa.Field(ge=0)
    slippage_cost: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def unique_and_balanced(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return data.lazyframe.select(
            _unique_expr(["date", "symbol", "side"])
            & (pl.col("notional") == pl.col("quantity") * pl.col("execution_price")).all()
            & (
                pl.col("total_fee")
                == pl.col("commission") + pl.col("stamp_tax") + pl.col("transfer_fee")
            ).all()
        )


class AShareSimulationPositionSchema(pa.DataFrameModel):
    date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    quantity: int = pa.Field(gt=0)
    sellable_quantity: int = pa.Field(ge=0)
    unsettled_quantity: int = pa.Field(ge=0)
    mark_price: float = pa.Field(gt=0)
    market_value: float = pa.Field(gt=0)
    target_weight: float = pa.Field(ge=0, le=1)
    target_quantity: int = pa.Field(nullable=True, ge=0)
    pending_exit: bool

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def unique_and_balanced(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return data.lazyframe.select(
            _unique_expr(["date", "symbol"])
            & (
                pl.col("quantity")
                == pl.col("sellable_quantity") + pl.col("unsettled_quantity")
            ).all()
            & (
                pl.col("market_value") == pl.col("quantity") * pl.col("mark_price")
            ).all()
        )


class AShareSimulationRejectionSchema(pa.DataFrameModel):
    date: pl.Date
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    side: str = pa.Field(isin=[item.value for item in OrderSide])
    reason: str = pa.Field(isin=[item.value for item in ExecutionRejectReason])
    requested_quantity: int = pa.Field(nullable=True, ge=0)
    filled_quantity: int = pa.Field(ge=0)
    rejected_quantity: int = pa.Field(nullable=True, ge=0)
    rejected_notional: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return data.lazyframe.select(
            _unique_expr(["date", "symbol", "side", "reason"])
        )


class AShareCorporateActionPostingSchema(pa.DataFrameModel):
    date: pl.Date
    event_id: str
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    posting_type: str = pa.Field(isin=[item.value for item in EntitlementPostingType])
    cash_amount: float
    stock_quantity: int = pa.Field(ge=0)
    cash_rounding_delta: float
    cash_state_before: str = pa.Field(isin=[item.value for item in EntitlementLegState])
    cash_state_after: str = pa.Field(isin=[item.value for item in EntitlementLegState])
    stock_state_before: str = pa.Field(isin=[item.value for item in EntitlementLegState])
    stock_state_after: str = pa.Field(isin=[item.value for item in EntitlementLegState])

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return data.lazyframe.select(
            _unique_expr(["date", "event_id", "posting_type"])
        )


class AShareDailyDiagnosticsSchema(pa.DataFrameModel):
    date: pl.Date = pa.Field(unique=True)
    n_target_symbols: int = pa.Field(ge=0)
    n_position_symbols: int = pa.Field(ge=0)
    n_order_intents: int = pa.Field(ge=0)
    n_trades: int = pa.Field(ge=0)
    n_rejections: int = pa.Field(ge=0)
    pre_trade_equity: float = pa.Field(gt=0)
    gross_turnover: float = pa.Field(ge=0)
    one_way_turnover: float = pa.Field(ge=0)
    buy_allocation_lambda: float = pa.Field(nullable=True, ge=0, le=1)
    cash_after: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = False


class AShareEntitlementSnapshotSchema(pa.DataFrameModel):
    date: pl.Date
    event_id: str
    symbol: str = pa.Field(str_matches=r"^\d{6}\.(SH|SZ)$")
    record_quantity: int = pa.Field(gt=0)
    cash_entitlement_gross: float = pa.Field(ge=0)
    stock_entitlement: int = pa.Field(ge=0)
    cash_state: str = pa.Field(isin=[item.value for item in EntitlementLegState])
    stock_state: str = pa.Field(isin=[item.value for item in EntitlementLegState])
    cash_receivable: float = pa.Field(ge=0)
    stock_receivable: int = pa.Field(ge=0)
    stock_receivable_value: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = False

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return data.lazyframe.select(_unique_expr(["date", "event_id"]))


class BacktestNavSchema(pa.DataFrameModel):
    """日频回测账户净值。"""

    strategy: str  # type: ignore[assignment]
    date: pl.Date
    equity: float = pa.Field(ge=0)
    unit_nav: float = pa.Field(ge=0)
    cash: float = pa.Field(ge=0)
    market_value: float = pa.Field(ge=0)
    cumulative_fees: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        expected_equity = pl.col("cash") + pl.col("market_value")
        tolerance = pl.max_horizontal(
            pl.lit(1.0), expected_equity.abs()
        ) * 1e-9
        numeric = [
            "equity",
            "unit_nav",
            "cash",
            "market_value",
            "cumulative_fees",
        ]
        return data.lazyframe.select(
            (
                _unique_expr(["strategy", "date"])
                & pl.all_horizontal(
                    [pl.col(column).is_finite() for column in numeric]
                ).all()
                & (
                    (pl.col("equity") - expected_equity).abs()
                    <= tolerance
                ).all()
            ).alias("nav_valid")
        )


class BacktestTradeSchema(pa.DataFrameModel):
    """日频回测的模拟成交。"""

    strategy: str  # type: ignore[assignment]
    date: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    side: str = pa.Field(isin=["BUY", "SELL"])
    quantity: int = pa.Field(gt=0)
    price: float = pa.Field(gt=0)
    notional: float = pa.Field(gt=0)
    fee: float = pa.Field(ge=0)
    slippage_cost: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True


class BacktestPositionSchema(pa.DataFrameModel):
    """日频回测的证券持仓证据。"""

    strategy: str  # type: ignore[assignment]
    date: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    quantity: int = pa.Field(ge=0)
    settled_quantity: int = pa.Field(ge=0)
    unsettled_quantity: int = pa.Field(ge=0)
    mark_price: float = pa.Field(gt=0)
    market_value: float = pa.Field(ge=0)
    target_weight: float = pa.Field(ge=0, le=1, nullable=True)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def position_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        expected_value = (
            pl.col("quantity").cast(pl.Float64) * pl.col("mark_price")
        )
        tolerance = pl.max_horizontal(
            pl.lit(1.0), expected_value.abs()
        ) * 1e-9
        return data.lazyframe.select(
            (
                (
                    pl.col("quantity")
                    == pl.col("settled_quantity")
                    + pl.col("unsettled_quantity")
                ).all()
                & (
                    (pl.col("market_value") - expected_value).abs()
                    <= tolerance
                ).all()
                & pl.col("mark_price").is_finite().all()
                & pl.col("market_value").is_finite().all()
                & (
                    pl.col("target_weight").is_null()
                    | pl.col("target_weight").is_finite()
                ).all()
                & _unique_expr(["strategy", "date", "symbol"])
            ).alias("position_valid")
        )


class BacktestRejectionSchema(pa.DataFrameModel):
    """日频回测的完整执行拒绝证据。"""

    strategy: str  # type: ignore[assignment]
    date: pl.Date
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    side: str = pa.Field(isin=["BUY", "SELL"])
    reason: str = pa.Field(
        isin=[
            "SUSPENDED",
            "BUY_AT_UPPER_LIMIT",
            "SELL_AT_LOWER_LIMIT",
            "T_PLUS_ONE",
        ]
    )
    requested_quantity: int = pa.Field(gt=0)
    rejected_quantity: int = pa.Field(gt=0)
    reference_price: float = pa.Field(gt=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def rejection_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        side_matches = (
            (pl.col("reason") == "SUSPENDED")
            | (
                (pl.col("reason") == "BUY_AT_UPPER_LIMIT")
                & (pl.col("side") == "BUY")
            )
            | (
                pl.col("reason").is_in(
                    ["SELL_AT_LOWER_LIMIT", "T_PLUS_ONE"]
                )
                & (pl.col("side") == "SELL")
            )
        )
        return data.lazyframe.select(
            (
                (
                    pl.col("requested_quantity")
                    == pl.col("rejected_quantity")
                ).all()
                & side_matches.all()
                & pl.col("reference_price").is_finite().all()
                & _unique_expr(["strategy", "date", "symbol", "side"])
            ).alias("rejection_valid")
        )


class OrderSchema(pa.DataFrameModel):
    """订单 order(本地 OMS 视角;broker_order_id 用于幂等映射)。"""

    order_id: str = pa.Field(unique=True)
    broker_order_id: str = pa.Field(nullable=True)
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    side: str = pa.Field(isin=["BUY", "SELL"])
    quantity: int = pa.Field(gt=0)
    limit_price: float = pa.Field(gt=0, nullable=True)  # null 表示市价/对手价
    status: str = pa.Field(
        isin=[
            "CREATED",
            "SUBMITTED",
            "PARTIAL_FILLED",
            "FILLED",
            "CANCELLING",
            "CANCELLED",
            "REJECTED",
        ]
    )
    created_at: pl.Datetime
    updated_at: pl.Datetime

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def timestamps_ordered(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """订单更新时间不得早于创建时间。"""
        return data.lazyframe.select(pl.col("updated_at") >= pl.col("created_at"))


class FillSchema(pa.DataFrameModel):
    """成交回报 fill。"""

    fill_id: str = pa.Field(unique=True)
    order_id: str
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    side: str = pa.Field(isin=["BUY", "SELL"])
    quantity: int = pa.Field(gt=0)
    price: float = pa.Field(gt=0)
    fee: float = pa.Field(ge=0)
    filled_at: pl.Datetime

    class Config:
        strict = True
        coerce = True


class PositionSchema(pa.DataFrameModel):
    """持仓快照 position(对账后)。"""

    as_of: pl.Datetime
    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    quantity: int = pa.Field(ge=0)
    sellable: int = pa.Field(ge=0)  # T+1 下当日买入不可卖
    avg_cost: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def position_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """可卖数量不超过总持仓，且快照键唯一。"""
        return data.lazyframe.select(
            (
                (pl.col("sellable") <= pl.col("quantity")).all()
                & _unique_expr(["as_of", "symbol"])
            ).alias("position_valid")
        )


class CashSchema(pa.DataFrameModel):
    """资金快照 cash(分币种)。"""

    as_of: pl.Datetime
    currency: str = pa.Field(isin=["CNY", "HKD"])
    balance: float = pa.Field(ge=0)
    available: float = pa.Field(ge=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def cash_valid(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        """可用资金不超过余额，且币种快照键唯一。"""
        return data.lazyframe.select(
            (
                (pl.col("available") <= pl.col("balance")).all()
                & _unique_expr(["as_of", "currency"])
            ).alias("cash_valid")
        )


def _rows_are_unique(data: pa.PolarsData, columns: list[str]) -> pl.LazyFrame:
    """返回单值检查结果：指定复合键没有重复行。"""
    return data.lazyframe.select(_unique_expr(columns).alias("is_unique"))


def _hk_action_fields_consistent_expr() -> pl.Expr:
    """Shared four-branch economic-field invariant for HK canonical/evidence rows."""
    action = pl.col("action_type")
    cash = pl.col("cash_per_share_gross")
    stock = pl.col("stock_ratio")
    multiplier = pl.col("share_multiplier")
    rights_ratio = pl.col("rights_ratio")
    rights_price = pl.col("rights_subscription_price")
    rights_start = pl.col("rights_subscription_start")
    rights_end = pl.col("rights_subscription_end")
    currency = pl.col("declared_currency")
    pay = pl.col("pay_date")
    list_date = pl.col("stock_list_date")
    common = (
        (pl.col("record_date") <= pl.col("ex_date"))
        & (cash.is_null() | cash.is_finite())
        & (stock.is_null() | stock.is_finite())
        & (multiplier.is_null() | multiplier.is_finite())
        & (rights_ratio.is_null() | rights_ratio.is_finite())
        & (rights_price.is_null() | rights_price.is_finite())
    )
    dividend = (
        (action == "DIVIDEND")
        & currency.is_not_null()
        & cash.is_not_null()
        & pay.is_not_null()
        & (pay >= pl.col("ex_date"))
        & stock.is_null()
        & multiplier.is_null()
        & rights_ratio.is_null()
        & rights_price.is_null()
        & rights_start.is_null()
        & rights_end.is_null()
        & list_date.is_null()
    )
    bonus = (
        (action == "BONUS")
        & currency.is_null()
        & cash.is_null()
        & stock.is_not_null()
        & multiplier.is_null()
        & rights_ratio.is_null()
        & rights_price.is_null()
        & rights_start.is_null()
        & rights_end.is_null()
        & pay.is_null()
        & list_date.is_not_null()
        & (list_date >= pl.col("ex_date"))
    )
    split = (
        (action == "SPLIT")
        & currency.is_null()
        & cash.is_null()
        & stock.is_null()
        & multiplier.is_not_null()
        & (multiplier != 1.0)
        & rights_ratio.is_null()
        & rights_price.is_null()
        & rights_start.is_null()
        & rights_end.is_null()
        & pay.is_null()
        & list_date.is_not_null()
        & (list_date >= pl.col("ex_date"))
    )
    rights = (
        (action == "RIGHTS")
        & currency.is_not_null()
        & cash.is_null()
        & stock.is_null()
        & multiplier.is_null()
        & rights_ratio.is_not_null()
        & rights_price.is_not_null()
        & rights_start.is_not_null()
        & rights_end.is_not_null()
        & pay.is_null()
        & list_date.is_not_null()
        & (pl.col("ex_date") <= rights_start)
        & (rights_start <= rights_end)
        & (rights_end <= list_date)
    )
    return common & (dividend | bonus | split | rights)


def _unique_expr(columns: list[str]) -> pl.Expr:
    """构造复合键唯一性的 Polars 表达式。"""
    return pl.struct(columns).n_unique() == pl.len()
