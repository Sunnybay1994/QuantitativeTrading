"""BaoStock 原始数据连接器，作为 A 股免费校验源。"""

import datetime as dt
import importlib
import socket
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

import polars as pl

from quant.data.base import BaseConnector

_BAR_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag,tradestatus"


class BaostockConnector(BaseConnector):
    """封装 BaoStock 登录会话和结果集迭代。"""

    source = "baostock"

    def __init__(self, client: Any | None = None) -> None:
        self._injected_client = client

    @property
    def client(self) -> Any:
        """延迟加载可选依赖。"""
        if self._injected_client is not None:
            return self._injected_client
        try:
            self._injected_client = importlib.import_module("baostock")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                'BaoStock 未安装；请在 WSL Miniforge base 中执行 pip install -e ".[data]"'
            ) from exc
        return self._injected_client

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        """获取完整证券基础资料；market 由下游 mapper 过滤并写入 raw 参数。"""
        _validate_market(market)
        with self._session():
            result = self.client.query_stock_basic()
            return _result_to_polars(result, "query_stock_basic")

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取沪深共用的原始交易日历。"""
        _validate_market(market)
        _validate_range(start, end)
        with self._session():
            result = self.client.query_trade_dates(
                start_date=start.isoformat(), end_date=end.isoformat()
            )
            return _result_to_polars(result, "query_trade_dates")

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取沪深 A 股不复权日线原始响应。"""
        _validate_range(start, end)
        if not symbols:
            raise ValueError("symbols 不能为空")
        frames: list[pl.DataFrame] = []
        with self._session():
            for symbol in symbols:
                code = _to_baostock_code(symbol)
                result = self.client.query_history_k_data_plus(
                    code,
                    _BAR_FIELDS,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    frequency="d",
                    adjustflag="3",
                )
                frame = _result_to_polars(result, "query_history_k_data_plus")
                frames.append(
                    frame.with_columns(
                        pl.lit(symbol).alias("_request_symbol"),
                        pl.lit("query_history_k_data_plus").alias("_endpoint"),
                    )
                )
        return pl.concat(frames, how="diagonal_relaxed")

    def fetch_reference_bar_raw(
        self,
        *,
        symbol: str,
        start: dt.date,
        end: dt.date,
        fields: str,
        frequency: str,
        adjustflag: str,
    ) -> pl.DataFrame:
        """Fetch one BaoStock reference bar request without mapping or dedup."""
        if type(symbol) is not str or type(fields) is not str:
            raise ValueError("reference bar 参数类型非法")
        if type(frequency) is not str or type(adjustflag) is not str:
            raise ValueError("reference bar 参数类型非法")
        if type(start) is not dt.date or type(end) is not dt.date:
            raise ValueError("reference bar 日期类型非法")
        if start > end:
            raise ValueError("start 不得晚于 end")
        if fields != _BAR_FIELDS:
            raise ValueError("reference bar fields 非法")
        if frequency != "d" or adjustflag != "3":
            raise ValueError("reference bar frequency/adjustflag 非法")
        code = _to_baostock_code(symbol)
        with self._session():
            result = self.client.query_history_k_data_plus(
                code,
                fields,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency=frequency,
                adjustflag=adjustflag,
            )
            return _result_to_polars(result, "query_history_k_data_plus")

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError("BaoStock 公司行动口径尚未接入")

    def fetch_intraday(self, symbol: str, start: dt.date, end: dt.date) -> pl.DataFrame:
        """Fetch unadjusted five-minute bars; supplier time denotes bar end."""
        _validate_range(start, end)
        with self._session():
            result = self.client.query_history_k_data_plus(
                _to_baostock_code(symbol),
                "date,time,code,open,high,low,close,volume,amount,adjustflag",
                start_date=start.isoformat(), end_date=end.isoformat(),
                frequency="5", adjustflag="3",
            )
            frame = _result_to_polars(result, "query_history_k_data_plus")
            _ensure_success(result, "minute response completion")
            return frame

    def fetch_adjust_factors(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        """获取累计后复权因子事件。"""
        _validate_range(start, end)
        frames: list[pl.DataFrame] = []
        with self._session():
            for symbol in symbols:
                result = self.client.query_adjust_factor(
                    _to_baostock_code(symbol),
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                )
                frame = _result_to_polars(result, "query_adjust_factor")
                frames.append(frame.with_columns(pl.lit(symbol).alias("_request_symbol")))
        return pl.concat(frames, how="diagonal_relaxed")

    @contextmanager
    def _session(self) -> Iterator[None]:
        if getattr(self.client, '__name__', '') != 'baostock':
            with self._unguarded_session():
                yield
            return
        from quant.data.connectors.baostock_access import AccessBudget, BaoStockAccessPaused, session_slot
        with session_slot():
            budget = AccessBudget()
            self._access_budget = budget
            failed = False
            opened = False
            try:
                budget.begin_session()  # Refuse before even opening a socket.
                opened = True
                with self._unguarded_session():
                    yield
            except Exception as exc:
                failed = True
                if '10001011' in str(exc):
                    budget.block()
                    raise BaoStockAccessPaused('BaoStock blacklist 10001011; further requests blocked') from exc
                raise
            finally:
                context = importlib.import_module('baostock.common.context')
                raw = getattr(context, 'default_socket', None)
                try:
                    if raw is not None:
                        raw.close()
                        context.default_socket = None
                finally:
                    if opened:
                        budget.session_event('failed' if failed or budget.error is not None else 'closed')
                    budget.db.close()
                if budget.error is not None:
                    raise budget.error

    @contextmanager
    def _unguarded_session(self) -> Iterator[None]:
        # BaoStock creates its socket at login without any timeout. Bound that
        # socket's connect/read waits; restore the process default immediately.
        previous_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(45.0)
            client = self.client
            if getattr(client, "__name__", "") == "baostock":
                transport = importlib.import_module("baostock.util.socketutil")
                context = importlib.import_module("baostock.common.context")
                original_connect = transport.SocketUtil.connect

                def connect(instance: Any) -> None:
                    original_connect(instance)
                    raw = getattr(context, "default_socket", None)
                    if raw is not None:
                        from quant.data.connectors.baostock_access import BudgetSocket
                        raw = BudgetSocket(raw, self._access_budget)
                        setattr(context, "default_socket", _BaoStockEOFSocket(raw))

                # Patch only the SDK's connection creation during this serial login.
                # The socket remains guarded through queries and logout.
                with patch.object(transport.SocketUtil, "connect", connect):
                    login_result = client.login()
                if getattr(login_result, "error_code", None) != "0":
                    raw = getattr(context, "default_socket", None)
                    if raw is not None:
                        raw.close()
            else:
                login_result = client.login()
        finally:
            socket.setdefaulttimeout(previous_timeout)
        _ensure_success(login_result, "login")
        query_failed = False
        try:
            yield
        except BaseException:
            # A timed-out/partial response leaves the stream boundary unknown.
            # Do not send logout on it or mask the original query exception.
            query_failed = True
            raise
        finally:
            budget = getattr(self, '_access_budget', None)
            if not query_failed and (budget is None or budget.error is None):
                result = self.client.logout()
                if result is not None:
                    _ensure_success(result, 'logout')


class BaostockResponseError(RuntimeError):
    """BaoStock 返回非零错误码。"""


class _BaoStockEOFSocket:
    """Turn peer closure into failure before the SDK enters its empty-recv loop."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def recv(self, size: int) -> bytes:
        chunk: bytes = self.connection.recv(size)
        if not chunk:
            raise ConnectionError("BaoStock peer closed the connection")
        return chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)


def _result_to_polars(result: Any, action: str) -> pl.DataFrame:
    _ensure_success(result, action)
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pl.DataFrame(rows, schema=list(result.fields), orient="row")


def _ensure_success(response: Any, action: str) -> None:
    code = str(response.error_code)
    if code != "0":
        raise BaostockResponseError(
            f"BaoStock {action} 失败: code={code}, message={response.error_msg}"
        )


def _to_baostock_code(symbol: str) -> str:
    try:
        code, market = symbol.rsplit(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"证券代码必须使用 000001.SZ 格式: {symbol}") from exc
    if not code.isdigit() or market not in {"SH", "SZ"}:
        raise ValueError(f"BaoStock 只支持沪深 A 股代码: {symbol}")
    return f"{market.lower()}.{code}"


def _validate_market(market: str) -> None:
    if market not in {"SH", "SZ"}:
        raise ValueError(f"BaoStock 只支持沪深市场: {market}")


def _validate_range(start: dt.date, end: dt.date) -> None:
    if start > end:
        raise ValueError("start 不得晚于 end")
