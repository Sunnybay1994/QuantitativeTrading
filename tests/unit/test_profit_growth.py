import datetime as dt

import polars as pl
import pytest

from quant.factors.profit_growth import compute_profit_growth
from quant.research.monthly_profit_growth import build_monthly_profit_growth


def history():
    rows = []
    for year, quarters in [(2022, [10., 20., 30., 40.]), (2023, [20., 30., 40., 50.]),
                           (2024, [30.])]:
        cumulative = 0.
        for i, value in enumerate(quarters):
            month, day = [(3, 31), (6, 30), (9, 30), (12, 31)][i]
            end = dt.date(year, month, day)
            cumulative += value
            ann = end + dt.timedelta(days=20)
            rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                "n_income": 1., "n_income_attr_p": cumulative,
                "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                "update_flag": "0", "source": "tushare"})
    prior = dict(rows[0], end_date=dt.date(2021,12,31), n_income_attr_p=80.,
        ann_date=dt.date(2022,1,20), f_ann_date=dt.date(2022,1,20), available_date=dt.date(2022,1,20))
    return pl.DataFrame([prior, *rows])


def build(income, *dates):
    return build_monthly_profit_growth(income_history=income, signal_dates=dates,
                                       candidate_symbols=("000001.SZ",))


def test_hand_computed_ttm_growth_and_gap():
    income = history()
    result = compute_profit_growth(income)
    assert result["pit_profit_growth_ttm"].to_list() == [None]*8 + [pytest.approx(.4), pytest.approx(150/110-1)]
    assert result["parent_profit_ttm"][-1] == 150
    assert result["parent_profit_ttm_lag4"][-1] == 110
    missing = income.filter(pl.col("end_date") != dt.date(2022, 6, 30))
    assert compute_profit_growth(missing)["pit_profit_growth_ttm"][-1] is None
    with pytest.raises(ValueError, match="Duplicate"):
        compute_profit_growth(pl.concat([income, income.tail(1)]))


@pytest.mark.parametrize("prior,current,expected", [(0.,100.,None),(-100.,-50.,.5),(-100.,-150.,-.5),(-100.,50.,1.5),
    (100.,0.,-1.),(100.,-50.,-1.5),(100.,50.,-.5),(100.,float('inf'),None)])
def test_ttm_denominators(prior, current, expected):
    income = history().filter(pl.col("end_date")<=dt.date(2023,12,31)).with_columns(
        pl.when(pl.col("end_date").dt.year()==2022).then(prior)
        .otherwise(current).alias("n_income_attr_p"))
    assert compute_profit_growth(income)["pit_profit_growth_ttm"][-1] == expected


def test_pit_lag_revision_and_invalid_latest():
    income=history()
    before, after=dt.date(2024,4,20),dt.date(2024,4,21)
    result=build(income,before,after)
    assert result.factors["pit_profit_growth_ttm"].to_list()==[pytest.approx(.4),pytest.approx(150/110-1)]
    revision=income.tail(1).with_columns(pl.lit(90.).alias("n_income_attr_p"),pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2024,5,20)).alias(c) for c in ("ann_date","f_ann_date","available_date")])
    assert build(pl.concat([income,revision]),before,after).factors.equals(result.factors)
    invalid=income.with_columns(pl.when(pl.col("end_date")==dt.date(2024,3,31))
                               .then(None).otherwise(pl.col("n_income_attr_p")).alias("n_income_attr_p"))
    assert build(invalid,after).factors["pit_profit_growth_ttm"][0] is None
    assert build(income,dt.date(2020,1,1)).factors["pit_profit_growth_ttm"][0] is None


def test_conflicting_denominator_revision_is_quarantined():
    income=history()
    conflict=income.filter(pl.col("end_date")==dt.date(2022,12,31)).with_columns(pl.lit(99.).alias("n_income_attr_p"))
    result=build(pl.concat([income,conflict]),dt.date(2024,4,21))
    assert result.factors["pit_profit_growth_ttm"][0] is None
    assert result.eligibility["status"][0]=='QUARANTINED'
