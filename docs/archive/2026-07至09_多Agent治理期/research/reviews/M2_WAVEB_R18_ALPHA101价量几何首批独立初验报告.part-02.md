- 原有 flat-open 覆盖仍在 `tests/unit/test_classic_sixth_batch.py:114-126`；新增 flat-volume fixture 在 `:128-139`，断言 Alpha006 尾窗为 null，同时 Alpha012 后九行与 Alpha041 全部可计算，证明零方差不会 batch-reject 其他可计算行/因子。
- 任意源 bool/NaN/Inf 的 fail-closed 参数化仍在 `tests/unit/test_classic_sixth_batch.py:248-280`；源字段检查与 `Bar1dSchema` 包装仍在 `src/quant/factors/classic_sixth_batch.py:67-87`。唯一的 `try/except` 仅将 schema 错误重新抛为 `ValueError`（`:75-79`），没有吞掉错误或绕过源检查。
- adjusted open/close 与 raw `high*low` 的非有限算术仍在 `src/quant/factors/classic_sixth_batch.py:89-98` 触发整批拒绝；Alpha012 delta 与 Alpha041 VWAP/geometric 的非有限 guard 仍在 `:193-202`，相关零分母/符号行为测试仍在 `tests/unit/test_classic_sixth_batch.py:154-228`。
- 最小复现：十个严格连续 session 的正 flat-open 或正 flat-volume 输入使 rolling correlation 产生零方差 null/NaN；修复后由 `:204-214` 输出 Alpha006 null，而不触发 `:193-202` 的整批 arithmetic exception。测试文本证明该预期，但本轮未执行。

### 交付证据、写入边界与未运行声明

- delivery report 已保留并明确 `DELIVERED / STATIC_ONLY`（`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:1-7`），且 Validation3 记录引用 stdout SHA `7dd05dc1a5cfb1a813d72a03c21c72424abb7c12b692a4596c44b73db6dc869c`、summary SHA `7b1e0036d1f955605f1adbe73b8cdcf99c9cf5e5f777f884504e44b6358a54bd`，结果为 `60 passed / 1 failed / 194 warnings`（`:55-64`）。该结果是修复前/验证基线证据，不能被改写为本轮运行通过。
- delivery 同一段保留 `RECOVERY_SUPERSESSION` 历史与此前交付边界；未运行 Ruff、mypy、cold、Python、pytest、real run、data I/O、network、PAPER 或 scope/runtime/Gate 验证，故本复验不推断任何 executable validation。
- 本轮三路径 scoped diff 仅涉及 factor、factor test 与 delivery 这三条允许路径；工作树中 roadmap、config、taskbook、review 及其他 sixth-package 状态是本轮前已存在的交付现场，未作为本轮新增写入。review 报告是唯一获准写入文件，且只追加本节；本结论不声称工作树 clean。

### Validation3 通过条件

- flat-open 与 flat-volume 零方差均静态落入 Alpha006 后续 null-and-finite filtering；源值和其他因子算术非有限仍 fail-closed；公式、window、ddof、session、output schema 与既有测试合同保持不变。
- flat-volume 测试静态断言 Alpha012/Alpha041 的可计算结果保留，未以 try/except 吞错或通过放宽 source validation 取得绿色表象。以上条件满足；剩余 `60 passed / 1 failed / 194 warnings` 仅作为未执行本轮验证的历史边界保留。

## VALIDATION5 F401 RECHECK — RECHECK_PASS / STATIC_ONLY

### 1. 身份、范围与结论

- 本轮 reviewer 仍为未参与实现/返工的独立上下文；已读取 R18 taskbook、delivery、既有 review 以及目标 runner/module/test。未调用 implementation context，未创建第二 reviewer、worker、外部 session、顶层 task 或 worktree。
- 本轮只做静态文本、源码引用和 Git scope 核对；唯一写入本 review 文件尾部，历史 `REVIEW_FAIL`、P1/Validation3 复验及其证据均保留。
- 结论：`RECHECK_PASS`，因此 F401 复验结论为 `REVIEW_PASS`。这是 `STATIC_ONLY / CPU NONE` 的静态复验，不是 executable validation、runtime、真实数据或项目 Gate 通过。

### 2. F401 direct-import 核对

- `tests/unit/test_run_classic_factors.py` 当前 import 区（`:1-35`）不再包含 `from quant.factors.classic_sixth_batch import SIXTH_BATCH_FACTOR_NAMES`；全文搜索也未发现该 direct import。
- 当前文件对 sixth identity 的唯一引用为 `tests/unit/test_run_classic_factors.py:820` 的 `factor_names = classic_runner.SIXTH_BATCH_FACTOR_NAMES`。因此 Validation5 报告的 `F401 ...:15 unused import SIXTH_BATCH_FACTOR_NAMES` 对应冗余 direct import 已静态删除，未以别名或复制常量绕过。
- 本项只确认当前源码文本，不把交付报告中历史 Ruff 首个失败当作本轮命令执行结果。

### 3. 权威 identity 与测试逻辑/输出断言

- `src/quant/factors/classic_sixth_batch.py:13-31` 定义 `SIXTH_BATCH_FACTOR_SPECS`，并在 `:33` 由 `tuple(spec.name for spec in SIXTH_BATCH_FACTOR_SPECS)` 形成 `SIXTH_BATCH_FACTOR_NAMES`；`src/quant/research/run_classic_factors.py:47-50` 仅导入该公共 identity，未复制第二份名称集合。
- runner 在 `src/quant/research/run_classic_factors.py:312`、`:460`、`:656` 及 sixth validator/report 路径继续以 `SIXTH_BATCH_FACTOR_NAMES` 做 batch 判定、factor branch、coverage 与 names/factors identity 核对；sixth branch 仍使用 `SIXTH_BATCH_FACTOR_SPECS` 和 sixth compute 的结果 join。
- `tests/unit/test_run_classic_factors.py:820-850` 的 mocked-main sixth compute、redundancy、coverage 和 schedule 数据均由 `classic_runner.SIXTH_BATCH_FACTOR_NAMES` 驱动；`:983-1000` 保留 cost→snapshot 顺序、single sixth compute、captured run 以及 exact 13 个 output key 的 no-extra/no-missing/order 断言。未见因移除 direct import 而漂移测试逻辑或输出断言。

### 4. Delivery Validation5 证据映射

- delivery `docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:66-73` 明确记录：parser `PASS`、identity `PASS`、collect `87`、focused `61 passed / 214 warnings`，以及首个 Ruff F401 为该未使用 direct import。
- 同一记录保留 focused stdout SHA `d07cd67b2d57492fb0392fa5500dbc5c4960bd1e781386d886b37507fb0e4d23`、Ruff stdout SHA `7a68d3533f928a711fcb8121d2f2ef826ce99f4b2726ded297d08602ed775b11`、summary SHA `fa76212ee31f4509d852b321815090672e500dec461c0234039f1871e3638324`，并说明 resource 已释放。
- 这些是 delivery 提供的历史验证载荷；本 reviewer 未重新运行对应工具，亦未把 SHA 或 `61 passed` 升级为本轮执行证据。

### 5. Git 实际 scope 核对

- `git -c core.quotePath=false status --short` 实际为 exact9 dirty：roadmap、runner、runner test 三个 modified，加上 sixth config、delivery、review、taskbook、sixth factor module、sixth factor test 六个 untracked；无第十条路径。
- `git -c core.quotePath=false diff --name-only` 仅列出前三个 modified 路径；`git -c core.quotePath=false diff --cached --name-only` 为空（cached0）。untracked 六路径由 status 现场计入 exact9，未被误报为 staged。
- `git -c core.quotePath=false diff --check` 无错误；终端仅出现 Git 的 LF/CRLF 提示。除本 review 文件尾部追加外，本轮未写入其他路径，未 stage、未 commit、未 merge。

### 6. 未运行边界与通过条件

- 本轮严格未运行 Python、pytest、Ruff、mypy、cold import、TOML runtime parse、真实 run、network、data I/O、PAPER、进程/资源探针、commit 或 merge；delivery 中的 `mypy`、`cold` 与 `scope` 均继续保持 `UNRUN`，不得由本静态复验推断通过。
- 通过条件已静态满足：direct import 不存在；测试只经 `classic_runner.SIXTH_BATCH_FACTOR_NAMES` 使用权威 identity；mocked-main 的 sixth 逻辑和 exact 13-output 顺序断言保持；delivery 的 parser/identity/collect87、61 passed、三项 SHA 及未运行边界记录准确；Git 为 exact9 dirty、cached0、diff-check 无错误且无额外路径。
- `RECHECK_PASS` 仅关闭本次 F401 静态复验项；后续仍须由授权验收链执行未运行的 mypy/cold/scope 及其他冻结验证，不能据此宣布 runtime/Gate/真实研究结果通过。

## VALIDATION7 TYPE REWORK REVIEW_PASS / STATIC_ONLY

### 1. 身份、输入与结论

- 本轮为未参与实现或返工的全新独立 reviewer；未复用 `/root/r18_f401_review`，未调用 implementation context，未创建第二 reviewer、worker、session、worktree 或 branch。
- 已完整读取当前 worktree 的 `AGENTS.md`、R18 taskbook §8、current delivery、目标 production helper 与本 review 全部历史；本轮唯一写入仍为本 review 报告本节。
- 结论：`VALIDATION7 TYPE REWORK REVIEW_PASS`。这是 `STATIC_ONLY / CPU NONE` 的源码、文档与 Git 静态复验，不是 mypy、runtime、真实数据、postfix validation 或项目 Gate 通过。

### 2. `_is_exact_float` 类型收窄与数值合同

- `src/quant/research/run_classic_factors.py:2243-2253` 以 `type(value) is int` 和 `type(value) is float` 明确分支；这为 `value: object` 建立了可证明的 `int | float` 窄化路径。
- exact `int` 分支唯一执行受控 `float(value)`，并在 `OverflowError` 时立即返回 `False`；因此巨大整数不会越过合同。exact `float` 分支直接复用已窄化的 float，不再对 object 调用转换。
- 其他类型立即返回 `False`；`type(value) is int` 明确排除 `bool`，两个 exact type 检查也排除自定义数值子类。统一尾部仍要求 `math.isfinite(numeric_value)` 且 `numeric_value == expected`，故 NaN、正负无穷及不相等值均拒绝，精确 equality 语义保持。
- helper 本节未使用 `cast`、`Any` 或 `type: ignore`，未改变 API、阈值、调用边界或其他数值语义。上述结论覆盖任务书要求的 bool、其他类型、自定义子类、巨大 int、非有限值和 exact expected equality 对抗面；本轮未运行测试或静态工具。

### 3. Delivery 证据与历史边界

- delivery `docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:75-86` 明确记录本轮为中央批准的 `AUTHORIZED_IMPLEMENTER_REPLACEMENT`，原 implementation Worker 及 subagent 的退出/不可用历史未被冒充为恢复；taskbook 与 roadmap 保持只读。
- 原 Validation7 可信边界仍准确保留：parser、identity、collect `87`、focused `61 passed / 214 warnings`、Ruff exact `4` 为历史 PASS；mypy 在 `src/quant/research/run_classic_factors.py:2247` 首失败后停止，cold 与 exact9 scope 为 `UNRUN`，资源已释放。
- 四个 SHA 与 taskbook §8 原样一致：summary `ceeb33518406b81b77c1ec4a982655844e70d7c9991106c5bfa1783089f45797`；focused stdout `aace7211267a07dc8a7c27c3a943a3b4e8e902e894b5663403039fd2753ad733`；Ruff stdout `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`；mypy stdout `2a109d8da4deb7d86b501d91c19410ae742fafa41e2bbb217496ef1c7ed3c415`。
- delivery 对通过条件的表述与合同一致：仅在独立 reviewer 静态确认 exact int/float 收窄、OverflowError→False、bool/其他/nonfinite 拒绝、exact equality 与旧失败证据完整保留后，才可申请 postfix validation；没有把本轮写入或历史 SHA 表述为 mypy/runtime/Gate 通过。

### 4. Git 实际 scope 与未运行边界

- 当前 `git -c core.quotePath=false status --short` 仍为 exact9 dirty：3 个 modified（roadmap、production runner、runner test）与 6 个 untracked（sixth config、delivery、review、taskbook、factor module、factor test），无第十条路径；这是既有唯一 worktree 的交付现场，不将其误报为 clean。
- `git -c core.quotePath=false diff --name-only` 仍仅列出 3 个 modified，`git -c core.quotePath=false diff --cached --name-only` 为空（cached0）；`git -c core.quotePath=false diff --check` exit `0`，仅有 LF/CRLF 提示。除本 review 报告本节追加外，本轮未写入其他路径，未 stage、未 commit、未 merge。
- 本轮严格未运行 Python、pytest、Ruff、mypy、cold、exact9 scope、真实 run、数据 I/O、网络、进程/资源探针或任何 postfix validation；不得从本静态 PASS 推断未运行 Gate。

### 5. 通过条件与后续

- Validation7 类型返工静态通过：helper 控制流和数值语义满足冻结合同；delivery 现象—根因—规则—最小复现—测试/证据—通过条件、四 SHA、`AUTHORIZED_IMPLEMENTER_REPLACEMENT`、resource release 及 cold/scope `UNRUN` 均完整且诚实；唯一 worktree/branch 与 exact9/cached0/diff-check 现场闭合。
- 本 `REVIEW_PASS` 只关闭 Validation7 静态类型返工项。现在可由授权链申请 postfix validation（identity → focused 或中央裁定的最小回归 → Ruff source → mypy production2 → cold → exact9 scope）；在其完成前，整体任务仍不得宣称 runtime、真实研究或项目 Gate 通过。

## R18 ECONOMIC POLICY AND EVIDENCE REVIEW_PASS / STATIC_ONLY

### 1. 身份、输入与结论

- 本轮继续由同一全新独立 reviewer 执行；未参与本轮 delivery 写入，未调用 implementation context，未创建第二 reviewer、worker、session、worktree 或 branch。
- 已完整读取 R18 taskbook §9、roadmap R18 exact hunk、delivery `AUTHORITATIVE_FINAL_STATE`，以及 Validation8、Validation9 scope、real-run、controlled-diagnostic 的持久 summary 与关键 stdout/stderr；本轮唯一写入仍为本 review 报告本节。
- 结论：`R18 ECONOMIC POLICY AND EVIDENCE REVIEW_PASS`。这是对既有终态、经济政策和证据链的静态复核；不把原生 run/diagnostic 载荷升级为本轮执行，也不把停止状态升级为研究或 Gate 通过。

### 2. chosen-outcome Gate 与经济政策

- `src/quant/research/classic_factor_evaluation.py:433-457` 的生产路径先按 factor 非空/有限值计算 score、稳定排序并固定 `chosen = cross_section.head(top_k)`，随后要求 execution/exit 唯一、日期合法、return 无 null 且全有限；失败才抛出 `ValueError("diagnostic selected target outcomes are invalid")`。它没有按未来 outcome 完整性预过滤证券，也没有第 51 名替补、跳过该调仓期或对不完整 Top50 重加权；合法路径固定 `weight = 1.0 / top_k`。
- 原生 real-run stderr 在 `run_classic_factors.py:1069` → `build_diagnostic_factor_targets` → `classic_factor_evaluation.py:456` 停止；controlled diagnostic stdout 精确记录 `factor=alpha101_006`、`fold=1`、`as_of=2022-01-04`、`chosen_count=50`、`return_null_count=1`、`return_nonfinite_count=0`，execution/exit 均唯一且合法。diagnostic wrapper 仅观察并复现原错误，且显式禁止 publication；没有生产修复或绕过 Gate。
- 因此“按未来 outcome 过滤后再排名”“用第 51 名补足”“事后跳期”或“不完整 Top50 重新加权”均是本轮明确拒绝的独立反例：任一做法都会改变信号时点可得性、预注册组合或收益样本，不能作为修复或经济结论。

### 3. 权威终态、候选状态与 trial ledger

- taskbook §9、roadmap R18 exact hunk 与 delivery 终态逐字一致：
  `STOPPED_BEFORE_PUBLICATION / DIAGNOSTIC_SELECTED_TARGET_OUTCOMES_INVALID / EXACT_ONE_SELECTED_RETURN_NULL`。
- 终态没有 `run_id`、immutable run、13 outputs、manifest、public verification 或 canonical retained publication；实际 worktree 中 `artifacts/research/runs` 与诊断 publication root 均不存在，controlled diagnostic scope 也记录 `RESEARCH_RUN_ROOT_EXISTS=False`、`DIAGNOSTIC_ARTIFACT_ROOT_EXISTS=False`。
- `alpha101_006`、`alpha101_012`、`alpha101_041` 均保持 `UNASSESSED/HOLD`，不是 `REJECTED`，不得据此声称任一因子有效或无效。独立反例 `R18-ADV-STATUS-SLOT-RESTORE`：若把这三个候选改写为 `REJECTED`，或删除 evidence/改写状态并恢复三个 slots，便会制造不存在的经济否证或重复消费 trial；正确状态是保留 `UNASSESSED/HOLD`，`trial_delta=3` 计入 ledger 且 slots 不恢复。
- 本 package 已消耗唯一真实 run 授权；第二次真实 run 必须由用户重新明确授权、在新任务身份中重新预注册，不能从 controlled diagnostic 授权或本任务推定。该记录不冒充完整研究 trial 结果。
- delivery 明确 production、tests、config、taskbook、roadmap、review 等既有边界未因终态修改；roadmap 同样要求不修改生产 Gate、不进行第二次运行。本 reviewer 未发现与该声明冲突的静态路径变更。

### 4. V8/V9/real-run/diagnostic 原生证据与 SHA

- Validation8 summary 文件 SHA-256 为 `0dc6e322a1d516b6488e5eec32eab1b939bc4f581d915773978c4399ba578f6f`，与 delivery/taskbook 一致；其 identity stdout `82b6919554a2be3161c5bb204bf8d923529b3518f2e3dc44d3fd9c41cf42fa46`、behavior stdout `bda21adfa37dd9c9ecc596250f382bb2fa5cadfe0e0dd3573ba5153978abfb6f`、Ruff stdout `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`、mypy stdout `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` 与 cold stdout `7a4c3e05a8bd0bd723169ff9c4ce4acbd5888927b1ad39dd7d69e6adab92cc32` 均与对应原生文件匹配，且 exit 均为 `0`。
- Validation9 scope summary 文件 SHA-256 为 `cee62b541c2d5a10bd8848c51fb0e77fae6168787aebc207759045a64382f8aa`；其原生 status stdout `16defa653c1601982456d90bcaa4035e6f51b928ed3ab751654db04f9cad500a`、cached stdout `243a4761f7409a5d65c46db7cf491bac787b1ab4193feef9db6aef139f144d41`、diff-check stderr `1175ad104b3ff1470639f8c1a4eea62bbe79085401d74b19c6356f48b721acc7`、history-ignore stdout `5501319072d9680bf0b99b8115588d6a93137a7d2ecdfa76a2a3e7a5fde89e62` 与 process-residue stdout `6abbd8c0070bd25a4e42c55cd1206b06a294b18a67a397636041aaa357a96dc5` 均匹配；原生结果为 `ACTUAL_COUNT=9`、`CACHED_COUNT=0`、`DIFF_CHECK_EXIT=0`、`PYTHON_COUNT=0`、`EXACT_0xF00_COUNT=0`、`WRITER_STATE=ABSENT`。
- real-run summary 文件 SHA-256 为 `5e33b2db06804f0ab9ccd13386a6895f9a84c28a02f323be57c4666e13502702`；preflight stdout `b7b1055cd105578d4a1792ed0d93e349102fe82bd33c1b3bd137c04dc022cdd4`、run stderr `07a3251151352d877502443f34dcaa90cfa94ad6e78c7a98009b30b15b694017`、空 run stdout `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` 均与原生文件匹配；exit 为 preflight `0`、run `1`，summary 为 `STOP=REAL_RUN_FAILED`。
- controlled diagnostic summary 文件 SHA-256 为 `bb915e3b80cf1d0feb9b0fe63cfb964cd8b8d3dc96e7b0caa235024730d80452`；diagnostic stdout `97f13af2c938385f066e0f9a3584c8ec14da71bf5fc3f3fb5b654bf87eaedac4`、stderr `3690fa9ee6120192baee931cc3ab0e85daeeae33488d4515fed71a5b2e524283`、复用的 preflight stdout `b7b1055cd105578d4a1792ed0d93e349102fe82bd33c1b3bd137c04dc022cdd4` 均匹配；diagnostic exit 为 `1`，scope/diff-check exit 均为 `0`。
- 上述 hash 是对持久文件的只读 `SHA-256` 核对结果；本轮没有重新执行任何 carrier、Python、pytest、Ruff、mypy、cold 或真实 I/O。

### 5. Git scope、历史保留与终态边界

- 当前 worktree 仍为 exact9 dirty：roadmap、runner、runner test 三个 modified，加上 sixth config、delivery、review、taskbook、factor module、factor test 六个 untracked；`git diff --cached --name-only` 为空（cached0），`git diff --check` exit `0`。无第十条路径、未 stage、未 commit、未 merge。
- Validation1—9、Validation7 类型返工、real-run 与 controlled diagnostic 的 summary/stdout/stderr/exit 现场均保留；旧 `REVIEW_FAIL`、P1/Validation3/Validation5/Validation7 结论未覆盖。delivery 的终态追加不被误读为 publication 或经济通过。
- 本轮严格未运行 Python、pytest、Ruff、mypy、cold、真实 run、data I/O、网络、进程/资源探针或任何第二次运行；未修改 production、tests、config、taskbook、roadmap、delivery 或其他路径。

### 6. 通过条件与后续

- 经济政策静态通过：chosen-outcome Gate 对固定完整 Top50 做 fail-closed 校验；不得 future-outcome 预过滤、替补、跳期或重加权；终态、候选 `UNASSESSED/HOLD`、trial ledger `trial_delta=3`、slots 不恢复及重新授权规则均闭合。
- 证据静态通过：V8/V9/real-run/diagnostic summary 与关键原生载荷 SHA 全部匹配；STOP、无 publication/retained 产物、exact9/cached0/diff-check 及历史保留表述一致且未越界。
- 本 `REVIEW_PASS` 只关闭 R18 economic-policy/evidence closeout 的静态审查项；不得据此重新开启 trial、恢复 slots、宣称因子有效/无效或宣称 publication/Gate 通过。
