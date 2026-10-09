"""B2: Q10 z + admitted-factor z with sign(48m incremental IC)/N weights (no fit)."""
from __future__ import annotations

import datetime as dt
import json
import math
import shutil
import tomllib
from pathlib import Path

import polars as pl

from quant.factors.library import load_library
from quant.research.nightly_steps import incremental_statistics


DEFAULT_CONFIG = Path("configs/models/q10_plus_admitted_v1.toml")


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    if spec.get("auto_trade") is not False:
        raise ValueError("q10_plus_admitted requires auto_trade=false")
    return spec


def admitted_factor_ids(library: Path) -> list[str]:
    """Formal N4 auto-library entries (ngp_*); sue_family survivors appear after N4 writes auto/."""
    return sorted(d.id for d in load_library(library) if d.id.startswith(("ngp_", "sue_", "rsue")))


def _cs_z(frame: pl.DataFrame, column: str, alias: str) -> pl.DataFrame:
    return frame.with_columns(
        ((pl.col(column) - pl.col(column).mean().over("trade_date"))
         / pl.col(column).std().over("trade_date").clip(lower_bound=1e-12)).alias(alias)
    )


def load_labels(statistics: Path) -> pl.DataFrame:
    frames = [
        pl.read_parquet(path).select("symbol", "trade_date", pl.col("label_rebalance").alias("label"))
        for path in sorted((statistics / "inputs").glob("*/monthly_labels.parquet"))
    ]
    if not frames:
        raise ValueError(f"No monthly labels under {statistics}/inputs")
    return pl.concat(frames).unique(subset=["symbol", "trade_date"], keep="last")


def load_factor_panel(statistics: Path, factors: list[str], *, variant: str) -> pl.DataFrame:
    keys = ["symbol", "trade_date"]
    panel = None
    for factor in factors:
        path = statistics / "factors" / factor / "monthly_scores.parquet"
        if not path.is_file():
            raise ValueError(f"Missing admitted factor scores: {path}")
        frame = pl.read_parquet(path).select(*keys, pl.col(variant).alias(factor))
        panel = frame if panel is None else panel.join(frame, on=keys, how="inner", validate="1:1")
    return panel


def trailing_incremental_weights(
    *,
    q10: pl.DataFrame,
    factors: pl.DataFrame,
    labels: pl.DataFrame,
    factor_ids: list[str],
    as_of: dt.date,
    lookback_months: int,
) -> dict[str, float]:
    """One frozen weight vector: sign(mean 48m incremental IC vs Q10) / N."""
    if not factor_ids:
        return {}
    panel = (
        q10.join(factors, on=["symbol", "trade_date"], how="inner", validate="1:1")
        .join(labels, on=["symbol", "trade_date"], how="inner", validate="1:1")
        .filter(pl.col("trade_date") <= as_of)
        .sort("trade_date", "symbol")
    )
    dates = sorted(panel["trade_date"].unique().to_list())
    if not dates:
        return {f: 0.0 for f in factor_ids}
    # Keep last lookback_months month-ends with known labels.
    window = dates[-lookback_months:] if len(dates) >= lookback_months else dates
    panel = panel.filter(pl.col("trade_date").is_in(window))
    n = len(factor_ids)
    weights: dict[str, float] = {}
    for factor in factor_ids:
        stats = incremental_statistics(panel, factor, ["q10_score"], 1)
        mean_ic = stats.get("mean_ic")
        if mean_ic is None or not math.isfinite(mean_ic) or mean_ic == 0:
            weights[factor] = 0.0
        else:
            weights[factor] = (1.0 if mean_ic > 0 else -1.0) / n
    return weights


def build_combined_scores(
    *,
    q10_predictions: Path,
    q10_score_column: str,
    statistics: Path,
    factor_ids: list[str],
    weights: dict[str, float],
    score_variant: str,
) -> pl.DataFrame:
    pred = pl.read_parquet(q10_predictions / "monthly_predictions.parquet")
    if q10_score_column not in pred.columns:
        raise ValueError(f"Q10 predictions lack {q10_score_column}")
    base = pred.select("symbol", "trade_date", pl.col(q10_score_column).alias("q10_raw"))
    base = _cs_z(base, "q10_raw", "q10_z").select("symbol", "trade_date", "q10_z")
    if not factor_ids:
        return base.with_columns(
            pl.col("q10_z").alias("q10_plus_admitted"),
            pl.col("q10_z").alias("q10_control"),
        )
    factors = load_factor_panel(statistics, factor_ids, variant=score_variant)
    for factor in factor_ids:
        factors = _cs_z(factors, factor, f"{factor}_z")
    joined = base.join(factors, on=["symbol", "trade_date"], how="inner", validate="1:1")
    combo = pl.col("q10_z")
    for factor in factor_ids:
        combo = combo + pl.col(f"{factor}_z") * float(weights.get(factor, 0.0))
    return joined.select(
        "symbol",
        "trade_date",
        combo.alias("q10_plus_admitted"),
        pl.col("q10_z").alias("q10_control"),
    )


def maybe_write_paper_draft(spec: dict, assessment: dict, *, period: str) -> str | None:
    """Draft paper config only; never opens an account or sets auto_trade."""
    delta = assessment.get("vs_q10_2x_excess_pp")
    promote = assessment.get("promote_draft")
    if not promote:
        return None
    folder = Path(spec["paper_draft_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    path = folder / f"q10_plus_admitted_{period.replace('-', '')}_{stamp}_DRAFT.toml"
    path.write_text(
        "\n".join([
            f'id = "q10-plus-admitted-{period}-draft"',
            f"registered_on = {dt.date.today().isoformat()}",
            "auto_trade = false",
            'status = "DRAFT_NOT_OPENED"',
            f'period = "{period}"',
            f"vs_q10_2x_excess_pp = {delta}",
            'source = "artifacts/research/nightly/monthly/' + period + '/q10_plus_admitted"',
            "note = \"Machine draft only; requires human confirmation before any paper account.\"",
            "",
        ]),
        encoding="utf-8",
    )
    return str(path)


def run_for_month(
    *,
    month_output: Path,
    data_root: Path,
    config: Path = DEFAULT_CONFIG,
    resume: bool = False,
) -> dict:
    """Build scores, budgeted Top50 three-cost replay, compare vs Q10 same window."""
    from quant.backtest.share_exchanges import validate_exchanges
    from quant.data.equal_weight_index import load_return_benchmarks
    from quant.data.factor_panels import available_sessions
    from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
    from quant.reporting.experiment_registry import register_run
    from quant.reporting.multifactor_assessment import assess_model
    from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
    from quant.research.factor_battery_costs import run_cost_plans
    from quant.research.run_multifactor_replay import model_target_plans

    spec = load_config(config)
    folder = month_output / "q10_plus_admitted"
    if (folder / "monthly_result.json").is_file() and not resume:
        return json.loads((folder / "monthly_result.json").read_text(encoding="utf-8"))

    statistics = month_output / "evaluation" / "statistics"
    if not statistics.is_dir():
        raise ValueError(f"Month lacks evaluation/statistics: {month_output}")
    as_of = tomllib.loads((statistics / "battery.toml").read_text(encoding="utf-8"))["run"]["as_of"]
    if isinstance(as_of, str):
        as_of = dt.date.fromisoformat(as_of)

    library = Path(spec["admitted_library"])
    factor_ids = [
        i for i in admitted_factor_ids(library)
        if (statistics / "factors" / i / "monthly_scores.parquet").is_file()
    ]
    q10_path = Path(spec["q10_predictions"])
    q10_raw = pl.read_parquet(q10_path / "monthly_predictions.parquet").select(
        "symbol", "trade_date", pl.col(spec["q10_score_column"]).alias("q10_score")
    )
    labels = load_labels(statistics)
    factors = load_factor_panel(statistics, factor_ids, variant=spec["score_variant"]) if factor_ids else None
    weights = trailing_incremental_weights(
        q10=q10_raw,
        factors=factors if factors is not None else pl.DataFrame({"symbol": [], "trade_date": []}),
        labels=labels,
        factor_ids=factor_ids,
        as_of=as_of,
        lookback_months=int(spec["lookback_months"]),
    ) if factor_ids else {}

    scores = build_combined_scores(
        q10_predictions=q10_path,
        q10_score_column=spec["q10_score_column"],
        statistics=statistics,
        factor_ids=factor_ids,
        weights=weights,
        score_variant=spec["score_variant"],
    )

    if folder.exists() and not resume:
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_bytes(config.read_bytes())
    scores.write_parquet(folder / "monthly_predictions.parquet")
    (folder / "weights.json").write_text(
        json.dumps({"as_of": str(as_of), "factors": factor_ids, "weights": weights}, indent=2),
        encoding="utf-8",
    )

    # Reuse Q10 prediction model/battery shells so walk_forward and portfolio match.
    for name in ("model.toml", "battery.toml"):
        shutil.copyfile(q10_path / name, folder / name)
    model = tomllib.loads((folder / "model.toml").read_text(encoding="utf-8"))
    model.setdefault("models", {})["methods"] = ["q10_plus_admitted"]
    model["portfolio"]["primary_top_k"] = int(spec["top_k"])
    model["models"]["minimum_signal_stocks"] = int(spec["minimum_symbols"])
    end = min(model["walk_forward"]["test_end"], scores["trade_date"].max())
    model["walk_forward"]["test_end"] = end
    (folder / "model_runtime.json").write_text(json.dumps(model, indent=2, default=str), encoding="utf-8")

    settings = tomllib.loads((folder / "battery.toml").read_text(encoding="utf-8"))
    settings["share_exchanges"] = validate_exchanges(
        tomllib.loads(Path("configs/data/share_exchanges_20260912.toml").read_text(encoding="utf-8"))[
            "share_exchanges"
        ]
    )
    sessions = available_sessions(data_root, end + dt.timedelta(days=40))
    name, targets = model_target_plans(scores, model=model, sessions=sessions)[
        f"q10_plus_admitted_top{spec['top_k']}"
    ]
    benchmarks = Path(spec["benchmarks"])
    snapshot = json.loads((benchmarks / "summary.json").read_text(encoding="utf-8"))["execution_snapshot"]
    shutil.copyfile(Path(spec["return_benchmark_config"]), folder / "return_benchmarks.toml")

    run_cost_plans(
        settings=settings,
        plans={"budgeted": (name, targets)},
        sessions=sessions,
        output=folder,
        data_root=data_root,
        execution_snapshot=snapshot,
        factor=f"q10-plus-admitted-{month_output.name}",
        start=model["walk_forward"]["test_start"],
        turnover_budgets={"budgeted": float(spec["monthly_one_way_budget"])},
        resume=resume and (folder / "replay_config.json").exists(),
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
            row["legacy_252_turnover"] = row["annualized_one_way_turnover"]
            row["annualized_one_way_turnover"] = turnover["median"]
            row["maximum_calendar_turnover"] = turnover["maximum"]
    nav, _ = load_cost_history(folder, "budgeted", 1.0, end)
    assessment = assess_model(
        nav=nav, one=rows[1.0], two=rows[2.0], benchmarks=baselines, model=model, windows=windows
    )
    excess = [
        r["net_cagr_excess"]
        for r in report["benchmark_comparisons"]
        if r["variant"] == "budgeted" and r["cost_multiplier"] == 2.0 and r["net_cagr_excess"] is not None
    ]
    if excess:
        assessment["double_cost_excess"] = min(excess)
        assessment["checks"]["turnover"] = turnover_passes(
            rows[1.0]["annualized_one_way_turnover"], min(excess)
        )
    assessment["conclusion"] = "PAPER_CANDIDATE" if all(assessment["checks"].values()) else "REJECTED"

    q10_excess = _q10_2x_excess(Path(spec["q10_control_replay"]), end=end)
    treatment_excess = assessment.get("double_cost_excess")
    delta_pp = None
    if treatment_excess is not None and q10_excess is not None:
        delta_pp = (treatment_excess - q10_excess) * 100
    assessment["q10_2x_excess"] = q10_excess
    assessment["vs_q10_2x_excess_pp"] = delta_pp
    assessment["promote_draft"] = bool(
        assessment["conclusion"] == "PAPER_CANDIDATE"
        and delta_pp is not None
        and delta_pp >= float(spec["promote_excess_pp"])
    )
    draft = maybe_write_paper_draft(spec, assessment, period=month_output.name)

    (folder / "assessment.json").write_text(
        json.dumps({
            "rows": report["rows"],
            "assessments": {"budgeted": assessment},
            "benchmark_comparisons": report["benchmark_comparisons"],
            "measurement": report.get("measurement"),
        }, indent=2, default=str),
        encoding="utf-8",
    )
    lines = [
        f"# {month_output.name} q10_plus_admitted",
        "",
        f"准入因子：{', '.join(factor_ids) or '（无）'}；权重：{weights}",
        f"vs Q10 同窗 2× 超额差：{delta_pp if delta_pp is not None else 'NA'} pp",
        f"结论：{assessment['conclusion']}；草稿：{draft or '无'}",
        "",
        "|成本|持股期年化|Sharpe|最大回撤|日历换手中位数|",
        "|---:|---:|---:|---:|---:|",
    ]
    for cost in (0.5, 1.0, 2.0):
        row = rows[cost]
        lines.append(
            f"|{cost}|{_fmt(row.get('cagr'))}|{_fmt(row.get('sharpe'), '.3f')}|"
            f"{_fmt(row.get('max_drawdown'))}|{_fmt(row.get('annualized_one_way_turnover'), '.3f')}|"
        )
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    register_run(folder)
    result = {
        "report": str(folder / "report.md"),
        "conclusions": {"budgeted": assessment["conclusion"]},
        "vs_q10_2x_excess_pp": delta_pp,
        "weights": weights,
        "factors": factor_ids,
        "paper_draft": draft,
        "cost_multipliers": [0.5, 1.0, 2.0],
    }
    (folder / "monthly_result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def _fmt(value, pattern=".2%") -> str:
    return format(value, pattern) if value is not None else "NA"


def _q10_2x_excess(control_replay: Path, *, end: dt.date) -> float | None:
    """Read frozen Q10 budgeted 2× excess (min across return benchmarks)."""
    _ = end
    path = control_replay / "assessment.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    bud = payload.get("assessments", {}).get("budgeted") or {}
    if bud.get("double_cost_excess") is not None:
        return float(bud["double_cost_excess"])
    excess = [
        r["net_cagr_excess"]
        for r in payload.get("benchmark_comparisons", [])
        if r.get("variant") == "budgeted"
        and r.get("cost_multiplier") == 2.0
        and r.get("net_cagr_excess") is not None
    ]
    return float(min(excess)) if excess else None


def attach_to_month_summary(month_output: Path, result: dict) -> None:
    summary_path = month_output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    methods = summary.setdefault("methods", {})
    methods["q10_plus_admitted"] = result
    summary_path.write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    report = month_output / "report.md"
    if report.is_file():
        text = report.read_text(encoding="utf-8")
        if "q10_plus_admitted" not in text:
            line = (
                f"|q10_plus_admitted|{result['conclusions']['budgeted']}|n/a|"
                f"[q10_plus_admitted](q10_plus_admitted/report.md)|"
            )
            report.write_text(text.rstrip() + "\n" + line + "\n", encoding="utf-8")
