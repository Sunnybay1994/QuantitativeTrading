```python

@dataclass(frozen=True)
class G1BuildInputs:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    responses: tuple[VerifiedRawResponse, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    signal_start: dt.date
    signal_end: dt.date
    history: HistoryWindow
    expected_constituent_count: int
    factor_ratio_rtol: float

@dataclass(frozen=True)
class G1ReceiptProjectionV1:
    source: Literal["tushare", "baostock"]
    request_id: str
    endpoint: str
    parameters_sha256: str
    stable_response_sha256: str
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class G1Candidate:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    bars: pl.DataFrame
    adjustment_factors: pl.DataFrame
    factor_match_evidence: pl.DataFrame
    benchmark_bars: pl.DataFrame
    suspensions: pl.DataFrame
    price_limits: pl.DataFrame
    corporate_actions: pl.DataFrame
    corporate_action_selection_evidence: pl.DataFrame
    corporate_action_reconciliation: pl.DataFrame
    table_content_digests: tuple[tuple[str, str], ...]
    price_limit_required_keys_sha256: str
    primary_candidate_key: str

@dataclass(frozen=True)
class CrossSourceSamplePlan:
    schema_version: Literal["m3-g1-cross-source-sample-v1"]
    primary_candidate_key: str
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    keys: tuple[tuple[str, dt.date], ...]
    sample_plan_sha256: str

@dataclass(frozen=True)
class CrossSourceReconciliationBundle:
    sample_plan: CrossSourceSamplePlan
    reference_receipts: tuple[G1ReceiptProjectionV1, ...]
    detail: pl.DataFrame
    detail_sha256: str
    summary: CrossSourceSummaryV1
    summary_sha256: str
    issues: tuple[G1QualityIssue, ...]
    passed: bool

@dataclass(frozen=True)
class G1PrimaryAuditResult:
    primary_candidate_key: str
    plan_sha256: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    table_content_digests: tuple[tuple[str, str], ...]
    issues: tuple[G1QualityIssue, ...]
    passed: bool

@dataclass(frozen=True)
class G1ArtifactEntryV1:
    path: str
    sha256: str
    content_sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    table_schema_version: str
    key_columns: tuple[str, ...]
    min_key: tuple[str, ...] | None
    max_key: tuple[str, ...] | None

@dataclass(frozen=True)
class G1QualityIssueV1:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class G1QualityReportV1:
    schema_version: Literal["m3-g1-quality-v1"]
    release_id: str
    primary_candidate_key: str
    plan_sha256: str
    error_count: int
    warning_count: int
    passed: bool
    issues: tuple[G1QualityIssueV1, ...]

@dataclass(frozen=True)
class CrossSourceFieldStatsV1:
    field: Literal["open", "high", "low", "close", "volume"]
    comparison_count: int
    mismatch_count: int
    max_abs_diff: float
    max_relative_diff: float

@dataclass(frozen=True)
class CrossSourceSummaryV1:
    schema_version: Literal["m3-g1-cross-source-v1"]
    primary_candidate_key: str
    sample_plan_sha256: str
    sample_symbol_count: int
    dates_per_symbol: int
    key_count: int
    field_count: int
    comparison_count: int
    primary_receipt_digests: tuple[str, ...]
    reference_receipt_digests: tuple[str, ...]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float
    missing_primary_rows: int
    missing_reference_rows: int
    mismatch_cells: int
    mismatch_rate: float
    field_stats: tuple[CrossSourceFieldStatsV1, ...]
    detail_sha256: str
    passed: bool

@dataclass(frozen=True)
class G1ManifestV1:
    schema_version: Literal["m3-g1-manifest-v1"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

@dataclass(frozen=True)
class G1Release:
    release_id: str
    root: Path
    manifest_path: Path
    quality_path: Path

@dataclass(frozen=True)
class G1CrossSourcePolicy:
    reference_source: Literal["baostock"]
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float

@dataclass(frozen=True)
class G1ReleaseInputs:
    build_inputs: G1BuildInputs
    cross_source_policy: G1CrossSourcePolicy
    reference_responses: tuple[VerifiedReferenceResponse, ...]

@dataclass(frozen=True)
class G1PreparedRelease:
    candidate: G1Candidate
    primary_audit: G1PrimaryAuditResult
    reconciliation: CrossSourceReconciliationBundle
    release_id: str
    quality: G1QualityReportV1

@dataclass(frozen=True)
class VerifiedG1Release:
    release: G1Release
    manifest: G1ManifestV1
    manifest_sha256: str
    quality: G1QualityReportV1
    quality_sha256: str
    artifact_paths: tuple[tuple[str, Path], ...]

def plan_index_weight_requests(
    *, index_code: str, start: dt.date, end: dt.date, warmup_months: int,
) -> TushareRequestBatch: ...

def resolve_history_window(
    *, open_dates: Sequence[dt.date], signal_start: dt.date, signal_end: dt.date,
    feature_warmup_sessions: int, label_tail_sessions: int,
) -> HistoryWindow: ...

def plan_history_requests(
    *, index_weight_batch: TushareRequestBatch, symbols: Sequence[str],
    benchmark: str, history: HistoryWindow,
) -> G1RequestPlan: ...

def execute_tushare_batch(
    *, batch: TushareRequestBatch, connector: TushareConnector,
    raw_store: RawStore, journal_root: Path,
    endpoint_policies: Mapping[str, EndpointPolicy],
    request_rate_per_minute: int, max_attempts: int, retry_base_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[BaseException], str],
) -> tuple[TushareRequestReceipt, ...]: ...

def verify_tushare_receipt(
    *, spec: TushareRequestSpec, receipt_path: Path, raw_root: Path,
    journal_root: Path, policy: EndpointPolicy,
) -> VerifiedRawResponse: ...

def normalize_index_weight_observations(
    *, batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse], universe: str,
) -> pl.DataFrame: ...

def apply_adjustment_factors_strict(
    *, bars: pl.DataFrame, adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    factor_responses: Sequence[VerifiedRawResponse],
) -> AdjustmentApplicationResult: ...

def build_observed_membership(
    *, observations: pl.DataFrame, calendars: pl.DataFrame,
    instruments: pl.DataFrame, universe: str,
    signal_start: dt.date, signal_end: dt.date,
    expected_constituent_count: int,
) -> ObservedMembershipResult: ...

def verify_observed_membership_result(
    *, batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    result: ObservedMembershipResult,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> None: ...

def clean_table_content_sha256(
    *, table_name: str, frame: pl.DataFrame,
) -> str: ...

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

def reconcile_g1_corporate_actions(
    *, corporate_actions: pl.DataFrame, bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    suspensions: pl.DataFrame, calendars: pl.DataFrame,
    history: HistoryWindow, factor_ratio_rtol: float,
) -> CorporateActionReconciliationResult: ...

def build_g1_candidate(
    *, inputs: G1BuildInputs,
) -> G1Candidate: ...

def verify_g1_candidate(
    *, inputs: G1BuildInputs, candidate: G1Candidate,
) -> None: ...

def plan_cross_source_reconciliation(
    *, candidate: G1Candidate, policy: G1CrossSourcePolicy,
) -> CrossSourceSamplePlan: ...

def plan_baostock_reference_requests(
    *, sample_plan: CrossSourceSamplePlan,
) -> ReferenceRequestPlanV1: ...

def execute_baostock_reference_plan(
    *, sample_plan: CrossSourceSamplePlan, plan: ReferenceRequestPlanV1,
    connector: BaostockConnector,
    raw_store: RawStore, journal_root: Path,
) -> tuple[ReferenceRequestReceipt, ...]: ...

def verify_reference_receipt(
    *, spec: ReferenceRequestSpec, receipt_path: Path,
    raw_root: Path, journal_root: Path,
) -> VerifiedReferenceResponse: ...

def reconcile_cross_source(
    *, candidate: G1Candidate, sample_plan: CrossSourceSamplePlan,
    reference_responses: Sequence[VerifiedReferenceResponse],
    policy: G1CrossSourcePolicy,
) -> CrossSourceReconciliationBundle: ...

def audit_g1_candidate(
    *, candidate: G1Candidate,
) -> G1PrimaryAuditResult: ...

def prepare_g1_release(
    *, inputs: G1ReleaseInputs,
) -> G1PreparedRelease: ...

def publish_g1_release(
    *, output_root: Path, inputs: G1ReleaseInputs,
) -> G1Release: ...

def verify_g1_release(*, release: G1Release) -> VerifiedG1Release: ...

def read_g1_manifest(path: Path) -> G1ManifestV1: ...
def read_g1_quality(path: Path) -> G1QualityReportV1: ...
def read_cross_source_summary(path: Path) -> CrossSourceSummaryV1: ...
```

标准化观察与基准行情必须使用领域 Schema，而不是散落在 mapper 中的临时列约定：

```python
class IndexConstituentObservationSchema(pa.DataFrameModel):
    universe: str  # CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1
    observation_date: pl.Date
    symbol: str  # 六位 .SH/.SZ A 股代码
    weight: float  # 正且 finite
    source: str  # tushare
    source_snapshot_id: str  # 小写 64 位 hex

class BenchmarkBar1dSchema(pa.DataFrameModel):
    benchmark: str
    trade_date: pl.Date
    open: float
    high: float
    low: float
    close: float
    source: str
    source_snapshot_id: str
```

G1 核心 mapper 首版固定放在 `quant.data.m3_mappers`，只接受 B2A 的 `VerifiedRawResponse`，不接受裸
DataFrame、调用方自报 symbol/source/snapshot 或配置路径。四个函数输出列顺序与语义固定为：

| 函数 | endpoint | 精确输出列 |
|---|---|---|
| `map_g1_daily_response` | `daily` | `symbol,trade_date,open,high,low,close,volume,amount,source` |
| `map_g1_adjustment_factor_response` | `adj_factor` | `symbol,effective_date,adj_factor,source` |
| `map_g1_benchmark_response` | `fund_daily` + 分段 `fund_adj` + `fund_div` | `benchmark,trade_date,open,high,low,close,source,source_snapshot_id` |
| `map_g1_suspension_response` | `suspend_d` | `symbol,trade_date,suspension_scope,suspension_detail,source,source_snapshot_id` |

`daily` 输出是尚未拼接 factor 的 G1 内部表，不得伪造 `adj_factor=1.0`；B4 的
`apply_adjustment_factors_strict` 才生成通过 `Bar1dSchema` 的最终表和 factor-match evidence。
`adj_factor` 输出必须逐供应商交易日保留，即使相邻值相同也不得压缩。前两张表没有逐行
`source_snapshot_id` 字段，其血缘由 `G1Candidate.input_receipts`、factor-match evidence 与 manifest 的精确
receipt 闭包绑定；不得为
“看起来统一”而修改现有 `Bar1dSchema/AdjustmentFactorSchema`。基准和停牌 Schema 已有该字段，值必须来自
`response.receipt.raw_snapshot_id`。四张表的 `source` 固定为 `tushare`，调用方不可覆盖。

mapper 必须在读取行值前重建并重验 exact `VerifiedRawResponse`：使用生产构造边界重新证明 spec 的规范
request identity、receipt 与 spec 的 endpoint/parameters/fields/columns/row count 闭包、规范 receipt bytes
hash，以及 frame 的 columns/row count/content digest。`frozen=True` 和对象曾经构造成功不能代替消费时
identity 闭包；重验失败统一脱敏为 `G1_MAPPER_RESPONSE_INVALID`。闭包通过后再核对 endpoint、请求参数与
响应范围。逐证券 endpoint 的每个 `ts_code` 必须等于 spec 的 `ts_code`；基准首版只允许
`510300.SH`；A 股代码只允许六位数字加 `.SH/.SZ`。日期严格解析 `YYYYMMDD`，数值 strict cast，拒绝
null/NaN/Infinity、非法 OHLC、负 volume/amount、非正 factor、响应越过请求日期范围和不可规范化代码。
Tushare `vol` 从手换算为股（`*100`），`amount` 从千元换算为元（`*1000`）。

`daily/adj_factor/index_daily` 的业务键重复必须拒绝，不得 `unique(keep="last")`。`suspend_d` 是唯一允许在
raw 留档后按 `(symbol,trade_date)` 合并多行的核心 mapper：`suspend_type` 必须为 `S`；全部
`suspend_timing=null` 映射一个 `FULL_DAY/null`；全部非空映射 `PARTIAL`，相同 detail 去重后按 Unicode
码点排序，以精确分隔符 `" | "` 连接；FULL/PARTIAL 同日冲突失败。空 `suspend_d` 返回带固定 dtype 的
零行表，其余三个 endpoint 的空 verified response 在 mapper 边界再次 fail-closed。

`M3G1MappingError` 的 `str()` 只允许稳定 code：
`G1_MAPPER_RESPONSE_INVALID`、`G1_MAPPER_ENDPOINT_MISMATCH`、`G1_MAPPER_EMPTY`、
`G1_MAPPER_COLUMNS_INVALID`、`G1_MAPPER_REQUEST_SCOPE_MISMATCH`、`G1_MAPPER_VALUE_INVALID`、
`G1_MAPPER_DUPLICATE_KEY`、`G1_MAPPER_SUSPENSION_CONFLICT`、`G1_MAPPER_SCHEMA_INVALID`。公开边界不得
泄露原始行、receipt/client repr、token 或绝对路径；底层 Polars/Pandera 异常使用 `from None` 转换。
输出按各自业务键稳定升序，并由对应领域 Schema 或本节内部列契约验证。

涨跌停与公司行动虽然也消费 `VerifiedRawResponse`，但它们依赖“合法无限制日”规则证据、公告版本选择与
factor-ratio 对账，不属于核心机械映射。首版由 G1-P3/B2C 专用任务书实现、B4 重验发布；不得在 B2B 为赶进度先写
`null -> unlimited`、`keep="last"` 或简化 dividend mapper。

观察唯一键为 `(universe,observation_date,symbol,source)`；同一来源同一观察日必须恰好形成一个完整
CSI300 状态，不得把同月多次观察合并成一个月末状态。研究基准固定为可交易 ETF `510300.SH`，只通过
`BenchmarkBar1dSchema` 校验；不得为通过 A 股代码正则而伪装成 SH/SZ symbol。

请求与发布语义：

- `request_id` 是 endpoint 与排序后参数规范化 JSON 的 SHA-256；参数必须显式包含稳定 `fields`，
  不得包含 token、客户端对象、重试次数、调用时间或绝对路径。`TushareRequestSpec.create`
  是唯一构造边界；executor 在任何 IO 前必须重算 request ID。
- 七个 endpoint 的 `fields` 使用代码中一份常量表，首版精确为：

  | endpoint | fields（顺序也是契约） |
  |---|---|
  | `index_weight` | `index_code,con_code,trade_date,weight` |
  | `daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` |
  | `adj_factor` | `ts_code,trade_date,adj_factor` |
  | `index_daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` |
  | `suspend_d` | `ts_code,trade_date,suspend_timing,suspend_type` |
  | `stk_limit` | `trade_date,ts_code,pre_close,up_limit,down_limit` |
  | `dividend` | `ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share` |

  planner 不接受任意 fields 覆盖；字段不足或额外字段都必须形成不同 request ID，mapper
  严格拒绝缺字段。
- `index_weight` 从 `signal_start` 所在月向前推 `membership_warmup_months`，直到
  `signal_end` 所在月，每个请求都使用该自然月的完整首尾，不 clamp 到 signal 日；history 第二阶段只能在全部
  权重 receipt 通过、历史成分并集确定后生成。`daily/adj_factor` 按单证券完整 history window 请求，
  `index_daily` 单独请求基准，`suspend_d` 按月请求全市场后过滤成分并集；`stk_limit` 按证券请求完整
  history window，`dividend` 按证券请求全历史后只保留 history window 内已实施事件。
- `resolve_history_window` 要求 signal start/end 本身都是已验真 SH 开市日，不自动对齐。
  history start 是 signal start 之前精确 `feature_warmup_sessions` 个 SH session，history end 是 signal end
  之后精确 `label_tail_sessions` 个 SH session；日历不足即失败。所有证券 planner 入口使用领域契约，
  A 股只接受六位数字加 `.SH/.SZ`，不复用只检查“全数字”的宽松 connector helper。
- executor 首版严格串行并使用单调时钟限频。只重试 connector 显式转换的 typed
  `NETWORK/RATE_LIMIT/TRANSIENT_SERVER` 错误；权限、字段、契约或未分类的 SDK 字符串异常均
  fail-closed。首次网络尝试立即执行；后续尝试的最早时刻是“上次尝试开始 + 限频间隔”与
  “上次失败 + `retry_base_seconds * 2**(attempt-1)`”两个 deadline 的较晚者。缓存命中和
  journal 恢复不计网络尝试、不限频；重试不得改 request ID。
- 每次 API 原始响应原样写 `RawStore`，不得在 raw 前 `unique(keep="last")`。receipt 只有 raw data、
  metadata、行数、字段和 hash 全部验证后才原子发布。receipt 已存在且有效则不联网；存在但损坏
  立即失败。响应行数等于 endpoint 上限时视为可能截断，不发布成功 receipt。
- endpoint 的空响应与截断规则分别配置，禁止用一个全局 `row_limit_guard` 推断所有接口。首版项目
  fail-closed 单请求行数安全阈值为
  `daily=6000`、`adj_factor=6000`、`index_daily=5000`、`index_weight=5000`、`suspend_d=5000`、
  `stk_limit=5800`、`dividend=5000`。这些不得被表述为供应商的统一最大页长；返回行数等于
  安全阈值即失败。`index_weight/daily/adj_factor/index_daily/stk_limit=REJECT`，
  `suspend_d/dividend=ALLOW`。`dividend` 空表只表示该证券无可用分红记录，不能作为跳过 factor
  跳变对账的理由。
- receipt 是 request journal 的已提交态。每个 request 使用确定目录
  `journal/<request_id>/{intent.json,candidate.json,receipt.json}`；`intent` 在连网前原子发布，
  `candidate` 在 raw data+metadata 都完整验真后绑定它们。首版固定布局只允许一个
  `candidate.json`：它不存在且没有 raw 证据时才允许联网；存在且与 intent/raw 完全一致时恢复 receipt；
  candidate 冲突，或 request journal 目录出现第二个 candidate-like/未知普通文件时均失败。单有不完整
  data 而无可验真 metadata 不得冒充恢复成功；需要人工处理该孤儿后才可重试。所有相对路径必须
  规范化并仍位于受控 root 内。
- receipt 的 `raw_file_sha256/raw_metadata_sha256/raw_snapshot_id/path` 用于物理证据验真；
  `stable_response_sha256` 只规范 hash request ID、endpoint、parameters hash、response content hash、
  row count 与 columns，不含抓取时间、物理路径或 metadata hash。DataFrame 内容 digest 用固定列顺序、
  业务键排序和类型标签的规范 JSON 行计算；日期用 ISO、finite float 用唯一十进制编码、
  `-0.0` 归一为 `0.0`、null 保留，不得以 Parquet 文件字节代替逻辑内容 digest。raw 仍保留供应商原顺序和重复行。
- `execute_tushare_batch` 不写 clean。最终 `G1RequestPlan` 的 request ID 集与 verified receipt 集必须
  精确相等，少一个、多一个、重复或跨 plan receipt 均不得构建 candidate。只有全局质量门禁无 ERROR 后，才允许
  `publish_g1_release` 在临时目录组装，完成文件 hash/manifest 后原子 rename 为 immutable release。
  失败或进程中断不得把半套数据写入现有 `data/clean/bar_1d`。
- `publish_g1_release` 不读取配置文件，也不反向 import `quant.research`；它只接收已验证的
  `config_version/g1_config_sha256` 并绑定到 release ID/manifest。G1 stage handler 在调用任何可能写入的
  data-layer 函数前，必须用 C0 唯一 selector 从同一 `LoadedM3Config` 复算该 hash；G9 再从冻结配置独立
  复算。release identity 还绑定全部输入 receipt 和规范化 clean 内容，不绑定 config 物理路径、抓取时间
  或本机路径。
