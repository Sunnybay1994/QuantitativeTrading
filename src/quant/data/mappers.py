"""供应商原始字段到 clean 数据契约的显式映射。"""

import datetime as dt
import re

from typing import Protocol

import polars as pl


class BarMapper(Protocol):
    """数据源日线映射器协议。"""

    source: str

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        """把供应商原始字段映射为 canonical bar_1d。"""
        ...


class CalendarMapper(Protocol):
    """数据源交易日历映射器协议。"""

    source: str

    def map(self, raw: pl.DataFrame) -> pl.DataFrame: ...


class InstrumentMapper(Protocol):
    """数据源证券主表映射器协议。"""

    source: str

    def map(self, raw: pl.DataFrame) -> pl.DataFrame: ...


class AdjustmentFactorMapper(Protocol):
    """累计后复权因子映射器协议。"""

    source: str

    def map(self, raw: pl.DataFrame) -> pl.DataFrame: ...


class AkshareBarMapper:
    """映射 AKShare A/H 股不复权日线原始响应。"""

    source = "akshare"
    chinese_columns = {"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"}
    english_columns = {"date", "open", "high", "low", "close", "volume", "amount"}

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        """保留 canonical 字段；不复权响应的基准复权因子记为 1。"""
        if "_request_symbol" not in raw.columns:
            raise ValueError("AKShare bar_1d 缺少字段: _request_symbol")
        columns = set(raw.columns)
        if self.chinese_columns.issubset(columns):
            names = {
                "date": "日期",
                "open": "开盘",
                "high": "最高",
                "low": "最低",
                "close": "收盘",
                "volume": "成交量",
                "amount": "成交额",
            }
        elif self.english_columns.issubset(columns):
            names = {name: name for name in self.english_columns}
        else:
            expected = sorted(self.chinese_columns | self.english_columns)
            raise ValueError(f"AKShare bar_1d 字段不匹配，期望中英文列集之一: {expected}")
        volume = pl.col(names["volume"]).cast(pl.Float64)
        if "_endpoint" in raw.columns:
            volume = (
                volume
                * pl.when(
                    pl.col("_endpoint").is_in(["stock_zh_a_hist", "fund_etf_hist_em"])
                )
                .then(pl.lit(100.0))
                .otherwise(pl.lit(1.0))
            )
        return raw.select(
            pl.col("_request_symbol").cast(pl.String).alias("symbol"),
            pl.col(names["date"]).cast(pl.Date).alias("trade_date"),
            pl.col(names["open"]).cast(pl.Float64).alias("open"),
            pl.col(names["high"]).cast(pl.Float64).alias("high"),
            pl.col(names["low"]).cast(pl.Float64).alias("low"),
            pl.col(names["close"]).cast(pl.Float64).alias("close"),
            volume.alias("volume"),
            pl.col(names["amount"]).cast(pl.Float64).alias("amount"),
            pl.lit(1.0, dtype=pl.Float64).alias("adj_factor"),
            pl.lit(self.source).alias("source"),
        )


class AkshareResearchPriceMapper:
    """映射 AKShare ETF 后复权收盘价到研究专用契约。"""

    source = "akshare"

    def __init__(self, source: str = "akshare") -> None:
        self.source = source

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"_request_symbol", "_adjustment", "日期", "收盘"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"AKShare research_price_1d 缺少字段: {', '.join(missing)}")
        allowed = {"hfq", "total_return_dividend"}
        if raw.filter(~pl.col("_adjustment").is_in(allowed)).height:
            raise ValueError("研究价格 mapper 只接受 hfq 或现金分红总回报响应")
        if "_cash_dividend" not in raw.columns:
            raw = raw.with_columns(pl.lit(0.0).alias("_cash_dividend"))
        prepared = raw.select(
            pl.col("_request_symbol").cast(pl.String).alias("symbol"),
            pl.col("日期").cast(pl.String).str.to_date().alias("trade_date"),
            pl.col("收盘").cast(pl.Float64, strict=False).alias("raw_close"),
            pl.col("_cash_dividend").cast(pl.Float64).fill_null(0.0),
            pl.col("_adjustment"),
        ).sort(["symbol", "trade_date"])
        gross_return = (
            (pl.col("raw_close") + pl.col("_cash_dividend"))
            / pl.col("raw_close").shift(1).over("symbol")
        ).fill_null(1.0)
        return prepared.with_columns(
            pl.when(pl.col("_adjustment") == "hfq")
            .then(pl.col("raw_close"))
            .otherwise(
                gross_return.cum_prod().over("symbol")
                * pl.col("raw_close").first().over("symbol")
            )
            .alias("adjusted_close")
        ).select(
            "symbol",
            "trade_date",
            "adjusted_close",
            pl.when(pl.col("_adjustment") == "hfq")
            .then(pl.lit("HFQ"))
            .otherwise(pl.lit("TOTAL_RETURN_DIVIDEND"))
            .alias("adjustment_method"),
            pl.lit(self.source).alias("source"),
        )


class BaostockBarMapper:
    """映射 BaoStock 不复权 A 股日线。"""

    source = "baostock"
    required_columns = {
        "_request_symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    }

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        """过滤非交易状态行并映射 canonical bar_1d。"""
        missing = sorted(self.required_columns - set(raw.columns))
        if missing:
            raise ValueError(f"BaoStock bar_1d 缺少字段: {', '.join(missing)}")
        tradable = raw.filter(pl.col("tradestatus") == "1") if "tradestatus" in raw.columns else raw
        return tradable.select(
            pl.col("_request_symbol").cast(pl.String).alias("symbol"),
            pl.col("date").str.to_date().alias("trade_date"),
            pl.col("open").cast(pl.Float64, strict=False).alias("open"),
            pl.col("high").cast(pl.Float64, strict=False).alias("high"),
            pl.col("low").cast(pl.Float64, strict=False).alias("low"),
            pl.col("close").cast(pl.Float64, strict=False).alias("close"),
            pl.col("volume").cast(pl.Float64, strict=False).alias("volume"),
            pl.col("amount").cast(pl.Float64, strict=False).alias("amount"),
            pl.lit(1.0, dtype=pl.Float64).alias("adj_factor"),
            pl.lit(self.source).alias("source"),
        )


class BaostockCalendarMapper:
    """映射 BaoStock 沪深交易日历。"""

    source = "baostock"

    def __init__(self, market: str) -> None:
        if market not in {"SH", "SZ"}:
            raise ValueError(f"BaoStock 日历只支持沪深市场: {market}")
        self.market = market

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"calendar_date", "is_trading_day"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"BaoStock trade_calendar 缺少字段: {', '.join(missing)}")
        return raw.select(
            pl.lit(self.market).alias("market"),
            pl.col("calendar_date").str.to_date().alias("date"),
            (pl.col("is_trading_day") == "1").alias("is_open"),
            pl.lit(False).alias("is_connect_open"),
            pl.lit(False).alias("is_half_day"),
        )


class BaostockInstrumentMapper:
    """映射 BaoStock 沪深股票和 ETF 证券主表。"""

    source = "baostock"

    def __init__(self, market: str) -> None:
        if market not in {"SH", "SZ"}:
            raise ValueError(f"BaoStock 证券主表只支持沪深市场: {market}")
        self.market = market

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"code", "code_name", "ipoDate", "outDate", "type", "status"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"BaoStock instrument 缺少字段: {', '.join(missing)}")
        prefix = self.market.lower() + "."
        selected = raw.filter(
            pl.col("code").str.starts_with(prefix) & pl.col("type").is_in(["1", "5"])
        )
        return selected.select(
            pl.concat_str(
                pl.col("code").str.split(".").list.get(1),
                pl.lit("."),
                pl.lit(self.market),
            ).alias("symbol"),
            pl.lit(self.market).alias("market"),
            pl.col("code_name").alias("name"),
            pl.when(pl.col("type") == "1")
            .then(pl.lit("STOCK"))
            .otherwise(pl.lit("ETF"))
            .alias("instrument_type"),
            pl.lit("CNY").alias("currency"),
            pl.col("ipoDate")
            .str.to_date(format="%Y-%m-%d", strict=False)
            .alias("list_date"),
            pl.col("outDate")
            .str.to_date(format="%Y-%m-%d", strict=False)
            .alias("delist_date"),
            pl.lit(100, dtype=pl.Int64).alias("board_lot"),
            pl.when(pl.col("status") == "1")
            .then(pl.lit("LISTED"))
            .otherwise(pl.lit("DELISTED"))
            .alias("status"),
        )


class BaostockAdjustmentFactorMapper:
    """映射 BaoStock 累计后复权因子。"""

    source = "baostock"

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"_request_symbol", "dividOperateDate", "backAdjustFactor"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"BaoStock adjust_factor 缺少字段: {', '.join(missing)}")
        if raw.is_empty():
            return _empty_adjustment_factors()
        return raw.select(
            pl.col("_request_symbol").alias("symbol"),
            pl.col("dividOperateDate")
            .str.to_date(format="%Y-%m-%d", strict=False)
            .alias("effective_date"),
            pl.col("backAdjustFactor")
            .cast(pl.Float64, strict=False)
            .alias("adj_factor"),
            pl.lit(self.source).alias("source"),
        )


_HK_CLOSE_ENVELOPE_MAX_RELATIVE_DEVIATION = 0.05


class TushareBarMapper:
    """映射 Tushare A/H 不复权日线并统一成交量、成交额单位。

    港股开盘/收市竞价价与供应商日内 high/low 可能采用不同口径。仅当原
    high/low 自洽时：若 close 位于原区间内，把 canonical 区间扩展至包含
    open；若全部 OHLC 有限为正、open 已在原区间、close 恰在一侧之外且
    相对最近正边界偏离不超过 5%，则扩展至包含 close。raw 值保持不变。
    A 股以及其他 OHLC 冲突继续交由 Schema fail closed。5% 只是脏数据
    防护上限，不是港交所价位表或 CAS 成交证明。
    """

    source = "tushare"

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {
            "_request_symbol", "_market", "trade_date", "open", "high", "low",
            "close", "vol", "amount",
        }
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"Tushare bar_1d 缺少字段: {', '.join(missing)}")
        is_a_share = pl.col("_market").is_in(["SH", "SZ"])
        open_price = pl.col("open").cast(pl.Float64)
        high_price = pl.col("high").cast(pl.Float64)
        low_price = pl.col("low").cast(pl.Float64)
        close_price = pl.col("close").cast(pl.Float64)
        hk_open_only_mismatch = (
            (pl.col("_market") == "HK")
            & (high_price >= low_price)
            & (close_price <= high_price)
            & (close_price >= low_price)
        )
        ohlc_finite_positive = (
            open_price.is_finite()
            & high_price.is_finite()
            & low_price.is_finite()
            & close_price.is_finite()
            & (open_price > 0)
            & (high_price > 0)
            & (low_price > 0)
            & (close_price > 0)
        )
        close_outside_high = close_price > high_price
        close_outside_low = close_price < low_price
        close_nearest_boundary_rel_dev = (
            pl.when(close_outside_high)
            .then((close_price - high_price) / high_price)
            .when(close_outside_low)
            .then((low_price - close_price) / low_price)
            .otherwise(pl.lit(float("inf")))
        )
        hk_close_only_mismatch = (
            (pl.col("_market") == "HK")
            & ohlc_finite_positive
            & (high_price >= low_price)
            & (open_price <= high_price)
            & (open_price >= low_price)
            & (close_outside_high | close_outside_low)
            & (
                close_nearest_boundary_rel_dev
                <= _HK_CLOSE_ENVELOPE_MAX_RELATIVE_DEVIATION
            )
        )
        return raw.select(
            pl.col("_request_symbol").alias("symbol"),
            pl.col("trade_date").str.to_date("%Y%m%d").alias("trade_date"),
            open_price.alias("open"),
            pl.when(hk_open_only_mismatch)
            .then(pl.max_horizontal(high_price, open_price))
            .when(hk_close_only_mismatch)
            .then(pl.max_horizontal(high_price, close_price))
            .otherwise(high_price)
            .alias("high"),
            pl.when(hk_open_only_mismatch)
            .then(pl.min_horizontal(low_price, open_price))
            .when(hk_close_only_mismatch)
            .then(pl.min_horizontal(low_price, close_price))
            .otherwise(low_price)
            .alias("low"),
            close_price.alias("close"),
            pl.when(is_a_share)
            .then(pl.col("vol").cast(pl.Float64) * 100.0)
            .otherwise(pl.col("vol").cast(pl.Float64))
            .alias("volume"),
            pl.when(is_a_share)
            .then(pl.col("amount").cast(pl.Float64) * 1000.0)
            .otherwise(pl.col("amount").cast(pl.Float64))
            .alias("amount"),
            pl.lit(1.0).alias("adj_factor"),
            pl.lit(self.source).alias("source"),
        )


class TushareAdjustmentFactorMapper:
    """映射 A 股 adj_factor 与港股 cum_adjfactor 为累计后复权因子。"""

    source = "tushare"

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        if raw.is_empty():
            return _empty_adjustment_factors()
        required = {"_request_symbol", "_market", "trade_date"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"Tushare adjust_factor 缺少字段: {', '.join(missing)}")
        if "adj_factor" not in raw.columns and "cum_adjfactor" not in raw.columns:
            raise ValueError("Tushare adjust_factor 缺少 adj_factor/cum_adjfactor")
        if "adj_factor" not in raw.columns:
            raw = raw.with_columns(pl.lit(None, dtype=pl.Float64).alias("adj_factor"))
        if "cum_adjfactor" not in raw.columns:
            raw = raw.with_columns(pl.lit(None, dtype=pl.Float64).alias("cum_adjfactor"))
        factor = (
            pl.when(pl.col("_market") == "HK")
            .then(pl.col("cum_adjfactor").cast(pl.Float64, strict=False))
            .otherwise(pl.col("adj_factor").cast(pl.Float64, strict=False))
        )
        mapped = raw.select(
            pl.col("_request_symbol").alias("symbol"),
            pl.col("trade_date").str.to_date("%Y%m%d").alias("effective_date"),
            factor.alias("adj_factor"),
            pl.lit(self.source).alias("source"),
        ).sort(["symbol", "effective_date"])
        previous = pl.col("adj_factor").shift(1).over("symbol")
        return mapped.filter(previous.is_null() | (pl.col("adj_factor") != previous))


def _empty_adjustment_factors() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.String,
            "effective_date": pl.Date,
            "adj_factor": pl.Float64,
            "source": pl.String,
        }
    )


class TushareCalendarMapper:
    """映射 Tushare 沪深/港交所基础交易日历。"""

    source = "tushare"

    def __init__(self, market: str) -> None:
        if market not in {"SH", "SZ", "HK"}:
            raise ValueError(f"Tushare 日历不支持市场: {market}")
        self.market = market

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"cal_date", "is_open"}
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"Tushare trade_calendar 缺少字段: {', '.join(missing)}")
        return raw.select(
            pl.lit(self.market).alias("market"),
            pl.col("cal_date").cast(pl.String).str.to_date("%Y%m%d").alias("date"),
            (pl.col("is_open").cast(pl.String) == "1").alias("is_open"),
            pl.lit(False).alias("is_connect_open"),
            pl.lit(False).alias("is_half_day"),
        )


class TushareInstrumentMapper:
    """映射 Tushare A/H 股票主表；ETF 仍由 ETF 专用接口补齐。"""

    source = "tushare"

    def __init__(self, market: str) -> None:
        if market not in {"SH", "SZ", "HK"}:
            raise ValueError(f"Tushare 证券主表不支持市场: {market}")
        self.market = market

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {
            "ts_code", "name", "list_date", "delist_date", "_request_list_status"
        }
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(f"Tushare instrument 缺少字段: {', '.join(missing)}")
        selected = raw.filter(
            pl.col("_request_list_status").is_in(["L", "D", "P"])
            & pl.col("list_date").is_not_null()
        )
        symbol_pattern = r"^\d{5}\.HK$" if self.market == "HK" else rf"^\d{{6}}\.{self.market}$"
        selected = selected.filter(pl.col("ts_code").str.contains(symbol_pattern))
        board_lot = (
            pl.col("trade_unit").cast(pl.Int64, strict=False)
            if self.market == "HK"
            else pl.lit(100, dtype=pl.Int64)
        )
        return selected.select(
            pl.col("ts_code").alias("symbol"),
            pl.lit(self.market).alias("market"),
            pl.col("name"),
            pl.lit("STOCK").alias("instrument_type"),
            pl.lit("HKD" if self.market == "HK" else "CNY").alias("currency"),
            pl.col("list_date").cast(pl.String).str.to_date("%Y%m%d").alias("list_date"),
            pl.col("delist_date")
            .cast(pl.String)
            .str.to_date("%Y%m%d", strict=False)
            .alias("delist_date"),
            board_lot.alias("board_lot"),
            pl.when(pl.col("_request_list_status") == "L")
            .then(pl.lit("LISTED"))
            .when(pl.col("_request_list_status") == "P")
            .then(pl.lit("SUSPENDED"))
            .otherwise(pl.lit("DELISTED"))
            .alias("status"),
        )


class HkexEtpInstrumentMapper:
    """Map exact HKEX ETP observations to the canonical Instrument contract."""

    source = "hkex"
    _symbol = re.compile(r"^\d{5}\.HK$")
    _identity_fields = (
        "first_trade_date",
        "lot_size",
        "name",
        "currency",
        "product_sub_category",
    )

    def __init__(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> None:
        if (
            not target_symbols
            or len(set(target_symbols)) != len(target_symbols)
            or tuple(sorted(target_symbols)) != target_symbols
            or any(
                type(symbol) is not str or not self._symbol.fullmatch(symbol)
                for symbol in target_symbols
            )
        ):
            raise ValueError("HKEX_ETP_TARGETS_INVALID")
        self.target_symbols = target_symbols
        self.as_of = as_of

    def map(self, raw: pl.DataFrame) -> pl.DataFrame:
        required = {"_request_symbol", "trade_date", *self._identity_fields}
        if not required.issubset(raw.columns):
            raise ValueError("HKEX_ETP_ROW_INVALID")
        chosen: list[dict[str, object]] = []
        for symbol in self.target_symbols:
            rows = raw.filter(pl.col("_request_symbol") == symbol).to_dicts()
            observations: list[tuple[dt.date, dict[str, object]]] = []
            for row in rows:
                trade_date = _epoch_milliseconds_date(row.get("trade_date"))
                if trade_date is not None and trade_date <= self.as_of:
                    observations.append((trade_date, row))
            if not observations:
                raise ValueError("HKEX_ETP_COVERAGE_INCOMPLETE")
            latest_date = max(date for date, _ in observations)
            latest = [row for date, row in observations if date == latest_date]
            identities = {
                tuple(_hashable_identity(row.get(field)) for field in self._identity_fields)
                for row in latest
            }
            if len(identities) != 1:
                raise ValueError("HKEX_ETP_IDENTITY_CONFLICT")
            row = latest[0]
            list_date = _epoch_milliseconds_date(row.get("first_trade_date"))
            lot = row.get("lot_size")
            if (
                list_date is None
                or list_date > self.as_of
                or type(lot) is not int
                or isinstance(lot, bool)
                or lot <= 0
                or type(row.get("name")) is not str
                or not str(row["name"]).strip()
                or row.get("currency") != "HKD"
                or row.get("product_sub_category") != "ETFs"
            ):
                raise ValueError("HKEX_ETP_ROW_INVALID")
            chosen.append(
                {
                    "symbol": symbol,
                    "market": "HK",
                    "name": str(row["name"]).strip(),
                    "instrument_type": "ETF",
                    "currency": "HKD",
                    "list_date": list_date,
                    "delist_date": None,
                    "board_lot": lot,
                    "status": "LISTED",
                }
            )
        result = pl.from_dicts(
            chosen,
            schema={
                "symbol": pl.String,
                "market": pl.String,
                "name": pl.String,
                "instrument_type": pl.String,
                "currency": pl.String,
                "list_date": pl.Date,
                "delist_date": pl.Date,
                "board_lot": pl.Int64,
                "status": pl.String,
            },
        ).sort("symbol")
        if tuple(result.get_column("symbol")) != self.target_symbols:
            raise ValueError("HKEX_ETP_COVERAGE_INCOMPLETE")
        return result


def _epoch_milliseconds_date(value: object) -> dt.date | None:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        return None
    try:
        instant = dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    if instant.time() != dt.time(0, 0):
        return None
    return instant.date()


def _hashable_identity(value: object) -> object:
    if isinstance(value, (dict, list, set)):
        raise ValueError("HKEX_ETP_ROW_INVALID")
    return value
