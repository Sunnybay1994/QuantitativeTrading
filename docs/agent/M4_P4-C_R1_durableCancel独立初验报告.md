# M4 P4-C R1 durable cancel 独立初验报告

日期：2026-08-02  
角色：未参与 P4-C 实现的独立初验者  
结论：**FAIL，不得进入主 Agent 终验**

## 结论摘要

Schema v5、exact codec、cancel risk、基本 stage/claim/dispatch/recovery 类型闭包已存在，Windows
定向 pytest/Ruff/mypy 为绿。但独立对抗复现发现 3 个会破坏“已跨 adapter 的撤单永不自动重发”、
“冻结快照漂移时 adapter 零调用”和“SENT callback-link 精确闭包”的高风险缺陷；另有
2 个稳定审计/外部返回码不符合冻结合同。

## 阻断问题

### P1：claim 后、adapter 前的 late fill 仍会跨过 gateway

- 现象：在 `dispatch_cancel` 完成第二个读事务后，利用注入 clock 在最后一次
  `now()` 中原子写入 PARTIAL_FILL 并 CAS aggregate。实际结果仍是
  `gateway_calls=[(cancel_id, 1)]`，仅在 adapter 返回后的 callback 事务里检测漂移并转
  `CANCEL_DELIVERY_UNKNOWN`。
- 根因：`service.py:475-488` 的快照重证与 `service.py:491` 的 adapter 调用之间没有可验证的
  aggregate fence；最后一次检查只验证 UTC/lease 时间。
- 破坏不变量：任务单必测反例 3 要求“claim 后 late fill 改变 aggregate：adapter 零调用”。
- 最小通过条件：在可稳定放大该竞态窗口的测试中，late fill 成功 CAS 后 gateway
  调用数必须为 0，delivery 保持可对账状态。

### P1：adapter 已开始后 lease 跨界，malformed/UNKNOWN 会被自动再次发送

- 现象：伪 gateway 记录调用后将 clock 推进 2 分钟并返回 malformed result。第一次
  `dispatch_cancel` 返回 `UNKNOWN_NOT_DURABLE`，delivery 仍是已过期 LEASED；第二次调用可重新
  claim，gateway 发生第 2 次调用，`attempt_count=2`。
- 根因：`_mark_cancel_unknown` 在观测时间已跨过 lease 时不落 UNKNOWN，但 store 仍允许任何
  `lease_until < now` 的 LEASED cancel 被重新 claim，没有“adapter started”的 durable fence。
- 破坏不变量：adapter exception、malformed result 和 UNKNOWN 必须持久化 UNKNOWN，并且永不自动重发。
- 最小通过条件：加入“adapter 已开始且 lease 在返回时跨界”的可重现测试；随后任意
  `dispatch_cancel` 都不得再调用 gateway，recovery 必须是 QUERY/MANUAL，不得 READY。

### P1：SENT 的多 callback 缺一条 link 仍被 recovery 判为 READY

- 现象：正常 SENT 撤单产生 2 个 callback 及 2 条 link。离线删除其中一条
  `cancel_event_links` 后，`recover_local_state` 返回 `disposition=READY, issues=[]`，仅余 1 条 link。
- 根因：`reconcile.py:449-456` 对 SENT 只要求“至少一条 link”，没有证明已提交 cancel
  callback 的完整集合。
- 破坏不变量：event link 是证明 callback 归属某次 cancel 的唯一 durable 关系；“缺 link”
  必须 MANUAL_REQUIRED/fail closed。
- 最小通过条件：增加“两个 cancel callback 只保留一条 link”的离线断链测试，并使
  recovery 稳定进入 `MANUAL_REQUIRED/CANCEL_RECOVERY_CLOSURE_INVALID`。

### P2：NOT_SENT 未持久化稳定审计 code

- 现象：NOT_SENT 后 delivery 为 `PENDING, attempt_count=1, last_error_code=None`。
- 根因：`mark_cancel_not_sent` 显式将 `last_error_code=NULL`。
- 通过条件：PENDING retry 不得丢失冻结合同要求的稳定 NOT_SENT 审计码，且 recovery id
  必须绑定该事实。

### P2：callback 事务失败没有返回明确的 CALLBACK_TRANSACTION_FAILED

- 现象：在 `put_cancel_event_link` 注入异常后，callback 事务确实整体回滚，delivery 也持久化
  `last_error_code=CANCEL_CALLBACK_TRANSACTION_FAILED`；但返回给调用者的 `CancelDispatchResult.code`
  是泛化的 `CANCEL_DELIVERY_UNKNOWN`。
- 通过条件：公开返回结果应保留任务单冻结的明确 callback transaction failure code，同时
  继续保持 UNKNOWN 终态和异常脱敏。

## 合同映射与通过证据

- v5 三表独立于 order outbox；strict lease 边界 `lease_until == now` 不可 reclaim：现有 store
  测试通过。
- cancel exact codec/identity/schema tamper：现有 wire 测试通过。
- risk 只增加 cancel counter；limit 拒绝无部分写：现有 risk/service 测试通过。
- 重复 stage 计数一次、双 worker 的 store claim/fence、NOT_SENT 显式再调度、malformed 常规窗口
  转 UNKNOWN：现有 service/store 测试通过。
- P5 recovery 和 P7 report 组合回归：Windows 合并定向集通过。
- 任务单必测反例 1、3、4、5、6、7 尚未形成完整的实现测试集；其中 3、4、5
  已由本初验的对抗复现证明存在失败路径。

## 验证命令与结果

Windows 解释器：`D:\Miniforge3\python.exe`，`PYTHONPATH=src`。

```text
python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_wire.py
  tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py
  tests/unit/test_reconcile.py tests/unit/test_execution_report.py -q
336 passed, 5 skipped, 1 PytestCacheWarning

python -m ruff check <P4-C source/tests + P5/P7 regression tests>
All checks passed!

python -m mypy src/quant/execution/migrations/v005_cancel_delivery.py
  src/quant/execution/wire.py src/quant/execution/store.py
  src/quant/execution/risk.py src/quant/execution/service.py
  src/quant/execution/reconcile.py
Success: no issues found in 6 source files
```

WSL Miniforge base 定向验证受当前执行额度/权限冻结阻塞，本轮遵循已知阻塞不重试。
Windows 绿测不代替 WSL Gate。

## 返工边界

实现者应先修复上述 5 项，增加稳定并发/fence/corruption 回归，再由未参与返工的独立初验者
复验。返工前 P4-C 不得标记通过，也不得解锁 P6/P8 或 M4 Gate。
