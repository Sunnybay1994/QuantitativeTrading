# M3 G6B R1 正式 ResearchSummaryArtifact 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**PASS；可进入主 Agent 最终验收**

## 1. 初验范围与白名单

已完整阅读 G6B R1 任务单、G6A R2 主验报告、G6B 实现交付报告，并逐项核对
`evaluate.py`、包根导出与新增 formal summary 测试。生产代码和实现者测试全程只读；
本轮唯一写入是本报告。未访问网络，未读写正式 artifact/journal，未扫描 `data/legacy`。

## 2. 契约映射

- `EvaluationFreshVerificationContext` 是 frozen dataclass，对自身所有成员执行 exact-type gate；
  context 只用于调用 formal G6A verifier，未进入 summary manifest/metrics/receipt。
- builder 和 verifier 共用 `_fresh_formal_summary`；三个序列先按原顺序一一对齐，
  fold 必须严格递增且等于 fresh fold-plan 的完整集合，不存在各自排序后再 zip 的路径。
- 每折调用正式 `verify_evaluation_artifact`，fresh 返回值与 supplied capability 逐字段比较，
  包含 resolved root、daily、typed metrics、manifest 及两个 receipt/manifest hash。horizon、experiment、
  scientific config、model/model-version、fold-plan 和上游物理 receipt 路径均重新闭包。
- 每折 daily dates 必须精确等于该 `PlannedFold.test_dates`；折间日期集合不相交，拼接后
  再验 schema、列序、dtype、唯一且严格递增的完整日期闭包。
- 五层 count 由拼接 daily 求和，coverage 由总计数/固定总分母重算；八状态按固定全集
  投影；IC/ICIR 只从全部 `COMPUTABLE` daily observations 以 `ddof=1` 重算，没有读取或
  平均 fold-level ICIR。
- `fold_metrics.parquet` 只从按折排列的 typed `EvaluationMetricsV1` 构造，列序和
  String/Int64/nullable Float64 schema 固定；verifier 与 fresh typed projection 整表 exact 比较。
- summary receipt 的逻辑输入精确为 experiment manifest/receipt，再按 fold 对齐每折
  daily/metrics/manifest/receipt，共 `2+4F`；输出精确 4 个。路径全局物理唯一，
  receipt verifier 重读所有 bytes。底层 StageRunner 按既有 SSOT 对 digest 做 canonical sort，
  G6B 的 fold-context-receipt 对齐仍在构造 digest 前以原序严格证明。
- 四输出复用已通过 G6A R2 主验的 `ArtifactPublication`：anchored root、exclusive create、
  首写前 root 复验、identity-aware rollback 和 no-clobber 语义没有分叉实现。
- formal 入口 exact 接收 formal evaluation/experiment/context，不调用 development verifier；公开失败
  稳定为 `M3_RESEARCH_SUMMARY_ARTIFACT_INVALID` 或 rollback 专用码，`cause/context` 为 `None`。

## 3. 独立对抗反例

1. **wholesale 全量重哈希重签**：在已成功的三折 summary 上改变 daily 计数，同步改变
   fold projection、重算 summary metrics，重写四个输出及 manifest 的全部 content hash，并针对
   目标 exact inputs/outputs 重签语法合法 receipt。formal verifier 仍以稳定脱敏错误拒绝：
   `WHOLESALE_REHASH_RESIGN_REJECT_PASS`。
2. **typed fold projection 攻击**：实现测试已修改 `n_predicted`，完整重写 Parquet hash、
   manifest 并重签；独立阅读确认 verifier 在 receipt 之前即用 fresh typed projection 拒绝。
3. **fold 集合/顺序/horizon**：缺一折、evaluation 单独乱序、目标 horizon 改为 10 均在
   output 0 bytes 前拒绝；源码中的唯一性与 expected-fold exact equality 同时覆盖重复/多一折。
4. **不等权 coverage/ICIR 手算**：使用每日分母差异很大的 3 日样本，实测
   `feature_coverage=91/102`，显著不等于日级 coverage 算术平均；ICIR 精确等于
   三个 daily IC 的全局 `mean/sample_std(ddof=1)`：
   `UNEQUAL_WEIGHT_COVERAGE_ICIR_RECOMPUTE_PASS`。
5. **fresh 完成后 root replacement**：在第三折 fresh verifier 返回后，将已预检的
   POSIX 输出目录 rename，并在原路径放回另一空目录。builder 在首个 writer 前拒绝，
   原目录与替换目录均为 0 files：`POSIX_ROOT_REPLACEMENT_ZERO_WRITE_PASS`。
6. **轻依赖导入**：Windows 冷导入包根后 `sys.modules` 不含 Qlib/LightGBM/MLflow：
   `COLD_IMPORT_NO_HEAVY_RUNTIME_PASS`。

## 4. 独立验证证据

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- G6B 新测试：`6 passed`，107.74s；
- formal G6A 直接前置：`5 passed`，80.06s；
- Ruff（`evaluate.py`、`__init__.py`、G6B test）：PASS；
- mypy `evaluate.py --no-incremental`：PASS；
- 首次 38 项合组在并发 Windows/WSL/对抗探针负载下 304s 超时，未将该超时计为通过；
  随后单独取得 G6B 6 项结果；剩余既有 32 项在 302s 内仍未完成而被超时终止，
  没有失败断言可供归因，亦未把该运行记为绿测。同一 38 项合组已在 WSL base 完整通过。

WSL Miniforge `base`，同一 `/mnt/f/.../m3-g4-formal` 工作树：

- G6B + formal G6A + development summary/evaluation 合组：`38 passed`，176.39s；
- Ruff：PASS；mypy `evaluate.py --no-incremental`：PASS。

Pandera/Polars deprecation 与 worktree `.pytest_cache` 权限为已知 warning，未改变断言。

## 5. 结论与边界

未发现可阻断 G6B R1 进入主验的问题。fresh formal G6A 完整折集、日期闭包、
拼接后数学重算、typed fold projection、`2+4F`/4-output receipt、事务/no-clobber、
formal/development 类型隔离和脱敏失败语义符合冻结契约。

本 PASS 只是 G6B 工程契约的独立初验；fixture 中 G6A verifier 为隔离的 typed fake fresh
capability，没有运行真实数据的全 folds/horizons。`/mnt/f` 合组证据是 WSL base + DrvFS
兼容性证据；额外 root-race 探针的临时输出位于 WSL POSIX 临时目录。二者都不代表
正式全 work、真实性能、acceptance threshold、G7--G9、Linux/ext4 发布 Gate 或 M3 已完成。
