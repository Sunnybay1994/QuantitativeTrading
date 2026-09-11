import json
from pathlib import Path

import pytest

from quant.research.deepseek_diagnostics import extract_facts, parse_diagnosis, run_diagnosis

CONFIG = Path(__file__).resolve().parents[2] / "configs/research/deepseek_diagnosis_v1.toml"


@pytest.fixture(autouse=True)
def off_peak_clock(monkeypatch):
    monkeypatch.setattr('quant.research.score_forecast_text.request_window',
                        lambda: {'allowed': True, 'next_allowed_at': '2026-09-12T00:00:00+00:00'})


def diagnosis(pointer="source0#/effective_months", value=24):
    return {"findings": [{"claim": "有效历史较短", "evidence": [
        {"pointer": pointer, "value": value}]}], "candidates": []}


@pytest.mark.parametrize("pointer,value", [("unknown", 24), ("source0#/effective_months", 96),
                                          ("source0#/effective_months", "24")])
def test_rejects_invented_citation(pointer, value):
    with pytest.raises(ValueError):
        parse_diagnosis(json.dumps(diagnosis(pointer, value)), {"source0#/effective_months": 24})


def test_rejects_unattributed_numbers_or_execution_fields():
    data = diagnosis()
    data["findings"][0]["claim"] = "历史只有24个月"
    with pytest.raises(ValueError):
        parse_diagnosis(json.dumps(data), {"source0#/effective_months": 24})
    data = diagnosis()
    data["orders"] = []
    with pytest.raises(ValueError):
        parse_diagnosis(json.dumps(data), {"source0#/effective_months": 24})


def test_only_artifacts_and_bounded_facts(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    source = root / "stats.json"
    source.write_text(json.dumps({"effective_months": 24, "ic": .02}))
    facts, sources = extract_facts([source], artifact_root=root, max_facts=1)
    assert facts == {"source0#/effective_months": 24} and len(sources) == 1
    with pytest.raises(ValueError):
        extract_facts([source], artifact_root=tmp_path / "other")


def test_dry_run_and_cited_result_resume(tmp_path):
    source = tmp_path / "stats.json"
    source.write_text(json.dumps({"effective_months": 24}))

    class Client:
        calls = 0

        def complete_messages(self, messages, settings):
            self.calls += 1
            assert json.loads(messages[1]["content"])["facts"] == {"source0#/effective_months": 24}
            return {"model": "deepseek-flash", "usage": {"prompt_tokens": 500,
                    "completion_tokens": 200, "total_tokens": 700},
                    "choices": [{"finish_reason": "stop", "message": {
                        "content": json.dumps(diagnosis())}}]}

    client = Client()
    args = dict(inputs=[source], config=CONFIG, cache_path=tmp_path / "cache.sqlite",
                artifact_root=tmp_path, client=client)
    dry = run_diagnosis(**args, output=tmp_path / "dry")
    assert dry["dry_run"] and client.calls == 0
    for index in range(2):
        report = run_diagnosis(**args, output=tmp_path / str(index), execute=True,
                               max_requests=2, max_usd=.1)
        assert report["result"] == "success"
    assert client.calls == 1
