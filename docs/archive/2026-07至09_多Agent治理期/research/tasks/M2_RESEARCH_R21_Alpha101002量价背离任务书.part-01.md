# M2 Research R21 Alpha101 #002 量价背离任务书

> 状态：`TASKBOOK_ONLY / STATIC_ONLY / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> task id：`M2-RESEARCH-R21-ALPHA101-002-PRICE-VOLUME-DIVERGENCE`
> exact base：`dfe49df5e8dfd9d929eb8ad196beced1da19715d`
> branch：`codex/m2-research-r21-alpha101-002-price-volume-divergence`
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r21-alpha101-002-price-volume-divergence`
> 任务性质：Alpha101公开公式的A股本地静态因子合同；不是经济回测、trial、PAPER或LIVE授权

## 1. 目标与非目标

R12增量候选地图把`alpha101_002`登记为READY8之一。本包只冻结公式、A股输入、横截面成员、时间序列窗口、
缺失值和未来评价合同。当前不实现代码，不读取真实bar、未来收益、run或trial ledger，不创建attempt，也不判断
该公开因子在A股是否仍有效。

可证伪机制是：股票成交活跃度的短期变化与同日价格结构若持续背离，可能反映参与者信息不同步、拥挤或过度
反应；原式取负相关，使更强的反向量价联动具有更高分数。若预注册方向跨fold不稳、分层不单调、成本后long
leg为负、结果只由极端成交或微盘驱动，或者信号与既有价量因子高度冗余，则拒绝或保持未评估。

本包明确不做：

- 不把公开论文或静态实现写成已验证收益；
- 不实现label、walk-forward、组合回放、publisher或public run verifier；
- 不读取data、bar snapshot、run、trial ledger、sealed holdout或历史经济结果；
- 不观察结果后改变rank、窗口、方向、volume口径或相关算法；
- 不构造市场状态切换策略；
- 不修改shared evaluator、repository、schema、receipt或`run_classic_factors.py`；
- 不授权真实策略run、PAPER、shadow、OMS、broker或LIVE。

## 2. 来源、假设与身份

来源入口固定为：

- `docs/research/references/quant_factor_research_v2/01A_Alpha101_001-050.md`的`Alpha #002`；
- Zura Kakushadze, *101 Formulaic Alphas*, arXiv `1601.00991`，作为未来primary逐式复核入口。

原始公式：

```text
(-1 * correlation(
    rank(delta(log(volume), 2)),
    rank(((close - open) / open)),
    6
))
```

本地实现身份冻结为：

- catalog：`alpha101_price_volume_divergence_eleventh_batch_v1`；
- hypothesis id：`m2-alpha101-002-price-volume-divergence-v1`；
- factor：`alpha101_002`；
- expected direction：`+1`；
- direction policy：`pre_registered_fixed_positive`；
- timing：`CLOSE_KNOWN_NEXT_OPEN`。

`+1`表示按原公式方向预注册“值越高，未来收益排序越高”。这只是待证伪方向；未来validation/test若反向，
必须降级，不得把`-1`作为同一attempt的fallback。

## 3. A股本地exact公式

### 3.1 严格交易日与基础特征

对symbol `i`和严格交易日`t`定义：

```text
volume_change_(i,t) = log(volume_(i,t)) - log(volume_(i,t-2 sessions))
intraday_return_(i,t) = (close_(i,t) - open_(i,t)) / open_(i,t)
```

规则：

- `volume`使用`Bar1dSchema.volume`的原始成交股数；当前与`t-2`必须finite且严格大于0；
- `log`为自然对数；不得改成`log1p`、成交额、换手率、标准化量、两行lag或百分比变化；
- `t-2 sessions`是严格共同交易日lag 2，需要`t-2,t-1,t`三期连续session；内部缺bar不允许跨洞；
- `intraday_return`使用同日不复权open/close。由于二者乘以同一正adj_factor后比值代数相同，该口径与同日
  multiplicative adjusted price ratio等价；不得把昨日收盘、close-to-close return或对数收益混入；
- `open`严格正值，分母不得引入epsilon；close/open及volume log/delta必须finite；
- volume为0是`Bar1dSchema`允许的局部观测，但该日及依赖它的volume feature为null，不填极小正数、不填0。

### 3.2 两个独立横截面rank

每个交易日分别对两个原始特征排名。成员集合独立：

- `U_t`：当日`volume_change` finite的证券集合；
- `R_t`：当日`intraday_return` finite的证券集合。

对任一集合和值`x`，按值升序计算average tie rank。有效成员数`n>=2`时归一化为：

`normalized_rank = (average_rank - 1) / (n - 1)`。

因此范围`[0,1]`；最小值0、最大值1、全相等时0.5。若该组件当日`n<2`，该组件所有证券rank为null。两个rank
不得先取共同intersection再排名，因为原式分别对两个表达式调用`rank`；只有后续相关计算才要求同一symbol/date
同时具备两个rank。

固定语义：

- ascending，不得改成descending；
- tie为average，不得改成dense/min/max/first/ordinal；
- 不得使用未归一1-based rank、百分位桶、winsorize、z-score或行业中性化；
- 每日成员只由当日信号输入可知性决定，不得按未来收益、未来可交易性或最终Top-K过滤；
- 输入行顺序、symbol字典序和并列行顺序不得改变rank。

### 3.3 六期Pearson相关与因子输出

令`u_(i,t)`和`r_(i,t)`分别为上述两个normalized rank。对当前及此前5个连续交易日形成exact 6 pairs：

`P_(i,t)=((u_(i,t-5),r_(i,t-5)),...,(u_(i,t),r_(i,t)))`。

六对必须全部finite。定义：

```text
u_bar = mean(u_1,...,u_6)
r_bar = mean(r_1,...,r_6)
numerator = sum((u_j-u_bar)*(r_j-r_bar), j=1..6)
denominator = sqrt(sum((u_j-u_bar)^2) * sum((r_j-r_bar)^2))
corr6 = numerator / denominator
alpha101_002 = -corr6
```

规则：

- 任一组件六期零方差、denominator为0、pair缺失或运算非finite时输出null；不得填0或epsilon；
- 数学输出范围`[-1,1]`；实现不得用clip隐藏明显越界或错误计算；
- `alpha101_002`为相关系数取负，禁止改成协方差、Spearman、rolling regression、相关绝对值或无负号；
- volume lag2首个特征位于第3个session，随后需要连续6个pair，所以首个因子值位于exact第8个session；
- 仅7个sessions无因子值；第9个session不改变第8个session的首值位置；
- 任一内部session/bar缺失使覆盖它的特征/六期窗口为null，不得拼接最近6个可用pair。

## 4. 数据、时间与输出合同

输入必须先通过现有`Bar1dSchema`并满足：

- exact Polars `DataFrame`且非空；
- `(symbol, trade_date)`唯一；
- `sessions`为非空、严格升序、无重复的`tuple[date,...]`；
- 每个bar日期都属于sessions；
- open、close、volume、adj_factor拒bool、NaN和正负Inf；
- open/close/adj_factor严格正值；volume允许schema级0但相关局部特征为null；
- 所有log、delta、return、rank、mean、平方、乘积、平方根和相关输出finite。

实现必须先形成symbol×sessions语义。合法局部缺失只产生局部null；schema、类型、唯一键、calendar或非有限源值
非法则拒绝整次计算。不得前后填充、用上一可用交易日、填0、缩短窗口或丢弃不利观测。

信号在`t`日收盘后形成，最早`t+1`共同可交易session open执行。涨跌停、停牌、T+1、整手和Top-K不足属于
未来组合层门禁，不能反向污染当日rank。输出只保留原bars已有unique keys，不补额外grid行；canonical排序为
`symbol, trade_date`。

输出exact ordered columns/dtypes：

1. `symbol = pl.String`；
2. `trade_date = pl.Date`；
3. `alpha101_002 = pl.Float64`。

因子列允许null，禁止NaN/Inf；`+0.0/-0.0`统一为`0.0`。

## 5. 共享rank边界与实现准入

以下原调用图分支保留为历史。第12节已冻结合流后的唯一公共API，未来实现必须遵循第12节；
“第二个以内可私有实现”和“第三消费者需等待新helper”的旧备选均不再可选。

本任务需要每日横截面ascending average-tie normalized rank。项目相邻R14/R15静态候选已经出现相似研究语义，
因此本任务书不能自动批准第三套私有rank实现，也不能cross-import相邻`run_*`或模块私有helper。

未来派实现Worker前，经理和统筹必须基于届时latest integration重做调用图：

- 若R21仍是第二个以内的独立消费者，且无需公共接口，可在本模块用最小private pure helper实现并由本模块测试；
- 若合流后的生产树已存在两个消费者，使R21成为第三个消费者，或另有模块需要共同复用，则本任务立即
  `CONTRACT_STOP / SHARED_RANK_BOUNDARY_REQUIRED`；由统筹把中立rank helper作为独立、窄research工具包冻结；
- 不得从未合流worktree复制helper，不得把R14/R15私有函数当公共API，不得在R21顺手新增shared module；
- 中立helper若形成跨域通用基础设施，再转框架领域；投研侧不得自行扩大。

该边界不改变本任务的经济公式，只决定实现所有权。taskbook完成不等于静态实现已准入。

## 6. 静态配置候选

若第12节迁移与静态准入通过，配置候选为`configs/research/m2_classic_daily_factors_eleventh_batch.toml`，至少包含：

```toml
[research]
hypothesis_id = "m2-alpha101-002-price-volume-divergence-v1"
strategy_name = "classic_alpha101_002_price_volume_divergence_top50"
strategy_version = "v1"

[factors]
catalog = "alpha101_price_volume_divergence_eleventh_batch_v1"
names = ["alpha101_002"]
horizons = [1, 5, 20]

[alpha101_eleventh_batch]
schema_version = "m2-alpha101-eleventh-batch-v1"
hypothesis_id = "m2-alpha101-002-price-volume-divergence-v1"
factors = ["alpha101_002"]
volume_basis = "raw_shares"
volume_transform = "natural_log_delta_2_sessions"
intraday_return = "raw_close_minus_open_divided_by_open"
cross_section_rank = "average_normalized_zero_one_ascending_component_specific"
correlation = "pearson_exact_6_contiguous_pairs"
required_contiguous_sessions = 8
expected_direction = 1
direction_policy = "pre_registered_fixed_positive"
attempt_ordinal = 1
trial_budget = 1
trial_delta = 0
economic_execution = "BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK"
```

universe、snapshot、fold、成本、admission和portfolio只可采用现有classic配置结构的静态候选值；不得把旧
snapshot、旧run或其他batch写成授权。`trial_delta`仅在未来public durable attempt start成功发布后变为1，运行结果
不得回写config。

## 7. 未来经济评价合同（当前不实现）

评价口径唯一服从`docs/research/投研评价指标与市场状态研究方法.md`。未来独立runner任务必须在任何label前冻结
exact config、snapshot、universe、fold、signal dates、cost、code和public receipt identity。

### 7.1 因子主证据

- primary horizon：20 sessions；h1/h5只作衰减诊断；
- 方向调整后的样本外RankIC均值、未年化RankICIR、fold方向一致性；
- h20五组收益按signal date等权后的单调性；
- long-only Top50在1x/2x成本下的净收益、换手、容量和不可成交；
- 每日两个组件各自成员数、pair coverage、零方差日期和null原因；
- 与R15 Alpha101 #011、现有价量/流动性因子的RankCorr和残差增量；
- 非微盘、Mainboard-VW、成交额分层和极端volume-change排除诊断。

fixed direction必须保持`+1`；不得用absolute IC隐藏反向。行业经验阈值不是本项目默认生产门槛，具体threshold
必须在未来run taskbook/config内于经济结果前冻结。

### 7.2 组合、风险与市场状态

因子证据通过后才报告净CAGR、累计收益、净Sharpe、Sortino、Calmar、最大回撤、回撤时长、冻结基准后的IR、
gross/one-way turnover、费用、冲击、容量、成交率和集中度。未定义值为`NOT_EVALUATED`，不能填0。

无条件结果优先。趋势×波动市场状态仅作预注册解释：分状态报告RankIC、ICIR、long leg、coverage、成本和样本数；
不得按状态选择方向、窗口、成员集合或赢家，不得把不连续状态日期拼成伪净值。任何状态门控或自动切换都是
新的假设和trial identity。

## 8. 公共receipt与经济运行硬前置

任何label、`evaluate_walk_forward`、attempt、run root、研究输出或sealed holdout读取必须等待public trial receipt
验证合流，并另立runner-integration/run任务书。未来attempt start在因子值、candidate symbols、fold和schedule闭合
后，严格在首次label/panel构造前durable no-clobber发布；receipt不存在、existing、identity drift或durability不满足
时label/evaluate均0-call。本任务禁止复制runner-local receipt。

## 9. 候选最小实现路径（当前未批准）

只有第5节调用图审计通过且统筹重新冻结后，才允许以下候选exact6：

1. 经理：`docs/research/tasks/M2_RESEARCH_R21_Alpha101002量价背离任务书.md`；
2. 实现Worker：`src/quant/factors/classic_eleventh_batch.py`；
3. 实现Worker：`tests/unit/test_classic_eleventh_batch.py`；
4. 实现Worker：`configs/research/m2_classic_daily_factors_eleventh_batch.toml`；
5. 实现Worker：`docs/research/deliveries/M2_RESEARCH_R21_Alpha101002量价背离交付报告.md`；
6. 独立reviewer：`docs/research/reviews/M2_RESEARCH_R21_Alpha101002量价背离独立初验报告.md`。

当前只批准taskbook exact1。production/test/config/delivery/review不得提前创建。`__init__`、shared runner/evaluator、
schema、repository、receipt、roadmap和其他路径只读。

## 10. 未来必测反例

1. exact8连续sessions产生首值；7期全null、9期不移动首值；
2. volume lag为交易日2而非两行或自然日；内部gap不跨洞；
3. volume正值自然log与lag2 delta exact；0为局部null，负值/非有限/非法类型fail-closed；
4. intraday return使用同日open/close，复权前后代数等价，禁止close-to-close和epsilon；
5. 两组件每日成员集合独立；共同intersection预排名版本在构造fixture上产生不同rank并被拒绝；
6. ascending average ties及`(rank-1)/(n-1)`；n=1为null、n=2边界0/1、全相等n>=2为0.5；
7. exact6 Pearson pairs，已知perfect +1/-1/0相关，factor必须取负；
8. 任一组件六期零方差、pair缺失、denominator0或非有限输出null；
9. duplicate symbol-date、session乱序/重复、bar日期越界拒绝；
10. 多symbol隔离、input row permutation与tie row permutation后canonical输出相同；
11. exact columns/order/dtypes、只返回输入keys、正负零规范化、无NaN/Inf；
12. config exact key/value/type/order、trial_delta0、economic_execution BLOCKED；
13. 反例证明不得改成Spearman/covariance/absolute correlation、delta1、五/七期窗口或反向direction；
14. 必须消费第12节已合流公共rank；在公共API identity缺失或不兼容时STOP，禁止复制或退回私有rank。

独立reviewer未来须补至少一个实现者未使用的对抗反例，重点挑战成员集合、exact8、zero variance、停牌跨洞、
相关负号和未来收益过滤。

## 11. 当前验证、资源与通过条件

当前唯一允许：

`TASKBOOK_ONLY / STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / NETWORK0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`

经理阶段通过条件：

- 仅新增本taskbook；
- actual exact1、cached0、`git diff --check` PASS；
- UTF-8 no BOM、LF-only、CR0、NUL0、TW0、single EOF LF；
- Python/data/network/economic I/O/trial均0。

taskbook完成后先由统筹基于latest integration执行第5节调用图裁定。只有裁定允许本地实现，才派唯一Worker；
若需共享边界，则转为独立任务，不得把taskbook READY写成implementation READY。

本任务当前上限：

`TASKBOOK_READY / IMPLEMENTATION_ADMISSION_PENDING_CALL_GRAPH / ECONOMIC_IO0 / TRIAL0`

## 12. 公共rank已合流后的迁移与唯一消费合同

本节由中央taskbook-only准入冻结，保留旧base与等待历史，不将静态候选升级为经济有效。
共享边界source为 `251147aaf599a7143a8ade5302294fbf1a20ec32`，已no-ff合流为
`33934c4035da907f3691f117cc18bec5c0616f1f`；拟迁移目标为当前clean main
`ab78a059044d49e2d8f3e94dd5b1087f55a9f86e`，包含该合流及R15合流。
共享组件的Windows回归已由中央报告15 passed、Ruff/mypy PASS；这不是R21验证或Linux Gate。

### 12.1 迁移操作与身份

当前R21仍为旧HEAD `dfe49df5e8dfd9d929eb8ad196beced1da19715d`，exact1 untracked任务书；
manager本轮只写本文件，不更新Git base、不创建其他文件。先独立taskbook review，PASS后由中央完成迁移：

1. fresh核唯一worktree/branch、old HEAD、cached0、exact1 untracked、无写者；记录本任务书实际bytes/SHA。
2. 证明old HEAD是目标base祖先且目标base含 `33934c4`；目标tree不得占用本untracked任务书路径。
3. 在同一branch/worktree仅以fast-forward到exact `ab78a059044d49e2d8f3e94dd5b1087f55a9f86e`，
   不rebase、不reset、不stash、不copy/move taskbook、不创建第二现场；不动shared main。
4. post核HEAD exact目标、branch不变、taskbook raw bytes/SHA不变、cached0、仍exact1 untracked；
   公共helper committed blob与第12.2节一致。迁移失败不强制覆盖，不自动选择另一base。

迁移是中央动作，本节不是manager或Worker Git写授权。目标漂移时由中央重新核身份与差异，禁止静默借latest。
taskbook自身final identity在中央grant外部绑定，不把自身SHA写回自身造成自指。

### 12.2 已合流公共API

唯一生产import为：

```python
from quant.factors.cross_sectional_rank import rank_cross_sectional_components
```

公共源码SSOT：`src/quant/factors/cross_sectional_rank.py`；目标base Git blob
`36198c19f92075ef33f8f1e7ede1b52e1e4c5205`，blob bytes=4417。
当前main Windows working presentation为4542 bytes /
`3193bb9f288a062f0f6003109aadb7b9681efbb1538891a9fbdd49e6e0cf440c`；raw presentation与Git blob分开记录，
不以CRLF差异改源码。迁移后以目标committed blob闭合公共实现，再记录实际working identity；不可用另一源码fallback。

签名为 `rank_cross_sectional_components(frame: pl.DataFrame) -> pl.DataFrame`。
输入ordered columns/dtypes为`signal_date: Date, component: String, symbol: String, value: Float64`；
exact非空DataFrame，keys非null且`(signal_date,component,symbol)`唯一，value只允许finite或null。
输出为`signal_date: Date, component: String, symbol: String, normalized_rank: Float64`，按上述三key排序，
keys/height保留；按date与component独立有效成员排名，null及有效成员不足2输出null，average ties升序归一至[0,1]。
这些只是本consumer的接口验收投影，完整错误优先级与实现仍以公共源码和其测试为SSOT；不在R21复制其算法。

### 12.3 R21适配和必测消费路径

R21仅构造已通过第3–4节校验的局部特征，将`trade_date`映射到`signal_date`，component固定为
`volume_change`与`intraday_return`。一次调用公共API处理同一long-form关系中的两个component、全部日期与证券；
不得对每行/每日另起helper调用，不在调用前取两组件有效值intersection。
两组件为每个待计算symbol/session分别保留一条key，缺失value为Float64 null；不得以value缺失删除另一组件成员。
公共helper只排名，不计算log、lag、Pearson或未来收益。返回后按key恢复两条rank序列，再按原exact6连续pairs求负相关，
最后仅输出原bars keys；函数输入、首值exact8、方向+1、零方差/null及经济禁止合同全部不变。

R21测试中用真实公共helper的薄spy证明调用exact1、输入ordered schema/key/value与两个component分母独立，
并与无spy的真实公共调用做同结果验证；不得以fake rank输出或源码字符串检查替代消费路径。
必须复用第10节n=1/n=2/ties/null/row-order与不等成员集合反例，证明公共helper null不能被填0、rank不能重算或clip。
公共helper抛错直接fail-closed，不fallback私有函数；禁止修改helper、其私有成员、相邻batch或`__init__`。
共享框架测试只读参考为`tests/unit/test_cross_sectional_rank.py`及
`tests/integration/test_shared_cross_sectional_rank_consumers.py`；R21自身测试写在既定test文件。

### 12.4 exact6及接续边界

第9节exact6路径保持不变。当前只有taskbook存在；production/test/config/delivery/review在实现准入前须absent，
不存在的文件不得猜测bytes/SHA。新文件身份在实际交付后fresh冻结；taskbook/review由各自owner写入，不由实现者代写。
独立taskbook审查在当前仅taskbook阶段以零写transcript回传，不提前创建review文件；不运行Python或真实数据。
迁移验证通过后中央另授唯一实现者静态exact4（production/test/config/delivery）；taskbook及共享源码全部只读。
实现后独立reviewer仅写第9节review，再由中央按UA-GOV-001安排定向Windows开发验证，不自动启动经济trial。

本节替代第5、6、9、10.14及第11节关于本地/private helper选择或继续等待shared boundary的旧准入文字，
但不改变公式、配置候选值、成本/PIT/时点、公共receipt前置或任何业务授权。
当前上限为`TASKBOOK_REFROZEN / PENDING_MIGRATION_REVIEW / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`；
经理阶段CPU_NONE/PYTHON0/DATA0/NETWORK0/ROOT_CREATE0/STAGE0/COMMIT0。

## 13. 迁移与静态复验完成后的Windows验证

中央已按§12将同一worktree fast-forward到`ab78a059044d49e2d8f3e94dd5b1087f55a9f86e`。
实现、返工与同一独立review历史保留在既有delivery/review；最终STATIC_REVIEW_PASS/P0=P1=P2=0，
review为15918 bytes / `b05ba94d9663cd39dfb92019909010e5ea7bcda17e9466366439d3f55fc1ff2b`。
这替代旧段落的CURRENTLY implementation0状态，不改历史；当前为IMPLEMENTED_PENDING_VALIDATION/TRIAL0。
本节经理仅改taskbook，独立零写执行合同review后中央另授资源；FWD优先，R21不得与其共享0xF00租约。

### 13.1 exact输入与无冲突输出

W为唯一absolute worktree：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r21-alpha101-002-price-volume-divergence`。
branch=`codex/m2-research-r21-alpha101-002-price-volume-divergence`，HEAD必须为上述ab78a059完整值。
验证前后exact6均只读，actual exact6 untracked、cached0。除taskbook最终identity由中央grant外部绑定，其余为：

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| src/quant/factors/classic_eleventh_batch.py | 8452 | 6fe8baf1000cb8ffd5b8e58968125f3e6c4069d2e5e76af25940709351f8a4a1 |
| tests/unit/test_classic_eleventh_batch.py | 15826 | 17f22016d9268058104276ae1c0d778916c38ee2b77115d70df603ff7f84f6be |
| configs/research/m2_classic_daily_factors_eleventh_batch.toml | 2774 | 0ca63e41fa77bb36c72eaedc2b1c713169bdf9c02add6e2387aec749b574cc5b |
| docs/research/deliveries/M2_RESEARCH_R21_Alpha101002量价背离交付报告.md | 3343 | 58cb657cdfdb1fa6ad3f3d1e1c97087170a15a7ae8ccdab3ff741d33eb1f4b17 |
| docs/research/reviews/M2_RESEARCH_R21_Alpha101002量价背离独立初验报告.md | 15918 | b05ba94d9663cd39dfb92019909010e5ea7bcda17e9466366439d3f55fc1ff2b |

Python=`D:\Miniforge3\python.exe`，93184 bytes/SHA256
`478ca44a015899fd0ff5aeaca9d407496f5c18ec454a6ec1fd36cf6d18c9a49f`，fresh匹配才运行。
公共helper继续绑定§12.2 Git blob，实际working bytes另作pre/post一致性核验，不修改CRLF呈现。

E为唯一新no-clobber evidence root：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r21-alpha101-002-price-volume-divergence\artifacts\agent_runs\m2-r21-alpha101-002-windows-validation1`。
T为唯一新no-clobber temp root：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r21-alpha101-002-price-volume-divergence\artifacts\validation_tmp\m2-r21-alpha101-002-windows-validation1`。
W/E/T仅为文档简写；执行时完全展开literal absolute路径，不从环境推断。E/T pre必须absent+ignored。
各ancestor及创建后的root必须real directory/non-reparse，文件ordinary/non-reparse；身份不可读或漂移STOP。
两个parent须先经下述唯一初始化处理；执行者不得把运行时发现的未知child自动登记为合法baseline。
中央只读裁定前的任务书review为REVIEW_FAIL/P0=0/P1=1/P2=0，问题仅是未冻结literal parent sets。
保留曾误报artifacts empty的历史并明确撤回：权威pre-set为exact `{.gitkeep}`，不是empty。
W\artifacts必须为real directory；分别核Directory位为true、ReparsePoint位为false及LinkType为空，
不得仅凭聚合Attributes数值判定。所有ancestors亦须非跟随核验。
`.gitkeep`须ordinary file/non-reparse，初始化前后bytes/SHA不变；agent_runs与validation_tmp均fresh absent。
当前.gitkeep冻结为2 bytes/SHA256 `7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6`。
初始化仅由中央在此合同独立复验及准入后按序创建W\artifacts\agent_runs、W\artifacts\validation_tmp，
不创建E/T，不补其他parent；创建前再次核absent，发现竞争或existing项即STOP，不把existing当本次创建成功。
初始化post artifacts集合exact `{.gitkeep, agent_runs, validation_tmp}`，两个新parent均ordinary empty directory。
正式验证的parent pre direct-child集合逐字为：agent_runs=`[]`，validation_tmp=`[]`；
正式验证post逐字分别为：agent_runs=`[m2-r21-alpha101-002-windows-validation1]`，
validation_tmp=`[m2-r21-alpha101-002-windows-validation1]`，两child均real directory/non-reparse。
除这两个指定新parent外，缺失任何ancestor均STOP；任一extra entry、race、reparse或.gitkeep身份漂移均STOP。
初始化中途失败保留已创建的partial状态，不删除/重试/补造完成；不得继续Python。
经理本轮不创建目录。E/T创建前仍须完成HEAD/scope/输入/Python/无重叠资源的fresh门禁。

### 13.2 唯一产品顺序与环境

中央为唯一执行者，cwd=W；不创建carrier文件，不读取或复用FWD carrier、残留或证据。
原生命令通过argv array执行，每项exact一次，首个非0停止后续；不另跑full suite或重试失败节点：

1. Python argv：`-m pytest W\tests\unit\test_classic_eleventh_batch.py -q --rootdir=W -c W\pyproject.toml -p no:cacheprovider --basetemp=T\pytest`
2. Python argv：`-m ruff check --no-cache --config W\pyproject.toml W\src\quant\factors\classic_eleventh_batch.py W\tests\unit\test_classic_eleventh_batch.py`
3. Python argv：`-m mypy --config-file W\pyproject.toml --cache-dir=T\mypy W\src\quant\factors\classic_eleventh_batch.py`

第1项为完整唯一unit文件；fresh Python collection import生产模块，
`test_config_exact_identity_contract`覆盖静态TOML全值/类型。以这两个可定位行为承担本次cold/config闭包，
不新增第四次重复import/测试；若收集失败或该节点未运行，不能声明cold/config PASS。
仅内存fixture生成因子值，不读项目data或真实returns，不调用研究runner/receipt/publisher。

child-only：PYTHONPATH=W\src；PYTHONUTF8=1；PYTHONIOENCODING=utf-8；PYTHONDONTWRITEBYTECODE=1；
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1；移除PYTEST_ADDOPTS/PYTEST_PLUGINS/PYTHONHOME；TEMP/TMP=T。
OMP_NUM_THREADS/MKL_NUM_THREADS/OPENBLAS_NUM_THREADS/NUMEXPR_NUM_THREADS/VECLIB_MAXIMUM_THREADS/
BLIS_NUM_THREADS/POLARS_MAX_THREADS/RAYON_NUM_THREADS均为2，不构造conda环境身份。
保存owner真实priority/affinity及实际改动的host环境，设置BelowNormal/0xF00并readback后启动child，串行且线程<=2。
finally恢复owner原值；记录每个known child PID/start/exit与Python/pythonw presence、restoration errors。
无法读取旁观进程不等于0，也不得使known-child/resource artifact丢失；以授权owner/child闭合租约释放。
原生日志不漏掉工具返回值；内存控制文本可以经独立零写审查并用UTF-8 bytes/SHA绑定后执行，不要求新脚本文件。

### 13.3 证据与保留Temp终态

