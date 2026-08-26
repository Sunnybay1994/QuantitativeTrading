# M3-G8F-R2B Rebuilt Production Successor Bridge / CLI 交付报告

状态：`EVIDENCE_UPDATE_READY` / `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`（组合 Windows 工程证据；**不**伪造单轮全绿；actual worker / 真实 Qlib / network / new root / retained / Linux / M3 Gate 仍 **OPEN**）

- task id：`M3-G8F-R2B-REBUILT-PRODUCTION-SUCCESSOR-BRIDGE-CLI`
- exact base / HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（实现全程未漂移）
- branch：`codex/m3-g8f-r2b-production-successor-bridge-cli-rebuilt`
- worktree：`artifacts/dev_worktrees/m3-g8f-r2b-production-successor-bridge-cli-rebuilt`
- 退出状态上限：`R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`（见 §18 组合证据；**不**关闭 M3 Gate）

## 1. 目标达成摘要

为已合流的 package-owned two-fold successor 提供唯一 production bridge 与窄 CLI：显式 `m3-successor-bridge-request-v1` request → fresh 重建 config/release/toolchain → 零参 `make_canonical_successor_production_dependencies()` → `run_production_two_fold_successor(..., public_apis=None, resume=...)`。bridge/CLI **不**枚举、选择、包装或复制任何 stage/fold/Gate 序列。

## 2. 逐路径变化（exact 实现所有权 1–6 + 交付 8）

| # | 路径 | 变化 |
|---|---|---|
| 1 | `src/quant/research/m3/successor_bridge.py` | **new→REWORK1→REWORK4→REWORK5**：REWORK5 仅 `Callable` import + `_build_entrypoint_authority` 返回注解 `Callable[[], None]` |
| 2 | `src/quant/research/m3/run_successor.py` | **new→REWORK1**（本 REWORK4 **未改**） |
| 3 | `tests/unit/test_m3_successor_bridge.py` | **new→REWORK1→REWORK3→REWORK4**：REWORK4 钉 `NaN`/`Infinity`/`-Infinity` → INPUT；**F10 未重写** |
| 4 | `tests/integration/test_m3_successor_bridge.py` | **new→REWORK1**（本 REWORK4 **未改**） |
| 5 | `tests/unit/test_m3_run_successor.py` | **new→REWORK1→REWORK4**：新增 raw Infinity → CLI exit 2 / 输入码 / 脱敏 |
| 6 | `tests/integration/test_m3_run_successor.py` | **new→REWORK1**（本 REWORK4 **未改**） |
| 7 | 任务书 | **EVIDENCE_UPDATE**：§14 组合证据表（本轮只改任务书+delivery） |
| 8 | 本交付报告 | **EVIDENCE_UPDATE**：§18 绑定 VALIDATION1–3 / REWORK3–5；状态上限 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` |
| 9 | 独立初验报告 | **只读**（实现者未改；含 REWORK3–5 复验历史） |

本 EVIDENCE_UPDATE 轮：**未**改 production / tests / review；零 Python / stage / commit。

## 3. 冻结公共合同

### 3.1 Request schema

- schema id：`m3-successor-bridge-request-v1`（字段名 `schema_id`）
- 根键精确集合：`schema_id`, `project_root`, `controlled_output_root`, `folds`, `runtime_identity`, `now`, `toolchain`, `resume`
- 文件 bytes 必须等于 canonical JSON（`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=True`, `allow_nan=False`）；`object_pairs_hook` 拒重复键；读取前后 inode/size/mtime/bytes 漂移 fail-closed
- `project_root` / `toolchain.python_executable`：当前平台 exact concrete absolute `Path`（拒 subclass / PurePath / relative / symlink/reparse）
- PROJECT 内路径：PROJECT-relative canonical posix（`controlled_output_root`, `config_path`, `g1_release_path`, `qlib_dump_tool_path`）
- `qlib_dump_tool_path` 必须 exact 等于 `fetch_qlib_tool.DEFAULT_TARGET_PATH`；size/SHA 必须与两 fold `build_qlib_dump_tool_spec` 及磁盘 bytes 一致
- `resume`：exact bool，禁止由 env/目录/wall clock/retained 推导
- `now`：canonical UTC 微秒文本（`...Z`）

### 3.2 Bridge / CLI API

- `run_production_successor_bridge(*, request_path: Path) -> SuccessorRunResult`
- `project_successor_bridge_result` / `successor_bridge_result_json_bytes`：窄成功投影（无绝对路径；保留 `two_fold_identity`、receipt node/sha、gate 名、reused、controlled 相对根）
- `run_successor.main(argv: Sequence[str] | None = None) -> int`

### 3.3 错误码与 CLI exit（冻结）

| 族 | 稳定码 | CLI exit |
|---|---|---|
| 输入/identity | `SUCCESSOR_BRIDGE_INPUT_INVALID` | `2` |
| runtime/Gate/terminal（及入口期未预期异常） | `SUCCESSOR_BRIDGE_RUNTIME_FAILED` | `3` |
| 成功 | （stdout 一行 JSON） | `0` |

映射：`SuccessorRuntimeError` 中 `SUCCESSOR_INPUT_INVALID` / `SUCCESSOR_CONFIG_INVALID` / `SUCCESSOR_RELEASE_INVALID` → 输入族；其余 runtime 码 → runtime 族。stderr **仅**脱敏码一行，无路径/配置内容。

### 3.4 Canonical callable authority（冻结合同；与当前源码一致）

**已废除（不得再作验收依据）：** 模块级 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY` 别名，以及「`runtime.make_canonical_successor_production_dependencies is _CANONICAL_FACTORY`」这类可被双侧同一 impostor 同时替换后仍彼此 `is` 通过的门禁模型。当前生产模块中**不存在**上述符号。

**现行 authority（`successor_bridge.py`）：**

1. **Import-time closure 真身**<br>
   `_build_entrypoint_authority(true_factory, true_entry)` 在模块导入时捕获当时的<br>
   `runtime.make_canonical_successor_production_dependencies` 与<br>
   `runtime.run_production_two_fold_successor`，连同各自 `__code__`，闭包进<br>
   `_require_canonical_entrypoints`（赋值于模块级该名；真身本身在闭包 cell 中，**不是**可改写的 `_CANONICAL_*` 别名）。

2. **调用前检查**（`run_production_successor_bridge` 进入 factory/entry 之前）
   - `runtime.make_canonical_successor_production_dependencies is true_factory`（闭包捕获对象）
   - `runtime.run_production_two_fold_successor is true_entry`
   - 对应 `__code__ is` 闭包捕获的 code 对象
   - 拒绝带 `__wrapped__` 的包装体
   因此：仅替换 `runtime.*` 一侧、或**双侧换成同一 impostor**（即使 impostor 彼此 `is` 相同），均因不等于闭包真身 / code 而 `SUCCESSOR_BRIDGE_INPUT_INVALID`。证据：`test_rejects_wrapper_factory_or_entrypoint_unilateral`、`test_rejects_bilateral_same_impostor_on_factory_and_entry`。

3. **factory 产物槽位**<br>
   `_require_canonical_dependencies` 要求各槽位 `is` 绑定 package-owned upstream/downstream / `make_project_stage_runner`。

4. **`public_apis=None`**<br>
   由 adapter 内部取得 exact canonical bundle；不得从 request/caller 注入。

5. **exact1 factory/entry 证据（不拆真身）**
   - **AST 合同**：`test_bridge_source_calls_factory_and_entry_exactly_once` 解析 `run_production_successor_bridge` 源码，断言对 `make_canonical_successor_production_dependencies` 与 `run_production_two_fold_successor` 各 **exact 1** 次属性调用。
   - **行为合同**：`test_bridge_reaches_two_folds_without_replacing_canonical_identity` 在**不**替换 closure 真身 / `runtime.*` 入口的前提下跑通两 fold，并断言跑后 `runtime.*` 仍 `is` 导入时真身。
   - **禁止**：靠同时 monkeypatch 双侧别名为 spy 来“数次数”（首轮做法已作废）。

## 4. 必测反例覆盖映射（任务书 §7）

| # | 反例 | 证据位置（REWORK1 后） |
|---|---|---|
| 1 | unknown/missing/duplicate/noncanonical；subclass/PurePath/relative；**真实 symlink + reparse 注入**；bytes 漂移 | unit：字段测 + `test_rejects_path_subclass_*` + `test_rejects_request_leaf_symlink_or_reparse_injection` + `test_rejects_member_file_symlink_*` |
| 2 | nested/wrong controlled；失败后 controlled 仍不存在；**已存在 controlled 错配零写入** | unit controlled absent；integration `test_controlled_exists_but_artifact_mismatch_*` |
| 3 | fold 少/乱序/**双 fold_001 重复**；SHA 错配；未引用 sibling | unit arity/order + `test_rejects_duplicate_fold_ids_*`；integration sibling |
| 4 | wrong dump target；timeout 类型；**两 fold `build_qlib_dump_tool_spec` 漂移**；**dump TOCTOU** | unit dump/timeout + `test_rejects_two_fold_tool_spec_drift_*` + `test_dump_toctou_*` |
| 5 | 单侧 wrapper；**双侧同一 impostor** | unit unilateral + `test_rejects_bilateral_same_impostor_*` |
| 6 | resume false/true；toolchain size/**SHA**；**runtime identity 漂移** | integration resume 测 |
| 7 | CLI help；成功 JSON；桥接错误码；**裸 Exception→RUNTIME/3** | unit/integration `test_m3_run_successor` |
| 8 | fixture 达两 fold（**不拆真身**）；源码 exact1 factory/entry | integration `test_bridge_reaches_two_folds_without_replacing_canonical_identity`；unit AST exact1 |

## 5. UNRUN / 仍 OPEN 边界（诚实）

本 EVIDENCE_UPDATE 会话 **STATIC_ONLY**（零 Python / pytest / Ruff / mypy / cold / stage / commit）。下列能力 **仍 OPEN**，不得虚称关闭：

- actual worker / 真实 Qlib / network
- new controlled root / retained resume 真跑
- Linux Gate / 真实 M3 Gate

历史部分绿与首失败见 §18；**不**伪造单轮全绿。

## 6. 静态卫生

- dirty：任务书 + review（只读）+ 实现 1–6 + 本 delivery；**无**白名单外生产文件
- `git rev-parse HEAD` == exact base `9cc5b56d176a18aa468386b369d550be73051edb`
- 无临时产物 / 凭据
- `CONTRACT_STOP`：**未触发**

## 7. 首轮预防性记录（历史保留；部分已被初验纠正）

| ID | 现象 | 根因 | 规则 | 最小复现 | 新增测试 | 通过条件 |
|---|---|---|---|---|---|---|
| H1 | CLI argparse usage 泄露 | 默认 `error()` | §6 | `main([])` | unit usage | stderr 仅输入码，exit 2 |
| H2 | factory 二次调用 | 自检再调 factory | §3 | — | 已改为 package `is` | exact1 不靠二次 factory |
| H3 | 输入失败 mkdir | 过早创建 | §4 | folds=`[]` | unit controlled absent | 失败后不存在 |

## 8. STATIC_REWORK1（对照任务书 §9 / 初验 F1–F8）

### 首轮过声明纠正

| 过声明 | 纠正 |
|---|---|
| §4 行1 已覆盖 symlink/reparse | **否**；REWORK1 才落地真实 symlink + reparse 注入测 |
| 测名 `duplicates` 已覆盖重复 fold | **否**；REWORK1 才构造双 `fold_001` |
| 测名 `spec_drift` 已覆盖两 fold spec | **否**；REWORK1 才用 public `build_qlib_dump_tool_spec` 不等 |
| integration exact1 计数 | 首轮靠**双侧替换**真身别名计数 → **作废**；改为 AST 源码 exact1 + 不拆真身 integration |
| CLI 未预期异常→输入族 | 与冻结表冲突；REWORK1 改为 RUNTIME/3 |

### F1–F7 逐项

| ID | 现象 | 根因 | 应遵循规则 | 最小复现 | 新增/修正测试 | 通过条件 |
|---|---|---|---|---|---|---|
| F1 | 测名含 symlink 体无 link | 只测 subclass/PurePath/relative | §7.1 / §9.F1 | request 叶 symlink；成员 config symlink；reparse `lstat` 注入 | `test_rejects_request_leaf_symlink_or_reparse_injection`；`test_rejects_member_file_symlink_*` | 均 `SUCCESSOR_BRIDGE_INPUT_INVALID`；不跟随目标 |
| F2 | `duplicates` 虚标 | 未构造双 `fold_001` | §7.3 / §9.F2 | folds 两元素同名 | `test_rejects_duplicate_fold_ids_*` | INPUT；`_require_canonical_entrypoints` 0 次；controlled 不存在 |
| F3 | `spec_drift` 虚标 | 未测两 fold spec 不等 | §5.3 / §9.F3 | 两 config dump sha 不同 → public `build_qlib_dump_tool_spec` 不等 | `test_rejects_two_fold_tool_spec_drift_via_public_build` | INPUT；entrypoints 门 0 次 |
| F4 | 裸异常→INPUT/2 | CLI `except Exception` 映射错 | §6 / 冻结表 / §9.F4 | `RuntimeError("C:\\secret\\...")` | unit/integration 裸异常参 | stderr 仅 `SUCCESSOR_BRIDGE_RUNTIME_FAILED\n`，exit 3，无路径 |
| F5 | dump 缺 mtime/二次读 | 仅 inode/size 单读 | §9.F5 | 同 size 内容置换 | `test_dump_toctou_same_size_content_swap_*`；production `_read_stable_regular_file_bytes` + dump mtime 闭包 | INPUT；entrypoints 0 |
| F6 | 双侧同一 impostor 放行 | 只比可改写别名彼此 `is` | §3 / §9.F6 | 同时替换 runtime factory/entry 为同一 impostor | `test_rejects_bilateral_same_impostor_*`；closure 真身+`__code__` | INPUT；exact1 改 AST，不拆真身 |
| F7 | 缺 identity 漂移与已存在树零写 | 只测 toolchain size | §7.6 / §9.F7 | resume=true 改 `code_version`；controlled 已存在改 artifact_root | integration resume 扩展；`test_controlled_exists_but_artifact_mismatch_*` | identity→RUNTIME；错配后 tree/digest 不变，无 completion/receipts/tmp |

### F8 文档

本 STATIC_REWORK1 节记录 F1–F7 与当时过声明纠正。其后发现冻结合同 **§3.4 仍残留已删除的 `_CANONICAL_*` 表述**（REWORK1_REVIEW_FAIL / F8′）；已由下方 **§10 STATIC_REWORK2** 单独闭合。全部运行检查继续 **UNRUN**。

## 9. 交接（REWORK1 时点；历史保留）

- 当时状态：`DELIVERY_READY`（STATIC_REWORK1 代码/测完成；§3.4 文档漂移待 REWORK2）
- 静态终态上限：`R2B_BRIDGE_CLI_STATIC_DELIVERED`
- 当时下一步：原独立 reviewer 复验 → 检出 F8′ → 任务书 §10 批准 delivery-only REWORK2

## 10. STATIC_REWORK2（对照任务书 §10 / REWORK1_REVIEW_FAIL F8′）

| 项 | 内容 |
|---|---|
| 范围 | **仅**本 delivery；未改 production / tests / taskbook / review |
| 现象 | 冻结合同 §3.4 仍写 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY` 与别名彼此 `is`；生产已无这些符号，权威为 import-time closure |
| 根因 | REWORK1 改 authority 后只在 §8.F6 叙事纠正，未回写 §3.4 SSOT 段 |
| 应遵循规则 | 任务书 §9.F8 / §10；冻结合同必须与当前源码一致 |
| 最小复现 | 对照旧 §3.4 与 `successor_bridge.py` 95–127（无 `_CANONICAL_*`） |
| 本次修改 | 删除陈旧 `_CANONICAL_*` 门禁表述；§3.4 改为 closure 真身 + `__code__` + runtime 属性 `is`、双侧 impostor 拒绝、AST exact1 + 不拆真身 integration |
| 通过条件 | §3.4 与源码及 §8.F6 / 测试名一致；读者无法再按过期别名合同验收 |
| UNRUN | 本 REWORK2 **未**运行 Python / pytest / Ruff / mypy / cold / worker / Qlib / network / stage / commit |
| `CONTRACT_STOP` | **未触发**（文档-only 足以闭合 F8′） |

## 11. 交接（REWORK2 时点；历史保留）

- 当时状态：`DELIVERY_READY`（STATIC_REWORK2 完成）
- 静态终态：`R2B_BRIDGE_CLI_STATIC_DELIVERED`
- 当时下一步：原独立 reviewer 复验 §3.4 → `REWORK2_REVIEW_PASS` → 申请 Windows VALIDATION1

## 12. STATIC_REWORK3（对照任务书 §11 / VALIDATION1 F9–F10）

### 12.1 VALIDATION1 证据绑定（诚实）

| 项 | 记录 |
|---|---|
| 权威摘要来源 | 任务书 §11（实现者只读） |
| identity | **PASS**（§11） |
| unit exact2 | **`18 passed / 1 skipped / 2 failed`**（§11；两项为首失败，测试承载/夹具，非 production 红） |
| integration exact2 | **UNRUN** |
| Ruff exact6 | **UNRUN** |
| mypy production2 | **UNRUN** |
| cold production2 | **UNRUN** |
| exact9 scope/diff/temp/process | **UNRUN** |
| evidence root | **未在任务书 §11 给出具体路径**；本会话 STATIC_ONLY 只读检索 `artifacts/agent_runs/*r2b*` **未发现**对应 VALIDATION1 根目录 → 记为 `NOT_CITED_IN_TASKBOOK_§11` / `NOT_FOUND_UNDER_artifacts/agent_runs/*r2b*`（**不伪造**路径） |
| summary SHA | **未在任务书 §11 给出**；本会话未计算、未运行校验 → 记为 `NOT_CITED_IN_TASKBOOK_§11`（**不伪造** SHA） |

本 REWORK3 **未**重跑 VALIDATION1，也 **未**把 `18/1/2` 改写为通过。

### 12.2 F9 / F10

| ID | 现象 | 根因 | 应遵循规则 | 最小复现 | 修正测试 | 通过条件 |
|---|---|---|---|---|---|---|
| F9 | `test_rejects_wrong_dump_target_and_timeout_types` 对 `float("nan")`/`float("inf")` 走 `_write_request` → `json.dumps(..., allow_nan=False)` 在 bridge 前抛 `ValueError` | 测试要求 canonical serializer 生成其合同禁止的非有限 JSON | §11.F9：非有限须 test-owned raw `NaN`/`Infinity` token 进入 bridge；不得改 serializer / `allow_nan=True` / 字符串化 / 弱化 bool·int·0·负值 | VALIDATION1 unit 失败节点 + 对 `_write_request(…, float("nan"))` 的静态路径 | 同测：`(True, 30, 0.0, -1.0)` 仍走 `_write_request`；`NaN`/`Infinity` 由 raw bytes 替换 `"timeout_seconds":30.0`；断言 `SUCCESSOR_BRIDGE_INPUT_INVALID`、factory/entry 仍为导入真身、controlled 不存在 | bridge 输入边界拒非有限；writer 合同不放宽；零副作用 |

**F9 静态残留风险（诚实，不扩白名单）：** 生产 `_load_canonical_request_object` 在 `json.loads` 接受非标准 `NaN`/`Infinity` 后，会对解析对象调用 `_canonical_json_bytes(..., allow_nan=False)`。若该 `ValueError` 未被捕获为 `_fail_input()`，则 raw-token 路径在运行时可能冒出裸 `ValueError` 而非 `SUCCESSOR_BRIDGE_INPUT_INVALID`。本轮 **禁止** 改 production；已按 §11 落地 test-owned raw token。VALIDATION2 若仍红，须另开 production 最小捕获返工，**不得**把本轮 18 绿冒充整包 PASS。

| F10 | `test_dump_toctou_same_size_content_swap_rejects_before_entry` 为计数 monkeypatch `_require_canonical_entrypoints`；且用全局 read 计数 `n==1`，dump 非首次读时 swap 不触发，落到 identity 门禁而非 dump TOCTOU | 测试替换了 canonical identity gate，且 TOCTOU 注入键错误 | §11.F10：不替换 factory/entry/`_require_canonical_entrypoints`；仅在 read/stat seam 上同 size 内容替换或 mtime 漂移；entry=0 靠窄观察/既有 fake | VALIDATION1 unit 失败节点 + 静态读该测 | 同测：仅保留 config/G1 fake；按 **dump 路径** 首次读后 `dump→DUMP`；断言 INPUT、`swapped`、authority/`_require_canonical_entrypoints` 对象不变、controlled 仅 preexisting marker、无 completion/receipts | 失败进入 dump TOCTOU/mtime guard；canonical authority 完整保留；controlled 零写 |

### 12.3 本轮范围与 UNRUN

| 项 | 内容 |
|---|---|
| 允许写入 | **仅** `tests/unit/test_m3_successor_bridge.py` + 本 delivery |
| 冻结只读 | production 两文件、其余 tests、taskbook、review |
| 本会话执行 | **STATIC_ONLY**：零 Python / pytest / Ruff / mypy / cold / Qlib / network / worker / stage / commit |
| `CONTRACT_STOP` | **未触发** |
| 下一步 | 交**同一原独立 reviewer**只读复验：production SHA 不变；F9/F10 失败进入目标 bridge guard；零副作用。`REVIEW_PASS` 后申请**新完整 VALIDATION2**（identity → unit exact2 → integration exact2 → Ruff exact6 → mypy production2 → cold production2 → exact9 scope）；**不得**沿用 VALIDATION1 失败轮 |

## 13. 交接（REWORK3 时点；历史保留）

- 当时状态：`DELIVERY_READY`（STATIC_REWORK3 test-only；自承 F9 生产残留）
- 静态终态上限：`R2B_BRIDGE_CLI_STATIC_DELIVERED`
- 当时下一步：原独立 reviewer 复验 → **`REWORK3_REVIEW_FAIL` / P1 F9′**（审查 §10）；F10 静态通过并冻结

## 14. STATIC_REWORK4（对照任务书 §12 / REWORK3_REVIEW_FAIL F9′）

### 14.1 历史保留

| 项 | 状态 |
|---|---|
| VALIDATION1 | §12.1 原文保留：`18 passed / 1 skipped / 2 failed`；evidence root/summary SHA `NOT_CITED…` |
| REWORK3 | §12.2 F9/F10 与自承残留原文保留；**不**洗白为 PASS |
| REWORK3_REVIEW_FAIL | 审查 §10：**P1 F9′**；F10 静态通过冻结 |
| F10 | **本轮未重写**；仍为 dump-path TOCTOU + 不替换 authority |

### 14.2 F9′

| 项 | 内容 |
|---|---|
| 现象 | raw `NaN`/`Infinity`（及对抗 `-Infinity`）测断言 `SuccessorBridgeError`，但 `_load_canonical_request_object` 对 `_canonical_json_bytes(..., allow_nan=False)` 失败未捕获 → 裸 `ValueError`；经 CLI 会落入 runtime 族 exit 3 |
| 根因 | re-encode 调用在 loads 的 try 外；REWORK3 禁改 production，通过条件与可达异常不一致 |
| 应遵循规则 | 任务书 §12：re-encode `ValueError`/等价 canonical-value 错误 → 立即 `_fail_input()`；不放宽 `allow_nan`；不改 canonical bytes SSOT；不 broad-catch runtime；三 token + CLI exit 2；不要求到达 `math.isfinite` |
| 最小复现 | 审查 §10 / R13：`"timeout_seconds":NaN|Infinity|-Infinity` → dumps `allow_nan=False` → 未捕获 `ValueError` |
| 修复 | `successor_bridge.py`：`try: canonical = _canonical_json_bytes(parsed) except (TypeError, ValueError): _fail_input()`；`allow_nan=False` 与 byte 相等门禁不变 |
| 新增/修正测试 | unit bridge：三 token → `SUCCESSOR_BRIDGE_INPUT_INVALID`、factory/entry 真身不变、controlled 不存在；unit CLI：`test_raw_nonfinite_request_is_stable_input_exit_two`（Infinity）→ stderr 仅输入码、exit 2、无路径/`ValueError`/`Infinity` 泄露 |
| 通过条件 | 三 token 稳定 INPUT；CLI 至少一个 raw 非有限 → exit 2；无裸 `ValueError`；成功 0 / runtime 3 合同未改；F10 保持 |
| UNRUN | 本 REWORK4 **STATIC_ONLY**：零 Python / pytest / Ruff / mypy / cold / Qlib / network / worker / stage / commit |
| `CONTRACT_STOP` | **未触发** |

### 14.3 本轮范围

| 项 | 内容 |
|---|---|
| 允许写入 | `successor_bridge.py`；`tests/unit/test_m3_successor_bridge.py`；`tests/unit/test_m3_run_successor.py`；本 delivery |
| 冻结只读 | taskbook、review、integration、`run_successor.py`、其余 production |
| 下一步 | 交**同一原独立 reviewer**只读复验 F9′；无 P0/P1/P2 后申请**新完整 VALIDATION2** |

## 15. 交接（REWORK4 时点；历史保留）

- 当时状态：`DELIVERY_READY`（STATIC_REWORK4 / F9′）
- 静态终态上限：`R2B_BRIDGE_CLI_STATIC_DELIVERED`
- 当时下一步：原独立 reviewer 复验 → 申请完整 VALIDATION2

## 16. STATIC_REWORK5（对照任务书 §13 / VALIDATION2 mypy；历史保留）

### 16.1 VALIDATION2 类型证据绑定（已由 §18 补全 SHA；本节保留返工叙事）

| 项 | 记录 |
|---|---|
| identity | **PASS** |
| unit exact2 | **`21 passed / 1 skipped`** |
| integration exact2 | **`6 passed`** |
| Ruff exact6 | **PASS** |
| mypy production2 | **首失败 STOP**：`successor_bridge.py:184: "object" not callable [operator]` |
| cold / scope | 当时 **UNRUN**（后由 POSTFIX VALIDATION3 闭合，见 §18） |
| evidence root | `artifacts/agent_runs/m3-r2b-rebuilt-validation2-20260826T201000Z` |
| summary SHA | `90CE3B52EA88278F32A3F4A59ED2B871C496672C3C317AEEE8F295B339FF5E8B` |
| mypy stdout SHA | `9E3C7ACCDE7EC9DCE0EBA991FD07676A30D4BA9779C294B30663F56B345BC40A` |

**不**把本节解读为 VALIDATION2 整包 PASS（mypy 当时 STOP）。

### 16.2 返工记录

| 项 | 内容 |
|---|---|
| 现象 | mypy：`_require_canonical_entrypoints()` 调用处将返回类型视为 `object`，报 `"object" not callable` |
| 根因 | `_build_entrypoint_authority(...) -> object` 注解过宽；真实唯一返回值是内部无参 callable |
| 类型规则 | 任务书 §13：从 `collections.abc` 导入 `Callable`；返回注解精确为 `Callable[[], None]`；参数仍为 `object`；禁止 `Any`/`cast`/`type: ignore`/Protocol/wrapper |
| 最小复现 | VALIDATION2 mypy production2 → `successor_bridge.py:184` |
| 修复 | `from collections.abc import Callable, ...`；`_build_entrypoint_authority(...) -> Callable[[], None]` |
| 通过条件 | production 逆向 diff **仅** import + 返回注解；函数体/closure/`is`/`__code__`/`__wrapped__`/错误分类/canonical bytes/运行分支不变；tests 未改 |
| 复验 | **`REWORK5_REVIEW_PASS`** |
| `CONTRACT_STOP` | **未触发** |

## 17. 交接（REWORK5 时点；历史保留）

- 当时状态：`DELIVERY_READY`（STATIC_REWORK5）；`REWORK5_REVIEW_PASS`
- 当时下一步：窄 postfix VALIDATION3

## 18. EVIDENCE_UPDATE：组合 Windows 工程证据

本轮仅更新任务书 §14 与本 delivery；production / tests / review **未改**；零 Python / stage / commit。

| 轮次 | evidence root / SHA | 结果（原生；保留，不洗白） |
|---|---|---|
| VALIDATION1 | （历史 fixture 轮） | identity **PASS**；unit `18 passed / 1 skipped / 2 failed`（NaN canonical 输入 + TOCTOU fixture）；integration / Ruff / mypy / cold / scope **UNRUN** |
| REWORK3 / 复验 | test-only F9/F10 | `REWORK3_REVIEW_FAIL` / P1 F9′；F10 静态通过冻结 |
| REWORK4 / 复验 | loader `_fail_input` + 三 token / CLI exit 2 | `REWORK4_REVIEW_PASS`（F9′ 闭合）；历史 §12–§14 保留 |
| VALIDATION2 | root `artifacts/agent_runs/m3-r2b-rebuilt-validation2-20260826T201000Z`；summary `90CE3B52EA88278F32A3F4A59ED2B871C496672C3C317AEEE8F295B339FF5E8B`；mypy stdout `9E3C7ACCDE7EC9DCE0EBA991FD07676A30D4BA9779C294B30663F56B345BC40A` | identity **PASS**；unit `21 passed / 1 skipped`；integration `6 passed`；Ruff exact6 **PASS**；mypy production2 **首失败** `:184 object not callable`；cold / scope **UNRUN** |
| REWORK5 / 复验 | 仅 `Callable` import + 返回注解 | **`REWORK5_REVIEW_PASS`** |
| POSTFIX VALIDATION3 | root `artifacts/agent_runs/m3-r2b-rebuilt-postfix-validation3-20260826T202000Z`；summary `7F9A7DA9FA3DD4E5B2E136193E4DDBDF96AC8C5F92A4B2A286A7EC571DB8C65E` | identity / Ruff `successor_bridge.py` / mypy production2 / cold production2 / exact9 scope / cached0 / diff / temp / process **全部 PASS**；`0xF00` released |

**组合口径：** Windows 工程验证 = VALIDATION2 已绿段（unit + integration + Ruff）∪ POSTFIX VALIDATION3（identity + 单文件 Ruff + mypy + cold + scope）。VALIDATION1 失败与 VALIDATION2 mypy STOP **保留为历史**，**不**伪造“单轮全绿”。

**状态上限申请：** `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`。

**仍 OPEN：** actual worker / 真实 Qlib / network / new controlled root / retained / Linux / 真实 M3 Gate。

## 19. 交接（当前）

- 实现会话结束状态：`EVIDENCE_UPDATE_READY`
- 状态上限：`R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`（组合证据）
- 本轮未 stage / commit；交经理/统筹合流与独立证据复核
- 本实现会话 **退出**
