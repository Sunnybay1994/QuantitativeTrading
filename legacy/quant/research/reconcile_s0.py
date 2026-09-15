"""用官方事实表校验指数源，并分层解释 ETF 跟踪差异。"""

import argparse
import datetime as dt
import json
import math
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
from quant.settings import resolve_data_root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0 沪深300 ETF 独立对账")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/research/m2_baseline.toml")
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    data_root = resolve_data_root(args.data_root)
    with args.config.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    benchmark = config["benchmark"]["csi300"]
    start, end = config["data"]["start_date"], config["data"]["end_date"]

    all_bars = pl.read_parquet(
        data_root / "clean" / "bar_1d" / "date=*" / "data.parquet"
    ).filter(pl.col("source") == "baostock")
    index_bars = all_bars.filter(pl.col("symbol") == benchmark["symbol"]).sort(
        "trade_date"
    )
    etf_bars = all_bars.filter(
        (pl.col("symbol") == benchmark["tracked_etf"])
        & pl.col("trade_date").is_between(start, end, closed="both")
    ).sort("trade_date")
    research = pl.read_parquet(
        data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    ).filter(
        (pl.col("symbol") == benchmark["tracked_etf"])
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & pl.col("trade_date").is_between(start, end, closed="both")
    ).sort("trade_date")

    official_start = benchmark["official_as_of"].replace(month=1, day=1)
    previous_dates = index_bars.filter(
        pl.col("trade_date") < official_start
    ).get_column("trade_date")
    if previous_dates.is_empty():
        raise ValueError("指数行情缺少官方 YTD 所需的上一年收盘")
    base_date = cast(dt.date, previous_dates.max())
    official_rows = index_bars.filter(
        pl.col("trade_date").is_in([base_date, benchmark["official_as_of"]])
    ).sort("trade_date")
    if official_rows.height != 2:
        raise ValueError("指数行情缺少官方事实表对账日")
    source_ytd = (
        cast(float, official_rows.item(1, "close"))
        / cast(float, official_rows.item(0, "close"))
        - 1
    )
    official_error = source_ytd - benchmark["official_ytd_return"]
    official_passed = abs(official_error) <= benchmark["official_tolerance"]
    if not official_passed:
        raise ValueError(
            f"沪深300数据源与官方事实表不一致: error={official_error:.8f}"
        )

    signal_date = etf_bars.item(0, "trade_date")
    calendars = pl.concat([
        pl.read_parquet(
            data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    strategy = EqualWeightStrategy(
        candidates=(benchmark["tracked_etf"],),
        name="s0_csi300_etf_reconcile",
        version="1.0.0",
    )
    targets = schedule_next_trading_day(
        strategy.target_weights(
            signal_date,
            pl.DataFrame({"symbol": [benchmark["tracked_etf"]], "eligible": [True]}),
        ),
        calendars,
    )
    instrument = pl.read_parquet(
        data_root / "clean" / "instrument" / "market=SH" / "data.parquet"
    ).filter(pl.col("symbol") == benchmark["tracked_etf"])
    cost_config = config["costs"]["etf"]
    costs = EtfCostModel(
        cost_config["commission_rate"],
        cost_config["commission_min"],
        cost_config["slippage"],
        cost_config["effective_from"],
    )
    initial_cash = config["backtest"]["initial_cash"]
    net = simulate_etf_targets(
        bars=etf_bars,
        research_prices=research,
        scheduled_targets=targets,
        instruments=instrument,
        initial_cash=initial_cash,
        costs=costs,
        strategy=strategy.name,
    )
    gross = simulate_etf_targets(
        bars=etf_bars,
        research_prices=research,
        scheduled_targets=targets,
        instruments=instrument,
        initial_cash=initial_cash,
        costs=EtfCostModel(0.0, 0.0, 0.0, costs.effective_from),
        strategy=strategy.name,
    )
    execution_date = cast(dt.date, targets.item(0, "execution_date"))
    index_window = index_bars.filter(
        pl.col("trade_date").is_between(execution_date, end, closed="both")
    )
    etf_window = etf_bars.filter(
        pl.col("trade_date").is_between(execution_date, end, closed="both")
    )
    index_return = (
        cast(float, index_window.item(-1, "close"))
        / cast(float, index_window.item(0, "open"))
        - 1
    )
    etf_price_return = (
        cast(float, etf_window.item(-1, "close"))
        / cast(float, etf_window.item(0, "open"))
        - 1
    )
    gross_return = cast(float, gross.nav.item(-1, "unit_nav")) - 1
    net_return = cast(float, net.nav.item(-1, "unit_nav")) - 1
    decomposition = decompose_returns(
        index_return=index_return,
        etf_price_return=etf_price_return,
        etf_gross_return=gross_return,
        etf_net_return=net_return,
    )

    daily = (
        research.select(
            "trade_date", pl.col("adjusted_close").pct_change().alias("etf_return")
        )
        .join(
            index_bars.select(
                "trade_date", pl.col("close").pct_change().alias("index_return")
            ),
            on="trade_date",
        )
        .filter(pl.col("trade_date") >= execution_date)
        .drop_nulls()
    )
    daily = daily.with_columns(
        (pl.col("etf_return") - pl.col("index_return")).alias("active_return")
    )
    tracking_error = cast(
        float, daily.get_column("active_return").std()
    ) * math.sqrt(252)
    correlation = cast(
        float, daily.select(pl.corr("etf_return", "index_return")).item()
    )
    report = {
        "config": str(args.config),
        "official_validation": {
            "source": benchmark["official_source"],
            "base_date": base_date.isoformat(),
            "as_of": benchmark["official_as_of"].isoformat(),
            "official_ytd_return": benchmark["official_ytd_return"],
            "data_source_ytd_return": source_ytd,
            "absolute_error": abs(official_error),
            "tolerance": benchmark["official_tolerance"],
            "passed": official_passed,
        },
        "etf_reconciliation": {
            "execution_date": execution_date.isoformat(),
            "end": end.isoformat(),
            **decomposition,
            "daily_return_correlation": correlation,
            "annualized_tracking_error": tracking_error,
        },
        "interpretation": {
            "price_tracking_gap": "ETF 不复权价格相对指数价格的跟踪差异",
            "dividend_and_lot_contribution": "现金分红与整手现金残差对账户收益的合计影响",
            "cost_drag": "佣金和滑点造成的收益拖累",
        },
    }
    output = args.artifact_root / "research" / "m2" / "s0_reconciliation"
    output.mkdir(parents=True, exist_ok=True)
    daily.write_parquet(output / "daily_returns.parquet")
    net.nav.write_parquet(output / "net_nav.parquet")
    gross.nav.write_parquet(output / "gross_nav.parquet")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0


def decompose_returns(
    *,
    index_return: float,
    etf_price_return: float,
    etf_gross_return: float,
    etf_net_return: float,
) -> dict[str, float]:
    price_tracking_gap = etf_price_return - index_return
    dividend_and_lot = etf_gross_return - etf_price_return
    cost_drag = etf_net_return - etf_gross_return
    return {
        "index_price_return": index_return,
        "etf_price_return": etf_price_return,
        "etf_gross_account_return": etf_gross_return,
        "etf_net_account_return": etf_net_return,
        "price_tracking_gap": price_tracking_gap,
        "dividend_and_lot_contribution": dividend_and_lot,
        "cost_drag": cost_drag,
        "net_gap_to_index": etf_net_return - index_return,
        "decomposition_residual": (
            etf_net_return
            - index_return
            - price_tracking_gap
            - dividend_and_lot
            - cost_drag
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
