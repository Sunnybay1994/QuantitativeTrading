# M2-STRATEGY-R6：ETF 双重动量任务书

> - task id：`M2-STRATEGY-R6-ETF-DUAL-MOMENTUM`
> - 领域：research
> - 当前阶段：`TASKBOOK_ECONOMIC_CONTRACT_PENDING / WAITING_R5_ORDER_AND_PUBLIC_TRIAL_RECEIPT_MERGE / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> - base/head：`f440f18aebb2e8a7393cb08dbaa8c7db1fc8dc93`
> - branch：`codex/m2-strategy-r6-etf-dual-momentum`
> - worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-strategy-r6-etf-dual-momentum`
> - 任务性质：经济合同预注册；不是实现、验证、回测、PAPER 或 LIVE 授权

### 首轮 taskbook 独立审查历史

首轮被审任务书为 16,773 bytes，SHA256=
`2f341ec7aefd2fb35e5f6c669b8431f47a41b6ee72f634f53445eee6d07e722f`；独立结论为
`TASKBOOK_REVIEW_FAIL / P0=0 / P1=1 / P2=0`。经济核心合同通过，唯一 P1 是没有把 Faber 已合流的
authoritative common-month-end、next-common-open schedule 与共享 `run_s1_walk_forward` 边界明确列为未来实现和
运行前置。本节永久保留该失败历史；后续修正不得把首轮写成 PASS，也不得据静态合同消费 trial。

## 1. 研究目标与身份

本任务预注册一个低自由度、本地 long-only ETF 双重动量策略。每个共同自然月末先使用完整 exact11 的十二月
总回报进行横截面相对排名，再只对相对排名 Top3 施加自身十二月绝对动量门。通过门的槽位持有 ETF，未通过
的槽位持有现金。研究问题是：在完全相同的样本、日历、next-open、成本和比较对象下，这一“relative ranking
+ absolute gate”能否产生稳定、可执行且成本后为正的样本外结果。

身份逐字冻结为：

- `hypothesis_id="m2-etf-dual-momentum-12m-top3-local-v1"`；
- `strategy_kind="etf_monthly_dual_momentum"`；
- `strategy_version="1.0.0"`；
- `trial_identity="m2-etf-dual-momentum-12m-top3-local-v1"`；
- `attempt_ordinal=1`；
- `trial_delta=1` 仅在未来 durable attempt start 成功发布后计入；当前为 `0`。

本任务必须标记 `LOCAL_ETF_DUAL_MOMENTUM_ADAPTATION_TRIAL`。Antonacci 的公开研究支持把 relative 与
absolute momentum 结合为可检验假设，但其多资产模块、工具、现金/债券替代、历史样本和实现细节与本项目
不同。本任务不得称论文逐字复现，也不得用论文结果声称本地 ETF 策略有效。

未来真实运行的最高自动状态仅为 `RESEARCH_ONLY`；任何 Gate 失败只允许降为 `REJECTED`。本任务不授权
PAPER、shadow、LIVE 或自动策略切换。

## 2. 非目标

本任务明确不做：

- 搜索 formation window、Top-K、方向、absolute threshold、权重、现金替代物或调仓频率；
- 比较后选择 3/6/9/12 月、Top1/Top2/Top3、`1/n_active`、equal-risk 或 volatility scaling；
- 使用债券、货币基金、黄金或其他未冻结资产替代现金；
- 允许杠杆、做空、风险平价、均值方差优化或 covariance 估计；
- 用 rank4 或更低排名替补未通过 absolute gate 的 Top3 槽位；
- 把 R5 绝对动量、Faber、R8 波动率目标或市场状态诊断与本 trial 联合择优；
- 用市场状态选择当期策略、回填历史赢家或事后修改状态阈值；
- 强迫时间序列/组合策略报告横截面 IC；
- 在 public durable trial receipt 合流和 R5 顺序前置解除前实现或运行任何代码。

## 3. 公开依据与本地适配

1. Antonacci 的 *Risk Premia Harvesting Through Dual Momentum* 讨论 relative 与 absolute momentum 的组合，
   并指出 absolute filter 的主要作用是降低波动与回撤；本任务只采用这两个信号层次。
2. Antonacci 的 *Absolute Momentum* 与 Moskowitz–Ooi–Pedersen 的 time-series momentum 文献支持用过去自身
   收益方向形成风险门，但原研究并不证明本地 exact11 ETF 或当前成本下的结论。
3. 本任务将原跨资产思路改为中国 ETF exact11 横截面 Top3、固定槽位和现金剩余，是独立的本地适配假设。

公开文献仅进入 hypothesis provenance。真实收益、Sharpe、回撤、成本和可交易性必须由未来不可覆盖 trial
证明。

## 4. exact universe、数据和时间

### 4.1 universe

- `name="ETF_POOL_M2_V1"`；
- `frozen_as_of=2026-07-12`；
- canonical order exact11：

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

这一顺序同时是 exact tie-break authority。不得用运行时文件顺序、交易所顺序、Python set/dict 顺序、symbol
字典序或任何结果相关顺序替代。

不得因上市时间、缺失、排名、当期表现或执行结果缩小候选集合。证券池在历史样本结束后冻结，存在历史候选池
后见偏差；该 caveat 必须进入未来 report，且本 trial 无权关闭。

### 4.2 数据与时点

- data start：`2023-01-01`；
- data end：`2026-07-10`；
- research price：`TOTAL_RETURN_DIVIDEND`；
- signal grid：每个已完成自然月中 SH 与 SZ 都开市的最后一个共同交易日；
- signal timing：共同月末 close 后；
- execution：下一共同开市日 open；
- valuation：close；
- rebalance：每个 canonical signal date。

共同月末只由两市场权威 calendar 交集构造。bars union、单市场开市、自然月最后一日、月内最后一条价格或
事后补齐日均不得冒充共同月末。缺日历、重复 `(market,date)`、乱序、未知市场、无下一共同开市日或类型/日期
漂移均 fail-closed。

## 5. 双重动量算法

### 5.1 完整 exact11 十二月信号

对每个 symbol、signal month `t`：

```text
momentum_12m(t) = close(t) / close(t-12) - 1
```

必须满足：

- 从 `t-12` 至 `t` exact13 个连续自然月共同月末；
- exact11 每个 symbol 都有完整、唯一、有限、正数的13个 close；
- 当前月和12个月前的 close 均包含；中间月份不得缺失；
- 不足、缺月、重复、乱序、symbol/date错配、null、bool、NaN、Inf、零或负价格时，**整期 STOP**；
- 禁止先排除缺信号 symbol 再对缩小后的 universe 排名；
- 禁止使用日频近似252日、月内平均/最高价、前向填充、较短 fallback 或later可见价格。

### 5.2 relative ranking

只有完整 exact11 信号闭合后才排序：

1. `momentum_12m` descending；
2. 数值 exact 相等时，按第4.1节 canonical order 较前者优先；
3. 选取 exact Top3，rank exact `1,2,3`；
4. Top3 之外不再参与当期 target；
5. 排名不得使用未来收益、未来可成交性、执行日 open、成本后结果或当期 outcome coverage。

tie 的数值相等必须在信号 canonical numeric contract 下确定。近似相等容差、rounding 后 tie 或不稳定 sort
均禁止；具体 dtype 与 canonical serialization 必须在 future re-freeze 中逐字冻结。

### 5.3 absolute gate 与固定槽位

只对已经选出的 Top3 逐槽执行：

- selected symbol `momentum_12m > 0`：该 rank slot 目标权重为 runtime `1.0 / 3`；
- selected symbol `momentum_12m <= 0`：包含 exact zero，该 rank slot 目标权重 exact `0.0`，槽位留现金；
- 不向其他 selected symbol 重分配空槽；
- 不以 rank4 或以后 symbol 替补；
- 当 Top3 全部非正，exact11 目标均为零，即全现金；
- 每 signal date 输出完整 exact11 target rows；非selected rows exact zero；
- active数为0/1/2/3时总ETF权重分别为0、1/3、2/3、1，剩余为现金。

注意：因为排名在完整 exact11 上进行，若 rank3 已非正，rank4以后不可能具有更高的正动量；仍需保持“不替补”
合同，以防未来实现将 absolute filter错误地提前到ranking前或按缺失缩小集合。

窗口 exact12个月、Top3、higher direction、strict zero threshold、固定 `1/3` slots 均不是 parameter grid。
未来 `selected_parameters` 只能记录固定值，`validation_grid=[]`。

## 6. 成本和执行合同

成本 authority 使用版本化 ETF 研究成本：

- commission rate：`0.00025`；
- minimum commission：`5`；
- slippage：`0.001`；
- ETF 不计股票印花税；
- effective from：`2023-01-01`；
- pressure multipliers exact：`0.5, 1, 2`。

base值、有效期、应用顺序、单位和 semantic digest 必须在 future config/run identity 闭合；具体配置字节由 receipt
合流后的 re-freeze 决定。三档成本必须复用同一 target object/identity，不得按成本重排或改变持仓。不得在看到
结果后免除minimum commission、切换滑点或挑选最有利成本档。

执行沿用权威 A 股/ETF 日频 next-open 合同，披露整手、现金、缺open、停牌、涨跌停、T+1和target gap。
任何 unresolved gap、未来 outcome 预过滤、缺失后替补或不完整组合重加权均 fail-closed。

## 7. walk-forward、基线与trial隔离

未来唯一fold exact2：

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

训练段只用于13个月预热；validation 不进行参数选择。sealed test 只允许在 durable attempt start 后消费一次。
fold/date/grid漂移属于新 trial identity，不能以“修复”名义重开本 attempt。

比较对象：

- `s0_equal`：同 exact11、同signal/execution、每slot `1/11`、同simulator/cost，用于判断策略相对持有全池的
  成本后增量；
- `510300.SH`：同日 `TOTAL_RETURN_DIVIDEND` 可投资基准，只用于 active return、tracking error 和 IR；
- R5：是独立 hypothesis/trial。未来两者均完成后可另立只读增量诊断，但 R5 结果不进入 R6 admission，
  不作为 comparator 前置，不与 R6 共用 attempt、候选选择或 winner 结论。

Sharpe 不以指数主动收益为分子；IR 不冒充 Sharpe。任一比较对象缺同窗证据时 primary 也只能 STOP/UNASSESSED。

## 8. 指标与admission

指标口径服从 `docs/research/投研评价指标与市场状态研究方法.md`。

### 8.1 报告指标

每fold、pooled、0.5x/1x/2x 至少报告：

- 成本后累计收益与 CAGR；
- 成本后 Sharpe、年化波动率及完整分子/分母/频率/样本数；
- 最大回撤、回撤开始/谷底/恢复日、持续时间和未恢复状态；
- Sortino、Calmar、MAR 与 downside deviation；
- 相对510300的active return、tracking error与IR；
- gross turnover、one-way turnover、commission、slippage、target gap、成交与成本压力；
- signal dates、coverage、Top3、active slots、cash weight、concentration、tie count和缺失分类。

undefined、零方差、样本不足、未恢复回撤或nonfinite必须显式状态化，禁止填零、极大数或静默删期。

### 8.2 primary Gate

在任何目标结果读取前冻结以下条件。全部通过仍只保持 `RESEARCH_ONLY`：

1. 每个 test fold 的 strategy 1x 成本后累计收益均 `>0`；
2. pooled strategy 1x 成本后累计收益严格高于同窗 `s0_equal`；
3. pooled strategy 1x Sharpe finite、状态 PASS 且严格高于 `s0_equal`；
4. pooled strategy 1x Calmar finite、状态 PASS 且严格高于 `s0_equal`；
5. pooled strategy 1x 最大回撤绝对值不大于 `s0_equal`；
6. pooled strategy 2x 成本后累计收益严格 `>0`；
7. exact11 full ranking、Top3、tie-break、absolute gate、fixed-slot targets、cost/coverage/comparator identity闭合；
8. public receipt、input/config/code、run/report schema、no-clobber publication与fresh verify闭合。

Gate 不投票。任一失败只允许 `RESEARCH_ONLY -> REJECTED`。IR、Sortino、状态切片、某一fold、某一成本档或
R5/Faber的历史表现都不能抵消硬 Gate。阈值不得在首轮后放宽。

### 8.3 市场状态仅诊断

趋势×波动率状态必须在结果前按长期方法文档预注册，且signal `as_of` 可知。它只用于解释收益来源和失效环境：

- 不参与八项Gate；
- 不改变Top3、absolute gate或仓位；
- 不选择R5/R6/Faber赢家；
- 不用全样本分位数回填历史；
- coverage不足时写 `INSUFFICIENT`。

## 9. public receipt依赖与当前空白名单

public durable trial receipt 尚未合流，R5 必须先按队列完成，且 Faber authoritative common-month-end、
next-common-open schedule 与共享 `run_s1_walk_forward` 边界必须先完成合流。因此当前 implementation whitelist
为 **exact 空集合**。本任务不猜测 public module、API、schema、error taxonomy、receipt path或平台durability
语义，也不复制第二套月末 schedule、next-open、simulator 或 metrics 实现。

receipt 验证完成、R5 顺序前置解除且 Faber 上述公共边界完成合流前：

- 不创建config、production、tests、delivery、review或run artifact；
- 不派Worker、运行Python、读取数据/经济output或消费trial；
- 不复制Faber、REGIME、PIT或其他runner-local receipt；
- 不从未合流 Faber 分支复制 common-month-end、next-common-open、simulator 或 metrics 代码；
- 不在research runner实现mkdir/open/fsync/link/path containment/fresh verify；
- 公开论文、任务书或静态代码都不计attempt。

上述三项前置全部满足后，未来必须从 latest clean main 的新 authoritative HEAD 重新审计调用图并重冻：

1. public receipt exact import/types/fields/order/schema/errors；
2. start严格早于第一笔future return、label、simulation或holdout读取；
3. existing/partial/reparse/alias/collision/identity drift时经济链0-call；
4. attempt identity绑定config/code/universe/folds/signal/ranking/portfolio/cost/inputs/Gates；
5. terminal绑定fresh verified immutable run；
6. exact production/config/tests/delivery/review paths与逐名test nodes；
7. Windows feedback与Linux durability Gate的诚实边界。
8. Faber 已合流 schedule、shared runner、simulator 与 metrics 的 exact public 调用路径；R6 只允许复用，不得复制。

## 10. 当前角色和写范围

当前唯一允许写：

```text
docs/research/tasks/M2_STRATEGY_R6_ETF双重动量任务书.md
```

以下只读且不得创建或修改：

- `docs/research/roadmaps/`；
- `docs/research/deliveries/`；
- `docs/research/reviews/`；
- `configs/research/`；
- `src/quant/`；
- `tests/`；
- research runs、receipt、evidence、temp、data与账户路径。

当前资源：`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / WORKER0 / STAGE0 / COMMIT0`。

## 11. future re-freeze验收与反例

只有 receipt 合流验证、R5 顺序前置解除、Faber authoritative schedule/shared runner 边界完成合流，并由统筹
给出基于 latest clean main 的新 base/worktree 后才允许后续工作：

1. 经理只读审计 latest main 的 factor/strategy/Faber common-month-end/next-common-open scheduler、共享
   `run_s1_walk_forward`、simulator、metrics、report 与 receipt 调用图；
2. 任务书冻结唯一production/config/test/delivery/review路径，不让Worker选目录；
3. 冻结ordered schemas/dtypes、canonical digests、run inputs、output set和report fields；
4. 独立reviewer复核完整ranking、tie-break、absolute gate、fixed slots、receipt时序与旧kind回归；
5. review PASS后才申请Windows定向开发验证；Windows PASS不冒充Linux Gate；
6. 开发验证闭合后另获唯一真实trial授权，不从本任务书推定。

未来逐名测试至少覆盖：

- exact11任一symbol缺月/非法导致整期STOP，禁止缩池ranking；
- exact13缺中间月、重复月、未来尾部、单市场月末与日频近似；
- 全正、全负、零边界、active slots 0/1/2/3；
- momentum ties按canonical order，输入行/文件顺序反转后Top3与bytes identity不变；
- absolute filter只能在Top3后执行；rank4禁止替补；
- target exact11，selected positive为`1/3`，其余zero，不重归一；
- future outcome缺失不得预过滤、替补或删期；
- 0.5x/1x/2x复用同一target object/identity；
- receipt existing/partial/reparse/identity drift时label/simulation exact0；
- undefined Sharpe/Calmar/IR和coverage不足明确降级；
- 旧strategy kinds与R5 identity不因R6静默漂移。

## 12. STOP与当前终态

下列任一情况立即STOP，不得由实现者猜测：

- public receipt未合流/未验证，或R5顺序前置尚未解除；
- Faber authoritative common-month-end、next-common-open schedule 或共享 `run_s1_walk_forward` 边界尚未合流；
- future whitelist、schema、digest、cost authority、tie numeric contract或errors未冻结；
- 需要复制通用文件、路径、持久化或carrier工具；
- 数据不能形成完整exact11×exact13共同月末；
- 需要改变window、Top3、tie-break、absolute threshold、fixed-slot、cost、fold、universe或Gate；
- 已读取目标结果后才提出经济合同变化；
- worktree、owner、branch、base或写范围漂移。

当前唯一终态：

`TASKBOOK_ECONOMIC_CONTRACT_REWORK_PENDING_REVIEW / WAITING_R5_PUBLIC_RECEIPT_AND_FABER / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`

它只证明经济假设已预注册，不证明代码、开发验证、策略有效性或可交易性。

## 13. 参考来源

- Gary Antonacci, “Risk Premia Harvesting Through Dual Momentum,” SSRN 2042750：
  <https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2042750>。
- Gary Antonacci, “Absolute Momentum: A Simple Rule-Based Strategy and Universal Trend-Following Overlay,”
  SSRN 2244633：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2244633>。
- Tobias J. Moskowitz, Yao Hua Ooi, Lasse Heje Pedersen, “Time Series Momentum,” *Journal of Financial
  Economics* 104(2), 2012：<https://faculty.som.yale.edu/tobymoskowitz/research/>。

这些来源只支持研究假设；本地经济结论必须来自未来唯一、不可覆盖且经fresh verify的trial。
