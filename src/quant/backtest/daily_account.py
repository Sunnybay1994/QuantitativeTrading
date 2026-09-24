"""Cash, receivables and share distributions around the shared daily simulator."""

import datetime as dt
import math
from typing import Any

import polars as pl

from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.daily_simulator import simulate_daily_targets


def prepare_account_actions(*, date: dt.date, state: dict[str, Any], calendar: pl.DataFrame,
                            dividends: pl.DataFrame, settle_cash: bool = True) -> dict[str, Any]:
    """Reuse entitlements; manual books settle cash only when an actual payment arrives."""
    holdings = {s: dict(h) for s, h in state["holdings"].items()}
    cash = float(state["cash"])
    receivables = list(state["receivables"])
    reduction_entitlements = dict(state.get("share_reduction_entitlements", {}))
    distributions = dict(state.get("share_distribution_entitlements", {}))
    restricted = [r for r in state.get("restricted_shares", []) if r["list_date"] > str(date)]
    for event in dividends.filter(pl.col("ex_date") == date).iter_rows(named=True):
        if event["ann_date"] > date:
            raise ValueError("Dividend announcement is not known on ex-date")
        quantity = holdings.get(event["symbol"], {}).get("quantity", 0)
        ratio = event.get("share_ratio") or 0.0
        amount = quantity * event["div_cash"]
        if ratio < 0:
            if not -1 < ratio < 0 or amount:
                raise ValueError("Invalid uncompensated share reduction")
            key = f"{event['symbol']}|{date}"
            if (key not in reduction_entitlements and not quantity
                    and state.get('started_with_cash') is True
                    and str(event['record_date']) < state.get('inception_date', '')):
                # This account did not exist at the record date and has no
                # affected shares now. Its entitlement is known to be zero.
                reduction_entitlements[key] = 0
            if key not in reduction_entitlements:
                raise ValueError("Share reduction requires record-date holdings snapshot")
            entitled = reduction_entitlements.pop(key)
            if entitled != quantity or any(r["symbol"] == event["symbol"] for r in restricted):
                raise ValueError("Share reduction holdings changed since record date")
            if quantity:
                # No compensating price adjustment: surrendered shares are a loss.
                # Conservatively round remaining shares down to a whole share.
                holdings[event["symbol"]]["quantity"] = math.floor(quantity * (1 + ratio) + 1e-9)
            continue
        entitled = quantity
        distribution = distributions.pop(f"{event['symbol']}|{date}", None) if ratio > 0 else None
        if ratio > 0 and distribution is not None:
            entitled = distribution["quantity"]
            amount = entitled * event["div_cash"]
        if (quantity or entitled) and (amount or ratio):
            previous_session = calendar.filter(
                pl.col("is_open") & (pl.col("market") == event["symbol"][-2:])
                & (pl.col("date") < date)
            ).get_column("date").max()
            if event["record_date"] != previous_session and distribution is None:
                if (ratio > 0 and state.get("started_with_cash") is True
                        and str(event["record_date"]) < state.get("inception_date", "")):
                    entitled, amount = 0, 0.0
                else:
                    raise ValueError("Dividend record date requires an earlier holdings snapshot")
            if amount:
                receivables.append({"symbol": event["symbol"], "pay_date": str(event["pay_date"]),
                                    "amount": amount})
            if ratio:
                added = math.floor(entitled * ratio + 1e-9)
                if event["symbol"] not in holdings:
                    if not added:
                        continue
                    if distribution is None:
                        raise ValueError("Missing record-date share distribution entitlement")
                    holdings[event["symbol"]] = {"quantity": 0, "mark_price": distribution["mark_price"]}
                holdings[event["symbol"]]["quantity"] += added
                if event.get("adjust_share_price", True):
                    holdings[event["symbol"]]["mark_price"] /= 1 + ratio
                listing = event["share_list_date"]
                if listing is None or listing < date:
                    raise ValueError("Invalid share distribution listing date")
                if listing > date and added:
                    restricted.append({"symbol": event["symbol"], "quantity": added,
                                       "list_date": str(listing)})
    if settle_cash:
        cash += sum(r["amount"] for r in receivables if r["pay_date"] <= str(date))
        receivables = [r for r in receivables if r["pay_date"] > str(date)]
    return {"holdings": holdings, "cash": cash, "receivables": receivables,
            "restricted_shares": restricted, "share_reduction_entitlements": reduction_entitlements,
            "share_distribution_entitlements": distributions}


def capture_record_date_entitlements(*, date: dt.date, state: dict[str, Any],
                                     dividends: pl.DataFrame) -> None:
    """Keep known record-date holdings for later share distributions or reductions."""
    reduction_entitlements = dict(state.get("share_reduction_entitlements", {}))
    distributions = dict(state.get("share_distribution_entitlements", {}))
    # Preserve record-date quantities until settlement, even after selling.
    # Future settlement metadata never changes targets or valuation here.
    if "share_ratio" in dividends.columns:
        for event in dividends.filter(
            (pl.col("record_date") == date) & (pl.col("share_ratio") > 0)
        ).iter_rows(named=True):
            holding = state["holdings"].get(event["symbol"], {})
            distributions[f"{event['symbol']}|{event['ex_date']}"] = {
                "quantity": holding.get("quantity", 0), "mark_price": holding.get("mark_price", 0.)}
        for event in dividends.filter(
            (pl.col("record_date") == date) & (pl.col("share_ratio") < 0)
        ).iter_rows(named=True):
            key = f"{event['symbol']}|{event['ex_date']}"
            reduction_entitlements[key] = state["holdings"].get(event["symbol"], {}).get("quantity", 0)
    if reduction_entitlements:
        state["share_reduction_entitlements"] = reduction_entitlements
    if distributions:
        state["share_distribution_entitlements"] = distributions


def advance(
    *, date: dt.date, state: dict[str, Any], bars: pl.DataFrame,
    calendar: pl.DataFrame, instruments: pl.DataFrame, market_states: dict,
    dividends: pl.DataFrame, config: dict[str, Any],
    scheduled_orders: pl.DataFrame | None = None,
    target_permissions: dict[str, tuple[bool, bool]] | None = None,
    execution_notional_caps: dict[str, float] | None = None,
    target_share_deltas: dict[str, int] | None = None,
) -> tuple[dict[str, Any], Any]:
    """Settle prior holdings, recognize dividends, then execute yesterday's targets."""
    paper = config["paper"]
    if paper["auto_trade"] is not False:
        raise ValueError("This ledger only accepts auto_trade=false")
    prepared = prepare_account_actions(date=date, state=state, calendar=calendar, dividends=dividends)
    holdings, cash, receivables = prepared["holdings"], prepared["cash"], prepared["receivables"]
    restricted = prepared["restricted_shares"]
    reduction_entitlements = prepared["share_reduction_entitlements"]
    distributions = prepared["share_distribution_entitlements"]
    pending = state["pending"] if paper.get("enabled", True) else []
    if scheduled_orders is not None:
        if pending:
            raise ValueError('Use either pending targets or fixed share orders')
        scheduled_orders = scheduled_orders.with_columns(
            *[pl.col(column).str.to_date() if scheduled_orders.schema[column] == pl.String
              else pl.col(column) for column in ('as_of', 'execution_date')])
        if scheduled_orders.height and scheduled_orders['execution_date'].unique().to_list() != [date]:
            raise ValueError('Fixed share orders belong to another trading session')
        if not paper.get('enabled', True):
            scheduled_orders = scheduled_orders.clear()
        elif paper.get('sell_only', False):
            scheduled_orders = scheduled_orders.filter(pl.col('side') == 'SELL')
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
        strategy=paper["name"], initial_positions=initial, scheduled_orders=scheduled_orders,
        target_permissions=target_permissions,
        execution_notional_caps=execution_notional_caps,
        target_share_deltas=target_share_deltas,
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
    for field in ("inception_date", "started_with_cash"):
        if field in state:
            next_state[field] = state[field]
    if reduction_entitlements:
        next_state["share_reduction_entitlements"] = reduction_entitlements
    if distributions:
        next_state["share_distribution_entitlements"] = distributions
    capture_record_date_entitlements(date=date, state=next_state, dividends=dividends)
    return next_state, result


