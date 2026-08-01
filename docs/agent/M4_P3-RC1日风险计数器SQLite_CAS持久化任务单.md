# M4 P3-RC1：日风险计数器 SQLite CAS 持久化任务单

状态：**隔离实现、自验与独立只读复验通过；待主线合并**

日期：2026-07-31（Asia/Shanghai）

执行角色：主 Agent。用户当前要求省略外部实现与外部初验；内部 subagent 仅承担只读对抗审计。

## 1. 目标

把 `DailyRiskCounters` 从“调用方自行保存的字典”升级为 `ExecutionStore` 内的认证持久状态，关闭：

- 进程重启后订单数、撤单数和当日买入金额归零；
- 两个 worker 基于同一旧快照更新时后写覆盖先写；
- command / aggregate / outbox 与风险计数分开提交；
- SQLite payload 或 identity 被篡改后继续交易。

本切片不实现 PaperGateway、cancel 业务流、service、reconciliation 或四周 PAPER Gate。

## 2. 权威合同

- `src/quant/execution/risk.py` 的 `DailyRiskCounters` 是计数器字段和数值约束 SSOT。
- `src/quant/execution/store.py` 的 `ExecutionStore.transaction()` 是写事务边界。
- `src/quant/execution/migrations/` 是 schema version SSOT。
- C0 配置继续定义 `max_daily_notional`、`max_orders_per_day` 和
  `max_cancels_per_day`；本切片不复制阈值。

## 3. 接口和状态语义

```python
repo.get_daily_risk_counters(session_date) -> StoredDailyRiskCounters | None

repo.compare_and_set_daily_risk_counters(
    *,
    expected_identity: str | None,
    counters: DailyRiskCounters,
    updated_at: datetime,
) -> bool
```

- `expected_identity=None` 只表示显式首次初始化。
- 缺行且 expected 非空：`RISK_COUNTERS_STALE`。
- 已有行与新 counters 完全相同：成功提交后的精确重试，返回 `False`，不得更新时间。
- 已有行 identity 等于 expected：原子更新并返回 `True`。
- 其他 identity 差异：`RISK_COUNTERS_STALE`，不得覆盖。
- 方法必须可与 command、aggregate、outbox 在同一个现有 transaction 中提交或回滚。

## 4. 持久化与身份

- migration v3 新增 `daily_risk_counters`，每个 `session_date` 最多一行。
- payload 是严格 UTF-8 canonical JSON：固定键、固定类型、排序键、无空白。
- identity 是带版本和类型 envelope 的 SHA-256。
- getter 必须逐项验证 session key、canonical payload、payload 内日期、identity 和 UTC
  `updated_at`；任一不一致均为 `ROW_CORRUPT`。
- 非法 bool/负数/NaN/Infinity/非 UTC 时间必须在 SQL 前失败。

## 5. 文件白名单

生产：

- `src/quant/execution/risk.py`
- `src/quant/execution/store.py`
- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/migrations/v003_daily_risk_counters.py`

测试和文档：

- `tests/unit/test_risk_counter_store.py`
- `tests/unit/test_execution_store.py`
- 本任务单及对应主 Agent 验收报告

## 6. 稳定失败语义

- `COUNTERS_INVALID`
- `RISK_COUNTERS_STALE`
- `ROW_CORRUPT`
- `RISK_COUNTERS_WRITE_FAILED`
- 事务竞争继续使用既有 `TX_BUSY`

错误不得包含 SQL、payload、绝对路径、凭据或底层异常文本。

## 7. 强制反例

1. 两 worker 同读旧 identity；A 更新成功后，B 必须 stale，不能覆盖。
2. command + aggregate + outbox + counters 同事务，在 counters 写后注入异常，四者全部回滚。
3. 关闭并重开数据库后计数和 identity 不变。
4. 成功提交后的相同 payload 重试为 no-op。
5. 分别篡改 identity、payload、updated_at，getter 均 `ROW_CORRUPT`。
6. 伪造 bool、负数、NaN 计数器，SQL 前 `COUNTERS_INVALID` 且不得留下行。
7. v1/v2 旧库升级至当前版本后，旧 outbox 仍保留且不被误标为可发送。

## 8. 验收命令

Windows 原生 Miniforge：

```powershell
$env:PYTHONPATH='<worktree>\src'
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_risk_counter_store.py `
  tests/unit/test_pretrade_risk.py `
  tests/unit/test_execution_store.py -q
D:\Miniforge3\python.exe -m ruff check `
  src/quant/execution/risk.py src/quant/execution/store.py `
  src/quant/execution/migrations tests/unit/test_risk_counter_store.py `
  tests/unit/test_execution_store.py
D:\Miniforge3\python.exe -m mypy `
  src/quant/execution/risk.py src/quant/execution/store.py `
  src/quant/execution/migrations/v003_daily_risk_counters.py
```

WSL Miniforge base 运行相同目标，并显式把 `PYTHONPATH` 指向隔离 worktree 的 `src`。

## 9. 通过边界

本切片通过只证明风险日计数可认证、可 CAS、可同事务持久化；尚未证明 cancel 路径执法、
PaperGateway、service、reconciliation、日报或连续 28 天 PAPER Gate。
