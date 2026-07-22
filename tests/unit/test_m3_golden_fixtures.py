from pathlib import Path

import polars as pl
import pytest

from quant.domain import (
    Bar1dSchema,
    BenchmarkBar1dSchema,
    ForwardReturnLabelSchema,
    PredictionScoreSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)

FIXTURE_ROOT = Path("tests/fixtures/m3")


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def test_m3_golden_contract_files_validate() -> None:
    TradeCalendarSchema.validate(_read("calendar.csv"))
    UniverseMembershipSchema.validate(_read("membership.csv"))
    Bar1dSchema.validate(_read("bars.csv"))
    # readiness still consumes Bar1d price-index fixture
    Bar1dSchema.validate(_read("benchmark_bars.csv"))
    BenchmarkBar1dSchema.validate(_read("benchmark_bars_total_return.csv"))
    ForwardReturnLabelSchema.validate(_read("expected_labels.csv"))
    PredictionScoreSchema.validate(_read("predictions.csv"))
    TargetWeightSchema.validate(_read("expected_targets.csv"))


def test_expected_labels_reconcile_to_next_open_and_future_close() -> None:
    bars = _read("bars.csv")
    benchmark = _read("benchmark_bars_total_return.csv")
    expected = _read("expected_labels.csv")
    for row in expected.iter_rows(named=True):
        entry = bars.filter(
            (pl.col("symbol") == row["symbol"])
            & (pl.col("trade_date") == row["return_start_date"])
        )
        exit_bar = bars.filter(
            (pl.col("symbol") == row["symbol"])
            & (pl.col("trade_date") == row["return_end_date"])
        )
        entry_open = entry.item(0, "open")
        entry_factor = entry.item(0, "adj_factor")
        exit_close = exit_bar.item(0, "close")
        exit_factor = exit_bar.item(0, "adj_factor")
        benchmark_entry = benchmark.filter(
            pl.col("trade_date") == row["return_start_date"]
        ).item(0, "open")
        benchmark_exit = benchmark.filter(
            pl.col("trade_date") == row["return_end_date"]
        ).item(0, "close")
        raw_return = (exit_close * exit_factor) / (entry_open * entry_factor) - 1
        benchmark_return = benchmark_exit / benchmark_entry - 1
        assert row["benchmark"] == "H00300.CSI"
        assert row["raw_return"] == pytest.approx(raw_return, abs=1e-10)
        assert row["benchmark_return"] == pytest.approx(
            benchmark_return, abs=1e-10
        )
        assert row["relative_return"] == pytest.approx(
            raw_return - benchmark_return, abs=1e-10
        )

    assert "000004.SZ" not in expected.get_column("symbol").unique().to_list()
    assert bars.filter(
        (pl.col("symbol") == "000004.SZ")
        & (pl.col("trade_date") == expected.item(0, "return_start_date"))
    ).is_empty()


def test_expected_targets_follow_pit_eligibility_and_score_order() -> None:
    predictions = _read("predictions.csv")
    eligibility = _read("eligibility_2026-01-05.csv")
    targets = _read("expected_targets.csv")
    selected = (
        predictions.join(eligibility, on="symbol")
        .filter(pl.col("eligible"))
        .sort(["score", "symbol"], descending=[True, False])
        .head(2)
        .get_column("symbol")
        .to_list()
    )
    positive_targets = (
        targets.filter(pl.col("weight") > 0).sort("weight", descending=True)
    )
    assert set(selected) == set(positive_targets.get_column("symbol").to_list())
    assert positive_targets.get_column("weight").sum() == pytest.approx(0.9)
    assert targets.filter(pl.col("symbol") == "000003.SZ").item(0, "weight") == 0


def test_expected_folds_use_sessions_and_one_session_embargo() -> None:
    open_dates = _read("calendar.csv").get_column("date").to_list()
    index = {date: offset for offset, date in enumerate(open_dates)}
    folds = _read("expected_folds.csv")
    for row in folds.iter_rows(named=True):
        assert index[row["train_end"]] - index[row["train_start"]] + 1 == 4
        assert index[row["validation_end"]] - index[row["validation_start"]] + 1 == 2
        assert index[row["test_end"]] - index[row["test_start"]] + 1 == 2
        assert index[row["validation_start"]] - index[row["train_end"]] - 1 == 1
        assert index[row["test_start"]] - index[row["validation_end"]] - 1 == 1
    assert index[folds.item(1, "train_start")] - index[folds.item(0, "train_start")] == 2
