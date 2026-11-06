```python

@dataclass(frozen=True)
class ModelManifestV1:
    schema_version: Literal["m3-lightgbm-model-v1"]
    experiment_key: str
    work_key: str
    snapshot_id: str
    provider_receipt_sha256: str
    fold: str
    horizon_sessions: int
    model: Literal["lightgbm"]
    model_version: str
    alignment_manifest_sha256: str
    feature_manifest_sha256: str
    label_manifest_sha256: str
    input_feature_schema_sha256: str
    selected_feature_names: tuple[str, ...]
    selected_feature_schema_sha256: str
    params_sha256: str
    train_row_keys_sha256: str
    validation_row_keys_sha256: str
    train_matrix_sha256: str
    validation_matrix_sha256: str
    train_labels_sha256: str
    validation_labels_sha256: str
    lightgbm_version: str
    best_iteration: int
    best_validation_l2: float
    model_sha256: str
    validation_curve_sha256: str

@dataclass(frozen=True)
class VerifiedModelArtifact:
    root: Path
    manifest: ModelManifestV1
    manifest_sha256: str
    model_receipt_sha256: str

def build_model_artifact(
    *, alignment: VerifiedAlignmentArtifact,
    feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    output_root: Path,
) -> ModelManifestV1: ...

def verify_model_artifact(...) -> VerifiedModelArtifact: ...

def predict_fitted_model(
    *, model: VerifiedModelArtifact, inference: InferenceSegment,
) -> tuple[float, ...]: ...
```

`build_lightgbm_training_spec(config)` 是 training spec 的唯一构造入口。booster parameter key 必须唯一并按
key 排序，值只允许上述规范标量；拒绝 bool/int 混淆、NaN/Infinity、list/dict 和参数别名重复。
`model_version` 从 scientific selector 进入 spec，builder 不接受第二份 free-form 字符串。verifier 同样接收
`LoadedM3Config` 并重验 experiment scientific identity。

预测返回 `PredictionScoreSchema`。不得在测试集重新 fit、early stop 或选择 iteration。

M3 直接调用 LightGBM native `train`，不使用 Qlib `LGBModel`。训练协议冻结为：

1. train/validation 列名、顺序、float64 dtype 和唯一 MultiIndex 完全一致；X 允许普通 NaN 但不允许 inf，
   y 必须 finite，X/y/metadata 的 keys 与顺序逐行一致。train/validation 都非空；test 对象不进入 fit 签名。
2. objective=`regression`、metric=`l2`；只把 validation Dataset 放入 `valid_sets`，使用官方
   `early_stopping(stopping_rounds, first_metric_only=True, min_delta=...)` 和 `record_evaluation`。官方 API
   说明 validation metric 决定 `best_iteration`：<https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.early_stopping.html>。
   不用 test 选 iteration，不做超参数搜索，也不在选出 best iteration 后把 train+validation 合并重训。
   Rank IC 是样本外研究指标，不冒充本版 booster 的 early-stopping metric。
3. `num_boost_round/early_stopping_*` 是 training control，不混进 booster params。booster params 必须显式
   含 objective/metric、`device_type="cpu"`、`deterministic=true`、`force_col_wise=true`、`seed/data_random_seed/
   feature_fraction_seed/bagging_seed` 和 `num_threads`；缺项或 GPU/CUDA 失败。不得由适配器偷偷补值。
4. LightGBM `Dataset` 不设 categorical features、不设 sample weight，保持稳定行序。记录每轮 validation
   l2；`best_iteration >= 1` 且 best score finite，否则失败。模型只保存到 best iteration。
5. `stage_dir` 必须是 StageRunner 分配的空临时目录。函数只写 `model.txt`、`model.metadata.json`、
   `validation_curve.parquet`，不自行覆盖 final work 目录；跨文件原子发布由唯一 StageRunner 完成。metadata
   记录 experiment/work、snapshot/provider、feature/label input hashes、行键/matrix/label hashes、有序 feature
   schema、规范参数、实际 LightGBM 版本、seed、best iteration/score 和 model hash。

`predict_fitted_model` 必须校验输入 feature 名称、顺序和 hash 与 `VerifiedModelArtifact` 完全一致；score 非 finite
立即失败，并只用已保存模型的 `best_iteration`。rank 统一由 `quant.research.m3.predictions` 的唯一
`normalize_prediction_scores` 生成，策略层改为 import 它，禁止模型/策略各写一套。排序分组和
PredictionScore Schema 唯一键都必须包含 `model`，不能只用 `model_version`。

predictions parquet 同目录发布 manifest，至少含 experiment/work、model metadata/model file hash、feature
bundle/test segment/eligibility/signal-date hash、snapshot/fold/horizon/model identity、`n_eligible/n_scorable/
n_predicted` 和 prediction hash。`n_predicted` 必须等于 test `n_scorable`；空预测或遗漏任一 scorable key
失败，不能等 evaluate 或 targets 才发现。

feature projection 的唯一执行点是 `build_feature_artifact`：先验真 158 维 input schema，再应用
train-only 全 NaN 列投影，输出 selected schema。model/predict 只接受该 bundle 的 selected columns，
不得由编排器临时 `.drop()`。`verify_model_artifact` 用于 train 与 predictions 分属不同进程的恢复路径，必须
复算 model/metadata/curve hash，并核对 work、snapshot/fold/horizon、feature projection 和实际 LightGBM
版本。`model.metadata.json` 不记录自身 hash，避免身份循环；其 bytes hash 只进入 verified bundle 与 receipt。

### 4.7 `evaluate.py`

```python
@dataclass(frozen=True)
class PredictionBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    model: Literal["lightgbm"]
    model_version: str

@dataclass(frozen=True)
class PredictionManifestV1:
    schema_version: Literal["m3-prediction-artifact-v1"]
    experiment_key: str
    work_key: str
    model_manifest_sha256: str
    model_sha256: str
    feature_manifest_sha256: str
    selected_feature_schema_sha256: str
    eligibility_sha256: str
    signal_dates_sha256: str
    snapshot_id: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_eligible: int
    n_scorable: int
    n_predicted: int
    prediction_keys_sha256: str
    predictions_sha256: str

@dataclass(frozen=True)
class VerifiedPredictionArtifact:
    root: Path
    predictions: pl.DataFrame
    manifest: PredictionManifestV1
    manifest_sha256: str
    prediction_receipt_sha256: str

@dataclass(frozen=True)
class EvaluationSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    minimum_ic_symbols: int

IcStatus = Literal[
    "NO_ELIGIBLE", "NO_LABELS", "NO_PREDICTIONS", "INSUFFICIENT_SYMBOLS",
    "BOTH_ZERO_VARIANCE", "SCORE_ZERO_VARIANCE", "LABEL_ZERO_VARIANCE",
    "COMPUTABLE",
]

@dataclass(frozen=True)
class EvaluationMetricsV1:
    schema_version: Literal["m3-evaluation-metrics-v1"]
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

@dataclass(frozen=True)
class EvaluationManifestV1:
    schema_version: Literal["m3-evaluation-artifact-v1"]
    experiment_key: str
    work_key: str
    prediction_manifest_sha256: str
    label_manifest_sha256: str
    feature_manifest_sha256: str
    fold_plan_manifest_sha256: str
    eligible_keys_sha256: str
    evaluation_dates_sha256: str
    scientific_config_sha256: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    daily_sha256: str
    metrics_sha256: str

@dataclass(frozen=True)
class VerifiedEvaluationArtifact:
    root: Path
    daily: pl.DataFrame
    metrics: EvaluationMetricsV1
    manifest: EvaluationManifestV1
    manifest_sha256: str
    evaluation_receipt_sha256: str

@dataclass(frozen=True)
class ResearchSummaryMetricsV1:
    schema_version: Literal["m3-research-summary-metrics-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    folds: tuple[str, ...]
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

@dataclass(frozen=True)
class ResearchSummaryManifestV1:
    schema_version: Literal["m3-research-summary-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    scientific_config_sha256: str
    folds: tuple[str, ...]
    evaluation_manifest_sha256s: tuple[str, ...]
    evaluation_receipt_sha256s: tuple[str, ...]
    test_dates_sha256: str
    daily_sha256: str
    fold_metrics_sha256: str
    metrics_sha256: str

@dataclass(frozen=True)
class VerifiedResearchSummaryArtifact:
    root: Path
    daily: pl.DataFrame
    fold_metrics: pl.DataFrame
    metrics: ResearchSummaryMetricsV1
    manifest: ResearchSummaryManifestV1
    manifest_sha256: str
    summary_receipt_sha256: str

def build_prediction_artifact(
    *, model: VerifiedModelArtifact, feature: VerifiedFeatureArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: PredictionBuildSpec,
    output_root: Path,
) -> PredictionManifestV1: ...

def verify_prediction_artifact(...) -> VerifiedPredictionArtifact: ...

def build_evaluation_artifact(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: EvaluationSpec,
    output_root: Path,
) -> EvaluationManifestV1: ...

def verify_evaluation_artifact(...) -> VerifiedEvaluationArtifact: ...

def summarize_prediction_metrics(...) -> EvaluationMetricsV1: ...

def build_research_summary_artifact(
    *, evaluations: Sequence[VerifiedEvaluationArtifact],
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    horizon_sessions: int, output_root: Path,
) -> ResearchSummaryManifestV1: ...
```

`evaluation_dates` 是当前 PlannedFold 的完整 test_dates，是日期域 SSOT。四层 keys 均按
`(as_of,symbol)` 唯一并满足 `scorable ⊆ eligible`、`predicted == scorable`、`labeled ⊆ eligible`；任何
区间外行、身份混片、集合关系破坏或 prediction 漏行先失败。labels 只按当前 horizon/benchmark/version
过滤；区间外 labels 不影响结果，且不能用 labels 决定哪些 test rows 先生成 prediction。
`VerifiedPredictionArtifact` 的 work/model/model file/feature schema/prediction hash 必须与 parquet 逐项一致；
这些高维研究 lineage 不塞进全局 PredictionScore Schema，但没有已验真 manifest 的 parquet 也不得评估。

每次调用只接受一个唯一的
`(model,model_version,dataset_snapshot_id,fold,horizon_sessions)` 预测切片；若包含多个切片必须
拒绝，不得自动混合。预测唯一键是该切片加 `(as_of,symbol)`，标签唯一键是
`(as_of,symbol,horizon_sessions)`；任一重复键必须在 join 前拒绝。连接键必须包含
`horizon_sessions`。模型名 `model` 也属于 prediction slice 与唯一键，不能让两个不同模型仅因
`model_version` 相同而被合并。

每日输出完整 coverage ladder：`n_eligible,n_scorable,n_predicted,n_labeled,n_evaluated`，并分别汇总：

- `feature_coverage = sum(n_scorable) / sum(n_eligible)`；
- `prediction_coverage = sum(n_predicted) / sum(n_scorable)`，验真后应为 1；
- `label_coverage = sum(n_labeled) / sum(n_eligible)`；
- `evaluation_coverage = sum(n_evaluated) / sum(n_labeled)`。

旧的 matched/expected-label 单一 `prediction_coverage` 会把特征缺失、预测遗漏和标签缺失混为一个数字，
在 G4–G6 实现时废止；F5 二次返工只先修日期域，不代表最终 G6 coverage 契约完成。

`daily_ic.parquet` 列精确为 `as_of,n_eligible,n_scorable,n_predicted,n_labeled,n_evaluated,feature_coverage,
prediction_coverage,label_coverage,evaluation_coverage,pearson_ic,rank_ic,ic_status`。Pearson/Spearman 都只在
evaluated rows 上计算；`ic_status` 按固定优先级选择首个适用项：`NO_ELIGIBLE`、`NO_LABELS`、
`NO_PREDICTIONS`、`INSUFFICIENT_SYMBOLS`、`BOTH_ZERO_VARIANCE`、`SCORE_ZERO_VARIANCE`、
`LABEL_ZERO_VARIANCE`、`COMPUTABLE`，绝不填 0。Spearman 使用 average
tie ranks。日均 IC 是可计算日等权均值；ICIR 是
日 IC mean / sample std (`ddof=1`)，不年化，不做 pooled cross-section。metrics 必须是严格
`EvaluationMetricsV1`，`status_counts` 按八状态完整固定排序且和为日期总数；manifest 绑定全部输入/output hash。
计数写 JSON integer；未定义的 IC/ICIR 写 `null`，规范 JSON 序列化必须 `allow_nan=false`，禁止把 NaN/
Infinity 写入 metrics 或 MLflow。
`minimum_ic_symbols` 必须与 `LoadedM3Config` scientific selector 相等；C0 不存在独立
`evaluation_config_sha256`。prediction 的 signal/eligibility hash 只能从 verified folds/feature 推导，不允许 spec
自报。所有 Parquet 使用 zstd level 3、statistics、row group 65536、Polars native writer 的冻结参数。

`build_research_summary_artifact` 只接受同 experiment/model/model version/horizon 且 test dates 不重叠的
verified evaluation；拼接
daily 后按同一公式重算 aggregate，不平均各 fold ICIR，不选择“最好 fold”。若 test 日期重叠立即失败。
该函数只聚合研究 IC；G7 的独立现金账户收益不得在这里顺序复合。

### 4.8 `ml_topk.py`

```python
class MlTopkStrategy(Strategy):
    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame: ...
```

输入只允许 `PredictionScoreSchema` 和当日资格表；输出 `TargetWeightSchema`。排序规则固定；策略
无状态、不读取账户。首版使用等权 Top-k，权重不超过 `1-cash_buffer` 和单证券 `max_weight`。
TopkDrop 不属于 M3 完成条件；未来实现时必须由调用者显式传入上期选择集合，不得藏在全局变量、
对象可变状态或磁盘中。若现有 `Strategy` 接口无法表达，应先提交接口变更方案。

无状态 Top-k 也必须在按 `as_of` 过滤后确认预测只有一个
`(model,model_version,dataset_snapshot_id,fold,horizon_sessions)` 切片；多切片输入必须拒绝。
资格表每个 symbol 只能有一个布尔值，冲突记录不得使用任意 `unique` 结果。

`TargetWeightSchema` 是 M2/M3/交易层共用契约，不增加研究框架字段。M3 target stage 必须发布 strict
`TargetManifestV1` 并经 `VerifiedTargetArtifact` 消费，固定记录模型、G1 release、snapshot、fold、horizon、prediction/eligibility/
signal dates/target domain/target 文件 hash、三层覆盖计数和策略身份。manifest 与 target parquet
及逐日覆盖表共同作为 targets stage receipt 的输出；任何字段变化必须改变下游 backtest run identity。禁止把这些
血缘压进 `strategy_version` 字符串，也禁止仅依赖上游目录名推断。

正式 G1 release 不是 StageRunner stage，不存在也不得补造 `receipt.json`。G7A 及其后续正式回测链对 G1 的
物理输入闭包固定使用 public `verify_g1_release` 已验真的 `manifest.json`、`quality.json` 与所需正式表；其中
`quality.json` 的 bytes 必须绑定 `VerifiedG1Release.quality_sha256`。development example 若真实发布了自己的
stage receipt，继续使用 development 专用 receipt，禁止把两条信任域互相代换。

每个 test signal date 的 target domain 是当日全部 PIT eligible symbols；`n_scorable` 是其中确实存在
Alpha158 feature row 的证券，`n_predicted` 必须等于 `n_scorable`。无预测、无 eligible、预测遗漏 scorable
证券或 scorable/eligible 低于配置阈值都使 targets stage 失败，不能发布空 batch。Top-k 只在 scorable
预测中选择，但最终 target parquet 必须扩展到完整 target domain，未选中和不可评分的 eligible symbol
显式为 0；已调出证券由模拟器与实际持仓取并集后补 0。空文件绝不表示清仓或保持仓位。

```python
def build_target_artifact(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: TargetBuildSpec, output_root: Path,
) -> TargetManifestV1: ...

def verify_target_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    feature: VerifiedFeatureArtifact, prediction: VerifiedPredictionArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
) -> VerifiedTargetArtifact: ...
```

该 builder 属于 `quant.research.m3.targets` 的纯适配层；策略仍只处理预测排序，适配层负责覆盖率门禁和完整
domain 扩展。不得要求策略读取持仓或把 research lineage 加进全局 TargetWeight Schema。

### 4.9 `tracking.py` 和 `run_m3.py`

```python
def register_remote_tracking_run(
    *, request: TrackingRequestV1, request_sha256: str,
    tracking_uri: str, experiment_name: str,
    artifact_roots: Mapping[str, Path], lock_root: Path,
    client: TrackingClientProtocol | None = None,
) -> TrackingMarkerV1: ...

def register_tracking_request(
    *, request: TrackingRequestV1, request_path: Path, marker_path: Path,
    tracking_uri: str, experiment_name: str,
    artifact_roots: Mapping[str, Path], client: TrackingClientProtocol | None = None,
) -> TrackingMarkerV1: ...

def compute_tracking_key(*, work_key: str, request_sha256: str) -> str: ...

@dataclass(frozen=True)
class ArtifactDigest:
    root_alias: str
    relative_path: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True, kw_only=True)
class StageReceipt:
    receipt_version: Literal["m3-stage-receipt-v1"] = "m3-stage-receipt-v1"
    stage: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    scope_key: str
    inputs: tuple[ArtifactDigest, ...]
    outputs: tuple[ArtifactDigest, ...]

def compute_experiment_key(
    *, snapshot_id: str, provider_receipt_sha256: str,
    scientific_config_hash: str, code_version: str,
    dependency_fingerprint_sha256: str,
) -> str: ...

def compute_snapshot_request_key(
    *, g1_release_id: str, g1_release_manifest_sha256: str,
    snapshot_config_sha256: str, code_version: str,
) -> str: ...

def compute_provider_key(
    *, snapshot_id: str, provider_config_hash: str,
    dump_tool_sha256: str, qlib_version: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_provider_validation_key(
    *, provider_key: str, provider_receipt_sha256: str,
    provider_validation_config_sha256: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_label_reconciliation_key(
    *, experiment_key: str, horizon: int,
    provider_validation_receipt_sha256: str,
    label_manifest_sha256: str, label_reconciliation_config_sha256: str,
    dependency_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_work_key(
    *, experiment_key: str, fold: str, horizon: int,
) -> str: ...

def verify_stage_receipt(
    *, receipt_path: Path, artifact_roots: Mapping[str, Path],
) -> StageReceipt | None: ...

def publish_stage_receipt(
    *, receipt_path: Path, stage: str,
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ],
    scope_key: str, artifact_roots: Mapping[str, Path],
    inputs: Sequence[tuple[str, Path]],
    outputs: Sequence[tuple[str, Path]],
) -> StageReceipt: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

所有 identity/key、配置 hash、manifest/receipt digest 的编码统一为**裸 64 位小写十六进制 SHA-256**；
不得返回或持久化 `sha256:<hex>`。这些值会直接组成 Windows 挂载盘目录，冒号非法。若报告需要可读算法名，
另写稳定字段 `hash_algorithm="sha256"`，不进入路径或 hash 值。identity join 仍是规范 JSON 数组 UTF-8
后 SHA-256，只迁移输出编码，不允许同时兼容两种格式。
所有组合 key 必须调用其唯一具名函数；禁止把字段直接串接后 hash。规范数组编码必须覆盖
`("ab","c")` 与 `("a","bc")` 不碰撞的反例。

CLI 支持 `readiness`、`snapshot`、`train`、`evaluate`、`backtest`、`tracking`、`run-all`、
`verify-reproducibility`、`acceptance-audit` 九个子命令；
每步可重跑，已存在相同 snapshot 时必须校验后复用，不得覆盖不同内容。

命令依赖闭包与停止点冻结如下；共同参数均含 `--config`：
