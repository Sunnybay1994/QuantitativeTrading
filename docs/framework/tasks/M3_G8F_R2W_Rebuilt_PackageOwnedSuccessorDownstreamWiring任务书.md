# M3-G8F-R2W Rebuilt Package-Owned Successor Downstream Wiring 任务书

状态：`TASK_READY / WINDOWS_ENGINEERING_VALIDATED`（仅表示 Windows 工程向可执行 downstream wiring 已验证；**不**表示 actual worker、真实 Qlib、new root、retained、acceptance 或 M3 Gate 完成）

- task id：`M3-G8F-R2W-REBUILT-PACKAGE-OWNED-SUCCESSOR-DOWNSTREAM-WIRING`
- exact base / HEAD：`1d9b4e09c91293de18fea5cf0aa563b782379d37`
- branch：`codex/m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2w-package-owned-successor-downstream-wiring-rebuilt`
- resource：`STATIC_ONLY`；Python、真实 I/O 与验证另行申请

## 1. 目标、前序事故与本次重冻

旧 R2W 基于 `eca54af...` 静态审计后正确 `CONTRACT_STOP`：当时 successor Gate 同时把聚合 Gate identity 当作 physical receipt scope key，导致真实 reproducibility、readiness、acceptance stage receipt 无法接线。该旧 worktree 只读保留为事故证据，不得继续写入或机械复制 placeholder。

R2I 已合流并闭合 physical receipt identity：reproducibility 使用真实 `comparison_key`，acceptance 使用真实 `acceptance_key`，acceptance receipt 的 G8 root 由 stage-aware runtime verifier 解释，aggregate Gate identity 与 physical scope key 分离。旧 STOP 只剩 readiness cardinality 冲突，本任务重冻为一个全局 readiness physical receipt。

目标是在 package 内实现 downstream formal/Gate wiring，并把 canonical production dependencies 收敛为零参数 factory。终态上限为 `R2W_WINDOWS_ENGINEERING_VALIDATED`。

## 2. 唯一写白名单（exact12）与职责

1. `src/quant/research/m3/successor_runtime.py`
2. `src/quant/research/m3/successor_upstream_stage.py`
3. `src/quant/research/m3/successor_downstream_stage.py`（new）
4. `tests/unit/test_m3_successor_runtime.py`
5. `tests/integration/test_m3_successor_runtime.py`
6. `tests/unit/test_m3_successor_upstream_stage.py`
7. `tests/integration/test_m3_successor_upstream_stage.py`
8. `tests/unit/test_m3_successor_downstream_stage.py`（new）
9. `tests/integration/test_m3_successor_downstream_stage.py`（new）
10. `docs/framework/tasks/M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring任务书.md`
11. `docs/framework/deliveries/M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring交付报告.md`
12. `docs/framework/reviews/M3_G8F_R2W_Rebuilt_PackageOwnedSuccessorDownstreamWiring独立初验报告.md`

经理唯一写 10；实现者只写 1–9、11；独立 reviewer 只写 12。禁止修改 formal、reproducibility、readiness、acceptance、quality、R2S、orchestration、config、`__init__.py`、schema、roadmap或共享 SSOT。

## 3. Readiness 单一物理 receipt 合同

- public readiness evidence 是 G1 release、config、runtime、provider 的全局闭包，不具有 fold 维度。
- successor readiness `GateExecution.receipt_refs` 必须精确一个：`stage="readiness-evidence"`、`scope="ACCEPTANCE"`、`fold=None`、`horizon=None`、`scope_key` 为 public stage 的真实 `readiness_key`。
- 两折及 prior Gate 的聚合闭包继续由 `GateExecution.identity == compute_successor_gate_identity(...)` 承担；不得把 aggregate identity 写入 physical receipt ref。
- 禁止把同一 path/SHA 复制成两个 fold slot，禁止发明 fold readiness key，禁止放宽 R2I 的 path/SHA/semantic-owner 单射。
- 缺失、多于一个、fold/horizon 非空、错 stage/scope/readiness key、same bytes different path、same path different bytes均稳定 fail closed。

## 4. Formal prior closure 与 package-owned API

- `SuccessorProductionFormalStageRunner` 必须显式消费 stable-sorted `prior_refs`；每次 backtest/tracking 前从确定 receipt path fresh 验证并重建 typed upstream closure。
- tracking 必须看到同 fold、同 horizon、同 request 的真实 backtest receipt；缺失、重复、乱序、跨 fold/horizon/request 或 output identity 漂移均拒绝。
- `successor_upstream_stage.py` 只允许增加窄 package-owned fresh-rehydrate API；不得公开 `_SharedUpstream`、sibling underscore import、glob/latest/tree scan、隐式 mutable cache或 caller artifact。
- 新 `successor_downstream_stage.py` 唯一拥有并实现现有 Protocol 的十个 callable：formal run、fold verify、summary verify、repro run/verify、readiness run/verify、acceptance run/verify、terminal verify。
- 只能组合既有 public backtest、tracking、R2S summary、reproducibility、readiness、quality/acceptance API；不得复制科学计算、receipt schema、fold/horizon/Gate顺序。
- tracking client 只能从冻结 config 的 canonical tracking URI 通过既有 public factory 构造，不得由 caller 注入。

## 5. Canonical dependency authority

- `make_canonical_successor_production_dependencies()` 改为零参数 factory，按 `is` 绑定 R2A upstream、R2S summary与本包十个 downstream functions。
- adapter 构造时逐项验证 exact function identity。lambda、partial、wrapper、monkeypatch、伪 bundle、marker、替换 verifier/runner/tracking client均 `SUCCESSOR_INPUT_INVALID`。
- formal、reproducibility、readiness、acceptance与terminal必须从显式 plan/receipt closure fresh rehydrate；cache hit仍重验 bytes、outputs、scope与ownership。

## 6. Gate 与 terminal 不变量

- summary：每 horizon一份真实 R2S receipt。
- reproducibility：每 fold×horizon一份真实 public receipt，ref scope key逐字为各自 `comparison_key`。
- readiness：全局一份真实 public receipt，按 §3。
- acceptance：唯一一份真实 public receipt，ref scope key逐字为 `acceptance_key`；G8 root只由R2I stage-aware verifier处理。
- `status="PASS"` 只能来自真实 public stage结果及随后专属 fresh verifier；禁止合成receipt、硬编码PASS、手工路径或跳过 verifier。
- terminal verifier重新闭合当前 Gate、全部 prior Gates、fold receipts、physical ownership、aggregate identity与controlled-tree identity后才返回成功。

## 7. 必测对抗

至少覆盖：

1. readiness 0/2 receipts、fold-bound ref、错physical key、复制同path/SHA双fold、same bytes different path。
2. formal prior refs缺/多/重/乱序、跨fold/horizon/request；tracking缺对应backtest或引用另一horizon。
3. receipt bytes、alias/path/size/digest、plan output spec漂移；磁盘存在伪latest但显式ref缺失仍拒绝。
4. wrapper/lambda/partial/monkeypatch替换任一 canonical callable；caller注入tracking client、bundle、StageRunner或artifact。
5. summary/repro/readiness/acceptance cardinality、顺序、physical scope key、aggregate identity漂移。
6. Gate runner返回合成receipt、伪PASS、跳过fresh verifier；cache后artifact或receipt篡改。
7. R2I回归：same SHA/different path、same path/different SHA、semantic owner冲突、acceptance G8错误root全部拒绝。

## 8. 实现、报告与验证

当前只授权外部实现 Agent `STATIC_ONLY`：零 Python、pytest、Ruff、mypy、cold、actual worker、真实 Qlib、network、new root、retained、stage/commit。

delivery 必须记录旧 STOP 如何被 R2I 与本次 readiness 重冻解除，并逐项写明“现象—根因—应遵循规则—最小复现—新增测试—通过条件”、修改路径、API调用图与未运行边界。完成后由未参与实现的另一全新外部会话独立初验，至少增加一个实现者未用的 physical receipt/aggregate identity 对抗反例。

review PASS 后才可申请 Windows 定向验证：identity → exact相关unit/integration → Ruff实际Python → mypy production → cold → exact12 scope/diff/temp/process。Windows绿不替代 actual worker、真实Qlib、new root、retained或M3 Gate。

## 9. STOP 与退出条件

以下任一立即在 delivery 留证并 STOP：

- exact12不足或需要修改任何禁止模块/API/schema；
- public API仍无法从显式 refs 完成强类型 fresh closure；
- 需要 caller injection、wrapper、目录扫描、隐式cache、placeholder、手工receipt或复制Gate顺序；
- base/branch/worktree漂移、第二writer或白名单外dirty。

静态交付要求 actual dirty只属exact12、cached=0、`git diff --check` PASS，无临时文件、真实产物或凭据。

## 10. STATIC_REWORK1：public summary verifier 与 tracking 行为反例

独立初验结论为 `REVIEW_FAIL / 2×P1`。保持同一原实现者与 exact12；review报告只读，完成后交回同一reviewer复验。仍为零Python STATIC_ONLY。

### F1 — Summary Gate必须调用R2S public fresh verifier

- 现象：`verify_successor_summary_gate` 仅验证receipt bytes与shape，没有调用canonical bundle中的 `summary_verifier`。
- 规则：每个horizon的summary ref必须从显式receipt定位final artifact，fresh重建R2S verifier所需的强类型publication/upstream identity，并调用exact `apis.summary_verifier`；只有两个horizon均fresh通过且与refs/aggregate gate identity闭合才可返回成功。
- 禁止自己重复R2S科学/schema验证、仅检查JSON/receipt、以bool/marker冒充、异常后fallback或caller注入verifier。
- 测试必须证明summary_verifier每horizon exact1；缺调用、wrapper替换、返回wrong artifact/identity、一个horizon tamper均fail closed。

### F2 — Tracking必须有真实行为级prior closure测试

- 新增行为测试，不接受源码字符串/API存在性替代：tracking transition缺同fold同horizon backtest receipt、引用另一horizon、另一fold、另一request、重复/乱序backtest ref均在handler/public tracking调用前稳定拒绝。
- 正向必须证明tracking只消费当前fold/horizon的fresh-verified backtest closure；磁盘存在伪latest但显式ref缺失仍拒绝。
- observer/spies不得改变StageRunner/receipt/handler语义，不得用假receipt绕过fresh verification。

### F3 — Readiness physical-vs-aggregate对抗

- 新增reviewer反例：唯一readiness ref的 `scope_key` 被替换为aggregate `gate.identity` 时必须拒绝，即使两者都是合法hex、receipt其他字段与Gate status均看似闭合。
- 保持exact一个global physical readiness receipt、fold/horizon None与two-fold aggregate identity分域。

delivery追加F1–F3“现象—根因—规则—最小复现—新增测试—通过条件”。若调用R2S public verifier需要修改R2S或白名单外API，立即CONTRACT_STOP并给精确签名证据，不得复制verifier。

## 11. VALIDATION1 F4：public返回类型测试边界

VALIDATION1有效证据：identity PASS；unit `74 passed / 1 failed`；integration、Ruff、mypy、cold、scope UNRUN。资源、临时目录与0xF00已释放。失败只发生在测试的全文件字符串断言，不构成production红。

- 现象：测试扫描整个 `successor_upstream_stage.py` 文本并禁止 `-> _SharedUpstream`，误命中合法私有 `_reconstruct_shared_upstream(...) -> _SharedUpstream`。
- 规则：任务合同只禁止三个public rehydrate API泄露私有返回类型；模块内部私有helper可使用 `_SharedUpstream`。
- 返工范围仅 `tests/unit/test_m3_successor_upstream_stage.py`、taskbook与delivery；全部production、其他tests与review字节冻结。
- 将全文件字符串断言改为精确目标函数边界：用AST/signature只定位三个public rehydrate def，逐一断言公开强类型返回annotation；不得因另一个private def出现同字符串而失败。
- 保持或补直接返回对象exact type、私有字段不泄露、caller不能注入 `_SharedUpstream` 的行为反例。
- 禁止通过删除私有helper annotation、改production返回类型、宽泛Any/type-ignore或放宽public合同假绿。

delivery追加F4“现象—根因—规则—最小复现—修正测试—通过条件”，如实记录74绿/1失败与后续UNRUN。完成后同一reviewer只读复验test-only diff；PASS后申请新的完整VALIDATION2，不继承本轮为整包PASS。

## 12. VALIDATION2 F5：downstream同类public返回类型误检

VALIDATION2有效证据：Parser/identity PASS；unit `79 passed / 1 failed`，耗时654.69s；integration、Ruff、mypy、cold、scope UNRUN。证据根为 `artifacts/agent_runs/m3-r2w-rebuilt-validation2-20260826T132000Z/`，unit stdout SHA为 `c4c8b32a2643865f8e16b85cb9d11525ba15ad055d9c66f0728f5283aa6a43af`。资源、临时目录、cache与0xF00均已释放。

- 现象：F4只修正了`tests/unit/test_m3_successor_upstream_stage.py`，实际同类全文件字符串断言仍存在于`tests/unit/test_m3_successor_downstream_stage.py:148`，继续误命中合法private `_reconstruct_shared_upstream(...) -> _SharedUpstream`。
- 根因与规则沿用F4：只禁止public rehydrate API泄露私有返回类型；private helper可显式返回`_SharedUpstream`。
- 本轮返工只允许修改 `tests/unit/test_m3_successor_downstream_stage.py`、本任务书与delivery；production、其他tests与review报告在实现交付前冻结。
- 用AST与`inspect.signature`精确定位三个public rehydrate API并断言其公开强类型返回annotation；不得扫描全文件禁止private annotation。
- 保持直接返回对象exact type、public字段无私有泄漏、caller不能通过kwargs注入私有对象的反例；禁止Any/type-ignore、删private annotation或改production假绿。
- delivery追加F5完整证据链；完成后仍由同一独立reviewer只读复验。复验PASS后申请新的完整VALIDATION3，不继承VALIDATION2为整包PASS。

## 13. VALIDATION3 F6：integration fixture共享subprocess authority恢复

VALIDATION3有效证据：Parser/identity PASS；unit `84 passed`；integration `41 passed / 1 failed`，耗时710.56s；Ruff、mypy、cold、scope UNRUN。证据根为 `artifacts/agent_runs/m3-r2w-rebuilt-validation3-20260826T140000Z/`，integration stdout SHA为 `19059559a9abcb7510dd67b5bf1aed41140bdde7d8b1b755aa870181e7843b73`。资源、temp/cache与0xF00已释放。

- 唯一失败位于`tests/integration/test_m3_successor_upstream_stage.py::test_integration_real_api_positive_probe_and_project_roots`的Authority B fixture构造；`plan_support._context`深层feature support把底层异常归一为`M3_FEATURE_ARTIFACT_INVALID`，尚未进入本包production目标路径。
- Authority A通过shared Python `subprocess` module安装provider worker fake；Authority B需要真实feature worker。两段虽使用不同`MonkeyPatch.context()`，但测试没有像已验收`test_m3_summary_stage.py`那样显式捕获、恢复并断言`subprocess.run`、`provider_module.subprocess.run`及相关共享引用的exact callable authority。
- 本轮只允许修改`tests/integration/test_m3_successor_upstream_stage.py`、本任务书与delivery；全部production、其他tests与review在实现交付前冻结。
- 在进入Authority A前捕获exact原始`subprocess.run`；Authority A退出后、Authority B `_context`前，以测试自有窄helper恢复该exact callable并逐项断言所有共享module引用均`is`同一对象。可直接复用`test_m3_summary_stage.py`已证明的capture/restore模式，但不得import其private helper或复制业务fixture。
- 恢复只针对test-owned worker seam；不得用fake worker替代Authority B真实feature worker，不得吞异常、patch production verifier/builder、改变PYTHONPATH/cwd或放宽artifact identity。
- 增加回归断言：Authority A期间fake确实生效；退出后real callable exact恢复；Authority B前后无fake泄漏；若恢复失败立即在`_context`前以明确AssertionError暴露，不再被feature wrapper模糊为artifact invalid。
- delivery追加F6完整“现象—根因—authority规则—最小复现—修正测试—通过条件”。完成后由同一独立reviewer复验；PASS后申请完整VALIDATION4，不继承VALIDATION3为整包PASS。

## 14. VALIDATION4 F7：Authority B受控feature worker ownership

VALIDATION4再次得到unit `84 passed`，integration仍为 `41 passed / 1 failed`；Ruff、mypy、cold、scope UNRUN。F6已证明Authority A的provider dump fake在退出后exact恢复，因此A→B泄漏根因被排除；失败仍位于Authority B的legacy feature fixture、尚未进入本包production目标。

- 根因：`test_m3_feature_artifact._build_feature_bundle`会在入口捕获当时的shared `subprocess.run`，完成upstream provider fixture后把该exact callable恢复为feature worker authority。普通独立feature测试由测试自身先安装`_fake_feature_worker`；当前Authority B却把shared callable强制固定为真实`subprocess.run`，使深层feature artifact尝试真实worker并被归一为`M3_FEATURE_ARTIFACT_INVALID`。
- F6关于Authority A退出后必须恢复original的断言保留；但Authority B进入`plan_support._context`前，必须在其独立`plan_mp`内显式安装`feature_support._fake_feature_worker`作为test-owned feature worker seam，并断言三处shared module引用exact `is`同一fake。
- `plan_support._context`返回后立即恢复F6捕获的original real callable并断言shared引用一致；随后真实调用`build_backtest_plan_artifact`。因此只有深层fixture feature worker被fake，任务目标backtest-plan builder/verifier保持真实。
- 禁止复用Authority A的provider dump fake、禁止把feature fake留到target builder之后、禁止patch production backtest builder/verifier、吞异常或放宽artifact identity。
- 本轮只允许修改`tests/integration/test_m3_successor_upstream_stage.py`、本任务书与delivery；production、其他tests与review冻结。
- 增加明确断言区分两种test authority：A的`_PROVIDER._fake_dump`与B的`feature_support._fake_feature_worker`不是同一对象；B前feature fake生效，B context后original恢复；任何跨段泄漏在production目标调用前失败。
- delivery追加F7完整证据链；同一独立reviewer复验后申请完整VALIDATION5。不得把VALIDATION4或此前部分绿冒充整包PASS。

## 15. VALIDATION8 F8：unit Authority B feature-worker seam

VALIDATION8首次形成可信本轮反馈：Parser/argv/identity均PASS；unit exact3为`82 passed / 2 failed`；integration、Ruff、mypy、cold、scope均UNRUN。两项失败均在新增unit节点调用`plan_support._context`后，经alignment→feature fixture进入`M3_FEATURE_ARTIFACT_INVALID`；真实`build_backtest_plan_artifact`尚未进入。

- 根因：F7只为integration Authority B安装了test-owned `feature_support._fake_feature_worker`；两个新增unit builder节点消费同一legacy `_context`，却遗漏同一fixture前置。
- 本轮仅允许原实现者修改`tests/unit/test_m3_successor_upstream_stage.py`、本任务书与delivery；全部production、其他tests和review冻结。
- 两个节点必须在`_context`前捕获original shared `subprocess.run`，安装exact feature-worker fake并断言它不是provider dump fake；`_context`返回后立即恢复original，再调用真实backtest-plan builder。
- 正常与异常路径均必须恢复；不得让feature fake泄漏到builder，不得stub production builder、吞异常或放宽artifact identity。
- 补seam进入、三处shared alias identity、非dump fake、退出恢复与异常安全断言；delivery记录现象—根因—authority规则—最小复现—修正测试—通过条件。

完成后仍由同一独立reviewer只读复验。复验PASS后申请完整VALIDATION9，不继承VALIDATION8的部分结果为整包PASS。

## 16. F8独立初验 P1：恢复positive节点的窄verifier seam

F8独立初验确认feature-worker seam本身满足§15，但实现者额外删除了positive PROJECT-only节点原有的`verify_target_artifact`窄stub。该删除未获授权，并会让测试在真实builder前先命中legacy fixture receipt alias=`root`与PROJECT-only root的已知漂移，无法验证本节点冻结的`artifact_roots={"PROJECT": project_root}`目标。

- 同一原实现者仅在positive节点恢复对`plan_module.verify_target_artifact`的原窄stub，返回`context`已经构造的真实target；不得伪造target或改builder。
- §15 feature-worker seam及其正常/异常恢复全部保留；stub只隔离既有legacy alias，不得泄漏到wrong-alias节点。
- wrong-alias节点不新增任何verifier stub，继续由真实production路径拒绝`EXTERNAL_QLIB`。
- production、其他tests和review冻结；delivery纠正“移除verifier stub”的旧表述并记录现象—根因—规则—最小复现—修正—通过条件。

完成后交同一reviewer复验。仅复验PASS后申请完整VALIDATION9。

## 17. VALIDATION9 F10：integration positive verifier seam

VALIDATION9有效结果：Parser/argv/identity PASS；unit exact3=`84 passed`；integration exact3=`41 passed / 1 failed`；Ruff、mypy、cold、scope均UNRUN。唯一失败已越过Authority-B feature fixture并真实进入`build_backtest_plan_artifact`，随后归一为`M3_BACKTEST_PLAN_ARTIFACT_INVALID`。

- 根因与§16相同：F7额外删除了positive integration节点原有的`verify_target_artifact`窄stub；legacy context receipt alias=`root`与本节点PROJECT-only root身份不同，fresh target verifier先拒绝。
- 同一原实现者本轮仅修改`tests/integration/test_m3_successor_upstream_stage.py`、本任务书与delivery；production、unit与review冻结。
- 在Authority B context返回、feature-worker original恢复后，用更窄的`MonkeyPatch.context()`只包裹positive builder调用：`plan_module.verify_target_artifact`仅返回context真实target。
- positive调用结束立即撤销该stub；wrong-alias调用必须在stub已撤销后走真实production verifier并继续拒绝`EXTERNAL_QLIB`。不得让stub覆盖wrong-alias、不得stub builder或伪造target。
- 保留F6/F7 shared subprocess authority、feature-worker seam及真实builder；补stub进入/退出、wrong-alias无stub的生命周期断言。
- delivery记录现象—根因—规则—最小复现—修正测试—通过条件及VALIDATION9证据SHA。

完成后由同一reviewer复验。复验PASS后申请完整VALIDATION10，不继承部分绿为整包PASS。

## 18. VALIDATION10 F11：七处 canonical 返回类型 SSOT 与 config float 收窄

VALIDATION10 有效结果：Parser/argv/identity PASS；unit exact3=`84 passed`；integration exact3=`42 passed`；Ruff exact9 PASS；mypy production3 **STOP**（`successor_downstream_stage.py` 共 21 个错误）；cold/scope **UNRUN**。

- 现象：mypy 将 `SuccessorPublicApiBundle` 七个 stage/audit callable 的返回值视为 `object`，下游属性访问（`receipt_path`/`receipt`/`report`/`decision` 等）报 `attr-defined`；`float(acceptance[...])` 对 `object` 报 `arg-type`。
- 根因：bundle 字段曾统一标注 `Callable[..., object]`，类型 SSOT 未对齐 public formal/readiness/acceptance 结果类型；config 容差用裸 `float()` 接受 bool/非精确类型/非有限值。
- 类型 SSOT：仅收窄七字段返回注解——`FormalBacktestStageResult`、`FormalTrackingStageResult`、`FormalReproducibilityResult`、`VerifiedReadinessEvidenceArtifact`（stage+verifier）、`FormalAcceptanceStageResult`、`AcceptanceDecisionV1`；`TYPE_CHECKING` + quoted concrete types；禁止 `Any`/`cast`/`type:ignore`/wrapper/duplicate DTO。
- 最小复现：对 production3 跑 mypy → 21 错全在 `successor_downstream_stage.py`；`float(True)`/`float("nan")` 可越过语义。
- 修正：`successor_runtime.py` 注解收窄；`successor_downstream_stage.py` 以 `_require_finite_config_float`（exact float + finite）替换裸 `float`；exact12 单测覆盖 canonical 注解/`is` 绑定、错误返回 fail-closed、bool/非有限/非法容差拒绝。
- 通过条件：注解与 factory `is` 身份不变；正常 Gate/receipt 路径不变；错误返回与非法 float 稳定 `SUCCESSOR_*` fail-closed；STATIC_ONLY 本轮不重跑 Python/pytest/Ruff/mypy/cold。

完成后交同一独立 reviewer 只读复验。复验 PASS 后才可申请**新的完整 VALIDATION11**（含 mypy）；不把 VALIDATION10 部分绿或本轮静态改动冒充整包 PASS。

## 19. VALIDATION11 F12：formal backtest/tracking 结果局部名分离

VALIDATION11 有效结果：identity PASS；unit=`57 passed`；integration=`29 passed`；Ruff PASS；mypy production3 **STOP**（`successor_downstream_stage.py:214` 单错）；cold/scope **UNRUN**。

- 现象：mypy `assignment`：同一 `try` 内局部名 `result` 先被标为 `FormalBacktestStageResult`，再赋 `FormalTrackingStageResult`。
- 根因：F11 收窄返回类型后，共享局部名使分支间类型不相容；非 API/行为错误。
- 最小复现：VALIDATION11 mypy → `:214 Incompatible types in assignment ... FormalTrackingStageResult / FormalBacktestStageResult`。
- 修正：仅改 `successor_downstream_stage.py`——`backtest_result` / `tracking_result`；调用、参数、顺序、`receipt_path`/`receipt` 消费、分支与 `SUCCESSOR_STAGE_INVALID` 归一保持逐字等价；禁止 `cast`/`Any`/`type:ignore`/union/wrapper/API 变更。本轮只写本文件 + 任务书 + delivery；tests/review 冻结。
- 通过条件：局部名语义分离；行为字节级不变（仅标识符）；STATIC_ONLY 不重跑 Python/checks。

完成后交同一独立 reviewer 只读复验。复验 PASS 后申请**完整 VALIDATION12**（须含 mypy）；不继承 VALIDATION11 部分绿或本轮静态改动为整包 PASS。

## 20. VALIDATION12 终态证据与组合口径（F12 后）

F12 局部名分离落地后，VALIDATION12 **PASS**（本轮未重写 production/tests；证据如实记录）。

组合证据口径（不得把任一历史 STOP 改写成 PASS）：

| 阶段 | 结果 | 说明 |
|---|---|---|
| VALIDATION10 | unit84 PASS；integration42 PASS；Ruff PASS；mypy **21 STOP**；cold/scope **UNRUN** | 历史类型合同 STOP；触发 F11 |
| F11 → VALIDATION11 | identity PASS；unit57 PASS；integration29 PASS；Ruff PASS；mypy **1 局部名 assignment STOP**；cold/scope **UNRUN** | 证据根 `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c`；unit `950b983d…cd252c`；integration `26493122…b2059`；Ruff `af352a86…2d9af`；mypy `4a4108d5…75fa2`；summary `034cd671…5ae64` |
| F12 → VALIDATION12 | identity PASS；Ruff（changed source）PASS；mypy production3 PASS；cold production3 PASS；exact12 / cached0 / diff / temp / process PASS | 证据根 `artifacts/agent_runs/m3-r2w-rebuilt-validation12-20260826T180000Z-c18d`；Ruff `af352a86…2d9af`；mypy `f6af9a42…8259c`；cold `30fe42e7…29023`；scope `1f4605b9…8f13f`；summary `2e0e2038…06405`；`reused_validation11=unit57_integration29_other_ruff` |

终态上限：`R2W_WINDOWS_ENGINEERING_VALIDATED` / 可执行 package-owned successor downstream wiring。**明确不**覆盖 actual worker、真实 Qlib、new root、retained 或 M3 Gate。
