"""A3 forward rules: attention can fire without demote in the demo window."""
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "configs/paper/q10_sue_v2_forward_rules_20261010.toml"


def test_forward_rules_frozen_fields():
    spec = tomllib.loads(RULES.read_text(encoding="utf-8"))
    assert spec["auto_trade"] is False
    assert spec["demote_to_research_only"]["minimum_complete_oos_months"] == 12
    assert spec["attention"]["cumulative_oos_excess_below"] == -0.05
    assert spec["halt_review"]["threshold_mdd"] == -0.3792


def test_demo_assertion_artifact():
    path = ROOT / "artifacts/paper/q10_sue_v2/monthly/demo_2025_08_2026_06.json"
    assert path.exists()
    import json

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["assertion"]["2026-06_status_is_attention"] is True
    assert result["assertion"]["2026-06_demote_false"] is True
