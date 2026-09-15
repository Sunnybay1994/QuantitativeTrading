"""由上交所年度公告和沪市基础日历构建沪港通服务日历。"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from quant.domain import ConnectCalendarSchema, TradeCalendarSchema


@dataclass(frozen=True)
class CalendarNotice:
    route: str
    year: int
    source: str
    announcement_url: str
    announcement_id: str
    published_date: dt.date
    service_start: dt.date
    service_end: dt.date
    full_closures: tuple[tuple[dt.date, dt.date, str], ...]
    half_days: tuple[tuple[dt.date, str, str], ...]


def load_calendar_notice(path: Path) -> CalendarNotice:
    """读取并校验人工复核后的官方年度公告结构化配置。"""
    with path.open("rb") as stream:
        data: dict[str, Any] = tomllib.load(stream)
    if data.get("version") != 1:
        raise ValueError("不支持的港股通日历配置版本")
    if data.get("route") != "SH_CONNECT" or data.get("source") != "sse":
        raise ValueError("沪港通日历配置 route/source 不匹配")
    closures = tuple(
        (item["start"], item["end"], item["name"])
        for item in data.get("full_closures", [])
    )
    half_days = tuple(
        (item["date"], item["closed_session"], item["name"])
        for item in data.get("half_days", [])
    )
    notice = CalendarNotice(
        route=data["route"], year=data["year"], source=data["source"],
        announcement_url=data["announcement_url"], announcement_id=data["announcement_id"],
        published_date=data["published_date"], service_start=data["service_start"],
        service_end=data["service_end"], full_closures=closures, half_days=half_days,
    )
    _validate_notice(notice)
    return notice


def build_sse_connect_calendar(
    sh_calendar: pl.DataFrame,
    notice: CalendarNotice,
    *,
    start: dt.date,
    end: dt.date,
) -> pl.DataFrame:
    """以沪市开市日为底表，应用官方港股通全日/半日服务例外。"""
    if start > end:
        raise ValueError("start 不得晚于 end")
    if start < notice.service_start or end > notice.service_end:
        raise ValueError("请求区间超出公告覆盖范围")
    base = TradeCalendarSchema.validate(sh_calendar).filter(
        (pl.col("market") == "SH") & pl.col("date").is_between(start, end, closed="both")
    )
    expected_dates = set(
        pl.date_range(start, end, interval="1d", eager=True).to_list()
    )
    actual_dates = set(base.get_column("date").to_list())
    if actual_dates != expected_dates:
        missing = sorted(expected_dates - actual_dates)
        raise ValueError(f"沪市基础日历覆盖不完整，缺少 {len(missing)} 日")

    closure_name: dict[dt.date, str] = {}
    for closure_start, closure_end, name in notice.full_closures:
        for date in pl.date_range(closure_start, closure_end, interval="1d", eager=True):
            closure_name[date] = name
    half_day_name = {date: name for date, _, name in notice.half_days}
    exception_dates = set(closure_name) | set(half_day_name)
    exceptions = pl.DataFrame(
        {
            "date": sorted(exception_dates),
            "notice_closed": [date in closure_name for date in sorted(exception_dates)],
            "notice_half_day": [date in half_day_name for date in sorted(exception_dates)],
            "holiday_name": [
                closure_name.get(date) or half_day_name.get(date)
                for date in sorted(exception_dates)
            ],
        },
        schema={
            "date": pl.Date,
            "notice_closed": pl.Boolean,
            "notice_half_day": pl.Boolean,
            "holiday_name": pl.String,
        },
    )
    result = (
        base.join(exceptions, on="date", how="left")
        .select(
            pl.lit(notice.route).alias("route"),
            pl.col("date"),
            (
                pl.col("is_open")
                & ~pl.col("notice_closed").fill_null(False)
            ).alias("is_open"),
            (
                pl.col("is_open")
                & pl.col("notice_half_day").fill_null(False)
            ).alias("is_half_day"),
            pl.col("holiday_name"),
            pl.lit(notice.source).alias("source"),
        )
        .sort("date")
    )
    return ConnectCalendarSchema.validate(result)


def notice_rules_frame(notice: CalendarNotice) -> pl.DataFrame:
    """把版本化公告规则转换为可进入 raw 留档的原始规则表。"""
    rows = [
        {
            "rule_type": "FULL_CLOSURE", "start": start, "end": end,
            "closed_session": "ALL", "name": name,
        }
        for start, end, name in notice.full_closures
    ]
    rows.extend(
        {
            "rule_type": "HALF_DAY", "start": date, "end": date,
            "closed_session": session, "name": name,
        }
        for date, session, name in notice.half_days
    )
    return pl.DataFrame(rows)


def _validate_notice(notice: CalendarNotice) -> None:
    if notice.service_start.year != notice.year or notice.service_end.year != notice.year:
        raise ValueError("公告年份与服务区间不一致")
    if notice.service_start > notice.service_end:
        raise ValueError("公告服务区间倒置")
    for start, end, _ in notice.full_closures:
        if start > end or start < notice.service_start or end > notice.service_end:
            raise ValueError("全日休市规则超界或倒置")
    for date, session, _ in notice.half_days:
        if not notice.service_start <= date <= notice.service_end or session not in {"AM", "PM"}:
            raise ValueError("半日休市规则非法")

