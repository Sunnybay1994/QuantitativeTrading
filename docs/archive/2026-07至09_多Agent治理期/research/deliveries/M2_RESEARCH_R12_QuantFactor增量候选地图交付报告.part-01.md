# M2-RESEARCH-R12 Quant Factor 增量候选地图：静态审计交付

- task id：M2-RESEARCH-R12-QUANT-FACTOR-CANDIDATE-MAP
- audit scope：指定 worktree、任务书冻结 reference pack、项目 tracked 源码/配置/测试/研究文档的静态文本与 Git/metadata 读取。
- terminal state：STATIC_INVENTORY / ECONOMIC_IO0 / TRIAL_DELTA0 / MANIFEST_GIT_BLOB_CLOSED_WITH_SINGLE_CSV_EXCEPTION
- conclusion ceiling：候选地图可冻结；不代表任何因子本地有效、已实现、可回测或可交易。
- taskbook identity：24,649 bytes；SHA256 43f6a090c7851da1021fdf72161c49fc1d4acb565190a4611e36e9da8d4ed581。
- reference manifest：以 base `df02b75169b23f011b6af214bd34c708d3869372` 的 Git blob 为权威身份，24 项中 23 项 manifest↔blob 完全匹配；CSV 保留唯一 taskbook exception（OID/size/blob SHA 已在 §8.1 列明），23 个 Markdown 的 working-tree CRLF 仅作历史 EOL 诊断；2024/2026 分层未混用；985=101+158+360+366。
- 历史 STOP 保留：首轮 `MANIFEST_RAW_DIGEST_DRIFT_UNDER_AUTOCRLF`；REWORK1 `STATIC_DELIVERY_REWORK1_PREWRITE_CONTRACT_STOP`；REWORK2 `STATIC_DELIVERY_REWORK2_PREWRITE_CONTRACT_STOP`。本次 REWORK3 仅解除 manifest 当前 terminal STOP，不删除历史事实。

## 1. 计数守恒与交叉表

|source|count|
|---|---:|
|ALPHA101|101|
|ALPHA158|158|
|ALPHA360|360|
|QIML_2024|366|
|TOTAL|985|

|source/disposition|count|
|---|---:|
|ALPHA101 / READY_FOR_TASKBOOK|8|
|ALPHA101 / NEEDS_DATA_CONTRACT|84|
|ALPHA101 / REDUNDANT|5|
|ALPHA101 / STOP|4|
|ALPHA158 / READY_FOR_TASKBOOK|0|
|ALPHA158 / NEEDS_DATA_CONTRACT|144|
|ALPHA158 / REDUNDANT|14|
|ALPHA158 / STOP|0|
|ALPHA360 / READY_FOR_TASKBOOK|0|
|ALPHA360 / NEEDS_DATA_CONTRACT|354|
|ALPHA360 / REDUNDANT|4|
|ALPHA360 / STOP|2|
|QIML_2024 / READY_FOR_TASKBOOK|0|
|QIML_2024 / NEEDS_DATA_CONTRACT|0|
|QIML_2024 / REDUNDANT|0|
|QIML_2024 / STOP|366|
|TOTAL / READY_FOR_TASKBOOK|8|
|TOTAL / NEEDS_DATA_CONTRACT|582|
|TOTAL / REDUNDANT|23|
|TOTAL / STOP|372|
|TOTAL|985|

|data_domain|count|
|---|---:|
|daily OHLCV|693|
|financial PIT|76|
|intraday;tick/L2|168|
|analyst|8|
|text;alternative|28|
|ownership|12|
|TOTAL|985|

|mechanism_family|count|
|---|---:|
|价量|394|
|统计/序列表示|133|
|反转|39|
|流动性|99|
|波动/低风险|54|
|动量|18|
|成交活跃|36|
|订单流|56|
|情绪|28|
|质量|30|
|成长|30|
|预期|8|
|所有权/资金流|12|
|价值|9|
|规模|6|
|投资|7|
|TOTAL|985|

### 四态判定

READY_FOR_TASKBOOK 仅用于首批 8 个、各占一个 canonical family：资料包公式可回到 primary/official 复核，daily clean 字段语义可承载，时点可写成 close-known → next-open，且静态未闭合 L0/L1 项目重合。NEEDS_DATA_CONTRACT 聚类登记字段/调整/窗口/方向合同尚未冻结；不把字段名存在写成 coverage。REDUNDANT 仅用于明确项目 identity 或 L0/L1；L2/L3 仅登记关系。QIML 2024 全部保守 STOP，因为资料包明确为摘要级 OCR/转写，关键公式不能唯一恢复。

## 2. L0-L3 与项目 overlap 索引

|level|static relation|entries / retained identity|
|---|---|---|
|L0|同式或退化常量|Alpha158 14 个已冻结 20 日 identity；Alpha360 OPEN0/HIGH0/LOW0/VWAP0 → Alpha158 同式；CLOSE0 与 VOLUME0 保守 STOP|
|L1|严格单调/反向排序或同方向等价|Alpha101 #033 → `src/quant/factors/classic.py:alpha101_033`；#101 → `src/quant/factors/classic.py:alpha101_101`；Alpha158 OPEN0 → #033 仅近等价，未升级为 REDUNDANT|
|L2|可推导/路径关系，未宣称经验冗余|Alpha360 lagged OHLC/VWAP/VOLUME blocks → Alpha158/日频路径；QIML 日频技术条目可由经典路径部分推导|
|L3|同机制或近似结构，需数值增量证据|Alpha158 KMID2 ↔ Alpha101 #101；Alpha158 MAX20 ↔ `M2-FROZEN-R15:max_daily_return_20`（同族命名/极值机制关联，但公式、单位、经济含义不同）；QIML 价量/波动/反转族 ↔ classic families；不得写成相关或持仓重合|

明确 project overlap：alpha101_006/012/041 指向 R18 frozen trial identity，仍保持 UNASSESSED/HOLD，不恢复 slots；alpha101_033/101 指向 classic production identities；14 个 Alpha158 20 日条目指向对应 classic batch identities；alpha158_max20 指向 `M2-FROZEN-R15:max_daily_return_20`，仅为 L3 关系，禁止升级为 L0/L1/REDUNDANT；其余 NONE_FOUND_STATICALLY 只表示本次允许静态输入内未找到闭合 identity。

## 3. 首批 READY 卡片（8 个 family，上限闭合）

以下是研发可执行性优先级，不是收益/Alpha/Sharpe 排名；每张卡都必须在经济读取前另写 taskbook，方向与阈值仍未冻结。

|candidate_family_id|source alias|mechanism / falsifiable hypothesis|package formula / source recheck|direction / fields / timing|main constraints and adversarial cases|future minimum package|
|---|---|---|---|---|---|---|
|alpha101_f001|alpha101_001|下行波动冲击后的极值状态可能区分持续风险与短期回归；若触发率/方向跨期不稳则否证|rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5；01A Alpha #001；回到原论文/官方实现复核|TWO_SIDED_TO_FREEZE；open/high/low/close/volume/amount/adj_factor；as_of收盘，最早next-open；warm-up≥20且极值再需5|连续涨跌停；波动制度突变；上市历史不足/并列值过多|taskbook；source verification；clean-bar window/null tests；config/doc|
|alpha101_f002|alpha101_002|成交量变化与日内收益背离可能提供独立价量信息；若被成本或低流动性吞噬则否证|-1*correlation(rank(delta(log(volume),2)),rank((close-open)/open),6)；01A Alpha #002；回原 primary 复核|TWO_SIDED_TO_FREEZE；daily OHLCV；close→next-open；warm-up≥6|零成交/分母近零；大宗或指数调仓；全市场单边行情|taskbook；volume-unit/epsilon contract；adversarial tests; config/doc|
|alpha101_f004|alpha101_004|低价近期位置的反转假设；强趋势或永久重估应否证|-1*Ts_Rank(rank(low),9)；01A Alpha #004；回原 primary 复核|TWO_SIDED_TO_FREEZE；daily OHLCV；close→next-open；warm-up≥9|除权错误；涨跌停；低价并列导致信号退化|taskbook；adjustment/rank contract；tests; config/doc|
|alpha101_f005|alpha101_005|开盘偏离历史 VWAP 与收盘偏离当日 VWAP 的联合反转；若 VWAP 代理/成本改变结果则否证|rank(open-sum(vwap,10)/10)*(-1*abs(rank(close-vwap)))；01A Alpha #005；回原 primary 复核|TWO_SIDED_TO_FREEZE；OHLCV+amount 推导 VWAP；close→next-open；warm-up≥10|amount=0；VWAP单位误配；强单边重估|taskbook；VWAP derivation/unit contract；tests; config/doc|
|alpha101_f007|alpha101_007|放量条件下 7 日价格变动的条件反转；触发率不足或状态漂移则否证|(adv20<volume)?(-ts_rank(abs(delta(close,7)),60)*sign(delta(close,7))):-1；01A Alpha #007；回原 primary 复核|TWO_SIDED_TO_FREEZE；OHLCV；close→next-open；warm-up≥60|条件触发过稀；成交量单位/停牌；离散信号拥挤|taskbook；condition/trigger/null contract；tests; config/doc|
|alpha101_f009|alpha101_009|连续同向日与普通噪声的状态切换；状态边界不稳定则否证|(0<ts_min(delta(close,1),5))?delta(close,1):((ts_max(delta(close,1),5)<0)?delta(close,1):-delta(close,1))；01A Alpha #009；回原 primary 复核|TWO_SIDED_TO_FREEZE；OHLCV；close→next-open；warm-up≥5|状态快速切换；平盘/停牌；T+1与涨跌停|taskbook；state-machine contract；tests; config/doc|
|alpha101_f010|alpha101_010|#009 的 4 日短窗排序版本；若只复制 #009 或样本外方向不稳则否证|rank(conditioned delta(close,1))；01A Alpha #010；回原 primary 复核|TWO_SIDED_TO_FREEZE；OHLCV；close→next-open；warm-up≥4|与 #009 近似；并列排名；极短窗噪声|taskbook；dedup probe; state/rank tests; config/doc|
|alpha101_f011|alpha101_011|VWAP-收盘极值与成交量变化联合反转；若量价口径或成本不稳则否证|(rank(ts_max(vwap-close,3))+rank(ts_min(vwap-close,3)))*rank(delta(volume,3))；01A Alpha #011；回原 primary 复核|TWO_SIDED_TO_FREEZE；OHLCV+amount→VWAP；close→next-open；warm-up≥3|VWAP缺失/零量；成交量跳变；连续涨跌停|taskbook；VWAP/volume unit contract；tests; config/doc|

## 4. NEEDS_DATA_CONTRACT 聚类

- daily_bar_adjustment_window：Alpha101 非首批 84 条与 Alpha158 未覆盖 144 条；需要逐式 primary 复核、复权/单位、窗口 warm-up、缺失/停牌和方向冻结；不得因 Bar1d 字段名存在而升级。
- alpha360_sequence_contract：354 条 lagged path entries；需冻结 60 日序列列序、复权前置、lag=0 边界、停牌掩码和模型输入形状。
- QIML 2024 不进入 NEEDS 聚类而全部 STOP：摘要级公式先恢复 primary/official 后重新建包。

## 5. REDUNDANT 映射

- Alpha101：alpha101_006/012/041 → `M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_006/012/041`；alpha101_033 → `src/quant/factors/classic.py:alpha101_033`；alpha101_101 → `src/quant/factors/classic.py:alpha101_101`。R18 三项仍 UNASSESSED/HOLD，不表示有效或无效。
- Alpha158：ROC20→alpha158_roc20、STD20→alpha158_std20、RSV20→alpha158_rsv20、VMA20→alpha158_vma20、MA20→alpha158_ma20、CORR20→alpha158_corr20、WVMA20→alpha158_wvma20、BETA20→alpha158_beta20、RSQR20→alpha158_rsqr20、CORD20→alpha158_cord20、SUMD20→alpha158_sumd20、RESI20→alpha158_resi20、IMXD20→alpha158_imxd20、VSUMD20→alpha158_vsumd20。
- Alpha360：lag 0 OPEN/HIGH/LOW/VWAP are L0 aliases to Alpha158 same-form entries; no production claim for unimplemented blocks.

## 6. STOP 汇总与反例

- DELAY0_UNSAFE：Alpha101 #042/#048/#053/#054；资料包明确 delay-0，不能在当前 close→next-open contract 下静态升级。
- DEGENERATE_CONSTANT / DEGENERATE_NEAR_CONSTANT：Alpha360 CLOSE0/VOLUME0；不把近常数特征当独立 long-only signal。
- FORMULA_NOT_UNIQUE;SUMMARY_ONLY_REQUIRES_PRIMARY：QIML_2024 366 entries；每条可由 date/page locator 追溯，但必须回到扫描原页/引用研报恢复精确参数、单位、方向、时点和缺失规则。
- adversarial static checks retained：若把 delay-0 写成 READY、把 R18 identity 写成 NONE_FOUND_STATICALLY、把 Alpha158 SUMD/CNTD 等确定性派生误作新 family，均应 REVIEW_FAIL。任何静态 L2/L3 关系不得改写为经验相关/RankIC/Sharpe/收益/实盘推荐。

## 7. 未执行证据、下一步与边界

- PYTHON_COUNT=0、IMPORT_COUNT=0、TEST_COUNT=0、RUFF_COUNT=0、MYPY_COUNT=0。
- DATA_READ_COUNT=0（未读 data/raw/clean/parquet/run/ledger/evidence/account）；ECONOMIC_IO_COUNT=0、NETWORK_COUNT=0、TRIAL_DELTA=0、STAGE=0、COMMIT=0。
- 唯一允许写入路径为本 delivery；未修改 taskbook/reference pack/roadmap/shared report/code/config/test/review。
- 下一步仅允许逐候选 taskbook 或数据合同；不得一次实现 8 个候选。
- public summary/static map are not local validity evidence; no local RankIC/Sharpe/return/live recommendation is made.

## 8. 审计现场与校验状态

ACTUAL_EXACT2=2；CACHED_COUNT=0；DIFF_CHECK=PASS；WORKTREE=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-research-r12-quant-factor-candidate-map；OWNER=unique read-only audit Worker；MANIFEST_GATE=GIT_BLOB_CLOSED_SINGLE_CSV_EXCEPTION；HISTORY_STOP_PRESERVED=YES；PYTHON/DATA/NETWORK/ECONOMIC_IO/TRIAL/STAGE/COMMIT=0。

### 8.1 Git blob manifest closure (REWORK3)

Base commit：`df02b75169b23f011b6af214bd34c708d3869372`。每行均为该 base 的 exact tree lookup、`git cat-file -s` size 与 `git cat-file blob` 原始 bytes SHA-256；CSV 的 manifest SHA 为 working-tree CRLF 历史诊断，按 taskbook 唯一 exception 以 base blob SHA 判定。

|path|base blob OID|size|blob bytes SHA-256|result|
|---|---|---:|---|---|
|00_因子体系与评估框架.md|d384e9db2f5c6209359ae69d2af8a7d265c31910|21152|55a16938f2b37cbc82a31954eb0912ff9387890d58528d33a365e2f6f43987a5|MATCH|
|01A_Alpha101_001-050.md|2bc28e3ff7d9929eeb49ffd6e943eef61b0d54ba|66086|878c358e8ddbe5588942dfd18ca43b3fddc40136abb63899436a75330dbd4281|MATCH|
|01B_Alpha101_051-101.md|4fe96e20d1045ca52b94ed657309f13d80b791a7|71816|823f995e28ee2a8505d3d6cacb3ef4ee7104d052d3c3021f762b73bb727443a7|MATCH|
|02_Qlib_Alpha158_完整清单与分析.md|80fdda7844f7f68e6d6cb38c0dbbc44ff1d02ec6|22780|bc7d30772fdd6c69ecbba05ac49f08e64d329815ecad16e96d6ac8d0a80dfd1a|MATCH|
|03_Qlib_Alpha360_完整清单与分析.md|ee93a33d6363b55bb1d1086947807c54452220e7|33633|d85ad0968b5ca7c19a2cec62d0032244320283024d0d7590b2cf8e1e2020310f|MATCH|
|04_QIML_2024/01_一月.md|49d13640a0188fc16560b05d6269dcebe28efd4c|43212|cffab3a09a217a4f84f26d6be9a9d205ee88f771b70129f4c33b9b628334a6dd|MATCH|
|04_QIML_2024/02_二月.md|43a45b825742274f0371017b98e9d2e1b6c3e819|40095|f7a9fa0d9b870464ee940680ece5eedcb81aec03e0cbc288508b3dab8d2f3492|MATCH|
|04_QIML_2024/03_三月.md|9e214b05528e62dabd6162d70308ed2fe1681c71|43945|6e7c9e540872cc91c28c3b2bbc81ef67cc6d130e76d9f96534bc15f70cc0caac|MATCH|
|04_QIML_2024/04_四月.md|ade13dfa2162ae72bdc43a26e083b903fc88ea53|42602|3f3698e4f6154e2a6a17bb4dc10449747b0dc9b8e41b3a581fe3f8804dc2b405|MATCH|
|04_QIML_2024/05_五月.md|c337d02fa7fbab9f7034924ab7adf29e5bafb59b|43534|a1ba5de166391cac9aa514554194c37d3ce3ba69911bdb25e467eaeda5f64131|MATCH|
|04_QIML_2024/06_六月.md|7b5b0340a1d2dbd9a34839ceebc3cf46363c5471|42094|e797076855286ceba943f2b3eeac72193b452188caa2f171044f0d634e533d82|MATCH|
|04_QIML_2024/07_七月.md|440cbc40679f180e5d6a96d8033d4831c2ad56fd|42988|50683d59c325995b137ff6e20ff5424af168085b7570a84fd965f5aa59eaa0a7|MATCH|
|04_QIML_2024/08_八月.md|91b90bb7e8a58193de63a4644167226a6a083f3e|42876|376586fa2d3d5bb3c8d8e61eccdd3e633b9cd7c33a00b9025b6c26439b5c71b1|MATCH|
|04_QIML_2024/09_九月.md|08a818dab2ad1454f3b1684bfdb366c2ab50a68e|41116|9a76c6a899f38428b067d5e95d5b95e9037e4fbe4124d9f6d9f686a5b65af0db|MATCH|
|04_QIML_2024/10_十月.md|c235727f83f8ca5a10ac030fb3a554dd3248e3cb|43180|a15b68809709d9e0d90d0016e3291e0d83f03cd0c65b87d7c48fa8ad64d263ed|MATCH|
|04_QIML_2024/11_十一月.md|f3f3a59b4b080225330799591793fc95a5334b6b|41870|2aea66458eec81726b7d7d641650280cf318fac4310ae6187a28b09a2e2fc815|MATCH|
|04_QIML_2024/12_十二月.md|6a972cee523d3dd2d75d41bbfd49a114db3062e2|43241|8ce6deba6627cca2bcc2e4a04d21d3133ec22992d7a3f72db0afbc65f523d53c|MATCH|
|04_QIML_2024/README.md|0980c9f02950f6c40b4eb78e9b8c9ff421b265a2|7431|e09feb4029fa255deb35981a52644da426b24d1e8957cd3f5104326ee713ee69|MATCH|
|04_QIML_2024/qiml_2024_factor_registry.csv|d02ecaabe270754aad733c759d6dc22b17a448bd|338737|3ab000df4a23c474e073ade8ba81b249fc022abfa6b950ca4771c4ef6df7dbfe|CSV_EXCEPTION_ALLOWED_BY_TASKBOOK|
|04_QIML_2024/qiml_2024_factor_registry.json|632509ae480a5e90ff7772ae6f2ee16c6eebe335|453853|8ac331e01f3dc9cd9e95ced067674cbe5d2d6ed937c3133f3d1e02ee200cd1d4|MATCH|
|04_QIML_2026因子日历_公开可核验子集.md|7f07dd503a93d6c3d99f6dbd1864f84f8aeb78de|13416|b16df407aafba54af53543e7dcab56eeee39f877e3a8c75af56c7a4ef3fadba7|MATCH|
|05_跨因子库去重与组合框架.md|ed34854570129d07ad7ffe3f7fb486ed8e0f2c34|12499|2025b13c865d4dfe35d3f8e17ae046517c9caf89f38576f11b52e12975a57c71|MATCH|
|06_参考文献与证据索引.md|39d8dc1d09ada41999e6184371c9c07a02864126|4663|c1854cc5fb6b45dd9872fcba5ff0b2f1c406e6866140f4f1bc8a06cb0b492b1e|MATCH|
|README.md|ce2c0070f259f8a1085d1f9b1fec60551a020b0f|2847|d3f89b1fb6fab1844703e80cfe6c0017d325452e7249bfdff78d904530859dea|MATCH|

### 8.2 Five-row exact correction (REWORK3)

|source entry|before project_overlap|before disposition|after project_overlap|after disposition|after reason code|
|---|---|---|---|---|---|
|alpha101_006|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_006|REDUNDANT|PROJECT_IDENTITY_R18_TRIAL_CONSUMED;R18_UNASSESSED_HOLD|
|alpha101_012|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_012|REDUNDANT|PROJECT_IDENTITY_R18_TRIAL_CONSUMED;R18_UNASSESSED_HOLD|
|alpha101_041|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|M2-WAVEB-R18-ALPHA101-PRICE-VOLUME-GEOMETRY:alpha101_041|REDUNDANT|PROJECT_IDENTITY_R18_TRIAL_CONSUMED;R18_UNASSESSED_HOLD|
|alpha101_033|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|src/quant/factors/classic.py:alpha101_033|REDUNDANT|PROJECT_IDENTITY_CLASSIC_FACTOR|
|alpha101_101|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|src/quant/factors/classic.py:alpha101_101|REDUNDANT|PROJECT_IDENTITY_CLASSIC_FACTOR|

### 8.3 alpha158_max20 exact correction (REWORK4)

|source entry|before dedup_level|before project_overlap|before disposition|before reason codes|after dedup_level|after project_overlap|after disposition|after reason codes|
|---|---|---|---|---|---|---|---|---|
|alpha158_max20|NONE|NONE_FOUND_STATICALLY|NEEDS_DATA_CONTRACT|QUEUE_CAP_DEFERRED;DAILY_SCHEMA_CONTRACT|L3|M2-FROZEN-R15:max_daily_return_20|NEEDS_DATA_CONTRACT|FORMULA_UNIT_MECHANISM_DIFFERENT;PROJECT_LINEAGE_R15_MAX_NAME_COLLISION|

Alpha158 `MAX20 = Max(high,20)/close` 与项目 R15 `max_daily_return_20`（20 日窗口内复权收盘日收益最大值）仅存在同族命名与极值型价格机制关联；公式、输入单位和经济含义不同。该行保持 `NEEDS_DATA_CONTRACT`，不得解释为 L0/L1 等价或 REDUNDANT。

## Appendix A. exact985 raw-entry ledger

