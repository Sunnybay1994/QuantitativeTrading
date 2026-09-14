# 个人 A 股 / ETF 量化系统

日频与月频研究、固定模型前向预测、模拟账户和人工订单清单。日更和持续因子挖掘由 Windows 计划任务运行，实盘默认关闭。

## 从哪里开始

| 入口 | 用途 |
|---|---|
| [项目实施路线图](项目实施路线图.md) | 当前任务、判定口径与冻结范围 |
| [接手与运行指南](docs/START_HERE.md) | 调度归属、恢复方式、配置及证据位置 |
| [AGENTS.md](AGENTS.md) | 项目工作准则和安全约束 |
| [机器排行榜](docs/research/排行榜.md) | 读取结果注册表生成的实验结果 |
| [研究文档索引](docs/research/README.md) | 方法、操作说明和历史结论入口 |

## 日常运行

唯一生产环境是 Windows 原生 `D:\Miniforge3\python.exe`（Python 3.13）。在项目根目录运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'

# 只检查日更配置，不刷新数据或修改账户
D:\Miniforge3\python.exe -m quant.research.scheduled_observation --check-only

# 查看已注册任务，不启动第二份进程
Get-ScheduledTask -TaskName 'QuantitativeTrading*' | Select-Object TaskName,State
```

| 执行者 | 时间（北京时间） | 内容 | 结果位置 |
|---|---|---|---|
| `QuantitativeTrading-DailyObservation` | 工作日17:30、21:30 | 数据/因子增量、冻结模型预测、观察账户、风险与月报；S0接续 | `artifacts/daily/sue_v2/`、`artifacts/daily/scheduler/` |
| `QuantitativeTrading-ContinuousMining` | 登录后及每10分钟尝试接续，运行中不重复启动 | 候选队列、GP、完整评估、准入、到期月度模型 | `artifacts/research/continuous/`、`artifacts/factors/nightly_batches/` |
| 主进程统一跟进 | 周一09:00、R5未完成时每日15:00、工作日22:00 | 检查结果、恢复失败、每周诊断、月末评分 | 当前任务及已有机器报告 |

电脑须开机，Windows调度账户须登录；Codex检查由应用运行。计划任务状态 `Ready` 仅表示等待运行，完成依据是实际日志、退出码和结果文件。机器休眠或有其他写入任务时可能延后，不能仅看计划时间判定成功。

## 配置与产物

| 工作 | 配置入口 | 产物入口 |
|---|---|---|
| 日更观察 | [daily_observation_q2_sue_v2_20260912.toml](configs/research/daily_observation_q2_sue_v2_20260912.toml) | `artifacts/daily/sue_v2/` |
| Q10模拟账户 | [q10_sue_v2_20260913.toml](configs/paper/q10_sue_v2_20260913.toml) | `artifacts/paper/q10_sue_v2/` |
| 持续研究 | [nightly.toml](configs/research/nightly.toml) | `artifacts/research/continuous/` |
| 因子定义 / 自动入库 / 待评估队列 | `configs/factors/library/`、`library/auto/`、`configs/factors/queue/` | `artifacts/factors/nightly_batches/` |
| 因子评估规则 | [battery.toml](configs/factors/battery.toml) | 各批次 `evaluation/summary.json` 和 `report.md` |
| 实验注册表 | `artifacts/registry/experiments.parquet` | [排行榜](docs/research/排行榜.md) |

结果只写机器生成的 `artifacts/<run>/report.md`，排行榜由注册表生成，不手工填写收益数字：

```powershell
D:\Miniforge3\python.exe -m quant.reporting.leaderboard
```

需要运行一个新实验或恢复失败阶段时，先按[接手指南](docs/START_HERE.md)确认进程、输入版本和输出目录，避免与日更/持续挖掘任务并发写入。查看后台状态：`powershell -NoProfile -File scripts/show_factor_mining_status.ps1`。

## 目录与边界

- `src/quant/data/`：采集、raw/clean、PIT与数据读取；SDK在`connectors/`。
- `src/quant/factors/`、`strategies/`：计算因子与目标权重；策略不读取账户、不下单。
- `src/quant/portfolio/`、`backtest/`、`execution/`：约束、统一成本回放、模拟账户与人工订单。
- `src/quant/research/`、`reporting/`：流水线编排、评估与机器报告。
- `configs/`：版本化规则；`*.local.toml`为忽略的本机凭据配置。
- `data/`、`artifacts/`：数据与可恢复实验现场，通常不进入Git；不得按临时缓存批量清理。
- `tests/`：定向验证；`docs/research/experiments_2026-09/`保留历史结论，`docs/archive/`为冻结历史。

保持原始数据不可覆盖、财务按公告日期可知、收盘信号最早下一开市日成交、统一交易规则与三档成本。`auto_trade=false`，真实资金操作由用户确认。WSL/Qlib formal链、旧OMS与高频相关模块按路线图冻结，不作为当前运行入口。
