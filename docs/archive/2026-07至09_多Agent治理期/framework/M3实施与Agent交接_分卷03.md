```python

def verify_provider_artifact(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
) -> VerifiedProviderArtifact: ...

def verify_provider_validation_artifact(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderValidationArtifact: ...
```

validation verifier 必须接收已经冻结的 `ProviderValidationSpec`，用它独立重算 formal/development key 和
完整 deterministic probe；不得从 details 自报 keys 反构造“期望计划”。无 `spec` 的旧签名不能证明
`provider_validation_key`，已经废止。

输出 staging 列固定为 `symbol,date,open,high,low,close,vwap,volume,factor`，每证券一个 Parquet，日期
升序。必须先按 `source` 过滤 bars，按 `universe` 过滤 membership 并取得历史 symbol 并集，再用该
并集过滤 bars；**不得**按 membership effective interval 删除行情。重复键必须拒绝。交易日域统一使用 SH session
calendar，不得把 SH/SZ 开市日做并集。finite 检查在选源后执行；OHLC/amount/volume/factor 任一
null、NaN 或正负 infinity 都必须拒绝，
且 emitted row 的 amount/volume 均须为正。`to_qlib_symbol`/`from_qlib_symbol` 是项目与 Qlib 证券代码
互转的唯一 SSOT，必须互为逆函数并支持 Qlib 返回的大小写形式。
`SnapshotSessionCalendarSchema` 的唯一定义位于 `quant.domain.schemas`，严格只有非空、唯一、严格升序的
单列 `date: pl.Date`；不保存 `is_connect_open/is_half_day`，避免与 SH session 无关的字段改变 provider。
snapshot 必须发布 `session_calendar.parquet`：它由通过 `TradeCalendarSchema` 的权威日历中过滤
`market="SH"`、`is_open=true` 和显式 `[history_start,history_end]` 得到，日期唯一且严格递增；其日期域来自
G1 release/config 的 warmup 至 label tail 请求，不从 staging 的实际日期并集反推。发布 snapshot 前，全部
staging 日期并集必须与该权威 session 列表完全一致；若某个权威开市日所有证券都缺行，snapshot 直接失败，
不得让 dump 工具静默删掉该日。

manifest 顶层字段精确以 `SnapshotManifestV1` 为准，其中业务字段包含
`source,universe,g1_release_id,g1_release_manifest_sha256,snapshot_config_sha256,config_version,row_count,
symbol_count,min_date,max_date,history_start,history_end,signal_start,signal_end,session_calendar_sha256,session_count,
schema_version,staging_format,adjustment_formula_version,adjustment_spec_sha256`；`staging_format` 固定为 `parquet`，不得把下游 `provider_format`
写进 snapshot，
每个数据文件条目至少包含相对路径、大小、SHA-256、symbol、行数和最小/最大日期。
manifest 不再读取或 hash 整份 TOML；否则只改 tracking URI 也会伪造新 snapshot。调用者只能传入 C0
已验证的 narrow `snapshot_config_sha256`，函数校验 64 位小写 hex。`config_path` 旧签名废止。

G1 manifest 必须公开 `signal_start/signal_end/history_start/history_end`。snapshot spec 的 history 首尾只能
与其中 `history_start/history_end` 精确相等；不得在保持 `snapshot_config_sha256` 和 request key 不变时由
caller 另传窗口。snapshot manifest 和 `SnapshotRequestRecordV1` 的 `signal_start/signal_end` 也必须从该
verified G1 manifest 投影，不接受 caller 另传。request record 是 request key 到内容 `snapshot_id` 的唯一严格映射，其
request/hash/G1/config/code/date 字段全部重算；它不进入 snapshot manifest 的内容 ID。snapshot temp 的
Parquet 写参数固定为 zstd level 3、statistics 开启、row group 65536、Polars native writer。

`snapshot.py` 到此为止，不 import Qlib、不启动 dump。`QlibDumpToolSpec` 唯一定义在 `contracts.py`；
`fetch_qlib_tool.build_qlib_dump_tool_spec` 从 C0 已验证的扁平字段
`runtime.qlib.dump_script_url/dump_script_sha256/dump_script_bytes/version` 显式映射并固定
`command="dump_all"`。`ensure_qlib_dump_tool` 不解析 TOML，只接收该 spec；现有
`fetch_qlib_tool.py` 中第二个 TOML reader 必须删除。
`provider.py` 负责标准库子进程与结构检查；只有
`qlib_adapter.py` 的 fresh worker 入口可以 import Qlib。`materialize_qlib_provider` 只接受 StageRunner 分配的空临时
output dir，以参数数组和 `shell=False` 调用**当前 WSL base 的同一 Python**：

```text
<python> <pinned dump_bin.py> dump_all
  --data_path <staging> --qlib_dir <stage-temp>/provider --freq day
  --file_suffix .parquet --date_field_name date --symbol_field_name symbol
  --include_fields open,high,low,close,vwap,volume,factor --max_workers 1
```

最终物理布局唯一为 `providers/<provider_key>/provider/{calendars,instruments,features}` 与同级
`provider_manifest.json`；validation 位于
`providers/<provider_key>/provider-validation/key=<provider_validation_key>/`。`--qlib_dir` 永远指向
stage temp 的 `provider/` 子目录。manifest 的 `files` 只列该子目录内普通文件，不列 manifest、receipt 或
validation，避免自引用。

禁止 `dump_fix/dump_update/limit_nums/backup_dir`、非空 output、shell、隐式默认 fields 或调用者提供任意
额外 argv。运行前重新校验脚本 URL 对应的固定 bytes/SHA、snapshot manifest 和全部 staging digest；
运行后无论 exit code 是否为 0 都执行结构验真。官方脚本会把值写成 little-endian float32、按全局 calendar
对证券起止区间 reindex，并会自行 drop duplicate date，因此上游仍须先拒绝重复，不能依赖脚本“修复”。

materializer 在任何副作用前重算 runtime fingerprint hash、要求 tool spec 与运行时 Qlib version 一致，并
调用 E3 唯一 `compute_provider_key` 重算 `spec.provider_key`；调用者自报 key/version/hash 不一致即失败。
provider runtime fingerprint 精确记录当前 Python、NumPy、pandas、PyArrow、Qlib、Fire、tqdm 和 Loguru
版本；这些包任一变化必须改变 provider key。只改变 LightGBM 不改变 provider；完整 dependency
fingerprint 仍进入 experiment。provider manifest 使用稳定 schema version，记录 snapshot/provider/config/
tool/code/runtime identities、逻辑 argv、calendar/instrument 摘要及所有生成普通文件的相对路径/大小/hash，
不记录绝对路径、wall-clock、PID 或非确定性 stdout。manifest 的稳定逻辑 argv 固定为
`<PYTHON> <DUMP_TOOL> dump_all --data_path <SNAPSHOT_STAGING> --qlib_dir <PROVIDER_TEMP>/provider ...`；
真实绝对 argv 只传 subprocess，不落盘。

`inspect_provider_structure` 不 import Qlib，严格验证：`calendars/day.txt` 等于 snapshot 发布的权威
`session_calendar.parquet` 且升序
唯一；`instruments/all.txt` 恰为 staging symbol 集及各自 min/max；每个 symbol 只有七个
`<field>.day.bin`，无额外 symbol/field；bin 首 float32 是正确 calendar offset，字节数等于该证券全局
calendar 起止跨度的 `4*(1+n)`，实际 staging 日期有限值、缺口位置 NaN。所有 symlink 和未声明文件失败。

正式 G1 长时 I/O 期间允许使用 development example 轨做工程反馈，但必须保持独立信任域：开发 Provider
materializer 只接受 `VerifiedDevelopmentExampleSnapshotArtifact` 并返回与正式路径同形的未发布
`ProviderBuildResult`；只有开发最终 verifier 返回
`VerifiedDevelopmentExampleProviderArtifact(release_kind="development_example",
formal_gate_eligible=False, example_id=...)`；identity 使用带固定 domain tag 和 `example_id` 的
`compute_development_provider_key`，receipt stage 固定为 `development-provider`，输出根名必须同时显式包含
`development` 与 `example`。正式 `materialize_qlib_provider/verify_provider_artifact` 只接受精确
`VerifiedSnapshotArtifact`，不得用 union、包装或重命名把开发对象提升为 `VerifiedProviderArtifact`。开发轨
复用同一个 `ProviderManifestV1`、七字段 bin 格式和静态 inspector，仅证明开发契约、跨平台兼容和编排恢复；
不证明正式 G2B/G2C、真实数据覆盖/性能或任何 Gate。开发 fixture 固定为 21 个连续 SH session；
`000001.SZ` 因一个全日停牌输出 20 行，另两证券各输出 21 行，同时保留公司行动/复权和退市生命周期边界。
因此开发轨可原样运行下述 G2C `3×20×7` sampling policy，不放宽正式规则。开发 G2C 另用
`compute_development_provider_validation_key` 的固定 domain tag/`example_id`、
`development-provider-validation` receipt stage 和开发专用 nominal verified 类型闭合；正式入口仍精确拒绝
开发类型。该结果只证明 development example 的 fresh-process 公共 API、确定性抽样和跨平台工程契约，
不提升为正式 `VerifiedProviderValidationArtifact`。

probe 不是随机数调用：策略固定为 `provider_market_stratified_hash_first_last_v1`，先按
规范 JSON 数组 `["provider-symbol-v1",snapshot_id,provider_key,symbol]` 的 SHA-256 各选 1 个 SH/SZ，再选
剩余最低 hash 证券；每证券必须至少 20 个 staging 行，日期包含首尾并以
`["provider-date-v1",provider_key,symbol,date]` 的规范数组 hash 选 18 个内部日期。另每证券最多选 5 个
区间内 staging 缺口，gap 排名固定使用规范数组
`["provider-gap-date-v1",provider_key,symbol,date]`。禁止直接字符串拼接。
最终 emitted 样本恰为 3 证券×20 日期，共 60 keys/420 field comparisons；gap 是另外的 0–15 keys/
0–105 comparisons。两类计数在 summary 分开记录。通过 fresh Python/Qlib API 回读；值必须等于 staging 值转
little-endian float32 后的结果并比较 UInt32 bit pattern。gap 的 API row 缺失或显式 NaN 都合法并分别记录，
任何 finite gap 值失败。calendar/instrument 也通过 Qlib API 全量核对。
不足 3 证券、任一市场缺失、某样本不足 20 日、Qlib 不可导入、版本/identity 不符或任一差异都失败，
不得退化为少量 sample。PID 只允许父进程测试 spy 实时观察，不写持久产物；持久 summary 记录 worker
protocol version、fresh-process enforced、provider URI hash、runtime hash 与 parent import/read audit。
details 和 summary 分别发布 `provider_validation.parquet/json`；严格 reader 拒绝未知/缺失字段、duplicate
JSON key、NaN 和宽松数字转换。details 对 gap 的 NaN 规范化为 nullable null，并保留 `api_row_present/status`；
summary 必须绑定完整 probe/details/API 摘要并重算 missing/extra/duplicate/non-finite/mismatch/gap-filled/
calendar/instrument 八类计数，不能只有 caller 自报 `passed`。

### 4.3 `labels.py`

G3A/G3B 分包同样以
[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)
为现行执行入口。标签 artifact 额外绑定直接输入 `bars_sha256` 与 experiment manifest；G3B 只接收 verified
G1/snapshot/provider/provider-validation/label bundle，并在 fresh worker 前关闭所有混配。G3B 发布后必须由
`verify_label_reconciliation_artifact` 重建 `VerifiedLabelReconciliationArtifact`；G9 不接受裸 summary 或
caller 自报 reconciliation receipt hash。

```python
@dataclass(frozen=True)
class LabelBuildResult:
    labels: pl.DataFrame
    diagnostics: pl.DataFrame

@dataclass(frozen=True)
class ExperimentIdentityManifestV1:
    schema_version: Literal["m3-experiment-identity-v1"]
    experiment_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

@dataclass(frozen=True)
class ExperimentIdentitySpec:
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

@dataclass(frozen=True)
class VerifiedExperimentIdentity:
    root: Path
    manifest: ExperimentIdentityManifestV1
    manifest_sha256: str
    experiment_receipt_sha256: str

def read_experiment_identity_manifest(path: Path) -> ExperimentIdentityManifestV1: ...

def verify_experiment_identity(
    *, experiment_root: Path, experiment_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedExperimentIdentity: ...

@dataclass(frozen=True)
class LabelBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    horizon_sessions: Literal[5, 10]
    benchmark: Literal["510300.SH"]
    label_version: str
    label_build_code_version: str

@dataclass(frozen=True)
class LabelArtifactManifest:
    schema_version: Literal["m3-label-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    horizon_sessions: int
    benchmark: str
    label_version: str
    label_build_code_version: str
    eligible_keys_sha256: str
    bars_sha256: str
    session_calendar_sha256: str
    benchmark_bars_sha256: str
    labels_sha256: str
    labels_row_count: int
    label_key_sha256: str
    diagnostics_sha256: str
    diagnostics_row_count: int
    diagnostic_key_sha256: str
    candidate_count: int
    success_count: int
    diagnostic_count: int

@dataclass(frozen=True)
class VerifiedLabelArtifact:
    root: Path
    labels: pl.DataFrame
    diagnostics: pl.DataFrame
    manifest: LabelArtifactManifest
    manifest_sha256: str
    label_receipt_sha256: str

def build_label_artifact(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec, output_root: Path,
) -> LabelArtifactManifest: ...

def read_label_artifact_manifest(path: Path) -> LabelArtifactManifest: ...

def verify_label_artifact(
    *, label_root: Path, label_receipt_path: Path,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedLabelArtifact: ...

def compute_forward_relative_labels(
    *,
    bars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    calendars: pl.DataFrame,
    horizons: Sequence[int],
    benchmark: str,
    label_version: str,
) -> LabelBuildResult: ...

@dataclass(frozen=True)
class LabelReconciliationSummaryV1:
    schema_version: Literal["m3-label-reconciliation-v1"]
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: int
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: str
    qlib_version: str
    qlib_expression: str
    details_sha256: str
    row_count: int
    row_key_sha256: str
    missing_key_count: int
    extra_key_count: int
    duplicate_key_count: int
    non_finite_count: int
    expression_direct_max_abs_error: float
    expression_direct_p99_abs_error: float
    benchmark_max_abs_error: float
    benchmark_p99_abs_error: float
    raw_label_max_abs_error: float
    raw_label_p99_abs_error: float
    relative_label_max_abs_error: float
    relative_label_p99_abs_error: float
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float
    passed: bool

@dataclass(frozen=True)
class LabelReconciliationResult:
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1

@dataclass(frozen=True)
class VerifiedLabelReconciliationArtifact:
    root: Path
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1
    summary_sha256: str
    reconciliation_receipt_sha256: str

@dataclass(frozen=True)
class LabelReconciliationSpec:
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: Literal[5, 10]
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: Literal["m3-qlib-worker-v1"]
    qlib_version: Literal["0.9.7"]
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float

@dataclass(frozen=True)
class LabelReconciliationReceiptPaths:
    snapshot_receipt_path: Path
    provider_receipt_path: Path
    provider_validation_receipt_path: Path
    experiment_receipt_path: Path
    label_receipt_path: Path

def read_label_reconciliation_summary(path: Path) -> LabelReconciliationSummaryV1: ...

def verify_label_reconciliation_artifact(
    *, reconciliation_root: Path, reconciliation_receipt_path: Path,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    labels: VerifiedLabelArtifact,
    config: LoadedM3Config, spec: LabelReconciliationSpec,
    receipt_paths: LabelReconciliationReceiptPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedLabelReconciliationArtifact: ...

def reconcile_labels_with_qlib(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    labels: VerifiedLabelArtifact, config: LoadedM3Config,
    spec: LabelReconciliationSpec,
    receipt_paths: LabelReconciliationReceiptPaths,
    artifact_roots: Mapping[str, Path],
    python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> LabelReconciliationResult: ...
```

G3B 不从目录扫描或按 hash 猜上游 receipt。formal/development reconcile 与 verifier 都显式接收五条
`LabelReconciliationReceiptPaths` 和完整 `artifact_roots`，并在启动 worker 前通过共享
`verify_stage_receipt_with_bytes` 核对 receipt bytes、stage/scope/scope_key、nominal SHA 与 root registry。
reconciliation receipt 的输入闭包精确为：experiment receipt+manifest；G1 manifest+benchmark；snapshot
receipt+manifest+session calendar；provider receipt+manifest+严格完整 provider tree；provider-validation
receipt+summary+details；label receipt+manifest+labels+diagnostics。输出严格只有
`reconciliation.parquet,reconciliation.json`。

development 路径必须使用独立 development nominal/key/API/stage，key 绑定 development domain tag 与
`example_id`，输出根名同时含 development/example，且 `formal_gate_eligible=False`；formal exact-type
入口拒绝 development nominal。worker 的 request/echo 完整绑定 config、dependency、code version，并在
import Qlib 前重算 row-key 与逻辑 provider URI hash。summary 的 `row_count` 是实际 details 行数；与
missing/extra/duplicate 三个计数及 verified label manifest 的 success count 共同证明期望/匹配行数闭包，
不再另设含义重叠的 expected/matched 字段。`non_finite_count` 固定为六个数值输入槽位的非 finite/缺失
cell 数；`-0.0` 的逻辑摘要规范化为 `0.0`。

返回值必须通过 `ForwardReturnLabelSchema`。不得用自然日位移；所有偏移基于对应市场开市日序号。
`calendars` 必须先通过 `TradeCalendarSchema`；过滤 SH 后日期仍须唯一、严格递增，重复 session 不能被 sort/
dict 静默合并或当作两个交易日。对任何成功样本，`return_end_date` 不得早于 `return_start_date`；`h=1`
表示同一下一 session 的 open-to-close，允许两日期相等，只有 `h>1` 时 end 才必须严格晚于 start。M3 v1
生产配置仍只允许 h=5/10。
尾部没有完整 horizon 的样本直接不输出。证券 entry/exit 两端都必须有正且 finite 的 adj_factor；
停牌缺价不得补值。需要以含除权事件的手算 fixture 对账，再与 Qlib 调整后价格表达式逐行对账。

`eligible_keys` 是样本候选 SSOT；不得遍历历史成分并集后把非成员日期也计为缺失。diagnostics 固定列为
`as_of,horizon_sessions,reason,sample_count`，reason 至少包括：`TAIL_INCOMPLETE`、
`BENCHMARK_ENTRY_MISSING`、`BENCHMARK_EXIT_MISSING`、`ASSET_ENTRY_BAR_MISSING`、
`ASSET_EXIT_BAR_MISSING`、`ASSET_ENTRY_FACTOR_INVALID`、`ASSET_EXIT_FACTOR_INVALID`。同一候选只能进入
一个最先命中的 reason 或成功 labels，计数必须守恒；尾部截断是预期 INFO，其他原因进入 G1/G3
质量报告。

每个 horizon 的 labels/diagnostics 必须与 `label_manifest.json` 在同一 stage receipt 原子发布。
`build_label_artifact` 绑定 G1/snapshot/experiment、eligible/bars/calendar/benchmark 输入 digest 与输出
digest，并验证 `candidate_count = success_count + diagnostic_count`、`labels_row_count=success_count`、
diagnostics row-count/sample-count 区分和唯一 label/diagnostic key hash；`verify_label_artifact` 从文件重算，
拒绝自报 hash、未知字段、duplicate JSON key、NaN 和宽松数字转换。该 manifest 的生产者属于 G3A，
不由 G8 编排器临时补造。
