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

