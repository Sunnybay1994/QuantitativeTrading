
| Dotted keys | 严格类型与当前版本约束 | Derived selector |
|---|---|---|
| `meta.config_version/purpose/enabled` | string/string/bool；version 必须精确为 `1.0.0`，purpose 非空；`enabled=false` 是合法可加载配置但运行 Gate 必须失败 | version 作为 G/S/P/C/PV/LR/A hash namespace；其余无 |
| `data.universe/benchmark/source/market/frequency/provider_format/snapshot_hash` | 非空 string；当前分别固定为示例值；source 仅 `tushare` | universe/benchmark/source/market/frequency/snapshot_hash → S+C；market/frequency/provider_format → P；provider_format → C |
| `data.start_date/end_date` | `datetime.date`，start≤end；拒绝 datetime/time；两端是信号域边界并须由 G1 日历证明为 SH session，不自动对齐；修正后示例为 `2016-01-04/2026-06-26` | S+C |
| `data.minimum_train_sessions/minimum_cross_section_symbols` | int 且非 bool，分别 `>0`、`>=2` | S+C |
| `data.required_fields/provider_fields` | tuple[str]；精确等于示例的有序唯一列表，不静默排序 | required → S+C；provider → P+C |
| `runtime.qlib.version/supported_python` | string；固定 `0.9.7` 与 `>=3.8,<3.13` | version → C，并单独进入最终 provider key；supported policy 无 derived config hash |
| `runtime.qlib.dump_script_url/sha256/bytes` | HTTPS URL、裸 64 hex、正 int；精确匹配固定供应链 spec | 无 derived config hash；实际 tool SHA 单独进入 provider key |
| `features.*` | handler/policy/version strings 固定示例；feature count 正 int且=158；coverage 是 `[0,1]` float | C |
| `labels.*` | horizons 精确 `(5,10)`；offset 正 int且=1；entry/exit/version strings 与 relative bool 固定示例 | C |
| `g1_backfill` 业务核心键 | code/version/source strings 固定示例；expected count=`300`、membership warmup=`1`、feature warmup=`60`；label tail 正 int且>=最大 horizon | 全部 → G；feature warmup + label tail 另 → S |
| `g1_backfill.request_rate_per_minute/max_attempts/retry_base_seconds` | 前两者正 int 且非 bool，retry 是 finite 非负 float | 仅 full；它们是运行政策，不改变 request/release 身份 |
| `g1_backfill.endpoint_row_limits.*` | 七个精确键与冻结值：daily/adj_factor=`6000`，index_daily/index_weight/suspend_d/dividend=`5000`，stk_limit=`5800`；int 且非 bool | G |
| `g1_backfill.reconciliation.*` 与 `corporate_action_reconciliation.*` | source 固定；sample symbols/dates=`30/20`；atol/rtol/rate 是 finite 非负 float，mismatch rate≤1；factor ratio rtol 另须≤0.01 | G |
| `walk_forward.*` | 五个 session 数是正 int；selection/test policy 固定示例；另满足 embargo/step/完整 fold 不变量 | C |
| `model.lightgbm.*` | string/bool/int/float 类型精确；固定 CPU/deterministic/force-column；learning rate>0，fractions∈(0,1]，bagging freq≥0，leaves≥2，depth=-1或正数，rounds/early-stop/threads正且early-stop<rounds，min-delta≥0，全部 seed 为非负 int 且非 bool | C |
| `portfolio.*` | strategy/version/rebalance 固定；top_k 正 int；cash_buffer∈[0,1)，max_weight∈(0,1]，并满足可行性 | C |
| `backtest.a_share.*` | initial cash/tick 为正 float；6 个 policy string 与 2 个 bool 分别固定示例；friction tuple 精确 `(0.5,1.0,2.0)` | C |
| `evaluation.minimum_ic_symbols` | int 且非 bool，>=2 | C |
| `validation.provider.*` | sample symbols/dates/gaps 精确 `3/20/5`；policy 固定示例 | PV |
| `validation.labels.*` | version 固定；三个 atol 是 finite 非负 float并满足容差层级 | LR |
| `costs` header 与 periods | version/HTTPS source/scaled-components 固定；period 是非空 tuple[mapping]，日期连续不重叠；commission_rate/min、stamp_tax_sell、transfer_fee、slippage 五项均须 exact finite nonnegative float；最后 effective_to 必须缺省 | C |
| `tracking.experiment_name/tracking_uri` | name 非空；URI 仅允许规范相对 SQLite 或无 userinfo/query/fragment 的 HTTP(S) | T |
| `tracking.artifact_root/log_*` | root 是项目内相对 POSIX 路径，无 `..`；三个 flags 当前必须为 true | 无；request/artifact digest 决定 tracking key |
| `acceptance.*` | 两个 reproducibility atol、五个 coverage 阈值为 finite 非负 float，coverage≤1；required metrics 是精确有序唯一 tuple | A |

数值类型不宽松转换：bool 不能充当 int，int 不能充当 float，字符串数字也非法。所有 float 拒绝 NaN/
Infinity；`-0.0` 规范化为 `0.0`。数组原顺序参与 hash，因此对语义为集合的字段直接要求示例中的唯一固定
顺序，不能在 loader 中偷偷排序。

当前 `1.0.0` 示例含 151 个 assignment；将 `costs.a_share_periods[<index>]` 归一为
`costs.a_share_periods[]` 后有 138 种 dotted-key shape。`config.py` 的唯一 `_FIELD_SPECS` 必须与这 138 种
shape 精确相等；每个 spec 明确 required/optional、严格 TOML 类型、literal/值域与 G/S/P/C/PV/LR/A/T
归属。唯一 optional shape 是 `costs.a_share_periods[].effective_to`，且只允许末期缺省。测试从真实示例
枚举闭包，漏 spec、多 spec 或 wildcard 吞键均失败；不能另写第二份测试 allowlist。

变化传播验证分为两类：当前版本允许合法变化的字段，必须用公开 loader/canonicalizer 对两份完整
有效文档运行时比较 hash；被 `1.0.0` 冻结为唯一 literal 的字段，必须同时证明变体被公开 API
拒绝、且该 field spec 的 selector 归属正确。禁止为了构造无效文档的 hash 测试而放宽 literal，
或把跳过验证的 trusted helper 暴露给生产调用方。如需让冻结字段成为可配置量，必须先升级
`config_version` 并同步所有消费者。

#### 4.0.2 规范 hash 与 URI

除 tracking target 外，每个 derived hash（包括 full 与 G1）输入固定为：

```text
{"hash_version":"m3-config-hash-v1","selector":"<name>",
 "config_version":"1.0.0","payload":<selected read-only subtree>}
```

再按 UTF-8、键排序、紧凑 JSON、ISO date 求裸 SHA-256。selector name 必须进入输入，避免两个不同身份
恰因 payload 相同而混用。散落字段按原始 section 层级重建最小 nested mapping，不展平成 dotted-key map；
section/array 顺序语义沿用已验证 document。实现固定使用 `json.dumps(..., ensure_ascii=False,
sort_keys=True, separators=(",", ":"), allow_nan=False)` 的 UTF-8 字节；date 先转 ISO 字符串，`-0.0` 先转
`0.0`。`full` 使用同一 envelope 和完整规范化 document。tracking target 不绑定 config version，
输入只含 `hash_version,selector="tracking-target",canonical_tracking_uri,experiment_name`。
`canonical_tracking_target_key` 自身必须执行与 loader 相同的 URI/name 校验和规范化；不能假定 direct caller
已清洗，也不能接受原 URI 与自报 canonical URI 两份可冲突输入。

相对 SQLite URI 以 workspace root 为运行期解析基准，但 hash 中保留规范逻辑 URI，不写绝对路径；HTTP(S)
URI 将 scheme/host 小写、去默认端口、规范 path，拒绝 userinfo、query、fragment、凭据和 `.`/`..` 路径段。
错误不得回显原 URI。loader 将 document 中的 `tracking_uri` 替换为同一规范逻辑 URI，并通过
`canonical_tracking_uri` 明确暴露；调用方不得恢复使用原始拼写。切换 URI 只改变 T 和 full，不改变科学
identity。

#### 4.0.3 错误与不可变对象

错误 code 只允许：`CONFIG_IO_ERROR,TOML_PARSE_ERROR,UNKNOWN_KEY,MISSING_KEY,TYPE_ERROR,EMPTY_STRING,NON_FINITE,
VALUE_ERROR,CROSS_FIELD_ERROR,SECRET_VALUE,UNSAFE_PATH,UNSAFE_URI`。dotted path 对 array table 使用
`costs.a_share_periods[0].commission_rate` 形式；message 只描述期望，不回显原值、URI、token 或绝对路径。
配置文件不存在、不是普通文件、不可读或解码失败统一为不含物理路径的 `CONFIG_IO_ERROR`；TOML parser
异常不得直接拼接进 message，避免回显原始值。除文件/TOML 无法解析外，应一次收集全部可独立判断的
问题并稳定排序。

成功 document 递归转换为 `MappingProxyType`、tuple 和不可变标量；任何深度的 mapping/array 不可修改。
hash selectors 只读取该对象，不能重新 parse TOML。`LoadedM3Config` 还应提供只读 `section(name)` helper，
未知 section 失败，禁止各调用方用 `.get(default)` 恢复隐式默认。

#### 4.0.4 凭据、路径与 URI 的机械规则

安全检查先于 unknown-key 丢弃，并对 percent-decoding 后的文本再检查；unknown secret key 可同时产生
`UNKNOWN_KEY` 与 `SECRET_VALUE`。敏感键 segment 规范为小写并把 `-` 换成 `_` 后，至少拒绝
`token,api_key,apikey,secret,password,passwd,authorization,cookie,credential,private_key`。字符串值拒绝
控制字符，以及大小写不敏感的 `Bearer <value>`、`token=...`、`api[_-]?key=...`、`password=...`、
`secret=...` 或 `sk-...` 形式；不能用“任意长 hex 都是 secret”的规则误杀冻结的 dump SHA。错误只记录
dotted path 与期望类别，不记录命中的片段。

非 URL 字符串若形如 POSIX 绝对路径、Windows drive/UNC 路径或包含反斜杠路径分隔，返回
`UNSAFE_PATH`。`artifact_root` 只接受非空、相对、规范 POSIX path segment；不得含空 segment、`.`、`..`、
percent-encoded separator/dot segment。相对 SQLite URI 只接受 `sqlite:///<relative-posix-path>`，第四个
slash 即绝对路径并拒绝；HTTP(S) URI 必须有 host，scheme/host 小写、默认端口移除、空 path 规范为 `/`，
拒绝 userinfo、query、fragment、反斜杠、控制字符以及 decoded `.`/`..` segment。当前首版 URI path
一律不接受 percent encoding；HTTP path 除根 `/` 外还拒绝重复 `/` 与尾 `/`，不做可能改变服务端语义的
自动折叠。`%2f/%5c/%2e` 等绕过必须失败。host case 与 `:80/:443` 默认端口是唯一要求归一为同一
HTTP(S) target key 的别名。所有路径的真实 root containment
和 no-symlink 检查仍由 StageRunner/发布器在解析 workspace root 后执行，C0 不凭逻辑字符串声称物理安全。

### 4.1 `readiness.py`

```python
@dataclass(frozen=True)
class ReadinessIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str

def audit_m3_readiness(
    *,
    bars: pl.DataFrame,
    instruments: pl.DataFrame,
    membership: pl.DataFrame,
    calendars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    config: Mapping[str, Any],
) -> list[ReadinessIssue]: ...
```

必须检查：字段契约、PIT 成员覆盖、基准覆盖、交易日覆盖、复权因子覆盖、最少训练长度、最小截面
证券数、horizon/embargo、Qlib 可导入性和 Python 版本。存在任何 `ERROR` 时 CLI 退出非零且不写
provider/model。

就绪口径冻结如下：

- 只检查 `data.start_date..data.end_date` 内的 SH 开市日，不得用配置区间外日历凑训练长度；
- “有效行情”是已选数据源中 OHLC、volume、adj_factor 完整且合法的唯一行；
- 先依 `data.source` 过滤 bars 和 benchmark bars，再执行重复键、finite、覆盖和截面检查；
  请求源不存在时返回 `DATA_SOURCE_MISSING`；
- 股票 bars 与 benchmark bars 是两种契约。基准精确使用 `BenchmarkBar1dSchema`，不得要求
  `symbol/volume/amount/adj_factor` 或调用股票 factor helper；M3 v1 benchmark 只允许
  `510300.SH`，重复键为 `(benchmark,trade_date,source)`；
- 每个开市日都对当日生效的 PIT 成员做稠密计数，有效证券数低于
  `minimum_cross_section_symbols` 的任意日期都产生 `CROSS_SECTION_TOO_SMALL`；不得以最大日
  截面代替逐日检查；
- “可训练 session”同时满足：截面达标、基准当日有效、日历开市；
  `minimum_train_sessions` 只对此计数；
- PIT 覆盖还必须拒绝“某一成员在其整个生效区间没有任何有效行情”；
- 缺少前置字段时先记录结构化 `ERROR`，然后跳过依赖该字段的检查；审计函数
  本身不得因输入契约错误而崩溃。

### 4.2 `snapshot.py`、`provider.py` 与 provider contracts

本节的现行实施颗粒度、verified bundle、fresh-worker 协议和五段外部闭环以
[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)
为准；旧任务书合并 P0–P4 的方式不再执行。G2A 只能消费 `VerifiedG1Release`，G2B/G2C 只能消费
`VerifiedSnapshotArtifact/VerifiedProviderArtifact`，不得回退裸 path/DataFrame 加自报 hash。
本节所有消费 `*_config_sha256` 的 plan/build/verify 函数同时接收同一严格 `LoadedM3Config`，并在任何 I/O
或 worker 前调用 C0 唯一 selector 重算对应 narrow hash；只检查 hex 或相信 spec/manifest 自报值不构成验真。
完整配置不写入产物，也不因此污染窄 identity。

```python
class SnapshotSessionCalendarSchema(pa.DataFrameModel):
    date: pl.Date

def prepare_qlib_staging(
    *, release: VerifiedG1Release,
    history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame: ...

def to_qlib_symbol(symbol: str) -> str: ...
def from_qlib_symbol(instrument: str) -> str: ...

def write_staging_by_symbol(
    *, frame: pl.DataFrame, output_dir: Path,
) -> tuple[Path, ...]: ...

def build_snapshot_session_calendar(
    *, release: VerifiedG1Release,
    history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame: ...

@dataclass(frozen=True)
class SnapshotBuildSpec:
    snapshot_request_key: str
    config_version: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]

@dataclass(frozen=True)
class SnapshotRequestRecordV1:
    schema_version: Literal["m3-snapshot-request-v1"]
    snapshot_request_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date

@dataclass(frozen=True)
class SnapshotArtifactEntryV1:
    path: str
    sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    symbol: str | None
    min_date: dt.date
    max_date: dt.date

@dataclass(frozen=True)
class SnapshotManifestV1:
    schema_version: Literal["m3-snapshot-manifest-v1"]
    snapshot_id: str
    config_version: str
    snapshot_config_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    source: Literal["tushare"]
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date
    row_count: int
    symbol_count: int
    min_date: dt.date
    max_date: dt.date
    session_calendar_sha256: str
    session_count: int
    session_start: dt.date
    session_end: dt.date
    staging_format: Literal["parquet"]
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]
    adjustment_spec_sha256: str
    files: tuple[SnapshotArtifactEntryV1, ...]

@dataclass(frozen=True)
class SnapshotBuildResult:
    root: Path
    manifest: SnapshotManifestV1
    manifest_sha256: str

@dataclass(frozen=True)
class VerifiedSnapshotArtifact:
    root: Path
    request: SnapshotRequestRecordV1
    request_sha256: str
    manifest: SnapshotManifestV1
    manifest_sha256: str
    snapshot_receipt_sha256: str
    session_calendar_path: Path
    staging_paths: tuple[Path, ...]

def build_snapshot_artifact(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec,
    output_root: Path,
) -> SnapshotBuildResult: ...

def build_snapshot_request_record(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec,
    result: SnapshotBuildResult,
) -> SnapshotRequestRecordV1: ...

def read_snapshot_manifest(path: Path) -> SnapshotManifestV1: ...
def read_snapshot_request_record(path: Path) -> SnapshotRequestRecordV1: ...

def verify_snapshot_artifact(
    *, snapshot_root: Path, snapshot_request_path: Path,
    snapshot_receipt_path: Path, release: VerifiedG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedSnapshotArtifact: ...

@dataclass(frozen=True)
class QlibDumpToolSpec:
    url: str
    sha256: str
    size_bytes: int
    qlib_version: Literal["0.9.7"]
    command: Literal["dump_all"]

def build_qlib_dump_tool_spec(config: LoadedM3Config) -> QlibDumpToolSpec: ...

def ensure_qlib_dump_tool(
    *, spec: QlibDumpToolSpec, target_path: Path,
) -> Path: ...

@dataclass(frozen=True)
class ProviderRuntimeFingerprint:
    python_version: str
    packages: tuple[tuple[str, str], ...]
    sha256: str

@dataclass(frozen=True)
class ProviderBuildSpec:
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_config_sha256: str
    dump_tool: QlibDumpToolSpec
    qlib_version: Literal["0.9.7"]
    code_version: str
    runtime_fingerprint: ProviderRuntimeFingerprint
    fields: tuple[str, ...]
    frequency: Literal["day"]
    dump_contract_version: Literal["m3-qlib-dump-all-v1"]

@dataclass(frozen=True)
class ProviderManifestV1:
    schema_version: Literal["m3-provider-manifest-v1"]
    provider_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_config_sha256: str
    qlib_version: str
    dump_tool_sha256: str
    dump_tool_bytes: int
    dump_contract_version: str
    provider_runtime_fingerprint_sha256: str
    code_version: str
    frequency: Literal["day"]
    fields: tuple[str, ...]
    storage_dtype: Literal["<f4"]
    calendar_sha256: str
    calendar_count: int
    calendar_start: dt.date
    calendar_end: dt.date
    instrument_count: int
    instrument_ranges_sha256: str
    output_tree_sha256: str
    logical_argv: tuple[str, ...]
    files: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class ProviderBuildResult:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str

@dataclass(frozen=True)
class VerifiedProviderArtifact:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str
    provider_receipt_sha256: str

def read_provider_manifest(path: Path) -> ProviderManifestV1: ...

def materialize_qlib_provider(
    *, snapshot: VerifiedSnapshotArtifact, qlib_dump_script: Path,
    python_executable: Path, config: LoadedM3Config,
    spec: ProviderBuildSpec,
    output_root: Path, timeout_seconds: float,
) -> ProviderBuildResult: ...

@dataclass(frozen=True)
class ProviderValidationSpec:
    provider_validation_key: str
    provider_validation_config_sha256: str
    code_version: str
    qlib_version: Literal["0.9.7"]
    sampling_policy_version: Literal["provider_market_stratified_hash_first_last_v1"]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

@dataclass(frozen=True)
class ProviderProbePlan:
    schema_version: Literal["m3-provider-probe-v1"]
    provider_validation_key: str
    provider_key: str
    snapshot_id: str
    sampling_policy_version: Literal["provider_market_stratified_hash_first_last_v1"]
    candidate_keys_sha256: str
    selected_rows: tuple[tuple[str, dt.date], ...]
    selected_gap_rows: tuple[tuple[str, dt.date], ...]
    emitted_keys_sha256: str
    gap_keys_sha256: str

@dataclass(frozen=True)
class ProviderValidationSummaryV1:
    schema_version: Literal["m3-provider-validation-v1"]
    provider_validation_key: str
    provider_key: str
    provider_receipt_sha256: str
    provider_manifest_sha256: str
    snapshot_id: str
    provider_validation_config_sha256: str
    provider_runtime_fingerprint_sha256: str
    qlib_version: str
    sampling_policy_version: str
    worker_protocol_version: str
    probe_plan_sha256: str
    candidate_keys_sha256: str
    emitted_keys_sha256: str
    gap_keys_sha256: str
    emitted_key_count: int
    gap_key_count: int
    emitted_comparison_count: int
    gap_comparison_count: int
    details_sha256: str
    details_row_count: int
    api_calendar_sha256: str
    api_instrument_ranges_sha256: str
    missing_emitted_cell_count: int
    extra_cell_count: int
    duplicate_cell_count: int
    non_finite_emitted_cell_count: int
    emitted_mismatch_cell_count: int
    gap_finite_cell_count: int
    calendar_mismatch_count: int
    instrument_mismatch_count: int
    provider_uri_sha256: str
    parent_import_audit_sha256: str
    read_audit_sha256: str
    passed: bool

@dataclass(frozen=True)
class ProviderValidationResult:
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1

@dataclass(frozen=True)
class VerifiedProviderValidationArtifact:
    root: Path
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1
    summary_sha256: str
    validation_receipt_sha256: str

def read_provider_validation_summary(path: Path) -> ProviderValidationSummaryV1: ...

def inspect_provider_structure(
    *, qlib_dir: Path, snapshot: VerifiedSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1: ...

def plan_provider_probe(
    *, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
) -> ProviderProbePlan: ...

def validate_provider_public_api(
    *, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec,
    python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> ProviderValidationResult: ...

```
