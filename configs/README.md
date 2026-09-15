# 活跃配置

一次性日期实验配置不要当默认入口。调度与日常命令只用下表。其余文件保留，不删。

| 用途 | 路径 |
|---|---|
| 运行时 / GPU / LLM 预算 | [runtime.toml](runtime.toml) |
| 通知通道 | [notify.toml](notify.toml) |
| 日更 | [research/daily_observation_q2_sue_v2_20260912.toml](research/daily_observation_q2_sue_v2_20260912.toml) |
| 持续挖掘 / 夜间规则 | [research/nightly.toml](research/nightly.toml) |
| 周度 LLM 候选 | [research/weekly_factor_candidates.toml](research/weekly_factor_candidates.toml) |
| 情报扫描 | [research/intel.toml](research/intel.toml) |
| 因子评估电池 | [factors/battery.toml](factors/battery.toml) |
| 因子库 / 自动入库 / 队列 | `factors/library/`、`factors/library/auto/`、`factors/queue/` |
| Q10 模拟账户 | [paper/q10_sue_v2_20260913.toml](paper/q10_sue_v2_20260913.toml) |
| 数据刷新 | [data/refresh_q2_sue_v2_model_20260912.toml](data/refresh_q2_sue_v2_model_20260912.toml) |
| 收益基准 | [data/return_benchmarks_q1b_20260912.toml](data/return_benchmarks_q1b_20260912.toml) |
| Tushare token | `tushare.local.toml`（Git 忽略，从 example 复制） |
| DeepSeek key | `deepseek.local.toml` 或环境变量 |

新增研究用版本化 config 加独立 run 目录，不要改上表里的冻结文件来"顺便试一下"。
