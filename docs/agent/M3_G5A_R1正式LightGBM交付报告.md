# M3 G5A R1 正式 LightGBM 交付报告

日期：2026-08-02  
状态：Windows 正式工程合同与 native LightGBM smoke 通过；WSL/Linux Gate、正式全 work 训练和 M3 Gate 未关闭。

## 交付内容

- 新增正式公共入口 `build_model_artifact`、`verify_model_artifact`、`predict_fitted_model`，包根安全导出；
  `model.py` 继续通过 `_lightgbm()` 延迟加载唯一重依赖，包根 import 不加载 LightGBM。
- formal/development 共享同一训练、LightGBM wire、manifest、curve、receipt、模型加载与预测核心；只在 exact
  capability、G4C verifier/loader、receipt stage 和返回 capability 处分流。
- formal builder 只接收 exact `VerifiedAlignmentArtifact`、`VerifiedFeatureArtifact`、`VerifiedLabelArtifact`、
  `VerifiedExperimentIdentity`；在输出目录检查和训练前拒绝 development 类型，通过正式 supervised loader
  只读取 train/validation。fit 公共签名不含 test。
- formal verifier 保留完整 G1→G4C 参数，先调用 `verify_alignment_artifact` fresh 重验 alignment 及其
  feature/label/完整上游，再逐项核对 capability、模型三文件、manifest identity/hash、连续 finite validation
  curve、best iteration/l2、LightGBM runtime version 及 exact receipt closure。
- formal receipt 固定 `stage="model"`、`scope="WORK"`、`scope_key=work_key`；development stage 保持
  `development-model`。输出树精确为 `model.txt`、`model.metadata.json`、`validation_curve.parquet`，沿用
  exclusive/no-clobber 与冻结 Parquet 写参数。
- formal prediction 只加载保存模型并使用 manifest 的 `best_iteration`；核对有序 feature names、全 Float64
  schema hash、禁止 X infinity 和非 finite score，不接受 label，也不做 rank。

## 验证与反例

正式专用测试覆盖：

- formal build → `model` receipt → fresh G4C verify → exact `VerifiedModelArtifact` → predict 公共链；
- fake native 证明 `valid_sets` 只有 validation、metric 为 l2、controls 不进入 booster params、保存与预测均使用
  best iteration；既有共享测试覆盖普通 X NaN 合法、X inf/y NaN、列序/dtype/key、train-validation 重叠、
  seed/GPU/control/best-score 漂移；
- formal/dev capability 在 build 与 verify 边界互换均失败，builder 零写入；
- fresh verifier 返回另一个绝对目录下、bytes 相同的伪 alignment capability 仍以 stale 拒绝；
- model/metadata/curve 任一 bytes 篡改、development stage receipt、receipt 未知字段均 fail closed；
- prediction Float32 schema 与非 finite score 拒绝；包根导出与 delayed import 通过。

formal G5A 单测使用 exact formal capability 和受控 `verify_alignment_artifact` double 来隔离验证 G5A 调用图；
生产 verifier 不存在 frozen dataclass 直通分支。正式 G4B 全公共链和 G4C fresh 闭包已分别由其已通过的专用
测试与独立初验证明，本任务没有复制或修改 G1–G4 fixture/实现。

## Windows 验证

解释器：`D:\Miniforge3\python.exe`；`PYTHONPATH=src`；pytest 使用唯一 basetemp。

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_model_artifact.py tests/unit/test_m3_formal_model_artifact.py -q -p no:cacheprovider --basetemp=artifacts/test-tmp/g5a-final
# 18 passed, 17191 warnings in 232.66s

D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/model.py src/quant/research/m3/__init__.py tests/unit/test_m3_formal_model_artifact.py
# All checks passed!

D:\Miniforge3\python.exe -m mypy src/quant/research/m3/model.py src/quant/research/m3/__init__.py tests/unit/test_m3_formal_model_artifact.py
# Success: no issues found in 3 source files
```

真实 native 冷启动证据：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_formal_model_artifact.py -k native_lightgbm -q -s -p no:cacheprovider --basetemp=artifacts/test-tmp/g5a-native-evidence
# G5A_NATIVE_LIGHTGBM_PASS 4.6.0 3 4
# 1 passed, 3 deselected in 5.79s
```

该 smoke 使用真实 LightGBM 4.6.0 完成 native train → save → load → best-iteration predict，并确认四个 score
均 finite。pytest warnings 均为现有 Pandera/Polars horizontal concat 弃用告警。

## 平台与 Gate 边界

依任务要求，已知 WSL 服务/权限阻塞本轮不重复触发。因此没有新的 WSL base 或 py312 结果，Windows 结果不
替代 Linux/ext4 Gate。本轮也未运行正式完整 folds/horizons work、真实数据性能、G5B–G9 或当前最终 source
identity 下的正式 G1/G2 重发布，不能据此关闭正式 G5/M3 Gate。

## 文件边界

本轮只修改或新增：

- `src/quant/research/m3/model.py`
- `src/quant/research/m3/__init__.py` 的必要导出
- `tests/unit/test_m3_formal_model_artifact.py`
- 本报告

未修改 `contracts.py`、G1–G4 实现、development fixture、正式 artifact/journal；未执行 git add/commit。
