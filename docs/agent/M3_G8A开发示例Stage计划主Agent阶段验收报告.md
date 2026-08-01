# M3-G8A 开发示例 Stage 计划主 Agent 阶段验收报告

日期：2026-08-02

结论：**registry、SNAPSHOT、WORK、SUMMARY 计划合同通过；PROVIDER/EXPERIMENT identity-resolved waves 待补，不宣称完整 G8A 或 G8 Gate 通过。**

## 已完成

- 冻结 18 个 StageSpec registry，包含 G7 `backtest_plan`，所有 TREE 输出声明 closure manifest。
- `RunPlan` 对 registry 漂移、producer coverage、DAG、receipt 路径、静态发布目录重复/嵌套和 output coverage 失败闭合。
- WORK 顺序固定为 alignment → train → predictions → evaluation → targets → backtest_plan → backtest → tracking。
- feature 以 verified experiment key、fold 共享；各 work 只使用规范 `compute_work_key(experiment_key, fold, horizon)`。
- 正式 verified 类型与 development/example verified 类型严格分流；snapshot 延续 content-addressed 两步发布合同。
- 删除曾用于 provider/experiment 的 surrogate `_plan_key` 及一次性 builder，避免代理尚未产生的 receipt/hash。

## 主 Agent 验证

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m3_orchestration.py tests/unit/test_m3_orchestration_plans.py -q
13 passed
ruff check src/quant/research/m3/orchestration.py tests/unit/test_m3_orchestration_plans.py
All checks passed!
mypy src/quant/research/m3/orchestration.py tests/unit/test_m3_orchestration_plans.py
Success
```

实现阶段 WSL Miniforge `base` 同组 `13 passed`，Ruff/mypy 通过。DrvFS 反馈不替代 ext4 Gate。

## 未关闭项

- PROVIDER/EXPERIMENT 必须按 verified waves 补齐；provider-validation receipt、experiment code/dependency identity 与 label manifest 均不得预填。
- G8B 通用 static runner、G8C CLI、G8E/G8F 与真实 handlers 尚未完成。
- 本报告不生成正式 G8 identity、receipt 或 MLflow run。
