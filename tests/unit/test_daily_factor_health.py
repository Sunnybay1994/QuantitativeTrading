import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import quant.data.daily_factor_health as module

AS_OF = dt.date(2026, 9, 11)


def setup_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = tmp_path / "health.toml"
    config.write_text('''[diagnostics]
selection = "frozen_selection"
statistics = "frozen_statistics"
battery_config = "battery.toml"
maximum_factors = 20
reference_months = 12
diagnostics_only = true
[statistics]
minimum_symbols = 4
minimum_reference_months = 12
[replacements]
original = "replacement"
''', encoding="utf-8")
    calls: list[dict[str, Any]] = []
    universe = pl.DataFrame({"symbol": ["a", "b", "c", "d", "excluded"],
        "trade_date": [AS_OF] * 5, "eligible": [True] * 4 + [False],
        "industry_l1": ["a", "a", "b", "b", "c"], "total_market_value": [1., 2., 3., 4., 5.]})
    dates = [dt.date(2025 if i < 4 else 2026, 9 + i if i < 4 else i - 3, 28) for i in range(12)]

    def selection(**kwargs: Any) -> pl.DataFrame:
        calls.append({"operation": "selection", **kwargs})
        return pl.DataFrame({"factor": ["original", "monthly"], "factor_id": ["replacement", "monthly"],
            "as_of": [AS_OF] * 2, "refit_close": [dt.date(2025, 12, 31)] * 2,
            "test_year": [2026] * 2, "variant": ["size_industry_neutral"] * 2})

    def read_universe(**kwargs: Any) -> pl.DataFrame:
        calls.append({"operation": "universe", **kwargs})
        return universe

    def month_ends(**kwargs: Any) -> list[dt.date]:
        calls.append({"operation": "month_ends", **kwargs})
        return dates

    def current(**kwargs: Any) -> pl.DataFrame:
        calls.append({"operation": "current", "factor_id": kwargs["factor_id"], "as_of": kwargs["as_of"]})
        missing = kwargs["factor_id"] == "monthly"
        return universe.filter(pl.col("eligible")).drop("eligible").with_columns(
            pl.Series("value", [None] * 4 if missing else [0., 1., 2., 3.], dtype=pl.Float64),
            pl.lit("missing_row" if missing else "observed").alias("raw_value_status"))

    def reference(**kwargs: Any) -> pl.DataFrame:
        calls.append({"operation": "reference", **kwargs})
        return pl.concat([universe.filter(pl.col("eligible")).select("symbol", "trade_date").with_columns(
            pl.lit(day).alias("trade_date"), pl.Series("value", [0., 1., 2., 3.])) for day in dates])

    monkeypatch.setattr(module, "read_factor_health_selection", selection)
    monkeypatch.setattr(module, "read_daily_health_universe", read_universe)
    monkeypatch.setattr(module, "read_factor_health_month_ends", month_ends)
    monkeypatch.setattr(module, "read_daily_health_factor", current)
    monkeypatch.setattr(module, "read_factor_health_inputs", reference)
    arguments = {"data_root": tmp_path / "data", "refresh_config": tmp_path / "refresh.toml",
        "health_config": config, "as_of": AS_OF, "output": tmp_path / "out"}
    return arguments, calls


def test_daily_current_values_and_frozen_reference_produce_only_diagnostic_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, calls = setup_case(tmp_path, monkeypatch)
    summary = module.run_daily_factor_health(**arguments)
    assert summary["diagnostics_only"] is True
    assert summary["factor_count"] == 2 and summary["current_eligible_symbols"] == 4
    assert summary["measured_factors"] == summary["no_finite_factors"] == 1
    assert summary["no_finite_factor_ids"] == ["monthly"]
    output = arguments["output"]
    assert {path.name for path in output.iterdir()} == {
        "summary.json", "health.jsonl", "health.parquet", "current_universe.parquet"}
    assert pl.read_parquet(output / "current_universe.parquet").height == 5
    health = [json.loads(line) for line in (output / "health.jsonl").read_text().splitlines()]
    monthly = next(row for row in health if row["factor_id"] == "monthly")
    assert monthly["counts"]["finite"] == 0
    assert monthly["distribution"]["reason"] == "no_finite_values"
    assert monthly["raw_status_counts"]["missing_row"] == 4
    assert monthly["drift"]["psi_reason"] == "insufficient_current_samples"
    selection = next(call for call in calls if call["operation"] == "selection")
    assert selection["as_of_dates"] == [AS_OF]
    assert selection["replacements"] == {"original": "replacement"}
    calendar = next(call for call in calls if call["operation"] == "month_ends")
    assert calendar["start"] == dt.date(2025, 9, 1)
    assert calendar["end"] == dt.date(2026, 8, 31)
    assert set(pl.read_parquet(output / "health.parquet")["as_of"]) == {AS_OF}


def test_missing_frozen_history_propagates_without_zero_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _ = setup_case(tmp_path, monkeypatch)

    def unavailable(**kwargs: Any) -> list[dt.date]:
        raise ValueError("Frozen month-end input missing")

    monkeypatch.setattr(module, "read_factor_health_month_ends", unavailable)
    with pytest.raises(ValueError, match="Frozen month-end"):
        module.run_daily_factor_health(**arguments)
    assert not arguments["output"].exists()


def test_existing_output_is_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, calls = setup_case(tmp_path, monkeypatch)
    arguments["output"].mkdir()
    with pytest.raises(FileExistsError):
        module.run_daily_factor_health(**arguments)
    assert calls == []


def test_more_than_twenty_factors_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, calls = setup_case(tmp_path, monkeypatch)
    config = arguments["health_config"]
    config.write_text(config.read_text().replace("maximum_factors = 20", "maximum_factors = 21"))
    with pytest.raises(ValueError, match="at most 20"):
        module.run_daily_factor_health(**arguments)
    assert calls == []


def test_current_panel_cannot_drop_eligible_stocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, _ = setup_case(tmp_path, monkeypatch)

    def incomplete(**kwargs: Any) -> pl.DataFrame:
        return pl.DataFrame({"symbol": ["a"], "trade_date": [AS_OF]})

    monkeypatch.setattr(module, "read_daily_health_factor", incomplete)
    with pytest.raises(ValueError, match="retain the eligible pool"):
        module.run_daily_factor_health(**arguments)
    assert not arguments["output"].exists()
