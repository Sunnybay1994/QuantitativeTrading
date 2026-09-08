# XP0-R2 Windows Reference 目录持久化与失败恢复独立复验报告

日期：2026-07-18  
角色：外部独立复验 Agent（全新会话；未参与 XP0-R2 实现）  
模型：`cursor-grok-4.5-high`  
任务单：[`XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md`](XP0_R2_WindowsReference目录持久化与失败恢复返工任务单.md)  
实现证据：[`XP0_R2_WindowsReference目录持久化与失败恢复返工交付报告.md`](XP0_R2_WindowsReference目录持久化与失败恢复返工交付报告.md)  
前置：[`XP0_R1_Python310_Fixture与测试平台能力独立复验报告.md`](XP0_R1_Python310_Fixture与测试平台能力独立复验报告.md)（RW1/RW2）  
状态：**独立复验通过（本返工合同范围内）**；**不声称主验 / XP0 / M3 / M4 / 任何 Gate 通过**

## 0. 边界与方法

| 项 | 内容 |
|---|---|
| 只读 | 生产代码、实现者测试、AGENTS、任务单/交付/R1 复验报告 |
| 唯一写入 | 本报告 |
| Windows | `D:\Miniforge3\python.exe`；`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src` |
| Linux | `wsl.exe` → `/home/mabw/AI_Coding_win/QuantitativeTrading` + `/home/mabw/miniforge3/bin/conda run -n base` |
| 禁止 | 联网、真实数据、凭据、安装依赖、改生产/实现测试、触碰 `data/**`/`artifacts/**`/`.git` |
| 对抗探针 | 仅 `%TEMP%\xp0_r2_adv_*` 与 WSL `/tmp/xp0_r2_adv_*`；**未入库**（仓库内 `xp0_r2*` 探针命中 = 0） |

## 1. 结论总览

| 面 | 结果 |
|---|---|
| R2.1 文件 fsync + exclusive hardlink + 临时清理 | **PASS** |
| R2.2 Windows `_fsync_directory` 平台早返回；无 ctypes；诚实 docstring | **PASS** |
| R2.2 POSIX 真实 `open+fsync+close`（未降为 no-op） | **PASS**（实现测 + L_ADV spy） |
| R2.3 link 后 dir fsync 失败：保留完整目标、可恢复、无 check-then-unlink | **PASS** |
| 删除 Windows autouse no-op；无全局 skip/xfail 替代 | **PASS**（源码无 `_windows_reference_dir_fsync_compat`） |
| 无 monkeypatch 产品路径 + stale/active lock 集成 | **PASS**（两平台） |
| 任务书强制对抗反例（§6） | **PASS**（见 §4） |
| **复验结论** | **通过（仅 XP0-R2 返工合同）** |

## 2. 合同逐项映射

### 2.1 R2.1 / R2.2 / R2.3（源码只读）

| ID | 冻结要求 | 证据 | 结论 |
|---|---|---|---|
| R2.1 | exclusive tmp → flush + file fsync → `os.link`；错误码不变；临时必清 | `_write_dataclass_once` L1692–1720；file/link 失败测无目标、无 tmp | **PASS** |
| R2.2 Win | `win32` 早返回；不再 `os.open(dir, O_RDONLY)`；无 ctypes | `_fsync_directory` L1739–1740；docstring L1729–1737；`ctypes` 仅出现在 docstring 否定句 | **PASS** |
| R2.2 POSIX | 真实 open/fsync/close；失败 → `G1_REFERENCE_IO_FAILED` | L1741–1748；`test_linux_fsync_directory_invokes_open_fsync_close`；L_ADV spy | **PASS** |
| R2.3 | link 后 dir fsync 失败仍 `IO_FAILED` 但保留完整目标；同 spec 恢复；异 spec/损坏 `JOURNAL_INVALID`；无目标 unlink | 注释 L1705–1707；`unlink` 仅 temporary；恢复测 + ADV tamper | **PASS** |

### 2.2 必须删除的伪装与新增回归

| # | 要求 | 证据 | 结论 |
|---|---|---|---|
| 1 | Win 无 monkeypatch `_fsync_directory` + `_write_dataclass_once` | `test_fsync_directory_and_write_dataclass_once_without_monkeypatch` 两平台绿；ADV_WIN_PRODUCT | **PASS** |
| 2 | stale/active lock 真实执行；仅允许既有 1314 类能力 skip | Win/Linux stale+active 子集绿；无 fsync 产品路径 skip | **PASS** |
| 3 | Linux 真实目录 fsync | spy 测 Win skip / Linux 执行；L_ADV `['open','fsync','close']` | **PASS** |
| 4 | file fsync 失败：IO_FAILED、无目标、无 tmp | 实现测 + ADV_WIN_NOSWALLOW / L_ADV | **PASS** |
| 5 | link 失败：既有错误码、无新目标、无 tmp | FileExists→`JOURNAL_INVALID`；OSError→`IO_FAILED` | **PASS** |
| 6 | link 后 dir fsync 失败可恢复 + fail closed | 实现测 + ADV_TAMPER / L_ADV_TAMPER | **PASS** |

## 3. 定向验证命令（复验实跑）

### 3.1 Windows（`D:\Miniforge3\python.exe`）

| 命令 | exit | 摘要 |
|---|---:|---|
| `pytest test_m3_reference.py -k "fsync_directory or write_dataclass_once or stale_lock_file_allows_repeat or active_flock_and_sigkill"` | **0** | **7 passed / 1 skipped**（Linux-only spy） |
| `pytest test_m3_journal_lock.py` | **0** | **22 passed** |
| `pytest test_m3_reference.py -k "lock or JOURNAL_WRITER or stale_lock or concurrent or flock"` | **0** | **3 passed** |
| `ruff check m3_reference.py test_m3_reference.py` | **0** | All checks passed |
| `mypy m3_reference.py` | **0** | Success: no issues |

### 3.2 Linux（WSL `conda run -n base`）

| 命令 | exit | 摘要 |
|---|---:|---|
| 同上 fsync/lock `-k` | **0** | **8 passed** |
| `pytest test_m3_journal_lock.py` | **0** | **20 passed / 4 skipped**（Windows-only） |
| reference lock `-k` | **0** | **3 passed** |
| 定向 ruff / mypy | **0** / **0** | All checks passed / Success |

未运行：G1 candidate/workflow 全文件；不记通过。

## 4. 实现者未使用的对抗反例（任务书 §6）

| ID | 场景 | 结果 |
|---|---|---|
| ADV-RESTORE | 临时 pytest plugin：先挂旧式 Win no-op autouse，再在 `pytest_runtest_call` 强制还原生产 `_fsync_directory`；跑 `test_fsync_directory_and_write_dataclass_once_without_monkeypatch` + `test_executor_stale_lock_file_allows_repeat_run` | **PASS**（2 passed，PLUGIN_EXIT=0；插件仅 `%TEMP%`） |
| ADV_WIN_PRODUCT | 无 monkeypatch：直接 `_fsync_directory` + `_write_dataclass_once` | **PASS**（`ADV_WIN_PRODUCT_OK`） |
| ADV_TAMPER | link 后注入 dir fsync 失败 → 完整目标保留 → 同 spec 恢复 → **不同 spec** 与 **篡改内容** → `G1_REFERENCE_JOURNAL_INVALID` | **PASS** |
| ADV_WIN_NOSWALLOW | Win 早返回分支下：file fsync / link OSError / FileExists / 坏 JSON 仍正确映射；成功路径无 tmp | **PASS** |
| L_ADV_SPY | Linux 仅在 `_fsync_directory` 窗口 spy：`open(O_RDONLY)+fsync+close` | **PASS**（`['open','fsync','close']`） |
| L_ADV_TAMPER / FILE_LINK | Linux 同 tamper/diff-spec 与 file/link fail-closed | **PASS** |

对照 R1 §3.3：此前无 monkeypatch 时 `_fsync_directory` → `PermissionError` errno 13；本轮同路径不再因目录 open 失败。

## 5. skip / error

| 项 | 记录 |
|---|---|
| Win skip | `test_linux_fsync_directory_invokes_open_fsync_close`（`skipif win32`，预期） |
| Linux skip | journal_lock 中 4 个 Windows-only |
| error | 定向命令与对抗探针 **零失败** |
| 探针脚本失误 | 首次 ADV_WIN_NOSWALLOW 因探针未 unlink 坏 JSON 目标导致误报；修正探针后 **PASS**（非生产缺陷） |

## 6. 未验证 / 明确不声称

- 主 Agent 终验、XP0 / M3 / M4 勾选、任何 Gate 关闭。
- Windows 目录项掉电持久化（合同明确不提供；Win 绿测 ≠ WSL Gate）。
- G1 candidate/workflow 全文件执行。
- 真实网络、`data/**`、凭据、依赖安装。

## 7. 返工项

**无。** 本轮未发现需按「现象—根因—规则—最小复现—新增测试—通过条件」回写的合同级缺陷。

## 8. 下一步（主 Agent）

1. 可进入第 4 步主验；主验仍须独立复核 SSOT/跨模块不变量，不得以本报告代替。  
2. 不得将本报告表述为 XP0 或任何 Gate 已关闭。  
3. 主验若保留对抗项，建议继续要求「绕过任何测试伪装、直接打生产路径」与「link 后失败可恢复目标」语义核对。
