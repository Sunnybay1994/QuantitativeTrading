# M2-STRATEGY-R9：ETF 跳月相对动量任务书

> - task id：`M2-STRATEGY-R9-ETF-PRIOR-2-12-RELATIVE-MOMENTUM`
> - 领域：research
> - 当前阶段：`TASKBOOK_ONLY / STATIC_ONLY / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> - base/head：`c0d820d2a465fc092cb0cdb0ad48b417af6978de`
> - branch：`codex/m2-strategy-r9-etf-prior-2-12-relative-momentum`
> - worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-strategy-r9-etf-prior-2-12-relative-momentum`
> - 当前唯一写路径：`docs/research/tasks/M2_STRATEGY_R9_ETF跳月相对动量任务书.md`
> - 任务性质：真实结果读取前的经济合同预注册；不是实现、验证、回测、PAPER 或 LIVE 授权

## 1. 目标与结论上限

本任务冻结一个低自由度的 ETF 横截面相对动量策略：在每个已经完成的 SH/SZ 共同自然月末 `s`，对
`ETF_POOL_M2_V1` exact11 使用 `P_(s-1) / P_(s-12) - 1` 计算 prior-(2–12) 排名分数，明确跳过最近一个
完整月；全池闭合后按分数降序和 canonical symbol tie-break 选择 Top3，每只固定 `1/3`，在下一共同开市日
open 执行。

本任务回答的唯一 primary 问题是：跳过最近一个月的固定 Top3 相对动量，是否在完全相同的样本、执行时点、
成本和候选池下，相对 exact11 equal-weight 基线改善成本后收益风险特征，并在加倍成本压力下保持正收益。

策略身份固定为：

- `hypothesis_id="m2-etf-prior-2-12-relative-momentum-local-v1"`；
- `strategy_kind="etf_monthly_prior_2_12_relative_momentum"`；
- `strategy_version="1.0.0"`；
- `trial_identity="m2-etf-prior-2-12-relative-momentum-local-v1"`；
- `attempt_ordinal=1`；
- `trial_delta=1`，仅在未来 public durable attempt start 成功发布后计入；当前 exact `0`。

该身份标记为 `LOCAL_LONG_ONLY_ETF_PRIOR_2_12_RELATIVE_MOMENTUM_ADAPTATION_TRIAL`。它不是 Jegadeesh–Titman
股票组合、Carhart UMD 或任何公开数据库因子的逐字复现：本任务使用中国/港股主题 ETF、long-only Top3、
月频二级市场执行和本地成本。公开研究只支持假设来源，不证明本地策略仍然有效。

未来真实运行的最高自动结论仅为 `RESEARCH_ONLY`；任一 admission Gate 失败只允许降为 `REJECTED`。即使
`RESEARCH_ONLY`，仍不自动产生 `PAPER_CANDIDATE`，更不授权 PAPER、shadow、LIVE 或自动下单。

## 2. 非目标

本任务不做：

- 搜索 formation 窗口、skip 长度、Top-K、权重、调仓频率、阈值或方向；
- 比较 `(1–12)`、`(2–12)`、`(2–7)` 等候选后选择历史最好者；
- 对 Top3 添加绝对动量门、市场趋势门、波动率门或现金替代物；
- 使用第4名或其他证券替补缺失、不可交易或未来 outcome 不完整的 Top3；
- 用 `1/n_available`、风险平价、波动率缩放、杠杆、做空或协方差优化；
- 将 R6 双重动量、R5 绝对动量、Faber 或市场状态结果并入本 trial，或观察后选择赢家；
- 用状态切片改变排名、持仓、Gate 或 disposition；
- 读取 immutable research run、forward、PAPER、broker、OMS 或账户数据；
- 在公共 receipt 与 Faber 共享 schedule/runner 合流前复制第二套 month-end、simulator、metrics 或 receipt；
- 修改 shared roadmap、共享进展报告或其他 worktree 文件。

## 3. 公开研究依据与本地适配边界

1. Jegadeesh 与 Titman 的横截面动量研究提供“过去相对强势资产随后可能继续强势”的可检验假设；原研究的
   股票池、分组、持有期和多空组合不等于本地 ETF Top3。
2. 跳过最近一个月的设计用于隔离短期反转、交易微结构和最新一个月噪声的潜在影响；本任务只预注册 exact
   prior-(2–12)，不把 skip-month 当成可搜索参数。
3. exact11 都是权益或权益主题 ETF，Top3 仍可能高度相关、集中在单一地区或风格；相对排名不自动产生跨资产
   分散，也不能在全池下跌时提供现金保护。

公开论文、数据库或其他市场的历史结果不能替代本地不可覆盖 trial、成本、容量、交易时点和前向证据。

## 4. exact 经济合同

### 4.1 universe exact11

- `name="ETF_POOL_M2_V1"`；
- `frozen_as_of=2026-07-12`；
- canonical symbol 顺序：

```text
159919.SZ
159920.SZ
159922.SZ
510300.SH
510500.SH
512170.SH
512880.SH
513060.SH
513180.SH
513330.SH
515790.SH
```

候选池不得按上市时间、历史表现、当月 coverage、交易状态或未来 outcome 删减、替补或重排。该 universe 在
历史样本结束后冻结，存在后见偏差；未来 report 必须固定披露，单靠本 trial 不能关闭。

### 4.2 数据与时间语义

- research price semantic：`TOTAL_RETURN_DIVIDEND`；
- signal timing：完整共同月末 close 后；
- execution timing：下一共同开市日 open；
- valuation timing：close；
- rebalance：每个 canonical signal date；
- holding：至下一 canonical rebalance 对应 open；
- primary target：始终为 exact3 个 symbol，各固定 `1/3`；正常情况下现金目标 exact `0`。

canonical signal month 必须满足：

1. 自然月已经完整结束；
2. SH 与 SZ 权威交易日历均已闭合；
3. signal date 是该月 SH、SZ 同时开市日期集合的最后一天；
4. exact11 在所需13个月末均具有合法研究 close；
5. execution date 是 signal date 后第一个 SH、SZ 同时开市且 Top3 均有合法 open 的交易日。

禁止使用 bars union、单市场月末、自然月最后日、月内最后一条偶然价格、未完成月份、上一交易日或后来
修订冒充上述身份。calendar/price 缺失、重复、乱序、日期漂移、无下一共同 open 或 signal/execution 同日均
fail-closed。

### 4.3 prior-(2–12) 分数

对 symbol `i` 和 signal month `s`：

```text
score_i(s) = close_i(s-1) / close_i(s-12) - 1
```

唯一观察合同：

- 必须具有 `s-12..s` 的 exact13 个连续自然月共同月末 close；
- 公式只使用 `s-12` 和 `s-1`，所以完整跳过最近共同月 `s-1 -> s` 的收益；
- `close(s)` 只用于证明当前 signal month 与最新跳过月的完整身份，不进入分数；
- `close(s-12)`、`close(s-1)` 及中间月份必须属于同一 symbol、均为正有限数值；
- 负、零、正分数均允许参加相对排名；本任务没有 absolute-momentum Gate；
- 缺任一月、重复月、乱序、symbol/date错配、null、bool、NaN、Inf、零或负价格时，整个 signal date STOP；
  不得只删除该 symbol、填零、前向填充、改用日频近似或换成 `(1–12)`。

`validation_grid` 必须 exact 空集合；不存在 `selected_lookback`、`selected_skip` 或结果后阈值。

### 4.4 完整排名与 Top3

每个 signal date 必须先形成 exact11 score rows，再执行唯一排序：

```text
primary key: score descending
tie-break: canonical symbol ascending
```

排序完成后：

- rank 1、2、3 各目标权重固定 `1/3`；
- rank 4—11 目标权重 exact `0`；
- target grid 必须保留 exact11 唯一 symbol 与 canonical 顺序；
- 负分数也不触发现金门；若全池分数均负，仍持相对最高 Top3；
- 禁止用第4名替代缺 open、停牌、未来收益缺失或 outcome 不完整的 Top3；
- 禁止先按未来可交易结果筛选再排名；
- 禁止在少于11个有效 score 时运行或用 `1/n_available` 重新归一；
- 正常 target sum exact `1`，无杠杆、无 short。

Top3 target 必须先于未来收益、label、holding outcome 或 terminal availability 读取而冻结。未来 canonical decimal
text、runtime float equality、ranking schema、rank dtype 和 digest 必须在 public receipt/shared runner 合流后重冻；
当前不得由实现者自选舍入或稳定排序实现。

### 4.5 换手与成本

成本 authority 使用项目版本化 ETF 研究成本候选：

- commission rate：`0.00025`；
- minimum commission：`5`；
- slippage：`0.001`；
- ETF 不计股票印花税；
- effective from：`2023-01-01`；
- pressure multipliers exact：`0.5, 1, 2`。

未来 config 必须逐字绑定基础值、类型、单位、应用顺序、有效期与 semantic digest。实际券商账单尚未校准，
因此成本通过也不授权 PAPER。不得观察结果后改变费用档、免除最低佣金或替换滑点。

换手和费用只按券商层 exact11 聚合 target 的实际变化计算；同一 symbol 连续入选不重复卖出再买入。停牌、缺
open、涨跌停、现金不足、整手、T+1、未成交 target 与 terminal liquidation 必须沿共享 ETF simulator 合同处理。
任一 unresolved target gap、outcome 预过滤、rank4 替补或不完整 Top3 重加权均 fail-closed。

## 5. 样本、fold 与功效边界

### 5.1 设计窗口

为与 R5/R6 exact11 快线保持同窗可比，设计输入窗口候选为：

- data start：`2023-01-01`；
- data end：`2026-07-10`。

这两个日期不是当前 readiness 结论。未来 terminal snapshot 必须证明 exact11 的 calendar、13个连续共同月末、
`TOTAL_RETURN_DIVIDEND` close、next-open 和持有期完整覆盖。第一个经济 signal 只能在 exact13 完整月末形成后
产生；尾部未完成月或无完整 exit 的持有期按共享 runner 合同排除。

exact11 最晚上市标的和13月预热会显著压缩月频观察数。当前只承认“小样本风险高、统计功效有限”，不把
理论上限或任务书中的估算当作真实 coverage。未来 report 必须给出 exact signal/outcome count、每fold月数和
置信度；coverage不足只能 `UNASSESSED/STOP`，不得扩窗、换证券或调参。

### 5.2 预注册 exact2 folds

在 terminal grid 闭合后，计划沿用 ETF 快线 exact2 anchored folds：

```json
[
  {
    "fold":1,
    "train_start":"2023-01-01",
    "train_end":"2024-12-31",
    "validation_start":"2025-01-01",
    "validation_end":"2025-06-30",
    "test_start":"2025-07-01",
    "test_end":"2025-12-31"
  },
  {
    "fold":2,
    "train_start":"2023-07-01",
    "train_end":"2025-06-30",
    "validation_start":"2025-07-01",
    "validation_end":"2025-12-31",
    "test_start":"2026-01-01",
    "test_end":"2026-06-30"
  }
]
```

train 只提供exact13预热，不拟合参数；validation 不选择 formation、skip、Top-K、方向、权重或 Gate。fold/date
任一漂移属于新 trial identity。若任一边界不能由完整共同月末和 next-open 映射实现，必须在任何经济读取前
回中央重冻，而不是运行后挪动日期。

## 6. 比较对象与相邻策略诊断

### 6.1 primary comparators

- `s0_equal`：同 exact11、同 signal/execution dates、每只固定 `1/11`、同 simulator/cost；这是判断相对排名
  集中持仓是否产生净增量的 primary comparator；
- `510300.SH` buy-and-hold：同日可投资基准，用于 active return、tracking error、IR 与 beta；不能替代
  `s0_equal` admission，也不能把指数主动收益塞入 Sharpe。

comparators 必须与 strategy 在日期、研究价格、成本、账户和 terminal exit 上逐字闭合；缺证据时 primary
只能 `UNASSESSED/STOP`。

### 6.2 R6、Faber 与 R5 仅作诊断

R9 与 R6 双重动量、R5 绝对动量、Faber 趋势保持独立 hypothesis、attempt、receipt、run、Gate 和 disposition。
只有相关策略及公共 schedule/runner 已合流后，R9 report 才可做预注册诊断：

- R9 Top3 与 R6 relative Top3 的重合率；
- 跳过最近一个月对排名、换手、收益和回撤的影响；
- R6 absolute gate 触发月份与 R9 全额持仓的风险差异；
- R5/Faber risk-on breadth 与 R9 集中暴露的同步性；
- 行业、地区、港股主题、规模/流动性和 Top3 内部相关集中度。

这些结果不参与 R9 admission，不得救援失败的 primary，也不得把多个趋势 trial 当成独立证据相加。相邻 run
缺失时诊断写 `NOT_EVALUATED`，禁止复制或重新运行对方策略作为 fallback。

## 7. 指标体系与 admission

指标口径唯一服从 `docs/research/投研评价指标与市场状态研究方法.md`。R9 同时是横截面排名信号与可执行
Top3策略，因此信号诊断和组合指标必须分开报告。

### 7.1 信号诊断

每个 signal date、fold 和 pooled 至少报告：

- cross-sectional Pearson IC 与 RankIC，对应下一 canonical holding-period return；
- mean RankIC、RankIC standard deviation、ICIR、positive-IC month count与方向；
- score coverage、rank stability、Top3 turnover、Top3/Bottom3 forward return spread；
- R9 score 与 R6 12M score、1M reversal、规模和流动性代理的相关；
- 样本月数、exact11数量、null/nonfinite/zero-variance状态。

由于每期只有11个证券且月数有限，IC/ICIR只作排序机制诊断，不是单独 promotion Gate；零方差、样本不足或
nonfinite必须标 `NOT_EVALUATED`，不得填零或删月。

### 7.2 组合主报告

每 fold、pooled、0.5x/1x/2x 至少报告：

- 成本后累计收益、CAGR、年化收益与年化波动率；
- 成本后 Sharpe，并披露频率、年化因子、样本数、分子和分母；
- Sortino、Calmar、最大回撤、回撤开始/谷底/恢复日、持续时间与未恢复状态；
- 相对 `s0_equal` 和 `510300.SH` 的 active return、tracking error、IR 与 beta；
- gross/one-way turnover、佣金、滑点、target gap、成本压力与 terminal cost；
- Top3持有期、胜率、盈亏比、集中度、主题贡献、最差月和尾部损失；
- coverage、有效signal数、缺失分类和 comparators identity。

任何 undefined、样本不足、零方差或 nonfinite 指标必须带显式状态。Sharpe、ICIR和IR不得混用公式；短样本
年化结果必须与原始月度分子、分母及样本数共同报告。

### 7.3 primary admission Gates

在任何 test/holdout 结果读取前冻结以下 exact8 布尔条件；全部通过时仍只保持 `RESEARCH_ONLY`：

1. 每个 test fold 的 strategy 1x 成本后累计收益均严格 `>0`；
2. pooled strategy 1x 成本后累计收益严格高于同窗 `s0_equal`；
3. pooled strategy 1x Sharpe finite、状态 PASS 且严格高于 `s0_equal`；
4. pooled strategy 1x Calmar finite、状态 PASS 且严格高于 `s0_equal`；
5. pooled strategy 1x 最大回撤绝对值不大于 `s0_equal`；
6. pooled strategy 2x 成本后累计收益严格 `>0`；
7. exact13月、skip-month、exact11完整排名、Top3、calendar/next-open、cost、coverage与comparators闭合；
8. public receipt、input/config/code/fold/run/report schema、no-clobber publication和fresh verification闭合。

Gate 不做多数表决。任一失败只允许 `RESEARCH_ONLY -> REJECTED`。RankIC、ICIR、R6/Faber结果、市场状态、
单一月份或低成本档不能抵消硬 Gate；阈值不得在看到结果后放宽。

### 7.4 市场状态诊断

趋势×波动率状态只按长期方法文档的低自由度定义报告：

- 状态必须在 signal `as_of` 时已知；
- 无条件结果优先，状态只解释贡献、集中、换手和尾部风险；
- 不连续状态日期不得拼成虚构净值计算 MDD/Calmar；
- 状态不改变排名、Top3、Gate 或 disposition；
- 任何状态门控或切换属于新 hypothesis/trial；
- coverage不足写 `INSUFFICIENT`，不得只汇报最好切片。

## 8. public receipt、共享 runner 与实现前置

当前 implementation whitelist 为 **exact 空集合**。只有以下前置全部满足后，经理才能基于 latest clean main
重冻实现任务书：

1. public durable trial receipt 已合流并通过冻结的 Windows development validation；Linux durability Gate须
   单独诚实记录，不能由Windows结果冒充；
2. Faber authoritative complete-common-month-end、next-common-open、统一 simulator、metrics 和共享
   `run_s1_walk_forward` 边界已合流；
3. R5、R6经济任务顺序与身份已合流，且它们的结果不进入R9 admission；
4. public receipt/shared runner API、schema、error taxonomy稳定；
5. exact11 terminal input inventory、cost schedule和两个 comparators可冻结；
6. 统筹从latest main分配新的exact base/worktree、唯一Worker和互斥白名单。

重冻必须逐字确定：

- exact production/config/unit/integration/delivery/review paths；
- receipt start/terminal types、字段顺序、错误码、path与平台能力；
- start早于第一次 test/holdout、future-return、label、ranking outcome、simulation或comparator读取；
- existing/partial/reparse/collision/identity drift时全部经济调用exact0；
- schedule、score、ranking、Top3、fold、cost、input、metric、Gate、report和run digests；
- ordered schemas/dtypes、canonical decimal、outputs exact set、report fields和final conclusion；
- focused Windows validation、Linux Gate和唯一真实trial的独立授权边界。

禁止复制 Faber、REGIME、R3/R4/R5/R6 的私有 receipt 或 runner-local filesystem helper，禁止形成第二套
month-end helper、simulator、metrics或publication verifier。若需要新的通用模块、第三消费者或跨域基础设施，
research包立即STOP，由统筹转交framework领域重冻。

## 9. 未来测试与验收矩阵

依赖满足后的实现任务书至少逐名覆盖：

- exact13缺中间月、重复月、尾部未完成月、单市场月末、future month、错误symbol；
- 证明公式使用`s-1/s-12`且不使用`close(s)`；最新一个月暴涨不得改变当前R9分数；
- score全负时仍选择相对最高Top3，不得自动持现金；
- exact tie使用canonical symbol ascending，row/file order不得改变Top3；
- exact11任一缺失时整期STOP，禁止rank4替补、删证券或`1/n_available`；
- future outcome缺失不得在排名或target形成前过滤；
- 连续Top3保留时不制造虚构卖出/买入和成本；
- calendar→next-open、持有期、terminal exit和comparator dates逐字一致；
- 0.5x/1x/2x复用相同target identity，仅成本倍率变化；
- fold、universe、price semantic、skip、cost、Gate或comparator任一漂移；
- public receipt existing/partial/reparse/alias/collision/drift时所有holdout/ranking outcome/simulation exact0；
- undefined IC/ICIR/Sharpe/Calmar/IR、未恢复回撤和coverage不足的显式状态；
- R6/Faber缺失只使诊断`NOT_EVALUATED`，不得影响或救援R9 admission；
- 旧strategy kind、R5/R6/Faber和shared runner输出身份不因新增R9静默漂移。

实现者自测、独立审查、Windows feedback、Linux Gate、真实trial、PAPER和LIVE必须分阶段授权；前一阶段通过不
自动授权后一阶段。

## 10. 当前角色、资源与写范围

本阶段唯一写路径：

```text
docs/research/tasks/M2_STRATEGY_R9_ETF跳月相对动量任务书.md
```

当前明确只读且不得创建或修改：

- `docs/research/roadmaps/`、shared progress report；
- R5、R6、R11任务书与其他策略文档；
- `docs/research/deliveries/`、`docs/research/reviews/`；
- `configs/research/`；
- `src/quant/`、`tests/`；
- research run、receipt、evidence、temp、data、ledger、账户与外部状态。

本阶段资源：`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / WORKER0 / STAGE0 / COMMIT0`。

后续实现必须由统筹分配唯一 worktree/Worker；实现与独立审查使用不同上下文。research经理不直接实现、
验证、合流或退休来源线。

## 11. STOP、反例与当前终态

任一以下情况立即STOP，不得由实现者猜测或缩窄成更容易通过的策略：

- public receipt或Faber/shared runner未合流、未验证或public contract仍漂移；
- exact11无法形成exact13连续共同月末，样本/成本/comparators不能同窗闭合；
- future whitelist、schema、digest、cost、fold、Gate或错误taxonomy未逐字冻结；
- 需要改变prior-(2–12)、skip=1、Top3、fixed1/3、long-only或完整排名；
- 需要添加absolute gate、现金替代、rank4 fallback、重新归一、参数搜索或杠杆；
- 需要按结果扩窗、换universe、改变状态、成本、fold或admission；
- 任何经济结果已读取后才提出上述变化；
- 发现必须复制公共schedule/simulator/metrics/receipt，或需要新的通用基础设施；
- 当前worktree、branch、base、owner、exact写路径或Git身份漂移。

必须锁住的最小反例：

1. 当前月`s-1 -> s`暴涨但`P_(s-1)/P_(s-12)`不变时，本期score和rank必须不变；
2. 全部11个score为负时仍持rank1—3各`1/3`，不能借用R6的absolute gate；
3. rank3与rank4同分时按canonical symbol决定，不能按输入row order；
4. rank2未来收益缺失时不能用rank4替补，也不能在排名前剔除rank2；
5. 仅10个symbol有score时整期STOP，不能每只`1/3`运行一个缩小池；
6. R6表现更好不能让R9 Gate失败后切换为R6或合并trial；
7. 高RankIC不能抵消成本后Top3收益、Sharpe、回撤或2x成本Gate失败。

当前终态唯一为：

`TASKBOOK_PENDING_REVIEW / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`

这只证明经济合同已在真实结果前写入任务书，不证明实现存在、策略有效、开发验证通过或可以交易。

## 12. 参考来源

- Narasimhan Jegadeesh, Sheridan Titman, “Returns to Buying Winners and Selling Losers: Implications for Stock
  Market Efficiency,” *Journal of Finance* 48(1), 1993，DOI：<https://doi.org/10.1111/j.1540-6261.1993.tb04702.x>。
- Mark M. Carhart, “On Persistence in Mutual Fund Performance,” *Journal of Finance* 52(1), 1997，DOI：
  <https://doi.org/10.1111/j.1540-6261.1997.tb03808.x>。
- 项目指标与状态方法SSOT：`docs/research/投研评价指标与市场状态研究方法.md`。
- 相邻但独立的本地任务合同：`docs/research/tasks/M2_STRATEGY_R5_ETF十二月绝对动量任务书.md`、
  `docs/research/tasks/M2_STRATEGY_R6_ETF双重动量任务书.md`。

引用只支持假设来源和诊断设计；本地收益、风险、成本、容量、可执行性和disposition必须由未来不可覆盖trial证明。
