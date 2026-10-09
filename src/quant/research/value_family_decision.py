"""Summarize the bounded evidence; no new strategy or admission is generated."""
from pathlib import Path

import polars as pl

from quant.research.value_family_evidence import save


def span(frame: pl.DataFrame, column: str) -> dict:
    return {"minimum": frame[column].min(), "maximum": frame[column].max()}


def conclude(out: Path) -> dict:
    metrics = pl.read_parquet(out / "common_window_metrics.parquet")
    neutral = metrics.filter((pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 1))
    second = metrics.filter((pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 2))
    benchmark = pl.read_parquet(out / "benchmark_risk.parquet").sort("cagr", descending=True).row(0, named=True)
    excess = second.with_columns((pl.col("cagr") - benchmark["cagr"]).alias("excess"))
    market = pl.read_parquet(out / "market_covariation.parquet").filter(
        (pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 1) & (pl.col("design") == "market_only"))
    pairs = pl.read_parquet(out / "return_overlap.parquet").filter((pl.col("cost") == 1)
        & pl.col("account").str.contains("size_industry_neutral") & pl.col("reference").str.starts_with("q10/"))
    holdings = pl.read_parquet(out / "actual_holdings_overlap.parquet").filter((pl.col("cost") == 1)
        & pl.col("account").str.contains("size_industry_neutral") & pl.col("reference").str.starts_with("q10/"))
    overlap = holdings.group_by("account").agg(pl.col("shared_equity_weight").mean())
    annual = pl.read_parquet(out / "calendar_year_metrics.parquet")
    concentration = []
    for key, group in annual.group_by("factor", "variant", "cost"):
        pos = group.filter(pl.col("log_return_contribution") > 0).sort("log_return_contribution", descending=True)
        concentration.append({"factor": key[0], "variant": key[1], "cost": key[2],
            "positive_years": pos.height, "reported_years": group.height,
            "top2_positive_log_contribution_share": pos.head(2)["log_return_contribution"].sum() / pos["log_return_contribution"].sum(),
            "top2_years": ",".join(str(x) for x in pos.head(2)["year"]),
            "partial_years_included": "2014,2026",
            "interpretation": "descriptive_concentration_no_year_exclusion_or_short_window_admission"})
    concentration = pl.DataFrame(concentration)
    save(out / "annual_gain_concentration", concentration)
    bridge = pl.read_parquet(out / "annual_bridge_reconciliation.parquet").filter(
        (pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 1)).group_by("factor").agg(
            pl.col("top5_positive_bridge_share").median(), pl.col("top5_negative_bridge_share").median(),
            pl.col("consistent_absolute_bridge_fraction").median(), pl.col("unallocated_on_begin_equity").mean())
    exposures = pl.read_parquet(out / "snapshot_exposures.parquet").filter(
        (pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 1)).group_by("factor").agg(
            pl.col("smallest_quartile_equity_weight").mean(), pl.col("top5_actual_weight").mean(),
            pl.col("industry_unknown_equity_weight").max())
    fees = neutral.with_columns((pl.col("annual_fee_on_nav") + pl.col("annual_slippage_on_nav")).alias("execution_spend_rate"))
    return {
        "decision": "关闭本轮价值/股息族账户扩展，不注册新个人账户假设。保存证据没有识别出区别于已失败加因子模型的可检验组合或执行机制；不再接续同族诊断、状态/窗口/Top-K 搜索或费用参数救援。保留原五因子准入及观察，不宣称所有价值方法无效。",
        "decision_scope": "close_this_account_extension_not_revoke_factor_admissions_or_prove_universal_ineffectiveness",
        "new_account_hypotheses": 0,
        "neutral_1x_sharpe": span(neutral, "sharpe"),
        "neutral_1x_max_drawdown": span(neutral, "max_drawdown"),
        "neutral_2x_excess_strongest": span(excess, "excess"),
        "strongest_common_benchmark": benchmark["benchmark"],
        "neutral_1x_market_r_squared": span(market, "r_squared"),
        "neutral_1x_q10_return_correlation": span(pairs, "return_correlation"),
        "neutral_1x_q10_mean_year_end_shared_weight": span(overlap, "shared_equity_weight"),
        "neutral_1x_median_daily_names": span(neutral, "median_position_count"),
        "neutral_1x_mean_small_quartile_snapshot_weight": span(exposures, "smallest_quartile_equity_weight"),
        "neutral_1x_mean_top5_snapshot_weight": span(exposures, "top5_actual_weight"),
        "neutral_1x_max_unknown_industry_snapshot_weight": span(exposures, "industry_unknown_equity_weight"),
        "neutral_1x_top2_positive_year_log_share": span(concentration.filter(
            (pl.col("variant") == "size_industry_neutral") & (pl.col("cost") == 1)), "top2_positive_log_contribution_share"),
        "neutral_1x_median_top5_positive_security_bridge_share": span(bridge, "top5_positive_bridge_share"),
        "neutral_1x_median_quantity_consistent_bridge_fraction": span(bridge, "consistent_absolute_bridge_fraction"),
        "neutral_1x_mean_unallocated_cash_on_begin_equity": span(bridge, "unallocated_on_begin_equity"),
        "neutral_1x_execution_spend_rate": span(fees, "execution_spend_rate"),
        "rejection_profit_drag": "unknown_no_unfilled_trade_counterfactual",
        "next_research_direction": "Independent whole-family candidate intake through the existing battery; possible net shareholder payout/capital-allocation family (realized common cash dividends plus actual common-share repurchases less common-share cash issuance), subject to actual announcement-time and realized-cash evidence. This is a candidate direction, not an implemented factor, new account, or validated result. Do not restart this value-family extension.",
    }
