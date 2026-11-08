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

