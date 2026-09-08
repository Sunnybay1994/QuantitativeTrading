# M2 Research R15 Alpha101 #011 量价极值独立初验报告

> task id：`M2-RESEARCH-R15-ALPHA101-011-VWAP-VOLUME-EXTREMES`
> 既有静态实现初验结论（保留）：`REVIEW_PASS / P0=0 / P1=0 / P2=0`
> 既有状态上限（保留）：`STATIC_IMPLEMENTATION_REVIEWED / VALIDATION_UNRUN / ECONOMIC_IO0 / TRIAL0`
> Windows Validation1首轮冻结合同复验（保留）：`REVIEW_FAIL / P0=0 / P1=4 / P2=0`
> 首轮状态上限（保留）：`STATIC_IMPLEMENTATION_REVIEWED / VALIDATION1_CONTRACT_REWORK_REQUIRED / ECONOMIC_IO0 / TRIAL0`
> STATIC_REWORK1同一reviewer续验：`REVIEW_PASS / P0=0 / P1=0 / P2=0`
> 第14节pre-root配置身份续验：`REVIEW_PASS / P0=0 / P1=0 / P2=0`
> 第15节outer参数绑定语法续验：`REVIEW_PASS / P0=0 / P1=0 / P2=0`
> 第16节TW控制证据续验：`REVIEW_FAIL / P0=0 / P1=1 / P2=0`
> 第16/17节文本TW旁证废止续验：`REVIEW_PASS / P0=0 / P1=0 / P2=0`
> 当前状态上限：`VALIDATION1_TASKBOOK_STATIC_REVIEWED / VALIDATION_UNRUN / DATA0 / ECONOMIC_IO0 / TRIAL0`

## 1. 审查范围与独立性

本审查者未参与实现，仅在冻结worktree内完整读取并逐项核对以下五条既有输入：

1. `docs/research/tasks/M2_RESEARCH_R15_Alpha101011量价极值任务书.md`；
2. `src/quant/factors/classic_ninth_batch.py`；
3. `tests/unit/test_classic_ninth_batch.py`；
4. `configs/research/m2_classic_daily_factors_ninth_batch.toml`；
5. `docs/research/deliveries/M2_RESEARCH_R15_Alpha101011量价极值交付报告.md`。

审查期间唯一写入本报告。未修改taskbook、production、test、config或delivery，未运行Python、pytest、Ruff、
mypy、cold、data、network、经济I/O、trial、stage或commit。因此本结论是独立静态初验，不是Windows开发验证，
更不是因子有效性、回测、PAPER或LIVE证据。

## 2. 逐项合同复核

### 2.1 公式、单位与复权

**结论：PASS。**

- production先在`amount > 0`且`volume > 0`时计算`amount / volume`，与任务书冻结的“人民币元 / 股”
  raw VWAP一致；零amount或零volume只形成局部null，没有epsilon、填0或历史替代。
- `_adjusted_vwap = _raw_vwap * adj_factor`与`_adjusted_close = close * adj_factor`使用同一行、同一
  `adj_factor`，再相减形成`_adjusted_gap`。实现没有只复权一侧，也没有把绝对gap改成百分比gap。
- `Bar1dSchema`继续约束close和adj_factor严格为正、volume和amount非负；模块在schema前拒绝Boolean源，
  schema后拒绝NaN/Inf，并在VWAP、复权乘法和差分后再次拒绝非finite，闭合了单位运算和溢出边界。
- test用`amount=(close+raw_gap)*volume`锁住amount/volume身份，并通过单symbol末日adj_factor变化证明
  gap极值排名会按共同复权尺度改变；另有overflow反例阻止非finite静默进入rank。

### 2.2 三session gap极值与raw-volume lag3

**结论：PASS。**

- production在`symbol × sessions`完整网格上回贴bar，`gap_max_3/gap_min_3`只有最近三个严格session的
  adjusted gap全部存在时才形成。
- volume分量逐字为`volume_t - volume_t-3`，没有复权、log、ratio或一日差分；`_bar_count_4 == 4`
  强制`t-3..t`四个session都有bar，即使端点存在也不能跨中间停牌洞。
- volume端点0在schema中合法，能参与raw delta；但若同一行amount或volume无法形成VWAP，最终因子仍因gap
  rank缺失而null，符合三个组件最终交集合同。
- tests覆盖三期不足、四期首个可评价值、内部/首尾缺口、zero endpoint和中间volume jump，未发现lag2、
  lag4或“上一可用观测”替代路径。

### 2.3 三组件独立横截面集合与排名

**结论：PASS。**

- `_with_component_rank`每次都对指定value column独立执行non-null count与ascending average-tie rank，
  并使用该组件自己的`(average_rank - 1)/(count - 1)`；三个调用没有共享count或先筛最终交集。
- `count < 2`时组件rank为null，未填0或0.5。三个rank全部存在后才计算
  `(r_max + r_min) * r_volume`。
- helper测试直接构造不同finite集合和tie，锁定第一组件分母3、第二组件分母3且成员不同；production调用结构
  保证相同规则分别应用到max、min和volume。最终join只负责回到输入keys，不会重算rank。
- 结果边界显式拒绝`<0`或`>2`；zero分支写入Float64 `0.0`，测试用copysign锁正零。

### 2.4 输入、输出和时间身份

**结论：PASS。**

- 输入必须是non-empty exact Polars DataFrame；sessions必须是non-empty exact tuple、元素为exact date、严格
  升序且无重复。Bar1dSchema、symbol/date二次唯一性以及bar日期属于sessions均fail-closed。
- 内部grid只用于窗口计算；最后用原始unique keys回取，因此输出不会补写缺失的symbol/session组合。输出列、
  顺序和dtype逐字为`symbol:String, trade_date:Date, alpha101_011:Float64`，canonical排序为
  `symbol, trade_date`。
- row-order置换测试覆盖输入顺序不变性，结果又做nonfinite和`[0,2]`终检。
- config逐字冻结`signal_timing="close"`与`execution_timing="next_session_open"`；本包没有label、同日成交、
  runner或publisher路径。

### 2.5 方向、trial与集成边界

**结论：PASS。**

- 因子公式没有额外负号，config的`expected_direction=1`和
  `direction_policy="pre_registered_fixed_positive"`与任务书一致；没有反向fallback或绝对IC准入逻辑。
- config中`trial_delta=0`且
  `economic_execution="BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK"`；交付报告诚实标为UNASSESSED。
- actual实现未接`run_classic_factors.py`、shared evaluator、`quant.factors.__init__`、repository、label、
  walk-forward或public receipt。冻结snapshot/config结构只是未来候选身份，不是运行授权。
- production/test/config/delivery均在任务书exact6白名单内；本报告补齐第六条路径，没有发现共享roadmap、
  progress report或其他生产路径被夹带。

## 3. 独立对抗反例

以下反例为本审查独立提出的静态推演，未调用Python或数据。它补充实现者已有测试，专门挑战“组件分母被最终
交集污染”和“价格尺度被悄悄归一化”两类高风险漂移。

### 3.1 不同分母不得在最终交集重排

设同一trade date：

- gap max/min的finite集合为`A,B,C`，两者原值均严格升序，因此B的两个rank均为`0.5`、C均为`1.0`；
- volume delta的finite集合为`B,C,D,E`，且B、C、D、E严格升序，因此B的volume rank为`0`，C为`1/3`；
- 最终三组件交集只有`B,C`。

冻结公式应给B=`(0.5+0.5)*0=0`，C=`(1+1)*(1/3)=2/3`。若错误地先取交集再统一排名，C会变成2，
经济含义和coverage都会被改写。当前production先完成三个独立rank，再检查同一symbol/date三rank非空，没有
在combined前过滤到最终交集，所以该反例保持冻结结果。

### 3.2 绝对价格尺度不得偷换为百分比gap

设两只证券的同一session分别为：A的close=10、raw VWAP=10.10，B的close=100、raw VWAP=100.20，
adj_factor均为1。冻结absolute gap为A=0.10、B=0.20，ascending rank中B高于A；若偷换成百分比gap，则A=1%、
B=0.2%，顺序反转。当前production只做`adjusted_vwap-adjusted_close`，没有除以close，因此保留任务书要求的
价格尺度暴露；delivery也将其列为未来必须诊断的风险，而没有静态美化掉该风险。

### 3.3 停牌洞与volume jump组合

设`t-3`与`t`都有bar且volume由100跃升到10000，但`t-2`缺bar。仅看两端会得到9900并产生极高volume rank；
冻结合同要求四session连续，因此该volume组件必须null。当前`_bar_count_4`在完整session grid上得到3而非4，
不会让volume jump跨洞进入最终因子。该路径与gap rolling count相互独立，最终仍需三rank共同finite。

## 4. 测试合同充分性与未执行边界

静态检查确认测试文本覆盖任务书第9节的公式、窗口、排名、zero/null、非法输入、溢出、canonical output和config
身份；实现与断言之间未见明显自洽但违约的替代算法。对抗反例3.1和3.2未作为新增可执行测试落盘，因为本角色
没有测试文件写权；建议后续Windows focused validation首先运行完整`test_classic_ninth_batch.py`，若未来返工涉及
rank集合或gap表达式，再将上述反例固化为回归节点。

本轮没有执行任何测试，所以不能把测试文件存在、静态可读或本审查PASS写成pytest/Ruff/mypy/cold PASS。

## 5. 缺陷分级与最终裁定

- P0：0；
- P1：0；
- P2：0。

最终裁定：`REVIEW_PASS`。

该结论只证明当前exact6静态实现与冻结合同一致。下一步仍需统筹另行授权focused Windows开发验证；其后也只能
获得开发验证状态。公共receipt合流、runner-integration、真实bar snapshot、walk-forward、成本/容量、市场状态
诊断和trial仍须分别冻结并授权。在产生本地样本外经济证据前，`alpha101_011`必须保持`UNASSESSED`，不得进入
PAPER或LIVE。

## 6. Windows Validation1冻结合同独立复验

### 6.1 复验身份、输入与未运行边界

本节由未参与R15经理、实现或既有review的全新独立reviewer完成，只审查任务书第12节的Windows Development
Validation1冻结合同。审查期间完整读取当前taskbook、production、test、config、delivery和既有review，并定向核对
`pyproject.toml`、`.gitignore`、`quant.factors`普通import surface与现有config node。唯一写入仍为本review文件；
production、test、config、taskbook和delivery保持只读。

本节写入前的冻结快照为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook最终版本 | 22193 | `cefc792cbe0428f754dc9f4b21db1801156b98be54986244b76de16e79eb85c3` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 既有review前置版本 | 8393 | `418ff3c68f5f389c8270ad82d78ad8bb33b77a95ba62cb40fa6503204016b97c` |

该快照与任务书第12.1节五条非taskbook输入及既有review identity逐字一致；taskbook最终identity已按第12.1节要求
重新冻结，不能再使用14722-byte前置taskbook。写入本节后review自身identity必然改变，最终bytes/SHA须作为外部
detached identity随本次review交回；Validation1准入必须使用写入后fresh exact6，不能继续使用8393-byte既有review
identity。

静态只读现场为：exact worktree、branch与HEAD匹配；`D:\Miniforge3\python.exe`为93184-byte ordinary leaf且
SHA-256=`478ca44a015899fd0ff5aeaca9d407496f5c18ec454a6ec1fd36cf6d18c9a49f`，与合同一致但未执行；
worktree及当前已存在的`artifacts` ancestors均为ordinary/non-reparse，两个Validation1 leaf均fresh absent、
worktree-contained且被`.gitignore`的`artifacts/*`规则命中；actual scope为exact6、cached0；
`git diff --check` exit0但对六条untracked路径coverage=0，
属于vacuous result而非可采信PASS，详见P1-4。本轮未执行Parser carrier或Validation，
未调用Windows Python、pytest、Ruff、mypy、data、network、真实bar、经济I/O、business execution、trial、stage或
commit；资源事实保持`STATIC_ONLY / CPU_NONE / PYTHON0 / root0 / data0 / trial0 / stage0 / commit0`。

### 6.2 已闭合合同项

以下合同静态可判定为闭合，但不等于运行PASS：

- exact6五条前置非taskbook输入、最终taskbook、worktree、branch、HEAD与Windows Python path/bytes/SHA均有明确
  identity；fresh准入要求在root/Python 0-call时检查漂移、cached0和diff-check；
- evidence/temp唯一leaf、fresh absent+ignored、ancestor ordinary/non-reparse/non-follow、worktree containment、
  no-clobber exact一次创建及“不得触碰其他root”边界已冻结；
- `ParseInput exact1/errors0 → fresh identity → full focused file → Ruff production+test → mypy production → existing
  config node → scope/evidence closure`的顺序、首失败、后续UNRUN和no-retry语义明确；
- focused与config nodeid均确实存在于当前exact test；pytest禁cacheprovider，Ruff禁cache，mypy cache和两个
  basetemp均指向本Validation1 Temp；
- test文本只构造内存fixture并打开tracked config；production与普通factor/domain import surface未发现真实data、
  runner、label、receipt或writer入口；任务书也明确要求真实bar/data/economic/business/trial exact0；
- 失败时保留本Validation evidence/Temp、不删除、不补证、不重跑；无精确删除授权时状态上限停在
  `R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE`；完整闭包上限不超过
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`。

### 6.3 P1-1：relative argv没有冻结实际child工作目录

**现象。** 第12.3节三个Python argv均使用相对test/production路径，但第12节没有要求每个native child的
`WorkingDirectory`等于exact worktree，也没有将实际cwd/解析后的绝对路径写入run contract和阶段证据。
`PYTHONPATH=<exact worktree>\src`只能绑定production import，不能绑定相对test文件或该test通过`__file__`解析的
config。

**根因。** “执行身份固定为worktree”是预期身份，不等于`ProcessStartInfo.WorkingDirectory`或等价native child
属性的设置与fresh readback。fixed argv digest也不包含操作系统cwd。

**应遵循规则。** 每个native process启动前必须把WorkingDirectory显式设置为exact worktree，fresh读取并记录
canonical resolved cwd；同时将每个相对argv operand解析为该worktree内的expected absolute ordinary/non-reparse
path。任一不一致必须在对应Python 0-call时STOP。

**最小反例。** 从相邻R13/R14或任意decoy checkout启动outer carrier；该checkout也有同名test/nodeid/config，
而`PYTHONPATH`仍指向R15 production。当前argv可能运行decoy test和decoy config，却把R15 production hash写进
identity，形成混合checkout的假PASS。

**新增测试要求。** 返工后的carrier合同应加入host-only decoy-cwd反例：outer cwd故意指向包含同名nodeid的相邻
root，断言在native process前STOP、Python0，并且两个Validation roots仍absent。另加入nodeid漂移反例：exact test
已改名但fixed nodeid未同步时，不允许转去其他checkout找到同名node。

**通过条件。** taskbook逐字冻结WorkingDirectory与resolved operand检查；run contract/evidence记录expected/actual
cwd和每个resolved path；decoy-cwd与nodeid漂移均0-Python STOP。

### 6.4 P1-2：继承环境可改变pytest有效语义并绕过full focused/data0

**现象。** 第12.2节只固定线程、编码、bytecode和`PYTHONPATH`变量，没有要求拒绝或清除
`PYTEST_ADDOPTS`、`PYTEST_PLUGINS`及pytest第三方plugin autoload。OS argv/count/digest不包含pytest从环境追加的
选项或自动加载的插件，因此“fixed argv”不能证明实际执行了focused tests，也不能证明未发生额外I/O。

**根因。** host原environment被保存/恢复，但child继承面的允许集合、拒绝集合与effective pytest option/plugin
identity没有闭合。stdout/stderr/exit三件套只能记录结果，不能阻止exit 0的语义旁路。

**应遵循规则。** child环境必须fail-closed：至少要求`PYTEST_ADDOPTS`和`PYTEST_PLUGINS`absent，设置并fresh
readback `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，拒绝会注入coverage/site/user-site/外部代码或另一路径cache/temp的
环境变量；只允许任务书冻结的必要变量继承或覆盖。pytest PASS还必须记录实际collected/executed/deselected counts，
full focused不得以collect-only或全deselect的exit 0替代。

**最小反例。** host预置`PYTEST_ADDOPTS=--collect-only`。当前native argv字节完全不变，pytest可以只收集节点后
exit 0；stage wrapper若只看exit code会把“一个测试都未执行”写成full focused PASS。另一反例是通过
`PYTEST_PLUGINS`/autoload加载环境外plugin，在collection时读取真实data或向其他cache root写文件；项目末尾的
unknown-file检查既不能证明0-read，也不能覆盖worktree外的cache逸出。

**新增测试要求。** 返工合同应包含两个host-only adversarial probes：预置`PYTEST_ADDOPTS=--collect-only`与预置
`PYTEST_PLUGINS=<decoy>`，两者都必须在pytest进程前STOP、Python0、root不创建或只保留合法首失败证据，且不得
尝试“运行后再判断”。

**通过条件。** taskbook冻结child环境allow/deny及readback；上述变量注入均pre-process STOP；正常阶段证据包含
非零executed count、deselected=0和预期node集合摘要，不能只以exit=0判PASS。

### 6.5 P1-3：manifest-last与延后删除授权的两阶段闭包互相冲突

**现象。** 第12.3节stage 6要求关闭`summary、terminal和manifest-last`；但第12.4节又规定产品阶段全绿而没有
删除授权时先停在`FINAL_CLOSURE_INCOMPLETE`，未来获授权删除Temp后再“补summary、terminal和manifest-last”。
两句无法同时满足no-clobber与manifest-last。

**根因。** 产品阶段终点与经用户授权的cleanup终点被写成一个终态，没有为等待授权的中间checkpoint冻结独立
entry/state。若stage 6先写manifest，后续删除和补文件发生在manifest之后；若不写，则违反stage 6“关闭”要求。

**应遵循规则。** 成功路径必须显式拆成两个状态：产品阶段完成后只写immutable
`product_stages_checkpoint`并释放资源，不写terminal/最终manifest；只有fresh精确删除授权、仅目标Temp的
ordinary/non-reparse/contained/ignored/entry-set核验和删除成功后，才exact一次写summary、terminal、manifest-last。
失败路径仍原位保留且不得进入cleanup。

**最小反例。** Validation1 Temp为目标A，同时相邻存在另一个任务Temp B。产品阶段全绿但无删除授权：若先写
manifest，后续授权删除A再补manifest会破坏last/no-clobber；若cleanup按父目录或枚举结果执行，还可能误删B，
违反第12.2节“不得扫描或清理其他root”。

**新增测试要求。** 返工合同应加入cleanup-only对抗反例：A为精确授权leaf，B为同父目录普通decoy root并冻结
bytes/SHA；cleanup后只允许A absent，B及其bytes/SHA必须不变，evidence root必须不变，且最终manifest是证据root
最后一个、exact一次创建的entry。不得用枚举后批量删除实现该测试。

**通过条件。** taskbook消除stage 6与第12.4节的双写歧义，冻结中间checkpoint、恢复入口、cleanup-only fixed
argv/entry set和唯一最终manifest时点；无授权时删除0，获授权后只删除A，B/evidence/父目录不变，产品阶段不重跑。

### 6.6 P1-4：普通git diff-check对当前untracked exact6是空检查

**现象。** 当前actual exact6全部为untracked、cached0；普通`git diff --check`返回exit 0且无输出，但Git不会把
untracked文件纳入该diff。因此第12.1/12.3节要求的`git diff --check`无法检查本任务任何一条实际输入。

**根因。** 合同把“命令exit 0”误当成“exact6均被检查”，没有冻结diff-check的输入清单和coverage计数。

**应遵循规则。** whitespace/encoding检查必须对exact6逐文件显式执行并记录expected=6、actual=6及每条path/digest；
可使用能把untracked文件作为新增blob检查的固定命令，或冻结等价的byte-level UTF-8 no-BOM、LF-only、CR0、NUL0、
trailing-whitespace0和single-EOF-LF检查。普通working-tree diff仍可作为额外检查，但不得替代exact6 coverage。

**最小反例。** 在任一untracked exact6末尾加入trailing whitespace或CRLF；当前`git diff --check`仍可exit 0，
scope仍是exact6、cached0，carrier会把未检查的输入误记为diff-check PASS。

**新增测试要求。** 用独立decoy untracked文件分别注入trailing whitespace、CRLF、BOM、NUL和缺失EOF LF，断言
exact-file checker逐例first-failure，且coverage报告不能少于六条或包含第七条路径。

**通过条件。** taskbook冻结可覆盖untracked exact6的fixed checker及expected/actual=6证据；每条负例均在root/
Python 0-call时STOP；普通`git diff --check`若coverage=0只能记为辅助vacuous结果，不能写PASS。

### 6.7 缺陷分级与裁定

- P0：0；
- P1：4；
- P2：0。

Windows Validation1冻结合同最终裁定：`REVIEW_FAIL`。

该FAIL不推翻上文既有静态实现初验的`REVIEW_PASS`，只表示第12节尚不能作为可执行Validation1 carrier合同。
在P1-1至P1-4由经理回写taskbook并由同一review链fresh复验前，必须保持
`STATIC_ONLY / CPU_NONE / PYTHON0 / root0 / data0 / trial0 / stage0 / commit0`，不得启动Parser carrier、创建
Validation roots或执行任何Windows Python阶段。

## 7. Validation1 STATIC_REWORK1同一reviewer续验

### 7.1 续验身份、冻结快照与未运行边界

中央批准首轮同一独立reviewer继续复验；本节只审查taskbook第13节对首轮四项P1的静态返工，不覆盖或删除
第6节`REVIEW_FAIL / P1=4`历史。续验写入前exact6为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook STATIC_REWORK1 | 29582 | `c932d34faff6abc3a92afaa445550daa8b611c711efd8c5e30857e890ee16184` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 首轮review | 20737 | `51b6b449976dbbda84742f3564d3958a94c03550ca30dbeb196dd74ad2fb6204` |

写入本节后review identity必然改变，最终bytes/SHA作为detached identity随本次续验交回；未来Validation1 fresh
identity必须使用该最终review，不得继续使用20737-byte首轮版本。tracked supporting input
`pyproject.toml`静态观察为1265 bytes / SHA256
`96047c6772bb08696f924ad9497d3a6c26b6cb08b2f5332fc600288355c8d3dd`。

续验前actual untracked set exact6、cached0；六条路径逐文件均为strict UTF-8、no BOM、LF-only、CR0、NUL0、
TW0、single EOF LF、ordinary/non-reparse且worktree-contained。普通`git diff --check`仍仅为exit0、
`tracked_untracked_exact6_coverage=0 / VACUOUS_FOR_EXACT6`，未被升级为权威PASS。Windows Python ordinary leaf仍为
93184 bytes / SHA256 `478ca44a015899fd0ff5aeaca9d407496f5c18ec454a6ec1fd36cf6d18c9a49f`，仅静态读取identity，
未执行。

本续验唯一写入本review；未修改taskbook、production、test、config或delivery，未启动Parser carrier、Windows
Python、pytest、Ruff、mypy、data、network、经济I/O、business execution、trial、stage或commit。现场保持
`STATIC_ONLY / CPU_NONE / PYTHON0 / root0 / data0 / trial0 / stage0 / commit0`。

### 7.2 首轮四项P1逐项闭合

#### P1-1：absolute argv、exact rootdir与WorkingDirectory——PASS

- 第13.2节明确supersede第12.3节全部相对产品输入；focused、Ruff、mypy和config node的test/source/basetemp/
  cache-dir均为exact worktree下absolute path，两个pytest阶段另固定exact `--rootdir=<worktree>`。
- 每个native product process必须在启动前把`ProcessStartInfo.WorkingDirectory`设置为exact worktree，并在
  process-start object fresh readback逐字相等；run contract逐阶段记录requested/readback值。
- default、空、relative、case/normalization或相邻checkout漂移均在child 0-call时STOP。`pyproject.toml`作为只读
  supporting input在fresh identity与执行后均复算bytes/SHA，不能借cwd读取另一份工具配置。

首轮“relative argv可混跑相邻checkout”已闭合。

#### P1-2：pytest环境注入与plugin autoload——PASS

- 第13.3节要求保存host原值后，从每个child environment显式删除`PYTEST_ADDOPTS`和`PYTEST_PLUGINS`，设置
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`；三项均在process-start object启动前fresh readback并进入run contract。
- `-p no:cacheprovider`继续保留，两个pytest argv都固定exact test path、rootdir和本Validation1 basetemp。
- 删除、readback或finally恢复host原值/原absent状态任一失败均fail-closed，不能由pytest exit0覆盖。

首轮“host环境可用collect-only或外部plugin形成假绿/额外I/O”已闭合。

#### P1-3：单一终态与Temp删除授权——PASS

- 第13.4节明确supersede第12节冲突文本：产品运行中只写过程证据，不写summary、terminal或manifest-last。
- 任一产品阶段失败时exact一次写失败终态并保留Temp，之后不得修补、覆盖或重跑。
- 产品阶段全PASS但没有exact Temp删除授权时，三个终态文件保持absent，固定停在
  `R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE`；absence是合同状态，不冒充证据缺失失败。
- 只有fresh精确删除授权并验证目标Temp ordinary/non-reparse/contained/ignored/entry set后，才只删除该Temp，
  随后exact一次写success summary、terminal和manifest-last。删除/写入失败均STOP，禁止第二终态或产品重跑。

首轮“manifest-last前后出现两次终态或误删其他root”已闭合，且standing delegation仍不授权删除。

#### P1-4：untracked exact6权威byte/path/set closure——PASS

- 第13.5节诚实保留ordinary diff-check为tracked旁证，并强制记录coverage=0与`VACUOUS_FOR_EXACT6`。
- 权威闭包改为product前后对六个冻结path逐文件复算bytes/SHA、strict UTF-8/no BOM、LF-only/CR0/NUL0、
  TW0、single EOF LF、exact ordinary/non-reparse/contained path，并核actual untracked set exact6、cached0及无第七
  business path。
- 任一identity、path kind、set或byte hygiene漂移均在下一阶段前STOP；不得运行时修文件，也不得笼统豁免
  Markdown trailing whitespace。root/tool cache与evidence/temp仍按各自边界核验，不混入exact6。

首轮“普通git diff-check对untracked exact6空检查却被记为PASS”已闭合。

### 7.3 独立对抗反例

#### 恶意PYTEST_ADDOPTS注入

假设host在carrier启动前已有`PYTEST_ADDOPTS=--collect-only`，并同时存在
`PYTEST_PLUGINS=decoy_external_plugin`。冻结合同要求先保存这两个host原值，再从child environment删除，设置
autoload disable为1，并在process-start object readback为两个absent、一个exact `1`。因此OS argv不变时也不能把
collect-only或decoy plugin注入pytest；任一readback不符在pytest 0-call时STOP。child结束后host必须恢复原恶意值，
不能因“安全化child”篡改用户环境。该反例同时锁住假绿、外部plugin I/O与restore边界。

#### caller cwd漂移至相邻checkout

假设outer从R13/R14或一个含同名test/nodeid/config的decoy checkout启动。四个product argv的输入均是R15 absolute
path，pytest还固定R15 absolute rootdir；PSI WorkingDirectory必须requested/readback为R15 exact worktree。若设置成功，
caller cwd无法改变test、config或pyproject来源；若发生case/normalization/相邻checkout漂移，则在对应child 0-call时
STOP。该反例闭合首轮混合checkout风险，不依赖执行后输出猜测身份。

### 7.4 roots、阶段、资源与数据边界无回归

- exact evidence/temp leaf仍fresh absent、ignored、worktree-contained；现有ancestor ordinary/non-reparse。本续验未创建
  root。no-clobber exact一次创建、unknown entry/root collision/reparse/containment漂移零Python STOP保持不变。
- `ParseInput exact1/errors0 → fresh identity → full focused → Ruff → mypy → existing config node → scope/evidence`
  首失败、后续UNRUN、no-retry、失败证据与Temp原位保留合同未被返工削弱。
- host priority/affinity/environment保存、`BelowNormal`、exact `0xF00`、child线程上限、finally恢复、known-child/
  Python residue和较早首失败优先级保持不变。
- test-owned memory/Temp fixture与tracked config仍是唯一允许输入；真实bar snapshot、data、run、ledger、holdout、
  Parquet、label/evaluator、publisher、receipt、PAPER、shadow、OMS、broker和LIVE全部禁止，data/economic/business/
  trial exact0。
- 完整运行后的状态上限仍只是
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`，不是因子有效、Gate、PAPER或LIVE证据。

### 7.5 缺陷分级与续验裁定

- P0：0；
- P1：0；
- P2：0。

STATIC_REWORK1最终裁定：`REVIEW_PASS`。

该PASS只证明第13节在静态层面闭合首轮四项P1，保留第6节首轮FAIL历史；它不是Parser、Windows Python、pytest、
Ruff、mypy、resource release、Temp cleanup或完整Validation的运行证据。中央另行依据授权执行产品阶段前，仍须以
写入后final exact6和supporting input fresh闭合；Temp删除继续需要精确用户授权。

## 8. 第14节pre-root配置身份STOP与唯一清单来源续验

### 8.1 续验范围、输入快照与独立边界

中央批准同一原reviewer继续复验第14节；本节保留第6节首轮FAIL和第7节STATIC_REWORK1 PASS历史，只判断
pre-root配置身份STOP的历史定性、唯一config identity以及新outer input manifest来源。写入本节前exact6为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook第14节版本 | 32241 | `8a9ea0c5617dd3cf7854df1daa460d06b4d5dbe4d1404fee25bce57a132096a5` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 第13节review | 29069 | `c1b69912b0b517f63da3abfd627999e7eb3a30abfd25824555c4b01d73460e98` |

写入本节后review identity必然变化；final bytes/SHA作为detached identity随本次续验交回，未来outer必须使用
写入后fresh exact6，不得继续绑定29069-byte review。续验前actual untracked set exact6、cached0；六条路径均为
strict UTF-8、no BOM、LF-only、CR0、NUL0、TW0、single EOF LF、ordinary/non-reparse且worktree-contained。

本轮唯一写入既有review；taskbook、production、test、config和delivery保持只读。没有启动Parser carrier、创建
root、取得资源或调用Windows Python、pytest、Ruff、mypy、data、经济I/O、business execution、trial、stage、commit。
资源事实为`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。

### 8.2 pre-root STOP历史定性——PASS

- 中央发现不存在的旧配置alias发生在fresh input-manifest准备阶段，早于evidence/temp root创建、资源取得、
  Parser product gate与任何Python，因此第14节原生终态
  `VALIDATION_CONTRACT_STOP / CONFIG_PATH_IDENTITY_MISMATCH / PRODUCT_NOT_EVALUATED`准确。
- 该事件是合同清单身份首失败，不是config内容、因子production、测试或产品阶段失败；必须维持
  `ROOT_CREATE0 / PYTHON0 / PRODUCT_UNRUN / DATA0 / ECONOMIC_IO0 / TRIAL0`。
- 因为没有进入outer产品执行，也没有创建可承载过程证据的root，所以它不计产品attempt、不产生可复用产品证据，
  更不能把后续新outer称为retry。当前两个Validation1 leaf现场仍fresh absent+ignored；第14节review PASS后，新的
  outer才可使用唯一产品attempt并exact-once执行。

历史没有被改写成一次虚假产品失败，也没有消耗唯一attempt。

### 8.3 唯一config identity与FORBIDDEN alias——PASS

Validation1唯一配置逐字闭合为：

- relative path：`configs/research/m2_classic_daily_factors_ninth_batch.toml`；
- absolute path：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r15-alpha101-011-vwap-volume-extremes\configs\research\m2_classic_daily_factors_ninth_batch.toml`；
- bytes：3227；
- SHA-256：`633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674`。

静态现场确认该path为ordinary/non-reparse文件且identity匹配。旧
`configs/research/m2_factor_r15_alpha101_011.toml`真实不存在；它只在taskbook第14节作为历史错误与
`VOID / FORBIDDEN_ALIAS`出现，写入本节前未进入production、test、config、delivery或既有review。第14节明确禁止把它解释为
兼容名、fallback或迁移入口，并禁止搜索相似文件、复制、symlink、动态fallback或改名修复。任何outer、run contract、
identity map、argv或evidence包含该alias，均须在root/Python 0-call时STOP。

### 8.4 outer input manifest权威来源与readback——PASS

- 新outer必须从taskbook冻结的exact6 path list按固定顺序逐项派生input manifest，禁止手工重建文件名、复用历史
  session列表或根据factor名猜测config名。
- manifest构造后必须对taskbook、production、test、config、delivery、review逐项fresh readback relative path、
  absolute path、bytes和SHA；六项的path、kind、containment与identity必须同时闭合。
- missing、extra、reordered、alias、containment或identity任一漂移均为pre-root STOP。review本次追加后的final identity
  必须取代第13节predecessor，不能从旧manifest继承。

因此清单的名称来源与identity来源都回到taskbook exact6，而不是外部手写alias或历史控制面。

### 8.5 独立对抗反例

假设外部准备器在manifest中同时放入正确ninth-batch config与旧alias，并让旧alias成为指向正确config的symlink，
从而使bytes/SHA表面相同。冻结合同仍应在root 0-call时STOP：actual set出现第七项且顺序/relative path错误，alias又被
逐字标记为`FORBIDDEN_ALIAS`；不得因为目标bytes相同就接受symlink、去重或fallback。当前第14节的exact6派生、
ordinary/non-reparse path与missing/extra/reordered/alias检查共同闭合该反例。

另设准备器沿用第13节29069-byte review identity。即使其余五项完全匹配，fresh readback也必须因review bytes/SHA
漂移而pre-root STOP；不能把本轮追加后的review静默排除在manifest之外。

### 8.6 roots、argv、阶段、资源与状态上限无回归

- evidence/temp唯一leaf、fresh absent+ignored、ancestor ordinary/non-reparse、containment与no-clobber exact一次创建
  保持第12、13节合同；本轮root创建为0。
- Parser source identity、absolute product argv、exact pytest rootdir、PSI WorkingDirectory requested/readback、pytest
  环境隔离、focused→Ruff→mypy→existing config node→scope的顺序、首失败/UNRUN/no-retry均未改变。
- priority/affinity/environment保存恢复、线程上限、known-child/Python residue、failure preserve与Temp精确删除权限
  未被第14节放宽。
- production、test、config、delivery及写入前review exact5未漂移；真实bar/data/economic/business/trial继续exact0。
- 完整产品阶段的最高状态仍仅为
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`，不构成因子有效、Gate、PAPER或LIVE证据。

### 8.7 缺陷分级与续验裁定

- P0：0；
- P1：0；
- P2：0。

第14节最终裁定：`REVIEW_PASS`。

该PASS只确认pre-root STOP历史、唯一config与outer manifest来源静态闭合；它不证明outer Parser、产品阶段、资源释放、
Temp清理或Windows Validation已经运行。中央构造新outer前仍须使用写入后final exact6 fresh readback；Temp删除仍需
精确用户授权。

## 9. 第15节outer root-collision参数绑定语法续验

### 9.1 续验范围、输入快照与未运行边界

中央批准同一原reviewer继续复验第15节；本节保留第6节首轮FAIL、第7节STATIC_REWORK1 PASS和第8节pre-root
config identity PASS历史，只判断本次outer参数绑定STOP、修正后的PowerShell布尔表达式和outer source identity。
写入本节前exact6为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook第15节版本 | 34066 | `f84f259b9ccf8192c0db6a643231e50e2e5501a80f34832b8a8529b6dd365273` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 第14节review | 35832 | `5a5d0e2a5056aef20ba6fa2557a5d0e3b45dfd239197832e081c4c2847f4b7e0` |

写入本节后review identity必然改变；final bytes/SHA作为detached identity随本次续验交回。未来outer必须fresh
绑定写入后review，不能继续使用35832-byte predecessor。续验前actual untracked set exact6、cached0，五条非taskbook
输入均未漂移；两个Validation1 roots仍fresh absent+ignored。

本轮唯一写入既有review；未修改taskbook、production、test、config或delivery，未启动Parser carrier、创建root、
取得资源或调用Windows Python、pytest、Ruff、mypy、data、economic/business I/O、trial、stage、commit。现场保持
`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。

### 9.2 outer parameter-binding STOP历史定性——PASS

- 旧root collision表达式把两个`Test-Path`调用写成
  `Test-Path -LiteralPath $ev -or Test-Path -LiteralPath $tmp`；第二个`-LiteralPath`会进入同一未闭合cmdlet调用的
  参数绑定面，形成pre-root控制面参数绑定错误。
- 第15节原生终态
  `VALIDATION_CONTRACT_STOP / OUTER_CONTROL_PARAMETER_BINDING_ERROR / PRODUCT_NOT_EVALUATED`准确；错误发生在
  evidence/temp root创建、资源取得和Python产品阶段之前。
- Evidence/Temp roots、Python、pytest、Ruff、mypy、resource、data、economic/business I/O与trial均为0；exact6未被
  outer修改，roots没有被占用。该事件不是R15因子、test、config或Windows product failure，不计产品attempt，也不
  产生可复用产品证据。

因此下一次获准outer仍是唯一产品attempt，而不是对已启动产品阶段的retry。

### 9.3 root-collision双括号语法——PASS

第15节唯一允许的检查为：

```powershell
if ((Test-Path -LiteralPath $ev) -or (Test-Path -LiteralPath $tmp)) {
    throw 'ROOT_COLLISION'
}
```

两个cmdlet调用分别在自己的完整括号中求值，随后才由外层布尔表达式使用`-or`连接；不存在把第二个
`-LiteralPath`误绑定给第一个`Test-Path`的路径。若任一leaf已存在，表达式抛出`ROOT_COLLISION`并保持root创建0；
两者均absent时才允许进入后续既有fresh identity/root no-clobber流程。

第15节同时把规则推广到同一outer内所有包含两个或以上cmdlet调用的布尔表达式：每个cmdlet调用必须逐调用完整
括号化，禁止用裸`-or`或`-and`连接尚未闭合的命令调用，也禁止依赖参数绑定优先级猜测。这一规则覆盖的不只是
当前两个leaf，避免相同缺陷在后续path/resource检查中复现。

### 9.4 Parser、execution source与run-contract identity——PASS

- 完整outer source仍须在任何root、resource和Python前由`Parser.ParseInput` exact1检查errors0。
- Parser输入的完整source bytes、实际执行source bytes及run contract记录的source bytes/SHA必须逐字同一；不是
  仅比较语义、命令数量或格式化后的文本。
- parse后修改、换用另一段outer、临时wrapper或以不同bytes执行均被禁止。即使替代source在语义上也包含双括号，
  只要bytes/SHA不等于Parser输入和run contract就必须STOP。

因此Parser负责语法闭合，source三方identity负责阻断“解析A、执行B”；参数绑定安全由第15节固定源码与逐cmdlet
括号规则共同保证。

### 9.5 独立对抗反例

设outer把当前检查扩展成三个调用：前两个正确括号化，但第三个写成裸
`-and Test-Path -LiteralPath $third`。即使前半段与冻结代码相同，第15节也要求拒绝：第三个cmdlet未独立完整括号化，
仍可能进入前一命令的参数绑定面。通过条件不是“Parser errors0”或现场恰好未报错，而是每一个cmdlet调用均满足
逐调用括号规则且完整source identity匹配。

另设source A通过Parser，随后只改变空白或错误消息形成source B并执行。即使B的PowerShell语义等价，A/B bytes与
run-contract SHA不一致，必须在root/resource/Python前STOP；不能用“语义相同”绕过逐字source identity。

### 9.6 exact6、roots、argv、resource、Temp与状态上限无回归

- 第12至14节的exact6逐文件identity/byte/path/set closure、唯一ninth-batch config及旧alias
  `VOID / FORBIDDEN_ALIAS`继续有效；ordinary diff-check仍只是coverage0旁证。
- evidence/temp唯一roots、fresh absent+ignored、ancestor ordinary/non-reparse、containment、no-clobber exact一次创建与
  collision零Python STOP未被放宽；本轮root创建仍为0。
- absolute product argv、exact pytest rootdir、PSI WorkingDirectory、pytest环境隔离、focused→Ruff→mypy→existing
  config node→scope顺序、first-failure/UNRUN/no-retry保持不变。
- priority/affinity/environment、线程上限、known-child/Python residue、failure preserve和Temp精确删除授权边界无漂移。
- 真实bar/data/economic/business/trial继续exact0；完整产品阶段最高状态仍仅为
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`，不是因子有效、Gate、PAPER或LIVE证据。

### 9.7 缺陷分级与续验裁定

- P0：0；
- P1：0；
- P2：0。

第15节最终裁定：`REVIEW_PASS`。

该PASS只确认outer参数绑定STOP历史、固定PowerShell括号规则与source identity静态闭合；它不证明Parser、root创建、
产品阶段、资源释放、Temp cleanup或Windows Validation已经运行。中央构造下一outer前仍须用写入后final exact6与
完整outer source fresh闭合；Temp删除继续需要精确用户授权。

## 10. 第16节trailing-whitespace控制证据续验

### 10.1 续验范围、输入快照与未运行边界

中央批准同一原reviewer继续复验第16节；本节保留第6节首轮FAIL与第7至9节历史，只判断control-evidence
mismatch、更正后的TW算法、文本旁证和outer source identity。写入本节前exact6为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook第16节版本 | 36469 | `c268779b39d3afccb2a08e21a33d2777a409082bb3cfcffd87aad22d7a4fb7e7` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 第15节review | 42464 | `394918a3d4562504574dbc524f05d30bda12a4b20ba3b0fb03d607645800ef45` |

写入本节后review identity必然改变；final bytes/SHA作为detached identity随本次续验交回。续验前actual untracked
set exact6、cached0，五条非taskbook输入未漂移，两个Validation1 roots继续fresh absent+ignored。

本轮唯一写入既有review；未修改taskbook、production、test、config或delivery，未启动Parser carrier、创建root、
取得资源或调用Windows Python、pytest、Ruff、mypy、data、economic/business I/O、trial、stage、commit。现场保持
`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。

### 10.2 control-evidence mismatch历史与全零边界——PASS

- 第15节review PASS后的outer在pre-root byte-hygiene阶段报告历史34066-byte taskbook存在35条TW；经理的`rg`与独立
  raw-byte LF回扫均为0，中央反审计定位为PowerShell数组/`-split`/pipeline优先级错误，而非taskbook字节缺陷。
- 历史taskbook identity `34066 / f84f259b9ccf8192c0db6a643231e50e2e5501a80f34832b8a8529b6dd365273`
  与第9节冻结输入一致。第16节将权威终态更正为
  `VALIDATION_CONTROL_EVIDENCE_MISMATCH / TRAILING_WHITESPACE_COUNTER_PRECEDENCE_ERROR /
  PRODUCT_NOT_EVALUATED`，没有把控制面假计数写成产品失败。
- Evidence/Temp roots仍absent，Python、resource、data、economic/business I/O与trial均为0；错误发生在产品阶段前，
  不计产品attempt。禁止修改或“规范化”已经TW0的taskbook，也不复用错误outer的控制证据。

该历史定性、全零边界与唯一产品attempt保留准确。

### 10.3 raw-byte权威TW算法——PASS

第16节要求权威检查直接`ReadAllBytes`，以0x0A为行界，只从每个LF前向左回扫连续0x20或0x09；这避免文本解码、
PowerShell正则、数组包装和pipeline优先级改变字节语义。每个命中必须输出：

- 1-based line number；
- ASCII suffix count；
- suffix hex；
- total hit count。

任一非零结果必须能从raw bytes独立复算，不能只给聚合数。当前36469-byte taskbook按该算法静态回扫得到
`RAW_HITS=0`，与文件的TW0和single EOF LF现场一致。该权威算法本身闭合。

### 10.4 P1-1：文本三步旁证仍把字母t和反引号当作TW

**现象。** 第16节把文本旁证拆成三步，但匹配行写为：

```powershell
$twLines = @($lines | Where-Object { $_ -match '[ `t]+$' })
```

PowerShell单引号字符串不会把backtick escape `` `t``展开为tab；传给.NET regex的是literal space、backtick和字母
`t`组成的字符类，而不是space/tab字符类。因此该旁证会把以字母`t`或反引号结尾的正常行计为TW，并漏掉真实0x09。

**根因。** 第16节修复了数组/`-split`/pipeline的运算优先级，却沿用了与字符串引号语义不兼容的tab写法。
三步拆分只闭合了计数对象，没有闭合正则字符集合。

**最小复现。** 对当前taskbook的只读静态复算结果为：

- raw-byte权威算法：`RAW_HITS=0`；
- 当前单引号模式：`BAD_TEXT_HITS=38`；
- `'t' -match '[ `t]+$'`为true；
- 反引号字符匹配为true；
- 实际tab匹配为false。

这会立刻重现第16节试图消除的control-evidence mismatch；虽然fail-closed不会形成产品假绿，但会让干净exact6在
pre-root阶段持续STOP，Validation1合同仍不可执行。

**应遵循规则。** 最小修复二选一：删除非权威文本旁证，只保留raw-byte权威结果；或把单引号regex逐字冻结为
`'[ \x09]+$'`，由.NET regex解释0x09。不得在单引号PowerShell字符串中继续使用`` `t``假装tab。

**新增反例与通过条件。** 修订后必须静态闭合：普通字母`t`结尾命中0、反引号结尾命中0、0x09结尾命中1、
0x20结尾命中1；当前taskbook的raw-byte与文本旁证均为0。任一不一致继续
`VALIDATION_CONTROL_EVIDENCE_MISMATCH` STOP，且root/Python/product attempt均为0。

### 10.5 mismatch STOP与outer source同源——PASS

- raw-byte权威结果与可选文本旁证只要不一致，就必须立即
  `VALIDATION_CONTROL_EVIDENCE_MISMATCH` STOP；禁止选择有利结果、修改文件或进入产品阶段。
- 完整outer仍须保持Parser输入、实际execution source和run-contract source bytes/SHA逐字同源；parse后修改或换用
  另一段TW检查实现均不允许。
- 这两项保证当前P1导致的是可见的pre-root控制面STOP，而不是假绿。但fail-closed只能限制后果，不能把错误旁证
  本身升级为合同PASS。

### 10.6 exact6、roots、argv、resource、Temp与状态上限无回归

- 第12至15节的exact6 identity/byte/path/set closure、唯一config、forbidden alias、absolute argv、pytest rootdir、
  PSI WorkingDirectory、pytest环境隔离和逐cmdlet括号规则继续有效。
- evidence/temp roots、fresh absent+ignored、ordinary/non-reparse ancestors、containment与no-clobber exact一次创建未变；
  本轮root创建仍为0。
- focused→Ruff→mypy→existing config node→scope、first-failure/UNRUN/no-retry、priority/affinity/environment、
  known-child/Python residue、failure preserve和Temp精确删除权限均未漂移。
- 真实bar/data/economic/business/trial继续exact0；完整产品阶段的最高状态仍只是
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`。

### 10.7 缺陷分级与续验裁定

- P0：0；
- P1：1；
- P2：0。

第16节最终裁定：`REVIEW_FAIL`。

该FAIL只针对第16节文本旁证的PowerShell字符串/regex语义，不推翻raw-byte权威算法、历史control-evidence mismatch
定性或第7至9节PASS。经理修正或删除文本旁证、并由同一review链fresh复验前，禁止启动新outer；必须继续保持
`PYTHON0 / ROOT_CREATE0 / DATA0 / TRIAL0`。

## 11. 第16/17节文本TW旁证废止续验

### 11.1 续验范围、输入快照与历史保留

中央批准同一原reviewer继续复验第16/17节；本节完整保留第10节
`REVIEW_FAIL / P0=0 / P1=1 / P2=0`及其最小复现，只判断错误文本算法是否已彻底不可达、raw-byte算法是否成为
唯一authority，以及其余合同是否无漂移。写入本节前exact6为：

| path | bytes | SHA-256 |
|---|---:|---|
| taskbook第17节版本 | 38060 | `854e184347f2daa7ae8f9677304d73624d5799e2164e3704225ea518c70f3ed6` |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` |
| delivery | 5970 | `2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792` |
| 第16节FAIL review | 49293 | `4df08fafbcbb1034fe857522d47c00936be257db687bfce77d81a2bd7e194cf5` |

第17节逐字保留上一轮review identity、raw hit 0、错误text hit 38及`t`/backtick/tab反例，没有改写失败历史。
写入本节后review identity必然变化；final bytes/SHA作为detached identity随本次续验交回，未来outer不得继续绑定
49293-byte predecessor。

本轮唯一写入既有review；taskbook、production、test、config和delivery保持只读。未启动Parser carrier、创建root、
取得资源或调用Windows Python、pytest、Ruff、mypy、data、economic/business I/O、trial、stage、commit。现场保持
`STATIC_ONLY / CPU_NONE / PYTHON0 / ROOT_CREATE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / STAGE0 / COMMIT0`。

### 11.2 错误文本正则与双算法路径已废止——PASS

- 第16节原三步文本split/regex/pipeline合同已删除，改为明确引用第17节永久废止；历史pattern
  `'[ `t]+$'`只在第17节的缺陷记录中作为VOID证据出现，不是可执行outer路径。
- 第17节禁止全部文本regex TW旁证、文本split、regex匹配和raw/text双算法比较；同时禁止`TrimEnd`、Unicode
  whitespace、shell pipeline或第三套fallback。
- 因此不再存在“raw结果正确但错误text旁证造成持续mismatch”的运行分支。上一轮P1的最小修复采用删除多余
  算法，而非再次修补字符串转义，避免形成第二事实来源。

上一轮P1已闭合；历史pattern保留不等于重新授权它执行。

### 11.3 唯一raw-byte TW authority——PASS

第17节只允许以下固定链：

1. `ReadAllBytes`读取冻结文件raw bytes；
2. 以0x0A为唯一行边界；
3. 每行仅从LF前向左回扫连续0x20或0x09；
4. 输出total hit count；每个命中输出1-based line number、trailing-byte count和suffix hex；
5. 当前taskbook expected hit count=0。

该链不经过文本解码、regex或pipeline，且非零结果具有line/count/hex可复算证据。当前exact6逐文件按相同raw语义
静态回扫均为`RAW_TW_HITS=0`，包括38060-byte taskbook和49293-byte predecessor review；TW0现场闭合。

### 11.4 固定对抗反例——PASS

只读raw-byte合成反例结果为：

- `0x74 0x0A`（普通ASCII字母`t`结尾）：hit 0；
- `0x60 0x0A`（literal backtick结尾）：hit 0；
- `0x09 0x0A`（真实Tab结尾）：hit 1，`line=1,count=1,hex=09`；
- `0x20 0x0A`（ASCII space结尾）：hit 1，`line=1,count=1,hex=20`。

结果逐项满足第17节冻结条件：字母`t`和backtick不得命中，0x09必须命中；同时没有放宽0x20拒绝。任何未来实现
不能同时满足这些条件，都必须在root/Python 0-call时STOP，不能再引入regex或fallback规避。

### 11.5 control mismatch历史、全零与outer同源无回归

- 第16节历史35-count仍正确定性为
  `VALIDATION_CONTROL_EVIDENCE_MISMATCH / TRAILING_WHITESPACE_COUNTER_PRECEDENCE_ERROR /
  PRODUCT_NOT_EVALUATED`；本轮PASS不把它改写为产品attempt或产品失败。
- Evidence/Temp roots继续absent，Python、resource、data、economic/business I/O与trial均为0；历史错误outer和本轮
  静态复验均不计产品attempt。
- 完整outer的Parser input、actual execution source与run-contract source bytes/SHA逐字同源继续有效；raw算法只能
  存在于该同源完整source中，不能parse后替换。

### 11.6 exact6、roots、outer、product与权限边界无漂移

- actual untracked set保持exact6、cached0；六条文件identity/strict UTF-8/no-BOM/LF-only/CR0/NUL0/TW0/
  single-EOF-LF/ordinary/non-reparse/containment均闭合。ordinary diff-check仍只是coverage0旁证。
- 唯一ninth-batch config、forbidden alias、absolute product argv、pytest rootdir、PSI WorkingDirectory、pytest环境隔离、
  root-collision双括号和逐cmdlet括号规则保持不变。
- roots的fresh absent+ignored、containment、no-clobber exact一次创建，focused→Ruff→mypy→existing config node→scope、
  first-failure/UNRUN/no-retry、resource恢复、failure preserve与Temp精确删除权限均未放宽。
- 真实bar/data/economic/business/trial继续exact0；完整产品阶段状态上限仍只是
  `R15_WINDOWS_DEVELOPMENT_VALIDATED / DATA0 / ECONOMIC_IO0 / TRIAL0`。

### 11.7 缺陷分级与续验裁定

- P0：0；
- P1：0；
- P2：0。

第16/17节最终裁定：`REVIEW_PASS`。

该PASS关闭第10节P1但保留其历史，仅证明文本TW旁证已VOID且唯一raw-byte合同静态闭合；它不是outer Parser、
product stages、resource release、Temp cleanup或Windows Validation的运行证据。中央启动新outer前仍须使用写入后
final exact6与完整outer source fresh闭合；Temp删除继续需要精确用户授权。

## 12. Validation1产品阶段原生证据独立复核

### 12.1 复核范围、身份与STATIC_ONLY边界

本节由未参与实现的独立reviewer追加，承接任务书§18与交付报告§7；只读复核既有原生证据、当前worktree身份和
exact6字节，不重跑、不补造、不删除、不提交。复核前HEAD为
`dfe49df5e8dfd9d929eb8ad196beced1da19715d`，branch为
`codex/m2-research-r15-alpha101-011-vwap-volume-extremes`。现场保持
`STATIC_ONLY / CPU0 / PYTHON0 / TEST0 / RUFF0 / MYPY0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / ROOT_CREATE0 / STAGE0 / COMMIT0`。

写入本节前review identity为 `55044 bytes / 2f01cadb218f0f8e581796f8507a8cab4ccd603f8a38289c4345a7f63e588a21`；
本次仅追加本review，final bytes/SHA在本节写入后作为detached identity回交，不能把前置review identity继续绑定到后续outer。

### 12.2 exact6、scope与过程证据——PASS

当前业务exact6仍为恰好六个untracked路径、cached=0，无第七个业务路径：taskbook、production、test、config、delivery
及本review。逐文件fresh raw-byte复核结果如下：

| path | bytes | SHA-256 | hygiene |
|---|---:|---|---|
| taskbook | 41206 | `969b0e10fd898cb16e17c548230b1870c07a6d2eef67cdf8ec3eb9336efc3821` | BOM/CR/NUL/TW=0, EOF LF |
| production | 9676 | `fd16e86edd9ef63a98d6b446f1e310b543b9a98537309f03b87587223e809d6a` | BOM/CR/NUL/TW=0, EOF LF |
| test | 21770 | `3e1eb14ee0ae37aac9179f285fe49714870d5e218f546f7bf5e76689e09c8476` | BOM/CR/NUL/TW=0, EOF LF |
| config | 3227 | `633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674` | BOM/CR/NUL/TW=0, EOF LF |
| delivery | 10419 | `8cc6f20a4316193cec08a1bc8b731a246e2360357247764564cdc399ba9ae17f` | BOM/CR/NUL/TW=0, EOF LF |
| review (pre-write) | 55044 | `2f01cadb218f0f8e581796f8507a8cab4ccd603f8a38289c4345a7f63e588a21` | BOM/CR/NUL/TW=0, EOF LF |

普通 `git diff --check` 为 exit 0，但exact6全untracked，故对exact6 coverage=0，语义只能是
`VACUOUS_FOR_EXACT6`，不能升级为exact6 whitespace PASS。taskbook、production、test、config、delivery当前身份与
任务书/交付报告声明一致，未发现旧scope哈希误套到更新文档。

### 12.3 Validation1阶段证据——PASS（仅Windows开发反馈环）

既有证据逐项闭合为：focused unit `23 passed`、Ruff `All checks passed!`、mypy production `Success`、config/cold
identity `1 passed`；对应四个exit均为0，stderr均为0。run_contract、scope_exact6、scope及resource_release的
bytes/SHA与任务书§18/交付§7一致。scope明确记录actual exact6全untracked、cached0和ordinary diff-check
`VACUOUS_FOR_EXACT6`；resource_release只证明既有退出记录，不冒充本次fresh资源验证。

### 12.4 保留现场与状态上限——PASS（按合同保留）

Evidence root存在且只读枚举到四阶段stdout/stderr/exit、run_contract、scope及resource证据；Validation1 Temp仍存在。
summary、terminal、manifest-last缺失，正符合任务书§13.4在未获精确删除授权时的单一终态规则；不补证、不删除Temp、
不创建第二终态、不重跑产品阶段。因而最终状态严格保持
`R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE / ECONOMIC_UNASSESSED / TRIAL0`，不是完整Windows Gate。

### 12.5 实现静态反例挑战

独立挑战：在同一最终session，让symbol A只有gap-max/gap-min有效而volume-delta缺失，让symbol B只有volume-delta
有效而gap-extrema缺失；三个组件的有效集合均不能互相借用，A、B最终值都必须为null，不能因为横截面其它组件有两个
有效值而产生rank或乘积。production先对每个组件独立rank，再要求三项rank同时非null，静态路径满足该fail-closed规则。
该反例不依赖既有零端点或单一组件rank测试，专门挑战组件有效集合串用。另一个身份挑战是将历史delivery SHA套到当前追加后的delivery；当前delivery fresh为10419/
`8cc6f20a4316193cec08a1bc8b731a246e2360357247764564cdc399ba9ae17f`，因此旧5970-byte identity不得复用。

### 12.6 缺陷分级与裁定

- P0：0；
- P1：0；
- P2：0。

独立证据复核裁定：`REVIEW_PASS`。该PASS只确认任务书/交付§18/§7所述原生Windows开发反馈环证据、当前exact6身份和
保留现场一致；不证明Linux/WSL Gate、因子经济有效性、RankIC、Sharpe、成本容量、promotion、PAPER或LIVE。Temp清理
继续需要精确用户授权，经济评价继续等待public receipt与独立runner/run任务书。
