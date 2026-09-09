import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from quant.data.gold_reference import normalize_gold_reference


def payload(dates, closes):
    return {"chart": {"result": [{
        "meta": {"symbol": "GC=F", "exchangeTimezoneName": "America/New_York"},
        "timestamp": [int(dt.datetime.combine(d, dt.time(), ZoneInfo("America/New_York")).timestamp()) for d in dates],
        "indicators": {"quote": [{"close": closes}]},
    }]}}


def test_completed_day_cutoff_and_dst():
    dates = [dt.date(2026, 3, 6), dt.date(2026, 3, 9), dt.date(2026, 3, 10)]
    p = payload(dates, [100.0, 102.0, 999.0])
    result = normalize_gold_reference(p, as_of=dt.datetime(2026, 3, 10, 1, tzinfo=dt.timezone.utc))
    assert result["reference_date"].to_list() == dates[:2]
    assert [x.hour for x in result["available_at"]] == [23, 22]
    assert result["reference_return"][-1] == pytest.approx(0.02)
    # Changing an unfinished foreign day cannot change completed returns.
    p["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = 1.0
    assert normalize_gold_reference(p, as_of=dt.datetime(2026, 3, 10, 1, tzinfo=dt.timezone.utc)).equals(result)


def test_null_close_does_not_bridge_unknown_day():
    dates = [dt.date(2026, 1, d) for d in (5, 6, 7, 8)]
    result = normalize_gold_reference(payload(dates, [100.0, None, 110.0, 121.0]),
                                      as_of=dt.datetime(2026, 1, 9, tzinfo=dt.timezone.utc))
    assert result["reference_return"].to_list()[:3] == [None, None, None]
    assert result["reference_return"][-1] == pytest.approx(0.1)


def test_reject_changed_daily_timestamp_convention():
    p = payload([dt.date(2026, 1, 5)], [100.0])
    p["chart"]["result"][0]["timestamp"][0] += 18 * 3600
    with pytest.raises(ValueError, match="timestamp convention"):
        normalize_gold_reference(p, as_of=dt.datetime(2026, 1, 9, tzinfo=dt.timezone.utc))


def test_holiday_morning_label_keeps_conservative_evening_availability():
    p = payload([dt.date(2025, 12, 24)], [100.0])
    p["chart"]["result"][0]["timestamp"][0] += 9 * 3600 + 30 * 60
    before = dt.datetime(2025, 12, 24, 22, tzinfo=dt.timezone.utc)
    assert normalize_gold_reference(p, as_of=before).is_empty()
    result = normalize_gold_reference(p, as_of=before + dt.timedelta(hours=1))
    assert result["reference_date"][0] == dt.date(2025, 12, 24)
    assert result["available_at"][0].hour == 23
