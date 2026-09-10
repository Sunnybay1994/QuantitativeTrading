"""Financial observations whose daily outputs also depend on price or peer ranks."""

import datetime as dt

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of, select_pit_quality_revisions_as_of
from quant.data.financial_clean import FinancialFactorDataset
from quant.factors.cash_yield import compute_ocf_ttm
from quant.factors.annual_profitability import COMPONENTS
from quant.research.monthly_annual_profitability import build_monthly_annual_profitability
from quant.research.financial_observations import STRUCTURAL, scoped_histories, ANNUAL_CASH_FIELDS


Z_FIELDS: dict[FinancialFactorDataset, tuple[str, ...]] = {"income": ("ebit", "revenue"),
            "balancesheet": ("total_assets", "total_cur_assets", "total_cur_liab", "surplus_rese", "undistr_porfit")}
Z_COLUMNS = tuple(name for columns in Z_FIELDS.values() for name in columns)
PROFITABILITY_NAMES = ("pit_annual_gpoa", "pit_annual_roe", "pit_annual_roa",
                       "pit_annual_gmar", "pit_annual_low_accruals", "pit_annual_profitability")


def cash_flow_snapshot(histories: dict[str, pl.DataFrame], date: dt.date, symbols: tuple[str, ...]) -> pl.DataFrame:
    cash = scoped_histories(histories, {"cashflow": ()})["cashflow"].filter(pl.col("symbol").is_in(symbols))
    selection = select_pit_quality_revisions_as_of(cash, dataset="cashflow", as_of=date,
                                                  allowed_report_types=("1",))
    latest = compute_ocf_ttm(selection.selected).sort("symbol", "end_date").group_by("symbol").tail(1)
    bad = selection.quarantined.filter(pl.col("quarantine_reason").is_in(
        ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]))["symbol"].unique().to_list()
    return pl.DataFrame({"symbol": symbols}).join(latest.select("symbol", "ocf_ttm"), on="symbol", how="left").with_columns(
        pl.lit(date).alias("trade_date"),
        pl.when(~pl.col("symbol").is_in(bad)).then(pl.col("ocf_ttm")).otherwise(None).alias("ocf_ttm"))


def annual_z_snapshot(histories: dict[str, pl.DataFrame], date: dt.date, symbols: tuple[str, ...]) -> pl.DataFrame:
    annual = (pl.col("end_date").dt.month() == 12) & (pl.col("end_date").dt.day() == 31)
    frames = {table: histories[table].filter(annual & (pl.col("report_type") == "1")
        & (pl.col("comp_type") == "1") & pl.col("symbol").is_in(symbols)).select(*STRUCTURAL, *columns)
        for table, columns in Z_FIELDS.items()}
    anchors = frames["income"].filter(pl.col("available_date") < date).group_by("symbol").agg(pl.col("end_date").max())
    cross = pl.DataFrame({"symbol": symbols}).join(anchors, on="symbol", how="left")
    for table, columns in Z_FIELDS.items():
        selected = select_financial_revisions_as_of(frames[table], dataset=table, as_of=date).selected
        cross = cross.join(selected.select("symbol", "end_date", *columns), on=["symbol", "end_date"],
                           how="left", validate="m:1")
    return cross.rename({"end_date": "financial_period_end"}).with_columns(pl.lit(date).alias("trade_date"))


def annual_profitability_snapshot(
    histories: dict[str, pl.DataFrame], date: dt.date, symbols: tuple[str, ...],
) -> pl.DataFrame:
    extras = {**ANNUAL_CASH_FIELDS, "income": ("revenue", "oper_cost")}
    frames = {table: frame.filter(pl.col("symbol").is_in(symbols))
              for table, frame in scoped_histories(histories, extras).items()}
    result = build_monthly_annual_profitability(income_history=frames["income"],
        cash_history=frames["cashflow"], balance_history=frames["balancesheet"],
        signal_dates=(date,), candidate_symbols=symbols).factors
    # Keep raw components; the full daily cross-section determines the rank score.
    return result.select("symbol", "trade_date", "financial_period_end", *COMPONENTS)
