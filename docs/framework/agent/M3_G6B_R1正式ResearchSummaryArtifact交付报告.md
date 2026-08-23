# M3 G6B R1 正式 ResearchSummaryArtifact 交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：实现与双平台定向自测完成，待独立初验；不得据此宣称正式 G6B/M3 Gate 通过

## 1. 改动范围

- `src/quant/research/m3/evaluate.py`
  - 新增 frozen、exact-type `EvaluationFreshVerificationContext`；
  - 新增 formal `build_research_summary_artifact` / `verify_research_summary_artifact`；
  - 逐 fold fresh 调用正式 G6A verifier，校验完整 fold-plan、三序列同序、固定 horizon、test-date 闭包；
  - 复用既有 daily、fold projection、summary 数学、canonical writer、receipt 与 `ArtifactPublication`；
  - 新增稳定脱敏错误 `M3_RESEARCH_SUMMARY_ARTIFACT_INVALID` / `M3_RESEARCH_SUMMARY_ROLLBACK_FAILED`。
- `src/quant/research/m3/__init__.py`
  - 安全导出 context、formal builder/verifier。
- `tests/unit/test_m3_formal_research_summary_artifact.py`
  - 新增三折 formal fixture、完整集合/顺序/horizon、typed projection、手算 ICIR、重哈希重签、事务回滚与公开导出测试。

未修改 `contracts.py`、development 入口、G1--G6A 生产逻辑、配置或正式 artifacts/journal。工作树中其他既有脏文件均保留，未 add/commit。

## 2. fresh call 图与身份闭包

对 `evaluations[i] / evaluation_contexts[i] / evaluation_receipt_paths[i]` 原序 zip，禁止排序后重配：

```text
formal summary builder/verifier
  -> exact-type + same-length + strict fold order
  -> verify_evaluation_artifact(root=evaluations[i].root,
                                receipt_path=evaluation_receipt_paths[i],
                                remaining formal G1--G5B inputs=context[i])
  -> fresh capability exact equals supplied capability
  -> all context fold plans exact equal
  -> actual fold tuple exact equals fresh fold-plan.manifest.folds
  -> each daily date tuple exact equals PlannedFold.test_dates
  -> experiment receipt is same physical path for top level and every context
```

跨 context 固定 scientific config、experiment、snapshot/provider/fold-plan specs、LightGBM training spec，以及 evaluation manifest 的 experiment/model/model-version/horizon。三折 fixture 明确证明缺一折、乱序与跨 horizon 均在 output 0 bytes 前拒绝。

## 3. daily、metrics 与 fold projection

- 只拼接 fresh capability 的完整 daily，稳定按 `as_of` 排序；schema 精确复用 `_DAILY_SCHEMA`，日期唯一且覆盖所有 planned test dates。
- 五层 count 先跨 daily 求总数；四个 coverage 使用固定总分母；八状态按固定全集保留零计数。
- IC/ICIR 从拼接后的 `COMPUTABLE` daily observations 重算。手算测试使用
  `(1, 2, 10, 12, -3, 4)`，按 `mean / sample_std(ddof=1)` 得到跨折 ICIR，并证明其不等于三个 fold ICIR 的平均值。
- `fold_metrics.parquet` 只从 ordered `EvaluationMetricsV1` 严格投影，固定 String/Int64/nullable Float64 schema；verifier 逐表与 fresh typed projection exact 比对。
- 对抗测试修改 `n_predicted` 后同步重写 Parquet hash、manifest 并按 exact inputs/outputs 重签 receipt，formal verifier 仍拒绝。

## 4. 输出与 receipt 闭包

- builder 只接受 caller-created 空实体目录 `horizon=<5|10>`；完整 fresh/math 在首个正式输出 byte 前完成。
- 四个输出均由共享 `ArtifactPublication` anchored exclusive-create transaction 发布：
  `daily_ic.parquet`、`fold_metrics.parquet`、`metrics.json`、`manifest.json`。
- 四个 writer 分别注入含私有路径/TOKEN/sentinel 的异常，均得到稳定脱敏错误、`cause/context is None`，并精确回滚为空目录。
- formal receipt 固定 `stage=research-summary`、`scope=EXPERIMENT`、experiment key；三折输入数实测为 `2 + 4F = 14`，输出精确 4 个。
- inputs 顺序为 experiment manifest/receipt，随后逐 fold 的 daily/metrics/evaluation manifest/receipt；所有路径要求唯一物理对象，receipt verifier 重读 bytes。

## 5. 验证结果

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- G6B 新文件：`6 passed`（先完整 `5 passed`，随后新增手算 ICIR 单项 `1 passed`）；
- 既有 formal G6A：`5 passed`；
- development summary/evaluation：`27 passed`；
- Ruff：`evaluate.py`、`__init__.py`、G6B test PASS；
- mypy `evaluate.py --no-incremental`：PASS；
- `git diff --check`：PASS。

WSL Miniforge `base`，同一 `/mnt/f/.../m3-g4-formal`：

- G6B 新文件：`6 passed`（完整 `5 passed` + 新增手算 ICIR `1 passed`）；
- 既有 formal G6A + development summary/evaluation：`32 passed`；
- Ruff：生产/测试白名单 PASS；
- mypy `evaluate.py --no-incremental`：PASS。

Pandera/Polars deprecation 与 worktree `.pytest_cache` 权限 warning 为既有环境提示，不改变测试结论。

## 6. 未关闭边界

- fixture 使用最小 formal typed capabilities 并 monkeypatch G6A verifier 返回已冻结 fresh capability，用于隔离 G6B 契约；未运行真实数据的正式全 folds/horizons。
- 当前 WSL 路径为 `/mnt/f` DrvFS，不是 ext4；本报告只证明 Windows 与 WSL-base/DrvFS 定向兼容。
- 未证明真实数据性能、acceptance threshold、G7--G9、Linux/ext4 Gate 或 M3 完成。
- 本交付仍需未参与实现者的独立初验，至少补充 wholesale summary 重签、fold 集合攻击和完整重哈希 fold projection 攻击，再进入主 Agent 最终验收。
