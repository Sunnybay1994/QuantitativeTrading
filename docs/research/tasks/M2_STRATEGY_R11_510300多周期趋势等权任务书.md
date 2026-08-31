# M2-STRATEGY-R11：510300 多周期趋势等权任务书

> - task id：`M2-STRATEGY-R11-510300-MULTI-HORIZON-TREND`
> - 领域：research
> - 当前阶段：`TASKBOOK_ONLY / STATIC_ONLY / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> - base/head：`6efbd6f12229b8577b1504e800acc63f319f8a5b`
> - branch：`codex/m2-strategy-r11-510300-multi-horizon-trend`
> - worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-strategy-r11-510300-multi-horizon-trend`
> - 当前唯一写路径：`docs/research/tasks/M2_STRATEGY_R11_510300多周期趋势等权任务书.md`
> - 任务性质：真实经济结果读取前的策略合同预注册；不是实现、验证、回测、PAPER 或 LIVE 授权

## 1. 目标与结论上限

本任务冻结一个低自由度、单资产、long/cash、无杠杆的多周期趋势组合：对 `510300.SH` 分别计算过去
1、3、12 个完整共同自然月的总回报；每个期限拥有固定 `1/3` 风险袖套，回报严格大于零时该袖套持有 ETF，
否则持有现金。三个袖套先聚合为唯一券商层目标权重，再沿项目统一月频 ETF 执行和成本边界回放。

本任务回答的唯一 primary 问题是：相对同窗 `510300.SH` buy-and-hold，固定 `1/3/12M` 多周期趋势等权规则
能否在成本后提高风险调整收益、控制回撤，并在加倍成本压力下保持正收益。它不回答哪个窗口“最优”，也不在
三个窗口之间动态分配风险。

策略身份固定为：

- `hypothesis_id="m2-510300-multi-horizon-trend-equal-v1"`；
- `strategy_kind="etf_single_asset_multi_horizon_trend"`；
- `strategy_version="1.0.0"`；
- `trial_identity="m2-510300-multi-horizon-trend-equal-v1"`；
- `attempt_ordinal=1`；
- `trial_delta=1`，仅在未来 public durable attempt start 成功发布后计入；当前 exact `0`。

该身份标记为 `LOCAL_LONG_ONLY_SINGLE_ETF_MULTI_HORIZON_TREND_ADAPTATION_TRIAL`。公开趋势研究只支持形成
可检验假设，不证明本地 ETF、当前数据、成本或执行边界下仍然有效。

未来真实运行的最高自动结论仅为 `RESEARCH_ONLY`；任一 admission Gate 失败只允许降为 `REJECTED`。即使
`RESEARCH_ONLY`，仍不自动产生 `PAPER_CANDIDATE`，更不授权 PAPER、shadow、LIVE 或自动下单。

## 2. 非目标

本任务明确不做：

- 搜索或比较 1—12 月任意窗口、阈值、方向、期限数量或袖套权重；
- 依据 validation/test 结果删除 1M、3M 或 12M 中任一袖套；
- 把未激活袖套的 `1/3` 预算重新分配给其他袖套；
- 使用 `1/n_active`、杠杆、做空、波动率缩放、均值方差、风险平价或机器学习；
- 把 Faber、R5、R6、REGIME、波动率目标或其他策略结果并入本 trial，或观察后选择赢家；
- 用市场状态切片改变仓位、窗口或 admission；
- 把横截面 IC/RankIC 强加给单资产时间序列策略；
- 读取 immutable research run、forward、PAPER、broker、OMS 或账户数据；
- 在公共 receipt 与 Faber 共享月末/next-open/runner 边界合流前实现第二套 schedule、simulator、metrics 或 receipt；
- 修改 shared roadmap、共享进展报告或其他 worktree 中的文件。

## 3. 研究依据与本地适配边界

1. Moskowitz、Ooi、Pedersen 的 time-series momentum 研究支持“资产自身过去收益方向可能预测后续收益”的
   可检验假设，但原研究覆盖期货、long/short 与风险缩放；本任务不复制这些交易工具或杠杆设计。
2. Hurst、Ooi、Pedersen 的长期趋势证据支持跨期限与跨状态审视趋势效应；本任务只预注册三个固定期限，
   不把论文的跨资产结果当作本地有效性证据。
3. 多期限等权的目的，是在真实结果前固定不同趋势速度的风险预算，降低单一窗口偶然性；它不是根据历史
   Sharpe 选择窗口，也不声明三个期限彼此独立。

任何公开论文、静态代码或其他市场回测都不能替代本地不可覆盖 trial、真实成本、可交易时点和前向观察。

## 4. exact 经济合同

### 4.1 证券、价格与现金

- symbol exact：`510300.SH`；
- security role：唯一风险资产；不得替换为指数、其他沪深300 ETF 或复权指数序列；
- research price semantic：`TOTAL_RETURN_DIVIDEND`；
- signal timing：完整共同月末 close 后；
- execution timing：下一共同开市日 open；
- valuation timing：close；
- cash target：未激活袖套留在现金；
- cash return：当前研究假设 exact `0`，必须进入配置、报告 caveat 和 trial identity；不得结果后替换为货基、
  逆回购或无风险利率。

`510300.SH` 的 tracked connector fixture 记录上市日期候选为 `2012-05-28`，这只用于样本功效设计，不证明
当前权威 bars、calendar 或 `TOTAL_RETURN_DIVIDEND` 从该日开始完整可用。未来 terminal input inventory 必须
逐字证明实际起止日、完整月末覆盖、正有限价格和执行 open；不足时 STOP，不得用旧数据、上一交易日或其他
证券补齐。

### 4.2 共同月末与执行日

canonical signal month 必须满足：

1. 该自然月已经完整结束；
2. SH 与 SZ 权威交易日历均已闭合；
3. signal date 是该自然月 SH、SZ 同时开市日期集合中的最后一天；
4. `510300.SH` 在 signal date 有可验证的 `TOTAL_RETURN_DIVIDEND` close；
5. execution date 是 signal date 之后第一天 SH、SZ 同时开市且标的存在合法 open 的交易日。

禁止使用 bars union、单市场月末、自然月最后日、月内最后一条偶然价格、当前未完成月份、上一交易日或后来
修订冒充上述身份。calendar/price 缺失、重复、乱序、日期漂移、无下一共同执行日或 signal/execution 同日均
fail-closed。

尾部数据截止处尚未完成的自然月完全排除；不能用“截至当前的月内最后共同开市日”生成新 signal。未来任务书
必须基于 terminal snapshot 冻结 exact signal-date/execution-date tuple 及 digest，不能由 Worker 运行时猜测。

### 4.3 三个固定趋势信号

对 signal month `t` 和 horizon `h in (1,3,12)`：

```text
total_return_h(t) = close(t) / close(t-h) - 1
signal_h(t) = 1 if total_return_h(t) > 0 else 0
```

唯一观察合同：

- 1M 必须具有 exact2 个连续自然月共同月末 close：`t-1..t`；
- 3M 必须具有 exact4 个连续自然月共同月末 close：`t-3..t`；
- 12M 必须具有 exact13 个连续自然月共同月末 close：`t-12..t`；
- 端点与所有中间月份均不得缺失；价格必须是同一 symbol 的正有限数值；
- 回报严格 `>0` 才为 risk-on；exact zero 与负值均为 cash；
- 任一期限缺月、重复月、乱序、错误 symbol/date、null、bool、NaN、Inf、零或负价格时，该 signal date 整体
  fail-closed；不得只删除出错袖套、填零、前向填充、改用日频近似或回退到更短窗口。

三期限、三个方向、阈值和权重都是 primary trial identity。`validation_grid` 必须 exact 空集合；不存在
`selected_horizon`。

### 4.4 固定袖套与聚合目标

三个袖套身份和顺序固定为：

```text
slot=1, horizon_months=1,  budget=1/3
slot=2, horizon_months=3,  budget=1/3
slot=3, horizon_months=12, budget=1/3
```

每个 signal date：

```text
target_weight_510300 = (signal_1m + signal_3m + signal_12m) / 3
cash_weight = 1 - target_weight_510300
```

所以唯一合法风险资产目标集合为 exact `{0, 1/3, 2/3, 1}`。规则必须满足：

- 每个 sleeve 永久拥有固定 `1/3`，未激活预算留现金；
- 禁止 `1/n_active`、把空出的预算重分配给其他期限或提高总杠杆；
- 三个 sleeve signal 先闭合，再聚合为唯一券商层 `510300.SH` 目标；
- 交易、换手、滑点和佣金只对聚合目标的实际变化计费；
- 若两个 sleeve 在同日一开一关而聚合目标不变，不得制造虚构的内部买卖和费用；
- 但 report 必须保留三个 sleeve 的信号、固定贡献和状态切换诊断，不能只保留净目标而丢失可解释性；
- 不得基于未来 open、未来收益或 outcome availability 决定 sleeve 或 target。

未来 canonical decimal text、runtime float equality、target schema 和 digest 必须在 public receipt/Faber 边界合流后
重冻；当前不得由实现者自选 `0.3333` 近似或不同舍入规则。

## 5. 样本、walk-forward 与功效边界

### 5.1 当前设计窗口

设计上的历史下界候选为 `2012-05-28`，上界候选为现有 ETF 研究输入截至 `2026-07-10`。这两个日期不是
当前数据 readiness 结论。未来真实运行前必须由冻结 snapshot 验证：

- 从下界到上界的 SH/SZ calendar、close/open 与 `TOTAL_RETURN_DIVIDEND` 覆盖；
- 第一个经济 signal 只能出现在形成 exact13 个连续完整共同月末之后；
- 最后一个 signal 必须属于已经完整结束、且存在下一共同 open 和完整持有期的月份；
- terminal incomplete month/holding period 必须按权威 shared runner 合同排除，不得临时缩短持有期。

按上市日到当前上界粗略估算，月频观察约为 159 个；该数字只说明为什么选择低自由度固定规则，不是实际
coverage、统计功效或策略有效性的证据。未来 report 必须以 terminal exact observation count 替代估算。

### 5.2 预注册 expanding walk-forward

在 terminal 月末 grid 与完整成本有效期闭合后，计划使用下列 exact3 anchored folds；若任一边界无法由完整
共同月末和 next-open 映射实现，必须在任何经济读取前回中央重冻 trial identity，而不是运行后挪动日期：

```json
[
  {
    "fold":1,
    "train_start":"2012-05-28",
    "train_end":"2017-12-31",
    "validation_start":"2018-01-01",
    "validation_end":"2018-12-31",
    "test_start":"2019-01-01",
    "test_end":"2020-12-31"
  },
  {
    "fold":2,
    "train_start":"2012-05-28",
    "train_end":"2019-12-31",
    "validation_start":"2020-01-01",
    "validation_end":"2020-12-31",
    "test_start":"2021-01-01",
    "test_end":"2022-12-31"
  },
  {
    "fold":3,
    "train_start":"2012-05-28",
    "train_end":"2021-12-31",
    "validation_start":"2022-01-01",
    "validation_end":"2022-12-31",
    "test_start":"2023-01-01",
    "test_end":"2026-06-30"
  }
]
```

训练段仅提供12M预热，不拟合参数；validation 只验证固定规则的实现与报告稳定性，不选择期限、阈值、权重
或 Gate。三个 test 段互不重叠。较早 test 年份后来可进入下一 fold 的已知 train/validation 历史，但不得回写
此前 disposition。任何 fold/date 或 terminal boundary 漂移都属于新 identity。

## 6. 比较对象与 Faber 诊断

### 6.1 primary comparator

唯一 primary comparator 是同一 `510300.SH`、同一 signal/execution dates、同一价格、同一账户、同一成本与
估值边界的 buy-and-hold。它从每个 test fold 的首个可执行 open 建仓并持有至同一 terminal exit；不得使用
指数价格、免成本或不同起点。

### 6.2 Faber 仅作预注册诊断

Faber 十月均线策略与 R11 保持独立 hypothesis、attempt、receipt、run 和 disposition。只有 Faber authoritative
common-month-end、next-common-open schedule、共享 `run_s1_walk_forward` 边界及 public receipt 已合流后，R11
才可基于 latest main 重审实现调用图。

未来 R11 report 可在同一 `510300.SH` signal grid 上诊断：

- R11 聚合 target 与 Faber 对 `510300.SH` 的目标重合率；
- risk-on/risk-off 分歧月份、连续 episode 与后续贡献；
- R11 相对 Faber 的增量换手、成本、收益、回撤和尾部损失；
- 1M/3M/12M sleeve 分别对分歧的贡献。

Faber 结果不得进入 R11 admission，不得在 R11 失败时替代 primary，也不得合并两个 trial 的收益、Gate 或
trial ledger。Faber run 缺失时该诊断为 `NOT_EVALUATED`，R11 primary 不得伪造替代实现。

## 7. 成本与可执行性前置

R11 计划覆盖 2012—2026，因此不能把仅从 `2023-01-01` 生效的单段 ETF 研究成本静默外推到更早年份。
未来真实 trial 前必须绑定覆盖整个实际 test window 的版本化 ETF cost schedule，并冻结：

- 每段 effective date、commission、minimum commission、slippage、ETF税费与单位；
- 成本应用顺序、聚合 target 计费语义和 semantic digest；
- pressure multipliers exact `0.5, 1, 2`；
- 每个 fold/test date 都被 exact1 成本段覆盖，段间无 gap、overlap 或 fallback；
- 交易单位、现金不足、停牌、涨跌停、缺 open、T+1、目标未成交和 terminal liquidation 的处理。

如果项目尚无可信的 2012—2022 ETF 成本 authority，本任务保持 `UNASSESSED/STOP`；不得把 2023 参数向前
复制、把早期年份删掉、仅从2023运行后仍声称完成本 trial，或在看到结果后选择样本。未来若中央决定缩短样本，
必须在任何收益读取前建立新 taskbook/trial identity，并重新评估约159个月的功效依据。

实际券商账单尚未校准；开发回测即使通过也不自动授权 PAPER。

## 8. 指标体系与 admission

指标口径唯一服从 `docs/research/投研评价指标与市场状态研究方法.md`。R11 是单资产时间序列策略，不要求
横截面 IC、RankIC、ICIR 或分组收益。

### 8.1 主报告闭包

每 fold、pooled、0.5x/1x/2x 至少报告：

- 成本后累计收益、CAGR、年化收益和年化波动率；
- 成本后 Sharpe，并披露现金收益、频率、年化因子、样本数、分子和分母；
- Sortino、Calmar、最大回撤、回撤开始/谷底/恢复日、持续时间和未恢复状态；
- 相对 buy-and-hold 的 active return、tracking error、Information Ratio 与 beta；
- gross/one-way turnover、成交费用、滑点、target gap、成本压力和 terminal cost；
- 三 sleeve signal、风险资产目标、cash weight、切换次数、持有期与贡献；
- coverage、完整月数、缺失分类、最差月/持有期和尾部损失；
- Faber 诊断的状态、重合率和增量指标，或明确 `NOT_EVALUATED`。

任何 undefined、样本不足、零方差或 nonfinite 指标必须带显式状态，不得填零、极大数或静默删期。Sharpe、
Sortino、Calmar 与 IR 不得混用公式。

### 8.2 primary admission Gates

在任何 test/holdout 结果读取前冻结以下 exact8 布尔条件；全部通过时仍只保持 `RESEARCH_ONLY`：

1. 每个 test fold 的 strategy 1x 成本后累计收益均严格 `>0`；
2. pooled strategy 1x 成本后累计收益严格 `>0`；
3. pooled strategy 1x Sharpe finite、状态 PASS 且严格高于 buy-and-hold；
4. pooled strategy 1x Calmar finite、状态 PASS 且严格高于 buy-and-hold；
5. pooled strategy 1x 最大回撤绝对值不大于 buy-and-hold；
6. pooled strategy 2x 成本后累计收益严格 `>0`；
7. exact2/4/13月、固定 sleeve、聚合 target、calendar/next-open、cost、coverage 与 comparator identity 全部闭合；
8. public receipt、input/config/code/fold/run/report schema、no-clobber publication 和 fresh verification 全部闭合。

Gate 不做多数表决。任一失败只允许 `RESEARCH_ONLY -> REJECTED`。Faber、状态切片、单一袖套、单个年份、
低成本档或其他优异指标不能救援 Gate；阈值不得在看到结果后放宽。

### 8.3 市场状态诊断

趋势×波动率状态只按长期方法文档既有低自由度定义报告：

- 状态必须在 signal `as_of` 时已知；
- 无条件 primary 结果优先；状态只解释贡献、失效、换手和尾部风险；
- 不连续状态日期不得拼成虚构净值计算 MDD/Calmar；
- 状态不改变 target、sleeve、Gate 或 disposition；
- 任何状态门控、切换或风险预算属于新 hypothesis/trial；
- coverage不足写 `INSUFFICIENT`，不得搜索状态阈值或只汇报最好切片。

## 9. public receipt、共享 runner 与实现前置

当前 public durable trial receipt 和 Faber authoritative schedule/runner 尚未形成可供本 worktree 消费的 merged
contract。因此 implementation whitelist 为 **exact 空集合**；当前不得创建 config、production、tests、delivery
或 review。

只有以下前置全部满足后，经理才能从 latest clean main 重冻实现任务书：

1. public receipt 已合流并通过其冻结的 Windows development validation；Linux durability Gate 是否完成必须
   单独诚实记录，不能由 Windows 结果冒充；
2. Faber authoritative complete-common-month-end、next-common-open schedule、统一 simulator、metrics 和共享
   `run_s1_walk_forward` 边界已合流；
3. public receipt 与共享 runner 的 public import/API/schema/error taxonomy 已稳定；
4. 本任务的完整历史 cost schedule 和 `510300.SH` terminal input inventory 已可冻结；
5. 统筹基于 latest main 分配新的 exact base/worktree、唯一 Worker 与互斥写白名单。

重冻时必须逐字确定：

- exact production/config/unit/integration/delivery/review paths；
- public receipt start/terminal types、字段顺序、错误码、path和平台能力；
- start 早于第一次 test/holdout、future-return、label、simulation 或经济 comparator 读取；
- existing/partial/reparse/collision/identity drift 时全部经济调用 exact0；
- schedule、sleeve、aggregate target、fold、cost、input、metric、Gate、report和run digests；
- ordered schemas/dtypes、canonical decimal、outputs exact set、report fields 与 final conclusion；
- focused Windows validation、Linux Gate 和唯一真实 trial 的独立授权边界。

禁止复制 Faber、REGIME、R3/R4/R5/R6 的私有 receipt 或 runner-local filesystem helper，禁止形成第二套
month-end helper、simulator、metrics 或 publication verifier。若实现需要新的通用模块、第三个消费者或跨域
基础设施，research 包立即 STOP，由统筹转交 framework 领域重冻。

## 10. 未来测试与验收矩阵

依赖满足后的实现任务书至少逐名覆盖：

- exact2/4/13月边界：缺中间月、重复月、尾部未完成月、单市场月末、future month、错误 symbol；
- total return strict zero：正 epsilon 为1，zero/负 epsilon 为0；
- 三 sleeve 的8种 signal mask 均映射到 exact `{0,1/3,2/3,1}`；
- 一开一关但净目标不变时实际 turnover/cost为0，同时 sleeve diagnostics仍保留；
- 禁止 `1/n_active`、预算重分配、日频近似、未来 outcome 预过滤和替补；
- calendar→next-open、持有期、terminal exit 和 comparator date逐字一致；
- 2012—2026每个实际 test date的成本段 exact1覆盖，gap/overlap/向前外推均STOP；
- fold、signal dates、cost、cash return、price semantic、candidate、Gate或Faber identity任一漂移；
- public receipt existing/partial/reparse/alias/collision/drift时所有 holdout/simulation/comparator exact0；
- 0.5x/1x/2x复用相同 target identity，仅成本倍率变化；
- undefined Sharpe/Calmar/IR、合法全现金、未恢复回撤与coverage不足的显式状态；
- Faber 缺失只使诊断 `NOT_EVALUATED`，不得影响或救援 primary admission；
- 旧 strategy kind、Faber、R5/R6和shared runner输出身份不因新增R11静默漂移。

实现者自测、独立审查、Windows feedback、Linux Gate、真实 trial、PAPER 和 LIVE 必须分阶段授权；前一阶段通过
不自动授权后一阶段。

## 11. 当前角色、资源与写范围

本阶段唯一写路径：

```text
docs/research/tasks/M2_STRATEGY_R11_510300多周期趋势等权任务书.md
```

当前明确只读且不得创建或修改：

- `docs/research/roadmaps/`、shared progress report；
- `docs/research/deliveries/`、`docs/research/reviews/`；
- `configs/research/`；
- `src/quant/`、`tests/`；
- research run、receipt、evidence、temp、data、ledger、账户与外部状态。

本阶段资源：`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / WORKER0 / STAGE0 / COMMIT0`。

后续实现必须由统筹分配唯一 worktree/Worker；实现与独立审查使用不同上下文。research 经理不直接实现、
验证、合流或退休来源线。

## 12. STOP、反例与当前终态

任一以下情况立即 STOP，不得由实现者猜测或缩窄成更容易通过的策略：

- public receipt 或 Faber/shared runner 未合流、未验证或 public contract仍漂移；
- 2012—2026完整成本 authority 不存在，或数据无法形成 exact13连续共同月末；
- future whitelist、schema、digest、cash/cost、fold、Gate或错误 taxonomy 未逐字冻结；
- 需要改变1/3/12M、strict zero、固定1/3、单资产、long/cash、无杠杆或buy-and-hold comparator；
- 需要按结果缩短样本、删除袖套、改变状态、成本、fold或admission；
- 任何经济结果已读取后才提出上述变化；
- 发现必须复制公共 schedule/simulator/metrics/receipt，或需要新的通用基础设施；
- 当前 worktree、branch、base、owner、exact写路径或Git身份漂移。

必须锁住的最小反例：

1. `signal=(1,0,0)` 的目标是 `1/3`，不是 `1`；
2. `signal=(1,0,1)` 的目标是 `2/3`，不是两个 active sleeve 各 `1/2` 后总计 `1`；
3. `signal=(1,0,0)` 变为 `(0,1,0)` 时聚合目标不变，真实换手和成本必须为零；
4. `close(t)==close(t-h)` 必须为 cash；
5. 缺少任一12M中间月时整个 signal date STOP，不能仅运行1M/3M；
6. 2023成本段不能向前覆盖2012—2022；
7. Faber表现优异不能让R11 Gate PASS，Faber缺失也不能伪造第二实现。

当前终态唯一为：

`TASKBOOK_PENDING_REVIEW / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`

这只证明经济合同已在真实结果前写入任务书，不证明实现存在、策略有效、开发验证通过或可以交易。

## 13. 参考来源

- Tobias J. Moskowitz, Yao Hua Ooi, Lasse Heje Pedersen, “Time Series Momentum,” *Journal of Financial
  Economics* 104(2), 2012：<https://faculty.som.yale.edu/tobymoskowitz/research/>。
- Brian Hurst, Yao Hua Ooi, Lasse Heje Pedersen, “A Century of Evidence on Trend-Following Investing” ：
  <https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf>。
- 项目指标与状态方法 SSOT：`docs/research/投研评价指标与市场状态研究方法.md`。
- Faber 共享 schedule/runner 边界候选来源：
  `docs/research/tasks/M2_STRATEGY_R2_FABER十月均线ETF趋势任务书.md`；其当前静态实现/审查结论不构成本地
  有效性或已合流证明。

引用只支持假设来源和诊断设计；本地收益、风险、成本、可执行性和 disposition 必须由未来不可覆盖 trial 证明。
