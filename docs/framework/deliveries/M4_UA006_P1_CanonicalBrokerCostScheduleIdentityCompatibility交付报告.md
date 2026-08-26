# M4-UA006-P1 Canonical Broker Cost Schedule Identity Compatibility 交付报告

日期：2026-08-26<br>
状态：`CANONICAL_BROKER_COST_IDENTITY_COMPAT_VALIDATED`（VALIDATION2 全绿；**P2 / bootstrap / PAPER / soak / UA-M4-006 仍 OPEN**；不等于主验合流或 Linux Gate）<br>
task id：`M4-UA006-P1-CANONICAL-BROKER-COST-IDENTITY-COMPAT`<br>
exact base / HEAD：`1d9b4e09c91293de18fea5cf0aa563b782379d37`<br>
branch：`codex/m4-ua006-p1-canonical-broker-cost-identity-compat`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p1-canonical-broker-cost-identity-compat`

## 1. 现象—根因—规则—最小复现—新增测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | 合法 fresh policy 的 `cost_schedule_identity` 无法通过 `build_formal_paper_broker_policy_descriptor`，formal store 归一为 `PAPER_FORMAL_STORE_INVALID` |
| 根因 | policy 使用 `paper-execution-cost-schedule-identity-v1` canonical payload；formal descriptor 却用本地 `_digest(_cost_payload(...))`（含 `"type":"ExecutionCostSchedule"`、字段/`str(Decimal)` 结构不同）复核 |
| 规则 | 同一 `ExecutionCostSchedule` 只允许一个 canonical identity 函数；consumer 不得复制第二 payload，不得信任自述字符串或删复核绕过 |
| 最小复现 | 真实 public initializer → `paper_formal_broker_store` 调 formal descriptor → `PAPER_BROKER_POLICY_INVALID`；trace SHA `d80142bd6b987d9a76e55616f14358a92eb13fe110f82387f3715c3fa80c0338` |
| 新增测试 | `test_paper_policy.py`：冻结 SHA、loader 相等、语义等价、经济漂移、period 缺失/额外、非 exact 类型；`test_paper_broker_store.py`：formal 成功+schema、stale/自述/binding/session/规则漂移、伪造/`__new__`/非 exact schedule、monkeypatch fail-closed、issued registry、non-formal bytes/identity 回归 |
| 通过条件 | REVIEW_PASS 后 Windows VALIDATION：identity → 两 test 文件 → Ruff production2/tests2 → mypy production2 → cold production2 → exact7 scope/diff/temp/process；首失败 STOP |

## 2. Public API 名（逐字）

`paper_execution_cost_schedule_identity(schedule: ExecutionCostSchedule) -> str`

- 模块：`quant.execution.paper_policy`
- 风格对齐：`trading_config_identity` 名词式 + schema `paper-execution-cost-schedule-identity-v1`
- 只接受 `type(schedule) is ExecutionCostSchedule`；不导出到 `quant.execution` 包根
- 删除私有 `_cost_schedule_identity`；loader 与 `_policy_payload` 的 fresh 复核均只调该 public 函数

## 3. 实现摘要

- `paper_policy.py`：原 `_cost_schedule_identity` 算法原样公开为上节函数（payload 版本、字段、`format(..., "f")`、`effective_to` 恒 `None`、period 顺序、`_sha256`/`_canonical_json` 不变）。
- `paper_broker_store.py`：`build_formal_paper_broker_policy_descriptor` 改为调用 `paper_execution_cost_schedule_identity(policy.execution_cost_schedule)` 与 `policy.cost_schedule_identity` exact 比较；删除 formal 路径上的 `_digest(_cost_payload(...))` 复核。
- 保持不变：non-formal `build_paper_broker_policy_descriptor` 及其 `_cost_payload`/`_digest`、issued registry/weakref、descriptor dataclass、store 初始化/事务、错误码、schema/migration、binding/session/adapter/fill/fault/finality/clock/fx 闭包字段检查。

## 4. Bytes / SHA 兼容证据设计（STATIC，未执行 runtime）

| 冻结项 | 设计值 | 用途 |
| --- | --- | --- |
| formal fixture schedule identity | `9864f09ccbc7be9f30299f74cb4659665765194776844ed36914815a87749f7a` | 与旧 `_cost_schedule_identity` 同算法的 expected；loader 产出必须相等 |
| development `_schedule()` cost identity | `464bc03f41dfe131dad396995b047c1365b2c6b403e991cbffa1ac1da7b7a1a7` | non-formal 路径未改的回归 |
| development descriptor identity | `9dd4dcb507578098ff946a2e57607ff03840af0f0b482b9283b3126233c12db1` | non-formal descriptor bytes/identity 未改 |

冻结 SHA 由与 Python `json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",", ":"))` 等价的 UTF-8 canonical bytes 经 SHA-256 离线计算；正式采信以 VALIDATION 跑测为准。

## 5. exact 变更路径

初轮实现者写集（1–4、6）及 exact8 返工（8、6）：

1. `src/quant/execution/paper_policy.py`
2. `src/quant/execution/paper_broker_store.py`
3. `tests/unit/test_paper_policy.py`
4. `tests/unit/test_paper_broker_store.py`
5. （经理）任务书 — 本实现未改（经理已写 §6 exact8）
6. `docs/framework/deliveries/M4_UA006_P1_CanonicalBrokerCostScheduleIdentityCompatibility交付报告.md`（本文件；含 §9 返工）
7. （独立 reviewer）初验报告 — 本实现未写
8. `tests/unit/test_paper_formal_broker_store.py`（exact8 返工：fixture + legacy digest 回归）
## 6. STATIC_ONLY 未运行边界

强制 STATIC_ONLY：零 Python、pytest、Ruff、mypy、cold、SQLite、PAPER、network/browser、stage/commit。本报告中的冻结 SHA 与代码审阅为静态证据，**不采信**为 VALIDATION / Gate。

## 7. STOP

无。未改 formal store/bootstrap/schema/migration/config；未复制第二 payload；未放宽 non-formal；policy identity 算法 bytes 意图保持逐字兼容。

说明（初验前）：白名单外既有 `test_paper_formal_broker_store.py` fixture 仍用 broker-local `_digest(_cost_payload)`；初验 AE-2 披露后由中央扩为 exact8，见 §9。

## 8. STATIC 退出核对（初轮 exact7）

- HEAD = exact base `1d9b4e09c91293de18fea5cf0aa563b782379d37`
- cached=0；`git diff --check` PASS（实现退出时核对）
- dirty ⊆ exact7（任务书 untracked + 本写集）
- 无 runtime root / SQLite / cache / 临时文件 / 凭据 / 为验证拉起的进程

## 9. exact8 返工：formal-store fixture 对齐（STATIC_ONLY）

| 项 | 内容 |
| --- | --- |
| 现象 | 初验 AE-2 / 任务书 §6：`test_paper_formal_broker_store.py` fixture 仍以 `b1._digest(b1._cost_payload(schedule))` 填 formal policy 成本身份；合入 canonical formal 复核后，既有 formal-store 单测会稳定变红 |
| 根因 | 历史 fixture 用 broker-local digest 伪造“已验证”policy，与唯一 SSOT `paper_execution_cost_schedule_identity` 不一致；非 production 第二算法，属测试债 |
| 规则 | exact8 仅改该测试文件：fixture 改用公开 canonical identity；保留旧 broker-local digest 被 `build_formal_paper_broker_policy_descriptor` 拒绝的回归；不改 formal-store production / schema / migration / API / 其他业务语义 |
| 修正测试 | (1) `_chains` 中 `cost_schedule_identity=paper_policy.paper_execution_cost_schedule_identity(schedule)`；(2) 新增 `test_legacy_broker_local_cost_identity_rejected_by_formal_descriptor`：`legacy=_digest(_cost_payload)` ≠ canonical，且 `replace` 后 formal descriptor 稳定 `PAPER_BROKER_POLICY_INVALID` |
| 通过条件 | 原独立 reviewer 复验 exact8；Windows 验证扩为三测试文件 + Ruff production2/tests3 + mypy/cold production2 + exact8 scope；本轮 STATIC_ONLY 未跑 runtime |
| exact8 扩围历史 | 中央确认 AE-2 后将白名单由 exact7 精确扩为 exact8，新增且仅新增 `tests/unit/test_paper_formal_broker_store.py`（任务书 §6）；经理更新任务书；本轮实现者只写该测试 + 本交付追加 |

本轮写集：`tests/unit/test_paper_formal_broker_store.py`、本交付报告。未改 production、taskbook、review、其他 tests。

STATIC 退出（返工轮）：HEAD 仍为 exact base；cached=0；dirty ⊆ exact8；`git diff --check` PASS；零 Python/pytest/Ruff/mypy/cold/SQLite/network/stage/commit。

## 10. VALIDATION1 F1：issued 可观察身份断言（STATIC_ONLY）

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION1：`test_issued_formal_descriptor_required_for_store` 在成功 `initialize_paper_broker_store(..., policy=issued)` 后断言不存在的 `store.policy_descriptor` |
| 根因 | 生产公开面为 `store.policy_identity`（底层 `store.descriptor.policy_identity` 持久化输入 descriptor 的 `descriptor_identity`）；测试误把输入 `PaperBrokerPolicyDescriptor` 对象名当作 store API |
| API 规则 | 不得为测试新增 production 属性或改 issued registry；用现有持久化可观察身份断言，例如 `store.policy_identity == issued.descriptor_identity`；保持 clone 拒绝与 issued 正向初始化 |
| 最小复现 | VALIDATION1：Parser/argv/identity PASS → `test_paper_policy.py` `41 passed / 1 skipped` → `test_paper_broker_store.py` `22 passed / 1 failed`（本断言）；formal-store / Ruff / mypy / cold / scope 均 **UNRUN** |
| 修正测试 | 仅改 `tests/unit/test_paper_broker_store.py`：`assert store.policy_identity == issued.descriptor_identity`；clone `PAPER_BROKER_POLICY_INVALID` 与 issued 正向初始化语义不变 |
| 通过条件 | 同一独立 reviewer 复验后申请完整 VALIDATION2（§6 exact8 全序列）；不得把 VALIDATION1 部分绿冒充整包 PASS。本轮 STATIC_ONLY 未重跑 runtime |

VALIDATION1 证据边界（任务书 §8）：identity PASS；41p1skip；22p1fail；随后 formal-store / Ruff / mypy / cold / scope **UNRUN**。本轮写集仅该测试文件与本交付追加；production / taskbook / review / 其他 tests 只读未改。

STATIC 退出（F1 轮）：HEAD 仍为 exact base；cached=0；dirty ⊆ exact8；`git diff --check` PASS；零 Python/pytest/Ruff/mypy/cold/SQLite/network/stage/commit。

## 11. EVIDENCE_UPDATE：VALIDATION1 STOP / F1 / VALIDATION2（中央授权）

本轮 STATIC_ONLY 仅更新任务书 §10 与本交付；未改 production / tests / review；未清 evidence；未 stage/commit。

### 11.1 VALIDATION1 test-only STOP

evidence root：`artifacts/agent_runs/m4-ua006-p1-validation1-20260826T070627Z`

| 检查 | 结果 |
| --- | --- |
| Parser / argv / identity | PASS |
| `test_paper_policy.py` | `41 passed / 1 skipped` |
| `test_paper_broker_store.py` | `22 passed / 1 failed`（`AttributeError: policy_descriptor`） |
| formal-store / Ruff / mypy / cold / scope | **UNRUN** |
| 收口 | `STOP\|STAGE_FAILED:03-broker-test`（test-only；production initializer / issued registry 已越过） |

| 产物 | SHA-256 |
| --- | --- |
| policy stdout | `c368cd21ecf1c43f9c540b2aa3a9ad08158f66994388ef752ef346cdd1e8803a` |
| broker stdout（fail） | `3f1527bb4cf7e4690f0120f4447921ebc9c32f4e9f6ba71e9ad5adf07abbc4d1` |
| stage-summary | `48075e64c8f90ac593ef3f36c406f923ce18135f2ccb1b1ce18630ade978eee0` |

### 11.2 F1 修复与复验

- 实现：`assert store.policy_identity == issued.descriptor_identity`（交付 §10）
- 独立 reviewer：`F1_REVIEW_PASS`（review 报告 F1 节）
- 不得把 VALIDATION1 部分绿冒充整包 PASS

### 11.3 VALIDATION2 完整结果（全绿）

evidence root：`artifacts/agent_runs/m4-ua006-p1-validation2-20260826T071606Z`

| 检查 | 结果 |
| --- | --- |
| Parser / argv / identity | PASS |
| `test_paper_policy.py` | `41 passed / 1 skipped` |
| `test_paper_broker_store.py` | `23 passed` |
| `test_paper_formal_broker_store.py` | `10 passed` |
| Ruff production2 / tests3 | PASS |
| mypy production2 | PASS（2 source files） |
| cold production2 | PASS |
| exact8 / cached=0 / diff / temp / process | PASS |

| 阶段产物 | SHA-256 |
| --- | --- |
| identity stdout | `d3f92b05c951e98281bf950830cc1f69232479dab78859fe5a747d605294f729` |
| policy stdout | `274cec6b8c8778287e0f094c5b7d5a476de7e636b2fabf8b85cc1d44274f7eca` |
| broker stdout | `4406df172c0465a9e8744d71e2bc180564f0500119883e7261094f9d8ea72c82` |
| formal-store stdout | `d9127496e149251bf4c7376fa5316eea7c26af8dd5c75ed34ce491892b81331e` |
| Ruff stdout | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` |
| mypy stdout | `07a5ca23e5d39b2565c0c1361f0556b8c3c75484bba05841f400436d190bb660` |
| cold stdout | `5aa38f80adebfeec03117f022acfed25029347bdda8093d301a91eb0495d2283` |
| scope status | `7bdb9e254de9d8dfec696c4703a9ffc2a04984a3a23203fa8c7b31b3bea2c3a0` |
| stage-summary | `75b54b072c89d1437cf5746d0b3bfba17e2eaccec9aed08622834e3a1e5437d5` |

收口声明：仅 `CANONICAL_BROKER_COST_IDENTITY_COMPAT_VALIDATED`；**P2 / bootstrap / PAPER / soak / UA-M4-006 仍 OPEN**。

DELIVERY_READY docs/framework/deliveries/M4_UA006_P1_CanonicalBrokerCostScheduleIdentityCompatibility交付报告.md
