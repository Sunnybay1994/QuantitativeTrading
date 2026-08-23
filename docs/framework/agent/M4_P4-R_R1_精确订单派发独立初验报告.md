# M4-P4-R-R1 精确订单派发独立初验报告

日期：2026-08-02  
角色：未参与实现的独立初验  
结论：**PASS（仅关闭 P4-R 工程前置；不关闭 P6、P8、PAPER soak、WSL Gate 或 M4）**

## 1. 复验范围与边界

依据 [`M4_P4-R_R1_精确订单派发任务单.md`](M4_P4-R_R1_精确订单派发任务单.md)，只读复核：

- `src/quant/execution/store.py`
- `src/quant/execution/service.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_execution_service.py`
- [`M4_P4-R_R1_精确订单派发交付报告.md`](M4_P4-R_R1_精确订单派发交付报告.md)

初验未修改生产代码或实现者测试，只新增本报告。工作树原有 P5/P6/P7 等并行变更及未跟踪测试目录均予保留。

## 2. 冻结合同逐项核对

### 2.1 Store 精确领取与全批原子性

- `claim_selected_outbox_deliveries` 要求 `command_ids` 为非空 tuple、严格字典序且唯一；每项经 canonical
  64 位小写十六进制 identity 校验。
- 调用方通过 `ExecutionStore.transaction()` 持有 `BEGIN IMMEDIATE`。方法在第一条写入前逐个检查 selected
  command、outbox、delivery、aggregate 的 join 闭包，并显式核对 command/outbox key、identity、payload 与
  delivery 的一一绑定。
- selected 只接受 ready `PENDING`，或 `lease_until < now` 的 `LEASED`；精确到期边界
  `lease_until == now` 明确仍不可领取，符合任务单“严格过期”语义。
- 全部预检后才建立 savepoint 并逐行 CAS；任一 rowcount 非 1 或后置读取失败都会回滚整个 savepoint。
  返回值按输入 candidates 顺序构造，未使用全局 ready 查询或 limit 推断确认集合。

### 2.2 Service 精确派发与失败脱敏

- `dispatch_commands` 在进入 store 前验证非空、排序、唯一、canonical command ID；非法选择固定返回
  `SERVICE_COMMAND_SELECTION_INVALID`。
- store/SQLite/竞态/闭包失败统一翻译为 `SERVICE_SELECTED_CLAIM_FAILED`，并清除 cause/context；输入 ID、
  payload、底层异常和主机路径不进入稳定异常对象。
- selected claim 结果直接传给 `_dispatch_claimed`，没有回退调用 `claim_outbox_deliveries` 或
  `dispatch_pending(limit)`。
- `dispatch_pending` 和 `dispatch_commands` 均以同一条
  `return self._dispatch_claimed(claimed, lease_until=lease_until)` 进入 gateway fence、certainty、OMS、ledger
  与 callback transaction；没有第二套 reducer 或回调写入实现。

### 2.3 保持的边界

- 本包没有新增 live gateway、SDK、cancel、broker query 或 CLI 分支。
- `dispatch_pending(limit)` 的全局 worker 领取语义保持原实现；精确 selected 的严格 `< now` 没有反向改变
  全局恢复 worker 原有 `<= now` 语义。
- P5 ledger callback 变更与 P7 v005 cancel migration 已在同一 dev worktree 合流，但精确派发仍复用唯一
  callback path，selected command/outbox 的稳定字节和身份合同未被另起一套实现。

## 3. 独立新增对抗反例

以下均为一次性、无落盘测试源码的独立运行探针，未写入实现者测试文件：

1. **确认集合外并发新增**：两个线程同时启动 selected A/B 派发与另一连接新增 C；SQLite writer busy 时新增方
   受控重试。最终 gateway 顺序精确等于 A/B，C 保持 `PENDING`、`attempt_count=0`。
2. **精确到期边界**：先领取 selected A，再以 `now == A.lease_until` 由另一 worker 精确领取；固定拒绝
   `OUTBOX_DELIVERY_SELECTED_UNCLAIMABLE`，原 lease 全字段不变。
3. **真实两连接竞争**：两个独立 `ExecutionStore`、两个 worker、两个 gateway 经 barrier 同时派发同一 exact
   set；恰有一个返回成功，另一个返回 `SERVICE_SELECTED_CLAIM_FAILED`，gateway 合计每个 selected command
   只出现一次，无重复经济回调。
4. **selected identity/payload 断链**：离线同时漂移一个 selected command 的 canonical identity 与 payload；
   整批固定失败，另一 ready 成员仍为 `PENDING/attempt_count=0`，gateway 零调用。
5. **异常 context 脱敏**：在 repository claim seam 注入含 `TOKEN` 与私有 Windows 路径的底层异常；service
   仅暴露 `SERVICE_SELECTED_CLAIM_FAILED`，`cause is None`、`context is None`、suppress context 为真，异常对象
   图不含 token 或路径。
6. **共用回调路径**：对两个公共方法读取实际函数源码，均只通过同一 `_dispatch_claimed` 返回；完整 service
   回归同时覆盖 SENT/UNKNOWN/NOT_SENT、gateway fence、ledger checkpoint 与 callback transaction。

独立探针输出：

```text
P4R_BOUNDARY_PASS
P4R_SCRUB_PASS
P4R_DRIFT_PASS
P4R_TWO_CONNECTION_RACE_PASS
P4R_CONCURRENT_OUTSIDE_PASS
P4R_SHARED_CALLBACK_PATH_PASS
```

## 4. 验证结果

### 4.1 Windows 原生 Miniforge

工作目录：`artifacts/dev_worktrees/m3-g8ab-prereq`，解释器：`D:\Miniforge3\python.exe`。

```text
python -m ruff check src/quant/execution/store.py src/quant/execution/service.py \
  tests/unit/test_execution_store.py tests/unit/test_execution_service.py
All checks passed!

python -m mypy src/quant/execution/store.py src/quant/execution/service.py
Success: no issues found in 2 source files

PYTHONPATH=src python -m pytest -p no:cacheprovider \
  tests/unit/test_execution_store.py tests/unit/test_execution_service.py -q \
  --basetemp=artifacts/p4r-independent-review-final2
230 passed, 5 skipped in 11.94s
```

5 个 skip 均为既有平台能力条件分支；本次 P4-R selected dispatch、双 worker、callback/recovery 回归没有被跳过。

### 4.2 并行合流中间态说明

初验期间曾观测到 P7 v005 migration 已进入注册表而 `CURRENT_SCHEMA_VERSION` 尚为 4 的短暂并行中间态，导致
`UNKNOWN_SCHEMA_VERSION`；同步 version=5 后，旧 v3 升级 fixture 又因残留 v5 表及硬编码 `==4` 各失败一次。
主任务随后把 fixture 修正为真实 v3 物理状态并断言 `CURRENT_SCHEMA_VERSION`。上述均是白名单外 v5 合流时序，
最终稳定态已按上方命令全量重跑绿色，未据中间态误判 P4-R。

### 4.3 WSL base

对应定向命令只尝试一次，WSL 在创建发行版实例前返回：

```text
Wsl/Service/CreateInstance/E_ACCESSDENIED
```

因此没有 Linux/WSL base 测试结果。Windows 绿色只证明本包的 Windows 工程合同，不替代 Linux、ext4 或任何
平台特有 Gate。

## 5. 最终判定

P4-R 的 exact allowlist、严格 lease 边界、全批 rollback、集合外隔离、双连接竞争、稳定脱敏失败以及唯一
callback path 均有代码证据与独立反例支撑；Windows 定向静态检查和完整两文件回归绿色。独立初验结论为
**PASS**，可进入主 Agent 最终验收。

仍保留的边界：WSL base 未执行；本结论不代表 P6 CLI、P8、PAPER soak、真实 broker、Linux Gate 或 M4 已完成。
