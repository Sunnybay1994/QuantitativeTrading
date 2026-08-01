# M3 G4C development example 监督对齐阶段验收

日期：2026-08-02
信任域：`development_example`（`formal_gate_eligible=false`）

## 结论

G4C 的 development example 工程合同已实现。该结论只证明隔离示例发布物可完成监督对齐与无标签
inference，不代表 production G4C、真实数据性能或 Linux Gate 关闭。

## 冻结边界

- `alignment.py` 不 import Qlib、LightGBM 或 MLflow；
- 每个 `work_key = SHA256([experiment_key, fold, horizon])` 只发布 train/validation 对齐产物；
- train/validation 对当前 horizon 标签做一对一 join，并分别应用 FoldPlan 的 label-available cutoff；
- test 不发布 alignment，也不接受 label、horizon 或 cutoff 参数；inference 只消费 fresh-verified fold-shared
  FeatureArtifact 的 test scorable rows；
- 部分 NaN 的 feature row 合法保留，只有 selected projection 全 NaN 才属于 unscorable；不填充 feature 或 label；
- manifest 同时绑定 feature/label/fold/experiment identity、Parquet bytes、冻结 row order、Float64 matrix/label
  逻辑摘要和 diagnostics；StageReceipt 使用 `WORK` scope 并要求精确输入/输出闭包；
- development verified type 保留 `development_example` 身份，不能构造或冒充 `VerifiedAlignmentArtifact`。

## 实现与测试

- 新增 alignment spec/upstream path、manifest/verified/load result 值对象；
- 新增 deterministic builder、strict reader、fresh verifier、supervised loader 和 label-free inference loader；
- 对抗测试覆盖 work/horizon/fold/schema 混配、no-clobber、输出 bytes 与 receipt 漂移、缺标签诊断、cutoff、
  X/y 顺序、formal/development 混用、路径脱敏，以及“test 可评分但尚无未来 exit”仍保留的反例。

## 验证证据

Windows 原生 Miniforge：

```text
set PYTHONPATH=src&& D:\Miniforge3\python.exe -m pytest -p no:cacheprovider \
  --basetemp=artifacts\testtmp\g4c_final_8300 tests\unit\test_m3_alignment.py -q
15 passed in 239.62s

D:\Miniforge3\python.exe -m ruff check <G4C source and test files>
All checks passed!

D:\Miniforge3\python.exe -m mypy <G4C source files>
Success: no issues found in 4 source files
```

WSL Miniforge `base`（直接消费同一隔离 worktree）：

```text
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output env \
  PYTHONPATH=/mnt/f/.../m3-g8ab-prereq/src python -m pytest -p no:cacheprovider \
  --basetemp=/tmp/quant-g4c-8303 /mnt/f/.../tests/unit/test_m3_alignment.py -q
15 passed in 133.81s
```

两平台均产生 Pandera/Polars `horizontal` 默认行为弃用告警，不影响本轮断言。WSL 结果证明同一 development
合同在 Linux 运行时通过，不替代正式发布的 ext4/Gate 验收。

## 尚未关闭

- production G4B 真实 Qlib 0.9.7 FeatureArtifact；
- production G4C 对正式 G2/G3/G4B verified artifacts 的发布；
- Linux 平台 Gate、真实数据训练/性能结论；
- G5A 及后续模型、预测、评价、回测与发布 Gate。
