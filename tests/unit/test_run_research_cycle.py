import json
from pathlib import Path
import sys
import tomllib

import polars as pl
import pytest

from quant.research import run_research_cycle as cycle

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path("artifacts")
    root.mkdir()
    scorecard = root / "scorecard.parquet"
    pl.DataFrame({"factor": ["fixture"] * 2, "variant": ["raw", "size_industry_neutral"]}).write_parquet(scorecard)
    assessments = []
    for i in range(3):
        path = root / f"model_{i}.json"
        path.write_text(json.dumps({"primary": {"conclusion": "REJECTED", "risk": {"cagr": .01}}}))
        assessments.append(str(path))
    design = root / "design.toml"
    design.write_text('''[search]
maximum_candidates = 20
maximum_hours = 8
maximum_cost_attempts = 2
workers = 2
execution_snapshot = "fixture"
fields = ["adj_close"]
operators = ["ts_mean"]
[dates]
start = 2010-01-01
training_end = 2023-12-29
validation_start = 2024-01-01
validation_end = 2025-12-31
panel_end = 2026-09-10
forward_start = 2026-09-14
''')
    scoring = root / "candidate_config.toml"
    scoring.write_text((ROOT / "configs/research/deepseek_diagnosis_v1.toml").read_text().replace("max_tokens = 2048", "max_tokens = 4096"))
    config = root / "cycle.toml"
    config.write_text(f'''[diagnosis]
scorecard = {json.dumps(str(scorecard))}
assessments = {json.dumps(assessments)}
config = {json.dumps(str(ROOT / 'configs/research/deepseek_diagnosis_v1.toml').replace(chr(92), '/'))}
[candidates]
config = {json.dumps(str(scoring))}
design = {json.dumps(str(design))}
scope = "synthetic fixture scope"
fields = ["adj_close"]
operators = ["ts_mean"]
maximum_candidates = 4
maximum_history = 60
[budget]
cache = "artifacts/shared_cache.sqlite"
max_requests = 20
max_usd = 0.05
''')
    return dict(config=config, output=root / "cycle_output")


def mocks(monkeypatch, setup, *, diagnosis="success", candidate="success", count=1, synthetic=False, failure=None, mutate=None):
    calls = []

    def diagnose(**kwargs):
        calls.append(("diagnosis", kwargs))
        kwargs["output"].mkdir()
        if failure == "diagnosis":
            raise RuntimeError("fixture diagnostic failure")
        return {"result": diagnosis, "usd_bound_including_retries": .01}

    def generate(**kwargs):
        calls.append(("candidates", kwargs))
        kwargs["output"].mkdir()
        if failure == "candidates":
            raise RuntimeError("fixture generation failure")
        text = kwargs["design"].read_text()
        search_lines = "".join(f'{name} = {json.dumps(str((kwargs["output"] / name).resolve()).replace(chr(92), "/"))}\n'
                              for name in ("library", "battery_config", "refresh_config"))
        text = text.replace("[search]\n", "[search]\n" + search_lines)
        text += f'\n[candidate_generation]\nsynthetic_fixture = {str(synthetic).lower()}\n'
        if mutate == "dates":
            text = text.replace("training_end = 2023-12-29", "training_end = 2023-12-28")
        if mutate == "library":
            text = text.replace(search_lines.splitlines()[0], 'library = "configs/factors/library"')
        (kwargs["output"] / "batch.toml").write_text(text)
        return {"result": candidate, "accepted_count": count, "synthetic_fixture": synthetic,
                "next_command": ["DO_NOT_EXECUTE", "malicious model command"], "usd_bound_including_retries": .02}

    def evaluate(**kwargs):
        calls.append(("evaluation", kwargs))
        kwargs["output"].mkdir()
        if failure == "evaluation":
            raise TimeoutError("fixture time budget")
        return {"message": "completed", "reason": "fixture only"}

    monkeypatch.setattr(cycle, "run_diagnosis", diagnose)
    monkeypatch.setattr(cycle, "generate_candidates", generate)
    monkeypatch.setattr(cycle, "run_factor_search", evaluate)
    return calls


def test_actual_dry_diagnosis_stops_before_candidates_and_has_unknown_cycle_cost(setup, monkeypatch):
    monkeypatch.setattr(cycle, "generate_candidates", lambda **kwargs: pytest.fail("No manufactured candidates"))
    monkeypatch.setattr(cycle, "run_factor_search", lambda **kwargs: pytest.fail("No dry evaluation"))
    monkeypatch.setattr("quant.research.deepseek_diagnostics.load_key", lambda *args: pytest.fail("No dry credential read"))
    result = cycle.run(**setup)
    assert result["status"] == "dry_run"
    assert result["stages"]["diagnosis"]["result"]["summary_coverage"]["assessments_included"] == 3
    assert result["stages"]["candidates"]["status"] == result["stages"]["evaluation"]["status"] == "not_run"
    assert result["cost_estimates"]["diagnosis_usd_bound_including_retries"] > 0
    assert result["cost_estimates"]["candidates_usd_bound_including_retries"] is None
    assert result["cost_estimates"]["full_cycle_usd_bound"] is None
    assert not Path("artifacts/shared_cache.sqlite").exists()


def test_success_calls_python_functions_with_shared_caps_and_fixed_paths(setup, monkeypatch):
    calls = mocks(monkeypatch, setup)
    result = cycle.run(**setup, execute=True, development_test=True)
    assert result["status"] == "completed"
    assert [name for name, _ in calls] == ["diagnosis", "candidates", "evaluation"]
    for _, kwargs in calls[:2]:
        assert kwargs["cache_path"] == Path("artifacts/shared_cache.sqlite").resolve()
        assert kwargs["max_requests"] == 20 and kwargs["max_usd"] == .05
        assert kwargs["execute"] is True and kwargs["development_test"] is True
    assert calls[0][1]["config"] != calls[1][1]["config"]
    assert tomllib.loads(calls[1][1]["config"].read_text())["max_tokens"] == 4096
    assert calls[2][1] == {"config": setup["output"] / "candidates/batch.toml", "output": setup["output"] / "evaluation"}
    assert result["dates"]["training_end"] == "2023-12-29"


@pytest.mark.parametrize("status", ["budget_exhausted", "deferred_off_peak", "failed", "retryable"])
def test_diagnosis_non_success_preserves_result_and_never_generates(setup, monkeypatch, status):
    calls = mocks(monkeypatch, setup, diagnosis=status)
    result = cycle.run(**setup, execute=True)
    assert result["status"] == "stopped" and result["stopped_stage"] == "diagnosis"
    assert len(calls) == 1
    saved = json.loads((setup["output"] / "run.json").read_text())
    assert saved["stages"]["diagnosis"]["status"] == status


@pytest.mark.parametrize("status,count,synthetic", [("budget_exhausted", 0, False), ("deferred_off_peak", 0, False),
                                                    ("success", 0, False), ("success", 1, True)])
def test_candidate_stop_and_fixture_never_evaluate(setup, monkeypatch, status, count, synthetic):
    calls = mocks(monkeypatch, setup, candidate=status, count=count, synthetic=synthetic)
    result = cycle.run(**setup, execute=True)
    assert result["status"] == "stopped" and len(calls) == 2
    assert result["stages"]["evaluation"]["status"] == "not_run"


@pytest.mark.parametrize("stage", ["diagnosis", "candidates", "evaluation"])
def test_stage_exception_preserves_failure_and_prior_outputs(setup, monkeypatch, stage):
    calls = mocks(monkeypatch, setup, failure=stage)
    result = cycle.run(**setup, execute=True)
    assert result["status"] == "failed" and result["stopped_stage"] == stage
    assert calls[-1][0] == stage
    assert (setup["output"] / stage).is_dir()
    assert json.loads((setup["output"] / "run.json").read_text())["stages"][stage]["status"] == "failed"


@pytest.mark.parametrize("change", ["dates", "library"])
def test_batch_cannot_change_dates_or_write_global_library(setup, monkeypatch, change):
    calls = mocks(monkeypatch, setup, mutate=change)
    result = cycle.run(**setup, execute=True)
    assert result["status"] == "failed" and len(calls) == 2


def test_cli_deferred_exit_and_same_directory_preserved(setup, monkeypatch, capsys):
    calls = mocks(monkeypatch, setup, diagnosis="deferred_off_peak")
    monkeypatch.setattr(sys, "argv", ["cycle", "--config", str(setup["config"]), "--output", str(setup["output"]), "--execute"])
    with pytest.raises(SystemExit) as error:
        cycle.main()
    assert error.value.code == 1 and json.loads(capsys.readouterr().out)["status"] == "stopped"
    saved = (setup["output"] / "run.json").read_bytes()
    with pytest.raises(FileExistsError):
        cycle.run(**setup, execute=True)
    assert len(calls) == 1 and (setup["output"] / "run.json").read_bytes() == saved
