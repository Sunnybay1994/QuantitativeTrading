"""Tushare Pro 原始数据连接器；Token 仅从本地忽略配置读取。"""

from __future__ import annotations

import datetime as dt
import importlib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.base import BaseConnector
from quant.settings import load_tushare_settings


class TushareConnector(BaseConnector):
    """覆盖 A/H 基础信息、日历、日线与复权因子的薄适配器。"""

    source = "tushare"

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        pro_client: Any | None = None,
    ) -> None:
        self._config_path = config_path
        self._pro_client = pro_client

    @property
    def client(self) -> Any:
        if self._pro_client is not None:
            return self._pro_client
        settings = load_tushare_settings(self._config_path)
        try:
            tushare = importlib.import_module("tushare")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                'Tushare 未安装；请在 WSL Miniforge base 中执行 pip install -e ".[data]"'
            ) from exc
        self._pro_client = tushare.pro_api(settings.token)
        return self._pro_client

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        if market in {"SH", "SZ"}:
            exchange = "SSE" if market == "SH" else "SZSE"
            frames = [
                _to_polars(self.client.stock_basic(
                    exchange=exchange,
                    list_status=status,
                    fields=(
                        "ts_code,name,exchange,curr_type,list_status,list_date,delist_date"
                    ),
                ))
                .with_columns(pl.lit(status).alias("_request_list_status"))
                for status in ("L", "D", "P", "G")
            ]
        elif market == "HK":
            frames = [
                _to_polars(self.client.hk_basic(
                    list_status=status,
                    fields=(
                        "ts_code,name,list_status,list_date,delist_date,trade_unit,curr_type"
                    ),
                ))
                .with_columns(pl.lit(status).alias("_request_list_status"))
                for status in ("L", "D", "P")
            ]
        else:
            raise ValueError(f"Tushare 不支持市场: {market}")
        nonempty = [frame for frame in frames if not frame.is_empty()]
        return pl.concat(nonempty, how="diagonal_relaxed") if nonempty else pl.DataFrame()

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        _validate_range(start, end)
        params = {"start_date": _date(start), "end_date": _date(end)}
        if market in {"SH", "SZ"}:
            exchange = "SSE" if market == "SH" else "SZSE"
            return _to_polars(self.client.trade_cal(exchange=exchange, **params))
        if market == "HK":
            return _to_polars(self.client.hk_tradecal(**params))
        raise ValueError(f"Tushare 不支持市场: {market}")

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        _validate_request(symbols, start, end)
        if start == end:
            return self._fetch_daily_snapshot(symbols, start)
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            market = _market(symbol)
            method = self.client.hk_daily if market == "HK" else self.client.daily
            for chunk_start, chunk_end in _date_chunks(start, end):
                frames.append(
                    _to_polars(
                        method(
                            ts_code=symbol,
                            start_date=_date(chunk_start),
                            end_date=_date(chunk_end),
                        )
                    ).with_columns(
                        pl.lit(symbol).alias("_request_symbol"),
                        pl.lit(market).alias("_market"),
                    )
                )
        return pl.concat(frames, how="diagonal_relaxed").unique(
            subset=["_request_symbol", "trade_date"], keep="last"
        )

    def _fetch_daily_snapshot(
        self, symbols: list[str], trade_date: dt.date
    ) -> pl.DataFrame:
        """单日按端点全市场批量抓取，避免低频账户逐证券消耗额度。"""
        frames: list[pl.DataFrame] = []
        groups = {
            "A": [symbol for symbol in symbols if _market(symbol) in {"SH", "SZ"}],
            "HK": [symbol for symbol in symbols if _market(symbol) == "HK"],
        }
        for asset, requested in groups.items():
            if not requested:
                continue
            method = self.client.hk_daily if asset == "HK" else self.client.daily
            frame = _to_polars(method(trade_date=_date(trade_date))).filter(
                pl.col("ts_code").is_in(requested)
            )
            frames.append(
                frame.with_columns(
                    pl.col("ts_code").alias("_request_symbol"),
                    pl.col("ts_code").str.split(".").list.last().alias("_market"),
                )
            )
        return pl.concat(frames, how="diagonal_relaxed").unique(
            subset=["_request_symbol", "trade_date"], keep="last"
        )

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        _validate_request(symbols, start, end)
        frames: list[pl.DataFrame] = []
        for symbol in symbols:
            market = _market(symbol)
            method = self.client.hk_adjfactor if market == "HK" else self.client.adj_factor
            for chunk_start, chunk_end in _date_chunks(start, end):
                frames.append(
                    _to_polars(
                        method(
                            ts_code=symbol,
                            start_date=_date(chunk_start),
                            end_date=_date(chunk_end),
                        )
                    ).with_columns(
                        pl.lit(symbol).alias("_request_symbol"),
                        pl.lit(market).alias("_market"),
                    )
                )
        return pl.concat(frames, how="diagonal_relaxed").unique(
            subset=["_request_symbol", "trade_date"], keep="last"
        )

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        _validate_request(symbols, start, end)
        raise NotImplementedError("Tushare 公司行动需在独立 PIT 契约实现后接入")

    def fetch_index_weight_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 index_weight 请求；原样返回，不去重/分块。"""
        _validate_range(start, end)
        _validate_index_code(index_code)
        return _to_polars(
            self.client.index_weight(
                index_code=index_code,
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_daily_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 A 股 daily 请求；原样返回，不去重/分块。"""
        _validate_range(start, end)
        _validate_a_share_symbol(symbol)
        return _to_polars(
            self.client.daily(
                ts_code=symbol,
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_hk_daily_batch_raw(
        self,
        *,
        symbols: tuple[str, ...],
        start: dt.date,
        end: dt.date,
        fields: str,
    ) -> pl.DataFrame:
        """单次探测 hk_daily 多代码参数；原样返回，不分页或静默降级。"""
        _validate_range(start, end)
        _validate_hk_symbol_batch(symbols)
        return _to_polars(
            self.client.hk_daily(
                ts_code=",".join(symbols),
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_adj_factor_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 A 股 adj_factor 请求；原样返回，不去重/分块。"""
        _validate_range(start, end)
        _validate_a_share_symbol(symbol)
        return _to_polars(
            self.client.adj_factor(
                ts_code=symbol,
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_index_daily_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 index_daily 请求；原样返回，不去重/分块。"""
        _validate_range(start, end)
        _validate_index_code(index_code)
        return _to_polars(
            self.client.index_daily(
                ts_code=index_code,
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_suspend_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 suspend_d 请求；按证券全窗口，固定 suspend_type=S，原样返回。"""
        _validate_range(start, end)
        _validate_a_share_symbol(symbol)
        return _to_polars(
            self.client.suspend_d(
                ts_code=symbol,
                start_date=_date(start),
                end_date=_date(end),
                suspend_type="S",
                fields=fields,
            )
        )

    def fetch_stk_limit_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame:
        """单次 stk_limit 请求；原样返回，不去重/分块。"""
        _validate_range(start, end)
        _validate_a_share_symbol(symbol)
        return _to_polars(
            self.client.stk_limit(
                ts_code=symbol,
                start_date=_date(start),
                end_date=_date(end),
                fields=fields,
            )
        )

    def fetch_dividend_raw(self, *, symbol: str, fields: str) -> pl.DataFrame:
        """单次 dividend 请求；原样返回，不去重/分块。"""
        _validate_a_share_symbol(symbol)
        return _to_polars(
            self.client.dividend(
                ts_code=symbol,
                fields=fields,
            )
        )


def _to_polars(frame: Any) -> pl.DataFrame:
    if isinstance(frame, pl.DataFrame):
        return frame
    return pl.from_pandas(frame)


def _date(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def _market(symbol: str) -> str:
    try:
        code, market = symbol.rsplit(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"非法标准证券代码: {symbol}") from exc
    if not code.isdigit() or market not in {"SH", "SZ", "HK"}:
        raise ValueError(f"非法标准证券代码: {symbol}")
    return market


def _validate_a_share_symbol(symbol: str) -> None:
    try:
        code, market = symbol.rsplit(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"非法标准证券代码: {symbol}") from exc
    if not code.isdigit() or market not in {"SH", "SZ"}:
        raise ValueError(f"非法标准证券代码: {symbol}")


def _validate_hk_symbol_batch(symbols: tuple[str, ...]) -> None:
    if (
        type(symbols) is not tuple
        or not symbols
        or len(symbols) > 100
        or len(set(symbols)) != len(symbols)
        or tuple(sorted(symbols)) != symbols
    ):
        raise ValueError("HK_DAILY_BATCH_SYMBOLS_INVALID")
    for symbol in symbols:
        if type(symbol) is not str or len(symbol) != 8 or not symbol.endswith(".HK"):
            raise ValueError("HK_DAILY_BATCH_SYMBOLS_INVALID")
        if not symbol[:5].isdigit():
            raise ValueError("HK_DAILY_BATCH_SYMBOLS_INVALID")


def _validate_index_code(index_code: str) -> None:
    try:
        code, market = index_code.rsplit(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"非法指数代码: {index_code}") from exc
    if market in {"SH", "SZ"}:
        if not code.isdigit():
            raise ValueError(f"非法指数代码: {index_code}")
    elif market == "CSI":
        if not code or not code.isalnum():
            raise ValueError(f"非法指数代码: {index_code}")
    else:
        raise ValueError(f"非法指数代码: {index_code}")


def _validate_range(start: dt.date, end: dt.date) -> None:
    if start > end:
        raise ValueError("start 不得晚于 end")


def _validate_request(symbols: list[str], start: dt.date, end: dt.date) -> None:
    _validate_range(start, end)
    if not symbols:
        raise ValueError("symbols 不能为空")
    for symbol in symbols:
        _market(symbol)


def _date_chunks(
    start: dt.date, end: dt.date, *, days: int = 3000
) -> list[tuple[dt.date, dt.date]]:
    """把长区间切到明显低于 5,000/6,000 行上限的日历窗口。"""
    chunks: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + dt.timedelta(days=days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + dt.timedelta(days=1)
    return chunks
