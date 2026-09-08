# 投研文档索引

- 做研究怎么走流程：[`研究流程精简版.md`](研究流程精简版.md)（一个假设 = 一个 config + 一个 run + 一页结论）。
- 报什么指标：[`投研评价指标与市场状态研究方法.md`](投研评价指标与市场状态研究方法.md)。
- 方法论背景：[`量化拥挤时代的因子发现与策略生存方法论.md`](量化拥挤时代的因子发现与策略生存方法论.md)、
  [`量化机构投研与实盘基础设施调研.md`](量化机构投研与实盘基础设施调研.md)。
- 当前要做什么：根目录 [`项目实施路线图.md`](../../项目实施路线图.md) §1；结果台账在其 §4。
- 机器可重放的 run：`artifacts/research/runs/<run_id>/run.json`（不进 Git）。

## `hypotheses/` —— 假设卡与结论（一页一个）

已有结论（2026-08，均在全市场 Top800 或 `ETF_POOL_M2_V1` 上，walk-forward，含 0.5×/1×/2× 成本）：

| 主题 | 结论 | 文件 |
|---|---|---|
| 经典日频因子第一轮（动量/波动/量价 Alpha158 子集） | 多数 RankIC 弱；见阶段总结 | `M2_经典日频因子第一轮研究结果.md`、`M2_经典日线因子阶段总结与下一分支.md` |
| 第二批价量机制 / 第三批正交日线机制 / 第四批残差时点量能 | REJECTED | 对应 `*研究结果.md` |
| 三因子组合、五因子 LightGBM | 未形成可晋级组合 | `M2_经典三因子组合第二轮研究结果.md`、`M2_经典因子五因子LightGBM研究结果.md` |
| 510300 市场风险覆盖 / downside beta | REJECTED | `M2_经典因子510300市场风险覆盖第三轮研究结果.md`、`M2_510300下行Beta因子研究结果.md` |
| Amihud 非流动性、自由流通换手 | REJECTED（2026-02 有效日不足 + RankIC 弱） | `M2_Amihud非流动性因子研究结果.md`、`M2_自由流通换手因子研究结果.md` |
| `daily_basic` 价值代理（EP/BP 等） | 见结果页 | `M2_daily_basic价值代理因子研究结果.md` |
| MAX 彩票偏好（含规模/换手残差化控制） | RankIC 0.046、3/3 折为正，但 2× 成本后为负 → REJECTED；是目前最强的单因子信号 | `M2_MAX彩票偏好因子研究结果.md`、`M2_MAX规模换手二阶段控制研究结果.md` |
| PIT 财务质量因子首批（ROE/ROA/现金利润质量/应计） | 仅有假设卡，等财务 clean 发布后跑 | `M2_PIT财务质量因子首批假设卡.md` |

ETF 策略系列（S0/S1/S2 及其 7 个单变量变体）的结论汇总在路线图 §0 与 §4；config 在
`configs/research/m2_s2_*.toml`，run 在 `artifacts/research/runs/`。

新结论一律按 [`研究流程精简版.md`](研究流程精简版.md) §3 模板写入本目录，文件名用 `hypothesis_id`。

## `references/` —— 外部知识输入（不是项目结论）

- [`quant_factor_research_v2/`](references/quant_factor_research_v2/README.md)：Alpha101 全表、Alpha158/360 清单、
  QIML 2024 因子日历、跨库去重与组合框架。挑候选因子时从这里找机制，本地 run 才算证据。
- [`EVOQUANT_验证器引导策略优化_论文总结与项目借鉴评估.md`](references/EVOQUANT_验证器引导策略优化_论文总结与项目借鉴评估.md)。

历史任务书/交付/审查文档已归档到 `docs/archive/2026-07至09_多Agent治理期/research/`，不再使用。
