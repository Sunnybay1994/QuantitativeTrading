"""Public correction announcements; titles identify candidates, not numeric revisions."""

import datetime as dt
from typing import Any, Iterator

import requests


def correction_pages(
    start: dt.date, end: dt.date, *, session: Any = None,
) -> Iterator[tuple[dict[str, str], list[dict[str, Any]]]]:
    """Fetch every page, rejecting incomplete or shifting result sets."""
    if start > end:
        raise ValueError("start must not exceed end")
    client = session if session is not None else requests
    expected: int | None = None
    seen: set[str] = set()
    page = 1
    while True:
        params = {
            "pageNum": str(page), "pageSize": "30", "column": "szse",
            "tabName": "fulltext", "plate": "", "stock": "", "searchkey": "",
            "secid": "", "category": "category_bcgz_szsh", "trade": "",
            "seDate": f"{start.isoformat()}~{end.isoformat()}", "sortName": "",
            "sortType": "", "isHLtitle": "false",
        }
        response = client.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query", data=params,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        total = body.get("totalAnnouncement")
        if type(total) is not int or total < 0:
            raise ValueError("missing or invalid announcement count")
        if expected is not None and total != expected:
            raise ValueError("announcement count changed during pagination; retry window")
        expected = total
        rows = body.get("announcements")
        if rows is None and total == 0:
            rows = []
        if not isinstance(rows, list) or (not rows and len(seen) < total):
            raise ValueError("missing announcement page")
        for row in rows:
            identity = row.get("announcementId") if isinstance(row, dict) else None
            if not identity or str(identity) in seen:
                raise ValueError("missing or repeated announcement ID")
            seen.add(str(identity))
        if len(seen) > total:
            raise ValueError("announcement rows exceed reported count")
        yield params, rows
        if len(seen) == total:
            return
        page += 1
