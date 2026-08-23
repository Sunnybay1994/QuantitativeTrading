# M4 P4-C R1 durable cancel 交付报告

## 结论

P4-C 的 R1 独立初验发现 3 个 P1 与 2 个 P2，现已完成 R2 返工与 Windows 主验，状态为
**待全新独立复验**。本包只关闭 durable cancel
工程前置，不关闭 P6、P8、四周 PAPER/SHADOW soak、live broker 或 M4。

## 实现范围

- schema v5 增加独立的 `cancel_commands`、`cancel_deliveries`、`cancel_event_links`，并保留
  order outbox 的原有合同。
- 新增严格的 cancel command / delivery wire codec、风险判定和 session counter。
- `ExecutionService.stage_cancel` 负责冻结目标订单快照、风险判定和原子落库；
  `dispatch_cancel` 使用 claim/lease/fence，区分 `NOT_SENT`、`SENT` 与 `UNKNOWN`。
- `SENT` 回调的 event、cancel-event link、OMS aggregate、ledger/checkpoint 与 delivery 终态在
  同一事务提交；异常不会留下部分 callback。
- adapter 前先持久化 `CANCEL_GATEWAY_STARTED`，started attempt 永不自动 reclaim；最后一次快照
  重证到 adapter crossing 由同一 `BEGIN IMMEDIATE` writer fence 覆盖。
- `recover_local_state` 将 cancel payload、delivery attempt/lease/terminal/error、counter 和 links
  纳入恢复闭包与 recovery identity，PENDING/LEASED/UNKNOWN/断链分别按冻结语义处理。
- P7 的 recovery 复核同步透传新增 cancel 闭包字段，避免报告层丢失已验证事实。

## 关键不变量

- 同一原订单只有一个逻辑 cancel；重复 stage 不重复增加 cancel counter。
- 只有明确 `NOT_SENT` 且 lease/fence 仍匹配时可回到 PENDING；started exception、malformed
  result 和 `UNKNOWN` 不自动重发。
- cancel callback 的 `ExecutionEvent.command_id` 仍指向原 order command；归属由 durable
  cancel-event link 证明。
- non-PAPER、终态订单、无 broker id、伪造 payload/identity/counter 在 gateway 前关闭。
- 旧 `dispatch_pending` / `dispatch_commands` 以及 P5/P7 的公开行为保持不变。

## Windows 验证

解释器：`D:\Miniforge3\python.exe`，`PYTHONPATH=src`。

```text
python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_wire.py
  tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py
  tests/unit/test_reconcile.py tests/unit/test_execution_report.py -q
341 passed, 5 skipped

python -m ruff check src/quant/execution src/quant/reporting/execution_report.py
  tests/unit/test_execution_store.py tests/unit/test_execution_wire.py
  tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py
  tests/unit/test_reconcile.py tests/unit/test_execution_report.py
All checks passed

python -m mypy src/quant/execution src/quant/reporting/execution_report.py
Success: no issues found in 20 source files
```

Windows pytest 仅出现工作区 `.pytest_cache` 无写权限警告，不影响测试结果。WSL Miniforge base
验证受当前执行额度/权限阻塞，尚未运行；Windows 结果不替代 WSL Gate。

## 仍待完成

- 由未参与实现的独立会话执行任务书逐项初验并增加并发/fence/corruption 反例。
- 独立初验通过后再进行主 Agent 最终 diff/合同复核。
- P6 PAPER 操作 CLI 与 P8 稳定性/故障演练另包推进。

## R2 返工闭环

- 现象：arm 后 late fill 可在最后一次读取之后跨过 gateway。根因是快照重证与 adapter crossing
  不在同一 writer fence。规则：先持久化 started marker，再在一个 immediate transaction 内重证并跨越
  exact PAPER cancel adapter。新增测试确认 late fill 的 CAS 已成功、gateway 调用为 0。
- 现象：adapter started 后跨 lease 的 malformed result 留下可 reclaim LEASED。根因是 terminal 写入被
  lease 上界拒绝，且过期 LEASED 没区分 started。规则：started marker 禁止 auto reclaim；同 owner/attempt
  未被继任时允许安全落 UNKNOWN。新增跨 lease 后第二次 dispatch 为 0 调用测试。
- 现象：SENT 两 callback 删除一条 link 仍 READY。根因是恢复仅检查“至少一条”。规则：SENT 的 links
  必须精确等于冻结 observed prefix 之后的 aggregate event suffix。新增部分删链反例。
- NOT_SENT 现在持久化 `CANCEL_GATEWAY_NOT_SENT`；callback transaction 失败公开返回
  `CANCEL_CALLBACK_TRANSACTION_FAILED`，并维持 UNKNOWN、零部分写。
