# M4-B1A Session Barrier Substrate 独立初验报告

状态：`DOC_REVIEW_PASS / STATIC_ONLY / SUBSTRATE_ONLY / UA-M4-006 OPEN`

- task id：`M4-B1A-SESSION-BARRIER-SUBSTRATE`
- exact base：`c124ec57e254672cd371ea04a732515a59c2fad1`
- branch / worktree：`codex/m4-b1-shared-session-close-barrier` @ 任务书指定路径
- 审查角色：未参与实现的**第六名**独立静态复验 Agent（续任；DOC_NORMALIZATION_REVIEW_ONLY；只读 exact11/task/delivery/evidence；本报告为唯一可写路径）
- 终态上限：不得宣称 `SESSION_BARRIER_SUBSTRATE_VALIDATED`、Linux Gate、formal all-writer、B1B、PAPER/soak、整包 PASS、UA-M4-006 关闭
- 绑定文档 SHA（DOC 规范化后只读重算）：task=`1CFBCECA40A4E5CD93061438E7F2544898C4709A6F57A63F7D4FA656924D4152`；delivery=`59D045C3A7BB07233988F8844AAA274A9EE018A385FA42EAA2A0E83804178065`

---

## A. 初验历史（REVIEW_FAIL，保留）

以下为返工前独立初验原文裁决与 findings，供对照；**不**因后续复验删除。

### A.0 审查范围与方法（初验）

只读核对：

- `docs/framework/tasks/M4_B1A_SessionBarrierSubstrate任务书.md`
- `docs/framework/deliveries/M4_B1A_SessionBarrierSubstrate交付报告.md`
- exact11 相对 `c124ec57…` 的实现/测试 diff 与新增文件全文静态阅读

**全部未运行（STATIC_ONLY）：** Python import、pytest、Ruff、mypy、SQLite probe、cold import、网络、浏览器、真实 I/O、commit。

### A.1 初验裁决

**`REVIEW_FAIL`** — 至少 1×P0、多个 P1；在修复并复验前不得进入中央 CPU 验证申请。

### A.2 初验 Findings（按严重性）

#### [P0] `_HeldBarrierLock` 为 frozen，释放路径赋值必然崩溃 — `src/quant/execution/session_barrier.py:231-240,1237-1257`

| 项 | 内容 |
|---|---|
| 现象 | `_HeldBarrierLock` 声明 `@dataclass(frozen=True, slots=True)`，但 `_release_barrier_lock` 在关闭 fd 后执行 `held.lock_fd = -1` / `held.dir_fd = -1`。静态上每次成功释放都会触发 `FrozenInstanceError`。 |
| 根因 | 持锁对象误用 frozen dataclass，却按可变句柄语义清零 fd。 |
| 规则 | 任务书 §5；§7。 |
| 最小复现 | `with hold_session_barrier_lock(cap): pass` 退出时崩溃。 |
| 新增测试 | `test_hold_session_barrier_lock_release_completes_without_frozen_error`。 |
| 通过条件 | 锁释放不再触碰 frozen 赋值；错误面无 `FrozenInstanceError`。 |

#### [P1] 状态迁移路径「先 BEGIN 后持 barrier lock」— `store.py` + `session_barrier.py`

| 项 | 内容 |
|---|---|
| 现象 | `transition_*` / `initialize_open_barrier` 与 writer 锁序相反，可跨连接死锁。 |
| 根因 | 未统一「锁覆盖 BEGIN…COMMIT」合同。 |
| 规则 | 任务书 §5。 |
| 新增测试 | `test_transition_acquires_barrier_lock_before_begin`；`test_writer_and_transition_lock_order_no_deadlock`。 |
| 通过条件 | 统一 OS lock → BEGIN → … → COMMIT/ROLLBACK → unlock。 |

#### [P1] §8.6 lock 对抗面测试意图不完整 — `tests/unit/test_session_barrier.py`

| 项 | 内容 |
|---|---|
| 现象 | 仅 symlink leaf；缺 hardlink / parent|leaf 替换 / object identity drift / Windows junction。 |
| 规则 | 任务书 §8.6。 |
| 通过条件 | §8.6 每类至少一条失败码断言。 |

#### [P1] §8.12 broker「所有写方法」未逐一证明 — `tests/unit/test_paper_broker_store.py`

| 项 | 内容 |
|---|---|
| 现象 | 未覆盖 `persist_operation` 与 `_sync_anchors` checkpoint UPDATE。 |
| 规则 | 任务书 §6.2 / §8.12。 |
| 通过条件 | Writer 覆盖表每一 broker 写入口均有用例证据。 |

#### [P2] `ExecutionStore.close` 不持 `_write_lock`，可与活跃 barrier 事务并发撕 handle/连接 — `store.py`

| 项 | 内容 |
|---|---|
| 现象 | `close()` 直接 invalidate + `conn.close()`，不获取 `_write_lock`。 |
| 对抗反例 | 活跃 OPEN lease 期间并发 `store.close()`（跨线程）。 |
| 通过条件 | close 与 writer 互斥或明确 fail-closed；无已提交经济行；不泄漏非稳定异常。 |

### A.3 初验对抗性反例（跨线程 close-vs-writer）

活跃 OPEN lease 期间**另一线程**调用 `store.close()`：不得提交经济写；lease/handle 失效；稳定 `StoreError`；barrier 仍 OPEN；OS lock 可再获取。

### A.4 初验 REVIEW_READY 摘要

```
REVIEW_READY
verdict: REVIEW_FAIL
p0: 1 (frozen _HeldBarrierLock release)
p1: 3 (lock-vs-BEGIN order; §8.6; §8.12 broker writers)
adversarial_new: concurrent store.close vs active OPEN lease (cross-thread)
```

---

## B. RE-REVIEW 历史（F1–F5 返工后，REVIEW_FAIL，保留）

以下为第二名独立复验对 F5b 同线程自死锁的裁决；**本轮不删除**，仅作历史对照。

### B.1 复验裁决（历史）

**`REVIEW_FAIL`** — F1–F4 与跨线程 F5 意图静态闭合；但 F5 返工使同线程活跃 TX 内 `close()` 对非可重入 `_write_lock` `acquire(blocking=True)` → 自死锁（1×P0）。

### B.2 历史 Findings

#### [P0] 同线程活跃事务内 `store.close()` 自死锁 — `store.py`（当时）

| 项 | 内容 |
|---|---|
| 现象 | `close()` 无条件 `acquire(blocking=True)`；同线程已持 `_write_lock` 时永久等待自己。 |
| 通过条件 | 同线程 fail-fast（稳定码）；跨线程仍串行；无部分 durable 写；无误 invalidate。 |

### B.3 历史对抗反例

同线程 `store.close()` 嵌套于活跃 `transaction()` —— 必须限时返回、稳定码、无 hang。

### B.4 历史 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_FAIL
phase: RE-REVIEW after F1-F5 rework
p0: 1 (same-thread close self-deadlock)
```

---

## C. RE-RE-REVIEW（F5b 修复后，本轮第三名独立静态初验）

### C.0 范围与方法

只读核对（相对 exact base `c124ec57…` 的 exact11）：

1. 任务书、交付报告（含 F1–F5b 返工记录）
2. §A / §B 历史 findings（上文）
3. 生产：`session_barrier.py`、`v009_session_barrier.py`、`migrations/__init__.py`、`store.py`、`paper_broker_store.py`
4. 测试：`test_session_barrier.py`、`test_execution_store.py`、`test_paper_broker_store.py`

**重点对抗：** F5b — 同线程 `CLOSE_DURING_TX`、跨线程 close 串行、`_write_lock_owner` 登记/清除、无 stale owner / 双释放 / 逃逸；并快速确认 F1–F5 未回归。

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / SQLite / network / browser / commit。本结论仅为敌意静态复验，不构成运行验证通过，亦不宣称 `SESSION_BARRIER_SUBSTRATE_VALIDATED`。

### C.1 本轮裁决

**`REVIEW_PASS`**

F5b 同线程 fail-fast 与跨线程串行在静态控制流上闭合；owner 仅在成功持锁后登记，异常/`finally` 路径清除；F1–F5 先前闭合点未见回归。无新增 P0/P1。可进入经理申请中央串行 CPU 验证的前置（仍为 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`）。

### C.2 F5b 对抗复核（本轮重点）

#### C.2.1 同线程活跃 TX 内 `close()` → `CLOSE_DURING_TX`

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 阻塞前抛出 | `close()` 先读 `_write_lock_owner`；`owner == get_ident()` 时立即 `raise StoreError("CLOSE_DURING_TX")`，**不**调用 `acquire` | **通过** |
| 不破坏 conn/handle | fail-fast 分支无 `invalidate_session_barrier_oms_handle`、无 `conn.close()`、无 `_conn`/`_barrier_oms_handle` 赋值 | **通过** |
| 回滚路径 | `CLOSE_DURING_TX` 自 `yield repo` 抛出 → `transaction()` `except Exception` → `_safe_rollback` + `invalidate_write_lease`；`finally` `_release_write_lock` | **通过** |
| 测试意图 | `test_same_thread_close_inside_active_transaction_fail_fast_no_deadlock`：限时 `<2s`、码 `^CLOSE_DURING_TX$`、无 durable 行、handle 仍可 unpack、随后可正常 `close` | **通过** |

#### C.2.2 跨线程 close 等 TX 完成再失效 handle

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 等待 TX | 非 owner 线程走 `acquire(blocking=True)`；writer 在 `transaction`/`transition_*` 的 `finally` 释放后方可进入 close 临界区 | **通过** |
| 其后才 invalidate | invalidate + `conn.close` 仅在成功 `acquire` 之后的 `try` 内 | **通过** |
| 测试意图 | `test_concurrent_close_during_barrier_transaction_fail_closed`：writer 持 TX 时 closer 仍 alive；完成后 `_conn`/`handle` 清空、OS lock 可再持 | **通过（未回退）** |

#### C.2.3 `_write_lock_owner` 登记 / 清除 / 无逃逸

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 仅成功获锁后登记 | `_try_acquire_write_lock`：`acquire(blocking=False)` 失败则 `return False` 且**不**写 owner；成功后才 `owner = get_ident()`。`close()` 亦在 `acquire(blocking=True)` 成功后才写 owner | **通过** |
| 异常路径清除 | `transaction`/`transition_*`：`finally: _release_write_lock()`（先 `owner=None` 再 `release`）。`close()`：`finally` 同样清 owner 并 `release`（含 `CLOSE_FAILED`） | **通过** |
| 无 stale owner | 失败 acquire 不登记；CLOSE_DURING_TX 不改 owner（持锁线程仍为合法 owner，直至 TX `finally` 释放） | **通过** |
| 无双释放 | `_write_lock` 仅经 `_try_acquire`+`_release_write_lock` 或 `close` 自管 acquire+release；两路径互斥（close 等或 CLOSE_DURING_TX） | **通过** |
| 无 owner 逃逸 | owner 为进程内 `int \| None` 线程号，非 lease/capability；CLOSE_DURING_TX 路径不提前清 owner，故等待中的跨线程 close 不会在 TX 仍活跃时进入 invalidate | **通过** |

### C.3 F1–F5 回归快扫（无新增回归）

| ID | 点 | 本轮静态结论 |
|---|---|---|
| F1 | frozen `_HeldBarrierLock` | **未回归**：`@dataclass(slots=True)` 非 frozen；`_release_barrier_lock` 可写 `lock_fd`/`dir_fd=-1`；测试意图仍在 |
| F2 | OS lock → BEGIN 序 | **未回归**：`_run_under_barrier_lock_transaction`；store `transition_*` 无外层 BEGIN；顺序/并发测试意图仍在 |
| F3 | §8.6 lock 对抗 | **未回归**：hardlink / leaf|parent replace / identity drift / Windows junction 用例意图仍在 |
| F4 | broker 全写入口 | **未回归**：`persist_operation` / zero-command / finalize / desync→`verify_fresh` 在 OPEN/CLOSING/CLOSED 有用例意图 |
| F5 | 跨线程 close-vs-TX | **未回归**：串行意图与测试保留；由 F5b 补同线程面 |

### C.4 本轮 Findings

**No findings.**（无新增 P0/P1/P2）

### C.5 本轮新增对抗性反例（实现者与前两轮初验均未使用）

**标题：同线程 `CLOSE_DURING_TX` 被吞掉后，跨线程已阻塞的 `close()` 不得提前撕 handle**

实现者已覆盖：

- 跨线程 writer 持 TX 时另一线程 `close()` 阻塞后串行（F5）
- 同线程嵌套 `close()` → `CLOSE_DURING_TX`、限时返回、不 mutate（F5b）

**未覆盖的组合控制流：**

1. 线程 W：`with store.transaction():` 已持 `_write_lock`（`owner=W`）且（barrier 时）持 OS lease + BEGIN
2. 线程 C：调用 `store.close()` → 因非 owner 进入 `acquire(blocking=True)`，阻塞
3. 线程 W：同线程再调 `store.close()` → 必须 `CLOSE_DURING_TX`；**且不得**清 `owner`、不得 `release`、不得 invalidate/close conn
4. 线程 W：`except StoreError: pass` 吞掉后继续写并正常 commit，或任由异常触发 rollback
5. 仅当 W 退出 `transaction()` 的 `finally` 释放 `_write_lock` 后，C 才允许进入 invalidate + `conn.close`

**静态期望（本轮核对结果）：**

| 步骤 | 期望 | 静态结论 |
|---|---|---|
| 3 | `CLOSE_DURING_TX` 分支零 mutate | **满足**（`store.py` close 前段仅 raise） |
| 3→4 期间 | C 仍阻塞；handle/conn 仍有效 | **满足**（C 未持锁；W 未释放） |
| 5 | C 在 W `finally` 之后才撕 handle | **满足**（invalidate 仅在 C 的 acquire 成功后） |

该反例专打「fail-fast 是否误释放 owner/锁导致跨线程 close 逃逸进临界区」；与实现者单测正交。静态控制流**通过**。

### C.6 其他不变量（快扫，无新增 P0/P1）

| 不变量 | 静态结论 |
|---|---|
| identity registries / `eq=False` | capability / handle / lease 均为 `eq=False` + 模块私有 WeakKeyDictionary — **意图通过** |
| 无 public raw conn / broker 无 raw provider | handle 无逃逸 conn 字段；`bind_session_barrier` 仅 handle — **通过** |
| nonformal 未配置 barrier | `_transaction_unbounded`；仍受 `_write_lock`/`CLOSE_DURING_TX` 约束 — **通过** |
| 旧 root / UA-M4-006 | `BARRIER_OLD_ROOT_REFUSED`；报告保持 `UA-M4-006 OPEN` / `SUBSTRATE_ONLY` — **通过** |
| 无第二套 broker 状态机 / 无锁算法复制 | broker 委托 `session_barrier`；状态 OMS fresh-read — **通过** |
| exact11 范围 | 生产/测试落在白名单 1–8；交付为 10；本报告为 11 — **通过** |

### C.7 残留风险（不构成 FAIL）

- 全部检查仍为 STATIC_ONLY，须中央 CPU 跑测后才能升至 `SESSION_BARRIER_SUBSTRATE_VALIDATED`。
- OMS `close()` 串行的是 process-local `_write_lock`，不是 OS barrier lock；broker 持 OPEN lease 时另一线程关闭 OMS 的交叉生命周期未在本包测试中显式覆盖，属后续 composition/B1B 观测面，不阻断本轮 F5b 合同闭合。

### C.8 未运行检查清单

- [ ] exact worktree import identity
- [ ] `tests/unit/test_session_barrier.py`
- [ ] `tests/unit/test_execution_store.py` barrier 定向
- [ ] `tests/unit/test_paper_broker_store.py` barrier 定向
- [ ] 三文件 focused 回归
- [ ] Ruff exact production/tests
- [ ] mypy 五个 production 模块
- [ ] cold import
- [ ] exact11 scope/diff-check/residue（仅静态目视）
- [ ] 任何 SQLite/网络/浏览器/PAPER

**全部勾选为未运行。**

### C.9 REVIEW_READY（历史保留）

```
REVIEW_READY
verdict: REVIEW_PASS
phase: RE-RE-REVIEW after F5b CLOSE_DURING_TX rework
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 3rd independent static (did not implement)
static_only: all checks unrun
history_A: REVIEW_FAIL (F1-F4 P0/P1 + F5 P2)
history_B: REVIEW_FAIL (F5b same-thread self-deadlock P0)
this_round:
  f5b_same_thread_CLOSE_DURING_TX: pass
  f5b_cross_thread_serial_invalidate: pass
  owner_register_after_acquire_clear_on_all_paths: pass
  prior_f1_f5_regression: none
  p0: 0
  p1: 0
adversarial_new: CLOSE_DURING_TX swallowed while cross-thread close blocked — must not release owner/lock or tear handle early (static pass)
ua_m4_006: OPEN
substrate_only: yes
next: manager may request serial CPU validation; still SUBSTRATE_ONLY
```

---

## D. VALIDATION1 Path 返工复验（第四名独立静态初验，本轮）

### D.0 范围与方法

只读核对（相对 exact base `c124ec57…` 的 exact11 + VALIDATION1 证据）：

1. 根 `AGENTS.md`、任务书 §9.1、交付报告 VALIDATION1 返工段、§A–§C 历史
2. 生产重点：`session_barrier.py` 的 `_CONCRETE_PATH_TYPE`、`_require_absolute_path`、`unpack_session_barrier_capability` lock_root guard；并快扫 absolute/real-dir/containment/symlink/reparse/identity 与迁移/事务/锁状态机未漂移
3. 测试：`test_lock_root_concrete_path_guards_native_and_rejects_nonconcrete`
4. VALIDATION1 证据：`artifacts/agent_runs/m4-b1a-validation1-20260825T204700295`（stdout SHA 与任务书/交付一致）

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / SQLite / 网络 / commit。本结论仅为敌意静态复验，不构成运行验证通过，亦不宣称 `SESSION_BARRIER_SUBSTRATE_VALIDATED`。

### D.1 VALIDATION1 证据绑定（20 failed / 1 skipped）

| 项 | 证据 |
|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation1-20260825T204700295` |
| stage-summary | `01-identity\|exit=0`；`02-session-barrier\|exit=1` |
| identity | stdout 指向本 worktree 的 `session_barrier.py`；**PASS** |
| session stdout SHA256 | `6b5ef5b7b53e70ff3be16a1a68b7457d286881f0f11a5a36e3eae1a763a3110a`（与任务书 §9.1 / 交付一致） |
| 汇总行 | **`20 failed, 1 skipped in 5.07s`** |
| 失败形态 | 几乎全部在 `_require_absolute_path` 抛 `BARRIER_LOCK_ROOT_INVALID`（当时行号 ~1519）；factory 对 `tmp_path` 等合法 native absolute Path 即失败 |
| 1 skipped | Windows 上 `@pytest.mark.skipif(sys.platform == "win32")` 的 POSIX symlink probe（`test_session_barrier.py` ~503） |
| 根因（静态对照） | 旧谓词 `type(value) is Path`；Windows 上 `Path()` 实际为 `WindowsPath`，`type(Path(...)) is Path` 恒为 False，concrete native Path 全拒 |

### D.2 本轮裁决

**`REVIEW_PASS`**

VALIDATION1 中央合同的最小 Path exact-type 修复在静态控制流上闭合：两 guard 仅接受当前平台 `type(Path())`；native absolute 通过；subclass / Pure* / duck / relative 拒绝；未放宽为 `isinstance`、未做字符串转换；absolute / real-dir / containment / symlink / reparse / identity 与迁移 / 事务 / 锁状态机未见漂移。无新增 P0/P1。仍为 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`；须中央重跑 CPU 确认原 20 失败清零后方可升终态。

### D.3 Path guard 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 平台 concrete 常量 | `_CONCRETE_PATH_TYPE: Final[type[Path]] = type(Path())`（模块级，注释明确 WindowsPath/PosixPath） | **通过** |
| factory guard | `build_session_barrier_capability` → `_require_absolute_path`：`type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute()` → `BARRIER_LOCK_ROOT_INVALID` | **通过** |
| unpack guard | `type(value.lock_root) is not _CONCRETE_PATH_TYPE or not value.lock_root.is_absolute()` → `BARRIER_CAPABILITY_INVALID` | **通过** |
| 两 guard 同一规则 | 均为 exact `type(...) is _CONCRETE_PATH_TYPE` + `is_absolute()`；测试断言两函数 `co_names` 含 `_CONCRETE_PATH_TYPE` | **通过** |
| 禁止 isinstance 放宽 | 全模块无 `isinstance(..., Path)` 用于 lock_root | **通过** |
| 禁止字符串转换入 guard | guard 不 `Path(str(...))` / 不接受 str；duck/`__fspath__` 仅靠 type 谓词拒绝 | **通过** |
| 新增测试意图 | native 正向 factory+unpack；relative；`HostileConcretePath(concrete)`；PurePath/PureWindowsPath/PurePosixPath；DuckPath；两 guard 共享常量 | **通过** |

### D.4 非 Path 面无漂移快扫

| 面 | 静态结论 |
|---|---|
| absolute 之后 real directory | `_snapshot_root_identities`：`lstat` + `S_ISDIR` + 拒 reparse — **未漂移** |
| containment / ancestor | root.parents 逐级 identity；acquire 后 `_revalidate_after_acquire` — **未漂移** |
| symlink / reparse / junction | `_is_reparse_stat` / `_reject_reparse_path` / Windows junction 测试意图仍在 — **未漂移** |
| lock object identity | `_validate_lock_fd` nlink/dev-ino；release revalidate — **未漂移** |
| 迁移 v9 | `v009` 仅建表+CHECK `OPEN/CLOSING/CLOSED`；不 insert OPEN / 不 adopt — **未漂移** |
| 事务 / 锁序 | `_run_under_barrier_lock_transaction`：OS lock → BEGIN → … → COMMIT/ROLLBACK → unlock；F5b `CLOSE_DURING_TX` 仍在 — **未漂移** |
| exact11 | 本轮只追加本报告；实现者声明未改初验报告/formal；本复验未改 1–10 — **通过** |

### D.5 本轮 Findings

**No findings.**（无新增 P0/P1/P2）

### D.6 本轮新增对抗性反例（实现者未覆盖）

**标题：跨平台 concrete「异端 Path」伪造 — 当前平台 `type(Path())` 以外的 concrete `PosixPath`/`WindowsPath`**

实现者已覆盖：

- 当前平台 native `Path`（即 `WindowsPath` 或 `PosixPath`）
- 自定义 `concrete` 子类
- `PurePath` / `PureWindowsPath` / `PurePosixPath`
- duck 伪 Path、相对 Path

**未覆盖：**

在 **Windows** 上构造绝对 `pathlib.PosixPath("/tmp/foreign-lock-root")`（或在 **POSIX** 上构造绝对 `pathlib.WindowsPath(r"C:\foreign-lock-root")`）：

1. `isinstance(foreign, Path)` 为 True，且 `foreign.is_absolute()` 可为 True
2. 但 `type(foreign) is not type(Path())`（异端 concrete ≠ 当前平台 concrete）
3. 期望：`build_session_barrier_capability(..., lock_root=foreign)` → `BARRIER_LOCK_ROOT_INVALID`；对已 mint capability `object.__setattr__(cap, "lock_root", foreign)` 后 `unpack_session_barrier_capability(cap)` → `BARRIER_CAPABILITY_INVALID`
4. 不得因 `isinstance` 或 `Path` ABC 放行

**静态期望（本轮核对）：** 两 guard 均用 `_CONCRETE_PATH_TYPE` exact 谓词，异端 concrete 必然 fail-closed。与实现者 Pure* / 同平台 subclass 用例正交，专打「跨平台 concrete 冒充」。

### D.7 残留风险（不构成 FAIL）

- STATIC_ONLY：须中央重跑 `test_session_barrier` 证明原 20 失败清零。
- 实现者测试未显式列入异端 concrete Path；静态谓词已覆盖，建议中央验证后可选补测。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### D.8 未运行检查清单

- [ ] exact worktree import identity（VALIDATION1 历史已 PASS，本轮未重跑）
- [ ] `tests/unit/test_session_barrier.py`（含 VALIDATION1 新测）
- [ ] execution/paper broker barrier 定向与三文件 focused
- [ ] Ruff / mypy / cold import
- [ ] exact11 scope/diff-check/residue（仅静态目视）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### D.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION1-PATH-RE-REVIEW (Windows concrete Path guard)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 4th independent static (did not implement)
static_only: all checks unrun
history_A: REVIEW_FAIL (F1-F4 P0/P1 + F5 P2)
history_B: REVIEW_FAIL (F5b same-thread self-deadlock P0)
history_C: REVIEW_PASS (F5b CLOSE_DURING_TX)
validation1_evidence:
  root: artifacts/agent_runs/m4-b1a-validation1-20260825T204700295
  stdout_sha256: 6b5ef5b7b53e70ff3be16a1a68b7457d286881f0f11a5a36e3eae1a763a3110a
  result: 20 failed / 1 skipped (identity PASS; root cause type(value) is Path)
this_round:
  _CONCRETE_PATH_TYPE = type(Path()): pass
  _require_absolute_path + unpack same predicate: pass
  native absolute accept / subclass Pure* duck relative reject: pass
  no isinstance / no str coerce: pass
  abs/real-dir/containment/symlink/reparse/identity + migration/tx/lock SM: no drift
  p0: 0
  p1: 0
adversarial_new: cross-platform concrete PosixPath-on-Win / WindowsPath-on-POSIX must fail both guards (static pass)
ua_m4_006: OPEN
substrate_only: yes
next: manager may request serial CPU re-validation; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## E. VALIDATION2 F1–F4 返工复验（第五名独立静态初验，本轮）

### E.0 范围与方法

只读核对（相对 exact base `c124ec57…` 的 exact11 + VALIDATION2 证据；**未**改路径 1–10）：

1. 根 `AGENTS.md`、任务书 §9.2、交付报告 VALIDATION2 段、§A–§D 历史
2. VALIDATION2 证据树：`artifacts/agent_runs/m4-b1a-validation2-20260825T210000000`（stdout SHA 与任务书/交付一致）
3. 本轮声称仅改：`tests/unit/test_session_barrier.py` + 任务书 + 交付；生产/迁移/store/`test_execution_store.py`/`test_paper_broker_store.py` 相对 Path 返工现场字节不变
4. 复核 V2-F1 replace 码、V2-F2 `set_trace_callback` 序、V2-F3/F4 writer 线程亲和与失败暴露

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / SQLite / 网络 / commit。本结论仅为敌意静态复验，不构成运行验证通过，亦不宣称 `SESSION_BARRIER_SUBSTRATE_VALIDATED`。

### E.1 VALIDATION2 证据绑定（4 failed）

| 项 | 证据 |
|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation2-20260825T210000000`（worktree 内） |
| stage-summary | `01-identity\|exit=0`；`02-session-barrier\|exit=1` |
| session stdout SHA256 | `bff0b741aaf26c5390d2cd6880033c7d1f1bb06d08365514462a601686b38dc4`（与任务书 §9.2 / 交付一致；本轮静态重算匹配） |
| 汇总行 | **`4 failed, 17 passed, 1 skipped in 8.63s`** |
| F1 | `test_protocol_subclass_object_new_and_replace_capability_rejected`：`replace(cap,…)` 期望 `TypeError`，实得 `SessionBarrierError: BARRIER_CAPABILITY_INVALID`（`dataclasses._replace` → `__init__`） |
| F2 | `test_write_lease_lifecycle_and_forgery`：`replace(live,…)` 同理 → `BARRIER_LEASE_INVALID` |
| F3 | `test_transition_acquires_barrier_lock_before_begin`：`monkeypatch.setattr(conn, "execute", …)` → `AttributeError: … 'execute' is read-only` |
| F4 | `test_writer_and_transition_lock_order_no_deadlock`：主线程 mint 的 handle 跨入 writer；`writer_ready.wait(timeout=5)` → **`assert False`（满 5 秒）**，未暴露线程内真实失败 |

### E.2 本轮范围 / 字节不变

| 路径 | mtime (UTC) vs V2 返工窗 (~13:06Z) | 结论 |
|---|---|---|
| `session_barrier.py` | 12:51Z（Path 返工后） | **相对 Path 现场未再改** |
| `migrations/__init__.py` / `v009_*.py` | 11:41Z | **未改** |
| `store.py` / `paper_broker_store.py` | 12:35Z / 11:55Z | **未改** |
| `test_execution_store.py` / `test_paper_broker_store.py` | 12:36Z / 12:27Z | **未改** |
| `test_session_barrier.py` | 13:06Z | **本轮唯一测试改动** |
| 任务书 / 交付 | 13:07Z | **本轮文档** |
| 本报告 | 本轮追加 §E | exact11 路径 11 |

实现者 transcript 仅 `StrReplace` 上述三路径；与 mtime/白名单一致。**生产/迁移/store/其他测试字节相对 Path 返工现场不变 — 通过。**

### E.3 本轮裁决

**`REVIEW_FAIL`** — V2-F1/F2/F3 合同意图静态闭合；V2-F4 线程亲和修复意图正确，但**失败暴露合同未闭合**（1×P1）：writer 在 `ready` 前失败时仍可能只呈现 5 秒 `wait` 超时，掩盖真实码/异常与 cleanup 二次异常。修复并复验前不得申请中央 CPU 重跑。仍为 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### E.4 V2-F1 / F2 / F3 合同复核（通过）

| ID | 检查项 | 静态证据 | 结论 |
|---|---|---|---|
| V2-F1 | replace → 稳定码 | `replace(cap,…)` / `replace(live,…)` 断言 `SessionBarrierError` + `BARRIER_CAPABILITY_INVALID` / `BARRIER_LEASE_INVALID` | **通过** |
| V2-F1 | copy/deepcopy/pickle | 仍 `pytest.raises(TypeError)`；生产 `__copy__`/`__deepcopy__`/`__reduce_ex__` 仍 TypeError | **通过** |
| V2-F1 | 生产未改 | capability/lease `__init__` 仍抛稳定码；`__replace__` 仍 TypeError；本轮未改生产 | **通过** |
| V2-F2 | 观测 API | `conn.set_trace_callback(trace_sql)`；**仅** monkeypatch `hold_session_barrier_lock`；无 `conn.execute` patch | **通过** |
| V2-F2 | 序断言 | initialize：`order[:3]==lock,begin,commit` 且 `order[3]==unlock`；transition：index(lock)<begin<commit<unlock | **通过** |
| V2-F2 | finally 清 callback | `finally: conn.set_trace_callback(None)` | **通过** |
| V2-F3/F4 | 同线程 conn/handle/lease | writer 内 `sqlite3.connect`→`issue_session_barrier_oms_handle(conn=conn2)`→`hold_open_write_lease`→`BEGIN`；主线程仅 `transition_*` | **意图通过** |
| V2-F3/F4 | 禁 `check_same_thread=False` | `test_session_barrier.py` 无该字面量（store 既有连接参数属 Path 前生产面，本轮字节未改，不计入本测违规） | **通过** |

### E.5 本轮 Findings

#### [P1] writer `ready` 前失败仍被 5s `wait` 超时掩盖；join 不断言线程退出；cleanup 二次异常可再掩盖 — `tests/unit/test_session_barrier.py:595-638`

| 项 | 内容 |
|---|---|
| 现象 | `assert writer_ready.wait(timeout=5)` 在 ready 未置位时满等 5 秒后仅 `AssertionError`；`errors` 中可能已有 `SessionBarrierError.code` / sqlite 名却未在 wait 失败路径读取。`thread.join(timeout=5)` 后**无** `assert not thread.is_alive()`。`finally` 中 `invalidate`→`close` 无隔离：若 `close` 抛错，可在已捕获主失败后作为线程未捕获异常逃逸，主线程仍只见 wait 超时。 |
| 根因 | 返工修正了跨线程 handle 亲和，但保留「仅靠 ready Event + 固定超时」的编排；与 VALIDATION2 F4 证据同构（当时亦是 `wait(timeout=5)` → `assert False`，真实失败被超时表面化）。 |
| 规则 | 中央 V2-F3/F4 通过条件含稳定暴露 BUSY/失败，禁止线程失败被超时掩盖；任务书 §7 稳定失败语义；初验须对抗实现者未覆盖编排缺陷。 |
| 最小复现（静态） | 人为使 writer 在 `writer_ready.set()` 前失败（例如错误 db_path / issue handle 失败）：主断言停在 wait，需满 5s；`errors` 内容不进入失败消息。 |
| 新增测试/修复方向 | wait 失败路径必须立即 `release_writer.set()` + `join` 短超时，并 `assert errors` / 线程已死且消息含真实码；成功路径 `join` 后 `assert not thread.is_alive()`；cleanup 用嵌套 try/finally 保证 `conn2.close()`，二次异常不得吞主失败。 |
| 通过条件 | writer ready 前任意失败：**<1s 级**稳定失败面暴露真实码/异常，不得仅 5s AssertionError；无 handle/conn 泄漏；无二次异常掩盖；持锁成功路径仍断言 `BARRIER_WRITER_BUSY` 后可 CLOSING。 |

### E.6 本轮新增对抗性反例（实现者未覆盖）

**标题：writer 在 `writer_ready.set()` 之前失败时，主线程不得只等待 5 秒；invalidate/close 不得二次异常掩盖**

实现者已覆盖：

- writer 同线程 `conn2` + issue handle + lease + BEGIN
- 主线程仅 transition，期望持锁时 `BARRIER_WRITER_BUSY`
- 成功路径 `errors == []` 且随后 CLOSING

**未覆盖（本轮对抗）：**

1. 线程 W：在 `writer_ready.set()` **之前**失败（issue/lease/BEGIN 任一）→ 必须把稳定码写入可观测处并退出
2. 线程 M：不得满等 `writer_ready.wait(5)` 后仅 `assert False`；应 fail-fast 读 `errors` / 线程死亡原因（对照 VALIDATION2 F4 证据形态）
3. W 的 `finally`：`invalidate_session_barrier_oms_handle` 若抛错，仍必须执行 `conn2.close()`；`close` 抛错不得抹掉步骤 1 的主失败码
4. M：`join` 后线程必须已退出，禁止超时后继续断言 `errors == []` 而线程仍存活（handle/conn 泄漏窗）

**静态核对结果：** 当前编排**不满足** 2–4 → 构成 §E.5 P1；与实现者「亲和修复」正交，专打失败暴露与 cleanup 掩盖。

### E.7 残留风险（不构成额外 FAIL 项）

- STATIC_ONLY：须中央重跑 `test_session_barrier` 证明原 4 失败清零（修复 P1 后）。
- 部分 Python 若 `dataclasses.replace` 走 `__replace__` 会得 TypeError；本轮合同按 VALIDATION2/Miniforge 实得 `SessionBarrierError` 冻结，跨解释器差异属观测面。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### E.8 未运行检查清单

- [ ] exact worktree import identity（V2 历史 identity PASS，本轮未重跑）
- [ ] `tests/unit/test_session_barrier.py`（含 V2 返工）
- [ ] execution/paper broker barrier 定向与三文件 focused
- [ ] Ruff / mypy / cold import
- [ ] exact11 scope/diff-check/residue（仅静态目视 + mtime）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### E.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_FAIL
phase: VALIDATION2-F1-F4-RE-REVIEW (test-surface only; production bytes frozen)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 5th independent static (did not implement)
static_only: all checks unrun
history_A: REVIEW_FAIL (F1-F4 P0/P1 + F5 P2)
history_B: REVIEW_FAIL (F5b same-thread self-deadlock P0)
history_C: REVIEW_PASS (F5b CLOSE_DURING_TX)
history_D: REVIEW_PASS (VALIDATION1 Path concrete guard)
validation2_evidence:
  root: artifacts/agent_runs/m4-b1a-validation2-20260825T210000000
  stdout_sha256: bff0b741aaf26c5390d2cd6880033c7d1f1bb06d08365514462a601686b38dc4
  result: 4 failed / 17 passed / 1 skipped (identity PASS)
scope_bytes:
  production/migration/store/other_tests vs Path现场: unchanged
  changed: test_session_barrier.py + task §9.2 + delivery only
this_round:
  V2-F1 replace SessionBarrierError codes + copy/deepcopy/pickle TypeError: pass
  V2-F2 set_trace_callback lock→begin→commit→unlock + finally clear: pass
  V2-F3/F4 writer conn2+handle+lease+BEGIN / main transition / no check_same_thread in test: intent pass
  V2-F4 failure-exposure harness: FAIL (P1)
  p0: 0
  p1: 1 (writer pre-ready failure masked by 5s wait; join/cleanup secondary mask)
adversarial_new: writer fails before ready must fail-fast with real code; invalidate/close must not secondary-mask (static FAIL)
ua_m4_006: OPEN
substrate_only: yes
next: implementer minimal test-harness rework on test_session_barrier only; then new independent re-review; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## F. VALIDATION2-F5 返工复验（第六名独立静态初验，本轮）

### F.0 范围与方法

只读核对（相对 exact base `c124ec57…` 的 exact11；**未**改路径 1–10）：

1. 任务书 §9.3、交付 VALIDATION2-F5 段、§A–§E 历史（尤其 §E P1）
2. `tests/unit/test_session_barrier.py` harness：`_await_writer_ready_or_expose_failure` / `_writer_cleanup_handle_and_conn` / `_run_writer_until_pre_ready_failure`；成功路径 lock-order；三 pre-ready 反例
3. 字节范围：生产/迁移/store/其他测试相对 Path 现场是否仍冻结
4. **敌意重点：** `conn2.close = tracking_close` 是否可执行 / 是否重演 VALIDATION2 F3 只读 native 方法；`errors` 中 `cleanup_*` 是否污染/掩盖主码

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / SQLite / 网络 / commit。

### F.1 本轮范围 / 字节不变

| 路径 | SHA16（相对 §E / Path 现场） | mtime (UTC) | 结论 |
|---|---|---|---|
| `session_barrier.py` | `54D4E728440FBE61` | 12:51Z | **未改** |
| `migrations/*` / `store.py` / `paper_broker_store.py` | 与 §E 相同 | ≤12:35Z | **未改** |
| `test_execution_store.py` / `test_paper_broker_store.py` | 与 §E 相同 | ≤12:36Z | **未改** |
| `test_session_barrier.py` | `BA9554666CC695E5`（新） | 13:22Z | **本轮唯一测试改动** |
| 任务书 §9.3 / 交付 | 新 | 13:23Z | **本轮文档** |
| 本报告 | §F 追加 | 本轮 | exact11 路径 11 |

**通过：** 仅 `test_session_barrier.py` + taskbook + delivery 改变。

### F.2 本轮裁决

**`REVIEW_FAIL`** — §E P1 的 fail-fast / join / nested cleanup / 成功 BUSY→CLOSING 意图已闭合；但三「无泄漏」反例依赖对原生 `sqlite3.Connection.close` 的**实例属性替换**做跟踪，与 VALIDATION2 F3 已证实的只读 native 方法问题同构（1×P1）。在同一 Miniforge 校验面上极可能 `AttributeError`，导致反例不可执行或 `errors` 空、泄漏断言落空。修复前不得申请中央 CPU。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### F.3 §E P1 合同闭合复核（通过）

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| ready 前失败 &lt;1s 暴露 | `_await_*` / `_run_writer_*` 默认 `timeout=0.5`；未 ready 则短 join + `assert errors` / `pytest.fail(... errors=...)`；**禁止**满 5s 泛化 AssertionError | **通过** |
| 成功/失败 join 后线程必退 | 成功：`finally` join + `assert not thread.is_alive()`；失败：`_run_writer_*` join + 同断言 | **通过** |
| nested cleanup 保证 close | `_writer_cleanup_handle_and_conn`：invalidate 在内层 try；`finally` 必 `conn2.close()`；异常只 `errors.append`，不 raise | **通过** |
| cleanup 不覆盖主码 | 主路径先 `errors.append(exc.code\|type)`；cleanup 仅追加 `cleanup_invalidate:` / `cleanup_close:` 前缀串；断言用 `code in errors` / `any(name in errors)`，前缀项≠主码 | **append 设计通过**（见 F.5 对抗对「污染」边界） |
| 成功路径 BUSY→CLOSING | lock-order：ready 后 `BARRIER_WRITER_BUSY`；`errors == []`；再 `transition` → `CLOSING` | **通过** |
| 无 `check_same_thread=False` | 本文件仅注释提及，无字面量启用 | **通过** |

### F.4 本轮 Findings

#### [P1] 三 pre-ready「无泄漏」反例用实例赋值替换原生 `Connection.close`，重演只读 native 方法风险 — `tests/unit/test_session_barrier.py:736-740,804-808,866-870`

| 项 | 内容 |
|---|---|
| 现象 | `test_writer_pre_ready_{issue,lease,begin}_failure_fail_fast_exposes_code` 均执行 `conn2.close = tracking_close`（再于 wrapper 内调 `sqlite3.Connection.close(conn2)`）。VALIDATION2 证据在同一解释器上已证 `monkeypatch.setattr(conn, "execute", …)` → `AttributeError: ... 'execute' is read-only`。实例 `setattr(conn2, "close", …)` 与之同属 C 扩展 Connection 槽位方法，**静态上高度同构**，赋值阶段即可失败。 |
| 根因 | 用替换 native 方法做观测，而非在测试自有 cleanup 辅助/包装层记账；未吸取 V2-F3「勿 patch 只读 Connection 方法」教训。 |
| 规则 | 任务书 §9.3：三反例须真实证明无 handle/conn 泄漏；V2-F2/F3：观测不得依赖只读 native 方法替换；§E 对抗：失败须稳定暴露主码。 |
| 最小复现（静态推演） | writer 进入后首句有效逻辑为 `conn2.close = tracking_close` → 预期 `AttributeError`（非 `SessionBarrierError`/`sqlite3.Error`）→ 未写入 `errors` → `_run_writer_until_pre_ready_failure` 在 0.5s 后 `assert errors` 失败，或线程未捕获异常退出而 `closed` 从未置位；`assert closed == [True]` / 泄漏证明落空。 |
| 修复方向 | **禁止**对 `Connection.close`/`execute` 做实例或 monkeypatch 替换。泄漏证明改为：向 `_writer_cleanup_handle_and_conn` 传入 `closed: list`（或包装 `conn2` 的薄代理仅测试持有），在辅助的 `finally` 里 `closed.append(True)` 后再 `sqlite3.Connection.close(conn2)`；issue/lease/BEGIN 注入保持 monkeypatch **模块函数**（已证明可写）。 |
| 通过条件 | 三反例在无 native close 替换前提下：&lt;1s 暴露主稳定码；`closed`/`invalidated` 由测试自有记账证明 cleanup 执行；线程退出；主码不被 `cleanup_*` 覆盖。 |

### F.5 本轮新增对抗性反例（实现者未覆盖）

**标题：`conn2.close = tracking_close` 在 Miniforge/VALIDATION2 同构面上不可赋值时，泄漏反例与主码暴露同时崩塌**

实现者已覆盖：

- fail-fast await（0.5s）+ 短 join + `not is_alive`
- nested cleanup append-only
- monkeypatch `issue_session_barrier_oms_handle` / `hold_open_write_lease`（模块级，可写）
- 成功路径 BUSY→CLOSING

**未覆盖：**

1. 在 **不** 赋值 `conn2.close` 的前提下证明 `conn2` 已被关闭（例如 cleanup 辅助记账，或关闭后对同一对象再 `execute` 得稳定 `ProgrammingError` 且 registry 无 handle）
2. 当 `setattr(conn2, "close", …)` 抛 `AttributeError` 时，harness 不得表现为「无 stable code」空 `errors`——须与 V2-F3 read-only 失败面显式隔离
3. `cleanup_close:ProgrammingError` 这类前缀项不得被 `name in errors` 误当成主 sqlite 名；当前主码为独立 list 元素时安全，但若将来只保留 cleanup 项则会假绿/假红——应用 `errors[0] == code` 或过滤非 `cleanup_` 前缀（建议加固，**不单独构成本轮第二 FAIL**）

**静态结论：** 点 1–2 因 P1 未满足 → **FAIL**；点 3 cleanup 前缀设计目前不掩盖已写入的主码 → 附注。

### F.6 残留风险（不构成额外 FAIL）

- STATIC_ONLY：须中央重跑证明 V2 四失败 + F5 新测。
- Event.wait(0.5) 不因线程早死而提前返回；仍满足 &lt;1s 合同，但是观测延迟上界。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### F.7 未运行检查清单

- [ ] exact worktree import identity
- [ ] `tests/unit/test_session_barrier.py`（含 F5 harness / 三反例）
- [ ] execution/paper broker 定向与 focused
- [ ] Ruff / mypy / cold
- [ ] exact11 scope/diff（仅静态 mtime/SHA）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### F.8 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_FAIL
phase: VALIDATION2-F5-RE-REVIEW (pre-ready fail-fast harness; production bytes frozen)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static (did not implement)
static_only: all checks unrun
history_A: REVIEW_FAIL (F1-F4 P0/P1 + F5 P2)
history_B: REVIEW_FAIL (F5b same-thread self-deadlock P0)
history_C: REVIEW_PASS (F5b CLOSE_DURING_TX)
history_D: REVIEW_PASS (VALIDATION1 Path concrete guard)
history_E: REVIEW_FAIL (V2-F4 5s wait mask P1)
scope_bytes:
  production/migration/store/other_tests: unchanged vs Path现场
  changed: test_session_barrier.py + task §9.3 + delivery only
this_round:
  fail_fast_<1s_expose_errors: pass
  join_assert_not_alive_success_and_failure: pass
  nested_cleanup_close_append_only: pass
  success_BUSY_then_CLOSING: pass
  cleanup_prefix_does_not_overwrite_primary: pass (design)
  three_anti_leak_via_conn2.close_assignment: FAIL (P1; read-only native risk)
  p0: 0
  p1: 1
adversarial_new: conn2.close=tracking_close likely AttributeError on same Miniforge as V2-F3 execute read-only — leak proofs / errors empty (static FAIL)
ua_m4_006: OPEN
substrate_only: yes
next: implementer remove native Connection.close instance patch; prove close via test-owned bookkeeping in cleanup helper; then new independent re-review; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## G. VALIDATION2-F6 返工复验（第六名独立静态续验，本轮）

### G.0 范围与方法

只读核对（相对 exact base `c124ec57…`；**未**改路径 1–10）：

1. 任务书 §9.4、交付 V2-F6 段、§A–§F 历史（尤其 §F P1）
2. `_writer_cleanup_handle_and_conn` / 三 `test_writer_pre_ready_*` / 成功 lock-order
3. 字节：生产/迁移/store/其他测试相对 Path 现场是否仍冻结
4. **敌意：** BEGIN 体先 `Connection.close` 再 finally 二次 close 的 `closed` 证据充分性；issue 失败 `handle2 is None` 时 close 证明是否仍成立

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / SQLite / 网络 / commit。

### G.1 本轮范围 / 字节不变

| 路径 | SHA16 | 相对 §F / Path | 结论 |
|---|---|---|---|
| 五生产模块 | `54D4E728…` 等与 §F 相同 | mtime ≤12:51Z | **未改** |
| `test_execution_store` / `test_paper_broker_store` | 同 §F | ≤12:36Z | **未改** |
| `test_session_barrier.py` | `83DF8BCE111C5BD9` | 13:35Z | **本轮唯一测试改动** |
| 任务书 §9.4 / 交付 | 新 | 13:35–13:36Z | **本轮文档** |

**通过：** 仅测试 + taskbook + delivery。

### G.2 本轮裁决

**`REVIEW_PASS`**

§F P1 已闭合：无原生 `Connection.close`/`execute` 实例赋值或 monkeypatch；`cleanup_errors` 与主 `errors` 分离；`closed` 仅在 unbound `sqlite3.Connection.close` 成功返回后置位；三 pre-ready 反例与成功 BUSY→CLOSING 静态意图完整。无新增 P0/P1。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`；须中央重跑 CPU 后方可升终态。

### G.3 §F P1 / V2-F6 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 禁止 native close/execute 替换 | 全文件无 `conn2.close =` / `setattr(conn…)` / `monkeypatch` 于 Connection 方法；close 仅 `sqlite3.Connection.close(conn2)` | **通过** |
| cleanup / primary 分离 | `_writer_cleanup_handle_and_conn(..., cleanup_errors=…)`；主路径只 `errors.append(code\|type)`；断言 `errors == […]` 且 `cleanup_errors == []` | **通过** |
| `closed` 成功后置位 | `try: Connection.close` / `except → cleanup_errors` / `else: closed.append(True)` | **通过** |
| issue &lt;1s + 无线程残留 | boom 模块 `issue_*`；`_run_writer_*` timeout=0.5；`errors == ["BARRIER_OMS_HANDLE_INVALID"]`；`issued == []`；`closed == [True]` | **通过** |
| lease 同左 + handle 清除 | boom `hold_open_write_lease`；`issued[0] not in sb._OMS_HANDLE_BINDINGS`；`closed == [True]` | **通过** |
| BEGIN 同左 + 无 execute patch | 体 `Connection.close` 后 `execute("BEGIN…")` 自然失败；主码 ∈ Programming/Operational/DatabaseError；handle 清除；`closed == [True]` | **通过** |
| 成功 BUSY→CLOSING | lock-order：`BARRIER_WRITER_BUSY` → join/`not is_alive` → `errors==[]`/`cleanup_errors==[]` → CLOSING | **通过（未漂移）** |

### G.4 本轮 Findings

**No findings.**（无新增 P0/P1/P2）

### G.5 敌意核对（用户指定两点）

#### G.5.1 BEGIN：体先 close，finally 再 close — `closed` 证据是否充分？

| 步骤 | 行为 | Miniforge/CPython 静态期望 |
|---|---|---|
| 1 | 体 `sqlite3.Connection.close(conn2)` | 成功；**不**写 `closed`（体无记账） |
| 2 | `conn2.execute("BEGIN…")` | 已关闭连接 → 稳定 `sqlite3.Error` 子类入主 `errors` |
| 3 | cleanup 再 `Connection.close(conn2)` | CPython sqlite3 对已关闭连接 **idempotent 成功返回**（不抛）→ `else: closed.append(True)` |
| 4 | 断言 | `closed == [True]` 且 `cleanup_errors == []` |

**结论：** 在目标 Miniforge（CPython）语义下，`closed` 证明的是 **cleanup 路径 unbound close 成功返回**，再叠加步骤 1 已释放连接，构成「无 open conn 泄漏」的充分静态证据；并非声称「cleanup 是唯一一次关闭」。若某绑定使二次 close 抛错，则 `cleanup_errors != []` 或 `closed != [True]` → **fail-closed**，不会假绿。

#### G.5.2 issue 失败：`handle2 is None`，close 证明是否仍成立？

| 步骤 | 行为 | 期望 |
|---|---|---|
| 1 | `boom_issue` 在赋值前抛 `BARRIER_OMS_HANDLE_INVALID` | `handle2` 保持 `None`；`issued` 不 append → `issued == []` |
| 2 | 无 registry 绑定可清 | 无需 invalidate；cleanup 跳过 handle 分支 |
| 3 | `conn2` 已 connect | cleanup `Connection.close(conn2)` 成功 → `closed == [True]` |

**结论：** handle 为空与 close 成功证明正交且同时成立；不依赖「先有 handle」。**通过。**

### G.6 本轮新增对抗性反例（实现者断言已覆盖、本轮核过）

**标题：issue boom 零 handle 时，cleanup 不得因 `handle2 is None` 跳过 `conn2` close**

实现者断言：`issued == []` 且 `closed == [True]`。

**控制流：** connect → issue 抛错 → finally cleanup：`handle2 is None` 跳过 invalidate，**仍**对非空 `conn2` 走 unbound close 并在成功后标记 `closed`。

**静态核对：** `_writer_cleanup_handle_and_conn` 的 `finally` 仅以 `conn2 is not None` 为 close 门闸，与 handle 无关 → **满足**。与 §F「必须实例 patch close 才能证明」方案正交。

### G.7 残留风险（不构成 FAIL）

- STATIC_ONLY：须中央重跑 `test_session_barrier`（含 F5/F6 harness）。
- BEGIN 二次 close 依赖 CPython idempotent；异常绑定会令测试变红而非假绿。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### G.8 未运行检查清单

- [ ] exact worktree import identity
- [ ] `tests/unit/test_session_barrier.py`（含 F6）
- [ ] execution/paper broker 定向与 focused
- [ ] Ruff / mypy / cold
- [ ] exact11 scope/diff（仅静态 SHA/mtime）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### G.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION2-F6-RE-REVIEW (no native Connection close/execute patch)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun
history_A: REVIEW_FAIL (F1-F4 P0/P1 + F5 P2)
history_B: REVIEW_FAIL (F5b same-thread self-deadlock P0)
history_C: REVIEW_PASS (F5b CLOSE_DURING_TX)
history_D: REVIEW_PASS (VALIDATION1 Path concrete guard)
history_E: REVIEW_FAIL (V2-F4 5s wait mask P1)
history_F: REVIEW_FAIL (V2-F5 conn2.close= assignment P1)
scope_bytes:
  production/migration/store/other_tests: unchanged vs Path现场
  changed: test_session_barrier.py + task §9.4 + delivery only
this_round:
  no_native_close_execute_patch: pass
  cleanup_errors_separated_from_primary: pass
  closed_only_after_unbound_close_success: pass
  issue_lease_begin_pre_ready_<1s_thread_exit_handle_clear_close: pass
  issue_null_handle_still_closes_conn: pass
  begin_body_close_then_cleanup_close_idempotent_evidence: pass (CPython)
  success_BUSY_then_CLOSING: pass
  p0: 0
  p1: 0
adversarial_new: issue boom with handle2=None must still unbound-close conn2 and mark closed (static pass)
ua_m4_006: OPEN
substrate_only: yes
next: manager may request serial CPU re-validation; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## H. VALIDATION3 返工复验（第六名独立静态续验，本轮）

### H.0 范围与方法

只读核对（相对 exact base `c124ec57…`；**未**改路径 1–10 外本报告）：

1. 任务书 §9.5、交付 VALIDATION3 段、§A–§G 历史
2. VALIDATION3 证据：`artifacts/agent_runs/m4-b1a-validation3-20260825T143500Z-c91e`
3. `tests/unit/test_paper_broker_store.py`：`test_broker_all_writers_require_open_lease` 及 fail-closed 邻接用例
4. 生产 `paper_broker_store._barrier_lease` / `gateway_identity`→`verify_fresh`→`_sync_anchors` 只读对照（确认未改 locking）

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / SQLite / 网络 / commit。

### H.1 VALIDATION3 证据与文档绑定

| 项 | 证据 | 结论 |
|---|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation3-20260825T143500Z-c91e`（worktree 内存在） | 与任务书 §9.5 / 交付一致 |
| stage-summary | `01–03 exit=0`；`04-broker-targeted\|exit=1` | 定向 broker STOP |
| 04 stdout SHA256 | 静态重算 `1092d8a472dff6950b897d065f5232e02e496bbeae9e5c603e429f7c07aed2ac` | **匹配**任务/交付 |
| 失败形态 | 旧 `tracked_lease` 包裹 `_barrier_lease` 再入 `real_lease()` → 持锁期 `_sync_anchors` 嵌套 → `BARRIER_WRITER_BUSY`；`1 failed, 3 passed` | 与 §9.5 现象一致 |

### H.2 本轮范围 / 字节不变

| 路径 | SHA16 / mtime | 结论 |
|---|---|---|
| 五生产模块 | 与 §G/Path 现场相同（`paper_broker_store` `79F0B791…` @11:55Z） | **未改** |
| `test_session_barrier` / `test_execution_store` | 同前 | **未改** |
| `test_paper_broker_store.py` | `A448D82CE6B30DF7` @13:55Z | **本轮唯一测试改动** |
| 任务书 §9.5 / 交付 | 13:56Z | **本轮文档** |

**通过：** 仅 paper-broker 测试 + taskbook + delivery；生产 locking 字节未改。

### H.3 本轮裁决

**`REVIEW_PASS`**

观测改到模块 `hold_open_write_lease` 边界，**不再**包裹/再入实例 `_barrier_lease`；无假 lease、无生产可重入改写；`max(enter_depth)==1` 与 idle 0-enter 对抗保留非重入语义；OPEN writer（zero / persist / finalize / verify_fresh 锚点）先真实 enter；CLOSING/CLOSED/identity/未配置 barrier 仍 fail-closed。无新增 P0/P1。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### H.4 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 不包裹 `_barrier_lease` | 无 `broker._barrier_lease =` / `tracked_lease`；注释明确禁止 | **通过** |
| 不改生产 locking / 无可重入 | `paper_broker_store.py` SHA 未变；`_barrier_lease` 仍单次 `hold_open_write_lease` | **通过** |
| 无假 lease | `observe_hold` → `with real_hold(...) as lease: yield lease` | **通过** |
| 观测边界 | `monkeypatch` 仅 `broker_store_module.hold_open_write_lease` | **通过** |
| depth 非重入 | enter 时 `assert depth["n"]==1`；`max(_enter_depths())==1` | **通过** |
| 观测器自身不二次进入 | 武装后立刻 `_enter_depths()==[]` 且 `depth["n"]==0` | **通过** |
| writer 先取 OPEN lease | zero / persist / finalize：`_enter_depths()[0]==1`；锚点 desync→`verify_fresh`：`==[1]` | **通过** |
| 持锁期不触 sync 属性 | `gateway_identity` **仅**在武装观测前读取（属性内会 `verify_fresh`）；观测窗注释禁止再读 | **通过** |
| CLOSING/CLOSED | zero / finalize / persist / `verify_fresh` 均 `BARRIER_STATE_*` | **通过** |
| 无 barrier / identity | `test_unconfigured_broker_store_unchanged_without_barrier`；`test_broker_barrier_identity_mismatch_rejected` 保留 | **通过** |
| 遗漏 writer 面 | OPEN+CLOSING/CLOSED 覆盖 zero、persist、finalize、锚点 UPDATE | **通过** |

### H.5 本轮 Findings

**No findings.**

### H.6 本轮新增对抗性反例（实现者未单独成用例，静态捕获器已在）

**标题：若在 writer 已持有 `hold_open_write_lease`（depth=1）的窗口内再触发 `gateway_identity`→`verify_fresh`→`_sync_anchors`→再次 `hold_open_write_lease`，观测器必须以 depth≠1 失败，而非静默嵌套或假 lease**

实现者已做：武装前缓存 `gateway_identity`；idle 武装 0 enter；成功路径 `max(depth)==1`。

**未单独写的注入：** 在 `observe_hold` 的 `yield lease` 期间故意读 `broker.gateway_identity`（会再入模块 hold）。

**静态期望：** `depth["n"]` 增至 2 → `assert depth["n"]==1` 立即失败 → 证明观测保留非重入 fail-fast，且不会像 VALIDATION3 旧 `tracked_lease` 那样把嵌套翻译成含糊的 `BARRIER_WRITER_BUSY` 后继续。当前 `observe_hold` 控制流**满足该捕获器**；与「idle 0 enter」正交。

### H.7 残留风险（不构成 FAIL）

- STATIC_ONLY：须中央重跑含 `test_paper_broker_store` 的定向/ focused 以清 VALIDATION3 04 红灯。
- `record_zero` 可能顺序多次 enter（`[1,1,…]`）；合同只禁嵌套 `depth>1`，已按 `max==1` 接受。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### H.8 未运行检查清单

- [ ] exact worktree import identity（V3 历史 01 PASS，未重跑）
- [ ] `test_session_barrier` / execution 定向（V3 02–03 历史 PASS，未重跑）
- [ ] `test_paper_broker_store`（含本轮观测重写）
- [ ] Ruff / mypy / cold
- [ ] exact11 scope/diff（仅静态 SHA/mtime）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### H.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION3-RE-REVIEW (paper broker lease observer; no _barrier_lease wrap)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun
history_A..G: preserved (A/B/E/F FAIL; C/D/G PASS; prior rounds)
validation3_evidence:
  root: artifacts/agent_runs/m4-b1a-validation3-20260825T143500Z-c91e
  04_stdout_sha256: 1092d8a472dff6950b897d065f5232e02e496bbeae9e5c603e429f7c07aed2ac
  result: 04 FAILED tracked_lease re-enter → BARRIER_WRITER_BUSY (1 failed / 3 passed)
scope_bytes:
  production/migration/store/other_tests: unchanged
  changed: test_paper_broker_store.py + task §9.5 + delivery only
this_round:
  no_wrap_reenter__barrier_lease: pass
  no_fake_lease_no_production_locking_change: pass
  observe_at_module_hold_open_write_lease: pass
  max_enter_depth_1_and_idle_0_enter: pass
  OPEN_writers_take_real_lease_first: pass
  CLOSING_CLOSED_identity_unconfigured_fail_closed: pass
  p0: 0
  p1: 0
adversarial_new: gateway_identity during active observe_hold yield would force depth=2 and fail assert (static trap present; implementer avoids by pre-cache)
ua_m4_006: OPEN
substrate_only: yes
next: manager may request serial CPU re-validation; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## I. VALIDATION4 production reentrancy 复验（第六名独立静态续验，本轮）

### I.0 范围与方法

只读核对（相对 exact base `c124ec57…`；唯一可写本报告）：

1. 任务书 §9.6、交付 VALIDATION4 段、§A–§H 历史
2. 证据：`artifacts/agent_runs/m4-b1a-validation4-20260825T153000Z-e84c`
3. 生产：`paper_broker_store.py` — `bind_session_barrier` / `_bound_gateway_identity` / `_verify_barrier_lease` / `_gateway_identity_digest` / public `gateway_identity`
4. 测试：`test_broker_all_writers_require_open_lease` 及邻接 fail-closed 用例

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / 提交。

### I.1 VALIDATION4 证据与文档绑定

| 项 | 证据 | 结论 |
|---|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation4-20260825T153000Z-e84c` | 与任务书 §9.6 / 交付一致 |
| stage-summary | `01–03 exit=0`；`04-broker-targeted\|exit=1` | 定向 broker STOP |
| 04 stdout SHA256 | 静态重算 `1e6236f7e770993bfc4e384dc9cf1e9b78e27376b3653567e7ec9cbe1202c57e` | **匹配** |
| 失败形态 | `_verify_barrier_lease` 读 `self.gateway_identity` → `verify_fresh`→`_sync_anchors`→再 `_barrier_lease` → `BARRIER_LEASE_INVALID`；`1 failed, 3 passed` | 与 §9.6 现象一致（持 OPEN lease 内误走 public property） |

### I.2 本轮范围 / 字节

| 路径 | 相对 §H | 结论 |
|---|---|---|
| `session_barrier` / migrations / `store` / 其他测试 | SHA 未变 | **未改** |
| `paper_broker_store.py` | `797736EAC599551E` @14:08Z | **本轮生产改动** |
| `test_paper_broker_store.py` | `82983FBF5852744C` @14:09Z | **本轮测试改动** |
| 任务书 §9.6 / 交付 | 14:09–14:10Z | **本轮文档** |

白名单与交付声明一致。

### I.3 本轮裁决

**`REVIEW_PASS`**

持 OPEN lease 的身份核对已改为 bind 后 module-private `_bound_gateway_identity` exact 比较；public `gateway_identity` 仍 `verify_fresh`+digest；锁非重入 / writer depth exact 1；observer 仍包装真实 `hold_open_write_lease`；drift / CLOSING / CLOSED / unconfigured / identity 仍 fail-closed。无新增 P0/P1。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### I.4 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 持 lease 不调 public `gateway_identity` | `_verify_barrier_lease` 仅读 `_bound_gateway_identity`；全模块无 lease 路径 `self.gateway_identity` | **通过** |
| bind 后 private raw | `verify_fresh()` → `_gateway_identity_digest()` → 校验 → 再赋值 `_session_barrier`/`_oms_handle`/`_bound_gateway_identity`；bind 签名无外部 identity 注入参数 | **通过** |
| digest 无 fresh/lease | `_gateway_identity_digest` 只读 descriptor 字段 `_digest` | **通过** |
| lease exact 比较保留 | `cap.gateway_identity != bound_gateway_identity`（及 account/broker store）→ `BARRIER_IDENTITY_DRIFT`；`type(bound) is not str` 亦 drift | **通过** |
| public fresh 语义 | `@property gateway_identity`: `verify_fresh()` 后 `_gateway_identity_digest()` | **通过** |
| 非重入 / depth≤1 | 测试 `assert depth["n"]==1`；`all(d==1)`；`max==1`；observer→`real_hold` | **通过** |
| observer 不改真实 hold | `with real_hold(...) as lease: yield lease`；idle 0 enter | **通过** |
| bound drift fail-closed | 测：`_bound_gateway_identity="f"*64` → `BARRIER_IDENTITY_DRIFT`；`public_gw_during_lease==[]` | **通过** |
| 持锁无 public gw | tracking property + `public_gw_during_lease==[]` 于各 OPEN writer | **通过** |
| CLOSING/CLOSED/unconfigured/identity | 本测 CLOSING/CLOSED；`test_unconfigured_*`；`test_broker_barrier_identity_mismatch_rejected` 保留 | **通过** |

### I.5 本轮 Findings

**No findings.**

### I.6 本轮新增对抗性反例（实现者未单独成用例）

**标题：bind 成功后将 `_bound_gateway_identity` 置为 `None`（非错 hex），writer 必须 `BARRIER_IDENTITY_DRIFT` 且不得调用 public `gateway_identity`**

实现者已测：错 hex `"f"*64` drift。

**未单独写：** `broker._bound_gateway_identity = None` 后走 `record_zero` / persist。

**静态期望：** `_verify_barrier_lease` 中 `type(bound_gateway_identity) is not str` → `SessionBarrierError("BARRIER_IDENTITY_DRIFT")` → `PaperBrokerStoreError`；不读 public property。当前控制流**满足**；与错 hex 用例正交，专打「缺失/非 str 绑定」。

### I.7 残留风险（不构成 FAIL）

- STATIC_ONLY：须中央重跑 04 broker 定向以清 VALIDATION4 红灯。
- `_bound_gateway_identity` 为进程内可赋值字段；合同禁止的是 bind API 注入，可信进程 setattr 仍可能（已有 drift 测覆盖错值）。
- drift 断言 `max(_enter_depths() or [1])` 在空 enters 时偏弱；主路径仍应先 enter——附注。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### I.8 未运行检查清单

- [ ] exact worktree import identity（V4 历史 01 PASS）
- [ ] session-barrier / execution 定向（V4 02–03 历史 PASS）
- [ ] `test_paper_broker_store`（含 V4 生产修复）
- [ ] Ruff / mypy / cold
- [ ] exact11 scope/diff（仅静态）
- [ ] 任何 SQLite/网络/PAPER

**全部勾选为未运行。**

### I.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION4-RE-REVIEW (lease-internal bound gateway identity; no public gw reentry)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun
history_A..H: preserved
validation4_evidence:
  root: artifacts/agent_runs/m4-b1a-validation4-20260825T153000Z-e84c
  04_stdout_sha256: 1e6236f7e770993bfc4e384dc9cf1e9b78e27376b3653567e7ec9cbe1202c57e
  result: 04 FAILED public gateway_identity under lease → nested hold / BARRIER_LEASE_INVALID
scope_bytes:
  changed: paper_broker_store.py + test_paper_broker_store.py + task §9.6 + delivery
  other_production_tests: unchanged
this_round:
  no_public_gateway_identity_under_open_lease: pass
  bind_private_immutable_raw_after_verify_fresh: pass
  lease_exact_compare_bound_identity: pass
  public_gateway_identity_fresh_unchanged: pass
  nonreentrant_depth_exact_1_observer_real_hold: pass
  bound_drift_CLOSING_CLOSED_unconfigured_identity_fail_closed: pass
  p0: 0
  p1: 0
adversarial_new: _bound_gateway_identity=None must BARRIER_IDENTITY_DRIFT via type guard without public gw (static pass)
ua_m4_006: OPEN
substrate_only: yes
next: manager may request serial CPU re-validation; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## J. VALIDATION5-FIXTURE 复验（第六名独立静态续验，本轮）

### J.0 范围与方法

只读核对（相对 exact base `c124ec57…`；唯一可写本报告）：

1. 任务书 §9.7、交付 VALIDATION5-FIXTURE 段、§A–§I 历史
2. 证据：`artifacts/agent_runs/m4-b1a-validation5-20260825T171500Z-b72d`
3. `tests/unit/test_execution_store.py` 两处 v3/v7 降级 fixture；生产 `v009_session_barrier.py` 只读对照

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / SQLite / 提交。

### J.1 VALIDATION5 证据与文档绑定

| 项 | 证据 | 结论 |
|---|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation5-20260825T171500Z-b72d` | 与任务书 §9.7 / 交付一致 |
| stage-summary | `01–04 exit=0`；`05-focused-three\|exit=1` | 前四阶段 PASS；full-three STOP |
| 05 stdout SHA256 | `FCF3989D22EC5B7DCA1C0F2292B7FFAE6CEC780937DE489D1C7B92DDD4657E4E` | **匹配**（静态重算） |
| 05 stderr (empty) SHA | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | **匹配** |
| summary SHA | `085694369A74735F217ED7D81A382C85F6000CC37F6D5FB5614D7D069351A891` | **匹配** |
| runner SHA | `E3A3CB737A260C29C4EF52986693D9AB75B3ACC9D12CC6FD4F8E0D474C408FBC` | **匹配** |
| full-three 汇总 | **`2 failed, 262 passed, 6 skipped in 17.44s`** | 与任务/交付一致 |
| 2 failed | `test_v3_upgrade_*`；`test_v7_database_upgrade_*` → reopen `MIGRATION_FAILED`（降级未 DROP barrier） | 原生 STOP；**不**冒充整包 PASS |
| 边界记录 | 任务/交付均写明定向 PASS + full-three 仍 2 failed、不宣称整包 PASS | **准确** |

### J.2 本轮范围 / 字节

| 路径 | 相对 §I / Path | 结论 |
|---|---|---|
| `v009_session_barrier.py` | `ABFADB6AC20767A9` @11:41Z | **未改** |
| `session_barrier` / migrations `__init__` / `store` / `paper_broker_store` | 与 §I 相同 | **未改** |
| `test_session_barrier` / `test_paper_broker_store` | 与 §I 相同 | **未改** |
| `test_execution_store.py` | `CCABC98B42570996` @14:22Z | **本轮唯一测试改动** |
| 任务书 §9.7 / 交付 | 14:24Z | **本轮文档** |

**通过：** 仅两处 fixture + taskbook + delivery；production v009 及其他生产/测试字节未因本轮改变。

### J.3 本轮裁决

**`REVIEW_PASS`**

两降级 fixture 均在旧 `schema_version` 前显式 `DROP TABLE session_barrier`（indexes 随表删除、未手工伪造）；未改 v009、未加 `IF NOT EXISTS`、未吞 `MIGRATION_FAILED`；reopen 断言 `CURRENT` / `session_barrier_enabled is False` / `COUNT==0` / `BARRIER_MISSING`，并保留 legacy 数据断言。VALIDATION5 evidence root/SHA 与 **262 passed / 6 skipped / 2 failed** 非整包 PASS 边界记录准确。无新增 P0/P1。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### J.4 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| DROP 在旧 version 前 | v3：`DROP TABLE session_barrier` 后 `UPDATE … version = 3`；v7：DROP 后 `UPDATE … version = 7` | **通过** |
| 未手工 indexes | 注释「Indexes fall with the table；do not hand-manage」；无单独 DROP INDEX | **通过** |
| 生产 v009 不变 | SHA 未变；`CREATE TABLE session_barrier` **无** `IF NOT EXISTS` | **通过** |
| 不吞 MIGRATION_FAILED | 本轮未改 `store.py` migration 路径 | **通过** |
| reopen 断言 | `schema_version()==CURRENT`；`session_barrier_enabled is False`；`COUNT(*)==0`；`BARRIER_MISSING` | **通过** |
| 旧数据保留 | v3：`cmd-a` / 空 ledger/approval；v7：`legacy-command` / 空 approval | **通过** |

### J.5 本轮 Findings

**No findings.**

### J.6 本轮新增对抗性反例（实现者未单独成用例）

**标题：若 fixture 只 `DROP TABLE IF EXISTS` 漏网或 DROP 放在 `UPDATE version` 之后，reopen 仍必须表面化为稳定 `MIGRATION_FAILED`，不得静默成功**

实现者已固定：显式 `DROP TABLE session_barrier`（非 IF NOT EXISTS）且先于 version 降级。

**未单独写的负向：** 故意省略 DROP 或颠倒顺序。

**静态期望：** 表仍在时真实 v009 `CREATE TABLE` 冲突 → store 映射 `MIGRATION_FAILED`（与 VALIDATION5 05 红灯同构）。生产无 `IF NOT EXISTS` 保证 fail-closed。当前正路径 fixture **满足**合同；该负向由证据历史覆盖。

### J.7 残留风险（不构成 FAIL）

- STATIC_ONLY：fixture 返工后须中央重跑 full-three / 定向以确认原 2 failed 清零。
- 证据中的 2 failed 是**返工前**原生 STOP，不得写成当前源码已绿。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### J.8 未运行检查清单

- [ ] 本轮未重跑任何 Python/pytest/Ruff/mypy/cold/SQLite
- [ ] 仅静态核对证据产物与源码/文档绑定

### J.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION5-FIXTURE-RE-REVIEW (v3/v7 DROP session_barrier before downgrade)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun this round
history_A..I: preserved
validation5_evidence:
  root: artifacts/agent_runs/m4-b1a-validation5-20260825T171500Z-b72d
  05_stdout_sha256: FCF3989D22EC5B7DCA1C0F2292B7FFAE6CEC780937DE489D1C7B92DDD4657E4E
  full_three: 2 failed / 262 passed / 6 skipped (NOT whole-pack PASS)
  failed_nodes: test_v3_upgrade_*; test_v7_database_upgrade_* (pre-fix MIGRATION_FAILED)
scope_bytes:
  changed: test_execution_store.py (2 fixtures) + task §9.7 + delivery
  production_v009_and_other: unchanged
this_round:
  drop_before_version_downgrade: pass
  no_hand_indexes_no_v009_IF_NOT_EXISTS_no_swallow: pass
  reopen_empty_barrier_disabled_legacy_preserved: pass
  evidence_root_sha_and_262_6_2_boundary_honest: pass
  p0: 0
  p1: 0
adversarial_new: omit DROP / reorder after version must still MIGRATION_FAILED (covered by V5 evidence; production CREATE fail-closed)
ua_m4_006: OPEN
substrate_only: yes
whole_pack_pass: no
next: manager may request serial CPU re-run after fixture; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## K. VALIDATION6-TYPE 复验（第六名独立静态续验，本轮）

### K.0 范围与方法

只读核对（相对 exact base `c124ec57…`；唯一可写本报告）：

1. 任务书 §9.8、交付 VALIDATION6-TYPE 段、§A–§J 历史
2. 证据：`artifacts/agent_runs/m4-b1a-validation6-20260825T174500Z-c63e`
3. `session_barrier.py`：平台锁 SSOT、`_digest`、`_IS_WIN32` 清除

**全部未运行（STATIC_ONLY）：** Python / pytest / Ruff / mypy / cold / scope / 提交。

### K.1 VALIDATION6 证据与文档绑定

| 项 | 证据 | 结论 |
|---|---|---|
| evidence root | `artifacts/agent_runs/m4-b1a-validation6-20260825T174500Z-c63e` | 存在且与任务/交付一致 |
| stage-summary | `01–06 exit=0`；`07-mypy-production5\|exit=1` | focused+Ruff **绿**；mypy STOP |
| focused SHA | `65BE40188EDE4CA5CF8CCB3C21517309F9C9143054C1119E20E5277B769E9835` | **匹配** |
| Ruff SHA | `82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18` | **匹配** |
| mypy SHA | `6C32100322FCACBCF6ECC7565CA6FFFCF69F67E749233F5F56E526CCBA7FAA25` | **匹配** |
| summary / runner SHA | `0A5259AC…` / `0CCAA7DF…` | **匹配** |
| mypy 三错（返工前原生） | `fcntl` name-defined×2；`_digest(object)`→`canonical_json_bytes` arg-type×1 | 与 §9.8 现象一致 |
| cold / scope | 证据树无 cold/scope 阶段；交付写明本 STATIC_ONLY 未跑；**不**冒充 Linux Gate/整包 PASS | **准确** |

### K.2 本轮范围 / 字节

| 路径 | 相对 §J | 结论 |
|---|---|---|
| migration / store / paper_broker / 三测试 | SHA 同 §J | **未改** |
| `session_barrier.py` | `487CA2C6A5516A71` @14:34Z | **本轮唯一生产改动** |
| 任务书 §9.8 / 交付 | 14:35Z | **本轮文档** |

**通过：** 仅 `session_barrier.py` + taskbook + delivery。

### K.3 本轮裁决

**`REVIEW_PASS`**

锁平台 SSOT 改为直接 `sys.platform == "win32"` 收窄 + 分支内惰性 `msvcrt`/`fcntl`；死 `_IS_WIN32` 已移除；offset/mode/nonblocking/错误码/early-return 顺序意图保持；无 `Any`/`type: ignore`/fallback；`_digest` 收窄为 `Mapping[str, object]` 且 caller 均为 canonical mapping；VALIDATION6 组合绿 + mypy 三错证据/SHA 与未跑 cold/scope、非整包/非 Linux Gate 边界记录准确。无新增 P0/P1。仍 `STATIC_ONLY` / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`。

### K.4 合同复核

| 检查项 | 静态证据 | 结论 |
|---|---|---|
| 直接 platform 收窄 | `_apply_exclusive_lock` / `_release_exclusive_lock` / `_acquire_barrier_lock` 均 `if sys.platform == "win32"` | **通过** |
| Win=msvcrt / 非 Win=fcntl | 分支内 `import msvcrt` / `import fcntl`；无模块顶层无条件 import | **通过** |
| 锁语义不变 | apply：`lseek(0)`+`LK_NBLCK,1` / `LOCK_EX\|LOCK_NB`；release：`lseek(0)`+`LK_UNLCK,1` / `LOCK_UN`；EACCES/EAGAIN/EWOULDBLOCK→`BARRIER_WRITER_BUSY` 否则 `BARRIER_LOCK_IO_FAILED`；Win apply 后 `return` | **通过** |
| 无 Any/ignore/fallback | 无 `Any`、无 `type: ignore`；无第三平台 fallback；仅既有 `cast`（非 ignore） | **通过** |
| `_IS_WIN32` 移除 | 仅注释提及「no _IS_WIN32」；无常量定义/引用 | **通过** |
| `_digest` Mapping | `def _digest(payload: Mapping[str, object])` → `canonical_json_bytes(payload)` | **通过** |
| caller canonical mapping | 全部 `_digest({...})` 字面 dict；无 `object`/`bytes` 宽传 | **通过** |

### K.5 本轮 Findings

**No findings.**

### K.6 本轮新增对抗性反例（实现者未单独成用例）

**标题：在非 win32 分析面上，`_apply_exclusive_lock` 不得在未 `import fcntl` 前引用 `fcntl.flock`；也不得用模块级 `_IS_WIN32: Final[bool]` 再次封死窄化**

实现者已改为分支内 import + 直接 `sys.platform`。

**静态捕获：** VALIDATION6 mypy 证据中的 `Name "fcntl" is not defined` 正是旧 `_IS_WIN32` 路径的失败面；当前控制流在 non-Windows 臂先 `import fcntl` 再 `flock`，Win 臂先 `import msvcrt` 再 `locking` 并 `return`，避免跨臂名泄漏。**通过。**

### K.7 残留风险（不构成 FAIL）

- STATIC_ONLY：类型返工后须中央重跑 mypy 证明原三错清零；cold/scope 仍未跑。
- focused 绿是返工前证据链一环；不把本轮写成已重跑绿测。
- 仍 `SUBSTRATE_ONLY` / `UA-M4-006 OPEN`；不宣称 Linux Gate。

### K.8 未运行检查清单

- [ ] 本轮未跑 Python / pytest / Ruff / mypy / cold / scope / 提交

### K.9 REVIEW_READY

```
REVIEW_READY
verdict: REVIEW_PASS
phase: VALIDATION6-TYPE-RE-REVIEW (sys.platform lock narrowing + _digest Mapping)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun this round
history_A..J: preserved
validation6_evidence:
  root: artifacts/agent_runs/m4-b1a-validation6-20260825T174500Z-c63e
  focused_sha: 65BE40188EDE4CA5CF8CCB3C21517309F9C9143054C1119E20E5277B769E9835
  ruff_sha: 82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18
  mypy_sha: 6C32100322FCACBCF6ECC7565CA6FFFCF69F67E749233F5F56E526CCBA7FAA25
  combo: focused+Ruff PASS; mypy 3 errors STOP (pre-fix)
  cold_scope: not in evidence / not claimed
scope_bytes:
  changed: session_barrier.py + task §9.8 + delivery only
this_round:
  sys_platform_direct_msvcrt_fcntl_lazy: pass
  lock_offset_mode_nb_error_order_unchanged: pass
  no_Any_type_ignore_fallback_dead__IS_WIN32_removed: pass
  _digest_Mapping_callers_canonical: pass
  evidence_sha_and_no_linux_gate_whole_pack_claim: pass
  p0: 0
  p1: 0
adversarial_new: non-win32 arm must import fcntl before flock; must not revive _IS_WIN32 Final bool (static pass)
ua_m4_006: OPEN
substrate_only: yes
linux_gate_pass: no
whole_pack_pass: no
next: manager may request mypy re-run; still SUBSTRATE_ONLY / UA-M4-006 OPEN
```

---

## L. EVIDENCE_REVIEW（第六名独立静态续验，本轮）

### L.0 范围与方法

只读核对：

1. 任务书 §9.9、交付 `EVIDENCE_DOC_CLOSE`、§A–§K 历史
2. VALIDATION6 evidence root：`artifacts/agent_runs/m4-b1a-validation6-20260825T174500Z-c63e`（组合 pytest/Ruff 结果）
3. POSTFIX VALIDATION7 evidence root：`artifacts/agent_runs/m4-b1a-postfix-validation7-20260825T181500Z-d91f`（root/SHA/stdout/summary）
4. `.gitignore` `artifacts/*`、当前 `git status --short`（exact11 范围；evidence 不入提交）

**本轮零执行：** 未跑 Python / pytest / Ruff / mypy / cold / SQLite / 网络 / 提交。

### L.1 文档 SHA 绑定

| 文档 | 声称 SHA256 | 本轮重算 | 结论 |
|---|---|---|---|
| 任务书 | `437A52D40F6F09D5674FFEC591E672074D479D14F55C55141251A728421BA76E` | 同左 | **匹配** |
| 交付报告 | `0A7A5DA24F16C1C86BF0914F95388F2ABB0A178022AE6D286A878A05B9F974B3` | 同左 | **匹配** |

### L.2 VALIDATION6（中央接受组合）

磁盘证据 `m4-b1a-validation6-20260825T174500Z-c63e` 可读 stdout：

| 阶段 | 证据摘要 | 结论 |
|---|---|---|
| 03-execution-targeted | `6 passed` | **PASS** |
| 04-broker-targeted | `4 passed` | **PASS** |
| 05-focused-three | `264 passed, 6 skipped` | **PASS**（与 §9.9 / 交付「full 264+6skip」一致） |
| 06-ruff-exact8 | `All checks passed!` | **PASS** |
| 07-mypy-production5 | `exit=1`（历史三错） | **不计入本条中央接受绿**；§9.9 明示 TYPE 返工闭合，不另宣称 Linux Gate |

**说明：** V6 stage-summary 仍保留 mypy `exit=1` 历史快照；中央接受的是 execution/broker/full/Ruff 组合绿 + TYPE 后 mypy 由 V7 证明，文档边界诚实。

### L.3 POSTFIX VALIDATION7

| 项 | 声称 | 本轮重算/读证 | 结论 |
|---|---|---|---|
| evidence root | `…/m4-b1a-postfix-validation7-20260825T181500Z-d91f` | 目录存在；`stage-summary` 01–08 均 `exit=0` | **PASS** |
| session | 24+1skip；SHA `624E2A57…E08D82` | stdout=`24 passed, 1 skipped`；SHA 匹配 | **PASS** |
| Ruff | SHA `82B3E6A6…6B4F18` | `All checks passed!`；SHA 匹配 | **PASS** |
| mypy5 | SHA `718DF785…3EC96A` | `Success: no issues found in 5 source files`；SHA 匹配 | **PASS** |
| cold | SHA `DCF12C4F…5FC5BF4` | 五条 production 路径冷导入列表；SHA 匹配 | **PASS** |
| scope | SHA `97030AD4…8B5281` | exact 改动面 + 三文档 untracked；SHA 匹配；`07-scope-diff-check` 空/exit=0 | **PASS** |
| summary / runner | `201F6D81…7CD372` / `CE3E5089…93D92D` | 均匹配 | **PASS** |
| process / residue | 无 cache/temp/`0xF00` | `08-process-residue` stdout 空、exit=0；runner 清理 `.tmp/session-barrier`+`mypy-cache`；当前 worktree **无** `.tmp` | **PASS** |

**注：** V7 `06-scope-status` 捕获时可见瞬时 `?? .tmp/`（runner 中途 temp）；finally 清理后无残留；与「无 temp/`0xF00` process residue」合同一致，不构成 FAIL。

### L.4 exact11 scope 与 ignored evidence

- 当前 `git status --short`：**仅** exact 生产/测试 8 路径 + task/delivery/review 三文档；**无** `artifacts/agent_runs/**` 出现在 status。
- `.gitignore`：`artifacts/*`（evidence 不提交）。
- 交付 §7：本轮 EVIDENCE_DOC_CLOSE 仅改任务书/交付；production/tests/review 字节未改——与「只读复验、证据树 ignored」叙述一致。

### L.5 终态边界

任务书 §9.9 / 交付 `EVIDENCE_DOC_CLOSE` 均写明：

- Windows 开发验证闭合；
- **仍** `SUBSTRATE_ONLY / UA-M4-006 OPEN`；
- **未验证** formal all-writer / B1B / PAPER / soak / Linux Gate。

本轮复验确认文档**未**越界宣称上述项。

### L.6 本轮裁决

**`EVIDENCE_REVIEW_PASS`**

VALIDATION6 组合（execution6 / broker4 / full264+6skip / Ruff）与 V7 root/SHA/stdout/summary/residue 证据链与 task/delivery 绑定一致；exact11 与 ignored evidence 叙述准确；终态仍 `SUBSTRATE_ONLY / UA-M4-006 OPEN`。无新增 P0/P1。本轮 STATIC_ONLY、零执行。

### L.7 Findings

**No findings.**

### L.8 未运行检查清单

- [ ] 本轮未跑 Python / pytest / Ruff / mypy / cold / scope / 提交

### L.9 REVIEW_READY

```
REVIEW_READY
verdict: EVIDENCE_REVIEW_PASS
phase: EVIDENCE_REVIEW (VALIDATION6 combo + POSTFIX VALIDATION7)
task: M4-B1A-SESSION-BARRIER-SUBSTRATE
reviewer: 6th independent static continued (did not implement)
static_only: all checks unrun this round
history_A..K: preserved
task_sha: 437A52D40F6F09D5674FFEC591E672074D479D14F55C55141251A728421BA76E
delivery_sha: 0A7A5DA24F16C1C86BF0914F95388F2ABB0A178022AE6D286A878A05B9F974B3
validation6_combo:
  execution6: pass
  broker4: pass
  full_264_passed_6_skipped: pass
  ruff: pass
  mypy_historical_exit1_in_v6_tree: noted; TYPE+V7 close; no linux_gate claim
validation7:
  root: artifacts/agent_runs/m4-b1a-postfix-validation7-20260825T181500Z-d91f
  identity_session24+1skip_ruff_mypy5_cold_scope_process: all pass
  session_sha: 624E2A57945F90289F51546EDBCFEF6E9E5DF30FF6C4DEA22507689995E08D82
  ruff_sha: 82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18
  mypy_sha: 718DF785EFBBD4B57E63B5F64AFF2C5B5592E433447681F759B307F97A3EC96A
  cold_sha: DCF12C4F22BE07B373EFBF84EC041120A94A1E80544C16CAF539D57F25FC5BF4
  scope_sha: 97030AD4C8BC2E0EB148A8629737B5E169A2BC4A3FEB087AF6BAC7C0048B5281
  summary_sha: 201F6D8148084C9D2034E20D9B92A65BB5F70AD35B86E685926D690B7E7CD372
  runner_sha: CE3E508955916213C0E127A06EADFBB218341E449DE463CD8FF66271D693D92D
  residue_cache_temp_0xF00: pass
exact11_scope_and_ignored_evidence: pass
windows_dev_closed: yes
formal_all_writer_b1b_paper_soak_linux_gate: not claimed / not verified
ua_m4_006: OPEN
substrate_only: yes
p0: 0
p1: 0
```

---

## M. DOC_NORMALIZATION_REVIEW_ONLY（第六名独立静态续验，本轮）

### M.0 范围与方法

只读：`AGENTS.md`、任务书、交付、本报告 §A–§L、VALIDATION7 证据 SHA。唯一可写：本报告。未改 taskbook/delivery/production/tests/Git index/evidence。未跑 Python/pytest/Ruff/mypy/cold/提交。

### M.1 行尾空白 / 硬换行 / EOF

| 文档 | 行尾空白 | 说明 |
|---|---|---|
| 任务书 | 0 | 已含显式 `<br>`；本轮只读 |
| 交付报告 | 0 | 已含显式 `<br>`；本轮只读 |
| 本报告（规范化后） | 0 | 去除全部行尾空白；列表/清单原 MD 硬换行改为自然块元素（不另造 `<br>`）；EOF 恰一换行 |

本报告**无**自指/prefix SHA 段；按合同不发明。

### M.2 文档 SHA 与证据

| 项 | 结论 |
|---|---|
| 任务书当前 SHA256 | `1CFBCECA40A4E5CD93061438E7F2544898C4709A6F57A63F7D4FA656924D4152` |
| 交付当前 SHA256 | `59D045C3A7BB07233988F8844AAA274A9EE018A385FA42EAA2A0E83804178065` |
| §L.1 EVIDENCE_REVIEW 时代指纹 | task=`437A52D40F6F09D5674FFEC591E672074D479D14F55C55141251A728421BA76E` / delivery=`0A7A5DA24F16C1C86BF0914F95388F2ABB0A178022AE6D286A878A05B9F974B3`（peer 文档 DOC 空白规范化后文件字节变化；业务措辞/证据/边界未改） |
| V7 session/summary 等 evidence SHA | 与 §L / 任务书 §9.9 / 交付 EVIDENCE_DOC_CLOSE **仍匹配** |
| 语义 / `SUBSTRATE_ONLY` / `UA-M4-006 OPEN` | **未漂移**；不宣称 formal all-writer / B1B / PAPER / soak / Linux Gate |

### M.3 裁决

**DOC_REVIEW_PASS**（仅文档卫生与绑定重算；不等于运行验证、Gate 或 UA-M4-006 关闭）
