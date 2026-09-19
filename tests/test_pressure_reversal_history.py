import datetime as dt
import json

import polars as pl
import pytest

from quant.research.pressure_reversal_history import completed_year, digest, input_files, month_ends, monthly_coverage


def test_month_ends_use_exchange_sessions_and_requested_bounds():
    dates = tuple(dt.date.fromisoformat(day) for day in ["2020-01-30", "2020-01-31", "2020-02-03", "2020-02-28", "2020-03-02"])
    assert month_ends(dates, dt.date(2020, 1, 1), dt.date(2020, 2, 28)) == [dates[1], dates[3]]


def test_monthly_input_counts_preserve_industry_gap_and_ineligible_names():
    day, missing_day = dt.date(2020, 1, 31), dt.date(2020, 2, 28)
    universe = pl.DataFrame({"symbol": ["A", "B", "C", "D"], "trade_date": [day] * 4,
                            "eligible": [True, True, True, False], "total_market_value": [1., 2., 3., 4.],
                            "industry_l1": [None] * 4}, schema_overrides={"industry_l1": pl.String})
    values = pl.DataFrame({"ts_code": ["A", "B", "C", "D"], "trade_date": [day] * 4,
                          "candidate_id": ["fixed"] * 4, "value": [1., 4., 2., 99.]})
    settings = {"variants": ["raw", "size_industry_neutral"], "minimum_symbols": 3,
                "preprocessing": {"mad_multiplier": 3., "mad_normal_scale": 1.4826}}
    rows, scores = monthly_coverage(values, universe, settings, [day, missing_day])
    assert [r["finite_symbols"] for r in rows] == [3, 0, 0, 0]
    assert [r["input_sufficient"] for r in rows] == [True, False, False, False]
    assert scores.height == 3
    assert all("paired_coverage" not in row for row in rows)


def test_completed_checkpoint_requires_unchanged_artifacts(tmp_path):
    output = tmp_path / "monthly_values.parquet"
    output.write_bytes(b"frozen")
    receipt = {"year": 2020, "output_hashes": {output.name: digest(output)}}
    (tmp_path / "summary.json").write_text(json.dumps(receipt))
    assert completed_year(tmp_path) == receipt
    output.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Completed readiness output changed"):
        completed_year(tmp_path)


def test_incomplete_year_is_not_a_checkpoint(tmp_path):
    (tmp_path / "monthly_values.parquet").write_bytes(b"partial")
    assert completed_year(tmp_path) is None


def test_warmup_year_does_not_require_evaluation_universe(tmp_path):
    files = input_files(tmp_path / "data", {"stock_snapshot": "s", "daily_basic_snapshot": "b"},
                        tmp_path / "battery", dt.date(2009, 11, 1), dt.date(2010, 12, 31),
                        universe_start=dt.date(2010, 1, 1))
    assert tmp_path / "battery/inputs/2010/universe.parquet" in files
    assert tmp_path / "battery/inputs/2009/universe.parquet" not in files
