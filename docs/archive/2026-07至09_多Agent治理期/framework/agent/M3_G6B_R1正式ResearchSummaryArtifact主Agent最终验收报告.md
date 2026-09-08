# M3 G6B R1 正式 ResearchSummaryArtifact 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅工程合同）**

## 1. 结论

G6B 已完成 formal ResearchSummaryArtifact 的完整工程闭环：逐折 fresh G6A、固定 horizon 与完整 fold/date
集合、跨折 daily 拼接后重新计算 coverage/八状态/IC/ICIR、typed fold metrics 投影、`2+4F` 输入与 4 输出
receipt，以及共享事务发布/no-clobber/稳定脱敏。实现、自测、全新独立初验和本轮主验均通过，现解锁 G7A。

该结论不代表真实全 work、模型性能、acceptance threshold、G7-G9、Linux/ext4 或 M3 Gate 通过。

## 2. 主验核对

- `EvaluationFreshVerificationContext` 对完整 G1→G5B formal 依赖执行 exact-type gate，且不序列化进产物。
- builder/verifier 共用 `_fresh_formal_summary`，按原序对齐 evaluation/context/receipt，每折 fresh 调用正式 G6A
  verifier；fold exact 等于 fresh plan 全集，daily exact 等于 planned test dates。
- 五层计数、四 coverage 与八状态从拼接后的 daily 重新计算；ICIR 使用全部 computable 日观测的
  `mean / sample_std(ddof=1)`，不平均各折 ICIR。
- `fold_metrics.parquet` 只由 typed `EvaluationMetricsV1` 投影，verifier 与 fresh projection 整表比较。
- receipt 固定 `research-summary/EXPERIMENT`，三折时 exact 14 inputs、4 outputs；四文件通过共享
  `ArtifactPublication` anchored exclusive transaction 发布。
- 公开失败只暴露稳定 artifact/rollback 码，异常 cause/context 脱离。

独立初验新增整包 daily/fold/metrics/manifest 全量重哈希并重签、非等权 coverage/ICIR 手算、第三折 fresh 后
POSIX root replacement，以及冷导入重依赖反例，均通过。

## 3. 验证证据

实现/独立验证：

- Windows：G6B `6 passed`、formal G6A `5 passed`，Ruff/mypy PASS；独立扩大合组因并发负载超时未冒充
  绿测；
- WSL base/DrvFS：G6B + formal G6A + development summary/evaluation `38 passed`，Ruff/mypy PASS；
- 实现者此前 Windows development/formal 分组共 38 项均已分别取得绿色结果。

主 Agent 定向复核：

- 跨日 ICIR 重算与 formal 三折 closed-loop/receipt 两节点 → `2 passed`；
- `evaluate.py`、包根与 formal test Ruff → PASS；
- 两个生产文件 mypy → PASS；
- `git diff --check` → PASS（仅既有 CRLF 提示）。

首次主验命令引用了不存在的测试节点，pytest未执行目标；随后以实际节点名补跑并通过。该命令错误不计为产品
失败，已在本报告如实保留。

## 4. 保留边界

- fixture 使用最小 typed formal 能力，未运行正式 release 上全部 folds/horizons。
- `/mnt/f` 是 DrvFS；兼容性绿测不替代 ext4 Gate。
- 未联网、未写正式 artifact/journal、未 add/commit；既有脏文件原样保留。
