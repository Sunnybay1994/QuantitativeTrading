# M3 G5A R1：正式 LightGBM Model Artifact 任务单

> 2026-08-09 状态补充：R3 的 fresh/model/predict 主合同保留；主 Agent 在 G5B output-root
> TOCTOU 复验后确认 G5A 三文件不可变发布同样缺少 root lease 与事务回滚。该子合同
> 重新打开为 `M3_G5A_R4-G5B_R3_输出根租约与事务发布返工任务单.md`；通过前 G5A 不再作为
> G6A 的已验收发布前置。
>
> 2026-08-09：R4 实现与双平台定向自测已交付，证据见
> `M3_G5A_R4-G5B_R3_输出根租约与事务发布返工交付报告.md`；状态仍为等待独立复验与主验，
> 尚未恢复 G6A 前置。

日期：2026-08-02  
状态：R2 合同修订已实现；等待独立初验与主验

## 目标与信任边界

在现有 `model.py` 的 development-example 合同上复用同一训练、wire、manifest、receipt 与验真核心，
新增正式 `VerifiedAlignmentArtifact → VerifiedModelArtifact` 路径。正式入口只接受 exact formal verified
capability，不接受 development/example 类型、普通 dataclass、路径自报或仅形状正确的 hash。

本包生成正式 model artifact，但不关闭完整 folds/horizons 训练、真实性能、G5B–G9、Linux/ext4 或 M3 Gate。

## 权威接口

沿用 `contracts.py` 已冻结的 `LightgbmTrainingSpec`、`ModelUpstreamPaths`、`ModelManifestV1`、
`VerifiedModelArtifact`，不另建格式。

```python
def build_model_artifact(
    *, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec,
    alignment: VerifiedAlignmentArtifact,
    alignment_spec: AlignmentBuildSpec,
    feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact,
    label_spec: LabelBuildSpec,
    folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec,
    config: LoadedM3Config,
    spec: LightgbmTrainingSpec,
    upstream_paths: ModelUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> ModelManifestV1: ...

def verify_model_artifact(
    *, root: Path,
    receipt_path: Path,
    release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    folds: VerifiedFoldPlanArtifact,
    feature: VerifiedFeatureArtifact,
    label: VerifiedLabelArtifact,
    alignment: VerifiedAlignmentArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    spec: LightgbmTrainingSpec,
    upstream_paths: ModelUpstreamPaths,
) -> VerifiedModelArtifact: ...

def predict_fitted_model(
    *, model: VerifiedModelArtifact, inference: InferenceSegment,
) -> tuple[float, ...]: ...
```

若当前 SSOT 的 verifier 参数通过 `artifact_roots: Mapping[str, Path]` 表达同一精确上游路径集合，保留
SSOT 签名；不得同时公开两套等价 API。

## 冻结实现合同

1. 只有 `model.py` 延迟 import `lightgbm`；包根与其他层 import 不加载 LightGBM。
2. builder/verify 首先 fresh-verify formal alignment；alignment verifier 必须继续 fresh-verify feature、label
   和完整正式上游。不得把 development verifier 或其类型 cast 成 formal。
3. train/validation 只通过 G4C supervised loader；fit 签名没有 test。X 允许 NaN、拒绝 infinity；y finite；
   Float64、列名/列序/schema、唯一有序 MultiIndex、X/y 行键和 train/validation 不相交必须严格核对。
4. training spec 只来自已验真 scientific config。booster params 精确包含 regression/l2、CPU、deterministic、
   force_col_wise、四 seed、num_threads；controls 不混入 params。valid_sets 只有 validation，early stop 只看
   validation l2；禁止 test、RankIC、合并重训和 Qlib LGBModel。
5. 输出精确 `model.txt`、`model.metadata.json`、`validation_curve.parquet`，exclusive/no-clobber。
   manifest 绑定正式 experiment/work/snapshot/provider/fold/horizon、G4B/G3B/G4C manifest、矩阵/标签/row-key
   摘要、参数、运行时版本、best iteration/score 与两个内容 hash。
6. receipt 精确 `stage=model`、`scope=WORK`，inputs/outputs 无未知字段，绑定 manifest/model/curve 与全部上游
   identity；verifier 重读所有 bytes 并核对 exact 闭包。
7. prediction 只按保存的 best iteration 评分，核对 inference feature schema/name/order/hash，score finite；
   不做 rank、不接 label、不读取 test label。
8. 所有稳定边界异常脱敏且 cause/context 为空；manifest、receipt、模型或 curve 任一篡改 fail closed。

## R2 合同裁定与失败闭环（2026-08-08）

- 现象：R1 builder 仅消费调用方传入的 formal capability，fresh verification 只发生在 verifier；调用者可在
  stale alignment 上先训练并写出文件，违背“正式构建入口自身建立完整 G1→G4C 新鲜信任链”。预测入口也只
  验 feature 列，不验证 `(as_of, symbol)` 行键与 metadata 闭包。
- 根因：把 freshness 推给调用方，并把 `InferenceSegment` 的形状约束误当成模型评分所需的身份约束。
- 应遵循规则：formal builder 接收与 verifier 相同的完整上游依赖（另加 `output_root`，不含 model root/receipt），
  在任何输出写入或 LightGBM 训练前调用正式 `verify_alignment_artifact`，返回 capability 必须 exact 等于传入
  alignment（包含绝对 root）。development builder 保持原接口。预测必须拒绝非 exact 两级、命名非
  `("as_of", "symbol")`、重复、乱序的 MultiIndex；metadata 必须精确两列、Date/String schema、等长且逐行
  键与 index 同序相等，禁止隐式排序。
- 最小复现：复制 alignment bytes 到另一绝对目录，让 fresh verifier 返回复制根；R1 builder 仍会训练。或给
  正确 feature 列但 RangeIndex / 反序 metadata，R1 prediction 仍会评分。
- 新增测试：builder 的 copied-root stale 返回必须发生在空输出与零新增 train call 前；正向 fresh call 次数与
  完整参数闭包；prediction 覆盖 RangeIndex、name 漂移、重复/乱序 index、metadata 列序/未知列/反序/键漂移。
- 通过条件：上述反例 fail closed，formal 正例仍 build/verify/predict；Windows 定向 pytest/Ruff/mypy 与 WSL
  base `/mnt/f` 对应定向验证通过。DrvFS 结果不表述为 Linux/ext4 Gate。

## R3 异常脱敏失败闭环（2026-08-08）

- 现象：R2 的 formal alignment fresh verifier 抛含敏感 marker 的 `ValueError` 时原文穿透；抛其他异常时
  表面错误码稳定，但原异常仍保留在 `__context__`。
- 根因：通用 `_model_boundary` 把任意 `ValueError` 当作可信本模块错误，且在 active `except` 中换译异常。
- 应遵循规则：formal alignment fresh verification 是独立的不可信边界；捕获任意普通异常后必须离开
  `except` 再抛 `M3_MODEL_ALIGNMENT_VERIFY_FAILED`，并保证 `__cause__`、`__context__` 均为空。
- 最小复现：分别令 `verify_alignment_artifact` 抛 `ValueError("C:/TOKEN")` 与
  `RuntimeError("C:/TOKEN")`，覆盖 formal builder 和 verifier。
- 新增测试：四种组合均断言固定错误码、marker 不出现、空 cause/context；builder 还必须保持空输出和零新增
  train call。
- 通过条件：新增四组对抗回归与既有 formal/development G5A 套件、Ruff、mypy 在 Windows 通过，并完成
  WSL base `/mnt/f` 对应定向复核；后者仍不替代 ext4 Gate。

## 白名单

- `src/quant/research/m3/model.py`
- `src/quant/research/m3/__init__.py` 的必要安全导出
- `tests/unit/test_m3_formal_model_artifact.py`
- 本任务单、交付报告、独立初验报告

除发现并先记录真实合同缺陷外，不修改 `contracts.py`、G1–G4 实现或 development fixture。

## 必测反例

- formal/dev capability 任一互换、跨 work/fold/horizon/experiment 混配；
- test 进入 fit、validation 混入 train、valid_sets 含 train/test、伪 RankIC early stop；
- 缺 seed、GPU、bool 冒充 int、NaN/Inf param、control 混入 booster params；
- X 列序/dtype/key 漂移、X inf、y NaN、train-validation key 重叠，普通 X NaN 合法；
- curve 非连续、best 与 curve 不一致、model/manifest/curve/receipt/whole-bundle 任一替换；
- top-level import 不加载 LightGBM；predict 列漂移/非 finite score；
- 伪造 fresh verifier 返回对象、绝对路径不同但 bytes 相同、receipt 未知字段均不得绕过。

## 验证与完成边界

Windows 定向 pytest/Ruff/mypy，另做一次真实 native LightGBM 冷启动 train/save/load/predict。WSL base
对应定向验证；若正式 Qlib 上游必须在 `py312` 读取，则增加 py312 严格链验证。Windows 绿测不替代
Linux/ext4 Gate。独立初验通过后才能运行正式完整 work 训练并进入 G5B。
