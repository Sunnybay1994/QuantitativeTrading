# M4-B1A Session Barrier Substrate 交付报告

状态：`DELIVERY_READY / STATIC_ONLY / SUBSTRATE_ONLY / UA-M4-006 OPEN`

- task id：`M4-B1A-SESSION-BARRIER-SUBSTRATE`
- exact base：`c124ec57e254672cd371ea04a732515a59c2fad1`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1-shared-session-close-barrier`
- 终态上限：`SESSION_BARRIER_SUBSTRATE_VALIDATED`（**未**运行验证，不宣称已达）
- **不宣称**：all-writer closure、UA-M4-006、PAPER、28 日 soak、B1B

## 0. 返工记录

### 经理静态返工（R1–R3，已保持）

| 轮次 | 要点 | 状态 |
|---|---|---|
| R1 | 全字段 identity 重算；删除 old-root opt-in；OMS handle 取代 raw conn | 保持 |
| R2 | 连接进模块私有 registry；exact clone 需 registry | 保持 |
| R3 | token dataclass `eq=False` 身份键，防 WeakKeyDictionary 结构碰撞 | 保持 |

### 独立初验 REVIEW_FAIL 返工（本轮）

#### F1 P0 — frozen `_HeldBarrierLock` 释放赋值崩溃

| 项 | 内容 |
|---|---|
| 现象 | `_HeldBarrierLock` 为 `frozen=True`，`_release_barrier_lock` 写 `held.lock_fd = -1` → `FrozenInstanceError`，泄漏非 `SessionBarrierError` |
| 根因 | 持锁句柄误用 frozen dataclass |
| 规则 | 任务书 §5 锁生命周期可完成；§7 失败语义稳定脱敏 |
| 最小复现 | `with hold_session_barrier_lock(cap): pass` 退出时崩溃 |
| 修复 | `_HeldBarrierLock` 改为非 frozen `slots` dataclass；释放后清零 fd |
| 新增测试 | `test_hold_session_barrier_lock_release_completes_without_frozen_error` |
| 通过条件 | acquire→release 正常；`lock_fd == -1`；`hold_open_write_lease` 进出无 FrozenInstanceError |

#### F2 P1 — initialize/transition 与 writer 锁序相反

| 项 | 内容 |
|---|---|
| 现象 | store `transition_*` 先 `BEGIN` 再进 `transition_*` 内持 OS lock；writer 先 OS lock 再 BEGIN → 跨连接死锁序 |
| 根因 | 状态迁移未统一「锁覆盖 BEGIN…COMMIT」合同 |
| 规则 | 任务书 §5：先 anchored lock，再 fresh-read；锁覆盖完整事务 |
| 最小复现 | writer 持 OS lock+BEGIN；transition 已 BEGIN 等 OS lock |
| 修复 | `initialize_open_barrier` / `transition_*` 经 `_run_under_barrier_lock_transaction`：**OS lock → BEGIN IMMEDIATE → work → COMMIT/ROLLBACK → unlock**；store transition 不再外层 BEGIN；open 时 migration COMMIT 后再 bind/initialize（避免嵌套再取锁） |
| 新增测试 | `test_transition_acquires_barrier_lock_before_begin`；`test_writer_and_transition_lock_order_no_deadlock` |
| 通过条件 | 探针顺序 lock → begin → commit → unlock；并发限时结束且为 `BARRIER_WRITER_BUSY` 而非互卡 |

#### F3 P1 — §8.6 lock 对抗测试缺口

| 项 | 内容 |
|---|---|
| 现象 | 仅 symlink leaf；缺 hardlink / parent|leaf 替换 / object identity drift / Windows junction |
| 根因 | 测试意图未按 §8.6 写满 |
| 规则 | 任务书 §8.6 |
| 最小复现 | 静态检索无对应用例 |
| 修复 | 补测试（实现校验已存在） |
| 新增测试 | `test_lock_hardlink_rejected`；`test_lock_leaf_replaced_after_open_fails_revalidate`；`test_lock_parent_replaced_rejected`；`test_lock_object_identity_drift_rejected`；`test_lock_windows_junction_ancestor_rejected` |
| 通过条件 | 每类至少一条 fail-closed 码断言 |

#### F4 P1 — broker 写路径未逐一证明

| 项 | 内容 |
|---|---|
| 现象 | `test_broker_all_writers_require_open_lease` 未覆盖 `persist_operation` 与 `_sync_anchors` checkpoint UPDATE |
| 根因 | 抽样不足 |
| 规则 | 任务书 §6.2 / §8.12 |
| 最小复现 | 测试无上述调用 |
| 修复 | 扩展 broker 测试 |
| 新增测试 | OPEN：lease 探针覆盖 zero-command / persist / finalize / desync→`verify_fresh`（anchor UPDATE）；CLOSING/CLOSED：上述写与 `verify_fresh` 均 `BARRIER_STATE_*` |
| 通过条件 | Writer 覆盖表每入口有用例证据 |

#### F5 P2/对抗 — close vs 活跃 barrier 事务（跨线程，已保持）

| 项 | 内容 |
|---|---|
| 现象 | `close()` 不持 `_write_lock`，可与 `transaction()` 并发 invalidate handle / `conn.close()` |
| 根因 | close 与 writer 生命周期未互斥 |
| 规则 | 任务书 §5–§6；初验 §3 对抗反例 |
| 最小复现 | 线程 W 持 OPEN lease+BEGIN；线程 C `close()` |
| 修复 | `ExecutionStore.close` 跨线程 **blocking acquire `_write_lock`**，再 invalidate handle + close conn；记录 `_write_lock_owner` |
| 新增测试 | `test_concurrent_close_during_barrier_transaction_fail_closed`（保留） |
| 通过条件 | close 与 writer 串行；完成后 OS lock 可再获取；handle/conn 清空 |

#### F5b P0 — 同线程活跃 TX 内 `close()` 自死锁（复验新增，已保持）

| 项 | 内容 |
|---|---|
| 现象 | `close()` 对非可重入 `threading.Lock` 使用 `acquire(blocking=True)`；同线程已在 `transaction()`/`transition_*` 持锁时再 `close()` → 永久等待自己 → 自死锁；OS lease 也无法释放 |
| 根因 | 未区分写锁 owner 线程与跨线程等待者 |
| 规则 | 任务书 §5–§6；复验合同：同线程嵌套 close 须 fail-fast，禁止 hang；无部分提交/handle 误伤 |
| 最小复现 | `with store.transaction(): store.close()` 同线程永不返回 |
| 修复 | 跟踪 `_write_lock_owner`（`threading.get_ident()`）；`close()` 若 `owner == current` → 立即 `StoreError("CLOSE_DURING_TX")`，**不** invalidate handle、**不** `conn.close()`；跨线程仍 blocking 串行 |
| 新增测试 | `test_same_thread_close_inside_active_transaction_fail_fast_no_deadlock`（限时 2 秒内返回、码 `CLOSE_DURING_TX`、无 durable 行、handle 仍可 unpack、OS lock 可再持、随后正常 close） |
| 通过条件 | 无 hang；稳定码；无部分持久化/误 invalidate；跨线程 F5 测试不回退 |

### VALIDATION1 中央批准返工 — Windows `Path` exact-type guard

| 项 | 内容 |
|---|---|
| 现象 | VALIDATION1：import identity PASS 后 `test_session_barrier` **20 failed / 1 skipped**；`_require_absolute_path` 与 capability unpack 对合法 Windows absolute `Path` 失败 |
| 根因 | 两处使用 `type(value) is Path`；Windows 上 `Path()` 实际为 `WindowsPath`，exact 谓词永不成立 |
| 规则 | 中央最小修：两处仅接受当前平台 `type(Path())`（模块常量 `_CONCRETE_PATH_TYPE`）；保持绝对路径与既有 lock containment/symlink/reparse/identity；禁止 `isinstance` / 字符串转换；不得改迁移/事务/锁状态机 |
| 最小复现 | Windows：`build_session_barrier_capability(..., lock_root=Path(r'C:\...'))` → `BARRIER_LOCK_ROOT_INVALID`；证据见 validation1 stdout |
| 修复 | `_CONCRETE_PATH_TYPE = type(Path())`；`_require_absolute_path` 与 `unpack_session_barrier_capability` 的 `lock_root` guard 共用该常量 |
| 新增测试 | `test_lock_root_concrete_path_guards_native_and_rejects_nonconcrete` |
| 通过条件 | native absolute 双 guard 通过；subclass / Pure* / duck / relative 双 guard 拒绝；`co_names` 证明两 guard 引用同一常量 |
| evidence root | `artifacts/agent_runs/m4-b1a-validation1-20260825T204700295` |
| session stdout SHA | `6b5ef5b7b53e70ff3be16a1a68b7457d286881f0f11a5a36e3eae1a763a3110a` |

### VALIDATION2 中央批准返工 — 测试面（生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V2-F1 | `replace(capability/lease)` 测期望 `TypeError`，VALIDATION2 实得 `SessionBarrierError` | 校验环境 `dataclasses.replace` 走 `__init__`（`BARRIER_*_INVALID`），而非 `__replace__` 的 TypeError | 精确断言 `SessionBarrierError` + `BARRIER_CAPABILITY_INVALID` / `BARRIER_LEASE_INVALID`；copy/deepcopy/pickle 仍 TypeError；生产不变 | `replace(cap/lease, …)` | capability + lease replace 断言 | 码精确；序列化路径仍 TypeError |
| V2-F2 | 顺序测试 patch `conn.execute` 不可用/失败 | Connection.execute 非可靠可写观测点 | `set_trace_callback` 观察 BEGIN/COMMIT/ROLLBACK；仅 monkeypatch `hold_session_barrier_lock` | initialize/transition 顺序 | `test_transition_acquires_barrier_lock_before_begin` | lock→begin→commit→unlock |
| V2-F3 | writer 跨线程复用 handle/conn；隐含同线程亲和破坏 | lease owner + SQLite 线程约束 | writer 内自建 conn2、同线程 issue→lease→BEGIN；主线程仅 transition；禁止 `check_same_thread=False` | 双线程锁竞争 | `test_writer_and_transition_lock_order_no_deadlock` | BUSY 后可 CLOSING |
| V2-F5 | ready 前失败满等 5s 仅泛化 `AssertionError`；join 不证退出；cleanup 可二次掩盖；缺 issue/lease/BEGIN 反例 | 「未 ready」当超时断言；cleanup 非隔离；失败面未注入 | &lt;1s 暴露 `errors` 稳定码；短 join；成败均 `not is_alive()`；嵌套 try/finally 保证 `conn2.close` 且二次异常不覆盖主失败 | ready 前分别 boom issue / lease / BEGIN | 修 lock-order 成功路径 harness；新增三 pre-ready fail-fast 反例 + cleanup/await 辅助 | BUSY→CLOSING 仍成立；三码/线程退出/无泄漏；本轮 STATIC_ONLY 未跑 |
| V2-F6 | 三 pre-ready 用 `conn2.close = tracking_close`；先标 `closed` 再 close；cleanup 可进主 `errors` | 实例替换只读 native `close`；bookkeeping 顺序错；主/清理通道未隔离 | 禁止实例/monkeypatch 替换 `Connection.close`/`execute`；`closed` 仅在 unbound `sqlite3.Connection.close(conn2)` 成功返回后置位；失败进独立 `cleanup_errors`；模块函数注入可留 | 去掉 `close=` 后仍须 &lt;1s 主码 + handle/close 证明 | 修 cleanup 辅助与三 pre-ready；BUSY→CLOSING 保持 | 无 native 方法替换；主码精确；handle 清除；`closed` 成功后标记；cleanup 不冒充主码 |

### VALIDATION3 中央批准返工 — paper broker 测试面（生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V3 | `tracked_lease` 包裹并再入真实 `_barrier_lease`；持锁期观测可触碰 `verify_fresh`/`_sync_anchors` 属性 | 实例包装层强制二次进入真实 lease；放大非重入锁风险 | 删/换 `tracked_lease`；模块 `hold_open_write_lease` 边界观测；不改生产锁/不可重入/无假 lease；证明 writer 先取 OPEN lease；观测持锁期不读触发 sync 的属性；观测器不导致第二次 enter | 去包裹后 OPEN writer 与锚点 UPDATE 仍真实 enter 且 depth=1 | 重写 `test_broker_all_writers_require_open_lease` 观测；保留 CLOSING/CLOSED/identity/无 barrier | `max(depth)==1`；idle 0 enter；fail-closed 保留；生产未改 |

### VALIDATION4 production reentrancy STATIC_ONLY

| ID | 现象 | 根因 | 不变量 | 最小复现 | 规则 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|---|
| V4 | 持 OPEN lease 时 `_verify_barrier_lease` 读 public `gateway_identity` → fresh/sync/再取 lease | lease 内身份核对误走 public property | 持 lease 不用会 fresh/sync/再取 lease 的 public property；与 `_bound_gateway_identity` exact 比较；不删比较/不信任 bool/无可变缓存/不可重入/不吞 BARRIER；public fresh 不变；writer depth≤1（并发 exact1） | 持锁期 `gateway_identity` + 需 sync 锚点 → 嵌套 hold | bind 后绑定 private raw；verify 只比 raw；public 仍 fresh | `paper_broker_store.py` + `test_paper_broker_store.py`（depth/gw/drift/CLOSING/CLOSED/observer） | depth exact1；持锁无 public gw；drift fail-closed；STATIC_ONLY |

- evidence root：`artifacts/agent_runs/m4-b1a-validation4-20260825T153000Z-e84c`
- 04 stdout SHA：`1e6236f7e770993bfc4e384dc9cf1e9b78e27376b3653567e7ec9cbe1202c57e`
- 白名单本轮（VALIDATION4）：`paper_broker_store.py`、`test_paper_broker_store.py`、任务书 §9.6、本交付；review 只读

### VALIDATION5-FIXTURE STATIC_ONLY（execution_store 降级 fixture）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V5 | v3/v7 降级只改 `schema_version`、未 DROP 已有 `session_barrier`；reopen 真实 v009 `CREATE TABLE` → `MIGRATION_FAILED` | 降级 fixture 未清 v9 表；生产 v009 无 `IF NOT EXISTS` 且失败 fail-closed | 设旧 version 前 `DROP TABLE session_barrier`；不手工 indexes；不改 v009 / 不加 `IF NOT EXISTS` / 不吞 `MIGRATION_FAILED`；reopen 断言空表重建+未启用+旧数据保留 | 不 DROP 即降到 3/7 再 `_open` | `test_v3_upgrade_*`；`test_v7_database_upgrade_*` | `CURRENT`；`enabled is False`；`COUNT==0`；`BARRIER_MISSING`；legacy 断言保持 |

- evidence tag：`M4-B1A-VALIDATION5-FIXTURE`
- evidence root：`artifacts/agent_runs/m4-b1a-validation5-20260825T171500Z-b72d`
- 阶段结果（原生，不冒充整包 PASS）：identity / session17 / execution-targeted6 / broker-targeted4 **PASS**；full-three=**262 passed / 6 skipped / 2 failed**
- 05 stdout SHA：`FCF3989D22EC5B7DCA1C0F2292B7FFAE6CEC780937DE489D1C7B92DDD4657E4E`
- 05 stderr（empty）SHA：`E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`
- summary SHA：`085694369A74735F217ED7D81A382C85F6000CC37F6D5FB5614D7D069351A891`
- runner SHA：`E3A3CB737A260C29C4EF52986693D9AB75B3ACC9D12CC6FD4F8E0D474C408FBC`
- 白名单本轮：仅 `tests/unit/test_execution_store.py`、任务书 §9.7、本交付；production v009/store/review 只读
- 本轮 STATIC_ONLY 证据绑定**不**宣称整包 PASS（full-three 仍 2 failed）

### VALIDATION6-TYPE STATIC_ONLY（session_barrier 平台锁 / `_digest`）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V6 | focused+Ruff 绿，mypy 三错（`_IS_WIN32` 锁分支 + `_digest(object)`） | Final bool 非 platform 窄化；digest 宽于 `canonical_json_bytes` | 直接 `sys.platform == "win32"` + 惰性 msvcrt/fcntl；锁语义不变；无 Any/ignore；`_digest: Mapping[str, object]`；删无用 `_IS_WIN32`；不宣称 Linux Gate | mypy 三错于 apply/release/digest | 仅 `session_barrier.py`；Win/POSIX 测试保持 | 类型合同闭合意图；锁行为不变；STATIC_ONLY |

- focused SHA：`65BE40188EDE4CA5CF8CCB3C21517309F9C9143054C1119E20E5277B769E9835`
- Ruff SHA：`82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18`
- mypy SHA：`6C32100322FCACBCF6ECC7565CA6FFFCF69F67E749233F5F56E526CCBA7FAA25`
- summary SHA：`0A5259AC6AFDD31700E91EE5509F041BD462A7CE6E7BDA0CA641A57399FEC184`
- runner SHA：`0CCAA7DF14B5E5D24FF6E8DF331EAE122639A44ACBE20F2C1F9771E8234C3050`
- 白名单：仅 `session_barrier.py`、任务书 §9.8、本交付；**不**冒充整包/Linux Gate PASS

### EVIDENCE_DOC_CLOSE — 中央接受的组合证据（仅文档）

**状态：** Windows 开发验证闭合；仍 `SUBSTRATE_ONLY / UA-M4-006 OPEN`。<br>
**未验证：** formal all-writer / B1B / PAPER / soak / Linux Gate。

#### VALIDATION6（中央接受）

- execution-targeted6 **PASS**；broker-targeted4 **PASS**；full **264 passed / 6 skipped**；Ruff **PASS**

#### POSTFIX VALIDATION7

- evidence root：`artifacts/agent_runs/m4-b1a-postfix-validation7-20260825T181500Z-d91f`
- identity / session **24+1skip** / Ruff / mypy5 / cold / scope/diff/process：**全 PASS**
- 无 cache / temp / `0xF00` residue
- session SHA：`624E2A57945F90289F51546EDBCFEF6E9E5DF30FF6C4DEA22507689995E08D82`
- Ruff SHA：`82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18`
- mypy SHA：`718DF785EFBBD4B57E63B5F64AFF2C5B5592E433447681F759B307F97A3EC96A`
- cold SHA：`DCF12C4F22BE07B373EFBF84EC041120A94A1E80544C16CAF539D57F25FC5BF4`
- scope SHA：`97030AD4C8BC2E0EB148A8629737B5E169A2BC4A3FEB087AF6BAC7C0048B5281`
- summary SHA：`201F6D8148084C9D2034E20D9B92A65BB5F70AD35B86E685926D690B7E7CD372`
- runner SHA：`CE3E508955916213C0E127A06EADFBB218341E449DE463CD8FF66271D693D92D`

本轮仅文档绑定；未改 production/tests；未跑 Python/检查/提交。
## 1. 实现摘要

OMS v9 singleton barrier + `session_barrier.py`（状态机 / close token / anchored lock / identity-keyed registry / OPEN write lease）+ 两 store 可选接入。未配置 barrier 时 nonformal 行为保持。

## 2. 状态机 / durable row

`OPEN→CLOSING→CLOSED`；经济旧 root → `BARRIER_OLD_ROOT_REFUSED`（无 opt-in）。

## 3. Lock / lease / handle 生命周期

```
initialize / transition_* / writer:
  OS lock → BEGIN IMMEDIATE → fresh state/work → COMMIT|ROLLBACK → unlock
  （同一路径不嵌套再取锁）

mint capability/handle/lease → eq=False identity registry（conn 仅 handle binding）
close(store):
  if _write_lock_owner == this thread → StoreError(CLOSE_DURING_TX) (no mutate)
  else acquire _write_lock → invalidate handle → conn.close
```

## 4. Writer 覆盖表

| 入口 | OPEN | CLOSING/CLOSED |
|---|---|---|
| ExecutionStore.transaction | lease+写 | 拒 |
| ExecutionStore.transition_* | lock→BEGIN→… | 幂等/冲突码 |
| broker.persist_operation | lease（探针） | `BARRIER_STATE_*` |
| broker.record_zero_broker_command_session_finality | 成功+lease | 拒 |
| broker.finalize_session | lease（探针） | 拒 |
| broker._sync_anchors checkpoint UPDATE | desync→verify_fresh+lease | 拒 |

## 5. 错误码

既有码；锁忙 `BARRIER_WRITER_BUSY`；handle/lease 失效 `BARRIER_OMS_HANDLE_INVALID` / `BARRIER_LEASE_INVALID`；同线程嵌套 close `CLOSE_DURING_TX`。

## 6. 反例（已写，STATIC_ONLY 未跑）

§8 十二条意图 + R1–R3 + 初验 F1–F5 + F5b + VALIDATION1–6 + **POSTFIX VALIDATION7 中央接受（Windows 开发验证闭合）**。

## 7. exact11 文件

本轮 EVIDENCE_DOC_CLOSE：仅任务书（§9.9）、本交付报告。production / tests / review **字节未改**。

## 8. 未运行项

本轮未运行 Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER / stage / commit。证据以中央 VALIDATION6 组合与 POSTFIX VALIDATION7 root `m4-b1a-postfix-validation7-20260825T181500Z-d91f` 为准。

## 9. 风险与边界

- Windows 开发验证已闭合；**仍** `SUBSTRATE_ONLY / UA-M4-006 OPEN`。
- **未**验证：formal all-writer / B1B / PAPER / soak / Linux Gate。
- 可信进程反射模块私有 registry 仍可能（已声明）。
