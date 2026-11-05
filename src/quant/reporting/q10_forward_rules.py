"""Evaluate frozen Q10 paper forward rules (A3). Advisory until user confirms halt."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.research.rolling_excess_diagnostics import monthly_excess_series, rolling_excess_diagnostics


class InsufficientMonthlySample(ValueError):
    """No month return can yet be measured from the available NAV boundaries."""


def rules_sha256(config: Path) -> str:
    return hashlib.sha256(config.read_bytes()).hexdigest()


def load_rules(config: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding="utf-8"))
    if spec.get("auto_trade") is not False:
        raise ValueError("forward rules require auto_trade=false")
    return spec


def evaluate_month(
    *,
    rules: dict,
    rules_path: Path,
    strategy_nav_1x: pl.DataFrame,
    strategy_nav_2x: pl.DataFrame | None,
    benchmarks: dict[str, pl.DataFrame],
    as_of_month: str,
    oos_start: dt.date,
) -> dict[str, Any]:
    """Evaluate rules at a month-end using provided nav paths (paper or demo replay)."""
    primary = rules["primary_benchmark"]
    monthly = monthly_excess_series(strategy_nav_1x, benchmarks[primary])
    row = monthly.filter(pl.col("month") == as_of_month)
    if row.is_empty():
        raise ValueError(f"no monthly excess for {as_of_month}")
    month_excess = float(row["excess"][0])
    oos = monthly.filter(pl.col("month_end") >= oos_start).filter(pl.col("month") <= as_of_month)
    cumulative = float(oos["excess"].sum()) if oos.height else None
    complete_oos_months = oos.height

    diag_1x = rolling_excess_diagnostics(strategy_nav_1x, benchmarks[primary])
    rolling = diag_1x["rolling12_excess"]
    rolling_end = next((s for s in rolling["series"] if s["month_end"] == as_of_month), None)
    rolling12_1x = None if rolling_end is None else float(rolling_end["excess"])

    rolling12_2x = None
    if strategy_nav_2x is not None:
        diag_2x = rolling_excess_diagnostics(strategy_nav_2x, benchmarks[primary])
        end2 = next(
            (s for s in diag_2x["rolling12_excess"]["series"] if s["month_end"] == as_of_month),
            None,
        )
        rolling12_2x = None if end2 is None else float(end2["excess"])

    bench_month = {}
    for name, frame in benchmarks.items():
        series = monthly_excess_series(strategy_nav_1x, frame).filter(pl.col("month") == as_of_month)
        if series.height:
            bench_month[name] = {
                "benchmark_return": float(series["benchmark_return"][0]),
                "excess": float(series["excess"][0]),
            }
    strongest = max(bench_month, key=lambda n: bench_month[n]["benchmark_return"]) if bench_month else primary

    attention_cfg = rules["attention"]
    flags = []
    if cumulative is not None and cumulative < attention_cfg["cumulative_oos_excess_below"]:
        flags.append("attention_cumulative_oos_excess")
    if month_excess < attention_cfg["single_month_excess_below"]:
        flags.append("attention_single_month_excess")

    demote_cfg = rules["demote_to_research_only"]
    demote = False
    demote_reason = None
    if complete_oos_months >= demote_cfg["minimum_complete_oos_months"] and rolling12_1x is not None:
        series = rolling["series"]
        idx = next((i for i, s in enumerate(series) if s["month_end"] == as_of_month), None)
        need = demote_cfg["consecutive_negative_month_ends"]
        if idx is not None and idx + 1 >= need:
            window = series[idx + 1 - need : idx + 1]
            if strategy_nav_2x is not None:
                series2 = rolling_excess_diagnostics(
                    strategy_nav_2x, benchmarks[primary]
                )["rolling12_excess"]["series"]
                map2 = {s["month_end"]: s["excess"] for s in series2}
                both_neg = all(
                    s["excess"] < 0 and map2.get(s["month_end"], 0) < 0 for s in window
                )
            else:
                both_neg = all(s["excess"] < 0 for s in window)
            if both_neg:
                demote = True
                demote_reason = "rolling12_excess_negative_both_costs_consecutive"

    status = "demote_to_research_only" if demote else ("attention" if flags else "ok")
    return {
        "as_of_month": as_of_month,
        "rules_id": rules["id"],
        "rules_sha256": rules_sha256(rules_path),
        "primary_benchmark": primary,
        "strongest_benchmark_this_month": strongest,
        "month_excess_primary": month_excess,
        "benchmark_month": bench_month,
        "cumulative_oos_excess_primary": cumulative,
        "complete_oos_months": complete_oos_months,
        "rolling12_excess_1x": rolling12_1x,
        "rolling12_excess_2x": rolling12_2x,
        "attention_flags": flags,
        "demote": demote,
        "demote_reason": demote_reason,
        "status": status,
        "halt_review": {
            "threshold_mdd": rules["halt_review"]["threshold_mdd"],
            "requires_user_confirmation": True,
            "note": "sell_only requires explicit user confirmation; not auto-applied",
        },
    }


def demo_replay_attention(
    *,
    rules_path: Path,
    nav_1x: pl.DataFrame,
    nav_2x: pl.DataFrame,
    benchmark_config: Path,
    data_root: Path,
    months: list[str],
) -> dict:
    """Historical demo: prove attention can fire without demote (pre-OOS)."""
    rules = load_rules(rules_path)
    benches = load_return_benchmarks(
        config=benchmark_config,
        data_root=data_root,
        start=dt.date(2019, 1, 1),
        end=dt.date(2026, 8, 31),
        names=list(rules["benchmarks"]),
    )
    first = dt.date.fromisoformat(months[0] + "-01")
    results = []
    for month in months:
        results.append(
            evaluate_month(
                rules=dict(rules),
                rules_path=rules_path,
                strategy_nav_1x=nav_1x,
                strategy_nav_2x=nav_2x,
                benchmarks=benches,
                as_of_month=month,
                oos_start=first,
            )
        )
    target = next(r for r in results if r["as_of_month"] == "2026-06")
    return {
        "demo": True,
        "months": results,
        "assertion": {
            "2026-06_status_is_attention": target["status"] == "attention",
            "2026-06_demote_false": target["demote"] is False,
            "2026-06_attention_flags": target["attention_flags"],
        },
    }


def _pct(value: float | None) -> str:
    return "不足" if value is None else f"{value:.2%}"


def write_monthly_package(
    *,
    stem: Path,
    evaluation: dict,
    markdown_extra: list[str] | None = None,
) -> None:
    """Write stem.md and stem.json."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")
    json_path.write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    lines = [
        f"# Q10 paper monthly {evaluation['as_of_month']}",
        "",
        f"rules: `{evaluation['rules_id']}` sha256=`{evaluation['rules_sha256']}`",
        "",
        f"status: **{evaluation['status']}**",
        "",
        "|benchmark|month return|month excess|",
        "|---|---:|---:|",
    ]
    for name, block in evaluation["benchmark_month"].items():
        lines.append(f"|{name}|{block['benchmark_return']:.2%}|{block['excess']:.2%}|")
    lines.append("")
    lines.append(f"cumulative OOS excess (primary): {_pct(evaluation['cumulative_oos_excess_primary'])}")
    lines.append(f"complete OOS months: {evaluation['complete_oos_months']}")
    lines.append(f"rolling12 excess 1x: {_pct(evaluation['rolling12_excess_1x'])}")
    lines.append(f"rolling12 excess 2x: {_pct(evaluation['rolling12_excess_2x'])}")
    lines.append(f"attention flags: {evaluation['attention_flags'] or 'none'}")
    lines.append(f"demote: {evaluation['demote']}")
    lines.append("")
    lines.append("halt_review requires explicit user confirmation before sell_only=true.")
    if markdown_extra:
        lines.extend(["", *markdown_extra])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_two_account_month(
    *,
    q10_output: Path,
    shadow_output: Path,
    rules_path: Path,
    stem: Path,
    data_root: Path,
    benchmark_config: Path | None = None,
) -> dict:
    """A3 month page for the live Q10 account and the size-neutral shadow."""
    rules = load_rules(rules_path)

    def nav_of(folder: Path) -> pl.DataFrame:
        snapshots = sorted(folder.glob("????-??-??/state.json"))
        if not snapshots:
            raise ValueError(f"missing paper snapshots: {folder}")
        state = json.loads(snapshots[-1].read_text(encoding="utf-8"))
        nav = pl.DataFrame(state["nav"]).with_columns(pl.col("date").str.to_date())
        value = 'unit_nav' if 'unit_nav' in nav.columns else 'equity'
        if (nav.is_empty() or nav['date'].null_count() or not nav['date'].is_sorted()
                or nav['date'].n_unique() != nav.height
                or nav[value].null_count() or not nav[value].is_finite().all()
                or (nav[value] <= 0).any()):
            raise ValueError(f"invalid paper NAV: {folder}")
        return nav

    q10_nav = nav_of(q10_output)
    shadow_nav = nav_of(shadow_output)
    as_of = q10_nav["date"].max()
    if shadow_nav['date'].max() != as_of:
        raise ValueError('Q10 and shadow NAV cutoffs differ')
    month_start = as_of.replace(day=1)
    for name, nav in (('q10', q10_nav), ('shadow', shadow_nav)):
        if not (nav['date'] < month_start).any():
            raise InsufficientMonthlySample(f'{name}: no NAV boundary before {month_start}')
    benchmarks = load_return_benchmarks(
        config=benchmark_config or Path(rules.get("return_benchmark_config", "configs/data/return_benchmarks_q1b_20260912.toml")),
        data_root=data_root,
        start=dt.date.fromisoformat(str(rules["oos_start"])),
        end=as_of,
    )
    month = f"{as_of.year:04d}-{as_of.month:02d}"
    oos = dt.date.fromisoformat(str(rules["oos_start"]))
    q10_eval = evaluate_month(
        rules=rules, rules_path=rules_path, strategy_nav_1x=q10_nav,
        strategy_nav_2x=None, benchmarks=benchmarks, as_of_month=month, oos_start=oos,
    )
    shadow_eval = evaluate_month(
        rules=rules, rules_path=rules_path, strategy_nav_1x=shadow_nav,
        strategy_nav_2x=None, benchmarks=benchmarks, as_of_month=month, oos_start=oos,
    )
    stem.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Q10 与规模中性影子 {month}", ""]
    for title, evaluation in (("Q10", q10_eval), ("影子 b0.5_k50_size_on", shadow_eval)):
        lines += [f"## {title}", "", "|benchmark|month return|month excess|", "|---|---:|---:|"]
        for name, block in evaluation["benchmark_month"].items():
            lines.append(f"|{name}|{block['benchmark_return']:.2%}|{block['excess']:.2%}|")
        lines.append("")
    path = stem.with_suffix(".md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {"status": "complete", "as_of_month": month, "q10": q10_eval, "shadow": shadow_eval}
    if benchmark_config is not None:
        payload['benchmark_source'] = {'config': str(benchmark_config),
            'sha256': hashlib.sha256(benchmark_config.read_bytes()).hexdigest(), 'as_of': str(as_of)}
    stem.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload
