# M3 G5B R1：正式 PredictionArtifact 任务单

> 2026-08-09 状态补充：R2 已关闭半发布、Parquet 覆盖竞态与 copied-root 先加载 LightGBM；
> 独立复验新增的 root rename/replacement 反例仍可将两文件发布到替换目录，故 R2 FAIL。R3 以
> `M3_G5A_R4-G5B_R3_输出根租约与事务发布返工任务单.md` 为唯一返工契约。
>
> 2026-08-09：R3 实现与双平台定向自测已交付，证据见
> `M3_G5A_R4-G5B_R3_输出根租约与事务发布返工交付报告.md`；状态仍为等待独立复验与主验，
> 尚未解锁正式 G6。

日期：2026-08-08  
状态：契约冻结，待实现  
前置：G4B/G4C 正式 capability 及 G5A R2 必须已通过独立复验和主 Agent 验收

## 1. 目标与完成边界

在现有 `quant.research.m3.predictions` 中新增一条与 development example 严格隔离的
正式 G5B 路径：从 fresh-verified 正式 G5A model 和 fresh-verified 正式 G4B test feature
构造、发布并重新验证 work-scoped `PredictionArtifact`。

本包通过只表示正式 G5B 工程契约关闭，不代表：

- 正式全 folds/horizons work 已运行；
- 真实数据性能、G6–G9、M3 或 Linux/ext4 Gate 已通过；
- development example 产物可以升格或转换为正式 capability。

## 2. 权威契约与现有边界

1. G5B 字段、计数、rank 与发布契约以
   `docs/framework/agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md` 第 7 节为 SSOT。
2. 字段与跨字段约束继续由 `contracts.py` 中现有 `PredictionBuildSpec`、
   `PredictionManifestV1`、`PredictionUpstreamPaths`、`VerifiedPredictionArtifact` 与
   `quant.domain.PredictionScoreSchema` 权威定义，不另起一套 formal schema。
3. `VerifiedPredictionArtifact` 是正式 capability；
   `VerifiedDevelopmentExamplePredictionArtifact` 只是 development capability。两者不得 cast、
   包装、复制或依靠字段巧合互换。
4. 复用现有 `normalize_prediction_scores`、manifest reader、Parquet 写参数、
   content hash 和 run-state receipt 公共接口；不增加第二个 rank normalizer。
5. 保持现有 development builder/verifier/spec helper 的公开名称、签名、返回类型和
   `stage=development-predictions` 不变。正式路径不得调用 development verifier。

## 3. 冻结公开接口

新增并在 `quant.research.m3` 包根安全导出：

```python
def build_prediction_artifact(
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
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
    upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> PredictionManifestV1: ...

def verify_prediction_artifact(
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
    config: LoadedM3Config,
    spec: PredictionBuildSpec,
    upstream_paths: PredictionUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedPredictionArtifact: ...
```

不新增第二个公开 spec 值对象。正式 builder/verifier 必须在内部从 exact formal
model/feature/folds/experiment 重建 `PredictionBuildSpec` 并与调用方传入值精确相等；
`eligibility_sha256`、`signal_dates_sha256`、snapshot/work/fold/horizon/model/version 和三层计数
一律从 fresh capabilities 推导，不接受 caller 自报。

## 4. Formal freshness 与 label-free inference

builder 和 verifier 均必须建立自己的 fresh 信任链，不信任调用方“刚验过”的声明：

1. 先用公开 `verify_model_artifact` 以 `model.root`、
   `upstream_paths.model_receipt_path`、`upstream_paths.model_upstream_paths` 和完整
   G1→G4C/G5A 参数 fresh-verify model。返回值必须与传入 `model` 精确相等，
   包括 resolved absolute root、manifest 和 receipt identity。
2. 再用公开 formal `build_inference_segment` 从 G4B test feature 重建 inference；
   `InferenceUpstreamPaths` 只由 `PredictionUpstreamPaths.feature_receipt_path` 和
   `.feature_upstream_paths` 组成。该调用必须继续 fresh-verify G4B 及完整正式上游。
3. label/alignment 只是 G5A model freshness 所需的历史训练闭包；test inference loader、
   expected test keys、计数和 predict 签名均不接收、读取或 join test label。对 test 末尾尚无
   future label 的 scorable feature 仍必须预测，不得缩成“有 label 子集”。
4. 任一 exact type、身份、fresh capability 或上游路径检查失败，必须发生在
   LightGBM load/predict 和首个输出写入之前。copied-root 即使 bytes 相同也是 stale。

## 5. 预测、key/order 与唯一 normalizer

1. builder 在所有 fresh/identity/key 前置检查通过后，对传入的 exact
   `VerifiedModelArtifact` 调用公开 `predict_fitted_model` **精确一次**；不直接调用
   Booster，不在 G5B 内重新实现 feature/index/model 校验。
2. verifier 同样 fresh-verify G5A/G4B，重建 label-free inference，并对 fresh model 调用
   `predict_fitted_model` 精确一次以重构期望 prediction；读回产物必须与重构值逐行、
   逐列精确相等。不通过二次 predict 自我对账掩盖单次输出漂移。
3. inference feature index 和 metadata 继续由 G5A `predict_fitted_model` 核对：exact
   `("as_of", "symbol")` 两级唯一递增 MultiIndex、metadata 精确 Date/String 两列，
   行数和逐行 key 同序相等；禁止在 G5B 隐式排序、去重或补行。
4. expected keys 精确等于 fresh formal G4B test 中全部 scorable keys；必须唯一、
   按 `(as_of, symbol)` 稳定递增、全部位于 fold test dates。inference metadata 必须与它
   同序精确相等，score 数量必须精确相等且全 finite。
5. 只调用现有 `normalize_prediction_scores`。分组和领域唯一键均精确包含
   `model`；每组按 `score DESC, symbol ASC` 得连续 `rank=1..N`。产物行序必须是
   normalizer 的稳定行序，不另做第二次排序。
6. `n_predicted == n_scorable > 0`，且 `n_scorable <= n_eligible`。
   `prediction_keys_sha256` 按 `PredictionScoreSchema` 的最终稳定行序计算；
   `predictions_sha256` 是 `predictions.parquet` 物理 bytes hash。

## 6. 发布树、manifest、receipt 与 no-clobber

1. output root 必须是调用方已创建的空实体目录，不接受 symlink/junction/reparse
   或非空目录。不创建、清空、覆盖或修复已有产物。
2. 输出精确只有 `predictions.parquet` 和 `prediction_manifest.json`，采用现有冻结
   Parquet 参数和 exclusive create。任一预测/校验失败时输出目录保持空。
3. manifest 字段精确为现有 `PredictionManifestV1`，必须 canonical，并重算绑定
   model/feature/snapshot/fold/horizon/experiment/work/schema/eligibility/signal dates/counts/keys 和两个
   physical content hash。拒绝重复/未知 JSON key 和 non-finite 值。
4. receipt 由现有 `publish_stage_receipt` 发布，builder 不另写一套 receipt。必须精确：
   `stage=predictions`、`scope=WORK`、`scope_key=spec.work_key`、两个输出无缺失/多余。
5. receipt inputs 复用 development G5B 的递归闭包形状，且不得重复、缺失或多出：
   `model.metadata.json`、model receipt、`feature_manifest.json`、feature receipt、`folds.json`、
   fold receipt、`experiment_manifest.json`、alignment receipt。model receipt 必须已 fresh 绑定
   `model.txt`/curve/metadata；feature receipt 必须已 fresh 绑定 test feature bytes。
6. verifier 必须先 fresh-verify 上游，再精确检查两文件树、manifest、Parquet schema/
   rank/order/keys/bytes hash 与 receipt input/output digest 闭包，最后才返回 exact
   `VerifiedPredictionArtifact(root.resolve(strict=True), ...)`。

## 7. 失败语义与禁止项

- 正式 builder/verifier 公开边界对未预期 IO、Polars、pandas、LightGBM 和 receipt
  内部异常统一翻译为稳定、脱敏的 `ValueError("M3_PREDICTION_ARTIFACT_INVALID")`；
  不输出绝对路径、SQL/原始异常、model bytes 或数据内容。对外异常 `cause/context`
  必须为 `None`。现有 development 公共错误契约不因此改变。
- 禁止 formal builder 只消费调用方传入 capability 而跳过 fresh verification。
- 禁止 development/formal verifier、capability 或 receipt stage 混用；禁止依赖 `isinstance`
  接受 subclass 绕过 exact type gate。
- 禁止读取 test label、只预测有 label 子集、在 G5B 内 fit/重训、使用 Qlib LGBModel、
  直接 import LightGBM、隐式补分、修复 key/rank 或静默丢行。
- 禁止读取/扫描 `data/legacy`，禁止网络请求，禁止写正式 G1/G2 journal、
  候选目录或已有正式 artifact。

## 8. 白名单

实现 Agent 只允许修改：

- `src/quant/research/m3/predictions.py`；
- `src/quant/research/m3/__init__.py` 中新正式入口的必要安全导出；
- 新增 `tests/unit/test_m3_formal_prediction_artifact.py`；
- 本任务的交付报告、独立初验报告与返工文档。

`contracts.py`、`schemas.py`、`model.py`、`alignment.py`、G1–G5A 生产代码、
development tests 和 `ml_topk.py` 默认为只读。若发现权威契约真实缺陷，先停止扩大
实现并提交最小复现，由主 Agent 先修订 SSOT/任务单。

## 9. 必测正例与对抗反例

### 正例

- exact formal G1→G5A 链 build→receipt→verify，输出精确两文件，返回 exact
  `VerifiedPredictionArtifact`；
- 多证券、多 test date、含不可评分 eligible 行；全部 scorable keys 恰好预测一次；
- score tie 按 symbol 升序，rank 从 1 连续；两个 model 同 version 时按 `model` 隔离分组；
- test 末尾 future label 缺失不改变 prediction keys/counts；
- top-level `import quant.research.m3`、策略 import 和 `predictions.py` import 均不加载 LightGBM。

### 必测反例

1. formal/dev release、snapshot、provider、experiment、fold、feature、label、alignment、model 或
   prediction capability 任一互换；subclass 伪装；
2. cross experiment/work/snapshot/fold/horizon/model/version 混配，scientific config 漂移；
3. copied model/feature root bytes 相同但 absolute root 不同；fresh verifier 返回非 exact 传入
   capability；必须在 predict 0 次、输出 0 bytes 前失败；
4. inference key 缺失/多余/重复/乱序/越出 test dates，MultiIndex 层数/名称/顺序漂移，
   metadata 列/类型/顺序/逐行 key 漂移；
5. predict 调用 0 次或 2 次，score 数量少/多，NaN/+Inf/-Inf，仅返回有 label 子集；
6. prediction 重复 key，不连续 rank，tie 次序错，去掉 `model` 的分组/唯一键，或发现
   formal 第二 normalizer；
7. 非空 output、symlink/junction/reparse output、第二次 build no-clobber；预测失败后目录必须仍空；
8. manifest/parquet/receipt 任一 byte 篡改，重复/未知 JSON key，Parquet schema/列序/dtype
   漂移，输出缺失/多余；
9. receipt stage/scope/scope_key 错误，input/output 缺失/多余/重复/指向错误根，或增加
   未知字段；
10. 另一 work 的 manifest+parquet+receipt 整包替换；同 work 内修改 score/rank 并重算
    manifest/receipt，仍必须被 verifier 的 fresh predict 拒绝；
11. 未预期异常消息中含私有路径/sentinel，或对外异常保留 cause/context。

## 10. 验收命令与平台边界

先运行 formal G5B 与直接依赖的定向回归，再按风险决定是否扩大：

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_formal_prediction_artifact.py `
  tests/unit/test_m3_formal_model_artifact.py `
  tests/unit/test_m3_prediction_artifact.py `
  tests/unit/test_m3_topk.py -q
D:\Miniforge3\python.exe -m ruff check `
  src/quant/research/m3/predictions.py src/quant/research/m3/__init__.py `
  tests/unit/test_m3_formal_prediction_artifact.py
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/predictions.py
```

WSL Miniforge base 在同一 `/mnt/f/.../m3-g4-formal` 路径运行对应 pytest/Ruff/mypy。测试
必须无网络、不读 `data/legacy`、不写正式 artifact/journal，并使用唯一临时目录。
至少一个正例必须使用 G5A 已保存模型经公开 `predict_fitted_model` 执行真实 native
LightGBM load/predict；其他对抗反例可用受控 double。

WSL `/mnt/f` 结果只是 WSL base + DrvFS 兼容性证据，不替代 ext4/Linux Gate。若测试需要
真实 Qlib 上游，只在已验收 `py312` 环境增加严格探针，不改 WSL base。Windows 绿测、
development example 绿测和 fake native 均不得表述为正式 G5B/Linux Gate 通过。

## R2：两文件事务式发布与 Parquet exclusive writer（2026-08-09）

### 失败闭环

- 现象：`predictions.parquet` 写成后，让 manifest writer 抛含 marker 的异常；公共错误虽已稳定脱敏，但
  `output_root` 残留单独 Parquet，违反“任一失败输出目录保持空”和精确两文件完成合同。
- 附带缺口：现有 `_write_parquet(frame, path)` 直接把 path 交给 Polars，只靠事前 empty-dir 检查，检查与
  创建之间存在竞争窗口，不具备 `O_EXCL` no-clobber。
- 根因：两次独立写入没有本次调用级 rollback；Parquet writer 未使用项目冻结的 exclusive create 原语。
- 最小复现：monkeypatch `_write_exclusive` 在 manifest 阶段抛
  `RuntimeError("PRIVATE_SENTINEL")`，build 返回 `M3_PREDICTION_ARTIFACT_INVALID`，目录内容为
  `['predictions.parquet']`。

### 冻结返工规则

1. Parquet 必须通过 `os.open(O_WRONLY|O_CREAT|O_EXCL|O_BINARY)` 创建，再把已打开的 binary stream 交给
   Polars writer；成功后 flush/fsync。禁止退回“先 exists/empty 检查再普通覆盖写”。
2. formal 与 development builder 共用一个窄事务式两文件 writer：只追踪本次调用成功 exclusive-create 的
   精确已知文件。任一步失败时，离开 active `except` 后按逆序删除本次创建文件；不得删除调用前存在的文件、
   未知文件或整个 output root。
3. rollback 后必须重新证明 output root 是同一个真实目录且为空；若 rollback 本身失败，抛独立稳定
   `M3_PREDICTION_ROLLBACK_FAILED`，cause/context 为空，并保留现场供人工调查，禁止谎报普通 input invalid。
4. 正常成功仍只有精确两文件，bytes/hash/receipt 不变；StageRunner receipt 仍是最终完成标记，本包不引入
   `os.replace`、目录覆盖或第三套 staging 格式。
5. manifest/parquet writer 的 ValueError 与非 ValueError 均不得穿透 marker；对外异常 cause/context 为空。

### 新增测试与通过条件

- Parquet writer 首步抛 ValueError/RuntimeError：目录为空；
- manifest writer 第二步抛 ValueError/RuntimeError：已写 Parquet 被精确回滚，目录为空；
- 预先存在任一同名文件、并发 writer 抢先 exclusive-create：原文件 bytes 不变，调用方不删除它；
- 模拟 rollback unlink 失败：固定 rollback error、空异常链，不删除未知文件；
- formal 与 development 正例、fresh G5A/G4B、native predict、重签篡改及 receipt 合同保持绿色；
- Windows 与 WSL base `/mnt/f` 定向 pytest/Ruff/mypy 通过，DrvFS 结果不替代 ext4。返工后必须由未参与 R2
  实现的全新 Agent 独立复验 PASS，才可关闭 G5B。

### R2 上游顺序补充：copied model root 必须先于 LightGBM 拒绝

- 现象：把合法 model 三文件复制到另一绝对 root，沿用原 model receipt 调用真实
  `verify_model_artifact`；当前 G5A verifier 会先加载 `Booster(model_file=copied_root)`，之后才在 receipt output
  root 闭包拒绝。G5B 因此已发生一次 LightGBM 调用，违反“stale/copied-root 在任何重依赖 load 前失败”。
- 根因：G5A `_verify_model_artifact` 的 receipt exact input/output/root 校验排在 `_lightgbm()` 与 Booster load 后。
- 应遵循规则：不增加 G5B 私有 receipt 预检或复制一套 G5A closure。最小权威修复是把 G5A 公共 verifier
  已有 receipt bytes/exact closure 检查移到 `_lightgbm()` 前；只有 tree、manifest/content hash、fresh alignment、
  exact receipt/root 全部通过后才允许加载 native model。成功路径与 receipt 字段不变。
- 新增真实反例：不 monkeypatch G5A verifier，使用 copied model root + 原 receipt，并把 `_lightgbm` 设为 hostile
  counter；G5A verifier 与 G5B builder/verifier 均稳定拒绝且 counter=0、G5B builder 输出为空。
- 本补充允许 R2 白名单最小增加 `src/quant/research/m3/model.py` 与
  `tests/unit/test_m3_formal_model_artifact.py`；不得改训练、manifest、receipt schema 或 G4C。

## 11. 交付与独立初验要求

交付报告必须列出改动文件、fresh call 图、predict 调用计数、receipt 闭包、验证命令/
结果和未关闭 Gate。独立初验者保持生产代码和实现测试只读，另外至少增加：

- fresh verifier 返回 bytes 相同但 root 不同 capability 的 copied-root 反例；
- SQLite/receipt/Parquet reader 或 LightGBM predict 带私有 sentinel 的异常脱敏反例；
- 同 work score 篡改后重算 manifest/receipt 的整包反例；
- 实现者未使用的 key/order/model-group 对抗反例。

初验 PASS 后仍由主 Agent 复核 SSOT、formal/development 边界、公开 import、真实 native
LightGBM 证据和平台声明；主验通过前不运行正式全 folds/horizons prediction work，
不进入 G6 正式闭环。
