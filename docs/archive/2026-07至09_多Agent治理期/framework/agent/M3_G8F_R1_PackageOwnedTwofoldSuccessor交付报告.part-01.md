# M3 G8F R1：Package-owned Two-fold Successor Runtime 交付报告

日期：2026-08-24
状态：VALIDATION_PASS；Windows 开发检查已闭合，不表示 actual worker / Gate 通过
任务：`M3-G8F-R1`
worktree：`artifacts/dev_worktrees/m3-g8f-successor-runtime`
exact base：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`

## 21. VALIDATION9 PASS 证据

- **identity preflight：PASS。** `quant` 与 `quant.research.m3.successor_runtime` 均精确从当前 M3 worktree 导入。
- **post-fix 定向 unit：PASS。** missing-boundary、逐字段 None dependency、canonical dataclass bytes 三个节点为 `3 passed in 2.63s`。
- **Ruff exact3：PASS。** production、unit、integration 三个 Python 文件返回 `All checks passed!`。
- **mypy production：PASS。** `Success: no issues found in 1 source file`。
- **cold import：PASS。** `quant` 与 successor runtime 的路径均精确指向当前 worktree。
- **scope/diff：PASS。** 非 ignored 写面精确为任务/交付/独立初验三份文档、production、unit、integration 六个路径；`git diff --check` 返回 0。VALIDATION8 已绿的完整 unit `15 passed` 与完整 integration `15 passed` 按中央裁定未机械重复。
- **持久化证据：** ignored `artifacts/agent_runs/m3-g8f-validation9/` 中，focused stdout SHA-256 `4f4809ebfeb1036eb55413ace7f59d9c517ee0ee0cc387e1060bc4a96f38adbd`；Ruff stdout SHA-256 `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`；mypy stdout SHA-256 `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff`；scope stdout SHA-256 `8a80ae0463f5e8ff8308ab616e251cbd68f1101afcdbeed60e4db252fc31a22b`；全部 exit 文件均为 0。
- **资源/边界：** fresh basetemp 与空 `.tmp` 已删除，0xF00 无残留。未运行 actual worker、retained resume、真实 acceptance、Linux 或 network；本结论只关闭 Windows 静态 runtime/terminal 开发验证，不冒充真实 successor 或项目 Gate。

## 20. VALIDATION8 STOP 证据

- **identity preflight：PASS。** `quant` 与 `quant.research.m3.successor_runtime` 均精确从当前 M3 worktree 导入。
- **focused unit：PASS。** `15 passed in 2.53s`。
- **focused integration：PASS。** `15 passed in 65.23s`；REWORK9/10 后两层 executable 首失败均已关闭。
- **Ruff exact3：PASS。** production、unit、integration 三个 Python 文件返回 `All checks passed!`。
- **mypy production：STOP。** `src/quant/research/m3/successor_runtime.py` 首次实际到达 mypy 后报告 13 个错误：五处 optional dependency callback 被静态视为可能为 `None`；gate payload 局部变量 `expected` 重定义导致后续 indexed assignment 被推断为字符串；controlled-tree 局部变量 `digest` 与前文 `ArtifactDigest` 类型冲突；`asdict` 的 `is_dataclass` 分支未满足 mypy overload narrowing。按首失败合同，未运行 cold import 或最终 exact6/scope。
- **持久化证据：** ignored `artifacts/agent_runs/m3-g8f-validation8/` 中，unit stdout SHA-256 `085ea98b0a720ed31dd4cbb6664d24233ce505751bff4ba95031727b0449850d`；integration stdout SHA-256 `81d9b5b9d218073e2ccb04739f3fda18eef140c74e9094c3dd2059b2b2851b9f`；Ruff stdout SHA-256 `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`；mypy stdout SHA-256 `ee7073f019c91a27530390b3f6da8e52a44733c7f93e62d9515b6fd0c5bfbf5b`，stderr 为空。
- **资源/临时终态：** fresh basetemp 与空 `.tmp` 已删除，0xF00 无残留。未运行 actual worker、retained、真实 acceptance、Linux 或 network。下一步必须先做 STATIC_ONLY、行为等价的类型返工并独立复验，再申请新的 post-fix validation；不得直接重试 mypy。

## 19. VALIDATION7 STOP 证据

- **identity preflight：PASS。** `quant` 与 `quant.research.m3.successor_runtime` 均精确从当前 M3 worktree 导入。
- **focused unit：PASS。** `tests/unit/test_m3_successor_runtime.py` 为 `15 passed in 2.54s`。
- **focused integration：STOP。** `tests/integration/test_m3_successor_runtime.py` 为 `14 passed / 1 failed in 50.88s`。唯一失败是 `test_terminal_rejects_receipt_bytes_and_unknown_tree_entry` 在 tamper 动作前读取不存在的 `receipts/snapshot/shared-snapshot.json`，原生异常为 `FileNotFoundError`。fixture `_stage_receipt(stage="snapshot", ...)` 当前生成的 node ID 是 `snapshot`，其 `_receipt` 路径规则为 `receipts/{stage}/{node_id}.json`；因此该测试硬编码路径没有指向本轮实际发布的 snapshot receipt。
- **停止语义：** 按首个 focused 检查失败即 STOP；未运行 Ruff exact3、mypy source、cold import 或最终 exact6/scope。当前结果证明 REWORK9 的 Windows `st_nlink=0` 首失败已经关闭，但不能据此宣称完整 integration、Gate 或 runtime 通过。下一步只能先做 STATIC_ONLY 最小 fixture 返工并重新独立复验；不得直接重试验证。
- **持久化证据：** ignored `artifacts/agent_runs/m3-g8f-validation7/` 中，integration stdout SHA-256 为 `a6977c70b7c00f1471d848d1af348ac6d76db4345800ff51df6c147e36296b58`，stderr 为空文件 SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，exit 文件 SHA-256 `6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b`；unit stdout SHA-256 为 `90c19f654552a244fa829492f0d6c2c6dfdb782c15864814e69fca734c596bc9`。
- **资源/临时终态：** 两个 fresh basetemp 均已删除，ignored `.tmp` 父目录为空后已删除，0xF00 无残留。未运行 actual worker、retained、真实 acceptance、Linux 或 network。

## 1. exact diff

本 worktree 仅写入任务单规定的五条路径：

1. `src/quant/research/m3/successor_runtime.py`：新增 package-owned runtime、可实例化的 `ProductionSuccessorStageAdapter`/factory、canonical public M3 API binding、确定性 Gate scope join、全局 receipt ownership verifier、receipt/tree verifier、PASS-only terminal publisher；`_runner` 接受平台具体 `Path` subclass 但保持 PROJECT-only root equality。
2. `tests/unit/test_m3_successor_runtime.py`：覆盖 h5/h10、summary 无 fold 的 receipt 形状、receipt 引用闭包和稳定错误码。
3. `tests/integration/test_m3_successor_runtime.py`：通过 concrete adapter/factory、真实 `StageRunner` 类型和测试侧隔离的 deterministic public-stage boundary substitutes 覆盖 two-fold replay、config/receipt/tree 漂移、缺失 h10、缺失第二 fold、marker public bundle、reproducibility scope drift、物理 receipt alias、Path subclass/invalid-root 守卫，以及缺少生产依赖时零 successor artifact/terminal 写入。
4. `docs/framework/agent/M3_G8F_R1_PackageOwnedTwofoldSuccessor任务单.md`：同步记录 REWORK1/REWORK2/REWORK3 的静态问题闭环，未改变冻结合同；REWORK4 因证据不足 STOP，未改任务合同。
5. 本交付报告。

未修改 `__init__.py`、配置、roadmap、shared SSOT、既有 stage 模块、旧 retained worktree 或其 config/evidence；未提交 commit。

## 2. API 与边界

公开输入/结果类型：

- `SuccessorRuntimeRequest`：显式 `project_root`、受控输出根、按 fold 排序的两个 `SuccessorFoldRequest`、统一带时区 UTC `now` 和 `SuccessorRuntimeIdentity`。
- `SuccessorFoldRequest`：一个 `SuccessorConfigInput` 与一个已经 verified 的 `VerifiedG1Release`；两份 config 必须有不同 raw/full identity，并共享 scientific identity。
- `SuccessorPublicApiBundle`：延迟绑定既有 `StageRunner`、公开 run-plan builders、formal backtest/tracking、research-summary builder/verifier、formal reproducibility、readiness evidence 和 formal acceptance/audit API。
- production adapter 内部重新绑定 `make_public_successor_api_bundle()`；可选 caller bundle 只有在 StageRunner、每个 run-plan builder、formal stage、summary/reproducibility/readiness/acceptance builder/verifier 全部 exact identity 相等时才可使用，marker bundle fail closed。
- `SuccessorProductionDependencies`：只允许单 stage 或单 gate 的窄 typed bridge callback；StageRunner factory 绑定既有 `make_project_stage_runner`，不接受任意 runner callback 或 caller-owned `run_fold`/`run_*` sequence。
- `ProductionSuccessorStageAdapter`：package-owned、可实例化的 `SuccessorStageApi` concrete implementation。它创建 PROJECT-only runner，固定上游 fold 顺序，逐 horizon 调用 formal backtest/tracking，固定 summary → reproducibility → readiness → acceptance，并在每个 gate 内调用对应现有 verifier bridge。
- `make_production_successor_stage_adapter(...)` / `run_production_two_fold_successor(...)`：生产构造与唯一 concrete 运行入口；依赖缺失在构造期以 `SUCCESSOR_INPUT_INVALID` fail closed。
- `SuccessorStageApi`：保留为 runtime 的窄 protocol；不再是唯一生产实现。
- `FoldExecution`：固定 h5/h10 `WorkIdentity`，共享跨 fold receipt 可用 `fold=null`，work receipt 显式绑定 fold/horizon。
- `GateExecution`：携带完整 `StageReceiptRef`，不是 caller 注入的 node ID 列表；顺序固定为 summary → reproducibility → readiness → acceptance。
- `compute_successor_gate_identity(...)` 与 `compute_successor_gate_scope_key(...)`：由 execution/work/prior-gate identity 确定性推导 Gate identity 与 summary/reproducibility/readiness/acceptance receipt scope_key join。
- `run_two_fold_successor(...)`：唯一编排入口；已存在 terminal 时只允许 `resume=True` 加 fresh verify 通过的 exact replay。
- `verify_terminal_attestation(...)`：重新读取 canonical bytes、config/release、全部 receipt、全部 outputs 和受控树，并调用 fold/gate fresh verifier；仅返回 `VerifiedTerminalAttestation`。
- `make_project_stage_runner(...)`：构造既有 `StageRunner`，`artifact_roots` 固定为 `{"PROJECT": project_root}`，专业 `stage_root` 必须位于 PROJECT 内；不把专业 root 冒充 PROJECT root。

## 3. terminal schema 与失败语义

`completion.json` 使用 `m3-successor-terminal-v1` canonical JSON，绑定：

- 两份 config 相对路径、version、raw/full/scientific SHA256；
- code version、dependency fingerprint、provider runtime fingerprint；
- 两个 G1 release/manifest/root、snapshot/experiment/work identities；
- two-fold identity、`[5, 10]` horizon 集合、全部 upstream/gate receipt 的 node/stage/scope/scope_key/path/SHA256；
- summary、reproducibility、readiness、acceptance 的 PASS identity；
- terminal status `PASS`、受控输出根相对路径和完整 tree digest。

receipt 必须在受控输出根内，所有 receipt outputs 也必须在该根内；`PROJECT` 是唯一传给 receipt verifier 的 root alias。树扫描拒绝未知文件、symlink/reparse、硬链接普通输出、`.tmp` 和 `.stage-tmp` 残留；保留同目录唯一临时项 + hardlink no-clobber 原子提交。

稳定边界错误码包括 `SUCCESSOR_INPUT_INVALID`、`SUCCESSOR_STAGE_INVALID`、`SUCCESSOR_GATE_FAILED`、`SUCCESSOR_TERMINAL_INVALID`、`SUCCESSOR_TERMINAL_CONFLICT` 和 `SUCCESSOR_TERMINAL_PUBLISH_FAILED`。任何缺 fold、缺 h10、非 PASS、identity/bytes/root/tree 漂移都不会发布有效 terminal。

## 4. 静态反例覆盖

- fixture 缺 h10：在 concrete adapter 形成 `FoldExecution` 时拒绝，`completion.json` 不创建。
- 缺失 production dependency：factory 在任何 stage callback、receipt、artifact 或 terminal 写入前返回 `SUCCESSOR_INPUT_INVALID`。
- request 重复 fold：构造层拒绝；两 fold 不是自动扫描得到。
- config bytes、receipt bytes 或受控树未知 entry 漂移：fresh terminal verify 返回 `SUCCESSOR_TERMINAL_INVALID`。
- 专业 root 嵌套于 PROJECT：`project_stage_root` 合法；`make_project_stage_runner` 仍只给 StageRunner PROJECT root。
- terminal replay：同 identity、同 bytes 只能 fresh verify；terminal 文件名、存在性、caller status 或 receipt-only 不构成证明；fresh gate verifier 收到 attestation 重建的 folds 与 prior-gate 前缀。
- F1 未知空目录：`test_terminal_rejects_unknown_empty_directory` 证明目录闭包不是仅文件集合。
- F2 runner bypass：`test_production_factory_rejects_arbitrary_stage_runner_bypass` 证明任意 StageRunner callback 在写入前拒绝；fixture 的 runner 是真实 `StageRunner`，root registry 精确为 `{"PROJECT": project_root}`。
- F3 identity join：`test_scope_key_drift_cannot_join_work_to_execution` 与 `test_lookup_refs_consumes_fold_and_prior_gate_ownership` 覆盖 snapshot/experiment/work join 和 fold/prior-gate receipt ownership。
- F4 fresh context：`test_fresh_gate_verifier_requires_reconstructed_fold_and_prior_context` 要求四 Gate fresh verify 都接收两 fold 与正确的 prior-gate 顺序。
- F2 marker bundle：`test_production_factory_rejects_marker_public_api_bundle` 证明 caller marker builders/verifiers 不能进入 production adapter。
- F3 reproducibility scope drift：`test_reproducibility_scope_key_drift_cannot_join_work` 证明正确 fold/horizon 形状不能替代 deterministic work join。
- F3 physical/semantic alias：`test_distinct_node_same_receipt_path_and_bytes_is_rejected` 与 `test_unique_refs_rejects_distinct_node_physical_and_semantic_alias` 证明不同 node_id 不能复用 receipt path、bytes 或 semantic owner；同一 shared node 仅允许显式 cross-fold shared-stage allowlist。
- symlink/reparse/hardlink 输出和临时残留：受控树/receipt 读取 fail closed。

Windows exact current Conda `sys.executable` 的多 hardlink 正向能力探针仍必须由后续授权 CPU 窗口按既有 session/capability gate 执行；本静态 turn 没有伪造或宣称该证据。

## 5. 验证与剩余风险

本 STATIC_ONLY REWORK2 turn 仅执行了只读 `git`、`rg`、`Get-Content` 和 `apply_patch`；没有执行任何 Python。此前原静态交付与 REWORK1 的“无代码验证”边界保留，不被本次代码改动改写为已验证。

未运行：focused unit、focused integration、pytest、Ruff、mypy、cold import、CPU、真实网络、actual M3 worker、retained resume、真实 acceptance、Linux Gate，也未提交或 stage 代码。因此当前状态是 `STATIC_DONE`，不是 Gate 通过。

剩余风险仅是静态窗口之外的验证边界：独立初验与主 Agent 终验仍需检查真实 receipt schema、Windows 当前 Conda 能力、真实 worker 输入闭包和跨 Gate 证据。本 turn 没有宣称这些 Gate 已通过。旧 retained `c9f2f36` 现场保持 LOCKED、零写。

## 6. REWORK1 问题闭环（现行实现）

以下记录对应任务单 F1-F4；每项均保留“现象—根因—规则—最小复现—新增测试—通过条件”，并描述当前 exact5 实现，而非 future work。

### F1：完整 allowlisted directory/path closure

- 现象：原 tree verifier 比较文件集合但放过未知空目录。
- 根因：没有把实际目录项纳入受控闭包。
- 规则：receipt/output 父目录与 StageRunner 已知运行时目录是唯一允许目录，未知空目录必须 fail closed。
- 最小复现：terminal 发布后创建 `controlled_output_root/unknown-empty/` 并 fresh verify。
- 新增测试：integration `test_terminal_rejects_unknown_empty_directory`。
- 通过条件：返回 `SUCCESSOR_TERMINAL_INVALID`。

当前代码用 receipt/output 父目录、`.stage-locks`/`.stage-tmp`、StageRunner 固定目录和受限 lock-directory 形态组成 allowlist；不复制 StageRunner 的目录逻辑。

### F2：真实 StageRunner 与 exact PROJECT-only topology

- 现象：原 integration fixture 是手写 `_DeterministicStageRunner`，生产 factory 可被任意 callback 替换。
- 根因：没有同时验证 factory 身份、StageRunner 具体类型和 root registry。
- 规则：只能调用既有 `make_project_stage_runner`；返回值必须是当前 `StageRunner`，`_artifact_roots` 精确为 `{"PROJECT": project_root}`，stage root 必须是既有 PROJECT 内路径。
- 最小复现：注入返回任意对象的 runner bypass callback。
- 新增测试：integration `test_production_factory_rejects_arbitrary_stage_runner_bypass`；正常 fixture 直接使用真实 `StageRunner`。
- 通过条件：adapter 构造在任何 successor receipt/artifact/terminal 写入前返回 `SUCCESSOR_INPUT_INVALID`。

### F3：scope_key 与完整 execution/work join

- 现象：原 `_lookup_refs` 丢弃 `executions`/`known`；snapshot scope_key 也未显式 join 到 execution。
- 根因：gate receipt refs 被当作孤立 caller 输出，ownership 与 execution/work identity 未形成显式闭包。
- 规则：snapshot→`snapshot_id`、experiment/features/labels→`experiment_key`、work h5/h10→`compute_work_key`；summary/gate scope contract 和 fold/prior-gate ownership 必须一致。
- 最小复现：把 work receipt scope_key 改为非 execution work key，或复用已有 fold/prior-gate receipt。
- 新增测试：integration `test_scope_key_drift_cannot_join_work_to_execution`；unit `test_lookup_refs_consumes_fold_and_prior_gate_ownership`。
- 通过条件：分别以 `SUCCESSOR_STAGE_INVALID` 或 `SUCCESSOR_GATE_FAILED` fail closed。

### F4：fresh verifier 的 attestation-reconstructed context

- 现象：原 terminal fresh gate verify 收到空 folds/prior-gates。
- 根因：`verify_gate` contract 未表达重建上下文，terminal replay 未按顺序累积前序 Gate。
- 规则：fresh verifier 接收 canonical attestation 重建的两 fold executions 和 summary → reproducibility → readiness → acceptance 的 prior-gate 前缀。
- 最小复现：注入拒绝空 folds 或错误 prior-gate 顺序的 verifier。
- 新增测试：integration `test_fresh_gate_verifier_requires_reconstructed_fold_and_prior_context`。
- 通过条件：首次 gate verify 与 terminal replay 均通过严格上下文断言。

本报告仍严格声明 STATIC_ONLY：上述测试仅静态写入，未执行 focused unit/integration、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux/network；未提交或 stage；独立初验报告未修改。

## 7. REWORK2 问题闭环（现行实现）

以下记录对应 REVIEW-REWORK2 F2/F3，保留现象、根因、规则、最小复现、新测试与通过条件；实现已经在当前 exact5 内完成，不描述为 future work。

### F2：canonical production public API binding

- 现象：REWORK1 只锁定真实 StageRunner；caller 仍可传入 stage_runner_type 正确但 builder/verifier 全为 marker 的 bundle。
- 根因：production adapter 直接采用 caller bundle，没有 canonical binding 或逐项 identity closure。
- 规则：adapter 内部调用 `make_public_successor_api_bundle()`；可选 bundle 必须逐项 exact identity 匹配 canonical StageRunner、所有 run-plan builder、formal stage、summary/reproducibility/readiness/acceptance builder/verifier。
- 最小复现：真实 StageRunner factory + marker bundle + 忽略 public API 的窄 callbacks。
- 新增测试：integration `test_production_factory_rejects_marker_public_api_bundle`；正常 fixture 通过 monkeypatch 仅隔离测试侧 canonical binding，production 入口不接收 marker 参数。
- 通过条件：构造阶段 `SUCCESSOR_INPUT_INVALID`，无 receipt/artifact/terminal 写入；canonical bundle 成为 adapter 内部绑定。

### F3：deterministic Gate scope joins

- 现象：原 reproducibility refs 可使用任意唯一 64-hex scope_key；四类 Gate 没有统一由 execution/work/prior-gate identity 重算的映射。
- 根因：Gate validator 只检查数量、stage、scope 和局部唯一性。
- 规则：summary 使用 shared experiment join；reproducibility 使用对应 work `(fold,horizon,work_key)` join；readiness 使用 fold execution join 与 prior Gate identities；acceptance 使用 deterministic acceptance Gate identity。Gate identity 本身同样由 folds/prior gates 推导。
- 最小复现：只替换 reproducibility scope_key，不改变 fold/horizon/stage/scope；或伪造匹配 shape 的 Gate identity。
- 新增测试：integration `test_reproducibility_scope_key_drift_cannot_join_work`。
- 通过条件：返回 `SUCCESSOR_GATE_FAILED`，不构建 terminal。

### F3：global physical receipt ownership

- 现象：不同 node_id 可指向同一 canonical receipt path/bytes，或复用同一 semantic owner；node-id 去重无法发现 alias。
- 根因：`_unique_refs` 与 terminal ownership 只以 node_id 为主，未做全局物理路径、bytes digest、semantic owner closure。
- 规则：全局同时检查 canonical physical path、receipt SHA256、`(stage, scope, scope_key, fold, horizon)` semantic owner 和 node_id；唯一例外是显式 shared-stage 中两个 fold 对同一 exact shared node 的复用。
- 最小复现：两个 fold-specific features 使用不同 node_id 但同一 receipt path/bytes；或两个不同 node_id 使用相同 semantic owner。
- 新增测试：integration `test_distinct_node_same_receipt_path_and_bytes_is_rejected`；unit `test_unique_refs_rejects_distinct_node_physical_and_semantic_alias`。
- 通过条件：返回 `SUCCESSOR_TERMINAL_INVALID`；合法 shared cross-fold receipt 仍只按窄 allowlist 保留。

REWORK2 交付仍是 STATIC_ONLY：未执行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux/network；未提交或 stage；独立初验报告保持只读。

## 8. REWORK3 问题闭环与 DELIVERY_READY

### Path concrete subclass acceptance

- 现象：identity preflight PASS；focused unit `7 passed`；focused integration `4 passed / 8 failed`，8 个失败全部定位到 `successor_runtime.py::_runner` 最终 guard 的 `SUCCESSOR_INPUT_INVALID`。
- 根因：真实 `StageRunner` 返回平台具体的 `pathlib.WindowsPath`/`pathlib.PosixPath`，`type(actual_stage_root) is not Path` 错误拒绝了合法 concrete subclass。
- 规则：使用 `isinstance(actual_stage_root, Path)` 接受平台具体子类，同时保留 `_artifact_roots == {"PROJECT": context.project_root}` 与 `actual_stage_root == stage_root`；非 Path 和 root mismatch 继续 fail closed。
- 最小复现：真实 StageRunner 的 `_stage_root` 为 `WindowsPath`/`PosixPath`；或将其替换为 `str(stage_root)`、`stage_root / "unexpected"` 再调用 `_runner`。
- 新增测试：integration `test_runner_accepts_concrete_path_subclass_and_rejects_invalid_root`，覆盖 concrete subclass 接受、非 Path 拒绝、root mismatch 拒绝。
- 通过条件：平台 concrete Path subclass 通过 `_runner` 最终 guard；非 Path/root mismatch 返回 `SUCCESSOR_INPUT_INVALID`；PROJECT-only root mapping/equality 未放宽。

### REWORK3 validation STOP evidence

- 已有可执行反馈证据：identity preflight PASS；focused unit `7 passed`；focused integration `4 passed / 8 failed`；全部 8 failures 均为上述 Path 类型误拒绝。
- 本轮严格 STATIC_ONLY：未重跑 Python、focused tests、Ruff、mypy、cold import 或 CPU；因此修复后的测试结果仍未验证，`DELIVERY_READY` 不等于 Gate 通过。
- 未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告未修改。

## 9. REWORK4 VALIDATION2 诊断（STOP）

本轮先将报告状态置为 `IN_PROGRESS`，随后仅做静态源码/fixture 合同核对；未修改生产代码或测试。现有证据不足以安全归因，因此按任务书 STOP，不宣称 `DELIVERY_READY`。

### bounded fold boundary

- 现象：VALIDATION2 identity preflight PASS；focused unit `7 passed`；focused integration `5 passed / 8 failed`。报告称 8 个失败到达 `run_two_fold_successor` line 1462，并以 `SUCCESSOR_STAGE_FAILED` 表面化；Path guard 已通过。
- 根因证据：line 1450 的 `api.verify_fold` 是三段 bounded region 中唯一没有在 adapter 内显式翻译普通异常的调用；`ProductionSuccessorStageAdapter.verify_fold`（约 1097-1104）直接调用 `SuccessorProductionDependencies.verify_fold`。因此一个任意 verifier exception 确实可以穿透到 line 1462。
- 生产合同证据：`SuccessorProductionFoldVerifier`（约 670-679）要求 `execution`、`context`、`public_apis`，返回 `None`；adapter 与该 Protocol 的调用形状一致。
- fixture 合同证据：integration `_DeterministicProductionBoundary.verify_fold`（约 319-328）接受同样三个 keyword、删除未使用的 `public_apis`、断言 `context.fold == execution.fold` 并递增已初始化的 `fold_verifications`，没有可由当前源码证明的异常或 malformed output。`run_two_fold_successor` 使用同一 `fold_request.fold` 构造 `fold_context` 与 `FoldExecution.fold`。
- 其余边界证据：`_validate_fold_execution` 将自身普通异常翻译为 `SUCCESSOR_STAGE_INVALID`；`_verify_receipts` 及外层 receipt 分支也翻译为稳定错误。因此当前源码无法证明 VALIDATION2 的 8 个失败来自 fixture `verify_fold`，也无法证明具体 exception 类型。

### STOP 决定

- 最小复现（仅证明潜在路径）：替换 production `verify_fold` bridge 为抛出普通 `RuntimeError` 的 callback；现行 adapter 会让该异常抵达 line 1462。这个复现不能证明当前正常 fixture 正在抛同一异常。
- 不能在没有 traceback/exception payload 的情况下猜测是 verifier exception、断言失败、输出形状还是其他状态；增加 broad catch、改变错误码或修改 fixture 都可能掩盖真实原因。
- required adversarial regression 未添加；原因是其预期错误码与真实失败原因尚未可证，继续修改会违反“不猜测、不扩大 swallowing”的 STOP 条件。需 manager 提供该 8 failures 的最小 traceback/异常类型后再恢复。
- 本轮 post-fix checks：无 fix，未运行 focused tests、pytest、Ruff、mypy、cold import、CPU 或任何 Python；未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 10. REWORK5 DIAGNOSTIC2 闭环（fixture-only）

本轮只修正 integration fixture 的 canonical builder 路由；生产 runtime、异常包装、receipt/gate/schema/identity 合同均未修改。REWORK4 的 STOP 历史保留，DIAGNOSTIC1/2 作为定位证据记录如下。

### labels builder route

- 现象：DIAGNOSTIC1 给出 identity preflight PASS、focused unit `7 passed`、focused integration `5 passed / 8 failed`；Path guard 已通过，但 fold boundary 仍以 `SUCCESSOR_STAGE_FAILED` 表面化。DIAGNOSTIC2 捕获到 `KeyError('labels')`，发生在 integration fixture `run_upstream_stage` line 282，并沿 adapter `run_fold` line 1037 传播。
- 根因：fixture `_builder_name("labels")` 原样回退为 `"labels"`，随后执行 `public_apis.run_plan_builders["labels"]`。canonical `make_public_successor_api_bundle()` 的 `run_plan_builders` 明确以 `"folds": make_experiment_artifact_run_plan` 提供该波次 builder，并没有 `"labels"`；`"label-reconciliation"` 是独立的 canonical builder，不能合并或改名。
- 应遵循规则：`labels` 必须显式映射到 canonical `folds` builder；`label-reconciliation` 必须继续映射自身；fixture 不得凭 stage 名称发明不存在的 production bundle key；不改变 production exception wrapping 或添加 broad catch。
- 最小复现：在 `_DeterministicProductionBoundary` 上调用 `_builder_name("labels")`，旧逻辑返回 `"labels"`，再索引只含 `folds` 的 `run_plan_builders` 即得到 `KeyError('labels')`。修复后返回 `"folds"`，同一 canonical mapping 可解析；`_builder_name("label-reconciliation")` 仍返回自身。
- 新增测试：integration `test_labels_routes_to_canonical_folds_builder_not_labels`，断言 `labels` 精确路由为 `folds`、`labels` 不在 canonical mapping、解析出的 callable 是 `folds` 项，且 `label-reconciliation` 保持独立 key。
- 通过条件：labels 波次不再查找不存在的 `labels` builder，实际 lookup 使用 `make_experiment_artifact_run_plan` 对应的 `folds` 项；label-reconciliation 路由不漂移；无生产代码/错误包装扩展。

### DIAGNOSTIC2 后验证边界

