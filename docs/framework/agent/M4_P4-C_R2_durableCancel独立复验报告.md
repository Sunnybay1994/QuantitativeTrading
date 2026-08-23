# M4 P4-C R2 durable cancel 独立复验报告

日期：2026-08-02  
角色：未参与 P4-C 实现、R1 初验或本轮返工的全新独立复验者  
结论：**PASS，可进入主 Agent 最终验收**

## 复验边界

本轮只读核对 `M4_P4-C_R1_durableCancel任务单.md`、R1 FAIL 报告、当前生产代码与测试；
未修改生产代码或现有测试。复验重点是 R1 的五个返工条件，以及 exact PAPER cancel 在 adapter
边界上的 writer fence、STARTED marker、旧 order dispatch、P5 recovery 与 P7 report 回归。

本结论只关闭 P4-C durable cancel 的 Windows 工程初验，不关闭 P6、P8、WSL Gate、四周
PAPER/SHADOW soak、live broker 或 M4。

## R1 五项返工结论

1. **arm 后 late fill：PASS。** 独立注入在 STARTED 已提交、adapter crossing 前由第二连接写入
   `PARTIAL_FILL`。CAS 明确返回 `True`，事件进入 aggregate，`filled_quantity=50`；最终
   `gateway_calls=[]`。公开结果和 durable delivery 均为 `CANCEL_SNAPSHOT_DRIFT/UNKNOWN`。
2. **started 后跨 lease：PASS。** 独立 gateway 在记录第一次调用后把时钟推进两分钟，分别覆盖
   malformed result 与 adapter exception。两者都落 durable UNKNOWN，`attempt_count=1`；后续
   exact dispatch 被 `CANCEL_DELIVERY_NOT_CLAIMABLE` 拒绝，gateway 永远只有一次调用。另注入
   callback COMMIT 失败，已持久化 STARTED marker 保留，补偿事务落
   `CANCEL_CALLBACK_TRANSACTION_FAILED/UNKNOWN`，同样不可 auto reclaim。
3. **SENT 多 callback 缺 link：PASS。** 两条 cancel callback 删除任一 link 后，恢复结果稳定为
   `MANUAL_REQUIRED/CANCEL_RECOVERY_CLOSURE_INVALID`；实现按 cancel 冻结前缀之后的 aggregate
   event suffix 计算完整 expected set，并要求 links 精确相等，不再只检查“至少一条”。
4. **NOT_SENT 审计码：PASS。** delivery 回到 PENDING 时持久化
   `CANCEL_GATEWAY_NOT_SENT`，attempt 不重置；该字段进入恢复事实与 recovery identity，明确
   NOT_SENT 才可由显式后续调度重试。
5. **callback 事务失败：PASS。** 独立在 cancel-event link 写入点注入异常，并另行注入 callback
   COMMIT 失败。公开 code 均为 `CANCEL_CALLBACK_TRANSACTION_FAILED`，delivery 为 durable
   UNKNOWN；前后对比确认 events、aggregate、ledger entries、ledger checkpoint 与 links 均零部分写，
   且 broker adapter 不会再次调用。

## 补充对抗证据

- 在 adapter 内用第二个 SQLite 连接尝试开启 writer transaction，稳定得到 `TX_BUSY`；原 cancel
  随后正常 SENT。这证明最终 aggregate 重验与 exact PAPER cancel adapter crossing 确实处于同一
  `BEGIN IMMEDIATE` writer fence，而不是仅靠调用顺序缩小竞态窗口。
- 独立 monkeypatch `validate_gateway_cancel` 抛异常，确认 gateway 0 调用，公开与 durable code 均为
  `CANCEL_GATEWAY_INPUT_INVALID`，delivery 为 UNKNOWN。
- 复验期间曾发现 crossing transaction 内的快照漂移被 broad `except` 误报为 callback transaction
  failure。返工已将最终快照重验单独捕获，并在同一事务写入/返回
  `CANCEL_SNAPSHOT_DRIFT`；上述 late-fill CAS 探针已在修正后的最终代码上重跑通过。同类 gateway
  input 校验也已从 callback failure 分支拆出。
- `claim_cancel_delivery` 仅允许过期且 `last_error_code IS NULL` 的 LEASED row 被 reclaim；已 arm 的
  `CANCEL_GATEWAY_STARTED` row 即使 lease 过期也不满足 reclaim 条件。异常或 commit failure 后不会
  静默重发。

## Windows 最终验证

解释器：`D:\Miniforge3\python.exe`，`PYTHONPATH=src`；pytest 使用独立
`.pytest-p4c-r2-review-final` basetemp。

```text
python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_wire.py
  tests/unit/test_pretrade_risk.py tests/unit/test_execution_service.py
  tests/unit/test_reconcile.py tests/unit/test_execution_report.py -q
341 passed, 5 skipped, 1 PytestCacheWarning

python -m ruff check --no-cache <P4-C source/tests + P5/P7 regression tests>
All checks passed!

python -m mypy --no-incremental
  src/quant/execution/migrations/v005_cancel_delivery.py
  src/quant/execution/wire.py src/quant/execution/store.py
  src/quant/execution/risk.py src/quant/execution/service.py
  src/quant/execution/reconcile.py
Success: no issues found in 6 source files
```

Pytest warning仅为工作区 `.pytest_cache` 无写权限，独立 basetemp 测试均完成。旧
`dispatch_pending/dispatch_commands`、P5 recovery、P7 execution report 已包含在 341 项合流回归中。

WSL Miniforge base 定向验证受当前执行额度/权限冻结阻塞；依任务指示未重复尝试。Windows 绿测不替代
WSL Gate。

## 剩余风险

- adapter boundary 持有 SQLite writer transaction 是任务冻结的 exact PAPER cancel 方案；若未来扩展到
  高延迟或 live transport，必须另行冻结不牺牲 STARTED 防重发与 aggregate fence 的架构，不能直接复用
  为通用长事务。
- P4-C 仍需主 Agent 做最终 diff、SSOT 与跨模块终验；P6/P8 和 M4 的运行期 Gate 状态不由本报告改变。
