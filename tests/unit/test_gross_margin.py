import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.factors.gross_margin import compute_gross_margin
from quant.research.monthly_gross_margin import build_monthly_gross_margin
from quant.research.monthly_financial_factors import read_monthly_financial_factors


def history():
    rows = []
    for end, revenue, cost in [
        (dt.date(2022, 12, 31), 90., 60.),
        (dt.date(2023, 3, 31), 10., 6.), (dt.date(2023, 6, 30), 25., 15.),
        (dt.date(2023, 9, 30), 45., 27.), (dt.date(2023, 12, 31), 70., 42.),
        (dt.date(2024, 3, 31), 20., 8.),
    ]:
        ann = end + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                     "n_income": 1., "n_income_attr_p": 1., "revenue": revenue, "oper_cost": cost,
                     "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                     "update_flag": "0", "source": "tushare"})
    return pl.DataFrame(rows)


def build(income, *dates):
    return build_monthly_gross_margin(income_history=income, signal_dates=dates,
                                     candidate_symbols=("000001.SZ",))


def test_hand_computed_ttm_and_missing_quarters():
    income = history()
    result = compute_gross_margin(income)
    assert result["pit_gross_margin_ttm"].to_list() == [None, None, None, None, pytest.approx(.4), pytest.approx(.45)]
    assert result["revenue_ttm"][-1] == 80
    assert result["oper_cost_ttm"][-1] == 44
    missing = income.filter(pl.col("end_date") != dt.date(2023, 6, 30))
    assert compute_gross_margin(missing)["pit_gross_margin_ttm"][-1] is None
    with pytest.raises(ValueError, match="Duplicate"):
        compute_gross_margin(pl.concat([income, income.tail(1)]))


@pytest.mark.parametrize("revenue,cost,expected", [(0., 0., None), (-1., 0., None), (1., -1., None),
                                                  (2., 3., -.5), (2., 0., 1.), (float('inf'), 1., None)])
def test_denominators_and_negative_margin(revenue, cost, expected):
    income = history().with_columns(pl.lit(revenue).alias("revenue"), pl.lit(cost).alias("oper_cost"))
    assert compute_gross_margin(income)["pit_gross_margin_ttm"][-1] == expected


def test_pit_lag_future_revision_and_latest_invalid():
    income = history()
    before, after = dt.date(2024, 4, 20), dt.date(2024, 4, 21)
    result = build(income, before, after)
    assert result.factors["pit_gross_margin_ttm"].to_list() == [pytest.approx(.4), pytest.approx(.45)]
    future = income.tail(1).with_columns(pl.lit(90.).alias("revenue"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2024, 5, 20)).alias(col) for col in ("ann_date", "f_ann_date", "available_date")])
    assert build(pl.concat([income, future]), before, after).factors.equals(result.factors)
    invalid = income.with_columns(pl.when(pl.col("end_date") == dt.date(2024, 3, 31))
                                  .then(None).otherwise(pl.col("revenue")).alias("revenue"))
    assert build(invalid, after).factors["pit_gross_margin_ttm"][0] is None
    assert build(income, dt.date(2020, 1, 1)).factors["pit_gross_margin_ttm"][0] is None


def test_conflicting_revision_is_quarantined():
    income = history()
    conflict = pl.concat([income, income.tail(1).with_columns(pl.lit(30.).alias("revenue"))])
    result = build(conflict, dt.date(2024, 4, 21))
    assert result.factors["pit_gross_margin_ttm"][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_monthly_loader_reads_income_fields_only(monkeypatch):
    calls = []

    def read(*, data_root, query):
        calls.append(query)
        return history()

    monkeypatch.setattr("quant.research.monthly_financial_factors.read_tushare_financial_history", read)
    result, histories = read_monthly_financial_factors(
        data_root=Path("unused"), candidates=("000001.SZ",),
        sessions=(dt.date(2024, 4, 29), dt.date(2024, 4, 30), dt.date(2024, 5, 2)),
        start=dt.date(2024, 4, 1), end=dt.date(2024, 4, 30),
        settings={"company_type": "1", "signal_frequency": "completed_month_end",
                  "availability": "strictly_before_signal_date", "missing_quarter": "null",
                  "allowed_report_types": ["1"], "factor_family": "gross_margin",
                  "snapshot_id": "fixture", "history_start": dt.date(2022, 1, 1)},
    )
    assert list(histories) == ["income"]
    assert len(calls) == 1 and calls[0].extra_fields == ("revenue", "oper_cost")
    assert result.factors["pit_gross_margin_ttm"].to_list() == [pytest.approx(.45)]
