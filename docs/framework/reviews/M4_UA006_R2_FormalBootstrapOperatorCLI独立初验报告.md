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
