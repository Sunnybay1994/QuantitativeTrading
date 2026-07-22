"""运行 ETF 买入持有与等权月调仓 S0 基线。"""

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any, Sequence, cast

import polars as pl

from quant.backtest import (
    EtfCostModel,
    schedule_next_trading_day,
    simulate_etf_targets,
)
from quant.strategies import EqualWeightStrategy


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 S0 ETF 基线")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/research/m2_baseline.toml")
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    with args.config.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    start, end = config["data"]["start_date"], config["data"]["end_date"]
    candidates = _candidates(config)

    bars = pl.read_parquet(
        args.data_root / "clean" / "bar_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & pl.col("trade_date").is_between(start, end, closed="both")
        & (
            ((pl.col("trade_date") < dt.date(2026, 1, 1)) & (pl.col("source") == "akshare"))
            | ((pl.col("trade_date") >= dt.date(2026, 1, 1)) & (pl.col("source") == "baostock"))
        )
    )
    research_prices = pl.read_parquet(
        args.data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & pl.col("trade_date").is_between(start, end, closed="both")
    )
    _require_complete_candidates(bars, candidates, "不复权行情")
    _require_complete_candidates(research_prices, candidates, "总回报研究价格")

    calendars = pl.concat([
        pl.read_parquet(
            args.data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    instruments = pl.concat([
        pl.read_parquet(
            args.data_root / "clean" / "instrument" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ]).filter(pl.col("symbol").is_in(candidates))

    dates = sorted(set(bars.get_column("trade_date").to_list()))
    first_signal = dates[0]
    month_ends = (
        pl.DataFrame({"date": dates})
        .with_columns(
            pl.col("date").dt.year().alias("year"),
            pl.col("date").dt.month().alias("month"),
        )
        .group_by("year", "month")
        .agg(pl.col("date").max())
        .sort("date")
        .get_column("date")
        .to_list()
    )
    availability = pl.DataFrame({"symbol": candidates, "eligible": [True] * len(candidates)})
    buy_hold = EqualWeightStrategy(
        candidates=tuple(candidates), name="s0_buy_hold", version="1.0.0"
    )
    monthly = EqualWeightStrategy(
        candidates=tuple(candidates), name="s0_equal_monthly", version="1.0.0"
    )
    buy_hold_targets = schedule_next_trading_day(
        buy_hold.target_weights(first_signal, availability), calendars
    )
    monthly_signals = sorted(set([first_signal, *month_ends]))
    monthly_targets = schedule_next_trading_day(
        pl.concat(
            [monthly.target_weights(date, availability) for date in monthly_signals]
        ),
        calendars,
    )

    cost_config = config["costs"]["etf"]
    costs = EtfCostModel(
        commission_rate=cost_config["commission_rate"],
        commission_min=cost_config["commission_min"],
        slippage=cost_config["slippage"],
        effective_from=cost_config["effective_from"],
    )
    initial_cash = config["backtest"]["initial_cash"]
    results = [
        simulate_etf_targets(
            bars=bars,
            research_prices=research_prices,
            scheduled_targets=targets,
            instruments=instruments,
            initial_cash=initial_cash,
            costs=costs,
            strategy=name,
        )
        for name, targets in (
            ("s0_buy_hold", buy_hold_targets),
            ("s0_equal_monthly", monthly_targets),
        )
    ]
    zero_costs = EtfCostModel(0.0, 0.0, 0.0, costs.effective_from)
    gross_results = [
        simulate_etf_targets(
            bars=bars,
            research_prices=research_prices,
            scheduled_targets=targets,
            instruments=instruments,
            initial_cash=initial_cash,
            costs=zero_costs,
            strategy=name,
        )
        for name, targets in (
            ("s0_buy_hold", buy_hold_targets),
            ("s0_equal_monthly", monthly_targets),
        )
    ]
    nav = pl.concat([result.nav for result in results])
    gross_nav = pl.concat([result.nav for result in gross_results])
    trades = pl.concat([result.trades for result in results])
    report = {
        "config": str(args.config),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "candidate_symbols": len(candidates),
        "initial_cash": initial_cash,
        "strategies": [
            _metrics(result.nav, result.trades, gross.nav, name)
            for name, result, gross in zip(
                ("s0_buy_hold", "s0_equal_monthly"),
                results,
                gross_results,
                strict=True,
            )
        ],
        "known_limits": [
            "尚未实现 ETF 涨跌停拒单",
            f"当前同口径样本为 {len(dates)} 个交易日",
            "成本参数是研究假设，尚未用券商账单校准",
        ],
    }
    output = args.artifact_root / "research" / "m2" / "s0"
    output.mkdir(parents=True, exist_ok=True)
    nav.write_parquet(output / "nav.parquet")
    gross_nav.write_parquet(output / "gross_nav.parquet")
    trades.write_parquet(output / "trades.parquet")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0


def _candidates(config: dict[str, Any]) -> list[str]:
    universe = config["universe"]
    return [
        symbol
        for group in ("wide", "industry", "hong_kong_theme")
        for symbol in universe[group]
    ]


def _require_complete_candidates(
    frame: pl.DataFrame, candidates: list[str], label: str
) -> None:
    missing = sorted(set(candidates) - set(frame.get_column("symbol").unique().to_list()))
    if missing:
        raise ValueError(f"{label}缺少证券: " + ", ".join(missing))


def _metrics(
    nav: pl.DataFrame,
    trades: pl.DataFrame,
    gross_nav: pl.DataFrame,
    strategy: str,
) -> dict[str, object]:
    unit_nav = nav.get_column("unit_nav")
    running_max = unit_nav.cum_max()
    max_drawdown = cast(float, (unit_nav / running_max - 1).min())
    total_return = float(unit_nav[-1] - 1)
    gross_total_return = float(gross_nav.get_column("unit_nav")[-1] - 1)
    return {
        "strategy": strategy,
        "total_return": total_return,
        "gross_total_return": gross_total_return,
        "cost_drag": total_return - gross_total_return,
        "max_drawdown": max_drawdown,
        "ending_equity": cast(float, nav.item(-1, "equity")),
        "cumulative_fees": cast(float, nav.item(-1, "cumulative_fees")),
        "cumulative_slippage": float(trades.get_column("slippage_cost").sum()),
        "trades": trades.height,
        "turnover_notional": float(trades.get_column("notional").sum()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
