"""从标准回测净值 Parquet 生成 QuantStats HTML 报告。"""

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd  # type: ignore[import-untyped]
import polars as pl


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 QuantStats 回测报告")
    parser.add_argument("--nav-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    args = parser.parse_args(argv)
    if not args.nav_path.exists():
        raise FileNotFoundError(args.nav_path)
    nav = pl.read_parquet(args.nav_path)
    if "cost_multiplier" in nav.columns:
        nav = nav.filter(pl.col("cost_multiplier") == args.cost_multiplier)
    series_by_strategy = returns_by_strategy(nav)
    if not series_by_strategy:
        raise ValueError("没有可生成报告的净值序列")
    try:
        quantstats: Any = importlib.import_module("quantstats")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'QuantStats 未安装；请在 WSL base 执行 pip install -e ".[research]"'
        ) from exc
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for strategy, returns in series_by_strategy.items():
        output = args.output_dir / f"{strategy}.html"
        quantstats.reports.html(
            returns,
            benchmark=None,
            title=f"{strategy} — QuantStats",
            output=str(output),
            periods_per_year=252,
        )
        outputs.append(str(output))
    print(json.dumps({"reports": outputs}, ensure_ascii=False))
    return 0


def returns_by_strategy(nav: pl.DataFrame) -> dict[str, pd.Series]:
    required = {"strategy", "date", "unit_nav"}
    missing = sorted(required - set(nav.columns))
    if missing:
        raise ValueError(f"净值文件缺少字段: {', '.join(missing)}")
    result: dict[str, pd.Series] = {}
    for (strategy,), frame in nav.partition_by(
        "strategy", as_dict=True, maintain_order=True
    ).items():
        ordered = frame.sort("date").select("date", "unit_nav").to_pandas()
        index = pd.DatetimeIndex(ordered.pop("date"))
        returns = pd.Series(ordered["unit_nav"].to_numpy(), index=index).pct_change().dropna()
        if not returns.empty:
            result[strategy] = returns
    return result


if __name__ == "__main__":
    raise SystemExit(main())
