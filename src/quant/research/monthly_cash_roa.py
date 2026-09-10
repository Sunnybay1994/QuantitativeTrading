"""Monthly PIT cash return on assets values from cash-flow and balance-sheet histories."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.factors.cash_roa import compute_cash_roa
from quant.research.pit_quality_research import PITQualitySignalResult


def build_monthly_cash_roa(
    *, cash_history: pl.DataFrame, balance_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...], candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Only use revisions known before each signal; never reuse an older valid score."""
    frames, eligibility, quarantines = [], [], []
    name = "pit_cash_roa_ttm"
    for date in signal_dates:
        cash = select_pit_quality_revisions_as_of(cash_history, dataset="cashflow", as_of=date,
                                                   allowed_report_types=("1",))
        balance = select_pit_quality_revisions_as_of(balance_history, dataset="balancesheet", as_of=date,
                                                    allowed_report_types=("1",))
        latest = compute_cash_roa(cash.selected, balance.selected).sort(
            "symbol", "end_date"
        ).group_by("symbol").tail(1).select("symbol", pl.col("end_date").alias("financial_period_end"), name)
        cross = pl.DataFrame({"symbol": candidate_symbols}).join(latest, on="symbol", how="left")
        bad: set[str] = set()
        for dataset, selection in (("cashflow", cash), ("balancesheet", balance)):
            quarantine = selection.quarantined.with_columns(pl.lit(date).alias("as_of"),
                                                             pl.lit(dataset).alias("dataset"))
            quarantines.append(quarantine)
            conflicts = quarantine.filter(pl.col("quarantine_reason").is_in(
                ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]
            ))
            if dataset == "balancesheet":
                conflicts = conflicts.join(cross.select("symbol", "financial_period_end"), on="symbol", how="inner").filter(
                    (pl.col("end_date") == pl.col("financial_period_end"))
                    | (pl.col("end_date") == pl.col("financial_period_end").dt.offset_by("-1y")))
            bad.update(conflicts["symbol"].to_list())
        cross = cross.with_columns(pl.lit(date).alias("trade_date"),
            pl.when(pl.col("symbol").is_in(sorted(bad))).then(pl.lit("QUARANTINED"))
            .when(pl.col(name).is_finite().fill_null(False)).then(pl.lit("VALID"))
            .otherwise(pl.lit("MISSING_OR_INVALID_STATEMENTS")).alias("status"),
        ).with_columns(pl.when(pl.col("status") == "VALID").then(pl.col(name)).otherwise(None).alias(name))
        frames.append(cross.drop("status"))
        eligibility.append(cross.select(pl.col("trade_date").alias("as_of"), "symbol", "financial_period_end",
                                        pl.lit(name).alias("factor"), "status"))
    return PITQualitySignalResult(factors=pl.concat(frames).sort("trade_date", "symbol"),
        eligibility=pl.concat(eligibility), quarantined=pl.concat(quarantines, how="diagonal_relaxed"))
