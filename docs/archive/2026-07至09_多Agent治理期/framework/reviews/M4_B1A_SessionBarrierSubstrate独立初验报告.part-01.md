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

