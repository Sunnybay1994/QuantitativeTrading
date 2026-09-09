"""Monthly revenue growth with statement revisions selected before each signal."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.revenue_growth import compute_revenue_growth
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_revenue_growth(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Never substitute an older valid score for invalid latest information."""
    frames, eligibility, quarantines = [], [], []
    name = "pit_revenue_growth_ttm"
    for date in signal_dates:
        income = select_pit_quality_revisions_as_of(
            income_history, dataset="income", as_of=date, allowed_report_types=("1",),
            history_quarters=9)
        latest = compute_revenue_growth(income.selected).sort("symbol", "end_date").group_by(
            "symbol").tail(1).select("symbol", pl.col("end_date").alias("financial_period_end"), name)
        cross = pl.DataFrame({"symbol": candidate_symbols}).join(latest, on="symbol", how="left")
        quarantine = income.quarantined.with_columns(
            pl.lit(date).alias("as_of"), pl.lit("income").alias("dataset"))
        quarantines.append(quarantine)
        bad = quarantine.filter(pl.col("quarantine_reason").is_in(
            ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]))["symbol"].to_list()
        cross = cross.with_columns(
            pl.lit(date).alias("trade_date"),
            pl.when(pl.col("symbol").is_in(bad)).then(pl.lit("QUARANTINED"))
            .when(pl.col(name).is_finite().fill_null(False)).then(pl.lit("VALID"))
            .otherwise(pl.lit("MISSING_OR_INVALID_STATEMENTS")).alias("status"),
        ).with_columns(pl.when(pl.col("status") == "VALID").then(pl.col(name)).otherwise(None).alias(name))
        frames.append(cross.drop("status"))
        eligibility.append(cross.select(pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
                                        pl.lit(name).alias("factor"), "status"))
    return PITQualitySignalResult(factors=pl.concat(frames).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how="diagonal_relaxed"))
