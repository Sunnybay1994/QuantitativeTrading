"""Official Southbound schedule, actual HK closures and 14:30 execution availability."""

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import polars as pl


# HKEX securities holiday circulars CT/058/22, CT/079/23, CT/063/24, CT/075/25.
# These are afternoon closures, even where an old daily calendar omits the flag.
HK_HALF_DAYS = {
    dt.date(2024, 2, 9),
    dt.date(2024, 12, 24),
    dt.date(2024, 12, 31),
    dt.date(2025, 1, 28),
    dt.date(2025, 12, 24),
    dt.date(2025, 12, 31),
    dt.date(2026, 2, 16),
    dt.date(2026, 12, 24),
    dt.date(2026, 12, 31),
}
OPTIMIZATION_DATE = dt.date(2023, 4, 24)
SZSE_OMITTED_WEEKENDS = {dt.date(2023, 12, 30), dt.date(2023, 12, 31)}
SSE_CALENDAR_URL = "https://www.sse.com.cn/services/hkexsc/home/arrange/data_1135.js"
NOTICE_URLS = {
    "sse_2023_original.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20221227_5714463.shtml",
    "sse_2023_optimization.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20230224_5716892.shtml",
    "sse_2024.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20231226_5733940.shtml",
    "sse_2025.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20241223_10767112.shtml",
    "sse_2026.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20251222_10802519.shtml",
    "sse_storm_20240906.html": "https://www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20240906_10761319.shtml",
}


def read_sse_closures(path: Path) -> dict[dt.date, tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    rows = re.findall(r"\[\s*'(\d{4}-\d{2}-\d{2})',\s*'([^']+)',\s*'([^']*)'\s*\]", text)
    if not rows:
        raise ValueError("No official SSE closure rows")
    result = {}
    for date, part, reason in rows:
        key = dt.date.fromisoformat(date)
        if part not in {"全天", "上午", "下午"} or key in result:
            raise ValueError("Unknown or duplicate SSE closure")
        result[key] = (part, reason)
    return result


def read_szse_calendar(root: Path, start: dt.date, end: dt.date) -> dict[dt.date, str]:
    rows = {}
    for path in sorted(root.glob("????-??.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["data"]:
            date = dt.date.fromisoformat(row["jyrq"])
            if not start <= date <= end:
                continue
            if date in rows or row["jybz"] not in {"不休市", "全日休市", "上午休市", "下午休市"}:
                raise ValueError("Duplicate date or unknown SZSE status")
            rows[date] = row["jybz"]
    # SZSE's December 2023 response ends on Dec 29; its two omitted days are
    # weekends, also explicitly closed in SSE's independent daily table.
    for offset in range((end - start).days + 1):
        date = start + dt.timedelta(days=offset)
        if date not in rows and date in SZSE_OMITTED_WEEKENDS:
            rows[date] = "全日休市"
    if len(rows) != (end - start).days + 1:
        raise ValueError("SZSE calendar does not cover every requested date")
    return rows


def _notice(date: dt.date) -> tuple[str, dt.date]:
    if date == dt.date(2024, 9, 6):
        return "sse_storm_20240906.html", date
    if date.year == 2023 and date < dt.date(2023, 12, 28):
        return "sse_2023_optimization.html", dt.date(2023, 2, 24)
    if date < dt.date(2024, 12, 30):
        return "sse_2024.html", dt.date(2023, 12, 26)
    if date.year <= 2025:
        return "sse_2025.html", dt.date(2024, 12, 23)
    return "sse_2026.html", dt.date(2025, 12, 22)


def build_calendar(
    hk_calendar: pl.DataFrame,
    closures: dict[dt.date, tuple[str, str]],
    szse: dict[dt.date, str],
    start: dt.date,
    end: dt.date,
) -> pl.DataFrame:
    """Daily marks, not an individual-security fill guarantee or an intraday halt feed."""
    if not dt.date(2023, 11, 1) <= start <= end <= dt.date(2026, 9, 9):
        raise ValueError("Outside the verified official 2023-11-01 to 2026-09-09 coverage")
    hk = hk_calendar.filter(pl.col("date").is_between(start, end))
    if hk.height != (end - start).days + 1 or hk["date"].n_unique() != hk.height:
        raise ValueError("HK calendar must cover every date exactly once")
    if hk["is_open"].null_count():
        raise ValueError("HK calendar has unknown open status")
    hk_days = {row["date"]: row for row in hk.iter_rows(named=True)}
    rows: list[dict[str, Any]] = []
    for offset in range((end - start).days + 1):
        date = start + dt.timedelta(days=offset)
        part, reason = closures.get(date, ("", "正常交易日"))
        # All weekend closures must be present in the official full closure table.
        if date.weekday() >= 5 and part != "全天":
            raise ValueError(f"SSE closure table omits a weekend: {date}")
        if date not in szse:
            raise ValueError(f"Missing SZSE calendar date: {date}")
        expected = {"": "不休市", "全天": "全日休市", "上午": "上午休市", "下午": "下午休市"}[part]
        if szse[date] != expected:
            raise ValueError(f"SSE/SZSE scheduled calendar disagreement: {date}")
        hk_open = bool(hk_days[date]["is_open"])
        hk_half = date in HK_HALF_DAYS or bool(hk_days[date].get("is_half_day", False))
        am = part not in {"全天", "上午"}
        pm = part not in {"全天", "下午"}
        scheduled = am or pm
        source, published = _notice(date)
        if date == dt.date(2024, 9, 6):
            am = pm = False
            reason = "八号台风：官方临时暂停南向交易"
        elif scheduled and not hk_open:
            raise ValueError(f"HK closure requires a dated official override: {date}")
        if hk_half and pm:
            pm = False
        rows.append(
            {
                "date": date,
                "hk_is_open": hk_open,
                "hk_is_half_day": hk_half,
                "southbound_scheduled_open": scheduled,
                "southbound_am_open": am and hk_open,
                "southbound_pm_open": pm and hk_open,
                "is_connect_open": (am or pm) and hk_open,
                "can_execute_1430": pm and hk_open and not hk_half,
                "reason": reason,
                "source_url": NOTICE_URLS[source],
                "source_published_date": published,
                "schedule_effective_date": date,
                "optimization_effective_date": OPTIMIZATION_DATE,
                "szse_verified": date not in SZSE_OMITTED_WEEKENDS,
                "hk_half_day_source": f"hkex_securities_{date.year}.pdf",
            }
        )
    return pl.DataFrame(rows)


def read_hk_connect_calendar(data_root: Path, snapshot_id: str) -> pl.DataFrame:
    return pl.read_parquet(
        data_root / "clean/hk_connect_calendar" / snapshot_id / "calendar.parquet"
    )


def check_trade_dates(trades: pl.DataFrame, calendar: pl.DataFrame) -> pl.DataFrame:
    """Report entry/exit date conflicts only, preserving every original trade."""
    indexed = trades.with_row_index("trade_row")
    checks = []
    for leg in ("entry_date", "exit_date"):
        frame = indexed.select("trade_row", "symbol", pl.col(leg).alias("date"))
        frame = frame.join(
            calendar.select("date", "can_execute_1430", "reason"),
            on="date",
            how="left",
            validate="m:1",
        )
        checks.append(frame.with_columns(pl.lit(leg).alias("leg")))
    return (
        pl.concat(checks)
        .filter(~pl.col("can_execute_1430").fill_null(False))
        .sort("trade_row", "leg")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--szse-raw", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2023, 11, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 9, 9))
    parser.add_argument("--check-trades", type=Path)
    args = parser.parse_args()
    for filename in NOTICE_URLS:
        if not (args.raw / filename).is_file():
            raise ValueError(f"Missing official source notice: {filename}")
    for year in range(args.start.year, args.end.year + 1):
        if not (args.raw / f"hkex_securities_{year}.pdf").is_file():
            raise ValueError(f"Missing official HKEX securities calendar: {year}")
    hk = pl.read_parquet(args.data_root / "clean/trade_calendar/market=HK/data.parquet")
    calendar = build_calendar(
        hk,
        read_sse_closures(args.raw / "sse_calendar.js"),
        read_szse_calendar(args.szse_raw, args.start, args.end),
        args.start,
        args.end,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    calendar.write_parquet(args.output / "calendar.parquet")
    calendar.write_csv(args.output / "calendar.csv")
    # Preserve the exact existing date skeleton used by this output, without changing it.
    hk.filter(pl.col("date").is_between(args.start, args.end)).write_parquet(
        args.output / "hk_input.parquet"
    )
    summary = {
        "start": str(args.start),
        "end": str(args.end),
        "calendar_rows": calendar.height,
        "connect_days": int(calendar["is_connect_open"].sum()),
        "executable_1430_days": int(calendar["can_execute_1430"].sum()),
        "hk_open_connect_closed": calendar.filter(
            pl.col("hk_is_open") & ~pl.col("is_connect_open")
        ).height,
        "hk_half_days": int(calendar["hk_is_half_day"].sum()),
    }
    if args.check_trades:
        trades = pl.read_parquet(args.check_trades)
        conflicts = check_trade_dates(trades, calendar)
        conflicts.write_csv(args.output / "trade_date_conflicts.csv")
        summary.update(
            {
                "checked_trades": trades.height,
                "conflicting_legs": conflicts.height,
                "conflicting_trades": conflicts["trade_row"].n_unique(),
            }
        )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
