"""由版本化配置和 clean 研究价格生成 ETF 趋势目标权重。"""

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from quant.backtest import schedule_next_trading_day
from quant.factors import compute_trend_factors_from_prices
from quant.strategies import EtfTrendStrategy
from quant.settings import resolve_data_root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 ETF 趋势信号")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/research/m2_baseline.toml")
    )
    parser.add_argument("--as-of", type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    data_root = resolve_data_root(args.data_root)
    with args.config.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    as_of = args.as_of or config["data"]["end_date"]
    candidates = _candidates(config)
    strategy_config = config["strategy"]["etf_trend"]

    price_glob = data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    if not list((data_root / "clean" / "research_price_1d").glob("date=*")):
        raise FileNotFoundError(price_glob)
    prices = pl.read_parquet(price_glob).filter(pl.col("symbol").is_in(candidates))
    present = set(prices.get_column("symbol").unique().to_list())
    missing = sorted(set(candidates) - present)
    if missing:
        raise ValueError("研究价格缺少候选证券: " + ", ".join(missing))
    factors = compute_trend_factors_from_prices(
        prices,
        as_of=as_of,
        source=None,
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=strategy_config["regression_window"],
        factor_version=strategy_config["factor_version"],
    )
    strategy = EtfTrendStrategy(
        candidates=tuple(candidates),
        top_k=strategy_config["top_k"],
        cash_buffer=strategy_config["cash_buffer"],
        factor_version=strategy_config["factor_version"],
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=strategy_config["regression_window"],
    )
    targets = strategy.target_weights(as_of, factors)
    calendars = pl.concat([
        pl.read_parquet(
            data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    scheduled = schedule_next_trading_day(targets, calendars)

    output = args.artifact_root / "research" / "m2" / f"as_of={as_of.isoformat()}"
    output.mkdir(parents=True, exist_ok=True)
    factors.write_parquet(output / "factors.parquet")
    targets.write_parquet(output / "target_weights.parquet")
    scheduled.write_parquet(output / "scheduled_targets.parquet")
    latest_methods = (
        prices.filter(pl.col("trade_date") <= as_of)
        .sort(["symbol", "trade_date"])
        .group_by("symbol", maintain_order=True)
        .tail(1)
    )
    methods = latest_methods.group_by("adjustment_method").agg(
        pl.col("symbol").n_unique().alias("symbols")
    )
    report = {
        "config": str(args.config),
        "as_of": as_of.isoformat(),
        "candidate_symbols": len(candidates),
        "factor_rows": factors.height,
        "selected_symbols": targets.get_column("symbol").to_list(),
        "invested_weight": float(targets.get_column("weight").sum()),
        "execution_dates": sorted(
            date.isoformat()
            for date in scheduled.get_column("execution_date").unique().to_list()
        ),
        "price_methods": methods.to_dicts(),
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0


def _candidates(config: dict[str, Any]) -> list[str]:
    universe = config["universe"]
    candidates = [
        symbol
        for group in ("wide", "industry", "hong_kong_theme")
        for symbol in universe[group]
    ]
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("ETF 候选池必须非空且不能重复")
    return candidates


if __name__ == "__main__":
    raise SystemExit(main())
