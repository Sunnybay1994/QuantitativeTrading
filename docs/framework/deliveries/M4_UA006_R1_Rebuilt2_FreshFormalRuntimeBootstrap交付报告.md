# M4-UA006-R1 Rebuilt2 Fresh Formal Runtime Bootstrap 交付报告

日期：2026-08-26
状态：`EVIDENCE_UPDATE_READY`（source merge-regression fix Windows validated；**不等于** main `937787` 回归解除、UA-M4-006 关闭、PAPER、soak、Linux Gate）
task id：`M4-UA006-R1-REBUILT2-FRESH-FORMAL-RUNTIME-BOOTSTRAP`
exact base / HEAD：`74586cea97ba93aa3e25cca0dd4921cf214de54c`（source branch；本轮未 stage/commit）
branch：`codex/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`
worktree：`artifacts/dev_worktrees/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`
角色：原实现者续任 EVIDENCE_UPDATE（仅任务书 + 本 delivery；production/tests/review 冻结；零 Python）

## 1. 现象—根因—应遵循规则—最小复现—新增测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | P1 canonical LF formal config 与 P2 broker first-materialization 经济投影已合流，但仍缺少 new root/new epoch 的 fail-closed formal runtime bootstrap 组合入口 |
| 根因 | broker/OMS 公共 initializer/verifier 已存在，但调用方需自行保证：exact Path、五 sibling 全 absent、cold→broker materialization→OMS（内建 session barrier）→fresh verify→OPEN reopen，且失败时不得删除含 broker 正式 bytes 的路径 |
| 应遵循规则 | 只组合已合流 public API；不得改 broker store/policy/account/config/schema/migration/barrier/formal composition；不得归一化 CRLF/BOM；不得 patch `_actual_project_root`/`_system_temp_root`；initializer 失败只回滚本次 identity 闭合且不含 broker 正式 bytes 的路径；错误码稳定且不泄露路径/config bytes |
| 最小复现 | exact concrete absolute `config_path` + UTC `now` + `session_date` → cold 链 → `initialize_verified_formal_paper_broker_store` → fresh materialized 链 → `initialize_verified_formal_paper_execution_store` → capability 身份闭合；reopen 只走 open/verify，不跑 initializer |
| 新增测试 | `tests/unit/test_paper_formal_bootstrap.py`、`tests/integration/test_paper_formal_bootstrap.py`（映射任务书 §7 反例；集成测试要求中央批准 basetemp，且不 patch 两个禁止根探测函数） |
| 通过条件 | STATIC dirty ⊆ exact7 之实现者路径 1–4、6；任务书只读；无 review 路径；cached=0；`git diff --check` PASS；无 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network 运行产物；独立 REVIEW_PASS 后另申请 Windows 验证 |

## 2. 实现摘要（exact scope）

### 2.1 Production

1. `src/quant/execution/paper_formal_bootstrap.py`（new）
   - `FormalPaperBootstrapError`：稳定码；`str(error)==code`；切断 `__cause__`/`__context__`
   - `VerifiedFormalPaperRuntimeBootstrap`：冻结、HMAC attestation、禁 pickle/copy/deepcopy/replace；不暴露 raw token/SQLite/private store
   - `bootstrap_fresh_formal_paper_runtime(*, config_path, session_date, now)`
   - `reopen_verified_formal_paper_runtime(*, config_path, session_date, now)`
   - `verify_existing_formal_paper_runtime_bootstrap(*, bootstrap, now)`
   - 显式顺序（依赖闭合，对应任务书 §4 叙事）：
     1. exact concrete Path 门禁 + public `load_paper_runtime_config`（双读防漂移）+ formal mode
     2. 五 sibling root 全 absent 门禁 + public cold environment/policy/binding/account
     3. public broker initializer（P2 cold→materialized 经济兼容由其内部完成）
     4. fresh materialized 链 + public OMS initializer（其内部创建并固定 formal session barrier / new epoch）
     5. fresh verifier 重验；最终 capability 绑定 materialized identity；要求 barrier `OPEN`
   - OMS 失败且 broker 已物化：不删除 broker 正式 bytes，稳定 `PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED`
   - reopen：只 `open_*` + verify；拒绝 partial / 非 OPEN；零 initializer

2. `src/quant/execution/__init__.py`
   - lazy export bootstrap 错误类型、结果类型与三个 public 入口

### 2.2 Tests

3. `tests/unit/test_paper_formal_bootstrap.py`
   - Path subclass / PurePath / relative / 非 Path
   - 非 UTC now、错误 session_date 类型
   - 已存在/partial root、nested、cross-parent（initializer 前 fail-closed）
   - public 调用序与 cold≠final identity
   - OMS 中途失败 → `ROLLBACK_REQUIRED`
   - CLOSING reopen 拒绝且不调用 initializer
   - pickle/copy/伪 attestation 拒绝
   - verifier 返回错类型 → fail-closed
   - 返回 bundle 身份字段闭合、无路径泄露

4. `tests/integration/test_paper_formal_bootstrap.py`
   - 真实 public fresh bootstrap → verify → close → reopen 身份闭合
   - partial root；CLOSING（public `transition_formal_session_barrier_to_closing`）拒绝 reopen
   - CRLF 不改写文件；BOM fail-closed
   - 明确不 patch `_actual_project_root` / `_system_temp_root`；无批准 basetemp 时 skip

### 2.3 Delivery

6. 本交付报告

### 2.4 未写 / 只读

5. 任务书：只读（经理所有）
7. 独立初验报告：**未创建、未修改**
- 未改：broker store、policy/account loader、config、schema、migration、ExecutionStore/PaperBrokerStore、session_barrier、formal composition、roadmap、共享 SSOT

## 3. 任务书 §4 顺序与 public API 依赖说明

任务书叙事步骤 2「创建 formal session barrier」在已合流 public API 中由 `initialize_verified_formal_paper_execution_store` 内部完成（需要已物化 broker capability 与 OMS store identity）。因此 bootstrap **不**在 broker 之前单独调用 `build_session_barrier_capability`，避免手工 descriptor/伪造身份。实现顺序为 cold 链 → broker init → OMS init（含 barrier）→ fresh verify，与 public 依赖一致，且不复制 barrier/P2 投影逻辑。

## 4. STATIC_ONLY 未运行边界（UNRUN）

本会话**强制未运行**：

- 任何 Python 解释器业务执行 / cold import / SQLite probe
- pytest（unit/integration 均 UNRUN）
- Ruff / mypy
- 真实 formal root / PAPER / soak / network / worker
- stage / commit / merge
- 读取旧 R1 / R1-rebuilt STOP/evidence worktree

因此：**不得**宣称 Windows engineering validated、产品绿或 UA-M4-006 关闭。

## 5. STOP

无 `CONTRACT_STOP`。exact7 足够；public P2 API 足以完成首次 broker materialization；ownership/rollback 边界可在 bootstrap 层证明（broker 正式 bytes 不删，改人工清理码）；未扩白名单；未第二 writer。

## 6. 静态退出核对

| 检查 | 结果 |
| --- | --- |
| HEAD / exact base | `9cc5b56d176a18aa468386b369d550be73051edb` |
| branch / worktree | 与任务书一致 |
| 实现者 dirty | `paper_formal_bootstrap.py`、`execution/__init__.py`、unit/integration tests、本 delivery |
| 任务书 | 既有 untracked，本会话未改 |
| review 路径 | 初验报告由 reviewer 写入；实现者 **未修改** |
| `git diff --check` | PASS |
| stage/commit | 无 |
| UA-M4-006 | 仍 OPEN |

## 7. 建议 Windows 验证顺序（本交付不执行）

REVIEW_PASS 后另申请资源：identity → focused unit+integration → Ruff production2+tests2 → mypy production2 → cold production2 → exact7 scope/diff/temp/process。pytest `--basetemp` 必须为中央批准的同卷、项目外、非 system-temp、no-clobber 根。

## 8. 收口声明

`DELIVERY_READY` / `FRESH_FORMAL_BOOTSTRAP_STATIC_DELIVERED`。

**仍 OPEN / 禁止宣称**：`FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、真实 PAPER、soak、Linux Gate、单轮全量 Gate。

---

## 9. STATIC_REWORK1（针对 REVIEW_FAIL P1×1 + P2×4）

日期：2026-08-26<br>
依据：任务书 §9 F1–F6；只读初验报告 `docs/framework/reviews/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap独立初验报告.md`<br>
范围：仅路径 1–4、6；任务书/review 未改；exact base/worktree 未漂移；UA-M4-006 仍 OPEN；全部运行检查继续 **UNRUN**。

### 9.0 首轮覆盖声明纠正

首轮交付将 `test_fresh_bootstrap_uses_public_sequence_and_rejects_stale_cold` 表述为覆盖 stale-cold 拒绝，**不实**：该测仅断言正向顺序，从不 `raises STALE`。<br>
首轮亦未覆盖：broker↔chain 字段级闭合、OPEN barrier 全身份集合、CLOSED 公共终端链、经济字段漂移、config symlink、absent 后 TOCTOU 植入 broker root、wrong barrier 身份参数化。本轮按 F1–F6 补齐并以下表为准。

### 9.1 F1 — broker capability ↔ chain 字段级闭包

| 项 | 内容 |
| --- | --- |
| 现象 | `mint` 仅用 `is`/总 capability/gateway/account_id；结果摘要与 `broker_store` 派生身份可分叉 |
| 根因 | 组合根未落实 §7.8 逐项闭合 |
| 应遵循规则 | 任务书 §4.5、§7.3、§7.8、§9 F1 |
| 最小复现 | forged `broker.execution_policy_identity` ≠ chain policy identity 仍可能伪成功 |
| 生产改动 | `_require_broker_matches_chain` + `_require_result_broker_field_closure`；逐项比对 env/policy/binding/account/config/session/account_id/gateway/root/layout |
| 新增测试 | `test_forged_broker_chain_field_fork_is_stale`；正向 `test_fresh_bootstrap_public_sequence_and_field_closure` + 集成逐字段断言 |
| 通过条件 | 分叉 → STALE 并在 broker bytes 后抬升 `ROLLBACK_REQUIRED`；正向 broker 派生字段与 result 全等 |

### 9.2 F2 — fresh materialized 不得回灌 cold

| 项 | 内容 |
| --- | --- |
| 现象 | reload 不要求 policy/binding/account 离开 cold；verifier 透传时 cold 链可进 OMS |
| 根因 | 组合层缺少 leave-cold 与 public join |
| 应遵循规则 | §6.4、§7.3、§9 F2 |
| 最小复现 | 新 env + cold policy/binding/account + verifier 透传 → 旧码不因 chain 侧 cold 失败 |
| 生产改动 | `_require_materialized_left_cold`、`_require_public_chain_join`（仅公开字段）；OMS 前强制调用 |
| 新增测试 | `test_reload_cold_policy_passthrough_rejects_before_oms`（直接断言 STALE helper + OMS 调用 0） |
| 通过条件 | cold 回灌在 OMS 前拒绝；OMS 调用计数 0 |

### 9.3 F3 — OPEN barrier 身份集合完整

| 项 | 内容 |
| --- | --- |
| 现象 | OPEN 闸缺 `session_date`/`broker_store_identity`/`lock_identity` |
| 根因 | 子集核验 |
| 应遵循规则 | §4.2、§7.6、§9 F3 |
| 最小复现 | OPEN row 但上述字段与 capability 漂移 |
| 生产改动 | `_require_open_barrier` 全量闭合 + 双读；result 增加 `barrier_lock_identity` |
| 新增测试 | `test_open_barrier_wrong_identity_fields_reject_without_initializer`（参数化 8 字段） |
| 通过条件 | 任一分叉 → `BARRIER_STATE_INVALID`；零 initializer |

### 9.4 F4 — CLOSED 与经济漂移；纠正名不副实测

| 项 | 内容 |
| --- | --- |
| 现象 | 无 CLOSED；无经济漂移；名含 rejects_stale_cold 的测不拒绝 |
| 根因 | 测试缺口 + 命名夸大 |
| 应遵循规则 | §5、§7.4、§7.6、§9 F4 |
| 最小复现 | 公共 CLOSING→CLOSED 后再 reopen；cost_schedule 等经济字段漂移 |
| 生产改动 | `_require_economic_stability`（公开字段；不复制 P2 私有投影） |
| 新增测试 | 单元 CLOSED/CLOSING reopen；`test_economic_source_schedule_drift_rejects_materialization`；集成 `test_public_closed_barrier_rejects_reopen_with_zero_initializer`；删除/更正名不副实正向测为 `test_fresh_bootstrap_public_sequence_and_field_closure` |
| 通过条件 | CLOSED reopen 稳定拒绝；经济漂移 OMS 前拒绝 |

### 9.5 F5 — TOCTOU 与真实路径反例

| 项 | 内容 |
| --- | --- |
| 现象 | 无 symlink config；无「二次 absent 后植入 broker root」 |
| 根因 | 对抗测缺失 |
| 应遵循规则 | §3、§7.1–§7.2、§9 F5 |
| 最小复现 | 第二次 absent 后 mkdir broker_root；config 叶 symlink |
| 生产改动 | 无（映射 `ALREADY_EXISTS→ROOTS_NOT_ABSENT` 已存在）；测试锁定 |
| 新增测试 | `test_toctou_broker_root_after_second_absent_check`；`test_config_symlink_leaf_is_rejected_without_patching_path_authority`；保留 partial/nested/cross-parent |
| 通过条件 | 稳定 `ROOTS_NOT_ABSENT`/config invalid；不 patch path authority |

### 9.6 F6 — 伪造与 rollback 边界不回退

| 项 | 内容 |
| --- | --- |
| 现象 | 返工可能削弱伪造拒绝或误删 broker bytes |
| 根因 | 新增闸可能改变失败时机 |
| 应遵循规则 | §5、§9 F6 |
| 最小复现 | pickle/伪 attestation；OMS 失败于 broker bytes 之后 |
| 生产/测试 | 保留 pickle/copy/伪 attestation/错类型 verifier；OMS 失败仍 `ROLLBACK_REQUIRED`；无 parent 递归删、无静默 adopt |
| 通过条件 | 既有伪造/rollback 测继续表达；delivery 诚实 UNRUN |

### 9.7 STATIC_REWORK1 退出核对

| 检查 | 结果 |
| --- | --- |
| exact base / branch / worktree | 未漂移 |
| 实现者写集 | 仅 1–4、6 |
| 任务书 / review | 只读未改 |
| P2 私有投影 | 未复制（仅公开字段 join/经济稳定） |
| CONTRACT_STOP | 无 |
| Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network | **全部 UNRUN** |
| UA-M4-006 | **仍 OPEN** |

### 9.8 STATIC_REWORK1 收口

`DELIVERY_READY`（STATIC_REWORK1 完成，交回同一独立 reviewer 复验）。

**仍不得宣称**：Windows engineering validated、UA-M4-006 关闭、PAPER/soak/Linux Gate。

## 10. STATIC_REWORK2：binding.cost_schedule_identity public join / 经济稳定

依据任务书 §10 与 `REWORK1_REVIEW_FAIL`（P2-R1 / AE-R1）。写集仅：`paper_formal_bootstrap.py`、直接相关 unit（及必要的 integration）、本 delivery。未改 `__init__.py`、任务书、review、其他生产/测试/配置。未复制/import P2 private 投影 helper。全部运行检查仍 **UNRUN**。

### 10.1 现象—根因—规则—最小复现—新增测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | REWORK1 后 public `_require_public_chain_join` / `_require_economic_stability` 未闭合 `VerifiedFormalPaperBrokerPolicyBinding.cost_schedule_identity`；unit `_binding` fixture 亦未携带该公开字段 |
| 根因 | join 只比对 env/config/policy/account 身份与 session；经济稳定只比对 policy/account 成本相关字段，遗漏 binding 与 policy 的 schedule 对齐及 cold→current binding schedule 稳定 |
| 应遵循规则 | 任务书 §10：`binding.cost_schedule_identity == policy.cost_schedule_identity`；cold/current binding `cost_schedule_identity` exact 相等；保持既有 env→policy→binding→account join；不得复制 P2 private 投影；错配/漂移在 OMS 前 STALE，broker bytes 后仍 elevate `ROLLBACK_REQUIRED`；OMS 调用 0、零写 |
| 最小复现 | materialized reload 返回 binding.schedule≠policy.schedule；或 cold/current 均 join 完整但 binding（及对齐后的 policy）schedule 相对 cold 漂移 |
| 新增测试 | `test_binding_cost_schedule_mismatch_vs_policy_rejects_before_oms`；`test_binding_cost_schedule_cold_current_drift_rejects_before_oms`；happy-path/integration 正向断言 cold/current/policy/binding/result 字段闭合；既有 policy schedule drift 测改为 join 完整后由经济闸捕获 |
| 通过条件 | 生产两处断言就位；两条对抗 OMS=0/零写；正向字段闭合；写集 ⊆ 批准路径；Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network **UNRUN**；UA-M4-006 仍 OPEN |

### 10.2 生产变更（摘要）

- `_require_public_chain_join`：增加 `binding.cost_schedule_identity != policy.cost_schedule_identity` → `PAPER_FORMAL_BOOTSTRAP_STALE`
- `_require_economic_stability`：增加 `cold_binding.cost_schedule_identity != current_binding.cost_schedule_identity` → 同码
- 未引入 P2 `_policy_economic` / 私有投影；未用 `Any`/cast/bool 或总 identity 掩盖

### 10.3 STATIC_REWORK2 退出核对

| 检查 | 结果 |
| --- | --- |
| exact base / branch / worktree | 未漂移 |
| 实现者写集 | 仅 bootstrap.py、unit、必要 integration、delivery |
| `__init__.py` / 任务书 / review | 只读未改 |
| P2 私有投影 | 未复制/import |
| CONTRACT_STOP | 无（exact7 写角色足够） |
| Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network | **全部 UNRUN** |
| UA-M4-006 | **仍 OPEN** |

### 10.4 STATIC_REWORK2 收口

`DELIVERY_READY`（STATIC_REWORK2 完成，交回同一独立 reviewer 复验）。

**仍不得宣称**：Windows engineering validated、UA-M4-006 关闭、PAPER/soak/Linux Gate。

## 11. STATIC_REWORK3：F7 禁用 monkeypatch 扫描自匹配修正

依据任务书 §11。写集**仅**：`tests/integration/test_paper_formal_bootstrap.py`、本 delivery。production、unit、`__init__.py`、任务书、review **字节冻结**。本轮零 Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network/stage/commit（只读绑定 VALIDATION1 既有证据）。

### 11.1 VALIDATION1 证据绑定（诚实；非整包 PASS）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation1-20260826T194000Z` |
| `summary.txt` SHA256 | `1F4065B1C22061370BCBACB9EEB705945BA97D8D708093E6B09DAE3479DB4C51` |
| identity | exit=`0`；stdout_sha256=`7368FAC6B3FA24F60B6C274C19AD58277A877AFB5C33CE79B88C42BE3FB25B3A` |
| focused | exit=`1`；stdout_sha256=`83D89FECAD407E3FDD825B1451ABF8C53F48158B2E91EEC3ED78D50C4C9D3460`；原生尾计数 **`1 failed, 23 passed, 4 skipped`** |
| 唯一失败 | `test_integration_module_does_not_patch_forbidden_runtime_roots`（test-only source self-reference；**非** production 失败） |
| STOP | `STOP=STAGE_FAILED:focused` |
| Ruff / mypy / cold / scope | **全部 UNRUN**（首失败合同） |
| 边界 | outer PowerShell / carrier exit **不**代表产品 PASS、**不**代表 Windows engineering validated、**不**关闭 UA-M4-006；不得继承本失败轮替代完整 VALIDATION2 |

### 11.2 F7 — 现象—根因—规则—最小复现—修正测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | 集成测读取整个自身源码并搜索完整 `monkeypatch.setattr(paper_runtime, "_system_temp_root" / "_actual_project_root")` 字面量；断言行自身含完整 needle → VALIDATION1 必然自匹配红 |
| 根因 | 禁用证明把「断言文本」与「真实测试调用体」混为同一 contiguous substring 扫描面 |
| 应遵循规则 | 任务书 §11 F7：保留不得 monkeypatch 两路径 authority 的强约束；扫描须排除自证明断言；可用不连续片段组合或 AST/窄边界；不得删检查、宽泛 substring、跳过片段漏真实调用、或改 production；正向继续真实 `_actual_project_root()` / `_system_temp_root()`；无批准 basetemp 仍 skip |
| 最小复现 | VALIDATION1 focused：`tests/integration/test_paper_formal_bootstrap.py:354` AssertionError；summary `STOP=STAGE_FAILED:focused` |
| 修正测试 | `_forbidden_paper_runtime_root_patches`：AST 仅计 `monkeypatch.setattr(paper_runtime, <forbidden attr>)` Call；forbidden attr 名以片段组合；合成 Call 源码自证检测器会命中、且组装 needle **不**出现在本文件 on-disk source；basetemp 门禁改用真实 `paper_runtime._system_temp_root()`（去掉 `tempfile.gettempdir` 旁路） |
| 通过条件 | 模块 AST 无 forbidden Call；合成自证命中两 attr；断言文本不构成命中；production/unit/`__init__.py` SHA 相对 REWORK2 不变；本轮 STATIC 检查 **UNRUN**；交同一 reviewer 确认禁用扫描未弱化后申请完整 VALIDATION2 |

### 11.3 STATIC_REWORK3 退出核对

| 检查 | 结果 |
| --- | --- |
| exact base / branch / worktree | 未漂移 |
| 实现者写集 | 仅 integration test + delivery |
| production / unit / `__init__.py` / 任务书 / review | 只读未改 |
| 禁用约束 | 保留并收窄为 AST Call；未删除 |
| Python/pytest/Ruff/mypy/cold/SQLite/PAPER/network | **全部 UNRUN**（本返工轮） |
| VALIDATION1 | 如实保留 23绿/4skip/1失败 + 后续 UNRUN；**非整包 PASS** |
| UA-M4-006 | **仍 OPEN** |

### 11.4 STATIC_REWORK3 收口

`DELIVERY_READY`（STATIC_REWORK3 / F7 完成，交回同一独立 reviewer 只读复验）。

**仍不得宣称**：VALIDATION1 整包 PASS、Windows engineering validated、UA-M4-006 关闭、PAPER/soak/Linux Gate。REVIEW_PASS 后另申请完整 VALIDATION2（不得继承失败轮）。

## 12. EVIDENCE_UPDATE：VALIDATION1 → REWORK3 → VALIDATION2 → SCOPE1

中央授权 EVIDENCE_UPDATE。本轮 **仅** 更新任务书 §12 与本交付 §12；production / tests / `__init__.py` / review **冻结只读**；不清 evidence；零 Python；零 stage/commit。历史 VALIDATION1 失败与 REWORK3 原文保留，不洗白。

### 12.1 VALIDATION1（test-only STOP；非整包 PASS）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation1-20260826T194000Z` |
| summary SHA256 | `1F4065B1C22061370BCBACB9EEB705945BA97D8D708093E6B09DAE3479DB4C51` |
| identity | PASS（exit=`0`） |
| focused | **`23 passed / 4 skipped / 1 failed`**（exit=`1`；stdout_sha256=`83D89FECAD407E3FDD825B1451ABF8C53F48158B2E91EEC3ED78D50C4C9D3460`） |
| 唯一失败 | `test_integration_module_does_not_patch_forbidden_runtime_roots`（断言自匹配；**非** production） |
| Ruff / mypy / cold / scope | **UNRUN** |
| STOP | `STOP=STAGE_FAILED:focused` |

### 12.2 STATIC_REWORK3 / F7（其后）

见本交付 §11：禁用扫描改为 AST Call + 片段组合；保留不得 monkeypatch `_system_temp_root` / `_actual_project_root`；正向使用真实 authority。独立 reviewer 复验后申请 VALIDATION2（不得继承 V1 失败轮）。

### 12.3 VALIDATION2（产品阶段绿；scope carrier STOP only）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation2-20260826T195000Z` |
| summary SHA256 | `F452D75E597840EFDD3680EA4872D5334DB765E949A1AA326DDD3F9D1CB686C6` |
| identity | PASS（exit=`0`；stdout_sha256=`28FA03AB2411236AA8730C84EED73E742A8D3236A8F5EB5BEE429350B4B9D8AE`） |
| focused | PASS；**`24 passed / 4 skipped`**（exit=`0`；stdout_sha256=`48EE027B41C71B0C0D7D66589A621F0673DA931D8CBB870F3BC563ED1CFA34C7`） |
| Ruff exact4 | PASS（exit=`0`；stdout_sha256=`82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18`） |
| mypy production2 | PASS（exit=`0`；stdout_sha256=`0C37C4158C91EF55C724BA017BF6465F26018199BADB08E3FF13F98ACDF056C2`） |
| cold production2 | PASS（exit=`0`；stdout_sha256=`8AD59E6439BDF97156443D8CC0DB99BFC2247DCFB090D709C23C7514111A8487`） |
| scope | **carrier STOP only**（exit=`1`；stderr_sha256=`40C23A68D925658479B74CC99881B7035CA3A4C7347DB83679F01072C22F0029`；runner `Where-Object`/`try` PowerShell 语法；**非** exact7 产品脏集失败） |
| STOP | `STOP=STAGE_FAILED:scope` |

不得把 VALIDATION2 的 outer STOP 表述为产品红，亦不得在 SCOPE1 前宣称 Windows engineering validated。

### 12.4 SCOPE1（exact7 scope 闭合）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation2-scope1-20260826T200000Z` |
| summary SHA256 | `552D75D607B2EA0F3908D784797E1DEC68308381AB96F523EEF2F50825FC596B` |
| status / exact7 | PASS（`ACTUAL_COUNT=7` ⊆ exact7） |
| cached | PASS（cached=0） |
| diff_check | PASS |
| residue / temp | PASS |
| process | PASS |
| 收口 | `PASS=ALL_SCOPE_CHECKS` |

### 12.5 组合口径与退出状态

| 声明 | 是否成立 |
| --- | --- |
| `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED` | **是**（V1 历史失败保留 + REWORK3 + V2 产品绿 + SCOPE1 PASS） |
| UA-M4-006 关闭 | **否**（仍 OPEN） |
| PAPER / soak / Linux Gate | **否**（仍 OPEN） |
| 主验合流 / 实盘准入 | **否** |

### 12.6 EVIDENCE_UPDATE 收口

`EVIDENCE_UPDATE_READY`

写集核对：仅任务书 + 本 delivery；production/tests/`__init__.py`/review 未改；evidence 未清；未 stage/commit。

## 13. STATIC_REWORK：main merge-regression（policy identity gate）

中央批准。main 已 merge `937787bc` 但回归 STOP；本 source branch tip `74586cea`（clean tracked + ignored evidence）。STATIC_ONLY：仅改 `paper_formal_bootstrap.py`、bootstrap unit/integration、taskbook/delivery；`__init__.py`/review/`paper_policy.py` 只读；零 Python；不 stage/commit。

### 13.1 main regression 证据（诚实保留）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-r1-rebuilt2-main-merge-regression-20260826T203000Z` |
| summary SHA256 | `EE48534311AF5162375B5F23B44706666F019ACA914FA305EC361E0530A86151` |
| focused | **`26 passed / 1 skipped / 1 failed`**；错误码 `PAPER_FORMAL_BOOTSTRAP_STALE` |
| 失败节点 | `tests/integration/test_paper_formal_bootstrap.py::test_public_fresh_bootstrap_reopen_and_identity_closure`（`verify_existing_formal_paper_runtime_bootstrap`） |
| Ruff / mypy / cold / scope | **全部 UNRUN** |
| STOP | `STOP=STAGE_FAILED:focused` |

### 13.2 现象—根因—规则—最小复现—测试—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | main 合流后 focused 回归：retained bootstrap 的 `verify_existing_*` 在 policy fresh helper 返回后稳定 `PAPER_FORMAL_BOOTSTRAP_STALE` |
| 根因 | `verify_existing_paper_execution_policy` 设计为 fresh-load 后按**值**相等返回**新** policy 对象（`_attestation` compare=False）；bootstrap 门禁误用 `policy is not bootstrap.policy`，把合法值相等误判为 STALE |
| 应遵循规则 | 生产唯一修复：`policy != bootstrap.policy`；binding/account 继续 `is`；broker/execution capability 继续 `is`；chain join / identity payload / bytes / 错误码 / 顺序不变；不得改 `paper_policy.py`；不用 Any/cast/type:ignore |
| 最小复现 | public fresh bootstrap → `verify_existing_formal_paper_runtime_bootstrap(bootstrap=first, now=NOW)`；policy helper 返回 `fresh == retained.policy` 且 `fresh is not retained.policy` → 旧码 STALE |
| 测试 | unit：值相等非同一对象正向且返回原 bootstrap；policy 字段/attestation/环境漂移仍 STALE；binding/account/capability 等值非同一对象仍 STALE。integration：verify 仍 `is first` |
| 通过条件 | 上述门禁与测试就位；写集 ⊆ 批准路径；本轮 Python/pytest/Ruff/mypy/cold **UNRUN**；不宣称新 Windows 全绿或 UA-M4-006 关闭 |

### 13.3 生产变更（唯一）

`verify_existing_formal_paper_runtime_bootstrap`：`policy is not bootstrap.policy` → `policy != bootstrap.policy`。其余 identity/`is` 闸未改。

### 13.4 STATIC_REWORK 收口

`STATIC_REWORK_READY`

**仍 OPEN**：UA-M4-006、PAPER、soak、Linux Gate。历史 `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED` 证据链保留；本回归修复后须另申请合流/回归验证，不得继承失败轮冒充全绿。

## 14. EVIDENCE_UPDATE：merge-regression fix source validation PASS

中央授权。本轮 **仅** 更新任务书 §14 与本交付 §14；production / tests / review **冻结只读**；不清 evidence；零 Python；零 stage/commit。

### 14.1 历史 main merge regression（保留；不洗白）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-r1-rebuilt2-main-merge-regression-20260826T203000Z` |
| summary SHA256 | `EE48534311AF5162375B5F23B44706666F019ACA914FA305EC361E0530A86151` |
| focused | **`26 passed / 1 skipped / 1 failed`**；`PAPER_FORMAL_BOOTSTRAP_STALE` |
| Ruff / mypy / cold / scope | **UNRUN**（首失败合同） |
| 口径 | **历史 STOP 原文保留；不得改写为通过** |

### 14.2 本轮 source fix validation（PASS）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m4-r1-rebuilt2-merge-regression-fix-validation-20260826T204000Z` |
| summary SHA256 | `1D39C474FCD239210A2820DFA597569A586ED6D5F67BA2E72CB45F528983D105` |
| identity | PASS |
| focused unit+integration | **`27 passed / 4 skipped`** |
| Ruff | 实际 production/tests PASS |
| mypy | production2 PASS |
| cold | bootstrap PASS |
| scope | exact7 actual dirty6 / cached0 / diff / temp / process PASS |
| 资源 | scratch/cache 清理；`0xF00=0`；writer PID7692 / `0x3` 未扰动 |
| 收口 | `PASS=ALL_STAGES` |

### 14.3 口径边界（强制）

| 声明 | 是否成立 |
| --- | --- |
| source fix Windows validated（本 worktree） | **是** |
| main `937787` 回归已解除 | **否**（仍 `MERGED_REGRESSION_STOP`） |
| UA-M4-006 / PAPER / soak / Linux Gate 关闭 | **否**（仍 OPEN） |

### 14.4 EVIDENCE_UPDATE 收口

`EVIDENCE_UPDATE_READY`

写集核对：仅任务书 + 本 delivery；production/tests/review 未改；evidence 未清；未 stage/commit。
