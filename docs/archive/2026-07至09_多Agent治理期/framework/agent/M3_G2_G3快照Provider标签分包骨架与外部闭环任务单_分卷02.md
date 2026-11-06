```python

def inspect_provider_structure(
    *, qlib_dir: Path, snapshot: VerifiedSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1: ...

def read_provider_manifest(path: Path) -> ProviderManifestV1: ...

def verify_provider_artifact(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderArtifact: ...
```

唯一真实 argv：

```text
<python> <verified dump_bin.py> dump_all
--data_path <snapshot>/staging --qlib_dir <output-root>/provider --freq day
--file_suffix .parquet --date_field_name date --symbol_field_name symbol
--include_fields open,high,low,close,vwap,volume,factor --max_workers 1
```

参数数组、`shell=False`；禁止 backup/fix/update/limit/额外 fields。稳定 manifest 只保存对应占位符 logical argv。
output root 必须空；dump exit 0 后仍必须执行全量结构检查。subprocess timeout/return code/stdout 只用于稳定
错误分类，不持久化原始文本。

### 4.4 全量静态检查

- `calendars/day.txt` 全量等于 snapshot session calendar；
- `instruments/all.txt` 证券集合、codec、每证券 min/max 等于 staging；
- 每证券恰有七个 `<field>.day.bin`，无额外 symbol/field/file/symlink；
- bin 是 `<f4`；首值是该证券首日相对全局 calendar 的整数 offset；字节数 `4*(1+span)`；offset 必须能
  无损解释为整数，NaN/负数/分数失败；
- staging emitted 值转 `np.float32` 后逐 bit/逐位置相等；区间 gap 全为 NaN；
- tree files bytes hash/size、calendar/instrument 摘要和 tree digest 写入 manifest；manifest 不列自己、receipt
  或 validation。

静态 inspector 不 import Qlib。provider root 固定只含 `provider/{calendars,instruments,features}` 和
`provider_manifest.json`。

上述格式不是项目猜测：Qlib v0.9.7 的固定
[`scripts/dump_bin.py`](https://github.com/microsoft/qlib/blob/v0.9.7/scripts/dump_bin.py) 明确把 calendar offset
作为首个 little-endian float32、在证券 min/max 间按全局 calendar reindex，并在 dump 前 drop duplicate date。
实现仍以本项目 pinned bytes/SHA 为执行证据；网页只用于设计核对，不能替代本地 tool 验真。

### 4.5 G2B 必测反例

精确 argv/shell/timeout、runtime package 漂移、tool size/hash/version/command、provider key 重算、dump 0 但少
factor、多 field/symbol、错 calendar/offset/span/endian、finite 值漂移、gap 非 NaN、重复 staging 被 dump
静默 drop、output 非空、树中 symlink/FIFO/hardlink/unknown、manifest JSON 严格性、parent import isolation 和
异常脱敏。fake subprocess 可以证明合同，但报告必须明确未证明真实 Qlib。

## 5. G2C：fresh-process Qlib public API validation

### 5.1 文件范围

```text
src/quant/research/m3/provider.py
src/quant/research/m3/qlib_adapter.py
src/quant/research/m3/__init__.py             # 只导出 provider parent API，禁止 import qlib_adapter
tests/unit/test_m3_provider_validation.py
tests/unit/test_m3_qlib_worker_protocol.py
docs/framework/agent/M3_G2CProvider公共API验真交付报告.md
docs/M3_G2CProvider公共API验真独立初验报告.md
```

### 5.2 probe、spec 与 verified result

```python
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
```

原 `candidate_sha256` 改名为 `candidate_keys_sha256`，明确它是 probe 前完整候选键身份，不是 G1 candidate。

### 5.3 接口

```python
def plan_provider_probe(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
) -> ProviderProbePlan: ...

def validate_provider_public_api(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec,
    python_executable: Path, output_root: Path, timeout_seconds: float,
) -> ProviderValidationResult: ...

def read_provider_validation_summary(path: Path) -> ProviderValidationSummaryV1: ...

def verify_provider_validation_artifact(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderValidationArtifact: ...
```

`spec` 是重算 `provider_validation_key` 与确定性 probe 的可信输入；若 verifier 不接收它，summary key、receipt
scope 和 plan hash 可被整套自洽替换，因此旧无 `spec` 签名废止。

### 5.4 确定性 sample

- 候选证券是 staging 中至少 20 emitted rows 的全部证券；如果 SH/SZ 任一无候选或总数不足 3，失败；
- 分别按 `sha256(canonical_json(["provider-symbol-v1",snapshot_id,provider_key,symbol]))` 选最低 SH、最低
  SZ，再从剩余全部候选取最低；hash tie 以 symbol 排序；
- 每证券必含首尾 emitted date，再从内部日期按
  `sha256(canonical_json(["provider-date-v1",provider_key,symbol,date_iso]))` 取 18；不足失败；
- 每证券从首尾区间内非 emitted session 按
  `sha256(canonical_json(["provider-gap-date-v1",provider_key,symbol,date_iso]))` 排序取最多 5；没有 gap 合法；
- emitted 精确 60 keys，gap 0–15。键最终按 `(symbol,date)` 排序，任何输入行序不影响。

### 5.5 worker protocol 与证据

parent 以参数数组启动：

```text
<python> -m quant.research.m3.qlib_adapter validate-provider
  --request <ephemeral-request.json>
  --response <ephemeral-response.json>
  --details <ephemeral-details.parquet>
```

worker strict request echo provider/snapshot/validation key、Qlib version、URI hash、60/gap keys、七 fields；随后
在 fresh process `qlib.init(provider_uri=唯一目录)`，通过公开 API 全量读取 calendar/instruments，并读取 probe
fields。worker 不写 summary/PASS，只写逐 cell actual 和全量 API 摘要；parent 重算 expected、missing/extra/
duplicate、420+gap×7 counts、status 和 summary。

details 每个计划 cell 一行；worker 原始返回中额外 cell 不伪装成计划行，而进入 `extra_cell_count` 和
`read_audit_sha256`：

```text
sample_kind, symbol, date, field, api_row_present,
expected, actual, expected_f32_bits, actual_f32_bits, status
```

`sample_kind=EMITTED/GAP`；field 顺序七项固定。emitted expected 是 staging cast `<f4` 后提升为 float64 的精确
值，必须以 `UInt32` bit pattern 等价；signed zero 不得被普通浮点相等吞掉。gap 在 Qlib public API 中可以是
“该 row 缺失”或“row 存在且值为 NaN”，两者都规范为 nullable `actual=null`，并用 `api_row_present/status`
区分 `GAP_ABSENT/GAP_NAN`；任何 finite gap 值都是 `GAP_FILLED` 并失败。emitted row 缺失、NaN/Inf 或 bit
不等价分别计数。summary 分开记录 emitted/gap key 和 comparison 数，不把 gap计入固定 420。
calendar/instruments 经 Qlib API 全量 hash 对账。

`probe_plan_sha256` 是完整 strict plan（除自报 hash 外无省略）的 canonical digest；`details_sha256` 是固定
schema、排序和 nullable/bit-field 规则下的逻辑内容 digest。summary `passed` 当且仅当所有八个错误/漂移计数
均为 0、`emitted_key_count=60`、`emitted_comparison_count=420`、gap counts 与 plan 精确相等，且所有 identity/
digest 重算一致。产物目录精确只有 `provider_validation.parquet`、`provider_validation.json`；output root 必须
预先为空，parent 从 details 与 worker raw audit 重算 summary 后才写 JSON。

parent 在 subprocess 前后断言自身 `sys.modules` 无 `qlib` 前缀；持久 `parent_import_audit_sha256` 对规范空
违规集合 hash。`provider_uri_sha256` 对规范 URI identity（provider key + 相对 `provider`）计算，不 hash 本机
绝对路径。read audit 绑定 worker request keys/fields、API calendar/instrument digest 和 response row-key digest。

### 5.6 G2C 必测反例

跨运行同 sample、hash tie、缺市场/不足 20、A 后 B cache 污染、worker identity echo 漂移、MultiIndex level
逆序/改名、timezone/non-midnight、missing/extra/duplicate cell、字段顺序、float32 signed-zero/NaN/Inf、gap row
缺失与显式 NaN 均合法、gap 被 forward-fill、calendar/instrument API 漂移、worker timeout/非零/坏 JSON/Parquet、父进程预加载 qlib、summary
整套自洽替换在原 worker rows 重算时失败。

## 6. G3A：每 horizon strict label artifact

### 6.1 文件范围

```text
src/quant/research/m3/contracts.py
src/quant/research/m3/development_example.py
src/quant/research/m3/labels.py
src/quant/research/m3/__init__.py
tests/unit/test_m3_labels.py
tests/unit/test_m3_label_artifact.py
docs/framework/agent/M3_G3A标签Artifact交付报告.md
docs/M3_G3A标签Artifact独立初验报告.md
```

不得 import Qlib 或实现 reconciliation worker。

### 6.2 manifest 与 verified bundle

```python
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
    diagnostic_count: int  # diagnostics.sample_count 之和，不是 diagnostics 行数

@dataclass(frozen=True)
class VerifiedLabelArtifact:
    root: Path
    labels: pl.DataFrame
    diagnostics: pl.DataFrame
    manifest: LabelArtifactManifest
    manifest_sha256: str
    label_receipt_sha256: str
```

### 6.3 接口与语义

```python
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
```

`ExperimentIdentityManifestV1` 的生产和 receipt 发布仍属于 G8；G3A 实现 strict reader/consumer verifier，
不能为了提前实现 G3A 而临时生成 experiment key。manifest 必须调用唯一 `compute_experiment_key` 重算，
且 verified bundle 必须由 experiment stage receipt 证明。G8 后续只编排/发布这一合同，不得另定义字段。
consumer verifier 必须接收可信 `ExperimentIdentitySpec`/`LabelBuildSpec`，防止 manifest、key 与重签 receipt
整体替换后仍凭内部自洽通过；scientific identity 必须同时与 `LoadedM3Config` 精确一致。

G3A 不得复制一套弱化的 receipt verifier。需要 receipt 原始字节或 hash 时，必须复用
`run_state.verify_stage_receipt_with_bytes`：它从同一打开文件身份完成 parse/hash，在读取任一 digest
前验真完整 root registry，并保留 E3 对嵌套 roots、symlink/reparse、重复物理 alias 和自引用的
全部失败语义。嵌套 root 下从路径推导 alias 时固定选择最具体的子 root；显式 receipt digest
仍以其 `root_alias` 为准。

用户已批准正式 G1 的 B 路径，现行配置和正式候选基准均为 `510300.SH` ETF HFQ 总回报代理；本节旧版
`H00300.CSI` Literal 已同步替换。开发示例与正式入口均从已验真配置和 G1 benchmark artifact 取得该值，
不得在标签实现中另写第二套基准。

生产 stage 每次只构建一个 horizon；内部可调用既有 `compute_forward_relative_labels(horizons=[h])`。入口从
verified G1 release 读取 bars/benchmark/eligible keys，从 verified snapshot 读取唯一 session calendar；所有
物理/逻辑 digest 在计算前重验。

标签语义保持：as-of `t`，start=`t+1` SH session open，end=`t+h` SH session close。不得用自然日。注意当
`h=1` 时 start=end 是合法的同日 open-to-close；因此公共 Schema 应要求 `return_end_date >= return_start_date`，
只有 `h>1` 才严格晚于。M3 v1 production 仍只允许 h=5/10。

每个 eligible key 恰好成功或进入一个 reason；优先级固定 tail→benchmark entry→benchmark exit→asset entry→
asset exit→entry factor→exit factor。candidate_count 精确等于该 horizon eligible row count，且
`candidate=success+diagnostic_count`。diagnostics 是聚合表，manifest 同时绑定行数、聚合 key hash 和
sample_count 总和。

目录精确为 `labels.parquet,diagnostics.parquet,label_manifest.json`。strict reader/verify 规则同前：未知字段、
duplicate JSON key、NaN/字符串数字、路径逃逸、frame/hash/receipt 混配全部失败。

### 6.4 G3A 必测反例

除权事件手算、Friday→Monday→h session、h=1 同日边界、尾部、停牌缺 entry/exit、factor 两端、benchmark
extra/dtype、eligible 非成员污染、reason 优先级、守恒、diagnostics row count 与 sample sum 混淆、bars digest
遗漏攻击、A frame+B manifest/receipt、输出非空/symlink、异常脱敏和零 Qlib import。

## 7. G3B：每 horizon 全量 fresh-worker reconciliation

### 7.1 文件范围

```text
src/quant/research/m3/contracts.py
src/quant/research/m3/development_example.py
src/quant/research/m3/labels.py
src/quant/research/m3/qlib_adapter.py
src/quant/research/m3/__init__.py             # 只导出 labels parent API，禁止 import qlib_adapter
tests/unit/test_m3_label_reconciliation.py
tests/unit/test_m3_qlib_worker_protocol.py
docs/M3_G3B标签全量对账交付报告.md
docs/M3_G3B标签全量对账独立初验报告.md
```

### 7.2 spec、summary 与接口

```python
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
class LabelReconciliationReceiptPaths:
    snapshot_receipt_path: Path
    provider_receipt_path: Path
    provider_validation_receipt_path: Path
    experiment_receipt_path: Path
    label_receipt_path: Path

def reconcile_labels_with_qlib(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    labels: VerifiedLabelArtifact, config: LoadedM3Config,
    spec: LabelReconciliationSpec,
    receipt_paths: LabelReconciliationReceiptPaths,
    artifact_roots: Mapping[str, Path],
    python_executable: Path, output_root: Path, timeout_seconds: float,
) -> LabelReconciliationResult: ...

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
```

formal/development 入口均显式接收上述五条 receipt path；禁止扫描目录、按 hash 猜路径或依赖 horizon
文件名约定。worker 启动前必须用共享 `verify_stage_receipt_with_bytes` 验证每条 receipt 的 bytes、stage、
scope、scope_key、nominal SHA 及完整 root registry。reconciliation receipt 的输入闭包精确为：experiment
receipt+manifest；G1 manifest+benchmark；snapshot receipt+manifest+session calendar；provider
receipt+manifest+严格完整 provider tree；provider-validation receipt+summary+details；label
receipt+manifest+labels+diagnostics。输出严格只有 `reconciliation.parquet,reconciliation.json`。
