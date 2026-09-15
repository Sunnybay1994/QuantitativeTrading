import datetime as dt

import polars as pl

from quant.data.audit_calendars import audit_calendar_frames


def connect(route: str, opens: list[bool]) -> pl.DataFrame:
    return pl.DataFrame({
        "route": [route] * 2,
        "date": [dt.date(2026, 1, 1), dt.date(2026, 1, 2)],
        "is_open": opens, "is_half_day": [False, False],
        "holiday_name": [None, None], "source": ["sse" if route == "SH_CONNECT" else "szse"] * 2,
    })


def market(opens: list[bool]) -> pl.DataFrame:
    return pl.DataFrame({
        "date": [dt.date(2026, 1, 1), dt.date(2026, 1, 2)], "is_open": opens,
    })


def test_calendar_audit_detects_impossible_open_day() -> None:
    report = audit_calendar_frames(
        connect("SH_CONNECT", [False, True]), connect("SZ_CONNECT", [False, True]),
        market([False, True]), market([False, True]), market([False, False]),
    )
    assert report["route_status_differences"] == 0
    assert report["sh_connect_market_violations"] == 1
    assert report["sz_connect_market_violations"] == 1
