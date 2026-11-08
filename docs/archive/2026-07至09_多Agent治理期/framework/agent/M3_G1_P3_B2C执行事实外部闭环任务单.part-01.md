# M3 G1-P3：B2C 执行事实外部实现—独立复验闭环任务单

日期：2026-07-14  
状态：`event_ids_json` 返工、全新独立复验及主 Agent 最终验收均已通过；仅关闭 P3/B2C 子包，不关闭 B2/G1/Gate  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md)  
上游 B2A：[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)  
上游 B2B：[`M3_G1_P1主Agent最终验收报告.md`](M3_G1_P1主Agent最终验收报告.md)  
前置 P2：[`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)

## 1. 目标与在 pipeline 中的位置

本包完成 G1 的 B2C“执行事实”层：

1. 将已验真的 Tushare `stk_limit` 映射为显式、不可猜测的 A 股涨跌停事实；
2. 从 `eligible_keys` 推导策略可能持仓后的完整价格限制覆盖域，不能只检查下一笔买入日；
3. 将 `dividend` 全历史响应裁剪为本次 `HistoryWindow` 内的已实施经济事件，确定性选择公告版本并保留证据；
4. 用公司行动事件与已验真 `daily.pre_close`（除权参考价）解释 Tushare 复权因子的每次变化，输出可由 B4
   从原始 daily/adj-factor/dividend 证据重新计算的 reconciliation 表。

它位于 B2A raw/receipt 与 B2B/B3 clean 结果之后，B4 candidate/audit/release 之前。B4 不得再自行实现另一套
涨跌停、公告选版或 factor-ratio 规则。

本包不实现 B4 文件发布、跨源 BaoStock 对账、Qlib、标签、回测或交易；不发网络请求，不读取配置文件，不写
raw/clean 数据。实现只接收显式已验证对象和 DataFrame。

## 2. 前置与外部闭环流程

P3 的结果身份必须复用 P2 已验收的 `clean_table_content_sha256`；P2 前置现已满足，不得复制一个临时 hash
工具或修改 P2 已验收实现来绕过依赖。

外部闭环为：

1. 实现 Agent 按本任务书实现、自测，生成
   `docs/M3_G1_P3_B2C执行事实交付报告.md`；
2. 未参与实现的独立初验 Agent 只读审查并增加未公开反例，生成
   `docs/M3_G1_P3_B2C执行事实独立初验报告.md`；
3. 初验若失败，按“现象—根因—应遵循规则—最小复现—新增测试—通过条件”退回实现；二者循环直至
   独立复验通过；
4. 复验通过后停止，等待主 Agent 最终验收。不得自行勾选 B2/G1/Gate。

两个角色必须是不同 Agent/独立上下文，均显式使用 `cursor-grok-4.5-high`，不得使用任何 `*-fast` 变体；
报告记录实际模型标识。Agent 进程运行在 Windows，但所有 Python、pytest、Ruff、mypy 和项目脚本必须通过
`wsl.exe` 在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 下使用 WSL Miniforge `base` 执行，禁止 Windows
Python/conda。开始前完整阅读根 `AGENTS.md`、`karpathy-guidelines.md`、本任务书、主契约 §4.10、P2 最终
验收报告以及上述 B2A/B2B 报告。不得读取 `_old/` 或 token 配置。

## 3. 官方依据与主 Agent 真实探针

官方接口依据：

- [每日涨跌停价格](https://tushare.pro/document/2?doc_id=183)：`stk_limit` 提供
  `trade_date/ts_code/pre_close/up_limit/down_limit`，单次上限 5800；
- [分红送股](https://tushare.pro/document/2?doc_id=103)：`cash_div_tax` 是税前每股现金，`stk_div` 是每股
  送转，实施、登记、除权、派息和红股上市日期职责不同；
- [复权因子](https://tushare.pro/document/2?doc_id=28)：`adj_factor` 是 Tushare 自生产的日频因子；研究后
  复权价格使用原价乘因子。
- [A 股日线行情](https://tushare.pro/document/2?doc_id=27)：`daily.pre_close` 明确定义为“昨收价（除权价）”，
  涨跌幅也以该除权昨收计算；它不能在 B2B 映射丢弃后再靠现金/送转字段精确猜回。
- [上交所 2026 交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)
  与[深交所 2026 交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)
  都给出含现金红利、配股价格和股份变动比例的通式，并明确允许按申请调整公式；只拿 dividend 的现金/送转
  字段无法覆盖配股、差异化分红或获准调整的参考价。

2026-07-14 主 Agent 在 WSL Miniforge base 用本地 ignored token 做了只读、脱敏小样本探针，没有保存响应或
输出凭据：

- 三只沪深股票的 dividend raw 精确返回冻结列；范围内可见实施记录的 `ann_date/imp_ann_date` 确有 null，
  因而版本排序必须给 null 明确定义，不能直接依赖 Polars 默认排序；
- 一只股票的 1991/1992 年实施记录存在非零现金但 `pay_date` 缺失，而 2016 年后抽样没有该缺口；dividend
  是无日期范围的全历史请求，因此必须先用可验证 `ex_date` 裁剪 `HistoryWindow`，再检查范围内结算契约；
- 后续扩大到 12 只匿名 CSI300 样本、2015-10-01 至 2026-06-26 的 31,248 个 factor transitions：31,121 个
  无事件 transition 全部在 `0.001` 内稳定；127 个有 dividend 事件的 transition 中，单纯现金/送转公式有
  121 个在 `0.001` 内，最大误差约 `0.00350`。其中 125 个有 daily 行，使用同一 verified raw 的
  `previous actual close / effective-date pre_close` 后全部在 `0.001` 内，最大约 `0.000356`；另 2 个事件日
  daily 缺行且 `stk_limit.pre_close=0`，但 declared 公式均闭合，最大误差约 `0.000194`；
- 六个差异不能通过扩大 rtol 掩盖，也不能把 Tushare factor 判成坏数据。它们证明旧接口缺少官方除权参考价；
  本任务据此修订为 raw `pre_close` 主门禁、现金送转公式诊断分支；
- 六个差异样本均为纯现金事件；由 raw pre-close 反推的虚拟现金均为正且为实际每股现金的约
  `66.7%..98%`，与差异化分红的市场参考价形态一致，但该聚合特征不冒充逐公告分类证据，因此仍以显式
  `MATCHED_EVENT_MARKET_REFERENCE` 留痕；
- `stk_limit` 样本返回 21 行、五列 dtype/空值均符合官方字段，但单个正常样本不能证明所有历史日完整。
- 补查 2021–2024 六个交易日的 `suspend_d` 与 `stk_limit` 集合：缺 limit 的停牌证券全部为 `.BJ`，不属于本
  项目 `.SH/.SZ` CSI300 域；抽查的沪深停牌证券均有 limit 行。这只支持当前 fail-closed 覆盖规则，不把六日
  样本夸大成全历史完整性证明。
- 进一步按 12 只匿名样本拉取完整历史后，`stk_limit` 出现 666 个 `pre_close=0` 键且全部有同日 suspension
  证据，另有 55 个 null 键（43 个有 suspension，12 个无）；说明“API 有行”不等于该日有可用 limit。
  Mapper 必须把严格 null/zero sentinel 留在 raw 而不发布伪造的 `PriceLimit1d`；coverage 再以 FULL_DAY
  suspension 为唯一豁免，其他持仓日缺有效 limit 仍失败。

真实探针只用于冻结边界，不替代外部 mock 测试和后续全量 G1 真实验收。

## 4. 冻结模块与公共接口

新增 `src/quant/data/m3_execution_facts.py`：

```python
G1_PRICE_LIMIT_METHOD_VERSION = "tushare_stk_limit_suspension_aware_v1"
G1_CORPORATE_ACTION_SELECTION_VERSION = "tushare_dividend_implemented_latest_v1"
G1_CORPORATE_ACTION_RECONCILIATION_VERSION = "tushare_factor_daily_preclose_v1"

class M3G1ExecutionFactError(ValueError):
    code: str

@dataclass(frozen=True)
class CorporateActionSelectionResult:
    ledger: pl.DataFrame
    selection_evidence: pl.DataFrame
    ledger_sha256: str
    selection_evidence_sha256: str

@dataclass(frozen=True)
class CorporateActionReconciliationResult:
    evidence: pl.DataFrame
    evidence_sha256: str

def map_g1_price_limit_response(
    *, response: VerifiedRawResponse,
) -> pl.DataFrame: ...

def require_g1_price_limit_coverage(
    *, price_limits: pl.DataFrame, eligible_keys: pl.DataFrame,
    suspensions: pl.DataFrame, calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    history: HistoryWindow,
) -> pl.DataFrame: ...

def select_g1_corporate_actions(
    *, response: VerifiedRawResponse, history: HistoryWindow,
) -> CorporateActionSelectionResult: ...

def verify_corporate_action_selection_result(
    *, result: CorporateActionSelectionResult,
) -> None: ...

def reconcile_g1_corporate_actions(
    *, corporate_actions: pl.DataFrame, bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    suspensions: pl.DataFrame, calendars: pl.DataFrame,
    history: HistoryWindow, factor_ratio_rtol: float,
) -> CorporateActionReconciliationResult: ...

def verify_corporate_action_reconciliation_result(
    *, result: CorporateActionReconciliationResult,
) -> None: ...
```

在 `quant.data` 包根导出三个版本常量、两个 result、错误类型和六个函数；在 `quant.domain` 包根导出本包新增
Schema。只新增必要导出，不重排无关符号。

所有 source 固定为 `tushare`。函数不得接收 caller-controlled source、config path、任意 method version、
自报 PASS 或裸 raw DataFrame。

## 5. 共同信任边界

`map_g1_price_limit_response` 和 `select_g1_corporate_actions` 在读取 frame 任何值前必须：

1. 用生产 `VerifiedRawResponse` 构造器重建 spec/receipt/receipt hash/frame content 闭包；
2. 验证 endpoint、冻结 fields、精确列顺序和 request scope；
3. 只消费重建后的 response/frame；
4. 把 Pandera/Polars/日期/数值异常转换为稳定错误码并 `from None`，不泄露路径、raw 值、客户端 repr 或 token。

`reconcile_g1_corporate_actions` 还必须重建全部 `daily_responses` 后才读取 `pre_close`；裸 caller DataFrame、
从 `close-cash` 猜出的参考价或 B2B 已丢弃的临时列都不是合法替代。frozen dataclass 不等于内部 DataFrame
永久可信。两个 result 构造时及公开 verify 函数调用时都必须重验 Schema 和内容 digest；B4 将从原输入重建
后再消费。

## 6. 涨跌停映射

### 6.1 单 response 映射

输入 endpoint 精确为 `stk_limit`，raw 列精确为：

```text
trade_date,ts_code,pre_close,up_limit,down_limit
```

行为：

- response 不得为空；`ts_code` 必须与 request 的六位 `.SH/.SZ` 代码逐行一致；
- `trade_date` 必须是合法八位日期且位于 request start/end 闭区间；
- 三个价格先按 strict scalar 解析：允许供应商数值、可无损十进制字符串或 null；拒绝 bool、NaN/inf、
  List/Struct、空串和负数；
- `pre_close>0` 时 up/down 必须正且满足 `down_limit < pre_close < up_limit`，映射为一条有效 limit；
- `pre_close is null` 或精确为 0 是供应商“本行无可用昨收”的 sentinel：up/down 只允许 null、0 或正 finite，
  该 raw 行不映射为 clean 行。它是否可接受只能由后续 suspension-aware coverage 决定；mapper 不把 0/null
  改成正数，也不输出 `has_price_limit=False`；
- `(symbol,trade_date,source)` 重复失败，不做 `unique/keep=last`；
- 输出精确为 `PriceLimit1dSchema` 八列，`has_price_limit=True`，snapshot 来自 receipt，按
  `(symbol,trade_date,source)` 排序；response 非空但全为 sentinel 时返回 exact-schema 空表；
- M3 v1 没有已验真的“依法无限制日”规则源。本函数永不把 sentinel 解释为无限制日，也永不输出
  `has_price_limit=False`；非 FULL_DAY 的缺行最终仍 fail-closed。

`PriceLimit1dSchema` 作为通用领域契约仍可表达未来有证据的无限制日；G1 v1 的更严格限制属于本 mapper 与
coverage 门禁，不能通过删掉 Schema 的未来分支冒充完成。

### 6.2 价格限制覆盖域

只检查每个 `(eligible as_of → next session)` 不够：证券调出后可能因停牌、涨跌停或 T+1 继续持有。覆盖域
固定为：

1. 对每个曾出现在 `eligible_keys` 的 symbol，取最早 eligible `as_of` 后的第一 SH session 作为
   `coverage_start`；信号当日开盘早于信号，不在覆盖域；
2. `coverage_end` 为 `history.end` 与该证券 `delist_date` 对应最后一个不晚于退市日的 SH session 较早者；
3. 展开 start/end 间全部 SH 开市日，包括退出 universe 后的日期；
4. suspensions 通过 `Suspension1dSchema` 且 source=tushare。恰有一条 `FULL_DAY` 的 key 从 limit-required 集合
   排除，因为当日两边都不可成交；`PARTIAL` 或无 suspension 的 key 仍必须有有效 limit；
5. 每个最终 required `(trade_date,symbol)` 必须恰有一条 source=tushare 且 `has_price_limit=True` 的行。

`require_g1_price_limit_coverage` 返回精确两列 `trade_date: Date,symbol: Utf8` 的 required keys，唯一且排序；
缺行、重复、false、未知证券、无 next session、生命周期倒置或 calendar 不闭合均失败。FULL_DAY 可有额外
合法 limit 行但不进入 required digest；sentinel 本身不进入 clean price_limits。price_limits 中早于首次可能
持仓的额外合法行可以保留，不得反向扩张 required keys。

calendar/instrument/suspension 分别通过代码 SSOT
`TradeCalendarSchema/InstrumentSchema/Suspension1dSchema`；HistoryWindow 重建；SH/SZ
在 history 自然日域的日期集与 `is_open` 必须一致。eligible keys 精确只有 `as_of,symbol`、唯一、非空，
as_of 必须是 SH session。

B4 必须重算 required keys，并把
`clean_table_content_sha256(table_name="price_limit_required_keys", ...)` 放入 candidate/audit 内容身份；该派生表
不新增 release 普通文件，避免改变已冻结目录布局。

## 7. 公司行动范围与版本选择

### 7.1 先裁范围，再验相关事件

dividend request 没有日期范围。对 raw 每行先只执行足以分类的检查：

- endpoint/列/response identity 已闭合；
- `ts_code` 与 request 逐行一致；
- `div_proc` 是字符串；
- 对 `div_proc=实施`，`ex_date` 必须是合法八位真实日期；无法证明 ex_date 的实施行不能被当作范围外忽略。

只有 `history.start <= ex_date <= history.end` 的实施行进入完整业务校验。其他实施行和所有非实施进度不进入
本次 ledger/evidence；raw receipt 仍完整绑定它们。不得先对全历史旧行执行 pay/list 必填检查，也不得按公告日
而不是 ex_date 裁剪。

`dividend` endpoint 允许合法空 response；非空 response 也可能在本次 HistoryWindow 内没有实施事件。两种情况
都必须返回带精确 dtype/列顺序的空 ledger、空 selection evidence 和对应 clean digest，不得报
`G1_EXECUTION_FACT_EMPTY`。该错误码只适用于 `stk_limit`。result verifier 必须能重验合法空结果。

### 7.2 相关实施行

对范围内实施行：

- `end_date/record_date/ex_date` 必需、合法；`record_date <= ex_date`；
- `ann_date/imp_ann_date` 可 null；非 null 必须是合法日期。null 只影响排序，不伪造日期；
- `cash_div_tax` 与 `stk_div` 是唯一经济数值，必须 finite、非负且至少一项大于 0；不使用税后 `cash_div`，
  不以 `stk_bo_rate/stk_co_rate` 替代 `stk_div`；
- cash>0 时 pay_date 必需且 `pay_date>=ex_date`；cash=0 时 pay_date 必须 null；
- stock>0 时 div_listdate 必需且 `div_listdate>=ex_date`；stock=0 时 div_listdate 必须 null；
- 拒绝 bool、空字符串、非规范日期、NaN/inf、负值、全零和日期倒置。

经济事件分组键固定为 `(symbol,end_date,record_date,ex_date)`。pay/list date、版本公告日和经济数值不是分组
键，因为它们可能被后续实施公告更正。

### 7.3 total order、冲突与重复

版本 rank 按下列 total order 降序：

```text
(imp_ann_date is not null, imp_ann_date-or-date.min,
 ann_date is not null, ann_date-or-date.min)
```

即每个 null 都比任何合法日期旧；不得依赖 Polars 默认 `nulls_last`。同一 group、同一 rank key：

- 若 cash、stock、pay/list 完全相同，是相同候选的 raw 重复，折叠为一条 evidence 并增加 `raw_row_count`；
- 任一上述决策字段不同即 `VERSION_CONFLICT`，不得用 row order、snapshot order 或 `keep=last` 选择。

不同 rank 的候选全部保留 evidence，rank=1 唯一进入 ledger。同一 ex_date 的不同经济 group 保留为多个
event，直到 factor reconciliation 才按日聚合。

### 7.4 确定 identity

- `economic_event_key_sha256` = 规范 JSON 数组
  `["m3-g1-corporate-action-key-v1",symbol,end_date,record_date,ex_date]` 的 SHA-256；日期 ISO；
- `candidate_id` = 下列规范 JSON 数组的 SHA-256：
  `["m3-g1-corporate-action-candidate-v1",economic_event_key_sha256,
  imp_ann_date-or-null,ann_date-or-null,cash,stock,pay_date-or-null,stock_list_date-or-null]`；
- ledger `event_id` =
  `["m3-g1-corporate-action-event-v1",symbol,end_date,record_date,ex_date,cash,stock]`；
- float 使用与 P2 clean identity 相同的 finite round-trip 十进制与 `-0.0→0.0` 规范；JSON UTF-8、紧凑、
  `allow_nan=false`。

event ID 不绑定 pay/list、snapshot 或路径；这些字段变化仍会改变 ledger 内容 digest/release，但经济事件主键保持
可追踪。不得用 Python `hash()`。

同 rank 的完全相同 raw rows 折叠后，`candidate_count` 是该 event key 下**不同 candidate_id 的数量**，
`raw_row_count` 是该 candidate_id 折叠的原始行数；二者不得把 raw duplicate 同时算成多个 candidate。

## 8. 新增/收紧领域 Schema

### 8.1 `CorporateActionLedgerSchema`

保持现有十列（`event_id,symbol,ex_date,cash_per_share_gross,stock_ratio,record_date,pay_date,
stock_list_date,source,source_snapshot_id`），收紧：

- `record_date` 非 null；event ID 唯一；source/snapshot 在 G1 消费边界固定/验真；
- cash/stock finite 非负且至少一项>0；
- cash>0 当且仅当 pay_date 非 null；stock>0 当且仅当 stock_list_date 非 null；
- record<=ex，pay/list 若存在均>=ex。

### 8.2 `CorporateActionSelectionEvidenceSchema`

精确列顺序：

```text
economic_event_key_sha256,candidate_id,symbol,end_date,record_date,ex_date,
imp_ann_date,ann_date,cash_per_share_gross,stock_ratio,pay_date,stock_list_date,
candidate_rank,candidate_count,raw_row_count,selected,selection_reason,
source,source_request_id,source_snapshot_id
```

约束：两个 hash、request/snapshot 为小写 64 hex；日期/数值规则同 ledger；rank/count/raw count 为正整数；
`1<=rank<=candidate_count`；selected 当且仅当 rank=1，reason 分别为 `SELECTED_LATEST` 或
`SUPERSEDED_OLDER`；candidate_id 唯一。每个 event key 的 rank 精确为 1..candidate_count 且只有一个 selected，
由 result verifier 重算。

### 8.3 `CorporateActionReconciliationSchema`

精确列顺序：

```text
symbol,previous_factor_date,effective_date,previous_close_date,previous_close,
ex_reference_price,daily_request_id,daily_stable_response_sha256,
event_count,event_ids_json,event_ids_sha256,cash_per_share_gross,stock_ratio,
declared_dividend_factor_ratio,market_reference_factor_ratio,actual_factor_ratio,
market_reference_relative_error,declared_dividend_relative_error,
factor_ratio_rtol,status,source
```

约束：日期递增；两个 daily lineage 字段始终为小写 64 hex，并指向该 symbol 唯一 verified daily response；
数值 finite；非 null ratio 正；两个相对误差/rtol 非负且 rtol<=0.01；键
`(symbol,effective_date,source)` 唯一。`NO_EVENT_STABLE_FACTOR` 要求 event_count=0、cash=stock=0、previous close
两列、`ex_reference_price`、market ratio/error 均为 null，declared ratio=1、declared error=`abs(actual-1)`；
`MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE` 要求 count>0、previous close 与 declared/actual ratio>1、
declared error<=rtol，但 ex-reference、market ratio/error 均为 null；只允许 effective date 的 verified daily
确实缺行且 suspensions 恰有 `FULL_DAY` 时使用。`MATCHED_EVENT_DECLARED_FORMULA` 与
`MATCHED_EVENT_MARKET_REFERENCE` 则都要求 count>0、
至少一个经济分量>0、previous close/ex-reference 正、previous date 早于 effective，三个 ratio 都>1，且
market-reference error<=rtol；前者还要求 declared error<=rtol，后者要求 declared error>rtol。后者不是静默
容差放宽，而是明确记录交易所/发行人参考价未被 dividend 两字段完整表达。source 精确为 tushare。
`event_ids_json` 是按字典序升序、无重复的小写 64 hex event ID 数组的规范 JSON 文本；序列化固定为
`json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`，不得含 namespace，空集合精确为
`[]`。`event_count` 必须等于解析后的数组长度。`event_ids_sha256` 固定为规范 JSON 数组
`["m3-g1-corporate-action-event-set-v1",*parsed_event_ids]` 的 SHA-256；空集合即只含 namespace 的数组，不能用
空字符串或空文件 hash 替代。构造和公开 verifier 都必须从 `event_ids_json` 解析并独立重算 count/hash；不得只用
整行内容 digest 为它们背书。

Schema 定义在 `src/quant/domain/schemas.py`，字段不在任务书之外再复制一套代码常量。

## 9. 公司行动—复权因子 reconciliation

### 9.1 输入闭包

- corporate actions 通过收紧后的 ledger Schema；
- bars 通过 `Bar1dSchema`，adjustment factors 通过 `AdjustmentFactorSchema`；
- calendar/suspensions 通过 `TradeCalendarSchema/Suspension1dSchema`，HistoryWindow 重建；
- 三表 source 精确为 tushare，日期在 history 内；factor/bar symbol 集非空且一致，action symbol 是其子集；
- 每个 bar 的 `(symbol,trade_date)` 必须存在数值完全相同的 factor，禁止使用 bar 内另一个 factor 版本；
- factor 每个 symbol 至少两行，日期严格递增、为 SH session；event ex_date 必须是 factor date 且不能落在该
  symbol 第一条 factor（第一条没有可比较前因子）。

`daily_responses` 必须逐个使用生产 `VerifiedRawResponse` 重建，endpoint/fields 精确为 B2A 的 `daily` 合同，
每个 factor/bar symbol 恰好一份、无 extra/duplicate，request symbol 与完整 `HistoryWindow` scope 匹配。
从 raw 只投影 `(symbol,trade_date,close,pre_close)`：两价格 strict finite positive，键唯一；其键集与 bars 精确
相等，`close` 数值逐键相等。这样 previous close 和 effective-date ex-reference 都来自同一份冻结 raw，不能由
caller 拼接另一张自洽 bars 表。停牌日没有 daily row 是合法来源语义；已实施事件/factor effective date 缺行
时，只有同键 verified `FULL_DAY` suspension 才能进入下述 declared-formula-no-reference 严格分支；PARTIAL、
无 suspension 或重复/跨源 suspension 均失败，不能伪造 `pre_close`。

每条 reconciliation 行都保存该 symbol 的 `daily_request_id/daily_stable_response_sha256`；即使无事件 transition
当天因停牌没有 daily row，也仍绑定用于 bars 闭包的唯一 symbol response。有事件且存在
`ex_reference_price` 时，它必须确实来自同一 lineage frame 的 effective-date 行；缺行分支三个 market 字段
必须同时为 null。P4 再将 lineage 回指 candidate receipt projections；不得只写一个全局 source 字符串。

这些是本函数的输入完整性，不代替 B4 对 request/receipt 和全 history coverage 的再次门禁。

### 9.2 每个 factor transition 一条证据

对每个 symbol 的相邻“可用 factor observation” `(previous_factor_date,effective_date)`：

```text
actual_factor_ratio = factor(effective_date) / factor(previous_factor_date)
```

factor observation 不要求覆盖停牌 session，但两个日期都必须是 SH 开市日。公司行动必须精确在
`effective_date`，不能把 gap 中更早事件挪到下一条 factor。

若 effective_date 无事件：

- declared ratio=1，market ratio/error=null，event_count=0；
- declared error 为 `abs(actual-1)`；
- error<=rtol 才输出 `NO_EVENT_STABLE_FACTOR`，否则 `FACTOR_UNEXPLAINED`。无事件分支不要求当天有 daily row，
  因为停牌期间 factor observation 可存在而 raw daily 合法缺行。

若当天有一个或多个事件：

- event ID 排序后按上述固定数组 hash；cash 和 stock 均按 event ID 稳定顺序使用 `math.fsum`，禁止普通
  浮点 reduce 使输入行序改变边界结果；
- previous_close 是 bars 中该 symbol 严格早于 ex_date 的最后一个有效未复权 close，允许因停牌早于
  previous_factor_date；缺失则失败；
- 分母 `previous_close-total_cash` 必须>0；
- `declared_dividend_factor_ratio = previous_close*(1+total_stock)/(previous_close-total_cash)`，只表示 dividend
  两个经济字段能推出的通式，不冒充交易所最终参考价；
- 若 effective-date daily row 存在，`ex_reference_price` 必须来自同一 verified raw 的 `pre_close` 且正，
  `market_reference_factor_ratio = previous_close/ex_reference_price`；market error 必须<=rtol。declared
  error<=rtol 输出 `MATCHED_EVENT_DECLARED_FORMULA`，否则输出 `MATCHED_EVENT_MARKET_REFERENCE`，不得改大
  rtol 让后者消失；
- 若 verified daily frame 在该 effective date 确实无行且 suspensions 同键恰有 `FULL_DAY`，三个 market 字段
  同时为 null；只有 declared error<=rtol 才输出 `MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`，否则
  失败。PARTIAL/无 suspension 缺 daily 直接失败；不得用 `stk_limit.pre_close=0`、
  前填或自然日价格构造参考价。

任何事件无对应 factor、事件发生在第一 factor row、同日聚合后分母非正、event 分支 actual/declared ratio
不大于 1、存在 market reference 时 market ratio不大于 1、无事件 factor jump、缺前收，或 market/declared
两条可用证明路径都超容差均失败。首版不把配股或
差异化分红硬塞进 dividend ledger；其影响会显式表现为 `MATCHED_EVENT_MARKET_REFERENCE`，后续若要恢复完整
经济拆解，必须新增相应事件源和版本，而不是修改历史 evidence 或扩大 rtol。

`factor_ratio_rtol` 必须是 exact float（非 bool）、finite 且 `0<=rtol<=0.01`。示例配置仍为 `0.001`。P3
同时在 C0 config validator 加上 maximum=0.01 并回归全部 C0 测试；data 模块不得 import research config。

证据行数精确等于 `sum(max(factor_rows_per_symbol-1,0))`，输入顺序变化不改变输出和 digest。

## 10. Result 与内容身份

SelectionResult 使用 table name：

- `corporate_action_ledger`；
- `corporate_action_selection_evidence`。

ReconciliationResult 使用 `corporate_action_reconciliation`。内容摘要必须调用 P2 已验收的
`clean_table_content_sha256`；不得复制 canonicalizer 或以 Parquet bytes 代替。

构造和公开 verify 必须重算 Schema、ledger↔selection 一一关系、selected candidate 与 ledger 数值、
reconciliation 行数、declared/market 两套公式、条件 status、从规范 `event_ids_json` 得到的 event count/hash 和
全部 digest。构造后只换 frame
或只换 hash 必须失败。若攻击者把
frame、hash 和全部相关业务字段一起替换成另一套内部自洽 result，单靠自包含 verifier 无法证明它仍来自原始
response；因此 B4 必须从冻结 plan/verified responses/输入表重新执行 P3 纯函数并比较，不能只调用 verify。

## 11. 稳定错误码

`str(error)` 只能是下列 code；未知 code 构造失败；`repr/cause/traceback` 不泄露输入：

