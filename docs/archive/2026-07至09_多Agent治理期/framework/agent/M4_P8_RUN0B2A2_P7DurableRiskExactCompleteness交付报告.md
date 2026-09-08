# M4 P8 RUN-0B2A2：P7 Durable Risk Exact Completeness 交付报告

日期：2026-08-09
状态：实现与自测完成，待全新独立复验；本报告不宣布 Gate 通过。

## 1. 交付结果

- `build_execution_report()` 已删除 `risk_decisions` 参数，不保留 optional、overload 或兼容入口；旧关键字由
  Python 直接拒绝。
- P7 fresh 重建 `RecoveryResult` 时显式透传 `risk_receipts`，并在生成 totals/report identity 前再次调用
  B2A1 公共 `verify_risk_receipt_semantic_closure()`。
- risk lines 唯一投影自 durable ORDER receipt 的 `DurableOrderRiskDecision.rule_results`；CANCEL receipt 参与
  recovery closure/identity，但不伪装为 pre-trade rule line。subject 仅写不可逆 identity，detail 不进入
  `ExecutionReport`、canonical bytes 或 repr。
- P8 session/fault recovery retained facts 显式演进为 v2，新增 exact `risk_receipts` 字段；编码使用公共 strict
  encoder，解码使用公共 strict decoder 并 fresh 构造 `RecoveryResult`。旧 v1 没有兼容回填旁路。

## 2. 修改范围

生产：

- `src/quant/reporting/execution_report.py`
- `src/quant/execution/soak.py`

测试：

- `tests/unit/test_execution_report.py`
- `tests/unit/test_execution_soak.py`

文档：本任务单、本报告，以及因 retained schema v2 演进而最小同步的
`docs/framework/runbooks/M4_PAPER_SOAK.md`。

未修改 B2A1 store/service/reconcile/risk-wire/migration 生产代码，未触正式 root、journal、runner、scheduler、
网络或注册状态。

## 3. 对抗覆盖

- caller `risk_decisions=` 注入稳定拒绝；非空 command 删除 durable receipt 并重算 outer recovery/reconciliation
  identity 后仍拒绝。
- canonical hostile receipt 中的 path/SQL/TOKEN/detail 不进入报告；公共 verifier 抛 `ValueError` 或带 marker 的
  `RuntimeError` 均映射为 detached `EXECUTION_REPORT_INVALID`。
- retained v2 对缺 `risk_receipts`、额外 legacy 字段和 receipt canonical bytes 漂移 exact fail closed。
- 已有 B2A1 组继续覆盖 missing/extra/duplicate/cross-plan/cross-kind、ORDER/CANCEL mixed chain 与 whole-rehash
  semantic closure；P8 独立 anchor 回归继续拒绝完整合法 closure 替换。
- builder/encoder 的 `open`、socket、SQLite 零 I/O 探针继续通过。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- `pytest test_risk_wire.py test_reconcile.py test_execution_report.py test_execution_soak.py -q`
  → **89 passed, 1 skipped**；
- 白名单 Ruff → **All checks passed**；
- 两个生产文件 mypy → **Success: no issues found**。

WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：

- 同组 pytest → **90 passed**；
- 同组 Ruff/mypy → **PASS**；
- `findmnt -T /mnt/f` → `drvfs rw,noatime,uid=1000,gid=1000,case=off`。

## 5. 边界

本交付只关闭 development 工程合同。RUN-0B2 正式装配、真实 28 日 PAPER soak、正式 scheduler、WSL2/ext4
及 M4 Gate 仍开放，状态继续 `WAITING_FOR_SOAK_EVIDENCE`。需由未参与实现的全新上下文独立复验，再进入主
Agent 最终验收。
