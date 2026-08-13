# M1 U0C-R3：连续五交易日无人干预调度任务单

日期：2026-08-08  
状态：R2 真实窗口失败；R3 runner、XML 与计划任务已注册，等待 2026-08-10 至 08-14 自然窗口

## R2 真实裁定

2026-08-03 至 08-07 不满足五日 Gate：

| 日期 | Task Scheduler | 项目日志 |
|---|---|---|
| 08-03 | 8 月 5 日 StartWhenAvailable，exit 0 | SUCCESS / ALREADY_COMPLETE |
| 08-04 | 8 月 5 日 StartWhenAvailable，exit 2 | `M1_SCHEDULE_PROCESS_FAILED` |
| 08-05 | 8 月 5 日运行，exit 2 | `M1_SCHEDULE_PROCESS_FAILED` |
| 08-06 | exit 0 | SUCCESS / ALREADY_COMPLETE |
| 08-07 | `0xC000013A` | 零字节日志 |

离线审计稳定返回 `M1_STREAK_RECEIPT_INVALID`。R2 产物和五个旧任务保持不可变；不得补跑或改写。
Task Scheduler Operational history未留存，系统日志也未发现同期关机/睡眠事件。R2 的结构性风险是多个独立
`StartWhenAvailable` 任务可在主机恢复后并发启动，而底层单实例锁会使其余固定日期直接失败；外部任务
两小时终止还可能留下零字节日志。

## R3 冻结窗口与 runner

本地 clean 日历对四个固定证券计算的下一批五个共同开市日为 2026-08-10 至 08-14。新 runner：

```text
scripts/run_m1_daily_streak_20260810_20260814.sh
```

保持固定 source、symbols、无复权因子、WSL Miniforge base、不可覆盖逐日日志、首次成功后同 identity
ALREADY_COMPLETE、无网络重试。仅增加两个运行时护栏：

1. 五个固定日期任务共享同一外层 `flock`，主机恢复导致并发 runnable 时按已获得锁的顺序串行执行；等待
   不是数据/API retry，每个日期仍只调用一次 daily runner；
2. 内层 daily runner 以 20 分钟超时，确保在 Task Scheduler 两小时上限前写出稳定失败码，不再留下
   零字节未决日志。

外层锁等待上限 50 分钟；失败写 `M1_SCHEDULE_SERIALIZATION_TIMEOUT`。真实调用失败仍写
`M1_SCHEDULE_PROCESS_FAILED`。不得手工运行白名单日期。

## XML 与注册合同

注册五个一次性任务 `QuantTrading-M1-U0C-R3-20260810` 至 `20260814`，各日 21:30
（Asia/Shanghai），action 固定 WSL + 新 runner + 对应日期。保留：

- `InteractiveToken`；
- `IgnoreNew`（外层跨任务锁另行串行）；
- `StartWhenAvailable=true`、`WakeToRun=true`；
- `ExecutionTimeLimit=PT2H`；
- 无 repetition、无 Task Scheduler retry。

注册前后保存/核对五份 XML 与 SHA-256。注册不触发任务。8 月 14 日后只能离线运行
`quant.data.audit_daily_streak`；五份日志和五份 fresh-verified receipt 全部闭包才关闭 U0C。

2026-08-08 已完成注册。首次回读发现 08-10 与 08-14 的 runner 范围替换不完整；两任务均从未运行，已
立即修正源 XML 并精确覆盖同名任务。随后对五个任务逐字段复验通过：边界、action/arguments、
`InteractiveToken`、`IgnoreNew`、`StartWhenAvailable`、`WakeToRun`、`PT2H` 均符合本合同，无 repetition，
状态均为 Ready，LastRunTime 仍为 Task Scheduler 未运行哨兵。注册前定义、注册后导出、结构化 receipt 与
SHA-256 均保存在正式 WSL 独立 artifact 目录；未手工运行任何白名单日期。

## 验证与边界

注册前完成 `bash -n`、非法日期 exit 65 且零写、并发 fixture 证明串行且各日期最多一次 crossing、20 分钟
超时分支的缩时 fixture。真实任务、正式 data、日志和 receipt 只由 OS scheduler 生成。R3 只解决 U0C，
不关闭 HK60、01065 官方无交易证据、WSL/ext4 发布或 M1 整体 Gate。
