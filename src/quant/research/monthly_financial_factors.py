"""Published PIT financial cross-sections for the monthly Top50 experiments."""

import datetime as dt
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.financial_clean import FinancialFactorDataset
from quant.data.financial_repository import (
    TushareFinancialHistoryQuery, read_tushare_financial_history,
)
from quant.research.pit_quality_research import (
    PITQualitySignalResult, build_pit_quality_signal_values, monthly_signal_sessions,
)


def read_monthly_financial_factors(
    *, data_root: Path, settings: dict[str, Any], candidates: tuple[str, ...],
    sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
) -> tuple[PITQualitySignalResult, dict[str, pl.DataFrame]]:
    """Read revision history through data APIs and compute sparse monthly signals."""
    if (settings["company_type"] != "1"
        or settings["signal_frequency"] != "completed_month_end"
        or settings["availability"] != "strictly_before_signal_date"
        or settings["missing_quarter"] != "null"
        or settings["allowed_report_types"] != ["1"]):
        raise ValueError("Unsupported financial factor configuration")
    histories: dict[str, pl.DataFrame] = {}
    sue = settings.get("factor_family") == "sue8"
    datasets: tuple[FinancialFactorDataset, ...] = ("income",) if sue else ("income", "balancesheet", "cashflow")
    for dataset in datasets:
        histories[dataset] = read_tushare_financial_history(
            data_root=data_root, query=TushareFinancialHistoryQuery(
                snapshot_id=settings["snapshot_id"], dataset=dataset,
                start_period=settings["history_start"], end_period=end,
                symbols=candidates,
            ),
        )
    if sue:
        from quant.research.monthly_sue import build_monthly_sue

        return build_monthly_sue(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end),
            candidate_symbols=candidates,
        ), histories
    signals = build_pit_quality_signal_values(
        income_history=histories["income"], balance_history=histories["balancesheet"],
        cash_history=histories["cashflow"],
        signal_dates=monthly_signal_sessions(sessions, start=start, end=end),
        candidate_symbols=candidates, allowed_report_types=("1",),
    )
    return signals, histories
