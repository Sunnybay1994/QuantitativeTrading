# M3 G8F R1 fake full-DAG 主 Agent 串行交付报告

日期：2026-08-13
状态：Windows 工程集成测试完成；不代表真实数据、Linux/ext4 或 M3 Gate

## 1. 交付结论

本包不新增平行生产 runner。新增 strict fake integration，直接使用现有 `STAGE_SPEC_REGISTRY`、`StageNode`、
`RunPlan`、`StageRunner` 和正式 receipt/no-clobber 实现执行 48 节点 DAG：provider、validation、experiment、
两个 label/reconciliation、folds、两个 feature、四个 work 的 alignment→train→prediction→evaluation→target→
backtest plan→backtest→tracking→reproducibility，以及两个 summary。

测试证明：

1. shared 节点各执行一次，2 folds×2 horizons 形成四个独立 work 和四个 backtest plan；
2. `fold-001/h5` prediction 首次失败时，另外三个 work、tracking 和 reproducibility 正常完成；
3. resume 时 shared 与已完成 work 只做 receipt/closure 恢复，不再调用 handler，只补失败 work 的缺失链；
4. 已完成 backtest-plan artifact 被篡改后 fail-closed，handler 不会覆盖重建；
5. tracking、cost/model、label tolerance、acceptance tolerance 的实际 config identity 分层保持；
6. provider 抽样 3×20×5 是当前 config SSOT 的 literal，尝试修改直接配置拒绝，不按旧骨架错误地宣称生成
   新 provider-validation identity；
7. `quant.domain`、`quant.strategies`、`quant.backtest` fresh import 不加载 Qlib/LightGBM/MLflow。

## 2. 修改范围

- `tests/integration/test_m3_orchestration.py`
- 本报告

## 3. 常规开发验证

Windows 原生 Miniforge，显式 `PYTHONPATH=<worktree>/src`：

- `tests/integration/test_m3_orchestration.py`：`4 passed`
- Ruff：PASS
- scoped `git diff --check`：PASS

## 4. 剩余边界

- G8F 是严格 fake 全 DAG 工程集成，不替代真实 G1/public CLI 长运行。
- 未运行 WSL/Linux/ext4 Gate；当前目标明确暂不考虑 Linux 实现。
- G9 acceptance/quality gate 尚未实现；M3 最终准入仍未关闭。
