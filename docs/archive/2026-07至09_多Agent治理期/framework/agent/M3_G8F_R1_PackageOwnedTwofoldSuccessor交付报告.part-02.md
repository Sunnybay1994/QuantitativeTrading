DIAGNOSTIC1/2 是已提供的反馈证据，本轮没有重新执行任何 Python。修复后的 focused unit/integration、Ruff、mypy、cold import 与 CPU 检查均未运行，因此本报告的 `DELIVERY_READY` 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 11. REWORK6 fixture callable lookup 闭环

本轮只补强 integration fixture/test 的可观察 lookup 证据；`successor_runtime.py`、生产异常包装、receipt/gate/schema/identity 合同均保持不变。独立初验 §13–14 指出的 REWORK5 缺口记录如下。

### folds 与 label-reconciliation 的独立 callable

- 现象：REWORK5 的 `test_labels_routes_to_canonical_folds_builder_not_labels` 只断言 `_builder_name("labels") == "folds"`、`"labels"` 不在 mapping，并将 `run_plan_builders["folds"]` 与自身比较；fixture 的所有 run-plan key 还共用一个 `marker`。因此测试没有进入 `run_upstream_stage` lookup，也不能证明 labels 实际调用了 folds callable，或 label-reconciliation 保持独立。
- 根因：测试替代 bundle 未提供可区分的 folds/label-reconciliation 行为观测；mapping 自比较和 shared marker 无法区分错误 key 路由、callable 误复用或实际 callback 未被调用。
- 应遵循规则：生产 route 仍为 `labels -> canonical folds`，`label-reconciliation -> canonical label-reconciliation`；fixture 必须使用独立 callable/sentinel 和阶段调用记录；回归必须经 concrete adapter 的 `run_fold`/依赖 `run_upstream_stage` lookup，禁止只验证字符串或 fixture mapping。
- 最小复现：旧测试即使把 `label-reconciliation` 错接到 folds，或让两个 key 共用 marker，也可能通过 `folds` 项自比较。新路径构造 concrete adapter，执行一个 fold；labels 若查找不存在的 key 会在 `run_upstream_stage` 失败，若误取 label-reconciliation 则调用记录不是 `("folds", "labels")`，若 label-reconciliation 误取 folds 则其记录不是 `("label-reconciliation", "label-reconciliation")`。
- 新增/强化测试：integration `test_labels_routes_to_canonical_folds_builder_not_labels` 现在使用独立 `folds_builder`、`label_reconciliation_builder`、不同 sentinel 与 `builder_call_records`，通过 `_adapter(boundary).run_fold(...)` 到达实际 callback lookup；断言 `"labels"` 缺失、两个 callable 不同、labels 只记录 `("folds", "labels")`，label-reconciliation 只记录自身 builder/stage。
- 通过条件：不改 production runtime；labels key 永不被索引，labels 只调用 canonical folds callable；label-reconciliation 只调用自己的独立 callable；任何错接或 shared marker 均被回归断言拒绝。

### REWORK6 验证边界

本轮没有运行任何 Python。修复后的 focused unit/integration、Ruff、mypy、cold import 与 CPU 检查均未运行，因此 `DELIVERY_READY` 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

## 15. REWORK8 VALIDATION4 shared receipt ownership 闭环

本轮只修正 `_lookup_refs` 的窄 ownership 例外并补充 unit/integration 对抗覆盖；不复制第二套规则，不改变 receipt/gate/schema/identity 合同之外的语义。VALIDATION4 的 STOP 历史保留。

### fold 间 exact shared receipt

- 现象：VALIDATION4 identity PASS、unit `7 passed`、integration `10 passed / 5 failed`；五个失败统一发生在 summary Gate 的 `_lookup_refs`，合法跨 fold shared receipt 也被 `SUCCESSOR_GATE_FAILED` 拒绝。
- 根因：原 `_lookup_refs` 只保存 `node_id -> "fold"/"gate"`，看到第二个相同 node_id 即拒绝，未保存完整 `StageReceiptRef` 和 owner tuple，也未调用既有 `_shared_receipt_duplicate_allowed` 窄判定。
- 应遵循规则：`owned` 必须保存 `node_id -> (StageReceiptRef, owner tuple)`；fold 间重复只有在 ref 完全相等且 `_shared_receipt_duplicate_allowed(ref, first_owner, second_owner)` 为 true 时允许。不同 ref（包含 bytes/path/semantic identity 任一漂移）、非 shared stage、同 fold、fold↔gate、prior gate↔current gate、gate↔gate 任何复用均 fail closed。
- 最小复现：两份 FoldExecution 使用同一 `experiment-identity`、`fold=None` 的 exact ref，并提交 summary Gate；旧实现仅因 node_id 重复返回 `SUCCESSOR_GATE_FAILED`。将该 ref 改动 sha/path/semantic 字段，或把 owner 改为同 fold、gate、非 shared stage，均不得进入例外。
- 新增/强化测试：unit `test_lookup_refs_allows_exact_shared_receipt_between_two_folds` 覆盖合法 exact shared 入 Gate；unit 覆盖 `test_lookup_refs_rejects_same_node_with_different_ref`、`test_lookup_refs_rejects_nonshared_stage_reuse_between_folds`、`test_lookup_refs_rejects_same_fold_reuse`、`test_lookup_refs_rejects_fold_gate_reuse`、`test_lookup_refs_rejects_prior_gate_current_gate_reuse`、`test_lookup_refs_rejects_gate_gate_reuse`；integration 强化 `test_two_fold_terminal_is_durable_and_replayable`，断言 two-fold summary Gate context 实际到达。
- 通过条件：合法两 fold exact shared receipt 可完成 summary Gate lookup；所有非窄 allowlist 重复稳定返回 `SUCCESSOR_GATE_FAILED`；既有 global physical path/bytes/semantic ownership 约束继续生效；不引入第二套 shared 判定。

### REWORK8 验证边界

VALIDATION4 的 identity/unit/integration 结果是外部提供的 STOP 证据；本轮没有重新执行任何 Python。修复后的 focused unit/integration、Ruff、mypy、cold import 与 CPU 检查均未运行，因此 `DELIVERY_READY` 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

DELIVERY_READY F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-successor-runtime\docs\framework\agent\M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md

## 17. VALIDATION6 STOP 证据

- **carrier 修正：PASS。** 仅预先创建 ignored `.tmp` 父目录，未预建 basetemp；identity preflight 再次证明 `quant` 与 successor runtime 精确来自当前 worktree。
- **focused unit：PASS。** `tests/unit/test_m3_successor_runtime.py` 为 `14 passed in 2.55s`。
- **focused integration：STOP。** pytest 已进入测试 body，捕获的原生 progress 为 `FF....F.......`。当前文件按定义顺序共有 15 个节点，因此该进度对应 12 个通过、3 个失败：`test_two_fold_terminal_is_durable_and_replayable`、`test_terminal_rejects_receipt_bytes_and_unknown_tree_entry`、`test_terminal_rejects_unknown_empty_directory`。这证明 VALIDATION5 的 basetemp setup 阻断已关闭，但 REWORK8 后仍存在可执行失败。
- **证据限制：** 本次桌面承载在长命令返回 session 边界时只保留 progress 行，未保留 pytest traceback、short summary、最终计时或显式 exit 文本；不得据此猜测三个节点是否共享根因，也不得把未捕获的错误码补造进报告。
- **停止语义：** 按首个业务检查失败即 STOP；未运行 Ruff exact3、mypy source、cold import 或最终 exact6/scope。下一步只应申请一个指定单节点、stdout/stderr/exit 无条件持久化的窄诊断，再形成 STATIC_ONLY 最小返工和独立复验；不得直接重跑完整 integration。
- **资源/临时终态：** integration basetemp 已由 carrier finally 删除；未运行 actual worker、retained、真实 acceptance、Linux 或 network。

## 16. VALIDATION5 STOP 证据

- **identity preflight：PASS。** `quant` 与 `quant.research.m3.successor_runtime` 均精确从当前 M3 worktree 导入；承载为 Windows Miniforge direct-call、BelowNormal、affinity `0xF00`、数值线程不超过 2。
- **focused unit：PASS。** `tests/unit/test_m3_successor_runtime.py` 为 `14 passed in 2.51s`。
- **focused integration：carrier/setup STOP。** 原生结果为 `1 passed, 14 errors in 3.45s`；14 个 error 均在 pytest setup 创建 fresh basetemp 时触发 `FileNotFoundError`，因为指定路径 `.tmp/m3-g8f-validation5-integration` 的父目录 `.tmp` 不存在。测试 body 未进入，因此该结果既不是 REWORK8 实现失败，也不能作为 post-fix integration PASS。
- **停止语义：** 按授权在首个 focused integration 非零退出处停止；未创建父目录后重试，未运行 Ruff exact3、mypy source、cold import 或最终 exact6/scope 检查。
- **资源/临时终态：** carrier finally 已确认目标 basetemp 不残留；未运行 actual worker、retained、真实 acceptance、Linux 或 network。后续若允许，应作为新的 carrier-corrected validation 租约，先由承载显式创建 ignored basetemp parent，再原样执行完整顺序；不得把本次 setup error 解释为代码红灯或绿灯。

## 14. VALIDATION4 STOP 证据

- **identity preflight：PASS。** `quant` 与 successor runtime 精确来自当前 worktree。
- **focused unit：PASS。** `7 passed in 2.45s`。
- **focused integration：STOP。** `10 passed / 5 failed in 19.64s`。五个失败均已越过 REWORK7 的 snapshot horizon 闭包，统一在 summary Gate 的 `_validate_gate_execution → _lookup_refs` 返回 `SUCCESSOR_GATE_FAILED`；因此 REWORK7 首失败已关闭，但当前结果尚不能仅凭共同错误码推定下一具体根因。
- **停止语义：** 按授权在 focused integration 失败处停止，未运行 Ruff、mypy、cold 或最终 scope；未重试或扩大范围。
- **资源/临时终态：** fresh basetemp 已精确删除；未运行 actual worker、retained、真实 acceptance、Linux 或 network。下一步只允许窄只读 Gate refs/fixture 诊断，形成静态返工并独立复验后再申请新租约。

## 12. VALIDATION3 STOP 证据

- **identity preflight：PASS。** `quant` 与 `quant.research.m3.successor_runtime` 均精确从当前 M3 worktree 导入；direct-call Windows Miniforge carrier 使用 BelowNormal、affinity `0xF00`、数值线程不超过 2。
- **focused unit：PASS。** `tests/unit/test_m3_successor_runtime.py` 为 `7 passed in 2.60s`。
- **focused integration：STOP。** `tests/integration/test_m3_successor_runtime.py` 为 `7 passed / 7 failed in 10.09s`。七个失败均已越过 REWORK6 的 `labels` lookup，统一在 `ProductionSuccessorStageAdapter.run_fold` 调用 `_one_ref(refs, stage="snapshot", horizon=None)` 时返回 `SUCCESSOR_STAGE_INVALID`；这证明上一层 `KeyError('labels')` 不再是当前首失败，但尚不能单凭共同表面错误断定新的具体根因。
- **停止语义：** 按授权在 focused integration 首失败处停止，未运行 Ruff exact3、mypy source、cold import 或最终 scope 检查，未自动重试或扩大范围。
- **资源/临时终态：** fresh pytest basetemp 已精确删除；未运行 actual worker、retained、真实 acceptance、Linux 或 network。下一步必须先做窄只读源码/失败证据诊断并形成静态返工，再经独立复验申请新验证租约。

## 13. REWORK7 VALIDATION3 horizon sentinel 闭环

本轮只修正 integration fixture 的 horizon 缺省值判断，并增加窄对抗测试；`successor_runtime.py`、unit test、生产异常包装、receipt/gate/schema/identity 合同均保持不变。VALIDATION3 的 STOP 历史保留。

### `_effective_horizon` 的 None 语义

- 现象：VALIDATION3 已提供 identity PASS、unit `7 passed`、integration `7 passed / 7 failed`；共同首失败发生在 snapshot 的 `horizon=None` 被 fixture `_effective_horizon` 改为 h5，随后 `ProductionSuccessorStageAdapter.run_fold` 的 `_one_ref(refs, stage="snapshot", horizon=None)` 返回 `SUCCESSOR_STAGE_INVALID`。
- 根因：旧条件只有 `horizon == self.omit_horizon`。fixture 默认 `omit_horizon=None` 时，snapshot 的合法 `horizon=None` 与默认配置相等，误触发 `runtime.HORIZONS[0]` 替换。
- 应遵循规则：只有 caller 明确设置了非 `None` 的 `omit_horizon`，且当前 horizon 精确命中该值，才执行既有缺失 horizon 替换；默认 `omit_horizon=None` 必须保留 `horizon=None`，不得改变生产错误包装或其他 fixture 逻辑。
- 最小复现：旧默认 boundary 上调用 `_effective_horizon(None)` 得到 h5；显式 `omit_horizon=10` 上调用 `_effective_horizon(10)` 仍应得到 `runtime.HORIZONS[0]`。新断言同时覆盖默认 `None` 保持 `None`、显式 10 的原有替换和显式 omit 下输入 `None` 不替换。
- 新增测试：integration `test_effective_horizon_requires_explicit_omit_setting`。
- 通过条件：默认 snapshot/任何未指定 horizon 的 stage 保持 `None`；显式 omit horizon 仍按原 fixture 语义替换为首个 horizon；VALIDATION3 的 snapshot `_one_ref` 不再因默认值误改而 fail closed；生产代码和错误包装不变。

### REWORK7 验证边界

VALIDATION3 的 identity/unit/integration 结果是外部提供证据；本轮没有重新执行任何 Python。修复后的 focused unit/integration、Ruff、mypy、cold import 与 CPU 检查均未运行，因此 `DELIVERY_READY` 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。

DELIVERY_READY F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-successor-runtime\docs\framework\agent\M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md

## 18. REWORK9 DIAGNOSTIC5 regular-file link-count 闭环

本轮状态由 IN_PROGRESS 收口为 DELIVERED；仅修改 exact5，独立初验报告保持只读。改动限于 regular-file link-count 平台谓词与窄对抗测试，未改变 symlink/reparse guard、controlled-tree identity、PROJECT-only root、receipt/Gate/terminal schema/identity 或错误包装。

### 现象、根因与平台规则

- 现象：DIAGNOSTIC5 的 wrapper/stdout carrier 证据将首个可归因问题定位为 regular-file link-count guard：Windows regular file 的 `st_nlink=0` 被旧的 `st_nlink != 1` 拒绝。证据 trace SHA：`f0dbca2bd2b222f23fe165d6dee2c5ee45de388321c271d92524492a0a79a81f`；原始 wrapper/stdout 不复制进交付物。
- 根因：`_walk_controlled_tree` 与 `_read_regular_file` 原先无条件要求 `st_nlink == 1`，没有表达 Windows regular file 的合法 0/1 反馈。
- 应遵循的平台规则：Windows regular file 只接受 `st_nlink in {0, 1}`；非 Windows 只接受 `st_nlink == 1`；任意平台 `st_nlink > 1` 拒绝。symlink/reparse guard 继续独立执行且不因该例外放宽。

### 最小复现、新测试与通过条件

- 最小复现：fake regular `DirEntry.stat(follow_symlinks=False)` 进入 `_walk_controlled_tree`，在 Windows 注入 nlink 0/1/2，在非 Windows 注入 0/1/2；再以 symlink mode 或 reparse attribute 配合 nlink 0，确认独立 guard 仍拒绝。
- 新增测试：unit `test_platform_regular_file_link_count_and_link_guards` 直接覆盖 Windows nlink0 正向、nlink1 正向、`>1` 拒绝；非 Windows nlink0 拒绝、nlink1 正向、`>1` 拒绝；symlink/reparse 仍拒绝。tree walk 与 `_read_regular_file` 均调用同一 `_regular_file_link_count_allowed`，不复制第二套规则。
- 通过条件：平台接受/拒绝矩阵与 symlink/reparse 独立拒绝均精确满足；不放宽实际路径 equality、PROJECT-only root 或任何 receipt/Gate/terminal 合同。

### REWORK9 验证边界与资源状态

本轮没有运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python；因此 DELIVERED 仅表示 exact5 静态交付就绪，不表示 Gate、真实 acceptance 或 actual worker 通过。未运行 retained、Linux、network；未提交、未 stage；controlled-tree identity 未改变；没有新建临时运行产物。DIAGNOSTIC5 identity/wrapper/stdout 为外部提供的诊断证据，本轮未重跑。

DELIVERY_READY F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-successor-runtime\docs\framework\agent\M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md

## 19. REWORK10 VALIDATION7 attestation-bound receipt tamper 闭环

本轮状态由 IN_PROGRESS 收口为 DELIVERED；仅修改 integration test 与两份任务文档，生产 `successor_runtime.py`、unit test、独立初验报告保持只读。receipt/tamper/fail-closed 生产合同未改变。

### 现象、根因与规则

- 现象：VALIDATION7 外部反馈为 unit `15 passed`、focused integration `14 passed / 1 STOP`，stdout trace SHA 为 `a6977c70b7c00f1471d848d1af348ac6d76db4345800ff51df6c147e36296b58`。失败对应 receipt-bytes tamper 反例的测试定位段：测试丢弃首轮 `SuccessorRunResult`，未从 canonical attestation 取得目标 receipt。
- 根因：旧测试在 `_run(request, boundary)` 后硬编码 `controlled_output_root/receipts/snapshot/shared-snapshot.json`，没有证明篡改的是 `first.attestation.receipts` 中已认证的 snapshot receipt；文件名也可能与当前 fixture/生产 adapter 的实际相对路径不一致。
- 应遵循规则：保留 `first = _run(...)`；从 `first.attestation.receipts` 唯一筛选 `stage == "snapshot"` 且 `fold is None`、`horizon is None`，强制 scope/scope_key/relative path shape；再用 `request.project_root / ref.relative_path` 定位真实 receipt，先核对原始 bytes sha，再实施既有 bytes tamper。禁止硬编码替代文件名、自构造 receipt 路径或弱化 `SUCCESSOR_TERMINAL_INVALID` fail-closed 断言。

### 最小复现、新测试与通过条件

- 最小复现：成功 `_run` 已生成 terminal attestation，但旧测试丢弃 `first` 并拼接 `shared-snapshot.json`；当该名字不在 attestation 的 snapshot ref 中时，tamper 目标脱离 canonical receipt 绑定。
- 新测试：integration `test_terminal_rejects_receipt_bytes_and_unknown_tree_entry` 现在使用 `first.attestation.receipts`，筛选唯一 snapshot/fold-none/horizon-none ref，断言 `SNAPSHOT` scope、`boundary.snapshot_id` scope_key、`output/stage/receipts/snapshot/*.json` shape 和原始 sha，再通过 `request.project_root / snapshot_ref.relative_path` 追加 bytes drift；随后仍断言 `verify_terminal_attestation` 为 `SUCCESSOR_TERMINAL_INVALID`，unknown-tree 分支保持独立。
- 通过条件：篡改目标必为当前 attestation 的唯一 canonical snapshot receipt；合法原始 receipt 可由 ref 定位，bytes drift 仍 fail closed 为 `SUCCESSOR_TERMINAL_INVALID`，且不存在硬编码 receipt 文件名或第二套路径解析规则。

### REWORK10 验证边界与资源状态

VALIDATION7 的 unit/integration 结果与 stdout SHA 是外部提供证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 focused integration 结果待后续授权验证，DELIVERED 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。

DELIVERY_READY F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-successor-runtime\docs\framework\agent\M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md

## 21. REWORK11 VALIDATION8 dependency typing 与 canonical bytes 闭环

本轮状态由 IN_PROGRESS 收口为 DELIVERED；仅修改生产 `successor_runtime.py`、unit test 与两份任务文档，integration test、独立初验报告、retained 现场保持只读。runtime 行为、字段顺序、receipt/terminal schema 与 canonical bytes 输出合同保持不变。

### 现象、根因与类型规则

- 现象：VALIDATION8 外部证据为 identity PASS、focused unit `15 passed`、focused integration `15 passed`、Ruff exact3 PASS；mypy 首次执行 STOP，报告 13 个错误。mypy stdout SHA：`ee7073f019c91a27530390b3f6da8e52a44733c7f93e62d9515b6fd0c5bfbf5b`，stderr 为空。
- 根因：`SuccessorProductionDependencies` 的 13 个必需 callback 字段仍标注为 Optional，静态调用无法证明可调用；`_validate_fold_execution` 中 work-key 与 receipt-shape 共用 `expected`，controlled-tree entry digest 与前文 digest 语义冲突；`_canonical_bytes` 的 `hasattr` 分支直接将 `object` 传入 `asdict`，未形成最窄 dataclass typing 桥接。
- 应遵循的类型规则：以下 13 个字段改为原有 Callable Protocol 的非 Optional 注解，顺序不变：`stage_runner_factory`、`run_upstream_stage`、`run_formal_stage`、`verify_fold`、`run_summary`、`verify_summary`、`run_reproducibility`、`verify_reproducibility`、`run_readiness`、`verify_readiness`、`run_acceptance`、`verify_acceptance`、`verify_gate`。`__post_init__` 和 adapter 的全部 callable/StageRunner identity 检查、None 拒绝和构造行为保留。仅将局部变量等价改名为 `expected_work_key`、`expected_receipts`、`entry_digest`；canonical bytes 仅使用 `asdict(cast(Any, value))` typing 桥接，不使用 `type: ignore`，并保留原 sort/separators/ASCII/allow_nan 与 schema/bytes。

### 最小复现、新测试与通过条件

- 最小复现：对任一 dependency field 传 `None`，构造必须仍返回 `SUCCESSOR_INPUT_INVALID`；同一验证函数中复用 `expected` 或 entry `digest` 会触发 mypy 重定义/类型冲突；对 dataclass 值直接 `asdict(value)` 则不满足静态 overload。
- 保留/新增测试：保留全 None 的 `test_production_dependencies_fail_closed_when_any_boundary_is_missing`；新增 `test_each_production_dependency_none_fails_closed`，逐一将 13 个字段替换为 None 并断言 `SUCCESSOR_INPUT_INVALID`；新增 `test_canonical_bytes_dataclass_matches_asdict_form`，断言 dataclass 与 `asdict` mapping 的 `_canonical_bytes` 完全相等。
- 通过条件：mypy 不再因 callback Optional、局部重名或 `asdict` overload 报错；每个 None/非 callable/错误 StageRunner identity 仍 fail closed；局部重命名不改变值、排序或 bytes；canonical bytes 等价测试通过且无 typing 忽略绕过。

### REWORK11 验证边界与资源状态

VALIDATION8 的 unit/integration/Ruff/mypy 结果与 stdout SHA 是外部提供的修复前证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 post-fix 检查待后续授权，DELIVERED 仅表示 exact5 静态交付就绪，不表示 Gate 或真实 acceptance 通过。

DELIVERY_READY F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-successor-runtime\docs\framework\agent\M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md
