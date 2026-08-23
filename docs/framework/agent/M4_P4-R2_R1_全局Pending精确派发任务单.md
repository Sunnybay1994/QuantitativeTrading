# M4 P4-R2 R1：全局 PENDING 集合精确派发任务单

日期：2026-08-02  
状态：实现、外部独立初验与主 Agent 最终验收均已通过；仅关闭全局 PENDING 精确派发子合同，不关闭 P4/M4 Gate

## 问题与不变量

P6 独立初验复现：确认 `A` 后并发插入 PENDING `B`，现有
`dispatch_commands(command_ids=(A,))` 会只发送 A、保留 B，并返回成功。P4-R 的 allowlist 语义本身正确，
但 P6 的 operator confirmation 要求 crossing 时**全局可派发集合仍精确等于已确认集合**；新增、缺失、
LEASED 或 UNKNOWN 任一漂移必须在 gateway 前整体失败。

CLI 先 `recover` 再调用 allowlist 存在 TOCTOU，不能作为修复。

## 最小公共接口

保留现有 `dispatch_commands` allowlist 行为不变，新增：

```python
ExecutionRepository.claim_exact_pending_outbox_deliveries(
    *, command_ids: tuple[str, ...], worker_id: str,
    now: datetime, lease_until: datetime,
) -> tuple[OutboxDelivery, ...]

ExecutionService.dispatch_exact_pending_commands(
    *, command_ids: tuple[str, ...],
) -> DispatchResult
```

store 方法在同一 `BEGIN IMMEDIATE` 中：

1. 重验 canonical sorted unique non-empty command ids；
2. 读取全表 typed delivery closure；允许既有 `SENT`，但禁止任何 `LEASED`/`UNKNOWN`；
3. 要求当前全部 `PENDING && available_at <= now` command ids 精确等于输入；
4. 若存在 `PENDING && available_at > now`，同样视为集合漂移；
5. 精确 claim 全集合，rowcount、返回集合、payload/identity/command closure 任一不等则整体 rollback；
6. 不跨 gateway，不部分 claim。

service 只组合该原子 claim 与既有 `_dispatch_claimed` 单一路径，不复制 gateway/OMS/ledger 公式。

## 失败语义

- 输入非法：`SERVICE_COMMAND_SELECTION_INVALID`；
- 全局集合新增/缺失/延迟、存在 LEASED/UNKNOWN、claim fence 漂移：
  `SERVICE_EXACT_PENDING_SET_DRIFT`；
- store busy/事务失败保持既有稳定可重试边界；所有失败 gateway 0 调用。

P6 `paper-submit` 第二次确认只调用新 service API；首次 challenge 仍只读，原 P4-R allowlist API 与测试保持。

## 白名单

- `src/quant/execution/store.py`
- `src/quant/execution/service.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- `src/quant/execution/cli.py`
- `tests/unit/test_execution_cli.py`
- 本任务单、返工交付报告、独立复验报告

## 必测反例

- 确认后新增 PENDING、删除确认项、确认项变 LEASED/UNKNOWN、加入未来 available PENDING：整体失败、gateway 0；
- 双 worker 同时 exact claim，最多一个成功，另一个稳定漂移；
- exact set 全部匹配时每项仅一次发送；callback 失败仍走既有 UNKNOWN 语义；
- 原 `dispatch_commands((A,))` 在 B pending 时仍只发送 A，证明 allowlist 合同未被破坏；
- P6 使用旧 confirmation 遇集合漂移返回非零且不产生任何经济影响；fresh confirmation 后才可继续。

## 验证边界

Windows 定向 store/service/CLI pytest、Ruff、mypy；WSL base 对应定向验证。通过只关闭 P6 的原子集合
前置，不关闭 P8、PAPER soak、Linux Gate 或 M4。
