# M3-G8F-R2P Orchestration Wave Compatibility 交付报告

状态：`DELIVERY_READY`（F1–F5 已闭合；VALIDATION2 focused + VALIDATION4 post-fix 全绿；evidence-only 文档闭环；**Windows 定向开发闭合**）<br>
task id：`M3-G8F-R2P-ORCHESTRATION-WAVE-COMPAT`<br>
exact base：`c124ec57e254672cd371ea04a732515a59c2fad1`<br>
worktree：`artifacts/dev_worktrees/m3-g8f-r2p-orchestration-wave-compat`<br>
终态上限：**不**表示 executable handler、bridge/CLI、actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate 完成。

## 0. 初验返工闭环（F1 / F2）

### F1 — wave cache 跨 request/resume 错误 identity

| 字段 | 内容 |
| --- | --- |
| 现象 | 同一 adapter 上后继 request/resume 可吃到前序 wave receipts；cache hit 直接 return |
| 根因 | `_wave_cache` 仅按 wave 名键控；未绑定 `two_fold_identity` / `project_root` / `resume` / 两 fold 消费集合 |
| 规则 | 任务书 §5：跨 fold 共享仅允许**同一** runtime request；resume 不得被无键 cache 吞掉；hit 必须对当前 context/request 重验闭包 |
| 最小复现 | 同 adapter：`run_fold(A,resume=True)` 后 `run_fold(B)` 或 `resume=False`；或同 fold 重复 / 第三 fold |
| 新增测试 | `test_wave_cache_rejects_cross_request_poison_and_resume_drift`；`test_wave_cache_rejects_duplicate_and_third_fold_consumption`；既有同 request 双 fold 单 builder 断言保留 |
| 通过条件 | adapter 绑定 `(two_fold_identity, project_root, resume, expected_folds)`；只允许两不同 fold 各消费一次；跨 request/resume 漂移 → `SUCCESSOR_INPUT_INVALID`；重复/第三 fold → `SUCCESSOR_STAGE_INVALID`；cache hit 对当前 request **重跑** `_validate_wave_receipt_closure` 并确认 refs 形状后才返回 |

### F2 — 六 builder legacy 逐字回归证据缺口

| 字段 | 内容 |
| --- | --- |
| 现象 | 初验时仅 provider 有 omitted≡`None` 断言 |
| 根因 | 其余五 builder 缺少对等 legacy 等价测试；不得依赖 Git base golden |
| 规则 | 任务书 §7.1；源码 `_verified_digest` legacy 分支保留即为静态证据 |
| 最小复现 | 同 fixture 下 omitted vs `artifact_roots=None` 的 `asdict`/`==` |
| 新增测试 | `test_remaining_five_builders_legacy_omitted_equals_explicit_none`（validation / experiment-artifacts / label-reconciliation / work / summary）；provider 既有 project-root 测保留 |
| 通过条件 | 六 builder 全部证明 omitted ≡ 显式 `None` 的 RunPlan dataclass/canonical identity 等价；无第二套 serialization/golden、不读 Git base |

未扩 handler / bridge / actual worker / 第二 work SSOT。独立初验报告只读未改。

### F3 — VALIDATION1：既有 monkeypatch stub 拒收 keyword-only `artifact_roots`

| 字段 | 内容 |
| --- | --- |
| 现象 | focused `tests/unit/test_m3_orchestration_plans.py`：**2 failed / 11 passed**；`test_work_scope_keys_only_use_verified_experiment_and_work_identity` 与 `test_development_summary_uses_verifier_receipt_stage` 在 builder 传入 `artifact_roots=roots` 时 `TypeError: ... unexpected keyword argument 'artifact_roots'` |
| 根因 | 两测 monkeypatch 的 boundary stub 仍为 `lambda *_args: ...`，未显式接受 keyword-only `artifact_roots`；生产 builder 在 legacy `None` 路径亦始终以 keyword 转发 |
| 规则 | 任务书 §4：builder 可选 keyword-only `artifact_roots`；测试 stub 必须与生产调用面兼容，且不得改变原返回值、身份断言与 legacy 行为 |
| 最小复现 | evidence root `artifacts/agent_runs/m3-r2p-validation1-20260825T131357881Z`；`02-unit-orchestration-plans.stdout.log` SHA-256=`c5b16b91d6385df53f55bef486fe417d87af74048d86c55933435430819fa89c`；stage-summary：`01-identity exit=0`，`02-unit-orchestration-plans exit=1`，`STOP STAGE_FAILED` |
| 修复 / 测试 | 仅改上述两测：`_fold/_experiment/_label/_reconciliation_boundary_inputs` 与 `_experiment/_evaluation_boundary_inputs` stub 改为 `lambda *_args, artifact_roots=None: (_external(),)`；原返回值、scope/receipt 身份断言与 omit legacy 路径不变；production / 其他测试 / review 未改 |
| 通过条件 | 同两测在 builder `artifact_roots=None`（默认）调用下不再因 stub 签名 `TypeError`；原身份断言语义保持；本轮 STATIC_ONLY 未重跑 pytest |

## 0.1 VALIDATION1 证据绑定（经理授权 focused 运行；本轮未重跑）

- evidence root：`artifacts/agent_runs/m3-r2p-validation1-20260825T131357881Z`
- identity：`01-identity` exit=0
- focused unit：`02-unit-orchestration-plans` exit=1；stdout SHA-256=`c5b16b91d6385df53f55bef486fe417d87af74048d86c55933435430819fa89c`
- 失败摘要：上述两测 `TypeError`（unexpected keyword `artifact_roots`）；其余 11 passed
- 本轮 STATIC_ONLY：禁止 Python/pytest/Ruff/mypy/cold/提交；F3 仅为测试 stub 签名对齐，待后续授权复跑验证

### F4 — VALIDATION2：Ruff F841 未使用 `manifest` 赋值

| 字段 | 内容 |
| --- | --- |
| 现象 | focused 13+15+5+36 全绿后，Ruff exact 首失败 F841：`orchestration.py:2284` 局部 `manifest` 赋值未使用 |
| 根因 | `_release_label_inputs` 用 `manifest = next(...)` 仅保留「inputs 中必有与 `release.manifest_sha256` 匹配项」的 `StopIteration` 校验副作用，结果未再读取 |
| 规则 | 消除 F841；校验副作用必须显式保留；不得改 digest/wave/receipt 语义 |
| 最小复现 | evidence root `artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3`；`06-ruff` stdout SHA-256=`355b0a73f1069325fa56ef30c15effa373eba02bf3f137d0b92a4b07244720ec` |
| 修复 | 改为无赋值的显式 `next(...)`；后续 `entries`/bytes-drift 循环与返回排序不变 |
| 通过条件 | 同路径无 F841；manifest 匹配失败仍经 `next` 失败；digest/wave/receipt 行为不变；本轮 STATIC_ONLY 未重跑 Ruff/pytest |

## 0.2 VALIDATION2 证据绑定（经理授权 focused；本轮未重跑）

- evidence root：`artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3`
- focused：13+15+5+36 全绿；Ruff F841 首失败 STOP
- `06-ruff` stdout SHA-256=`355b0a73f1069325fa56ef30c15effa373eba02bf3f137d0b92a4b07244720ec`
- 本轮仅 exact10 内去掉未使用赋值并保留 `next` 校验；review 只读；未 Python/pytest/Ruff/mypy/cold/提交

### F5 — VALIDATION3：mypy 复用 `expected` / 二元 vs 三元 receipt key

| 字段 | 内容 |
| --- | --- |
| 现象 | mypy 四错：`_validate_wave_receipt_closure` 内不同语义 `expected`（experiment-artifacts / label-reconciliation 二元 vs work 三元）类型冲突 |
| 根因 | 同名局部变量跨分支承载不同 tuple 宽度；`observed` 推导亦未与 work 侧窄三元组统一 |
| 规则 | 不同语义用明确名称；expected/actual 共用窄三元组 `(stage: str, fold: str\|None, horizon: int\|None)`；禁 `type: ignore`/`Any`；不得改运行分支、比较语义、排序、错误码、identity、wave/receipt schema |
| 最小复现 | evidence root `artifacts/agent_runs/m3-r2p-postfix-validation3-20260825T151500Z-d42b`；mypy stdout SHA-256=`c348414b6fce19d607a2a9c518ba4a15bc528a40b9a13edeeeeee96a11615c93` |
| 修复 | 引入 `_WaveReceiptKey`；三波分别命名 `expected_*`/`actual_*` 集合并显式注解；共享 wave 的 fold=`None` 纳入三元键；保留既有 `fold is not None` fail-closed 分支 |
| 通过条件 | mypy 四错消除；fold None/str、horizon None/int、expected/actual 错位仍 fail-closed；本轮 STATIC_ONLY 未重跑 mypy/pytest |

## 0.3 VALIDATION3 证据绑定（经理授权；本轮未重跑）

- evidence root：`artifacts/agent_runs/m3-r2p-postfix-validation3-20260825T151500Z-d42b`
- mypy stdout SHA-256=`c348414b6fce19d607a2a9c518ba4a15bc528a40b9a13edeeeeee96a11615c93`
- 本轮仅 `successor_runtime.py` + task/delivery；review 只读；未 Python/Ruff/mypy/cold/提交

## 0.4 VALIDATION2 + VALIDATION4 组合证据（提交前 evidence-only；本会话未重跑）

### VALIDATION2 focused（pytest 绿，Ruff 曾首失败后已由 F4 修复）

- evidence root：`artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3`
- focused：`13 + 15 + 5 + 36` **PASS**（plans / waves / project-root / successor 定向）
- 当时 Ruff F841 首失败 → F4 已闭合；不以 VALIDATION2 Ruff 失败态宣称 lint 通过

### VALIDATION4 post-fix 全绿

- evidence root：`artifacts/agent_runs/m3-r2p-postfix-validation4-20260825T160000Z-f19a`
- identity / Ruff / mypy2 / cold / scope / diff / process：**全 PASS**
- 无 temp / cache / affinity `0xF00` 残留

关键 stdout SHA-256：

| 项 | SHA-256 |
| --- | --- |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `85b01af69016a727b65564a6669e32fa364c216cf51e3276cdd140e88a661138` |
| scope | `505d79fd5baea8c04dc1530a513bf778723e7e906b21923f09e2bdf4f465d0bd` |
| summary | `f43b88a6b1c033e4b165aa71657fc1606a39f1c4a32fa84429bc5d894b65f275` |
| runner | `3c147c5156a8822987918961069d5386d003edef666ab5b0848e4cf8b0bd801d` |

### 闭合边界（强制）

- **已闭合**：Windows 定向开发验证链（focused + identity/Ruff/mypy2/cold/scope/diff/process）与 F1–F5 返工文档。
- **未完成 / 不得宣称**：executable handler、bridge/CLI、actual worker、真实 Qlib、new root、retained、acceptance、Linux/M3 Gate。

本轮 **仅** 更新任务书与本交付；production / tests / review **未改**；未运行 Python/检查/提交。

## 1. exact10 写面

1. `src/quant/research/m3/orchestration.py`
2. `src/quant/research/m3/successor_runtime.py`
3. `tests/unit/test_m3_orchestration_plans.py`
4. `tests/unit/test_m3_orchestration_waves.py`（未改合同语义；本包对抗例主要落在 plans/project-root/successor）
5. `tests/integration/test_m3_orchestration_project_root.py`（新）
6. `tests/unit/test_m3_successor_runtime.py`
7. `tests/integration/test_m3_successor_runtime.py`
8. 任务书（本轮 F3 补 VALIDATION1 证据与返工合同）
9. 本交付报告
10. 初验报告（初验独占，只读）

未改 `__init__.py`、roadmap、共享 SSOT、handlers、experiment_identity 模块、R2/R2A dirty worktree、无关测试。未 commit。F3 测 stub；F4 `next` 校验；F5 `_WaveReceiptKey` 分波命名；任务书/交付已绑 VALIDATION1–3。

## 2. 六 builder：legacy / PROJECT 映射

对以下 builder 增加 **keyword-only 可选** `artifact_roots: Mapping[str, Path] | None = None`：

- `make_provider_materialization_run_plan`
- `make_provider_validation_run_plan`
- `make_experiment_artifact_run_plan`
- `make_label_reconciliation_run_plan`
- `make_work_run_plan`
- `make_summary_run_plan`

合同实现：

| 模式 | 行为 |
|---|---|
| `artifact_roots is None` | `_verified_digest` / boundary helpers 保持 legacy alias（`stage` / `g1-release` / `qlib-dump-tool`）、relative、size/SHA；`StageOutputInput.root_alias` 仍为 `stage`。省略参数与显式 `None` 路径一致。 |
| supplied | 先 `_validate_roots`（拒绝空/重复物理/嵌套）；每个 external input 经现有 `select_artifact_root` 选唯一 alias/root，再按所选 root **重算** relative/size/SHA；禁止只改 alias 字符串。 |
| successor | 约定传 `{"PROJECT": project_root}`；单 root 时 work 内 `StageOutputInput` alias 同步为该唯一 alias。 |

未修改 `experiment_identity.make_experiment_identity_run_plan` 的既有强制 `artifact_roots` 合同。未新增 `make_features_run_plan`，未复制第二套 work builder。

## 3. `select_run_plan_nodes`

纯选择/校验 API：

```text
select_run_plan_nodes(plan, *, expected_continuation, expected_node_ids) -> tuple[StageNode, ...]
```

- exact `RunPlan` 类型与 continuation；
- `expected_node_ids` 必须为 **tuple**、无重复，且与 plan 全量 node-id 闭包集合相等（禁止子集冒充完整 wave）；
- 输出按稳定 node id 排序；
- 无目录扫描、无发布、不改 plan、不执行 handler。

## 4. 真实 wave 顺序与 node→receipt 映射

`ProductionSuccessorStageAdapter` 唯一上游顺序改为：

1. snapshot
2. provider
3. provider-validation
4. experiment-identity
5. **experiment-artifacts**（labels+folds，一次 plan/一次 wave）
6. **label-reconciliation**（全部 horizons，一次 plan）
7. **work**（features + 全部 fold×horizon 至 backtest-plan，一次 plan；按 fold 过滤映射到 `FoldExecution`）
8. formal backtest/tracking（每 fold×horizon）
9. summary → reproducibility → readiness → acceptance（summary 仍为独立 Gate）

协议变更要点：

- `run_plan_builders` 键：`folds` → `experiment-artifacts`；禁止 `labels` / `features` / `folds` 伪 single-transition 键；
- `SuccessorProductionDependencies.run_upstream_stage` → `run_upstream_wave`，返回 `tuple[StageReceiptRef, ...]`；
- adapter **绑定**单一 canonical `two_fold_identity` + exact `project_root` + `resume`，并记录两 fold 消费；仅同 request 两不同 fold 共享 wave 一次；
- cache hit 必须对当前 `context.request` **重跑** receipt closure 并确认 refs 形状，不得裸 return；
- wave 闭包校验：experiment-artifacts 必须映射真实 labels×HORIZONS + folds；work 必须覆盖 request 两 fold 的 features 与 pre-formal work stages；再过滤到当前 fold 的 individual refs；
- 共享 physical ownership / cross-fold shared / global uniqueness 沿既有 runtime 合同；
- **本包无 placeholder handler、无 build/verifier 实现**。

## 5. 错误码 / 失败语义

- orchestration builders / `select_run_plan_nodes`：稳定 `ValueError` 文案（无绝对路径、无 payload/凭据、无底层 cause 泄漏）。
- successor：既有 `SuccessorRuntimeError` 码面；wave 闭包/伪键/非法 receipt 形状 → `SUCCESSOR_STAGE_INVALID`；依赖/public bundle 身份及 **跨 request/resume 绑定漂移** → `SUCCESSOR_INPUT_INVALID`；重复/第三 fold → `SUCCESSOR_STAGE_INVALID`。

## 6. 反例覆盖（实现者）

1. 六 builder `artifact_roots` keyword-only 且 default `None`；无 `make_features_run_plan`。
2. **六 builder** legacy omitted/`None` plan `asdict`/`==` 逐字等价（provider + 其余五）。
3. PROJECT remap：alias 全为 `PROJECT`，relative 相对 PROJECT 重算且文件可达；与 legacy relative 集合不等。
4. nested / duplicate physical roots、路径越界 fail closed。
5. `select_run_plan_nodes`：缺/多/重复/错误 continuation/非 tuple 输入；零目录副作用。
6. successor：experiment-artifacts / label-reconciliation / work 各调用一次；labels/folds 真实映射；features 按 fold 过滤。
7. 伪 builder 键 `labels` 进入 public bundle 构造拒绝。
8. summary 仍为独立 Gate；无 package-owned placeholder handler。
9. production dependency `run_upstream_wave` None fail closed。
10. work wave fold 过滤不把跨 fold features / shared labels 误收入本 fold。
11. **A/B poison**、**resume drift**、**重复/第三 fold** fail closed；同 request 双 fold 仍单 builder。

## 7. 验证边界与风险

本包 **Windows 定向开发验证** 已由 VALIDATION2 focused + VALIDATION4 post-fix 组合证据闭合（见 §0.4）。实现会话本轮未重跑任何检查。

风险 / 未完成：

- Windows `abspath` vs `resolve` 在极端 junction 场景下仍依赖既有 root 校验拒绝 symlink/reparse；
- **未实现 / 未验收**：executable handler、bridge/CLI、actual worker、真实 Qlib、new root、retained、acceptance、M3 Gate；
- production bridge/worker 尚未实现真实 `run_upstream_wave`；本包只冻结 protocol 与映射；
- 正式路径 work plan 不含 backtest/tracking（仍由 formal stages 承担），与既有 formal builder 边界一致。

## 8. STOP 条件

F1–F5 与 VALIDATION1–4 文档/证据已闭环；**未 STOP**。提交前 evidence-only 完成。仍不得把本包表述为 handler/bridge/CLI/actual worker/真实 Qlib/new root/retained/Gate 完成。
