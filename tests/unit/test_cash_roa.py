import datetime as dt

import polars as pl
import pytest

from quant.factors.cash_roa import compute_cash_roa
from quant.research.monthly_cash_roa import build_monthly_cash_roa


def histories():
    rows = []
    for date, cash in [("2022-12-31", 90.), ("2023-03-31", 10.), ("2023-06-30", 25.),
                       ("2023-09-30", 45.), ("2023-12-31", 70.), ("2024-03-31", 20.)]:
        end = dt.date.fromisoformat(date)
        ann = end + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                     "n_cashflow_act": cash, "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                     "update_flag": "0", "source": "tushare"})
    cash = pl.DataFrame(rows)
    balance = cash.drop("n_cashflow_act").with_columns(
        pl.when(pl.col("end_date").dt.year() < 2024).then(100.).otherwise(300.).alias("total_assets"),
        pl.lit(50.).alias("total_hldr_eqy_exc_min_int"))
    return cash, balance


def build(cash, balance, *dates):
    return build_monthly_cash_roa(cash_history=cash, balance_history=balance,
                                 signal_dates=dates, candidate_symbols=("000001.SZ",))


def test_single_quarters_average_assets_and_missing_chain():
    c, b = histories()
    row = compute_cash_roa(c.reverse(), b.reverse()).tail(1).to_dicts()[0]
    assert row["ocf_ttm"] == 80
    assert row["average_assets"] == 200
    assert row["pit_cash_roa_ttm"] == pytest.approx(.4)
    for table in ("cash", "balance"):
        cut = (c if table == "cash" else b).filter(pl.col("end_date") != dt.date(2023, 3, 31))
        result = compute_cash_roa(cut if table == "cash" else c, cut if table == "balance" else b)
        assert result["pit_cash_roa_ttm"][-1] is None


def test_negative_ocf_is_eligible():
    c, b = histories()
    c = c.with_columns(-pl.col("n_cashflow_act"))
    assert compute_cash_roa(c, b)["pit_cash_roa_ttm"][-1] == pytest.approx(-.4)


@pytest.mark.parametrize("asset", [0., -1., float("inf"), float("nan")])
@pytest.mark.parametrize("period", [dt.date(2023, 3, 31), dt.date(2024, 3, 31)])
def test_each_asset_endpoint_must_be_finite_positive(asset, period):
    c, b = histories()
    b = b.with_columns(pl.when(pl.col("end_date") == period).then(asset)
                       .otherwise(pl.col("total_assets")).alias("total_assets"))
    assert compute_cash_roa(c, b)["pit_cash_roa_ttm"][-1] is None


def test_strict_announcement_future_revision_and_no_stale_fallback():
    c, b = histories()
    date1, date2 = dt.date(2024, 4, 20), dt.date(2024, 4, 21)
    expected = build(c, b, date1, date2)
    assert expected.factors["pit_cash_roa_ttm"].to_list() == [pytest.approx(.7), pytest.approx(.4)]
    future = c.tail(1).with_columns(pl.lit(900.).alias("n_cashflow_act"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2024, 5, 20)).alias(col) for col in ("ann_date", "f_ann_date", "available_date")])
    assert build(pl.concat([c, future]), b, date1, date2).factors.equals(expected.factors)
    assert build(c, b.head(5), date2).factors["pit_cash_roa_ttm"][0] is None
    assert build(c, b, dt.date(2020, 1, 1)).factors["pit_cash_roa_ttm"][0] is None


@pytest.mark.parametrize("dataset", ["cash", "current_assets", "prior_assets"])
def test_conflicting_revisions_are_quarantined(dataset):
    c, b = histories()
    if dataset == "cash":
        c = pl.concat([c, c.tail(1).with_columns(pl.lit(30.).alias("n_cashflow_act"))])
    else:
        period = dt.date(2023 if dataset == "prior_assets" else 2024, 3, 31)
        b = pl.concat([b, b.filter(pl.col("end_date") == period).with_columns(pl.lit(110.).alias("total_assets"))])
    result = build(c, b, dt.date(2024, 4, 21))
    assert result.factors["pit_cash_roa_ttm"][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_duplicate_period_and_invalid_cash():
    c, b = histories()
    with pytest.raises(ValueError, match="Duplicate"):
        compute_cash_roa(pl.concat([c, c.tail(1)]), b)
    c = c.with_columns(pl.when(pl.col("end_date") == dt.date(2024, 3, 31)).then(float("inf"))
                      .otherwise(pl.col("n_cashflow_act")).alias("n_cashflow_act"))
    assert compute_cash_roa(c, b)["pit_cash_roa_ttm"][-1] is None
