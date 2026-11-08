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

