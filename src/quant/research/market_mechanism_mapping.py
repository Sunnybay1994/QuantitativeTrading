"""Outcome-independent economic grouping of the frozen library."""

FINANCIAL = {
    "value_dividend": "book_to_price daily_dividend_yield_ttm daily_ep_ttm_positive daily_sp_ttm_positive pit_cash_yield_ttm",
    "profitability": "pit_annual_gmar pit_annual_gpoa pit_annual_roa pit_annual_roe pit_asset_turnover_ttm pit_gross_margin_ttm pit_gross_profitability_ttm pit_net_margin_ttm pit_roa_ttm pit_roe_ttm pit_quarterly_roe_volatility",
    "cash_quality": "pit_annual_cash_profitability pit_cash_profit_quality_ttm pit_cash_roa_ttm pit_cash_to_liabilities_ttm",
    "investment_accrual": "pit_annual_low_accruals pit_asset_growth_yoy pit_inventory_expansion_yoy pit_total_accruals_ttm",
    "growth_surprise": "pit_profit_acceleration pit_profit_growth_ttm pit_revenue_acceleration pit_revenue_growth_ttm pit_sue8 pit_sue8_context_v2",
    "balance_sheet_safety": "pit_annual_debt_ebitda pit_current_ratio pit_liabilities_to_assets pit_annual_zscore",
    "composite_quality": "pit_annual_fscore pit_annual_profitability",
}


def mechanism(definition: dict) -> tuple[str, str]:
    """Group by frozen expression/source identity, never by realized outcomes."""
    name, source = definition["id"], definition["family"]
    for group, names in FINANCIAL.items():
        if name in names.split():
            return group, "explicit_economic_definition"
    if source == "pit_financial":
        raise ValueError(f"Unclassified financial definition: {name}")
    if source == "size":
        return "size_reference", "explicit_size_control"
    if name.startswith("alpha101_"):
        return "alpha101_mixed", "mixed_formulas_no_single_causal_mechanism"
    if name.startswith("alpha158_"):
        import re
        prefix = re.sub(r"\d+$", "", name.removeprefix("alpha158_"))
        if prefix in {"roc", "ma", "beta", "rsqr", "resi", "max", "min", "qtlu", "qtld", "rank", "rsv", "imax", "imin", "imxd", "cntp", "cntn", "cntd", "sump", "sumn", "sumd"}:
            return "price_trend_position", "alpha158_price_formula_block"
        if prefix in {"vma", "vstd", "wvma", "vsump", "vsumn", "vsumd", "volume"}:
            return "volume_activity", "alpha158_volume_formula_block"
        if prefix in {"corr", "cord"}:
            return "price_volume_interaction", "alpha158_joint_formula_block"
        if prefix == "std":
            return "volatility_risk", "alpha158_volatility_formula_block"
        return "price_bar_shape", "alpha158_OHLC_formula_block"
    if source == "minute_low_frequency":
        return "intraday_aggregated", "mixed_minute_features"
    if name in {"momentum_126", "pret_12m_skip1m", "high52_ratio"}:
        return "momentum", "positive_registered_price_trend"
    if name in {"reversal_20", "overnight_return_20", "intraday_return_20", "vol_scaled_reversal_20"} or name.startswith("p6c1_vol_scaled_reversal_"):
        return "reversal", "registered_return_reversal"
    if any(word in name for word in ("volatility", "ivol", "beta_60", "max_daily_return")):
        return "volatility_risk", "risk_or_lottery_formula"
    if name.startswith("p6c1_close_position") or source == "report_shadow_normalization":
        return "price_bar_shape", "registered_price_location_formula"
    if name.startswith("p6c1_return_volume") or source == "report01_price_liquidity":
        return "price_volume_interaction", "joint_price_liquidity_formula"
    if source in {"legacy_monthly_liquidity", "calendar_monthly_liquidity", "liquidity", "report_turnover_growth_stability"} or "turnover" in name:
        return "liquidity_activity", "registered_liquidity_formula"
    if source in {"genetic_price_liquidity", "nightly_predictive_priority_v2", "nightly_price_volume"}:
        return "mined_mixed", "generated_interactions_not_independent_economic_mechanism"
    return "other_" + source, "source_family_heterogeneous_preserved"
