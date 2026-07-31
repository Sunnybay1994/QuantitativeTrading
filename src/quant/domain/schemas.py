"""核心数据契约(调研文档 3.2 节标准表)。

以 Pandera Polars schema 定义 clean 层各标准表的结构与领域约束。
所有下游(因子、策略、回测、执行)只依赖这些契约,不依赖任何数据源的原始字段。

约定:
- symbol 统一为 "000001.SZ" / "600000.SH" / "00700.HK" 风格。
- 时间字段:trade_date 为交易日(Date);as_of 为信号可知时间。
- 金额单位:人民币/港币元;成交量单位:股(不是手)。
"""

import pandera.polars as pa
import polars as pl

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
        isin=["HFQ", "TOTAL_RETURN_DIVIDEND", "CUMULATIVE_FACTOR"]
    )
    source: str

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def key_unique(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        return _rows_are_unique(data, ["symbol", "trade_date"])


class CorporateActionSchema(pa.DataFrameModel):
    """公司行动 corporate_action。"""

    symbol: str = pa.Field(str_matches=SYMBOL_PATTERN)
    ex_date: pl.Date
    action_type: str = pa.Field(isin=["DIVIDEND", "BONUS", "SPLIT", "RIGHTS"])
    cash_per_share: float = pa.Field(ge=0, nullable=True)
    share_ratio: float = pa.Field(ge=0, nullable=True)
    announce_time: pl.Datetime  # PIT:真实披露时间
    source: str

    class Config:
        strict = True
        coerce = True


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
    def prediction_key_unique(  # type: ignore[misc]
        cls, data: pa.PolarsData
    ) -> pl.LazyFrame:
        return _rows_are_unique(
            data,
            [
                "as_of",
                "symbol",
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
        return _rows_are_unique(data, ["strategy", "date"])


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


def _unique_expr(columns: list[str]) -> pl.Expr:
    """构造复合键唯一性的 Polars 表达式。"""
    return pl.struct(columns).n_unique() == pl.len()
