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

