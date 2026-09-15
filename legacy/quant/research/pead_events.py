"""Announcement-time SUE events and a fixed forty-session portfolio."""

import copy
import datetime as dt
import math
from bisect import bisect_right
from typing import Any

import polars as pl

from quant.backtest.daily_account import advance
from quant.factors.reversal_volatility import exclude_historical_risk_names
from quant.research.monthly_sue import build_monthly_sue


def build_events(*, history: pl.DataFrame, bars: pl.DataFrame, names: pl.DataFrame,
                 sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
                 minimum_threshold_events: int = 100) -> pl.DataFrame:
    """Freeze each first-observed announcement; never use future quarterly peers."""
    first = (history.filter((pl.col("report_type") == "1") & (pl.col("comp_type") == "1"))
             .group_by("symbol", "end_date").agg(pl.col("available_date").min())
             .filter(pl.col("available_date").is_between(start, end))
             .filter((pl.col("available_date") - pl.col("end_date")).dt.total_days().is_between(0, 180)))
    first = first.sort("end_date").group_by("symbol", "available_date").tail(1)
    rows = []
    for (date,), events in first.partition_by("available_date", as_dict=True).items():
        symbols = tuple(events["symbol"].to_list())
        scores = build_monthly_sue(
            income_history=history.filter(pl.col("symbol").is_in(symbols)),
            signal_dates=(date + dt.timedelta(days=1),), candidate_symbols=symbols,
        ).factors.drop("trade_date")
        scored = events.join(scores, on="symbol", how="left").filter(
            (pl.col("end_date") == pl.col("financial_period_end"))
            & pl.col("pit_sue8").is_finite())
        rows.append(scored)
    frame = pl.concat(rows).drop("end_date").rename({"available_date": "announcement_date"})
    # Only the last exchange close at or before the announcement is observable.
    prices = bars.sort("symbol", "trade_date").with_columns(
        pl.col("amount").rolling_mean(20).over("symbol").alias("liquidity20"),
        pl.col("trade_date").cum_count().over("symbol").alias("history_rows"),
    ).select("symbol", pl.col("trade_date").alias("price_date"), "liquidity20", "history_rows")
    frame = frame.sort("symbol", "announcement_date").join_asof(
        prices.sort("symbol", "price_date"), left_on="announcement_date", right_on="price_date",
        by="symbol", check_sortedness=False).filter(
            (pl.col("liquidity20") >= 20_000_000) & (pl.col("history_rows") >= 120))
    frame = exclude_historical_risk_names(frame.with_columns(
        pl.col("announcement_date").alias("trade_date")), names).drop("trade_date")
    output = []
    for row in frame.sort("announcement_date", "symbol").iter_rows(named=True):
        date = row["announcement_date"]
        quarter = dt.date(date.year, ((date.month - 1) // 3) * 3 + 1, 1)
        previous_end = quarter - dt.timedelta(days=1)
        previous_start = dt.date(previous_end.year, ((previous_end.month - 1) // 3) * 3 + 1, 1)
        prior = frame.filter(pl.col("announcement_date").is_between(previous_start, previous_end))["pit_sue8"]
        cutoff = prior.quantile(0.9, interpolation="linear") if len(prior) >= minimum_threshold_events else None
        index = bisect_right(sessions, date)
        if index + 40 >= len(sessions):
            continue
        output.append({**row, "threshold_count": len(prior), "threshold": cutoff,
                       "selected": cutoff is not None and row["pit_sue8"] > 0 and row["pit_sue8"] >= cutoff,
                       "execution_date": sessions[index], "expiry_date": sessions[index + 40]})
    return pl.DataFrame(output, infer_schema_length=None).sort("announcement_date", "symbol")


def portfolio_weights(*, state: dict[str, Any], date: dt.date, opens: dict[str, float],
                      dividends: pl.DataFrame, expired: set[str], entrants: list[str]) -> dict[str, float]:
    """Translate frozen decisions to weights while keeping existing round-lot quantities."""
    holdings = copy.deepcopy(state["holdings"])
    cash = state["cash"] + sum(r["amount"] for r in state["receivables"] if r["pay_date"] <= str(date))
    for row in dividends.filter(pl.col("ex_date") == date).iter_rows(named=True):
        if row["symbol"] not in holdings:
            continue
        holding = holdings[row["symbol"]]
        old = holding["quantity"]
        holding["quantity"] += math.floor(old * (row.get("share_ratio") or 0) + 1e-9)
        holding["mark_price"] /= 1 + (row.get("share_ratio") or 0)
        if row["pay_date"] is not None and row["pay_date"] <= date:
            cash += old * row["div_cash"]
    references = {s: opens.get(s, h["mark_price"]) for s, h in holdings.items()}
    equity = cash + sum(h["quantity"] * references[s] for s, h in holdings.items())
    weights = {s: (0.0 if s in expired else (h["quantity"] + 1e-7) * references[s] / equity)
               for s, h in holdings.items()}
    # Buffer is only arithmetic stabilization (< one millionth of a share).
    remaining = max(0.0, 1.0 - sum(weights.values()) - 1e-10)
    weight = min(0.02, remaining / len(entrants)) if entrants else 0.0
    weights.update({s: weight for s in entrants})
    return weights


def replay_events(*, events: pl.DataFrame, bars: pl.DataFrame, calendar: pl.DataFrame,
                  instruments: pl.DataFrame, dividends: pl.DataFrame, market_states: dict,
                  sessions: list[dt.date], config: dict[str, Any], name: str
                  ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """One entry attempt; no extension; blocked expiry sales retry daily."""
    state: dict[str, Any] = {"holdings": {}, "cash": config["portfolio"]["initial_cash"],
                             "receivables": [], "pending": [], "nav": []}
    account = {"paper": {"name": name, "auto_trade": False, "initial_cash": state["cash"]},
               "costs": config["costs"]}
    by_date = {k[0]: v for k, v in bars.partition_by("trade_date", as_dict=True).items()}
    event_dates = {k[0]: v for k, v in events.partition_by("execution_date", as_dict=True).items()}
    expiry: dict[str, dt.date] = {}
    trades: list[pl.DataFrame] = []
    rejected: list[pl.DataFrame] = []
    decisions: list[dict[str, Any]] = []
    prior_closes = {r["symbol"]: r for r in bars.filter(pl.col("trade_date") < sessions[0])
                    .sort("trade_date").unique("symbol", keep="last").iter_rows(named=True)}
    for date in sessions:
        today = by_date.get(date, bars.head(0))
        today_symbols = set(today["symbol"])
        removed, writeoff = [], 0.0
        for symbol in instruments.filter(pl.col("delist_date") < date)["symbol"]:
            holding = state["holdings"].pop(symbol, None)
            if holding:
                writeoff += holding["quantity"] * holding["mark_price"]
                removed.append(symbol)
        state["restricted_shares"] = [r for r in state.get("restricted_shares", []) if r["symbol"] not in removed]
        expiry = {s: d for s, d in expiry.items() if s in state["holdings"]}
        expired = {s for s, d in expiry.items() if d <= date}
        entrants: list[str] = []
        batch = event_dates.get(date)
        capacity = max(0, config["portfolio"]["slots"] - len(state["holdings"]))
        # Conservative capacity: an expiring slot is available only after the actual sale.
        if batch is not None:
            for row in batch.sort("announcement_date", "symbol").iter_rows(named=True):
                symbol = row["symbol"]
                status = "ENTRY_ATTEMPT"
                if symbol in state["holdings"] or symbol in entrants:
                    status = "OVERLAP_SKIP"
                elif len(entrants) >= capacity:
                    status = "CAPACITY_SKIP"
                else:
                    entrants.append(symbol)
                    expiry[symbol] = row["expiry_date"]
                decisions.append({**row, "decision": status})
        if expired or entrants:
            weights = portfolio_weights(state=state, date=date,
                opens=dict(today.select("symbol", "open").iter_rows()), dividends=dividends,
                expired=expired, entrants=entrants)
            state["pending"] = [{"as_of": str(date - dt.timedelta(days=1)), "execution_date": str(date),
                "symbol": s, "weight": w, "strategy": name, "strategy_version": "v1"}
                for s, w in weights.items()]
            missing = set(entrants) - today_symbols
            extra = [prior_closes[s] for s in missing if s in prior_closes]
            if extra:
                today = pl.concat([today, pl.DataFrame(extra, schema=bars.schema)])
        state, result = advance(date=date, state=state, bars=today, calendar=calendar,
            instruments=instruments, market_states=market_states, dividends=dividends, config=account)
        state["nav"][-1].update(position_count=len(state["holdings"]), delisting_writeoff=writeoff)
        trades.append(result.trades)
        rejected.append(result.rejections)
        for row in by_date.get(date, bars.head(0)).iter_rows(named=True):
            prior_closes[row["symbol"]] = row
    return (pl.DataFrame(state["nav"]).with_columns(pl.col("date").str.to_date()),
            pl.concat(trades, how="vertical_relaxed"), pl.concat(rejected, how="vertical_relaxed"),
            pl.DataFrame(decisions))
