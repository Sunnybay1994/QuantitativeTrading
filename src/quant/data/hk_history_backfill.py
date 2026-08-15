"""Strict, resumable Tushare HK daily-history backfill.

The module deliberately keeps the undocumented multi-symbol wire contract behind
an immutable plan.  A network response is persisted before its contents are
accepted, and clean bars are published only after every planned batch is closed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, NoReturn, Sequence

import polars as pl

from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.connectors.tushare import TushareConnector
from quant.data.hkex_daily_quotations import (
    EXPECTED_RAW_SHA256 as HKEX_02983_RAW_SHA256,
    SOURCE_URL as HKEX_02983_SOURCE_URL,
    HKEXDailyQuotationsError,
    VerifiedHKEXDailyQuotationRetainedBundle,
    verify_hkex_daily_quotation,
    verify_hkex_daily_quotation_retained,
    verify_hkex_daily_quotation_retained_bundle,
)
from quant.data.mappers import TushareBarMapper
from quant.data.storage import CleanBarStore, RawStore, RequestRawSnapshot
from quant.domain import Bar1dSchema, HkBarAvailabilityEvidenceSchema
from quant.domain.schemas import HKNoTradeEvidenceSchema

HK_DAILY_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
)
HK_HISTORY_STRATEGY = "MULTI_SYMBOL_RANGE_STRICT_V1"
HK_HISTORY_SCHEMA_VERSION = "hk-history-plan-v1"
HK_HISTORY_STRATEGY_V2 = "MULTI_SYMBOL_RANGE_STRICT_V2"
HK_HISTORY_SCHEMA_VERSION_V2 = "hk-history-plan-v2"
HK_NO_TRADE_EVIDENCE_SET_VERSION = "hk-no-trade-evidence-set-v1"
HK_NO_TRADE_USER_APPROVED_SOURCE = "USER_APPROVED_MULTI_SOURCE_CONSENSUS"
HK_HISTORY_COOLDOWN_SECONDS = 3600
HK_HISTORY_MAX_BATCH_SYMBOLS = 80
HK_HISTORY_ROW_LIMIT = 5000
HK_HISTORY_RAW_TABLE = "hk_daily_multi_symbol_backfill"
_HK_SYMBOL = re.compile(r"^[0-9]{5}\.HK$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RAW_COLUMNS = tuple(HK_DAILY_FIELDS.split(","))
_HKEX_SUPPLEMENT_UNRESOLVED = (("02983.HK", ("2026-07-10",)),)
_AVAILABILITY_FILE = "availability.json"
_HKEX_RETAINED_RAW_FILE = "hkex-retained.raw"
_HKEX_RETAINED_METADATA_FILE = "hkex-retained.metadata.json"
_USER_APPROVED_RECORD_NAMESPACE = "UA-M1-"
_USER_APPROVED_SELECTOR_NAMESPACE = "user-approved-consensus/"
_USER_APPROVED_NO_TRADE_KEY = ("01065.HK", "2026-05-05")
_USER_APPROVED_NO_TRADE_RECORD = "UA-M1-001"
_USER_APPROVED_NO_TRADE_SELECTOR = (
    "user-approved-consensus/ua-m1-001-01065-2026-05-05.record"
)
_USER_APPROVED_SUSPENSION_RANGE_RECORD = "UA-M1-004"
_USER_APPROVED_SUSPENSION_RANGE_SELECTOR = (
    "user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record"
)
_USER_APPROVED_SUSPENSION_RANGE_SYMBOL = "02402.HK"
_USER_APPROVED_SUSPENSION_RANGE_DATES = (
    "2026-04-14",
    "2026-04-15",
    "2026-04-16",
    "2026-04-17",
    "2026-04-20",
    "2026-04-21",
    "2026-04-22",
    "2026-04-23",
    "2026-04-24",
    "2026-04-27",
    "2026-04-28",
    "2026-04-29",
    "2026-04-30",
)
_USER_APPROVED_SUSPENSION_AT = "2026-04-01T01:00:00+00:00"
_USER_APPROVED_RESUMPTION_AT = "2026-05-04T01:00:00+00:00"
_USER_APPROVED_SUSPENSION_NOTICE_URL = (
    "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0401/2026040100185.htm"
)
_USER_APPROVED_RESUMPTION_NOTICE_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0504/2026050400135.htm"
)
_USER_APPROVED_TRADING_HALT_KEY = ("06110.HK", "2026-06-25")
_USER_APPROVED_TRADING_HALT_RECORD = "UA-M1-005"
_USER_APPROVED_TRADING_HALT_SELECTOR = (
    "user-approved-consensus/ua-m1-005-06110-2026-06-25.record"
)
_USER_APPROVED_TRADING_HALT_NOTICE_URL = (
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0625/2026062500129.htm"
)
_USER_APPROVED_TRADING_HALT_INDEPENDENT_URL = (
    "https://www.etnet.com.hk/www/tc/news/news-article.php"
    "?category=latest&newsid=2026062568&section=categorized"
)
_USER_APPROVED_SUSPENSION_OBSERVATION = (
    "H_SHARES_SUSPENDED_FROM_2026-04-01T01:00:00+00:00"
)
_USER_APPROVED_RESUMPTION_OBSERVATION = (
    "H_SHARES_RESUMED_FROM_2026-05-04T01:00:00+00:00"
)
_USER_APPROVED_TUSHARE_ZERO_ROW_OBSERVATION = "RETAINED_ZERO_ROW"
_CAPABILITY_SECRET = os.urandom(32)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class HKHistoryBackfillError(RuntimeError):
    """A stable, sanitized HK history failure code."""


class VerifiedHkBarBundle:
    """Process-local, content-bound view of a freshly verified v3 publication."""

    __slots__ = (
        "_bars",
        "_availability",
        "plan_sha256",
        "publication_sha256",
        "_root_identities",
        "_attestation",
    )

    _bars: pl.DataFrame
    _availability: pl.DataFrame
    plan_sha256: str
    publication_sha256: str
    _root_identities: tuple[tuple[str, int, int], ...]
    _attestation: str

    def __new__(cls, *_args: object, **_kwargs: object) -> VerifiedHkBarBundle:
        del cls
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None

    def __init_subclass__(cls, **_kwargs: object) -> None:
        del cls
        raise TypeError("VerifiedHkBarBundle is final")

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None

    @property
    def bars(self) -> pl.DataFrame:
        return self._bars.clone()

    @property
    def availability(self) -> pl.DataFrame:
        return self._availability.clone()

    def __reduce__(self) -> NoReturn:
        raise TypeError("VerifiedHkBarBundle is process-local")


@dataclass(frozen=True)
class HKNoTradeEvidence:
    """One exact no-daily-trading fact bound to retained authoritative raw bytes."""

    schema_version: str
    evidence_sha256: str
    symbol: str
    trade_date: str
    market: str
    reason: str
    source: str
    source_record_id: str
    source_as_of: str
    raw_selector: str
    raw_file_sha256: str
    raw_metadata_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != "hk-no-trade-evidence-v1"
            or not _HEX64.fullmatch(self.evidence_sha256)
            or not _HK_SYMBOL.fullmatch(self.symbol)
            or self.market != "HK"
            or self.reason != "NO_DAILY_TRADING_V1"
            or self.source not in {
                "HKEX_DAILY_QUOTATIONS",
                HK_NO_TRADE_USER_APPROVED_SOURCE,
            }
            or type(self.source_record_id) is not str
            or not self.source_record_id
            or not _HEX64.fullmatch(self.raw_file_sha256)
            or not _HEX64.fullmatch(self.raw_metadata_sha256)
        ):
            raise ValueError("no-trade evidence contract invalid")
        _date(self.trade_date)
        _utc(dt.datetime.fromisoformat(self.source_as_of))
        _validate_selector(self.raw_selector, suffix=None)
        if self.source == HK_NO_TRADE_USER_APPROVED_SOURCE and not (
            _user_approved_no_trade_is_exact(self)
        ):
            raise ValueError("no-trade evidence contract invalid")
        if (
            self.source_record_id.startswith(_USER_APPROVED_RECORD_NAMESPACE)
            or self.raw_selector.startswith(_USER_APPROVED_SELECTOR_NAMESPACE)
        ) and self.source != HK_NO_TRADE_USER_APPROVED_SOURCE:
            raise ValueError("no-trade evidence contract invalid")
        if self.evidence_sha256 != _evidence_identity(self):
            raise ValueError("no-trade evidence identity mismatch")


@dataclass(frozen=True)
class HKNoTradeEvidenceSet:
    """Canonical conflict-free no-trade evidence set."""

    schema_version: str
    evidences: tuple[HKNoTradeEvidence, ...]
    evidence_set_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != HK_NO_TRADE_EVIDENCE_SET_VERSION
            or not self.evidences
            or not _HEX64.fullmatch(self.evidence_set_sha256)
        ):
            raise ValueError("no-trade evidence set invalid")
        keys = tuple((item.symbol, item.trade_date) for item in self.evidences)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("no-trade evidence key conflict")
        if self.evidence_set_sha256 != _evidence_set_identity(self.evidences):
            raise ValueError("no-trade evidence set identity mismatch")


@dataclass(frozen=True)
class HKHistorySeed:
    """An already-fetched raw snapshot reused without a wire request."""

    selector: str
    symbols: tuple[str, ...]
    checksum_sha256: str
    metadata_sha256: str

    def __post_init__(self) -> None:
        _validate_selector(self.selector)
        _validate_symbols(self.symbols, allow_empty=False)
        if not _HEX64.fullmatch(self.checksum_sha256) or not _HEX64.fullmatch(
            self.metadata_sha256
        ):
            raise ValueError("seed digest 非法")


@dataclass(frozen=True)
class HKHistoryRequest:
    """One immutable multi-symbol hk_daily wire request."""

    request_id: str
    symbols: tuple[str, ...]
    expected_dates: tuple[tuple[str, tuple[str, ...]], ...]
    parameters: tuple[tuple[str, str], ...]
    effective_expected_dates: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        _validate_symbols(self.symbols, allow_empty=False)
        if len(self.symbols) > HK_HISTORY_MAX_BATCH_SYMBOLS:
            raise ValueError("batch symbols 超过 80")
        _validate_expected_dates(self.expected_dates, self.symbols)
        if self.effective_expected_dates:
            _validate_expected_dates(
                self.effective_expected_dates,
                self.symbols,
                allow_empty_dates=True,
            )
            original = dict(self.expected_dates)
            if any(
                not set(dates).issubset(original[symbol])
                for symbol, dates in self.effective_expected_dates
            ):
                raise ValueError("effective expected dates exceed original")
        parameters = _request_parameters(self.symbols)
        if self.parameters != parameters or self.request_id != _request_id(parameters):
            raise ValueError("request identity 不一致")


@dataclass(frozen=True)
class HKHistoryPlan:
    """Canonical HK60 plan containing every expected symbol/date key."""

    schema_version: str
    strategy: str
    as_of: str
    window_start: str
    window_end: str
    fields: str
    batch_size: int
    expected_dates: tuple[tuple[str, tuple[str, ...]], ...]
    seed: HKHistorySeed
    unresolved: tuple[tuple[str, tuple[str, ...]], ...]
    requests: tuple[HKHistoryRequest, ...]
    plan_sha256: str
    no_trade_evidence: tuple[HKNoTradeEvidence, ...] = ()
    no_trade_evidence_sha256: str = ""
    effective_expected_dates: tuple[tuple[str, tuple[str, ...]], ...] = ()
    journal_id: str = ""

    def __post_init__(self) -> None:
        if (
            self.schema_version not in {HK_HISTORY_SCHEMA_VERSION, HK_HISTORY_SCHEMA_VERSION_V2}
            or self.strategy
            != (
                HK_HISTORY_STRATEGY_V2
                if self.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
                else HK_HISTORY_STRATEGY
            )
            or self.fields != HK_DAILY_FIELDS
            or self.batch_size != HK_HISTORY_MAX_BATCH_SYMBOLS
        ):
            raise ValueError("plan contract 非法")
        as_of = _date(self.as_of)
        start, end = _date(self.window_start), _date(self.window_end)
        if start > end or end != as_of:
            raise ValueError("plan window 非法")
        expected_symbols = tuple(symbol for symbol, _ in self.expected_dates)
        _validate_expected_dates(self.expected_dates, expected_symbols)
        is_v2 = self.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
        if is_v2:
            _validate_expected_dates(
                self.effective_expected_dates,
                expected_symbols,
                allow_empty_dates=True,
            )
            if (
                not self.no_trade_evidence
                or not _HEX64.fullmatch(self.no_trade_evidence_sha256)
                or not _HEX64.fullmatch(self.journal_id)
            ):
                raise ValueError("v2 identity closure invalid")
            if self.no_trade_evidence_sha256 != _evidence_set_identity(
                self.no_trade_evidence
            ):
                raise ValueError("v2 evidence set drift")
            original = dict(self.expected_dates)
            effective = dict(self.effective_expected_dates)
            evidence_keys = {(item.symbol, item.trade_date) for item in self.no_trade_evidence}
            original_keys = {
                (symbol, date_value)
                for symbol, dates in self.expected_dates
                for date_value in dates
            }
            if not evidence_keys.issubset(original_keys):
                raise ValueError("v2 evidence target outside original expected")
            if self.effective_expected_dates != tuple(
                (
                    symbol,
                    tuple(
                        date_value
                        for date_value in original[symbol]
                        if (symbol, date_value) not in evidence_keys
                    ),
                )
                for symbol in expected_symbols
            ):
                raise ValueError("v2 effective expected drift")
        elif (
            self.no_trade_evidence
            or self.no_trade_evidence_sha256
            or self.effective_expected_dates
            or self.journal_id
        ):
            raise ValueError("v1 contains v2 fields")
        if start != dt.date(2026, 4, 14) or end != dt.date(2026, 7, 10):
            raise ValueError("plan window 不是冻结区间")
        if any(
            not start <= _date(value) <= end
            for _, dates in self.expected_dates
            for value in dates
        ):
            raise ValueError("expected dates 超出冻结区间")
        _validate_expected_dates(self.unresolved, tuple(symbol for symbol, _ in self.unresolved))
        expected = dict(self.expected_dates)
        seed_symbols = set(self.seed.symbols)
        unresolved_symbols = {symbol for symbol, _ in self.unresolved}
        if not seed_symbols <= set(expected) or not unresolved_symbols <= set(expected):
            raise ValueError("seed/unresolved 不在 expected 中")
        if seed_symbols & unresolved_symbols:
            raise ValueError("seed 与 unresolved 重叠")
        request_symbols: list[str] = []
        for request in self.requests:
            request_symbols.extend(request.symbols)
            if dict(request.expected_dates) != {
                symbol: expected[symbol] for symbol in request.symbols
            }:
                raise ValueError("request expected dates 漂移")
            if is_v2 and dict(request.effective_expected_dates) != {
                symbol: effective[symbol] for symbol in request.symbols
            }:
                raise ValueError("request effective expected dates drift")
        target = sorted(set(expected) - seed_symbols - unresolved_symbols)
        if request_symbols != target or len(request_symbols) != len(set(request_symbols)):
            raise ValueError("request symbols 未精确分区")
        if self.plan_sha256 != _plan_hash_values(self):
            raise ValueError("plan_sha256 不一致")


@dataclass(frozen=True)
class HKHistoryExecutionResult:
    """Result of one invocation; at most one new wire request was attempted."""

    request_id: str | None
    network_requests: int
    completed_requests: int
    total_requests: int
    is_complete: bool


def build_hk_history_plan(
    *,
    expected_dates: Mapping[str, Sequence[dt.date]],
    seed: HKHistorySeed,
    unresolved: Mapping[str, Sequence[dt.date]],
    as_of: dt.date,
    window_start: dt.date,
) -> HKHistoryPlan:
    """Build the canonical sorted plan, partitioning non-seed work into batches."""
    try:
        if type(as_of) is not dt.date or type(window_start) is not dt.date:
            raise ValueError
        if (
            window_start != dt.date(2026, 4, 14)
            or as_of != dt.date(2026, 7, 10)
            or not isinstance(expected_dates, Mapping)
        ):
            raise ValueError
        normalized = _normalize_expected_dates(expected_dates)
        unresolved_normalized = (
            _normalize_expected_dates(unresolved) if unresolved else ()
        )
        expected = dict(normalized)
        for symbol, dates in unresolved_normalized:
            if symbol not in expected or dates != expected[symbol]:
                raise ValueError
        remaining = sorted(set(expected) - set(seed.symbols) - set(dict(unresolved_normalized)))
        requests = tuple(
            _make_request(tuple(remaining[offset : offset + HK_HISTORY_MAX_BATCH_SYMBOLS]), expected)
            for offset in range(0, len(remaining), HK_HISTORY_MAX_BATCH_SYMBOLS)
        )
        values: dict[str, Any] = {
            "schema_version": HK_HISTORY_SCHEMA_VERSION,
            "strategy": HK_HISTORY_STRATEGY,
            "as_of": as_of.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": as_of.isoformat(),
            "fields": HK_DAILY_FIELDS,
            "batch_size": HK_HISTORY_MAX_BATCH_SYMBOLS,
            "expected_dates": normalized,
            "seed": seed,
            "unresolved": unresolved_normalized,
            "requests": requests,
            "plan_sha256": "0" * 64,
        }
        hash_values = dict(values)
        hash_values["seed"] = asdict(seed)
        hash_values["requests"] = [
            {key: value for key, value in asdict(request).items() if key != "effective_expected_dates"}
            for request in requests
        ]
        hash_values["plan_sha256"] = "0" * 64
        values["plan_sha256"] = hashlib.sha256(
            _canonical_json(hash_values).encode()
        ).hexdigest()
        return HKHistoryPlan(**values)
    except (KeyError, TypeError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_INPUT_INVALID") from None


def load_hk_no_trade_evidence(
    path: Path, *, raw_root: Path
) -> HKNoTradeEvidenceSet:
    """Load canonical evidence and verify every retained raw/metadata byte digest."""
    result: HKNoTradeEvidenceSet | None = None
    failure: str | None = None
    try:
        payload = path.read_bytes()
        value = _strict_json(payload)
        if set(value) != {"schema_version", "evidences", "evidence_set_sha256"}:
            raise ValueError
        if type(value["evidences"]) is not list:
            raise ValueError
        evidences = tuple(_evidence_from_dict(item) for item in value["evidences"])
        loaded = HKNoTradeEvidenceSet(
            schema_version=value["schema_version"],
            evidences=evidences,
            evidence_set_sha256=value["evidence_set_sha256"],
        )
        expected_payload = _canonical_json(
            {
                "schema_version": loaded.schema_version,
                "evidences": [asdict(item) for item in loaded.evidences],
                "evidence_set_sha256": loaded.evidence_set_sha256,
            }
        ).encode("utf-8")
        if payload != expected_payload:
            raise ValueError
        _verify_evidence_projection(loaded, raw_root=raw_root)
        result = loaded
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    return result


def build_hk_history_plan_v2(
    *,
    expected_dates: Mapping[str, Sequence[dt.date]],
    seed: HKHistorySeed,
    unresolved: Mapping[str, Sequence[dt.date]],
    evidence: HKNoTradeEvidenceSet,
    as_of: dt.date,
    window_start: dt.date,
) -> HKHistoryPlan:
    """Build a v2 plan whose effective keys subtract only exact verified evidence."""
    result: HKHistoryPlan | None = None
    failure: str | None = None
    try:
        if (
            type(as_of) is not dt.date
            or type(window_start) is not dt.date
            or window_start != dt.date(2026, 4, 14)
            or as_of != dt.date(2026, 7, 10)
            or type(evidence) is not HKNoTradeEvidenceSet
        ):
            raise ValueError
        normalized = _normalize_expected_dates(expected_dates)
        unresolved_normalized = _normalize_expected_dates(unresolved) if unresolved else ()
        original = dict(normalized)
        for symbol, dates in unresolved_normalized:
            if symbol not in original or dates != original[symbol]:
                raise ValueError
        evidence_keys = {(item.symbol, item.trade_date) for item in evidence.evidences}
        original_keys = {
            (symbol, date_value)
            for symbol, dates in normalized
            for date_value in dates
        }
        if not evidence_keys.issubset(original_keys):
            raise ValueError
        evidence_symbols = {symbol for symbol, _ in evidence_keys}
        if evidence_symbols & (
            set(seed.symbols) | set(dict(unresolved_normalized))
        ):
            raise ValueError
        effective = tuple(
            (
                symbol,
                tuple(
                    date_value
                    for date_value in dates
                    if (symbol, date_value) not in evidence_keys
                ),
            )
            for symbol, dates in normalized
        )
        effective_map = dict(effective)
        remaining = sorted(
            set(original) - set(seed.symbols) - set(dict(unresolved_normalized))
        )
        requests = tuple(
            _make_request(
                tuple(remaining[offset : offset + HK_HISTORY_MAX_BATCH_SYMBOLS]),
                original,
                effective=effective_map,
            )
            for offset in range(0, len(remaining), HK_HISTORY_MAX_BATCH_SYMBOLS)
        )
        journal_id = hashlib.sha256(
            _canonical_json(
                {
                    "schema_version": "hk-history-journal-identity-v2",
                    "seed": asdict(seed),
                    "evidence_set_sha256": evidence.evidence_set_sha256,
                    "requests": [request.request_id for request in requests],
                }
            ).encode()
        ).hexdigest()
        values: dict[str, Any] = {
            "schema_version": HK_HISTORY_SCHEMA_VERSION_V2,
            "strategy": HK_HISTORY_STRATEGY_V2,
            "as_of": as_of.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": as_of.isoformat(),
            "fields": HK_DAILY_FIELDS,
            "batch_size": HK_HISTORY_MAX_BATCH_SYMBOLS,
            "expected_dates": normalized,
            "seed": seed,
            "unresolved": unresolved_normalized,
            "requests": requests,
            "plan_sha256": "0" * 64,
            "no_trade_evidence": evidence.evidences,
            "no_trade_evidence_sha256": evidence.evidence_set_sha256,
            "effective_expected_dates": effective,
            "journal_id": journal_id,
        }
        payload = _serialize_plan_values(values)
        payload["plan_sha256"] = "0" * 64
        values["plan_sha256"] = hashlib.sha256(
            _canonical_json(payload).encode()
        ).hexdigest()
        result = HKHistoryPlan(**values)
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    return result


def write_or_verify_plan(path: Path, plan: HKHistoryPlan) -> None:
    """Create an immutable plan or verify the existing plan byte-for-byte."""
    payload = _canonical_json(_plan_dict(plan)).encode("utf-8")
    failure: str | None = None
    try:
        if path.exists():
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
            load_hk_history_plan(path)
            return
        _write_once(path, payload)
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_PLAN_CONFLICT"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def load_hk_history_plan(path: Path) -> HKHistoryPlan:
    """Load and strictly reconstruct an immutable plan."""
    result: HKHistoryPlan | None = None
    failure: str | None = None
    try:
        value = _strict_json(path.read_bytes())
        plan = _plan_from_dict(value)
        if path.read_bytes() != _canonical_json(_plan_dict(plan)).encode("utf-8"):
            raise ValueError
        result = plan
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_PLAN_CONFLICT"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None
    return result


def execute_next_hk_history_request(
    *,
    plan: HKHistoryPlan,
    connector: TushareConnector,
    raw_store: RawStore,
    journal_root: Path,
    seed_raw_root: Path,
    now: Callable[[], dt.datetime] | None = None,
    confirm_uncertain_retry: bool = False,
) -> HKHistoryExecutionResult:
    """Verify completed work and execute at most one new API request."""
    clock = now or (lambda: dt.datetime.now(dt.timezone.utc))
    _validate_plan_again(plan)
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_locked(
                plan=plan,
                connector=connector,
                raw_store=raw_store,
                journal_root=journal_root,
                seed_raw_root=seed_raw_root,
                now=clock,
                confirm_uncertain_retry=confirm_uncertain_retry,
            )
    except HKHistoryBackfillError:
        raise
    except M3JournalLockError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    except OSError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def recover_existing_hk_history_requests(
    *,
    plan: HKHistoryPlan,
    raw_store: RawStore,
    journal_root: Path,
    seed_raw_root: Path,
) -> HKHistoryExecutionResult:
    """Recover COMPLETE existing raw into a fresh v2 journal without a connector."""
    _validate_plan_again(plan)
    if plan.schema_version != HK_HISTORY_SCHEMA_VERSION_V2:
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
    result: HKHistoryExecutionResult | None = None
    failure: str | None = None
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
        with hold_journal_writer_lock(journal_root=journal_root):
            _load_seed(plan, seed_raw_root)
            _bind_v2_journal(plan, journal_root)
            completed = 0
            for request in plan.requests:
                verified = _verify_receipt(plan, request, raw_store, journal_root)
                if verified is not None:
                    completed += 1
                    continue
                state = _raw_state(raw_store, request)
                if state == "ABSENT":
                    raise HKHistoryBackfillError("HK_HISTORY_INCOMPLETE")
                if state != "COMPLETE":
                    raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID")
                frame = _read_and_validate_request(request, raw_store)
                _write_receipt(plan, request, raw_store, journal_root, frame)
                completed += 1
            result = HKHistoryExecutionResult(
                request_id=None,
                network_requests=0,
                completed_requests=completed,
                total_requests=len(plan.requests),
                is_complete=True,
            )
    except HKHistoryBackfillError as error:
        failure = str(error)
    except M3JournalLockError:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    return result


def finalize_hk_history(
    *,
    plan: HKHistoryPlan,
    raw_store: RawStore,
    journal_root: Path,
    seed_raw_root: Path,
    clean_root: Path,
    hkex_retained_raw: bytes | None = None,
    hkex_retained_bundle: VerifiedHKEXDailyQuotationRetainedBundle | None = None,
) -> int:
    """Publish all validated planned bars after a read-only conflict preflight."""
    _validate_plan_again(plan)
    if hkex_retained_raw is not None and hkex_retained_bundle is not None:
        raise HKHistoryBackfillError("HK_HISTORY_AVAILABILITY_INVALID") from None
    supplement_frame: pl.DataFrame | None
    supplement_receipt: dict[str, Any] | None
    v3_bundle: VerifiedHKEXDailyQuotationRetainedBundle | None = None
    if hkex_retained_bundle is not None:
        supplement_frame, supplement_receipt, v3_bundle = _prepare_hkex_supplement_v3(
            plan=plan, retained_bundle=hkex_retained_bundle
        )
    else:
        supplement_frame, supplement_receipt = _prepare_hkex_supplement(
            plan=plan, retained_raw=hkex_retained_raw
        )
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
        with hold_journal_writer_lock(journal_root=journal_root):
            seed_frame, seed_fetched_at = _load_seed(plan, seed_raw_root)
            _bind_v2_journal(plan, journal_root)
            frames = [seed_frame]
            request_frames: list[tuple[HKHistoryRequest, pl.DataFrame]] = []
            for request in plan.requests:
                receipt = _verify_receipt(plan, request, raw_store, journal_root)
                if receipt is None:
                    raise HKHistoryBackfillError("HK_HISTORY_INCOMPLETE")
                frames.append(receipt)
                request_frames.append((request, receipt))
            if supplement_frame is not None:
                frames.append(supplement_frame)
            clean = Bar1dSchema.validate(pl.concat(frames, how="vertical_relaxed")).sort(
                "symbol", "trade_date", "source"
            )
            expected_source = (
                plan.effective_expected_dates
                if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
                else plan.expected_dates
            )
            expected_keys = {
                (symbol, _date(date_value))
                for symbol, dates in expected_source
                for date_value in dates
            }
            actual_keys = set(clean.select("symbol", "trade_date").iter_rows())
            if actual_keys != expected_keys or clean.height != len(expected_keys):
                raise HKHistoryBackfillError(
                    "HK_HISTORY_AVAILABILITY_INVALID"
                    if v3_bundle is not None
                    else "HK_HISTORY_RAW_INVALID"
                )
            availability: pl.DataFrame | None = None
            if v3_bundle is not None:
                availability = _build_availability_evidence(
                    plan=plan,
                    seed_frame=seed_frame,
                    seed_fetched_at=seed_fetched_at,
                    request_frames=request_frames,
                    raw_store=raw_store,
                    journal_root=journal_root,
                    hkex_frame=supplement_frame,
                    hkex_bundle=v3_bundle,
                )
            _preflight_clean(clean, clean_root)
            try:
                written = CleanBarStore(clean_root).upsert(clean)
                _verify_published(clean, clean_root)
                if v3_bundle is None:
                    _write_finalize_receipt(
                        journal_root, plan, clean, hkex_supplement=supplement_receipt
                    )
                else:
                    if availability is None:
                        raise HKHistoryBackfillError(
                            "HK_HISTORY_AVAILABILITY_INVALID"
                        )
                    _write_finalize_v3(
                        root=journal_root,
                        plan=plan,
                        clean=clean,
                        availability=availability,
                        raw_store=raw_store,
                        hkex_bundle=v3_bundle,
                    )
                return written
            except HKHistoryBackfillError:
                raise
            except Exception:
                raise HKHistoryBackfillError("HK_HISTORY_PUBLISH_FAILED") from None
    except HKHistoryBackfillError:
        raise
    except M3JournalLockError:
        raise HKHistoryBackfillError("HK_HISTORY_PUBLISH_FAILED") from None
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def load_verified_hkex_retained_bundle_for_finalize(
    raw_path: Path,
    metadata_path: Path,
) -> VerifiedHKEXDailyQuotationRetainedBundle:
    """Read and freshly verify one explicit retained HKEX input pair.

    The retained inputs are trusted to have been published write-once/no-clobber,
    and the caller must keep them free of concurrent writers until downstream
    finalize has consumed the returned bundle.  Each file remains physically
    anchored through its final held-instance content and identity checks, and
    the returned bundle is derived only from the initially cached bytes.  These
    finite sequential checks do not prove that both external paths are immutable
    at one common instant.  The loader never creates or repairs retained metadata.
    """
    anchors: list[_DirectoryAnchor] = []
    result: VerifiedHKEXDailyQuotationRetainedBundle | None = None
    failed = False
    try:
        raw_absolute = raw_path.absolute()
        metadata_absolute = metadata_path.absolute()
        raw_anchor = _DirectoryAnchor(raw_absolute.parent)
        anchors.append(raw_anchor)
        metadata_anchor = _DirectoryAnchor(metadata_absolute.parent)
        anchors.append(metadata_anchor)

        raw_payload = raw_anchor.read_bytes(raw_absolute.name)
        raw_identity = _last_anchored_file_identity(raw_anchor)
        raw_content = (len(raw_payload), hashlib.sha256(raw_payload).digest())
        metadata_payload = metadata_anchor.read_bytes(metadata_absolute.name)
        metadata_identity = _last_anchored_file_identity(metadata_anchor)
        metadata_content = (
            len(metadata_payload),
            hashlib.sha256(metadata_payload).digest(),
        )
        if raw_identity == metadata_identity:
            raise _AnchorViolation

        result = verify_hkex_daily_quotation_retained(
            raw_payload,
            metadata_payload,
            source_url=HKEX_02983_SOURCE_URL,
            expected_raw_sha256=HKEX_02983_RAW_SHA256,
        )
        for anchor, path, expected_identity, expected_content in (
            (raw_anchor, raw_absolute, raw_identity, raw_content),
            (
                metadata_anchor,
                metadata_absolute,
                metadata_identity,
                metadata_content,
            ),
        ):
            anchor.assert_live()
            if _reread_held_file_content(anchor) != expected_content:
                raise _AnchorViolation
            anchor.assert_namespace()
            if _path_file_identity(path) != expected_identity:
                raise _AnchorViolation
    except Exception:
        failed = True
    finally:
        for anchor in reversed(anchors):
            try:
                anchor.close()
            except Exception:
                failed = True
    if failed or result is None:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    return result


def _last_anchored_file_identity(anchor: _DirectoryAnchor) -> tuple[int, int]:
    if os.name == "nt":
        if not anchor._held_handles:
            raise _AnchorViolation
        _handle, _duplicate, attributes, volume, index = anchor._held_handles[-1]
        if attributes & 0x00000400 or attributes & 0x00000010:
            raise _AnchorViolation
        return volume, index
    if not anchor._held_fds:
        raise _AnchorViolation
    _fd, _duplicate, device, inode, file_type, _flags = anchor._held_fds[-1]
    if file_type != stat.S_IFREG:
        raise _AnchorViolation
    return device, inode


def _reread_held_file_content(anchor: _DirectoryAnchor) -> tuple[int, bytes]:
    original_offset: int | None = None
    payload: bytes | None = None
    failed = False
    try:
        original_offset = _held_file_current_offset(anchor)
        _held_file_seek_start(anchor)
        payload = _held_file_read_all(anchor)
    except Exception:
        failed = True
    finally:
        if original_offset is not None:
            try:
                _held_file_restore_offset(anchor, original_offset)
            except Exception:
                failed = True
    if failed or payload is None:
        raise _AnchorViolation from None
    return len(payload), hashlib.sha256(payload).digest()


def _held_file_current_offset(anchor: _DirectoryAnchor) -> int:
    descriptor = _last_held_file_descriptor(anchor)
    if os.name == "nt":
        return _win_seek_file_handle(descriptor, 0, 1)
    return os.lseek(descriptor, 0, os.SEEK_CUR)


def _held_file_seek_start(anchor: _DirectoryAnchor) -> None:
    descriptor = _last_held_file_descriptor(anchor)
    observed = (
        _win_seek_file_handle(descriptor, 0, 0)
        if os.name == "nt"
        else os.lseek(descriptor, 0, os.SEEK_SET)
    )
    if observed != 0:
        raise _AnchorViolation


def _held_file_read_all(anchor: _DirectoryAnchor) -> bytes:
    descriptor = _last_held_file_descriptor(anchor)
    if os.name == "nt":
        return _win_read_file_handle(descriptor)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _held_file_restore_offset(anchor: _DirectoryAnchor, offset: int) -> None:
    descriptor = _last_held_file_descriptor(anchor)
    observed = (
        _win_seek_file_handle(descriptor, offset, 0)
        if os.name == "nt"
        else os.lseek(descriptor, offset, os.SEEK_SET)
    )
    if observed != offset:
        raise _AnchorViolation


def _last_held_file_descriptor(anchor: _DirectoryAnchor) -> int:
    if os.name == "nt":
        if not anchor._held_handles:
            raise _AnchorViolation
        return anchor._held_handles[-1][0]
    if not anchor._held_fds:
        raise _AnchorViolation
    return anchor._held_fds[-1][0]


def _path_file_identity(path: Path) -> tuple[int, int]:
    if os.name == "nt":
        handle = _win_create_handle(path, directory=False)
        try:
            attributes, volume, index = _win_file_information(handle)
            if attributes & 0x00000400 or attributes & 0x00000010:
                raise _AnchorViolation
            return volume, index
        finally:
            _win_close_handle(handle)
    fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _AnchorViolation
        return info.st_dev, info.st_ino
    finally:
        os.close(fd)


def _prepare_hkex_supplement(
    *, plan: HKHistoryPlan, retained_raw: bytes | None
) -> tuple[pl.DataFrame | None, dict[str, Any] | None]:
    """Freshly verify and map the one frozen HKEX supplement before any write."""
    if (
        plan.unresolved == _HKEX_SUPPLEMENT_UNRESOLVED
        and plan.schema_version != HK_HISTORY_SCHEMA_VERSION_V2
    ):
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
    if plan.unresolved != _HKEX_SUPPLEMENT_UNRESOLVED:
        if plan.unresolved or retained_raw is not None:
            raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
        return None, None
    if retained_raw is None:
        raise HKHistoryBackfillError("HK_HISTORY_INCOMPLETE")
    if type(retained_raw) is not bytes:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID")
    try:
        verified = verify_hkex_daily_quotation(
            retained_raw,
            source_url=HKEX_02983_SOURCE_URL,
            expected_raw_sha256=HKEX_02983_RAW_SHA256,
        )
        evidence = verified.evidence
        frame = Bar1dSchema.validate(
            pl.DataFrame(
                {
                    "symbol": [evidence.symbol],
                    "trade_date": [evidence.trade_date],
                    "open": [float(evidence.open)],
                    "high": [float(evidence.high)],
                    "low": [float(evidence.low)],
                    "close": [float(evidence.close)],
                    "volume": [float(evidence.sales_volume)],
                    "amount": [float(evidence.sales_turnover)],
                    "adj_factor": [1.0],
                    "source": ["hkex"],
                }
            )
        )
        if (
            frame.height != 1
            or frame.select("symbol", "trade_date").row(0)
            != ("02983.HK", dt.date(2026, 7, 10))
        ):
            raise ValueError
        receipt = {
            "evidence_id": verified.evidence_id,
            "raw_sha256": evidence.raw_sha256,
            "source_record_id": evidence.source_record_id,
            "supplement_content_sha256": _frame_hash(frame),
        }
        return frame, receipt
    except HKHistoryBackfillError:
        raise
    except HKEXDailyQuotationsError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def _prepare_hkex_supplement_v3(
    *,
    plan: HKHistoryPlan,
    retained_bundle: VerifiedHKEXDailyQuotationRetainedBundle,
) -> tuple[
    pl.DataFrame,
    dict[str, Any],
    VerifiedHKEXDailyQuotationRetainedBundle,
]:
    """Freshly reverify an exact retained bundle eligible for receipt v3."""
    if (
        plan.schema_version != HK_HISTORY_SCHEMA_VERSION_V2
        or plan.unresolved != _HKEX_SUPPLEMENT_UNRESOLVED
        or type(retained_bundle) is not VerifiedHKEXDailyQuotationRetainedBundle
    ):
        raise HKHistoryBackfillError("HK_HISTORY_AVAILABILITY_INVALID") from None
    try:
        rebuilt = verify_hkex_daily_quotation_retained_bundle(retained_bundle)
        evidence = rebuilt.quotation.evidence
        metadata = rebuilt.metadata
        if (
            metadata.report_trade_date != evidence.trade_date
            or metadata.market != "HK"
            or metadata.source_record_id != evidence.source_record_id
        ):
            raise ValueError
        frame = Bar1dSchema.validate(
            pl.DataFrame(
                {
                    "symbol": [evidence.symbol],
                    "trade_date": [evidence.trade_date],
                    "open": [float(evidence.open)],
                    "high": [float(evidence.high)],
                    "low": [float(evidence.low)],
                    "close": [float(evidence.close)],
                    "volume": [float(evidence.sales_volume)],
                    "amount": [float(evidence.sales_turnover)],
                    "adj_factor": [1.0],
                    "source": ["hkex"],
                }
            )
        )
        if frame.select("symbol", "trade_date").row(0) != (
            "02983.HK",
            dt.date(2026, 7, 10),
        ):
            raise ValueError
        receipt = {
            "evidence_id": rebuilt.quotation.evidence_id,
            "bundle_id": rebuilt.bundle_id,
            "raw_sha256": evidence.raw_sha256,
            "metadata_sha256": hashlib.sha256(rebuilt.retained_metadata).hexdigest(),
            "metadata_identity": metadata.metadata_identity,
            "source_record_id": evidence.source_record_id,
            "supplement_content_sha256": _frame_hash(frame),
        }
        return frame, receipt, rebuilt
    except HKHistoryBackfillError:
        raise
    except HKEXDailyQuotationsError:
        raise HKHistoryBackfillError("HK_HISTORY_AVAILABILITY_INVALID") from None
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_AVAILABILITY_INVALID") from None


def _execute_locked(
    *,
    plan: HKHistoryPlan,
    connector: TushareConnector,
    raw_store: RawStore,
    journal_root: Path,
    seed_raw_root: Path,
    now: Callable[[], dt.datetime],
    confirm_uncertain_retry: bool,
) -> HKHistoryExecutionResult:
    _, seed_time = _load_seed(plan, seed_raw_root)
    _bind_v2_journal(plan, journal_root)
    completed = 0
    pending: HKHistoryRequest | None = None
    pending_has_attempt = False
    for request in plan.requests:
        verified = _verify_receipt(plan, request, raw_store, journal_root)
        if verified is not None:
            completed += 1
            continue
        state = _raw_state(raw_store, request)
        if state == "COMPLETE":
            _verify_intent(journal_root, request)
            frame = _read_and_validate_request(request, raw_store)
            _write_receipt(plan, request, raw_store, journal_root, frame)
            completed += 1
            continue
        if state != "ABSENT":
            raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID")
        if pending is None:
            pending = request
            pending_has_attempt = _has_uncertain_attempt(
                journal_root, request.request_id
            )
    if pending is None:
        return HKHistoryExecutionResult(None, 0, completed, len(plan.requests), True)

    current = _utc(now())
    latest = max([seed_time, *_all_attempt_times(journal_root)], default=seed_time)
    if (current - latest).total_seconds() < HK_HISTORY_COOLDOWN_SECONDS:
        raise HKHistoryBackfillError("HK_HISTORY_COOLDOWN_ACTIVE")
    if pending_has_attempt and not confirm_uncertain_retry:
        raise HKHistoryBackfillError("HK_HISTORY_ATTEMPT_UNCERTAIN")

    request_dir = journal_root / "requests" / pending.request_id
    _guard_journal_path(journal_root, request_dir)
    intent = {
        "schema_version": "hk-history-intent-v1",
        "request_id": pending.request_id,
        "parameters": dict(pending.parameters),
    }
    _write_or_verify_json(request_dir / "intent.json", intent, "HK_HISTORY_PLAN_CONFLICT")
    attempt_id = current.strftime("%Y%m%dT%H%M%S.%fZ")
    attempt = {
        "schema_version": "hk-history-attempt-v1",
        "request_id": pending.request_id,
        "attempt_id": attempt_id,
        "started_at": current.isoformat(),
    }
    _write_once(
        request_dir / "attempts" / f"{attempt_id}.json",
        _canonical_json(attempt).encode("utf-8"),
    )
    try:
        raw = connector.fetch_hk_daily_batch_raw(
            symbols=pending.symbols,
            start=_date(dict(pending.parameters)["start_date"]),
            end=_date(dict(pending.parameters)["end_date"]),
            fields=HK_DAILY_FIELDS,
        )
    except Exception:
        failure = {
            "schema_version": "hk-history-failure-v1",
            "request_id": pending.request_id,
            "attempt_id": attempt_id,
            "code": "HK_HISTORY_API_FAILED",
        }
        _write_once(
            request_dir / "failures" / f"{attempt_id}.json",
            _canonical_json(failure).encode("utf-8"),
        )
        raise HKHistoryBackfillError("HK_HISTORY_API_FAILED") from None
    try:
        raw_store.write_request(
            source="tushare",
            table=HK_HISTORY_RAW_TABLE,
            request_id=pending.request_id,
            frame=raw,
            parameters=dict(pending.parameters),
            fetched_at=current,
        )
    except (OSError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    clean = _read_and_validate_request(pending, raw_store)
    _write_receipt(plan, pending, raw_store, journal_root, clean)
    return HKHistoryExecutionResult(
        pending.request_id, 1, completed + 1, len(plan.requests), completed + 1 == len(plan.requests)
    )


def _validate_raw(
    raw: pl.DataFrame,
    all_expected: Mapping[str, tuple[str, ...]],
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    result: pl.DataFrame | None = None
    failure: str | None = None
    try:
        if tuple(raw.columns) != _RAW_COLUMNS or raw.height >= HK_HISTORY_ROW_LIMIT:
            raise ValueError
        if raw.null_count().row(0) != (0,) * len(raw.columns):
            raise ValueError
        symbol_set = {symbol for symbol in symbols if all_expected[symbol]}
        observed_symbols = set(raw.get_column("ts_code").cast(pl.String).to_list())
        if observed_symbols != symbol_set:
            raise ValueError
        keys = raw.select("ts_code", "trade_date")
        if keys.unique().height != keys.height:
            raise ValueError
        for symbol in symbols:
            dates = tuple(
                sorted(
                    _date(value).isoformat()
                    for value in raw.filter(pl.col("ts_code") == symbol)
                    .get_column("trade_date")
                    .cast(pl.String)
                    .to_list()
                )
            )
            if dates != all_expected[symbol]:
                raise ValueError
        enriched = raw.with_columns(
            pl.col("ts_code").alias("_request_symbol"), pl.lit("HK").alias("_market")
        )
        result = Bar1dSchema.validate(TushareBarMapper().map(enriched))
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    return result


def _read_and_validate_request(
    request: HKHistoryRequest,
    raw_store: RawStore,
    *,
    raw_anchor: _DirectoryAnchor | None = None,
) -> pl.DataFrame:
    failure: str | None = None
    frame: pl.DataFrame | None = None
    try:
        _, frame = _verify_request_bundle_fresh(
            request=request, raw_store=raw_store, raw_anchor=raw_anchor
        )
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if frame is None:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    expected = (
        request.effective_expected_dates
        if request.effective_expected_dates
        else request.expected_dates
    )
    return _validate_raw(frame, dict(expected), request.symbols)


def _read_anchored_path(
    path: Path, *, root: Path, anchor: _DirectoryAnchor | None
) -> bytes:
    if anchor is None:
        return path.read_bytes()
    return anchor.read_bytes(path.relative_to(root))


def _verify_request_bundle_fresh(
    *,
    request: HKHistoryRequest,
    raw_store: RawStore,
    raw_anchor: _DirectoryAnchor | None,
) -> tuple[RequestRawSnapshot, pl.DataFrame]:
    if raw_anchor is None:
        return raw_store.verify_request_bundle(
            source="tushare",
            table=HK_HISTORY_RAW_TABLE,
            request_id=request.request_id,
            parameters=dict(request.parameters),
        )
    data_path, metadata_path = raw_store.request_paths(
        source="tushare",
        table=HK_HISTORY_RAW_TABLE,
        request_id=request.request_id,
    )
    payload = _read_anchored_path(data_path, root=raw_store.root, anchor=raw_anchor)
    metadata_payload = _read_anchored_path(
        metadata_path, root=raw_store.root, anchor=raw_anchor
    )
    metadata = _strict_json(metadata_payload)
    expected_keys = {
        "schema_version",
        "snapshot_id",
        "source",
        "table",
        "request_id",
        "fetched_at",
        "parameters",
        "rows",
        "columns",
        "checksum_sha256",
        "size_bytes",
    }
    if (
        set(metadata) != expected_keys
        or metadata_payload != _canonical_json(metadata).encode("utf-8")
        or metadata["schema_version"] != "request-raw-v1"
        or metadata["snapshot_id"] != request.request_id
        or metadata["request_id"] != request.request_id
        or metadata["source"] != "tushare"
        or metadata["table"] != HK_HISTORY_RAW_TABLE
        or metadata["parameters"] != dict(request.parameters)
        or type(metadata["rows"]) is not int
        or type(metadata["size_bytes"]) is not int
        or type(metadata["fetched_at"]) is not str
        or type(metadata["columns"]) is not list
        or not all(type(item) is str for item in metadata["columns"])
    ):
        raise ValueError
    fetched_at = dt.datetime.fromisoformat(metadata["fetched_at"])
    if fetched_at.tzinfo is None:
        raise ValueError
    checksum = hashlib.sha256(payload).hexdigest()
    if metadata["checksum_sha256"] != checksum or metadata["size_bytes"] != len(payload):
        raise ValueError
    frame = pl.read_parquet(io.BytesIO(payload))
    if frame.height != metadata["rows"] or frame.columns != metadata["columns"]:
        raise ValueError
    return (
        RequestRawSnapshot(
            snapshot_id=request.request_id,
            data_path=data_path,
            metadata_path=metadata_path,
            checksum_sha256=checksum,
            metadata_sha256=hashlib.sha256(metadata_payload).hexdigest(),
            size_bytes=len(payload),
            row_count=frame.height,
            columns=tuple(frame.columns),
        ),
        frame,
    )


def _verify_receipt(
    plan: HKHistoryPlan,
    request: HKHistoryRequest,
    raw_store: RawStore,
    journal_root: Path,
    *,
    journal_anchor: _DirectoryAnchor | None = None,
    raw_anchor: _DirectoryAnchor | None = None,
) -> pl.DataFrame | None:
    path = journal_root / "requests" / request.request_id / "receipt.json"
    _guard_journal_path(journal_root, path)
    if journal_anchor is None and not path.exists():
        return None
    result: pl.DataFrame | None = None
    failure: str | None = None
    try:
        if plan.schema_version == HK_HISTORY_SCHEMA_VERSION:
            _verify_intent(journal_root, request)
        frame = _read_and_validate_request(request, raw_store, raw_anchor=raw_anchor)
        payload = _read_anchored_path(
            path, root=journal_root, anchor=journal_anchor
        )
        value = _strict_json(payload)
        snapshot, _ = _verify_request_bundle_fresh(
            request=request, raw_store=raw_store, raw_anchor=raw_anchor
        )
        expected = _receipt_dict(plan, request, snapshot, frame)
        expected_payload = _canonical_json(expected).encode("utf-8")
        if value != _strict_json(expected_payload) or payload != expected_payload:
            raise ValueError
        result = frame
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    return result


def _write_receipt(
    plan: HKHistoryPlan,
    request: HKHistoryRequest,
    raw_store: RawStore,
    journal_root: Path,
    frame: pl.DataFrame,
) -> None:
    failure: str | None = None
    try:
        snapshot, _ = raw_store.verify_request_bundle(
            source="tushare",
            table=HK_HISTORY_RAW_TABLE,
            request_id=request.request_id,
            parameters=dict(request.parameters),
        )
        _write_or_verify_json(
            journal_root / "requests" / request.request_id / "receipt.json",
            _receipt_dict(plan, request, snapshot, frame),
            "HK_HISTORY_RAW_INVALID",
        )
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def _receipt_dict(
    plan: HKHistoryPlan,
    request: HKHistoryRequest,
    snapshot: RequestRawSnapshot,
    frame: pl.DataFrame,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": (
            "hk-history-receipt-v2"
            if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
            else "hk-history-receipt-v1"
        ),
        "status": "PASS",
        "request_id": request.request_id,
        "raw_file_sha256": snapshot.checksum_sha256,
        "raw_metadata_sha256": snapshot.metadata_sha256,
        "row_count": snapshot.row_count,
        "clean_content_sha256": _frame_hash(frame),
    }
    if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2:
        value.update(
            {
                "plan_sha256": plan.plan_sha256,
                "no_trade_evidence_sha256": plan.no_trade_evidence_sha256,
                "original_expected_dates": request.expected_dates,
                "effective_expected_dates": request.effective_expected_dates,
            }
        )
    return value


def _load_seed(
    plan: HKHistoryPlan,
    raw_root: Path,
    *,
    seed_anchor: _DirectoryAnchor | None = None,
) -> tuple[pl.DataFrame, dt.datetime]:
    if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2:
        failure: str | None = None
        try:
            _verify_evidence_projection(
                HKNoTradeEvidenceSet(
                    schema_version=HK_NO_TRADE_EVIDENCE_SET_VERSION,
                    evidences=plan.no_trade_evidence,
                    evidence_set_sha256=plan.no_trade_evidence_sha256,
                ),
                raw_root=raw_root,
                anchor=seed_anchor,
            )
        except HKHistoryBackfillError as error:
            failure = str(error)
        except (TypeError, ValueError):
            failure = "HK_HISTORY_REFERENCE_INVALID"
        if failure is not None:
            raise HKHistoryBackfillError(failure) from None
    base = raw_root.resolve()
    data_path = (base / PurePosixPath(plan.seed.selector)).resolve()
    result: tuple[pl.DataFrame, dt.datetime] | None = None
    failure = None
    try:
        data_path.relative_to(base)
        if data_path.suffix != ".parquet":
            raise ValueError
        metadata_path = data_path.with_suffix(".json")
        metadata_payload = _read_anchored_path(
            metadata_path, root=raw_root, anchor=seed_anchor
        )
        metadata = _strict_json(metadata_payload)
        payload = _read_anchored_path(data_path, root=raw_root, anchor=seed_anchor)
        payload_checksum = hashlib.sha256(payload).hexdigest()
        if (
            payload_checksum != metadata["checksum_sha256"]
            or payload_checksum != plan.seed.checksum_sha256
            or hashlib.sha256(metadata_payload).hexdigest()
            != plan.seed.metadata_sha256
        ):
            raise ValueError
        raw = pl.read_parquet(io.BytesIO(payload))
        if metadata["rows"] != raw.height or metadata["columns"] != raw.columns:
            raise ValueError
        fetched_at = _utc(dt.datetime.fromisoformat(metadata["fetched_at"]))
        expected_source = (
            plan.effective_expected_dates
            if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
            else plan.expected_dates
        )
        clean = _validate_seed_raw(raw, dict(expected_source), plan.seed.symbols)
        result = (clean, fetched_at)
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    return result


def _validate_seed_raw(
    raw: pl.DataFrame,
    all_expected: Mapping[str, tuple[str, ...]],
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    """Accept the frozen P1 enrichment without relaxing request-raw columns."""
    if tuple(raw.columns) == _RAW_COLUMNS:
        return _validate_raw(raw, all_expected, symbols)
    if tuple(raw.columns) != (*_RAW_COLUMNS, "_request_symbol", "_market"):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID")
    failure: str | None = None
    result: pl.DataFrame | None = None
    try:
        if raw.filter(
            (pl.col("_request_symbol") != pl.col("ts_code"))
            | (pl.col("_market") != "HK")
        ).height:
            raise ValueError
        result = _validate_raw(raw.select(_RAW_COLUMNS), all_expected, symbols)
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    return result


def _preflight_clean(incoming: pl.DataFrame, root: Path) -> None:
    for trade_date in incoming.get_column("trade_date").unique().sort().to_list():
        target = root / f"date={trade_date.isoformat()}" / "data.parquet"
        if not target.exists():
            continue
        try:
            existing = Bar1dSchema.validate(pl.read_parquet(target))
            part = incoming.filter(pl.col("trade_date") == trade_date)
            overlapping = existing.join(part.select(CleanBarStore.key), on=CleanBarStore.key)
            if overlapping.height:
                expected = part.join(overlapping.select(CleanBarStore.key), on=CleanBarStore.key)
                if _frame_hash(overlapping.sort(CleanBarStore.key)) != _frame_hash(
                    expected.sort(CleanBarStore.key)
                ):
                    raise HKHistoryBackfillError("HK_HISTORY_PUBLISH_CONFLICT")
        except HKHistoryBackfillError:
            raise
        except Exception:
            raise HKHistoryBackfillError("HK_HISTORY_PUBLISH_CONFLICT") from None


def _verify_published(incoming: pl.DataFrame, root: Path) -> None:
    rows: list[pl.DataFrame] = []
    for trade_date in incoming.get_column("trade_date").unique().sort().to_list():
        target = root / f"date={trade_date.isoformat()}" / "data.parquet"
        existing = Bar1dSchema.validate(pl.read_parquet(target))
        rows.append(existing.join(incoming.select(CleanBarStore.key), on=CleanBarStore.key))
    observed = pl.concat(rows, how="vertical_relaxed").sort(CleanBarStore.key)
    if _frame_hash(observed) != _frame_hash(incoming.sort(CleanBarStore.key)):
        raise HKHistoryBackfillError("HK_HISTORY_PUBLISH_FAILED")


def _write_finalize_receipt(
    root: Path,
    plan: HKHistoryPlan,
    clean: pl.DataFrame,
    *,
    hkex_supplement: dict[str, Any] | None,
) -> None:
    value: dict[str, Any] = {
        "schema_version": (
            "hk-history-finalize-v2"
            if hkex_supplement is not None
            else "hk-history-finalize-v1"
        ),
        "plan_sha256": plan.plan_sha256,
        "row_count": clean.height,
        "clean_content_sha256": _frame_hash(clean),
    }
    if hkex_supplement is not None:
        value["hkex_supplement"] = hkex_supplement
    path = root / "finalize.json"
    _guard_journal_path(root, path)
    _write_or_verify_json(path, value, "HK_HISTORY_PUBLISH_FAILED")


def _availability_row(
    *,
    symbol: str,
    trade_date: dt.date,
    source: str,
    kind: str,
    available_at: dt.datetime,
    source_record_id: str,
    request_id: str | None,
    raw_file_sha256: str,
    raw_metadata_sha256: str,
    request_receipt_sha256: str | None,
    plan_sha256: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "source": source,
        "availability_source_kind": kind,
        "bar_available_at": _utc(available_at).isoformat(),
        "source_record_id": source_record_id,
        "request_id": request_id,
        "raw_file_sha256": raw_file_sha256,
        "raw_metadata_sha256": raw_metadata_sha256,
        "request_receipt_sha256": request_receipt_sha256,
        "plan_sha256": plan_sha256,
    }
    value["availability_evidence_sha256"] = hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()
    return value


def _metadata_fetched_at(
    path: Path,
    expected_sha256: str,
    *,
    root: Path | None = None,
    anchor: _DirectoryAnchor | None = None,
) -> dt.datetime:
    payload = (
        path.read_bytes()
        if anchor is None or root is None
        else _read_anchored_path(path, root=root, anchor=anchor)
    )
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError
    value = _strict_json(payload)
    if type(value.get("fetched_at")) is not str:
        raise ValueError
    return _utc(dt.datetime.fromisoformat(value["fetched_at"]))


def _build_availability_evidence(
    *,
    plan: HKHistoryPlan,
    seed_frame: pl.DataFrame,
    seed_fetched_at: dt.datetime,
    request_frames: Sequence[tuple[HKHistoryRequest, pl.DataFrame]],
    raw_store: RawStore,
    journal_root: Path,
    hkex_frame: pl.DataFrame | None,
    hkex_bundle: VerifiedHKEXDailyQuotationRetainedBundle,
    anchors: _ReadAnchors | None = None,
) -> pl.DataFrame:
    """Build the exact one-source-per-effective-key retained observation table."""
    try:
        rows: list[dict[str, Any]] = []
        for row in seed_frame.iter_rows(named=True):
            rows.append(
                _availability_row(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    source=row["source"],
                    kind="SEED_RAW",
                    available_at=seed_fetched_at,
                    source_record_id=plan.seed.selector,
                    request_id=None,
                    raw_file_sha256=plan.seed.checksum_sha256,
                    raw_metadata_sha256=plan.seed.metadata_sha256,
                    request_receipt_sha256=None,
                    plan_sha256=plan.plan_sha256,
                )
            )
        for request, frame in request_frames:
            snapshot, _ = _verify_request_bundle_fresh(
                request=request,
                raw_store=raw_store,
                raw_anchor=None if anchors is None else anchors.raw,
            )
            fetched_at = _metadata_fetched_at(
                snapshot.metadata_path,
                snapshot.metadata_sha256,
                root=raw_store.root,
                anchor=None if anchors is None else anchors.raw,
            )
            receipt_path = (
                journal_root / "requests" / request.request_id / "receipt.json"
            )
            _guard_journal_path(journal_root, receipt_path)
            receipt_payload = _read_anchored_path(
                receipt_path,
                root=journal_root,
                anchor=None if anchors is None else anchors.journal,
            )
            if receipt_payload != _canonical_json(
                _receipt_dict(plan, request, snapshot, frame)
            ).encode("utf-8"):
                raise ValueError
            receipt_sha256 = hashlib.sha256(receipt_payload).hexdigest()
            for row in frame.iter_rows(named=True):
                rows.append(
                    _availability_row(
                        symbol=row["symbol"],
                        trade_date=row["trade_date"],
                        source=row["source"],
                        kind="REQUEST_RAW",
                        available_at=fetched_at,
                        source_record_id=request.request_id,
                        request_id=request.request_id,
                        raw_file_sha256=snapshot.checksum_sha256,
                        raw_metadata_sha256=snapshot.metadata_sha256,
                        request_receipt_sha256=receipt_sha256,
                        plan_sha256=plan.plan_sha256,
                    )
                )
        if hkex_frame is None:
            raise ValueError
        metadata = hkex_bundle.metadata
        for row in hkex_frame.iter_rows(named=True):
            rows.append(
                _availability_row(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    source=row["source"],
                    kind="HKEX_SUPPLEMENT",
                    available_at=metadata.source_observed_at,
                    source_record_id=metadata.source_record_id,
                    request_id=None,
                    raw_file_sha256=metadata.raw_file_sha256,
                    raw_metadata_sha256=hashlib.sha256(
                        hkex_bundle.retained_metadata
                    ).hexdigest(),
                    request_receipt_sha256=None,
                    plan_sha256=plan.plan_sha256,
                )
            )
        expected = {
            (symbol, _date(date_value))
            for symbol, dates in plan.effective_expected_dates
            for date_value in dates
        }
        keys = [(row["symbol"], _date(row["trade_date"])) for row in rows]
        if set(keys) != expected or len(keys) != len(expected):
            raise ValueError
        rows.sort(key=lambda item: (item["symbol"], item["trade_date"]))
        frame = pl.DataFrame(rows).with_columns(
            pl.col("trade_date").str.to_date(),
            pl.col("bar_available_at").str.to_datetime(time_zone="UTC"),
        )
        validated = HkBarAvailabilityEvidenceSchema.validate(frame)
        for row in validated.iter_rows(named=True):
            serialized = {
                key: (_scalar(value) if key != "availability_evidence_sha256" else value)
                for key, value in row.items()
                if key != "availability_evidence_sha256"
            }
            if row["availability_evidence_sha256"] != hashlib.sha256(
                _canonical_json(serialized).encode("utf-8")
            ).hexdigest():
                raise ValueError
        return validated.sort("symbol", "trade_date")
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_AVAILABILITY_INVALID") from None


def _availability_payload(plan: HKHistoryPlan, frame: pl.DataFrame) -> dict[str, Any]:
    rows = [
        {key: _scalar(value) for key, value in row.items()}
        for row in frame.sort("symbol", "trade_date").iter_rows(named=True)
    ]
    return {
        "schema_version": "hk-bar-availability-v1",
        "plan_sha256": plan.plan_sha256,
        "availability_content_sha256": hashlib.sha256(
            _canonical_json(rows).encode("utf-8")
        ).hexdigest(),
        "rows": rows,
    }


def _request_source_receipts(
    plan: HKHistoryPlan,
    raw_store: RawStore,
    root: Path,
    *,
    anchors: _ReadAnchors | None = None,
) -> list[dict[str, str]]:
    values = []
    for request in plan.requests:
        path = root / "requests" / request.request_id / "receipt.json"
        _guard_journal_path(root, path)
        payload = _read_anchored_path(
            path,
            root=root,
            anchor=None if anchors is None else anchors.journal,
        )
        snapshot, frame = _verify_request_bundle_fresh(
            request=request,
            raw_store=raw_store,
            raw_anchor=None if anchors is None else anchors.raw,
        )
        clean = _validate_raw(
            frame,
            dict(request.effective_expected_dates or request.expected_dates),
            request.symbols,
        )
        if payload != _canonical_json(
            _receipt_dict(plan, request, snapshot, clean)
        ).encode("utf-8"):
            raise ValueError
        values.append(
            {
                "request_id": request.request_id,
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return values


def _write_finalize_v3(
    *,
    root: Path,
    plan: HKHistoryPlan,
    clean: pl.DataFrame,
    availability: pl.DataFrame,
    raw_store: RawStore,
    hkex_bundle: VerifiedHKEXDailyQuotationRetainedBundle,
) -> None:
    """Publish the retained HKEX closure, availability and finalize atomically."""
    try:
        availability_value = _availability_payload(plan, availability)
        availability_bytes = _canonical_json(availability_value).encode("utf-8")
        metadata_sha256 = hashlib.sha256(
            hkex_bundle.retained_metadata
        ).hexdigest()
        finalize_value = {
            "schema_version": "hk-history-finalize-v3",
            "plan_sha256": plan.plan_sha256,
            "row_count": clean.height,
            "clean_content_sha256": _frame_hash(clean),
            "availability_content_sha256": availability_value[
                "availability_content_sha256"
            ],
            "availability_file_sha256": hashlib.sha256(availability_bytes).hexdigest(),
            "source_receipts": {
                "seed": {
                    "source_record_id": plan.seed.selector,
                    "raw_file_sha256": plan.seed.checksum_sha256,
                    "raw_metadata_sha256": plan.seed.metadata_sha256,
                },
                "requests": _request_source_receipts(plan, raw_store, root),
                "hkex": {
                    "bundle_id": hkex_bundle.bundle_id,
                    "quotation_evidence_id": hkex_bundle.quotation.evidence_id,
                    "metadata_identity": hkex_bundle.metadata.metadata_identity,
                    "raw_file": _HKEX_RETAINED_RAW_FILE,
                    "raw_file_sha256": hashlib.sha256(
                        hkex_bundle.retained_raw
                    ).hexdigest(),
                    "metadata_file": _HKEX_RETAINED_METADATA_FILE,
                    "raw_metadata_sha256": metadata_sha256,
                    "source_record_id": hkex_bundle.metadata.source_record_id,
                },
            },
        }
        files = {
            _HKEX_RETAINED_RAW_FILE: hkex_bundle.retained_raw,
            _HKEX_RETAINED_METADATA_FILE: hkex_bundle.retained_metadata,
            _AVAILABILITY_FILE: availability_bytes,
            "finalize.json": _canonical_json(finalize_value).encode("utf-8"),
        }
        _write_v3_file_set(root, files)
    except HKHistoryBackfillError:
        raise
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_FINALIZE_V3_INVALID") from None


def _write_v3_file_set(root: Path, files: Mapping[str, bytes]) -> None:
    paths = {name: root / name for name in files}
    for path in paths.values():
        _guard_journal_path(root, path)
    existing = {name for name, path in paths.items() if path.exists()}
    if existing:
        if existing != set(files) or any(
            paths[name].read_bytes() != payload for name, payload in files.items()
        ):
            raise HKHistoryBackfillError("HK_HISTORY_FINALIZE_V3_INVALID") from None
        return
    created: list[Path] = []
    try:
        for name, payload in files.items():
            if _write_v3_one(paths[name], payload):
                created.append(paths[name])
    except Exception:
        rollback_failed = False
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                rollback_failed = True
        if rollback_failed:
            raise HKHistoryBackfillError("HK_HISTORY_FINALIZE_V3_INVALID") from None
        raise HKHistoryBackfillError("HK_HISTORY_FINALIZE_V3_INVALID") from None


def _write_v3_one(path: Path, payload: bytes) -> bool:
    """Hard-link one no-clobber file and report whether this caller created it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.v3.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError(
                    "HK_HISTORY_FINALIZE_V3_INVALID"
                ) from None
            return False
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _root_identity(path: Path) -> tuple[str, int, int]:
    try:
        absolute = path.absolute()
        resolved = path.resolve(strict=True)
        mode = os.lstat(path)
        attributes = getattr(mode, "st_file_attributes", 0)
        if (
            resolved != absolute
            or stat.S_ISLNK(mode.st_mode)
            or not stat.S_ISDIR(mode.st_mode)
            or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError
        return str(resolved), mode.st_dev, mode.st_ino
    except Exception:
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None


class _AnchorViolation(RuntimeError):
    pass


class _DirectoryAnchor:
    """Physical directory object held for one complete verification window."""

    __slots__ = (
        "path",
        "identity",
        "_fd",
        "_fd_duplicate",
        "_fd_status_flags",
        "_handle",
        "_handle_duplicate",
        "_held_fds",
        "_held_handles",
        "_closed",
    )

    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._fd: int | None = None
        self._fd_duplicate: int | None = None
        self._fd_status_flags: int | None = None
        self._handle: int | None = None
        self._handle_duplicate: int | None = None
        self._held_fds: list[tuple[int, int, int, int, int, int]] = []
        self._held_handles: list[tuple[int, int, int, int, int]] = []
        self._closed = False
        if os.name == "nt":
            handle, identity = _win_open_directory(self.path)
            try:
                duplicate = _win_duplicate_handle(handle)
            except Exception:
                _win_close_handle(handle)
                raise
            self._handle, self._handle_duplicate = handle, duplicate
            self.identity = identity
        else:
            flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW
            fd = os.open(self.path, flags)
            try:
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError
                resolved = self.path.resolve(strict=True)
                duplicate, status_flags = _posix_duplicate_fd(fd)
            except Exception:
                os.close(fd)
                raise
            self._fd, self._fd_duplicate = fd, duplicate
            self._fd_status_flags = status_flags
            self.identity = (str(resolved), info.st_dev, info.st_ino)

    def read_bytes(self, relative: str | Path) -> bytes:
        self.assert_namespace()
        parts = _safe_anchor_parts(relative)
        if os.name == "nt":
            if self._handle is None:
                raise ValueError
            payload, held = _win_read_anchored(self.path, parts)
            self._held_handles.extend(held)
            self.assert_namespace()
            return payload
        if self._fd is None:
            raise ValueError
        directory_fd = self._fd
        opened: list[tuple[int, int, int, int, int, int]] = []
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    info = os.fstat(next_fd)
                    duplicate, status_flags = _posix_duplicate_fd(next_fd)
                except Exception:
                    os.close(next_fd)
                    raise
                opened.append((
                    next_fd,
                    duplicate,
                    info.st_dev,
                    info.st_ino,
                    stat.S_IFMT(info.st_mode),
                    status_flags,
                ))
                directory_fd = next_fd
            file_fd = os.open(
                parts[-1], os.O_RDONLY | _O_NOFOLLOW, dir_fd=directory_fd
            )
            try:
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError
                duplicate, status_flags = _posix_duplicate_fd(file_fd)
            except Exception:
                os.close(file_fd)
                raise
            opened.append((
                file_fd,
                duplicate,
                info.st_dev,
                info.st_ino,
                stat.S_IFMT(info.st_mode),
                status_flags,
            ))
            chunks = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            payload = b"".join(chunks)
            self._held_fds.extend(opened)
            opened = []
            self.assert_namespace()
            return payload
        finally:
            for fd, duplicate, *_identity in reversed(opened):
                os.close(duplicate)
                os.close(fd)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failure: Exception | None = None
        for fd, duplicate, *_identity in reversed(self._held_fds):
            for descriptor in (duplicate, fd):
                try:
                    os.close(descriptor)
                except Exception as error:
                    failure = failure or error
        self._held_fds.clear()
        for handle, duplicate, *_identity in reversed(self._held_handles):
            for descriptor in (duplicate, handle):
                try:
                    _win_close_handle(descriptor)
                except Exception as error:
                    failure = failure or error
        self._held_handles.clear()
        if self._fd_duplicate is not None:
            try:
                os.close(self._fd_duplicate)
            except Exception as error:
                failure = failure or error
            self._fd_duplicate = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception as error:
                failure = failure or error
            self._fd = None
        self._fd_status_flags = None
        if self._handle_duplicate is not None:
            try:
                _win_close_handle(self._handle_duplicate)
            except Exception as error:
                failure = failure or error
            self._handle_duplicate = None
        if self._handle is not None:
            try:
                _win_close_handle(self._handle)
            except Exception as error:
                failure = failure or error
            self._handle = None
        if failure is not None:
            raise failure

    def assert_live(self) -> None:
        if self._closed:
            raise _AnchorViolation
        if os.name == "nt":
            if self._handle is None or self._handle_duplicate is None:
                raise _AnchorViolation
            attributes, volume, index = _win_file_information(self._handle)
            duplicate_identity = _win_file_information(self._handle_duplicate)
            if (
                attributes & 0x00000400
                or not attributes & 0x00000010
                or (volume, index) != self.identity[1:]
                or duplicate_identity != (attributes, volume, index)
                or not _win_same_object_handle(
                    self._handle, self._handle_duplicate
                )
            ):
                raise _AnchorViolation
            for handle, duplicate, expected_attributes, expected_volume, expected_index in (
                self._held_handles
            ):
                observed = _win_file_information(handle)
                duplicate_identity = _win_file_information(duplicate)
                if observed != (
                    expected_attributes,
                    expected_volume,
                    expected_index,
                ) or duplicate_identity != observed or not _win_same_object_handle(
                    handle, duplicate
                ):
                    raise _AnchorViolation
        else:
            if (
                self._fd is None
                or self._fd_duplicate is None
                or self._fd_status_flags is None
            ):
                raise _AnchorViolation
            info = os.fstat(self._fd)
            duplicate_info = os.fstat(self._fd_duplicate)
            if (
                not stat.S_ISDIR(info.st_mode)
                or (info.st_dev, info.st_ino) != self.identity[1:]
                or (
                    duplicate_info.st_dev,
                    duplicate_info.st_ino,
                    stat.S_IFMT(duplicate_info.st_mode),
                )
                != (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
            ):
                raise _AnchorViolation
            _posix_assert_same_open_instance(
                self._fd, self._fd_duplicate, self._fd_status_flags
            )
            for (
                fd,
                duplicate,
                expected_dev,
                expected_ino,
                expected_type,
                expected_flags,
            ) in self._held_fds:
                observed_stat = os.fstat(fd)
                duplicate_stat = os.fstat(duplicate)
                if (
                    observed_stat.st_dev,
                    observed_stat.st_ino,
                    stat.S_IFMT(observed_stat.st_mode),
                ) != (expected_dev, expected_ino, expected_type) or (
                    duplicate_stat.st_dev,
                    duplicate_stat.st_ino,
                    stat.S_IFMT(duplicate_stat.st_mode),
                ) != (expected_dev, expected_ino, expected_type):
                    raise _AnchorViolation
                _posix_assert_same_open_instance(fd, duplicate, expected_flags)

    def assert_namespace(self) -> None:
        self.assert_live()
        self._assert_path_namespace()

    def _assert_path_namespace(self) -> None:
        if os.name == "nt":
            handle, identity = _win_open_directory(self.path)
            _win_close_handle(handle)
        else:
            identity = _root_identity(self.path)
        if identity != self.identity:
            raise _AnchorViolation


class _ReadAnchors:
    __slots__ = ("journal", "seed", "raw", "clean", "_closed")

    def __init__(
        self, *, journal: Path, seed: Path, raw: Path, clean: Path
    ) -> None:
        self._closed = False
        opened: list[_DirectoryAnchor] = []
        try:
            self.journal = _DirectoryAnchor(journal)
            opened.append(self.journal)
            self.seed = _DirectoryAnchor(seed)
            opened.append(self.seed)
            self.raw = _DirectoryAnchor(raw)
            opened.append(self.raw)
            self.clean = _DirectoryAnchor(clean)
            opened.append(self.clean)
        except Exception:
            for anchor in reversed(opened):
                anchor.close()
            raise

    @property
    def identities(self) -> tuple[tuple[str, int, int], ...]:
        return (
            self.journal.identity,
            self.seed.identity,
            self.raw.identity,
            self.clean.identity,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failure: Exception | None = None
        for anchor in (self.clean, self.raw, self.seed, self.journal):
            try:
                anchor.close()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure

    def assert_namespaces(self) -> None:
        if self._closed:
            raise _AnchorViolation
        anchors = (self.journal, self.seed, self.raw, self.clean)
        for anchor in anchors:
            anchor.assert_live()
        for anchor in anchors:
            anchor._assert_path_namespace()


def _safe_anchor_parts(relative: str | Path) -> tuple[str, ...]:
    value = Path(relative)
    if value.is_absolute() or not value.parts or any(
        part in {"", ".", ".."} for part in value.parts
    ):
        raise ValueError
    return tuple(value.parts)


def _posix_duplicate_fd(fd: int) -> tuple[int, int]:
    import importlib

    fcntl = importlib.import_module("fcntl")
    duplicate = int(fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0))
    try:
        status_flags = int(fcntl.fcntl(fd, fcntl.F_GETFL))
        if int(fcntl.fcntl(duplicate, fcntl.F_GETFL)) != status_flags:
            raise _AnchorViolation
        return duplicate, status_flags
    except Exception:
        os.close(duplicate)
        raise


def _posix_assert_same_open_instance(
    fd: int, duplicate: int, expected_flags: int
) -> None:
    import importlib

    fcntl = importlib.import_module("fcntl")
    toggle = int(getattr(os, "O_NONBLOCK", 0))
    if not toggle:
        raise _AnchorViolation
    restore_required = False
    failed = False
    try:
        original_flags = int(fcntl.fcntl(fd, fcntl.F_GETFL))
        duplicate_flags = int(fcntl.fcntl(duplicate, fcntl.F_GETFL))
        if original_flags != expected_flags or duplicate_flags != expected_flags:
            raise _AnchorViolation
        toggled_flags = expected_flags ^ toggle
        fcntl.fcntl(fd, fcntl.F_SETFL, toggled_flags)
        restore_required = True
        observed_original = int(fcntl.fcntl(fd, fcntl.F_GETFL))
        observed_duplicate = int(fcntl.fcntl(duplicate, fcntl.F_GETFL))
        if (
            observed_original & toggle != toggled_flags & toggle
            or observed_duplicate & toggle != toggled_flags & toggle
            or observed_original & ~toggle != expected_flags & ~toggle
            or observed_duplicate & ~toggle != expected_flags & ~toggle
        ):
            failed = True
    except Exception:
        failed = True
    finally:
        if restore_required:
            try:
                fcntl.fcntl(fd, fcntl.F_SETFL, expected_flags)
            except Exception:
                failed = True
        try:
            if (
                int(fcntl.fcntl(fd, fcntl.F_GETFL)) != expected_flags
                or int(fcntl.fcntl(duplicate, fcntl.F_GETFL)) != expected_flags
            ):
                failed = True
        except Exception:
            failed = True
    if failed:
        raise _AnchorViolation from None


def _win_file_information(handle: int) -> tuple[int, int, int]:
    import ctypes
    from ctypes import wintypes

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    info = FileInformation()
    kernel32 = getattr(ctypes, "windll").kernel32
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    get_info.restype = wintypes.BOOL
    if not get_info(wintypes.HANDLE(handle), ctypes.byref(info)):
        raise OSError
    file_index = (int(info.file_index_high) << 32) | int(info.file_index_low)
    return int(info.attributes), int(info.volume_serial), file_index


def _win_duplicate_handle(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "windll").kernel32
    current_process = kernel32.GetCurrentProcess
    current_process.argtypes = []
    current_process.restype = wintypes.HANDLE
    duplicate_handle = kernel32.DuplicateHandle
    duplicate_handle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    duplicate_handle.restype = wintypes.BOOL
    process = current_process()
    duplicate = wintypes.HANDLE()
    if not duplicate_handle(
        process,
        wintypes.HANDLE(handle),
        process,
        ctypes.byref(duplicate),
        0,
        False,
        0x00000002,
    ):
        raise OSError
    if duplicate.value is None:
        raise OSError
    return int(duplicate.value)


def _win_same_object_handle(handle: int, duplicate: int) -> bool:
    import ctypes
    from ctypes import wintypes

    try:
        kernelbase = getattr(ctypes, "WinDLL")(
            "KernelBase.dll", use_last_error=True
        )
        compare = kernelbase.CompareObjectHandles
    except Exception:
        raise _AnchorViolation from None
    compare.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    compare.restype = wintypes.BOOL
    try:
        return bool(compare(wintypes.HANDLE(handle), wintypes.HANDLE(duplicate)))
    except Exception:
        raise _AnchorViolation from None


def _win_create_handle(path: Path, *, directory: bool) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "windll").kernel32
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    # OPEN_REPARSE_POINT is 0x00200000; BACKUP_SEMANTICS is 0x02000000.
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = create(
        str(path),
        0x80000000,
        0x00000001 | 0x00000002,
        None,
        3,
        flags,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        raise OSError
    return int(handle)


def _win_open_directory(path: Path) -> tuple[int, tuple[str, int, int]]:
    handle = _win_create_handle(path, directory=True)
    try:
        attributes, volume, index = _win_file_information(handle)
        if attributes & 0x00000400 or not attributes & 0x00000010:
            raise ValueError
        resolved = path.resolve(strict=True)
        if resolved != path:
            raise ValueError
        return handle, (str(resolved), volume, index)
    except Exception:
        _win_close_handle(handle)
        raise


def _win_close_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    close_handle = getattr(ctypes, "windll").kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(wintypes.HANDLE(handle)):
        raise OSError


def _win_read_anchored(
    root: Path, parts: tuple[str, ...]
) -> tuple[bytes, list[tuple[int, int, int, int, int]]]:
    records: list[tuple[int, int, int, int, int]] = []
    try:
        cursor = root
        for part in parts[:-1]:
            cursor /= part
            handle = _win_create_handle(cursor, directory=True)
            try:
                attributes, volume, index = _win_file_information(handle)
                if attributes & 0x00000400 or not attributes & 0x00000010:
                    raise ValueError
                duplicate = _win_duplicate_handle(handle)
            except Exception:
                _win_close_handle(handle)
                raise
            records.append((handle, duplicate, attributes, volume, index))
        file_handle = _win_create_handle(cursor / parts[-1], directory=False)
        try:
            attributes, volume, index = _win_file_information(file_handle)
            if attributes & 0x00000400 or attributes & 0x00000010:
                raise ValueError
            duplicate = _win_duplicate_handle(file_handle)
        except Exception:
            _win_close_handle(file_handle)
            raise
        records.append((file_handle, duplicate, attributes, volume, index))
        payload = _win_read_file_handle(file_handle)
        held = records
        records = []
        return payload, held
    finally:
        for handle, duplicate, *_identity in reversed(records):
            _win_close_handle(duplicate)
            _win_close_handle(handle)


def _win_read_file_handle(handle: int) -> bytes:
    import ctypes
    from ctypes import wintypes

    read_file = getattr(ctypes, "windll").kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL
    chunks: list[bytes] = []
    while True:
        buffer = ctypes.create_string_buffer(1024 * 1024)
        read = wintypes.DWORD()
        if not read_file(
            wintypes.HANDLE(handle), buffer, len(buffer), ctypes.byref(read), None
        ):
            raise OSError
        if read.value == 0:
            return b"".join(chunks)
        chunks.append(buffer.raw[: read.value])


def _win_seek_file_handle(handle: int, offset: int, method: int) -> int:
    import ctypes
    from ctypes import wintypes

    set_pointer = getattr(ctypes, "windll").kernel32.SetFilePointerEx
    set_pointer.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    set_pointer.restype = wintypes.BOOL
    observed = ctypes.c_longlong()
    if not set_pointer(
        wintypes.HANDLE(handle),
        ctypes.c_longlong(offset),
        ctypes.byref(observed),
        method,
    ):
        raise OSError
    return int(observed.value)


def _verify_journal_binding(
    plan: HKHistoryPlan, root: Path, *, anchor: _DirectoryAnchor | None = None
) -> None:
    marker = root / "binding.json"
    _guard_journal_path(root, marker)
    expected = {
        "schema_version": "hk-history-journal-binding-v2",
        "journal_id": plan.journal_id,
        "plan_sha256": plan.plan_sha256,
        "no_trade_evidence_sha256": plan.no_trade_evidence_sha256,
    }
    payload = _read_anchored_path(marker, root=root, anchor=anchor)
    if payload != _canonical_json(expected).encode("utf-8"):
        raise HKHistoryBackfillError("HK_HISTORY_FINALIZE_V3_INVALID") from None


def _read_published_exact(
    plan: HKHistoryPlan,
    clean_root: Path,
    *,
    anchor: _DirectoryAnchor | None = None,
) -> pl.DataFrame:
    rows: list[pl.DataFrame] = []
    expected = {
        (symbol, _date(value))
        for symbol, dates in plan.effective_expected_dates
        for value in dates
    }
    for trade_date in sorted({item[1] for item in expected}):
        target = clean_root / f"date={trade_date.isoformat()}" / "data.parquet"
        _guard_journal_path(clean_root, target)
        payload = _read_anchored_path(target, root=clean_root, anchor=anchor)
        part = Bar1dSchema.validate(pl.read_parquet(io.BytesIO(payload))).filter(
            pl.col("trade_date") == trade_date
        )
        symbols = [symbol for symbol, date_value in expected if date_value == trade_date]
        selected = part.filter(pl.col("symbol").is_in(symbols))
        rows.append(selected)
    clean = Bar1dSchema.validate(pl.concat(rows, how="vertical_relaxed")).sort(
        "symbol", "trade_date", "source"
    )
    keys = list(clean.select("symbol", "trade_date").iter_rows())
    if set(keys) != expected or len(keys) != len(expected):
        raise ValueError
    if clean.filter(
        ~pl.col("symbol").str.contains(r"^[0-9]{5}\.HK$")
        | (pl.col("adj_factor") != 1.0)
    ).height:
        raise ValueError
    return clean


def _parse_availability(payload: bytes, plan: HKHistoryPlan) -> pl.DataFrame:
    value = _strict_json(payload)
    if (
        set(value)
        != {
            "schema_version",
            "plan_sha256",
            "availability_content_sha256",
            "rows",
        }
        or value["schema_version"] != "hk-bar-availability-v1"
        or value["plan_sha256"] != plan.plan_sha256
        or type(value["rows"]) is not list
        or payload != _canonical_json(value).encode("utf-8")
        or value["availability_content_sha256"]
        != hashlib.sha256(_canonical_json(value["rows"]).encode("utf-8")).hexdigest()
    ):
        raise ValueError
    exact = {
        "symbol",
        "trade_date",
        "source",
        "availability_source_kind",
        "bar_available_at",
        "source_record_id",
        "request_id",
        "raw_file_sha256",
        "raw_metadata_sha256",
        "request_receipt_sha256",
        "plan_sha256",
        "availability_evidence_sha256",
    }
    if any(type(row) is not dict or set(row) != exact for row in value["rows"]):
        raise ValueError
    frame = pl.DataFrame(value["rows"]).with_columns(
        pl.col("trade_date").str.to_date(),
        pl.col("bar_available_at").str.to_datetime(time_zone="UTC"),
    )
    validated = HkBarAvailabilityEvidenceSchema.validate(frame).sort(
        "symbol", "trade_date"
    )
    for row in value["rows"]:
        evidence = row["availability_evidence_sha256"]
        base = {key: item for key, item in row.items() if key != "availability_evidence_sha256"}
        if evidence != hashlib.sha256(_canonical_json(base).encode("utf-8")).hexdigest():
            raise ValueError
    return validated


def _load_v3_state(
    *,
    plan: HKHistoryPlan,
    journal_root: Path,
    seed_raw_root: Path,
    raw_store: RawStore,
    clean_root: Path,
    as_of: dt.datetime,
) -> tuple[
    pl.DataFrame,
    pl.DataFrame,
    str,
    tuple[tuple[str, int, int], ...],
    _ReadAnchors,
]:
    _validate_plan_again(plan)
    cutoff = _utc(as_of)
    anchors: _ReadAnchors | None = None
    try:
        anchors = _ReadAnchors(
            journal=journal_root,
            seed=seed_raw_root,
            raw=raw_store.root,
            clean=clean_root,
        )
        identities = anchors.identities
        finalize_path = journal_root / "finalize.json"
        _guard_journal_path(journal_root, finalize_path)
        try:
            finalize_payload = _read_anchored_path(
                finalize_path, root=journal_root, anchor=anchors.journal
            )
            finalize = _strict_json(finalize_payload)
        except (OSError, ValueError, json.JSONDecodeError):
            raise HKHistoryBackfillError(
                "HK_HISTORY_FINALIZE_V3_INVALID"
            ) from None
        if finalize.get("schema_version") in {
            "hk-history-finalize-v1",
            "hk-history-finalize-v2",
        }:
            raise HKHistoryBackfillError(
                "HK_HISTORY_AVAILABILITY_UNSUPPORTED"
            ) from None
        if (
            finalize.get("schema_version") != "hk-history-finalize-v3"
            or finalize_payload != _canonical_json(finalize).encode("utf-8")
            or set(finalize)
            != {
                "schema_version",
                "plan_sha256",
                "row_count",
                "clean_content_sha256",
                "availability_content_sha256",
                "availability_file_sha256",
                "source_receipts",
            }
            or finalize["plan_sha256"] != plan.plan_sha256
        ):
            raise ValueError
        _verify_journal_binding(plan, journal_root, anchor=anchors.journal)
        seed_frame, seed_time = _load_seed(
            plan, seed_raw_root, seed_anchor=anchors.seed
        )
        request_frames: list[tuple[HKHistoryRequest, pl.DataFrame]] = []
        for request in plan.requests:
            frame = _verify_receipt(
                plan,
                request,
                raw_store,
                journal_root,
                journal_anchor=anchors.journal,
                raw_anchor=anchors.raw,
            )
            if frame is None:
                raise ValueError
            request_frames.append((request, frame))
        raw_path = journal_root / _HKEX_RETAINED_RAW_FILE
        metadata_path = journal_root / _HKEX_RETAINED_METADATA_FILE
        _guard_journal_path(journal_root, raw_path)
        _guard_journal_path(journal_root, metadata_path)
        retained = verify_hkex_daily_quotation_retained(
            _read_anchored_path(
                raw_path, root=journal_root, anchor=anchors.journal
            ),
            _read_anchored_path(
                metadata_path, root=journal_root, anchor=anchors.journal
            ),
            source_url=HKEX_02983_SOURCE_URL,
            expected_raw_sha256=HKEX_02983_RAW_SHA256,
        )
        hkex_frame, _receipt, retained = _prepare_hkex_supplement_v3(
            plan=plan, retained_bundle=retained
        )
        expected_availability = _build_availability_evidence(
            plan=plan,
            seed_frame=seed_frame,
            seed_fetched_at=seed_time,
            request_frames=request_frames,
            raw_store=raw_store,
            journal_root=journal_root,
            hkex_frame=hkex_frame,
            hkex_bundle=retained,
            anchors=anchors,
        )
        availability_path = journal_root / _AVAILABILITY_FILE
        _guard_journal_path(journal_root, availability_path)
        availability_payload = _read_anchored_path(
            availability_path, root=journal_root, anchor=anchors.journal
        )
        availability = _parse_availability(availability_payload, plan)
        expected_payload = _canonical_json(
            _availability_payload(plan, expected_availability)
        ).encode("utf-8")
        if availability_payload != expected_payload:
            raise ValueError
        if availability.filter(pl.col("bar_available_at") > cutoff).height:
            raise HKHistoryBackfillError("HK_BAR_PUBLICATION_INVALID") from None
        clean = _read_published_exact(plan, clean_root, anchor=anchors.clean)
        expected_clean = Bar1dSchema.validate(
            pl.concat(
                [seed_frame, *(frame for _, frame in request_frames), hkex_frame],
                how="vertical_relaxed",
            )
        ).sort("symbol", "trade_date", "source")
        if _frame_hash(clean) != _frame_hash(expected_clean):
            raise ValueError
        source_receipts = finalize["source_receipts"]
        expected_sources = {
            "seed": {
                "source_record_id": plan.seed.selector,
                "raw_file_sha256": plan.seed.checksum_sha256,
                "raw_metadata_sha256": plan.seed.metadata_sha256,
            },
            "requests": _request_source_receipts(
                plan, raw_store, journal_root, anchors=anchors
            ),
            "hkex": {
                "bundle_id": retained.bundle_id,
                "quotation_evidence_id": retained.quotation.evidence_id,
                "metadata_identity": retained.metadata.metadata_identity,
                "raw_file": _HKEX_RETAINED_RAW_FILE,
                "raw_file_sha256": hashlib.sha256(retained.retained_raw).hexdigest(),
                "metadata_file": _HKEX_RETAINED_METADATA_FILE,
                "raw_metadata_sha256": hashlib.sha256(
                    retained.retained_metadata
                ).hexdigest(),
                "source_record_id": retained.metadata.source_record_id,
            },
        }
        availability_value = _availability_payload(plan, availability)
        if (
            source_receipts != expected_sources
            or finalize["row_count"] != clean.height
            or finalize["clean_content_sha256"] != _frame_hash(clean)
            or finalize["availability_content_sha256"]
            != availability_value["availability_content_sha256"]
            or finalize["availability_file_sha256"]
            != hashlib.sha256(availability_payload).hexdigest()
        ):
            raise ValueError
        return (
            clean,
            availability,
            hashlib.sha256(finalize_payload).hexdigest(),
            identities,
            anchors,
        )
    except HKHistoryBackfillError as error:
        if anchors is not None:
            anchors.close()
        if str(error) in {
            "HK_HISTORY_AVAILABILITY_UNSUPPORTED",
            "HK_HISTORY_FINALIZE_V3_INVALID",
            "HK_BAR_PUBLICATION_INVALID",
        }:
            raise
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None
    except Exception:
        if anchors is not None:
            anchors.close()
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None


def _capability_attestation(
    *,
    plan_sha256: str,
    bars: pl.DataFrame,
    availability: pl.DataFrame,
    publication_sha256: str,
    root_identities: tuple[tuple[str, int, int], ...],
    anchors: _ReadAnchors | None = None,
) -> str:
    if anchors is not None:
        anchors.assert_namespaces()
    payload = _canonical_json(
        {
            "plan_sha256": plan_sha256,
            "bars": _frame_hash(bars),
            "availability": _frame_hash(availability),
            "publication_sha256": publication_sha256,
            "root_identities": root_identities,
        }
    ).encode("utf-8")
    return hmac.new(_CAPABILITY_SECRET, payload, hashlib.sha256).hexdigest()


def load_verified_hk_bar_bundle(
    *,
    plan: HKHistoryPlan,
    journal_root: Path,
    seed_raw_root: Path,
    raw_store: RawStore,
    clean_root: Path,
    as_of: dt.datetime,
) -> VerifiedHkBarBundle:
    """Freshly load a v3 publication into a process-local capability."""
    anchors: _ReadAnchors | None = None
    result: VerifiedHkBarBundle | None = None
    failure: str | None = None
    try:
        bars, availability, publication, roots, anchors = _load_v3_state(
            plan=plan,
            journal_root=journal_root,
            seed_raw_root=seed_raw_root,
            raw_store=raw_store,
            clean_root=clean_root,
            as_of=as_of,
        )
        anchors.assert_namespaces()
        attestation = _capability_attestation(
            plan_sha256=plan.plan_sha256,
            bars=bars,
            availability=availability,
            publication_sha256=publication,
            root_identities=roots,
            anchors=anchors,
        )
        result = object.__new__(VerifiedHkBarBundle)
        object.__setattr__(result, "_bars", bars.clone())
        object.__setattr__(result, "_availability", availability.clone())
        object.__setattr__(result, "plan_sha256", plan.plan_sha256)
        object.__setattr__(result, "publication_sha256", publication)
        object.__setattr__(result, "_root_identities", roots)
        object.__setattr__(
            result,
            "_attestation",
            attestation,
        )
    except Exception as error:
        failure = _public_hk_bar_error_code(error)
    finally:
        if anchors is not None:
            try:
                anchors.close()
            except Exception:
                failure = "HK_BAR_VERIFY_FAILED"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if result is None:
        raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None
    return result


def _public_hk_bar_error_code(error: Exception) -> str:
    if type(error) is HKHistoryBackfillError and str(error) in {
        "HK_HISTORY_AVAILABILITY_UNSUPPORTED",
        "HK_HISTORY_FINALIZE_V3_INVALID",
        "HK_BAR_PUBLICATION_INVALID",
    }:
        return str(error)
    return "HK_BAR_VERIFY_FAILED"


def verify_hk_bar_bundle(
    bundle: VerifiedHkBarBundle,
    *,
    plan: HKHistoryPlan,
    journal_root: Path,
    seed_raw_root: Path,
    raw_store: RawStore,
    clean_root: Path,
    as_of: dt.datetime,
) -> None:
    """Freshly rebuild every source and reject stale/fabricated capabilities."""
    failure: str | None = None
    try:
        if type(bundle) is not VerifiedHkBarBundle:
            raise ValueError
        rebuilt = load_verified_hk_bar_bundle(
            plan=plan,
            journal_root=journal_root,
            seed_raw_root=seed_raw_root,
            raw_store=raw_store,
            clean_root=clean_root,
            as_of=as_of,
        )
        expected = _capability_attestation(
            plan_sha256=bundle.plan_sha256,
            bars=bundle._bars,
            availability=bundle._availability,
            publication_sha256=bundle.publication_sha256,
            root_identities=bundle._root_identities,
        )
        if (
            bundle.plan_sha256 != rebuilt.plan_sha256
            or bundle.publication_sha256 != rebuilt.publication_sha256
            or bundle._root_identities != rebuilt._root_identities
            or _frame_hash(bundle._bars) != _frame_hash(rebuilt._bars)
            or _frame_hash(bundle._availability) != _frame_hash(rebuilt._availability)
            or not hmac.compare_digest(bundle._attestation, expected)
            or not hmac.compare_digest(bundle._attestation, rebuilt._attestation)
        ):
            raise ValueError
    except Exception as error:
        failure = _public_hk_bar_error_code(error)
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def _raw_state(store: RawStore, request: HKHistoryRequest) -> str:
    failure: str | None = None
    state: str | None = None
    try:
        state = store.inspect_request_state(
            source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
        )
    except Exception:
        failure = "HK_HISTORY_RAW_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if state is None:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    return state


def _load_attempts(root: Path, request_id: str) -> tuple[dt.datetime, ...]:
    directory = root / "requests" / request_id / "attempts"
    _guard_journal_path(root, directory)
    if not directory.exists():
        return ()
    try:
        values = []
        for path in sorted(directory.glob("*.json")):
            value = _strict_json(path.read_bytes())
            if (
                value.get("schema_version") != "hk-history-attempt-v1"
                or value.get("request_id") != request_id
            ):
                raise ValueError
            values.append(_utc(dt.datetime.fromisoformat(value["started_at"])))
        return tuple(values)
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def _has_uncertain_attempt(root: Path, request_id: str) -> bool:
    attempts = root / "requests" / request_id / "attempts"
    return attempts.exists() and any(attempts.glob("*.json"))


def _verify_intent(root: Path, request: HKHistoryRequest) -> None:
    path = root / "requests" / request.request_id / "intent.json"
    _guard_journal_path(root, path)
    expected = {
        "schema_version": "hk-history-intent-v1",
        "request_id": request.request_id,
        "parameters": dict(request.parameters),
    }
    try:
        if path.read_bytes() != _canonical_json(expected).encode("utf-8"):
            raise ValueError
    except (OSError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


def _all_attempt_times(root: Path) -> list[dt.datetime]:
    values: list[dt.datetime] = []
    requests = root / "requests"
    if not requests.exists():
        return values
    for request_dir in requests.iterdir():
        if request_dir.is_dir() and _HEX64.fullmatch(request_dir.name):
            _guard_journal_path(root, request_dir)
            values.extend(_load_attempts(root, request_dir.name))
    return values


def _make_request(
    symbols: tuple[str, ...],
    expected: Mapping[str, tuple[str, ...]],
    *,
    effective: Mapping[str, tuple[str, ...]] | None = None,
) -> HKHistoryRequest:
    parameters = _request_parameters(symbols)
    return HKHistoryRequest(
        _request_id(parameters),
        symbols,
        tuple((symbol, expected[symbol]) for symbol in symbols),
        parameters,
        (
            tuple((symbol, effective[symbol]) for symbol in symbols)
            if effective is not None
            else ()
        ),
    )


def _request_parameters(symbols: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "ts_code": ",".join(symbols),
                "start_date": "20260414",
                "end_date": "20260710",
                "fields": HK_DAILY_FIELDS,
            }.items()
        )
    )


def _request_id(parameters: tuple[tuple[str, str], ...]) -> str:
    return hashlib.sha256(
        _canonical_json({"endpoint": "hk_daily", "parameters": parameters}).encode()
    ).hexdigest()


def _normalize_expected_dates(
    values: Mapping[str, Sequence[dt.date]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(values, Mapping):
        raise ValueError
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for symbol in sorted(values):
        if not _HK_SYMBOL.fullmatch(symbol):
            raise ValueError
        dates = values[symbol]
        if not isinstance(dates, Sequence) or isinstance(dates, (str, bytes)):
            raise ValueError
        date_values = tuple(date.isoformat() for date in dates if type(date) is dt.date)
        if len(date_values) != len(dates) or not date_values or tuple(sorted(set(date_values))) != date_values:
            raise ValueError
        normalized.append((symbol, date_values))
    if not normalized:
        raise ValueError
    return tuple(normalized)


def _validate_expected_dates(
    values: tuple[tuple[str, tuple[str, ...]], ...],
    symbols: tuple[str, ...],
    *,
    allow_empty_dates: bool = False,
) -> None:
    if tuple(symbol for symbol, _ in values) != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
        raise ValueError("expected symbols 非法")
    for symbol, dates in values:
        if not _HK_SYMBOL.fullmatch(symbol) or (not dates and not allow_empty_dates):
            raise ValueError("expected dates 非法")
        parsed = tuple(_date(value) for value in dates)
        if tuple(sorted(set(parsed))) != parsed:
            raise ValueError("expected dates 未排序或重复")


def _validate_symbols(symbols: tuple[str, ...], *, allow_empty: bool) -> None:
    if type(symbols) is not tuple or (not allow_empty and not symbols):
        raise ValueError("symbols 非法")
    if tuple(sorted(set(symbols))) != symbols or not all(_HK_SYMBOL.fullmatch(v) for v in symbols):
        raise ValueError("symbols 必须排序唯一且为 HK 代码")


def _validate_selector(value: str, *, suffix: str | None = ".parquet") -> None:
    path = PurePosixPath(value)
    if (
        type(value) is not str
        or not value
        or path.is_absolute()
        or "\\" in value
        or ".." in path.parts
        or (suffix is not None and path.suffix != suffix)
    ):
        raise ValueError("seed selector 非法")


def _validate_plan_again(plan: HKHistoryPlan) -> None:
    try:
        _plan_from_dict(asdict(plan))
    except (TypeError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


def _plan_hash_values(plan: HKHistoryPlan) -> str:
    value = _plan_dict(plan)
    value["plan_sha256"] = "0" * 64
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _plan_dict(plan: HKHistoryPlan) -> dict[str, Any]:
    return _serialize_plan_values(asdict(plan))


def _serialize_plan_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact on-disk shape, omitting v2 defaults from v1 plans."""
    result = dict(values)
    result["seed"] = asdict(values["seed"]) if isinstance(values["seed"], HKHistorySeed) else values["seed"]
    requests: list[dict[str, Any]] = []
    for request_value in values["requests"]:
        item = asdict(request_value) if isinstance(request_value, HKHistoryRequest) else dict(request_value)
        if values["schema_version"] == HK_HISTORY_SCHEMA_VERSION:
            item.pop("effective_expected_dates", None)
        requests.append(item)
    result["requests"] = requests
    if values["schema_version"] == HK_HISTORY_SCHEMA_VERSION:
        for key in (
            "no_trade_evidence",
            "no_trade_evidence_sha256",
            "effective_expected_dates",
            "journal_id",
        ):
            result.pop(key, None)
    else:
        result["no_trade_evidence"] = [
            asdict(item) if isinstance(item, HKNoTradeEvidence) else dict(item)
            for item in values["no_trade_evidence"]
        ]
    return result


def _plan_from_dict(value: dict[str, Any]) -> HKHistoryPlan:
    seed = HKHistorySeed(
        value["seed"]["selector"],
        tuple(value["seed"]["symbols"]),
        value["seed"]["checksum_sha256"],
        value["seed"]["metadata_sha256"],
    )
    requests = tuple(
        HKHistoryRequest(
            item["request_id"],
            tuple(item["symbols"]),
            tuple((row[0], tuple(row[1])) for row in item["expected_dates"]),
            tuple(tuple(row) for row in item["parameters"]),
            tuple(
                (row[0], tuple(row[1]))
                for row in item.get("effective_expected_dates", ())
            ),
        )
        for item in value["requests"]
    )
    is_v2 = value["schema_version"] == HK_HISTORY_SCHEMA_VERSION_V2
    return HKHistoryPlan(
        schema_version=value["schema_version"],
        strategy=value["strategy"],
        as_of=value["as_of"],
        window_start=value["window_start"],
        window_end=value["window_end"],
        fields=value["fields"],
        batch_size=value["batch_size"],
        expected_dates=tuple((row[0], tuple(row[1])) for row in value["expected_dates"]),
        seed=seed,
        unresolved=tuple((row[0], tuple(row[1])) for row in value["unresolved"]),
        requests=requests,
        plan_sha256=value["plan_sha256"],
        no_trade_evidence=(
            tuple(_evidence_from_dict(item) for item in value["no_trade_evidence"])
            if is_v2
            else ()
        ),
        no_trade_evidence_sha256=(value["no_trade_evidence_sha256"] if is_v2 else ""),
        effective_expected_dates=(
            tuple((row[0], tuple(row[1])) for row in value["effective_expected_dates"])
            if is_v2
            else ()
        ),
        journal_id=(value["journal_id"] if is_v2 else ""),
    )


def _evidence_from_dict(value: object) -> HKNoTradeEvidence:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "evidence_sha256",
        "symbol",
        "trade_date",
        "market",
        "reason",
        "source",
        "source_record_id",
        "source_as_of",
        "raw_selector",
        "raw_file_sha256",
        "raw_metadata_sha256",
    }:
        raise ValueError
    return HKNoTradeEvidence(**value)


def _evidence_identity(evidence: HKNoTradeEvidence) -> str:
    value = asdict(evidence)
    value.pop("evidence_sha256")
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _evidence_set_identity(evidences: Sequence[HKNoTradeEvidence]) -> str:
    return hashlib.sha256(
        _canonical_json([asdict(item) for item in evidences]).encode()
    ).hexdigest()


def _verify_evidence_projection(
    evidence_set: HKNoTradeEvidenceSet,
    *,
    raw_root: Path,
    anchor: _DirectoryAnchor | None = None,
) -> None:
    base = raw_root.resolve()
    rows: list[dict[str, Any]] = []
    for evidence in evidence_set.evidences:
        raw_path = (base / PurePosixPath(evidence.raw_selector)).resolve()
        metadata_path = raw_path.with_suffix(".json")
        failure: str | None = None
        try:
            raw_path.relative_to(base)
            metadata_path.relative_to(base)
            raw_payload = _read_anchored_path(
                raw_path, root=raw_root, anchor=anchor
            )
            metadata_payload = _read_anchored_path(
                metadata_path, root=raw_root, anchor=anchor
            )
            if (
                hashlib.sha256(raw_payload).hexdigest() != evidence.raw_file_sha256
                or hashlib.sha256(metadata_payload).hexdigest()
                != evidence.raw_metadata_sha256
            ):
                raise ValueError
            metadata = _strict_json(metadata_payload)
            expected_metadata = {
                "schema_version": "hk-no-trade-raw-metadata-v1",
                "source": evidence.source,
                "source_record_id": evidence.source_record_id,
                "source_as_of": evidence.source_as_of,
                "raw_selector": evidence.raw_selector,
                "raw_file_sha256": evidence.raw_file_sha256,
            }
            if (
                metadata != expected_metadata
                or metadata_payload != _canonical_json(expected_metadata).encode("utf-8")
            ):
                raise ValueError
            if evidence.source == HK_NO_TRADE_USER_APPROVED_SOURCE:
                _verify_user_approved_no_trade_raw(raw_payload, evidence=evidence)
            row = asdict(evidence)
            row["trade_date"] = _date(evidence.trade_date)
            row["source_as_of"] = dt.datetime.fromisoformat(evidence.source_as_of)
            rows.append(row)
        except Exception:
            failure = "HK_HISTORY_REFERENCE_INVALID"
        if failure is not None:
            raise HKHistoryBackfillError(failure) from None
    failure = None
    try:
        HKNoTradeEvidenceSchema.validate(pl.DataFrame(rows))
    except Exception:
        failure = "HK_HISTORY_REFERENCE_INVALID"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def _user_approved_no_trade_is_exact(evidence: HKNoTradeEvidence) -> bool:
    if evidence.source_record_id == _USER_APPROVED_NO_TRADE_RECORD:
        return (
            (evidence.symbol, evidence.trade_date) == _USER_APPROVED_NO_TRADE_KEY
            and evidence.raw_selector == _USER_APPROVED_NO_TRADE_SELECTOR
        )
    if evidence.source_record_id == _USER_APPROVED_SUSPENSION_RANGE_RECORD:
        return (
            evidence.symbol == _USER_APPROVED_SUSPENSION_RANGE_SYMBOL
            and evidence.trade_date in _USER_APPROVED_SUSPENSION_RANGE_DATES
            and evidence.raw_selector == _USER_APPROVED_SUSPENSION_RANGE_SELECTOR
        )
    if evidence.source_record_id == _USER_APPROVED_TRADING_HALT_RECORD:
        return (
            (evidence.symbol, evidence.trade_date) == _USER_APPROVED_TRADING_HALT_KEY
            and evidence.raw_selector == _USER_APPROVED_TRADING_HALT_SELECTOR
        )
    return False


def _user_approved_suspension_range_payload() -> dict[str, Any]:
    return {
        "approval_id": _USER_APPROVED_SUSPENSION_RANGE_RECORD,
        "no_trade_dates": list(_USER_APPROVED_SUSPENSION_RANGE_DATES),
        "observations": [
            {
                "observation": _USER_APPROVED_SUSPENSION_OBSERVATION,
                "source_kind": "HKEX_NEWS",
                "url": _USER_APPROVED_SUSPENSION_NOTICE_URL,
            },
            {
                "observation": _USER_APPROVED_RESUMPTION_OBSERVATION,
                "source_kind": "HKEX_NEWS",
                "url": _USER_APPROVED_RESUMPTION_NOTICE_URL,
            },
            {
                "observation": _USER_APPROVED_TUSHARE_ZERO_ROW_OBSERVATION,
                "source_kind": "TUSHARE_HK_DAILY",
            },
        ],
        "resumption_at": _USER_APPROVED_RESUMPTION_AT,
        "schema_version": "hk-no-trade-user-approved-suspension-range-v1",
        "suspension_at": _USER_APPROVED_SUSPENSION_AT,
        "symbol": _USER_APPROVED_SUSPENSION_RANGE_SYMBOL,
    }


def _user_approved_trading_halt_payload() -> dict[str, Any]:
    return {
        "approval_id": _USER_APPROVED_TRADING_HALT_RECORD,
        "decision": "NO_DAILY_TRADING_V1",
        "impact_assessment": {
            "changes_cash": False,
            "changes_corporate_actions": False,
            "changes_positions": False,
            "changes_real_orders": False,
            "changes_strategy_signal": False,
        },
        "observations": [
            {
                "observation": "TRADING_HALTED_FROM_09_00",
                "source_kind": "HKEX_NEWS",
                "url": _USER_APPROVED_TRADING_HALT_NOTICE_URL,
            },
            {
                "observation": _USER_APPROVED_TUSHARE_ZERO_ROW_OBSERVATION,
                "source_kind": "TUSHARE_HK_DAILY",
            },
            {
                "observation": "LISTED_AS_SUSPENDED",
                "source_kind": "INDEPENDENT_PUBLIC_MARKET_NEWS",
                "url": _USER_APPROVED_TRADING_HALT_INDEPENDENT_URL,
            },
        ],
        "schema_version": "hk-no-trade-user-approved-trading-halt-v1",
        "symbol": _USER_APPROVED_TRADING_HALT_KEY[0],
        "trade_date": _USER_APPROVED_TRADING_HALT_KEY[1],
    }


def _verify_user_approved_no_trade_raw(
    payload: bytes, *, evidence: HKNoTradeEvidence
) -> None:
    """Verify one of the three exact user-approved, non-HKEX consensus records."""
    value = _strict_json(payload)
    if evidence.source_record_id == _USER_APPROVED_NO_TRADE_RECORD:
        expected: dict[str, Any] = {
            "approval_id": _USER_APPROVED_NO_TRADE_RECORD,
            "approved_on": "2026-08-15",
            "decision": "NO_DAILY_TRADING_V1",
            "evidence": [
                {
                    "observation": "NO_DAILY_TRADING",
                    "source_kind": "USER_SECURITIES_SOFTWARE",
                },
                {
                    "observation": "ZERO_ROWS_ON_TARGETED_RETRY",
                    "source_kind": "TUSHARE_HK_DAILY",
                },
            ],
            "impact_assessment": {
                "changes_cash": False,
                "changes_corporate_actions": False,
                "changes_positions": False,
                "changes_real_orders": False,
                "changes_strategy_signal": False,
            },
            "schema_version": "hk-no-trade-user-approved-consensus-v1",
            "symbol": evidence.symbol,
            "trade_date": evidence.trade_date,
        }
    elif evidence.source_record_id == _USER_APPROVED_SUSPENSION_RANGE_RECORD:
        expected = _user_approved_suspension_range_payload()
        if (
            evidence.symbol != expected["symbol"]
            or evidence.trade_date not in expected["no_trade_dates"]
        ):
            raise ValueError
    elif evidence.source_record_id == _USER_APPROVED_TRADING_HALT_RECORD:
        expected = _user_approved_trading_halt_payload()
        if (
            evidence.symbol != expected["symbol"]
            or evidence.trade_date != expected["trade_date"]
        ):
            raise ValueError
    else:
        raise ValueError
    if value != expected or payload != _canonical_json(expected).encode("utf-8"):
        raise ValueError


def _frame_hash(frame: pl.DataFrame) -> str:
    rows = [
        [_scalar(value) for value in row]
        for row in frame.sort(frame.columns).iter_rows()
    ]
    return hashlib.sha256(
        _canonical_json({"columns": frame.columns, "rows": rows}).encode()
    ).hexdigest()


def _scalar(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _strict_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload)
    if type(value) is not dict:
        raise ValueError
    return value


def _write_or_verify_json(path: Path, value: dict[str, Any], code: str) -> None:
    payload = _canonical_json(value).encode("utf-8")
    failure: str | None = None
    try:
        if path.exists():
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError(code)
            return
        _write_once(path, payload)
    except HKHistoryBackfillError as error:
        failure = str(error)
    except OSError:
        failure = code
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def _bind_v2_journal(plan: HKHistoryPlan, root: Path) -> None:
    if plan.schema_version == HK_HISTORY_SCHEMA_VERSION:
        return
    marker = root / "binding.json"
    _guard_journal_path(root, marker)
    expected = {
        "schema_version": "hk-history-journal-binding-v2",
        "journal_id": plan.journal_id,
        "plan_sha256": plan.plan_sha256,
        "no_trade_evidence_sha256": plan.no_trade_evidence_sha256,
    }
    failure: str | None = None
    try:
        if not marker.exists():
            existing = {path.name for path in root.iterdir()}
            if existing - {".writer.lock"}:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
        _write_or_verify_json(marker, expected, "HK_HISTORY_PLAN_CONFLICT")
    except HKHistoryBackfillError as error:
        failure = str(error)
    except Exception:
        failure = "HK_HISTORY_PLAN_CONFLICT"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _guard_journal_path(root: Path, target: Path) -> None:
    """Reject pre-existing nested symlinks and non-directory ancestors."""
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    cursor = root
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
        if stat.S_ISLNK(mode) or (
            index < len(relative.parts) - 1 and not stat.S_ISDIR(mode)
        ):
            raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID")


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value) if "-" in value else dt.datetime.strptime(value, "%Y%m%d").date()


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("timezone required")
    return value.astimezone(dt.timezone.utc)
