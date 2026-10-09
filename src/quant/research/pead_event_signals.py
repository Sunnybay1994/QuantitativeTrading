"""First-disclosure financial events using the existing point-in-time SUE context.

This produces announcement signals only. A date-only announcement is usable
after that date, not at its open; execution eligibility belongs to a later stage.
Available dates describe the supplied history, not proof of original vintages.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable
from typing import Any

import polars as pl

from quant.research.monthly_sue_context_v2 import NAME, build_monthly_sue_context_v2

EVENT_SCHEMA = {
    "symbol": pl.String,
    "announcement_date": pl.Date,
    "end_date": pl.Date,
    "sue": pl.Float64,
    "status": pl.String,
    "reason": pl.String,
    "disclosure_delay_days": pl.Int64,
    "context_as_of": pl.Date,
    "financial_period_end": pl.Date,
    "latest_report_end": pl.Date,
    "latest_comp_type": pl.String,
    "context_status": pl.String,
}
_HISTORY_SCHEMA = {
    "symbol": pl.String,
    "ann_date": pl.Date,
    "f_ann_date": pl.Date,
    "available_date": pl.Date,
    "end_date": pl.Date,
    "report_type": pl.String,
    "comp_type": pl.String,
    "update_flag": pl.String,
}


def _validate(history: pl.DataFrame, start: dt.date, end: dt.date) -> None:
    if type(start) is not dt.date or type(end) is not dt.date or start > end:
        raise ValueError("Require date start <= end")
    if not isinstance(history, pl.DataFrame) or any(
        history.schema.get(column) != dtype for column, dtype in _HISTORY_SCHEMA.items()
    ) or "ts_code" in history.columns:
        raise ValueError("Require normalized financial income history schema")
    # A missing event key cannot be assigned an announcement; do not silently
    # lose such records or replace missing publication dates with report dates.
    invalid = history.filter(pl.col("report_type") == "1").filter(
        pl.col("symbol").is_null() | (pl.col("symbol").str.len_chars() == 0)
        | pl.col("end_date").is_null() | pl.col("available_date").is_null()
    )
    if not invalid.is_empty():
        raise ValueError("Type-1 reports require symbol, end_date and available_date")


def _event_result(
    row: dict[str, Any], context: dict[str, Any], value: float | None,
) -> dict[str, Any]:
    context_status = context["status"]
    row.update({
        "financial_period_end": context["financial_period_end"],
        "latest_report_end": context["latest_report_end"],
        "latest_comp_type": context["latest_comp_type"],
        "context_status": context_status,
        "reason": context["reason"],
        "status": "MISSING",
    })
    if context["latest_report_end"] is not None and context["latest_report_end"] != row["end_date"]:
        row.update(status="NOT_APPLICABLE", reason="EVENT_PERIOD_NOT_LATEST_DISCLOSED_REPORT")
    elif context_status == "CONTEXT_NON_INDUSTRIAL":
        row["status"] = "NOT_APPLICABLE"
    elif context_status in {"QUARANTINED", "CONTEXT_AMBIGUOUS"}:
        row["status"] = "QUARANTINED"
    elif context_status == "VALID":
        if context["financial_period_end"] != row["end_date"]:
            row["reason"] = "EVENT_PERIOD_DIFFERS_FROM_COMPUTED_FINANCIAL_PERIOD"
        elif value is None or not math.isfinite(value):
            row["reason"] = "NONFINITE_CONTEXT_SUE"
        else:
            row.update(status="VALID", sue=value, reason="SUE_FIRST_DISCLOSURE_CONTEXT_VALID")
    return row


def build_financial_events(
    history: pl.DataFrame,
    start: dt.date,
    end: dt.date,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> pl.DataFrame:
    """Freeze SUE at each type-1 period's first available date, inclusively.

    First dates are found before applying the requested date window. Revisions
    never open another event for that period. Simultaneous first announcements
    retain only the newest period, with no company-type or active-stock filter.
    Disclosure delays outside 0..180 days remain NOT_APPLICABLE rows. Other
    invalid/missing contexts remain visible and always have a null score.

    Context V2 receives announcement + 1 day and selects strictly earlier
    publications. This includes the first publication day but excludes future
    revisions. All economic fields are preserved for revision-conflict checks.
    progress, when supplied, receives one dictionary per announcement date.
    """
    _validate(history, start, end)
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable or None")
    events = (
        history.filter(pl.col("report_type") == "1")
        .group_by("symbol", "end_date")
        .agg(pl.col("available_date").min().alias("announcement_date"))
        .filter(pl.col("announcement_date").is_between(start, end, closed="both"))
        .group_by("symbol", "announcement_date")
        .agg(pl.col("end_date").max())
        .with_columns(
            (pl.col("announcement_date") - pl.col("end_date"))
            .dt.total_days().alias("disclosure_delay_days"),
        )
        .sort("announcement_date", "symbol")
    )
    if events.is_empty():
        return pl.DataFrame(schema=EVENT_SCHEMA)
    if events["announcement_date"].max() == dt.date.max:
        raise ValueError("Announcement date must allow next-day context")
    # The history is partitioned once. Each date batch reads only its event
    # symbols, retaining every report type and company type in their history.
    histories = history.partition_by("symbol", as_dict=True)
    batches = events.partition_by("announcement_date", maintain_order=True)
    results: list[dict[str, Any]] = []
    for batch_index, batch in enumerate(batches, start=1):
        date = batch["announcement_date"][0]
        as_of = date + dt.timedelta(days=1)
        eligible = batch.filter(pl.col("disclosure_delay_days").is_between(0, 180))
        contexts: dict[str, dict[str, Any]] = {}
        values: dict[str, float | None] = {}
        if not eligible.is_empty():
            symbols = tuple(eligible["symbol"].to_list())
            known = pl.concat([histories[(symbol,)] for symbol in symbols]).filter(
                pl.col("available_date") < as_of
            )
            context = build_monthly_sue_context_v2(
                income_history=known, signal_dates=(as_of,), candidate_symbols=symbols,
            )
            contexts = {row["symbol"]: row for row in context.eligibility.iter_rows(named=True)}
            values = dict(context.factors.select("symbol", NAME).iter_rows())
            if (len(contexts) != len(symbols) or len(values) != len(symbols)
                    or set(contexts) != set(symbols) or set(values) != set(symbols)):
                raise ValueError("Incomplete SUE context batch")
        batch_results = []
        for event in batch.iter_rows(named=True):
            row = dict.fromkeys(EVENT_SCHEMA)
            row.update(event, context_as_of=as_of, status="NOT_APPLICABLE",
                       reason="DISCLOSURE_DELAY_OUTSIDE_0_180")
            if 0 <= event["disclosure_delay_days"] <= 180:
                row = _event_result(row, contexts[event["symbol"]], values[event["symbol"]])
            batch_results.append(row)
        results.extend(batch_results)
        if progress is not None:
            progress({
                "announcement_date": date.isoformat(), "completed_dates": batch_index,
                "total_dates": len(batches), "events": len(batch_results),
                "valid_events": sum(row["status"] == "VALID" for row in batch_results),
            })
    return pl.DataFrame(results, schema=EVENT_SCHEMA).sort("announcement_date", "symbol")
