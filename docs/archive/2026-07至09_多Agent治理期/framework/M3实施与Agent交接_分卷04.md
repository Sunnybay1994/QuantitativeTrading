
reason 优先级按上段列举顺序固定：tail → benchmark entry → benchmark exit → asset entry bar → asset
exit bar → entry factor → exit factor。`benchmark_bars` 必须通过实际代码 SSOT 的
`BenchmarkBar1dSchema`，且只含显式 `benchmark` 参数对应切片；现行配置验证只接受 `510300.SH`。
`ForwardReturnLabelSchema` 对三列收益要求 finite，benchmark 使用独立 benchmark pattern，绝不放宽可交易
证券 `SYMBOL_PATTERN`。当前 Schema/label builder 已有初次实现和测试；readiness 虽已移除个股必需列，
但消费边界必须执行 exact `BenchmarkBar1dSchema`，required-column subset 不得代替 strict Schema。extra
column、dtype 或 Schema 约束失败统一形成 `BENCHMARK_INVALID` 且不泄露底层异常。Schema 验真必须发生在
任何 `source/benchmark/date` filter、comparison、duplicate 或 coverage 表达式之前；因 Schema 开启
coercion，下游只允许消费 `validate` 返回的规范 DataFrame，不得继续操作原 frame。extra 表若要继续收集
独立覆盖 issue，先投影 required columns，再以同一 Schema 验真该投影；现有绿测不能作为完整 G1/G3 证据。
当前 G1-P1 已按此通过主验。生产 Schema 的唯一键 check 会把重复 benchmark key 归入
`BENCHMARK_INVALID`；专用 `BENCHMARK_DUPLICATE_KEYS` 的诊断恢复记录为 P2，随 B4 统一质量错误分类处理，
不得为恢复专用码把 duplicate Polars 操作移回 Schema 之前。

### 4.4 `folds.py`

G4–G6 的现行执行颗粒度、verified artifact、失败语义和外部闭环以
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md) 为准；
旧 H0–H5 合并任务只保留设计历史。fold 不再向下游暴露裸 `FoldPlan` 或 caller 自报 hash。

```python
@dataclass(frozen=True)
class PlannedFold:
    name: str
    train_dates: tuple[dt.date, ...]
    train_validation_embargo_dates: tuple[dt.date, ...]
    validation_dates: tuple[dt.date, ...]
    validation_test_embargo_dates: tuple[dt.date, ...]
    test_dates: tuple[dt.date, ...]
    train_label_available_by: dt.date
    validation_label_available_by: dt.date
    planned_fold_sha256: str

@dataclass(frozen=True)
class FoldPlanBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    train_sessions: int
    validation_sessions: int
    test_sessions: int
    step_sessions: int
    embargo_sessions: int
    max_horizon_sessions: int

@dataclass(frozen=True)
class FoldPlanManifestV1:
    schema_version: Literal["m3-fold-plan-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    session_calendar_sha256: str
    signal_dates_sha256: str
    scientific_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    max_horizon_sessions: int
    folds: tuple[PlannedFold, ...]

@dataclass(frozen=True)
class FoldPlanUpstreamPaths:
    snapshot_request_path: Path
    snapshot_receipt_path: Path
    provider_dump_tool_path: Path
    provider_receipt_path: Path
    experiment_receipt_path: Path

@dataclass(frozen=True)
class VerifiedFoldPlanArtifact:
    root: Path
    manifest: FoldPlanManifestV1
    manifest_sha256: str
    folds_receipt_sha256: str

def build_temporal_fold_plan(
    *, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, output_root: Path,
) -> FoldPlanManifestV1: ...

def verify_fold_plan_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedFoldPlanArtifact: ...

def select_supervised_labels(
    *, label: VerifiedLabelArtifact, folds: VerifiedFoldPlanArtifact,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    label_spec: LabelBuildSpec, fold_spec: FoldPlanBuildSpec,
    label_receipt_path: Path, folds_receipt_path: Path,
    upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path], fold_name: str,
    segment: Literal["train", "validation"],
) -> pl.DataFrame: ...
```

development example 复用完全相同的 manifest、schema、hash 与 receipt 形态，但使用精确平行 API 和
`VerifiedDevelopmentExampleFoldPlanArtifact(release_kind="development_example", formal_gate_eligible=False,
example_id=...)`。formal API 在写入前拒绝 development nominal；development 产物只允许位于显式
development/example 路径，不能进入正式 G1/G4 发布根、journal 或候选映射。当前最小 fixture 含 38 个
history sessions：前 28 个 signal sessions 加 10 个 label-tail sessions；development walk-forward 为
`2/2/2/2/10`，恰好两折。该链通过只表示开发契约通过，不关闭正式 G4 Gate。

M3 使用固定长度 rolling window，不使用 expanding train。`open_dates` 必须唯一、严格递增且全部是冻结
SH session；函数先取 `[signal_start,signal_end]`，provider 的 60-session warmup 和 10-session label tail
永不进入 train/validation/test。`embargo_sessions >= max_horizon_sessions`，且为形成无重叠样本外汇总，M3 要求
`step_sessions >= test_sessions`。每折布局固定为
`train -> embargo_1 -> validation -> embargo_2 -> test`，尾部不足完整 test 不生成。

标签可知截止点不是 segment end：train 标签允许使用到 `embargo_1` 最后一个 session 已知的数据，
validation 标签允许使用到 `embargo_2` 最后一个 session 已知的数据。embargo 的作用正是等待前段标签
成熟；若仍用 train/validation end 截止，会无理由丢掉各段末尾约 h 个信号。test 只用于模型冻结后的
推理与事后评估，其标签可知截止由 `test.end + horizon tail` 单独验真，不进入训练接口。

`folds.json` 是 strict `FoldPlanManifestV1`，必须发布完整日期列表、两个 label cutoff、完整 warmup→tail
`session_calendar_sha256`、信号域 `signal_dates_sha256`、experiment 已绑定的 `scientific_config_sha256` 和
每折日期 hash；只存
首尾日期不足以证明 session 数、embargo 或日历未漂移。fold name 由规范日期计划稳定生成。跨折 train
可以重叠，test 日期不得重叠；任何 test 指标不得用于参数、iteration 或 feature schema 选择。

FoldPlan 必须非空。fold receipt 固定为 `EXPERIMENT` scope，formal/development stage 分别为
`folds`/`development-folds`；直接输入精确为 snapshot request、snapshot manifest/receipt/calendar、
experiment manifest/receipt，输出只允许 `folds.json`。标签选择器每次消费都用完整上游 nominal、配置、
spec、receipt 和 artifact roots 重新验真 label 与 FoldPlan，拒绝漏项、增项、decoy 或仅信已构造 dataclass。
`FoldPlanUpstreamPaths` 是上游 request/receipt/tool 的唯一物理路径来源；不得从 snapshot 的最具体 alias
反推公共 artifacts base。Fold verifier 必须 fresh 验真 snapshot、provider、experiment 各自的完整 receipt
闭包，并按 digest 解析出的精确物理路径处理重叠 root alias；禁止 basename 搜索或同 bytes decoy 替换。
spec 的 signal window 必须等于 snapshot request/manifest 从 G1 继承的窗口，walk-forward 数值必须等于
`LoadedM3Config` scientific selector；C0 不存在独立 `walk_forward_config_sha256`，不得新增伪 selector。

### 4.5 `features.py`、`alignment.py` 与 `qlib_adapter.py`

row key、允许 NaN 的 Float64 feature matrix、finite label series 和 schema digest 精确采用
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md) §2.1 的
`m3-f64-matrix-digest-v1`；禁止 pickle、本机默认 endian、Parquet bytes 或 NaN JSON 作为逻辑摘要。

```python
@dataclass(frozen=True)
class FeatureSchemaManifestV1:
    feature_version: str
    qlib_version: str
    input_names: tuple[str, ...]
    expressions: tuple[str, ...]
    input_schema_sha256: str
    selected_names: tuple[str, ...]
    selected_dtypes: tuple[str, ...]
    dropped_all_nan_train: tuple[str, ...]
    selected_schema_sha256: str

@dataclass(frozen=True)
class FeatureSegmentManifestV1:
    name: Literal["train", "validation", "test"]
    path: str
    bytes_sha256: str
    content_sha256: str
    eligible_keys_sha256: str
    feature_row_keys_sha256: str
    feature_matrix_sha256: str
    scorable_keys_sha256: str
    n_eligible: int
    n_feature_rows: int
    n_scorable: int

@dataclass(frozen=True)
class FeatureManifestV1:
    schema_version: Literal["m3-feature-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    fold: str
    planned_fold_sha256: str
    scientific_config_sha256: str
    eligible_keys_sha256: str
    worker_protocol_version: str
    schema: FeatureSchemaManifestV1
    segments: tuple[FeatureSegmentManifestV1, ...]
    coverage_path: str
    coverage_sha256: str
    coverage_row_count: int

@dataclass(frozen=True)
class FeatureBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    fold: str
    planned_fold_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    feature_version: str
    expected_qlib_version: Literal["0.9.7"]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

@dataclass(frozen=True)
class VerifiedFeatureArtifact:
    root: Path
    manifest: FeatureManifestV1
    manifest_sha256: str
    feature_receipt_sha256: str

@dataclass(frozen=True)
class AlignmentBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: Literal[5, 10]
    feature_manifest_sha256: str
    label_manifest_sha256: str

@dataclass(frozen=True)
class AlignmentSegmentManifestV1:
    name: Literal["train", "validation"]
    path: str
    bytes_sha256: str
    row_keys_sha256: str
    matrix_sha256: str
    labels_sha256: str
    n_feature_scorable: int
    n_label_identity: int
    n_label_joined: int
    n_cutoff_dropped: int
    n_final: int

@dataclass(frozen=True)
class AlignmentManifestV1:
    schema_version: Literal["m3-alignment-artifact-v1"]
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: int
    feature_manifest_sha256: str
    label_manifest_sha256: str
    selected_feature_schema_sha256: str
    segments: tuple[AlignmentSegmentManifestV1, ...]
    diagnostics_path: str
    diagnostics_sha256: str
    diagnostics_row_count: int

@dataclass(frozen=True)
class VerifiedAlignmentArtifact:
    root: Path
    manifest: AlignmentManifestV1
    manifest_sha256: str
    alignment_receipt_sha256: str

@dataclass(frozen=True)
class SupervisedSegment:
    name: Literal["train", "validation"]
    features: pd.DataFrame
    labels: pd.Series
    metadata: pl.DataFrame

@dataclass(frozen=True)
class InferenceSegment:
    name: Literal["test"]
    features: pd.DataFrame
    metadata: pl.DataFrame

def build_feature_artifact(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    experiment: VerifiedExperimentIdentity, folds: VerifiedFoldPlanArtifact,
    config: LoadedM3Config, spec: FeatureBuildSpec, python_executable: Path,
    output_root: Path, timeout_seconds: float,
) -> FeatureManifestV1: ...

def verify_feature_artifact(...) -> VerifiedFeatureArtifact: ...

def load_supervised_segment(
    *, alignment: VerifiedAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment: ...

def build_alignment_artifact(
    *, feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: AlignmentBuildSpec, output_root: Path,
) -> AlignmentManifestV1: ...

def build_inference_segment(
    *, feature: VerifiedFeatureArtifact, folds: VerifiedFoldPlanArtifact,
    fold_name: str,
) -> InferenceSegment: ...
```

H1 启动前必须由编排器确认 provider-validation PASS；该 receipt 只作前置门禁，不传给 H1 builder/handler、不列入
feature 内容 receipt。H1 只读取已验真的 snapshot `session_calendar.parquet`、provider receipt/tree 与 fold，
不能接受调用者临时传入另一份 calendar。`FeatureBuildSpec` 在启动 worker 前重算并核对 provider/fold/config
identities，worker 回包必须 echo 相同 identity。feature 配置只由 scientific selector 验真；C0 不存在独立
`feature_config_sha256`。inference 只能按 `fold_name` 从 verified folds bundle 取 test 日期，不接受裸 fold。
这里的“已验真”是本次调用沿显式 upstream paths/spec fresh 重验 G4A 及其上游，不接受仅凭可构造 dataclass
跳过磁盘验真。稳定 worker request/response 只保存 provider URI 身份摘要；绝对 URI 仅经 fresh subprocess
临时环境传递，不进入 manifest、receipt、stdout 或其他稳定产物。

`features.py` 是安全 parent API；`qlib_adapter.py` 是唯一 Qlib worker。handler 构造与 DatasetH prepare 必须在
同一个 fresh Python 子进程中连续执行，Qlib 对象不能跨进程返回；父进程只通过规范 JSON/Parquet 接收普通
数据并从原始文件重算 manifest。不得让 Qlib recorder 成为主实验记录器。Alpha158 features **按 fold 生成一次并在 h=5/h=10
间共享**；标签对齐才是 work/horizon 级。禁止为两个 horizon 重算和复制同一份大特征矩阵。

首版 processor 与标签策略冻结如下：

1. 生产 feature handler 固定为官方 Qlib v0.9.7 `Alpha158` 默认 158 个 expression，显式传
   `infer_processors=[]`、`learn_processors=[]`、`label=([], [])`；不允许 loader 计算 `LABEL0`，更不能
   把它丢弃后假装没有前瞻依赖。Qlib v0.9.7 官方源码确认 Alpha158 默认 learn processor 含
   `DropnaLabel/CSZScoreNorm`，因此这三个显式空值是防泄漏契约，不是可选优化：
   <https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/data/handler.py>。
2. handler `start_time` 必须使用 provider manifest 的 history start，而不是 train start；否则首个 train
   session 没有 60-session rolling lookback。`end_time=fold.test.end`，instruments 使用 provider manifest
   发布的历史并集 instrument set，禁止 Alpha158 默认 `csi500` 或今天的 csi300。Dataset segments 使用
   PlannedFold 的三个精确边界。
3. `DatasetH.prepare(..., col_set="feature", data_key=DataHandlerLP.DK_I)` 只导出 feature。Qlib 官方文档
   明确 `prepare` 的 segment/col_set/data_key 职责：<https://qlib.readthedocs.io/en/stable/component/data.html>。
   返回列必须与运行时 `get_feature_config()` 的 158 个唯一 name/expression 一一对应；接受全为 feature
   group 的两级列或唯一 flat names，其他列结构、重复 leaf name、数量不为 158 均失败。manifest 记录
   names、expressions、实际 Qlib 版本及 hash，不能只写 `Alpha158` 字符串。
4. feature index 必须按命名 level 从 Qlib `(datetime,instrument)` 显式转换为项目
   `(as_of,symbol)`；证券代码转换只调用 snapshot 的同一对映射函数，不复制字符串逻辑。
   时间戳必须无时区且为午夜；不能用 `.date()` 静默截断日内或时区值。转换后重复键、segment 外日期、
   非 SH session 都失败。
5. verified G1 release 的 `eligible_keys` 是唯一正向 PIT 资格域，键必须唯一且只含 fold 三段日期。先按 segment 与资格键过滤
   Qlib 历史行，再以 **train eligible rows** 拟合 feature schema：inf 转 NaN，只删除 train 全 NaN 列，
   validation/test 复用同一有序列和 float64 dtype。选定列后整行全 NaN 是 unscorable，三段均剔除并按日
   输出 `n_eligible/n_feature_rows/n_scorable/reason`；不做均值填充、不删普通含 NaN 行、不按 test 改列。
   “剔除”是指从 G4C/inference 的 scorable 消费域剔除；G4B segment parquet 仍保留该 feature row，保证
   `feature_row_keys_sha256` 与 `scorable_keys_sha256` 均可由稳定产物独立重建，不依赖 worker summary。
6. `build_alignment_artifact` 只允许 train/validation。它消费对应 `VerifiedLabelArtifact` 并使用 PlannedFold
   对应 `available_by`，一对一连接 scorable feature keys；X/y 使用同一
   唯一 `(as_of,symbol)` pandas MultiIndex、稳定排序且行数/顺序完全一致。缺标签进入 alignment diagnostics，
   不得填充。
7. test 使用 `build_inference_segment`，**绝不 join 未来标签**。所有 PIT eligible 且 scorable test keys
   都必须进入预测；标签只在模型已冻结、predictions 已发布后由 evaluate 事后连接。否则会产生幸存者/
   可标签样本选择偏差，并让 G7 缺少本应交易的信号。

这条路径不包含需要 `fit` 的 feature processor，因此不存在“在 validation/test 上 fit”的入口。
未来若增加任何有状态 processor，必须新增可见的 processor manifest，证明其 fit 日期严格等于
train segment；不能仅依赖 DatasetH 的 segment，因为 segment 只控制 prepare 取数，不自动限制
handler processor 的拟合区间。

provider history domain 与 model sample domain 必须分离：前者为历史成分并集的连续行情，以保证新
调入证券首个生效日也有完整 60-session Alpha158 回看；后者只能是 PIT membership 当日有效的
`eligible_keys`。禁止通过删 provider 历史来表达样本资格，也禁止保留历史后省略资格 join。

G3 的 Qlib 对账只是语义审计：在日期 `t` 计算
`Ref($close, -h) / Ref($open, -1) - 1` 的证券调整后收益，并减去独立 `510300.SH` ETF HFQ 总回报代理
区间收益，与独立标签的
`raw_return/benchmark_return/relative_return` 三列逐行比较。对账表达式不得反向成为训练标签 SSOT。

该审计必须在 fresh Python 子进程中完成并关闭 Qlib disk/expression cache；父进程和核心 import 路径不得
加载 Qlib。每个 horizon 独立运行，先按 `benchmark/label_version/horizon` 严格取得唯一标签切片。Qlib
表达式结果只保留已发布 label keys；缺一行、重复、多一身份或非 finite 都失败。不得只抽样 reconciliation。

启动 worker 前先验真 provider、label、snapshot calendar、G1 benchmark 文件及全部 receipt/hash；任一
“A 的 DataFrame + B 的 digest”组合都在 import Qlib 前失败。worker 请求和回包必须 echo identities。
主 join key 固定为 `(as_of,symbol,benchmark,horizon_sessions,label_version)`；return start/end 由权威 session
独立推导后逐值比较，不能放进 join key 掩盖日期错位。provider expression/direct 先以 `(as_of,symbol)`
计算，再严格一对一连接主 key。

由于固定 `dump_bin.py` 把 provider fields 写成 float32，G3 不再使用不可实现的单一 `1e-10` 门槛，而是
分开核对三层：

1. 对每个 label key，另外通过 Qlib 直接读取 return start 的 `$open` 和 return end 的 `$close`，手算
   `provider_raw_return`；与 Qlib `Ref` expression 的误差使用 `validation.labels.qlib_expression_atol`。
2. benchmark audit 不调用 `compute_forward_relative_labels`，而以 SH session 和原始 `510300.SH`
   open/close 独立向量化查表；与 label `benchmark_return` 使用 `benchmark_return_atol`。
3. `provider_raw_return` 与权威 Float64 label `raw_return`、以及
   `provider_raw_return-audit_benchmark_return` 与 label `relative_return` 使用 `label_return_atol`，明确容纳
   provider float32 量化但不掩盖日期错位。

details 至少包含唯一键、return start/end、Qlib expression/direct raw、label raw、audit/label benchmark、
audit/label relative、四种 abs error 和稳定 status；summary 分别记录
`expression_direct/benchmark/raw_label/relative_label` 四个 max/p99 序列，不能把后两者合成一个 max；记录 experiment/provider-validation/label
manifest/reconciliation identities、行键 hash、期望/匹配行数、每种 max/p99 error、配置容差和全量 PASS。
p99 固定使用 nearest-rank：升序 n 个误差取 `ceil(0.99*n)-1`（n>0），不得使用依赖版本可能改变插值默认值
的通用 quantile。
JSON 禁止 NaN/Infinity。reconciliation key 绑定 experiment、horizon、provider validation receipt、label
manifest、label-reconciliation config、code/dependency；配置容差改变不重建 provider/experiment，但必须形成新
reconciliation 路径和 receipt。生产 Alpha158 handler 仍固定 `label=([],[])`，训练永不读取该审计输出。

### 4.6 `model.py`

```python
@dataclass(frozen=True)
class LightgbmTrainingSpec:
    model_version: str
    booster_params: tuple[tuple[str, str | int | float | bool], ...]
    num_boost_round: int
    early_stopping_rounds: int
    early_stopping_min_delta: float

```
