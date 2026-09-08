# M2-STRATEGY-R5：ETF 十二月绝对动量任务书

> - task id：`M2-STRATEGY-R5-12M-ABSOLUTE-MOMENTUM`
> - 领域：research
> - 当前阶段：`TASKBOOK_ECONOMIC_CONTRACT_PENDING / WAITING_PUBLIC_TRIAL_RECEIPT_MERGE / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> - base/head：`f440f18aebb2e8a7393cb08dbaa8c7db1fc8dc93`
> - branch：`codex/m2-strategy-r5-12m-absolute-momentum`
> - worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-strategy-r5-12m-absolute-momentum`
> - 任务性质：经济合同预注册；不是实现、开发验证、回测、PAPER 或 LIVE 授权

## 1. 目标与结论上限

本任务预注册一个低自由度、long-only、无杠杆的 ETF 十二月绝对动量策略，用于回答：在本项目冻结的
`ETF_POOL_M2_V1` 上，逐证券十二个月总回报为正时保留其固定风险槽位、否则持有现金，能否在完全相同的
样本、执行时点和成本合同下改善 equal-weight 基线的成本后收益风险特征。

策略身份固定为：

- `hypothesis_id="m2-etf-absolute-momentum-12m-local-v1"`；
- `strategy_kind="etf_monthly_absolute_momentum"`；
- `strategy_version="1.0.0"`；
- `trial_identity="m2-etf-absolute-momentum-12m-local-v1"`；
- `attempt_ordinal=1`；
- `trial_delta=1`，仅在未来 durable attempt start 成功发布后计入；当前为 `0`。

该身份必须标记为 `LOCAL_LONG_ONLY_ETF_ABSOLUTE_MOMENTUM_ADAPTATION_TRIAL`。它不是 Moskowitz–Ooi–Pedersen
期货 long/short、波动率缩放策略的逐字复现，也不是 Antonacci 跨资产配置实例的逐字复现。公开论文只提供
经济假设来源，不能证明本地 ETF、当前样本或当前成本下仍然有效。

未来真实运行的最高自动结论仅为 `RESEARCH_ONLY`；任一 Gate 失败只允许降为 `REJECTED`。本任务不授权
`PAPER_CANDIDATE`、PAPER、shadow、LIVE、参数搜索或自动策略切换。

## 2. 非目标

本任务不做：

- 搜索 1—12 月窗口、方向、阈值、Top-K、现金替代物、权重或调仓频率；
- 在看到任何目标收益后比较 `fixed-slot` 与 `1/n_active`；
- 做空负动量 ETF、使用杠杆、波动率缩放、风险平价或协方差优化；
- 把 Faber 十月均线、R6 双重动量、R8 波动率目标或市场状态诊断合并成组合 trial；
- 用趋势×波动率状态选择赢家、改变仓位或挽救失败的 primary；
- 读取 immutable research run、forward run、PAPER、broker、OMS 或账户数据；
- 在 public durable trial receipt 合流并验证前实现任何生产代码、测试、配置或 runner-local receipt；
- 把横截面 IC 强加给本时间序列择时策略。

## 3. 公开研究依据与本地适配边界

1. Moskowitz、Ooi、Pedersen 的 *Time Series Momentum* 记录了多类期货在 1—12 个月区间的收益延续，原设计
   包含 long/short 和风险缩放；本任务只借用“自身过去收益方向”的假设，不复制其交易工具、空头或杠杆。
2. Antonacci 的 *Absolute Momentum* 把正负自身回报用于规则化风险开关；本任务将其改写为 A 股 ETF 二级市场
   的 long-only 固定槽位 overlay。
3. Hurst、Ooi、Pedersen 的长期趋势研究说明趋势收益应跨时期和状态审视；本项目因此报告预注册状态切片，
   但不把这些历史文献结果当成本地有效性证据。

正式结果必须清楚区分“公开研究支持可检验假设”与“本项目真实 OOS/forward 证据”。

## 4. exact 经济合同

### 4.1 候选池

universe exact：

- `name="ETF_POOL_M2_V1"`；
- `frozen_as_of=2026-07-12`；
- symbol 顺序 exact11：

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

不得依据上市时间、结果、当期 coverage 或单只表现删减、替补或重新排序。该证券池在历史样本结束后冻结，
存在候选池后见偏差；该 caveat 必须进入未来 report，且单靠本 trial 不能关闭。

### 4.2 数据与时间语义

- data start：`2023-01-01`；
- data end：`2026-07-10`；
- 研究价格：`TOTAL_RETURN_DIVIDEND`；
- signal date：每个已完成自然月中 SH、SZ 均开市的最后一个共同交易日；
- signal timing：该 signal date 收盘后；
- execution：下一共同开市日 open；
- valuation：close；
- rebalance：每个 canonical signal date；
- 只允许从当时已经完成的共同月末 close 构造信号；当月月末之后的价格、later revision 或单市场月末不可见。

共同月末必须由 SH/SZ 权威日历交集构造。bars union、单市场开市、自然月最后一日或月内最后一条偶然记录
都不能冒充共同月末。日历缺失、重复、乱序、未知市场、无下一共同执行日或 date/schema 漂移均 fail-closed。

### 4.3 十二月绝对动量

对每个 symbol 和 signal month `t`：

```text
absolute_momentum_12m(t) = close(t) / close(t-12) - 1
```

唯一窗口规则：

- 必须具有从 `t-12` 到 `t` 的 exact13 个连续自然月共同月末 close；
- `close(t)` 与 `close(t-12)` 均包含在窗口中，中间月份不得缺失；
- 所有价格必须是 exact symbol 的有限正数；
- `absolute_momentum_12m > 0`：该 symbol 的固定槽位 risk-on；
- `absolute_momentum_12m <= 0`：包含 exact zero，固定槽位为现金；
- 不足13个月、缺月、重复月、乱序、symbol/date错配、null、bool、NaN、Inf、零或负价格均 fail-closed，
  不得填零、前向填充、使用日频近似12个月、退回更短窗口或把该 symbol 静默排出分母。

只运行这一个公式、一个窗口、一个方向和一个阈值。12个月不是 validation grid；未来 report 的
`selected_parameters` 只能诚实记录固定参数，`validation_grid` 必须为空。

### 4.4 固定槽位组合

primary 是 fixed-slot overlay，不是 active-only 重新归一：

- 每个 exact11 symbol 独占一个固定 `1/11` 风险槽位；
- 正动量 symbol 的目标权重为 runtime `1.0 / 11`；
- 非正动量 symbol 的目标权重 exact `0.0`；
- 剩余权重留在现金；
- 全部非正时 exact11 目标均为零，即全现金；
- 不向仍为正的 symbol 重分配空出的槽位，不允许 `1/n_active`；
- 每个 signal date 必须输出 exact11、唯一 symbol、固定顺序的完整 target grid；
- 不得因交易不可达、未来收益缺失或某标的无执行结果而用下一名替补、删行或重新归一。

目标权重的经济 identity 因而由 positive mask 和固定 `1/11` 构成。未来 canonical digest 文本、runtime float
相等规则与 output schema 必须在 public receipt 合流后的任务书重冻中逐字确定；本阶段不得由 Worker 猜测。

### 4.5 成本与执行

成本 authority 使用项目版本化 ETF 研究成本：

- commission rate：`0.00025`；
- minimum commission：`5`；
- slippage：`0.001`；
- ETF 不计股票印花税；
- effective from：`2023-01-01`；
- pressure multipliers exact：`0.5, 1, 2`。

基础值、有效期、应用顺序、费用单位及 semantic digest 必须在未来 config 与 public run identity 中闭合。实际
券商账单尚未校准；因此成本通过也不自动授权 PAPER。不得在看到结果后改用不同成本档、免除 minimum
commission 或改变滑点。

模拟必须沿用权威 A 股/ETF 日频 next-open 合同，并披露整手、现金、缺 open、停牌、涨跌停与 T+1 等目标缺口。
任一 unresolved target gap、未来 outcome 预过滤、Top-K 替补或不完整组合重加权均 fail-closed。

## 5. walk-forward 与比较对象

为保持与当前 ETF 快线同窗可比，未来唯一 fold exact2：

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

训练段仅用于13个月预热，不拟合参数。validation 不选窗口、方向、阈值或权重；sealed test 只允许在 durable
attempt start 后消费一次。fold/date/grid 任一漂移属于新 trial identity，而非同一 attempt 的“修复”。

比较对象分工：

- `s0_equal`：同 exact11、同 signal/execution dates、每槽位固定 `1/11`、同 simulator/cost；用于判断绝对动量
  overlay 相对持有全部 ETF 的净增量；
- `510300.SH`：同日 `TOTAL_RETURN_DIVIDEND` 可投资基准；只用于 active return、tracking error 与 IR；
- Sharpe 不使用指数主动收益作分子；IR 不冒充 Sharpe。

strategy、`s0_equal` 和 benchmark 必须在日期、价格口径、成本与执行边界上闭合。比较对象缺证据时 primary
也只能 `UNASSESSED/STOP`，不能单独晋级。

## 6. 指标体系与 admission

指标口径服从 `docs/research/投研评价指标与市场状态研究方法.md`。本时间序列策略不强制报告横截面 IC。

### 6.1 主报告

每fold、pooled、0.5x/1x/2x 至少报告：

- 成本后累计收益与 CAGR；
- 成本后 Sharpe，并披露年化因子、收益频率、样本数、分子和分母；
- 年化波动率、最大回撤、回撤开始/谷底/恢复日、持续时间与未恢复状态；
- Sortino 与 Calmar，包括 MAR、downside deviation 及不可定义状态；
- 相对 `510300.SH` 的 active return、tracking error 与 IR；
- gross turnover、one-way turnover、费用、滑点、成交/target gap 和成本压力；
- invested slot count、cash weight、有效 signal dates、coverage、集中度和缺失分类。

任何 undefined、样本不足、零方差或 nonfinite 指标必须带显式状态，不得填零、极大数或静默删期。

### 6.2 primary admission Gates

在任何目标结果读取前冻结以下布尔条件；所有条件均通过时仍只保持 `RESEARCH_ONLY`：

1. 每个 test fold 的 strategy 1x 成本后累计收益均 `>0`；
2. pooled strategy 1x 成本后累计收益严格高于同窗 `s0_equal`；
3. pooled strategy 1x Sharpe finite、状态 PASS 且严格高于 `s0_equal`；
4. pooled strategy 1x Calmar finite、状态 PASS 且严格高于 `s0_equal`；
5. pooled strategy 1x 最大回撤绝对值不大于 `s0_equal`；
6. pooled strategy 2x 成本后累计收益严格 `>0`；
7. exact13 month、fixed-slot target、signal/execution、cost、coverage 与 comparator identity 全部闭合；
8. public receipt、input/config/code、run/report schema、no-clobber publication 和 fresh verify 全部闭合。

Gate 不做多数表决；任何一项失败只允许 `RESEARCH_ONLY -> REJECTED`。Sortino、IR、胜率、状态切片、单月
极端收益或某个成本档的优异表现不能抵消硬 Gate。阈值不得从结果生成或在首轮后放宽。

### 6.3 市场状态诊断

趋势×波动率切片只能按既有长期方法文档的低自由度原则预注册，并满足 signal `as_of` 可知。它只回答策略
何时贡献或失效：

- 不参与上述八项 Gate；
- 不决定是否持仓或选择另一策略；
- 不以全样本分位数回填历史；
- 不在看到 R5 结果后改窗口、阈值或状态定义；
- 状态覆盖不足时写 `INSUFFICIENT`。

## 7. trial receipt 与不可覆盖执行边界

public durable trial receipt 尚未合流；因此当前 implementation whitelist 为 **exact 空集合**。本任务现在不
冻结或猜测 public module path、API 类型、字段、错误码、Windows/Linux durability 语义或 receipt 文件路径。

receipt 合流并完成其自身验证前：

- 不得创建 config、production、tests、delivery 或 review；
- 不得派 Worker、运行 Python、读取经济 output 或启动 trial；
- 不得把 Faber、REGIME、PIT 或其他 runner 的私有 receipt 复制到本任务；
- 不得在 runner-local 实现 mkdir/open/fsync/link/path containment/fresh verify；
- 不得把静态 taskbook、公开论文或已有策略收益计作本 hypothesis 的 attempt。

未来任务书必须基于新的 authoritative HEAD 重新冻结：

1. public receipt 的 exact import path、public types、字段顺序、schema 和错误状态；
2. start 必须早于第一笔未来收益、label、simulation 或 holdout 读取；
3. existing start/terminal、identity漂移、partial、reparse、alias、collision 的 0-call STOP；
4. attempt identity 对 config/code/universe/folds/signal dates/portfolio/cost/inputs/Gates 的绑定；
5. terminal 对 fresh verified immutable run 的绑定；
6. 逐路径 implementation whitelist、逐名测试与平台 Gate。

## 8. 当前写范围与角色

本阶段唯一允许写：

```text
docs/research/tasks/M2_STRATEGY_R5_ETF十二月绝对动量任务书.md
```

当前明确只读且不得创建/修改：

- `docs/research/roadmaps/`；
- `docs/research/deliveries/`；
- `docs/research/reviews/`；
- `configs/research/`；
- `src/quant/`；
- `tests/`；
- research run、receipt、evidence、temp、data 与账户路径。

本阶段：`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / WORKER0 / STAGE0 / COMMIT0`。

## 9. receipt 合流后的重冻与验收矩阵

只有 public receipt 已合流、验证并由统筹给出新的 exact base/worktree 后，才允许 REWORK：

1. 只读审计 latest main 的 factor/strategy/scheduler/simulator/report/public receipt 调用图；
2. 由经理冻结唯一 production/config/test/delivery/review paths，不允许 Worker 选择目录；
3. 冻结 exact ordered schemas、dtypes、canonical digests、run inputs、output set 与 report fields；
4. 独立 reviewer 验证 fixed-slot、时间前像、receipt 时序和旧 strategy kind 回归；
5. 静态审查 PASS 后再申请定向 Windows development validation；Windows PASS 不冒充 Linux durability Gate；
6. 所有开发验证闭合后，另获唯一真实 trial 授权；不得从本任务书推定。

未来至少逐名覆盖以下反例：

- exact13中缺任一中间月、重复月、非共同月末、单市场calendar或未来尾部；
- close等于12月前close，必须落 cash；正负 `epsilon` 锁 strict边界；
- active数为0/1/3/7/11时，正动量行始终 `1/11`，不得重归一；
- symbol顺序、候选集合、fold/date/cost/comparator漂移；
- 未来收益缺失不得在signal排名/target形成前过滤或用替补；
- public receipt existing/partial/reparse/identity drift 时所有经济读取和simulation exact0；
- 0.5x/1x/2x 必须复用相同 target object/identity；
- undefined Sharpe/Calmar/IR、未恢复回撤和 coverage不足必须显式降级；
- 旧 strategy kind 行为和输出 identity 不因新增 R5 静默漂移。

## 10. STOP 与终态

任一以下情况立即 STOP，不得由实现者猜测：

- public receipt 未合流、未验证或 public contract 仍在变动；
- future whitelist、schema、digest、cost authority 或错误 taxonomy 未在任务书逐字冻结；
- 发现只能通过复制通用文件/路径/持久化工具才能实现；
- 真实数据不足以形成 exact13 连续共同月末或比较对象无法同窗闭合；
- 需要改变 fixed-slot、窗口、阈值、方向、成本、fold、universe 或 Gate；
- 任一经济结果已被读取后才提出上述改动；
- 当前唯一 worktree、owner、branch、base 或写范围漂移。

当前终态唯一为：

`TASKBOOK_ECONOMIC_CONTRACT_PENDING / WAITING_PUBLIC_TRIAL_RECEIPT_MERGE / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`

这只证明经济假设在真实结果前得到预注册，不证明代码存在、开发验证通过、策略有效或可以交易。

## 11. 参考来源

- Tobias J. Moskowitz, Yao Hua Ooi, Lasse Heje Pedersen, “Time Series Momentum,” *Journal of Financial
  Economics* 104(2), 2012：<https://faculty.som.yale.edu/tobymoskowitz/research/>。
- Gary Antonacci, “Absolute Momentum: A Simple Rule-Based Strategy and Universal Trend-Following Overlay,”
  SSRN 2244633：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2244633>。
- Brian Hurst, Yao Hua Ooi, Lasse Heje Pedersen, “A Century of Evidence on Trend-Following Investing” ：
  <https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf>。

引用只支持假设来源与诊断设计；本地收益、风险、成本、可执行性及 disposition 必须由未来不可覆盖 trial 证明。
