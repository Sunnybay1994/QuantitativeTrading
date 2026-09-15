"""用版本化 HKEX 年度通告复核并补充港股基础交易日历。"""

import datetime as dt
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.domain import TradeCalendarSchema


@dataclass(frozen=True)
class HkexCalendarNotice:
    year: int
    announcement_url: str
    announcement_id: str
    published_date: dt.date
    coverage_start: dt.date
    coverage_end: dt.date
    closures: tuple[dt.date, ...]
    half_days: tuple[dt.date, ...]


def load_hkex_calendar_notice(path: Path) -> HkexCalendarNotice:
    """读取并校验人工复核后的 HKEX 证券市场年度通告。"""
    with path.open("rb") as stream:
        data: dict[str, Any] = tomllib.load(stream)
    if data.get("version") != 1:
        raise ValueError("不支持的 HKEX 日历配置版本")
    if data.get("market") != "HK" or data.get("source") != "hkex":
        raise ValueError("HKEX 日历配置 market/source 不匹配")
    notice = HkexCalendarNotice(
        year=data["year"],
        announcement_url=data["announcement_url"],
        announcement_id=data["announcement_id"],
        published_date=data["published_date"],
        coverage_start=data["coverage_start"],
        coverage_end=data["coverage_end"],
        closures=tuple(item["date"] for item in data.get("closures", [])),
        half_days=tuple(item["date"] for item in data.get("half_days", [])),
    )
    _validate_notice(notice)
    return notice


def apply_hkex_calendar_notice(
    calendar: pl.DataFrame, notice: HkexCalendarNotice
) -> pl.DataFrame:
    """核对官方全日休市，并把官方半日市写入标准日历。"""
    clean = TradeCalendarSchema.validate(calendar)
    if clean.filter(pl.col("market") != "HK").height:
        raise ValueError("HKEX 通告只能应用于 HK 基础日历")
    if clean.is_empty():
        return clean
    start = cast(dt.date, clean.get_column("date").min())
    end = cast(dt.date, clean.get_column("date").max())
    if start < notice.coverage_start or end > notice.coverage_end:
        raise ValueError("港股日历区间超出 HKEX 通告覆盖范围")

    closure_set = set(notice.closures)
    half_day_set = set(notice.half_days)
    wrongly_open = clean.filter(pl.col("date").is_in(closure_set) & pl.col("is_open"))
    wrongly_closed = clean.filter(pl.col("date").is_in(half_day_set) & ~pl.col("is_open"))
    if wrongly_open.height or wrongly_closed.height:
        raise ValueError(
            "Tushare 港股日历与 HKEX 官方通告冲突: "
            f"休市日误开 {wrongly_open.height}，半日市误关 {wrongly_closed.height}"
        )
    result = clean.with_columns(
        (pl.col("is_open") & pl.col("date").is_in(half_day_set)).alias("is_half_day")
    )
    return TradeCalendarSchema.validate(result)


def _validate_notice(notice: HkexCalendarNotice) -> None:
    if notice.coverage_start.year != notice.year or notice.coverage_end.year != notice.year:
        raise ValueError("HKEX 通告年份与覆盖区间不一致")
    if notice.coverage_start > notice.coverage_end:
        raise ValueError("HKEX 通告覆盖区间倒置")
    if set(notice.closures) & set(notice.half_days):
        raise ValueError("同一日期不能同时是全日休市和半日市")
    for date in (*notice.closures, *notice.half_days):
        if not notice.coverage_start <= date <= notice.coverage_end:
            raise ValueError("HKEX 日历规则超出覆盖区间")
