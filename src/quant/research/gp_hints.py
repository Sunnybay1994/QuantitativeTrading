"""C3: after N4, write structured GP soft-constraint hints (LLM optional, ≤$0.3)."""
from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from pathlib import Path

HINTS_DIR = Path("configs/research/gp_hints")
CACHE_DIR = Path("artifacts/research/gp_hints_cache")
MAX_USD = 0.3


def latest_hint(directory: Path = HINTS_DIR) -> Path | None:
    paths = sorted(directory.glob("batch_*.toml"))
    return paths[-1] if paths else None


def load_hint(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8"))


def batch_number(run: Path) -> str:
    match = re.search(r"batch_(\d+)", run.as_posix())
    return match.group(1) if match else run.name.replace("batch_", "")


def deterministic_hints(batch: dict) -> dict:
    """Machine fallback from funnel / diagnostics — no LLM required."""
    avoid_ops, avoid_windows, suggested = [], [], []
    for diagnostic in batch.get("candidate_diagnostics", [])[:20]:
        expr = str(diagnostic.get("expression") or diagnostic.get("expr") or "")
        for op in ("ts_corr", "ts_cov", "delta", "delay", "rank"):
            if op in expr and op not in avoid_ops and diagnostic.get("conclusion") == "REJECTED":
                # Prefer avoiding only when many rejects share the op — counted below.
                avoid_ops.append(op)
        stage = diagnostic.get("reject_stage") or diagnostic.get("first_failure")
        if stage and str(stage) not in avoid_windows:
            avoid_windows.append(str(stage))
    # Keep top-3 most common rejected operators.
    counts: dict[str, int] = {}
    for op in avoid_ops:
        counts[op] = counts.get(op, 0) + 1
    avoid_ops = [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    families = batch.get("families") or {}
    for name, summary in families.items():
        if summary.get("statistical_pass", 0) == 0 and name not in suggested:
            continue
        if summary.get("statistical_pass", 0) > 0:
            suggested.append(f"continue_{name}")
    if not suggested:
        suggested = ["favor_financial_pit_terminals", "prefer_incremental_residual_objective"]
    return {
        "avoid_operator_families": avoid_ops or ["none"],
        "avoid_windows": avoid_windows[:5] or ["none"],
        "suggested_inputs": suggested[:5],
        "rationale": (
            f"deterministic from batch {batch.get('run')}: "
            f"pass={batch.get('statistical_pass')} reject_heavy_ops={avoid_ops}"
        ),
    }


def write_hint_toml(path: Path, payload: dict, *, batch_id: str, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'batch = "{batch_id}"',
        f'written_on = {dt.date.today().isoformat()}',
        f'source = "{source}"',
        "auto_trade = false",
        "soft_constraint_only = true",
        f'rationale = {json.dumps(payload["rationale"], ensure_ascii=False)}',
        "",
        "avoid_operator_families = "
        + json.dumps(list(payload["avoid_operator_families"]), ensure_ascii=False),
        "avoid_windows = " + json.dumps(list(payload["avoid_windows"]), ensure_ascii=False),
        "suggested_inputs = " + json.dumps(list(payload["suggested_inputs"]), ensure_ascii=False),
        "",
    ]
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def priced_usd(response: dict, pricing_path: Path) -> tuple[float | None, bool]:
    """Provider usd wins. Otherwise estimate from the frozen tariff. Never return 0."""
    raw = response.get("usd") if response.get("usd") not in (None, 0, 0.0) else response.get("cost_usd")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return float(raw), False
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None, False
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int:
        return None, False
    from quant.llm.pricing import load_pricing

    rates = load_pricing(pricing_path)
    usd = (prompt * rates["input_usd_per_million"] + completion * rates["output_usd_per_million"]) / 1_000_000
    return (usd, True) if usd > 0 else (None, False)


def _llm_enrich(base: dict, batch: dict, *, batch_id: str, pricing_path: Path) -> dict | None:
    """Optional DeepSeek enrichment; returns None on budget/API failure."""
    try:
        from quant.llm import complete_messages, RequestFailure
        from quant.llm.ledger import append as ledger_append
    except ImportError:
        return None
    top = []
    for row in batch.get("candidate_diagnostics", [])[:20]:
        top.append({
            "factor": row.get("factor"),
            "expression": row.get("expression") or row.get("expr"),
            "conclusion": row.get("conclusion"),
            "reject_stage": row.get("reject_stage"),
            "mean_ic": (row.get("full_history") or {}).get("mean_ic"),
        })
    messages = [
        {"role": "system", "content": (
            "Return ONLY a JSON object with keys avoid_operator_families, avoid_windows, "
            "suggested_inputs (string arrays), rationale (string). Soft GP search hints only; "
            "do not invent admission rule changes."
        )},
        {"role": "user", "content": json.dumps({
            "seed_hints": base,
            "top_candidates": top,
            "batch_summary": {k: batch.get(k) for k in (
                "statistical_pass", "families", "search_selection") if k in batch},
        }, ensure_ascii=False, default=str)},
    ]
    settings = {"max_usd": MAX_USD, "reserve_usd": MAX_USD, "temperature": 0.2, "max_tokens": 600}
    try:
        response = complete_messages(messages, settings)
    except Exception:
        return None
    text = response.get("content") or response.get("text") or ""
    if isinstance(response.get("message"), dict):
        text = response["message"].get("content", text)
    try:
        usd, estimated = priced_usd(response, pricing_path)
        if usd is not None:
            ledger_append({
                "task": "gp_hints",
                "usd": usd,
                "estimated": estimated,
                "tokens": response.get("usage"),
                "batch": batch.get("run"),
                "batch_id": batch_id,
            })
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    for key in ("avoid_operator_families", "avoid_windows", "suggested_inputs", "rationale"):
        if key not in parsed:
            return None
    return parsed


def update_from_feedback(
    feedback: dict,
    *,
    hints_dir: Path = HINTS_DIR,
    cache_dir: Path = CACHE_DIR,
    pricing_path: Path | None = None,
    use_llm: bool = True,
) -> dict:
    """Write one hint file. Each batch_id calls the LLM at most once."""
    from quant.llm.pricing import DEFAULT_PRICING

    batches = feedback.get("completed_batteries") or []
    if not batches:
        return {"written": None, "reason": "no_completed_batteries"}
    batch = batches[-1]
    run = Path(batch["run"])
    batch_id = batch_number(run)
    path = hints_dir / f"batch_{batch_id}.toml"
    tariff = pricing_path or DEFAULT_PRICING
    base = deterministic_hints(batch)
    source = "deterministic"
    payload = base
    receipt = cache_dir / f"batch_{batch_id}.json"
    if use_llm and receipt.is_file():
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if saved.get("ok") and isinstance(saved.get("payload"), dict):
            payload, source = saved["payload"], "llm"
    elif use_llm:
        enriched = _llm_enrich(base, batch, batch_id=batch_id, pricing_path=tariff)
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = receipt.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(
            {"ok": enriched is not None, "payload": enriched}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(receipt)
        if enriched:
            payload, source = enriched, "llm"
    write_hint_toml(path, payload, batch_id=batch_id, source=source)
    return {"written": str(path), "source": source, "batch": batch_id}


def apply_soft_constraints(search_settings: dict, hint: dict | None) -> dict:
    """Bias favored terminals / note avoided ops; never touch fitness or admission."""
    if not hint:
        return search_settings
    updated = dict(search_settings)
    updated["gp_hints"] = {
        "avoid_operator_families": list(hint.get("avoid_operator_families") or []),
        "avoid_windows": list(hint.get("avoid_windows") or []),
        "suggested_inputs": list(hint.get("suggested_inputs") or []),
        "batch": hint.get("batch"),
        "soft_constraint_only": True,
    }
    suggested = hint.get("suggested_inputs") or []
    favored = list(updated.get("favored_terminals") or [])
    for item in suggested:
        if item.startswith("gp_") and item not in favored:
            favored.append(item)
    if favored:
        updated["favored_terminals"] = favored
    return updated
