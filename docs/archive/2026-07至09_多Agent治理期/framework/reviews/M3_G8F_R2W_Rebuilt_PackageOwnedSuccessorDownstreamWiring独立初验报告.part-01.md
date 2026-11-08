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

