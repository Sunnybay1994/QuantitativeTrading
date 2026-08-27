# M4-UA006-R2 Formal Bootstrap Operator CLI 交付报告

日期：2026-08-27
状态：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`（V4 已绿节点 + REWORK5 类型收敛 + POSTFIX V5 组合闭合；**不等于**真实 bootstrap / PAPER / soak / submit / network / Linux Gate / UA-M4-006 关闭）
task id：`M4-UA006-R2-FORMAL-BOOTSTRAP-OPERATOR-CLI`
exact base / HEAD：`27d42840c08d883d08c9578b3c2802b4630bd0f8`（本轮证据更新未 stage/commit）
branch：`codex/m4-ua006-r2-formal-bootstrap-operator-cli`
worktree：`artifacts/dev_worktrees/m4-ua006-r2-formal-bootstrap-operator-cli`
角色：implementation（原实现者；证据-only 更新 delivery；production/tests/taskbook/review 只读）

## 1. 实现摘要（exact scope）

### 1.1 Production（白名单 #1）

`src/quant/execution/run_paper_formal_bootstrap.py`（new）

| 契约项 | 实现 |
| --- | --- |
| 参数 | 仅 `--config`、`--session-date`、恰好一个 `--initialize`/`--reopen`；`_QuietParser` 抑制 usage；无 env/cwd/default/`--now`/root/PAPER 参数 |
| 时间 | 业务路径经 `_canonical_utc_now()` 取一次 `datetime.now(timezone.utc)`；要求 aware UTC |
| 调用顺序 | initialize：`bootstrap_fresh` → `verify_existing`（same now）；reopen：`reopen_verified` → `verify_existing`（same now）；fresh 返回必须 `is` 同一 capability |
| callable 真身 | import-time closure 捕获 package-owned 三元组；每次调用核对 module 属性 `is`/`__code__`、拒绝 `partial`/`__wrapped__`；双侧同一 impostor fail-closed → `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED` |
| config 门禁 | 调用 public API 前：exact concrete `Path`、absolute、`lstat` regular file；拒绝 relative/PurePath/subclass/symlink/junction/reparse/missing/directory；不读文件内容 |
| session-date | canonical `YYYY-MM-DD` 且 `isoformat()` 逐字 round-trip |
| projection | schema `m4-formal-bootstrap-operator-result-v1`；18 字段 exact；值仅来自 fresh-verified capability；`canonical_json_bytes` + 末尾一个 LF；无 path/account id/verified_at/token |
| 错误码 | help/成功 → 0；输入 → `PAPER_FORMAL_BOOTSTRAP_CLI_INPUT_INVALID` / 2；stable-token `FormalPaperBootstrapError.code` verbatim / 3；非 token code 或业务段 `SystemExit`/callable drift/非 `is`/未知 `Exception` → `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED` / 3；失败 stdout 0B |
| 零清理 | 无 shutil/rmtree/删除/重试/adopt；initialize 失败完全交给 public API rollback 语义；reopen 零 initializer |

### 1.2 Tests（白名单 #2–3）

2. `tests/unit/test_run_paper_formal_bootstrap.py`（new）
3. `tests/integration/test_run_paper_formal_bootstrap.py`（new）

### 1.3 Delivery（白名单 #5）

本交付报告。

### 1.4 未写 / 只读（首轮）

4. 任务书：首轮只读；**STATIC_REWORK1 按派发写入 §4.4/§6/§10 冻结补充**
6. 独立初验报告：**只读**（保留 `REVIEW_FAIL` 历史；实现者未改）
- 未改：`quant.execution.__init__`、`paper_formal_bootstrap.py`、broker/policy/account/runtime/config、schema、migration、barrier、service、soak、pyproject、roadmap、既有测试

## 2. 任务书 §6 反例映射

| # | 反例 | 覆盖 |
| ---: | --- | --- |
| 1 | help / 缺参 / 多余参数 / initialize+reopen 同时或均未指定 | unit `test_help_*`、`test_argv_shape_failures_*`；integration help/空 argv |
| 2 | relative / PurePath / subclass / symlink·reparse / missing / directory | unit path 门禁组 |
| 3 | 非 canonical date / datetime / 无效日 / 前后空白 | unit `test_non_canonical_session_date_*` |
| 4 | initialize/reopen 调用序、same-now、fresh `is` | unit call-order；equal-but-not-identical → runtime |
| 5 | wrapper / partial / marker / 双侧同一 impostor / 错返回类型 | unit impostor + wrong-type |
| 6 | public stable code / 未知异常脱敏；业务段 SystemExit；hostile code 整码 runtime | unit 错误脱敏 + F1/F2 对抗测 |
| 7 | success projection exact keys/schema，无 path/account/time/token | unit success projection；integration identity 对齐 |
| 8 | failure stdout 0B、stderr 一行、exit 2/3 | unit/integration 失败路径 |
| 9 | initialize 失败不删不重试；reopen 零 initializer | unit delete/retry + reopen seam；integration partial 保留 broker root |
| 10 | public TOCTOU/STALE → runtime，无成功 JSON | unit `test_public_toctou_*` |
| 11 | 真实 public：CLI initialize→verify/reopen；CLOSING 拒 reopen；partial 拒 initialize | integration 三测（需批准 basetemp） |

禁止项：测试未 monkeypatch `_actual_project_root` / `_system_temp_root`；integration AST 自证；unit 仅用 `_require_owned_api` seam 验证调用形状。

## 3. STATIC_ONLY 未运行边界（全部 UNRUN）

本会话**强制未运行**：

- 任何 Python 解释器业务执行 / cold import / SQLite probe
- pytest（unit/integration 均 UNRUN）
- Ruff / mypy
- 真实 formal root / PAPER / soak / submit / network / worker
- stage / commit / merge

因此：**不得**宣称 `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、PAPER/soak/Linux Gate。

## 4. STOP

无 `CONTRACT_STOP`。public bootstrap/reopen/verify API 足以满足 same-now + fresh `is`；未扩白名单；未修改 package-owned bootstrap 真身。

## 5. 静态退出核对

| 检查 | 结果 |
| --- | --- |
| HEAD / exact base | `27d42840c08d883d08c9578b3c2802b4630bd0f8` |
| branch / worktree | 与任务书一致 |
| 实现者 dirty | CLI、unit/integration、任务书（REWORK 冻结补充）、本 delivery |
| 任务书 | STATIC_REWORK1 写入 §4.4/§6/§10；review 只读 |
| review 路径 | 保留既有 `REVIEW_FAIL`；本会话**未修改** |
| stage/commit | 无 |
| UA-M4-006 / PAPER / soak / Linux Gate | 仍 OPEN |

## 6. 建议 Windows 验证顺序（本交付不执行）

`REVIEW_PASS` 后另向中央申请：

1. identity：`quant`、CLI、`paper_formal_bootstrap` 来自 exact worktree
2. unit test
3. integration test（批准 project-outside/non-system-temp fresh basetemp）
4. Ruff CLI + tests
5. mypy CLI
6. cold import CLI
7. exact6 Unicode-safe scope、cached0、diff/temp/cache/process residue

首失败 STOP。Windows 绿只允许 `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`。

## 7. 收口声明（首轮；历史保留）

首轮曾声明 `DELIVERY_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_DELIVERED`。

独立初验裁决 **`REVIEW_FAIL`**（P1-1 业务 `SystemExit` 逃逸；P1-2 hostile `error.code`；P2-1 `\n` 闸无测）。报告路径：
`docs/framework/reviews/M4_UA006_R2_FormalBootstrapOperatorCLI独立初验报告.md`（只读保留）。

**仍 OPEN / 禁止宣称**：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、真实 PAPER、soak、Linux Gate、单轮全量 Gate。

---

## 8. STATIC_REWORK1（针对 REVIEW_FAIL P1×2 + P2×1）

日期：2026-08-26
依据：任务书 §10 F1–F2；只读初验报告（状态 `REVIEW_FAIL` 历史保留）
范围：exact6 之 CLI、unit、integration、任务书冻结补充、本 delivery；review **未改**；全部运行检查继续 **UNRUN**。

### 8.1 F1 — 业务段 `SystemExit` → runtime/3

| 项 | 内容 |
| --- | --- |
| 现象 | 业务 `try` 仅 `except Exception`，`SystemExit` 穿透 `main`，不写 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED`，可泄漏路径型 exit code |
| 根因 | 解析期与业务期 SystemExit 策略不对称；「未预期异常」被收窄为 `Exception` |
| 应遵循规则 | 任务书 §4.4 / §10 F1；审查 AE-1 |
| 最小复现（对抗） | seam 在 bootstrap / reopen / verify 内 `raise SystemExit(r"C:\secret\...")` |
| 生产改动 | 业务段显式 `except SystemExit` → emit runtime / exit 3；**不** `except BaseException`；`KeyboardInterrupt`/`GeneratorExit` 不捕获；parse 期 help→0 不变 |
| 新增测试 | `test_business_systemexit_maps_to_runtime_failed`（parametrize initialize/reopen/verify） |
| 通过条件 | 三槽位均 exit 3、stdout 0B、stderr exact `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n`、无路径/usage |

### 8.2 F2 — `error.code` exact stable token 或整码 runtime

| 项 | 内容 |
| --- | --- |
| 现象 | 旧闸仅拒空/`\n`；含 `\r`/C0/path 片段的 hostile code 可原样写入 stderr |
| 根因 | stable code 门禁未覆盖控制字符与非 token 形态 |
| 应遵循规则 | 任务书 §4.4 / §10 F2；审查 AE-2 / P2-1 |
| 最小复现（对抗） | `FormalPaperBootstrapError("...\rC:\\secret...")` / `"...\nY"` / slash/colon/Unicode/非 str |
| 生产改动 | `_stable_public_error_code`：`type is str` + ASCII + `^[A-Z][A-Z0-9_]*$`；否则整码→`PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED`；禁止部分消毒 |
| 新增测试 | `test_hostile_formal_bootstrap_error_code_maps_wholly_to_runtime`；`test_non_str_*`；helper 单测（含 `\n` 回归，关 P2-1） |
| 通过条件 | hostile 码永不出现在 stderr；仅 generic runtime 一行；合法 `PAPER_FORMAL_BOOTSTRAP_*` 仍 verbatim |

### 8.3 保持不变

单次 UTC now、owned callable 真身、exact config Path、fresh `is`、canonical 18 键投影、exit 0/2 表、零清理/零 initializer、integration 真实 public 路径、禁 patch `_actual_project_root`/`_system_temp_root`。

### 8.4 STATIC_ONLY / STOP

本返工**强制 UNRUN**：Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。
无 `CONTRACT_STOP`。不得申请 Windows fixture，直至新独立上下文 `REVIEW_PASS`。

### 8.5 收口

`REWORK_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_REWORK1`。

**仍禁止宣称**：Windows engineering validated、UA-M4-006 关闭、PAPER、soak、Linux Gate。

---

## 9. STATIC_REWORK2（VALIDATION1 unit fixture：`stat.S_IFMT` fallback）

日期：2026-08-26
依据：任务书 §11；VALIDATION1 证据根 `artifacts/agent_runs/m4-ua006-r2-validation1-20260826T2203/`
范围：**仅** `tests/unit/test_run_paper_formal_bootstrap.py` + 本 delivery；production / integration / 任务书 / review **只读未改**；全部本轮运行检查继续 **UNRUN**。

### 9.1 现象—根因—规则—最小复现—修正—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION1：identity PASS；unit `58 passed / 1 failed`（`test_symlink_or_reparse_config_is_input_invalid`）；首失败 STOP；integration / Ruff / mypy / cold / scope **UNRUN**。Windows 无真实 symlink 时走 fallback，得到 exit **3**，合同要求 input exit **2** |
| 根因 | fallback 使用 `(info.st_mode & ~stat.S_IFMT) \| stat.S_IFLNK`。在 Windows 上 `stat.S_IFMT` 是**函数**而非位掩码，`~stat.S_IFMT` 触发 `TypeError`；CLI 业务段既有 `except Exception` 合同将其归一为 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED` / exit 3 |
| Python stat 规则 | 合成 `os.stat_result.st_mode` 必须用明确的 file-type bits + permission bits。正确写法：`stat.S_IFLNK \| stat.S_IMODE(info.st_mode)`（或严格等价）。**不得**把 `stat.S_IFMT` 函数当位掩码；**不得**改 production config guard 或异常归一来迁就错误 fixture |
| 最小复现 | Windows 主机禁止创建 symlink → `created=False` → `marked_lstat` 执行 `~stat.S_IFMT` → `TypeError` → CLI runtime/3 |
| 修正测试 | 仅替换 fallback mode 构造为 `stat.S_IFLNK \| stat.S_IMODE(info.st_mode)`；保留 target-path `normcase` exact 匹配、真实 symlink 正向分支、`EXIT_INPUT`、stdout 0B、stderr exact input code、target path 脱敏断言 |
| 通过条件 | 同一原 reviewer 确认仅 unit+delivery 变化且 production/integration SHA 冻结；随后从 identity 起完整跑 VALIDATION2；**不得**把本轮 58 绿冒充整包 PASS |

### 9.2 VALIDATION1 诚实边界（历史保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`58 passed / 1 failed`**（本 fixture；首失败 STOP） |
| integration | **UNRUN** |
| Ruff / mypy / cold / scope | **UNRUN** |

本失败为 **test-only fixture**，不构成 production 红，也不构成 Windows engineering 整包 PASS。

### 9.3 STATIC_ONLY / STOP

本返工强制 UNRUN：Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O / stage / commit。
无 `CONTRACT_STOP`。

### 9.4 收口

`REWORK_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_REWORK2`。

**仍禁止宣称**：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、PAPER、soak、Linux Gate；亦不得宣称 VALIDATION1 整包 PASS。

---

## 10. STATIC_REWORK3（VALIDATION2 integration：time-bound `bootstrap_identity`）

日期：2026-08-27
依据：任务书 §12；VALIDATION2 证据根 `artifacts/agent_runs/m4-ua006-r2-validation2-20260827T033820Z/`
integration stdout SHA256：`EC1ECFEBB0B43179056F7DE3164DC2DB6965E9DB9F402640A865D5F4EA1DBBF9`
summary SHA256：`A9FF402C39B5B7F6749ECFC25013EFBBBC009A41AB20E7412C0227EA9CE8B8A3`
范围：**仅** `tests/integration/test_run_paper_formal_bootstrap.py` + 本 delivery；production / unit / 任务书 / review **只读未改**；本轮运行检查继续 **UNRUN**。

### 10.1 现象—根因—规则—最小复现—修正—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION2：identity PASS；unit `59 passed`；integration `5 passed / 1 failed`（`test_cli_public_initialize_and_reopen_identity_projection`）；首失败 STOP；Ruff / mypy / cold / scope **UNRUN** |
| 根因 | integration 把 CLI initialize 投影与**后来** public reopen capability、以及两次 CLI initialize/reopen 投影的 `bootstrap_identity` 当作跨调用 durable 字段逐字相等。public identity payload 含 `verified_at`，故 `bootstrap_identity` 是每次 fresh verification 的 time-bound 摘要，不是跨 reopen 稳定身份 |
| 应遵循规则 | 任务书 §12：`bootstrap_identity` 仍为 CLI 必需字段且须 canonical lowercase 64-hex；四次 fresh（CLI initialize → public reopen → CLI reopen → public reopen）identity **互异**；跨调用稳定闭包**只排除** `bootstrap_identity`；不得暴露 `verified_at`、删字段或改 production；同次 capability 相等仍由 unit seam 负责 |
| 最小复现 | CLI initialize（now=T1）后 public reopen（now=T2>T1）→ 两枚 `bootstrap_identity` 不同；旧测 `_assert_projection(... capability=later)` 与 `reopen_payload[bi]==payload[bi]` 失败 |
| 修正测试 | `_assert_canonical_bootstrap_identity`；`_assert_projection` 对后来 capability 只比 durable 字段；`_durable_identity_projection` 跨 CLI initialize/reopen 排除 `bootstrap_identity`（`mode` 按各调用语义单独断言）；收集四枚 identity 断言 `len(set)==4`；保留 key 集合、schema、barrier_epoch、execution_store_identity、脱敏、真实 public 链 |
| 通过条件 | 同一原 reviewer 确认仅 integration+delivery 变化且 production/unit 冻结；随后从 identity 起完整跑 **VALIDATION3**；不得继承本轮部分绿为整包 PASS |

### 10.2 VALIDATION2 诚实边界（历史保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`5 passed / 1 failed`**（本 identity 合同；首失败 STOP） |
| Ruff / mypy / cold / scope | **UNRUN** |

本失败为 **integration 合同/断言错误**（误把 time-bound 字段当 durable），不构成 production 红，也不构成 Windows engineering 整包 PASS。

### 10.3 VALIDATION3 完整条件（本交付不执行）

REVIEW_PASS 后另申请完整 VALIDATION3（不得沿用 VALIDATION2 部分绿）：

1. identity
2. unit
3. integration
4. Ruff CLI + tests
5. mypy CLI
6. cold import CLI
7. exact6 scope / cached0 / diff / temp / cache / process

### 10.4 STATIC_ONLY / STOP

本返工强制 UNRUN：Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。
无 `CONTRACT_STOP`。

### 10.5 收口

`REWORK_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_REWORK3`。

**仍禁止宣称**：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、PAPER、soak、Linux Gate；亦不得宣称 VALIDATION2 整包 PASS。

---

## 11. STATIC_REWORK4（VALIDATION3：完整 TIME_BOUND/DURABLE 身份分组）

日期：2026-08-27
依据：任务书 §13（**取代** §12「跨调用只排除 `bootstrap_identity`」的不完整规则；§12 失败历史保留）
VALIDATION3 证据根：`artifacts/agent_runs/m4-ua006-r2-validation3-20260827T035206Z/`
integration stdout SHA256：`6AB242600679E219AB14EF1C744C9EC98215090510F8FF293F5497D0B913A8E8`
summary SHA256：`C556FBA20EB813232312BD43232D6C97F6CB2DB147C572CF7B3AEC209CBB7FCA`
范围：**仅** `tests/integration/test_run_paper_formal_bootstrap.py` + 本 delivery；production / unit / 任务书 / review **只读未改**；本轮运行检查继续 **UNRUN**。

### 11.1 现象—根因—规则—最小复现—修正—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION3：identity PASS；unit `59 passed`；integration `5 passed / 1 failed`（`test_cli_public_initialize_and_reopen_identity_projection`）；首失败 STOP；Ruff / mypy / cold / scope **UNRUN** |
| 根因 | REWORK3 按 §12 把除 `bootstrap_identity` 外的投影字段一律当 durable。public 链中 `runtime_environment_identity` / `execution_policy_identity` / `broker_binding_identity` / `account_verification_identity` / `broker_capability_identity` 均经 `verified_at`（或依赖含时间戳的上游 verification）进入摘要，跨 reopen 随 `now` 变化；旧测 durable 全等因此失败。`runtime_layout_identity` 在 cold→materialized 后稳定，不应归入 time-bound |
| 源码证据（只读核对，无改 production） | `paper_formal_bootstrap._identity_payload` 含 `verified_at`；env/policy/binding/account/broker capability payload 均含 `verified_at` 或上游 verification identity。与 §13 TIME_BOUND exact6 / DURABLE exact10 **无冲突** → 未 `CONTRACT_STOP` |
| 应遵循规则 | 任务书 §13：18 键由 `schema_version` + `mode` + TIME_BOUND exact6 + DURABLE exact10 互斥精确覆盖；四次 fresh 中每个 TIME_BOUND 字段 lowercase 64-hex 且四值互异；每个 DURABLE（含 `runtime_layout_identity`）四次逐字相等；不删字段、不暴露 `verified_at`、不改 identity 算法；unit 同次 capability 全字段投影责任不变 |
| 最小复现 | CLI initialize（T1）后 public reopen（T2>T1）→ TIME_BOUND 六字段均变；§12 式 durable 闭包把 `runtime_environment_identity` 等当作稳定字段 → 断言失败 |
| 修正测试 | 引入 `_TIME_BOUND_KEYS` / `_DURABLE_KEYS` / `_CONTROL_KEYS` 互斥并 `union == _RESULT_KEYS`；四次 fresh 收集 TIME_BOUND 断言每字段 `len(set)==4`；DURABLE 四次全等；envelope/脱敏/canonical JSON/真实 public 链保持 |
| 通过条件 | 同一原 reviewer 确认仅 integration+delivery 变化且 production/unit 冻结；随后从 identity 起完整跑 **VALIDATION4**；不得继承本轮部分绿 |

### 11.2 VALIDATION3 诚实边界（历史保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`5 passed / 1 failed`**（§12 不完整 durable 闭包；首失败 STOP） |
| Ruff / mypy / cold / scope | **UNRUN** |

本失败为 **integration 合同分组错误**（§12 过窄），不构成 production 红，也不构成 Windows engineering 整包 PASS。

### 11.3 对 §12 / REWORK3 的取代声明

§13 / 本 REWORK4 **取代**「跨调用只排除 `bootstrap_identity`」规则。§12 VALIDATION2 失败史与 REWORK3 交付记录**原文保留**，不得洗白为曾整包通过。

### 11.4 VALIDATION4 完整条件（本交付不执行）

REVIEW_PASS 后另申请完整 VALIDATION4（不得沿用 VALIDATION3 部分绿）：

1. identity
2. unit
3. integration
4. Ruff CLI + tests
5. mypy CLI
6. cold import CLI
7. exact6 scope / cached0 / diff / temp / cache / process

### 11.5 STATIC_ONLY / STOP

本返工强制 UNRUN：Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。
无 `CONTRACT_STOP`（public identity 与 §13 分组一致）。

### 11.6 收口

`REWORK_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_REWORK4`。

**仍禁止宣称**：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、PAPER、soak、Linux Gate；亦不得宣称 VALIDATION3 整包 PASS。

---

## 12. STATIC_REWORK5（VALIDATION4：callable 类型收敛）

日期：2026-08-27
依据：任务书 §14
VALIDATION4 证据根：`artifacts/agent_runs/m4-ua006-r2-validation4-20260827T040605Z/`
mypy stdout SHA256：`AEE3A11B1C69E1FC45B9524717B1E7F4D257E56F4A71BEAC44B8667B31CF5307`
summary SHA256：`239DB23C8787667591DC48CA7B9C81A65006EF3F2EE282E5D4EF65ED3E6B2E05`
范围：**仅** `src/quant/execution/run_paper_formal_bootstrap.py`（annotations）+ 本 delivery；unit / integration / 任务书 / review **只读未改**；本轮运行检查继续 **UNRUN**。

### 12.1 现象—根因—规则—最小复现—修正—通过条件

| 项 | 内容 |
| --- | --- |
| 现象 | VALIDATION4：identity PASS；unit `59 passed`；integration `6 passed`；Ruff PASS；mypy CLI **1 error**（约 L122 `return bootstrap_fn, reopen_fn, verify_fn` 推断为 `tuple[object, object, object]`）；首失败 STOP；cold / scope **UNRUN** |
| 根因 | `_build_callable_authority` 的 `true_bootstrap` / `true_reopen` / `true_verify` 标注为 `object`。inner 在 `is not true_*` 守卫后，mypy 将模块 callable 收窄为与 `object` 参数同一身份，返回元组退化为 `tuple[object, object, object]`，与声明的三元 `Callable[..., VerifiedFormalPaperRuntimeBootstrap]` 冲突 |
| 应遵循规则 | 任务书 §14：单一窄 alias `_BootstrapCallable = Callable[..., VerifiedFormalPaperRuntimeBootstrap]`，统一用于三个 outer 参数、outer 返回 `Callable[[], tuple[...]]`、inner 返回三元组；禁止 `cast` / `Any` / `type: ignore` / `Protocol`；不得改函数体、`is`/`__code__`/`partial`/`__wrapped__`、调用序、异常码、projection/schema、测试 |
| 最小复现 | mypy CLI → L122 incompatible return type `tuple[object, object, object]` |
| 修正 | 仅增加 `_BootstrapCallable` 并替换上述 annotations；runtime 执行路径字节级语义不变 |
| 通过条件 | 同一原 reviewer 确认仅 alias/annotations + delivery 变化；随后 POSTFIX **VALIDATION5**：identity → Ruff 仅 CLI → mypy CLI → cold CLI → exact6 Unicode scope/cached0/diff/temp/cache/process（不重复 V4 已绿 unit59/integration6/Ruff tests，除非 reviewer 发现行为变化） |

### 12.2 VALIDATION4 诚实边界（历史保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`6 passed`** |
| Ruff | **PASS** |
| mypy | **1 error @ ~L122**（callable 返回类型；首失败 STOP） |
| cold / scope | **UNRUN** |

本失败为 **type-only annotation 过宽**，不构成 runtime/行为红，也不构成 Windows engineering 整包 PASS。

### 12.3 POSTFIX VALIDATION5 条件（本交付不执行）

REVIEW_PASS 后另申请 POSTFIX VALIDATION5（不得沿用 VALIDATION4 mypy STOP）：

1. identity
2. Ruff 仅 CLI
3. mypy CLI
4. cold CLI
5. exact6 Unicode scope / cached0 / diff / temp / cache / process

### 12.4 STATIC_ONLY / STOP

本返工强制 UNRUN：Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。
无 `CONTRACT_STOP`。

### 12.5 收口

`REWORK_READY` / `FORMAL_BOOTSTRAP_OPERATOR_CLI_STATIC_REWORK5`。

**仍禁止宣称**（当时）：`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`、UA-M4-006 关闭、PAPER、soak、Linux Gate；亦不得宣称 VALIDATION4 整包 PASS。

---

## 13. 最终组合证据（VALIDATION1–5；任务书 §15）

日期：2026-08-27
依据：任务书 §15；`REWORK5_REVIEW_PASS` 后中央 POSTFIX VALIDATION5
POSTFIX VALIDATION5 证据根：`artifacts/agent_runs/m4-ua006-r2-postfix-validation5-20260827T041948Z/`
summary SHA256：`8054701A99588936DD8646057CF994E2D33627E55D6AD4235BD472DDCC2EAEDB`
本更新：**仅**本 delivery；production / tests / 任务书 / review **只读未改**；本会话零 Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O；零 stage/commit。

### 13.1 诚实组合表（不得洗白历史首失败）

| 轮次 | 证据根（摘要） | 诚实结果 |
| --- | --- | --- |
| VALIDATION1 | `.../m4-ua006-r2-validation1-20260826T2203/` | identity PASS；unit **`58 passed / 1 failed`**（symlink fallback `stat.S_IFMT`）；integration / Ruff / mypy / cold / scope **UNRUN** → REWORK2 |
| VALIDATION2 | `.../m4-ua006-r2-validation2-20260827T033820Z/` | identity PASS；unit **`59 passed`**；integration **`5 passed / 1 failed`**（跨调用误比 `bootstrap_identity`）；后续 **UNRUN** → REWORK3 |
| VALIDATION3 | `.../m4-ua006-r2-validation3-20260827T035206Z/` | identity PASS；unit **`59 passed`**；integration **`5 passed / 1 failed`**（§12 不完整 durable 闭包）；后续 **UNRUN** → REWORK4（§13 取代 §12） |
| VALIDATION4 | `.../m4-ua006-r2-validation4-20260827T040605Z/` | identity PASS；unit **`59 passed`**；integration **`6 passed`**；Ruff（CLI+tests）**PASS**；mypy CLI **1 error @ callable 注解** 首失败 STOP；cold / scope **UNRUN** → REWORK5 |
| REWORK5 | （类型-only；见 §12） | 仅 `_BootstrapCallable` alias + annotations；`REWORK5_REVIEW_PASS`；运行路径/测试/projection/真身检查/异常语义未变；允许复用 V4 已绿节点 |
| VALIDATION5（POSTFIX） | `artifacts/agent_runs/m4-ua006-r2-postfix-validation5-20260827T041948Z/` | identity **PASS**；Ruff 仅 CLI **PASS**；mypy CLI **`Success: no issues found in 1 source file`**；cold CLI **PASS**；exact6 Unicode-safe scope、cached=0、`git diff --check`、temp/cache/`__pycache__`、0xF00 释放与 writer PID7692 affinity `0x3` **全部 PASS**；summary SHA256 `8054701A99588936DD8646057CF994E2D33627E55D6AD4235BD472DDCC2EAEDB` |

历史 STOP / FAIL / UNRUN **全部保留**于 §9–§12 与上表；不得把任一历史首失败改写为「单轮全绿」。

### 13.2 组合口径与状态上限

Windows 工程验证以 **VALIDATION4 已绿段**（identity / unit59 / integration6 / Ruff tests）+ **REWORK5 纯类型收敛** + **POSTFIX VALIDATION5**（identity / Ruff CLI / mypy CLI / cold / exact6 scope·cached0·diff·temp·process）**组合闭合**。

本包状态上限仅提升为：

`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`

### 13.3 仍 OPEN（强制）

以下能力本轮**未执行**，继续 **OPEN**，不得据此开始真实运行或计时：

- 真实 formal bootstrap / fresh-root / new-epoch 业务运行
- PAPER
- soak / submit / scheduler / order / gateway dispatch
- network
- Linux Gate
- **UA-M4-006**

### 13.4 收口

`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`（组合证据；非单轮全绿叙事）。

下一步：同一原 reviewer 仅更新唯一 review（`EVIDENCE_REVIEW_PASS` / `EVIDENCE_REVIEW_FAIL`）；只有 PASS 后方可申请 SAFE_COMMIT；ignored evidence 必须保留且不得 stage。
