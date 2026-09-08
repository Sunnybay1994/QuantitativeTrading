# M4-UA006-P2 Rebuilt Formal Broker Materialization Identity Compatibility 独立初验报告

日期：2026-08-26
状态：`REVIEW_FAIL`（STATIC_ONLY；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network；不等于 Windows VALIDATION、bootstrap、UA-M4-006）
task id：`M4-UA006-P2-REBUILT-FORMAL-BROKER-MATERIALIZATION-IDENTITY-COMPAT`
exact base / HEAD：`6097670de3c7f2b1f414580b429facb8d99b67a4`
branch：`codex/m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p2-formal-broker-materialization-identity-compat-rebuilt`
审查角色：全新独立外部初验 Agent（未参与实现；未委派；未改 production/tests/task/delivery）

任务书：`docs/framework/tasks/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility任务书.md`
交付：`docs/framework/deliveries/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility交付报告.md`
唯一写路径：本报告（exact5 #5）

审查中 scoped 输入 SHA256（起止一致，未漂移）：

| 路径 | SHA256 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | `F06FA4B36669D76B1795A0FFC3C3721E1F4C986B28584F48140B9EF8E0E176AC` |
| `tests/unit/test_paper_formal_broker_store.py` | `2EA5E73FE30718BEE05E72EA865D70B3AC144C8740A3D02B06514D8380F2066A` |
| 交付报告 | `FB094D265D8B3BE170C49347C2DC97B3D6A8BF265EDD787A5973BC0BF792583A` |
| 任务书 | `0606AEA447BBDBC3C7529B078C3D5C618FE2833E4C52E769F099D06C726DA9BC` |

---

## 0. 裁决

**`REVIEW_FAIL`**

cold→materialized 经济投影收窄与最终 `_assemble_capability(chain=final, …)` / 未改的 `_compare_materialized` 在诚实 public loader 路径上方向正确，且未见 P1 canonical 成本身份倒退或错误码/rollback 所有权被改写。但冻结合同要求派生 attestation「允许且必须变化」、旧对象/monkeypatch fail-closed、以及跨对象身份一致；当前 `_compare_cold_materialized` 只强制 env verification/layout/broker 三元变化，**不**强制 policy/binding/account 派生身份变化，也**不**在 materialized 元组内做跨对象闭合，也**不**要求物化后 broker identity 非 `absent`。实现者测试未覆盖下列对抗面。存在 **P1×2**（加 **P2×2**），不得申请 Windows 验证。

本裁决**不**授权声称任何 Gate / Windows 绿 / UA-M4-006 关闭。

---

## 1. 范围与只读证据

| 项 | 静态结论 |
| --- | --- |
| 根 `AGENTS.md` | 已读；服从 STATIC_ONLY、职责分离、不自宣 Gate |
| dirty / untracked | `paper_formal_broker_store.py` / `test_paper_formal_broker_store.py` `M`；任务书/交付 `??`；本报告（写后） |
| cached | 0 |
| `git diff --check` | PASS（无输出） |
| HEAD | = exact base `6097670de3c7f2b1f414580b429facb8d99b67a4` |
| 业务 diff | production +78/−约20 量级；tests +733/−17 |
| 越界写 | **无**（未见 policy/account/binding/runtime/bootstrap/schema/migration/`__init__.py`/roadmap dirty） |

---

## 2. 逐项静态核验矩阵

| # | 合同项 | 结论 | 关键证据 |
| --- | --- | --- | --- |
| A | cold→materialized 仅窄经济投影；materialized→fresh / final verify 仍逐字段完整 | **部分满足** | 新增 `_policy_economic` / `_binding_economic` / `_account_economic`（`paper_formal_broker_store.py` L481–537）；`_compare_materialized` + `_policy_business`（仍含 `policy_identity`）未改（L470–478, L540–553）。但见 P1-1/P1-2 |
| B | 经济投影闭合 source/SHA/selector/session/trading/cost/fill/fault/finality/clock/markets/account/binding classification 等 | **基本满足；有缺口** | policy 经济投影相对旧 `_policy_business` 为超集（含 selector/source/markets/notionals/a_share 等）。account 排除 `runtime_config_identity`；三投影均省略 `schema_version`（P2-1） |
| C | env verification/layout/root 及派生 attestation 必须变化；不得从 final capability 删除 | **env 层满足；派生层不足** | L454–462 强制 verification/layout/broker **不等**。capability 仍绑定 materialized fresh identities（L636–655）。**未**要求 `policy_identity` / `binding_identity` / account `verification_identity` 相对 cold 变化，亦无 materialized 内跨对象核对（P1-1） |
| D | initializer 序：cold verify → mkdir → materialized loaders → compare → store → reload/fresh | **满足** | L157–208 顺序未改 |
| E | final capability 绑定 materialized 链；禁止 cold 泄漏 / injection | **诚实路径满足；敌意 loader 不足** | `final = _reload_materialized_chain(...)` 后 `_assemble_capability`（L205–208）。public 正向测断言 capability≠cold（tests L696–816）。敌意旧对象见 P1-1 与 AE-1 |
| F | rollback ownership / 错误码不漂移 | **满足（静态）** | 失败路径 L224–238 / `_remove_owned_empty_root` L690–703 未改语义；测例覆盖 compare 前空 root 回滚与 formal bytes 后 unknown WAL 保留（tests L1070–1117） |
| G | P1 canonical `paper_execution_cost_schedule_identity`；拒绝 legacy broker-local digest | **满足（静态）** | 经济投影消费 `cost_schedule_identity`（L491, L516）；未恢复 `_digest(_cost_payload)`。tests L423–452 正/反向；public 正向亦断言 canonical（L708–712） |
| H | 必测 §6 映射 | **部分满足** | 真实 public 正向、cold 不泄漏、若干经济漂移、layout 未变、preexisting/partial/symlink/separation、多失败点回滚、wrapper 错类型、legacy 错误码、P1 cost 均有测名。**缺** AE-1/AE-2 对抗；若干经济字段未参数化（P2-2） |

---

## 3. 发现分级

### P1-1 — materialized 链允许跨对象身份不一致 / 复用 cold 派生 attestation

**位置：** `src/quant/execution/paper_formal_broker_store.py` L445–467, L503–518, L521–537

**现象：** `_compare_cold_materialized` 在 env 三元已变化且经济投影相等时即通过。`_binding_economic` / `_account_economic` 故意排除 `runtime_environment_identity`、`execution_policy_identity`、`binding_identity`、account 侧 env/policy/binding 派生字段，但比较器**既不**要求这些派生身份相对 cold 发生变化，**也不**断言 materialized 元组内例如：

- `binding.execution_policy_identity == policy.policy_identity`
- `binding.runtime_environment_identity == environment.verification_identity`
- `account.runtime_environment_identity` / `execution_policy_identity` / `broker_binding_identity` 与兄弟对象一致

**根因：** 收窄冷热比较时只做了「跨物化经济相等 + env 必须变」，漏掉任务书 §4/§5「派生 attestation 必须变化」与 §6.7「旧对象拒绝」所需的 **materialized 内闭合** 或 **派生身份必变** 闸门。

**破坏的不变量：** 最终 capability 可同时绑定「新 env verification」与「仍指向 cold 的 policy/binding/account 派生身份」，形成跨对象不一致；与「cold 对象不泄漏」合同冲突。

**应遵循规则：** 任务书 §5（派生 identity 允许且必须变化；final 绑定 materialized fresh）；§6.2/§6.7。

### P1-2 — 物化后仍可接受另一枚 `absent-*` broker identity

**位置：** `src/quant/execution/paper_formal_broker_store.py` L164–192, L445–467, L663–666

**现象：** mkdir 之后 initializer **不**对 materialized environment 调用 `_require_materialized`。比较器只要求 `cold_broker != current_broker`（且非 None），不要求 current broker identity **不含** `"absent"`，也不要求 root 已反映为 materialized 目录身份。

**根因：** 「identity 必须变化」被实现成字符串不等，而非「cold absent → materialized present」状态机。

**破坏的不变量：** 敌意 `verify_paper_runtime_environment` 可返回新的 verification/layout identity + 另一 `absent-*` broker id，通过冷热比较，随后 `initialize_paper_broker_store` 写入真实 root，而 capability/`broker_root_identity` 仍呈 absent 语义。

**应遵循规则：** 任务书 §4（absent→materialized 必然改变 root identity 的物化语义）；既有 `_require_materialized`（L663–666）本就是该语义的 fail-closed 原语，却未用于 initialize 的 materialized 段。

### P2-1 — 经济投影省略不随 root 物化变化的 `schema_version`（及 account `runtime_config_identity` 不对称）

**位置：** L481–537；对照 binding 含 `runtime_config_identity`（L510）而 account 经济投影不含（L521–537），尽管 `VerifiedFormalPaperAccountDescriptor.runtime_config_identity` 亦不随 broker root 物化改变。

**影响：** 敌意/漂移 schema 或 account 侧 config identity 不一致时，冷热比较可能静默放过（env `config` 全量相等可部分兜底 config 字节，但不覆盖 account 字段自洽）。属合同「所有不随 root 物化变化的字段」闭合缺口。

### P2-2 — 经济漂移测试覆盖面偏窄；多数对抗依赖 `_allow_chain`

**位置：** `tests/unit/test_paper_formal_broker_store.py` L820–856 等

**影响：** policy 参数化未覆盖 `minimum_order_notionals` / `a_share_rule_selector` / `source_*` / `fx_snapshot_identity`；binding 仅测 cost；account 仅测 descriptor。真实 public 正向存在（L696+），但 §6.3/§6.7 的敌意面仍大量只在 monkeypatch 链上证明，易漏 P1-1/P1-2。

### 无 P0

静态未见「诚实 public loader 下首次合法物化必然 AttributeError/错码」或 P1 成本身份被恢复为 broker-local digest 的证据。

---

## 4. 实现者未使用的静态对抗反例

### AE-1 — 新 env + 复用 cold policy/binding/account（派生身份不变）

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现者 `test_public_loader_wrappers_and_wrong_return_types_fail_closed` 覆盖：错类型 `object()`、**整棵** cold environment 当作 materialized（identities 未变→STALE）、loader 抛错。未覆盖：materialized env identities 已变，但 `load_verified_paper_execution_policy` / bind / account loader 仍返回 **cold** 对象（或仅 `replace` 了 env 字段而 `execution_policy_identity` 仍为 cold policy）。 |
| 根因 | `_compare_cold_materialized` 不读派生 attestation 的「必变」或跨对象相等。 |
| 应遵循规则 | 任务书 §5/§6.2/§6.7；审查指令 challenge (1)(2)。 |
| 最小复现（静态，未执行） | `_allow_chain` 基础上：`verify_paper_runtime_environment`→新 env；`load_verified_paper_execution_policy`→`cold.policy`；bind/account 同理返回 cold（或 binding 仅改 `runtime_environment_identity` 文本而 `execution_policy_identity` 仍为 cold）。`initialize_verified_formal_paper_broker_store` 预期应 fail-closed；**按现码**经济投影与 env 三元检查将 **通过**，capability 可出现 `runtime_environment_identity`（新）与 `execution_policy_identity`（cold）并存。 |
| 通过条件 | 比较器或紧随其后的校验拒绝该链；新增回归测断言 STALE/INVALID，且空 root 回滚。 |
| 分级 | **P1-1** |

### AE-2 — 物化后换一枚不同的 `absent-*` broker identity

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现者 `test_unchanged_layout_identity_across_materialization_is_rejected` 只测 layout/verification **保持 cold 不变**。未测：二者已变，但 `root_identities["broker"]` 从 `absent-AAA…` 改为 `absent-BBB…`（仍含 absent）。 |
| 根因 | 只校验 `cold_broker != current_broker`，不调用 `_require_materialized`。 |
| 应遵循规则 | 任务书 §4 物化语义；审查指令 challenge (1)(2)。 |
| 最小复现（静态，未执行） | monkeypatch `verify_paper_runtime_environment` 返回 env：`verification_identity`/`layout_identity` 新值，`broker`=`"absent-" + ("b"*57)` 且 ≠ cold 的 absent 串；policy/binding/account 经济字段与 cold 对齐。现码 `_compare_cold_materialized` **不应**因 broker 条款失败；随后可写入 store 并签发带 absent 语义的 `broker_root_identity`。 |
| 通过条件 | initialize 在 store bytes 前拒绝；或强制 `_require_materialized(materialized_environment)`；回归测锁定错误码与空 root 回滚。 |
| 分级 | **P1-2** |

---

## 5. 五项专项挑战结论

| # | 挑战 | 静态结论 |
| --- | --- | --- |
| 1 | 经济投影误删字段 / 跨对象身份 | **FAIL 点**：派生字段排除后缺闭合（P1-1）；`schema_version`/account `runtime_config_identity` 缺口（P2-1）。核心经济字段集合本身大体完整。 |
| 2 | final / materialized→fresh 永不复用 cold authority | **诚实路径 PASS**；**敌意 loader 路径 FAIL**（P1-1/P1-2）。`_compare_materialized` 仍完整。 |
| 3 | 唯一 canonical cost identity；拒 legacy digest | **PASS（静态）** |
| 4 | rollback ownership / 错误码 fail-closed | **PASS（静态）** |
| 5 | 测试非仅靠过宽 monkeypatch；覆盖真实 public 链 | **部分 PASS**：有真实 public 正向；但 AE-1/AE-2 未测，经济漂移面不足（P2-2） |

---

## 6. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite | **未运行** |
| 网络 / 真实 PAPER / soak / browser | **未运行** |
| stage / commit | **未执行** |
| Windows 验证 / 主验 / Linux Gate / UA-M4-006 | **不声称；本 FAIL 后不得申请 Windows 验证** |

诚实边界：上述 P1 结论来自合同与控制流静态推演；未执行 monkeypatch 复现。返工后需独立复验再谈 VALIDATION。

---

## 7. 结论

**REVIEW_FAIL**

最小返工建议（供领域经理写返工单，审查者不动代码）：

1. 在 cold→materialized 成功路径上增加 materialized 内跨对象身份闭合，并/或要求 policy/binding/account 派生 attestation 相对 cold **必须变化**。
2. 对 materialized environment 强制非 absent / 调用 `_require_materialized`（或等价）。
3. 落地 AE-1/AE-2 回归；补经济字段漂移参数化与 `schema_version`（及 account `runtime_config_identity`）闭合评估。
4. 保持 P1 canonical cost、rollback/错误码、`_compare_materialized` 完整比较不被放宽。

报告路径：`docs/framework/reviews/M4_UA006_P2_Rebuilt_FormalBrokerMaterializationIdentityCompatibility独立初验报告.md`

---

## 8. STATIC_REWORK 复验（P1×2-P2；不擦除上文 REVIEW_FAIL）

日期：2026-08-26
复验角色：同一独立外部初验 Agent（仍只写本报告；未改 production/tests/task/delivery）
授权：`[STATIC_REVIEW_REWORK][M4-UA006-P2-REBUILT][P1x2-P2]` / 任务书 §9 / delivery §8
上文 §0–§7 的 **`REVIEW_FAIL` 原文保留**，不洗白。

### 8.0 复验裁决

**`REVIEW_PASS`**（仅针对授权 STATIC_REWORK 差分；STATIC_ONLY；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network）

原 P1-1/P1-2/P2-1/P2-2 已按 §9 最小合同闭合；`_compare_materialized` / `_policy_business` / `_binding_business` / `_account_business` 相对 exact base **逐函数未改**；未见 P1 canonical 成本身份倒退。无新的 P0/P1。下文 AE-3 为授权范围外残余对抗，**不**构成 FAIL。

本裁决**仍不**等于 Windows VALIDATION / bootstrap / UA-M4-006 Gate。

### 8.1 复验范围哈希（起止一致）

| 路径 | SHA256 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | `E15923E8C855623D2DBD1ADCD23C94D374D552EF29D0B118EE0260F5B1CF429B` |
| `tests/unit/test_paper_formal_broker_store.py` | `F0ADFC21FC7247CE9B5101D38365E346C6300F4CCF8267796273E203B61B56DD` |
| 交付报告 | `9387000E18BF9603294403E431306A088B5F5C832B58445BB7CFCF38B899A5F4` |
| 任务书 | `DE92E4CE627F2A8ABDF0EC0DF85C3A7E823AF7769993D4FD36BD4797E8B14B24` |
| HEAD / cached / `git diff --check` | `6097670…`；cached=0；PASS |

### 8.2 授权返工条对照

| # | 授权要求 | 静态结论 | 证据 |
| --- | --- | --- | --- |
| 1 | store bytes 前 `_require_materialized`；去掉自造 absent 启发式 | **满足** | initialize L192→L193→L197；比较器 L454–465 不再比较 broker 字符串不等；AE-2 期望 `PAPER_FORMAL_STORE_NOT_FOUND`（tests L1073–1114） |
| 2 | 单一 `_require_materialized_chain_closure`：join + 派生相对 cold 必变；final 仍 fresh reload | **满足** | L468–488；capability 仍 `final=_reload_materialized_chain` 后组装（L206–209）；`test_final_capability_binds_fresh_materialized_identities_not_cold`（L1220–1251） |
| 3 | 经济投影补齐非 root 变化公开字段；仅文档化排除 | **满足** | `_policy_economic` 含 schema/source_path/trading_config/schedule 等（L502–525）；binding/account 含 schema 与 account `runtime_config_identity`（L528–566）；docstring/任务书 §9.2 排除 env 派生、`verified_at`、私有 attestation；仍消费 `cost_schedule_identity` |
| 4 | AE-1/AE-2、每一 join、漂移、public 正向、final、rollback/错误码 | **满足** | AE-1 两测（L1020–1070）；AE-2（L1073+）；10 项 join/派生参数化（L1117–1178）；policy/binding/account 经济+schema/source/config 漂移；public 正向保留；rollback/legacy 错误码测保留 |
| 5 | `_compare_materialized` 与 P1 canonical cost 不变 | **满足** | 四函数相对 base `UNCHANGED`；模块无 `_cost_payload` 恢复；tests 仍正/反向断言 `paper_execution_cost_schedule_identity` vs `b1._digest(b1._cost_payload(...))` |

### 8.3 原发现关闭状态

| ID | 关闭？ | 说明 |
| --- | --- | --- |
| P1-1 | **关闭** | join + `policy_identity`/`binding_identity`/`account.verification_identity` 必变 |
| P1-2 | **关闭** | mkdir 后 `_require_materialized`；另一 `absent-*`→`NOT_FOUND` |
| P2-1 | **关闭** | schema/source/config/schedule/account `runtime_config_identity` 已入经济投影 |
| P2-2 | **关闭** | AE-1/AE-2 与扩展漂移/join 测已落地 |

### 8.4 实现者未使用的新对抗（AE-3）

### AE-3 — 经济与 join 全绿，但 sibling 携带伪造派生身份或无效私有 attestation

| 字段 | 内容 |
| --- | --- |
| 现象 | 在 `_allow_chain` 全量替换 public loader 的前提下：构造 materialized 链使 verification/layout 已变、经济投影与 cold 相等、`_require_materialized_chain_closure` 全部 join/必变字面量满足，但 (a) `policy.policy_identity` 为任意新伪造串（非对应当前 env+经济字段的真实 `_sha256` 载荷），或 (b) `policy._attestation` / binding/account 私有 attestation 为无效字节（如 `b""` / `b"test"`），public 字段外表合法。 |
| 根因 | 本包闸门按授权只做经济投影 + sibling 字面 join + 派生相对 cold 不等 + 物化在场；**不**在 formal-store 内重算 policy/binding/account HMAC，也不调用各模块 `verify_existing_*` 复核 materialized 对象（私有 attestation 被任务书 §9.2 明确排除出经济投影）。`build_formal_paper_broker_policy_descriptor` 亦不验 attestation token（只验 type/字段 join/canonical cost）。 |
| 应遵循规则 | 任务书 §9.2 排除私有 attestation；生产权威仍是各 public loader 签发的 process-local capability。全量 monkeypatch 替换 loader 后，字面 join 无法恢复密码学签发语义——这与 fixture 自身使用 `_PolicyAttestation(b"test")` 的测试模型一致。 |
| 最小复现（静态，未执行） | `_chains` 正常 materialized 上 `replace(policy, policy_identity="ab"*32)` 并同步 binding/account 的 `execution_policy_identity`；或 `object.__setattr__(policy, "_attestation", paper_policy._PolicyAttestation(b""))` 保持其余字段。`_require_materialized` + `_compare_cold_materialized` **将通过**；随后 descriptor/store 亦可在 patched 链上继续。对照：实现者已覆盖的 join **失配** / AE-1 复用 cold 身份会 STALE。 |
| 通过条件 / 裁决 | **不构成 REVIEW_FAIL**：属 loader 信任边界与授权排除项下的残余敌意面；诚实 public 链（未 patch loader）由签发模块保证 attestation 与 identity 载荷一致，且 `_reload_materialized_chain`→`_compare_materialized`（含 `policy_identity`）在双次真实加载间仍完整。若未来要 fail-closed 此面，需另授权在 store bytes 前对 materialized 调用各 `verify_existing_*`（超出本返工 exact 合同）。 |
| 分级 | **残余风险（非 P0/P1）** |

### 8.5 发现分级（复验）

- **无新 P0 / P1**
- **无未关闭的原 P1/P2**
- 残余：AE-3；binding `fx_snapshot_identity` 等个别经济字段未单列参数化（同学段闸门已在投影内，覆盖面残余）

### 8.6 未运行边界（复验仍强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite | **未运行** |
| 网络 / PAPER / soak / browser | **未运行** |
| stage / commit | **未执行** |
| Windows 验证 / Gate / UA-M4-006 | **不声称**；本 `REVIEW_PASS` 仅解除「因本包初验 FAIL 而不得申请」的阻断，申请与执行仍归中央 |

### 8.7 复验结论

**REVIEW_PASS**（STATIC_REWORK）

上文历史 **REVIEW_FAIL** 保留作审计链。返工后 exact5 静态满足物化在场、join/派生必变、经济投影闭合、AE-1/AE-2 与 join 矩阵、final fresh 绑定、rollback/错误码锁定，以及 P1 cost / `_compare_materialized` 不漂移。下一步仅可申请任务书规定的 Windows 验证序列。

---

## 9. STATIC_REWORK 复验（VALIDATION2 F3–F5；保留全部历史）

日期：2026-08-26
复验角色：同一独立外部初验 Agent（只写本报告；未改 production/tests/task/delivery）
授权：`[STATIC_REVIEW_REWORK][M4-UA006-P2-REBUILT][VALIDATION2 F3-F5]` / 任务书 §10 / delivery §9
上文 §0–§7 `REVIEW_FAIL` 与 §8 `REVIEW_PASS`（P1×2-P2）**原文保留**。

### 9.0 裁决

**`F3_F5_REVIEW_PASS`**（STATIC_ONLY；**未**跑 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network）

F3–F5 授权合同静态闭合：materialized 段在 store bytes 前经 `_verify_existing_chain` 再验并采用返回链；`_require_materialized` 仅物理 `is_dir()`；无 `"absent"` 子串语义；敌意 cold/forged layout 在真实 preflight 下 → `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID` + 空 root 回滚；public 正向/F5 错误码与既有 P1×2/P2/join/canonical cost/`_compare_materialized` 闭包保持。无新 P0/P1。

本裁决**仍不**等于 Windows VALIDATION 全绿或 UA-M4-006 关闭。

### 9.1 复验范围哈希（起止一致）

| 路径 | SHA256 |
| --- | --- |
| `src/quant/execution/paper_formal_broker_store.py` | `42C2916C3391C6F7F283D0264130FCBD36202DAA30582C1DE43A78C9AE6C55C4` |
| `tests/unit/test_paper_formal_broker_store.py` | `64DCB551496DFFCADEFF116CFEA4CE1BE02D15A6F0C3113D8725520977B0747D` |
| 交付报告 | `AFBF4ADAFDBA151D491F635FAC5D0074F9E54BD05AC2F7EA4EBC338F5CDD1AA1` |
| 任务书 | `6B891011B30252F975EE38A23C49507F58FC5621D6CD276119D0AC5ED5DB8781` |
| HEAD / cached / `git diff --check` | `6097670…`；cached=0；PASS |

### 9.2 授权条对照

| # | 合同 | 结论 | 证据 |
| --- | --- | --- | --- |
| F3.1 | materialized 组装后 `_verify_existing_chain` → 采用返回 fresh 对象 → 再 `_require_materialized` / compare | **满足** | `paper_formal_broker_store.py` L186–200：`materialized = _verify_existing_chain(...)` 覆盖原元组；其后 L199–200；store 在 L204+ |
| F3.2 | `_require_materialized` 仅物理目录；真实性靠 preflight | **满足** | L699–706 仅 `broker_root.is_dir()`→`NOT_FOUND`；docstring 明确 SHA opaque；模块内 `"absent"` 字面量计数=0 |
| F3.3 | 禁止 private digest/string marker；rollback/错误归一不改 | **满足** | 无 `_cost_payload`/absent marker；失败路径 L225+ / `_remove_owned_empty_root` 未改语义 |
| F4 | 去 substring；物理缺失 + hex64 快照；init 后 identity 变化 | **满足** | tests 无 `"absent"`；public 正向 L715–747：`not exists`、`len==64`、`[0-9a-f]`、后 `is_dir`、`capability.broker_root_identity != cold` 且等于 materialized |
| F5 | 物化后 cold env → `ENVIRONMENT_INVALID`（非 STALE） | **满足** | L825–834；loader stale-env L1472–1531（cold preflight 一次放行，其后真实 preflight，`count>=2`） |
| 敌意 cold layout | 真实 preflight 激活 → `ENVIRONMENT_INVALID` + 空 root 回滚 | **满足** | `test_ae2_forged_cold_layout_after_mkdir_fails_environment_invalid` L1084–1121 |
| 先验闭包 | P1×2/P2 join/经济/canonical cost/`_compare_materialized` | **保持** | `_compare_materialized`/`_policy_business`/`_binding_business`/`_account_business` 相对 base **UNCHANGED**；`_require_materialized_chain_closure` 仍在；经济投影仍含 `cost_schedule_identity`；AE-1/join/rollback 测仍在 |

### 9.3 控制流（store bytes 前）

静态顺序：

1. cold `_verify_existing_chain`
2. mkdir
3. materialization loaders 组装元组
4. **`materialized = _verify_existing_chain(...)`**（preflight + 返回 fresh policy/binding/account；environment 为经 preflight 校验的同一对象）
5. `_require_materialized`（物理 `is_dir`）
6. `_compare_cold_materialized`（经济 + join/派生必变）
7. 才 `initialize_paper_broker_store`

敌意/forged layout 在步骤 4 即以 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID` 失败，不进入步骤 7。

### 9.4 实现者未使用的新对抗（AE-4）

### AE-4 — joins/经济可过，但 materialized env 的 preflight attestation/layout 陈旧

| 字段 | 内容 |
| --- | --- |
| 现象 | 与实现者 AE-2（整棵 cold 复用）不同：构造 **字面 join 已闭合** 的伪 materialized 链——`verification_identity`/`layout_identity`/broker hex 已相对 cold 变更，binding/account 的 env/policy/binding 指针对齐，经济投影与 cold 相等——但 environment `_attestation` 无效，或 `layout` 与 mkdir 后磁盘真实 layout 投影不一致（陈旧 retained layout）。 |
| 根因对照 | 若无步骤 4 再验，步骤 5–6 可能把该伪链当成合法物化（物理目录已存在 + 经济/join 字面量满足）。 |
| 应遵循规则 | 任务书 §10.2：真实性由 `_verify_existing_chain` 内 public preflight（`_verify_environment_attestation` / `_verify_retained_layout` / 与 `verify_paper_runtime_environment` 投影比对）供给；物理在场与 attestation 分离。 |
| 最小复现（静态，未执行） | public cold → 允许真实 cold 链；mkdir 后 patch materialization loaders 返回上述「join 闭合但 attestation/layout 陈旧」的 env+对齐 siblings；**不** patch `verify_existing_paper_runtime_preflight`。步骤 4 preflight 抛错 → formal 归一 `PAPER_FORMAL_STORE_ENVIRONMENT_INVALID`；`broker_root` 被空 root 回滚；步骤 7 不执行。对照：实现者 AE-2 用 cold 整树复用（派生身份亦未变）；本 AE-4 隔离「字面 join 绿、preflight 红」。 |
| 通过条件 | 现码控制流满足；拒绝发生在 store bytes 前。 |
| 分级 | **非缺陷**（确认闸门）；不构成 FAIL |

### 9.5 发现分级

- **无新 P0 / P1 / P2**
- F3/F4/F5 授权项全部静态满足
- 残余：fixture `_allow_chain` 仍可 no-op preflight 以测经济/join（有意）；生产/AE-2/AE-4 路径依赖真实 preflight——与合同「真实性由 public preflight 供给」一致

### 9.6 未运行边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite | **未运行**（本复验） |
| 网络 / PAPER / soak / browser | **未运行** |
| stage / commit | **未执行** |
| Windows VALIDATION 重跑 / Gate | **不声称**；本 PASS 仅支持中央重申请 focused+后续序列 |

### 9.7 复验结论

**F3_F5_REVIEW_PASS**

历史 FAIL（§0–§7）与 P1×2-P2 PASS（§8）保留。F3–F5 返工使物化后再验、物理在场与 opaque SHA 语义分离，并修正 F4/F5 断言；AE-4 确认伪造 env 在 join 表象下仍被 preflight 挡在 store 之前。

---

## 10. STATIC_REWORK 复验（VALIDATION3 F6；保留全部历史）

日期：2026-08-26
复验角色：同一独立外部初验 Agent（只写本报告；未改 production/tests/task/delivery）
授权：`[STATIC_REVIEW_REWORK][M4-UA006-P2-REBUILT-F6]` / 任务书 §11 / delivery §10
上文 §0–§9 历史裁决**原文保留**。

### 10.0 裁决

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
