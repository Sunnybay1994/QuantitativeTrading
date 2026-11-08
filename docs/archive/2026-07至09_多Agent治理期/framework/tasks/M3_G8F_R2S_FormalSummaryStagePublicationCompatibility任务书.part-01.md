# M3-G8F-R2S Formal Summary Stage Publication Compatibility 任务书

状态：`R2S_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION8 Windows 工程验证闭合；**不**表示 R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained 或 M3 Gate 完成）

- task id：`M3-G8F-R2S-FORMAL-SUMMARY-STAGE-PUBLICATION-COMPAT`
- exact base：`57dcf2e579175ead8d7c833ed7fb4b7bccedc5c5`
- branch：`codex/m3-g8f-r2s-formal-summary-stage-publication-compat`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2s-formal-summary-stage-publication-compat`
- 目标终态：`FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED`（尚未宣告；当前仅 Windows 工程验证闭合）
- 工程验证证据：`artifacts/agent_runs/m3-r2s-validation8-20260826T032000/`（见 §22）

## 1. 背景与根因

R2A rebuilt 静态实现发现真实 G5：`make_summary_run_plan` 的 canonical publication 根为 `summaries/{experiment_key}/h{horizon}/{model}/{model_version}`，而 legacy `build_research_summary_artifact` / `verify_research_summary_artifact` 强制根叶名为 `horizon={n}`；`StageRunner` handler 的临时根又是 `.stage-tmp` 随机目录。三者当前不可组合。

本包只补足 formal summary 的 StageRunner-shaped publication compatibility。不得改 plan、StageRunner、receipt/schema或summary科学语义；不得用搬运、rename、手工receipt或伪GateExecution绕过。

## 2. exact8 与角色

1. `src/quant/research/m3/evaluate.py`
2. `src/quant/research/m3/summary_stage.py`（新）
3. `tests/unit/test_m3_formal_research_summary_artifact.py`
4. `tests/unit/test_m3_summary_stage.py`（新）
5. `tests/integration/test_m3_summary_stage.py`（新）
6. `docs/framework/tasks/M3_G8F_R2S_FormalSummaryStagePublicationCompatibility任务书.md`（经理独占）
7. `docs/framework/deliveries/M3_G8F_R2S_FormalSummaryStagePublicationCompatibility交付报告.md`（实现者独占）
8. `docs/framework/reviews/M3_G8F_R2S_FormalSummaryStagePublicationCompatibility独立初验报告.md`（初验者独占）

实现者只写 1–5、7；任务书与 review 只读。初验者只读 1–7、唯一写 8。白名单或合同不足时写 delivery 并 STOP，不自行扩围。

## 3. 冻结 API 名称与职责

### 3.1 `evaluate.py`

新增 frozen exact type：

- `FormalSummaryStagePublicationIdentity`

exact fields：

- `stage_root: Path`
- `node_id: str`
- `final_relative_path: PurePosixPath`
- `experiment_key: str`
- `horizon_sessions: Literal[5, 10]`
- `model: str`
- `model_version: str`

新增 exact public callables：

- `build_research_summary_stage_artifact(...) -> ResearchSummaryManifestV1`
- `verify_research_summary_stage_precommit(...) -> VerifiedResearchSummaryArtifact`
- `verify_research_summary_stage_artifact(...) -> VerifiedResearchSummaryArtifact`

三者必须复用 legacy formal summary 的同一科学计算与 canonical serialization，不复制公式或字段。legacy `build_research_summary_artifact` / `verify_research_summary_artifact` 的签名、`horizon={n}` 根规则、输出文件集合、bytes、schema、identity与错误语义保持不变。

### 3.2 `summary_stage.py`

新增 exact public types/callables：

- frozen `FormalSummaryStageResult`
- `run_formal_summary_stage(...) -> FormalSummaryStageResult`

`FormalSummaryStageResult` 至少持有：`final_root`、`receipt_path`、fresh typed `verified`、verified stage `receipt`、`reused`；必须在 `__post_init__` 检查 exact concrete types 与身份闭包。

`run_formal_summary_stage` 的显式输入必须包含：canonical `stage_root`、PROJECT-only `artifact_roots`、`LoadedM3Config`、完整 formal evaluations/context、experiment、horizon，以及 `resume: bool`。不得接受 caller handler/verifier、marker、raw receipt或任意 publication path。

## 4. Publication identity 与两阶段验证

1. `final_relative_path` 必须逐字等于 canonical summary plan node 的 `StaticDirectoryPublication.final_directory`，即 `summaries/{experiment_key}/h{horizon}/{model}/{model_version}`；model/version须由 exact evaluation closure 唯一导出，禁止 caller 自述覆盖。
2. `stage_root` 与所有 Path 要求当前平台 exact concrete `type(Path())`、绝对、真实、无 symlink/reparse；root alias只允许 PROJECT。
3. stage build 仅接受 StageRunner-owned temp root：位于 `stage_root/.stage-tmp` 的直属随机 leaf，leaf 与 exact `node_id` 前缀闭合，初始为空。任意临时目录、嵌套目录、非空目录、alias/ancestry漂移拒绝。
4. precommit verifier只验证同一 publication identity绑定的 temp root，并要求 `SUMMARY_STAGE_SPEC` exact顶层 outputs；少、多、嵌套、额外文件或子目录全部拒绝。
5. final verifier只接受 `stage_root / final_relative_path` 与 canonical plan node `receipt_path`，fresh验证 artifact bytes、receipt outputs与identity。precommit/final必须是不同强类型函数，不用 bool/字符串模式切换。
6. temp到final由唯一 `StageRunner.run_static` 完成；本包不得自行移动、复制、rename或发布文件。

## 5. 唯一 StageRunner wiring

`run_formal_summary_stage` 必须：

1. 调用现有 `make_summary_run_plan` 构造完整 plan；
2. 用 `select_run_plan_nodes` 要求 exact `SUMMARY` continuation 与唯一 canonical node；0/2 node、少/多/重、publication/output/spec drift均拒绝；
3. 创建 canonical PROJECT-only `StageRunner`；
4. handler只调用 stage build与precommit verifier，并返回与 `SUMMARY_STAGE_SPEC` outputs逐项一致的 `StageBuildReport`；
5. `run_static(..., plan=complete_plan)`，closure verifier只调用precommit verifier；
6. 发布后调用final typed verifier，对 final root、receipt path/bytes/outputs fresh闭合；
7. 返回 `FormalSummaryStageResult`。resume=true只允许 exact plan/receipt/artifact复用；任何tamper均fail closed。

不得复制 `make_summary_run_plan`、`SUMMARY_STAGE_SPEC`、StageRunner、summary公式或 receipt；不得创建 `GateExecution`。

## 6. 必须覆盖的反例

至少覆盖：

- legacy build/verify调用、`horizon={n}`规则、bytes/path/schema逐字回归；stage与legacy对同经济输入生成exact相同summary文件bytes；
- arbitrary temp、wrong `.stage-tmp` ancestry、wrong node prefix、symlink/reparse、非空temp；
- wrong experiment/horizon/model/version/final relative/final root/receipt path；
- plan 0/2 nodes、node/spec/output/publication drift；handler outputs少/多/嵌套/额外目录；
- 手工receipt、手工publication、GateExecution冒充拒绝；
- exact resume复用；manifest/artifact/receipt/output digest任一tamper拒绝；
- evaluation/input顺序变化不改变canonical结果；重复或冲突identity拒绝。

独立初验必须新增实现者未使用的对抗性反例，优先挑战 precommit temp identity 与 final root 之间的 TOCTOU、Path alias 或 reparse 漂移。

## 7. 错误与禁止项

- 错误沿现有 `M3StageRunnerError` 稳定码，禁止泄露绝对路径、payload或底层cause/context。
- `STATIC_ONLY`：禁止 Python、pytest、Ruff、mypy、cold、真实Qlib、网络、actual worker、新root真实运行、retained、stage/commit。
- 禁止修改 orchestration、StageRunner、successor_runtime、config、`__init__.py`、共享SSOT或R2A STOP现场。
- 若不改 orchestration/StageRunner 就无法证明 temp→final publication identity，必须带精确源码证据 STOP。

## 8. 交付与验收

实现者在 delivery 写明现象—根因—规则—最小复现—新增测试—通过条件、exact diff及未运行边界。全新独立 reviewer只写唯一review报告，输出 `REVIEW_PASS`/`REVIEW_FAIL`。静态初验通过后，经理再申请Windows定向验证资源。

本包即使最终通过，也只关闭 summary publication compatibility；不表示 R2A、bridge/CLI、actual worker、真实Qlib、new root、retained或M3 Gate完成。

## 9. STATIC_REWORK1：`evaluate.py` EOL 最小变更闭包

首次 `DELIVERY_READY` 的语义路径位于 exact8 内，但 `evaluate.py` 由基线 CRLF 整文件变为 LF，使 Git 显示 825 行非语义改写，违反最小变更和可审查性要求。

同一原实现会话仅做如下静态返工：

1. 恢复 `evaluate.py` 与 base 一致的 CRLF 物理换行，保留已交付的语义增量；
2. `git diff --ignore-space-at-eol` 所见语义 diff 不得因本返工增减，其他 production/test 字节不得改动；
3. delivery 记录现象、根因、规则、最小复现与通过条件；
4. 通过条件：普通 `git diff --check` PASS，`evaluate.py` 不再出现整文件换行噪声，exact8 范围不变。

本返工仍为 `STATIC_ONLY`，禁止运行 Python/测试/静态检查；完成后才允许启动全新独立初验会话。

## 10. ARCHITECTURE_STOP 与 CONTRACT_REFREEZE_B：三阶段 typed verification

首次交付将 precommit verifier 实现为 temp/final 双相接口。根因是现有 `StageRunner._run_static_locked` 对同一 `closure_verifier` 分别以 temp、发布后 final、preexisting/reuse final root 调用；而原§5又要求 closure 只调用 temp-only precommit。两者不可同时满足。本节取代原§4–§5中与此冲突的表述，delivery 中“precommit 接受 temp 或 final”也必须标明为已被 supersede。

### 10.1 三个互斥强类型阶段

1. `verify_research_summary_stage_precommit`：严格 temp-only；仅接受 identity 绑定的 `stage_root/.stage-tmp` 直属随机 leaf、exact node 前缀、真实非 symlink/reparse 目录与 `SUMMARY_STAGE_SPEC` exact outputs。
2. `verify_research_summary_stage_publication`：独立 final-root-only、pre-receipt verifier；仅接受 identity 中 exact `stage_root/final_relative_path`，fresh 验证 artifact bytes/schema/科学 identity/exact outputs，不得要求尚未发布的 receipt。
3. `verify_research_summary_stage_artifact`：严格 post-run final+receipt；仅在 `StageRunner` 返回 `StaticStageResult` 后调用，闭合 exact final root、receipt path/bytes/inputs/outputs 与 artifact identity。

temp 不能进入 publication/artifact，final 不能进入 precommit，artifact 缺失或错误 receipt 必须拒绝。

### 10.2 唯一 module-private closure dispatcher

`summary_stage.py` 为 `StageRunner` 构造唯一 package-owned module-private dispatcher。它只接受 runner 传入的 root，闭包捕获已验证 publication identity 与科学输入：

- root exact等于canonical final root时，只调用 final publication verifier；
- 否则必须先逐项证明是合法 StageRunner-owned temp root，再只调用 temp precommit verifier；
- 禁止“先尝试temp，catch后改当final”的 fallback；任一 phase 失败原样 fail closed，不得重解释为另一 phase；
- 不接受 caller bool/string/mode/marker/verifier注入，不公开 phase 选择 authority。

arbitrary root、final父/子alias、相似prefix、wrong node、symlink/reparse均拒绝。

### 10.3 执行顺序与反例

`make_summary_run_plan` → exact node/publication identity 选择 → handler仅build并返回 `StageBuildReport` → `StageRunner.run_static` 使用上述dispatcher → 返回后调用post-run final+receipt verifier → `FormalSummaryStageResult`。temp→final仍只由StageRunner完成。

测试必须锁定：

- fresh publish路由temp precommit + final publication + post-run receipt；resume路由final publication + post-run receipt且不调用temp；
- preexisting-no-receipt recovery按StageRunner既有序列fresh final closure，tamper fail closed；
- dispatcher无fallback：合法temp内容tamper不转final，canonical final tamper不转temp；
- arbitrary/alias/prefix/reparse、plan output/receipt drift、TOCTOU反例；legacy签名、`horizon={n}`、bytes/schema不变。

若 exact8 仍无法实现三阶段，或 StageRunner 不提供足够 root identity 区分证据，必须再次 STOP，不得修改 orchestration。独立初验必须等本返工 `DELIVERY_READY` 后才能启动。

## 11. STATIC_REWORK2：EOL 误恢复后的语义重建

STATIC_REWORK1 错误地将 `evaluate.py` 整文件恢复为 base，导致首次交付中已批准的 stage publication 语义丢失，且未更新 delivery。该结果不是有效交付。

同一原实现会话必须：

1. 以当前 base `evaluate.py` 为干净起点，按§3–§6与§10重建批准的 publication identity、共享科学计算抽取和三阶段 typed verifier；
2. 不得从历史工作文件整文件覆盖；未修改基线行保持 base 物理字节，新增/修改 hunk 使用与 Git diff-check 兼容的 LF，不得产生 CR 尾随空白；
3. 同步修正 `summary_stage.py` 与既有新测试，删除 temp/final fallback，实现§10的唯一 dispatcher 与三阶段互斥反例；
4. delivery 追加 ARCHITECTURE_STOP、CONTRACT_REFREEZE_B、EOL误恢复事故及本次最终 exact diff，明确旧“precommit temp/final”表述已失效；
5. 终态只能是 `DELIVERY_READY` 或带精确证据的 `STOP`。仍禁止 Python/测试/静态检查/网络/commit/review 报告修改。

通过条件：actual dirty仍只在 exact8，`evaluate.py` 只显示语义 hunks，ordinary `git diff --check` PASS，三阶段互斥与 dispatcher 无fallback可由静态测试证明。

## 12. MANAGER_STATIC_REWORK3：preexisting final without receipt

三阶段实现静态准入通过，但测试未覆盖§10明确要求的 preexisting-no-receipt recovery。同一原实现会话仅在 exact8 内补最小反例并更新delivery：

1. 先通过真实 `run_formal_summary_stage` 形成 canonical final root，再精确删除对应receipt，构成“final存在但receipt缺失”；
2. 内容未漂移时，再次 `resume=True` 必须按 StageRunner 既有序列fresh调用 final publication closure，不调用temp precommit去“采信”final；恢复后post-run artifact+receipt闭合；
3. 另一反例在receipt缺失时篡改final artifact/manifest任一bytes，必须稳定fail closed，不发布新receipt，不转temp phase；
4. 测试必须锁定实际 phase调用序列与receipt是否出现，禁止只检查一个宽泛异常。

仍为 `STATIC_ONLY`，禁止 Python/测试/静态检查/网络/commit/review修改。完成 `DELIVERY_READY` 后才启动全新独立 reviewer。

## 13. REVIEW_FAIL → STATIC_REWORK4：temp leaf exact ownership 与 link/reparse 反例

独立初验增加对抗后返回两项 P1，均为真实合同缺口：

1. `_require_stage_temp_output_root` 仅使用 `startswith(f".{node_id}.")`。当 `model_version` 等 node identity 含点号且存在更长 sibling（例如 `v1` 与 `v1.2`）时，错误 sibling temp leaf 仍可吞掉该前缀。
2. 原§6明确要求 symlink/reparse 反例，当前测试未覆盖。

同一原实现会话在 exact8 内做最小 `STATIC_ONLY` 返工：

- temp leaf 必须分解为 exact `.{identity.node_id}.` 前缀加唯一非空随机后缀段；后缀不允许 `.`、路径分隔符或非 `tempfile.mkdtemp` 命名字符，从而拒绝更长 sibling node、籼似 prefix、空后缀与附加层级。不得仅换一个更长 `startswith`。
- 新增实现者反例：`v1` identity 必须拒绝 `v1.2` sibling temp leaf；另覆盖 temp/final root 的 symlink 及 Windows reparse/junction 或等价可执行属性注入，证明build、三阶段 verifier与dispatcher均fail closed。若host无法创建symlink，测试必须保留属性注入反例，不得整类缺失。
- delivery 按现象—根因—规则—最小复现—新增测试—通过条件记录本轮，不修改review报告。

禁止 Python/pytest/Ruff/mypy/cold/网络/commit。交付后交回同一独立 reviewer 复验；复验不得继承本次 FAIL 为 PASS。

## 14. REVIEW_FAIL → STATIC_REWORK5：dispatcher 原始叶身份闭包

§13 复验确认temp leaf exact ownership已闭合，但发现新的P1：`_make_summary_stage_closure_dispatcher` 在非跟随检查前对调用方root及candidate final执行 `resolve(strict=True)`，随后 `lstat` 的是解析目标，并把解析目标交给typed verifier。exact final lexical leaf若为symlink/junction/reparse，可能丢失原始叶身份并绕过typed verifier已有的 `abspath != resolve` / reparse拒绝。

同一原实现会话在exact8内执行最小 `STATIC_ONLY` 返工：

1. dispatcher不得在phase分类前resolve调用方root，也不得把resolved target替代原始root传给typed verifier。
2. root必须是当前平台exact native concrete `Path` 且absolute；只形成词法规范化的 `raw_absolute = Path(os.path.abspath(root))`。先对raw_absolute使用 `os.lstat` 非跟随验证，拒绝symlink、reparse/junction及非目录；任一失败fail closed。
3. candidate final由已绑定 `identity.stage_root` 与 `final_relative_path` 形成exact lexical absolute path。phase分类只能比较 `normcase(raw_absolute)` 与 `normcase(candidate_final_absolute)`，不得用resolve后等价判定。命中final时，publication verifier收到raw_absolute；否则precommit verifier收到raw_absolute，并由各typed verifier完成已有闭包。
4. 禁止catch typed verifier异常后回退另一phase；禁止新增bool/string/mode/verifier注入；不得放宽evaluate.py三个typed verifier、legacy bytes/path/schema或StageRunner合同。
5. candidate final若为symlink/junction/reparse，必须在任何成功publication前拒绝。不得先follow再检查target。
6. 新增reviewer R3反例：host支持时，在exact final lexical leaf创建指向独立真实artifact target的junction/symlink；direct publication verifier与dispatcher均拒绝，phase calls中不得出现成功publication，也不得fallback precommit。另锁定lexical alias、`..`或等价root不会因resolve被重解释为final。

delivery追加本轮现象、根因、规则、最小复现、新增测试与通过条件，并保留前两轮STOP历史。review报告只读。禁止Python/测试/静态检查/网络/commit；交付后由同一独立reviewer再次复验。

## 15. VALIDATION2 STOP 后的 STATIC_REWORK6：h10 fixture 字段归属

`VALIDATION2` 的Parser/BOM、argv sentinel与identity三重carrier自证通过；focused exact3有效执行得到 `9 passed / 14 failed`。14项失败统一发生在 `_stage_bundle` 构造h10 fixture时：`EvaluationManifestV1` 没有 `evaluation_receipt_sha256` 字段，该字段属于外层 `VerifiedEvaluationArtifact`；summary stage测试体尚未进入，因此不能计为production失败。Ruff、mypy、cold与scope均未运行。

同一原实现者仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；本任务书由经理更新，production、其他tests与review冻结：

1. h10必须分层构造：inner `replace(item.manifest, ...)` 仅传 `EvaluationManifestV1` 的合法字段 `horizon_sessions=10` 与对应 `work_key`；outer `replace(item, ...)` 设置新root、更新后的manifest及 `evaluation_receipt_sha256=receipt_sha`。
2. 精确删除manifest replace中的非法 `evaluation_receipt_sha256` keyword；不得给manifest新增字段、修改contracts或用 `Any` / `type: ignore` 绕过。
3. 保持现有receipt file与receipt_sha、h10 context、upstream path、fold/model identity闭包；不得预判后续失败而修改manifest schema、production verifier或其他fixture语义。
4. delivery记录F4的现象、根因、字段归属规则、最小复现、修正测试与通过条件，引用VALIDATION2 carrier三重PASS及9绿/14失败边界；不得把后续未运行阶段写成通过。

实现完成后交同一独立reviewer复验，确认production字节不变且outer receipt identity仍被summary消费。复验PASS后重新申请完整 `VALIDATION3`；当前零Python，不自行重跑。

## 16. VALIDATION3 STOP 后的 STATIC_REWORK7：canonical summary plan fixture 闭包

`VALIDATION3` 的 Parser/BOM、argv sentinel、identity carrier 均通过；focused exact3 有效执行得到 `18 passed / 5 failed`。五项失败统一发生在 `run_formal_summary_stage` 的 public plan/input 阶段，后续 Ruff、mypy、cold、scope 均未运行。根因不是 production verifier 或 `EvaluationFreshVerificationContext` 字段错位：`summary_stage.py` 先调用 `make_summary_run_plan`，后者在读取 horizon context 前要求每个 evaluation 的 `manifest.work_key` 逐字等于 `compute_work_key(experiment_key, fold, horizon)`，并要求 evaluation root/receipt 满足 public work publication tree。legacy h5 fixture 使用任意 `sha256("work-{index}")`，h10 又只同步 manifest，且两者 root/receipt 都不是 public builder 的 canonical 路径。

同一原实现会话仅修改 `tests/unit/test_m3_summary_stage.py` 与 delivery；production、其他 tests 与 review 冻结：

1. 对每个 h5/h10 fold+horizon 唯一计算 `canonical_work_key = compute_work_key(experiment_key, fold, horizon)`，逐字同步 `EvaluationManifestV1.work_key/horizon_sessions`、`EvaluationMetricsV1.work_key` 及其既有 horizon 字段、`EvaluationFreshVerificationContext.evaluation_spec.work_key/horizon_sessions`；h10 的 label/prediction horizon 同步保持。
2. 每项 fixture evaluation 使用显式 canonical 路径 `<upstream_stage_root>/work/<work_key>/evaluation`，receipt 使用 `<upstream_stage_root>/receipts/evaluation/<work_key>.json`。逐项构造，禁止 glob/latest/目录扫描/alias，所有 fold/horizon root 与 receipt 必须 physical distinct。
3. 复制 daily/metrics/manifest 测试字节后，凡对象字段改变，必须使用既有 canonical test helper 重写 metrics/manifest bytes并重新计算 outer `manifest_sha256`；`evaluation_receipt_sha256` 必须来自 canonical receipt 的实际 bytes。禁止内存对象与磁盘 bytes/SHA 漂移。
4. `ResearchSummaryUpstreamPaths` 按 evaluations exact 顺序引用 canonical receipts；`by_root` fresh-verifier mapping同步 canonical roots。
5. 新增 fixture 自证：每项 `manifest.work_key == metrics.work_key == context.evaluation_spec.work_key == compute_work_key(...)`；root/receipt exact canonical且physical distinct；`make_summary_run_plan` 可构造 h5+h10 exact nodes。
6. 保持 summary 科学内容、fold/model/version、StageRunner/dispatcher、三个 typed verifier及 R3 symlink/reparse 闭包不变；不处理无关 `VerifiedG1Release` repr。

delivery须记录 F5 的现象—根因—public plan identity/publication规则—最小复现—修正测试—通过条件，并保留 `VALIDATION3` 的18绿/5失败及后续UNRUN边界。当前仍为 `STATIC_ONLY`，禁止Python/pytest/Ruff/mypy/cold/网络/commit。完成后由同一独立reviewer只读复验，PASS后另申请完整 `VALIDATION4`。

## 17. VALIDATION4 STOP 后的 STATIC_REWORK8：formal experiment publication fixture 闭包

`VALIDATION4` 的 Parser/BOM、argv sentinel与identity均通过；focused exact3有效执行得到 `9 passed / 14 failed`。F5的evaluation canonical work key/root/receipt门禁已越过；14项失败统一发生于新增 `make_summary_run_plan` 自证的 `_experiment_boundary_inputs`。bundle中的对象exact type为 `VerifiedExperimentIdentity`，因此canonical stage必须是 `experiment-identity`，不能使用或改名冒充 `development-experiment-identity`。后续Ruff、mypy、cold、scope均未运行。

同一原实现者仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；production、其他tests与review冻结：

1. `_stage_bundle` 先显式materialize canonical formal experiment：root为 `<upstream_stage_root>/runs/<experiment_key>`；使用现有canonical test helper把同一 `ExperimentIdentityManifestV1` 写入 `experiment_manifest.json` 并从实际bytes重算 `manifest_sha256`；receipt为 `<upstream_stage_root>/receipts/experiment-identity/<experiment_key>.json`。
2. 优先复制/复用legacy已验证experiment receipt的exact bytes并重算outer receipt SHA，禁止发明第二套receipt schema。继续前必须静态证明原receipt bytes中的stage/scope/scope_key逐字满足formal `experiment-identity`；若实际为development receipt或无法证明，立即 `CONTRACT_STOP`，在delivery回报实际stage/scope/key，不自行生成替代receipt。
3. 返回新的 `VerifiedExperimentIdentity`，root/manifest/manifest SHA/receipt SHA必须与canonical磁盘bytes闭合；manifest经济字段、experiment key、config/scientific SHA不得变化。
4. bundle、`make_summary_run_plan`及全部h5/h10 evaluation materializer统一使用canonical experiment。
5. 每个 `EvaluationFreshVerificationContext` 同步 `context.experiment=canonical experiment`；并仅替换其 `evaluation_upstream_paths` 中 prediction→feature→fold 链的 `experiment_receipt_path` 为canonical formal receipt。snapshot/provider/fold/feature/label/alignment/model/prediction及其spec保持原对象/字节。
6. top-level `ResearchSummaryUpstreamPaths.experiment_receipt_path` 同步canonical receipt；F5的evaluation receipt顺序与physical-distinct闭包保持。
7. 新增fixture自证：exact type为 `VerifiedExperimentIdentity`；root/manifest/receipt canonical路径及outer SHA闭合；receipt若解析则stage/scope/scope_key exact formal identity；所有context.experiment为canonical object，嵌套experiment receipt path与top-level指向同一physical file；`make_summary_run_plan`越过experiment+evaluation boundary形成exact h5/h10 nodes。
8. 不扫描/glob/latest，不改production builder/verifier，不处理无关 `VerifiedG1Release` repr。

delivery须追加F6的现象—根因—formal stage/path/传播规则—最小复现—修正测试—通过条件，引用 `VALIDATION4` 9绿/14失败及后续UNRUN边界。当前仍为 `STATIC_ONLY`，禁止Python/测试/静态检查/网络/commit。交付后同一独立reviewer只读复验，PASS后申请完整 `VALIDATION5`。

## 18. CONTRACT_STOP 后的 STATIC_REWORK9：public formal experiment publication fixture

STATIC_REWORK8 的先验审计证明legacy receipt属于 `development-experiment-identity`，不能供exact `VerifiedExperimentIdentity` 的formal summary plan使用；原实现者按合同未改名冒充、未手写替代receipt并正确STOP。无需新增production前置包：现有公开链已能发布真实formal experiment identity。

同一原实现者仍仅修改 `tests/unit/test_m3_summary_stage.py` 与delivery；production、其他tests与review冻结：

1. 测试fixture必须通过现有公开API链 `make_experiment_identity_run_plan` → `StageRunner.run_experiment_identity` → `make_experiment_identity_handler` → typed output/final verifier，生成真实 `VerifiedExperimentIdentity`。不得手写、改名、复制formal receipt，也不得monkeypatch绕过experiment identity verifier。
2. receipt必须逐项闭合：stage=`experiment-identity`、scope=`EXPERIMENT`、canonical `runs/<experiment_key>/experiment_manifest.json` 与 `receipts/experiment-identity/<experiment_key>.json`、实际bytes/SHA一致。
3. 可只读复用现有experiment-identity测试支持以取得snapshot/provider/provider-validation/config/spec，但不得修改或cross-import其业务实现；public API仍是唯一发布者。
4. `_stage_bundle` 必须在构造canonical evaluations前切换到该formal experiment，并同步experiment key、scientific config identity、work key、evaluation manifest/metrics/spec、全部嵌套upstream experiment receipt paths及canonical bytes/SHA。
5. 增加先验断言：formal experiment exact对象、manifest、receipt stage/scope/path/SHA逐项闭合；development receipt不得进入summary plan或任何fresh context。
6. 保持h5/h10、fold、evaluation与summary publication语义不变；禁止修改production以接受development receipt。
7. 若无法让全部evaluation contexts与真实formal experiment逐项一致，立即再次 `CONTRACT_STOP`，不得用monkeypatch、marker或第二receipt绕过。

delivery须保留STATIC_REWORK8 STOP证据并追加本轮现象—根因—public publication规则—最小复现—修正测试—通过条件。当前为 `STATIC_ONLY`，禁止Python/pytest/Ruff/mypy/cold/network/stage/commit。交付后同一独立reviewer复验，PASS后再申请完整 `VALIDATION5`。

## 19. VALIDATION5 STOP 后的 STATIC_REWORK10：共享 worker monkeypatch 作用域隔离

