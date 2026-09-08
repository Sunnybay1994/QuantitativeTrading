# M4-UA006-P2 Rebuilt Formal Broker Materialization Identity Compatibility 交付报告

日期：2026-08-26
状态：`P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`（§11 组合证据闭合；§1–§10 历史 STATIC/返工原文保留；**不等于** `FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED` / UA-M4-006 / PAPER / bootstrap / soak / Linux Gate）
task id：`M4-UA006-P2-REBUILT-FORMAL-BROKER-MATERIALIZATION-IDENTITY-COMPAT`
exact base / HEAD：`6097670de3c7f2b1f414580b429facb8d99b67a4`
branch：`codex/m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
角色：实现所有权续任（本轮 `EVIDENCE_UPDATE_ONLY`：只写任务书 + 本 delivery；production / tests / review **冻结只读**）

## 1. 现象—根因—应遵循规则—最小复现—新增测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | 真实 public `initialize_verified_formal_paper_broker_store` 在首次合法 broker root materialization 时，于正式 store bytes 前失败，空 root 被回滚，错误码 `PAPER_FORMAL_STORE_STALE` |
| 根因 | absent→materialized 必然改变 environment verification/layout/root identity；`paper_policy._identity_payload` 把 environment verification 纳入 `policy_identity`；旧 `_compare_cold_materialized` 经 `_policy_business`（含 `policy_identity`）与 `_binding_business`（含 `execution_policy_identity`）要求跨物化恒等，合法首次物化被误判 STALE |
| 应遵循规则 | cold→materialized 只比窄经济投影；environment/layout/root 及派生 attestation 必须变化且最终 capability 仍完整绑定 materialized fresh identity；materialized→fresh reopen 与 final verify 保持逐字段完整；保留已合流 P1 `paper_execution_cost_schedule_identity`；不得改错误码/schema/migration/SQLite/rollback |
| 最小复现 | 真实 public cold 链（absent broker）→ initializer 创建 root → 重建 materialized 链 → 旧比较因 `policy_identity` 变化抛 STALE 并回滚空 root |
| 新增/强化测试 | 见 §3：真实 public 正向（观察 identity 变化）、无 cold 泄漏、经济漂移、layout/verification 未变、cross-session/account/root、preexisting/partial/symlink/separation、多失败点回滚、loader wrapper、legacy 错误码、P1 canonical 成本身份正/反向 |
| 通过条件 | STATIC dirty ⊆ exact5；cached=0；`git diff --check` PASS；无 runtime/SQLite/cache/temp/凭据；独立 REVIEW_PASS 后由中央跑 Windows 验证 |

## 2. 旧 STOP 与 P1 前置

- 旧 P2（base `1d9b4e09…`）未合流事故现场仅作只读设计参考；本包从 clean base `6097670…` 独立实现，未机械复制 placeholder/dirty 字节。
- 旧 DIAGNOSTIC1（broker-local `_digest(_cost_payload(...))` 拒真实 policy）已由 M4-P1 合流：唯一 public 成本身份为 `paper_execution_cost_schedule_identity`。
- 本包保留该闭包：fixture/descriptor 正向消费 canonical；legacy broker-local digest 继续拒绝；禁止恢复旧 digest 为 formal 成本身份。

## 3. 实现摘要（exact scope）

### 3.1 Production

`src/quant/execution/paper_formal_broker_store.py`

- `_compare_cold_materialized` 改为 `_policy_economic` / `_binding_economic` / `_account_economic`。
- 仍要求 config 相等，且 verification_identity、layout_identity、broker root identity **必须变化**。
- `_policy_economic`：selector/session/source identities/raw SHA/trading/cost/markets/notionals/规则版本；**排除** `policy_identity`。
- `_binding_economic`：classification/session/runtime_config_identity/规则/cost/fx；**排除** `runtime_environment_identity` / `execution_policy_identity` / `binding_identity`。
- `_account_economic`：经济字段含 `source_parent_identity`；**排除** env/policy/binding 派生 attestation。
- `_compare_materialized` / `_policy_business`（仍含 `policy_identity`）不变 → materialized→fresh reopen 行为不变。
- 未改：错误码、schema、migration、SQLite、descriptor bytes、transaction、barrier、rollback ownership、capability 字段闭包、public loader/verifier 调用序、P1 成本身份消费路径。

### 3.2 Tests

`tests/unit/test_paper_formal_broker_store.py`

| 任务书 §6 | 测试 |
| --- | --- |
| 1 真实 public、identity 变化、initializer 成功 | `test_public_chain_cold_materialization_changes_identity_and_returns_fresh_capability` |
| 2 最终 capability 绑定新链、cold 不泄漏 | `test_public_chain_final_capability_does_not_reuse_cold_objects` |
| 3 经济字段漂移拒绝 | `test_economic_policy_drift_rejects_cold_materialization`、`test_economic_binding_cost_drift_rejects_cold_materialization`、`test_economic_account_descriptor_drift_rejects_cold_materialization` |
| 4 env 未变 / 错 root / cross-session/account | `test_unchanged_layout_identity_across_materialization_is_rejected`、`test_cross_session_and_cross_account_capability_are_rejected` |
| 5 preexisting / partial / symlink / separation | `test_preexisting_broker_root_and_separation_conflict_fail_closed`、`test_partial_sibling_and_symlink_broker_root_fail_closed`（child 目录显式 mkdir） |
| 6 多失败点回滚 / unknown WAL 不删 | `test_compare_failure_before_store_bytes_rolls_back_empty_root`、`test_rollback_preserves_unknown_wal_after_formal_bytes`、既有 `test_failed_initialization_removes_only_owned_empty_root` |
| 7 wrapper / 错类型 / 旧对象 | `test_public_loader_wrappers_and_wrong_return_types_fail_closed` |
| 8 legacy 正向与错误码不漂移 | `test_legacy_initializer_open_verify_error_codes_do_not_drift` + 既有 initializer/open/verify |
| 9 P1 canonical 成本身份 | `test_canonical_cost_identity_positive_on_formal_descriptor`、`test_legacy_broker_local_cost_identity_rejected_by_formal_descriptor`；public 正向亦断言 canonical |

project 布局：public 链使用真实 `_actual_project_root()` 与调用方显式合法 paper-parent；仅对 `_system_temp_root` 做既有测试模式隔离，**不** patch `_actual_project_root` / layout guard。Windows 验证 basetemp 须同卷、project 外、非 system-temp、new no-clobber。

### 3.3 Diff 统计（未 stage）

| 路径 | 角色 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | production |
| `tests/unit/test_paper_formal_broker_store.py` | test |
| `docs/framework/deliveries/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility交付报告.md` | delivery |
| `docs/framework/tasks/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility任务书.md` | 经理既有 untracked（实现者只读） |

## 4. STATIC_ONLY 未运行边界

本轮**强制**零：Python 解释器业务探测、pytest、Ruff、mypy、cold import、SQLite probe、真实 PAPER、network/browser、stage/commit。

正式 Windows 验证与 bootstrap **仍 STOP / 未申请**；本交付不宣称产品绿，也不关闭 UA-M4-006。

## 5. STOP

无 CONTRACT_STOP。exact5 足够；未扩写 policy/account/binding/runtime/bootstrap/schema/migration/store/barrier；未删除最终 fresh identity；未复用 cold/stale 对象；未放宽错误码；未倒退 P1 成本身份。

## 6. 静态退出核对

- HEAD == exact base `6097670de3c7f2b1f414580b429facb8d99b67a4`
- cached=0；`git diff --check` PASS（见实现现场）
- dirty ⊆ exact5（实现写 1/2/4；任务书为经理既有 untracked）
- 无验证拉起的 runtime root / SQLite / cache / 临时文件 / 凭据

## 7. 退出声明

**`DELIVERY_READY`**（首轮；历史保留）

下一步：另一全新独立 reviewer 只读 production/test/delivery 并唯一写 review；重点挑战经济投影误删经济字段、final capability 仍绑 cold environment、或 P1 成本身份倒退。`REVIEW_PASS` 后申请 Windows：identity → `test_paper_formal_broker_store.py` → Ruff source/test → mypy source → cold source → exact5 scope/diff/temp/process。

---

## 8. STATIC_REWORK（P1×2-P2；中央授权；REVIEW_FAIL 后）

日期：2026-08-26
状态：`DELIVERY_READY`（STATIC_REWORK；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network；review 只读未改）
授权：`[STATIC_REWORK_AUTHORIZED][M4-UA006-P2-REBUILT][P1x2-P2]`
审查来源：`docs/framework/reviews/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility独立初验报告.md`（`REVIEW_FAIL`）

### 8.1 REVIEW_FAIL 发现（不洗白）

| ID | 现象摘要 |
| --- | --- |
| P1-1 | 无 materialized 内 join / 派生 attestation 相对 cold 必变；AE-1 可混绑 |
| P1-2 | mkdir 后未 `_require_materialized`；另一 `absent-*` 可通过（AE-2） |
| P2-1 | 经济投影缺 schema_version / account `runtime_config_identity` / exact source_path·trading_config·schedule |
| P2-2 | 缺 AE-1/AE-2；经济漂移面偏窄 |

### 8.2 六段返工证据

| 项 | 内容 |
| --- | --- |
| 现象 | 见 §8.1；敌意窄 loader 可在 store bytes 前绕过物化语义或跨对象身份闭合 |
| 根因 | 经济收窄后闸门不完整；比较器用 broker 字符串不等代替物化在场原语 |
| 应遵循规则 | 任务书 §4/§5/§9；中央返工条 1–5；既有 `_require_materialized`；保留 P1 canonical cost 与 `_compare_materialized` |
| 最小复现 | AE-1 复用 cold policy/binding/account；AE-2 替换为另一 `absent-*`；各 join 字段单独失配 |
| 新增/强化测试 | `test_ae1_new_env_reusing_cold_policy_binding_account_is_rejected`、`test_ae1_patched_env_text_keeps_cold_execution_policy_identity_rejected`、`test_ae2_alternate_absent_broker_identity_is_rejected`、`test_materialized_chain_join_or_derived_freshness_mismatch_rejected`（10 join/派生）、扩展 policy/binding/account 经济与 schema/source/config 漂移、`test_final_capability_binds_fresh_materialized_identities_not_cold`；诚实 public 正向保留；fixture 使 materialized policy/binding/account 派生身份相对 cold 变化并 join 闭合 |
| 通过条件 | STATIC dirty⊆exact5；cached=0；`git diff --check` PASS；无 runtime/SQLite/temp/凭据；独立复验 PASS 前不申请 Windows |

### 8.3 Production 差分（本轮）

`src/quant/execution/paper_formal_broker_store.py`

- initialize：materialized 链组装后、store bytes 前调用 `_require_materialized(materialized.environment)`。
- `_compare_cold_materialized`：去掉自造 broker 字符串不等启发式；保留 config 相等与 verification/layout 必变 + 经济投影；末尾调用 `_require_materialized_chain_closure`。
- 新增 `_require_materialized_chain_closure`：binding/account↔env/policy/binding join；`policy_identity`/`binding_identity`/`account.verification_identity` 相对 cold 必变。
- `_policy_economic` / `_binding_economic` / `_account_economic`：补 `schema_version`、exact `source_path`/`trading_config`/`execution_cost_schedule`、account `runtime_config_identity` 等；仍排除 env 派生身份、`verified_at`、私有 attestation；继续消费 canonical `cost_schedule_identity`。
- `_compare_materialized` / `_policy_business`（含 `policy_identity`）**未改**。
- 未改错误码集合、rollback ownership、schema/migration/SQLite、capability 组装仍走 final reload。

### 8.4 错误码与回滚边界（锁定）

| 场景 | 期望码 | 空 root |
| --- | --- | --- |
| AE-2 / cold env 当作 materialized（absent broker） | `PAPER_FORMAL_STORE_NOT_FOUND`（既有 `_require_materialized`） | 回滚 |
| AE-1 / join 失配 / 经济漂移 / layout·verification 未变 | `PAPER_FORMAL_STORE_STALE` | 回滚 |
| formal bytes 后 unknown WAL | `PAPER_FORMAL_STORE_ROLLBACK_REQUIRED` | 保留 |

### 8.5 STATIC 边界与写集

| 路径 | 本轮 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | 返工 |
| `tests/unit/test_paper_formal_broker_store.py` | 返工 |
| 本 delivery | 追加 §8 |
| 任务书 | 追加 §9（授权） |
| review | **只读未改** |

零 Python / pytest / Ruff / mypy / cold / SQLite / network / stage / commit / PAPER。

### 8.6 退出

**`DELIVERY_READY`**（STATIC_REWORK P1×2-P2）

下一步：另一全新独立 reviewer 复验；重点复核 AE-1/AE-2、join 闭合、经济投影字段、final fresh 绑定与 P1 cost 未倒退。

---

## 9. STATIC_REWORK（VALIDATION2 F3–F5）

日期：2026-08-26
状态：`DELIVERY_READY`（STATIC_REWORK VALIDATION2 F3–F5；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network；review 只读未改）
授权：`[STATIC_REWORK_AUTHORIZED][M4-UA006-P2-REBUILT][VALIDATION2 F3-F5]`

### 9.1 Evidence / 分类（不洗白）

| 项 | 内容 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation2-20260826T170000Z-a31f` |
| identity | PASS（exit 0） |
| focused | `70 passed / 1 skipped / 2 failed` |
| focused SHA | `D33A16EB8312D869148C98A45FB26B5F1606267112EDB7E5251E0C55A9F6AC30` |
| summary | `B9F09E589DE9DD758AF5017B3B0B218D473115AF509D403AFA412B69487F5E99` |
| runner | `AD744E10657DC7D32A32B362F88BAA5AD12CEE786A4F14F5E9ED9057669E0213` |
| 后续 Ruff/mypy/cold/scope | **UNRUN** |
| classification | `PRODUCT_FOCUSED_TEST_STOP` |
| F3 production | `"absent" in root_identity` 非语义；materialized 段缺 `_verify_existing_chain` |
| F4 tests | 非法 substring 断言 |
| F5 tests | 物化后 cold env 误断言 `STALE`，应为 `ENVIRONMENT_INVALID` |

### 9.2 六段返工证据

| 项 | 内容 |
| --- | --- |
| 现象 | 见 §9.1 focused 2 failed |
| 根因 | 物理在场闸门与 SHA256 root identity 语义混淆；materialized 未再经 public preflight；测试断言错误码/子串 |
| 应遵循规则 | 中央 F3–F5：`_verify_existing_chain` → `_require_materialized(物理目录)` → cold/materialized 比较；无 private digest/string marker |
| 最小复现 | public cold → mkdir → 敌意 loader 回传 cold layout → `ENVIRONMENT_INVALID` + 空 root 回滚 |
| 修正 | 见 §9.3–§9.4 |
| 通过条件 | STATIC dirty⊆exact5；cached=0；`git diff --check` PASS；复验后再申请 VALIDATION 重跑 |

### 9.3 Production（F3）

`src/quant/execution/paper_formal_broker_store.py`

- materialized 元组组装后：`materialized = _verify_existing_chain(..., timestamp)`，采用返回的 fresh 对象。
- 其后 `_require_materialized` + `_compare_cold_materialized`。
- `_require_materialized` **仅** `broker_root.is_dir()`；删除 `"absent" in root_identity`。
- 无 private `paper_runtime` digest import/copy/string marker。
- 错误归一与空 root rollback 路径未改。

### 9.4 Tests（F4/F5）

- 删除全部 `"absent" in ...` 断言；fixture cold broker 改为 opaque hex64。
- public 正向：冷 root 物理不存在；broker identity `len==64` 且 `[0-9a-f]`；init 后 root 存在；`capability.broker_root_identity` 与冷快照不同且等于 materialized。
- public 无泄漏：物化后 cold capability verify → `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`（非 STALE）。
- `test_ae2_forged_cold_layout_after_mkdir_fails_environment_invalid`：真实 preflight 保持激活；敌意 materialization loader 回传 cold → `ENVIRONMENT_INVALID` + 回滚。
- loader wrapper 内 stale-env：cold preflight 放行一次，其后真实 preflight → `ENVIRONMENT_INVALID`。

### 9.5 写集与 STATIC 边界

| 路径 | 本轮 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | F3 |
| `tests/unit/test_paper_formal_broker_store.py` | F4/F5 |
| 本 delivery | 追加 §9 |
| 任务书 | 追加 §10 |
| review | **只读未改** |

零 Python / pytest / Ruff / mypy / cold / SQLite / network / stage / commit / PAPER。

### 9.6 退出

**`DELIVERY_READY`**（STATIC_REWORK VALIDATION2 F3–F5）

---

## 10. STATIC_REWORK（VALIDATION3 F6）

日期：2026-08-26
状态：`DELIVERY_READY`（STATIC_REWORK VALIDATION3 F6；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network；production/review 只读未改）
授权：`[STATIC_REWORK_AUTHORIZED][M4-UA006-P2-REBUILT-F6]`

### 10.1 Evidence / 分类（不洗白）

| 项 | 内容 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation3-20260826T183000Z-d49e` |
| identity | PASS（exit 0） |
| focused | `71 passed / 1 skipped / 1 failed` |
| focused SHA | `15ACE25896A682DC62014E22863A24AD42BAC06EA8B8089BBE020892F7F73364` |
| summary | `E416E310A1AC43CC3E5F38EEF95F677ED72C8515939E97D047E5AC7C1D6E6A2D` |
| runner | `FEDC7D95B25406D3D40B2CB97F398B191D94890C652F4629BB01D607D866EB8A` |
| 后续阶段 | **UNRUN** |
| classification | `PRODUCT_FOCUSED_TEST_STOP` |
| F6 | wrong-type `verify_paper_runtime_environment` 期望码应为 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID` |

### 10.2 六段返工证据

| 项 | 内容 |
| --- | --- |
| 现象 | focused 1 fail：断言 `INVALID`，生产归一 `ENVIRONMENT_INVALID` |
| 根因 | 测试未跟随 F3 后 materialized `_verify_existing_chain` 对非环境对象的 environment 错误分类 |
| 应遵循规则 | environment 路径 → `ENVIRONMENT_INVALID`；policy wrapper 仍 `INVALID`；空 root 回滚；零 store bytes；无 `__cause__`/`__context__` |
| 最小复现 | 见 VALIDATION3 evidence；`object()` 伪 environment |
| 修正 | `test_public_loader_wrappers_and_wrong_return_types_fail_closed` wrong-type 分支 → `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`；policy_wrap 仍 `INVALID`；stale-env 仍 `ENVIRONMENT_INVALID` |
| 通过条件 | production SHA 不变；dirty ⊆ exact5 tests+task+delivery；cached=0；`git diff --check` PASS |

### 10.3 写集

| 路径 | 本轮 |
| --- | --- |
| `tests/unit/test_paper_formal_broker_store.py` | F6 断言 |
| 本 delivery | 追加 §10 |
| 任务书 | 追加 §11 |
| production / review | **只读未改** |

### 10.4 退出

**`DELIVERY_READY`**（STATIC_REWORK VALIDATION3 F6）

---

## 11. EVIDENCE_UPDATE_ONLY（Windows 工程组合闭合）

日期：2026-08-26
状态：`P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`（组合证据；**非**单轮全绿；**未**跑本轮 Python/pytest/Ruff/mypy/cold）
授权：`[EVIDENCE_UPDATE_ONLY][M4-UA006-P2-REBUILT]`；production / tests / review **只读未改**；零 stage/commit
任务书：§12

### 11.1 组合证据索引（历史失败不改写）

| 轮次 | evidence root | 结果（原生；保留） |
| --- | --- | --- |
| VALIDATION1 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation1-20260826T150000Z` | identity PASS；`CARRIER_EXTERNAL_ROOT_PERMISSION_STOP`（basetemp WinError 5；`1 passed, 72 errors`；product_evidence=NONE）；Ruff/mypy/cold/scope **UNRUN**；summary `F079D600C5114DEB59AA14315A2B59970E52AEDA485C690BA17D358979405EDC`；pytest stdout `616CDE11B5172B20E5F55D52CE4E6519028AC7754FB99ECBFE1575AF86D91DDF` |
| VALIDATION2 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation2-20260826T170000Z-a31f` | identity PASS；`70 passed / 1 skipped / 2 failed` → F3–F5（§9）；Ruff/mypy/cold/scope **UNRUN**；focused `D33A16EB8312D869148C98A45FB26B5F1606267112EDB7E5251E0C55A9F6AC30`；summary `B9F09E589DE9DD758AF5017B3B0B218D473115AF509D403AFA412B69487F5E99` |
| VALIDATION3 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation3-20260826T183000Z-d49e` | identity PASS；`71 passed / 1 skipped / 1 failed` → F6（§10）；Ruff/mypy/cold/scope **UNRUN**；focused `15ACE25896A682DC62014E22863A24AD42BAC06EA8B8089BBE020892F7F73364`；summary `E416E310A1AC43CC3E5F38EEF95F677ED72C8515939E97D047E5AC7C1D6E6A2D` |
| VALIDATION4 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation4-20260826T220000Z-f63b` | identity PASS；`72 passed / 1 skipped`；Ruff/mypy/cold **PASS**；scope=`CARRIER_PARSE_STOP`；`PRODUCT_GREEN_SCOPE_UNRUN` |
| SCOPE1 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation4-scope1-20260826T223000Z-a74d` | `CARRIER_RUNTIME_STOP` / `POWERSHELL5_PROCESSSTARTINFO_ARGUMENTLIST_NULL`；python **UNRUN** |
| FINAL_SCOPE_AUDIT | `artifacts/agent_runs/m4-ua006-p2-rebuilt-final-scope-audit-20260826T230000Z-b85e` | **PASS**（01–05 exit 0；python/product_validation **UNRUN**） |

### 11.2 VALIDATION4 有效绿 SHA

| 产物 | exit | SHA256 |
| --- | --- | --- |
| `stage-summary.log` | — | `FF661A79F4939127C18EB19AF7039394BDEBCC14820697D90D83359603C72406` |
| `01-identity.stdout.log` | 0 | `1016A6CEF3EA8AACBA99F4E1888C0A55083BE70A4F7D1D1D383A290B35B50D24` |
| `02-pytest.stdout.log` | 0 | `6E555AED6BEA6280877CA77DFACB57DF929571FECB98A72B0F13A0FE440411B0` |
| `03-ruff.stdout.log` | 0 | `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` |
| `04-mypy.stdout.log` | 0 | `94594DB09076FE305D51B50210D0BC5E9D275FB814F8B42C1ED4CF3368392F9A` |
| `05-cold.stdout.log` | 0 | `7E876190E44507C993898657174A69ACF439FB41C7898552B9275B7E9A8D8CE4` |
| `runner.ps1` | — | `E636419867D77D10FF0B5E996F011D0FFE9E5B375C0B9FFB700FF085F46D2EE4` |

### 11.3 SCOPE1 / FINAL_SCOPE_AUDIT SHA

| 轮次 | 产物 | SHA256 |
| --- | --- | --- |
| SCOPE1 | `stage-summary.log` | `C9FD5E6E731EC009FFB0C8A75B2564A699B5662EF5BAA4A96D16C47ED091C8AE` |
| SCOPE1 | `01-scope.stderr.log` | `4339FF06FD3D6AAD3A63FEA3B45CC92130571E3BEC87A294744653B453DB9AD6` |
| SCOPE1 | `scope.ps1` | `A61DE24C9C7D996190EED3A554CD6F964402FB61B2245CE207170DB0855969BC` |
| FINAL_SCOPE_AUDIT | `stage-summary.log` | `5ED3C4CE5D50FF80BE991F99933BB5373DFDE7DDD943933B102B8AE91A699FCD` |
| FINAL_SCOPE_AUDIT | `01-status.stdout.log` | `8C3E96E6F7C1A911D410DA56ED3016A70E63D3B7BB461E2F850BEDBB227CD1DA` |
| FINAL_SCOPE_AUDIT | `04-temp-cache.stdout.log` | `3EE95BC7EB3E20FB92EF262951F3FF2C621FE045D6638FD693E2635324889B45` |
| FINAL_SCOPE_AUDIT | `05-process.stdout.log` | `E88CC84BD1C7DF9DF42D08EF03F9150D66F51E40E0DF7854527546641B007C43` |

### 11.4 写集与 STATIC 边界

| 路径 | 本轮 |
| --- | --- |
| 本 delivery | 追加 §11；抬头状态升至工程标签 |
| 任务书 | 追加 §12；§1/§10.1/§11.1 证据绑定 |
| production / tests / review | **只读未改** |

零 Python / pytest / Ruff / mypy / cold / SQLite / network / stage / commit / PAPER。

### 11.5 退出

**`P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`**

组合认定：VALIDATION4 identity + focused `72 passed / 1 skipped` + Ruff/mypy/cold PASS ⊕ FINAL_SCOPE_AUDIT PASS；VALIDATION1 carrier STOP、VALIDATION2/3 红测与 F3–F6、VALIDATION4/SCOPE1 carrier STOP **永久保留**。

**仍 OPEN / 禁止宣称**：UA-M4-006、真实 PAPER、bootstrap、soak、Linux Gate、`FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED`、单轮全量 Gate。
