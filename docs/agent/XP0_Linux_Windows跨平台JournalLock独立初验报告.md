# XP0 Linux/Windows 跨平台 Journal Lock 独立初验报告

日期：2026-07-18  
角色：外部独立初验 Agent（全新会话；未参与 XP0 实现）  
模型：`cursor-grok-4.5-high`  
任务单：[`XP0_Linux_Windows跨平台JournalLock实现任务单.md`](XP0_Linux_Windows跨平台JournalLock实现任务单.md)  
实现证据：[`XP0_Linux_Windows跨平台JournalLock实现交付报告.md`](XP0_Linux_Windows跨平台JournalLock实现交付报告.md)  
状态：**初验不通过**（锁专项合同与对抗多数成立，但任务书成功标准未完整举证；**不声称 Gate / 主验通过**）

## 0. 边界与方法

| 项 | 内容 |
|---|---|
| 只读 | 生产代码、实现者测试、AGENTS、README、配置、data、artifacts、.git、任务单/交付报告 |
| 唯一写入 | 本报告 |
| Windows | `D:\Miniforge3\python.exe`；workspace `F:\AI_Coding\QuantitativeTrading` |
| Linux | `wsl.exe` → `/home/mabw/AI_Coding_win/QuantitativeTrading` + `/home/mabw/miniforge3/bin/conda run -n base` |
| 禁止 | 联网、真实数据、凭据、安装/升级依赖、修改白名单外任何文件 |
| 对抗脚本 | 仅 `%TEMP%` / `/tmp` 临时探针，不进入仓库 |

## 1. 结论总览

| 面 | 结果 |
|---|---|
| 锁模块双平台导入 / 六稳定码 / 公共 CM | **PASS** |
| Linux flock 既有对抗（实现者测试） | **PASS**（19 passed / 3 skipped） |
| Windows msvcrt 同进程/跨进程/kill/junction/hardlink | **PASS**（实现者 20 passed + 初验 ADV） |
| 初验未公开对抗（线程互斥、深 junction、锁路径 junction、身份漂移、kill、Linux 物理替换） | **PASS** |
| Windows 物理持锁替换 | **如实区分**：sharing 阻断真实 unlink/rename（WinError 32/5）；实现者 release 漂移为 **SIMULATED** |
| `m3_backfill` 锁相关执行 | **PASS**（Win 4 passed；Linux backfill 全绿） |
| `m3_reference` 锁集成执行 | **BLOCKED**：fixture `KeyError`（80 errors，两平台） |
| Windows backfill 全文件 | **11 failed**（WinError 1314 symlink 特权；非锁） |
| G1 planning / run_g1 | Win：51 passed / 3 failed（symlink 特权）；Linux planning：18 passed |
| G1 candidate / workflow **执行**（非 collect） | candidate 单测可在加长窗口通过；workflow 120s 内未收尾；**不得用 collect 代替** |
| 文档 §8 / README 双平台边界 | **PASS**（只读核对） |
| **初验结论** | **不通过** — 锁实现未见需返工的合同缺陷，但任务书 §3「reference 集成 + M3 定向组通过」未满足举证 |

## 2. 任务书成功标准逐项映射

| # | 成功标准 | 证据 | 结论 |
|---|---|---|---|
| 1 | `_journal_lock.py` 两平台可导入；公共接口与六稳定码不变 | Win 导入探针；两平台 `test_m3_journal_lock.py`；源码六码 | **PASS** |
| 2 | Linux flock/dir-fd/nofollow/身份复验等不回退；对抗测试未删弱 | Linux 19 passed / 3 skipped；源码 posix 路径仍在 | **PASS** |
| 3 | Windows `msvcrt` 非阻塞字节锁；同进程第二句柄与跨进程 → `JOURNAL_WRITER_ACTIVE` | 实现者用例 + ADV1/ADV1b | **PASS** |
| 4 | 正常/强制终止后内核释放；锁文件保留可重获 | 实现者 kill 用例 + ADV4；Linux L_ADV4 | **PASS** |
| 5 | 拒相对路径、缺失/非目录 root、symlink/junction/reparse、锁硬链/目录等；稳定脱敏码 | 实现者用例；ADV2 深 junction；ADV2b 锁路径为 junction | **PASS** |
| 6 | acquire 后与 release 前复验；主异常不覆盖 release 失败 | 实现者测试；ADV3/ADV3c/ADV5；Linux 物理 unlink 替换 L_ADV3 | **PASS** |
| 7 | `m3_backfill`/`m3_reference` 错误映射不变；并发无第二份副作用 | backfill 映射源码只读 + 锁相关 4 测通过；**reference 锁测因 fixture 链无法执行** | **部分 / 未完整举证** |
| 8 | Windows M3 定向组收集并通过；Linux 锁与 M3 定向回归 | 全量 collect 1349；journal/backfill Linux 绿；Win backfill 11 fail；reference 80 errors；G1 不全 | **未满足** |
| 9 | 文档明确双平台反馈环 ≠ Linux Gate | `AGENTS.md` §8；`README.md` 环境说明 | **PASS** |

## 3. 实际命令、退出码与压缩摘要

### 3.1 锁专项（必须执行）

| 命令 | 退出码 | 摘要 |
|---|---:|---|
| Win: `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | 20 passed / 18.32s |
| Linux: 同上 | **0** | 19 passed, 3 skipped / 7.83s |
| Linux: `pytest test_m3_journal_lock.py test_m3_backfill_requests.py -q` | **0** | 150 passed, 3 skipped |

### 3.2 实现报告失败项复现（执行，非 collect）

| 命令 | 退出码 | 摘要与归因 |
|---|---:|---|
| Win: `pytest tests/unit/test_m3_backfill_requests.py -q` | **1** | **11 failed / 120 passed**。失败名均为 symlink/fifo 布局用例；最小复现 `test_controlled_roots_fail_before_any_side_effect[raw_root]` → `OSError: [WinError 1314]`。**归因：Windows 创建 symlink 特权不足，非 journal lock。** |
| Win: `pytest ...backfill... -k "lock or JOURNAL_WRITER or stale_lock or concurrent"` | **0** | **4 passed**（锁相关子集） |
| Win: `pytest tests/unit/test_m3_reference.py -q` | **1** | **36 passed / 80 errors** |
| Linux: 同上 | **1** | **36 passed / 80 errors** |
| 最小复现: `test_reconcile_cross_source_happy_path_full_closure` | **1** | setup `happy_inputs` → `_build_inputs` L395 `KeyError: '0026210c…'` |
| **KeyError 根因（初验独立归因）** | — | `plan.history_batch` 现含 **300** 条带 `ts_code` 的 `suspend_d`；`_build_inputs` 只为无 `ts_code` 的旧式 suspend 造假响应 → **缺失 300 个 request_id**。`sample_plan`/`request_plan` module fixture 依赖 `happy_candidate`→`happy_inputs`，故 **含锁集成的 reference 用例也无法 setup**。**归因：测试 fixture 与 planning 合同漂移，超出 XP0 锁白名单，非 `_journal_lock` 回归。** |
| Win: `pytest test_m3_g1_planning.py test_m3_run_g1.py -q` | **1** | 51 passed / **3 failed**（均为 symlink 创建 WinError 1314） |
| Linux: `pytest test_m3_g1_planning.py -q` | **0** | 18 passed |
| Win/Linux: G1 / 全量 `--collect-only` | **0** | candidate+workflow **58 collected**；全量 **1349 collected** |
| Win: candidate 单测（90s 杀） | **timeout** | 空输出 → 与实现报告“未完成”一致 |
| Win: 同上（**180s**） | **0** | **1 passed** / 103.47s / 36244 pandera warnings。**修正实现报告表述：非锁死，乃超时窗口不足 + 极慢校验。** |
| Linux: 同上单测 | **0** | **1 passed** / 82.31s |
| Linux: `pytest test_m3_g1_workflow.py`（120s） | **timeout** | 120s 仍无收尾；**全文件执行未完成，不能记通过** |
| Win/Linux: `ruff check` 白名单；`mypy` 三源文件 | **0** | All checks passed / Success |

### 3.3 初验对抗反例（实现者未使用或加严）

临时脚本仅在 `%TEMP%`。**均 PASS。**

| ID | 场景 | 结果 |
|---|---|---|
| ADV1 | 嵌套 CM + raw 二次 acquire + 外层持锁下双线程 | 均 `JOURNAL_WRITER_ACTIVE` |
| ADV1b | 无外层双线程竞态 | 恰 1 获取 / 1 ACTIVE |
| ADV2 | 深路径 junction 祖先 | `JOURNAL_LOCK_ROOT_INVALID` |
| ADV2b | `.writer.lock` 本身为 junction | `JOURNAL_LOCK_FILE_INVALID` |
| ADV3 | acquire 后篡改 `held.lock_identity` 再 release | `JOURNAL_LOCK_RELEASE_FAILED` |
| ADV3b | 持锁期间真实 `unlink`/`os.replace` | **失败** WinError **32** / **5**；release 正常。**PHYSICAL 不可达；与实现者 monkeypatch SIMULATED 区分** |
| ADV3c | 篡改 ancestor_identities 后 release | `JOURNAL_LOCK_RELEASE_FAILED` |
| ADV4 | 子进程持锁 → 阻塞 → `kill` → 重获；锁文件仍在 | PASS |
| ADV5 | body 主异常 + release 期 validate 漂移 | 抛出 `RuntimeError` 主异常 |
| L_ADV1 | Linux 双线程互斥 | PASS |
| L_ADV3 | Linux **物理** unlink+重建 directory entry 后 release | `JOURNAL_LOCK_RELEASE_FAILED`（真实覆盖） |
| L_ADV4 | Linux kill 后重获 | PASS |

## 4. 源码只读要点（不改代码）

- 平台分派：`sys.platform == "win32"` → `msvcrt.locking(LK_NBLCK,1)` / 否则 `fcntl.flock`；顶层不再无条件 `import fcntl`。
- Windows：`lstat` + `os.path.isjunction` + `st_file_attributes` reparse 位；无 dir-fd（与 Linux 原语不等价，文档已声明）。
- 错误映射只读：`m3_backfill._map_journal_lock_error` / `m3_reference._map_journal_lock_error` 仍为既有六码映射表。
- `AGENTS.md` §8 与 `README.md` 已写明 Windows 反馈环不替代 WSL Gate。

## 5. 返工项（初验不通过）

> 格式：现象 — 根因 — 应遵循规则 — 最小复现 — 需新增测试 — 通过条件  
> 说明：下列 **R1–R3 不是 `_journal_lock` 实现缺陷**；阻塞的是任务书 §3 举证闭环。锁对抗无合同级返工项。

### R1 — `test_m3_reference` 80 errors 阻断锁集成举证

- **现象**：两平台 `test_m3_reference.py` 大量 ERROR；含 `test_executor_stale_lock_file_allows_repeat_run` / `test_executor_active_flock_and_sigkill_recovery`。
- **根因**：`_build_inputs` 未为 per-symbol `suspend_d`（含 `ts_code`）生成 `VerifiedRawResponse`，与当前 `plan_history_requests` 输出不一致（缺失 300 ids）；module fixture 链拖垮锁测。
- **应遵循规则**：AGENTS.md 测试须覆盖契约；任务书 §3 要求 reference 错误映射与并发副作用可验证；SSOT 以实际 planning 为准，测试 fixture 不得滞后。
- **最小复现**：`D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_reference.py::test_reconcile_cross_source_happy_path_full_closure -q --tb=short` → L395 `KeyError`。
- **需新增/修复测试**：在授权白名单内修复 `_build_inputs`（为每条 `suspend_d` 按 `ts_code`+日期参数造响应），并保证锁集成两测可执行通过。
- **通过条件**：两平台 reference 锁相关用例执行通过（非仅 collect）；不再因 `happy_inputs` setup 失败。

### R2 — Windows backfill/G1 中 symlink 用例 WinError 1314

- **现象**：backfill 11 failed；g1_planning/run_g1 共 3 failed；均在创建 symlink。
- **根因**：当前 Windows 会话无创建 symlink 特权；与 journal lock 无关。锁路径已用 junction 覆盖祖先 reparse。
- **应遵循规则**：任务书允许记录平台限制；不得把特权失败记为锁缺陷；亦不得在无特权环境声称“M3 定向全绿”。
- **最小复现**：`pytest tests/unit/test_m3_backfill_requests.py::test_controlled_roots_fail_before_any_side_effect -q --tb=short`。
- **需新增测试**：非锁模块可考虑无特权时 `skip`；或主 Agent 明确将 symlink 特权用例排除出 XP0 成功标准。
- **通过条件**：要么特权环境全绿，要么任务书书面 carve-out + 锁/junction 路径仍 fail-closed（已满足）。

### R3 — G1 candidate/workflow 全量执行未在实现报告窗口完成

- **现象**：实现报告记“未完成/卡死”；初验 90s 杀进程无输出；加长后 **单测可过**（Win ~103s / Linux ~82s）；Linux **workflow 全文件 120s 仍未收尾**。
- **根因**：极慢（大量 pandera DeprecationWarning，约 3.6 万条/单测）+ 超时窗口过短；**不是** writer lock 死锁（锁专项与 ADV 已否证）。
- **应遵循规则**：任务书要求执行而非 collect；不得把超时记为锁通过或锁失败。
- **最小复现**：对 `test_response_order_and_frame_row_order_stable_identity` 用 ≥180s；对 `test_m3_g1_workflow.py` 用更长窗口或分批。
- **需新增测试**：无（非 XP0）；主验应规定 G1 执行时间盒或降噪策略（若授权）。
- **通过条件**：任务书若坚持“G1 定向执行通过”，须在约定时间盒内跑完并 exit 0；否则主 Agent 缩小 XP0 成功标准为锁+collect+planning。

## 6. 未验证项

- `test_m3_g1_candidate.py` / `test_m3_g1_workflow.py` **全文件**完整执行（仅单测/超时抽样）。
- reference 执行器在 fixture 修复后的并发锁副作用（当前被 R1 阻断）。
- Windows 在持锁下的 **物理** directory-entry TOCTOU（sharing 下不可达；仅 Linux 物理覆盖 + Windows 模拟）。
- 全量 `pytest`（非 collect）、真实网络/数据、任何 Gate 关闭。
- 主 Agent 终验与路线图勾选。

## 7. 下一步建议（主 Agent）

1. **不要**将 XP0 标为 Gate/主验通过。  
2. 决定：扩白名单修 R1 fixture，或修订任务书成功标准、把 reference/G1 全量执行挪出 XP0。  
3. 锁实现本身可进入主验合同复核；主验应保留未公开跨平台反例，并区分 Windows sharing 与 Linux unlink TOCTOU。  
4. 实现者无需就 `_journal_lock.py` 做合同级返工；若扩围修 reference fixture，须重新走「外部实现 → 外部独立初验」。
