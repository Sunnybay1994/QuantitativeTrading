# M3-G4B-R1 formal FeatureArtifact 交付报告

日期：2026-08-02  
状态：R1 返工与 Windows 自测完成；待独立复验、WSL base / py312 补验与主验  
任务单：[`M3_G4B_R1_formalFeatureArtifact任务单.md`](M3_G4B_R1_formalFeatureArtifact任务单.md)

## 交付内容

- 新增正式公共入口 `build_feature_artifact` 与 `verify_feature_artifact`，只接受 exact
  `VerifiedG1Release`、`VerifiedSnapshotArtifact`、`VerifiedProviderArtifact`、
  `VerifiedExperimentIdentity`、`VerifiedFoldPlanArtifact`。
- development/formal 入口共用同一内部构建、train-only schema selection、segment 发布、coverage、manifest
  与 fresh verifier；没有复制两套特征摘要或验真算法。
- 正式 verifier 通过 `verify_fold_plan_artifact` fresh 重验 G4A 及其显式 G1/snapshot/provider/experiment
  上游与 receipt；feature receipt 使用显式路径和 alias root 逐项闭合，不假设所有上游同根。
- Qlib adapter 新增独立 `build-alpha158-formal` 子命令。父进程仅通过 subprocess 环境临时传递 provider URI，
  稳定 request/response/manifest 不保存绝对 URI；正式 request 使用 `release_kind=formal`、
  `formal_gate_eligible=true` 且禁止 `example_id`。
- worker 固定 Qlib 0.9.7 `Alpha158`、空 infer/learn processors、空 label config，按 provider history start
  初始化 handler，只用 `DatasetH.prepare(..., col_set="feature", data_key=DK_I)` 导出特征；index 通过
  snapshot 的 `from_qlib_symbol` 转换，test 输入/输出不含 label。
- 包根导出正式 build/verify；development 入口及 `VerifiedDevelopmentExampleFeatureArtifact` 保持原身份。

## R1 独立初验返工

- request/response 新增稳定的 `provider_uri_sha256`，唯一算法为 canonical JSON
  `[provider_key, "provider"]` 的 SHA256；正式与 development 均不把主机绝对 provider URI 写入稳定产物。
- `contracts.py` 冻结 formal/development request 与 response-extra 的固定字段集合，父进程 verifier 和隔离
  worker 共用同一协议 SSOT；双方均按 release kind 校验 exact key set，未知、缺失或跨 kind 字段 fail closed，
  verifier 不再从收到的 request 动态推导 response schema。
- 新增真正的 formal 成功闭环 fixture：使用公开严格入口发布并验真 G1、snapshot、provider、experiment、
  folds，再执行 feature build、`features` receipt 和 fresh `verify_feature_artifact`。fixture 不把 development
  capability/dataclass 伪装成 formal；仅用确定性无网络 subprocess stub 替代外部 Qlib dump 与 Alpha158 计算。
- formal fixture 断言 exact `VerifiedFeatureArtifact`、formal request 无 `example_id`/绝对 URI、规范 URI digest、
  receipt stage/root closure、h=5/10 共用同一 feature manifest/receipt 且 worker 只调用一次，并在重新发布匹配
  漂移字节的 receipt 后确认未知 request/response 字段仍被 fresh verifier 拒绝。

## 验证结果

Windows 原生 Miniforge：

- 白名单 Ruff：通过。
- 定向 mypy（`contracts.py`、`features.py`、`qlib_adapter.py`、包入口及 formal fixture）：
  `Success: no issues found in 5 source files`。
- `test_m3_feature_artifact.py`、`test_m3_feature_digests.py`、
  `test_m3_qlib_worker_protocol.py`：`22 passed in 146.68s`。
- `test_m3_formal_feature_artifact.py`：`1 passed in 1036.41s (0:17:16)`；完整执行公开 strict
  G1→snapshot→provider→experiment→folds→features build/receipt/fresh verify 链及 formal schema drift 负例。
- 覆盖 development 原闭环、train-only 全 NaN 列剔除、coverage/receipt/hash 漂移、formal/development
  capability 交叉拒绝、URI digest 漂移、request/response 未知字段及 formal request 携带 `example_id` 在
  Qlib import 前拒绝。
- `git diff --check`：通过。

## 待补验证与边界

- WSL base Ruff/mypy/pytest 调用在启动前被当前执行额度审查拦截，未产生 Linux 结果。
- 因同一额度拦截，本轮未在 WSL `py312` 对实际 Qlib 0.9.7 worker 执行正式 provider smoke；源码签名已按
  已安装 Qlib 0.9.7 `Alpha158` / `DatasetH` 实现核对，但这不替代运行证据。
- Windows 已完成严格 formal G1→G4B 工程合同闭环；fixture 使用无网络确定性 dump/feature worker，因此不构成
  实际 Qlib 0.9.7 运行证据、真实数据性能证据或 formal Gate 关闭。
- 本包没有连接 `run_m3`，没有运行正式数据、网络、G1 journal 或 artifact；不关闭 formal G4/M3 Gate。
- Windows 结果不替代 Linux/ext4 Gate；本 worktree 未提交。
