"""交易日历与证券主表 raw→clean 集成测试。"""

import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.base import BaseConnector
from quant.data.mappers import BaostockCalendarMapper, BaostockInstrumentMapper
from quant.data.pipeline import CalendarUpdatePipeline, InstrumentUpdatePipeline
from quant.data.storage import CleanCalendarStore, CleanInstrumentStore, RawStore


class MarketFixtureConnector(BaseConnector):
    source = "fixture"

    def fetch_instruments(self, market: str) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "code": ["sh.600000", "sh.510300", "sz.000001"],
                "code_name": ["浦发银行", "沪深300ETF", "平安银行"],
                "ipoDate": ["1999-11-10", "2012-05-28", "1991-04-03"],
                "outDate": ["", "", ""],
                "type": ["1", "5", "1"],
                "status": ["1", "1", "1"],
            }
        )

    def fetch_trade_calendar(
        self, market: str, start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "calendar_date": ["2026-07-10", "2026-07-11"],
                "is_trading_day": ["1", "0"],
            }
        )

    def fetch_bar_1d(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError

    def fetch_corporate_actions(
        self, symbols: list[str], start: dt.date, end: dt.date
    ) -> pl.DataFrame:
        raise NotImplementedError


class FixtureCalendarMapper(BaostockCalendarMapper):
    source = "fixture"


class FixtureInstrumentMapper(BaostockInstrumentMapper):
    source = "fixture"


def test_calendar_pipeline_is_idempotent(tmp_path: Path):
    store = CleanCalendarStore(tmp_path / "data" / "clean" / "trade_calendar")
    pipeline = CalendarUpdatePipeline(
        connector=MarketFixtureConnector(),
        mapper=FixtureCalendarMapper("SH"),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=store,
    )

    for _ in range(2):
        pipeline.update(
            market="SH", start=dt.date(2026, 7, 10), end=dt.date(2026, 7, 11)
        )

    clean = pl.read_parquet(
        tmp_path / "data" / "clean" / "trade_calendar" / "market=SH" / "data.parquet"
    )
    assert clean.height == 2
    assert clean["is_open"].to_list() == [True, False]


def test_instrument_pipeline_filters_market_and_is_idempotent(tmp_path: Path):
    store = CleanInstrumentStore(tmp_path / "data" / "clean" / "instrument")
    pipeline = InstrumentUpdatePipeline(
        connector=MarketFixtureConnector(),
        mapper=FixtureInstrumentMapper("SH"),
        raw_store=RawStore(tmp_path / "data" / "raw"),
        clean_store=store,
    )

    for _ in range(2):
        pipeline.update(market="SH")

    clean = pl.read_parquet(
        tmp_path / "data" / "clean" / "instrument" / "market=SH" / "data.parquet"
    )
    assert clean["symbol"].to_list() == ["510300.SH", "600000.SH"]
    assert clean["instrument_type"].to_list() == ["ETF", "STOCK"]
