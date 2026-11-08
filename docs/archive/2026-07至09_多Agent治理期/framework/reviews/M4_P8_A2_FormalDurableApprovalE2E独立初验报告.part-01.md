# M4 P8 A2：Formal Durable Approval E2E 独立初验报告

日期：2026-08-25<br>
身份：未参与实现的独立初验 / REWORK2/3 复验 Agent（STATIC_ONLY）<br>
exact base / HEAD：`7fe836dcfbd841c5473057d3f6e222a6081ae3fa`<br>
branch：`codex/m4-a2-formal-approval-flow`<br>
worktree：`artifacts/dev_worktrees/m4-a2-formal-approval-flow`<br>
唯一写入：本报告<br>
结论：**REVIEW_PASS**（REWORK2/3 静态复验；无 P0/P1；不得解读为运行验证或 Gate 通过）<br>
历史：§0–§7 为首轮独立初验原文；§8 为 REWORK2/3 复验追加。

## 0. 审查边界

- 只读 exact15（实现 13 + 任务书 + 交付报告）；未改实现/测试/任务书/交付报告。
- **未运行**：Python / pytest / Ruff / mypy / cold import / SQLite probe / 网络 / browser / PAPER / commit。
- 证据来源：任务书、交付报告（含 REWORK1 追加）、working tree 相对 base 的 diff 与源码静态阅读。
- exact15 路径集合与 `git status`/`git diff --name-only` 一致；未见 `approval.py` / `store.py` / migration / config / `__init__.py` / roadmap 越界修改。

## 1. 中央合同逐项证据

| # | 合同点 | 静态结论 | 证据（路径/符号） |
| --- | --- | --- | --- |
| 1 | credential/secret 不持久化、不进 repr/log/error；首次 secret authority 诚实 | 通过 | `approval_flow.py`：`_secret`/`_proof` 为 `repr=False,compare=False`；错误仅稳定 code + `from None`；模块 docstring/交付 §4 与 `test_first_capability_authority_honesty_and_wrong_secret_reverify` 明确首次注入即 authority，wrong-secret 仅 reverify/conflict |
| 2 | fake capability/bool/raw receipt/反射构造不能绕过 | 通过 | `FormalApprovalCredentialCapability.__init__` 拒绝；`unpack_*` 要求 `type is` + HMAC proof；`require_verified_approval_receipt` → A1 `unpack_verified_approval_receipt`；测试覆盖 bool/raw/Protocol/`object.__new__` 假 proof；service/risk 拒 True |
| 3 | full planning source exact key set + digest；target receipt/verification 不弱化 | 通过（REWORK1 F1） | CLI `_planning_sources` 含 `target_receipt_identity`/`target_verification_identity`；`normalize_approval_source_identities` exact 6 keys；`prove_approval_source_binding` 只复算可推导子集；`test_plan_and_approve_challenges_keep_full_planning_source_keys`、service weak-map → `APPROVAL_SOURCE_DRIFT` |
| 4 | confirm 成功前不触碰 capability；trusted operator/session/plan 绑定 | 通过（REWORK1 F4/F5） | `_approve`：`_confirm_or_emit` 在 capability 使用之前；无 confirm 时 `test_approve_confirm_gate_leaves_fail_on_call_capability_untouched`；issue/reverify 交叉 operator/session；service 校验 plan/session/source digest；单次 `_now` 用于 challenge 与签发 |
| 5 | 同一 `BEGIN IMMEDIATE`：recovery fence → approval first → risk/stage/command/outbox/ledger；异常全回滚 | 通过 | `ExecutionStore.transaction`：`BEGIN IMMEDIATE`，异常 `_safe_rollback`；`_plan_and_stage_with_approval`：无 existing 时 `recover_repository_state` → `put_verified_approval_receipt` → `evaluate_pretrade` → `_write_order_stage`；`test_approval_insert_then_stage_failure_rolls_back_entire_tx` 断言审批及相关表 count=0 |
| 6 | exact receipt replay 完整闭包；孤儿拒绝且不补完 | 通过（REWORK1 F3） | existing 路径：index/payload exact → stage decode → risk chain/ORDER receipt → `_require_approval_replay_closure`（ledger + 逐 command/aggregate/outbox/delivery）；缺 stage → `APPROVAL_ORPHAN_STAGE_MISSING`；`test_approval_replay_orphan_closure_fail_closed` 参数化 8 类，失败后 bytes 不变 |
| 7 | zero-command durable closure/replay；SHADOW 零命令；manual 无 receipt 零命令 | 通过 | `test_approval_zero_command_closure_and_exact_replay`；risk：`SHADOW` 永不发 command；`manual_approval and verified_approval is None` → `MANUAL_APPROVAL_REQUIRED`；`test_verified_approval_unlocks_manual_gate_for_paper_only` |
| 8 | 不提交 gateway；不冒充 A1/A2/PAPER Gate | 通过 | approve/`plan_and_stage` 路径 gateway.calls 断言为 0；`paper-submit` 仍独立 challenge；交付/本报告均声明 STATIC_ONLY，未宣称 Gate |

## 2. REWORK1 F1–F5 对抗核对

| 项 | 结论 | 核对摘要 |
| --- | --- | --- |
| F1 | 闭合 | 弱 `target_identity` 集合被拒绝；完整 planning-source keys 恢复；service 显式 `approval_source_identities` |
| F2 | 闭合 | CLI/formal-daily fresh post-completion → `APPROVAL_STAGED_REPLAY` + 同 `receipt_id`；`reverify_stored_approval_receipt` + index 交叉；wrong capability 失败且无 secret 进 stderr |
| F3 | 闭合 | replay 补齐 command/aggregate/outbox/delivery/ledger join；参数化孤儿删除 fail-closed |
| F4 | 闭合 | zero-command、insert 后 stage 失败整事务回滚、CLI confirm 前 fail-on-call、formal capability/operator/session 透传与 session mismatch |
| F5 | 闭合 | `test_pretrade_risk.py` 尾部 `build_execution_event,` / `evaluate_cancel_risk,` 已恢复；approve 单次 clock read |

说明：交付报告首轮 §3–§4 仍保留 REWORK1 前表述（弱 source / fresh→CONFIRMATION_DRIFT），与 §7 追加及当前代码不一致；符合“不改写首轮历史”约束，不作为实现缺陷计分，但读者须以 §7 + 代码为准。

## 3. 发现分级

### 无 P0 / P1

### [P2] 合法 capability 的字段级 `object.__new__` 克隆仍可通过 unpack — `src/quant/execution/approval_flow.py`

实现者已覆盖 `copy`/`deepcopy`/`pickle` 失败，以及**无效 proof** 的 `object.__new__` 伪造。但静态上：对**已由 factory 签发的真实 capability**，按字段 `getattr` → `object.__setattr__` 重建的同类型对象可通过 `unpack_formal_approval_credential_capability`（proof 仍有效）。这不扩大“已持有 capability 的进程内 authority”，但绕过了 copy/pickle 硬失败面；`dataclasses.replace` 会走拒绝型 `__init__`（静态预期失败，实现者未单测）。建议补测：合法字段克隆是否应继续拒绝，或文档化为 process-local 已知面。

### [P3] capability 相等性忽略 `_secret`/`_proof`

`compare=False` 使同公开 id、不同 secret 的两个 capability `__eq__` 为真。当前鉴权路径走 unpack/HMAC 而非 `==`，暂无直接绕过；若未来用 set/dict 去重 capability 会误判。

## 4. 实现者未使用的静态对抗反例（至少一例）

**反例 A（capability 字段克隆，见 §3 P2）**

最小静态复现（未执行）：

1. `cap = build_formal_approval_credential_capability(secret, ...)`
2. `clone = object.__new__(FormalApprovalCredentialCapability)`
3. 对 `credential_id/operator_id/session_date/_secret/_proof` 逐字段 `object.__setattr__(clone, name, getattr(cap, name))`
4. 预期（当前实现）：`unpack_formal_approval_credential_capability(clone)` 成功；而 `copy.copy(cap)` / `pickle.dumps(cap)` / `dataclasses.replace(cap, ...)` 失败
5. 规则：copy/pickle 封印若要表达“不可复制的受控 hand-off”，应连同字段级重建一起封闭，或明确“持有引用即持有 authority”
6. 建议测试：合法字段克隆断言（拒绝或诚实记录）；保留 replace/copy/pickle 失败断言

**反例 B（CLI 读库短事务与 service 写事务之间的 TOCTOU，实现者未以 CLI E2E 命名覆盖）**

1. CLI `_approve` 在独立 `store.transaction` 中 `get_approval_receipt_for_plan` 后提交，再在事务外 issue/reverify，最后进入 `plan_and_stage` 新的 `BEGIN IMMEDIATE`
2. 并发写入若在间隔内完成同 plan 审批或改变 economic recovery：service 侧 `APPROVAL_BUSINESS_KEY_CONFLICT` / `APPROVAL_RECOVERY_DRIFT` / orphan 检查 fail-closed，不补完
3. 静态认为安全；建议后续授权运行时补一条“challenge 确认后、stage 前注入并发写”的 CLI 级残留为零断言（与任务书 §8.4 更贴齐）

## 5. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite / 网络 / PAPER / broker / browser | **未运行** |
| Git commit | **未执行** |
| A1/A2/PAPER/Linux Gate / UA-M4-006/007 | **不声称** |

本结论仅基于静态合同对照；经理授权 CPU 槽后的 focused 运行验证仍为后续门禁。

## 6. 结论

**REVIEW_PASS**

无 P0/P1；REWORK1 F1–F5 与中央合同在源码与测试断言层面静态对齐；exact15 无越界。残留 P2/P3 不阻断进入授权运行验证，但不得将本报告表述为 pytest/Ruff/mypy/Gate 已通过。

报告路径：`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`

## 7. 报告 SHA256（DOC-WHITESPACE 规范化后重签）

`5683d7b1da4ed9a85df7edd638549e3e2ddf5fc5778a88c6ba4f1bbff02be99b`

口径：对本文件「§7 标题行之前」全部 UTF-8 字节计算 SHA-256。原「首轮历史指纹；勿覆盖」口径因本轮行尾空白规范化导致标题前字节变化，已按实际标题边界重签；业务结论未改。REWORK2/3 复验指纹见 §9。


## 8. REWORK2/3 静态复验（追加；不改写 §0–§7）

日期：2026-08-25<br>
角色：未参与实现的独立 reviewer 新会话<br>
范围：exact17 只读；唯一写入本报告<br>
约束：**STATIC_ONLY** — 未运行 Python / pytest / Ruff / mypy / cold / SQLite / network / browser / PAPER / commit；未改实现 / 测试 / 任务书 / 交付报告。

### 8.1 exact17 边界

相对 base `7fe836d…ae3fa` 的变更路径与任务书 §14 exact17 一致：

实现/测试 15+2：`approval_flow.py`、`cli.py`、`cli_ports.py`、`paper_formal_daily.py`、`reconcile.py`、`risk.py`、`risk_wire.py`、`service.py` 及对应 8 个 unit 测试；外加任务/交付文档。
未见 `store.py` / schema / migration / config / `__init__.py` / roadmap / `approval.py` 越界修改。

### 8.2 中央 §14 + F6–F13 对抗核对

| 项 | 静态结论 | 证据摘要 |
| --- | --- | --- |
| §14.2 唯一 stage encoder | 通过 | `risk_wire.encode_execution_stage` 接受 `RiskDecision`/`DurableOrderRiskDecision`；`service._encode_stage` 仅委托该入口；schema 仍为 `m4-execution-stage-v1`；`test_encode_execution_stage_matches_risk_and_durable_decision` |
| §14.3 zero ORDER + 默认空 allow-set | 通过 | `verify_risk_receipt_semantic_closure(..., allowed_zero_order_subject_ids=frozenset())`；默认空拒绝；subject∈allow-set 且 empty intents/commands、`accepted`、`!manual`、subject==plan_id、chain/counter/wire、allow-set exact consume；`test_verify_risk_closure_*` |
| §14.4 service/reconcile 闭包 | 通过 | 两侧 `_prove_zero_order_allow_set`：approval raw/index（含 action=`FORMAL_APPROVAL_ACTION`、plan/session 与 decode 闭合）+ stage key/identity/encoder bytes；reconcile 仅结构、无 HMAC；service live replay 仍逐字段比对 `VerifiedApprovalReceipt` |
| §14.4 PAPER 写前 / SHADOW | 通过 | mode≠PAPER → `APPROVAL_PAPER_ONLY`（approval 写入前）；`test_approval_shadow_mode_rejects_before_any_write` 全表零写；pretrade SHADOW+verified 仍零命令且不经 service 持久化 |
| reporting/soak 默认空集合 | 通过（合同边界） | `execution_report`/`soak` 调用 verifier 不传 allow-set；`_verify_recovery`/`_prove_recovery` 重建时丢弃 allow-set 字段 → 含 zero ORDER 的 recovery 在报告/soak 路径 fail-closed（§14.4 明示） |
| F6 source drift | 通过 | exact-type Guard 不触 `__getattr__`；`reverify` 将 `APPROVAL_SOURCE_IDENTITIES_INVALID` 归一为 `APPROVAL_SOURCE_DRIFT`；CLI confirm 前 untouched 保留 |
| F7 FK/WAL | 通过 | orphan 改为 UPDATE + `_logical_execution_snapshot`；不再 DELETE 破坏 FK / 比较 WAL 主文件 bytes |
| F9 canonical source | 通过 | pretrade fixture `dict(sorted(...))` + unique values |
| F11 service 四族 drift | 通过 | `test_approval_zero_replay_rejects_stage_and_approval_structure_drift` 参数隔离：`stage_payload`/`stage_identity`/`approval_raw_payload`/`approval_index_identity`/`approval_index_session`；先证 snapshot 变，再 fail-closed，后 snapshot exact |
| F12 reconcile drift | 通过 | 正向结构闭包 + `test_recover_zero_approval_rejects_approval_or_stage_structure_drift` 四类；`RECOVERY_RISK_CLOSURE_INVALID`；前后 logical snapshot exact |
| F13 RecoveryResult allow-set | 通过 | `_recovery_identity` **不含** allow-set / approval rows；`__post_init__`→semantic exact-consume；`test_recovery_result_allow_set_exact_with_observed_zero_subjects`（extra/missing/wrong）；合法重建同 id；伪造集构造拒绝。选择保留公共 witness 字段与交付 §9.1 一致 |
| 普通 nonzero/CANCEL | 通过（静态） | verifier 非空 `command_ids` 分支未改；既有 CANCEL/ORDER 测试文件保留；本轮未运行故不声称绿测 |
| 既有 P2/P3 | 保留 | 交付 §8.5 与首轮一致：合法 capability 字段级 `__new__` 克隆仍可通过 unpack；`__eq__` 忽略 secret/proof |

### 8.3 发现分级（REWORK2/3）

### 无 P0 / P1

### 既有 [P2]/[P3]（复核保留，非本轮新开）

见 §3：进程内 capability 字段克隆与 equality 面；不扩大跨进程/跨存储 authority。

### 8.4 实现者未使用的静态对抗反例（本轮新增）

**反例 C（stage encoder 异常 dataclass / 子类）**

实现者覆盖 RiskDecision↔Durable 同字节，未覆盖非 exact-type。

1. `sub = object.__new__(RiskDecision)` 或不完整字段对象；或 `class Sub(RiskDecision): ...` 实例
2. 静态预期：`encode_execution_stage(sub)` 因 `type(decision) is RiskDecision` 失败 → `RiskReceiptError`
3. 规则：唯一 encoder 不得接受子类/残缺对象生成“看起来像”的 stage bytes
4. 建议授权运行后补测：子类与 `__new__` 残缺对象均稳定拒绝

**反例 D（多 zero 历史链 + 部分 allow-set / 重复 subject）**

实现者单 plan zero 正向/多余 allow；未显式多 zero 链与重复 subject。

1. 内存构造两笔不同 `plan_id` 的合法 zero ORDER 链（或同 subject 两笔——DB 有 `UNIQUE(transition_kind,subject_id)`，持久化路径不可；仅测 verifier）
2. `allowed_zero_order_subject_ids={only_first}` → exact-consume 拒绝；全集 exact → 通过
3. 同 subject 两笔 zero：allow-set 单元素可能骗过 set-consume，但同 `risk_counter_key` 下第二笔 predecessor 必失败
4. `_prove_zero_order_allow_set` 对重复 `plan_identity` 的多 session approval：`len(by_plan)!=len(rows)` 拒绝（business-key 歧义）

**反例 E（`RecoveryResult.__new__` 与正常构造 / `reconcile` 入口）**

实现者已测构造器拒绝伪造 allow-set，并证明 `__new__` 可得同 `recovery_id`。补充：

1. 用 `__new__` 写入错误 allow-set 且 `recovery_id=_recovery_identity(...)`
2. `reconcile(local, ...)` 只检查 `type is RecoveryResult` 与 `recovery_id == _recovery_identity(local)`，**不**重跑 allow-set consume
3. 结论：与 §3 P2 同类——绕过 `__post_init__` 的进程内对象不是“第二合法状态”；合法 `RecoveryResult(...)` 仍唯一。建议文档化：下游若消费 allow-set，必须经构造器或显式 re-prove，不得信任裸 `__new__` 对象

### 8.5 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite / 网络 / PAPER / broker / browser | **未运行** |
| Git commit | **未执行** |
| A1/A2/PAPER/Linux Gate / UA-M4-006/007 | **不声称** |
| 本结论 | **仅静态**；不得冒充授权运行验证 |

### 8.6 复验结论

**REVIEW_PASS**

无 P0/P1；REWORK2/3 F6–F13 与中央 §14 在源码与测试断言层面静态对齐；exact17 无越界；既有 P2/P3 进程内 authority 边界保留。reporting/soak 默认空 allow-set 拒绝 zero 为合同明示残留集成面，不构成本包缺陷。

报告路径：`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`

## 9. REWORK2/3 复验报告 SHA256（DOC-WHITESPACE 规范化后重签）

`7df97525ababa98a915123f513bef785895c45a308429fcb27353ad0167b5583`

口径：对本文件「§9 标题行之前」全部 UTF-8 字节（含 §0–§8 及 §7 重签指纹段；**不含**本 §9 块）计算 SHA-256。本值于 DOC-WHITESPACE 行尾规范化后按实际标题边界重签；不再沿用「回填后正文指纹不变」旧口径。业务结论未改。


## 10. REWORK4 静态复验（追加；不改写 §0–§9）

日期：2026-08-25<br>
角色：未参与实现的全新独立初验 Agent（REWORK4 / F14–F17）<br>
范围：exact17 实现/测试只读；唯一写入本报告<br>
约束：**STATIC_ONLY** — 未运行 Python / pytest / Ruff / mypy / cold / SQLite probe / 网络 / browser / PAPER / commit；未改生产 / 测试 / 任务书 / 交付报告。<br>
对照：任务书 §16（含 F14 合同漏项）、交付报告 §12–§13、既有 §0–§9。

### 10.1 本轮变更边界（生产字节）

相对 REWORK3 后现场，REWORK4 允许写集为 `reconcile.py` + `test_reconcile.py` / `test_execution_service.py` / `test_pretrade_risk.py` + 任务/交付文档。

静态 mtime 证据（本机工作树）：

| 路径 | LastWriteTime | 本轮结论 |
| --- | --- | --- |
| `src/quant/execution/reconcile.py` | 2026-08-25 18:24 | **本轮唯一生产改动**（F15） |
| `tests/unit/test_reconcile.py` | 2026-08-25 18:28 | F14 CAST+typeof / F15 断言 |
| `tests/unit/test_execution_service.py` | 2026-08-25 18:29 | F14 CAST+typeof / F16 DELETE |
| `tests/unit/test_pretrade_risk.py` | 2026-08-25 18:25 | F17 planner 可选参 |
| `src/quant/execution/risk_wire.py` | 2026-08-25 17:32 | **未改** |
| `src/quant/execution/service.py` | 2026-08-25 17:33 | **未改** |
| `src/quant/execution/approval_flow.py` | 2026-08-25 17:44 | **未改** |

`service.py` / `risk_wire.py` / `approval_flow.py` 正文无 F14 `CAST(...AS BLOB)` / `typeof(payload)` / F15 `query_approval_receipts` 前置模式；与交付 §13「仅改 reconcile + 三测试」一致。

### 10.2 F14–F17 对抗证据映射

| 项 | 静态结论 | 证据摘要 |
| --- | --- | --- |
| F14 CAST 保持 BLOB | 通过 | reconcile/service 两处 `approval_raw_payload`：`CAST(payload \|\| X'00' AS BLOB)`；未改 v008 `CHECK (typeof(payload) = 'blob')` |
| F14 typeof 可观察 | 通过 | 仅该分支、`commit` 后 `SELECT typeof(payload)` 且 `assert == "blob"`；其他 tamper 分支无此断言；随后 `snapshot≠before` → fail-closed → snapshot exact |
| F15 approval 专读失败→risk | 通过 | `recover_repository_state`：先 `repo.query_approval_receipts()`，`except Exception`→`_RiskRecoveryClosureError`；再 `read_recovery_rows()`；`rows.approval_receipts != observed_approvals`→同归 risk；外层映射 `RECOVERY_RISK_CLOSURE_INVALID` |
| F15 非 approval 不吞 | 通过 | 后续 command/event/aggregate 等仍 `raise ValueError`→通用 `except Exception: pass`→`RECOVERY_LOCAL_INVALID`；既有 `test_orphaned_context_parent_fails_recovery_*` 仍断言 LOCAL；cancel 仍走 `_CancelRecoveryClosureError` |
| F16 delivery 真实 schema | 通过 | `DELETE FROM outbox_deliveries WHERE outbox_key = ?`；v002 表无 `identity` 列（identity 来自 outbox join）；replay `_require_approval_replay_closure`→`APPROVAL_ORPHAN_DELIVERY_MISSING`；测试证 snapshot 变→拒绝→不补完 |
| F17 planner/trading 互异 | 通过 | `_plan(..., planner_config_identity=None)` 默认 `planner_id=cfg_id`；PAPER/SHADOW 分别传 `_hex64("pretrade-planner-paper\|shadow")`；`config_identity!=trading_config_identity`；intent 共享 planner；`dict(sorted)` + unique values；其余 `_plan(` 调用未传可选参 |
| P2/P3 / review E | 保留 | 进程内 capability 字段克隆、`__eq__` 忽略 secret/proof、`RecoveryResult.__new__` allow-set 旁路；交付 §13.2 明示本轮未消除 |

### 10.3 发现分级（REWORK4）

### 无 P0 / P1

### 既有 [P2]/[P3] / review E（复核保留，非本轮新开）

见 §3 / §8.3 / §8.4 反例 E：仍为进程内 authority 边界，不扩大跨进程/跨存储 authority。

### 10.4 实现者未使用的静态对抗反例（本轮新增）

**反例 F（query 成功但 RecoveryRows approval 集合顺序/内容漂移 → 必须 risk closure）**

实现者覆盖了真实 DB 上 raw/index 漂移→`RECOVERY_RISK_CLOSURE_INVALID`，以及源码中的 `rows.approval_receipts != observed_approvals` 分支；**未**单独构造「两次公开读取均成功但 tuple 不等」的定向用例。

最小静态复现（未执行）：

1. 在已打开的 repository 事务内，monkeypatch `query_approval_receipts` 返回合法 `observed` tuple
2. monkeypatch `read_recovery_rows` 返回同内容但 **顺序颠倒** 或 **缺一 / 多一** 的 `approval_receipts`
3. 调用 `recover_repository_state(repo)`
4. 合同预期：`RECOVERY_RISK_CLOSURE_INVALID`（走 tuple mismatch→`_RiskRecoveryClosureError`），不得落入 `RECOVERY_LOCAL_INVALID`
5. 对照分支：同一设置下让 `read_recovery_rows` 在 **commands** 解码处抛 `ValueError`（approval tuple 仍 exact）→ 仍须 `RECOVERY_LOCAL_INVALID`

**反例 G（非法 planner identity 在构造期 fail-closed；默认调用不变）**

实现者证明了合法互异 hex planner；未显式测非法覆盖。

1. `_plan(..., planner_config_identity="not-a-hex64")`
2. 静态预期：`build_order_plan`→`_require_hex64("config_identity", ...)` 拒绝（`contracts.py`），不会生成弱 source map
3. 不传可选参的既有 `_plan(` 调用点仍保持 `planner==trading`，不静默改变历史等式

### 10.5 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite probe / 网络 / PAPER / broker / browser | **未运行** |
| Git commit | **未执行** |
| A1/A2/PAPER/Linux Gate / UA-M4-006/007 | **不声称** |
| 本结论 | **仅静态**；不得冒充授权运行验证 |

### 10.6 复验结论

**REVIEW_PASS**

无 P0/P1；F14–F17（含 F14 typeof 漏项）与任务书 §16 / 交付 §13 在源码与测试断言层面静态对齐；本轮未改 `risk_wire`/`service`/`approval_flow` 生产字节；既有 P2/P3/review E 进程内 authority 边界如实保留。

报告路径：`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`

## 11. REWORK4 复验报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）

`0c8e00f97d7b76fafe7d75e545623747db168e4a75263fde2af4cd7d82ea7053`

口径：对本文件「§11 标题行之前」全部 UTF-8 字节（含 §0–§9 历史与本轮 §10；**不含**本 §11 块）计算 SHA-256。
说明：文首结论行仍保留 REWORK2/3 历史表述（不改写 §0–§9 业务正文）；**本轮最新结论以 §10.6 `REVIEW_PASS` 为准**。本值于 DOC-WHITESPACE 行尾规范化后按实际标题边界重签；不再沿用「回填后正文指纹不变」旧口径。


## 12. REWORK5 / F19 静态复验（追加；不改写 §0–§11）

身份：M4-A2 F19 全新独立初验 Agent（未参与实现；STATIC_ONLY）<br>
依据：任务书 §17、交付报告 §14/§15、既有本报告；只读 exact17 实现/测试；唯一写入：本报告。<br>
约束：未运行 Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；未改实现/测试/任务/交付；未 commit。

### 12.1 F19 合同逐项证据

| # | 核对点 | 静态结论 | 证据 |
| --- | --- | --- | --- |
| 1 | `RecoveryError.__init__` 仅 `self.code=code` 后 `super().__init__(code)` | 通过 | `reconcile.py:89-91`；无额外校验/包装/默认码 |
| 2 | 全部构造点传稳定 str literal | 通过 | 六处：`RecoveryIssue`/`RecoveryResult`→`RECOVERY_RESULT_INVALID`；cancel/risk/local→`CANCEL_RECOVERY_CLOSURE_INVALID`/`RECOVERY_RISK_CLOSURE_INVALID`/`RECOVERY_LOCAL_INVALID`（含 `recover_local_state` 外层）；均字面量，无变量/拼接 |
| 3 | args/str/cause/context/脱敏零漂移 | 通过 | 既有 `raise RecoveryError("…") from None` 与 bare re-raise 未改码；`super().__init__(code)` 保持 `args[0]==str(error)==code`；定向测 `test_recovery_error_exposes_stable_code_without_context`：真实 hostile `payload=b"TOKEN"`→`RECOVERY_LOCAL_INVALID`；`code==args[0]==str`；`_assert_detached`；`TOKEN` 不进 `repr(args)`；两实例 `is not` 且 `first.code="MUTATED"` 不污染 `second` |
| 4 | 公共失败分类零漂移 | 通过 | `service.py:452-453` 仍 `ExecutionServiceError(error.code) from None`；CLI `_raise_service` 仍按 code 子串分类；错误码集合未增删 |
| 5 | `service.py` 本轮字节未改；mypy 缺口由类型合同关闭 | 通过 | 消费点只读；`service.py` mtime（约 17:33）早于本轮 `reconcile.py`/`test_reconcile.py`（约 18:41）；`RecoveryError` 现显式 `code: str` 属性，关闭 VALIDATION5 `attr-defined` 根因；本复验未跑 mypy |
| 6 | 范围 | 通过 | REWORK5 生产/测试触点仅 `reconcile.py` + `test_reconcile.py`；`ReconciliationError` 仍为空子类；未扩围 store/schema/migration/config/`__init__` |

### 12.2 发现分级（REWORK5）

### 无 P0 / P1

### 既有 [P2]/[P3] / review E（复核保留，非本轮新开）

进程内 capability authority 边界仍以 §3 / §8.3 / §10.3 为准。

### [P3] 外部改写 `.code` 后 `args`/`str` 仍保留构造期稳定码 — `src/quant/execution/reconcile.py`

实现者测了两实例隔离，但未断言**同一实例**在 `error.code = "MUTATED"` 之后：`error.args[0]` 与 `str(error)` 仍为原 `"RECOVERY_LOCAL_INVALID"`，而 `.code` 已分叉。这是 `BaseException.args` 与可变实例属性的诚实语义边界；生产 catch 点在抛出瞬间读 `.code`，不构成合同破坏，但若未来以 `str(error)` 与 `.code` 交叉验真需知悉可漂移。

### 12.3 实现者未使用的静态对抗反例（本轮新增）

**反例 H（同实例 `.code` 可变 vs `args`/`str` 冻结；见 §12.2 P3）**

最小静态复现（未执行）：

1. 经真实 hostile command 路径得到 `err = RecoveryError`（`code==args[0]==str=="RECOVERY_LOCAL_INVALID"`）
2. `err.code = "MUTATED"`
3. 预期：`err.code == "MUTATED"`，且 `err.args[0] == str(err) == "RECOVERY_LOCAL_INVALID"`
4. 规则：API 兼容性增强不保证事后属性与 `args` 持续耦合同步；service 公共分类以捕获时 `.code` 为准
5. 建议（非阻断）：定向测补一条同实例分叉断言，或文档化为 process-local 已知面

**反例 I（非 str 构造：项目内部不可达；注解-only 运行时边界）**

1. 六处生产构造均为 str literal → 内部不可达非 str
2. `RecoveryError.__init__` 无 `isinstance`/`_text` 运行时护栏（与任务“最窄 `__init__`”一致）
3. 外部若 `RecoveryError(b"TOKEN")` / `RecoveryError(object())`：`.code`/`args[0]` 可为非 str；与 `ExecutionServiceError(error.code)` 类型合同在运行时不对齐
4. 分级：**P3 诚实边界**（非 P0/P1）；typed 调用面由注解约束，不扩 runtime guard 符合 F19 最小面

### 12.4 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| SQLite probe / 网络 / PAPER / broker / browser | **未运行** |
| Git commit | **未执行** |
| A1/A2/PAPER/Linux Gate / UA-M4-006/007 | **不声称** |
| VALIDATION5 focused/Ruff 绿 | **不自动冒充**本轮最终通过 |
| 本结论 | **仅静态**；不得冒充授权 post-fix validation |

### 12.5 复验结论

**REVIEW_PASS**

无 P0/P1；F19 与任务书 §17 / 交付 §15 在源码与测试断言层面静态对齐；`RecoveryError` 为最窄兼容性增强；`service.py` 本轮未改且类型合同关闭 mypy 缺口；定向测走真实 hostile recovery、双实例独立且不泄漏 TOKEN。新增静态反例 H/I 为 P3 诚实边界。既有 P2/P3/review E 保留。

报告路径：`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`

## 13. REWORK5 复验报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）

`1d36c0c811c337482d4380d42f42cca43fad2e29db098fcd12a4b56c85e929d1`

