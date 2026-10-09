"""Fixed B31 market checks and previous-quarter thresholds, without a portfolio.

Date-only disclosures are assumed available at announcement-day close. Names
are reconstructed effective intervals, not proof of original capture vintages;
known announcement dates are respected and missing name timing stays unknown.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Sequence
from typing import Any

import polars as pl

ELIGIBILITY_SCHEMA = {
    "expected_price_date": pl.Date, "price_date": pl.Date,
    "liquidity_window_start": pl.Date, "liquidity_session_count": pl.Int64,
    "liquidity20": pl.Float64, "valid_price_history": pl.Int64,
    "historical_name": pl.String, "name_start_date": pl.Date,
    "name_end_date": pl.Date, "name_ann_date": pl.Date,
    "name_status": pl.String, "name_timing_basis": pl.String,
    "financial_eligible": pl.Boolean, "market_eligible": pl.Boolean,
    "eligible": pl.Boolean, "eligibility_reason": pl.String,
    "threshold_quarter_start": pl.Date, "threshold_quarter_end": pl.Date,
    "threshold_count": pl.Int64, "threshold": pl.Float64,
    "selected": pl.Boolean, "selection_reason": pl.String,
}
_RISK_NAME = re.compile(r"^\*?S?ST|^PT|退", re.IGNORECASE)


def _check_schema(frame: pl.DataFrame, expected: dict[str, pl.DataType], label: str) -> None:
    if not isinstance(frame, pl.DataFrame) or any(
        frame.schema.get(key) != dtype for key, dtype in expected.items()
    ):
        raise ValueError(f"Invalid {label} schema")


def _validate(events: pl.DataFrame, bars: pl.DataFrame, names: pl.DataFrame,
              sessions: Sequence[dt.date]) -> None:
    _check_schema(events, {"symbol": pl.String, "announcement_date": pl.Date,
                          "end_date": pl.Date, "status": pl.String, "sue": pl.Float64}, "events")
    _check_schema(bars, {"symbol": pl.String, "trade_date": pl.Date}, "bars")
    _check_schema(names, {"symbol": pl.String, "name": pl.String,
                         "start_date": pl.Date, "end_date": pl.Date}, "names")
    if "ann_date" in names.columns and names.schema["ann_date"] != pl.Date:
        raise ValueError("Name ann_date must be Date")
    if any(not bars.schema.get(key, pl.Null).is_numeric() for key in ("close", "amount")):
        raise ValueError("Bars require numeric close and amount in CNY")
    if (not sessions or any(type(day) is not dt.date for day in sessions)
            or list(sessions) != sorted(set(sessions))):
        raise ValueError("Require nonempty ordered unique exchange sessions")
    if set(events.columns) & (set(ELIGIBILITY_SCHEMA) | {"_row_id", "_session", "_before"}):
        raise ValueError("Events already contain reserved eligibility columns")
    if events.select(pl.any_horizontal(pl.col("symbol", "announcement_date", "end_date").is_null()).any()).item():
        raise ValueError("Null event identity")
    if events.select(pl.struct("symbol", "announcement_date").is_duplicated().any()).item():
        raise ValueError("Duplicate first-disclosure event")


def _name_at(rows: list[dict[str, Any]], date: dt.date) -> dict[str, Any]:
    result = {"historical_name": None, "name_start_date": None, "name_end_date": None,
              "name_ann_date": None, "name_status": "UNKNOWN_NAME_COVERAGE",
              "name_timing_basis": "EFFECTIVE_INTERVAL_RECONSTRUCTION_NOT_ORIGINAL_VINTAGE"}
    known = [row for row in rows if row["start_date"] is not None and row["start_date"] <= date
             and (row["ann_date"] is None or row["ann_date"] <= date)]
    if not known:
        return result
    start = max(row["start_date"] for row in known)
    latest = [row for row in known if row["start_date"] == start]
    result["name_start_date"] = start
    if len(latest) != 1:
        result["name_status"] = "UNKNOWN_NAME_CONFLICT"
        return result
    row = latest[0]
    result.update(historical_name=row["name"], name_ann_date=row["ann_date"],
                  name_end_date=row["end_date"])
    if row["ann_date"] is None:
        result["name_status"] = "UNKNOWN_NAME_ANNOUNCEMENT"
    elif row["end_date"] is not None and row["end_date"] < date:
        result["name_status"] = "UNKNOWN_NAME_EXPIRED"
    elif row["name"] is None or not row["name"].strip():
        result["name_status"] = "UNKNOWN_NAME_VALUE"
    elif _RISK_NAME.search(row["name"].strip()):
        result["name_status"] = "RISK_NAME"
    else:
        result["name_status"] = "NORMAL"
    return result


def _previous_quarter(date: dt.date) -> tuple[dt.date, dt.date]:
    current = dt.date(date.year, 1 + 3 * ((date.month - 1) // 3), 1)
    end = current - dt.timedelta(days=1)
    return dt.date(end.year, 1 + 3 * ((end.month - 1) // 3), 1), end


def enrich_event_eligibility(
    *, events: pl.DataFrame, bars: pl.DataFrame, names: pl.DataFrame,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Preserve every event; apply the original 20m/20-day/120-close/90% rules.

    Bars must be unique symbol/trading-day rows with unadjusted close and CNY
    amount. Supply the full available prior history and an exchange calendar
    covering event dates (calendar dates may extend beyond the final price).
    Twenty-day amounts require all twenty exact exchange sessions, with zero
    amounts allowed but missing/nonfinite/negative amounts explicitly missing.
    The 120-close count is cumulative positive finite closes, not calendar age.

    A quarter's threshold uses ALL eligible finite SUE events in its previous
    natural quarter, including negative SUE, with >=100 observations and linear
    90th percentile. Only SUE>0 and SUE>=threshold are selected. No execution,
    liquidity participation, current-survivor filtering or return calculation.
    """
    _validate(events, bars, names, sessions)
    if events.is_empty():
        return events.with_columns([pl.lit(None, dtype=dtype).alias(key)
                                    for key, dtype in ELIGIBILITY_SCHEMA.items()])
    calendar = pl.DataFrame({"trade_date": sessions}, schema={"trade_date": pl.Date}).with_row_index(
        "_session"
    ).with_columns(pl.col("_session").cast(pl.Int64))
    relevant = bars.filter(
        (pl.col("trade_date") <= events["announcement_date"].max())
        & pl.col("symbol").is_in(events["symbol"].unique().implode())
    ).select("symbol", "trade_date", pl.col("close", "amount").cast(pl.Float64))
    if relevant.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("Duplicate symbol/day price rows")
    prices = relevant.join(calendar, on="trade_date", how="left", validate="m:1")
    if prices["_session"].null_count():
        raise ValueError("Price rows outside supplied exchange sessions")
    prices = prices.sort("symbol", "trade_date").with_columns(
        (pl.col("close").is_finite() & (pl.col("close") > 0)).fill_null(False).alias("_valid_close"),
        (pl.col("amount").is_finite() & (pl.col("amount") >= 0)).fill_null(False).alias("_valid_amount"),
    ).with_columns(
        pl.col("_valid_close").cast(pl.Int64).cum_sum().over("symbol").alias("valid_price_history"),
        pl.col("_valid_amount").cast(pl.Int64).cum_sum().over("symbol").alias("_amount_count"),
        pl.when(pl.col("_valid_amount")).then(pl.col("amount")).otherwise(0.)
        .cum_sum().over("symbol").alias("_amount_sum"),
        pl.when(pl.col("_valid_close")).then(pl.col("trade_date")).otherwise(None)
        .forward_fill().over("symbol").alias("price_date"),
    ).select("symbol", "_session", "valid_price_history", "_amount_count", "_amount_sum", "price_date")
    attached = (events.with_row_index("_row_id").sort("announcement_date")
        .join_asof(calendar.rename({"trade_date": "expected_price_date"}),
                   left_on="announcement_date", right_on="expected_price_date", check_sortedness=False)
        .with_columns((pl.col("_session") - 20).alias("_before")))
    # Prefix differences give the exact exchange-calendar window, including
    # absent price rows. Rolling over twenty stored bars would bridge suspensions.
    attached = attached.sort("symbol", "_session").join_asof(
        prices, on="_session", by="symbol", check_sortedness=False,
    ).join_asof(
        prices.select("symbol", pl.col("_session").alias("_before"),
                      pl.col("_amount_count").alias("_past_count"),
                      pl.col("_amount_sum").alias("_past_sum")),
        on="_before", by="symbol", check_sortedness=False,
    ).with_columns(
        (pl.col("_amount_count").fill_null(0) - pl.col("_past_count").fill_null(0))
        .alias("liquidity_session_count"),
        pl.col("valid_price_history").fill_null(0),
    ).with_columns(
        pl.when((pl.col("_session") >= 19) & (pl.col("liquidity_session_count") == 20))
        .then((pl.col("_amount_sum") - pl.col("_past_sum").fill_null(0.)) / 20.)
        .otherwise(None).alias("liquidity20"),
    )
    if "ann_date" not in names.columns:
        names = names.with_columns(pl.lit(None, dtype=pl.Date).alias("ann_date"))
    name_rows: dict[str, list[dict[str, Any]]] = {}
    for row in names.select("symbol", "name", "start_date", "end_date", "ann_date").unique().iter_rows(named=True):
        name_rows.setdefault(row["symbol"], []).append(row)
    additions = []
    for row in attached.sort("_row_id").iter_rows(named=True):
        name = _name_at(name_rows.get(row["symbol"], []), row["announcement_date"])
        reasons = []
        if row["_session"] is None:
            reasons.append("NO_PRIOR_EXCHANGE_SESSION")
        if row["announcement_date"] > sessions[-1]:
            reasons.append("CALENDAR_COVERAGE_UNKNOWN")
        if row["price_date"] is None:
            reasons.append("NO_VALID_CLOSE")
        elif row["price_date"] != row["expected_price_date"]:
            reasons.append("STALE_CLOSE")
        if row["_session"] is None or row["_session"] < 19:
            reasons.append("INSUFFICIENT_EXCHANGE_WINDOW")
        if row["liquidity_session_count"] != 20:
            reasons.append("INCOMPLETE_20_SESSION_AMOUNT")
        if row["liquidity20"] is not None and row["liquidity20"] < 20_000_000:
            reasons.append("MEAN_AMOUNT_BELOW_20M")
        if row["valid_price_history"] < 120:
            reasons.append("PRICE_HISTORY_BELOW_120")
        if name["name_status"] != "NORMAL":
            reasons.append(name["name_status"])
        market = not reasons
        financial = row["status"] == "VALID" and row["sue"] is not None and math.isfinite(row["sue"])
        if not financial:
            reasons.insert(0, "FINANCIAL_EVENT_NOT_VALID")
        previous_start, previous_end = _previous_quarter(row["announcement_date"])
        additions.append({
            "expected_price_date": row["expected_price_date"], "price_date": row["price_date"],
            "liquidity_window_start": sessions[row["_session"] - 19]
            if row["_session"] is not None and row["_session"] >= 19 else None,
            "liquidity_session_count": row["liquidity_session_count"],
            "liquidity20": row["liquidity20"], "valid_price_history": row["valid_price_history"],
            **name, "financial_eligible": financial, "market_eligible": market,
            "eligible": financial and market, "eligibility_reason": ";".join(reasons) or "ELIGIBLE",
            "threshold_quarter_start": previous_start, "threshold_quarter_end": previous_end,
        })
    enriched = events.hstack(pl.DataFrame(additions, schema={key: dtype for key, dtype
        in ELIGIBILITY_SCHEMA.items() if key not in {"threshold_count", "threshold", "selected", "selection_reason"}}))
    cohorts: dict[tuple[int, int], list[float]] = {}
    for row in enriched.filter(pl.col("eligible")).select("announcement_date", "sue").iter_rows(named=True):
        date = row["announcement_date"]
        cohorts.setdefault((date.year, (date.month - 1) // 3), []).append(row["sue"])
    cuts = {key: (len(values), pl.Series(values, dtype=pl.Float64).quantile(0.9, interpolation="linear")
                  if len(values) >= 100 else None) for key, values in cohorts.items()}
    decisions = []
    for row in enriched.iter_rows(named=True):
        previous = row["threshold_quarter_start"]
        count, cutoff = cuts.get((previous.year, (previous.month - 1) // 3), (0, None))
        selected = row["eligible"] and cutoff is not None and row["sue"] > 0 and row["sue"] >= cutoff
        reason = ("EVENT_INELIGIBLE" if not row["eligible"] else "PRIOR_QUARTER_BELOW_100"
                  if cutoff is None else "NONPOSITIVE_SUE" if row["sue"] <= 0 else
                  "BELOW_PREVIOUS_QUARTER_P90" if not selected else "SELECTED")
        decisions.append({"threshold_count": count, "threshold": cutoff,
                          "selected": selected, "selection_reason": reason})
    return enriched.hstack(pl.DataFrame(decisions, schema={key: ELIGIBILITY_SCHEMA[key] for key in
        ("threshold_count", "threshold", "selected", "selection_reason")}))
