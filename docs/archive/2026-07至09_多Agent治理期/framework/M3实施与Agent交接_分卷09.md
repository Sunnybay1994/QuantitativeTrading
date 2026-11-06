
上述七个 `*_raw` 方法是 G1 executor 唯一允许调用的 connector API；现有聚合型
`fetch_bar_1d/fetch_adjust_factors` 会分块并在返回前 `unique(keep="last")`，禁止在 G1 复用，否则
供应商重复键会在 raw 留档前被吞掉。raw 方法不得去重、排序、映射或附加非供应商列。
现有 `TushareBarMapper/TushareAdjustmentFactorMapper` 依赖 `_request_symbol/_market` 且 factor mapper
会删除连续相同行，因此不得复用于 G1。G1 B2B 按上文新建 bar/factor/benchmark/suspension 核心 mapper；
price-limit/dividend 归 G1-P3/B2C，B4 只重验发布，仍必须从 `VerifiedRawResponse` 注入 receipt 血缘。factor 保留每个供应商
交易日行。

月度观察转 PIT 的保守规则：

1. normalize 必须同时接收完整 `INDEX_WEIGHT` batch 与 verified responses，并在读 frame 值前重建两者；
   response request ID 多重集合必须与 batch 精确相等。每个请求覆盖一个完整自然月，月份连续且代码固定
   `000300.SH`。只传若干 response 无法证明整批没有漏月，因此不再是合法接口。
2. `trade_date` 重命名为 `observation_date`；请求月份首日不是观察日或生效日。source 固定为 `tushare`，
   不能由调用方注入。
3. 首个 CSI300 版本每个 observation 必须**恰好 300** 个唯一证券、正且 finite 权重；按 symbol 稳定排序后
   用 `math.fsum` 计算权重和并要求在 `[99,101]`，禁止依赖输入行序/线程分块的普通浮点 reduce，也不得
   round 后比较。请求范围每个自然月至少一个 observation。250–350 只作为未来其他指数的通用
   诊断范围，不能放宽当前硬门禁。若同月多 observation，全部按日期顺序保留。
4. 成员方法版本精确为 `tushare_monthly_observed_next_session_close_v1`；旧
   `tushare_monthly_observed_next_open_v1` 必须拒绝。某 observation 的成分从其**下一 SH 开市日的收盘后信号**
   起可用；不得在 observation 当日或当月月初向前回填。下一 observation 生效时，前一状态在前一 SH
   开市日结束。
5. B3 membership 只表达 signal window：与 instrument 生命周期和 `[signal_start,signal_end]` 相交；
   `list_date` 向后映射为首个 `>=` 的 SH session，`delist_date` 向前映射为最后一个 `<=` 的 SH session；相邻
   状态中持续存在的证券区间合并，调出后再调入形成两段。`effective_to` 一律非 null，最后状态精确截到
   `signal_end`。生命周期裁剪后每个 signal session 仍必须恰好 300 个资格键，否则 fail-closed。
6. signal start 的第一个开市日必须已有 warmup observation 推导出的状态，否则 G1 失败。令
   `calendar_anchor=max(max(observation_date), signal_end)`，calendar 必须同时包含并证明 anchor 之后第一个
   SH 开市日 `calendar_proof_end`，并在依赖自然日域逐日证明 SH/SZ 日期集和 `is_open` 一致；不得求并集、
   用自然次日猜 session，或因尾部缺少严格下一 session 而截断。
7. observations/membership/eligible keys 的逻辑摘要统一使用 `m3-clean-table-content-v1`：规范 JSON、显式
   scalar 类型、完整规范行排序、重复保留、`-0.0→0.0`，与 Parquet bytes 和输入行序无关。v1 只接受
   null/bool/int/finite float/date/string，datetime 明确拒绝。公开 verifier 必须从原始 batch、verified
   responses、calendar、instruments 和参数重新 normalize/build，再逐表逐 digest 比较；不能只检查 result
   内部 hex，否则整体平移一个 session 后重算 digest 的自洽伪造仍会通过。值对象构造若调用带 coercion 的
   Schema，必须把 validator 返回的三张规范 frame 写回后再基于实际公开 frame 验 digest；不得用规范结果算
   摘要却继续暴露预验证 DataFrame。

B3 配置前置已按
[`M3_G1_P2_0主Agent最终验收报告.md`](agent/M3_G1_P2_0主Agent最终验收报告.md)
通过主验。B3 的现行可执行任务书为
[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](agent/M3_G1_P2_B3PIT成员状态外部闭环任务单.md)；本节保存跨模块
业务不变量，精确错误码、文件范围、测试矩阵和外部实现—复验循环以该任务书为准。

G1 质量门禁至少包括：全部 standard Schema、选中 source 唯一、成分月完整、会员日行情/全日停牌
二选一、部分时段停牌仍要求行情、每条行情有可 as-of 的正 finite factor、OHLC/amount/volume 正且
finite、基准覆盖整个 history window、feature warmup 与 label tail 完整、重复键/截断/未知证券为
ERROR。Tushare `daily` 的停牌日无行是正常来源语义，但没有 bar 且没有全日停牌证据不能静默接受。

G1 使用两阶段身份：`primary_candidate_key` 由 `g1_config_sha256`、完整 Tushare plan/
stable response digests、calendar/instrument/标准化 clean 内容 digest、mapper/schema/membership/build
code version、dependency fingerprint 以及显式 `signal_start/signal_end/history_start/history_end` 按具名字段
规范 JSON 计算；不含 BaoStock 证据。四日期同时是 `G1Candidate` 字段，不能只藏在 opaque plan hash 中。
用该 key 按固定
hash-rank 算法先选 30 只证券，再为每只选 20 个已发布 primary bar 交易日；样本不足即失败。
证券 rank 键是规范 JSON 数组 `["m3-g1-cross-source-symbol-v1",primary_candidate_key,symbol]`
的 SHA-256，日期 rank 键是
`["m3-g1-cross-source-date-v1",primary_candidate_key,symbol,trade_date_iso]`；均按 `(hash,原值)`
升序取前 N，最终 sample keys 再按 `(symbol,trade_date)` 排序。
冻结 sample plan 后才能请求 BaoStock 不复权数据，每个参考请求也必须先 raw 留档、再形成可验真
receipt。每个入选 symbol 恰有一个 BaoStock request，区间是该 symbol 样本日的 min–max，参数固定为
`fields=date,code,open,high,low,close,volume,amount,adjustflag,tradestatus`、`frequency=d`、
`adjustflag=3`。首版参考源 executor 严格串行且不自动重试；网络失败保留 intent 并由人工重跑，
有效 receipt 则零网络复用。参考 raw 可保留区间内额外日期，对账严格只比较冻结的 600 个
`(symbol,trade_date)` 键，每键比较 OHLC 和 volume 五个值；
缺少一行按五个 mismatch 计数。价格通过条件为
`abs(primary-reference) <= price_atol + price_rtol * abs(reference)`，成交量为
`abs(primary-reference) <= volume_rtol * max(abs(reference), 1)`；`mismatch_rate`是 mismatch cell 数除以 3000，
不大于配置阈值才 PASS。最终 `release_id` 在 primary identity 上再绑定 sample plan、BaoStock stable
receipt digests 和 reconciliation detail/summary digest，因此无身份循环，也不含抓取时间或物理路径。

BaoStock executor 只接受自证的 `ReferenceRequestPlanV1`，而不是可被 caller 任意裁剪的 request sequence。
该 plan 必须把 `sample_plan_sha256` 与按 request ID 排序的 30 个完整 request spec 绑定到
`request_plan_sha256`；写任何 intent 或联网前，重算 600 个 sample key 到 30 个请求的精确闭包。P4 的
`primary_candidate_key`、sample plan、reference request plan 和 `release_id` 使用的确切 canonical JSON
envelope 以 P4 任务拆分文档为准，不得用 `repr`、位置含糊的对象或字段子集替代。

`primary_candidate_key` 是主源 candidate 的唯一内容身份；不再维护含义重叠的 `candidate_sha256`。
`publish_g1_release` 只接受 `G1ReleaseInputs`，必须从 `G1BuildInputs` 和 verified reference responses 重建
candidate、request/receipt 闭包、跨源结果和所有门禁，不接受调用方自报的 candidate、audit、`quality`
列表或 PASS 布尔值。精确的 P4A/P4B/P4C 信任边界、接口、身份 DAG、文件状态机和外部闭环以
[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](agent/M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
为准。发布目录首版固定为：

```text
data/clean/m3_g1/releases/<release_id>/
  manifest.json
  quality.json
  universe_membership.parquet
  eligible_keys.parquet
  bar_1d.parquet
  adjustment_factor.parquet
  adjustment_factor_match.parquet
  benchmark_bar_1d.parquet
  suspension_1d.parquet
  trade_calendar.parquet
  instrument.parquet
  index_constituent_observation.parquet
  price_limit_1d.parquet
  corporate_action_ledger.parquet
  corporate_action_selection_evidence.parquet
  corporate_action_reconciliation.parquet
  cross_source_reconciliation.parquet
  cross_source_reconciliation.json
```

不允许自行分区或增加普通文件。manifest 的 file table 精确列出除 manifest 自身外的所有普通文件，
不自引用；外层 snapshot/stage receipt 负责绑定 manifest bytes。manifest、quality 和 cross-source
summary 分别使用严格 `m3-g1-manifest-v1`、`m3-g1-quality-v1`、`m3-g1-cross-source-v1`
reader，拒绝未知/缺字段、duplicate JSON key、字符串数字、NaN/Infinity、绝对/逃逸路径和未知
issue code。`G1QualityIssue.evidence` 只保存固定排序的业务键或受控相对路径，禁止本机路径、客户端
repr 或凭据。后续 snapshot manifest 必须记录 `g1_release_id` 与 G1 manifest hash，不能只写
`source=tushare`。

首版 issue code 精确集为：

```text
REQUEST_PLAN_MISMATCH, RECEIPT_INVALID, SCHEMA_INVALID, DUPLICATE_KEY,
UNKNOWN_INSTRUMENT, MEMBERSHIP_MISSING_MONTH, MEMBERSHIP_COUNT_MISMATCH,
MEMBERSHIP_WEIGHT_INVALID, MEMBERSHIP_INTERVAL_OVERLAP, CALENDAR_MISMATCH,
HISTORY_WINDOW_INCOMPLETE, BAR_OR_SUSPENSION_MISSING,
BAR_FULL_SUSPENSION_CONFLICT, PARTIAL_SUSPENSION_BAR_MISSING,
FACTOR_MISSING, FACTOR_INVALID, PRICE_LIMIT_MISSING, PRICE_LIMIT_INVALID,
BENCHMARK_MISSING, CORPORATE_ACTION_INVALID,
CORPORATE_ACTION_FACTOR_MISMATCH, CROSS_SOURCE_INCOMPLETE,
CROSS_SOURCE_MISMATCH
```

issues 按 `(severity,code,message,evidence)` 排序；`error_count/warning_count` 必须与 issues 重算相等，
`passed` 当且仅当 `error_count == 0`。manifest `input_receipts` 按 `(source,endpoint,request_id)`
排序，files 按 path 排序；`sha256` 是物理文件 bytes，`content_sha256` 是规范表内容，二者均验真。
`min_key/max_key` 使用与 `key_columns` 同长的规范字符串 tuple；0 行文件两者均为 null，非空文件两者
均必需；`quality.json/cross_source_reconciliation.json` 固定 `row_count=1`、空 `key_columns`、
null min/max，`content_sha256` 是对严格解析后对象的规范 JSON hash。cross-source `field_stats` 顺序精确为 `open,high,low,close,volume`，`key_count=600`、
`field_count=5`、`comparison_count=3000`，每个 field comparison count=600；统计、detail digest、receipt
digests 和 `passed` 均由 reader 重算而不信任自报。

`apply_adjustment_factors_strict` 必须先按 `symbol,trade_date,source` 唯一键验证两侧数据，再做精确匹配；
每个 emitted bar 必须保留“确实匹配到供应商 factor 行”的证据，匹配缺失、重复、非正或 non-finite 均为
ERROR。禁止使用 `coalesce(..., 1.0)`、默认值或前值填充掩盖缺因子。现有聚合 pipeline/store 的逐日发布
语义不得用于 G1；`publish_g1_release` 只能创建全新的临时 release，原子 rename 后立即调用
`verify_g1_release` 重算 manifest、文件 hash、Schema、行数和键范围。已存在 release 只允许验真复用，
不得增量补写或覆盖。

G1 release 的 Parquet 写参数固定为 zstd level 3、statistics 开启、row group 65536、Polars native writer；
目录发布只允许 WSL/Linux `renameat2(RENAME_NOREPLACE)` 或经测试证明语义等价的 no-clobber primitive。
运行时不支持时 fail-closed，禁止回退到 `os.rename`、`os.replace`、先检查后 rename 或逐文件 merge。

SH 日历是信号与 membership 的唯一 session SSOT；同一日期若 SH/SZ `is_open` 不一致必须产生结构化
诊断并失败，不得求并集或静默选边。`eligible_keys.parquet` 是 G1 release 必需产物，严格只含
`as_of,symbol` 两列、键唯一且排序稳定；G2/G3/G4 不得从 membership 自行再推导一份。跨源证据
未执行、缺双方 receipt、样本集不精确或超阈值时均不得宣称 G1 通过。

G7 的执行事实不得从价格形态猜测。`stk_limit` 映射结果必须通过代码 SSOT
`PriceLimit1dSchema`；`dividend` 只接受 `div_proc=实施` 的行，使用税前每股现金和每股送转比例映射到
`CorporateActionLedgerSchema`。供应商没有公告时分的历史实施事件不得伪造 `announce_time` 后塞入
面向 PIT 研究的 `CorporateActionSchema`。mapper 必须在 raw 留档后处理同一事件的多次公告版本，保留
选择证据；任何 adj_factor 跳变若在相邻交易日无法由已实施公司行动解释，进入 G7 前必须报 ERROR。
`PriceLimit1dSchema.has_price_limit` 必须显式区分“有完整上下限”和“当日依法无限制”；前者要求
up/down 均存在且包围昨收，后者需要另一份已验真交易规则键证明。首版尚未接入该规则源，
因此 M3 v1 不发布 `has_price_limit=false`。真实 `stk_limit` 的 null/zero `pre_close` 是无可用 limit 的供应商
sentinel，只保留在 raw、不映射 clean；它不是无限制日证明。未来要支持合法无涨跌幅限制日，必须新增规则
输入、方法版本和 digest 后升级契约；mapper 不得从 null/zero 或价格形态猜测。

G1 价格限制覆盖不能只检查 `(eligible as_of → next session)`：调出、停牌、涨跌停或 T+1 后仍可能持仓。
每个曾 eligible 的证券从首次 eligible 后第一 SH session 起，直到 `history.end` 或退市日对应最后 SH
session 展开潜在持仓域；有 verified `FULL_DAY` suspension 的 key 因两边均不可成交而从 limit-required 集合
排除，`PARTIAL` 或无 suspension 的 key 必须有一条 `has_price_limit=true` 的 Tushare 行。首次可能持仓前的
合法 extra 行可保留。null/zero sentinel 若没有 FULL_DAY 证据仍 fail-closed。
该 required key 派生表进入 candidate/audit 内容 digest，但不增加 release 普通文件。通用
`PriceLimit1dSchema` 仍保留未来有规则证据的 false 分支，M3 v1 mapper/coverage 不得使用该分支。

公司行动首版多公告选择规则固定为：只保留 `div_proc=实施`；经济事件分组键为
`(ts_code,end_date,record_date,ex_date)`，`pay_date/div_listdate` 是可被后续公告更正的版本属性，不得进入分组键。
组内按 `(imp_ann_date,ann_date)` 降序选唯一最新版本；
排序键完全相同但现金/送转数值冲突时失败，不得 `keep="last"`。`record_date/ex_date` 必需；
`cash_per_share_gross > 0` 时 `pay_date` 必需，否则 `pay_date` 必须为空；`stock_ratio > 0` 时
`stock_list_date` 必需，否则该日期必须为空。事件 ID 是规范分组键+最终数值的 SHA-256，选择证据记录
候选数、被选 raw snapshot/request 和冲突计数。同一 ex-date 的多个不同经济事件在 factor 对账前才汇总，
不得在版本选择阶段相互覆盖。

`dividend` 请求是单证券全历史，不得让范围外旧记录阻断当前研究：对实施行先验证 `ex_date` 可分类，再只对
`HistoryWindow` 内 ex-date 执行完整经济/结算契约；无法解析 ex-date 的实施行不能伪装成范围外。
`imp_ann_date/ann_date` 可 null，total order 中每个 null 都比任何合法日期旧；同 group 同 rank 且决策字段
相同的 raw 重复合并计数，cash/stock/pay/list 任一冲突则失败。范围内 cash>0 当且仅当 pay date 存在，
stock>0 当且仅当 list date 存在；`record_date` 非 null。
合法空 dividend response 或 HistoryWindow 内零实施事件必须形成带精确 Schema/digest 的空 ledger/evidence，
不得当作数据错误。ledger 现行字段数是十列，不是九列。`candidate_id` 规范绑定 event key、imp/ann、
cash/stock、pay/list；同 rank 完全重复折叠后，candidate count 只计不同 candidate ID，raw row count 单独保存。
公司行动数值对账必须保留并重建对应 verified daily raw，因为 Tushare `daily.pre_close` 是除权参考价，而沪深
交易规则的通式含配股且允许发行人/交易所批准调整。现金/送转只能计算
`declared_dividend_factor_ratio = previous_close * (1 + stock_ratio) /
(previous_close - cash_per_share_gross)`；存在 effective-date daily 行时，主门禁使用
`market_reference_factor_ratio = previous_close / daily.pre_close(ex_date)`，并与
`adj_factor(ex_date)/adj_factor(previous_factor_observation)` 在配置 rtol 内对账。若 verified daily 缺该行，
必须另有同键 `FULL_DAY` suspension；此时 market 三字段为 null，且只有 declared ratio 自身在 rtol 内闭合
才可继续。PARTIAL 或无 suspension 的缺行仍失败。
previous factor observation 是该证券严格早于 ex-date 的最后一条可用因子，不要求停牌期间逐 session 有因子；
但事件必须精确落在 factor row，不能把 gap 中事件移动到下一 row。previous close 是 ex-date 前最后一条有效
未复权 bar，允许早于 previous factor date。
多个同日实施事件
按 event ID 排序并用 `math.fsum` 分别合并现金与送转后计算；event-set hash 使用规范数组
`["m3-g1-corporate-action-event-set-v1",*sorted_event_ids]`。有 factor 跳变无事件、有效事件无可用前收，或
market/declared 两条可用证明路径都超容差均为 ERROR。有 daily 且 declared 公式在 rtol 内输出
`MATCHED_EVENT_DECLARED_FORMULA`；无 daily 但 declared 闭合输出
`MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`；declared 超出但 market reference 闭合时输出
`MATCHED_EVENT_MARKET_REFERENCE`，明确记录配股、差异化分红或批准调整未被 dividend 两字段完整表达，
不得扩大 rtol 让该状态消失。

公司行动 reconciliation 对每个相邻 factor observation 输出一行证据：无事件时 declared/market ratio=1，
有事件时以规范 `event_ids_json` 保留排序去重 event IDs，并从它重算 event count/hash；同时绑定聚合经济分量、previous close、raw ex-reference、declared/market/actual ratio、
两种 relative error、实际 rtol，以及可回指 candidate receipt 的 daily request/stable-response lineage；行数
严格等于各 symbol 的 factor rows-1。`factor_ratio_rtol` 首版必须 finite 且位于 `[0,0.01]`，示例仍为
`0.001`；C0 与 data 函数双重门禁，禁止用 1.0/NaN 把 residual 变绿。

B2C 的现行可执行任务书为
[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](agent/M3_G1_P3_B2C执行事实外部闭环任务单.md)。精确 evidence Schema、
identity、错误码、文件范围、真实探针和外部实现—复验循环以该任务书为准。

P3 初验曾发现只改 `event_ids_sha256` 并同步整表 digest 仍可通过。通用教训是：整表内容 digest 只能证明字段
属于该表，不能替待验证的派生身份自证；自包含 verifier 必须保存并规范化重算所需的最小原始证据。P3 因此
新增 `event_ids_json` 并从中重算 count/hash。若攻击者把证据、派生值和全部 digest 一起替换为另一套内部自洽
结果，来源闭包仍必须由 P4A 从冻结 plan/verified responses/输入表重新执行 P2/P3 关闭，不能继续堆自报 hash。

`HistoryWindow` 定义在 `quant.data.m3_backfill`；P4A 的 `G1QualityIssue` 定义在
`quant.data.m3_g1_candidate`，不得为复用类型而把 B4 继续塞入 `m3_backfill`。二者都不得从
`quant.research.m3.contracts/readiness` 反向 import；data 层不能依赖 research 层。

停牌 clean 契约由 `src/quant/domain/schemas.py` 新增的 `Suspension1dSchema` 作为 SSOT：

```python
class Suspension1dSchema(pa.DataFrameModel):
    symbol: str
    trade_date: pl.Date
    suspension_scope: str  # FULL_DAY / PARTIAL
    suspension_detail: str | None
    source: str
    source_snapshot_id: str
```

唯一键为 `(symbol,trade_date,source)`。Tushare 只请求 `suspend_type="S"`；`suspend_timing` 为空映射
`FULL_DAY`，非空映射 `PARTIAL` 并保留原字符串。若原始同日多行，mapper 只能在 raw 留档后规范化：
多个 partial detail 排序合并，FULL/PARTIAL 冲突拒绝。`无 bar + FULL_DAY` 合法，`无 bar + PARTIAL`
或未知状态非法，`有 bar + PARTIAL` 合法，`有 bar + FULL_DAY` 为冲突。

### 4.11 `a_share_simulator.py`：G7 统一 A 股回测

G7 不是复用当前 ETF 薄模拟器换一个成本对象。股票账户必须显式处理停牌持仓估值、涨跌停开盘拒单、
T+1、公司行动应收款/应收股和历史费率。现行 G7P0–G7F verified-artifact 边界、金额舍入和外部闭环以
[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)
为执行入口；旧 E4A–E4E 只保留历史。实现时相应输出 Schema 写入
`src/quant/domain/schemas.py` 成为字段 SSOT：

```python
@dataclass(frozen=True)
class VerifiedTargetArtifact:
    root: Path
    targets: pl.DataFrame
    target_daily: pl.DataFrame
    manifest: TargetManifestV1
    manifest_sha256: str
    target_receipt_sha256: str

@dataclass(frozen=True)
class VerifiedBacktestPlanArtifact:
    root: Path
    scheduled_targets: pl.DataFrame
    manifest: BacktestPlanManifestV1
    manifest_sha256: str
    plan_receipt_sha256: str

```
