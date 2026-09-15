"""港股通标的快照、调整事件和路由交易日历的标准化与编排。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Protocol

import polars as pl

from quant.data.storage import RawSnapshot, RawStore


def map_sse_snapshot(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.select(
        pl.lit("SH_CONNECT").alias("route"),
        pl.col("UPDATE_DATE").str.to_date().alias("snapshot_date"),
        (pl.col("SECURITY_CODE") + ".HK").alias("symbol"),
        pl.col("ABBR_CN").str.strip_chars().alias("name_cn"),
        pl.col("ABBR_EN").str.strip_chars().alias("name_en"),
        _security_type(pl.col("SECURITY_TYPE")).alias("security_type"),
        (pl.col("TRADE_FLAG") == "1").alias("buy_eligible"),
        pl.lit("sse").alias("source"),
    )


def map_sse_events(raw: pl.DataFrame) -> pl.DataFrame:
    """将 SSE 港股通调整事件映射为标准事件；仅接受官方中文调进/调出。"""
    normalized = raw.get_column("ADJUST_TYPE").cast(pl.String).str.strip_chars()
    valid = normalized.is_in(["调进", "调出"]).fill_null(False)
    if not bool(valid.all()):
        raise ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")

    return raw.select(
        pl.lit("SH_CONNECT").alias("route"),
        pl.col("VALID_DATE").str.to_date().alias("effective_date"),
        (pl.col("SECURITY_CODE") + ".HK").alias("symbol"),
        pl.when(pl.col("ADJUST_TYPE").cast(pl.String).str.strip_chars() == "调进")
        .then(pl.lit("ADD"))
        .otherwise(pl.lit("REMOVE"))
        .alias("action"),
        pl.col("SECURITY_ABBR").fill_null("").str.strip_chars().alias("name_cn"),
        pl.col("ABBR_EN").fill_null("").str.strip_chars().alias("name_en"),
        _security_type(pl.col("SECURITY_TYPE")).alias("security_type"),
        pl.col("FILE_DATE").str.to_date(strict=False).alias("published_date"),
        pl.lit("sse").alias("source"),
    )


def map_szse_snapshot(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.select(
        pl.lit("SZ_CONNECT").alias("route"),
        pl.col("_snapshot_date").cast(pl.String).str.to_date().alias("snapshot_date"),
        (pl.col("zqdm") + ".HK").alias("symbol"),
        pl.col("zqjc").fill_null("").alias("name_cn"),
        pl.col("zqywjc").fill_null("").alias("name_en"),
        pl.lit("OTHER").alias("security_type"),
        pl.lit(True).alias("buy_eligible"),
        pl.lit("szse").alias("source"),
    )


def map_szse_events(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.select(
        pl.lit("SZ_CONNECT").alias("route"),
        pl.col("sxrq").cast(pl.String).str.to_date().alias("effective_date"),
        (pl.col("zqdm") + ".HK").alias("symbol"),
        pl.when(pl.col("tznr") == "调入")
        .then(pl.lit("ADD"))
        .otherwise(pl.lit("REMOVE"))
        .alias("action"),
        pl.col("zqjc").fill_null("").alias("name_cn"),
        pl.col("zqywjc").fill_null("").alias("name_en"),
        pl.lit("OTHER").alias("security_type"),
        pl.lit(None, dtype=pl.Date).alias("published_date"),
        pl.lit("szse").alias("source"),
    )


def map_szse_calendar(raw: pl.DataFrame) -> pl.DataFrame:
    return raw.select(
        pl.lit("SZ_CONNECT").alias("route"),
        pl.col("jyrq").str.to_date().alias("date"),
        pl.col("jybz")
        .is_in(["不休市", "上午休市", "下午休市"])
        .alias("is_open"),
        pl.col("jybz").is_in(["上午休市", "下午休市"]).alias("is_half_day"),
        pl.col("jjrmc").cast(pl.String).alias("holiday_name"),
        pl.lit("szse").alias("source"),
    )


def _security_type(column: pl.Expr) -> pl.Expr:
    return (
        pl.when(column.str.contains("股票|EQTY"))
        .then(pl.lit("STOCK"))
        .when(column.str.contains("基金|ETF|TRST"))
        .then(pl.lit("ETF"))
        .otherwise(pl.lit("OTHER"))
    )


@dataclass(frozen=True)
class ConnectUpdateResult:
    snapshot: RawSnapshot
    clean_rows: int


class _FrameStore(Protocol):
    def upsert(self, frame: pl.DataFrame) -> int: ...


class ConnectMarketPipeline:
    def __init__(
        self, *, connector: Any, raw_store: RawStore, clean_root: _FrameStore
    ) -> None:
        self.connector = connector
        self.raw_store = raw_store
        self.clean_root = clean_root

    def update_snapshot(self) -> ConnectUpdateResult:
        raw = self.connector.fetch_eligibility_snapshot()  # type: ignore[attr-defined]
        snap = self.raw_store.write(
            source=self.connector.source, table="connect_eligibility_snapshot", frame=raw,
            parameters={"route": self.connector.route},
        )
        clean = map_sse_snapshot(raw) if self.connector.source == "sse" else map_szse_snapshot(raw)
        return ConnectUpdateResult(snap, self.clean_root.upsert(clean))

    def update_events(self, *, replace_clean: bool = False) -> ConnectUpdateResult:
        if type(replace_clean) is not bool:
            raise TypeError("replace_clean 必须是严格 bool")
        raw = self.connector.fetch_eligibility_events()  # type: ignore[attr-defined]
        snap = self.raw_store.write(
            source=self.connector.source, table="connect_eligibility_event", frame=raw,
            parameters={"route": self.connector.route},
        )
        clean = map_sse_events(raw) if self.connector.source == "sse" else map_szse_events(raw)
        if replace_clean:
            event_store = self.clean_root
            return ConnectUpdateResult(snap, event_store.replace_route(clean))  # type: ignore[attr-defined]
        return ConnectUpdateResult(snap, self.clean_root.upsert(clean))

    def update_calendar(self, start: dt.date, end: dt.date) -> ConnectUpdateResult:
        raw = self.connector.fetch_connect_calendar(start, end)  # type: ignore[attr-defined]
        snap = self.raw_store.write(
            source=self.connector.source, table="connect_calendar", frame=raw,
            parameters={"route": self.connector.route, "start": start, "end": end},
        )
        return ConnectUpdateResult(snap, self.clean_root.upsert(map_szse_calendar(raw)))
