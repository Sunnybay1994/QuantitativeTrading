# M1 U0C-R3：连续五交易日调度注册报告

日期：2026-08-08  
状态：注册合同通过；等待 2026-08-10 至 08-14 自然运行和离线审计

## 2026-08-09 主 Agent 只读状态回查

未触发、未修改、未重注册任何任务。Windows Task Scheduler 只读回查结果：

- `QuantTrading-M1-U0C-R3-20260810` 至 `20260814` 五项均为 `Ready`；
- `LastRunTime` 均为未运行哨兵 `1999-11-30T00:00:00+08:00`，`LastTaskResult=267011`；
- `NextRunTime` 分别为 2026-08-10 至 08-14 每日 `21:30:30+08:00`；
- XML trigger start 仍分别为对应日期 `21:30:00+08:00`。

因此 R3 仍处于等待自然窗口状态；禁止手工提前触发的冻结条件保持不变。

## 注册结果

已注册五个一次性任务 `QuantTrading-M1-U0C-R3-20260810` 至 `20260814`。触发时间分别为对应自然日
21:30（`+08:00`），action 精确调用正式 WSL 项目路径中的
`scripts/run_m1_daily_streak_20260810_20260814.sh` 与对应固定日期。五个任务均为 Ready，从未运行。

runner 的 Windows 工作树、正式 WSL/DrvFS 副本 SHA-256 均为
`bdedb95335c8bbeaf2238a443eb321dee2a9120d9caf74d65bc7de31af2df02c`；`bash -n` 通过。Windows 上 runner
显示 0777 是当前 WSL1 文件互操作权限映射结果，内容身份和普通文件检查成立；任务显式以 `bash <path>`
运行，不依赖 executable bit。

首次注册后只读回读发现 08-10 与 08-14 XML 的 runner 文件名分别残留旧范围一端。两任务当时均从未
运行；已修正两份刚创建的 XML 并用同名定义精确覆盖。最终五任务逐字段断言全部通过：

- `InteractiveToken`、`IgnoreNew`；
- `StartWhenAvailable=true`、`WakeToRun=true`、`ExecutionTimeLimit=PT2H`；
- 无 repetition、无 Task Scheduler retry；
- exact trigger、command、arguments 与日期；
- Ready，LastRunTime 为未运行哨兵、LastTaskResult 为 `267011`。

## 正式证据路径

正式调度使用的 WSL/DrvFS 独立 artifacts 路径：

```text
/home/mabw/AI_Coding_win/QuantitativeTrading/artifacts/data_quality/m1_daily_streak/20260810_20260814/
```

其中 `task_definitions/` 为最终注册输入，`registered_definitions/` 为 Task Scheduler 注册后导出，
`registration_receipt.json` 为结构化字段与 export hash，另保存全体 SHA-256。R2 目录、旧任务、旧日志和
receipts 均未改写。

## 验证与 Gate 边界

- Windows runner 测试在任务冻结阶段：3 skipped（Linux-only）。
- WSL base：runner `bash -n`，并发/非法日期/缩时超时及 daily-streak 定向套件 `7 passed`。
- 注册后逐字段计划任务断言：5 个 `TASK_CONTRACT_PASS`。
- 正式 registration receipt 离线解析：`M1_U0C_R3_REGISTRATION_RECEIPT_PASS 5`。

本报告只证明调度合同和注册状态。当前 Ubuntu 仍是 WSL1，项目路径解析到 `/mnt/f` DrvFS；U0C 必须等待
五个自然计划任务完成，再对五份日志与 fresh receipt 做离线审计。它不关闭 HK60、01065 官方无交易证据、
正式 G1 Linux/ext4 发布 Gate 或 M1 整体 Gate。

## 2026-08-09 自然窗口前状态复核

只读回查确认 `20260810`–`20260814` 五个任务均仍为 `Ready`，未手工触发。首个任务状态为：

```text
LastRunTime=1999-11-30 00:00:00
LastTaskResult=267011
NextRunTime=2026-08-10 21:30:30 +08:00
```

因此 R3 仍按自然窗口等待；本次检查未运行、重启或修改任何计划任务。

## 2026-08-09 runner 缺失发现与冻结字节恢复

自然窗口前进一步按 Task Scheduler 实际 action 对 WSL 路径做只读 preflight 时，发现
`/home/mabw/AI_Coding_win/QuantitativeTrading/scripts/run_m1_daily_streak_20260810_20260814.sh` 当时不存在。
Ubuntu、项目目录与 `scripts/` 目录均正常；缺失范围是该 runner 文件。若保持该状态，08-10 首个任务会在
进入 Python 前失败。

未触发、停止、修改或重注册任何计划任务。主 Agent 从本任务冻结 worktree 中取出注册时已验真的 runner
exact bytes，其 SHA-256 为 `bdedb95335c8bbeaf2238a443eb321dee2a9120d9caf74d65bc7de31af2df02c`，与本报告
原注册证据完全一致；随后把这份 exact bytes 恢复到 Task Scheduler action 指向的正式 WSL 项目路径。未从
旧 08-03..07 runner 改写日期，也未生成新的 runner 变体。

恢复后无副作用 preflight：

- Windows 与 WSL `sha256sum` 均为上述冻结 SHA；
- WSL `bash -n`：PASS；
- WSL base 冷导入 `quant.data.run_scheduled_daily`：PASS；
- 正式 `task_definitions/` 与 `registration_receipt.json` 仍存在；
- 五个任务仍为 Ready、从未运行，action/trigger 未改变。

本次恢复只修复注册任务依赖的缺失冻结文件，没有运行任何白名单日期，也没有创建正式日志/receipt。根因仅
能确认“正式路径文件缺失、冻结 worktree 副本仍在”，没有足够证据归因于具体删除或同步动作，因此不作猜测。
