"""公开源抓取。网络失败返回空列表，不中断整次扫描。"""

from __future__ import annotations

import datetime as dt
import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

Fetcher = Callable[[str], str]

ARXIV = "http://export.arxiv.org/api/query"
GITHUB = "https://api.github.com/search/repositories"


def _get(url: str, timeout: float = 20) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True, trust_env=False)
    response.raise_for_status()
    return response.text


def item_id(source: str, url: str) -> str:
    return hashlib.sha256(f"{source}|{url}".encode()).hexdigest()[:16]


def fetch_arxiv(
    *,
    # Spaces become '+'; literal '+OR+' would be percent-encoded and match nothing.
    category: str = "cat:q-fin.ST OR cat:q-fin.PM OR cat:q-fin.TR",
    limit: int = 20,
    getter: Fetcher | None = None,
) -> list[dict[str, Any]]:
    query = urlencode({"search_query": category, "sortBy": "submittedDate", "max_results": limit})
    try:
        text = (getter or _get)(f"{ARXIV}?{query}")
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        if not title or not url:
            continue
        items.append({
            "id": item_id("arxiv", url),
            "source": "arxiv",
            "title": " ".join(title.split()),
            "url": url,
            "summary": " ".join(summary.split())[:800],
            "published": (entry.findtext("a:published", default="", namespaces=ns) or "")[:10],
        })
    return items


def fetch_github(
    *,
    query: str = "quantitative factor investing language:Python stars:>20",
    limit: int = 10,
    getter: Fetcher | None = None,
) -> list[dict[str, Any]]:
    url = f"{GITHUB}?{urlencode({'q': query, 'sort': 'updated', 'per_page': limit})}"
    try:
        text = (getter or _get)(url)
    except Exception:
        return []
    import json

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = []
    for row in payload.get("items") or []:
        html = str(row.get("html_url") or "")
        if not html:
            continue
        items.append({
            "id": item_id("github", html),
            "source": "github",
            "title": str(row.get("full_name") or html),
            "url": html,
            "summary": str(row.get("description") or "")[:800],
            "published": str(row.get("updated_at") or "")[:10],
        })
    return items


def fetch_rss(url: str, *, getter: Fetcher | None = None, limit: int = 15) -> list[dict[str, Any]]:
    try:
        text = (getter or _get)(url)
    except Exception:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    channel = root.find("channel")
    entries = channel.findall("item") if channel is not None else root.findall("{http://www.w3.org/2005/Atom}entry")
    for entry in entries[:limit]:
        title = (entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = (entry.findtext("link") or "")
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (atom_link.get("href") if atom_link is not None else "") or ""
        if not title or not link:
            continue
        summary = (entry.findtext("description") or entry.findtext("{http://www.w3.org/2005/Atom}summary") or "")
        items.append({
            "id": item_id("rss", link),
            "source": "rss",
            "title": " ".join(title.split()),
            "url": link.strip(),
            "summary": " ".join(summary.split())[:800],
            "published": (entry.findtext("pubDate") or "")[:16],
        })
    return items


def collect(config: dict[str, Any], *, getter: Fetcher | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    sources = dict(config.get("sources") or {})
    if sources.get("arxiv", True):
        items.extend(fetch_arxiv(limit=int(sources.get("arxiv_limit", 20)), getter=getter))
    if sources.get("github", True):
        items.extend(fetch_github(
            query=str(sources.get("github_query", "quantitative factor investing language:Python stars:>20")),
            limit=int(sources.get("github_limit", 10)),
            getter=getter,
        ))
    for feed in list(sources.get("rss") or []):
        items.extend(fetch_rss(str(feed), getter=getter, limit=int(sources.get("rss_limit", 10))) )
    seen: set[str] = set()
    unique = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


def iso_week(now: dt.date | None = None) -> str:
    """ISO week label for the intel digest folder.

    IntelWeekly runs Sunday 20:00. Attribute that run to the ISO week that
    begins the following Monday so 2026-11-01 → ``2026-W45`` and
    2026-11-08 → ``2026-W46`` (F2 acceptance paths).
    """
    day = now or dt.date.today()
    if day.weekday() == 6:  # Sunday
        day = day + dt.timedelta(days=1)
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"
