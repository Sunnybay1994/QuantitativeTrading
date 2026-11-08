无新的 P0 / P1 / P2。integration 已按 §13 建立互斥精确覆盖：CONTROL=`{schema_version,mode}`、TIME_BOUND exact6、DURABLE exact10，并集恰为 18 键。四次 fresh（CLI initialize / public reopen / CLI reopen / public reopen）中每个 TIME_BOUND 字段为 canonical lowercase 64-hex 且四值互异；每个 DURABLE（含 `runtime_layout_identity`）四次逐字相等。真实 public 链、canonical JSON、脱敏、unit 同次 capability 全字段责任、production/unit 冻结与 VALIDATION3 诚实证据均闭合。未删字段、未暴露 `verified_at`、未改 production identity 算法。须另起完整 **VALIDATION4**，不得继承 VALIDATION3 部分绿。

### 13.1 互斥分区核对

| 集合 | 期望键 | 现场 | 结论 |
| --- | --- | --- | --- |
| CONTROL | `schema_version`, `mode` | `_CONTROL_KEYS` L90 | **满足** |
| TIME_BOUND exact6 | `bootstrap_identity`, `runtime_environment_identity`, `execution_policy_identity`, `broker_binding_identity`, `account_verification_identity`, `broker_capability_identity` | `_TIME_BOUND_KEYS` L66–75 | **满足** |
| DURABLE exact10 | `session_date`, `config_identity`, `config_raw_sha256`, `source_file_identity`, `runtime_layout_identity`, `gateway_identity`, `execution_store_identity`, `barrier_epoch`, `barrier_capability_identity`, `barrier_lock_identity` | `_DURABLE_KEYS` L76–89 | **满足** |
| 两两互斥 ∪ = 18 | `6+10+2=18` | 模块级 assert L93–98 + `_assert_result_key_partition` L290–296 | **满足** |
| `runtime_layout_identity` ∈ DURABLE（非 TIME_BOUND） | §13 明确 | 仅在 `_DURABLE_KEYS` | **满足** |

production `_RESULT_KEYS`（18 元组，含 `schema_version`/`mode` 与上述 16 identity 键）与 integration `_RESULT_KEYS` 集合一致；投影仍经 `_project_identity`，未见删键。

### 13.2 四次 fresh 样本与字段语义

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 四样本 = 两 CLI payload + 两 public capability | **满足** | CLI init → public reopen → CLI reopen → public reopen（L324–400）；`fresh_time_bound` 四元组（L402–407） |
| TIME_BOUND：canonical lowercase 64-hex | **满足** | `_assert_canonical_hex64`（L218–225）；payload/capability 抽取均经此闸（L228–261） |
| TIME_BOUND：同字段四值互异 | **满足** | 每键 `len(set(values))==4`（L408–411） |
| DURABLE：四次逐字相等（含 `runtime_layout_identity`） | **满足** | `durable_public_after_init == durable_cli_init`；`durable_cli_reopen == durable_cli_init`；`durable_public_after_reopen == durable_cli_init`；并显式钉 `runtime_layout_identity`/`barrier_epoch`/`execution_store_identity`（L362, L382–390, L400） |
| CONTROL：`schema_version`/`mode` 按调用语义 | **满足** | `_assert_operator_envelope`：initialize/reopen 分别断言（L281–284, L340, L379） |
| 真实 public 链 | **满足** | `reopen_verified_…` + `verify_existing_…` 且 `verified is capability`（L353–359, L395–397） |
| canonical JSON + 脱敏 | **满足** | stdout bytes == `canonical_json_bytes`；禁 `verified_at`/`account_id`/`config_path`/绝对路径（L339, L344–347, L378, L391–392） |
| 同次 capability 全字段（unit 责任） | **满足（冻结）** | unit 成功投影仍钉同 capability 字段（含 `bootstrap_identity`）；unit SHA 未变 |
| 无删字段 / 无 `verified_at` 暴露 / 无 production 算法改动 | **满足** | production SHA == §11.2/§12.2；CLI 投影无 `verified_at` |

### 13.3 冻结范围与 delivery 诚实性

| 路径 | 本轮 SHA256 | 相对 §12.2 / §11.2 | 结论 |
| --- | --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `A36A53F236907B15F19B0C9BEA19734810E7D3B785EF060E3626756BDB5DD0E8` | **相同** | production 冻结 |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `C565ECBEA01458B095391AFAC78C71FFC193D5BD83E97B3DD1CC66F38D210C3D` | **相同** | unit 冻结 |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `E95F12AECB3229A995CF1859B4B4416C076E221114F8EDFFE919D9205F33D626` | 变更 | 仅允许的 §13 分组修正 |
| 交付（含 §11） | `7F58F846AFEACFECCCB6BC192EB66E34FC3BA0FAA702F3A9347B1BF0D721ACBF` | 变更 | 实现者 delivery |
| 任务书（含 §13） | `959ADCDB75816A886DBD5DBDB047B8120203ACC2914B83488488F2671313E091` | 变更 | 经理授权节；实现者未改 |

delivery §11 写「任务书只读未改」按实现者写集解读；经理 §13 为授权增量。production/unit 冻结证据为 SHA 逐字相等。

### 13.4 VALIDATION3 历史边界（强制保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`5 passed / 1 failed`**（§12 过窄 durable 闭包；首失败 STOP） |
| Ruff / mypy / cold / scope | **UNRUN** |
| 证据根 | `artifacts/agent_runs/m4-ua006-r2-validation3-20260827T035206Z/` |
| integration stdout SHA256 | `6AB242600679E219AB14EF1C744C9EC98215090510F8FF293F5497D0B913A8E8` |
| summary SHA256 | `C556FBA20EB813232312BD43232D6C97F6CB2DB147C572CF7B3AEC209CBB7FCA` |

本失败定性为 **integration 合同分组错误**（§12 不完整），不构成 production 回归，也**不**构成 VALIDATION3 整包 PASS。§12/REWORK3 失败史保留；§13 为规则取代而非洗白。

### 13.5 未运行 / 不超宣称

| 项 | 状态 |
| --- | --- |
| 本审查 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network | **未运行** |
| stage / commit | **未执行** |
| VALIDATION4 / Windows engineering validated | **未跑；不得宣称；不得继承 VALIDATION3 部分绿** |
| UA-M4-006 / PAPER / soak / Linux Gate | **仍 OPEN** |

### 13.6 收口

**`REWORK4_REVIEW_PASS`**

§0–§12 历史保留。TIME_BOUND/DURABLE 精确分区静态闭合后，下一步须按任务书 §13 / delivery §11.4 **从 identity 起完整重跑 VALIDATION4**；禁止沿用 VALIDATION3 的 unit 59 绿或 integration 5 绿冒充整包。

---

## 14. REWORK5_REVIEW（VALIDATION4 callable 类型收敛；相对 §13 `REWORK4_REVIEW_PASS`）

日期：2026-08-27<br>
复验角色：同一独立外部初验 Agent（仍只写本报告；未改 CLI/tests/task/delivery）<br>
授权：任务书 §14 / delivery §12<br>
上文 §0–§13 历史**原文保留**；不洗白 VALIDATION4 mypy STOP。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。

### 14.0 裁决

**`REWORK5_REVIEW_PASS`**

无新的 P0 / P1 / P2。runtime 源码相对 REWORK4 **仅**增加窄 alias `_BootstrapCallable = Callable[..., VerifiedFormalPaperRuntimeBootstrap]`，并用于三个 `true_*` 参数、outer 返回 `Callable[[], tuple[...]]` 与 inner 返回三元组；未见 `cast` / `Any` / `type: ignore` / `Protocol` / wrapper / runtime 重绑定。函数体、`is`/`__code__`/`partial`/`__wrapped__`、调用序、错误码、projection/schema 静态未变。unit/integration SHA 相对 §13.3 **冻结**。VALIDATION4 证据诚实：identity/unit59/integration6/Ruff PASS，mypy 1 error STOP，cold/scope UNRUN。

**行为等价判定：是。** 类型-only 注解收敛，执行路径不变 → **允许复用 VALIDATION4 已绿的 unit59 / integration6 / Ruff-tests**，按任务书 §14 跑窄 POSTFIX **VALIDATION5**：identity → Ruff 仅 CLI → mypy CLI → cold CLI → exact6 Unicode scope/cached0/diff/temp/cache/process。不得宣称 VALIDATION4/5 整包或 Windows engineering validated。

### 14.1 变更面核对

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 单一窄 alias | **满足** | CLI L63：`_BootstrapCallable = Callable[..., VerifiedFormalPaperRuntimeBootstrap]`（§14 允许等价命名） |
| 用于三个 `true_*` 参数 | **满足** | L81–83：`true_bootstrap` / `true_reopen` / `true_verify: _BootstrapCallable` |
| 用于 outer 返回三元组 | **满足** | L84：`-> Callable[[], tuple[_BootstrapCallable, _BootstrapCallable, _BootstrapCallable]]` |
| 用于 inner 返回三元组 | **满足** | L91–93：`_require_owned_api() -> tuple[_BootstrapCallable, ...]` |
| 无 `cast` / `Any` / `type: ignore` / `Protocol` | **满足** | 全文件无匹配；`typing` 仅 `Literal, NoReturn` |
| 无 wrapper / runtime 重赋值绕过门禁 | **满足** | 仍为 import-time closure 捕获真身（L119–124）；无额外赋值改写 owned API |
| `is` / `__code__` / `partial` / `__wrapped__` 保留 | **满足** | L97–113 逻辑仍在 |
| 调用序 / 错误 / projection / schema 未改 | **满足（静态）** | `_RESULT_KEYS` / `_project_identity` / exit 表 / SystemExit·stable-code 闸仍在；相对行为面无新分支 |
| unit/integration 冻结 | **满足** | SHA == §13.3（见 §14.2） |

### 14.2 冻结 SHA 与写集

| 路径 | 本轮 SHA256 | 相对 §13.3 | 结论 |
| --- | --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `70031E0642B73BFD335D74F7707B9A1B4C31CCF51921BB6BD4733F2245A3C733` | 变更 | 仅允许的 annotation/alias |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `C565ECBEA01458B095391AFAC78C71FFC193D5BD83E97B3DD1CC66F38D210C3D` | **相同** | unit 冻结 |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `E95F12AECB3229A995CF1859B4B4416C076E221114F8EDFFE919D9205F33D626` | **相同** | integration 冻结 |
| 交付（含 §12） | `92AAC6600B8290C3252EAE8FBCCA7FC4ADC98BFF619639EC6CE3FBEDF25FD073` | 变更 | 实现者 delivery |
| 任务书（含 §14） | `DC8E3620E14BABF03C65AEDC3E9E2D9F63F008B398F0C0F33B1919F2F5CF2B2F` | 变更 | 经理授权节 |

实现者写集 = CLI annotations + delivery；unit/integration 只读冻结。

### 14.3 VALIDATION4 诚实边界（强制保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`6 passed`** |
| Ruff | **PASS** |
| mypy | **1 error @ ~L122**（`tuple[object,object,object]` 返回；首失败 STOP） |
| cold / scope | **UNRUN** |
| 证据根 | `artifacts/agent_runs/m4-ua006-r2-validation4-20260827T040605Z/` |
| mypy stdout SHA256 | `AEE3A11B1C69E1FC45B9524717B1E7F4D257E56F4A71BEAC44B8667B31CF5307` |
| summary SHA256 | `239DB23C8787667591DC48CA7B9C81A65006EF3F2EE282E5D4EF65ED3E6B2E05` |

本失败定性为 **type-only 注解过宽**，不构成 runtime 行为回归，也**不**构成 VALIDATION4 整包 PASS。

### 14.4 POSTFIX VALIDATION5 复用裁定

| 项 | 裁定 |
| --- | --- |
| 是否行为等价 | **是** — 仅类型 alias/annotations；门禁与调用语义不变 |
| 可复用 V4 节点 | **unit 59**、**integration 6**、**Ruff tests**（任务书 §14 明示，除非后续发现行为差） |
| 必须重跑（窄 POSTFIX V5） | identity → Ruff 仅 CLI → mypy CLI → cold CLI → exact6 Unicode scope / cached0 / diff / temp / cache / process |
| 禁止 | 把 V4 部分绿或本静态 PASS 写成 Windows engineering validated / Gate 关闭 |

### 14.5 未运行 / 不超宣称

| 项 | 状态 |
| --- | --- |
| 本审查 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network | **未运行** |
| stage / commit | **未执行** |
| VALIDATION5 / Windows engineering validated | **未跑；可申请窄 POSTFIX；不得预先宣称 PASS** |
| UA-M4-006 / PAPER / soak / Linux Gate | **仍 OPEN** |

### 14.6 收口

**`REWORK5_REVIEW_PASS`**

§0–§13 历史保留。callable 类型收敛静态闭合且行为等价。下一步按 §14 / delivery §12.3 申请 **POSTFIX VALIDATION5**（复用 V4 unit59/integration6/Ruff-tests；重跑 identity/Ruff-CLI/mypy/cold/scope）；不得沿用 VALIDATION4 mypy STOP 结果或宣称整包绿。

---

## 15. EVIDENCE_REVIEW（任务书 §15 / delivery §13；FINAL）

日期：2026-08-27<br>
复验角色：同一独立外部初验 Agent（FINAL EVIDENCE_REVIEW；只写本报告；未改 production / tests / task / delivery；未 stage / commit）<br>
授权：任务书 §15；delivery §13；上文 §14 `REWORK5_REVIEW_PASS`<br>
§0–§14 **原文保留**，不洗白历史首失败 / UNRUN。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / 真实 I/O。

### 15.0 裁决

**`EVIDENCE_REVIEW_PASS`**

磁盘证据与任务书 §15 / delivery §13 组合口径一致：V4 已绿段（identity / unit59 / integration6 / Ruff-tests）⊕ REWORK5 类型-only ⊕ POSTFIX V5（identity / Ruff-CLI / mypy-CLI / cold / exact6 scope·cached0·diff·residue）构成 Windows 工程闭包。状态上限**仅** `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`。真实 bootstrap / PAPER / soak / submit / network / Linux Gate / UA-M4-006 **仍 OPEN**。

### 15.1 POSTFIX VALIDATION5 证据根与 summary SHA

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 证据根存在且路径逐字 | **满足** | `artifacts/agent_runs/m4-ua006-r2-postfix-validation5-20260827T041948Z/`（含 `summary.txt`、01–05 stage 产物、`paths.txt`） |
| `summary.txt` SHA256 | **满足** | 磁盘 `8054701A99588936DD8646057CF994E2D33627E55D6AD4235BD472DDCC2EAEDB` == 任务书 §15 / delivery §13 声称 |
| summary 状态 / 边界 | **满足** | `STATUS=PASS`；`BOUNDARY=M4_UA006_R2_POSTFIX_VALIDATION5_WINDOWS_ENGINEERING_ONLY`；`REUSED_V4=unit59,integration6,ruff-tests-pass` |
| 五阶段 exit | **满足** | `01-identity` / `02-ruff-cli` / `03-mypy-cli` / `04-cold-cli` / `05-scope` 的 `*.exit.txt` 均为 `0`；summary 对应 `*.sha256` 与磁盘产物逐字匹配 |
| mypy CLI 文本 | **满足** | `03-mypy-cli.stdout.txt` 全文：`Success: no issues found in 1 source file` |

### 15.2 exact6 / cached0 / diff-check / residue

| 检查 | 结论 | 证据（`05-scope.stdout.txt`） |
| --- | --- | --- |
| actual exact6 | **满足** | `ACTUAL_COUNT=6`；六路径恰为 task / delivery / review / CLI / unit / integration（Unicode 文件名完整） |
| cached0 | **满足** | `CACHED_COUNT=0` |
| `git diff --check` | **满足** | `DIFFCHECK_EXIT=0` |
| temp / cache / pycache / run-root | **满足** | `.tmp` / `.pytest_cache` / `.ruff_cache` / `.mypy_cache` `ABSENT`；`PYCACHE_COUNT=0`；`RUN_ROOT_ABSENT=1` |
| 0xF00 / writer | **满足** | `F00_COUNT=0`；`WRITER_PID=7692`；`WRITER_AFFINITY=3`（≡ `0x3`） |
| scope 收口 | **满足** | `SCOPE_PASS` |

### 15.3 冻结字节（相对 §14.2 REWORK5）

| 路径 | 本轮磁盘 SHA256 | 相对 §14.2 | 结论 |
| --- | --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `70031E0642B73BFD335D74F7707B9A1B4C31CCF51921BB6BD4733F2245A3C733` | **相同** | production 冻结（REWORK5 类型-only 后未再改） |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `C565ECBEA01458B095391AFAC78C71FFC193D5BD83E97B3DD1CC66F38D210C3D` | **相同** | unit 冻结（V4 复用） |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `E95F12AECB3229A995CF1859B4B4416C076E221114F8EDFFE919D9205F33D626` | **相同** | integration 冻结（V4 复用） |

REWORK5 仍为类型-only：§14 已确认 alias/annotations；本轮未重跑生产语义测试，与 V5 `REUSED_V4=unit59,integration6,ruff-tests-pass` 一致。

### 15.4 V1–V4 首失败 / UNRUN 诚实性（只读核对磁盘）

| 轮次 | 磁盘摘要 | delivery §13.1 / 历史节 | 结论 |
| --- | --- | --- | --- |
| V1 | `.../m4-ua006-r2-validation1-20260826T2203/`：`stage-summary` identity exit0 / unit exit1；unit stdout `1 failed, 58 passed`（symlink fixture；构造含 `~stat.S_IFMT`） | 首失败 + integration/Ruff/mypy/cold/scope **UNRUN** → REWORK2 | **诚实保留** |
| V2 | `.../validation2-20260827T033820Z/summary.txt`：`UNIT=59 passed`；`INTEGRATION=5 passed / 1 failed`；Ruff/mypy/cold/scope **UNRUN**；`FAIL_REASON` 跨调用误比 `bootstrap_identity` | → REWORK3 | **诚实保留** |
| V3 | `.../validation3-20260827T035206Z/summary.txt`：unit59；integration `5/1`；后续 **UNRUN**；`FAIL_REASON` 涉 `runtime_environment_identity`（§12 不完整 durable） | → REWORK4（§13 取代 §12） | **诚实保留** |
| V4 | `.../validation4-20260827T040605Z/summary.txt`：`STATUS=PRODUCT_STOP`；unit59；integration6；RUFF=PASS；MYPY=FAIL 1 error；COLD/SCOPE=**UNRUN** | → REWORK5 | **诚实保留** |
| V5 | 见 §15.1–§15.2 全 PASS（窄 POSTFIX；不宣称单轮从零全绿） | delivery §13.2 组合口径 | **一致** |

未发现把任一历史首失败改写为「单轮全绿」的表述。

### 15.5 组合闭包与状态上限（不超宣称）

| 项 | 结论 |
| --- | --- |
| Windows 工程组合 | **闭合** — V4 identity/unit59/integration6/Ruff-tests ⊕ REWORK5 类型-only ⊕ V5 identity/Ruff-CLI/mypy-CLI/cold/exact6-scope |
| 本包状态上限 | **仅** `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED` |
| 真实 formal bootstrap / fresh-root / new-epoch | **OPEN（未执行）** |
| PAPER / soak / submit / scheduler / order / gateway | **OPEN（未执行）** |
| network / Linux Gate | **OPEN（未执行）** |
| **UA-M4-006** | **OPEN** |
| 本审查运行检查 | **全部未运行**（STATIC_ONLY） |
| stage / commit | **未执行** |

delivery §13 与任务书 §15 的上限/OPEN 边界与磁盘证据一致；未见更高 Gate 或真实运行宣称。

### 15.6 收口

**`EVIDENCE_REVIEW_PASS`**

§0–§14 历史保留。可申请 **SAFE_COMMIT**（ignored evidence 根必须保留且不得 stage）。不得据此启动真实 bootstrap / PAPER / soak / network，或宣称 Linux Gate / UA-M4-006 关闭。
