from dataclasses import asdict
import json
from pathlib import Path
import tomllib

import pytest

from quant.factors.library import FactorDefinition
from quant.factors.search import prepare
from quant.research import generate_factor_candidates as module

CONFIG = Path(__file__).resolve().parents[2] / "configs/research/deepseek_diagnosis_v1.toml"
DESIGN = Path(__file__).resolve().parents[2] / "configs/factors/search/p6c_finite_batch01_window02_20260911.toml"


def candidate(expression="ts_mean(adj_close, 3)", **changes):
    return {"expression": expression, "direction": -1, "rationale": "检验价格平滑后的假设",
            "sources": ["diagnosis#/candidates/0"], **changes}


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "artifacts"
    diagnosis = root / "diagnosis"
    diagnosis.mkdir(parents=True)
    facts = {"source0#/metric": .2}
    (diagnosis / "facts.json").write_text(json.dumps(facts))
    (diagnosis / "diagnosis.json").write_text(json.dumps({"findings": [], "candidates": [{
        "proposal": "检验价格平滑关系", "rationale": "既有相关性值得独立研究", "evidence": [
            {"pointer": "source0#/metric", "value": .2}]}]}))
    library = root / "existing"
    library.mkdir()
    existing = FactorDefinition("original", "adj_close", "fixture", 1, "fixture")
    (library / "original.toml").write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in asdict(existing).items()))
    design = root / "design.toml"
    design.write_text(DESIGN.read_text(encoding="utf-8").replace('library = "configs/factors/library"',
        f"library = {json.dumps(str(library).replace(chr(92), '/'))}"), encoding="utf-8")
    return dict(diagnosis=diagnosis, design=design, scope="价格平滑；只准备候选，不评价收益",
        fields=["adj_close"], operators=["ts_mean", "delay"], maximum_candidates=10,
        maximum_history=60, output=root / "generated", config=CONFIG, artifact_root=root,
        cache_path=root / "shared.sqlite")


def test_fixture_retains_invalid_trials_and_prepares_only_valid_local_definitions(inputs):
    fixture = inputs["artifact_root"] / "fixture.json"
    items = [candidate(), candidate(" ts_mean(adj_close, 3) ".strip()), candidate("adj_close"),
        candidate("ts_mean(adj_close, 100000)"), candidate("delay(adj_close, -1)"),
        candidate("future_return"), candidate(direction=True), candidate(sources=["unknown"]),
        candidate("__import__('os').system('echo unsafe')"), candidate("ts_mean()")]
    fixture.write_text(json.dumps({"synthetic_fixture": True, "candidates": items}))
    before = (inputs["artifact_root"] / "existing/original.toml").read_bytes()
    result = module.run(**inputs, fixture=fixture)
    assert result["accepted_count"] == 1 and len(result["trials"]) == 10
    assert sum(row["result"] == "rejected" for row in result["trials"]) == 9
    assert result["synthetic_fixture"] and not result["evaluated"] and result["next_command"] is None
    assert result["prepared"]["registered_count"] == 1
    assert (inputs["artifact_root"] / "existing/original.toml").read_bytes() == before
    assert len(list((inputs["artifact_root"] / "existing").glob("*.toml"))) == 1
    batch = tomllib.loads((inputs["output"] / "batch.toml").read_text(encoding="utf-8"))
    original = tomllib.loads(inputs["design"].read_text(encoding="utf-8"))
    assert batch["dates"] == original["dates"]
    assert batch["search"]["maximum_history"] == 60
    assert batch["search"]["maximum_hours"] == original["search"]["maximum_hours"]
    assert batch["templates"][0]["direction"] == -1
    with pytest.raises(ValueError, match="Synthetic"):
        prepare(config=inputs["output"] / "batch.toml", library=inputs["output"] / "registry",
                output=inputs["output"] / "evaluation")
    assert not (inputs["output"] / "evaluation").exists()


def test_dry_run_freezes_design_but_never_calls_api_or_registers_candidates(inputs, monkeypatch):
    monkeypatch.setattr(module, "load_key", lambda *args: pytest.fail("No credential read in dry-run"))
    result = module.run(**inputs)
    assert result["result"] == "dry_run" and result["accepted_count"] == 0
    assert not inputs["cache_path"].exists() and not (inputs["output"] / "batch.toml").exists()
    frozen = json.loads((inputs["output"] / "frozen_request.json").read_text(encoding="utf-8"))
    assert frozen["maximum_requests"] == 0 and frozen["maximum_usd"] == 0
    assert frozen["request"]["maximum_history"] == 60


def test_fake_provider_reuses_budget_offpeak_cache_and_produces_runnable_config(inputs, monkeypatch):
    monkeypatch.setattr("quant.research.score_forecast_text.request_window", lambda: {
        "allowed": False, "next_allowed_at": "2026-09-14T04:00:00+00:00"})

    class Client:
        calls = 0

        def complete_messages(self, messages, settings):
            self.calls += 1
            # All design, bounds and input snapshots precede even the fixture transport call.
            assert (current / "frozen_request.json").is_file()
            return {"model": "fixture", "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps({"candidates": [candidate()]})}}]}

    client = Client()
    current = inputs["output"]
    args = {**inputs, "client": client, "execute": True, "max_requests": 1, "max_usd": .1}
    assert module.run(**args)["result"] == "deferred_off_peak"
    assert client.calls == 0
    current = inputs["artifact_root"] / "tiny_budget"
    assert module.run(**{**args, "output": current, "max_usd": .000001}, development_test=True)["result"] == "budget_exhausted"
    for index in range(2):
        current = inputs["artifact_root"] / f"live_fixture_transport_{index}"
        result = module.run(**{**args, "output": current}, development_test=True)
        assert result["accepted_count"] == 1 and result["next_command"]
        batch = current / "batch.toml"
        prepared = prepare(config=batch, library=current / "registry", output=current / "evaluation")
        assert prepared["registered_count"] == 1
    assert client.calls == 1
    exhausted = module.run(**{**args, "scope": "第二批不同研究范围", "output": inputs["artifact_root"] / "exhausted"},
                           development_test=True)
    assert exhausted["result"] == "budget_exhausted" and client.calls == 1


@pytest.mark.parametrize("change", ["unknown_field", "unknown_operator", "budget", "dates", "bad_citation"])
def test_invalid_scope_or_diagnosis_fails_before_new_output(inputs, change):
    if change == "unknown_field":
        inputs["fields"].append("future_return")
    elif change == "unknown_operator":
        inputs["operators"].append("python")
    elif change == "budget":
        inputs["maximum_candidates"] = 50
    elif change == "dates":
        text = inputs["design"].read_text(encoding="utf-8").replace("forward_start = 2026-09-14", "forward_start = 2023-01-01")
        inputs["design"].write_text(text, encoding="utf-8")
    else:
        (inputs["diagnosis"] / "facts.json").write_text(json.dumps({"source0#/metric": .9}))
    with pytest.raises(ValueError):
        module.run(**inputs)
    assert not inputs["output"].exists()


def test_unmarked_fixture_and_oversized_envelope_rejected(inputs):
    path = inputs["artifact_root"] / "fixture.json"
    path.write_text(json.dumps({"candidates": [candidate()]}))
    with pytest.raises(ValueError, match="synthetic_fixture"):
        module.run(**inputs, fixture=path)
    with pytest.raises(ValueError, match="count"):
        module._envelope(json.dumps({"candidates": [candidate()] * 11}), 10)


def test_nested_history_and_zero_direction_cannot_enter_preparation(inputs):
    fixture = inputs["artifact_root"] / "nested.json"
    fixture.write_text(json.dumps({"synthetic_fixture": True, "candidates": [
        candidate("ts_mean(ts_mean(adj_close, 40), 40)"), candidate(direction=0)]}))
    result = module.run(**inputs, fixture=fixture)
    assert result["accepted_count"] == 0 and result["prepared"] is None
    assert "history" in result["trials"][0]["reason"]
    assert "direction" in result["trials"][1]["reason"]
    assert not (inputs["output"] / "batch.toml").exists()


@pytest.mark.parametrize('state,count,execute,exit_code', [
    ('dry_run', 0, False, 0), ('success', 1, True, 0),
    ('success', 0, True, 1), ('budget_exhausted', 0, True, 1),
    ('deferred_off_peak', 0, True, 1), ('failed', 0, True, 1),
])
def test_live_cli_only_succeeds_when_a_usable_batch_exists(monkeypatch, capsys, state, count, execute, exit_code):
    import sys

    argv = ['generate_factor_candidates', '--diagnosis', 'diagnosis', '--design', 'design',
            '--scope', 'scope', '--fields', 'adj_close', '--maximum-candidates', '2',
            '--maximum-history', '60', '--output', 'new'] + (['--execute'] if execute else [])
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(module, 'run', lambda **kwargs: {
        'result': state, 'synthetic_fixture': False, 'accepted_count': count,
        'usd_bound_including_retries': .01})
    if exit_code:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == exit_code
    else:
        module.main()
    assert json.loads(capsys.readouterr().out)['result'] == state
