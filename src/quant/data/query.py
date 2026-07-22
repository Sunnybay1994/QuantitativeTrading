"""基于 DuckDB 的 clean 数据查询。"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import polars as pl

from quant.data.eligibility import eligible_symbols_on
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

        required = self._validate_session_items(self.required_sessions, allow_empty_dates=False)
        missing = self._validate_session_items(self.missing_sessions, allow_empty_dates=False)
        unexpected = self._validate_session_items(self.unexpected_sessions, allow_empty_dates=False)
        required_symbols = set(required)
        if required_symbols & set(self.excluded_etf_symbols):
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if len(required_symbols) + len(self.excluded_etf_symbols) != self.eligible_symbol_count:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        if not set(missing).issubset(required_symbols) or not set(unexpected).issubset(
            required_symbols
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
    audited: AuditedBarWindow,
    calendar_path: Path,
    instrument_path: Path,
    eligibility_snapshot_root: Path,
    eligibility_event_root: Path,
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
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
    if (
        not calendar_path.exists()
        or not instrument_path.exists()
        or not eligibility_snapshot_root.exists()
        or not eligibility_event_root.exists()
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    try:
        validated_calendar = TradeCalendarSchema.validate(pl.read_parquet(calendar_path))
        instruments = InstrumentSchema.validate(pl.read_parquet(instrument_path))
    except Exception as exc:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from exc
    if (
        validated_calendar.is_empty()
        or validated_calendar.filter(pl.col("market") != Market.HK.value).height
        or instruments.filter(pl.col("market") != Market.HK.value).height
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")

    calendar = cast(
        pl.DataFrame,
        validated_calendar.filter(pl.col("date") <= audited.coverage.as_of).sort("date"),
    )
    if calendar.is_empty():
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    calendar_dates = tuple(calendar.get_column("date").to_list())
    first_calendar_date = calendar_dates[0]
    if (
        type(first_calendar_date) is not dt.date
        or len(calendar_dates) != (audited.coverage.as_of - first_calendar_date).days + 1
    ):
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    open_dates = tuple(calendar.filter(pl.col("is_open")).get_column("date").to_list())
    if not open_dates:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    open_date_set = set(open_dates)

    frame_symbols = (
        set(audited.frame.get_column("symbol").to_list()) if audited.frame.height else set()
    )
    eligible_symbols = frame_symbols | set(audited.coverage.missing_symbols)
    if len(eligible_symbols) != audited.coverage.eligible_symbol_count:
        raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
    official_types = _load_official_connect_security_types(
        snapshot_root=eligibility_snapshot_root,
        event_root=eligibility_event_root,
        eligible_symbols=eligible_symbols,
    )
    instrument_rows = {
        cast(str, row["symbol"]): row
        for row in instruments.filter(
            pl.col("symbol").is_in(sorted(eligible_symbols))
        ).iter_rows(named=True)
    }

    excluded_etfs: list[str] = []
    required_sessions: list[tuple[str, tuple[dt.date, ...]]] = []
    requested = audited.coverage.requested_observations
    as_of = audited.coverage.as_of
    for symbol in sorted(eligible_symbols):
        row = instrument_rows.get(symbol)
        official_type = official_types.get(symbol)
        if official_type == InstrumentType.ETF.value:
            if row is not None and row["instrument_type"] != InstrumentType.ETF.value:
                raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
            excluded_etfs.append(symbol)
            continue
        if row is None:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        instrument_type = cast(str, row["instrument_type"])
        if official_type == InstrumentType.STOCK.value and instrument_type != official_type:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        list_date = cast(dt.date, row["list_date"])
        delist_date = cast(dt.date | None, row["delist_date"])
        if list_date > as_of or (delist_date is not None and delist_date < as_of):
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        if instrument_type == InstrumentType.ETF.value:
            excluded_etfs.append(symbol)
            continue
        if instrument_type != InstrumentType.STOCK.value:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        if list_date >= first_calendar_date and list_date not in open_date_set:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        available_dates = tuple(date for date in open_dates if date >= list_date)
        if list_date < first_calendar_date and len(available_dates) < requested:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        sessions = available_dates[-requested:]
        if not sessions:
            raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
        required_sessions.append((symbol, sessions))

    observed: dict[str, set[dt.date]] = {symbol: set() for symbol, _ in required_sessions}
    if audited.frame.height:
        for symbol, trade_date in audited.frame.select("symbol", "trade_date").iter_rows():
            if symbol in observed:
                observed[symbol].add(trade_date)
    missing_sessions = tuple(
        (symbol, tuple(sorted(set(dates) - observed[symbol])))
        for symbol, dates in required_sessions
        if set(dates) - observed[symbol]
    )
    unexpected_sessions = tuple(
        (symbol, tuple(sorted(observed[symbol] - set(dates))))
        for symbol, dates in required_sessions
        if observed[symbol] - set(dates)
    )
    return AvailableHistoryCoverage(
        universe=audited.coverage.universe,
        as_of=as_of,
        source=audited.coverage.source,
        requested_observations=requested,
        eligible_symbol_count=audited.coverage.eligible_symbol_count,
        excluded_etf_symbols=tuple(excluded_etfs),
        required_sessions=tuple(required_sessions),
        missing_sessions=missing_sessions,
        unexpected_sessions=unexpected_sessions,
    )


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
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
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
    except Exception as exc:
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID") from exc
    facts = (
        pl.concat(frames)
        .filter(
            pl.col("symbol").is_in(sorted(eligible_symbols))
            & (pl.col("security_type") != "OTHER")
        )
        .unique()
    )
    conflicts = (
        facts.group_by("symbol")
        .agg(pl.col("security_type").n_unique().alias("type_count"))
        .filter(pl.col("type_count") != 1)
    )
    if not conflicts.is_empty():
        raise BarWindowQueryError("BAR_WINDOW_REFERENCE_INVALID")
    return dict(
        facts.unique(subset="symbol").select("symbol", "security_type").iter_rows()
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
        )

    def audit_available_history(
        self,
        *,
        audited: AuditedBarWindow,
        calendar_path: Path,
        instrument_path: Path,
        eligibility_snapshot_root: Path,
        eligibility_event_root: Path,
    ) -> AuditedAvailableHistoryBarWindow:
        """Bind trusted HK references and exact available-history evidence."""
        if type(audited) is not AuditedBarWindow:
            raise BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")
        available_history = _available_history_from_references(
            audited=audited,
            calendar_path=calendar_path,
            instrument_path=instrument_path,
            eligibility_snapshot_root=eligibility_snapshot_root,
            eligibility_event_root=eligibility_event_root,
        )
        return AuditedAvailableHistoryBarWindow(
            frame=audited.frame,
            coverage=audited.coverage,
            available_history=available_history,
        )
