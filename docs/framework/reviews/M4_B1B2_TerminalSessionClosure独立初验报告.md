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

| 边界 | 陈述 |
|---|---|
| 本 R2 审查会话 | **零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / PAPER / soak / network / browser / stage / commit |
| 交付 §15.4 自披露 | 实现者承认 R2 过程中曾误跑本机 `python -c ast.parse(...)` 语法自检，**违反**零 Python 禁令；**不构成**产品/Gate 验证，亦**不得**洗白 §12 历史违约 |
| 本审查对 §15.4 的处置 | 记入边界；**不**因该探针单独改写 R1-F2/F3 产品静态结论；**不**宣布探针已由中央核可。经理申请 Windows 资源前须按 §12 同类规则由中央/经理处置该过程违约 |
| Gate / 终态 | `R2_REVIEW_PASS` 仅是 Windows 工程主验**产品合同**准入候选；仍禁止宣称 `B1B2_WINDOWS_ENGINEERING_VALIDATED`、真实 PAPER/soak、28 日、fault-drill、Linux Gate、UA-M4-006 关闭或 M4 完成，直至中央允许的 Windows 验证实际通过 |
| 未运行产品验证 | pytest / Ruff / mypy / cold / SQLite probe / focused 回归：**全部未跑** |

### 10.6 残留风险（不阻断本轮产品 PASS）

1. view 上 `_composition` 私有逃逸面仍在（AE-R2-1）。
2. `view.broker_store.store` 仍为 broker 包既有 raw store 端口（OMS 面已收窄；非 §10 点名对象）。
3. F1 测例补强建议（v9 既有行 bytes、formal CLOSED NULL replay）仍为残留，非 R2 范围。

### 10.7 交接（R2 历史；保留）

- 裁决：`R2_REVIEW_PASS`
- 历史：`REVIEW_FAIL`（§0–§8）+ `R1_REVIEW_FAIL`（§9）全文保留
- 下一步：经理向中央申请 Windows 验证资源前处理 §15.4 过程违约；通过后仅可宣称工程 `UA-M4-006_WINDOWS_ENGINEERING_CLOSED` 候选上限
- 本审查者退出；唯一本轮写产物为本报告路径

---

## 11. ADOPTION_R2 复验（2026-08-26）

### 11.0 范围与方法

- 只读：任务书 §11；delivery §16；exact33 production/tests 当前字节；§12 / §15.4 保留性。
- **完整保留** §0–§8 `REVIEW_FAIL`、§9 `R1_REVIEW_FAIL`、§10 `R2_REVIEW_PASS`，不删改。
- 本会话：零 Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / scripts / subagent / stage / commit。
- 核对手段：只读 `git hash-object` / `status` / `diff --cached` / `diff --check` + 文本对照；**不构成**产品验证。

### 11.1 裁决

**`ADOPTION_R2_REVIEW_PASS`**

全新 §16 adopter 对 production/tests **逐字采用、adoption delta=0**；本审查独立重算的 WT SHA-1 与 delivery §16.2 表**逐行一致**；相对 `R2_REVIEW_PASS` 产品面无字节漂移；§12 与 §15.4 仍在且声明为无效证据；actual ⊆ exact33、cached=0、`git diff --check` PASS、无新增执行痕迹。

### 11.2 采用者身份 / 角色（ provenance）

| 项 | 结论 |
|---|---|
| delivery 自称角色 | 全新外部 `AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2`；Cursor Grok 4.5；与 §13/§14/§15 实现会话**无关** |
| subagent/委派 | 自报 **无** |
| 可写路径 | 自报仅 delivery(30)；本审查见 production/tests SHA 未因 §16 改变 → 与声明一致 |
| 审查可核部分 | 身份/会话隔离为 **delivery 自证**（审查者无法密码学证明会话 UUID）；产品闭包以 **SHA/delta/scope** 为准 |

### 11.3 最终 SHA 表（审查者独立 `git hash-object`；与 §16.2 对照）

HEAD=`d525770ac9deb78e414098308b34acbd0773c099`。下列 **30** 个 exact33 production+tests 路径：

| 路径 | 审查者 WT SHA-1 | vs HEAD | vs §16.2 |
|---|---|---|---|
| `session_barrier.py` | `2920a4188bfdd1841cd43f61d78972190a3cffeb` | DIRTY | **一致** |
| `store.py` | `f8815295003701cffc2e6bce161ef3543f9c8a05` | DIRTY | **一致** |
| `paper_broker_store.py` | `660303eb2545247fe05b96a1d548968960930a8a` | DIRTY | **一致** |
| `service.py` | `1d8c21f704d63ecd425df597acf4189a114f4dbf` | CLEAN | **一致** |
| `gateways/paper_durable.py` | `b5be54e8b322067620a40d304fb3b017a1fcb061` | CLEAN | **一致** |
| `paper_formal_execution_store.py` | `048c5b061c55109e4e481e005d5550fd7e084113` | DIRTY | **一致** |
| `paper_formal_broker_store.py` | `305a335185bdabe9343dfc3d5d77a4710b41c387` | CLEAN | **一致** |
| `paper_formal_gateway.py` | `d8a0cefd62156c790ccbb0f4e9fc86670bbe3d34` | CLEAN | **一致** |
| `paper_formal_service.py` | `72e95fa39aac52d95d51884bce956191295d9243` | DIRTY | **一致** |
| `paper_formal_daily.py` | `c625336b71f89d0eddced7b248bd17a1cae03743` | CLEAN | **一致** |
| `paper_formal_broker_snapshot.py` | `97171cc4729b6a2e486f76224fa988ea49a12b39` | DIRTY | **一致** |
| `soak.py` | `1a6ad2a09124676e299c22c51ccb96a7ff98e935` | DIRTY | **一致** |
| `soak_runtime.py` | `892c652263d0f729a31e3452cd85499c880a6a08` | DIRTY | **一致** |
| `reconcile.py` | `b6d5d4fba86062e59b8d1f71a596467dc00079ba` | CLEAN | **一致** |
| `migrations/__init__.py` | `509c8d9dfdef2567a78db517ac35adbea0ccedfc` | DIRTY | **一致** |
| `migrations/v010_terminal_successor.py` | `a3eaf938341b4e82bec38591fe2ae3a4c0bcd314` | NEW | **一致** |
| `test_session_barrier.py` | `4f0b0da1cff89396eea8a0c293b19fce1358d881` | DIRTY | **一致** |
| `test_execution_store.py` | `c548db3e6872f7363c1f5cd8462448e67de8ad11` | CLEAN | **一致** |
| `test_paper_broker_store.py` | `1c1d6eb0d89e104b20783cab2742df6783f75704` | CLEAN | **一致** |
| `test_execution_service.py` | `1a7ce167b26fc67795372f39b543db99ce8987ac` | CLEAN | **一致** |
| `test_paper_durable_gateway.py` | `426ede5a43b2410675c4ee62e9bd3ddb9442ed5b` | CLEAN | **一致** |
| `test_paper_formal_execution_store.py` | `ff656bef2408e547f5c78482ab6b9fcd35c2593f` | DIRTY | **一致** |
| `test_paper_formal_broker_store.py` | `e1c5e850a80f8f4db90f620f2467594a3f2f7c45` | CLEAN | **一致** |
| `test_paper_formal_gateway.py` | `ed1f45ef213aae1214a454c15c68c7552eec7735` | CLEAN | **一致** |
| `test_paper_formal_service.py` | `4a3898f72db1bca2fdd19067d296c728e19d21df` | CLEAN | **一致** |
| `test_paper_formal_daily.py` | `8ca9a491499417924c70fee69ead95dc8fd7b478` | CLEAN | **一致** |
| `test_paper_formal_broker_snapshot.py` | `ee4a6e7c5e0fd7c4b5c4b87ba0246b9ab139e405` | NEW | **一致** |
| `test_execution_soak.py` | `bad68a5ae6a00282d3742ba4126ec7854c0a9ea4` | DIRTY | **一致** |
| `test_paper_soak_runtime.py` | `80a9b0ca1355c6be01c7c00d474ee42c55f1843d` | DIRTY | **一致** |
| `test_reconcile.py` | `1621bbf3f09928d8b11204aefbb7ba2f0ea1758c` | CLEAN | **一致** |

| 汇总 | 值 |
|---|---|
| production/tests adoption delta | **0**（adopter 未改业务字节；审查 SHA ≡ §16.2） |
| 相对 `R2_REVIEW_PASS` 产品面 | **不变**（无 production/test 字节漂移 → 无需完整产品复验） |
| 本审查时刻 delivery SHA-1 | `757c4ec0529c8b957ae23728bc84fc779024e9cb`（含 §16 追加；pre-adoption 自报 `22d27729…`） |

### 11.4 违约证据隔离与 provenance 边界

| 项 | 结论 |
|---|---|
| §12 `CONTRACT_DEVIATION_STOP / STATIC_ONLY_BREACH` | **仍在**（delivery L179+）；正文仍裁定子会话 `ast.parse` 为违约；**未覆盖/未洗白** |
| §15.4 本机 `python -c ast.parse` | **仍在**（delivery L473–477）；仍标违反零 Python；§16.4 再隔离为无效证据 |
| §16 对两次违规 | 明确 **无效证据**、不恢复来源闭包、不计入验证（L558–563） |
| §12/§15.4 探针 | **不得**视为产品或 Gate 绿；本 ADOPTION PASS **不**洗白历史违约 |
| 本 ADOPTION 审查会话 | 零 Python；未把任何历史探针计入验证 |

### 11.5 Scope / residue

| 检查 | 结果 |
|---|---|
| actual dirty ⊆ exact33 | **PASS**（13 modified production/tests + 2 new + taskbook/delivery/review docs） |
| `git diff --cached` | **cached0** |
| `git diff --check HEAD` | **PASS**（exit 0） |
| `__pycache__` / `.pyc` / `.pytest_cache` / `.mypy_cache` / `.ruff_cache` | **未发现**（只读扫描） |
| 凭据 / 真实 DB/evidence 新增 | **未发现** |

### 11.6 诚实未运行 / Gate 边界

- 未运行：pytest、Ruff、mypy、cold、SQLite probe、PAPER、真实 soak、网络、browser、stage、commit。
- `ADOPTION_R2_REVIEW_PASS` 恢复的是**采用闭包 + 与 R2 产品面 SHA 一致**，**不是** Windows VALIDATION1 绿。
- 任务书 §11：仅 reviewer PASS 后可重新申请完整 Windows VALIDATION1；B1B2 未验证；`UA-M4-006` 继续 OPEN。
- 终态上限不变：即使后续 Windows 工程通过，亦不得宣称真实 PAPER/soak/28 日/fault-drill/Linux Gate 或 M4 整体完成。

### 11.7 交接（ADOPTION_R2 历史；保留）

- 裁决：`ADOPTION_R2_REVIEW_PASS`
- 历史全文保留：`REVIEW_FAIL` + `R1_REVIEW_FAIL` + `R2_REVIEW_PASS`
- 下一步：经理/中央在保留 §12/§15.4 无效证据前提下，可申请完整 Windows VALIDATION1
- 本审查者退出；本轮唯一写路径仍为本报告

---

## 12. VALIDATION1_REWORK 复验（2026-08-26）

### 12.0 范围与方法

- 只读：任务书 §12；delivery §17；VALIDATION1 evidence root；exact33 当前字节（对照 ADOPTION_R2 production SHA 表）。
- **完整保留** §0–§11 全部历史裁决（`REVIEW_FAIL` / `R1_REVIEW_FAIL` / `R2_REVIEW_PASS` / `ADOPTION_R2_REVIEW_PASS`），不删改。
- 本会话：零 Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / scripts / subagent / stage / commit。
- 核对：evidence 文本 + `git hash-object` + 测试源码静态映射；**不构成** VALIDATION2 或产品绿。

### 12.1 裁决

**`VALIDATION1_REWORK_REVIEW_PASS`**

VALIDATION1 focused 四失败与 delivery §17 根因对齐：两项为 **test-only** fixture（v010 `fresh` 父目录；`schema_version==10`）；两项 terminal 失败由 **fixture formal-clock 漂移** 在 step4 `append_soak_session`→`_require_formal_now` 触发，**production SHA 相对 ADOPTION_R2 面零漂移**。返工将 pin 限制在 test-owned `_production_utc_now`，公开窄 API step trace 仍调用真实实现；same-token / broker exact1 / CLOSING / orphan·tamper 合同面未放宽。

### 12.2 VALIDATION1 证据核对

| 项 | 证据 |
|---|---|
| 证据根 | `...\artifacts\agent_runs\m4-b1b2-validation1-20260826T062412Z` |
| identity | `01-identity` exit=0（`stage-summary.log`） |
| focused | `02-focused` exit=1；stdout_sha256=`29728EC681014FF8C1B1C573A9690AB012FAE0FAFF70108872C96FE15224C845`（与 §17 一致） |
| 四失败 | `test_v010_...`；`test_barrier_enabled_open_write_and_closing_rejects`；`test_zero_command_...`；`test_mid_sequence_...`（stdout short summary L448–451） |
| Ruff/mypy/cold/scope | **UNRUN**（§17.6；本审查确认 evidence 仅 01/02 阶段） |

### 12.3 两项 fixture 修复（test-only）

| 项 | 结论 | 证据 |
|---|---|---|
| v010 fresh 父目录 | **满足** | VALIDATION1：`unable to open database file` at `fresh/oms.sqlite3`（stdout L76–82）。返工：`fresh_root.mkdir(...)` 后 `_oms_conn`（`test_session_barrier.py` L2086–2090）。升级链仍 `INSERT ... version=9` 再 `upgrade_v010`（L2069–2075）；非法 `g*64` 仍拒绝（L2096–2102）。**未**改 SQLite/store/migration API |
| schema_version==10 | **满足** | VALIDATION1：`10 == 9`（stdout L120–123）。返工：`assert store.schema_version() == 10`（`test_execution_store.py` L3477）。同测例仍保留 OPEN `transaction` 可写、CLOSING/CLOSED ordinary 拒绝（L3483–3500） |

### 12.4 两项 terminal 失败 → formal-clock @ step4

| 项 | 结论 | 证据 |
|---|---|---|
| 生产时钟闸 | **存在且未改** | `soak.py` `_FORMAL_CLOCK_TOLERANCE=5min`（L76）；`_require_formal_now` 对照 `_production_utc_now()` 墙钟（L2221–2233）；WINDOWS append 路径 L379–382 调用该闸 |
| zero-command 首次链 | **根因闭合** | VALIDATION1 仅见 sanitize `PAPER_SOAK_SESSION_INVALID`（stdout L268 / `soak_runtime.py` L218）。fixture `now=2026-08-20` vs 验证日 `2026-08-26` ≫5min → step4 必然 `ValueError`。返工 pin `soak_module._production_utc_now`→`formal_clock[0]`（`test_paper_soak_runtime.py` L280–282, L343–344） |
| mid-sequence retry | **根因闭合** | VALIDATION1：首次断言 `CLOSING` + `record_calls==1` **已通过**（stdout L302–305），失败在 retry `close_formal_paper_soak_session`（L309–318）。证明：不回 OPEN、broker finality exact1、失败点在首次未达 append 之后的 retry step4 时钟闸。返工：`formal_clock[0]=retry_now`（L600–601） |
| production 字节 | **未变** | 审查者重算 ADOPTION_R2 表内全部 dirty production SHA：**全部 MATCH**（含 `soak.py`/`soak_runtime.py`/`paper_formal_service.py`/`store.py`/`session_barrier.py`/v010） |

### 12.5 test-owned clock pin 与 public step trace（不绕过 machinery）

| 项 | 结论 | 证据 |
|---|---|---|
| clock pin 范围 | **仅测试** | `_allow_verification_bypass(..., formal_clock=)` monkeypatch `soak_module._production_utc_now`（L250–252, L280–282）；**不**改 production 定义 |
| step trace | **公开窄 API 包装** | `_install_public_narrow_step_trace` 包装 `finalize_and_query_formal_paper_broker_eod` / `session_order_semantic_closure_identity` / `reconcile` / `append_soak_session` / `compute_terminal_successor_identity`，均 `note` 后 **return real_*(...)**（L300–334） |
| 无 raw 暴露 | **满足** | 包装目标均为已公开函数；不引入 store/repo/conn/live barrier；INFRA-007 源码断言仍在（L398–426） |
| 真实闭包断言 | **加强** | zero-command：到达 `broker_finality`…`terminal_successor` 且 CLOSED + successor 非 None；replay `record_calls==1`（L360–393）。mid：首次无 `report_soak`、有注入失败码；retry `record_calls==1` 且 CLOSED（L584–620） |

### 12.6 same-token / broker exact1 / CLOSING / orphan·tamper

| 不变量 | 静态结论 |
|---|---|
| 首次失败不回 OPEN / 不换 token | mid 测例仍断言 CLOSING；同 `inputs.closure` retry |
| broker finality 经济影响 exact1 | 首次与 retry 均 `record_calls == 1` |
| orphan/tamper fail-closed | production/`test_execution_soak` orphan·MISSING 面未在本轮削弱；soak_runtime 源码合同断言保留 |
| 无假绿跳过真实 step | step trace 强制观察到 `report_soak`/`terminal_successor`；wrapper 调用真实 append/successor |

### 12.7 新增对抗反例（本审查；实现者未用）

#### AE-V1-1 — 双时钟：只推进 `now=` 不 pin `_production_utc_now` 仍必败

- **最小复现（静态）**：fixture `now=2026-08-20T16:30Z`，仅把 `close_formal_paper_soak_session(..., now=retry_now)` 调到 `+5s`，**不** monkeypatch `soak._production_utc_now`。step4 `append_soak_session` → `_require_formal_now(invocation_completed_at)` 仍用墙钟（VALIDATION1 日）与 2026-08-20 比较 → `now - value > 5min` → `ValueError` → `PAPER_SOAK_SESSION_INVALID`。这正是 VALIDATION1 mid-sequence retry 形态（stdout L307–318 时尚未 pin）。
- **对照**：返工用可变 `formal_clock[0]` 同步 pin（L343–344 / L600–601），证明根因是 **soak 正式时钟钩子**，不是 barrier/token/OMS。实现者测例在 pin 之后绿路径断言，未单独写“故意不 pin 必败”负向清单——本 AE 补之。
- **通过条件（已满足于返工设计）**：测试若声称覆盖 WINDOWS formal append，必须显式拥有 `_production_utc_now`；不得只改调用方 `now=` 假装闭合。

#### AE-V1-2 — step trace 若替换为 no-op append 不能假绿

- **最小复现（静态）**：若 wrapper 在 `note("report_soak")` 后返回伪造 receipt 而不调用 `real_append`，后续 `_verified_windows_evidence` / receipt 相等检查会 fail-closed。当前实现 **必须** `return real_append(...)`（L318–320）。强化“观察缝 ≠ 跳过真实 step”。

### 12.8 Scope / Gate 边界

| 检查 | 结果 |
|---|---|
| 本轮写入（相对 ADOPTION） | tests：`test_session_barrier.py` / `test_execution_store.py` / `test_paper_soak_runtime.py` + delivery §17；**production SHA 全 MATCH ADOPTION 表** |
| cached / diff-check | cached0；`git diff --check` PASS |
| §12/§15.4/§16 | 仍在；历史违约仍为无效证据；本 PASS 不洗白 |
| 未运行 | 本审查零解释器；VALIDATION1 后 Ruff/mypy/cold/final scope 仍 **UNRUN**；返工后 focused **未**在本会话重跑 |
| 下一步 | 经理可申请完整 **VALIDATION2**（identity→focused exact14→Ruff exact30→mypy production16→cold production16→exact33 scope） |
| 终态 | B1B2 仍未验证；`UA-M4-006` OPEN；禁止宣称工程 Gate 已关或真实 PAPER/soak/Linux |

### 12.9 交接

- 裁决：`VALIDATION1_REWORK_REVIEW_PASS`
- 历史全文保留至 §11
- 本审查者退出；唯一写路径为本报告

---

## 13. RUFF_REWORK 复验（2026-08-26）

> 原独立初验者 · 任务书 §13 / delivery §18 · `STATIC_ONLY`
> 只读：任务书 §13；delivery §18；VALIDATION2 evidence root；当前 `tests/unit/test_session_barrier.py` 与 ADOPTION production SHA 表。
> **完整保留** §0–§12 全部历史裁决，不删改。

### 13.1 裁决

**`RUFF_REWORK_REVIEW_PASS`**

VALIDATION2 Ruff 六项（F401×2 + F811×4）全部落在 `tests/unit/test_session_barrier.py` 的**两处未使用顶层导入**与其函数内同名局部重定义；返工后顶层无该二符号，两测例函数内局部导入 / 真实调用 / 断言仍在；相对 VALIDATION2 `03-ruff` 行号两侧同为 Δ=−2、函数间距不变，支持「仅删两行顶层 import」；production SHA 相对 ADOPTION_R2 表零漂移；delivery §18.1 证据哈希与 UNRUN 边界与磁盘一致。本 PASS **不**等于 Ruff postfix 已跑绿。

### 13.2 VALIDATION2 证据核对（只读磁盘；未重跑工具）

| 项 | delivery §18.1 | 审查者核对 |
|---|---|---|
| evidence root | `...\m4-b1b2-validation2-20260826T064500Z` | 存在；仅 `01-identity` / `02-focused` / `03-ruff` + `stage-summary` + `runner.ps1`；**无** `04*` mypy/cold/scope 产物 |
| 01-identity | PASS；exit=0；stdout_sha256=`87CDF981…473E` | exit.log=`0`；独立 SHA256 **MATCH** |
| 02-focused exact14 | **559 passed / 7 skipped**；exit=0；stdout_sha256=`EF6A236E…959E0E` | exit=`0`；stdout 尾 `559 passed, 7 skipped`；SHA256 **MATCH** |
| 03-ruff exact30 | STOP；exit=1；stdout_sha256=`366B9997…8064`；仅该测试文件 6 项；无 production Ruff 失败 | exit=`1`；`Found 6 errors.`；F401×2 + F811×4 **全部** `tests\unit\test_session_barrier.py`；stdout **无** `src\quant` / `src/quant` 路径；SHA256 **MATCH** |
| mypy / cold / final scope | **UNRUN** | 目录无后续 stage 文件；`stage-summary.log`：`VALIDATION_STOP=STAGE_FAILED:03-ruff:1` — **如实** |

### 13.3 Ruff 失败位点 → 当前字节（精确 diff/行号）

VALIDATION2 `03-ruff` 冻结失败面：

| 码 | 预返工行 | 符号 |
|---|---|---|
| F401 | L52 | 顶层 `recover_session_barrier_closure_capability` |
| F401 | L58 | 顶层 `unpack_session_barrier_closure_capability` |
| F811 | L1209–1210 | 函数内局部同名（`test_closure_capability_issue_recover_forge_and_third_mint`） |
| F811 | L1306–1307 | 函数内局部同名（`test_closure_cross_identity_and_raw_token_closed_remain_substrate_only`） |

当前 `tests/unit/test_session_barrier.py`（`git hash-object`=`3d5a80aca36b18bddc2f7d50091ba845c23d1684`）：

| 检查 | 证据 |
|---|---|
| 顶层无该二符号 | L27–62 `from quant.execution.session_barrier import (`：L51=`read_session_barrier` 后直接 L52=`transition_closing_to_closed`；L56=`unpack_session_barrier_capability` 后直接 L57=`unpack_session_barrier_oms_handle` — **无** `*_closure_capability` |
| 局部导入保留 | L1205–1209：`SessionBarrierClosureCapability` + `recover_…` + `unpack_…`；L1303–1306：`recover_…` + `unpack_…` |
| 调用/断言保留 | L1220–1222 unpack assert；L1229–1232 recover；L1234–1237 TOKEN_CONFLICT；L1260–1261 forge unpack；L1278–1282 remint；L1286–1288 REISSUE_LIMIT；L1323–1327 cross-identity unpack/recover |
| 仅删两行 | 局部 recover 行：预 1209→现 1207；预 1306→现 1304（**两侧 Δ=−2**）；间距 1209↔1306 与 1207↔1304 均为 **97 行** — 两局部导入位点之间无净增删行 |
| 能力语义 | 两测例仍覆盖 issue/recover/forge/third-mint、cross-identity、substrate raw CLOSED；未见 noqa/autofix/把局部搬回顶部；未见改 `terminal_policy` / bind / migration 断言 |

### 13.4 production / 其他路径冻结

| 路径 | 当前 `git hash-object` | vs ADOPTION_R2 §11 表 |
|---|---|---|
| `session_barrier.py` | `2920a4188bfdd1841cd43f61d78972190a3cffeb` | **MATCH** |
| `store.py` | `f8815295003701cffc2e6bce161ef3543f9c8a05` | **MATCH** |
| `soak.py` | `1a6ad2a09124676e299c22c51ccb96a7ff98e935` | **MATCH** |
| `soak_runtime.py` | `892c652263d0f729a31e3452cd85499c880a6a08` | **MATCH** |
| `paper_formal_service.py` | `72e95fa39aac52d95d51884bce956191295d9243` | **MATCH** |
| `v010_terminal_successor.py` | `a3eaf938341b4e82bec38591fe2ae3a4c0bcd314` | **MATCH** |

mtime 旁证（非哈希）：`test_session_barrier.py` / delivery §18 ≈ 06:47；`test_execution_store.py` / `test_paper_soak_runtime.py` 停在 ≈06:34–06:35（VALIDATION1 面）；`session_barrier.py` 05:33 — 与「本轮仅改该测试顶层 import + delivery」一致。

### 13.5 Scope / Gate 边界

| 检查 | 结果 |
|---|---|
| 本轮审查写入 | **仅本报告**追加 §13；未改 production/tests/taskbook/delivery |
| §12/§15.4 历史违约 | 仍为无效证据；本 PASS **不洗白** |
| 本审查会话 | 零 Python / 零 Ruff·pytest 重跑；只读哈希与文本 |
| 未运行（诚实） | VALIDATION2 后 **mypy / cold / final scope UNRUN**；Ruff **postfix 未跑**（本 PASS 不宣称 F401/F811 已工具关闭） |
| 下一步 | 经理可申请 VALIDATION2 postfix：identity→Ruff exact30→mypy production16→cold production16→exact33 scope/residue；**不重复**已绿 focused 559 |
| 终态 | B1B2 仍未验证；`UA-M4-006` OPEN |

### 13.6 交接

- 裁决：`RUFF_REWORK_REVIEW_PASS`
- 历史全文保留至 §12（含 `VALIDATION1_REWORK_REVIEW_PASS`）
- 本审查者退出；唯一写路径为本报告

---

## 14. TYPE_ANNOTATION 复验（2026-08-26）

> 原独立初验者 · 任务书 §14 / delivery §19 · `STATIC_ONLY`
> 只读：任务书 §14；delivery §19；VALIDATION3 evidence root；exact33 当前字节（对照 ADOPTION production SHA）。
> **完整保留** §0–§13 全部历史裁决，不删改。

### 14.1 裁决

**`TYPE_ANNOTATION_REVIEW_PASS`**

本轮相对即时前态的可逆 diff **恰好三行**：L10 标准库 `AbstractContextManager` 导入，以及 `VerifiedFormalPaperClosureView.hold_terminal_closure` / `hold_terminal_step` 两处返回注解 `object` → `AbstractContextManager[object]`。函数体仍为对 `hold_formal_terminal_*` 的逐字转发；锁/capability/schema/escape 面未放宽；**未新增** `Any` / `cast(` / `type: ignore`。VALIDATION3 证据哈希与 cold/final **UNRUN** 边界与 delivery §19 一致；本 PASS **不**宣称 mypy 14 项已关闭或 VALIDATION4/Gate 完成。

### 14.2 VALIDATION3 证据核对（只读磁盘；未重跑工具）

| 项 | delivery §19.1 | 审查者核对 |
|---|---|---|
| evidence root | `...\m4-b1b2-postfix-validation3-20260826T071119Z` | 存在；仅 `01-identity` / `03-ruff` / `04-mypy` + summary（**无** `02-focused` / `05-cold` / scope） |
| 01-identity | PASS；exit=0；stdout_sha256=`87CDF981…473E` | exit=`0`；SHA256 **MATCH** |
| 03-ruff exact30 | PASS；exit=0；stdout_sha256=`AF352A86…D9AF` | exit=`0`；stdout=`All checks passed!`；SHA256 **MATCH** |
| 04-mypy production16 | STOP；exit=1；stdout_sha256=`50441960…5299`；`soak_runtime.py` 七 `with` ×14 `attr-defined` | exit=`1`；L175/241/274/302/327/379/394 各 `__enter__`+`__exit__`；`Found 14 errors in 1 file`；SHA256 **MATCH** |
| cold / final scope | **UNRUN** | 无后续 stage 文件；`stage-summary` SHA256=`6EDCE34C…4B67` **MATCH**；正文 `VALIDATION_STOP=STAGE_FAILED:04-mypy:1` |
| focused559 | 沿用 VALIDATION2；本轮未重跑 | 诚实；目录无 `02-focused` |

### 14.3 本轮 diff（精确行号）

当前 `paper_formal_service.py`：`git hash-object`（clean）=`91a8b5cba300322533113f98bcb9cf45ef553968`。

将下列三处逆向还原后，与当前文件 **逐行比对仅这三行不同**（其余 631 行恒等；行数 634=634）：

| 行 | 还原前（本轮前态） | 当前 |
|---|---|---|
| L10 | `from contextlib import contextmanager` | `from contextlib import AbstractContextManager, contextmanager` |
| L199 | `def hold_terminal_closure(self, closure: object) -> object:` | `... -> AbstractContextManager[object]:` |
| L209 | `) -> object:`（`hold_terminal_step`） | `) -> AbstractContextManager[object]:` |

逆向内容 clean SHA=`584d7bd585d58a807eb6514ad1b4e688ced059f6`（仅作本轮前态指纹；见 §14.5 台账残差）。

函数体（不变）：

```199:215:src/quant/execution/paper_formal_service.py
    def hold_terminal_closure(self, closure: object) -> AbstractContextManager[object]:
        """Hold the B1 anchored lock for one durable terminal closure sequence."""
        return hold_formal_terminal_closure(
            capability=_closure_view_execution_store(self),
            closure=closure,
            now=_utc_now(),
        )

    def hold_terminal_step(
        self, context: object, *, step_kind: str
    ) -> AbstractContextManager[object]:
        """Mint one single-step terminal child under an already-held context."""
        return hold_formal_terminal_step(
            context,
            capability=_closure_view_execution_store(self),
            step_kind=step_kind,  # type: ignore[arg-type]
        )
```

### 14.4 runtime / schema / lock / escape / 禁止项

| 检查 | 结论 |
|---|---|
| 运行分支 | 体仍只 `return hold_formal_terminal_closure/step(...)`；无新增分支/异常/时序 |
| yield/caller 可见类型 | `AbstractContextManager[object]` — yield 仍为 **object**；未把 live terminal child/context/capability 写入公开返回注解 |
| 参数面 | 仍 `closure: object` / `context: object` / `step_kind: str` |
| 底层 CM | `paper_formal_execution_store.hold_formal_terminal_*` 仍 `-> Iterator[object]`（SHA `048c5b06…` **MATCH ADOPTION**）；本轮未改 |
| soak 调用点 | `soak_runtime.py` SHA `892c6522…` **MATCH**；`with view.hold_terminal_*` 位点未改 |
| `Any` / `cast(` | **零**新增；文件无 `cast(`；唯一 `any` 命中为 docstring 英文 “any commit/write”（L119），非 typing.Any |
| `type: ignore` | 仍仅既有三处：L214 `arg-type`、L327/L453 `no-untyped-def`；逆向后仍在 → **非本轮新增** |
| Protocol 泛化 | 无 |

### 14.5 其他 exact33 冻结与 SHA 台账残差

| 路径 | 当前 clean SHA | vs ADOPTION_R2 |
|---|---|---|
| `session_barrier.py` | `2920a418…` | **MATCH** |
| `store.py` | `f8815295…` | **MATCH** |
| `soak.py` | `1a6ad2a0…` | **MATCH** |
| `soak_runtime.py` | `892c6522…` | **MATCH** |
| `paper_formal_execution_store.py` | `048c5b06…` | **MATCH** |
| `v010_terminal_successor.py` | `a3eaf938…` | **MATCH** |
| `paper_formal_service.py` | `91a8b5cb…`（注解后） | 预期变化 |
| 本轮前态（三行逆向） | `584d7bd5…` | ≠ 历史表 `72e95fa3…` |

残差（不升格为本轮注解 FAIL）：ADOPTION/RUFF 曾记录 PFS=`72e95fa3…`，但当前减去本轮三行后的指纹为 `584d7bd5…`。**不能**用历史表字节证明「注解前 ≡ ADOPTION 快照」；**能**用逐行可逆 diff 证明「本 rework 自身只动了 import+两返回注解」。mtime：PFS/delivery ≈07:15；`soak_runtime` 05:57、`test_session_barrier` 06:47 — 与「仅改该文件+delivery」一致。经理若需闭合台账，应在 VALIDATION4 前单独核对 PFS 历史漂移，**不**在本注解合同内扩修。

### 14.6 Scope / Gate 边界

| 检查 | 结果 |
|---|---|
| 本审查写入 | **仅本报告** §14；business/tests/taskbook/delivery 只读 |
| §12/§15.4 | 仍为无效证据；不洗白 |
| 本会话 | 零解释器 / 零 Ruff·mypy·pytest 重跑 |
| 未运行 | cold / final scope **UNRUN**；mypy 14 项 **未**在注解后重跑（postfix=VALIDATION4） |
| 下一步 | 窄 VALIDATION4：identity→Ruff 本文件→mypy production16→cold production16→exact33 scope；不重复 focused559 |
| 终态 | B1B2 候选；`UA-M4-006` OPEN |

### 14.7 交接

- 裁决：`TYPE_ANNOTATION_REVIEW_PASS`
- 历史全文保留至 §13
- 本审查者退出；唯一写路径为本报告

---

## 15. EVIDENCE_REVIEW（2026-08-26）

> 原独立初验者 · 任务书 §15 / delivery §20 · `STATIC_ONLY`
> 只读：各 evidence root 磁盘产物、delivery §20、任务书 §15、exact33 白名单、当前 `git status`/`diff --check`、本报告 §0–§14 历史链。
> **完整保留** §0–§14 全部裁决（含 FAIL/PASS 与违约记录），不删改、不洗白。

### 15.1 裁决

**`EVIDENCE_REVIEW_PASS`**

组合证据闭合成立且不伪造单轮全绿：V2 focused **559/7** + V4 identity/Ruff(本文件)/mypy16/cold16 **PASS** + scope-close5 actual19⊆exact33 / cached0 / diff-check / residue/writer **PASS**；V1–V3 与 scope-close1–4（及附加 SCOPE_EXTRA）首失败/UNRUN **均仍在磁盘且 SHA 与 delivery §20 一致**。F1→R1-F2/F3→采用→V1返工→Ruff→注解审查链完整保留。delivery 本包状态 `B1B2_WINDOWS_ENGINEERING_VALIDATED` 与 `SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN` 边界诚实；**无**真实 PAPER/soak/Linux Gate 关闭声明。本 PASS **仅**授权进入安全提交申请，**不是** UA-M4-006 关闭或 M4 完成。

### 15.2 VALIDATION1–4 关键 SHA / exit（磁盘核对）

| 轮次 | root 存在 | 关键核对 | vs delivery §20.2 |
|---|---|---|---|
| **V1** | `...validation1-20260826T062412Z` | summary=`8503F566…B7B0`；focused stdout=`29728EC6…C845`；exit focused=1 / identity=0；尾 `4 failed, 555 passed, 7 skipped`；无 `03-ruff`；`VALIDATION_STOP=STAGE_FAILED:02-focused:1` | **MATCH**；UNRUN 后续如实 |
| **V2** | `...validation2-20260826T064500Z` | summary=`452F153B…09DB`；focused=`EF6A236E…959E0E` exit=0 `559 passed, 7 skipped`；ruff=`366B9997…8064` exit=1；无 `04-mypy`；`STOP:03-ruff:1` | **MATCH** |
| **V3** | `...postfix-validation3-20260826T071119Z` | summary=`6EDCE34C…4B67`；ruff=`AF352A86…D9AF` exit=0；mypy=`50441960…5299` exit=1；无 focused/cold；`STOP:04-mypy:1` | **MATCH** |
| **V4** | `...postfix-validation4-20260826T072258Z` | summary=`E32F8154…8B44`；identity=`87CDF981…473E` exit=0；ruff=`AF352A86…D9AF` exit=0（runner **仅** `paper_formal_service.py`）；mypy=`6F0C27F6…3061` exit=0 `Success: no issues found in 16 source files`；cold=`756443DB…0B65` exit=0（16 production 路径列出）；06-scope stderr=`DCFC2A99…24E4` exit=1 `SCOPE_EXTRA` 三 docs；**无** `06-scope.stdout`（summary 记缺文件 STOP） | **MATCH**；工程四段绿 + 内嵌 scope FAIL **不洗白** |

组合要件映射：focused559 ← V2；Ruff/mypy/cold ← V4；**非**同一 runner 全绿。

### 15.3 scope-close1–5

| # | root | 磁盘结论 | 关键 SHA | vs §20.3 |
|---|---|---|---|---|
| 1 | `...raw-bytes-scope-20260825T235204Z` | FAIL `GIT_STATUS_RECORD_INVALID`；exit=1 | stderr=`2AA21EDA…3AFB`；git-status.raw=`48132F7E…CD0E` | **MATCH** |
| 2 | = V4 `06-scope` | FAIL `SCOPE_EXTRA` 三 docs | stderr=`DCFC2A99…24E4` | **MATCH**（无独立 close2 目录 — 交付已声明） |
| 3 | `...scope-close3-20260825T235504Z` | FAIL 再次 `GIT_STATUS_RECORD_INVALID` | stderr=`1BCC8BC2…384E` | **MATCH** |
| 4 | `...scope-close4-20260825T235812Z` | FAIL 空 cached `ConvertFrom-NulPayload` | stderr=`007A9FA6…819A` | **MATCH** |
| **5** | `...scope-close5-20260826T000341Z` | **PASS** `RAW_BYTES_SCOPE_PASS`；ACTUAL=19；ALLOWED=33；CACHED=0；DIFF_CHECK=PASS；TEMP_CACHE=ABSENT；F00_RESIDUE=0；WRITER_PID=7692 / BelowNormal / 0x3；exit_code=0 | stdout=`DE6BE7EB…F27F`；exit 文件 SHA=`5FECEB66…57E9`；git-status.raw=`48132F7E…CD0E`；cached/diff-check empty=`E3B0C442…855` | **MATCH** |
| 附加 | `...scope-close-20260826T074843Z` | 再次 SCOPE_EXTRA（保留） | stderr=`1E1404DF…50B3` | **MATCH**；不推翻 sc5 |

时间戳备注（非 FAIL）：sc5 目录时戳 `000341Z` 早于 V4 `072258Z`；属组合路径集合证据，非“V4 之后单轮 scope 绿”。当前 WT 路径集仍与 sc5 ACTUAL19 **一致**（见下）。

### 15.4 actual19 ⊆ exact33 / cached0 / diff / residue（当前 WT）

- 任务书 §3 exact33 = 33；当前 `git status --porcelain -z` **19** 条；**extras=0** → **⊆ exact33**。
- 19 路径与 delivery §20.3 / sc5 ACTUAL 清单**逐条同集**（3 docs + 11 production/migration + 5 tests）。
- `git diff --cached --name-only` 空 → **cached0**。
- `git diff --check` exit=0 → **PASS**。
- 本审查未发现 temp/cache/0xF00 业务残留要求之外的额外 dirty。

### 15.5 F-chain 与审查史保全

| 链环 | 本报告位置 | 状态 |
|---|---|---|
| F1–F4 初验 FAIL | §0–§8 | **保留** |
| R1-F2 / R1-F3 FAIL | §9 | **保留** |
| R2 产品闭合 PASS | §10 | **保留** |
| ADOPTION_R2 PASS | §11 | **保留** |
| VALIDATION1 返工 PASS | §12 | **保留** |
| RUFF 返工 PASS | §13 | **保留** |
| TYPE_ANNOTATION PASS | §14 | **保留** |
| §12/§15.4 违约 | delivery 历史 + 历次审查声明 | **不洗白**（仍为无效探针证据） |

无发现把 V1 focused FAIL、V2 Ruff FAIL、V3 mypy FAIL、sc1–4 FAIL 改写成通过的矛盾表述；delivery §20 明确“首失败保留”。

### 15.6 Gate / 过度声明核对

| 声明 | 结论 |
|---|---|
| `B1B2_WINDOWS_ENGINEERING_VALIDATED` | **允许**：组合证据满足任务书 §15；delivery §20.1/§20.5 已写 |
| `SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN` | delivery §20.1 **明确 OPEN**；§20.5 重申 — **诚实** |
| 真实 PAPER / soak / 28 日 / fault-drill / Linux Gate / 新 root·epoch / M4 完成 | delivery 终态与 §20 **禁止声称** — **无过度声明** |
| `UA-M4-006_WINDOWS_ENGINEERING_CLOSED` | §20 **未**宣称关闭（历史 § 文仅“候选上限”） — **未越界** |

### 15.7 本审查边界

| 项 | 结果 |
|---|---|
| 本会话写入 | **仅本报告** §15 |
| business / taskbook / delivery | **只读未改** |
| 工具 | 零 Python/pytest/Ruff/mypy/cold；只读哈希与 git status/diff-check |
| stage/commit | **无** |
| 下一步 | 经理可申请**安全提交**；提交后仍不得宣称 UA-M4-006 用户关闭或真实 PAPER/soak/Linux |

### 15.8 交接

- 裁决：`EVIDENCE_REVIEW_PASS`
- 历史全文保留至 §14
- 本审查者退出；唯一写路径为本报告
