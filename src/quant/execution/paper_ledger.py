"""Daily S0 paper ledger using the shared daily simulator; no broker connection."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.backtest import EtfCostModel
from quant.backtest.daily_account import advance as advance
from quant.data.etf_limits import read_limits
from quant.data.etf_paper_inputs import etf_session_states, read_etf_dividends
from quant.data.etf_research_inputs import read_etf_research_inputs
from quant.data.refresh import SHANGHAI, completed_date, latest_session
from quant.research.run_s1_walk_forward import _candidates


def next_targets(
    date: dt.date, next_session: dt.date, first_session: dt.date,
    symbols: list[str], config: dict[str, Any],
    prices: pl.DataFrame | None = None, calendar: pl.DataFrame | None = None,
) -> list[dict[str, Any]]:
    if not config["paper"].get("enabled", True):
        return []
    if next_session < first_session or (date.month == next_session.month and next_session != first_session):
        return []
    if config.get("strategy", {}).get("kind") == "inverse_volatility":
        from quant.research.monthly_etf import completed_month_prices
        from quant.strategies.inverse_volatility import InverseVolatilityStrategy

        if prices is None or calendar is None:
            raise ValueError("Inverse-volatility targets require total-return prices and calendar")
        monthly = completed_month_prices(prices, calendar).filter(pl.col("trade_date") <= date)
        cutoff = monthly["trade_date"].max()
        if cutoff is None:
            raise ValueError("No completed month for inverse-volatility targets")
        target = InverseVolatilityStrategy(tuple(sorted(symbols)), config["strategy"]["lookback_sessions"],
            name=config["paper"]["name"]).target_weights(date, prices.filter(pl.col("trade_date") <= cutoff))
        return [{"as_of": str(date), "execution_date": str(next_session),
                 "strategy": row["strategy"], "strategy_version": row["strategy_version"],
                 "symbol": row["symbol"], "weight": row["weight"]} for row in target.to_dicts()]
    return [{"as_of": str(date), "execution_date": str(next_session),
             "strategy": config["paper"]["name"], "strategy_version": "1.0.0",
             "symbol": s, "weight": 1.0 / len(symbols)} for s in sorted(symbols)]


def order_estimates(state: dict[str, Any], bars: pl.DataFrame, config: dict[str, Any]) -> pl.DataFrame:
    """Close-price reference list; actual fills are recomputed from next-session opens."""
    schema = {"as_of": pl.String, "execution_date": pl.String, "symbol": pl.String,
              "side": pl.String, "quantity": pl.Int64, "reference_price": pl.Float64,
              "reference_amount": pl.Float64}
    if not state["pending"]:
        return pl.DataFrame(schema=schema)
    marks = dict(bars.select("symbol", "close").iter_rows())
    equity = state["cash"] + sum(h["quantity"] * marks[s] for s, h in state["holdings"].items())
    costs = EtfCostModel(**config["costs"]["etf"])
    rows = []
    for target in state["pending"]:
        symbol = target["symbol"]
        held = state["holdings"].get(symbol, {}).get("quantity", 0)
        desired = math.floor(target["weight"] * equity / marks[symbol] / 100) * 100
        delta = desired - held
        if config["paper"].get("sell_only", False) and delta > 0:
            continue
        if delta:
            rows.append({"as_of": target["as_of"], "execution_date": target["execution_date"],
                         "symbol": symbol, "side": "BUY" if delta > 0 else "SELL",
                         "quantity": abs(delta), "reference_price": marks[symbol],
                         "reference_amount": abs(delta) * marks[symbol]})
    rows.sort(key=lambda r: (r["side"] != "SELL", r["symbol"]))
    cash = state["cash"]
    for row in rows:
        side, quantity, price = row["side"], row["quantity"], row["reference_price"]
        fill = costs.execution_price(price, side)
        date = dt.date.fromisoformat(row["execution_date"])
        if side == "BUY":
            while quantity and quantity * fill + costs.fee(quantity * fill, date) > cash:
                quantity -= 100
        if quantity:
            fee = costs.fee(quantity * fill, date)
            cash += quantity * fill - fee if side == "SELL" else -(quantity * fill + fee)
        row["quantity"] = quantity
        row["reference_amount"] = quantity * price
    return pl.DataFrame([r for r in rows if r["quantity"]], schema=schema)


def run(*, config_path: Path, data_root: Path, output: Path, end: dt.date,
        rehearsal_start: dt.date | None = None, sell_only: bool | None = None,
        halt: bool | None = None) -> dict[str, Any]:
    config_text = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(config_text)
    paper = config["paper"]
    if paper["auto_trade"] is not False or paper["name"] not in {
        "s0_equal", "b20_inverse_volatility", "b20_equal_weight",
    }:
        raise ValueError("Only the frozen paper baseline and B20 observation are supported")
    if rehearsal_start is not None:
        output = output / "rehearsal"
    output.mkdir(parents=True, exist_ok=True)
    controls_path = output / "controls.json"
    controls = (json.loads(controls_path.read_text(encoding="utf-8")) if controls_path.exists()
                else {"halt": False, "sell_only": paper.get("sell_only", False)})
    original_controls = dict(controls)
    if halt is not None:
        controls["halt"] = halt
    if sell_only is not None:
        controls["sell_only"] = sell_only
    paper["enabled"] = not controls["halt"]
    paper["sell_only"] = controls["sell_only"]
    controls_path.write_text(json.dumps(controls), encoding="utf-8")
    frozen = output / "config.toml"
    if frozen.exists() and frozen.read_text(encoding="utf-8") != config_text:
        raise ValueError("Paper config changed; use a new account directory")
    if not frozen.exists():
        frozen.write_text(config_text, encoding="utf-8")
    existing_snapshot = (output / str(end) / "state.json").exists()
    if existing_snapshot and original_controls == controls:
        return {"output": str(output / str(end)), "message": "no-op"}
    symbols = config["universe"].get("symbols") or _candidates(config)
    data_start = config["data"].get("start_date") or config["data"]["start"]
    if "cross_asset_daily_prefix" in config["data"]:
        from quant.research.monthly_etf import read_inputs

        bars, prices, calendars, instruments, dividends = read_inputs(data_root, tuple(symbols), {
            "cross_asset_snapshot": f"{config['data']['cross_asset_daily_prefix']}_{end:%Y%m%d}",
            "start": data_start, "end": end,
        })
    else:
        bars, prices, calendars, instruments = read_etf_research_inputs(
            data_root, symbols, data_start, end,
        )
        dividends = read_etf_dividends(data_root, symbols, data_start)
    sessions = sorted(calendars.filter(pl.col("is_open")).get_column("date").unique().to_list())
    start = rehearsal_start or paper["start_date"]
    first = next(d for d in sessions if d >= start)
    previous = max(d for d in sessions if d < first)
    market_states = etf_session_states(
        bars.filter(pl.col("trade_date").is_between(first, end)), dividends,
        slippage=config["costs"]["etf"]["slippage"], official_limits=read_limits(data_root),
        slippage_per_share=config["costs"]["etf"].get("slippage_per_share", 0.0),
    )
    snapshots = sorted(p for p in output.glob("????-??-??/state.json") if p.parent.name <= str(end))
    state: dict[str, Any] = {"cash": paper["initial_cash"], "holdings": {}, "receivables": [],
                             "pending": [], "nav": [], "cumulative_fees": 0.0}
    last_date = previous
    if snapshots:
        state = json.loads(snapshots[-1].read_text(encoding="utf-8"))
        last_date = dt.date.fromisoformat(state["date"])
        if state["nav"] and state["nav"][0]["date"] != str(first):
            raise ValueError("Account start changed; use another rehearsal directory")
    if end >= first and last_date < first and not state["pending"]:
        state["pending"] = next_targets(previous, first, first, symbols, config, prices, calendars)
    process_dates = [d for d in sessions if first <= d <= end and d > last_date]
    if not process_dates:
        process_dates = [end]
    for date in process_dates:
        result = None
        if date >= first and not existing_snapshot:
            state, result = advance(date=date, state=state, bars=bars, calendar=calendars,
                                    instruments=instruments, market_states=market_states,
                                    dividends=dividends, config=config)
        state["date"] = str(date)
        state["trading_enabled"] = paper["enabled"]
        state["sell_only"] = paper["sell_only"]
        following = next(d for d in sessions if d > date)
        state["pending"] = next_targets(date, following, first, symbols, config, prices, calendars)
        folder = output / str(date)
        folder.mkdir(exist_ok=True)
        estimates = order_estimates(state, bars.filter(pl.col("trade_date") == date), config)
        estimates.write_csv(folder / "orders.csv")
        pl.DataFrame(state["pending"], schema={"as_of": pl.String, "execution_date": pl.String,
            "strategy": pl.String, "strategy_version": pl.String, "symbol": pl.String,
            "weight": pl.Float64}).write_csv(folder / "targets.csv")
        pl.DataFrame(state["nav"], schema={"strategy": pl.String, "date": pl.String,
            "equity": pl.Float64, "unit_nav": pl.Float64, "cash": pl.Float64,
            "market_value": pl.Float64, "cumulative_fees": pl.Float64,
            "receivable": pl.Float64}).write_csv(folder / "nav.csv")
        pl.DataFrame([{"symbol": s, **h} for s, h in state["holdings"].items()],
            schema={"symbol": pl.String, "quantity": pl.Int64, "mark_price": pl.Float64}
        ).write_csv(folder / "positions.csv")
        if result is not None:
            result.trades.write_csv(folder / "fills.csv")
            result.rejections.write_csv(folder / "rejections.csv")
        title = "S0 模拟盘" if paper["name"] == "s0_equal" else "B20 前向观察"
        lines = [f"# {title}订单参考：{date}", "", "价格使用信号日收盘价，实际股数须按下一开市日价格及现金复核。", "",
                 "| 证券 | 方向 | 股数 | 参考价 | 参考金额 |", "|---|---|---:|---:|---:|"]
        lines += [f"| {r['symbol']} | {r['side']} | {r['quantity']} | {r['reference_price']:.3f} | {r['reference_amount']:.2f} |"
                  for r in estimates.iter_rows(named=True)]
        if estimates.is_empty():
            lines += ["", f"无待执行调仓；前向模拟盘首个交易日为 {first}。"]
        (folder / "orders.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output / str(end)), "sessions": len(state["nav"]),
            "first_session": str(first), "equity": state["nav"][-1]["equity"] if state["nav"] else state["cash"],
            "mode": "rehearsal" if rehearsal_start else "paper"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/paper/s0_equal_20260909.toml"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/paper"))
    parser.add_argument("--to", default="today")
    parser.add_argument("--rehearsal-start", type=dt.date.fromisoformat)
    parser.add_argument("--sell-only", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--halt", action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    end = latest_session(data_root=args.data_root, through=completed_date(args.to, dt.datetime.now(SHANGHAI)))
    print(json.dumps(run(config_path=args.config, data_root=args.data_root, output=args.output,
                         end=end, rehearsal_start=args.rehearsal_start,
                         sell_only=args.sell_only, halt=args.halt), ensure_ascii=False))


if __name__ == "__main__":
    main()
