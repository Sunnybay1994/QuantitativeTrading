"""C4: monthly research brief — numbers from code, LLM only narrates."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import hashlib
import math
from pathlib import Path

import polars as pl

from quant.llm.ledger import append as ledger_append,SHANGHAI
from quant.reporting.structured_market import fund_share_facts,render_fund_shares
from quant.reporting.structured_margin import margin_facts,render_margin

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
                    stamp=dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    parsed.append((stamp.replace(tzinfo=SHANGHAI) if stamp.tzinfo is None else stamp.astimezone(SHANGHAI)).date())
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
    market=[]
    for path in (root/'artifacts/research').glob('market_indicators_*/summary.json'):
        payload=json.loads(path.read_text(encoding='utf-8'))
        latest=payload.get('latest') or {}
        date=str(latest.get('trade_date') or '')[:10]
        if date and date<=str(end) and 'observed_stocks' in latest:
            market.append((date,path,latest))
    market_fact={'status':'unavailable_for_month','source':None,'as_of':None,'values':{}}
    if market:
        date,path,latest=max(market,key=lambda item:item[0])
        market_fact={'status':'observed_in_month' if str(start)<=date else 'stale_before_month',
            'source':str(path),'as_of':date,'values':latest}
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
        "market_state":market_fact,
        "etf_shares":fund_share_facts(month,root=root),
        "margin":margin_facts(month,root=root),
    }


def render_template(facts: dict, narrative: str | None = None) -> str:
    lines = [
        f"# 研究简报 {facts['month']}",
        "",
        "数字均由代码填入；LLM 每月只写一次「市场状态解读」，不得改数字。",
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
              "", "## 市场状态输入", f"- {facts.get('market_state')}",
              "", "## 市场状态解读", narrative or "（本月无可用的LLM解读；保留机器事实及调用回执）", ""]
    if facts.get('etf_shares'):
        lines.extend(['',render_fund_shares(facts['etf_shares']),''])
    if facts.get('margin'):
        lines.extend(['',render_margin(facts['margin']),''])
    return "\n".join(lines)


def _llm_narrative(facts: dict,*,cache_path:Path,ledger_root:Path,pricing:Path) -> str | None:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding='utf-8')).get('accepted_text')
        except json.JSONDecodeError:
            return None
    cache_path.parent.mkdir(parents=True,exist_ok=True)
    receipt={'status':'attempted','month':facts['month'],'maximum_calls':1,
        'facts_sha256':hashlib.sha256(json.dumps(facts,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()}
    try:
        with cache_path.open('x',encoding='utf-8') as handle:
            handle.write(json.dumps(receipt,ensure_ascii=False))
    except FileExistsError:
        return None
    def save():
        temporary=cache_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(cache_path)
    try:
        from quant.llm import complete_messages
    except Exception:
        receipt['status']='client_unavailable';save()
        return None
    messages = [
        {"role": "system", "content": (
            "用简体中文写不超过120字的「市场状态解读」。只解释给定的市场状态输入及其证据限制。"
            "若输入缺失或早于当月，必须明确资料不足，禁止凭空描述本月行情。禁止改写、复述或编造任何数字；不要给出买卖指令。"
        )},
        {"role": "user", "content": json.dumps(
            {k: facts[k] for k in facts if k != "funnel"}, ensure_ascii=False, default=str)},
    ]
    try:
        response = complete_messages(messages, {"max_usd": 0.2, "reserve_usd": 0.2, "max_tokens": 200})
    except Exception as exc:
        receipt.update(status='request_failed',error_type=type(exc).__name__)
        code=getattr(exc,'code','')
        if code not in ('connect_failed','monthly_budget_exhausted'):
            ledger_append({'task':'research_brief','usd':.2,'estimated':True,'unknown_charge':True,
                'month':facts['month'],'artifact':str(cache_path)},ledger_root)
        save()
        return None
    from quant.research.gp_hints import priced_usd
    usd,estimated=priced_usd(response,pricing)
    unknown=usd is None or not math.isfinite(usd) or usd<=0
    usd=.2 if unknown else usd
    ledger_append({'task':'research_brief','usd':usd,'estimated':estimated or unknown,'unknown_charge':unknown,
        'month':facts['month'],'artifact':str(cache_path),'usage':response.get('usage')},ledger_root)
    receipt.update(response=response,usd=usd,estimated=estimated or unknown)
    text = response.get("content") or ""
    if response.get('choices'):
        text=response['choices'][0].get('message',{}).get('content') or ''
    if isinstance(response.get("message"), dict):
        text = response["message"].get("content", text)
    if not isinstance(text,str):
        receipt['status']='invalid_response_text';save()
        return None
    text = text.strip()
    if re.search(r"\d", text):
        # Reject narratives that inject digits (protect facts).
        receipt['status']='rejected_numeric_narrative';save()
        return None
    receipt.update(status='accepted' if text else 'empty_response',accepted_text=text or None)
    save()
    return text


def write_brief(month: str, *, root: Path = Path("."), use_llm: bool = True) -> dict:
    facts = collect_facts(month, root=root)
    narrative = _llm_narrative(facts,cache_path=root/BRIEF_ROOT/f'{month}.narrative.json',
        ledger_root=root/'artifacts/research/llm_ledger',pricing=Path(__file__).resolve().parents[3]/'configs/llm/pricing.toml') if use_llm else None
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
