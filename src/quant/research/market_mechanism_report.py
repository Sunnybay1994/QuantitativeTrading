"""Generate the evidence report from saved full-library diagnosis tables."""
from pathlib import Path
import polars as pl

from quant.research.market_mechanism_mapping import FINANCIAL


def table(frame: pl.DataFrame, columns: list[str]) -> list[str]:
    def cell(x):
        if x is None:
            return "unknown"
        if isinstance(x, float):
            return f"{x:.5f}"
        return str(x).replace("|", "/")
    return ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |",
            *["| " + " | ".join(cell(row[c]) for c in columns) + " |" for row in frame.iter_rows(named=True)]]


def write_report(out: Path, summary: dict):
    families = pl.read_parquet(out / "family_summary.parquet")
    costs = pl.read_parquet(out / "family_cost_summary.parquet")
    states = pl.read_parquet(out / "state_summary.parquet")
    counts = pl.read_parquet(out / "mapping.parquet").group_by("mechanism").len().rename({"len": "factors"})
    overview = families.filter((pl.col("basis") == "available_paired_members") & (pl.col("variant") == "neutral_ic"))
    overview = counts.join(overview, on="mechanism", how="left").sort("mechanism")
    lines = ["# 全库市场状态与机制适配诊断", "", "本报告由保存的因子电池、月度标签、市场状态和成本回执自动生成。",
        "", "结论：停止把本轮状态切片延伸为择时或切换策略。未注册新的个人账户假设。正向家族 IC 只能构成机制线索，不能替代净收益、增量信号和个人账户执行证据。", "",
        f"覆盖 {summary['factors']} 个因子、{summary['variants']} 个版本，含全部 {summary['financial_factors']} 个财务因子。归类先于本轮结果计算冻结；通过与失败均保留，方向不翻转。",
        f"月度标签 {summary['signal_dates']} 个日期，状态与实际下一开盘执行日对齐 {summary['state_dates_aligned']} 个，状态日期缺失 {summary['state_dates_absent']} 个，有效日不一致 {summary['effective_date_mismatches']} 个。缺失保留 unknown。",
        f"状态历史 {summary['state_source_start']} 至 {summary['state_source_end']}；成熟 IC 截止 {summary['known_ic_through']}。历史重建不等于当时真实到达回执，9 月 30 日的现行回执不得回填成历史观测。", "",
        "## 机制与年度稳定性", "",
        "下表先在同因子同月配对原始与中性化 IC，再按月对家族成员等权平均。它是成员 IC 均值，不是组合 IC 或组合收益。混合公式族不解释为独立经济机制。年度分母及不足六个月的年份另列。", ""]
    lines += table(overview, ["mechanism", "factors", "months", "mean_ic", "years_observed", "years_at_least_6_months", "positive_qualified_year_fraction", "worst_year_mean_ic"])
    findings = {x["mechanism"]: x for x in summary["financial_complete_roster"]}
    lines += ["", "完整成员结果的解释："]
    for name in ["value_dividend", "cash_quality", "profitability", "investment_accrual", "growth_surprise", "balance_sheet_safety", "composite_quality"]:
        row = findings[name]
        lines += [f"- {name}：{row['months']} 个月，中性化 IC {row['mean_ic']:.5f}，至少六个月的年份正向比例 {row['positive_qualified_year_fraction']:.1%}。"]
    lines += ["", "固定完整成员敏感性见 family_summary.csv 的 complete_frozen_roster；family_months.csv 保留每月成员数量。缺失成员不填零，不把晚加入的高 IC 因子视为全历史可得。", "",
        "## 财务机制：原始与中性化", ""]
    financial = families.filter(pl.col("mechanism").is_in(list(FINANCIAL))).sort("mechanism", "basis", "variant")
    lines += table(financial, ["mechanism", "basis", "variant", "months", "mean_ic", "positive_qualified_year_fraction"])
    lines += ["", "中性化同时控制市值与行业，且可用股票集合不同，因此差值不是纯市值因果贡献。size_correlations.csv 单列与两个小市值方向参考因子的已存相关性；相关性不等于增量 IC。", "",
        "## 财务机制的市场状态切片", "",
        "下表是完整冻结成员、已配对月份的中性化 IC；其他三维状态和所有家族见 state_summary.csv。稀疏状态不拼接做连续时间 t 检验；state_years.csv 保留每年月份，state_within_year_contrasts.csv 对比同年其他已知状态。", ""]
    view = states.filter(pl.col("mechanism").is_in(list(FINANCIAL)) & (pl.col("variant") == "neutral_ic")
        & (pl.col("basis") == "complete_frozen_roster") & (pl.col("dimension") == "market_state")).sort("mechanism", "state")
    lines += table(view, ["mechanism", "state", "months", "mean_ic", "years_observed", "years_at_least_6_months", "largest_year_month_share"])
    lines += ["", "## 已存三档成本", "",
        f"旧电池：本金 {summary['original_cost_identity']['initial_cash']:,.0f} 元、最低佣金 {summary['original_cost_identity']['commission_min']} 元、最高分组等权；它不代表十万元、少持股、最低佣金一元账户。",
        f"原评分卡 {summary['cost_complete_variants']} 个版本记载成本完整，收益指数基准完整的版本为 {summary['complete_return_benchmark_variants']}。读取 {summary['saved_cost_receipt_rows']} 条三档成本回执并逐一复现评分卡 CAGR，最大误差 {summary['cost_receipt_max_cagr_error']:.3g}。它们仍是原基准版本，未套用本次此前完成的公司行动修正版，不能称为最新基准重评。",
        "下表是已存个体策略成本指标的中位数，并非家族组合收益。没有成本的因子仍为 unknown；不可把有成本子集当成全家族。没有运行状态切换账户，也没有状态条件成本收益证据。", ""]
    lines += table(costs.filter(pl.col("mechanism").is_in(list(FINANCIAL))).sort("mechanism", "variant", "cost_multiplier"),
                   ["mechanism", "variant", "cost_multiplier", "factors_with_saved_costs", "roster_factors", "median_cagr", "median_sharpe", "median_turnover", "median_drawdown"])
    evidence = pl.read_parquet(out / "factor_cost_evidence.parquet").filter(
        pl.col("mechanism").is_in(["value_dividend", "cash_quality"]) & (pl.col("variant") == "size_industry_neutral"))
    lines += ["", "价值/股息已有正向且去风格后保留的线索，但旧成本路径的风险表现不能推导个人集中账户改善；现金质量的已存两倍成本超额不足。保留所有成员逐项结果：", ""]
    lines += table(evidence.sort("mechanism", "factor"), ["factor", "statistical_pass", "factor_admitted", "cost_1_sharpe", "cost_2_all_market_equal_weight_cagr_excess", "cost_2_annualized_one_way_turnover"])
    lines += ["", "## 增量证据身份", ""]
    for item in summary["incremental_identity"]:
        lines += [f"- {item['source']}：{item['factors']} 个因子；与当前电池有 {item['matched_factor_months']} 个可比因子月，其中 {item['different_raw_ic_months']} 个原始秩 IC 不同。旧模型的控制集合、缺失填补、样本和版本不同，不能替代当前全库增量结果。"]
    lines += ["", "historical_partial_summary.csv 保留旧模型已识别的部分秩相关线索及未识别月份；没有覆盖的家族不解释成增量为零。", "",
        "## 行动边界", "",
        "下一方向明确选择独立的估值/现金流价格机制：把五个已有价值股息因子作为整族，先查保存的集中持仓、成交和增量线索，判断正向 IC 为何没有转化为足够强的账户风险收益。若只是在重复现有模型暴露，或原净收益风险不支持延伸，就停止；不得借此重启现金质量/应计的状态、窗口或 Top-K 搜索。",
        "当前没有同时满足同口径增量证据、个人账户三档成本及跨年适配证据的新假设；停止本轮状态择时延伸。任何后续新财务能力都按整族电池处理，而不是从本表挑一个赢家。", "",
        "## 验证与复现", "",
        f"评分卡全部版本月数复现，均值最大误差 {summary['scorecard_max_ic_error']:.3g}；{summary['unchanged_source_files']} 个已消费文件哈希保持不变。",
        "运行 `python -m quant research market-mechanism --config configs/research/market_mechanism_20261004.toml`；diagnosis.ipynb 提供同一入口。source_manifest.json 保存源文件哈希，frozen_mapping.json 保存事前归类、公式、方向和出处。",
        "未重跑因子电池、账户或指标，未调整准入门槛、订单、调度器和 raw，auto_trade=false。",
        "", *[f"- {text}" for text in summary["limitations"]], ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
