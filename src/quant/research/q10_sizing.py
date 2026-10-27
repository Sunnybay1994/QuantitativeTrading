"""A5: preregistered Q10 sizing neighborhood grid (12 cells, no post-hoc edits)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path

import polars as pl

DEFAULT_CONFIG = Path("configs/portfolio/q10_sizing_v1.toml")


def cells(spec: dict) -> list[dict]:
    out = []
    for budget in spec["budgets"]:
        for top_k in spec["top_ks"]:
            for size_mode in spec["size_neutral_modes"]:
                out.append({
                    "cell_id": f"b{budget:g}_k{top_k}_size_{size_mode}",
                    "budget": float(budget),
                    "top_k": int(top_k),
                    "size_neutral": size_mode == "on",
                })
    if len(out) != 12:
        raise ValueError(f"A5 requires exactly 12 cells, got {len(out)}")
    return out


def _q10_2x_and_mdd(control: Path) -> tuple[float | None, float | None]:
    payload = json.loads((control / "assessment.json").read_text(encoding="utf-8"))
    bud = payload.get("assessments", {}).get("budgeted") or {}
    mdd = None
    for row in payload.get("rows", []):
        if row.get("variant") == "budgeted" and row.get("cost_multiplier") == 2.0:
            mdd = row.get("max_drawdown")
    excess = [
        r["net_cagr_excess"]
        for r in payload.get("benchmark_comparisons", [])
        if r.get("variant") == "budgeted" and r.get("cost_multiplier") == 2.0
        and r.get("net_cagr_excess") is not None
    ]
    return (float(min(excess)) if excess else bud.get("double_cost_excess")), mdd


def run_cell(
    *,
    spec: dict,
    cell: dict,
    output: Path,
    data_root: Path,
    resume: bool = False,
    score_frame: pl.DataFrame | None = None,
    execution_months: tuple[int, ...] | None = None,
    research_id: str | None = None,
    initial_cash: float | None = None,
) -> dict:
    from quant.backtest.share_exchanges import validate_exchanges
    from quant.data.equal_weight_index import load_return_benchmarks
    from quant.data.factor_panels import available_sessions
    from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
    from quant.reporting.experiment_registry import register_run
    from quant.reporting.multifactor_assessment import assess_model
    from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
    from quant.research.factor_battery_costs import run_cost_plans
    from quant.research.rolling_excess_diagnostics import rolling_excess_diagnostics
    from quant.research.run_constrained_portfolio import prepare_constrained_hook, window_metrics
    from quant.research.run_multifactor_replay import model_target_plans

    folder = output / cell["cell_id"]
    if (folder / "cell_result.json").is_file() and not resume:
        return json.loads((folder / "cell_result.json").read_text(encoding="utf-8"))
    if folder.exists() and not resume:
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)

    source = Path(spec["predictions"])
    scores = score_frame if score_frame is not None else pl.read_parquet(source / "monthly_predictions.parquet")
    model = tomllib.loads((source / "model.toml").read_text(encoding="utf-8"))
    settings = tomllib.loads((source / "battery.toml").read_text(encoding="utf-8"))
    settings["share_exchanges"] = validate_exchanges(
        tomllib.loads(Path("configs/data/share_exchanges_20260912.toml").read_text(encoding="utf-8"))[
            "share_exchanges"
        ]
    )
    if initial_cash is not None:
        settings["portfolio"]["initial_cash"] = float(initial_cash)
    model["portfolio"]["primary_top_k"] = cell["top_k"]
    model["models"]["methods"] = [spec["method"]]
    end = model["walk_forward"]["test_end"]
    sessions = available_sessions(data_root, end + dt.timedelta(days=40))
    name, targets = model_target_plans(scores, model=model, sessions=sessions)[
        f"{spec['method']}_top{cell['top_k']}"
    ]
    if execution_months:
        targets = targets.filter(pl.col("execution_date").dt.month().is_in(list(execution_months)))
    for filename in ("model.toml", "battery.toml"):
        shutil.copyfile(source / filename, folder / filename)
    shutil.copyfile(Path(spec["return_benchmark_config"]), folder / "return_benchmarks.toml")
    cell_toml = "\n".join([
        "[research]",
        f'id = "{research_id or f"q10-sizing-{cell["cell_id"]}"}"',
        f'registered_on = {dt.date.today().isoformat()}',
        f'cell_id = "{cell["cell_id"]}"',
        f"budget = {cell['budget']}",
        f"top_k = {cell['top_k']}",
        f"size_neutral = {str(cell['size_neutral']).lower()}",
        "auto_trade = false",
        "",
    ])
    (folder / "cell.toml").write_text(cell_toml, encoding="utf-8")
    (folder / "config.toml").write_text(cell_toml, encoding="utf-8")

    benchmarks = Path(spec["benchmarks"])
    snapshot = json.loads((benchmarks / "summary.json").read_text(encoding="utf-8"))["execution_snapshot"]
    target_constraints = None
    constraint_symbols = None
    if cell["size_neutral"]:
        policy = dict(spec["size_on_policy"])
        policy["top_k"] = cell["top_k"]
        transform, extra, _ = prepare_constrained_hook(
            scores=scores,
            targets=targets,
            statistics=Path(spec["statistics"]),
            policy=policy,
            score_column=spec["method"],
            minimum_signal_stocks=model["models"]["minimum_signal_stocks"],
        )
        target_constraints = transform
        constraint_symbols = extra
        settings["target_constraints_config"] = (folder / "cell.toml").read_text(encoding="utf-8")

    run_cost_plans(
        settings=settings,
        plans={"budgeted": (name, targets)},
        sessions=sessions,
        output=folder,
        data_root=data_root,
        execution_snapshot=snapshot,
        factor=f"q10-sizing-{cell['cell_id']}",
        start=model["walk_forward"]["test_start"],
        turnover_budgets={"budgeted": cell["budget"]},
        resume=resume and (folder / "replay_config.json").exists(),
        target_constraints=target_constraints,
        constraint_execution_symbols=constraint_symbols,
    )
    report = collect_cost_report(
        run=folder,
        benchmarks=benchmarks,
        data_root=data_root,
        return_benchmark_config=folder / "return_benchmarks.toml",
    )
    baselines = load_return_benchmarks(
        config=folder / "return_benchmarks.toml",
        data_root=data_root,
        start=model["walk_forward"]["test_start"],
        end=end,
    )
    baselines = {
        ("510300_total_return_reference" if k == "510300" else k): v for k, v in baselines.items()
    }
    model["admission"]["benchmarks"] = list(baselines)
    windows = tomllib.loads(Path(model["admission"]["stress_windows_config"]).read_text(encoding="utf-8"))[
        "cycle_validation"
    ]["stress_windows"]
    rows = {r["cost_multiplier"]: r for r in report["rows"] if r["variant"] == "budgeted"}
    for multiplier, row in rows.items():
        nav, trades = load_cost_history(folder, "budgeted", multiplier, end)
        if nav.filter(pl.col("market_value") > 0).height:
            turnover = calendar_turnover(nav, trades)
            measured = row.get("annualized_one_way_turnover") or 0
            median = turnover["median"] or 0
            # A zero calendar median must not wipe the cost-report turnover.
            row["annualized_one_way_turnover"] = measured if median == 0 and measured > 0 else median
    nav1, _ = load_cost_history(folder, "budgeted", 1.0, end)
    nav2, _ = load_cost_history(folder, "budgeted", 2.0, end)
    assessment = assess_model(
        nav=nav1, one=rows[1.0], two=rows[2.0], benchmarks=baselines, model=model, windows=windows
    )
    excess = [
        r["net_cagr_excess"]
        for r in report["benchmark_comparisons"]
        if r["variant"] == "budgeted" and r["cost_multiplier"] == 2.0 and r["net_cagr_excess"] is not None
    ]
    treatment_2x = min(excess) if excess else None
    if treatment_2x is not None:
        assessment["double_cost_excess"] = treatment_2x
        assessment["checks"]["turnover"] = turnover_passes(
            rows[1.0]["annualized_one_way_turnover"], treatment_2x
        )
    q10_2x, q10_mdd = _q10_2x_and_mdd(Path(spec["q10_control"]))
    mdd2 = rows[2.0].get("max_drawdown")
    delta_pp = None if treatment_2x is None or q10_2x is None else (treatment_2x - q10_2x) * 100
    mdd_ok = mdd2 is not None and q10_mdd is not None and mdd2 >= q10_mdd
    promote = (
        delta_pp is not None
        and delta_pp >= float(spec["promote_excess_pp"])
        and mdd_ok
        and all(assessment["checks"].values())
    )
    label = "CANDIDATE_REPLACEMENT" if promote else "RESEARCH_ONLY"
    # Registry admits only PAPER_CANDIDATE / RESEARCH_ONLY / REJECTED.
    assessment["conclusion"] = "RESEARCH_ONLY"
    assessment["sizing_label"] = label
    assessment["vs_q10_2x_excess_pp"] = delta_pp
    stress = window_metrics(
        nav2,
        dt.date.fromisoformat(str(spec["stress_start"])),
        dt.date.fromisoformat(str(spec["stress_end"])),
    )
    primary = assessment.get("strongest_benchmark") or next(iter(baselines))
    rolling = rolling_excess_diagnostics(nav1, baselines[primary])
    reg = rolling.get("registry") or {}
    diagnostics = {
        "rolling12_excess_min": reg.get("rolling12_excess_min"),
        "rolling24_excess": reg.get("rolling24_excess"),
        "best_month_share": reg.get("best_month_share"),
        "monthly_hit_rate": reg.get("monthly_hit_rate"),
        "stress_2024_01": stress,
    }
    (folder / "assessment.json").write_text(
        json.dumps({
            "rows": report["rows"],
            "assessments": {"budgeted": assessment},
            "benchmark_comparisons": report["benchmark_comparisons"],
            "diagnostics": {"registry": diagnostics},
            "measurement": report.get("measurement"),
        }, indent=2, default=str),
        encoding="utf-8",
    )
    (folder / "report.md").write_text(
        "\n".join([
            f"# {cell['cell_id']}",
            "",
            f"budget={cell['budget']} top_k={cell['top_k']} size_neutral={cell['size_neutral']}",
            f"2x excess={treatment_2x} vs Q10 Δpp={delta_pp} MDD2={mdd2} sizing_label={label}",
            f"rolling12_min={diagnostics['rolling12_excess_min']} rolling24_last={diagnostics['rolling24_excess']}",
            f"2024-01 stress={stress}",
            "",
        ]),
        encoding="utf-8",
    )
    register_run(folder)
    result = {
        **cell,
        "conclusion": label,
        "double_cost_excess": treatment_2x,
        "vs_q10_2x_excess_pp": delta_pp,
        "max_drawdown_2x": mdd2,
        "diagnostics": diagnostics,
        "report": str(folder / "report.md"),
    }
    (folder / "cell_result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def run(
    *,
    config: Path = DEFAULT_CONFIG,
    output: Path | None = None,
    data_root: Path = Path("data"),
    resume: bool = True,
) -> dict:
    spec = tomllib.loads(config.read_text(encoding="utf-8"))
    if spec.get("auto_trade") is not False:
        raise ValueError("q10_sizing requires auto_trade=false")
    stamp = dt.date.today().strftime("%Y%m%d")
    root = output or Path(f"artifacts/portfolio/q10_sizing_v1_{stamp}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config, root / "config.toml")
    rows = []
    for cell in cells(spec):
        rows.append(run_cell(spec=spec, cell=cell, output=root, data_root=data_root, resume=resume))
    grid = pl.DataFrame(rows)
    grid.write_parquet(root / "grid.parquet")
    lines = [
        "# Q10 sizing v1 grid",
        "",
        "|cell|budget|top_k|size_neutral|2x excess|vs Q10 pp|MDD 2x|conclusion|",
        "|---|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"|{row['cell_id']}|{row['budget']}|{row['top_k']}|{row['size_neutral']}|"
            f"{row.get('double_cost_excess')}|{row.get('vs_q10_2x_excess_pp')}|"
            f"{row.get('max_drawdown_2x')}|{row['conclusion']}|"
        )
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {"output": str(root), "cells": len(rows), "rows": rows}
    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--resume", action="store_true", default=True)
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root, resume=args.resume),
                      ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
