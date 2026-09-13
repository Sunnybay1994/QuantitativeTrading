"""Monthly inventory expansion from strictly prior industrial statements."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.inventory_expansion import compute_inventory_expansion
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_inventory_expansion(
    *, balance_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Use latest known period; quarantine relevant conflicts without older fallback."""
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        selection = select_pit_quality_revisions_as_of(
            balance_history, dataset="balancesheet", as_of=date, allowed_report_types=("1",),
        )
        selected = selection.selected
        latest = compute_inventory_expansion(selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        latest = latest.select("symbol", pl.col("end_date").alias("financial_period_end"), "pit_inventory_expansion_yoy")
        cross = pl.DataFrame({"symbol": candidate_symbols}).join(latest, on="symbol", how="left")
        quarantine = selection.quarantined.with_columns(pl.lit(date).alias("as_of"))
        quarantines.append(quarantine)
        symbol_col = "symbol" if "symbol" in quarantine.columns else "ts_code"
        conflicts = quarantine.filter(pl.col("quarantine_reason") == "LATEST_REVISION_CONFLICT")
        if not conflicts.is_empty():
            # A conflict at/after the chosen period must not cause fallback;
            # a conflict at the denominator period also invalidates the factor.
            relevant = conflicts.select(pl.col(symbol_col).alias("symbol"),
                pl.col("end_date").alias("conflict_end")).join(
                    cross.select("symbol", "financial_period_end"), on="symbol", how="inner",
                ).filter(
                    pl.col("financial_period_end").is_null()
                    | (pl.col("conflict_end") >= pl.col("financial_period_end"))
                    | (pl.col("conflict_end") == pl.col("financial_period_end").dt.offset_by("-1y"))
                )["symbol"].unique().to_list()
        else:
            relevant = []
        cross = cross.with_columns(
            pl.lit(date).alias("trade_date"),
            pl.when(pl.col("symbol").is_in(relevant)).then(pl.lit("QUARANTINED"))
            .when(pl.col("pit_inventory_expansion_yoy").is_finite().fill_null(False)).then(pl.lit("VALID"))
            .otherwise(pl.lit("MISSING_OR_INVALID_INVENTORY_OR_ASSETS")).alias("status"),
        ).with_columns(
            pl.when(pl.col("status") == "VALID").then(pl.col("pit_inventory_expansion_yoy"))
            .otherwise(None).alias("pit_inventory_expansion_yoy")
        )
        factors.append(cross.drop("status"))
        eligibility.append(cross.select(pl.col("trade_date").alias("as_of"), "symbol",
            "financial_period_end", pl.lit("pit_inventory_expansion_yoy").alias("factor"), "status"))
    return PITQualitySignalResult(factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how="diagonal_relaxed"))
