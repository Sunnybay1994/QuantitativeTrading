# M3 G6B development example 跨折研究汇总 Artifact 阶段验收

日期：2026-08-02

## 结论

G6B development example 工程合同已实现并通过 Windows 与 WSL base 定向验证。它证明隔离示例链可将
同 experiment、model、version、horizon 的多个 verified G6A evaluation 合并为确定性 summary；不代表
production G6、真实研究绩效或 Linux/ext4 Gate 已关闭。

## 实现边界

- summary 是 `EXPERIMENT` 作用域，输入至少两个 fold，按 fold 名排序且 test dates 不得重叠；
- 输出严格为 `daily_ic.parquet`、`fold_metrics.parquet`、`metrics.json`、`manifest.json`；
- `daily_ic` 直接拼接各折逐日记录；coverage 由总 count 重算，IC/ICIR 由全部可计算日重算，不平均 fold
  ICIR、不选最佳折、不调参；
- `fold_metrics.parquet` 是各折 `EvaluationMetricsV1` 的固定 24 列有序投影，计数均为 Int64；
- manifest 固定记录 folds、evaluation manifest/receipt hashes、test dates、scientific config 与四个输出哈希；
- summary receipt 固定为 `development-research-summary` / `EXPERIMENT`，输入闭包是 experiment
  manifest+receipt，以及按 fold 排序的每个 evaluation daily/metrics/manifest/receipt；
- verifier 重新读取并核对每个上游 capability 的 bytes，再重算 summary tables、metrics、manifest 和 receipt
  精确闭包；development capability 固定 `formal_gate_eligible=false`。

## 对抗验证

覆盖两折日期互斥、逆序输入/稳定 fold 顺序、总 count 与跨日 IC/ICIR 重算、精确 schema/dtype、日期重叠、
horizon/model/experiment 混用、no-clobber、四输出及 receipt 篡改、receipt 多余输入、跨 experiment 整包替换，
以及核心 import 不加载 Qlib、LightGBM、MLflow。

```text
Windows Miniforge: 8 passed in 4.34s
WSL base:          8 passed in 2.95s
Ruff:              All checks passed
mypy:              Success: no issues found
```

## 尚未关闭

- production G4–G6 对正式 G2/G3 artifacts 的全链发布；
- G7 组合/统一回测、G8 追踪恢复、G9 正式 Gate；
- 真实数据覆盖、模型效果、性能结论与 Linux/ext4 Gate。
