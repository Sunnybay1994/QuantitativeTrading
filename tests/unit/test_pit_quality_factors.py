from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.factors.pit_quality import (
    PIT_QUALITY_ELIGIBILITY_STATUSES,
    PIT_QUALITY_FACTOR_NAMES,
    PIT_QUALITY_FACTOR_SPECS,
    compute_pit_quality_factor_diagnostics,
    compute_pit_quality_factors,
)


def _frames(
    *, missing_quarter: int | None = None, comp_type: str = "1"
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    dates = [
        dt.date(2023, 3, 31),
        dt.date(2023, 6, 30),
        dt.date(2023, 9, 30),
        dt.date(2023, 12, 31),
    ]
    total_income = [10.0, 25.0, 45.0, 70.0]
    parent_income = [8.0, 20.0, 36.0, 56.0]
    operating_cash = [12.0, 22.0, 40.0, 68.0]
    income_rows = []
    cash_rows = []
    for quarter, day in enumerate(dates, start=1):
        if quarter == missing_quarter:
            continue
        key = {
            "symbol": "000001.SZ",
            "end_date": day,
            "report_type": "1",
            "comp_type": comp_type,
        }
        income_rows.append(
            key
            | {
                "n_income": total_income[quarter - 1],
                "n_income_attr_p": parent_income[quarter - 1],
            }
        )
        cash_rows.append(key | {"n_cashflow_act": operating_cash[quarter - 1]})
    balance = pl.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "end_date": dt.date(2022, 12, 31),
                "report_type": "1",
                "comp_type": comp_type,
                "total_assets": 100.0,
                "total_hldr_eqy_exc_min_int": 50.0,
            },
            {
                "symbol": "000001.SZ",
                "end_date": dt.date(2023, 12, 31),
                "report_type": "1",
                "comp_type": comp_type,
                "total_assets": 120.0,
                "total_hldr_eqy_exc_min_int": 60.0,
            },
        ]
    )
    return pl.DataFrame(income_rows), balance, pl.DataFrame(cash_rows)


def test_catalog_and_hand_calculated_ttm_factors_are_frozen() -> None:
    assert tuple(spec.name for spec in PIT_QUALITY_FACTOR_SPECS) == (PIT_QUALITY_FACTOR_NAMES)
    income, balance, cash = _frames()
    result = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    row = result.filter(pl.col("end_date") == dt.date(2023, 12, 31)).row(0, named=True)
    assert row["pit_roe_ttm"] == pytest.approx(56.0 / 55.0)
    assert row["pit_roa_ttm"] == pytest.approx(70.0 / 110.0)
    assert row["pit_cash_profit_quality_ttm"] == pytest.approx(68.0 / 70.0)
    assert row["pit_total_accruals_ttm"] == pytest.approx(2.0 / 110.0)


def test_missing_quarter_prevents_ttm_instead_of_bridging_gap() -> None:
    income, balance, cash = _frames(missing_quarter=2)
    result = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    row = result.filter(pl.col("end_date") == dt.date(2023, 12, 31))
    assert row.select(PIT_QUALITY_FACTOR_NAMES).row(0) == (None, None, None, None)


def test_nonindustrial_company_is_excluded() -> None:
    income, balance, cash = _frames(comp_type="2")
    result = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    assert result.is_empty()


def test_missing_cash_quarter_does_not_remove_profitability_factors() -> None:
    income, balance, cash = _frames()
    cash = cash.filter(pl.col("end_date") != dt.date(2023, 6, 30))
    result = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    row = result.filter(pl.col("end_date") == dt.date(2023, 12, 31)).row(0, named=True)
    assert row["pit_roe_ttm"] == pytest.approx(56.0 / 55.0)
    assert row["pit_roa_ttm"] == pytest.approx(70.0 / 110.0)
    assert row["pit_cash_profit_quality_ttm"] is None
    assert row["pit_total_accruals_ttm"] is None

    diagnostics = compute_pit_quality_factor_diagnostics(
        income=income,
        balance_sheet=balance,
        cash_flow=cash,
    ).filter(pl.col("end_date") == dt.date(2023, 12, 31))
    statuses = dict(diagnostics.select("factor", "status").iter_rows())
    assert statuses == {
        "pit_cash_profit_quality_ttm": "MISSING_CHAIN",
        "pit_roa_ttm": "VALID",
        "pit_roe_ttm": "VALID",
        "pit_total_accruals_ttm": "MISSING_CHAIN",
    }


def test_nonpositive_ttm_income_only_nulls_cash_profit_ratio() -> None:
    income, balance, cash = _frames()
    income = income.with_columns(
        pl.when(pl.col("end_date") == dt.date(2023, 12, 31))
        .then(-10.0)
        .otherwise(pl.col("n_income"))
        .alias("n_income")
    )
    result = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    row = result.filter(pl.col("end_date") == dt.date(2023, 12, 31)).row(0, named=True)
    assert row["pit_cash_profit_quality_ttm"] is None
    assert row["pit_roa_ttm"] is not None
    assert row["pit_total_accruals_ttm"] is not None
    diagnostic = compute_pit_quality_factor_diagnostics(
        income=income,
        balance_sheet=balance,
        cash_flow=cash,
    ).filter(
        (pl.col("end_date") == dt.date(2023, 12, 31))
        & (pl.col("factor") == "pit_cash_profit_quality_ttm")
    )
    assert diagnostic.get_column("status").item() == "INVALID_DENOMINATOR"


def test_diagnostics_keep_nonindustrial_rows_with_exact_status_vocabulary() -> None:
    income, balance, cash = _frames(comp_type="2")
    diagnostics = compute_pit_quality_factor_diagnostics(
        income=income,
        balance_sheet=balance,
        cash_flow=cash,
    )
    latest = diagnostics.filter(pl.col("end_date") == dt.date(2023, 12, 31))
    assert latest.height == len(PIT_QUALITY_FACTOR_NAMES)
    assert set(latest.get_column("status").to_list()) == {"NON_INDUSTRIAL"}
    assert set(latest.get_column("status").unique().to_list()) <= set(
        PIT_QUALITY_ELIGIBILITY_STATUSES
    )


def test_input_order_does_not_change_output() -> None:
    income, balance, cash = _frames()
    first = compute_pit_quality_factors(income=income, balance_sheet=balance, cash_flow=cash)
    second = compute_pit_quality_factors(
        income=income.reverse(),
        balance_sheet=balance.reverse(),
        cash_flow=cash.reverse(),
    )
    assert first.equals(second)


def test_duplicate_business_key_is_rejected() -> None:
    income, balance, cash = _frames()
    with pytest.raises(ValueError, match="PIT_QUALITY_FACTOR_INVALID") as exc:
        compute_pit_quality_factors(
            income=pl.concat([income, income.head(1)]),
            balance_sheet=balance,
            cash_flow=cash,
        )
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
