# M3 G7A R1：正式 TargetArtifact 任务单

日期：2026-08-09  
状态：R3 正式 G1 quality 来源闭包工程主验 PASS；G7B 来源闭包返工已解锁；真实全折与 Linux/ext4 Gate 仍开放

## 1. 目标与边界

在不改变 development example 接口的前提下，把现有 target 工程合同接到正式 G1→G5B 信任链：从完整
test-date eligible domain、fresh formal feature 与 fresh formal prediction 构造无状态 Top-k 目标权重，发布
正式 `VerifiedTargetArtifact`。

本包只关闭 G7A 工程合同，不实现 G7B–G7F 账户回测，不读取持仓，不关闭真实数据性能、M3、M4 或
Linux/ext4 Gate。G7P0 四个 scientific selector 已通过阶段验收，本包不得硬编码另一套策略数值。

## 2. 权威契约与复用

- 字段、计数、权重和日期域以
  `docs/agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md` G7A/receipt 表为权威。
- 复用 `TargetBuildSpec`、`TargetManifestV1`、`TargetUpstreamPaths`、`VerifiedTargetArtifact`；不新增平行
  manifest 或“formal target v2”。
- 复用唯一 Top-k/rank 结果，不在本包重排 prediction；复用 `build_inference_segment` 的 formal G4B loader、
  `verify_prediction_artifact` 的 formal G5B verifier 和现有 canonical row-key/parquet/receipt 公共接口。
- 正式与 development verified 类型、入口和 receipt stage 必须 exact 隔离；不得 cast development capability。

## 3. 冻结公开接口

在 `quant.research.m3.targets` 新增并从包根安全导出：

```python
def build_target_artifact(
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
    spec: TargetBuildSpec,
    upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> TargetManifestV1: ...

def verify_target_artifact(
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
    spec: TargetBuildSpec,
    upstream_paths: TargetUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedTargetArtifact: ...
```

若 G5B 最终验收后的公开签名有名称级微调，以已验收公开接口为准，但不得减少完整 G1→G5B fresh verifier
所需输入。不得用宽 `context: object`、任意 Mapping 或 orchestrator 自报“已 fresh”代替显式依赖。

## 4. Formal freshness 与完整域

builder 和 verifier 在任何写入或读取 target 内容前都必须：

1. exact type 检查全部 formal capability；
2. 以 `prediction.root`、正式 prediction receipt、完整上游 specs/paths/roots 调用公开
   `verify_prediction_artifact`，返回值必须 exact 等于传入 prediction（包含绝对 root）；
3. 通过公开 `build_inference_segment` fresh-verify formal G4B feature 并取得 label-free scorable test keys；
4. 从 fresh folds 取得当前 fold 完整 test dates，从 verified G1 release 的 `eligible_keys.parquet` 取得这些日期的
   complete eligible domain；禁止扫描 data、重建 membership 或读取 label；
5. 从 exact formal inputs 重建 `TargetBuildSpec` 并与调用方 spec 完全相等。

任何 copied-root、whole-bundle 重签、跨 experiment/work/fold/horizon/model 或 formal/dev 混配必须在输出为空
时失败。上游 verifier/loader 每个公开调用在 builder/verifier 内各自精确一次；不得缓存调用方未验真的结果。

## 5. Target 数学与集合合同

- 每个 test signal date 都必须有 eligible batch、scorable batch 与 prediction batch；日期域 exact 等于 fold
  test dates，严格递增，无区间外日期。
- `scorable ⊆ eligible`、`prediction keys = scorable keys`。prediction 少、多、重复、乱序或日期缺 batch 均
  fail closed；空 prediction 不能解释为全清仓。
- 当日 `scorable_coverage = n_scorable / n_eligible`，eligible 为零失败；低于 scientific threshold 失败。
- Top-k 只消费已验真 `rank`；tie 行为沿用唯一 rank normalizer。每个 eligible key 必须输出一行：未选与
  unscorable 为 `target_weight=0.0`，不得只发布持仓候选子集。
- 选中权重用 `Decimal(str(config_value))` 计算
  `min((1-cash_buffer)/n_selected, max_weight)` 后投影 Float64；`n_selected` 是逐日选择数之和。
- R2 算术闭包：上述公式按正有理数语义执行，不得把有限 Decimal context 对非终止除法的向上尾差误判为
  超配。先以 exact `max_weight * n_selected <= 1-cash_buffer` 判断 capped 分支；未 capped 时在模块私有固定
  `Context(prec=50, rounding=ROUND_DOWN)` 中计算单份 weight，并以同一 context 重算 total，必须满足
  `total <= investable`。禁止依赖调用方全局 Decimal context、epsilon/tolerance 或删除超配断言。formal 与
  development 必须复用同一私有 helper；`cash_buffer=.1,max_weight=.2,n_selected=7` 的 build+verify 为必测正例。
- 策略是无状态纯函数，不读取账户、持仓、现金、订单或 G7B+ 产物。

输出精确三文件：`target_weights.parquet`、`target_daily.parquet`、`target_manifest.json`。列、dtype、物理排序、
canonical JSON、固定 Parquet 参数、三个 content hash 和 row-key hash 沿用现有 development 核心与 G7A SSOT。
不得隐式排序来修复非法上游；builder 输出本身按冻结顺序产生，verifier 精确重建逐行 bytes/content。

## 6. Receipt 与不可变发布

- writer 只接受已存在空 temp，三文件全部 exclusive/no-clobber；Parquet/JSON 必须从
  本次调用 exclusive-create 成功打开的文件流写入，不得先检查后按路径覆盖。任一写入、
  flush/fsync 或后续校验失败时，只逆序回滚本次已成功独占创建的文件，不覆盖、不删除
  并发调用者抢先创建或既有/未知文件；成功回滚后不留部分成功集合。回滚本身失败必须返回
  独立稳定码 `M3_TARGET_ROLLBACK_FAILED`，与其他公开错误一样保证 `cause/context is None`。
- 首次空 temp 预检必须保留平台安全的目录实体身份，并在首个输出 exclusive-create 前 fresh
  证明原路径仍指向同一实体。上游 fresh verification/数学计算期间原目录被 rename 并用另一空目录
  替换时，必须在写入 0 bytes 时 fail closed；重做路径 `lstat`/空目录检查不等于目录身份不变。
- receipt 固定 `stage=targets`、`scope=WORK`、`scope_key=spec.work_key`；development 继续
  `development-targets`。
- inputs 必须是 G7A receipt 表的 exact 递归闭包：G1 release/eligible；feature manifest/receipt/coverage/test；
  prediction manifest/receipt/parquet 及其正式递归上游；fold bundle；experiment bundle。不能漏实际读取 bytes，
  也不能加入 label 内容或任意未知文件。
- outputs exact 为三文件；verifier 既检查通用 receipt 自洽，也重建 exact path/content 集合。相同 bytes 不同
  物理 root、路径别名、未知 receipt 字段、错误 stage/scope 均失败。

## 7. 稳定错误与禁止项

所有公开边界输出固定、不含路径/SQL/token/data 内容的错误；来自上游 verifier/loader、Polars/Pandera 或
文件系统的异常必须在专用边界捕获并离开 active `except` 后换译，`__cause__`、`__context__` 均为空。

禁止：读取 test label；把缺 prediction 解释为 0 权重；直接调用私有 `_read_feature_segment` 绕过 formal
loader；重新 fit/predict/rank；读取持仓；扫描 `data/legacy`；联网；修改 G1–G6、正式 artifacts/journal；
用 development fixture 或 Windows 结果宣称正式 Gate。

## 8. 白名单

- `src/quant/research/m3/targets.py`
- `src/quant/research/m3/__init__.py` 的必要安全导出
- 新增 `tests/unit/test_m3_formal_target_artifact.py`
- 本任务单、交付报告、独立复验报告

除发现并先记录权威合同缺陷外，不修改 `contracts.py`、development target 测试或 G1–G6 实现。

## 9. 必测反例与验证

- 300/299/301 eligible/prediction domain，缺/多 key，缺日期，重复/乱序，区间外日期；
- 调出证券不在当前 target domain；当前 eligible 的 unselected/unscorable 必须显式 0；
- 低 coverage、空 eligible、空 prediction、tie、top_k、max-weight/cash-buffer Decimal 边界；
- formal/dev capability 混配，跨 work/fold/horizon/experiment/model，copied-root fresh capability；
- manifest/parquet/receipt/whole-bundle wholesale 替换并重哈希重签；
- monkeypatch label reader 为 hostile 并断言零调用；monkeypatch账户/持仓入口为 hostile 并断言零调用；
- hostile prediction verifier 与 feature loader 分别抛 ValueError/非 ValueError，固定错误、空 cause/context、
  marker 不进 traceback，builder 零输出；
- 三个 writer 分别在写入/flush/fsync 及第二、第三文件阶段抛 ValueError/非 ValueError，必须
  精确回滚为空且异常链不泄露；并发抢占同名 Parquet/JSON 不覆盖也不删除；回滚
  unlink 失败使用独立码且 `cause/context is None`；
- 在 hostile prediction verifier/feature loader 返回前 rename 已预检 output root 并用新空实体目录替换
  原路径，builder 必须拒绝，原目录与替换目录均 0 files；
- development 回归保持绿色，包根 import 不加载 Qlib/LightGBM/MLflow。

Windows 运行 formal G7A 与直接依赖定向 pytest、Ruff、mypy；WSL base `/mnt/f` 对应验证并明确 DrvFS 非
ext4。实现自测后必须由未参与实现的全新 Agent 增加至少两个对抗变体；独立复验 PASS 后才能进入 G7B。

## 10. R3：正式 G1 `quality.json` 来源闭包返工

### 10.1 现象、根因与规则

- 现象：当前 formal `_formal_receipt_inputs`、formal upstream bytes 校验及 formal receipt exact-set 重建仍引用
  `release.release.root / "receipt.json"`；真实且已通过 public `verify_g1_release` 的正式 G1 release exact tree
  不含该文件，因此合法正式输入会被稳定拒绝。
- 根因：G7A R1 把 development stage receipt 语义复制到了并非 StageRunner stage 的正式 G1 release。
- 应遵循规则：正式 G1 的来源证明是 public `verify_g1_release` 加 exact `manifest.json`、`quality.json` 与已选
  artifact；禁止新增、回填或测试中伪造 G1 `receipt.json`。development 路径仍保留其真实 receipt，不得改动。
- 最小复现：对已验真的 `VerifiedG1Release`，断言 `release.release.quality_path` 存在且 sha256 等于
  `release.quality_sha256`，同时 `release.release.root / "receipt.json"` 不存在；当前 formal G7A 仍把后者列为输入。
- 通过条件：formal G7A build -> publish receipt -> verify 全链只使用正式 G1 quality，不再要求或读取伪 receipt；
  原 R1/R2 数学、freshness、不可变发布与 development 行为保持不变。

### 10.2 精确实现合同

1. 仅在 formal 路径中把 G1 第二项从 `release.release.root / "receipt.json"` 替换为 exact
   `release.release.quality_path`，并绑定 `release.quality_sha256`。至少同步：formal 14-input 构造、formal
   upstream stable-bytes 校验、formal receipt expected exact path/digest 集合及 verifier 重建。
2. formal input 数量仍精确为 14；顺序保持 G1 manifest、G1 quality、G1 eligible，随后 feature、prediction、
   folds、experiment。不得把 manifest/quality/eligible 合并、增项或用目录扫描推断。
3. formal 路径必须拒绝：缺失或漂移 quality；same-bytes 路径别名/硬链接；用任意 `receipt.json` 替换 quality；
   同时存在额外伪 G1 receipt 也不能令其成为 receipt input。旧的以伪 G1 receipt 签发的 target receipt 必须拒绝。
4. 测试必须构造或消费与真实 G1 exact tree 一致的 formal fixture：禁止在 G1 root 写 fake receipt，禁止把
   development manifest/root/capability 冒充 formal。若现有测试 helper 依赖 fake receipt，只在本文件白名单内
   最小修正 helper；不得放宽 production exact type/fresh verifier。
5. 不改 `m3_release.py`、G1 registry/final tree、development `_fresh_upstream_bytes`/`_receipt_inputs`、公共 API、
   manifest schema、Top-k/Decimal、publication 或错误码。任何需要这些变化的情况立即停止回报。

### 10.3 白名单与验证

- `src/quant/research/m3/targets.py`
- `tests/unit/test_m3_formal_target_artifact.py`
- 本任务单状态
- 唯一 R3 交付报告 `docs/agent/M3_G7A_R3_正式G1Quality来源闭包返工交付报告.md`
- 唯一 R3 独立复验报告 `docs/agent/M3_G7A_R3_正式G1Quality来源闭包独立复验报告.md`

实现至少验证 Windows 与 WSL base 的 formal G7A 定向节点、development target 邻接、Ruff、mypy、cold import、
scoped diff-check；WSL `/mnt/f` 只算 DrvFS 兼容。独立初验必须使用未参与实现的全新外部 Agent，并额外攻击
quality same-bytes alias、旧伪 receipt 合法重签、quality 内容漂移与 hostile 异常脱敏。R3 初验及主验 PASS 前，
不得继续 G7B/G7F/G8 来源闭包修复或恢复 G8C。
