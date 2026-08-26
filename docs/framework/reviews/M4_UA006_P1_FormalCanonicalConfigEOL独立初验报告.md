# M4-UA006-P1 Formal Canonical Config EOL 独立初验报告

日期：2026-08-26<br>
状态：`REVIEW_PASS`（§0–§8 历史保留）+ `EVIDENCE_REVIEW_PASS / EVIDENCE_REVIEW_ONLY` + 上限 `FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`；**UA-M4-006 仍 OPEN**<br>
task id：`M4-UA006-P1-FORMAL-CONFIG-EOL`<br>
exact base / HEAD：`eca54af513078ca6d000feb544329cba69797948`<br>
branch：`codex/m4-ua006-p1-formal-config-eol`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p1-formal-config-eol`<br>
审查角色：同一独立初验者 · `EVIDENCE_REVIEW_ONLY`（未参与实现；未委派；未创建 subagent）<br>
方法：本轮只读核对 VALIDATION1 证据树 / 任务书 §7 / 交付 §5–§8；零 Python / pytest / Ruff / mypy / cold / stage / commit<br>
唯一写路径：本报告（exact8 #8）；`.gitattributes` / configs / tests / 任务书 / 交付 **只读**

任务书：`docs/framework/tasks/M4_UA006_P1_FormalCanonicalConfigEOL任务书.md`<br>
交付：`docs/framework/deliveries/M4_UA006_P1_FormalCanonicalConfigEOL交付报告.md`<br>
VALIDATION1：`artifacts/agent_runs/m4-ua006-p1-validation1-20260826T111408798Z`

---

## 0. 裁决

**`REVIEW_PASS`**

exact8 范围内：`.gitattributes` 仅为两 formal TOML 精确路径冻结 `text eol=lf`；两配置工作树 raw bytes 与 base/index blob 一致且 LF-only、恰一末尾 LF、无 BOM；测试真实读取版本化 source 并与模块既有 `_render_canonical` 逐字相等；CRLF/BOM/额外 LF 经公共 loader fail-closed；未放宽 renderer、未改 loader、未见配置语义漂移。实现者披露的开工前一次只读 `python -c` 记为 STATIC_ONLY **流程偏差**，本审查**不**采信为验证证据，亦未见产品字节/资源污染迹象（详见 §4）。

本裁决**不**授权声称 Windows 验证或任何 Gate 完成。

---

## 1. 范围与只读证据

| 项 | 静态结论 |
| --- | --- |
| `AGENTS.md`（worktree / 父树规则） | 已读；服从 STATIC_ONLY、职责分离、不自宣 Gate、配置 SSOT |
| dirty / untracked | `.gitattributes`；两 TOML；两 tests；交付 ??；任务书 ??；本报告（写后） |
| cached | 0 |
| `git diff --check` | PASS（无输出） |
| HEAD | = exact base `eca54af…7948` |
| production loaders | `paper_policy.py` / `paper_account.py` **无** dirty；未改 renderer/compare |
| 越界写 | **无**（bootstrap / `__init__.py` / 其他 config/test / roadmap 未见） |

说明：两 TOML 在 `git status` 可标 `M`，但 `git diff`/`git diff --name-only HEAD` **无内容 hunk**；`git hash-object --no-filters` = index = 任务书冻结 blob。属任务书/交付允许的 exact8 dirty（属性/stat 刷新），**非**语义漂移。

---

## 2. 逐项静态核验矩阵

| # | 合同项 | 结论 | 关键证据 |
| --- | --- | --- | --- |
| A | `.gitattributes` 仅两精确路径 `text eol=lf`，无 `configs/**` 宽规则 | **满足** | `.gitattributes` L11–13；既有 research/script 规则未扩到 trading 通配 |
| B | `git check-attr text eol` → `text: set`、`eol: lf` | **满足** | 两路径静态查询均为 set / lf |
| C | policy index/working blob = `2984975e42522bea2b19ba37ec603c414b30d263` | **满足** | `git rev-parse :…` 与 `hash-object --no-filters` 同左；size=1881 |
| D | account index/working blob = `83dba597d500697f33fe0addac9b9632394e2b89` | **满足** | 同上；size=449 |
| E | 工作树 CR=0、无 BOM、恰一末尾 LF、无双 `\n\n` | **满足** | PowerShell 原始字节：policy/account CR count=0；不以 `EF BB BF` 起；尾字节 `…0A`；非双 LF |
| F | 配置字段/顺序/数值/注释相对 base blob 逐字不变 | **满足** | content diff 空；blob SHA 未变 → 仅允许的 EOL 物化恢复，无语义变更 |
| G | 真实版本化 source ↔ 模块 `_render_canonical` 逐字相等；不复制 renderer / 不手写 expected | **满足** | `FORMAL_POLICY`/`FORMAL_ACCOUNT` 指向仓库 `configs/trading/...`；`assert text == module._render_canonical(tomllib.loads(...))` |
| H | source bytes 锁定无 `\r` / 无 BOM / 恰一尾 `\n` | **满足** | 两 `test_versioned_formal_*_source_bytes_match_canonical_renderer` |
| I | 复制后 CRLF / BOM / 额外 `\n` 经**公共** loader fail-closed | **满足** | 参数化 mutate → `_project` → `_load` → `PAPER_*_SOURCE_INVALID`；loader 既有 `text != _render_canonical`（`paper_policy.py` L451–452；`paper_account.py` L523–524） |
| J | 不 monkeypatch canonical compare / renderer / source read | **满足** | 新测仅复用既有 `_allow_formal_runtime` / `_allow_fresh`（fresh/binding），未 patch `_render_canonical` 或 compare |
| K | 不放宽 renderer；不改配置值 | **满足** | production 无 diff；blob SHA 冻结 |
| L | 既有合法 load/verify/selector/identity/语义测保留 | **满足（静态）** | 新测插入既有套件之前；未见删除/改写既有正向合同测体 |

---

## 3. 实现者未使用的静态对抗反例

### AE-1 — 去掉唯一末尾 LF（实现者仅测“额外 `\n`”）

- **最小复现（静态，未执行）**：`raw = FORMAL_*.read_bytes()[:-1]`（canonical 文件本以单一 `\n` 终止）→ 写入 `_project` → 调用公共 `_load`。
- **预期**：`tomllib.loads` 仍可能成功解析；但 `_render_canonical` 经 `"\n".join(lines)` **恒以 `\n` 终止**（account：`paper_account.py` L626–647；policy 同模式），故 `text != _render_canonical(document)` → 稳定 `PAPER_*_SOURCE_INVALID`。
- **对照**：实现者参数化仅有 `raw + b"\n"`（额外终止），**未**覆盖缺失终止 LF；与任务书“仅改变末尾换行数量”的另一侧对称。
- **用途**：证明 fail-closed 不依赖“多一行”这一单侧，且**不得**先 normalize 补 `\n` 再接受。

### AE-2 — 仅末行 CRLF、正文仍 LF（部分 EOL 污染）

- **最小复现（静态，未执行）**：`raw = FORMAL_*.read_bytes()[:-1] + b"\r\n"`（非整文件 `replace(b"\n", b"\r\n")`）。
- **预期**：decode 文本含 `\r`，不等于 LF-only canonical → 公共 loader 拒绝。
- **对照**：实现者覆盖整文件 CRLF；未单测“仅末行”局部污染。静态上同一 compare 闸门应拒绝；建议 Windows 验证阶段可顺带纳入，但**不**构成当前 FAIL。

---

## 4. 交付披露的 STATIC_ONLY 违反（强制记录）

| 字段 | 内容 |
| --- | --- |
| 披露来源 | 交付报告 §5：「偶然：开工前一次只读 `python -c` 统计工作树 CR/LF；不构成验收证据。」 |
| 性质判断 | **流程偏差**（违反本包 `STATIC_ONLY` 零 Python 约束），**非**产品验收手段 |
| 是否形成产品验证 | **否**。本审查独立用 `git hash-object --no-filters` / `check-attr` / 原始字节读取核对；**绝不**把该 `python -c` 当作 blob/EOL/loader 证据 |
| 是否字节污染 | **未见迹象**。披露为只读统计；当前 working raw blob 仍精确等于 base index 冻结 SHA |
| 是否资源污染 | **未见迹象**。无常驻进程/网络/PAPER/临时验证产物被本审查采信为依赖 |
| 计分 | **不**单独构成 `REVIEW_FAIL`；**不得隐瞒**；**不得洗白为已验证** |

---

## 5. 发现分级

### 无 P0 / P1 / P2

无阻断合同缺陷。AE-1/AE-2 为实现者未覆盖的静态对抗面，由既有 `text != _render_canonical` 闸门静态闭合；建议后续授权运行验证时可增测 AE-1，非本 STATIC 包返工条件。

---

## 6. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| 网络 / 真实 PAPER / soak | **未运行** |
| stage / commit | **未执行** |
| Windows 验证 / 主验 / Linux Gate / UA-M4-006 | **不声称** |

---

## 7. 结论

**REVIEW_PASS**

合同 A–L 静态满足；dirty ⊆ exact8；cached=0；两 formal TOML raw blob 与冻结 SHA 一致；测试合同与 fail-closed 路径静态对齐。实现者 `python -c` 仅记流程偏差。下一步仅可申请任务书规定的 **Windows 验证**，不得解读为本包已关闭 UA006 或 Linux Gate。

报告路径：`docs/framework/reviews/M4_UA006_P1_FormalCanonicalConfigEOL独立初验报告.md`

---

## 8. 报告 SHA256（STATIC 初验历史指纹；保留）

`15e5552f08b237d3af241af59125b1e5ab29158fd5a0a9e3e59f07f3ce26bd81`

口径（历史）：对本文件「§8 标题行之前」全部 UTF-8 字节（LF-only）计算 SHA-256；指纹行与本节正文不计入哈希。后续 EVIDENCE 追加不改写该历史指纹语义。

---

## 9. EVIDENCE_REVIEW（VALIDATION1 / 2026-08-26）

### 9.0 范围

只读：任务书 §7（含流程偏差与 VALIDATION1 陈述）、交付 §5–§8、evidence root 原生产物与 `runner.ps1`。本轮**未**重跑 pytest/Ruff/mypy/cold；**未**改 `.gitattributes`/configs/tests/task/delivery。

### 9.1 裁决

**`EVIDENCE_REVIEW_PASS`**

交付/任务书 VALIDATION1 陈述与磁盘证据根、exit、stdout 关键 SHA、scope 闭包一致；未把实现期只读 `python -c` 采信为证据；未过度声明 Gate；**UA-M4-006 仍 OPEN**。本包上限仅 `FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`。

### 9.2 关键 root / SHA / exit

evidence root（相对 worktree）：`artifacts/agent_runs/m4-ua006-p1-validation1-20260826T111408798Z`（与任务书 §7.2 / 交付 §8 一致）。

| 产物 | 交付声称 SHA-256 | 磁盘实测（stdout/summary） | exit | 结论 |
| --- | --- | --- | --- | --- |
| focused `02-focused.stdout.log` | `8a96851b…d399` | **一致** | 0 | PASS |
| Ruff `03-ruff.stdout.log` | `82b3e6a6…4f18` | **一致** | 0 | PASS |
| mypy `04-mypy.stdout.log` | `0c37c415…56c2` | **一致** | 0 | PASS |
| cold `05-cold.stdout.log` | `a84f0784…0c18` | **一致** | 0 | PASS |
| scope `09-scope.stdout.log` | `3013556c…0a4c` | **一致** | 0 | PASS |
| summary `stage-summary.log` | `abc96b77…2f1a` | **一致** | — | PASS |

旁证：`00-parser`…`09-scope` 全部 exit=0；各阶段 stderr 长度均为 0；summary 无 `STOP=`；`TEMP_CLEANUP=PASS` + `RESOURCE_RELEASE`。

### 9.3 合同项 ↔ 原生日志

| 检查 | 交付/任务书陈述 | 证据 | 结论 |
| --- | --- | --- | --- |
| Parser / identity | PASS | `00-parser.stdout`：`PARSER_ERRORS=0`；`01-identity.stdout`：`IDENTITY_PASS` + worktree 内 `quant`/`paper_policy`/`paper_account` | **满足** |
| focused 两 test 文件 | `72 passed` / `2 skipped` | `02-focused.stdout` 末行原文；`runner.ps1` 仅跑 `test_paper_policy.py` + `test_paper_account.py` | **满足** |
| Ruff 两 tests | PASS | stdout `All checks passed!`；runner 仅两 test 路径 `--no-cache` | **满足** |
| mypy production2 | PASS | stdout `Success: no issues found in 2 source files`；目标 `paper_policy.py` + `paper_account.py` | **满足** |
| cold | PASS | `COLD_IMPORT_PASS` + 两 loader 路径落在本 worktree | **满足** |
| exact8 Unicode scope | PASS | `core.quotePath=false` + `-z` NUL 路径；`ACTUAL_COUNT=8`；approved 含中文任务/交付/审查文件名；8 路径均 ∈ exact8 | **满足** |
| 两 config LF / 无 BOM / 单末尾 LF / raw=原 index blob | PASS | runner：CR/BOM/尾 `0x0A` 闸 + `hash-object --no-filters` 与 `HEAD:` 均等于冻结 `2984975e…` / `83dba597…`；scope `CONFIG_BYTES=PASS` | **满足** |
| cached=0 / diff-check / temp / process | PASS | cached stdout 空；diff-check exit0；scope `CACHED_COUNT=0`/`DIFF_CHECK=PASS`；无 worktree `.pytest_cache`/`.mypy_cache` 等；`PROCESS_RESIDUE=0`；evidence 下 `basetemp`/`mypy-cache` 已清理 | **满足** |
| `0xF00` residue / writer | 无 residue；PID `7692` / `0x3` 不变 | runner：排除自身后无其他 `ProcessorAffinity==0xF00`；`Get-Process 7692` 要求 affinity `0x3` + BelowNormal；scope 通过 | **满足（历史现场）** |

### 9.4 实现期只读 `python -c`（继续强制）

| 字段 | 本轮结论 |
| --- | --- |
| 任务书 §7.1 / 交付 §5 | 仍记为偏离冻结 `STATIC_ONLY` 的**流程偏差** |
| 采信 | **继续不采信**为 VALIDATION1 / 初验 / Gate 证据 |
| 正式证据 | 仅本 §9 核对之 VALIDATION1 产物 |
| 污染 | 无新迹象把该调用洗入 focused/Ruff/mypy/cold/scope SHA |

### 9.5 过度声明检查

| 声明面 | 结论 |
| --- | --- |
| 状态上限 | 任务书/交付均为 `FORMAL_CONFIG_EOL_WINDOWS_VALIDATED` |
| `UA-M4-006` | 明确 **仍 OPEN**（任务书文首、§7.2；交付文首、§8 收口） |
| Linux Gate / 主验合流 / bootstrap 关闭 / PAPER/soak | 文首显式排除；未见反向关闭声明 |
| 本审查 | **不**声称主验、合流、UA006 关闭或 Linux Gate |

### 9.6 本轮审查边界

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold（本审查会话） | **未运行** |
| stage / commit | **未执行** |
| 对实现产物的写 | **无**（仅本报告） |

---

## 10. EVIDENCE_REVIEW 报告 SHA256

`3c82449e21bbdfc3bc990ef0d091d935af67a685b92ff8b8ef79b0c7fe461809`

口径：对本文件「§10 标题行之前」全部 UTF-8 字节（LF-only；含 §0–§9 与 §8 历史指纹段；**不含**本 §10 块）计算 SHA-256。

---

## 11. DOC_REVIEW（delivery L23–25 行尾空白规范化 / 2026-08-26）

**`DOC_REVIEW_PASS`**

只读核对：任务书 / 交付 / 本审查报告三文档 trailing whitespace=0、LF-only、恰一 EOF 换行；交付第 23–25 行由尾随双空格硬换行改为单行列表项，语义与 VALIDATION1 证据/SHA 文本/状态边界（`FORMAL_CONFIG_EOL_WINDOWS_VALIDATED`；**UA-M4-006 仍 OPEN**）未漂移。`.gitattributes`/configs/tests 本轮只读未改。§8 / §10 历史指纹保留不重算。本审查零 Python / 未 stage / 未 commit。

---

## 12. DOC_REVIEW 报告 SHA256

`2730a0b6a5d9fb7942484b1d6c8917a6825648462d67541b72e99ef637514777`

口径：对本文件「§12 标题行之前」全部 UTF-8 字节（LF-only；含 §0–§11 与 §8/§10 历史指纹段；**不含**本 §12 块）计算 SHA-256。历史 §8/§10 指纹正文未改写。
