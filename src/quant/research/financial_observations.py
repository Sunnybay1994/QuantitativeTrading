"""Existing financial formula families with their original revision field scopes."""

import datetime as dt
from collections.abc import Callable

import polars as pl

from quant.research.monthly_annual_cash_profitability import build_monthly_annual_cash_profitability
from quant.research.monthly_asset_growth import build_monthly_asset_growth
from quant.research.monthly_cash_roa import build_monthly_cash_roa
from quant.research.monthly_current_ratio import build_monthly_current_ratio
from quant.research.monthly_debt_ebitda import build_monthly_debt_ebitda
from quant.research.monthly_gross_margin import build_monthly_gross_margin
from quant.research.monthly_gross_profitability import build_monthly_gross_profitability
from quant.research.monthly_inventory_expansion import build_monthly_inventory_expansion
from quant.research.monthly_leverage import build_monthly_leverage
from quant.research.monthly_profit_acceleration import build_monthly_profit_acceleration
from quant.research.monthly_profit_growth import build_monthly_profit_growth
from quant.research.monthly_quarterly_roe_stability import build_monthly_quarterly_roe_stability
from quant.research.monthly_revenue_acceleration import build_monthly_revenue_acceleration
from quant.research.monthly_revenue_growth import build_monthly_revenue_growth
from quant.research.monthly_sue import build_monthly_sue
from quant.research.monthly_sue_context_v2 import build_monthly_sue_context_v2
from quant.research.pit_quality_research import PITQualitySignalResult


STRUCTURAL = ("symbol", "ann_date", "f_ann_date", "available_date", "end_date",
              "report_type", "comp_type", "update_flag", "source")
BASE_FIELDS = {"income": ("n_income", "n_income_attr_p"),
               "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int"),
               "cashflow": ("n_cashflow_act",), "fina_indicator": ("interestdebt", "ebitda")}
ARGUMENTS = {"income": "income_history", "balancesheet": "balance_history", "cashflow": "cash_history",
             "fina_indicator": "indicator_history"}
ANNUAL_CASH_FIELDS = {"income": (), "cashflow": ("depr_fa_coga_dpba", "c_pay_acq_const_fiolta"),
                     "balancesheet": ("total_cur_assets", "total_cur_liab", "money_cap", "st_borr", "taxes_payable")}

# Formula callable, extra input columns, maximum report age in calendar months.
DIRECT: dict[str, tuple[Callable[..., PITQualitySignalResult], dict[str, tuple[str, ...]], int | None]] = {
    "pit_cash_roa_ttm": (build_monthly_cash_roa, {"cashflow": (), "balancesheet": ()}, None),
    "pit_gross_profitability_ttm": (build_monthly_gross_profitability,
                                   {"income": ("revenue", "oper_cost"), "balancesheet": ()}, None),
    "pit_gross_margin_ttm": (build_monthly_gross_margin, {"income": ("revenue", "oper_cost")}, None),
    "pit_inventory_expansion_yoy": (build_monthly_inventory_expansion, {"balancesheet": ("inventories",)}, None),
    "pit_asset_growth_yoy": (build_monthly_asset_growth, {"balancesheet": ()}, None),
    "pit_current_ratio": (build_monthly_current_ratio, {"balancesheet": ("total_cur_assets", "total_cur_liab")}, None),
    "pit_liabilities_to_assets": (build_monthly_leverage, {"balancesheet": ("total_liab",)}, None),
    "pit_profit_growth_ttm": (build_monthly_profit_growth, {"income": ()}, None),
    "pit_profit_acceleration": (build_monthly_profit_acceleration, {"income": ()}, None),
    "pit_revenue_growth_ttm": (build_monthly_revenue_growth, {"income": ("revenue",)}, None),
    "pit_revenue_acceleration": (build_monthly_revenue_acceleration, {"income": ("revenue",)}, None),
    "pit_sue8": (build_monthly_sue, {"income": ()}, None),
    "pit_sue8_context_v2": (build_monthly_sue_context_v2, {"income": ()}, None),
    "pit_annual_cash_profitability": (build_monthly_annual_cash_profitability, ANNUAL_CASH_FIELDS, 18),
    "pit_quarterly_roe_volatility": (build_monthly_quarterly_roe_stability,
                                     {"income": (), "balancesheet": ()}, 6),
    "pit_annual_debt_ebitda": (build_monthly_debt_ebitda, {"income": (), "fina_indicator": ()}, 18),
}


def scoped_histories(
    histories: dict[str, pl.DataFrame], extras: dict[str, tuple[str, ...]],
) -> dict[str, pl.DataFrame]:
    """Only a family's original economic columns participate in revision conflicts."""
    return {name: histories[name].select(
        *(STRUCTURAL if name != "fina_indicator" else ("symbol", "ann_date", "available_date", "end_date", "source")),
        *BASE_FIELDS[name], *columns)
            for name, columns in extras.items()}


def direct_snapshot(
    name: str, histories: dict[str, pl.DataFrame], date: dt.date, symbols: tuple[str, ...],
) -> pl.DataFrame:
    function = DIRECT[name][0]
    arguments = {ARGUMENTS[table]: frame.filter(pl.col("symbol").is_in(symbols))
                 for table, frame in histories.items()}
    return function(**arguments, signal_dates=(date,), candidate_symbols=symbols).factors.select(
        "symbol", "trade_date", "financial_period_end", name)
