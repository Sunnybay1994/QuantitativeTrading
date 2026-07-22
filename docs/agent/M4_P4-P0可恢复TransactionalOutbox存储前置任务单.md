# M4-P4-P0 可恢复 Transactional Outbox 存储前置任务单

状态：2026-07-18 冻结，主 Agent 自行实现与验收；24 小时临时流程内不调用外部 Agent

## 1. 目标与价值

- 用户可观察结果：SQLite store 能在同一事务中持久化 command、aggregate、outbox 和 delivery，能稳定 claim、
  lease、标记 `SENT` 或 `UNKNOWN`，进程重启后不会丢失待发送命令。
- 解决的问题：现有 v1 `outbox` 只有 opaque payload，没有 pending 枚举、worker 互斥、lease、attempt 或未知结果状态；
  直接实现 P4 service 会迫使业务层私下使用 SQL，破坏 typed repository 边界。
- 明确非目标：不实现 `execution/service.py`、Paper Gateway、订单 planner、自动重试线程、broker wire format、
  B1/B3/G7 语义，也不关闭任何 M4 Gate。

## 2. 现状与权威上下文

- 权威规划：[`../M3_M4实施总规划.md`](../M3_M4实施总规划.md) §4.2 与
  [`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) P0/P4/P5。
- 代码 SSOT：`src/quant/execution/store.py`、`src/quant/execution/migrations/`；store 只持久化 opaque bytes，
  不解释 command/outbox payload。
- 已确认事实：P0/P0-H1 已主验；v1 schema 有 `commands`、`order_aggregates`、`outbox`，但没有 delivery 状态。

## 3. 冻结合同

### 3.1 Schema v2

新增 `outbox_deliveries`，不重建或回填现有 `outbox`：

- `outbox_key`：主键及外键，指向 `outbox.outbox_key`；
- `command_id`：外键，指向 `commands.command_id`；
- `state`：仅 `PENDING | LEASED | SENT | UNKNOWN`；
- `attempt_count`：非负整数；每次成功 claim（含过期 lease 重领）恰加一；
- `available_at`：规范 UTC 文本；
- `lease_owner`、`lease_until`、`terminal_at`、`last_error_code`：按状态受 CHECK 约束；终态保留最后
  owner/lease/attempt 作为幂等审计信息，不代表 lease 仍有效；
- pending 查询索引以 `state/available_at/lease_until/outbox_key` 支持稳定枚举。

旧 v1 outbox 不自动生成 delivery，因此迁移后不得被静默发送。

### 3.2 Typed repository

- `put_outbox_delivery(...) -> bool`：要求 command/outbox 已在同一或更早事务中存在；同 key 同内容 no-op，
  同 key 异内容 `IdempotencyConflict`。
- `get_outbox_delivery(...)`：返回严格验证后的不可变记录；数据库非法状态或矛盾字段一律 `ROW_CORRUPT`。
- `claim_outbox_deliveries(worker_id, now, lease_until, limit)`：参数在 SQL 前严格验证；`now` 与
  `lease_until` 必须为 UTC，且 `lease_until > now`；`limit` 必须为正的真 `int`，拒绝 bool/0/负数。
- 可 claim 集合为 `PENDING && available_at <= now` 或 lease 已到期的 `LEASED`；顺序固定为
  `available_at, outbox_key`。`BEGIN IMMEDIATE` 串行化 writer，两个 worker 不得取得同一行。
- delivery 的 `command_id` 同时外键闭合 `commands` 与 `order_aggregates`；缺任一行都不能 stage delivery。
- claim 返回关联 outbox 的 opaque identity/payload、稳定 `command_id` 和本次 `attempt_count` fencing token；
  不生成新 command id。
- `mark_outbox_sent(...)` 只允许当前 lease owner 且 `expected_attempt` 等于当前 attempt 的调用从 `LEASED`
  转为终态 `SENT`；`mark_outbox_unknown(...)` 同理转为终态 `UNKNOWN` 并记录 `terminal_at`。仅 owner 相同不足以
  越过 fencing：同名 worker 的旧 attempt 迟到也必须被拒绝。普通 claim 永不返回 `SENT/UNKNOWN`。
- 相同终态参数允许幂等 no-op；任何终态回退或不同终态覆盖均 fail closed。
- `put_outbox_delivery` 的幂等 identity 只比较不可变创建字段（outbox_key/command_id/available_at）；即使当前已
  `LEASED/SENT/UNKNOWN`，相同 staging 重放也必须 no-op 且不得复活状态。
- claim 在筛选前校验全部 delivery 行及 LEFT JOIN 闭包；非法状态、孤儿 FK 或因过滤条件不可见的损坏行也
  不得被静默当作“无 pending”。
- 所有新增 SQLite 异常映射为稳定、脱敏的 `StoreError`，不得携带路径、payload、SQLite 原文、cause/context。
- SQLite writer 锁不等待不确定的默认超时；`BEGIN IMMEDIATE` busy 必须稳定、快速返回 `TX_BUSY`。
- worker id 与 error code 复用既有安全字符集且最多 128 字符，拒绝原值回显；同一 store 实例嵌套/并发 writer
  及两个连接的锁争用均 fail fast `TX_BUSY`。Windows/WSL smoke 各用独立临时数据库，禁止跨 OS 路径别名
  同时打开同一 SQLite 文件。

### 3.3 时间与失败语义

- Python 边界只接受 timezone-aware UTC `datetime`，规范化为固定微秒精度的 `...Z`；读取时严格 round-trip。
- `terminal_at >= lease_until` 时旧 worker 已失去所有权，mark 必须拒绝；调用方注入的 UTC `now/terminal_at`
  是受信业务时钟，P4 service 不得任意前移或回拨。
- gateway timeout/结果不明必须由上层显式标记 `UNKNOWN`；本包不提供 UNKNOWN 自动重试入口。
- 发送成功但 mark 前崩溃时，lease 到期后仍以原 `command_id` 重领；这是稳定幂等键支撑的 at-least-once 恢复，
  不是 exactly-once 声明。

## 4. 成功标准与反例

- [ ] v1→v2 migration 保留旧表/旧 row，schema version=2；旧 outbox 无 delivery 且不可 claim。
- [ ] command/aggregate/outbox/delivery 任一步异常导致整事务回滚。
- [ ] commit 后重启仍可 claim；claim 后重启在 lease 到期前不可重领，到期后另一 worker可重领且 attempt 恰加一。
- [ ] 双 store/双 worker claim 集合互斥，选择顺序确定。
- [ ] `UNKNOWN`、`SENT` 均带 `terminal_at`、为终态，不被普通 pending 查询返回且不能回退。
- [ ] lease 过期重领后，即使新旧 worker_id 相同，旧 `expected_attempt` 也不能落 `SENT/UNKNOWN`。
- [ ] bool/非正 limit、naive/非 UTC 时间、无效 worker/error code 均在 SQL 前失败。
- [ ] 手工污染 state、负 attempt、矛盾 lease/sent 字段时读取 fail closed。
- [ ] SQLite attempt 达到有符号 64 位上限时 fail closed，不允许自增转为 REAL。
- [ ] WSL base 定向 pytest、Ruff、mypy 通过；Windows 原生环境完成兼容 smoke。

关键对抗反例：worker A claim 后“发送成功但落库前崩溃”；lease 到期后 worker B 只能取得相同
`command_id/outbox_key/payload`，`attempt_count` 从 1 变 2；旧 attempt=1 即使复用同一 worker_id 也不能落终态，
不能产生第二个经济身份。

## 5. 范围与禁止项

可写白名单：

- `src/quant/execution/store.py`
- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/migrations/v002_outbox_delivery.py`
- `tests/unit/test_execution_store.py`
- 本任务书及对应交付/审查/最终验收报告
- 完成后仅同步必要的 M4 总任务书、总览、路线图和交接状态

禁止：修改 `service.py`、Gateway、OMS、portfolio/backtest；新增依赖；公开通用 SQL；使用本地时区或数据库
`now` 作为业务时钟；把本前置包写成 P4 或 M4 Gate 通过。

## 6. 验证顺序与安全

1. 新增 schema/API 对抗单测，再实现最小 v2 migration 与 typed methods。
2. WSL base：定向 pytest、`ruff check`、`mypy`；migration 属关键持久化变更，补跑 execution store 直接回归。
3. Windows Miniforge：相同定向测试和 Ruff smoke，验证路径/SQLite/UTC 行为兼容。
4. 独立内部子 Agent 只读审查新增合同并增加至少一个实现者未使用的反例；主 Agent 修订后终验。

迁移只在测试临时数据库及后续正常 `ExecutionStore.open` 时执行；不触碰现有用户数据库、不删除或覆盖数据。
若发现 v1 真实数据需要自动补 delivery、或 service wire format必须进入 store，本任务停止并重新冻结，不自行扩 scope。
