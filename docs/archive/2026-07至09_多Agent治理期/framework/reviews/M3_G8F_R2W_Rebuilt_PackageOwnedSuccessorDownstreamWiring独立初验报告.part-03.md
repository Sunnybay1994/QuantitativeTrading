## 18. EVIDENCE_REVIEW（对照 taskbook §20 / delivery §18）

日期：2026-08-26<br>
身份：与首轮/REWORK1/F4–F12 同一独立初验者；未参与实现<br>
范围：只读 taskbook §20、delivery §18、retained VALIDATION10/11/12 证据根与报告 SHA；exact12 dirty/scope；组合边界<br>
本轮唯一写入：本报告<br>
STATIC_ONLY：零 Python / pytest / Ruff / mypy / cold / network / stage / commit

### 18.1 证据根存在性与组合口径

| 验证 | 证据根 | 组合口径（task/delivery 陈述 ↔ 留存日志） |
| --- | --- | --- |
| VALIDATION10 | `artifacts/agent_runs/m3-r2w-rebuilt-validation10-20260826T080935Z/` | unit **84 PASS** → integration **42 PASS** → Ruff **PASS** → mypy **21 STOP**；cold/scope **UNRUN** |
| VALIDATION11 | `artifacts/agent_runs/m3-r2w-rebuilt-validation11-20260826T173000Z-b72c/` | identity **PASS** → unit **57 PASS** → integration **29 PASS** → Ruff **PASS** → mypy **1 STOP**；cold/scope **UNRUN** |
| VALIDATION12 | `artifacts/agent_runs/m3-r2w-rebuilt-validation12-20260826T180000Z-c18d/` | identity **PASS** → Ruff（changed）**PASS** → mypy production3 **PASS** → cold production3 **PASS** → exact12 scope **PASS**；`reused_validation11=unit57_integration29_other_ruff` |

**无矛盾：** V10/V11 的 mypy STOP 在组合表中仍如实保留，未被改称为 PASS；V12 明确复用 V11 已绿 unit/integration，不重写历史 STOP。

### 18.2 精确 SHA 核对（只读重算）

#### VALIDATION10

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| unit stdout | `7469e724…bd2b5ec` | **MATCH** | `84 passed` |
| integration stdout | `1cda2fd0…c0c721` | **MATCH** | `42 passed` |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | `All checks passed!` |
| mypy stdout | `e539f47c…09b4268` | **MATCH** | `Found 21 errors` |
| stage-summary | `c4986776…ee3c9d6` | **MATCH** | `STOP\|STAGE_FAILED:05-mypy` |

#### VALIDATION11

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| identity stdout | `e153b441…195962a3` | **MATCH** | exit=0 |
| unit stdout | `950b983d…f0cd252c` | **MATCH** | `57 passed` |
| integration stdout | `26493122…b13b2059` | **MATCH** | `29 passed` |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | PASS |
| mypy stdout | `4a4108d5…440475fa2` | **MATCH** | `:214` assignment；`Found 1 error` |
| stage-summary | `034cd671…aac35ae64` | **MATCH** | `unit=57_passed`；`mypy=1_error`；cold/scope=UNRUN |

#### VALIDATION12

| 产物 | 报告 SHA-256 | 重算 | 内容钉 |
| --- | --- | --- | --- |
| Ruff stdout | `af352a86…41d2d9af` | **MATCH** | `All checks passed!`（exit=0） |
| mypy stdout | `f6af9a42…5648259c` | **MATCH** | `Success: no issues found in 3 source files` |
| cold stdout | `30fe42e7…84029023` | **MATCH** | production3 三路径列出；exit=0 |
| scope stdout | `1f4605b9…1408f13f` | **MATCH** | `ACTUAL_COUNT=12`；`CACHED_COUNT=0`；`DIFF_CHECK=PASS`；`CACHE_RESIDUE=0`；`OTHER_0xF00=0` |
| stage-summary | `2e0e2038…89fc06405` | **MATCH** | `classification=PASS`；`reused_validation11=unit57_integration29_other_ruff` |
| identity | （delivery 未单列 SHA；exit=0） | **一致** | stdout SHA=`e153b441…`（与 V11 identity 字节相同）；exit=0 |

### 18.3 exact12 scope / dirty / residue（对照 V12 scope + 当前只读 git）

| 项 | 结论 |
| --- | --- |
| exact12 名单 | scope 列出 12 路径与任务书白名单一致（3 production + 6 tests + task/delivery/review） |
| cached | `CACHED_COUNT=0`；当前 `git diff --cached` 空 |
| diff-check | scope `DIFF_CHECK=PASS`；本审查观察 `git diff --check` PASS |
| residue | `CACHE_RESIDUE=0`；`OTHER_0xF00=0`；`RUNROOT=False` |
| HEAD | `1d9b4e09…` 与任务书 exact base 一致 |

### 18.4 越权声明检查

| 声明面 | 结论 |
| --- | --- |
| delivery 状态行 / §18.3 | 明确 **不**表示 actual worker、真实 Qlib、new root、retained、acceptance、M3 Gate |
| taskbook §20 | 终态上限 `R2W_WINDOWS_ENGINEERING_VALIDATED`；同样排除 worker/Qlib/new root/retained/M3 Gate |
| 组合是否冒充整包 Gate | **否**；历史 mypy STOP 保留；V12 仅 Windows 工程验证组合 |

### 18.5 发现分级

**无 P0/P1。** SHA/计数/STOP 边界与 task§20、delivery§18 无矛盾。

### 18.6 EVIDENCE_REVIEW 结论

**EVIDENCE_REVIEW_PASS**（VALIDATION10/11/12 留存根与报告 SHA 闭合；组合口径合法；exact12/cached0/diff/residue 一致；未越权宣称 worker/Qlib/new root/retained/M3 Gate）。
