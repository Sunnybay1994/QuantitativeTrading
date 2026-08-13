# M3 G8B 开发示例静态阶段 Runner 主 Agent 阶段验收报告

日期：2026-08-02（Asia/Shanghai）

结论：**G8B 通用静态目录发布与可恢复 runner 的开发契约通过。**
边界：本结论不是正式 G8/G9 Gate，也不得代替正式 G1 发布、真实 Qlib 运行或 Linux/ext4 Gate。

## 实现

- `StageRunner.run_static` 只消费已解析的 `StageNode` / `RunPlan`，不扫描目录猜输入。
- `ExternalInput` 按 `ArtifactDigest` 重验；`StageOutputInput` 必须由依赖阶段的可重验 receipt 精确闭包。
- handler 只写 runner 所有的临时目录；独立 closure verifier 通过后，以整目录 no-clobber commit 提交。
- receipt 位于最终输出目录之外，并绑定 scope/key、全部输入与输出内容摘要。
- 已覆盖首次发布、幂等 resume、`--no-resume`、“最终目录已完整但 receipt 缺失”恢复、部分目录、字节冲突、依赖 receipt 缺失和 TREE 闭包。
- 主验补充反例：receipt 路径作为 final 目录祖先时必须在 handler 前拒绝，避免文件/目录路径冲突。

## 验证

实现阶段已完成：

- Windows Miniforge：Ruff 通过，mypy 通过，pytest `19 passed`；
- WSL Miniforge `base`：mypy 通过，pytest `19 passed`；
- `git diff --check` 无 whitespace error。

主 Agent 补充反例后的最终定向结果：

- Windows Miniforge：pytest `20 passed`，Ruff、mypy 与公共导入探针通过；
- WSL Miniforge `base`：与已合流 M2 定向回归合并执行 pytest `142 passed`，
  G8B/M2 Ruff 与 mypy 通过；
- Windows 与 WSL 均只证明开发契约；WSL 当前仍是 WSL1/wslfs，不构成 Linux/ext4 Gate。

## 剩余边界

- G8A 的 PROVIDER / EXPERIMENT 多波 plan 生成器仍需继续闭包；
- 本 runner 不会将 development/example 输出构造为正式 verified Gate 证据；
- MLflow target 跟踪与 G9 总验收仍属后续包。
