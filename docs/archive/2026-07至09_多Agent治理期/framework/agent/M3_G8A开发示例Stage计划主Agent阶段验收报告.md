# M3-G8A 开发示例 Stage 计划主 Agent 阶段验收报告

日期：2026-08-02

结论：G8A 的 PROVIDER、EXPERIMENT、WORK、SUMMARY plan-only 开发契约通过。该结论不代表真实 handler、正式 artifact、G8 或任何正式 Gate 通过。

## 已完成

- PROVIDER 拆为 materialization 与 validation 两个身份完全解析的 wave；只消费已验证 snapshot、固定 dump tool、provider artifact 与 receipt。
- ExperimentIdentity 只把 snapshot/provider 的 manifest 与 receipt 四项作为内容输入；provider-validation 仅作 PASS Gate，同时严格绑定 validation 配置摘要和 provider runtime fingerprint。
- labels/folds 仅在 ExperimentIdentity 已验证后规划；正式 G1 release 与 snapshot 的 release id、manifest hash 在 request 和 manifest 两处闭包，development/example 额外保持 example_id 一致，拒绝跨 release 混用。
- reconciliation 等待 verified label 后按正式 key 函数重算身份，并闭包 experiment、snapshot、G1、provider-validation receipt、label manifest 与 label receipt。
- WORK 固定为 features → alignment → train → predictions → evaluation → targets → backtest_plan → backtest → tracking；fold、label、reconciliation 与 experiment 的 key/hash、snapshot/G1 身份和 development example_id 必须一致，reconciliation 必须 PASS。
- SUMMARY 按 `(horizon, model, model_version)` 分组生成独立节点和发布目录；每组至少两折，折集合完全一致，evaluation 的 experiment/work/config/fold-plan/label 身份和 receipt 均进入闭包。h5 与 h10 不会进入同一 summary。
- development stages 全部使用 verifier 要求的 `development-*` stage 与独立 receipt 路径，不产生或伪装正式 receipt。
- 删除 provider/experiment 的 surrogate plan hash；所有范围 key 使用既有正式计算函数或已验证上游身份。

## 独立初验返工闭环

### 现象

初验发现首轮实现仍允许 release/snapshot 漂移、provider-validation 配置或 runtime 指纹漂移、WORK 跨 experiment/example 混用，以及 SUMMARY 把不同 horizon 合并且允许单折。

### 根因

首轮只完成 nominal track 分流和 stage 名称闭包，没有把 producer/verifier dataclass 中的全部共享身份字段提升为 continuation 前置条件；SUMMARY 仍沿用“一次实验一个节点”的旧假设。

### 应遵循规则

plan builder 只能从已验证对象形成多 wave 计划，并必须在进入下一 wave 前核对所有可共享的上游身份；summary 的规划粒度必须与 `evaluate.py` 的实际 producer 粒度一致。

### 新增最小反例与通过条件

- foreign formal/development release id 或 manifest hash 必须被拒绝。
- provider validation 配置摘要或 runtime fingerprint 任一漂移必须被拒绝。
- reconciliation wave 还必须拒绝 provider manifest、provider-validation 配置摘要或 runtime fingerprint 任一漂移；这三项必须同时由已验证 validation summary 与当前 provider/config 闭包。
- foreign experiment/example、错误 label manifest、未 PASS reconciliation 必须被拒绝。
- 每个 summary 必须至少两折；h5/h10 必须产生不同节点、路径和 receipt；不同组的折闭包必须一致。
- Windows 与 WSL base 的定向 pytest、Ruff、mypy 全部通过后，才可恢复“开发契约通过”的结论。

## 主 Agent 验证

Windows 原生 Miniforge：

```text
python -m pytest -p no:cacheprovider --basetemp <independent-artifacts-path> \
  tests/unit/test_m3_orchestration.py \
  tests/unit/test_m3_orchestration_plans.py \
  tests/unit/test_m3_orchestration_waves.py \
  tests/unit/test_m3_stage_runner_static.py -q
37 passed

ruff check src/quant/research/m3/orchestration.py \
  src/quant/research/m3/__init__.py \
  tests/unit/test_m3_orchestration_plans.py \
  tests/unit/test_m3_orchestration_waves.py
All checks passed!

mypy --no-incremental src/quant/research/m3/orchestration.py \
  src/quant/research/m3/__init__.py \
  tests/unit/test_m3_orchestration_plans.py \
  tests/unit/test_m3_orchestration_waves.py
exit 0
```

WSL Miniforge `base` 对应命令：`37 passed`，Ruff `All checks passed!`，mypy exit 0。该 WSL 运行位于 `/mnt/f`/DrvFS，只是双平台开发反馈，不替代 ext4/Linux Gate。

## 未关闭项

- 这是无真实网络、无正式 artifact 写入的 plan-only 开发合同；不生成正式 G8 identity、receipt 或 MLflow run。
- G8C CLI、G8E/G8F、真实 handlers 与正式 artifact 尚待后续任务；Windows 绿测与 WSL/DrvFS 开发反馈均不替代 ext4/Linux Gate。
- 第二轮独立复验同时发现 `labels.py` 的 producer/verifier 可能存在同类 provider-validation SSOT 闭包疑点。该文件不在 G8A 白名单，本包未修改；主 Agent 应另立任务核对 producer、verifier 与 orchestration 三方字段闭包，避免在本次 plan-only 修复中越界。
