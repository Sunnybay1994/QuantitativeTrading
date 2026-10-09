from pathlib import Path

from quant.research.gp_hints import (
    apply_soft_constraints,
    deterministic_hints,
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


def test_soft_constraints_recorded():
    settings = apply_soft_constraints(
        {"favored_terminals": ["gp_a"], "seed": 1},
        {"avoid_operator_families": ["ts_corr"], "suggested_inputs": ["gp_b"],
         "avoid_windows": [], "batch": "1"},
    )
    assert "gp_hints" in settings
    assert "gp_b" in settings["favored_terminals"]
