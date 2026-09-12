import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data import factor_health_inputs as inputs

JAN = dt.date(2023, 1, 31)
FEB = dt.date(2023, 2, 28)


def universe(root: Path, rows: list[tuple[str, dt.date, bool]]) -> None:
    frame = pl.DataFrame({"symbol": [row[0] for row in rows], "trade_date": [row[1] for row in rows],
        "eligible": [row[2] for row in rows], "industry_l1": [None] * len(rows),
        "total_market_value": [None] * len(rows), "amount20": [1000.0] * len(rows)},
        schema={"symbol": pl.String, "trade_date": pl.Date, "eligible": pl.Boolean,
                "industry_l1": pl.String, "total_market_value": pl.Float64, "amount20": pl.Float64})
    for year in frame["trade_date"].dt.year().unique():
        path = root / f"inputs/{year}/universe.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.filter(pl.col("trade_date").dt.year() == year).write_parquet(path)


def factor(root: Path, rows: list[tuple[dt.date, str, float | None]], factor_id="alpha", year=2023) -> Path:
    path = root / f"factors/{factor_id}/year={year}/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema={"trade_date": pl.Date, "ts_code": pl.String, "value": pl.Float64},
                 orient="row").write_parquet(path)
    return path


def annual(root: Path, rows: list[tuple[str, int, dt.date, bool]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame(rows, schema={"factor": pl.String, "test_year": pl.Int64,
        "refit_close": pl.Date, "provisional_selected": pl.Boolean}, orient="row")
    path = root / "annual_selection.parquet"
    frame.with_columns(pl.lit("size_industry_neutral").alias("variant")).write_parquet(path)
    return path


def test_raw_statuses_keep_all_eligible_and_null_controls(tmp_path):
    later = dt.date(2024, 1, 31)
    root, stats = tmp_path / "data", tmp_path / "stats"
    universe(stats, [(f"00000{i}.SZ", JAN, i != 6) for i in range(1, 7)] + [("000007.SZ", later, True)])
    factor(root, [(JAN, "000001.SZ", 0.0), (JAN, "000002.SZ", None),
                  (JAN, "000003.SZ", float("nan")), (JAN, "000004.SZ", float("inf")),
                  (JAN, "000006.SZ", 100.0)])
    result = inputs.read_factor_health_inputs(data_root=root, statistics=stats, factor_id="alpha",
                                             as_of_dates=[later, JAN])
    assert result["symbol"].to_list() == [f"00000{i}.SZ" for i in (1, 2, 3, 4, 5, 7)]
    assert result["raw_value_status"].to_list() == ["observed", "null_value", "nonfinite_value",
                                                   "nonfinite_value", "missing_row", "missing_partition"]
    assert result["value"][0] == 0
    assert result["industry_l1"].null_count() == result.height
    assert result["total_market_value"].null_count() == result.height
    assert result.columns == ["symbol", "trade_date", "industry_l1", "total_market_value", "value", "raw_value_status"]


def test_only_requested_dates_and_years_are_read(tmp_path):
    root, stats = tmp_path / "data", tmp_path / "stats"
    universe(stats, [("000001.SZ", JAN, True)])
    factor(root, [(JAN, "000001.SZ", -3.5), (FEB, "000001.SZ", 9.0), (FEB, "000001.SZ", 8.0)])
    outside = root / "factors/alpha/year=2022/data.parquet"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"unrelated invalid parquet")
    result = inputs.read_factor_health_inputs(data_root=root, statistics=stats, factor_id="alpha", as_of_dates=[JAN])
    assert result["value"].to_list() == [-3.5]


@pytest.mark.parametrize("problem", ["duplicate", "null_key", "date_type", "value_type", "extra_column"])
def test_raw_key_or_schema_errors_are_explicit(tmp_path, problem):
    root, stats = tmp_path / "data", tmp_path / "stats"
    universe(stats, [("000001.SZ", JAN, True)])
    path = factor(root, [(JAN, "000001.SZ", 1.0)])
    value = pl.read_parquet(path)
    if problem == "duplicate":
        value = pl.concat([value, value])
    elif problem == "null_key":
        value = value.with_columns(pl.lit(None, dtype=pl.String).alias("ts_code"))
    elif problem == "date_type":
        value = value.with_columns(pl.col("trade_date").cast(pl.Datetime))
    elif problem == "value_type":
        value = value.with_columns(pl.col("value").cast(pl.String))
    else:
        value = value.with_columns(pl.lit(2.0).alias("score"))
    value.write_parquet(path)
    with pytest.raises(ValueError):
        inputs.read_factor_health_inputs(data_root=root, statistics=stats, factor_id="alpha", as_of_dates=[JAN])


def test_missing_frozen_date_and_unsafe_factor_path_fail(tmp_path):
    universe(tmp_path, [("000001.SZ", JAN, True)])
    with pytest.raises(ValueError, match="Missing frozen universe trade dates"):
        inputs.read_factor_health_inputs(data_root=tmp_path, statistics=tmp_path, factor_id="alpha", as_of_dates=[FEB])
    with pytest.raises(ValueError, match="identifier"):
        inputs.read_factor_health_inputs(data_root=tmp_path, statistics=tmp_path, factor_id="../alpha", as_of_dates=[JAN])
    with pytest.raises(ValueError, match="unique"):
        inputs.read_factor_health_inputs(data_root=tmp_path, statistics=tmp_path, factor_id="alpha", as_of_dates=[JAN, JAN])


def test_empty_eligible_pool_has_typed_empty_result(tmp_path):
    universe(tmp_path, [("000001.SZ", JAN, False)])
    result = inputs.read_factor_health_inputs(data_root=tmp_path, statistics=tmp_path, factor_id="alpha", as_of_dates=[JAN])
    assert result.is_empty() and result.schema["value"] == pl.Float64
    assert result.schema["raw_value_status"] == pl.String


def test_selection_switches_at_december_refit_close_and_ignores_future(tmp_path):
    annual(tmp_path, [("old", 2023, dt.date(2022, 12, 30), True),
                      ("new", 2024, dt.date(2023, 12, 29), True),
                      ("future", 2025, dt.date(2024, 12, 31), True)])
    dates = [dt.date(2023, 11, 30), dt.date(2023, 12, 28), dt.date(2023, 12, 29)]
    result = inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=dates, max_factors=2)
    assert result["test_year"].to_list() == [2023, 2023, 2024]
    assert result["factor"].to_list() == ["old", "old", "new"]
    assert (result["refit_close"] <= result["as_of"]).all()
    with pytest.raises(ValueError, match="No annual refit"):
        inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[dt.date(2022, 12, 29)])


def test_selected_decision_and_explicit_replacement_only(tmp_path):
    cutoff = dt.date(2022, 12, 30)
    annual(tmp_path, [("amihud_illiquidity_monthly", 2023, cutoff, True),
                      ("free_float_turnover_level_monthly", 2023, cutoff, True),
                      ("pit_sue8", 2023, cutoff, True), ("not_selected", 2023, cutoff, False)])
    replacement = {"amihud_illiquidity_monthly": "amihud_illiquidity_monthly_calendar80_v1"}
    result = inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[JAN], replacements=replacement)
    pairs = dict(zip(result["factor"], result["factor_id"], strict=True))
    assert pairs == {**replacement, "free_float_turnover_level_monthly": "free_float_turnover_level_monthly", "pit_sue8": "pit_sue8"}
    with pytest.raises(ValueError, match="union"):
        inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[JAN], max_factors=2)
    with pytest.raises(ValueError, match="merges"):
        inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[JAN],
                                            replacements={"amihud_illiquidity_monthly": "pit_sue8"})


@pytest.mark.parametrize("problem", ["duplicate", "refit_conflict", "shared_refit", "null_decision", "wrong_schema"])
def test_ambiguous_or_malformed_annual_tables_fail(tmp_path, problem):
    path = annual(tmp_path, [("alpha", 2023, dt.date(2022, 12, 30), True)])
    frame = pl.read_parquet(path)
    if problem == "duplicate":
        frame = pl.concat([frame, frame])
    elif problem == "refit_conflict":
        frame = pl.concat([frame, frame.with_columns(pl.lit("beta").alias("factor"), pl.lit(JAN).alias("refit_close"))])
    elif problem == "shared_refit":
        frame = pl.concat([frame, frame.with_columns(pl.lit(2024, dtype=pl.Int64).alias("test_year"))])
    elif problem == "null_decision":
        frame = frame.with_columns(pl.lit(None, dtype=pl.Boolean).alias("provisional_selected"))
    else:
        frame = frame.with_columns(pl.col("refit_close").cast(pl.String))
    frame.write_parquet(path)
    with pytest.raises(ValueError):
        inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[JAN])


def test_known_empty_annual_selection_keeps_empty_typed_schedule(tmp_path):
    annual(tmp_path, [("alpha", 2023, dt.date(2022, 12, 30), False)])
    result = inputs.read_factor_health_selection(selection=tmp_path, as_of_dates=[JAN])
    assert result.is_empty()
    assert result.columns == ["as_of", "factor", "factor_id", "test_year", "refit_close", "variant"]


def test_month_ends_use_confirmed_calendar_and_do_not_promote_partial_end(tmp_path, monkeypatch):
    sessions = (dt.date(2023, 1, 30), JAN, dt.date(2023, 2, 1), FEB, dt.date(2023, 3, 1))
    monkeypatch.setattr(inputs, "available_sessions", lambda root, through: sessions)
    universe(tmp_path, [("000001.SZ", day, True) for day in (JAN, FEB)])
    result = inputs.read_factor_health_month_ends(data_root=tmp_path, statistics=tmp_path,
                                                start=dt.date(2023, 1, 1), end=FEB)
    assert result == [JAN, FEB]
    partial = inputs.read_factor_health_month_ends(data_root=tmp_path, statistics=tmp_path,
                                                 start=dt.date(2023, 1, 15), end=dt.date(2023, 2, 10))
    assert partial == [JAN]


def test_incomplete_calendar_or_missing_actual_frozen_month_end_fails(tmp_path, monkeypatch):
    universe(tmp_path, [("000001.SZ", dt.date(2023, 1, 30), True), ("000001.SZ", FEB, True)])
    monkeypatch.setattr(inputs, "available_sessions", lambda root, through: (JAN, dt.date(2023, 2, 1), FEB))
    with pytest.raises(ValueError, match="cannot confirm"):
        inputs.read_factor_health_month_ends(data_root=tmp_path, statistics=tmp_path, start=JAN, end=FEB)
    monkeypatch.setattr(inputs, "available_sessions", lambda root, through: (JAN, dt.date(2023, 2, 1), FEB, dt.date(2023, 3, 1)))
    with pytest.raises(ValueError, match="Missing frozen universe trade dates"):
        inputs.read_factor_health_month_ends(data_root=tmp_path, statistics=tmp_path, start=JAN, end=FEB)
