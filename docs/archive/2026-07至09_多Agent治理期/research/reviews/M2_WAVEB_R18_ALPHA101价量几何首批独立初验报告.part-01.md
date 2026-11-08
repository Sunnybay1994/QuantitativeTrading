# REVIEW_FAIL / STATIC_ONLY

> 本轮独立复核于 2026-08-27 重新核对当前 exact base、exact8 工作树差异及下述 P1 证据；结论未改变。

## 审查身份与边界

- task id：`M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY`
- reviewer：全新隔离独立 reviewer，未参与实现/返工，未复用或调用 implementation subagent 上下文。
- exact base：`91a11058961824d934cde5bacf4b3c97c5aa1552`
- branch/worktree：`codex/m2-waveb-r18-alpha101-price-volume-geometry` / `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-waveb-r18-alpha101-price-volume-geometry`
- 本次 repo 审查输入严格为用户指定 exact8；唯一写入本报告。未创建或调用第二 reviewer、实现 agent、外部会话、顶层 task 或 worktree。
- 未运行 Python、pytest、Ruff、mypy、cold import、真实 run、网络、data I/O、PAPER、worker、commit 或 merge。

## 结论

`REVIEW_FAIL`。发现 1 个 P1 fail-open：R17 对称 redundancy 的 `median_abs_rank_corr` 只验证有限数值，没有验证绝对 RankCorr 必须位于 `[0, 1]`；负值会通过严格 `< 0.80` 门禁并保留 `RESEARCH_ONLY`。因此当前包不得进入后续验收链。

本报告交付状态为 `DELIVERY_READY`；这只表示独立初验报告已写入，不表示代码、Gate、snapshot、artifact 或真实运行通过。

## P1-001：负 absolute RankCorr 可漏过 redundancy admission

### 现象

`src/quant/research/run_classic_factors.py:241-252` 对 `median_abs_rank_corr` 只拒绝非数值、布尔值和非有限值，没有拒绝负数。` :1502-1510` 只判断非空且 `< maximum_median_absolute_rank_correlation`；负值因此得到 `redundancy_passed=True`。` :1511-1522` 随后可把候选写为 `combination_eligible=True` 并保留 `RESEARCH_ONLY`。

### 根因

聚合层没有检查绝对相关系数的语义域 `0 <= value <= 1`，admission 层也没有对非法 redundancy contract 做第二道 fail-closed 保护。字段名 `median_abs_rank_corr` 与任务书的“最大 median absolute RankCorr”共同规定该值不能为负。

### 应遵循规则

R17 对称 redundancy 必须同时满足端点非空且不同、pair 无重复/反向重复、相关值为有限数值且在 `[0, 1]`；任一违反都应在准入前稳定拒绝，不能因负数小于阈值而放行。

### 最小复现

```python
summary = pl.DataFrame({"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]})
redundancy = pl.DataFrame({
    "factor_a": ["control"], "factor_b": ["candidate"],
    "median_abs_rank_corr": [-0.01],
})
coverage = pl.DataFrame({"factor": ["candidate"], "coverage_passed": [True]})
schedule = pl.DataFrame({"factor": ["candidate"], "schedule_aligned": [True]})
apply_fourth_batch_admission_gates(
    summary,
    redundancy_summary=redundancy,
    coverage_summary=coverage,
    schedule_alignment=schedule,
    maximum_median_absolute_rank_correlation=0.80,
)
```

静态路径为 `:241-252` 接受 `-0.01` → `:270-272` 聚合 → `:1502-1510` 判定通过 → `:1513-1522` 在其他条件为真时保留 `RESEARCH_ONLY`。

### 新增的独立静态对抗反例/测试要求

本 reviewer 新增反例 `R18-ADV-REDUNDANCY-NEGATIVE-ABS-RANKCORR`；它未出现在实现者 exact8 测试中。应在 `tests/unit/test_run_classic_factors.py` 增加 `test_negative_median_absolute_rank_corr_is_rejected_before_admission`，复用上述四个最小 DataFrame，断言聚合或 admission 以 `ValueError`/明确 `REJECTED` fail-closed，不能得到 `RESEARCH_ONLY`。

### 通过条件

1. 在 `_aggregate_redundancy_by_factor` 或等价 contract 边界拒绝 `<0` 和 `>1`，并继续拒绝 NaN、正负 infinity、布尔值和非数值。
2. 增加上述独立单测，同时保留既有对称端点、self-pair、重复/反向重复、无 incident pair、阈值恰等于 `0.80` 和已 `REJECTED` 不升级断言。
3. 返工交回同一 implementation chain，由未参与实现的独立上下文复验；当前 STATIC_ONLY 审查不运行验证命令。

## 逐项静态核对

### 1. Alpha101 公式、单位、strict exchange-session gap、窗口/null 与 fail-closed

结论：公式和局部 null 结构静态符合，未作运行时确认。

- 任务书冻结公式和单位：`docs/research/tasks/M2_WAVEB_R18_ALPHA101价量几何首批任务书.md:40-79`。
- public names/specs：`src/quant/factors/classic_sixth_batch.py:13-31`；入口及 sessions 合同：`:46-65`。
- Alpha006 的 `open * adj_factor`、raw `volume`、10-session positive mask、rolling correlation 和 `ddof=1`：`:89-91`、`:126-178`、`:204-214`。
- Alpha012 的 raw-volume delta、adjusted-close delta、正/零/负 sign 分支：`:179-228`；没有收益率/百分比替代。
- Alpha041 的 raw `high*low`、raw `amount/volume`、几何均值差值且不使用 `adj_factor`：`:92`、`:130-149`、`:187-233`。
- symbol×session grid 和缺失不跨 gap：`:100-124`；源值 bool/NaN/Inf、重复键、历法外日期和算术非有限拒绝：`:67-98`、`:193-202`、`:253-258`。
- 因子测试覆盖 exact 10/9、内部 gap、zero variance、volume=0、delta 符号、raw unit、跨 symbol、bool/NaN/Inf、overflow、duplicate/calendar/session order 和置换：`tests/unit/test_classic_sixth_batch.py:86-308`。
- 静态注意：zero-variance 是否由 Polars `rolling_corr` 返回 null 未在本边界确认；若返回非有限值，`:193-202` 会整次拒绝，而任务要求该窗口为 null，须由后续 focused runtime 测试确认。

### 2. Bar1dSchema、wide schema、ordered columns/dtypes/keys/sorting、有限值和无 cross-sectional rank

结论：静态调用和输出构造符合合同，未运行 schema/dtype。

- `Bar1dSchema.validate`、唯一 `(symbol, trade_date)` 和 key 回连：`src/quant/factors/classic_sixth_batch.py:74-87`、`:236-242`。
- exact column order、因子 Float64 cast、最终排序和有限值检查：`:243-258`。
- 测试锁定 exact schema、列顺序、输入 key 数量、排序、置换稳定性：`tests/unit/test_classic_sixth_batch.py:60-84`、`:291-308`。
- 模块中没有横截面 rank 操作；计算只使用时序 rolling、lag、算术和 key 回连，符合任务书 `:87-91`。

### 3. config raw bytes、strict parse/raw SHA、cost semantic identity 与 artifact 前 fail-closed

结论：静态顺序符合“配置/成本身份 → snapshot → labels/evaluation → artifact”；未验证真实文件漂移、publisher 或目录行为。

- 配置中的 snapshot、区间、Top800/Top50、三因子顺序、controls、horizons、trial、cost 和 admission：`configs/research/m2_classic_daily_factors_sixth_batch.toml:1-104`。
- 主配置单次 raw `read_bytes`、UTF-8/BOM/NUL、TOML parse 和 hash：`src/quant/research/run_classic_factors.py:295-313`、`:2059-2070`。
- nested section/key/type/list/fold/constant/thread 严格验证：`:2268-2435`；漂移测试：`tests/unit/test_run_classic_factors.py:980-1068`、`:1610-1706`。
- cost 单次 bytes 读取、同 payload parse、完整 `[costs]` semantic projection/SHA 和 input digest：`src/quant/research/run_classic_factors.py:2077-2173`、`:2195-2225`；结构/数字/period 测试：`tests/unit/test_run_classic_factors.py:406-520`。
- R18 在 cost semantic SHA 核对后才调用 snapshot verifier：`:316-326`；labels/evaluation 后才调用 publisher：`:548-578`、`:854-886`。mock 证明 cost 先于 snapshot、raw SHA 绑定 run、cost input 先于 market input：`tests/unit/test_run_classic_factors.py:776-977`、`:1129-1172`。

### 4. trial identity、snapshot/universe/fold/horizon/signal/next-open/close/cost identity

结论：静态身份字段与调用链闭合；未把未运行身份代码当成真实验证。

- R18 catalog/hypothesis/snapshot/cost/folds constants：`src/quant/research/run_classic_factors.py:95-154`。
- validator 精确绑定 snapshot、2019 freeze、Top800、三 folds、`[1,5,20]`、20-session selection/rebalance、Top50、三档成本、cost SHA 和阈值：`:2355-2431`。
- 同一 panel/horizons/folds/cost/schedule 进入 walk-forward、redundancy、coverage、schedule：`:548-611`、`:970-1133`、`:1178-1339`。
- run 记录 config/code/universe/candidate/timing/folds/cost/input identity：`:854-883`；report 记录 snapshot/timing/R18 config/cost SHA：`:2617-2666`。close→next exchange session open→close 见 `:2648-2652`。

### 5. R17 对称 redundancy、incident pair/duplicate/coverage、RankIC/direction/2x cost 与只降级不升级

结论：对称聚合和主要门禁存在，但 P1-001 使该项整体不通过。

- 两端 incident 聚合、candidate 无 incident 的 null、self-pair 和 duplicate/reverse duplicate：`src/quant/research/run_classic_factors.py:188-280`；R18 调用及严格 `<0.80`：`:584-611`、`:654-692`。
- 已有测试覆盖对称、reference-only、self-pair、无 incident、duplicate/reverse、candidate-candidate 双端、非法 endpoint/status/correlation 和只降级不升级：`tests/unit/test_run_classic_factors.py:64-395`；但没有负 absolute RankCorr。
- coverage 的日期 coverage、scheduled rebalance 最小横截面和 median coverage：`src/quant/research/run_classic_factors.py:1178-1275`。
- RankIC、正向 test folds、方向一致性、1x/2x chained return 及初始状态：`:1136-1175`；第四批/R18 admission 与已有 `REJECTED` 不升级：`:1480-1524`。

### 6. shared panel/folds/cost/schedule 与 cost input

结论：静态复用关系符合边界。

- 同一 panel 传给 evaluator、redundancy、coverage、schedule：`src/quant/research/run_classic_factors.py:548-611`。
- 同一 folds、horizons、20-session rebalance、cash、cost multipliers、periods 和 strategy identity：`:561-578`。
- factor-independent schedule 由 `exit_date_20` 生成、targets 对齐 expected dates：`:2016-2033`、`:1278-1339`；cost input 置于 market input 前：`:2195-2225`。

### 7. mocked orchestration exact 13 outputs、恢复历史与 DELIVERED STATIC_ONLY 表述

结论：输出集合/顺序静态锁定，交付表述诚实，未运行 publisher。

- output dict exact insertion order：`src/quant/research/run_classic_factors.py:757-797`，为 `daily_ic.parquet`、`factor_catalog.json`、`factor_summary.parquet`、`fold_metrics.parquet`、`group_returns.parquet`、`portfolio_nav.parquet`、`report.json`、`targets.parquet`、`redundancy_daily.parquet`、`redundancy_summary.parquet`、`factor_coverage_daily.parquet`、`factor_coverage_summary.parquet`、`rebalance_schedule_alignment.parquet`。
- mock 捕获并 exact 断言 no-extra/no-missing/order：`tests/unit/test_run_classic_factors.py:858-969`；统一 publisher 接收点：`src/quant/research/run_classic_factors.py:884-886`。
- 交付报告明确 `DELIVERED / STATIC_ONLY`、`CPU NONE`、未运行 Python/pytest/Ruff/mypy/cold/真实 run/network/data I/O/PAPER、未宣称 runtime/Gate：`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:1-7`、`:20-24`、`:35-41`。
- 路线图保持 R18 为用户授权的单次 bar-only 例外、`TASK_READY / STATIC_ONLY`，不扩候选、不冒充 Gate：`docs/research/roadmaps/M2_策略与因子库并行建设路线图.md:386-403`、`:553-556`；任务书的最高状态和失败状态：`:19-24`、`:110-117`。

## exact8 稳定性、未运行边界与剩余风险

### exact8 输入

1. `docs/research/tasks/M2_WAVEB_R18_ALPHA101价量几何首批任务书.md`
2. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md`
3. `src/quant/factors/classic_sixth_batch.py`
4. `src/quant/research/run_classic_factors.py`
5. `tests/unit/test_classic_sixth_batch.py`
6. `tests/unit/test_run_classic_factors.py`
7. `configs/research/m2_classic_daily_factors_sixth_batch.toml`
8. `docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md`

### 未运行

本次没有运行 Python、pytest、Ruff、mypy、cold、TOML runtime parse、真实 snapshot/universe/panel/folds/labels、cost 文件现场、artifact mkdir/no-clobber/public verify、经济 RankIC/coverage/schedule/2x cost、PAPER 或任何项目 Gate；因此以上均不是通过证据。

### 剩余风险

1. `src/quant/research/run_classic_factors.py:352` 以选中 bars 的日期并集构造 sessions；若 snapshot 在整个选中股票集合共同漏掉一个 exchange session，runner 无法从该并集识别缺口。真实验收须证明 snapshot 日期完备性，或提供权威 exchange-session 输入。
2. Alpha006 zero-variance 的具体 Polars 行为未确认；须由后续 focused runtime 测试确认。
3. Bar1dSchema、shared evaluator、cost source、snapshot verifier 和 publisher 不在 exact8，本次只核对调用边界。
4. P1-001 修复前，不能把当前静态实现、单测文本或 `DELIVERED` 表述解读成 runtime/Gate/经济结论。

## 审查终态

- review verdict：`REVIEW_FAIL`
- delivery state：`DELIVERY_READY`
- next action：P1-001 返工交回同一 implementation chain，补负 absolute RankCorr 对抗测试并由独立上下文复验；当前不运行、不提交、不合流。

## P1-001 RE-REVIEW（STATIC_ONLY）

### 复验结论

- reviewer identity：沿用本报告原独立 reviewer；implementation subagent 已完成并退出。本轮未创建 reviewer、implementation agent、外部 session、顶层 task 或 worktree。
- verdict：`REVIEW_PASS`。P1-001 的 fail-open 缺陷已在静态证据中闭合；本轮未发现新的 P0/P1。
- scope：只复验 `_aggregate_redundancy_by_factor` 的相关值域、聚合前 fail-closed 顺序、既有冗余语义和新增对抗测试；未运行任何 Python、pytest、Ruff、mypy、cold、真实 run、数据 I/O 或网络。

### P1-001 本轮记录（保留原始历史）

- 现象：原实现可接受负的 `median_abs_rank_corr`，负值随后可能通过 `< 0.80` 的准入比较，形成冗余门禁 fail-open。
- 根因：聚合边界原先只有 bool/type/finite 检查，没有先约束相关系数闭区间 `[0, 1]`。
- 应遵循规则：任何 `median_abs_rank_corr` 必须为非 bool 的 `int`/`float`/`Decimal`、有限且满足 `0 <= value <= 1`；越界值必须在 max 聚合和 admission 前抛出 `ValueError`。
- 最小复现：`median_abs_rank_corr=-0.01` 或 `1.01`，配合一个 `RESEARCH_ONLY` candidate，调用 `apply_fourth_batch_admission_gates(...)`。
- 新增测试：`tests/unit/test_run_classic_factors.py:299-332` 的参数化测试覆盖 `negative` 与 `greater-than-one` 两个实现者未使用的反例，并通过准入边界断言 `ValueError`。
- 通过条件：值域异常在聚合/准入前 fail-closed；合法有限值与既有 self-pair、duplicate/reverse duplicate、no-incident、`0.80` rejection、`REJECTED` non-upgrade 语义保持不变。本轮静态条件满足，未将任何未执行命令写成运行通过。

### 修复静态证据

- `src/quant/research/run_classic_factors.py:241-252` 的 bool、类型和 `math.isfinite(float(...))` 检查仍在；`src/quant/research/run_classic_factors.py:253-254` 新增 `numeric_correlation < 0 or numeric_correlation > 1` 的严格闭区间拒绝。
- 该 `ValueError` 位于 pair max aggregation（`src/quant/research/run_classic_factors.py:263-267`）之前，也位于 admission 使用聚合结果之前，因此越界值不能进入 max、coverage 或准入状态更新。
- 静态类型路径仍接受有限 `int`、`float`、`Decimal`；严格不等式使精确端点 `0` 与 `1` 继续接受。这里只是源码控制流确认，没有执行型接受证据。
- 新测试的 `-0.01` 与 `1.01` 均从 admission API 入口验证抛错，断言覆盖“到达 admission 前拒绝”的 fail-closed 行为；本轮没有改动测试以外的实现/配置/任务书/路线图文件。

### 既有语义回归静态核对

- self-pair 仍由 `src/quant/research/run_classic_factors.py:239-240` 拒绝；no-incident 的空聚合仍产生 null，并由原 gate 约束，既有测试位于 `tests/unit/test_run_classic_factors.py:117-172`。
- canonical pair 归一化及 duplicate/reverse duplicate 拒绝仍在 `src/quant/research/run_classic_factors.py:256-261`；既有测试位于 `tests/unit/test_run_classic_factors.py:340-355`。
- exact `0.80` 仍由原严格门槛拒绝，`0.79` 仍可通过；candidate-candidate 两侧的最大相关值及已有 `REJECTED` 保持 rejected 的断言仍在 `tests/unit/test_run_classic_factors.py:358-427`。新增 range check 只增加越界拒绝，不改变这些合法值的后续路径。
- 既有 `None`、bool、NaN、正负无穷和字符串的 contract rejection 仍在 `tests/unit/test_run_classic_factors.py:276-296`；未见其被新分支绕过。

### exact8 与交付状态稳定性

- 本轮复验读取既定 exact8；factor、config、taskbook、roadmap 及 delivery report 未因本轮复验新增改动。唯一获准写入的是本 review 报告；本节为追加内容，之前的 REVIEW_FAIL、P1-001 发现和历史证据均未改写或删除。
- delivery report 中的 `RECOVERY_SUPERSESSION` 与 `FINAL_STATIC_HANDOFF` 历史保持不变（`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:9-41`），交付仍明确为 `DELIVERED / STATIC_ONLY`；这不等同于真实运行、Gate 或经济有效性通过。
- 当前结论仅表示静态独立复验通过；尚无任何本轮执行、真实数据、PAPER、worker、commit 或 merge 证据，剩余风险仍由后续受控运行与领域验收承担。

## P1-001 STATIC_REVIEW_RECHECK（RECHECK_PASS / STATIC_ONLY）

### 复验范围与结论

- identity：沿用本报告原独立 reviewer；不使用 implementation context，不创建 reviewer、implementation agent、外部 session、顶层 task 或 worktree。
- scope：本轮只复核 `src/quant/research/run_classic_factors.py`、`tests/unit/test_run_classic_factors.py` 与既有 delivery report 的本轮三路径 diff；未修改生产代码或测试，仅追加本报告本节。
- verdict：`RECHECK_PASS`，因此当前 P1-001 复验结论为 `REVIEW_PASS`。首轮 `REVIEW_FAIL` 及其现象、根因和历史证据均保留，未被覆盖或改写。
- boundary：本轮为 `STATIC_ONLY / CPU NONE`；未运行 Python、pytest、Ruff、mypy、cold、real run、data I/O、network、PAPER 或 commit，未把任何 executable validation 写成通过。

### P1-001 修复证据

- `src/quant/research/run_classic_factors.py:241-252` 仍先执行 bool、numeric type 和 `math.isfinite(float(...))` 校验；`src/quant/research/run_classic_factors.py:253-254` 对 `numeric_correlation < 0 or numeric_correlation > 1` 确定性抛出 `ValueError`。
- 该 range check 位于 pair/max aggregation（`src/quant/research/run_classic_factors.py:256-267`）之前；从 `apply_fourth_batch_admission_gates` 入口构造异常输入的测试位于 `tests/unit/test_run_classic_factors.py:304-329`，因此静态控制流满足“聚合/准入前拒绝”。
- `isinstance(correlation, (int, float, Decimal))` 与既有 finite check 仍使合法有限 `Decimal`、`int`、`float` 进入后续路径；严格的 `< 0`/`> 1` 条件使精确端点 `0`、`1` 保持接受。该项是源码控制流确认，不是执行结果。

### 实现者未使用反例与既有语义

- `tests/unit/test_run_classic_factors.py:299-329` 的参数化测试以 `-0.01` 和 `1.01` 为 `negative`、`greater-than-one` 对抗，经过 admission API 断言匹配 `between 0 and 1` 的 `ValueError`；不会产生可被误认为准入成功的 `REJECTED` 输出。
- self-pair、对称端点/无 incident 既有核对仍在 `tests/unit/test_run_classic_factors.py:117-172`；pair canonicalization 与 exact/reverse duplicate 拒绝仍在 `tests/unit/test_run_classic_factors.py:332-355`。
- finite/type/bool/NaN/Inf/string contract rejection 仍在 `tests/unit/test_run_classic_factors.py:276-296`；exact `0.80` 仍严格 rejection、低于阈值仍可继续既有路径，且已有 `REJECTED` 不升级断言仍在 `tests/unit/test_run_classic_factors.py:358-427`。
- 新 range 分支只拒绝闭区间外值，未改变对称最大值聚合、duplicate/reverse duplicate、no-incident、exact `0.80` 门禁或 `REJECTED` non-upgrade 语义。

### 三路径变更边界与交付状态

- 本轮 scoped diff 的实现性变更仅落在上述 source/test 两条路径；delivery report 作为第三条允许路径仅作读取。工作树中 roadmap、factor、config、taskbook、factor test 和 review 等路径的状态属于此前交付包/历史现场，不归因于本轮 recheck；本轮未写入或修改它们。
- review 报告是唯一获准写入文件，本节为追加；首轮 `REVIEW_FAIL`、P1-001 完整记录和此前历史均保留。delivery report 的 `RECOVERY_SUPERSESSION`（`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:9-24`）及 `DELIVERED / STATIC_ONLY` 状态（`:1-7`）保持不变。
- 本轮结论只表示 P1-001 静态复验通过；delivery 仍不是 runtime/Gate/真实数据验证，未执行边界和后续验收风险继续有效。

## VALIDATION3 P1 RECHECK — RECHECK_PASS / STATIC_ONLY

### 身份、范围与结论

- 沿用本报告原独立 reviewer；不使用 implementation context，不创建第二 reviewer、implementation agent、外部 session 或 worktree。implementation subagent 已完成并退出。
- 本轮只读取 `src/quant/factors/classic_sixth_batch.py`、`tests/unit/test_classic_sixth_batch.py` 与 delivery report 中的 Validation3-P1 记录；唯一写入仍是本 review 报告本节，首轮 `REVIEW_FAIL` 及全部此前历史保持不变。
- 结论：`RECHECK_PASS`，因此当前 reviewer 结论为 `REVIEW_PASS`。这是静态文本/Git 复核，不是 executable validation、runtime 或 Gate 通过。

### 冻结修复核对

- 现象/根因：Validation3 基线中，有限正 flat-open 零方差使 `_alpha006_corr` 产生 null/NaN，却被 global arithmetic non-finite guard 当作整批错误；flat-volume 是同类实现者未使用的对抗。
- 应遵循规则：源字段 bool/NaN/Inf、adjusted open/close 与 `high*low` 算术非有限仍必须整批 fail-closed；仅 Alpha006 rolling correlation 的窗口级零方差结果走后续 null 化，不得吞异常或放宽源检查。
- `src/quant/factors/classic_sixth_batch.py:193-202` 的 global non-finite arithmetic guard 现在只覆盖 Alpha041 VWAP/geometric 与 Alpha012 delta，已不包含 `_alpha006_corr`；`src/quant/factors/classic_sixth_batch.py:204-214` 仍要求 Alpha006 correlation non-null、finite 且完整十行才取负值，否则输出 null。
- `_alpha006_corr` 仍使用 `window_size=10`、`min_samples=10`、`ddof=1` 并按 symbol rolling（`src/quant/factors/classic_sixth_batch.py:167-178`）；Alpha006/012/041 公式、strict-session grid、ordered wide output 与 Float64 schema 未被该修复改写（`src/quant/factors/classic_sixth_batch.py:204-258`；`tests/unit/test_classic_sixth_batch.py:60-83`）。

### 对抗测试与 fail-closed 边界

- 原有 flat-open 覆盖仍在 `tests/unit/test_classic_sixth_batch.py:114-126`；新增 flat-volume fixture 在 `:128-139`，断言 Alpha006 尾窗为 null，同时 Alpha012 后九行与 Alpha041 全部可计算，证明零方差不会 batch-reject 其他可计算行/因子。
- 任意源 bool/NaN/Inf 的 fail-closed 参数化仍在 `tests/unit/test_classic_sixth_batch.py:248-280`；源字段检查与 `Bar1dSchema` 包装仍在 `src/quant/factors/classic_sixth_batch.py:67-87`。唯一的 `try/except` 仅将 schema 错误重新抛为 `ValueError`（`:75-79`），没有吞掉错误或绕过源检查。
- adjusted open/close 与 raw `high*low` 的非有限算术仍在 `src/quant/factors/classic_sixth_batch.py:89-98` 触发整批拒绝；Alpha012 delta 与 Alpha041 VWAP/geometric 的非有限 guard 仍在 `:193-202`，相关零分母/符号行为测试仍在 `tests/unit/test_classic_sixth_batch.py:154-228`。
- 最小复现：十个严格连续 session 的正 flat-open 或正 flat-volume 输入使 rolling correlation 产生零方差 null/NaN；修复后由 `:204-214` 输出 Alpha006 null，而不触发 `:193-202` 的整批 arithmetic exception。测试文本证明该预期，但本轮未执行。

### 交付证据、写入边界与未运行声明

- delivery report 保持 `DELIVERED / STATIC_ONLY`（`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md:1-7`）。其 Validation3-P1 记录引用 stdout SHA `7dd05dc1a5cfb1a813d72a03c21c72424abb7c12b692a4596c44b73db6dc869c`、summary SHA `7b1e0036d1f955605f1adbe73b8cdcf99c9cf5e5f777f884504e44b6358a54bd`，并保留 `60 passed / 1 failed / 194 warnings` 的失败基线（`:55-64`）。该基线不能被表述为本轮修复运行通过。
- delivery 记录明确未运行 Ruff、mypy、cold、Python、pytest、real run、data I/O、network、PAPER 或 scope/runtime/Gate 验证；本复验不推断任何 executable validation。
- 本轮 scoped 变更仅对应三条允许路径：factor、factor test、delivery；工作树中 roadmap、config、taskbook、review 及其他 sixth-package 状态为本轮前已存在的交付现场，未作为本轮新增写入。review 报告是唯一获准写入文件，且本轮只追加本节；不声称工作树 clean。

### Validation3 通过条件

- 仅 `_alpha006_corr` 从 global non-finite arithmetic rejection 中移除；源 bool/NaN/Inf、adjusted arithmetic、Alpha012 delta、Alpha041 VWAP/geometric rejection 保持；rolling correlation 零方差经后续 `is_not_null()`/`is_finite()` 局部转 null。
- flat-open 与 flat-volume adversaries 均有覆盖，Alpha012/041 的可计算结果保留；formula/window/ddof/sessions/schema 无漂移，未以 try/except 吞错或放宽 source checks 取得表面通过。以上条件静态满足；剩余基线统计与未运行边界继续有效。

## Validation3 P1 RECHECK — RECHECK_PASS / STATIC_ONLY

### 身份、范围与结论

- 沿用本报告原独立 reviewer；不使用 implementation context，不创建第二 reviewer、implementation agent、外部 session 或 worktree。implementation subagent 已完成并退出。
- 本轮只读取 `src/quant/factors/classic_sixth_batch.py`、`tests/unit/test_classic_sixth_batch.py` 与既有 delivery report；唯一写入仍是本 review 报告的本节，首轮 `REVIEW_FAIL` 及全部此前历史保持不变。
- 结论：`RECHECK_PASS`，因此当前 reviewer 结论为 `REVIEW_PASS`。本结论是静态文本/Git 复核，不是 executable validation、runtime 或 Gate 通过。

### Validation3 P1 修复核对

- 现象/根因：Validation3 基线中，有限正 flat-open 零方差使 `_alpha006_corr` 产生 null/NaN，却被 global arithmetic non-finite guard 当作整批错误；flat-volume 是同类实现者未使用的对抗。
- 应遵循规则：源字段 bool/NaN/Inf、adjusted open/close 与 `high*low` 算术非有限仍必须整批 fail-closed；仅 Alpha006 rolling correlation 的窗口级零方差结果走后续 null 化，不得吞异常或放宽源检查。
- `src/quant/factors/classic_sixth_batch.py:193-202` 的 global non-finite arithmetic guard 现在只覆盖 Alpha041 VWAP/geometric 与 Alpha012 delta，已不包含 `_alpha006_corr`；`src/quant/factors/classic_sixth_batch.py:204-214` 仍要求 Alpha006 correlation non-null、finite 且完整十行才取负值，否则输出 null。
- `_alpha006_corr` 仍使用 `window_size=10`、`min_samples=10`、`ddof=1` 并按 symbol rolling（`src/quant/factors/classic_sixth_batch.py:167-178`）；Alpha006/012/041 公式与 strict-session grid、输出列/Float64 schema 未被该修复改写（`src/quant/factors/classic_sixth_batch.py:204-258`；`tests/unit/test_classic_sixth_batch.py:60-83`）。

### 对抗测试与 fail-closed 证据

