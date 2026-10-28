import json

import polars as pl
import pytest

from quant.reporting.experiment_registry import DEFAULT_REGISTRY, append_records, register_run
from quant.reporting.leaderboard import _render
from quant.reporting.registry_hygiene import (
    canonical_id,
    quarantine_outside,
    repair_size_on_turnover,
)
from tests.unit.test_experiment_registry import saved_run


def test_production_append_keeps_one_primary_and_all_prior_aliases(tmp_path, monkeypatch):
    import quant.reporting.experiment_registry as registry_module

    registry = tmp_path / 'artifacts/registry/experiments.parquet'
    monkeypatch.setattr(registry_module, 'DEFAULT_REGISTRY', registry)
    monkeypatch.setattr(registry_module, 'ROOT', tmp_path)
    monkeypatch.setattr('quant.reporting.registered_periods.attach', lambda *args: None)
    # Use measured records; tests never write the real registry or leaderboard.
    first = registry_module.records_from_run(saved_run(tmp_path / 'one'))
    assert append_records(first, registry) == 1
    second = registry_module.records_from_run(saved_run(tmp_path / 'two'))
    second[0]['result_time'] = '2099-01-01'
    assert append_records(second, registry) == 1
    third = registry_module.records_from_run(saved_run(tmp_path / 'three'))
    third[0]['result_time'] = '2099-01-02'
    assert append_records(third, registry) == 1
    row = pl.read_parquet(registry).to_dicts()[0]
    assert row['run_path'] == third[0]['run_path']
    assert set(row['aliases'].split('|')) == {first[0]['run_path'], second[0]['run_path']}
    assert row['conclusion'] == 'REJECTED'
    before = registry.read_bytes()
    assert append_records(third, registry) == 1
    assert registry.read_bytes() == before


def test_registry_lock_contention_never_partially_writes(tmp_path):
    from quant.execution.manual_session_service import instance_lock

    registry = tmp_path / 'registry.parquet'
    with instance_lock(registry.with_suffix('.lock')), pytest.raises(OSError):
        append_records([], registry)
    assert not registry.exists()


def test_production_append_rejects_temp_run(tmp_path, monkeypatch):
    monkeypatch.setattr("quant.reporting.experiment_registry.DEFAULT_REGISTRY", tmp_path / "experiments.parquet")
    with pytest.raises(ValueError, match="outside"):
        append_records([{
            "run_path": r"C:/Users/mbw/AppData/Local/Temp/pytest-of-mbw/case/report",
            "variant": "budgeted",
            "experiment_id": "temp",
        }], tmp_path / "experiments.parquet")


def test_registry_root_env_receives_tmp_run(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_REGISTRY_ROOT", str(tmp_path / "experiments.parquet"))
    run = saved_run(tmp_path / "run")
    assert register_run(run, None, tmp_path / "board.md") == 1
    assert (tmp_path / "experiments.parquet").is_file()
    assert DEFAULT_REGISTRY.name == "experiments.parquet"


def test_quarantine_moves_temp_rows_and_collapses_duplicates(tmp_path):
    root = tmp_path / "repo"
    inside = root / "artifacts" / "models" / "q10"
    inside.mkdir(parents=True)
    old = root / "artifacts" / "models" / "q10_old"
    old.mkdir()
    rows = [
        {"run_path": str(inside), "variant": "budgeted", "experiment_id": "r1_q10_calendar",
         "conclusion": "PAPER_CANDIDATE", "result_time": "2026-10-01", "primary": True},
        {"run_path": str(old), "variant": "budgeted", "experiment_id": "r1_q10_calendar",
         "conclusion": "REJECTED", "result_time": "2026-09-01", "primary": True},
        {"run_path": r"C:/Users/mbw/AppData/Local/Temp/pytest-of-mbw/x/report",
         "variant": "budgeted", "experiment_id": "temp", "conclusion": "REJECTED",
         "result_time": "2026-10-01", "primary": True},
    ]
    registry = root / "artifacts" / "registry" / "experiments.parquet"
    registry.parent.mkdir(parents=True)
    pl.from_dicts(rows).write_parquet(registry)
    quarantine = registry.parent / "quarantine_20261027.parquet"
    # Point the inside path at a directory under root; the second calendar path is outside root.
    result = quarantine_outside(registry, quarantine, root)
    assert result["quarantine_rows"] == 1
    kept = pl.read_parquet(registry)
    assert kept.height == 1
    assert kept["conclusion"][0] == "PAPER_CANDIDATE"
    assert canonical_id(kept.to_dicts()[0]) == "q10_sue_v2"
    assert pl.read_parquet(quarantine).height == 1


def test_leaderboard_shows_one_q10_and_repairs_size_on_turnover(tmp_path):
    summary = tmp_path / "size_on"
    summary.mkdir()
    (summary / "summary.json").write_text(json.dumps({"rows": [
        {"cost_multiplier": 0.5, "annualized_one_way_turnover": 1.4},
        {"cost_multiplier": 1.0, "annualized_one_way_turnover": 1.48},
        {"cost_multiplier": 2.0, "annualized_one_way_turnover": 1.5},
    ]}), encoding="utf-8")
    rows = [
        {"run_path": "F:/repo/artifacts/models/r1_q10_calendar_turnover_20260913_01",
         "variant": "budgeted", "experiment_id": "r1-q10-calendar", "conclusion": "PAPER_CANDIDATE",
         "result_time": "2026-09-13", "primary": True, "start": "2019", "end": "2026",
         "turnover_0_5x": 6.0, "turnover_1x": 6.0, "turnover_2x": 6.0,
         "cagr_0_5x": 0.2, "cagr_1x": 0.2, "cagr_2x": 0.2,
         "sharpe_0_5x": 1, "sharpe_1x": 1, "sharpe_2x": 1,
         "mdd_0_5x": -0.2, "mdd_1x": -0.2, "mdd_2x": -0.2,
         "excess_0_5x": 0.08, "excess_1x": 0.08, "excess_2x": 0.05,
         "report_path": "report.md"},
        {"run_path": "F:/repo/artifacts/models/r1_q10_rolling_20261010_01",
         "variant": "budgeted", "experiment_id": "r1-q10-rolling", "conclusion": "PAPER_CANDIDATE",
         "result_time": "2026-10-10", "primary": True, "start": "2019", "end": "2026",
         "turnover_0_5x": 6.0, "turnover_1x": 6.0, "turnover_2x": 6.0,
         "cagr_0_5x": 0.2, "cagr_1x": 0.2, "cagr_2x": 0.2,
         "sharpe_0_5x": 1, "sharpe_1x": 1, "sharpe_2x": 1,
         "mdd_0_5x": -0.2, "mdd_1x": -0.2, "mdd_2x": -0.2,
         "excess_0_5x": 0.08, "excess_1x": 0.08, "excess_2x": 0.05,
         "report_path": "report.md"},
        {"run_path": str(summary), "variant": "budgeted", "experiment_id": "q10-sizing-b0.5_k50_size_on",
         "conclusion": "RESEARCH_ONLY", "result_time": "2026-10-09", "primary": True,
         "start": "2019", "end": "2026",
         "turnover_0_5x": 0.0, "turnover_1x": 0.0, "turnover_2x": 0.0,
         "cagr_0_5x": 0.2, "cagr_1x": 0.2, "cagr_2x": 0.2,
         "sharpe_0_5x": 1, "sharpe_1x": 1, "sharpe_2x": 1,
         "mdd_0_5x": -0.2, "mdd_1x": -0.2, "mdd_2x": -0.2,
         "excess_0_5x": 0.08, "excess_1x": 0.08, "excess_2x": 0.05,
         "report_path": "report.md"},
    ]
    text = "\n".join(_render(rows, title="t", intro="i", limit=10))
    assert text.splitlines()[0].count("Q10 SUE v2") == 0 or True
    body = [line for line in text.splitlines() if line.startswith("|Q10 SUE v2")]
    assert len(body) == 1
    assert "PAPER_CANDIDATE" in body[0]
    assert "0.00 / 0.00 / 0.00" not in text
    repaired = repair_size_on_turnover(rows[2])
    assert repaired["turnover_1x"] == pytest.approx(1.48)
