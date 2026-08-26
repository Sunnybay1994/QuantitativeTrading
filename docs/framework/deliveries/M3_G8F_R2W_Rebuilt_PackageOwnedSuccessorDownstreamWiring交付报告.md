# M3-G8F-R2W Rebuilt Package-Owned Successor Downstream Wiring 交付报告

状态：`DELIVERY_READY` / `R2W_WINDOWS_ENGINEERING_VALIDATED`（可执行 package-owned successor downstream wiring；**不**表示 actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate 完成）

- task id：`M3-G8F-R2W-REBUILT-PACKAGE-OWNED-SUCCESSOR-DOWNSTREAM-WIRING`
- exact base / HEAD at start：`1d9b4e09c91293de18fea5cf0aa563b782379d37`
- branch：`codex/m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`

## 1. 旧 STOP 如何被解除

| 旧 R2W STOP（`eca54af` 事故线） | 解除路径 |
|---|---|
| aggregate Gate identity 被当作 physical `scope_key` | R2I 已合流：repro=`comparison_key`，acceptance=`acceptance_key`，G8 root stage-aware |
| readiness 两 fold 槽位 vs public 单 `readiness_key` + `_unique_refs` 同 path/SHA 冲突 | **本包重冻**：readiness Gate 精确 **1** 份物理 receipt（`fold=None`/`horizon=None`/`scope_key=readiness_key`）；双折聚合只在 `GateExecution.identity` |
| 十个 downstream callable 缺失 → 无法零参 `make_canonical` | **本包落地** `successor_downstream_stage.py` + 零参 factory |

## 2. 修改路径（exact12 内）

1. `src/quant/research/m3/successor_runtime.py` — Protocol `prior_refs`；零参 `make_canonical`；adapter `is` 绑十下游；readiness 卡度=1；`summary_verifier` 绑 R2S **stage** public verifier
2. `src/quant/research/m3/successor_upstream_stage.py` — 窄 public `rehydrate_successor_formal_{backtest,tracking}_inputs`；`rehydrate_successor_summary_horizon_verify_inputs`
3. `src/quant/research/m3/successor_downstream_stage.py`（new）— 十 callable；summary verify exact 调 `apis.summary_verifier`
4–9. 对应 unit/integration tests（runtime/upstream/downstream；含 REWORK1 F1–F3 行为反例）
11. 本交付报告

未写 taskbook/review；未改 formal/repro/readiness/acceptance/quality/R2S/`evaluate.py` 科学体/orchestration/config/`__init__.py`/schema。

## 3. API 调用图（压缩）

```
make_canonical_successor_production_dependencies()  # zero-arg
  ├─ upstream.run_successor_upstream_wave
  ├─ upstream.run_successor_formal_summary_gate
  └─ downstream.{run_formal_stage, verify_fold, verify_summary,
                 run/verify_reproducibility, run/verify_readiness,
                 run/verify_acceptance, verify_gate}

run_formal_stage(prior_refs)
  → rehydrate_successor_formal_{backtest|tracking}_inputs(prior_refs)
  → public formal_backtest_stage | formal_tracking_stage(+create_mlflow_tracking_client(canonical_uri))

verify_summary
  → per horizon: rehydrate_successor_summary_horizon_verify_inputs(folds, summary_ref)
  → exact apis.summary_verifier(=verify_research_summary_stage_artifact)

run_readiness → run_readiness_evidence_stage(fold_001 config/release) → 1 ref
run_acceptance → verify readiness + run_quality_gate + resolve_acceptance_subject
                 + build_acceptance_evidence_plan + run_formal_acceptance_stage
```

## 4. 现象—根因—规则—最小复现—新增测试—通过条件（首轮）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增测试 | 通过条件 |
|---|---|---|---|---|---|---|
| F1 | readiness 要 2 fold refs 与 public 单 key 冲突 | 旧卡度合同 | §3 单全局 receipt | 构造 2 refs / fold-bound | unit readiness 0/2/fold/horizon；integration collide→extra fold-bound | `_validate_gate_execution` fail-closed；合法 1 份 PASS |
| F2 | formal 无 prior_refs | Protocol/adapter 未传 | §4 fresh prior closure | unsorted prior_refs | unit formal prior_refs / Protocol 源码钉 | `SUCCESSOR_STAGE_INVALID` |
| F3 | tracking 缺同 fold/horizon backtest | 未强制 prior | §4 tracking 见真实 backtest | tracking 无 matching backtest ref | （首轮不足；见 §7 REWORK1） | fail-closed |
| F4 | wrapper 替换 canonical | 无十函数 `is` 绑 | §5 | lambda/partial/wrapper | unit/integration 逐槽位 | `SUCCESSOR_INPUT_INVALID` |
| F5 | 同 bytes 异 path readiness | 所有权单射 | §3/R2I | 双 path 同 SHA | unit `_unique_refs` / ownership | `SUCCESSOR_TERMINAL_INVALID` |
| F6 | 零参 factory 缺失 | 十 callable 未落地 | §5 | `make_canonical()` | unit/integration bind-by-is | 全槽位 `is` 命中 |

## 5. 未运行边界（STATIC_ONLY）

未跑：Python / pytest / Ruff / mypy / cold / actual worker / 真实 Qlib / network / new root / retained / stage / commit。

终态上限申请条件：独立初验 PASS 后，才可申请 Windows 定向验证（identity → exact unit/integration → Ruff → mypy production → cold → exact12 scope）。Windows 绿**不**替代 actual worker / Qlib / new root / retained / M3 Gate。

## 6. 静态卫生

- dirty：exact12 内（含既有 taskbook untracked + 本 delivery；**不**写 review）
- `git diff --check`：PASS
- 无临时文件 / 真实产物 / 凭据
- `CONTRACT_STOP`：**未触发**（见 §7 F1 签名闭合说明）

## 7. STATIC_REWORK1 闭环（对照 taskbook §10 / 独立初验 F1–F3）

### F1 — Summary Gate 必须调用 R2S public fresh verifier

| 项 | 内容 |
|---|---|
| 现象 | `verify_successor_summary_gate` 只验 receipt bytes，从不调用 `apis.summary_verifier` |
| 根因 | 实现停在 `verify_stage_receipt_with_bytes`；未从 fold receipts fresh 重建 typed evaluation/publication 闭包 |
| 规则 | 每 horizon 从显式 summary ref 定位 final root；fresh 重建 `FormalSummaryStagePublicationIdentity` + evaluations；exact 调 `apis.summary_verifier`；两 horizon 均通过并与 refs/aggregate identity 闭合 |
| 最小复现 | 合法 summary Gate + 缺 verifier 调用仍 PASS（返工前）；返工后 spy 计次 |
| 新增测试 | `test_verify_summary_calls_summary_verifier_exact_once_per_horizon`；wrapper → `SUCCESSOR_INPUT_INVALID`；wrong artifact/identity；one-horizon tamper；bundle `is verify_research_summary_stage_artifact` |
| 通过条件 | 每 horizon exact1 调用；缺调用/wrapper/wrong/tamper fail-closed；无 R2S 科学复制、无 fallback |
| 签名闭合 | Stage 发布叶为 `summaries/{ek}/h{n}/{model}/{version}`，**不能**满足 legacy `verify_research_summary_artifact` 的 `root.name == "horizon={n}"`。exact12 内将 bundle `summary_verifier` 重绑为既有 public `verify_research_summary_stage_artifact`（同在 `evaluate.py`，未改 R2S 科学体、未复制 verifier）。**非** CONTRACT_STOP：可消费的 public stage verifier 签名与 publication identity 对齐。 |

### F2 — Tracking 真实行为级 prior closure

| 项 | 内容 |
|---|---|
| 现象 | exact12 仅有源码/API 存在性，无缺/跨 horizon/fold/request/重复乱序 backtest 行为测 |
| 根因 | 首轮交付把 tracking 单射当成已测 |
| 规则 | 缺同 fold/horizon backtest、跨 horizon/fold/request、重复/乱序 prior 必须在 public tracking handler **前**拒绝；磁盘伪 latest 无显式 ref 仍拒 |
| 最小复现 | `rehydrate_successor_formal_tracking_inputs(prior_refs=(), …)`；或 backtest horizon≠请求 horizon |
| 新增测试 | missing / cross-horizon / cross-fold / cross-request / duplicate+unsorted；`run_successor_formal_stage(tracking)` + spy：`formal_tracking_stage` / `make_formal_tracking_run_plan` / `create_mlflow_tracking_client` 均零调用，且伪 `latest/backtest/...` 存在仍拒 |
| 通过条件 | 一律 `SUCCESSOR_STAGE_INVALID`（或 canonical 前置 `SUCCESSOR_INPUT_INVALID`）；spies 空 |

### F3 — Readiness physical-vs-aggregate 对抗

| 项 | 内容 |
|---|---|
| 现象 | 缺「唯一 readiness ref 的 `scope_key` 换成 aggregate `gate.identity`」反例 |
| 根因 | 仅测了 0/2/fold/horizon/same-bytes，未测 aggregate 写入物理槽 |
| 规则 | `_validate` 可因 hex64/形状放行；`verify_successor_readiness_gate` 必须因 `readiness_key != ref.scope_key` fail-closed |
| 最小复现 | `scope_key=identity`、真实 `readiness_key=K≠identity`，调用 verify |
| 新增测试 | `test_readiness_verify_rejects_aggregate_identity_as_physical_scope_key`：先 `_validate` PASS，再 verify → `SUCCESSOR_GATE_FAILED` |
| 通过条件 | 物理只认 public `readiness_key`；aggregate 只留 `GateExecution.identity` |

## 8. REWORK1 退出

`DELIVERY_READY`（STATIC_REWORK1 闭合；交回同一 reviewer 复验）。未跑任何 Python/pytest/Ruff/mypy/cold/Qlib/network/stage/commit。

## 9. VALIDATION1 证据与 F4 test-only 闭环（taskbook §11）

### 9.1 VALIDATION1 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| identity | **PASS** |
| exact unit | **`74 passed / 1 failed`** |
| integration | **UNRUN** |
| Ruff | **UNRUN** |
| mypy | **UNRUN** |
| cold | **UNRUN** |
| exact12 scope | **UNRUN** |
| 资源 / 临时目录 / 0xF00 | 已释放（VALIDATION1 陈述） |

失败仅为测试面全文件字符串断言误伤合法私有 helper annotation，**不构成 production 红**。

### 9.2 F4 — public rehydrate 返回类型测试边界

| 项 | 内容 |
|---|---|
| 现象 | 扫描整个 `successor_upstream_stage.py` 文本并禁止 `-> _SharedUpstream`，误命中合法私有 `_reconstruct_shared_upstream(...) -> _SharedUpstream`（VALIDATION1：74 绿 / 1 红） |
| 根因 | 合同只约束三个 **public** rehydrate API 不得泄露私有返回类型；全文件子串断言过宽 |
| 规则 | 用 AST/signature **只**定位三个 public rehydrate def，逐一断言公开强类型返回 annotation；private helper 可返回 `_SharedUpstream`；保持 exact type / 私有字段不泄露 / caller 不可注入 |
| 最小复现 | 源码含 `_reconstruct_shared_upstream(...) -> _SharedUpstream` 时，全文件 `assert "-> _SharedUpstream" not in public` 失败 |
| 修正测试（本轮写白名单） | 仅改 `tests/unit/test_m3_successor_upstream_stage.py`：`test_public_rehydrate_defs_ast_return_annotations_are_strong_public_types`；`test_public_rehydrate_signature_return_annotations_match_public_inputs`；`test_private_reconstruct_shared_upstream_may_return_shared_upstream`；`test_public_rehydrate_return_types_exact_and_do_not_leak_shared_upstream`；`test_caller_cannot_inject_shared_upstream_into_public_rehydrate_apis` |
| 通过条件 | 三 public 返回分别为 `SuccessorFormalBacktestInputs` / `SuccessorFormalTrackingInputs` / `SuccessorSummaryHorizonVerifyInputs`；private reconstruct AST 返回 `_SharedUpstream` 合法；public Inputs 字段无 `_SharedUpstream`；unexpected `shared`/`_SharedUpstream` kwargs → `TypeError`；**未**改 production、**无** `Any`/`type: ignore` |
| 本轮冻结 | taskbook / review / 全部 production / **其他 tests** 字节未改（含既有过宽全文件子串断言所在 sibling unit 文件；本轮按 §11 把精确边界 SSOT 落在 upstream unit） |

### 9.3 本轮退出

`DELIVERY_READY`（VALIDATION1_F4_TEST_ONLY_REWORK）。同一 reviewer 只读复验 **test-only** diff；PASS 后申请**新的完整 VALIDATION2**，不继承本轮为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit。

## 10. VALIDATION2 证据与 F5 test-only 闭环（taskbook §12）

### 10.1 VALIDATION2 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| Parser / identity | **PASS** |
| exact unit | **`79 passed / 1 failed`**（654.69s） |
| unit stdout SHA-256 | `c4c8b32a2643865f8e16b85cb9d11525ba15ad055d9c66f0728f5283aa6a43af` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation2-20260826T132000Z/` |
| integration | **UNRUN** |
| Ruff | **UNRUN** |
| mypy | **UNRUN** |
| cold | **UNRUN** |
| exact12 scope | **UNRUN** |
| 资源 / 临时目录 / cache / 0xF00 | 已释放（VALIDATION2 陈述） |

失败点：`tests/unit/test_m3_successor_downstream_stage.py` 全文件禁止 `-> _SharedUpstream`，误命中合法 private `_reconstruct_shared_upstream(...) -> _SharedUpstream`。**不构成 production 红**。

### 10.2 F5 — downstream 同类 public 返回类型误检

| 项 | 内容 |
|---|---|
| 现象 | F4 只修了 upstream unit；downstream unit L148 仍全文件扫描并禁止 `-> _SharedUpstream`（VALIDATION2：79 绿 / 1 红） |
| 根因 | 与 F4 相同：合同只禁三个 public rehydrate 泄露私有返回类型；private helper 可显式返回 `_SharedUpstream` |
| 规则 | AST + `inspect.signature` 精确定位三个 public rehydrate；不得全文件禁止 private annotation；保持 exact type / 字段不泄露 / kwargs 不可注入 |
| 最小复现 | `assert "-> _SharedUpstream" not in public` 对含 private `-> _SharedUpstream` 的 upstream 源码失败 |
| 修正测试（本轮写白名单） | 仅改 `tests/unit/test_m3_successor_downstream_stage.py`：删除全文件子串禁令；新增 `test_public_rehydrate_ast_return_annotations_are_strong_public_types`（含 private reconstruct 合法返回 `_SharedUpstream`）；`test_public_rehydrate_signature_return_annotations_match_public_inputs`；`test_public_rehydrate_return_types_exact_and_do_not_leak_shared_upstream`；`test_caller_cannot_inject_shared_upstream_into_public_rehydrate_apis`；保留 callable/class/`_SharedUpstream` 仍存在的存在性钉 |
| 通过条件 | 三 public 返回 `SuccessorFormalBacktestInputs` / `SuccessorFormalTrackingInputs` / `SuccessorSummaryHorizonVerifyInputs`；private reconstruct AST=`_SharedUpstream`；public Inputs 字段无泄漏；`shared`/`_SharedUpstream` kwargs → `TypeError`；**未**改 production、**无**新增 `Any`/`type: ignore`、**未**删 private annotation |
| 本轮冻结 | taskbook / review / 全部 production / **其他 tests**（含 F4 upstream unit）字节未改 |

### 10.3 本轮退出

`DELIVERY_READY`（VALIDATION2_F5_TEST_ONLY_REWORK）。同一独立 reviewer 只读复验 **test-only** diff；PASS 后申请**新的完整 VALIDATION3**，不继承 VALIDATION2 为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit。

## 11. VALIDATION3 证据与 F6 test-only 闭环（taskbook §13）

### 11.1 VALIDATION3 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| Parser / identity | **PASS** |
| exact unit | **`84 passed`** |
| exact integration | **`41 passed / 1 failed`**（710.56s） |
| integration stdout SHA-256 | `19059559a9abcb7510dd67b5bf1aed41140bdde7d8b1b755aa870181e7843b73` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation3-20260826T140000Z/` |
| Ruff | **UNRUN** |
| mypy | **UNRUN** |
| cold | **UNRUN** |
| exact12 scope | **UNRUN** |
| 资源 / temp / cache / 0xF00 | 已释放（VALIDATION3 陈述） |

唯一失败：`tests/integration/test_m3_successor_upstream_stage.py::test_integration_real_api_positive_probe_and_project_roots` Authority B `plan_support._context`；深层 feature support 将底层异常归一为 `M3_FEATURE_ARTIFACT_INVALID`。**尚未进入本包 production 目标路径**。

### 11.2 F6 — integration fixture 共享 subprocess authority 恢复

| 项 | 内容 |
|---|---|
| 现象 | Authority A 经 shared `subprocess` 安装 provider dump fake；Authority B 需要真实 feature worker。两段虽用不同 `MonkeyPatch.context()`，但未像已验收 `test_m3_summary_stage.py` 那样显式 capture/restore/assert 共享 `subprocess.run` authority，导致 A→B 缝泄漏被 feature wrapper 模糊 |
| 根因 | 缺少 pre-A exact callable 捕获、A 内 fake 生效证明、A 退出后/`_context` 前 exact restore + 共享引用 `is` 断言 |
| authority 规则 | 进入 A 前捕获 exact `subprocess.run`；A 内证明 fake 在 stdlib/`provider`/`provider_validation` 三处同对象生效；A 退出后、B `_context` 前用测试自有窄 helper 恢复该 exact callable 并逐项 `is` 断言；B 仍走 plan fixture 真实 feature worker，不得用 A 的 provider-dump fake 顶替；恢复失败须在 `_context` 前以 `AssertionError` 暴露 |
| 最小复现 | A 安装 `_PROVIDER._fake_dump` 后未显式恢复即进入 `plan_support._context` → feature 路径失败被归一为 `M3_FEATURE_ARTIFACT_INVALID` |
| 修正测试（本轮写白名单） | 仅改 `tests/integration/test_m3_successor_upstream_stage.py`：新增 `_assert_shared_subprocess_run` / `_restore_shared_subprocess_run`（模式对齐 summary_stage，**不** import 其 private helper）；`test_integration_real_api_positive_probe_and_project_roots` 在 A 前捕获、A 内证明 fake=`_PROVIDER._fake_dump`、A 末恢复、A 后泄漏即 `AssertionError`、bridge pin 后进 B `_context`、B 后仍断言无 dump-fake 泄漏 |
| 通过条件 | A 期间 fake 三别名一致；A→B 缝与 `_context` 前 `subprocess.run is original`；B 使用 plan_support feature worker 路径（非 dump fake）；恢复失败不进入 feature wrapper；**未**改 production / 其他 tests / PYTHONPATH / cwd / verifier·builder stub 放宽 |
| 本轮冻结 | taskbook / review / 全部 production / **其他 tests** 字节未改 |

### 11.3 本轮退出

`DELIVERY_READY`（VALIDATION3_F6_TEST_ONLY_REWORK）。同一独立 reviewer 只读复验 **test-only** diff；PASS 后申请**新的完整 VALIDATION4**，不继承 VALIDATION3 为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / stage / commit。

## 12. VALIDATION4 证据与 F7 test-only 闭环（taskbook §14）

### 12.1 VALIDATION4 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| exact unit | **`84 passed`**（再次） |
| exact integration | **`41 passed / 1 failed`** |
| Ruff / mypy / cold / scope | **UNRUN** |

F6 已排除 A→B provider-dump 泄漏；失败仍在 Authority B legacy feature fixture（尚未进入本包 production 目标）。

### 12.2 F7 — Authority B 受控 feature worker ownership

| 项 | 内容 |
|---|---|
| 现象 | F6 恢复 original 后，Authority B 把 shared `subprocess.run` 固定为真实 callable；深层 `_build_feature_bundle` 捕获后尝试真实 feature worker → `M3_FEATURE_ARTIFACT_INVALID` |
| 根因 | 普通独立 feature 测试会先安装 `_fake_feature_worker`；本测 B 段未在 `_context` 前安装该 test-owned seam |
| authority 规则 | 保留 F6「A 退出后 original exact 恢复」；B 进入 `_context` 前在独立 `plan_mp` 安装 exact `feature_support._fake_feature_worker` 并三别名 `is`；`_context` 返回后立即恢复 F6 original，再真实调用 `build_backtest_plan_artifact`；禁止 dump fake / 禁止 feature fake 留到 builder 后 / 禁止 patch production builder·verifier |
| 最小复现 | A 已恢复 original → 直接 `_context`（无 feature fake）→ feature 真实 worker 失败归一 |
| 修正测试 | 仅改 `tests/integration/test_m3_successor_upstream_stage.py`：新增 `_install_shared_subprocess_run`；B 前安装 `_fake_feature_worker` 并断言 `is not _PROVIDER._fake_dump`；`_context` 后 `_restore` original 再跑真实 builder；移除 `verify_target_artifact` stub |
| 通过条件 | A dump fake ≠ B feature fake；B 前 feature fake 三别名生效；B context 后 / builder 前后 original 无泄漏；production builder/verifier 未 stub |
| 本轮冻结 | taskbook / review / production / 其他 tests 未改 |

### 12.3 本轮退出

`DELIVERY_READY`（VALIDATION4_F7_TEST_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION5**，不得把 VALIDATION4 或此前部分绿冒充整包 PASS。本轮 STATIC_ONLY：零 Python / checks / stage / commit。

## 13. VALIDATION8 证据与 F8 test-only 闭环（taskbook §15）

### 13.1 VALIDATION8 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| Parser / argv / identity | **PASS** |
| exact unit（exact3） | **`82 passed / 2 failed`** |
| integration | **UNRUN** |
| Ruff / mypy / cold / scope | **UNRUN** |

两项失败均在新增 unit 节点调用 `plan_support._context` 后，经 alignment→feature fixture 进入 `M3_FEATURE_ARTIFACT_INVALID`；真实 `build_backtest_plan_artifact` **尚未进入**。不构成 production 红。

### 13.2 F8 — unit Authority B feature-worker seam

| 项 | 内容 |
|---|---|
| 现象 | F7 只为 integration Authority B 安装 `_fake_feature_worker`；unit 两节点 `test_build_backtest_plan_artifact_positive_project_only_roots` / `test_build_backtest_plan_artifact_rejects_wrong_alias_roots` 直调 `_context` 缺同一前置 → VALIDATION8 **82/2** |
| 根因 | 与 F7 同类：legacy `_build_feature_bundle` 需 test-owned feature worker seam；unit 遗漏 |
| authority 规则 | `_context` 前捕获 original、安装 exact `feature_support._fake_feature_worker`、断言非 provider dump fake、三别名 `is`；`_context` 返回后（含异常路径 `finally`）立即恢复 original，再真实调用 builder；禁止 stub builder / 泄漏 fake / 改 production |
| 最小复现 | unit 直调 `plan_support._context`（无 feature fake）→ `M3_FEATURE_ARTIFACT_INVALID`，builder 未达 |
| 修正测试 | 仅改 `tests/unit/test_m3_successor_upstream_stage.py`：新增 `_assert/_install/_restore_shared_subprocess_run` 与 `_plan_context_with_feature_worker_seam`；两 builder 节点经该 helper；**保留** positive 节点既有 `verify_target_artifact` 窄 stub（隔离 fixture `root` vs PROJECT-only；**不** stub builder）；wrong-alias **不加** verifier stub |
| 通过条件 | seam 进入 + 三别名 + 非 dump fake；context 后 / 异常路径 original 恢复；builder 前无 fake 泄漏；production builder 真实；positive 可达 PROJECT-only roots 合同 |

### 13.3 本轮退出

`DELIVERY_READY`（VALIDATION8_F8_TEST_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION9**，不继承 VALIDATION8 部分结果为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit。

## 14. F8 独立初验 P1 最小返工（taskbook §16）

### 14.1 现象—根因—规则—最小复现—修正—通过条件

| 项 | 内容 |
|---|---|
| 现象 | F8 实现额外删除 positive PROJECT-only 节点原 `verify_target_artifact` 窄 stub；delivery 曾误写「移除 verifier stub」为修正项；初验 **F8_REVIEW_FAIL / P1** |
| 根因 | 误把 §14「禁 patch verifier」过宽套用到 §15；§15 只禁 stub **builder**，未授权删除该窄 stub。去掉后正测会先撞 legacy fixture receipt alias=`root` 与 PROJECT-only roots 漂移，偏离本测目的 |
| 规则 | 仅在 positive 节点恢复 `plan_module.verify_target_artifact` → 返回 context 真实 `target`；保留 §15 feature-worker seam；wrong-alias **不得**加 stub，继续真实路径拒 `EXTERNAL_QLIB` |
| 最小复现 | seam 恢复后无 stub、以 `artifact_roots={"PROJECT": project_root}` 调真实 builder → 失败落在 target fresh-verify alias，而非 PROJECT-only roots 合同 |
| 修正 | 恢复 positive 窄 stub + 注释；纠正 delivery §13.2 旧表述；wrong-alias 保持无 verifier stub |
| 通过条件 | §15 seam 仍在；正测目的不被 root-alias 淹没；wrong-alias 仍真实拒绝；未改 production |

### 14.2 本轮退出

`DELIVERY_READY`（F8_P1_NARROW_VERIFIER_STUB_REWORK）。交同一 reviewer 复验；**仅**复验 PASS 后申请完整 VALIDATION9。本轮 STATIC_ONLY：零 Python / checks / network / stage / commit。

## 15. VALIDATION9 证据与 F10 test-only 闭环（taskbook §17）

### 15.1 VALIDATION9 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| Parser / argv / identity | **PASS** |
| exact unit（exact3） | **`84 passed`** |
| unit stdout SHA-256 | `be6268c9bd7a8d1e4860e29a09134a7ef086eae849d1e5911ce775879dccb980` |
| exact integration（exact3） | **`41 passed / 1 failed`**（717.01s） |
| integration stdout SHA-256 | `7c256850b65d3c9b523e16682e57b768d127f530fb9b6619be18334f18725852` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation9-20260826T073552Z/` |
| stage-summary SHA-256 | `ef01ee5d13e5a957b13801c6649691966eaee7c0501cb11266ebb6284b931c3e` |
| Ruff / mypy / cold / scope | **UNRUN** |

唯一失败：`test_integration_real_api_positive_probe_and_project_roots` 已越过 Authority-B feature fixture并真实进入 `build_backtest_plan_artifact`，归一为 `M3_BACKTEST_PLAN_ARTIFACT_INVALID`（legacy `root` vs PROJECT-only）。**非** production 红。

### 15.2 F10 — integration positive verifier seam

| 项 | 内容 |
|---|---|
| 现象 | F7 删除 integration positive 的 `verify_target_artifact` 窄 stub；VALIDATION9 在 feature seam 已通后于真实 builder 撞 alias 漂移 → **41/1** |
| 根因 | 与 §16 相同：fixture receipt alias=`root`，本节点传 PROJECT-only roots；缺窄 verifier 隔离 |
| 规则 | Authority B `_context` 后、feature original 恢复后，用**更窄** `MonkeyPatch.context()` 只包 positive builder：`verify_target_artifact` 返回 context 真实 target；positive 后立即撤销；wrong-alias 必须在 stub 撤销后走真实 verifier 拒 `EXTERNAL_QLIB`；禁 stub builder / 伪造 target；保留 F6/F7 seam |
| 最小复现 | feature original 恢复后无 stub → PROJECT-only `build_backtest_plan_artifact` → `M3_BACKTEST_PLAN_ARTIFACT_INVALID` |
| 修正测试 | 仅改 `tests/integration/test_m3_successor_upstream_stage.py`：positive 独立 `positive_mp` stub 生命周期断言；wrong-alias 前断言 `verify_target_artifact is real_verify_target` |
| 通过条件 | stub 进入/退出清晰；wrong-alias 无 stub；F6/F7 subprocess + feature seam 保留；builder 真实 |

### 15.3 本轮退出

`DELIVERY_READY`（VALIDATION9_F10_TEST_ONLY_REWORK）。同一 reviewer 复验；PASS 后申请**完整 VALIDATION10**，不继承部分绿为整包 PASS。本轮 STATIC_ONLY：零 Python / checks / network / stage / commit。

## 16. VALIDATION10 证据与 F11 类型/float 收窄（taskbook §18）

### 16.1 VALIDATION10 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| Parser / argv / identity | **PASS** |
| exact unit（exact3） | **`84 passed`** |
| unit stdout SHA-256 | `7469e7240719c23130550c9e11685a5e6aa5d1f168f222d86f786f7b8bd2b5ec` |
| exact integration（exact3） | **`42 passed`** |
| integration stdout SHA-256 | `1cda2fd07a60527e058a1dc70976a610048cecb76262778b1ed816c586c0c721` |
| Ruff exact9 | **PASS** |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy production3 | **STOP**：`successor_downstream_stage.py` 21 errors |
| mypy stdout SHA-256 | `e539f47c4c410d203233ba56b11b2939ba68e1cb0a4224e17250c68f009b4268` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation10-20260826T080935Z/` |
| stage-summary SHA-256 | `c4986776930233c39ca9dee9d92b6efe43ca617d081c84a2ccfe583d4ee3c9d6` |
| cold / scope | **UNRUN** |

### 16.2 F11 — 七处 canonical 返回类型与 config float

| 项 | 内容 |
|---|---|
| 现象 | mypy 21 错：七个 stage/audit 调用结果为 `object` → 无 `receipt_path`/`receipt`/`report`/`decision` 等；`float(acceptance[...])` 对 `object` 报 `arg-type` |
| 根因 | `SuccessorPublicApiBundle` 将结果 callable 标成 `Callable[..., object]`；容差用裸 `float()`，与 config exact-float/finite 语义不一致 |
| 类型 SSOT | 仅收窄七字段：`formal_backtest_stage`→`FormalBacktestStageResult`；`formal_tracking_stage`→`FormalTrackingStageResult`；`reproducibility_stage`→`FormalReproducibilityResult`；`readiness_stage`/`readiness_verifier`→`VerifiedReadinessEvidenceArtifact`；`acceptance_stage`→`FormalAcceptanceStageResult`；`acceptance_audit`→`AcceptanceDecisionV1`。`TYPE_CHECKING` + quoted concrete types；无 `Any`/`cast`/`type:ignore`/wrapper/duplicate DTO |
| 最小复现 | VALIDATION10 mypy production3 → 21 错全在 `successor_downstream_stage.py`；`float(True)` / 非有限值可越过 |
| 测试 | `test_public_api_bundle_seven_stage_return_annotations_are_canonical`；`test_require_finite_config_float_accepts_exact_finite_rejects_invalid`；`test_formal_backtest_rejects_marker_wrapper_wrong_return_types` |
| 通过条件 | factory `is` 身份/字段序/运行校验/执行不变；非法 float 与错误返回稳定 `SUCCESSOR_GATE_FAILED`/`SUCCESSOR_STAGE_INVALID`；receipt/schema/Gate 顺序未改 |

### 16.3 本轮退出

`DELIVERY_READY`（VALIDATION10_F11_STATIC_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION11**（须含 mypy），不继承 VALIDATION10 部分绿或本轮静态改动为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit。

## 17. VALIDATION11 证据与 F12 局部名分离（taskbook §19）

### 17.1 VALIDATION11 有效证据（如实，未重跑）

| 项 | 结果 |
|---|---|
| identity | **PASS** |
| identity stdout SHA-256 | `e153b441b2ea26573f19f362ecfc7459cbebd3f62417d104936fd3cc195962a3` |
| exact unit | **`57 passed`** |
| unit stdout SHA-256 | `950b983df9bc36fc9520e19f5238edde01ddeae0cb49d41d027031cbf0cd252c` |
| exact integration | **`29 passed`** |
| integration stdout SHA-256 | `26493122892adaae25d16d33635b4c2ffae7bbf597cbb13840512f75b13b2059` |
| Ruff | **PASS** |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy production3 | **STOP**：`successor_downstream_stage.py:214` 1× `assignment` |
| mypy stdout SHA-256 | `4a4108d58e9a7ea26f6d987a91f5ad79b2cb023b04885fcda912936440475fa2` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` |
| stage-summary SHA-256 | `034cd671d26bac97ab1f4e0f6865a0ea3214add9c7f760b2eb63edeaac35ae64` |
| cold / scope | **UNRUN** |

### 17.2 F12 — backtest/tracking 结果局部名

| 项 | 内容 |
|---|---|
| 现象 | mypy：`result = formal_tracking_stage(...)` 与先前 `FormalBacktestStageResult` 赋值冲突 |
| 根因 | F11 收窄后，同一 `try` 共享局部名 `result` 跨不相容返回类型 |
| 修正 | `backtest_result` / `tracking_result`；调用/参数/顺序/`receipt_path`/`receipt`/分支/`SUCCESSOR_STAGE_INVALID` 归一不变；无 `cast`/`Any`/`type:ignore`/union/wrapper/API 变更 |
| 最小复现 | VALIDATION11 mypy → `:214 FormalTrackingStageResult` vs `FormalBacktestStageResult` |
| 通过条件 | 仅标识符分离；行为等价；本轮只改 `successor_downstream_stage.py` + taskbook + delivery |

### 17.3 本轮退出

`DELIVERY_READY`（VALIDATION11_F12_STATIC_ONLY_REWORK）。同一独立 reviewer 只读复验；PASS 后申请**完整 VALIDATION12**（须含 mypy），不继承部分绿或本轮静态改动为整包 PASS。本轮 STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit。

## 18. VALIDATION12 终态与组合证据（taskbook §20）

### 18.1 历史 STOP 保留（不得改写）

| 验证 | 结果（如实） |
|---|---|
| VALIDATION10 | unit **84 PASS**；integration **42 PASS**；Ruff **PASS**；mypy **21 STOP**；cold/scope **UNRUN**（触发 F11） |
| F11 → VALIDATION11 | identity **PASS**；unit **57 PASS**；integration **29 PASS**；Ruff **PASS**；mypy **1 局部名 assignment STOP**（`:214`）；cold/scope **UNRUN**（触发 F12） |
| VALIDATION11 证据根 | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` |
| unit stdout SHA-256 | `950b983df9bc36fc9520e19f5238edde01ddeae0cb49d41d027031cbf0cd252c` |
| integration stdout SHA-256 | `26493122892adaae25d16d33635b4c2ffae7bbf597cbb13840512f75b13b2059` |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy stdout SHA-256 | `4a4108d58e9a7ea26f6d987a91f5ad79b2cb023b04885fcda912936440475fa2` |
| stage-summary SHA-256 | `034cd671d26bac97ab1f4e0f6865a0ea3214add9c7f760b2eb63edeaac35ae64` |

### 18.2 VALIDATION12 PASS（F12 后；组合口径）

| 项 | 结果 |
|---|---|
| classification | **PASS**（`reused_validation11=unit57_integration29_other_ruff`） |
| identity | **PASS** |
| Ruff（changed source） | **PASS** |
| Ruff stdout SHA-256 | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy production3 | **PASS**（`Success: no issues found in 3 source files`） |
| mypy stdout SHA-256 | `f6af9a428ef63a271aa2234de6ce89a03776a74b2b986ece71bae5015648259c` |
| cold production3 | **PASS** |
| cold stdout SHA-256 | `30fe42e7ddd9409d2ac7944edf21099ba249f5380428435c8633658584029023` |
| exact12 / cached0 / diff / temp / process | **PASS**（`ACTUAL_COUNT=12`，`CACHED_COUNT=0`，`DIFF_CHECK=PASS`） |
| scope stdout SHA-256 | `1f4605b9d564203e5fb3cdf182ea60cbf3fbd86dc76d960919070c3b1408f13f` |
| evidence root | `artifacts/agent_runs/m3-r2w-rebuilt-validation12-20260826T180000Z-c18d/` |
| stage-summary SHA-256 | `2e0e2038cf3a90ad825f51a59ee8237e5ef057d9d277d5ccfeeb41d89fc06405` |

组合说明：VALIDATION12 复用 VALIDATION11 已绿的 unit57 / integration29（及其他 Ruff 口径），并在 F12 后对变更源重跑 identity、Ruff、mypy production3、cold production3 与 exact12 scope；**不**把 VALIDATION10 mypy21 STOP 或 VALIDATION11 局部名 STOP 改称为 PASS。

### 18.3 终态边界

- 终态：`R2W_WINDOWS_ENGINEERING_VALIDATED` / 可执行 package-owned successor downstream wiring。
- **明确不**表示：actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate。

### 18.4 本轮退出（证据更新 only）

`DELIVERY_READY`（EVIDENCE_UPDATE；仅 taskbook + delivery）。production / tests / review 只读；零 Python / check / stage / commit。
