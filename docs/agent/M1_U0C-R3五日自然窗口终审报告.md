# M1 U0C-R3：五日自然窗口终审报告

日期：2026-08-14（Asia/Shanghai）
结论：**PASS；U0C-R3 连续五交易日自然调度子 Gate 达到 5/5。**

本结论只关闭 2026-08-10 至 2026-08-14 的连续调度子 Gate，不关闭 HK60、正式许可、港股复权与公司行动、
Linux/ext4 或 M1 整体 Gate。

## 1. 冻结合同

- 五个共同开市日：`2026-08-10` 至 `2026-08-14`；
- 每日由独立 Windows Task Scheduler 一次性任务在 21:30 唤起 Ubuntu WSL；
- runner：`scripts/run_m1_daily_streak_20260810_20260814.sh`；
- runner SHA-256：`bdedb95335c8bbeaf2238a443eb321dee2a9120d9caf74d65bc7de31af2df02c`；
- 固定证券：`000001.SZ 600000.SH 00005.HK 00700.HK`；
- 通过条件是 Scheduler 轴与五日 receipt/data 闭包轴同时成立。

## 2. Scheduler 轴

08-10 至 08-13 的任务在各自合同日完成后均已由当时的只读查询记录为 `LastTaskResult=0`，其
`LastRunTime` 均落在各自 21:30 自然窗口。终审前 live task objects 已只剩 08-14；本报告没有把缺失的
历史对象伪装成当前可查询对象，而是使用此前同时期状态记录、注册收据和不可覆盖日证据组成连续证据链。

08-14 的触发前快照于 `21:29:56+08:00` 记录：`State=Ready`、未运行哨兵、
`NextRunTime=21:30:30+08:00`。自然运行后主 Agent 只读查询得到：

- `LastRunTime=2026-08-14T21:30:30+08:00`；
- `LastTaskResult=0`；
- `NumberOfMissedRuns=0`；
- `NextRunTime=null`，符合一次性任务完成后的终态；
- live XML 仍为冻结的 `StartBoundary`、系统 `wsl.exe`、固定 Ubuntu/runner/日期参数、
  `InteractiveToken`、`IgnoreNew`、`StartWhenAvailable=true`、`WakeToRun=true` 与 `PT2H`。

五份 `registered_definitions/*.xml` 的 SHA-256 重新计算后均逐项等于
`registration_receipt.json` 的 `export_sha256`；runner 物理 SHA 也等于注册收据。未发现任务定义漂移、
手工 Run、重注册或补跑的正面证据。

Task Scheduler Operational 历史通道终审时仍为 `IsEnabled=false`，记作诚实边界
`U0C_R3_HISTORY_CHANNEL_DISABLED`。因此本报告不声称拥有事件级完整操作历史，也不以“没有事件”推导
无人操作；本轴依据的是注册前后快照、逐日同时期状态、固定脚本身份和自然窗口内生成的不可覆盖日志。

终审观察器本身在 `21:30:08` 因一次性任务运行后 `NextRunTime=null` 被错误强转为
`DateTimeOffset` 而退出。该缺陷只影响辅助取证脚本，没有调用任务修改或触发 API；调度器 live 终态与正式日
日志随后由只读命令取得，因此不改变被观察任务的成功结果。

## 3. 五日日志与数据闭包轴

五份日志均为单行 exact JSON，`status=SUCCESS`、`replay_status=ALREADY_COMPLETE`、`exit_code=0`：

| 日期 | UTC 起止 | run id | 日志 SHA-256 |
|---|---|---|---|
| 2026-08-10 | 13:30:13 → 13:30:15 | `b59805f9...caf5c` | `f0ef3ae1...cf0fb` |
| 2026-08-11 | 13:30:11 → 13:30:12 | `88ec86f1...cb199` | `41c81625...3bdb2` |
| 2026-08-12 | 13:30:37 → 13:30:47 | `19a1fb0b...4b73` | `fe9a5632...f2211` |
| 2026-08-13 | 13:30:14 → 13:30:16 | `36a94469...dcd4` | `f104f90f...edfd` |
| 2026-08-14 | 13:30:17 → 13:30:19 | `d12c714a...15f6` | `a27b99f3...6fb0` |

08-14 receipt SHA-256 为
`95dc0b2c789626d94652305068e4f0d297727cc12664c8037f820eb01d26d605`，其 5 个 artifact 与 run id
由正式 auditor 重新验真。终审在 WSL Miniforge `base`、零网络下运行冻结命令，唯一结果为：

```json
{"schema_version":"m1-daily-streak-audit-v1","status":"PASS","sessions":5,"dates":["2026-08-10","2026-08-11","2026-08-12","2026-08-13","2026-08-14"]}
```

该命令 fresh verify 了五份 daily receipt 及其 raw/quality/intent/manifest 字节闭包，不是只引用历史摘要。

## 4. 最终裁定与剩余风险

Scheduler 正面证据和五日数据闭包同时成立，未命中定义漂移、提前日志、结果异常、跨日补启、人工触发或
证据篡改分类。因此 U0C-R3 记为 **5/5 PASS**。

仍开放：

- Task Scheduler Operational 历史通道关闭，缺少事件级全历史；该限制已披露，不反转本次正面证据结论；
- M1 的 HK licensed provenance、`01065.HK` 权威无交易事实、HK60、正式许可/复权/公司行动仍未完成；
- WSL 当前仍不是 Linux/ext4 Gate 环境，本报告不扩大为该平台结论。

终审报告和 live 终态证据落定后，已删除最后一个完成的一次性 Task Scheduler 对象及临时 watcher 目录，
避免遗留无未来触发的系统任务。五份注册 XML、注册收据、正式日 JSON、daily receipt 与全部数据产物均保留，
任务定义可由注册快照审计或恢复；本次清理没有触碰任何正式数据闭包。
