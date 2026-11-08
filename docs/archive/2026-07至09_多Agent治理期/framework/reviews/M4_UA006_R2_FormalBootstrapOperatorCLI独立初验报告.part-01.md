# M4-UA006-R2 Formal Bootstrap Operator CLI 独立初验报告

日期：2026-08-26（§15 EVIDENCE_REVIEW：2026-08-27）<br>
状态：`EVIDENCE_REVIEW_PASS`；本包状态上限仅 `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`（§15；§0–§14 历史保留；STATIC_ONLY；组合证据非单轮全绿；真实 bootstrap / PAPER / soak / submit / network / Linux Gate / UA-M4-006 **仍 OPEN**）<br>
task id：`M4-UA006-R2-FORMAL-BOOTSTRAP-OPERATOR-CLI`<br>
exact base / HEAD：`27d42840c08d883d08c9578b3c2802b4630bd0f8`（一致）<br>
branch：`codex/m4-ua006-r2-formal-bootstrap-operator-cli`<br>
worktree：`artifacts/dev_worktrees/m4-ua006-r2-formal-bootstrap-operator-cli`<br>
审查角色：同一未参与实现的独立静态初验 Agent 续任 FINAL EVIDENCE_REVIEW（无委派 / 无 subagent）<br>
唯一写路径：本报告（exact6 #6）

任务书：`docs/framework/tasks/M4_UA006_R2_FormalBootstrapOperatorCLI任务书.md`<br>
交付：`docs/framework/deliveries/M4_UA006_R2_FormalBootstrapOperatorCLI交付报告.md`

---

## 0. 审查边界

- 已读：`AGENTS.md`、任务书、交付报告；只读 production `src/quant/execution/run_paper_formal_bootstrap.py`、unit/integration 两测；为 callable/路径合同对照只读 `paper_formal_bootstrap` public 表面与 `canonical_json_bytes`。
- **只写本报告**；未改 production / tests / task / delivery；未 stage / commit。
- **STATIC_ONLY**：未运行业务 Python、pytest、Ruff、mypy、cold import、真实 config/root/epoch、PAPER、soak、submit、network。
- dirty（只读）：exact6 内 `??` 为 task / delivery / CLI / unit / integration；写入前无本 review；HEAD == exact base。

---

## 1. 裁决

**`REVIEW_FAIL`**

诚实主路径（参数形状、单次 UTC now、initialize/reopen 分轨、owned callable `is`/`__code__`/`partial`/`__wrapped__` 门禁、leaf Path 具体类/绝对/regular/symlink·reparse、fresh `is` 闭合、18 键脱敏投影、`FormalPaperBootstrapError`→exit 3、未知 `Exception`→`RUNTIME_FAILED`、无 cleanup/retry/submit/soak、delivery 未超宣称 Windows/Gate）静态可读为大体对齐。

但任务书 §4.4 要求失败 stderr **exact 一行**稳定码、禁止路径/usage/repr 泄漏，且「未预期异常」归一 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED`。现码在 **业务段 `SystemExit` 逃逸** 与 **`error.code` 控制字符消毒不完整** 上可绕过该红acted 边界。存在 **P1×2**（加 **P2×1**）。**不得**申请 Windows fixture 验证。

无 P0（未见诚实 public API 正向必然错码/必然路径泄漏的静态证据）。

---

## 2. 合同核对矩阵（静态）

| # | 合同点 | 结论 | 证据摘要 |
| ---: | --- | --- | --- |
| 1 | 仅 `--config` / `--session-date` / 恰一 mode；无 env/cwd/default/`--now`/root/PAPER | **满足** | `_build_parser` L220–250；无其它 add_argument；unit argv 形状 |
| 2 | 业务路径一次 `datetime.now(timezone.utc)`；aware UTC | **满足** | `_canonical_utc_now` L214–217；`main` 单次取 now 后 initialize/reopen→verify 共用 L276–293 |
| 3 | initialize / reopen 分轨；后接 fresh verify；`verified is capability` | **满足** | L281–295；unit call-order + equal-but-not-identical |
| 4 | package-owned callable 真身；拒 wrapper/partial/双侧 impostor | **满足** | `_build_callable_authority` L76–129；unit impostor 组 |
| 5 | config：exact concrete absolute regular `Path`；拒 subclass/PurePath/symlink·reparse/missing/dir；不读内容 | **满足（leaf）** | `_require_exact_config_path` L139–157；unit path 组。mid-path link 未扫（残余，非本轮 FAIL 主因） |
| 6 | session-date canonical `YYYY-MM-DD` round-trip | **满足** | `_require_session_date` L160–169；unit 非 canonical 组 |
| 7 | 成功一行 canonical JSON；schema/18 键；无 path/account/time/token | **满足** | `_project_identity` + `canonical_json_bytes`；unit projection 禁词 |
| 8 | 错误码 exit 0/2/3；失败 stdout 0B；public stable code / 未知异常脱敏 | **部分失败** | parse 段 QuietParser+SystemExit 处理可读；**业务段 SystemExit 未捕获（P1-1）**；`error.code` 仅拒空/`\n`（P1-2） |
| 9 | 零 cleanup/retry/submit/soak；reopen 零 initializer | **满足** | 无 shutil/rmtree；unit delete/retry + reopen seam；integration AST 禁私有 helper |
| 10 | §6 反例映射 / delivery 诚实 UNRUN | **部分满足** | delivery §2–3 与测名大体对齐且未宣称 Windows/Gate；**缺** AE-1/AE-2 对抗测（P1）；`\n` 消毒无回归（P2） |
| 11 | 不复制 bootstrap/policy/P2；不改白名单外模块 | **满足** | CLI 仅编排 public 三函数；dirty ⊆ exact6 |

---

## 3. 发现分级

### [P1] P1-1 — 业务路径 `SystemExit` 绕过红acted exit 归一 — `run_paper_formal_bootstrap.py:262-267` vs `:269-314`

| 字段 | 内容 |
| --- | --- |
| 现象 | `SystemExit` **仅**在 `parse_args` 外层捕获（help→0；其它→INPUT/2）。业务 `try`（L269+）只 `except Exception`，**不**捕获 `SystemExit`/`BaseException`。`__main__` 为 `raise SystemExit(main())`，故业务段若升起 `SystemExit`（含 `code` 为路径型 `str`），将直接穿透 `main`，**不**写 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED`，exit/语义也不再是冻结的 2/3 表。 |
| 根因 | 解析期与业务期 SystemExit 策略不对称；任务书「未预期异常→RUNTIME_FAILED」在实现上收窄为 `Exception`。 |
| 应遵循 | 任务书 §4.4；审查指令 challenge（argparse/SystemExit 泄漏）。 |
| 实现者覆盖 | unit 有 help/`_QuietParser` 输入失败；`test_public_and_unknown_errors_*` 仅 `FormalPaperBootstrapError`/`RuntimeError`/`ValueError`/`OSError`——**无**业务段 `SystemExit`。 |
| 分级 | **P1** |

### [P1] P1-2 — `FormalPaperBootstrapError.code` 控制字符消毒不完整 — `run_paper_formal_bootstrap.py:302-308`

| 字段 | 内容 |
| --- | --- |
| 现象 | 现码对 `error.code` 仅拒绝非 `str`、空串、含 `\n`。含 `\r` / 其它 C0 控制字符 / 嵌入绝对路径片段的 hostile code（无 `\n`）会原样 `_emit_code(code)`，破坏「stderr exact 一行」并可在终端 CR 覆写下露出路径状文本。 |
| 根因 | CLI 已承认应对非稳定 code 做 fail-closed（故有 `\n` 闸），但闸门未覆盖控制字符与非 token 形态。 |
| 应遵循 | 任务书 §4.4「仅其 stable `error.code + "\n"`」；stderr 禁路径。 |
| 实现者覆盖 | 无 hostile code（`\n`/`\r`/controls）单测。 |
| 分级 | **P1** |

### [P2] P2-1 — 已存在的 `\n` code 闸无回归测

生产 L304 已拒 `"\n" in code`，但 unit 从未断言 `FormalPaperBootstrapError("X\nY")`→`RUNTIME_FAILED` 且 stdout 0B。与 P1-2 同源测试债。

### 无 P0

---

## 4. 实现者未使用的静态对抗反例

### AE-1 — 业务段 `SystemExit` 路径型 code（优先：argparse/SystemExit 泄漏族）

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现者覆盖 parse 期 help/usage→稳定 INPUT，以及普通 `Exception`→RUNTIME。未覆盖：owned seam 在 bootstrap/reopen/verify 内 `raise SystemExit(r"C:\secret\root\config.toml")` 或 `raise SystemExit("usage: ...")`。 |
| 根因 | P1-1。 |
| 最小复现（静态，未执行） | `_install_owned_seam` 令 `bootstrap_fn` raise `SystemExit(r"C:\secret\config.toml")`；`main(_argv(abs_config, mode="initialize"))`。**按现码**：异常穿出 `main`，调用方/`__main__` 见到非 3 的 SystemExit，且**不会**出现唯一 stderr 行 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n`。对照：同缝 `RuntimeError(同路径)` 已被测为 RUNTIME 脱敏。 |
| 通过条件 | 业务段将意外 `SystemExit`（保留 KeyboardInterrupt/GeneratorExit）归一 RUNTIME/3、stdout 0B、stderr 仅稳定码；新增 unit。 |
| 分级 | **P1-1** |

### AE-2 — hostile `error.code` 含 `\r` + 路径（优先：hostile control text）

| 字段 | 内容 |
| --- | --- |
| 现象 | 实现者测稳定 public code 透传与未知异常脱敏；生产拒 `\n` 但**未测**。未覆盖：`FormalPaperBootstrapError("PAPER_FORMAL_BOOTSTRAP_STALE\rC:\\secret\\config.toml")`。 |
| 根因 | P1-2。 |
| 最小复现（静态，未执行） | seam raise 上述错误；**按现码**：`type is str` 且 `"\n" not in code` → stderr 写入含 `\r` 与路径的一行（显示可被 CR 拆成伪多行/覆写），exit 3。预期：与空/`\n` 相同，改写为 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n`。 |
| 通过条件 | stable code 门禁至少拒绝 `\r`/C0（或等价 `isascii` + 单 token `^[A-Z0-9_]+$`）；unit 覆盖 `\n` 与 `\r`；stdout 仍 0B。 |
| 分级 | **P1-2** |

（equal-nonidentical capability、Path subclass/symlink leaf 已由实现者覆盖，本轮不重复计 FAIL。）

---

## 5. 五项专项挑战结论

| # | 挑战 | 静态结论 |
| ---: | --- | --- |
| 1 | CLI 是否复制 bootstrap/policy/P2 | **PASS** — 仅调用 public 三元组并投影 identity 字段 |
| 2 | path/env/root/clock 注入绕过 | **诚实 argv PASS**；clock 无注入口；leaf path 门禁在；**红acted 边界**见 P1-1/P1-2 |
| 3 | success JSON 是否泄露 path/account/time/token | **PASS（静态）** — 键集合与禁词测可读 |
| 4 | callable 双侧 impostor / equal-not-identical / TOCTOU | **PASS（静态）** — owned closure + `is` + STALE 测 |
| 5 | initialize 失败 CLI 是否擅自删除/重试；Windows/Gate 超宣称 | **PASS** — 无删除/重试；delivery 明确 UNRUN / Gate OPEN |

---

## 6. 只读 SHA / scope

| 路径 | SHA256 |
| --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `6A2C7CE067B0191B752711483E6FDC3601F94CA323709DC71A8E5A2171D8C846` |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `DA51D93B68B3825835A4005BF395B6C19D54AFA238C782DFC0AD8753C833E2EA` |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `4479FABA70328843C1B80E4A1492DE559A09A96AFC6EB7138A1B22736375D2E9` |
| 交付报告 | `D61411E5C873F106A3C668924D8D0A4F1FA40524EF4A23052146C11731EFFBE0` |
| 任务书 | `E65FCA93E743E087C255A91A5F790A37885EB62ECF962365B55D6B2CD88458F9` |

**actual scope（本轮可见）**

1. `src/quant/execution/run_paper_formal_bootstrap.py`（实现者）
2. `tests/unit/test_run_paper_formal_bootstrap.py`（实现者）
3. `tests/integration/test_run_paper_formal_bootstrap.py`（实现者）
4. `docs/framework/tasks/M4_UA006_R2_FormalBootstrapOperatorCLI任务书.md`（经理；只读核）
5. `docs/framework/deliveries/M4_UA006_R2_FormalBootstrapOperatorCLI交付报告.md`（实现者）
6. 本报告（审查者唯一写入）

未 stage / commit。

---

## 7. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python 业务执行 / pytest / Ruff / mypy / cold / SQLite | **未运行**（审查结论为静态控制流推演） |
| 真实 formal root / PAPER / soak / submit / network | **未运行** |
| stage / commit | **未执行** |
| Windows engineering / UA-M4-006 / Linux Gate | **不声称；本 FAIL 后不得申请 Windows 验证** |

---

## 8. 最小返工建议（审查者不改代码）

1. 业务 `try` 将意外 `SystemExit` 归一为 `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED` / exit 3（勿吞 KeyboardInterrupt/GeneratorExit）；parse 期 help 行为保持。
2. 收紧 `FormalPaperBootstrapError.code` 稳定码门禁：拒 `\n`/`\r`/C0，或要求 ASCII 单 token；失败则 RUNTIME_FAILED。
3. 落地 AE-1/AE-2 unit；并为现有 `\n` 闸补回归（关 P2-1）。
4. 保持 owned callable / fresh `is` / 零 cleanup / 投影脱敏不被放宽。

---

## 9. 结论

**REVIEW_FAIL**

- P0：无
- P1：P1-1（业务 `SystemExit` 逃逸）、P1-2（hostile `error.code` 控制字符）
- P2：P2-1（`\n` 闸无测）

报告路径：`docs/framework/reviews/M4_UA006_R2_FormalBootstrapOperatorCLI独立初验报告.md`

---

## 10. REWORK1_REVIEW（相对 §1–§9 `REVIEW_FAIL`）

日期：2026-08-26<br>
复验角色：同一独立外部初验 Agent（仍只写本报告；未改 production/tests/task/delivery）<br>
授权：任务书 §10 F1–F2 / delivery §8；上文 §0–§9 **`REVIEW_FAIL` 原文保留**，不洗白。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。

### 10.0 裁决

**`REWORK1_REVIEW_PASS`**

无新的 P0 / P1 / P2。F1/F2 与 AE-1/AE-2 / P2-1 静态闭合；保持项（单次 UTC now、callable 真身、config Path、fresh `is`、canonical projection、其它 exit、零清理、exact6）未回退。**仍不得**宣称 Windows engineering validated 或关闭 UA-M4-006 / PAPER / soak / Linux Gate；运行检查全部 **UNRUN**。

### 10.1 F1 — 业务段 `SystemExit` → runtime/3

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| initialize/reopen/verify 升起 `SystemExit` 整码归一 | **满足** | 业务 `try` 显式 `except SystemExit` → `_emit_code(_RUNTIME_CODE)` / `EXIT_RUNTIME`（CLI L330–334）；unit `test_business_systemexit_maps_to_runtime_failed` 三槽位 bootstrap/reopen/verify |
| stdout 0B；stderr exact `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n` | **满足（静态）** | 该分支只 emit runtime 码；测断言 `out==""`、`err==f"{_RUNTIME}\n"`、路径/usage 不出现 |
| 无 `except BaseException` | **满足** | 全文件无 `BaseException` 捕获；顺序为 Input / FormalPaperBootstrapError / `_RuntimeFailed` / `SystemExit` / `Exception` |
| `KeyboardInterrupt` / `GeneratorExit` 不捕获 | **满足** | 二者属 `BaseException` 且非 `SystemExit`/`Exception`，保持穿透 |
| parse 期 help→0 不变 | **满足** | parse 外层 `SystemExit` 仍 `code in (0, None) → EXIT_SUCCESS`（L280–285） |

### 10.2 F2 — stable token verbatim；否则整码 runtime

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 仅 exact nonempty ASCII token：首 `A-Z`，其余 `A-Z0-9_` | **满足** | `_STABLE_PUBLIC_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")`；`_stable_public_error_code` 要求 `type is str`、非空、`isascii()`、`fullmatch`（L38–39, L217–229） |
| 控制/空白/slash/backslash/colon/Unicode/path-like/非 str → 整码 generic runtime | **满足** | `stable is None` 时只 emit `_RUNTIME_CODE`（L320–324）；从不 strip/改写后写出 |
| 禁止部分消毒 | **满足** | helper 返回 `None` 或原串 verbatim；无中间态 emit |
| 对抗测 | **满足** | `test_hostile_*`（`\n`/`\r`/TAB/ESC/空白/大小写/digit 前缀/`/`/`\`/`:`/path/Unicode/空）；`test_non_str_*`；helper 单测含 `\n`/`\r`（关 P2-1）；合法 `PAPER_FORMAL_BOOTSTRAP_*` 既有测仍 verbatim |

### 10.3 保持项复核（未放宽）

| 项 | 结论 |
| --- | --- |
| 单次 `_canonical_utc_now()` / same-now 传入 bootstrap\|reopen→verify | **保持**（L294–311） |
| owned callable `is`/`__code__`/`partial`/`__wrapped__` | **保持**（L79–132） |
| exact concrete absolute regular config `Path`；拒 subclass/symlink·reparse | **保持**（L142–160） |
| fresh verifier `verified is capability` | **保持**（L312–313） |
| canonical 18 键投影 + `canonical_json_bytes` + 末尾 LF | **保持**（L175–210） |
| exit 0/2 表；失败 stdout 0B；零 cleanup/retry/submit/soak | **保持**（无 shutil/rmtree；Input/help 路径未改） |
| exact6 dirty；HEAD == `27d42840…`；integration SHA 相对首轮未变 | **保持**（见 §10.4） |

### 10.4 本轮现场 SHA（只读核）

| 路径 | SHA256 | 相对首轮 §6 |
| --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `A36A53F236907B15F19B0C9BEA19734810E7D3B785EF060E3626756BDB5DD0E8` | 变更（F1/F2） |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `4A86D221028B808AAE5984FA08A8DEC5D7AB94B2342CB5E74E4BBA54C9CF9530` | 变更（AE-1/AE-2） |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `4479FABA70328843C1B80E4A1492DE559A09A96AFC6EB7138A1B22736375D2E9` | **不变** |
| 任务书（含 §10） | `14572420C2950124B7BEB16803AE18938727E0CD812497C2B8FB4DDC87E8139A` | 变更（F1/F2 冻结） |
| 交付（含 §8） | `3F999686DE9DC143E8868363CA64E71C17033A6C0C85C5DD11BCFE3C4DB6E255` | 变更（REWORK1） |

### 10.5 未运行 / 不超宣称

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network | **未运行** |
| stage / commit | **未执行** |
| Windows VALIDATION / UA-M4-006 / soak / Linux Gate | **仍 OPEN；本 PASS 仅静态合同闭合，可支持随后申请 Windows 序列，不等于已绿** |

### 10.6 收口

**`REWORK1_REVIEW_PASS`**

首轮 §1/§9 `REVIEW_FAIL`（P1-1/P1-2/P2-1）保留作审计链。返工后 F1/F2 静态满足；无残留 P0/P1/P2。下一步仅可按任务书 §7 申请 Windows fixture 验证；不得宣称 `FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED` 直至该序列实际通过。

---

## 11. REWORK2_REVIEW（VALIDATION1 unit fixture；相对 §10 `REWORK1_REVIEW_PASS`）

日期：2026-08-26<br>
复验角色：同一独立外部初验 Agent（RUNTIME_RECOVERY：补全先前仅改表头、未写 §11 的中断轮；仍只写本报告；未改 production/tests/task/delivery）<br>
授权：任务书 §11 / delivery §9<br>
上文 §0–§9 `REVIEW_FAIL` 与 §10 `REWORK1_REVIEW_PASS` **原文保留**，不洗白。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O / PAPER / network / stage / commit。

### 11.0 裁决

**`REWORK2_REVIEW_PASS`**

无新的 P0 / P1 / P2。unit fallback 已改为 `stat.S_IFLNK | stat.S_IMODE(info.st_mode)`；真实 symlink 分支、target exact 匹配、INPUT/2、stdout 0B、路径脱敏均保留；production / integration SHA 相对 §10.4 **冻结**；实现者本轮写集为 unit + delivery；经理任务书仅增 §11 授权（实现者未改 production guard / 异常归一）。VALIDATION1 历史诚实保留为 **`58 passed / 1 failed`**，后续阶段 **UNRUN**。**不得**把 58 绿或本静态 PASS 冒充 VALIDATION1/2 整包或 Windows engineering validated。

### 11.1 Fixture 修正核对

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| fallback mode = `stat.S_IFLNK \| stat.S_IMODE(info.st_mode)`（或严格等价） | **满足** | `tests/unit/test_run_paper_formal_bootstrap.py` L281；注释说明 Windows 上 `stat.S_IFMT` 为函数不可作位掩码（L279–280） |
| 无 `~stat.S_IFMT` / 把 `S_IFMT` 当掩码 | **满足** | unit 仅注释提及 `S_IFMT`；可执行构造不再使用 |
| target-path exact 匹配（`normcase` + `fspath`） | **满足** | L276–277；非目标 path 原样返回 `info` |
| 真实 symlink 正向分支保留 | **满足** | L261–269：`symlink_to` 成功则 `target=link.absolute()`，不走 fallback |
| 断言 exit 2 / stdout 0B / stderr exact input / 不泄露 target | **满足** | L288–291：`EXIT_INPUT`、`out==""`、`err==f"{_INPUT}\n"`、`str(target) not in err` |
| 未改 production config guard / 异常归一迁就 fixture | **满足** | production SHA == §10.4；`_require_exact_config_path` / `_is_link_or_reparse` / 业务 `except Exception` 未为本 fixture 放宽 |

### 11.2 冻结范围与 delivery 诚实性

| 路径 | 本轮 SHA256 | 相对 §10.4 | 结论 |
| --- | --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `A36A53F236907B15F19B0C9BEA19734810E7D3B785EF060E3626756BDB5DD0E8` | **相同** | production 冻结 |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `4479FABA70328843C1B80E4A1492DE559A09A96AFC6EB7138A1B22736375D2E9` | **相同** | integration 冻结 |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `C565ECBEA01458B095391AFAC78C71FFC193D5BD83E97B3DD1CC66F38D210C3D` | 变更 | 仅允许的 fixture 修正 |
| 交付（含 §9） | `21554E1B28A52CB829C0D4E9A2E9B0F88DDE7A3D1B4E0E7A851C987E73A856EC` | 变更 | 实现者 delivery |
| 任务书（含 §11） | `46FFC37DFD88DBF5418E76A1CF2091E0BFFFF94B34269120CBFEA37DC79DD2F6` | 相对 §10.4 变更 | 经理授权节；实现者未改 production/integration |

delivery §9 写「任务书只读未改」按**实现者写集**解读为未改任务书；经理侧 §11 为授权增量，与任务书「任务书由经理维护；实现者只改 unit+delivery」一致。production/integration 冻结证据为 SHA 逐字相等。

### 11.3 VALIDATION1 历史边界（强制保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS（delivery/任务书记录） |
| unit | **`58 passed / 1 failed`**（`test_symlink_or_reparse_config_is_input_invalid`；首失败 STOP） |
| integration | **UNRUN** |
| Ruff / mypy / cold / scope | **UNRUN** |
| 证据根 | `artifacts/agent_runs/m4-ua006-r2-validation1-20260826T2203/` |

本失败定性为 **test-only fixture**（Windows `S_IFMT` 函数误用），不构成 production 回归，也**不**构成 VALIDATION1 整包 PASS。

### 11.4 未运行 / 不超宣称

| 项 | 状态 |
| --- | --- |
| 本审查 Python / pytest / Ruff / mypy / cold / SQLite / 真实 I/O | **未运行** |
| stage / commit | **未执行** |
| VALIDATION2 / Windows engineering validated | **未跑；不得宣称** |
| UA-M4-006 / PAPER / soak / Linux Gate | **仍 OPEN** |

### 11.5 收口

**`REWORK2_REVIEW_PASS`**

§0–§10 历史保留。fixture 合同静态闭合后，下一步须按任务书 §11 **从 identity 起完整重跑 VALIDATION2**；禁止沿用 VALIDATION1 的 58 个通过节点冒充整包绿。

---

## 12. REWORK3_REVIEW（VALIDATION2 integration identity；相对 §11 `REWORK2_REVIEW_PASS`）

日期：2026-08-27<br>
复验角色：同一独立外部初验 Agent（仍只写本报告；未改 production/tests/task/delivery）<br>
授权：任务书 §12 / delivery §10<br>
上文 §0–§11 历史（含 `REVIEW_FAIL` / REWORK1–2 PASS）**原文保留**，不洗白。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。

### 12.0 裁决

**`REWORK3_REVIEW_PASS`**

无新的 P0 / P1 / P2。integration 已将 `bootstrap_identity` 正确降为 per-verification/time-bound：仍为必需输出且须 canonical lowercase 64-hex；四次 fresh identity 互异；跨调用 durable 闭包只排除该字段（`mode` 按调用语义单独 exact）；其余 durable 字段 / key 集合 / schema / 脱敏 / `barrier_epoch` / `execution_store_identity` / 真实 public 链保持严格比较；同次 capability 相等仍由冻结 unit seam 负责。production / unit SHA 相对 §11.2 **冻结**；实现者写集为 integration + delivery；经理任务书仅增 §12。VALIDATION2 历史诚实：identity PASS、unit **`59 passed`**、integration **`5 passed / 1 failed`**、后续 **UNRUN**。**不得**继承部分绿为整包 PASS；须另起完整 VALIDATION3。

### 12.1 合同核对

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| `bootstrap_identity` 仍为 CLI 必需字段 | **满足** | production `_RESULT_KEYS` / `_project_identity` 仍含该键（CLI L45, L186）；integration `_RESULT_KEYS` 含之；未删字段 |
| canonical lowercase 64-hex | **满足** | `_assert_canonical_bootstrap_identity`：`type is str`、`len==64`、`==lower()`、字符∈`0123456789abcdef`（integration L188–195）；四枚 identity 均经此闸 |
| per-verification / time-bound（非跨 reopen durable） | **满足（静态）** | public `_identity_payload` 含 `verified_at` 且 `bootstrap_identity=_sha256(payload)`（`paper_formal_bootstrap` L201–211, L934–962）；integration 不再跨调用 `bi` 逐字相等 |
| 四次 fresh identity 互异 | **满足** | CLI initialize → public reopen → CLI reopen → public reopen 收集四串；`len(set(fresh_identities))==4`（L355–361） |
| 跨调用 durable 只排除 `bootstrap_identity`；`mode` 单独 exact | **满足** | `_DURABLE_IDENTITY_KEYS = _RESULT_KEYS - {bootstrap_identity, mode}`（L65–67）；`_durable_identity_projection` 跨 CLI init/reopen 相等（L337–339）；`mode` 分别断言 `initialize`/`reopen`（L292, L333） |
| 其余 durable / key / schema / barrier_epoch / execution_store / 脱敏 | **满足** | `_assert_projection` 仍逐字段比 durable（L223–244）；显式 `barrier_epoch` / `execution_store_identity`（L340–343）；禁 `verified_at`/`account_id`/`config_path`/绝对路径（L245–247, L296–299, L344–345） |
| 真实 public 链 | **满足** | 仍调用 `reopen_verified_formal_paper_runtime` + `verify_existing_…` 且 `verified is capability`（L305–311, L348–354） |
| 同次 capability `bootstrap_identity` 相等（unit 责任） | **满足（冻结）** | unit `test_success_projection_exact_keys_and_no_secrets`：同一 capability 经 verify 返回后 `payload["bootstrap_identity"]=="b"*64`（unit L525–548）；unit SHA 未改 |
| 未改 production identity 算法 / 未暴露 `verified_at` | **满足** | production SHA == §11.2；CLI 投影仍无 `verified_at` |

### 12.2 冻结范围与 delivery 诚实性

| 路径 | 本轮 SHA256 | 相对 §11.2 | 结论 |
| --- | --- | --- | --- |
| `src/quant/execution/run_paper_formal_bootstrap.py` | `A36A53F236907B15F19B0C9BEA19734810E7D3B785EF060E3626756BDB5DD0E8` | **相同** | production 冻结 |
| `tests/unit/test_run_paper_formal_bootstrap.py` | `C565ECBEA01458B095391AFAC78C71FFC193D5BD83E97B3DD1CC66F38D210C3D` | **相同** | unit 冻结 |
| `tests/integration/test_run_paper_formal_bootstrap.py` | `002DFE34A649D9B4EEEFDEB5D63A6EA6674FA6F5B48E0CFFA7DFC2F308B91F81` | 变更 | 仅允许的 identity 合同修正 |
| 交付（含 §10） | `921FF6790CD6517C9446C9EEFCE2924D154D9DE00CCF6C7D11D3BB99F6D7DD0F` | 变更 | 实现者 delivery |
| 任务书（含 §12） | `1759006DF524285919CE8A9C3C3325CCA1C5AFDF50D17BE9236566F9A5BE2685` | 相对 §11.2 变更 | 经理授权节 |

delivery §10 写「任务书只读未改」按实现者写集解读；经理 §12 为授权增量，与「实现者只改 integration+delivery」一致。production/unit 冻结为 SHA 逐字相等。

### 12.3 VALIDATION2 历史边界（强制保留）

| 阶段 | 结果 |
| --- | --- |
| identity | PASS |
| unit | **`59 passed`** |
| integration | **`5 passed / 1 failed`**（`test_cli_public_initialize_and_reopen_identity_projection`；首失败 STOP） |
| Ruff / mypy / cold / scope | **UNRUN** |
| 证据根 | `artifacts/agent_runs/m4-ua006-r2-validation2-20260827T033820Z/` |
| integration stdout SHA256 | `EC1ECFEBB0B43179056F7DE3164DC2DB6965E9DB9F402640A865D5F4EA1DBBF9` |
| summary SHA256 | `A9FF402C39B5B7F6749ECFC25013EFBBBC009A41AB20E7412C0227EA9CE8B8A3` |

本失败定性为 **integration 断言误把 time-bound `bootstrap_identity` 当 durable**，不构成 production 回归，也**不**构成 VALIDATION2 整包 PASS。

### 12.4 未运行 / 不超宣称

| 项 | 状态 |
| --- | --- |
| 本审查 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network | **未运行** |
| stage / commit | **未执行** |
| VALIDATION3 / Windows engineering validated | **未跑；不得宣称；不得继承 VALIDATION2 部分绿** |
| UA-M4-006 / PAPER / soak / Linux Gate | **仍 OPEN** |

### 12.5 收口

**`REWORK3_REVIEW_PASS`**

§0–§11 历史保留。identity 合同静态闭合后，下一步须按任务书 §12 / delivery §10.3 **从 identity 起完整重跑 VALIDATION3**；禁止沿用 VALIDATION2 的 unit 59 绿或 integration 5 绿冒充整包。

---

## 13. REWORK4_REVIEW（VALIDATION3 完整 TIME_BOUND/DURABLE 分组；相对 §12 `REWORK3_REVIEW_PASS`）

日期：2026-08-27<br>
复验角色：同一独立外部初验 Agent（仍只写本报告；未改 production/tests/task/delivery）<br>
授权：任务书 §13 / delivery §11<br>
上文 §0–§12 历史（含 `REVIEW_FAIL` / REWORK1–3 PASS / §12 不完整规则失败史）**原文保留**；§13 取代「跨调用只排除 `bootstrap_identity`」，不洗白既往失败。<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / SQLite / PAPER / network / stage / commit。

### 13.0 裁决

**`REWORK4_REVIEW_PASS`**

