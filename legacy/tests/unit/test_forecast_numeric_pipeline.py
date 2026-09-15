import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors import compute
from quant.research.evaluate_forecast_numeric import monthly_coverage, reuse_inputs
from tests.unit.test_factor_expressions import prepared, sample_bars


def test_numeric_compute_incremental_equals_full_and_noops(tmp_path, monkeypatch):
    dates = tuple(dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(4))
    bars = sample_bars().filter(pl.col("symbol") == "600000.SH").head(4)
    events = pl.DataFrame({"symbol": ["600000.SH"] * 2,
        "publication_date": [dates[0], dates[2]], "report_period": [dt.date(2020, 3, 31)] * 2,
        "forecast_p_change_midpoint": [15., None], "forecast_p_change_width": [10., None],
        "forecast_numeric_event_status": ["valid", "missing_range"]})
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in dates if d <= end))
    monkeypatch.setattr(compute, "read_forecast_numeric_config", lambda *args: events)

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    common = dict(refresh_config=Path("configs/data/refresh_p7_numeric_20260912.toml"),
        library=Path("configs/factors/p7_numeric_library"), selected="all", start=dates[0],
        artifact_root=tmp_path / "artifacts")
    for mode in ("full", "increment"):
        root = tmp_path / mode
        if mode == "increment":
            compute.run(**common, data_root=root, end=dates[1])
        compute.run(**common, data_root=root, end=dates[-1])
        assert compute.run(**common, data_root=root, end=dates[-1])["years"] == []
    for name, expected in (("forecast_p_change_midpoint", [15., 15., None, None]),
                           ("forecast_p_change_width", [10., 10., None, None])):
        path = f"factors/{name}/year=2020/data.parquet"
        full = pl.read_parquet(tmp_path / "full" / path)
        assert full["value"].to_list() == expected
        assert_frame_equal(full, pl.read_parquet(tmp_path / "increment" / path))


def test_cached_inputs_reject_different_cutoff_and_settings(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    battery = tmp_path / "battery.toml"
    battery.write_text("start = 2020-01-01\nminimum_symbols = 100\n", encoding="utf-8")
    (source / "battery.toml").write_text(battery.read_text() +
        "\n[run]\nas_of = 2020-12-31\nselected = 'all'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identical"):
        reuse_inputs(source=source, output=output, battery=battery, as_of=dt.date(2020, 11, 30))
    battery.write_text("start = 2020-01-01\nminimum_symbols = 99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identical"):
        reuse_inputs(source=source, output=output, battery=battery, as_of=dt.date(2020, 12, 31))


def test_coverage_keeps_requested_denominator_and_unobservable_labels_separate():
    day = dt.date(2026, 8, 31)
    scores = pl.DataFrame({"symbol": ["A", "B", "C"], "trade_date": [day] * 3,
                           "raw": [1., None, None]})
    ic = pl.DataFrame({"trade_date": [day], "variant": ["raw"],
        "rank_ic": pl.Series([None], dtype=pl.Float64), "paired_count": [0]})
    result = monthly_coverage(scores, ic, symbols=["A", "B"], factor="numeric", variants=["raw"]).row(0, named=True)
    assert result["eligible_stocks"] == 3
    assert result["requested_coverage"] == .5
    assert result["universe_coverage"] == pytest.approx(1 / 3)
    assert result["rank_ic"] is None
    assert result["paired_count"] == 0
