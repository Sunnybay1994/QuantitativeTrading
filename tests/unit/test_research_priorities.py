"""B5: structured research_priorities.toml must parse and expose open items."""
import json
from pathlib import Path

import tomllib

from quant.research.research_feedback import open_priorities, prompt_context

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/research/research_priorities.toml"


def test_priorities_structured_and_open_complete():
    policy = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert "priorities" not in policy
    rows = policy["priority"]
    assert len(rows) >= 10
    required = {"id", "status", "mechanism", "evidence_paths", "stop_condition", "next_action", "updated"}
    for row in rows:
        assert required <= set(row)
        assert row["status"] in ("open", "closed")
    opens = open_priorities(policy)
    assert opens
    assert all(r["status"] == "open" for r in opens)
    assert {r["id"] for r in opens} >= {
        "llm_weekly_candidates",
        "q10_paper_and_next_candidate",
    }
    closed = {r['id'] for r in rows if r['status'] == 'closed'}
    assert {'price_delay_family_v1', 'return_seasonality_family_v1'} <= closed


def test_prompt_context_shorter_than_legacy_blob():
    # Legacy priorities string list was ~14KB of English prose in the policy payload.
    ctx = prompt_context(CONFIG)
    payload = json.dumps(ctx["policy"], ensure_ascii=False, default=str)
    assert "open_priorities" in ctx["policy"]
    assert len(payload) < 7000
    assert all(item["status"] == "open" for item in ctx["open_priorities"])
