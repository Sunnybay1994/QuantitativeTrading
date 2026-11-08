# M4-B1B2 Terminal Session Closure 独立初验报告

状态：`REVIEW_FAIL`（历史保留）+ `R1_REVIEW_FAIL`（历史保留）+ `R2_REVIEW_PASS`（历史保留）+ `ADOPTION_R2_REVIEW_PASS`（历史保留）+ `VALIDATION1_REWORK_REVIEW_PASS`（历史保留）+ `RUFF_REWORK_REVIEW_PASS`（历史保留）+ `TYPE_ANNOTATION_REVIEW_PASS`（历史保留）+ `EVIDENCE_REVIEW_PASS / STATIC_ONLY`<br>
task id：`M4-B1B2-TERMINAL-SESSION-CLOSURE`<br>
exact base / HEAD：`d525770ac9deb78e414098308b34acbd0773c099`<br>
branch / worktree：`codex/m4-b1b2-terminal-session-closure` @ 任务书指定路径<br>
审查角色：原独立初验者 · §15 组合证据 `EVIDENCE_REVIEW`（未参与实现 / 未创建 subagent / 未委派）<br>
方法：`STATIC_ONLY` — 零 Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / scripts / stage / commit<br>
唯一写路径：本报告（31）；production / tests / taskbook / delivery **只读**<br>
终态核对：承认 delivery 本包上限 `B1B2_WINDOWS_ENGINEERING_VALIDATED`；`SUBSTRATE+B1B1+B1B2 / UA-M4-006` **仍 OPEN**；**无** PAPER/soak/Linux 过度声明

任务书：`docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md`（§15；§12–§14 历史保留）<br>
交付：`docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`（§20；§12/§15.4/§16–§19 永久保留）<br>
VALIDATION1：`...\m4-b1b2-validation1-20260826T062412Z`<br>
VALIDATION2：`...\m4-b1b2-validation2-20260826T064500Z`<br>
VALIDATION3：`...\m4-b1b2-postfix-validation3-20260826T071119Z`<br>
VALIDATION4：`...\m4-b1b2-postfix-validation4-20260826T072258Z`<br>
scope-close5：`...\m4-b1b2-validation4-scope-close5-20260826T000341Z`

---

## 0. 裁决

**`REVIEW_FAIL`**

实现者已建立 formal closure → 6 步 terminal 序列骨架、successor bind 门闩（§13 修正）、INFRA-007 表面消除与两库非原子诚实表述；但至少四项冻结合同缺口在静态上成立，且交付 §7 自行点名的审查焦点未被合同化闭合。实现者未使用的对抗反例见 §3。本审查**不改实现**。

---

## 1. 范围与只读证据

| 项 | 静态结论 |
|---|---|
| AGENTS.md / `.ai/README.md` / review_checklist | 已读；本审查服从 STATIC_ONLY、职责分离、不自宣 Gate |
| exact31 dirty | production8 + tests4 + delivery + 经理任务书 untracked；**无**本报告外写集；`git diff --check` PASS |
| §12 `STATIC_ONLY_BREACH` | 交付保留取证；**不**构成产品验证，亦不洗白 |
| §13 授权采用 | 承认为唯一实现责任重写/修正；successor bind 修正见 F0；其余 FAIL 不因采用而免除 |
| 未改白名单 production（`service.py` 等 5） | 与交付声明一致（复用既有 API） |

---

## 2. 逐项静态核验矩阵

| # | 合同项 | 结论 | 关键证据（文件:行） |
|---|---|---|---|
| A | 唯一 formal closure 驱动 broker finality→OMS recovery/reconcile→report/soak→successor→CLOSED | **部分满足** | `soak_runtime.py` L244–395 顺序齐全；入口强制 `closure=`（L124–142, L187–188） |
| B | same-token partial CLOSING 恢复 | **部分满足** | mid-failure 后 broker marker 保留 + 同 closure 重试（`test_paper_soak_runtime.py` L391–438）；step identity 仅进程内重算、无独立 durable step 行 |
| C | 跨两库非原子事实诚实表达 | **满足** | `compute_terminal_step_identity` 文档 L1275；`transition_closing_to_closed_with_closure` L1424–1426；交付 §4/§7 |
| D | CLOSING 普通 writer 拒绝 | **满足（静态）** | `store.transaction` 仍走 `hold_open_write_lease`（`store.py` L3343–3415）；terminal 另闸 `transaction_under_terminal_child`（L3237+） |
| E | CLOSED replay | **FAIL → F1** | `_replay_closed` L414–458：`terminal_successor_identity=None`；仅 token/state；测试断言 None（`test_paper_soak_runtime.py` L316） |
| F | INFRA-007：无 underscore sibling import / 无私有 composition 字段 / 无第二锁 | **满足（静态）** | `soak_runtime` import 公开 API（L27–69）；源码断言测例 L442–456；无 `_hold_session_lock`；序列化注释 L129–131 |
| G | adoption：successor bind 不可绕过 | **满足（静态）** | `bind_terminal_successor_identity` L1325–1361；CLOSED 要求 `bound`（L1450–1453）；无 bind → `BARRIER_TERMINAL_SUCCESSOR_REQUIRED`（`test_session_barrier.py` L1875–1886） |
| H | zero-command / ORDER closure SSOT | **FAIL → F2** | `_session_closure_identity` fallback L541–570 自造 `soak-runtime-zero-order-closure-v1` |
| I | `transaction_under_terminal_child` 步进域 | **FAIL → F3** | OMS 写闸在 `broker_finality` child 下开启（`soak_runtime.py` L244–249） |
| J | partial orphan / TOCTOU | **FAIL → F4** | soak evidence/`existing` 在持 barrier 锁**之前**冻结（L173–178 vs L188） |

---

## 3. 实现者未使用的对抗性反例（本审查新增）

### AE-1 — CLOSED replay + `successor=None` 无法拒绝链篡改

- **最小复现（静态）**：会话已 `CLOSED` 且 soak receipt 仍在；调用方持合法 live closure 进入 `close_formal_paper_soak_session` → `hold_terminal_closure` 抛 `BARRIER_STATE_CLOSED` → `_replay_closed`。即使 broker finality / recovery 摘要与 receipt 所绑定的历史链已漂移，只要 `close_token_identity` 字符串相等，仍返回成功且 `terminal_successor_identity is None`。
- **对照**：实现者测例 `test_zero_command_session_closes_end_to_end...` **正向断言** `replayed.terminal_successor_identity is None`（L316），把合同缺口测成“期望行为”。
- **任务书**：§4.1「只允许 fresh read/verify exact terminal successor」；§5.10「exact terminal successor tamper 及 CLOSED row 不匹配拒绝」。

### AE-2 — zero-command fallback 可写入与 soak 包不同域的 durable 身份

- **最小复现（静态）**：零 OMS command 会话 → `session_order_semantic_closure_identity` 抛 `SOAK_SESSION_ORDER_RECEIPT_MISSING` → `soak_runtime` 吞掉并写入 `kind=soak-runtime-zero-order-closure-v1` digest → `record_zero_broker_command_session_finality(... order_semantic_closure_identity=...)` 持久化（`paper_formal_broker_snapshot.py` L199–203）。
- **对抗**：若日后 `soak` 包补齐零 command 的 package-owned 身份算法，与 runtime 私有域不一致 → 既有 marker 拒绝或静默分叉；实现者测例只覆盖“能 CLOSED”，未覆盖“身份必须来自 soak SSOT”。
- **任务书**：§4.3 soak 提供 ORDER closure identity；§4.4 / §5.9 zero-command 不漂移。

### AE-3 — 预锁 soak 快照 TOCTOU / partial-step orphan

- **最小复现（静态）**：`before`/`existing` 于 L173–178 读取；L188 才 `hold_terminal_closure`。在两读之间（或 step1–3 期间）由**不持本 barrier 锁**的路径写入/替换同 `session_date` 的 soak receipt / bytes：
  - `existing is None` 过时 → step4 `append_soak_session` 与已存在 receipt 冲突或双写风险；
  - `existing` 过时非空 → step4 直接信任陈旧 `before`/`existing`（L334–336），**不再** under-lock `verify_soak_evidence`。
- **实现者覆盖**：仅有 mid-reconcile failure resume（锁内失败），**无**锁外 evidence 竞态 / orphan receipt 对抗。

### AE-4 — `transaction_under_terminal_child` + 错误 step_kind 域

- **最小复现（静态）**：在 live `broker_finality` child 内调用 `store.transaction_under_terminal_child(step_kind="broker_finality")` 得到完整 `ExecutionRepository` 并 `COMMIT`（`store.py` L3237–3314；`soak_runtime.py` L244–249）。合同要求该 child 只授权**当前步骤**写集；此处用 broker 步闸打开 OMS 通用写事务（即便当前只 `recover_repository_state` 只读，API 面仍可写）。
- **实现者**：交付 §7.1 仅备注“需审查”，无限制 step_kind∈{oms_recovery,…} 的负向测试。

### AE-5 — `object.__new__` / 反射（补充）

- context/child forge 已有测例（`test_session_barrier.py` L1558–1638）→ **不作为 FAIL**。
- 额外缺口：`_replay_closed` 对 `closed_row` 使用 `getattr(..., None)`（L439–443），弱于 barrier 行类型闸；在 AE-1 未修前放大“假 CLOSED 成功态”风险。实现者未测 duck-typed row。

---

## 4. FAIL 条目（现象 — 根因 — 规则 — 最小复现 — 测试 — 通过条件）

### F1 — CLOSED fresh replay 不验证 exact terminal successor（P0）

| 字段 | 内容 |
|---|---|
| 现象 | `_replay_closed` 固定返回 `terminal_successor_identity=None`；CLOSED 行不持久化 successor；replay 只比对 `state`/`close_token_identity` |
| 根因 | successor bind 仅为 process-local（`_TerminalChildBinding.bound_successor_identity`）；无 migration/CLOSED 读闸下无法从两库重算并对照；交付选择“返回 None”而非 STOP |
| 规则 | 任务书 §4.1、§4.2（successor 绑定全链）、§5.10；STOP：无法以现有 durable 事实完成合同能力时应申请新包/migration，不得削弱 CLOSED verify |
| 证据 | `soak_runtime.py` L414–458；`session_barrier.py` L1477–1490（CLOSED 更新不含 successor）；交付 §7.3；`test_paper_soak_runtime.py` L302–316 |
| 最小复现 | AE-1 |
| 新增测试要求 | CLOSED 后篡改/替换与 successor 链相关的 durable 事实（或注入不匹配的 persisted successor）必须 fail-closed；合法 replay 必须返回**可验证**的 exact successor（或等价 durable 对照），禁止 `None` 成功态 |
| 通过条件 | replay 路径静态+测例证明：verify exact successor；或任务书经经理修订并明确降级（本审查不接受实现者单方降级） |

### F2 — zero-command ORDER closure 身份落在 soak_runtime 私有域（P1）

| 字段 | 内容 |
|---|---|
| 现象 | 公开 `session_order_semantic_closure_identity` 对零 command fail-closed；runtime 另造 `soak-runtime-zero-order-closure-v1` 并写入 broker finality |
| 根因 | 未把零 command 身份收口到 soak package-owned API，却继续推进 terminal CLOSED |
| 规则 | 任务书 §4.3、§4.4、§5.9；INFRA-007 精神：runtime 消费窄公开面，不平行发明 durable 身份 SSOT |
| 证据 | `soak_runtime.py` L541–570；`soak.py` L680–708；`paper_formal_broker_snapshot.py` L195–235 |
| 最小复现 | AE-2 |
| 新增测试要求 | 零 command 身份必须等于 soak 公开函数结果；禁止 runtime 私有 `kind` 域；篡改 fallback 域拒绝 finality resume |
| 通过条件 | 身份算法仅存在于 soak（或经理改写合同）；runtime 无平行 digest |

### F3 — `transaction_under_terminal_child` 步进域过宽（P1）

| 字段 | 内容 |
|---|---|
| 现象 | 任意 live terminal child（含 `broker_finality`）可打开 OMS `BEGIN IMMEDIATE`+可写 `ExecutionRepository` |
| 根因 | 为 CLOSING 下 OMS 一致读引入通用写闸，未按 step_kind 收窄允许集 |
| 规则 | 任务书 §4.1「只有冻结序列中的唯一 terminal child operation 可写其当前步骤」；交付 §7.1 自承需挑战 |
| 证据 | `store.py` L3237–3314；`soak_runtime.py` L244–249、L278–283 |
| 最小复现 | AE-4 |
| 新增测试要求 | `broker_finality`/`report_soak`/… child 调用 OMS `transaction_under_terminal_child` 应拒绝（除非合同显式允许的只读闸且不可 `COMMIT` 写路径）；仅 `oms_recovery`（或明文白名单）可通过 |
| 通过条件 | API/测例证明 step 写集分域；或单独只读 OMS peek 且无通用 repo 暴露 |

### F4 — soak evidence 预锁快照 TOCTOU / partial orphan（P1）

| 字段 | 内容 |
|---|---|
| 现象 | `existing`/`before` 在锚定锁外确定；step4 在 `existing is not None` 时不重验 evidence |
| 根因 | 两库非原子下把 process 外 evidence 快照当成锁内真相 |
| 规则 | 任务书 §4.2 orphan/错序/tamper fail-closed；§5.5；审查指令要求挑战 partial-step orphan 与 TOCTOU |
| 证据 | `soak_runtime.py` L173–178、L188、L333–336 |
| 最小复现 | AE-3 |
| 新增测试要求 | 锁外插入/替换/篡改 receipt 后进入 terminal 序列必须 fail-closed 或 under-lock 重验后正确 resume；禁止使用过期 `before` |
| 通过条件 | step4（及 CLOSED replay）在 barrier 锁内 fresh verify evidence/receipt bytes 与 identity |

---

## 5. 非 FAIL 的正面观察（不抵消 F1–F4）

1. **Successor bind 采用修正有效（静态）**：未 bind 不能 CLOSED；mismatch 拒绝；§13 相对“丢弃 successor”草案有实质加固。
2. **INFRA-007 表面**：`soak_runtime` 无 sibling underscore import、无 `._execution_store` / `._ledger_provider` 源码穿透、无第二 session lock 符号。
3. **formal vs raw**：`transition_closing_to_closed` 对 `FORMAL_CLOSURE_ONLY` → `BARRIER_CLOSURE_REQUIRED`（`session_barrier.py` L1376–1378）；substrate raw 正向路径保留意图清晰。
4. **child 伪造/嵌套/跨线程**：测例覆盖 `__new__`/copy/pickle/replace/second child/owner mismatch。
5. **§12/§13**：违约取证保留；本审查不把历史 `ast.parse` 记为绿证。

---

## 6. 未运行边界（诚实）

本初验会话：**零** Python 解释器、`ast.parse`、pytest、Ruff、mypy、cold import、SQLite probe、PAPER、真实 soak、网络、browser、stage、commit。所有结论仅来自只读文本/diff 静态核验。

---

## 7. 返工最小集（给经理；审查者不改代码）

1. 闭合 F1：CLOSED 后 exact successor 可验证（durable 对照或合同修订+STOP 记录）——**阻断 Windows 主验准入**。
2. 闭合 F2：零 command ORDER 身份收回 soak 公开面。
3. 闭合 F3：OMS terminal 事务按 step 分域或改为不可写 peek。
4. 闭合 F4：锁内 fresh verify soak evidence；补 AE-3 测例。
5. 保持 STATIC_ONLY 直至经理解冻；返工后须**另一未参与该轮实现的**外部初验复验。

---

## 8. 交接（初验历史；保留）

- 裁决：`REVIEW_FAIL`
- 下一步：经理形成返工任务书 → 外部实现 → 原独立 reviewer 复验；**不得**申请 Windows 验证资源
- 本审查者退出；唯一产物为本报告路径

---

## 9. R1 复验（2026-08-26）

### 9.0 范围与方法

- 只读：任务书 §9（exact33）、delivery §14、production16+tests 相关 diff、v010 migration。
- **保留**上文 §0–§8 原 `REVIEW_FAIL` 正文不删改。
- 本复验会话：零 Python / SQLite / pytest / Ruff / mypy / cold / network / commit；无 subagent/委派。
- dirty ⊂ exact33（含经理任务书 + 本报告）；`git diff --check` PASS（复验时核对）。

### 9.1 裁决

**`R1_REVIEW_FAIL`**

F1 / F4 合同行为在静态上已基本闭合；F2 将 zero-command 改为 soak 成功身份后，与既有 formal empty gate 测例/语义未对齐；F3 可写 `transaction_under_terminal_child` 已收窄到 `oms_recovery`，但只读 inspect 仍暴露可 `commit` 升级的通用 `ExecutionRepository`。不改实现。

### 9.2 F1–F4 复核矩阵

| 项 | 结论 | 关键证据 |
|---|---|---|
| F1 v10 nullable 列 | **满足** | `v010_terminal_successor.py` L11–18；`store.py` `CURRENT_SCHEMA_VERSION=10` L56；`migrations/__init__.py` L20–35 |
| F1 legacy NULL / substrate row identity 无新键 | **满足** | `_row_identity_for` L2364–2388：仅 FORMAL+非空 successor 追加键；substrate 非空 successor 拒绝 L2387–2388；`transition_closing_to_closed` 写 `None` L1401–1408 |
| F1 formal CLOSED 同事务持久 hex64 + row identity 绑定 | **满足** | `transition_closing_to_closed_with_closure` L1485–1500；idempotent 要求列匹配 L1469–1474 |
| F1 CLOSED replay 全链重算非 None | **满足** | `_replay_closed` L442–562：`persisted_successor` 必须 hex64；重算 step1–4+successor；`recomputed != persisted` fail；返回非 None |
| F1 v3/v7/v9/非法值测例 | **部分** | `test_v010_...` L2030–2099 跑通 upgrade 链+非法 `g*64`；**未**插入既有 v9 barrier 行断言 row_identity bytes 不变；**未**显式 formal CLOSED NULL→replay fail 测例（行为由 L452–453 静态保证） |
| F2 soak 唯一 SSOT / 无私有 fallback | **算法满足 / 闸测冲突 → R1-F2** | `soak.py` L713–730 `SoakSessionOrderSemanticClosureZero`；`soak_runtime` 无私有域（源码断言 L334–335）；但见 R1-F2 |
| F2 无孤儿 ORDER | **代码有 / 测例缺** | orphan：`soak.py` L714–721；无独立孤儿测例 |
| F3 可写 OMS 仅 `oms_recovery` | **transaction 满足 / inspect → R1-F3** | `store.py` L3250–3251 拒绝非 `oms_recovery`；测例 L350–371 |
| F4 锁内 fresh before/existing + append 前后复验 | **满足** | `soak_runtime.py` L176–182 锁内首读；L331–373 step4 复验+append 后复验；CLOSED replay L455–529 在 `inspect_oms_when_closed` 锁内重读 |

### 9.3 R1 新增对抗反例（实现者未用）

#### AE-R1-1 — legacy / 升级后 formal CLOSED 列 NULL

- 最小复现：v9 formal CLOSED 行（无 successor 列）→ v010 ALTER 后列 NULL 且 formal row_identity（仅 `terminal_policy_domain`）仍自洽 → `_parse_barrier_row` 接受（L2568–2579）→ `_replay_closed` 因 `persisted_successor` 非 hex64 于 L452–453 fail-closed。
- 实现者有 substrate NULL 与非法值测例，**无**“formal CLOSED NULL → replay 拒绝”专用测例；行为静态正确，记残留。

#### AE-R1-2 — row identity domain 混合

- 最小复现：substrate CLOSED `row_identity`（无 policy domain）+ 非空 `terminal_successor_identity` → L2586–2589 `BARRIER_TERMINAL_SUCCESSOR_INVALID`；formal CLOSED 列 successor 与 digest 内嵌值不一致 → `BARRIER_ROW_CORRUPT`。静态闭合。

#### AE-R1-3 — 锁内 receipt 替换（F4）

- 最小复现：持 barrier 锁后 steps1–3 期间替换 soak FS receipt → step4 `locked_before != before`（L337–338）或 append 后 receipt 不等（L372–373）fail-closed；CLOSED replay 双读 evidence（L455 vs L520–529）。静态闭合。实现者仅源码顺序断言，缺行为测例 → 残留。

#### AE-R1-4 — wrong-step 只读闸升级为写（F3）→ **FAIL**

- 最小复现：live `broker_finality` child 下 `inspect_repository_under_terminal_child`（L3318–3363）yield 完整 `ExecutionRepository`（含 `_conn` 与写路径）；调用方 `repo._conn.execute(...); repo._conn.commit()` 可在 `finally: _safe_rollback`（L3362–3363）之前使写持久化，ROLLBACK 无法撤销已 COMMIT。
- 任务书 §9 F3：「不暴露 commit 能力的最窄接口」。交付 §14.3 仅称“强制 ROLLBACK”，未覆盖该升级。

#### AE-R1-5 — F2 成功身份 vs formal empty MISSING 闸（→ **FAIL**）

- 最小复现：空 OMS recovery（`_facts` 打开空库）走 `_session_issue_codes` → 调用 `_session_order_semantic_closure_identity`（`soak.py` L982–984）→ 现 zero 路径返回成功身份（L713–730），**不再**抛 `SOAK_SESSION_ORDER_RECEIPT_MISSING`（该字符串在 identity 函数内已无 raise 点，仅残留于 L989 识别表）。
- 对抗：`test_formal_empty_session_is_durably_blocked_without_order_receipt`（`test_execution_soak.py` L583–611）仍断言 `issue_codes == (SOAK_SESSION_ORDER_RECEIPT_MISSING,)` 且 `BLOCKED`。与 F2 成功零身份静态互斥；R1 只改了 L901–928 旧 MISSING 期望，未调和该 formal empty 闸测例/产品语义。

### 9.4 FAIL 条目（六要素）

#### R1-F2 — zero-command SSOT 与 formal empty MISSING 闸/测例未闭合（P0）

| 字段 | 内容 |
|---|---|
| 现象 | identity 对真零 command 改为成功 `SoakSessionOrderSemanticClosureZero`；`SOAK_SESSION_ORDER_RECEIPT_MISSING` 从 identity 不可达；formal empty 测例仍要求 MISSING+BLOCKED |
| 根因 | F2 收回 SSOT 时未同步 soak gate issue_codes 合同与冲突测例 |
| 规则 | 任务书 §9 F2（唯一 soak SSOT + 测例锁定）；§5.9 不漂移；既有 formal empty 阻塞语义须显式迁移或保留 |
| 最小复现 | AE-R1-5；对照 `soak.py` L713–730 vs `test_execution_soak.py` L608–611 |
| 新增测试要求 | （a）正式定义空会话 gate：若允许零身份通过 ORDER 检查，更新/替换 L583 测例并证明 BLOCKED 另由何码保证；若仍要阻塞，须在 gate 层对 Zero 身份另立稳定码且测例锁定；（b）补孤儿 ORDER → `SOAK_SESSION_ORDER_RECEIPT_INVALID` 行为测例 |
| 通过条件 | identity / gate / 测例三者无静态矛盾；MISSING 要么仍有可达语义要么从断言与死表清除 |

#### R1-F3 — inspect 只读闸可升级为持久写（P1）

| 字段 | 内容 |
|---|---|
| 现象 | 非 `oms_recovery` 步骤通过 inspect 获得与写事务同型的 `ExecutionRepository`；`_conn.commit()` 可绕过强制 ROLLBACK |
| 根因 | 以“finally ROLLBACK”代替“不暴露 commit/写 API” |
| 规则 | 任务书 §9 F3；初验 AE-4 的升级形态 |
| 最小复现 | AE-R1-4；`store.py` L3318–3363；`ExecutionRepository.__init__` L1078–1079 |
| 新增测试要求 | wrong-step inspect 下对 `_conn.commit()` 或写路径后断言库无持久副作用（或 API 根本不暴露 conn/写方法）；合法 `oms_recovery` transaction 仍可 COMMIT |
| 通过条件 | 非 `oms_recovery` 不可能获得可 commit 的 OMS 写面（只读视图/禁止 commit 的包装/不 yield Repository） |

### 9.5 已闭合的原 F1/F4（不抵消 R1-F2/F3）

- 原 F1：v10 列 + formal 持久 successor + replay 全链非 None — **静态闭合**。
- 原 F4：`before`/`existing` 移入 `hold_terminal_closure` 内，step4/CLOSED replay 复验 — **静态闭合**。
- 原 F3 的 `transaction_under_terminal_child` 任意 step — **已修**；残余为 inspect 升级（R1-F3）。
- 原 F2 runtime 私有 digest — **已删**；残余为 gate/测例矛盾（R1-F2）。

### 9.6 未运行边界

本 R1 复验：**零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / PAPER / soak / network / browser / stage / commit。

### 9.7 返工最小集（审查者不改代码）

1. 闭合 R1-F2：调和 Zero 身份与 formal empty gate/测例；补孤儿 ORDER 测例。
2. 闭合 R1-F3：非 `oms_recovery` 不得暴露可 commit 的 OMS repository。
3. 建议补强（非本轮唯一阻断）：v9 既有行升级后 row_identity bytes 断言；formal CLOSED NULL replay 负向测例；锁内 FS 替换行为测例。
4. 返工后仍由**未参与该轮实现**的独立初验复验；在此之前**不得**申请 Windows 验证资源。

### 9.8 交接（R1 历史；保留）

- 裁决：`R1_REVIEW_FAIL`
- 历史 `REVIEW_FAIL`（§0–§8）保留
- 下一步：经理/中央形成 R2 返工 → 同一或新授权实现者 → 独立复验

---

## 10. R2 复验（2026-08-26）

### 10.0 范围与方法

- 只读：任务书 §10；delivery §15；`soak.py` / `paper_formal_service.py` / `soak_runtime.py` 与对应 tests。
- **完整保留**上文 §0–§8 原 `REVIEW_FAIL` 与 §9 `R1_REVIEW_FAIL` 正文，不删改、不洗白。
- 本复验会话：零 Python / SQLite / pytest / Ruff / mypy / cold / network / scripts / Git stage/commit；无 subagent/委派。
- 复核范围仅 R1-F2 + R1-F3；已闭合 F1/F4/v10 未要求重开（交付声明未改 row identity / F4 锁序；本审查抽检 `soak_runtime` 锁内 `before` 仍在 `hold_terminal_closure` 内）。

### 10.1 裁决

**`R2_REVIEW_PASS`**

R1-F2（Zero / MISSING / INVALID / Gate·测例对齐）与 R1-F3（closure view 不向 caller 暴露可 commit OMS 面；`soak_runtime` 仅消费 RecoveryResult / barrier 事实）在静态上满足任务书 §10。本裁决**不**构成产品验证绿，**不**授权 Windows 主验；见 §10.5 诚实边界。

### 10.2 R1-F2 复核（行号证据）

| 合同点 | 结论 | 证据 |
|---|---|---|
| 真零 + 无孤儿 → `SoakSessionOrderSemanticClosureZero` 成功 | **满足** | `soak.py` L713–730；测例 `test_formal_empty_session_order_closure_uses_canonical_zero` L583–616：无 MISSING/INVALID，无 `SOAK_SESSION_BLOCKED`，`WAITING_FOR_SOAK_EVIDENCE` |
| 旧“空会话必 MISSING+BLOCKED”已 supersede | **满足** | 任务书 §10 L201–202；旧名测例已替换为上表 |
| 有本 session command、ORDER 覆盖不全 → `MISSING` 仍可达 | **满足** | `soak.py` L754–756 显式 `SoakError("SOAK_SESSION_ORDER_RECEIPT_MISSING")`；`test_nonzero_session_commands_without_order_receipts_are_missing` L665–681 |
| 孤儿 ORDER / 错身份 → `INVALID` | **满足** | 孤儿：`soak.py` L714–721；`test_orphan_order_receipt_for_session_without_commands_is_invalid` L619–662；其它异常 → L767–768 `INVALID` |
| 非零历史 identity 类型名/字段 | **满足（静态）** | 非零仍 `_identity("SoakSessionOrderSemanticClosure", {command_ids, receipt_ids, session_date})` L757–763；未改为 Zero 域 |
| Gate issue 双码映射 | **满足** | `_session_issues` / 等价路径仍识别 MISSING+INVALID（`soak.py` L987–992） |
| `soak_runtime` 无私有 zero digest | **满足** | 源码断言 `test_infra_007_and_f2_f3_source_contracts` L335–336；直接调用公开 `session_order_semantic_closure_identity` |

### 10.3 R1-F3 复核（行号证据）

| 合同点 | 结论 | 证据 |
|---|---|---|
| view 删除 raw `open_oms_store` / `inspect_oms_*` | **满足** | `paper_formal_service.py` 无匹配符号；测例 L391–393 `not hasattr` |
| 窄方法只返回 immutable recovery（+ CLOSED row） | **满足** | `recover_oms_under_terminal_child` → `RecoveryResult` L141–159；`recover_oms_when_barrier_closed` yield `(RecoveryResult, SessionBarrierRow)` L161–177；二者均为 `frozen=True` dataclass |
| `oms_recovery` 提交型 TX 仅模块内 | **满足** | L151–155 `transaction_under_terminal_child` 在 view 方法内；只 `return recover_repository_state(repo)` |
| 其它 step 仅内部 rollback inspect | **满足** | L156–159 `inspect_repository_under_terminal_child` |
| `soak_runtime` 不直接碰 store/repo/recover_repository | **满足** | 使用 `view.recover_oms_under_terminal_child` / `recover_oms_when_barrier_closed`（L242–244、L275–277、L438）；源码断言无 `open_oms_store`/`inspect_oms_*`/`transaction_under_terminal_child`/`recover_repository_state`（L329、L344–347） |
| wrong-step 返回对象无 `_conn`/commit/write | **满足（静态+测例意图）** | `test_closure_view_wrong_step_recovery_is_immutable_and_non_writable` L397–408；`RecoveryResult` 无 `_conn`/`commit`/`execute` |

### 10.4 R2 新增对抗性反例（实现者未用）

#### AE-R2-1 — 私有 `_composition` 逃逸 vs 公开返回面

- **最小复现（静态）**：敌对调用方可 `view._composition` → `._execution_store.store` 取得 raw `ExecutionStore`（字段仍在 view 上，L132–134）。这与 R1 AE-R1-4「方法返回 repo」不同：公开方法不再 yield 可写面；逃逸依赖私有字段。
- **对照**：任务书 §10 要求 caller 不能经 view 公开操作升级为写；`soak_runtime` 源码禁止 `._execution_store`（L330）。本对抗**不**作为 FAIL：公开 API / runtime 调用链已收窄；记残留风险——完整杜绝需 attestation 隐藏 composition 或 `object.__getattribute__` 闸（超出本轮最小面时可另开债）。
- **通过观察**：wrong-step 返回的 `RecoveryResult` 即使 `object.__new__(ExecutionRepository)` 也无法附着 live `_conn`（测例 L404–405）。

#### AE-R2-2 — 非零缺 ORDER 与真零的码面分离

- **最小复现**：本 session 有 command 但 `risk_receipts` 清空 → L754–756 `MISSING`（测例 L665–681）；真零无 command 无孤儿 → L722–730 Zero 成功且 gate 不写 MISSING（L583–616）。二者静态不可混淆。实现者有分测例；本反例强调 gate 语义分域已对齐 §10，作为 PASS 强化而非缺口。

### 10.5 诚实 STATIC_ONLY / Gate 边界

