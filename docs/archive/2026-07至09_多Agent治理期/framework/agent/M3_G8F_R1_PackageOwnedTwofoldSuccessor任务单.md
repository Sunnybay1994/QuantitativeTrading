# M3 G8F R1：Package-owned Two-fold Successor Runtime 与 Durable Terminal 任务单

日期：2026-08-23
状态：VALIDATION_PASS；Windows 开发检查已闭合，source commit / integration 待主 Agent 收口
exact base：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`
branch：`codex/m3-g8f-successor-runtime`
worktree：`artifacts/dev_worktrees/m3-g8f-successor-runtime`

## 1. 目标

新增最小 package-owned M3 two-fold successor runtime 和 durable terminal attestation，使后续全新 Windows root 能以受跟踪生产代码完成 two-fold × h5/h10 的阶段编排，并在所有节点 fresh verify 为 PASS 后发布可重验终态。

本包只实现生产 runtime/terminal 与确定性 fixture，不启动 actual worker，不生成真实 M3 successor，不改变旧 retained 现场。

## 2. 唯一写白名单

1. `src/quant/research/m3/successor_runtime.py`（新）
2. `tests/unit/test_m3_successor_runtime.py`（新）
3. `tests/integration/test_m3_successor_runtime.py`（新）
4. `docs/framework/agent/M3_G8F_R1_PackageOwnedTwofoldSuccessor任务单.md`（本文件）
5. `docs/framework/agent/M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md`（新）

禁止修改 `__init__.py`、配置、roadmap、共享 SSOT、既有阶段模块与测试。若现有 API 无法在此白名单内正确组合，立即 STOP 并给出所需最小扩围，不得复制第二套阶段实现。

## 3. 冻结合同

### 3.1 输入与根边界

- 调用方必须显式提供两份 versioned config、对应 G1 verified release、一个全新 successor project root 和统一 UTC `now`；禁止目录扫描、latest、alias 或自动发现。
- 两个 fold 必须是不同的 config identity，并共同形成唯一 two-fold identity；horizon 精确为 5、10。
- successor root、各专业 stage root 与 project root 的映射必须复用当前 `StageRunner`/root-topology 合同：`StageRunner` 只接收 PROJECT root，resolver/worker 继续使用既有专业 roots。
- 不读取、继承、resume 或复制 detached `c9f2f36` retained root、两份 untracked session config、旧 helper、receipt 或 completion。旧现场只作为冻结历史证据存在。

### 3.2 编排

- 只组合现有生产 stage API 与 verifier；禁止重写 feature/model/prediction/backtest/summary/reproducibility/readiness/acceptance 逻辑。
- 顺序必须覆盖 two-fold × h5/h10 的所需上游节点，再依次形成 summary、reproducibility、readiness 与 acceptance。
- `resume=True` 只能复用同 exact identity 且 fresh verifier 通过的节点；任何 identity、bytes、receipt、root 或依赖漂移必须在下游写入前 fail closed。
- 任一 fold、任一 horizon 或任一终态 Gate 缺失/非 PASS 时，不得创建 terminal attestation。

### 3.3 durable terminal attestation

- canonical JSON、no-clobber、稳定 schema/error；发布采用同目录唯一临时项加原子提交，成功和失败终态临时项均清零。
- 至少绑定：两份 config 原始 bytes SHA256、code version、dependency fingerprint、provider runtime fingerprint、两个 G1 release/snapshot/work identity、所有必需 stage receipt identity、two-fold/horizon 集合、acceptance/readiness/reproducibility identity、terminal status、完整受控输出树 digest。
- verifier 必须重新读取 canonical bytes、重新验证引用 receipt/节点和树摘要；仅 `PASS` 可返回 verified terminal value object。
- `completion.json` 文件名本身、caller 注入状态、路径存在或 receipt-only 均不能证明成功。

## 4. 必须覆盖的反例

1. development/fixture 伪造 completion，但第二 fold 或 h10 缺失：terminal 发布前拒绝。
2. summary 后任一 receipt bytes、config bytes 或 tree entry 漂移：fresh verify 拒绝。
3. root 实际拓扑中专业 root 嵌套于 PROJECT root：合法；把专业 root 误传给 `StageRunner`：拒绝。
4. Windows exact current Conda `sys.executable` 的合法多 hardlink：正向实际 PASS、不可 skip；非当前解释器、额外路径、symlink/reparse 仍拒绝。
5. resume 指向旧 FAILED retained 或不同 identity 的已完成节点：拒绝且旧现场零写。
6. terminal 同 identity 同 bytes 重放可验证；同 identity 不同 bytes、未知文件或残留临时项：fail closed。

## 5. 实现与验证方式

- 实现由本地 Luna Worker 的独立 subagent 完成；顶层 Worker 只编排和汇总。
- 当前先允许静态实现；CPU 检查必须等待根 Agent 分配窗口。
- 获得 CPU 槽后的顺序：focused unit → focused integration → Ruff（白名单 Python）→ mypy（唯一生产模块）→ cold import → scoped diff/临时项/进程残留检查。
- Windows：BelowNormal、affinity `0xF00`、threads ≤ 2、唯一实例。不得运行 actual M3 worker、retained resume、全链真实 acceptance 或 Linux Gate。

## 6. 通过与停止条件

通过：exact 五路径、全部定向检查通过、无真实 artifact、worktree clean 安全提交、交付报告列出 API、schema、反例和命令证据。

立即停止：需要扩大白名单；需要改 receipt/schema/identity SSOT；发现现有 stage API 无法无复制组合；任何旧 retained 写入；base/HEAD 漂移；资源槽未授权。

## 7. REWORK1 问题闭环（F1-F4）

本节是对独立初验返工项的最小闭环记录；不改变 terminal receipt/schema/identity SSOT，仍只允许本任务单第 2 节的 exact5。

### F1：受控树的目录闭包

- 现象：原实现只比较受控树中的文件集合；新增一个未知的空目录不会改变 `expected_files`，因此可能被纳入 terminal tree digest。
- 根因：目录项未与 receipt/output 的项目相对父目录集合及 StageRunner 明确允许的运行时目录做闭包校验。
- 应遵循规则：受控输出树只能包含 receipt/output 所需父目录和既有 StageRunner 运行时目录；未知空目录、未知文件、临时项、symlink/reparse 统一 fail closed。
- 最小复现：成功生成 terminal 后在 controlled output root 下创建 `unknown-empty/`，再执行 fresh terminal verify。
- 新增测试：`test_terminal_rejects_unknown_empty_directory`。
- 通过条件：fresh verify 返回 `SUCCESSOR_TERMINAL_INVALID`，不接受未知空目录。

### F2：真实 StageRunner 与 PROJECT-only 拓扑

- 现象：原实现的 integration fixture 使用手写 `_DeterministicStageRunner`，且生产依赖可注入任意 `stage_runner_factory`，无法证明生产 factory 返回真实 StageRunner 或阻断 callback bypass。
- 根因：runner factory 仅有可调用性检查，未绑定既有 `make_project_stage_runner`、真实 `StageRunner` 类型和 `{"PROJECT": project_root}` 的 root registry。
- 应遵循规则：生产 adapter 只能通过既有 `make_project_stage_runner` 构造真实 `StageRunner`；StageRunner 只能看到 PROJECT root，专业 stage root 必须位于 PROJECT 内；任意替代 callback 在写入前拒绝。
- 最小复现：把 `stage_runner_factory` 替换为返回任意对象的 callback，再构造 production adapter。
- 新增测试：`test_production_factory_rejects_arbitrary_stage_runner_bypass`；integration boundary 改为传递真实 StageRunner 类型与既有 public API bundle。
- 通过条件：构造阶段返回 `SUCCESSOR_INPUT_INVALID`，无 receipt/artifact/terminal 写入；正常 fixture 只在真实 StageRunner 边界上注入确定性 stage/gate substitutes。

### F3：scope_key 与 execution/work 完整 join

- 现象：原实现 `_lookup_refs` 忽略 `executions`/`known`，且 fold 校验没有把 snapshot receipt 的 scope_key 显式绑定到 `snapshot_id`。
- 根因：receipt 引用闭包只依赖 gate 自带 refs，execution/work identity 与 snapshot/experiment/work receipt scope_key 的连接没有形成显式校验。
- 应遵循规则：snapshot receipt 必须绑定 `FoldExecution.snapshot_id`；experiment/features/labels 与 `experiment_key` 对齐；每个 h5/h10 work receipt 必须等于 `compute_work_key(experiment_key, fold, horizon)`；gate refs 必须与已有 fold/prior-gate ownership 不重叠，并按 gate scope contract 校验。
- 最小复现：让一个 h5/h10 work receipt 使用不属于 execution 的 scope_key，或让 gate 重用 fold/prior-gate receipt node。
- 新增测试：`test_scope_key_drift_cannot_join_work_to_execution`、`test_lookup_refs_consumes_fold_and_prior_gate_ownership`。
- 通过条件：在 terminal 前返回稳定 `SUCCESSOR_STAGE_INVALID`/`SUCCESSOR_GATE_FAILED`，不接受不完整 identity join 或重复 ownership。

### F4：fresh verifier 的 attestation context

- 现象：原实现 terminal fresh gate verifier 只收到 gate 和空 folds/prior-gates，无法基于 attestation 重建上下文验证跨 fold 与前序 Gate 依赖。
- 根因：`verify_gate` contract 未携带 reconstructed fold/prior-gate context；terminal verifier 重放时也未按 Gate 顺序传入前序 gates。
- 应遵循规则：fresh gate verifier 必须接收从 canonical attestation 重建的完整两 fold executions，以及按 summary → reproducibility → readiness → acceptance 顺序累积的 prior gates。
- 最小复现：使用一个拒绝空 folds 或错误 prior-gate 顺序的 gate verifier 执行 terminal fresh verify。
- 新增测试：`test_fresh_gate_verifier_requires_reconstructed_fold_and_prior_context`。
- 通过条件：初次验证与 terminal replay 都收到 `(fold_001, fold_002)` 及正确的 prior-gate 前缀；缺 context 时 fail closed。

REWORK1 仍为 STATIC_ONLY：本轮未运行 pytest、Ruff、mypy、cold import、CPU、actual worker、真实 acceptance、Linux、network；未提交、未 stage，独立初验报告保持只读。

## 8. REWORK2 问题闭环（F2-F3）

本节追加 REVIEW-REWORK2 的最小修复记录，不改写 REWORK1 历史，不改变 terminal schema/receipt SSOT，仍只允许 exact5。

### F2：production public API binding

- 现象：REWORK1 已锁定真实 `StageRunner`，但 production adapter 仍可接受 caller-supplied marker `SuccessorPublicApiBundle`；只要 `stage_runner_type` 正确，任意 builder/verifier callback 即可绕过既有 public M3 API。
- 根因：production entry 直接采用传入 bundle，没有内部 canonical binding 或逐项 callable identity 校验。
- 应遵循规则：production entry 必须内部调用 `make_public_successor_api_bundle()`；若保留可选 bundle，只能逐项校验 StageRunner type、run-plan builder、formal stage、summary/reproducibility/readiness/acceptance builder/verifier 的 exact identity。测试 substitutes 只能在测试侧替换 canonical binding，不得作为任意 production bundle 进入。
- 最小复现：构造真实 StageRunner type 加 marker builders/verifiers 的 bundle，传入 production factory，并让窄 callbacks 忽略 public API。
- 新增测试：`test_production_factory_rejects_marker_public_api_bundle`；正常 integration fixture 不再把 marker bundle 作为 production 参数传入，而由测试侧隔离替换 canonical binding。
- 通过条件：marker/caller bundle 在 receipt、artifact、terminal 写入前返回 `SUCCESSOR_INPUT_INVALID`；生产入口内部持有 canonical bundle。

### F3：Gate scope join 与全局 receipt ownership

- 现象：REWORK1 已修复 fold snapshot/experiment/work join 和 node-id ownership，但 reproducibility scope_key 仍可任意唯一；summary/reproducibility/readiness/acceptance 未全部由 execution/work identity 可重算；不同 node_id 可复用同一物理 receipt path/bytes。
- 根因：Gate 校验只验证形状、stage/scope 与局部唯一性；全局 ownership 仍以 node_id 为主。
- 应遵循规则：summary scope_key 必须 join shared experiment；reproducibility scope_key 必须由对应 h5/h10 `WorkIdentity` 可重算；readiness scope_key 必须由 fold execution join 与 prior-gate identities 可重算；acceptance scope_key 必须与 deterministic acceptance gate identity join。全局按 canonical physical receipt path、receipt bytes SHA256、semantic owner `(stage, scope, scope_key, fold, horizon)` 和 node_id 检查 alias；仅允许同一 exact shared node 在两个 fold 的窄 shared-stage allowlist 中复用。
- 最小复现：让四个 reproducibility refs 使用正确 fold/horizon 但任意唯一 64-hex scope_key；或让两个不同 node_id 使用同一 receipt path/bytes。
- 新增测试：`test_reproducibility_scope_key_drift_cannot_join_work`、`test_distinct_node_same_receipt_path_and_bytes_is_rejected`、`test_unique_refs_rejects_distinct_node_physical_and_semantic_alias`。
- 通过条件：Gate scope drift 返回 `SUCCESSOR_GATE_FAILED`；物理/bytes/semantic alias 返回 `SUCCESSOR_TERMINAL_INVALID`，合法 shared cross-fold node 仅按显式 allowlist 保留。

REWORK2 仍为 STATIC_ONLY：未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU、actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage，独立初验报告保持只读。

## 9. REWORK3 问题闭环（Path 类型守卫）

本节只记录 REVIEW/执行反馈中定位到的 `_runner` 类型守卫问题；不改变 receipt、Gate、terminal schema/identity 合同，仍只允许 exact5。

### Path concrete subclass acceptance

- 现象：identity preflight PASS；focused unit 为 7 passed；focused integration 为 4 passed、8 failed，8 个失败全部在 `successor_runtime.py::_runner` 最终 guard 返回 `SUCCESSOR_INPUT_INVALID`。
- 根因：`StageRunner` 将实际路径保存为平台具体的 `pathlib.WindowsPath`/`pathlib.PosixPath`，原守卫使用 `type(actual_stage_root) is not Path`，把合法 `Path` concrete subclass 误拒绝。
- 应遵循规则：接受 `isinstance(actual_stage_root, Path)` 的平台具体 `Path` 子类，但继续要求 `_artifact_roots == {"PROJECT": context.project_root}` 且 `actual_stage_root == stage_root`；非 Path 与 root mismatch 必须 fail closed。
- 最小复现：真实 StageRunner 返回 `WindowsPath`/`PosixPath`；或将 `_stage_root` 替换为 `str(stage_root)`、`stage_root / "unexpected"` 后调用 adapter `_runner`。
- 新增测试：integration `test_runner_accepts_concrete_path_subclass_and_rejects_invalid_root`，分别断言 concrete subclass 接受、非 Path 拒绝、root mismatch 拒绝。
- 通过条件：真实 platform concrete Path subclass 不再触发 `SUCCESSOR_INPUT_INVALID`；非 Path/root mismatch 仍返回该错误，且不放宽 PROJECT-only root equality。

### REWORK3 validation STOP evidence

- 已有可执行反馈证据精确为：identity preflight PASS；focused unit `7 passed`；focused integration `4 passed / 8 failed`；8 failures 均为上述 `_runner` final guard 类型误拒绝。
- 本 STATIC_ONLY 修复 turn 不重跑任何 Python、pytest、Ruff、mypy、cold import 或 CPU 检查；修复后的结果保持未验证，不能宣称 Gate 通过。
- 未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 10. REWORK5 DIAGNOSTIC2 闭环（fixture-only）

本轮只修正 integration fixture 的 canonical builder 路由；生产 runtime、异常包装、receipt/gate/schema/identity 合同均未修改。REWORK4 的 STOP 历史保留，DIAGNOSTIC1/2 作为定位证据记录如下。

### labels builder route

- 现象：DIAGNOSTIC1 给出 identity preflight PASS、focused unit `7 passed`、focused integration `5 passed / 8 failed`；Path guard 已通过，但 fold boundary 仍以 `SUCCESSOR_STAGE_FAILED` 表面化。DIAGNOSTIC2 捕获到 `KeyError('labels')`，发生在 integration fixture `run_upstream_stage` line 282，并沿 adapter `run_fold` line 1037 传播。
- 根因：fixture `_builder_name("labels")` 原样回退为 `"labels"`，随后执行 `public_apis.run_plan_builders["labels"]`。canonical `make_public_successor_api_bundle()` 的 `run_plan_builders` 明确以 `"folds": make_experiment_artifact_run_plan` 提供该波次 builder，并没有 `"labels"`；`"label-reconciliation"` 是独立的 canonical builder，不能合并或改名。
- 应遵循规则：`labels` 必须显式映射到 canonical `folds` builder；`label-reconciliation` 必须继续映射自身；fixture 不得凭 stage 名称发明不存在的 production bundle key；不改变 production exception wrapping 或添加 broad catch。
- 最小复现：在 `_DeterministicProductionBoundary` 上调用 `_builder_name("labels")`，旧逻辑返回 `"labels"`，再索引只含 `folds` 的 `run_plan_builders` 即得到 `KeyError('labels')`。修复后返回 `"folds"`，同一 canonical mapping 可解析；`_builder_name("label-reconciliation")` 仍返回自身。
- 新增测试：integration `test_labels_routes_to_canonical_folds_builder_not_labels`，断言 `labels` 精确路由为 `folds`、`labels` 不在 canonical mapping、解析出的 callable 是 `folds` 项，且 `label-reconciliation` 保持独立 key。
- 通过条件：labels 波次不再查找不存在的 `labels` builder，实际 lookup 使用 `make_experiment_artifact_run_plan` 对应的 `folds` 项；label-reconciliation 路由不漂移；无生产代码/错误包装扩展。

REWORK5 仍为 STATIC_ONLY：DIAGNOSTIC1/2 是外部提供的反馈证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 11. REWORK6 fixture callable lookup 闭环

本轮只补强 integration fixture/test 的可观察 lookup 证据；`successor_runtime.py`、生产异常包装、receipt/gate/schema/identity 合同均保持不变。独立初验 §13–14 指出的 REWORK5 缺口记录如下。

### folds 与 label-reconciliation 的独立 callable

- 现象：REWORK5 的 `test_labels_routes_to_canonical_folds_builder_not_labels` 只断言 `_builder_name("labels") == "folds"`、`"labels"` 不在 mapping，并将 `run_plan_builders["folds"]` 与自身比较；fixture 的所有 run-plan key 还共用一个 `marker`。因此测试没有进入 `run_upstream_stage` lookup，也不能证明 labels 实际调用了 folds callable，或 label-reconciliation 保持独立。
- 根因：测试替代 bundle 未提供可区分的 folds/label-reconciliation 行为观测；mapping 自比较和 shared marker 无法区分错误 key 路由、callable 误复用或实际 callback 未被调用。
- 应遵循规则：生产 route 仍为 `labels -> canonical folds`，`label-reconciliation -> canonical label-reconciliation`；fixture 必须使用独立 callable/sentinel 和阶段调用记录；回归必须经 concrete adapter 的 `run_fold`/依赖 `run_upstream_stage` lookup，禁止只验证字符串或 fixture mapping。
- 最小复现：旧测试即使把 `label-reconciliation` 错接到 folds，或让两个 key 共用 marker，也可能通过 `folds` 项自比较。新路径构造 concrete adapter，执行一个 fold；labels 若查找不存在的 key 会在 `run_upstream_stage` 失败，若误取 label-reconciliation 则调用记录不是 `("folds", "labels")`，若 label-reconciliation 误取 folds 则其记录不是 `("label-reconciliation", "label-reconciliation")`。
- 新增/强化测试：integration `test_labels_routes_to_canonical_folds_builder_not_labels` 现在使用独立 `folds_builder`、`label_reconciliation_builder`、不同 sentinel 与 `builder_call_records`，通过 `_adapter(boundary).run_fold(...)` 到达实际 callback lookup；断言 `"labels"` 缺失、两个 callable 不同、labels 只记录 `("folds", "labels")`，label-reconciliation 只记录自身 builder/stage。
- 通过条件：不改 production runtime；labels key 永不被索引，labels 只调用 canonical folds callable；label-reconciliation 只调用自己的独立 callable；任何错接或 shared marker 均被回归断言拒绝。

REWORK6 仍为 STATIC_ONLY：本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 12. REWORK7 VALIDATION3 horizon sentinel 闭环

本轮只修正 integration fixture 的 horizon 缺省值判断，并增加窄对抗测试；`successor_runtime.py`、unit test、生产异常包装、receipt/gate/schema/identity 合同均保持不变。

### `_effective_horizon` 的 None 语义

- 现象：VALIDATION3 已提供 identity PASS、unit `7 passed`、integration `7 passed / 7 failed`；共同首失败发生在 snapshot 的 `horizon=None` 被 fixture `_effective_horizon` 改为 h5，随后 `ProductionSuccessorStageAdapter.run_fold` 的 `_one_ref(refs, stage="snapshot", horizon=None)` 返回 `SUCCESSOR_STAGE_INVALID`。
- 根因：旧条件只有 `horizon == self.omit_horizon`。fixture 默认 `omit_horizon=None` 时，snapshot 的合法 `horizon=None` 与默认配置相等，误触发 `runtime.HORIZONS[0]` 替换。
- 应遵循规则：只有 caller 明确设置了非 `None` 的 `omit_horizon`，且当前 horizon 精确命中该值，才执行既有缺失 horizon 替换；默认 `omit_horizon=None` 必须保留 `horizon=None`，不得改变生产错误包装或其他 fixture 逻辑。
- 最小复现：旧默认 boundary 上调用 `_effective_horizon(None)` 得到 h5；显式 `omit_horizon=10` 上调用 `_effective_horizon(10)` 仍应得到 `runtime.HORIZONS[0]`。新断言同时覆盖默认 `None` 保持 `None`、显式 10 的原有替换和显式 omit 下输入 `None` 不替换。
- 新增测试：integration `test_effective_horizon_requires_explicit_omit_setting`。
- 通过条件：默认 snapshot/任何未指定 horizon 的 stage 保持 `None`；显式 omit horizon 仍按原 fixture 语义替换为首个 horizon；VALIDATION3 的 snapshot `_one_ref` 不再因默认值误改而 fail closed；生产代码和错误包装不变。

REWORK7 仍为 STATIC_ONLY：VALIDATION3 的 identity/unit/integration 结果是外部提供证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 13. REWORK8 VALIDATION4 shared receipt ownership 闭环

本轮只修正 `_lookup_refs` 的窄 ownership 例外并补充 unit/integration 对抗覆盖；不复制第二套规则，不改变 receipt/gate/schema/identity 合同之外的语义。

### fold 间 exact shared receipt

- 现象：VALIDATION4 identity PASS、unit `7 passed`、integration `10 passed / 5 failed`；五个失败统一发生在 summary Gate 的 `_lookup_refs`，合法跨 fold shared receipt 也被 `SUCCESSOR_GATE_FAILED` 拒绝。
- 根因：原 `_lookup_refs` 只保存 `node_id -> "fold"/"gate"`，看到第二个相同 node_id 即拒绝，未保存完整 `StageReceiptRef` 和 owner tuple，也未调用既有 `_shared_receipt_duplicate_allowed` 窄判定。
- 应遵循规则：`owned` 必须保存 `node_id -> (StageReceiptRef, owner tuple)`；fold 间重复只有在 ref 完全相等且 `_shared_receipt_duplicate_allowed(ref, first_owner, second_owner)` 为 true 时允许。不同 ref（包含 bytes/path/semantic identity 任一漂移）、非 shared stage、同 fold、fold↔gate、prior gate↔current gate、gate↔gate 任何复用均 fail closed。
- 最小复现：两份 FoldExecution 使用同一 `experiment-identity`、`fold=None` 的 exact ref，并提交 summary Gate；旧实现仅因 node_id 重复返回 `SUCCESSOR_GATE_FAILED`。将该 ref 改动 sha/path/semantic 字段，或把 owner 改为同 fold、gate、非 shared stage，均不得进入例外。
- 新增/强化测试：unit `test_lookup_refs_allows_exact_shared_receipt_between_two_folds` 覆盖合法 exact shared 入 Gate；unit 覆盖 `test_lookup_refs_rejects_same_node_with_different_ref`、`test_lookup_refs_rejects_nonshared_stage_reuse_between_folds`、`test_lookup_refs_rejects_same_fold_reuse`、`test_lookup_refs_rejects_fold_gate_reuse`、`test_lookup_refs_rejects_prior_gate_current_gate_reuse`、`test_lookup_refs_rejects_gate_gate_reuse`；integration 强化 `test_two_fold_terminal_is_durable_and_replayable`，断言 two-fold summary Gate context 实际到达。
- 通过条件：合法两 fold exact shared receipt 可完成 summary Gate lookup；所有非窄 allowlist 重复稳定返回 `SUCCESSOR_GATE_FAILED`；既有 global physical path/bytes/semantic ownership 约束继续生效；不引入第二套 shared 判定。

REWORK8 仍为 STATIC_ONLY：VALIDATION4 的 identity/unit/integration 结果是外部提供的 STOP 证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 14. REWORK9 DIAGNOSTIC5 regular-file link-count 闭环

本轮只按中央 REWORK9 裁定收窄 regular-file link-count 平台规则；不改变 symlink/reparse 独立守卫、controlled-tree identity、receipt/Gate/schema/identity 合同，也不做顺手重构。

### 现象、根因与平台规则

- 现象：DIAGNOSTIC5 的 wrapper/stdout 证据定位到 regular-file link-count guard；Windows regular file 的 `st_nlink=0` 被硬编码的 `st_nlink != 1` 拒绝。该证据以 trace SHA `f0dbca2bd2b222f23fe165d6dee2c5ee45de388321c271d92524492a0a79a81f` 标识；原始 carrier 不复制到 exact5。
- 根因：`_walk_controlled_tree` 与 `_read_regular_file` 共享的旧判断无平台分支，要求所有 regular file 的 link count 恰为 1；这与 Windows `stat` 反馈的合法 0/1 形态不相容。
- 应遵循的平台规则：Windows regular file 仅接受 `st_nlink in {0, 1}`；非 Windows regular file 仅接受 `st_nlink == 1`；任意平台 `st_nlink > 1` 必须拒绝。symlink/reparse 判断继续在 link-count 判断之前独立 fail closed，不能因平台放宽而接受。

### 最小复现、新测试与通过条件

- 最小复现：向 controlled-tree regular entry 注入 `st_mode=S_IFREG`，分别给出 Windows 的 `st_nlink=0/1/2` 与非 Windows 的 `0/1/2`；另以 `S_IFLNK` 或 reparse attribute 配合 `st_nlink=0`，确认 link-count 例外不会绕过 symlink/reparse guard。
- 新增测试：unit `test_platform_regular_file_link_count_and_link_guards` 使用独立 fake `DirEntry.stat(follow_symlinks=False)` 进入 `_walk_controlled_tree`；断言 Windows regular `0`、`1` 正向，`>1` 拒绝；非 Windows `0` 拒绝、`1` 正向、`>1` 拒绝；symlink 与 reparse 仍拒绝。生产 `_read_regular_file` 与 tree walk 均调用同一窄 predicate，避免第二套规则。
- 通过条件：上述四类平台/guard 反例均满足精确接受或拒绝规则，且不改变真实路径 equality、PROJECT-only root、receipt/Gate/terminal schema/identity 或错误包装。

### REWORK9 验证边界

DIAGNOSTIC5 的 identity/wrapper/stdout 反馈为外部提供证据；本轮仅静态编辑，未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python，因此不能宣称 Gate/真实 acceptance 通过。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。controlled-tree identity 未改变。

## 15. REWORK10 VALIDATION7 attestation-bound receipt tamper 闭环

本轮只修改 integration test 与本任务书/交付报告；生产 `successor_runtime.py`、unit test、receipt/tamper/fail-closed 实现合同均冻结不动。

### 现象、根因与规则

- 现象：VALIDATION7 外部反馈为 unit `15 passed`、focused integration `14 passed / 1 STOP`，stdout trace SHA 为 `a6977c70b7c00f1471d848d1af348ac6d76db4345800ff51df6c147e36296b58`。唯一失败落在 receipt-bytes tamper 反例的测试定位段：测试没有使用首轮结果的 canonical attestation receipt，而是硬编码替代文件名。
- 根因：旧 integration 测试先调用 `_run(request, boundary)` 丢弃 `SuccessorRunResult`，随后自构造 `controlled_output_root/receipts/snapshot/shared-snapshot.json`。该名字不由当前 `first.attestation.receipts` 提供，因而不能证明篡改的是已认证 receipt，也可能在真实 receipt 之外失败或误指向。
- 应遵循规则：必须保留 `first = _run(...)`；从 `first.attestation.receipts` 筛选 `stage == "snapshot"` 且 `fold is None`、`horizon is None`，强制恰有一项并校验其 scope/scope_key/relative path shape；再用 `request.project_root / ref.relative_path` 定位实际文件，校验原始 bytes 的 ref sha 后实施既有 tamper。禁止硬编码替代文件名、自构造 receipt 路径或弱化 `SUCCESSOR_TERMINAL_INVALID` fail-closed 断言。

### 最小复现、新测试与通过条件

- 最小复现：首轮 `_run` 已返回 canonical attestation，但旧测试丢弃 `first`，直接拼接 `shared-snapshot.json`；当 attestation 的 snapshot ref 不是该名字时，tamper 不再绑定已认证 receipt。
- 新测试：integration `test_terminal_rejects_receipt_bytes_and_unknown_tree_entry` 使用 `first.attestation.receipts` 的唯一 snapshot/fold-none/horizon-none ref，断言 `SNAPSHOT` scope、`boundary.snapshot_id` scope_key、`output/stage/receipts/snapshot/*.json` shape 和原始 sha，再通过 `request.project_root / snapshot_ref.relative_path` 写入 bytes drift；随后仍断言 `verify_terminal_attestation` 返回 `SUCCESSOR_TERMINAL_INVALID`。unknown-tree 分支保持原有独立覆盖。
- 通过条件：篡改目标必为当前 attestation 的唯一 canonical snapshot receipt；合法原始 receipt 可被定位，任意 bytes drift 仍 fail closed 为 `SUCCESSOR_TERMINAL_INVALID`，且不引入硬编码文件名或第二套 receipt 解析规则。

### REWORK10 验证边界

VALIDATION7 的 unit/integration 结果与 stdout SHA 是外部提供证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 integration 结果待后续授权验证，不能将本轮静态交付表述为 Gate 通过。

## 16. REWORK11 VALIDATION8 dependency typing 与 canonical bytes 闭环

本轮只修正生产模块的静态 typing 表达，并补 unit 对抗测试；不改变 runtime 行为、字段顺序、receipt/terminal schema、canonical bytes 排序或编码规则。integration test 与独立初验报告保持只读。

### 现象、根因与类型规则

- 现象：VALIDATION8 外部证据为 focused unit `15 passed`、focused integration `15 passed`、Ruff exact3 PASS；mypy 首次执行 STOP，stdout SHA 为 `ee7073f019c91a27530390b3f6da8e52a44733c7f93e62d9515b6fd0c5bfbf5b`。报告归因 13 个类型错误：必需 dependency callback 被注解为 Optional、局部 `expected`/`digest` 重名及 `asdict(object)` 未形成安全的 dataclass typing 收窄。
- 根因：`SuccessorProductionDependencies` 的 13 个必需 callable 字段虽然由 `__post_init__`/adapter 做 runtime fail-closed 检查，却在静态类型层保留 `| None`；同一函数的不同语义局部变量名又触发 mypy 重定义/类型冲突；`hasattr` 分支没有让 `asdict` overload 得到 dataclass 类型。
- 应遵循的类型规则：13 个字段使用原有 Callable Protocol 类型、去除 Optional，字段顺序不变；`__post_init__` 与 adapter 的全部 callable/StageRunner identity 检查、None 拒绝与构造行为保留。`expected` 只等价改名为 `expected_work_key`/`expected_receipts`，tree entry 的 `digest` 只等价改名为 `entry_digest`。canonical bytes 只允许最窄桥接 `asdict(cast(Any, value))`，不得 `type: ignore`，且必须保持 `sort_keys`、紧凑 separators、ASCII、`allow_nan=False` 和 schema/bytes 完全不变。

### 最小复现、新测试与通过条件

- 最小复现：对 `SuccessorProductionDependencies` 任一必需字段传 `None`，构造仍必须返回 `SUCCESSOR_INPUT_INVALID`；对同一 `_validate_fold_execution` 同时使用 work-key expected 与 receipt-shape expected，或在 controlled-tree digest 语义中复用 `digest`，会触发静态重定义；对 dataclass 值调用 `_canonical_bytes` 时，直接 `asdict(value)` 无法满足静态 overload。
- 保留/新增测试：保留 `test_production_dependencies_fail_closed_when_any_boundary_is_missing`；新增 `test_each_production_dependency_none_fails_closed`，逐项验证 13 个字段的 None 反例；新增 `test_canonical_bytes_dataclass_matches_asdict_form`，断言 dataclass 与其 `asdict` mapping 的 canonical bytes 完全相等。
- 通过条件：13 个字段在静态层为非 Optional callable，runtime 仍拒绝任一 None/非 callable/错误 StageRunner identity；三个局部重命名不改变值、排序或输出；canonical bytes 等价测试通过且无 `type: ignore` typing 绕过，receipt/terminal schema 与 bytes 不漂移。

### REWORK11 验证边界

VALIDATION8 的 unit/integration/Ruff 与 mypy stdout SHA 是外部提供的失败前证据；本轮只做 STATIC_ONLY 编辑，未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 post-fix 检查待后续授权，不能将本轮静态交付表述为 Gate 通过。
