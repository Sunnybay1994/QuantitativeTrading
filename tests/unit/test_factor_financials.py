import datetime as dt
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.research.factor_financials import attach_quality_factors
from quant.research.pit_quality_research import build_pit_quality_signal_values
from tests.unit.test_pit_quality_research import _histories
from tests.unit.test_factor_expressions import prepared, sample_bars
from quant.factors import compute


def test_announcements_conflicting_revisions_and_missing_bars_match_daily_reselection():
    income, balance, cash = _histories()
    # A new conflicting annual revision must erase an earlier valid score.
    revision = income.tail(1).with_columns(
        pl.lit(dt.date(2024, 4, 25)).alias("available_date"),
        pl.lit(dt.date(2024, 4, 25)).alias("ann_date"),
        pl.lit(dt.date(2024, 4, 25)).alias("f_ann_date"),
    )
    income = pl.concat([income, revision, revision.with_columns(pl.lit(999.).alias("n_income"))])
    histories = {"income": income, "balancesheet": balance, "cashflow": cash}
    dates = tuple(dt.date(2024, 4, day) for day in (22, 23, 24, 25, 26, 29))
    panel = pl.DataFrame({"trade_date": dates, "symbol": ["000001.SZ"] * len(dates),
                          "close": [10., 10., None, 10., 10., 10.]})
    expected = build_pit_quality_signal_values(
        income_history=income, balance_history=balance, cash_history=cash,
        signal_dates=dates, candidate_symbols=("000001.SZ",), allowed_report_types=("1",),
    ).factors.select("symbol", "trade_date", *PIT_QUALITY_FACTOR_NAMES)
    expected = panel.join(expected, on=["symbol", "trade_date"]).with_columns(
        pl.when(pl.col("close").is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
        for name in PIT_QUALITY_FACTOR_NAMES
    ).sort("symbol", "trade_date")
    actual = attach_quality_factors(panel, histories)
    assert_frame_equal(actual, expected)
    assert actual.filter(pl.col("trade_date") == dt.date(2024, 4, 23))["pit_roa_ttm"].item() is not None
    assert actual.filter(pl.col("trade_date") == dt.date(2024, 4, 26))["pit_roa_ttm"].item() is None
    cutoff = dt.date(2024, 4, 25)
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff), attach_quality_factors(
        panel.filter(pl.col("trade_date") <= cutoff), histories))
    wide = {name: frame.with_columns(pl.lit(1.).alias("unrelated_measure"))
            for name, frame in histories.items()}
    duplicate = wide["income"].filter(pl.col("end_date") == dt.date(2023, 6, 30)).with_columns(
        pl.lit(2.).alias("unrelated_measure"))
    wide["income"] = pl.concat([wide["income"], duplicate])
    assert_frame_equal(actual, attach_quality_factors(panel, wide))


def test_quality_batch_reads_history_and_increment_matches_full(tmp_path, monkeypatch):
    dates = tuple(dt.date(2024, 4, day) for day in (22, 23, 24, 25, 26, 29))
    bars = sample_bars().filter(pl.col("symbol") == "600000.SH").head(len(dates)).with_columns(
        pl.Series("trade_date", dates, dtype=pl.Date), pl.lit("000001.SZ").alias("symbol"))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in dates if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    config = tmp_path / "refresh.toml"
    config.write_text('financial_snapshot="fixture"\n')
    library = tmp_path / "library"
    library.mkdir()
    for name in PIT_QUALITY_FACTOR_NAMES:
        (library / f"{name}.toml").write_text(
            f'id="{name}"\nexpr="{name}"\nfamily="pit_quality"\ndirection=1\nsource_ref="fixture"\n')
    income, balance, cash = _histories()
    for mode in ("full", "increment"):
        root = tmp_path / mode / "clean/tushare_financials/fixture"
        root.mkdir(parents=True)
        for name, frame in (("income", income), ("balancesheet", balance), ("cashflow", cash)):
            frame.write_parquet(root / f"{name}.parquet")
    common = dict(refresh_config=config, library=library, selected="all", start=dates[0],
                  artifact_root=tmp_path / "artifacts")
    compute.run(**common, data_root=tmp_path / "increment", end=dates[2])
    compute.run(**common, data_root=tmp_path / "increment", end=dates[-1])
    compute.run(**common, data_root=tmp_path / "full", end=dates[-1])
    for name in PIT_QUALITY_FACTOR_NAMES:
        path = Path("factors") / name / "year=2024/data.parquet"
        full = pl.read_parquet(tmp_path / "full" / path)
        assert full["value"].count() > 0
        assert_frame_equal(full, pl.read_parquet(tmp_path / "increment" / path))
    assert compute.run(**common, data_root=tmp_path / "increment", end=dates[-1])["years"] == []
