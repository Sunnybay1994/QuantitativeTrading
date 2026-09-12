import datetime as dt

import polars as pl
import pytest

from quant.data.sue_input_quality import diagnose_sue_report_context, read_sue_report_context

AS_OF = dt.date(2026, 8, 31)
SYMBOL = "000750.SZ"


def report(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {"symbol": SYMBOL, "end_date": dt.date(2026, 6, 30),
        "available_date": dt.date(2026, 8, 28), "report_type": "1", "comp_type": "4",
        "update_flag": "0"}
    row.update(changes)
    return row


def inputs(value: float | None = 0.5) -> tuple[pl.DataFrame, pl.DataFrame]:
    pool = pl.DataFrame({"symbol": [SYMBOL], "trade_date": [AS_OF]})
    values = pl.DataFrame({"ts_code": [SYMBOL], "date": [AS_OF], "value": [value]})
    return pool, values


def diagnose(rows: list[dict[str, object]], value: float | None = 0.5) -> dict[str, object]:
    pool, values = inputs(value)
    return diagnose_sue_report_context(pool=pool, income_history=pl.DataFrame(rows),
        factor_values=values, as_of=AS_OF).row(0, named=True)


def test_company_type_transition_flags_old_industrial_sue_without_recomputing() -> None:
    result = diagnose([report(end_date=dt.date(2011, 3, 31),
        available_date=dt.date(2011, 4, 20), comp_type="1"), report()])
    assert result["latest_report_end"] == dt.date(2026, 6, 30)
    assert result["latest_comp_type"] == "4"
    assert result["report_context"] == "non_industrial"
    assert result["unexpected_factor_value"] is True
    assert result["factor_value"] == 0.5


def test_same_day_future_announcement_and_future_period_are_not_visible() -> None:
    result = diagnose([report(comp_type="1"),
        report(available_date=AS_OF, update_flag="1"),
        report(available_date=dt.date(2026, 9, 1)),
        report(end_date=dt.date(2026, 9, 30)),
        report(report_type="4", available_date=dt.date(2026, 8, 30))])
    assert result["report_context"] == "industrial"
    assert result["latest_available_date"] == dt.date(2026, 8, 28)
    assert result["unexpected_factor_value"] is False


def test_latest_available_date_precedes_update_rank_and_tied_types_remain_ambiguous() -> None:
    result = diagnose([report(comp_type="1", available_date=dt.date(2026, 8, 27), update_flag="1"),
        report(comp_type="1", update_flag="0"), report(comp_type="4", update_flag="1"),
        report(comp_type="3", update_flag="1"), report(comp_type="4", update_flag="1")])
    assert result["latest_comp_types"] == "3,4"
    assert result["latest_comp_type"] is None
    assert result["report_context"] == "ambiguous"
    assert result["unexpected_factor_value"] is True


@pytest.mark.parametrize("comp_type", [None, "9", ""])
def test_unknown_type_is_not_silently_nonindustrial(comp_type: str | None) -> None:
    result = diagnose([report(comp_type=comp_type)])
    assert result["latest_comp_type"] is None
    assert result["report_context"] == "unknown"
    assert result["unexpected_factor_value"] is True


def test_industrial_and_null_tie_is_ambiguous() -> None:
    result = diagnose([report(comp_type="1"), report(comp_type=None)])
    assert result["report_context"] == "ambiguous"
    assert result["latest_comp_type"] is None
    assert result["latest_comp_types"] == "1,<null>"
    assert result["unexpected_factor_value"] is True


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_missing_or_nonfinite_value_does_not_automatically_flag_context(value: float | None) -> None:
    assert diagnose([report()], value)["unexpected_factor_value"] is False


def test_no_known_report_with_finite_factor_is_unsupported() -> None:
    result = diagnose([report(available_date=AS_OF)])
    assert result["latest_report_end"] is None
    assert result["report_context"] == "no_report"
    assert result["unexpected_factor_value"] is True


@pytest.mark.parametrize("duplicate", ["pool", "factor"])
def test_duplicate_keys_fail(duplicate: str) -> None:
    pool, values = inputs()
    with pytest.raises(ValueError, match="unique"):
        diagnose_sue_report_context(pool=pl.concat([pool, pool]) if duplicate == "pool" else pool,
            income_history=pl.DataFrame([report()]),
            factor_values=pl.concat([values, values]) if duplicate == "factor" else values,
            as_of=AS_OF)


def test_pool_dates_are_not_silently_filtered() -> None:
    pool, values = inputs()
    with pytest.raises(ValueError, match="as_of"):
        diagnose_sue_report_context(pool=pool.with_columns(pl.lit(dt.date(2026, 8, 28)).alias("trade_date")),
            income_history=pl.DataFrame([report()]), factor_values=values, as_of=AS_OF)


def test_missing_factor_row_remains_null() -> None:
    pool, values = inputs()
    result = diagnose_sue_report_context(pool=pool, income_history=pl.DataFrame([report()]),
        factor_values=values.head(0), as_of=AS_OF).row(0, named=True)
    assert result["factor_value"] is None
    assert result["unexpected_factor_value"] is False


def test_reader_reuses_full_period_history(monkeypatch: pytest.MonkeyPatch) -> None:
    import quant.data.sue_input_quality as module
    from quant.data.financial_repository import TushareFinancialHistoryQuery
    from pathlib import Path

    queries: list[TushareFinancialHistoryQuery] = []

    def read(*, data_root: Path, query: TushareFinancialHistoryQuery) -> pl.DataFrame:
        assert data_root == Path("data")
        queries.append(query)
        return pl.DataFrame([report()])

    monkeypatch.setattr(module, "read_tushare_financial_history", read)
    pool, values = inputs()
    result = read_sue_report_context(data_root=Path("data"), snapshot="frozen",
        pool=pool, factor_values=values.rename({"ts_code": "symbol", "date": "trade_date"}), as_of=AS_OF)
    assert result["unexpected_factor_value"].item() is True
    assert queries[0].snapshot_id == "frozen"
    assert queries[0].start_period == dt.date(1900, 1, 1)
    assert queries[0].end_period == AS_OF
    assert queries[0].symbols == (SYMBOL,)
