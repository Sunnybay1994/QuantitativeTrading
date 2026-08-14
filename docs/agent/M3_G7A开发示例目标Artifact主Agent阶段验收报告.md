# M3 G7A development example 目标 Artifact 阶段验收

日期：2026-08-02

## 结论

G7A development example 工程合同已实现，并通过 Windows 与 WSL Miniforge base 定向验证。它证明隔离示例链可以从 verified prediction 生成完整的目标权重域、日级诊断、严格 manifest 与 receipt；不代表正式 G7A、真实回测结果或 Linux/ext4 Gate 已关闭。

## 实现边界

- `TargetBuildSpec` 只从 verified release/feature/prediction/fold/experiment 与已验证配置投影，不接受调用者自报的上游 hash。
- 每个 test signal date 的输出域精确等于 G1 eligible domain；不可评分、未入选证券显式输出零权重。
- prediction key 必须与 feature scorable key 精确相等；eligible、scorable、prediction 任一重复、缺失、多余或越界均 fail closed。
- 等权分配使用 `Decimal(str(value))` 计算 `min((1-cash_buffer)/n_selected, max_weight)`，写出前才转换为 schema 的 Float64。
- 输出树严格只有 `target_weights.parquet`、`target_daily.parquet`、`target_manifest.json`；receipt 固定为 `development-targets` / `WORK`，精确绑定 13 个输入和 3 个输出。
- verifier 重读并重算上游 bytes、完整目标域、日级诊断、manifest 与 receipt 闭包；development capability 固定 `formal_gate_eligible=false`。
- development fixture 刻意保留一个不可评分 eligible 边界，因此派生配置把 `minimum_scorable_coverage` 固定为 0.5；该值进入 scientific identity，正式示例 TOML 仍为 0.98。
- `MlTopkStrategy` 保持既有兼容行为：所有输入证券均显式输出，`eligible=false`、不可评分和未入选证券为零权重；选择只发生在可评分且 eligible 的行上。

## 对抗验证

覆盖 299/300/301 证券边界、不可评分 eligible 行、完整 domain 与日级计数、Decimal 权重、配置投影、prediction key 缺失/多余/重复/越界、低覆盖、空预测、跨 identity 混用、no-clobber、13/3 receipt 闭包、逐输出及 receipt 篡改、跨 work 整包替换，以及核心 import 不加载 LightGBM。

```text
Windows G7A pytest:       15 passed in 264.17s
Windows Top-k regression: 11 passed in 3.24s
WSL base G7A + Top-k:     25 passed in 143.63s
Windows Ruff:             All checks passed
Windows mypy:             Success: no issues found in 4 source files
WSL base Ruff:            All checks passed
WSL base mypy:            Success: no issues found in 4 source files
```

## 尚未关闭

- 正式 G7A 对正式 G1/G2-G6 artifacts 的发布与真实数据折级验收；
- G7B-G7F 统一 A 股回测、G8 continuation、G9 正式 Gate；
- Linux/ext4 发布 Gate、真实数据性能和策略有效性结论。
