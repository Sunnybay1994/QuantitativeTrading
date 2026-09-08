# M4-P6-R2：PAPER 操作 CLI 独立复验报告

日期：2026-08-02  
角色：未参与实现的独立复验 Agent  
结论：**FAIL**

## 结论摘要

P4-R2 已关闭上一轮“确认后新增 PENDING 仍发送旧集合”的主要缺陷：全局 PENDING 新增、缺失、未来可用、
LEASED 或 UNKNOWN 均在 adapter submit 前整体失败；双 worker 最多一个成功；旧
`dispatch_commands` allowlist 合同保持不变。Windows 定向回归、Ruff 和 mypy 全部通过。

但独立写锁故障注入证明，可重试的 SQLite `TX_BUSY` 被
`dispatch_exact_pending_commands` 无差别翻译为 `SERVICE_EXACT_PENDING_SET_DRIFT`，P6 随后输出
exit 20 / `CONFIRMATION_DRIFT`。这违反冻结任务单“store busy/事务失败保持稳定可重试边界”和 P6
exit 50 的合同，也会让操作员把基础设施瞬态故障误判为已确认经济集合变化。因此本轮复验不得通过。

## 合同逐项映射

| 合同 | 独立证据 | 结论 |
|---|---|---|
| 确认后新增/缺失/未来 PENDING 整体失败 | store 参数化反例验证三种漂移均保持全部 PENDING、`attempt_count == 0`；CLI 并发插入反例返回 20 且 submit 0 调用 | PASS |
| 任意 LEASED/UNKNOWN 阻断全局 exact set | store 参数化反例覆盖非选中成员的 LEASED 与 UNKNOWN，未触碰剩余 PENDING | PASS |
| exact set 全匹配且双 worker 最多一个成功 | service 全集合成功；两个独立 store/worker 中首个发送两项，第二个稳定漂移且 adapter 0 调用 | PASS |
| store 失败整体回滚、零经济影响 | 漂移反例均未产生 lease/attempt；独立 `TX_BUSY` 探针 gateway submit 0 调用 | PASS（状态无副作用） |
| store busy/事务失败保持可重试边界 | 独立写锁在 fresh recovery 后、exact claim 前注入，CLI 实际返回 `20/CONFIRMATION_DRIFT`，而非 exit 50 | **FAIL** |
| 旧 `dispatch_commands` allowlist 不变 | 当 A、B 均 PENDING 时旧 API 仍只派发选定成员，未选成员逐字段不变 | PASS |
| 错误正文与内部 cause/context 脱敏 | exact claim 的真实 `TX_BUSY` 对外 `ExecutionServiceError` 的 cause/context 均为空，stdout 为空、stderr 仅稳定 code | PASS |
| fresh challenge 后可继续 | 实际集合漂移不会 mutation；解除漂移并重新读取 challenge 后可按完整集合进入既有单一路径 | PASS（受本报告阻断项约束） |

## 阻断问题

### P6-R2-01：`TX_BUSY` 被误报为 confirmation drift

- 现象：在 `paper-submit` 已完成 fresh recovery 和 challenge 核对后、exact claim 前，由第二个 SQLite
  连接持有 `BEGIN IMMEDIATE`。确认调用返回 `20`，stderr 为 `CONFIRMATION_DRIFT`，gateway submit 为 0；
  direct service 同时稳定返回 `SERVICE_EXACT_PENDING_SET_DRIFT`。
- 根因：`src/quant/execution/service.py` 的 `dispatch_exact_pending_commands` 捕获 exact claim 事务的
  **所有**异常并统一设置 `claim_failed`，随后只抛 `SERVICE_EXACT_PENDING_SET_DRIFT`。因此
  `ExecutionStore.transaction()` 的 `TX_BUSY`、begin/commit 类事务错误与真正的集合闭包漂移不可区分；
  `src/quant/execution/cli.py::_raise_service` 又按 `DRIFT` 映射到 exit 20。
- 应遵循规则：P4-R2 任务单“失败语义”明确要求 store busy/事务失败保持稳定可重试边界；P6 任务单将
  store busy/可重试瞬态错误冻结为 exit 50。操作员确认漂移只用于经济集合或身份确实变化。
- 最小复现：stage A → 获取 submit challenge → fresh recovery 后由独立连接持有 write transaction →
  用原 challenge 确认。当前 direct service 输出
  `ExecutionServiceError SERVICE_EXACT_PENDING_SET_DRIFT None None 0`；CLI 输出
  `20, stdout='', stderr='CONFIRMATION_DRIFT\n', gateway.calls=0`。
- 新增测试：
  1. service exact claim 在 `TX_BUSY` 下断言稳定可重试 service code、cause/context 为空、gateway 0；
  2. CLI 用 service factory 在 recovery 后注入独立 writer lock，断言 exit 50、稳定 retry code、gateway 0、
     delivery/aggregate/ledger/风控计数逐项不变；
  3. 保留同构真实集合漂移反例，仍断言 exit 20，防止把 drift 泛化成 retry。
- 通过条件：只把 `OUTBOX_DELIVERY_EXACT_SET_DRIFT`/实际 closure fence 冲突映射为
  `SERVICE_EXACT_PENDING_SET_DRIFT`；`TX_BUSY` 及冻结为可重试的事务失败使用不含 `DRIFT`、可由 CLI
  稳定映射到 exit 50 的公开 code。两类异常都必须 gateway 0、整体 rollback、无敏感 cause/context。

## 额外对抗核对

- **确认项缺失**：输入包含不存在的 canonical id 时，pending tuple 与 selected 不等，事务在 claim 前失败。
- **未来 PENDING**：即使 selected id 完整相等，只要 `available_at > now` 仍失败，未被“尚不可派发”静默遗漏。
- **全局歧义成员**：非选中 delivery 处于 LEASED/UNKNOWN 也会阻断，而不是只检查 selected 成员。
- **双 worker**：`BEGIN IMMEDIATE` 串行化全局读与 claim；首个提交后第二个观察 LEASED/SENT，不能重复 crossing。
- **旧 allowlist**：新增 exact API 未改变旧 API 的局部选集用途，P4-R 兼容性成立。
- **脱敏边界**：真实 busy 异常离开 active `except` 后才翻译，direct service 的 `__cause__`、`__context__`
  均为 `None`；CLI 未输出数据库路径或 SQL。
- **Windows/WSL 边界**：本轮只验证 Windows 原生 SQLite 与 Python 行为，不把该结果表述为 Linux/WSL Gate。

## 验证证据

环境：Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`，唯一 basetemp；无网络、无 broker。

1. `python -m pytest tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_execution_cli.py -q -p no:cacheprovider --basetemp .pytest-p6-r2-independent-20260802`
   - `260 passed, 5 skipped in 12.04s`。
2. `python -m ruff check` 定向检查 store/service/CLI 及三份对应测试。
   - PASS。
3. `python -m mypy src/quant/execution/store.py src/quant/execution/service.py src/quant/execution/cli.py`
   - `Success: no issues found in 3 source files`。
4. 独立 direct-service writer-lock 探针：
   - `ExecutionServiceError SERVICE_EXACT_PENDING_SET_DRIFT None None 0`。
5. 独立 CLI post-recovery writer-lock 探针：
   - `20 '' 'CONFIRMATION_DRIFT\n' 0`；最后一项为 gateway submit 调用数。

当前外部权限额度窗口阻塞 WSL 启动，本轮依约未重试；没有 WSL Miniforge base 证据。本报告只写入这一份
独立复验报告，未修改生产代码或实现者测试，未执行 git add/commit。P8、PAPER/SHADOW soak、Linux Gate
与 M4 均保持开放。
