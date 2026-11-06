
受信只读 root alias 至少包含 `CONFIG`（版本化 M3 配置）、`G1_RELEASE`（已验真 clean release）和
`EXTERNAL_QLIB`（固定 `dump_bin.py`）；运行期另注入 `SNAPSHOT/PROVIDER/EXPERIMENT/WORK/REPRO/
ACCEPTANCE`。provider handler 不隐式联网，D8/显式供应链命令先下载，provider StageNode 再把脚本作为
digest 输入。稳定产物与最小 required-input 闭包如下；receipt 必须精确列出本行全部输入和输出：

| Scope/stage | Required inputs | Required outputs |
|---|---|---|
| snapshot/readiness | `CONFIG`；`G1_RELEASE:{manifest,bars,benchmark,membership,calendar,instruments}` | `readiness.json` |
| snapshot/snapshot | readiness receipt；`CONFIG` narrow hash；上述 G1 文件 | `manifest.json`, `session_calendar.parquet`, `staging/*.parquet` |
| provider/provider | `EXTERNAL_QLIB:dump_bin.py`；snapshot receipt、manifest、calendar、全部 staging | `provider/**`, `provider_manifest.json` |
| provider/provider_validation | provider receipt/manifest/全部 provider tree；snapshot manifest/calendar/全部 staging | `provider-validation/key=<provider_validation_key>/{provider_validation.parquet,provider_validation.json}` |
| experiment/experiment_identity | snapshot/provider receipts 与 manifests；scientific/dependency identities；provider-validation PASS 仅作编排前置、不列内容 input | `experiment_manifest.json` |
| experiment/labels[h] | experiment manifest；`G1_RELEASE:{manifest,bars,benchmark,eligible_keys}`；snapshot calendar | `labels/horizon=<h>/{labels.parquet,diagnostics.parquet,label_manifest.json}` |
| experiment/label_reconciliation[h] | experiment receipt/manifest；`G1_RELEASE:{manifest,benchmark}`；snapshot receipt/manifest/session calendar；provider receipt/manifest/严格完整 tree；provider-validation receipt/summary/details；label receipt/manifest/labels/diagnostics | `labels/horizon=<h>/reconciliation/key=<reconciliation_key>/{reconciliation.parquet,reconciliation.json}` |
| experiment/folds | verified experiment；verified snapshot calendar；walk-forward config identity | strict `folds.json` |
| experiment/features[fold] | verified provider/folds/G1 eligible keys；feature config identity；provider-validation PASS 仅作编排前置、不列内容 input | `features/fold=<fold>/{train,validation,test}.parquet`, `feature_manifest.json`, `coverage.parquet` |
| work/alignment | verified feature；对应 horizon verified label；verified fold | `alignment/{train,validation}.parquet`, `alignment_manifest.json`, `diagnostics.parquet` |
| work/train | verified alignment/feature/label/experiment；model config/dependency identities | `train/{model.txt,model.metadata.json,validation_curve.parquet}` |
| work/predictions | verified model；verified test feature/fold/eligibility | `predictions/{predictions.parquet,prediction_manifest.json}` |
| work/evaluation | verified prediction/label/feature/fold；G1 eligible keys | `evaluation/{daily_ic.parquet,metrics.json,evaluation_manifest.json}` |
| work/targets | verified prediction/feature/fold；G1 eligibility/domain；scientific config identity | `targets/{target_weights.parquet,target_daily.parquet,target_manifest.json}` |
| work/backtest_plan | verified target/fold/G1 calendar；window/cost/backtest identities | `backtest_plan/{scheduled_targets,schedule_diagnostics}.parquet`, `cost_schedule.json`, `manifest.json` |
| work/backtest | verified target/backtest plan；`G1_RELEASE` market facts/benchmark/manifest | `backtest/scenario={0p5x,1p0x,2p0x}/{nav,trades,positions,rejections,postings,diagnostics,entitlements}.parquet`、每场景 `metrics.json`/`manifest.json`、根 `backtest_metrics.json`/`backtest_manifest.json` |
| work/tracking | 本 work 全部需登记的已验真 artifacts；tracking target identity | `work/<work_key>/tracking/{tracking_request.json,tracking_marker.json}` |
| experiment/research_summary[h] | 该 horizon 全部 verified evaluations，test dates 不重叠 | `summary/horizon=<h>/{daily_ic,fold_metrics}.parquet`, `metrics.json`, `manifest.json` |
| repro/comparison | 已验真 provider/features/labels/alignment；work/config/code/dependency identities；禁止读取正常 work model | `repro/<comparison_key>/attempt={1,2}/{model.txt,model.metadata.json,predictions.parquet,prediction_manifest.json,daily_ic.parquet,metrics.json,read_audit.json}`、根 `reproducibility.json` |
| acceptance/quality | source/test trees、版本化配置、code/dependency identities | `acceptance/quality/<quality_key>/{quality_report.json,pytest.log,ruff.log,mypy.log,import_isolation.json}` |
| acceptance/final | 预期 DAG 的全部 receipts/manifests、tracking markers、repro comparisons、quality receipt 与 acceptance config identity | `acceptance/final/<acceptance_key>/acceptance_report.json` |

`labels[h]` 可以在 folds 间共享但不同 horizon 不得混文件；Alpha158 feature bundle 依赖 fold 但不依赖
horizon，因此每 fold 只生成一次；supervised alignment 才依赖 horizon/work。任何共享产物的失败只阻止
真实依赖 work。stage runner
只能接收 `StageSpec` 中声明的输入路径；测试使用 fake runner 记录 open/read 路径，发现未声明读取即失败。

同一缓存的成功复用不能证明 G5/G9 冷启动可复现。CLI 另提供 `verify-reproducibility`：由父编排器启动
两个顺序执行的全新 WSL Miniforge base Python 子进程，在独立
`repro/<comparison_key>/attempt=1|2/` 下复用已验真的 snapshot/provider/features，但强制重新训练、预测
和评估。两个子进程使用 attempt 专属临时/cache 目录和显式确定性环境，不能共享 Python 对象、Qlib/
LightGBM 进程内缓存，也不读取正常 work 的 model/predictions；比较行键、score 和 metrics 后发布 comparison receipt。
两个 attempt 任一失败、读到对方产物或容差超限都不通过。

所有新 JSON manifest、report 和 receipt 必须有稳定 `schema_version`（stage receipt 固定
`m3-stage-receipt-v1`），使用规范 JSON 且禁止 NaN/Infinity、时间戳、本机绝对路径和凭据。版本未知时
fail-closed，不能按“字段差不多”继续读取。

### 4.9.1 `quality_gate.py` 和 `acceptance.py`

G9 不是“再跑一次测试”的别名，而是验证 G0–G8 的全部证据确实形成同一条身份闭包。验收模块只编排
生产模块自己的 artifact validator 和 `verify_stage_receipt`，不得复制标签、IC、账户或费用公式。

```python
@dataclass(frozen=True)
class QualityCheckResultV1:
    name: Literal["pytest", "ruff", "mypy", "import_isolation"]
    logical_argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str

@dataclass(frozen=True)
class QualityReportV1:
    schema_version: Literal["m3-quality-report-v1"]
    quality_key: str
    command_policy_version: Literal["m3-quality-commands-v1"]
    code_version: str
    dependency_fingerprint_sha256: str
    checks: tuple[QualityCheckResultV1, ...]
    passed: Literal[True]

@dataclass(frozen=True)
class VerifiedQualityArtifact:
    report: QualityReportV1
    report_digest: ArtifactDigest
    receipt: StageReceipt
    receipt_sha256: str

GateName = Literal["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"]

@dataclass(frozen=True)
class EvidenceLocatorV1:
    gate: GateName
    node_id: str
    expected_stage: str
    expected_scope: Scope
    expected_scope_key: str
    root_alias: str
    receipt_relative_path: str

@dataclass(frozen=True)
class AcceptanceIssueV1:
    gate: GateName
    code: str
    subject: str
    evidence: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class GateResultV1:
    gate: GateName
    status: Literal["PASS", "FAIL"]
    issues: tuple[AcceptanceIssueV1, ...]
    evidence: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class VerifiedRuntimeIdentity:
    code_version: str
    provider_runtime_fingerprint_sha256: str
    dependency_fingerprint_sha256: str
    full_config_sha256: str
    readiness_receipt_sha256: str

@dataclass(frozen=True)
class VerifiedComparisonIdentityV1:
    work_key: str
    fold: str
    horizon: int
    comparison_key: str
    comparison_receipt_sha256: str
    feature_receipt_sha256: str
    label_receipt_sha256: str
    alignment_receipt_sha256: str
    python_executable_sha256: str

@dataclass(frozen=True)
class VerifiedAcceptanceSubject:
    release: VerifiedG1Release
    snapshot: VerifiedSnapshotArtifact
    provider: VerifiedProviderArtifact
    provider_validation: VerifiedProviderValidationArtifact
    experiment: VerifiedExperimentIdentity
    folds: VerifiedFoldPlanArtifact
    runtime: VerifiedRuntimeIdentity
    readiness: VerifiedReadinessEvidenceArtifact
    comparisons: tuple[VerifiedComparisonIdentityV1, ...]

@dataclass(frozen=True)
class AcceptanceEvidencePlanV1:
    schema_version: Literal["m3-acceptance-evidence-plan-v1"]
    snapshot_id: str
    provider_key: str
    experiment_key: str
    expected_work_keys: tuple[str, ...]
    expected_comparison_keys: tuple[str, ...]
    evidence: tuple[EvidenceLocatorV1, ...]

@dataclass(frozen=True)
class RemoteTrackingObservationV1:
    work_key: str
    tracking_target_key: str
    tracking_key: str
    run_id: str
    status: Literal["FINISHED"]
    request_sha256: str
    artifact_digest_sha256: str

@dataclass(frozen=True)
class AcceptanceDecisionV1:
    schema_version: Literal["m3-acceptance-report-v1"]
    acceptance_key: str
    experiment_key: str
    acceptance_config_sha256: str
    code_version: str
    dependency_fingerprint_sha256: str
    tracking_target_key: str
    tracking_observations_sha256: str
    gate_results: tuple[GateResultV1, ...]
    overall_status: Literal["PASS", "FAIL"]

def build_acceptance_evidence_plan(
    *, subject: VerifiedAcceptanceSubject, config: LoadedM3Config,
) -> AcceptanceEvidencePlanV1: ...

def audit_m3_acceptance(
    *, subject: VerifiedAcceptanceSubject, plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact, config: LoadedM3Config,
    artifact_roots: Mapping[str, Path], tracking_verifier: TrackingVerifier,
) -> AcceptanceDecisionV1: ...
```

G9A quality handler 只以 `shell=False` 顺序运行当前 WSL Python 的固定 argv：`python -m pytest -q`、
`python -m ruff check src tests`、`python -m mypy src`，并以新子进程执行核心 import/重依赖隔离审计。
不得执行配置提供的命令、调用网络或记录 Python
绝对路径；日志将 workspace/Python 前缀规范化为 `<WORKSPACE>`/`<PYTHON>` 后写入临时 acceptance 目录。
执行前后重算 code、dependency 与版本化配置 identity，任一漂移都失败。四项全为 0、实际 dependency
fingerprint 与 experiment 完全一致时才发布 quality receipt；失败只返回脱敏诊断，
不得发布成功 receipt。

G9B 前先由 `readiness-evidence` ACCEPTANCE stage 把 fresh `VerifiedG1Release`、当前完整 config/runtime/provider
fingerprint 与 `audit_m3_readiness` 的 canonical ERROR/WARNING 结果绑定为正式 report+receipt。失败 readiness
可以形成审计证据，但只有 ERROR 为 0 才可使后续 G0 PASS。stage 必须进入唯一 registry；不得让纯函数返回值或
caller 自报 SHA 冒充 readiness receipt。

`resolve_acceptance_subject` 从 fresh readiness、已验真的 release/snapshot/provider/provider-validation/
experiment/folds、当前配置及 code/dependency fingerprint 重算 provider key 和 experiment key，调用者提供的
snapshot ID 只用于定位，不能信任目录名或 manifest 自报 identity。每个 fold×horizon 的 comparison identity
必须由实际 G8E comparison tree、receipt、两次 read audit 和 exact formal feature/label/alignment/Python 输入
重验后签发；subject 不接受裸 comparison key。
`build_acceptance_evidence_plan` 再使用 G8 的 plan builder/StageSpec registry 枚举明确 receipt locator；
生产函数内部调用唯一 `get_m3_stage_registry()`，不得由 CLI/调用者注入另一份 Mapping。
禁止扫描目录猜 work。每个期望 fold×horizon 必须恰有一个 work、tracking marker
和独立进程 comparison receipt，每个 horizon 必须恰有一个 research summary。额外的非权威文件不自动
成为证据，缺失、重复、跨 experiment 混用或损坏 receipt 均失败。

`audit_m3_acceptance` 收集全部可判定问题而不是首错退出，并验证：G0 readiness/实际依赖；G1 release 与
snapshot；G2 provider 全量结构、60 emitted keys/420 comparisons 与另计 gap；G3 每 horizon label reconciliation；G4 folds；G5 每 work 冷启动 comparison；
G6 每 work evaluation、每 horizon summary 和 coverage 阈值；G7 完整 targets、三档 backtest manifest 与
required metrics；G8 receipt 闭包与 tracking marker；G9 当前 code/dependency 对应的四项质量检查。所有
manifest 的 snapshot/provider/experiment/work/fold/horizon/model/feature/label/target hashes 必须沿链一致。

coverage、可计算日期比例和复现容差只从 `config.acceptance` 读取并逐 work 检查，不能用 pooled 结果
掩盖坏 fold。required metric 使用限定来源名：`evaluation.test_rank_ic`、`evaluation.test_rank_icir`、
`backtest.1p0x.test_net_excess_return`、`backtest.1p0x.test_turnover`、
`backtest.1p0x.test_max_drawdown`。前两者只投影当前 work 的 `EvaluationMetricsV1.rank_ic_mean/rank_icir`，
后三者只投影当前 work `BacktestMetricsV1` 中 `scenario=1p0x` 的同名字段；禁止动态去前缀、用 summary
替代、跨 work pooled 或从 0.5×/2× 回退。负收益或负 IC 本身不是工程失败。threshold 改变形成新 acceptance key，
不改变 experiment。`acceptance_key` 规范 hash experiment key、acceptance config hash、tracking target key、
quality receipt hash、remote tracking observations hash 和所有有序 required receipt hash。只有十个 Gate 全 PASS 才原子发布 `acceptance_report.json` 与
ACCEPTANCE receipt；FAIL 报告只输出到 stdout，不写可被误认为晋级证据的 complete receipt。验收通过
不自动修改路线图，仍需主 Agent 终验后更新。

G8 tracking validator 在 G9 时必须连接当前 tracking target，确认每个 work 恰有一个相同
`quant_tracking_key` 的 `FINISHED` run，request/artifact hash 与本地 marker 完全一致；仅有 marker 文件
不能证明 G8 当前仍闭合。远端 query 的规范最小观察值进入 acceptance report 与 identity；网络/认证错误
是 G8 FAIL，不得 SKIP。artifact/manifest/receipt 只对 evidence plan 引用的限定文件做 secret/path scan，
不扫描工作区、`archive/legacy_pre_greenfield/`、`data/legacy/` 或计划外目录。

### 4.10 `index_membership.py` 和 `m3_backfill.py`

```python
class TushareConnector:
    def fetch_index_weight_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_daily_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_adj_factor_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_index_daily_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_suspend_raw(
        self, *, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_stk_limit_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_dividend_raw(
        self, *, symbol: str, fields: str
    ) -> pl.DataFrame: ...

@dataclass(frozen=True)
class TushareRequestSpec:
    schema_version: Literal["m3-g1-tushare-request-v1"]
    request_id: str
    endpoint: Literal[
        "index_weight", "daily", "adj_factor", "index_daily", "suspend_d",
        "stk_limit", "dividend",
    ]
    parameters: tuple[tuple[str, str], ...]

    @classmethod
    def create(
        cls, *, endpoint: str, parameters: Mapping[str, str]
    ) -> "TushareRequestSpec": ...

@dataclass(frozen=True)
class EndpointPolicy:
    row_limit: int
    empty_response: Literal["ALLOW", "REJECT"]

@dataclass(frozen=True)
class TushareRequestBatch:
    schema_version: Literal["m3-g1-tushare-request-batch-v1"]
    phase: Literal["INDEX_WEIGHT", "HISTORY"]
    requests: tuple[TushareRequestSpec, ...]
    batch_sha256: str

@dataclass(frozen=True)
class G1RequestPlan:
    schema_version: Literal["m3-g1-request-plan-v1"]
    index_weight_batch: TushareRequestBatch
    history_batch: TushareRequestBatch
    plan_sha256: str

@dataclass(frozen=True)
class TushareRequestIntentV1:
    schema_version: Literal["m3-g1-tushare-intent-v1"]
    request_id: str
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

@dataclass(frozen=True)
class TushareRawCandidateV1:
    schema_version: Literal["m3-g1-tushare-candidate-v1"]
    request_id: str
    endpoint: str
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class TushareRequestReceipt:
    schema_version: Literal["m3-g1-tushare-receipt-v1"]
    request_id: str
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class VerifiedRawResponse:
    spec: TushareRequestSpec
    receipt: TushareRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

class M3G1MappingError(ValueError):
    code: str

def map_g1_daily_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...
def map_g1_adjustment_factor_response(
    *, response: VerifiedRawResponse
) -> pl.DataFrame: ...
def map_g1_benchmark_response(
    *,
    fund_daily: VerifiedRawResponse,
    fund_adj_segments: Sequence[VerifiedRawResponse],
    fund_div: VerifiedRawResponse,
    factor_ratio_rtol: float,
) -> pl.DataFrame: ...
def map_g1_suspension_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...

@dataclass(frozen=True)
class ReferenceRequestSpec:
    schema_version: Literal["m3-g1-baostock-request-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class ReferenceRequestPlanV1:
    schema_version: Literal["m3-g1-baostock-request-plan-v1"]
    sample_plan_sha256: str
    requests: tuple[ReferenceRequestSpec, ...]
    request_plan_sha256: str

@dataclass(frozen=True)
class ReferenceRequestIntentV1:
    schema_version: Literal["m3-g1-baostock-intent-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

@dataclass(frozen=True)
class ReferenceRawCandidateV1:
    schema_version: Literal["m3-g1-baostock-candidate-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class ReferenceRequestReceipt:
    schema_version: Literal["m3-g1-baostock-receipt-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class VerifiedReferenceResponse:
    spec: ReferenceRequestSpec
    receipt: ReferenceRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

@dataclass(frozen=True)
class AdjustmentApplicationResult:
    bars: pl.DataFrame
    factor_match_evidence: pl.DataFrame

@dataclass(frozen=True)
class HistoryWindow:
    start: dt.date
    end: dt.date

@dataclass(frozen=True)
class G1QualityIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class ObservedMembershipResult:
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str

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

@dataclass(frozen=True)
class G1BuildSpec:
    config_version: str
    g1_config_sha256: str
    mapper_version: str
    schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    build_code_version: str
    dependency_fingerprint_sha256: str

```
