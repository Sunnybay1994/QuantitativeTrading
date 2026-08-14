# M4-P4-C-R1：PAPER durable cancel 任务单

日期：2026-08-02  
状态：R2 返工实现、外部独立复验与主 Agent 最终验收均已通过；仅关闭 durable cancel 工程子合同

## 目标与系统不变量

补齐 M4 PAPER 撤单的持久化、风控、恢复与派发闭环。CLI 永不直接调用 gateway；每个撤单先由当前 verified
`OrderCommand + OrderAggregate` 构造内容寻址 `CancelCommand`，在同一事务内完成 cancel 次数 Gate、counter CAS、
cancel command 与 delivery 落库，随后由有 lease/fence 的 worker 跨越 `GatewayCancelTransport`，并将 callback 的
event/OMS/ledger/link/checkpoint 在同一事务提交。

只支持 `ExecutionMode.PAPER`。不存在 live 分支、broker SDK import、自动修账、UNKNOWN 自动重发或绕过既有 OMS/
ledger reducer 的第二套状态公式。

## Schema v5

新增迁移 `v005_cancel_delivery.py`，只加表，不改写 v1-v4 既有字节：

- `cancel_commands(cancel_id PK, command_id FK commands, identity, payload, risk_counter_key, risk_policy_identity)`；
- `cancel_deliveries(cancel_id PK/FK cancel_commands, command_id FK commands, state, attempt_count, available_at,
  lease_owner, lease_until, terminal_at, last_error_code)`；
- `cancel_event_links(cancel_id FK cancel_commands, event_id FK events, PRIMARY KEY(cancel_id,event_id))`。

cancel payload 使用 `wire.py` 新增的 exact schema `m4-cancel-command-v1` codec；decode 后必须 re-encode byte-identical，row
key/identity 均等于 `cancel_id`。delivery 状态复用 `OutboxDeliveryState` 的
`PENDING/LEASED/SENT/UNKNOWN` 语义，但使用独立 `CancelOutboxDelivery` 类型，不能塞进 order outbox。

## 风控与 stage

`risk.py` 新增零 IO `evaluate_cancel_risk(cancel, trading_config, counters) -> CancelRiskDecision`。它重证 cancel/config/
counter；由 service 先证明 counter session 等于原 order 的 market `session_date`，pure risk 再按该 session 选择现有版本化 `risk.limits[].max_cancels_per_day`；只有
`counters.cancel_count + 1 <= limit` 才 accepted。projected counter 只增加 cancel_count，其他字段逐值不变。

`ExecutionService.stage_cancel(command_id, trading_config) -> StagedCancel`：

1. 用注入 UTC clock 作为 `as_of`，在一个 `BEGIN IMMEDIATE` 中读取 exact command/aggregate；
2. 若 target 已有 cancel，严格 decode/rebuild/replay 并返回 `replayed=True`，不重复计数、不写新 delivery；
3. first cancel 调用 public `build_cancel_command`；读取与现有 service 相同
   `risk_counter_scope:session_date` counter，执行 cancel risk；
4. accepted 时 counter CAS 与 cancel command/delivery insert 同事务；任一步失败整体回滚；
5. limit 拒绝返回稳定 `CANCEL_LIMIT_EXCEEDED`，零 cancel row/delivery/counter 变化；
6. stage 不调用 gateway，aggregate 保持当前 SUBMITTED/PARTIAL_FILLED，直到 broker callback 由 OMS reducer 推进。

同一 target 只允许一个 logical first cancel。并发重复请求必须命中相同 row/计数一次；不同 `as_of` 竞争不得产生两条
经济撤单，loser fresh 读取 winner 并以 winner canonical cancel replay，或稳定冲突且零额外计数。

## exact claim 与 dispatch

store 新增按单一 `cancel_id` 的 exact claim；仅 `PENDING` 或 lease **严格早于** now 的 `LEASED` 可领取。claim 在事务内
验证 cancel→target command、delivery→cancel、row identity/payload 闭包，更新 attempt/owner/until；任一漂移零 gateway。

`ExecutionService` 构造器新增可选且 runtime-checkable 的 `GatewayCancelTransport`；原 submit-only caller 不受破坏。
`dispatch_cancel(cancel_id)`：

1. exact claim 后、adapter 前重新读取 target command/aggregate/cancel，验证 aggregate 仍与 cancel 冻结 snapshot 完全相同；
2. 最后一次 UTC/lease fence 后调用 `validate_gateway_cancel` 与 injected PAPER cancel transport；
3. adapter exception、malformed result、`UNKNOWN` 均持久化 UNKNOWN，终止自动化；
4. `NOT_SENT` 只有在 lease 仍归本 worker 且 attempt 匹配时回到 PENDING，并记录稳定审计 code，可再次由显式确认调度；
5. `SENT` 先调用 `verify_gateway_cancel_result`；随后单一 store 事务写新 event、cancel-event link、OMS aggregate、ledger
   entries/checkpoint，最后将 cancel delivery 标 SENT；任一步失败不提交部分 callback，并返回明确的
   `CALLBACK_TRANSACTION_FAILED`，delivery 保持可对账的不确定状态，禁止静默自动重发。

重复相同 event bytes 幂等；同 event id 不同 bytes fail closed。cancel callbacks 的 `ExecutionEvent.command_id` 仍引用原 order
command，因此 event link 是恢复时证明该 callback 属于哪次 cancel 的唯一 durable 关系。

## 恢复闭包

`RecoveryRows` 与 P5 `RecoveryResult` 增加 sorted unique：cancel commands、cancel deliveries、cancel-event links。
`recover_local_state` 逐行 decode/re-encode并验证：

- cancel→存在 target command，delivery→cancel/command，link→cancel/event，linked event.command_id==target；
- cancel observed event ids 是 aggregate applied ids 的前缀，cancel snapshot quantity/status/time 可由 durable 历史证明；
- cancel counter 的 cancel_count 不小于当日 accepted logical cancel 数；不从 broker 事实补造本地 row；
- PENDING 为 READY；LEASED/UNKNOWN 为 QUERY_REQUIRED；断链、伪 identity、缺 link 或 counter 不足为 MANUAL_REQUIRED；
- recovery id 绑定 cancel payload、delivery attempt/lease/terminal/error、links 与既有全部 typed facts。

UNKNOWN 后若 retained broker callback 后到，可由显式 reconciliation/callback ingestion 包推进 OMS/ledger并加 link，但
UNKNOWN delivery 审计状态不得被改写为“从未不确定”。本包不实现 broker query ingestion。

## 稳定错误与脱敏

固定外部 code 至少包括：`CANCEL_PAPER_ONLY`、`CANCEL_LIMIT_EXCEEDED`、`CANCEL_IDENTITY_CONFLICT`、
`CANCEL_DELIVERY_NOT_CLAIMABLE`、`CANCEL_DELIVERY_FENCE_MISMATCH`、`CANCEL_DELIVERY_UNKNOWN`、
`CANCEL_CALLBACK_INVALID`、`CANCEL_CALLBACK_CONFLICT`、`CANCEL_RECOVERY_CLOSURE_INVALID`。

底层异常离开 active `except` 后 `raise from None`；异常 message/args/cause/context/object graph 不得恢复 payload、broker text、
路径、SQL、TOKEN、lease owner 或 command/cancel id 原文。

## 白名单

- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/migrations/v005_cancel_delivery.py`
- `src/quant/execution/wire.py`
- `src/quant/execution/store.py`
- `src/quant/execution/risk.py`
- `src/quant/execution/service.py`
- `src/quant/execution/reconcile.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_wire.py`
- `tests/unit/test_pretrade_risk.py`
- `tests/unit/test_execution_service.py`
- `tests/unit/test_reconcile.py`
- 本任务单、交付报告、独立初验报告

不得修改 domain enum、OMS/ledger 公式、gateway contract/PaperGateway、正式 G1/M3 artifact/journal 或 P6/P7 生产文件。

## 必测反例

1. 同 cancel 两线程 stage：一 row、counter +1；limit N/N+1 并发只有一个 accepted；
2. 双 worker claim 只有一个胜者；`lease_until == now` 不算过期；旧 owner/attempt finalize 被拒；
3. claim 后 late fill 改变 aggregate：adapter 零调用；
4. 未跨 adapter 的 NOT_SENT 可显式重调；started/exception/malformed/UNKNOWN 永不自动重发；
5. duplicate callback bytes 幂等，同 id 异 bytes 或 ledger/checkpoint/link 任一步失败整体回滚；
6. partial fill→cancel accepted→late fill→cancelled 的 OMS/ledger 数量、现金、fee 只应用一次；
7. non-PAPER、终态 order、无 broker id、伪 cancel/aggregate/config/counter 全表 before/after 不变；
8. recovery 任一 cancel/delivery/link/counter 断链 fail closed；UNKNOWN 只 QUERY，不伪装 READY；
9. 原 order `dispatch_pending/dispatch_commands` 与 P5/P7 回归不变。

## 验收边界

Windows 定向 Ruff/mypy/pytest；WSL Miniforge base 对应定向验证；独立复验增加未公开并发/fence/corruption 反例。
本包通过只关闭 durable cancel 工程前置，不关闭 P6、P8、四周 PAPER/SHADOW soak、live broker 或 M4。
