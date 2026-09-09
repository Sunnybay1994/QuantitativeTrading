# START HERE — 新 Agent 接手指南

> 你是这个项目唯一的量化研究员兼工程师。你的 KPI 是让用户的钱赚到经风险调整后为正的收益，
> 不是写文档、不是造框架、不是通过 Gate。

## 第一次进入项目时（10 分钟内完成，不要多读）

只读这四个文件，按顺序：

1. [`../AGENTS.md`](../AGENTS.md) —— 行为准则，特别是 §1 "已获永久授权的事项"、§3 "反过度工程化硬规则"和 §6 研究范围。
2. [`../项目实施路线图.md`](../项目实施路线图.md) —— 只看 §1 当前阶段目标、§1.1 本周任务和 §1.2 预注册规则。
3. [`research/研究流程精简版.md`](research/研究流程精简版.md) —— 一个假设怎么从想法到结论。
4. [`research/研究议程_因子与策略清单.md`](research/研究议程_因子与策略清单.md) —— 阶段 B 的菜单：三条研究线、
   因子与策略清单、各品种成本与门槛。结果记到 [`research/排行榜.md`](research/排行榜.md)。
   分钟数据怎么取见 [`research/分钟级数据源调研_20260909.md`](research/分钟级数据源调研_20260909.md)。

**不要**去读 `docs/archive/` 里的任何东西，除非路线图明确让你去查一个具体数字。那里有约 1,200 份
2026-07 至 09 期间的任务书/交付/审查/治理文档，它们是这个项目过去两个月停滞的原因，不是知识。

## 环境（唯一）

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

# 数据补齐（日频 + 个股/ETF/港股分钟线；17点前取上一完整日）
D:\Miniforge3\python.exe -m quant.data.refresh --to today

# 仅分钟数据；BaoStock 单连接串行，首次历史回填时间较长
D:\Miniforge3\python.exe -m quant.data.intraday --to today

# 只刷新日频（例如分钟历史回填仍在后台运行时）
D:\Miniforge3\python.exe -m quant.data.refresh --to today --no-intraday
```

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
你接手 F:\AI_Coding\QuantitativeTrading。先读 AGENTS.md、项目实施路线图.md §1、
docs/research/研究流程精简版.md、docs/research/研究议程_因子与策略清单.md，
然后直接开始执行路线图 §1.1 中第一个未完成的任务。
阶段 B 的目标是复现有效的因子与策略。分钟数据可以用，但优先用来做 A 股截面策略的分钟低频化因子；
日内策略只在成本地图比值 ≥ 20 的 T+0 ETF（主要是黄金 ETF）上做，日均 ≤ 6 笔，不做高频、不做秒级；
滑点按延迟 0/1/3 分钟三档报，悲观档为正才算通过。时序、横截面、基本面、分钟低频化四类因子都要覆盖；
分钟数据用 BaoStock（个股 5 分钟）/ Yahoo Finance（ETF、港股）免费源。
不需要向我申请运行 Python、读写数据、联网抓数据或使用 CPU 的权限。
不要读 docs/archive。不要新建任务书、审查报告或状态标签。
每完成一项就在路线图 §4 和 docs/research/排行榜.md 追加一行并提交。遇到阻塞先绕过或修掉，实在不行一句话记到 §5 然后做下一件事。
汇报只要三段：做了什么（带数字）、下一步、最多一条需要我确认的事。
```
