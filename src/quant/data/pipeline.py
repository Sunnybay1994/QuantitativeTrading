"""日线数据 raw → clean 的最小编排。"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from typing import Protocol

import polars as pl

from quant.data.adjustments import apply_adjustment_factors
from quant.data.base import BaseConnector
from quant.data.mappers import (
    AdjustmentFactorMapper,
    BarMapper,
    CalendarMapper,
    InstrumentMapper,
    HkexEtpInstrumentMapper,
)
from quant.data.quality import BarQualityReport, QualityGateError, validate_bars, write_quality_report
from quant.data.storage import (
    CleanBarStore,
    CleanCalendarStore,
    CleanAdjustmentFactorStore,
    CleanInstrumentStore,
    RawSnapshot,
    RawStore,
)
from quant.data.temporary_instruments import (
    HkexTemporaryCounterNotice,
    project_temporary_instruments,
    temporary_counter_raw_frame,
)


@dataclass(frozen=True)
class BarUpdateResult:
    """一次日线更新的可追溯结果。"""

    raw_snapshot: RawSnapshot
    quality_report: BarQualityReport
    clean_rows: int
    factor_snapshot: RawSnapshot | None = None
    factor_rows: int = 0


class BarUpdatePipeline:
    """抓取、raw 留档、映射、门禁和 clean 幂等写入。"""

    def __init__(
        self,
        *,
        connector: BaseConnector,
        mapper: BarMapper,
        raw_store: RawStore,
        clean_store: CleanBarStore,
        quality_root: Path,
        factor_mapper: AdjustmentFactorMapper | None = None,
        factor_store: CleanAdjustmentFactorStore | None = None,
    ) -> None:
        self.connector = connector
        self.mapper = mapper
        self.raw_store = raw_store
        self.clean_store = clean_store
        self.quality_root = quality_root
        self.factor_mapper = factor_mapper
        self.factor_store = factor_store
        if connector.source != mapper.source:
            raise ValueError(
                f"连接器与映射器来源不一致: {connector.source} != {mapper.source}"
            )
        if (factor_mapper is None) != (factor_store is None):
            raise ValueError("factor_mapper 与 factor_store 必须同时提供")
        if factor_mapper is not None:
            _ensure_same_source(connector.source, factor_mapper.source)

    def update(
        self,
        *,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        fetched_at: dt.datetime | None = None,
        expected_dates: set[dt.date] | None = None,
        missing_rate_limit: float = 0.0,
    ) -> BarUpdateResult:
        """执行一次更新；质量失败时 raw 保留但 clean 不写入。"""
        raw = self.connector.fetch_bar_1d(symbols, start, end)
        snapshot = self.raw_store.write(
            source=self.connector.source,
            table="bar_1d",
            frame=raw,
            parameters={
                "symbols": symbols,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            fetched_at=fetched_at,
        )
        clean = self.mapper.map(raw)
        factor_snapshot: RawSnapshot | None = None
        factors: pl.DataFrame | None = None
        factor_rows = 0
        if self.factor_mapper is not None and self.factor_store is not None:
            factor_start = dt.date(1990, 1, 1)
            factor_raw = self.connector.fetch_adjust_factors(symbols, factor_start, end)
            factor_snapshot = self.raw_store.write(
                source=self.connector.source,
                table="adjust_factor",
                frame=factor_raw,
                parameters={
                    "symbols": symbols,
                    "start": factor_start.isoformat(),
                    "end": end.isoformat(),
                    "factor_type": "cumulative_backward",
                },
                fetched_at=fetched_at,
            )
            factors = self.factor_mapper.map(factor_raw)
            # coverage preflight 在 apply 内全局 fail-closed；通过前不写任一 clean store
            clean = apply_adjustment_factors(clean, factors)
        report_path = self.quality_root / f"{snapshot.snapshot_id}.json"
        try:
            report = validate_bars(
                clean,
                expected_dates=expected_dates,
                expected_symbols=set(symbols),
                missing_rate_limit=missing_rate_limit,
            )
        except QualityGateError as exc:
            write_quality_report(exc.report, report_path)
            raise
        write_quality_report(report, report_path)
        if factors is not None and self.factor_store is not None:
            factor_rows = self.factor_store.upsert(factors)
        rows = self.clean_store.upsert(clean)
        return BarUpdateResult(snapshot, report, rows, factor_snapshot, factor_rows)


@dataclass(frozen=True)
class MarketDataUpdateResult:
    """一次市场基础数据更新结果。"""

    raw_snapshot: RawSnapshot
    clean_rows: int


class CalendarUpdatePipeline:
    """交易日历 raw → clean 编排。"""

    def __init__(
        self,
        *,
        connector: BaseConnector,
        mapper: CalendarMapper,
        raw_store: RawStore,
        clean_store: CleanCalendarStore,
        clean_transform: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
    ) -> None:
        _ensure_same_source(connector.source, mapper.source)
        self.connector = connector
        self.mapper = mapper
        self.raw_store = raw_store
        self.clean_store = clean_store
        self.clean_transform = clean_transform

    def update(
        self, *, market: str, start: dt.date, end: dt.date
    ) -> MarketDataUpdateResult:
        raw = self.connector.fetch_trade_calendar(market, start, end)
        snapshot = self.raw_store.write(
            source=self.connector.source,
            table="trade_calendar",
            frame=raw,
            parameters={"market": market, "start": start.isoformat(), "end": end.isoformat()},
        )
        clean = self.mapper.map(raw)
        if self.clean_transform is not None:
            clean = self.clean_transform(clean)
        return MarketDataUpdateResult(snapshot, self.clean_store.upsert(clean))


class InstrumentUpdatePipeline:
    """证券主表 raw → clean 编排。"""

    def __init__(
        self,
        *,
        connector: BaseConnector,
        mapper: InstrumentMapper,
        raw_store: RawStore,
        clean_store: CleanInstrumentStore,
    ) -> None:
        _ensure_same_source(connector.source, mapper.source)
        self.connector = connector
        self.mapper = mapper
        self.raw_store = raw_store
        self.clean_store = clean_store

    def update(self, *, market: str) -> MarketDataUpdateResult:
        raw = self.connector.fetch_instruments(market)
        snapshot = self.raw_store.write(
            source=self.connector.source,
            table="instrument",
            frame=raw,
            parameters={"market": market},
        )
        clean = self.mapper.map(raw)
        return MarketDataUpdateResult(snapshot, self.clean_store.upsert(clean))


class HkexEtpConnectorProtocol(Protocol):
    """Narrow protocol for the HKEX ETP reference endpoint."""

    source: str

    def fetch_etp_instruments(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> pl.DataFrame: ...


class HkexEtpInstrumentUpdatePipeline:
    """Fetch, preserve and publish an exact as-of HKEX ETF reference set."""

    def __init__(
        self,
        *,
        connector: HkexEtpConnectorProtocol,
        mapper: HkexEtpInstrumentMapper,
        raw_store: RawStore,
        clean_store: CleanInstrumentStore,
    ) -> None:
        _ensure_same_source(connector.source, mapper.source)
        self.connector = connector
        self.mapper = mapper
        self.raw_store = raw_store
        self.clean_store = clean_store

    def update(
        self, *, target_symbols: tuple[str, ...], as_of: dt.date
    ) -> MarketDataUpdateResult:
        if target_symbols != self.mapper.target_symbols or as_of != self.mapper.as_of:
            raise ValueError("HKEX_ETP_TARGETS_INVALID")
        raw = self.connector.fetch_etp_instruments(
            target_symbols=target_symbols, as_of=as_of
        )
        snapshot = self.raw_store.write(
            source=self.connector.source,
            table="instrument_etp",
            frame=raw,
            parameters={
                "as_of": as_of.isoformat(),
                "target_symbols": list(target_symbols),
                "page_url": (
                    "https://www.hkex.com.hk/Market-Data/Securities-Prices/"
                    "Exchange-Traded-Products?sc_lang=en"
                ),
                "endpoint_url": (
                    "https://www1.hkex.com.hk/hkexwidget/data/getetpexportdata"
                ),
                "selection_rule": "latest_trade_date_lte_as_of_v1",
            },
        )
        clean = self.mapper.map(raw)
        return MarketDataUpdateResult(snapshot, self.clean_store.upsert(clean))


class HkexTemporaryInstrumentUpdatePipeline:
    """Preserve versioned temporary-counter facts and publish an as-of projection."""

    def __init__(self, *, raw_store: RawStore, clean_store: CleanInstrumentStore) -> None:
        self.raw_store = raw_store
        self.clean_store = clean_store

    def update(
        self,
        *,
        notice: HkexTemporaryCounterNotice,
        target_symbols: tuple[str, ...],
        as_of: dt.date,
    ) -> MarketDataUpdateResult:
        raw = temporary_counter_raw_frame(notice)
        snapshot = self.raw_store.write(
            source="hkex",
            table="instrument_temporary_counter_notice",
            frame=raw,
            parameters={
                "as_of": as_of.isoformat(),
                "target_symbols": list(target_symbols),
                "notice_version": notice.version,
                "selection_rule": notice.selection_rule,
                "evidence_sha256": sorted(
                    item.content_sha256 for item in notice.evidence
                ),
            },
        )
        clean = project_temporary_instruments(
            notice, target_symbols=target_symbols, as_of=as_of
        )
        return MarketDataUpdateResult(snapshot, self.clean_store.upsert(clean))


def _ensure_same_source(connector_source: str, mapper_source: str) -> None:
    if connector_source != mapper_source:
        raise ValueError(f"连接器与映射器来源不一致: {connector_source} != {mapper_source}")
