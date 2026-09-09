"""Cash, receivables and share distributions around the shared daily simulator."""

import datetime as dt
import math
from typing import Any

import polars as pl

from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.daily_simulator import simulate_daily_targets


def advance(
    *, date: dt.date, state: dict[str, Any], bars: pl.DataFrame,
    calendar: pl.DataFrame, instruments: pl.DataFrame, market_states: dict,
    dividends: pl.DataFrame, config: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """Settle prior holdings, recognize dividends, then execute yesterday's targets."""
    paper = config["paper"]
    if paper["auto_trade"] is not False:
        raise ValueError("This ledger only accepts auto_trade=false")
    holdings = {s: dict(h) for s, h in state["holdings"].items()}
    cash = float(state["cash"])
    receivables = list(state["receivables"])
    restricted = [r for r in state.get("restricted_shares", []) if r["list_date"] > str(date)]
    for event in dividends.filter(pl.col("ex_date") == date).iter_rows(named=True):
        if event["ann_date"] > date:
            raise ValueError("Dividend announcement is not known on ex-date")
        quantity = holdings.get(event["symbol"], {}).get("quantity", 0)
        amount = quantity * event["div_cash"]
        ratio = event.get("share_ratio") or 0.0
        if quantity and (amount or ratio):
            previous_session = calendar.filter(
                pl.col("is_open") & (pl.col("market") == event["symbol"][-2:])
                & (pl.col("date") < date)
            ).get_column("date").max()
            if event["record_date"] != previous_session:
                raise ValueError("Dividend record date requires an earlier holdings snapshot")
            if amount:
                receivables.append({"symbol": event["symbol"], "pay_date": str(event["pay_date"]),
                                    "amount": amount})
            if ratio:
                added = math.floor(quantity * ratio + 1e-9)
                holdings[event["symbol"]]["quantity"] += added
                holdings[event["symbol"]]["mark_price"] /= 1 + ratio
                listing = event["share_list_date"]
                if listing is None or listing < date:
                    raise ValueError("Invalid share distribution listing date")
                if listing > date and added:
                    restricted.append({"symbol": event["symbol"], "quantity": added,
                                       "list_date": str(listing)})
    cash += sum(r["amount"] for r in receivables if r["pay_date"] <= str(date))
    receivables = [r for r in receivables if r["pay_date"] > str(date)]
    pending = state["pending"] if paper.get("enabled", True) else []
    targets = pl.DataFrame(schema={"as_of": pl.Date, "strategy": pl.String,
        "strategy_version": pl.String, "symbol": pl.String, "weight": pl.Float64,
        "execution_date": pl.Date})
    if pending:
        targets = pl.DataFrame(pending).with_columns(
            pl.col("as_of").str.to_date(), pl.col("execution_date").str.to_date(),
        )
        if targets.get_column("execution_date").unique().to_list() != [date]:
            raise ValueError("Pending targets belong to another trading session")
        if paper.get("sell_only", False):
            # Keep sells but cap each target at its existing position value.
            opens = dict(bars.filter(pl.col("trade_date") == date).select("symbol", "open").iter_rows())
            equity = cash + sum(h["quantity"] * opens[s] for s, h in holdings.items())
            caps = {s: h["quantity"] * opens[s] / equity for s, h in holdings.items()}
            targets = targets.with_columns(pl.Series("weight", [
                min(r["weight"], caps.get(r["symbol"], 0.0)) for r in targets.iter_rows(named=True)
            ]))
    initial = pl.DataFrame([
        {"symbol": s, "quantity": h["quantity"], "settled_quantity": h["quantity"] - sum(
             r["quantity"] for r in restricted if r["symbol"] == s),
         "mark_price": h["mark_price"]} for s, h in holdings.items()
    ]) if holdings else None
    result = simulate_daily_targets(
        calendar=calendar.filter(pl.col("date") == date),
        bars=bars.filter(pl.col("trade_date") <= date), scheduled_targets=targets,
        instruments=instruments, market_states=market_states, initial_cash=cash,
        etf_costs=EtfCostModel(**config["costs"]["etf"]),
        stock_costs=AShareCostModel(**config["costs"]["a_share"]),
        strategy=paper["name"], initial_positions=initial,
    )
    nav = result.nav.row(-1, named=True)
    nav["receivable"] = sum(r["amount"] for r in receivables)
    nav["equity"] += nav["receivable"]
    nav["unit_nav"] = nav["equity"] / paper["initial_cash"]
    nav["cumulative_fees"] += state.get("cumulative_fees", 0.0)
    if not math.isclose(nav["equity"], nav["cash"] + nav["market_value"] + nav["receivable"]):
        raise ValueError("Paper account does not reconcile")
    next_state = {
        "date": str(date), "cash": nav["cash"], "receivables": receivables,
        "restricted_shares": restricted,
        "cumulative_fees": nav["cumulative_fees"], "pending": [],
        "holdings": {r["symbol"]: {"quantity": r["quantity"], "mark_price": r["mark_price"]}
                     for r in result.positions.iter_rows(named=True) if r["quantity"] > 0},
        "nav": [*state["nav"], {**nav, "date": str(date)}],
    }
    return next_state, result


