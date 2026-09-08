# M3 G6B R1：正式 ResearchSummaryArtifact 任务单

日期：2026-08-08  
状态：主 Agent 最终验收通过（仅工程合同；正式全 work/ext4/M3 Gate 仍开放）  
前置：正式 G6A 必须先通过外部独立复验和主 Agent 最终验收；本任务冻结不等于获准运行正式全 folds/horizons

## 1. 目标、价值与非目标

在现有 `quant.research.m3.evaluate` 中新增与 development example 严格隔离的正式 G6B
路径。它针对一个已 fresh-verified 的正式 experiment 和一个固定 horizon，证明该 horizon 的
**全部 planned folds** 均有唯一、最新、可重算的正式 `VerifiedEvaluationArtifact`，随后按日期拼接
各 fold 的 `daily_ic.parquet`，从拼接后的 daily observations 重算 experiment-scoped 汇总指标，
并发布、重新验证正式 `ResearchSummaryArtifact`。

本包通过只证明正式 G6B 工程契约。不执行或宣称：

- 正式全 horizons 汇总、真实数据性能、acceptance threshold、G7–G9 或 M3 已完成；
- 任何 “best fold”、模型/特征/超参数选择，或用 test IC 反向修改 G4/G5；
- Windows/DrvFS 绿测等于 Linux/ext4 Gate；
- development summary 产物可以复制、包装、重签或升格为正式 capability。

## 2. 权威来源与已确认事实

1. G6B 的同 horizon、跨 fold 拼接、输出与禁止项以
   `docs/framework/agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md` 第 8.4 节为 SSOT；
   receipt 以同文档第 9.1 节为 SSOT。
2. `docs/framework/agent/M3_G4-G6设计审查与修订记录.md` 的来源闭包、完整 test 域、明确不可计算状态、
   no-clobber 与禁止 test 反馈选择规则继续适用。
3. 正式单 fold evaluation 的 fresh verification、五层集合、八状态、IC/ICIR、17-input receipt
   闭包以 `docs/framework/agent/M3_G6A_R1正式EvaluationArtifact任务单.md` 为直接前置。
4. 复用 `contracts.py` 现有 `ResearchSummaryUpstreamPaths`、`ResearchSummaryMetricsV1`、
   `ResearchSummaryManifestV1`、`VerifiedResearchSummaryArtifact`；不新增另一套正式 summary schema、
   metrics 或 capability。
5. 复用 development 已验收的 canonical JSON、固定 Parquet writer、daily 汇总纯函数、
   fold metrics schema、receipt verifier 与空目录/no-clobber helper；不得复制第二套汇总数学。
6. 当前 `VerifiedEvaluationArtifact` 只保存 evaluation 结果和 receipt identity，不保存重新调用正式
   G6A verifier 所需的完整 G1→G5B 参数。因此仅靠 G6B 骨架中的 `evaluations` 参数不能履行
   “fresh-verify 所有 folds”。本任务冻结一个**非序列化、只用于调用 verifier 的 in-memory
   context**；它不进入 manifest/receipt，不改变任何 artifact schema。

## 3. 冻结公开接口

### 3.1 fresh verification context

在 `evaluate.py` 新增并从 `quant.research.m3` 包根安全导出 frozen dataclass
`EvaluationFreshVerificationContext`。它只聚合一次正式 `verify_evaluation_artifact` 调用所需、
且无法从 `VerifiedEvaluationArtifact` 恢复的现有 formal 值对象：

```python
@dataclass(frozen=True)
class EvaluationFreshVerificationContext:
    release: VerifiedG1Release
    snapshot: VerifiedSnapshotArtifact
    snapshot_spec: SnapshotBuildSpec
    provider: VerifiedProviderArtifact
    provider_spec: ProviderBuildSpec
    experiment: VerifiedExperimentIdentity
    experiment_spec: ExperimentIdentitySpec
    folds: VerifiedFoldPlanArtifact
    fold_spec: FoldPlanBuildSpec
    feature: VerifiedFeatureArtifact
    feature_spec: FeatureBuildSpec
    label: VerifiedLabelArtifact
    label_spec: LabelBuildSpec
    alignment: VerifiedAlignmentArtifact
    alignment_spec: AlignmentBuildSpec
    model: VerifiedModelArtifact
    model_spec: LightgbmTrainingSpec
    prediction: VerifiedPredictionArtifact
    prediction_spec: PredictionBuildSpec
    evaluation_spec: EvaluationSpec
    evaluation_upstream_paths: EvaluationUpstreamPaths
```

该 context 的 `__post_init__` 对自身及每个成员执行 exact type gate；不接受 subclass、development
capability、Mapping、tuple positional payload 或字段巧合对象。evaluation 本体、evaluation receipt、
`LoadedM3Config` 与 `artifact_roots` 分别由 G6B 的 `evaluations`、`ResearchSummaryUpstreamPaths` 和
顶层参数提供，避免在 context 重复保存两份身份。

### 3.2 builder/verifier

新增并安全导出：

```python
def build_research_summary_artifact(
    *,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    evaluation_contexts: Sequence[EvaluationFreshVerificationContext],
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    horizon_sessions: Literal[5, 10],
    upstream_paths: ResearchSummaryUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> ResearchSummaryManifestV1: ...

def verify_research_summary_artifact(
    *,
    root: Path,
    receipt_path: Path,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    evaluation_contexts: Sequence[EvaluationFreshVerificationContext],
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    horizon_sessions: Literal[5, 10],
    upstream_paths: ResearchSummaryUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedResearchSummaryArtifact: ...
```

builder 也必须 fresh-verify，且在首个输出 byte 前完成全部上游、集合、日期、数学和 identity 校验。
`upstream_paths.evaluation_receipt_paths` 必须已经按 fold 严格递增，与 `evaluations`、contexts 一一
对应；实现不得靠 basename、共同父目录或 hash 猜路径。现有 development builder/verifier 的名称、
签名、返回类型、`stage=development-research-summary` 和错误文本保持不变。

## 4. 同 horizon 全 folds fresh verification

builder 与 verifier 每次调用均执行相同信任链：

1. 顶层参数以及每个 evaluation/context 使用 exact type gate。序列非空且三组长度精确相等；
   evaluation fold、context `evaluation_spec.fold`、receipt path 以同一 index 对齐，随后验证 folds
   已严格递增。拒绝先各自排序再 zip，防止 receipt/context 被静默错配。
2. 对每个 index 调用正式 `verify_evaluation_artifact`：`root=evaluation.root`、对应
   `receipt_path`，其余参数来自 context 与顶层 `config/artifact_roots`。fresh 返回值必须与传入
   evaluation **exact 相等**，包括 resolved absolute root、daily DataFrame、metrics、manifest、
   manifest hash 和 evaluation receipt hash。
3. 每个 context 的 experiment 必须与顶层 `experiment` exact 相等；config scientific hash、
   experiment/model/model-version、snapshot/provider/fold-plan identity 必须跨所有 contexts 一致。
   copied/relocated upstream 即使 bytes 相同，只要 absolute root 或物理 receipt path 不同也失败。
4. 所有 contexts 的 fresh `VerifiedFoldPlanArtifact` 必须 exact 相等。expected fold set 唯一取自
   `folds.manifest.folds`，实际 evaluation folds 必须与其名称元组**精确相等**；缺一折、多一折、
   重复折或只提交 “表现最好”的子集均失败。不得从调用者自报 folds 推定完整性。
5. 每个 evaluation 的 horizon 精确等于顶层 `horizon_sessions`；work/spec/label/prediction horizon
   同样一致。任一 h=5/h=10 混入均失败，不能按 horizon 静默过滤。
6. 每个 evaluation daily 的日期必须精确等于对应 `PlannedFold.test_dates`，唯一、严格递增；
   所有 folds 的 test date sets 两两不相交。虽然 formal fold plan 自身已约束，G6B 仍从 fresh
   capability 重新对齐，不盲信 summary caller。
7. `ResearchSummaryUpstreamPaths.experiment_receipt_path` 必须与每个 context 内 formal 链唯一导出的
   experiment receipt 为同一物理路径；其 digest 精确等于 `experiment.experiment_receipt_sha256`。
   evaluation receipt paths 必须与 fresh 返回 capability identity 一一相等、唯一且无 alias。

任何一项失败时，不读取旧 summary 充当输入，不写 output，不发布 receipt。

## 5. daily 拼接、汇总数学与 fold projection

### 5.1 `daily_ic.parquet`

输入只允许各 fresh evaluation 的已验真 `daily`。按 fold 取出完整 daily，拼接后按 `as_of`
稳定排序；结果必须恰好覆盖所有 planned fold test dates，日期唯一、严格递增，schema/列序/dtype
与 G6A `_DAILY_SCHEMA` 精确相等。不得平均 fold daily、删掉不可计算日、补不存在的交易日，或把
同日两折聚合为一行。

### 5.2 `metrics.json`

所有 summary metrics 均从**拼接后的 daily observations** 重算：

- 五层总 count 是 daily count 逐日求和；四个 coverage 用总 count 按 G6A 的四个固定分母相除，
  不平均 daily coverage 或 fold coverage；分母 0 写 null；
- `status_counts` 按 G6A 八状态固定顺序全量记录，包含 0 count，和精确等于 `n_dates`；
- IC mean 使用所有 `COMPUTABLE` daily IC 等权均值；
- ICIR 使用所有 `COMPUTABLE` daily IC 的 `mean / sample_std(ddof=1)`，不年化；不足 2 日或
  sample std 为 0 时为 null；
- **严禁平均、加权平均或选择 fold-level ICIR**。即使每折 ICIR 都可计算，summary ICIR 仍必须
  只从跨折拼接后的 daily IC 序列重新计算；
- count 是 JSON int，Parquet Int64；bool/float 不得冒充；所有非空 float 必须 finite，JSON
  `allow_nan=false`。

### 5.3 `fold_metrics.parquet`

该表只是按 fold 严格递增排列的每个 fresh `EvaluationMetricsV1` 的**严格投影**。实现必须从
capability 的 typed metrics 构造，不能接受 caller Mapping、读取旧 summary 表或重算另一种 fold
统计。列顺序固定为：

```text
fold,
n_dates,n_computable_dates,n_eligible,n_scorable,n_predicted,n_labeled,n_evaluated,
feature_coverage,prediction_coverage,label_coverage,evaluation_coverage,
pearson_ic_mean,rank_ic_mean,pearson_icir,rank_icir,
status_count_no_eligible,status_count_no_labels,status_count_no_predictions,
status_count_insufficient_symbols,status_count_both_zero_variance,
status_count_score_zero_variance,status_count_label_zero_variance,
status_count_computable
```

count/status 列为 Int64，coverage/IC 列为 Float64（nullable），fold 为 String。行数精确等于
expected fold count，fold 唯一且严格递增。每一单元格都必须等于对应 typed metrics 投影；
verifier 不能只验 schema/hash。

## 6. 输出、manifest、receipt 与 no-clobber

### 6.1 输出闭包

- `output_root` 是调用方已创建的空实体目录，目录名为 `horizon=<horizon_sessions>`；拒绝
  symlink/junction/reparse、非空目录和第二次 build，不创建、清空、覆盖或修复旧产物。
- 首次空目录预检必须保留平台安全的目录实体身份，并在首个输出 exclusive-create 前 fresh
  证明原路径仍指向同一实体。逐 fold fresh verification/汇总期间目录被 rename 并以另一空目录替换时，
  必须在写入 0 bytes 时 fail closed；只重做路径 `lstat`/空目录检查不能证明还是原调用方目录。
- 输出精确只有 `daily_ic.parquet`、`fold_metrics.parquet`、`metrics.json`、`manifest.json`。
  Parquet 参数复用冻结 writer；JSON canonical、exclusive create、无重复/未知 key、NaN/Inf。
- 全部 fresh verification 与内存重算在首个输出 byte 前完成。四个输出共同形成事务发布边界：
  Parquet 与 JSON 均从本次调用 exclusive-create 成功打开的文件流写入，不得“先 exists 检查、
  后按路径覆盖”。任一写入、flush/fsync 或后续校验失败时，只回滚本次已成功独占创建的
  文件，不覆盖、不删除并发调用者抢先创建或任何既有/未知文件。成功回滚后目录必须为空；
  回滚本身失败使用独立稳定码 `M3_RESEARCH_SUMMARY_ROLLBACK_FAILED`，公开异常
  `cause/context` 均为 `None`。不保留 partial bundle 作为恢复协议，不自动覆盖/续写。

### 6.2 manifest 闭包

`ResearchSummaryManifestV1` 每个字段从 fresh capabilities、顶层 config 和本次物理 bytes 推导：

- experiment/scientific config/horizon/model/model-version；
- `folds` 为 formal fold plan 的完整有序 fold names；
- `evaluation_manifest_sha256s`、`evaluation_receipt_sha256s` 与 folds 同序一一对应；
- `test_dates_sha256` 对拼接后严格递增的完整 dates 计算，不对 fold hashes 二次 hash 代替；
- daily/fold_metrics/metrics 三个物理 bytes hash。

verifier 必须 fresh-verify 全部 evaluations，再重建 daily、fold projection、metrics 和 manifest，
逐表逐字段精确比对；不得以四文件互相引用、hash 自洽或 receipt 已重签代替重算。返回 exact
`VerifiedResearchSummaryArtifact(root.resolve(strict=True), ...)`。

### 6.3 `stage=research-summary` exact receipt closure

receipt 仍由现有 StageRunner/`publish_stage_receipt` 在 builder 成功后发布，builder 不另写 receipt：

```text
stage     = research-summary
scope     = EXPERIMENT
scope_key = experiment.manifest.experiment_key
```

inputs 精确按以下顺序组成，且全部是唯一物理路径：

1. experiment bundle：`experiment_manifest.json`、experiment receipt；
2. 按 fold 严格递增的每个 evaluation bundle：`daily_ic.parquet`、`metrics.json`、
   `evaluation_manifest.json`、对应 evaluation receipt。

若共有 `F` 个 folds，则 inputs 精确为 `2 + 4F` 个。这里的 bundle 包含阶段实际数据文件，
不是只列 manifest/receipt。outputs 精确为 summary 的 4 个文件。多一个、少一个、重复、alias、
同 bytes 不同物理路径、错误 root、未知字段、stage/scope/scope_key 错误均失败。receipt verifier
必须重读全部 input/output bytes；递归 receipt 自洽或 digest set 大致相等不足以通过。

## 7. Formal/development 隔离、失败语义与禁止项

- `VerifiedResearchSummaryArtifact` 只代表 formal capability；
  `VerifiedDevelopmentExampleResearchSummaryArtifact` 只代表 development capability。formal 入口
  只接收 exact formal evaluation/experiment/context，绝不调用 development verifier；development
  入口不得因本任务改变行为或信任边界。
- formal builder/verifier 的未预期上游、IO、Polars、JSON、Parquet、receipt 异常统一翻译为稳定、
  脱敏的 `ValueError("M3_RESEARCH_SUMMARY_ARTIFACT_INVALID")`。公开异常的
  `__cause__`、`__context__` 均为 `None`；不得泄露绝对路径、原始异常、证券/数据内容或测试 sentinel。
  development 的既有错误文本保持不变。
- 禁止网络、Qlib/LightGBM/MLflow 加载、扫描 `data/legacy`、读取 label/prediction 原始数据绕过 G6A，
  或写正式 G1/G2 journal、候选目录及任何已有 formal artifact。
- 禁止跨 horizon 汇总、缺 fold、重复 fold、折间 test 日期重叠、选 best fold、平均 fold ICIR、
  在 G6B 调阈值/模型/feature，或引入任何 G7 NAV/成本/组合逻辑。

## 8. 可写白名单

实现 Agent 只允许修改：

- `src/quant/research/m3/evaluate.py`；
- `src/quant/research/m3/__init__.py` 中 G6B 与 context 的必要安全导出；
- 新增 `tests/unit/test_m3_formal_research_summary_artifact.py`；
- 本任务的交付、独立初验和返工报告。

`contracts.py`、`development_example.py`、所有 G1–G6A 生产代码、development tests、配置和 SSOT
默认只读。若正式 G6A 最终签名与本任务不一致，或上述 in-memory context 仍不足以无歧义调用其
verifier，必须停止实现并向主 Agent 返回最小复现；不得私改 schema、猜 receipt 路径或降低 fresh
verification。

## 9. 必测正例与对抗反例

### 9.1 正例

- 一个 formal experiment、至少 3 个 planned folds、固定 h=5：乱序输入必须被明确拒绝；按严格
  fold 顺序输入后，逐 fold fresh G6A verify、summary build→receipt→verify 成功，返回 exact
  `VerifiedResearchSummaryArtifact`，输出精确 4 文件；
- 各 fold test dates 完整且不重叠，包含 `COMPUTABLE` 与至少两种不可计算状态；拼接结果覆盖
  fold plan 全部 test dates；
- 用受控 daily IC 使 “平均 fold ICIR” 与 “拼接 daily 后 ICIR” 明显不同，手算证明实现采用后者；
- `fold_metrics` 每列逐格等于 ordered `EvaluationMetricsV1` 投影，nullable 和 dtype 精确；
- top-level import 与 `evaluate.py` import 不加载 Qlib/LightGBM/MLflow。

### 9.2 必测反例

1. formal/dev evaluation、experiment、summary capability 或 context 任一互换，以及 subclass 伪装；
2. **fold 缺失/重复/跨 horizon**：相对 fresh fold plan 少一折、多一折、重复 fold，或混入另一
   horizon/model/model-version/experiment/scientific-config；均在 output 0 bytes 前拒绝；
3. fold/context/receipt 三序列分别排序后错误 zip、同 hash receipt 复制到新路径、receipt 路径 alias、
   copied evaluation root，必须 fresh fail closed；
4. 任一 evaluation 的 daily 日期缺失、多余、重复、乱序、越出对应 test dates，或两折日期重叠；
5. **不得平均 fold ICIR**：构造各 fold 样本数和均值不同的 daily IC；若实现平均/加权平均
   fold ICIR，必须被手算期望击穿；单个、零 std、跨折后可计算三种边界均覆盖；
6. **伪造 fold metrics 但重哈希**：修改一行 count/coverage/IC/status 或交换两折，随后重写
   `fold_metrics_sha256`、manifest/metrics content hashes，并用目标 exact inputs/outputs 重签合法
   receipt；verifier 必须用 fresh typed metrics 严格投影拒绝；
7. **wholesale summary 重签**：复制另一 experiment/horizon 或另一组 evaluations 的四文件，修改
   experiment/fold/upstream/content hashes 使 JSON 内部自洽，再针对目标 `2+4F` inputs/4 outputs
   发布语法正确 receipt；只要不是目标 fresh evaluations 重算结果就必须拒绝；
8. 四个输出任一 byte 篡改/缺失/多出，Parquet 列序/schema/dtype/日期/fold 顺序漂移，JSON
   重复/未知 key、non-canonical/non-finite；
9. output 非空、symlink/junction/reparse、第二次 build；以及任一 fresh/identity/math 前置失败后
   目录必须仍为空；还必须逐个覆盖两个 Parquet/两个 JSON writer 抛出 ValueError 和
   非 ValueError 后精确回滚为空、并发抢占同名文件不覆盖也不删除、unlink 回滚失败返回独立稳定码，
   且所有公开异常 `cause/context is None`；在任一 fresh fold verifier 返回前 rename 已预检根并以新空目录替换
   原路径时必须拒绝，原/替换目录均 0 files；
10. receipt stage/scope/scope_key 错误，`2+4F` inputs 任一缺失/多余/重复/alias/错误 root，
    4 outputs 任一缺失/多余或未知字段；
11. 上游 formal G6A verifier、Parquet/JSON/receipt reader 抛含私有路径和 sentinel 的异常；公开
    G6B 边界只暴露稳定 code，`cause/context` 均为 `None`。

## 10. 验证命令与平台边界

测试使用最小确定 formal fixture，无网络、不扫描 `data/legacy`、不写正式 artifact/journal；每次
pytest 使用唯一 temp/basetemp。正式 G6A 未验收前，只可实现 isolated fixture 和定向测试，不能运行
正式全 folds summary。

Windows 原生定向验证：

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_formal_research_summary_artifact.py `
  tests/unit/test_m3_formal_evaluation_artifact.py `
  tests/unit/test_m3_research_summary_artifact.py `
  tests/unit/test_m3_evaluation_artifact.py -q
D:\Miniforge3\python.exe -m ruff check `
  src/quant/research/m3/evaluate.py src/quant/research/m3/__init__.py `
  tests/unit/test_m3_formal_research_summary_artifact.py
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/evaluate.py
```

WSL Miniforge `base` 在同一 `/mnt/f/.../m3-g4-formal` 路径运行对应 pytest/Ruff/mypy。
`/mnt/f` 是 DrvFS，此证据只说明 WSL base 解释器与当前共享路径的定向兼容性，不表示 ext4/Linux
Gate。Windows 绿测、development summary 绿测、fake formal upstream 或单个 horizon fixture 均不是
正式全 experiment/Gate 证据。

## 11. 交付、独立初验与停止条件

交付报告必须列出：改动文件、逐 fold fresh call 图、formal fold-plan 完整集合证明、test date
闭包、daily 拼接及 ICIR 手算对照、fold metrics typed projection、`2+4F` inputs/4 outputs receipt
闭包、验证命令/实际结果和未关闭 Gate。

未参与实现的独立初验者保持生产代码和实现测试只读，必须补充实现者未用反例，至少同时覆盖：

- wholesale summary 重签；
- fold 缺失/重复/跨 horizon 中一项；
- 伪造 fold metrics 后完整重哈希和重签。

初验 PASS 后仍由主 Agent 复核 SSOT、formal/development 类型边界、完整 fold set、daily 重算、
receipt 实际数据文件闭包、轻依赖 import 和平台声明。

以下任一情形必须停止扩大实现并返回主 Agent 重新冻结：

- 正式 G6A 最终签名、receipt/fresh 语义或 capability 字段与本任务不一致；
- 无法从 fresh fold plan 证明提交的是该 horizon 全 folds，或无法唯一对齐
  evaluation/context/receipt 三元组；
- exact receipt 需要修改 `contracts.py`、G1–G6A 生产代码、配置或 SSOT；
- 验证发现旧 summary 可被覆盖/修复，或出现未预期网络、legacy 扫描、重依赖加载。

正式 G6B 独立初验和主验通过前，不运行正式全 horizons summary，不进入正式 G7。
