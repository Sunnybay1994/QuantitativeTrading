# M1-U0C 连续五交易日无人干预调度主 Agent 预验收报告

状态：2026-07-18 **预注册与初验返工通过；真实 Gate 0/5，未关闭**

## 1. 已完成

- 已实现一次 scheduler invocation 内的 `SUCCESS → ALREADY_COMPLETE` 双运行包装器、严格离线 streak auditor
  和 WSL 启动脚本。
- 已注册五个 Windows 一次性任务：2026-07-20 至 2026-07-24，每日 21:30 Asia/Shanghai，均为
  `Ready`。
- action 固定为 `C:\Windows\System32\wsl.exe -d Ubuntu -- bash
  /home/mabw/AI_Coding_win/QuantitativeTrading/scripts/run_m1_daily_streak.sh <date>`。
- 五个任务均为 `IgnoreNew`、`StartWhenAvailable=true`、`WakeToRun=true`、`RestartCount=0`、
  `ExecutionTimeLimit=PT2H`；未手工启动任何真实日期任务。
- 导出的任务定义保存在
  `artifacts/data_quality/m1_daily_streak/20260720_20260724/task_definitions/`。

## 2. 不可变任务定义

| 日期 | XML SHA-256 |
| --- | --- |
| 2026-07-20 | `6bcdec309136d73b29c7f919b13d177697544092588aaf8bfd84c9f0339bee41` |
| 2026-07-21 | `5a02368011e697989d9f367b49a9213516a7116228c22c4ab52d5f092bf38b80` |
| 2026-07-22 | `5fef0ea47dfa06115f5d73995cd27d7b83fe38ac1edf7346d56933ec7b9b1194` |
| 2026-07-23 | `c438fa9b7bb8ad3b2e52cd099805bf6ae108b97a9b6c8fe3f1144dd67c440fba` |
| 2026-07-24 | `51a2f6d095439a456174f6950a351f2a94f47cd5be165fffe7e09febc184f499` |

Task Scheduler 的 `NextRunTime` 显示为对应日期 `21:30:30+08:00`，但导出 XML 的权威
`StartBoundary` 均为 `21:30:00+08:00` 且没有 `RandomDelay`；不把 UI/调度器显示粒度误写为合同漂移。

## 3. 初验返工

独立初验用对抗 runner 证明：原 wrapper 只要求 `run_id`/`receipt_selector` 为字符串，异常适配器可把绝对
路径或敏感文本带入成功日志。预注册后已收紧为：

- `run_id` 必须恰为 64 位小写十六进制；
- selector 必须恰为 `run_state/m1_daily/<run_id>/receipt.json`；
- 大写 hash、错配 identity、Windows 绝对路径和 `..` 路径均 fail closed；
- 新增五组对抗单测，异常仍只暴露稳定错误码且不保留异常链。

修复后的主 Agent 复验已完成：WSL Miniforge base 与 Windows 原生 Miniforge 均运行 U0C 与 P2A 合并定向
集，分别为 `27 passed`；Ruff 全部通过，mypy 对 3 个相关生产源文件通过。初验报告保留最初 FAIL 作为
历史，不以修改报告抹去返工原因。

## 4. 尚未关闭的风险与 Gate

- 当前真实证据仍为 **0/5**。最早只能在 2026-07-24 21:30 后运行离线 streak audit 判定。
- Windows `Microsoft-Windows-TaskScheduler/Operational` 历史通道当前为 `enabled=false`。直接启用被
  `Access is denied` 拒绝，后续 UAC 提权请求被取消，未继续弹窗。五个单行项目日志及
  `Get-ScheduledTaskInfo` 仍保留，但若要求系统事件级历史，必须在 7 月 20 日首跑前由管理员启用该通道。
- 任一日期首次不是 `SUCCESS`、第二次不是同 identity 的 `ALREADY_COMPLETE`、任务被人工重跑、receipt
  漂移或 writer 冲突，都使本轮 streak 失败；不得补跑后继续计数。

结论：代码返工和任务定义已通过预运行主验，但 Task Scheduler Operational 历史通道和五个真实 session
尚未关闭，因此 M1 连续五日 Gate 仍为未通过。
