**`F6_REVIEW_PASS`**（STATIC_ONLY；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network）

F6 仅为测试期望码对齐：production SHA 相对 F3–F5 复验**不变**；wrong-type environment 分支期望 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`；policy wrapper 仍 `PAPER_FORMAL_STORE_INVALID`；空 root 回滚 / `_assert_store_error` 脱敏 / 任务书与 delivery 对 VALIDATION3 `71 passed / 1 skipped / 1 failed` 与后续 **UNRUN** 记录正确。无新 P0/P1。

### 10.1 复验范围哈希（起止一致）

| 路径 | SHA256 | 相对 F3–F5 |
| --- | --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | `42C2916C3391C6F7F283D0264130FCBD36202DAA30582C1DE43A78C9AE6C55C4` | **不变** |
| `tests/unit/test_paper_formal_broker_store.py` | `6FCDBD6219D19F68BC1850A032CF2D97EFEE257986C1E8B2B560B2FFC409EBFC` | 仅 F6 断言 |
| 交付报告 | `E5B6D37E91D9635A99222CB5A9A9F119EFBA4A095817223255109ED003F03932` | 追加 §10 |
| 任务书 | `BE2774AB466F31C575DEFBAE27986788E8905069809878EF56464724F013A592` | 追加 §11 |
| HEAD / cached / `git diff --check` | `6097670…`；cached=0；PASS | — |

### 10.2 授权条对照

| # | 合同 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | production bytes 不变 | **满足** | prod SHA == F3–F5 复验哈希 `42C2916C…` |
| 2 | wrong-type env → `ENVIRONMENT_INVALID` | **满足** | tests L1453–1467；生产路径：`object()` 入 `_verify_existing_chain` 时求值 `environment.config.source_path` 抛错，L409–414 归一 `ENVIRONMENT_INVALID`（`from None`） |
| 3 | policy/binding/account 分类不漂移 | **满足** | policy_wrap 仍 `PAPER_FORMAL_STORE_INVALID`（L1537–1551）；`_verify_existing_chain` 仍分 env / policy-binding / account 三闸（L409–433）；`_require_inputs` 类型闸未改（L376–386） |
| 4 | 空 root 回滚、零 store bytes、脱敏 | **满足** | wrong-type/stale/policy 均 `assert not …broker_root.exists()`；`_assert_store_error` 要求 `__cause__`/`__context__` is None（L44–48）；`raise FormalPaperBrokerStoreError(...) from None`（L246/303/352） |
| 5 | VALIDATION3 记录 71/1/1 与后续 UNRUN | **满足** | 任务书 §11.1；delivery §10.1（focused `71 passed / 1 skipped / 1 failed`；Ruff/mypy/cold/scope 或「后续阶段」**UNRUN**） |

### 10.3 实现者未使用的对抗（AE-5）

### AE-5 — 错类型 environment 对象 vs 错类型 policy 对象：错误码必须分叉

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现者 F6 只改 `verify_paper_runtime_environment → object()` 的期望码；同测内 policy 分支用 **抛错** loader，未用「返回 `object()` 伪 policy」对照。 |
| 静态差分 | **Env：** mkdir 后 loader 返回 `object()` → 组装链后进入 `_verify_existing_chain`；参数求值 `environment.config.source_path` 失败 → **仅** env 段 `except` → `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`（在 compare/store 之前）。**Policy：** 保持真实 env，使 `load_verified_paper_execution_policy → object()`（或现有 HOSTILE 抛错）：失败不落在 env preflight 段——抛错发生于 loader 调用（initialize 外层 `except Exception` → `PAPER_FORMAL_STORE_INVALID`），或若拼进链后在 `_policy_economic`/`verify_existing_paper_execution_policy` 失败则分别为 `INVALID` / `POLICY_BINDING_INVALID`，**不得**被标成 `ENVIRONMENT_INVALID`。 |
| 应遵循规则 | 任务书 §11.2：environment 路径 vs policy/binding/account 分类不漂移。 |
| 最小复现（静态，未执行） | 分支 A：现 F6 wrong-type（已测）→ `ENVIRONMENT_INVALID` + 空 root。分支 B：`_allow_chain` 后只 patch `load_verified_paper_execution_policy` 返回 `object()` → 期望码 ∈ `{PAPER_FORMAL_STORE_INVALID, PAPER_FORMAL_STORE_POLICY_BINDING_INVALID}` 且 ≠ `ENVIRONMENT_INVALID`；空 root；`_assert_store_error` 脱敏。 |
| 通过条件 | 现码控制流与 F6/policy_wrap 断言已体现分叉；AE-5 确认分类未被 F6「一刀切改 INVALID→ENVIRONMENT_INVALID」污染。 |
| 分级 | **非缺陷**（分类确认）；不构成 FAIL |

### 10.4 发现分级

- **无新 P0 / P1 / P2**
- F6 范围正确：test-only 期望对齐生产既有归一

### 10.5 未运行边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite | **未运行**（本复验） |
| VALIDATION3 后续阶段 | 文档记 **UNRUN**；本复验不重跑 |
| stage / commit | **未执行** |
| Gate / UA-M4-006 | **不声称** |

### 10.6 复验结论

**F6_REVIEW_PASS**

历史 §0–§9 保留。F6 将 wrong-type environment 测试期望对齐 `ENVIRONMENT_INVALID`，production 未动；policy 分类与回滚/脱敏合同保持；VALIDATION3 evidence 摘要记录完整。

---

## 11. EVIDENCE_REVIEW（VALIDATION4 ⊕ FINAL_SCOPE_AUDIT；保留全部历史）

日期：2026-08-26
复验角色：同一独立外部初验 Agent（只写本报告；task/delivery/production/tests **只读**；零 Python/pytest/Ruff/mypy/cold/stage/commit/merge/cleanup；未委派）
授权语境：任务书 §12 / delivery §11（`EVIDENCE_UPDATE_ONLY`）
上文 §0–§10 历史裁决**原文保留**。

### 11.0 裁决

**`EVIDENCE_REVIEW_PASS`**

组合证据静态闭合支持工程标签 **仅** `P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION4 product 绿 ⊕ FINAL_SCOPE_AUDIT PASS；V1–V3 / V4-scope / SCOPE1 历史 STOP **未洗白**）。冻结 exact5 哈希、cached=0、`git diff --check`、F3–F6 生产闭包与任务书/delivery 禁止宣称一致。无矛盾性 Gate 越权宣称。

**仍 OPEN（本裁决明确不关闭）**：`UA-M4-006`、真实 PAPER、bootstrap、soak、Linux Gate、`FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED`、单轮全量 Gate。

### 11.1 冻结面核对（本复验实测）

| 项 | 期望 | 结果 |
| --- | --- | --- |
| HEAD | `6097670de3c7f2b1f414580b429facb8d99b67a4` | **匹配** |
| dirty ⊆ exact5 | production + tests `M`；task/delivery/review `??` | **匹配**（仅此五路径） |
| cached | 0 | **匹配** |
| `git diff --check` | PASS | **匹配**（exit 0） |
| production SHA | `42C2916C3391C6F7F283D0264130FCBD36202DAA30582C1DE43A78C9AE6C55C4` | **匹配（冻结）** |
| tests SHA | `6FCDBD6219D19F68BC1850A032CF2D97EFEE257986C1E8B2B560B2FFC409EBFC` | **匹配（冻结）** |
| task SHA | `F123A35294723FA1C27F5B5F93BC2C9230EC84385232D9E68584AB12EC9BEF4B` | **匹配** |
| delivery SHA | `392812CBBA1A7687D49B594C977C61D4557B4550B5BBA3256FDD1082BA7AF444` | **匹配** |
| F3–F6 生产闭包 | materialized `_verify_existing_chain`；`_require_materialized` 仅 `is_dir`；无 `"absent"` 字面量；chain closure 仍在 | **匹配**（静态） |

### 11.2 历史 STOP 保留映射（原生日志）

证据根（worktree 相对 `artifacts/agent_runs/…`，绝对路径已核）：

| 轮次 | stage-summary 要点 | 与文档一致性 |
| --- | --- | --- |
| VALIDATION1 | `CARRIER_EXTERNAL_ROOT_PERMISSION_STOP`；`product_evidence=NONE`；ruff/mypy/cold/scope UNRUN；summary SHA=`F079D600…` **匹配** | **保留且一致** |
| VALIDATION2 | `PRODUCT_FOCUSED_TEST_STOP`；`70_passed_1_skipped_2_failed` → F3–F5 | **保留且一致** |
| VALIDATION3 | `PRODUCT_FOCUSED_TEST_STOP`；`71_passed_1_skipped_1_failed` → F6 | **保留且一致** |
| VALIDATION4 scope | summary：`scope=CARRIER_PARSE_STOP`；`classification=PRODUCT_GREEN_SCOPE_UNRUN` | **保留且一致** |
| SCOPE1 | `CARRIER_RUNTIME_STOP` / `POWERSHELL5_PROCESSSTARTINFO_ARGUMENTLIST_NULL`；python/product_tools UNRUN；summary SHA **匹配** | **保留且一致** |

### 11.3 VALIDATION4 产品绿证据映射

根：`artifacts/agent_runs/m4-ua006-p2-rebuilt-validation4-20260826T220000Z-f63b`

| 产物 | 文档 SHA | 实测 | 内容要点 |
| --- | --- | --- | --- |
| `stage-summary.log` | `FF661A79…` | **匹配** | identity/pytest/ruff/mypy/cold exit=0；scope=`CARRIER_PARSE_STOP`；`PRODUCT_GREEN_SCOPE_UNRUN` |
| `01-identity.stdout.log` | `1016A6CE…` | **匹配** | exit 0 |
| `02-pytest.stdout.log` | `6E555AED…` | **匹配** | `72 passed, 1 skipped` |
| `03-ruff.stdout.log` | `AF352A86…` | **匹配** | exit 0 |
| `04-mypy.stdout.log` | `94594DB0…` | **匹配** | exit 0 |
| `05-cold.stdout.log` | `7E876190…` | **匹配** | exit 0 |
| `runner.ps1` | `E6364198…` | **匹配** | — |

### 11.4 FINAL_SCOPE_AUDIT 证据映射

根：`artifacts/agent_runs/m4-ua006-p2-rebuilt-final-scope-audit-20260826T230000Z-b85e`

| 产物 | 文档 SHA | 实测 | 内容要点 |
| --- | --- | --- | --- |
| `stage-summary.log` | `5ED3C4CE…` | **匹配** | `classification=PASS`；01–05 exit 0；`python=UNRUN`；`product_validation=UNRUN` |
| `01-status.stdout.log` | `8C3E96E6…` | **匹配** | dirty ⊆ exact5（与当前工作树一致） |
| `04-temp-cache.stdout.log` | `3EE95BC7…` | **匹配** | exit 0 |
| `05-process.stdout.log` | `E88CC84B…` | **匹配** | exit 0 |
| `02-cached` / `03-diff-check` | （exit 日志） | **exit 0** | 与 summary 一致 |

### 11.5 Gate 宣称边界（无矛盾）

| 检查 | 结论 |
| --- | --- |
| 任务书/delivery 状态上限仅为 `P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED` | **是** |
| 明确禁止 `FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED` / UA-M4-006 关闭 / PAPER / bootstrap / soak / Linux Gate / 单轮全量 Gate | **是** |
| 是否把 VALIDATION4 scope carrier STOP 或 SCOPE1 伪造成 scope 绿 | **否**（显式 `PRODUCT_GREEN_SCOPE_UNRUN` / `CARRIER_RUNTIME_STOP`） |
| 是否宣称单轮全绿洗白历史 V1–V3 | **否**（索引保留红测与 F3–F6） |

### 11.6 未运行边界（本证据复验）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行**（只读既有日志） |
| stage / commit / merge / cleanup | **未执行** |
| 委派 / 改 production/tests/task/delivery | **无** |

### 11.7 结论

**EVIDENCE_REVIEW_PASS**

历史初验 FAIL 与 F3–F6 复验 PASS 链保留。证据层支持中央认定 **`P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`**；不支持关闭 UA-M4-006 或宣称 PAPER/bootstrap/soak/Linux Gate / formal identity compat 终态。
