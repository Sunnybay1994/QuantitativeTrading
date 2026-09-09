import datetime as dt

import polars as pl
import pytest

from quant.factors.asset_growth import compute_asset_growth
from quant.research.monthly_asset_growth import build_monthly_asset_growth


def history():
    rows = []
    for year, month, day, value in [(2024, 3, 31, 80.), (2024, 6, 30, 100.),
                                   (2025, 3, 31, 90.), (2025, 6, 30, 120.)]:
        end = dt.date(year, month, day)
        ann = end + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                     "total_assets": value, "total_hldr_eqy_exc_min_int": value / 2,
                     "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                     "update_flag": "0", "source": "tushare"})
    return pl.DataFrame(rows)


def build(frame, *dates):
    return build_monthly_asset_growth(balance_history=frame, signal_dates=dates,
                                      candidate_symbols=("000001.SZ",))


def test_exact_calendar_comparison_and_positive_assets():
    f = history()
    assert compute_asset_growth(f)["pit_asset_growth_yoy"].to_list() == [None, None, .125, pytest.approx(.2)]
    assert compute_asset_growth(f.filter(pl.col("end_date") != dt.date(2024, 6, 30)))["pit_asset_growth_yoy"][-1] is None
    for period in (dt.date(2024, 6, 30), dt.date(2025, 6, 30)):
        bad = f.with_columns(pl.when(pl.col("end_date") == period).then(0.).otherwise(pl.col("total_assets")).alias("total_assets"))
        assert compute_asset_growth(bad)["pit_asset_growth_yoy"][-1] is None


def test_same_day_announcement_and_future_revision():
    f = history()
    a, b = dt.date(2025, 7, 20), dt.date(2025, 7, 21)
    expected = build(f, a, b)
    assert expected.factors["pit_asset_growth_yoy"].to_list() == [.125, pytest.approx(.2)]
    revised = f.tail(1).with_columns(pl.lit(400.).alias("total_assets"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2025, 8, 20)).alias(c) for c in ("ann_date", "f_ann_date", "available_date")])
    assert build(pl.concat([f, revised]), a, b).factors.equals(expected.factors)


@pytest.mark.parametrize("index", [1, 3])
def test_conflicting_current_or_denominator_period_is_excluded(index):
    f = history()
    conflict = f.slice(index, 1).with_columns(pl.lit(400.).alias("total_assets"))
    result = build(pl.concat([f, conflict]), dt.date(2025, 8, 31))
    assert result.factors["pit_asset_growth_yoy"][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_invalid_latest_period_does_not_fall_back():
    f = history().with_columns(pl.when(pl.col("end_date") == dt.date(2025, 6, 30))
        .then(0.).otherwise(pl.col("total_assets")).alias("total_assets"))
    assert build(f, dt.date(2025, 8, 31)).factors["pit_asset_growth_yoy"][0] is None


def test_no_announced_data_is_missing():
    assert build(history(), dt.date(2023, 12, 31)).factors["pit_asset_growth_yoy"][0] is None
