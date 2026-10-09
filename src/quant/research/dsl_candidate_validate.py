"""C2: compile/validate LLM factor expressions and prepare retry feedback."""
from __future__ import annotations

import ast
from typing import Any

import polars as pl

from quant.factors.expressions import ExpressionEngine
from quant.factors.search import canonical


def operator_table(operators: list[str], fields: list[str]) -> dict[str, list[str]]:
    return {"fields": sorted(fields), "operators": sorted(operators)}


def legal_examples(library_rows: list[dict], *, limit: int = 3) -> list[dict]:
    """Pick short library expressions as positive DSL examples."""
    ranked = sorted(library_rows, key=lambda r: len(str(r.get("expression", ""))))
    out = []
    for row in ranked:
        expr = row.get("expression") or row.get("expr")
        if not expr:
            continue
        try:
            ast.parse(expr, mode="eval")
        except SyntaxError:
            continue
        out.append({"id": row.get("id"), "expression": expr, "direction": row.get("direction", 1)})
        if len(out) >= limit:
            break
    return out


def compile_expression(expression: str, fields: list[str]) -> None:
    """Raise if expression fails ExpressionEngine.compile against a stub panel."""
    import datetime as dt

    tree = ast.parse(expression, mode="eval")
    used = {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id in set(fields)
    }
    if not used:
        raise ValueError("expression_requires_an_allowed_input_column")
    columns: dict[str, pl.Series] = {
        "symbol": pl.Series("symbol", ["000001.SZ", "000001.SZ", "000002.SZ"]),
        "trade_date": pl.Series(
            "trade_date",
            [dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)],
        ),
    }
    for name in used:
        if name == "industry_l1":
            columns[name] = pl.Series(name, ["A", "A", "B"])
        else:
            columns[name] = pl.Series(name, [1.0, 2.0, 3.0])
    ExpressionEngine(pl.DataFrame(columns)).compile(expression)


def partition_candidates(
    payload: dict,
    *,
    fields: list[str],
    existing_keys: set[str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return raw, validated, rejected partitions with compile + duplicate checks."""
    raw = list(payload.get("candidates") or [])
    validated, rejected = [], []
    seen = set(existing_keys)
    for index, row in enumerate(raw):
        item = {"index": index, "candidate": row}
        try:
            expression = row["expression"]
            if row.get("direction") not in (-1, 1):
                raise ValueError("direction must be 1 or -1")
            if not row.get("rationale"):
                raise ValueError("mechanism/rationale required")
            compile_expression(expression, fields)
            key = canonical(expression)
            if key in seen:
                raise ValueError("duplicate_expression")
            seen.add(key)
            validated.append({
                **row,
                "mechanism": row.get("rationale"),
                "source": "llm_weekly",
                "canonical": key,
            })
        except Exception as exc:  # noqa: BLE001 - surface any compile/schema failure to LLM retry
            rejected.append({**item, "reason": f"{type(exc).__name__}: {exc}"[:500]})
    return raw, validated, rejected


def retry_messages(
    base_messages: list[dict],
    rejected: list[dict],
    *,
    operators: list[str],
    fields: list[str],
    examples: list[dict],
) -> list[dict]:
    feedback = {
        "task": "repair_invalid_dsl_candidates",
        "allowed": operator_table(operators, fields),
        "legal_examples": examples,
        "rejected": rejected[:20],
        "instruction": (
            "Return a JSON object with candidates array only. "
            "Fix syntax/operators using the allowed table and examples. "
            "Keep distinct mechanisms; do not invent new operators."
        ),
    }
    return [
        *base_messages,
        {"role": "user", "content": __import__("json").dumps(feedback, ensure_ascii=False)},
    ]


def illegal_rate(raw_count: int, rejected_count: int) -> float:
    if raw_count <= 0:
        return 0.0
    return rejected_count / raw_count
