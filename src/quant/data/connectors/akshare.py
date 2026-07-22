"""AKShare 原始数据连接器。

这里只负责调用供应商接口并返回带请求证券标识的原始字段，不负责映射 clean
Schema。AKShare 是可选依赖，因此 SDK 在首次请求时才导入。
"""

import datetime as dt
import importlib
import time
from typing import Any

import polars as pl

from quant.data.base import BaseConnector


class AkshareConnector(BaseConnector):
    """AKShare 薄适配器；当前骨架覆盖证券列表、A/H 日线与 A 股日历。"""

    source = "akshare"

    def __init__(self, client: Any | None = None) -> None:
        self._injected_client = client

    @property
    def client(self) -> Any:
        """延迟加载可选依赖，便于核心环境和单元测试使用。"""
        if self._injected_client is not None:
            return self._injected_client
        try:
            self._injected_client = importlib.import_module("akshare")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                'AKShare 未安装；请在 WSL Miniforge base 中执行 pip install -e ".[data]"'
            ) from exc
        return self._injected_client

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        """获取指定市场的实时证券列表原始响应。"""
        endpoint_by_market = {
            "SH": "stock_sh_a_spot_em",
            "SZ": "stock_sz_a_spot_em",
            "HK": "stock_hk_spot_em",
        }
        try:
            endpoint = endpoint_by_market[market]
        except KeyError as exc:
            raise ValueError(f"AKShare 不支持市场: {market}") from exc
        return _to_polars(getattr(self.client, endpoint)())

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取 A 股交易日历原始响应；接口本身可能返回请求区间外数据。"""
        _validate_range(start, end)
        if market not in {"SH", "SZ"}:
            raise NotImplementedError("AKShare 骨架尚未提供可核验的港股交易日历")
        return _to_polars(self.client.tool_trade_date_hist_sina())

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """逐证券获取不复权日线，并保留请求使用的标准证券代码。"""
        _validate_range(start, end)
        if not symbols:
            raise ValueError("symbols 不能为空")

        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            code, market = _split_symbol(symbol)
            if market in {"SH", "SZ"}:
                frame, endpoint = _fetch_a_share_bar(
                    self.client, code=code, market=market, start=start, end=end
                )
            elif market == "HK":
                endpoint = "stock_hk_hist"
                frame = _to_polars(
                    self.client.stock_hk_hist(
                        symbol=code,
                        period="daily",
                        start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"),
                        adjust="",
                    )
                )
            else:  # pragma: no cover - _split_symbol 已限制
                raise ValueError(f"AKShare 不支持市场: {market}")
            frames.append(
                frame.with_columns(
                    pl.lit(symbol).alias("_request_symbol"),
                    pl.lit(endpoint).alias("_endpoint"),
                )
            )

        return pl.concat(frames, how="diagonal_relaxed")

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """公司行动需要单独核验数据口径，M1 实现前显式拒绝。"""
        _validate_range(start, end)
        raise NotImplementedError("AKShare 公司行动接口尚未完成口径核验")

    def fetch_research_price_1d(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        *,
        adjustment: str = "hfq",
    ) -> pl.DataFrame:
        """获取 ETF 后复权研究价格；与账户核算的不复权 bar_1d 分离。"""
        _validate_range(start, end)
        if not symbols:
            raise ValueError("symbols 不能为空")
        if adjustment != "hfq":
            raise ValueError("研究价格链路仅接受后复权 hfq，拒绝会重写历史的 qfq")
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            code, market = _split_symbol(symbol)
            if market not in {"SH", "SZ"}:
                raise ValueError("ETF 后复权研究价格当前只支持沪深证券")
            try:
                frame = _fetch_etf_research_price(
                    self.client,
                    symbol=code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjustment=adjustment,
                ).with_columns(
                    pl.lit(0.0).alias("_cash_dividend"),
                    pl.lit("").alias("_hfq_errors"),
                )
                method = "hfq"
                endpoint = "fund_etf_hist_em"
            except RuntimeError as exc:
                frame = _fetch_etf_total_return_input(
                    self.client,
                    symbol=code,
                    market=market,
                    start=start,
                    end=end,
                ).with_columns(pl.lit(str(exc)).alias("_hfq_errors"))
                method = "total_return_dividend"
                endpoint = "fund_etf_hist_em+fund_etf_dividend_sina"
            frames.append(
                frame.with_columns(
                    pl.lit(symbol).alias("_request_symbol"),
                    pl.lit(endpoint).alias("_endpoint"),
                    pl.lit(method).alias("_adjustment"),
                )
            )
        return pl.concat(frames, how="diagonal_relaxed")


def _to_polars(frame: Any) -> pl.DataFrame:
    """把 SDK 的 pandas 返回值转换为 Polars，保持原始列名。"""
    if isinstance(frame, pl.DataFrame):
        return frame.clone()
    return pl.from_pandas(frame)


def _fetch_etf_research_price(
    client: Any,
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    adjustment: str,
) -> pl.DataFrame:
    """对网页端偶发断连做有界重试；最终失败时保留明确证券上下文。"""
    errors: list[str] = []
    for attempt, delay in enumerate((0.0, 1.0, 3.0), start=1):
        if delay:
            time.sleep(delay)
        try:
            frame = _to_polars(client.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjustment,
            ))
        except Exception as exc:
            errors.append(f"attempt={attempt}:{type(exc).__name__}")
            continue
        if not frame.is_empty():
            return frame
        errors.append(f"attempt={attempt}:empty")
    raise RuntimeError(
        f"AKShare ETF {adjustment} 研究价格失败: {symbol}; " + "; ".join(errors)
    )


def _fetch_etf_total_return_input(
    client: Any,
    *,
    symbol: str,
    market: str,
    start: dt.date,
    end: dt.date,
) -> pl.DataFrame:
    """取得不复权日线及除息日现金分红增量，供 mapper 构造总回报指数。"""
    prices = _fetch_etf_research_price(
        client,
        symbol=symbol,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjustment="",
    ).with_columns(pl.col("日期").cast(pl.String).str.to_date())
    try:
        dividends = _to_polars(
            client.fund_etf_dividend_sina(symbol=f"{market.lower()}{symbol}")
        )
    except Exception as exc:
        raise RuntimeError(
            f"AKShare ETF 分红事件失败: {symbol}; {type(exc).__name__}"
        ) from exc
    if dividends.is_empty():
        return prices.with_columns(pl.lit(0.0).alias("_cash_dividend"))
    required = {"日期", "累计分红"}
    missing = sorted(required - set(dividends.columns))
    if missing:
        raise ValueError(f"ETF 分红响应缺少字段: {', '.join(missing)}")
    events = (
        dividends.select(
            pl.col("日期").cast(pl.Date),
            pl.col("累计分红").cast(pl.Float64).alias("_cumulative_dividend"),
        )
        .sort("日期")
        .with_columns(
            pl.col("_cumulative_dividend")
            .diff()
            .fill_null(pl.col("_cumulative_dividend"))
            .alias("_cash_dividend")
        )
    )
    if events.filter(pl.col("_cash_dividend") < 0).height:
        raise ValueError(f"ETF 累计分红非单调: {symbol}")
    return prices.join(
        events.select("日期", "_cash_dividend"), on="日期", how="left"
    ).with_columns(pl.col("_cash_dividend").fill_null(0.0))


def _fetch_a_share_bar(
    client: Any,
    *,
    code: str,
    market: str,
    start: dt.date,
    end: dt.date,
) -> tuple[pl.DataFrame, str]:
    """按东财股票、新浪股票、东财 ETF 顺序获取沪深日线。"""
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    errors: list[str] = []
    attempts = [
        (
            "stock_zh_a_hist",
            lambda: client.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            ),
        ),
        (
            "stock_zh_a_daily",
            lambda: client.stock_zh_a_daily(
                symbol=f"{market.lower()}{code}",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            ),
        ),
        (
            "fund_etf_hist_em",
            lambda: client.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            ),
        ),
        (
            "fund_etf_hist_sina",
            lambda: _to_polars(
                client.fund_etf_hist_sina(symbol=f"{market.lower()}{code}")
            ).filter(
                pl.col("date").cast(pl.Date).is_between(start, end, closed="both")
            ),
        ),
    ]
    for endpoint, request in attempts:
        try:
            frame = _to_polars(request())
        except Exception as exc:
            errors.append(f"{endpoint}={exc!r}")
            continue
        if not frame.is_empty():
            return frame, endpoint
        errors.append(f"{endpoint}=empty")
    raise RuntimeError(f"AKShare 沪深日线全部端点失败: {market}.{code}; {'; '.join(errors)}")


def _validate_range(start: dt.date, end: dt.date) -> None:
    if start > end:
        raise ValueError("start 不得晚于 end")


def _split_symbol(symbol: str) -> tuple[str, str]:
    try:
        code, market = symbol.rsplit(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"证券代码必须使用 000001.SZ/00700.HK 格式: {symbol}") from exc
    if not code.isdigit() or market not in {"SH", "SZ", "HK"}:
        raise ValueError(f"无效证券代码: {symbol}")
    return code, market
