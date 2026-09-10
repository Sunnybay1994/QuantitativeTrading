"""PIT selection for the fixed net-margin, turnover and cash/debt ratios."""

import datetime as dt
from typing import cast

import polars as pl

from quant.data.financial_pit import select_pit_quality_revisions_as_of
from quant.data.financial_clean import FinancialFactorDataset
from quant.factors.financial_ratios import compute_net_margin, compute_asset_turnover, compute_cash_to_liabilities
from quant.research.financial_observations import STRUCTURAL


RATIO_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "pit_net_margin_ttm": {"income": ("n_income", "revenue")},
    "pit_asset_turnover_ttm": {"income": ("revenue",), "balancesheet": ("total_assets",)},
    "pit_cash_to_liabilities_ttm": {"cashflow": ("n_cashflow_act",), "balancesheet": ("total_liab",)},
}


def ratio_snapshot(
    name: str, histories: dict[str, pl.DataFrame], date: dt.date, symbols: tuple[str, ...],
) -> pl.DataFrame:
    selections = {table: select_pit_quality_revisions_as_of(frame.filter(pl.col("symbol").is_in(symbols)),
        dataset=cast(FinancialFactorDataset, table), as_of=date, allowed_report_types=("1",)) for table, frame in histories.items()}
    if name == "pit_net_margin_ttm":
        values = compute_net_margin(selections["income"].selected)
    elif name == "pit_asset_turnover_ttm":
        values = compute_asset_turnover(selections["income"].selected, selections["balancesheet"].selected)
    elif name == "pit_cash_to_liabilities_ttm":
        values = compute_cash_to_liabilities(selections["cashflow"].selected, selections["balancesheet"].selected)
    else:
        raise ValueError(f"Unknown financial ratio: {name}")
    latest = values.sort("symbol", "end_date").group_by("symbol").tail(1).select("symbol", name)
    bad = set()
    for table, selection in selections.items():
        if table != "balancesheet":
            bad.update(selection.quarantined.filter(pl.col("quarantine_reason").is_in(
                ["LATEST_REVISION_CONFLICT", "REVISION_CHAIN_CONFLICT"]))["symbol"].to_list())
    return pl.DataFrame({"symbol": symbols}).join(latest, on="symbol", how="left").with_columns(
        pl.lit(date).alias("trade_date"),
        pl.when(~pl.col("symbol").is_in(sorted(bad))).then(pl.col(name)).otherwise(None).alias(name))


def ratio_histories(name: str, histories: dict[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    return {table: histories[table].select(*STRUCTURAL, *columns) for table, columns in RATIO_FIELDS[name].items()}
