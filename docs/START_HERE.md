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
| [run_nightly_research.ps1](../scripts/run_nightly_research.ps1) | Windows `QuantitativeTrading-NightlyResearch`，工作日22:30/周六09:00 |
| Codex `automation`：量化主进程统一跟进 | 09/15/22唤醒，分别按周一、R5待验收、工作日日更分支检查；不代替Windows再启动同一批任务 |

调度配置入口：[日更](../configs/research/daily_observation_q2_sue_v2_20260912.toml)、[夜间](../configs/research/nightly.toml)。两个安装/注册脚本仅在首次部署或明确修改调度时使用，不作为日常启动命令。

旧`background_mining`三轮已结束且接续暂停；当前R5为单独授权的夜间流水线。不要因为旧配置仍在仓库而恢复旧搜索。原来源任务已交接，不再向其发执行请求。

## 看哪些证据

| 问题 | 核对位置 |
|---|---|
| 日更是否完整 | `artifacts/daily/scheduler/`日志、当日`artifacts/daily/sue_v2/`的`summary.json`与`scheduler.json`；S0记录独立检查 |
| Q10是否产生真实前向记录 | `artifacts/paper/q10_sue_v2/`，规则见[账户配置](../configs/paper/q10_sue_v2_20260913.toml)；初始化现金不算成交 |
| 夜间是否完成 | `artifacts/research/nightly/<日期>/summary.json`、`digest.md`和各阶段`result.json` |
| 候选是否评估和入库 | `artifacts/factors/nightly_batches/<批次>/evaluation/summary.json`、`admission_scorecard.parquet`及`configs/factors/library/auto/` |
| 历史实验结论 | `artifacts/registry/experiments.parquet`及[机器排行榜](research/排行榜.md)；旧文档只供追溯 |

R5验收要求连续三个真实计划调度夜的完整记录；零入选可以，失败和`nightly_validation/`白天验证不能计数。月度模型首次到期由配置决定，未到期跳过不表示已经完成月度模型实跑。

## 恢复失败任务

- 先确认实际进程已结束，再读失败阶段日志；保留原run与断点。
- 夜间恢复使用该run已冻结的`config.toml`调用`quant.research.nightly --config <原配置>`，原`deadline_at`不重置。
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
