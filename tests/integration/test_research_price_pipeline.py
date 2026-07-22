import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.mappers import AkshareResearchPriceMapper
from quant.data.research_price import (
    ResearchPriceQualityError,
    ResearchPriceUpdatePipeline,
)
from quant.data.storage import CleanResearchPriceStore, RawStore


class FixtureResearchPriceConnector:
    source = "akshare"

    def __init__(self, *, omit_last: bool = False) -> None:
        self.omit_last = omit_last

    def fetch_research_price_1d(
        self,
        symbols: list[str],
        start: dt.date,
        end: dt.date,
        *,
        adjustment: str = "hfq",
    ) -> pl.DataFrame:
        rows = [
            {
                "_request_symbol": symbol,
                "_adjustment": adjustment,
                "_endpoint": "fixture",
                "日期": date,
                "收盘": 4.0 + index / 100,
            }
            for symbol in symbols
            for index, date in enumerate((start, end))
        ]
        if self.omit_last:
            rows.pop()
        return pl.DataFrame(rows)


def pipeline(tmp_path: Path, *, omit_last: bool = False) -> ResearchPriceUpdatePipeline:
    return ResearchPriceUpdatePipeline(
        connector=FixtureResearchPriceConnector(omit_last=omit_last),
        mapper=AkshareResearchPriceMapper(),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=CleanResearchPriceStore(
            tmp_path / "data" / "clean" / "research_price_1d"
        ),
        quality_root=tmp_path / "artifacts" / "data_quality" / "research_price_1d",
    )


def test_research_price_pipeline_archives_validates_and_upserts(tmp_path: Path):
    dates = {dt.date(2026, 7, 9), dt.date(2026, 7, 10)}
    result = pipeline(tmp_path).update(
        symbols=["510300.SH", "159919.SZ"],
        start=min(dates),
        end=max(dates),
        expected_dates=dates,
    )
    assert result.clean_rows == 4
    assert result.quality_report.passed
    clean = pl.read_parquet(
        tmp_path / "data" / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    )
    assert clean.height == 4
    assert clean.get_column("adjustment_method").unique().to_list() == ["HFQ"]


def test_missing_price_keeps_raw_and_rejects_clean(tmp_path: Path):
    dates = {dt.date(2026, 7, 9), dt.date(2026, 7, 10)}
    with pytest.raises(ResearchPriceQualityError) as error:
        pipeline(tmp_path, omit_last=True).update(
            symbols=["510300.SH", "159919.SZ"],
            start=min(dates),
            end=max(dates),
            expected_dates=dates,
        )
    assert error.value.report.missing_rows == 1
    assert list((tmp_path / "data" / "raw").rglob("*.parquet"))
    assert not list((tmp_path / "data" / "clean").rglob("*.parquet"))


def test_new_research_method_replaces_old_source_for_same_symbol_date(tmp_path: Path):
    store = CleanResearchPriceStore(tmp_path / "research_price_1d")
    base = {
        "symbol": ["510300.SH"],
        "trade_date": [dt.date(2026, 7, 10)],
        "adjusted_close": [5.0],
    }
    store.upsert(pl.DataFrame({
        **base, "adjustment_method": ["HFQ"], "source": ["akshare"]
    }))
    store.upsert(pl.DataFrame({
        **base,
        "adjusted_close": [4.8],
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"],
        "source": ["baostock_akshare"],
    }))
    result = pl.read_parquet(
        tmp_path / "research_price_1d" / "date=2026-07-10" / "data.parquet"
    )
    assert result.height == 1
    assert result.item(0, "adjustment_method") == "TOTAL_RETURN_DIVIDEND"
