"""Monthly builders for the pre-registered SUE family (A4)."""
from __future__ import annotations

import datetime as dt

import polars as pl

from quant.data.financial_clean import project_selected_financial_factor_frame
from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.earnings_surprise import compute_sue8
from quant.factors.sue_family import apply_time_decay, compute_rsue8, compute_sue_mad8
from quant.research.pit_quality_research import PITQualitySignalResult

_SCHEMA = {
    "symbol": pl.String,
    "trade_date": pl.Date,
    "financial_period_end": pl.Date,
}


def _latest_selected(income_history: pl.DataFrame, date: dt.date) -> pl.DataFrame:
    selection = select_pit_quality_revisions_as_of(
        income_history, dataset="income", as_of=date, allowed_report_types=("1",),
        history_quarters=14,
    )
    return project_selected_financial_factor_frame(selection.selected, dataset="income"), selection


def _announce_by_period(selection) -> pl.DataFrame:
    """PIT selection keeps available_date; factor projection intentionally drops it."""
    frame = selection.selected
    if "available_date" not in frame.columns:
        raise ValueError("PIT selection lacks available_date for SUE decay")
    symbol = (
        pl.col("symbol") if "symbol" in frame.columns
        else pl.col("ts_code").alias("symbol")
    )
    end = pl.col("end_date")
    if frame.schema["end_date"] == pl.String:
        end = end.str.to_date("%Y%m%d", strict=False)
    available = pl.col("available_date")
    if frame.schema["available_date"] == pl.String:
        available = available.str.to_date("%Y%m%d", strict=False)
    return (
        frame.select(symbol, end.alias("end_date"), available.alias("available_date"))
        .unique(subset=["symbol", "end_date"], keep="last")
    )


def _cross(symbols: tuple[str, ...], latest: pl.DataFrame, date: dt.date, name: str) -> pl.DataFrame:
    return (
        pl.DataFrame({"symbol": list(symbols)})
        .join(latest, on="symbol", how="left")
        .with_columns(pl.lit(date).alias("trade_date"))
        .select("symbol", "trade_date", "financial_period_end", name)
    )


def build_monthly_sue_decay(
    *,
    income_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
    tau: int,
) -> PITQualitySignalResult:
    name = f"sue_decay_tau{tau}"
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        selected, selection = _latest_selected(income_history, date)
        scored = compute_sue8(selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        # Projection strips available_date; take it from the PIT selection view.
        scored = scored.join(
            _announce_by_period(selection), on=["symbol", "end_date"], how="left", validate="1:1",
        )
        scored = apply_time_decay(
            scored.rename({"end_date": "financial_period_end"}),
            signal_date=date,
            sue_col="pit_sue8",
            taus=(tau,),
        ).select("symbol", "financial_period_end", name)
        cross = _cross(candidate_symbols, scored, date, name)
        factors.append(cross)
        eligibility.append(cross.select(
            pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
            pl.lit(name).alias("factor"),
            pl.when(pl.col(name).is_finite()).then(pl.lit("VALID")).otherwise(pl.lit("MISSING")).alias("status"),
        ))
        quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias("as_of")))
    return PITQualitySignalResult(
        factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility),
        quarantined=pl.concat(quarantines, how="diagonal_relaxed"),
    )


def build_monthly_sue_decay_tau20(**kwargs) -> PITQualitySignalResult:
    return build_monthly_sue_decay(**kwargs, tau=20)


def build_monthly_sue_decay_tau40(**kwargs) -> PITQualitySignalResult:
    return build_monthly_sue_decay(**kwargs, tau=40)


def build_monthly_sue_mad8(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    name = "sue_mad8"
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        selected, selection = _latest_selected(income_history, date)
        latest = compute_sue_mad8(selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        latest = latest.select("symbol", pl.col("end_date").alias("financial_period_end"), name)
        cross = _cross(candidate_symbols, latest, date, name)
        factors.append(cross)
        eligibility.append(cross.select(
            pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
            pl.lit(name).alias("factor"),
            pl.when(pl.col(name).is_finite()).then(pl.lit("VALID")).otherwise(pl.lit("MISSING")).alias("status"),
        ))
        quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias("as_of")))
    return PITQualitySignalResult(
        factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility),
        quarantined=pl.concat(quarantines, how="diagonal_relaxed"),
    )


def build_monthly_rsue8(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    name = "rsue8"
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        selected, selection = _latest_selected(income_history, date)
        if "revenue" not in selected.columns:
            empty = pl.DataFrame({
                "symbol": list(candidate_symbols),
                "trade_date": [date] * len(candidate_symbols),
                "financial_period_end": [None] * len(candidate_symbols),
                name: [None] * len(candidate_symbols),
            }).cast({"financial_period_end": pl.Date, name: pl.Float64})
            factors.append(empty)
            eligibility.append(empty.select(
                pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
                pl.lit(name).alias("factor"), pl.lit("SAMPLE_INSUFFICIENT").alias("status"),
            ))
            quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias("as_of")))
            continue
        latest = compute_rsue8(selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        latest = latest.select("symbol", pl.col("end_date").alias("financial_period_end"), name)
        cross = _cross(candidate_symbols, latest, date, name)
        factors.append(cross)
        eligibility.append(cross.select(
            pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
            pl.lit(name).alias("factor"),
            pl.when(pl.col(name).is_finite()).then(pl.lit("VALID")).otherwise(pl.lit("MISSING")).alias("status"),
        ))
        quarantines.append(selection.quarantined.with_columns(pl.lit(date).alias("as_of")))
    return PITQualitySignalResult(
        factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility),
        quarantined=pl.concat(quarantines, how="diagonal_relaxed"),
    )


def build_monthly_sue_prelim(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """S4 placeholder: prelim surprise requires statement_event_dates coverage.

    Until prelim events are wired with unique PIT surprise values, every row is
    explicitly SAMPLE_INSUFFICIENT (not zero-filled).
    """
    name = "sue_prelim"
    factors, eligibility = [], []
    for date in signal_dates:
        frame = pl.DataFrame({
            "symbol": list(candidate_symbols),
            "trade_date": [date] * len(candidate_symbols),
            "financial_period_end": [None] * len(candidate_symbols),
            name: [None] * len(candidate_symbols),
        }).cast({"financial_period_end": pl.Date, name: pl.Float64})
        factors.append(frame)
        eligibility.append(frame.select(
            pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
            pl.lit(name).alias("factor"), pl.lit("SAMPLE_INSUFFICIENT").alias("status"),
        ))
    empty_q = pl.DataFrame({"symbol": [], "as_of": [], "quarantine_reason": []}).cast({
        "symbol": pl.String, "as_of": pl.Date, "quarantine_reason": pl.String,
    })
    return PITQualitySignalResult(
        factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility),
        quarantined=empty_q,
    )
