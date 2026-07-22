# XP0-R2 Windows Reference 目录持久化与失败恢复返工任务单

日期：2026-07-18  
角色：主 Agent 根据 XP0-R1 外部独立复验冻结第二轮返工；实现与复验必须使用不同的全新外部会话  
状态：已授权实施；XP0/M3/M4 与任何 Gate 均未关闭

## 1. 已确认事实

- Windows 真实产品路径调用 `m3_reference._fsync_directory()` 时，`os.open(directory, os.O_RDONLY)`
  抛 `PermissionError`（errno 13），使 `_write_dataclass_once()` 映射为
  `G1_REFERENCE_IO_FAILED`。
- `tests/unit/test_m3_reference.py` 的 Windows autouse fixture 将生产 `_fsync_directory` 替换为 no-op，
  因而默认绿测不能证明产品路径可运行。
- `os.link(temporary, path)` 已成功而随后目录 fsync 失败时，目标文件是完整、已做文件级 fsync 的 hardlink，
  但调用方收到失败；当前测试没有冻结该可恢复状态。
- Microsoft 的 Windows API 合同要求用 `FILE_FLAG_BACKUP_SEMANTICS` 才能获得目录 handle；官方列出的目录
  handle 可用函数不包含 `FlushFileBuffers`。本机 Win32 探针即使成功打开目录，`FlushFileBuffers` 仍返回
  `ERROR_ACCESS_DENIED`。不得用未经证明可用的 ctypes 目录 flush 伪装 POSIX `fsync(dir)`。

## 2. 冻结的跨平台发布合同

### R2.1 文件内容与唯一发布

1. 两个平台都必须先以 exclusive temporary file 写入 canonical payload，`flush` 并 `os.fsync(file_fd)`；文件级
   fsync 失败统一映射 `G1_REFERENCE_IO_FAILED`，不得创建目标路径。
2. 仍以 `os.link(temporary, path)` 作为 no-overwrite 发布原语；目标已存在保持
   `G1_REFERENCE_JOURNAL_INVALID`，其他 link 错误保持 `G1_REFERENCE_IO_FAILED`。
3. 临时文件在所有成功/失败路径都必须清理；不得降低既有 intent 内容校验或 JournalLock 合同。

### R2.2 目录持久化

1. POSIX/Linux 保留真实 `open(directory, O_RDONLY) + fsync + close`；任一步失败映射
   `G1_REFERENCE_IO_FAILED`。
2. Windows 标准用户环境不存在本任务可依赖的、与 POSIX 等价且已验证的目录 fsync。Windows
   `_fsync_directory` 必须显式采用平台分支，在完成文件级 fsync 与 exclusive hardlink 后返回；不得再尝试
   当前必败的 `os.open(directory, O_RDONLY)`，也不得新增 ctypes/第三方依赖。
3. 代码注释/docstring 必须诚实说明 Windows 的边界：保证完整文件在 link 前已 file-fsync，保证 exclusive
   no-overwrite 发布，但不声称提供 POSIX 目录项掉电持久化保证。Windows 绿测仍不能替代 WSL Gate。

### R2.3 hardlink 后目录 fsync 失败的恢复语义

1. `os.link` 成功是“完整不可变目标已可见”的边界；POSIX 后续目录 fsync 失败时仍返回
   `G1_REFERENCE_IO_FAILED`，但保留该完整目标，作为可验证、可重试的恢复状态。
2. 不得在异常处理中先检查 inode 再按路径 unlink：该 check-then-unlink 会引入竞态并可能删除被替换的路径。
3. 下一次同一 spec 调用必须通过既有 `_verify_existing_intent` 验证后继续；不同 spec 或损坏内容仍必须
   `G1_REFERENCE_JOURNAL_INVALID`。报告必须称其为“完整但目录持久化确认失败的可恢复目标”，不得称为成功
   持久化或半文件。

## 3. 必须删除的测试伪装与新增回归

删除 Windows autouse `_windows_reference_dir_fsync_compat`，不得以其他全局 monkeypatch、skip、xfail 或
平台无条件跳过替代。至少新增/修正以下测试：

1. Windows 无 monkeypatch 直接运行 `_fsync_directory(temp_dir)` 与 `_write_dataclass_once()`；后者成功且
   canonical 目标内容可解析。
2. Windows 真实 reference executor 的 stale-lock repeat-run 与 active-lock recovery 集成用例实际执行并通过；
   只允许既有精确能力 skip（例如 WinError 1314 symlink），不得 skip 产品 fsync 路径。
3. Linux 真实 `_fsync_directory` 仍实际调用 `os.open/os.fsync/os.close`；禁止把 Linux 降为 no-op。
4. 注入 file fsync 失败：返回 `G1_REFERENCE_IO_FAILED`、无目标、无 temporary。
5. 注入 link 失败：错误码保持既有合同、无新目标、无 temporary。
6. 注入 hardlink 后 directory fsync 失败：返回 `G1_REFERENCE_IO_FAILED`；目标存在且等于完整 canonical
   payload；temporary 不存在；同 spec 重试可恢复，不同 spec/损坏内容 fail closed。

## 4. 文件白名单

- `src/quant/data/m3_reference.py`
- `tests/unit/test_m3_reference.py`
- `docs/agent/XP0_R2_WindowsReference目录持久化与失败恢复返工交付报告.md`

禁止修改 `_journal_lock.py`、其他生产代码/测试、AGENTS、README、pyproject、配置、`data/**`、
`artifacts/**`、`.git` 与既有任务/报告。禁止联网、真实数据、凭据、安装/升级依赖。

## 5. 实现验证

实现使用全新 `cursor-grok-4.5-high` 会话。Windows 使用 `D:\Miniforge3\python.exe`，WSL 使用
`/home/mabw/AI_Coding_win/QuantitativeTrading` 与 `/home/mabw/miniforge3/bin/conda run -n base`。

至少执行并在交付报告中记录命令、exit code 与简短摘要：

1. 两平台 `tests/unit/test_m3_reference.py` 中新增持久化/失败恢复测试及 stale/active lock 集成子集；
2. 两平台 XP0 journal-lock 文件与 reference 锁相关子集；
3. 两平台定向 Ruff：`src/quant/data/m3_reference.py tests/unit/test_m3_reference.py`；
4. 两平台定向 mypy：`src/quant/data/m3_reference.py`；
5. Windows 无 monkeypatch 的直接产品探针；WSL 真实目录 fsync 探针。

不得机械运行已知耗时的 G1 candidate/workflow 全文件，不得把未运行项目写为通过。

## 6. 外部独立复验

实现停止后，另一全新 `cursor-grok-4.5-high` 会话只读生产代码、实现测试与既有报告，唯一允许写：

- `docs/agent/XP0_R2_WindowsReference目录持久化与失败恢复独立复验报告.md`

复验除逐项映射本任务合同外，必须增加实现者未使用的对抗反例：

- 临时恢复旧 autouse 思路但在测试调用前强制还原生产函数，证明 Windows 产品路径本身通过；临时插件不得入库；
- directory fsync 在 link 后抛错，随后将目标内容篡改或用不同 spec 重试，必须 fail closed；
- Windows 平台分支不得吞掉 file fsync、link、temporary cleanup 或 JSON 校验错误；
- Linux monkeypatch/spy 证明真实目录 fsync 分支被调用，不接受仅以测试通过推断。

复验报告必须准确记录 pass/skip/error；不得宣布主验、XP0、M3/M4 或任何 Gate 通过。

## 7. 停止条件

- 需要改变公共六码错误合同、改用 overwrite 发布、引入第三方依赖或 ctypes；
- 需要删除目标文件但无法证明不会竞态删除替换者；
- 试图用 Windows no-op 全局 monkeypatch、skip/xfail 或 collect-only 宣称产品路径通过；
- 触碰白名单外文件、真实网络/数据、凭据或外部状态。
