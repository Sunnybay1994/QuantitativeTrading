import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import intraday
from quant.data.intraday_bars import TZ, normalize_baostock, normalize_yahoo


def bao():
    return pl.DataFrame({"date": ["2026-09-08"], "time": ["20260908093500000"],
                         "code": ["sh.600000"], "open": ["10"], "high": ["11"],
                         "low": ["9"], "close": ["10.5"], "volume": ["100"],
                         "amount": ["1050"], "adjustflag": ["3"]})


def test_bao_end_timestamp_and_invalid_prices():
    result = normalize_baostock(bao(), "600000.SH")
    assert result["bar_start"][0] == dt.datetime(2026, 9, 8, 9, 30, tzinfo=TZ)
    assert result["bar_end"][0] == dt.datetime(2026, 9, 8, 9, 35, tzinfo=TZ)
    with pytest.raises(ValueError, match="OHLCV"):
        normalize_baostock(bao().with_columns(pl.lit("8").alias("high")), "600000.SH")
    zero = bao().with_columns(pl.lit("0").alias(c) for c in ("open", "high", "low", "close", "volume", "amount"))
    assert normalize_baostock(zero, "600000.SH").is_empty()


def test_yahoo_lunch_interval_live_quote_and_availability():
    times = [dt.datetime(2026, 9, 8, h, m, second, tzinfo=TZ)
             for h, m, second in [(11, 30, 0), (12, 30, 0), (13, 30, 0), (14, 4, 51)]]
    payload = {"chart": {"result": [{"timestamp": [t.timestamp() for t in times],
        "indicators": {"quote": [{"open": [10.] * 4, "high": [11.] * 4,
                                  "low": [9.] * 4, "close": [10.5] * 4,
                                  "volume": [100.] * 4}]}}]}}
    now = dt.datetime(2026, 9, 8, 14, tzinfo=TZ)
    hk = normalize_yahoo(payload, "00700.HK", "60m", now)
    assert hk.height == 2  # 13:30 -> 14:30 is not yet available; live quote is excluded.
    assert hk["bar_end"][-1] == dt.datetime(2026, 9, 8, 13, 30, tzinfo=TZ)
    china = normalize_yahoo(payload, "518880.SH", "60m", now)
    assert china.height == 1  # 11:30 -> 12:30 has no continuous trading in Shanghai.


def test_stock_capture_resume_and_clean_revision(monkeypatch, tmp_path: Path):
    calls = []

    class Connector:
        def fetch_intraday(self, symbol, start, end):
            calls.append((symbol, start, end))
            return bao()

    monkeypatch.setattr(intraday, "BaostockConnector", Connector)
    calendar = tmp_path / "clean/trade_calendar/market=SH/data.parquet"
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({"date": [dt.date(2026, 9, 8)], "is_open": [True],
                  "is_half_day": [False]}).write_parquet(calendar)
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    directory.mkdir(parents=True)
    normalize_baostock(bao(), "600000.SH").head(0).write_parquet(directory / "data.parquet")
    (directory / "coverage.json").write_text(json.dumps({"through": "2026-09-07"}))
    args = (str(tmp_path), "600000.SH", "2026-09-08", [dt.date(2026, 9, 8)])
    first = intraday._stock_job(args)
    assert first["changed_rows"] == 1 and first["incomplete_days"] == 1
    assert intraday._stock_job(args)["changed_rows"] == 0
    assert len(calls) == 1
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    revised = pl.read_parquet(directory / "data.parquet").with_columns(pl.lit(10.6).alias("close"))
    assert intraday.merge_bars(directory, revised) == 1
    assert intraday.merge_bars(directory, revised) == 0


def test_short_response_cannot_mark_capture_complete(monkeypatch, tmp_path: Path):
    class Connector:
        def fetch_intraday(self, *args):
            return bao()

    monkeypatch.setattr(intraday, "BaostockConnector", Connector)
    monkeypatch.setattr(intraday.time, "sleep", lambda seconds: None)
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    directory.mkdir(parents=True)
    normalize_baostock(bao(), "600000.SH").head(0).write_parquet(directory / "data.parquet")
    (directory / "coverage.json").write_text(json.dumps({"through": "2026-09-07"}))
    with pytest.raises(ValueError, match="known traded days"):
        intraday._stock_job((str(tmp_path), "600000.SH", "2026-09-09",
                            [dt.date(2026, 9, 8), dt.date(2026, 9, 9)]))
    assert json.loads((directory / "coverage.json").read_text())["through"] == "2026-09-07"


def test_hk_half_day_last_hour_available_at_noon(tmp_path):
    date = dt.date(2026, 2, 16)
    stamps = [dt.datetime.combine(date, dt.time(h, 30), TZ).timestamp() for h in (9, 10, 11)]
    payload = {"chart": {"result": [{"timestamp": stamps, "indicators": {"quote": [
        {"open": [10.] * 3, "high": [11.] * 3, "low": [9.] * 3,
         "close": [10.5] * 3, "volume": [100.] * 3}]} }]}}
    frame = normalize_yahoo(payload, "00700.HK", "60m", dt.datetime(2026, 2, 17, tzinfo=TZ))
    path = tmp_path / "clean/trade_calendar/market=HK/data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({"date": [date], "is_open": [True], "is_half_day": [False]}).write_parquet(path)
    result = intraday.add_session_quality(frame, tmp_path, "60m", "00700.HK")
    assert result["session_complete"].all()
    assert result["bar_end"][-1] == dt.datetime(2026, 2, 16, 12, tzinfo=TZ)


def test_year_chunk_survives_later_network_failure(monkeypatch, tmp_path):
    dates = [dt.date(2025, 12, 31), dt.date(2026, 1, 2)]
    calls, fail = [], [True]

    class Connector:
        def fetch_intraday(self, symbol, start, end):
            calls.append((start, end))
            if start.year == 2026 and fail[0]:
                raise RuntimeError("network unavailable")
            date = dates[start.year - 2025]
            return bao().with_columns(pl.lit(str(date)).alias("date"),
                pl.lit(date.strftime("%Y%m%d") + "093500000").alias("time"))

    monkeypatch.setattr(intraday, "BaostockConnector", Connector)
    monkeypatch.setattr(intraday.time, "sleep", lambda seconds: None)
    path = tmp_path / "clean/trade_calendar/market=SH/data.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({"date": dates, "is_open": [True, True], "is_half_day": [False, False]}).write_parquet(path)
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    directory.mkdir(parents=True)
    normalize_baostock(bao(), "600000.SH").head(0).write_parquet(directory / "data.parquet")
    (directory / "coverage.json").write_text(json.dumps({"through": "2025-12-30"}))
    args = (str(tmp_path), "600000.SH", "2026-01-02", dates)
    with pytest.raises(RuntimeError, match="network"):
        intraday._stock_job(args)
    assert json.loads((directory / "coverage.json").read_text())["through"] == "2025-12-31"
    assert pl.read_parquet(directory / "data.parquet").height == 1
    fail[0] = False
    assert intraday._stock_job(args)["changed_rows"] == 1
    assert pl.read_parquet(directory / "data.parquet").height == 2
    assert intraday._stock_job(args)["changed_rows"] == 0
