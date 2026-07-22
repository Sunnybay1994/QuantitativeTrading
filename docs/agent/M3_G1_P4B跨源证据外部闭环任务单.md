# M3 G1-P4B：BaoStock 跨源证据外部实现—独立初验任务单

日期：2026-07-14  
状态：**P4B 已于 2026-07-15 通过主 Agent 最终验收**；历史任务与返工合同保留，下一包为 P4C  
主设计：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §2、§3、§5、§7–§9  
P4A 前置：[`M3_G1_P4A主Agent最终验收报告.md`](M3_G1_P4A主Agent最终验收报告.md)  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10
最终验收：[`M3_G1_P4B主Agent最终验收报告.md`](M3_G1_P4B主Agent最终验收报告.md)

2026-07-14 合同阻塞解除：首轮实现发现 `G1QualityIssue` 现行允许码与主契约的跨源码不一致；现行返工边界和
六段式证据见 [`M3_G1_P4B合同阻塞解除与重开任务单.md`](M3_G1_P4B合同阻塞解除与重开任务单.md)。该补充任务单
只放宽下述一个文件/枚举边界，其余合同不变。

2026-07-15 首轮独立初验不通过；bundle 的 detail→summary/issues 闭包及同包可见来源闭包的现行返工合同见
[`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)。

2026-07-15 独立复验通过后，主 Agent 未公开反例发现缺失行 canonical detail 与 30 个 stable response 身份仍可
自洽漂移；现行返工合同见 [`M3_G1_P4B主验一次返工任务单.md`](M3_G1_P4B主验一次返工任务单.md)。

## 1. 本包目标与停止边界

P4B 只完成四件事：

1. 从已验收 `G1Candidate` 确定性冻结 30 个证券×20 个交易日共 600 个样本键；
2. 从完整 sample plan 唯一生成 30 个 BaoStock 单证券请求，并以严格 request journal 获取/恢复 raw 证据；
3. 严格验证 receipt/raw/frame 闭包；
4. 对 600×5=3000 个字段单元做跨源 reconciliation，输出可供 P4C 重建的 detail、summary、issues 和身份。

不实现 P4C reader/manifest/release，不写 release，不修改 P4A/P2/P3 算法，不接 Qlib/research，不读取配置或
环境变量。实现完成和独立初验通过后停止，等待主 Agent 终验；不得宣称 B4/G1/Gate 完成。

## 2. 允许文件与环境

只允许：

- `src/quant/data/m3_reference.py`（新增）；
- `src/quant/data/m3_g1_candidate.py`（**唯一允许**：只向 `_ISSUE_CODES` 增加
  `CROSS_SOURCE_INCOMPLETE`、`CROSS_SOURCE_MISMATCH`，不得修改 P4A audit 行为）；
- `src/quant/data/connectors/baostock.py`（只新增 `fetch_reference_bar_raw` 及直接私有校验）；
- `src/quant/data/__init__.py`（只新增冻结导出）；
- `tests/unit/test_m3_reference.py`（新增）；
- `tests/unit/test_baostock_connector.py`；
- 本包交付/初验报告。

除上述两个跨源码的外科式枚举扩展外，不得修改 `m3_g1_candidate.py`；不得修改 `m3_backfill.py`、`storage.py`、
Schema、配置、路线图或上游测试来迁就实现。
不得 import `m3_backfill` 私有 `_helper`；P4B 使用公开 `RawStore.write_request/verify_request`，严格 journal 的
source-specific 值对象和验证放在 `m3_reference.py`。不为未来复用先重构公共 journal 框架。

外部实现与独立初验均使用不同 Cursor 会话，模型精确为 `cursor-grok-4.5-high`，禁止 fast。Agent 从 Windows
启动，但所有 Python/pytest/Ruff/mypy 经 `wsl.exe` 在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 使用 WSL
Miniforge `base`。默认测试禁止真实 BaoStock 网络；不得读取 token 或 `_old/`。

## 3. 已解决的接口矛盾

原草案 executor 只接收 `ReferenceRequestPlanV1`，其中只有 `sample_plan_sha256`，没有 600 keys，却要求在 IO 前
重算“600 keys→30 requests”，该要求不可实现。现行冻结签名改为：

```python
def execute_baostock_reference_plan(
    *,
    sample_plan: CrossSourceSamplePlan,
    plan: ReferenceRequestPlanV1,
    connector: BaostockConnector,
    raw_store: RawStore,
    journal_root: Path,
) -> tuple[ReferenceRequestReceipt, ...]: ...
```

executor 必须从 `sample_plan` 调用同一纯 planner 重建整个 request plan，并在任何 root/lock/intent/raw/network
副作用前与传入 `plan` 精确比较。仅比较 sample hash 不够；二者不一致必须零网络、零证据增量失败。

## 4. 公共接口、类型和稳定错误

实现并在 `quant.data` 包根导出主设计 §3/§5 的以下公共类型与五个函数：

- `G1CrossSourcePolicy`；
- `CrossSourceSamplePlan`；
- `ReferenceRequestSpec`、`ReferenceRequestPlanV1`、`ReferenceRequestIntentV1`；
- `ReferenceRawCandidateV1`、`ReferenceRequestReceipt`、`VerifiedReferenceResponse`；
- `CrossSourceFieldStatsV1`、`CrossSourceSummaryV1`、`CrossSourceReconciliationBundle`；
- `plan_cross_source_reconciliation`、`plan_baostock_reference_requests`、
  `execute_baostock_reference_plan`、`verify_reference_receipt`、`reconcile_cross_source`。

`CrossSourceFieldStatsV1`、`CrossSourceSummaryV1` 和 bundle 字段精确使用主契约 §4.10 / 主设计 §5.6，不增删字段。
这些类型与 `G1CrossSourcePolicy` 定义在 `m3_reference.py`；复用 P4A 导出的 `G1Candidate`、
`G1ReceiptProjectionV1`、`G1QualityIssue`。

稳定边界异常 `M3ReferenceError` 的 `str/repr` 只允许以下 code：

```text
G1_REFERENCE_INPUT_INVALID
G1_REFERENCE_IDENTITY_MISMATCH
G1_REFERENCE_PLAN_INVALID
G1_REFERENCE_JOURNAL_INVALID
G1_REFERENCE_IO_FAILED
G1_REFERENCE_NETWORK_FAILED
G1_REFERENCE_RESPONSE_INVALID
G1_REFERENCE_RECEIPT_INVALID
G1_CROSS_SOURCE_RECONCILIATION_INVALID
```

底层 Polars/JSON/OSError/client 异常统一 `from None`，四观察面不得含绝对路径、raw 值、client repr、账号或
凭据。具体失败诊断不够细可后置，但不得泄露或 fail-open。

## 5. 值对象与身份自证

所有 dataclass exact-type 验证；bool 不冒充 int/float；数值 finite；tuple/排序/唯一性/literal 均重建验证。
内部自洽替换和原输入来源闭包分开说明，不能只检查合法 64 hex。

### 5.1 policy

`reference_source=="baostock"`、`sample_symbols==30`、`dates_per_symbol==20`；四容差为 exact finite float，
`price_atol>=0`，其余三项在 `[0,1]`。不得在 data 层复制配置默认值。

### 5.2 sample plan

精确 600 个 `(symbol,date)`，30 个合法 A 股 symbol、每个恰好 20 个唯一日期，按 symbol/date 排序；构造器从
冻结 envelope 重算 `sample_plan_sha256`。planner 先调用 `audit_g1_candidate` 并要求 passed，再按主设计 §5.4
hash 排序取样；不得预过滤不足 20 日的 symbol，不足即失败。

### 5.3 request identity

parameters 精确五项并按 key 排序：`fields/frequency/adjustflag/start_date/end_date`；**symbol/code 不放入
parameters**，由 `ReferenceRequestSpec.symbol` 唯一派生。fields/frequency/adjustflag 精确为主设计 §5.4，日期
为 ISO。任何第六项或 caller code 均拒绝。

`parameters_sha256 = SHA256(canonical_json(parameters))`。request ID 固定为：

```json
{
  "schema_version": "m3-g1-baostock-request-v1",
  "endpoint": "query_history_k_data_plus",
  "symbol": "000001.SZ",
  "parameters": [["key","value"], "按 key 排序"]
}
```

每个 spec 构造器重算 request ID。request plan 精确 30 个 request，按 request_id 排序且 symbol 唯一；构造器重算
主设计 §5.4 的 plan envelope。`plan_baostock_reference_requests` 必须从 sample keys 的每 symbol min/max 唯一生成。

### 5.4 raw/receipt identity

raw columns 精确为 fields 顺序：

```text
date,code,open,high,low,close,volume,amount,adjustflag,tradestatus
```

`response_content_sha256` 独立于 Parquet bytes 和 row order，但绑定 endpoint、列名/dtype、重复行和值：按
`(code,date,完整规范行)` 排序后 canonical hash，重复不得去除。stable response hash 与 B2A 同字段语义：

```json
{
  "request_id": "...",
  "endpoint": "query_history_k_data_plus",
  "parameters_sha256": "...",
  "response_content_sha256": "...",
  "row_count": 0,
  "columns": ["..."]
}
```

`receipt_sha256 = SHA256(canonical_json(asdict(receipt)))`。`raw_snapshot_id==request_id`。candidate/receipt 中 raw
paths 必须是相对 `raw_root` 的规范 POSIX 路径，精确指向
`baostock/query_history_k_data_plus/request=<request_id>/{data.parquet,metadata.json}`；拒绝绝对、`..`、反斜杠、
空段、symlink、非普通文件或越界物理身份。Verified response 构造器重建 spec/receipt/receipt hash，核对 frame
row_count/columns/response content；不得暴露未规范 frame 与按另一 frame 计算的 digest。

`CrossSourceSummaryV1.primary_receipt_digests` 与 `reference_receipt_digests` 均精确保存相应 receipt projections 的
`stable_response_sha256`，排序且唯一；不是 Parquet hash、metadata hash 或 receipt JSON bytes hash。

## 6. connector 与 journal 状态机

### 6.1 connector

`fetch_reference_bar_raw` 每次 exact type/range/fields/frequency/adjustflag 校验；把 `000001.SZ` 唯一转换为
`sz.000001`；一次 login、一次 `query_history_k_data_plus`、一次 logout。返回供应商原始 columns/rows/重复/顺序，
不加 `_request_symbol/_endpoint`、不 map、不 cast、不去重。login/query/logout 异常由 executor 脱敏；测试用 fake
client，生产测试不联网。

### 6.2 plan-wide preflight

executor 首先重建 sample/plan 值对象与闭包，然后检查 raw root、journal root 及 30 个 request 目录的完整物理
状态。未知文件、非普通文件、symlink、冲突 intent/candidate/receipt、孤儿 raw、receipt 与 plan 不符时，必须在
创建首个 intent 或网络调用前失败。允许创建尚不存在的空 root 和短暂 no-clobber writer lock；失败时 lock cleanup
不得掩盖主异常，cleanup 自身失败且无主异常必须报告。

### 6.3 单请求状态

固定 `journal/<request_id>/{intent.json,candidate.json,receipt.json}`，严格 JSON UTF-8、拒 duplicate key、未知/
缺字段、NaN/Infinity、字符串数字。写入使用 exclusive temp、file fsync、`os.link` no-clobber、parent dir fsync；
生产路径禁止 `os.replace/os.rename`。

- 完整 receipt：严格 verify 后零网络复用；
- intent+candidate 无 receipt：从 RawStore 完整证据恢复并发布 receipt，零网络；
- 无证据：先 no-clobber intent，再单次 connector 请求，`RawStore.write_request(source="baostock",
  table="query_history_k_data_plus", request_id=...)`，再 candidate、receipt；
- 网络失败：保留 intent，不自动 retry；已提交的更早请求不删除；重跑从现有证据继续；
- 单侧 raw、candidate/raw 冲突、未知状态：失败，不覆盖、不删除、不“修复”。

返回 receipt tuple 按 request_id 排序且与 plan 精确同集。空响应允许 receipt；`row_count>=6000` 作为可能截断失败。

`verify_reference_receipt` 必须要求 receipt path 精确为 journal 固定位置，严格读取 JSON，验证 spec、RawStore metadata/
Parquet、所有 hashes、row_count/columns，并返回完全自证的 `VerifiedReferenceResponse`。

## 7. reconciliation 语义

1. 重建 candidate/policy/sample plan；sample plan 必须等于从 candidate+policy 重新规划的结果。
2. 从 sample plan 重建 request plan；reference responses 必须与 30 个 specs 精确一一对应，重建每个 verified
   object，拒少/多/重复/cross-wire/frame/receipt drift。
3. 每个 raw 行 code 必须等于 request symbol 的 BaoStock code；date 必须在 request start/end；adjustflag 精确 `3`；
   `(code,date)` 任何重复失败。区间 extra date 完整验证后不进 detail。
4. `tradestatus` 只接受 `0/1`。`1` 时 OHLC strict finite positive、volume/amount strict finite nonnegative；bool、
   空串、nan/inf、不可损字符串、List/Struct 拒绝。`0` 时该日期视为 reference missing，空行情字段允许但不当 0。
5. primary 从 candidate bars 逐 sample key读取 open/high/low/close/volume；缺 primary 也形成五个 missing cell，不
   静默删除。detail 精确 3000 行，列/field/missing/tolerance/排序按主设计 §5.6。
6. relative diff：双方存在时 `abs_diff / max(abs(reference), 1e-300)`；缺侧时 diff/tolerance 均按主设计保持 null
   或相应固定容差，不得除零/NaN。价格与 volume matched 公式精确使用 policy。
7. summary 从 detail、sample plan、candidate receipt projections、reference projections 与 policy 全量重算：
   30/20/600/5/3000 守恒，每字段 600，missing rows 按 key 而非 cell 计，mismatch cells/rate、field stats 最大差异、
   detail digest、issues/passed 精确闭合。无可比较值时 field max diff 固定 `0.0`，不得 NaN/null。
8. detail digest 使用 P2 `clean_table_content_sha256(table_name="cross_source_detail", frame=detail)`；summary digest
   使用项目 canonical JSON 对 `asdict(summary)` 求 SHA-256。bundle 构造器从 detail 重算 digest/stats/summary
   digest/issues/passed；涉及 candidate 原始 receipts 的来源证明由 `reconcile_cross_source` 与 P4C 原输入重执行关闭，
   不夸大自包含 bundle 能力。
9. issues 只允许 `CROSS_SOURCE_INCOMPLETE`、`CROSS_SOURCE_MISMATCH`，均为 ERROR，按 P4A `G1QualityIssue` 规则排序；
   passed 当且仅当无 issue。任何 missing row 产生 INCOMPLETE；总 mismatch rate 超过（严格 `>`）policy 才产生
   MISMATCH，等于阈值不产生。

## 8. 必测矩阵

实现者至少覆盖：

1. policy bool/int/NaN/Inf/边界；candidate audit 不通过；证券不足 30、hash 顺序、先选后发现不足 20 日失败；
2. keys/plan/request/parameters 任一漂移，构造器和 executor pre-IO 均失败；特别验证旧“只有 sample hash、没有
   keys”不能绕过 plan closure；
3. connector exact 调用次数/参数/logout；raw columns/order/duplicates 保留；login/query/error 脱敏；
4. plan-wide preflight：第 30 个目录冲突时前 29 个也零 intent/零网络；root/request/file symlink、hardlink/FIFO/
   socket/device、未知文件、祖先替换；
5. journal 首次、有效 receipt 重跑、candidate recovery、intent-only 网络继续、网络中断后跨请求恢复、raw/candidate/
   receipt drift；每个 fsync/link/cleanup/lock fault；静态无 replace/rename；
6. strict JSON duplicate/unknown/missing/string number/NaN/Infinity/非法 UTF-8；绝对/逃逸/反斜杠路径；receipt 与
   spec/raw/frame/hash 多层漂移；row_count 0/5999/6000；
7. 30×20 抽样行序稳定；reference extra dates 忽略、sample 缺行、停牌 0、重复/wrong code/date/adjustflag/
   tradestatus/数值；
8. 价格 atol+rtol、volume denominator、阈值等于/略超、缺一行=5 mismatch、3000 守恒、field max、两类 issue；
9. detail/summary/bundle 单字段、dtype、hash、issues、passed 漂移；整套 summary 自洽替换必须由重新调用
   `reconcile_cross_source` 从 candidate/sample/responses/policy 比较发现；
10. P4B pure planners/reconcile monkeypatch open/socket/RawStore 证明零 IO/网络；只有 executor 可副作用。

独立初验至少增加六类实现者未使用反例，必须包含：

- sample keys 与 request plan 同时伪造为另一自洽集合，executor 用原 sample plan 零副作用拒绝；
- 第 30 个 journal 冲突导致 plan-wide 零增量；
- receipt/frame/receipt_sha/stable hash 全套局部伪造；
- `tradestatus=0` 的空值与 `tradestatus=1` 空值对照；
- 5999/6000 截断边界和 exact mismatch-rate 边界；
- bundle summary/hash/issues/passed wholesale drift，并从原输入重执行比较。

## 9. 验证、报告和迭代

实现报告固定 `docs/M3_G1_P4B跨源证据交付报告.md`；独立初验固定
`docs/M3_G1_P4B跨源证据独立初验报告.md`。报告记录实际模型、文件范围、是否联网、测试数量、故障注入、
脱敏、未实现 P4C。

先跑 P4B/connector 定向测试，再跑全量 pytest、Ruff、mypy。独立初验失败时按“现象—根因—规则—最小复现—
新增测试—通过条件”退回原实现会话；再用全新会话复验，循环至通过。初验通过仅表示可交主 Agent 终验。
