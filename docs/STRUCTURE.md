# 项目结构

当前代码基线为 `5831562d`；结构整理不改变业务规则。长期规则见 [研究协议](RESEARCH_PROTOCOL.md)，数据见 [DATA](DATA.md)，操作见 [OPERATIONS](OPERATIONS.md)。

## 包职责

| 包 | 职责 |
|---|---|
| `core` | 路径与运行时设置 |
| `data` | 数据连接、原始采集与 PIT 清洗 |
| `factors` | 表达式、计算与评估电池 |
| `research` | 预注册研究、GP 与日更；m3 冻结 |
| `portfolio` | 组合权重与约束 |
| `backtest` | 统一撮合、成本与回测 |
| `execution` | 模拟账本、人工订单与执行接口 |
| `reporting` | doctor、报告与看板 |
| `llm` | LLM 调用与预算 |
| `notify` | 微信、飞书等收发渠道 |
| `intel` | 情报摘要与出处核对 |

## CLI 子命令

统一入口 `python -m quant`。内建 `gpu-check`、`status`、`doctor`、`notify`、`intel scan`；下表按当前 `_DELEGATE` 生成。

| 组 | 子命令 |
|---|---|
| data | refresh, probe-tushare, structured-events, forward-benchmarks, account-portfolio-inputs, account-portfolio-panel, events-v0, realtime, market-snapshot, stock-execution-open, monthly-execution-open, latency, minutes, minute-history, minute-factors, baostock-history, post-close-k1m |
| factors | compute |
| paper | q10, top15-observation, rehearse, order-chain, order-watch, orders, manual, b16-forward |
| report | leaderboard, account-stock-leg, account-portfolio, review, periods, dashboard, q10-rolling, q10-forward-demo, funnel, brief |
| research | q10-sizing, account-etf-baselines, account-stock-leg, account-portfolio, account-portfolio-top15, gp-skew-repair, factor-family-states, market-mechanism, value-family-holdings, net-payout-feasibility, statement-event-family, turnover-reference-family, turnover-reference-verify, suspension-execution-audit, monthly-execution-open-verify, industry-information-coverage, industry-information-verify, joint-account, joint-integer, personal-top5, admitted-model-pair, residual-momentum, pead-event-inputs, pead-event-market-inputs, pead-account, benchmark-repair, benchmark-repair-evaluate, etf-measurement, etf-history-extension, calendar-allocation, cross-asset-long-cycle, etf-delayed-replay, etf-envelope-report, intraday-afternoon, minutes, mechanisms, allocation-attribution, market-indicators, mechanism-detail, etf-manual-init, etf-execution-stress, daily, nightly, feedback, reversal-readiness, predictive-inputs, batch-diagnosis, mining, recovery-audit, cycle, gp |

## 调度脚本与入口

按本机 2026-11-06 只读任务快照生成，包含全部 14 个 Quant 任务；不修改任务。

| 任务 | 脚本 | 入口 |
|---|---|---|
| BaostockHistory | `run_baostock_history.ps1` | `data baostock-history` |
| ContinuousMining | `run_continuous_mining.ps1` | `research mining`, `research minutes`, `quant.notify.automation_alert` |
| DailyObservation | `run_daily_observation.ps1` | `research daily`, `report brief`, `doctor`, `quant.notify.automation_alert`, `quant.research.daily_market_context` |
| IntelWeekly | `run_intel_weekly.ps1` | `intel scan`, `quant.notify.automation_alert` |
| MinutesHistory | `run_minute_refresh.ps1` | `data minute-factors`, `research minutes`, `quant.notify.automation_alert` |
| MinutesRecent | `run_minute_refresh.ps1` | `data minute-factors`, `research minutes`, `quant.notify.automation_alert` |
| NightlyResearch | `run_nightly_research.ps1` | `intel scan`, `research nightly`, `quant.notify.automation_alert` |
| PaperOrderWatch | `run_paper_insurance.ps1` | `paper order-watch`, `quant.notify.automation_alert` |
| PaperRehearsal | `run_paper_insurance.ps1` | `paper rehearse`, `quant.notify.automation_alert` |
| PostCloseK1M | `run_post_close_k1m.ps1` | `data post-close-k1m` |
| PostCloseK1M-HK | `run_post_close_k1m.ps1` | `data post-close-k1m` |
| PostCloseK1M-US | `run_post_close_k1m.ps1` | `data post-close-k1m` |
| RealtimeQuotes | `run_realtime_quotes.ps1` | `data realtime`, `paper b16-forward`, `data market-snapshot`, `quant.notify.automation_alert` |
| ResearchDashboard | `run_research_dashboard.ps1` | `report dashboard` |

详细参数见 [只读任务快照](../artifacts/x1/scheduled_tasks.json)。

## 运行目录

| 路径 | 用途 |
|---|---|
| `data/raw` | 只追加原始数据 |
| `data/clean` | 清洗表与可用时间 |
| `data/factors` | 因子值 |
| `data/features` / `data/qlib` | 特征缓存与冻结 provider |
| `data/realtime` / `data/run_state` | 盘中缓存与采集状态 |
| `data/external` | 固定版本外部工具 |
| `artifacts/paper` | 账户状态、净值与订单 |
| `artifacts/research` | 研究运行与批次回执 |
| `artifacts/daily` | 日更摘要 |
| `artifacts/registry` | 策略与实验注册表 |
| `artifacts/doctor` | 每日机器检查 |
| `artifacts/tests` | 测试回执 |
| `artifacts/intel` / `artifacts/llm` | 情报摘要与调用账本 |
| `artifacts/runtime` | 本地锁与运行状态 |
| `artifacts/worklog` | 实际日期工作记录 |

`legacy/quant` 已归档实现由现有 shim 保持导入兼容。当前可达的 m3/formal 等模块保留；不按文件名猜测死代码。文档位于 data、operations、reviews、worklists、research、archive；旧清单路径保留跳转入口供自动化使用。
