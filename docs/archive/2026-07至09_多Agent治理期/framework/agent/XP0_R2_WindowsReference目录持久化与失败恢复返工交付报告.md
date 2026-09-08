# XP0-R2 Windows Reference 目录持久化与失败恢复返工交付报告

日期：2026-07-18  
角色：外部返工实现 Agent（全新会话；只实现，不兼任独立复验或主验）  
模型：`cursor-grok-4.5-high`  
任务单：[`XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md`](XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md)  
前置：XP0-R1 独立复验暴露的 Windows 产品路径 `PermissionError` 与 autouse no-op 伪装  
状态：**返工已交付待独立复验**；**不声称初验 / 主验 / XP0 / M3 / M4 / 任何 Gate 通过**

## 1. 结论摘要

| 项 | 结果 |
|---|---|
| R2.1 文件 fsync + exclusive hardlink | **保持**：临时文件 exclusive 写入 → file fsync → `os.link`；错误码未改 |
| R2.2 Windows 目录持久化分支 | **已修**：`win32` 在 file-fsync + link 后直接返回；不再 `os.open(dir, O_RDONLY)`；docstring 诚实声明无 POSIX 目录项掉电保证 |
| R2.2 POSIX 目录 fsync | **保持**：真实 `open + fsync + close`；失败映射 `G1_REFERENCE_IO_FAILED` |
| R2.3 hardlink 后 dir fsync 失败 | **冻结**：保留完整目标；临时文件清理；同 spec `_ensure_intent` 可恢复；不同 spec/损坏 fail closed；无 check-then-unlink |
| 删除 Windows autouse no-op | **已删** `_windows_reference_dir_fsync_compat`；无全局 monkeypatch/skip/xfail 替代 |
| 验证范围 | 见 §4；未跑 G1 candidate/workflow 全文件 |

## 2. 修改文件（白名单）

| 文件 | 目的 |
|---|---|
| `src/quant/data/m3_reference.py` | `_fsync_directory` 平台分支 + 诚实边界说明；`_write_dataclass_once` 注释冻结 link 后失败可恢复语义 |
| `tests/unit/test_m3_reference.py` | 删除 autouse 替身；新增无 monkeypatch 发布、Linux spy、file/link/dir-fsync 失败与恢复测试 |
| 本报告 | 交付证据 |

未改：`_journal_lock.py`、其他生产/测试、AGENTS、README、pyproject、配置、`data/**`、`artifacts/**`、`.git`、既有任务/报告。

## 3. 合同对照

### R2.1 / R2.2

- 两平台：exclusive tmp → `flush` + `os.fsync(file_fd)` → `os.link` → `_fsync_directory`。
- Windows：`_fsync_directory` 显式 `sys.platform == "win32"` 早返回；不引入 ctypes/第三方。
- Linux：仍真实目录 fsync；测试 spy 证明调用 `os.open(O_RDONLY)` / `os.fsync` / `os.close`。

### R2.3

- `os.link` 成功后目标为完整、已 file-fsync 的 hardlink。
- 随后目录 fsync 失败仍返回 `G1_REFERENCE_IO_FAILED`，但**不删除目标**（报告用语：完整但目录持久化确认失败的可恢复目标；非成功持久化、非半文件）。
- 同 spec 经 `_verify_existing_intent` 继续；不同 spec / 损坏内容 → `G1_REFERENCE_JOURNAL_INVALID`。

### 测试

| 测试 | 覆盖 |
|---|---|
| `test_fsync_directory_and_write_dataclass_once_without_monkeypatch` | 两平台无替身产品路径 |
| `test_linux_fsync_directory_invokes_open_fsync_close` | Linux 真实目录 fsync（Windows skip） |
| `test_write_dataclass_once_file_fsync_failure_leaves_no_target` | file fsync 失败：无目标、无 tmp |
| `test_write_dataclass_once_link_file_exists_is_journal_invalid` | 已存在 → `JOURNAL_INVALID` |
| `test_write_dataclass_once_link_oserror_is_io_failed` | link OSError → `IO_FAILED` |
| `test_write_dataclass_once_dir_fsync_fail_after_link_is_recoverable` | link 后 dir fsync 失败可恢复 + fail closed |
| 既有 stale/active lock 集成 | 无 fsync 产品路径 skip；仅保留既有 WinError 1314 能力 skip |

## 4. 验证命令、exit code 与摘要

环境：Windows `D:\Miniforge3\python.exe` + `PYTHONPATH=...\src`；  
Linux `wsl` → `/home/mabw/AI_Coding_win/QuantitativeTrading` + `conda run -n base`。

### 4.1 持久化 / 失败恢复 + stale/active lock

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `pytest tests/unit/test_m3_reference.py -q -p no:cacheprovider -k "fsync_directory or write_dataclass_once or stale_lock_file_allows_repeat or active_flock_and_sigkill"` | **0** | **7 passed / 1 skipped**（Linux-only spy） |
| Linux | 同上 | **0** | **8 passed** |

### 4.2 JournalLock 全文件 + reference 锁子集

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | **22 passed** |
| Linux | 同上 | **0** | **20 passed / 4 skipped**（Windows-only） |
| Win | `pytest test_m3_reference.py -k "lock or JOURNAL_WRITER or stale_lock or concurrent or flock"` | **0** | **3 passed** |
| Linux | 同上 | **0** | **3 passed** |

### 4.3 定向 Ruff / mypy

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `ruff check src/quant/data/m3_reference.py tests/unit/test_m3_reference.py` | **0** | All checks passed |
| Linux | 同上 | **0** | All checks passed |
| Win | `mypy src/quant/data/m3_reference.py` | **0** | Success: no issues |
| Linux | 同上 | **0** | Success: no issues |

### 4.4 产品探针

| 平台 | 探针 | exit | 摘要 |
|---|---|---:|---|
| Win | 无 monkeypatch：`_fsync_directory(tmp)` + `_write_dataclass_once` → canonical bytes | **0** | `WIN_PROBE_OK` |
| Linux | spy：`_fsync_directory` 真实调用 open/fsync/close | **0** | `LINUX_DIR_FSYNC_PROBE_OK ['open', 'fsync', 'close']` |

未运行：G1 candidate/workflow 全文件及其他白名单外目标。

## 5. 风险与未决

- Windows **不**提供 POSIX 目录项掉电持久化；Windows 绿测 ≠ WSL Gate。
- hardlink 后目录 fsync 失败时调用方见 `G1_REFERENCE_IO_FAILED`，但目标已可见；调用方必须按可恢复状态处理，不能当作半写失败去 unlink。
- 本报告仅为实现自测证据；**独立复验与主验尚未执行**。

## 6. 停止条件核对

未改变公共六码错误合同；未改用 overwrite 发布；未引入 ctypes/第三方；未对目标做 check-then-unlink；未用全局 no-op/skip 伪装产品路径；未触碰白名单外文件、网络、凭据或外部状态。
