# M4-P8-RUN-0B2A1 Durable Risk Receipt 与 Recovery 实现交付报告

状态：实现与自测完成，待全新独立初验；本报告不宣布 Gate 通过。  
日期：2026-08-09  
任务合同：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md)

## 1. 实现摘要

- 新增公开 `quant.execution.risk_wire`：严格 canonical、fresh decode、content identity 的
  `DurableRiskTransitionReceipt`，统一覆盖 `ORDER` 与 `CANCEL`；ORDER 保留完整 risk audit，CANCEL 绑定
  cancel、target command、policy 与 projected counter。
- 新增 v006 `risk_transition_receipts`，不 backfill legacy；store 提供 insert-only 的 subject 查询、全局 tail、
  exact replay 与 transaction-consistent recovery snapshot。
- `plan_and_stage()` 在原 `BEGIN IMMEDIATE` 事务内把 counter CAS、commands/outbox/ledger、ORDER receipt 与
  private stage 一起提交；`stage_cancel()` 同样把 counter CAS、cancel command/delivery 与 CANCEL receipt 一起提交。
- exact order/cancel replay 必须存在并 fresh 验证对应 receipt，不补签 legacy，不追加 sequence。
- recovery 在同一 snapshot 内验证：全局 sequence/previous chain；每个 counter key 的 ORDER/CANCEL 混合
  predecessor/projected chain；最终 durable counter 行；每个 command 的唯一 ORDER 归属；每个 cancel 的唯一
  CANCEL 归属及 target/policy 闭包。verified receipts 进入 `RecoveryResult` 与 `recovery_id`。
- hostile codec/store 异常映射为稳定、脱离原异常图的公开错误，不包含 payload detail、路径、SQL 或 TOKEN。

## 2. 写入文件

生产代码：

- `src/quant/execution/risk_wire.py`（新增）
- `src/quant/execution/migrations/v006_risk_receipt.py`（新增）
- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/store.py`
- `src/quant/execution/service.py`
- `src/quant/execution/reconcile.py`

测试：

- `tests/unit/test_risk_wire.py`（新增）
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- `tests/unit/test_reconcile.py`

未修改 reporting、soak、CLI/runner、broker/runtime、formal root、配置或正式 artifacts/journal。
共享工作树中 `src/quant/execution/__init__.py` 等既有脏改动均予以保留，本实现没有改写它们。

## 3. 关键反例

- canonical JSON 的未知/重复字段、非 canonical bytes、receipt identity/sequence 变更均稳定拒绝；ORDER 与
  CANCEL exact field-set 互斥。
- 显式验证同 key `ORDER R1 → CANCEL C1 → ORDER R2` 三段 predecessor/projected 连续链。
- order/order、cancel/cancel、order/cancel 三类同 predecessor 两连接竞争：旧 predecessor 只由一个写事务占有，
  busy 后 fresh tail 重试形成下一条链，不分叉。
- ORDER 或 CANCEL receipt 写失败时，counter、command/delivery、ledger/stage 在 commit 前整体回滚。
- private stage/command 或 cancel row 存在但对应 v006 receipt 缺失时，service replay/recovery fail closed。
- counter payload/identity 漂移、receipt 删除/断链、command/cancel ownership 不闭合均返回
  `RECOVERY_RISK_CLOSURE_INVALID`，不产生健康 `RecoveryResult`。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- `pytest tests/unit/test_risk_wire.py tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_reconcile.py -q --tb=short`
  → **285 passed, 5 skipped**。skip 为 Windows 平台既有能力差异用例。
- 白名单 Ruff → **All checks passed**。
- 白名单生产 mypy（5 个 source files）→ **Success: no issues found**。

WSL Miniforge base，项目位于 `/mnt/f/.../m3-g8ab-prereq`：

- 同组 pytest → **290 passed**。
- 同组 Ruff → **All checks passed**。
- 同组生产 mypy（5 个 source files）→ **Success: no issues found**。
- `findmnt -T /mnt/f` → `drvfs rw,noatime,...`。这是 WSL/DrvFS 跨平台工程证据，**不是 WSL2/ext4 Gate**。

提交前白名单 `git diff --check` 通过；没有 add/commit。

## 5. 已知后续边界

- 只读直接消费者探针：
  `pytest tests/unit/test_execution_report.py tests/unit/test_execution_soak.py -q --tb=short -x` 在
  `test_execution_report.py::test_filled_report_covers_orders_fills_ledger_risk_and_redacts_raw_text` 失败，公开码为
  `EXECUTION_REPORT_INVALID`（`execution_report.py:313`）。原因是 P7 的 retained-copy 仍重建旧形态
  `RecoveryResult`，没有携带新 `risk_receipts`。这正是 B2A2 的 API/complete-union 适配范围；本轮依冻结白名单
  没有修改 reporting/soak。
- 本包只证明同库 canonical 结构、counter transition 与 command/cancel closure。具有整个 OMS root 离线写权限的
  主体仍可协调替换完整合法 closure 并重算全部自哈希；独立首次观察/来源由后续 P8 evidence/anchor 负责。
- 尚未开展全新独立初验、B2A2、正式 runner/scheduler、WSL2/ext4 或 28 天 soak；M4 继续
  `WAITING_FOR_SOAK_EVIDENCE`。
