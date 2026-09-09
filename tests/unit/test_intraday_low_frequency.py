import datetime as dt
import math
import tomllib
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.intraday_bars import SCHEMA, TZ
from quant.data.stock_intraday_repository import reconcile_five_minute_days
from quant.factors.intraday_low_frequency import (
    FACTOR_NAMES, compute_intraday_low_frequency_factors,
)
from quant.research.monthly_intraday_factors import read_monthly_intraday_factors


def _day(day: dt.date, symbol: str = "600000.SH", flat: bool = False) -> pl.DataFrame:
    rows = []
    price = 10.0
    for index in range(48):
        minute = 570 + 5 * index if index < 24 else 780 + 5 * (index - 24)
        begin = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        opening = price
        price *= math.exp(0.01 if index < 10 and not flat else 0)
        rows.append({"symbol": symbol, "trade_date": day, "bar_start": begin,
                     "bar_end": begin + dt.timedelta(minutes=5), "open": opening,
                     "close": price, "high": price, "low": opening,
                     "volume": 10.0, "amount": 10 * price, "source": "baostock"})
    return pl.DataFrame(rows, schema=SCHEMA).with_columns(pl.lit(True).alias("session_complete"))


def test_complete_day_hand_calculation_and_no_overnight_return():
    days = (dt.date(2026, 1, 5), dt.date(2026, 1, 6))
    first = _day(days[0])
    second = _day(days[1]).with_columns([pl.col(c) * 2 for c in ("open", "close", "high", "low", "amount")])
    result = compute_intraday_low_frequency_factors(pl.concat([first, second]), sessions=days, window=2)
    amounts = first["amount"].to_list()
    expected = [sum(amounts[-6:]) / sum(amounts),
                (sum(amounts[:10]) / 100) / (sum(amounts) / 480),
                math.sqrt(48 / 10), sum(amounts[:6]) / sum(amounts)]
    for factor, value in zip(FACTOR_NAMES, expected):
        assert result[factor].to_list() == [None, pytest.approx(value)]
    assert result["valid_day"].to_list() == [True, True]


@pytest.mark.parametrize("field", ["close", "volume", "amount"])
def test_daily_disagreement_invalidates_window_without_changing_raw(field):
    days = tuple(dt.date(2026, 1, d) for d in (5, 6, 7, 8))
    minute = pl.concat([_day(day) for day in days])
    original = minute.clone()
    reference = minute.group_by("symbol", "trade_date").agg(
        pl.col("close").last(), pl.col("volume").sum(), pl.col("amount").sum())
    reference = reference.with_columns(pl.when(pl.col("trade_date") == days[1])
        .then(pl.col(field) * 1.02).otherwise(pl.col(field)).alias(field))
    quality = reconcile_five_minute_days(minute, reference, close_tolerance=.01,
                                        volume_tolerance=.01, amount_tolerance=.01)
    assert quality["daily_reconciled"].to_list() == [True, False, True, True]
    result = compute_intraday_low_frequency_factors(minute.join(
        quality.select("symbol", "trade_date", "daily_reconciled"), on=["symbol", "trade_date"]),
        sessions=days, window=2)
    assert result["valid_day"].to_list() == [True, False, True, True]
    assert result[FACTOR_NAMES[0]].is_null().to_list() == [True, True, True, False]
    assert_frame_equal(minute, original)


def test_monthly_reader_preserves_factor_values_and_hashes_consumed_bars(tmp_path):
    settings = tomllib.loads(Path("configs/research/b8_tail_amount_20260909.toml").read_text(
        encoding="utf-8"))["intraday"]
    settings["window_sessions"] = 2
    days = (dt.date(2026, 1, 5), dt.date(2026, 1, 6))
    minute = pl.concat([_day(day) for day in days])
    directory = tmp_path / "clean/bar_intraday/freq=5m/source=baostock/symbol=600000.SH"
    directory.mkdir(parents=True)
    path = directory / "data.parquet"
    minute.write_parquet(path)
    daily_bars = minute.group_by("symbol", "trade_date").agg(
        pl.col("close").last(), pl.col("volume").sum(), pl.col("amount").sum())
    args = dict(data_root=tmp_path, settings=settings, candidates=("600000.SH",),
                sessions=days, start=days[0], end=days[-1], daily_bars=daily_bars)
    daily, digest = read_monthly_intraday_factors(**args)
    expected = compute_intraday_low_frequency_factors(minute, sessions=days, window=2)
    assert_frame_equal(daily.select(expected.columns), expected)
    assert daily["daily_reconciled"].all()
    assert (digest.rows, digest.min_date, digest.max_date) == (96, days[0], days[-1])
    # Storage row order cannot change the consumed input, but a price/amount revision does.
    minute.reverse().write_parquet(path)
    assert read_monthly_intraday_factors(**args)[1] == digest
    minute.with_columns(pl.col("amount") * 1.01).write_parquet(path)
    assert read_monthly_intraday_factors(**args)[1].content_sha256 != digest.content_sha256
    minute.filter(pl.col("trade_date") == days[0]).write_parquet(path)
    with pytest.raises(ValueError, match="known traded"):
        read_monthly_intraday_factors(**args)


def test_missing_bar_missing_day_and_future_invariance():
    days = tuple(dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(5))
    first = pl.concat([_day(days[0]), _day(days[1]).head(47), _day(days[2])])
    result = compute_intraday_low_frequency_factors(first, sessions=days, window=2)
    assert result["valid_day"].to_list() == [True, False, True]
    assert all(result[factor].null_count() == 3 for factor in FACTOR_NAMES)
    # A whole missing exchange session must not compress the rolling window.
    gap = pl.concat([_day(days[0]), _day(days[2]), _day(days[3])])
    result_gap = compute_intraday_low_frequency_factors(gap, sessions=days, window=2)
    assert result_gap[FACTOR_NAMES[0]][1] is None
    assert result_gap[FACTOR_NAMES[0]][2] is not None
    later = compute_intraday_low_frequency_factors(pl.concat([gap, _day(days[4])]), sessions=days, window=2)
    assert_frame_equal(result_gap, later.filter(pl.col("trade_date") < days[4]))


def test_zero_variance_invalid_amount_duplicate_and_wrong_grid():
    day = dt.date(2026, 1, 5)
    bars = _day(day, flat=True)
    result = compute_intraday_low_frequency_factors(bars, sessions=(day,), window=1)
    assert result["intraday_skew20"].item() is None
    assert result["intraday_smart_vwap20"].item() == pytest.approx(1)
    bad_amount = bars.with_columns(pl.when(pl.col("bar_start") == bars["bar_start"][0])
        .then(float("nan")).otherwise(pl.col("amount")).alias("amount"))
    assert not compute_intraday_low_frequency_factors(bad_amount, sessions=(day,), window=1)["valid_day"].item()
    with pytest.raises(ValueError, match="duplicate"):
        compute_intraday_low_frequency_factors(pl.concat([bars, bars.head(1)]), sessions=(day,))
    wrong_grid = bars.with_columns(pl.col("bar_start") + pl.duration(minutes=1),
                                   pl.col("bar_end") + pl.duration(minutes=1))
    assert not compute_intraday_low_frequency_factors(wrong_grid, sessions=(day,), window=1)["valid_day"].item()


def test_symbols_do_not_share_return_or_rolling_history():
    days = (dt.date(2026, 1, 5), dt.date(2026, 1, 6))
    a = pl.concat([_day(day) for day in days])
    b = _day(days[1], "000001.SZ", flat=True)
    combined = compute_intraday_low_frequency_factors(pl.concat([a, b]), sessions=days, window=2)
    assert_frame_equal(compute_intraday_low_frequency_factors(a, sessions=days, window=2),
                       combined.filter(pl.col("symbol") == "600000.SH"))
    assert combined.filter(pl.col("symbol") == "000001.SZ")["intraday_tail_amount20"].item() is None
