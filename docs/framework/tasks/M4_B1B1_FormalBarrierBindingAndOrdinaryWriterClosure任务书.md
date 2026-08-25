# M4-B1B1 Formal Barrier Binding And Ordinary Writer Closure 任务书

状态：`B1B1_WINDOWS_ENGINEERING_VALIDATED / SUBSTRATE+B1B1 / UA-M4-006 OPEN`

> 中央 `EVIDENCE_UPDATE_GRANT` 收口：组合证据（非单轮全绿）。**不宣称** B1B2、terminal all-writer closure、CLOSING→CLOSED 消费、PAPER、soak、Linux Gate。历史失败证据不得改写。

## 1. 身份、职责与终态

- task id：`M4-B1B1-FORMAL-BARRIER-BINDING`
- exact base：`57dcf2e579175ead8d7c833ed7fb4b7bccedc5c5`
- branch：`codex/m4-b1b1-formal-barrier-binding`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1b1-formal-barrier-binding`
- 经理：框架主 Agent，独占本任务书。
- 实现：一个全新的外部 Cursor Grok 4.5 High 会话，只写 production/tests 与唯一 delivery。
- 初验：另一全新且未参与实现的外部 Cursor Grok 4.5 High 会话；实现、测试、任务书和 delivery 只读，只写唯一 review。
- 终态上限：`FORMAL_OPEN_WRITER_BARRIER_BOUND`。仍为 `UA-M4-006 OPEN`，不表示 B1B2、terminal all-writer closure、PAPER、soak 或 Linux Gate 完成。

## 2. 目标与拆包边界

B1A 已提供 v9 barrier、OPEN/CLOSING/CLOSED 状态机、anchored OS lock、OPEN write lease及两个底层 store 的可选接入。本包只完成：

1. 新 root 的 formal execution/broker/gateway/service/daily 使用同一 barrier capability；
2. 所有普通 formal writer 真实继承同一 OS lock + OPEN lease；
3. OPEN→CLOSING 在同锁下签发唯一、不可伪造、与 close token/全部身份绑定的 closure capability；
4. CLOSING/CLOSED 后所有普通 writer fail closed。

B1B1 不允许 closure capability执行 broker finality、OMS recovery/reconcile/report/soak写，不推进CLOSED。上述 terminal successor属于合流后另建的 B1B2。

## 3. 精确白名单

exact25：

1. `src/quant/execution/session_barrier.py`
2. `src/quant/execution/store.py`
3. `src/quant/execution/paper_broker_store.py`
4. `src/quant/execution/service.py`
5. `src/quant/execution/gateways/paper_durable.py`
6. `src/quant/execution/paper_formal_execution_store.py`
7. `src/quant/execution/paper_formal_broker_store.py`
8. `src/quant/execution/paper_formal_gateway.py`
9. `src/quant/execution/paper_formal_service.py`
10. `src/quant/execution/paper_formal_daily.py`
11. `src/quant/execution/reconcile.py`
12. `tests/unit/test_session_barrier.py`
13. `tests/unit/test_execution_store.py`
14. `tests/unit/test_paper_broker_store.py`
15. `tests/unit/test_execution_service.py`
16. `tests/unit/test_paper_durable_gateway.py`
17. `tests/unit/test_paper_formal_execution_store.py`
18. `tests/unit/test_paper_formal_broker_store.py`
19. `tests/unit/test_paper_formal_gateway.py`
20. `tests/unit/test_paper_formal_service.py`
21. `tests/unit/test_paper_formal_daily.py`
22. `tests/unit/test_reconcile.py`
23. `docs/framework/tasks/M4_B1B1_FormalBarrierBindingAndOrdinaryWriterClosure任务书.md`（经理独占）
24. `docs/framework/deliveries/M4_B1B1_FormalBarrierBindingAndOrdinaryWriterClosure交付报告.md`（实现者独占）
25. `docs/framework/reviews/M4_B1B1_FormalBarrierBindingAndOrdinaryWriterClosure独立初验报告.md`（初验者独占）

实现者不得修改 23、25；初验者不得修改 1–24。migration、config、`__init__.py`、broker snapshot、soak/soak_runtime、roadmap、共享 SSOT和旧 root全部只读。任何扩围先写 delivery 并 STOP。

## 4. 单一 barrier 身份与 formal 绑定

1. 仅新 root 可初始化 formal barrier；禁止旧 root adoption、backfill、自动建 OPEN 或沿用旧 epoch。
2. 一个 formal session 的 execution store、broker store、gateway、service、daily runner必须绑定同一 canonical barrier capability，精确闭合：barrier schema/epoch、session date、account、OMS store、broker store、gateway、config/runtime root和anchored lock identity。
3. capability必须由可信 formal composition从已fresh验证的真实 store/gateway/config identity构造；禁止caller bool、raw mapping/token、Protocol、subclass或未绑定store注入。
4. formal capability/open/reverify必须fresh验证 barrier row、两个store与gateway identity；任一漂移在业务writer前拒绝。
5. 非formal且未配置barrier的既有development路径保持原行为；但formal入口绝不允许回退到unconfigured store。

## 5. 普通 writer 完整闭包

所有普通写操作必须最终落入B1A底层 transaction的同一 OPEN lease，不在上层重复取锁：

- OMS plan、stage、command、outbox、cancel、risk、counter、ledger、approval/reconcile相关写；
- broker submit/cancel callback、operation、fill/finality marker等普通写；
- formal gateway/service/daily所有可触发上述写的入口。

要求：

1. shared anchored OS lock覆盖真实BEGIN至commit/rollback；上层不得用bool/precheck/raw token替代。
2. 同一调用链lease depth必须exact 1；禁止service→gateway→store重复进入同一非重入锁。
3. generic `ExecutionStore.transaction()`与`PaperBrokerStore`普通writer始终OPEN-only；不得因closure capability出现而放宽。
4. reconcile只读恢复保持可用；任何会写的repair/reconcile路径必须在OPEN lease内，CLOSING/CLOSED拒绝。
5. 异常rollback不得残留经济写、barrier推进或可重放lease。

## 6. Closure capability 只签发、不消费

`session_barrier.py`新增module-private factory绑定的exact process-local closure capability：

- 只能由exact `OPEN -> CLOSING` transition在同一anchored lock下签发；
- 绑定close token identity、barrier epoch/session/account/root、两个store、gateway/config、lock object和CLOSING row identity；
- direct constructor、bool/raw token、Protocol/subclass、`object.__new__`/`__setattr__`、copy/deepcopy/pickle/replace均不能获得可信性；
- exact同token恢复只能得到同一capability identity并fresh验证CLOSING row；新token、跨identity或第三次签发拒绝；
- capability不可序列化、不可持久化、不可日志/repr泄露proof；durable row只保存非secret identity。

B1B1中closure capability没有通用transaction/write接口，不能写broker finality、OMS closure或soak，也不能调用CLOSING→CLOSED。现有raw close-token直达CLOSED能力在formal/public边界必须不可达；B1A内部兼容代码不得成为旁路。

## 7. 竞争、失败语义与反例

必须线性化 writer-vs-close：

- writer先拿锁：完成commit/rollback后close才能transition；
- close先拿锁并进入CLOSING：之后所有普通writer拒绝；
- check后写入、跨store锁顺序倒置、重复锁进入和部分barrier绑定均不可发生。

稳定错误须脱敏，不泄露绝对路径、SQLite payload、proof/token material或底层cause/context。至少覆盖：

1. canonical新root formal binding正向，旧root/unconfigured formal拒绝；
2. barrier epoch/session/account/root/store/gateway/config任一漂移；
3.无/伪/跨身份capability与两个store不一致；
4. plan/stage/dispatch/cancel/callback/reconcile普通写均在OPEN成功；
5. 上述每类在CLOSING与CLOSED拒绝，且无部分经济影响；
6. writer与OPEN→CLOSING双向竞争的唯一线性顺序；
7. lease depth exact 1，重复/第三次锁进入拒绝；
8. closure direct/object/copy/pickle/replace伪造及跨session/root/store/gateway/epoch replay；
9. exact token CLOSING恢复同identity，新token冲突；
10. raw token或普通write lease不能直达CLOSED或执行terminal写；
11. read-only inspect/fresh verify在CLOSING可用且零写；
12. nonformal未配置barrier路径回归不变。

独立初验必须新增至少一个实现者未使用的对抗性反例，优先挑战上层重复锁、unbound store fallback或closure capability能力外溢。

## 8. 交付与验证边界

实现阶段为 `STATIC_ONLY`：不得运行 Python、pytest、Ruff、mypy、cold、SQLite probe、PAPER、网络、browser、soak或提交。实现者在 delivery 中逐项记录：现象、根因、被保护不变量、规则、最小复现、测试、通过条件、exact diff和未验证边界。

独立初验只读 1–24，只写25；输出 `REVIEW_PASS`/`REVIEW_FAIL`，不得把静态审查写成运行通过。通过后由经理另向中央申请串行Windows定向验证资源。

## 9. STOP 条件

出现任一情况立即 STOP：需要migration/config/`__init__.py`或soak路径；必须让generic transaction接受closure permit；无法避免重复OS lock；无法在新root形成单一barrier identity；必须adopt旧root；必须复制锁/状态机；发现第二writer、base漂移或白名单外依赖。

## 10. 独立初验失败后的 STATIC_REWORK1

首次静态交付经独立初验判定 `REVIEW_FAIL`。两项 P1 均为真实合同违反：formal capability 可组合 raw token 与底层 store 直达 CLOSED；submit/cancel 的 broker durable write 与 OMS callback 之间可被 CLOSING 插入。capability escape P2并入 F1；half-init P2纳入 F3 fail-closed证据。原review报告保持只读，由同一实现会话按本节返工，之后交回同一独立reviewer复验。

### 10.1 F1：formal raw CLOSED 隔离

1. 新增强类型 terminal transition policy，exact值域仅 `SUBSTRATE_RAW_TOKEN` / `FORMAL_CLOSURE_ONLY`。它进入 `SessionBarrierCapability` 字段、capability identity/proof、closure identity/proof与 durable row-identity closure。
2. 不改 v9 表列或DDL。B1A substrate默认/显式 `SUBSTRATE_RAW_TOKEN`，其既有 row bytes、row identity算法及 raw CLOSED正向保持；formal new root只能 `FORMAL_CLOSURE_ONLY`，使用policy-domain-separated row identity closure。
3. read可验证两种已知row closure；任何transition、lease、handle、operation permit或closure都必须由当前capability policy与当前row identity逐字闭合。unknown/mixed policy拒绝。
4. `transition_closing_to_closed` 与 `ExecutionStore` raw CLOSED入口对 `FORMAL_CLOSURE_ONLY` 稳定拒绝 `BARRIER_CLOSURE_REQUIRED`；substrate raw-token行为不变。
5. formal `_build_formal_barrier` 必须显式使用 `FORMAL_CLOSURE_ONLY`；formal closing API只返回 `(row, closure)`，不得返回 raw token。
6. 删除 `VerifiedFormalPaperExecutionStoreCapability.session_barrier` live capability公开属性。formal模块只提供 verify/recover closing 所需的窄函数，内部消费私有barrier；caller不得取得live barrier capability、OMS handle或raw token。既有 `.store` 即使保留，也不能越过formal policy guard。
7. 反例：从formal row/closure/`object.__new__`/属性反射取得token后，经 `.store` raw CLOSED和session_barrier module raw CLOSED均拒绝；跨policy capability/row/descriptor拒绝；substrate legacy row/identity/CLOSED正向逐字不变。禁止仅依赖“token不公开”。

### 10.2 F2：submit/cancel 跨 store OPEN operation fence

1. 新增module-private、不可伪造 `SessionBarrierOperationPermit`（可使用等价私有命名，但须在delivery逐字记录）与 `hold_open_operation_permit`。它在fresh OPEN验证后持有同一anchored OS lock，覆盖完整一次dispatch。
2. `ExecutionStore` 提供窄 operation-fence context；未配置barrier时为legacy no-op。`dispatch_commands`、`dispatch_exact_pending_commands` 与 `dispatch_cancel` 在barrier-enabled时必须从首次 claim/fence写开始，覆盖 gateway broker durable write，直到 OMS callback 或 unknown closure结束。不得只包gateway或在claim后才取permit。
3. outer permit期间不持SQLite transaction。每个inner OMS transaction与 `PaperBrokerStore` writer仍取得store-kind exact的OPEN child write lease。
4. 保持Gateway Protocol不变。若用module-private `ContextVar`/线程绑定registry传播，里面只能保存真实live permit对象；`hold_open_write_lease` 每次都须fresh验证 permit alive、owner pid/thread、same capability、same OMS handle/connection、same held lock identity及当前row OPEN，之后复用已持 physical lock并mint store-specific child lease，不得再次 `_acquire_barrier_lock`。
5. 同一permit可顺序签发多个child lease，但同一时刻最多一个active child。nested child、second operation permit、cross thread/capability/OMS handle、expired/replay/forge/third-layer均fail closed。完成或异常后permit及所有child全部失效；禁止thread-local bool/raw token旁路。
6. close竞争只能阻塞在outer OS lock并报 `BARRIER_WRITER_BUSY`，不得插入broker commit与OMS callback之间。gateway失败、result invalid、OMS callback异常、unknown路径都须finally释放permit；释放后close才能进入CLOSING。
7. submit与cancel都必须测试：physical lock depth exact1；真实 OMS/broker child leases；gateway暂停点close BUSY；operation完成后可CLOSING；gateway/OMS异常释放；forge/cross-thread/cross-identity/replay/third-layer拒绝；nonbarrier结果与bytes不漂移。

### 10.3 F3：initialize 半失败

1. 对 `_write_exclusive` 失败与 broker barrier bind失败分别补反例：不得返回formal capability；open/initialize及所有ordinary/formal writer不可达。
2. 若root含broker正式bytes导致安全rollback不能删除，允许稳定 `PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED` 并保留人工清理边界；不得递归删除broker root或静默adopt。
3. 只有逐项证明文件由本次创建、identity闭合且不触碰broker bytes，才可精确回滚OMS sqlite/descriptor；否则保持 `ROLLBACK_REQUIRED`。测试必须锁定真实错误码、残留形态与不可open。

本次仍为 `STATIC_ONLY / UA-M4-006 OPEN`。不得修改migration/schema列/Gateway Protocol或白名单外路径；不得运行Python、SQLite或提交。若上述合同在exact25内不可满足，必须带精确源码证据 STOP。

## 11. MANAGER_STATIC_REWORK2：F2 module-private 与 F3 rollback identity 闭包

STATIC_REWORK1 的主 Agent 静态准入发现两处未闭合，独立reviewer暂不启动：

1. F2要求 operation permit 与 holder 为module-private，但首次返工将 `SessionBarrierOperationPermit` 与 `hold_open_operation_permit` 加入 `session_barrier.__all__`。保留store内部的窄调用可以，但不得从 `__all__` 导出这两个authority symbol，也不得新增公开wrapper。测试必须锁定它们不在 `__all__`，同时store内部 operation fence 仍使用真实permit。
2. F3 `_rollback` 会删除descriptor与 WAL/SHM，但当前只记录main sqlite identity，未记录descriptor或WAL/SHM identity，违反“逐项证明由本次创建且identity闭合”。必须在 `_write_exclusive` 成功后立即记录descriptor object identity并传入rollback；rollback删除前fresh比对。任何未记录identity的WAL/SHM或其他残留不得删除，必须返回false并上浮 `PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED`；不允许用文件名或“在新root内”代替identity证明。
3. 新增反例至少覆盖descriptor identity替换/漂移不被删除且返回ROLLBACK_REQUIRED，未记录WAL/SHM残留不被删除，安全无漂移路径仍可精确回滚。

同一原实现会话仅在exact25内完成该最小静态返工并更新delivery。不得运行Python/测试/静态检查/SQLite，不得修改review报告或提交。

## 12. VALIDATION1 STOP 后的 STATIC_REWORK3（F20–F23）

Windows `VALIDATION1` 的 identity preflight 通过；exact11 focused 得到 `465 passed / 6 skipped / 6 failed`，随后 Ruff、mypy、cold 与 final scope 均按首失败合同未运行。原生证据位于 `artifacts/agent_runs/m4-b1b1-validation1-20260826T004700/`。本节冻结一项生产门禁修复与五项测试/fixture修复；仍为 `STATIC_ONLY`，review报告只读。

### 12.1 F20：operation permit acquire 计数（test-only）

`initialize_open_barrier` 已产生一次 tracked acquire，原测试错误地把初始化计入permit并期待总数为1。测试必须在initialize与handle构造后记录baseline：进入outer permit只新增一次physical acquire；两个顺序child期间及permit退出后保持 `baseline + 1`；随后 `OPEN -> CLOSING` 再变为 `baseline + 2`。不得修改session barrier生产锁逻辑。

### 12.2 F21：unrecorded WAL/SHM 注入时序（test-only）

原fixture在 `ExecutionStore` 尚打开时注入 `oms.sqlite3-wal`，真实close可由SQLite自行删除/收敛sidecar，未能证明rollback保留unknown sidecar。测试应通过class-level窄包装 `ExecutionStore.close`（或等价test-owned seam）先调用真实close，再注入unrecorded WAL，使其在rollback inventory前存在。禁止patch native sqlite实例只读方法。必须断言 `PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED`、sidecar仍存在、formal open不可达；不得改production rollback伪造残留。

### 12.3 F22：formal barrier-enabled method 门禁（production）

`ExecutionStore.session_barrier_enabled` 与 `PaperBrokerStore.session_barrier_enabled` 均为method；本包formal代码与测试把它们当属性时，bound与unbound都会得到truthy bound-method，实际门禁失效。所有本包新增/修改的production调用必须显式调用 `session_barrier_enabled()`，至少逐处核对formal execution store、formal gateway、formal service与formal daily；禁止把B1A既有method API改成property。

所有正向测试断言同样调用method。unbound gateway反例必须在test-owned fresh verifier返回该exact capability后，仍因 `enabled() is False` 被拒绝，不能依赖无关identity mismatch偶然通过。两个gateway正向fixture须只在 `_setup` 内为formal gateway verifier补与现有人工capability一致的exact返回；生产gateway不得放宽，hostile verifier反例保持真实拒绝。

### 12.4 F23：reconcile CLOSING 错误边界（test-only）

`recover_local_state` 公共合同会把底层 `StoreError` 归一为detached `RecoveryError("RECOVERY_LOCAL_INVALID")`。测试应断言code、`args[0]` 与 `str(exc)` 均为该稳定值，且cause/context脱离；之后 `read_session_barrier_row` 仍可只读得到CLOSING，`reconcile(open_recovery, broker, ...)` 的只读路径仍可用且零写。不得修改 `reconcile.py` 的生产分类；若发现已有SSOT明确要求barrier code穿透，须STOP举证。

### 12.5 交付与通过条件

实现者在delivery逐项记录F20–F23的现象、根因、规则、原生复现、新增/修正测试与通过条件，并明确F22是真实production门禁缺陷、其余为test/fixture合同错误；不得把465项绿色改写成整包通过。ordinary `git diff --check` 必须通过且actual dirty继续完全属于exact25。原独立reviewer复验时必须重点确认：所有新增formal门禁均调用method；unbound测试不是因identity mismatch假绿；WAL确在真实close之后注入。复验通过后另申请完整 `VALIDATION2`，不得只重跑六个失败节点。

## 13. VALIDATION2 STOP 后的 STATIC_REWORK4（F24）

`VALIDATION2` identity通过，exact11 focused得到 `470 passed / 6 skipped / 1 failed`；唯一失败是F23新增测试误解Python异常链语义，不是production门禁失败。`recover_local_state` 使用 `raise RecoveryError("RECOVERY_LOCAL_INVALID") from None`：公开traceback链被抑制，表现为 `__cause__ is None` 且 `__suppress_context__ is True`；语言不会清空当前被处理异常仍保存在 `__context__` 的事实。

同一原实现者仅修改 `tests/unit/test_reconcile.py` 与delivery；本任务书由经理更新，production和其他tests字节冻结：

1. 在 `test_barrier_closing_rejects_recover_local_write_path_keeps_read` 中移除对旧 `_assert_detached` 的复用；保留并逐字断言 `code == args[0] == str(error) == "RECOVERY_LOCAL_INVALID"`、`__cause__ is None`、`__suppress_context__ is True`。
2. 不要求 `__context__ is None`，也不把其内部类型或消息冻结为public API。测试注释应明确“suppressed traceback != cleared object context”。
3. CLOSING row/state/row identity零写不变量、fresh read及后续纯read/reconcile路径仍须闭合；不得弱化CLOSING fail-closed。
4. 不修改全局 `_assert_detached` helper及既有调用，不改 `reconcile.py` 控制流，不手工篡改异常对象，不新增production异常字段或日志。
5. delivery追加F24的现象、根因、语言规则、最小复现、修正测试与通过条件，引用 `artifacts/agent_runs/m4-b1b1-validation2-20260826T011000/` 及470绿/1失败边界；不得写成实现失败或整包通过。

实现完成后交同一独立reviewer复验，确认production SHA不变、CLOSING仍fail closed，且测试只校正异常链可见语义。复验PASS后重新申请完整 `VALIDATION3`：identity → focused exact11 → Ruff exact22 → mypy production11 → cold production11 → exact25 scope/residue，不缩测。

## 14. VALIDATION3 STOP 后的 STATIC_REWORK5（F25）

`VALIDATION3` 中F24异常链断言已通过；focused exact11仍为 `470 passed / 6 skipped / 1 failed`。唯一失败发生在新增测试的后续只读reconcile fixture构造：`build_broker_snapshot` 要求broker `as_of` 与account `as_of` 形成同一canonical observation identity，但测试误用barrier `created=2026-08-25` 配合 `_account()` 的既有observation时间。barrier transition时间与broker/account observation时间是独立身份，不得混用，也不得修改production放宽。

同一原实现者仅修改 `tests/unit/test_reconcile.py` 与delivery；本任务书由经理更新，production、其他tests与review冻结：

1. 在后续只读reconcile段先绑定 `account = _account()`；调用 `build_broker_snapshot(account=account, as_of=account.as_of, ...)`，保持orders/events/finality/source不变；再调用 `reconcile(open_recovery, broker, account.as_of)`。
2. barrier capability的created、transition now及CLOSING row仍保持原2026-08-25身份；不得改成account时间或把两类时间强绑定。
3. 前半段F24 public RecoveryError/suppressed context及CLOSING zero-write/row identity断言保持；reconcile后row/state/identity零写断言保持。
4. 不改 `build_broker_snapshot`、`reconcile`、全局 `_account` fixture或其他既有tests；不得放宽as_of验证。
5. delivery追加F25的现象、根因、身份规则、最小复现、修正测试与通过条件，引用VALIDATION3 470绿/1失败及后续检查未运行边界；不得写成production失败。

完成后交同一独立reviewer复验，确认production SHA不变、两类时间身份分离且CLOSING只读闭包未弱化。PASS后重新申请完整 `VALIDATION4`，仍不缩测。

## 15. VALIDATION4 STOP 后的 STATIC_REWORK6（F26）

`VALIDATION4` 的 identity 与 exact11 focused 均通过，focused结果为 `471 passed / 6 skipped`。Ruff exact22首失败且唯一错误为 `tests/unit/test_execution_service.py` 并发submit fence节点的 F841：`staged = _stage(service, tmp_path)` 返回值未被读取。源码复核确认 `_stage(...)` 调用本身负责创建后续dispatch所需的持久stage，是必要副作用；问题仅为无用局部绑定，不是production或行为失败。mypy、cold与scope均未运行。

同一原实现者仅修改 `tests/unit/test_execution_service.py` 与delivery；本任务书由经理更新，production、其他tests与review冻结：

1. 将该行精确改为 `_stage(service, tmp_path)`，保留调用位置、参数、次数、异常传播及全部后续并发/close断言。
2. 禁止删除调用、赋给 `_`、增加 `noqa`/Ruff ignore、修改 `_stage` helper、gateway、service或测试时序。
3. delivery追加F26的现象—根因—必要副作用规则—最小复现—修正—通过条件，引用 `artifacts/agent_runs/m4-b1b1-validation4-20260826T024000/`、focused PASS与Ruff F841，诚实标记mypy/cold/scope为UNRUN。

完成后由同一独立reviewer只读复验，必须确认仅删除局部绑定且调用上下文/行为不变。复验PASS后申请postfix窄验证：identity轻量 → Ruff exact22 → mypy production11 → cold production11 → exact25 scope/diff/temp/process；`VALIDATION4` 已绿focused 471不机械重复。若review发现超出该单行行为等价变化，必须STOP重新申请完整验证。当前零Python，不自行重跑。

## 16. VALIDATION5 STOP 后的 STATIC_REWORK7（F27）

`VALIDATION5` 的 identity 与 Ruff exact22 均通过；mypy production11 首失败，三个错误均位于 `paper_formal_execution_store.py`：`_build_formal_barrier` 的真实返回值只来自 `build_session_barrier_capability`，但函数注解写为 `object`，导致caller访问 `capability_identity` 时出现 `attr-defined`。cold与scope均未运行。这是生产类型合同缺口，不是运行分支或barrier identity失败。

同一原实现者仅修改 `src/quant/execution/paper_formal_execution_store.py` 与delivery；本任务书由经理更新，其他production/tests/review冻结：

1. 从 `quant.execution.session_barrier` 显式import `SessionBarrierCapability`，并将 `_build_formal_barrier(...) -> object` 精确收窄为 `-> SessionBarrierCapability`。
2. 禁止 `cast`、`Any`、`type: ignore` 或 Protocol替代；不得修改函数体、异常归一、terminal policy、identity、descriptor bytes、调用顺序或运行分支。
3. 为保持 capability escape 边界，本轮不得修改 `VerifiedFormalPaperExecutionStoreCapability._session_barrier: object`、`mint(session_barrier: object)` 或 `_bind_formal_broker_barrier(..., session_barrier: object)`；这些入口继续通过unpack/store边界验证，不将raw capability强类型扩散到跨层接口。
4. 若该单一修正后静态检查出现新的确切错误，必须STOP取证，不得预先扩大注解。
5. delivery追加F27现象—根因—类型规则—最小复现—修正—通过条件，引用 `artifacts/agent_runs/m4-b1b1-validation5-20260826T031000/`、Ruff PASS、mypy三错误及cold/scope UNRUN。

完成后交同一独立reviewer复验，确认仅import与返回注解变化，runtime/schema/bytes/capability escape边界不变。PASS后申请postfix窄验证：identity → Ruff实际修改production file → mypy production11 → cold production11 → exact25 scope/diff/temp/process；不重复focused471或Ruff其余已绿文件。当前零Python。

## 17. EVIDENCE_UPDATE_GRANT（中央批准文档收口）

本轮中央特批仅更新本任务书与 delivery；production/tests/review 冻结；零 Python / stage / commit。

### 17.1 组合有效绿证据（跨轮；不得改写历史失败）

| 轮次 | evidence root | 首失败 / 结果 | 修复链 | 本轮有效绿 | 本轮 UNRUN |
|---|---|---|---|---|---|
| V1 | `…/m4-b1b1-validation1-20260826T004700/` | focused：6 failed / 465 passed | §12 F20–F23 | identity PASS | Ruff/mypy/cold/scope |
| V2 | `…/m4-b1b1-validation2-20260826T011000/` | focused：1 failed / 470 passed（`__context__`） | §13 F24 | identity PASS | Ruff/mypy/cold/scope |
| V3 | `…/m4-b1b1-validation3-20260826T014000/` | focused：1 failed / 470 passed（as_of 混用） | §14 F25 | identity PASS | Ruff/mypy/cold/scope |
| V4 | `…/m4-b1b1-validation4-20260826T024000/` | Ruff F841（focused 已绿） | §15 F26 | **identity + focused `471 passed / 6 skipped`** | mypy/cold/scope |
| V5 | `…/m4-b1b1-validation5-20260826T031000/` | mypy 3× attr-defined | §16 F27 | **identity + Ruff exact22** | focused（不重复）/cold/scope |
| V6 | `…/m4-b1b1-validation6-20260826T043000/` | 无失败（postfix 全绿） | — | **identity + Ruff changed-file + mypy11 + cold11 + scope**（cached0 / diff-check PASS / temp residue 清） | focused（沿用 V4 471，不机械重跑） |

### 17.2 VALIDATION6 关键证据与 SHA

最新 evidence root：`artifacts/agent_runs/m4-b1b1-validation6-20260826T043000/`

| 产物 | exit | SHA256 |
|---|---|---|
| `stage-summary.log` | 全阶段 0 | `d4c44f8610b6cc611a4b440f0a1afe6cf3c52055c3e064425ebf932a02e3f7cf` |
| `01-identity.stdout.log` | 0 | `4630a9835997dcab87ec9e27a2aca1ab14b7c511b877a828efa971f937ca26d2` |
| `03-ruff.stdout.log` | 0 | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| `04-mypy.stdout.log` | 0 | `ce32e21ee307d2da61637151f2f239cf8568be270711ff04e8e3025805ab7f57` |
| `05-cold.stdout.log` | 0 | `3d7eb1f1cbc189e0b56f320f769d6918982875771d61679db270db7671180b79` |
| `06-final-scope.stdout.log` | 0 | `e10206e0d6d98aa6a2c996f0bb874fd205d9b427993d8dd4d4a0bb5fdf570e7c` |

scope 快照：`ACTUAL_COUNT=16`（exact25 子集）；`CACHED_COUNT=0`；`DIFF_CHECK=PASS`。快照内 **PID37448**=`pwsh`/`BelowNormal`/`0xF00` 为 finally **前** carrier；runner 退出后亲和性已释放（无残留 `0xF00` 占用）。**PID7692** writer=`python`/`0x3` **未扰动**。

### 17.3 状态上限与禁止宣称

- 工程状态上限：`B1B1_WINDOWS_ENGINEERING_VALIDATED`（Windows 组合工程验证）
- 持续：`SUBSTRATE+B1B1` / `UA-M4-006 OPEN`
- **禁止宣称**：B1B2、all-writer terminal closure、CLOSING→CLOSED 消费、PAPER、soak、Linux Gate、单轮「全量 Gate 通过」
