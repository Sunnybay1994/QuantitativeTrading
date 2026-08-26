# M4-UA006-R1 Rebuilt2 Fresh Formal Runtime Bootstrap 独立初验报告

日期：2026-08-26<br>
状态：`DOC_REVIEW_PASS`（文档规范化；既有裁决仍为 `EVIDENCE_REVIEW_PASS`；STATIC_ONLY；**不**关闭 UA-M4-006；**不**宣称 PAPER/soak/Linux Gate/主验合流）<br>
task id：`M4-UA006-R1-REBUILT2-FRESH-FORMAL-RUNTIME-BOOTSTRAP`<br>
exact base / HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`<br>
branch：`codex/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`<br>
worktree：`artifacts/dev_worktrees/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`<br>
审查角色：同一独立外部初验 Agent 续任 DOC_REVIEW（未参与实现；未委派；只写本报告）

任务书：`docs/framework/tasks/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap任务书.md`（§12）<br>
交付：`docs/framework/deliveries/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap交付报告.md`（§12）<br>
唯一写路径：本报告（exact7 #7）

---

## D0. DOC_REVIEW 裁决

**`DOC_REVIEW_PASS`**

| 项 | 结论 |
| --- | --- |
| 本报告规范化 | CRLF→LF；trailing whitespace=0；恰一 EOF LF；硬换行改 `<br>` |
| 任务书 SHA | `0A27D223BFDF21815D4CA5627435800E473E5FBB9120F273252975EBE8F425D1`（现场一致；LF-only、trail=0、恰一 EOF LF） |
| 交付 SHA | `905CF847166FB857352F6C794D875A5E26B56302FFB2E050D81F2DF5904FABF8`（现场一致；同上） |
| 语义/证据边界 | 相对 §E0–§E6 **未漂移**；证据 summary SHA / 冻结实现 SHA / Gate 边界未改写 |
| production/tests/`__init__.py` | SHA 仍等于 REWORK3/E1 冻结表 |
| 自指 SHA | 本报告正文**不含**自指/prefix 全量 SHA 表；无需重算自指 |
| 零 Python / stage / commit | 本轮遵守；未改其他路径 |

---

## E0. EVIDENCE_REVIEW 裁决

**`EVIDENCE_REVIEW_PASS`**

留存 evidence 与任务书/交付口径一致，且**未洗白** VALIDATION1 失败史：

| 链 | 核对 |
| --- | --- |
| VALIDATION1 | summary SHA `1F4065B1…` 命中；identity exit=0；focused exit=1、stdout SHA `83D89FEC…`；尾计数 **`1 failed, 23 passed, 4 skipped`**；失败为 `test_integration_module_does_not_patch_forbidden_runtime_roots` 断言自匹配；`STOP=STAGE_FAILED:focused`；Ruff/mypy/cold/scope 未产物 |
| REWORK3 / F7 | integration 现为 AST Call 扫描 + 片段组合；正向仍调用真实 `_system_temp_root()` / `_actual_project_root()`；先验 `REWORK3_REVIEW_PASS` |
| VALIDATION2 | summary SHA `F452D75E…` 命中；identity/focused/ruff/mypy/cold **exit=0**；focused **`24 passed, 4 skipped`**、stdout SHA `48EE027B…`；scope **exit=1**、stderr SHA `40C23A68…`（PowerShell `Where-Object`/`try` carrier）；`STOP=STAGE_FAILED:scope`；**非** exact7 产品脏集失败 |
| SCOPE1 | summary SHA `552D75D6…` 命中；`PASS=ALL_SCOPE_CHECKS`；status `ACTUAL_COUNT=7` ⊆ exact7；cached=0；diff_check/residue/process exit=0 |
| 冻结实现 | production/unit/`__init__.py`/integration SHA **等于** REWORK3 报告冻结表 |
| 不超宣称 | 可承认 `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED`（任务书 §12 上限）；**UA-M4-006 / PAPER / soak / Linux Gate / 主验合流仍 OPEN** |

无 P0/P1/P2。本轮零 Python/stage/commit；evidence 未清。

证据根（worktree 内相对 `artifacts/agent_runs/…`，与文档路径一致）：

- `…/m4-ua006-r1-rebuilt2-validation1-20260826T194000Z`
- `…/m4-ua006-r1-rebuilt2-validation2-20260826T195000Z`
- `…/m4-ua006-r1-rebuilt2-validation2-scope1-20260826T200000Z`

---

## E1. 冻结实现 SHA（相对 REWORK3）

| 路径 | SHA256 | 结论 |
| --- | --- | --- |
| `src/quant/execution/paper_formal_bootstrap.py` | `D0FD1B6750F2B82D66FDE4AB75B864560FF9AFE22F72C7C7BB5BEF3B6FAB1749` | 不变 |
| `src/quant/execution/__init__.py` | `A47172D0C25772F7D955565FABB690830B78A473D6AFAB4E7676CF0D47A7B323` | 不变 |
| `tests/unit/test_paper_formal_bootstrap.py` | `50E1F6F3CA788439024AE679038109727BC09EEEE756DD776D05EA943E856891` | 不变 |
| `tests/integration/test_paper_formal_bootstrap.py` | `363E994FCCC00E805DA91AE81FE2A2B89C5F7BF5A5649086742D455D0A05AD45` | 不变（REWORK3 后冻结） |

EVIDENCE_UPDATE 写集：仅任务书 + delivery（实现者声明）；本审查只写 review。`git diff --cached` 空；HEAD=`9cc5b56d…`。

---

## E2. 分轮证据矩阵

### E2.1 VALIDATION1（历史失败保留）

| 项 | 交付/任务书 | 现场 |
| --- | --- | --- |
| summary SHA | `1F4065B1C22061370BCBACB9EEB705945BA97D8D708093E6B09DAE3479DB4C51` | **一致** |
| identity | PASS | exit=`0`；stdout_sha `7368FAC6…` |
| focused | 23/4/1 fail | exit=`1`；stdout_sha `83D89FEC…`；失败测名与自匹配断言原文一致 |
| 后续阶段 | UNRUN | root 无 ruff/mypy/cold/scope 产物 |
| STOP | `STAGE_FAILED:focused` | summary 一致 |
| 洗白 | 禁止 | 交付 §12.1 / 任务书 §12 **保留**失败表述 |

### E2.2 REWORK3

| 项 | 结论 |
| --- | --- |
| 先验审查 | `REWORK3_REVIEW_PASS`（本报告附录 T） |
| 代码面 | `_forbidden_paper_runtime_root_patches` + synthetic 自证仍在；真实 authority 调用仍在 |
| 与 V2 | focused 自 23+1fail → 24 pass，与 F7 修复叙事一致 |

### E2.3 VALIDATION2（产品绿 + scope carrier STOP）

| 阶段 | exit | stdout/stderr SHA（与交付） | 结论 |
| --- | --- | --- | --- |
| identity | 0 | `28FA03AB…` | PASS |
| focused | 0 | `48EE027B…`；尾 `24 passed, 4 skipped` | PASS |
| ruff | 0 | `82B3E6A6…`；`All checks passed!` | PASS |
| mypy | 0 | `0C37C415…`；`Success: no issues found in 2 source files` | PASS |
| cold | 0 | `8AD59E64…`；列出 production2 路径 | PASS |
| scope | 1 | stderr `40C23A68…`；`Where-Object`/`try` 语法 | **carrier STOP only** |
| summary | — | `F452D75E…` | **一致**；`STOP=STAGE_FAILED:scope` |

不得把 V2 outer STOP 读成产品红；交付 §12.3 边界诚实。

### E2.4 SCOPE1

| 检查 | exit | 要点 |
| --- | --- | --- |
| status | 0 | `ACTUAL_COUNT=7`；七路径 = exact7（task/delivery/review/bootstrap/`__init__`/unit/integration） |
| cached | 0 | `CACHED_COUNT=0` |
| diff_check | 0 | `DIFF_CHECK=PASS` |
| residue | 0 | `TEMP_CACHE_RESIDUE=0` |
| process | 0 | `EXACT_F00_COUNT=0` |
| summary | — | SHA `552D75D6…`；`PASS=ALL_SCOPE_CHECKS` |

---

## E3. 发现分级

### 无 P0 / P1 / P2

证据根存在、summary/stage SHA 与原生尾计数/失败测名/carrier stderr 均可对上；实现冻结；无 Gate/UA 超宣称。

### P3（不阻 PASS）

文档写 `artifacts/agent_runs/…`，本机解析为 **worktree 内** `artifacts/dev_worktrees/…/artifacts/agent_runs/…`（非仓库顶层 `artifacts/agent_runs`）。路径语义在 worktree 合同下成立；若中央索引只认顶层根，需运维对齐——**不**构成证据造假。

---

## E4. 不超宣称核对

| 声明 | 裁决 |
| --- | --- |
| `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED` | **允许**（§12 上限；V1 史+REWORK3+V2 产品绿+SCOPE1） |
| UA-M4-006 关闭 | **否** — 仍 OPEN |
| PAPER / soak / Linux Gate | **否** |
| 主验合流 / 实盘准入 | **否** |
| VALIDATION1 整包 PASS | **否** — 失败史保留 |

---

## E5. 本轮边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold（本审查） | **未运行** |
| stage / commit / 清 evidence | **未做** |
| 只写 | 本 review 报告 |

---

## E6. EVIDENCE_REVIEW 收口

**`EVIDENCE_REVIEW_PASS`**

唯一写入：本报告。

---

## D1. DOC_REVIEW 收口

**`DOC_REVIEW_PASS`**

三文档语义与证据边界未漂移；production/tests 冻结；本报告已 LF 规范化。

---

# 附录 T — REWORK3（`REWORK3_REVIEW_PASS`）

F7 AST 扫描消除自匹配；production/unit/`__init__` 冻结；无 P0/P1/P2。

# 附录 S — REWORK2（`REWORK2_REVIEW_PASS`）

`binding.cost_schedule_identity` join/经济稳定闭合。

# 附录 R — REWORK1（`REWORK1_REVIEW_FAIL`）→ 已由 REWORK2 闭合

# 附录 A — 首轮（`REVIEW_FAIL`）→ 已由后续返工闭合
