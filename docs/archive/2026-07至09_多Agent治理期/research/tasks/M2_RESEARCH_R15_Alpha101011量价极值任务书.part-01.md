# M2 Research R15 Alpha101 #011 量价极值任务书

> 状态：`TASKBOOK_ONLY / STATIC_ONLY / IMPLEMENTATION0 / ECONOMIC_IO0 / TRIAL0`
> task id：`M2-RESEARCH-R15-ALPHA101-011-VWAP-VOLUME-EXTREMES`
> exact base：`dfe49df5e8dfd9d929eb8ad196beced1da19715d`
> branch：`codex/m2-research-r15-alpha101-011-vwap-volume-extremes`
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes`

## 1. 目标与边界

R12候选地图已把`alpha101_011`登记为READY8之一。本包只冻结公式、A股本地适配、VWAP/成交量/横截面排名
语义、时间边界和静态实现合同，并以单元测试覆盖纯因子计算。不得消费未来收益、创建attempt、运行回测或判断
该因子当前仍然有效。

选择本候选只因为它把日内定价偏差极值与成交量变化相结合，机制不同于R13状态动量和R14低价排序反转，且
仅依赖现有日频bar字段。公开论文、参考文档、静态代码和历史经验都不能证明它在本地A股、long-only Top50与
真实成本下有效。

本包明确不做：

- 不接入`run_classic_factors.py`、shared evaluator、label、walk-forward或组合回放；
- 不读取bar snapshot、data、run、trial ledger、sealed holdout或任何收益结果；
- 不根据市场状态改公式、窗口、方向、VWAP定义或股票池；
- 不修改schema、repository、公共trial receipt、roadmap或共享progress report；
- 不授权PAPER、shadow、OMS、broker或LIVE。

## 2. 来源、假设与因子身份

来源入口固定为：

- `docs/research/references/quant_factor_research_v2/01A_Alpha101_001-050.md`的`Alpha #011`；
- Kakushadze, *101 Formulaic Alphas*, arXiv `1601.00991`作为未来primary-source逐式复核入口。

参考公式：

```text
((rank(ts_max((vwap - close), 3))
  + rank(ts_min((vwap - close), 3)))
 * rank(delta(volume, 3)))
```

原式未逐字冻结A股amount/volume单位、复权、tie、缺失值和停牌语义。本任务将下文口径作为项目本地可执行适配；
交付和未来报告必须同时保留原式与适配式，不得把本地选择冒充论文逐字实现。

可证伪假设：证券近期VWAP相对收盘价的正负极端位置与三日成交量变化共同刻画短期定价冲击；按原公式方向，
较高输出应对应较高未来收益排序。若预注册方向样本外不一致、分层不单调、long leg真实成本后为负，或效果只
由微盘、零成交、价格尺度、涨跌停和不可交易样本驱动，则拒绝或保持未评估，不得事后翻转方向、改变VWAP或
窗口。

实现身份冻结为：

- catalog：`alpha101_vwap_volume_extremes_ninth_batch_v1`；
- hypothesis id：`m2-alpha101-011-vwap-volume-extremes-v1`；
- factor：`alpha101_011`；
- expected direction：`+1`；
- direction policy：`pre_registered_fixed_positive`。

`+1`只是待证伪的公式方向。未来出现反向证据必须降级，不得将`-1`作为同一attempt的fallback。

## 3. A股适配后的exact公式

### 3.1 VWAP与复权价差

对symbol `i`、session `t`定义：

```text
raw_vwap_(i,t) = amount_(i,t) / volume_(i,t)
adjusted_vwap_(i,t) = raw_vwap_(i,t) * adj_factor_(i,t)
adjusted_close_(i,t) = close_(i,t) * adj_factor_(i,t)
adjusted_gap_(i,t) = adjusted_vwap_(i,t) - adjusted_close_(i,t)
                   = (raw_vwap_(i,t) - close_(i,t)) * adj_factor_(i,t)
```

`amount`单位为元、`volume`单位为股，二者必须有限且严格大于0才能形成VWAP；`close`和`adj_factor`必须有限
且严格大于0。零成交量、零成交额或任一无效operand只令该symbol/session的gap为null，不允许epsilon、填0、
上一日VWAP或横截面均值替代。

原式使用`vwap-close`。本地适配将VWAP和close用同一adj_factor复权以处理公司行动断点，但仍保留价格尺度暴露。
未来必须用价格、市值、行业和公司行动诊断证伪，不能结果后改成百分比gap、`(vwap-close)/close`或日内区间位置。

### 3.2 三日极值与三日成交量变化

在严格共同sessions上定义：

```text
gap_max_3_(i,t) = max(adjusted_gap_(i,t-2), ..., adjusted_gap_(i,t))
gap_min_3_(i,t) = min(adjusted_gap_(i,t-2), ..., adjusted_gap_(i,t))
volume_delta_3_(i,t) = volume_(i,t) - volume_(i,t-3)
```

规则：

- gap max/min需要最近三个连续sessions均存在bar且gap finite；
- volume delta lag为exact 3 sessions，因此首值需要`t-3...t`四个连续sessions的bar；
- volume delta只使用端点原始volume，不复权、不取对数、不除以历史volume；端点volume允许0但必须finite且非负；
- 中间session必须存在，防止把跨停牌的两端误当成三session delay；
- 任一缺口只使受影响组件和最终因子为null，不跨洞拼接上一可用观测。

合并后首个可评价值需要四个连续sessions，而不是三个或五个。

### 3.3 三个横截面rank与最终值

在每个trade_date，对`gap_max_3`、`gap_min_3`、`volume_delta_3`分别独立形成横截面rank：

- candidate universe须在未来运行前冻结并进入run identity；
- 每个组件只使用当日该组件finite的证券；三个组件可有不同的有效集合和分母；
- 按原值升序，tie使用average rank；
- 组件有效证券数`n >= 2`时，归一化为`(average_rank - 1) / (n - 1)`，范围`[0,1]`；
- `n < 2`时该组件当日所有rank为null，不填0或0.5；
- 不得因未来收益、后续可交易性或结果好坏动态调整当日rank成员。

记三个归一rank为`r_max`、`r_min`、`r_volume`，则：

`alpha101_011 = (r_max + r_min) * r_volume`

最终值仅在同一symbol/date的三个rank均finite时形成，范围`[0,2]`；`+0/-0`统一为Float64 `0.0`。不得改成
rank总gap、先合成再rank、共同交集统一分母、dense/min/max rank、降序rank或未归一1-based rank。

## 4. 数据、输出与时间语义

输入必须先通过现有`Bar1dSchema`，并满足：

- exact Polars `DataFrame`且非空；
- `(symbol, trade_date)`唯一；
- `sessions`是非空、严格升序、无重复的`tuple[date, ...]`；
- 每个bar日期都属于sessions；
- `close`、`volume`、`amount`、`adj_factor`不得为bool、NaN或正负Inf；
- 整体schema、唯一键、calendar或错误类型不合法时拒绝整次计算。

合法的局部零成交、缺bar或无法形成组件只产生局部null。输入行顺序不得改变结果。输出只保留原bars已有的
unique keys，不补写symbol×session网格额外行；canonical排序为`symbol, trade_date`。

输出exact ordered columns/dtypes：

1. `symbol = pl.String`；
2. `trade_date = pl.Date`；
3. `alpha101_011 = pl.Float64`。

因子列允许null，禁止NaN/Inf。信号在交易日收盘后才可知，未来最早执行固定为下一共同交易日open；不得以
当日amount、volume、close形成信号后在同日收盘前成交。

## 5. 静态接口与配置

新模块公共身份固定为：

- `NINTH_BATCH_FACTOR_SPECS`；
- `NINTH_BATCH_FACTOR_NAMES = ("alpha101_011",)`；
- `compute_ninth_batch_daily_factors(bars, *, sessions)`。

配置新增`configs/research/m2_classic_daily_factors_ninth_batch.toml`，当前禁止runner读取或执行。至少包含：

```toml
[research]
hypothesis_id = "m2-alpha101-011-vwap-volume-extremes-v1"
strategy_name = "classic_alpha101_011_vwap_volume_extremes_top50"
strategy_version = "v1"

[factors]
catalog = "alpha101_vwap_volume_extremes_ninth_batch_v1"
names = ["alpha101_011"]
horizons = [1, 5, 20]

[alpha101_ninth_batch]
schema_version = "m2-alpha101-ninth-batch-v1"
hypothesis_id = "m2-alpha101-011-vwap-volume-extremes-v1"
factors = ["alpha101_011"]
vwap_basis = "amount_cny_divided_by_volume_shares"
gap_basis = "adjusted_vwap_minus_adjusted_close"
gap_extreme_window_sessions = 3
volume_basis = "raw_volume_shares"
volume_delta_lag_sessions = 3
required_bar_sessions = 4
cross_section_rank = "componentwise_average_normalized_zero_one_ascending"
cross_section_minimum_symbols = 2
expected_direction = 1
direction_policy = "pre_registered_fixed_positive"
signal_timing = "close"
execution_timing = "next_session_open"
attempt_ordinal = 1
trial_budget = 1
trial_delta = 0
economic_execution = "BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK"
```

其余universe、snapshot、fold、成本、admission和portfolio字段采用现有classic配置静态候选结构，但不得将旧
snapshot、旧run或历史测试写成新运行授权。运行结果不得回写config。

## 6. 未来经济评价合同（当前不实现）

未来独立runner-integration任务须在任何label前重新冻结exact config、snapshot、candidate universe、fold、
signal dates、cost、code和public receipt identity。评价遵循
`docs/research/投研评价指标与市场状态研究方法.md`，不得只看单一Sharpe、IC或累计收益。

### 6.1 因子主证据

- primary horizon为20 sessions，h1/h5只作衰减诊断；
- 方向调整后的样本外RankIC均值、未年化RankICIR、IC t统计与fold方向一致性；
- h20五组收益按signal date等权后的单调性；
- long-only Top50在1x/2x真实成本下的收益、换手、不可成交与容量；
- 冗余RankCorr、coverage、主板/非微盘/Mainboard-VW和流动性分层；
- 价格尺度、市值、行业、零成交、低价股、涨跌停、复权断点及volume jump暴露；
- 三个组件rank分母、tie比例、组件缺失率和最终交集coverage。

fixed direction必须保持`+1`，不得以绝对RankIC掩盖反向。阈值须由未来taskbook/config按候选族、trial ledger和
样本逐字冻结；行业经验阈值不能自动成为本项目生产门槛。

### 6.2 组合、风险和市场状态

若因子主证据通过，组合报告才完整披露净CAGR/累计及超额收益、Sharpe、Sortino、Calmar、最大回撤及持续
时间、Information Ratio、波动/下行波动、换手、成本、容量、胜率和盈亏比。每项附样本、频率、基准和成本
口径；未定义为`NOT_EVALUATED`，不得填0。

无条件结果优先。既有REGIME合同完成开发验证并另获真实诊断授权后，才可按预注册趋势×波动状态报告RankIC、
ICIR、long leg、换手、成本和样本数。不得拼接不连续状态日期构造伪净值，也不得观察状态结果后选择方向、
窗口、组件或赢家；门控/切换规则必须新建trial identity。

## 7. 公共receipt与运行硬前置

静态因子计算不依赖公共执行载体，但以下动作必须等待框架侧public trial receipt边界合流，并另立
runner-integration/run taskbook：

- 构造未来收益label或调用`evaluate_walk_forward`；
- 创建attempt、run root或研究输出；
- 读取bar snapshot、run、trial ledger或sealed holdout；
- 作出有效、无效、promotion、PAPER或LIVE结论。

未来attempt start须在因子值、candidate symbols、fold和signal schedule闭合后，严格在首次label/panel构造前
durable no-clobber发布。receipt缺失、existing、identity drift或平台durability不足时label/evaluate均0-call。

## 8. 文件所有权与最小实现包

最终静态实现exact 6路径：

1. 经理唯一写：`docs/research/tasks/M2_RESEARCH_R15_Alpha101011量价极值任务书.md`；
2. 实现Worker唯一写：`src/quant/factors/classic_ninth_batch.py`；
3. 实现Worker唯一写：`tests/unit/test_classic_ninth_batch.py`；
4. 实现Worker唯一写：`configs/research/m2_classic_daily_factors_ninth_batch.toml`；
5. 实现Worker唯一写：`docs/research/deliveries/M2_RESEARCH_R15_Alpha101011量价极值交付报告.md`；
6. 不同独立reviewer唯一写：`docs/research/reviews/M2_RESEARCH_R15_Alpha101011量价极值独立初验报告.md`。

`run_classic_factors.py`、shared evaluator、`quant.factors.__init__`、schema、repository、roadmap、共享progress report
及其他路径全部只读。若必须扩围，立即`CONTRACT_STOP`回中央。未来接runner是receipt合流后的独立任务。

## 9. 必测反例

实现测试至少覆盖：

1. amount/volume得到raw VWAP，并锁定同一adj_factor同时作用于VWAP和close；
2. 三个连续gap形成exact max/min，volume lag3需四个连续sessions；
3. 仅三期bar、内部缺口、首尾缺失不跨洞，volume delay不使用上一可用观测；
4. 三个组件分别按自己的有效集合做ascending average normalized rank；
5. tie、`n<2`、不同组件分母及最终三rank交集null；
6. 最终公式、范围`[0,2]`、边界0/2与negative zero规范化；
7. 禁止percent gap、共同交集统一分母、先合成再rank、dense/min/max/descending rank；
8. volume delta必须是raw shares lag3，禁止log、ratio、复权volume或一日变化；
9. zero volume/amount令gap null；zero endpoint volume仍可形成finite raw volume delta但最终gap缺失使因子null；
10. duplicate key、session乱序/重复、bar日期越界稳定拒绝；
11. bool、NaN、Inf、非正close/adj_factor及乘积/差分溢出；
12. 多symbol、乱序输入和行置换后canonical输出相同；
13. exact columns/order/dtypes、input-only keys、无NaN/Inf；
14. 配置exact key/value/type/order，bool不得冒充int，trial_delta=0且economic execution为BLOCKED；
15. close-known到next-open时间语义，涨跌停/停牌只作未来可交易性诊断，不污染当日rank。

独立reviewer必须补至少一个实现者未使用的对抗反例，重点挑战VWAP单位、复权gap、组件各自分母、lag3
off-by-one、停牌缺口、volume jump和方向偷换。

## 10. 验证、资源和STOP

经理、实现和review阶段默认：

`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / NETWORK0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`

静态交付和独立review通过后才可申请Windows开发验证。建议最小序列：

1. Parser/identity；
2. `tests/unit/test_classic_ninth_batch.py`完整focused；
3. Ruff仅新production/test；
4. mypy仅新production；
5. fresh exact config identity单节点，不调用runner/data；
6. exact6 scope/cached0/diff/temp/process。

验证PASS只表示`R15_WINDOWS_DEVELOPMENT_VALIDATED`，不表示因子有效。输入/owner/白名单漂移、公式或rank语义
未闭合、需要经济数据、公共receipt未合流却准备label、或需要shared runner变更时立即STOP。

## 11. 当前通过条件

经理阶段只要求：

- 仅新增本taskbook；
- actual exact1、cached0、`git diff --check` PASS；
- UTF-8 no BOM、LF-only、CR0、NUL0、TW0、single EOF LF；
- Python/data/network/economic I/O/trial均为0。

当前状态上限：

`TASKBOOK_READY / STATIC_FACTOR_IMPLEMENTATION_PENDING / ECONOMIC_IO0 / TRIAL0`

## 12. Windows Development Validation1冻结合同

### 12.1 准入背景与冻结输入

静态实现与独立review已完成，但本节只冻结Windows开发反馈环，不改变第6、7节的经济评价和public receipt前置。
Validation1执行前的exact6输入为：

1. taskbook前置版本：14722 bytes / SHA256
   `0cf9dcaca89dd07aa802a64008dcdbb91c3b76a2f588f14072e2d332862be667`；
2. production：9676 bytes / SHA256
   `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a`；
3. test：21770 bytes / SHA256
   `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476`；
4. config：3227 bytes / SHA256
   `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674`；
5. delivery：5970 bytes / SHA256
   `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792`；
6. review：8393 bytes / SHA256
   `418ff3c68f5f389c8270ad82d78ad8bb33b77a95ba62cb40fa6503204016b97c`。

执行身份固定为：

- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes`；
- branch：`codex/m2-research-r15-alpha101-011-vwap-volume-extremes`；
- HEAD：`dfe49df5e8dfd9d929eb8ad196beced1da19715d`；
- Windows Python：`D:\Miniforge3\python.exe`，93184 bytes / SHA256
  `478ca44a015899fd0ff5aeaca9d407496f5c18ec454a6ec1fd36cf6d18c9a49f`。

本节落盘后的taskbook最终bytes/SHA必须由独立review重新冻结；不得继续引用前置版本identity冒充执行输入。
Validation1前fresh核exact6、HEAD/branch、cached0和`git diff --check`；任一漂移在root/Python 0-call时STOP。

### 12.2 唯一roots、path与资源边界

唯一evidence root：

`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\artifacts\agent_runs\m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1`

唯一temp root：

`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\artifacts\validation_tmp\m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1`

执行前两leaf必须fresh absent+ignored；worktree、`artifacts`和全部已存在ancestor为real directory、non-reparse、
non-follow。两root必须worktree-contained并no-clobber创建exact一次；unknown entry、root collision、reparse或containment
漂移均零Python STOP。不得扫描、复用、覆盖、移动或清理其他任务、validation、evidence或temp root。

host须保存真实priority/affinity/environment，再设置`BelowNormal`和affinity exact `0xF00`并fresh readback。child-only
环境固定：

- `OMP_NUM_THREADS=2`、`MKL_NUM_THREADS=2`、`OPENBLAS_NUM_THREADS=2`、`NUMEXPR_NUM_THREADS=2`；
- `VECLIB_MAXIMUM_THREADS=2`、`BLIS_NUM_THREADS=2`、`POLARS_MAX_THREADS=2`、`RAYON_NUM_THREADS=2`；
- `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`；
- `PYTHONPATH=<exact worktree>\src`。

全部native child串行、每阶段exact一次、线程不超过2。finally无论成功或失败均恢复host原priority/affinity/
environment，记录known child和Python/pythonw presence，并由中央外层fresh核exact `0xF00` residue=0；resource release失败
不得掩盖更早首失败。

### 12.3 Parser、阶段顺序与fixed argv

完整outer PowerShell source在任何identity、root创建、资源或Python前先以
`[System.Management.Automation.Language.Parser]::ParseInput` exact1验证errors exact0；实际执行outer source必须与
run contract记录的bytes/SHA逐字一致。parse后修补、第二次parse、临时wrapper、EncodedCommand或替代carrier均禁止。

前一阶段PASS后才可进入下一阶段；首失败立即STOP，后续全部`UNRUN`且不得重试：

1. **fresh identity**：只读闭合第12.1、12.2节全部身份、exact6、roots、scope和解释器，不启动Python。
2. **full focused test file**：
   `D:\Miniforge3\python.exe -m pytest tests/unit/test_classic_ninth_batch.py -q -p no:cacheprovider --basetemp=<Temp>\pytest`
3. **Ruff production+test**：
   `D:\Miniforge3\python.exe -m ruff check --no-cache src/quant/factors/classic_ninth_batch.py tests/unit/test_classic_ninth_batch.py`
4. **mypy production**：
   `D:\Miniforge3\python.exe -m mypy src/quant/factors/classic_ninth_batch.py --cache-dir=<Temp>\mypy`
5. **fresh config/cold identity node**：只允许现有节点，不得新增临时脚本、`python -c`、动态import探针或现场
   monkeypatch：
   `D:\Miniforge3\python.exe -m pytest tests/unit/test_classic_ninth_batch.py::test_ninth_batch_config_identity_values_types_and_order_are_exact -q -p no:cacheprovider --basetemp=<Temp>\config`
6. **scope与证据闭包**：fresh核HEAD/branch、exact6逐文件bytes/SHA、actual exact6、cached0和
   `git diff --check`；项目root不得新增`.pytest_cache`、`.ruff_cache`、`.mypy_cache`、`__pycache__`或未知文件；关闭
   process/resource、stage triples、summary、terminal和manifest-last。

第5阶段只证明tracked config exact key/value/type/order及factor module的普通pytest import surface，不调用runner、repository、
data loader、Parquet reader、label/evaluator、publisher、trial receipt或output writer。nodeid、argv、basetemp、cache-dir、
解释器或source/config identity漂移均在对应native process前STOP。

### 12.4 Evidence、I/O禁区与失败语义

evidence root中每阶段分别以no-clobber三件套保存原生stdout、stderr、exit；另保存run contract、outer Parser identity、
每项argv/count/digest、exact6 identity、resource before/after、known child、Python/process、scope/cached/diff、temp/cache
状态和manifest-last。allowed entry set须在执行前冻结；missing/extra/duplicate、partial evidence、identity或manifest漂移均
fail-closed。

本Validation只可使用test-owned内存/Temp fixture和tracked config。禁止打开、枚举或读取真实bar snapshot、data、run、
trial ledger、sealed holdout、Parquet、经济label或历史研究输出；禁止调用runner、`evaluate_walk_forward`、publisher、
receipt、PAPER、shadow、OMS、broker或LIVE。真实data/economic I/O、business execution与trial必须exact0。任何测试意外
触达真实路径、构造未来收益label或发现需要shared runner变更，立即STOP，不把部分测试通过写成因子有效。

失败时evidence和Temp原位保留，不删除、不补证、不重跑。产品阶段全部PASS后，既定成功合同要求仅清理本Validation1
Temp并证明absent；但`UA-GOV-001`明确不包含删除，因此在没有精确用户删除授权时只能停在
`R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE`，不得擅自删除或把product-stage green冒充完整Gate。
获得精确删除授权后，也只能fresh验证本Temp ordinary/non-reparse/contained/ignored与冻结entry set，删除该Temp，随后
补summary、terminal和manifest-last；不得删除evidence、父目录、其他root或项目文件，不得重跑产品阶段。

完整闭包后的唯一上限为：

`R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`

它只证明静态因子实现、测试和config通过Windows开发反馈环，不表示`alpha101_011`在A股有效，不产生RankIC、Sharpe、
组合收益或immutable run，也不授权真实trial、RUN_ONLY、PAPER、shadow或LIVE。经济评价仍须等待public receipt合流并
另立runner-integration/run任务书。

## 13. Validation1任务书独立复验与STATIC_REWORK1

### 13.1 独立复验终态

第12节经一个未参与经理、实现或既有review的全新独立reviewer复验，终态为：

`REVIEW_FAIL / P0=0 / P1=4 / P2=0`

review为20737 bytes / SHA256
`51b6b449976dbbda84742f3564d3958a94c03550ca30dbeb196dd74ad2fb6204`。复验时actual exact6、cached0，两个
Validation1 roots均absent+ignored；Python、root创建、data、economic I/O、trial、stage和commit均为0。普通
`git diff --check`虽exit0，但exact6全部为untracked，实际coverage为0，不能记为exact6 whitespace PASS。

四项P1为：相对argv未闭合child工作目录；pytest外部环境/plugin autoload未隔离；Temp删除前后会产生两次终态；
untracked exact6被ordinary`git diff --check`空洞漏检。这些问题只影响验证载体合同，不构成因子production、test、
config或经济有效性失败。Validation1在本节复验通过前继续禁止执行。

### 13.2 absolute argv与WorkingDirectory

本节supersede第12.3节所有相对产品输入path。唯一worktree绝对值为：

`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes`

每个native product process的`ProcessStartInfo.WorkingDirectory`必须在启动前设置为该exact path，并在process-start
object上fresh readback逐字相等；run contract逐阶段记录requested/readback working directory。任何default、空值、
relative、case/normalization漂移或指向相邻checkout均在child 0-call时STOP。全部product input paths改为以下absolute
argv；禁止依赖caller cwd解释test、production、config或pyproject：

1. focused：
   `D:\Miniforge3\python.exe -m pytest F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\tests\unit\test_classic_ninth_batch.py -q -p no:cacheprovider --rootdir=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes --basetemp=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\artifacts\validation_tmp\m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1\pytest`
2. Ruff：
   `D:\Miniforge3\python.exe -m ruff check --no-cache F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\src\quant\factors\classic_ninth_batch.py F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\tests\unit\test_classic_ninth_batch.py`
3. mypy：
   `D:\Miniforge3\python.exe -m mypy F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\src\quant\factors\classic_ninth_batch.py --cache-dir=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\artifacts\validation_tmp\m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1\mypy`
4. config/cold node：
   `D:\Miniforge3\python.exe -m pytest F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\tests\unit\test_classic_ninth_batch.py::test_ninth_batch_config_identity_values_types_and_order_are_exact -q -p no:cacheprovider --rootdir=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes --basetemp=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\artifacts\validation_tmp\m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1\config`

本任务不额外猜测Ruff或mypy的config-file参数；二者只接受上述absolute source/test inputs，并由fixed/readback
WorkingDirectory解析tracked`pyproject.toml`。该pyproject必须在fresh identity阶段作为只读supporting input记录
bytes/SHA，执行后复验不漂移；它不加入exact6写scope。任何argv item/count/order或supporting identity漂移STOP。

### 13.3 pytest环境隔离

第12.2节child环境补充以下强制操作：在保存host原值后，从每个child environment显式删除`PYTEST_ADDOPTS`和
`PYTEST_PLUGINS`，设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。process-start object必须在启动前fresh readback这三个
结果；run contract逐字记录。不得从用户、系统、IDE、repo cache或其他环境自动加载pytest options/plugins；
`-p no:cacheprovider`继续保留。finally恢复host原值，包括变量原本absent的状态。任何删除/readback/恢复失败
fail-closed，不能用pytest exit0掩盖。

### 13.4 单一终态与Temp删除时序

本节supersede第12.3节stage6和第12.4节中可能导致两次终态的表述：

- 产品阶段运行中只写阶段stdout/stderr/exit三件套、run contract、Parser/input/resource/known-child/Python和scope
  evidence；这些是过程证据，不是summary、terminal或manifest-last。
- 若任一产品阶段失败，按首失败合同写一次失败summary、terminal、manifest-last并保留Temp；之后不得修补、覆盖或
  重跑。
- 若所有产品阶段PASS但未获得exact Temp删除授权，不写summary、terminal或manifest-last；只保留过程证据，状态为
  `R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE`。缺少这三个文件是冻结的未终态状态，不得伪造为
  evidence缺失失败或完整PASS。
- 获得exact Temp删除授权后，fresh验证Temp ordinary/non-reparse/contained/ignored及entry set，完成唯一允许的Temp
  删除；随后且仅随后一次性写success summary、terminal和manifest-last。任一删除或写入失败STOP并保留现场，禁止
  第二终态、覆盖、补写或产品重跑。

### 13.5 untracked exact6权威scope闭包

