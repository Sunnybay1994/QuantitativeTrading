
development 路径使用独立 `VerifiedDevelopmentExampleLabelReconciliationArtifact`、
`compute_development_label_reconciliation_key`、`reconcile_development_example_labels_with_qlib`、
`verify_development_example_label_reconciliation_artifact` 和 stage
`development-label-reconciliation`。其 key 固定包含 development domain tag 与 `example_id`，输出根名必须
同时标记 development/example，且 `formal_gate_eligible=False`；formal 入口 exact-type 拒绝 development
nominal。

入口从 verified bundle（含 `VerifiedExperimentIdentity`）重算唯一 `compute_label_reconciliation_key`；horizon/experiment/provider-validation/
label manifest 必须互相一致。任何混配在启动 worker 前失败。
三个 tolerance 必须是 exact finite non-negative float（bool/int 均拒绝），且满足 C0 已冻结的层级约束；summary
中的值必须与 spec 精确相等。`details_sha256` 对固定列、固定排序、nullable 语义的逻辑内容计算，不能使用
Parquet bytes 冒充。

### 7.3 worker 查询与 parent 独立计算

每个 horizon 一个 fresh worker。worker 通过 Qlib public API：

1. 对完整 label symbol/date 域读取固定表达式
   `Ref($close,-h)/Ref($open,-1)-1`；
2. 另读取原始 `$open/$close` 覆盖所有 return start/end dates；
3. 按命名 MultiIndex level 解析，只返回 label keys 的 expression 值和由原始 lookup 直接计算的
   `provider_raw_return`；
4. echo 全部 identity 和 row-key digest，不计算 benchmark、label diff 或最终 PASS。完整 key preimage
   还包括 `label_reconciliation_config_sha256`、`dependency_fingerprint_sha256` 与 `code_version`；worker
   必须在 import Qlib 前重算 `row_key_sha256` 并核对逻辑 `provider_uri_sha256`。

parent 使用 snapshot session calendar 独立推导每行 start/end；用 verified G1 原始 `510300.SH` open/close
独立计算 `audit_benchmark_return`，不得调用 label builder或复制 label benchmark。然后形成四个误差序列：

```text
expression_direct = |qlib_expression - provider_raw_return|
benchmark          = |audit_benchmark_return - label_benchmark_return|
raw_label          = |provider_raw_return - label_raw_return|
relative_label     = |provider_raw_return - audit_benchmark_return - label_relative_return|
```

只用绝对容差。provider float32 与权威 label Float64 的差异由 `label_return_atol` 容纳；不得把容差放大到能
掩盖 session/date 错位。所有值必须 finite。

### 7.4 details、summary 与 p99

details 精确列：

```text
as_of,symbol,benchmark,horizon_sessions,label_version,
return_start_date,return_end_date,
qlib_expression_raw,provider_direct_raw,label_raw,
audit_benchmark,label_benchmark,
audit_relative,label_relative,
expression_direct_abs_error,benchmark_abs_error,
raw_label_abs_error,relative_label_abs_error,
expression_status,benchmark_status,raw_label_status,relative_label_status,overall_status
```

主 join key 固定前五列；start/end 不进入 join key，避免用错误日期自洽。expected/actual keys 精确相等，
missing/extra/duplicate/non-finite 任一失败。summary 必须增加并重算
`missing_key_count/extra_key_count/duplicate_key_count/non_finite_count`，并分别记录四组 max/p99/tolerance。

p99 不调用依赖版本可能改变插值的 quantile 默认值；固定 nearest-rank：对升序 n 个误差，索引
`ceil(0.99*n)-1`（n>0）。summary `passed` 当且仅当所有计数为 0 且每个 cell 四项均通过。

产物目录精确 `reconciliation.parquet,reconciliation.json`；strict reader 从 details 重算全部 count、row-key、
max/p99/PASS，拒绝自报 summary。跨包与 G9 只能消费 `VerifiedLabelReconciliationArtifact` 或由该 verifier
重新取得的 receipt/summary，不得接受裸 summary、caller 自报 receipt hash 或仅凭文件存在。

### 7.5 G3B 必测反例

全量非抽样、expression 正确/direct 错和反向、label benchmark 错用 t+2、start/end 交换但 join 仍命中、
Float32 正常量化、missing/extra/duplicate key、MultiIndex 顺序、horizon/experiment 混配、provider validation
自报 hash、worker cache A→B、worker echo/JSON/Parquet/timeout、p99 n=1/100/101、NaN/Inf/signed zero、summary
wholesale drift、parent Qlib import isolation 和四观察面脱敏。

## 8. 稳定异常与“抓大放小”

每包定义一个边界异常，`str(error)==code`、`repr` 只含 code、`from None`：

```text
M3SnapshotError: SNAPSHOT_INPUT_INVALID / SNAPSHOT_OUTPUT_INVALID / SNAPSHOT_IDENTITY_MISMATCH
M3ProviderError: PROVIDER_INPUT_INVALID / PROVIDER_RUNTIME_UNAVAILABLE /
                 PROVIDER_SUBPROCESS_FAILED / PROVIDER_STRUCTURE_INVALID /
                 PROVIDER_IDENTITY_MISMATCH
M3ProviderValidationError: PROVIDER_VALIDATION_INPUT_INVALID /
                           PROVIDER_WORKER_FAILED / PROVIDER_VALIDATION_MISMATCH
M3LabelArtifactError: LABEL_ARTIFACT_INPUT_INVALID / LABEL_ARTIFACT_IDENTITY_MISMATCH
M3LabelReconciliationError: LABEL_RECONCILIATION_INPUT_INVALID /
                            LABEL_WORKER_FAILED / LABEL_RECONCILIATION_MISMATCH
```

阻塞 P0/P1：identity/receipt 混配、session/PIT/return 日期错误、dump/tree/bin 错误仍通过、Qlib cache 污染、
worker/parent 可自报 PASS、发布覆盖/路径逃逸、凭据泄露、fake 冒充真实 Gate。

可记录 P2 后置：错误码可更细、注释/命名、deprecation warning、非关键性能优化。不得把全量结构、fresh
process、独立 benchmark、Float32 口径或 verified bundle 降为“小问题”。

## 9. 外部闭环报告与执行顺序

固定报告：

```text
docs/framework/agent/M3_G2A快照Artifact交付报告.md
docs/M3_G2A快照Artifact独立初验报告.md
docs/framework/agent/M3_G2BProvider构建与静态验真交付报告.md
docs/M3_G2BProvider构建与静态验真独立初验报告.md
docs/framework/agent/M3_G2CProvider公共API验真交付报告.md
docs/M3_G2CProvider公共API验真独立初验报告.md
docs/framework/agent/M3_G3A标签Artifact交付报告.md
docs/M3_G3A标签Artifact独立初验报告.md
docs/M3_G3B标签全量对账交付报告.md
docs/M3_G3B标签全量对账独立初验报告.md
```

每包实现者先读 `AGENTS.md`、`karpathy-guidelines.md`、本文、对应 SSOT 和上包最终验收报告。独立验收者
不得参与实现，至少增加两个不同 dtype/identity/故障点反例。失败按“现象—根因—规则—最小复现—新增
测试—通过条件”退回循环。外部通过只可表述“可交主 Agent 终验”，不得勾选 G2/G3/Gate。

原顺序把 snapshot receipt 的唯一 publisher 放在 G8B，却又要求 G2B 先消费 `VerifiedSnapshotArtifact`，形成
执行依赖循环。修订后的实现/正式运行顺序为：

```text
G1-P4C 主验
  -> G2A temp builder/strict verifier 合同实现 + 双平台定向主验
  -> G8A/G8B 最小 publication/StageRunner 前置
  -> 正式 G2A publish + receipt + VerifiedSnapshotArtifact 主验
  -> G2B 外部闭环 + 主验
  -> G2C 外部闭环 + 主验
  -> G3A 外部闭环 + 主验
  -> G3B 外部闭环 + 主验
  -> 兼容 WSL/Qlib 真实链路终验
```

## 10. 验证与真实 Gate 边界

每包先跑定向，再统一运行：

```bash
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m mypy src
```

G2A/G3A 可在当前环境真实执行无 Qlib 部分。G2B/G2C/G3B 默认使用 fake subprocess/worker；报告必须记录
当前 Python、Qlib availability 和真实命令未执行。最终 G2/G3 Gate 还要求在满足 `>=3.8,<3.13`、精确
`pyqlib 0.9.7` 的 WSL Miniforge 环境中：

1. 用已固定 SHA/bytes 的本地 `dump_bin.py` materialize；
2. 全量 static tree/bin 验真；
3. fresh Qlib public API 60×7 emitted + gap 回读；
4. h=5/h=10 全量 label reconciliation；
5. 全部 stage receipts、strict manifests 和 read/import audit 通过。

缺兼容依赖只能报告 G0/exit 4 blocker，不能把 fake 绿测写成 G2/G3 通过，也不能擅自降级 Python、Qlib 或
修改 base 环境。
