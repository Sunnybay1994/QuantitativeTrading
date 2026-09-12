# START HERE — 新 Agent 接手指南

> 你是这个项目唯一的量化研究员兼工程师。你的 KPI 是让用户的钱赚到经风险调整后为正的收益，
> 不是写文档、不是造框架、不是通过 Gate。

## 第一次进入项目时（10 分钟内完成，不要多读）

只读这五个文件，按顺序：

1. [`../AGENTS.md`](../AGENTS.md) —— 行为准则，特别是 §1 "已获永久授权的事项"、§2 人机分工、§3 硬规则（尤其第 11–13 条）和 §6 研究范围。
2. [`../项目实施路线图.md`](../项目实施路线图.md) —— 只看 §1.0 当前阶段目标与任务、§1.2 预注册规则。
3. [`research/因子挖掘流水线_设计与分工.md`](research/因子挖掘流水线_设计与分工.md) —— **当前阶段的总设计**：为什么 93 个假设没有产出、
   因子库/因子评估流水线/多因子模型怎么建、Agent 该做什么不该做什么。
4. [`research/研究流程精简版.md`](research/研究流程精简版.md) —— 因子轨道 vs 假设轨道；策略级假设怎么从想法到结论。
5. [`research/研究议程_因子与策略清单.md`](research/研究议程_因子与策略清单.md) —— 因子与策略的内容清单（流水线的输入范围）。
   结果记到 [`research/排行榜.md`](research/排行榜.md)；分钟数据见 [`research/分钟级数据源调研_20260909.md`](research/分钟级数据源调研_20260909.md)。

**不要**去读 `docs/archive/` 里的任何东西，除非路线图明确让你去查一个具体数字。那里有约 1,200 份
2026-07 至 09 期间的任务书/交付/审查/治理文档，它们是这个项目过去两个月停滞的原因，不是知识。

## 订单风险诊断

已有观察账户的持仓与参考订单可以生成只读风险报告：

```powershell
D:\Miniforge3\python.exe -m quant.execution.order_risk --snapshot artifacts/paper/b32_stock_observation/b32_cv20_buffer75/2026-09-09 --config configs/paper/order_risk_diagnostic_v1_20260911.toml --output artifacts/order_risk/<新目录>
```

输出`risk.json`与`report.md`，使用信号日已保存的行情、官方限制及历史行业，检查现金、可卖数量、整手、集中度和流动性。现金不足、超卖或非整手订单会停止资金和持仓预测，报告保留需修正项目。执行日市场状态需届时核对；这一步只做诊断，阈值不改变既有观察账户规则。

手工成交与现金事件可用`quant.execution.manual_fills`导入新账本，去重并与同日持仓核对；`quant.execution.manual_nav`逐日处理公司行动、收盘估值和资金流调整；`quant.execution.manual_orders`生成风险过滤后的次日订单演练；`quant.research.run_manual_order_replay`按固定股数和实际次日行情完成三档成本回放，见[输入格式与演练](research/手工成交导入与对账_20260911.md)。

## 环境（唯一）

固定模型预测的事后月度评分使用`quant.research.score_model_forecasts --forecast <预测目录> --known-through <已收盘日期> --output <新目录>`；多个日期重复传`--forecast`。历史演练与事前记录分开，见[评分口径与真实核对](research/固定模型预测评分_20260911.md)。

已有模型及候选的流动性、规模、行业、市场状态与成交容量诊断：`quant.reporting.model_stratification --config configs/models/p6cd_stratified_diagnostics_20260911.toml --output <新目录>`；见[诊断结论](research/模型与候选分层诊断_20260911.md)。

```powershell
cd F:\AI_Coding\QuantitativeTrading
$env:PYTHONPATH = "F:\AI_Coding\QuantitativeTrading\src"
D:\Miniforge3\python.exe --version          # Python 3.13；polars/duckdb/pandera/tushare/akshare/baostock/lightgbm 已装
D:\Miniforge3\python.exe -m pytest tests/unit/test_lightweight_research_run.py -q   # 冒烟
```

Tushare token 在 `configs/tushare.local.toml`（已 gitignore）。不打印、不复制到任何产物。
不需要 WSL，不需要 conda 环境切换，不需要向用户申请运行权限。

## 常用入口

```powershell
# 因子库全市场历史/每日增量（P1已完成；相同数据再次运行no-op）
D:\Miniforge3\python.exe -m quant.factors.compute --factors all --from 2010-01-01 --to today

# ETF 策略 walk-forward（S0/S1/S2 系列；config 决定假设）
D:\Miniforge3\python.exe -m quant.research.run_s1_walk_forward --config configs/research/m2_s2_volatility_target.toml

# A 股三因子月度 Top50（阶段 A 基线）
D:\Miniforge3\python.exe -m quant.research.run_classic_factor_composite --config configs/research/a7_monthly_zscore_20260909.toml --threads 4

# 全市场因子评估（RankIC / 分组 / Top50 成本后收益）
D:\Miniforge3\python.exe -m quant.research.run_classic_factors --config configs/research/m2_classic_daily_factors.toml --threads 8

# 财务四表 clean 重建（自动生成新版本名，保留 raw）
D:\Miniforge3\python.exe -m quant.data.publish_tushare_financials --workers 8

# S0 模拟盘（先刷新数据）
D:\Miniforge3\python.exe -m quant.execution.paper_ledger --to today

# B32 A股双账户固定前向观察（每日21点后；RESEARCH_ONLY）
D:\Miniforge3\python.exe -m quant.execution.stock_paper --to today
D:\Miniforge3\python.exe -m quant.reporting.stock_paper_monthly

# 数据补齐（日频 + 分钟 + 基准 + 财务 + 因子增量及实际覆盖检查；17点前取上一完整日）
D:\Miniforge3\python.exe -m quant.data.refresh --to today

# 扫描财务公告使用已有 Poppler 和 Windows 中文 OCR；识别页缓存，重复更新复用。
# 待解析公告、实际因子覆盖和财务版本见刷新结果中的 input_quality / financials。

# 有限因子搜索：展开固定24项候选 → 历史计算 → 开发/验证 → 成本及评分表；同一目录恢复
# 确认原进程已停止后重跑；未写完批次汇总的成本阶段会复用已完成因子，并恢复本批次年度账户断点。
D:\Miniforge3\python.exe -m quant.research.run_factor_search --config configs/factors/search/p6c_finite_batch01_20260911.toml --output artifacts/factors/search/p6c_batch01_20260911

# 多因子模型随既有成本结果自动续跑（五分钟检查一次；最多等待24小时）
D:\Miniforge3\python.exe -m quant.research.follow_multifactor_pipeline --config configs/models/p4_annual_walk_forward_20260911.toml --output artifacts/models/p4_follow_new --resume-from artifacts/models/p4_pipeline_20260911_04_resumed

# 固定三种模型方法按验证RankIC自动选型；仅研究前向观察
D:\Miniforge3\python.exe -m quant.research.run_strategy_template_selection --config configs/models/p6c_method_selection_20260911.toml --output artifacts/models/<新选型目录>

# 固定日历口径修正版生成研究预测，继承原冻结方法；9月14日前核对须显式使用--rehearsal
# 原版selection因旧月度换手因子缺失，9月11日无完整特征；修正版当天演练生成2393条，仍为RESEARCH_ONLY。
D:\Miniforge3\python.exe -m quant.research.run_fixed_model_forecast --selection artifacts/models/p6c_calendar_model_20260911_02/selection --as-of YYYY-MM-DD --output artifacts/models/<新预测目录>

# 一条命令刷新完成交易日的数据与因子、检查质量、记录同日冻结模型预测；不改账户持仓
D:\Miniforge3\python.exe -m quant.research.run_daily_model_forecast --to today --selection artifacts/models/p6c_calendar_model_20260911_02/selection --output artifacts/models/<新日更目录>
# 已发布数据演练可加--saved-data --rehearsal；数据缺失/质量错误返回非零。仍使用新目录保留每次记录。
# --saved-data同样扫描完整配置范围的实际质量；当前旧SUE的2个错误会阻止预测。

# 9月14日起：同日刷新与预测、B20/B32冻结观察账户、B32月报一条命令；预测不驱动持仓
D:\Miniforge3\python.exe -m quant.research.run_daily_observation --to today --output artifacts/research/<新日更观察目录>
# 9月14日前的演练须加--saved-data --rehearsal --account-root <已初始化的隔离副本根目录>。
# output/report.md汇总阶段与输入问题；factor_health记录原始因子健康诊断，详见日更运行说明。

# 仅分钟数据；BaoStock 单连接串行，首次历史回填时间较长
D:\Miniforge3\python.exe -m quant.data.intraday --to today

# 有界个股分钟补齐：固定名单前200只，仅查询指定日期，保留历史缺口
D:\Miniforge3\python.exe -m quant.data.intraday --stock-from 2026-09-11 --to 2026-09-11 --no-yahoo --limit 200

# 只刷新日频（例如分钟历史回填仍在后台运行时）
D:\Miniforge3\python.exe -m quant.data.refresh --to today --no-intraday
```

日常`quant.data.refresh`按配置补最近7个自然日的个股分钟线；历史补缺仍用上面的完整分钟入口。
个股分钟数据发生变化后，日常入口会重算该日期范围内的分钟因子，随后检查覆盖率。
行业快照过期时，日常入口更新当前申万成员、复用已结束的SW2014历史，并重算新增日期的行业表达式。

run 产物在 `artifacts/research/runs/<run_id>/`；`run.json` 有假设、config/code 哈希、结论。
研究结论一页一个，放 `docs/research/hypotheses/`。

## 每个工作会话的固定开场

1. `git status` + `git log --oneline -5`：确认在 `main`、工作树干净。
2. 打开路线图 §1.1，选一个未完成任务，写一句话目标和时间盒。
3. 干活。产出：run / 数据 / 代码 / 一页结论，四选一以上。
4. 更新路线图 §4 结果台账（一行）和 [`research/排行榜.md`](research/排行榜.md) 对应行，必要时更新 §1.1 状态与 §5 阻塞栏；
   在研究议程里把做完的因子/策略勾掉。
5. `git commit`，提交信息说人话："feat(research): S2 波动率目标在 2026-07~09 样本外 +1.2%"。

## 会话结束前自检

- 这次会话让"回测结论 / 数据覆盖 / 订单清单 / 模拟盘净值"四者中至少一个发生了变化吗？
  没有 → 下次会话第一件事必须是让其中一个变化。
- 我有没有新建任务书、审查报告、状态标签、receipt、锁、"待批示"？有 → 删掉。
- 我有没有因为"未授权"而停下？有 → 重读 AGENTS.md §1，除了真实资金和删 raw，都不需要授权。
- 我的汇报是否是"做了什么 + 数字 + 下一步"三段式？

## 给用户的启动 prompt（可直接复制到新会话）

```text
你接手 F:\AI_Coding\QuantitativeTrading。先读 AGENTS.md、项目实施路线图.md §1.0、
docs/research/因子挖掘流水线_设计与分工.md、docs/research/研究流程精简版.md，
然后直接开始执行路线图 §1.0 任务表中第一个未完成的任务（P1 起）。
当前阶段（B2）的目标是把因子挖掘变成无人流水线：因子库 ≥ 200 个 → 因子评估流水线一条命令出全历史 scorecard →
三种多因子模型 2015–2026 逐年 walk-forward 回测 → 有候选就进模拟盘第二账户。
从现在起不要再做单因子假设卡、一年窗口配对增量、Top75 缓冲/双月变体这类微假设；因子一律登记进因子库走因子评估流水线。
你的工作是：建流水线；从文献/研报批量写因子表达式（一次 20–50 个）；读 scorecard 写诊断；
把文本信号变成可评估的因子列；做模型和组合规则级别的策略决策。算因子、跑评估、选因子、回测都让机器做。
判定只认全历史统计量（Newey–West t ≥ 3、ICIR、年度符号一致率、多空 Sharpe），三基准并报。
不需要向我申请运行 Python、读写数据、联网抓数据或使用 CPU 的权限。
不要读 docs/archive。不要新建任务书、审查报告或状态标签。
每完成一项就在路线图 §4 和 docs/research/排行榜.md 追加一行并提交。遇到阻塞先绕过或修掉，实在不行一句话记到 §5 然后做下一件事。
汇报只要三段：做了什么（带数字）、下一步、最多一条需要我确认的事。
```
