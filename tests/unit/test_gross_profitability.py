import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history
from quant.factors.gross_profitability import compute_gross_profitability
from quant.research.monthly_gross_profitability import build_monthly_gross_profitability


def histories():
    rows = []
    for y, m, d, revenue, cost in [(2022, 12, 31, 90., 60.), (2023, 3, 31, 10., 6.),
                                  (2023, 6, 30, 25., 15.), (2023, 9, 30, 45., 27.),
                                  (2023, 12, 31, 70., 42.), (2024, 3, 31, 20., 8.)]:
        end = dt.date(y, m, d)
        ann = end + dt.timedelta(days=20)
        rows.append({"symbol": "000001.SZ", "end_date": end, "report_type": "1", "comp_type": "1",
                     "n_income": 1., "n_income_attr_p": 1., "revenue": revenue, "oper_cost": cost,
                     "ann_date": ann, "f_ann_date": ann, "available_date": ann,
                     "update_flag": "0", "source": "tushare"})
    income = pl.DataFrame(rows)
    balance = income.tail(2).drop("n_income", "n_income_attr_p", "revenue", "oper_cost").with_columns(
        pl.lit(100.).alias("total_assets"), pl.lit(50.).alias("total_hldr_eqy_exc_min_int"))
    return income, balance


def build(income, balance, *dates):
    return build_monthly_gross_profitability(income_history=income, balance_history=balance,
        signal_dates=dates, candidate_symbols=("000001.SZ",))


def test_cumulative_to_ttm_and_matching_balance_period():
    i, b = histories()
    row = compute_gross_profitability(i, b).tail(1).to_dicts()[0]
    assert row["revenue_ttm"] == 80
    assert row["oper_cost_ttm"] == 44
    assert row["pit_gross_profitability_ttm"] == pytest.approx(.36)
    assert compute_gross_profitability(i, b.head(1))["pit_gross_profitability_ttm"][-1] is None
    missing = i.filter(pl.col("end_date") != dt.date(2023, 6, 30))
    assert compute_gross_profitability(missing, b)["pit_gross_profitability_ttm"][-1] is None


def test_announcement_lag_future_income_revision_and_latest_invalid():
    i, b = histories()
    a, c = dt.date(2024, 4, 20), dt.date(2024, 4, 21)
    expected = build(i, b, a, c)
    assert expected.factors["pit_gross_profitability_ttm"].to_list() == [pytest.approx(.28), pytest.approx(.36)]
    future = i.tail(1).with_columns(pl.lit(90.).alias("revenue"), pl.lit("1").alias("update_flag"),
        *[pl.lit(dt.date(2024, 5, 20)).alias(col) for col in ("ann_date", "f_ann_date", "available_date")])
    assert build(pl.concat([i, future]), b, a, c).factors.equals(expected.factors)
    assert build(i, b.head(1), c).factors["pit_gross_profitability_ttm"][0] is None


@pytest.mark.parametrize("dataset", ["income", "balance"])
def test_revenue_or_asset_conflict_is_excluded(dataset):
    i, b = histories()
    if dataset == "income":
        i = pl.concat([i, i.tail(1).with_columns(pl.lit(30.).alias("revenue"))])
    else:
        b = pl.concat([b, b.tail(1).with_columns(pl.lit(110.).alias("total_assets"))])
    result = build(i, b, dt.date(2024, 4, 21))
    assert result.factors["pit_gross_profitability_ttm"][0] is None
    assert result.eligibility["status"][0] == "QUARANTINED"


def test_invalid_assets_and_empty_known_history():
    i, b = histories()
    assert compute_gross_profitability(i, b.with_columns(pl.lit(0.).alias("total_assets")))["pit_gross_profitability_ttm"][-1] is None
    assert build(i, b, dt.date(2020, 1, 1)).factors["pit_gross_profitability_ttm"][0] is None


def test_optional_revenue_columns_preserved_without_changing_default(tmp_path: Path):
    i, _ = histories()
    root = tmp_path / "clean/tushare_financials/fixture"
    root.mkdir(parents=True)
    i.write_parquet(root / "income.parquet")
    kwargs = dict(snapshot_id="fixture", dataset="income", start_period=dt.date(2022, 1, 1),
                  end_period=dt.date(2024, 12, 31), symbols=("000001.SZ",))
    ordinary = read_tushare_financial_history(data_root=tmp_path, query=TushareFinancialHistoryQuery(**kwargs))
    extended = read_tushare_financial_history(data_root=tmp_path, query=TushareFinancialHistoryQuery(
        **kwargs, extra_fields=("revenue", "oper_cost")))
    assert "revenue" not in ordinary.columns
    assert extended["revenue"].to_list() == i["revenue"].to_list()
    with pytest.raises(ValueError, match="Unsupported financial fields"):
        read_tushare_financial_history(data_root=tmp_path, query=TushareFinancialHistoryQuery(
            **kwargs, extra_fields=("unknown",)))


def test_optional_long_term_debt_keeps_missing_values(tmp_path: Path):
    _, balances = histories()
    balances = balances.with_columns(pl.lit(10.0).alias('lt_borr'), pl.lit(None, dtype=pl.Float64).alias('bond_payable'))
    root = tmp_path / 'clean/tushare_financials/fixture'
    root.mkdir(parents=True)
    balances.write_parquet(root / 'balancesheet.parquet')
    query = TushareFinancialHistoryQuery(
        snapshot_id='fixture', dataset='balancesheet', start_period=dt.date(2022, 1, 1),
        end_period=dt.date(2024, 12, 31), symbols=('000001.SZ',), extra_fields=('lt_borr', 'bond_payable'))
    result = read_tushare_financial_history(data_root=tmp_path, query=query)
    assert result.height == balances.height
    assert result['lt_borr'].to_list() == [10.0] * result.height
    assert result['bond_payable'].null_count() == result.height
    assert result.select((pl.col('lt_borr') + pl.col('bond_payable')).alias('debt'))['debt'].null_count() == result.height
