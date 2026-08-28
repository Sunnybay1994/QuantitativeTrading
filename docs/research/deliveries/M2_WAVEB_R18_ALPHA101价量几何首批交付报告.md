# DELIVERED / STATIC_ONLY

任务：`M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY`

用户已明确解除此前的派发计数笔误：权威任务书 #3–#8 的六条实现者路径是完整且唯一的写入白名单。本报告仅由实现者维护；manager-owned taskbook/roadmap 与 reviewer report 保持只读。

当前交付状态：`DELIVERED / STATIC_ONLY`；资源约束：`CPU NONE`。本任务只实现 `alpha101_006`、`alpha101_012`、`alpha101_041`，复用既有 immutable bar snapshot、next-open label、R17 对称 redundancy、coverage/schedule/summary admission 与 lightweight research output contract；最高结论仍为 `RESEARCH_ONLY`，失败门禁为 `REJECTED`。

## RECOVERY_SUPERSESSION

- 旧 Worker3 thread：`01a03730...`（`notLoaded`）；旧 top turn：`01a03e73...`（`interrupted`）。
- 旧 implementation subagent：`01a03e71...`（`notLoaded` / turn `interrupted`）；不复用旧 agent。
- recovery 接管时唯一可见的 partial 实现路径为 `src/quant/factors/classic_sixth_batch.py`；其余实现者路径未改。
- 接管理由：恢复同一 exact base、branch 和唯一隔离 worktree 的未完成实现，避免创建第二 worker、worktree 或 branch，并继续沿用任务书冻结的 exact6 白名单。
- 新 implementation subagent：当前 Codex recovery implementation subagent（本平台未向任务上下文暴露 session UUID）。

## RECOVERY_SUPERSESSION — CURRENT AGENT

- 当前 agent identity：`M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY / fresh isolated implementation recovery subagent / Codex desktop / 2026-08-27`；本次继续使用既有唯一 worktree，未创建第二 worker、worktree 或 branch。
- 本次沿旧 interruption 事实继续，未删除或改写其历史含义；在旧 partial 基础上完成了任务书 implementer items #3–#8 的六条路径内静态收束：`classic_sixth_batch.py`、`run_classic_factors.py`、对应两个 unit test 文件、sixth batch TOML 配置和本交付报告。
- `alpha101_006` 冻结为 `-Corr(adjusted_open, raw_volume, 10 strict exchange sessions)`；`alpha101_012` 冻结为 `Sign(Delta(raw_volume, 1))*-Delta(adjusted_close, 1)`；`alpha101_041` 冻结为 `sqrt(raw_high*raw_low)-amount/volume`，保留 raw CNY/share 与 amount/volume 单位。缺失窗口、零方差、非正因子分母、非有限值、重复键、越历法日期和算术失败均 fail-closed。
- runner 已接入 sixth factor identity、精确配置/成本语义校验、原始 config digest、成本 input digest、共享 panel/fold/label/evaluator/admission/output contract 与 `RESEARCH_ONLY` 边界；未改候选定义、共享 evaluator/schema/repository/publisher/facade、R17 语义、Gate 或路线图。
- 静态审查仅在上述六条白名单路径内完成；未运行 Python、pytest、Ruff、mypy、cold import、真实 run、网络、数据 I/O、PAPER 或其他 worker，也未提交或合流。因此本报告不宣称任何运行时/Gate 通过；后续需由授权验收链执行冻结的验证命令。
- 本次没有真实阻断，未追加 `STOP`；此前静态交付标记为 `DELIVERY_READY`，本轮状态更新为 `DELIVERED / STATIC_ONLY`；最高研究结论仍为 `RESEARCH_ONLY`，失败状态仍为 `REJECTED`。

## CURRENT STATIC_REWORK — P1

- 现象：sixth mocked-main orchestration test 已锁定 raw config SHA、成本 input 和执行顺序，但 publisher callback 原先丢弃 `output_payloads`，没有对 sixth batch 的完整输出集合及顺序作断言；delivery 顶部状态也仍为 `IN_PROGRESS`。
- 根因：上一轮 recovery 只覆盖了身份与成本绑定证据，遗漏了 manager clarification 要求的 exact 13-output no-extra/no-missing 静态锁定，并未同步更新交付状态。
- 应遵循规则：P1.1 只锁定既有 sixth-batch 的 13 个输出键、raw config SHA 和 cost input；不得修改 production output set。no-clobber/public verify 仍由 manager/统筹在真实 run 后按既有 publisher/verifier 语义处理。P1.2 要求交付报告状态与静态边界一致；不得把静态测试内容表述为运行时或 Gate 通过。
- 最小复现：在 `test_sixth_batch_main_binds_raw_config_and_cost_before_snapshot` 的 `publish(..., output_payloads)` 回调中执行 `del output_payloads`，即无法发现输出键缺失、额外或顺序漂移。
- 补充测试：同一测试现捕获 `output_payloads`，并按任务书顺序断言恰好为 `daily_ic.parquet`、`factor_catalog.json`、`factor_summary.parquet`、`fold_metrics.parquet`、`group_returns.parquet`、`portfolio_nav.parquet`、`report.json`、`targets.parquet`、`redundancy_daily.parquet`、`redundancy_summary.parquet`、`factor_coverage_daily.parquet`、`factor_coverage_summary.parquet`、`rebalance_schedule_alignment.parquet`；本轮未执行该测试。
- 通过条件：静态审查可确认上述断言是唯一 sixth mocked-main 输出锁；报告顶部和正文保持 `DELIVERED / STATIC_ONLY`，并明确未运行 Python、pytest、Ruff、mypy、cold、真实 run、网络、数据 I/O、PAPER，未进行 runtime/Gate 验证。

## FINAL_STATIC_HANDOFF

- exact6 写入范围最终闭合为：`src/quant/factors/classic_sixth_batch.py`、`src/quant/research/run_classic_factors.py`、`tests/unit/test_classic_sixth_batch.py`、`tests/unit/test_run_classic_factors.py`、`configs/research/m2_classic_daily_factors_sixth_batch.toml` 与本报告；manager taskbook/roadmap、reviewer report、shared evaluator/schema/repository/publisher/facade、data/raw、run_state、financial clean 均未写入。
- factor 实现覆盖 exact 10/9 session、symbol×session 缺口、零方差、volume=0、跨 symbol 隔离、正/零/负 volume delta、正/零/负 adjusted-price delta、raw unit/adj_factor 隔离、amount/volume 非正、负值、溢出、duplicate key、calendar escape、bool/NaN/Inf、乱序/重复 sessions 与输入行置换。
- runner/config 静态覆盖 sixth public identity、strict nested key/value/type/trial/fold/cost/snapshot validation、raw config SHA、cost input 先于 snapshot、13 个输出键的 no-extra/no-missing 顺序锁、共享 panel/folds/horizons/schedule/admission 与 `RESEARCH_ONLY → REJECTED` 边界；Alpha006 rolling correlation 的非有限结果也整次拒绝，legacy report field 不被 sixth 字段污染。
- 已执行的非 Python 静态检查：`git -c core.quotePath=false status --short`、`git -c core.quotePath=false diff --name-only` 与 `git -c core.quotePath=false diff --check`；`diff --check` 通过，终端仅报告 Git 的 LF/CRLF 提示。现场保留 manager-owned roadmap 修改与 taskbook 未跟踪文件，未将其视为本实现者变更。
- 按 `STATIC_ONLY / CPU NONE` 明确未运行 Python、pytest、Ruff、mypy、cold import、TOML runtime parse、真实 run、network、data I/O、PAPER、进程/资源探针或 commit；故本报告只提供静态交付，不宣称 runtime、fresh verify、真实 snapshot、artifact no-clobber 或任何项目 Gate 通过。下一步由授权经理/独立初验/统筹验收链执行。
- recovery 现场身份核对：exact base `91a11058961824d934cde5bacf4b3c97c5aa1552`，branch `codex/m2-waveb-r18-alpha101-price-volume-geometry`，worktree `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-waveb-r18-alpha101-price-volume-geometry`；未创建第二 worktree/branch，未提交。

## STATIC_REWORK P1-001

- review report：`docs/research/reviews/M2_WAVEB_R18_ALPHA101价量几何首批独立初验报告.md`。
- 现象：`_aggregate_redundancy_by_factor` 原先只校验 `median_abs_rank_corr` 为非布尔、数值且有限，负值或大于 `1` 的有限值仍可能进入最大值聚合，随后被 admission 当作普通 redundancy 结果处理。
- 根因：redundancy correlation 的基础域约束未在聚合这一唯一权威 contract boundary 固化；下游 threshold `0.80` 只能判断上限，不能替代 `[0, 1]` 输入域校验，也不能保证 malformed upstream value 在 admission 前被拒绝。
- 应遵循规则：在保留有限 `Decimal`/`int`/`float` 与既有对称端点、self-pair、重复/反向重复、无 incident、精确 `0.80` rejection 和 `REJECTED` 不升级语义的前提下，`median_abs_rank_corr` 必须严格属于闭区间 `[0, 1]`；越界输入必须在 max aggregation/admission 前确定性抛出 `ValueError`，不得静默转为 `REJECTED`。
- 最小复现：构造一条 `candidate`–`reference` redundancy incident，分别令 `median_abs_rank_corr = -0.01` 或 `1.01`，直接进入 `apply_fourth_batch_admission_gates`；旧实现未在该输入域边界拒绝，无法证明 malformed upstream value 被 fail-closed 截断。
- 新增测试：`test_redundancy_correlation_range_fails_closed_before_admission` 参数化覆盖 `negative` 与 `greater-than-one`，通过既有 admission 调用路径断言越界值抛出 `ValueError("...between 0 and 1...")`，不产生 `REJECTED` 结果。
- 本轮实现：在 `_aggregate_redundancy_by_factor` 的有限性校验之后、pair/max 聚合之前增加 `[0, 1]` 闭区间校验；未改 production output set、因子模块、配置、共享组件或 Gate 语义。
- 通过条件：负值和大于 `1` 的有限 numeric correlation 均在聚合/admission 前确定性失败；合法 `Decimal`/`int`/`float`、边界 `0`/`1`、对称端点、self-pair、duplicate/reverse-duplicate、无 incident、`0.80` 严格 rejection 与既有 `REJECTED` non-upgrade 行为保持原合同。测试文件本轮仅静态写入，未执行任何 Python、pytest、Ruff、mypy、cold、真实 run、network、data I/O、PAPER、runtime 或 Gate 验证。

## STATIC_REWORK VALIDATION3-P1-ALPHA006-ZERO-VARIANCE

- 中央 Validation3 证据：identity `PASS`；collect `87`；focused 边界为 `60 passed / 1 failed / 194 warnings`；失败节点为 `test_alpha006_gap_and_zero_variance_are_null_without_cross_gap_bridging`，实际错误为 `ValueError('sixth-batch factor arithmetic is non-finite')`。focused stdout SHA：`7dd05dc1a5cfb1a813d72a03c21c72424abb7c12b692a4596c44b73db6dc869c`；summary SHA：`7b1e0036d1f955605f1adbe73b8cdcf99c9cf5e5f777f884504e44b6358a54bd`；resource 已释放。
- 现象：有限正值的 flat-open 零方差窗口在 Alpha006 应输出 `null`，但 `_alpha006_corr` 的 rolling correlation 非有限结果先触发了整批 `ValueError`，因此该测试在取得 Alpha006 后续 null 分支前失败。
- 根因：global non-finite arithmetic rejection 错误地包含 `_alpha006_corr`；rolling correlation 的零方差 NaN/null 是该因子窗口级 insufficiency，不是源数据或必须整批拒绝的 arithmetic failure。
- 应遵循规则：保留源字段 bool/NaN/Inf 的整批拒绝、adjusted open/close 与 `high*low` arithmetic 拒绝，以及 Alpha012 delta、Alpha041 VWAP/geometric arithmetic 的整批拒绝；仅让 `_alpha006_corr` 通过后续 `is_not_null() & is_finite()` 分支，令零方差窗口的 `alpha101_006` 为 `null`。不得吞异常、放宽源检查、改变公式/window/ddof/session/output contract。
- 最小复现：对十个严格连续 session 使用有限正值且 `open` 全部为 `100.0`，rolling correlation 的一侧零方差，旧实现进入 `sixth-batch factor arithmetic is non-finite`；同样使用 `volume` 全部为 `1000.0` 可构造 flat-volume 零方差对抗。
- 新增测试：保留原 `flat_open` 断言，并在 `test_alpha006_gap_and_zero_variance_are_null_without_cross_gap_bridging` 中加入全正 flat-volume fixture；断言 Alpha006 尾窗为 `null`，Alpha012 后九行和 Alpha041 全部仍可计算，证明零方差只影响该 Alpha006 窗口而不 batch-reject 其他因子/行。
- 本轮实现：从 global non-finite arithmetic rejection 中移除 `_alpha006_corr`，保留其后续 null 化 guard 以及全部源值和其他因子 arithmetic fail-closed 语义；未修改 runner/config/shared files 或 Alpha006 公式、窗口、ddof、session/output schema。
- 通过条件：flat-open 与 flat-volume 零方差均不再抛整批错误，Alpha006 对受影响窗口返回 `null`，可计算的 Alpha012/041 结果和其他行保留；Validation3 的 `60 passed / 1 failed / 194 warnings` 仅为已提供的失败基线，本轮未运行 Python、pytest、Ruff、mypy、cold、真实 run、数据 I/O、network、PAPER、scope 检查或任何 runtime/Gate 验证。

## STATIC_REWORK VALIDATION5-RUFF-F401

- 现象：Validation5 parser `PASS`、identity `PASS`、collect `87`，focused 为 `61 passed / 214 warnings`；Ruff 首个失败为 `F401 tests/unit/test_run_classic_factors.py:15 unused import SIXTH_BATCH_FACTOR_NAMES`。focused stdout SHA：`d07cd67b2d57492fb0392fa5500dbc5c4960bd1e781386d886b37507fb0e4d23`；Ruff stdout SHA：`7a68d3533f928a711fcb8121d2f2ef826ce99f4b2726ded297d08602ed775b11`；summary SHA：`fa76212ee31f4509d852b321815090672e500dec461c0234039f1871e3638324`；resource 已释放。
- 根因：`tests/unit/test_run_classic_factors.py` 保留了未使用的 `SIXTH_BATCH_FACTOR_NAMES` 直接导入；sixth mocked-main 测试实际通过 authoritative `classic_runner.SIXTH_BATCH_FACTOR_NAMES` 取 identity，因此该直导入是冗余的静态依赖。
- 应遵循规则：按最小 F401 修复删除未使用导入，保留测试逻辑及 authoritative runner identity，不改 production code、factor/config/shared contract 或输出集合；静态交付仍保持 `DELIVERED / STATIC_ONLY`，不得把 focused/Ruff 证据升级为 runtime 或 Gate 结论。
- 最小复现：在测试文件保留 `from quant.factors.classic_sixth_batch import SIXTH_BATCH_FACTOR_NAMES`，但 sixth 测试仅引用 `classic_runner.SIXTH_BATCH_FACTOR_NAMES`，Ruff 即报告该 direct import 为 F401。
- 本轮修复与证据：仅删除上述未使用 direct import；未改变测试逻辑。Validation5 的 `61 passed / 214 warnings` 是已提供的 focused 基线，Ruff F401 及其 stdout/summary SHA 为本轮静态修复依据；mypy、cold、scope 与其他验证均保持 `UNRUN`。
- 通过条件：测试文件不再含该未使用 direct import，sixth identity 继续唯一来自 `classic_runner.SIXTH_BATCH_FACTOR_NAMES`，后续授权 Ruff 不再报告该 F401；本轮未运行 Python、Ruff、pytest、mypy、cold、check、真实 run、data I/O、network、PAPER、commit 或 merge。

## STATIC_REWORK VALIDATION7-TYPE-NARROWING

- 身份与历史：本轮使用中央批准的 `AUTHORIZED_IMPLEMENTER_REPLACEMENT`，因为原 implementation Worker 因 usage limit 不可用且其 implementation subagent 已完成退出；本轮不是恢复或冒充原实现链，不创建第二 worktree/branch，继续本任务唯一 worktree/branch。taskbook 与 roadmap 保持只读。
- Validation7 原始可信边界（按任务书原文保留）：Validation7 的可信边界为：parser、identity、collect（87）、focused（61 passed / 214 warnings）与 Ruff exact 4 均通过；mypy 在 `src/quant/research/run_classic_factors.py:2247` 首次失败后立即停止，cold 与 exact 9 scope 运行阶段未执行。资源已释放，退出后 actual exact 9、cached=0 与 diff-check 通过。
- Validation7 原始类型合同（按任务书原文保留）：唯一返工是 `_is_exact_float(value: object, expected: float)` 的可证明类型收窄：必须显式区分 `type(value) is int` 与 `type(value) is float`。exact `int` 可受控转换为 `float`，巨大整数转换发生 `OverflowError` 时返回 `False`；exact `float` 直接使用。`bool`、其他类型、非有限值继续返回 `False`，最终仍以 finite 且与 `expected` 精确相等为通过条件。禁止使用 `cast`、`Any`、`type: ignore` 或放宽数值语义。
- 现象：Validation7 中 parser、identity、collect（87）、focused（61 passed / 214 warnings）及 Ruff exact 4 均 PASS；mypy 在 `src/quant/research/run_classic_factors.py:2247` 首次失败并停止，cold 与 exact 9 scope 未运行。原 `_is_exact_float` 先用 `type(value) not in {int, float}` 检查，再对 `object` 直接调用 `float(value)`，mypy 无法证明该转换安全。
- 根因：集合成员类型检查没有为静态类型分析建立 `object → int|float` 的显式分支收窄；同时既有实现把 int 与 float 合并为一次转换，未显式表达 exact int 的受控转换和 exact float 的直接使用。
- 应遵循规则：`_is_exact_float(value: object, expected: float)` 必须显式区分 `type(value) is int` 与 `type(value) is float`。exact int 仅在受控 `float` 转换中使用，巨大 int 的 `OverflowError` 返回 `False`；exact float 直接使用；bool 与其他类型返回 `False`；非有限值返回 `False`；最终仍要求与 `expected` 精确相等。禁止 `cast`、`Any`、`type: ignore`，不改变数值语义、API 或运行边界。
- 最小复现：传入 `object` 类型值并执行 `float(value)`，即使运行时值来自 int/float 集合检查，mypy 仍报告 `arg-type`；以 `True`、自定义数值类型或巨大整数分别验证时，合同要求它们继续返回 `False`，不能借由放宽类型检查接受。
- 本轮实现：仅在 `src/quant/research/run_classic_factors.py` 将 helper 改为 exact int / exact float 显式分支；int 分支捕获 `OverflowError`，float 分支直接复用值，其他类型立即拒绝，最后统一执行 `math.isfinite` 与精确 equality。仅在本交付报告追加本节；未改 taskbook、roadmap、review、测试、配置、因子或其他路径。
- 测试/证据边界：按 `STATIC_ONLY / CPU NONE` 本轮未运行 Python、pytest、Ruff、mypy、cold、exact 9 scope、真实 run、数据 I/O、网络、PAPER、进程/资源探针、stage、commit 或 merge。保留 Validation7 原始可信边界及证据：parser/identity/collect87/focused61/Ruff exact4 PASS；mypy 首失败、cold/scope UNRUN；资源已释放。四个 SHA-256 原样保留：summary `ceeb33518406b81b77c1ec4a982655844e70d7c9991106c5bfa1783089f45797`；focused stdout `aace7211267a07dc8a7c27c3a943a3b4e8e902e894b5663403039fd2753ad733`；Ruff stdout `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`；mypy stdout `2a109d8da4deb7d86b501d91c19410ae742fafa41e2bbb217496ef1c7ed3c415`。
- 通过条件：独立 reviewer 只读确认 helper 具备可证明的 exact int/float 收窄、巨大 int `OverflowError → False`、bool/其他/nonfinite 拒绝与 exact equality；并确认本轮仅有两个授权路径变化且旧失败证据完整保留。review PASS 后，才可按任务书申请 postfix validation（identity → focused 或中央裁定的最小回归 → Ruff source → mypy production2 → cold → exact9 scope）；本交付本身不宣称 mypy、runtime 或任何 Gate 通过。

## AUTHORITATIVE_FINAL_STATE — R18 REAL-RUN CLOSEOUT

- 终态：Validation8 产品阶段与 Validation9 Unicode/NUL-safe scope 阶段均已完成；随后唯一一次真实 run 的 preflight 通过 exact bar snapshot、manifest、canonical cost、零历史同 hypothesis attempt 与 no-clobber target 检查，但在 publication 前由 `build_diagnostic_factor_targets` 的 chosen-outcome 完整性 Gate 停止。一次另行授权的 controlled diagnostic 只复现到同一 fail-closed 点，publish 入口未到达。
- 真实运行证据：Validation8 summary SHA-256 为 `0dc6e322a1d516b6488e5eec32eab1b939bc4f581d915773978c4399ba578f6f`；Validation9 summary SHA-256 为 `cee62b541c2d5a10bd8848c51fb0e77fae6168787aebc207759045a64382f8aa`；real-run evidence summary SHA-256 为 `5e33b2db06804f0ab9ccd13386a6895f9a84c28a02f323be57c4666e13502702`，其 preflight stdout SHA-256 为 `b7b1055cd105578d4a1792ed0d93e349102fe82bd33c1b3bd137c04dc022cdd4`、run stderr SHA-256 为 `07a3251151352d877502443f34dcaa90cfa94ad6e78c7a98009b30b15b694017`，run stdout 为空（SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`），summary 终态为 `STOP=REAL_RUN_FAILED`。
- 受控诊断证据：diagnostic summary SHA-256 为 `bb915e3b80cf1d0feb9b0fe63cfb964cd8b8d3dc96e7b0caa235024730d80452`；diagnostic stdout SHA-256 为 `97f13af2c938385f066e0f9a3584c8ec14da71bf5fc3f3fb5b654bf87eaedac4`，stderr SHA-256 为 `3690fa9ee6120192baee931cc3ab0e85daeeae33488d4515fed71a5b2e524283`；其 preflight stdout 沿用 `b7b1055cd105578d4a1792ed0d93e349102fe82bd33c1b3bd137c04dc022cdd4`。诊断记录：`alpha101_006`、fold `1`、`as_of=2022-01-04`、首个 builder call 的 chosen Top50 中 exact 一个 holding-period return 为 null；execution/exit 日期均唯一、非空、类型与顺序合法，return nonfinite count 为 `0`。
- 经济裁定：不得按未来 outcome 是否存在预过滤排名候选，不得替补第 51 名，不得事后跳过该调仓期，也不得将不完整 Top50 重新加权。上述处理会引入未来可得性、改变预注册组合或改变收益样本；chosen-outcome Gate 的 fail-closed 行为正确，production/test/config 不修。
- 权威状态：本包冻结为 `STOPPED_BEFORE_PUBLICATION / DIAGNOSTIC_SELECTED_TARGET_OUTCOMES_INVALID / EXACT_ONE_SELECTED_RETURN_NULL`。没有 `run_id`、immutable run、13 outputs、manifest、public verification 或 canonical retained publication。
- 候选结论：`alpha101_006 / alpha101_012 / alpha101_041` 均为 `UNASSESSED/HOLD`，不是 `REJECTED`；不得据此声称任一因子有效或无效。
- Trial ledger 与后续授权：本 package 按 `trial_delta=3` 计入既有 trial ledger 边界；不得删除 evidence、改写状态或只重跑未到达候选以恢复三个 slots，且该记录不得冒充完整研究 trial 结果。唯一真实 run 授权已消耗；第二次真实 run 必须由用户重新明确授权、在新任务身份中重新预注册，不得从本次诊断授权或本任务推定。
- 历史保留与边界：Validation1—9、真实 run、controlled diagnostic、Validation7 类型返工及此前所有 STOP/失败证据均保留；本 closeout 只追加本 delivery，未修改 production、tests、config、taskbook、roadmap、review 或其他路径。真实 run / diagnostic 之外没有新增运行授权；本报告不把任何 STOP 现场升级为 Gate 通过。
