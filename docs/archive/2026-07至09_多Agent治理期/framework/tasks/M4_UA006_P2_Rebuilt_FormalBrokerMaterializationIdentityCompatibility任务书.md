# M4-UA006-P2 Rebuilt Formal Broker Materialization Identity Compatibility 任务书

## 1. 身份、目标与状态上限

- exact base/HEAD：`6097670de3c7f2b1f414580b429facb8d99b67a4`
- branch：`codex/m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
- 本包已达工程状态：`P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`（§12 组合证据；**非**单轮全绿洗白）
- 合同目标上限（**未宣称**）：`FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED`
- **仍 OPEN**：`UA-M4-006` / 真实 PAPER / bootstrap / soak / Linux Gate

本包只修复 public formal broker initializer 在首次合法 broker root materialization 时的身份比较矛盾，使 cold absent-root 与 materialized-root 链按经济语义等价，同时保持最终 capability 完整绑定 materialized fresh identity。它不实现 bootstrap、PAPER、soak、B1B2，也不关闭 UA-M4-006。

## 2. 唯一写白名单 exact5

1. `src/quant/execution/paper_formal_broker_store.py`
2. `tests/unit/test_paper_formal_broker_store.py`
3. `docs/framework/tasks/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility任务书.md`
4. `docs/framework/deliveries/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility交付报告.md`
5. `docs/framework/reviews/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility独立初验报告.md`

经理唯一写3；全新外部实现者只写1、2、4；另一全新独立reviewer唯一写5。禁止修改runtime/policy/account/binding/config/schema/migration/store/barrier/bootstrap、`__init__.py`、roadmap或共享SSOT。

## 3. 前置闭包与旧STOP历史

旧P2在base `1d9b4e09…`形成未合流事故现场，仅作只读设计参考，不得复制其dirty字节或继续验证。其DIAGNOSTIC1已定位：public initializer进入`paper_formal_broker_store.py`后，旧formal descriptor用broker-local成本digest拒绝真实policy。该前置已由M4-P1闭合并合流到本base：

- 唯一public成本身份：`paper_execution_cost_schedule_identity`；
- formal descriptor与formal-store fixture均消费该身份；
- 组合回归policy/broker/formal-store全绿。

本包必须保留该P1闭包，禁止恢复`_digest(_cost_payload(...))`作为formal成本身份。

## 4. 现象、根因与系统不变量

真实public broker initializer在首次合法materialization中：

1. root创建前fresh验证cold chain；
2. 创建broker root后重建materialized environment/policy/binding/account；
3. absent→materialized必然改变environment verification/layout/root identity；
4. policy/binding/account的attestation identity因此合法变化；
5. 当前cold→materialized比较却把这些派生identity当作跨物化恒等字段，错误归为`PAPER_FORMAL_STORE_STALE`。

不变量：物理root状态变化时环境绑定identity必须变化；跨该边界只有经济policy/account/binding语义应相等。最终capability仍必须绑定materialized后的fresh链，不能删除身份或复用cold对象。

## 5. 冻结实现合同

- 只把cold→materialized比较收敛为窄、显式、可审查的经济投影；普通materialized→fresh reopen比较与最终fresh verify保持逐字段完整。
- 经济投影至少闭合canonical source bytes/SHA、selector、session、trading/cost/fill/fault/finality/clock规则、supported markets、account descriptor经济内容、binding classification及所有不随root物化变化的字段。
- environment verification/layout/root identity以及由其派生的policy/binding/account attestation identity允许且必须变化；它们不得从最终capability、descriptor或fresh verify删除。
- initializer仍须按原顺序：cold public loaders/verifiers → 创建root → materialized public loaders/verifiers → store initialize → final chain重建及fresh verify。
- final capability必须绑定materialized environment、policy、binding、account、root、store与separation identities；禁止cold/stale对象、caller injection、bool/marker、`Any`、cast或`type: ignore`绕过。
- existing/partial root、unknown sibling、symlink/reparse、经济字段漂移、source/config/session/selector/cost/account drift、wrapper/monkeypatch public authority替换继续fail closed。
- rollback ownership不变：只清本次创建且仍空、identity闭合的root；正式bytes、unknown WAL/SHM或ownership不明必须保留并要求人工处置。
- 不改错误码、schema、migration、SQLite布局、descriptor bytes、transaction或session barrier。

## 6. 必测对抗

至少覆盖：

1. 真实public chain下cold environment identity与materialized identity不同，首次initializer成功并返回fresh capability。
2. materialization后policy/binding/account均来自新environment；final capability与fresh reopen/verify闭合，cold对象不泄漏。
3. raw SHA、selector、session、trading/cost/fill/fault/finality/clock、account经济字段任一漂移拒绝。
4. environment identity未随物化变化、错root、cross-root/session/account capability拒绝。
5. preexisting root、partial/unknown sibling、symlink/reparse、separation冲突拒绝。
6. 初始化前、root创建后、store正式bytes后三类失败分别证明安全回滚或人工清理边界；unknown sidecar不删除。
7. public loader/verifier wrapper/lambda/monkeypatch、错类型、旧对象、不等值对象拒绝。
8. legacy/B1A broker initialize/open/verify及稳定错误码不漂移。
9. P1 canonical成本身份真实正向；旧broker-local digest伪造identity继续拒绝。

实现测试不得伪造固定identity让cold/materialized看似相等；至少一个正向必须消费真实public链并观察environment identity变化。project布局测试使用调用方显式创建的合法root，不放宽production layout guard。

## 7. 交付、独立初验与验证

当前仅授权全新外部实现者`STATIC_ONLY`：零Python、pytest、Ruff、mypy、cold、SQLite、PAPER、network/browser、stage/commit。delivery必须写“现象—根因—应遵循规则—最小复现—新增测试—通过条件”、旧STOP与P1前置、actual diff和未运行边界。

实现完成后由另一全新外部reviewer只读production/test/delivery且唯一写review；必须新增实现者未用对抗，重点挑战：经济投影误删真正经济字段、final capability仍绑定cold environment、或P1 canonical成本身份倒退。REVIEW_PASS后才申请Windows验证：identity → `test_paper_formal_broker_store.py` → Ruff source/test → mypy source → cold source → exact5 scope/diff/temp/process。pytest basetemp必须同卷、project外、非system-temp、new no-clobber。

## 8. STOP与退出条件

以下任一立即在delivery留证并STOP：

- exact5不足，需要改policy/account/binding/runtime/bootstrap/schema/migration/store/barrier；
- 不能同时保持cold→materialized经济等价与final materialized fresh identity；
- 需要复用stale对象、caller injection、raw SQLite、删除identity或放宽错误码；
- base/branch/worktree漂移、第二writer、白名单外dirty。

静态退出要求actual dirty只属exact5、cached=0、`git diff --check`PASS，无runtime root、SQLite、cache、temp或凭据。Windows绿仍不代表bootstrap、PAPER、B1B2、soak、Linux Gate或UA-M4-006完成。

## 9. STATIC_REWORK_AUTHORIZED（P1×2 + P2；中央授权）

触发：独立初验 `REVIEW_FAIL`（`docs/framework/reviews/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility独立初验报告.md`）。本轮实现者获权追加本节与 delivery 返工证据；**review 只读**直至再交付。仍 `STATIC_ONLY`。

### 9.1 REVIEW_FAIL 发现摘要（不洗白）

| ID | 摘要 |
| --- | --- |
| P1-1 | `_compare_cold_materialized` 未强制 policy/binding/account 派生 attestation 相对 cold 必变，亦未做 materialized 内跨对象 join 闭合；AE-1 敌意可混绑新 env 与 cold 派生身份 |
| P1-2 | mkdir 后未调用 `_require_materialized`；仅 `cold_broker != current_broker` 可接受另一枚 `absent-*`（AE-2） |
| P2-1 | 经济投影缺 `schema_version`；account 缺 `runtime_config_identity`；缺 exact `source_path` / `trading_config` / `execution_cost_schedule` 等不随 root 物化变化的公开字段 |
| P2-2 | 缺 AE-1/AE-2；经济漂移参数化面偏窄 |

### 9.2 中央最小返工合同

1. store bytes 前对 current materialized environment 调用既有 `_require_materialized`；保留稳定归一与空 root 回滚；比较器不再自造 absent-string 启发式。
2. 新增窄 `_require_materialized_chain_closure`：binding/account 与当前 env/policy/binding siblings join；`policy_identity` / `binding_identity` / `account.verification_identity` 相对 cold 必变。final capability 仍只由后续 fresh materialized reload 组装。
3. 经济投影闭合所有不随 broker-root 物化单独变化的公开字段（含 schema_version、exact source_path/config/schedule 对象、account `runtime_config_identity`）；仅排除已文档化的 env 派生身份、`verified_at`、私有 attestation。保留 canonical `paper_execution_cost_schedule_identity`；`_compare_materialized` 不变。
4. 测试补 AE-1/AE-2、每一 join 失配、schema/config/source/经济漂移、fresh final capability、rollback/错误码、诚实 public 正向；敌意窄 loader 必须因目标不变量失败。
5. 本任务书与 delivery 追加 REVIEW_FAIL 与六段返工证据；不改 review 报告与 exact5 外路径。

### 9.3 返工六段证据（现象—根因—规则—复现—测试—通过条件）

| 项 | 内容 |
| --- | --- |
| 现象 | 敌意 loader 可在 env 三元已变时复用 cold 派生 attestation，或换成另一 `absent-*` broker identity，于 store bytes 前未被拒绝 |
| 根因 | 经济收窄后缺 materialized 内 join/派生必变闸门；缺 `_require_materialized` 物化在场检查 |
| 应遵循规则 | 任务书 §4/§5；审查 P1-1/P1-2/P2-1；既有 `_require_materialized` 为 absent→present 原语 |
| 最小复现 | AE-1：新 env + cold policy/binding/account；AE-2：新 verification/layout + 另一 `absent-*` broker id |
| 新增测试 | `test_ae1_*`、`test_ae2_*`、`test_materialized_chain_join_or_derived_freshness_mismatch_rejected`、扩展经济/schema/source 漂移、`test_final_capability_binds_fresh_materialized_identities_not_cold` |
| 通过条件 | STATIC dirty⊆exact5；cached=0；`git diff --check` PASS；无 runtime/SQLite/temp/凭据；独立复验后再谈 Windows |

## 10. STATIC_REWORK_AUTHORIZED（VALIDATION2 F3–F5）

触发：Windows VALIDATION2 focused 红测分类 F3–F5。授权 `[STATIC_REWORK_AUTHORIZED][M4-UA006-P2-REBUILT][VALIDATION2 F3-F5]`。仍 `STATIC_ONLY`；review 只读。

### 10.1 Evidence / 分类

| 项 | 内容 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation2-20260826T170000Z-a31f` |
| identity | PASS（exit 0） |
| focused | `70 passed / 1 skipped / 2 failed` |
| focused SHA | `D33A16EB8312D869148C98A45FB26B5F1606267112EDB7E5251E0C55A9F6AC30` |
| summary | `B9F09E589DE9DD758AF5017B3B0B218D473115AF509D403AFA412B69487F5E99` |
| runner | `AD744E10657DC7D32A32B362F88BAA5AD12CEE786A4F14F5E9ED9057669E0213` |
| Ruff / mypy / cold / scope | **UNRUN** |
| classification | `PRODUCT_FOCUSED_TEST_STOP` |
| F3 | production：`"absent" in root_identity` 非语义（root identity 为 SHA256）；mkdir 后缺 public `_verify_existing_chain` 再验 |
| F4 | tests：非法 substring 断言（`"absent" in broker identity`） |
| F5 | tests：物化后 cold environment 误期望 `STALE`，应为 `ENVIRONMENT_INVALID` |

### 10.2 中央最小返工合同

1. materialized 元组组装后、store bytes 前：经既有 `_verify_existing_chain(..., timestamp)` 并采用其返回的 fresh 对象；再 `_require_materialized` 与 cold/materialized 比较。
2. `_require_materialized` 仅检查物理 `broker_root` 目录在场；真实性由 `_verify_existing_chain` 内 public preflight 供给。
3. 禁止 private `paper_runtime` digest import/copy/string marker；保留错误归一与空 root 回滚。
4. 敌意 materialization-loader（真实 preflight 保持激活）+ forged/cold layout → `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`，store bytes 前并回滚。
5. F4：去掉 substring 断言；冷 root 物理不存在 + broker identity exact hex64/快照；init 后 root 存在且 capability/materialized identity 不同。
6. F5：物化后 stale cold environment → `ENVIRONMENT_INVALID`（非 STALE）；保留 cold 对象拒绝/无泄漏。

### 10.3 六段返工证据

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION2 focused 2 failed：非法 absent substring 语义；物化后 cold env 错误码不符 |
| 根因 | `_require_materialized` 误用 identity 子串；materialized 段未再走 public preflight；测试断言绑定错误语义/错误码 |
| 应遵循规则 | root identity 为不透明 SHA256；真实性靠 public preflight；物理在场与 attestation 分离 |
| 最小复现 | 真实 public cold → mkdir → 敌意 loader 返回 cold capability → 应 ENVIRONMENT_INVALID 并回滚空 root |
| 新增/修正测试 | `test_ae2_forged_cold_layout_after_mkdir_fails_environment_invalid`；public 正向/无泄漏 F4/F5 断言；loader stale-env 保持真实 preflight |
| 通过条件 | STATIC dirty⊆exact5；cached=0；`git diff --check` PASS；独立复验后再申请 VALIDATION 重跑 |

## 11. STATIC_REWORK_AUTHORIZED（VALIDATION3 F6）

触发：VALIDATION3 focused 残留 1 fail。授权 `[STATIC_REWORK_AUTHORIZED][M4-UA006-P2-REBUILT-F6]`。仍 `STATIC_ONLY`；**production / review 只读**。

### 11.1 Evidence / 分类

| 项 | 内容 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation3-20260826T183000Z-d49e` |
| identity | PASS（exit 0） |
| focused | `71 passed / 1 skipped / 1 failed` |
| focused SHA | `15ACE25896A682DC62014E22863A24AD42BAC06EA8B8089BBE020892F7F73364` |
| summary | `E416E310A1AC43CC3E5F38EEF95F677ED72C8515939E97D047E5AC7C1D6E6A2D` |
| runner | `FEDC7D95B25406D3D40B2CB97F398B191D94890C652F4629BB01D607D866EB8A` |
| Ruff / mypy / cold / scope | **UNRUN** |
| classification | `PRODUCT_FOCUSED_TEST_STOP` |
| F6 | `test_public_loader_wrappers_and_wrong_return_types_fail_closed` 敌意 `verify_paper_runtime_environment` 错类型期望码应为 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`（非 `INVALID`） |

### 11.2 返工合同

- 仅改 `tests/unit/test_paper_formal_broker_store.py` + 本任务书 + delivery。
- 错类型断言改为 exact `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`。
- 保留 policy/binding/account 错误分类、空 root 回滚、零 store bytes、异常上下文脱敏。
- production bytes 不变。

### 11.3 六段证据

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION3 focused 1 failed：wrong-type loader 断言 `INVALID`，实际 `ENVIRONMENT_INVALID` |
| 根因 | materialized `_verify_existing_chain` 在求值 `environment.config.source_path` 时对非环境对象归一为 `ENVIRONMENT_INVALID`；测试仍锁旧 `INVALID` |
| 应遵循规则 | 公开错误归一；environment 路径失败归 `ENVIRONMENT_INVALID`；policy/binding/account 分类不漂移 |
| 最小复现 | `_allow_chain` + `verify_paper_runtime_environment→object()` → initialize → `ENVIRONMENT_INVALID` + 空 root |
| 修正测试 | wrong-type 分支断言改为 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`；其余分支不变 |
| 通过条件 | STATIC dirty⊆exact5；production 无 diff；cached=0；`git diff --check` PASS |

## 12. EVIDENCE_UPDATE_ONLY（Windows 工程组合闭合）

授权：同一实现所有权、`STATIC_ONLY`、零 Python；**仅**更新本任务书与 delivery；production / tests / review **冻结只读**；零 stage/commit。历史 VALIDATION1–3 失败与 F3–F6 返工链**原文保留**，不得洗白。

### 12.1 组合证据索引（历史失败不改写）

| 轮次 | evidence root | 结果（原生；保留） |
| --- | --- | --- |
| VALIDATION1 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation1-20260826T150000Z` | identity PASS；pytest carrier-only STOP：`CARRIER_EXTERNAL_ROOT_PERMISSION_STOP`（basetemp `PermissionError` WinError 5；`1 passed, 72 errors`）；product_evidence=NONE；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION2 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation2-20260826T170000Z-a31f` | identity PASS；focused `70 passed / 1 skipped / 2 failed` → F3–F5（§10）；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION3 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation3-20260826T183000Z-d49e` | identity PASS；focused `71 passed / 1 skipped / 1 failed` → F6（§11）；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION4 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation4-20260826T220000Z-f63b` | identity PASS；focused `72 passed / 1 skipped`；Ruff PASS；mypy PASS；cold PASS；scope=`CARRIER_PARSE_STOP`；classification=`PRODUCT_GREEN_SCOPE_UNRUN` |
| SCOPE1 | `artifacts/agent_runs/m4-ua006-p2-rebuilt-validation4-scope1-20260826T223000Z-a74d` | carrier STOP：`CARRIER_RUNTIME_STOP` / `POWERSHELL5_PROCESSSTARTINFO_ARGUMENTLIST_NULL`；python/product_tools **UNRUN** |
| FINAL_SCOPE_AUDIT | `artifacts/agent_runs/m4-ua006-p2-rebuilt-final-scope-audit-20260826T230000Z-b85e` | **PASS**（status/cached/diff-check/temp-cache/process 全 exit 0；python/product_validation **UNRUN**） |

### 12.2 VALIDATION1 SHA（carrier-only STOP）

| 产物 | SHA256 |
| --- | --- |
| `stage-summary.log` | `F079D600C5114DEB59AA14315A2B59970E52AEDA485C690BA17D358979405EDC` |
| `01-identity.stdout.log` | `1016A6CEF3EA8AACBA99F4E1888C0A55083BE70A4F7D1D1D383A290B35B50D24` |
| `02-pytest.stdout.log` | `616CDE11B5172B20E5F55D52CE4E6519028AC7754FB99ECBFE1575AF86D91DDF` |
| `runner.ps1` | `36CB445838AEBEF75AF3817E07164E3BCA61D797E3A2AB519C4F5F1E77CF79AD` |

### 12.3 VALIDATION4 product SHA（有效绿；scope carrier STOP）

| 产物 | exit | SHA256 |
| --- | --- | --- |
| `stage-summary.log` | — | `FF661A79F4939127C18EB19AF7039394BDEBCC14820697D90D83359603C72406` |
| `01-identity.stdout.log` | 0 | `1016A6CEF3EA8AACBA99F4E1888C0A55083BE70A4F7D1D1D383A290B35B50D24` |
| `02-pytest.stdout.log` | 0 | `6E555AED6BEA6280877CA77DFACB57DF929571FECB98A72B0F13A0FE440411B0`（`72 passed, 1 skipped`） |
| `03-ruff.stdout.log` | 0 | `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` |
| `04-mypy.stdout.log` | 0 | `94594DB09076FE305D51B50210D0BC5E9D275FB814F8B42C1ED4CF3368392F9A` |
| `05-cold.stdout.log` | 0 | `7E876190E44507C993898657174A69ACF439FB41C7898552B9275B7E9A8D8CE4` |
| `runner.ps1` | — | `E636419867D77D10FF0B5E996F011D0FFE9E5B375C0B9FFB700FF085F46D2EE4` |

### 12.4 SCOPE1 / FINAL_SCOPE_AUDIT SHA

| 轮次 | 产物 | SHA256 |
| --- | --- | --- |
| SCOPE1 | `stage-summary.log` | `C9FD5E6E731EC009FFB0C8A75B2564A699B5662EF5BAA4A96D16C47ED091C8AE` |
| SCOPE1 | `01-scope.stderr.log` | `4339FF06FD3D6AAD3A63FEA3B45CC92130571E3BEC87A294744653B453DB9AD6` |
| SCOPE1 | `scope.ps1` | `A61DE24C9C7D996190EED3A554CD6F964402FB61B2245CE207170DB0855969BC` |
| FINAL_SCOPE_AUDIT | `stage-summary.log` | `5ED3C4CE5D50FF80BE991F99933BB5373DFDE7DDD943933B102B8AE91A699FCD` |
| FINAL_SCOPE_AUDIT | `01-status.stdout.log` | `8C3E96E6F7C1A911D410DA56ED3016A70E63D3B7BB461E2F850BEDBB227CD1DA` |
| FINAL_SCOPE_AUDIT | `04-temp-cache.stdout.log` | `3EE95BC7EB3E20FB92EF262951F3FF2C621FE045D6638FD693E2635324889B45` |
| FINAL_SCOPE_AUDIT | `05-process.stdout.log` | `E88CC84BD1C7DF9DF42D08EF03F9150D66F51E40E0DF7854527546641B007C43` |

### 12.5 状态上限与禁止宣称

- 本包工程状态：**仅** `P2_REBUILT_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION4 product 绿 ⊕ FINAL_SCOPE_AUDIT PASS；V1 carrier / V2–V3 红测 / V4·SCOPE1 carrier STOP **均保留**）
- **禁止宣称**：`FORMAL_BROKER_MATERIALIZATION_IDENTITY_COMPAT_VALIDATED`、UA-M4-006 关闭、真实 PAPER、bootstrap、soak、Linux Gate、单轮「全量 Gate 通过」
