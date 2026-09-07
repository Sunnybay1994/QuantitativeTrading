# M2 ETF exact11 隔离总回报补数 R1

## 1. 状态、职责和现场

- task_id：`M2-ETF-EXACT11-ISOLATED-TOTAL-RETURN-BACKFILL-R1`。
- 当前状态：`TASKBOOK_READY / INPUT_INVENTORY_PENDING / EXECUTION_UNRUN`。
- 本轮准入基线：`main@e4f169c03bbc92698e78e119f4cd58e9872141b8`；共享根为 `F:\AI_Coding\QuantitativeTrading`。
- 本轮唯一写路径为本任务书；不创建 worktree、Worker、运行目录或证据，不读取真实 data，不运行 Python/网络。
- 建议后续 branch：`codex/m2-etf-exact11-isolated-total-return-backfill-r1`；建议 worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-etf-exact11-isolated-total-return-backfill-r1`。均由中央另行创建并冻结；如基线变化，中央先审计源码/配置差异并明确新 base，不自动采用 latest。
- 框架/data 经理负责数据接口、任务合同、唯一实现链与技术验收；投研经理负责经济口径和结果验收；中央负责共享写锁、网络/data I/O/CPU 租约、提交合流。此前将投研经理笼统称为数据执行负责人的表述，以本职责划分为准。
- 用户已批准 exact11 截至 2026-08-31、既有来源、隔离输出的价格与分红补齐，不再次索取同一业务批准。该批准不等于本轮已取得运行资源。

## 2. 目标与冻结口径

产出一个可独立核验、保留旧历史的 `TOTAL_RETURN_DIVIDEND` 研究价格候选；成功上限 `ISOLATED_TOTAL_RETURN_CANDIDATE_VALIDATED`，不等于 canonical 发布、FWD readiness 或策略有效性。

exact11 按以下顺序处理，集合与顺序不得漂移：

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

权威配置为 `configs/research/m2_s2_volatility_target_forward.toml` 的 data/universe，并交叉核对其引用的 `configs/research/m2_s2_volatility_target.toml`。来源冻结为 historical_raw_price_source=`akshare_sina`、incremental_raw_price_source=`baostock`、dividend_source=`akshare_sina`。这允许既有历史/增量双来源，禁止临时换源。

历史重建请求范围固定 2023-01-01 至 2026-08-31；现有历史锚点截至 2026-07-10。报告中的每证券 851 个观测、首日 2023-01-03 只是待复核输入，不冒充本轮数据证据。新增价格请求固定 2026-07-11 至 2026-08-31；闭市日由已验证 SH/SZ 日历排除，不推测交易日数量。实际 historical first observation 若与已报告锚点冲突即 STOP，不改首日以迁就结果。

## 3. 可复用源码与已确认限制

- `src/quant/data/connectors/baostock.py`：`BaostockConnector.fetch_reference_bar_raw`，逐证券、daily、adjustflag=`3`、fields 必须等于源码既有 `_BAR_FIELDS`。该接口返回 raw，不自动附加 `_request_symbol`；后续窄数据编排需显式绑定请求证券并保留原列。
- `src/quant/data/reprocess_etf_total_return.py`：`ArchivedEtfTotalReturnConnector` 接受显式 raw 文件列表，在线取得新浪累计分红，并保留价格 raw 引用。它不对重叠 raw 去重，不能把有重复日期的两份输入直接拼入。
- `src/quant/data/mappers.py`：`AkshareResearchPriceMapper` 按传入序列首日 close 和累计收益构造总回报尺度；必须旧 raw 加新增 raw，完整历史一次 map，禁止增量窗口单算后接旧值。
- `src/quant/data/research_price.py`：`ResearchPriceUpdatePipeline` 先 raw 后质量门禁再 clean；`validate_research_prices` 只检查 expected 减 actual 的缺失，不能单独证明没有额外 symbol/date。
- `src/quant/data/storage.py`：`CleanResearchPriceStore.upsert` 会替换既有证券日；只能指向本任务全新隔离候选目录，绝不指向 canonical。
- `src/quant/data/calendar.py`：`expected_open_dates` 从 data-root 下 SH/SZ 日历读取并要求自然日完整覆盖及沪深开市集合一致。隔离 CLI 不能在没有日历的空 data-root 直接使用；应消费已验证只读日历获得 expected_dates，再向隔离 stores 编排，或在后续合同中显式冻结日历的逐字隔离副本。
- 禁止使用 `update_research_price` 作为本包补数入口：其 HFQ 优先/失败 fallback 会改变来源与调整口径。

所有源码、上述两个配置、解释器与 SDK 版本/文件身份，需在执行准入中记录 Git blob、实际 SHA256/size；本轮未声称依赖可运行。不得新增通用 carrier、复用已关闭 receipt/诊断承载链或修改研究公式。

## 4. 第一资源申请：只读真实输入 inventory

状态 `RESOURCE_REQUEST / DATA_READ_ONLY`。中央先冻结允许的精确路径清单及读取窗口，才可执行。当前不扫描 data 来猜路径。

待批准定位范围仅为 canonical `F:\AI_Coding\QuantitativeTrading\data\clean\research_price_1d` 中日期 2023-01-01 至 2026-07-10 的分区、`data\clean\trade_calendar\market=SH\data.parquet`、`market=SZ\data.parquet`，以及由既有来源记录明确引用的价格 raw/metadata。raw 尚无完整清单，不能填虚构路径或用 latest/glob 搜索全 data。若引用不能定位，先提交待扩大只读清单，保持 `INPUT_INVENTORY_INCOMPLETE`。

inventory 必须形成：

1. 每个旧 raw 的绝对路径、metadata、来源/endpoint、请求范围、size/SHA256/mtime、schema、证券日期集合，以及其到旧 clean 的来源关联；全部使用显式清单，覆盖完整历史，不只找最后一个 raw。
2. exact11 旧 clean 的完整逐值投影与分区文件身份；记录额外证券但不将它们纳入候选。需核首末日、851 观测声明、唯一键、调整方法、source 与 2026-07-10 close。
3. SH/SZ 日历在完整重建区间的日期唯一性、自然日覆盖、is_open 类型和相等开市集合；日历缺口 STOP，本包不自动联网补日历。
4. 旧 raw 在 2026-01-01 来源切换附近的覆盖、重复、close 和已有分红/总回报证据；冲突不得通过任意取 first/last 去重。
5. 原分红留档或旧重建输入中的 `_cash_dividend` 证据；其路径与身份。若无法证明旧分红闭包，明确缺口，禁止把新返回的空表当成无分红证明。
6. canonical 价格分区与日历完整文件集合的 pre manifest（相对路径 Ordinal 排序、size/SHA256/mtime）；运行后逐项复算，要求集合与身份不变。只在批准范围内核验，不扫描其他业务数据。

inventory 完成后由投研经理确认历史口径，中央冻结具体 input manifest、网络端点/调用上限、执行 argv、输出路径及资源，再进入采集；当前任务书不是含未解析路径的可运行命令。

## 5. 后续隔离输出与写白名单建议

以下绝对路径为待中央准入的建议，启动前必须 absent、ignored、ordinary/non-reparse ancestors、完整路径精确相等；任一存在即 STOP，不采用或覆盖：

```text
F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-etf-exact11-isolated-total-return-backfill-r1
F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-etf-exact11-isolated-total-return-backfill-r1\raw
F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-etf-exact11-isolated-total-return-backfill-r1\candidate
```

唯一运行根下分离原始价格、原始分红、派生输入、candidate/clean/research_price_1d、质量与验证报告。精确文件名/允许集合由 inventory 后的执行冻结确定，不由 Worker 临时扩展。所有新增文件 no-clobber；失败保留 partial，禁止原地修补、resume、删除或覆盖。既有 raw/clean/calendar 均只读。

后续文档候选 exact3：本 taskbook、`docs/framework/deliveries/M2_ETF_EXACT11_IsolatedTotalReturnBackfillR1交付报告.md`、`docs/framework/reviews/M2_ETF_EXACT11_IsolatedTotalReturnBackfillR1独立初验报告.md`。当前仅 taskbook 可写。现有 CLI 无法直接保证分红原响应独立留档和本包额外集合门禁；如需窄 quant.data 编排及定向测试，经理先提交精确生产/测试写集由中央批准，不隐含授权 Worker 新建脚本。

## 6. 后续执行顺序与资源申请

单一 Worker/单一 writer，独立 reviewer 使用不同上下文。当前不派发。

1. 输入 inventory 及合同复核 PASS；冻结 raw manifest 和运行依赖。
2. fixture 自测与独立审查证明隔离写入、完整尺度、分红原始响应留档和验收门禁。
3. 取得唯一 Windows CPU/网络/data I/O 租约后，fresh 核输入/根不存在/资源；解释器建议 `D:\Miniforge3\python.exe`，实际 identity 待冻结，cwd 为获批 worktree，PYTHONPATH 为其 src，BelowNormal/0xF00、线程最多 2、单进程串行。
4. exact11 每证券一项 BaoStock daily unadjusted 请求，成功即独立留档，最多 11 项价格请求；不得中途失败后重新整批采集。仅消费明确请求范围；SDK 超时/内部重试能力须在执行前审计并冻结，不能假称已有硬时限。
5. exact11 新浪分红请求逐项留存原始响应和请求身份；最多 11 项业务请求。现有 `_fetch_dividend_events` 内含最多三次重试，不能未经裁定直接调用并声称单次请求；本包要求首请求异常 STOP，后续窄编排需明确禁用额外尝试或重新提交可审计调用预算。
6. 以显式旧 raw 清单与新增 raw 构成完整无重复价格输入；新旧价格区间互斥。分红差分按完整累计事件序列求得，再按交易日应用；未来日期事件不参与截止日前价格，异常/歧义/旧事件修订 STOP。
7. 先通过下述 mapper 前 raw gate 和显式 source 绑定，再复用 mapper/schema/quality，完整历史一次重建，仅写隔离候选；执行 §7 全部验证。
8. pre/post canonical 与输入身份复核、资源恢复、进程释放、证据/终态闭合；投研经理验收结果，独立 reviewer 验证，中央决定后续发布任务。

网络仅已有 BaoStock 价格和 AKShare/Sina 分红来源；实际 SDK 端点、版本、timeout、总时限和日志脱敏须在运行前冻结，禁止安装包或使用新来源。资源失败不得分类为经济/产品失败。无 CPU 租约时不运行 Python。保存真实 priority/affinity，finally 恢复，线程限制采用子进程环境；原生 stdout/stderr/exit 与每阶段首失败、UNRUN、调用计数/已写路径持久化。使用获批现有执行通道，不开发新承载平台。

## 7. 验收标准与命令边界

开发命令仅在另授 Windows 开发资源后运行，当前全部 UNRUN：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_reprocess_etf_total_return.py tests/integration/test_research_price_pipeline.py -q
```

如新增窄编排，先冻结其 exact tests/Ruff/mypy argv 再实现；上述旧测试不是本包全部成功证据。真实重建暂不列伪可执行 CLI：raw 清单、依赖和日历身份未完成，执行命令必须在下一准入逐项具体化。

候选验收必须全部满足：

- mapper 前 raw gate：每条必需 raw_close 均检查字段存在、非 null、严格数值转换成功、有限且大于零；missing/非法文本/NaN/Inf/零负值立即 STOP。cash_dividend 字段必须存在，每条值均非 null、转换合法、有限且非负；累计分红原值与差分也必须有限非负。只有已留档原始响应及覆盖证据明确证明该证券该日期 no-event，才可在事件到价格日期的显式映射中赋零，并保留证明关联；空响应、缺字段或未知覆盖不等于 no-event。禁止以 `strict=False`、`gross_return.fill_null(1.0)` 或 `_cash_dividend.fill_null(0.0)` 让坏输入通过；既有 mapper 内部此类逻辑不能替代调用前 gate，失败时 mapper 0-call。
- source 绑定：inventory 同时记录旧 clean.source 的实际逐组值和新 connector/mapper 的实际 source，并核其与冻结历史/增量/分红来源的映射。运行前显式绑定经审查的 source；不得依赖隔离目录 `path.parts` 自动推断来源，不得为通过重叠比较伪写旧 source。实际来源或 source 标签映射冲突即 `SOURCE_CONTRACT_STOP`；现有 connector 的路径推断不构成本包的来源权威。
- 实际 `(symbol, trade_date)` 集合严格等于 exact11 与已验证开市日期的笛卡尔积，双向差集均空；截止 2026-08-31，不能只依赖 quality.passed。
- 唯一键无重复；价格无 null/NaN/Inf/非正；类型、source、adjustment_method 经领域 Schema 验证；每证券逐日期完整覆盖，任一缺行不能前值填充。
- 旧区间与 canonical exact11 同日期 adjusted_close 逐值数值相等；不设置事后容差，不按比例归一化掩盖差异。source/调整口径保持原合同；不比较新旧 parquet 二进制相等。
- 2026-07-10 至下一有效日按 mapper 既有现金分红收益公式递推，验证价差/分红输入和累计尺度；不要求市场收益为零或用任意涨跌阈值代替公式一致性。
- 完整事件序列日期/累计金额合法，重复或歧义事件 STOP，累计分红非单调 STOP；旧事件和已留档输入一致，新窗口分红具备原始响应证据。分红日未落入可用价格日期的事件须显式拒绝/交投研解释，不静默丢弃。
- canonical clean/calendar、全部旧 raw pre/post 文件集合、size/SHA/mtime 不变；候选/原始响应/验证报告的 SHA 与调用清单闭合。
- 退出后无本任务活动 writer/子进程，资源恢复有证据。失败候选永久保留且标记不可消费。

## 8. 必须覆盖的反例与 STOP

fixture 至少覆盖：额外第12证券、截止后日期、缺一个开市日、重复 key、NaN/Inf/零负价格；旧 raw 重叠冲突；仅新增窗口重建导致尺度重置；旧区间同大小字节篡改；历史分红修订/负增量/重复事件/空响应歧义；source 改成 HFQ；日期集缺口；isolated root 已存在或 reparse；采集第 k 项异常后后续请求 0-call；写入失败保留 raw 和 partial；canonical pre/post 漂移。

补充成对反例：bad/NULL close 与正常 close；缺 cash 字段、null cash、非有限累计/差分均拒绝，而具有原始覆盖证明的 no-event 可显式零；隔离目录改名导致 connector 推断 source 漂移须拒绝；手工伪写旧 source 不得通过。必须证明坏输入在 mapper 前被拒，不能仅检测最后 adjusted_close 是否有限。

首失败立即 STOP，后续 UNRUN，不重试、换源、删除或修复；分别记录 INPUT_INVENTORY_INCOMPLETE、SOURCE_CONTRACT_STOP、ACQUISITION_STOP、CANDIDATE_VALIDATION_STOP、RESOURCE_STOP，不能统称数据已完成。预算或资源未冻结时保持 EXECUTION_UNRUN。报告保留现象、根因、规则、最小复现、修正要求与通过条件。

## 9. 禁止项及交付边界

禁止 canonical 发布/upsert、覆盖旧历史、修改研究配置/因子/策略、回测、trial、FWD 信号生成、labels、PAPER/LIVE/交易；禁止改 HFQ、仅增量独算拼接、新数据源、宽泛 data 扫描、通用 carrier、receipt 已关闭链的恢复。香港主题 ETF 是沪深上市 exact11 成员，不构成 licensed HK 数据采购授权。

当前交付仅任务书。后续交付报告列实际输入/输出身份、命令/调用次数、原生 exit、通过/失败/UNRUN 和资源释放，独立初验重点挑战尺度与集合闭包；中央另行 SAFE_COMMIT/integration。Windows 候选验证不关闭 Linux Gate，也不自动解锁研究消费者。

迟到历史重建必须记录真实 retrieved_at 和候选生成时间，保留来源历史时间与本次采集时间的区别。2026-08-31 是数据截止日，不是本次产物当时已可用的证明；不得声称当日已知、已发 signal 或 2026-09-01 已成交。后续 prospective 观察须另冻新的 as_of 与 next-open，不能用本候选倒签或恢复已错过的观察窗口。

## 10. 经济口径审查返工历史

原版本 13879 bytes / SHA256 `9bd355668a53c2f4b18d9d581f059357b862be89e7f44c832a1f900e6c538287` 经投研经理只读审查为 REVIEW_FAIL。现象是末端价格检查不足以排除 mapper 填充值掩盖坏 raw、缺少迟到重建时间声明、隔离路径可影响 source 推断。根因是输入经济有效性、可知时间和来源身份未分别形成前置门禁。本次只修任务书：§6/§7 冻结 mapper 前逐值拒绝与 source 显式绑定，§8 补区分未知与已证明无事件的反例，§9 冻结真实时间。通过条件为三项经独立只读复验闭合，且原 exact11/完整历史/隔离/不发布不 trial 范围不变。全部数据、网络、Python、执行验证继续 UNRUN。
