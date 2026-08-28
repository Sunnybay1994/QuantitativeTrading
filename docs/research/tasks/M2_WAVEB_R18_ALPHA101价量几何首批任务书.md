# M2 Wave B R18 Alpha101 价量几何首批任务书

> 状态：`TASK_READY / STATIC_ONLY`
> task id：`M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY`
> trial delta：`3`
> exact base：`91a11058961824d934cde5bacf4b3c97c5aa1552`
> branch：`codex/m2-waveb-r18-alpha101-price-volume-geometry`
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-waveb-r18-alpha101-price-volume-geometry`

## 1. 目标与边界

用户明确授权在财务 writer 后台继续采集期间，使用既有、已验证、冻结且不可变的 bar snapshot 开发并证伪
更多策略。本包只实现 `quant_factor_research_v2` 中三个不依赖财务数据的 Alpha101 价量候选：

1. `alpha101_006`；
2. `alpha101_012`；
3. `alpha101_041`。

三者组成一个不可事后扩展或替补的候选族，`trial_delta=3`。本包不是候选动物园，不改变首个 PIT、audit-v4、
R3 或 annual asset growth 的既有 Gate；不得读取 partial financial raw、finance ledger 或未发布 financial clean。
结果最高为 `RESEARCH_ONLY`，任一准入门禁失败为 `REJECTED`，不得进入 S2、PAPER 或真实交易。
公式来源为
`docs/research/references/quant_factor_research_v2/01A_Alpha101_001-050.md` 的 Alpha #006/#012/#041；
adjusted/raw 价格口径是本项目在真实结果前冻结的 A 股适配，不反向改写参考资料。

## 2. 数据、时间与公共运行身份

- 只消费公开 verifier 验证后的 immutable bar snapshot：
  `b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2`；
- 研究区间：`2020-01-01` 至 `2026-08-13`；冻结池 `Top800`，组合 `Top50`；
- 三个 walk-forward folds，horizons exact `[1, 5, 20]`，每 20 个严格 exchange sessions 调仓；
- signal 在收盘后形成，最早下一交易日 open 成交，close 估值；成本倍率 exact `[0.5, 1, 2]`；
- 三因子共用完全相同的 universe、fold、signal-date、outcome cohort、cost 与 portfolio identity；
- 每折只允许 validation 选择方向并冻结，test 不得翻转方向；公式中的符号仍是因子定义的一部分；
- 复用既有 classic outcome-cohort、coverage、R17 对称 redundancy 和 2x cost 门禁；不得修改 shared evaluator、
  run schema、output 集合或 public verifier；
- config 只读取一次 raw bytes，同一 payload 严格 UTF-8 parse 与 raw SHA-256，运行 input 绑定 canonical cost
  semantic SHA；config/cost/snapshot identity 必须在 artifact 目录创建前 fail closed。

## 3. 因子定义与 fail-closed 语义

公共输入必须通过现有 `Bar1dSchema`，并满足 `(symbol, trade_date)` 唯一。exchange sessions 必须是严格递增、
无重复的 `date` tuple，bar 日期必须属于该集合。实现须先形成 symbol×session 语义；缺失 session 只使受影响的
窗口为 null，绝不能跨缺口拼接。相关源列出现 bool、NaN、正负 infinity 或无法保持有限运算时稳定拒绝整次计算；
局部历史不足、零方差或因子专属的非正分母仅令对应行/窗口为 null，不填 0、不前后填充、不使用 epsilon。

### 3.1 `alpha101_006`

定义为：

`-Corr(adjusted_open, raw_volume, 10 strict exchange sessions)`，其中
`adjusted_open = open * adj_factor`，`raw_volume` 使用 `Bar1dSchema.volume` 的原始股数单位。

- 每个窗口必须恰有 10 个连续 sessions；
- 10 个 adjusted open 均须有限且严格为正，10 个 raw volume 均须有限且严格为正；
- 使用每个 symbol 的时序 Pearson correlation，样本协方差/方差口径 `ddof=1`；
- 任一边零方差、窗口缺口或样本不足时输出 null；不得在因子函数内做横截面 rank。

### 3.2 `alpha101_012`

定义为：

`Sign(Delta(raw_volume, 1 strict session)) * -Delta(adjusted_close, 1 strict session)`，其中
`adjusted_close = close * adj_factor`。

- 当前与上一 session 必须连续且两期 raw volume、adjusted close 均有限、严格为正；
- `Sign` exact 为 `-1 / 0 / +1`；volume delta 为 0 时因子值 exact 0，是合法观察；
- 不得跨缺失 session 做 delta，不得使用收益率或百分比变化替代价格差。

### 3.3 `alpha101_041`

定义为：

`sqrt(raw_high * raw_low) - raw_vwap`，其中 `raw_vwap = amount / volume`。

- `high/low` 使用未复权 CNY/share，`amount` 使用人民币元，`volume` 使用股；
- high、low、amount、volume 必须有限且严格为正，乘积、平方根、VWAP 与输出必须有限；
- 不乘 `adj_factor`，不做价格归一化，不改成收益率或百分比；保留原始 CNY/share 公式；
- 价格水平暴露是本候选可被冗余、RankIC 或成本 Gate 证伪的预注册风险，禁止结果后修公式。

新模块 public identity 固定为：

- `SIXTH_BATCH_FACTOR_SPECS`；
- `SIXTH_BATCH_FACTOR_NAMES = ("alpha101_006", "alpha101_012", "alpha101_041")`；
- `compute_sixth_batch_daily_factors(bars, *, sessions)`。

compute 输出必须复用仓库现有宽表契约，exact ordered columns 为
`symbol, trade_date, alpha101_006, alpha101_012, alpha101_041`，dtypes exact 为
`pl.String, pl.Date, pl.Float64, pl.Float64, pl.Float64`；只返回输入 bars 已有的 unique keys，不返回补齐 grid 的
额外行，并按 symbol、trade_date 稳定排序。因子列允许 null，但不得含 NaN/Inf。禁止另建
`factor/value` 长表或第二套 dataframe/schema。

## 4. 配置、候选身份与准入

版本化配置新增且严格验证 `[alpha101_sixth_batch]`：

- `schema_version = "m2-alpha101-sixth-batch-v1"`；
- `hypothesis_id = "m2-alpha101-price-volume-geometry-sixth-batch-v1"`；
- `factors = ["alpha101_006", "alpha101_012", "alpha101_041"]`；
- `correlation_window_sessions = 10`；
- `delta_lag_sessions = 1`；
- `alpha041_price_basis = "raw_cny_per_share"`；
- `alpha041_vwap_formula = "amount_div_volume"`；
- `direction_policy = "validation_only_per_fold"`；
- `trial_budget = 3`、`trial_delta = 3`、`attempt_ordinal = 1`。

unknown/missing key、顺序/名称/常数漂移、bool 冒充 int 或任一身份不闭合，均须在 snapshot verify、artifact mkdir
和经济 label 消费前拒绝。不得观察结果后修改窗口、方向政策、公式、snapshot、universe、fold、成本或候选集合。

冗余 controls 固定为当前 classic 第一至第五批全部候选加 `liquidity_20`；每个新候选必须汇总其位于
`factor_a` 或 `factor_b` 的全部 incident pairs。candidate 无 incident pair、重复/反向重复 pair、coverage
非严格通过或最大 median absolute RankCorr 不满足严格 `<0.80`，均拒绝。其余统一准入为：

- 横截面至少 100，日期中位 coverage 至少 0.80；
- direction-adjusted mean test RankIC 至少 0.01，至少 2/3 test folds 为正且与 validation 冻结方向一致；
- 2x 成本后组合收益严格为正；
- 状态只允许 `RESEARCH_ONLY → REJECTED`，既有 `REJECTED` 永不升级。

## 5. 文件所有权

最终提交 exact 9 路径：

1. 经理唯一写：`docs/research/tasks/M2_WAVEB_R18_ALPHA101价量几何首批任务书.md`；
2. 经理唯一写：`docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的 R18 exact hunk；
3. 实现者唯一写：`src/quant/factors/classic_sixth_batch.py`；
4. 实现者唯一写：`src/quant/research/run_classic_factors.py`；
5. 实现者唯一写：`tests/unit/test_classic_sixth_batch.py`；
6. 实现者唯一写：`tests/unit/test_run_classic_factors.py`；
7. 实现者唯一写：`configs/research/m2_classic_daily_factors_sixth_batch.toml`；
8. 实现者唯一写：`docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md`；
9. 独立初验者唯一写：`docs/research/reviews/M2_WAVEB_R18_ALPHA101价量几何首批独立初验报告.md`。

不得交叉写 owner 文件，不得新增 runner/module/config、修改 shared evaluator/schema/repository/publisher/facade，
也不得触碰 integration、旧 R15 事故现场、data/raw、data/run_state 或 financial clean。

## 6. 必测反例

- 006：exact 10 sessions、9 sessions、内部缺口、零方差、volume=0、乱序输入、跨 symbol 污染；
- 012：连续两日、内部缺口、volume delta 正/零/负、adjusted price delta 正/零/负、不得跨缺口；
- 041：正确 raw unit、不得使用 adj_factor、volume/amount 为 0、负值、溢出、raw VWAP 与几何均值相等；
- 公共：duplicate key、session 乱序/重复、out-of-calendar、bool/NaN/Inf、输入行置换后 canonical bytes 不变；
- config 任一 key/名称/窗口/trial identity 漂移在 snapshot/artifact/economic label 前拒绝；
- 三因子共享完全相同的 panel/folds/costs/horizons/signal schedule，只有 factor 与 validation-selected direction 变化；
- R17 对称 redundancy、无 incident pair、重复/反向重复 pair、coverage、RankIC 与 2x 成本降级语义；
- mocked orchestration 锁定现有 13 个 output exact 集合、raw config SHA 与 cost input 顺序；no-clobber 与
  public verify 复用既有 lightweight publisher/verifier，并在唯一真实 run 后由经理/统筹 fresh 验收，不为 R18
  改写 classic runner 的公共发布语义。

独立初验必须增加至少一个实现者未使用的对抗反例。发现问题时须记录“现象—根因—应遵循规则—最小复现—
新增测试—通过条件”，返工交回同一实现链。

## 7. 验证、真实运行与停止条件

当前仅 `STATIC_ONLY / CPU NONE`。实现交付与独立初验通过经理 scope 核对后，另向统筹申请 CPU8–11/
`0xF00` 串行资源；finance writer 的 PID/affinity/优先级不得扰动。

获批开发验证顺序：focused 因子与 runner 节点 → Ruff 相关 Python → mypy 生产文件 → cold import/TOML →
exact 9 scope/diff/temp/process。禁止全量 pytest、网络、真实 data I/O、PAPER 或并发研究运行。

开发证据全绿、fresh verify 冻结 snapshot 与 canonical cost 后，才可另行申请唯一一次真实
`RESEARCH_ONLY` run；单实例、BelowNormal、affinity `0xF00`、数值线程不超过 2。真实 run 后必须 public
verify、检查输出闭包并由统筹 no-clobber retain。任何候选失败不得替补或第二次运行。

出现白名单扩大、共享合同变化、数据身份漂移、已有同 hypothesis attempt、非唯一 writer、资源冲突、验证失败
或 artifact 闭包失败时立即 `STOP`，保留证据且不盲重跑、不提交、不修改请求状态。

## 8. Validation7 静态类型返工合同

Validation7 的可信边界为：parser、identity、collect（87）、focused（61 passed / 214 warnings）与 Ruff exact 4
均通过；mypy 在 `src/quant/research/run_classic_factors.py:2247` 首次失败后立即停止，cold 与 exact 9 scope
运行阶段未执行。资源已释放，退出后 actual exact 9、cached=0 与 diff-check 通过。证据 SHA-256：

- summary：`ceeb33518406b81b77c1ec4a982655844e70d7c9991106c5bfa1783089f45797`；
- focused stdout：`aace7211267a07dc8a7c27c3a943a3b4e8e902e894b5663403039fd2753ad733`；
- Ruff stdout：`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`；
- mypy stdout：`2a109d8da4deb7d86b501d91c19410ae742fafa41e2bbb217496ef1c7ed3c415`。

唯一返工是 `_is_exact_float(value: object, expected: float)` 的可证明类型收窄：必须显式区分
`type(value) is int` 与 `type(value) is float`。exact `int` 可受控转换为 `float`，巨大整数转换发生
`OverflowError` 时返回 `False`；exact `float` 直接使用。`bool`、其他类型、非有限值继续返回 `False`，最终仍以
finite 且与 `expected` 精确相等为通过条件。禁止使用 `cast`、`Any`、`type: ignore` 或放宽数值语义。

本轮实现者 exact 写路径仅为：

1. `src/quant/research/run_classic_factors.py`；
2. `docs/research/deliveries/M2_WAVEB_R18_ALPHA101价量几何首批交付报告.md`。

其余路径全部只读；阶段为 `STATIC_ONLY / CPU NONE`，禁止 Python、pytest、Ruff、mypy、cold、真实 run、数据
I/O、网络、提交或合流。交付报告须追加本轮“现象—根因—应遵循规则—最小复现—测试/证据—通过条件”，并
逐字保留上述 Validation7 边界与四个 SHA。实现交付后必须由不同独立 reviewer 只读复验，唯一写原 review
报告；复验通过后才可申请 postfix validation。原实现 Worker 因客观 usage limit 且其 subagent 已退出，本轮使用
中央批准的 `AUTHORIZED_IMPLEMENTER_REPLACEMENT`，不得冒充原实现链恢复，也不得创建第二 worktree/branch。

## 9. 唯一真实运行停止裁定

Validation8 的产品阶段与 Validation9 的 Unicode/NUL-safe scope 阶段共同关闭 Windows 开发验证；其 summary
SHA-256 分别为 `0dc6e322a1d516b6488e5eec32eab1b939bc4f581d915773978c4399ba578f6f` 与
`cee62b541c2d5a10bd8848c51fb0e77fae6168787aebc207759045a64382f8aa`。随后唯一一次授权真实 run 的 preflight
通过 exact bar snapshot、manifest、canonical cost、零历史同 hypothesis attempt 与 no-clobber target 检查，但
运行在发布前由 `build_diagnostic_factor_targets` 的 chosen-outcome 完整性 Gate 停止。真实运行 evidence summary
SHA-256 为 `5e33b2db06804f0ab9ccd13386a6895f9a84c28a02f323be57c4666e13502702`。

一次另行授权、无 publication 的受控诊断只重算到同一 fail-closed 点，publish 入口未到达。它把唯一原因定位为：
`alpha101_006`、fold 1、`as_of=2022-01-04`、首个 builder call 的 Top50 中 exact 一个 holding-period return
为 null；execution/exit 日期唯一、非空、类型与顺序合法，return nonfinite=0。诊断 summary SHA-256 为
`bb915e3b80cf1d0feb9b0fe63cfb964cd8b8d3dc96e7b0caa235024730d80452`，stdout SHA-256 为
`97f13af2c938385f066e0f9a3584c8ec14da71bf5fc3f3fb5b654bf87eaedac4`。

权威经济裁定为：不得在排名前按未来 outcome 是否存在过滤证券，不得以第 51 名替补，不得事后跳过该调仓期，
也不得把不完整 Top50 重新加权。这些处理会引入未来可得性、改变预注册组合或改变收益样本。现有 fail-closed Gate
行为正确，不做生产修复。本包终态冻结为
`STOPPED_BEFORE_PUBLICATION / DIAGNOSTIC_SELECTED_TARGET_OUTCOMES_INVALID / EXACT_ONE_SELECTED_RETURN_NULL`；
没有 run_id、immutable run、13 outputs、manifest、public verification 或 canonical retained publication。
`alpha101_006 / alpha101_012 / alpha101_041` 均保持 `UNASSESSED/HOLD`，不是 `REJECTED`，也不得声称因子有效或
无效。

本次 package 已开始消费冻结经济链，按 `trial_delta=3` 记入既有 trial ledger 边界，禁止通过删除 evidence、改写
状态或只重跑未到达的候选来恢复三个 slots；但该记录不得冒充完整研究 trial 结果。唯一真实 run 授权已消耗，
任何第二次真实运行都必须由用户重新明确授权并在新任务身份中预注册，不得从诊断授权或本任务推定。现有
Validation1—9、真实 run 与 controlled diagnostic evidence 全部保留至 source commit、integration 回归和
archive-first 退休闭合。
