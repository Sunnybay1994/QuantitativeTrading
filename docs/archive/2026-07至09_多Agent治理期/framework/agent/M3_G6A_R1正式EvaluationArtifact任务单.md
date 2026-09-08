# M3 G6A R1：正式 EvaluationArtifact 任务单

日期：2026-08-08  
状态：R2 已通过实现自测、全新独立复验与主 Agent 最终验收；仅关闭工程合同  
前置：正式 G5B 必须先通过独立复验和主 Agent 验收

## 1. 目标、价值与非目标

在现有 `quant.research.m3.evaluate` 中新增与 development example 严格隔离的
正式 G6A 路径。它从 fresh-verified 正式 G1→G5B 上游重建当前 fold 完整 test
日期域、五层 key/count/coverage、逐日 Pearson/Spearman IC 和稳定八状态，发布并
重新验证 work-scoped `EvaluationArtifact`。

本包通过只证明正式 G6A 工程契约。不执行或宣称：

- 正式全 folds/horizons evaluation work、G6B–G9 或 M3 已完成；
- 真实数据性能或 acceptance threshold 已通过；
- Windows/DrvFS 绿测等于 Linux/ext4 Gate；
- development evaluation 产物可以升格、复制或包装为正式 capability。

## 2. 权威来源与已确认事实

1. G6A 字段、八状态、五层集合、coverage 分母、IC/ICIR 及输出契约以
   `docs/framework/agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md` 第 8 节为 SSOT。
2. evaluation receipt 以同文档第 9.1 节为 SSOT：必须绑定本阶段实际读取的数据文件，
   不得只列 manifest/receipt 后依赖递归自洽。
3. `docs/framework/agent/M3_G4-G6设计审查与修订记录.md` P0-6/P0-10/P0-11 的根因和反例
   仍适用：test prediction 不能被 future label 选择；prediction batch lineage 必须验真；
   所有不可计算日必须用明确状态而非 NaN/泛化“零方差”。
4. 复用 `contracts.py` 现有 `EvaluationSpec`、`EvaluationUpstreamPaths`、
   `EvaluationMetricsV1`、`EvaluationManifestV1`、`IcStatus`、`VerifiedEvaluationArtifact`。
   不新增 formal schema 或另一套 metrics 值对象。
5. 复用 development 已验收的纯数学/helper、canonical JSON、冻结 Parquet 参数、
   receipt verifier 和 no-clobber 边界；不复制第二个评估算法。
6. `minimum_ic_symbols` 只来自 `LoadedM3Config` 的 scientific selector，且内部重建
   `EvaluationSpec` 后必须与传入 strict spec 精确相等。不新增
   `evaluation_config_sha256`，acceptance threshold 不进入科学结果 identity。

## 3. 冻结公开接口

新增并在 `quant.research.m3` 包根安全导出：

```python
def build_evaluation_artifact(
    *,
    release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec,
    prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec,
    config: LoadedM3Config,
    spec: EvaluationSpec,
    upstream_paths: EvaluationUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> EvaluationManifestV1: ...

def verify_evaluation_artifact(
    *,
    root: Path,
    receipt_path: Path,
    release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec,
    alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    model: VerifiedModelArtifact,
    model_spec: LightgbmTrainingSpec,
    prediction: VerifiedPredictionArtifact,
    prediction_spec: PredictionBuildSpec,
    config: LoadedM3Config,
    spec: EvaluationSpec,
    upstream_paths: EvaluationUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedEvaluationArtifact: ...
```

现有 `build_evaluation_spec` 和 development builder/verifier 的名称、签名、返回类型、
`stage=development-evaluation` 及错误契约保持不变。formal builder/verifier 自己从
exact `VerifiedPredictionArtifact` 和 scientific config 重建预期 spec，不需要第二个
公开 spec helper。

## 4. 完整 G1→G5B fresh verification

formal builder 和 verifier 均必须在首个输出写入前建立自己的完整信任链：

1. 所有公开输入使用 exact type gate，不接受 subclass、development capability、cast 或
   字段巧合对象。`LoadedM3Config`、spec/upstream-path 值对象同样精确验证。
2. 先调用正式 `verify_prediction_artifact`，传入 `prediction.root`、
   `upstream_paths.prediction_receipt_path`、`upstream_paths.prediction_upstream_paths` 和完整
   G1→G5B 参数。fresh 返回值必须与传入 prediction **exact 相等**，包括
   resolved absolute root、DataFrame、manifest 和 receipt identity。
3. 再调用正式 `verify_label_artifact`，用 `label.root`、
   `upstream_paths.label_receipt_path`、release/snapshot/experiment/config/experiment_spec/label_spec
   fresh-verify 当前 horizon 的完整 label bundle。返回值必须与传入 label exact 相等，
   包括 labels、diagnostics、root、manifest 和 receipt identity。
4. prediction fresh 链必须继续验证 G5A model 及正式 G4B label-free test inference；
   label fresh 链必须重算 label/diagnostics 并 fresh-verify G1 release。不得用手工检查一两个
   manifest hash 替代公开 verifier。
5. `EvaluationUpstreamPaths` 的显式 feature/fold/label receipt 必须与 nested
   prediction→model→alignment→feature/fold 链的对应物理路径精确相等；experiment receipt
   只从 nested `FoldPlanUpstreamPaths.experiment_receipt_path` 唯一导出。拒绝别名、
   同 bytes 不同路径或重复路径。
6. copied/relocated upstream 即使 bytes 相同，只要 fresh capability 的 absolute root 不同，
   就必须在 evaluation 计算和输出 0 bytes 前 fail closed。

## 5. 五层 key、count 与 coverage 不变量

评估日期域精确为当前 fold 的完整 `test_dates`，必须唯一且严格递增。
每层 frame 的 key 精确为 `(as_of: Date, symbol: String)`，唯一、按 key 稳定递增，
日期不得越出 test domain，value 列必须 Float64 且 finite。

| 层 | 唯一来源 | 定义 |
|---|---|---|
| eligible | fresh formal G1 `eligible_keys.parquet` 在完整 test dates 上的 key | PIT 可投资域 |
| scorable | fresh G4B `test.parquet` 中 selected features 可评分的 key | `scorable ⊆ eligible` |
| predicted | fresh G5B prediction 的 `(as_of,symbol,score)` | `predicted == scorable` |
| labeled | fresh G3A label 在当前 horizon/test dates 上的成功 key | `labeled ⊆ eligible` |
| evaluated | predicted 与 labeled 的唯一 inner intersection | `evaluated == predicted ∩ labeled` |

必须逐日记录五层 count，并同时重算全 test domain 的五层总 count。不接受
manifest 自报 count 或 join 后才推测 predicted/labeled 母集。整个 test eligible 总数为 0 或
labeled 总数为 0 时，builder 在发布前 fail closed；单日为 0 合法，仍必须输出该日。

四层 coverage 只允许以下分母：

```text
feature_coverage    = n_scorable / n_eligible
prediction_coverage = n_predicted / n_scorable
label_coverage      = n_labeled / n_eligible
evaluation_coverage = n_evaluated / n_labeled
```

分母为 0 时写 JSON/Parquet null，不写 NaN/Inf/0 伪值。汇总 coverage 必须用各层总 count
重新相除，不平均 daily coverage。label 缺失只能降低 `n_labeled`、`n_evaluated`、
`label_coverage` 或改变相应 status；绝对不得删减 predicted 或降低
`prediction_coverage`。在正常 G5B 契约下，非空 scorable 日的 prediction coverage 必须为 1.0。

## 6. 八状态优先级、IC 与 ICIR

每个 test date 按以下固定顺序选择**第一个**适用状态：

1. `NO_ELIGIBLE`：`n_eligible == 0`；
2. `NO_LABELS`：前者不成立且 `n_labeled == 0`；
3. `NO_PREDICTIONS`：前两者不成立且 `n_predicted == 0`；
4. `INSUFFICIENT_SYMBOLS`：`n_evaluated < minimum_ic_symbols`；
5. `BOTH_ZERO_VARIANCE`：evaluated score 与 return 均零方差；
6. `SCORE_ZERO_VARIANCE`：只有 score 零方差；
7. `LABEL_ZERO_VARIANCE`：只有 return 零方差；
8. `COMPUTABLE`：以上均不成立。

只有 `COMPUTABLE` 日计算 Pearson 与 Spearman，且只使用 evaluated rows。Spearman 对 tie
使用 average rank。非 `COMPUTABLE` 日的两个 IC 精确为 null；`COMPUTABLE` 日的两个
IC 必须 finite。

汇总 `pearson_ic_mean/rank_ic_mean` 是全部可计算日等权均值。ICIR 精确为
该组 daily IC 的 `mean / sample_std(ddof=1)`，不年化；可计算日少于 2 或 sample std
为 0 时 ICIR 为 null。禁止平均 fold ICIR、使用总行级 IC、年化、将 null 替换为 0，
或用 test metric 调参/选 fold/改 model。

`status_counts` 必须按上述八状态全量、固定顺序记录，包含 0 count，总和精确等于
`n_dates`；`n_computable_dates == status_counts["COMPUTABLE"]`。所有 count 是 JSON int/Parquet
Int64，bool/float 不得冒充 int。所有非空 float 必须 finite。

## 7. 产物、manifest、receipt 与 no-clobber

### 7.1 输出闭包

- output root 必须是调用方已创建的空实体目录，拒绝 symlink/junction/reparse、
  非空目录和第二次 build。不创建、清空、覆盖或修复旧产物。
- builder 在首次空目录预检时必须保留平台安全的目录实体身份，并在首个输出独占创建前
  fresh 重验路径仍指向同一目录实体。若 fresh verification/数学计算期间原目录被 rename/替换，
  必须在写入 0 bytes 时 fail closed；不得只重做路径 `lstat`、空目录或 reparse 检查就把替换目录
  当成原调用方的 output root。
- 输出精确只有 `daily_ic.parquet`、`metrics.json`、`evaluation_manifest.json`。
  `daily_ic.parquet` 列/schema 与 SSOT 精确一致，按完整 test dates 严格递增且不重复；
  Parquet 参数沿用 G4B 冻结值。
- JSON 使用 canonical bytes、`allow_nan=false`、exclusive create，拒绝重复/未知 key、
  non-canonical bytes、NaN/Inf。builder 必须在内存中完成全部 fresh/identity/key/count/
  metric 校验后才开始写文件；任一前置失败时 output root 保持空。
- 三个输出的正式发布是一个事务边界：Parquet 与 JSON 均必须从由本次调用以
  exclusive-create 方式成功打开的文件流写入，不得使用“先 exists 检查、后按路径覆盖”。
  任一写入、flush/fsync 或后续校验失败时，builder 只删除本次调用已成功独占创建的文件，
  不删除并发调用者抢先创建的文件或任何既有/未知文件；成功回滚后输出目录必须为空。
  回滚本身失败必须使用独立稳定码 `M3_EVALUATION_ROLLBACK_FAILED`，同样保证
  `cause/context is None`，不得掩盖成普通数学或上游校验失败。

### 7.2 manifest 闭包

`EvaluationManifestV1` 每个字段从 fresh capabilities、strict spec 和本次重算的 bytes
推导：experiment/work/prediction/label/feature/fold/eligible/evaluation dates/scientific config/fold/
horizon/model/version/daily/metrics。`eligible_keys_sha256` 绑定完整 test eligible 逻辑 key
摘要，同时必须与 G5B prediction manifest 中已 fresh-verified 的 eligibility identity 一致；
不盲信任一边自报。`daily_sha256` 与 `metrics_sha256` 均是物理 bytes hash。

verifier 必须从 fresh 五层输入重算 daily、metrics 和 manifest，逐行/逐列精确比对
产物，不只检查三个文件自洽。返回 exact
`VerifiedEvaluationArtifact(root.resolve(strict=True), ...)`。

### 7.3 `stage=evaluation` exact receipt 闭包

receipt 由现有 StageRunner/`publish_stage_receipt` 发布，builder 不另写 receipt。必须精确：

```text
stage     = evaluation
scope     = WORK
scope_key = spec.work_key
```

inputs 必须是下列 **17 个唯一物理路径**，多一个、少一个、重复、别名、同 bytes
不同路径或 digest 指向错误 root 均失败：

1. G1 release：release manifest、`eligible_keys.parquet`；
2. G4B feature：`feature_manifest.json`、feature receipt、`coverage.parquet`、`test.parquet`；
3. G5B prediction：`prediction_manifest.json`、prediction receipt、`predictions.parquet`；
4. G3A label：`label_manifest.json`、label receipt、`labels.parquet`、`diagnostics.parquet`；
5. fold：`folds.json`、fold receipt；
6. experiment：`experiment_manifest.json`、experiment receipt。

outputs 精确为上述 3 个 evaluation 文件。receipt verifier 必须重读全部 input/output bytes，
核对 root alias、物理路径、digest、stage/scope/scope_key 和无未知字段；只验通用
receipt 自洽不足以通过。

## 8. Formal/development 隔离、失败语义和禁止项

- `VerifiedEvaluationArtifact` 只是 formal capability；
  `VerifiedDevelopmentExampleEvaluationArtifact` 只是 development capability。formal 入口不得
  调用 development verifier，development 入口不得因本任务改变信任边界。
- formal builder/verifier 的未预期 IO、Polars、JSON、Parquet、receipt 和上游内部
  异常统一翻译为稳定、脱敏的
  `ValueError("M3_EVALUATION_ARTIFACT_INVALID")`。不输出绝对路径、原始异常、证券/数据
  内容或私有 sentinel；对外异常 `cause/context` 必须均为 `None`。现有
  development 错误文本不因此改变。
- 禁止读取/扫描 `data/legacy`，禁止网络、Qlib/LightGBM/MLflow 加载，禁止写
  正式 G1/G2 journal、候选目录或已有正式 artifact。evaluation 模块仍是轻依赖路径。
- 禁止读 test 之外日期、用 label 筛 prediction、静默补/丢/去重 key、用 daily ratio 平均
  代替总 count ratio，或将 test IC 反向用于 feature/model/fold 选择。

## 9. 可写白名单

实现 Agent 只允许修改：

- `src/quant/research/m3/evaluate.py`；
- `src/quant/research/m3/__init__.py` 中 formal G6A 必要安全导出；
- 新增 `tests/unit/test_m3_formal_evaluation_artifact.py`；
- 本任务的交付报告、独立初验报告与返工文档。

`contracts.py`、`development_example.py`、`predictions.py`、`labels.py`、`features.py`、所有 G1–G5B
生产代码、development tests 和配置默认只读。若发现现有值对象无法表达 9.1
exact receipt 闭包或上游路径唯一性，必须停止扩大实现，先向主 Agent 提交最小
复现和建议的 SSOT/任务单修订；不得私改 `contracts.py` 或推测隐含路径。

## 10. 必测正例与对抗反例

### 10.1 正例

- exact formal G1→G5B build→evaluation build→receipt→verify，返回 exact
  `VerifiedEvaluationArtifact`，输出精确 3 文件；
- 完整多日 test domain，每日都有唯一记录；正例覆盖可评分/不可评分 eligible、
  部分 label 缺失和至少两个 `COMPUTABLE` 日；
- 八状态各有独立 fixture，并有同时命中多条件时优先级只取第一项的组合反例；
- Pearson/Spearman 使用受控手算值，Spearman average tie；两个可计算日手算 sample
  std/ICIR，单可计算日和零 sample std 的 ICIR 为 null；
- top-level `import quant.research.m3` 和 `evaluate.py` import 不加载 Qlib/LightGBM/MLflow。

### 10.2 必测反例

1. formal/dev release、snapshot、provider、experiment、fold、feature、label、alignment、model、
   prediction、evaluation capability 任一互换，或 subclass 伪装；
2. cross experiment/work/snapshot/fold/horizon/model/model-version/scientific-config 混配，
   `minimum_ic_symbols` 用 caller 自报值绕过 config；
3. fresh prediction/label verifier 返回 bytes 相同但 absolute root 不同 capability；需在
   output 0 bytes 前拒绝；
4. eligible/scorable/predicted/labeled 任一重复、乱序、dtype/value 漂移或日期越界；
   `scorable ⊄ eligible`、`predicted != scorable`、`labeled ⊄ eligible`、
   `evaluated != predicted ∩ labeled` 逐一 fail closed；
5. 四个 denominator 分别为 0，必须得 null；整个 test eligible/labeled 总数为 0 则发布前
   fail closed；bool/float count、NaN/Inf JSON/Parquet 拒绝；
6. minimum symbols 边界 `N-1/N`，score/label 单零与双零方差，tie，单可计算日、
   两日 sample std、多日 zero std，年化或 daily-ratio-average 伪实现；
7. output 非空、symlink/junction/reparse、第二次 build，及前置失败后产生部分文件；
   在 hostile upstream verifier/计算返回前将已预检的 output root rename 并以另一空实体目录替换
   原路径，builder 必须拒绝且原目录/替换目录均为 0 files；
   还必须覆盖 Parquet/第一 JSON/第二 JSON writer 分别抛出 ValueError 和非 ValueError，
   失败后目录为空且异常链不泄露；并发抢先创建同名 Parquet/JSON 时不覆盖也不删除对方文件；
   模拟回滚 unlink 失败时返回独立稳定码且 `cause/context is None`；
8. 三个输出任一 byte 篡改/缺失/多出，Parquet schema/列序/dtype/日期序漂移，
   JSON 重复/未知 key、non-canonical bytes 和 non-finite；
9. receipt stage/scope/scope_key 错误，17 inputs 任一缺失/多余/重复/别名/指向错误 root，
   3 outputs 任一缺失/多余，或未知字段；
10. **wholesale 重签反例**：将另一 work 的 daily/metrics/manifest 整包复制，修改
    work/upstream hashes 和 content hashes，并用目标 work 的合法 17-input/3-output 闭包重新发布
    语法正确的 receipt；只要数学结果不是目标 fresh 五层输入重算值，verifier 必须拒绝。
11. **label 缺失不得降低 prediction coverage**：构造两条合法、可 fresh-verify 的 formal fixture
    链，第二条只通过 future exit 端缺失/生命周期边界使部分 label 进入合法 diagnostic，
    不直接篡改已验真 label artifact。在 scorable/prediction keys 不变时，必须保持
    `n_predicted == n_scorable` 和 daily/aggregate `prediction_coverage == 1.0`；只允许
    labeled/evaluated/label coverage/status 变化。
12. 上游 verifier、Parquet/JSON/receipt reader 抛含私有路径/sentinel 的异常；公开边界只暴露
    稳定 code，`cause/context` 均为 `None`。

## 11. 验证命令与平台边界

测试必须使用最小确定 fixture，无网络、不扫描 `data/legacy`、不写正式 artifact/journal，
每次 pytest 使用唯一 temp/basetemp。

Windows 原生定向验证：

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_formal_evaluation_artifact.py `
  tests/unit/test_m3_formal_prediction_artifact.py `
  tests/unit/test_m3_evaluation_artifact.py `
  tests/unit/test_m3_evaluate.py -q
D:\Miniforge3\python.exe -m ruff check `
  src/quant/research/m3/evaluate.py src/quant/research/m3/__init__.py `
  tests/unit/test_m3_formal_evaluation_artifact.py
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/evaluate.py
```

WSL Miniforge base 在同一 `/mnt/f/.../m3-g4-formal` 路径运行对应 pytest/Ruff/mypy。
`/mnt/f` 是 DrvFS：该证据只说明 WSL base 解释器与当前路径的定向兼容性，
不表示 ext4/Linux Gate 通过。Windows 绿测、development 绿测和 fake upstream 也不是
正式全 work/Gate 证据。G6A 自身不需要启动 Qlib/LightGBM/MLflow；若实现导入它们，
视为架构回归。

## 12. 交付、独立初验和停止条件

交付报告必须列出：改动文件、fresh call 图、5 层集合与 4 分母对应证据、
8 状态覆盖、IC/ICIR 手算对照、17-input/3-output receipt 闭包、验证命令/实际结果
和未关闭 Gate。

未参与实现的独立初验者保持生产代码和实现测试只读，必须增加实现者未用的对抗反例，
至少包含 wholesale 重签或 label/prediction coverage 中的一项，以及一项多条件同时成立的
status priority 反例。初验 PASS 后仍由主 Agent 复核 SSOT、formal/development 边界、receipt
实际数据文件闭包、轻依赖 import 和平台声明。

以下任一情形必须停止扩大实现并返回主 Agent 重新冻结：

- 正式 G5B 最终公开签名、fresh 语义或 receipt 闭包与其任务单不一致；
- `EvaluationUpstreamPaths` 无法唯一、无别名地导出 17 个 receipt input 物理路径；
- SSOT 与 formal capability 的实际字段冲突，需修改 `contracts.py`、配置或 G1–G5B 代码；
- 验证证明发布路径可篡改已有产物，或未预期扫描/网络/重依赖读取。

正式 G6A 独立初验和主验通过前，不运行正式全 folds/horizons evaluation，
不进入正式 G6B。

## 13. R2：共享 publication 首写前 current-root 复验（2026-08-09）

R1 独立初验报告：`M3_G6A_R1正式EvaluationArtifact独立初验报告.md`。结论 FAIL；fresh 链、五层/四分母、
八状态、IC/ICIR、17-input/3-output receipt、wholesale 重签、coverage 与异常脱敏均通过，唯一阻断在共享发布
原语。

### 13.1 失败闭环

POSIX/WSL 在 fresh verifier 返回后、首个 evaluation 输出前把 caller `output_root` rename并以另一空目录替换。
最终 builder稳定报错且新旧目录均回滚为空，但探针显示 `FRESH_CALLS=1, WRITE_CALLS=3`。Windows因 no-share-delete
目录handle阻止rename，`WRITE_CALLS=0`。根因 `_artifact_publication.py::ArtifactPublication.write_stream()` 在
`_open_output()` 和调用 writer 前没有 `_require_current_root()`，只在 acquire/commit检查；POSIX dir-fd仍锚着
旧目录，因此会把三文件写入已脱离caller路径的旧实体后才在commit发现漂移。

这违反 §7.1“首个输出独占创建前 fresh 重验路径仍指向同一目录实体；不成立则不写输出”的不变量。

### 13.2 最小返工规则

- 扩大本轮白名单仅允许修改共享 `src/quant/research/m3/_artifact_publication.py` 及其直接 G5A/G5B/G6A
  publication tests；不得改变G1–G5B业务/数学/receipt接口。
- `write_stream()` 每个输出都必须在 `_open_output()` **之前**调用 `_require_current_root()`；exclusive open取得
  descriptor并记录owned identity后、调用任何 caller writer **之前**再次对原 anchor与当前path执行
  `_require_current_root()`。第二次失败只允许回滚本次空owned file，writer调用次数为0。
- POSIX仍从原dir-fd独占open，Windows仍使用原handle身份/no-share-delete；不得为通过测试退化成普通path IO。
- writer执行后原有fsync、owned identity、exact entries、commit和rollback语义不变；root在writer执行过程中漂移
  仍由返回前/commit复验与精确rollback关闭。

### 13.3 新增测试与通过条件

- formal G6A在fresh窗口、数学窗口结束后首写前分别替换root：若平台允许替换，fresh调用按预期完成但
  writer/open-content回调为0、旧新目录均无retained bytes；若Windows阻止替换，同样writer为0。
- 对共享 `ArtifactPublication.write_stream` 增加“pre-open漂移”和“open后/writer前漂移”探针；后者允许短暂
  exclusive空文件但必须由owned rollback删除，writer为0且不删竞争文件。
- G5A model、G5B prediction、G6A evaluation的root replacement、writer/fsync/rollback/no-clobber全组回归；
  Windows与WSL base/DrvFS定向pytest/Ruff/mypy通过。
- R2 由原G6A实现上下文最小返工，再由未参与R2的全新独立上下文复验；PASS后才进入主Agent终验。
