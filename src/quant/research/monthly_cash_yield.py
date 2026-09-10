"""Monthly cash-flow yield with announcement lag and exact-date capitalization."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.cash_yield import compute_cash_yield, compute_ocf_ttm
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_cash_yield(
    *, cash_history: pl.DataFrame, daily_basic: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Latest invalid cash statements remain invalid instead of falling back."""
    frames, eligibility, quarantines = [], [], []
    name = "pit_cash_yield_ttm"
    for date in signal_dates:
        selected = select_pit_quality_revisions_as_of(
            cash_history, dataset="cashflow", as_of=date, allowed_report_types=("1",))
        latest = compute_ocf_ttm(selected.selected).sort("symbol", "end_date").group_by("symbol").tail(1)
        cross = pl.DataFrame({"symbol": candidate_symbols}).join(
            latest.select("symbol", pl.col("end_date").alias("financial_period_end"), "ocf_ttm"),
            on="symbol", how="left",
        ).with_columns(pl.lit(date).alias("trade_date"))
        cross = compute_cash_yield(cross, daily_basic.filter(pl.col("trade_date") == date))
        quarantine = selected.quarantined.with_columns(pl.lit(date).alias("as_of"),
                                                       pl.lit("cashflow").alias("dataset"))
        quarantines.append(quarantine)
        bad = quarantine.filter(pl.col("quarantine_reason").is_in(
            ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]))["symbol"].unique().to_list()
        cross = cross.with_columns(
            pl.when(pl.col("symbol").is_in(bad)).then(pl.lit("QUARANTINED"))
            .when(pl.col(name).is_finite().fill_null(False)).then(pl.lit("VALID"))
            .otherwise(pl.lit("MISSING_OR_INVALID_CASH_OR_MARKET_VALUE")).alias("status"),
        ).with_columns(pl.when(pl.col("status") == "VALID").then(pl.col(name)).otherwise(None).alias(name))
        frames.append(cross.drop("status"))
        eligibility.append(cross.select(pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
                                        pl.lit(name).alias("factor"), "status"))
    return PITQualitySignalResult(factors=pl.concat(frames).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how="diagonal_relaxed"))
