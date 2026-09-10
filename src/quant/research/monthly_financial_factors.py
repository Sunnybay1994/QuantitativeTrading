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
    daily_basic: pl.DataFrame | None = None,
) -> tuple[PITQualitySignalResult, dict[str, pl.DataFrame]]:
    """Read revision history through data APIs and compute sparse monthly signals."""
    if (settings["company_type"] != "1"
        or settings["signal_frequency"] != "completed_month_end"
        or settings["availability"] != "strictly_before_signal_date"
        or settings["missing_quarter"] != "null"
        or settings["allowed_report_types"] != ["1"]):
        raise ValueError("Unsupported financial factor configuration")
    histories: dict[str, pl.DataFrame] = {}
    roe_stability = settings.get("factor_family") == "quarterly_roe_stability"
    annual_cash = settings.get("factor_family") == "annual_cash_profitability"
    sue = settings.get("factor_family") == "sue8"
    growth = settings.get("factor_family") == "asset_growth"
    current_ratio = settings.get("factor_family") == "current_ratio"
    leverage = settings.get("factor_family") == "leverage"
    cash_yield = settings.get("factor_family") == "cash_yield"
    cash_roa = settings.get("factor_family") == "cash_roa"
    gross = settings.get("factor_family") == "gross_profitability"
    margin = settings.get("factor_family") == "gross_margin"
    revenue_growth = settings.get("factor_family") == "revenue_growth"
    profit_growth = settings.get("factor_family") == "profit_growth"
    revenue_acceleration = settings.get("factor_family") == "revenue_acceleration"
    profit_acceleration = settings.get("factor_family") == "profit_acceleration"
    datasets: tuple[FinancialFactorDataset, ...] = (
        ("cashflow",) if cash_yield else
        ("income",) if sue or margin or revenue_growth or profit_growth or profit_acceleration or revenue_acceleration
        else ("balancesheet",) if growth or leverage or current_ratio else
        ("cashflow", "balancesheet") if cash_roa else
        ("income", "balancesheet") if gross or roe_stability else ("income", "balancesheet", "cashflow")
    )
    for dataset in datasets:
        histories[dataset] = read_tushare_financial_history(
            data_root=data_root, query=TushareFinancialHistoryQuery(
                snapshot_id=settings["snapshot_id"], dataset=dataset,
                start_period=settings["history_start"], end_period=end,
                symbols=candidates,
                extra_fields=("depr_fa_coga_dpba", "c_pay_acq_const_fiolta") if annual_cash and dataset == "cashflow"
                else ("total_cur_assets", "total_cur_liab", "money_cap", "st_borr", "taxes_payable")
                if annual_cash and dataset == "balancesheet" else (("revenue",) if revenue_growth or revenue_acceleration else ("revenue", "oper_cost"))
                if (gross or margin or revenue_growth or revenue_acceleration) and dataset == "income"
                else ("total_liab",) if leverage else ("total_cur_assets", "total_cur_liab") if current_ratio else (),
            ),
        )
    if roe_stability:
        from quant.research.monthly_quarterly_roe_stability import build_monthly_quarterly_roe_stability

        return build_monthly_quarterly_roe_stability(
            income_history=histories["income"], balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if annual_cash:
        from quant.research.monthly_annual_cash_profitability import build_monthly_annual_cash_profitability

        return build_monthly_annual_cash_profitability(
            income_history=histories["income"], cash_history=histories["cashflow"],
            balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if cash_yield:
        from quant.research.monthly_cash_yield import build_monthly_cash_yield

        if daily_basic is None:
            raise ValueError("Cash yield requires signal-date daily basic")
        return build_monthly_cash_yield(
            cash_history=histories["cashflow"], daily_basic=daily_basic,
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if cash_roa:
        from quant.research.monthly_cash_roa import build_monthly_cash_roa

        return build_monthly_cash_roa(
            cash_history=histories["cashflow"], balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if current_ratio:
        from quant.research.monthly_current_ratio import build_monthly_current_ratio

        return build_monthly_current_ratio(
            balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if leverage:
        from quant.research.monthly_leverage import build_monthly_leverage

        return build_monthly_leverage(
            balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if revenue_acceleration:
        from quant.research.monthly_revenue_acceleration import build_monthly_revenue_acceleration

        return build_monthly_revenue_acceleration(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if profit_acceleration:
        from quant.research.monthly_profit_acceleration import build_monthly_profit_acceleration

        return build_monthly_profit_acceleration(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if profit_growth:
        from quant.research.monthly_profit_growth import build_monthly_profit_growth

        return build_monthly_profit_growth(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if revenue_growth:
        from quant.research.monthly_revenue_growth import build_monthly_revenue_growth

        return build_monthly_revenue_growth(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if margin:
        from quant.research.monthly_gross_margin import build_monthly_gross_margin

        return build_monthly_gross_margin(
            income_history=histories["income"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if gross:
        from quant.research.monthly_gross_profitability import build_monthly_gross_profitability

        return build_monthly_gross_profitability(
            income_history=histories["income"], balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end), candidate_symbols=candidates,
        ), histories
    if growth:
        from quant.research.monthly_asset_growth import build_monthly_asset_growth

        return build_monthly_asset_growth(
            balance_history=histories["balancesheet"],
            signal_dates=monthly_signal_sessions(sessions, start=start, end=end),
            candidate_symbols=candidates,
        ), histories
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
