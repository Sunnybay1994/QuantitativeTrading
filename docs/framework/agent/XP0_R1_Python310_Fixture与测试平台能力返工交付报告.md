# XP0-R1 Python 3.10、Fixture 与测试平台能力返工交付报告

日期：2026-07-18  
角色：外部返工实现 Agent（全新会话；只实现，不兼任独立复验或主验）  
模型：`cursor-grok-4.5-high`  
任务单：[`XP0_R1_Python310_Fixture与测试平台能力返工任务单.md`](XP0_R1_Python310_Fixture与测试平台能力返工任务单.md)  
前置：[`XP0_Linux_Windows跨平台JournalLock实现交付报告.md`](XP0_Linux_Windows跨平台JournalLock实现交付报告.md) /
[`XP0_Linux_Windows跨平台JournalLock独立初验报告.md`](XP0_Linux_Windows跨平台JournalLock独立初验报告.md)  
状态：**返工已交付待独立复验**；**不声称初验 / Gate / 主验通过**

## 1. 结论摘要

| 项 | 结果 |
|---|---|
| R1 `isjunction` feature detection | **已修**：`getattr`；无 `AttributeError`；reparse 仍 fail-closed |
| R2 reference per-symbol `suspend_d` fixture | **已修**：request id 与 plan 闭合；零 setup `KeyError` |
| R3 Windows symlink/fifo 特权 | **已适配**：仅 WinError 1314 / 无 mkfifo 时窄 skip |
| R4 `AGENTS.md` §1.1 ↔ §8 | **已去冲突**：WSL 路径更新；允许任务书指定 Windows 反馈环 |
| 修订验证范围 | 见 §4；未跑 candidate/workflow 全文件执行 |

## 2. 修改文件（白名单）

| 文件 | 目的 |
|---|---|
| `src/quant/data/_journal_lock.py` | `_is_reparse_stat`：`getattr(os.path, "isjunction", None)` |
| `tests/unit/test_m3_journal_lock.py` | 缺 `isjunction` 普通路径可 acquire；Windows reparse 仍拒绝 |
| `tests/unit/test_m3_reference.py` | per-symbol `suspend_d` + id 闭合断言；symlink/fifo helper；Windows 测试侧 `_fsync_directory` no-op（见风险）；active holder 等待加长 |
| `tests/unit/test_m3_backfill_requests.py` | `_require_symlink` / `_require_fifo` |
| `tests/unit/test_m3_g1_planning.py` | `_require_symlink` |
| `tests/unit/test_m3_run_g1.py` | `_require_symlink` |
| `AGENTS.md` | 仅 §1.1 环境边界与 §8 对齐 |
| 本报告 | 交付证据 |

## 3. 返工项对照

### R1

- `_is_reparse_stat` 不再无保护调用 `os.path.isjunction`。
- 仍用 `S_ISLNK` + `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` fail-closed。
- 六码公共接口未改。

### R2

- `_build_inputs` 为每条 `suspend_d` 按 `ts_code`/`start_date`/`end_date`/`suspend_type` 造响应。
- `plan_ids == response_ids` 显式断言；不等则 `AssertionError`（fail closed）。
- stale lock / active lock + kill recovery 两平台均可执行并通过。

### R3

- 仅当 `sys.platform == "win32"` 且 `winerror == 1314` 时对 symlink 构造 `pytest.skip`。
- 其他 `OSError` 继续失败；禁止按 `os.name` 整类跳过。
- FIFO：无 `os.mkfifo` 或创建失败 → skip（能力缺失）；Linux 仍真实执行。

### R4

- §1.1 默认 WSL 路径改为 `/home/mabw/AI_Coding_win/QuantitativeTrading`。
- 允许具体任务书指定 Windows Miniforge 反馈环。
- 保留：禁止从 WSL 调 Windows conda；Windows 绿测 ≠ WSL Gate。

## 4. 验证命令、exit code 与摘要

环境：Windows `D:\Miniforge3\python.exe` + `PYTHONPATH=...\src`；  
Linux `wsl` → `/home/mabw/AI_Coding_win/QuantitativeTrading` + `conda run -n base`。

### 4.1 JournalLock 全文件

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | 22 passed |
| Linux | 同上 | **0** | 20 passed / 4 skipped（Windows-only） |

### 4.2 backfill / reference 锁与 fixture

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `pytest test_m3_backfill_requests.py -q` | **0** | **120 passed / 11 skipped**（原 11 failed→1314 skip） |
| Win | backfill `-k "lock or JOURNAL_WRITER or stale_lock or concurrent"` | **0** | 4 passed |
| Linux | backfill 全文件 | **0** | **131 passed** |
| Linux | backfill 锁子集 | **0** | 4 passed |
| Win | `test_reconcile_cross_source_happy_path_full_closure` | **0** | 1 passed（fixture 链闭合） |
| Win | `test_executor_stale_lock_file_allows_repeat_run` + `test_executor_active_flock_and_sigkill_recovery` | **0** | **2 passed** |
| Linux | reference `-k "stale_lock or active_flock or journal_layout or journal_state_machine"` | **0** | **8 passed** |

### 4.3 planning / run_g1 特权适配

| 平台 | 命令 | exit | 摘要 |
|---|---|---:|---|
| Win | `pytest test_m3_g1_planning.py test_m3_run_g1.py -q` | **0** | **51 passed / 3 skipped**（原 3 failed→1314） |
| Linux | `pytest test_m3_g1_planning.py -q` | **0** | 18 passed |

### 4.4 collect / 静态检查 / 探针

| 项 | exit | 摘要 |
|---|---:|---|
| Win G1 四文件 `--collect-only` | **0** | 112 collected |
| Win 全量 `--collect-only` | **0** | 1359 collected |
| Linux G1 四文件 `--collect-only` | **0** | 112 collected |
| Win/Linux `ruff check` 白名单 | **0** | All checks passed |
| Win/Linux `mypy` `_journal_lock` + `m3_backfill` + `m3_reference` | **0** | Success |
| Win/Linux 探针：`del os.path.isjunction` 后普通 root acquire | **0** | `plain_ok` |
| candidate/workflow **全文件执行** | — | **按任务单不跑**；不记通过 |

## 5. skip / error 说明

- **Windows skip（预期）**：无 `SeCreateSymbolicLinkPrivilege`（WinError 1314）时的 symlink 构造用例；无 `mkfifo` 的 FIFO 用例。backfill **11**；planning+run_g1 **3**；reference journal_layout 中 symlink/fifo 同类 skip。
- **Linux skip**：journal_lock 中 Windows-only 用例（含缺 `isjunction` 的 reparse 对抗）。
- **零 setup error**：reference 不再因缺失 `suspend_d` request id 崩溃。
- **无无条件整类 skip**；非 1314 异常仍失败。

## 6. 风险与未决（供复验 / 主验）

1. **Windows `m3_reference._fsync_directory`**：生产代码对目录 `os.open(..., O_RDONLY)` + `fsync` 在本机返回 `Permission denied`（errno 13）。该文件**不在**本返工白名单。测试文件用 **autouse monkeypatch** 将 `_fsync_directory` 置为 no-op，仅在 Windows 解除 journal 发布阻塞以便锁映射可测；**Linux 保持真实 dir fsync**。后续需扩白名单修生产路径（例如 BACKUP_SEMANTICS 或 Windows 跳过 dir fsync），否则无 monkeypatch 的真实 Windows reference 写 journal 仍会 `G1_REFERENCE_IO_FAILED`。
2. **未声称**独立复验、Gate、主验或 XP0 关闭。
3. **未执行** G1 candidate/workflow 全文件；留给 M3 跨包回归。
4. Windows 持锁物理 directory-entry TOCTOU 与 Linux 仍不等价（既有 XP0 声明）。

## 7. 回滚

恢复上表白名单文件即可；无 `data/`、`artifacts/`、依赖安装、联网或 `.git` 变更。
