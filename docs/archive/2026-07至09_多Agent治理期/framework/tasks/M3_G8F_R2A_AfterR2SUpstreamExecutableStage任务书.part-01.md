# M3-G8F-R2A After-R2S Upstream Executable Stage 任务书

状态：`R2A_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION7 focused74+Ruff 与 POSTFIX VALIDATION8 identity/Ruff/mypy/cold/scope 组合闭合；**不**表示 production bridge、CLI、actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate 完成）<br>
task id：`M3-G8F-R2A-AFTER-R2S-UPSTREAM-EXECUTABLE-STAGE`<br>
exact base：`d525770ac9deb78e414098308b34acbd0773c099`<br>
branch：`codex/m3-g8f-r2a-upstream-executable-stage-after-r2s`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2a-upstream-executable-stage-after-r2s`

## 1. 目标与终态上限

在已合流 R2P orchestration wave compatibility 与 R2S formal summary publication 之上，补齐唯一 package-owned upstream/summary executable wiring，使现有 successor runtime 能以真实 public plan、`StageRunner`、artifact builder/verifier 和显式 prior receipt 执行完整 upstream waves。

本包最高只能声明 `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED`。不得宣称 production bridge、CLI、actual worker、真实 Qlib、新 root、retained、acceptance 或 M3 Gate 完成。

## 2. 权威现状与被取代历史

- R2P 已提供 PROJECT-only `artifact_roots`、真实 wave builder 与 `select_run_plan_nodes`。
- R2S 已提供 `run_formal_summary_stage` 及 temp/publication/post-receipt 三阶段 verifier；本包必须消费，不得复制 summary handler。
- 旧 R2A STOP 的 G5 已由 R2S 关闭；旧 worktree/branch 已退休且没有可复用提交。旧 placeholder、marker、目录启发式或未验证 receipt 不得复制。
- `successor_runtime.py` 继续唯一拥有双 fold、formal backtest/tracking、summary 与四 Gate 的顺序。

## 3. 唯一写白名单（exact9）

1. `src/quant/research/m3/successor_upstream_stage.py`（new）
2. `src/quant/research/m3/successor_runtime.py`
3. `tests/unit/test_m3_successor_upstream_stage.py`（new）
4. `tests/integration/test_m3_successor_upstream_stage.py`（new）
5. `tests/unit/test_m3_successor_runtime.py`
6. `tests/integration/test_m3_successor_runtime.py`
7. `docs/framework/tasks/M3_G8F_R2A_AfterR2SUpstreamExecutableStage任务书.md`（经理独占）
8. `docs/framework/deliveries/M3_G8F_R2A_AfterR2SUpstreamExecutableStage交付报告.md`（实现者独占）
9. `docs/framework/reviews/M3_G8F_R2A_AfterR2SUpstreamExecutableStage独立初验报告.md`（独立 reviewer 独占）

实现者只写 1–6、8，不写 7、9。reviewer 只写 9，其余只读。禁止修改 orchestration、evaluate、summary_stage、formal stage 模块、`__init__.py`、config、roadmap、共享 SSOT 或任何其他路径。

## 4. 冻结公共合同

### 4.1 Package-owned executable wiring

- `successor_upstream_stage.py` 是 upstream wave wiring 的唯一实现位置。每次调用必须构造一个完整 canonical wave plan，并通过现有 `StageRunner.run_snapshot` / `run_static` 执行或 resume 完整 node closure。
- 它只能组合 public `make_*_run_plan`、`select_run_plan_nodes`、public artifact build/verify 与 R2S `run_formal_summary_stage`；不得 import orchestration 私有 helper、扫描目录、猜文件名或持有 mutable result cache。
- snapshot、provider、provider-validation、experiment-identity 各执行完整 wave；experiment-artifacts 的 labels+folds 只构造一个完整 plan；label-reconciliation 覆盖全部 horizons；work 覆盖 features 与全部 fold×horizon nodes。完整 wave 不得拆成逐 node 发布。
- formal backtest/tracking 与四 Gate 继续由 runtime 调用既有 public 函数；新模块不得拥有或复制该顺序。

### 4.2 Context、receipt 与 fresh closure

- frozen context 只绑定 exact request、stage context、stable-sorted verified `StageReceiptRef` tuple 与预期 transition identity；不得持有 runner、mutable dict/cache、目录发现结果或未验证 artifact。
- 上游输入只从 context 显式 prior refs 的确定 `relative_path` 读取。必须先用 `verify_stage_receipt_with_bytes` fresh 验真，再将 receipt outputs 与当前 exact `RunPlan` / `StageNode.output_specs` 做唯一闭包匹配；少、多、重复、unknown、wrong alias/path/size/hash/node 均 `SUCCESSOR_STAGE_INVALID`。
- cache/reuse 命中不得直接返回内存 tuple。每次 fold 调用都重建 canonical plan 并 fresh 验证 receipt 与 typed artifact。
- 同一 request 的两个不同 folds 可共享一次物理 wave；第二 fold 只能在本次进程内、首 fold 已成功发布且 identity 完全相同时使用 exact resume。caller 原始 `resume=false` 不允许跨进程采用旧产物。
- 跨 request、project root、resume、two-fold identity、fold 顺序漂移，重复 fold、第三 fold、逆序进入及失败 wave 的部分结果复用均 fail closed。

### 4.3 Toolchain binding 与 identity

在 runtime 中新增 frozen `SuccessorToolchainBinding`（等价命名必须在 delivery 说明），exact fields：

- `python_executable: Path`
- `qlib_dump_tool_path: Path`
- `timeout_seconds: float`

规则：

1. 两个 Path 必须是当前平台 exact concrete `Path()` 类型、绝对、存在的普通文件；拒绝 subclass、`PurePath`、相对路径、symlink/reparse。
2. Python 可位于 project 外，但必须 fresh 验证；不得默认 `sys.executable`、PATH lookup 或环境发现。
3. dump tool canonical resolved path 必须逐字等于 `project_root / DEFAULT_TARGET_PATH`；`DEFAULT_TARGET_PATH` 只能 import 自现有 `fetch_qlib_tool.py` SSOT。
4. 两 fold config 经既有 `build_qlib_dump_tool_spec` 得到的 spec 必须 exact 相同；dump bytes/size/SHA 必须闭合。禁止 ensure/download/network/fallback。
5. timeout 必须 `type is float`、finite 且 `>0`；bool/int/0/非有限值拒绝。
6. canonical toolchain identity至少包含 resolved Python path、PROJECT-relative dump path、dump size/SHA、timeout，并进入升级后的 `two_fold_identity`。terminal schema/output集合不变；任一工具漂移必须拒绝旧 terminal/receipt。
7. request/toolchain validation 必须在任何 controlled root 创建或 worker 启动前完成，错误稳定为 `SUCCESSOR_INPUT_INVALID`。

### 4.4 Canonical callable identity

- public bundle与 `SuccessorProductionDependencies` 必须以 `is` identity 绑定 package-owned upstream runner、R2S summary runner/verify 能力及 runtime canonical advance callable。
- 为避免 import cycle 可在 factory 内局部 import，但最终 identity 必须可验证；wrapper/lambda/monkeypatch/marker/bool/非 callable/旧字段均拒绝。
- caller 不得注入 handler、verifier、artifact object、StageRunner 替代品或完整 stage 序列。

## 5. 必须覆盖的对抗性反例

至少覆盖：

1. 缺失/多余/乱序/重复 prior ref；stage/fold/horizon/scope/path/size/hash 漂移；后置 artifact 已存在但 prior ref 未提供；伪 latest/tree scan 不得被消费。
2. 完整 experiment/work plan 少、多、重复、乱序 node；labels/folds 不得共享伪 receipt；跨 fold physical ownership 漂移。
3. 第二 fold 前篡改 receipt 或 artifact bytes必须 fresh 拒绝；同 request 双 fold物理 publish exact1但closure调用两次；首次 wave 失败不得登记成功。
4. missing/None/非 exact Path、relative/subclass/PurePath/symlink/reparse Python/dump；wrong `DEFAULT_TARGET_PATH`；两 config spec 漂移；dump bytes/size漂移；timeout bool/int/0/nonfinite。
5. toolchain 任一字段改变 two-fold identity并拒绝旧 terminal/receipt。
6. wrapper/monkeypatch 替换 upstream/summary/verify/advance；marker bundle、object replacement、旧字段、None/noncallable。
7. context 外部 mutation、跨 fold/context reuse、重复/第三/逆序 fold；resume identity漂移与 terminal伪成功。
8. summary必须走R2S public runner并完成真实build/publication/post-receipt fresh closure；不得返回 placeholder、plan hash、手工 receipt 或 `GateExecution` 冒充。

## 6. 静态实施与验证顺序

当前仅授权 `STATIC_ONLY`：零 Python、pytest、Ruff、mypy、cold、真实 Qlib、网络、actual worker、new root、retained 访问或提交。

实现者应：

1. 先读 AGENTS、R2P/R2S task/delivery/review与 exact9目标源码；确认 base/branch/dirty 只有本任务书。
2. 先冻结 public types/callable identity，再实现最小 wiring；每个 wave 复用现有 builder/runner/verifier。
3. 补齐 unit/integration 静态测试与 delivery，逐项记录合同映射、STOP历史与未运行边界。
4. 完成后回 `DELIVERY_READY <delivery path>`；不得自行运行检查、stage或commit。

独立 reviewer 必须使用未参与实现的全新外部会话，补至少一个实现者未使用的反例，重点挑战：同进程第二 fold resume 与跨进程旧产物隔离、receipt output唯一映射、toolchain identity漂移和callable replacement。review PASS 后由经理另向中央申请 Windows 验证资源。

## 7. STOP 条件

出现以下任一情况立即在 delivery 写明“现象—根因—规则—最小复现—所需路径/API—通过条件”并 STOP：

- exact9 不足，或需要修改 R2P/R2S、orchestration、formal stage、config/schema/`__init__`；
- public builder/verifier 无法完成真实 stage closure；
- `DEFAULT_TARGET_PATH` 与两 fold spec 不能 exact 闭合；
- `StageRunner` 无法区分本进程第二 fold resume 与 caller `resume=false` 的跨进程旧产物；
- 需要扫描目录、隐式 cache、placeholder、手工 receipt 或复制 stage/Gate 顺序；
- base/branch/worktree漂移、出现第二 writer或白名单外 dirty。

## 8. 交付与完成标准

- actual dirty 必须精确属于 exact9，普通 `git diff --check` PASS；无临时文件、缓存、凭据或真实产物。
- delivery 必须列出修改、关键 API、每类反例、未运行项、边界与建议 focused/Ruff/mypy/cold 顺序。
- reviewer `REVIEW_PASS` 只是 Windows 主验准入，不等于本包或 M3 Gate 完成。

## 9. 独立初验返工 R1（2026-08-26）

独立初验结论为 `REVIEW_FAIL`。本轮保持 exact9、base、branch、worktree 与全部禁止项不变，交回 §0A 的同一授权重实现采用者；不得创建第二实现者或复用已退出的原违规实现者。review 报告在实现交付前只读，返工后必须由另一全新外部 reviewer 复验。

### F1 — 多 horizon prior 唯一闭包

- 现象：`labels` 或 `label-reconciliation` 可用两个不同 `node_id`、相同 horizon 的 ref 满足数量检查，随后在 horizon-keyed dict 中静默覆盖。
- 根因：分组只检查 stage 计数，没有验证 horizon 集合与 request/config 的 canonical horizons exact 相等。
- 规则：所有按 horizon 索引的 prior 必须在重建前证明 horizon 非空、无重复、无缺失/额外，且 exact 等于当前请求的 canonical horizon 集合；重复 horizon 必须稳定 `SUCCESSOR_STAGE_INVALID`，不得依赖下游晚失败。
- 最小复现：两个 `labels` ref 均 `horizon=5`、不同 `node_id` 且整体 node-id 排序合法。
- 新增测试：labels 与 reconciliation 各自 duplicate horizon；missing/extra horizon；顺序变化仍按 canonical 集合闭合。
- 通过条件：入口 fail closed，任何 dict 写入前已证明唯一 horizon 闭包。

### F2 — registry poison 不得授予 resume

- 现象：`_WAVE_REGISTRY` 只要存在 matching key 就把 caller `resume=False` 抬为 `effective_resume=True`；预植入条目可能采用跨进程旧产物。
- 根因：把可写进程内 dict 的“键存在”误当成本进程首 fold 已由本函数成功发布并 fresh 闭合的证明。
- 规则：只有本次 request 生命周期内由 canonical runner 在完整 plan 成功发布、fresh receipt/typed artifact closure 全部通过后生成的不可伪造成功状态，才可授权第二 fold resume。外部/测试预植入 registry、失败 wave 部分结果、错 request/root/toolchain/fold 都不得抬 resume。若在 exact9 内无法构造该证明，按 §7 STOP，不得用隐藏 cache 或弱化 caller `resume=false`。
- 最小复现：首次真实 publish 前预植入 matching registry key+旧盘面 refs，再以 `resume=False` 调用。
- 新增测试：pre-seed poison 必拒；handler 入口失败与多 node 部分发布失败均不登记成功；首 fold完整成功后第二 fold物理发布 exact1、fresh closure exact2保持。
- 通过条件：poison/partial state不能改变 caller resume语义；只有 canonical成功状态可授权同request第二fold resume。

### F3 — toolchain symlink/reparse 强制回归

- 现象：实现有非跟随拒绝逻辑，但 exact9 测试未覆盖任务书 §5.4 的 Python/dump symlink/reparse 反例。
- 规则：exact lexical leaf 为 symlink、junction/reparse或resolve漂移时必须 `SUCCESSOR_INPUT_INVALID`；不得先follow后验证target。普通native concrete Path正向保持。
- 新增测试：Python与dump各覆盖symlink；Windows reparse/junction在宿主允许时实际构造，权限不足时使用项目既有窄属性注入证明guard，不能以无条件skip关闭合同。
- 通过条件：正向普通文件保持，所有链接/reparse叶稳定fail closed。

本轮实现者必须在delivery按“现象—根因—规则—最小复现—新增测试—通过条件”记录F1–F3与采用结果。继续零Python、零脚本编辑、零验证、零提交。

## 10. VALIDATION1 test-only fixture 返工（2026-08-26）

VALIDATION1 的 identity preflight PASS；focused exact4 得到 `61 passed / 3 failed`，随后 Ruff、mypy、cold、scope 均未运行。三项失败均为测试 fixture 排序错误，尚未形成 production 红证据。本轮保持 exact9、base、branch、worktree 与全部禁止项不变，交回 §0A 的同一授权采用者，且仅允许修改：

- `tests/unit/test_m3_successor_upstream_stage.py`
- `tests/integration/test_m3_successor_upstream_stage.py`
- `docs/framework/deliveries/M3_G8F_R2A_AfterR2SUpstreamExecutableStage交付报告.md`

冻结修正：

1. unit 与 integration 中原 `unsorted=(provider, snapshot)` 实际已经按 `node_id` stable-sort；改为真实逆序 `(snapshot, provider)`，继续证明乱序 node closure fail closed。不得修改 production selection/sort 规则。
2. partial-failure 用例中成功 handler 返回的 refs 必须按真实 `node_id` stable-sort：`folds, labels.h10, labels.h5`。不得借 fixture 修正改变首次失败路径、异常语义或 registry 合同。
3. 保留并逐字验证：首次 wave 失败不登记 reusable success；第二次进入仍使用 `resume=False`；只有完整成功并 fresh closure 后才封存本次 request 的成功状态。
4. delivery 追加本轮“现象—根因—排序规则—最小复现—修正测试—通过条件”，同时记录有效 evidence root、identity PASS、`61 passed / 3 failed` 与后续阶段 `UNRUN`；另一个空 evidence root 只能标记 `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE`，不得冒充产品证据。
5. production、runtime tests、taskbook与review报告（本次任务书经理追加除外）保持冻结；零Python、零验证、零提交。完成后由原独立 reviewer 复验本轮最小diff，再申请从 identity→focused exact4 开始的完整 VALIDATION2。

## 11. VALIDATION2 Ruff-only 静态返工（2026-08-26）

VALIDATION2 的有效证据为：identity PASS；focused exact4 `64 passed`；Ruff 首失败 STOP；mypy、cold、final scope 均 `UNRUN`。production/runtime 行为失败未被证明。本轮保持 exact9、base、branch、worktree 与全部禁止项不变，交回 §0A 同一授权采用者，且仅允许修改：

- `src/quant/research/m3/successor_upstream_stage.py`
- `docs/framework/deliveries/M3_G8F_R2A_AfterR2SUpstreamExecutableStage交付报告.md`

冻结修正：

1. 删除 Ruff 报告的三个未使用 import：`ProviderValidationSpec`、`StageContext`、`StageReceiptRef`。
2. 删除未使用局部绑定 `label_refs`；若其右侧表达式承担必须保留的验证副作用，则保留原表达式为显式调用而不赋值。不得删除或跳过任何 validation/wave/receipt closure。
3. 除上述 import/binding 收敛外，不得改变运行分支、调用次数/顺序、异常码、receipt/wave/identity、resume、registry 或 public API。
4. delivery 追加 VALIDATION2 的原生 evidence root、focused/Ruff/summary关键 SHA、有效阶段与 `UNRUN` 边界；另一个 parser 失败 root 只可标为 `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE`。不得把 focused PASS 冒充整包通过。
5. runtime、tests、taskbook与review（本次经理追加除外）保持冻结；零Python、零验证、零提交。完成后由原独立 reviewer 复验行为等价最小diff；PASS 后申请 postfix validation：identity→Ruff prod2/tests4→mypy prod2→cold prod2→exact9 scope/residue，不重复已绿 focused64。

## 12. VALIDATION3 production type-contract 返工（2026-08-26）

POSTFIX VALIDATION3 的有效证据为：identity PASS；Ruff production2/tests4 PASS；mypy production2 在 `successor_upstream_stage.py` 以 115 项错误首失败 STOP；cold与final scope `UNRUN`。至少三处为真实可运行分支合同错误，不能归为注解噪声；本轮必须重新进入完整 production 返工与独立复验，后续不得沿用窄 postfix。

本轮保持 exact9、base、branch、worktree及全部真实运行禁止项不变，交回 §0A 同一授权采用者。允许修改：

- `src/quant/research/m3/successor_upstream_stage.py`
- `tests/unit/test_m3_successor_upstream_stage.py`
- `tests/integration/test_m3_successor_upstream_stage.py`
- `docs/framework/deliveries/M3_G8F_R2A_AfterR2SUpstreamExecutableStage交付报告.md`

### 12.1 三项真实 API 错误

1. `BacktestPlanFreshVerificationContext` 必须从其真实 SSOT `quant.backtest.a_share_plan` 导入；禁止从 `quant.research.m3.contracts` 伪导入或复制类型。
2. `plan_provider_probe` 调用必须传入现有 public API 要求的 exact `spec`，且与当前 provider-validation node/receipt/identity闭合；不得改 public 函数签名或测试 mock 掩盖。
3. `build_backtest_plan_artifact` 调用必须传入现有 public API 要求的 `artifact_roots`，只使用本包 canonical `{"PROJECT": project_root}`；不得扫描、默认 alias或改 builder。

### 12.2 bundle、plan 与配置强类型闭包

1. public bundle 中本包消费的 run-plan builders、selector、runner/verifier callable必须以窄 `Protocol`、明确 callable alias或等价静态可验证类型表达真实签名和 `RunPlan` 返回值；不得继续以 `object` 流入 `select_run_plan_nodes`/`.nodes`，也不得使用 `Any`、`cast`、`type: ignore`、宽泛 duck fallback。
2. 只能收窄本包 exact9 内的消费边界；不得修改R2P/R2S public API、orchestration或runtime外公共模块。canonical callable `is` identity与现有 marker/wrapper fail-closed测试不得削弱。
3. request/config 中进入 `Literal` 合同的 horizon、benchmark、dump contract、strategy等必须在首次使用前做 exact runtime type/value验证后静态收窄；普通 str/int/object不得直接传入。只接受既有冻结值域，不新增默认值、不放宽 bool/int混淆。
4. train/validation/test/step/embargo、tolerance、minimum coverage/top-k等 object字段必须先以 exact type与范围闭合，再构造现有 spec；错误仍归既有稳定输入/stage错误，不泄露内部类型异常。

### 12.3 verified artifact、path 与 summary node闭包

1. 所有 `Verified* | None`、spec或receipt `Path | None` 必须在对应 builder 前完成显式存在性、exact type及identity闭包，再以已收窄局部变量调用；禁止靠 `assert`、truthy、Any/cast/ignore掩盖。
2. fold/horizon允许的 `None` 只保留在协议明确允许的位置；进入 horizon-specific spec前必须收窄为既有 `Literal[5,10]`。不得改变node集合、排序、physical ownership或receipt schema。
3. `_SummaryNodeRef` 与 `_new_receipt_ref(StageNode)` 不得伪装兼容。使用最窄只读 Protocol/专用构造函数或等价强类型，把 summary node 的 exact `node_id/stage/fold/horizon/scope_key/publication` 绑定清楚；不得扩大通用 StageNode API或手工伪造receipt。
4. iterable/sorted/max等操作前必须证明输入为对应tuple/mapping/int窄类型，不得让bundle/config `object` 静默传播。

### 12.4 测试、证据与停止条件

1. 在现有 upstream unit/integration 中补未 mock 的真实签名反例，至少让 provider-validation 的 `plan_provider_probe(spec=...)` 与 backtest-plan 的 `artifact_roots={"PROJECT": project_root}` 通过真实调用边界；错误导入必须由模块加载/真实路径合同覆盖，不能只测源码字符串。
2. 保持并补齐 Literal/Optional拒绝：horizon `None`/非法int、benchmark/strategy/dump contract漂移、缺verified fold/alignment/model/prediction或receipt path均在builder前fail closed；合法h5/h10与完整artifact链保持。
3. delivery追加 VALIDATION3 evidence root、Ruff/mypy/summary关键SHA、115项按类别映射、三项真实API错误与全部 `UNRUN` 边界，记录“现象—根因—规则—最小复现—新增测试—通过条件”。
4. 零Python、pytest、Ruff、mypy、cold、脚本、真实Qlib、网络、actual worker、new root、retained、stage/commit。若强类型闭包需要exact9外公共API或无法在不使用Any/cast/ignore下完成，立即 `CONTRACT_STOP` 举证，不得自行扩围。
5. 完成后原独立 reviewer 必须完整复验 production/API/测试合同；PASS 后重新申请完整 validation：identity→focused exact4→Ruff prod2/tests4→mypy prod2→cold prod2→exact9 scope/residue。

## 13. TYPE_CONTRACT_REVIEW test-only 真实调用返工（2026-08-26）

独立 reviewer 结论为 `TYPE_CONTRACT_REVIEW_FAIL`：§12.1–12.3 的 production 静态面大体闭合，但 §12.4 强制的两个 unmocked 真实调用边界未满足。现有测试仅 `inspect.signature`、源码字符串与缺参失败；这不能证明合法 `spec=` / `artifact_roots=` 已进入真实 public API。

本轮保持 exact9 与全部禁止项不变，交回 §0A 同一 adopter，且仅允许修改：

- `tests/unit/test_m3_successor_upstream_stage.py`
- `tests/integration/test_m3_successor_upstream_stage.py`
- `docs/framework/deliveries/M3_G8F_R2A_AfterR2SUpstreamExecutableStage交付报告.md`

冻结修正：

1. 为 `plan_provider_probe` 增加至少一条 unmocked 实调：使用测试现有canonical helper/materialized fixture构造合法、identity闭合的 snapshot/provider/config 与 `ProviderValidationSpec`，逐字以 `spec=validation_spec` 调用真实 public 函数。测试必须越过Python参数绑定与输入shape门禁，得到真实 `ProviderProbePlan`（或该API冻结的等价合法结果），并核关键identity；不能只测缺参、`inspect.signature`、source string或用 `object()` 触发早失败。
2. 为 `build_backtest_plan_artifact` 增加至少一条 unmocked 实调：复用测试现有canonical fold/feature/alignment/model/prediction/target/upstream fixture，显式传 `artifact_roots={"PROJECT": project_root}` 与合法output root/spec，执行真实 public builder并核返回artifact/manifest/receipt-input identity或等价合法产物。不得把 builder monkeypatch 成桩，不得只检查源码字符串/签名。
3. 若完整合法fixture过重，可使用同一测试模块已有最小canonical builders/materializers组合；但必须保留真实 public函数调用，且失败若发生应在业务artifact验证之后而非参数绑定/缺字段之前。禁止为了方便修改production/public API或放宽artifact closure。
4. 保留原 signature/source断言可作为辅助，但不能替代正向实调。补一个对照反例：wrong/missing `spec` 或 wrong alias roots仍按原稳定码fail closed；PROJECT-only正向与错alias反向必须分离。
5. delivery追加本轮六要素与 reviewer FAIL证据，明确production字节冻结、零Python/验证、历史115项尚待运行复验。完成后交同一 reviewer 复验，仅通过后申请完整 validation。
## 14. VALIDATION4 focused fixture 父目录返工（2026-08-26）

VALIDATION4 的有效承载证据为：identity PASS；focused exact4 `73 passed / 1 failed / 373236 warnings`；Ruff、mypy、cold、final scope均 `UNRUN`。唯一失败发生在新增真实 API 正向测试的 test fixture：调用 `plan_support._context(tmp_path / "plan", ...)` 前未创建 `plan` 父目录，深层 support 按既有合同执行 `plan/artifacts.mkdir(parents=False)` 时抛出 `FileNotFoundError`。这不是 production 或真实 API 合同失败；同节点此前的 `plan_provider_probe(spec=...)` 正向调用已执行并通过。

授权同一 adopter 在 `STATIC_ONLY` 下最小返工：

1. 仅修改 `tests/integration/test_m3_successor_upstream_stage.py` 与既有 delivery；production、其他 tests、taskbook（本节经理追加除外）和 review 冻结。
2. 在该真实 API 正向节点中先建立唯一 test-owned `plan_root` 父目录，再把同一 `plan_root` 传给 `_context`；不得修改 support、production builder、自动创建语义或错误处理来掩盖 fixture 前置。
3. 保持 `plan_provider_probe(spec=...)` 与 `build_backtest_plan_artifact(..., artifact_roots={"PROJECT": ...})` 的真实未 mock 调用、原参数、返回类型/identity断言及负向反例不变；不得改回 `inspect.signature`、源码字符串或 mock 替代。
4. delivery记录现象、根因、父目录所有权规则、最小复现、修正测试、通过条件及 evidence root `artifacts/agent_runs/m3-r2a-validation4-20260826T065000Z/`，并绑定 focused stdout SHA `A9C0E7066543EE0427FB07A05E6C8F81722E387C9E7B0CE21FA24E5C72ACFA6A`、summary SHA `6CA985A9291DE2A8818F761D389E6B3771A3C123C9EA7B973027446E6B438BDC`。此前 carrier-invalid root只保留为承载失败历史，不计产品证据。
5. 原独立 reviewer 复验 production SHA不变、仅fixture父目录前置修正且两个真实 API 正向合同仍可达。PASS后重新申请完整 VALIDATION5：identity→focused exact4→Ruff production2/tests4→mypy production2→cold production2→exact9 scope/residue；不沿用本轮focused为整包通过。

全程零Python、pytest、Ruff、mypy、cold、真实Qlib、network、actual worker、new root、retained、stage或commit。状态上限仍 `EXECUTABLE_STAGE_SUBSTRATE_VALIDATED` 候选，不关闭bridge/CLI/M3 Gate。

## 15. VALIDATION5 真实 API fixture authority 隔离返工（2026-08-26）

VALIDATION5 有效证据：identity PASS；focused exact4 `73 passed / 1 failed / 374354 warnings`；Ruff、mypy、cold、scope均 `UNRUN`。§14父目录问题已关闭，真实 `plan_provider_probe(spec=...)` 正向已通过。唯一失败仍位于同一新增integration节点：第一套provider support执行后，第二套backtest-plan深层support复用同一 monkeypatch authority，在feature artifact构造阶段被稳定归一为 `M3_FEATURE_ARTIFACT_INVALID`，尚未进入backtest-plan正向调用。

授权同一 adopter 在 `STATIC_ONLY` 下做 test-only 最小隔离：

