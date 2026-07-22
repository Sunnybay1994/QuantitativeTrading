"""研究专用后复权价格的 raw→clean 编排与质量门禁。"""

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from quant.data.storage import CleanResearchPriceStore, RawSnapshot, RawStore
from quant.domain import ResearchPrice1dSchema


class ResearchPriceConnector(Protocol):
    source: str

    def fetch_research_price_1d(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        *,
        adjustment: str = "hfq",
    ) -> pl.DataFrame: ...


class ResearchPriceMapper(Protocol):
    source: str

    def map(self, raw: pl.DataFrame) -> pl.DataFrame: ...


@dataclass(frozen=True)
class ResearchPriceQualityReport:
    rows: int
    expected_rows: int
    missing_rows: int
    duplicate_rows: int
    null_rows: int
    invalid_price_rows: int
    passed: bool


class ResearchPriceQualityError(ValueError):
    def __init__(self, report: ResearchPriceQualityReport) -> None:
        self.report = report
        super().__init__(f"研究价格质量门禁失败: {asdict(report)}")


@dataclass(frozen=True)
class ResearchPriceUpdateResult:
    raw_snapshot: RawSnapshot
    quality_report: ResearchPriceQualityReport
    clean_rows: int


class ResearchPriceUpdatePipeline:
    """后复权研究价格采集、留档、校验与幂等发布。"""

    def __init__(
        self,
        *,
        connector: ResearchPriceConnector,
        mapper: ResearchPriceMapper,
        raw_store: RawStore,
        clean_store: CleanResearchPriceStore,
        quality_root: Path,
    ) -> None:
        if connector.source != mapper.source:
            raise ValueError("研究价格连接器与 mapper 来源不一致")
        self.connector = connector
        self.mapper = mapper
        self.raw_store = raw_store
        self.clean_store = clean_store
        self.quality_root = quality_root

    def update(
        self,
        *,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        expected_dates: set[dt.date],
    ) -> ResearchPriceUpdateResult:
        raw = self.connector.fetch_research_price_1d(
            symbols, start, end, adjustment="hfq"
        )
        snapshot = self.raw_store.write(
            source=self.connector.source,
            table="research_price_1d",
            frame=raw,
            parameters={
                "symbols": symbols,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "hfq",
                "usage": "research_only",
            },
        )
        clean = self.mapper.map(raw)
        report = validate_research_prices(
            clean, expected_symbols=set(symbols), expected_dates=expected_dates
        )
        report_path = self.quality_root / f"{snapshot.snapshot_id}.json"
        write_research_price_report(report, report_path)
        if not report.passed:
            raise ResearchPriceQualityError(report)
        validated = ResearchPrice1dSchema.validate(clean)
        return ResearchPriceUpdateResult(
            snapshot, report, self.clean_store.upsert(validated)
        )


def validate_research_prices(
    frame: pl.DataFrame,
    *,
    expected_symbols: set[str],
    expected_dates: set[dt.date],
) -> ResearchPriceQualityReport:
    required = {"symbol", "trade_date", "adjusted_close"}
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise ValueError(f"研究价格缺少字段: {', '.join(missing_columns)}")
    duplicate_rows = int(
        frame.select("symbol", "trade_date").is_duplicated().sum()
    )
    null_rows = frame.filter(pl.any_horizontal(pl.all().is_null())).height
    invalid_price_rows = frame.filter(
        pl.col("adjusted_close").is_null()
        | ~pl.col("adjusted_close").is_finite()
        | (pl.col("adjusted_close") <= 0)
    ).height
    actual = set(frame.select("symbol", "trade_date").iter_rows())
    expected = {
        (symbol, date) for symbol in expected_symbols for date in expected_dates
    }
    missing_rows = len(expected - actual)
    expected_rows = len(expected)
    passed = not any((missing_rows, duplicate_rows, null_rows, invalid_price_rows))
    return ResearchPriceQualityReport(
        rows=frame.height,
        expected_rows=expected_rows,
        missing_rows=missing_rows,
        duplicate_rows=duplicate_rows,
        null_rows=null_rows,
        invalid_price_rows=invalid_price_rows,
        passed=passed,
    )


def write_research_price_report(
    report: ResearchPriceQualityReport, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
