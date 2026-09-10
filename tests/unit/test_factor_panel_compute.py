from pathlib import Path
import datetime as dt
import json

import polars as pl
from polars.testing import assert_frame_equal

from quant.factors import compute
from tests.unit.test_factor_expressions import prepared, sample_bars
from tests.unit.test_factor_financials import _expanded_histories


def test_incremental_matches_full_batch_and_second_call_is_noop(tmp_path, monkeypatch):
    bars = sample_bars()
    sessions = tuple(sorted(bars["trade_date"].unique()))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in sessions if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    config = tmp_path / "refresh.toml"
    config.write_text('financial_snapshot="fixture"\nfinancial_share_changes_snapshot="fixture"\nfactor_benchmark_snapshot="fixture"\n')
    common = {"refresh_config": config, "library": Path("configs/factors/library"),
              "selected": "all", "start": sessions[0], "artifact_root": tmp_path / "artifacts"}
    for name in ("increment", "full"):
        benchmark_root = tmp_path / name / "clean/factor_benchmark/fixture"
        benchmark_root.mkdir(parents=True)
        bars.filter(pl.col("symbol") == bars["symbol"][0]).with_columns(
            pl.lit("510300.SH").alias("symbol")).write_parquet(benchmark_root / "bars.parquet")
        industry_root = tmp_path / name / "clean/tushare_industry/fixture"
        industry_root.mkdir(parents=True)
        bars.select("symbol").unique().with_columns(
            pl.lit(sessions[0]).alias("valid_from"),
            pl.lit(sessions[-1] + dt.timedelta(days=1)).alias("valid_to"),
            *[pl.lit("sector").alias(f"industry_l{n}") for n in (1, 2, 3)],
        ).write_parquet(industry_root / "intervals.parquet")
        (industry_root / "summary.json").write_text(json.dumps({"with_current": True}))
        financial_root = tmp_path / name / "clean/tushare_financials/fixture"
        financial_root.mkdir(parents=True)
        for table, frame in _expanded_histories().items():
            frame.write_parquet(financial_root / f"{table}.parquet")
        pl.DataFrame(schema={"symbol": pl.String, "ann_date": pl.Date, "available_date": pl.Date,
            "end_date": pl.Date, "interestdebt": pl.Float64, "ebitda": pl.Float64,
            "source": pl.String}).write_parquet(financial_root / "fina_indicator.parquet")
        share_root = tmp_path / name / "clean/cninfo_share_changes/fixture"
        share_root.mkdir(parents=True)
        pl.DataFrame(schema={"symbol": pl.String, "event_date": pl.Date, "ann_date": pl.Date,
            "change_type_codes": pl.String}).write_parquet(share_root / "events.parquet")
        pl.DataFrame(schema={"symbol": pl.String, "start": pl.Date, "end": pl.Date,
            "empty_response": pl.Boolean}).write_parquet(share_root / "request_coverage.parquet")
    compute.run(**common, data_root=tmp_path / "increment", end=sessions[40])
    increment = compute.run(**common, data_root=tmp_path / "increment", end=sessions[-1])
    compute.run(**common, data_root=tmp_path / "full", end=sessions[-1])
    for file in (tmp_path / "full/factors").glob("*/year=*/data.parquet"):
        relative = file.relative_to(tmp_path / "full")
        assert_frame_equal(pl.read_parquet(file), pl.read_parquet(tmp_path / "increment" / relative),
                           rel_tol=1e-8, abs_tol=1e-10)
    assert increment["years"][0]["factors"]["alpha158_roc20"]["rows"] == 4 * 29
    repeated = compute.run(**common, data_root=tmp_path / "increment", end=sessions[-1])
    assert repeated["years"] == []


def test_industry_factor_uses_dated_classification_input(tmp_path, monkeypatch):
    bars = sample_bars()
    sessions = tuple(sorted(bars["trade_date"].unique()))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: sessions)
    monkeypatch.setattr(compute, "read_factor_inputs", lambda *args: (prepared(bars), bars))
    library = tmp_path / "library"
    library.mkdir()
    (library / "industry_mean.toml").write_text(
        'id="industry_mean"\nexpr="ind_neutralize(close, industry_l1)"\n'
        'family="test"\ndirection=1\nsource_ref="fixture"\n')
    data_root = tmp_path / "data"
    industry_root = data_root / "clean/tushare_industry/20260101"
    industry_root.mkdir(parents=True)
    bars.select("symbol").unique().with_columns(
        pl.lit(sessions[0]).alias("valid_from"),
        pl.lit(sessions[-1] + dt.timedelta(days=1)).alias("valid_to"),
        *[pl.lit("sector").alias(f"industry_l{n}") for n in (1, 2, 3)],
    ).write_parquet(industry_root / "intervals.parquet")
    (industry_root / "summary.json").write_text(json.dumps({"with_current": True}))
    result = compute.run(data_root=data_root, refresh_config=Path("unused"), library=library,
                         selected="all", start=sessions[0], end=sessions[-1], artifact_root=tmp_path / "artifacts")
    assert result["factor_count"] == 1
    path = next((data_root / "factors/industry_mean").glob("year=*/data.parquet"))
    output = pl.read_parquet(path)
    assert output["value"].count() == bars.height
    assert output.group_by("trade_date").agg(pl.col("value").mean())["value"].abs().max() < 1e-10
