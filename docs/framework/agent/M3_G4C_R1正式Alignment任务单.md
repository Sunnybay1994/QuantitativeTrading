# M3-G4C-R1：正式 Alignment 与 label-free inference 任务单

日期：2026-08-02  
状态：设计冻结；G4B R1 Windows 独立复验通过后解冻实现

## 目标与信任边界

在既有 `m3-alignment-artifact-v1`、matrix digest、strict receipt 与 development example 实现上补齐正式入口。
正式入口只接受 `VerifiedG1Release`、`VerifiedSnapshotArtifact`、`VerifiedProviderArtifact`、
`VerifiedExperimentIdentity`、`VerifiedFoldPlanArtifact`、`VerifiedFeatureArtifact`、
`VerifiedLabelArtifact` 和对应 strict spec/path/config；返回 `VerifiedAlignmentArtifact`。任何
development nominal 在写入前拒绝，正式产物不得写 development stage 或携带 example 身份。

监督 artifact 只生成 train/validation；test 只通过独立 inference loader 消费已 fresh 验真的 feature artifact，
公开签名、调用图、文件读取均不得出现 label、label receipt、horizon 或 future-exit 依赖。

## 固定接口

```python
def build_alignment_artifact(
    *, feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: AlignmentBuildSpec, output_root: Path,
) -> AlignmentManifestV1: ...

def verify_alignment_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity, experiment_spec: ExperimentIdentitySpec,
    folds: VerifiedFoldPlanArtifact, fold_spec: FoldPlanBuildSpec,
    feature: VerifiedFeatureArtifact, feature_spec: FeatureBuildSpec,
    label: VerifiedLabelArtifact, label_spec: LabelBuildSpec,
    config: LoadedM3Config, spec: AlignmentBuildSpec,
    upstream_paths: AlignmentUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedAlignmentArtifact: ...

def load_supervised_segment(
    *, alignment: VerifiedAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment: ...

def build_inference_segment(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, folds: VerifiedFoldPlanArtifact,
    fold_spec: FoldPlanBuildSpec, feature: VerifiedFeatureArtifact,
    feature_spec: FeatureBuildSpec, config: LoadedM3Config, fold_name: str,
    upstream_paths: InferenceUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> InferenceSegment: ...
```

## 内容与 receipt 闭包

- artifact 文件精确为 `train.parquet`、`validation.parquet`、`diagnostics.parquet`、
  `alignment_manifest.json`；保持现有 schema/digest 公式，不复制一套 formal 格式。
- builder 对 feature scorable key 与同 horizon label 做 1:1 join；label 必须在 fold cutoff 前可知；缺 label 和
  cutoff 后 label 只进入 diagnostics。最终 label 必须 finite，train/validation 均非空。
- verifier fresh 重验 feature 与 label 的完整公开闭包，再逐 segment 从 verified 上游重建行键、feature matrix、
  label series、计数和 diagnostics。
- 正式 receipt 固定 `stage="alignment"`、`scope="WORK"`、`scope_key=work_key`；direct inputs/outputs 与
  development 格式同形但绑定正式 roots/receipts。未知、缺失、decoy 或路径逃逸均失败。
- supervised loader 至少重验 manifest 与物理 segment digest；inference loader fresh 重验 feature/fold 全链，
  只读取 test feature parquet。

## 禁止项

- 不 import Qlib、LightGBM、MLflow；不修改 G1/G2 正式 artifact/journal。
- 不让 test row 受 label 是否存在、future exit 是否可知或 horizon 过滤影响。
- 不接受裸 DataFrame、自报 hash、development verified 类型或仅凭 frozen dataclass 跳过 fresh verify。
- 不修改 matrix digest、label、fold、feature 的既有公式；发现矛盾先停并报告。

## 白名单

- `src/quant/research/m3/alignment.py`
- `src/quant/research/m3/__init__.py`
- `tests/unit/test_m3_alignment.py`
- 本任务单、交付报告、独立初验报告

## 必测反例与通过条件

1. formal 公开链 build→receipt→fresh verify→supervised loader 成功；development/formal 混配零写入失败。
2. monkeypatch label verifier/read/parquet 为抛错后，formal test inference 仍成功且保留无 future label 的 scorable key。
3. feature/label/fold/experiment/spec/receipt 任一混配、bytes 漂移、decoy input、非 canonical manifest 均失败。
4. duplicate key、late label、missing label、NaN/inf label、空 segment、row order/matrix/signed-zero 漂移 fail closed。
5. 包根安全导出 formal 与 development 平行 API，import isolation 不出现 qlib/lightgbm/mlflow。

Windows 定向 Ruff/mypy/pytest 后，再补 WSL base 同组验证。Windows 工程通过不关闭正式 G4/M3 Gate；正式
LightGBM、evaluation、冷启动复现和当前 source identity 下的 G1/G2 重发仍属于后续 Gate。
