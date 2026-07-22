"""Versioned HKEX temporary-counter lifecycle facts and as-of projection."""

from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

HK_TEMPORARY_SELECTION_RULE = "temporary_counter_lifecycle_as_of_v1"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HK_SYMBOL = re.compile(r"^\d{5}\.HK$")
_REQUIRED_EVIDENCE_ROLES = {"TRADING_SCHEDULE", "FINAL_EFFECTIVE"}


@dataclass(frozen=True)
class HkexNoticeEvidence:
    role: str
    announcement_id: str
    published_date: dt.date
    url: str
    content_sha256: str


@dataclass(frozen=True)
class TemporaryCounterLifecycle:
    symbol: str
    related_symbol: str
    name: str
    instrument_type: str
    currency: str
    event: str
    list_date: dt.date
    parallel_trading_end: dt.date
    delist_date: dt.date
    certificate_delivery_end: dt.date
    ccass_conversion_end: dt.date
    board_lot: int


@dataclass(frozen=True)
class HkexTemporaryCounterNotice:
    version: int
    market: str
    source: str
    selection_rule: str
    evidence: tuple[HkexNoticeEvidence, ...]
    counters: tuple[TemporaryCounterLifecycle, ...]


def load_hkex_temporary_counter_notice(path: Path) -> HkexTemporaryCounterNotice:
    """Load and strictly validate versioned HKEX temporary-counter facts."""
    try:
        with path.open("rb") as stream:
            data: dict[str, Any] = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID") from None
    if set(data) != {
        "version",
        "market",
        "source",
        "selection_rule",
        "evidence",
        "counters",
    }:
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    try:
        evidence = tuple(_parse_evidence(item) for item in data["evidence"])
        counters = tuple(_parse_counter(item) for item in data["counters"])
        notice = HkexTemporaryCounterNotice(
            version=data["version"],
            market=data["market"],
            source=data["source"],
            selection_rule=data["selection_rule"],
            evidence=evidence,
            counters=counters,
        )
    except (KeyError, TypeError):
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID") from None
    _validate_notice(notice)
    return notice


def temporary_counter_raw_frame(notice: HkexTemporaryCounterNotice) -> pl.DataFrame:
    """Return deterministic raw facts, including the official evidence closure."""
    _validate_notice(notice)
    evidence_json = json.dumps(
        [
            {
                "role": item.role,
                "announcement_id": item.announcement_id,
                "published_date": item.published_date.isoformat(),
                "url": item.url,
                "content_sha256": item.content_sha256,
            }
            for item in notice.evidence
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return pl.from_dicts(
        [
            {
                **vars(item),
                "evidence_json": evidence_json,
                "notice_version": notice.version,
                "selection_rule": notice.selection_rule,
            }
            for item in notice.counters
        ]
    ).sort(["symbol", "list_date"])


def project_temporary_instruments(
    notice: HkexTemporaryCounterNotice,
    *,
    target_symbols: tuple[str, ...],
    as_of: dt.date,
) -> pl.DataFrame:
    """Project the latest known lifecycle for every exact target at ``as_of``."""
    _validate_notice(notice)
    targets = _normalize_targets(target_symbols)
    projected: list[dict[str, object]] = []
    for symbol in targets:
        candidates = [
            item
            for item in notice.counters
            if item.symbol == symbol and item.list_date <= as_of
        ]
        if not candidates:
            raise ValueError("HK_TEMPORARY_COVERAGE_INCOMPLETE")
        item = max(candidates, key=lambda value: value.list_date)
        projected.append(
            {
                "symbol": item.symbol,
                "market": "HK",
                "name": item.name,
                "instrument_type": item.instrument_type,
                "currency": item.currency,
                "list_date": item.list_date,
                "delist_date": item.delist_date,
                "board_lot": item.board_lot,
                "status": "LISTED" if as_of <= item.delist_date else "DELISTED",
            }
        )
    result = pl.from_dicts(
        projected,
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
    if tuple(result.get_column("symbol")) != targets:
        raise ValueError("HK_TEMPORARY_COVERAGE_INCOMPLETE")
    return result


def _parse_evidence(data: object) -> HkexNoticeEvidence:
    if type(data) is not dict or set(data) != {
        "role",
        "announcement_id",
        "published_date",
        "url",
        "content_sha256",
    }:
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    return HkexNoticeEvidence(**data)


def _parse_counter(data: object) -> TemporaryCounterLifecycle:
    expected = {
        "symbol",
        "related_symbol",
        "name",
        "instrument_type",
        "currency",
        "event",
        "list_date",
        "parallel_trading_end",
        "delist_date",
        "certificate_delivery_end",
        "ccass_conversion_end",
        "board_lot",
    }
    if type(data) is not dict or set(data) != expected:
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    return TemporaryCounterLifecycle(**data)


def _validate_notice(notice: HkexTemporaryCounterNotice) -> None:
    if (
        type(notice.version) is not int
        or notice.version != 1
        or notice.market != "HK"
        or notice.source != "hkex"
        or notice.selection_rule != HK_TEMPORARY_SELECTION_RULE
        or not notice.evidence
        or not notice.counters
    ):
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    roles = {evidence_item.role for evidence_item in notice.evidence}
    if not _REQUIRED_EVIDENCE_ROLES.issubset(roles):
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    if len({evidence_item.announcement_id for evidence_item in notice.evidence}) != len(
        notice.evidence
    ):
        raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    for evidence_item in notice.evidence:
        if (
            type(evidence_item.role) is not str
            or type(evidence_item.announcement_id) is not str
            or not evidence_item.announcement_id
            or type(evidence_item.published_date) is not dt.date
            or type(evidence_item.url) is not str
            or not evidence_item.url.startswith("https://")
            or type(evidence_item.content_sha256) is not str
            or _HEX64.fullmatch(evidence_item.content_sha256) is None
        ):
            raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
    seen_keys: set[tuple[str, dt.date]] = set()
    by_symbol: dict[str, list[TemporaryCounterLifecycle]] = {}
    for counter in notice.counters:
        key = (counter.symbol, counter.list_date)
        if key in seen_keys:
            raise ValueError("HK_TEMPORARY_LIFECYCLE_CONFLICT")
        seen_keys.add(key)
        if (
            type(counter.symbol) is not str
            or _HK_SYMBOL.fullmatch(counter.symbol) is None
            or type(counter.related_symbol) is not str
            or _HK_SYMBOL.fullmatch(counter.related_symbol) is None
            or counter.related_symbol == counter.symbol
            or type(counter.name) is not str
            or not counter.name.strip()
            or counter.instrument_type != "STOCK"
            or counter.currency != "HKD"
            or counter.event != "SHARE_SUBDIVISION_TEMP_COUNTER"
            or any(
                type(value) is not dt.date
                for value in (
                    counter.list_date,
                    counter.parallel_trading_end,
                    counter.delist_date,
                    counter.certificate_delivery_end,
                    counter.ccass_conversion_end,
                )
            )
            or counter.delist_date != counter.parallel_trading_end
            or not (
                counter.list_date
                <= counter.delist_date
                < counter.certificate_delivery_end
                <= counter.ccass_conversion_end
            )
            or type(counter.board_lot) is not int
            or isinstance(counter.board_lot, bool)
            or counter.board_lot <= 0
        ):
            raise ValueError("HK_TEMPORARY_NOTICE_INVALID")
        by_symbol.setdefault(counter.symbol, []).append(counter)
    for lifecycles in by_symbol.values():
        ordered = sorted(lifecycles, key=lambda item: item.list_date)
        if any(
            right.list_date <= left.delist_date
            for left, right in zip(ordered, ordered[1:])
        ):
            raise ValueError("HK_TEMPORARY_LIFECYCLE_CONFLICT")


def _normalize_targets(symbols: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not symbols
        or len(set(symbols)) != len(symbols)
        or tuple(sorted(symbols)) != symbols
        or any(type(symbol) is not str or _HK_SYMBOL.fullmatch(symbol) is None for symbol in symbols)
    ):
        raise ValueError("HK_TEMPORARY_TARGETS_INVALID")
    return symbols
