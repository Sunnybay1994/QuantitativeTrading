import datetime as dt

import polars as pl
import pytest

from quant.factors.inventory_expansion import compute_inventory_expansion
from quant.research.factor_financials import attach_financial_factors
from quant.research.monthly_inventory_expansion import build_monthly_inventory_expansion
from tests.unit.test_asset_growth import history

NAME = "pit_inventory_expansion_yoy"


def sample():
    return history().with_columns(pl.Series("inventories", [8., 10., 17., 32.]))


def build(frame, *dates):
    return build_monthly_inventory_expansion(balance_history=frame, signal_dates=dates,
                                             candidate_symbols=("000001.SZ",))


def test_same_quarter_and_average_assets():
    f = sample()
    assert compute_inventory_expansion(f)[NAME].to_list() == [None, None, pytest.approx(9 / 85), .2]
    assert compute_inventory_expansion(f.filter(pl.col("end_date") != dt.date(2024, 6, 30)))[NAME][-1] is None
    assert compute_inventory_expansion(f.with_columns(pl.lit(0.).alias("inventories")))[NAME][-1] == 0


@pytest.mark.parametrize("field,value", [("inventories", None), ("inventories", -1.),
    ("inventories", float("inf")), ("inventories", float("nan")), ("total_assets", 0.),
    ("total_assets", float("inf"))])
@pytest.mark.parametrize("index", [1, 3])
def test_invalid_endpoint_does_not_fall_back(field, value, index):
    f = sample().with_row_index().with_columns(
        pl.when(pl.col("index") == index).then(pl.lit(value, dtype=pl.Float64))
        .otherwise(pl.col(field)).alias(field)).drop("index")
    assert build(f, dt.date(2025, 8, 31)).factors[NAME][0] is None


def test_announcements_revisions_and_daily_carry():
    f = sample()
    dates = (dt.date(2025, 7, 20), dt.date(2025, 7, 21), dt.date(2025, 8, 21))
    revision = f.tail(1).with_columns(pl.lit(54.).alias("inventories"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2025, 8, 20)).alias(c) for c in ("ann_date", "f_ann_date", "available_date")])
    revised = pl.concat([f, revision])
    assert build(revised, *dates).factors[NAME].to_list() == [pytest.approx(9 / 85), .2, .4]
    panel = pl.DataFrame({"symbol": ["000001.SZ"] * 3, "trade_date": dates, "close": [10.] * 3})
    actual = attach_financial_factors(panel, {"balancesheet": revised}, (NAME,))
    assert actual[NAME].to_list() == [pytest.approx(9 / 85), .2, .4]


@pytest.mark.parametrize("index", [1, 3])
def test_inventory_revision_conflict_is_excluded(index):
    f = sample()
    result = build(pl.concat([f, f.slice(index, 1).with_columns(pl.lit(90.).alias("inventories"))]),
                   dt.date(2025, 8, 31))
    assert result.factors[NAME][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_financial_company_and_not_yet_published():
    assert build(sample().with_columns(pl.lit("2").alias("comp_type")), dt.date(2025, 8, 31)).factors[NAME][0] is None
    assert build(sample(), dt.date(2023, 12, 31)).factors[NAME][0] is None
