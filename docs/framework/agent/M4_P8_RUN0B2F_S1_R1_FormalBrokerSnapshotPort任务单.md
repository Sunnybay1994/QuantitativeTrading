# M4 P8 RUN-0B2F-S1 R1：Formal Broker Snapshot Port 任务单

日期：2026-08-12  
状态：**主 Agent 串行实现与 Windows 工程验收 PASS；只读 snapshot port 可供后续装配，formal gateway dispatch 等待 UA-M4-003**  
前置：RUN-0B2E R2 Windows 工程主验 PASS

## 1. 唯一目标

提供只读 formal `BrokerSnapshotPort`：它只消费一份 fresh、未关闭的 `VerifiedFormalPaperBrokerStoreCapability` 及其 exact runtime/policy/binding/account 链，从 B1 durable broker store 重建 `VerifiedBrokerEvidence`。

本包不实现 gateway dispatch，不接收 clock/fill/fault policy，不发送/取消订单，不打开 caller path，不创建或修改 store，不实现 service/CLI/runner/soak。formal gateway 被 UA-M4-003 阻塞。

## 2. Public API

新模块 `quant.execution.paper_formal_broker_snapshot` 只导出：

- `FormalPaperBrokerSnapshotError`
- `open_verified_formal_paper_broker_snapshot_port(...) -> BrokerSnapshotPort`

参数 exact 为 `store_capability`、materialized `environment/policy/binding/account`、explicit aware UTC `now`。入口必须先调用 public `verify_existing_formal_paper_broker_store_capability`，返回必须是传入同一 capability，之后才可取得 `capability.store`。

返回 port 的 `query_and_verify(gateway_identity=...)` 每次重新运行上述 B2E existing verifier，再调用 actual `DurablePaperBrokerSnapshotPort`；gateway identity 必须 exact 等于 capability identity。不得缓存 caller evidence、裸 snapshot 或 caller path。

## 3. 失败与安全

唯一稳定码：`PAPER_FORMAL_BROKER_SNAPSHOT_INVALID`。所有 public 失败 `cause/context=None`，不得泄露 path、SQLite、hostile marker 或上游错误图。

拒绝 fake/subclass/closed/stale/cross-chain capability、wrong gateway identity、store/tree/journal drift、hostile upstream verifier、hostile evidence reader。无任何写入、network、wall-clock、gateway dispatch 或 OMS 读取。

## 4. 白名单与验证

允许：

- `src/quant/execution/paper_formal_broker_snapshot.py`
- `src/quant/execution/__init__.py` 必要 lazy export
- `tests/unit/test_paper_formal_broker_store.py` 增加 snapshot focused 回归
- 本任务与唯一交付/主验报告

Windows：focused B2E+snapshot、B1 durable gateway 邻接、Ruff、mypy、cold import、scoped diff-check。当前不执行 Linux/ext4 Gate。

## 5. 通过条件与停止条件

通过条件：actual fresh B2E capability → actual B1 evidence snapshot → exact `VerifiedBrokerEvidence`；existing verifier 每次 query 被调用；错误脱敏；零写入；所有反例绿色。

若实现需要 caller path/裸 descriptor/裸 evidence，需要 clock/fill/fault mapper，需要修改 B1 schema/gateway dispatch/service/CLI，立即停止并转入 UA-M4-003，不得猜测。
