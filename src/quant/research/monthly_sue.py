"""Monthly earnings surprises using only prior-announced revision chains."""

import datetime as dt

import polars as pl

from quant.data.financial_clean import project_selected_financial_factor_frame
from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.earnings_surprise import compute_sue8
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_sue(
    *, income_history: pl.DataFrame, signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Keep the latest period even when invalid; never fall back to an older score."""
    factors, eligibility, quarantines = [], [], []
    for date in signal_dates:
        selection = select_pit_quality_revisions_as_of(
            income_history, dataset="income", as_of=date, allowed_report_types=("1",),
            history_quarters=14,
        )
        selected = project_selected_financial_factor_frame(selection.selected, dataset="income")
        latest = compute_sue8(selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        latest = latest.select("symbol", pl.col("end_date").alias("financial_period_end"), "pit_sue8")
        cross = pl.DataFrame({"symbol": candidate_symbols}).join(latest, on="symbol", how="left")
        quarantine = selection.quarantined.with_columns(pl.lit(date).alias("as_of"))
        quarantines.append(quarantine)
        symbol_col = "symbol" if "symbol" in quarantine.columns else "ts_code"
        conflicts = quarantine.filter(pl.col("quarantine_reason").is_in(
            ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]
        ))[symbol_col].unique().to_list()
        cross = cross.with_columns(
            pl.lit(date).alias("trade_date"),
            pl.when(pl.col("symbol").is_in(conflicts)).then(pl.lit("QUARANTINED"))
            .when(pl.col("pit_sue8").is_finite().fill_null(False)).then(pl.lit("VALID"))
            .otherwise(pl.lit("MISSING_OR_ZERO_VARIANCE")).alias("status"),
        ).with_columns(
            pl.when(pl.col("status") == "VALID").then(pl.col("pit_sue8"))
            .otherwise(None).alias("pit_sue8")
        )
        factors.append(cross.drop("status"))
        eligibility.append(cross.select(
            pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
            pl.lit("pit_sue8").alias("factor"), "status",
        ))
    return PITQualitySignalResult(
        factors=pl.concat(factors).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility),
        quarantined=pl.concat(quarantines, how="diagonal_relaxed"),
    )
