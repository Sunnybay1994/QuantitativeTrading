# M1 HK CA P1 PRE-B R4 descriptor open-instance continuity 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；Availability Receipt v3 / `VerifiedHkBarBundle` 的开发态 PRE-B 合同通过主验**

## 1. 验收范围

本轮复核 PRE-B 任务单 §11–§13、R3 的 same-object/same-number descriptor reuse 旁路、R4 实现交付、
全新独立复验及当前 anchor/signing 实现。本结论只关闭开发态 v3 availability、四 root retained read 与
process-local capability 合同，不改写任何正式 02983/01065 data、journal 或 HK60 plan。

## 2. 契约复核

### 2.1 原始 open-instance continuity

POSIX 每个 root、实际读取的后代目录及文件均保留 original fd 与同次 `F_DUPFD_CLOEXEC` 得到的 private
duplicate。fresh assertion 不只比较 inode：它在保存初始 `F_GETFL` 后临时翻转 original 的 `O_NONBLOCK`，
要求 duplicate 同步观察到 shared open-file-description flag，并在 `finally` 精确恢复；设置、观察或恢复
任何一步失败均 fail closed。同一物理对象重新打开到相同整数 fd 不共享 OFD，不能复用旧 capability。

Windows 每个 original handle 由 `DuplicateHandle` 产生 private duplicate，并使用 KernelBase
`CompareObjectHandles` 证明两者仍指向同一 kernel object；同一对象重新打开且复用相同整数 handle 也不成立。
实现没有在 primitive 缺失时降级到仅比较 file-id。

### 2.2 全窗口锚与签发顺序

四个权威 root 及所有实际读取的 descendant/file original/duplicate 均保持到
`_capability_attestation(..., anchors=...)` 内最后一次 `assert_namespaces()`。实现先验证全部 live/open-instance，
再验证路径 namespace，随后计算 attestation 与构造 exact capability；`finally` 关闭失败会覆盖待返回结果，
capability 不逃逸。

### 2.3 清理和异常边界

close 为 terminal/idempotent，并在一个 descriptor 关闭失败时继续尝试其余全部 original/private duplicate。
POSIX flag 恢复失败、Windows `CompareObjectHandles` hostile、partial teardown 与 public load/verify 异常均收敛
为稳定码，`cause/context=None`，不泄露 marker/path。独立复验 50 轮 Windows/WSL descriptor 计数未发现泄漏。

## 3. 验证证据

实现者完整定向证据：

- Windows：`173 passed, 1 skipped`；Ruff PASS；mypy 4 files PASS；
- WSL base `/mnt/f`：`174 passed`；Ruff PASS；mypy 4 files PASS。

独立复验新增并通过：root/descendant/file same-object/same-number reopen、private duplicate reuse、POSIX
restore failure、Windows hostile CompareObjectHandles、partial teardown、50 轮 descriptor 泄漏与异常图。
独立复验同样得到 Windows `173 passed, 1 skipped`、WSL `174 passed`，两平台 Ruff/mypy PASS。

主 Agent 精选验证：

- Windows R4 四组矩阵：`21 passed, 72 deselected`；
- Windows 定向 Ruff：PASS；mypy 2 source files：PASS；
- WSL base 同一 R4 矩阵：`21 passed, 72 deselected`；
- `git diff --check`：PASS。

大量 warning 为既有 Pandera/Polars deprecation 与 worktree `.pytest_cache` 权限提示，不是本轮合同失败。

## 4. 状态与仍开放事项

PRE-B 开发合同现可作为后续 formal v3 migration 任务的前置，但本报告不表示以下事项已完成：

- 正式 02983/01065 v3 migration/finalize；
- licensed HKEX `01065.HK@2026-05-05` main + supplement/correction bytes 与同版 File Specification；
- HK60 其余批次与最终双 Route Gate；
- 合规 HK ETF Instrument 来源、真实 HK 公司行动/复权、M1 Gate；
- WSL2/ext4 平台终验。

当前 `/mnt/f` 为 DrvFS；Windows 与 WSL/DrvFS 绿测只证明跨平台开发合同。下一步必须另立 formal migration
任务，并继续遵守“不修改旧 v1/v2 receipt、不合成 01065 OHLC、不把开发 capability 冒充正式 evidence”。
