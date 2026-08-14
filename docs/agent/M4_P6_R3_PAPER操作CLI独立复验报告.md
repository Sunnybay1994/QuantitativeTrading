# M4-P6-R3：PAPER 操作 CLI 独立复验报告

日期：2026-08-08  
角色：未参与实现的独立复验 Agent  
结论：**FAIL**

## 结论摘要

R3 已修复 R2 报告中的直接阻断项：在 fresh confirmation recovery 之后由真实独立 SQLite
连接持有 `BEGIN IMMEDIATE` 时，direct service 稳定返回
`SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 返回 exit 50 / `EXECUTION_RETRY_REQUIRED`；异常
`cause/context` 均为 `None`，gateway 零调用，delivery 仍为 `PENDING/attempt_count=0`，recovery identity
逐字节语义不变。确认后真正新增、缺失、未来 PENDING、LEASED、UNKNOWN 五类集合漂移也都稳定返回
exit 20 / `CONFIRMATION_DRIFT`，旧 allowlist 仍只派发选中成员。

但独立的 claim 写入故障注入发现，exact-set store 在已经完成集合验证后，仍会把 SQLite 写入失败无差别
改写成 `OUTBOX_DELIVERY_EXACT_SET_DRIFT`。因此 service/CLI 会再次把基础设施写故障误报为操作员确认的
经济集合漂移。冻结任务单要求“store busy/事务失败保持稳定可重试边界”，该不变量尚未完整关闭，本轮
独立复验不得通过。

## 合同逐项映射

| 合同 | 独立证据 | 结论 |
|---|---|---|
| 独立 writer lock 的 `TX_BUSY` 保持可重试语义 | fresh recovery 后、exact claim 前由第二连接持有 `BEGIN IMMEDIATE`；direct service 返回 `SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 返回 `50/EXECUTION_RETRY_REQUIRED` | PASS |
| writer lock 失败脱敏且无部分 claim | direct exception 的 `cause/context` 均为 `None`；stdout 空、stderr 仅稳定 code；gateway 0；recovery id 不变；delivery 为 `PENDING/0` | PASS |
| 新增/缺失/未来 PENDING、LEASED/UNKNOWN 属于确认漂移 | 五个独立 post-confirmation 数据库状态探针全部返回 `20/CONFIRMATION_DRIFT` 且 gateway 0 | PASS |
| 旧 allowlist 合同不变 | A、B 均 PENDING 时，旧 `dispatch_commands((A,))` 只发送 A；最终状态为 `SENT + PENDING`，gateway 仅 1 次 | PASS |
| 集合验证后的 SQLite claim 写故障保持事务/写失败语义 | 合法 exact set 上用 SQLite trigger 在 `UPDATE ... state='LEASED'` 时 `RAISE(ABORT)`；实际返回 `SERVICE_EXACT_PENDING_SET_DRIFT` | **FAIL** |
| Windows 定向 pytest / Ruff / mypy | `262 passed, 5 skipped`；Ruff PASS；mypy 3 files PASS | PASS |
| WSL base `/mnt/f` 对应定向验证 | `266 passed, 1 skipped`；Ruff PASS；mypy 3 files PASS | PASS（DrvFS，不是 ext4 Gate） |

## 阻断问题

### P6-R3-01：exact claim 的 SQLite 写失败仍被误报为 confirmation drift

- **现象**：准备一个完整且一致的 PENDING exact set，在集合读取和验证通过后，用 SQLite trigger 让
  claim 的 `UPDATE outbox_deliveries ... state='LEASED'` 抛出 SQLite `ABORT`。delivery 整体回滚、gateway
  零调用，但 direct service 实际返回 `SERVICE_EXACT_PENDING_SET_DRIFT`，而不是
  `SERVICE_EXACT_PENDING_WRITE_FAILED`。
- **根因**：`src/quant/execution/store.py:1571-1579` 调用既有
  `claim_selected_outbox_deliveries` 后捕获所有 `Exception`，无论是 claim fence 冲突还是
  `OUTBOX_DELIVERY_CLAIM_FAILED` / rollback / SQLite 写故障，都统一改写为
  `OUTBOX_DELIVERY_EXACT_SET_DRIFT`。此外 `src/quant/execution/store.py:1539-1550` 也把读取时的
  `sqlite3.Error` 与真实 closure/row drift 合并为同一 code。service 在
  `src/quant/execution/service.py:771-778` 只能根据这个已经丢失的 store code 分类，因此 R3 的 service
  收窄映射无法恢复真实失败类型。
- **应遵循规则**：P4-R2 任务单冻结“只有全局集合新增/缺失/未来、LEASED/UNKNOWN 或真实 claim fence
  漂移才是 `SERVICE_EXACT_PENDING_SET_DRIFT`；store busy/事务失败保持稳定可重试边界”。P6 任务单将
  store busy/可重试瞬态失败固定为 exit 50，不能用 exit 20 暗示操作员确认内容发生变化。
- **最小复现**：stage A → exact set 为 `(A,)` → 创建 `BEFORE UPDATE OF state` trigger，在
  `NEW.state='LEASED'` 时执行 `RAISE(ABORT, ...)` → 调用
  `dispatch_exact_pending_commands((A,))`。当前结果为
  `SERVICE_EXACT_PENDING_SET_DRIFT, cause=None, context=None, gateway=0, delivery=PENDING/0`。
- **必须新增测试**：
  1. store exact claim 在集合验证通过后的 SQLite `UPDATE` 失败时保留稳定写/事务失败 code，并整体回滚；
  2. direct service 将该 code 映射为 `SERVICE_EXACT_PENDING_WRITE_FAILED`，断言 cause/context 为 `None`、
     gateway 0、delivery 无部分 claim；
  3. CLI 同构 post-confirmation 故障返回 exit 50 / `EXECUTION_RETRY_REQUIRED`；
  4. 保留真实 rowcount/fence 冲突和五类经济集合漂移仍为 exit 20，防止把 drift 泛化成 retry。
- **通过条件**：store 只把明确的 closure/set/fence 冲突归类为
  `OUTBOX_DELIVERY_EXACT_SET_DRIFT`；SQLite read/write、claim/rollback 和事务失败保留非 `DRIFT` 稳定
  code，使 service/CLI 分别得到 `SERVICE_EXACT_PENDING_WRITE_FAILED` 与 exit 50。所有路径均需整体
  rollback、gateway 0、无敏感异常链。

## 独立对抗证据

### 真实 writer lock（R2 原阻断项）

独立临时数据库、第二 SQLite 连接、真实 `BEGIN IMMEDIATE`：

```text
direct_code=SERVICE_EXACT_PENDING_WRITE_FAILED
direct_cause_none=true
direct_context_none=true
cli_exit=50
cli_stderr=EXECUTION_RETRY_REQUIRED
gateway_calls=0
recovery_unchanged=true
delivery_states=[[PENDING, 0]]
```

### 确认后集合漂移与旧 allowlist

```text
EXTRA   -> 20 CONFIRMATION_DRIFT gateway=0
MISSING -> 20 CONFIRMATION_DRIFT gateway=0
FUTURE  -> 20 CONFIRMATION_DRIFT gateway=0
LEASED  -> 20 CONFIRMATION_DRIFT gateway=0
UNKNOWN -> 20 CONFIRMATION_DRIFT gateway=0
ALLOWLIST -> claimed=1 gateway=1 states=[PENDING, SENT]
```

### 集合验证后的 SQLite claim 写故障

```text
code=SERVICE_EXACT_PENDING_SET_DRIFT
cause_none=true
context_none=true
gateway_calls=0
recovery_unchanged=true
deliveries=[[PENDING, 0]]
```

最后一组证明原子回滚和脱敏成立，但失败类型仍违反冻结合同。

## 验证命令与结果

环境均无网络、无 broker；每次 pytest 使用唯一 basetemp。

1. Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：
   - `pytest tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_execution_cli.py -q -p no:cacheprovider --basetemp .pytest-p6-r3-independent-20260808`
   - 结果：`262 passed, 5 skipped in 15.47s`。
2. Windows 定向 Ruff：store/service/CLI 与三份对应测试，结果 PASS。
3. Windows 定向 mypy：store/service/CLI，结果 `Success: no issues found in 3 source files`。
4. WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：
   - 对应三份测试结果：`266 passed, 1 skipped in 14.36s`；
   - 对应 Ruff PASS；mypy 3 files PASS。
5. 另运行三个独立无网络探针：真实 writer lock、五类集合漂移加旧 allowlist、SQLite claim 写入故障；
   结果分别如上一节所列。

## 范围与 Gate 边界

- 本轮未修改生产代码或实现者测试，只新增本独立复验报告；未执行 git add/commit。
- WSL 结果来自 `/mnt/f` DrvFS，只证明 WSL base 解释器与当前文件系统路径的定向兼容性，不等于 ext4/Linux
  平台 Gate。
- 本报告不关闭 P6、P8 四周 PAPER/SHADOW soak、broker live、ext4 Gate 或 M4 里程碑。
