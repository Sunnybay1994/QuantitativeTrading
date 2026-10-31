"""Point-in-time repurchase and insider-trading announcements. Not a factor test."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import math
import json
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import polars as pl

from quant.data.connectors.cninfo_announcements import (
    AnnouncementSetChanged, announcement_pages, download_document)

from quant.factors.forecast_text_score import strict_json
from quant.llm.pricing import load_pricing
from quant.data.events_v0_schema import EventV0Schema

MAX_INPUT_CHARS = 1500
TASK_BUDGET_USD = 5.0
QUERIES = (
    ("repurchase", "回购实施"),
    ("insider_trading", "股东减持"),
    ("insider_trading", "股东增持"),
)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(万亿|亿|万元|万|元)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SCALES = {"元": 1.0, "万": 1e4, "万元": 1e4, "亿": 1e8, "万亿": 1e12}


def plain_title(title: object) -> str:
    return _SPACE.sub(" ", _TAGS.sub("", str(title or ""))).strip()


def family_of(title: str) -> str | None:
    text = plain_title(title)
    if "回购" in text and any(word in text for word in ("实施", "进展", "完成", "结果", "到期")):
        return "repurchase"
    actors = ("股东", "高管", "董事", "监事", "高级管理人员", "实际控制人", "持股")
    if any(word in text for word in ("增持", "减持")) and any(actor in text for actor in actors):
        return "insider_trading"
    return None


def a_share_symbol(code: object) -> str | None:
    digits = re.sub(r"\D", "", str(code or ""))
    if len(digits) < 6:
        return None
    code6 = digits[-6:]
    if code6.startswith(("92", "83", "87", "43", "82")):
        return f"{code6}.BJ"
    if code6.startswith(("6", "9")):
        return f"{code6}.SH"
    if code6.startswith(("0", "3")):
        return f"{code6}.SZ"
    return None


def published_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return (value.astimezone(ZoneInfo('Asia/Shanghai')).date()
                if value.tzinfo is not None else value.date())
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if float(value) > 1e12 else float(value)
        try:
            return dt.datetime.fromtimestamp(seconds, ZoneInfo('Asia/Shanghai')).date()
        except (OverflowError, OSError, ValueError):
            return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _compact(text: str) -> str:
    return _SPACE.sub("", text)


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, abs(right) * 1e-4)


def accept_extraction(excerpt: str, payload: dict) -> dict:
    """Keep a parse only when every filled number is visible in the excerpt."""
    empty = {"parse_status": "unresolved", "amount_cny": None, "ratio_pct": None,
             "term_days": None, "direction": None, "evidence": None}
    if payload.get("status") != "parsed":
        return empty
    evidence = payload.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        return empty
    if _compact(evidence) not in _compact(excerpt):
        return empty
    amount = payload.get("amount_cny")
    ratio = payload.get("ratio_pct")
    term = payload.get("term_days")
    direction = payload.get("direction")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            return empty
        plain_numbers = evidence.replace(",", "").replace("，", "")
        if not any(_close(float(number) * _SCALES[unit], float(amount))
                   for number, unit in _AMOUNT.findall(plain_numbers)):
            return empty
    if ratio is not None:
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or ratio < 0:
            return empty
        if not any(_close(float(number), float(ratio)) for number in _NUMBER.findall(evidence)):
            return empty
    if term is not None and isinstance(term, float) and term.is_integer():
        term = int(term)
    if term is not None:
        if isinstance(term, bool) or type(term) is not int or term <= 0:
            return empty
        months = re.search(r"(\d+)\s*个月", evidence)
        if str(term) not in evidence.replace(",", "").replace("，", "") and not (
                months and int(months.group(1)) * 30 == term):
            return empty
    if direction not in {"buy", "sell", "repurchase"}:
        return empty
    if direction == "repurchase" and "回购" not in evidence:
        return empty
    if direction == "buy" and "增持" not in evidence:
        return empty
    if direction == "sell" and "减持" not in evidence:
        return empty
    if direction == "buy" and "减持" in evidence and "增持" not in evidence:
        return empty
    return {"parse_status": "parsed", "amount_cny": None if amount is None else float(amount),
            "ratio_pct": None if ratio is None else float(ratio),
            "term_days": term, "direction": direction, "evidence": evidence}


_EXPLICIT_TOTAL = re.compile(
    r"(成交总金额|支付的资金总额|已支付的总金额|已支付的资金总额|使用资金总额)"
    r"(?:为人民币|为|人民币)?\s*(\d[\d,，]*(?:\.\d+)?)\s*(万亿|亿|万元|万|元)"
)


def fill_explicit_total(excerpt: str, parsed: dict, family: str) -> dict:
    """Copy one paid total the model left blank. A plan range stays blank."""
    if parsed.get("amount_cny") is not None:
        return parsed
    found = []
    for match in _EXPLICIT_TOTAL.finditer(excerpt):
        window = excerpt[max(0, match.start() - 12):match.end()]
        if "不低于" in window or "不超过" in window:
            continue
        number = float(match.group(2).replace(",", "").replace("，", ""))
        found.append((number * _SCALES[match.group(3)], match.group(0)))
    if len({round(value, 2) for value, _evidence in found}) != 1:
        return parsed
    amount, evidence = found[0]
    direction = parsed.get("direction")
    if direction not in {"buy", "sell", "repurchase"}:
        if family == "repurchase" and "回购" in excerpt:
            direction = "repurchase"
        elif "增持" in excerpt and "减持" not in excerpt:
            direction = "buy"
        elif "减持" in excerpt and "增持" not in excerpt:
            direction = "sell"
        else:
            return parsed
    updated = dict(parsed)
    updated.update(parse_status="parsed", amount_cny=amount, direction=direction, evidence=evidence)
    return updated


_ACTUAL_RATIO = re.compile(r"实际回购股数占总股本比例\s*(\d+(?:\.\d+)?)%")
_NO_SELL = ("未减持", "未实施减持")


def fill_explicit_ratio(excerpt: str, parsed: dict) -> dict:
    """Copy one completed repurchase ratio the model left blank."""
    if parsed.get("ratio_pct") is not None:
        return parsed
    numbers = [float(item) for item in _ACTUAL_RATIO.findall(_compact(excerpt))]
    if len({round(number, 6) for number in numbers}) != 1:
        return parsed
    updated = dict(parsed)
    updated["ratio_pct"] = numbers[0]
    return updated


def _reports_completed_sale(evidence: str) -> bool:
    if "实施减持" in evidence:
        return True
    compact = evidence.replace(",", "").replace("，", "").replace(" ", "")
    return re.search(r"减持(?:公司)?股份(?:\d*\.)?[1-9]", compact) is not None


def drop_unexecuted_sell(parsed: dict) -> dict:
    """A quote that says the sale did not happen is not a sell."""
    if parsed.get("direction") != "sell":
        return parsed
    evidence = str(parsed.get("evidence") or "")
    if not any(token in evidence for token in _NO_SELL):
        return parsed
    if _reports_completed_sale(evidence):
        return parsed
    updated = dict(parsed)
    updated.update(parse_status="unresolved", direction=None, amount_cny=None, ratio_pct=None)
    return updated


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    objects = {}
    for match in re.finditer(rb"(?:^|[\r\n])(\d+)\s+0\s+obj", data):
        start = match.end()
        end = data.find(b"endobj", start)
        stream_at = data.find(b"stream", start)
        if stream_at != -1 and (end == -1 or stream_at < end):
            endstream = data.find(b"endstream", stream_at)
            if endstream != -1:
                end = data.find(b"endobj", endstream)
        if end == -1:
            continue
        objects[int(match.group(1))] = data[start:end]
    return objects


def _pdf_stream(body: bytes) -> bytes:
    match = re.search(rb"stream\r?\n(.*)\r?\nendstream", body, re.S)
    if not match:
        return b""
    raw = match.group(1)
    if b"FlateDecode" not in body:
        return raw
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return b""


def _parse_cmap(blob: bytes) -> dict[int, str]:
    text = blob.decode("latin1", errors="ignore")
    mapping: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = bytes.fromhex(dst).decode("utf-16-be", errors="ignore")
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for src, end, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start_i, end_i = int(src, 16), int(end, 16)
            chars = bytes.fromhex(dst).decode("utf-16-be", errors="ignore")
            if len(chars) == 1:
                base = ord(chars)
                for offset, code in enumerate(range(start_i, end_i + 1)):
                    mapping[code] = chr(base + offset)
        for src, end, dests in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
            codes = range(int(src, 16), int(end, 16) + 1)
            chars = [bytes.fromhex(item).decode("utf-16-be", errors="ignore")
                     for item in re.findall(r"<([0-9A-Fa-f]+)>", dests)]
            for code, char in zip(codes, chars):
                mapping[code] = char
    return mapping


def _map_hex(hex_code: str, cmap: dict[int, str]) -> str:
    raw = re.sub(r"\s+", "", hex_code)
    if not raw:
        return ""
    width = 4 if len(raw) % 4 == 0 else 2
    chars = []
    for index in range(0, len(raw), width):
        chars.append(cmap.get(int(raw[index:index + width], 16), ""))
    return "".join(chars)


def _unescape_pdf_literal(body: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 >= len(body):
            chars.append(char)
            index += 1
            continue
        nxt = body[index + 1]
        simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                  "\\": "\\", "(": "(", ")": ")"}
        if nxt in simple:
            chars.append(simple[nxt])
            index += 2
            continue
        if nxt.isdigit():
            octal = nxt
            index += 2
            for _ in range(2):
                if index < len(body) and body[index].isdigit():
                    octal += body[index]
                    index += 1
                else:
                    break
            chars.append(chr(int(octal, 8) & 0xFF))
            continue
        chars.append(nxt)
        index += 2
    return "".join(chars)


def _show_text(body: str, cmap: dict[int, str]) -> str:
    """Keep hex glyphs and literal strings in the order the page draws them."""
    chunks: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == "<":
            end = body.find(">", index)
            if end < 0:
                break
            chunks.append(_map_hex(body[index + 1:end], cmap))
            index = end + 1
            continue
        if body[index] == "(":
            depth = 1
            start = index + 1
            index += 1
            while index < len(body) and depth:
                if body[index] == "\\":
                    index += 2
                    continue
                if body[index] == "(":
                    depth += 1
                elif body[index] == ")":
                    depth -= 1
                    if not depth:
                        break
                index += 1
            chunks.append(_unescape_pdf_literal(body[start:index]))
            index += 1
            continue
        index += 1
    return "".join(chunks)


def pdf_plain_text(data: bytes) -> str:
    """Read text from the embedded ToUnicode maps. Unmapped glyphs are dropped."""
    if not data.startswith(b"%PDF-"):
        return ""
    if b'startxref' in data:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            text = _SPACE.sub(' ', ' '.join(page.extract_text() or '' for page in reader.pages)).strip()
            if len(re.findall(r'[\u4e00-\u9fff]', text)) >= 20:
                return text
        except (PdfReadError, ValueError, TypeError):
            pass
    objects = _pdf_objects(data)
    cmaps: dict[int, dict[int, str]] = {}
    for obj_id, body in objects.items():
        ref = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not ref:
            continue
        target = objects.get(int(ref.group(1)))
        if target is not None:
            cmaps[obj_id] = _parse_cmap(_pdf_stream(target) or target)
    font_names = {name.decode(): int(obj)
                  for name, obj in re.findall(rb"/F(?:T)?(\d+)\s+(\d+)\s+0\s+R", data)}
    token = re.compile(
        r"/F(?:T)?(\d+)\s+[-\d.]+\s+Tf|<([0-9A-Fa-f\s]+)>\s*Tj|\[([^\]]*)\]\s*TJ", re.S)
    chunks: list[str] = []
    for obj_id in sorted(objects):
        blob = _pdf_stream(objects[obj_id])
        if b"Tj" not in blob and b"TJ" not in blob:
            continue
        current = None
        for match in token.finditer(blob.decode("latin1", errors="ignore")):
            if match.group(1):
                current = font_names.get(match.group(1))
            elif match.group(2):
                chunks.append(_map_hex(match.group(2), cmaps.get(current or -1, {})))
            else:
                chunks.append(_show_text(match.group(3), cmaps.get(current or -1, {})))
    text = _SPACE.sub(" ", "".join(chunks)).strip()
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    return text if chinese >= 20 else ""


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        return


def _month_ends(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    windows = []
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            nxt = dt.date(cursor.year + 1, 1, 1)
        else:
            nxt = dt.date(cursor.year, cursor.month + 1, 1)
        windows.append((cursor, min(end, nxt - dt.timedelta(days=1))))
        cursor = nxt
    return windows


def _index_path(raw_root: Path, searchkey: str, start: dt.date, end: dt.date, page: int) -> Path:
    return raw_root / "cninfo" / "events_v0_index" / searchkey / f"{start}_{end}" / f"page_{page}.json"


def _load_or_fetch_pages(raw_root: Path, searchkey: str, start: dt.date, end: dt.date,
                         session: Any) -> list[dict]:
    done = _index_path(raw_root, searchkey, start, end, 0).with_name("done.json")
    folder = done.parent
    if done.is_file():
        rows = []
        for path in sorted(folder.glob("page_*.json")):
            rows.extend(json.loads(path.read_text(encoding="utf-8"))["rows"])
        return rows
    # Wide windows churn often; bisect quickly. Single-day windows retry harder.
    max_attempts = 5 if start >= end else 2
    for attempt in range(max_attempts):
        collected = []
        try:
            for page, (params, rows) in enumerate(
                    announcement_pages(start, end, category="", searchkey=searchkey,
                                       session=session), 1):
                target = _index_path(raw_root, searchkey, start, end, page)
                # Replace any partial page from a prior failed pagination attempt.
                if target.is_file():
                    target.unlink()
                _write_new(target, json.dumps({"parameters": params, "rows": rows},
                                              ensure_ascii=False))
                collected.extend(rows)
            _write_new(done, json.dumps({"rows": len(collected)}))
            return collected
        except AnnouncementSetChanged:
            for path in folder.glob("page_*.json"):
                path.unlink(missing_ok=True)
            if attempt + 1 < max_attempts:
                time.sleep(2 * (attempt + 1))
                continue
            # Month-sized windows can churn mid-pagination; bisect until single-day.
            if start >= end:
                raise
            mid = start + (end - start) // 2
            left = _load_or_fetch_pages(raw_root, searchkey, start, mid, session)
            right = _load_or_fetch_pages(raw_root, searchkey, mid + dt.timedelta(days=1),
                                         end, session)
            return left + right
    return []


def bulletin_text(row: dict, session: Any, pdf_dir: Path | None = None) -> str:
    if pdf_dir is not None:
        cached_pdf = pdf_dir/f"{row.get('announcementId')}.pdf"
        if cached_pdf.is_file():
            return pdf_plain_text(cached_pdf.read_bytes())[:MAX_INPUT_CHARS]
    when = published_date(row.get("announcementTime"))
    try:
        response = session.post(
            "https://www.cninfo.com.cn/new/announcement/bulletin_detail",
            data={"announceId": str(row.get("announcementId")), "flag": "true",
                  "announceTime": "" if when is None else when.isoformat()},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        body = {}
    html = ""
    if isinstance(body, dict):
        html = body.get("announcementContent") or ""
        nested = body.get("announcement")
        if not html and isinstance(nested, dict):
            html = nested.get("announcementContent") or ""
    if not isinstance(html, str):
        html = ""
    text = _SPACE.sub(" ", _TAGS.sub(" ", html)).strip()
    if text:
        return text[:MAX_INPUT_CHARS]
    relative = str(row.get("adjunctUrl") or "")
    if not re.fullmatch(r"finalpage/[0-9-]+/[0-9]+\.[pP][dD][fF]", relative):
        return ""
    try:
        data = download_document(relative, session=session)
    except Exception:
        return ""
    if pdf_dir is not None:
        identity = str(row.get("announcementId") or "")
        if identity:
            path = pdf_dir / f"{identity}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                pass
    return pdf_plain_text(data)[:MAX_INPUT_CHARS]


def _message_text(response: dict) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    for key in ("content", "text"):
        if isinstance(response.get(key), str):
            return response[key]
    return ""


_LEDGER_LOCK = threading.Lock()


def _task_spend(ledger_root: Path, now: dt.datetime | None = None) -> float:
    from quant.llm.ledger import month_path
    path = month_path(ledger_root, now=now)
    if not path.is_file():
        return 0.0
    with _LEDGER_LOCK:
        total = 0.0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("task") == "event_extract":
                value = row.get('usd')
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid event extraction charge')
                total += float(value)
        return total


def _record_spend(response: dict, ledger_root: Path, pricing: Path, announcement_id: str,
                  request_id: str | None = None, now: dt.datetime | None = None) -> float:
    from quant.llm.ledger import append
    from quant.research.gp_hints import priced_usd
    usd, estimated = priced_usd(response, pricing)
    unknown = usd is None or not math.isfinite(usd) or usd <= 0
    if unknown:
        usd, estimated = .02, True
    with _LEDGER_LOCK:
        append({"task": "event_extract", "announcement_id": announcement_id, "usd": usd,
                "estimated": estimated, "usage": response.get("usage"),
                'unknown_charge': unknown, 'event_request_id': request_id}, ledger_root, now=now)
    return usd


def build_events(
    *,
    start: dt.date,
    end: dt.date,
    data_root: Path,
    artifact_root: Path,
    session: Any,
    complete: Callable[[list[dict[str, str]], dict], dict],
    pricing: Path = Path("configs/llm/pricing.toml"),
    ledger_root: Path = Path("artifacts/research/llm_ledger"),
    limit: int | None = None,
    workers: int = 4,
    resume: bool = False,
    collect_only: bool = False,
) -> dict[str, Any]:
    """Append raw pages, extract fields, and write versioned tables once."""
    if start > end:
        raise ValueError("start must not exceed end")
    raw_root = data_root / "raw"
    version = artifact_root / f"events_v0_{end.isoformat()}"
    partition = end.strftime('%Y%m%d')
    resumed_from = None
    if resume:
        previous = sorted(path for path in artifact_root.glob('events_v0_*/summary.json')
                          if re.fullmatch(r'events_v0_\d{4}-\d{2}-\d{2}(?:_\d{8}T\d{6}_\d{6})?', path.parent.name)
                          and path.parent.name[10:20] <= end.isoformat())
        resumed_from = str(previous[-1]) if previous else None
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S_%f')
        version = version.with_name(version.name+'_'+stamp)
        partition += '_'+stamp
    if (version / "summary.json").exists():
        raise ValueError("event summary already exists")
    targets = {name: data_root/'clean/events'/name/f'version={partition}'/'events.parquet'
               for name in ('repurchase', 'insider_trading')}
    for target in targets.values():
        if target.exists():
            raise ValueError(f'refuse to overwrite {target}')
    rates = load_pricing(pricing)
    cache = artifact_root / "events_v0_cache_v2"
    rows: list[dict] = []
    seen: set[str] = set()
    stopped = None
    calls = 0
    calls_lock = threading.Lock()

    def filing_row(source: dict, family: str, symbol: str, published: dt.date, title: str) -> dict | None:
        nonlocal calls
        identity = str(source.get("announcementId") or "")
        text_path = raw_root / "cninfo" / "events_v0_text_v2" / f"{identity}.txt"
        recovered = text_path.is_file() and not text_path.stat().st_size
        if recovered:
            retries = text_path.parent/'retries'/identity
            available = sorted((p for p in retries.glob('*.txt') if p.stat().st_size), reverse=True)
            text_path = available[0] if available else retries/f'{partition}.txt'
        if not text_path.is_file():
            try:
                _write_new(text_path, bulletin_text(
                    source, session, raw_root / "cninfo" / "events_v0_pdf"))
            except Exception:
                _write_new(text_path, "")
        excerpt = text_path.read_text(encoding="utf-8")[:MAX_INPUT_CHARS]
        cached = cache / f"{identity}.json"
        if recovered and excerpt:
            cached = cache/'recovered'/identity/(hashlib.sha256(excerpt.encode('utf-8')).hexdigest()+'.json')
        if cached.is_file():
            parsed = json.loads(cached.read_text(encoding="utf-8"))
        elif not excerpt:
            parsed = accept_extraction("", {"status": "unresolved"})
        elif collect_only:
            # Keep text for a later budget window; no extraction result exists yet.
            parsed = accept_extraction('', {'status': 'unresolved'})
        else:
            if _task_spend(ledger_root) >= TASK_BUDGET_USD:
                return {"_stop": "budget"}
            from quant.llm import RequestFailure
            from quant.data.events_v0_budget import complete_with_budget, EventBudgetExhausted
            response = None
            for attempt in range(2):
                try:
                    response = complete_with_budget(complete, [
                        {"role": "system", "content": (
                            "只从摘录抽取回购实施或股东增减持。返回 JSON，键为 status、amount_cny、"
                            "ratio_pct、term_days、direction、evidence。status 只能是 parsed 或 unresolved。"
                            "amount_cny 用人民币元，只填已经支付或成交的总金额，不填不低于/不超过的方案区间。"
                            "ratio_pct 是百分数本身。direction 只能是 buy、sell、"
                            "repurchase 或 null。evidence 必须是摘录里的连续原文。没有的数字不要猜。"
                        )},
                        {"role": "user", "content": excerpt},
                    ], {"max_tokens": 250, "max_usd": 0.02, "reserve_usd": 0.02,
                        "temperature": 0}, ledger_root=ledger_root, announcement_id=identity,
                        spend=_task_spend, limit=TASK_BUDGET_USD,
                        record=lambda reply, request_id, started: _record_spend(
                            reply, ledger_root, pricing, identity, request_id, started))
                    break
                except EventBudgetExhausted:
                    return {'_stop': 'budget'}
                except RequestFailure as exc:
                    if getattr(exc, "code", "") == "monthly_budget_exhausted":
                        return {"_stop": "budget"}
                    if attempt == 0 and getattr(exc, "retryable", False):
                        time.sleep(1)
                        continue
                    response = None
                    break
            if response is None:
                parsed = accept_extraction("", {"status": "unresolved"})
            else:
                with calls_lock:
                    calls += 1
                try:
                    payload = strict_json(_message_text(response))
                except ValueError:
                    payload = {"status": "unresolved"}
                parsed = accept_extraction(excerpt, payload)
                _write_new(cached, json.dumps(parsed, ensure_ascii=False))
        parsed = fill_explicit_total(excerpt, parsed, family)
        parsed = fill_explicit_ratio(excerpt, parsed)
        parsed = drop_unexecuted_sell(parsed)
        return {"announcement_id": identity, "symbol": symbol, "title": title,
                "published": published, "known_at": published, "family": family,
                "human_label": None, "excerpt": excerpt,
                "adjunct_url": source.get("adjunctUrl"), **parsed}

    for window_start, window_end in _month_ends(start, end):
        if stopped:
            break
        print(f"start {window_start}", flush=True)
        for family, searchkey in QUERIES:
            if stopped:
                break
            pending = []
            for source in _load_or_fetch_pages(raw_root, searchkey, window_start, window_end, session):
                if limit is not None and len(rows) + len(pending) >= limit:
                    stopped = "limit"
                    break
                identity = str(source.get("announcementId") or "")
                title = plain_title(source.get("announcementTitle"))
                if not identity or identity in seen or family_of(title) != family:
                    continue
                symbol = a_share_symbol(source.get("secCode"))
                published = published_date(source.get("announcementTime"))
                if symbol is None or published is None or not start <= published <= end:
                    continue
                seen.add(identity)
                pending.append((source, family, symbol, published, title))
            if not pending:
                continue
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for result in pool.map(lambda item: filing_row(*item), pending):
                    if not result:
                        continue
                    if result.get("_stop") == "budget":
                        stopped = "budget"
                        continue
                    rows.append(result)
        print(f"{window_start} rows={len(rows)} calls={calls} stopped={stopped}", flush=True)
    frame = pl.DataFrame(rows) if rows else pl.DataFrame(schema={
        "announcement_id": pl.String, "symbol": pl.String, "title": pl.String,
        "published": pl.Date, "known_at": pl.Date, "family": pl.String,
        "amount_cny": pl.Float64, "ratio_pct": pl.Float64, "term_days": pl.Int64,
        "direction": pl.String, "parse_status": pl.String, "human_label": pl.String,
        "evidence": pl.String, "excerpt": pl.String, "adjunct_url": pl.String})
    if rows:
        frame = frame.with_columns(
            pl.col("published").cast(pl.Date), pl.col("known_at").cast(pl.Date),
            pl.col("term_days").cast(pl.Int64),
        )
    EventV0Schema.validate(frame)
    version.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in ("repurchase", "insider_trading"):
        part = frame.filter(pl.col("family") == name)
        target = targets[name]
        folder = target.parent
        if target.exists():
            raise ValueError(f"refuse to overwrite {target}")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as handle:
                part.write_parquet(handle)
        except FileExistsError as exc:
            raise ValueError(f'refuse to overwrite {target}') from exc
        unresolved = 0 if part.is_empty() else int((part["parse_status"] == "unresolved").sum())
        months = [] if part.is_empty() else sorted({f"{d.year:04d}-{d.month:02d}" for d in part["published"].to_list()})
        counts[name] = {"rows": part.height, "unresolved": unresolved,
                        "unresolved_ratio": None if part.is_empty() else unresolved / part.height,
                        "months": months, "path": str(target)}
    sample = frame.head(0)
    if frame.height:
        parsed = frame.filter(pl.col("parse_status") == "parsed")
        pool = parsed if parsed.height >= 50 else frame
        sample = pool.sample(n=min(50, pool.height), seed=20261027)
    sample_path = version / "sample50.csv"
    with sample_path.open('x', encoding='utf-8', newline='') as handle:
        sample.write_csv(handle)
    summary = {"start": str(start), "end": str(end), "stopped": stopped,
               "llm_calls": calls, "task_budget_usd": TASK_BUDGET_USD,
               "pricing_input_usd_per_million": rates["input_usd_per_million"],
               "tables": counts, "sample_rows": sample.height, "sample_path": str(sample_path),
               "evaluate_this_round": False}
    summary.update(collect_only=collect_only, partition=partition, resumed_from=resumed_from)
    summary['publication_timezone'] = 'Asia/Shanghai'
    summary['text_nonempty'] = sum(bool(row.get('excerpt')) for row in rows)
    summary['text_unavailable'] = len(rows)-summary['text_nonempty']
    with (version/'summary.json').open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--to", dest="end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts/data"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument('--resume', action='store_true', help='Reuse caches and publish a new immutable version')
    parser.add_argument('--collect-only', action='store_true', help='Collect source text without LLM calls')
    parser.add_argument('--workers', type=int, default=4,
                        help='Thread pool size for PDF/text collection and extraction (default 4)')
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit('--workers must be >= 1')
    from quant.llm import complete_messages
    import requests
    summary = build_events(start=args.start, end=args.end, data_root=args.data_root,
                           artifact_root=args.artifact_root, session=requests,
                           complete=complete_messages, limit=args.limit,
                           workers=args.workers, resume=args.resume,
                           collect_only=args.collect_only)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
