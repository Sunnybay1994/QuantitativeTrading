import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.factor_benchmark import read_factor_benchmark
from quant.factors.expressions import required_history
from quant.research.factor_market import MARKET_FACTOR_NAMES, attach_market_factors, market_input_names
from tests.unit.test_factor_expressions import prepared, sample_bars


def test_market_columns_match_numpy_and_require_contiguous_history():
    bars = sample_bars()
    sessions = tuple(sorted(bars["trade_date"].unique()))
    benchmark = bars.filter(pl.col("symbol") == "600003.SH").with_columns(
        pl.lit("510300.SH").alias("symbol"))
    result = attach_market_factors(prepared(bars), bars, benchmark, sessions, MARKET_FACTOR_NAMES)
    market = np.diff(np.log((benchmark["close"] * benchmark["adj_factor"]).to_numpy()))[-60:]
    down = market < 0
    assert down.sum() >= 15
    for symbol in bars["symbol"].unique():
        stock = bars.filter(pl.col("symbol") == symbol).sort("trade_date")
        returns = np.diff(np.log((stock["close"] * stock["adj_factor"]).to_numpy()))[-60:]
        for name, mask in zip(MARKET_FACTOR_NAMES, (np.ones(60, dtype=bool), down), strict=True):
            expected = np.cov(market[mask], returns[mask], ddof=0)[0, 1] / np.var(market[mask])
            actual = result.filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == sessions[-1]))[name].item()
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-10)
    assert result.filter(pl.col("trade_date") < sessions[60])[MARKET_FACTOR_NAMES[0]].count() == 0
    gap = benchmark.filter(pl.col("trade_date") != sessions[65])
    broken = attach_market_factors(prepared(bars), bars, gap, sessions, MARKET_FACTOR_NAMES)
    assert broken.filter(pl.col("trade_date") >= sessions[65])[MARKET_FACTOR_NAMES[0]].count() == 0
    future = benchmark.with_columns(pl.when(pl.col("trade_date") > sessions[65])
        .then(pl.col("adj_factor") * 1.2).otherwise(pl.col("adj_factor")).alias("adj_factor"))
    changed = attach_market_factors(prepared(bars), bars, future, sessions, MARKET_FACTOR_NAMES)
    assert_frame_equal(result.filter(pl.col("trade_date") <= sessions[65]),
                       changed.filter(pl.col("trade_date") <= sessions[65]))
    empty = attach_market_factors(prepared(bars), bars, benchmark.head(0), sessions, MARKET_FACTOR_NAMES)
    assert all(empty[name].count() == 0 for name in MARKET_FACTOR_NAMES)
    for name in MARKET_FACTOR_NAMES:
        assert required_history(name) == 60
        assert required_history(f"ts_mean({name},20)") == 79
        assert required_history(f"delay({name},5)") == 65
    assert market_input_names(("close",)) == ()


def test_benchmark_reader_filters_dates_and_checks_scope(tmp_path: Path):
    folder = tmp_path / "clean/factor_benchmark/fixture"
    folder.mkdir(parents=True)
    config = tmp_path / "refresh.toml"
    config.write_text('factor_benchmark_snapshot="fixture"\n')
    bars = sample_bars().filter(pl.col("symbol") == "600003.SH").with_columns(
        pl.lit("510300.SH").alias("symbol"))
    bars.write_parquet(folder / "bars.parquet")
    result = read_factor_benchmark(tmp_path, config, dt.date(2020, 1, 15), dt.date(2020, 1, 17))
    assert result.height == 3
    bars.with_columns(pl.lit("510500.SH").alias("symbol")).write_parquet(folder / "bars.parquet")
    with pytest.raises(ValueError, match="only 510300"):
        read_factor_benchmark(tmp_path, config, dt.date(2020, 1, 15), dt.date(2020, 1, 17))


def test_market_cross_year_increment_matches_full(tmp_path, monkeypatch):
    from quant.factors import compute

    bars = sample_bars().with_columns(
        (pl.col("trade_date") + dt.timedelta(days=(dt.date(2025, 11, 15) - dt.date(2020, 1, 1)).days))
        .alias("trade_date"))
    sessions = tuple(sorted(bars["trade_date"].unique()))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in sessions if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    config = tmp_path / "refresh.toml"
    config.write_text('factor_benchmark_snapshot="fixture"\n')
    for mode in ("full", "increment"):
        folder = tmp_path / mode / "clean/factor_benchmark/fixture"
        folder.mkdir(parents=True)
        bars.filter(pl.col("symbol") == "600003.SH").with_columns(
            pl.lit("510300.SH").alias("symbol")).write_parquet(folder / "bars.parquet")
    args = dict(refresh_config=config, library=Path("configs/factors/library"),
        selected=",".join(MARKET_FACTOR_NAMES), start=sessions[0], artifact_root=tmp_path / "artifacts")
    compute.run(**args, data_root=tmp_path / "increment", end=sessions[63])
    compute.run(**args, data_root=tmp_path / "increment", end=sessions[-1])
    compute.run(**args, data_root=tmp_path / "full", end=sessions[-1])
    for file in (tmp_path / "full/factors").glob("*/year=*/data.parquet"):
        assert_frame_equal(pl.read_parquet(file), pl.read_parquet(
            tmp_path / "increment" / file.relative_to(tmp_path / "full")))
    for name in MARKET_FACTOR_NAMES:
        assert pl.read_parquet(tmp_path / "full/factors" / name / "year=2026/data.parquet")["value"].count() == 40
    assert compute.run(**args, data_root=tmp_path / "increment", end=sessions[-1])["years"] == []
