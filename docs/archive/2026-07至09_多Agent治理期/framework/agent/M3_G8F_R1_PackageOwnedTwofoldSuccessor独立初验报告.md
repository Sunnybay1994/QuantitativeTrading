# M3 G8F R1：Package-owned Two-fold Successor Runtime 独立初验报告

## 1. 身份、范围与稳定性

- task_id：`M3-G8F-R1-REVIEW`
- manager_task_id：`019ff5c4-942f-7260-8f31-c52fc43c249f`
- root_task_id：`01a00613-d47b-7281-a2e0-4f0fa585eb59`
- dispatcher：Luna worker 2 / `01a031ea-fa6a-7422-9332-d3d7b0ca1cac`
- exact base / HEAD：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`
- branch：`codex/m3-g8f-successor-runtime`
- worktree：`F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`

审查前后两次 Git 读取均显示相同的 branch、HEAD、tracked diff 和五个输入文件的 Git object hash；未发现 Git worktree lock 或源文件漂移。未创建 worktree、未提交，也未调用 external cursor-agent。除本报告外没有写入任何文件。

严格只读了以下五个输入：

1. `src/quant/research/m3/successor_runtime.py`
2. `tests/unit/test_m3_successor_runtime.py`
3. `tests/integration/test_m3_successor_runtime.py`
4. `docs/framework/agent/M3_G8F_R1_PackageOwnedTwofoldSuccessor任务单.md`
5. `docs/framework/agent/M3_G8F_R1_PackageOwnedTwofoldSuccessor交付报告.md`

本 turn 没有运行 Python、pytest/collection、Ruff、mypy、cold import、网络、浏览器、SQLite、worker 或其他真实 I/O。

## 2. 必须记录的终端事实

按调度任务提供的终端事实记录：两次 validation attempt 均为 carrier/import environment failure；第二次 identity preflight `-c` payload 被截断为 `from`。因此没有 unit/integration/Ruff/mypy/cold code evidence。`M3-G8F-R1` 是 durable `STOP`；exact5 禁止 submit、merge 和 actual worker。以上事实不被本静态审查改写成测试通过。

## 3. 静态合同结论

已确认的正向结构：

- `ProductionSuccessorStageAdapter` 在代码内固定 fold 上游顺序、h5/h10、summary → reproducibility → readiness → acceptance；没有把一个 caller-owned `run_fold`/全序列 callback 作为字段。
- `SuccessorStageContext.artifact_roots` 和 `make_project_stage_runner` 将 receipt verifier/StageRunner 的 root alias 固定为 `PROJECT`，专业 stage root 必须位于 PROJECT 内。
- 依赖字段在 `SuccessorProductionDependencies.__post_init__` 和 concrete adapter 构造期检查；缺依赖在 stage callback 前失败，静态上满足“先 fail closed、后不写 artifact/terminal”的方向。
- canonical JSON、解析时 canonical-byte 比较、同目录临时文件、hardlink no-clobber 和冲突字节拒绝均有代码路径；receipt/output 的 symlink、reparse、普通 hardlink 和未知普通文件有 fail-closed 路径。
- 已存在 terminal 且 `resume=True` 时，`run_two_fold_successor` 直接 fresh verify，不调用 fold/gate run 方法；但 callback 在 terminal 不存在时是否真正不重启 worker，静态合同无法证明。
- runtime identity 会写入 terminal，并在 replay 时与 request 比较；identity drift 的拒绝路径存在。但三个 fingerprint 只是 caller 注入的 64-hex 字符串，没有代码证明其确实来自当前代码、依赖或 provider runtime。

## 4. Findings

### F-1 [P1] 受控树只闭合普通文件，允许预先存在的空目录

**状态：Confirmed；这是本审查新增、交付报告未列出的对抗反例。**

- 证据：`successor_runtime.py:1929-1934` 只比较 `actual_files` 与 `expected_files`；`successor_runtime.py:1948-1986` 虽然把目录记录为 `D`，却没有把实际目录集合与允许目录集合比较。
- 违反不变量：任务单要求完整 controlled output tree closure，extra paths 必须 fail closed。
- 最小推演：在首次运行前创建 `controlled_output_root/rogue-empty/`，不放任何文件。扫描只多出一个 `D`，`actual_files` 仍可与 expected files 相等；该目录被纳入 tree digest，terminal 发布后 replay 看到同一目录，因而仍可 fresh verify。实现报告覆盖了 unknown file，但没有覆盖该空目录反例。
- 必须条件：发布前比较完整 entry/path 集合，或至少拒绝所有不属于 receipt/output 必需祖先目录的目录；增加“预先存在的空 extra directory”回归测试。

### F-2 [P1] concrete production boundary 没有强制返回真实 PROJECT-only StageRunner

**状态：Confirmed static gap；在真实 bridge verifier 是否额外拒绝属于 unproven。**

- 证据：`successor_runtime.py:497-502` 的 factory 返回 `Any`；`successor_runtime.py:589-606` 只验证 `stage_runner_type` 本身是 type；`successor_runtime.py:1002-1014` 接受 factory 返回值而没有 `isinstance` 或 artifact-root 校验。
- 违反不变量：任务单要求复用既有 `StageRunner`/root-topology；`stage_runner_type` 不能只是未使用的声明字段。
- 最小推演：注入 `stage_runner_factory=lambda **_: object()`，再注入会忽略 `runner`、直接生成合法 receipt refs 的窄 callbacks。adapter 仍可继续进入 receipt/tree/terminal 流程；代码没有在 runner 边界 fail closed。确定性 fixture 的 substitute 不构成真实 StageRunner 证据。
- 必须条件：将 factory 绑定到允许的真实 StageRunner 构造，至少校验返回对象类型及其 `artifact_roots == {"PROJECT": project}`；禁止 production public bundle 通过任意 caller-supplied type/callback 绕过该绑定，并补 adversarial test。

### F-3 [P1] fold/gate receipt 的关键 identity 没有由 package runtime 完整 join

**状态：Confirmed static gap；实际外部 verifier 是否补齐约束为 unproven。**

- 证据：`successor_runtime.py:1466-1501` 检查 stage/scope，但没有把 snapshot receipt 的 `scope_key` 与 `execution.snapshot_id` 相等；`successor_runtime.py:1544-1585` 对 reproducibility 只检查 `(fold, horizon)`、stage 和 scope，没有检查 `scope_key == 对应 WorkIdentity.work_key`，summary 也没有检查 `scope_key == experiment_key`。
- 进一步证据：`successor_runtime.py:1593-1603` 的 `_lookup_refs` 完全忽略 `executions` 和 `known`，只返回 caller/adapter 提供的 refs。
- 违反不变量：terminal 必须绑定两个 fold 的 snapshot/work identity 及各 Gate 的真实 receipt closure，而不是仅绑定形状正确的 ID。
- 最小推演：构造 bytes 有效、fold/horizon 正确、stage/scope 正确但 `scope_key` 为错误 64-hex 的 reproducibility refs；现有 package checks 可通过。若注入的 generic fresh verifier 只返回匹配的 `GateVerification`，错误 work identity 会进入 terminal。
- 必须条件：对 snapshot、experiment、work、summary、reproducibility、readiness、acceptance 逐项建立期望 scope-key/identity 映射，并在 terminal-level 独立校验；不能把该不变量完全外包给任意 callback。

### F-4 [P2] fresh gate verifier 收不到 terminal 的 fold/prior-gate 上下文

**状态：Confirmed interface mismatch；真实 verifier 能否仅凭单个 gate 完成同等校验为 unproven。**

- 证据：`SuccessorProductionGateVerifier` 在 `successor_runtime.py:564-576` 声明接收 `folds` 和 `prior_gates`；但 concrete `verify_gate` 在 `successor_runtime.py:984-997` 固定传入 `folds=()`、`prior_gates=()`。replay 的 `verify_terminal_attestation` 也只能通过窄 `GateVerifier(gate, context)` 调用。
- 违反不变量：fresh verification 应能重新证明跨 fold、跨 Gate 的所有权和顺序。
- 必须条件：传入从 attestation 重建的完整 folds/先前 gates，或把 verifier 合同收窄为明确、可证明只依赖单 gate 的 API，并由 runtime 自己完成跨对象 join。

## 5. 覆盖与阻塞边界

静态上已审查：adapter/factory 是否固定编排、PROJECT-only root、缺依赖先失败、terminal no-clobber/canonical/tree、runtime identity/replay、普通 hardlink/symlink/reparse/extra file、以及 terminal replay 不调用 worker。未能以执行证据确认：Windows 当前 Conda 的合法多 hardlink 正向能力、真实 StageRunner/API binding、真实 receipt schema、真实 provider/runtime fingerprint、真实 worker resume 语义、空目录反例和上述外部 verifier 补充约束。

## 6. 压缩结论与 dispatch outcome

`M3-G8F-R1-REVIEW`：**STATIC_DONE/STOP（概念性 dispatch outcome）**。

这是静态审查完成并保持 durable STOP，不是 implementation approval，不是 Gate 通过，也不是 submit/merge 授权。应先修复 F-1 至少以及 F-2/F-3 的 boundary/identity 缺口，再由授权窗口重新执行独立验证；在此之前 exact5 禁止 submit、merge、actual worker。

## 7. REWORK2 corrected review（追加，不改写原 F1-F4 历史）

### 7.1 身份、稳定性与边界

- logical task：M3-G8F-R1-REVIEW-REWORK2
- reviewer identity：01a031ff-0056-7c42-8dfc-0a704f1d5824
- implementation binding agent（任务提供）：01a02f38-f8ff-7080-a0a5-53e8b328e66f
- worktree：F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime
- branch / HEAD：codex/m3-g8f-successor-runtime / ac57ce9e40dc6731e1106b2fa2398f4013fa19da

审查前后两次 Git 读取的 branch、HEAD、tracked diff、worktree 状态和 exact5 object hash 相同；未发现 Git worktree lock 或源文件漂移。当前 exact5 hash 为：生产模块 cca04cc66fae7565d6082b9520f1c5b8a0e977ba，unit 497c2f6bab867bb46b39c57e1c50f84deb1f85e9，integration 0d3251275d883a070e69bd9a0062b6ececaf28f3，任务单 0c6f1dd79483d5755b146a6d210332ff95a4a94e，交付报告 f40c83a531d596e08eb3b642fdfb56d92c7948f7。未读取 mapping、status 或 attestation。

本轮只重新读取 exact5；未运行 Python、pytest/collection、Ruff、mypy、cold import、worker、retained、network、browser、SQLite、real I/O 或 commit。原报告 F1-F4、此前 validation/environment failure 事实和 STATIC_ONLY 边界均保留。

### 7.2 F1：complete entry/directory closure

- 现象：REWORK1 已把实际目录项加入闭包；_controlled_tree_sha256 在 successor_runtime.py:2072-2086 同时比较文件集合、receipt/output 父目录集合和 _CONTROLLED_RUNTIME_DIRECTORIES/受限 .stage-locks/<hex> 形态。_walk_controlled_tree 在 2121-2159 仍拒绝 symlink/reparse、普通 hardlink、隐藏未知项和临时项。
- 根因：原实现只检查普通文件；本次修复增加 actual_directories 与允许目录集合。
- 规则：receipt/output 所需父目录和既有 StageRunner 运行时目录可存在；未知空目录必须 fail closed，且不得误伤显式允许目录。
- 最小复现：integration test_terminal_rejects_unknown_empty_directory（tests/integration/test_m3_successor_runtime.py:682-699）在已生成 terminal 后创建 unknown-empty/，沿 verify_terminal_attestation → _verify_controlled_tree → _controlled_tree_sha256 进入实现路径并要求 SUCCESSOR_TERMINAL_INVALID。
- 通过条件/结论：对未知空目录的静态路径 PASS；显式列出的 .stage-locks、.stage-tmp、snapshots、snapshot-requests、receipts 目录及合法 lock-directory 形态不会被该 allowlist 拒绝。由于 StageRunner 源码和运行均不在 exact5/STATIC_ONLY 范围内，完整“真实 StageRunner 所有合法目录”仍是未执行证据，不把它表述为代码验证通过。

### 7.3 F2：真实 StageRunner、factory identity、PROJECT-only root 与 callback bypass

- 现象：StageRunner 子项已收紧：SuccessorProductionDependencies.__post_init__ 在 successor_runtime.py:753-774 要求 factory 身份必须是 make_project_stage_runner；adapter 构造在 821-827 要求真实 orchestration.StageRunner；_runner 在 1036-1068 再检查 exact type、_stage_root 和 _artifact_roots == {"PROJECT": context.project_root}。
- 根因：原实现允许任意 factory/object；这些检查已覆盖该旧反例。
- 规则：production adapter 只能使用既有 factory、真实 StageRunner 和精确 PROJECT root；不得以任意 callback/object 替换现有 public M3 API。
- 新静态对抗反例：SuccessorPublicApiBundle 在 597-650 只检查字段可调用；adapter 在 786-833 接受 caller 提供的任意 bundle，只要 stage_runner_type is StageRunner。因此可构造真实 StageRunner factory 加 stage_runner_type=StageRunner 的 marker bundle（integration 正常 fixture 本身在 75-106 构造 marker bundle，并在 546-550 注入），再让窄 run_upstream_stage/Gate callbacks 忽略 public API 直接发布合法 fixture receipts。构造不会因 public API 身份失败，StageRunner exact check 不能阻止业务 API bypass；交付测试只拒绝任意 StageRunner factory，没有拒绝任意 public API bundle。
- 通过条件：production 入口必须内部绑定 canonical make_public_successor_api_bundle()，或逐项验证现有 public builder/verifier 的不可替换身份；test substitute 必须与 production 入口隔离。仅检查 StageRunner 类型/root 不能证明完整 production API binding。
- 结论：StageRunner/factory/root 子项 PASS（静态结构）；no arbitrary callback/object bypass 整体 FAIL。

### 7.4 F3：scope_key join、_lookup_refs ownership 与物理 receipt reuse

- 现象：fold 侧已建立 snapshot/experiment/work join：successor_runtime.py:1566-1637 检查 snapshot→snapshot_id、experiment/features/labels（除 label-reconciliation 的 scope_key 外）→experiment_key、work→compute_work_key。_lookup_refs 在 1716-1739 现在确实消费 executions/known，并按 node_id 拒绝 fold/prior-gate/current-gate reuse。
- 根因：REWORK1 的“完全忽略上下文”问题已修复，但 gate scope contract 仍不完整，且 ownership key 仍只有 node ID。
- 规则：runtime 本身必须把 summary/reproducibility/readiness/acceptance refs 与 execution/work identity 建立可重算的 scope_key join；同一物理 receipt/path 不能用新 node ID 伪造第二份 ownership。
- 新静态对抗反例（实现报告未覆盖）：构造四个 reproducibility refs，fold/horizon/stage/scope 均正确，但每个 scope_key 使用任意、唯一的 64-hex，而非由 execution/work identity 可重算的值。_validate_gate_execution 在 1646-1713 对该 Gate 只检查 pair、stage、scope 和 scope_key 唯一性（1673-1687），未检查其与对应 WorkIdentity 或确定性 gate identity 的关系；_lookup_refs 也只检查 node ID。若 generic verifier 返回匹配 GateVerification，runtime 自身可继续构建 terminal。
- 新增物理复用反例：两个 fold-specific features refs 使用不同 node ID/fold，但相同 relative_path、receipt bytes/digest、stage、scope_key。_lookup_refs 不覆盖 fold-to-fold ownership；_unique_refs 和 attestation ownership 在 1989-1996、1941-1950 只按 node ID 去重，_verify_receipts 会重复读取同一 physical receipt，tree 的 file set 也会折叠同一路径。
- 通过条件：为每个 gate 定义并在 runtime 内实现确定性 scope_key→fold/horizon/work/experiment join；全局按 canonical receipt path/bytes/semantic owner 检查物理复用，除明确、受限的共享节点外拒绝 alias node。现有 work-scope drift 测试（725-737）和 node-ID reuse 单测（143-183）不能覆盖上述两个新反例。
- 结论：_lookup_refs 消费上下文并拒绝 node-ID reuse 子项 PASS；完整 scope_key/physical ownership join FAIL。

### 7.5 F4：首次执行与 fresh replay 的 reconstructed context

- 现象：首次 Gate verify 在 successor_runtime.py:1312-1318、1332-1338、1356-1362、1381-1387 传入当前 folds 与正确 prior prefix；terminal replay 在 1458-1468 从 attestation 重建 executions，并按 Gate 顺序累积 prior gates；concrete adapter 在 1013-1034 将二者传给 dependency verifier。
- 根因：原实现传空 folds/prior-gates；本次 contract 与 replay loop 已修复。
- 规则：summary、reproducibility、readiness、acceptance 必须分别收到两 fold 和 (), (summary), (summary,reproducibility), (summary,reproducibility,readiness)。
- 最小复现：test_fresh_gate_verifier_requires_reconstructed_fold_and_prior_context（tests/integration/test_m3_successor_runtime.py:740-764）设置严格断言，并要求 gate_contexts == expected + expected，对应首次验证和 replay 两轮实现路径。
- 通过条件/结论：PASS（静态路径）；该测试未执行，不构成 executable verification。

### 7.6 四类新增测试是否到达实现路径

- F1 到达 terminal fresh verification/tree closure；但只有未知目录负例，没有合法 StageRunner runtime-directory 正例。
- F2 bypass 测试到达 dependencies/adapter 构造期身份拒绝；正常路径到达 _runner，但 public API 使用 marker substitutes，且没有测试任意 public bundle 被拒绝。
- F3 work drift 到达 concrete adapter 的 _validate_fold_execution；unit ownership test 直接到达 _lookup_refs；没有 reproducibility scope-key drift 或 physical receipt alias 测试。
- F4 到达首次 Gate verify 和 terminal replay 两条路径，严格上下文断言覆盖两轮。

## 8. REWORK2 static review outcome

REVIEW_FAIL（仅表示本轮 STATIC_ONLY 静态审查结果；不表示 Gate 通过、代码可执行验证通过或 submit/merge approval）。未满足 F2 的完整 production API binding 和 F3 的完整 gate/physical receipt identity closure；exact5 继续禁止 submit、merge 和 actual worker。

## 9. REWORK3 corrected independent review

任务：M3-G8F-R1-REVIEW-REWORK3；continuation_of：M3-G8F-R1-REVIEW-REWORK2；triggered_by：M3-G8F-R1-REVIEW-REWORK2。reviewer identity 保持 01a031ff-0056-7c42-8dfc-0a704f1d5824；不创建新 reviewer、外部 Cursor、top-level task 或 worktree。

### 9.1 identity、稳定性与证据边界

- target worktree 为 artifacts/dev_worktrees/m3-g8f-successor-runtime；HEAD 精确为 ac57ce9e40dc6731e1106b2fa2398f4013fa19da；branch 精确为 codex/m3-g8f-successor-runtime。
- REWORK3 开始与写入前两次 Git 只读检查均显示 tracked diff 为空、cached diff 为空；exact5 内容哈希在重读后保持不变：
  - successor_runtime.py：99d90cabb270e93fb11a35b89b53a955e3cc6ac8
  - unit test：68aeb804fc47898163bf320c88ac7a73c34de2d5
  - integration test：69f9b382aba6e42b0fd549494805b0be8247aada
  - 任务单：865e25da2aaa0518fd54c34f26ccb402f827ff1e
  - 交付报告：734b317c68a7100319e212bff92070b2d6ab3e80
- 本节只重读 exact5，并只写入本报告；没有读取或修改 mapping/status/attestation。没有运行 Python、pytest/collection、Ruff、mypy、cold import、CPU、worker、retained、network、browser、SQLite、real I/O 或 commit。
- 原始 collision、初验 F-1 至 F-4、REWORK2 事实全部保留，包括两次 validation attempt 为 carrier/import environment failure、第二次 identity preflight -c payload 被截断为 from、没有 unit/integration/Ruff/mypy/cold code evidence；这些历史事实没有被本节改写。当前 M3-G8F-R1 仍是 STATIC_ONLY durable STOP，exact5 仍禁止 submit、merge、actual worker。

### 9.2 REWORK3-F2：canonical public API binding 与 test substitution isolation

- 现象：REWORK2 的风险是 production adapter 可接受 stage_runner_type 正确但 builder/verifier 全为 marker 的 caller bundle；若仍存在，会让窄 callback 替代完整生产 API。
- 根因（已修复的旧根因）：旧入口直接采用 caller bundle；当前 ProductionSuccessorStageAdapter.__init__ 在 successor_runtime.py:978-996 先无条件内部调用 make_public_successor_api_bundle，再把内部结果保存为唯一 self._public_apis。successor_runtime.py:789-815 的 _require_canonical_public_api_bundle 对 exact bundle type、StageRunner type、run_plan_builders 的键和值以及全部十二个 public callable 字段逐项使用对象 identity 检查，不是仅检查 callable。
- 应遵循规则：production entry 必须内部绑定当前既有 API；可选 caller bundle 只能是该 canonical bundle 的 exact identity closure；测试 substitute 只能隔离替换 canonical binding，不能以任意 marker bundle 作为 production 参数进入。
- 最小复现与静态路径：以 integration test:785-799 的 marker bundle 传给 make_production_successor_stage_adapter，而不 monkeypatch make_public_successor_api_bundle。构造进入 successor_runtime.py:950-998，内部 canonical bundle 与 marker bundle 在 797-810 的逐项 identity closure 上不相等，随后以 SUCCESSOR_INPUT_INVALID 返回；测试还在 797-799 检查 terminal/receipts/artifacts 均未出现。真实 runner 入口另由 successor_runtime.py:1199-1231 检查既有 StageRunner exact type、factory identity、_artifact_roots 精确等于 {"PROJECT": context.project_root} 和 stage-root closure。
- 通过条件：任意 marker、局部替换、mapping 增删或 callable wrapper 在 receipt/artifact/terminal 写入前被拒绝；无 caller bundle 时 adapter 仍持有内部 canonical bundle。源代码控制流满足；未执行，因此执行层仍 UNPROVEN。
- test-only isolation：integration test:583-603 的 monkeypatch 只替换测试期间 runtime.make_public_successor_api_bundle；正常 _run/test helper 在 integration test:606-620 不向 production entry 传入 public_apis；独立的 marker rejection test:785-799 不使用该 monkeypatch。故静态上 marker fixture 与 caller injection 已分离，测试 reaches adapter constructor，而不是只验证 fixture object。交付报告:130-137 与任务单:116-123 对同一边界一致。
- 边界说明：run_two_fold_successor 在 successor_runtime.py:1405-1424 仍保留窄 SuccessorStageApi protocol 作为可测试的通用编排入口；本结论只把 make_production_successor_stage_adapter/run_production_two_fold_successor 作为 production boundary。若上层另行要求任何直接调用通用 protocol 的路径也必须被生产 adapter 封锁，则需扩大合同并另行返工；当前 exact5 的任务单将该 protocol 保留为 runtime/test boundary，故不把它误报为本轮 F2 失败。

### 9.3 REWORK3-F3：deterministic Gate identity 与 scope joins

- 现象：REWORK2 的风险是 reproducibility refs 只要拥有四个正确 fold/horizon 且 scope_key 各自唯一即可通过；summary、reproducibility、readiness、acceptance 的 scope join 没有全部由 execution/work/prior-gate identity 重算。
- 根因（已修复的旧根因）：successor_runtime.py:386-457 现在集中定义 deterministic gate identity/scope functions。summary 使用唯一 shared experiment_key；reproducibility 对每个 fold/horizon 取对应 WorkIdentity.work_key；readiness 使用该 fold 的完整 execution join 与 prior-gate identity 前缀；acceptance 使用 deterministic acceptance gate identity。successor_runtime.py:1817-1889 同时校验 gate identity、形状、stage/scope、每个 ref 的 fold/horizon 与重算出的 scope_key。
- 应遵循规则：Gate identity 必须是固定版本、fold execution/work identity 和正确 prior-gate prefix 的 canonical hash；scope_key 必须按 gate contract 与 execution/work identity 可重算，不能接受任意唯一 64-hex。
- 最小复现与静态路径：integration test:817-829 打开 drift_reproducibility_scope，使 test boundary 在正确 fold/horizon/stage/scope 形状下写入 _hex("drifted-repro:...")，而非 successor_runtime.py:412-438 计算的 work join。_run 通过 production adapter 进入 successor_runtime.py:1233-1272，再在 1258-1263 调用 _validate_gate_execution；当前实现应以 SUCCESSOR_GATE_FAILED 拒绝且不发布 terminal。该测试不是只构造 validator fixture，而是进入 concrete adapter/factory 的 gate path；未执行，故结果为静态确认、运行结果 UNPROVEN。
- 通过条件：summary/reproducibility/readiness/acceptance 的 identity 与 scope join 均可从当前 folds、WorkIdentity、prior gates 唯一重算；scope drift 在下游 terminal 构建前稳定 fail closed。静态代码闭包满足；无 pytest/代码执行证据。

### 9.4 REWORK3-F3：global physical path、bytes digest、semantic owner 与 shared-node exception

- 现象：REWORK2 的风险是不同 node_id 可以指向相同物理 receipt path、相同 receipt bytes 或相同 semantic owner；node-id 去重本身不能闭合 receipt ownership。
- 根因（已修复的旧根因）：successor_runtime.py:2179-2242 的 _validate_global_receipt_ownership 为全部 fold/gate refs 同时建立 by_node、canonical resolved physical path、bytes SHA256 与 semantic owner(stage, scope, scope_key, fold, horizon) 索引；successor_runtime.py:2259-2288 的 _unique_refs 也保留 path、bytes、owner、node 四重去重。_build_attestation 在 successor_runtime.py:1974-1985 发布前调用 global check；terminal replay 在 successor_runtime.py:2126-2130 的 attestation binding 中再次调用，故不是只在首次写入检查。
- 应遵循规则：全局 physical path、receipt bytes digest、semantic owner 和 node_id 必须唯一；唯一例外只能是同一 exact node/ref 在两个 fold 中、fold=None、stage 属于显式 _SHARED_RECEIPT_STAGES 的 shared cross-fold node。successor_runtime.py:2245-2257 没有放宽到 gate、不同 node、fold-specific ref 或任意同值 refs。
- 最小复现与静态路径：integration test:832-844 打开 alias_physical_receipt，使两个 fold 产生不同 node_id 却复用 output/stage/receipts/features/shared-alias.json 和同一 output path/bytes；_run 进入 production adapter 并在 _build_attestation 的 global ownership closure 失败，期望 SUCCESSOR_TERMINAL_INVALID 且无 completion。unit test:187-211 另以不同 node_id、相同 path、相同 sha256 和相同 semantic owner 直接击中 _unique_refs 的 path/bytes/owner 分支。两项测试分别覆盖 concrete production path 与 helper-level closure；未执行，运行结果 UNPROVEN。
- 通过条件：distinct node 的同 path、same bytes 或 same semantic owner 在 terminal publish/replay 前返回 SUCCESSOR_TERMINAL_INVALID；合法的同一 shared node 仅在上述显式 allowlist 下可跨两个 fold 重用。静态控制流与 allowlist 满足；没有 executable/Gate evidence。

### 9.5 reviewer-only 新对抗性反例（REWORK3-A1）

- 现象：若只检查 physical path，攻击者可把已有 receipt bytes 复制到第二个不同路径，再伪造不同 node_id；path 不冲突但 bytes digest 发生跨 node alias。该反例没有出现在实现者列出的 REWORK2 两个 integration/unit 测试中。
- 根因：脆弱实现以 node_id 或 path 单键去重，忽略 receipt bytes digest 的全局语义；这会让两个物理文件看似不同而实际证明同一份 receipt bytes。
- 应遵循规则：global receipt ownership 必须在 distinct physical path 之间也拒绝同一 bytes SHA256，除非是同一 exact shared node 的窄例外。
- 最小复现/推理：构造 ref-a(node-a, receipts/a.json, sha256=X) 与 ref-b(node-b, receipts/b.json, sha256=X)，令两者 fold/scope/owner 均为各自合法但 node_id 不同，并把它们放入同一 folds/gates 集合；_validate_global_receipt_ownership 的 by_bytes 分支 successor_runtime.py:2200-2224 应在 terminal build 前拒绝，即使 by_path 不冲突。
- 通过条件：返回 SUCCESSOR_TERMINAL_INVALID、completion.json 不生成；同一 exact shared node 仍按 2245-2257 的窄条件保留。静态代码已显示该反例被 by_bytes 覆盖，但没有 Python/pytest 执行证据，标记为 STATIC_CONFIRMED / EXECUTION_UNPROVEN。

### 9.6 findings/evidence 压缩结论

- CONFIRMED STATIC: REWORK3 F2 canonical internal binding、exact callable identity closure、marker caller bundle rejection 与 test-only substitution isolation；F3 四类 Gate identity/scope join、reproducibility scope drift fail-closed path、global path/bytes/semantic-owner/node closure，以及 narrow shared-node exception。
- UNPROVEN: 所有测试实际运行结果、真实 orchestration.StageRunner import/constructor 行为、真实 public M3 API 行为、receipt schema 在真实 worker 中的闭包、Windows hardlink/reparse 原语、CPU/Gate/actual worker/retained/network/Linux 证据。
- BLOCKED BY CONTRACT: 不得执行上述命令或 I/O；历史两次 validation carrier/import failure 与被截断的 identity preflight -c payload 仅作为既有事实保留，不能补写成代码验证。

## 10. REWORK3 static review outcome

REVIEW_PASS（仅表示 exact5 的 STATIC_ONLY 独立审查在本轮 F2/F3 范围内通过；不表示 executable verification、Gate 通过、submit/merge approval 或 actual-worker 授权）。M3-G8F-R1 继续保持 STATIC_ONLY durable STOP，直至授权窗口完成独立的 focused validation 与主 Agent 终验。

## 11. REWORK4 narrow static re-review：Path concrete subclass guard

任务：M3-G8F-R1-REVIEW-REWORK4；reviewer identity 保持 01a031ff-0056-7c42-8dfc-0a704f1d5824。本节是 REWORK3 的延续，只复核 executable feedback 定位的 Path 类型守卫；collision、初验 F-1 至 F-4、REWORK2、REWORK3 和此前所有事实均保留，不删除、不改写。

### 11.1 identity、稳定性与静态证据边界

- worktree：F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime
- HEAD：ac57ce9e40dc6731e1106b2fa2398f4013fa19da
- branch：codex/m3-g8f-successor-runtime
- 实现/测试/任务单/交付报告重读前后 tracked diff 与 cached diff 均为空；exact5 哈希稳定：
  - src/quant/research/m3/successor_runtime.py：09bac9a3ff96977cb853753fa4cc78a4a167099f
  - tests/unit/test_m3_successor_runtime.py：68aeb804fc47898163bf320c88ac7a73c34de2d5
  - tests/integration/test_m3_successor_runtime.py：6dde2595acb1b48cb52f3accb432578955154ade
  - taskbook：a8f29fb58b9119ecd969617097eb73a00c7a820c
  - delivery report：924eaa17508b1b4ca491c4d2414101c2cd288f1c
- 本节只读取 taskbook、delivery report、taskbook 指定的 implementation/unit/integration exact5；只写本报告。没有运行 Python、pytest、Ruff、mypy、cold import、CPU、worker、retained、network、real I/O 或 commit。

### 11.2 REWORK4-F1：concrete Path acceptance with exact root closure

- 现象：此前 identity preflight PASS、focused unit 7 passed，但 pre-fix focused integration 只有 4 passed、8 failed；失败集中在真实 StageRunner 将平台具体 WindowsPath/PosixPath 交给 successor runtime 后，被最终类型守卫误判为 SUCCESSOR_INPUT_INVALID。
- 根因：旧 guard 使用 type(actual_stage_root) is not Path，把 Path 的 concrete platform subclass 当成非法值。
- 应遵循规则：actual_stage_root 必须满足 isinstance(actual_stage_root, Path)，以接受 WindowsPath 和 PosixPath；同时必须继续满足 roots 的 exact PROJECT-only mapping，以及 actual_stage_root == stage_root 的 exact stage-root equality。非 Path 和 root mismatch 必须 fail closed，不能通过放宽 equality 或 root registry 绕过。
- 实现证据：successor_runtime.py:1199-1231 先要求既有 make_project_stage_runner identity、真实 StageRunner exact type，并在 1222-1229 检查 type(roots) is dict、roots == {"PROJECT": context.project_root}、isinstance(actual_stage_root, Path) 和 actual_stage_root == stage_root。修复只改变 Path 类型判定，未削弱 PROJECT-only 或 equality 条件。
- 最小复现：integration test_m3_successor_runtime.py:785-804 通过 concrete adapter/factory 取得真实 runner，要求 isinstance(actual_stage_root, Path)、type(actual_stage_root) is not Path 且 actual_stage_root == expected_stage_root；随后 807-840 用同一 real factory 派生 runner，分别把 _stage_root 改为 str(stage_root) 和 stage_root / "unexpected"，并调用 adapter._runner。
- 通过条件：平台 concrete Path subclass 通过最终 guard；str(stage_root) 与 mismatched root 都以 SUCCESSOR_INPUT_INVALID 拒绝；PROJECT-only roots 与 exact stage_root equality保持不变。静态控制流满足该条件。

### 11.3 new integration adversary reaches the implementation guard

- 现象：新增 adversary 不能只检查 fixture 类型，必须真正进入 production adapter 的 _runner。
- 根因：若测试仅在 helper 层断言 Path，无法证明生产 factory 返回对象经过 successor_runtime.py 的最终 guard。
- 应遵循规则：测试必须通过 make_production_successor_stage_adapter、真实 StageRunner factory 和 adapter._runner；正向 concrete subclass、非 Path、root mismatch 三条路径都要观察稳定边界结果。
- 最小复现/路径：integration:785-795 构造 request、安装仅测试侧的 fixture binding、调用 _adapter(boundary)，随后直接调用 adapter._runner；integration:805-840 替换依赖 factory，仍由 ProductionSuccessorStageAdapter._runner 在 source:1199-1231 执行 roots/type/equality 守卫。非 Path 与 mismatch 两次都断言 SUCCESSOR_INPUT_INVALID，且不是只断言 fixture 变量。
- 通过条件：正向 concrete Path subclass 不被误拒绝；非 Path 与 mismatched root 均 fail closed；测试不扩大到实际 worker 或 Gate。静态路径满足；该测试本轮未执行。

### 11.4 validation evidence honesty

- taskbook:140-147 与 delivery report:161-168 明确记录修复内容、最小复现、新测试和通过条件；没有把修复后的测试写成已通过。
- taskbook:149-153 与 delivery report:170-174 明确保留已有可执行反馈：identity preflight PASS；focused unit 7 passed；pre-fix focused integration 4 passed / 8 failed；8 failures 均为旧 Path 类型误拒绝；post-fix integration 未运行。
- 因此本轮可确认的是“证据记录诚实且没有把 unrun post-fix 转写为 PASS”。本轮没有重跑 identity、unit 或 integration，也没有新增 executable evidence；不能把静态检查升级为 post-fix integration PASS、Gate PASS 或 code execution approval。

### 11.5 remaining gap and narrow outcome

- 唯一剩余 gap：修复后的 focused integration 尚未执行，故 WindowsPath/PosixPath 正向路径与两个负向 adversary 的运行结果仍为 UNPROVEN；CPU、Ruff、mypy、cold import、actual worker、retained、真实 acceptance、Linux/network 也仍不在本 STATIC_ONLY review 范围。
- 静态结论：REVIEW_PASS（仅针对 REWORK4 的 Path concrete subclass guard、exact stage_root equality、PROJECT-only roots 和新 adversary 的静态闭包；不表示任何 executable 或 Gate 验证）。

## 12. REWORK4 DELIVERY_READY review path

DELIVERY_READY review path：可以交回授权窗口执行 post-fix focused integration；在该命令实际完成并由主 Agent 终验前，M3-G8F-R1 仍保持 STATIC_ONLY durable STOP，不得据此宣称 Gate 通过、submit/merge approval 或 actual-worker 授权。

## 13. REWORK5 DIAGNOSTIC2 narrow static re-review：fixture canonical labels route

任务：M3-G8F-R1-REVIEW-REWORK5；reviewer identity 保持 01a031ff-0056-7c42-8dfc-0a704f1d5824。本节仅复核 DIAGNOSTIC2 root cause 与 REWORK5 fixture/test contract；collision、初验、REWORK2、REWORK3、REWORK4 及此前所有历史事实保留，不删除、不改写。

### 13.1 identity、稳定性与范围

- worktree：F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime
- HEAD：ac57ce9e40dc6731e1106b2fa2398f4013fa19da
- branch：codex/m3-g8f-successor-runtime
- REWORK5 开始、exact5 重读后和写入前 tracked diff/cached diff 均为空；implementation source 在本轮未改变，哈希始终为 09bac9a3ff96977cb853753fa4cc78a4a167099f。
- 本轮 exact5 最终哈希：unit 68aeb804fc47898163bf320c88ac7a73c34de2d5；integration 0c2875e6dc90531c9e3be6fb734801d5aeb972d0；taskbook b6918347ba529e297176ed8fc34ec998a48c34c2；delivery a481ebafc96100180e43a6ee3288b834a9ec13da。
- 只读取 taskbook、delivery report、implementation、unit test、integration test；只写本报告。没有运行 Python、pytest、Ruff、mypy、cold import、actual worker、retained、network、real I/O 或 commit。

### 13.2 REWORK5-F1：fixture route 正确，但 adversarial proof 不足

- 现象：integration:256-269 的 _builder_name 已把 labels 显式映射到 folds，其他 work stages 仍映射 work，label-reconciliation 落回自身；因此修复后的静态 route 字符串符合 DIAGNOSTIC2 根因。可是新增 test_labels_routes_to_canonical_folds_builder_not_labels（integration:862-873）没有调用 run_upstream_stage，也没有真正从 production adapter 进入 successor_runtime.py:1017-1031/依赖 callback 的 lookup。
- 根因：_public_api_substitutes（integration:75-106）用同一个 marker callable 填入 folds、label-reconciliation 和其他所有 run_plan_builders。新测试的断言 run_plan_builders[builder_name] is run_plan_builders["folds"] 在 builder_name == "folds" 时只是同一 mapping 项的自比较；它不能区分 folds callable 与 label-reconciliation callable，也不能证明实际 lookup 使用了 folds 项。labels key absent 的断言本身有效，但其余两项 adversarial proof 没有被建立。
- 应遵循规则：fixture 只能把 labels 映射到 canonical folds key；labels key 必须不存在；实际 lookup 必须取 exact folds callable；label-reconciliation 必须保持独立 key 且使用独立 callable/可观察调用路径。测试必须触达 run_upstream_stage 的 builder lookup，而非只检查 _builder_name 字符串和 fixture mapping。
- 最小复现/推理：当前 integration:75-106 令所有 builder values 为同一 marker；即使将 folds 与 label-reconciliation 的 marker 替换为两个不同 sentinel，现有 test:862-873 仍只会检查 labels 不在 mapping、builder_name 为 folds 和 folds 项自相等，仍不会调用 run_upstream_stage。因此一个错误的 fixture lookup 实现或 label-reconciliation 与 folds 误共用 callable，当前测试都可能无法暴露。应增加 distinct folds_builder 与 label_reconciliation_builder，并通过实际 run_upstream_stage（或等价的真实 lookup 入口）记录/断言 labels 只调用 folds_builder、label-reconciliation 只调用其独立 builder。
- 通过条件：生产 runtime source 保持不变；fixture 的 labels route 使用 canonical folds key；test 明确证明 labels key 缺失、实际 lookup 返回/调用的对象是独立定义的 folds callable，并证明 label-reconciliation 仍查找和调用独立 callable；测试路径进入 run_upstream_stage/adapter boundary。当前 source route 静态满足，但 new adversarial test proof 不满足。

### 13.3 taskbook/delivery traceability 与 unrun honesty

- taskbook:155-168 和 delivery:195-206 对 DIAGNOSTIC2 的 KeyError(labels)、canonical folds route、label-reconciliation 独立性和新测试名称进行了可追溯记录；两份文档也明确生产 runtime source 本轮不改。
- taskbook:168 与 delivery:208-210 明确声明 DIAGNOSTIC1/2 是外部反馈，本轮及修复后的 focused unit/integration、Ruff、mypy、cold import、CPU 均未运行；没有把 post-fix 结果写成 PASS，也没有宣称 Gate/真实 acceptance。
- 但 delivery:205-206 将新增测试概括为已证明实际 lookup 使用 canonical folds callable；上述静态检查表明该表述超出测试本身的证明力。应在不改生产 runtime 的前提下补强 fixture/test 后，再重新记录该 traceability claim。

## 14. REWORK5 static review outcome

REVIEW_FAIL（仅针对本轮窄范围 fixture/test 静态合同；生产 runtime 未被修改且 route 字符串修复方向正确，但新增 adversarial test 尚未证明 exact folds callable lookup 与 label-reconciliation 独立调用）。本结论不表示任何 executable verification 或 Gate 结果；exact5 继续禁止 submit、merge 和 actual worker，直至测试证明缺口被修复并由授权窗口实际验证。

## 15. REWORK6 独立静态复审：fixture callable lookup 闭环

### 15.1 身份、范围与稳定性

- 本节继续使用 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REVIEW-REWORK6`；未创建 reviewer、实现 agent、外部 Cursor、top-level task 或 worktree。
- 复核范围仍是 exact5：`successor_runtime.py`、unit/integration tests、任务单和交付报告；仅追加本报告。HEAD 为 `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`，branch 为 `codex/m3-g8f-successor-runtime`。
- 两次深读前快照及一次写入前快照完全一致：production `successor_runtime.py` `09bac9a3ff96977cb853753fa4cc78a4a167099f`；unit `68aeb804fc47898163bf320c88ac7a73c34de2d5`；integration `589af2ca42f3923eb38ef25768d8c4e99642b336`；taskbook `0d64fe728289e058e519b913f480aa6f7e7c9304`；delivery `1c937ecfd671e3e6120f8458c2eaa1aba6082655`。因此本轮没有 exact5 并发漂移；production source 也未改变。
- 本节是 STATIC_ONLY 复核。未运行 Python、pytest/collection、Ruff、mypy、cold import、CPU、worker、retained、network、SQLite、real I/O 或 commit；下述“到达”均为静态控制流证据，不是执行结果。

### 15.2 R6-1：REWORK5 的 shared-marker/self-comparison 缺口已静态闭环

- 现象：REWORK5 的测试可在 `folds` 自比较、所有键共享 marker、且没有进入 `run_upstream_stage` 时通过，不能排除 labels 错接或 label-reconciliation 复用 folds。
- 根因：fixture 没有可区分的 callable、返回 sentinel 和调用记录，断言只验证了字符串映射或同一对象自身。
- 应遵循规则：production route 必须是 `labels -> canonical folds`，`label-reconciliation -> canonical label-reconciliation`；测试替代 bundle 必须提供独立 callable 与可观察调用记录，并由 concrete adapter 的 `run_fold` 进入依赖的 `run_upstream_stage` lookup。任何错接或 shared marker 都必须使断言失败。
- 最小复现/反例：若 `_builder_name("labels")` 返回 `"labels"`，而 mapping 无该键，则 lookup 在 fixture line 313 失败；若 labels 取 `label-reconciliation`，记录不会是 `("folds", "labels")`；若 label-reconciliation 取 folds 或两键共享 marker，则 callable 身份或阶段记录不满足测试 line 899–925 的断言。仅把 `run_plan_builders["folds"]` 与自身比较不能发现这些变体。
- 静态证据：integration fixture lines 75–132 定义不同的 `folds_builder`、`label_reconciliation_builder`、两个不同 sentinel 和 `builder_call_records`；lines 285–315 将 labels 映射为 `folds` 后由 `run_upstream_stage` 索引 mapping 并调用选定 callable；lines 637–640 通过 `make_production_successor_stage_adapter` 构造 concrete adapter。adversarial test lines 891–925 断言缺少 `labels` key、folds 与 label-reconciliation callable 非同一对象，并直接调用 `adapter.run_fold`；其记录断言要求每个 horizon 的 labels 仅为 `("folds", "labels")`，label-reconciliation 仅为自身记录。
- 生产路径闭合：`successor_runtime.py` lines 1010–1047 的 `ProductionSuccessorStageAdapter.run_fold` 对 `_FOLD_HORIZON_PRE_FORMAL_STAGES` 逐 horizon 调用 `dependencies.run_upstream_stage`；该阶段表 lines 125–134 明确包含 labels 与 label-reconciliation。故测试调用在静态控制流上确实穿过 `adapter.run_fold -> boundary.run_upstream_stage -> run_plan_builders[...] -> builder`，不是仅测试 fixture 字符串。
- 通过条件：不修改 production runtime；labels key 不被索引，labels 只触发 folds callable；label-reconciliation 只触发独立 callable；删除/改写任一记录、改成 shared marker 或任一错误映射都使现有断言失败。以上条件在代码/测试文本上满足。

### 15.3 生产 binding、替代隔离与证据边界

- `successor_runtime.py` lines 817–887 的 canonical bundle 仍以 `"folds"` 绑定 `make_experiment_artifact_run_plan`、以 `"label-reconciliation"` 绑定独立 `make_label_reconciliation_run_plan`，不含 `"labels"`；lines 789–814 对候选 bundle 执行 exact callable identity closure。adapter lines 978–983 内部重绑 canonical bundle，测试替代只通过 integration `_install_fixture_verifiers` lines 630–634 作为静态隔离边界观察，未改 production source。
- taskbook REWORK6 lines 170–183 与 delivery REWORK6 lines 212–227 均记录了本轮 fixture/test-only 修复、上述 lookup 证据和验证边界；delivery 明确写出 focused unit/integration、Ruff、mypy、cold import、CPU、actual worker、retained、真实 acceptance、Linux/network 均未运行，`DELIVERY_READY` 不等于 Gate 或 executable acceptance。未将未运行证据表述为通过。
- 已确认：静态身份/稳定性、production source 未改、callable/record 分离、具体 lookup 路径、labels 缺失、错误/shared-marker 变体的拒绝理由、文档 traceability 和 unrun 声明。
- 未证明：任何 Python 断言实际执行、post-fix unit/integration 结果、Ruff/mypy/cold import、真实 worker/retained 或任何 Gate。该部分保持 blocked/unrun，不得由本节改写。

### 15.4 REWORK6 静态结论

REVIEW_PASS（仅表示本轮指定 fixture/callable-lookup 静态合同满足；不表示 executable verification、Gate 通过、实际 worker 可运行或可 submit/merge。exact5 的 post-fix 执行证据仍待授权验证。）

## 16. REWORK7 独立静态复审：horizon sentinel 缺省值闭环

### 16.1 身份、范围与稳定性

- 本节继续使用 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REVIEW-REWORK7`；未创建或复用其他 reviewer、实现 agent、外部 session、top-level task 或 worktree。
- worktree 为 `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`；HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch `codex/m3-g8f-successor-runtime`。
- 两次初始快照与一次写入前快照完全一致。当前 pre-write `git hash-object`：production `successor_runtime.py` `09bac9a3ff96977cb853753fa4cc78a4a167099f`；unit `test_m3_successor_runtime.py` `68aeb804fc47898163bf320c88ac7a73c34de2d5`；integration `test_m3_successor_runtime.py` `918b42768202834b012edf8ef5c2221e3273f8fb`；taskbook `4a3a67099b204ccecd3cd6ff6407e1942d00c642`；delivery `b77bc2bf94dc77ae427694e10691f70e051777d4`；本 review report（写入前）`21580222b6429577dd136d0afb8ae2c2bb3941af`。旧 REWORK6 中记录的历史哈希保持为历史事实，不被本节改写。
- production source 与 unit test 哈希均保持前一轮值，确认本轮零变化；REWORK7 变更只落在 integration fixture/test 及其任务/交付记录。仅追加本报告。
- 本节 STATIC_ONLY / zero Python：未运行 Python、pytest/collection、Ruff、mypy、cold、CPU、actual worker、retained、network、SQLite、real I/O 或 commit。

### 16.2 R7-1：`_effective_horizon` 的 `None` sentinel 语义

- 现象：VALIDATION3 外部反馈为 identity PASS、focused unit `7 passed`、focused integration `7 passed / 7 failed`；任务单记录共同首失败是 fixture 把 snapshot 的合法 `horizon=None` 改成 h5，随后 production `run_fold` 的 `_one_ref(..., stage="snapshot", horizon=None)` fail closed。
- 根因：旧条件只有 `horizon == self.omit_horizon`；默认 `omit_horizon=None` 时，合法输入 `None` 与默认配置相等，误触发替换。
- 应遵循规则：仅当 `self.omit_horizon is not None` 且输入 horizon 与其精确相等时返回 `HORIZONS[0]`；默认 `omit_horizon=None` 必须原样保留输入（包括 `None`）；显式 omit 与 `None` 输入不得匹配。
- 最小复现/反例：旧逻辑中 `default_boundary._effective_horizon(None)` 得到 h5；修复后 integration lines 234–237 的条件先检查 `self.omit_horizon is not None`。显式 `omit_horizon=10` 时输入 `10` 返回 `runtime.HORIZONS[0]`，输入 `None` 仍返回 `None`。
- 静态测试证据：integration `test_effective_horizon_requires_explicit_omit_setting` lines 773–782 覆盖默认 `None` 保持、显式 `10` 命中替换、显式 omit 配合 `None` 不替换；现有 `test_missing_h10_cannot_publish_terminal` lines 732–744 仍保留显式缺 h10 的 downstream 对抗路径。production source lines 1062–1063 仍要求 snapshot/experiment ref 的 horizon 为 `None`，且 production source 哈希未变。
- 通过条件：默认及未指定 horizon 的 stage 不被 sentinel 替换；显式 omit 只替换 exact matching horizon；VALIDATION3 的 snapshot `_one_ref` 不因 fixture 默认值误改而失败；production runtime、错误包装和 unit test 不改变。静态代码与测试文本满足。

### 16.3 文档 traceability 与验证边界

- taskbook REWORK7 lines 185–198 记录了现象、根因、规则、最小复现、新测试、通过条件及 `VALIDATION3` 的 `7 passed / 7 failed STOP`；delivery lines 231–254 保留 identity PASS、unit `7 passed`、integration `7 passed / 7 failed STOP`，并明确修复后 focused checks 尚未运行。
- delivery 同时明确未运行 Ruff、mypy、cold、CPU、actual worker、retained、真实 acceptance、Linux/network，`DELIVERY_READY` 不是 Gate 或 executable acceptance。未把外部 STOP 证据改写为 post-fix PASS。
- 已确认：exact5 稳定、production/unit 本轮零变化、fixture 条件满足三种 horizon 语义、测试与文档可追溯、unrun 边界诚实。
- 未证明：修复后 Python/test 实际执行结果、Ruff/mypy/cold/CPU、worker/retained/network/Linux 或任何 Gate。上述结果保持 UNPROVEN/未运行，不能由本节升级。

### 16.4 REWORK7 静态结论

REVIEW_PASS（仅针对 REWORK7 `_effective_horizon` fixture sentinel 合同、窄对抗测试和文档证据边界；不表示 executable、Gate 或 runtime 验证。）

## 17. REWORK7 DELIVERY_READY

DELIVERY_READY（仅表示本轮 exact5 静态交付可交回授权验证窗口；post-fix 执行和主 Agent 终验完成前，不得据此宣称 Gate 通过或实际运行成功。）


## 20. REWORK9 独立静态复审：regular-file link-count 平台守卫

### 20.1 身份、范围与稳定性

- 本节继续使用原 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REVIEW-REWORK9`；未创建或使用其他 reviewer、实现 agent、外部 session、top-level task 或 worktree。
- worktree 为 `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`；HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch `codex/m3-g8f-successor-runtime`。
- 两次初始快照与一次写入前快照完全一致。当前 exact5 `git hash-object`：production `successor_runtime.py` `5089962fcb731f2ab19d514a37b0b15c878b4203`；unit `test_m3_successor_runtime.py` `0081ac9a245ac0ba910ecd0e53340485695c876f`；integration `test_m3_successor_runtime.py` `8dfe969d97593fe0b53e0288ca518fb698d902f6`；taskbook `5c2b133d0f4843c78f9f43d6c251c15d129c11a4`；delivery `e629a7827961711498459bc2036a462a1e50bd75`。
- 本节 STATIC_ONLY / resource NONE：未运行 Python、pytest/collection、Ruff、mypy、cold、CPU、actual worker、retained、network、SQLite、real I/O 或 commit；本节不构成 executable 或 Gate 验证。

### 20.2 R9-1：regular-file link-count 平台矩阵

- 现象：DIAGNOSTIC5 定位到旧 guard 无条件要求 regular file 的 `st_nlink == 1`，会错误拒绝 Windows regular file 的合法 `st_nlink=0`。
- 根因：平台谓词未区分 Windows regular-file 统计语义与非 Windows 约束。
- 应遵循规则：Windows regular file 仅允许 `st_nlink in {0, 1}`；非 Windows regular file 仅允许 `st_nlink == 1`；任何平台的 `st_nlink > 1` 必须拒绝。该例外只作用于 regular file，不得改变 symlink/reparse 或其他非-regular 分支。
- 静态实现证据：`_regular_file_link_count_allowed` lines 2704–2707 使用精确的 `sys.platform == "win32"` 分支；Windows 返回 `nlink in {0, 1}`，其他平台返回 `nlink == 1`。`_walk_controlled_tree` lines 2446–2458 只在 `stat.S_ISREG` 分支调用该 predicate；`_read_regular_file` lines 2690–2701 也调用同一 predicate。
- 测试证据：unit `test_platform_regular_file_link_count_and_link_guards` lines 194–224 静态覆盖 Windows 0/1 接受、>1 拒绝；Linux 0 拒绝、1 接受、>1 拒绝；并覆盖 symlink/reparse 的独立拒绝。没有把外部 `14 passed` 或 integration STOP 当作本轮执行结论。
- 通过条件：平台/类型矩阵精确满足上述规则，Windows 的 0 allowance 不传播到 POSIX、非 regular entry 或 link/reparse 分支；当前源码和测试文本满足。

### 20.3 R9-2：symlink/reparse 与 real-path second guard 未放宽

- 现象/风险：若只在 tree walk 的 `DirEntry` 层做 link-count 处理，或把 Windows 0 allowance 放到统一入口，real-path 读取可能绕过 symlink/reparse 或 regular-file guard。
- 规则与路径：`_walk_controlled_tree` 先以 `entry.stat(follow_symlinks=False)` 检查 `stat.S_ISLNK(info.st_mode) or _is_reparse(info)`，再进入 directory/regular/other 分支；`_read_regular_file` 先经过 `_absolute_no_links` 的逐组件 `os.lstat` guard，再对 `resolved.lstat()` 独立检查 regular、`resolved.is_symlink()`、`_is_reparse(info)` 和 link-count predicate。`_absolute_no_links` lines 2724–2735 仍拒绝任何 symlink/reparse path component。
- 通过条件：symlink、reparse、非 regular entry 不因 Windows `nlink=0` 而放行；real-path second guard 仍独立拒绝；源码静态路径满足，未执行真实 I/O。

### 20.4 新增独立静态 adversarial counterexamples

- 反例 A（实现者测试未覆盖）：fake regular entry 在 `sys.platform="win32"` 下给出 `st_nlink=-1`。`-1 not in {0,1}`，tree walk 必须抛 `ValueError`；在 Linux 或任意非精确 `"win32"` 平台别名下也必须拒绝。
- 反例 B（平台别名）：将平台值设为 `"win32-compat"`，regular `st_nlink=0` 不得进入 Windows 分支；精确比较会走非 Windows `nlink == 1` 分支并拒绝。该变体不在实现者列出的 0/1/2 的 `win32`/`linux` 测试中。
- 反例 C（real-path consistency）：即使第一层 entry 观察到 regular/`nlink=0`，`_read_regular_file` 重新解析后若 `resolved.lstat()` 看到 symlink、reparse、非-regular、负数或 >1 link count，second guard 必须拒绝；其 lines 2693–2700 仍逐项执行这些检查，而不是信任 tree-walk 传入状态。
- 根因/通过条件：这些反例分别检验负值、非精确平台别名和第二次真实路径检查不能被 Windows 例外吞掉；均应 fail closed（tree/read boundary 的 `ValueError`，上层再按既有错误包装处理），且不得生成新的成功树/terminal。以上为静态推理，未运行。

### 20.5 文档证据与静态结论

- taskbook REWORK9 lines 215–233 与 delivery REWORK9 lines 300–320 记录了 DIAGNOSTIC5 根因、平台矩阵、symlink/reparse 独立规则、测试范围和未运行边界。delivery 的 `VALIDATION6` 仅保留外部 `14 passed` 与 integration `12 passed / 3 failed STOP` 证据，并明确未保留 traceback、未重跑本轮 Python；没有被本节改写为 Gate 或 post-fix runtime 通过。
- 已确认：exact5 稳定；Windows/POSIX/`>1` regular-file 矩阵正确；Windows 0 allowance 未传播到 POSIX、非 regular 或 symlink/reparse；`_read_regular_file` real-path second guard 保持严格；新增 adversarial counterexamples 有明确 fail-closed 条件。
- 未证明：本轮任何 Python/test 执行、真实 Windows/POSIX stat 行为、CPU、Gate、actual worker、retained、network/Linux 或 real I/O。上述内容保持 UNPROVEN/未运行。

### 20.6 REWORK9 静态结论

REVIEW_PASS（仅针对 REWORK9 regular-file link-count、symlink/reparse 和 real-path second-guard 静态合同；不表示 executable、Gate 或 runtime 验证。）

## 21. REWORK9 DELIVERY_READY

DELIVERY_READY（仅表示本轮 exact5 静态交付可交回授权验证窗口；post-fix 执行和主 Agent 终验完成前，不得据此宣称 Gate 通过或实际运行成功。）

## 18. REWORK8 独立静态复审：exact shared receipt ownership 闭环

### 18.1 身份、范围与稳定性

- 本节继续使用 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REWORK8-REVIEW`；未创建或使用其他 reviewer、实现 agent、外部 session、top-level task 或 worktree。
- worktree 为 `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`；HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch `codex/m3-g8f-successor-runtime`。
- 两次初始快照与一次写入前快照完全一致。当前 exact5 的 `git hash-object` 为：production `successor_runtime.py` `959e22c1bb14f99e2d671ab996bfc52a84aa1df7`；unit `test_m3_successor_runtime.py` `18e04e0cd33a3a3cf1f790375bfe0f2aca91c329`；integration `test_m3_successor_runtime.py` `8dfe969d97593fe0b53e0288ca518fb698d902f6`；taskbook `c29301971b915fc6d552983b2efe0641dfd294de`；delivery `77be294156f2f2e4feac756c85e5b7c1936d543f`。此前不稳定窗口未写入本报告；本节仅基于恢复后稳定快照。
- 本节 STATIC_ONLY / zero Python：未运行 Python、pytest/collection、Ruff、mypy、cold、CPU、actual worker、retained、network、SQLite、real I/O 或 commit；所有“到达/通过”均是静态控制流结论。

### 18.2 R8-1：窄 shared ownership 例外及全部拒绝矩阵

- 现象：VALIDATION4 外部反馈为 identity PASS、unit `7 passed`、integration `10 passed / 5 failed`；五个失败在 summary Gate 的 `_lookup_refs`，合法跨 fold exact shared receipt 也曾被 `SUCCESSOR_GATE_FAILED` 拒绝。
- 根因：旧 `owned` 只保存 `node_id -> owner kind`，重复 node 无法区分完整 receipt，也没有复用既有 `_shared_receipt_duplicate_allowed` 的窄规则。
- 应遵循规则：重复 node 首先必须是完整相等的 `StageReceiptRef`，然后且仅然后由既有 `_shared_receipt_duplicate_allowed` 判断；该 helper 只允许 shared-stage、`ref.fold is None`、两个 owner 都是不同 fold。任何其他 owner pair 或 ref 漂移必须 fail closed。
- 合法最小路径：unit lines 235–256 用完全相同的 `experiment-identity`/`fold=None` ref 进入两个不同 fold，再提交 summary gate。production `_validate_gate_execution` lines 1809–1821 调用 `_lookup_refs`；`_lookup_refs` lines 1904–1924 先比较完整 ref，再在重复处调用 `_shared_receipt_duplicate_allowed`。helper lines 2254–2265 的四个条件共同形成唯一窄例外。
- 失败矩阵静态闭合：
  - 不同 ref（bytes、path 或 semantic 字段任一变化）：`previous[0] != ref` 先拒绝，lookup 边界为 `SUCCESSOR_GATE_FAILED`；
  - 非 shared stage：`ref.stage not in _SHARED_RECEIPT_STAGES`，helper 返回 false；
  - same-fold：两个 owner 的 fold 标识相等，helper 返回 false；
  - fold-gate、prior-current gate、gate-gate：至少一个或两个 owner kind 为 `gate`，helper 返回 false。
  unit lines 259–383 分别覆盖上述六类拒绝，且不是通过同一断言自比较；每个 helper 异常都由 `_lookup_refs` 的边界包装为 `SUCCESSOR_GATE_FAILED`。
- integration lines 654–685 的 two-fold replay 静态构造真实 production run path，断言两 fold 之间存在完全相等、`fold is None`、stage 属于 `_SHARED_RECEIPT_STAGES` 的 shared node，并断言 summary Gate context 收到 `("fold_001", "fold_002")`。这使合法 shared receipt 的 admission 经过 summary `_validate_gate_execution -> _lookup_refs`，而不是只在 fixture 中声明。

### 18.3 新增独立静态 adversarial counterexample

- 反例（实现者测试未覆盖的字段变体）：从合法 shared ref 构造 `second = replace(shared, relative_path="receipts/experiment-identity/alternate.json")`，或构造 `second = replace(shared, scope_key=_hex("different-semantic-owner"))`，保持同一 node_id、同一 bytes digest、两个不同 fold，再提交 summary gate。
- 现象/根因：如果例外只按 node_id、bytes 或 stage 判断，这类路径漂移/semantic-owner 漂移会被错误当作 shared；实现的完整 ref equality 位于 helper 之前，因此不会发生这种放行。
- 规则与最小复现：`_lookup_refs` lines 1905–1912 在调用 helper 前比较 `previous[0] != ref`，故 path 或 scope_key 任一变化即抛错；若该数据进入 terminal builder，`_validate_global_receipt_ownership` lines 2215–2222 仍执行同一完整 ref/既有 helper 判定。
- 通过条件：返回 `SUCCESSOR_GATE_FAILED`（lookup）或 `SUCCESSOR_TERMINAL_INVALID`（terminal global path），不得生成/接受 shared ownership。该反例在当前静态路径上满足拒绝条件，且不依赖实现者只改变 `sha256` 的既有测试。

### 18.4 global ownership 未被例外放宽与证据边界

- `_validate_global_receipt_ownership` lines 2188–2247 在 node duplicate 的同一 helper 之后，仍独立维护 `by_path`、`by_bytes`、`by_owner`。不同 node_id 复用 physical path、bytes digest 或 semantic owner 分别在 lines 2226–2246 拒绝；同一 node 的不同 ref 已在前置完整 equality 分支拒绝。合法 exact shared 只会让同一 node/ref 在三张表中重复，不会让不同 node alias 获得例外。
- `_build_attestation` lines 1983–1995 先运行 global ownership，再调用 `_unique_refs`；terminal replay lines 2135–2139 再次运行 global ownership。因此 `_unique_refs` 的相同 node/ref 去重不是一条绕过 helper 的 terminal admission path。
- taskbook REWORK8 lines 200–213 与 delivery REWORK8 lines 229–254 均记录现象、根因、规则、拒绝矩阵、合法 shared 测试、VALIDATION4 的 `10 passed / 5 failed STOP` 和未运行边界。delivery 明确指出本轮未重新执行 Python，post-fix focused tests、Ruff、mypy、cold、CPU、worker、retained、network/Linux 均未运行；`DELIVERY_READY` 不等于 Gate 或 runtime 通过。
- 已确认：exact5 稳定；合法两 fold exact shared 只能经既有 helper 规则；指定六类复用 fail closed；global path/bytes/semantic ownership 仍独立；新增 path/semantic adversary 的静态拒绝理由；文档证据诚实。
- 未证明：任何 post-fix Python/test 执行、真实 receipt I/O、Gate、actual worker、retained 或平台原语行为。上述内容保持 UNPROVEN/未运行。

### 18.5 REWORK8 静态结论

REVIEW_PASS（仅针对 REWORK8 exact shared receipt ownership 的静态合同与 adversarial reasoning；不表示 executable、Gate 或 runtime 验证。）

## 19. REWORK8 DELIVERY_READY

DELIVERY_READY（仅表示本轮 exact5 静态交付可交回授权验证窗口；post-fix 执行和主 Agent 终验完成前，不得据此宣称 Gate 通过或实际运行成功。）

## 22. REWORK10 独立静态复审：published attestation receipt tamper

### 22.1 身份、范围与稳定性

- 本节继续使用原 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REVIEW-REWORK10`；未创建或使用其他 reviewer、实现 agent、外部 session、top-level task 或 worktree。
- worktree 为 `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`；HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch `codex/m3-g8f-successor-runtime`。
- exact5 两次初始静态读取及一次写入前读取完全一致。写入前 SHA-256 为：production `successor_runtime.py` `0f86020d509ab193bb663bc3d63f83d25e65f65746b57ad4d0ca929996f5d73e`；unit `test_m3_successor_runtime.py` `a11d835ef70a21ada9c118e182e968344d92c1a1c6724de9fee71bf0574a95a0`；integration `test_m3_successor_runtime.py` `380d3541aac0e2d3ac014a0cf74b41fec676728b9e525afe9232a0952caebbfb`；taskbook `74d75fd09b10fcc06c531fd7408fbbfd1ff8b28edba86bff7e997c21d283f18c`；delivery `a8514852e1739a183f184594557f4ae32b959a2fb243642d770ff298df2f9258`。
- 统一 `git hash-object` 复核显示 production `5089962fcb731f2ab19d514a37b0b15c878b4203`、unit `0081ac9a245ac0ba910ecd0e53340485695c876f`，均与 REWORK9 §20.1 相同；integration/taskbook/delivery 的当前 hash 分别为 `68ccc2d7adfe02f84798a59bb3d0fcaef42e59be`、`c0949a85fd448a533713d7daeb5511b485c5c87b`、`91de263ae1c989aa3bbe95df450e6501ababe2ca`。因此本轮 production/unit 未变，变更范围与 taskbook/delivery 所述的 integration 与文档一致。
- 本节 STATIC_ONLY / resource NONE：未运行 Python、pytest/collection、Ruff、mypy、cold import、CPU、actual worker、retained、network、SQLite、real I/O 或 commit。

### 22.2 R10-1：canonical published receipt 的唯一选择与 tamper 路径

- fixture lines 183–232 先以实际 `publish_stage_receipt(...)` 发布 receipt，再从该实际文件 bytes 构造 `StageReceiptRef.relative_path` 与 `sha256`；这不是一个仅声明文件名的 marker。
- `_run` lines 643–650 调用 production `run_production_two_fold_successor`。integration line 699 保留 `first = _run(...)`，lines 714–718 从 `first.attestation.receipts` 精确筛选 `stage == "snapshot"`、`fold is None`、`horizon is None`，line 719 强制 `len(snapshot_refs) == 1`。
- lines 721–726 校验 `SNAPSHOT` scope、`boundary.snapshot_id` scope key 及 `output/stage/receipts/snapshot/*.json` 的相对路径形状；lines 727–730 以 `request.project_root / snapshot_ref.relative_path` 定位该 canonical ref，并先以原始 bytes SHA256 对比 `snapshot_ref.sha256`；line 731 才追加 tamper bytes，lines 732–738 仍断言 `SUCCESSOR_TERMINAL_INVALID`。unknown-tree 分支的原有错误断言仍在 lines 740–756。
- 当前 integration 中没有 `shared-snapshot.json` 等替代文件名；line 727 的路径来自 attestation ref。fixture lines 193–229 的路径是发布 receipt 时的真实相对路径，不是 tamper 分支另造的替代路径。

### 22.3 R10-2：production verifier 的摘要、路径与错误闭包未被削弱

- production `verify_terminal_attestation` lines 1589–1608 重新读取 canonical terminal、解析 attestation、校验 bindings，并把 `attestation.receipts` 交给 `_verify_receipts`；receipt/tree/gate/ownership 后续仍在同一 fresh verification 路径中执行。
- `_verify_receipts` lines 2308–2327 只按 `ref.relative_path` 经 `_path_from_relative` 找文件，且要求真实 receipt 的 `sha256`、stage、scope、scope_key 与 ref 完全相等；异常统一在 lines 2337–2340 fail closed 为 `SUCCESSOR_TERMINAL_INVALID`。
- `_path_from_relative` lines 2714–2721 与 `_validate_relative` lines 2742–2756 继续拒绝绝对路径、反斜杠、冒号、`.`、`..`、越出 PROJECT 的路径；因此 direct `project_root + relative_path` 的测试定位不能削弱 production 的现有 schema/path guard。

### 22.4 独立静态 adversarial counterexamples（当前 REWORK10 新增路径未覆盖）

- **A1：重复 snapshot ref。** 现象：若 selector 只取第一项或 fallback 到固定文件名，两个同时满足 snapshot/fold-none/horizon-none 的 ref 会使 tamper 目标歧义。根因：没有把 canonical attestation 的唯一性作为前置条件。规则：taskbook REWORK10 lines 241–249 要求恰有一项。最小复现：向 `first.attestation.receipts` 逻辑上加入第二个匹配 ref（可仅改变 node/path/digest），再执行当前筛选。通过条件：`len(snapshot_refs) == 1` 在歧义时 fail closed，不能写入任一不确定目标；terminal binding 还必须由 source lines 2106–2110 的 node 唯一性及 lines 2242–2247 的 semantic-owner guard 拒绝非法发布。当前 exact5 未见该注入变体；本项为实现者未使用的静态反例。
- **A2：绝对或 parent-traversal relative path。** 现象：若测试或 verifier 信任未经 schema 校验的字符串，`/outside.json` 或 `receipts/../outside.json` 可能脱离 PROJECT。根因：把 receipt ref 当作普通路径而未执行相对路径闭包。规则：`StageReceiptRef.__post_init__` line 279 及 `_validate_relative` lines 2742–2754 必须拒绝，绕过对象构造时 `_path_from_relative` 仍须拒绝。最小复现：将上述任一路径注入 attestation receipt ref。通过条件：构造/解析或路径解析失败，并由现有 terminal invalid 包装拒绝；不得发生 outside receipt 的 tamper/read。当前 REWORK10 integration 未执行此注入，本项为独立静态反例。
- **A3：metadata SHA mismatch before tamper。** 现象：保持 canonical receipt bytes 不变，只把 ref 的 `sha256` 换成另一 64-hex 值。根因：若只验证文件存在或只在 tamper 后看 tree，错误 metadata 可能被接受。规则：source lines 2316–2318 必须先比较 verified receipt SHA；通过条件：fresh verify 直接返回 `SUCCESSOR_TERMINAL_INVALID`，且不能把后续 tree/terminal 结果当作成功。当前 integration 检查的是 tamper 前的原始 SHA 一致性（lines 729–730），没有把 metadata 改写变体冒充为已执行测试。

### 22.5 文档证据边界与静态结论

- taskbook REWORK10 lines 235–253 与 delivery REWORK10 lines 331–351 记录了同一现象、根因、规则、测试定位、原始 SHA/tamper 通过条件及 `VALIDATION7` 外部证据；delivery 明确记载 unit `15 passed`、focused integration `14 passed / 1 STOP` 与 stdout trace SHA，但修复后的 integration 本轮未重跑。
- 已确认：exact5 稳定；production/unit 与 REWORK9 相同；integration 使用真实 published `first.attestation.receipts` 的唯一 snapshot ref、scope/shape/original-SHA 校验、ref-derived PROJECT 定位和既有错误码；production receipt digest/path/schema/terminal guard 未放宽；新增重复、路径越界和 metadata-SHA 静态反例均有明确 fail-closed 条件。
- 未证明：任何本轮 Python/test 执行、post-fix integration 结果、真实 receipt I/O、Ruff/mypy/cold/CPU、actual worker、retained、Linux/network 或任何 Gate。`VALIDATION7` 仅是文档中的外部历史证据，不能升级为本轮执行证明。

### 22.6 REWORK10 静态结论

REVIEW_PASS（仅针对 REWORK10 attestation-bound receipt tamper 的静态合同与 adversarial reasoning；不表示 executable、Gate 或 runtime 验证。）

## 23. REWORK10 DELIVERY_READY

DELIVERY_READY（仅表示本轮 exact5 静态交付可交回授权验证窗口；post-fix 执行和主 Agent 终验完成前，不得据此宣称 Gate 通过或实际运行成功。）

## 24. REWORK11 独立静态复审：dependency typing 与 canonical bytes

### 24.1 身份、范围与稳定性

- 本节继续使用原 reviewer `01a031ff-0056-7c42-8dfc-0a704f1d5824`，逻辑任务为 `M3-G8F-R1-REVIEW-REWORK11`；未创建或使用其他 reviewer、实现 agent、外部 session、top-level task 或 worktree。
- worktree 为 `F:/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g8f-successor-runtime`；HEAD `ac57ce9e40dc6731e1106b2fa2398f4013fa19da`；branch `codex/m3-g8f-successor-runtime`。
- exact5 两次初始静态读取及一次写入前读取完全一致。写入前 SHA-256 为：production `58afb3092f85d94193eff073a5a8b825ee893620b75ca98992877a0a0fea747f`；unit `940a047a8767b5a124e9819f7b3fb866f26a9157e5cd003fd2da7f73fe8723c8`；integration `380d3541aac0e2d3ac014a0cf74b41fec676728b9e525afe9232a0952caebbfb`；taskbook `53189b78af87c9c169cac93db38bbab4837d85a769266e9df9ff05ba2011e26e`；delivery `ca9f472153a9127b3b9576b0957c4c83a79f0633e2e49deed23e205a881c1a1c`。
- 当前 `git hash-object` 为：production `8bbc29ac993eec010094cfea3642f852d77dcb1c`；unit `343e5d9f960cb6a7e88a190ae3304278cf4d45be`；integration `68ccc2d7adfe02f84798a59bb3d0fcaef42e59be`；taskbook `8771321a4e98a4501e4895c08ee84e3f7b32fc75`；delivery `a60dbeb59911720608bee712839fb2b44d63e255`。与 taskbook/delivery REWORK11 声明的范围一致：本轮 production、unit 与文档更新，integration 保持只读；本报告是唯一写入目标。
- 本节 STATIC_ONLY / resource NONE：未运行 Python、pytest/collection、Ruff、mypy、cold import、CPU、actual worker、retained、network、SQLite、real I/O 或 commit。

### 24.2 13 个 dependency 字段的类型与 fail-closed 守卫

- source lines 904–916 的顺序和非 Optional Protocol 类型精确为：`stage_runner_factory`、`run_upstream_stage`、`run_formal_stage`、`verify_fold`、`run_summary`、`verify_summary`、`run_reproducibility`、`verify_reproducibility`、`run_readiness`、`verify_readiness`、`run_acceptance`、`verify_acceptance`、`verify_gate`；字段没有 `Optional` 或 `| None`。
- dataclass `__post_init__` lines 918–940 仍对 13 项统一执行 `callable` 检查，并要求 `stage_runner_factory is make_project_stage_runner`。adapter constructor lines 957–995 再次检查同一 13 项、factory identity 和 canonical `StageRunner` identity；`_runner` lines 1207–1231 仍复查 factory、具体 runner 类型、PROJECT-only roots、Path 类型和精确 stage-root equality。因此 None、非 callable、错误 factory/runner identity 都保持 `SUCCESSOR_INPUT_INVALID` fail closed。
- unit lines 227–245 直接以全 None 构造依赖；lines 248–284 先构造合法依赖，再用 dataclass `replace` 逐一将 13 个字段置 None 并断言稳定错误码。该测试直接进入依赖 dataclass 构造/ `__post_init__`，不是只验证 fixture 字符串。integration line 774 的缺依赖路径保持不变；post-fix 执行仍未由本节声称。

### 24.3 字段顺序、固定 callback/run sequence 与 rename-only 变更

- dependency 字段顺序与 taskbook REWORK11 lines 261–269 的冻结列表一致；integration boundary lines 166–181 也按同一顺序提供 13 个 keyword callback。字段顺序没有被 typing 修复重排。
- adapter fold sequence 仍由 source lines 118–135 的固定 stage tuples、lines 1018–1092 的 pre-formal → each horizon → formal backtest/tracking 组成；orchestrator lines 1444–1464 仍逐 fold run/verify 后才进入 Gate。
- Gate sequence 仍是 lines 1469–1483 的 summary、1485–1503 的 reproducibility、1505–1527 的 readiness、1529–1552 的 acceptance，每步按既有 prior-gate prefix fresh verify；没有把完整 `run_fold`/Gate sequence 外包给 callback。
- `_validate_fold_execution` lines 1723–1729 的 `expected_work_key` 仍是同一 `compute_work_key(experiment_key, fold, horizon)` 比较；lines 1747–1803 的 `expected_receipts` 仍生成同一 stage/horizon 计数并与 `observed` 比较；controlled-tree lines 2390–2395 的 `entry_digest` 只替代局部变量名。三者均未改变输入、值、排序或序列化字段。

### 24.4 canonical bytes、schema 与新增测试路径

- `_canonical_bytes` lines 2665–2674 仅在 dataclass 形态下使用 `asdict(cast(Any, value))`，并保留 `sort_keys=True`、紧凑 separators、`ensure_ascii=True`、`allow_nan=False`；非 dataclass mapping/list 仍直接交给同一 JSON encoder。terminal build line 2053 和 parse canonical comparison line 2489 继续经过该函数，exact-object schema/key closure 未变。
- unit lines 287–296 构造真实 `SuccessorRuntimeIdentity`，分别把 dataclass 和 `asdict(identity)` mapping 送入 runtime `_canonical_bytes`，直接断言 bytes 相等；这确实命中实现函数，而非只检查测试 fixture 或文本。当前测试没有把该等价断言冒充为 full terminal/Gate execution。
- taskbook lines 255–273 与 delivery lines 363–381 均将本轮限定为行为等价 typing/窄序列化桥接，并诚实记录 post-fix checks 未运行。

### 24.5 独立静态 adversarial counterexamples（实现者未使用）

- **A1：non-callable non-None 的 adapter 路径。** 现象：当前新增 per-field 测试覆盖 None，但没有把一个非 None、非 callable 值注入已构造对象后再走 adapter constructor。根因：静态非 Optional 类型不能替代运行时 callable guard。规则：dataclass 与 adapter 两层均必须拒绝非 callable，且在任何 successor 写入前返回 `SUCCESSOR_INPUT_INVALID`。最小复现：先取得合法 `dependencies`，再以 `object.__setattr__(dependencies, "verify_gate", object())` 破坏 frozen 实例，调用 `make_production_successor_stage_adapter`。通过条件：adapter lines 962–978 fail closed，不进入 `_runner`、stage callback、receipt、artifact 或 terminal；当前 exact5 未见该变体。
- **A2：positional field-order swap。** 现象：将合法 13 个 callback 以 positional constructor 传入，但交换 `run_summary` 与 `verify_summary`；两者仍 callable，若字段顺序漂移，单纯 callable/identity 检查可能无法发现语义错接。根因：callback 的职责由冻结字段顺序和 Protocol 类型共同定义，不能只靠可调用性。规则：保持 lines 904–916 顺序及 keyword wiring；summary runner 必须先产生 GateExecution，summary verifier 只能走 fresh verification。最小复现：交换第 5/6 个 positional value 后调用 adapter 的 summary path。通过条件：静态字段顺序不变，typed construction 拒绝不匹配签名，且现有固定 sequence不被重排；当前实现者新增测试未覆盖 positional swap。
- **A3：nested dataclass/tuple canonical form。** 现象：identity 是扁平 dataclass，等价测试不能单独证明嵌套 `FoldExecution`/`StageReceiptRef` tuples 的 canonical form。根因：递归 `asdict`、tuple-to-JSON-array 和 nested key sorting 若任一改变，terminal bytes/tree identity 会漂移。规则：对合法 nested dataclass 与 `asdict` mapping 必须保持同一 JSON schema/bytes，仍由同一 sort/separator/ASCII/NaN 选项编码。最小复现：构造含两个 `WorkIdentity`、多个 `StageReceiptRef` 的 `FoldExecution`，比较 `_canonical_bytes(value)` 与 `_canonical_bytes(asdict(value))`，并再以逆插入顺序 mapping 检查 sorted keys。通过条件：静态路径显示递归 asdict 只展开 dataclass、JSON 将 tuple 同形编码为数组、`sort_keys=True` 抵抗 mapping 插入顺序；本轮未执行该 probe，不能写成执行通过。

### 24.6 文档证据边界与静态结论

- delivery VALIDATION8 记录的外部历史证据为 identity PASS、unit `15 passed`、integration `15 passed`、Ruff exact3 PASS；mypy 首次 STOP，13 个错误的 stdout SHA 为 `ee7073f019c91a27530390b3f6da8e52a44733c7f93e62d9515b6fd0c5bfbf5b`。这些是修复前证据，不是本轮 post-fix 执行结果。
- 已确认：exact5 稳定；13 字段非 Optional 且字段顺序保持；None/non-callable/factory/StageRunner identity 的 runtime guards 保持；fold/Gate callback 顺序未变；三个变量为 rename-only；`asdict(cast(Any, value))` 的 canonical JSON options/schema path 未变；新增 unit tests 直接命中依赖构造和 canonical helper。
- 未证明：本轮 post-fix unit/integration/Ruff/mypy/cold/CPU、真实 canonical terminal bytes、actual worker、retained、Linux/network 或任何 Gate。上述内容保持 UNPROVEN/未运行，不能由静态报告升级。

### 24.7 REWORK11 静态结论

REVIEW_PASS（仅针对 REWORK11 dependency typing、runtime guard、固定 sequence、rename-only 与 canonical bytes 静态合同；不表示 executable、Gate 或 runtime 验证。）

## 25. REWORK11 DELIVERY_READY

DELIVERY_READY（仅表示本轮 exact5 静态交付可交回授权验证窗口；post-fix 执行和主 Agent 终验完成前，不得据此宣称 Gate 通过或实际运行成功。）
