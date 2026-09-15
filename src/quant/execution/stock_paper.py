"""B32 fixed stock forward observations, sharing the real daily account simulator."""

import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.daily_account import advance
from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from quant.data.refresh import SHANGHAI, latest_session
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.stock_paper_inputs import (
    StockPaperInputs,
    read_stock_paper_calendar,
    read_stock_paper_freeze,
    read_stock_paper_inputs,
)
from quant.research.run_classic_factors import select_frozen_liquid_universe
from quant.strategies.stock_paper import effective_stock_factors, stock_targets

ORDER_SCHEMA = {
    "as_of": pl.String,
    "execution_date": pl.String,
    "symbol": pl.String,
    "side": pl.String,
    "quantity": pl.Int64,
    "board_lot": pl.Int64,
    "reference_price": pl.Float64,
    "estimated_fill_price": pl.Float64,
    "estimated_notional": pl.Float64,
    "estimated_fee": pl.Float64,
    "cash_after": pl.Float64,
}
TARGET_SCHEMA = {
    "as_of": pl.String,
    "execution_date": pl.String,
    "strategy": pl.String,
    "strategy_version": pl.String,
    "symbol": pl.String,
    "weight": pl.Float64,
}


def _controls(
    output: Path, paper: dict[str, Any], halt: bool | None, sell_only: bool | None
) -> dict[str, bool]:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "controls.json"
    controls = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"halt": paper["halt"], "sell_only": paper["sell_only"]}
    )
    if set(controls) != {"halt", "sell_only"} or any(
        type(v) is not bool for v in controls.values()
    ):
        raise ValueError("Invalid global stock controls")
    if halt is not None:
        controls["halt"] = halt
    if sell_only is not None:
        controls["sell_only"] = sell_only
    path.write_text(json.dumps(controls), encoding="utf-8")
    return controls


def account_config(
    config: dict[str, Any], account: dict[str, Any], controls: dict[str, bool]
) -> dict[str, Any]:
    return {
        "paper": {
            **config["paper"],
            "name": account["name"],
            "enabled": not controls["halt"],
            "sell_only": controls["sell_only"],
        },
        "costs": config["costs"],
    }


def reference_orders(
    state: dict[str, Any],
    inputs: StockPaperInputs,
    config: dict[str, Any],
) -> pl.DataFrame:
    """Sizing-only close-price scenario; never persist its hypothetical NAV or fills."""
    if config["paper"]["auto_trade"] is not False:
        raise ValueError("Stock paper requires auto_trade=false")
    if not state["pending"] or not config["paper"].get("enabled", True):
        return pl.DataFrame(schema=ORDER_SCHEMA)
    as_of = dt.date.fromisoformat(state["date"])
    execution_date = dt.date.fromisoformat(state["pending"][0]["execution_date"])
    if execution_date <= as_of:
        raise ValueError("Reference order date must be after the signal close")
    targets = pl.DataFrame(state["pending"]).with_columns(
        pl.col("as_of").str.to_date(), pl.col("execution_date").str.to_date()
    )
    symbols = set(targets["symbol"]) | set(state["holdings"])
    current = inputs.bars.filter(pl.col("trade_date") == as_of)
    marks = dict(current.select("symbol", "close").iter_rows())
    for symbol, holding in state["holdings"].items():
        marks.setdefault(symbol, holding["mark_price"])
    if symbols - marks.keys():
        raise ValueError("Missing signal-date reference price")
    equity = state["cash"] + sum(h["quantity"] * marks[s] for s, h in state["holdings"].items())
    if config["paper"].get("sell_only", False):
        targets = targets.with_columns(
            pl.Series(
                "weight",
                [
                    min(
                        row["weight"],
                        state["holdings"].get(row["symbol"], {}).get("quantity", 0)
                        * marks[row["symbol"]]
                        / equity,
                    )
                    for row in targets.iter_rows(named=True)
                ],
            )
        )
    # This isolated scenario only sizes reference orders. Actual execution below
    # uses the observed next-session OHLC, official limits and suspensions.
    scenario_bars = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": execution_date,
                "open": marks[symbol],
                "high": marks[symbol],
                "low": marks[symbol],
                "close": marks[symbol],
                "volume": 1.0,
                "amount": marks[symbol],
                "adj_factor": 1.0,
                "source": "close_reference_estimate",
            }
            for symbol in sorted(symbols)
        ]
    )
    positions = (
        pl.DataFrame(
            [
                {
                    "symbol": symbol,
                    "quantity": holding["quantity"],
                    "settled_quantity": holding["quantity"]
                    - sum(
                        item["quantity"]
                        for item in state.get("restricted_shares", [])
                        if item["symbol"] == symbol and item["list_date"] > str(execution_date)
                    ),
                    "mark_price": marks[symbol],
                }
                for symbol, holding in state["holdings"].items()
            ]
        )
        if state["holdings"]
        else None
    )
    result = simulate_daily_targets(
        calendar=inputs.calendar.filter(pl.col("date") == execution_date),
        bars=scenario_bars,
        scheduled_targets=targets,
        instruments=inputs.instruments,
        market_states={(execution_date, symbol): DailyMarketState() for symbol in symbols},
        initial_cash=state["cash"],
        initial_positions=positions,
        stock_costs=AShareCostModel(**config["costs"]["a_share"]),
        etf_costs=EtfCostModel(**config["costs"]["etf"]),
        strategy=config["paper"]["name"],
    )
    lots = dict(inputs.instruments.select("symbol", "board_lot").iter_rows())
    cash = state["cash"]
    rows = []
    for row in result.trades.iter_rows(named=True):
        cash += (
            row["notional"] - row["fee"]
            if row["side"] == "SELL"
            else -(row["notional"] + row["fee"])
        )
        rows.append(
            {
                "as_of": str(as_of),
                "execution_date": str(execution_date),
                "symbol": row["symbol"],
                "side": row["side"],
                "quantity": row["quantity"],
                "board_lot": lots[row["symbol"]],
                "reference_price": marks[row["symbol"]],
                "estimated_fill_price": row["price"],
                "estimated_notional": row["notional"],
                "estimated_fee": row["fee"],
                "cash_after": cash,
            }
        )
    return pl.DataFrame(rows, schema=ORDER_SCHEMA)


def advance_stock_day(
    *,
    date: dt.date,
    state: dict[str, Any],
    inputs: StockPaperInputs,
    config: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """Advance once, refusing unknown missing prices and using real order-day bands."""
    if state.get("date") and date <= dt.date.fromisoformat(state["date"]):
        raise ValueError("Stock ledger cannot execute a date twice or move backwards")
    state = copy.deepcopy(state)
    relevant = set(state["holdings"]) | {row["symbol"] for row in state["pending"]}
    delisted = set(inputs.instruments.filter(pl.col("delist_date") < date)["symbol"])
    removed = relevant & delisted
    writeoff = sum(
        state["holdings"].get(symbol, {}).get("quantity", 0)
        * state["holdings"].get(symbol, {}).get("mark_price", 0)
        for symbol in removed
    )
    for symbol in removed:
        state["holdings"].pop(symbol, None)
    state["restricted_shares"] = [
        row for row in state.get("restricted_shares", []) if row["symbol"] not in removed
    ]
    if any(row["symbol"] in removed for row in state["pending"]):
        raise ValueError("A pending target became delisted; inspect before advancing")
    relevant -= removed
    bars = inputs.bars.filter(pl.col("trade_date") <= date)
    today = bars.filter(pl.col("trade_date") == date)
    suspended = set(inputs.suspensions.filter(pl.col("trade_date") == date)["symbol"])
    missing = relevant - set(today["symbol"]) - suspended
    if missing:
        raise ValueError(
            f"Missing current stock price without official suspension: {date} {sorted(missing)}"
        )
    if today.is_empty():
        raise ValueError("Missing entire current stock trading session")
    # Supply only relevant history to the account, including a prior close for
    # explicitly suspended new targets. Never replace a missing row with future data.
    account_bars = bars.filter(pl.col("symbol").is_in(sorted(relevant)))
    states = stock_session_states(
        bars=account_bars,
        limits=inputs.limits,
        suspensions=inputs.suspensions,
        sessions=[date],
        symbols=sorted(relevant),
        execution_dates=[date] if state["pending"] and config["paper"].get("enabled", True) else [],
        slippage=config["costs"]["a_share"]["slippage"],
    )
    local_config = copy.deepcopy(config)
    if (
        config["paper"].get("sell_only", False)
        and state["pending"]
        and set(state["holdings"]) - set(today["symbol"])
    ):
        # daily_account's generic sell-only cap requires a current opening row.
        # Here explicitly suspended holdings use their carried mark for sizing;
        # stock_session_states still prohibits filling those orders.
        marks = dict(today.select("symbol", "open").iter_rows())
        for symbol, holding in state["holdings"].items():
            marks.setdefault(symbol, holding["mark_price"])
        equity = state["cash"] + sum(h["quantity"] * marks[s] for s, h in state["holdings"].items())
        for target in state["pending"]:
            quantity = state["holdings"].get(target["symbol"], {}).get("quantity", 0)
            cap = quantity * marks.get(target["symbol"], 0) / equity
            target["weight"] = min(target["weight"], cap)
        local_config["paper"]["sell_only"] = False
    next_state, result = advance(
        date=date,
        state=state,
        bars=account_bars,
        calendar=inputs.calendar,
        instruments=inputs.instruments,
        market_states=states,
        dividends=inputs.dividends,
        config=local_config,
    )
    if (
        config["paper"].get("sell_only", False)
        and result.trades.filter(pl.col("side") == "BUY").height
    ):
        raise ValueError("Sell-only sizing attempted a buy; stock snapshot was not advanced")
    next_state["previous_targets"] = state.get("previous_targets", [])
    next_state["nav"][-1]["position_count"] = len(next_state["holdings"])
    next_state["nav"][-1]["delisting_writeoff"] = writeoff
    next_state["nav"][-1]["carried_suspended_symbols"] = ",".join(
        sorted(relevant - set(today["symbol"]))
    )
    return next_state, result


def render_order_reference(orders: pl.DataFrame, controls: dict[str, bool],
                           title: str = 'B32 A股研究观察：下一日订单参考') -> str:
    lines = [
        f"# {title}",
        "",
        f"全局暂停={controls.get('halt', '未记录')}；仅卖出={controls.get('sell_only', '未记录')}；auto_trade=false。",
        "按信号日收盘价估算，次日模拟成交按真实开盘及官方涨跌停/停牌状态重算。",
        "",
        "|信号日|执行日|证券|方向|股数|参考价|估算成交金额|估算费用|剩余现金|",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"|{r['as_of']}|{r['execution_date']}|{r['symbol']}|{r['side']}|{r['quantity']}|{r['reference_price']:.2f}|{r['estimated_notional']:.2f}|"
        f"{r['estimated_fee']:.2f}|{r['cash_after']:.2f}|"
        for r in orders.iter_rows(named=True)
    )
    if orders.is_empty():
        lines.append("\n无当前可执行参考订单。")
    return "\n".join(lines) + "\n"


def _write_current_orders(folder: Path, orders: pl.DataFrame, controls: dict[str, bool],
                          title: str = 'B32 A股研究观察：下一日订单参考') -> None:
    orders.write_csv(folder / "latest_orders.csv")
    (folder / "latest_orders.md").write_text(render_order_reference(orders, controls, title), encoding="utf-8")


def _write_snapshot(
    folder: Path,
    state: dict[str, Any],
    orders: pl.DataFrame,
    result: Any,
    ranked: pl.DataFrame | None,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    orders.write_csv(folder / "orders.csv")
    (folder/'orders.md').write_text(render_order_reference(orders,
        state.get('controls_at_snapshot', {}),
        f"{state['date']} 股票观察账户订单参考"), encoding='utf-8')
    pl.DataFrame(state["pending"], schema=TARGET_SCHEMA).write_csv(folder / "targets.csv")
    pl.DataFrame(
        [{"symbol": symbol, **holding} for symbol, holding in state["holdings"].items()],
        schema={"symbol": pl.String, "quantity": pl.Int64, "mark_price": pl.Float64},
    ).write_csv(folder / "positions.csv")
    if state["nav"]:
        pl.DataFrame(state["nav"]).write_csv(folder / "nav.csv")
    else:
        pl.DataFrame(
            schema={
                "date": pl.String,
                "unit_nav": pl.Float64,
                "equity": pl.Float64,
                "cash": pl.Float64,
                "market_value": pl.Float64,
                "receivable": pl.Float64,
            }
        ).write_csv(folder / "nav.csv")
    if result is not None:
        result.trades.write_csv(folder / "fills.csv")
        result.rejections.write_csv(folder / "rejections.csv")
    if ranked is not None:
        ranked.write_parquet(folder / "signal_factors.parquet")
        ranked.filter("selected").write_csv(folder / "selected_factors.csv")
    # Completed snapshots are the restart point; write this after the date's outputs.
    (folder / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run(
    *,
    config_path: Path,
    data_root: Path,
    output: Path,
    end: dt.date,
    halt: bool | None = None,
    sell_only: bool | None = None,
) -> dict[str, Any]:
    payload = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(payload)
    paper = config["paper"]
    if (
        paper["auto_trade"] is not False
        or config["research"]["conclusion"] != "RESEARCH_ONLY"
        or [a["name"] for a in config["accounts"]]
        != ["b32_cv20_buffer75", "b32_paired_three_factor"]
        or config["signal"]["top_k"] != 50
        or config["signal"]["target_weight"] != 0.02
    ):
        raise ValueError("Only the frozen B32 stock observation accounts are supported")
    if not paper["initial_signal_date"] <= end <= paper["end_date"]:
        raise ValueError("Requested date outside the frozen forward window")
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "config.toml"
    if frozen.exists() and frozen.read_text(encoding="utf-8") != payload:
        raise ValueError("Frozen stock paper config changed; use a new observation")
    if not frozen.exists():
        frozen.write_text(payload, encoding="utf-8")
    controls = _controls(output, paper, halt, sell_only)
    universe_path = output / "frozen_universe.csv"
    if universe_path.exists():
        symbols = pl.read_csv(universe_path)["symbol"].to_list()
    else:
        universe = config["universe"]
        symbols = list(
            select_frozen_liquid_universe(
                read_stock_paper_freeze(data_root, config),
                top_n=universe["top_n"],
                minimum_observations=universe["minimum_observations"],
                minimum_average_amount=universe["minimum_average_amount"],
            )
        )
        pl.DataFrame({"symbol": symbols}).write_csv(universe_path)
    calendar = read_stock_paper_calendar(data_root)
    sessions = tuple(calendar.filter(pl.col("is_open"))["date"].unique().sort().to_list())
    if end not in sessions or paper["initial_signal_date"] not in sessions:
        raise ValueError("Stock observation requires exchange session dates")
    cache: dict[dt.date, StockPaperInputs] = {}
    panels: dict[dt.date, pl.DataFrame] = {}
    summaries = []
    for account in config["accounts"]:
        folder = output / account["name"]
        folder.mkdir(exist_ok=True)
        snapshots = sorted(folder.glob("????-??-??/state.json"))
        state: dict[str, Any] = {
            "cash": paper["initial_cash"],
            "holdings": {},
            "receivables": [],
            "restricted_shares": [],
            "pending": [],
            "nav": [],
            "previous_targets": [],
            "cumulative_fees": 0.0,
        }
        last = paper["initial_signal_date"] - dt.timedelta(days=1)
        if snapshots:
            state = json.loads(snapshots[-1].read_text(encoding="utf-8"))
            last = dt.date.fromisoformat(state["date"])
            if last > end:
                raise ValueError("Cannot branch or rewind an existing forward stock account")
        elif end != paper["initial_signal_date"]:
            raise ValueError(
                "Initialize the forward observation on its frozen initial signal date first"
            )
        dates = [
            date for date in sessions if last < date <= end and date >= paper["initial_signal_date"]
        ]
        for date in dates:
            if date not in cache:
                cache.clear()
                cache[date] = read_stock_paper_inputs(data_root, config, symbols, date)
            inputs = cache[date]
            local_config = account_config(config, account, controls)
            result, ranked = None, None
            if date >= paper["start_date"]:
                state, result = advance_stock_day(
                    date=date, state=state, inputs=inputs, config=local_config
                )
            state["date"] = str(date)
            state["mode"] = "forward_research_observation"
            state["conclusion"] = "RESEARCH_ONLY"
            state["controls_at_snapshot"] = dict(controls)
            state["recorded_at"] = dt.datetime.now(SHANGHAI).isoformat()
            following = next((day for day in sessions if day > date), None)
            signal_due = date == paper["initial_signal_date"] or (
                following is not None and following.month != date.month
            )
            if signal_due and following is not None and following <= paper["end_date"]:
                if date not in panels:
                    panels[date] = effective_stock_factors(
                        bars=inputs.bars,
                        daily_basic=inputs.daily_basic,
                        names=inputs.names,
                        sessions=tuple(
                            day for day in sessions if day >= config["data"]["warmup_start"]
                        ),
                        as_of=date,
                        config=config,
                    )
                state["pending"], ranked = stock_targets(
                    panels[date],
                    previous_targets=state["previous_targets"],
                    as_of=date,
                    execution_date=following,
                    account=account,
                    top_k=config["signal"]["top_k"],
                )
                state["previous_targets"] = [row["symbol"] for row in state["pending"]]
            else:
                state["pending"] = []
            orders = reference_orders(state, inputs, local_config)
            _write_snapshot(folder / str(date), state, orders, result, ranked)
        if end not in cache:
            cache.clear()
            cache[end] = read_stock_paper_inputs(data_root, config, symbols, end)
        orders = reference_orders(state, cache[end], account_config(config, account, controls))
        _write_current_orders(folder, orders, controls)
        summaries.append(
            {
                "account": account["name"],
                "as_of": state["date"],
                "sessions": len(state["nav"]),
                "positions": len(state["holdings"]),
                "cash": state["cash"],
                "targets": len(state["pending"]),
                "reference_orders": orders.height,
                "reference_notional": orders["estimated_notional"].sum(),
                "estimated_fees": orders["estimated_fee"].sum(),
                "equity": state["nav"][-1]["equity"] if state["nav"] else paper["initial_cash"],
                "new_sessions": len(dates),
                "output": str(folder / state["date"]),
            }
        )
    summary = {
        "conclusion": "RESEARCH_ONLY",
        "mode": "forward_research_observation",
        "auto_trade": False,
        "controls": controls,
        "accounts": summaries,
    }
    (output / "latest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/paper/b32_stock_observation_20260909.toml")
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/paper/b32_stock_observation")
    )
    parser.add_argument("--to", default="today")
    parser.add_argument("--halt", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--sell-only", action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    now = dt.datetime.now(SHANGHAI)
    date = now.date() if args.to == "today" else dt.date.fromisoformat(args.to)
    if date > now.date():
        parser.error("Future trading dates cannot be recorded")
    if date == now.date() and now.hour < 21:
        if args.halt is not None or args.sell_only is not None:
            config = tomllib.loads(args.config.read_text(encoding="utf-8"))
            controls = _controls(args.output, config["paper"], args.halt, args.sell_only)
            # Safety switches apply immediately, without recording a new session.
            for account in config["accounts"]:
                folder = args.output / account["name"]
                prior = sorted(folder.glob("????-??-??/orders.csv"))
                if prior:
                    orders = pl.read_csv(prior[-1])
                    if controls["halt"]:
                        orders = orders.clear()
                    elif controls["sell_only"]:
                        orders = orders.filter(pl.col("side") == "SELL")
                    _write_current_orders(folder, orders, controls)
        print(
            json.dumps(
                {
                    "action": "skipped_waiting_for_daily_inputs",
                    "requested_date": str(date),
                    "ready_after": f"{date}T21:00:00+08:00",
                    "snapshots_advanced": 0,
                }
            )
        )
        return
    end = latest_session(data_root=args.data_root, through=date)
    print(
        json.dumps(
            run(
                config_path=args.config,
                data_root=args.data_root,
                output=args.output,
                end=end,
                halt=args.halt,
                sell_only=args.sell_only,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
