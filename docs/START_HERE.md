# 接手与运行指南

先读根目录[AGENTS.md](../AGENTS.md)，再读[路线图](../项目实施路线图.md)的§1.0.3与§1.2。最新代码、配置和机器产物优先于历史交接或旧文档。

## 接手顺序

1. 查看`git status --short`与最近提交，保留其他工作的未提交改动。
2. 核对Windows计划任务和实际Python进程。已有正常运行任务时，读取一次紧凑状态即可，不重复启动。
3. 按路线图选择当前尚未完成事项，写一句目标和时间盒；不要照旧启动提示重新做R1/R2。
4. 实验用版本化配置与独立run目录；修复后按原入口恢复，保留失败日志和原截止时间。
5. 结果由机器报告及注册表保存，排行榜自动生成；只提交本轮明确文件。

## 唯一运行环境

```powershell
cd F:\AI_Coding\QuantitativeTrading
$env:PYTHONPATH = "$PWD\src"
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
D:\Miniforge3\python.exe --version
D:\Miniforge3\python.exe -m quant.research.scheduled_observation --check-only
```

凭据从ignored本地配置读取，不能打印配置内容。依赖以`pyproject.toml`为准。WSL、旧Qlib环境与跨平台验证已经冻结。

## 当前调度归属

| 执行入口 | 当前职责 |
|---|---|
| [run_daily_observation.ps1](../scripts/run_daily_observation.ps1) | Windows `QuantitativeTrading-DailyObservation`，工作日17:30/21:30 |
| [run_continuous_mining.ps1](../scripts/run_continuous_mining.ps1) | Windows `QuantitativeTrading-ContinuousMining`，登录后及每10分钟尝试接续，运行中不重复启动；原 `NightlyResearch` 调度停用 |
| Codex `automation`：量化主进程统一跟进 | 当前暂停，持续挖掘由Windows独立运行；不要自行恢复旧跟进 |

调度配置入口：[日更](../configs/research/daily_observation_q2_sue_v2_20260912.toml)、[夜间](../configs/research/nightly.toml)。两个安装/注册脚本仅在首次部署或明确修改调度时使用，不作为日常启动命令。

旧`background_mining`三轮已结束且接续暂停；当前R5为用户授权的持续流水线，白天也执行。不要因为旧配置仍在仓库而恢复旧搜索或旧夜间调度。原来源任务已交接，不再向其发执行请求。

## 看哪些证据

| 问题 | 核对位置 |
|---|---|
| 日更是否完整 | `artifacts/daily/scheduler/`日志、当日`artifacts/daily/sue_v2/`的`summary.json`与`scheduler.json`；S0记录独立检查 |
| Q10是否产生真实前向记录 | `artifacts/paper/q10_sue_v2/`，规则见[账户配置](../configs/paper/q10_sue_v2_20260913.toml)；初始化现金不算成交 |
| 持续批次是否完成 | `artifacts/research/continuous/status.json`、`batch_*/<日期>/summary.json`、`digest.md`和各阶段`result.json`；旧夜间记录仍在`artifacts/research/nightly/` |
| 候选是否评估和入库 | `artifacts/factors/nightly_batches/<批次>/evaluation/summary.json`、`admission_scorecard.parquet`及`configs/factors/library/auto/` |
| 历史实验结论 | `artifacts/registry/experiments.parquet`及[机器排行榜](research/排行榜.md)；旧文档只供追溯 |

09-14用户要求持续运行后，默认入口改为持续批次。已有夜间验证产物保留，不把恢复次数或白天测试冒充多个完整研究批次。月度模型首次到期由配置决定，未到期跳过不表示已经完成月度模型实跑。

### 持续挖掘与关机恢复

电脑唤醒且Windows用户登录后自动接续；不依赖Codex窗口。每次最多运行2小时，优先恢复旧批次，完成后下一次触发才创建新seed批次。工作日17:20/21:20前结束当前执行片段，为17:30/21:30日更让路；日更仍在运行则继续等待。

关机后从最近保存的GP种群、随机状态、已评估表达式及成本断点恢复；尚未保存的计算会重做。相同批次连续三次非超时错误会停止重试并显示需要处理，原产物保留。不要删除断点或换目录绕过失败。

查看实时任务/进程/批次与GP代数：`powershell -NoProfile -File scripts/show_factor_mining_status.ps1`。机器状态为`artifacts/research/continuous/status.json`，每批结果在`batch_*/<日期>/digest.md`，调度日志在`artifacts/research/continuous/scheduler/`。

本地GP与评估本身不调用LLM。持续调度通过`configs/research/weekly_factor_candidates.toml`每周尝试一次DeepSeek候选生成，复用共享缓存，上海自然周上限$5、自然月上限$30，未知扣费保留预留。北京时间工作日09–12与14–18延后，其余时间及周末允许；价格快照过期时只延后LLM，本地GP继续（[官方价格，09-14核实](https://api-docs.deepseek.com/quick_start/pricing/)）。生成候选经DSL校验去重后进入原队列，实测相关性比例由N4结果自动写入`artifacts/research/weekly_candidates/<周一日期>/report.md`，未评估时不报通过比例。

## 前向跟踪与影子价格

日更配置的 `forward_tracking.enabled=true` 会在本次日更目录的 `forward_tracking/` 生成 `dashboard.html`、`dashboard.json`、`shadow_execution.csv` 与 `slippage_monthly.csv`。日更 `report.md` 提供页面入口；历史演练只读隔离账户，不混入生产 Q10。

页面使用保存账户的净值、实际持仓权重和观察期半成交额换手。影子价格使用参考订单对应下一交易日开盘与完整 5/15/30 分钟窗口；缺失分钟成交额或覆盖不完整时留空并提示处理。此记录用于积累校准证据，不能当作实际成交滑点。页面视觉检查尚待浏览器访问授权。

## 手工分日执行建议

手工订单演练现在同时生成 `execution_plan.csv`：按历史成交额参与率估计最多三日的分配，超过容量或缺少日历则标记拒绝。它不解除 `orders.csv` 的风险拦截；每日按实际成交重新核对现金、可卖数量和剩余需求。开盘后用当日核实的价格计算价格带：`D:\Miniforge3\python.exe -m quant.execution.manual_execution_plan --opening 10.03 --down-limit 9 --up-limit 11`（这里是演示值）。输出只用于价格核对，不执行交易。

## 恢复失败任务

- 先确认实际进程已结束，再读失败阶段日志；保留原run与断点。
- 持续批次由`quant.research.continuous_mining`自动恢复原run，执行时间片重新计时；旧夜间恢复仍用该run冻结的`config.toml`，原`deadline_at`不重置。
- GP已完成时复用其输出；已有因子批次复用统计、成本年度断点和最新评分表。N3没有完成时不能跳过它直接入库。
- 成本异常分开处理：全部版本统计拒绝且确无可执行组合可终态拒绝；数据缺失、计算异常与外部任务未完成仍需修复。
- 日期或输入版本变化时创建新run，不能修改冻结配置冒充同一次恢复。队列processing/completed由流水线维护，人工整理不要移动活跃候选。
- 日更保持S0、B20、B32、Q10各自冻结账户规则；自动研究不会直接驱动实盘。

## 按需入口

日更、队列和夜间流水线是默认入口。需要理解某一环节再读相应操作说明：

- [日更与观察账户](research/日更模型与观察账户运行说明_20260912.md)、[Windows日更调度](research/Windows独立日更调度_20260913.md)
- [PAPER月度对照](research/PAPER月度对照运行说明.md)、[手工成交与对账](research/手工成交导入与对账_20260911.md)
- [因子评估成本口径](research/因子评估流水线_历史成本口径_20260911.md)、[年度模型接续](research/因子评估接续年度模型_20260913.md)
- [研究方法与历史索引](research/README.md)

研究结果不再手写进`docs/research/`；新因子批量登记，模型/组合规则才需要预注册设计。排行榜通过`D:\Miniforge3\python.exe -m quant.reporting.leaderboard`更新。测试只运行与改动相关的范围，大改动再扩大验证。
