# M1 U0C-R2：连续五交易日无人干预调度任务单

状态：**本地 runner / XML 已冻结并校验；2026-08-02 已按冻结 XML 注册，等待 2026-08-03 至 08-07 真实运行证据**

日期：2026-07-31（Asia/Shanghai）

## 1. 原窗口裁定

2026-07-20 至 07-24 的首个真实窗口最终为：

| 日期 | 项目日志 | run_state |
|---|---|---|
| 2026-07-20 | SUCCESS / ALREADY_COMPLETE | receipt 完整 |
| 2026-07-21 | SUCCESS / ALREADY_COMPLETE | receipt 完整 |
| 2026-07-22 | SUCCESS / ALREADY_COMPLETE | receipt 完整 |
| 2026-07-23 | `M1_SCHEDULE_PROCESS_FAILED` | 只有合法 intent |
| 2026-07-24 | SUCCESS / ALREADY_COMPLETE | receipt 完整 |

7 月 23 日没有 raw、quality、manifest 或 receipt，说明第一次真实采集在 raw 落盘前失败。相邻五份任务 XML
除日期、URI 和参数日期外一致。冻结安全合同要求底层 stderr 丢弃、项目日志只保留单行稳定错误码，因此历史
根因不能再从产物还原。

原任务书明确规定任一日期失败即整轮失败，人工补跑不得继续计数。故真实 Gate 是 **4 SUCCESS + 1 FAILED**，
不是 5/5；旧窗口脚本、日志和 XML 保持不可变。

## 2. 新窗口

Windows 原生与 WSL Miniforge base 使用同一 `expected_open_dates(...)` 独立计算得到下一批五个共同开市日：

```text
2026-08-03
2026-08-04
2026-08-05
2026-08-06
2026-08-07
```

本地 SH / SZ / HK clean 日历的 15 条记录均为 `is_open=true`、`is_half_day=false`。

固定证券与语义不变：

```text
000001.SZ
600000.SH
00005.HK
00700.HK
source=tushare
without_adjustment_factors=true
```

## 3. 版本化 runner

新 runner：

```text
scripts/run_m1_daily_streak_20260803_20260807.sh
```

只接受上述五个日期，日志根目录固定为：

```text
artifacts/data_quality/m1_daily_streak/20260803_20260807/
```

继续保持：

- 固定 WSL Miniforge `base`；
- 首次必须 SUCCESS，立即同 identity 零网络重放必须 ALREADY_COMPLETE；
- 单行脱敏项目日志；
- 每日日志不可覆盖；
- 无自动 retry；
- 非白名单日期稳定退出 65。

已验证 `bash -n` 与非法日期退出 65；非法日期没有创建新日志目录。真实五日任务未被手工触发。

## 4. 任务定义与注册证据

本地 XML 位于：

```text
artifacts/data_quality/m1_daily_streak/20260803_20260807/task_definitions/
```

| TaskName | StartBoundary | XML SHA-256 |
|---|---|---|
| `QuantTrading-M1-U0C-R2-20260803` | `2026-08-03T21:30:00+08:00` | `0681fc2226201b38397803d51ee1cb6e8913f060a8509510b75fb7261c303819` |
| `QuantTrading-M1-U0C-R2-20260804` | `2026-08-04T21:30:00+08:00` | `199e16bd95911a86672c70f1da6f1337d0592fc4e24bb1bbbc2950dbdd5e30fd` |
| `QuantTrading-M1-U0C-R2-20260805` | `2026-08-05T21:30:00+08:00` | `2c1f1b18eb643bfdd284d22c88e3d8a97c669222f1b7e0873a3244d297450d97` |
| `QuantTrading-M1-U0C-R2-20260806` | `2026-08-06T21:30:00+08:00` | `31033e8bd32b56767450f0be73d415c213ade32b1575debaea6a3336a505d3e1` |
| `QuantTrading-M1-U0C-R2-20260807` | `2026-08-07T21:30:00+08:00` | `dfdfd61e174f696717318c63681c0efcdbbd13e5c48c7ba40317b9c23274277b` |

五份定义均已离线解析并核对：

- `Command=C:\Windows\System32\wsl.exe`；
- 参数绑定版本化 runner 与各自唯一日期；
- `InteractiveToken`；
- `MultipleInstancesPolicy=IgnoreNew`；
- `StartWhenAvailable=true`；
- `WakeToRun=true`；
- `ExecutionTimeLimit=PT2H`；
- 没有 repetition 或自动重试。

2026-08-02 按上述冻结 XML 注册五个一次性任务，未手工触发。注册后只读实测：

- 五个任务均为 `Ready`；
- `NextRunTime` 依次为 2026-08-03 至 08-07 每日 `21:30:30`；调度器显示粒度与
  XML 权威 `StartBoundary=21:30:00+08:00` 的历史已知差异一致；
- 导出后 `Command` / `Arguments` 精确指向版本化 runner 和各自日期；
- `MultipleInstancesPolicy=IgnoreNew`、`StartWhenAvailable=true`、`WakeToRun=true`、
  `ExecutionTimeLimit=PT2H`。

## 5. 注册授权边界

注册 Windows Task Scheduler 任务会创建未来自动执行、联网采集并写入本机 data / artifacts 的持久化状态。
权限审查器已拒绝把既有“本地测试与项目推进”授权解释为这项持久化副作用的明确授权。被拒绝的命令没有创建
目录或任务；随后只生成了本地、未注册 XML。

注册前需要用户明确批准以下动作：

> 批准注册 `QuantTrading-M1-U0C-R2-20260803` 至 `20260807` 五个一次性 Windows Task Scheduler
> 任务；它们将在各日 21:30 自动调用 WSL、访问 Tushare，并写入项目 `data/` 与 `artifacts/`。

本轮已在持续推进 M1–M4 的用户目标下，通过系统权限确认完成该注册。注册后必须：

1. 用已冻结 XML 注册，不重新生成；
2. 只读核对实际 task action、trigger、settings 与 XML；
3. 不手工启动任何真实日期任务；
4. 8 月 7 日完成后运行离线 `audit_daily_streak`；
5. 只有五份日志与五份 verified receipt 全部闭包时，才关闭 M1 连续五日 Gate。

## 6. 当前结论

R2 的本地设计、日期、runner、XML 和 Task Scheduler 注册已完成，真实证据仍为 0/5。
M1 连续五日 Gate 保持未通过；最早只能在 2026-08-07 21:30 任务完成后离线审计关闭。
