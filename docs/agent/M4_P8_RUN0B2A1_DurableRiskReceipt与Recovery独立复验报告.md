# M4-P8-RUN-0B2A1 Durable Risk Receipt 与 Recovery 独立复验报告

状态：**FAIL，退回实现返工**  
日期：2026-08-09  
复验角色：未参与实现的全新独立只读复验  
权威合同：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery任务单.md)  
实现报告：[`M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery交付报告.md`](M4_P8_RUN0B2A1_DurableRiskReceipt与Recovery交付报告.md)

## 1. 结论

实现已建立 v006 同库 ORDER/CANCEL receipt journal，正常路径的混合 counter chain、原子回滚、
legacy 缺 receipt fail-closed、fresh codec 和 recovery outer identity 基础能力均存在；实现者的全部
定向测试也在 Windows 与 WSL base 通过。

但独立对抗复验证明三个冻结不变量尚未成立：

1. 低层 `RecoveryResult` 可接受与 commands/cancels 无关的额外 canonical receipt；
2. ORDER exact replay 可接受重签到错误 `risk_counter_key` 的 receipt，并返回健康 `replayed=True`；
3. `stage_cancel()` 把 SQLite `TX_BUSY` 误译为不可识别的 `CANCEL_STAGE_FAILED`。

这三项分别违反任务单 §5、§6 和 §4/§7，会直接污染后续 B2A2 的 command-risk exact
completeness，因此本轮不通过，不解锁 B2A2。

## 2. 必须返工的问题

### F1（阻断）：`RecoveryResult` 只验 receipt 自链，没有验证与 recovery 事实的 exact closure

**现象**

从合法单 ORDER recovery 出发，追加一条 sequence 连续、`previous_receipt_id` 正确、编码与自哈希
全部 canonical，但与现有 command/cancel 无关的空-command ORDER receipt；然后按实现的
`_recovery_identity()` 重算 outer identity。`RecoveryResult(...)` 成功构造：

```text
EXTRA_RECEIPT_ACCEPTED 1 2 ff5c7de2dc9310bcce381f6c533d8827611e3c0c657cb15e0588a047f8f0b61f
```

**根因**

`RecoveryResult.__post_init__()` 调用的 `_valid_recovery_receipts()` 只检查：exact runtime type、全局
sequence、previous receipt chain 以及 codec round-trip。它不检查：

- 每个 `RecoveryResult.commands` 是否恰好归属一条 ORDER receipt；
- 是否存在额外 ORDER command/intent/plan 所有者；
- 每个 `cancel_commands` 是否恰好归属一条 CANCEL receipt；
- receipt 内 plan/intent/command 顺序是否与 retained recovery facts exact。

`recover_local_state()` 内部 `_verify_risk_closure()` 做了其中大部分验证，但公共 frozen result 的
低层复制/重建边界没有重做可从 retained fields 证明的 closure，因而“exact verified receipt
tuple”可被转换成仅自洽的 receipt tuple。

**应遵循规则**

任务单 §6：`RecoveryResult.__post_init__` 必须 fresh 验证 exact type/order/identity，且非空 commands/
cancels 与 receipts 必须 exact closure，不得接受 missing/extra/duplicate/cross-plan risk。

**新增测试与通过条件**

- 基于合法 `RecoveryResult` 低层复制，分别测 missing ORDER、extra ORDER、extra CANCEL、receipt 与
  command/cancel 交换、跨 plan/intent、重复 owner、换序；
- 即使调用方按新 tuple 重算 outer `recovery_id`，上述非 exact closure 仍必须稳定
  `RECOVERY_RESULT_INVALID`；
- 可使用一个共享的纯函数同时服务 `_verify_risk_closure()` 与 `__post_init__`，但公共 result
  缺少 store-only counter/policy 字段时，不得伪造已验证结论；必要时应冻结窄 verified receipt
  container，不能只靠可任意构造的 tuple。

### F2（阻断）：ORDER exact replay 未绑定 counter key/transition closure

**现象**

完成一次合法 ORDER stage 后，保留原 private stage、commands 和 decision，仅将 ORDER receipt
重签为 `risk_counter_key="other-scope:2026-07-20"`，并同步更新表的 indexed metadata/payload。
再次调用同一 `plan_and_stage()` 得到：

```text
WRONG_COUNTER_KEY_REPLAY_ACCEPTED True other-scope:2026-07-20
```

此时 `recover_local_state()` 最终会因 counter rows 不闭合而拒绝，但已经返回健康
`StagedExecution(replayed=True)` 的 service 边界违反 exact replay fail-closed。

**根因**

`_require_order_receipt(row, risk)` 只对比 decoded ORDER decision 与 private stage 中的 risk fields，既不接收
应由 plan/session/scope 导出的 expected `risk_counter_key`，也不证明该 receipt 的 predecessor/
projected transition 仍在全局链和对应 counter-key 链中。

**应遵循规则**

任务单 §5：exact replay 必须要求 private stage、receipt、commands、counter identities 和 payload
全部 exact；receipt 缺失、额外、bytes/identity/counter/command 任一不一致均 fail closed。

**新增测试与通过条件**

- ORDER replay 必须显式传入并比较从 `self._risk_counter_scope + session_date` 导出的 expected key；
- 覆盖 wrong key、wrong predecessor/projected identity、合法重签但不在当前链、断链后 replay、
  ORDER/CANCEL 混合链中的旧 ORDER replay；
- replay 只有在 retained store snapshot 中的 receipt/counter/command closure exact 时才能返回
  `replayed=True`。

### F3（阻断）：CANCEL 竞争的 `TX_BUSY` 被误译为普通 stage failure

**现象**

两个已打开的 `ExecutionStore` 连接指向同一 SQLite。连接 A 持有 `BEGIN IMMEDIATE`，
连接 B 调用 `stage_cancel()`，公开结果为：

```text
CANCEL_BUSY_CODE ExecutionServiceError CANCEL_STAGE_FAILED None None
```

对照窄 store journal 的真实并发探针，同 predecessor 只有一个连接成功，另一个正确收到
`TX_BUSY`，稍后 fresh tail retry 可形成 sequence 2：

```text
CONCURRENT_RESULTS [(1, 'TX_BUSY'), (2, 'OK')]
RETRY_TAIL 2
```

**根因**

`stage_cancel()` 的最外层 `except Exception: pass` 把 `with self._store.transaction()` 进入时的
`StoreError("TX_BUSY")` 与其他未知异常合并映射为 `CANCEL_STAGE_FAILED`。调用方因而丢失任务单要求
保留的 retryable busy/CAS 边界。

**应遵循规则**

任务单 §4/§7：SQLite busy/事务失败必须保留既有可重试 store/service 语义，不得误译为
identity drift 或不可分类的普通 stage failure。

**新增测试与通过条件**

- ORDER/ORDER、CANCEL/CANCEL、ORDER/CANCEL 两连接真实同 predecessor 竞争，对 busy、CAS stale、
  fresh retry 分别断言稳定可重试码；
- commit 前 busy 零部分写；释放锁后 fresh retry 使用新 predecessor，无分叉、无丢计数；
- 错误仍必须 detached，且不泄露 path/SQL/TOKEN。

## 3. 其他合同核对

- ORDER/CANCEL 使用 exact-set 不同 decision field，跨 kind 字段与 duplicate JSON key 会被 codec
  拒绝；`transition_kind + subject_id` 与 receipt/sequence 在 v006 有唯一约束。
- 正常 `ORDER R1 → CANCEL C1 → ORDER R2` 同 key 路径可形成一条全局链和一条连续
  counter-key 链；任意缺 ORDER/CANCEL receipt 的 legacy closure 被 recovery fail closed。
- receipt/store/codec 实现中的 hostile 未知异常由固定公开码脱离原 cause/context；定向
  测试不显示 path、SQL、TOKEN 或 rule detail。
- whole-rehash 对抗：替换 canonical receipt 但保留旧 outer `recovery_id` 正确拒绝：
  `STALE_OUTER_REJECT RECOVERY_RESULT_INVALID`。同时，为全部内部事实与 outer identity 协调重算后可被接受：
  `COORDINATED_REHASH_ACCEPTED_BOUNDARY True`。后者正是任务单 §2 明示的同库信任边界，
  本报告不将它误判为 B2A1 缺陷，也不声称本包提供外部首次观察/来源防伪。
- v006 只创建新表，没有 backfill legacy row；本轮未触碰 P7/soak/CLI/broker/runtime/
  formal root，未联网、未 add/commit。

## 4. 独立验证证据

Windows 原生，`D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- 定向 pytest：`tests/unit/test_risk_wire.py tests/unit/test_execution_store.py tests/unit/test_execution_service.py tests/unit/test_reconcile.py`
  → **285 passed, 5 skipped**；
- 白名单 Ruff → **All checks passed**；
- 白名单生产 mypy → **Success: no issues found in 6 source files**；
- 四个独立内存/临时目录对抗探针分别覆盖：extra receipt 低层复制、wrong-key ORDER
  replay、真实双连接 busy/fresh retry、whole-rehash 旧 outer identity。

WSL Miniforge base，对应 `/mnt/f/.../m3-g8ab-prereq`：

- 同组定向 pytest → **290 passed**；
- 同组 Ruff → **All checks passed**；
- 同组生产 mypy → **Success: no issues found in 6 source files**；
- `findmnt -T /mnt/f` → `drvfs rw,noatime,uid=1000,gid=1000,case=off`。这只是 WSL/DrvFS 跨平台
  工程证据，**不是 WSL2/ext4 Gate**。

## 5. 返工闭环

实现者应以 F1–F3 的最小复现新增回归，并修复：

1. public `RecoveryResult` 的 retained command/cancel-risk exact closure；
2. ORDER replay 的 expected counter key 及完整 retained transition closure；
3. CANCEL busy/CAS 的可重试错误语义。

返工后必须由未参与该轮实现的新会话再次独立复验。在复验 PASS 与主 Agent 终验前，
RUN-0B2A1 仍为待验收，B2A2 不解锁，M4 仍为 `WAITING_FOR_SOAK_EVIDENCE`。
