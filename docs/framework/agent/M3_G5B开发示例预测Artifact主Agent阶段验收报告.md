# M3 G5B development example 预测 Artifact 阶段验收

日期：2026-08-02
信任域：`development_example`（`formal_gate_eligible=false`）

## 结论

G5B 的 development example 工程合同已实现。该结论只证明隔离示例链能够从 fresh-verified G5A model
和完整 test feature 生成、验真并由策略消费 prediction artifact；不代表 production G5、真实数据性能或
Linux/ext4 Gate 关闭。

## 冻结边界

- `normalize_prediction_scores` 的唯一实现位于 `predictions.py`，策略模块只 import；
- PredictionScore Schema 的唯一键与 rank 分组均精确包含 `model`；score 必须 finite；每个
  `(as_of, model, model_version, dataset_snapshot_id, fold, horizon_sessions)` 横截面按 score 降序、
  symbol 升序生成连续 rank；
- builder 只接收 verified model/feature/folds/experiment capability 和严格 spec，不接收 label；完整 test
  inference 的 key 集必须与 feature manifest 的 scorable test 闭包完全相等，少、多、重复或区间外 key
  均在发布前失败；
- 输出精确为 `predictions.parquet` 与 `prediction_manifest.json`；manifest 绑定 model/feature/fold/
  experiment lineage、eligibility、signal dates、三层计数、逻辑 key hash 和 Parquet bytes hash；
- verifier fresh-verify G5A 及其全上游，并重新加载无 label inference，精确核对 receipt 输入/输出闭包；
- development verified type 固定 `development_example`、`formal_gate_eligible=false`，不能冒充
  `VerifiedPredictionArtifact`。

## 实现与对抗测试

- 新增 prediction spec/upstream paths/manifest/formal 与 development verified 值对象；
- 新增 deterministic builder、strict reader、fresh verifier、逻辑 key hash 和唯一 rank normalizer；
- 更新领域 PredictionScore Schema 和无状态 Top-k 导入边界；
- 对抗覆盖 tie、同 version 不同 model、NaN/Inf、predict 数量漂移、inference key 少/多/重复/越界、
  label-free 全量 test、lineage 混配、no-clobber、manifest/parquet/receipt 篡改、whole-bundle 替换，及
  package/strategy import 不加载 LightGBM。

## 验证证据与边界

Windows 原生 Miniforge：

```text
PYTHONPATH=<worktree>/src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_prediction_artifact.py -q
17 passed in 334.29s

D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_topk.py -q
10 passed in 3.01s
```

WSL Miniforge `base` 对同一 worktree：

```text
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output env \
  PYTHONPATH=/mnt/f/.../m3-g8ab-prereq/src python -m pytest \
  test_m3_prediction_artifact.py test_m3_topk.py test_m3_contracts.py test_m3_evaluate.py -q
44 passed in 163.40s
```

定向 Ruff 和 mypy 通过。两平台均产生 Pandera/Polars `horizontal` 默认行为弃用告警，不影响断言。
双平台 development fixture 绿测只证明接口/契约兼容，不代替正式输入、完整 folds/horizons、真实模型效果
或 Linux ext4 Gate。

## 尚未关闭

- production G4B/G4C/G5A/G5B 对正式 G2/G3 verified artifacts 的全链发布；
- G6 evaluation、G7 统一回测、G8 冷启动复现/MLflow 与 G9 Gate；
- 正式参数、正式数据的覆盖与性能结论，以及 Linux ext4 Gate。
