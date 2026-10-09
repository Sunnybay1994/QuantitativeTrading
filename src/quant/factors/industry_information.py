"""Fixed industry-level monthly information signals, not stock-specific alpha.

Input is one observed stock per exact exchange month end. Industry labels must
already be joined to their dated membership, with taxonomy versions distinct.
No financial labels, target returns, data access or portfolio logic live here.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import polars as pl

SIGNALS = ("industry_momentum_6m", "industry_leader_return_1m")
CONTROL = "industry_return_1m"
MINIMUM_MEMBERS = 10
LEADER_FRACTION = 0.30
_KEYS = ["symbol", "trade_date"]


def _positive(x: object) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def _quote(row: dict) -> bool:
    return all(_positive(row.get(k)) for k in ("close", "adj_factor", "volume"))


def compute_industry_information(
    panel: pl.DataFrame, *, month_ends: tuple[dt.date, ...],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return stock signal rows and industry-month formation/coverage evidence.

Every industry's membership and market-value weights are frozen at the prior
month end, before any ending quote is examined. A missing endpoint invalidates
that portfolio instead of renormalizing its surviving members. All known
formation members must have positive finite market value, even if they would
not have entered the largest-30% portfolio. Returns at one month end cannot be
substituted for another month. The caller supplies complete exchange anchors.
"""
    columns = {*_KEYS, "close", "adj_factor", "volume", "total_market_value", "industry_l1"}
    if not columns <= set(panel.columns):
        raise ValueError("Industry information requires monthly quotes, capital and dated industry")
    if len(month_ends) < 2 or tuple(sorted(set(month_ends))) != month_ends:
        raise ValueError("Month ends must be unique and increasing")
    ordinals = [d.year * 12 + d.month for d in month_ends]
    if any(b - a != 1 for a, b in zip(ordinals, ordinals[1:])):
        raise ValueError("Month ends must include every calendar month")
    if panel.select(_KEYS).is_duplicated().any():
        raise ValueError("Duplicate stock month end")
    if not set(panel["trade_date"].to_list()) <= set(month_ends):
        raise ValueError("Unexpected non-anchor observation")
    months = {date: rows.to_dicts() for (date,), rows in panel.partition_by("trade_date", as_dict=True).items()}
    portfolio: dict[tuple[int, str], float | None] = {}
    diagnostics, output = [], []
    for index, day in enumerate(month_ends):
        if not index:
            continue
        prior = month_ends[index - 1]
        current = {r["symbol"]: r for r in months.get(day, [])}
        groups: dict[str, list[dict]] = {}
        for row in months.get(prior, []):
            industry = row["industry_l1"]
            if isinstance(industry, str) and industry and _quote(row):
                groups.setdefault(industry, []).append(row)
        leader_values, industry_values = {}, {}
        for industry, members in sorted(groups.items()):
            count = len(members)
            capital_valid = all(_positive(r["total_market_value"]) for r in members)
            row = dict(trade_date=day, formation_date=prior, industry_l1=industry,
                       formation_members=count, invalid_capital=sum(not _positive(r["total_market_value"]) for r in members),
                       leader_members=0, missing_endpoints=0, leader_missing_endpoints=0,
                       endpoint_weight_coverage=None, leader_endpoint_weight_coverage=None,
                       industry_return_1m=None, industry_leader_return_1m=None,
                       reason="insufficient_members" if count < MINIMUM_MEMBERS else "invalid_formation_capital")
            if count >= MINIMUM_MEMBERS and capital_valid:
                members.sort(key=lambda r: (-r["total_market_value"], r["symbol"]))
                n_leaders = math.ceil(LEADER_FRACTION * count)
                weights = np.array([r["total_market_value"] for r in members], dtype=float)
                # Normalize before multiplication, avoiding huge market-value sums.
                weights /= weights.max()
                changes = np.full(count, np.nan)
                for k, start in enumerate(members):
                    end = current.get(start["symbol"])
                    if end is not None and _quote(end):
                        change = ((end["close"] / start["close"])
                                  * (end["adj_factor"] / start["adj_factor"]) - 1.0)
                        if math.isfinite(change) and change > -1:
                            changes[k] = change
                valid = np.isfinite(changes)
                leaders_valid = valid[:n_leaders]
                row.update(leader_members=n_leaders, missing_endpoints=int((~valid).sum()),
                           leader_missing_endpoints=int((~leaders_valid).sum()),
                           endpoint_weight_coverage=float(weights[valid].sum() / weights.sum()),
                           leader_endpoint_weight_coverage=float(weights[:n_leaders][leaders_valid].sum() / weights[:n_leaders].sum()),
                           reason="complete" if valid.all() else "missing_frozen_member_endpoint")
                if valid.all():
                    row[CONTROL] = float(np.dot(weights / weights.sum(), changes))
                if leaders_valid.all():
                    row[SIGNALS[1]] = float(np.dot(weights[:n_leaders] / weights[:n_leaders].sum(), changes[:n_leaders]))
            portfolio[index, industry] = row[CONTROL]
            industry_values[industry] = row[CONTROL]
            leader_values[industry] = row[SIGNALS[1]]
            diagnostics.append(row)
        for symbol, current_row in sorted(current.items()):
            industry = current_row["industry_l1"]
            values = {name: None for name in (*SIGNALS, CONTROL)}
            if _quote(current_row) and isinstance(industry, str) and industry:
                values[CONTROL] = industry_values.get(industry)
                values[SIGNALS[1]] = leader_values.get(industry)
                past = [portfolio.get((j, industry)) for j in range(index - 5, index + 1)]
                if all(v is not None for v in past):
                    compounded = float(np.prod([1 + v for v in past]) - 1)
                    values[SIGNALS[0]] = compounded if math.isfinite(compounded) else None
            output.append(dict(symbol=symbol, trade_date=day, industry_l1=industry, **values))
    result_schema = {"symbol": pl.String, "trade_date": pl.Date, "industry_l1": pl.String,
                     **{k: pl.Float64 for k in (*SIGNALS, CONTROL)}}
    diagnostic_schema = {"trade_date": pl.Date, "formation_date": pl.Date, "industry_l1": pl.String,
                         **{k: pl.Int64 for k in ("formation_members", "invalid_capital", "leader_members", "missing_endpoints", "leader_missing_endpoints")},
                         **{k: pl.Float64 for k in ("endpoint_weight_coverage", "leader_endpoint_weight_coverage", CONTROL, SIGNALS[1])}, "reason": pl.String}
    return (pl.DataFrame(output, schema=result_schema).sort(_KEYS),
            pl.DataFrame(diagnostics, schema=diagnostic_schema).sort("trade_date", "industry_l1"))
