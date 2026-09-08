# XP0 Linux / Windows 跨平台 JournalLock 主 Agent 最终验收报告

日期：2026-07-18  
角色：主 Agent 最终契约、回归与对抗性验收  
状态：**XP0 通过**；解除 M3 HISTORY-PILOT10 的 JournalLock 前置阻塞；不等于 M3/M4 或任何业务 Gate 通过

## 1. 结论

XP0 经原实现、R1、R2 两轮“实现—独立复验”闭环后通过主验。最终实现满足：

- Python `>=3.10` 能力探测不再泄漏 `os.path.isjunction` 的版本差异；Windows reparse/junction 仍 fail closed；
- Linux 使用真实 `flock` 与路径防护，Windows 使用受控的本机 writer lock 语义，公共六码错误合同未改变；
- reference fixture 与当前 per-symbol `suspend_d` 计划闭合，Windows 无 symlink 特权时仅做精确 capability skip；
- reference journal 发布在两平台都先 file-fsync，再以 exclusive hardlink no-overwrite 发布；
- Linux 继续真实 fsync 目录；Windows 明确不虚构 POSIX 目录项掉电持久化能力；
- 删除了曾掩盖 Windows 产品缺陷的 autouse no-op，Windows stale/active lock 与 journal 发布现在直接运行生产路径；
- hardlink 后目录 fsync/close 失败返回 `G1_REFERENCE_IO_FAILED`，保留完整可验证目标；同 spec 可恢复，异 spec
  或篡改内容仍 `G1_REFERENCE_JOURNAL_INVALID`，不做有竞态风险的 check-then-unlink。

因此，XP0 对 M3 有界真实恢复任务的跨平台 writer-lock 与 reference journal 前置条件已经满足。

## 2. 交付闭环

1. 原任务与交付：
   [`XP0_Linux_Windows跨平台JournalLock实现任务单.md`](XP0_Linux_Windows跨平台JournalLock实现任务单.md)、
   [`XP0_Linux_Windows跨平台JournalLock实现交付报告.md`](XP0_Linux_Windows跨平台JournalLock实现交付报告.md)。
2. 原独立初验：
   [`XP0_Linux_Windows跨平台JournalLock独立初验报告.md`](XP0_Linux_Windows跨平台JournalLock独立初验报告.md)。
3. R1 任务、交付与未通过复验：
   [`XP0_R1_Python310_Fixture与测试平台能力返工任务单.md`](XP0_R1_Python310_Fixture与测试平台能力返工任务单.md)、
   [`XP0_R1_Python310_Fixture与测试平台能力返工交付报告.md`](XP0_R1_Python310_Fixture与测试平台能力返工交付报告.md)、
   [`XP0_R1_Python310_Fixture与测试平台能力独立复验报告.md`](XP0_R1_Python310_Fixture与测试平台能力独立复验报告.md)。
4. R2 任务、交付与通过复验：
   [`XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md`](XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md)、
   [`XP0_R2_WindowsReference目录持久化与失败恢复返工交付报告.md`](XP0_R2_WindowsReference目录持久化与失败恢复返工交付报告.md)、
   [`XP0_R2_WindowsReference目录持久化与失败恢复独立复验报告.md`](XP0_R2_WindowsReference目录持久化与失败恢复独立复验报告.md)。

R1 复验发现的 Windows 生产 `_fsync_directory` 失败和测试 autouse 掩盖问题已在 R2 关闭；R2 独立复验无返工项。

## 3. 主验实跑证据

### Windows（`D:\Miniforge3\python.exe`）

| 范围 | 结果 |
|---|---|
| `tests/unit/test_m3_journal_lock.py` | **22 passed** |
| reference/backfill：fsync、write-once、stale/active lock、writer/concurrent 定向子集 | **7 passed / 1 skipped**；skip 为 Linux-only 目录 fsync spy |
| Ruff：JournalLock、reference、backfill 生产与测试白名单 | **All checks passed** |
| mypy：`_journal_lock.py`、`m3_reference.py`、`m3_backfill.py` | **Success** |

### Linux（WSL Miniforge `base`）

| 范围 | 结果 |
|---|---|
| `tests/unit/test_m3_journal_lock.py` | **20 passed / 4 skipped**；skip 为 Windows-only |
| reference/backfill 同一主验子集 | **8 passed** |
| Ruff：同一白名单 | **All checks passed** |
| mypy：同一三生产模块 | **Success** |

首次 WSL 静态命令误写了不存在的 `m3_backfill_requests.py`，Ruff 因路径不存在返回 E902；确认测试实际 import
`quant.data.m3_backfill` 后，以正确的 `src/quant/data/m3_backfill.py` 重跑 Ruff/mypy，均 exit 0。该项是验收命令
笔误，不是产品失败。

## 4. 主 Agent 未公开反例

在 WSL 系统临时目录注入“目录 fsync 已成功、`os.close(directory_fd)` 随后失败”：

- `_write_dataclass_once` 返回 `G1_REFERENCE_IO_FAILED`；
- 完整目标存在，temporary 为零；
- 同 spec `_ensure_intent` 可恢复；
- 篡改目标后同 spec 重试返回 `G1_REFERENCE_JOURNAL_INVALID`；
- 临时目录清理完成。

结果：`XP0_R2_MAIN_CLOSE_FAILURE_RECOVERY_PASS`。

该反例补充覆盖了实现者与独立复验主要针对 fsync 失败的场景，证明 close 失败同样遵守已冻结恢复语义。

## 5. 剩余边界与风险

- Windows 只保证 link 前文件内容已 file-fsync、exclusive no-overwrite 发布；**不提供也不声称** POSIX 等价的
  目录项掉电持久化。Linux/WSL 仍是业务 Gate 与生产语义权威环境。
- XP0 未运行已知耗时的 G1 candidate/workflow 全文件；它们属于后续 M3 跨包 Gate，不在本报告中称通过。
- 本轮未访问真实网络、真实业务数据或凭据。HISTORY-PILOT10 的有界真实请求仍须单独执行、核对 receipt 与
  baseline 增量，不能由 XP0 绿测代替。

## 6. 下一步

按 [`M3_HISTORY-PILOT10真实有界恢复执行任务单.md`](M3_HISTORY-PILOT10真实有界恢复执行任务单.md) 执行最多
10 个缺失 identity / 50 次尝试的真实恢复；执行前必须复核 baseline 仍为 3186 total、114 verified reusable、
3072 missing、`[INDEX]`，执行后逐 receipt 验证并确认增量边界。
