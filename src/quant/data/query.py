"""基于 DuckDB 的 clean 数据查询。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NoReturn, cast

import duckdb
import polars as pl

from quant.data.eligibility import eligible_symbols_on
from quant.data.hk_history_backfill import (
    HK_HISTORY_SCHEMA_VERSION_V2,
    HKHistoryBackfillError,
    HKHistoryPlan,
    HKNoTradeEvidence,
    VerifiedHkBarBundle,
    load_hk_no_trade_evidence,
)
from quant.domain.enums import InstrumentType, Market
from quant.domain.schemas import (
    ConnectEligibilityEventSchema,
    ConnectEligibilitySnapshotSchema,
    InstrumentSchema,
    SYMBOL_PATTERN,
    TradeCalendarSchema,
)

_BAR_WINDOW_ERROR_CODES = frozenset(
    {
        "BAR_WINDOW_INCOMPLETE",
        "BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE",
        "BAR_WINDOW_DUPLICATE_KEY",
        "BAR_WINDOW_INPUT_INVALID",
        "BAR_WINDOW_REFERENCE_INVALID",
    }
)
_SYMBOL_RE = re.compile(SYMBOL_PATTERN)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
VERIFIED_HK_AVAILABILITY_SOURCE = "verified-hk-availability-v1"


class BarWindowQueryError(ValueError):
    """Stable bar-window query boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _BAR_WINDOW_ERROR_CODES:
            raise ValueError("unknown bar window error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"BarWindowQueryError({self.code!r})"


def _require_canonical_symbol(symbol: str) -> None:
    if _SYMBOL_RE.fullmatch(symbol) is None:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class BarWindowCoverage:
    """Universe bar-window coverage summary; immutable and strictly validated."""

    universe: str
    as_of: dt.date
    source: str
    requested_observations: int
    eligible_symbol_count: int
    returned_symbol_count: int
    missing_symbols: tuple[str, ...]
    short_symbol_counts: tuple[tuple[str, int], ...]
    min_observations: int
    max_observations: int

    def __post_init__(self) -> None:
        if type(self.universe) is not str or not self.universe:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.as_of) is not dt.date:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.source) is not str or not self.source:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.requested_observations) is not int or self.requested_observations <= 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for name in (
            "eligible_symbol_count",
            "returned_symbol_count",
            "min_observations",
            "max_observations",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.missing_symbols) is not tuple or any(
            type(symbol) is not str for symbol in self.missing_symbols
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.short_symbol_counts) is not tuple:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for item in self.short_symbol_counts:
            if (
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not int
                or item[1] <= 0
                or item[1] >= self.requested_observations
            ):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for symbol in self.missing_symbols:
            _require_canonical_symbol(symbol)
        for symbol, _ in self.short_symbol_counts:
            _require_canonical_symbol(symbol)
        if self.missing_symbols != tuple(sorted(self.missing_symbols)):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.short_symbol_counts != tuple(
            sorted(self.short_symbol_counts, key=lambda item: item[0])
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if len(set(self.missing_symbols)) != len(self.missing_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        short_symbols = tuple(symbol for symbol, _ in self.short_symbol_counts)
        if len(set(short_symbols)) != len(short_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if set(self.missing_symbols) & set(short_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.returned_symbol_count + len(self.missing_symbols) != self.eligible_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.min_observations > self.max_observations:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.max_observations > self.requested_observations:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if len(self.short_symbol_counts) > self.returned_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.eligible_symbol_count == 0:
            if (
                self.returned_symbol_count != 0
                or self.missing_symbols
                or self.short_symbol_counts
                or self.min_observations != 0
                or self.max_observations != 0
            ):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            return
        if self.returned_symbol_count == 0:
            if (
                self.short_symbol_counts
                or self.min_observations != 0
                or self.max_observations != 0
                or len(self.missing_symbols) != self.eligible_symbol_count
            ):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            return
        if self.max_observations <= 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.missing_symbols:
            if self.min_observations != 0:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        elif self.min_observations <= 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        full_count = self.returned_symbol_count - len(self.short_symbol_counts)
        if full_count < 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        short_counts = tuple(count for _, count in self.short_symbol_counts)
        expected_min = (
            0
            if self.missing_symbols
            else (min(short_counts) if short_counts else self.requested_observations)
        )
        expected_max = (
            self.requested_observations
            if full_count > 0
            else (max(short_counts) if short_counts else 0)
        )
        if self.min_observations != expected_min or self.max_observations != expected_max:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")

    @property
    def is_full_window(self) -> bool:
        """True iff every eligible symbol has exactly the requested observations."""
        return not self.missing_symbols and not self.short_symbol_counts


@dataclass(frozen=True, slots=True)
class AuditedBarWindow:
    """Bar window frame bound to an explicit coverage audit."""

    frame: pl.DataFrame
    coverage: BarWindowCoverage

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pl.DataFrame):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.coverage) is not BarWindowCoverage:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        coverage = self.coverage
        frame = self.frame
        if frame.height == 0:
            if coverage.returned_symbol_count != 0 or coverage.max_observations != 0:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            return
        for column in ("symbol", "trade_date", "source"):
            if column not in frame.columns:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (
            frame.schema["symbol"] != pl.String
            or frame.schema["trade_date"] != pl.Date
            or frame.schema["source"] != pl.String
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (
            frame.get_column("symbol").null_count()
            or frame.get_column("trade_date").null_count()
            or frame.get_column("source").null_count()
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if frame.filter(
            (pl.col("source") != coverage.source) | (pl.col("trade_date") > coverage.as_of)
        ).height:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if frame.select(["symbol", "trade_date", "source"]).n_unique() != frame.height:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        symbols = frame.get_column("symbol").to_list()
        trade_dates = frame.get_column("trade_date").to_list()
        for symbol in symbols:
            if type(symbol) is not str:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            _require_canonical_symbol(symbol)
        order_keys = list(zip(symbols, trade_dates, strict=True))
        if order_keys != sorted(order_keys):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        count_frame = frame.group_by("symbol", maintain_order=True).agg(pl.len().alias("n"))
        counts = {
            str(symbol): int(count)
            for symbol, count in count_frame.select("symbol", "n").iter_rows()
        }
        if len(counts) != coverage.returned_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if set(counts) & set(coverage.missing_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        requested = coverage.requested_observations
        for count in counts.values():
            if count < 1 or count > requested:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        derived_short = tuple(
            (symbol, counts[symbol]) for symbol in sorted(counts) if counts[symbol] < requested
        )
        if derived_short != coverage.short_symbol_counts:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        short_symbols = {symbol for symbol, _ in coverage.short_symbol_counts}
        for symbol, count in counts.items():
            if symbol not in short_symbols and count != requested:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        observation_values = list(counts.values())
        expected_min = 0 if coverage.missing_symbols else min(observation_values)
        expected_max = max(observation_values)
        if coverage.min_observations != expected_min or coverage.max_observations != expected_max:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class AvailableHistoryCoverage:
    """Exact required-session coverage for listed stocks in an eligible universe."""

    universe: str
    as_of: dt.date
    source: str
    requested_observations: int
    eligible_symbol_count: int
    excluded_etf_symbols: tuple[str, ...]
    required_sessions: tuple[tuple[str, tuple[dt.date, ...]], ...]
    missing_sessions: tuple[tuple[str, tuple[dt.date, ...]], ...]
    unexpected_sessions: tuple[tuple[str, tuple[dt.date, ...]], ...]
    exempted_sessions: tuple[tuple[str, tuple[dt.date, ...]], ...]
    exemption_reason_counts: tuple[tuple[str, int], ...]
    no_trade_evidence_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.universe) is not str or not self.universe:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.as_of) is not dt.date:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.source) is not str or not self.source:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.requested_observations) is not int or self.requested_observations <= 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.eligible_symbol_count) is not int or self.eligible_symbol_count < 0:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.excluded_etf_symbols) is not tuple:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.excluded_etf_symbols != tuple(sorted(self.excluded_etf_symbols)):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if len(set(self.excluded_etf_symbols)) != len(self.excluded_etf_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for symbol in self.excluded_etf_symbols:
            if type(symbol) is not str:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            _require_canonical_symbol(symbol)

        required = self._validate_session_items(self.required_sessions, allow_empty_dates=True)
        missing = self._validate_session_items(self.missing_sessions, allow_empty_dates=False)
        unexpected = self._validate_session_items(self.unexpected_sessions, allow_empty_dates=False)
        exempted = self._validate_session_items(self.exempted_sessions, allow_empty_dates=False)
        required_symbols = set(required)
        if required_symbols & set(self.excluded_etf_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if len(required_symbols) + len(self.excluded_etf_symbols) != self.eligible_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (
            not set(missing).issubset(required_symbols)
            or not set(unexpected).issubset(required_symbols)
            or not set(exempted).issubset(required_symbols)
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for symbol, dates in required.items():
            if len(dates) > self.requested_observations:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if any(date > self.as_of for date in dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if not set(missing.get(symbol, ())).issubset(dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if set(unexpected.get(symbol, ())) & set(dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if set(exempted.get(symbol, ())) & set(dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.exemption_reason_counts) is not tuple or any(
            type(reason) is not str or not reason or type(count) is not int or count <= 0
            for reason, count in self.exemption_reason_counts
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.exemption_reason_counts != tuple(sorted(self.exemption_reason_counts)):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        exempted_total = sum(len(dates) for dates in exempted.values())
        if sum(count for _, count in self.exemption_reason_counts) != exempted_total:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (self.no_trade_evidence_sha256 is None) != (exempted_total == 0):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if self.no_trade_evidence_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.no_trade_evidence_sha256
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")

    @staticmethod
    def _validate_session_items(
        items: object, *, allow_empty_dates: bool
    ) -> dict[str, tuple[dt.date, ...]]:
        if type(items) is not tuple:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        result: dict[str, tuple[dt.date, ...]] = {}
        previous_symbol: str | None = None
        for item in items:
            if type(item) is not tuple or len(item) != 2:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            symbol, dates = item
            if type(symbol) is not str or type(dates) is not tuple:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            _require_canonical_symbol(symbol)
            if previous_symbol is not None and symbol <= previous_symbol:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            previous_symbol = symbol
            if not dates and not allow_empty_dates:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if any(type(date) is not dt.date for date in dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            result[symbol] = dates
        return result

    @property
    def required_stock_symbol_count(self) -> int:
        return len(self.required_sessions)

    @property
    def min_required_sessions(self) -> int:
        counts = [len(dates) for _, dates in self.required_sessions]
        return min(counts, default=0)

    @property
    def max_required_sessions(self) -> int:
        counts = [len(dates) for _, dates in self.required_sessions]
        return max(counts, default=0)

    @property
    def exempted_session_count(self) -> int:
        return sum(len(dates) for _, dates in self.exempted_sessions)

    @property
    def is_available_history_complete(self) -> bool:
        return not self.missing_sessions and not self.unexpected_sessions


@dataclass(frozen=True, slots=True)
class AuditedAvailableHistoryBarWindow:
    """Bar result bound to both count and exact available-history audits."""

    frame: pl.DataFrame
    coverage: BarWindowCoverage
    available_history: AvailableHistoryCoverage

    def __post_init__(self) -> None:
        AuditedBarWindow(frame=self.frame, coverage=self.coverage)
        if type(self.available_history) is not AvailableHistoryCoverage:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        available = self.available_history
        if (
            available.universe != self.coverage.universe
            or available.as_of != self.coverage.as_of
            or available.source != self.coverage.source
            or available.requested_observations != self.coverage.requested_observations
            or available.eligible_symbol_count != self.coverage.eligible_symbol_count
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")

        frame_symbols = (
            set(self.frame.get_column("symbol").to_list()) if self.frame.height else set()
        )
        eligible_symbols = frame_symbols | set(self.coverage.missing_symbols)
        required = dict(available.required_sessions)
        expected_symbols = set(required) | set(available.excluded_etf_symbols)
        if eligible_symbols != expected_symbols:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        observed: dict[str, set[dt.date]] = {symbol: set() for symbol in required}
        if self.frame.height:
            for symbol, trade_date in self.frame.select("symbol", "trade_date").iter_rows():
                if symbol in observed:
                    observed[symbol].add(trade_date)
        derived_missing = tuple(
            (symbol, tuple(sorted(set(dates) - observed[symbol])))
            for symbol, dates in available.required_sessions
            if set(dates) - observed[symbol]
        )
        derived_unexpected = tuple(
            (symbol, tuple(sorted(observed[symbol] - set(dates))))
            for symbol, dates in available.required_sessions
            if observed[symbol] - set(dates)
        )
        if (
            available.missing_sessions != derived_missing
            or available.unexpected_sessions != derived_unexpected
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")


def _require_hex64(value: object) -> str:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _availability_content_sha256(frame: pl.DataFrame) -> str:
    rows = [
        {
            key: (item.isoformat() if isinstance(item, (dt.date, dt.datetime)) else item)
            for key, item in row.items()
        }
        for row in frame.sort("symbol", "trade_date").iter_rows(named=True)
    ]
    return hashlib.sha256(_canonical_json(rows).encode("utf-8")).hexdigest()


def _evidence_set_sha256(evidences: tuple[HKNoTradeEvidence, ...]) -> str:
    return hashlib.sha256(
        _canonical_json([asdict(item) for item in evidences]).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MixedSourceBarWindowCoverage:
    """Mixed-source bar-window coverage bound to a verified availability identity."""

    universe: str
    as_of: dt.date
    source: str
    requested_observations: int
    eligible_symbol_count: int
    returned_symbol_count: int
    missing_symbols: tuple[str, ...]
    short_symbol_counts: tuple[tuple[str, int], ...]
    min_observations: int
    max_observations: int
    plan_sha256: str
    publication_sha256: str
    availability_content_sha256: str
    source_row_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        BarWindowCoverage(
            universe=self.universe,
            as_of=self.as_of,
            source=self.source,
            requested_observations=self.requested_observations,
            eligible_symbol_count=self.eligible_symbol_count,
            returned_symbol_count=self.returned_symbol_count,
            missing_symbols=self.missing_symbols,
            short_symbol_counts=self.short_symbol_counts,
            min_observations=self.min_observations,
            max_observations=self.max_observations,
        )
        if self.source != VERIFIED_HK_AVAILABILITY_SOURCE:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        _require_hex64(self.plan_sha256)
        _require_hex64(self.publication_sha256)
        _require_hex64(self.availability_content_sha256)
        if type(self.source_row_counts) is not tuple:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        previous: str | None = None
        for item in self.source_row_counts:
            if (
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or not item[0]
                or type(item[1]) is not int
                or item[1] <= 0
            ):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if previous is not None and item[0] <= previous:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            previous = item[0]
        if self.returned_symbol_count == 0 and self.source_row_counts:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")

    @property
    def is_full_window(self) -> bool:
        """True iff every eligible symbol has exactly the requested observations."""
        return not self.missing_symbols and not self.short_symbol_counts

    @property
    def source_row_total(self) -> int:
        return sum(count for _, count in self.source_row_counts)


@dataclass(frozen=True, slots=True)
class AuditedMixedSourceBarWindow:
    """Mixed-source bar window bound to verified availability coverage."""

    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pl.DataFrame):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(self.coverage) is not MixedSourceBarWindowCoverage:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        coverage = self.coverage
        frame = self.frame
        expected_total = coverage.source_row_total
        if frame.height == 0:
            if (
                coverage.returned_symbol_count != 0
                or coverage.max_observations != 0
                or coverage.source_row_counts
                or expected_total != 0
            ):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            return
        if frame.height != expected_total:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        for column in ("symbol", "trade_date", "source"):
            if column not in frame.columns:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (
            frame.schema["symbol"] != pl.String
            or frame.schema["trade_date"] != pl.Date
            or frame.schema["source"] != pl.String
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if (
            frame.get_column("symbol").null_count()
            or frame.get_column("trade_date").null_count()
            or frame.get_column("source").null_count()
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if frame.filter(pl.col("trade_date") > coverage.as_of).height:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if frame.select(["symbol", "trade_date"]).n_unique() != frame.height:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if frame.select(["symbol", "trade_date", "source"]).n_unique() != frame.height:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        symbols = frame.get_column("symbol").to_list()
        trade_dates = frame.get_column("trade_date").to_list()
        for symbol in symbols:
            if type(symbol) is not str:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            _require_canonical_symbol(symbol)
        order_keys = list(zip(symbols, trade_dates, strict=True))
        if order_keys != sorted(order_keys):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        count_frame = frame.group_by("symbol", maintain_order=True).agg(pl.len().alias("n"))
        counts = {
            str(symbol): int(count)
            for symbol, count in count_frame.select("symbol", "n").iter_rows()
        }
        if len(counts) != coverage.returned_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if set(counts) & set(coverage.missing_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        requested = coverage.requested_observations
        for count in counts.values():
            if count < 1 or count > requested:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        derived_short = tuple(
            (symbol, counts[symbol]) for symbol in sorted(counts) if counts[symbol] < requested
        )
        if derived_short != coverage.short_symbol_counts:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        short_symbols = {symbol for symbol, _ in coverage.short_symbol_counts}
        for symbol, count in counts.items():
            if symbol not in short_symbols and count != requested:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        observation_values = list(counts.values())
        expected_min = 0 if coverage.missing_symbols else min(observation_values)
        expected_max = max(observation_values)
        if coverage.min_observations != expected_min or coverage.max_observations != expected_max:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        source_frame = frame.group_by("source", maintain_order=False).agg(pl.len().alias("n"))
        derived_sources = tuple(
            (str(source), int(count))
            for source, count in sorted(source_frame.select("source", "n").iter_rows())
        )
        if derived_sources != coverage.source_row_counts:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class AuditedMixedSourceAvailableHistoryBarWindow:
    """Mixed-source result bound to count coverage and exact available-history."""

    frame: pl.DataFrame
    coverage: MixedSourceBarWindowCoverage
    available_history: AvailableHistoryCoverage

    def __post_init__(self) -> None:
        AuditedMixedSourceBarWindow(frame=self.frame, coverage=self.coverage)
        if type(self.available_history) is not AvailableHistoryCoverage:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        available = self.available_history
        if (
            available.universe != self.coverage.universe
            or available.as_of != self.coverage.as_of
            or available.source != self.coverage.source
            or available.requested_observations != self.coverage.requested_observations
            or available.eligible_symbol_count != self.coverage.eligible_symbol_count
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        frame_symbols = (
            set(self.frame.get_column("symbol").to_list()) if self.frame.height else set()
        )
        eligible_symbols = frame_symbols | set(self.coverage.missing_symbols)
        required = dict(available.required_sessions)
        expected_symbols = set(required) | set(available.excluded_etf_symbols)
        if eligible_symbols != expected_symbols:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        missing = dict(available.missing_sessions)
        unexpected = dict(available.unexpected_sessions)
        if self.frame.height:
            for symbol, trade_date in self.frame.select("symbol", "trade_date").iter_rows():
                if symbol not in required:
                    continue
                if trade_date in missing.get(symbol, ()):
                    raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
                if trade_date not in required[symbol] and trade_date not in unexpected.get(
                    symbol, ()
                ):
                    raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")


def _require_positive_int(observations: object) -> int:
    if type(observations) is not int or observations <= 0:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
    return observations


def _coverage_from_counts(
    *,
    universe: str,
    as_of: dt.date,
    source: str,
    requested_observations: int,
    eligible: list[str],
    counts: dict[str, int],
) -> BarWindowCoverage:
    missing_symbols = tuple(symbol for symbol in eligible if counts.get(symbol, 0) == 0)
    short_symbol_counts = tuple(
        (symbol, counts[symbol])
        for symbol in eligible
        if 0 < counts.get(symbol, 0) < requested_observations
    )
    returned_symbol_count = sum(1 for symbol in eligible if counts.get(symbol, 0) > 0)
    observation_values = [counts.get(symbol, 0) for symbol in eligible] or [0]
    return BarWindowCoverage(
        universe=universe,
        as_of=as_of,
        source=source,
        requested_observations=requested_observations,
        eligible_symbol_count=len(eligible),
        returned_symbol_count=returned_symbol_count,
        missing_symbols=missing_symbols,
        short_symbol_counts=short_symbol_counts,
        min_observations=min(observation_values),
        max_observations=max(observation_values),
    )


def _available_history_from_references(
    *,
    frame: pl.DataFrame,
    universe: str,
    as_of: dt.date,
    source: str,
    requested_observations: int,
    eligible_symbol_count: int,
    missing_symbols: tuple[str, ...],
    calendar_path: Path,
    instrument_path: Path,
    eligibility_snapshot_root: Path,
    eligibility_event_root: Path,
    no_trade_evidences: tuple[HKNoTradeEvidence, ...],
    no_trade_evidence_sha256: str | None,
    observed_frame: pl.DataFrame | None = None,
    unexpected_observed_frame: pl.DataFrame | None = None,
) -> AvailableHistoryCoverage:
    if not all(
        isinstance(path, Path)
        for path in (
            calendar_path,
            instrument_path,
            eligibility_snapshot_root,
            eligibility_event_root,
        )
    ):
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if (
        not calendar_path.exists()
        or not instrument_path.exists()
        or not eligibility_snapshot_root.exists()
        or not eligibility_event_root.exists()
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    failure: BarWindowQueryError | None = None
    try:
        validated_calendar = TradeCalendarSchema.validate(pl.read_parquet(calendar_path))
        instruments = InstrumentSchema.validate(pl.read_parquet(instrument_path))
    except Exception:
        failure = BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    if failure is not None:
        raise failure from None
    if (
        validated_calendar.is_empty()
        or validated_calendar.filter(pl.col("market") != Market.HK.value).height
        or instruments.filter(pl.col("market") != Market.HK.value).height
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None

    calendar = cast(
        pl.DataFrame,
        validated_calendar.filter(pl.col("date") <= as_of).sort("date"),
    )
    if calendar.is_empty():
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    calendar_dates = tuple(calendar.get_column("date").to_list())
    first_calendar_date = calendar_dates[0]
    if (
        type(first_calendar_date) is not dt.date
        or len(calendar_dates) != (as_of - first_calendar_date).days + 1
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    open_dates = tuple(calendar.filter(pl.col("is_open")).get_column("date").to_list())
    if not open_dates:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    open_date_set = set(open_dates)

    evidence_by_key = {
        (item.symbol, dt.date.fromisoformat(item.trade_date)): item for item in no_trade_evidences
    }

    missing_observation = frame if observed_frame is None else observed_frame
    unexpected_observation = (
        missing_observation if unexpected_observed_frame is None else unexpected_observed_frame
    )
    frame_symbols = set(frame.get_column("symbol").to_list()) if frame.height else set()
    eligible_symbols = frame_symbols | set(missing_symbols)
    if len(eligible_symbols) != eligible_symbol_count:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    official_types = _load_official_connect_security_types(
        snapshot_root=eligibility_snapshot_root,
        event_root=eligibility_event_root,
        eligible_symbols=eligible_symbols,
    )
    instrument_rows = {
        cast(str, row["symbol"]): row
        for row in instruments.filter(pl.col("symbol").is_in(sorted(eligible_symbols))).iter_rows(
            named=True
        )
    }

    excluded_etfs: list[str] = []
    required_sessions: list[tuple[str, tuple[dt.date, ...]]] = []
    exempted_sessions: list[tuple[str, tuple[dt.date, ...]]] = []
    selected_reasons: Counter[str] = Counter()
    requested = requested_observations
    for symbol in sorted(eligible_symbols):
        row = instrument_rows.get(symbol)
        official_type = official_types.get(symbol)
        if official_type == InstrumentType.ETF.value:
            if row is not None and row["instrument_type"] != InstrumentType.ETF.value:
                raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
            excluded_etfs.append(symbol)
            continue
        if row is None:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        instrument_type = cast(str, row["instrument_type"])
        if official_type == InstrumentType.STOCK.value and instrument_type != official_type:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        list_date = cast(dt.date, row["list_date"])
        delist_date = cast(dt.date | None, row["delist_date"])
        if list_date > as_of or (delist_date is not None and delist_date < as_of):
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        if instrument_type == InstrumentType.ETF.value:
            excluded_etfs.append(symbol)
            continue
        if instrument_type != InstrumentType.STOCK.value:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        if list_date >= first_calendar_date and list_date not in open_date_set:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        available_dates = tuple(date for date in open_dates if date >= list_date)
        if list_date < first_calendar_date and len(available_dates) < requested:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        original_sessions = available_dates[-requested:]
        if not original_sessions:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        exemptions = tuple(date for date in original_sessions if (symbol, date) in evidence_by_key)
        sessions = tuple(date for date in original_sessions if date not in set(exemptions))
        required_sessions.append((symbol, sessions))
        if exemptions:
            exempted_sessions.append((symbol, exemptions))
            selected_reasons.update(evidence_by_key[(symbol, date)].reason for date in exemptions)

    missing_seen: dict[str, set[dt.date]] = {symbol: set() for symbol, _ in required_sessions}
    unexpected_seen: dict[str, set[dt.date]] = {symbol: set() for symbol, _ in required_sessions}
    if missing_observation.height:
        for symbol, trade_date in missing_observation.select("symbol", "trade_date").iter_rows():
            if symbol in missing_seen:
                missing_seen[symbol].add(trade_date)
    if unexpected_observation.height:
        for symbol, trade_date in unexpected_observation.select("symbol", "trade_date").iter_rows():
            if symbol in unexpected_seen:
                unexpected_seen[symbol].add(trade_date)
    missing_sessions = tuple(
        (symbol, tuple(sorted(set(dates) - missing_seen[symbol])))
        for symbol, dates in required_sessions
        if set(dates) - missing_seen[symbol]
    )
    unexpected_sessions = tuple(
        (symbol, tuple(sorted(unexpected_seen[symbol] - set(dates))))
        for symbol, dates in required_sessions
        if unexpected_seen[symbol] - set(dates)
    )
    return AvailableHistoryCoverage(
        universe=universe,
        as_of=as_of,
        source=source,
        requested_observations=requested,
        eligible_symbol_count=eligible_symbol_count,
        excluded_etf_symbols=tuple(excluded_etfs),
        required_sessions=tuple(required_sessions),
        missing_sessions=missing_sessions,
        unexpected_sessions=unexpected_sessions,
        exempted_sessions=tuple(exempted_sessions),
        exemption_reason_counts=tuple(sorted(selected_reasons.items())),
        no_trade_evidence_sha256=(no_trade_evidence_sha256 if exempted_sessions else None),
    )


def _load_no_trade_from_path(
    *,
    no_trade_evidence_path: Path | None,
    no_trade_raw_root: Path | None,
) -> tuple[tuple[HKNoTradeEvidence, ...], str | None]:
    if no_trade_evidence_path is None or not no_trade_evidence_path.exists():
        return (), None
    if no_trade_raw_root is None:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    try:
        evidence_set = load_hk_no_trade_evidence(no_trade_evidence_path, raw_root=no_trade_raw_root)
    except HKHistoryBackfillError:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    return evidence_set.evidences, evidence_set.evidence_set_sha256


def _load_official_connect_security_types(
    *,
    snapshot_root: Path,
    event_root: Path,
    eligible_symbols: set[str],
) -> dict[str, str]:
    """Load conflict-free non-OTHER types from verified Route facts."""
    snapshot_files = sorted(snapshot_root.glob("route=*/date=*/data.parquet"))
    event_files = sorted(event_root.glob("route=*/data.parquet"))
    if not snapshot_files or not event_files:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    failure: BarWindowQueryError | None = None
    try:
        frames = [
            ConnectEligibilitySnapshotSchema.validate(pl.read_parquet(path)).select(
                "symbol", "security_type"
            )
            for path in snapshot_files
        ]
        frames.extend(
            ConnectEligibilityEventSchema.validate(pl.read_parquet(path)).select(
                "symbol", "security_type"
            )
            for path in event_files
        )
    except Exception:
        failure = BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    if failure is not None:
        raise failure from None
    facts = (
        pl.concat(frames)
        .filter(
            pl.col("symbol").is_in(sorted(eligible_symbols)) & (pl.col("security_type") != "OTHER")
        )
        .unique()
    )
    conflicts = (
        facts.group_by("symbol")
        .agg(pl.col("security_type").n_unique().alias("type_count"))
        .filter(pl.col("type_count") != 1)
    )
    if not conflicts.is_empty():
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
    return dict(facts.unique(subset="symbol").select("symbol", "security_type").iter_rows())


def _raise_hk_bar_verify_failed() -> NoReturn:
    raise HKHistoryBackfillError("HK_BAR_VERIFY_FAILED") from None


def _mapping_from_verified_bundle(
    bundle: object, plan: object
) -> tuple[pl.DataFrame, str, str, str]:
    if type(bundle) is not VerifiedHkBarBundle:
        _raise_hk_bar_verify_failed()
    if type(plan) is not HKHistoryPlan:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    if plan.schema_version != HK_HISTORY_SCHEMA_VERSION_V2:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
    failure: str | None = None
    mapping: pl.DataFrame | None = None
    availability_sha: str | None = None
    try:
        if bundle.plan_sha256 != plan.plan_sha256:
            raise ValueError
        availability = bundle.availability
        mapping = availability.select("symbol", "trade_date", "source").sort("symbol", "trade_date")
        if (
            mapping.schema["symbol"] != pl.String
            or mapping.schema["trade_date"] != pl.Date
            or mapping.schema["source"] != pl.String
        ):
            raise ValueError
        if mapping.get_column("source").null_count():
            raise ValueError
        if mapping.select(["symbol", "trade_date"]).n_unique() != mapping.height:
            raise ValueError
        expected = {
            (symbol, dt.date.fromisoformat(date_value))
            for symbol, dates in plan.effective_expected_dates
            for date_value in dates
        }
        actual = set(mapping.select("symbol", "trade_date").iter_rows())
        if actual != expected or mapping.height != len(expected):
            raise ValueError
        availability_sha = _availability_content_sha256(availability)
    except HKHistoryBackfillError:
        raise
    except BarWindowQueryError:
        raise
    except Exception:
        failure = "HK_BAR_VERIFY_FAILED"
    if failure is not None:
        raise HKHistoryBackfillError(failure) from None
    if mapping is None or availability_sha is None:
        _raise_hk_bar_verify_failed()
    return mapping, plan.plan_sha256, bundle.publication_sha256, availability_sha


def _source_row_counts(frame: pl.DataFrame) -> tuple[tuple[str, int], ...]:
    if frame.height == 0:
        return ()
    count_frame = frame.group_by("source", maintain_order=False).agg(pl.len().alias("n"))
    return tuple(
        (str(source), int(count))
        for source, count in sorted(count_frame.select("source", "n").iter_rows())
    )


def _mixed_coverage_from_counts(
    *,
    universe: str,
    as_of: dt.date,
    requested_observations: int,
    eligible: list[str],
    counts: dict[str, int],
    plan_sha256: str,
    publication_sha256: str,
    availability_content_sha256: str,
    source_row_counts: tuple[tuple[str, int], ...],
) -> MixedSourceBarWindowCoverage:
    missing_symbols = tuple(symbol for symbol in eligible if counts.get(symbol, 0) == 0)
    short_symbol_counts = tuple(
        (symbol, counts[symbol])
        for symbol in eligible
        if 0 < counts.get(symbol, 0) < requested_observations
    )
    returned_symbol_count = sum(1 for symbol in eligible if counts.get(symbol, 0) > 0)
    observation_values = [counts.get(symbol, 0) for symbol in eligible] or [0]
    return MixedSourceBarWindowCoverage(
        universe=universe,
        as_of=as_of,
        source=VERIFIED_HK_AVAILABILITY_SOURCE,
        requested_observations=requested_observations,
        eligible_symbol_count=len(eligible),
        returned_symbol_count=returned_symbol_count,
        missing_symbols=missing_symbols,
        short_symbol_counts=short_symbol_counts,
        min_observations=min(observation_values),
        max_observations=max(observation_values),
        plan_sha256=plan_sha256,
        publication_sha256=publication_sha256,
        availability_content_sha256=availability_content_sha256,
        source_row_counts=source_row_counts,
    )


class BarQuery:
    """查询分区化 bar_1d Parquet。"""

    def __init__(self, clean_bar_root: Path) -> None:
        self.clean_bar_root = clean_bar_root

    def recent(
        self,
        *,
        as_of: dt.date,
        observations: int = 60,
        source: str | None = None,
    ) -> pl.DataFrame:
        """返回截至 as_of 每只证券最近 N 个交易观测。"""
        if observations <= 0:
            raise ValueError("observations 必须大于 0")
        files = list(self.clean_bar_root.glob("date=*/data.parquet"))
        if not files:
            return pl.DataFrame()
        parquet_glob = str(self.clean_bar_root / "date=*" / "data.parquet")
        source_filter = "AND source = ?" if source is not None else ""
        sql = f"""
            WITH ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY symbol, source ORDER BY trade_date DESC
                ) AS observation_number
                FROM read_parquet(?)
                WHERE trade_date <= ?
                {source_filter}
            )
            SELECT * EXCLUDE (observation_number)
            FROM ranked
            WHERE observation_number <= ?
            ORDER BY symbol, trade_date
        """
        parameters: list[object] = [parquet_glob, as_of]
        if source is not None:
            parameters.append(source)
        parameters.append(observations)
        with duckdb.connect() as connection:
            table = connection.execute(sql, parameters).to_arrow_table()
        return cast(pl.DataFrame, pl.from_arrow(table))

    def recent_for_universe(
        self,
        *,
        membership_path: Path,
        universe: str,
        as_of: dt.date,
        source: str,
        observations: int = 60,
    ) -> pl.DataFrame:
        """用 as_of 时点有效成员筛选证券，再取每只证券最近 N 个源内观测。

        成员区间只决定 ``as_of`` 时点的证券集合；为计算滚动特征，返回的历史
        行情可以早于证券的 ``effective_from``。逐日持有资格检查属于回测层职责。
        """
        if observations <= 0:
            raise ValueError("observations 必须大于 0")
        if not membership_path.exists():
            raise FileNotFoundError(membership_path)
        files = list(self.clean_bar_root.glob("date=*/data.parquet"))
        if not files:
            return pl.DataFrame()
        sql = """
            WITH eligible AS (
                SELECT DISTINCT symbol
                FROM read_parquet(?)
                WHERE universe = ?
                  AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
            ), ranked AS (
                SELECT bars.*, row_number() OVER (
                    PARTITION BY bars.symbol ORDER BY bars.trade_date DESC
                ) AS observation_number
                FROM read_parquet(?) AS bars
                INNER JOIN eligible USING (symbol)
                WHERE bars.trade_date <= ? AND bars.source = ?
            )
            SELECT * EXCLUDE (observation_number)
            FROM ranked
            WHERE observation_number <= ?
            ORDER BY symbol, trade_date
        """
        parquet_glob = str(self.clean_bar_root / "date=*" / "data.parquet")
        with duckdb.connect() as connection:
            table = connection.execute(
                sql,
                [
                    str(membership_path),
                    universe,
                    as_of,
                    as_of,
                    parquet_glob,
                    as_of,
                    source,
                    observations,
                ],
            ).to_arrow_table()
        return cast(pl.DataFrame, pl.from_arrow(table))

    def recent_for_universe_audited(
        self,
        *,
        membership_path: Path,
        universe: str,
        as_of: dt.date,
        source: str,
        observations: int = 60,
    ) -> AuditedBarWindow:
        """返回 as-of 成员最近 N 个源内观测，并绑定显式 coverage 审计结果。

        成员区间决定 eligible 集合；早于可证明覆盖起点时沿用 eligibility 失败语义。
        无 bar 文件时仍报告全部 eligible 为 missing。目标 source 的
        ``(symbol, trade_date, source)`` 重复键 fail closed，不用去重掩盖。
        """
        requested = _require_positive_int(observations)
        if type(universe) is not str or not universe:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(as_of) is not dt.date:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if type(source) is not str or not source:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if not isinstance(membership_path, Path):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if not membership_path.exists():
            raise FileNotFoundError(membership_path)

        membership = pl.read_parquet(membership_path)
        eligible = eligible_symbols_on(membership, route=universe, as_of=as_of)
        files = sorted(self.clean_bar_root.glob("date=*/data.parquet"))
        if not eligible:
            coverage = _coverage_from_counts(
                universe=universe,
                as_of=as_of,
                source=source,
                requested_observations=requested,
                eligible=eligible,
                counts={},
            )
            return AuditedBarWindow(frame=pl.DataFrame(), coverage=coverage)
        if not files:
            coverage = _coverage_from_counts(
                universe=universe,
                as_of=as_of,
                source=source,
                requested_observations=requested,
                eligible=eligible,
                counts={},
            )
            return AuditedBarWindow(frame=pl.DataFrame(), coverage=coverage)

        parquet_glob = str(self.clean_bar_root / "date=*" / "data.parquet")
        eligible_frame = pl.DataFrame({"symbol": eligible})
        with duckdb.connect() as connection:
            connection.register("eligible_symbols", eligible_frame)
            duplicate = connection.execute(
                """
                SELECT bars.symbol
                FROM read_parquet(?) AS bars
                INNER JOIN eligible_symbols USING (symbol)
                WHERE bars.trade_date <= ? AND bars.source = ?
                GROUP BY bars.symbol, bars.trade_date, bars.source
                HAVING COUNT(*) > 1
                LIMIT 1
                """,
                [parquet_glob, as_of, source],
            ).fetchone()
            if duplicate is not None:
                raise BarWindowQueryError("BAR_WINDOW_DUPLICATE_KEY")
            table = connection.execute(
                """
                WITH ranked AS (
                    SELECT bars.*, row_number() OVER (
                        PARTITION BY bars.symbol ORDER BY bars.trade_date DESC
                    ) AS observation_number
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    WHERE bars.trade_date <= ? AND bars.source = ?
                )
                SELECT * EXCLUDE (observation_number)
                FROM ranked
                WHERE observation_number <= ?
                ORDER BY symbol, trade_date
                """,
                [parquet_glob, as_of, source, requested],
            ).to_arrow_table()
        frame = cast(pl.DataFrame, pl.from_arrow(table))
        if frame.height == 0:
            counts: dict[str, int] = {}
        else:
            if "source" in frame.columns and frame.filter(pl.col("source") != source).height:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            count_frame = frame.group_by("symbol", maintain_order=True).agg(pl.len().alias("n"))
            counts = {
                str(symbol): int(count)
                for symbol, count in count_frame.select("symbol", "n").iter_rows()
            }
            if any(count > requested for count in counts.values()):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
            if any(symbol not in set(eligible) for symbol in counts):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        coverage = _coverage_from_counts(
            universe=universe,
            as_of=as_of,
            source=source,
            requested_observations=requested,
            eligible=eligible,
            counts=counts,
        )
        return AuditedBarWindow(frame=frame, coverage=coverage)

    def recent_for_universe_available_history_audited(
        self,
        *,
        membership_path: Path,
        calendar_path: Path,
        instrument_path: Path,
        eligibility_snapshot_root: Path,
        eligibility_event_root: Path,
        no_trade_evidence_path: Path | None = None,
        no_trade_raw_root: Path | None = None,
        universe: str,
        as_of: dt.date,
        source: str,
        observations: int = 60,
    ) -> AuditedAvailableHistoryBarWindow:
        """Return a universe window with an exact listed-history coverage audit."""
        audited = self.recent_for_universe_audited(
            membership_path=membership_path,
            universe=universe,
            as_of=as_of,
            source=source,
            observations=observations,
        )
        return self.audit_available_history(
            audited=audited,
            calendar_path=calendar_path,
            instrument_path=instrument_path,
            eligibility_snapshot_root=eligibility_snapshot_root,
            eligibility_event_root=eligibility_event_root,
            no_trade_evidence_path=no_trade_evidence_path,
            no_trade_raw_root=no_trade_raw_root,
        )

    def audit_available_history(
        self,
        *,
        audited: AuditedBarWindow,
        calendar_path: Path,
        instrument_path: Path,
        eligibility_snapshot_root: Path,
        eligibility_event_root: Path,
        no_trade_evidence_path: Path | None = None,
        no_trade_raw_root: Path | None = None,
    ) -> AuditedAvailableHistoryBarWindow:
        """Bind trusted HK references and exact available-history evidence."""
        if type(audited) is not AuditedBarWindow:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        evidences, evidence_sha256 = _load_no_trade_from_path(
            no_trade_evidence_path=no_trade_evidence_path,
            no_trade_raw_root=no_trade_raw_root,
        )
        available_history = _available_history_from_references(
            frame=audited.frame,
            universe=audited.coverage.universe,
            as_of=audited.coverage.as_of,
            source=audited.coverage.source,
            requested_observations=audited.coverage.requested_observations,
            eligible_symbol_count=audited.coverage.eligible_symbol_count,
            missing_symbols=audited.coverage.missing_symbols,
            calendar_path=calendar_path,
            instrument_path=instrument_path,
            eligibility_snapshot_root=eligibility_snapshot_root,
            eligibility_event_root=eligibility_event_root,
            no_trade_evidences=evidences,
            no_trade_evidence_sha256=evidence_sha256,
        )
        return AuditedAvailableHistoryBarWindow(
            frame=audited.frame,
            coverage=audited.coverage,
            available_history=available_history,
        )

    def recent_for_universe_mixed_audited(
        self,
        *,
        membership_path: Path,
        universe: str,
        as_of: dt.date,
        observations: int,
        bundle: VerifiedHkBarBundle,
        plan: HKHistoryPlan,
    ) -> AuditedMixedSourceBarWindow:
        """Return last-N bars using the unique source mapping from a verified bundle."""
        requested = _require_positive_int(observations)
        if type(universe) is not str or not universe:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if type(as_of) is not dt.date:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if not isinstance(membership_path, Path):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if type(plan) is not HKHistoryPlan:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if dt.date.fromisoformat(plan.as_of) != as_of:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        mapping, plan_sha256, publication_sha256, availability_sha = _mapping_from_verified_bundle(
            bundle, plan
        )
        if not membership_path.exists():
            raise FileNotFoundError(membership_path)
        eligible = eligible_symbols_on(
            pl.read_parquet(membership_path), route=universe, as_of=as_of
        )
        files = sorted(self.clean_bar_root.glob("date=*/data.parquet"))
        if not eligible or not files:
            coverage = _mixed_coverage_from_counts(
                universe=universe,
                as_of=as_of,
                requested_observations=requested,
                eligible=eligible,
                counts={},
                plan_sha256=plan_sha256,
                publication_sha256=publication_sha256,
                availability_content_sha256=availability_sha,
                source_row_counts=(),
            )
            return AuditedMixedSourceBarWindow(frame=pl.DataFrame(), coverage=coverage)
        frame = self._select_mapped_recent_n(
            mapping=mapping,
            eligible=eligible,
            as_of=as_of,
            requested=requested,
        )
        if frame.height == 0:
            counts: dict[str, int] = {}
        else:
            if frame.select(["symbol", "trade_date"]).n_unique() != frame.height:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
            count_frame = frame.group_by("symbol", maintain_order=True).agg(pl.len().alias("n"))
            counts = {
                str(symbol): int(count)
                for symbol, count in count_frame.select("symbol", "n").iter_rows()
            }
            if any(count > requested for count in counts.values()):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
            if any(symbol not in set(eligible) for symbol in counts):
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
            joined = frame.join(mapping, on=["symbol", "trade_date", "source"], how="inner")
            if joined.height != frame.height:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        coverage = _mixed_coverage_from_counts(
            universe=universe,
            as_of=as_of,
            requested_observations=requested,
            eligible=eligible,
            counts=counts,
            plan_sha256=plan_sha256,
            publication_sha256=publication_sha256,
            availability_content_sha256=availability_sha,
            source_row_counts=_source_row_counts(frame),
        )
        return AuditedMixedSourceBarWindow(frame=frame, coverage=coverage)

    def audit_available_history_mixed(
        self,
        *,
        audited: AuditedMixedSourceBarWindow,
        calendar_path: Path,
        instrument_path: Path,
        eligibility_snapshot_root: Path,
        eligibility_event_root: Path,
        no_trade_evidences: tuple[HKNoTradeEvidence, ...],
        no_trade_evidence_sha256: str,
    ) -> AuditedMixedSourceAvailableHistoryBarWindow:
        """Audit mixed-source exact sessions using plan-embedded no-trade evidence."""
        if type(audited) is not AuditedMixedSourceBarWindow:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if type(no_trade_evidences) is not tuple:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        for item in no_trade_evidences:
            if type(item) is not HKNoTradeEvidence:
                raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if (
            type(no_trade_evidence_sha256) is not str
            or _HEX64_RE.fullmatch(no_trade_evidence_sha256) is None
        ):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID") from None
        if no_trade_evidences and _evidence_set_sha256(no_trade_evidences) != (
            no_trade_evidence_sha256
        ):
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
        unexpected_observed = self._physical_last_n(
            eligible_symbols=(
                set(audited.frame.get_column("symbol").to_list()) if audited.frame.height else set()
            )
            | set(audited.coverage.missing_symbols),
            as_of=audited.coverage.as_of,
            requested=audited.coverage.requested_observations,
        )
        available_history = _available_history_from_references(
            frame=audited.frame,
            universe=audited.coverage.universe,
            as_of=audited.coverage.as_of,
            source=audited.coverage.source,
            requested_observations=audited.coverage.requested_observations,
            eligible_symbol_count=audited.coverage.eligible_symbol_count,
            missing_symbols=audited.coverage.missing_symbols,
            calendar_path=calendar_path,
            instrument_path=instrument_path,
            eligibility_snapshot_root=eligibility_snapshot_root,
            eligibility_event_root=eligibility_event_root,
            no_trade_evidences=no_trade_evidences,
            no_trade_evidence_sha256=no_trade_evidence_sha256,
            observed_frame=audited.frame,
            unexpected_observed_frame=unexpected_observed,
        )
        return AuditedMixedSourceAvailableHistoryBarWindow(
            frame=audited.frame,
            coverage=audited.coverage,
            available_history=available_history,
        )

    def _select_mapped_recent_n(
        self,
        *,
        mapping: pl.DataFrame,
        eligible: list[str],
        as_of: dt.date,
        requested: int,
    ) -> pl.DataFrame:
        parquet_glob = str(self.clean_bar_root / "date=*" / "data.parquet")
        eligible_frame = pl.DataFrame({"symbol": eligible})
        failure: BarWindowQueryError | None = None
        try:
            with duckdb.connect() as connection:
                connection.register("eligible_symbols", eligible_frame)
                connection.register("source_mapping", mapping)
                duplicate = connection.execute(
                    """
                    SELECT 1
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    INNER JOIN source_mapping AS mapping
                      ON bars.symbol = mapping.symbol
                     AND bars.trade_date = mapping.trade_date
                    WHERE bars.trade_date <= ?
                    GROUP BY bars.symbol, bars.trade_date, bars.source
                    HAVING COUNT(*) > 1
                    LIMIT 1
                    """,
                    [parquet_glob, as_of],
                ).fetchone()
                if duplicate is not None:
                    raise BarWindowQueryError("BAR_WINDOW_DUPLICATE_KEY") from None
                multi_source = connection.execute(
                    """
                    SELECT 1
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    INNER JOIN source_mapping AS mapping
                      ON bars.symbol = mapping.symbol
                     AND bars.trade_date = mapping.trade_date
                    WHERE bars.trade_date <= ?
                    GROUP BY bars.symbol, bars.trade_date
                    HAVING COUNT(DISTINCT bars.source) > 1
                    LIMIT 1
                    """,
                    [parquet_glob, as_of],
                ).fetchone()
                if multi_source is not None:
                    raise BarWindowQueryError("BAR_WINDOW_DUPLICATE_KEY") from None
                wrong_source = connection.execute(
                    """
                    SELECT 1
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    INNER JOIN source_mapping AS mapping
                      ON bars.symbol = mapping.symbol
                     AND bars.trade_date = mapping.trade_date
                    WHERE bars.trade_date <= ?
                      AND bars.source != mapping.source
                    LIMIT 1
                    """,
                    [parquet_glob, as_of],
                ).fetchone()
                if wrong_source is not None:
                    raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from None
                table = connection.execute(
                    """
                    WITH ranked AS (
                        SELECT bars.*, row_number() OVER (
                            PARTITION BY bars.symbol ORDER BY bars.trade_date DESC
                        ) AS observation_number
                        FROM read_parquet(?) AS bars
                        INNER JOIN eligible_symbols USING (symbol)
                        INNER JOIN source_mapping AS mapping
                          ON bars.symbol = mapping.symbol
                         AND bars.trade_date = mapping.trade_date
                         AND bars.source = mapping.source
                        WHERE bars.trade_date <= ?
                    )
                    SELECT * EXCLUDE (observation_number)
                    FROM ranked
                    WHERE observation_number <= ?
                    ORDER BY symbol, trade_date
                    """,
                    [parquet_glob, as_of, requested],
                ).to_arrow_table()
        except BarWindowQueryError as exc:
            failure = exc
        except Exception:
            failure = BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        if failure is not None:
            raise failure from None
        return cast(pl.DataFrame, pl.from_arrow(table))

    def _physical_last_n(
        self,
        *,
        eligible_symbols: set[str],
        as_of: dt.date,
        requested: int,
    ) -> pl.DataFrame:
        files = sorted(self.clean_bar_root.glob("date=*/data.parquet"))
        if not eligible_symbols or not files:
            return pl.DataFrame()
        parquet_glob = str(self.clean_bar_root / "date=*" / "data.parquet")
        eligible_frame = pl.DataFrame({"symbol": sorted(eligible_symbols)})
        failure: BarWindowQueryError | None = None
        try:
            with duckdb.connect() as connection:
                connection.register("eligible_symbols", eligible_frame)
                duplicate = connection.execute(
                    """
                    SELECT 1
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    WHERE bars.trade_date <= ?
                    GROUP BY bars.symbol, bars.trade_date, bars.source
                    HAVING COUNT(*) > 1
                    LIMIT 1
                    """,
                    [parquet_glob, as_of],
                ).fetchone()
                if duplicate is not None:
                    raise BarWindowQueryError("BAR_WINDOW_DUPLICATE_KEY") from None
                multi_source = connection.execute(
                    """
                    SELECT 1
                    FROM read_parquet(?) AS bars
                    INNER JOIN eligible_symbols USING (symbol)
                    WHERE bars.trade_date <= ?
                    GROUP BY bars.symbol, bars.trade_date
                    HAVING COUNT(DISTINCT bars.source) > 1
                    LIMIT 1
                    """,
                    [parquet_glob, as_of],
                ).fetchone()
                if multi_source is not None:
                    raise BarWindowQueryError("BAR_WINDOW_DUPLICATE_KEY") from None
                table = connection.execute(
                    """
                    WITH ranked AS (
                        SELECT bars.*, row_number() OVER (
                            PARTITION BY bars.symbol ORDER BY bars.trade_date DESC
                        ) AS observation_number
                        FROM read_parquet(?) AS bars
                        INNER JOIN eligible_symbols USING (symbol)
                        WHERE bars.trade_date <= ?
                    )
                    SELECT * EXCLUDE (observation_number)
                    FROM ranked
                    WHERE observation_number <= ?
                    ORDER BY symbol, trade_date
                    """,
                    [parquet_glob, as_of, requested],
                ).to_arrow_table()
        except BarWindowQueryError as exc:
            failure = exc
        except Exception:
            failure = BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        if failure is not None:
            raise failure from None
        return cast(pl.DataFrame, pl.from_arrow(table))
