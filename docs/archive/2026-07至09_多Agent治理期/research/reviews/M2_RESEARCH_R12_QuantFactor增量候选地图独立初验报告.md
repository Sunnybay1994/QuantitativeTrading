# M2-RESEARCH-R12 Quant Factor 增量候选地图独立初验报告

- task id：`M2-RESEARCH-R12-QUANT-FACTOR-CANDIDATE-MAP`
- review conclusion：`REVIEW_FAIL / P0=0 / P1=1 / P2=0`
- conclusion ceiling：`CANDIDATE_MAP_REVIEW_FAIL`；不授权修改taskbook、实现、回测、trial、stage或commit。
- resource boundary：`STATIC_ONLY / PYTHON0 / DATA0 / ECONOMIC_IO0 / NETWORK0 / TRIAL_DELTA0 / STAGE0 / COMMIT0`。

## 1. Fresh身份与范围

- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r12-quant-factor-candidate-map`
- branch：`codex/m2-research-r12-quant-factor-candidate-map`
- HEAD/base：`df02b75169b23f011b6af214bd34c708d3869372`
- taskbook：22,135 bytes；SHA-256 `72dabb35a08cb2ff62d0c59398d3da7bbaf7350b6f2a93db6fb8e82365f3b203`
- delivery：450,940 bytes；SHA-256 `421bf6be74297610249c8ff8d02e2f52638dc2a1ffc8c1f99ec5292f474b13f3`
- reviewer启动前，review路径不存在；taskbook与delivery是exact两个untracked scoped文件，cached=0，`git diff --check`通过。
- 本审查仅使用Git CLI、PowerShell与tracked静态文本；未运行Python、import、测试、Ruff、mypy、编译器、网络、data/raw/clean/run/evidence/ledger读取、经济I/O或trial。

## 2. 独立重建证据

### 2.1 Reference manifest与唯一CSV exception

以base tree逐项执行exact lookup、对象类型、blob size及blob bytes SHA-256复核：manifest exact24、路径unique24；23项manifest SHA与Git blob bytes SHA完全一致，bad=0。

唯一exception严格闭合：

- path：`04_QIML_2024/qiml_2024_factor_registry.csv`
- blob OID：`d02ecaabe270754aad733c759d6dc22b17a448bd`
- size：`338737`
- blob SHA-256：`3ab000df4a23c474e073ade8ba81b249fc022abfa6b950ca4771c4ef6df7dbfe`
- manifest历史working-tree CRLF摘要：`b677ab168c86c94ac2ce3da3d5fd32bdb56f14eb0f3b50bd837d0f03ff91894d`

`b677...`未参与该CSV Gate，未扩大exception、未normalize、未改reference/EOL。

### 2.2 exact985、唯一键、排序与计数

独立按15列ledger行解析：rows=985，`(source_library, source_entry_id)` unique=985，duplicate=0；source顺序无逆序，稳定保持`ALPHA101 → ALPHA158 → ALPHA360 → QIML_2024`。

- 四源：101 / 158 / 360 / 366，总计985。
- 四态：READY 8 / NEEDS 582 / REDUNDANT 23 / STOP 372，总计985。
- Alpha101：READY 8 / NEEDS 84 / REDUNDANT 5 / STOP 4，总计101。
- READY exact成员与顺序：`001, 002, 004, 005, 007, 009, 010, 011`；8个不同canonical family，未超过上限。

八张卡均包含公式与未来primary复核点、字段/时点/warm-up、方向未冻结、约束及至少三个反例、未来最小包和经济读取前P0边界；队列按静态可执行性而非收益排序，未见本地RankIC/Sharpe/收益或实盘推荐宣称。

### 2.3 五行REWORK3修正

ledger、five-row correction表、REDUNDANT索引三处一致：

- `alpha101_006/012/041` → `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:<id>`；`REDUNDANT`；`PROJECT_IDENTITY_R18_TRIAL_CONSUMED;R18_UNASSESSED_HOLD`。
- `alpha101_033/101` → `src/quant/factors/classic.py:<id>`；`REDUNDANT`；`PROJECT_IDENTITY_CLASSIC_FACTOR`。

before均为`NONE_FOUND_STATICALLY / NEEDS_DATA_CONTRACT`，after及派生计数已机械闭合；R18 slots未恢复。

### 2.4 四源locator抽样与L0-L3

每源回源至少5项：

- ALPHA101：#001、#002、#004、#033、#101。公式、heading、delay-1/next-open边界与ledger一致；#033及#101已有classic identity，正确为REDUNDANT。
- ALPHA158：OPEN0、ROC20、STD20、KMID2、VSUMD20。OPEN0与#033只记近似L1且不直接REDUNDANT；KMID2与#101仅L3；14个20日项目identity中抽查ROC20/STD20/VSUMD20闭合。
- ALPHA360：CLOSE0、OPEN0、CLOSE20、VWAP0、VOLUME0。CLOSE0常数STOP，VOLUME0近常数STOP；OPEN0/VWAP0与Alpha158为L0，CLOSE20保守登记Alpha158 L2路径。
- QIML_2024：2024-01-01至2024-01-05。date/page locator均回到对应月册；文本明确摘要级、参数/方向/时点需primary复核，ledger全部保守STOP。01-01与01-02可登记反转同族，但不能从摘要升级L0/L1或READY。

### 2.5 delay/PIT/intraday/summary-only反例

- delay-0：`alpha101_042`为`UNFROZEN_OR_UNSAFE / STOP / DELAY0_UNSAFE`，未错误升级READY。
- PIT：QIML `2024-01-03/04`需要financial PIT且仅摘要级，均STOP。
- intraday/summary-only：QIML `2024-01-05`需要intraday/tick-L2且公式不唯一，STOP。

上述均说明地图没有用字段名、daily proxy或完整收盘后假定收盘成交来错误升级READY。

## 3. 新增对抗反例

### ADV-R12-MAX-NAME-COLLISION

构造两个名字都含`MAX20`但经济定义不同的候选：Qlib Alpha158 `MAX20 = Max(high,20)/close`，项目R15为`max_daily_return_20 = max(20个有符号日简单收益)`。若仅按名字把两者标L0/REDUNDANT，会制造假同式；若因公式不同就把Qlib条目的project overlap写成`NONE_FOUND_STATICALLY`，又会漏掉已有MAX lineage。正确处理是保留非L0关系，同时在`project_overlap`登记R15/MAX lineage及“公式/单位/机制不同”的L2/L3或边界reason。

该反例不是delivery §6列出的delay-0、R18或Alpha158确定性派生反例，且直接暴露以下P1。

## 4. Findings

### P1-R12-1：`alpha158_max20`漏配已有R15/MAX project overlap

- 现象：ledger中`alpha158_max20`写为`dedup_level=NONE`、`project_overlap=NONE_FOUND_STATICALLY`、`NEEDS_DATA_CONTRACT`；但允许只读范围内的`docs/research/M2_MAX彩票偏好因子假设卡.md`及`docs/research/agent/M2_FROZEN_R15_冻结Clean_MAX纠偏重放任务与交付记录.md`明确存在MAX/R15 lineage，并专节说明其与Qlib Alpha158 MAX20的公式、单位和机制边界。任务书§7要求逐项检查MAX overlap，§10把已有R18/MAX/ETF/PIT却误报`NONE_FOUND_STATICALLY`定为必须捕获的反例，并规定project-overlap漏配必须REVIEW_FAIL。
- 根因：delivery把“不是L0同式”错误压缩成“没有project overlap”。`project_overlap`不仅登记L0/L1重复，还须登记已有候选/任务/run lineage；静态非同式只能决定不可直接REDUNDANT，不能抹去R15关联。
- 应遵循规则：保留Qlib MAX20与`max_daily_return_20`公式不同、不可L0/L1合并的边界；同时把`project_overlap`指向exact R15/MAX lineage，并用稳定reason说明同名异式及关系级别。不得因此改成REDUNDANT、恢复trial或宣称任一MAX有效。
- 最小复现：读取delivery中`alpha158_max20`行；再读取`M2_MAX彩票偏好因子假设卡.md`§1—§3与R15记录§1—§2。前者明确Qlib `Max(high,20)/close`，后者冻结已有`max_daily_return_20` lineage，足以反证`NONE_FOUND_STATICALLY`。
- 通过条件：同一原Worker仅修正既有delivery中`alpha158_max20`的project overlap、关系/reason及必要索引/派生汇总；保持disposition符合“非L0/L1、不因名字直接冗余”的合同。随后由同一独立reviewer复验985守恒、READY8不漂移、所有project overlap扫描无同类漏配。

## 5. 历史与执行边界

delivery永久保留首轮`MANIFEST_RAW_DIGEST_DRIFT_UNDER_AUTOCRLF`、REWORK1 `STATIC_DELIVERY_REWORK1_PREWRITE_CONTRACT_STOP`及原生`Not a valid object name`边界、REWORK2 mixed-representation CSV STOP，以及各轮delivery/五行写入0和Python/data/network/economic I/O/trial/stage/commit 0事实。本review没有删除或重解释这些历史。

## 6. 结论

`REVIEW_FAIL / P0=0 / P1=1 / P2=0`

Manifest、CSV exception、exact985、计数、五行修正、READY8与零执行边界均通过独立静态复核；但`alpha158_max20`违反任务书明确的project-overlap合同，因此不能给出`CANDIDATE_MAP_REVIEW_PASS`。返工必须回同一原Worker；reviewer不得修改taskbook、delivery或任何生产路径。

## 7. REWORK4独立复验

本节追加于首轮`REVIEW_FAIL / P0=0 / P1=1 / P2=0`之后；首轮finding、最小复现及`ADV-R12-MAX-NAME-COLLISION`均永久保留，不改写为首轮PASS。

### 7.1 Fresh身份与唯一P1闭包

- taskbook：24,649 bytes；SHA-256 `43f6a090c7851da1021fdf72161c49fc1d4acb565190a4611e36e9da8d4ed581`。
- delivery：452,033 bytes；SHA-256 `161edecbbe2360e02de0e9f351ee14e02ac1b313fca2a1205bd09a184b8b922f`。
- 复验前既有review：7,779 bytes；SHA-256 `593e9c3c9770276f63a405158a038e29229bd37352acd3bcdf7b83d2c5f735c5`。
- HEAD/base与branch仍为`df02b75169b23f011b6af214bd34c708d3869372`、`codex/m2-research-r12-quant-factor-candidate-map`。

`alpha158_max20`在REWORK4修正表、project-overlap索引和exact985 ledger中一致闭合为：

- `dedup_level=L3`
- `project_overlap=M2-FROZEN-R15:max_daily_return_20`
- `disposition=NEEDS_DATA_CONTRACT`
- `reason_codes=FORMULA_UNIT_MECHANISM_DIFFERENT;PROJECT_LINEAGE_R15_MAX_NAME_COLLISION`

Alpha158 `MAX20 = Max(high,20)/close`使用价格高点相对当前收盘；R15 `max_daily_return_20`使用20日窗口内复权收盘日简单收益最大值。两者公式、输入单位和经济含义不同，只能登记同名/极值型价格机制的L3 project lineage，禁止L0、L1、REDUNDANT或经济等价推断。首轮P1-R12-1已按冻结合同关闭。

### 7.2 无回归复验

- ledger仍为exact985、unique985、duplicate0，四源101/158/360/366；四态READY8/NEEDS582/REDUNDANT23/STOP372。
- READY成员和顺序仍为`alpha101_001/002/004/005/007/009/010/011`，八张卡的公式、时点、方向未冻结、反例和未来最小包未漂移。
- 五行Alpha101 REWORK仍精确保持：006/012/041指向R18且`REDUNDANT`、`R18_UNASSESSED_HOLD`；033/101指向classic identity且`REDUNDANT`。
- base Git blob manifest仍为24项：23项manifest SHA逐项MATCH，唯一CSV严格匹配冻结path/OID/size/blob SHA，bad=0。
- 对比冻结REWORK4范围，除`alpha158_max20`行、其机械correction表/project-overlap索引及任务书新增§14外，未发现候选、计数、卡片或历史边界漂移。
- 首轮manifest STOP、REWORK1原生object-name STOP、REWORK2 CSV mixed-representation STOP、首轮review FAIL和新增对抗反例均保留。

### 7.3 REWORK4结论

`REVIEW_PASS / P0=0 / P1=0 / P2=0`

允许的结论上限仅为`CANDIDATE_MAP_REVIEW_PASS`。本复验不授权修改taskbook/delivery/reference，不授权实现、回测、economic I/O、trial、stage或commit；后续仍须中央执行其安全提交与集成闭环。
