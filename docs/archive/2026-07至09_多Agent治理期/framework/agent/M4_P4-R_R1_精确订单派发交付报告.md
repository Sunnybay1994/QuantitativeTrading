# M4-P4-R-R1 精确订单派发交付报告

日期：2026-08-02  
状态：实现与 Windows 定向自测通过，待独立初验；不关闭 P6、P8、PAPER soak 或 M4。

## 交付范围

- `ExecutionRepository.claim_selected_outbox_deliveries(...)`：仅接受非空、字典序、唯一的 canonical command ID tuple；在调用方的 `BEGIN IMMEDIATE` 事务中先验证全部 command/outbox/delivery/aggregate 闭包及可领取状态，再以逐行 CAS 更新全部 selected delivery，返回顺序等于输入顺序。
- `ExecutionService.dispatch_commands(...)`：只消费 selected claim；输入或持久化失败统一翻译为脱敏、无底层 cause/context 的稳定 service error。
- `dispatch_pending(...)` 与新入口共同调用 `_dispatch_claimed(...)`，gateway lease fence、certainty、OMS、ledger 与 callback transaction 仍只有一套实现。

## 关键失败语义

- selected 成员只允许 ready `PENDING` 或 lease **严格早于** `now` 的 `LEASED`。
- 任一成员为 `SENT`、`UNKNOWN`、活跃 lease、future pending、缺行或 command/outbox/delivery 断链，整批零更新且 gateway 零调用。
- selected 更新 rowcount 非 1 时报告 CAS conflict，并回滚整个 savepoint/外层事务。
- 集合外 delivery 不参与查询或更新。

## 新增反例

- 三个 ready command 中只派发精确选择的两个，未选择 command 的完整 delivery 记录保持不变。
- selected 集合中一个成员分别为 `SENT`、`UNKNOWN`、活跃 `LEASED`、outbox 断链时，另一个 ready 成员保持 `PENDING/attempt_count=0`，gateway 零调用。
- 空、乱序、重复、恶意格式及格式合法但不存在的 command ID 均返回脱敏稳定错误。
- 两个 worker 对同一 exact set 至多一个成功，第二个 worker 无 gateway 调用。
- store 层验证返回顺序、集合外隔离及 terminal 成员导致的整批回滚。

## 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，显式 `PYTHONPATH=src`：

```text
python -m pytest -p no:cacheprovider tests/unit/test_execution_store.py tests/unit/test_execution_service.py -q --basetemp=artifacts/p4r-final3
230 passed, 5 skipped in 10.73s

python -m ruff check src/quant/execution/store.py src/quant/execution/service.py tests/unit/test_execution_store.py tests/unit/test_execution_service.py
All checks passed!

python -m mypy src/quant/execution/store.py src/quant/execution/service.py
Success: no issues found in 2 source files
```

WSL base 定向命令已发起，但主机在创建发行版实例时返回
`Wsl/Service/CreateInstance/E_ACCESSDENIED`，因此本轮没有 Linux Gate 结果；Windows 结果不替代 WSL Gate。

## 工作区说明

交付未提交。工作树在本任务开始前已有 P5/P0C 等修改与未跟踪文件；本实现只修改任务白名单中的
`store.py`、`service.py`、两份定向测试及本报告，保留所有无关脏文件。
