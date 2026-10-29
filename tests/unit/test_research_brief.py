from pathlib import Path

from quant.reporting.research_brief import collect_facts, render_template, write_brief


def test_brief_template_keeps_facts(tmp_path: Path):
    facts = {
        "month": "2026-10",
        "registry_new_rows": 1,
        "registry_conclusions": {"REJECTED": 1},
        "n5_methods": {"q10_plus_admitted": "PAPER_CANDIDATE"},
        "q10_forward": None,
        "llm_month_usd": 0.0,
        "llm_tasks": 0,
        "funnel": {},
        "gp_hints_count": 0,
        "latest_gp_hint": None,
    }
    text = render_template(facts, "关注增量模型稳定性")
    assert "PAPER_CANDIDATE" in text
    assert "关注增量模型稳定性" in text


def test_write_brief_no_llm(tmp_path: Path, monkeypatch):
    notifications = []
    monkeypatch.setattr("quant.notify.send", lambda **kw: notifications.append(kw))
    result = write_brief("2026-10", root=tmp_path, use_llm=False)
    path = Path(result["path"])
    assert path.is_file() and path.is_relative_to(tmp_path)
    assert result["facts"]["month"] == "2026-10"
    assert result["facts"]["registry_new_rows"] == 0
    assert result["facts"]["llm_month_usd"] == 0
    assert len(notifications) == 1
    assert notifications[0]["subject"] == "research brief 2026-10"
