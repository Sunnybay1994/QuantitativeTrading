"""Generate a bounded value-family account diagnosis from measured tables."""
from pathlib import Path

import polars as pl

from quant.research.market_mechanism_report import table
from quant.research.value_family_evidence import write_json


def write_report(out: Path, summary: dict):
    metrics = pl.read_parquet(out / "common_window_metrics.parquet")
    benchmarks = pl.read_parquet(out / "benchmark_risk.parquet")
    strongest = benchmarks.sort("cagr", descending=True).row(0, named=True)
    metrics = metrics.with_columns((pl.col("cagr") - strongest["cagr"]).alias("excess_strongest_cagr"))
    neutral = metrics.filter(pl.col("variant") == "size_industry_neutral")
    exposures = pl.read_parquet(out / "snapshot_exposures.parquet")
    factor_exposures = exposures.filter(pl.col("variant").is_in(["raw", "size_industry_neutral"]))
    average_exposures = factor_exposures.group_by("factor", "variant", "cost").agg(
        pl.len().alias("snapshot_dates"), pl.col("positions").median().alias("median_names"),
        pl.col("top5_actual_weight").mean(), pl.col("smallest_quartile_equity_weight").mean(),
        pl.col("largest_quartile_equity_weight").mean(), pl.col("size_unknown_equity_weight").max(),
        pl.col("largest_known_industry_equity_weight").mean(), pl.col("industry_unknown_equity_weight").max())
    risk = pl.read_parquet(out / "market_covariation.parquet").filter(pl.col("design") == "market_only")
    bridge = pl.read_parquet(out / "annual_bridge_reconciliation.parquet")
    bridge_summary = bridge.group_by("factor", "variant", "cost").agg(
        pl.col("top5_positive_bridge_share").median(), pl.col("top5_negative_bridge_share").median(),
        pl.col("consistent_absolute_bridge_fraction").median(),
        pl.col("unallocated_on_begin_equity").mean(), pl.col("quantity_inconsistent_symbols").sum())
    pair = pl.read_parquet(out / "return_overlap.parquet")
    model_pairs = pair.filter(pl.col("reference").str.starts_with("q10/") | pl.col("reference").str.starts_with("monthly_"))
    holding_pair = pl.read_parquet(out / "actual_holdings_overlap.parquet")
    model_holdings = holding_pair.filter(pl.col("reference").str.starts_with("q10/") | pl.col("reference").str.starts_with("monthly_"))
    holding_summary = model_holdings.group_by("account", "reference").agg(pl.len().alias("snapshot_dates"),
        pl.col("shared_equity_weight").mean(), pl.col("a_weight_in_b_names").mean(), pl.col("b_weight_in_a_names").mean())
    holding_summary.write_parquet(out / "model_holdings_overlap_summary.parquet")
    holding_summary.write_csv(out / "model_holdings_overlap_summary.csv")
    def pct_range(key):
        x = summary[key]
        return f"{x['minimum']:.2%}—{x['maximum']:.2%}"

    lines = ["# 价值/股息整族：保存账户的有界诊断", "", summary["decision"], "",
        f"固定五因子、两版本、三档成本，共 {summary['factor_accounts']} 条原账户；未重跑任何账户。共同风险收益区间为 {summary['common_start']} 至 {summary['common_end']}，起点取中性化账户最晚起始日，终点受已验证修正版基准与 Q10 共同覆盖限制。",
        "raw 原始起点为 2010-02-01，中性化为 2014-02-07；本报告所有原始/中性化收益比较均使用共同区间。即便同区间差异，也包含股票集合、行业和规模变化，不解释为中性化的因果贡献。", "",
        "本次判断依据：",
        f"- 五个中性化账户1× Sharpe 为 {summary['neutral_1x_sharpe']['minimum']:.3f}—{summary['neutral_1x_sharpe']['maximum']:.3f}，最大回撤 {pct_range('neutral_1x_max_drawdown')}；2× 相对共同区间最强基准年化超额只有 {pct_range('neutral_2x_excess_strongest')}。",
        f"- 市场回归 R² {pct_range('neutral_1x_market_r_squared')}；与 Q10 的日收益相关 {summary['neutral_1x_q10_return_correlation']['minimum']:.3f}—{summary['neutral_1x_q10_return_correlation']['maximum']:.3f}，而年末共同持仓权重均值仅 {pct_range('neutral_1x_q10_mean_year_end_shared_weight')}。共同市场变化明显，不能用低持股重合推导分散化。",
        f"- 日持仓数量中位数为 {summary['neutral_1x_median_daily_names']['minimum']:.0f}—{summary['neutral_1x_median_daily_names']['maximum']:.0f} 只；年末实际最大五股合计权重均值只有 {pct_range('neutral_1x_mean_top5_snapshot_weight')}。这不是少持股账户。",
        f"- 中性化账户年末最小市值四分位权重均值 {pct_range('neutral_1x_mean_small_quartile_snapshot_weight')}，并非简单把小盘超配当全部解释；行业未知最大快照权重 {pct_range('neutral_1x_max_unknown_industry_snapshot_weight')}，不作完整行业归因。", "",
        "## 共同区间风险收益", "",
        f"最强共同区间收益指数为 {strongest['benchmark']}，年化 {strongest['cagr']:.3%}；相对超额使用同一日历与前一交易日锚点。基准无账户成本。",
        "修正版公司行动基准的原始版本与本月电池基准在全部重合行完全一致后才用于比较；修复沿用待换股权益的旧账面价估值约定，并非观测公允价值。", ""]
    lines += table(metrics.sort("factor", "variant", "cost"), ["factor", "variant", "cost", "cagr", "excess_strongest_cagr", "sharpe", "max_drawdown", "annual_turnover", "median_position_count"])
    lines += ["", "## 市场共同变化与实际持仓暴露", "",
        "市场回归只描述与修正版全市场等权指数的同期共同变化。另存的全市场减中证800相对收益列是广度/风格混合代理，不能解释成纯小盘因子，更不能视为因果 alpha。行业与市值取同版电池的年末收盘记录，仅描述当日持仓；不同版 Q10 的行业/市值保持 unknown。", ""]
    lines += table(risk.filter(pl.col("cost") == 1).sort("factor", "variant"), ["factor", "variant", "market_beta", "r_squared", "arithmetic_intercept_times252"])
    lines += ["", "年末实际持仓摘要（并非每日持仓）：", ""]
    lines += table(average_exposures.filter(pl.col("cost") == 1).sort("factor", "variant"), ["factor", "variant", "snapshot_dates", "median_names", "top5_actual_weight", "smallest_quartile_equity_weight", "largest_quartile_equity_weight", "size_unknown_equity_weight", "largest_known_industry_equity_weight", "industry_unknown_equity_weight"])
    lines += ["", "## 与已有账户重合", "",
        "收益相关使用双方实际开始持仓后的共同日期。年末共同持仓权重为逐股票两账户净值权重的较小值之和；不是每日重合或可合并收益。完整三档结果见 return_overlap.csv，实际持仓重合见 actual_holdings_overlap.csv。", ""]
    lines += table(model_pairs.filter((pl.col("cost") == 1) & pl.col("account").str.contains("size_industry_neutral")).sort("account", "reference"), ["account", "reference", "start", "sessions", "return_correlation", "cagr_difference", "tracking_error_annual"])
    lines += ["", "中性化因子与模型的年末实际重合：", ""]
    lines += table(holding_summary.filter(pl.col("account").str.contains("size_industry_neutral")).sort("account", "reference"), ["account", "reference", "snapshot_dates", "shared_equity_weight", "a_weight_in_b_names", "b_weight_in_a_names"])
    lines += ["", "## 年份与个股贡献边界", "",
        "calendar_year_metrics.csv 保留全部年份风险收益和对数收益贡献，2014 与 2026 是部分年份。没有按表现删年或挑股票。",
        f"五个中性化1×账户中，最大两个正贡献年份占所有正年度对数收益之和 {pct_range('neutral_1x_top2_positive_year_log_share')}（详见 annual_gain_concentration.csv，包含2014部分年份）；这里只描述收益集中，未把两年窗口用于准入判定。",
        "个股表按完整保存的年末持仓计算：期末市值－期初市值＋卖出金额－买入金额－费用。成交价已包含滑点，不能重复扣滑点。该桥接不是含分红总收益归因；未分配分红、应收和公司行动现金流留在单独残差。买卖数量不能解释期末数量的股票单独标记，不纳入可核对股票的集中贡献比例。",
        f"五个账户可核对股票的 top5 正桥接贡献占比年度中位数为 {pct_range('neutral_1x_median_top5_positive_security_bridge_share')}；数量可核对桥接绝对金额覆盖中位数为 {pct_range('neutral_1x_median_quantity_consistent_bridge_fraction')}。未分配现金残差平均占年初净值 {pct_range('neutral_1x_mean_unallocated_cash_on_begin_equity')}，因此不能声称已经完整解释个股总收益。",
        "以下 top5 是事后贡献集中度描述，不是 Top-K 策略筛选；分母是数量可核对股票的正/负桥接金额总和，不是账户净利润。", ""]
    lines += table(bridge_summary.filter(pl.col("cost") == 1).sort("factor", "variant"), ["factor", "variant", "top5_positive_bridge_share", "top5_negative_bridge_share", "consistent_absolute_bridge_fraction", "unallocated_on_begin_equity", "quantity_inconsistent_symbols"])
    lines += ["", "## 成本与拒单", "",
        "费用逐笔合计与连续净值累计费用增量核对。fee 与 slippage 对前日净值的比率是已发生执行支出尺度，不是无摩擦收益反事实。0.5× 与 2× 保存路径的差异同时含仓位、整手和成交变化。", ""]
    lines += table(metrics.filter(pl.col("cost") == 1).sort("factor", "variant"), ["factor", "variant", "annual_fee_on_nav", "annual_slippage_on_nav", "trade_count", "delisting_writeoff_cny"])
    lines += ["", f"中性化1×实际费用加滑点的年化前日净值比率为 {pct_range('neutral_1x_execution_spend_rate')}。这是执行支出尺度，不足以建立区别于已失败加因子模型的新执行策略。",
        "rejection_reasons.csv 保留全部拒单事件与原因。重复受阻请求不能相加解释成损失资本；没有未成交后的反事实交易，故拒单利润拖累 unknown。", "",
        "## 结论", "", summary["decision"], "",
        "资源回到具有独立经济机制的新整族候选及原电池。可考察股东净回报/资本配置整族，以实际回购、股权融资与分配现金流刻画资本纪律；它目前仅为候选方向，公告时点与实际完成数据尚未验证，未实现、未进电池，也未注册新账户。不再把本次停止改写成下一轮同族诊断。", "",
        "所有账户仍是本金100万元、最低佣金5元的宽持仓路径；不能外推10万元、少持股、佣金1元账户。现有准入结论不变。", "",
        "## 复现与验证", "",
        f"消费源文件 {summary['source_files_unchanged']} 个，读取后哈希均未变化；{summary['reconciled_snapshots']} 个实际持仓快照与净值市值核对，{summary['accounting_bridge_years']} 个账户年保留分项与未分配余额。",
        "运行 `python -m quant research value-family-holdings --config configs/research/value_family_holdings_20261004.toml`。source_manifest.json、benchmark_identity.json 与各核对表保存原始证据身份。未修改 raw、原净值、准入、观察账户、日更、挖掘或调度；auto_trade=false。", ""]
    text = "\n".join(lines)
    # Keep the main report within the repository's Markdown size limit.
    if len(text.encode("utf-8")) > 30000:
        raise ValueError("Split generated report before publication")
    (out / "report.md").write_text(text, encoding="utf-8")
    receipt = neutral.filter(pl.col("cost") == 1).select("factor", "cagr", "excess_strongest_cagr", "sharpe", "max_drawdown").sort("factor")
    write_json(out / "sources.json", {"schemaVersion": 1, "items": [{"id": "value-family-saved-accounts", "title": "五因子中性化账户：共同区间1倍成本",
        "queries": [{"id": "same-window", "source": {"label": "Saved continuous NAV, verified corrected return benchmarks",
            "caveats": ["CNY1m, minimum commission CNY5, broad top group. No personal account replay.",
                "Common window 2014-02-07 to 2026-08-31 includes the first common day's return.",
                "No new admission, state switching or causal attribution is established."]},
            "columns": receipt.columns, "rows": receipt.to_dicts(), "rowCount": receipt.height}]}]})
