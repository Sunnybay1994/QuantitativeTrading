# M3 G5B R1：正式 PredictionArtifact 独立复验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL，返回返工**

## 1. 独立性与范围

- 使用与实现者分离的全新上下文，完整核对项目 `AGENTS.md`、`.ai` 规则、G5A R3 主验、
  G5B R1 任务书/交付报告、`predictions.py`、formal G5A/G4B 直接依赖、contracts/schema 和测试。
- 生产代码与实现者测试保持只读；本报告是唯一写入的审查文件。未 add/commit，未访问网络、
  `data/legacy`、正式 G1 journal 或正式候选目录。
- WSL 路径是 `/mnt/f` DrvFS，不是 ext4；本轮在 P1 缺陷成立后停止机械扩大回归，未形成新的
  Linux/ext4 Gate 证据。

## 2. 标准—证据—结论

### 已通过的独立检查

- builder/verifier 静态调用图：每个入口各有且仅有一处 `verify_model_artifact`、
  `build_inference_segment`、`predict_fitted_model` 调用；formal G4B inference 的公开签名与实现均无
  label 参数或 test-label 读取路径。
- G5A verifier、G4B inference loader、native predictor 分别注入 `ValueError` 和
  `RuntimeError`：六种情况均稳定返回精确 `M3_PREDICTION_ARTIFACT_INVALID`，cause/context 为空，
  output 为空。
- 独立 rank 探针：两个 model、相同 score tie、symbol 反序输入仍按 model 分组，symbol 升序，
  rank 连续 `1..N`，score 保持 Float64。
- Windows Ruff：`predictions.py`、包根导出、formal prediction 测试通过。
- Windows mypy：`predictions.py` 通过。
- 实现者已报告的 Windows/WSL 38-test 证据可复现来源明确，但不能覆盖下述新反例。

### 不通过的独立反例

#### P1-1：第二文件失败留下半发布目录

- 现象：在 Parquet 已写入后，让 `_write_exclusive` 抛出带私有 sentinel 的 `RuntimeError`；公开错误
  正确脱敏且 cause/context 为空，但 output 目录残留唯一的 `predictions.parquet`。
- 代码位置：`predictions.py:316` 先直接写最终 Parquet，`predictions.py:321` 才 exclusive 写 manifest；
  失败路径没有回滚。
- 违反规则：任务书 §6.2 要求失败后 output 保持空目录；精确两文件/no-clobber 发布不得留下可被误读为
  候选产物的半发布树。
- 最小复现摘要：patch `_write_exclusive` 抛 `RuntimeError("PRIVATE_SENTINEL")` 后调用 formal builder，
  得到 `ValueError("M3_PREDICTION_ARTIFACT_INVALID")` 且 `FILES == ["predictions.parquet"]`。

#### P1-2：Parquet 写入不是 exclusive，空目录预检存在 TOCTOU 覆盖

- 现象：在 `_require_empty_directory` 通过后、predict 返回前，由受控竞争写者创建
  `predictions.parquet` sentinel；随后 `_write_parquet` 静默覆盖该文件，builder 成功。
- 代码位置：`predictions.py:292` 只做一次空目录预检；`predictions.py:959` 使用 Polars path writer 直接
  写最终目标，不具备 `O_EXCL` 语义。
- 违反规则：任务书 §6.1–6.2 的 no-clobber/exclusive create；检查与写入分离不能保护并发出现的同名文件。
- 最小复现摘要：predict wrapper 写入 `b"DO_NOT_CLOBBER"` 后返回真实 score；build 无异常、sentinel
  被覆盖，证明不是理论竞态。

#### P1-3：copied model root 在 stale 拒绝前已触发 LightGBM load

- 现象：复制完整 model bytes 到另一 root，以 `replace(model, root=copied_root)` 调用真实 formal builder；
  在 G5A verifier 的 `_lightgbm` 处设置 forbidden counter，得到 `LIGHTGBM_CALLS == 1`，之后才因 receipt/root
  闭包失败而拒绝。
- 代码位置：`predictions.py:661` 先调用完整 `verify_model_artifact`，到 `predictions.py:672` 才比较 fresh
  capability；真实 G5A verifier 在 receipt output/root 闭包判断前加载 Booster。
- 违反规则：任务书 §4.4 明确要求 copied-root/identity/path 失败发生在任何 LightGBM load/predict 和首个
  输出写入前。实现测试用 monkeypatch verifier 直接返回 copied capability，没有覆盖真实 verifier 顺序。
- 最小复现结果：错误仍正确脱敏、output 为空，但 `LIGHTGBM_CALLS == 1`，因此时序合同未满足。

## 3. 必须返工与新增测试

1. 采用真正的事务式两文件发布：所有最终目标均具备 exclusive/no-clobber 语义；任一阶段失败只清理本次
   调用成功创建的文件，恢复为空目录，绝不删除调用前或竞争写者创建的文件。
2. Parquet 不得使用会覆盖目标的普通 path writer。可先写调用私有的安全临时文件，再以平台兼容、
   不覆盖既有目标的原子提交方式发布；两文件提交中途失败仍须按第 1 条可靠回滚。
3. 在进入完整 G5A verifier/Booster load 前，先用受信 receipt/path 闭包拒绝 copied model root；若这要求
   改动 G5A verifier 或超出当前白名单，主 Agent 必须先修订任务书/SSOT 再实施。
4. 新增至少这些回归：Parquet 写失败、manifest `ValueError`/非 `ValueError` 写失败、第二文件失败、
   空目录检查后出现同名 Parquet/manifest 的竞争写者、清理不得删除他人文件、真实 copied-root 时
   LightGBM load 计数为 0。每项同时断言固定脱敏、空 cause/context、最终目录状态和 no-clobber。

## 4. 验证记录

| 检查 | 结果 |
| --- | --- |
| Windows 定向 Ruff | PASS |
| Windows production mypy | PASS |
| rank/model/tie/Float64 独立探针 | PASS |
| 三个 hostile 依赖 × 两类异常 | 6/6 PASS |
| manifest 写失败后的空目录 | **FAIL：残留 Parquet** |
| Parquet exclusive/no-clobber | **FAIL：竞争文件被覆盖** |
| copied-root pre-LightGBM gate | **FAIL：load 计数为 1** |
| Windows/WSL 扩大 pytest | P1 成立后停止；不用于冲淡失败结论 |

## 5. 结论

**FAIL，返回返工。** G5B R1 的 freshness、label-free inference、rank、receipt 校验和错误脱敏主体方向
正确，但发布原子性/no-clobber 与 copied-root 的 pre-load 时序仍破坏冻结不变量。完成上述最小返工并由
另一未参与返工实现的全新独立 Agent 复验前，不进入主 Agent 最终验收，也不解锁正式 G6。
