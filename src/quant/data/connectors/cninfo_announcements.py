"""Public announcement pages; titles identify candidates, not numeric revisions."""

import datetime as dt
import re
import time
from typing import Any, Iterator

import requests


class AnnouncementSetChanged(ValueError):
    """The publisher changed a result set while it was being paged."""


class AnnouncementDocumentTooLarge(ValueError):
    """One public PDF exceeds the bounded download limit."""


MAX_ANNOUNCEMENT_DOCUMENT_BYTES = 128 * 1024 * 1024


def download_document(relative: str, *, session: Any = None) -> bytes:
    """Fetch one public PDF with a bounded response; callers append it to raw."""
    if not re.fullmatch(r'finalpage/[0-9-]+/[0-9]+\.[pP][dD][fF]', relative):
        raise ValueError('Unexpected public announcement document path')
    client = session if session is not None else requests
    for attempt in range(3):
        try:
            with client.get('https://static.cninfo.com.cn/'+relative, stream=True, timeout=60,
                            headers={'User-Agent': 'Mozilla/5.0'}) as response:
                response.raise_for_status()
                declared = response.headers.get('Content-Length')
                if declared is not None and declared.isdigit() and int(declared) > MAX_ANNOUNCEMENT_DOCUMENT_BYTES:
                    raise AnnouncementDocumentTooLarge(
                        'Announcement document exceeds the 128 MiB limit')
                data = bytearray()
                for chunk in response.iter_content(1024*1024):
                    data.extend(chunk)
                    if len(data) > MAX_ANNOUNCEMENT_DOCUMENT_BYTES:
                        raise AnnouncementDocumentTooLarge(
                            'Announcement document exceeds the 128 MiB limit')
            if not data.startswith(b'%PDF-'):
                raise ValueError('Expected a public PDF document')
            return bytes(data)
        except AnnouncementDocumentTooLarge:
            raise
        except requests.RequestException:
            if attempt == 2:
                raise RuntimeError('Announcement PDF unavailable after three attempts') from None
            time.sleep(attempt+1)
    raise RuntimeError('Announcement PDF unavailable')


def announcement_pages(
    start: dt.date, end: dt.date, *, category: str, session: Any = None,
    searchkey: str = "",
) -> Iterator[tuple[dict[str, str], list[dict[str, Any]]]]:
    """Fetch every page, rejecting incomplete or shifting result sets."""
    if start > end:
        raise ValueError("start must not exceed end")
    if not isinstance(searchkey, str) or len(searchkey) > 40:
        raise ValueError("invalid announcement search key")
    client = session if session is not None else requests
    expected: int | None = None
    seen: set[str] = set()
    page = 1
    while True:
        params = {
            "pageNum": str(page), "pageSize": "30", "column": "szse",
            "tabName": "fulltext", "plate": "", "stock": "", "searchkey": searchkey,
            "secid": "", "category": category, "trade": "",
            "seDate": f"{start.isoformat()}~{end.isoformat()}", "sortName": "",
            "sortType": "", "isHLtitle": "false",
        }
        for attempt in range(3):
            try:
                response = client.post(
                    "https://www.cninfo.com.cn/new/hisAnnouncement/query", data=params,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"},
                    timeout=30,
                )
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise RuntimeError(f'Announcement page {page} unavailable after three attempts') from None
                time.sleep(attempt + 1)
        body = response.json()
        total = body.get("totalAnnouncement")
        if type(total) is not int or total < 0:
            raise ValueError("missing or invalid announcement count")
        if expected is not None and total != expected:
            raise AnnouncementSetChanged("announcement count changed during pagination; retry window")
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


def correction_pages(start: dt.date, end: dt.date, *, session: Any = None
                     ) -> Iterator[tuple[dict[str, str], list[dict[str, Any]]]]:
    """Retain the correction-only collector's existing query scope."""
    return announcement_pages(start, end, category='category_bcgz_szsh', session=session)
