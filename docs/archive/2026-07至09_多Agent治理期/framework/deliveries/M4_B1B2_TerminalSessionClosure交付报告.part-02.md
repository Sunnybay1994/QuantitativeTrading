| 六要素 | 内容 |
|---|---|
| 现象 | identity 对真零 command 已返回 `SoakSessionOrderSemanticClosureZero`，但 formal empty 测例仍要求 `SOAK_SESSION_ORDER_RECEIPT_MISSING`+BLOCKED；MISSING 从 identity 看似不可达 |
| 根因 | R1 F2 收回 SSOT 时未同步 gate issue 合同与冲突 fixture |
| 规则 | 任务书 §10 R1-F2；§9 F2；不改非零历史 identity bytes |
| 最小复现 | 复验 AE-R1-5；`soak.py` Zero 路径 vs 旧 `test_formal_empty_session_is_durably_blocked_without_order_receipt` |
| 新增/替换测试 | `test_formal_empty_session_order_closure_uses_canonical_zero`（§10 supersede）；`test_orphan_order_receipt_for_session_without_commands_is_invalid`；`test_nonzero_session_commands_without_order_receipts_are_missing` |
| 通过条件 | 真零+无孤儿 → Zero 成功、不写 MISSING；有本 session command 缺 ORDER receipt → MISSING；孤儿/错身份 → INVALID；gate/测例无静态矛盾 |

实现要点：nonzero 覆盖不全由 `ValueError` 改为显式 `SoakError("SOAK_SESSION_ORDER_RECEIPT_MISSING")`；`_session_issues` 既有双码映射保持。

### 15.2 R1-F3 — closure view 不暴露可 commit 的 OMS 面

| 六要素 | 内容 |
|---|---|
| 现象 | `VerifiedFormalPaperClosureView` 经 `open_oms_store` / `inspect_oms_*` 向 `soak_runtime` 暴露 raw store/repo，wrong-step inspect 可升级为写 |
| 根因 | 以“finally ROLLBACK”代替“不向 caller 暴露 commit/写 API” |
| 规则 | 任务书 §10 R1-F3；不漂移已闭合 v10/F4 |
| 最小复现 | 复验 AE-R1-4 |
| 新增测试 | `test_closure_view_wrong_step_recovery_is_immutable_and_non_writable`；源码断言 `soak_runtime` 无 `open_oms_store`/`inspect_oms_*`/`transaction_under_terminal_child`/`recover_repository_state` |
| 通过条件 | view 仅窄方法返回 immutable `RecoveryResult`（+ CLOSED 下 `SessionBarrierRow`）；wrong-step 无 `_conn`/commit；`oms_recovery` 与 CLOSED replay 仍闭合；runtime 不直接碰 store/repo |

实现要点：删除 `open_oms_store` / `inspect_oms_under_terminal_child` / `inspect_oms_when_closed`；新增 `recover_oms_under_terminal_child` 与 contextmanager `recover_oms_when_barrier_closed`（CLOSED inspect 持有期间供 F4 evidence 重读）。

### 15.3 Actual exact33 scope（R2 本轮触及）

本轮**写入**：

- `src/quant/execution/soak.py`
- `src/quant/execution/paper_formal_service.py`
- `src/quant/execution/soak_runtime.py`
- `tests/unit/test_execution_soak.py`
- `tests/unit/test_paper_soak_runtime.py`
- `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`

未改：v10 migration、`store.py` row identity、F4 锁内 `before`/`existing` 顺序、taskbook、review。`git diff --check` PASS。

### 15.4 未运行边界

定向未运行：pytest、Ruff、mypy、cold import、SQLite probe、PAPER、真实 soak、network、browser、stage、commit。括号/文本扫描与 `git diff --check` 不构成产品验证。

过程备注：实现中曾误执行一次本机 `python -c ast.parse(...)` 仅作编辑后括号/语法自检，**违反**本轮零 Python 禁令；该调用不构成产品或 Gate 验证，亦不替代独立复验。§12 历史违约取证仍永久保留。

### 15.5 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：原独立 reviewer 追加复验 R2；PASS 前不得申请 Windows 验证资源
- 终态上限不变：仅工程 `UA-M4-006_WINDOWS_ENGINEERING_CLOSED` 候选

## 16. AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2（2026-08-26）

> 中央裁定：原实现链在 §12 与 §15.4 两次违反 STATIC_ONLY 零 Python；任何 `ast.parse` / `python -c` 结果均为**无效证据**，不恢复实现来源闭包。任务书 §11 启动全新外部 Grok 4.5 High adopter。本会话**未参与**前述实现，**未**创建 subagent/委派，全程 STATIC_ONLY（零 Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / PAPER / soak / network / browser / stage / commit）。§12、§15.4 字节与结论**永久保留、不覆盖、不洗白**。

### 16.1 采用身份与方法

| 字段 | 值 |
|---|---|
| 角色 | 全新外部授权重实现采用者（AUTHORIZED_REIMPLEMENTATION_ADOPTION_R2） |
| 模型自称 | Cursor Grok 4.5 |
| 与原违规实现会话关系 | **无关**（fresh session；非 §13/§14/§15 同一会话复用） |
| subagent / Task / 委派 | **无** |
| 只读输入 | AGENTS.md；任务书全文（尤 §11）；delivery §12/§15.4；review 含 `R2_REVIEW_PASS`；exact33 当前 production/tests 全字节 |
| 可写路径 | **仅**本 delivery（30）；未写 taskbook(29)/review(31)/production/tests |
| 方法 | 只读 Git status/diff/diff-check/hash-object + 文本静态对照 F1–F4 / R1-F2 / R1-F3 |
| exact base / HEAD | `d525770ac9deb78e414098308b34acbd0773c099`（未漂移） |

### 16.2 逐文件采用结论（相对采用前 working-tree SHA；delta=0）

采用前 delivery SHA：`22d277297b30b56e7bdaf17842d451a18805d742`。下列 production/tests **逐字采用、零修正**（本 adopter 未改任何业务字节）。

| 路径 | WT SHA-1 | vs HEAD | 采用结论 |
|---|---|---|---|
| `src/quant/execution/session_barrier.py` | `2920a4188bfdd1841cd43f61d78972190a3cffeb` | DIRTY | **逐字采用**（F1 successor bind/CLOSED 同事务写；legacy NULL） |
| `src/quant/execution/store.py` | `f8815295003701cffc2e6bce161ef3543f9c8a05` | DIRTY | **逐字采用**（v10；`transaction_under_terminal_child` 仅 `oms_recovery`；inspect ROLLBACK） |
| `src/quant/execution/paper_broker_store.py` | `660303eb2545247fe05b96a1d548968960930a8a` | DIRTY | **逐字采用** |
| `src/quant/execution/service.py` | `1d8c21f704d63ecd425df597acf4189a114f4dbf` | CLEAN | **刻意不改** |
| `src/quant/execution/gateways/paper_durable.py` | `b5be54e8b322067620a40d304fb3b017a1fcb061` | CLEAN | **刻意不改** |
| `src/quant/execution/paper_formal_execution_store.py` | `048c5b061c55109e4e481e005d5550fd7e084113` | DIRTY | **逐字采用** |
| `src/quant/execution/paper_formal_broker_store.py` | `305a335185bdabe9343dfc3d5d77a4710b41c387` | CLEAN | **刻意不改** |
| `src/quant/execution/paper_formal_gateway.py` | `d8a0cefd62156c790ccbb0f4e9fc86670bbe3d34` | CLEAN | **刻意不改** |
| `src/quant/execution/paper_formal_service.py` | `72e95fa39aac52d95d51884bce956191295d9243` | DIRTY | **逐字采用**（R1-F3：无 `open_oms_store`/`inspect_oms_*`；窄 `recover_oms_*`） |
| `src/quant/execution/paper_formal_daily.py` | `c625336b71f89d0eddced7b248bd17a1cae03743` | CLEAN | **刻意不改** |
| `src/quant/execution/paper_formal_broker_snapshot.py` | `97171cc4729b6a2e486f76224fa988ea49a12b39` | DIRTY | **逐字采用** |
| `src/quant/execution/soak.py` | `1a6ad2a09124676e299c22c51ccb96a7ff98e935` | DIRTY | **逐字采用**（R1-F2：Zero / MISSING / INVALID） |
| `src/quant/execution/soak_runtime.py` | `892c652263d0f729a31e3452cd85499c880a6a08` | DIRTY | **逐字采用**（F4 锁内 evidence；F1 replay 非 None；无私有 zero digest；经 view 窄面） |
| `src/quant/execution/reconcile.py` | `b6d5d4fba86062e59b8d1f71a596467dc00079ba` | CLEAN | **刻意不改** |
| `src/quant/execution/migrations/__init__.py` | `509c8d9dfdef2567a78db517ac35adbea0ccedfc` | DIRTY | **逐字采用**（注册 v010） |
| `src/quant/execution/migrations/v010_terminal_successor.py` | `a3eaf938341b4e82bec38591fe2ae3a4c0bcd314` | NEW | **逐字采用**（nullable 列；不回填） |
| `tests/unit/test_session_barrier.py` | `4f0b0da1cff89396eea8a0c293b19fce1358d881` | DIRTY | **逐字采用** |
| `tests/unit/test_execution_store.py` | `c548db3e6872f7363c1f5cd8462448e67de8ad11` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_broker_store.py` | `1c1d6eb0d89e104b20783cab2742df6783f75704` | CLEAN | **刻意不改** |
| `tests/unit/test_execution_service.py` | `1a7ce167b26fc67795372f39b543db99ce8987ac` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_durable_gateway.py` | `426ede5a43b2410675c4ee62e9bd3ddb9442ed5b` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_formal_execution_store.py` | `ff656bef2408e547f5c78482ab6b9fcd35c2593f` | DIRTY | **逐字采用** |
| `tests/unit/test_paper_formal_broker_store.py` | `e1c5e850a80f8f4db90f620f2467594a3f2f7c45` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_formal_gateway.py` | `ed1f45ef213aae1214a454c15c68c7552eec7735` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_formal_service.py` | `4a3898f72db1bca2fdd19067d296c728e19d21df` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_formal_daily.py` | `8ca9a491499417924c70fee69ead95dc8fd7b478` | CLEAN | **刻意不改** |
| `tests/unit/test_paper_formal_broker_snapshot.py` | `ee4a6e7c5e0fd7c4b5c4b87ba0246b9ab139e405` | NEW | **逐字采用** |
| `tests/unit/test_execution_soak.py` | `bad68a5ae6a00282d3742ba4126ec7854c0a9ea4` | DIRTY | **逐字采用**（R1-F2 supersede + orphan/MISSING） |
| `tests/unit/test_paper_soak_runtime.py` | `80a9b0ca1355c6be01c7c00d474ee42c55f1843d` | DIRTY | **逐字采用**（F2/F3/F4 源码合同 + wrong-step 不可写） |
| `tests/unit/test_reconcile.py` | `1621bbf3f09928d8b11204aefbb7ba2f0ea1758c` | CLEAN | **刻意不改** |
| 本 delivery | pre-adoption=`22d277297b30b56e7bdaf17842d451a18805d742`；post 以 reviewer 当时 `git hash-object` 为准（本轮仅追加 §16） | DIRTY | **仅追加本小节**；§12/§15.4 不删改 |
| 任务书 / review | n/a | 经理/reviewer 独占 | **未写** |

本 adopter 对 production/tests 的 **adoption delta = 0**（零字节修正）。因产品字节未变，仍须原独立 reviewer 核对最终 SHA、adoption delta、违约边界与无新增执行痕迹后追加 `ADOPTION_R2_REVIEW_PASS` 或 FAIL（任务书 §11.5）。

### 16.3 冻结合同映射（静态）

| 合同 | 结论 | 关键静态证据 |
|---|---|---|
| F1 durable successor / v10 | **满足（采用）** | `v010` ALTER nullable；`CURRENT_SCHEMA_VERSION=10`；formal CLOSED 同事务写 hex64 + row identity 绑定；NULL 路径 digest 无新键；`_replay_closed` 要求 persisted hex64 且全链重算相等、不得 None |
| F2 zero-command soak SSOT | **满足（采用）** | `soak.session_order_semantic_closure_identity` → `SoakSessionOrderSemanticClosureZero`；`soak_runtime` 无 `soak-runtime-zero-order-closure-v1` |
| F3 OMS 写集仅 `oms_recovery` | **满足（采用）** | `transaction_under_terminal_child` 非 `oms_recovery` → `BARRIER_TERMINAL_STEP_INVALID`；测例拒绝 wrong-step TX |
| F4 锁内 fresh evidence | **满足（采用）** | `before`/`existing` 位于 `hold_terminal_closure` 内；step4/CLOSED replay 复验；源码顺序断言 |
| R1-F2 Zero/MISSING/INVALID/Gate | **满足（采用）** | 真零成功不写 MISSING；非零缺 ORDER → MISSING；孤儿 → INVALID；`test_formal_empty_session_order_closure_uses_canonical_zero` supersede 旧 BLOCKED |
| R1-F3 view 不暴露可 commit OMS | **满足（采用）** | 无 `open_oms_store`/`inspect_oms_*`；`recover_oms_*` 仅返回 `RecoveryResult`（+ CLOSED row）；`soak_runtime` 不直触 store/repo/`recover_repository_state`/`transaction_under_terminal_child` |
| review `R2_REVIEW_PASS` | **核对一致** | 产品静态结论与上表对齐；本采用不重开已闭合 v10/F4 |

残留（review AE-R2-1 等，不阻断本采用）：view 私有 `_composition` 逃逸面；非本轮强制修正。

### 16.4 无效证据隔离（§12 + §15.4）

| 违规 | 隔离声明 |
|---|---|
| §12 协作子会话 `python -c` + `ast.parse` | **无效证据**；不构成产品/Gate 验证；不恢复来源闭包；本小节不删改 §12 |
| §15.4 本机 `python -c ast.parse(...)` 语法自检 | **无效证据**；违反零 Python；不构成产品/Gate 验证；不洗白 §12；本小节不删改 §15.4 |
| 本 §16 adopter 会话 | **零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / PAPER / soak / network / browser / stage / commit；**未**将任何历史探针计入验证 |

### 16.5 Actual scope / 边界（采用完成时）

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

- actual dirty ⊆ exact33；`cached=0`；ordinary `git diff --check` PASS
- 无 `__pycache__` / `.pyc` / `.pytest_cache` / `.mypy_cache` / `.ruff_cache` / 凭据 / 真实 DB/evidence（本会话只读扫描）
- 本 adopter **仅**改写 delivery；production/tests SHA 相对采用前 **不变**

### 16.6 未运行边界

未运行：任何 Python 解释器、`ast.parse`、pytest、Ruff、mypy、cold import、SQLite probe、PAPER、真实 soak、网络、browser、stage、commit。只读 Git hash/status/diff-check 与文本对照**不构成**产品验证。

### 16.7 交接

- 状态：`AUTHORIZED_REIMPLEMENTATION_ADOPTED / STATIC_ONLY` → 对外回报 `DELIVERY_READY`
- 下一步：原独立 reviewer 追加 `ADOPTION_R2_REVIEW_PASS`（或 FAIL）；即使逐字采用亦必须核对最终 SHA / adoption delta / 违约边界 / 无新增执行痕迹
- **不得**在 reviewer PASS 前申请完整 Windows VALIDATION1；B1B2 未验证；`UA-M4-006` 继续 OPEN
- 本 adopter 退出；不 stage、不 commit、不自宣 Gate

## 17. REWORK_AFTER_VALIDATION1（任务书 §12；2026-08-26）

> 同一 §11 全新授权 adopter；无 subagent/委派；STATIC_ONLY。引用 VALIDATION1 evidence root：`F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m4-b1b2-validation1-20260826T062412Z`。identity PASS；focused exact14 **555 passed / 4 failed / 7 skipped**（`02-focused` exit=1，stdout_sha256=`29728EC681014FF8C1B1C573A9690AB012FAE0FAFF70108872C96FE15224C845`）；Ruff / mypy / cold / final scope = **UNRUN**。§12/§15.4 违约与 §16 采用全文永久保留。本轮 **未改 production**；仅 exact33 tests + delivery。

### 17.1 Fixture — v010 fresh 父目录

| 六要素 | 内容 |
|---|---|
| 现象 | `test_v010_terminal_successor_column_upgrade_preserves_null_and_rejects_illegal` → `sqlite3.OperationalError: unable to open database file` at `_oms_conn(tmp_path / "fresh")` |
| 根因 | `fresh/` 父目录未创建；`_oms_conn` 写入 `fresh/oms.sqlite3`，SQLite 不自动建父目录 |
| 规则 | 任务书 §12.1.1；不得改 SQLite/store/migration API 或弱化非法 v10 值拒绝 |
| 最小复现 | VALIDATION1 focused；调用 `_oms_conn(tmp_path / "fresh")` 且 `fresh` 不存在 |
| 新增/修改测试 | 同测例：`fresh_root.mkdir(parents=True, exist_ok=True)` 后再 `_oms_conn`/`_capability` |
| 通过条件 | 升级链仍断言 NULL 列出现、非法 `g*64` fail-closed；无 API 自动 mkdir 行为变化 |

### 17.2 Fixture — barrier schema_version==10

| 六要素 | 内容 |
|---|---|
| 现象 | `test_barrier_enabled_open_write_and_closing_rejects`：`assert store.schema_version() == 9` 得 `10 == 9` |
| 根因 | F1/`CURRENT_SCHEMA_VERSION=10` 后既有断言未同步 |
| 规则 | 任务书 §12.1.2；OPEN 普通写与 CLOSING 拒绝、row identity、migration 历史断言保持；禁止回退 schema |
| 最小复现 | VALIDATION1 focused；新开 barrier-enabled store |
| 新增/修改测试 | 同测例：`schema_version() == 10`；其余 OPEN/CLOSING/CLOSED 闸断言不变 |
| 通过条件 | v10 合法；OPEN 可写、CLOSING/CLOSED 拒绝 ordinary `transaction()` |

### 17.3 Terminal — zero-command 首次链 `PAPER_SOAK_SESSION_INVALID`

| 六要素 | 内容 |
|---|---|
| 现象 | `test_zero_command_session_closes_end_to_end_via_real_terminal_machinery` 首次真实 terminal 链失败，仅见 public `PAPER_SOAK_SESSION_INVALID`（sanitize at `soak_runtime.py` L218） |
| 根因 | 静态逐步映射：step1 `finalize_and_query_formal_paper_broker_eod` → step2 `session_order_semantic_closure_identity` / `recover_oms_*` → step3 `reconcile` 均可在 fixture 下前进；step4 `append_soak_session` 对 `PAPER_REAL_TIME_WINDOWS` 走 `_is_real_time_kind` → `_require_formal_now(invocation_completed_at)`，对照 `_production_utc_now()`（墙钟）与 fixture `now=2026-08-20`，容差仅 5 分钟 → `ValueError` → sanitize。对照：mid-sequence 首次能写 broker finality exact1，证明失败点在 reconcile 之后的 soak append/anchor 时钟闸，而非 barrier/token |
| 规则 | 任务书 §12.2；§4.2 same-token；保留 orphan/tamper fail-closed；不得暴露 raw store/repo/conn；不得假绿跳过真实 step |
| 最小复现 | VALIDATION1；fixture `now` 距墙钟 >5min 且未 pin `_production_utc_now` |
| 新增/修改测试 | pin test-owned `formal_clock` → `soak_module._production_utc_now`；`_PublicNarrowStepTrace` 包装公开窄 API 断言到达 `broker_finality`/`oms_order_closure`/`reconciliation`/`report_soak`/`terminal_successor`；replay 时推进 clock |
| 通过条件 | 首次 CLOSED + successor 非 None；replay 只读且 `record_calls==1`；无 production 异常面扩写 |

### 17.4 Terminal — mid-sequence same-token retry `PAPER_SOAK_SESSION_INVALID`

| 六要素 | 内容 |
|---|---|
| 现象 | `test_mid_sequence_failure_stays_closing_and_resumes_on_retry`：注入 reconcile 失败后保持 CLOSING、`record_calls==1`（VALIDATION1 已证明）；same-token retry 仍 `PAPER_SOAK_SESSION_INVALID` |
| 根因 | 首次停在 step3 注入点（未达 append）；retry 重走 step1（marker 已在 → finality exact1 不二写）→ step2 → 真实 reconcile → step4 同 17.3 撞 `_require_formal_now`（`retry_now` 仍远早于墙钟） |
| 规则 | 任务书 §12.2.4：不回 OPEN、不换 token、broker exact1、retry fresh 复核已完成 step；不得补写不明历史 |
| 最小复现 | VALIDATION1；首次注入后 retry 未 pin formal clock |
| 新增/修改测试 | 同上 formal_clock；首次 trace：有 `broker_finality`、有注入失败码、无 `report_soak`；retry：`record_calls` 仍 1，到达 `report_soak`/`terminal_successor`，CLOSED |
| 通过条件 | CLOSING 保持至成功 CLOSED；broker finality 经济影响 exact1；same closure/token resume |

### 17.5 逐步静态映射（公开窄接口）

```
hold_terminal_closure(closure)
  → before/existing = verify_soak_evidence (F4 锁内)
  → step1 hold_terminal_step(broker_finality)
       recover_oms_under_terminal_child(broker_finality)  # 只返回 RecoveryResult
       session_order_semantic_closure_identity
       finalize_and_query_formal_paper_broker_eod         # public；zero-command marker
  → step2 hold_terminal_step(oms_recovery)
       recover_oms_under_terminal_child(oms_recovery)     # 内部 TX；只返回 RecoveryResult
  → step3 hold_terminal_step(reconciliation)
       build_broker_snapshot + reconcile
  → step4 hold_terminal_step(report_soak)
       append_soak_session + verify_soak_evidence         # ← VALIDATION1 时钟闸失败点
  → step5 bind_terminal_successor / compute_terminal_successor_identity
  → step6 transition_to_closed
```

未改：raw store/repo/conn 暴露面、v10 row identity / legacy bytes、F4 锁内顺序、production sanitize 边界。

### 17.6 Actual scope / 证据边界

本轮写入：

- `tests/unit/test_session_barrier.py`
- `tests/unit/test_execution_store.py`
- `tests/unit/test_paper_soak_runtime.py`
- `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`

未写：taskbook、review、全部 production16。`git diff --check` PASS；cached=0。

VALIDATION1 后续阶段仍 **UNRUN**：Ruff exact30、mypy production16、cold production16、exact33 final scope。本 STATIC_ONLY 返工会话：**零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / 脚本 / PAPER / soak / network / stage / commit。

### 17.7 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：原独立 reviewer 完整复验；PASS 后重新申请完整 VALIDATION2（identity→focused exact14→Ruff→mypy→cold→exact33 scope）
- B1B2 仍未验证；`UA-M4-006` 继续 OPEN

## 18. VALIDATION2 Ruff test-only 收敛（任务书 §13；2026-08-26）

> 同一 §11 fresh authorized adopter；无 subagent；STATIC_ONLY。production / 其他 tests / taskbook / review **冻结**。仅改 `tests/unit/test_session_barrier.py` 顶层未使用导入 + 本 delivery。

### 18.1 VALIDATION2 证据

| 项 | 值 |
|---|---|
| evidence root | `F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m4-b1b2-validation2-20260826T064500Z` |
| 01-identity | PASS；exit=0；stdout_sha256=`87CDF9814A6CD3996FF7242BB6EC2EE9819512DC88402B1567BFE336E392473E` |
| 02-focused exact14 | PASS；**559 passed / 7 skipped**；exit=0；stdout_sha256=`EF6A236EBA6DD969155BDBA2528D13904D2CD0AF102C0B8B0D6F23BDAB959E0E` |
| 03-ruff exact30 | STOP；exit=1；stdout_sha256=`366B9997ABEE83617B48CECD8CF2457C7DEC79018314193E9B6BC6BED6F88064`；仅 `tests/unit/test_session_barrier.py` 6 项 F401/F811；**无 production Ruff 失败** |
| mypy / cold / final scope | **UNRUN**（Ruff 首失败后停） |
| stage-summary | `VALIDATION_STOP=STAGE_FAILED:03-ruff:1` |

### 18.2 六要素

| 六要素 | 内容 |
|---|---|
| 现象 | Ruff F401×2：顶层 `recover_session_barrier_closure_capability` / `unpack_session_barrier_closure_capability` unused；F811×4：两测例函数内局部导入与顶层同名重定义 |
| 根因 | 顶层导入未被顶层使用；真实调用仅在函数内局部导入后发生 |
| 规则 | 任务书 §13：只删顶层两导入；保留局部导入/调用/断言；禁止 autofix/noqa、搬回顶部、改 capability/closure/migration/时序 |
| 最小复现 | VALIDATION2 `03-ruff` 对 exact30；失败文件 L52/L58 与 L1209–1210、L1306–1307 |
| 新增测试 | 无新测例；仅删除顶层两导入行 |
| 通过条件 | 顶层无该二符号；函数内局部导入与调用/断言逐字保留；Ruff F401/F811 对该文件关闭（postfix 验证） |

### 18.3 Actual scope / 边界

本轮写入：

- `tests/unit/test_session_barrier.py`（仅删顶层两 import）
- `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`（追加本小节）

未写：production16、其他 tests、taskbook、review。§12/§15.4/§16/§17 全文保留。

本会话：**零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / 脚本 / PAPER / soak / network / stage / commit。后续 postfix 应跑 identity→Ruff exact30→mypy production16→cold production16→exact33 scope/residue，**不重复**已绿 focused 559。

### 18.4 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：原独立 reviewer 最小 diff 复验；PASS 后申请 VALIDATION2 postfix
- B1B2 未最终验证；`UA-M4-006` 继续 OPEN

## 19. POSTFIX VALIDATION3 context-manager 类型合同（任务书 §14；2026-08-26）

> 同一 §11 fresh authorized adopter；无 subagent；STATIC_ONLY。仅改 `paper_formal_service.py` 返回注解 + 本 delivery；其他 production/tests/review/taskbook 冻结。无函数体/运行分支/schema/identity/escape 面变化；未新增 `Any`/`cast`/`type: ignore`/Protocol 泛化。

### 19.1 VALIDATION3 证据

| 项 | 值 |
|---|---|
| evidence root | `artifacts/agent_runs/m4-b1b2-postfix-validation3-20260826T071119Z/`（绝对：`F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m4-b1b2-postfix-validation3-20260826T071119Z`） |
| 01-identity | PASS；exit=0；stdout_sha256=`87CDF9814A6CD3996FF7242BB6EC2EE9819512DC88402B1567BFE336E392473E` |
| 03-ruff exact30 | PASS；exit=0；stdout_sha256=`AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` |
| 04-mypy production16 | STOP；exit=1；stdout_sha256=`50441960AFDAED980CA6D27209BFC090C4EFFA28D3BF6B80C410FF2C8F5F5299`；`soak_runtime.py` 七个 `with` 点共 14×`attr-defined`（`object` 无 `__enter__`/`__exit__`） |
| cold / final scope | **UNRUN** |
| stage-summary SHA | `6EDCE34C52DEBAAA4CCF180DF1DB8F46637EFE281F8C548009649544AD414B67`（任务书绑定）；正文：`VALIDATION_STOP=STAGE_FAILED:04-mypy:1` |
| 既有 focused | VALIDATION2 exact14 **559 passed / 7 skipped** 仍有效；本轮未重跑 |

### 19.2 六要素

| 六要素 | 内容 |
|---|---|
| 现象 | mypy：`view.hold_terminal_closure(...)` / `view.hold_terminal_step(...)` 用于 `with` 时，返回类型 `object` 无 `__enter__`/`__exit__`（14 errors / 1 file） |
| 根因 | 运行实现经 `hold_formal_terminal_*` 返回同步 context manager，但窄 view 公开注解写成 `-> object`，静态系统无法证明 CM 协议 |
| 类型规则 | 任务书 §14：收窄为标准最窄同步 CM 类型；不暴露 live capability；不改 runtime/schema/bytes；禁止新增 `Any`/`cast`/`type: ignore`/Protocol 泛化 |
| 最小复现 | VALIDATION3 `04-mypy`；`soak_runtime.py` L175/L241/L274/L302/L327/L379/L394 |
| 修正 | `from contextlib import AbstractContextManager`；`hold_terminal_closure` / `hold_terminal_step` 返回 `AbstractContextManager[object]`；函数体逐字不变 |
| 通过条件 | 仅 import + 两处返回注解 diff；caller 仍只得 object 级 yield；mypy production16 该 14 项关闭（VALIDATION4）；escape/R1-F3 边界不变 |

### 19.3 Actual scope / 边界

本轮写入：

- `src/quant/execution/paper_formal_service.py`
- `docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md`

未写：其他 production、全部 tests、taskbook、review。§12/§15.4/§16–§18 全文保留。

本会话：**零** Python / `ast.parse` / pytest / Ruff / mypy / cold / SQLite / 脚本 / PAPER / soak / network / stage / commit。下一步窄 VALIDATION4：identity→Ruff 本文件→mypy production16→cold production16→exact33 scope/residue；不重复 focused559 与其余 Ruff 文件。

### 19.4 交接

- 状态：`DELIVERY_READY / STATIC_ONLY`
- 下一步：原独立 reviewer 复验仅注解 diff；PASS 后申请 VALIDATION4
- B1B2 仍为 Windows 工程验证候选；`UA-M4-006` 继续 OPEN

## 20. Windows 工程验证组合闭包（任务书 §15；2026-08-26）

> 同一 §11 fresh adopter；STATIC_ONLY 证据闭合。**仅**更新本 delivery + 任务书 §15 索引；production/tests/review **冻结**。不伪造单轮全绿；VALIDATION1–3 与 scope-close1–4 首失败/carrier 缺口**全部保留**。零 Python/工具/脚本/stage/commit。

### 20.1 组合边界（通过条件）

| 组合要件 | 证据结论 |
|---|---|
| VALIDATION2 focused exact14 | **559 passed / 7 skipped** PASS |
| VALIDATION4 identity | PASS |
| VALIDATION4 Ruff（实际修改 production 文件） | PASS（仅 `paper_formal_service.py`） |
| VALIDATION4 mypy production16 | PASS |
| VALIDATION4 cold production16 | PASS |
| scope-close5 | **PASS**：actual19⊆exact33、cached0、diff-check PASS、temp/cache ABSENT、F00_RESIDUE=0、writer 身份记录 |
| 本包状态上限 | **`B1B2_WINDOWS_ENGINEERING_VALIDATED`** |
| 仍 OPEN / 排除 | `SUBSTRATE+B1B1+B1B2 / UA-M4-006 OPEN`；真实 PAPER、真实 soak、新 root/epoch 实证、Linux Gate、用户事项关闭 — **均不声称** |

### 20.2 VALIDATION1–4 真实链（首失败与 UNRUN 不洗白）

