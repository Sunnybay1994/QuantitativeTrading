"""C4: monthly research brief — numbers from code, LLM only narrates."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import polars as pl

from quant.llm.ledger import append as ledger_append

BRIEF_ROOT = Path("artifacts/research/brief")


def collect_facts(month: str, *, root: Path = Path(".")) -> dict:
    """Assemble machine facts for YYYY-MM; LLM must not alter these numbers."""
    year, mon = map(int, month.split("-"))
    start = dt.date(year, mon, 1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    registry = root / "artifacts/registry/experiments.parquet"
    new_rows = 0
    conclusions: dict[str, int] = {}
    if registry.is_file():
        frame = pl.read_parquet(registry)
        if "result_time" in frame.columns:
            parsed = []
            for value in frame["result_time"].to_list():
                try:
                    parsed.append(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date())
                except ValueError:
                    parsed.append(None)
            month_frame = frame.with_columns(pl.Series("result_day", parsed)).filter(
                (pl.col("result_day") >= start) & (pl.col("result_day") <= end)
            )
            new_rows = month_frame.height
            if "conclusion" in month_frame.columns:
                for row in month_frame.group_by("conclusion").len().iter_rows():
                    conclusions[str(row[0])] = int(row[1])
    n5 = root / f"artifacts/research/nightly/monthly/{month}/summary.json"
    n5_methods = {}
    if n5.is_file():
        summary = json.loads(n5.read_text(encoding="utf-8"))
        for name, item in (summary.get("methods") or {}).items():
            n5_methods[name] = (item.get("conclusions") or {}).get("budgeted") or item.get("conclusion")
    forward = list((root / "artifacts/paper").glob("**/forward_evaluation.json"))
    q10_forward = None
    if forward:
        q10_forward = json.loads(max(forward, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"))
    ledger = root / f"artifacts/research/llm_ledger/{month}.jsonl"
    llm_usd = 0.0
    llm_tasks = 0
    if ledger.is_file():
        from quant.llm.ledger import priced_rows
        for row in priced_rows(ledger):
            llm_usd += float(row.get("usd") or row.get("cost_usd") or 0)
            llm_tasks += 1
    funnel_path = root / "artifacts/research/funnel_latest.json"
    funnel = json.loads(funnel_path.read_text(encoding="utf-8")) if funnel_path.is_file() else {}
    hints = sorted((root / "configs/research/gp_hints").glob("batch_*.toml"))
    return {
        "month": month,
        "registry_new_rows": new_rows,
        "registry_conclusions": conclusions,
        "n5_methods": n5_methods,
        "q10_forward": {
            "status": (q10_forward or {}).get("status"),
            "complete_oos_months": (q10_forward or {}).get("complete_oos_months"),
            "cumulative_oos_excess_primary": (q10_forward or {}).get("cumulative_oos_excess_primary"),
        } if q10_forward else None,
        "llm_month_usd": round(llm_usd, 4),
        "llm_tasks": llm_tasks,
        "funnel": funnel,
        "gp_hints_count": len(hints),
        "latest_gp_hint": str(hints[-1]) if hints else None,
    }


def render_template(facts: dict, narrative: str | None = None) -> str:
    lines = [
        f"# 研究简报 {facts['month']}",
        "",
        "数字均由代码填入；LLM 仅可写「下月建议关注」段落且不得改数字。",
        "",
        "## 注册表当月",
        f"- 新增行：{facts['registry_new_rows']}",
        f"- 结论分布：{facts['registry_conclusions']}",
        "",
        "## N5 月度模型",
    ]
    for name, conclusion in (facts.get("n5_methods") or {}).items():
        lines.append(f"- {name}: {conclusion}")
    lines += ["", "## Q10 前向", f"- {facts.get('q10_forward')}", "",
              "## LLM", f"- 花费 USD：{facts['llm_month_usd']}；任务数：{facts['llm_tasks']}",
              "", "## 漏斗 / hints",
              f"- funnel keys：{list((facts.get('funnel') or {}).keys())}",
              f"- gp_hints：{facts.get('gp_hints_count')}；最新 {facts.get('latest_gp_hint')}",
              "", "## 下月建议关注", narrative or "（未调用 LLM；保留机器事实）", ""]
    return "\n".join(lines)


def _llm_narrative(facts: dict) -> str | None:
    try:
        from quant.llm import complete_messages
    except Exception:
        return None
    messages = [
        {"role": "system", "content": (
            "用简体中文写不超过 120 字的「下月建议关注」。禁止改写、复述或编造任何数字；"
            "不要给出买卖指令。"
        )},
        {"role": "user", "content": json.dumps(
            {k: facts[k] for k in facts if k != "funnel"}, ensure_ascii=False, default=str)},
    ]
    try:
        response = complete_messages(messages, {"max_usd": 0.2, "reserve_usd": 0.2, "max_tokens": 200})
    except Exception:
        return None
    text = response.get("content") or ""
    if isinstance(response.get("message"), dict):
        text = response["message"].get("content", text)
    text = text.strip()
    if re.search(r"\d", text):
        # Reject narratives that inject digits (protect facts).
        return None
    ledger_append({"task": "research_brief", "usd": response.get("usd") or 0, "month": facts["month"]})
    return text


def write_brief(month: str, *, root: Path = Path("."), use_llm: bool = True) -> dict:
    facts = collect_facts(month, root=root)
    narrative = _llm_narrative(facts) if use_llm else None
    text = render_template(facts, narrative)
    out = root / BRIEF_ROOT / f"{month}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / f"{month}.facts.json").write_text(
        json.dumps(facts, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    out.write_text(text, encoding="utf-8")
    try:
        from quant.notify import send
        send(subject=f"research brief {month}", body=text[:2000])
    except Exception:
        pass
    return {"path": str(out), "facts": facts, "narrative": bool(narrative)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    print(json.dumps(write_brief(args.month, use_llm=not args.no_llm), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
