"""Attach A2 rolling/concentration diagnostics to a frozen Q10 assessment copy."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.research.factor_battery_cost_report import load_cost_history
from quant.research.rolling_excess_diagnostics import rolling_excess_diagnostics
from quant.reporting.experiment_registry import register_run


def _load_nav(source: Path, variant: str, cost: float, end: dt.date) -> pl.DataFrame:
    nav, _trades = load_cost_history(source, variant, cost, end)
    return nav


def run(config: Path, output: Path, data_root: Path = Path("data")) -> dict:
    spec = tomllib.loads(config.read_text(encoding="utf-8"))["research"]
    fills = Path(spec["source"])
    assessment_source = Path(spec.get("assessment_source", fills))
    if output.exists():
        raise ValueError("Use a new output directory")
    old_bytes = (assessment_source / "assessment.json").read_bytes()
    result = copy.deepcopy(json.loads(old_bytes.decode("utf-8")))
    end = spec["report_end"] if isinstance(spec.get("report_end"), dt.date) else dt.date.fromisoformat(
        str(spec.get("report_end", result["rows"][0]["report_end"]))
    )
    bench_name = spec.get("benchmark", "all_market_equal_weight")
    bench_cfg = Path(spec["benchmark_config"])
    start = spec["benchmark_start"] if isinstance(spec.get("benchmark_start"), dt.date) else dt.date.fromisoformat(
        str(spec.get("benchmark_start", "2018-01-01"))
    )
    benchmarks = load_return_benchmarks(
        config=bench_cfg, data_root=data_root, start=start, end=end, names=[bench_name]
    )
    benchmark = benchmarks[bench_name]

    diagnostics: dict = {}
    for cost in (1.0, 2.0):
        nav = _load_nav(fills, spec.get("variant", "budgeted"), cost, end)
        diagnostics[f"cost_{cost:g}x"] = rolling_excess_diagnostics(nav, benchmark)

    result["diagnostics"] = {
        "advisory": True,
        "benchmark": bench_name,
        "costs": diagnostics,
        "registry": diagnostics["cost_1x"]["registry"],
    }
    result["source"] = str(assessment_source)
    result["fills_source"] = str(fills)
    # Preserve §1.2 conclusion; diagnostics are advisory only.
    output.mkdir(parents=True)
    (output / "config.toml").write_bytes(config.read_bytes())
    (output / "assessment.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    r12 = diagnostics["cost_1x"]["rolling12_excess"]
    lines = [
        "# Q10 滚动与集中度（advisory）",
        "",
        f"源评估：`{assessment_source}`（字节未改）。基准：`{bench_name}`。",
        "",
        "## 滚动超额（链接收益）",
        "",
        f"|窗口|窗口数|最小|最小月|为正比例|中位|末值|",
        f"|---|---:|---:|---|---:|---:|---:|",
    ]
    def pct(value: float | None, digits: str = ".2%") -> str:
        return "" if value is None else format(value, digits)

    for key, label in (
        ("rolling12_excess", "12月"),
        ("rolling24_excess", "24月"),
        ("rolling36_excess", "36月"),
    ):
        block = diagnostics["cost_1x"][key]
        lines.append(
            f"|{label}|{block['n_windows']}|{pct(block['min'])}|{block['min_month']}|"
            f"{pct(block['positive_fraction'], '.0%')}|{pct(block['median'])}|{pct(block['last'])}|"
        )
    lines += [
        "",
        "验收锚点：2026-06 滚动 12 月 1× 超额应为 −8.5pp±0.1。",
        f"实测 min={r12['min']:.4%} @ {r12['min_month']}。",
        "",
        "## 月胜率与最佳月占比（1×）",
        "",
        "|年|月胜率|年超额和|去最佳单月后|最佳月占比|",
        "|---|---:|---:|---:|---:|",
    ]
    hit = diagnostics["cost_1x"]["monthly_hit_rate"]
    share = diagnostics["cost_1x"]["best_month_share"]
    for year in sorted(hit):
        s = share[year]
        lines.append(
            f"|{year}|{hit[year]:.0%}|{s['year_excess_sum']:.2%}|"
            f"{s['excess_sum_without_best']:.2%}|{pct(s['best_month_share'], '.0%')}|"
        )
    split = diagnostics["cost_1x"]["up_down_split"]
    lines += [
        "",
        "## 上涨/下跌月拆分（advisory）",
        "",
        f"基准上涨月均超额 {split['mean_excess_when_benchmark_up']:.2%}（n={split['up_months']}）；"
        f"下跌月均超额 {split['mean_excess_when_benchmark_down']:.2%}（n={split['down_months']}）。",
        "",
        "不改 §1.2 判定；旧目录 assessment.json 字节不变。",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if (assessment_source / "assessment.json").read_bytes() != old_bytes:
        raise RuntimeError("Source assessment mutated")

    register_run(output)
    return {
        "output": str(output),
        "rolling12_min": r12["min"],
        "rolling12_min_month": r12["min_month"],
        "conclusion": result.get("conclusion")
        or result.get("assessments", {}).get("budgeted", {}).get("conclusion"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output, args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
