import datetime as dt

import polars as pl
import pytest

from quant.factors.cash_yield import compute_cash_yield, compute_ocf_ttm
from quant.research.monthly_cash_yield import build_monthly_cash_yield


def cash_history():
    rows = []
    for date, cash in [("2022-12-31", 90.), ("2023-03-31", 10.), ("2023-06-30", 25.), ("2023-09-30", 45.),
                       ("2023-12-31", 70.), ("2024-03-31", 20.)]:
        end = dt.date.fromisoformat(date)
        ann = end + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                     "n_cashflow_act": cash, "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                     "update_flag": "0", "source": "tushare"})
    return pl.DataFrame(rows)


def basic():
    return pl.DataFrame({"symbol": ["000001.SZ"] * 2,
                         "trade_date": [dt.date(2024, 4, 20), dt.date(2024, 4, 21)],
                         "total_market_value": [1000., 2000.]})


def build(cash, capital):
    return build_monthly_cash_yield(cash_history=cash, daily_basic=capital,
        signal_dates=(dt.date(2024, 4, 20), dt.date(2024, 4, 21)), candidate_symbols=("000001.SZ",))


def test_ttm_and_exact_day_yuan_capitalization_with_announcement_lag():
    result = build(cash_history(), basic())
    assert result.factors["pit_cash_yield_ttm"].to_list() == [pytest.approx(.07), pytest.approx(.04)]
    assert compute_ocf_ttm(cash_history().reverse())["ocf_ttm"][-1] == 80.
    assert build(cash_history(), basic().head(1)).factors["pit_cash_yield_ttm"][-1] is None


@pytest.mark.parametrize("market_value", [0., -10., None, float("nan"), float("inf")])
def test_invalid_denominator(market_value):
    capital = basic().with_columns(pl.lit(market_value, dtype=pl.Float64).alias("total_market_value"))
    assert build(cash_history(), capital).factors["pit_cash_yield_ttm"].null_count() == 2


def test_missing_quarter_and_invalid_latest_cash_no_fallback():
    c = cash_history()
    assert build(c.filter(pl.col("end_date") != dt.date(2023, 6, 30)), basic()).factors[
        "pit_cash_yield_ttm"].null_count() == 2
    c = c.with_columns(pl.when(pl.col("end_date") == dt.date(2024, 3, 31)).then(float("inf"))
                      .otherwise(pl.col("n_cashflow_act")).alias("n_cashflow_act"))
    assert build(c, basic()).factors["pit_cash_yield_ttm"].to_list() == [pytest.approx(.07), None]


def test_negative_cash_and_future_revision():
    c = cash_history().with_columns(-pl.col("n_cashflow_act"))
    expected = build(c, basic()).factors
    assert expected["pit_cash_yield_ttm"][-1] == pytest.approx(-.04)
    future = c.tail(1).with_columns(pl.lit(900.).alias("n_cashflow_act"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2024, 5, 20)).alias(col) for col in ("ann_date", "f_ann_date", "available_date")])
    assert build(pl.concat([c, future]), basic()).factors.equals(expected)


def test_conflicting_cash_revision_and_duplicate_capital():
    c = cash_history()
    conflict = pl.concat([c, c.tail(1).with_columns(pl.lit(30.).alias("n_cashflow_act"))])
    result = build(conflict, basic())
    assert result.factors["pit_cash_yield_ttm"][-1] is None
    assert result.eligibility["status"][-1] == "QUARANTINED"
    with pytest.raises(pl.exceptions.ComputeError):
        compute_cash_yield(result.factors.drop("total_market_value", "pit_cash_yield_ttm"),
                           pl.concat([basic(), basic()]))
