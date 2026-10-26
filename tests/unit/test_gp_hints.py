from pathlib import Path

import pytest

from quant.research.gp_hints import (
    apply_soft_constraints,
    deterministic_hints,
    priced_usd,
    update_from_feedback,
    write_hint_toml,
)


def test_deterministic_and_write(tmp_path: Path):
    batch = {
        "run": "artifacts/research/continuous/batch_000069/2026-10-07",
        "statistical_pass": 0,
        "candidate_diagnostics": [
            {"factor": "a", "expression": "ts_corr(x,y,20)", "conclusion": "REJECTED",
             "reject_stage": "statistics"},
            {"factor": "b", "expression": "ts_corr(a,b,10)", "conclusion": "REJECTED",
             "reject_stage": "fdr"},
        ],
        "families": {"nightly_x": {"statistical_pass": 1}},
    }
    hints = deterministic_hints(batch)
    assert "ts_corr" in hints["avoid_operator_families"]
    path = tmp_path / "batch_000069.toml"
    write_hint_toml(path, hints, batch_id="000069", source="deterministic")
    assert path.is_file()
    result = update_from_feedback(
        {"completed_batteries": [batch]}, hints_dir=tmp_path, use_llm=False)
    assert result["written"]
    assert Path(result["written"]).is_file()


def test_llm_is_called_once_per_batch(tmp_path, monkeypatch):
    calls = []

    def enrich(base, batch, *, batch_id, pricing_path):
        calls.append(batch_id)
        return {**base, "rationale": "from llm"}

    monkeypatch.setattr("quant.research.gp_hints._llm_enrich", enrich)
    batch = {"run": "artifacts/research/continuous/batch_000070/2026-10-07", "statistical_pass": 1}
    feedback = {"completed_batteries": [batch]}
    kwargs = {"hints_dir": tmp_path / "hints", "cache_dir": tmp_path / "cache", "use_llm": True}
    first = update_from_feedback(feedback, **kwargs)
    second = update_from_feedback(feedback, **kwargs)
    assert calls == ["000070"]
    assert first["source"] == second["source"] == "llm"


def test_missing_provider_usd_is_estimated_from_tariff(tmp_path):
    tariff = tmp_path / "pricing.toml"
    tariff.write_text("input_usd_per_million = 0.3\noutput_usd_per_million = 1.2\n", encoding="utf-8")
    usd, estimated = priced_usd(
        {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}, tariff)
    assert estimated is True
    assert usd == pytest.approx(0.3)
    quoted, flag = priced_usd({"usd": 0.2, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}, tariff)
    assert flag is False and quoted == pytest.approx(0.2)
    assert priced_usd({"usd": 0, "usage": {}}, tariff) == (None, False)


def test_freeze_inventory_omits_intraday_bars():
    from pathlib import Path
    text = Path("src/quant/data/gp_context_inputs.py").read_text(encoding="utf-8")
    assert "clean/bar_intraday" not in text


def test_soft_constraints_recorded():
    settings = apply_soft_constraints(
        {"favored_terminals": ["gp_a"], "seed": 1},
        {"avoid_operator_families": ["ts_corr"], "suggested_inputs": ["gp_b"],
         "avoid_windows": [], "batch": "1"},
    )
    assert "gp_hints" in settings
    assert "gp_b" in settings["favored_terminals"]
