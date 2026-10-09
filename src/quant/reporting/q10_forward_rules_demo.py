"""Demo replay of A3 forward rules on 2025-08→2026-06 backtest path."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.reporting.q10_forward_rules import demo_replay_attention, write_monthly_package
from quant.research.factor_battery_cost_report import load_cost_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("configs/paper/q10_sue_v2_forward_rules_20261010.toml"),
    )
    parser.add_argument(
        "--backtest",
        type=Path,
        default=Path("artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01"),
    )
    parser.add_argument(
        "--benchmark-config",
        type=Path,
        default=Path("configs/data/p8_return_benchmarks_20260912.toml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/paper/q10_sue_v2/monthly/demo_2025_08_2026_06"),
    )
    args = parser.parse_args()
    end = dt.date(2026, 8, 31)
    nav1, _ = load_cost_history(args.backtest, "budgeted", 1.0, end)
    nav2, _ = load_cost_history(args.backtest, "budgeted", 2.0, end)
    months = [
        "2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
    ]
    result = demo_replay_attention(
        rules_path=args.rules,
        nav_1x=nav1,
        nav_2x=nav2,
        benchmark_config=args.benchmark_config,
        data_root=Path("data"),
        months=months,
    )
    out_json = args.output if args.output.suffix == ".json" else Path(str(args.output) + ".json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Also emit a sample monthly package for 2026-06 under monthly/
    june = next(r for r in result["months"] if r["as_of_month"] == "2026-06")
    write_monthly_package(
        stem=Path("artifacts/paper/q10_sue_v2/monthly/2026-06_demo"),
        evaluation=june,
        markdown_extra=["（演示回放，非真实样本外月报；真实 OOS 自 2026-10-08 起。）"],
    )
    print(json.dumps(result["assertion"], ensure_ascii=False, indent=2))
    if not result["assertion"]["2026-06_status_is_attention"] or not result["assertion"]["2026-06_demote_false"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
