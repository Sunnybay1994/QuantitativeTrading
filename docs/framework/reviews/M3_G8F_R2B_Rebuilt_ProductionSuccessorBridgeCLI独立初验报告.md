# M3-G8F-R2B Rebuilt Production Successor Bridge / CLI 独立初验报告

日期：2026-08-26<br>
身份：未参与本包实现的全新独立静态初验 Agent（STATIC_ONLY；无委派 / 无 subagent）<br>
task id：`M3-G8F-R2B-REBUILT-PRODUCTION-SUCCESSOR-BRIDGE-CLI`<br>
exact base / HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（一致）<br>
branch：`codex/m3-g8f-r2b-production-successor-bridge-cli-rebuilt`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2b-production-successor-bridge-cli-rebuilt`<br>
唯一写入：本报告<br>
结论：**DOC_REVIEW_PASS**（`EVIDENCE_REVIEW_PASS` 语义保留于 §13；本轮见 §14）<br>
终态上限声明：可支持组合口径 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`；**不**表示单轮全绿洗白；actual worker / 真实 Qlib / network / new root / retained / Linux / 真实 M3 Gate 仍 **OPEN**。本证据复核 **未** 运行 Python / pytest / Ruff / mypy / cold。

## 0. 审查边界

- 已完整阅读：任务书 `docs/framework/tasks/M3_G8F_R2B_Rebuilt_ProductionSuccessorBridgeCLI任务书.md`、交付报告、exact 实现所有权 1–6（`successor_bridge.py` / `run_successor.py` 及四份 unit/integration 测试）。
- 为评估调用边界只读相关主仓公共 API：`successor_runtime.py`（`SuccessorRuntimeRequest` / `run_production_two_fold_successor` / `make_canonical_successor_production_dependencies` / `project_stage_root` / resume+terminal）、`successor_upstream_stage.validate_successor_toolchain_binding`、`fetch_qlib_tool.DEFAULT_TARGET_PATH` / `build_qlib_dump_tool_spec`。
- production / tests / 任务书 / 交付：**只读**；未改实现、未改测试、未改任务书、未改交付、未改 runtime/orchestration/Gate/config/roadmap/SSOT。
- **STATIC_ONLY**：未运行 Python / pytest / Ruff / mypy / cold import / 真实 Qlib / worker / network / 新 controlled root / retained / stage / commit；未读取旧 STOP/evidence worktree；未创建或调用 subagent。
- dirty（只读观察）：exact9 内 `??`（task/delivery/实现 1–6 + 本报告写入前无 review）；未见白名单外生产路径；`git rev-parse HEAD` == exact base；owned Python `git diff --check` 空输出。

## 1. 合同逐项静态核对

| # | 合同点（任务书） | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | 唯一 bridge：验 request → fresh config/release/toolchain → 零参 factory → `run_production_two_fold_successor`；不复制 stage/fold/Gate 序列 | **实现面通过** | `run_production_successor_bridge`（`successor_bridge.py` 146–168）仅组装 `SuccessorRuntimeRequest` 后调用入口；无 Gate 枚举/选择 |
| 2 | `public_apis=None`；R2P/R2S/R2A/R2W callable `is` identity；禁止 caller 注入 factory/handler | **实现面通过 / 测部分** | 入口 `public_apis=None`（156–160）；`_require_canonical_entrypoints` + `_require_canonical_dependencies`（219–261）；unit wrapper 拒 factory/entry；**未**钉 impostor deps 槽位 / `__wrapped__` 专测 |
| 3 | schema `m3-successor-bridge-request-v1`；拒 subclass/PurePath/relative/symlink/reparse/未知缺失重复/非 canonical/读取前后漂移 | **实现面大体通过 / 强制测缺口** | canonical bytes + `object_pairs_hook` + 双读+inode/size/mtime（264–286）；Path 合同（564–580, 699–711）；unit 覆盖未知/缺失/重复/非 canonical/subclass/PurePath/relative/bytes 漂移；**symlink/reparse 测名存实亡**（见 F1） |
| 4 | PROJECT-only controlled；输入失败在创建/写入前；fold 少/多/重复/乱序；未引用文件不发现 | **实现面通过 / 强制测缺口** | 不 `mkdir`；`_require_real_directory` + `project_stage_root` 单根对齐（333–359）；unit 有 arity/乱序/controlled 不存在；**“duplicates”测未构造双 `fold_001`**（见 F2） |
| 5 | G1 fresh verifier；config public parser；toolchain=`DEFAULT_TARGET_PATH`+`build_qlib_dump_tool_spec` 两 fold exact；无 ensure/download/network/Qlib | **实现面通过 / 强制测缺口** | `_fresh_verify_release`/`_fresh_load_config`；dump path==`DEFAULT_TARGET_PATH`；`specs[0]==specs[1]`（469–477）；无 `ensure_qlib_dump_tool`；unit **未**测两 fold spec 漂移（见 F3） |
| 6 | 错误归一两族；CLI 仅 `--request`；help 零 IO；成功一行 JSON；失败 stderr 仅码；exit 冻结 | **部分失败** | bridge：`SUCCESSOR_BRIDGE_INPUT_INVALID` / `SUCCESSOR_BRIDGE_RUNTIME_FAILED`；CLI exit 0/2/3；help/usage/成功 JSON/桥接错误码测存在；**CLI 裸 `Exception`→INPUT/2，与 delivery 冻结「未预期→RUNTIME/3」冲突**（见 F4） |
| 7 | resume 显式 bool；false 拒旧 terminal；true 仅 exact identity 复用；request/toolchain 漂移拒绝 | **部分通过** | integration：false→`BRIDGE_RUNTIME_ERROR`；true reuse；toolchain size 漂移→INPUT；**缺 request identity（如 `code_version`）漂移拒旧 terminal**（见 §3 R5） |
| 8 | fixture 达两 fold；factory/entry exact1；无 actual worker/Qlib/network | **实现+测面可读通过（UNRUN）** | integration spy：`factory_calls==["factory"]`、`entry_calls==["entry"]`；boundary fixture；不启动真实 worker |
| 9 | 成功投影保留 terminal identity / receipt refs；无绝对路径泄露 | **实现面通过** | 投影取 attestation 相对 `controlled_output_root`、`two_fold_identity`、receipt node/sha、gate 名（171–216）；不含 `terminal_path` |
| 10 | exact9 范围；不改 runtime/orchestration/Gate/config/`__init__` | **通过** | dirty 仅任务书+delivery+1–6+本报告；runtime 等只读 |

## 2. 发现分级

### [P1] 任务书 §7.1 强制 symlink/reparse 反例未落地 — 测试面

`tests/unit/test_m3_successor_bridge.py` 函数名 `test_rejects_path_subclass_purepath_relative_and_symlink` **仅**覆盖 `SubPath` / `PurePosixPath` / relative；**无** `symlink_to`、junction、或 `FILE_ATTRIBUTE_REPARSE_POINT` / `S_ISLNK` 注入用例。交付 §4 行 1 却映射为已覆盖 symlink/reparse。

实现面 `_lstat_regular_file` / `_require_concrete_absolute_regular_file` / 成员路径遍历可读为应拒 link/reparse，但任务书 §7.1 为**强制反例清单**；对照本系列初验先例，名实不符且交付过声明构成证据 FAIL。

### [P1] 任务书 §7.3 强制 fold「重复」反例未落地 — 测试面

`test_rejects_fold_arity_order_duplicates_and_unreferenced_files` 实际只测：乱序两 fold、单 fold、未引用 sibling 不被打开。**从未**构造 `folds=[{fold_001...},{fold_001...}]`。实现 `len(set(fold_names)) != 2`（323–325）静态可读，但强制反例证据未闭合；函数名中的 `duplicates` 为虚标。

### [P1] 任务书 §7.4 强制两 fold toolchain spec 漂移反例未落地 — 测试面

`test_rejects_wrong_dump_target_timeout_types_and_spec_drift` 只覆盖 wrong `qlib_dump_tool_path` 与 timeout `bool/int/0/nan/inf/-1`。**无**两份 `LoadedM3Config` / request 折配置导致 `build_qlib_dump_tool_spec` 结果不等的用例。实现 `specs[0] != specs[1] → _fail_input`（473–474）存在，但 §7.4「两 fold spec 漂移」强制测缺失；交付 §4 行 4 过声明。

### [P2] CLI 未预期异常错误族与 delivery 冻结表冲突 — `run_successor.py:84-86`

交付 §3.3 冻结：「入口期未预期异常」→ `SUCCESSOR_BRIDGE_RUNTIME_FAILED` / exit `3`。CLI：

```text
except Exception:
    sys.stderr.write(f"{BRIDGE_INPUT_ERROR}\n")
    return EXIT_INPUT  # 2
```

桥接层对 runtime 外 `Exception` 已 `_fail_runtime()`（166–167），但投影/编码或其它 CLI 路径裸异常会被标成**输入族**。与任务书 §6「两固定非零值并在 delivery 冻结」及交付表不一致；现有测只钉 `SuccessorBridgeError` 两码，**不**钉裸 `Exception` 族。

### 无 P0

主路径静态可读：不复制 Gate 序列、`public_apis=None`、import-time factory/entry 冻结、`resume` 显式、help 零 request IO、失败前不创建 controlled、投影相对根无 `terminal_path`。本轮 FAIL 主因是 **§7 强制反例名实不符（F1–F3）** 与 **CLI 错误族冻结漂移（F4）**。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1 — request 叶路径 symlink / Windows reparse（canonical path TOCTOU 前置）

实现者覆盖 subclass/PurePath/relative；**未**覆盖 link 叶。

**最小静态复现（未执行）：**

1. 合法 canonical request bytes 写入普通文件 `real.json`。
2. 创建 `link.json` → symlink/junction 指向 `real.json`（或对 `os.lstat` 注入 `S_ISLNK` / `FILE_ATTRIBUTE_REPARSE_POINT`）。
3. `run_production_successor_bridge(request_path=Path(link.json 的绝对路径))`。
4. 预期：`SUCCESSOR_BRIDGE_INPUT_INVALID`；不得跟随 link 读入后伪成功。

**通过条件：** unit 至少一条真实 symlink（或注入）+ 可选 mid-path reparse 成员文件；交付映射可逐条对齐 §7.1。

### 反例 R2 — dump tool 同 size 内容置换 × 缺二次读 / 缺 mtime（tool bytes TOCTOU）

request 使用双读 + `st_mtime_ns`（264–276）；dump 仅单读 + inode/size（479–488），**不**比 mtime、**不**在二次 lstat 后再读。随后 `validate_successor_toolchain_binding` 再独立 `read_bytes`——窗口依赖第二次读 fail-closed，但 bridge 自身未达 request 同级 TOCTOU。

**最小静态复现（未执行）：**

1. fixture dump size/sha 与 request/toolchain 一致。
2. monkeypatch：第一次 `_read_regular_file_bytes` 返回合法 bytes；在 bridge 首次读后、`validate_successor_toolchain_binding` 读前，同 inode 同 size 写入异内容（或只推进 `st_mtime_ns`）。
3. 预期：稳定 `SUCCESSOR_BRIDGE_INPUT_INVALID`；不得带着已过期的首次读 hash 进入 runtime。

**通过条件：** dump/config 与 request 对齐「读前 lstat → read → 读后 lstat(+mtime) → 再 read 且 bytes 相等」；定向测锁定同 size 置换。

### 反例 R3 — 双槽同位 impostor（callable identity 替换）

实现者 unit 只替换 `runtime.make_canonical_*` / `run_production_*` 而保留 `_CANONICAL_*` 真身 → `is` 失败。integration exact1 则把 **两侧同时**换成同一 spy（等于绕过「冻结真身」门禁来数次数）。

**最小静态复现（未执行）：**

1. `impostor = lambda: real_factory()`（无 `__wrapped__`）。
2. 同时 `monkeypatch` `bridge._CANONICAL_FACTORY` 与 `runtime.make_canonical_successor_production_dependencies` 为**同一** `impostor`（entry 同理）。
3. 当前 `_require_canonical_entrypoints` 因 `is` 对称而**放行**。
4. 合同预期（§3/§7.5）：拒绝任何非 import-time 真身 callable；exact1 计数不得以拆除 identity 门禁为前提，或另测「真身未替换时 exact1」。

**通过条件：** 门禁改为与模块 import 捕获的不可变真身比较且测试不可改写该真身；或文档冻结「仅检测 runtime 模块属性漂移」并新增「假 factory 返回错误槽位 `is`」测。

### 反例 R4 — 两 fold `dump_script_sha256` / size 漂移（config/release/toolchain drift）

**最小静态复现（未执行）：**

1. integration fixture 两 config 对象：fold_001 与 fold_002 的 `runtime.qlib.dump_script_sha256`（或 bytes）不同，其余合法。
2. request toolchain sha 对齐其一。
3. `run_production_successor_bridge` → 预期在 `specs[0]!=specs[1]` 或后续 validate 处 `SUCCESSOR_BRIDGE_INPUT_INVALID`；不得进入 entry。

**通过条件：** unit/integration 显式断言；函数名 `spec_drift` 与行为一致。

### 反例 R5 — `resume=true` + request identity 漂移拒旧 terminal

实现者只测 toolchain **size** 漂移→INPUT。§7.6 要求 request/**toolchain 任一**漂移拒绝旧 terminal。

**最小静态复现（未执行）：**

1. 先 `resume=true` 跑通并留下 terminal。
2. 仅改 request `runtime_identity.code_version`（或 deps fingerprint），其余路径/toolchain bytes 不变，仍 `resume=true`。
3. 预期：不得 `reused=True`；应 `SUCCESSOR_BRIDGE_RUNTIME_FAILED` 或输入族（以 runtime 对 identity 失配的稳定码为准），且 stderr 无路径。

**通过条件：** 至少一条 request 身份字段漂移 + 一条 toolchain sha 漂移（size 已有）。

### 反例 R6 — 失败前零副作用：controlled 已存在但 identity 错配仍零写入

实现者测 missing controlled / `..` 后不存在。补充：**controlled 目录已存在**，folds 合法外形但两 config `artifact_root` 不一致或与 controlled 相对路径错配。

**最小静态复现（未执行）：**

1. 预建 `output/stage`；fold configs 指向不同 artifact_root 或错误相对根。
2. 调用 bridge → INPUT。
3. 断言：除既有空目录外无新文件（无 `completion.json`、无 receipts、无临时文件）；`rglob` 集合相对调用前不变（或仅允许测试自己写入的 sentinel 不出现）。

**通过条件：** integration/unit 钉「失败后 tree digest/文件集不变」。

### 反例 R7 — CLI stderr 脱敏 × 裸异常族

实现者已测 `SuccessorBridgeError` 两码无路径。补充：

1. monkeypatch `run_production_successor_bridge` 抛 `RuntimeError("C:\\secret\\path")` 或含 request 绝对路径的 `ValueError`。
2. 当前 CLI → stderr 仅 `SUCCESSOR_BRIDGE_INPUT_INVALID`（脱敏碰巧成立）但 **exit=2 / 输入族**，与 delivery RUNTIME/3 冲突。
3. 预期（按冻结表）：stderr 一行 `SUCCESSOR_BRIDGE_RUNTIME_FAILED`，exit 3，且无路径碎片。

**通过条件：** 修正 CLI 映射 + 参数化测裸异常。

### 反例 R8 — factory/entry exact1 在**未**替换 `_CANONICAL_*` 时计数

当前 exact1 测同时替换冻结别名与 runtime 属性。补充：仅 wrap 探测调用次数且仍满足真身 `is`（若设计允许 spy 挂在真身外），或源码级断言 `run_production_successor_bridge` 词法上各调用一次且 `_require_canonical_*` 不再调用 factory。

**通过条件：** exact1 证据与 identity 门禁同时成立，而非互斥。

## 4. 失败项（现象—根因—规则—最小复现—新增测试—通过条件）

### F1 — §7.1 symlink/reparse 强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | 测名含 symlink，体不含 link/reparse；交付仍映射已覆盖 |
| 根因 | 只写了 subclass/PurePath/relative |
| 规则 | 任务书 §4、§7.1；交付不得过声明 |
| 最小复现 | 静态阅读 `test_rejects_path_subclass_purepath_relative_and_symlink` 125–149 行 |
| 新增测试 | request/python/dump/project 成员路径的 symlink 与 Windows reparse 各至少一条 |
| 通过条件 | 稳定 `SUCCESSOR_BRIDGE_INPUT_INVALID`；交付映射可逐条指到断言 |

### F2 — §7.3 fold 重复强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | `duplicates` 测名无双 `fold_001` 用例 |
| 根因 | 只覆盖乱序与 arity=1 |
| 规则 | 任务书 §7.3 |
| 最小复现 | 构造两元素 folds 同名 `fold_001` 的 canonical request |
| 新增测试 | `test_rejects_duplicate_fold_ids` |
| 通过条件 | INPUT；且失败后无 controlled 新写入 |

### F3 — §7.4 两 fold spec 漂移强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | `spec_drift` 测名无两 fold `build_qlib_dump_tool_spec` 不等用例 |
| 根因 | 只覆盖 wrong dump path 与 timeout 类型 |
| 规则 | 任务书 §5.3、§7.4 |
| 最小复现 | 见 §3 R4 |
| 新增测试 | 两 config dump sha/size 不一致 → INPUT，且 entry 调用次数为 0 |
| 通过条件 | 断言在 factory/entry 前 fail；delivery 不再虚标 |

### F4 — CLI 未预期异常映射违反冻结表

| 字段 | 内容 |
| --- | --- |
| 现象 | 裸 `Exception` → `SUCCESSOR_BRIDGE_INPUT_INVALID` / exit 2 |
| 根因 | `main` 宽捕获归入输入族 |
| 规则 | 任务书 §6；交付 §3.3 |
| 最小复现 | 见 §3 R7 |
| 新增测试 | 裸异常 → RUNTIME 码与 exit 3；stderr 单行无路径 |
| 通过条件 | 与交付冻结表逐字一致 |

## 5. 已通过项（压缩）

- exact base/HEAD/branch/worktree 与任务书一致；dirty 限于 exact9。
- bridge 不枚举 Gate；`public_apis=None`；成功返回原生 `SuccessorRunResult`。
- request canonical JSON、重复键拒绝、双读+mtime TOCTOU（request 文件本身）。
- Path subclass/PurePath/relative 拒绝；PROJECT-relative 拒 `..`/`\`/绝对伪相对。
- 失败路径不 `mkdir` controlled（folds=`[]` / `controlled=..` 测存在）。
- dump path 钉死 `DEFAULT_TARGET_PATH`；timeout 拒绝 bool/int/0/nonfinite（实现+测）。
- factory/entry **单侧** monkeypatch wrapper 拒绝（unit）。
- resume false/true 主路径 + toolchain size 漂移（integration，UNRUN）。
- CLI help 零目录；usage/桥接错误 stderr 仅稳定码；成功一行 canonical JSON（测面，UNRUN）。
- 无 `ensure_qlib_dump_tool` / env / `sys.executable` / glob 发现接线。

## 6. 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| new controlled root / retained 真跑 / stage / commit | **未执行** |
| Windows 定向：identity → unit exact2 → integration exact2 → Ruff exact6 → mypy production2 → cold production2 → exact9 scope | **阻断**（需先返工至 REVIEW_PASS） |
| M3 Gate / R2B Windows engineering validated | **未关闭** |

## 7. 结论（首轮）

**REVIEW_FAIL**（P1：F1+F2+F3 强制反例证据缺口与交付过声明；P2：F4 CLI 错误族与冻结表冲突）。返工后须由**同一**独立 reviewer 按任务书 §9 做 STATIC_REWORK1 复验；复验通过前不得申请 Windows 定向验证，更不得宣称 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` 或 M3 Gate 完成。

---

## 8. STATIC_REWORK1 复验（对照任务书 §9 / 初验 F1–F8）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读更新后的 exact9 实现/tests/delivery + 任务书 §9；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / worker / network / new root / retained / stage / commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）

### 8.1 F1–F8 逐项静态结论

| ID | 合同要求 | 静态结论 | 证据 |
| --- | --- | --- | --- |
| F1 | request 叶真实 symlink + 成员文件 symlink；不可用时非跟随 lstat reparse 注入；均 INPUT；不 patch 掉 guard | **通过** | `test_rejects_request_leaf_symlink_or_reparse_injection`：真实 `symlink_to`（若 OS 允许）+ 对 `bridge.os.lstat` 注入 `FILE_ATTRIBUTE_REPARSE_POINT`；`test_rejects_member_file_symlink_without_following_target`：config 叶真实 symlink（不可用则 skip）。生产 `_lstat_regular_file` / `_require_project_member_file` 仍非跟随。测名已去掉虚标 symlink。 |
| F2 | 双 `fold_001` canonical request；factory/entry 前 INPUT；controlled 零写 | **通过** | `test_rejects_duplicate_fold_ids_before_factory_and_without_controlled_write`：两元素同名；`_require_canonical_entrypoints` 计数 0；controlled 不存在。生产 preflight（321–334）在 config/release IO 前拒重复/乱序。原 arity/乱序/sibling 测保留。 |
| F3 | 两真实 config 仅 dump spec 字段不同；`build_qlib_dump_tool_spec` 不等 → INPUT；entry 0；不 monkeypatch specs 列表 | **通过** | `test_rejects_two_fold_tool_spec_drift_via_public_build`：两 `LoadedM3Config` dump sha 不同并 `assert build_qlib_dump_tool_spec(a)!=build_qlib_dump_tool_spec(b)`；生产路径调用 public `build_qlib_dump_tool_spec`；gate 计数 0。 |
| F4 | 非 `SuccessorBridgeError` → stderr 仅 `SUCCESSOR_BRIDGE_RUNTIME_FAILED`、exit 3、无路径 | **通过** | `run_successor.py` 84–86；unit 参数化 `RuntimeError(C:\...)` / `ValueError(/tmp/...)`；integration `boom_bare` 同口径。输入族 exit 2 / 成功 0 未改。 |
| F5 | dump/config 等价「lstat→read→lstat(+mtime)→二次 read」；同 size 置换反例；INPUT 且 entry 0 | **通过** | `_read_stable_regular_file_bytes`（752–767）用于 request/config；dump 在 `_parse_toolchain` 499–514 显式 mtime+双读；`test_dump_toctou_same_size_content_swap_rejects_before_entry`：首读后同 size 写入 `DUMP` → INPUT，gate 0。 |
| F6 | 双侧同一 impostor 不得因彼此 `is` 通过；真身不可靠可改写别名；exact1 不拆门禁 | **通过（实现+测）** | `_build_entrypoint_authority` 闭包捕获 import-time 真身 + `__code__`（95–127）；无 `_CANONICAL_*` 模块别名。`test_rejects_bilateral_same_impostor_on_factory_and_entry` 同时替换 runtime factory/entry（及残留别名若存在）仍 INPUT。exact1 改 AST `test_bridge_source_calls_factory_and_entry_exactly_once`；integration `test_bridge_reaches_two_folds_without_replacing_canonical_identity` 不拆真身。 |
| F7 | resume=true 改 runtime identity 拒旧 terminal；toolchain size/SHA；controlled 已存在错配零写 | **通过** | resume 测：size→INPUT、SHA→INPUT、`code_version`→`BRIDGE_RUNTIME_ERROR`。`test_controlled_exists_but_artifact_mismatch_leaves_tree_unchanged`：预置 sentinel，改 fold_002 `artifact_root`，前后 tree/bytes 相等，无 completion/receipts/tmp。 |
| F8 | 纠正过声明；F1–F7 现象—根因—规则—复现—测试—通过条件；运行仍 UNRUN | **部分失败** | §8 首轮过声明纠正表与 F1–F7 逐项表存在且诚实；UNRUN 声明完整。**但冻结公共合同 §3.4 仍写 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY` 与「`runtime... is _CANONICAL_*`」**，与生产已删除别名、改用 closure 真身及同文档 §8.F6 自述**直接矛盾**（见 F8′）。 |

### 8.2 发现分级（复验）

### [P2] 交付冻结合同 §3.4 仍描述已删除的 `_CANONICAL_*` 别名门禁 — delivery §3.4 vs `successor_bridge.py`

任务书 §9.F8 要求 delivery 纠正过声明并与返工后实现一致。生产源码中 **不存在** `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY`（全文件 grep 空）；权威为 `_build_entrypoint_authority` 闭包。交付 §8.F6 已正确叙述 closure+`__code__`，但 §3.4「冻结公共合同」仍要求：

- 导入时冻结 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY`
- `runtime.make_canonical... is _CANONICAL_FACTORY`

这是**可演示的合同/实现漂移**：读者若按 §3.4 验收会寻找不存在的符号，或误以为旧双侧别名 `is` 模型仍是 SSOT。属 F8 未完全闭合，不是纯文风问题。

### 无 P0 / 无残留 P1

首轮 F1–F4（P1/P2）在实现与定向测上静态可读为已修复；F5–F7 按 §9 新增要求亦闭合。本轮唯一阻断为 **F8 冻结核心段落未与 REWORK1 机制同步**。

### 8.3 实现者本轮仍未使用的对抗反例（新增）

### 反例 R9 — 成员路径 reparse 注入（symlink skip 主机）

F1 成员测在 `OSError` 时 `pytest.skip`，**无**对成员 config 路径的 `lstat` reparse 注入回退。request 叶已有注入；成员 mid-path/leaf 在无 symlink 特权主机上可能零覆盖。

**最小静态复现（未执行）：** 对 `configs/fold_001.toml` 的 `os.lstat` 注入 reparse 位（不创建真实 junction），调用 bridge → 预期 INPUT，且不跟随目标内容。

**通过条件：** 成员路径与 request 叶对称：真实 symlink **或** 最窄 reparse 注入至少一条常驻。

### 反例 R10 — 改写 authority 闭包 cell 后双侧 impostor

§9.F6 要求「不可由测试/caller 重写」的真身。CPython 上可对 `_require_canonical_entrypoints.__closure__` 写入 `cell_contents`，同步替换 true_factory / true_factory_code / true_entry / true_entry_code 后再把 `runtime.*` 指到 impostor，可能使 `is`+`__code__` 同时满足。

**合同预期：** 要么拒绝（例如绑定 `id`/`__module__`/`qualname` 到 package-owned 不可变令牌，或检测 cell 被写），要么在 delivery 明确威胁模型不含闭包 cell 篡改并接受该上限。

**通过条件：** 定向测或书面冻结；不得 silently 依赖「测试不会写 cell」。

### 反例 R11 — config `load_m3_config` 窗口同 size 置换

config 使用 `_read_stable_regular_file_bytes` 于 load 前后，但 `load_m3_config(path)` 独立再读。补：稳定首读后、load 中、二次稳定读前的同 inode 同 size 内容翻转。

**通过条件：** 仍 INPUT；不得带着错误 parsed 语义进入 toolchain。

### 反例 R12 — 裸异常来自投影/编码路径（非 bridge）

现测 monkeypatch `run_production_successor_bridge`。补：bridge 成功返回后，`project_successor_bridge_result` 或 `decode` 抛裸异常 → 仍须 RUNTIME/3 且无路径（实现 84–86 静态可读应满足）。

### 8.4 失败项（复验）

### F8′ — 冻结合同 §3.4 与 closure 真身实现不一致

| 字段 | 内容 |
| --- | --- |
| 现象 | delivery §3.4 仍规定 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY` 与别名 `is` 门禁；生产已无这些符号 |
| 根因 | REWORK1 改 authority 后未回写冻结合同段；仅在 §8.F6 叙事纠正 |
| 规则 | 任务书 §9.F8；交付「冻结公共合同」须与 exact 实现同一事实 |
| 最小复现 | 对照 delivery §3.4 与 `successor_bridge.py` 95–127 / 全文件无 `_CANONICAL_*` |
| 新增测试 | 文档级：§3.4 改为 closure 真身 + `__code__` + runtime 属性 `is`；可选 unit 断言模块无 `_CANONICAL_FACTORY` 属性 |
| 通过条件 | §3.4 与源码/§8.F6 一致；无读者可跟随的过期别名合同 |

### 8.5 已通过项（REWORK1 压缩）

- F1 真实 symlink（request+成员）与 request reparse 注入；不拆除 `_is_link_or_reparse`。
- F2 双 `fold_001` + 门禁前失败 + controlled 不存在。
- F3 public `build_qlib_dump_tool_spec` 两 fold 不等。
- F4 CLI 裸异常 → RUNTIME/exit 3，路径脱敏测存在。
- F5 dump/config 稳定双读+mtime；dump 同 size 置换测。
- F6 闭包真身拒双侧 runtime 替换；AST exact1；integration 不拆真身达两 fold。
- F7 identity / toolchain SHA / 已存在 controlled 错配零写。
- 首轮过声明在 delivery §8 有对照纠正表；运行检查仍全部 **UNRUN**。

### 8.6 未运行与未关闭边界（强制，复验后仍成立）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| new controlled root / retained 真跑 / stage / commit | **未执行** |
| Windows 定向验证申请 | **阻断**（须先闭合 F8′ 至无 P0/P1/P2） |
| M3 Gate / `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` | **OPEN / 未关闭** |

### 8.7 复验结论（REWORK1）

**REWORK1_REVIEW_FAIL**（残留 **P2：F8′** — 交付冻结合同 §3.4 与 REWORK1 closure 真身实现不一致）。

首轮 F1–F4 与 §9 新增 F5–F7 的实现/测试静态证据可读为已闭合；在修正 delivery §3.4（及如需的模块属性断言）前，不得申请 Windows 定向验证，不得宣称工程 validated 或关闭 M3 Gate。

本复验会话结束；仅更新本报告。

---

## 9. STATIC_REWORK2 复验（对照任务书 §10 / F8′）

日期：2026-08-26<br>
身份：与首轮 / REWORK1 同一独立初验者；未参与实现<br>
范围：只读任务书 §10、更新后的 delivery §3.4 / §10、当前 production/tests（核对一致性）；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / worker / network / real I/O / stage / commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）<br>
授权边界：实现者 **仅** 改 delivery；本轮不重新打开已闭合的 F1–F7 代码面，但 **不** 将 REWORK1_FAIL 继承为通过——必须独立证实 F8′ 已消除。

### 9.1 F8′ 核对清单

| 检查项 | 静态结论 | 证据 |
| --- | --- | --- |
| 陈旧 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY` **不再作为有效门禁合同** | **通过** | delivery §3.4 开篇「**已废除（不得再作验收依据）**」明确废止别名模型与「`runtime... is _CANONICAL_*`」；现行条款不再要求存在或依赖这些符号 |
| 生产模块仍无上述符号 | **通过** | `successor_bridge.py` 全文件无 `_CANONICAL_FACTORY` / `_CANONICAL_ENTRY`；权威为 `_build_entrypoint_authority` → `_require_canonical_entrypoints`（95–127） |
| import-time closure authority 描述准确 | **通过** | §3.4 项 1–2：导入时捕获 `runtime.make_canonical_*` / `run_production_two_fold_successor` 及 `__code__`；调用前 `is` 真身 + `__code__ is` + 拒 `__wrapped__`——与源码 101–118、124–127 一致 |
| 双侧同一 impostor 拒绝 | **通过** | §3.4 项 2 写明仅替换一侧或双侧换成 impostor（即使彼此 `is`）均因≠闭包真身而 INPUT；指向 `test_rejects_wrapper_factory_or_entrypoint_unilateral`、`test_rejects_bilateral_same_impostor_on_factory_and_entry`（测试仍存在） |
| AST exact1 + 不拆真身 integration | **通过** | §3.4 项 5：AST `test_bridge_source_calls_factory_and_entry_exactly_once`；行为 `test_bridge_reaches_two_folds_without_replacing_canonical_identity`；明确禁止首轮双侧 spy 计数——与测试及 REWORK1 结论一致 |
| factory 槽位 `is` + `public_apis=None` | **通过** | §3.4 项 3–4 与 `_require_canonical_dependencies` / 入口 `public_apis=None` 一致 |
| delivery §10 记录 F8′ 闭合 | **通过** | 现象/根因/规则/复现/修改/通过条件/UNRUN 齐备；声明仅改 delivery |
| 未越权改 production/tests | **通过（只读观察）** | 本轮审查对照 REWORK1 已审源码/测试名；任务书 §10 授权 delivery-only；dirty 仍限于 exact9，未见本轮新增生产/测试路径要求 |

### 9.2 发现分级（REWORK2）

**无 P0 / P1 / P2。**

F8′（delivery §3.4 过期别名合同）已由 delivery-only 修订消除：废除段 + 现行 closure authority 与源码/测试映射一致。§8.3 所列 R9–R12 仍为**非阻断**对抗建议，不构成本轮合同失败。

### 9.3 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| new controlled root / retained 真跑 / stage / commit | **未执行** |
| Windows 定向：identity → unit exact2 → integration exact2 → Ruff exact6 → mypy production2 → cold production2 → exact9 scope | **可申请**（静态文档合同已无 P0/P1/P2；**不**等于已跑通） |
| M3 Gate / `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` | **OPEN / 未关闭** |

### 9.4 复验结论（REWORK2）

**REWORK2_REVIEW_PASS**

静态交付合同（含 F1–F7 实现面于 REWORK1 已闭合 + F8′ 文档于 REWORK2 闭合）无残留 P0/P1/P2。全部运行时验证与 M3 Gate 仍为 **UNRUN / OPEN**；本结论 **不** 表示 Windows engineering validated，也 **不** 关闭 M3。

本复验会话结束；仅更新本报告。

---

## 10. STATIC_REWORK3 复验（对照任务书 §11 / F9–F10）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读任务书 §11、delivery §12、`tests/unit/test_m3_successor_bridge.py`（F9/F10 相关）及只读对照 production `successor_bridge.py`；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / network / stage / commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）

### 10.1 范围与冻结

| 项 | 静态结论 |
| --- | --- |
| 授权写入 | unit `test_m3_successor_bridge.py` + delivery（§11） |
| production / 其余 tests / taskbook | **只读**；delivery 宣称 production 字节冻结；本轮未见授权外生产 diff 要求 |
| VALIDATION1 绑定 | delivery §12.1：identity PASS；unit `18/1/2`；其余 UNRUN；evidence root / summary SHA 诚实记为 `NOT_CITED_IN_TASKBOOK_§11`（不伪造） |

### 10.2 F9 / F10 逐项

| ID | 要求 | 静态结论 | 证据 |
| --- | --- | --- | --- |
| F9 | test-owned raw `NaN`/`Infinity`；不放宽 writer；bridge → `SUCCESSOR_BRIDGE_INPUT_INVALID`；factory/entry 0；controlled 零写；进入目标 guard | **失败** | 测已改 raw 替换（423–439），bool/int/0/−1 仍走 `_write_request`；**但**生产 `_load_canonical_request_object`（281–292）在 `json.loads` 接受非标准 token 后调用 **未捕获** 的 `_canonical_json_bytes(..., allow_nan=False)`（818–825）→ 静态可达裸 `ValueError`，**不是** `SuccessorBridgeError`；亦 **未**到达 `_parse_toolchain` 的 `math.isfinite` 目标 guard（480–487）。测断言 `SuccessorBridgeError` 与生产路径矛盾。delivery §12.2 已自承该残留，但未闭合 §11 通过条件。 |
| F10 | 不替换 canonical authority；仅 read/stat seam 同 size 置换；INPUT；entry 0；controlled 不变 | **通过** | `test_dump_toctou_same_size_content_swap_rejects_before_entry`：仅 fake `load_m3_config`/`verify_g1_release`；按 dump 路径首次读后 `dump→DUMP`；**不** patch `_require_canonical_entrypoints`/factory/entry；断言 `swapped`、authority/`_require_canonical_entrypoints` 对象不变、controlled 仅 preexisting marker、无 completion/receipts。生产顺序：dump TOCTOU 在 `_build_runtime_request`/`_parse_toolchain`（499–514）内，早于 `_require_canonical_entrypoints()`（184）与 runtime entry（188）。 |

### 10.3 发现分级

### [P1] F9 raw 非有限 token 无法稳定归一为 `SUCCESSOR_BRIDGE_INPUT_INVALID` — `successor_bridge.py:281-292` × `test_rejects_wrong_dump_target_and_timeout_types`

任务书 §11.F9 通过条件要求 bridge **稳定返回** `SUCCESSOR_BRIDGE_INPUT_INVALID`，且失败进入目标输入边界。静态路径：

1. request bytes 含 `"timeout_seconds":NaN`（或 `Infinity`）；
2. `json.loads`（CPython 默认）接受为 `float` 非有限；
3. `_canonical_json_bytes` → `json.dumps(..., allow_nan=False)` 抛 `ValueError`；
4. 该调用在 `_load_canonical_request_object` **无** `try`/`_fail_input` 包裹 → 冒泡裸 `ValueError`；
5. 测试 `pytest.raises(SuccessorBridgeError)` 静态上会对不齐；目标 `math.isfinite` 超时 guard **不可达**。

实现者已正确停止用 `_write_request(float("nan"))` 并改 raw carrier，且 delivery 诚实记录风险；但在 **禁止改 production** 的前提下仍声称 F9 通过条件满足，属于合同未闭合。零副作用（controlled 不存在、authority 未替换）在 ValueError 早退时可附带成立，**不能**替代稳定输入错误码。

### 无 P0；F10 未见 P1/P2

F10 测试面与生产调用序静态一致：canonical authority 保持、dump TOCTOU/mtime 双读 guard 可达、runtime entry 前 INPUT、controlled 零写断言完备。

### 10.4 实现者未使用的对抗反例（新增）

### 反例 R13 — raw `-Infinity` × 裸 `ValueError` 经 CLI 错族

实现者 raw 循环仅 `NaN` / `Infinity`。补：

1. 同法写入 `"timeout_seconds":-Infinity`；
2. 直接调 `run_production_successor_bridge` → 静态预期同 F9：裸 `ValueError`（非 `SuccessorBridgeError`）；
3. 再经 `run_successor.main(["--request", abs])`：CLI `except Exception` → **`SUCCESSOR_BRIDGE_RUNTIME_FAILED` / exit 3**（非输入族 exit 2）。

**合同预期（§6/§11）：** 非法 request 非有限数应稳定 **输入族**；不得因 loader 未捕获 dumps 失败而落入 runtime 族或未捕获异常。

**通过条件：** `_canonical_json_bytes` 失败（及等价非有限）一律 `_fail_input()`；unit 对 `NaN`/`Infinity`/`-Infinity` 断言 `SuccessorBridgeError`+INPUT；可选 CLI 断言 exit 2；其后才允许到达或不必到达 `math.isfinite`（二者择一冻结，但错误码必须稳定）。

### 10.5 失败项

### F9′ — raw 非有限 carrier 未闭合稳定 INPUT 码

| 字段 | 内容 |
| --- | --- |
| 现象 | raw `NaN`/`Infinity` 测断言 `SuccessorBridgeError`，生产 loader 对 `allow_nan=False` dumps 失败未捕获 |
| 根因 | `_load_canonical_request_object` 289 行 `_canonical_json_bytes(parsed)` 在 try 外；REWORK3 禁改 production 却未调整断言/通过条件与真实可达异常一致 |
| 规则 | 任务书 §11.F9；§6 输入错误稳定码；reviewer 须确认进入目标 bridge guard |
| 最小复现 | 静态：`json.loads('{"timeout_seconds":NaN,...}')` → dumps `allow_nan=False` → `ValueError`；对照 281–292 与测 431–433 |
| 新增测试 / 返工 | production 最小：捕获 dumps/`ValueError`→`_fail_input()`（须另开授权）；或在未改生产前不得宣称 F9 PASS。测保留 raw carrier，并钉 `-Infinity` |
| 通过条件 | 三 token 均 `SUCCESSOR_BRIDGE_INPUT_INVALID`；factory/entry 未调用；controlled 零写；无裸 `ValueError` |

### 10.6 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN**（本复验未跑；不继承 VALIDATION1 `18/1/2` 为通过） |
| actual worker / 真实 Qlib / network | **UNRUN** |
| VALIDATION2 | **阻断**（须先闭合 F9′） |
| M3 Gate / Windows engineering validated | **OPEN / 未关闭** |

### 10.7 复验结论（REWORK3）

**REWORK3_REVIEW_FAIL**（**P1：F9′** — raw 非有限 token 不能稳定归一为 `SUCCESSOR_BRIDGE_INPUT_INVALID`，目标 timeout 有限性 guard 不可达；F10 静态通过）。

不得申请 VALIDATION2，不得将 VALIDATION1 失败轮或本轮 test-only 修改表述为整包通过。闭合 F9′ 需授权触及 production 最小捕获（或等价合同修订），超出本轮 test-only 白名单。

本复验会话结束；仅更新本报告。

---

## 11. STATIC_REWORK4 复验（对照任务书 §12 / F9′）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读任务书 §12、delivery §14、`successor_bridge.py`、`tests/unit/test_m3_successor_bridge.py`、`tests/unit/test_m3_run_successor.py`；核对 F10 未重写；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / network / stage / commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）

### 11.1 F9′ 合同核对

| # | §12 要求 | 静态结论 | 证据 |
| --- | --- | --- | --- |
| 1 | re-encode `ValueError`/等价 → 立即 `_fail_input()`；不 broad-catch runtime | **通过** | `_load_canonical_request_object` 291–294：仅包裹 `_canonical_json_bytes(parsed)` 的 `except (TypeError, ValueError): _fail_input()`；非 `except Exception`；loads 既有 try 未扩围 |
| 2 | `allow_nan=False`、canonical bytes、其余门禁不变 | **通过** | `_canonical_json_bytes` 仍 `allow_nan=False`（823–830）；`canonical != raw` 仍在捕获之后（295–296）；未见字符串化非有限或 serializer SSOT 改写 |
| 3 | raw `NaN`/`Infinity`/`-Infinity` → `SUCCESSOR_BRIDGE_INPUT_INVALID`；factory/entry 0；controlled 零写 | **通过** | unit 425–439：三 token raw 替换；`SuccessorBridgeError` + `BRIDGE_INPUT_ERROR`；controlled 不存在；`runtime.make_*` / `run_production_*` 仍 `is` 导入真身（失败在 loader，早于 184 行 entrypoints/factory/entry） |
| 4 | CLI ≥1 raw 非有限 → stderr 仅输入码、exit 2、脱敏；不改 0/3 | **通过** | `test_raw_nonfinite_request_is_stable_input_exit_two`：Infinity → `EXIT_INPUT`、`BRIDGE_INPUT_ERROR\n`、无路径/`Infinity`/`ValueError`；`run_successor.py` 本轮未改（delivery 声明） |
| 5 | 不要求到达 `math.isfinite`；loader 边界拒绝为权威 | **通过** | 与 §12.5 及修复注释（289–290）一致；三 token 在 re-encode 即 INPUT |
| 6 | F10 不重写 | **通过** | `test_dump_toctou_same_size_content_swap_rejects_before_entry` 仍为 dump-path 首次读后置换、不 patch `_require_canonical_entrypoints`/factory/entry；delivery §14.1 冻结声明 |
| 7 | delivery 记录 F9′ 与 VALIDATION1/REWORK3_FAIL 历史 | **通过** | §14.1–14.2 保留 `18/1/2`、REWORK3_FAIL、F9′ 现象—根因—规则—复现—修复—测试—通过条件；UNRUN |

### 11.2 发现分级

**无 P0 / P1 / P2。**

REWORK3 的 F9′（裸 `ValueError` / CLI 错落入 runtime 族）已由窄捕获闭合；未放宽 `allow_nan`；未扩大异常分类；F10 与成功 0 / runtime 3 合同静态可读为未受损。

### 11.3 对抗反例（本轮新增，非阻断）

### 反例 R14 — CLI 对 `NaN` / `-Infinity` 对称 exit 2

实现者 CLI 仅钉 `Infinity`。补：`main(["--request", abs])` 对 raw `NaN` 与 `-Infinity` 同样断言 exit 2、仅输入码、无 token/路径泄露。生产 loader 路径对三 token 对称，静态预期应同 `Infinity`。

**通过条件（建议 VALIDATION2 顺带）：** 三 token CLI 参数化或等价；非本轮 FAIL 条件（§12.4 仅要求至少一个）。

### 11.4 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **UNRUN** |
| actual worker / 真实 Qlib / network | **UNRUN** |
| VALIDATION1 `18/1/2` | **历史保留，不继承为通过** |
| VALIDATION2（完整重跑） | **可申请**（静态无 P0/P1/P2；**不得**沿用失败轮） |
| M3 Gate / `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` | **OPEN / 未关闭** |

### 11.5 复验结论（REWORK4）

**REWORK4_REVIEW_PASS**

F9′ 中央批准的最小修复与定向测静态闭合；F10 及其他冻结合同未见回退。全部运行时验证与 M3 Gate 仍为 **UNRUN / OPEN**。本结论 **不** 表示 VALIDATION2 或 Windows engineering validated，也 **不** 关闭 M3。

本复验会话结束；仅更新本报告。

---

## 12. STATIC_REWORK5 复验（对照任务书 §13 / mypy 返回注解）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读任务书 §13、delivery §16、当前 `successor_bridge.py`（相对 REWORK4 逆向核对）；tests/taskbook 只读；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / Qlib / network / stage / commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）

### 12.1 逆向 diff 核对（相对 REWORK4 已审形态）

| 检查项 | 静态结论 | 证据 |
| --- | --- | --- |
| 新增 `Callable` 导入 | **通过** | `from collections.abc import Callable, Mapping, Sequence`（L20）；REWORK4 为 `Mapping, Sequence` only |
| 返回注解收窄 | **通过** | `_build_entrypoint_authority(...) -> Callable[[], None]`（L95–98）；不再为 `-> object` |
| 参数仍为 `object` | **通过** | `true_factory: object`, `true_entry: object`（L96–97） |
| 函数体 / 闭包 / 门禁不变 | **通过** | L101–120：仍捕获 `__code__`；内部 `_require_canonical_entrypoints` 仍做 `is` / `__code__` / `__wrapped__`；`return _require_canonical_entrypoints` |
| 模块赋值与调用序不变 | **通过** | L124–127 仍绑定 `_require_canonical_entrypoints = _build_entrypoint_authority(...)`；L184 仍在 `_build_runtime_request` 之后、factory/entry 之前调用 `_require_canonical_entrypoints()` |
| 错误码 / schema / identity / F9′ loader | **通过** | `BRIDGE_*`、schema id、F9′ re-encode `try/except (TypeError, ValueError): _fail_input()`、canonical `allow_nan=False` 未见本轮改动迹象 |
| 无 `Any` / 新 `cast` / `type: ignore` / Protocol 扩散 | **通过** | production 文件无 `Any`、`Protocol`、`type: ignore`；本轮未新增 `cast`（既有 `cast` 于 dict/Path 辅助路径，非本返工引入，亦未因本修复向外扩散） |
| tests 冻结 | **通过** | §13 禁止改 tests；delivery 声明 tests 字节冻结；本轮审查未要求/未见 test 合同变更 |
| delivery 记录 | **通过** | §16.1–16.2：VALIDATION2 `21/1` + integration 6 + Ruff PASS、mypy 首失败原文、修复与通过条件；evidence root/mypy SHA 诚实 `NOT_CITED…` |

### 12.2 发现分级

**无 P0 / P1 / P2。**

相对 REWORK4，production 静态可读变更面 **仅** 为：`Callable` 导入 + `_build_entrypoint_authority` 返回注解 `Callable[[], None]`。运行语义、authority 闭包与错误分类未变；mypy `"object" not callable` 的根因注解已按 §13 收窄。

### 12.3 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold（本复验） | **UNRUN** |
| VALIDATION2 unit/integration/Ruff | **历史已绿（§13/§16.1）；不在本轮复跑，不洗白 mypy** |
| mypy production2 / cold / exact9 scope | **待窄 postfix**（identity → Ruff `successor_bridge.py` → mypy production2 → cold → exact9）；**不得**重复已绿 unit/integration |
| M3 Gate / Windows engineering validated | **OPEN / 未关闭** |

### 12.4 复验结论（REWORK5）

**REWORK5_REVIEW_PASS**

类型收窄合同静态闭合，无残留 P0/P1/P2。本结论 **不** 表示 mypy/cold postfix 或 M3 Gate 已通过；全部本轮命令 **UNRUN**。

本复验会话结束；仅更新本报告。

---

## 13. EVIDENCE_REVIEW（组合 Windows 工程证据）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读任务书 §14、delivery §18、本报告历史 §0–§12；只读核对 worktree 下 `artifacts/agent_runs/m3-r2b-rebuilt-{validation1,validation2,postfix-validation3}-*`；**仅改本报告**<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold；未 stage / commit；未改 production / tests / taskbook / delivery<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`（仍等于 exact base）

### 13.1 组合证据表（文档 ↔ 磁盘）

| 轮次 | 文档声明 | 磁盘核对 | 结论 |
| --- | --- | --- | --- |
| VALIDATION1 | identity PASS；unit `18/1/2`；其后 UNRUN；**不洗白** | root 存在：`…/m3-r2b-rebuilt-validation1-20260826T193000Z`；`summary.txt`：`STOP=STAGE_FAILED:unit`；unit 尾：`2 failed, 18 passed, 1 skipped`；无 integration/Ruff/mypy/cold/scope 产物 | **通过**（失败与 UNRUN 未洗白） |
| REWORK3–4 / 复验 | `REWORK3_REVIEW_FAIL` P1 F9′；`REWORK4_REVIEW_PASS`；F10 冻结 | 本报告 §10–§11 原文保留；delivery §12–§14 / 任务书 §11–§12 保留 | **通过** |
| VALIDATION2 | root `…/validation2-20260826T201000Z`；summary `90CE…5E8B`；mypy stdout `9E3C…C40A`；unit `21/1`；integration 6；Ruff PASS；mypy **首失败** `:184 object not callable`；cold/scope **UNRUN** | root 存在；`Get-FileHash SHA256(summary.txt)=90CE3B52EA88278F32A3F4A59ED2B871C496672C3C317AEEE8F295B339FF5E8B`；`mypy.stdout.txt` hash=`9E3C7ACCDE7EC9DCE0EBA991FD07676A30D4BA9779C294B30663F56B345BC40A`；内容含 `successor_bridge.py:184: error: "object" not callable`；`mypy.exit=1`；unit/integration/ruff exit=0；unit 尾 `21 passed, 1 skipped`；无 cold/scope 文件；`STOP=STAGE_FAILED:mypy`；`RESOURCE_RELEASE=0xF00` | **通过** |
| REWORK5 | 仅 `Callable` import + `-> Callable[[], None]`；`REWORK5_REVIEW_PASS` | 源码 L20/L98 可见；本报告 §12 逆向核对仅注解收窄；无运行语义回退 | **通过** |
| POSTFIX VALIDATION3 | root `…/postfix-validation3-20260826T202000Z`；summary `7F9A…C65E`；identity/Ruff 单文件/mypy/cold/scope/cached0/diff/temp/process **PASS**；`0xF00` | root 存在；`SHA256(summary.txt)=7F9A7DA9FA3DD4E5B2E136193E4DDBDF96AC8C5F92A4B2A286A7EC571DB8C65E`；各 stage exit=0；`PASS=ALL_STAGES`；`RESOURCE_RELEASE=0xF00`；scope：`ACTUAL_COUNT=9`、`CACHED_COUNT=0`、`DIFF_CHECK=PASS`、`CACHE_RESIDUE=0`、`EXACT_F00_FOREIGN=0`；mypy stdout `Success: no issues found in 2 source files` | **通过** |

### 13.2 强制口径核对

| 项 | 静态结论 |
| --- | --- |
| 组合 = V2 已绿（unit+integration+Ruff）∪ V3（identity+单文件 Ruff+mypy+cold+scope） | **通过**；任务书 §14 / delivery §18 明示；**未**声称 VALIDATION2 或 VALIDATION3 单轮覆盖全部门 |
| VALIDATION1 `18/1/2` 与 V2 mypy STOP 未改写为全绿 | **通过** |
| REWORK1–5 与 P0/P1/P2 历史可追溯 | **通过**（本报告 §2–§12 + delivery 对应节） |
| 状态上限 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED` | **文档与组合证据一致** |
| actual worker / 真实 Qlib / network / new root / retained / Linux / M3 Gate | **仍 OPEN**（任务书 §14 / delivery §18 明示；本复核不关闭） |

### 13.3 记录 SHA（本复核实测）

| 产物 | SHA-256 |
| --- | --- |
| VALIDATION2 `summary.txt` | `90CE3B52EA88278F32A3F4A59ED2B871C496672C3C317AEEE8F295B339FF5E8B` |
| VALIDATION2 `mypy.stdout.txt` | `9E3C7ACCDE7EC9DCE0EBA991FD07676A30D4BA9779C294B30663F56B345BC40A` |
| VALIDATION3 `summary.txt` | `7F9A7DA9FA3DD4E5B2E136193E4DDBDF96AC8C5F92A4B2A286A7EC571DB8C65E` |

### 13.4 发现分级

**无 P0 / P1 / P2。**

组合证据链完整、SHA 与磁盘一致、失败/UNRUN 历史未洗白、exact9/`cached0`/diff/`0xF00` 与 POSTFIX 摘要一致。

### 13.5 结论

**EVIDENCE_REVIEW_PASS**

支持组合口径退出上限 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`。本结论 **不** 关闭 actual worker / 真实 Qlib / network / new controlled root / retained / Linux Gate / 真实 M3 Gate，也 **不** 将 VALIDATION1/2 失败轮改写为单轮全绿。

本证据复核会话结束；仅更新本报告。

---

## 14. DOC_REVIEW（文档规范化只读核对）

日期：2026-08-26<br>
身份：与首轮同一独立初验者；未参与实现<br>
范围：只读 exact9 实现/测试与 task/delivery；**唯一可写**本报告（本轮仅规范化换行/EOF 并追加本节）<br>
STATIC_ONLY：零 Python；未改 production/tests/task/delivery；未 stage/commit<br>
HEAD：`9cc5b56d176a18aa468386b369d550be73051edb`

### 14.1 格式门禁

| 文档 | trailing WS | CR | 单一 EOF LF |
| --- | --- | --- | --- |
| 任务书 | 0 | 0 | **通过** |
| 交付报告 | 0 | 0 | **通过** |
| 本审查报告（规范化后） | 0 | 0 | **通过** |

### 14.2 证据语义相对 `EVIDENCE_REVIEW_PASS`

| 项 | 结论 |
| --- | --- |
| VALIDATION1 `18/1/2` + 后续 UNRUN 未洗白 | **无漂移** |
| VALIDATION2 summary `90CE3B52…5E8B` / mypy stdout `9E3C7ACC…C40A` + mypy STOP 保留 | **无漂移** |
| VALIDATION3 summary `7F9A7DA9…C65E` + exact9/cached0/0xF00 | **无漂移** |
| 组合口径 V2 tests/Ruff ∪ V3 identity/Ruff/mypy/cold/scope；不伪造单轮全绿 | **无漂移** |
| 上限 `R2B_BRIDGE_CLI_WINDOWS_ENGINEERING_VALIDATED`；worker/Qlib/network/new root/retained/Linux/M3 Gate **OPEN** | **无漂移** |
| REWORK5 仅 Callable 返回注解收窄 | **无漂移** |
| exact9 九路径仍在 | **通过** |

### 14.3 发现

**无 P0 / P1 / P2。** 初检时本报告为 CRLF（`CR_count>0`）；已在本文件内规范化为 LF + 单一 EOF，**未**改证据正文语义。

### 14.4 结论

**DOC_REVIEW_PASS**
