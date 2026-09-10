from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from quant.factors import compute
from tests.unit.test_factor_expressions import prepared, sample_bars


def test_incremental_matches_full_batch_and_second_call_is_noop(tmp_path, monkeypatch):
    bars = sample_bars()
    sessions = tuple(sorted(bars["trade_date"].unique()))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in sessions if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    common = {"refresh_config": Path("unused"), "library": Path("configs/factors/library"),
              "selected": "all", "start": sessions[0], "artifact_root": tmp_path / "artifacts"}
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
