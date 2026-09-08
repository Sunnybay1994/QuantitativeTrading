# M4-UA006-R1 Rebuilt2 Fresh Formal Runtime Bootstrap 独立初验报告

日期：2026-08-26<br>
状态：`FIX_EVIDENCE_REVIEW_PASS`（merge-regression fix source validation 证据复验；既有 `REWORK_REVIEW_PASS` / `DOC_REVIEW_PASS` / `EVIDENCE_REVIEW_PASS` 保留；STATIC_ONLY；**不**关闭 UA-M4-006；**不**宣称 main `937787` 回归已解除、PAPER/soak/Linux Gate）<br>
task id：`M4-UA006-R1-REBUILT2-FRESH-FORMAL-RUNTIME-BOOTSTRAP`<br>
exact base / HEAD：`74586cea97ba93aa3e25cca0dd4921cf214de54c`<br>
branch：`codex/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`<br>
worktree：`artifacts/dev_worktrees/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`<br>
审查角色：同一独立外部初验 Agent 续任 FIX EVIDENCE_REVIEW（未参与实现；未委派；只写本报告）

任务书：`docs/framework/tasks/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap任务书.md`（§14）<br>
交付：`docs/framework/deliveries/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap交付报告.md`（§14）<br>
唯一写路径：本报告（exact7 #7）

---

## F0. FIX EVIDENCE_REVIEW 裁决

**`FIX_EVIDENCE_REVIEW_PASS`**

无 P0 / P1。本轮零 Python / stage / commit；未改 production / tests / task / delivery。

### F0.1 本轮 evidence root 与 summary

| 项 | 交付/任务书 | 现场 |
| --- | --- | --- |
| evidence root | `artifacts/agent_runs/m4-r1-rebuilt2-merge-regression-fix-validation-20260826T204000Z` | worktree 内路径存在；原生产物齐全 |
| summary SHA256 | `1D39C474FCD239210A2820DFA597569A586ED6D5F67BA2E72CB45F528983D105` | **一致** |
| 收口行 | `PASS=ALL_STAGES`；`RESOURCE_RELEASE=0xF00` | **一致** |

### F0.2 分阶段核对（exit / stdout SHA / 原生尾）

| 阶段 | exit | stdout SHA256 | 原生要点 | 结论 |
| --- | --- | --- | --- | --- |
| identity | 0 | `28FA03AB2411236AA8730C84EED73E742A8D3236A8F5EB5BEE429350B4B9D8AE` | worktree 内 `quant` + `paper_formal_bootstrap` | PASS |
| focused | 0 | `75EA2DBD7DA088ECFE8C30DA9A23E36C644FDA4069407A4A513F0E082B373684` | **`27 passed, 4 skipped`** | PASS |
| ruff | 0 | `82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18` | `All checks passed!`；runner 实际扫 bootstrap + unit + integration | PASS |
| mypy | 0 | `0C37C4158C91EF55C724BA017BF6465F26018199BADB08E3FF13F98ACDF056C2` | `Success: no issues found in 2 source files`；production2=`paper_formal_bootstrap.py`+`__init__.py` | PASS |
| cold | 0 | `B8C733A05EC86C2B4D5E302D0EA60C28C3D238F0B3EBBEA413DC28BADD48E8A0` | cold-import 打印 bootstrap 路径 | PASS |
| scope | 0 | `76712757202381B649A0669EC9036936A2893E7042B93CA9F4BE1C325F1062F5` | `ACTUAL_COUNT=6`；`APPROVED_EXACT7=PASS`；`CACHED_COUNT=0`；`DIFF_CHECK=PASS`；`CACHE_RESIDUE=0`；`EXACT_F00_FOREIGN=0`；`WRITER=7692\|BelowNormal\|0x3` | PASS |

各阶段 stderr SHA 均为空文件 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`。summary 内嵌 stage SHA 与现场文件 **逐项一致**。

### F0.3 exact7 / 资源 / writer

| 检查 | 结论 |
| --- | --- |
| dirty6 ⊆ exact7 | scope 期望六路径 = task/delivery/review/bootstrap/unit/integration（`__init__.py` 不脏）；`APPROVED_EXACT7=PASS` |
| cached0 | `CACHED_COUNT=0` |
| diff | `DIFF_CHECK=PASS` |
| temp/cache residue | `CACHE_RESIDUE=0`；现场 worktree 无 `.tmp`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`；scratch 已清理 |
| process / 0xF00 | `EXACT_F00_FOREIGN=0`；summary `RESOURCE_RELEASE=0xF00` |
| writer 不扰动 | `WRITER=7692\|BelowNormal\|0x3` |

### F0.4 历史 main merge regression（不得洗白）

| 项 | 文档 | 现场 |
| --- | --- | --- |
| root | `…/m4-r1-rebuilt2-main-merge-regression-20260826T203000Z` | 顶层 `artifacts/agent_runs/…` 仍在 |
| summary | `EE48534311AF5162375B5F23B44706666F019ACA914FA305EC361E0530A86151` | **一致** |
| focused | **`26 passed / 1 skipped / 1 failed`**；UNRUN 后续 | 尾计数一致；失败测名保留 |
| main `937787` | **仍** `MERGED_REGRESSION_STOP` | 任务书 §14 / 交付 §14.3 **明确否决**“回归已解除” |

### F0.5 production/tests 相对 `REWORK_REVIEW_PASS` 未漂移

| 路径 | REWORK §M0.2 SHA | 本轮现场 | 结论 |
| --- | --- | --- | --- |
| `paper_formal_bootstrap.py` | `50BC7464B779639B03AF4715F923C0FEEF3B195155886B117AE070DCC1A05C22` | 同 | **未漂移** |
| `__init__.py` | `A47172D0C25772F7D955565FABB690830B78A473D6AFAB4E7676CF0D47A7B323` | 同 | **未漂移** |
| unit | `342B7019BC70B9C582C658D1383ECF6CCC2FB82E02602D70A5BFC1B1045D47FE` | 同 | **未漂移** |
| integration | `9B67D328CB8465FC690AB8D321574392313698EE1A169FD0B52F72C22DF8CB95` | 同 | **未漂移** |

实现者本轮仅更新 taskbook/delivery（与授权一致）。

### F0.6 不超宣称

| 声明 | 裁决 |
| --- | --- |
| source fix Windows validated（本 worktree） | **允许**（本轮 evidence `PASS=ALL_STAGES`） |
| main `937787` 回归解除 | **否** — 仍 `MERGED_REGRESSION_STOP` |
| UA-M4-006 关闭 | **否** — 仍 OPEN |
| PAPER / soak / Linux Gate | **否** — 仍 OPEN |

### F0.7 文档 SHA（只读核）与 actual scope

| 路径 | SHA256 |
| --- | --- |
| 任务书 §14 | `1B9066FF80B784767FC52EE3595997E3BA1948AA8E43D35F4CFD6D7B719A6206` |
| 交付 §14 | `964DB63DA470F40757E0DBBE9E09E351193E118536143D70352448279F47D6B1` |

**actual scope（本复验可见）**

- 实现者 EVIDENCE_UPDATE 写集：task + delivery（production/tests 冻结）
- 本审查唯一写入：review
- exact7 脏集仍为 6（含本 review）；未 stage/commit；evidence 未清

### F0.8 收口

**`FIX_EVIDENCE_REVIEW_PASS`**

---

## M0. MERGE-REGRESSION REWORK 裁决

**`REWORK_REVIEW_PASS`**

无 P0 / P1。本轮零 Python / stage / commit；未改 production/tests/task/delivery。

### M0.1 核对矩阵

| 项 | 结论 |
| --- | --- |
| 生产唯一门禁变更 | `verify_existing_formal_paper_runtime_bootstrap`：`policy is not bootstrap.policy` → `policy != bootstrap.policy`（`git diff HEAD` 仅此 1 行语义变更） |
| policy helper 合同 | `paper_policy.verify_existing_paper_execution_policy` fresh-load 后 `fresh != policy` 则 STALE，否则 **return fresh**；`_attestation` compare=False → 值相等可非同对象 |
| binding / account | 仍 `is not` → STALE |
| broker / execution capability | 仍 `is not`（含 `execution.broker_store is not broker`） |
| chain join / identity payload / bytes | verify 仍 `_require_public_chain_join` + `_identity_payload(chain=…bootstrap.policy…)` + `_sha256` / `_stable_projection`；未放宽 |
| 错误码 / 调用顺序 | STALE/INVALID 映射与 preflight→policy→binding→account→capability→join→barrier→identity 顺序未改 |
| mint / reopen `is` 闸 | execution_store↔chain 等 `is` 路径未改 |
| `__init__.py` | SHA `A47172D0C25772F7D955565FABB690830B78A473D6AFAB4E7676CF0D47A7B323`（相对 REWORK3 冻结表不变） |
| unit 反例 | `test_verify_accepts_fresh_equal_policy_not_same_object_and_retains_bootstrap`；`test_verify_rejects_policy_field_attestation_or_environment_drift`；`test_verify_keeps_binding_account_and_capability_identity_is_gates` |
| integration | `verify_existing… is first` 保留；注释说明 policy 可值相等非同对象 |
| unit EOF LF | 文件末字节恰一 `0x0A`；非双 EOF |
| task/delivery 诚实 | 保留 main `937787bc` merge 后回归 STOP；focused **`26 passed / 1 skipped / 1 failed`**；Ruff/mypy/cold/scope **UNRUN**；summary SHA `EE485343…` |
| merge-regression evidence | 顶层 `artifacts/agent_runs/m4-r1-rebuilt2-main-merge-regression-20260826T203000Z`；summary SHA **一致**；尾 `1 failed, 26 passed, 1 skipped`；`STOP=STAGE_FAILED:focused` |
| 不超宣称 | UA-M4-006 / PAPER / soak / Linux Gate 仍 OPEN；本轮不宣称新 Windows 全绿 |

### M0.2 本轮现场 SHA（实现者脏集 + 冻结项）

| 路径 | SHA256 | 相对 REWORK3/E1 |
| --- | --- | --- |
| `src/quant/execution/paper_formal_bootstrap.py` | `50BC7464B779639B03AF4715F923C0FEEF3B195155886B117AE070DCC1A05C22` | 变更（policy 闸） |
| `src/quant/execution/__init__.py` | `A47172D0C25772F7D955565FABB690830B78A473D6AFAB4E7676CF0D47A7B323` | **不变** |
| `tests/unit/test_paper_formal_bootstrap.py` | `342B7019BC70B9C582C658D1383ECF6CCC2FB82E02602D70A5BFC1B1045D47FE` | 变更（反例） |
| `tests/integration/test_paper_formal_bootstrap.py` | `9B67D328CB8465FC690AB8D321574392313698EE1A169FD0B52F72C22DF8CB95` | 变更（注释） |
| 任务书 §13 | `9645B0FA7A28A590ADE41795AE3075DF15DACAA0EEE9B8B9C84DA030488A75D7` | 实现者写集（只读核；其后 §14 更新见 F0.7） |
| 交付 §13 | `F6BD590F0D1D79BD54274292E429CFD2F020CFEEE0D879C60A7CAC678C419971` | 实现者写集（只读核；其后 §14 更新见 F0.7） |

### M0.3 actual scope（REWORK 复验可见脏集）

实现者批准写集（相对 `74586cea` working tree，未 stage）：

1. `src/quant/execution/paper_formal_bootstrap.py`
2. `tests/unit/test_paper_formal_bootstrap.py`
3. `tests/integration/test_paper_formal_bootstrap.py`
4. `docs/framework/tasks/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap任务书.md`
5. `docs/framework/deliveries/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap交付报告.md`

本审查唯一写入：

6. `docs/framework/reviews/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap独立初验报告.md`

exact7 未扩；`paper_policy.py` 未改；未 stage/commit。

### M0.4 收口

**`REWORK_REVIEW_PASS`**

历史 §D0/§E0–§E6 与附录裁决保留。main `937787bc` 仍处于 merge-regression STOP 叙事；修复后须另申请合流/回归验证，不得继承失败轮冒充全绿。

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

> 注：上表为 DOC_REVIEW 当时现场；§13/§14 后任务书/交付 SHA 以 §M0.2 / §F0.7 为准。

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

> 注：上表为 EVIDENCE_REVIEW 冻结快照；merge-regression STATIC_REWORK 后的现场 SHA 见 §M0.2 / §F0.5。

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

## M1. MERGE-REGRESSION REWORK 收口

**`REWORK_REVIEW_PASS`**

唯一写入：本报告。无 P0/P1。

---

## F1. FIX EVIDENCE_REVIEW 收口

**`FIX_EVIDENCE_REVIEW_PASS`**

唯一写入：本报告。无 P0/P1。

---

# 附录 T — REWORK3（`REWORK3_REVIEW_PASS`）

F7 AST 扫描消除自匹配；production/unit/`__init__` 冻结；无 P0/P1/P2。

# 附录 S — REWORK2（`REWORK2_REVIEW_PASS`）

`binding.cost_schedule_identity` join/经济稳定闭合。

# 附录 R — REWORK1（`REWORK1_REVIEW_FAIL`）→ 已由 REWORK2 闭合

# 附录 A — 首轮（`REVIEW_FAIL`）→ 已由后续返工闭合
