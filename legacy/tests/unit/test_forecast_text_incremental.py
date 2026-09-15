import datetime as dt
from pathlib import Path
import tomllib

import numpy as np
import polars as pl
import pytest

from quant.data.forecast_text_evaluation import attach_forecast_controls, read_forecast_controls
from quant.research.evaluate_forecast_text import run_fixture
from quant.research.forecast_text_incremental import diagnose_sections, residualize_text, summarize_incremental
from quant.research.score_forecast_text import load_design

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/factors/p7_text_evaluation_v2.toml"
SETTINGS = tomllib.loads((ROOT / "configs/factors/battery.toml").read_text())


def fixture_panel(count=120):
    rows = []
    for month in (1, 2, 3):
        date = dt.date(2020, month, 28)
        for i in range(count):
            rows.append({"symbol": f"{600000+i}.SH", "trade_date": date, "eligible": True,
                "synthetic_fixture": True, "is_month_end": True, "industry_l1": f"sector{i % 5}",
                "forecast_p_change_midpoint": float(i % 17), "pit_sue8": float(np.sin(i / 13)),
                "total_market_value": float(np.exp(i / 90) * 1e8),
                "text_operating_improvement": float(i % 4),
                "text_nonrecurring_gain_dependency": float((i // 3) % 4),
                "text_operating_pressure": float((i // 5) % 4),
                **{f"label_{h}": float(np.sin(i + month) * .01) for h in (1, 5, 10, 20, 60)},
                "label_rebalance": float(np.cos(i + month) * .03)})
    return pl.from_dicts(rows)


def test_controls_keep_own_publication_missing_revision_and_expiry(tmp_path):
    source = tmp_path / "numeric.parquet"
    pl.DataFrame({"ts_code": ["600001.SH"] * 2,
        "publication_date": [dt.date(2020, 1, 1), dt.date(2020, 2, 1)],
        "first_ann_date": ["20191201"] * 2, "report_period": [dt.date(2020, 3, 31)] * 2,
        "same_day_conflict": [False, False], "p_change_min": [10., None],
        "p_change_max": [30., 99.]}).write_parquet(source)
    events = read_forecast_controls(source)
    grid = pl.DataFrame({"symbol": ["600001.SH"] * 4,
        "trade_date": [dt.date(2019, 12, 31), dt.date(2020, 1, 1),
                       dt.date(2020, 2, 1), dt.date(2020, 6, 1)]})
    result = attach_forecast_controls(grid, events, max_age_days=120)
    assert result["forecast_p_change_midpoint"].to_list() == [None, 20., None, None]
    assert result["forecast_publication_date"][1] == dt.date(2020, 1, 1)


def test_same_day_conflicts_and_latest_period(tmp_path):
    source = tmp_path / "numeric.parquet"
    pl.DataFrame({"ts_code": ["600001.SH"] * 3,
        "publication_date": [dt.date(2020, 1, 1)] * 3,
        "report_period": [dt.date(2019, 12, 31), dt.date(2020, 3, 31), dt.date(2020, 3, 31)],
        "same_day_conflict": [False] * 3, "p_change_min": [1., 3., 5.],
        "p_change_max": [2., 4., 6.]}).write_parquet(source)
    result = read_forecast_controls(source)
    assert result.height == 1 and result["forecast_p_change_midpoint"][0] is None


def test_common_support_identical_for_all_comparators_and_missing_not_zero():
    panel = fixture_panel().with_columns(
        pl.when(pl.col("symbol") == "600000.SH").then(None).otherwise(pl.col("pit_sue8")).alias("pit_sue8"),
        pl.when(pl.col("symbol") == "600001.SH").then(None).otherwise(pl.col("label_20")).alias("label_20"))
    points, support = diagnose_sections(panel, label="label_20", frequency="daily_20", settings=SETTINGS)
    assert points["common_count"].unique().to_list() == [118]
    assert points["input_common_count"].unique().to_list() == [119]
    assert not {"600000.SH", "600001.SH"} & set(support["symbol"])
    assert points["sue_count"].unique().to_list() == [119]
    assert set(points["comparator"]) == {"text", "forecast_midpoint", "pit_sue8", "residual_text"}


def test_future_return_changes_do_not_change_residuals():
    panel = fixture_panel()
    points, support = diagnose_sections(panel, label="label_20", frequency="daily_20", settings=SETTINGS)
    inverse, other = diagnose_sections(panel.with_columns(-pl.col("label_20")), label="label_20",
                                        frequency="daily_20", settings=SETTINGS)
    np.testing.assert_allclose(support["residual_text"].to_numpy(), other["residual_text"].to_numpy())
    np.testing.assert_allclose(points["rank_ic"].to_numpy(), -inverse["rank_ic"].to_numpy(), atol=1e-12)


def test_projection_orthogonal_to_contemporaneous_controls():
    i = np.arange(120, dtype=float)
    midpoint, sue, size = i % 17, np.sin(i / 13), np.exp(i / 90) * 1e8
    industry = np.array([str(int(x) % 5) for x in i])
    residual, rank = residualize_text(i % 4, midpoint, sue, size, industry)
    assert rank == 8
    for control in (np.ones(120), midpoint, sue, np.log(size), (industry == "1").astype(float)):
        assert abs(float(control @ residual)) < 1e-8


def test_insufficient_symbols_or_paired_coverage_remains_missing():
    points, support = diagnose_sections(fixture_panel(99), label="label_20", frequency="daily_20", settings=SETTINGS)
    assert points["rank_ic"].null_count() == points.height
    assert support["residual_text"].null_count() == support.height
    panel = fixture_panel().with_columns(pl.when(pl.col("symbol") < "600010.SH").then(None)
        .otherwise(pl.col("label_20")).alias("label_20"))
    points, _ = diagnose_sections(panel, label="label_20", frequency="daily_20", settings=SETTINGS)
    assert points["common_count"][0] == 110
    assert points["rank_ic"].null_count() == points.height


def test_perfectly_explained_text_has_no_residual_ic():
    panel = fixture_panel().with_columns(pl.col("forecast_p_change_midpoint").alias("text_operating_improvement"))
    points, _ = diagnose_sections(panel, label="label_20", frequency="daily_20", settings=SETTINGS)
    residual = points.filter((pl.col("factor") == "text_operating_improvement")
                              & (pl.col("comparator") == "residual_text"))
    assert residual["rank_ic"].null_count() == residual.height


def test_duplicate_keys_refused():
    panel = fixture_panel()
    with pytest.raises(ValueError, match="duplicate"):
        diagnose_sections(pl.concat([panel, panel.head(1)]), label="label_20", frequency="daily_20", settings=SETTINGS)


def test_monthly_summary_keeps_missing_months_and_existing_threshold():
    points, _ = diagnose_sections(fixture_panel(), label="label_rebalance", frequency="monthly", settings=SETTINGS)
    points = points.with_columns(pl.when(pl.col("trade_date").dt.month() == 2).then(None)
        .otherwise(pl.col("rank_ic")).alias("rank_ic"))
    rows = summarize_incremental(points, sessions=tuple(fixture_panel()["trade_date"].unique().sort()),
                                 settings=SETTINGS, design=load_design(DESIGN))
    full = [r for r in rows if r["split"] == "full"]
    assert all(r["months"] == 2 and r["existing_minimum_months"] == 96 for r in full)
    assert all("admitted" not in r for r in rows)


def test_fixture_runner_exercises_existing_battery_without_publishing(tmp_path):
    source = tmp_path / "fixture.parquet"
    fixture_panel().write_parquet(source)
    result = run_fixture(source=source, output=tmp_path / "run", design_path=DESIGN)
    assert result == {"synthetic_fixture": True, "battery_variants": 6, "incremental_summaries": 96}
    assert (tmp_path / "run/incremental/common_support.parquet").is_file()
    assert not (tmp_path / "data").exists()


def test_configured_sue_version_reaches_panel_without_legacy_fallback(tmp_path, monkeypatch):
    from quant.data.forecast_text_evaluation import read_text_evaluation_year

    date = dt.date(2020, 1, 28)
    keys = pl.DataFrame({'symbol': ['600001.SH', '600002.SH'], 'trade_date': [date, date]})
    events = pl.DataFrame({'symbol': keys['symbol'], 'publication_date': [date, date],
        'report_period': [date, date], 'forecast_p_change_midpoint': [1., 2.]})
    for version, values in [('pit_sue8', [99., 88.]), ('pit_sue8_context_v2', [None, 2.])]:
        path = tmp_path / f'factors/{version}/year=2020/data.parquet'
        path.parent.mkdir(parents=True)
        keys.rename({'symbol': 'ts_code'}).with_columns(pl.Series('value', values, dtype=pl.Float64)).write_parquet(path)
    monkeypatch.setattr('quant.data.factor_battery_inputs.read_battery_factor_year',
        lambda *args, **kwargs: (keys.with_columns(pl.lit(1.).alias('value')), keys))
    args = dict(data_root=tmp_path, year=2020, known_through=date, universe=keys,
        numeric_events=events, factors=['text_operating_improvement'], max_age_days=120)
    old, _ = read_text_evaluation_year(**args)
    new, _ = read_text_evaluation_year(**args, sue_factor='pit_sue8_context_v2')
    assert old['pit_sue8'].to_list() == [99., 88.]
    assert new['pit_sue8'].to_list() == [None, 2.]
    (tmp_path / 'factors/pit_sue8_context_v2/year=2020/data.parquet').unlink()
    missing, _ = read_text_evaluation_year(**args, sue_factor='pit_sue8_context_v2')
    assert missing['pit_sue8'].null_count() == 2
    with pytest.raises(ValueError, match='Unsupported SUE'):
        read_text_evaluation_year(**args, sue_factor='../pit_sue8')


def test_new_design_fixture_uses_v2_values_and_names_in_saved_evidence(tmp_path):
    import json
    design_path = ROOT / 'configs/factors/p7_text_evaluation_v2_sue_context_20260912.toml'
    source = tmp_path / 'fixture.parquet'
    fixture_panel().with_columns(
        pl.when(pl.col('symbol') == '600000.SH').then(None).otherwise(pl.col('pit_sue8'))
        .alias('pit_sue8_context_v2')).write_parquet(source)
    result = run_fixture(source=source, output=tmp_path / 'run', design_path=design_path)
    assert result['incremental_summaries'] == 96
    folder = tmp_path / 'run/incremental'
    points = pl.read_parquet(folder / 'incremental_ic.parquet')
    common = pl.read_parquet(folder / 'common_support.parquet')
    summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    assert points['common_count'].unique().to_list() == [119]
    assert 'pit_sue8_context_v2' in set(points['comparator'])
    assert 'pit_sue8' not in set(points['comparator'])
    assert '600000.SH' not in set(common['symbol'])
    assert 'pit_sue8' not in common.columns and 'pit_sue8_context_v2' in common.columns
    assert 'pit_sue8_context_v2' in summary['regression_inputs']
    fixture_panel().write_parquet(tmp_path / 'legacy_only.parquet')
    with pytest.raises(ValueError, match='configured SUE'):
        run_fixture(source=tmp_path / 'legacy_only.parquet', output=tmp_path / 'wrong', design_path=design_path)
    assert not (tmp_path / 'wrong').exists()


def test_sue_design_is_only_a_control_version_change_and_rejects_unknown(tmp_path):
    old_path = ROOT / 'configs/factors/p7_text_evaluation_v2_all.toml'
    new_path = ROOT / 'configs/factors/p7_text_evaluation_v2_sue_context_20260912.toml'
    old, new = load_design(old_path), load_design(new_path)
    assert new['evaluation']['numeric_controls'] == ['forecast_p_change_midpoint', 'pit_sue8_context_v2']
    new['version'] = old['version']
    new['evaluation']['numeric_controls'] = old['evaluation']['numeric_controls']
    assert new == old
    bad = tmp_path / 'bad.toml'
    bad.write_text(new_path.read_text(encoding='utf-8').replace('pit_sue8_context_v2', 'unknown_sue'), encoding='utf-8')
    with pytest.raises(ValueError, match='Unsupported P7 design'):
        load_design(bad)
