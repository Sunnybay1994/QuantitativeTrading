# M2-RESEARCH-R12：Quant Factor 增量候选地图任务书

> task id：`M2-RESEARCH-R12-QUANT-FACTOR-CANDIDATE-MAP`
>
> domain：research
>
> 当前阶段：`TASKBOOK_REWORK1 / STATIC_INVENTORY / ECONOMIC_IO0 / TRIAL_DELTA0`
>
> 结论上限：`CANDIDATE_MAP_FROZEN`，不等于因子有效、实现就绪或允许回测

## 1. 目标

本任务把 `docs/research/references/quant_factor_research_v2/` 中登记的985个原始条目，与当前项目已经实现、
运行、拒绝、HOLD、预注册或等待数据合同的因子和策略逐项对齐，形成一个可维护的增量候选地图。

本任务解决的是“下一步研究什么、为什么、还缺什么”，不是“从985条中挑历史回测最好的一条”。输出必须：

1. 对原始条目计数 `101 + 158 + 360 + 366 = 985` 完整守恒；
2. 使用L0—L3关系、数据与时间可得性、A股交易约束、成本/容量和当前项目冗余做静态分类；
3. 把每个条目归入exact四态之一：
   `READY_FOR_TASKBOOK / NEEDS_DATA_CONTRACT / REDUNDANT / STOP`；
4. 从静态可执行且非冗余条目中形成一个有上界的小型候选队列，供未来逐包预注册；
5. 明确公开资料、静态公式和本任务地图都不是本地RankIC、Sharpe、收益或实盘有效性证据。

## 2. 权威现场与所有权

- base/HEAD：`df02b75169b23f011b6af214bd34c708d3869372`；
- branch：`codex/m2-research-r12-quant-factor-candidate-map`；
- worktree：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r12-quant-factor-candidate-map`；
- manager当前唯一写路径：
  `docs/research/tasks/M2_RESEARCH_R12_QuantFactor增量候选地图任务书.md`。

中央后续另行批准后，唯一静态审计Worker只允许写：

`docs/research/deliveries/M2_RESEARCH_R12_QuantFactor增量候选地图交付报告.md`

不同上下文的唯一独立reviewer只允许写：

`docs/research/reviews/M2_RESEARCH_R12_QuantFactor增量候选地图独立初验报告.md`

roadmap、shared dirty progress report、reference pack、代码、配置、测试、现有taskbook/delivery/review和Git状态
全部只读。实现、审查和合流权限不由本任务书自动产生。

## 3. 只读SSOT与输入范围

### 3.1 因子资料包

Worker必须以当前base下的下列tracked文件为唯一资料包，不从网络、缓存、Notebook或其他版本补公式：

- `docs/research/references/quant_factor_research_v2/README.md`；
- `docs/research/references/quant_factor_research_v2/MANIFEST_SHA256.txt`；
- `00_因子体系与评估框架.md`；
- `01A_Alpha101_001-050.md`；
- `01B_Alpha101_051-101.md`；
- `02_Qlib_Alpha158_完整清单与分析.md`；
- `03_Qlib_Alpha360_完整清单与分析.md`；
- `04_QIML_2024/README.md`、12个月分册、`qiml_2024_factor_registry.csv/json`；
- `04_QIML_2026因子日历_公开可核验子集.md`只作来源边界旁证，不增加985分母；
- `05_跨因子库去重与组合框架.md`；
- `06_参考文献与证据索引.md`。

`MANIFEST_SHA256.txt`中的tracked文件摘要必须fresh逐项复核；missing、extra、digest drift、985计数漂移或2024/2026
混用立即STOP。不得把2024扫描摘要改写为已核原研报的生产公式。

本包自REWORK1起，tracked reference输入的跨checkout权威身份唯一改冻为base commit中的Git blob bytes：对manifest
列出的每个路径，必须以base `df02b75169b23f011b6af214bd34c708d3869372`做exact tree lookup，记录blob object id、
`git cat-file -s`字节数，并对`git cat-file blob`返回的原始blob bytes计算SHA-256，与manifest冻结摘要逐项比较。
路径不在该commit、对象类型不是blob、manifest缺/重/额外路径、blob size或SHA不匹配均立即STOP。

Windows working-tree raw bytes只允许作为checkout/EOL展示诊断，不是跨`core.autocrlf`环境的合同身份。禁止修改
reference文件、转换EOL、以working-tree LF规范化后的摘要替代manifest摘要，或把“23个Markdown规范化后匹配”
冒充原任务书raw working-tree Gate通过。Git blob身份与manifest逐项闭合后，才可解除本轮
`MANIFEST_RAW_DIGEST_DRIFT_UNDER_AUTOCRLF`；若Git blob闭包失败，保持STOP。

### 3.2 项目当前能力与历史

只允许定向读取：

- `docs/research/投研评价指标与市场状态研究方法.md`；
- `docs/research/tasks/`、`docs/research/deliveries/`、`docs/research/reviews/`中当前M2因子/策略包；
- `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md`；
- `src/quant/factors/`、`src/quant/research/`、`configs/research/`与对应单元测试的tracked源码；
- `src/quant/domain/schemas.py`和`src/quant/domain/enums.py`，只用于确认clean字段与领域枚举；
- `pyproject.toml`，只用于依赖声明边界。

禁止读取research run、Parquet、data、raw、clean、ledger、artifact/evidence、ignored/cache、账户或外部状态；禁止
import、执行CLI、运行测试或由源码名称推断真实数据coverage。发布契约字段存在不等于本地数据READY。

## 4. 原始条目身份与守恒

### 4.1 exact四源

| source_library | source id域 | exact count |
|---|---|---:|
| `ALPHA101` | `alpha101_001`—`alpha101_101` | 101 |
| `ALPHA158` | 资料包列出的158个维度，保留原名称与窗口 | 158 |
| `ALPHA360` | 资料包列出的6类×60日维度，保留原名称与lag | 360 |
| `QIML_2024` | registry中的366个唯一自然日条目 | 366 |
| **TOTAL** | 不含QIML 2026旁证项 | **985** |

Worker必须在delivery中给出完整raw-entry ledger。每个source entry出现exact一次，键为
`(source_library, source_entry_id)`；禁止删行、重复、用family行冒充entry行或把同式别名从985分母消失。

允许在Markdown附录中用紧凑CSV code block表示ledger，但每行至少包含第5节exact列。按
`ALPHA101 → ALPHA158 → ALPHA360 → QIML_2024`及各自原始顺序稳定排序。

### 4.2 canonical family不改变raw分母

L0/L1合并只改变`canonical_family_id`与disposition，不改变raw count。L2/L3关系只登记机制/推导关系；在没有
执行数值证据时不得宣称经验相关、Partial IC或持仓重合已经成立。

## 5. raw-entry ledger exact schema

每行exact列、顺序为：

1. `source_library`
2. `source_entry_id`
3. `source_locator`
4. `canonical_family_id`
5. `mechanism_family`
6. `data_domain`
7. `timing_class`
8. `minimum_fields`
9. `formula_authority`
10. `direction_candidate`
11. `dedup_level`
12. `project_overlap`
13. `disposition`
14. `reason_codes`
15. `next_minimum_package`

字段合同：

- `source_locator`必须精确到tracked相对路径及可稳定定位的标题/原始编号；
- `canonical_family_id`为lowercase稳定标识，只表达静态同族，不是假定生产factor id；
- `mechanism_family`仅可从价值、质量、投资、成长、动量、反转、波动/低风险、高阶矩、流动性、成交活跃、
  价量、订单流、筹码、预期、情绪、所有权/资金流、事件、宏观/跨资产、统计/序列表示中选择；
- `data_domain`必须列出daily OHLCV、daily basic、financial PIT、intraday、tick/L2、text、analyst、ownership、
  macro/alternative等实际所需域，不以“可计算”掩盖缺域；
- `timing_class`至少区分`CLOSE_KNOWN_NEXT_OPEN`、`PIT_ANNOUNCEMENT_NEXT_OPEN`、
  `INTRADAY_COMPLETED_BAR`、`EVENT_TIMESTAMP_REQUIRED`、`UNFROZEN_OR_UNSAFE`；
- `minimum_fields`只列字段语义，不声称本地存在或coverage通过；
- `formula_authority`只可为`EXACT_PRIMARY_OR_OFFICIAL`、`REFERENCE_PACKAGE_EXACT`、
  `SUMMARY_ONLY_REQUIRES_PRIMARY_CHECK`、`AMBIGUOUS_OR_INCOMPLETE`；
- `direction_candidate`只可为`+1`、`-1`、`TWO_SIDED_TO_FREEZE`、`NOT_APPLICABLE`；它不是已运行方向；
- `dedup_level`只可为`NONE / L0 / L1 / L2 / L3`；
- `project_overlap`必须指向已有factor/task/run lineage，或exact `NONE_FOUND_STATICALLY`；
- `reason_codes`为稳定、排序、去重的code列表；
- `next_minimum_package`只能登记未来taskbook/data-contract/source-verification动作，不得包含执行命令。

## 6. exact disposition与reason codes

### 6.1 `READY_FOR_TASKBOOK`

只有全部满足才可使用：

1. 公式至少为`REFERENCE_PACKAGE_EXACT`，且未来taskbook能够回到primary/official来源复核；
2. required data domain已有项目Schema/受控repository候选，且不需要delay-0、未来label或未完成bar；
3. 可以明确`as_of → next-open`或更保守时点；
4. 未被现有因子、R18、MAX、ETF策略或已冻结PIT候选L0/L1覆盖；
5. 机制和主要失效反例可证伪；
6. 适合在真实成本、流动性、long-only与当前universe下形成独立任务书。

`READY_FOR_TASKBOOK`只代表可以继续写任务书。它不代表字段coverage、实现、trial或经济有效性READY。

### 6.2 `NEEDS_DATA_CONTRACT`

用于公式/机制足够明确，但至少一个必需数据域、PIT版本链、event timestamp、复权/单位、universe或clean字段合同
尚未闭合。典型包括financial PIT、intraday、tick/L2、分析师、文本、资金流、持仓和另类数据。

不得以daily proxy、填0、fina_indicator替代、供应商catalog或字段名存在把该状态升级。

### 6.3 `REDUNDANT`

用于静态L0/L1闭合，或项目已有同一canonical经济信号与trial identity。L2/L3通常不足以直接REDUNDANT；若因
当前模型/数据能力选择暂不保留，必须仍以L2/L3 reason说明而不能冒充同式。

R18三候选已消费trial并保持`UNASSESSED/HOLD`；把相同或单调等价公式标REDUNDANT不能恢复其slots或建立fallback。

### 6.4 `STOP`

至少包括：

- 公式只有摘要转写且关键窗口/单位/方向/时点无法唯一恢复；
- 明确delay-0、future data、观察后参数、不可成交或T+1下不成立且无忠实保守解释；
- 缺少合法来源/provenance，或需要用户禁止的legacy/archive实现；
- 纯常数、确定无信息、不可稳定tokenize/计算或与目标long-only任务无经济解释；
- 只有通过结果后选域、翻方向、换窗口或忽略成本才可能成立。

## 7. 静态去重与当前项目对齐顺序

每个raw entry必须依次经过：

1. **来源闭合**：原始编号、公式权威、数据单位、窗口、delay和缺失规则；
2. **L0代数闭合**：常数化、相同表达式、同口径别名；
3. **L1排序闭合**：仿射/严格单调等价及反向等价；
4. **L2可推导登记**：如Alpha360路径可推导Alpha158摘要；只登记，不凭静态关系宣称经济冗余；
5. **L3机制登记**：动量、反转、价量、波动等同族；未来用增量证据判断；
6. **项目overlap**：已有classic factor、R18、MAX、PIT质量、ETF策略及REGIME诊断；
7. **数据/时点/成本**：current Schema、PIT、next-open、交易限制、换手、容量；
8. **disposition**：按第6节四态唯一选择。

禁止运行AST compiler、数值指纹、相关、IC、回测或模型消融。本任务中的L0/L1只能使用资料包或可逐式证明的
静态等价；无法证明时保守记L2/L3或STOP，不猜。

## 8. READY候选队列上限与卡片

为防止因子动物园，delivery中`READY_FOR_TASKBOOK`候选的canonical family最多8个；同family多个raw entry不能
占多个名额。超过8个时，不按主观收益排序，使用以下无结果优先序形成首批8个，其余保持原disposition并标
`QUEUE_CAP_DEFERRED`：

1. 现有verified daily clean与next-open链能够忠实承载；
2. 公式自由度、窗口和分支更少；
3. 与现有项目L0/L1不重合；
4. 机制可证伪且适合long-only；
5. 预计换手与容量更容易在真实成本下审计；
6. primary/official来源更容易逐字复核。

这只是研发可执行性优先级，不是预期收益排名。Worker不得给候选打Alpha分、预测Sharpe或声称“最有效”。

每个首批候选必须有exact卡片：

- `candidate_family_id`与全部source aliases；
- 经济机制与可证伪假设；
- 资料包公式、未来primary来源复核点；
- 方向候选及为何尚未成为trial方向；
- exact minimum fields、复权/单位、lookback warm-up；
- signal as_of、最早execution和horizon候选；
- target universe与long-only映射候选；
- 对已有项目的L0—L3关系；
- 预期主要换手、容量与交易约束；
- 至少三个对抗反例；
- future taskbook的最小code/test/config/doc路径候选；
- 在任何经济读取前仍须冻结的P0清单。

## 9. delivery必备汇总

delivery必须同时提供：

1. exact985 raw ledger及四源计数守恒；
2. disposition总计与按source、data domain、mechanism的交叉计数，全部加总985；
3. L0—L3关系表和当前project overlap索引；
4. 首批最多8个READY卡片；
5. `NEEDS_DATA_CONTRACT`按最小data taskbook聚类，不逐条重复同一缺口；
6. `REDUNDANT`指向canonical保留项或现有项目identity；
7. `STOP`按稳定reason code汇总并保留raw-entry可追溯性；
8. “未执行证据”清单：Python0、data0、economic I/O0、trial0、network0、run/evidence0；
9. 下一步只能是逐候选taskbook或数据合同，不得一次实现8个候选。

## 10. 独立审查合同

reviewer不得只核985算术或复述delivery。至少独立复核：

1. 从四个source各抽取至少5个entry，逐项回到source locator；
2. 复核Alpha101 #033/#101、Alpha158/360重叠及至少一个QIML同族的L0/L1/L2/L3分级；
3. 查找至少一个被错误升级为READY的delay-0/PIT/intraday/summary-only反例；
4. 查找至少一个已有R18/MAX/ETF/PIT候选但ledger误报`NONE_FOUND_STATICALLY`的反例；
5. 检查8个READY卡片是否都能在收益读取前唯一写成未来taskbook；
6. 检查计数、唯一键、排序和四态守恒；
7. 确认没有本地有效性、RankIC、Sharpe、收益或实盘推荐措辞。

任何raw entry缺失/重复、状态不唯一、来源越界、formula authority夸大、项目overlap漏配或候选上限突破均为
REVIEW_FAIL。review结论上限为`CANDIDATE_MAP_REVIEW_PASS`，不授权实现或回测。

## 11. 资源、禁止项与STOP

资源固定：

`STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / TRIAL_DELTA0 / STAGE0 / COMMIT0`

明确禁止：

- 读取任何收益、价格、calendar、financial、run、report结果或trial ledger；
- 运行Python、Notebook、SQL、DuckDB、Polars、测试、Ruff、mypy或编译器；
- 网络搜索、下载论文、安装依赖或补充第五因子库；
- 修改reference pack、方法SSOT、roadmap、dirty report、代码、配置或测试；
- 根据公开研究结论预判A股本地有效，或把国外多空结果直接转成个人long-only结论；
- 新建trial、选择方向、阈值、窗口、universe、持有期或promotion Gate；
- 一次性批准/实现整个READY队列。

任一以下情况立即STOP并记录：

- base/worktree/owner/exact路径漂移；
- reference MANIFEST、985分母或source registry不能闭合；
- 必须执行代码/数据才能判断，却试图用静态推断升级READY；
- 需要扩写新CSV/JSON/代码路径才能承载地图；
- 发现公式来源与资料包自身矛盾且无法在允许范围内裁定；
- 需要修改共享SSOT或跨域通用工具。

## 12. 当前通过条件与终态

manager阶段通过条件：

- 只写本taskbook；
- actual exact1、cached0、`git diff --check` PASS；
- UTF-8 no BOM、LF-only、CR0、NUL0、TW0、single EOF LF；
- Python/data/network/经济I/O/trial均为0。

taskbook静态复核后，中央才可批准唯一Worker写delivery；Worker完成并退出后，中央才可批准不同reviewer写review。
review PASS后仍需central safe commit、latest-main merge-tree/no-ff、scope核验和archive-first退休。

当前唯一终态为：

`TASKBOOK_PENDING_REVIEW / STATIC_INVENTORY / ECONOMIC_IO0 / TRIAL_DELTA0`

本任务不会产生可交易策略，也不会证明公开因子仍然有效。它只把后续研究自由度压缩为可审计的小型队列。

## 13. 首轮delivery STOP与REWORK1冻结合同

### 13.1 永久保留的首轮事实

唯一audit Worker首轮交付为：

- delivery：`docs/research/deliveries/M2_RESEARCH_R12_QuantFactor增量候选地图交付报告.md`；
- bytes：`445053`；
- SHA-256：`f0a4f0d0feed491052cd495fa7e1eca95879a0af657c2d2ceafff591b71dad13`；
- terminal：`STOP / STATIC_INVENTORY / ECONOMIC_IO0 / TRIAL_DELTA0 /
  MANIFEST_RAW_DIGEST_DRIFT_UNDER_AUTOCRLF`；
- ledger：exact985，四源`101 / 158 / 360 / 366`；
- 首轮四态计数：`READY8 / NEEDS587 / REDUNDANT18 / STOP372`；
- 未执行：Python0、data0、network0、economic I/O0、trial0、stage0、commit0。

首轮观察到23个Markdown working-tree raw SHA受`core.autocrlf=true`影响，而23/23在LF规范化后与manifest
匹配；CSV raw 1/1匹配。该观察只说明可能的checkout行尾差异，不推翻首轮STOP，也不得删除或改写其历史。

REWORK1首次恢复Worker后，在delivery写入前发生
`STATIC_DELIVERY_REWORK1_PREWRITE_CONTRACT_STOP`：§3.1一度误写42位Git object token
`df02b75169b23f011b30a7bbd7e0d6f65fcfe4d91c`，Git原生返回`Not a valid object name`。该次
delivery写入0，Python/data/network/economic I/O/trial均0，原Worker自然退出。此STOP属于任务书身份错误，
不是delivery内容失败或候选地图失败；不得删除、覆盖或冒充Git blob Gate已执行。

REWORK2再次恢复Worker后，在delivery写入和五行修正前发生
`STATIC_DELIVERY_REWORK2_PREWRITE_CONTRACT_STOP`：manifest的24个tracked target中23项通过base Git blob闭包，
唯一失败为`04_QIML_2024/qiml_2024_factor_registry.csv`的mixed-representation摘要。该次delivery写入0、
五行修正0，Python/data/network/economic I/O/trial/stage/commit均0，原Worker自然退出。此STOP属于reference
identity合同缺陷，不是candidate-map经济失败或候选有效性证据。

上述CSV的唯一内容authority冻结为以下base Git blob三元组：

- path：`04_QIML_2024/qiml_2024_factor_registry.csv`；
- base blob OID：`d02ecaabe270754aad733c759d6dc22b17a448bd`；
- blob size：`338737`；
- blob bytes SHA-256：`3ab000df4a23c474e073ade8ba81b249fc022abfa6b950ca4771c4ef6df7dbfe`。

manifest中的`b677ab168c86c94ac2ce3da3d5fd32bdb56f14eb0f3b50bd837d0f03ff91894d`与当前working-tree
CRLF raw bytes相同，只作历史checkout-CRLF诊断，不参与该CSV的通过判定。其他23项仍必须要求manifest SHA与
base blob bytes SHA逐项完全一致。禁止扩大exception、忽略其他摘要、自动normalize、修改manifest/CSV/EOL，
或使用working-tree内容替代blob；任一path、OID、size、blob SHA或其他23项漂移均立即STOP。

### 13.2 首轮project-overlap矛盾

首轮正文和索引已经声明：

- `alpha101_006 / alpha101_012 / alpha101_041`对应已消费`trial_delta=3`的
  `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY`身份，终态为`UNASSESSED/HOLD`且slots不恢复；
- `alpha101_033 / alpha101_101`对应`src/quant/factors/classic.py`中的既有生产因子身份；
- 将这些条目误报为`NONE_FOUND_STATICALLY`应当`REVIEW_FAIL`。

但首轮exact985 ledger的上述五行仍同时写为`project_overlap=NONE_FOUND_STATICALLY`、
`disposition=NEEDS_DATA_CONTRACT`，并使Alpha101的`REDUNDANT`计数为0。权威ledger与正文、任务书第6.3节及
第10节自相矛盾，因此当前delivery不得进入独立review，也不得把READY8当作已审查队列。

### 13.3 五行exact修正

恢复同一原audit Worker后，只允许对既有delivery做以下五行及派生计数修正：

| source entry | exact `project_overlap` | exact disposition | reason code要求 |
|---|---|---|---|
| `alpha101_006` | `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_006` | `REDUNDANT` | 必须包含`PROJECT_IDENTITY_R18_TRIAL_CONSUMED` |
| `alpha101_012` | `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_012` | `REDUNDANT` | 必须包含`PROJECT_IDENTITY_R18_TRIAL_CONSUMED` |
| `alpha101_041` | `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_041` | `REDUNDANT` | 必须包含`PROJECT_IDENTITY_R18_TRIAL_CONSUMED` |
| `alpha101_033` | `src/quant/factors/classic.py:alpha101_033` | `REDUNDANT` | 必须包含`PROJECT_IDENTITY_CLASSIC_FACTOR` |
| `alpha101_101` | `src/quant/factors/classic.py:alpha101_101` | `REDUNDANT` | 必须包含`PROJECT_IDENTITY_CLASSIC_FACTOR` |

这里的`REDUNDANT`只表示本项目已经有相同候选/实现/trial identity，不表示因子有效，也不把R18的
`UNASSESSED/HOLD`改成`REJECTED`，不恢复任何slot或建立fallback。

五行修正后，四源与四态计数必须exact闭合为：

- Alpha101：`READY8 / NEEDS84 / REDUNDANT5 / STOP4 = 101`；
- 全部985：`READY8 / NEEDS582 / REDUNDANT23 / STOP372 = 985`；
- Alpha158、Alpha360、QIML_2024各自计数保持首轮不变。

Worker必须同步修改所有由这五行机械派生的摘要、交叉表、overlap索引和STOP说明；不得改变其他980行、
READY8成员/顺序/卡片、L0—L3规则或根据收益重新选择候选。任何额外ledger行变化、READY队列变化或计数不守恒
立即STOP。

### 13.4 REWORK1最小序列与通过条件

1. 中央先静态复核本taskbook REWORK1；
2. 通过后只恢复同一原audit Worker，只写既有delivery；taskbook/reference/review及其他路径只读；
3. Worker用第3.1节Git blob合同重新闭合manifest，并报告每个tracked输入的blob id、size与SHA；
4. Worker按第13.3节修正五行和派生计数，保持Python/data/network/economic I/O/trial均为0；
5. Worker自然退出后，经理只读核新delivery identity、exact985唯一键、四源/四态计数、五行before/after和
   Git blob manifest闭包；
6. 只有上述全部通过，中央才可启用不同上下文的唯一独立reviewer。

REWORK1通过前状态固定为：

`TASKBOOK_REWORK1_PENDING_REVIEW / DELIVERY_CONTRACT_STOP / REVIEW0 / ECONOMIC_IO0 / TRIAL_DELTA0`

## 14. 独立初验P1与REWORK4冻结合同

### 14.1 永久保留的独立初验事实

REWORK3交付完成后，唯一独立reviewer形成既有review：

- path：`docs/research/reviews/M2_RESEARCH_R12_QuantFactor增量候选地图独立初验报告.md`；
- bytes：`7779`；
- SHA-256：`593e9c3c9770276f63a405158a038e29229bd37352acd3bcdf7b83d2c5f735c5`；
- terminal：`REVIEW_FAIL / P0=0 / P1=1 / P2=0`；
- 唯一对抗反例：`ADV-R12-MAX-NAME-COLLISION`。

该FAIL只暴露一处project-overlap静态漏配，不推翻已闭合的24项manifest、exact985唯一键、四源计数、
五行Alpha101修正或READY8队列，也不构成任何因子经济失败、trial或收益证据。Review历史不得删除、覆盖或
改写为首轮PASS。

### 14.2 `alpha158_max20` exact修正规则

既有ledger中的`alpha158_max20`不得继续写为`project_overlap=NONE_FOUND_STATICALLY`。它与项目R15/MAX
存在同族名称及极值型价格机制关系，但两者公式、输入单位和经济含义不同：

- Alpha158：`Max(high,20)/close`；
- 项目R15：`max_daily_return_20`，即20日窗口内复权收盘日收益的最大值。

同一原audit Worker只允许将该行及其机械派生overlap索引修正为：

- `project_overlap = M2-FROZEN-R15:max_daily_return_20`；
- `dedup_level = L3`；
- `disposition = NEEDS_DATA_CONTRACT`；
- `reason_codes`必须包含并按既有稳定规则排序：
  `FORMULA_UNIT_MECHANISM_DIFFERENT`、`PROJECT_LINEAGE_R15_MAX_NAME_COLLISION`。

这里的`L3`仅表示同族命名和机制关联，不表示公式等价。禁止把该条目标为`L0`、`L1`或`REDUNDANT`，禁止
由同名推导经济等价，也不得改变其future data-contract要求。

### 14.3 REWORK4不变量与最小序列

修正后以下事实必须逐字保持：

- READY8成员、顺序与卡片不变；
- 全部985四态仍为`READY8 / NEEDS582 / REDUNDANT23 / STOP372`；
- 其他984行、24项manifest、五行Alpha101 REWORK及其计数不变；
- Python/data/network/economic I/O/trial/stage/commit均为0。

执行顺序固定为：中央复核本taskbook后，只恢复同一原audit Worker，仅写既有delivery；Worker自然退出后，
只恢复同一原独立reviewer，仅写既有review并保留首轮FAIL历史。不得创建替代Worker/reviewer，不得修改
reference、roadmap、代码、配置、测试或共享报告。

REWORK4复验通过前状态固定为：

`TASKBOOK_REWORK4_PENDING_REVIEW / STATIC_INVENTORY / ECONOMIC_IO0 / TRIAL_DELTA0`
