# M3 G4B 开发示例 FeatureArtifact 主 Agent 阶段验收报告

日期：2026-08-02

结论：**development example 的 G4B parent/worker/receipt 契约在 Windows 原生环境通过；正式
Alpha158、正式 G4B Gate 与 Linux Gate 未关闭。**

## 范围与边界

- 仅在隔离 worktree、pytest 临时目录及独立 development/example artifact root 写入。
- 返回类型固定为 `VerifiedDevelopmentExampleFeatureArtifact`，携带
  `release_kind="development_example"`、`formal_gate_eligible=False` 和 `example_id`；不能升级为
  `VerifiedFeatureArtifact`。
- development worker 在 fresh Python 子进程内生成确定的 Alpha158-shaped 158 维输入，不导入 Qlib、
  不请求网络，也不冒充真实 Alpha158 计算。稳定 request/response 不含绝对 provider URI、PID 或环境变量。
- 同 fold 的 feature spec 不含 horizon，可由 h=5/h=10 共享；正式数据性能和真实 Qlib 结论仍等待正式路径。

## 实现

- `features.py` 提供唯一的 `m3-f64-matrix-digest-v1` row/matrix/schema/content 摘要实现，规范 NaN、
  little-endian Float64、signed zero、行序和列序。
- 新增 strict FeatureBuildSpec/FeatureUpstreamPaths/schema/segment/manifest/verified contracts。
- development parent 在启动 worker 前沿 G4A 显式路径和 specs fresh 验真 G1→snapshot→provider→experiment→fold。
- worker 输入严格 158 个唯一 name/expression；只按 train eligible rows 删除全 NaN 列，validation/test
  复用 157 列投影。test 中 selected 后全 NaN 的行保留在 parquet，但不进入 scorable keys。
- coverage 固定逐 segment×date 记录 eligible/feature/scorable 与原因；verifier 从稳定 parquet 重建所有逻辑摘要。
- receipt 精确绑定 12 个上游文件和 request/response、三个 segment、coverage、manifest 七个输出。

## Windows 验证

```text
test_m3_feature_artifact.py
8 passed

feature digests + feature artifact + fold plan + worker protocol
24 passed

Ruff
All checks passed!

mypy
Success: no issues found in 5 source files

git diff --check
PASS

WSL Miniforge base：
feature digests + feature artifact
13 passed
```

独立对抗测试覆盖：跨 development/formal 混用、spec/worker echo 漂移、可解析 coverage 逻辑漂移、
Parquet bytes 漂移、receipt 增删输入/输出、no-clobber、train-only schema、unscorable 行保留，以及稳定
request 的路径/PID 泄露。独立结论 P0=0、P1=0。

## 未关闭事项

- production `build-alpha158` 的 Qlib 0.9.7 handler/DatasetH 路径、真实 provider 冷启动和 158 expression
  验真尚未实现，本报告不关闭正式 G4B。
- WSL base 定向开发契约测试已通过，但 development fixture 仍不替代 production Alpha158、正式发布或完整
  Linux Gate。
- 正式 G1 已 PUBLISH SUCCESS，且独立磁盘 `verify_g1_release` 已验真 17 个 artifact；Windows 轨
  `VerifiedG1Release` 已取得。正式 G2A 已转入独立执行线，Linux/ext4 Gate 仍单独保留。
