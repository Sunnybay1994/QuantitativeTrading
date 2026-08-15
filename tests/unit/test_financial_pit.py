from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.data.financial_pit import (
    FinancialPITError,
    select_financial_revisions_as_of,
)


def _statement(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20240420",
        "f_ann_date": "20240422",
        "end_date": "20231231",
        "report_type": "1",
        "comp_type": "1",
        "update_flag": "0",
        "n_income": 100.0,
        "n_income_attr_p": 90.0,
    }
    row.update(overrides)
    return row


def test_latest_known_statement_revision_is_selected_without_same_day_lookahead() -> None:
    frame = pl.DataFrame(
        [
            _statement(),
            _statement(
                ann_date="20240510",
                f_ann_date="20240510",
                update_flag="1",
                n_income=110.0,
                n_income_attr_p=99.0,
            ),
        ]
    )
    before_revision = select_financial_revisions_as_of(
        frame, dataset="income", as_of=dt.date(2024, 5, 10)
    )
    assert before_revision.selected.get_column("n_income").item() == 100.0

    after_revision = select_financial_revisions_as_of(
        frame, dataset="income", as_of=dt.date(2024, 5, 11)
    )
    assert after_revision.selected.get_column("n_income").item() == 110.0
    assert after_revision.selected.get_column("available_date").item() == dt.date(2024, 5, 10)


def test_statement_uses_later_announcement_date_and_falls_back_when_one_is_missing() -> None:
    frame = pl.DataFrame(
        [
            _statement(ann_date="20240425", f_ann_date="20240420"),
            _statement(
                end_date="20230930",
                ann_date="20231020",
                f_ann_date=None,
                n_income=70.0,
            ),
        ]
    )
    result = select_financial_revisions_as_of(frame, dataset="income", as_of=dt.date(2024, 4, 26))
    assert result.selected.sort("end_date").get_column("available_date").to_list() == [
        dt.date(2023, 10, 20),
        dt.date(2024, 4, 25),
    ]


def test_latest_same_day_economic_conflict_is_quarantined_without_falling_back() -> None:
    frame = pl.DataFrame(
        [
            _statement(ann_date="20240401", f_ann_date="20240401", n_income=80.0),
            _statement(
                ann_date="20240501",
                f_ann_date="20240501",
                update_flag="1",
                n_income=100.0,
            ),
            _statement(
                ann_date="20240501",
                f_ann_date="20240501",
                update_flag="1",
                n_income=101.0,
            ),
        ]
    )
    result = select_financial_revisions_as_of(frame, dataset="income", as_of=dt.date(2024, 5, 2))
    assert result.selected.is_empty()
    assert result.quarantined.get_column("quarantine_reason").to_list() == [
        "LATEST_REVISION_CONFLICT",
        "LATEST_REVISION_CONFLICT",
    ]


def test_exact_duplicate_economics_collapse_and_row_order_does_not_matter() -> None:
    rows = [
        _statement(update_flag="0"),
        _statement(update_flag="1"),
        _statement(
            end_date="20230930",
            ann_date="20231020",
            f_ann_date="20231020",
            n_income=70.0,
        ),
    ]
    first = select_financial_revisions_as_of(
        pl.DataFrame(rows), dataset="balancesheet", as_of=dt.date(2024, 5, 1)
    )
    second = select_financial_revisions_as_of(
        pl.DataFrame(list(reversed(rows))),
        dataset="balancesheet",
        as_of=dt.date(2024, 5, 1),
    )
    assert first.selected.equals(second.selected)
    assert first.selected.height == 2
    assert (
        first.selected.filter(pl.col("end_date") == "20231231").get_column("update_flag").item()
        == "1"
    )


def test_indicator_uses_announcement_date_and_invalid_rows_are_quarantined() -> None:
    frame = pl.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20240420",
                "end_date": "20231231",
                "roe": 12.0,
            },
            {
                "ts_code": "BAD",
                "ann_date": "20240420",
                "end_date": "20231231",
                "roe": 99.0,
            },
            {
                "ts_code": "000002.SZ",
                "ann_date": "not-a-date",
                "end_date": "20231231",
                "roe": 8.0,
            },
        ]
    )
    result = select_financial_revisions_as_of(
        frame, dataset="fina_indicator", as_of=dt.date(2024, 4, 21)
    )
    assert result.selected.get_column("ts_code").to_list() == ["000001.SZ"]
    assert set(result.quarantined.get_column("quarantine_reason")) == {
        "AVAILABLE_DATE_INVALID",
        "SYMBOL_INVALID",
    }


def test_invalid_contract_is_sanitized() -> None:
    with pytest.raises(FinancialPITError, match="TUSHARE_FINANCIAL_PIT_INVALID") as exc:
        select_financial_revisions_as_of(
            pl.DataFrame({"ts_code": ["000001.SZ"]}),
            dataset="income",
            as_of=dt.date(2024, 1, 1),
        )
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


def test_typed_clean_snapshot_contract_selects_without_string_round_trip() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "ann_date": [dt.date(2024, 4, 20), dt.date(2024, 5, 10)],
            "f_ann_date": [dt.date(2024, 4, 22), dt.date(2024, 5, 10)],
            "available_date": [dt.date(2024, 4, 22), dt.date(2024, 5, 10)],
            "end_date": [dt.date(2023, 12, 31), dt.date(2023, 12, 31)],
            "report_type": ["1", "1"],
            "comp_type": ["1", "1"],
            "update_flag": ["0", "1"],
            "n_income": [100.0, 110.0],
            "n_income_attr_p": [90.0, 99.0],
            "source": ["tushare", "tushare"],
        }
    )
    result = select_financial_revisions_as_of(frame, dataset="income", as_of=dt.date(2024, 5, 11))
    assert result.selected.get_column("n_income").item() == 110.0
    assert result.selected.get_column("end_date").item() == dt.date(2023, 12, 31)
    assert result.quarantined.is_empty()
