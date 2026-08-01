"""Strict, resumable Tushare HK daily-history backfill.

The module deliberately keeps the undocumented multi-symbol wire contract behind
an immutable plan.  A network response is persisted before its contents are
accepted, and clean bars are published only after every planned batch is closed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import polars as pl

from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.connectors.tushare import TushareConnector
from quant.data.mappers import TushareBarMapper
from quant.data.storage import CleanBarStore, RawStore, RequestRawSnapshot
from quant.domain import Bar1dSchema
from quant.domain.schemas import HKNoTradeEvidenceSchema

HK_DAILY_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
)
HK_HISTORY_STRATEGY = "MULTI_SYMBOL_RANGE_STRICT_V1"
HK_HISTORY_SCHEMA_VERSION = "hk-history-plan-v1"
HK_HISTORY_STRATEGY_V2 = "MULTI_SYMBOL_RANGE_STRICT_V2"
HK_HISTORY_SCHEMA_VERSION_V2 = "hk-history-plan-v2"
HK_NO_TRADE_EVIDENCE_SET_VERSION = "hk-no-trade-evidence-set-v1"
HK_HISTORY_COOLDOWN_SECONDS = 3600
HK_HISTORY_MAX_BATCH_SYMBOLS = 80
HK_HISTORY_ROW_LIMIT = 5000
HK_HISTORY_RAW_TABLE = "hk_daily_multi_symbol_backfill"
_HK_SYMBOL = re.compile(r"^[0-9]{5}\.HK$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RAW_COLUMNS = tuple(HK_DAILY_FIELDS.split(","))


class HKHistoryBackfillError(RuntimeError):
    """A stable, sanitized HK history failure code."""


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
            or self.source != "HKEX_DAILY_QUOTATIONS"
            or type(self.source_record_id) is not str
            or not self.source_record_id
            or not _HEX64.fullmatch(self.raw_file_sha256)
            or not _HEX64.fullmatch(self.raw_metadata_sha256)
        ):
            raise ValueError("no-trade evidence contract invalid")
        _date(self.trade_date)
        _utc(dt.datetime.fromisoformat(self.source_as_of))
        _validate_selector(self.raw_selector, suffix=None)
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
    try:
        payload = path.read_bytes()
        value = _strict_json(payload)
        if set(value) != {"schema_version", "evidences", "evidence_set_sha256"}:
            raise ValueError
        if type(value["evidences"]) is not list:
            raise ValueError
        evidences = tuple(_evidence_from_dict(item) for item in value["evidences"])
        result = HKNoTradeEvidenceSet(
            schema_version=value["schema_version"],
            evidences=evidences,
            evidence_set_sha256=value["evidence_set_sha256"],
        )
        expected_payload = _canonical_json(
            {
                "schema_version": result.schema_version,
                "evidences": [asdict(item) for item in result.evidences],
                "evidence_set_sha256": result.evidence_set_sha256,
            }
        ).encode("utf-8")
        if payload != expected_payload:
            raise ValueError
        _verify_evidence_projection(result, raw_root=raw_root)
        return result
    except HKHistoryBackfillError:
        raise
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


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
        return HKHistoryPlan(**values)
    except (KeyError, TypeError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def write_or_verify_plan(path: Path, plan: HKHistoryPlan) -> None:
    """Create an immutable plan or verify the existing plan byte-for-byte."""
    payload = _canonical_json(_plan_dict(plan)).encode("utf-8")
    try:
        if path.exists():
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
            load_hk_history_plan(path)
            return
        _write_once(path, payload)
    except HKHistoryBackfillError:
        raise
    except OSError:
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


def load_hk_history_plan(path: Path) -> HKHistoryPlan:
    """Load and strictly reconstruct an immutable plan."""
    try:
        value = _strict_json(path.read_bytes())
        plan = _plan_from_dict(value)
        if path.read_bytes() != _canonical_json(_plan_dict(plan)).encode("utf-8"):
            raise ValueError
        return plan
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


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
            return HKHistoryExecutionResult(
                request_id=None,
                network_requests=0,
                completed_requests=completed,
                total_requests=len(plan.requests),
                is_complete=True,
            )
    except HKHistoryBackfillError:
        raise
    except M3JournalLockError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    except OSError:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


def finalize_hk_history(
    *,
    plan: HKHistoryPlan,
    raw_store: RawStore,
    journal_root: Path,
    seed_raw_root: Path,
    clean_root: Path,
) -> int:
    """Publish all validated planned bars after a read-only conflict preflight."""
    _validate_plan_again(plan)
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
        with hold_journal_writer_lock(journal_root=journal_root):
            seed_frame, seed_fetched_at = _load_seed(plan, seed_raw_root)
            _bind_v2_journal(plan, journal_root)
            del seed_fetched_at
            frames = [seed_frame]
            for request in plan.requests:
                receipt = _verify_receipt(plan, request, raw_store, journal_root)
                if receipt is None:
                    raise HKHistoryBackfillError("HK_HISTORY_INCOMPLETE")
                frames.append(receipt)
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
                if symbol not in dict(plan.unresolved)
                for date_value in dates
            }
            actual_keys = set(clean.select("symbol", "trade_date").iter_rows())
            if actual_keys != expected_keys or clean.height != len(expected_keys):
                raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID")
            _preflight_clean(clean, clean_root)
            try:
                written = CleanBarStore(clean_root).upsert(clean)
                _verify_published(clean, clean_root)
                _write_finalize_receipt(journal_root, plan, clean)
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
        return Bar1dSchema.validate(TushareBarMapper().map(enriched))
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


def _read_and_validate_request(
    request: HKHistoryRequest, raw_store: RawStore
) -> pl.DataFrame:
    try:
        _, frame = raw_store.verify_request_bundle(
            source="tushare",
            table=HK_HISTORY_RAW_TABLE,
            request_id=request.request_id,
            parameters=dict(request.parameters),
        )
    except (OSError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None
    expected = (
        request.effective_expected_dates
        if request.effective_expected_dates
        else request.expected_dates
    )
    return _validate_raw(frame, dict(expected), request.symbols)


def _verify_receipt(
    plan: HKHistoryPlan,
    request: HKHistoryRequest,
    raw_store: RawStore,
    journal_root: Path,
) -> pl.DataFrame | None:
    path = journal_root / "requests" / request.request_id / "receipt.json"
    _guard_journal_path(journal_root, path)
    if not path.exists():
        return None
    if plan.schema_version == HK_HISTORY_SCHEMA_VERSION:
        _verify_intent(journal_root, request)
    frame = _read_and_validate_request(request, raw_store)
    try:
        value = _strict_json(path.read_bytes())
        snapshot, _ = raw_store.verify_request_bundle(
            source="tushare",
            table=HK_HISTORY_RAW_TABLE,
            request_id=request.request_id,
            parameters=dict(request.parameters),
        )
        expected = _receipt_dict(plan, request, snapshot, frame)
        if value != expected or path.read_bytes() != _canonical_json(expected).encode("utf-8"):
            raise ValueError
        return frame
    except (OSError, ValueError, json.JSONDecodeError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


def _write_receipt(
    plan: HKHistoryPlan,
    request: HKHistoryRequest,
    raw_store: RawStore,
    journal_root: Path,
    frame: pl.DataFrame,
) -> None:
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
    except HKHistoryBackfillError:
        raise
    except (OSError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


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


def _load_seed(plan: HKHistoryPlan, raw_root: Path) -> tuple[pl.DataFrame, dt.datetime]:
    if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2:
        try:
            _verify_evidence_projection(
                HKNoTradeEvidenceSet(
                    schema_version=HK_NO_TRADE_EVIDENCE_SET_VERSION,
                    evidences=plan.no_trade_evidence,
                    evidence_set_sha256=plan.no_trade_evidence_sha256,
                ),
                raw_root=raw_root,
            )
        except (TypeError, ValueError):
            raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    base = raw_root.resolve()
    data_path = (base / PurePosixPath(plan.seed.selector)).resolve()
    try:
        data_path.relative_to(base)
        if data_path.suffix != ".parquet":
            raise ValueError
        metadata_path = data_path.with_suffix(".json")
        metadata_payload = metadata_path.read_bytes()
        metadata = _strict_json(metadata_payload)
        payload = data_path.read_bytes()
        payload_checksum = hashlib.sha256(payload).hexdigest()
        if (
            payload_checksum != metadata["checksum_sha256"]
            or payload_checksum != plan.seed.checksum_sha256
            or hashlib.sha256(metadata_payload).hexdigest()
            != plan.seed.metadata_sha256
        ):
            raise ValueError
        raw = pl.read_parquet(data_path)
        if metadata["rows"] != raw.height or metadata["columns"] != raw.columns:
            raise ValueError
        fetched_at = _utc(dt.datetime.fromisoformat(metadata["fetched_at"]))
        expected_source = (
            plan.effective_expected_dates
            if plan.schema_version == HK_HISTORY_SCHEMA_VERSION_V2
            else plan.expected_dates
        )
        clean = _validate_seed_raw(raw, dict(expected_source), plan.seed.symbols)
        return clean, fetched_at
    except HKHistoryBackfillError:
        raise
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


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
    try:
        if raw.filter(
            (pl.col("_request_symbol") != pl.col("ts_code"))
            | (pl.col("_market") != "HK")
        ).height:
            raise ValueError
        return _validate_raw(raw.select(_RAW_COLUMNS), all_expected, symbols)
    except HKHistoryBackfillError:
        raise
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


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


def _write_finalize_receipt(root: Path, plan: HKHistoryPlan, clean: pl.DataFrame) -> None:
    value = {
        "schema_version": "hk-history-finalize-v1",
        "plan_sha256": plan.plan_sha256,
        "row_count": clean.height,
        "clean_content_sha256": _frame_hash(clean),
    }
    path = root / "finalize.json"
    _guard_journal_path(root, path)
    _write_or_verify_json(path, value, "HK_HISTORY_PUBLISH_FAILED")


def _raw_state(store: RawStore, request: HKHistoryRequest) -> str:
    try:
        return store.inspect_request_state(
            source="tushare", table=HK_HISTORY_RAW_TABLE, request_id=request.request_id
        )
    except (OSError, ValueError):
        raise HKHistoryBackfillError("HK_HISTORY_RAW_INVALID") from None


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
    evidence_set: HKNoTradeEvidenceSet, *, raw_root: Path
) -> None:
    base = raw_root.resolve()
    rows: list[dict[str, Any]] = []
    for evidence in evidence_set.evidences:
        raw_path = (base / PurePosixPath(evidence.raw_selector)).resolve()
        metadata_path = raw_path.with_suffix(".json")
        try:
            raw_path.relative_to(base)
            metadata_path.relative_to(base)
            raw_payload = raw_path.read_bytes()
            metadata_payload = metadata_path.read_bytes()
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
            row = asdict(evidence)
            row["trade_date"] = _date(evidence.trade_date)
            row["source_as_of"] = dt.datetime.fromisoformat(evidence.source_as_of)
            rows.append(row)
        except Exception:
            raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None
    try:
        HKNoTradeEvidenceSchema.validate(pl.DataFrame(rows))
    except Exception:
        raise HKHistoryBackfillError("HK_HISTORY_REFERENCE_INVALID") from None


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
    try:
        if path.exists():
            if path.read_bytes() != payload:
                raise HKHistoryBackfillError(code)
            return
        _write_once(path, payload)
    except HKHistoryBackfillError:
        raise
    except OSError:
        raise HKHistoryBackfillError(code) from None


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
    try:
        if not marker.exists():
            existing = {path.name for path in root.iterdir()}
            if existing - {".writer.lock"}:
                raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")
        _write_or_verify_json(marker, expected, "HK_HISTORY_PLAN_CONFLICT")
    except HKHistoryBackfillError:
        raise
    except OSError:
        raise HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT") from None


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
