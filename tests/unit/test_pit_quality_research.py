from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.research.pit_quality_research import (
    build_pit_quality_signal_values,
    monthly_signal_sessions,
)


def _histories() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    periods = [
        dt.date(2023, 3, 31),
        dt.date(2023, 6, 30),
        dt.date(2023, 9, 30),
        dt.date(2023, 12, 31),
    ]
    available = [
        dt.date(2023, 4, 20),
        dt.date(2023, 8, 20),
        dt.date(2023, 10, 20),
        dt.date(2024, 4, 22),
    ]
    income_values = [10.0, 25.0, 45.0, 70.0]
    parent_values = [8.0, 20.0, 36.0, 56.0]
    cash_values = [12.0, 22.0, 40.0, 68.0]

    def common(index: int) -> dict[str, object]:
        return {
            "symbol": "000001.SZ",
            "ann_date": available[index],
            "f_ann_date": available[index],
            "available_date": available[index],
            "end_date": periods[index],
            "report_type": "1",
            "comp_type": "1",
            "update_flag": "0",
            "source": "tushare",
        }

    income = pl.DataFrame(
        [
            common(index)
            | {
                "n_income": income_values[index],
                "n_income_attr_p": parent_values[index],
            }
            for index in range(4)
        ]
    )
    cash = pl.DataFrame(
        [common(index) | {"n_cashflow_act": cash_values[index]} for index in range(4)]
    )
    balance = pl.DataFrame(
        [
            {
                **common(3),
                "ann_date": dt.date(2023, 4, 20),
                "f_ann_date": dt.date(2023, 4, 20),
                "available_date": dt.date(2023, 4, 20),
                "end_date": dt.date(2022, 12, 31),
                "total_assets": 100.0,
                "total_hldr_eqy_exc_min_int": 50.0,
            },
            {
                **common(3),
                "total_assets": 120.0,
                "total_hldr_eqy_exc_min_int": 60.0,
            },
        ]
    )
    return income, balance, cash


def test_monthly_signal_dates_are_exchange_sessions_not_calendar_month_ends() -> None:
    sessions = (
        dt.date(2024, 1, 30),
        dt.date(2024, 1, 31),
        dt.date(2024, 2, 28),
        dt.date(2024, 3, 29),
    )
    assert monthly_signal_sessions(
        sessions, start=dt.date(2024, 1, 1), end=dt.date(2024, 2, 29)
    ) == (dt.date(2024, 1, 31), dt.date(2024, 2, 28))


def test_monthly_signal_dates_exclude_a_truncated_final_month() -> None:
    sessions = (
        dt.date(2025, 1, 31),
        dt.date(2025, 2, 3),
        dt.date(2025, 2, 28),
        dt.date(2025, 3, 3),
        dt.date(2025, 3, 14),
    )
    assert monthly_signal_sessions(
        sessions, start=dt.date(2025, 1, 1), end=dt.date(2025, 3, 14)
    ) == (dt.date(2025, 1, 31), dt.date(2025, 2, 28))


def test_same_day_announcement_is_excluded_then_enters_next_signal() -> None:
    income, balance, cash = _histories()
    result = build_pit_quality_signal_values(
        income_history=income,
        balance_history=balance,
        cash_history=cash,
        signal_dates=(dt.date(2024, 4, 22), dt.date(2024, 4, 23)),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("1",),
    )
    same_day = result.factors.filter(pl.col("trade_date") == dt.date(2024, 4, 22))
    next_day = result.factors.filter(pl.col("trade_date") == dt.date(2024, 4, 23))
    assert same_day.get_column("financial_period_end").item() == dt.date(2023, 9, 30)
    assert same_day.get_column("pit_roe_ttm").item() is None
    assert next_day.get_column("financial_period_end").item() == dt.date(2023, 12, 31)
    assert next_day.get_column("pit_roe_ttm").item() == pytest.approx(56.0 / 55.0)
    assert next_day.get_column("pit_roa_ttm").item() == pytest.approx(70.0 / 110.0)
    assert result.quarantined.is_empty()


def test_latest_income_conflict_is_quarantined_without_older_period_fallback() -> None:
    income, balance, cash = _histories()
    conflict = income.tail(1).with_columns(pl.lit(71.0).alias("n_income"))
    result = build_pit_quality_signal_values(
        income_history=pl.concat([income, conflict]),
        balance_history=balance,
        cash_history=cash,
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("1",),
    )
    assert result.factors.select(PIT_QUALITY_FACTOR_NAMES).row(0) == (
        None,
        None,
        None,
        None,
    )
    assert set(result.eligibility.get_column("status").to_list()) == {"QUARANTINED"}
    assert result.quarantined.select(
        "dataset", "symbol", "end_date", "quarantine_reason"
    ).to_dicts() == [
        {
            "dataset": "income",
            "symbol": "000001.SZ",
            "end_date": dt.date(2023, 12, 31),
            "quarantine_reason": "LATEST_REVISION_CONFLICT",
        }
    ]


def test_cash_conflict_only_quarantines_cash_dependent_factors() -> None:
    income, balance, cash = _histories()
    conflict = cash.tail(1).with_columns(pl.lit(69.0).alias("n_cashflow_act"))
    result = build_pit_quality_signal_values(
        income_history=income,
        balance_history=balance,
        cash_history=pl.concat([cash, conflict]),
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("1",),
    )
    statuses = dict(result.eligibility.select("factor", "status").iter_rows())
    assert statuses == {
        "pit_cash_profit_quality_ttm": "QUARANTINED",
        "pit_roa_ttm": "VALID",
        "pit_roe_ttm": "VALID",
        "pit_total_accruals_ttm": "QUARANTINED",
    }


def test_signal_result_is_independent_of_history_row_order() -> None:
    income, balance, cash = _histories()
    first = build_pit_quality_signal_values(
        income_history=income,
        balance_history=balance,
        cash_history=cash,
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("1",),
    )
    second = build_pit_quality_signal_values(
        income_history=income.reverse(),
        balance_history=balance.reverse(),
        cash_history=cash.reverse(),
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("1",),
    )
    assert first.factors.equals(second.factors)
    assert first.eligibility.equals(second.eligibility)
    assert first.quarantined.equals(second.quarantined)


def test_eligibility_keeps_missing_candidates_in_the_frozen_denominator() -> None:
    income, balance, cash = _histories()
    result = build_pit_quality_signal_values(
        income_history=income,
        balance_history=balance,
        cash_history=cash,
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ", "000002.SZ"),
        allowed_report_types=("1",),
    )
    missing = result.eligibility.filter(pl.col("symbol") == "000002.SZ")
    assert missing.height == len(PIT_QUALITY_FACTOR_NAMES)
    assert set(missing.get_column("status").to_list()) == {"MISSING_CHAIN"}
    assert result.eligibility.height == 2 * len(PIT_QUALITY_FACTOR_NAMES)


def test_invalid_signal_contract_is_sanitized() -> None:
    income, balance, cash = _histories()
    with pytest.raises(ValueError, match="PIT_QUALITY_RESEARCH_INVALID") as exc:
        build_pit_quality_signal_values(
            income_history=income,
            balance_history=balance,
            cash_history=cash,
            signal_dates=(dt.date(2024, 4, 23), dt.date(2024, 4, 22)),
            candidate_symbols=("000001.SZ",),
            allowed_report_types=("1",),
        )
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


def test_report_type_must_be_pre_frozen_and_is_not_hard_coded() -> None:
    income, balance, cash = _histories()
    with pytest.raises(ValueError):
        build_pit_quality_signal_values(
            income_history=income,
            balance_history=balance,
            cash_history=cash,
            signal_dates=(dt.date(2024, 4, 23),),
            candidate_symbols=("000001.SZ",),
            allowed_report_types=(),
        )

    type_two = tuple(
        frame.with_columns(pl.lit("2").alias("report_type"))
        for frame in (income, balance, cash)
    )
    result = build_pit_quality_signal_values(
        income_history=type_two[0],
        balance_history=type_two[1],
        cash_history=type_two[2],
        signal_dates=(dt.date(2024, 4, 23),),
        candidate_symbols=("000001.SZ",),
        allowed_report_types=("2",),
    )
    assert result.factors.get_column("pit_roe_ttm").item() == pytest.approx(56.0 / 55.0)
