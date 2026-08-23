# XP0-R1 Python 3.10、Fixture 与测试平台能力独立复验报告

日期：2026-07-18  
角色：外部独立复验 Agent（全新会话；未参与 XP0 或 R1 实现）  
模型：`cursor-grok-4.5-high`  
任务单：[`XP0_R1_Python310_Fixture与测试平台能力返工任务单.md`](XP0_R1_Python310_Fixture与测试平台能力返工任务单.md)  
实现证据：[`XP0_R1_Python310_Fixture与测试平台能力返工交付报告.md`](XP0_R1_Python310_Fixture与测试平台能力返工交付报告.md)  
前置初验：[`XP0_Linux_Windows跨平台JournalLock独立初验报告.md`](XP0_Linux_Windows跨平台JournalLock独立初验报告.md)  
状态：**复验不通过**（R1/R3/R4 与多数修订范围绿测成立，但 Windows 生产 `m3_reference._fsync_directory` 为真实缺陷；实现者测试 autouse no-op 掩盖产品路径；**不得宣称产品路径通过**；**不声称主验 / Gate / M3 / XP0 通过**）

## 0. 边界与方法

| 项 | 内容 |
|---|---|
| 只读 | 生产代码、实现者测试、AGENTS、配置、data、artifacts、.git、任务单/交付/初验报告 |
| 唯一写入 | 本报告 |
| Windows | `D:\Miniforge3\python.exe`；`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src`；workspace `F:\AI_Coding\QuantitativeTrading` |
| Linux | `wsl.exe` → `/home/mabw/AI_Coding_win/QuantitativeTrading` + `/home/mabw/miniforge3/bin/conda run -n base` |
| 禁止 | 联网、真实数据、凭据、安装/升级依赖、修改白名单外任何文件（含生产代码与实现者测试） |
| 对抗探针 | 仅 `%TEMP%` / WSL 可读临时脚本；临时 pytest plugin 仅用于绕过 autouse，不入仓库 |

## 1. 结论总览

| 面 | 结果 |
|---|---|
| R1 `isjunction` feature detection | **PASS**（实现者测 + 复验 ADV 普通/模拟 reparse） |
| R2 reference fixture 闭包 / setup error | **部分 PASS**：id 闭合与零 setup `KeyError` 成立；**Windows 锁集成产品路径未举证** |
| R3 symlink/fifo 特权窄 skip | **PASS**（Win skip 精确；非 1314 不 skip；Linux 实际执行） |
| R4 `AGENTS.md` §1.1 ↔ §8 | **PASS**（只读核对） |
| 修订验证范围 §2.1–2.5 绿测命令 | **多数 exit 0**（见 §3）；candidate/workflow 全文件按任务单不跑 |
| **关键对抗：绕过 autouse 后生产 `_fsync_directory` / reference executor** | **FAIL / 确认真实生产缺陷** → `PermissionError` errno 13 → `G1_REFERENCE_IO_FAILED`；且 hardlink 后文件可残留 |
| **复验结论** | **不通过** |

## 2. R1–R4 与修订验证范围逐项映射

### 2.1 返工项

| ID | 任务书通过条件 | 复验证据 | 结论 |
|---|---|---|---|
| R1 | 无原始 `AttributeError`；普通路径可 acquire；真实/属性 reparse 仍稳定码拒绝；六码不变 | Win journal 22 passed；Linux 20 passed / 4 skipped；ADV-A/B/C 与 L_ADV-A/B/C；源码 `getattr(os.path, "isjunction", None)` | **PASS** |
| R2 | 两平台 reference 锁集成与共享 fixture 链通过，零 setup error | fixture 真实闭合 `n=1503`；happy/stale/active 在 **带 autouse no-op** 下通过；**绕过 no-op 后** `test_executor_stale_lock_file_allows_repeat_run` → `G1_REFERENCE_IO_FAILED` | **不通过（产品路径）** |
| R3 | 无特权 Windows 不再 1314 失败；报告 skip；Linux 仍执行；JournalLock 替代反例仍过 | Win backfill 120 passed / 11 skipped；planning+run_g1 51 passed / 3 skipped；ADV-G/G2；Linux backfill 131 / planning 18 / run_g1 36 全执行；L_ADV symlink | **PASS** |
| R4 | §1.1 WSL 路径更新；允许任务书指定 Windows 反馈环；禁 WSL→Windows conda；Win≠Gate | `AGENTS.md` L53–57 与 §8 对齐 | **PASS** |

### 2.2 修订验证范围（任务书 §2）

| # | 范围 | 证据摘要 | 结论 |
|---|---|---|---|
| 1 | 两平台 JournalLock 全文件 | Win 22 passed；Linux 20 passed / 4 skipped | **PASS** |
| 2 | 两平台 backfill/reference 锁与 fixture；零 setup error | backfill 锁子集两平台 4 passed；reference 锁相关 Win 6p/3s、Linux 9p（k 过滤）；**但 Win 产品 fsync 路径失败** | **fixture PASS / 产品锁集成 FAIL** |
| 3 | Win backfill/planning/run_g1 能力适配；Linux 聚焦回归 | Win 全文件绿（含 skip）；Linux planning+run_g1 绿 | **PASS** |
| 4 | 两平台 G1 四文件 collect；Win 全量 collect | 两平台 G1 **112 collected**；Win 全量 **1378 collected** | **PASS**（计数以本机为准） |
| 5 | 白名单 Ruff/mypy | 两平台 ruff All checks passed；mypy Success（三源文件） | **PASS** |
| 6 | 不跑 candidate/workflow 全文件 | 未跑；不记通过 | **遵守** |

## 3. 命令、exit code 与摘要

### 3.1 Windows（`D:\Miniforge3\python.exe`）

| 命令 | exit | 摘要 |
|---|---:|---|
| `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | 22 passed / 17.02s |
| `pytest tests/unit/test_m3_backfill_requests.py -q` | **0** | **120 passed / 11 skipped** |
| backfill `-k "lock or JOURNAL_WRITER or stale_lock or concurrent"` | **0** | 4 passed |
| reference `-k "stale_lock or active_flock or journal_layout or journal_state_machine or reconcile_cross_source_happy"` | **0** | **6 passed / 3 skipped** / 107 deselected（**依赖 autouse fsync no-op**） |
| `test_executor_stale_lock…` + `test_executor_active_flock…` | **0** | 2 passed（**同上，被 no-op 掩盖**） |
| `pytest test_m3_g1_planning.py test_m3_run_g1.py -q` | **0** | **51 passed / 3 skipped** |
| G1 四文件 `--collect-only -q` | **0** | 112 collected |
| 全量 `--collect-only -q` | **0** | 1378 collected |
| `ruff check` 白名单 6 文件 | **0** | All checks passed |
| `mypy` `_journal_lock` + `m3_backfill` + `m3_reference` | **0** | Success |

### 3.2 Linux（WSL `conda run -n base`）

| 命令 | exit | 摘要 |
|---|---:|---|
| `pytest tests/unit/test_m3_journal_lock.py -q` | **0** | 20 passed / 4 skipped |
| `pytest tests/unit/test_m3_backfill_requests.py -q` | **0** | 131 passed |
| backfill 锁子集 | **0** | 4 passed |
| reference 同 Win `-k` 过滤 | **0** | **9 passed** / 107 deselected（Linux 无 fsync no-op；真实 dir fsync） |
| `pytest test_m3_g1_planning.py -q` | **0** | 18 passed |
| `pytest test_m3_run_g1.py -q` | **0** | 36 passed |
| G1 四文件 `--collect-only` | **0** | 112 collected |
| `ruff check` 白名单 | **0** | All checks passed |
| `mypy` 三源文件 | **0** | Success |

### 3.3 绕过 autouse 的产品路径（任务书强制）

| 探针 | exit / 结果 | 摘要 |
|---|---|---|
| 直接调用 `m3_reference._fsync_directory(tmpdir)` | 捕获异常 | `PermissionError` **errno 13** Permission denied |
| `_write_dataclass_once`（无 monkeypatch） | 捕获 | `M3ReferenceError: G1_REFERENCE_IO_FAILED`；**`intent.json` 已存在于磁盘**（hardlink 成功后 fsync 失败） |
| `hold_journal_writer_lock` + `_write_dataclass_once` | 捕获 | 同上 `G1_REFERENCE_IO_FAILED`；intent 残留 |
| 临时 plugin `pytest_runtest_call` 在测试体前恢复生产 `_fsync_directory`，重跑 `test_executor_stale_lock_file_allows_repeat_run` | **1** | **FAILED**：`_ensure_intent` → `_write_dataclass_once` L1701 → `G1_REFERENCE_IO_FAILED` |
| 同测在默认 autouse no-op 下 | **0** | 1 passed（**仅测试伪装通过**） |

结论：交付报告 §6.1 风险项 **已独立证实为真实生产缺陷**；不得用 monkeypatch 宣称 Windows reference / journal 发布产品路径通过。

## 4. 任务书未公开对抗反例

| ID | 场景 | 结果 |
|---|---|---|
| ADV-A | `del os.path.isjunction` 后普通绝对 root acquire/release | **PASS**（Win + Linux） |
| ADV-B | 缺 `isjunction` + 模拟 `st_file_attributes` 含 reparse 位 | `_is_reparse_stat` → **True**（不得放行）**PASS** |
| ADV-C | 缺 `isjunction` + 普通 `st_file_attributes=0` | → **False**（不得误拒）**PASS** |
| ADV-H | 真实 `_build_inputs` 闭合；少一条 / 多一条 id | 闭合 `n=1503`；缺失/多余均 `AssertionError` fail-closed **PASS** |
| ADV-G / G2 | `_require_symlink`：碰撞 WinError 183 / 注入 winerror=5 不得 skip；注入 1314 才 skip | **PASS** |
| L_ADV symlink | Linux 真实 `symlink_to` 执行 | **PASS**（`is_symlink=True`） |
| L_ADV fsync | Linux 生产 `_fsync_directory` | **PASS** |
| ADV-F / F2 / executor | 见 §3.3 | **确认生产缺陷** |

## 5. 源码只读要点（不改代码）

- `_journal_lock._is_reparse_stat`：`getattr(os.path, "isjunction", None)` + `S_ISLNK` + `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`。
- `test_m3_reference._build_inputs`：按 per-symbol `suspend_d` 造响应；`plan_ids != response_ids` → `AssertionError`。
- `_require_symlink`（backfill/reference/planning/run_g1）：仅 `win32` 且 `winerror == 1314` 时 `pytest.skip`。
- **阻塞点**：`tests/unit/test_m3_reference.py` autouse `_windows_reference_dir_fsync_compat` 在 Win 上将 `ref._fsync_directory` 置 no-op；生产 `m3_reference._fsync_directory` 仍为 `os.open(dir, O_RDONLY)` + `os.fsync`（约 L1713–1718），本机 Permission denied。
- `AGENTS.md` §1.1 已用 `/home/mabw/AI_Coding_win/QuantitativeTrading`，并允许任务书指定 Windows Miniforge；保留禁 WSL 调 Windows conda、Win≠Gate。

## 6. 返工项（复验不通过）

> 格式：现象 — 根因 — 应遵循规则 — 最小复现 — 需新增测试 — 通过条件

### RW1 — Windows 生产 `_fsync_directory` / reference journal 发布失败（被测试 no-op 掩盖）

- **现象**：无 monkeypatch 时 `_fsync_directory` → `PermissionError` errno 13；`_write_dataclass_once` / `execute_baostock_reference_plan` → `G1_REFERENCE_IO_FAILED`。绕过 autouse 后 `test_executor_stale_lock_file_allows_repeat_run` 失败。默认测试套件因 autouse no-op 仍绿。
- **根因**：Windows 上对目录 `os.open(..., O_RDONLY)` 无 `FILE_FLAG_BACKUP_SEMANTICS`（或等价）时无法打开目录 FD；生产代码未做平台适配。`m3_reference.py` 不在 R1 白名单，实现者用测试侧 no-op 绕过以便锁映射可测。
- **应遵循规则**：任务书复验要求「不得用测试 monkeypatch 宣称产品路径通过」；AGENTS 测试应覆盖真实可观察行为；交付风险不得用绿测掩盖为已修复。
- **最小复现**：
  1. `D:\Miniforge3\python.exe -c "from pathlib import Path; import tempfile; from quant.data.m3_reference import _fsync_directory; _fsync_directory(Path(tempfile.mkdtemp()))"` → Permission denied；
  2. 临时 plugin 在 `pytest_runtest_call` 恢复生产 `_fsync_directory` 后跑 `test_executor_stale_lock_file_allows_repeat_run` → exit 1 / `G1_REFERENCE_IO_FAILED`。
- **需新增/修复**：扩白名单修复生产 `_fsync_directory`（例如 Win 跳过 dir fsync，或使用可打开目录的 Win32 标志）；**删除或严格限制**仅掩盖缺陷的 autouse no-op；补充「无 monkeypatch 的 Windows journal 写路径」回归；覆盖 hardlink 成功后 fsync 失败时的清理/失败语义（当前 **intent 文件可残留**）。
- **通过条件**：Windows 无测试 monkeypatch 时，reference executor 锁集成（至少 stale lock + active lock recovery）真正 exit 0；直接调用 `_fsync_directory` / `_write_dataclass_once` 不再因目录 open 权限失败；失败路径不得留下半发布 journal 文件（或合同明确并测试该语义）。

### RW2 —（观察，非阻塞 R1–R4 字面）hardlink 后 fsync 失败的残留文件

- **现象**：ADV-F2 中 `_write_dataclass_once` 抛 `G1_REFERENCE_IO_FAILED` 时 `intent.json` 已存在。
- **根因**：`os.link` 成功后才 `_fsync_directory`；fsync 异常映射为 IO 失败但未回滚已 link 的目标。
- **应遵循规则**：journal 发布失败语义应 fail-closed 且可恢复；与 RW1 一并设计。
- **最小复现**：见 ADV-F2。
- **需新增测试**：fsync 失败后目标路径不存在，或明确 RECOVER 可处理残留并测通。
- **通过条件**：与 RW1 一并验收。

说明：R1/R3/R4 本身未见需再返工的合同级缺陷；**阻塞复验通过的是 RW1（及关联 RW2）**。R2 的 fixture 闭合已满足，但任务书要求的 reference 锁集成在 Windows **产品路径**上仍未成立。

## 7. skip / error 说明

- **Windows skip（预期）**：无 symlink 特权（1314）相关构造；无 mkfifo 的 FIFO。backfill 11；planning+run_g1 3；reference journal_layout 同类 3 skipped（k 过滤子集）。
- **Linux skip**：journal_lock 中 Windows-only（含缺 isjunction 的 reparse 对抗）共 4。
- **零 setup KeyError**：reference 不再因缺失 per-symbol `suspend_d` id 崩溃。
- **产品路径 error**：见 §3.3 / RW1（非测试套件默认输出，但是复验强制项）。

## 8. 未验证 / 明确不声称

- 主 Agent 终验、Gate 关闭、M3/M4/XP0 里程碑勾选。
- G1 candidate/workflow **全文件执行**（按修订范围不跑）。
- 真实网络、真实 `data/**`、凭据、依赖安装。
- Windows 持锁物理 directory-entry TOCTOU（既有 XP0 声明与 Linux 不等价）。

## 9. 下一步建议（主 Agent）

1. **不要**将 XP0-R1 或 XP0 标为独立复验/主验/Gate 通过。  
2. 冻结扩白名单任务：修复 `m3_reference._fsync_directory`（及 `_write_dataclass_once` 失败清理语义）；去掉掩盖性 Win autouse no-op；强制无 monkeypatch 的 Windows reference 锁集成回归。  
3. R1/R3/R4 与 fixture 闭合可保留；新实现仍须「外部实现 → 外部独立初验」闭环。  
4. 主验若启动，须保留「绕过测试伪装、直接打生产路径」的未公开反例。
