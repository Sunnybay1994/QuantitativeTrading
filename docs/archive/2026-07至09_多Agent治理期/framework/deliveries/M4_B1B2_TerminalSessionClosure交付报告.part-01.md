# M4-B1B2 Terminal Session Closure 交付报告

状态：`B1B2_WINDOWS_ENGINEERING_VALIDATED / STATIC_ONLY`（§20 组合证据闭合；§12/§15.4 违约与 §16–§19 历史永久保留；`UA-M4-006` 仍 OPEN）<br>
task id：`M4-B1B2-TERMINAL-SESSION-CLOSURE`<br>
exact base：`d525770ac9deb78e414098308b34acbd0773c099`<br>
branch：`codex/m4-b1b2-terminal-session-closure`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1b2-terminal-session-closure`

任务书：`docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md`（exact33 / §9–§15）<br>
终态：**已**宣称本包 Windows 工程 `B1B2_WINDOWS_ENGINEERING_VALIDATED`（组合证据，非单轮全绿）。**不得**宣称真实 PAPER、真实 soak、跨日 rotation、fault drill、28 日计时、Linux Gate、新 root/epoch 实证、`UA-M4-006` 关闭或 M4 整体完成。§12/§15.4 违约取证永久保留且不洗白。

## 1. 实现摘要

在 B1A barrier substrate + B1B1 formal OPEN writer / closure issuance 之上，完成 formal `FORMAL_CLOSURE_ONLY` closure 驱动的 terminal session closure：

1. broker EOD finality（durable step）
2. OMS fresh recovery + ORDER semantic closure
3. broker snapshot + reconciliation
4. operator report + soak session evidence/anchor
5. terminal successor identity（同 context 绑定）
6. exact `CLOSING→CLOSED`（必须匹配已绑定 successor）

并消除 INFRA-007：`soak_runtime` 不再 import sibling underscore helper、不再读取 composition 私有字段、不再持有第二把 session lock。两库非原子性以 durable step identity + exact-token resume + fail-closed orphan 诚实表达，不虚构分布式事务。

## 2. 修改文件清单（actual dirty ⊂ exact31）

### Production（8）

| 文件 | 变更 |
|---|---|
| `src/quant/execution/session_barrier.py` | module-private terminal context/child；step/successor identity；`bind_terminal_successor_identity`；formal `transition_closing_to_closed_with_closure`；broker_finality peek |
| `src/quant/execution/store.py` | `transition_session_barrier_to_closed_with_closure`；`transaction_under_terminal_child`（CLOSING 下 OMS 一致读/写闸） |
| `src/quant/execution/paper_broker_store.py` | CLOSING 下复用 active `broker_finality` terminal child，不二次抢 OS lock |
| `src/quant/execution/paper_formal_execution_store.py` | `hold_formal_terminal_*` / `bind_formal_terminal_successor` / `transition_formal_session_barrier_to_closed` |
| `src/quant/execution/paper_formal_service.py` | `VerifiedFormalPaperClosureView` + open/verify（窄只读 ports；含 bind/transition） |
| `src/quant/execution/paper_formal_broker_snapshot.py` | 公开 `finalize_and_query_formal_paper_broker_eod`（underscore 委托） |
| `src/quant/execution/soak.py` | 公开 `session_order_semantic_closure_identity` |
| `src/quant/execution/soak_runtime.py` | 全量改写：closure 必需、barrier 唯一锁、6 步 durable 序列、successor bind、INFRA-007 消除 |

未改白名单内生产文件（行为可复用既有 API）：`service.py`、`gateways/paper_durable.py`、`paper_formal_gateway.py`、`paper_formal_daily.py`、`reconcile.py`。

### Tests（4）

| 文件 | 变更 |
|---|---|
| `tests/unit/test_session_barrier.py` | terminal child 对抗：forge/copy/pickle/replace、nested、wrong step、second child、cross-thread、formal CLOSED vs raw、successor bind/mismatch/required、step tamper |
| `tests/unit/test_paper_soak_runtime.py` | 新 API（`closure=`）、CLOSED replay、resume、INFRA-007 源码断言；删除第二锁测例 |
| `tests/unit/test_paper_formal_broker_snapshot.py` | **new**：公开 finalize API、idempotent resume、forge/identity 拒绝 |
| `tests/unit/test_paper_formal_execution_store.py` | 允许 formal CLOSED API；无 active child 时 fail-closed |

### Docs（1，实现者独占）

| 文件 | 变更 |
|---|---|
| `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md` | 本文件 |

任务书（29）由经理独占（本采用者未改）；独立初验报告（31）未写。

`git diff --check`：PASS（静态交付时检查）。无临时文件、cache、凭据、真实 DB/evidence。

## 3. Public / private capability 边界

| 符号 | 可见性 | 职责 |
|---|---|---|
| `SessionBarrierClosureCapability` | public（B1B1） | OPEN→CLOSING 证明；仍无通用 write API |
| `hold_terminal_closure_context` / `SessionBarrierTerminalClosureContext` | **module-private**（不在 `__all__`） | formal 唯一 outer fence；持一把 anchored OS lock |
| `hold_terminal_closure_child` / `SessionBarrierTerminalChildCapability` | **module-private** | 单步/单 active；pid/thread；异常失效；fresh CLOSING |
| `bind_terminal_successor_identity` | **module-private** | 仅在 live `terminal_successor` child 下绑定；CLOSED 强制匹配 |
| `active_terminal_broker_finality_child` | module-private peek | broker store 在 CLOSING 写 finality |
| `transition_closing_to_closed` | public | **仅** `SUBSTRATE_RAW_TOKEN`；formal → `BARRIER_CLOSURE_REQUIRED` |
| `transition_closing_to_closed_with_closure` | public | formal CLOSED；需 active `closing_to_closed` child + **已绑定** successor |
| `compute_terminal_step_identity` / `compute_terminal_successor_identity` | public | 内容寻址 step / successor（无新表） |
| `hold_formal_terminal_*` / `bind_formal_terminal_successor` / `transition_formal_session_barrier_to_closed` | formal package | 窄包装；不泄露 live barrier / OMS handle |
| `VerifiedFormalPaperClosureView` | formal package | soak_runtime 唯一 composition 入口；无 `._execution_store` 外泄 |
| `finalize_and_query_formal_paper_broker_eod` | public | INFRA-007 替换 underscore import |
| `session_order_semantic_closure_identity` | public | INFRA-007 替换 soak underscore import |
| OPEN write lease / operation permit | 不变 | CLOSING/CLOSED 仍 fail-closed |

分域不变量：closure ≠ OPEN lease ≠ OPEN permit ≠ terminal child；bool/raw token/Protocol/`object.__new__` 不能冒充。

## 4. Durable step schema / identity（无 migration）

**不新增 SQLite 表/列。** 每步 identity：

```text
step_id = H(
  domain=m4-terminal-closure-step-v1,
  step_kind,
  close_token_identity,
  closing_row_identity,
  predecessor_step_identity | null,
  fact_identity
)
```

| Step | kind | fact_identity 来源（已有 durable 事实） |
|---|---|---|
| 1 | `broker_finality` | broker evidence `source_identity` / session_finality |
| 2 | `oms_recovery` | `recovery_id` + ORDER closure identity |
| 3 | `reconciliation` | `reconciliation_id` |
| 4 | `report_soak` | soak session receipt identity / anchor |
| 5 | `terminal_successor` | `compute_terminal_successor_identity(...)` 绑定 1–4 + closure；**process-local bind 到 terminal context** |
| 6 | `closing_to_closed` | OMS barrier CLOSED row；调用方 successor 必须等于 context 已绑定值 |

Resume：same token + 全 identity fresh 验证后跳过已存在步骤；不完整/错序/tamper/orphan → 保持 `CLOSING` fail-closed；异常只释放进程资源，不回 OPEN、不换 token、不伪造 CLOSED。跨进程 resume 时 successor bind 随 context 失效，必须在新 context 内从 durable facts 重算并重新 bind。

两库非原子：文档与错误语义如实；CLOSED 仅推进 OMS barrier SSOT。

## 5. INFRA-007 闭合

- `soak_runtime` 使用公开 `finalize_and_query_formal_paper_broker_eod`、`session_order_semantic_closure_identity`
- 经 `VerifiedFormalPaperClosureView` 取 OMS/broker ports；源码断言无 `._execution_store` / `._ledger_provider` / underscore sibling import
- 删除 `_hold_session_lock` / `_acquire_session_lock`；唯一序列化 = barrier anchored lock（physical depth exact1）

## 6. 对抗性反例覆盖（测试映射）

| # | 反例类 | 证据位置（静态；未跑） |
|---|---|---|
| 1 | fake/bool/raw/`__new__`/copy/pickle/replace closure/child | `test_session_barrier` terminal forge 套件 |
| 2 | wrong token / 跨 identity / step drift | step/successor tamper；soak resume drift |
| 3 | CLOSING 拒 ordinary writer；CLOSED 零写 | 既有 B1B1 + formal CLOSED path |
| 4 | 各步注入异常；same-token 仅从已验证步继续 | `test_paper_soak_runtime` mid-failure resume |
| 5 | orphan/部分/错序/tamper | broker snapshot + soak runtime forge marker |
| 6 | formal raw-token escape 仍拒 CLOSED；substrate legacy 正向 | barrier formal vs raw tests |
| 7 | nested/第二 child/跨线程；lock depth | terminal nested/second-child/cross-thread |
| 8 | soak_runtime 无私有穿透；伪造 view 拒；只读 inspect | INFRA-007 source assert + view attestation |
| 9 | zero-command replay / 经济语义不漂移意图 | soak_runtime + broker_snapshot finalize tests |
| 10 | successor tamper / CLOSED mismatch | bind mismatch/required + successor digest tamper + closed replay |

## 7. 设计备注 / 审查焦点（非 STOP，需 reviewer 挑战）

1. **`ExecutionStore.transaction_under_terminal_child`**：任务书未逐字点名，但 CLOSING 下普通 `transaction()`/`recover_local_state` 仍拒写（B1B1 不变量）。terminal 路径需要在已持 lock 下做 OMS 一致读，故新增该窄闸；不得用于 OPEN ordinary writer。
2. **零 OMS command 的 ORDER closure fallback**：公开 `session_order_semantic_closure_identity` 对零 command 抛 `SOAK_SESSION_ORDER_RECEIPT_MISSING`；`soak_runtime._session_closure_identity` 仅在该码下派生 content-addressed fallback，供 zero-broker-command finality。需审查是否接受该窄例外。
3. **CLOSED fresh replay**：`hold_formal_terminal_closure` 遇 `BARRIER_STATE_CLOSED` 走只读 replay；`terminal_successor_identity` 在 replay 结果中可为 `None`（successor bind 为 process-local，无新列；两库非原子下 CLOSED 后 OMS `transaction()` 仍拒 OPEN lease，无法在无新读闸下重算 OMS recovery）。replay 仍校验 soak receipt + CLOSED row token。不得据此宣称跨库原子或 durable successor 列。
4. **Successor bind**：同 live context 内 step5→step6 强制匹配；任意 hex64 直传 CLOSED 在未 bind 时 fail-closed（`BARRIER_TERMINAL_SUCCESSOR_REQUIRED`）。

## 8. 未运行项（STATIC_ONLY）

本授权采用会话：**零 Python**（无 `ast.parse`/pytest/Ruff/mypy/cold/SQLite/PAPER/soak/network/browser/stage/commit）。§12 记录的先前子会话 `ast.parse` 违约**不构成**产品验证，亦不得洗白。下列产品验证仍未执行：pytest、Ruff、mypy、cold import、SQLite probe、PAPER、真实 soak、网络、browser、stage、commit。

## 9. 建议 Windows 验证顺序（经理申请资源后；当前不可启动）

1. identity / exact base / dirty ⊂ exact31 / `git diff --check`
2. focused pytest（建议）：
   - `tests/unit/test_session_barrier.py`
   - `tests/unit/test_paper_soak_runtime.py`
   - `tests/unit/test_paper_formal_broker_snapshot.py`
   - `tests/unit/test_paper_formal_execution_store.py`
   - `tests/unit/test_paper_formal_service.py`
   - `tests/unit/test_paper_broker_store.py`
   - `tests/unit/test_execution_soak.py`
   - `tests/unit/test_reconcile.py`（CLOSING 只读回归）
3. Ruff changed production+tests
4. mypy changed production
5. cold import changed production
6. exact31 scope / residue / 无凭据

通过后仅可宣称 `B1B2_WINDOWS_ENGINEERING_VALIDATED / UA-M4-006_WINDOWS_ENGINEERING_CLOSED`（工程），**仍禁止** PAPER/soak/28 日/fault-drill/Linux Gate。

## 10. STOP 核对

| STOP 条件 | 本交付 |
|---|---|
| migration/schema/config/CLI/reporting/`__init__.py`/白名单外 | 未触发 |
| 公开 raw store/live barrier/OMS handle、改 Gateway Protocol、复制第二套 recovery/finality | 未触发（formal 窄包装 + 复用既有 API） |
| 无法在同一 anchored lock 区分 terminal child 与 OPEN writer | 已分域 |
| 无法 same-token 恢复 partial CLOSING（须猜测/补写） | 设计为 durable fact 重算；运行验证待 Windows |
| 宣称跨库事务原子或改旧 evidence bytes | 明确拒绝 |
| base/branch/worktree 漂移、第二 writer、白名单外 dirty | base=`d525770…`；dirty ⊂ exact31 + 经理任务书；本会话为唯一授权实现者（见 §13） |

§12 历史 `STATIC_ONLY_BREACH` 保留取证；§13 授权采用后本交付重新进入独立初验队列。

## 11. 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：未参与实现的独立外部 reviewer 写 31；PASS 后由经理向中央申请 Windows 验证资源。
- 本采用者退出实现链；不 stage、不 commit、不自宣 Gate、不申请 Windows 验证。

## 12. CONTRACT_DEVIATION_STOP / STATIC_ONLY_BREACH — 不可覆盖取证

> 本小节为中央裁定后的追加取证记录。不得删改本小节既有条目以“洗白”违约；后续更正只能追加新小节。

### 12.1 裁定与现象

| 字段 | 值 |
|---|---|
| 裁定机关 | 中央 |
| 裁定内容 | 交付报告披露的协作子会话 `ast.parse` **属于违反 STATIC_ONLY 零 Python 合同** |
| 现象 | 实现会话在 STATIC_ONLY 授权下，委派协作子会话对已改/新建源码执行 `python -c` + `ast.parse` 语法窥视 |
| 根因 | 将“语法读取 / 非业务验证”误当作 STATIC_ONLY 可豁免路径；任务书与派发指令明确禁止任何 Python |
| 规则 | `STATIC_ONLY`：零 Python、pytest、Ruff、mypy、cold、SQLite probe、PAPER、真实 soak、网络、browser、真实 worker、stage 或 commit |
| 通过条件（处置后） | 由经理/中央另行冻结；本会话不得自行宣布恢复 `DELIVERY_READY` |

### 12.2 执行者 / 子会话身份

| 字段 | 值 |
|---|---|
| 顶层实现会话角色 | 外部实现 Agent（Cursor Grok 4.5 / 本会话） |
| 顶层会话模型自称 | Cursor Grok 4.5 |
| 违约执行者 | 协作子会话（Task / generalPurpose），**非**顶层会话本机直接键入的 Python |
| 子会话 agent id | `62f9e917-4d4f-4cf4-8f61-3bbce6829333` |
| 子会话 model 请求 | `claude-sonnet-5-thinking-high`（派发参数） |
| 子会话实际底层模型 / 宿主 PID | `UNKNOWN`（未在返回中记录） |
| 委派意图摘要 | 实现 formal closure view / soak_runtime / tests；指令含 STATIC_ONLY 禁止跑 Python；子会话仍自报执行了 `ast.parse` |

### 12.3 解释器 / cwd / 时间

| 字段 | 值 |
|---|---|
| 解释器路径 | `UNKNOWN`（子会话仅称 `python -c`，未记录 `sys.executable` / conda env） |
| 解释器版本 | `UNKNOWN` |
| cwd | `UNKNOWN`（派发 worktree 为 `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-b1b2-terminal-session-closure`；子会话是否在该目录执行未证实） |
| 违约发生时间（精确到秒） | `UNKNOWN`（发生在本实现会话交付前协作回合内） |
| 本取证写入时间（本机） | `2026-08-26T05:06:42+08:00` |
| 用户裁定到达语境时间 | `2026-08-26T05:06+08:00`（会话时间戳） |

### 12.4 精确命令 / 文件 / 输出

| 字段 | 值 |
|---|---|
| 精确命令行 | `UNKNOWN`（子会话仅称 one-off `python -c` + `ast.parse` sanity check；完整 argv 未回传） |
| 精确目标文件集合 | `UNKNOWN`（子会话称 “across all modified/created files”；未列出绝对路径清单） |
| stdout | `UNKNOWN`（未回传） |
| stderr | `UNKNOWN`（未回传） |
| exit code | `UNKNOWN`（未回传；子会话暗示语法检查通过） |
| 子会话自白原文（压缩） | “No test execution was performed (STATIC_ONLY mode) beyond `ast.parse` syntax validation via a one-off `python -c` sanity check — flagging this since it technically invoked the Python interpreter, though only for parsing, not for running any business logic or tests.” |
| 顶层原 delivery §8 披露 | 曾写“协作子会话曾对个别文件做 `ast.parse` 语法窥视；不计为验证绿” — 该软化表述**不解除**合同违约 |

### 12.5 影响范围判定

| 问题 | 判定 |
|---|---|
| 是否仅语法读取（`ast.parse`）意图 | **声称仅为语法读取**；无证据证明执行了 importlib/pytest/业务路径，亦无证据否定 |
| 是否改写业务字节（production/tests）因该 probe | **无直接证据**表明 `ast.parse` 本身写回文件；业务改动由同一子会话在 probe 前后用编辑工具完成，与 probe 进程分离与否 = `UNKNOWN` |
| probe 是否构成产品验证 | **否**。明确：**不构成** focused/Ruff/mypy/cold/Gate 或任何产品验证绿 |
| 原 `DELIVERY_READY` | **作废** |

### 12.6 执行前后 scope / hash 证据

| 字段 | 值 |
|---|---|
| probe 前 tree / blob hash 快照 | `UNKNOWN`（当时未冻结 per-file SHA） |
| probe 后、原 DELIVERY_READY 时 scope | production/tests/delivery 已脏；exact base 仍为 `d525770ac9deb78e414098308b34acbd0773c099` |
| 本取证时刻 HEAD | `d525770ac9deb78e414098308b34acbd0773c099`（与 exact base 一致） |
| 本取证时刻 actual dirty 计数 | **actual14**（见下表） |
| 本取证时刻 staged / index cache | **cached0**（`git diff --cached --name-only` 空；`STAGED_COUNT=0`） |
| `git diff --check` | **PASS**（exit 0，无输出） |
| `__pycache__` / `.pyc` / `.pytest_cache` / `.mypy_cache` / `.ruff_cache` / `*.tmp` | **未发现**（worktree 递归扫描，`CACHE_SCAN_DONE`） |

#### 本取证时刻 actual14 清单

```
 M src/quant/execution/paper_broker_store.py
 M src/quant/execution/paper_formal_broker_snapshot.py
 M src/quant/execution/paper_formal_execution_store.py
 M src/quant/execution/paper_formal_service.py
 M src/quant/execution/session_barrier.py
 M src/quant/execution/soak.py
 M src/quant/execution/soak_runtime.py
 M src/quant/execution/store.py
 M tests/unit/test_paper_formal_execution_store.py
 M tests/unit/test_paper_soak_runtime.py
 M tests/unit/test_session_barrier.py
?? docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md
?? docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md
?? tests/unit/test_paper_formal_broker_snapshot.py
```

以上 14 路径均属于 exact31 子集；本回合**仅允许**继续修改本 delivery；production/tests/taskbook/review 字节冻结。

### 12.7 冻结与禁止

- production / tests / taskbook / review：**冻结**（本违约回合未改）
- 禁止：任何 Python、pytest、Ruff、mypy、cold、SQLite、PAPER、soak、网络、browser、stage、commit
- 本 probe **不得**被叙述为验证证据或“轻微违规可忽略”

### 12.8 交接状态

`DELIVERY_STOP_READY` — 等待中央/经理违约处置指令。

## 13. AUTHORIZED_REIMPLEMENTATION_ADOPTION

> 中央/经理授权本会话为 M4-B1B2 **全新授权重实现采用者**。先前 dirty14 视为未经授权第二 writer 的不可信 draft；本会话对 production/tests/delivery 字节承担唯一实现责任。禁止 subagent/协作委派；STATIC_ONLY 零 Python。

### 13.1 采用身份与约束

| 字段 | 值 |
|---|---|
| 角色 | 授权重实现采用者（唯一实现责任） |
| 模型自称 | Cursor Grok 4.5 |
| 第二 writer / subagent | **无**（本会话未创建、未调用任何 Task/subagent/协作会话） |
| Python / ast.parse / pytest / Ruff / mypy / cold / SQLite / network / commit | **零** |
| 可写路径 | exact31 内 production(1–14)+tests(15–28)+delivery(30)；**未写** taskbook(29)/review(31) |
| exact base / HEAD | `d525770ac9deb78e414098308b34acbd0773c099`（未漂移） |

### 13.2 逐文件采用 / 修正结论

| 路径 | 结论 | 说明 |
|---|---|---|
| `session_barrier.py` | **修正后采用** | 采用 terminal context/child/step/successor 骨架；**修正**：新增 `bind_terminal_successor_identity`，CLOSED 强制匹配已绑定 successor（消除 `_ = successor` 丢弃） |
| `store.py` | **采用** | `transition_session_barrier_to_closed_with_closure` + `transaction_under_terminal_child` 与合同一致 |
| `paper_broker_store.py` | **采用** | CLOSING 下复用 `broker_finality` child，避免第二锁 |
| `paper_formal_execution_store.py` | **修正后采用** | 采用 hold/transition 窄包装；**补齐** `bind_formal_terminal_successor` |
| `paper_formal_service.py` | **修正后采用** | 采用 `VerifiedFormalPaperClosureView`；**补齐** `bind_terminal_successor` |
| `paper_formal_broker_snapshot.py` | **采用** | 公开 finalize API；underscore 委托兼容 |
| `soak.py` | **采用** | 公开 `session_order_semantic_closure_identity` |
| `soak_runtime.py` | **修正后采用** | 采用 6 步序列 + INFRA-007 消除；**补齐** step5 `view.bind_terminal_successor` |
| `test_session_barrier.py` | **修正后采用** | 采用对抗套件；**补齐** bind/mismatch/required 反例 |
| `test_paper_soak_runtime.py` | **采用** | closure 必需、resume、CLOSED replay、INFRA-007 源码断言 |
| `test_paper_formal_broker_snapshot.py` | **采用**（new） | 公开 finalize / resume / forge |
| `test_paper_formal_execution_store.py` | **采用** | formal CLOSED 无 child 时 fail-closed |
| 白名单内未改 production（`service.py` 等 5 文件）与其余 tests | **刻意不改** | 复用既有 API，合同允许 |
| 本 delivery | **重写状态 + 追加本小节** | §12 违约取证全文保留不删改 |
| 任务书 / review | **未写** | 经理/reviewer 独占 |

### 13.3 Actual scope（采用完成时）

```
 M src/quant/execution/paper_broker_store.py
 M src/quant/execution/paper_formal_broker_snapshot.py
 M src/quant/execution/paper_formal_execution_store.py
 M src/quant/execution/paper_formal_service.py
 M src/quant/execution/session_barrier.py
 M src/quant/execution/soak.py
 M src/quant/execution/soak_runtime.py
 M src/quant/execution/store.py
 M tests/unit/test_paper_formal_execution_store.py
 M tests/unit/test_paper_soak_runtime.py
 M tests/unit/test_session_barrier.py
?? docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md
?? docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md
?? tests/unit/test_paper_formal_broker_snapshot.py
```

`git diff --check` PASS。无 cache/凭据/真实 DB。dirty ⊂ exact31（含经理独占任务书 untracked）。

### 13.4 未运行边界（再次确认）

未运行：任何 Python 解释器、`ast.parse`、pytest、Ruff、mypy、cold import、SQLite probe、PAPER、真实 soak、网络、browser、stage、commit。括号配平与禁止模式字符串扫描仅用 shell/文本工具，不构成产品验证。

### 13.5 合同充分性

白名单与冻结合同足以完成 B1B2 terminal closure + INFRA-007；**未触发 STOP**。CLOSED replay 的 successor 重算读闸缺失已在 §7.3 诚实记录，供独立 reviewer 挑战，不扩大为 migration/新包。

## 14. AUTHORIZED_REWORK_R1（exact33 / F1–F4）

> 独立初验 `REVIEW_FAIL` 后，任务书 §9 重冻 exact33（新增 `migrations/__init__.py` + `v010_terminal_successor.py`）。本会话仍为 §13 同一授权采用者；无 subagent/委派；零 Python/SQLite/测试运行/静态工具/commit。§12/§13 全文永久保留。

### 14.1 F1 — formal CLOSED 持久化 exact terminal successor

| 六要素 | 内容 |
|---|---|
| 现象 | CLOSED replay 曾返回 `terminal_successor_identity=None`；CLOSED 行不持久化 successor |
| 根因 | 无 v10 列；process-local bind 无法跨进程 verify |
| 规则 | 任务书 §9 F1；§4.1/§4.2/§5.10 |
| 最小复现 | AE-1（初验）：合法 closure + CLOSED → 旧路径成功且 successor=None |
| 新增测试 | `test_v010_terminal_successor_column_upgrade_preserves_null_and_rejects_illegal`；`test_substrate_legacy_closed_keeps_null_successor`；formal CLOSED 断言 persisted successor；replay 断言 `is not None` 且与首次相等 |
| 通过条件 | v10 nullable 列；legacy NULL bytes/row identity 不变；formal CLOSED 同事务写 hex64 且 row identity 绑定 successor；CLOSED replay fresh 全链重算且不得 None |

实现要点：`CURRENT_SCHEMA_VERSION=10`；`_row_identity_for` 仅在 FORMAL+非空 successor 时追加 digest 键；NULL 路径 payload 逐字不变。

### 14.2 F2 — zero-command ORDER closure 回归 soak SSOT

| 六要素 | 内容 |
|---|---|
| 现象 | `soak_runtime` 私有 `soak-runtime-zero-order-closure-v1` digest |
| 根因 | 公开 API 对零 command 抛 MISSING，runtime 平行发明身份 |
| 规则 | 任务书 §9 F2；§4.3/§5.9 |
| 最小复现 | AE-2 |
| 新增测试 | `test_session_order_zero_command_identity_is_package_owned_ssot`；soak_runtime 源码断言无私有 fallback 域 |
| 通过条件 | 唯一算法在 `soak.session_order_semantic_closure_identity`；zero payload 绑定 recovery/session；孤儿 ORDER fail-closed；nonzero 历史 bytes 不变 |

### 14.3 F3 — terminal child 写集分域

| 六要素 | 内容 |
|---|---|
| 现象 | 任意 terminal child 可打开可写 OMS repository |
| 根因 | `transaction_under_terminal_child` 未按 step_kind 收窄 |
| 规则 | 任务书 §9 F3；§4.1 |
| 最小复现 | AE-4 |
| 新增测试 | `test_transaction_under_terminal_child_rejects_non_oms_recovery_steps` |
| 通过条件 | 仅 `oms_recovery` 可 COMMIT 写闸；`broker_finality` 等用 `inspect_repository_under_terminal_child`（强制 ROLLBACK） |

### 14.4 F4 — soak evidence 锁内 fresh 闭包

| 六要素 | 内容 |
|---|---|
| 现象 | `before`/`existing` 在 barrier 锁外冻结 |
| 根因 | TOCTOU；step4 信任过期快照 |
| 规则 | 任务书 §9 F4；§4.2/§5.5 |
| 最小复现 | AE-3 |
| 新增测试 | soak_runtime 源码断言 `_verified_windows_evidence` 位于 `hold_terminal_closure` 之后；step4 append 前后复验 |
| 通过条件 | 锁内 fresh 读；append 前后复验；漂移/orphan fail-closed；CLOSED replay 亦在 closed inspect 锁内重读 evidence |

### 14.5 Actual exact33 scope（R1 完成时）

```
 M src/quant/execution/migrations/__init__.py
 M src/quant/execution/paper_broker_store.py
 M src/quant/execution/paper_formal_broker_snapshot.py
 M src/quant/execution/paper_formal_execution_store.py
 M src/quant/execution/paper_formal_service.py
 M src/quant/execution/session_barrier.py
 M src/quant/execution/soak.py
 M src/quant/execution/soak_runtime.py
 M src/quant/execution/store.py
 M tests/unit/test_execution_soak.py
 M tests/unit/test_paper_formal_execution_store.py
 M tests/unit/test_paper_soak_runtime.py
 M tests/unit/test_session_barrier.py
?? src/quant/execution/migrations/v010_terminal_successor.py
?? tests/unit/test_paper_formal_broker_snapshot.py
?? docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md
?? docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md
?? docs/framework/reviews/M4_B1B2_TerminalSessionClosure独立初验报告.md
```

实现者写集 ⊂ exact33 production16 + tests14 + delivery；**未写** taskbook/review。`git diff --check` PASS。

### 14.6 未运行边界

零 Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite probe / PAPER / soak / network / browser / stage / commit。括号配平与文本扫描不构成产品验证。

### 14.7 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：原独立 reviewer 复验（任务书要求）；PASS 后经理申请 Windows 资源
- 终态上限不变：仅工程 `UA-M4-006_WINDOWS_ENGINEERING_CLOSED` 候选，不扩 PAPER/真实 soak/Linux Gate

## 15. AUTHORIZED_REWORK_R2（exact33 / R1-F2 + R1-F3）

> 独立复验 `R1_REVIEW_FAIL` 后，任务书 §10 缩小为 R1-F2 / R1-F3。本会话仍为 §13 同一授权采用者；无 subagent/委派；taskbook/review 只读；未改已闭合 v10 row identity / legacy bytes / F4 锁内顺序。§12–§14 全文永久保留。

### 15.1 R1-F2 — true zero-command identity / Gate / 测例统一

