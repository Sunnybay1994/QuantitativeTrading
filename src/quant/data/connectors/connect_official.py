"""上交所/深交所港股通官方名单、调整事件和交易日历连接器。"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections.abc import Iterable

import httpx
import polars as pl


_SSE_QUERY = "https://query.sse.com.cn/commonQuery.do"
_SZSE_REPORT = "https://www.szse.cn/api/report/ShowReport/data"
_SZSE_CALENDAR = "https://www.szse.cn/api/report/exchange/ggtrl"


class SseConnectConnector:
    """沪港通下港股通官方数据。"""

    source = "sse"
    route = "SH_CONNECT"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)

    def fetch_eligibility_snapshot(self) -> pl.DataFrame:
        return pl.DataFrame(self._query("COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L"))

    def fetch_eligibility_events(self) -> pl.DataFrame:
        return pl.DataFrame(self._query("COMMON_SSE_JYFW_HGT_XXPL_BDZQTZXX_L"))

    def _query(self, sql_id: str) -> list[dict[str, object]]:
        params = {
            "jsonCallBack": "jsonpCallback",
            "sqlId": sql_id,
            "isPagination": "true",
            "pageHelp.pageSize": "5000",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "1",
            "keyword": "",
        }
        response = self._client.get(
            _SSE_QUERY,
            params=params,
            headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "quant/0.1"},
        )
        response.raise_for_status()
        match = re.fullmatch(r"jsonpCallback\((.*)\)\s*", response.text, flags=re.DOTALL)
        if match is None:
            raise ValueError("上交所响应不是预期 JSONP")
        payload = json.loads(match.group(1))
        return list(payload["pageHelp"]["data"])


class SzseConnectConnector:
    """深港通下港股通官方数据。"""

    source = "szse"
    route = "SZ_CONNECT"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30, follow_redirects=True)

    def fetch_eligibility_snapshot(self) -> pl.DataFrame:
        return pl.DataFrame(self._fetch_report("SGT_GGTBDQD"))

    def fetch_eligibility_events(self) -> pl.DataFrame:
        return pl.DataFrame(self._fetch_report("SGT_GGTBDTZ"))

    def fetch_connect_calendar(self, start: dt.date, end: dt.date) -> pl.DataFrame:
        if start > end:
            raise ValueError("start 不得晚于 end")
        rows: list[dict[str, object]] = []
        for month in _months_between(start, end):
            response = self._get_with_retry(
                _SZSE_CALENDAR,
                params={"month": month},
            )
            response.raise_for_status()
            rows.extend(response.json()["data"])
        return pl.DataFrame(rows).filter(
            pl.col("jyrq").str.to_date().is_between(start, end, closed="both")
        )

    def _fetch_report(self, catalog_id: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        page_no = 1
        while True:
            response = self._get_with_retry(
                _SZSE_REPORT,
                params={
                    "SHOWTYPE": "JSON",
                    "CATALOGID": catalog_id,
                    "TABKEY": "tab1",
                    "PAGENO": page_no,
                },
            )
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                raise ValueError("深交所报表响应结构异常")
            report = payload[0]
            metadata = report["metadata"]
            snapshot_date = metadata.get("subname")
            page_rows = report.get("data")
            if not isinstance(page_rows, list):
                raise ValueError("深交所报表缺少 data 数组")
            for row in page_rows:
                row["_snapshot_date"] = snapshot_date
                rows.append(row)
            if page_no >= int(metadata["pagecount"]):
                break
            page_no += 1
        expected = int(metadata["recordcount"])
        if len(rows) != expected:
            raise ValueError(f"深交所报表不完整: expected={expected}, actual={len(rows)}")
        return rows

    def _get_with_retry(
        self, url: str, *, params: dict[str, str | int | float | bool | None]
    ) -> httpx.Response:
        """深交所长分页偶发断连；仅对幂等 GET 做有限退避重试。"""
        last_error: httpx.HTTPError | None = None
        for attempt in range(4):
            try:
                response = self._client.get(
                    url,
                    params=params,
                    headers={
                        "Referer": "https://www.szse.cn/",
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "Chrome/136.0 Safari/537.36"
                        ),
                        "Connection": "close",
                    },
                )
                response.raise_for_status()
                time.sleep(0.3)
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(0.5 * (2**attempt))
        assert last_error is not None
        raise last_error


def _months_between(start: dt.date, end: dt.date) -> Iterable[str]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1
