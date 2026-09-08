# M3-G8F-R2W Rebuilt Package-Owned Successor Downstream Wiring 独立初验报告

日期：2026-08-26<br>
身份：未参与本包实现的全新独立静态初验 Agent（STATIC_ONLY）<br>
task id：`M3-G8F-R2W-REBUILT-PACKAGE-OWNED-SUCCESSOR-DOWNSTREAM-WIRING`<br>
exact base / HEAD：`1d9b4e09c91293de18fea5cf0aa563b782379d37`（一致）<br>
branch：`codex/m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`<br>
唯一写入：本报告<br>
结论：**EVIDENCE_REVIEW_PASS**（§18；§17 F12_PASS / §16 F11_PASS / §15 F10_PASS / §14–§8 与首轮 FAIL 原文保留）<br>
终态上限声明：可支持 `R2W_WINDOWS_ENGINEERING_VALIDATED` 组合口径；**不**关闭 actual worker / 真实 Qlib / new root / retained / acceptance / M3 Gate。本轮验证命令均为 **UNRUN**（见 §18）。

## 0. 审查边界

- 已完整阅读：根 `AGENTS.md`、任务书、交付报告、exact12 内 production（`successor_runtime.py` / `successor_upstream_stage.py` / `successor_downstream_stage.py`）与对应 unit/integration 测试。
- production / tests / 任务书 / 交付：**只读**；未改实现、未改测试、未改任务书、未改交付。
- **STATIC_ONLY**：未运行 Python / pytest / Ruff / mypy / cold / 真实 Qlib / network / actual worker / new root / retained / stage / commit。
- dirty（只读观察）：exact12 内 `M`/`??`（含本报告写入前的 task/delivery/实现/tests）；未见白名单外生产路径；`git diff --check` PASS；cached=0。

## 1. 合同逐项静态核对

| # | 合同点 | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | 十 callable 仅组合既有 public API | **部分通过 / summary verify 失败** | `successor_downstream_stage.py` 拥有 formal/fold/summary-verify/repro/readiness/acceptance/terminal；run 路径调用 formal/repro/readiness/quality/acceptance public API；**`verify_successor_summary_gate` 未调用 `apis.summary_verifier`**（见 F1） |
| 2 | formal `prior_refs` fresh typed rehydrate；tracking 对应同 fold/horizon backtest | **实现面通过 / 强制反例不全** | Protocol 含 `prior_refs`；adapter 传 stable-sorted refs；`rehydrate_successor_formal_{backtest,tracking}_inputs` 从显式 path 验真；tracking 经 `_one_fold_horizon_ref(..., stage="backtest")` 绑定；exact12 **无**缺 backtest / 跨 horizon 定向测（见 F2） |
| 3 | 零参 `make_canonical` + 全槽位 `is` identity | **通过（实现面+测）** | `make_canonical_successor_production_dependencies()` 零参；adapter 对十下游 + upstream/summary 做 `is`；unit/integration 覆盖 lambda/partial/wrapper/impostor |
| 4 | readiness exact **1** 全局物理 ref；aggregate Gate identity 仍两折 | **通过（实现面+测）** | `_validate_gate_execution("readiness")`：`len==1`、`fold/horizon is None`、`stage=readiness-evidence`；`run_successor_readiness_gate` 发单 ref；`identity=compute_successor_gate_identity(...)` 仍吃两折；0/2/fold/horizon 测存在 |
| 5 | R2I `comparison_key` / `acceptance_key` / G8 / path-SHA-semantic 未回退 | **通过（实现面+测）** | repro 绑 `comparison_key`；acceptance 允 physical≠identity；G8 仅 acceptance；`_unique_refs` 仍拒 path/bytes/semantic-owner 别名；未见 `compute_successor_gate_scope_key` 回归 |
| 6 | cache / tamper / scan / placeholder / caller injection fail-closed | **部分通过** | adapter 拒 wrapper/injection；tracking client 仅 `create_mlflow_tracking_client(canonical_uri)`；无 glob/latest 接线；**summary fresh verifier 被跳过**，与「禁止跳过 verifier」冲突（F1）；integration 用 monkeypatch 替换真实 `verify_successor_summary_gate`，掩盖该洞 |

## 2. 发现分级

### [P1] summary Gate fresh verifier 跳过 public R2S `summary_verifier` — `successor_downstream_stage.py:264-326`

`verify_successor_summary_gate` 仅：形状检查 + `verify_stage_receipt_with_bytes` + 断言 `apis.summary_verifier is not None`，**从未调用** `apis.summary_verifier`（即 `verify_research_summary_artifact`），也未从 fold receipts 重建 typed evaluation/experiment 闭包。源码注释写明 “Public summary verifier requires typed upstream; reconstruct via R2S path”，但实现停在 receipt bytes。

后果：adapter `_run_gate` 与 `verify_successor_terminal_gate` 分发均可在未跑 R2S 科学 fresh verifier 的情况下返回 `GateVerification(status="PASS")`，直接违反任务书 §6「PASS 只能来自真实 public stage + 专属 fresh verifier；禁止跳过 verifier」。integration 边界 stub 用 monkeypatch 换成会调用 `summary_verifier` 的假实现，**生产实现路径未被这些测试钉死**。

### [P1] 任务书 §7.2 tracking↔backtest 强制反例未落地 — 测试面

§7 要求覆盖：formal prior 缺/多/重/乱序、跨 fold/horizon/request；**tracking 缺对应 backtest 或引用另一 horizon**。交付 F3 称「integration stub assert；rehydrate 单射」，但 exact12 内仅有：

- `prior_refs` Protocol / unsorted 拒绝（formal run）
- rehydrate API **callable / 源码字符串**存在性检查

**无**对 `rehydrate_successor_formal_tracking_inputs` 的缺 backtest、跨 horizon、跨 fold/request 行为断言。实现面 `_one_fold_horizon_ref` 可读为应 fail-closed，但强制反例证据未闭合。

### 无 P0；其余主路径未见可演示的 R2I 回退

零参 factory、`is` 绑定、readiness 单全局物理 receipt vs 两折 aggregate identity、repro/acceptance physical key、G8 root map、`_unique_refs` 单射在源码与已有测上可读一致。本轮 FAIL 主因是 **summary verifier 跳过（实现缺陷）** 与 **§7.2 强制测试证据缺失**。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1 — readiness 物理 `scope_key` 伪装成 aggregate `gate.identity`（physical-vs-aggregate）

实现者已覆盖：acceptance physical≠identity 正例、acceptance identity masquerade 负例、readiness 0/2/fold-bound/same-bytes-异 path。**未**覆盖「readiness 物理槽位写入 aggregate identity」。

**最小静态复现（未执行）：**

1. 合法两折 folds + prior summary/repro，计算 `identity = compute_successor_gate_identity(gate="readiness", ...)`。
2. 发布真实 readiness-evidence receipt，其 `readiness_key = K`，且 `K != identity`。
3. 构造 `GateExecution(gate="readiness", identity=identity, receipt_refs=(ref,))`，其中 `ref.scope_key = identity`（把 aggregate 写入物理槽），path/sha 可与磁盘 receipt 一致或故意漂移。
4. 调用 `_validate_gate_execution("readiness", ...)` → 预期仍可能因 hex64/形状而**放行**（合同允许 physical≠identity，但不把 aggregate 当作合法 readiness_key）。
5. 再调用真实 `verify_successor_readiness_gate`（经 public `readiness_verifier`）→ 必须因 `verified.report.readiness_key != ref.scope_key` **fail-closed**（`SUCCESSOR_GATE_FAILED`）。

**合同预期：** 物理 receipt 只认 public `readiness_key`；aggregate 只留在 `GateExecution.identity`。旧 R2W「aggregate 当 physical scope」不得借单槽位复活。

**通过条件：** 新增定向测：`_validate` 不把 `scope_key==identity` 当作 readiness 语义通过；fresh verify 稳定拒绝；可选再钉「改 fold_002 work_key → identity 变、物理 readiness_key 不变」的分离性质。

### 反例 R2 — 同 bytes、异 semantic-owner 的跨 stage 别名（same-bytes-different-owner）

实现者 readiness same-bytes 测落在同 stage 双 path。补充：两 ref **同 sha256**、不同 `stage`（例如 `readiness-evidence` vs `acceptance`）与不同 `scope_key`，经 `_unique_refs` / terminal ownership。

**合同预期：** `SUCCESSOR_TERMINAL_INVALID`（bytes 单射），不得因 semantic-owner 不同而放行。

**现状：** `_unique_refs` 的 `by_bytes` 应拒绝；exact12 **无**跨 stage same-bytes owner 测。

## 4. 失败项（现象—根因—规则—最小复现—新增测试—通过条件）

### F1 — summary fresh verifier 跳过 public API

| 字段 | 内容 |
| --- | --- |
| 现象 | `verify_successor_summary_gate` 返回 PASS 却从不调用 `apis.summary_verifier` |
| 根因 | 仅做 receipt bytes/形状检查；typed upstream 重建未接线 |
| 规则 | 任务书 §4（组合 R2S summary API）、§6（禁止跳过专属 fresh verifier） |
| 最小复现 | 静态阅读 `successor_downstream_stage.py` 264–326；对照 `evaluate.verify_research_summary_artifact` 签名 |
| 新增测试 | 源码/行为钉：summary verify **必须**调用 `summary_verifier`；monkeypatch 探测调用次数；缺 typed upstream / 输出漂移 fail-closed；integration **不得**长期用假 verify 掩盖生产路径 |
| 通过条件 | 每 horizon 一次 public summary fresh verify；cache hit 仍重建 evaluation/experiment 闭包并重验；跳过 verifier 的实现不得再返回 PASS |

### F2 — §7.2 tracking↔backtest 强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | exact12 无 tracking 缺 backtest / 错 horizon 的行为测；交付 F3 证据偏虚 |
| 根因 | 只钉 API 存在与 formal unsorted prior_refs |
| 规则 | 任务书 §4、§7.2 |
| 最小复现 | 构造 prior_refs 无同 fold/horizon `stage="backtest"`，或 backtest horizon=5 而 tracking 请求 10，调用 `rehydrate_successor_formal_tracking_inputs` |
| 新增测试 | 缺 backtest、跨 horizon、跨 fold/request、重复 backtest 各至少一条 |
| 通过条件 | 稳定 `SUCCESSOR_STAGE_INVALID`（或合同规定码）；交付可逐条映射 §7.2 |

## 5. 已通过项（压缩）

- 零参 `make_canonical_successor_production_dependencies` + adapter 全槽位 `is`（含 wrapper/lambda/partial）。
- readiness 物理卡度=1、`fold/horizon=None`；aggregate identity 仍 `compute_successor_gate_identity` 两折闭包。
- R2I：repro `comparison_key`、acceptance `acceptance_key`≠identity 允许、G8 仅 acceptance、`_unique_refs` path/bytes/semantic-owner、旧 scope helper 未回归。
- tracking client 无 caller 注入参数；formal 走 package-owned rehydrate。
- dirty 限于 exact12；STATIC_ONLY 边界与交付声明一致。

## 6. 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| new root / retained / stage / commit | **未执行** |
| R2B / CLI / M3 Gate / acceptance Gate 关闭 | **未关闭** |
| Windows 定向验证申请 | **阻断**（需先返工至 REVIEW_PASS） |

## 7. 结论（首轮）

**REVIEW_FAIL**（存在 P1：F1 实现缺陷 + F2 强制反例证据缺口）。返工后须由**同一** reviewer 按 taskbook §10 做 STATIC_REWORK1 复验；复验通过前不得申请 Windows 定向验证，更不得宣称 R2W / M3 Gate 完成。

---

## 8. STATIC_REWORK1 复验（对照 taskbook §10）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读更新后的 exact12 实现/tests/delivery + 任务书 §10；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / new root / retained / network / stage / commit

### 8.1 F1 — Summary 每 horizon fresh rehydrate + exact public stage verifier

| 检查 | 静态结论 | 证据 |
| --- | --- | --- |
| 每 horizon 调用 `rehydrate_successor_summary_horizon_verify_inputs` | **通过** | `verify_successor_summary_gate` 对每个 `gate.receipt_refs` 先 rehydrate，再建 `FormalSummaryStagePublicationIdentity` 与 evaluations 闭包（upstream 3436–3614） |
| exact 调用 `apis.summary_verifier` | **通过** | `apis.summary_verifier(identity=..., root=..., receipt_path=..., evaluations=..., ...)`；校验 `VerifiedResearchSummaryArtifact` 的 sha/experiment/horizon/root |
| bundle `is` 绑 `verify_research_summary_stage_artifact` | **通过** | `make_public_successor_api_bundle`：`summary_verifier=verify_research_summary_stage_artifact`；unit `test_bundle_binds_stage_summary_verifier_not_legacy_horizon_leaf`；**非** legacy `verify_research_summary_artifact` |
| 未复制 R2S verifier / 未改 evaluate 科学体 | **通过** | exact12 未改 `evaluate.py`/`summary_stage.py`；downstream 只组合 public API；delivery 签名闭合说明与 stage leaf 路径一致 |
| exact1 / wrapper / wrong identity / one-horizon tamper | **通过** | `test_verify_summary_calls_summary_verifier_exact_once_per_horizon`（calls==[5,10]）；wrapper→`SUCCESSOR_INPUT_INVALID`；wrong artifact→`SUCCESSOR_GATE_FAILED`；h10 rehydrate tamper→fail 且 seen≤1 |
| 无 fallback / 无仅 JSON 冒充 PASS | **通过** | 异常路径统一 `SUCCESSOR_GATE_FAILED`；无 `summary_verifier is None` 旁路 |

### 8.2 F2 — Tracking prior closure 行为拒绝（public tracking/client 前）

| 反例 | 静态结论 | 证据 |
| --- | --- | --- |
| 缺同 fold/horizon backtest | **通过** | `test_tracking_rehydrate_rejects_missing_backtest_prior` → `SUCCESSOR_STAGE_INVALID`（`_one_fold_horizon_ref`） |
| 跨 horizon | **通过** | `test_tracking_rehydrate_rejects_cross_horizon_backtest_prior` |
| 跨 fold | **通过** | `test_tracking_rehydrate_rejects_cross_fold_backtest_prior` |
| 跨 request fold | **通过** | `test_tracking_rehydrate_rejects_cross_request_fold` |
| 重复 + 乱序 prior | **通过** | `test_tracking_rehydrate_rejects_duplicate_and_unsorted_backtest_priors` |
| 伪 `latest/...` 无显式 ref 仍拒，且 public tracking/client 零调用 | **通过** | `test_tracking_formal_stage_rejects_before_public_tracking_apis`：磁盘 `latest/backtest/...` 存在；`formal_tracking_stage` / `make_formal_tracking_run_plan` / `create_mlflow_tracking_client` spies 为空 |

实现面：`rehydrate_successor_formal_tracking_inputs` 在 `verify_backtest_artifact` / tracking client 构造前完成 prior 单射检查；`run_successor_formal_stage(tracking)` 先 rehydrate 再 `create_mlflow_tracking_client`。

### 8.3 F3 — Readiness physical-vs-aggregate；R2I 未回退

| 检查 | 静态结论 | 证据 |
| --- | --- | --- |
| `_validate` 可放行 `scope_key==identity`（hex/形状） | **通过** | `test_readiness_verify_rejects_aggregate_identity_as_physical_scope_key` 先调用 `_validate_gate_execution` 无异常 |
| 专属 fresh `verify_successor_readiness_gate` 拒绝 | **通过** | 同测：`readiness_verifier` 回报真实 `readiness_key=K≠identity` → `SUCCESSOR_GATE_FAILED` |
| exact1 global physical + 两折 aggregate 分域 | **通过** | readiness `len(refs)==1`、`fold/horizon is None` 仍在；`compute_successor_gate_identity` 仍吃两折 |
| R2I 未回退 | **通过** | 未见 `compute_successor_gate_scope_key`；repro/acceptance physical key、G8 仅 acceptance、`_unique_refs` path/bytes/semantic-owner 合同保留；未改 R2I 模块 |

### 8.4 发现分级（REWORK1）

**无新 P0/P1。**

残留（不阻断本复验）：integration 边界仍可 monkeypatch 十下游做编排测——属既有 fixture 模式；F1 行为测对 rehydrate 使用 spy stub，fresh 重建正确性主要靠 production 源码静态阅读 + verifier exact1 锁定。跨 stage same-bytes-different-owner（首轮 R2）仍可选补强，非 §10 强制项。

### 8.5 未运行与 Gate 边界（强制保留）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| new root / retained / stage / commit | **未执行** |
| R2B / CLI / M3 Gate / acceptance | **未关闭** |

### 8.6 REWORK1 结论

**STATIC_REWORK1_REVIEW_PASS**（taskbook §10 F1–F3 静态闭合）。可申请 Windows 定向验证（identity → exact unit/integration → Ruff → mypy production → cold → exact12 scope）。Windows 绿**不**替代 actual worker / Qlib / new root / retained / M3 Gate。

---

## 9. VALIDATION1_F4_REVIEW（对照 taskbook §11）

日期：2026-08-26<br>
身份：与首轮/REWORK1 同一独立初验者；未参与实现<br>
范围：只读 taskbook §11、delivery §9、**test-only** diff（`tests/unit/test_m3_successor_upstream_stage.py` F4 段）；production / 其他 tests / task / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit

### 9.1 VALIDATION1 证据复述（未重跑，与 delivery 一致）

| 项 | 状态 |
| --- | --- |
| identity | **PASS**（VALIDATION1 陈述） |
| exact unit | **`74 passed / 1 failed`**（失败=测试面全文件子串误伤；**非** production 红） |
| integration / Ruff / mypy / cold / exact12 scope | **UNRUN** |
| 资源 / 临时目录 / 0xF00 | 已释放（VALIDATION1 陈述） |
| 本轮 F4 复验命令 | **全部 UNRUN** |

### 9.2 F4 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 全文件 `-> _SharedUpstream` 禁止改为三 public rehydrate 的 AST/signature 边界 | **通过** | `test_public_rehydrate_defs_ast_return_annotations_are_strong_public_types`：`ast.parse` + 仅查 `_PUBLIC_REHYDRATE_RETURN_TYPES` 三 def；`test_public_rehydrate_signature_return_annotations_match_public_inputs` 用 `inspect.signature` |
| 2 | 三 public 返回强类型 annotation | **通过** | 分别为 `SuccessorFormalBacktestInputs` / `SuccessorFormalTrackingInputs` / `SuccessorSummaryHorizonVerifyInputs`；与 production def 行一致（upstream 3097 / 3348 / 3441） |
| 3 | private `_reconstruct_shared_upstream -> _SharedUpstream` 合法 | **通过** | `test_private_reconstruct_shared_upstream_may_return_shared_upstream` 断言 AST 返回 `_SharedUpstream`；production 819–828 保留该 annotation |
| 4 | exact 公开类型 + 字段不泄露 `_SharedUpstream` | **通过** | `test_public_rehydrate_return_types_exact_and_do_not_leak_shared_upstream`：三类 Inputs `fields` 的 type/name 均无 `_SharedUpstream` / `_shared*`；production dataclass 字段为公开契约类型 |
| 5 | caller 注入 `shared` / `_SharedUpstream` kwargs 拒绝 | **通过** | `test_caller_cannot_inject_shared_upstream_into_public_rehydrate_apis`：签名无此类参数；`fn(**{...})` → `TypeError` |
| 6 | 未改 production；无 Any / type:ignore 假绿 | **通过（声明+静态）** | §11 写白名单仅 upstream unit + task/delivery；F4 diff 为该 unit 文件追加 AST/signature 测；未见 production 为本轮 F4 修改；未见为过宽断言删除 private annotation 或放宽 public 返回类型 |
| 7 | delivery F4 现象—根因—规则—最小复现—修正测试—通过条件 | **通过** | delivery §9.2 齐全；74/1 与后续 UNRUN 如实 |

### 9.3 Production 字节冻结（F4 轮次）

只读指纹（本复验观察时点，**非** VALIDATION1 当时快照；用于证明审查未改 production）：

| 文件 | SHA256 |
| --- | --- |
| `successor_runtime.py` | `7071a904bf6ffb024962e62a5b377155327cc3cbff64935e87146622b21d2bc5` |
| `successor_upstream_stage.py` | `2adb24f040cf191ea7f28855b8d4b56e35350c69cd455f387aacc0f16be5a51c` |
| `successor_downstream_stage.py` | `e6476698e3a43a7439e6abb49db6ed7b561541c4c4ccc532fc33273fba3076c0` |

§11 / delivery 称 F4 **未**改 production；本审查亦未改。worktree 中 production 相对 exact base 的既有 dirty 属 R2W 实现轮次，**不**视为 F4 回写。

### 9.4 发现分级（F4）

**无 P0/P1。**

残留（不阻断 F4_PASS；须进 VALIDATION2 记账）：`tests/unit/test_m3_successor_downstream_stage.py` 仍含全文件 `assert "-> _SharedUpstream" not in public`（约 L148）。§11 明确冻结其他 tests，故本轮不得改该文件；delivery 已注明 sibling 过宽断言仍在、精确边界 SSOT 落在 upstream unit。申请 **完整 VALIDATION2** 时不得把本 F4_PASS 继承为整包绿；应预期 sibling 断言仍可能红，或另开允许改 sibling 的最小测试返工。

### 9.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION1 之 integration / Ruff / mypy / cold / scope | **仍为 UNRUN**（未重跑、未洗白） |
| VALIDATION2 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION2 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 9.6 F4 结论

**F4_REVIEW_PASS**（taskbook §11 test-only 边界闭合）。可申请**新的完整 VALIDATION2**；**不**继承本轮为整包 PASS。

---

## 10. VALIDATION2_F5_REVIEW（对照 taskbook §12）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4 同一独立初验者；未参与实现<br>
范围：只读 AGENTS.md、taskbook §12、delivery §10、exact F5 test-only diff（`tests/unit/test_m3_successor_downstream_stage.py`）；production / 其他 tests **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit

### 10.1 写范围核对

| 路径 | F5 轮次 | 结论 |
| --- | --- | --- |
| `tests/unit/test_m3_successor_downstream_stage.py` | 允许改动 | **命中**：删除全文件 `-> _SharedUpstream` 禁令；新增 AST/signature/exact-type/kwargs 测 |
| delivery / taskbook §12 | 允许 | **命中**（delivery §10 证据链） |
| production 三文件 | 冻结 | **通过**：SHA256 与 F4 复验指纹逐字节一致（runtime `7071a904…` / upstream `2adb24f0…` / downstream `e6476698…`） |
| 其他 tests（含 F4 upstream unit） | 冻结 | **通过**：upstream F4 AST 测仍在；未见为本轮改写 |

### 10.2 VALIDATION2 证据复述（未重跑；只读核对 stdout）

| 项 | 状态 |
| --- | --- |
| Parser / identity | **PASS**（delivery；证据根存在） |
| exact unit | **`79 passed / 1 failed`**（654.69s） |
| unit stdout SHA-256 | `c4c8b32a2643865f8e16b85cb9d11525ba15ad055d9c66f0728f5283aa6a43af`（只读哈希与 delivery 一致） |
| 失败点 | `test_upstream_exposes_formal_rehydrate_without_shared_upstream` 全文件禁止 `-> _SharedUpstream`，误命中 private `_reconstruct_shared_upstream`（stdout 可证） |
| integration / Ruff / mypy / cold / exact12 scope | **UNRUN** |
| 本轮 F5 复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation2-20260826T132000Z/`（worktree 内）。

### 10.3 F5 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 去掉全文件字符串禁令 | **通过** | 原 L148 `assert "-> _SharedUpstream" not in public` 已删除；`test_upstream_exposes_formal_rehydrate_without_shared_upstream` 仅保留 callable/class/`_SharedUpstream` 存在性钉 |
| 2 | AST/signature 只钉三个 public rehydrate | **通过** | `_PUBLIC_REHYDRATE_RETURN_TYPES` 三元组；`test_public_rehydrate_ast_return_annotations_are_strong_public_types`；`test_public_rehydrate_signature_return_annotations_match_public_inputs` |
| 3 | private helper 仍允许 `-> _SharedUpstream` | **通过** | 同 AST 测断言 `defs["_reconstruct_shared_upstream"].returns == "_SharedUpstream"`；production annotation 未删（指纹未变） |
| 4 | exact type / 字段不泄露 | **通过** | `test_public_rehydrate_return_types_exact_and_do_not_leak_shared_upstream` |
| 5 | kwargs 注入 `shared`/`_SharedUpstream` 拒绝 | **通过** | `test_caller_cannot_inject_shared_upstream_into_public_rehydrate_apis` → `TypeError` |
| 6 | 无 Any / type:ignore / 改 production 假绿 | **通过** | F5 文件未见新增 Any/type:ignore；production 指纹不变 |

### 10.4 发现分级（F5）

**无 P0/P1。**

### 10.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION2 之 integration / Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION3 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION3 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 10.6 F5 结论

**F5_REVIEW_PASS**（taskbook §12 test-only 边界闭合）。可申请**新的完整 VALIDATION3**；**不**继承 VALIDATION2 / 本轮为整包 PASS。

---

## 11. VALIDATION3_F6_REVIEW（对照 taskbook §13）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4/F5 同一独立初验者；未参与实现<br>
范围：只读 taskbook §13、delivery §11、exact F6 diff（`tests/integration/test_m3_successor_upstream_stage.py`）；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit

### 11.1 写范围核对

| 路径 | F6 轮次 | 结论 |
| --- | --- | --- |
| `tests/integration/test_m3_successor_upstream_stage.py` | 允许 | **命中**：`_assert_shared_subprocess_run` / `_restore_shared_subprocess_run` + `test_integration_real_api_positive_probe_and_project_roots` authority 缝 |
| delivery / taskbook §13 | 允许（实现侧已写） | **只读复验** delivery §11 证据链齐全 |
| production 三文件 | 冻结 | **通过**：SHA256 与 F4/F5 指纹一致 |
| 其他 tests | 冻结 | **通过**（本审查未改；F6 合同写集仅 integration upstream） |

### 11.2 VALIDATION3 证据复述（未重跑；只读核对日志）

| 项 | 状态 |
| --- | --- |
| Parser / identity | **PASS**（delivery；证据根存在） |
| exact unit | **`84 passed`**（`02-unit.stdout.log`） |
| exact integration | **`41 passed / 1 failed`**（710.56s；`03-integration.stdout.log`） |
| integration stdout SHA-256 | `19059559a9abcb7510dd67b5bf1aed41140bdde7d8b1b755aa870181e7843b73`（只读哈希与 delivery 一致） |
| 失败点 | `test_integration_real_api_positive_probe_and_project_roots` → `M3_FEATURE_ARTIFACT_INVALID`（Authority B fixture；**非**本包 production 目标路径） |
| Ruff / mypy / cold / exact12 scope | **UNRUN** |
| 本轮 F6 复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation3-20260826T140000Z/`。

### 11.3 F6 authority 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | Authority A 前捕获 exact `subprocess.run` | **通过** | `original_subprocess_run = subprocess.run` + `_assert_shared_subprocess_run(original)`（L733–735） |
| 2 | fake 仅在 A 内生效且三别名同对象 | **通过** | A 内 `subprocess.run is _PROVIDER._fake_dump` 且 `_assert_shared_subprocess_run(subprocess.run)`（stdlib/provider/provider_validation） |
| 3 | A 末 / A 退出后 exact restore + `is` | **通过** | `_restore_shared_subprocess_run(provider_mp, original)`；A 外泄漏则显式 `AssertionError`；再 `_assert_shared_subprocess_run(original)` |
| 4 | B `_context` 前无 dump-fake；恢复失败不进 feature wrapper | **通过** | bridge pin + plan 入口前 `_assert_shared_subprocess_run(original)` 且 `is not _fake_dump`；泄漏路径为 `AssertionError` 文案，不吞异常 |
| 5 | B 不用 A 的 provider-dump fake 顶替 feature worker | **通过** | B 仍 `plan_support._context` + 真实 `build_backtest_plan_artifact`；进入前断言非 dump fake |
| 6 | 不 import summary_stage private helper / 不复制业务 fixture | **通过** | 测试自有窄 helper；无 import summary_stage restore 私有符号 |
| 7 | 不为 F6 放宽而 patch production builder / 吞错 | **通过** | F6 未新增 builder stub；未 `except: pass`；错误以 AssertionError 暴露 |
| 8 | delivery F6 现象—根因—authority 规则—复现—修正—通过条件 | **通过** | delivery §11.2 |

### 11.4 发现分级（F6）

**无 P0/P1。**

残留（不阻断）：Authority B 仍保留既有 `plan_module.verify_target_artifact` 局部 stub 以隔离 PROJECT alias（注释明确不 stub builder）；非 F6 引入的 dump-fake 替代，且非本轮写范围外 production 改写。

### 11.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION3 之 Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION4 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION4 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 11.6 F6 结论

**F6_REVIEW_PASS**（taskbook §13 test-only authority 缝闭合）。可申请**新的完整 VALIDATION4**；**不**继承 VALIDATION3 / 本轮为整包 PASS。

---

## 12. VALIDATION4_F7_REVIEW（对照 taskbook §14）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F6 同一独立初验者；未参与实现<br>
范围：只读 taskbook §14、delivery §12、exact F7 diff（`tests/integration/test_m3_successor_upstream_stage.py`）；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit

### 12.1 写范围核对

| 路径 | F7 轮次 | 结论 |
| --- | --- | --- |
| `tests/integration/test_m3_successor_upstream_stage.py` | 允许 | **命中**：`_install_shared_subprocess_run`；B 段 feature worker ownership；移除 `verify_target_artifact` stub |
| delivery / taskbook §14 | 允许（实现侧已写） | **只读复验** delivery §12 |
| production 三文件 | 冻结 | **通过**：SHA256 与 F4–F6 指纹一致 |
| 其他 tests | 冻结 | **通过** |

### 12.2 VALIDATION4 证据复述（未重跑；只读核对日志）

| 项 | 状态 |
| --- | --- |
| exact unit | **`84 passed`**（`02-unit.stdout.log`） |
| exact integration | **`41 passed / 1 failed`**（`03-integration.stdout.log`；仍失败于同测 Authority B 路径） |
| Ruff / mypy / cold / exact12 scope | **UNRUN**（stage-summary 仅至 integration exit=1） |
| 本轮 F7 复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation4-20260826T152000Z/`。delivery 如实写 84 / 41p1f / 后续 UNRUN；未把 VALIDATION4 冒充整包 PASS。

### 12.3 F7 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | F6「A 退出后 original exact 恢复」保留 | **通过** | A 末 `_restore` + A 外泄漏 `AssertionError` + bridge pin（L802–819） |
| 2 | B 单独在 `_context` 前安装 exact `_fake_feature_worker` | **通过** | `plan_mp` 内 `_install_shared_subprocess_run(plan_mp, feature_fake)` 后才 `plan_support._context`（L832–840） |
| 3 | dump fake ≠ feature fake；feature ≠ original | **通过** | `assert dump_fake is not feature_fake`；`feature_fake is not original_subprocess_run` |
| 4 | B 前三别名 exact `is` feature fake | **通过** | `_assert_shared_subprocess_run(feature_fake)`（stdlib/provider/provider_validation） |
| 5 | `_context` 后立即恢复 original，再真实 `build_backtest_plan_artifact` | **通过** | `_restore` + 多处 `is original` / `is not feature_fake` 后才 builder（L841–862） |
| 6 | 禁止 patch production builder/verifier（含移除既有 `verify_target` stub） | **通过** | diff 删除 `plan_mp.setattr(...verify_target_artifact...)`；当前文件无 `verify_target` / `plan_module` setattr；builder 为真实 `build_backtest_plan_artifact` |
| 7 | feature/dump fake 不得留到 builder 之后 | **通过** | builder 后与 `plan_mp`/`bridge` 出口均 `_assert_shared_subprocess_run(original)` |

### 12.4 发现分级（F7）

**无 P0/P1。**

### 12.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION4 之 Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION5 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION5 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 12.6 F7 结论

**F7_REVIEW_PASS**（taskbook §14 Authority B feature-worker ownership 闭合）。可申请**新的完整 VALIDATION5**；**不**继承 VALIDATION4 / 本轮为整包 PASS。

---

## 13. VALIDATION8_F8_REVIEW（对照 taskbook §15）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F7 同一独立初验者；未参与实现<br>
范围：只读 taskbook §15、delivery §13、exact F8 diff（`tests/unit/test_m3_successor_upstream_stage.py`）；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 13.1 写范围与证据边界

| 项 | 结论 |
| --- | --- |
| 写集 | 仅 unit upstream 测试 + delivery/taskbook（审查只读）；production 三文件 SHA 与 F4–F7 指纹一致 |
| VALIDATION8 | Parser/argv/identity **PASS**；unit exact3 **`82 passed / 2 failed`**（stdout 钉两 builder 节点在 `_context`→feature 即 `M3_FEATURE_ARTIFACT_INVALID`，真实 builder **未进入**） |
| integration / Ruff / mypy / cold / scope | **UNRUN**（stage-summary：`STOP\|STAGE_FAILED:02-unit`） |
| 本轮复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation8-20260826T065401Z/`。

### 13.2 Feature-worker seam（两 unit 节点）— 实现面通过

`_plan_context_with_feature_worker_seam` 与两 builder 节点静态满足 §15 seam 合同：

| 检查 | 结论 |
| --- | --- |
| `_context` 前安装 exact `_fake_feature_worker` | **通过** |
| 非 provider dump fake；三 alias `is` | **通过**（`_assert_shared_subprocess_run`） |
| 正常/异常 `finally` 恢复 original | **通过** |
| 恢复后才真实 `build_backtest_plan_artifact` | **通过**（builder 前再断言非 feature/dump fake） |
| 未 stub production builder | **通过** |

### 13.3 发现分级

### [P1] 无 §15 依据移除 `verify_target_artifact` 窄 stub — 使 PROJECT-only 正测可预见撞上 legacy root-alias 漂移

**现象：** F8 在补 feature-worker seam 的同时，删除了正测原注释所载之窄 stub：

```text
# Isolate PROJECT alias binding: fixture receipts use "root"; production
# successor path is PROJECT-only. Stub only fresh target verify (not the builder).
monkeypatch.setattr(plan_module, "verify_target_artifact", lambda **_: target)
```

现 `test_build_backtest_plan_artifact_positive_project_only_roots` 在 seam 恢复后，以 `artifact_roots={"PROJECT": project_root}` 直调真实 builder，且**无**任何 `verify_target_artifact` 隔离。

**根因：** 实现者把 F7/§14「禁止 patch builder/**verifier**」与 delivery 表述过宽套用到 §15；§15 明文只禁 **stub production builder**，并要求真实 builder——**未**要求删除该窄 verifier stub，也未授权用「去 stub」替代 seam 修复。

**规则：**

1. taskbook §15：只禁止 stub builder / fake 泄漏 / 放宽 identity；合同目标是 unit 节点获得与 F7 同类的 feature-worker seam。
2. 既有 formal plan 夹具大量对 `verify_target_artifact` 使用 `lambda **_: target`，因 fixture receipt 使用 `alias="root"`，而本测刻意传 PROJECT-only roots——正是为隔离该已知 legacy root-alias 漂移，才能检验「PROJECT-only `artifact_roots`」这一测试目的。
3. `build_backtest_plan_artifact` 入口路径会调用真实 `verify_target_artifact(..., artifact_roots=...)`（`a_share_plan.py`）；去掉窄 stub 后，正测在达到「PROJECT-only roots 语义」前，可静态预见先撞 target 侧 root/PROJECT alias 不匹配，从而偏离本测目的（甚至在 seam 修好后仍可能下一失败）。

**最小复现（静态，未执行）：**

1. 经 `_plan_context_with_feature_worker_seam` 得到 `plan_kwargs` + `common`（fixture 侧 target/receipt 仍为 root alias 世界）。
2. 不安装 `verify_target_artifact` 窄 stub。
3. 调用 `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": project_root}, ...)`。
4. 预期：失败或漂移落在 target fresh-verify / receipt alias 闭合，而非稳定证明 PROJECT-only builder roots 合同。

**新增/恢复测试要求：**

- **恢复**正测上的窄 `verify_target_artifact` stub（保留「只 stub fresh target verify，不 stub builder」注释）。
- **保留** `_plan_context_with_feature_worker_seam` 全部断言（seam 进入、非 dump、三别名、finally 恢复、builder 前无 fake）。
- wrong-alias 负测：若同样依赖 fixture target 闭合，按同一窄 stub 规则处理；不得 stub `build_backtest_plan_artifact` 本身。

**通过条件：** §15 seam 绿路径可达真实 builder；PROJECT-only 正测目的不被 legacy root-alias 漂移淹没；delivery 不再把「移除 verify_target stub」写成 §15 通过条件。

### 无 P0；seam 主修复方向正确

### 13.4 失败项六段式（F8）

| 字段 | 内容 |
| --- | --- |
| 现象 | 正测删除 `verify_target_artifact` 窄 stub；delivery 将其列为 F8「修正」 |
| 根因 | 误用 §14 verifier 禁令 / 过度净化；§15 未要求删除该 stub |
| 规则 | §15 仅禁 stub **builder**；窄 verifier stub 用于隔离 fixture `root` vs PROJECT-only 测试目的 |
| 最小复现 | 见 §13.3 |
| 测试 | 恢复窄 stub + 保留 feature-worker seam helper |
| 通过条件 | 见 §13.3；再交同一 reviewer 只读复验后才可申请 VALIDATION9 |

### 13.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION8 integration / Ruff / mypy / cold / scope | **仍为 UNRUN** |
| VALIDATION9 / 整包 Windows PASS | **未授予**；须 F8 返工复验 PASS 后再申请 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 13.6 F8 结论

**F8_REVIEW_FAIL**（P1：无 §15 依据移除 `verify_target_artifact` 窄 stub，可静态预见 PROJECT-only 正测偏离目的）。实现者最小返工仅限 `tests/unit/test_m3_successor_upstream_stage.py`（+delivery 修正表述）；**不得**改 production。审查者未改实现、未跑 Python。

---

## 14. F8_P1_REVIEW（对照 taskbook §16）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F8 同一独立初验者；未参与实现<br>
范围：只读 taskbook §16、delivery §14、exact unit 返工；production / 其他 tests / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 14.1 写范围与冻结

| 项 | 结论 |
| --- | --- |
| 返工写集 | 仅 `tests/unit/test_m3_successor_upstream_stage.py` + delivery/taskbook（审查只读） |
| production 三文件 | **冻结**：SHA256 与 F4–F8 指纹一致 |
| 其他 tests | **冻结** |

### 14.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | positive 仅恢复 `plan_module.verify_target_artifact` 窄 stub | **通过** | L1072–1076：注释恢复；`setattr(..., lambda **_: target)` |
| 2 | stub 返回 context 真实 `target`（非伪造） | **通过** | `target = kwargs["target"]`，`kwargs` 来自 `_plan_context_with_feature_worker_seam` |
| 3 | §15 feature-worker seam 保留 | **通过** | 正测/负测均经 `_plan_context_with_feature_worker_seam`（安装非 dump fake、三别名、`finally` 恢复） |
| 4 | 真实 `build_backtest_plan_artifact` 保留；未 stub builder | **通过** | 正测 L1091+ 直调；builder 前仍断言 subprocess 非 feature/dump fake |
| 5 | wrong-alias **无** verifier stub | **通过** | 全文件仅一处 `verify_target_artifact` setattr（正测）；wrong-alias L1110–1153 无 stub，真实路径拒 `EXTERNAL_QLIB` |
| 6 | delivery §14 / §13.2 表述闭合 | **通过** | §14 六段式齐全；§13.2 已改为**保留**正测窄 stub、wrong-alias 不加 stub |

### 14.3 发现分级

**无 P0/P1。** 前轮 P1 已按 §16 最小面闭合。

### 14.4 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | 前轮删除正测窄 stub → F8_REVIEW_FAIL |
| 根因 | 无 §15 授权；偏离 PROJECT-only roots 测试目的 |
| 规则 | §16：仅正测恢复 stub→真实 context target；seam 保留；wrong-alias 不加 stub |
| 最小复现 | 已由前轮 §13.3 给出；本轮静态确认 stub 已回 |
| 测试 | `test_build_backtest_plan_artifact_positive_project_only_roots` 含窄 stub；wrong-alias 无 stub |
| 通过条件 | 本表 §14.2 全通过；可申请完整 VALIDATION9（**不**继承本轮为整包 PASS） |

### 14.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION9 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION9 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 14.6 F8_P1 结论

**F8_P1_REVIEW_PASS**（taskbook §16 窄 verifier stub 最小返工闭合）。可申请**完整 VALIDATION9**；**不**继承本轮 / VALIDATION8 部分结果为整包 PASS。

---

## 15. VALIDATION9_F10_REVIEW（对照 taskbook §17）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F8_P1 同一独立初验者；未参与实现<br>
范围：只读 taskbook §17、delivery §15、exact integration F10 diff；production / unit / taskbook / delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 15.1 写范围与证据边界

| 项 | 结论 |
| --- | --- |
| F10 写集 | 仅 `tests/integration/test_m3_successor_upstream_stage.py`（+delivery/taskbook）；unit/production 审查冻结：production SHA 与 F4–F8 指纹一致 |
| VALIDATION9 | Parser/argv/identity **PASS**；unit **`84 passed`**（stdout SHA=`be6268c9…`）；integration **`41 passed / 1 failed`**（717.01s；stdout SHA=`7c256850…`） |
| 唯一失败 | 已过 Authority-B feature fixture，真实进入 `build_backtest_plan_artifact` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID`（legacy root vs PROJECT） |
| Ruff / mypy / cold / scope | **UNRUN** |
| 本轮复验命令 | **全部 UNRUN** |

证据根：`artifacts/agent_runs/m3-r2w-rebuilt-validation9-20260826T073552Z/`（与 delivery 一致）。

### 15.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | feature original 恢复后再装窄 verifier stub | **通过** | L841–846 restore subprocess；L860+ 才 `positive_mp` |
| 2 | 更窄 `positive_mp` 仅 stub `verify_target_artifact`→context 真实 `target` | **通过** | `target = kwargs["target"]`；`lambda **_: target`；`verify_target_artifact(**{}) is target` |
| 3 | 真实 `build_backtest_plan_artifact` 保留；未 stub builder | **通过** | positive 内直调 builder |
| 4 | positive 退出后 identity 恢复为 `real_verify_target` | **通过** | L881 `assert plan_module.verify_target_artifact is real_verify_target` |
| 5 | wrong-alias 在 stub 撤销后真实拒绝 `EXTERNAL_QLIB` | **通过** | L889–903 进入前/后均 `is real_verify_target`；期望 `M3_BACKTEST_PLAN_ARTIFACT_INVALID` |
| 6 | F6/F7 subprocess + feature-worker seam 不漂移 | **通过** | A 捕获/恢复、bridge pin、B 安装 `_fake_feature_worker`、非 dump、三别名、`_context` 后 restore original 均保留 |
| 7 | delivery §15 六段式 + 证据 SHA 闭合 | **通过** | 与只读哈希一致 |

### 15.3 发现分级

**无 P0/P1。**

### 15.4 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V9 integration 41/1：feature seam 已通后 builder 因缺窄 verifier stub 撞 alias |
| 根因 | F7 删除 integration positive 的 `verify_target_artifact` 窄 stub |
| 规则 | §17：更窄 `positive_mp` 生命周期；wrong-alias 无 stub；保留 F6/F7 seam + 真实 builder |
| 最小复现 | 见 delivery §15.2 / V9 stdout |
| 测试 | `test_integration_real_api_positive_probe_and_project_roots` 已补 stub 生命周期断言 |
| 通过条件 | §15.2 全通过；可申请完整 VALIDATION10（**不**继承本轮为整包 PASS） |

### 15.5 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION10 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION10 |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 15.6 F10 结论

**F10_REVIEW_PASS**（taskbook §17 integration positive verifier seam 闭合）。可申请**完整 VALIDATION10**；**不**继承 VALIDATION9 / 本轮部分绿为整包 PASS。

---

## 16. VALIDATION10_F11_REVIEW（对照 taskbook §18）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F10 同一独立初验者；未参与实现<br>
范围：只读 taskbook §18、delivery §16、exact12 内 F11 静态 diff（runtime 七注解 + downstream float helper + unit 三测）；production/tests/taskbook/delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 16.1 写范围、指纹与 VALIDATION10 证据边界

| 项 | 结论 |
| --- | --- |
| exact12 / base | dirty 仅 exact12；HEAD=`1d9b4e09…`；`git diff --check` PASS；cached=0 |
| F11 写集（实现侧） | `successor_runtime.py` 七字段返回注解；`successor_downstream_stage.py` `_require_finite_config_float`；unit：`test_public_api_bundle_seven_stage_return_annotations_are_canonical` / `test_require_finite_config_float_*` / `test_formal_backtest_rejects_marker_wrapper_wrong_return_types` |
| upstream | **冻结未漂**：SHA256=`2adb24f040cf191ea7f28855b8d4b56e35350c69cd455f387aacc0f16be5a51c`（与 F4 指纹一致） |
| runtime / downstream 指纹（F11 后只读） | runtime=`272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b`；downstream=`452270df1a30df56d88379e77b3c32e3574bc6f76434ef894ce4ff34bd7d48e6`（相对 F4 变更符合写集） |
| VALIDATION10（未重跑） | Parser/argv/identity **PASS**；unit **`84 passed`**（stdout SHA=`7469e724…`）；integration **`42 passed`**（SHA=`1cda2fd0…`）；Ruff exact9 **PASS**（SHA=`af352a86…`）；mypy production3 **STOP** 21 errors 全在 `successor_downstream_stage.py`（SHA=`e539f47c…`）；cold/scope **UNRUN** |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation10-20260826T080935Z/`；stage-summary SHA=`c4986776…`；与 delivery §16.1 逐项一致 |
| 本轮复验命令 | **全部 UNRUN** |

### 16.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 仅七处返回注解收窄为 canonical concrete（TYPE_CHECKING + quoted） | **通过** | `SuccessorPublicApiBundle`：`formal_backtest_stage`→`FormalBacktestStageResult`；`formal_tracking_stage`→`FormalTrackingStageResult`；`reproducibility_stage`→`FormalReproducibilityResult`；`readiness_stage`/`readiness_verifier`→`VerifiedReadinessEvidenceArtifact`；`acceptance_stage`→`FormalAcceptanceStageResult`；`acceptance_audit`→`AcceptanceDecisionV1`。其余 callable 仍 `Callable[..., object]`。类型名仅在 `TYPE_CHECKING` 块 import |
| 2 | 无 Any/cast/type:ignore/wrapper/duplicate DTO（本轮 SSOT 路径） | **通过** | 七字段注解无 Any/`cast`/`type: ignore`；无 wrapper/新 DTO。runtime 既有 `stage_runner_type: type[Any]` 与 terminal 解析 `cast` **非本轮新增、非七字段收窄** |
| 3 | callable `is` 绑定、字段序、运行校验、执行分支不变 | **通过** | `make_public_successor_api_bundle` 字段序与 dataclass 一致；`_require_canonical_public_api_bundle` 仍 `is` 比对 `_PUBLIC_API_CALLABLE_FIELDS`；unit 钉七 callable `is` 真实 public 函数；Gate 顺序仍 `_GATES=(summary, reproducibility, readiness, acceptance)`；formal/repro/readiness/acceptance 执行体仍直调 public API + `_stage_receipt_ref` |
| 4 | downstream 直接消费 canonical 结果属性 | **通过** | 无中间 DTO；消费 `receipt_path`/`receipt`/`comparison_key`/`report`/`decision` 等；summary verifier 仍 exact `type(verified) is VerifiedResearchSummaryArtifact` |
| 5 | `_require_finite_config_float` exact-float + finite；拒 bool/int/str/NaN/Inf；稳定 gate fail | **通过** | `type(value) is not float or not math.isfinite(value)` → `SUCCESSOR_GATE_FAILED`；repro verify 容差仅经该 helper；裸 `float(...)` 已自 acceptance atol 路径移除 |
| 6 | wrong marker/wrapper/return 仍 fail-closed | **通过** | unit：`marker`/`wrapper`/`_MarkerResult` → `SUCCESSOR_STAGE_INVALID`（canonical apis 旁路后仍拒） |
| 7 | receipt/schema/identity/Gate 顺序未改 | **通过** | 未见 schema/identity helper 改动；upstream 指纹冻结；Gate prior 基数与 `_GATES` 不变 |
| 8 | task§18 ↔ delivery§16 证据一致 | **通过** | 84/42/Ruff PASS/mypy 21 STOP/SHA/evidence root 一致 |

### 16.3 审查者新增对抗性静态反例（实现者未专测）

| 反例 | 静态判定 | 不信任注解的依据 |
| --- | --- | --- |
| **Lying annotation**：callable 注解声称返回 `FormalBacktestStageResult`，运行时返回 `object()` / 伪 namespace | **仍 fail-closed** | `from __future__ import annotations` + `TYPE_CHECKING`：注解不参与运行；路径走属性访问 + `_stage_receipt_ref` 的 `type(receipt) is StageReceipt` / verify bytes；异常归一 `SUCCESSOR_STAGE_INVALID`（与 unit marker/wrapper 同门禁）。**不**存在“因注解为真而放行”的分支 |
| **float 子类 / `Decimal`**：`class F(float): pass` 的 `F(1e-3)` 或 `Decimal("0.1")` 作为 atol | **仍 fail-closed** | `type(value) is not float` 拒绝子类与 Decimal；有限性检查不会被碰到。unit 列表覆盖 bool/int/str/None/NaN/±Inf，**未列**子类/Decimal，但源码 exact-type 合同已静态闭合本反例 |

### 16.4 发现分级

**无 P0/P1。**（mypy 绿须由新完整 VALIDATION11 证明；本轮 STATIC_ONLY 不洗白 V10 mypy STOP。）

### 16.5 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V10 mypy production3：七 stage/audit 结果为 `object` → 21× attr-defined/arg-type；裸 `float` 可接受 bool/非有限 |
| 根因 | bundle 统一 `Callable[..., object]`；config 容差未 enforce exact float |
| 规则 | §18：仅七字段 canonical quoted 注解；`TYPE_CHECKING`；禁 Any/cast/type:ignore/wrapper/DTO；`_require_finite_config_float`；`is`/字段序/执行不变 |
| 最小复现 | V10 `05-mypy.stdout.log`（21 errors）；`float(True)` 语义（交付陈述） |
| 测试 | 注解/`is` 绑定；exact float 拒非法；marker/wrapper/wrong-type fail-closed；审查者追加 lying-annotation 与 float-subclass/Decimal 静态反例 |
| 通过条件 | §16.2–16.3 全通过；可申请**完整 VALIDATION11**（须含 mypy）；**不**继承 V10 部分绿或本轮静态改动为整包 PASS |

### 16.6 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION11 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION11（含 mypy） |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 16.7 F11 结论

**F11_REVIEW_PASS**（taskbook §18 七处 canonical 返回类型 SSOT 与 config exact-float 收窄闭合）。可申请**完整 VALIDATION11**（须含 mypy）；**不**继承 VALIDATION10 / 本轮静态改动为整包 PASS。

---

## 17. VALIDATION11_F12_REVIEW（对照 taskbook §19）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F11 同一独立初验者；未参与实现<br>
范围：只读 taskbook §19、delivery §17、`run_successor_formal_stage` 授权局部名 diff；production/tests/taskbook/delivery **只读**<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 17.1 写范围、指纹与 VALIDATION11 证据边界

| 项 | 结论 |
| --- | --- |
| exact12 / base | dirty 仅 exact12；HEAD=`1d9b4e09…`；`git diff --check` PASS；cached=0 |
| F12 授权写集 | 仅 `successor_downstream_stage.py` 内 formal stage 两局部名（+ taskbook/delivery）；tests/review **冻结**（本审查只写 review） |
| runtime / upstream | **未漂**：runtime=`272c42f6…`（同 F11）；upstream=`2adb24f0…`（同 F4） |
| downstream 指纹（F12 后只读） | `02bae1d1779fc04f8486cf32bb4467486a4418d9ef680a11f46cbb5f5c109acd`（相对 F11 仅本授权改动） |
| VALIDATION11（未重跑） | identity **PASS**（stdout SHA=`e153b441…`）；unit **`57 passed`**（SHA=`950b983d…`）；integration **`29 passed`**（SHA=`26493122…`）；Ruff **PASS**（SHA=`af352a86…`）；mypy production3 **STOP** 单错 `:214 assignment`（SHA=`4a4108d5…`）；cold/scope **UNRUN** |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/`；stage-summary SHA=`034cd671…`；与 task§19 / delivery§17.1 逐项一致 |
| 本轮复验命令 | **全部 UNRUN** |

### 17.2 合同逐项静态核对

| # | 合同点 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 仅分离 `backtest_result` / `tracking_result` | **通过** | backtest 分支赋 `backtest_result` 并消费 `.receipt_path`/`.receipt` 后 `return`；tracking 赋 `tracking_result` 后同形消费 |
| 2 | 调用/参数/顺序/receipt/分支/错误归一不变 | **通过** | `formal_backtest_stage` / `formal_tracking_stage` 关键字实参表、`_stage_receipt_ref` 节点构造、`except`→`SUCCESSOR_STAGE_INVALID` 与 F11 语义等价；无 API/schema/Gate 改动 |
| 3 | 无 cast/Any/type:ignore/union/wrapper/API 变更 | **通过** | formal stage 函数体内未见 `cast`/`Any`/`type: ignore`/union 合并类型；无 wrapper；runtime 指纹冻结 |
| 4 | task/delivery 准确绑定 V11 57+29+Ruff PASS / 单 mypy STOP / cold·scope UNRUN | **通过** | 只读 stdout/exit/stage-summary 与 delivery 表及 task§19 数字一致 |

### 17.3 审查者新增对抗性静态反例

| 反例 | 静态判定 | 依据 |
| --- | --- | --- |
| **跨分支局部泄漏**：`backtest_result` 是否可在 tracking 路径被读取，或 `tracking_result` 是否可回指 backtest 结果 | **不能泄漏** | `if stage == "backtest":` 块在消费 `backtest_result` 后立即 `return`，控制流不落入 tracking；`tracking_result` 仅在该 `if` 之外绑定与消费；两名互不出现在对方分支。无共享 `result`、无跨分支赋值/别名 |

### 17.4 发现分级

**无 P0/P1。**（mypy 绿须由新完整 VALIDATION12 证明；本轮不洗白 V11 mypy STOP。）

### 17.5 六段式（本轮闭合记录）

| 字段 | 内容 |
| --- | --- |
| 现象 | V11 mypy：同一 `try` 内共享 `result` 先 `FormalBacktestStageResult` 再赋 `FormalTrackingStageResult` → `:214 assignment` 单错 |
| 根因 | F11 收窄返回类型后共享局部名跨不相容类型；非行为/API 错误 |
| 规则 | §19：仅 `backtest_result`/`tracking_result`；调用/参数/顺序/receipt/分支/错误归一逐字等价；禁 cast/Any/type:ignore/union/wrapper/API |
| 最小复现 | V11 `05-mypy.stdout.log` 单行 assignment |
| 测试 | 本轮 tests 冻结；审查者追加跨分支局部不泄漏静态反例 |
| 通过条件 | §17.2–17.3 全通过；可申请**完整 VALIDATION12**（须含 mypy）；**不**继承 V11 部分绿或本轮静态改动为整包 PASS |

### 17.6 Gate / 验证边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / cold / stage / commit | **UNRUN / 未执行** |
| VALIDATION12 / 整包 Windows PASS | **未授予**；须新申请完整 VALIDATION12（含 mypy） |
| R2B / CLI / actual worker / Qlib / new root / retained / M3 Gate | **未关闭** |

### 17.7 F12 结论

**F12_REVIEW_PASS**（taskbook §19 formal backtest/tracking 结果局部名分离闭合）。可申请**完整 VALIDATION12**（须含 mypy）；**不**继承 VALIDATION11 / 本轮静态改动为整包 PASS。

---

## 18. EVIDENCE_REVIEW（对照 taskbook §20 / delivery §18）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F12 同一独立初验者；未参与实现<br>
范围：只读 taskbook §20、delivery §18、retained VALIDATION10/11/12 证据根与报告 SHA；exact12 dirty/scope；组合边界<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 18.1 证据根存在性与组合口径

| 验证 | 证据根 | 组合口径（task/delivery 陈述 ↔ 留存日志） |
| --- | --- | --- |
| VALIDATION10 | `artifacts/agent_runs/m3-r2w-rebuilt-validation10-20260826T080935Z/` | unit **84 PASS** → integration **42 PASS** → Ruff **PASS** → mypy **21 STOP**；cold/scope **UNRUN** |
| VALIDATION11 | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` | identity **PASS** → unit **57 PASS** → integration **29 PASS** → Ruff **PASS** → mypy **1 STOP**；cold/scope **UNRUN** |
| VALIDATION12 | `artifacts/agent_runs/m3-r2w-rebuilt-validation12-20260826T180000Z-c18d/` | identity **PASS** → Ruff（changed）**PASS** → mypy production3 **PASS** → cold production3 **PASS** → exact12 scope **PASS**；`reused_validation11=unit57_integration29_other_ruff` |

**无矛盾：** V10/V11 的 mypy STOP 在组合表中仍如实保留，未被改称为 PASS；V12 明确复用 V11 已绿 unit/integration，不重写历史 STOP。

### 18.2 精确 SHA 核对（只读重算）

#### VALIDATION10

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| unit stdout | `7469e724…bd2b5ec` | **MATCH** | `84 passed` |
| integration stdout | `1cda2fd0…c0c721` | **MATCH** | `42 passed` |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | `All checks passed!` |
| mypy stdout | `e539f47c…09b4268` | **MATCH** | `Found 21 errors` |
| stage-summary | `c4986776…ee3c9d6` | **MATCH** | `STOP\|STAGE_FAILED:05-mypy` |

#### VALIDATION11

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| identity stdout | `e153b441…195962a3` | **MATCH** | exit=0 |
| unit stdout | `950b983d…f0cd252c` | **MATCH** | `57 passed` |
| integration stdout | `26493122…b13b2059` | **MATCH** | `29 passed` |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | PASS |
| mypy stdout | `4a4108d5…440475fa2` | **MATCH** | `:214` assignment；`Found 1 error` |
| stage-summary | `034cd671…aac35ae64` | **MATCH** | `unit=57_passed`；`mypy=1_error`；cold/scope=UNRUN |

#### VALIDATION12

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | `All checks passed!`（exit=0） |
| mypy stdout | `f6af9a42…5648259c` | **MATCH** | `Success: no issues found in 3 source files` |
| cold stdout | `30fe42e7…84029023` | **MATCH** | production3 三路径列出；exit=0 |
| scope stdout | `1f4605b9…1408f13f` | **MATCH** | `ACTUAL_COUNT=12`；`CACHED_COUNT=0`；`DIFF_CHECK=PASS`；`CACHE_RESIDUE=0`；`OTHER_0xF00=0` |
| stage-summary | `2e0e2038…89fc06405` | **MATCH** | `classification=PASS`；`reused_validation11=unit57_integration29_other_ruff` |
| identity | （delivery 未单列 SHA；exit=0） | **一致** | stdout SHA=`e153b441…`（与 V11 identity 字节相同）；exit=0 |

### 18.3 exact12 scope / dirty / residue（对照 V12 scope + 当前只读 git）

| 项 | 结论 |
| --- | --- |
| exact12 名单 | scope 列出 12 路径与任务书白名单一致（3 production + 6 tests + task/delivery/review） |
| cached | `CACHED_COUNT=0`；当前 `git diff --cached` 空 |
| diff-check | scope `DIFF_CHECK=PASS`；本审查观察 `git diff --check` PASS |
| residue | `CACHE_RESIDUE=0`；`OTHER_0xF00=0`；`RUNROOT=False` |
| HEAD | `1d9b4e09…` 与任务书 exact base 一致 |

### 18.4 越权声明检查

| 声明面 | 结论 |
| --- | --- |
| delivery 状态行 / §18.3 | 明确 **不**表示 actual worker、真实 Qlib、new root、retained、acceptance、M3 Gate |
| taskbook §20 | 终态上限 `R2W_WINDOWS_ENGINEERING_VALIDATED`；同样排除 worker/Qlib/new root/retained/M3 Gate |
| 组合是否冒充整包 Gate | **否**；历史 mypy STOP 保留；V12 仅 Windows 工程验证组合 |

### 18.5 发现分级

**无 P0/P1。** SHA/计数/STOP 边界与 task§20、delivery§18 无矛盾。

### 18.6 EVIDENCE_REVIEW 结论

**EVIDENCE_REVIEW_PASS**（VALIDATION10/11/12 留存根与报告 SHA 闭合；组合口径合法；exact12/cached0/diff/residue 一致；未越权宣称 worker/Qlib/new root/retained/M3 Gate）。
