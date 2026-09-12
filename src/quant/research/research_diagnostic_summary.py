"""Deterministic whole-scorecard counts and balanced examples for LLM diagnosis."""
from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path

import polars as pl

from quant.factors.forecast_text_score import strict_json

VERSION = "scorecard_model_summary_v1"
VARIANTS = ("raw", "size_industry_neutral")
FLAGS = ("statistical_pass", "costs_complete", "cost_excess_pass", "redundancy_pass", "factor_admitted")
METRICS = ("months", "icir", "newey_west_t", "cost_1_cagr", "cost_2_cagr", "cost_1_sharpe", "cost_1_max_drawdown")
SAMPLE_FIELDS = ("direction", *METRICS, *FLAGS, "conclusion")
MODEL_FIELDS = ("conclusion", "strongest_benchmark", "net_cagr_excess", "annual_outperformance_fraction",
                "active_start", "active_years", "underwater/years", "risk/first", "risk/last",
                "risk/cagr", "risk/sharpe", "risk/max_drawdown")


def _scalar(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str) and len(value) <= 200:
        return value
    raise ValueError("Summary expects short scalar metrics")


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _source(path: Path, *, root: Path, source: str, suffix: str) -> dict:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != suffix:
        raise ValueError("Summary inputs must be the requested artifact types under artifact_root")
    if suffix == ".json" and path.stat().st_size > 2_000_000:
        raise ValueError("Model assessment exceeds the 2MB input limit")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"source": source, "path": str(path), "sha256": digest}


def build_research_summary(*, scorecard: Path, assessments: list[Path], artifact_root: Path) -> dict:
    """All aggregates scan the entire input; examples are a fixed five-stratum sample.

    Each requested assessment receives its entire fixed field set. This mode
    never truncates one source to make room for another; the caller applies the
    existing overall request byte/budget limit before any provider call.
    """
    ordered = sorted(path.resolve() for path in assessments)
    if len(ordered) > 10 or len(set(ordered)) != len(ordered):
        raise ValueError("Provide at most ten distinct model assessments per diagnosis")
    sources = [_source(scorecard, root=artifact_root, source="source0", suffix=".parquet")]
    table = pl.read_parquet(scorecard)
    if (not {"factor", "variant"}.issubset(table.columns) or table.is_empty()
            or table.select("factor", "variant").is_duplicated().any()
            or table["factor"].null_count() or table["variant"].null_count()):
        raise ValueError("Scorecard requires nonempty unique factor/variant rows")
    factors = sorted(table["factor"].unique().to_list())
    if (any(not isinstance(factor, str) or not factor or len(factor) > 100 for factor in factors)
            or set(table.select("factor", "variant").rows()) != {(f, v) for f in factors for v in VARIANTS}):
        raise ValueError("Full scorecard must include raw and neutralized variants for every factor")
    rows = table.to_dicts()
    indexed = {(row["factor"], row["variant"]): (index, row) for index, row in enumerate(rows)}
    for row in rows:
        if any(row.get(field) is not None and type(row[field]) is not bool for field in FLAGS):
            raise ValueError("Scorecard status flags must be booleans or missing")
    facts, origins = {}, {}

    def add(key: str, value: object, **origin: object) -> None:
        pointer = f"summary#/{key}"
        facts[pointer] = _scalar(value)
        origins[pointer] = origin

    add("scope/aggregates", "All rows in the supplied scorecard; counts are factor-variant rows unless labelled factors", operation="policy")
    add("scope/examples", "Fixed strata with lexical selection; both variants; illustrative, not representative or independent validation", operation="policy")
    add("scope/models", "Every requested model: primary only; sensitivity, annual and stress arrays omitted", operation="policy")
    add("full_scorecard/rows", len(rows), source="source0", operation="count_all_rows")
    add("full_scorecard/factors", len(factors), source="source0", operation="count_distinct_factor")
    for variant in VARIANTS:
        section = [row for row in rows if row["variant"] == variant]
        prefix = f"full_scorecard/{variant}"
        add(f"{prefix}/rows", len(section), source="source0", operation="count_rows", variant=variant)
        for field in FLAGS:
            for label, flag_value in (("true", True), ("false", False), ("missing", None)):
                add(f"{prefix}/{field}/{label}", sum(row.get(field) is flag_value for row in section),
                    source="source0", operation="count_flag", variant=variant, field=field, equals=flag_value,
                    absent_column=field not in table.columns)
        for field in METRICS:
            count = sum(_scalar(row.get(field)) is None for row in section)
            add(f"{prefix}/missing_metrics/{field}", count, source="source0", operation="count_missing_or_nonfinite",
                variant=variant, field=field, absent_column=field not in table.columns)
        reasons: Counter[str] = Counter()
        unknown = 0
        for row in section:
            value = row.get("statistical_failures")
            if value is None:
                unknown += 1
            elif not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError("Statistical failures must be lists of reason strings")
            else:
                reasons.update(set(value))
        if len(reasons) > 32:
            raise ValueError("Unexpected number of statistical failure categories")
        add(f"{prefix}/failure_reasons_unknown", unknown, source="source0", operation="count_missing_failure_list", variant=variant)
        for reason, count in sorted(reasons.items()):
            add(f"{prefix}/failure_reasons/{_escape(reason)}", count, source="source0",
                operation="count_rows_containing_failure_reason_nonexclusive", variant=variant, reason=reason)
    strata = {
        "admitted": lambda r: r.get("factor_admitted") is True,
        "statistical_rejected": lambda r: r.get("statistical_pass") is False,
        "cost_rejected": lambda r: r.get("statistical_pass") is True and r.get("costs_complete") is True and r.get("cost_excess_pass") is False,
        "redundancy_rejected": lambda r: r.get("statistical_pass") is True and r.get("redundancy_pass") is False,
        "evidence_missing": lambda r: r.get("costs_complete") is not True or r.get("redundancy_pass") is None,
    }
    selections, chosen = {}, set()
    for name, predicate in strata.items():
        available = sorted({row["factor"] for row in rows if predicate(row)})
        unused = [factor for factor in available if factor not in chosen]
        selected = (unused or available or [None])[0]
        if selected is not None:
            chosen.add(selected)
        selections[name] = {"eligible_factors": len(available), "selected": selected,
                            "rule": "first_lexical_unselected_factor_else_first_lexical; all_matching_variants_count"}
        add(f"sample_selection/{name}/eligible_factors", len(available), source="source0", operation="stratum_distinct_factor_count", stratum=name)
        add(f"sample_selection/{name}/selected", selected, source="source0", operation="deterministic_stratum_selection", stratum=name)
    for factor in sorted(chosen):
        for variant in VARIANTS:
            index, row = indexed[(factor, variant)]
            for field in SAMPLE_FIELDS:
                add(f"examples/{_escape(factor)}/{variant}/{field}", row.get(field), source="source0",
                    pointer=f"source0#/rows/{index}/{_escape(field)}", row_key={"factor": factor, "variant": variant},
                    absent_column=field not in table.columns, nonfinite_to_missing=isinstance(row.get(field), float) and not math.isfinite(row[field]))
    for index, path in enumerate(ordered, 1):
        source = f"source{index}"
        sources.append(_source(path, root=artifact_root, source=source, suffix=".json"))
        document = strict_json(path.read_text(encoding="utf-8"))
        primary = document.get("primary")
        if not isinstance(primary, dict) or not isinstance(primary.get("conclusion"), str):
            raise ValueError("Each model assessment requires its primary conclusion")
        prefix = f"models/model{index}"
        add(f"{prefix}/name", path.parent.name, source=source, operation="assessment_parent_directory_name")
        for field in MODEL_FIELDS:
            model_value: object = primary
            missing = False
            for component in field.split("/"):
                if not isinstance(model_value, dict) or component not in model_value:
                    model_value, missing = None, True
                    break
                model_value = model_value[component]
            add(f"{prefix}/primary/{field}", model_value, source=source, pointer=f"{source}#/primary/{field}", absent_field=missing)
        checks = primary.get("checks", {})
        if not isinstance(checks, dict) or len(checks) > 32:
            raise ValueError("Model primary checks must be a bounded mapping")
        add(f"{prefix}/primary/checks_present", bool(checks), source=source, operation="nonempty_primary_checks")
        for name, value in sorted(checks.items()):
            if value is not None and type(value) is not bool:
                raise ValueError("Model primary checks must be booleans or missing")
            add(f"{prefix}/primary/checks/{_escape(name)}", value, source=source, pointer=f"{source}#/primary/checks/{_escape(name)}")
    for source_entry in sources:
        source_entry["fact_count"] = sum(origin.get("source") == source_entry["source"] for origin in origins.values())
    return {"version": VERSION, "facts": facts, "provenance": origins, "sources": sources,
        "selection": selections, "coverage": {"scorecard_rows": len(rows), "scorecard_factors": len(factors),
            "sampled_factors": sorted(chosen), "sampled_variant_rows": len(chosen) * 2,
            "assessments_requested": len(ordered), "assessments_included": len(ordered), "fact_count": len(facts)},
        "aggregation_scope": "entire_supplied_scorecard", "model_scope": "primary_only",
        "missing_policy": "null/nonfinite/absent stay missing; explicit false retained; costs_complete=false means incomplete evidence; no zero imputation"}
