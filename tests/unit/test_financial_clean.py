from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.data.financial_clean import (
    FinancialCleanError,
    normalize_tushare_financial_frame,
    project_selected_financial_factor_frame,
)
from quant.data.financial_pit import select_financial_revisions_as_of


def _income(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20240420",
        "f_ann_date": "20240422",
        "end_date": "20231231",
        "report_type": "1",
        "comp_type": "1",
        "update_flag": "0",
        "n_income": "100.5",
        "n_income_attr_p": 90.25,
    }
    row.update(overrides)
    return row


def test_schema_drift_is_normalized_to_float_without_filling_nulls() -> None:
    result = normalize_tushare_financial_frame(
        pl.DataFrame(
            [
                _income(),
                _income(
                    ts_code="000002.SZ",
                    n_income=None,
                    n_income_attr_p="",
                ),
            ]
        ),
        dataset="income",
    )
    assert result.quarantined.is_empty()
    assert result.clean.schema["n_income"] == pl.Float64
    assert result.clean.schema["n_income_attr_p"] == pl.Float64
    assert result.clean.get_column("n_income").to_list() == [100.5, None]
    assert result.clean.get_column("n_income_attr_p").to_list() == [90.25, None]
    assert result.clean.get_column("source").to_list() == ["tushare", "tushare"]


@pytest.mark.parametrize("bad_value", ["not-a-number", "NaN", "inf"])
def test_nonempty_invalid_economic_value_is_quarantined(bad_value: str) -> None:
    result = normalize_tushare_financial_frame(
        pl.DataFrame([_income(n_income=bad_value)]), dataset="income"
    )
    assert result.clean.is_empty()
    assert result.quarantined.get_column("quarantine_reason").item() == ("REQUIRED_NUMERIC_INVALID")


@pytest.mark.parametrize("bad_update_flag", ["2", None])
def test_structural_invalidity_is_quarantined_without_guessing(
    bad_update_flag: object,
) -> None:
    result = normalize_tushare_financial_frame(
        pl.DataFrame(
            [
                _income(ts_code="BAD"),
                _income(ts_code="000002.SZ", update_flag=bad_update_flag),
            ]
        ),
        dataset="income",
    )
    assert result.clean.is_empty()
    assert result.quarantined.get_column("quarantine_reason").to_list() == [
        "SYMBOL_INVALID",
        "UPDATE_FLAG_INVALID",
    ]


def test_update_flag_pair_survives_normalization_then_pit_prefers_update() -> None:
    normalized = normalize_tushare_financial_frame(
        pl.DataFrame([_income(update_flag="0"), _income(update_flag="1")]),
        dataset="income",
    )
    assert normalized.clean.height == 2
    selected = select_financial_revisions_as_of(
        normalized.clean,
        dataset="income",
        as_of=dt.date(2024, 4, 23),
    ).selected
    assert selected.get_column("update_flag").item() == "1"
    factor = project_selected_financial_factor_frame(selected, dataset="income")
    assert factor.columns == [
        "symbol",
        "end_date",
        "report_type",
        "comp_type",
        "n_income",
        "n_income_attr_p",
    ]
    assert factor.get_column("end_date").item() == dt.date(2023, 12, 31)


def test_normalization_and_projection_are_row_order_invariant() -> None:
    rows = [
        _income(),
        _income(
            ts_code="000002.SZ",
            end_date="20230930",
            ann_date="20231020",
            f_ann_date=None,
            n_income="70",
        ),
    ]
    first = normalize_tushare_financial_frame(pl.DataFrame(rows), dataset="income")
    second = normalize_tushare_financial_frame(pl.DataFrame(list(reversed(rows))), dataset="income")
    assert first.clean.equals(second.clean)
    assert first.quarantined.equals(second.quarantined)


def test_indicator_contract_and_invalid_input_are_sanitized() -> None:
    indicator = normalize_tushare_financial_frame(
        pl.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "ann_date": ["20240420"],
                "end_date": ["20231231"],
            }
        ),
        dataset="fina_indicator",
    )
    assert indicator.clean.columns == [
        "ts_code",
        "ann_date",
        "end_date",
        "source",
    ]
    with pytest.raises(FinancialCleanError, match="TUSHARE_FINANCIAL_CLEAN_INVALID") as exc:
        normalize_tushare_financial_frame(
            pl.DataFrame({"ts_code": ["000001.SZ"]}), dataset="income"
        )
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
