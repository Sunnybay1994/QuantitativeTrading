import calendar
import datetime as dt
import statistics

import polars as pl
import pytest

from quant.factors.earnings_surprise import compute_sue8
from quant.research.monthly_sue import build_monthly_sue


def income(values):
    rows, cumulative = [], 0.0
    for i, value in enumerate(values):
        year, quarter = 2020 + i // 4, i % 4 + 1
        cumulative = value if quarter == 1 else cumulative + value
        date = dt.date(year, quarter * 3, calendar.monthrange(year, quarter * 3)[1])
        announced = date + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": date, "report_type": "1",
                     "comp_type": "1", "n_income_attr_p": cumulative, "n_income": cumulative,
                     "ann_date": announced, "f_ann_date": announced, "available_date": announced,
                     "update_flag": "0", "source": "tushare"})
    return pl.DataFrame(rows)


def test_seasonal_difference_prior_window_and_single_quarters():
    values = [float(i * i + 5 * (i % 4)) for i in range(16)]
    frame = income(values)
    result = compute_sue8(frame)
    past = [values[i] - values[i - 4] for i in range(7, 15)]
    expected = (values[15] - values[11] - statistics.mean(past)) / statistics.stdev(past)
    assert result["_single_n_income_attr_p"].to_list() == values
    assert result["pit_sue8"][-1] == pytest.approx(expected)
    assert result["pit_sue8"][:12].null_count() == 12
    revised = frame.with_columns(pl.when(pl.col("end_date") == frame["end_date"][-1])
                                .then(pl.col("n_income_attr_p") + 100)
                                .otherwise(pl.col("n_income_attr_p")).alias("n_income_attr_p"))
    assert compute_sue8(revised)["_std"][-1] == result["_std"][-1]


def test_missing_quarter_and_zero_variance_are_null():
    frame = income([float(i * i) for i in range(16)])
    assert compute_sue8(frame.filter(pl.col("end_date") != frame["end_date"][7]))["pit_sue8"][-1] is None
    assert compute_sue8(income([float(i) for i in range(16)]))["pit_sue8"][-1] is None


def test_announcement_day_and_future_revision_cannot_leak():
    frame = income([float(i * i) for i in range(16)])
    date = frame["ann_date"][-1]
    result = build_monthly_sue(income_history=frame, signal_dates=(date, date + dt.timedelta(days=1)),
                             candidate_symbols=("000001.SZ", "000002.SZ"))
    stock = result.factors.filter(pl.col("symbol") == "000001.SZ")
    assert stock["financial_period_end"].to_list() == frame["end_date"][-2:].to_list()
    assert stock["pit_sue8"][-1] == pytest.approx(compute_sue8(frame)["pit_sue8"][-1])
    later = frame.tail(1).with_columns(pl.lit(date + dt.timedelta(days=10)).alias("ann_date"),
        pl.lit(date + dt.timedelta(days=10)).alias("f_ann_date"),
        pl.lit(date + dt.timedelta(days=10)).alias("available_date"),
        pl.lit("1").alias("update_flag"), pl.lit(99999.).alias("n_income_attr_p"))
    with_later = build_monthly_sue(income_history=pl.concat([frame, later]),
        signal_dates=(date, date + dt.timedelta(days=1)), candidate_symbols=("000001.SZ", "000002.SZ"))
    assert result.factors.equals(with_later.factors)


def test_conflicting_latest_revision_does_not_fall_back():
    frame = income([float(i * i) for i in range(16)])
    conflict = frame.tail(1).with_columns(pl.lit(99999.).alias("n_income_attr_p"))
    result = build_monthly_sue(income_history=pl.concat([frame, conflict]),
        signal_dates=(frame["ann_date"][-1] + dt.timedelta(days=1),), candidate_symbols=("000001.SZ",))
    assert result.factors["pit_sue8"][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_no_announcement_yet_returns_missing():
    result = build_monthly_sue(income_history=income([float(i * i) for i in range(16)]),
                              signal_dates=(dt.date(2019, 12, 31),), candidate_symbols=("000001.SZ",))
    assert result.factors["pit_sue8"][0] is None
