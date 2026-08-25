# M4-B1A Session Barrier Substrate 任务书

状态：`TASK_READY / STATIC_ONLY / UA-M4-006 OPEN`

## 1. 身份与职责

- task id：`M4-B1A-SESSION-BARRIER-SUBSTRATE`
- exact base：`c124ec57e254672cd371ea04a732515a59c2fad1`
- branch：`codex/m4-b1-shared-session-close-barrier`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1-shared-session-close-barrier`
- 经理：框架主 Agent，独占维护本任务书。
- 实现：一名全新外部 Cursor Agent，只写实现白名单和唯一交付报告。
- 初验：另一名未参与实现的全新外部 Cursor Agent；实现和测试只读，只写唯一初验报告。
- 本包终态上限：`SESSION_BARRIER_SUBSTRATE_VALIDATED`。不得表述为 all-writer closure、UA-M4-006、PAPER 或 28 日 soak 完成。

## 2. 背景与目标

UA-M4-006 已批准“新 root + 新 barrier epoch + 新 soak run”。旧 RUN-0D2 v1 只保留为 non-formal 历史，不能 adoption 或 backfill。当前 OMS、broker 和 evidence 没有共同 `OPEN/CLOSING/CLOSED` 状态、anchored OS lock、close token 与不可逃逸 write lease。

本包只建立底层 substrate：

1. OMS schema v9 中唯一 session barrier row 与单向状态机；
2. 绑定 root/epoch/session/account/store/gateway/config identity 的 close token；
3. 同一 anchored OS lock 下、覆盖完整 transaction commit/rollback 生命周期的 process-local write lease；
4. `ExecutionStore` 和 `PaperBrokerStore` 的每个底层写事务可选择受 barrier 约束；未配置 barrier 的既有 non-formal 行为不变。

本包不接 formal composition、gateway、daily operator、soak 或 EOD closure；这些属于基于本 API 的后续 B1B。

## 3. 精确白名单

exact11：

1. `src/quant/execution/session_barrier.py`（新）
2. `src/quant/execution/migrations/__init__.py`
3. `src/quant/execution/migrations/v009_session_barrier.py`（新）
4. `src/quant/execution/store.py`
5. `src/quant/execution/paper_broker_store.py`
6. `tests/unit/test_session_barrier.py`（新）
7. `tests/unit/test_execution_store.py`
8. `tests/unit/test_paper_broker_store.py`
9. `docs/framework/tasks/M4_B1A_SessionBarrierSubstrate任务书.md`（经理独占）
10. `docs/framework/deliveries/M4_B1A_SessionBarrierSubstrate交付报告.md`（实现者独占）
11. `docs/framework/reviews/M4_B1A_SessionBarrierSubstrate独立初验报告.md`（初验者独占）

实现者不得修改路径 9、11；初验者不得修改路径 1–10。所有 formal composition、gateway、daily、soak、reconcile、config、`__init__.py`、roadmap 和共享 SSOT 只读。

## 4. 状态与身份合同

### 4.1 OMS 唯一事实来源

- schema v9 新增唯一、规范化的 session barrier 表/行；状态只允许 `OPEN`、`CLOSING`、`CLOSED`。
- 主键与 canonical payload 必须绑定：barrier schema/version、barrier epoch、session date、account identity、OMS store identity、broker store identity、gateway identity、runtime/config identity、anchored lock identity、created/transition UTC、current state、close token identity。
- `OPEN → CLOSING → CLOSED` 是唯一顺序；禁止回到 OPEN、跳过 CLOSING、重复不同 token 关闭、跨 session/epoch/root 复用。
- exact replay 只能返回同一 canonical row；任何同 key 异 payload、未知未来 state/schema、额外 row、缺 row、部分字段或 index/payload 漂移均 fail closed。
- 新 root 初始化时创建 OPEN；本包禁止对旧 v1 root 自动建 OPEN、adopt、backfill 或静默升级为 formal barrier root。

### 4.2 Close token

- close token 的 durable identity 必须由上述 barrier identity、预期 predecessor state、session、epoch 和 caller-provided no-secret nonce/challenge 的 canonical bytes 确定；不得只使用随机字符串、wall-clock 或 caller 自报 label。
- durable row只保存 token identity/canonical non-secret fields，不保存可用来伪造 lease 的进程内 secret/capability。
- 同一 CLOSING token exact replay 幂等；不同 token、不同 session、不同 epoch、不同 root 或不同 predecessor 一律冲突。

## 5. Anchored OS lock 与 write lease

- `session_barrier.py` 是 lock path、object identity、state transition 和 lease mint/verify 的唯一实现；`store.py` 与 `paper_broker_store.py` 不复制锁算法。
- lock 位于由新 root 身份绑定的固定普通文件路径；验证所有父路径和 leaf，拒绝 symlink、junction/reparse、hardlink alias、替换、非普通文件和 object identity 漂移。
- Windows 使用真实可用的独占文件锁；非 Windows fallback 保持可导入且使用平台适配锁，不得把 Windows 结果写成 Linux Gate。
- lease 必须是 module-private factory 创建的 exact process-local 类型，不可 pickle/copy/deepcopy/dataclasses.replace；不能由 bool、raw token、Protocol、subclass、`object.__new__` 或字段伪造获得可信性。
- lease 绑定 exact barrier capability、root/epoch/session、state、lock object identity、transaction nonce 与 owner thread/process；离开 context、释放 lock、commit/rollback 后立即失效，不能缓存、重放或跨 store 使用。
- 所有受控写 transaction 必须先持同一 anchored lock，再 fresh 读取 OMS barrier state并验证 lease；锁与 lease 必须覆盖数据库 `BEGIN IMMEDIATE` 至 commit/rollback 完成的整个区间，不能只包调用前检查。

## 6. 两个 store 的底层接入

### 6.1 ExecutionStore

- 未配置 barrier 的现有 `ExecutionStore`/`ExecutionRepository` 行为、bytes、错误码和 migration replay 保持。
- formal/barrier-enabled store 初始化必须是新 root/schema v9，并绑定唯一 barrier capability；所有 repository 写方法只能在有效 OPEN write lease 下执行。
- CLOSING 期间普通 repository writer 全拒；只有后续 B1B 的 closure 专用 lease 类别可写，但本包不实现 formal closure sequence。
- CLOSED 期间所有写拒绝，read/recovery/query 保持只读可用。
- transaction commit 前再次验证 lock/lease/state，避免检查后状态漂移；异常 rollback 后 lease 失效且 barrier row不被部分推进。

### 6.2 PaperBrokerStore

- 未配置 barrier 的 development/non-formal store行为保持。
- barrier-enabled broker store 必须绑定与 OMS 完全相同的 root/epoch/session/account/store/gateway/config 和 anchored lock identity；任何 mismatch 在写前拒绝。
- `persist_operation`、zero-command finality、finalize session、journal/anchor 等所有底层写事务都必须在有效 lease 下覆盖 commit/rollback；不能只保护 public helper 的一部分。
- 本包不宣称 broker DB 是 barrier SSOT，也不在 broker DB 建第二套状态机；状态只从 OMS v9 fresh 读取。

## 7. 稳定失败语义

至少区分并脱敏：

- barrier 未配置/缺失/多行/损坏；
- barrier identity/root/epoch/session/store/gateway/config 漂移；
- 非法 state transition、reopen、skip-close、close token conflict；
- lock path/对象/reparse/hardlink/替换漂移；
- lease missing、forged、expired、escaped、wrong store/state/session/thread；
- writer busy、state stale、commit/rollback failure。

不得泄露绝对路径、SQLite payload、token material、系统用户名或底层异常 cause/context。既有非formal稳定错误码不得被无关重分类。

## 8. 必须覆盖的反例

至少覆盖：

1. OPEN 正常写、CLOSING/CLOSED 普通写拒绝；
2. OPEN→CLOSING→CLOSED exact replay与 reopen/skip/token conflict；
3. 同一 barrier 并发 writer 与 close：锁决定唯一线性顺序，不出现检查后写入；
4. lease 离开 context 后、commit 后、rollback 后、跨线程、跨 store、跨 session/epoch 重放；
5. bool/raw token/Protocol/subclass/direct constructor/`object.__new__`/copy/deepcopy/pickle/replace 伪造；
6. lock symlink/reparse/hardlink、leaf replacement、parent replacement、object identity drift；
7. execution 与 broker store identity 任一不一致；
8. migration v8→v9、fresh v9、interrupted migration、future schema、extra/missing barrier row；
9. 旧 v1 root 无 barrier 时不能被默认为 OPEN 或 formal；
10. 未配置 barrier 的既有 store 回归 bytes/行为不变；
11. writer 异常 rollback 零部分经济写、lease 失效、state 不误推进；
12. broker 所有写方法逐一证明受 lease，而非只覆盖 finalize。

独立初验必须增加至少一个实现者未使用的并发或能力伪造反例，并核对没有在两个 store 复制第二套锁/状态规则。

## 9. 验证合同

当前阶段为 `STATIC_ONLY`：实现者先写代码、测试和交付报告，不运行 Python、pytest、Ruff、mypy、SQLite probe 或真实 I/O。独立静态初验通过后，经理向中央申请串行 CPU8–11 验证。

拟定顺序：

1. exact worktree import identity；
2. `tests/unit/test_session_barrier.py`；
3. `tests/unit/test_execution_store.py` 中 migration/barrier定向节点；
4. `tests/unit/test_paper_broker_store.py` 中 barrier定向节点；
5. 三文件完整 focused 回归；
6. Ruff exact production/tests；
7. mypy 五个 production 模块；
8. cold import；
9. exact11 scope、diff-check、temp/cache/process residue。

首失败立即 STOP；不得借验证扩到 formal composition、PAPER、soak 或旧 root。

### 9.1 VALIDATION1 中央批准返工（Windows concrete Path）

| 项 | 内容 |
|---|---|
| 现象 | identity PASS 后 `tests/unit/test_session_barrier.py` **20 failed / 1 skipped**；根因集中为 `_require_absolute_path` / capability unpack 使用 `type(value) is Path`，而 Windows 上 `Path()` 为 `WindowsPath` |
| 根因 | 以抽象 `pathlib.Path` 作 exact type 谓词，平台 concrete 子类全部被拒 |
| 规则 | 中央合同最小修：两处 guard 仅接受当前平台 `type(Path())`；保持绝对路径与既有 directory/containment/symlink/reparse/identity；禁止 `isinstance` 放宽与字符串转换；不得改迁移/事务/锁状态机 |
| 最小复现 | Windows：`type(Path('C:/x')) is Path` → False；factory/`unpack` 对合法 native absolute Path 失败 |
| 新增测试 | `test_lock_root_concrete_path_guards_native_and_rejects_nonconcrete`：native 正向；concrete subclass；PurePath/PureWindowsPath/PurePosixPath；duck 伪 Path；相对 Path；两 guard 共用 `_CONCRETE_PATH_TYPE` |
| 通过条件 | native absolute 通过 factory+unpack；非 concrete / 相对一律 fail-closed；两 guard 谓词一致 |
| evidence root | `artifacts/agent_runs/m4-b1a-validation1-20260825T204700295` |
| session stdout SHA | `6b5ef5b7b53e70ff3be16a1a68b7457d286881f0f11a5a36e3eae1a763a3110a` |

### 9.2 VALIDATION2 中央批准返工（测试面 F1–F3；生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V2-F1 | `dataclasses.replace(capability/lease)` 断言 `TypeError`，与运行时经 `__init__` 失败的 `SessionBarrierError` 不一致 | 测试期望绑定了 `__replace__` 的 TypeError，而校验环境 `replace` 走构造/`__init__` 抛稳定 barrier 码 | 精确断言 `SessionBarrierError` + `BARRIER_CAPABILITY_INVALID` / `BARRIER_LEASE_INVALID`；copy/deepcopy/pickle 仍 `TypeError`；**不改生产** | `replace(cap, …)` / `replace(lease, …)` | 更新 capability/lease replace 断言 | 两 replace 命中对应码；copy/deepcopy/pickle 仍 TypeError |
| V2-F2 | transition 顺序测试 `monkeypatch` `Connection.execute` 失败或不可靠 | execute 可能只读/不可替换；观测应走 SQLite 追踪 API | 用 `Connection.set_trace_callback` 观察 BEGIN/COMMIT/ROLLBACK；**仅** monkeypatch 模块 `hold_session_barrier_lock` | 顺序探针 | `test_transition_acquires_barrier_lock_before_begin` | lock→begin→commit→unlock |
| V2-F3 | 并发 writer 跨线程共用 handle/conn，或依赖 `check_same_thread=False` | lease `owner_thread_id` 与 SQLite 连接线程亲和 | writer 线程内自建 `conn2`、同线程 `issue handle→lease→BEGIN`；主线程只竞争 `transition`；禁止 `check_same_thread=False` | 双线程 OS 锁竞争 | `test_writer_and_transition_lock_order_no_deadlock` | 持锁时 transition=`BARRIER_WRITER_BUSY`；释放后可 CLOSING |

- evidence / artifacts：`artifacts/agent_runs/m4-b1a-validation2-20260825T210000000`
- session stdout SHA：`bff0b741aaf26c5390d2cd6880033c7d1f1bb06d08365514462a601686b38dc4`
- 生产 / 迁移 / store / 其他测试：**字节不变**；仅改 `tests/unit/test_session_barrier.py` 与任务书/交付

### 9.3 VALIDATION2-F5 STATIC_ONLY 最小返工（测试面；生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V2-F5 | `writer_ready.wait(timeout=5)` 满等后仅泛化 `AssertionError`；join 后不断言线程退出；cleanup 二次异常可掩盖主失败；无 ready 前 issue/lease/BEGIN 失败反例 | 成功路径编排把「未 ready」一律当超时断言，未 fail-fast 读 `errors`；cleanup 非嵌套隔离；失败面未注入 | ready 前失败须 **&lt;1s** 可观测稳定码/异常；短 join/释放；成功与失败 join 后均 `assert not thread.is_alive()`；cleanup 嵌套 try/finally 保证 `conn2.close`，二次异常只追加不覆盖主码；禁止 5s 泛化 AssertionError | writer 在 `writer_ready.set()` 前分别注入 issue / lease / BEGIN 失败 | 修 `test_writer_and_transition_lock_order_no_deadlock`；新增 `test_writer_pre_ready_{issue,lease,begin}_failure_fail_fast_exposes_code`；辅助 `_await_writer_ready_or_expose_failure` / `_run_writer_until_pre_ready_failure` / `_writer_cleanup_handle_and_conn` | 成功路径仍 BUSY→CLOSING；三反例真实码、线程退出、无 handle/conn 泄漏；STATIC_ONLY 未跑 pytest |

- evidence root：`artifacts/agent_runs/m4-b1a-validation2-20260825T210000000`
- session stdout SHA：`bff0b741aaf26c5390d2cd6880033c7d1f1bb06d08365514462a601686b38dc4`
- 白名单：**仅** `tests/unit/test_session_barrier.py`、本任务书、交付报告；production/migration/store/其他测试/review 报告字节不变
- 禁止：Python / pytest / Ruff / mypy / cold / SQLite / network / 提交

### 9.4 VALIDATION2-F6 STATIC_ONLY 最小返工（测试面；生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V2-F6 | 三 pre-ready 反例用 `conn2.close = tracking_close` 替换原生 `Connection.close`；且 wrapper 先 `closed.append` 再 close；cleanup 与主码同 list 前缀并存，可冒充/污染主通道 | 用实例赋值观测 close，重演 V2-F3 只读 native 方法风险；bookkeeping 顺序错误；主/清理通道未隔离 | **禁止**对原生 `sqlite3.Connection` 实例 `close`/`execute` 做替换、赋值或 monkeypatch；`closed` 仅在 `sqlite3.Connection.close(conn2)` **成功返回后** append/set；invalidate/close 失败写入独立 `cleanup_errors`（或前缀通道），主通道仅保留 issue/lease/BEGIN 稳定码；模块函数注入可保留 | 去掉实例 `close=` 后，三反例须仍 &lt;1s 暴露真实主码并证明 close/handle 清理 | 修 `_writer_cleanup_handle_and_conn` + 三 `test_writer_pre_ready_*`；成功 BUSY→CLOSING 保持 | 无 native close/execute 替换；三反例主码精确、线程退出、handle 清除、`closed==[True]` 且仅成功 close 后置位；`cleanup_errors` 不覆盖主码；STATIC_ONLY 未跑 |

- evidence root：`artifacts/agent_runs/m4-b1a-validation2-20260825T210000000`
- session stdout SHA：`bff0b741aaf26c5390d2cd6880033c7d1f1bb06d08365514462a601686b38dc4`
- 白名单：**仅** `tests/unit/test_session_barrier.py`、本任务书、交付报告；production/migration/store/其他测试/review 报告字节不变
- 禁止：Python / pytest / Ruff / mypy / cold / SQLite / network / 提交

### 9.5 VALIDATION3 STATIC_ONLY 最小返工（paper broker 测试面；生产字节不变）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V3 | `test_broker_all_writers_require_open_lease` 用 `tracked_lease` 包裹并再次进入真实 `broker._barrier_lease`；观测可改变/放大非重入锁语义，并在持锁期触碰 `gateway_identity`/`verify_fresh`/`_sync_anchors` 路径 | 在实例 `_barrier_lease` 外包一层再调 `real_lease()`，等于观测器强制二次进入真实 lease 路径；非重入 OS lock 下易嵌套/挂起；用假 lease/改生产可重入会绕过合同 | **禁止**包裹/再入真实 `_barrier_lease`；不得改生产 locking、不得改成可重入、不得用假 lease/重复值绕过；在模块 `hold_open_write_lease` 边界观测；证明 record/update 等 writer **先**取得真实 OPEN lease；观测持锁期不得读取触发 `verify_fresh`/`_sync_anchors` 的属性；新增观测器自身不导致第二次 lease 进入回归；保留无 lease、错 session/identity、CLOSING/CLOSED、遗漏 writer fail-closed | 替换 `tracked_lease` 后，OPEN writer/`verify_fresh` 锚点 UPDATE 仍见真实 enter 且 `depth==1` | 重写 `tests/unit/test_paper_broker_store.py` 中该测试的观测；任务/交付五段式 | 无 `_barrier_lease` 包裹；`max(enter_depth)==1`；idle 观测 0 enter；CLOSING/CLOSED/identity/无 barrier 保留；生产字节不变；STATIC_ONLY 未跑 |

- evidence root：`artifacts/agent_runs/m4-b1a-validation3-20260825T143500Z-c91e`
- 04 stdout SHA：`1092d8a472dff6950b897d065f5232e02e496bbeae9e5c603e429f7c07aed2ac`
- 白名单：**仅** `tests/unit/test_paper_broker_store.py`、本任务书、交付报告；production/migration/store/其他测试/review 报告只读且字节不变
- 禁止：Python / pytest / Ruff / mypy / cold / 真实 I/O / 提交

### 9.6 VALIDATION4 production reentrancy STATIC_ONLY 返工

| ID | 现象 | 根因 | 不变量 | 最小复现 | 规则 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|---|
| V4 | 持 OPEN lease 的 `_verify_barrier_lease` 读取 public `gateway_identity` → `verify_fresh`/`_sync_anchors`，可在非重入 OS lock 下再取 lease（depth&gt;1 / 挂起） | lease 内身份核对错误地走会触发 fresh/sync 的 public property，而非 bind 时已验证绑定的 raw identity | 持 lease 内部验证不得调用会 `verify_fresh`/`_sync_anchors`/再取 lease 的 public property；lease gateway identity 与 store 绑定 identity **exact** 比较保留；不删比较、不信任 bool、无可变缓存、不可重入锁、不吞 BARRIER；public `gateway_identity` fresh 语义不变；一切 writer 真实 lease depth≤1（持锁并发 depth exact 1） | OPEN writer 持锁期访问 `self.gateway_identity` 且锚点需 sync → 嵌套 `hold_open_write_lease` | bind 经 `verify_fresh` 后写入 module-private `_bound_gateway_identity`（禁止外部注入）；`_verify_barrier_lease` 只比对该 raw 字段；public property 仍 `verify_fresh`+digest | 更新 `paper_broker_store.py`；`test_broker_all_writers_require_open_lease`：depth exact1、持 lease 不调 public gateway、bound/lease drift fail-closed；保留 CLOSING/CLOSED/unconfigured/cross-session/identity；observer 不改变 hold | depth exact1；`public_gw_during_lease==[]`；drift→`BARRIER_IDENTITY_DRIFT`；public fresh 不变；STATIC_ONLY 未跑 |

- evidence root：`artifacts/agent_runs/m4-b1a-validation4-20260825T153000Z-e84c`
- 04 stdout SHA：`1e6236f7e770993bfc4e384dc9cf1e9b78e27376b3653567e7ec9cbe1202c57e`
- 白名单：**仅** `src/quant/execution/paper_broker_store.py`、`tests/unit/test_paper_broker_store.py`、本任务书、交付报告；review 只读
- 禁止：Python / pytest / Ruff / mypy / cold / 提交

### 9.7 VALIDATION5-FIXTURE STATIC_ONLY 返工（execution_store 降级 fixture）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V5 | v3/v7 降级 fixture 仅压低 `schema_version`、未去掉已存在的 `session_barrier`；reopen 跑真实 v009 `CREATE TABLE session_barrier` → `MIGRATION_FAILED` | 当前库先以 v9 打开已建 barrier 表；降级模拟未 DROP 该表；生产 v009 故意无 `IF NOT EXISTS`、失败须 fail-closed | fixture 在设旧 version **前**显式 `DROP TABLE session_barrier`；**不**手工删 indexes；**不**改 production v009 / 不加 `IF NOT EXISTS` / 不吞 `MIGRATION_FAILED`；reopen 后断言真实 migration 重建空表、无 barrier row、未启用，且旧数据保留 | `_open`→写行→close→不 DROP barrier 即 `UPDATE schema_version` 到 3/7→`_open` | `test_v3_upgrade_adds_empty_ledger_tables_without_forging_context`；`test_v7_database_upgrade_adds_only_approval_substrate_and_preserves_rows` | `schema_version==CURRENT`；`session_barrier_enabled is False`；`COUNT(*)==0`；`BARRIER_MISSING`；legacy 行/空 approval/ledger 断言保持；STATIC_ONLY 未跑 |

- evidence tag：`M4-B1A-VALIDATION5-FIXTURE`
- evidence root：`artifacts/agent_runs/m4-b1a-validation5-20260825T171500Z-b72d`
- 阶段结果（原生，不冒充整包 PASS）：identity / session17 / execution-targeted6 / broker-targeted4 **PASS**；full-three=**262 passed / 6 skipped / 2 failed**
- 05 stdout SHA：`FCF3989D22EC5B7DCA1C0F2292B7FFAE6CEC780937DE489D1C7B92DDD4657E4E`
- 05 stderr（empty）SHA：`E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`
- summary SHA：`085694369A74735F217ED7D81A382C85F6000CC37F6D5FB5614D7D069351A891`
- runner SHA：`E3A3CB737A260C29C4EF52986693D9AB75B3ACC9D12CC6FD4F8E0D474C408FBC`
- 白名单：**仅** `tests/unit/test_execution_store.py`、本任务书、交付报告；production v009 / store / 其他测试 / review 只读
- 禁止：Python / pytest / Ruff / mypy / cold / SQLite 探针 / 提交
- 本轮 STATIC_ONLY 证据绑定**不**宣称整包 PASS（full-three 仍 2 failed）

### 9.8 VALIDATION6-TYPE STATIC_ONLY 返工（session_barrier 类型/平台锁）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增/修改测试 | 通过条件 |
|---|---|---|---|---|---|---|
| V6 | 组合绿（focused+Ruff）但 mypy 三错：平台锁经 `_IS_WIN32` 分支使 `msvcrt`/`fcntl` 不可窄化；`_digest(payload: object)` 与 `canonical_json_bytes(Mapping[str, object])` 不匹配 | `_IS_WIN32: Final[bool]` 对 mypy 非 platform 特化；digest 参数过宽 | 锁路径用直接 `sys.platform == "win32"`（或 non-Windows 惰性 import）；Windows=`msvcrt`、非 Windows=`fcntl`；offset/mode/nonblocking/错误码/finally **不变**；禁用 Any/`type: ignore`/fallback；不宣称 Linux Gate；无引用则删 `_IS_WIN32`；`_digest` 收窄 `Mapping[str, object]`，canonical bytes/keys/values/errors 不变；保持既有 Win/POSIX 静态可达与 mapping 合同 | mypy 对 `_apply_exclusive_lock`/`_release_exclusive_lock`/`_digest` | 仅改 `session_barrier.py`；既有 Win/POSIX 测试保持未改 | 三 mypy 错清零意图；锁语义字节级不变；无 Linux Gate 宣称；STATIC_ONLY 未跑 |

- evidence（组合绿 + 三 mypy 错误，**不**冒充整包/Gate PASS）：
  - focused SHA：`65BE40188EDE4CA5CF8CCB3C21517309F9C9143054C1119E20E5277B769E9835`
  - Ruff SHA：`82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18`
  - mypy SHA：`6C32100322FCACBCF6ECC7565CA6FFFCF69F67E749233F5F56E526CCBA7FAA25`
  - summary SHA：`0A5259AC6AFDD31700E91EE5509F041BD462A7CE6E7BDA0CA641A57399FEC184`
  - runner SHA：`0CCAA7DF14B5E5D24FF6E8DF331EAE122639A44ACBE20F2C1F9771E8234C3050`
- 白名单：**仅** `src/quant/execution/session_barrier.py`、本任务书、交付报告；migration/store/其他测试/review 只读
- 禁止：Python / pytest / Ruff / mypy / cold / 提交

### 9.9 EVIDENCE_DOC_CLOSE — 中央接受的组合证据（仅文档）

**状态：** Windows 开发验证闭合；仍 `SUBSTRATE_ONLY / UA-M4-006 OPEN`。<br>
**未验证：** formal all-writer / B1B / PAPER / soak / Linux Gate。

#### VALIDATION6（中央接受的组合结果）

- execution-targeted6 **PASS**
- broker-targeted4 **PASS**
- full：**264 passed / 6 skipped**；Ruff **PASS**
- （历史 mypy 三错已由 TYPE 返工闭合；本条记录中央接受的组合绿，不另宣称 Linux Gate）

#### POSTFIX VALIDATION7（中央终态证据）

- evidence root：`artifacts/agent_runs/m4-b1a-postfix-validation7-20260825T181500Z-d91f`
- 全 PASS：identity；session **24 passed + 1 skipped**；Ruff；mypy5；cold；scope/diff/process
- 无 cache / temp / `0xF00` residue
- session SHA：`624E2A57945F90289F51546EDBCFEF6E9E5DF30FF6C4DEA22507689995E08D82`
- Ruff SHA：`82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18`
- mypy SHA：`718DF785EFBBD4B57E63B5F64AFF2C5B5592E433447681F759B307F97A3EC96A`
- cold SHA：`DCF12C4F22BE07B373EFBF84EC041120A94A1E80544C16CAF539D57F25FC5BF4`
- scope SHA：`97030AD4C8BC2E0EB148A8629737B5E169A2BC4A3FEB087AF6BAC7C0048B5281`
- summary SHA：`201F6D8148084C9D2034E20D9B92A65BB5F70AD35B86E685926D690B7E7CD372`
- runner SHA：`CE3E508955916213C0E127A06EADFBB218341E449DE463CD8FF66271D693D92D`

本轮仅更新任务书/交付；禁止 production/tests/Python/检查/提交。

## 10. 交付与后续 B1B 边界

交付报告必须给出状态机、durable row schema、lock/lease生命周期、两个 store 的每个 writer 覆盖表、错误码、反例、未运行项和风险。每个返工问题按“现象—根因—规则—最小复现—新增测试—通过条件”记录。

B1A 通过后仍必须保持：`SUBSTRATE_ONLY / UA-M4-006 OPEN`。中央合流后再从新 integration 创建 B1B，接入 formal service/gateway/daily/EOD/soak/reconcile，消除 `soak_runtime` sibling underscore import 与 composition 私有字段穿透，并形成 all-writer/closure/terminal successor 工程闭包。B1A 不得预写 B1B 路径或启动任何 PAPER/真实 run。
