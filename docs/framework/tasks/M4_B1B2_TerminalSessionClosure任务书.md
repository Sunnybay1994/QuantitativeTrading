# M4-B1B2 Terminal Session Closure 任务书

状态：`EVIDENCE_CLOSE_READY / B1B2_WINDOWS_ENGINEERING_VALIDATED`（§15 组合证据闭合；待 `EVIDENCE_REVIEW`）<br>
task id：`M4-B1B2-TERMINAL-SESSION-CLOSURE`<br>
exact base：`d525770ac9deb78e414098308b34acbd0773c099`<br>
branch：`codex/m4-b1b2-terminal-session-closure`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1b2-terminal-session-closure`

## 1. 目标与终态上限

在已合流 B1A barrier substrate 与 B1B1 formal OPEN writer binding 上，完成同一 formal closure capability 驱动的 terminal session closure：broker finality → OMS fresh recovery/reconciliation → report/soak evidence → terminal successor → `CLOSED`。同时消除 `soak_runtime` 对 sibling underscore helper 与 verified composition 私有字段的穿透。

本包最高只能声明 `B1B2_WINDOWS_ENGINEERING_VALIDATED / UA-M4-006_WINDOWS_ENGINEERING_CLOSED`。不得宣称真实 PAPER、真实 soak、跨日 rotation、fault drill、28 日计时、Linux Gate 或 M4 整体完成。

## 2. 权威现状与核心不变量

- B1A 已冻结 v9唯一 barrier row、OPEN write lease、anchored OS lock 与 legacy `SUBSTRATE_RAW_TOKEN`。
- B1B1 已冻结 formal `FORMAL_CLOSURE_ONLY`、OPEN operation permit、ordinary/formal writer closure，并签发仅可验证的 process-local `SessionBarrierClosureCapability`；B1B1 不消费它做 terminal 写或 `CLOSING→CLOSED`。
- 两个 SQLite store 不具备跨库事务原子性。本包必须以 durable step identity、exact-token resume 与 fail-closed orphan detection诚实闭合，不能虚构分布式事务。
- 现有 `soak_runtime.py` import `paper_formal_broker_snapshot._finalize...`、`soak._session...` 并读取 composition 私有字段；这是 INFRA-007 已登记债，必须在本包消除，不能增加新的私有穿透。

## 3. 唯一写白名单（exact33；原 exact31 + 中央新增 2）

### Production（14）

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
11. `src/quant/execution/paper_formal_broker_snapshot.py`
12. `src/quant/execution/soak.py`
13. `src/quant/execution/soak_runtime.py`
14. `src/quant/execution/reconcile.py`

### 中央返工扩围 Production（2）

- `src/quant/execution/migrations/__init__.py`
- `src/quant/execution/migrations/v010_terminal_successor.py`（new）

### Tests（14）

15. `tests/unit/test_session_barrier.py`
16. `tests/unit/test_execution_store.py`
17. `tests/unit/test_paper_broker_store.py`
18. `tests/unit/test_execution_service.py`
19. `tests/unit/test_paper_durable_gateway.py`
20. `tests/unit/test_paper_formal_execution_store.py`
21. `tests/unit/test_paper_formal_broker_store.py`
22. `tests/unit/test_paper_formal_gateway.py`
23. `tests/unit/test_paper_formal_service.py`
24. `tests/unit/test_paper_formal_daily.py`
25. `tests/unit/test_paper_formal_broker_snapshot.py`（new）
26. `tests/unit/test_execution_soak.py`
27. `tests/unit/test_paper_soak_runtime.py`
28. `tests/unit/test_reconcile.py`

### Docs（3）

29. `docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md`（经理独占）
30. `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`（实现者独占）
31. `docs/framework/reviews/M4_B1B2_TerminalSessionClosure独立初验报告.md`（独立 reviewer 独占）

实现者只写上述 production 16 路径、tests 14 路径与 delivery，不写 taskbook、review。reviewer 只写 review，其余只读。除中央新增的 migration registry 与 v010 外，禁止修改其他 migration/schema、config、execution package `__init__.py`、CLI、roadmap、reporting实现或共享 SSOT。

## 4. 冻结 terminal closure 合同

### 4.1 Authority 与状态机

- 只有 exact `FORMAL_CLOSURE_ONLY` 的 live `SessionBarrierClosureCapability` 可启动/恢复 terminal closure。必须 fresh 闭合 capability、closing row、close token、barrier epoch、session/account、OMS/broker/gateway/config/store/root/lock identity。
- `SUBSTRATE_RAW_TOKEN` 的 B1A legacy正向行为保持；formal row通过 raw token、`transition_closing_to_closed` 或 `ExecutionStore` raw CLOSED入口必须稳定 `BARRIER_CLOSURE_REQUIRED`。
- closure capability、OPEN write lease、OPEN operation permit与terminal child capability严格分域；不得用 bool/raw token/caller label/Protocol/object属性代替。
- `CLOSING`期间ordinary/formal writer、dispatch/cancel/reconcile write、generic transaction均fail closed。只有冻结序列中的唯一 terminal child operation可在同一 anchored lock与exact closure下写其当前步骤。
- `CLOSED`后所有writer和closure replay零写；只允许fresh read/verify exact terminal successor。

### 4.2 Durable step sequence 与非原子恢复

固定顺序：

1. broker EOD finality及其 exact identity；
2. OMS fresh recovery与ORDER semantic closure；
3. broker snapshot + reconciliation；
4. operator report与soak session evidence/anchor；
5. terminal successor identity；
6. exact `CLOSING→CLOSED` row。

要求：

- 每一步必须有 canonical durable identity并引用前一步；不能只靠进程内对象或调用顺序。
- same token + same full identity重启时，可对已存在步骤fresh验证后继续下一个缺失步骤；不得重复经济影响或第二次append。
- 任何存在但不完整、错identity、错序、tamper、unknown orphan必须保持 `CLOSING`并fail closed；不能“补完”来源不明历史。
- 任一步异常只允许释放进程资源，不得回退barrier到OPEN、换token或伪造CLOSED。下一次只能same token恢复。
- terminal successor必须绑定 closing row/closure/token、broker finality、OMS recovery、reconciliation、report、soak receipt/anchor及最终CLOSED row identity；不能只绑定部分摘要。
- 两库非原子事实必须在类型、文档和错误语义中如实表达，不得声称同事务提交。

### 4.3 Narrow capabilities 与 INFRA-007

- `session_barrier`可新增最窄module-private terminal closure child capability/context；它必须不可构造、不可pickle/copy/replace、owner pid/thread绑定、单步/单active child、异常后失效，并在同一 held lock下fresh验证row仍为same CLOSING。
- `paper_formal_broker_snapshot`提供窄package-owned broker finalization capability/API；`soak`提供窄public/package-owned ORDER closure identity或append能力。不得让 `soak_runtime` import sibling underscore helper。
- `paper_formal_service`或相邻formal模块提供强类型只读 closure view/ports，使 `soak_runtime`不读取 `composition._execution_store`、`._ledger_provider` 或任何其他私有字段。
- 不扩成通用service locator，不公开raw stores、live barrier capability、OMS handle、credential或可绕过guard的万能composition。
- reporting仍只通过现有窄 `SessionReportPort`消费 verified recovery/reconciliation；本包不修改 reporting实现。

### 4.4 Broker/OMS/soak closure

- broker finality必须同时闭合session、account、gateway、broker store、ORDER semantic closure与barrier closure identity；zero-command与nonzero均保持既有经济语义。
- OMS recovery/reconcile必须fresh读取且任何risk/cancel/ledger/outbox/stage closure不完整都拒绝；CLOSING read-only路径不得误开writer。
- report/soak append必须使用同一 verified facts，append前后再次验证recovery/closure零漂移；replay exact receipt不得追加第二经济/anchor影响。
- `soak_runtime`不得自建第二把session lock；唯一serialization authority是B1 barrier anchored lock。旧 `_hold_session_lock` 若仅本runtime使用，应移除；若仍有兼容调用则必须证明不形成第二锁层或锁序倒置。
- 现有 Windows evidence kind、receipt/schema与非formal历史bytes不得静默改写。需要schema/migration变化时STOP申请新包。

## 5. 必须覆盖的对抗性反例

至少覆盖：

1. fake/marker/bool/raw token、direct constructor、`object.__new__`/`__setattr__`、subclass、copy/deepcopy/pickle/replace、expired/replayed closure。
2. wrong close token；跨root/session/epoch/account/store/gateway/config/lock identity；same token但任一 durable step identity漂移。
3. writer与OPEN→CLOSING竞争；CLOSING后plan/stage/dispatch/cancel/broker callback/reconcile/generic transaction均拒绝；CLOSED后零写。
4. broker finality、OMS recovery、reconcile、report、soak append、terminal successor、CLOSED各边界分别注入异常；重启后same token仅从fresh已验证step继续。
5. broker/OMS/soak存在孤儿或部分记录、错序、多余记录、tamper bytes/hash/identity；不得自动补写或换token。
6. raw token从formal row/closure/反射泄漏后仍不能CLOSED；`SUBSTRATE_RAW_TOKEN` legacy positive不变。
7. terminal child nested、第二/第三child、跨线程/进程/closure/handle、已退出replay拒绝；physical barrier lock depth exact1。
8. `soak_runtime`无underscore import和composition私有字段；伪造narrow view/port拒绝；read-only inspect不写。
9. zero-command exact replay、nonzero普通链、cancel链与unconfigured legacy行为不漂移。
10. exact terminal successor tamper及CLOSED row不匹配拒绝；CLOSED fresh replay只读且结果bytes稳定。

## 6. 静态实施与验证顺序

当前仅授权 `STATIC_ONLY`：零 Python、pytest、Ruff、mypy、cold、SQLite probe、PAPER、真实soak、网络、browser、真实worker、stage或commit。

实现者应：

1. 阅读 AGENTS、B1A/B1B1 task/delivery/review及 exact33源码；开始前确认只有本任务书dirty。
2. 先冻结terminal child capability、durable step identity和narrow composition view，再最小改动连接现有finality/recovery/soak API。
3. 优先删除私有穿透与第二锁层，不复制现有finality/recovery/receipt逻辑。
4. 补齐 exact tests 与 delivery，逐项写明非原子恢复、反例和未运行边界。
5. 完成后回 `DELIVERY_READY <delivery path>`；不得自行运行检查或提交。

独立 reviewer 必须为未参与实现的全新外部会话，新增至少一个实现者未使用的反例，重点挑战：partial CLOSING same-token recovery、formal raw-token escape、terminal child replay、broker/OMS/soak孤儿以及composition私有能力是否仍可达。review PASS 后由经理向中央申请 Windows 验证资源。

## 7. STOP 条件

以下任一情况立即在 delivery 写明“现象—根因—规则—最小复现—所需路径/API—通过条件”并 STOP：

- 需要本任务书 v010 之外的 migration/schema/config/CLI/reporting/`__init__.py` 或 exact33 外路径；
- 必须公开raw store/live barrier/OMS handle、改变Gateway Protocol或复制第二套recovery/finality/receipt；
- 无法在same anchored lock下区分terminal child与OPEN writer；
- 无法以现有durable事实恢复partial CLOSING而需要猜测/扫描/补写未知历史；
- 必须宣称跨库事务原子或修改旧evidence bytes才能闭合；
- base/branch/worktree漂移、第二 writer、白名单外dirty或真实运行资源冲突。

## 8. 交付与完成标准

- actual dirty必须精确属于exact33，普通 `git diff --check` PASS；无临时文件、cache、凭据、真实数据库或evidence。
- delivery列出所有修改、public/private capability边界、durable step schema/identity、每类反例、未运行项及建议focused/Ruff/mypy/cold顺序。
- reviewer `REVIEW_PASS`仅是Windows主验准入；即使主验全绿，也不得启动PAPER/soak或关闭Linux/28日/fault-drill Gate。

## 9. 独立初验返工 R1 与中央 exact33 重冻（2026-08-26）

独立初验结论 `REVIEW_FAIL`。保留原 review 与 §12/§13 违约、授权采用历史，不覆盖。返工由 §13 同一授权采用者承担，禁止新建第二实现者或任何 subagent/委派；完成后交回原独立 reviewer 复验。继续 `STATIC_ONLY`、零 Python/SQLite/测试/静态工具/真实运行/提交。

### F1 — formal CLOSED 持久化 exact terminal successor

1. v010 为 `session_barrier` 新增 nullable `terminal_successor_identity TEXT`；`CURRENT_SCHEMA_VERSION=10`。
2. 既有 v9 行升级后保持 `NULL`，不得回填或伪造历史 successor。`OPEN`/`CLOSING` 必须为 `NULL`；`SUBSTRATE_RAW_TOKEN` legacy `CLOSED` 继续为 `NULL` 且既有 row identity bytes 逐字不变。
3. `FORMAL_CLOSURE_ONLY` 只能在同一个 OMS transaction 内原子写入 `state=CLOSED` 与 exact lowercase hex64 successor。Formal CLOSED 的 row identity必须包含该 successor；所有 `NULL` 路径保持既有 digest payload逐字不变。
4. CLOSED replay必须 fresh读取持久 successor，重算 broker finality→OMS recovery→reconciliation→report/soak→terminal successor 完整 durable chain并逐字比较。合法 replay不得返回 `None`；缺失、错值、tamper、旧formal row或链漂移稳定fail closed。
5. tests覆盖v3/v7/v9升级、既有行保持、非法列值、formal CLOSED successor tamper与substrate legacy兼容。

### F2 — zero-command ORDER closure 回归 soak SSOT

- `soak.session_order_semantic_closure_identity` 是唯一公开canonical算法；`soak_runtime`删除私有zero-order digest域。
- zero-command必须证明本session无command且无孤儿ORDER receipt，以独立canonical zero payload绑定recovery/session；nonzero历史bytes不变。
- 测试锁定zero/nonzero replay、孤儿receipt、错session/recovery及私有fallback域不存在。

### F3 — terminal child写集分域

- OMS terminal repository只允许exact `oms_recovery` child；`broker_finality`、`reconciliation`、`report_soak`、`terminal_successor`、`closing_to_closed`及未知step均拒绝。
- 不得向其他步骤暴露通用可写repository；若需要只读事实，使用不暴露commit能力的现有/最窄接口。
- 测试覆盖wrong-step、nested/replayed/cross-thread与合法`oms_recovery`。

### F4 — soak evidence 锁内fresh闭包

- `before`、existing receipt及其bytes/identity全部移入同一anchored barrier lock内fresh读取；append前后都必须复验。
- 锁外快照不得参与step4或CLOSED replay。插入、替换、篡改、部分orphan或并发漂移必须保持`CLOSING`并fail closed，不得补写来源不明历史。
- 测试覆盖锁外插入/替换/篡改后进入closure、append前后漂移及same-token合法resume。

实现者须在delivery对F1–F4逐项写“现象—根因—规则—最小复现—新增测试—通过条件”，列actual exact33与未运行边界。终态上限仍仅 `UA-M4-006_WINDOWS_ENGINEERING_CLOSED`，不扩大至 PAPER、真实 soak 或 Linux Gate。

## 10. 独立复验返工 R2（2026-08-26）

R1 独立复验结论为 `R1_REVIEW_FAIL`。原 F1 durable successor 与 F4 锁内 fresh evidence 已静态闭合，原 F2/F3 缩小为以下两个缺口。本轮继续 exact33、同一 §13 授权采用者、原独立 reviewer 与全部禁止项；review 报告只读，返工后交回原 reviewer 再次追加复验。

### R1-F2 — true zero-command 的 identity、Gate 与测试统一

- 中央 §9 F2 已明确：真正 zero-command、无孤儿 ORDER receipt 时，由 `soak.session_order_semantic_closure_identity` 返回 canonical `SoakSessionOrderSemanticClosureZero`，这是成功闭包，不是 `MISSING`。
- 因此旧 `test_formal_empty_session_is_durably_blocked_without_order_receipt` 的“空会话必为 `SOAK_SESSION_ORDER_RECEIPT_MISSING` + BLOCKED”被本次重冻 supersede。若 recovery/reconciliation/report 无其他问题，true empty session 的 ORDER closure检查必须通过，整体 disposition按其余真实issues决定，不得人为保留MISSING。
- `SOAK_SESSION_ORDER_RECEIPT_MISSING` 仍用于“存在本 session command、但缺少所需 ORDER receipt”的非零场景；不得删除该可达错误语义。
- orphan ORDER receipt、错session/recovery、zero payload字段漂移必须 `SOAK_SESSION_ORDER_RECEIPT_INVALID`；补独立测试。
- 同步 `soak.py` gate issue逻辑与 `test_execution_soak.py` 冲突fixture；不得改非零历史identity bytes或弱化正式evidence Gate。

### R1-F3 — closure view 不暴露可 commit 的 OMS 面

- `VerifiedFormalPaperClosureView` 不得公开 raw `ExecutionStore`、`ExecutionRepository`、connection或任何可 `commit`/写的通用对象。删除/收窄 `open_oms_store`、`inspect_oms_under_terminal_child`、`inspect_oms_when_closed` 对 caller 的 raw返回。
- 改为最窄强类型操作：在 formal module 内部持有/验证 store，针对 live terminal child 或 CLOSED barrier fresh计算并返回 immutable `RecoveryResult` 与必要的 exact `SessionBarrierRow`/identity；caller只消费结果，不能升级为写。
- exact `oms_recovery` child 若确需提交型 transaction，也必须由窄方法内部使用并只返回 recovery结果；其他step仅内部rollback inspect。`soak_runtime`不得直接接触store/repository。
- 测试必须覆盖：wrong-step inspect返回对象无 `_conn`/commit/write接口；即使反射/`object.__new__`伪造也不能持久写；合法broker_finality只读recovery、合法oms_recovery与CLOSED replay仍闭合；view不再暴露raw store。

delivery追加R2六要素、逐文件修改与未运行边界。R2不得改已闭合的v10 row identity/legacy bytes/F4锁内顺序，除非发现直接冲突并STOP举证。

## 11. AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2（2026-08-26）

原实现链在 §12 及 delivery §15.4 两次违反明确的零 Python 过程合同；其中任何 `ast.parse` / `python -c` 结果均为无效证据，不恢复实现来源闭包。中央裁定当前状态为 `CONTRACT_DEVIATION_STOP / STATIC_ONLY_BREACH`，不得直接进入 Windows validation。

恢复合同：

1. 启动一个全新的、未参与前述实现的外部 Grok 4.5 High adopter；禁止 subagent、委派或复用原违规实现会话。
2. adopter 在 exact33 内逐文件审计当前 production/tests/delivery 字节，核对本任务书 §§1–10、delivery §12/§15.4 历史与 review 的 `R2_REVIEW_PASS`。可原样采用，或只做证明合同所需的最小修正；任何 exact33 外需求立即 STOP。
3. 全程 `STATIC_ONLY`：零 Python、`ast.parse`、pytest、Ruff、mypy、cold、SQLite、PAPER、真实 soak、网络、browser、stage、commit或任何脚本执行。不得把两次违规探针计入产品验证。
4. delivery 追加 `AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2`：逐文件采用结论、相对采用前 SHA/delta、F1–F4与R1-F2/R1-F3合同映射、两次违规证据隔离、actual scope与未运行边界。原 §12、§15.4 字节和结论永久保留，不覆盖、不洗白。
5. 若任何 production/test 字节改变，原独立 reviewer 必须完整复验；即使逐字采用，也必须由同一原 reviewer 核对最终 SHA、adoption delta、违约边界与无新增执行痕迹，追加 `ADOPTION_R2_REVIEW_PASS` 或 FAIL。
6. 退出前只允许只读 Git scope/diff 检查：actual 必须 `⊆ exact33`、cached=0、ordinary `git diff --check` PASS，且无新增执行 cache/evidence。只有 reviewer PASS 后才可重新申请完整 Windows VALIDATION1。

本轮状态上限仍为 `AUTHORIZED_REIMPLEMENTATION_ADOPTED / STATIC_ONLY`；B1B2 未验证，`UA-M4-006` 继续 OPEN。

## 12. VALIDATION1 focused 返工与 terminal 根因审计（2026-08-26）

VALIDATION1 有效证据：identity PASS；focused exact14 `555 passed / 4 failed / 7 skipped`；Ruff、mypy、cold、final scope均 `UNRUN`。资源已释放且无temp/cache/0xF00残留。返工交回 §11 的同一全新授权 adopter；原违规实现链不得恢复。保持 exact33 与全部真实运行禁止项。

### 12.1 两项确定的 test fixture 漂移

1. `test_v010_terminal_successor_column_upgrade_preserves_null_and_rejects_illegal` 在调用 `_oms_conn(tmp_path / "fresh")` 前必须显式创建 exact `fresh` 父目录；不得改 SQLite/store/migration API、自动创建任意父目录或弱化非法v10值拒绝。
2. `test_barrier_enabled_open_write_and_closing_rejects` 的既有 `schema_version()==9` 断言必须同步为当前合法 v10；OPEN普通写与CLOSING拒绝、row identity及migration历史断言保持不变，禁止回退schema或把v10改成兼容假象。

### 12.2 两项 terminal runtime 失败的 STATIC_ONLY 根因闭包

当前两个节点均只见 public `PAPER_SOAK_SESSION_INVALID`：

- `test_zero_command_session_closes_end_to_end_via_real_terminal_machinery` 首次真实terminal链失败；
- `test_mid_sequence_failure_stays_closing_and_resumes_on_retry` 已证明首次注入失败后保持CLOSING、broker finality只写一次，但same-token retry仍失败。

冻结审计：

1. 沿真实窄接口逐step静态映射：broker finality → OMS recovery/ORDER semantic closure → reconciliation → report/soak append → terminal successor bind → exact CLOSING→CLOSED。逐项核调用入参、durable identity、resume precondition与错误归一位置，不能只看最终sanitize码猜测。
2. 允许在现有 exact33 tests 内增加 test-owned step observation/seam，记录首次与retry到达的公开窄步骤、稳定码与durable side-effect count；不得修改production异常边界以泄露内部对象/路径，不得暴露raw store/repository/connection/live barrier或绕过真实terminal machinery。
3. 若静态证据能证明fixture缺少canonical输入/身份，最小修fixture并锁真实闭包；若证明production逻辑错误，只在exact33做最小修复，保持same-token、non-atomic resume、orphan/tamper fail-closed与zero-command/非零码面。
4. 特别保持：首次失败不能回OPEN或换token；broker finality经济影响exact1；retry必须fresh复核已完成step再继续；existing partial事实错identity/错序必须拒绝，不能补写来源不明历史。
5. 不得用 broad catch、bool、marker、mock最终返回值、手工CLOSED row或跳过真实step令测试假绿。若根因需要exact33外路径，立即 `CONTRACT_STOP` 举证。

### 12.3 写入、证据与复验

- adopter可修改exact33内必要production/tests与delivery；taskbook/review只读。
- delivery追加四项完整“现象—根因—规则—最小复现—新增测试—通过条件”，引用 VALIDATION1 evidence root与关键SHA，明确 `555/4/7` 及后续 `UNRUN`，保留§12/§15.4历史违约与§16授权采用。
- 全程零Python、`ast.parse`、pytest、Ruff、mypy、cold、SQLite、脚本、PAPER、soak、network、stage/commit。完成后原独立 reviewer 完整复验；PASS后重新申请完整 VALIDATION2（identity→focused exact14→Ruff exact30→mypy production16→cold production16→exact33 scope）。

## 13. VALIDATION2 Ruff test-only 收敛（2026-08-26）

VALIDATION2 有效证据：identity PASS；focused exact14 `559 passed / 7 skipped`；Ruff exact30 在 `tests/unit/test_session_barrier.py` 以6项首失败 STOP；mypy、cold、final scope均 `UNRUN`。未发现production Ruff失败。

授权 §11 同一 fresh adopter 在 `STATIC_ONLY` 下仅修改：

- `tests/unit/test_session_barrier.py`
- `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`

冻结修正：

1. 从测试文件顶部删除未使用的 `recover_session_barrier_closure_capability` 与 `unpack_session_barrier_closure_capability` 两个导入。
2. 保留两个测试函数内部各自的局部导入、真实调用、参数、异常与全部断言；不得把局部导入搬回顶部、删除调用或用自动fix/noqa/ignore掩盖。
3. production、其他tests、taskbook/review（本次经理追加除外）全部冻结；不改变barrier capability、closure、migration、identity或测试时序。
4. delivery追加 VALIDATION2 evidence root、focused/Ruff/summary SHA、`559/7`与后续 `UNRUN` 边界及六要素。零Python/工具/脚本/stage/commit。
5. 原独立 reviewer 复验最小diff；PASS后申请postfix：identity→Ruff exact30→mypy production16→cold production16→exact33 scope/residue，不重复已绿focused559。

## 14. POSTFIX VALIDATION3 context-manager 类型合同返工（2026-08-26）

POSTFIX VALIDATION3 有效证据：identity PASS；Ruff exact30 PASS；mypy production16 在 `soak_runtime.py` 的七个 `with` 使用点共报14项首失败；cold与final scope `UNRUN`。既有 VALIDATION2 focused exact14 `559 passed / 7 skipped` 保持有效。根因是 `VerifiedFormalPaperClosureView.hold_terminal_closure(...)` 与 `hold_terminal_step(...)` 的运行实现返回 context manager，但公开窄 view 注解均为 `object`，静态类型系统无法证明 `__enter__`/`__exit__`。

授权 §11 同一 fresh adopter 在 `STATIC_ONLY` 下最小返工：

1. 仅修改 `src/quant/execution/paper_formal_service.py` 与既有 delivery；其他 production/tests、taskbook（本节经理追加除外）与 review 冻结。
2. 将两个 `hold_*` 方法的返回类型收窄为标准、最窄的同步 context-manager 类型（例如 `AbstractContextManager[object]` 或源码现有风格的等价精确类型）；补所需标准库类型 import。
3. 不修改函数体、调用顺序、锁/permit/child capability、异常、identity、schema、bytes或任何运行分支；不得使用 `Any`、`cast`、`type: ignore`、Protocol泛化或把live capability暴露给caller。
4. delivery记录现象、根因、类型规则、最小复现、修正、通过条件与 evidence root `artifacts/agent_runs/m4-b1b2-postfix-validation3-20260826T071119Z/`；绑定 Ruff stdout SHA `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF`、mypy stdout SHA `50441960AFDAED980CA6D27209BFC090C4EFFA28D3BF6B80C410FF2C8F5F5299`、summary SHA `6EDCE34C52DEBAAA4CCF180DF1DB8F46637EFE281F8C548009649544AD414B67`。
5. 原独立 reviewer 复验仅 import+两处返回注解变化、runtime/schema/escape边界不变。PASS后申请窄 VALIDATION4：identity→Ruff实际修改production文件→mypy production16→cold production16→exact33 scope/residue；不重复已绿 focused559 与 Ruff其余文件。

零Python、SQLite、PAPER、真实soak、network、stage或commit。状态仍只到B1B2 Windows工程验证候选，`UA-M4-006` 保持 OPEN。

## 15. Windows 工程验证组合闭包与证据复核（2026-08-26）

本包Windows开发验证以组合证据闭合，不伪造单轮全绿：VALIDATION2 focused exact14 `559 passed / 7 skipped`；VALIDATION4 identity、Ruff实际修改文件、mypy production16、cold production16 PASS；scope-close5 actual19⊆exact33、cached0、diff-check、temp/cache/process与writer身份 PASS。历史VALIDATION1–3及scope-close1–4的首失败和carrier缺口全部保留，不改写为通过。

授权同一fresh adopter仅更新既有delivery的最终执行证据、各轮真实首失败/UNRUN、关键SHA、组合范围与剩余边界；production/tests/review冻结，零Python、零stage/commit。状态最多写 `B1B2_WINDOWS_ENGINEERING_VALIDATED`。

随后由同一原独立reviewer仅写唯一review报告完成 `EVIDENCE_REVIEW`：核对各evidence root/关键SHA/exit、actual19⊆exact33、F1至本节返工链、无证据矛盾及无Gate过度声明，输出 `EVIDENCE_REVIEW_PASS` 或 FAIL。只有PASS后才申请安全提交。

边界继续保持：`SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN`；不声称真实PAPER、真实soak、新root/epoch实证、Linux Gate或用户事项关闭。

### 15.1 组合证据索引（adopter 闭合记录；2026-08-26）

权威细节与关键 SHA 以 delivery §20 为准。摘要：

| 轮次 | 结论（不洗白历史首失败） |
|---|---|
| VALIDATION1 | identity PASS；focused `555/4/7` FAIL STOP；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION2 | identity PASS；focused **559/7** PASS；Ruff F401/F811 STOP；mypy/cold/scope **UNRUN** |
| VALIDATION3 postfix | identity+Ruff PASS；mypy 14×attr-defined STOP；cold/scope **UNRUN** |
| VALIDATION4 postfix | identity+Ruff(本文件)+mypy+cold **PASS**；内嵌 06-scope SCOPE_EXTRA FAIL（不改写工程绿） |
| scope-close1–4 | 首失败/carrier 缺口保留（见 delivery §20） |
| scope-close5 | **PASS**：actual19⊆exact33、cached0、diff-check、temp/cache/process、writer 身份 |

状态上限本包：`B1B2_WINDOWS_ENGINEERING_VALIDATED`。`UA-M4-006` / 真实 PAPER/soak/Linux **仍 OPEN/排除**。下一步：原独立 reviewer `EVIDENCE_REVIEW`。
