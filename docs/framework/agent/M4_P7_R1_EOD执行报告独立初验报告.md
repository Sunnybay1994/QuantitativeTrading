# M4-P7-R1 EOD 执行报告独立初验报告

日期：2026-08-02  
角色：未参与实现的只读独立初验  
结论：**FAIL**

本结论只针对 P7 工程合同；不关闭 EOD reconcile Gate、PAPER soak 或 M4。初验期间生产代码和
`tests/unit/test_execution_report.py` 保持只读，唯一持久交付为本报告。

## 验收摘要

实现者定向测试与静态检查均绿色：

```text
Windows D:\Miniforge3\python.exe
pytest -p no:cacheprovider tests/unit/test_execution_report.py -q --basetemp=artifacts/p7-review
7 passed in 3.31s

ruff check src/quant/reporting/execution_report.py src/quant/reporting/__init__.py tests/unit/test_execution_report.py
All checks passed!

mypy src/quant/reporting/execution_report.py src/quant/reporting/__init__.py
Success: no issues found in 2 source files
```

已有测试证明了普通输入的确定编码、逆序 risk 规则、broker order ID/risk detail 脱敏、明显 identity 漂移、
risk command 不属于 recovery、重复 plan、零 I/O，以及未同步更新 `report_id` 的冻结对象 mutation。不过，新增的
自洽哈希对抗探针稳定暴露以下两个阻塞问题。

## 阻塞问题 1：自洽 hash 可把 mutation 后的敏感原文编码出去

### 现象

对 builder 返回的 frozen `ExecutionOrderLine` 使用 `object.__setattr__` 将 `symbol` 改成
`TOKEN C:\\private\\account.db`，随后按公开冻结 canonical 规则重算 `report_id`。`encode_execution_report()`
接受该对象，输出 bytes 同时包含 `TOKEN` 和 `private`：

```text
SELF_CONSISTENT_MUTATION_ACCEPTED True True TOKEN C:\private\account.db
```

这违反任务单“冻结对象被 mutation 必须拒绝”以及输出不得包含 token、绝对路径的合同。

### 根因

- `encode_execution_report()` 在 `src/quant/reporting/execution_report.py:278-304` 只用报告自身字段重新构造
  `ExecutionReport`；没有任何 builder 来源闭包可供重新验证。
- `_valid_report()` 在 `src/quant/reporting/execution_report.py:463-614` 对 `symbol/market/side/status` 等只检查
  非空文本，其中 symbol 的检查位于 `:504`。
- `_report_identity()` 在 `:616` 是无密钥内容 hash；攻击者修改字段后可按同一 canonical 规则生成新的自洽 hash。
  内容寻址证明内容未意外漂移，不证明该内容来自已验证的 recovery。
- 现有测试 `tests/unit/test_execution_report.py:236` 只修改 `gate_passed` 而不重算 `report_id`，没有覆盖任务单要求的
  “手工构造自洽 hash”反例。

### 最小复现

1. 用 `_filled_inputs` 构造正常报告。
2. `object.__setattr__(report.orders[0], "symbol", r"TOKEN C:\\private\\account.db")`。
3. 按冻结 payload/canonical JSON 规则重算 SHA-256，并同步写入 `report.report_id`。
4. 调用 encoder；实际成功且原文进入 bytes。

### 应遵循规则与通过条件

encoder 必须能区分“builder 对已验证输入生成的报告”和“调用方手工拼装/修改后重算 hash 的报告”；仅重算无密钥
content hash 不足以建立该来源闭包。返工设计需先明确可复验的 provenance/factory 边界，并对所有会原样输出的文本
执行领域级验证。新增测试必须按上述步骤重算自洽 hash，仍得到脱敏、无 cause/context 的
`EXECUTION_REPORT_INVALID`，且 hostile 原文不在异常对象图中。

## 阻塞问题 2：自洽 RecoveryResult 中的重复 command ID 被静默折叠

### 现象

独立探针手工构造包含同一 canonical command 两次的 `RecoveryResult`，按 recovery 的冻结 canonical 算法生成匹配
`recovery_id`，并同步构造匹配该 recovery 的自洽 `ReconciliationResult`。两种输入类型的 `__post_init__` 都接受；
P7 builder 也接受，并把两个输入 command 静默折叠为一个 order：

```text
DUPLICATE_COMMAND_ACCEPTED 2 1 b83bae90974db982b49e5d0f02e89f150575dea4134b994c397fc1022e30ac4f
```

这直接违反任务单“重复 id 拒绝”和 totals 不得掩盖输入闭包破坏的合同。

### 根因

- `_verify_recovery()` 在 `src/quant/reporting/execution_report.py:311-328` 通过重建 `RecoveryResult` 验证顶层 hash，
  但没有单独检查 command/event/aggregate 等序列的唯一性与冻结顺序。
- builder 在 `:150` 直接使用 dict comprehension：
  `commands = {item.command_id: item for item in checked_recovery.commands}`，因此重复 key 在任何显式检查前已丢失。
- 后续 `set(commands) == set(aggregates)` 只比较折叠后的 key 集合，无法恢复重复事实。

### 最小复现

1. 从正常 filled recovery 取唯一 command，并令 `commands=(command, command)`；其余 recovery 字段保持不变。
2. 按 recovery canonical identity 算法计算新的 `recovery_id`，构造 `RecoveryResult`。
3. 用新 recovery ID 重算 `ReconciliationResult.reconciliation_id`。
4. 调用 builder；实际返回 `len(recovery.commands)==2`、`report.totals.commands==1`。

### 应遵循规则与通过条件

在任何 dict/set 映射前，对 recovery 的 commands、events、aggregates、deliveries、ledger entries/contexts 等冻结序列逐项
调用现有 public verifier，并显式检查唯一 ID、冻结排序及 command 引用闭包。至少新增“自洽 recovery hash + duplicate
command ID”测试，必须稳定返回 `EXECUTION_REPORT_INVALID`，异常 cause/context/object graph 不保留输入。

## 已核对的非阻塞项

- 正常 builder 与 encoder 不直接 import/open store、broker、socket 或文件；已有 monkeypatch 测试证明零 I/O。
- order 的 broker order ID、risk subject/detail 以及 reconciliation difference subject 在正常 builder 路径只输出 SHA-256
  身份或完全省略；difference subject 映射位于 builder 的 `_text_identity(item.subject)`。
- fills、orders、risk lines 的正常路径显式排序；canonical JSON 使用 UTF-8、sorted keys、紧凑 separators、禁止 NaN且无换行。
- risk command 不属于 recovery 与重复 plan 的现有测试能够拒绝。

由于上述两项反例均突破冻结任务单的核心输入闭包和脱敏要求，P7-R1 本轮不得进入主验通过状态；应返工后由同一独立
初验角色复验新增对抗用例及 Windows/WSL 定向结果。

---

## R1 返工复验（2026-08-02）

复验角色与原初验相同，生产代码和实现者测试继续只读。R1 结论：**FAIL**。

### 原阻塞关闭情况

两项原始最小复现均已原样重放并得到拒绝：

```text
ORIGINAL_1 REJECTED
ORIGINAL_2 REJECTED
```

- 报告行的 symbol/market/side/status/currency 及 rule/code 已按领域枚举或受限格式重新验证；修改 frozen line 后即使同步
  重算自洽 `report_id`，encoder 仍返回 `EXECUTION_REPORT_INVALID`。
- builder 已在 dict 映射前检查 command、aggregate、event 的冻结排序和唯一 ID，并重算 command/event identity；自洽
  recovery/reconciliation hash 不再掩盖重复 command ID。
- 新增的两个实现者回归测试与原复现一致。

Windows R1 定向结果：

```text
pytest -p no:cacheprovider tests/unit/test_execution_report.py -q --basetemp=artifacts/p7-r1-review-tests
9 passed in 4.00s

ruff check src/quant/reporting/execution_report.py src/quant/reporting/__init__.py tests/unit/test_execution_report.py
All checks passed!

mypy src/quant/reporting/execution_report.py src/quant/reporting/__init__.py
Success: no issues found in 2 source files
```

### R1 新阻塞：aggregate 没有按 retained events 重放 reducer 闭包

#### 现象

从合法 filled recovery 构造一个结构上合法的 `OrderAggregate`：保留原 command ID、broker order ID、两个
`applied_event_ids` 和 `last_event_at`，但将状态改为 `SUBMITTED`、`filled_quantity=0`。随后重算自洽
`recovery_id`，并同步重算 reconciliation 的 local recovery ID 与 `reconciliation_id`。builder 接受该输入，产生内部互相
矛盾的报告：order 声称 `SUBMITTED/filled=0`，fill 明细却有两条成交事件。

```text
REDUCER_DIVERGENCE ACCEPTED SUBMITTED 0 2
```

#### 根因

- 任务单要求所有输入先重验现有 public identity/**reducer** 不变量。
- builder 在 `src/quant/reporting/execution_report.py:166-175` 只检查 aggregate ID 的排序、唯一性、command key 集合，并调用
  `_verify_aggregate()`。
- `_verify_aggregate()`（`:367`）仅以当前字段重建 `OrderAggregate`，所以只能验证单对象的结构/跨字段约束；代码没有导入或
  调用 `new_order_aggregate()`、`reduce_order()`，也没有按 `applied_event_ids` 将 recovery events 重放后与持久 aggregate
  比较。
- event 的 identity、唯一性和 command membership 在 `:199-206` 单独验证，但这不足以证明 aggregate 是这些 events 的
  reducer 结果。

#### 最小复现

1. 取得包含 ACCEPTED/PARTIAL_FILL/FILL 的正常 recovery。
2. 用同一 command 构造 `OrderAggregate(status=SUBMITTED, filled_quantity=0, broker_order_id=原值,
   applied_event_ids=原值, last_event_at=原值)`。
3. 替换 recovery aggregate，并按冻结算法重算 recovery/reconciliation identities。
4. 调用 builder；实际成功且返回 `status=SUBMITTED`、`filled_quantity=0`、`totals.fills=2`。

#### 应遵循规则与通过条件

在生成报告行前，按每个 aggregate 的 `applied_event_ids` 从 recovery event map 取事件，以对应 command 调用
`new_order_aggregate()` 后逐项 `reduce_order()`；最终 reducer 结果必须与 recovery aggregate 完全一致。还应拒绝 aggregate
引用缺失、跨 command、重复或未按其冻结 reducer 顺序闭合的 event ID。

新增回归测试必须使用上述“自洽 hash + 结构合法但 reducer 不一致”的 aggregate，稳定得到脱敏且无 cause/context 的
`EXECUTION_REPORT_INVALID`；正常 CREATED、部分成交、完全成交与重复 callback 幂等路径仍须通过。

因此，虽然原两项阻塞已关闭，P7 R1 尚未满足冻结任务单的 reducer 闭包，仍不得进入主验通过状态。

---

## R2 返工复验（2026-08-02）

复验角色与前两轮相同，生产代码与实现者测试保持只读。R2 结论：**PASS**。

### R1 新阻塞关闭证据

builder 现建立完整 command → retained events → aggregate 闭包：

- commands、aggregates、events 在映射前分别要求冻结排序且 ID 唯一；command/event 重算 public identity。
- 对每个 command 从 `new_order_aggregate(command)` 开始，严格按该 aggregate 的 `applied_event_ids` 查找 retained event，
  校验 command membership 后逐项调用 `reduce_order()`。
- reducer 最终投影必须逐值等于 recovery aggregate。
- 所有 aggregate 消费的 event ID 排序后必须与全部 retained event ID 精确相等，因此缺失、跨 command、重复消费和孤儿
  retained event 均失败。

原 R1 自洽 aggregate 漂移探针现稳定拒绝，且异常脱离 hostile context：

```text
R1_REDUCER_DIVERGENCE REJECTED True True
```

新增一个实现者未使用的对抗变体：保留 recovery 中 ACCEPTED/PARTIAL_FILL/FILL 全部 events，但 aggregate 只从 genesis
消费 ACCEPTED，形成结构正确且 reducer 自洽的 `SUBMITTED` 投影；同步重算 recovery/reconciliation identities。该输入仍因
其余 retained fill events 未被任何 aggregate 消费而拒绝：

```text
ORPHAN_RETAINED_EVENTS REJECTED True True
```

两个布尔值分别证明 `ExecutionReportError.__cause__ is None` 与 `__context__ is None`。

### R2 验证结果

```text
Windows D:\Miniforge3\python.exe
pytest -p no:cacheprovider tests/unit/test_execution_report.py -q --basetemp=artifacts/p7-r2-review-tests
10 passed in 3.49s

ruff check src/quant/reporting/execution_report.py src/quant/reporting/__init__.py tests/unit/test_execution_report.py
All checks passed!

mypy src/quant/reporting/execution_report.py src/quant/reporting/__init__.py
Success: no issues found in 2 source files
```

### 最终边界

R2 已关闭原报告的两项阻塞以及 R1 新增 reducer 闭包阻塞，正常确定性、canonical bytes、脱敏、顺序、空/filled ledger、
Gate false 视图与零 I/O 回归继续通过。因此 M4-P7-R1 的 Windows 工程独立初验通过，可进入主 Agent 最终验收。

本 PASS 不代表 WSL/Linux Gate 已验证，也不关闭正式 EOD reconcile Gate、PAPER soak 或 M4；这些状态仍由对应平台验证和
后续里程碑验收决定。
