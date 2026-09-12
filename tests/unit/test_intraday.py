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


def bao_day(day=dt.date(2026, 9, 8)):
    rows = []
    for hour, minute in [(9, 30), (13, 0)]:
        start = dt.datetime.combine(day, dt.time(hour, minute))
        for step in range(1, 25):
            stamp = start + dt.timedelta(minutes=5*step)
            rows.append(bao().with_columns(pl.lit(str(day)).alias('date'),
                pl.lit(stamp.strftime('%Y%m%d%H%M%S')+'000').alias('time')))
    return pl.concat(rows)


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
            return bao_day()

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
    assert first["changed_rows"] == 48 and first["incomplete_days"] == 0
    assert intraday._stock_job(args)["changed_rows"] == 0
    assert len(calls) == 1
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    revised = pl.read_parquet(directory / "data.parquet").with_columns(pl.lit(10.6).alias("close"))
    assert intraday.merge_bars(directory, revised) == 48
    assert intraday.merge_bars(directory, revised) == 0


def test_short_response_cannot_mark_capture_complete(monkeypatch, tmp_path: Path):
    class Connector:
        def fetch_intraday(self, *args):
            return bao_day()

    monkeypatch.setattr(intraday, "BaostockConnector", Connector)
    monkeypatch.setattr(intraday.time, "sleep", lambda seconds: None)
    calendar = tmp_path / "clean/trade_calendar/market=SH/data.parquet"
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({"date": [dt.date(2026, 9, 8), dt.date(2026, 9, 9)],
                  "is_open": [True, True], "is_half_day": [False, False]}).write_parquet(calendar)
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    directory.mkdir(parents=True)
    normalize_baostock(bao(), "600000.SH").head(0).write_parquet(directory / "data.parquet")
    (directory / "coverage.json").write_text(json.dumps({"through": "2026-09-07"}))
    with pytest.raises(ValueError, match="known traded days"):
        intraday._stock_job((str(tmp_path), "600000.SH", "2026-09-09",
                            [dt.date(2026, 9, 8), dt.date(2026, 9, 9)]))
    assert json.loads((directory / "coverage.json").read_text())["through"] == "2026-09-07"
    status = json.loads((directory / "coverage.json").read_text())
    assert status["missing_traded_dates"] == ["2026-09-09"]
    assert status["attempted_through"] == "2026-09-09"
    assert pl.read_parquet(directory / "data.parquet")["trade_date"].unique().to_list() == [dt.date(2026, 9, 8)]


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
            return bao_day(date)

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
    assert pl.read_parquet(directory / "data.parquet").height == 48
    fail[0] = False
    assert intraday._stock_job(args)["changed_rows"] == 48
    assert pl.read_parquet(directory / "data.parquet").height == 96
    assert intraday._stock_job(args)["changed_rows"] == 0


def test_missing_old_day_preserves_later_year_without_reporting_completion(monkeypatch, tmp_path):
    from quant.data.stock_intraday_repository import read_stock_five_minute_pool

    dates = [dt.date(2025, 12, 31), dt.date(2026, 1, 2)]
    gap, calls = [True], []

    class Connector:
        def fetch_intraday(self, symbol, start, end):
            calls.append((start, end))
            if start.year == 2025 and gap[0]:
                return bao().head(0)
            day = dates[start.year - 2025]
            return bao_day(day)

    monkeypatch.setattr(intraday, "BaostockConnector", Connector)
    calendar = tmp_path / "clean/trade_calendar/market=SH/data.parquet"
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({"date": dates, "is_open": [True, True], "is_half_day": [False, False]}).write_parquet(calendar)
    directory = intraday._directory(tmp_path, "baostock", "600000.SH", "5m")
    directory.mkdir(parents=True)
    normalize_baostock(bao(), "600000.SH").head(0).write_parquet(directory / "data.parquet")
    (directory / "coverage.json").write_text(json.dumps({"through": "2025-12-30"}))
    args = (str(tmp_path), "600000.SH", "2026-01-02", dates)
    with pytest.raises(ValueError, match="known traded days"):
        intraday._stock_job(args)
    assert pl.read_parquet(directory / "data.parquet")["trade_date"].unique().to_list() == [dates[1]]
    status = json.loads((directory / "coverage.json").read_text())
    assert status["through"] == "2025-12-30" and status["attempted_through"] == "2026-01-02"
    assert status["missing_traded_dates"] == [str(dates[0])]
    with pytest.raises(ValueError, match="known traded symbol-days"):
        read_stock_five_minute_pool(tmp_path, symbols=("600000.SH",), start=dates[0], end=dates[1],
            expected_traded_days=pl.DataFrame({"symbol": ["600000.SH"] * 2, "trade_date": dates}))
    with pytest.raises(ValueError, match="known traded days"):
        intraday._stock_job(args)
    gap[0] = False
    assert intraday._stock_job(args)["changed_rows"] == 48
    assert json.loads((directory / "coverage.json").read_text())["missing_traded_dates"] == []
    count = len(calls)
    assert intraday._stock_job(args)["changed_rows"] == 0 and len(calls) == count


def test_bounded_stock_capture_preserves_historical_gaps(monkeypatch, tmp_path):
    calls = []
    day = dt.date(2026, 9, 8)
    class Connector:
        def fetch_intraday(self, symbol, start, end):
            calls.append((start, end))
            return bao_day()
    monkeypatch.setattr(intraday, 'BaostockConnector', Connector)
    calendar = tmp_path/'clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date': [day], 'is_open': [True], 'is_half_day': [False]}).write_parquet(calendar)
    directory = intraday._directory(tmp_path, 'baostock', '600000.SH', '5m')
    directory.mkdir(parents=True)
    history = json.dumps({'through': '2020-01-01', 'missing_traded_dates': ['2020-01-02']})
    (directory/'coverage.json').write_text(history)
    args = (str(tmp_path), '600000.SH', str(day), [dt.date(2020, 1, 2), day])
    assert intraday._stock_job(args, start_date=day)['changed_rows'] == 48
    assert calls == [(day, day)]
    assert (directory/'coverage.json').read_text() == history
    recent = json.loads((directory/'recent_coverage.json').read_text())
    assert recent['from'] == str(day) and recent['through'] == str(day)
    assert intraday._stock_job(args, start_date=day)['changed_rows'] == 0
    assert len(calls) == 1
    # An earlier requested range is not satisfied by the later capture.
    with pytest.raises(ValueError, match='known traded days'):
        intraday._stock_job((str(tmp_path), '600000.SH', str(day), [day-dt.timedelta(days=1), day]),
                           start_date=day-dt.timedelta(days=1))
    assert calls[-1] == (day-dt.timedelta(days=1), day)
    assert (directory/'coverage.json').read_text() == history


def test_bounded_stock_capture_rejects_invalid_range(tmp_path):
    with pytest.raises(ValueError, match='start must not exceed'):
        intraday._stock_job((str(tmp_path), '600000.SH', '2026-09-08', []),
                           start_date=dt.date(2026, 9, 9))
    with pytest.raises(ValueError, match='stocks enabled'):
        intraday.refresh_intraday(data_root=tmp_path, end=dt.date(2026, 9, 8), stocks=False,
                                  stock_from=dt.date(2026, 9, 8))


@pytest.mark.parametrize('bounded', [False, True])
def test_partial_day_is_retried_despite_completed_coverage(monkeypatch, tmp_path, bounded):
    day = dt.date(2026, 9, 8)
    calls, complete = [], [False]

    class Connector:
        def fetch_intraday(self, symbol, start, end):
            calls.append((start, end))
            return bao_day() if complete[0] else bao_day().head(47)

    monkeypatch.setattr(intraday, 'BaostockConnector', Connector)
    calendar = tmp_path/'clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date': [day], 'is_open': [True], 'is_half_day': [False]}).write_parquet(calendar)
    directory = intraday._directory(tmp_path, 'baostock', '600000.SH', '5m')
    directory.mkdir(parents=True)
    partial = normalize_baostock(bao_day().head(47), '600000.SH')
    intraday.add_session_quality(partial, tmp_path, '5m', '600000.SH').write_parquet(directory/'data.parquet')
    coverage = directory/('recent_coverage.json' if bounded else 'coverage.json')
    coverage.write_text(json.dumps({'through': str(day), 'from': str(day)}))
    args = (str(tmp_path), '600000.SH', str(day), [day])
    options = {'start_date': day} if bounded else {}
    with pytest.raises(ValueError, match='missing complete bars'):
        intraday._stock_job(args, **options)
    assert calls == [(day, day)]
    assert json.loads(coverage.read_text())['missing_traded_dates'] == [str(day)]
    assert json.loads(coverage.read_text())['through'] < str(day)
    assert pl.read_parquet(directory/'data.parquet').height == 47
    first_raw = set((tmp_path/'raw').rglob('*.parquet'))
    assert first_raw

    complete[0] = True
    result = intraday._stock_job(args, **options)
    assert result['changed_rows'] == 1
    assert result['missing_traded_dates'] == []
    assert pl.read_parquet(directory/'data.parquet')['session_complete'].all()
    assert first_raw < set((tmp_path/'raw').rglob('*.parquet'))
    assert intraday._stock_job(args, **options)['changed_rows'] == 0
    assert len(calls) == 2
