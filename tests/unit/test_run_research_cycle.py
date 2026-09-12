from contextlib import closing
import json
from pathlib import Path
import sys
import sqlite3
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
    with closing(sqlite3.connect(root / "shared_cache.sqlite")) as db:
        db.execute("CREATE TABLE attempts (charged_usd REAL)")
    return dict(config=config, output=root / "cycle_output")


def mocks(monkeypatch, setup, *, diagnosis="success", candidate="success", count=1, synthetic=False, failure=None, mutate=None):
    calls = []

    def diagnose(**kwargs):
        calls.append(("diagnosis", kwargs))
        kwargs["output"].mkdir()
        if failure == "diagnosis":
            raise RuntimeError("fixture diagnostic failure")
        report = {"result": diagnosis, "usd_bound_including_retries": .01}
        (kwargs["output"] / "run.json").write_text(json.dumps(report))
        (kwargs["output"] / "facts.json").write_text('{}')
        (kwargs["output"] / "diagnosis.json").write_text('{"findings": [], "candidates": []}')
        return report

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
        report = {"result": candidate, "accepted_count": count, "synthetic_fixture": synthetic,
                "next_command": ["DO_NOT_EXECUTE", "malicious model command"], "usd_bound_including_retries": .02}
        (kwargs["output"] / "run.json").write_text(json.dumps(report))
        (kwargs["output"] / "frozen_request.json").write_text(json.dumps({"synthetic_fixture": synthetic}))
        (kwargs["output"] / "candidates.json").write_text('{"candidates": [{}]}')
        prepared = kwargs["output"] / "prepared"
        prepared.mkdir()
        (prepared / "search.toml").write_text(text)
        (prepared / "trials.json").write_text(json.dumps({"registered_count": count, "factors": []}))
        return report

    def evaluate(**kwargs):
        calls.append(("evaluation", kwargs))
        kwargs["output"].mkdir(exist_ok=True)
        if failure == "evaluation":
            raise TimeoutError("fixture time budget")
        report = {"message": "completed", "reason": "fixture only", "completed_stages": ["screen"]}
        (kwargs["output"] / "screen").mkdir(exist_ok=True)
        (kwargs["output"] / "screen/summary.json").write_text('{}')
        (kwargs["output"] / "summary.json").write_text(json.dumps(report))
        return report

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
    assert cycle._cache_totals(Path("artifacts/shared_cache.sqlite"))["requests"] == 0


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


def test_cycle_passes_return_benchmarks_and_refuses_changed_resume_before_llm(setup, monkeypatch):
    calls = mocks(monkeypatch, setup)
    benchmark = Path('artifacts/returns.toml')
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="fixture"\n')
    args = {**setup, 'execute': True, 'development_test': True, 'return_benchmark_config': benchmark}
    assert cycle.run(**args)['status'] == 'completed'
    assert calls[-1][1]['return_benchmark_config'].read_bytes() == benchmark.read_bytes()
    count = len(calls)
    assert cycle.run(**args, resume=True)['status'] == 'completed'
    assert len(calls) == count
    benchmark.write_text('[benchmarks]\nequal_weight_snapshot="changed"\n')
    with pytest.raises(ValueError, match='Changed or unfrozen'):
        cycle.run(**args, resume=True)
    assert len(calls) == count


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


def test_resume_completed_makes_no_calls(setup, monkeypatch):
    calls = mocks(monkeypatch, setup)
    assert cycle.run(**setup, execute=True)['status'] == 'completed'
    calls.clear()
    assert cycle.run(**setup, execute=True, resume=True)['status'] == 'completed'
    assert cycle.run(**setup, execute=True, resume=True)['status'] == 'completed'
    assert calls == []


@pytest.mark.parametrize('failed_stage,expected', [
    ('diagnosis', ['diagnosis', 'candidates', 'evaluation']),
    ('candidates', ['candidates', 'evaluation']), ('evaluation', ['evaluation'])])
def test_resume_interrupted_stages(setup, monkeypatch, failed_stage, expected):
    mocks(monkeypatch, setup, failure=failed_stage)
    assert cycle.run(**setup, execute=True)['status'] == 'failed'
    calls = mocks(monkeypatch, setup)
    assert cycle.run(**setup, execute=True, resume=True)['status'] == 'completed'
    assert [name for name, _ in calls] == expected
    if failed_stage != 'evaluation':
        assert (setup['output'] / f'{failed_stage}_partial_001').is_dir()


@pytest.mark.parametrize('target', ['scorecard.parquet', 'model_0.json', 'design.toml', 'candidate_config.toml', 'cycle.toml'])
def test_resume_changed_inputs_preserves_results(setup, monkeypatch, target):
    calls = mocks(monkeypatch, setup)
    cycle.run(**setup, execute=True)
    original = (setup['output'] / 'run.json').read_bytes()
    path = Path('artifacts') / target
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        cycle.run(**setup, execute=True, resume=True)
    assert (setup['output'] / 'run.json').read_bytes() == original and len(calls) == 3


@pytest.mark.parametrize('target', ['diagnosis/diagnosis.json', 'candidates/batch.toml',
                                     'candidates/prepared/search.toml', 'evaluation/screen/summary.json'])
def test_resume_checks_outputs_not_success_label(setup, monkeypatch, target):
    calls = mocks(monkeypatch, setup)
    cycle.run(**setup, execute=True)
    original = (setup['output'] / 'run.json').read_bytes()
    (setup['output'] / target).unlink()
    with pytest.raises((ValueError, OSError)):
        cycle.run(**setup, execute=True, resume=True)
    assert (setup['output'] / 'run.json').read_bytes() == original and len(calls) == 3


@pytest.mark.parametrize('mutation', ['cache', 'requests', 'usd'])
def test_resume_cannot_expand_budget_or_replace_cache(setup, monkeypatch, mutation):
    mocks(monkeypatch, setup, diagnosis='budget_exhausted')
    cycle.run(**setup, execute=True)
    text = setup['config'].read_text()
    before, after = {'cache': ('shared_cache.sqlite', 'new_cache.sqlite'),
                     'requests': ('max_requests = 20', 'max_requests = 21'),
                     'usd': ('max_usd = 0.05', 'max_usd = 1.0')}[mutation]
    setup['config'].write_text(text.replace(before, after))
    with pytest.raises(ValueError):
        cycle.run(**setup, execute=True, resume=True, development_test=True)
    assert not Path('artifacts/new_cache.sqlite').exists()


@pytest.mark.parametrize('state', ['budget_exhausted', 'unknown'])
def test_resume_failed_llm_keeps_caps_and_unknown_state(setup, monkeypatch, state):
    mocks(monkeypatch, setup, diagnosis=state)
    cycle.run(**setup, execute=True)
    calls = mocks(monkeypatch, setup, diagnosis=state)
    result = cycle.run(**setup, execute=True, resume=True, development_test=True)
    assert result['status'] == 'stopped' and len(calls) == 1
    assert calls[0][1]['max_requests'] == 20 and calls[0][1]['max_usd'] == .05
    assert calls[0][1]['cache_path'] == Path('artifacts/shared_cache.sqlite').resolve()
    assert result['stages']['diagnosis']['status'] == state


@pytest.mark.parametrize('remove', [True, False])
def test_resume_missing_or_reset_cache_rejected(setup, monkeypatch, remove):
    cache = Path('artifacts/shared_cache.sqlite')
    with closing(sqlite3.connect(cache)) as db:
        db.execute('INSERT INTO attempts VALUES (0.01)')
        db.commit()
    mocks(monkeypatch, setup)
    cycle.run(**setup, execute=True)
    if remove:
        cache.unlink()
    else:
        with closing(sqlite3.connect(cache)) as db:
            db.execute('DELETE FROM attempts')
            db.commit()
    with pytest.raises(ValueError, match='cache'):
        cycle.run(**setup, execute=True, resume=True)


def test_resume_synthetic_candidates_rejected(setup, monkeypatch):
    calls = mocks(monkeypatch, setup, synthetic=True)
    assert cycle.run(**setup, execute=True)['status'] == 'stopped'
    with pytest.raises(ValueError, match='Synthetic'):
        cycle.run(**setup, execute=True, resume=True)
    assert len(calls) == 2


def test_resume_old_unfrozen_cycle_rejected(setup, monkeypatch):
    mocks(monkeypatch, setup)
    cycle.run(**setup, execute=True)
    path = setup['output'] / 'run.json'
    saved = json.loads(path.read_text())
    del saved['input_hashes']
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='unfrozen'):
        cycle.run(**setup, execute=True, resume=True)


def test_cli_resume_completed(setup, monkeypatch, capsys):
    calls = mocks(monkeypatch, setup)
    cycle.run(**setup, execute=True)
    calls.clear()
    monkeypatch.setattr(sys, 'argv', ['cycle', '--config', str(setup['config']),
        '--output', str(setup['output']), '--execute', '--resume'])
    cycle.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'completed' and not calls


@pytest.mark.parametrize('reserved_key,expected', [('same-request', 'unknown'), ('another-request', 'budget_exhausted')])
def test_resume_real_cache_never_resubmits_unknown_or_exhausted(setup, monkeypatch, reserved_key, expected):
    from quant.data.forecast_text_scores import ScoreCache
    from quant.research.score_forecast_text import load_settings, score_one

    cache_path = Path('artifacts/shared_cache.sqlite')
    cache_path.unlink()  # Replace only this test's empty stub with the actual schema.
    cache = ScoreCache(cache_path)
    try:
        for index in range(20):
            key = reserved_key if index == 19 else f"other-{index}"
            assert cache.reserve(key, .001, max_requests=20, max_usd=.05, max_attempts=20)
    finally:
        cache.close()
    calls = mocks(monkeypatch, setup)
    settings = load_settings(ROOT / 'configs/research/deepseek_diagnosis_v1.toml')

    class NoNetwork:
        def complete(self, *args):
            pytest.fail('Unknown request or exhausted budget must never call the provider')

    def diagnose(**kwargs):
        kwargs['output'].mkdir()
        cache = ScoreCache(kwargs['cache_path'])
        try:
            value = score_one('', settings=settings, cache=cache, client=NoNetwork(),
                max_requests=kwargs['max_requests'], max_usd=kwargs['max_usd'],
                request_key='same-request', token_bound=100, development_test=True)
            return {'result': value['state']}
        finally:
            cache.close()

    monkeypatch.setattr(cycle, 'run_diagnosis', diagnose)
    for resume in (False, True):
        result = cycle.run(**setup, execute=True, resume=resume, development_test=True)
        assert result['stages']['diagnosis']['status'] == expected
        assert result['cache_totals']['requests'] == 20
        assert result['status'] == 'stopped'
    assert not calls
