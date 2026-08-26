# M3-G8F-R2I Successor Physical Receipt Identity Compatibility 独立初验报告

日期：2026-08-26<br>
身份：未参与本包实现的全新独立静态初验 Agent（STATIC_ONLY）<br>
task id：`M3-G8F-R2I-SUCCESSOR-PHYSICAL-RECEIPT-IDENTITY-COMPAT`<br>
exact base / HEAD：`eca54af513078ca6d000feb544329cba69797948`（一致）<br>
branch：`codex/m3-g8f-r2i-successor-physical-receipt-identity-compat`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2i-successor-physical-receipt-identity-compat`<br>
唯一写入：本报告<br>
结论：**EVIDENCE_REVIEW_PASS**（§9；§8 STATIC_REWORK2 / §7 STATIC_REWORK1 PASS 保留；§0–§6 首轮 **REVIEW_FAIL** 原文保留）<br>
终态上限声明：可确认任务/交付所称 `R2I_WINDOWS_ENGINEERING_VALIDATED` 之**组合**工程证据闭合；**不**表示单轮全绿洗白，**不**关闭 R2W / R2B / actual worker / 真实 Qlib / new root / retained / M3 Gate。

## 0. 审查边界

- 已完整阅读：根 `AGENTS.md`、任务书、交付报告、exact6 之 `successor_runtime.py` 与 unit/integration 测试及对 exact base 的 diff。
- production / tests / 任务书 / 交付：**只读**；未改实现、未改测试、未改任务书、未改交付。
- **STATIC_ONLY**：未运行 Python / pytest / Ruff / mypy / cold / 真实 Qlib / network / actual worker / new root / retained / stage / commit。
- dirty（只读观察）：`M successor_runtime.py`、`M` 两测试、`??` 任务书与交付；未见审查报告以外越界写入；`git diff --check` PASS；cached=0。

## 1. 合同逐项静态核对

| # | 合同点 | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | aggregate `GateExecution.identity` vs physical `scope_key` 分离 | **通过（实现面）** | 删除 `compute_successor_gate_scope_key`/`_GATE_SCOPE_JOIN_VERSION` 与 `__all__` 导出；`_validate_gate_execution` 不再把 ref 绑到 join hash；acceptance 允许 physical≠identity；summary 仍绑真实 `experiment_key` |
| 2 | readiness 双 fold 槽位 + physical key 单射 | **实现面通过 / 强制反例不全** | `len==2` 且 fold 集合 exact；`scope_key` 集合单射；integration/unit 覆盖 key 碰撞；**缺** fold 所有权错配/缺一 fold 定向测（§7.2） |
| 3 | canonical G8 + stage-specific root map | **通过（实现面+测）** | `_resolve_canonical_g8_stage_root`：两 fold `project_stage_root` 唯一且 `== controlled`；`_artifact_roots_for_receipt_stage` acceptance→`{G8}` 其余→`{PROJECT}`；分歧/controlled 漂移/单侧 alias 测存在 |
| 4 | `_unique_refs` 不放宽；terminal 绑 aggregate+physical | **通过（实现面）** | `_unique_refs` 仍拒 path/bytes/semantic-owner 别名；`_build_attestation`/`verify_terminal_attestation` 继续校验 gate identity 与 receipt 复验；schema/字段集合未见收缩 |
| 5 | 任务书 §7 强制反例落地 | **失败** | join 伪装、acceptance 正/负、G8/PROJECT 单侧错 alias、根分歧等有测；**缺** mixed/extra alias（§7.4）与 readiness fold 所有权错配/缺折（§7.2）；path/bytes 复制测未钉死 `_unique_refs` |

## 2. 发现分级

### [P1] 任务书 §7.4 mixed/extra alias 强制反例未落地 — 测试面

§7.4 要求覆盖「额外/mixed alias」。实现面 `_verify_receipts` 对单 receipt 的全部 inputs/outputs 要求统一 `expected_alias`（acceptance=`G8`，其余=`PROJECT`），且 root map 由 `_artifact_roots_for_receipt_stage` 只返回单键——静态可读为应 fail-closed。但 exact6 测试仅有：

- `test_acceptance_project_alias_is_rejected`
- `test_non_acceptance_g8_alias_is_rejected`

**无**同一 receipt 内 PROJECT+G8 混用，也无向 root map 注入额外 alias 的定向断言。对照本项目 R2A/R2S 初验先例，强制反例清单缺项构成证据 FAIL。

### [P1] 任务书 §7.2 readiness fold 所有权错配 / 缺一 fold 强制反例未落地 — 测试面

`_validate_gate_execution("readiness")` 以 `len(refs)==2` 且 `{ref.fold}=={execution.fold}` 闭合双折单所有权，静态应拒绝：仅一折、两 ref 同标 `fold_001`、或折集合含未知 fold。交付 C2 / 新增测只钉 key 碰撞与 shared path；**无** fold 错配或缺折定向测。§7.2 明文要求该项。

### [P2] `test_readiness_shared_path_bytes_across_folds_fails` 未锁定 path/bytes 单射机制 — 测试面

fixture 在共享文件上 `publish_stage_receipt(..., scope_key=readiness:shared-publish)`，两 fold ref 却声称不同 `readiness:{fold}`。失败路径落在 `_verify_receipts` 的 scope_key 漂移（`SUCCESSOR_TERMINAL_INVALID`），**到不了** `_unique_refs` 的同 path/同 bytes 拒绝。交付将其表述为 path/bytes 复制反例，证据偏弱；同 bytes、不同 path、且各文件 scope_key 与 ref 一致的 readiness 字节别名仍未钉死。

### 无 P0；实现主路径未见可演示的生产逻辑回退

aggregate/physical 分离、旧 scope helper 删除、G8 权威解析、按 stage 唯一 root map、terminal 双绑定在源码上可读且与已落地反例大体一致。本轮 FAIL 主因是 **§7 强制测试证据未闭合**，不是已证伪的生产回退。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1 — acceptance receipt 同单内 mixed PROJECT+G8 alias（实现者未覆盖）

**最小静态复现（未执行）：**

1. 构造合法两折 request，canonical G8=`controlled=project_stage_root`。
2. 发布 `stage="acceptance"` receipt：`inputs` 含 `root_alias="PROJECT"` digest，`outputs` 含 `root_alias="G8"` digest（路径均落在 controlled 下）。
3. Gate ref 的 `scope_key`/path/sha 与该 receipt 一致，且 `identity=compute_successor_gate_identity(...)`。
4. 走 `_verify_receipts` / `run_two_fold_successor` 至 acceptance 复验。

**合同预期：** fail-closed（`SUCCESSOR_TERMINAL_INVALID`）；不得因「存在 G8」而放过 PROJECT 半边。

**现状：** 源码 `any(digest.root_alias != expected_alias)` 应拒绝；**无测试锁定**。

**通过条件：** 新增定向测断言 mixed alias 稳定失败；可选再测 root map 被注入第二 alias 键时仍不得用于验真。

### 反例 R2 — readiness 双 ref 同标一折 / 或缺一折（实现者未覆盖）

**最小静态复现（未执行）：**

1. **错配：** 两份 `readiness-evidence` ref，`scope_key` 互异且 hex64，但 `fold` 均为 `fold_001`（或一为 `fold_001`、一为不在 executions 中的 `fold_003`）。
2. **缺折：** 仅 1 份 readiness ref（另一折缺失）。
3. 调用 `_validate_gate_execution("readiness", ...)`。

**合同预期：** `SUCCESSOR_GATE_FAILED`；双折严格单所有权不得被「两份不同 key」掩盖。

**现状：** 源码 fold 集合 / `len==2` 检查应拒绝；**无对应单测/集成测**。

**通过条件：** unit 至少各一条错配与缺折；失败码稳定为 `SUCCESSOR_GATE_FAILED`。

### 反例 R3 — readiness 同字节异路径别名且 ref↔receipt scope 自洽（实现者未覆盖）

**最小静态复现（未执行）：**

1. 为 `fold_001`/`fold_002` 各发布独立 receipt 文件，`scope_key` 分别为不同 readiness_key，**文件 bytes 完全相同**（同 sha256），path 不同。
2. refs 与各自 receipt 的 stage/scope/scope_key/path/sha 一致；fold 集合正确。
3. 跑至 terminal `_unique_refs` / `_validate_global_receipt_ownership`。

**合同预期：** 因同 bytes 跨 node 别名 fail-closed（`SUCCESSOR_TERMINAL_INVALID`），不得发布 terminal。

**现状：** 现有 shared-path 测因 scope 漂移提前失败，**未**覆盖本自洽字节别名；`_unique_refs` 机制本身仍在。

**通过条件：** 新增 integration/unit 钉死 readiness 跨 fold 同 sha 拒绝，且不得依赖 scope_key 漂移。

## 4. 失败项（现象—根因—规则—最小复现—通过条件）

### F1 — §7.4 mixed/extra alias 证据缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | exact6 测试无 mixed/extra alias 定向断言 |
| 根因 | 实现者只覆盖单侧整单错 alias |
| 规则 | 任务书 §7.4；独立初验须追加未用对抗例 |
| 最小复现 | 反例 R1 |
| 新增测试 | acceptance（及必要时非 acceptance）mixed alias；禁止额外 root map 键 |
| 通过条件 | 稳定 fail-closed；交付可逐条映射 §7.4 |

### F2 — §7.2 readiness fold 所有权错配/缺折证据缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | 无 fold 错配或缺一 fold 定向测 |
| 根因 | 反例集只覆盖 key 碰撞与（弱）shared path |
| 规则 | 任务书 §7.2 readiness 双 fold 单所有权 |
| 最小复现 | 反例 R2 |
| 新增测试 | 同标一折 / 未知折 / 缺折 |
| 通过条件 | `_validate_gate_execution` 稳定 `SUCCESSOR_GATE_FAILED` |

### F3 — readiness path/bytes 单射测试证据偏弱（P2）

| 字段 | 内容 |
| --- | --- |
| 现象 | shared-path 测实际打在 scope 漂移上 |
| 根因 | 共享文件只含一个 published scope_key |
| 规则 | 任务书 §6 `_unique_refs`；§7.2 path/bytes 复制 |
| 最小复现 | 反例 R3 |
| 新增测试 | 同 sha 异 path 且 ref 自洽 |
| 通过条件 | 失败归因于 bytes/path 单射，而非 scope 漂移 |

## 5. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| 真实 Qlib / network / actual worker / new root / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做**（仅写本报告） |

## 6. 总判

**REVIEW_FAIL**

生产侧 physical/aggregate 分离、旧 `compute_successor_gate_scope_key` 删除、canonical G8、按 stage 唯一 root map、以及 terminal 同时绑定 aggregate identity 与 physical refs，静态阅读与已有测大体贴合合同。但任务书 §7 **强制**的 mixed/extra alias 与 readiness fold 所有权错配/缺折反例未落地，且 readiness path/bytes 复制测未钉死 `_unique_refs` 单射。须在 exact6 测试白名单内最小补测（实现若已正确则无需改生产代码），再由全新独立初验复验；**不可**据此申请 Windows 验证或解冻 R2W。

---

## 7. STATIC_REWORK1 复验（原独立 reviewer）

日期：2026-08-26<br>
身份：与首轮同一独立初验角色（未参与实现/返工）<br>
依据：任务书 §9、交付 STATIC_REWORK1、exact6 diff<br>
唯一写入：本报告追加；production / tests / 任务书 / 交付只读<br>
STATIC_ONLY：未运行 Python / pytest / Ruff / mypy / cold / network / worker / Qlib / stage / commit

### 7.1 Production 未漂移

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 交付声称本轮未改 production | **成立** | delivery §3/§4 |
| working-tree blob vs 首轮交付 tip | **一致** | `git hash-object successor_runtime.py` = `2f925820096a2f7199b95b08931fccc405989c8d` ≡ 首轮 diff `index …2f92582` |
| 关键验闭包未改写 | **成立** | `_verify_receipts` 仍统一 `expected_alias`；`_validate_gate_execution` readiness 仍 `len==2`+fold 集合；`_unique_refs` / ownership 仍 bytes 单射 |

### 7.2 F1–F3 闭包映射

| 项 | 结论 | 证据 |
| --- | --- | --- |
| F1 mixed alias | **闭合** | unit `test_verify_receipts_rejects_acceptance_mixed_project_g8_alias`（inputs=PROJECT、outputs=G8，ref 自洽→`SUCCESSOR_TERMINAL_INVALID`）；integration `test_acceptance_mixed_project_g8_alias_is_rejected`（`force_acceptance_mixed_alias`）；`test_artifact_roots_for_receipt_stage_are_exclusive` 锁 `keys==["G8"]`/`["PROJECT"]`（无公共 extra-map 注入口，符合 §9「若可表达则补」） |
| F2 fold 所有权 | **闭合** | `test_validate_gate_rejects_readiness_both_refs_same_fold`（互异 key 同标 fold_001）；`…_unknown_fold`（fold_003）；`…_missing_fold`（仅 1 份）；均 `SUCCESSOR_GATE_FAILED`，不依赖 key 碰撞 |
| F3 bytes 单射 | **闭合** | 移除弱 `duplicate_readiness_path`；`test_unique_refs_rejects_readiness_same_bytes_different_paths` + `test_global_ownership_rejects_readiness_same_bytes_different_paths` 钉 `_unique_refs`/ownership；交付如实说明互异 key 的自洽 receipt 不可能等 SHA，测锁实际 terminal 节点 |

### 7.3 复验总判

**REVIEW_PASS**

首轮 F1–F3 测试证据缺口已按 §9 在 exact6 测试面闭合；production 字节相对首轮交付未漂移。本结论**仅**静态初验通过，**不**表示 Windows 验证、R2W 解冻或 M3 Gate 完成；可另申请 Windows 工程验证资源。

---

## 8. STATIC_REWORK2 复验（原独立 reviewer）

日期：2026-08-26<br>
身份：与首轮同一独立初验角色（未参与实现/返工）<br>
依据：任务书 §10、交付 §7、VALIDATION1 evidence、exact6 当前工作区<br>
唯一写入：本报告追加；production / tests / 任务书 / 交付只读<br>
STATIC_ONLY：未运行 Python / pytest / Ruff / mypy / cold / network / worker / Qlib / stage / commit

### 8.1 VALIDATION1 证据核对

| 项 | 结论 | 证据 |
| --- | --- | --- |
| evidence root | **可读** | worktree `artifacts/agent_runs/m3-r2i-validation1-20260826T105333347Z`（与交付引用同名） |
| identity | **PASS** | `01-identity.exit.txt=0`；stdout `IDENTITY_PASS` |
| unit | **1 failed / 29 passed** | `02-unit.stdout.log`；`02-unit.exit.txt=1` |
| 唯一失败点 | **第二次 mkdir** | 栈：`second_path.parent.mkdir(parents=True)` → `FileExistsError` / WinError 183；**未**进入 `_validate_global_receipt_ownership` |
| 后续阶段 | **UNRUN** | `stage-summary.log`：`STOP=STAGE_FAILED:02-unit`；无 Ruff/mypy/cold/scope/integration |

### 8.2 本轮变更范围与语义冻结

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 仅共享父目录 mkdir 收敛 | **成立** | 当前 `test_global_ownership_…` 仅 `first_path.parent.mkdir(parents=True)`；无第二次 `mkdir` |
| ownership 对抗语义不变 | **成立** | 仍两不同 path（fold_001/002.json）、相同 `payload`/`shared_sha`、不同 fold/key；仍断言 `_validate_global_receipt_ownership` → `SUCCESSOR_TERMINAL_INVALID` |
| production 未改 | **成立** | `git hash-object successor_runtime.py` = `2f925820096a2f7199b95b08931fccc405989c8d`（与 §7.1 一致） |
| integration 未改 | **成立** | `git hash-object tests/integration/…` = `f7edf9273d0296b132954575353efdcee8dc72d1`（与 REWORK1 后一致） |
| 交付 §7 记录 | **成立** | 现象—根因—规则—最小复现—修正—通过条件齐；引用 VALIDATION1 root；声明未重跑 Python |

### 8.3 复验总判

**REVIEW_PASS**

§10 授权的 fixture mkdir 最小修正已落地，且未削弱 F3 ownership 对抗语义；production/integration 冻结成立。本结论**不等于**整包验证通过，也**不得**把 VALIDATION1 的 29 绿冒充通过；可另申请新的完整验证。

---

## 9. EVIDENCE_REVIEW（VALIDATION1/2 + scope-close）

日期：2026-08-26<br>
身份：原独立初验角色（EVIDENCE_REVIEW_ONLY；未参与实现/验证执行）<br>
依据：AGENTS.md、任务书 §11、交付 §8、三份 evidence root<br>
唯一写入：本报告追加；production / tests / 任务书 / 交付只读<br>
零 Python / pytest / Ruff / mypy / cold / stage / commit

### 9.1 组合轮次（禁止洗成单轮全绿）

| 轮次 | root | 独立复核 |
| --- | --- | --- |
| VALIDATION1 | `…/m3-r2i-validation1-20260826T105333347Z` | **历史 STOP 保留**：identity PASS；unit `1 failed, 29 passed`（二次 mkdir）；integration/Ruff/mypy/cold/scope UNRUN；`STOP=STAGE_FAILED:02-unit` |
| VALIDATION2 | `…/m3-r2i-validation2-20260826T110402344Z` | **product 绿 + 同轮 scope STOP**：见 §9.2 |
| scope-close | `…/m3-r2i-validation2-scope-close-20260826T111225888Z` | **独立无 Python PASS**：见 §9.3 |

不得把上述三轮合并表述为「单次 runner 全绿」。

### 9.2 VALIDATION2 product / SHA / scope STOP

| 阶段 | exit | 结果 | stdout SHA-256（复核≡交付/任务书） |
| --- | --- | --- | --- |
| identity | 0 | `IDENTITY_PASS` | （未在交付表列；日志可读） |
| unit | 0 | **30 passed** | `2dc90a1cfec229d3ca15bdeea243ef755f053ed260f5f1af0baf133c91d48bd2` |
| integration | 0 | **25 passed** | `bfefd10ad1f7f178543d7c6837f86069b74d49d6b2e6c31209b60dbc66340e22` |
| Ruff | 0 | `All checks passed!` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | 0 | `Success: no issues found in 1 source file` | `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` |
| cold | 0 | `COLD_IMPORT_PASS` | `c1a6694e0f5d2fe587ae68c0c187026cd54e534db00fb4217a256e7342e7a4c2` |
| scope | 1 | **STOP** `CACHE_RESIDUE:.mypy_cache` | stderr 逐字命中；`stage-summary`：`STOP=CACHE_RESIDUE:.mypy_cache`；BASETEMP_CLEANUP=PASS |

### 9.3 独立 scope-close

| 项 | 复核 |
| --- | --- |
| `SCOPE_CLOSE=PASS` | 成立（stdout + summary） |
| ACTUAL_COUNT=6 / CACHED_COUNT=0 | 成立；六路径=exact6（prod+两测+task+delivery+review） |
| DIFF_CHECK=PASS | 成立 |
| CACHE_RESIDUE=0 / PROCESS_RESIDUE=0 | 成立 |
| scope SHA | `095e8db4ecb5a4afd563dc74332556988499c5aac2e68c9a93810e612497d256` ≡ |
| summary SHA | `bc09f1322eea35c4b68dbc7d44d04400802c92ac19bc7b3e79a37609a085224d` ≡ |

### 9.4 当前工作区边界（只读抽查）

| 项 | 结论 |
| --- | --- |
| HEAD == exact base | `eca54af513078ca6d000feb544329cba69797948` |
| actual dirty ⊆ exact6 | 3×`M` prod/tests + 3×`??` task/delivery/review |
| cached | 0 |
| `git diff --check` | PASS |
| `.mypy_cache` 等工作区残留 | 未见（scope-close 后清理成立） |
| production blob 冻结 | `2f925820096a2f7199b95b08931fccc405989c8d`（相对首轮实现未再漂移） |

### 9.5 未验证 / 未关闭边界（强制）

R2W、R2B、actual worker、真实 Qlib、network、new root、retained、M3 Gate：**未**验证、**未**关闭。本包终态上限仅 `R2I_WINDOWS_ENGINEERING_VALIDATED`（组合证据）。

### 9.6 证据总判

**EVIDENCE_REVIEW_PASS**

VALIDATION2 unit30 / integration25 / Ruff / mypy / cold 绿与 SHA 一致；同轮 scope 因 `.mypy_cache` STOP 后经授权清理；独立无 Python scope-close PASS；actual exact6 / cached0 / diff / residue 与任务书§11、交付§8 陈述一致。历史 VALIDATION1 STOP **未洗白**。
